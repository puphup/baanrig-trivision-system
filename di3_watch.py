"""Live DI3 watch, no motion:  ./venv/bin/python di3_watch.py CAB ID [SECONDS]
Prints every change of the drive's DI3 input (Pr8.46) so a sensor can be triggered by hand and checked.
ponytail: read-only, standalone like check_cab.py."""
import json, sys, time
from pymodbus.client import ModbusTcpClient
DI_STATE_REG = 0x602E
cab, sid = int(sys.argv[1]), int(sys.argv[2]); secs = int(sys.argv[3]) if len(sys.argv) > 3 else 120
m = json.load(open("motor_map.json"))
c = next(x for x in m["cabinets"] if x["cabinet"] == cab)
cl = ModbusTcpClient(host=c["host"], port=c["port"], timeout=1); cl.connect()
last = None; t0 = time.time(); changes = 0; beat = t0; reads = 0
print(f"cabinet {cab} motor {sid}: watching DI3 for {secs} s via {c['host']} (Ctrl-C to stop)", flush=True)
while time.time() - t0 < secs:
    if not cl.connected:
        cl.connect()
    try:
        r = cl.read_holding_registers(DI_STATE_REG, count=1, device_id=sid)
        if r.isError():
            raise IOError(str(r))
    except Exception:
        cl.close(); time.sleep(0.3); fails = locals().get("fails", 0) + 1
        if time.time() - beat > 15:
            print(f"  {time.time() - t0:6.1f} s  NO REPLY from the drive ({fails} failed reads)", flush=True); beat = time.time()
        continue
    di = "ON" if r.registers[0] & 4 else "off"; reads += 1
    if time.time() - beat > 15:              # heartbeat so a stuck gateway is visible
        print(f"  {time.time() - t0:6.1f} s  still DI3={di}  ({reads} reads)", flush=True); beat = time.time()
    if di != last:
        print(f"  {time.time() - t0:6.1f} s  DI3={di}", flush=True); last = di; changes += 1
    time.sleep(0.05)
print(f"done: {changes - 1} change(s) seen" if changes else "done: no reply from the drive")
