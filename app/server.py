"""FastAPI server for multi-gateway, multi-motor control.

Each *gateway* is one Modbus-TCP↔RTU bridge with up to 32 motors (wall: 11 cabinets,
231 motors from motor_map.json) hanging off its RS485 side. The server opens one
:class:`TcpModbus` per gateway in :func:`lifespan` and builds a :class:`MotorDriver`
for every configured motor, keyed by ``"<gateway-id>.<slave-id>"`` (e.g. ``"gw1.5"``).

Endpoints take a ``motor_key`` instead of a bare slave_id so the same slave_id
on different gateways doesn't collide.
"""

import asyncio
import os
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
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
from .modbus_interface import ModbusInterface, SimulatedModbus, TcpModbus, RealModbus
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
# Latest raw status per motor key, written by the per-cabinet pollers.
status_cache: dict[str, dict] = {}
_poll_tasks: list[asyncio.Task] = []
# The in-flight seek-home run: the wall task + its per-motor display-zero tasks.
_home_tasks: list[asyncio.Task] = []
# Progress of the in-flight /api/seek-home run (single run at a time).
homing_state: dict = {"active": False, "total": 0, "done": 0, "failed": []}


def _motor_specs() -> list[dict]:
    return list(config.get("motors", []))


def _motor_keys() -> list[str]:
    return [build_motor_key(m["gateway"], m["slave_id"]) for m in _motor_specs()]


def _label_for(key: str) -> str:
    """Pretty label for a motor key — prefers the motor-map label, falling
    back to one derived from gateway id + slave_id."""
    ex = config.get("motor_extras", {}).get(key)
    if ex:
        return ex["label"]
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
        # Connect all gateways concurrently and don't block long on any one —
        # the drivers self-heal/reconnect on first use anyway. A sequential
        # connect to an unreachable gateway would stall startup for seconds.
        gws = cfg.get("gateways", [])
        # ponytail: a gateway whose host looks like a serial device (/dev/…, COMn)
        # is a direct USB-RS485 link; its "port" field is then the baudrate.
        def _client(gw):
            h = gw["host"]
            if h.startswith("/dev/") or h.upper().startswith("COM"):
                return RealModbus(port=h, baudrate=int(gw["port"]))
            return TcpModbus(host=h, port=int(gw["port"]))
        clients = {gw["id"]: _client(gw) for gw in gws}
        async def _try_connect(c):
            try:
                await c.connect()
            except Exception:
                pass
        await asyncio.gather(*(_try_connect(c) for c in clients.values()))
        new_gws.update(clients)
        for m in cfg.get("motors", []):
            client = new_gws.get(m["gateway"])
            if client is None:
                continue
            key = build_motor_key(m["gateway"], m["slave_id"])
            # NOTE: no per-startup configure() here. The command filter is
            # persisted to EEPROM during commissioning (--setup-iclrs-enable),
            # so writing it on every launch is redundant and would block startup
            # with 36 sequential modbus writes (each retrying on a flaky link).
            new_drivers[key] = make_hardware_driver(m["driver_type"], client, int(m["slave_id"]))
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
        await _stop_homing()
        await _stop_pollers()
        await _teardown_runtime()
        new_g, new_d, new_s = await _build_runtime(config)
        gateways = new_g
        drivers = new_d
        sim_motors = new_s
        sequencer = MultiMotorSequencer(drivers=drivers, motor_keys=list(drivers.keys()))
        await _start_pollers()
        # Fresh array → face 1 by convention.
        await show.set_current_page(1)


async def run_iclrs_setup(method: str = "configure_software_enable", only: str | None = None, **kw) -> int:
    """One-time iCL-RS commissioning (default: hand enable control to software).

    Builds the runtime from the current config, calls ``ICLRSDriver.<method>``
    (``configure_software_enable`` or ``configure_home_switch``) on every iCL-RS driver
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
            if not isinstance(d, ICLRSDriver) or (only and key != only):
                continue
            print(f"[setup] {key}: {method} …")
            try:
                await getattr(d, method)(**kw)
                touched += 1
            except Exception as e:
                print(f"[setup] {key} failed: {e}")
        return touched
    finally:
        await _teardown_runtime()


async def _reconnect_loop():
    """Reconnect down gateways OUT OF BAND, every few seconds.

    The live status feed never attempts a connect (it fast-fails offline
    gateways instantly), so reconnection has to happen here instead. A missing
    gateway therefore costs the UI nothing — its motors just show offline until
    this loop dials it back, while the healthy gateways keep updating at full
    speed.

    Only TCP gateways are redialled: a ``RealModbus`` (direct USB-RS485) link is
    intentionally left alone — a yanked adapter needs a human, not a retry loop."""
    while True:
        await asyncio.sleep(5.0)
        clients = [c for c in gateways.values()
                   if isinstance(c, TcpModbus) and not c.connected]
        if not clients:
            continue
        # Concurrent so 3 down gateways don't take 3× the connect timeout.
        async def _try(c):
            try:
                await c.ensure_connected()
            except Exception:
                pass
        await asyncio.gather(*(_try(c) for c in clients))


async def _poll_cabinet(keys: list[str]) -> None:
    """Continuously read every motor on one bus into status_cache. Buses run in
    their own task so a slow/offline cabinet never delays the others."""
    # ponytail: a healthy tcp bus polls back-to-back (no pacing); only a cycle
    # that got no successful read backs off, so a down cabinet can't spin hot.
    interval = 0.1 if config.get("mode") != "tcp" else 0.0
    gw_id = keys[0].rsplit(".", 1)[0] if keys else ""
    while True:
        client = gateways.get(gw_id)
        if isinstance(client, TcpModbus) and not client.connected:
            # Whole cabinet is down — mark it offline in one pass instead of
            # burning 21 doomed transactions per cycle. _reconnect_loop redials.
            for key in keys:
                status_cache[key] = dict(_OFFLINE_ST)
            await asyncio.sleep(1.0)
            continue
        ok = 0
        for key in keys:
            d = drivers.get(key)
            if d is None:
                continue
            try:
                st = await d.read_status_fast()
            except Exception:
                st = dict(_OFFLINE_ST)
            if not st.get("offline"):
                ok += 1
            status_cache[key] = st
            await asyncio.sleep(0)
        await asyncio.sleep(interval if ok else 0.25)


async def _start_pollers() -> None:
    await _stop_pollers()
    by_gw: dict[str, list[str]] = {}
    for key in drivers:
        by_gw.setdefault(key.rsplit(".", 1)[0], []).append(key)
    _poll_tasks.extend(asyncio.create_task(_poll_cabinet(keys)) for keys in by_gw.values())


async def _stop_pollers() -> None:
    tasks = list(_poll_tasks)
    for t in tasks:
        t.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _poll_tasks.clear()
    status_cache.clear()


async def _stop_homing() -> None:
    """Cancel an in-flight seek-home run and clear its progress. The drivers it
    was homing are about to be replaced (or the app is shutting down), so
    ``homing_state["active"]`` must not survive."""
    tasks = list(_home_tasks)
    for t in tasks:
        t.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _home_tasks.clear()
    homing_state.update({"active": False, "total": 0, "done": 0, "failed": []})


@asynccontextmanager
async def lifespan(app: FastAPI):
    global config, gateways, drivers, sim_motors, sequencer
    config = load_config()
    new_g, new_d, new_s = await _build_runtime(config)
    gateways = new_g
    drivers = new_d
    sim_motors = new_s
    sequencer = MultiMotorSequencer(drivers=drivers, motor_keys=list(drivers.keys()))
    # Every modbus call runs in the default executor; the stock 32-thread pool
    # would serialize 11 cabinets behind each other. Not recomputed on reload —
    # the gateway count comes from the map, which a reload doesn't change.
    asyncio.get_running_loop().set_default_executor(
        ThreadPoolExecutor(max_workers=len(gateways) + 8))
    await _start_pollers()

    broadcast_task = asyncio.create_task(_broadcast_loop())
    reconnect_task = asyncio.create_task(_reconnect_loop())
    yield
    broadcast_task.cancel()
    reconnect_task.cancel()
    await _stop_homing()
    await _stop_pollers()
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


class SeekHomeRequest(BaseModel):
    motor_key: str | None = None       # one motor
    cabinet: int | None = None         # one cabinet; neither → whole wall


class CabinetRequest(BaseModel):
    cabinet: int


class HomeRequest(BaseModel):
    motor_key: str | None = None       # None → all motors
    speed_rpm: int = 10
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


def _keys_for_cabinet(cabinet: int) -> list[str]:
    prefix = f"gw{int(cabinet)}."
    return [k for k in drivers if k.startswith(prefix)]


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


@app.get("/operator")
async def operator():
    """Tablet page: a few big buttons, no per-motor controls."""
    return FileResponse(STATIC_DIR / "operator.html")


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
    """Drive motor(s) to face 1 by the SHORTEST path. Each motor makes a RELATIVE
    move onto the nearest face-1 orientation of its own displayed angle (face 1 =
    0° after Set Zero/Set Home), so it re-aligns onto the face without depending
    on a shared absolute origin. At most a 180° move; usually just re-squaring."""
    if sequencer.active:
        return {"error": "Sequence in progress"}
    targets = _resolve_targets(req.motor_key)
    failed = []
    for key in targets:
        try:
            d = drivers[key]     # inside the try: a reload mid-loop fails one motor
            st = await d.read_status()
            raw = int(st.get("position_pulses", 0))
            display_deg = d.pulses_to_deg(raw - zero_offsets.get(key, 0))
            # nearest face-1 (multiple of 360) expressed as a relative delta
            delta = round(display_deg / 360.0) * 360.0 - display_deg
            await d.start_move("relative", delta, req.speed_rpm, req.accel, req.decel)
        except Exception as e:
            failed.append({"motor_key": key, "error": str(e)[:80]})
    # Homing the whole array declares it back on face 1.
    if not req.motor_key:
        await show.set_current_page(1)
    return {"ok": True, "total": len(targets), "done": len(targets) - len(failed), "failed": failed}


@app.post("/api/seek-home")
async def seek_home(req: SeekHomeRequest):
    """Drive-level DI3 homing. One motor, one cabinet, or the whole wall.
    Cabinets run in parallel; motors inside a cabinet are staggered 200 ms."""
    if (sequencer is not None and sequencer.active) or homing_state["active"]:
        return {"error": "Sequence or homing in progress"}
    if req.motor_key:
        targets = _resolve_targets(req.motor_key)
    elif req.cabinet is not None:
        targets = _keys_for_cabinet(req.cabinet)
        if not targets:
            raise HTTPException(status_code=404, detail=f"unknown cabinet {req.cabinet}")
    else:
        targets = list(drivers.keys())
    whole_wall = not req.motor_key and req.cabinet is None
    homing_state.update({"active": True, "total": len(targets), "done": 0, "failed": []})
    by_gw: dict[str, list[str]] = {}
    for k in targets:
        by_gw.setdefault(k.rsplit(".", 1)[0], []).append(k)
    _home_tasks.clear()          # one run at a time; the last run's tasks are done
    _home_tasks.append(asyncio.create_task(_seek_home_wall(list(by_gw.values()), whole_wall)))
    return {"ok": True, "total": len(targets)}


@app.post("/api/seek-home/cancel")
async def seek_home_cancel():
    """Operator-page Cancel. Always 200 so the tablet can press it any time.
    ICLRSDriver.seek_home() is fire-and-forget: the drive keeps homing on its own
    once started, so cancelling the Python-side run can't stop the motors — we
    e-stop them instead."""
    was_active = homing_state["active"]
    await _stop_homing()
    if was_active:
        await sequencer.emergency_stop_all()
    return {"ok": True, "cancelled": was_active}


async def _seek_home_cabinet(keys: list[str]) -> None:
    zero_tasks = []
    for i, key in enumerate(keys):
        try:
            d = drivers[key]     # a reload mid-loop must fail this motor, not the run
            if not hasattr(d, "seek_home"):
                raise TypeError("no home-switch homing on this driver")
            await d.seek_home()
            t = asyncio.create_task(_zero_display_after_homing(key))
            zero_tasks.append(t)
            _home_tasks.append(t)
        except Exception as e:
            homing_state["failed"].append({"motor_key": key, "error": str(e)[:80]})
            homing_state["done"] += 1    # a failed motor is still "finished"
        if i < len(keys) - 1:
            await asyncio.sleep(0.2)
    for t in zero_tasks:
        await t
        homing_state["done"] += 1


async def _seek_home_wall(groups: list[list[str]], whole_wall: bool) -> None:
    try:
        await asyncio.gather(*(_seek_home_cabinet(g) for g in groups))
        if whole_wall and not homing_state["failed"]:
            await show.set_current_page(1)
    finally:
        homing_state["active"] = False


async def _zero_display_after_homing(key: str) -> None:
    """Homing zeroes the drive's origin but not the absolute counter the UI
    shows (same quirk as Set Home), so once the motor stops, capture the
    software offset so the tile reads 0 at the switch.

    Reads the poller cache, never the bus: 231 of these watchers each doing
    their own read_status() would saturate every gateway for the whole run."""
    await asyncio.sleep(1.0)
    deadline = time.monotonic() + 120.0       # ponytail: give up after 2 min
    while time.monotonic() < deadline:
        st = status_cache.get(key)
        if st and not st.get("running") and not st.get("offline"):
            zero_offsets[key] = int(st.get("position_pulses", 0))
            return
        await asyncio.sleep(0.5)


@app.post("/api/commission")
async def commission(req: CabinetRequest):
    """Fresh-drive setup for one cabinet: DI1 → software enable, DI3 = home
    switch (N.O.), homing speeds 3/1 rpm, EEPROM save. Power-cycle after."""
    from .drivers.icl_rs import ICLRSDriver
    targets = _keys_for_cabinet(req.cabinet)
    if not targets:
        raise HTTPException(status_code=404, detail=f"unknown cabinet {req.cabinet}")
    failed = []
    for key in targets:
        try:
            d = drivers[key]     # inside the try: a reload mid-loop fails one motor
            if not isinstance(d, ICLRSDriver):
                raise TypeError("not an iCL-RS drive (simulated?)")
            await d.configure_software_enable()
            await d.configure_home_switch(normally_closed=False, high_rpm=3, low_rpm=1)
        except Exception as e:
            failed.append({"motor_key": key, "error": str(e)[:80]})
    return _bulk_result(targets, failed)


@app.post("/api/set-zero")
async def set_zero(req: MotorKeyRequest):
    targets = _resolve_targets(req.motor_key)
    failed = []
    for key in targets:
        try:
            d = drivers[key]     # inside the try: a reload mid-loop fails one motor
            if key in sim_motors:
                sim_motors[key].position = 0.0
                zero_offsets[key] = 0
            else:
                st = await d.read_status()
                zero_offsets[key] = int(st.get("position_pulses", 0))
        except Exception as e:
            failed.append({"motor_key": key, "error": str(e)[:80]})
    # If the user zero'd every motor at once, the array is now aligned to face 1.
    if not req.motor_key:
        await show.set_current_page(1)
    return {"ok": True, "total": len(targets), "done": len(targets) - len(failed), "failed": failed}


@app.post("/api/set-home")
async def set_home(req: MotorKeyRequest):
    """Make the current physical position the DRIVE's origin and persist it to
    EEPROM (survives power cycles), unlike /api/set-zero which only stores a
    software display offset. Also clears that software offset since the drive
    now reads 0 here."""
    targets = _resolve_targets(req.motor_key)
    failed = []
    for key in targets:
        try:
            d = drivers[key]     # inside the try: a reload mid-loop fails one motor
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
    return _bulk_result(targets, failed)


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


def _bulk_result(targets: list, failed: list) -> dict:
    """Standard multi-motor response so the UI can pop up 'M/N completed'."""
    n = len(targets)
    return {"ok": True, "total": n, "done": n - len(failed), "failed": failed}


@app.post("/api/alarm-reset")
async def alarm_reset(req: MotorKeyRequest):
    targets = _resolve_targets(req.motor_key)
    failed = []
    for key in targets:
        try:
            await drivers[key].alarm_reset()
        except Exception as e:
            failed.append({"motor_key": key, "error": str(e)[:80]})
    return _bulk_result(targets, failed)


@app.post("/api/save")
async def save_params():
    targets = list(drivers.keys())
    failed = []
    for key in targets:
        try:
            await drivers[key].save_params()
        except Exception as e:
            failed.append({"motor_key": key, "error": str(e)[:80]})
    return _bulk_result(targets, failed)


@app.post("/api/enable")
async def enable_motors(req: MotorKeyRequest = MotorKeyRequest()):
    # ponytail: per-motor try/except so a dead gateway can't 500 the whole call.
    targets = _resolve_targets(req.motor_key)
    failed = []
    for key in targets:
        try:
            await drivers[key].enable()
        except Exception as e:
            failed.append({"motor_key": key, "error": str(e)[:80]})
    return _bulk_result(targets, failed)


@app.post("/api/disable")
async def disable_motors(req: MotorKeyRequest = MotorKeyRequest()):
    targets = _resolve_targets(req.motor_key)
    failed = []
    for key in targets:
        try:
            await drivers[key].disable()
        except Exception as e:
            failed.append({"motor_key": key, "error": str(e)[:80]})
    return _bulk_result(targets, failed)


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


@app.get("/api/motors")
async def motors_inventory():
    from .motor_map import cabinet_summary
    from .config import _map_path
    data = await _build_status()
    cabs = cabinet_summary(_map_path(config), config.get("use_spare", []))
    for c in cabs:
        c["motor_keys"] = _keys_for_cabinet(c["cabinet"])
    return {"cabinets": cabs, "motors": data["inventory"],
            "motion": config.get("motion", {}), "mode": config.get("mode")}


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


_BUSY_MSG = "Motors still finishing the last flip — wait until they stop."


@app.post("/api/show/next")
async def show_next(req: TransitionRequest = TransitionRequest()):
    if sequencer is not None and sequencer.active:
        return {"error": "Sequence in progress"}
    fired = await show.next_page(drivers, _opts_from(req))
    return {"ok": fired, "rejected": not fired,
            "error": None if fired else _BUSY_MSG, **show.state()}


@app.post("/api/show/prev")
async def show_prev(req: TransitionRequest = TransitionRequest()):
    if sequencer is not None and sequencer.active:
        return {"error": "Sequence in progress"}
    fired = await show.prev_page(drivers, _opts_from(req))
    return {"ok": fired, "rejected": not fired,
            "error": None if fired else _BUSY_MSG, **show.state()}


@app.post("/api/show/goto")
async def show_goto(req: TransitionRequest):
    if sequencer is not None and sequencer.active:
        return {"error": "Sequence in progress"}
    if req.target_page is None:
        return {"error": "target_page required"}
    fired = await show.goto(drivers, int(req.target_page), _opts_from(req))
    return {"ok": fired, "rejected": not fired,
            "error": None if fired else _BUSY_MSG, **show.state()}


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


def _parse_addr(addr: str) -> int:
    """'0x602E' / '24622' → int. A typo is a bad request, not a 500."""
    try:
        return int(addr, 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"bad register address {addr!r} (use 0x602E or 24622)")


@app.get("/api/reg/{motor_key}/{addr}")
async def read_reg(motor_key: str, addr: str, count: int = 1):
    """Raw holding-register read for bench checks, e.g. /api/reg/gw4.1/0x602E
    (Pr8.46 digital inputs — watch it flip while you trigger the home sensor)."""
    d = drivers.get(motor_key)
    if d is None or not hasattr(d, "modbus"):
        return {"error": "unknown or simulated motor"}
    a = _parse_addr(addr)
    regs = await d.modbus.read_holding_registers(d.slave_id, a, count)
    return {"addr": f"0x{a:04X}", "values": regs, "hex": [f"0x{v:04X}" for v in regs], "bin": [f"{v:016b}" for v in regs]}


class RegWrite(BaseModel):
    values: list[int]
    save: bool = False


@app.post("/api/reg/{motor_key}/{addr}")
async def write_reg(motor_key: str, addr: str, req: RegWrite):
    """Raw holding-register write for bench tuning (e.g. homing speeds
    0x600F/0x6010). save=true also persists to EEPROM."""
    d = drivers.get(motor_key)
    if d is None or not hasattr(d, "modbus"):
        return {"error": "unknown or simulated motor"}
    a = _parse_addr(addr)
    await d.modbus.write_registers(d.slave_id, a, [int(v) & 0xFFFF for v in req.values])
    if req.save:
        await d.save_params()
    regs = await d.modbus.read_holding_registers(d.slave_id, a, len(req.values))
    return {"addr": f"0x{a:04X}", "values": regs, "saved": req.save}


@app.get("/api/config")
async def get_config():
    return {
        **{k: config.get(k) for k in
           ("mode", "map", "use_spare", "motion", "motor_defaults", "server")},
        "limits": {
            "max_gateways": MAX_GATEWAYS,
            "max_motors_per_gateway": MAX_MOTORS_PER_GATEWAY,
            "max_total_motors": MAX_TOTAL_MOTORS,
        },
    }


@app.post("/api/config")
async def update_config(new_cfg: dict):
    """Only mode / use_spare / motion are user-editable; gateways and motors
    come from the map file. Saving rebuilds the runtime in place."""
    global config
    for section in ("mode", "use_spare", "motion"):
        if section in new_cfg:
            config[section] = new_cfg[section]
    save_config(config)
    try:
        config = load_config()
    except Exception as e:
        return {"ok": False, "applied": False, "reload_error": str(e)}
    try:
        await _reload_runtime()
        return {"ok": True, "config": {k: config[k] for k in ("mode", "use_spare", "motion")}, "applied": True}
    except Exception as e:
        return {"ok": False, "applied": False, "reload_error": str(e)}


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
    """Cache lookup + post-processing (zero offset, degrees, face). Stays
    ``async def`` so callers (and _build_status's gather) don't need to
    change even though the poller already did the actual I/O."""
    d = drivers.get(key)
    st = status_cache.get(key)
    if d is None or st is None:
        return dict(_OFFLINE_ST)
    st = dict(st)
    if not st.get("offline"):
        raw_pulses = int(st.get("position_pulses", 0))
        display_pulses = raw_pulses - zero_offsets.get(key, 0)
        st["position_pulses"] = display_pulses
        st["position_deg"] = round(d.pulses_to_deg(display_pulses), 2)  # per-driver PPR
        st["current_face"] = face_for_position(st["position_deg"])
    else:
        st["current_face"] = None
    return st


async def _build_status() -> dict:
    """Emit a flat motor-keyed dict from status_cache (no I/O here — the
    per-cabinet pollers keep the cache warm in the background, so this no
    longer blocks the WS broadcast / keepalive on live modbus reads)."""
    specs = _motor_specs()
    extras = config.get("motor_extras", {})
    inventory = []
    for s in specs:
        key = build_motor_key(s["gateway"], s["slave_id"])
        ex = extras.get(key, {})
        inventory.append({
            "motor_key": key,
            "label": ex.get("label") or motor_label(s["gateway"], s["slave_id"]),
            "gateway": s["gateway"],
            "slave_id": int(s["slave_id"]),
            "driver_type": s["driver_type"],
            "motor": ex.get("motor"), "cabinet": ex.get("cabinet"),
            "x": ex.get("x"), "y": ex.get("y"), "apex_deg": ex.get("apex_deg"),
            "estimated": ex.get("estimated", False),
        })

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
        "homing": homing_state,
    }
