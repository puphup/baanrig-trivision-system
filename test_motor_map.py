"""Self-check for the motor-map loader. Run: ./venv/bin/python test_motor_map.py"""
import json, subprocess, sys
from pathlib import Path

from app.motor_map import load_map, cabinet_summary, MapError

root = Path(__file__).parent

# generator is idempotent and produces 231 motors / 11 cabinets
subprocess.run([sys.executable, "gen_motor_map.py"], check=True, cwd=root)
m = json.loads((root / "motor_map.json").read_text())
assert len(m["motors"]) == 231 and len(m["cabinets"]) == 11

gws, motors, extras = load_map(root / "motor_map.json")
assert [g["host"] for g in gws][0] == "192.168.20.101"
assert [g["host"] for g in gws][10] == "192.168.20.121"
assert len(motors) == 231 and motors[0]["driver_type"] == "icl_rs"
counts = {}
for mm in motors:
    counts[mm["gateway"]] = counts.get(mm["gateway"], 0) + 1
assert [counts[f"gw{n}"] for n in range(1, 12)] == [21, 21, 21, 21, 21, 21, 11, 22, 24, 24, 24], counts
assert extras["gw4.10"]["motor"] == 73 and extras["gw4.10"]["label"] == "M073"
assert [k for k, v in extras.items() if v["estimated"]] == [f"gw7.{i}" for i in range(7, 12)]
assert [v["motor"] for v in extras.values()] == list(range(1, 232))   # wall order

# spare IP override
gws2, _, _ = load_map(root / "motor_map.json", use_spare=[2])
assert gws2[1]["host"] == "192.168.20.104" and gws2[0]["host"] == "192.168.20.101"
assert cabinet_summary(root / "motor_map.json", [2])[1]["active_host"] == "192.168.20.104"

# bench map: serial host, baud in port
bg, bm, be = load_map(root / "bench_map.json")
assert bg == [{"id": "gw1", "host": "/dev/cu.usbserial-2140", "port": 115200}]
assert bm == [{"gateway": "gw1", "slave_id": 1, "driver_type": "icl_rs"}]
assert be["gw1.1"]["label"] == "M001"

# errors
try:
    load_map(root / "nope.json"); assert False
except MapError:
    pass
print("ok")
