"""FastAPI application with REST + WebSocket for multi-motor control (up to 5 motors)."""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import load_config, save_config, MAX_MOTORS
from .modbus_interface import ModbusInterface, SimulatedModbus, RealModbus, TcpModbus
from .motor_sim import MotorSim
from .sequencer import MultiMotorSequencer, MotorStep
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
sequencer: MultiMotorSequencer
sim_motors: dict[int, MotorSim] = {}
ws_clients: set[WebSocket] = set()
# Software zero offsets per slave ID (in pulses)
zero_offsets: dict[int, int] = {}


def _slave_ids() -> list[int]:
    return list(config["motors"].get("slave_ids", []))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global config, modbus, sequencer, sim_motors
    config = load_config()

    from .registers import set_pulses_per_rev
    set_pulses_per_rev(
        command_ppr=config["motors"].get("command_ppr", 10000),
        encoder_ppr=config["motors"].get("encoder_ppr", 10000),
    )

    ids = _slave_ids()
    conn = config["connection"]
    sim_motors = {}

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
    elif conn["mode"] == "tcp":
        tcp = TcpModbus(
            host=conn.get("tcp_host", "192.168.1.100"),
            port=conn.get("tcp_port", 502),
        )
        await tcp.connect()
        modbus = tcp
    else:
        sim_motors = {sid: MotorSim(slave_id=sid) for sid in ids}
        modbus = SimulatedModbus(sim_motors)
        for m in sim_motors.values():
            m.start()

    sequencer = MultiMotorSequencer(modbus, slave_ids=ids)

    broadcast_task = asyncio.create_task(_broadcast_loop())
    yield
    broadcast_task.cancel()
    for m in sim_motors.values():
        await m.stop()
    if isinstance(modbus, (RealModbus, TcpModbus)):
        await modbus.disconnect()


app = FastAPI(lifespan=lifespan)


def _static_dir() -> Path:
    """Static asset dir. When frozen, the launcher sets PYSIM_RESOURCE_ROOT to sys._MEIPASS."""
    env = os.environ.get("PYSIM_RESOURCE_ROOT")
    if env:
        return Path(env) / "static"
    return Path(__file__).parent.parent / "static"


STATIC_DIR = _static_dir()


# --- Pydantic models ---

class MoveRequest(BaseModel):
    slave_id: int = 1
    angle_deg: float = 90.0
    speed_rpm: int = 200
    accel: int = 200
    decel: int = 200
    mode: str = "relative"  # "absolute" or "relative"


class MotorParams(BaseModel):
    slave_id: int
    angle_deg: float = 90.0
    speed_rpm: int = 200
    accel: int = 200
    decel: int = 200


class SequenceRequest(BaseModel):
    motors: list[MotorParams]
    delay_s: float = 1.0
    mode: str = "relative"


class AlarmResetRequest(BaseModel):
    slave_id: int = 1


class HomeRequest(BaseModel):
    slave_id: int = 0  # 0 = all motors, otherwise a specific slave_id
    speed_rpm: int = 20      # Homing is safety-sensitive — slow by default.
    accel: int = 200
    decel: int = 200


class JogStartRequest(BaseModel):
    slave_id: int
    direction: int = 1  # +1 forward, -1 reverse
    speed_rpm: int = 60
    accel: int = 200
    decel: int = 200


class JogStopRequest(BaseModel):
    slave_id: int


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
    if not req.motors:
        return {"error": "No motors in sequence"}

    mode_val = MODE_ABSOLUTE if req.mode == "absolute" else MODE_RELATIVE
    steps = [
        MotorStep(
            slave_id=m.slave_id,
            angle_deg=m.angle_deg,
            speed_rpm=m.speed_rpm,
            accel=m.accel,
            decel=m.decel,
        )
        for m in req.motors
    ]
    asyncio.create_task(sequencer.run_sequence(steps=steps, delay_s=req.delay_s, mode=mode_val))
    return {"ok": True}


@app.post("/api/jog/start")
async def jog_start(req: JogStartRequest):
    """Begin a jog: issue a large relative move at the requested speed. Stop with /api/jog/stop."""
    if sequencer.active:
        return {"error": "Sequence in progress"}

    from .registers import PR0_MODE, PR0_TRIGGER, PR0_TRIGGER_VAL, degrees_to_pulses, split_32

    # 100 revolutions worth of motion in the requested direction.
    # The user releases the jog button → /api/jog/stop decelerates before this finishes.
    angle = 36000.0 * (1 if req.direction >= 0 else -1)
    pulses = degrees_to_pulses(angle)
    pos_h, pos_l = split_32(pulses)
    await modbus.write_registers(req.slave_id, PR0_MODE, [
        MODE_RELATIVE, pos_h, pos_l, req.speed_rpm, req.accel, req.decel,
    ])
    await modbus.write_registers(req.slave_id, PR0_TRIGGER, [PR0_TRIGGER_VAL])
    return {"ok": True}


@app.post("/api/jog/stop")
async def jog_stop(req: JogStopRequest):
    """Stop a jogging motor without latching e-stop."""
    sid = req.slave_id
    if isinstance(modbus, SimulatedModbus) and sid in modbus.motors:
        modbus.motors[sid].stop_motion()
    else:
        # On real hardware, writing the stop value to ESTOP_REG decelerates the motor.
        await modbus.write_registers(sid, ESTOP_REG, [ESTOP_VAL])
    return {"ok": True}


@app.post("/api/home")
async def home_motor(req: HomeRequest):
    """Move motor(s) to absolute position 0 (home)."""
    if sequencer.active:
        return {"error": "Sequence in progress"}

    from .registers import PR0_MODE, PR0_TRIGGER, PR0_TRIGGER_VAL, split_32

    targets = _slave_ids() if req.slave_id == 0 else [req.slave_id]

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
    targets = _slave_ids() if sid == 0 else [sid]

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
    for sid in _slave_ids():
        await modbus.write_registers(sid, SYSTEM_CMD_REG, [PERM_SAVE_VAL])
    return {"ok": True}


@app.post("/api/enable")
async def enable_motors():
    from .registers import SW_ENABLE_REG, SW_ENABLE_VAL
    for sid in _slave_ids():
        await modbus.write_registers(sid, SW_ENABLE_REG, [SW_ENABLE_VAL])
    return {"ok": True}


@app.post("/api/disable")
async def disable_motors():
    from .registers import SW_ENABLE_REG
    for sid in _slave_ids():
        await modbus.write_registers(sid, SW_ENABLE_REG, [0])
    return {"ok": True}


@app.get("/api/ports")
async def list_serial_ports():
    """Detect available serial ports on the system.

    On macOS we deliberately drop /dev/tty.* entries — the tty interface blocks
    waiting for a hardware DCD signal that USB-RS485 adapters don't provide, so
    opening it just hangs or errors. /dev/cu.* is the correct non-blocking dial-out
    interface for serial bridges.
    """
    import glob as g
    import sys
    ports = []
    if sys.platform.startswith("darwin"):
        ports = g.glob("/dev/cu.*")
    elif sys.platform.startswith("linux"):
        ports = g.glob("/dev/ttyUSB*") + g.glob("/dev/ttyACM*") + g.glob("/dev/ttyS*")
    elif sys.platform.startswith("win"):
        ports = [f"COM{i}" for i in range(1, 20)]
    ports.sort()
    return {"ports": ports}


@app.post("/api/test-connection")
async def test_connection():
    """Ping every configured motor via the *currently active* connection.

    We deliberately reuse the live modbus client (built in lifespan()) instead
    of opening a fresh one. Two clients can't share the same serial port, so a
    fresh client would always fail with "Cannot open" while the server is up.
    The trade-off: this tests the running connection, not the in-form values —
    so changes need to be saved and the server restarted before the test
    reflects them. The UI already communicates that with "restart required".
    """
    ids = _slave_ids()

    if isinstance(modbus, SimulatedModbus):
        return {"ok": True, "motors": [
            {"ok": True, "slave_id": sid, "status": 0} for sid in ids
        ]}

    if not isinstance(modbus, (RealModbus, TcpModbus)):
        return {"ok": False, "error": "No active modbus client"}

    try:
        results = [await modbus.test_connection(sid) for sid in ids]
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
    return {**config, "max_motors": MAX_MOTORS}


@app.post("/api/config")
async def update_config(new_cfg: dict):
    global config
    # Merge into current config
    for section in ["connection", "motors", "server"]:
        if section in new_cfg:
            config.setdefault(section, {}).update(new_cfg[section])

    # On macOS, normalize /dev/tty.usb* → /dev/cu.usb*. The tty interface blocks
    # on DCD and never works for USB-RS485 adapters; users shouldn't have to know
    # this. (Harmless on Linux/Windows since paths don't match the prefix.)
    sp = config.get("connection", {}).get("serial_port", "")
    if sp.startswith("/dev/tty.usb"):
        config["connection"]["serial_port"] = sp.replace("/dev/tty.", "/dev/cu.", 1)

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
    ids = _slave_ids()
    result = {
        "slave_ids": ids,
        "motors": {},
        "sequence": {"phase": sequencer.phase, "active": sequencer.active, "error": sequencer.error},
    }

    for sid in ids:
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
