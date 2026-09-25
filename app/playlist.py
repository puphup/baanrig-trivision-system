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
from .config import MAX_RPM      # hard cap shared with the drivers
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


# ponytail: accel/decel registers are ms per 1000 rpm, so ramps last ≤ ~25 ms at 12 rpm
# (plus the S-curve filter) and are ignored; the runner waits for all-stopped anyway,
# so a few ms of overrun is harmless.
def rpm_for(turn_s: float, angle_deg: float) -> int:
    """Constant speed that covers angle in turn seconds. Clamped to 1…MAX_RPM."""
    return max(1, min(MAX_RPM, round(angle_deg * 60.0 / (360.0 * float(turn_s)))))


def min_turn(angle_deg: float) -> float:
    return angle_deg / (MAX_RPM * 6.0)


def validate(doc: dict) -> tuple[list[str], list[str]]:
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
                errs.append(f"step {i}: {k} must be {lo:g}…{hi:g}"
                            + (f" s ({MAX_RPM} rpm cap)" if k == "turn" else ""))
            return v
        seq = s.get("seq")
        if seq not in (1, 2, 3):
            errs.append(f"step {i}: seq must be 1, 2 or 3")
        angle = s.get("angle")
        if angle not in (120, 240):
            errs.append(f"step {i}: angle must be 120 or 240")
            angle = 120
        turn = num("turn", min_turn(angle), 20)
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
                        run=0, phase="starting", failed=[], loop=bool(loop))
        self.task = asyncio.create_task(self._run(doc))
        return True

    async def stop(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            # ponytail: drives may still be mid-turn; show.busy blocks Next/Auto/Run
            # until the wave has landed, so nothing interrupts them off-face.
            self.show.settle(self._drivers())
        self._st.update(running=False, phase="idle")

    async def _run(self, doc: dict) -> None:
        try:
            while True:
                if any(f != 0 for f in (await self._faces()).values()):
                    self._st["phase"] = "homing"
                    await self._home()
                    await self.show.wait_all_stopped(self._drivers(), timeout=60)
                for i, step in enumerate(doc["playlist"], 1):
                    self._st["step"] = i
                    for run in range(int(step["runs"])):
                        self._st["run"] = run + 1
                        await self._one(step, last=run == int(step["runs"]) - 1)
                if not self._st["loop"]:
                    return
        except asyncio.CancelledError:
            return
        except Exception as e:
            # ponytail: this codebase has no logging module (grep shows none in app/*.py);
            # matches the existing bracket-tag print convention (server.py's [setup]/[home-memory])
            print(f"[playlist] {self._st['name']!r} failed: {e}")
            self._st["phase"] = "error"
        finally:
            self._st["running"] = False
            if self._st["phase"] != "error":
                self._st["phase"] = "idle"

    async def _one(self, step: dict, last: bool) -> None:
        self._st["phase"] = "moving"
        m = self._motion()
        drivers = self._drivers()
        t0 = time.monotonic()
        moves = plan_step(step, await self._faces(), self.panels, self._wall_forward())
        if moves:
            rpm = rpm_for(step["turn"], step["angle"])
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
