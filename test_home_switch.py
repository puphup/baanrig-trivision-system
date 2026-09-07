"""Self-check: configure_home_switch / seek_home write the right iCL-RS registers."""
import asyncio
from app.drivers.icl_rs import ICLRSDriver


class FakeModbus:
    def __init__(self): self.writes = []
    async def write_registers(self, sid, addr, vals): self.writes.append((addr, vals[0]))
    async def read_holding_registers(self, sid, addr, n): return [0] * n


async def main():
    mb = FakeModbus(); d = ICLRSDriver(mb, 1)
    await d.configure_home_switch(normally_closed=True, direction_cw=True, high_rpm=10, low_rpm=2)
    w = dict(mb.writes)
    assert w[0x0149] == 0xA7, w          # DI3 = ORG, N.C.
    assert w[0x600A] == 0x05, w          # home-switch homing, dir bit set
    assert w[0x600F] == 10 and w[0x6010] == 2
    assert mb.writes[-1] == (0x1801, 0x2211)   # EEPROM save last
    mb.writes.clear()
    await d.seek_home()
    assert mb.writes == [(0x6002, 0x20)], mb.writes
    print("ok")

asyncio.run(main())
