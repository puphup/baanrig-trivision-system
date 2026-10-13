"""Auto-cycle direction 0 = random face: every flip is ±1 (never stays put), both signs occur."""
import asyncio
from app.show import ShowController, TransitionOptions


async def main():
    show, steps = ShowController(), []
    async def fake_step(drivers, delta, opts):
        steps.append(delta)
        if len(steps) >= 40:
            show.auto.running = False
    async def no_wait(*a, **k): pass
    show._step, show.wait_all_stopped = fake_step, no_wait
    await show.start_auto({}, 0.5, 0, TransitionOptions())
    show.auto.hold_s = 0
    await asyncio.wait_for(show.auto.task, 5)
    assert show.auto.direction == 0
    assert set(steps) == {1, -1}, steps
    print("ok: random auto-cycle,", len(steps), "flips")

asyncio.run(main())
