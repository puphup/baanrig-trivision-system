"""Read-only health check of one cabinet:  ./venv/bin/python check_cab.py 3 [--spare] [--home]
--home also reads the home-sensor setup: Pr4.04 DI3 function (0x27 = home switch N.O.,
0xA7 = N.C.), Pr8.10 homing mode (bit2 = home-switch homing), homing speeds, and the
live digital inputs Pr8.46 (DI3 = bit2) so a stuck or unwired sensor shows up.
Reads status / position / alarm from every drive in the cabinet. Writes nothing.
ponytail: run it while no controller is polling that cabinet, or replies interleave."""
import json, socket, sys
from pymodbus.client import ModbusTcpClient
from app.registers import (MOTION_STATUS, FEEDBACK_POS_H, CURRENT_ALARM, DI3_FUNC_REG,
                           HOMING_MODE_REG, HOMING_VEL_HIGH_REG)
DI_STATE_REG = 0x602E   # Pr8.46 live digital inputs

cab = int(sys.argv[1])
m = json.load(open("motor_map.json"))
c = next(x for x in m["cabinets"] if x["cabinet"] == cab)
host = c["spare"] if "--spare" in sys.argv else c["host"]
ids = [x["slave_id"] for x in m["motors"] if x["cabinet"] == cab]
print(f"cabinet {cab}: gateway {host}:{c['port']}, {len(ids)} drives")
try:
    socket.create_connection((host, c["port"]), timeout=3).close()
except OSError as e:
    sys.exit(f"GATEWAY UNREACHABLE: {e}")

cl = ModbusTcpClient(host=host, port=c["port"], timeout=1)
ok = 0
for sid in ids:
    if not cl.connected:
        cl.connect()          # a Modbus exception drops the gateway's TCP session
    try:
        blk = cl.read_holding_registers(MOTION_STATUS, count=FEEDBACK_POS_H - MOTION_STATUS + 2, device_id=sid)
        al = cl.read_holding_registers(CURRENT_ALARM, count=1, device_id=sid)
        if blk.isError() or al.isError():
            raise IOError(f"{blk} {al}")
        o = FEEDBACK_POS_H - MOTION_STATUS
        pos = (blk.registers[o] << 16) | blk.registers[o + 1]
        line = f"  id {sid:2d}  status 0x{blk.registers[0]:04X}  pos {pos - (1 << 32) if pos >> 31 else pos:>9d}  alarm 0x{al.registers[0]:04X}"
        if "--home" in sys.argv:
            rd = lambda a, n=1: cl.read_holding_registers(a, count=n, device_id=sid).registers
            di3, mode, vel, di = rd(DI3_FUNC_REG)[0], rd(HOMING_MODE_REG)[0], rd(HOMING_VEL_HIGH_REG, 2), rd(DI_STATE_REG)[0]
            cfg = "OK" if di3 & 0x7F == 0x27 and mode & 0x04 else "NOT SET UP"
            line += f"  | DI3func 0x{di3:02X} mode 0x{mode:02X} vel {vel[0]}/{vel[1]} rpm  inputs {di:08b} DI3={'ON' if di & 4 else 'off'}  {cfg}"
        print(line)
        ok += 1
    except Exception as e:
        print(f"  id {sid:2d}  NO REPLY  ({str(e)[:70]})")
        cl.close()
cl.close()
print(f"{ok}/{len(ids)} drives answered")
