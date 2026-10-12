"""DI3 home-switch homing, one cabinet at a time:  ./venv/bin/python seek_home_all.py 1 [2 ...]
Per drive: servo-on (Pr0.07=1), trigger the drive's own homing routine (0x6002 = 0x20), then wait
until every drive in the cabinet has stopped. Prints position (should read 0 at the switch), alarm and
the live DI3 input. Drives are LEFT ENABLED so the shafts hold while prisms are aligned by hand.
ponytail: standalone like check_cab.py; the app is not running on site yet. Run only on cabinets whose
DI3 sensors are wired, else the drive spins forever."""
import json, sys, time
from pymodbus.client import ModbusTcpClient
from app.registers import (SW_ENABLE_REG, ESTOP_REG, ESTOP_VAL, HOMING_TRIGGER_VAL, MOTION_STATUS, STATUS_RUNNING,
                           FEEDBACK_POS_H, CURRENT_ALARM)
DI_STATE_REG = 0x602E
TIMEOUT_S = 120         # fast search up to one turn (20 s at 3 rpm) plus the 1 rpm approach (up to 60 s)

m = json.load(open("motor_map.json"))
cabs = [int(a) for a in sys.argv[1:]]
if not cabs:
    sys.exit("name the cabinet(s) to home, e.g.  seek_home_all.py 1")
for cab in cabs:
    c = next(x for x in m["cabinets"] if x["cabinet"] == cab)
    ids = [x["slave_id"] for x in m["motors"] if x["cabinet"] == cab]
    cl = ModbusTcpClient(host=c["host"], port=c["port"], timeout=1)
    cl.connect()
    def rd(sid, reg, n=1):
        if not cl.connected:
            cl.connect()
        r = cl.read_holding_registers(reg, count=n, device_id=sid)
        if r.isError():
            raise IOError(str(r))
        return r.registers
    print(f"cabinet {cab}: homing {len(ids)} drives via {c['host']}")
    failed = []
    for sid in ids:
        try:
            cl.write_registers(SW_ENABLE_REG, [1], device_id=sid)
            time.sleep(0.1)
            cl.write_registers(ESTOP_REG, [HOMING_TRIGGER_VAL], device_id=sid)
        except Exception as e:
            failed.append(sid); print(f"  id {sid:2d}  trigger FAILED ({str(e)[:50]})"); cl.close()
        time.sleep(0.2)                       # staggered like the app, one trigger per drive
    moving = {s for s in ids if s not in failed}
    t0 = time.time()
    while moving and time.time() - t0 < TIMEOUT_S:
        time.sleep(1.0)
        for sid in list(moving):
            try:
                if not rd(sid, MOTION_STATUS)[0] & STATUS_RUNNING:
                    moving.discard(sid)
            except Exception:
                cl.close()
    for sid in moving:                        # ponytail: switch never seen -> e-stop + servo-off, don't spin forever
        try:
            if not cl.connected:
                cl.connect()
            cl.write_registers(ESTOP_REG, [ESTOP_VAL], device_id=sid); time.sleep(0.3)
            cl.write_registers(SW_ENABLE_REG, [0], device_id=sid)
        except Exception:
            cl.close()
    for sid in ids:
        if sid in failed:
            continue
        try:
            st = rd(sid, MOTION_STATUS)[0]
            p = rd(sid, FEEDBACK_POS_H, 2); pos = (p[0] << 16) | p[1]; pos = pos - (1 << 32) if pos >> 31 else pos
            al = rd(sid, CURRENT_ALARM)[0]; di = rd(sid, DI_STATE_REG)[0]
            flag = "NO SWITCH (e-stopped, servo-off)" if sid in moving else ("ALARM" if al else "ok")
            print(f"  id {sid:2d}  status 0x{st:04X}  pos {pos:>8d}  alarm 0x{al:04X}  DI3={'ON' if di & 4 else 'off'}  {flag}")
        except Exception as e:
            print(f"  id {sid:2d}  NO REPLY after homing ({str(e)[:50]})"); cl.close()
    cl.close()
    print(f"cabinet {cab}: {len(ids) - len(failed) - len(moving)}/{len(ids)} homed in {time.time() - t0:.0f} s")
