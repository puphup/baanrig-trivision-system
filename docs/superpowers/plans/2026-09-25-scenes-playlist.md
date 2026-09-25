# Scenes / Playlists Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run, save, import and export BAANRIG-simulator playlists on the real wall, with hardware-derived limits enforced on import.

**Architecture:** A new pure module `app/playlist.py` turns a simulator step into per-motor relative moves (delta, delay) using the layout file and the faces the poller already reports, plus a small asyncio runner. `show.py` gains one generalised `fire_moves()`; `server.py` adds file-backed CRUD and run routes; the Control page gets a Scenes tab.

**Tech Stack:** Python 3.14, FastAPI, asyncio, vanilla JS. Tests are plain-assert scripts run with `./venv/bin/python test_*.py` (no pytest).

**Spec:** `docs/superpowers/specs/2026-09-25-scenes-playlist-design.md`

## Global Constraints

- Ponytail mode: minimum code, no new dependencies, `# ponytail:` comment on every deliberate simplification.
- Playlist document is the simulator JSON verbatim: `app == "lv-trivision-corridor"`, `version == 3`; unknown keys preserved.
- Face 1/2/3 == simulator A/B/C. Parity by panel number: `motor % 2` → odd/even.
- Wave order and `s` come from `trivision_layout.json` only, never from motor_map x.
- `rpm = angle*60 / (360 * (turn − (accel+decel)/2000))`, clamped 1…40; validation rejects a turn that would clamp.
- Next step starts at `max(all_stopped, t0 + nextAt) + pauseAfter`.
- New config key `wall_forward = {"long": "cw", "short": "ccw"}`, persisted.
- Playlists live in `playlists/` next to `config.json`; the kiosk rsync must exclude it.
- Never move real motors from a test: every test sets `cfg["mode"] = "simulation"`.
- Do not commit unless the user asks (user rule). Tasks below therefore end with "tests pass", not with a commit.
- Deviation from the spec, agreed by the planner: `GET /api/limits` is not extended. The save/import
  response already carries the exact limit in its error text, so the UI needs no second source.

---

### Task 1: playlist.py — layout, validation, planning, rpm

**Files:**
- Create: `app/playlist.py`
- Test: `test_playlist.py`

**Interfaces:**
- Consumes: `trivision_layout.json` (repo root, next to `motor_map.json`), `config["motor_extras"][key]["motor"]`.
- Produces: `load_layout(path) -> dict[int, tuple[str, float]]`, `validate(doc, accel_ms, decel_ms) -> tuple[list[str], list[str]]` (errors, warnings), `plan_step(step, faces, panels, wall_forward) -> list[tuple[str, float, int]]`, `rpm_for(turn_s, angle_deg, accel_ms, decel_ms) -> int`, constants `APP_ID`, `APP_VERSION`, `MAX_RPM`.

- [ ] **Step 1: Write the failing test**

```python
"""Playlist planning: layout order, validation limits, per-motor moves.
Run: ./venv/bin/python test_playlist.py"""
import asyncio
from pathlib import Path
from app import playlist as P

ROOT = Path(__file__).parent


def test_layout():
    lay = P.load_layout(ROOT / "trivision_layout.json")
    assert len(lay) == 231
    assert lay[137] == ("long", 0.0) and lay[231][0] == "short"
    assert abs(lay[1][1] - 1.0) < 1e-9 and abs(lay[138][1] - 1.0) < 1e-9
    assert lay[231][1] > 0.0 and lay[231][1] < 0.2      # short wall starts inside the corridor


def test_rpm():
    assert P.rpm_for(2.5, 120, 500, 900) == 11
    assert P.rpm_for(1.0, 120, 500, 900) == P.MAX_RPM        # clamped
    assert P.rpm_for(100, 120, 500, 900) == 1


STEP4 = {"seq": 3, "turn": 2.5, "nextAt": 12.5, "pauseAfter": 0, "odd": "A", "even": "A",
         "dirLong": "ccw", "dirShort": "cw", "angle": 240, "runs": 1, "sweep": 10}
WF = {"long": "cw", "short": "ccw"}
# 4 panels: two per wall. key -> (motor number, wall, s)
PANELS = {"gw1.1": (1, "long", 1.0), "gw7.5": (137, "long", 0.0),
          "gw8.1": (138, "short", 1.0), "gw11.9": (231, "short", 0.1)}


def test_plan_turn_to_backward():
    faces = {k: 2 for k in PANELS}                      # everyone on C
    moves = dict((k, (d, ms)) for k, d, ms in P.plan_step(STEP4, faces, PANELS, WF))
    assert moves["gw1.1"] == (-240.0, 0) and moves["gw7.5"] == (-240.0, 10000)
    assert moves["gw8.1"][0] == -240.0 and moves["gw11.9"] == (-240.0, 9000)


def test_plan_every_other_and_stay():
    step = {"seq": 2, "turn": 2, "nextAt": 4, "pauseAfter": 0, "odd": "B", "even": "stay",
            "dirLong": "cw", "dirShort": "ccw", "angle": 120, "runs": 1, "sweep": 10}
    faces = {k: 0 for k in PANELS}
    moves = P.plan_step(step, faces, PANELS, WF)
    assert sorted(k for k, _, _ in moves) == ["gw1.1", "gw11.9", "gw7.5"]   # odd panels only
    assert all(d == 120.0 and ms == 0 for _, d, ms in moves)
    # already on B → k = 0 → omitted
    assert P.plan_step(step, {k: 1 for k in PANELS}, PANELS, WF) == []


def test_plan_next_240_wave_in():
    step = {"seq": 1, "turn": 2, "nextAt": 12, "pauseAfter": 0, "odd": "next", "even": "next",
            "dirLong": "cw", "dirShort": "ccw", "angle": 240, "runs": 1, "sweep": 10}
    moves = dict((k, (d, ms)) for k, d, ms in P.plan_step(step, {k: 0 for k in PANELS}, PANELS, WF))
    assert moves["gw7.5"] == (240.0, 0) and moves["gw1.1"] == (240.0, 10000)


def test_validate():
    good = {"app": P.APP_ID, "version": 3, "title": "t", "playlist": [STEP4]}
    errs, warns = P.validate(good, 500, 900)
    assert errs == [] and warns == [], (errs, warns)
    bad = dict(good, playlist=[dict(STEP4, turn=1.0, angle=90, seq=4, dirShort="ccw")])
    errs, _ = P.validate(bad, 500, 900)
    assert any("turn" in e for e in errs) and any("angle" in e for e in errs)
    assert any("seq" in e for e in errs) and any("opposite" in e for e in errs)
    errs, _ = P.validate(dict(good, app="other"), 500, 900)
    assert errs and "app" in errs[0]
    _, warns = P.validate(dict(good, playlist=[dict(STEP4, nextAt=1)]), 500, 900)
    assert warns and "nextAt" in warns[0]


if __name__ == "__main__":
    for fn in [test_layout, test_rpm, test_plan_turn_to_backward, test_plan_every_other_and_stay,
               test_plan_next_240_wave_in, test_validate]:
        fn()
    print("test_playlist OK")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./venv/bin/python test_playlist.py`
Expected: `ImportError`/`AttributeError` because `app.playlist` does not exist.

- [ ] **Step 3: Write the module**

```python
"""BAANRIG simulator playlists on the real wall.

A playlist document is the simulator's JSON verbatim (see TRIVISION_SIMULATOR.md §3–4).
This module turns one step into per-motor RELATIVE moves and validates the limits
the hardware can actually meet.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

APP_ID = "lv-trivision-corridor"
APP_VERSION = 3
MAX_RPM = 40                     # UI/driver cap: above this the prisms shake
FACES = "ABC"                    # index 0/1/2 == our face 1/2/3
RULES = ("stay", "next", "A", "B", "C")

Move = tuple[str, float, int]    # (motor_key, delta_deg, delay_ms)


def load_layout(path: str | Path) -> dict[int, tuple[str, float]]:
    """panel number -> (wall, s). s = 0 at the entrance, 1 at the exit, computed
    across BOTH walls exactly like the simulator (same X on both walls starts together)."""
    lay = json.loads(Path(path).read_text())
    pts = [("long", 137 - i, p[0]) for i, p in enumerate(lay["long"])]
    pts += [("short", 231 - i, p[0]) for i, p in enumerate(lay["short"])]
    xs = [x for _, _, x in pts]
    x_max, x_min = max(xs), min(xs)
    return {n: (wall, (x_max - x) / (x_max - x_min)) for wall, n, x in pts}


def rpm_for(turn_s: float, angle_deg: float, accel_ms: int, decel_ms: int) -> int:
    """Trapezoid: constant speed for turn − (accel+decel)/2. Clamped to 1…MAX_RPM."""
    flat = float(turn_s) - (int(accel_ms) + int(decel_ms)) / 2000.0
    if flat <= 0:
        return MAX_RPM
    return max(1, min(MAX_RPM, round(angle_deg * 60.0 / (360.0 * flat))))


def min_turn(angle_deg: float, accel_ms: int, decel_ms: int) -> float:
    return angle_deg / (MAX_RPM * 6.0) + (int(accel_ms) + int(decel_ms)) / 2000.0


def validate(doc: dict, accel_ms: int, decel_ms: int) -> tuple[list[str], list[str]]:
    """(errors, warnings). Errors block saving; warnings only mean the simulator
    would time the step differently from the wall."""
    errs: list[str] = []
    warns: list[str] = []
    if not isinstance(doc, dict) or doc.get("app") != APP_ID:
        return [f"app must be {APP_ID!r}"], warns
    if doc.get("version") != APP_VERSION:
        return [f"version must be {APP_VERSION}"], warns
    steps = doc.get("playlist")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 200:
        return ["playlist must hold 1…200 steps"], warns
    for i, s in enumerate(steps, 1):
        def num(k, lo, hi):
            try:
                v = float(s.get(k))
            except (TypeError, ValueError):
                errs.append(f"step {i}: {k} missing")
                return None
            if not lo <= v <= hi:
                errs.append(f"step {i}: {k} must be {lo}…{hi}")
            return v
        seq = s.get("seq")
        if seq not in (1, 2, 3):
            errs.append(f"step {i}: seq must be 1, 2 or 3")
        angle = s.get("angle")
        if angle not in (120, 240):
            errs.append(f"step {i}: angle must be 120 or 240")
            angle = 120
        turn = num("turn", min_turn(angle, accel_ms, decel_ms), 20)
        sweep = num("sweep", 0, 60)
        next_at = num("nextAt", 0, 3600)
        num("pauseAfter", 0, 600)
        num("runs", 1, 99)
        for k in ("odd", "even"):
            if s.get(k) not in RULES:
                errs.append(f"step {i}: {k} must be one of {', '.join(RULES)}")
        dl, ds = s.get("dirLong"), s.get("dirShort")
        if dl not in ("cw", "ccw") or ds not in ("cw", "ccw"):
            errs.append(f"step {i}: dirLong/dirShort must be cw or ccw")
        elif dl == ds:
            errs.append(f"step {i}: walls must turn opposite (dirLong != dirShort)")
        if None not in (turn, sweep, next_at):
            need = turn + (sweep if seq in (1, 3) else 0)
            if next_at < need:
                warns.append(f"step {i}: nextAt {next_at:g} < {need:g}; the simulator overlaps "
                             f"moves here, the wall waits for motors to stop")
    return errs, warns


def plan_step(step: dict, faces: dict[str, int], panels: dict[str, tuple[int, str, float]],
              wall_forward: dict[str, str]) -> list[Move]:
    """faces: motor_key -> 0/1/2 (A/B/C). panels: motor_key -> (panel number, wall, s).
    Returns one move per motor that has to turn. delta_deg is in OUR units where
    +120° always goes A→B→C; cw/ccw only decides forward/backward per wall."""
    out: list[Move] = []
    k2 = 2 if step.get("angle") == 240 else 1
    sweep_ms = float(step.get("sweep", 0)) * 1000.0
    for key, (num, wall, s) in panels.items():
        cur = faces.get(key)
        if cur is None:
            continue                                # offline: skipped this step
        rule = step["odd" if num % 2 else "even"]
        fwd = step["dirLong" if wall == "long" else "dirShort"] == wall_forward[wall]
        if rule == "stay":
            k = 0
        elif rule == "next":
            k = k2
        else:
            t = FACES.index(rule)
            k = (t - cur) % 3 if fwd else (cur - t) % 3
        if k == 0:
            continue
        seq = step["seq"]
        delay = 0.0 if seq == 2 else (s if seq == 1 else 1.0 - s) * sweep_ms
        out.append((key, (1 if fwd else -1) * k * 120.0, int(round(delay))))
    return out
```

- [ ] **Step 4: Run the test**

Run: `./venv/bin/python test_playlist.py`
Expected: `test_playlist OK`

---

### Task 2: show.fire_moves() and a runner-safe wait

**Files:**
- Modify: `app/show.py` (`_fire_transition`, `_wait_all_stopped`, `_settle`)
- Test: `test_playlist.py` (append)

**Interfaces:**
- Produces: `ShowController.fire_moves(drivers, moves: list[tuple[str, float, int]], speed_rpm, accel, decel)` — enable, stage per-motor delta, trigger on delay. `ShowController.wait_all_stopped(drivers, timeout=60.0, stop=None)` — public; `stop` is a zero-arg callable that returns True to abandon the wait early (defaults to "never"). Existing auto-loop passes `stop=lambda: not self.auto.running`.

- [ ] **Step 1: Append the failing test**

```python
async def _fire_moves_sim():
    from app import server as S
    from app.config import load_config
    cfg = load_config()
    cfg["mode"] = "simulation"
    S.config = cfg
    await S._reload_runtime()
    try:
        keys = list(S.drivers)[:3]
        moves = [(keys[0], 120.0, 0), (keys[1], -240.0, 50), (keys[2], 0.0, 0)]
        await S.show.fire_moves(S.drivers, moves, 40, 200, 200)
        await S.show.wait_all_stopped(S.drivers, timeout=20)
        st = [await S.drivers[k].read_status() for k in keys]
        assert abs(st[0]["position_deg"] - 120) < 1 and abs(st[1]["position_deg"] + 240) < 1, st
        assert st[2]["position_deg"] == 0.0 and not any(s["running"] for s in st), st
    finally:
        await S._stop_pollers()


def test_fire_moves():
    asyncio.run(_fire_moves_sim())
```

Add `test_fire_moves` to the `__main__` list.

- [ ] **Step 2: Run it to verify it fails**

Run: `./venv/bin/python test_playlist.py`
Expected: `AttributeError: 'ShowController' object has no attribute 'fire_moves'`

- [ ] **Step 3: Refactor show.py**

Replace the body of `_fire_transition` from `delta_deg = delta_pages * PAGE_STEP_DEG` to the end of the method with:

```python
        delta_deg = delta_pages * PAGE_STEP_DEG
        await self.fire_moves(drivers, [(k, delta_deg, dly) for k, dly in schedule],
                              opts.speed_rpm, opts.accel, opts.decel)

    async def fire_moves(self, drivers: dict[str, MotorDriver], moves: list[tuple[str, float, int]],
                         speed_rpm: int, accel: int, decel: int) -> None:
        """Enable → stage every (key, delta_deg) → trigger each on its delay_ms.
        Two-phase so all triggers are a single tiny write and start within a few
        ms per bus; effects and playlists both come through here."""
        async def _arm(motor_key: str):
            d = drivers.get(motor_key)
            if d is None:
                return
            try:
                await d.enable()
            except Exception:
                pass
        await asyncio.gather(*(_arm(k) for k, _, _ in moves))

        async def _stage(motor_key: str, delta_deg: float):
            d = drivers.get(motor_key)
            if d is None:
                return
            try:
                await d.stage_move("relative", delta_deg, speed_rpm, accel, decel)
            except Exception:
                pass
        await asyncio.gather(*(_stage(k, dd) for k, dd, _ in moves))

        async def _trigger(motor_key: str, delay_ms: int):
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000.0)
            d = drivers.get(motor_key)
            if d is None:
                return
            try:
                await d.trigger_move()
            except Exception:
                pass
        await asyncio.gather(*(_trigger(k, dly) for k, _, dly in moves))
```

Keep the existing comment block about two-phase start above `fire_moves` (move it there). Delete the old `_arm/_stage/_trigger` closures from `_fire_transition`.

Rename `_wait_all_stopped` to `wait_all_stopped` with signature `(self, drivers, timeout: float = 60.0, stop=None)`; replace `if not self.auto.running: return` with `if stop is not None and stop(): return`. Update callers: `_settle` → `await self.wait_all_stopped(drivers)`; `_auto_loop` → `await self.wait_all_stopped(drivers, stop=lambda: not self.auto.running)`. Add above the rename: `# ponytail: the old early-return on "auto not running" also cut the manual settle short; stop() is explicit now.`

- [ ] **Step 4: Run all tests**

Run: `for t in test_playlist.py test_pollers.py test_operator_routes.py test_motor_map.py; do ./venv/bin/python $t || break; done`
Expected: every script prints its OK line.

---

### Task 3: PlaylistRunner

**Files:**
- Modify: `app/playlist.py` (append)
- Test: `test_playlist.py` (append)

**Interfaces:**
- Consumes: `ShowController.fire_moves`, `ShowController.wait_all_stopped` (Task 2), `plan_step`, `rpm_for`.
- Produces: `class PlaylistRunner(show, drivers_getter, panels, read_faces, home_all, motion_getter, wall_forward_getter)`; `start(name, doc, loop=False) -> bool`, `stop()`, `state() -> dict`.

- [ ] **Step 1: Append the failing test**

```python
CUSTOMER = {"app": P.APP_ID, "version": 3, "title": "customer test", "playlist": [
    {"seq": 2, "turn": 1.5, "nextAt": 1.5, "pauseAfter": 0.5, "odd": "stay", "even": "stay",
     "dirLong": "cw", "dirShort": "ccw", "angle": 120, "runs": 1, "sweep": 1},
    {"seq": 1, "turn": 1.5, "nextAt": 2.5, "pauseAfter": 0.5, "odd": "B", "even": "B",
     "dirLong": "cw", "dirShort": "ccw", "angle": 120, "runs": 1, "sweep": 1},
    {"seq": 2, "turn": 1.5, "nextAt": 1.5, "pauseAfter": 0.5, "odd": "C", "even": "C",
     "dirLong": "cw", "dirShort": "ccw", "angle": 120, "runs": 1, "sweep": 1},
    {"seq": 3, "turn": 2.0, "nextAt": 3.0, "pauseAfter": 0, "odd": "A", "even": "A",
     "dirLong": "ccw", "dirShort": "cw", "angle": 240, "runs": 1, "sweep": 1},
]}   # every step passes validate() with the default 500/900 ms ramps and raises no warning


async def _runner_sim():
    from app import server as S
    from app.config import load_config
    cfg = load_config()
    cfg["mode"] = "simulation"
    S.config = cfg
    await S._reload_runtime()
    try:
        # start from face B on one motor: the runner must home first
        k0 = next(iter(S.drivers))
        await S.drivers[k0].start_move("relative", 120, 40, 200, 200)
        await S.show.wait_all_stopped(S.drivers, timeout=10)
        assert S.runner.start("customer", CUSTOMER, loop=False)
        assert not S.runner.start("customer", CUSTOMER)          # already running
        while S.runner.state()["running"]:
            await asyncio.sleep(0.2)
        faces = await S._faces()
        assert set(faces.values()) == {0}, faces                  # everyone back on A
        assert S.runner.state()["failed"] == []
        assert S.show.current_page == 1
    finally:
        await S.runner.stop()
        await S._stop_pollers()


def test_runner():
    asyncio.run(_runner_sim())
```

Add `test_runner` to the `__main__` list (after `test_fire_moves`).

- [ ] **Step 2: Run it to verify it fails**

Run: `./venv/bin/python test_playlist.py`
Expected: `AttributeError: module 'app.server' has no attribute 'runner'`

- [ ] **Step 3: Append the runner to playlist.py**

```python
class PlaylistRunner:
    """One playlist at a time. Next step starts at max(all stopped, t0 + nextAt) + pauseAfter,
    so a slow turn never eats into the hold and the simulator's rhythm is kept when the
    wall is fast enough."""

    def __init__(self, show, drivers_getter, panels, read_faces, home_all, motion_getter,
                 wall_forward_getter):
        self.show = show
        self._drivers = drivers_getter          # () -> dict[key, driver]
        self.panels = panels                    # key -> (panel number, wall, s)
        self._faces = read_faces                # async () -> dict[key, 0/1/2]
        self._home = home_all                   # async () -> None (software home to face A)
        self._motion = motion_getter            # () -> {"accel":..,"decel":..}
        self._wall_forward = wall_forward_getter
        self.task: asyncio.Task | None = None
        self._st = {"running": False, "name": None, "step": 0, "steps": 0, "run": 0,
                    "phase": "idle", "failed": [], "loop": False}

    def state(self) -> dict:
        return dict(self._st)

    def start(self, name: str, doc: dict, loop: bool = False) -> bool:
        if self._st["running"] or self.show.busy or self.show.auto.running:
            return False
        self._st.update(running=True, name=name, step=0, steps=len(doc["playlist"]),
                        run=0, phase="homing", failed=[], loop=bool(loop))
        self.task = asyncio.create_task(self._run(doc))
        return True

    async def stop(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self._st.update(running=False, phase="idle")

    async def _run(self, doc: dict) -> None:
        try:
            faces = await self._faces()
            if any(f != 0 for f in faces.values()):
                await self._home()
                await self.show.wait_all_stopped(self._drivers(), timeout=60)
            while True:
                for i, step in enumerate(doc["playlist"], 1):
                    self._st["step"] = i
                    for run in range(int(step["runs"])):
                        self._st["run"] = run + 1
                        await self._one(step, last=run == int(step["runs"]) - 1)
                if not self._st["loop"]:
                    return
        except asyncio.CancelledError:
            return
        finally:
            self._st.update(running=False, phase="idle")

    async def _one(self, step: dict, last: bool) -> None:
        m = self._motion()
        drivers = self._drivers()
        t0 = time.monotonic()
        moves = plan_step(step, await self._faces(), self.panels, self._wall_forward())
        self._st["phase"] = "moving"
        if moves:
            rpm = rpm_for(step["turn"], step["angle"], m["accel"], m["decel"])
            await self.show.fire_moves(drivers, moves, rpm, m["accel"], m["decel"])
            await self.show.wait_all_stopped(drivers, timeout=60)
            faces = await self._faces()
            # a motor that moved but now reads offline is "stuck" for the status line
            self._st["failed"] = [k for k, _, _ in moves if k not in faces]
            # ponytail: current_page is display-only now; the per-motor truth is the status cache
            if faces:
                self.show.current_page = next(iter(faces.values())) + 1
        self._st["phase"] = "hold"
        wait = max(0.0, float(step["nextAt"]) - (time.monotonic() - t0))
        if last:
            wait += float(step["pauseAfter"])
        await asyncio.sleep(wait)
```

- [ ] **Step 4: Wire it in server.py (minimum for the test)**

In `app/server.py` add to the imports: `from .playlist import PlaylistRunner, load_layout, validate as validate_playlist, APP_ID as PLAYLIST_APP`. After `show: ShowController = ShowController()` add:

```python
PLAYLIST_DIR = CONFIG_PATH.parent / "playlists"     # rsync must exclude it, like home_state.json
_LAYOUT = load_layout(CONFIG_PATH.parent / "trivision_layout.json")


def _panels() -> dict[str, tuple[int, str, float]]:
    out = {}
    for key, ex in config.get("motor_extras", {}).items():
        wall, s = _LAYOUT[int(ex["motor"])]
        out[key] = (int(ex["motor"]), wall, s)
    return out


async def _faces() -> dict[str, int]:
    """Online motors only: key -> 0/1/2 (A/B/C) from the poller cache."""
    out = {}
    for key in drivers:
        st = await _read_one_status(key)
        if not st.get("offline") and st.get("current_face"):
            out[key] = int(st["current_face"]) - 1
    return out


runner = PlaylistRunner(show, lambda: drivers, {}, _faces,
                        lambda: home_motor(HomeRequest()),
                        lambda: config["motion"], lambda: config["wall_forward"])
```

`HomeRequest` and `home_motor` are defined later in the module; the lambdas resolve them at call time, so the order is fine. In `_reload_runtime`, right after `await show.stop_auto()`, add `await runner.stop()` and after the new drivers are installed add `runner.panels = _panels()`. In `estop()` add `await runner.stop()` as the first line. In `show_auto_start` add `await runner.stop()` first.

Note: `config["wall_forward"]` needs Task 4; until then the test would `KeyError`. Do Task 4 Step 3 (config default) before running this test.

- [ ] **Step 5: Run the test**

Run: `./venv/bin/python test_playlist.py`
Expected: `test_playlist OK` (the runner test takes about 15 s of simulated moves).

---

### Task 4: config wall_forward + playlist routes

**Files:**
- Modify: `app/config.py` (DEFAULTS, `_normalize`, `_PERSISTED`)
- Modify: `app/server.py` (routes, `/api/config`, WS payload)
- Test: `test_playlist.py` (append)

**Interfaces:**
- Produces routes: `GET /api/playlists`, `GET /api/playlists/{name}`, `PUT /api/playlists/{name}`, `DELETE /api/playlists/{name}`, `POST /api/playlists/{name}/run` `{loop}`, `POST /api/playlists/stop`, `GET /api/playlists/state`. Names are `[A-Za-z0-9_-]{1,64}`. WS status gains `"playlist": runner.state()`.

- [ ] **Step 1: Append the failing test**

```python
async def _routes_sim():
    from app import server as S
    from app.config import load_config
    import shutil
    cfg = load_config()
    cfg["mode"] = "simulation"
    S.config = cfg
    S.PLAYLIST_DIR = ROOT / "playlists_test"
    shutil.rmtree(S.PLAYLIST_DIR, ignore_errors=True)
    await S._reload_runtime()
    try:
        assert cfg["wall_forward"] == {"long": "cw", "short": "ccw"}
        r = await S.playlist_put("cust", CUSTOMER)
        assert r["ok"] and r["warnings"] == [], r
        r = await S.playlist_put("bad name!", CUSTOMER)
        assert r["error"], r
        r = await S.playlist_put("bad", dict(CUSTOMER, app="x"))
        assert r["error"] and not (S.PLAYLIST_DIR / "bad.json").exists(), r
        lst = await S.playlist_list()
        assert [p["name"] for p in lst["playlists"]] == ["cust"] and lst["playlists"][0]["steps"] == 4
        assert (await S.playlist_get("cust")) == CUSTOMER
        r = await S.playlist_run("cust", S.PlaylistRunRequest(loop=False))
        assert r["ok"] and (await S.playlist_state())["running"], r
        r = await S.playlist_stop()
        assert r["ok"] and not (await S.playlist_state())["running"]
        r = await S.playlist_delete("cust")
        assert r["ok"] and (await S.playlist_list())["playlists"] == []
        assert "playlist" in (await S._build_status())
    finally:
        await S.runner.stop()
        await S._stop_pollers()
        shutil.rmtree(S.PLAYLIST_DIR, ignore_errors=True)


def test_routes():
    asyncio.run(_routes_sim())
```

Add `test_routes` to the `__main__` list.

- [ ] **Step 2: Run it to verify it fails**

Run: `./venv/bin/python test_playlist.py`
Expected: `AttributeError: module 'app.server' has no attribute 'playlist_put'` (or `KeyError: 'wall_forward'` if Task 3 ran first).

- [ ] **Step 3: Config**

In `app/config.py` DEFAULTS, after the `home_sensor_cabinets` line add:

```python
    # which simulator direction word means A→B→C (our +120°) on each wall; flip a word
    # if a wall turns out to be built the other way round (TRIVISION_SIMULATOR.md CONFIRM #1/#4)
    "wall_forward": {"long": "cw", "short": "ccw"},
```

In `_normalize`, after the `home_sensor_cabinets` block add:

```python
    wf = cfg.get("wall_forward") or {}
    cfg["wall_forward"] = {w: (wf.get(w) if wf.get(w) in ("cw", "ccw") else DEFAULTS["wall_forward"][w])
                           for w in ("long", "short")}
```

Add `"wall_forward"` to `_PERSISTED` (after `"home_sensor_cabinets"`), and to the tuple of keys returned by `GET /api/config` in server.py.

- [ ] **Step 4: Routes**

In `app/server.py`, after the show routes (`show_auto_stop`), add:

```python
# ---------------------------------------------------------------------------
# Playlists (simulator JSON, stored verbatim in playlists/<name>.json)
# ---------------------------------------------------------------------------

class PlaylistRunRequest(BaseModel):
    loop: bool = False


def _playlist_path(name: str) -> Path | None:
    import re
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name or ""):
        return None
    return PLAYLIST_DIR / f"{name}.json"


@app.get("/api/playlists")
async def playlist_list():
    out = []
    for p in sorted(PLAYLIST_DIR.glob("*.json")) if PLAYLIST_DIR.exists() else []:
        try:
            doc = json.loads(p.read_text())
            out.append({"name": p.stem, "title": doc.get("title", p.stem), "steps": len(doc["playlist"])})
        except Exception:
            continue      # a hand-edited broken file just doesn't list
    return {"playlists": out}


@app.get("/api/playlists/state")
async def playlist_state():
    return runner.state()


@app.get("/api/playlists/{name}")
async def playlist_get(name: str):
    p = _playlist_path(name)
    if p is None or not p.exists():
        raise HTTPException(404, "no such playlist")
    return json.loads(p.read_text())


@app.put("/api/playlists/{name}")
async def playlist_put(name: str, doc: dict):
    """Import / save. The body is the simulator document; errors block, warnings don't."""
    p = _playlist_path(name)
    if p is None:
        return {"error": "name: letters, digits, - and _ only"}
    m = config["motion"]
    errs, warns = validate_playlist(doc, m["accel"], m["decel"])
    if errs:
        return {"error": "; ".join(errs), "errors": errs, "warnings": warns}
    PLAYLIST_DIR.mkdir(exist_ok=True)
    p.write_text(json.dumps(doc, indent=1))
    return {"ok": True, "name": name, "warnings": warns}


@app.delete("/api/playlists/{name}")
async def playlist_delete(name: str):
    p = _playlist_path(name)
    if p is None or not p.exists():
        raise HTTPException(404, "no such playlist")
    p.unlink()
    return {"ok": True}


@app.post("/api/playlists/{name}/run")
async def playlist_run(name: str, req: PlaylistRunRequest = PlaylistRunRequest()):
    if sequencer is not None and sequencer.active:
        return {"error": "Sequence in progress"}
    if homing_state["active"]:
        return {"error": "Seek Home in progress"}
    doc = await playlist_get(name)
    if not runner.start(name, doc, req.loop):
        return {"error": "A playlist, auto-cycle or flip is still running"}
    return {"ok": True, **runner.state()}


@app.post("/api/playlists/stop")
async def playlist_stop():
    await runner.stop()
    return {"ok": True, **runner.state()}
```

Route order matters: `/api/playlists/state` and `/api/playlists/stop` are declared before `/{name}` routes of the same method (`state` is GET before `GET /{name}`; `stop` is POST and `/{name}/run` has a different shape, so no clash). In the WS payload (line with `"show": show.state(),`) add `"playlist": runner.state(),`.

- [ ] **Step 5: Run all tests**

Run: `for t in test_playlist.py test_pollers.py test_operator_routes.py test_motor_map.py; do ./venv/bin/python $t || break; done`
Expected: all OK lines.

---

### Task 5: Scenes tab in the Control page

**Files:**
- Modify: `static/index.html` (header tabs, new `tab-scenes` block after `tab-cabinets`, JS at the end of the Trivision Show section, `onStatus`)

**Interfaces:**
- Consumes: the routes from Task 4, `data.playlist` in the WS status, `api()`/`get()`/`showToast()`/`switchTab()` helpers.

- [ ] **Step 1: Header tab**

After the Cabinets tab button add:

```html
      <button type="button" class="tab" data-tab="scenes" onclick="switchTab('scenes'); loadPlaylists()">Scenes</button>
```

- [ ] **Step 2: Tab markup** (insert after the closing `</div>` of `tab-cabinets`, before `<div class="toast"`)

```html
<!-- ============== SCENES TAB ============== -->
<div id="tab-scenes" class="tab-content">
  <div class="grid-card">
    <div class="grid-toolbar">
      <h2 style="margin:0">Scenes</h2>
      <select id="pl-select" onchange="openPlaylist(this.value)"></select>
      <button type="button" class="btn-sm" onclick="newPlaylist()">New</button>
      <button type="button" class="btn-sm" onclick="V('pl-file').click()">Import</button>
      <input type="file" id="pl-file" accept=".json" hidden onchange="importPlaylist(this.files[0])">
      <a id="pl-export" class="btn-sm" download style="display:none">Export</a>
      <button type="button" class="btn-sm btn-warning" onclick="deletePlaylist()">Delete</button>
      <span class="spacer"></span>
      <button type="button" class="btn-success" onclick="runPlaylist(false)">Run</button>
      <button type="button" class="btn-success" onclick="runPlaylist(true)">Run loop</button>
      <button type="button" class="btn-warning" onclick="api('playlists/stop')">Stop</button>
    </div>
    <div class="field-row">
      <div class="field" style="grid-column: span 2"><label for="pl-title">Title</label><input id="pl-title"></div>
      <div class="field"><label for="pl-name">File name</label><input id="pl-name" placeholder="letters digits - _"></div>
      <button type="button" onclick="savePlaylist()">Save</button>
    </div>
    <table class="cab-table" id="pl-table">
      <thead><tr><th>#</th><th>seq</th><th>turn s</th><th>sweep s</th><th>nextAt s</th><th>pause s</th><th>runs</th>
        <th>odd</th><th>even</th><th>long</th><th>short</th><th>angle</th><th>note</th><th></th></tr></thead>
      <tbody id="pl-rows"></tbody>
    </table>
    <button type="button" class="btn-sm" onclick="addStep()">+ step</button>
    <pre id="pl-msg" style="font-size:.72rem; white-space:pre-line"></pre>
    <div id="pl-status" style="font-size:.8rem; margin-top:6px">idle</div>
    <div style="font-size:.7rem;color:var(--text-dim)">seq 1 = wave in (entrance→exit), 2 = all together, 3 = wave out. Walls must turn opposite. Faces: A Silver, B Monogram, C Gradient.</div>
  </div>
</div>
```

If `.btn-success` does not exist in the stylesheet, use `.btn-warning` for Run too; do not add CSS.

- [ ] **Step 3: JS** (append after `loadShowEffects` in the Trivision Show section)

```js
// ============================ Scenes / playlists ============================
// ponytail: the editor is a plain table over the simulator JSON; no undo, no drag-reorder.
let plDoc = null;
const PL_SEL = (v, opts) => opts.map(o => `<option ${o == v ? 'selected' : ''}>${o}</option>`).join('');
function blankStep() {
  return { seq: 2, turn: 2, sweep: 10, nextAt: 2, pauseAfter: 8, runs: 1, odd: 'next', even: 'next',
           dirLong: 'cw', dirShort: 'ccw', angle: 120, note: '' };
}
async function loadPlaylists(select) {
  const r = await get('playlists');
  const sel = V('pl-select');
  sel.innerHTML = r.playlists.map(p => `<option value="${p.name}">${p.title} (${p.steps})</option>`).join('');
  const name = select || sel.value;
  if (name) { sel.value = name; openPlaylist(name); } else newPlaylist();
}
async function openPlaylist(name) {
  plDoc = await get('playlists/' + name);
  V('pl-name').value = name;
  renderPlaylist();
}
function newPlaylist() {
  plDoc = { app: 'lv-trivision-corridor', version: 3, title: 'New playlist', playlist: [blankStep()] };
  V('pl-name').value = '';
  renderPlaylist();
}
function renderPlaylist() {
  V('pl-title').value = plDoc.title || '';
  V('pl-rows').innerHTML = plDoc.playlist.map((s, i) => `<tr>
    <td>${i + 1}</td>
    <td><select data-i="${i}" data-k="seq">${PL_SEL(s.seq, [1, 2, 3])}</select></td>
    ${['turn', 'sweep', 'nextAt', 'pauseAfter', 'runs'].map(k =>
      `<td><input type="number" step="0.1" style="width:4.5em" data-i="${i}" data-k="${k}" value="${s[k]}"></td>`).join('')}
    <td><select data-i="${i}" data-k="odd">${PL_SEL(s.odd, ['stay', 'next', 'A', 'B', 'C'])}</select></td>
    <td><select data-i="${i}" data-k="even">${PL_SEL(s.even, ['stay', 'next', 'A', 'B', 'C'])}</select></td>
    <td><select data-i="${i}" data-k="dirLong">${PL_SEL(s.dirLong, ['cw', 'ccw'])}</select></td>
    <td><select data-i="${i}" data-k="dirShort">${PL_SEL(s.dirShort, ['cw', 'ccw'])}</select></td>
    <td><select data-i="${i}" data-k="angle">${PL_SEL(s.angle, [120, 240])}</select></td>
    <td><input data-i="${i}" data-k="note" value="${(s.note || '').replace(/"/g, '&quot;')}"></td>
    <td><button type="button" class="btn-sm" onclick="plDoc.playlist.splice(${i},1); renderPlaylist()">✕</button></td>
  </tr>`).join('');
  const exp = V('pl-export');
  exp.href = URL.createObjectURL(new Blob([JSON.stringify(plDoc, null, 1)], { type: 'application/json' }));
  exp.download = (V('pl-name').value || 'playlist') + '.json';
  exp.style.display = '';
}
function readPlaylistTable() {
  plDoc.title = V('pl-title').value;
  $$('#pl-rows [data-k]').forEach(el => {
    const s = plDoc.playlist[+el.dataset.i], k = el.dataset.k;
    s[k] = (k === 'note' || k === 'odd' || k === 'even' || k === 'dirLong' || k === 'dirShort') ? el.value : +el.value;
  });
}
function addStep() { readPlaylistTable(); plDoc.playlist.push(blankStep()); renderPlaylist(); }
async function savePlaylist() {
  readPlaylistTable();
  const name = V('pl-name').value.trim();
  if (!name) { showToast('File name required', 'danger'); return; }
  const res = await fetch('/api/playlists/' + name, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(plDoc) });
  const r = await res.json();
  V('pl-msg').textContent = (r.errors || []).concat((r.warnings || []).map(w => 'warning: ' + w)).join('\n');
  if (r.error) showToast(r.error, 'danger'); else { showToast('Saved', 'success'); loadPlaylists(name); }
}
async function importPlaylist(file) {
  if (!file) return;
  try { plDoc = JSON.parse(await file.text()); } catch { showToast('Not a JSON file', 'danger'); return; }
  V('pl-name').value = file.name.replace(/\.json$/i, '').replace(/[^A-Za-z0-9_-]/g, '_').slice(0, 64);
  renderPlaylist();
  savePlaylist();
}
async function deletePlaylist() {
  const name = V('pl-name').value.trim();
  if (!name || !confirm(`Delete playlist "${name}"?`)) return;
  await fetch('/api/playlists/' + name, { method: 'DELETE' });
  loadPlaylists();
}
async function runPlaylist(loop) {
  const name = V('pl-name').value.trim();
  if (!name) { showToast('Save the playlist first', 'danger'); return; }
  await api(`playlists/${name}/run`, { loop });
}
function updatePlaylistState(p) {
  if (!p) return;
  V('pl-status').textContent = p.running
    ? `running ${p.name}: step ${p.step}/${p.steps} run ${p.run} — ${p.phase}${p.loop ? ' (loop)' : ''}${p.failed.length ? ' — stuck: ' + p.failed.join(' ') : ''}`
    : 'idle';
}
```

In `onStatus`, after `updateShowState(data.show || {});` add `updatePlaylistState(data.playlist);`.

- [ ] **Step 4: Manual check in simulation mode**

Run: `./venv/bin/python run.py` (or the usual start command from README), open `http://localhost:8000`, Scenes tab: New → Save as `smoke` → Run. Expected: status line advances through the steps, motor faces on the wall map change, `playlists/smoke.json` appears. Import the `every other` example from `TRIVISION_SIMULATOR.md` §3 wrapped in the document envelope: it saves with no errors. Set `turn` to 0.5 and Save: an inline error names the minimum turn.

---

### Task 6: README, rsync exclude, simulator doc corrections

**Files:**
- Modify: `README.md` (kiosk deploy rsync line; a "Scenes / playlists" section)
- Modify: `TRIVISION_SIMULATOR.md` (corrections block at the top)

- [ ] **Step 1: README**

Change the rsync line to add `--exclude config.json --exclude playlists`. Add a section:

```markdown
## Scenes / playlists

The Scenes tab plays BAANRIG simulator playlists (`app: lv-trivision-corridor`, version 3) on the
wall. Import the simulator's saved JSON, or build one in the table and Export it back to the
simulator. Files live in `playlists/` next to `config.json` (not synced to the kiosk).

Limits enforced on save/import (the wall cannot do more): `angle` 120 or 240; `turn` at least
`angle/240 + (accel+decel)/2000` seconds (≈1.2 s for 120°, ≈1.7 s for 240° with the default 500/900 ms
ramps) and at most 20 s; `sweep` 0–60 s; `pauseAfter` 0–600 s; `runs` 1–99; the walls must turn
opposite. The next step starts at the later of "all motors stopped" and `nextAt`, plus `pauseAfter`,
so a slow turn never shortens a hold. Face A is the home face; a playlist homes the wall (shortest
path) before its first step if any motor is off face A. `config.json` → `wall_forward` says which
direction word (`cw`/`ccw`) means A→B→C on each wall; flip one if a wall is built the other way.
```

- [ ] **Step 2: Simulator doc corrections**

Insert after the title line of `TRIVISION_SIMULATOR.md`:

```markdown
> **Corrections from the real rig (2026-09-25, controller side):** gateways and drives run **38400** baud, not
> 115200. Cabinet 7's DI3 home switches are wired **N.O. (0x0149 = 0x27)**, not N.C. 0xA7. Drives boot
> **disabled** under software enable; the controller enables before every move. The real motion profile is a
> trapezoid (accel/decel in ms, then constant rpm), not the cubic ease shown here. Triggers on one RS485 bus
> go out one drive at a time (≈7 ms each, ≈150 ms across a 21-drive cabinet). Our controller imports and
> exports this document format unchanged; see README "Scenes / playlists" for the limits it enforces.
```

- [ ] **Step 3: Run the full test set once more**

Run: `for t in test_playlist.py test_pollers.py test_operator_routes.py test_motor_map.py test_status_fast.py test_cabinet_box.py; do ./venv/bin/python $t || break; done`
Expected: every script prints its OK line. Report the output to the user; do not commit.
