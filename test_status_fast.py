"""read_status_fast must parse the same as read_status with 2 reads. Run: ./venv/bin/python test_status_fast.py"""
import asyncio
from app.drivers.icl_rs import ICLRSDriver
from app.drivers.sim import SimDriver
from app.motor_sim import MotorSim


class FakeModbus:
    def __init__(self):
        self.reads = []
        self.regs = {0x1003: 0x0034, 0x1014: 0xFFFF, 0x1015: 0xFFF6, 0x2203: 0x0A0, 0x1046: 0, 0x1047: 7}

    async def read_holding_registers(self, sid, addr, n):
        self.reads.append((addr, n))
        return [self.regs.get(addr + i, 0) for i in range(n)]

    async def write_registers(self, sid, addr, vals):
        pass


async def main():
    mb = FakeModbus(); d = ICLRSDriver(mb, 1)
    slow = await d.read_status()
    mb.reads.clear()
    fast = await d.read_status_fast()
    assert mb.reads == [(0x1003, 19), (0x2203, 1)], mb.reads
    slow["velocity_rpm"] = 0
    assert fast == slow, (fast, slow)
    assert fast["position_pulses"] == -10 and fast["running"] and fast["alarm"] == 0x0A0

    class Dead(FakeModbus):
        async def read_holding_registers(self, sid, addr, n): raise ConnectionError("x")
    off = await ICLRSDriver(Dead(), 1).read_status_fast()
    assert off["offline"] is True

    sim = MotorSim(slave_id=1); sim.position = 1234.0
    sd = SimDriver(sim)
    await sd.seek_home()
    assert sim.position == 0.0
    assert (await sd.read_status_fast())["position_pulses"] == 0
    print("ok")

asyncio.run(main())
