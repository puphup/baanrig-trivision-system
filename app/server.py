"""FastAPI application with REST + WebSocket for dual-motor control."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import load_config, save_config
from .modbus_interface import ModbusInterface, SimulatedModbus, RealModbus, TcpModbus
from .motor_sim import MotorSim
from .sequencer import DualMotorSequencer
from .registers import (
    MOTION_STATUS, FEEDBACK_POS_H, FEEDBACK_POS_L,
    FEEDBACK_VEL_H, FEEDBACK_VEL_L, CURRENT_ALARM,
    ESTOP_REG, ESTOP_VAL, SYSTEM_CMD_REG,
    ALARM_RESET_VAL, PERM_SAVE_VAL,
    MODE_RELATIVE, MODE_ABSOLUTE,
    join_32, join_32_signed, pulses_to_degrees,
)

# --- Globals set during lifespan ---
config: dict
modbus: ModbusInterface
sequencer: DualMotorSequencer
motor1: MotorSim | None = None
motor2: MotorSim | None = None
ws_clients: set[WebSocket] = set()
# Software zero offsets per slave ID (in pulses)
zero_offsets: dict[int, int] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global config, modbus, sequencer, motor1, motor2
    config = load_config()

    from .registers import set_pulses_per_rev
    set_pulses_per_rev(
        command_ppr=config["motors"].get("command_ppr", 10000),
        encoder_ppr=config["motors"].get("encoder_ppr", 10000),
    )

    m1_id = config["motors"]["motor1_slave_id"]
    m2_id = config["motors"]["motor2_slave_id"]
    conn = config["connection"]

    if conn["mode"] == "hardware":
        real = RealModbus(
            port=conn["serial_port"],
            baudrate=conn["baudrate"],
            data_bits=conn.get("data_bits", 8),
            parity=conn.get("parity", "none"),
            stop_bits=conn.get("stop_bits", 1),
        )
        await real.connect()
        modbus = real
        motor1 = None
        motor2 = None
    elif conn["mode"] == "tcp":
        tcp = TcpModbus(
            host=conn.get("tcp_host", "192.168.1.100"),
            port=conn.get("tcp_port", 502),
        )
        await tcp.connect()
        modbus = tcp
        motor1 = None
        motor2 = None
    else:
        motor1 = MotorSim(slave_id=m1_id)
        motor2 = MotorSim(slave_id=m2_id)
        modbus = SimulatedModbus({m1_id: motor1, m2_id: motor2})
        motor1.start()
        motor2.start()

    sequencer = DualMotorSequencer(modbus, motor1_id=m1_id, motor2_id=m2_id)

    broadcast_task = asyncio.create_task(_broadcast_loop())
    yield
    broadcast_task.cancel()
    if motor1:
        await motor1.stop()
    if motor2:
        await motor2.stop()
    if isinstance(modbus, (RealModbus, TcpModbus)):
        await modbus.disconnect()


app = FastAPI(lifespan=lifespan)

STATIC_DIR = Path(__file__).parent.parent / "static"


# --- Pydantic models ---

class MoveRequest(BaseModel):
    slave_id: int = 1
    angle_deg: float = 90.0
    speed_rpm: int = 200
    accel: int = 200
    decel: int = 200
    mode: str = "relative"  # "absolute" or "relative"


class MotorParams(BaseModel):
    angle_deg: float = 90.0
    speed_rpm: int = 200
    accel: int = 200
    decel: int = 200


class SequenceRequest(BaseModel):
    m1: MotorParams = MotorParams()
    m2: MotorParams = MotorParams()
    delay_s: float = 1.0
    mode: str = "relative"


class AlarmResetRequest(BaseModel):
    slave_id: int = 1


class HomeRequest(BaseModel):
    slave_id: int = 0  # 0 = both, 1 = motor1, 2 = motor2
    speed_rpm: int = 200
    accel: int = 200
    decel: int = 200


# --- Routes ---

@app.get("/favicon.ico")
async def favicon():
    from fastapi.responses import Response
    # 1x1 transparent PNG
    return Response(content=b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n\xb4\x00\x00\x00\x00IEND\xaeB`\x82', media_type="image/png")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
async def get_status():
    return await _build_status()


@app.post("/api/move")
async def move_motor(req: MoveRequest):
    if sequencer.active:
        return {"error": "Sequence in progress"}

    from .registers import PR0_MODE, PR0_TRIGGER, PR0_TRIGGER_VAL, degrees_to_pulses, split_32
    mode_val = MODE_ABSOLUTE if req.mode == "absolute" else MODE_RELATIVE
    pulses = degrees_to_pulses(req.angle_deg)
    pos_h, pos_l = split_32(pulses)
    await modbus.write_registers(req.slave_id, PR0_MODE, [mode_val, pos_h, pos_l, req.speed_rpm, req.accel, req.decel])
    await modbus.write_registers(req.slave_id, PR0_TRIGGER, [PR0_TRIGGER_VAL])
    return {"ok": True}


@app.post("/api/sequence")
async def run_sequence(req: SequenceRequest):
    if sequencer.active:
        return {"error": "Sequence already running"}

    mode_val = MODE_ABSOLUTE if req.mode == "absolute" else MODE_RELATIVE
    asyncio.create_task(sequencer.run_sequence(
        m1_angle=req.m1.angle_deg, m1_speed=req.m1.speed_rpm, m1_accel=req.m1.accel, m1_decel=req.m1.decel,
        m2_angle=req.m2.angle_deg, m2_speed=req.m2.speed_rpm, m2_accel=req.m2.accel, m2_decel=req.m2.decel,
        delay_s=req.delay_s, mode=mode_val,
    ))
    return {"ok": True}


@app.post("/api/home")
async def home_motor(req: HomeRequest):
    """Move motor(s) to absolute position 0 (home)."""
    if sequencer.active:
        return {"error": "Sequence in progress"}

    from .registers import PR0_MODE, PR0_TRIGGER, PR0_TRIGGER_VAL, split_32

    m1_id = config["motors"]["motor1_slave_id"]
    m2_id = config["motors"]["motor2_slave_id"]
    targets = []
    if req.slave_id == 0:
        targets = [m1_id, m2_id]
    else:
        targets = [req.slave_id]

    for sid in targets:
        # Absolute move to the zero-offset position (user's 0)
        home_pulses = zero_offsets.get(sid, 0)
        pos_h, pos_l = split_32(home_pulses)
        await modbus.write_registers(sid, PR0_MODE, [
            MODE_ABSOLUTE, pos_h, pos_l, req.speed_rpm, req.accel, req.decel
        ])
        await modbus.write_registers(sid, PR0_TRIGGER, [PR0_TRIGGER_VAL])

    return {"ok": True}


@app.post("/api/set-zero")
async def set_zero(req: AlarmResetRequest):
    """Set current position as 0 by storing a software offset."""
    sid = req.slave_id
    m1_id = config["motors"]["motor1_slave_id"]
    m2_id = config["motors"]["motor2_slave_id"]
    targets = [m1_id, m2_id] if sid == 0 else [sid]

    for t in targets:
        if isinstance(modbus, SimulatedModbus) and t in modbus.motors:
            modbus.motors[t].position = 0.0
            zero_offsets[t] = 0
        else:
            # Read current raw position and store as offset
            pos_regs = await modbus.read_holding_registers(t, FEEDBACK_POS_H, 2)
            raw_pulses = join_32_signed(pos_regs[0], pos_regs[1])
            zero_offsets[t] = raw_pulses

    return {"ok": True}


@app.post("/api/estop")
async def estop():
    await sequencer.emergency_stop_all()
    return {"ok": True}


@app.post("/api/alarm-reset")
async def alarm_reset(req: AlarmResetRequest):
    await modbus.write_registers(req.slave_id, SYSTEM_CMD_REG, [ALARM_RESET_VAL])
    return {"ok": True}


@app.post("/api/save")
async def save_params():
    m1_id = config["motors"]["motor1_slave_id"]
    m2_id = config["motors"]["motor2_slave_id"]
    await modbus.write_registers(m1_id, SYSTEM_CMD_REG, [PERM_SAVE_VAL])
    await modbus.write_registers(m2_id, SYSTEM_CMD_REG, [PERM_SAVE_VAL])
    return {"ok": True}


@app.post("/api/enable")
async def enable_motors():
    from .registers import SW_ENABLE_REG, SW_ENABLE_VAL
    m1_id = config["motors"]["motor1_slave_id"]
    m2_id = config["motors"]["motor2_slave_id"]
    await modbus.write_registers(m1_id, SW_ENABLE_REG, [SW_ENABLE_VAL])
    await modbus.write_registers(m2_id, SW_ENABLE_REG, [SW_ENABLE_VAL])
    return {"ok": True}


@app.post("/api/disable")
async def disable_motors():
    from .registers import SW_ENABLE_REG
    m1_id = config["motors"]["motor1_slave_id"]
    m2_id = config["motors"]["motor2_slave_id"]
    await modbus.write_registers(m1_id, SW_ENABLE_REG, [0])
    await modbus.write_registers(m2_id, SW_ENABLE_REG, [0])
    return {"ok": True}


@app.get("/api/ports")
async def list_serial_ports():
    """Detect available serial ports on the system."""
    import glob as g
    import sys
    ports = []
    if sys.platform.startswith("darwin"):
        ports = g.glob("/dev/tty.*") + g.glob("/dev/cu.*")
    elif sys.platform.startswith("linux"):
        ports = g.glob("/dev/ttyUSB*") + g.glob("/dev/ttyACM*") + g.glob("/dev/ttyS*")
    elif sys.platform.startswith("win"):
        ports = [f"COM{i}" for i in range(1, 20)]
    # Filter to only ports that actually exist (Windows COM check)
    ports.sort()
    return {"ports": ports}


@app.post("/api/test-connection")
async def test_connection():
    """Test connection by pinging both motors via the configured protocol."""
    conn = config["connection"]
    m1_id = config["motors"]["motor1_slave_id"]
    m2_id = config["motors"]["motor2_slave_id"]
    mode = conn.get("mode", "simulation")

    if mode == "simulation":
        return {"ok": True, "motors": [
            {"ok": True, "slave_id": m1_id, "status": 0},
            {"ok": True, "slave_id": m2_id, "status": 0},
        ]}

    try:
        if mode == "tcp":
            test_client = TcpModbus(
                host=conn.get("tcp_host", "192.168.1.100"),
                port=conn.get("tcp_port", 502),
            )
            connected = await test_client.connect()
            if not connected:
                return {"ok": False, "error": f"Cannot connect to {conn.get('tcp_host')}:{conn.get('tcp_port')}"}
        else:
            test_client = RealModbus(
                port=conn["serial_port"],
                baudrate=conn["baudrate"],
                data_bits=conn.get("data_bits", 8),
                parity=conn.get("parity", "none"),
                stop_bits=conn.get("stop_bits", 1),
            )
            connected = await test_client.connect()
            if not connected:
                return {"ok": False, "error": f"Cannot open {conn['serial_port']}"}

        results = []
        for sid in [m1_id, m2_id]:
            r = await test_client.test_connection(sid)
            results.append(r)

        await test_client.disconnect()
        all_ok = all(r["ok"] for r in results)
        return {"ok": all_ok, "motors": results}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/debug/{slave_id}")
async def debug_registers(slave_id: int):
    """Read raw register values for debugging."""
    try:
        status = await modbus.read_holding_registers(slave_id, MOTION_STATUS, 1)
        pos = await modbus.read_holding_registers(slave_id, FEEDBACK_POS_H, 2)
        vel = await modbus.read_holding_registers(slave_id, FEEDBACK_VEL_H, 2)
        alarm = await modbus.read_holding_registers(slave_id, CURRENT_ALARM, 1)
        return {
            "status_raw": f"0x{status[0]:04X}",
            "pos_high": f"0x{pos[0]:04X}",
            "pos_low": f"0x{pos[1]:04X}",
            "pos_joined": join_32_signed(pos[0], pos[1]),
            "vel_high": f"0x{vel[0]:04X}",
            "vel_low": f"0x{vel[1]:04X}",
            "vel_joined_32": join_32(vel[0], vel[1]),
            "vel_low_only": vel[1],
            "alarm": f"0x{alarm[0]:04X}",
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/config")
async def get_config():
    return config


@app.post("/api/config")
async def update_config(new_cfg: dict):
    global config
    # Merge into current config
    for section in ["connection", "motors", "server"]:
        if section in new_cfg:
            config.setdefault(section, {}).update(new_cfg[section])
    save_config(config)
    return {"ok": True, "config": config, "restart_required": True}


# --- WebSocket ---

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    try:
        while True:
            await ws.receive_text()  # keep connection alive
    except WebSocketDisconnect:
        ws_clients.discard(ws)


async def _broadcast_loop():
    """Push status to all WebSocket clients. 10Hz for sim, 4Hz for hardware."""
    is_hw = isinstance(modbus, (RealModbus, TcpModbus))
    interval = 0.25 if is_hw else 0.1  # hardware needs more time per poll cycle
    while True:
        await asyncio.sleep(interval)
        if not ws_clients:
            continue
        try:
            data = await _build_status()
        except Exception:
            continue  # skip this cycle on read error
        dead = []
        for ws in ws_clients:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            ws_clients.discard(ws)


async def _build_status() -> dict:
    """Read motor registers and build status dict."""
    from .registers import STATUS_RUNNING, STATUS_CMD_OK, STATUS_PATH_OK
    m1_id = config["motors"]["motor1_slave_id"]
    m2_id = config["motors"]["motor2_slave_id"]
    result = {"motors": {}, "sequence": {"phase": sequencer.phase, "active": sequencer.active, "error": sequencer.error}}

    for sid in [m1_id, m2_id]:
        try:
            status_regs = await modbus.read_holding_registers(sid, MOTION_STATUS, 1)
            pos_regs = await modbus.read_holding_registers(sid, FEEDBACK_POS_H, 2)
            vel_regs = await modbus.read_holding_registers(sid, FEEDBACK_VEL_H, 2)
            alarm_regs = await modbus.read_holding_registers(sid, CURRENT_ALARM, 1)
        except Exception:
            # Motor not responding — show zeroed/disconnected state
            result["motors"][str(sid)] = {
                "position_deg": 0.0, "position_pulses": 0, "velocity_rpm": 0,
                "running": False, "enabled": False, "estopped": False,
                "alarm": 0, "status_bits": 0, "offline": True,
            }
            continue

        # Position is signed (negative for reverse rotation), subtract software zero offset
        raw_pulses = join_32_signed(pos_regs[0], pos_regs[1])
        pos_pulses = raw_pulses - zero_offsets.get(sid, 0)
        status = status_regs[0]

        # Velocity: high register (0x1046) returns 0xFFFF when idle/invalid
        # Use only the low register (0x1047) which holds the actual RPM value
        vel_rpm = vel_regs[1] if vel_regs[0] == 0xFFFF else join_32(vel_regs[0], vel_regs[1])

        if isinstance(modbus, SimulatedModbus):
            motor = modbus.motors[sid]
            running = motor.running
            enabled = motor.enabled
            estopped = motor.estopped
        else:
            running = bool(status & STATUS_RUNNING)
            enabled = bool(status & (STATUS_CMD_OK | STATUS_PATH_OK | STATUS_RUNNING))
            estopped = False

        result["motors"][str(sid)] = {
            "position_deg": round(pulses_to_degrees(pos_pulses), 2),
            "position_pulses": pos_pulses,
            "velocity_rpm": vel_rpm,
            "running": running,
            "enabled": enabled,
            "estopped": estopped,
            "alarm": alarm_regs[0],
            "status_bits": status,
        }
    return result
