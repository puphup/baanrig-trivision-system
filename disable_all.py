"""Servo-off every drive in every cabinet:  ./venv/bin/python disable_all.py [cab ...]
Writes Pr0.07 (SW_ENABLE_REG) = 0 on each iCL-RS drive and reads it back. Nothing else is touched.
ponytail: standalone like check_cab.py so it works without the app running; stop any show first."""
import json, sys
from pymodbus.client import ModbusTcpClient
from app.registers import SW_ENABLE_REG

m = json.load(open("motor_map.json"))
want = [int(a) for a in sys.argv[1:]] or [c["cabinet"] for c in m["cabinets"]]
total = done = 0
for c in m["cabinets"]:
    if c["cabinet"] not in want:
        continue
    ids = [x["slave_id"] for x in m["motors"] if x["cabinet"] == c["cabinet"]]
    cl = ModbusTcpClient(host=c["host"], port=c["port"], timeout=1)
    bad = []
    for sid in ids:
        total += 1
        if not cl.connected:
            cl.connect()                      # a Modbus exception drops the gateway's TCP session
        try:
            cl.write_registers(SW_ENABLE_REG, [0], device_id=sid)
            r = cl.read_holding_registers(SW_ENABLE_REG, count=1, device_id=sid)
            if r.isError() or r.registers[0] != 0:
                raise IOError(str(r))
            done += 1
        except Exception as e:
            bad.append(f"id {sid} ({str(e)[:40]})")
            cl.close()
    cl.close()
    print(f"cabinet {c['cabinet']:2d}: {len(ids) - len(bad)}/{len(ids)} disabled" + (f"  FAILED: {', '.join(bad)}" if bad else ""))
print(f"{done}/{total} drives disabled")
