"""Operator-page routes: seek-home/cancel stops a run and clears state.
Run: ./venv/bin/python test_operator_routes.py"""
import asyncio
import os
from app import server as S
from app.config import load_config


async def main():
    cfg = load_config()
    cfg["mode"] = "simulation"          # never touch real gateways from a test
    S.config = cfg
    await S._reload_runtime()
    try:
        page = (await S.operator()).path
        assert str(page).endswith("operator.html") and os.path.exists(page), page

        r = await S.seek_home_cancel()
        assert r == {"ok": True, "cancelled": False}, r

        r = await S.seek_home(S.SeekHomeRequest())
        assert r.get("ok") and r["total"] == len(S.drivers), r
        assert S.homing_state["active"] is True

        r = await S.seek_home_cancel()
        assert r == {"ok": True, "cancelled": True}, r
        assert S.homing_state["active"] is False and not S._home_tasks, S.homing_state

        # seek_home() is fire-and-forget on the drive, so cancel e-stops the motors.
        key = next(iter(S.drivers))
        st = await S.drivers[key].read_status()
        assert st["estopped"] is True, st

        # A cancelled run must not block the next one.
        r = await S.seek_home(S.SeekHomeRequest())
        assert r.get("ok"), r
        await S._stop_homing()
    finally:
        await S._stop_pollers()
        await S._teardown_runtime()
    print("ok")


asyncio.run(main())
