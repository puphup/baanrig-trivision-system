"""FastAPI server for multi-gateway, multi-motor control.

Each *gateway* is one Modbus-TCP↔RTU bridge with up to 20 motors hanging off
its RS485 side. The server opens one :class:`TcpModbus` per gateway in
:func:`lifespan` and builds a :class:`MotorDriver` for every configured motor,
keyed by ``"<gateway-id>.<slave-id>"`` (e.g. ``"gw1.5"``).

Endpoints take a ``motor_key`` instead of a bare slave_id so the same slave_id
on different gateways doesn't collide.
"""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import (
    load_config, save_config,
    MAX_TOTAL_MOTORS, MAX_GATEWAYS, MAX_MOTORS_PER_GATEWAY,
    motor_key as build_motor_key, motor_label,
    driver_type_for,
    ALLOWED_DRIVER_TYPES, DEFAULT_DRIVER_TYPE,
)
from .drivers import (
    MotorDriver, DRIVER_CATALOG,
    make_hardware_driver, make_sim_driver,
)
from .modbus_interface import ModbusInterface, SimulatedModbus, TcpModbus
from .motor_sim import MotorSim
from .sequencer import MultiMotorSequencer, MotorStep
from .show import (
    ShowController, TransitionOptions, effects_catalog, face_for_position,
    DEFAULT_SPEED_RPM, DEFAULT_ACCEL, DEFAULT_DECEL, DEFAULT_STEP_MS,
)


# --- Globals set during lifespan -------------------------------------------
config: dict = {}
gateways: dict[str, ModbusInterface] = {}        # gateway_id → modbus client
drivers: dict[str, MotorDriver] = {}             # motor_key → driver
sim_motors: dict[str, MotorSim] = {}             # motor_key → simulator (sim mode only)
sequencer: MultiMotorSequencer | None = None
show: ShowController = ShowController()
ws_clients: set[WebSocket] = set()
# Software zero offsets per motor key (encoder pulses)
zero_offsets: dict[str, int] = {}


def _motor_specs() -> list[dict]:
    return list(config.get("motors", []))


def _motor_keys() -> list[str]:
    return [build_motor_key(m["gateway"], m["slave_id"]) for m in _motor_specs()]


def _label_for(key: str) -> str:
    """Pretty label for a motor key — derived from gateway id + slave_id."""
    if "." not in key:
        return key
    gw, sid = key.rsplit(".", 1)
    try:
        return motor_label(gw, int(sid))
    except (TypeError, ValueError):
        return key


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

_reload_lock = asyncio.Lock()


async def _build_runtime(cfg: dict):
    """Construct gateways, drivers, and sim motors for *cfg*.

    Returns ``(gateways, drivers, sim_motors)`` — caller decides when to swap
    them into the module-level globals.
    """
    from .registers import set_pulses_per_rev
    md = cfg.get("motor_defaults", {})
    set_pulses_per_rev(
        command_ppr=int(md.get("command_ppr", 4000)),
        encoder_ppr=int(md.get("encoder_ppr", 4000)),
    )

    new_gws: dict[str, ModbusInterface] = {}
    new_drivers: dict[str, MotorDriver] = {}
    new_sims: dict[str, MotorSim] = {}

    mode = cfg.get("mode", "simulation")
    if mode == "tcp":
        for gw in cfg.get("gateways", []):
            client = TcpModbus(host=gw["host"], port=int(gw["port"]))
            try:
                await client.connect()
            except Exception:
                pass
            new_gws[gw["id"]] = client
        for m in cfg.get("motors", []):
            client = new_gws.get(m["gateway"])
            if client is None:
                continue
            key = build_motor_key(m["gateway"], m["slave_id"])
            d = make_hardware_driver(m["driver_type"], client, int(m["slave_id"]))
            await d.configure()      # writes S-curve filter on iCL-RS, no-op elsewhere
            new_drivers[key] = d
    else:
        for m in cfg.get("motors", []):
            key = build_motor_key(m["gateway"], m["slave_id"])
            sim = MotorSim(slave_id=int(m["slave_id"]))
            new_sims[key] = sim
            sim.start()
            new_drivers[key] = make_sim_driver(sim)

    return new_gws, new_drivers, new_sims


async def _teardown_runtime():
    """Stop every in-process simulator and close every open gateway client."""
    global gateways, drivers, sim_motors
    for sim in list(sim_motors.values()):
        try:
            await sim.stop()
        except Exception:
            pass
    for client in list(gateways.values()):
        try:
            await client.disconnect()
        except Exception:
            pass
    sim_motors = {}
    gateways = {}
    drivers = {}


async def _reload_runtime():
    """Atomically replace the running gateways/drivers/sequencer with a fresh
    set built from the current ``config``. Held by ``_reload_lock`` so two
    concurrent saves can't race.
    """
    global gateways, drivers, sim_motors, sequencer
    async with _reload_lock:
        if sequencer is not None:
            sequencer.cancel()
        # Cancel any running auto-cycle; its drivers map is about to be replaced.
        await show.stop_auto()
        await _teardown_runtime()
        new_g, new_d, new_s = await _build_runtime(config)
        gateways = new_g
        drivers = new_d
        sim_motors = new_s
        sequencer = MultiMotorSequencer(drivers=drivers, motor_keys=list(drivers.keys()))
        # Fresh array → face 1 by convention.
        await show.set_current_page(1)


async def run_iclrs_setup() -> int:
    """One-time iCL-RS commissioning: hand enable control to software.

    Builds the runtime from the current config, calls
    :meth:`ICLRSDriver.configure_software_enable` on every iCL-RS driver
    (silently skipping anything else), then tears the runtime down. Returns
    the count of drives that were reconfigured.

    Used by ``launcher.py --setup-iclrs-enable``; not called on normal
    startup. Other driver families are intentionally untouched.
    """
    global gateways, drivers, sim_motors, config
    from .drivers.icl_rs import ICLRSDriver

    config = load_config()
    if config.get("mode") != "tcp":
        print("[setup] mode is not 'tcp'; skipping iCL-RS commissioning")
        return 0
    new_g, new_d, new_s = await _build_runtime(config)
    gateways, drivers, sim_motors = new_g, new_d, new_s
    try:
        touched = 0
        for key, d in drivers.items():
            if not isinstance(d, ICLRSDriver):
                continue
            print(f"[setup] reconfiguring {key} for software enable …")
            try:
                await d.configure_software_enable()
                touched += 1
            except Exception as e:
                print(f"[setup] {key} failed: {e}")
        return touched
    finally:
        await _teardown_runtime()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global config, gateways, drivers, sim_motors, sequencer
    config = load_config()
    new_g, new_d, new_s = await _build_runtime(config)
    gateways = new_g
    drivers = new_d
    sim_motors = new_s
    sequencer = MultiMotorSequencer(drivers=drivers, motor_keys=list(drivers.keys()))

    broadcast_task = asyncio.create_task(_broadcast_loop())
    yield
    broadcast_task.cancel()
    await _teardown_runtime()


app = FastAPI(lifespan=lifespan)


def _static_dir() -> Path:
    env = os.environ.get("PYSIM_RESOURCE_ROOT")
    if env:
        return Path(env) / "static"
    return Path(__file__).parent.parent / "static"


STATIC_DIR = _static_dir()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class MoveRequest(BaseModel):
    motor_key: str
    angle_deg: float = 90.0
    speed_rpm: int = 200
    accel: int = 200
    decel: int = 200
    mode: str = "relative"


class MotorParams(BaseModel):
    motor_key: str
    angle_deg: float = 90.0
    speed_rpm: int = 200
    accel: int = 200
    decel: int = 200


class SequenceRequest(BaseModel):
    motors: list[MotorParams]
    delay_s: float = 1.0
    mode: str = "relative"


class MotorKeyRequest(BaseModel):
    motor_key: str | None = None       # None / empty → apply to all


class HomeRequest(BaseModel):
    motor_key: str | None = None       # None → all motors
    speed_rpm: int = 5
    accel: int = 200
    decel: int = 200


class JogStartRequest(BaseModel):
    motor_key: str
    direction: int = 1
    speed_rpm: int = 60
    accel: int = 200
    decel: int = 200


class TransitionRequest(BaseModel):
    """Shared body for /api/show/next, /api/show/prev, /api/show/goto."""
    effect: str = "simultaneous"
    speed_rpm: int = DEFAULT_SPEED_RPM
    accel: int = DEFAULT_ACCEL
    decel: int = DEFAULT_DECEL
    step_ms: int = DEFAULT_STEP_MS
    gap_ms: int = DEFAULT_STEP_MS * 4
    max_jitter_ms: int = 1500
    soft_stop_deg: float = 0.0
    soft_stop_speed_rpm: int = 0
    target_page: int | None = None     # only used by /goto


class AutoCycleRequest(BaseModel):
    hold_s: float = 5.0
    direction: int = 1                 # +1 forward, -1 backward
    effect: str = "wave"
    speed_rpm: int = DEFAULT_SPEED_RPM
    accel: int = DEFAULT_ACCEL
    decel: int = DEFAULT_DECEL
    step_ms: int = DEFAULT_STEP_MS
    gap_ms: int = DEFAULT_STEP_MS * 4
    max_jitter_ms: int = 1500
    soft_stop_deg: float = 0.0
    soft_stop_speed_rpm: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_targets(motor_key: str | None) -> list[str]:
    """A None/empty motor_key applies to every configured motor."""
    if motor_key:
        return [motor_key] if motor_key in drivers else []
    return list(drivers.keys())


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/favicon.ico")
async def favicon():
    from fastapi.responses import Response
    return Response(
        content=b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n\xb4\x00\x00\x00\x00IEND\xaeB`\x82',
        media_type="image/png",
    )


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
    d = drivers.get(req.motor_key)
    if d is None:
        return {"error": f"Unknown motor {req.motor_key!r}"}
    await d.start_move(req.mode, req.angle_deg, req.speed_rpm, req.accel, req.decel)
    return {"ok": True}


@app.post("/api/sequence")
async def run_sequence(req: SequenceRequest):
    if sequencer.active:
        return {"error": "Sequence already running"}
    if not req.motors:
        return {"error": "No motors in sequence"}
    steps = [
        MotorStep(
            motor_key=m.motor_key,
            angle_deg=m.angle_deg,
            speed_rpm=m.speed_rpm,
            accel=m.accel,
            decel=m.decel,
        )
        for m in req.motors
        if m.motor_key in drivers
    ]
    if not steps:
        return {"error": "No valid motors in sequence"}
    asyncio.create_task(sequencer.run_sequence(steps=steps, delay_s=req.delay_s, mode=req.mode))
    return {"ok": True}


@app.post("/api/jog/start")
async def jog_start(req: JogStartRequest):
    if sequencer.active:
        return {"error": "Sequence in progress"}
    d = drivers.get(req.motor_key)
    if d is None:
        return {"error": f"Unknown motor {req.motor_key!r}"}
    await d.jog_start(req.direction, req.speed_rpm, req.accel, req.decel)
    return {"ok": True}


@app.post("/api/jog/stop")
async def jog_stop(req: MotorKeyRequest):
    if not req.motor_key:
        return {"error": "motor_key required"}
    d = drivers.get(req.motor_key)
    if d is None:
        return {"error": f"Unknown motor {req.motor_key!r}"}
    await d.jog_stop()
    return {"ok": True}


@app.post("/api/home")
async def home_motor(req: HomeRequest):
    if sequencer.active:
        return {"error": "Sequence in progress"}
    for key in _resolve_targets(req.motor_key):
        d = drivers[key]
        home_pulses = zero_offsets.get(key, 0)
        await d.start_move(
            mode="absolute",
            angle_deg=d.pulses_to_deg(home_pulses),   # per-driver PPR, not global
            speed_rpm=req.speed_rpm,
            accel=req.accel,
            decel=req.decel,
        )
    return {"ok": True}


@app.post("/api/set-zero")
async def set_zero(req: MotorKeyRequest):
    targets = _resolve_targets(req.motor_key)
    for key in targets:
        d = drivers[key]
        if key in sim_motors:
            sim_motors[key].position = 0.0
            zero_offsets[key] = 0
        else:
            st = await d.read_status()
            zero_offsets[key] = int(st.get("position_pulses", 0))
    # If the user zero'd every motor at once, the array is now aligned to face 1.
    if not req.motor_key:
        await show.set_current_page(1)
    return {"ok": True}


@app.post("/api/set-home")
async def set_home(req: MotorKeyRequest):
    """Make the current physical position the DRIVE's origin and persist it to
    EEPROM (survives power cycles), unlike /api/set-zero which only stores a
    software display offset. Also clears that software offset since the drive
    now reads 0 here."""
    failed = []
    for key in _resolve_targets(req.motor_key):
        d = drivers[key]
        try:
            await d.set_home()
        except Exception as e:
            failed.append({"motor_key": key, "error": str(e)[:80]})
            continue
        # Make the DISPLAY read 0 at the new home too. set_home() clears the
        # drive's positioning origin (persisted), but on iCL-RS the register we
        # display (0x1014) is a separate absolute counter that isn't cleared —
        # so capture a software offset like Set Zero. TL-R's display register
        # *is* cleared, so its offset lands on 0 naturally.
        if key in sim_motors:
            zero_offsets[key] = 0
        else:
            try:
                st = await d.read_status()
                zero_offsets[key] = int(st.get("position_pulses", 0))
            except Exception:
                zero_offsets[key] = 0
    # Set Home on the whole array → treat the new origin as face 1.
    if not req.motor_key:
        await show.set_current_page(1)
    return {"ok": True, "failed": failed}


@app.post("/api/reconnect")
async def reconnect():
    """Tear down and rebuild every gateway TCP client + driver from the current
    config. Use when motors show offline after a gateway/PC disconnect — the
    sockets go stale and don't auto-recover. Returns the online count so the UI
    can report the result."""
    try:
        await _reload_runtime()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    online = 0
    for key, d in drivers.items():
        try:
            st = await d.read_status()
            if not st.get("offline"):
                online += 1
        except Exception:
            pass
    return {"ok": True, "online": online, "total": len(drivers)}


@app.post("/api/estop")
async def estop():
    await sequencer.emergency_stop_all()
    return {"ok": True}


@app.post("/api/alarm-reset")
async def alarm_reset(req: MotorKeyRequest):
    for key in _resolve_targets(req.motor_key):
        await drivers[key].alarm_reset()
    return {"ok": True}


@app.post("/api/save")
async def save_params():
    for d in drivers.values():
        try:
            await d.save_params()
        except Exception:
            pass
    return {"ok": True}


@app.post("/api/enable")
async def enable_motors(req: MotorKeyRequest = MotorKeyRequest()):
    # ponytail: per-motor try/except so a dead gateway can't 500 the whole call.
    failed = []
    for key in _resolve_targets(req.motor_key):
        try:
            await drivers[key].enable()
        except Exception as e:
            failed.append({"motor_key": key, "error": str(e)[:80]})
    return {"ok": True, "failed": failed}


@app.post("/api/disable")
async def disable_motors(req: MotorKeyRequest = MotorKeyRequest()):
    failed = []
    for key in _resolve_targets(req.motor_key):
        try:
            await drivers[key].disable()
        except Exception as e:
            failed.append({"motor_key": key, "error": str(e)[:80]})
    return {"ok": True, "failed": failed}


# ---------------------------------------------------------------------------
# Inventory / setup endpoints
# ---------------------------------------------------------------------------

@app.get("/api/driver-types")
async def driver_catalog():
    return {
        "types": [{"key": k, **v} for k, v in DRIVER_CATALOG.items()],
        "default": DEFAULT_DRIVER_TYPE,
        "allowed": list(ALLOWED_DRIVER_TYPES),
    }


# ---------------------------------------------------------------------------
# Trivision / triangular-prism show endpoints
# ---------------------------------------------------------------------------

def _opts_from(req: TransitionRequest | AutoCycleRequest) -> TransitionOptions:
    return TransitionOptions(
        effect=req.effect,
        speed_rpm=int(req.speed_rpm),
        accel=int(req.accel),
        decel=int(req.decel),
        step_ms=int(req.step_ms),
        gap_ms=int(req.gap_ms),
        max_jitter_ms=int(req.max_jitter_ms),
        soft_stop_deg=float(req.soft_stop_deg),
        soft_stop_speed_rpm=int(req.soft_stop_speed_rpm),
    )


@app.get("/api/show/effects")
async def show_effects():
    return {"effects": effects_catalog()}


@app.get("/api/show/state")
async def show_state():
    return show.state()


@app.post("/api/show/next")
async def show_next(req: TransitionRequest = TransitionRequest()):
    if sequencer is not None and sequencer.active:
        return {"error": "Sequence in progress"}
    await show.next_page(drivers, _opts_from(req))
    return {"ok": True, **show.state()}


@app.post("/api/show/prev")
async def show_prev(req: TransitionRequest = TransitionRequest()):
    if sequencer is not None and sequencer.active:
        return {"error": "Sequence in progress"}
    await show.prev_page(drivers, _opts_from(req))
    return {"ok": True, **show.state()}


@app.post("/api/show/goto")
async def show_goto(req: TransitionRequest):
    if sequencer is not None and sequencer.active:
        return {"error": "Sequence in progress"}
    if req.target_page is None:
        return {"error": "target_page required"}
    await show.goto(drivers, int(req.target_page), _opts_from(req))
    return {"ok": True, **show.state()}


@app.post("/api/show/set-current-page")
async def show_set_current_page(req: TransitionRequest):
    """Tell the show controller what page the array is currently on, without
    moving any motors. Use after a manual realignment / Set Zero so the next
    'Next' lands on the right face.
    """
    if req.target_page is None:
        return {"error": "target_page required"}
    await show.set_current_page(int(req.target_page))
    return {"ok": True, **show.state()}


@app.post("/api/show/auto/start")
async def show_auto_start(req: AutoCycleRequest):
    await show.start_auto(drivers, req.hold_s, req.direction, _opts_from(req))
    return {"ok": True, **show.state()}


@app.post("/api/show/auto/stop")
async def show_auto_stop():
    await show.stop_auto()
    return {"ok": True, **show.state()}


@app.get("/api/limits")
async def limits():
    return {
        "max_gateways": MAX_GATEWAYS,
        "max_motors_per_gateway": MAX_MOTORS_PER_GATEWAY,
        "max_total_motors": MAX_TOTAL_MOTORS,
    }


@app.post("/api/test-connection")
async def test_connection():
    """Ping every configured motor via its currently active driver."""
    results = []
    for key, d in drivers.items():
        r = await d.test_connection()
        r["motor_key"] = key
        r["label"] = _label_for(key)
        results.append(r)
    all_ok = bool(results) and all(r["ok"] for r in results)
    return {"ok": all_ok, "motors": results}


@app.get("/api/debug/{motor_key}")
async def debug_status(motor_key: str):
    d = drivers.get(motor_key)
    if d is None:
        return {"error": f"Unknown motor {motor_key!r}"}
    try:
        st = await d.read_status()
        return {
            "label": _label_for(motor_key),
            "driver_type": driver_type_for(config, *motor_key.rsplit(".", 1)) if "." in motor_key else DEFAULT_DRIVER_TYPE,
            **st,
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/config")
async def get_config():
    return {
        **config,
        "limits": {
            "max_gateways": MAX_GATEWAYS,
            "max_motors_per_gateway": MAX_MOTORS_PER_GATEWAY,
            "max_total_motors": MAX_TOTAL_MOTORS,
        },
        "allowed_driver_types": list(ALLOWED_DRIVER_TYPES),
    }


@app.post("/api/config")
async def update_config(new_cfg: dict):
    """Replace top-level sections with the values supplied, persist, and apply.

    After saving, the running gateways / drivers / sequencer are torn down and
    rebuilt in place — no process restart needed. The only setting that still
    can't be hot-applied is the web server's bind host/port, since uvicorn
    holds the socket; restart the launcher for those.
    """
    global config
    for section in ("mode", "gateways", "motors", "motor_defaults", "server", "connection"):
        if section in new_cfg:
            config[section] = new_cfg[section]
    save_config(config)
    config = load_config()
    try:
        await _reload_runtime()
        return {"ok": True, "config": config, "applied": True}
    except Exception as e:
        return {"ok": True, "config": config, "applied": False, "reload_error": str(e)}


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_clients.discard(ws)


async def _broadcast_loop():
    while True:
        # Recompute each tick so a sim↔tcp hot-swap takes effect immediately.
        interval = 0.25 if config.get("mode") == "tcp" else 0.1
        await asyncio.sleep(interval)
        if not ws_clients:
            continue
        try:
            data = await _build_status()
        except Exception:
            continue

        # Send to all clients CONCURRENTLY with a per-client timeout. A single
        # half-open tab used to block every other client (sends were sequential
        # + unbounded), stalling the whole feed. Now a slow/dead client is
        # dropped after 2s without affecting the others.
        clients = list(ws_clients)

        async def _send(ws):
            try:
                await asyncio.wait_for(ws.send_json(data), timeout=2.0)
                return None
            except Exception:
                return ws

        results = await asyncio.gather(*(_send(ws) for ws in clients))
        for ws in results:
            if ws is not None:
                ws_clients.discard(ws)


_OFFLINE_ST = {
    "position_deg": 0.0, "position_pulses": 0, "velocity_rpm": 0,
    "running": False, "enabled": False, "estopped": False,
    "alarm": 0, "status_bits": 0, "offline": True, "current_face": None,
}


async def _read_one_status(key: str) -> dict:
    """Read + post-process one motor. Returns an offline dict on any failure so
    a single dead drive can't break the whole status build."""
    d = drivers.get(key)
    if d is None:
        return dict(_OFFLINE_ST)
    try:
        st = await d.read_status()
    except Exception:
        return dict(_OFFLINE_ST)
    if not st.get("offline"):
        raw_pulses = int(st.get("position_pulses", 0))
        display_pulses = raw_pulses - zero_offsets.get(key, 0)
        st["position_pulses"] = display_pulses
        st["position_deg"] = round(d.pulses_to_deg(display_pulses), 2)  # per-driver PPR
        st["current_face"] = face_for_position(st["position_deg"])
    else:
        st["current_face"] = None
    return dict(st)


async def _build_status() -> dict:
    """Read live status for every driver and emit a flat motor-keyed dict.

    Reads run CONCURRENTLY — same-gateway reads still serialize on that
    gateway's modbus lock, but the gateways overlap, so 50 motors across 3
    gateways take ~1/3 the wall-clock of a sequential loop. (Sequential was
    ~2.4s and choked the WS broadcast / keepalive.)"""
    specs = _motor_specs()
    inventory = [{
        "motor_key": build_motor_key(s["gateway"], s["slave_id"]),
        "label": motor_label(s["gateway"], s["slave_id"]),
        "gateway": s["gateway"],
        "slave_id": int(s["slave_id"]),
        "driver_type": s["driver_type"],
    } for s in specs]

    keys = [it["motor_key"] for it in inventory]
    results = await asyncio.gather(*(_read_one_status(k) for k in keys))
    motors_out = {k: st for k, st in zip(keys, results)}

    seq_info = (
        {"phase": sequencer.phase, "active": sequencer.active, "error": sequencer.error}
        if sequencer is not None else
        {"phase": "idle", "active": False, "error": None}
    )
    return {
        "mode": config.get("mode"),
        "motors": motors_out,
        "inventory": inventory,
        "sequence": seq_info,
        "show": show.state(),
    }
