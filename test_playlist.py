"""Playlist planning: layout order, validation limits, per-motor moves.
Run: ./venv/bin/python test_playlist.py"""
import asyncio
import json
import time
from pathlib import Path
from app import playlist as P

ROOT = Path(__file__).parent


def test_layout():
    lay = P.load_layout(ROOT / "trivision_layout.json")
    assert len(lay) == 231
    assert lay[121] == ("long", 0.0)                     # long wall's x extreme (rounded corner)
    assert lay[137][0] == "long" and 0.11 < lay[137][1] < 0.12
    assert abs(lay[1][1] - 1.0) < 1e-9 and abs(lay[138][1] - 1.0) < 1e-9
    assert lay[231][0] == "short" and 0.2 < lay[231][1] < 0.3   # short wall starts inside the corridor


def test_rpm():
    assert P.rpm_for(2.5, 120) == 8 and P.rpm_for(2, 120) == 10 and P.rpm_for(1.5, 120) == P.MAX_RPM
    assert P.rpm_for(0.3, 120) == P.MAX_RPM                  # clamped
    assert P.rpm_for(100, 120) == 1
    assert abs(P.min_turn(120) - 5 / 3) < 1e-9 and abs(P.min_turn(240) - 10 / 3) < 1e-9


STEP4 = {"seq": 3, "turn": 4, "nextAt": 14, "pauseAfter": 0, "odd": "A", "even": "A",
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
    step = {"seq": 1, "turn": 4, "nextAt": 14, "pauseAfter": 0, "odd": "next", "even": "next",
            "dirLong": "cw", "dirShort": "ccw", "angle": 240, "runs": 1, "sweep": 10}
    moves = dict((k, (d, ms)) for k, d, ms in P.plan_step(step, {k: 0 for k in PANELS}, PANELS, WF))
    assert moves["gw7.5"] == (240.0, 0) and moves["gw1.1"] == (240.0, 10000)


def test_validate():
    good = {"app": P.APP_ID, "version": 3, "title": "t", "playlist": [STEP4]}
    errs, warns = P.validate(good)
    assert errs == [] and warns == [], (errs, warns)
    bad = dict(good, playlist=[dict(STEP4, turn=0.3, angle=90, seq=4, dirShort="ccw")])
    errs, _ = P.validate(bad)
    assert any("turn" in e for e in errs) and any("angle" in e for e in errs)
    assert any("seq" in e for e in errs) and any("opposite" in e for e in errs)
    errs, _ = P.validate(dict(good, app="other"))
    assert errs and "app" in errs[0]
    _, warns = P.validate(dict(good, playlist=[dict(STEP4, nextAt=1)]))
    assert warns and "nextAt" in warns[0]


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
        await S.show.fire_moves(S.drivers, moves, 12, 200, 200)
        await S.show.wait_all_stopped(S.drivers, timeout=20)
        st = [await S.drivers[k].read_status() for k in keys]
        assert abs(st[0]["position_deg"] - 120) < 1 and abs(st[1]["position_deg"] + 240) < 1, st
        assert st[2]["position_deg"] == 0.0 and not any(s["running"] for s in st), st
    finally:
        await S._stop_pollers()


def test_fire_moves():
    asyncio.run(_fire_moves_sim())


CUSTOMER = {"app": P.APP_ID, "version": 3, "title": "customer test", "playlist": [
    {"seq": 2, "turn": 2, "nextAt": 2, "pauseAfter": 0.5, "odd": "stay", "even": "stay",
     "dirLong": "cw", "dirShort": "ccw", "angle": 120, "runs": 1, "sweep": 1},
    {"seq": 1, "turn": 2, "nextAt": 3, "pauseAfter": 0.5, "odd": "B", "even": "B",
     "dirLong": "cw", "dirShort": "ccw", "angle": 120, "runs": 1, "sweep": 1},
    {"seq": 2, "turn": 2, "nextAt": 2, "pauseAfter": 0.5, "odd": "C", "even": "C",
     "dirLong": "cw", "dirShort": "ccw", "angle": 120, "runs": 1, "sweep": 1},
    {"seq": 3, "turn": 4, "nextAt": 5, "pauseAfter": 0, "odd": "A", "even": "A",
     "dirLong": "ccw", "dirShort": "cw", "angle": 240, "runs": 1, "sweep": 1},
]}   # every step passes validate() and raises no warning


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
        await S.drivers[k0].start_move("relative", 120, 12, 200, 200)
        await S.show.wait_all_stopped(S.drivers, timeout=10)
        assert S.runner.start("customer", CUSTOMER, loop=False)
        assert not S.runner.start("customer", CUSTOMER)          # already running
        deadline = time.monotonic() + 60
        while S.runner.state()["running"]:
            assert time.monotonic() < deadline, ("runner did not finish", S.runner.state())
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
        r = await S.show_next(S.TransitionRequest())
        assert r == {"error": "Playlist running"}, r
        assert (await S.home_motor(S.HomeRequest())) == {"error": "Playlist running"}
        k0 = next(iter(S.drivers))
        r = await S.move_motor(S.MoveRequest(motor_key=k0, angle_deg=0.1, speed_rpm=5))
        assert r == {"error": "Playlist running"}, r
        await S.runner.stop()
        assert S.show.busy                                   # settle: drives may still be turning
        deadline = time.monotonic() + 5
        while S.show.busy:
            assert time.monotonic() < deadline, "show.busy never cleared after stop"
            await asyncio.sleep(0.05)
        r = await S.playlist_stop()
        assert r["ok"] and not (await S.playlist_state())["running"]
        r = await S.playlist_delete("cust")
        assert r["ok"] and (await S.playlist_list())["playlists"] == []
        assert "playlist" in (await S._build_status())
        (S.PLAYLIST_DIR / "broken.json").write_text(json.dumps(
            {"app": P.APP_ID, "version": 3, "playlist": [{"seq": 9}]}))
        r = await S.playlist_run("broken", S.PlaylistRunRequest())
        assert r.get("error") and not S.runner.state()["running"], r
        assert S._playlist_path("state") is None and S._playlist_path("stop") is None
        assert (await S.playlist_put("state", CUSTOMER))["error"]
    finally:
        await S.runner.stop()
        await S._stop_pollers()
        shutil.rmtree(S.PLAYLIST_DIR, ignore_errors=True)


def test_routes():
    asyncio.run(_routes_sim())


if __name__ == "__main__":
    for fn in [test_layout, test_rpm, test_plan_turn_to_backward, test_plan_every_other_and_stay,
               test_plan_next_240_wave_in, test_validate, test_fire_moves, test_runner, test_routes]:
        fn()
    print("test_playlist OK")
