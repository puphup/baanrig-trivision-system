"""One-shot: Trivision_Motor_Map.md (first ```json block) -> motor_map.json.
Run: ./venv/bin/python gen_motor_map.py"""
import json, re
from pathlib import Path

root = Path(__file__).parent
md = (root / "Trivision_Motor_Map.md").read_text()
block = re.search(r"```json\s*(\[.*?\])\s*```", md, re.S).group(1)
rows = json.loads(block)

cabinets = {}
for r in rows:
    n = int(r["cabinet"])
    primary = f"192.168.20.{99 + 2 * n}"
    assert r["gatewayIp"] == primary, (r["motor"], r["gatewayIp"], primary)
    cabinets[n] = {"cabinet": n, "host": primary, "spare": f"192.168.20.{100 + 2 * n}", "port": 502}

motors = [{
    "motor": int(r["motor"]), "cabinet": int(r["cabinet"]), "slave_id": int(r["modbusId"]),
    "x": float(r["x"]), "y": float(r["y"]), "apex_deg": float(r["apexDeg"]),
    "estimated": bool(r.get("estimated", False)),
} for r in sorted(rows, key=lambda r: int(r["motor"]))]

out = {"cabinets": [cabinets[n] for n in sorted(cabinets)], "motors": motors}
(root / "motor_map.json").write_text(json.dumps(out, indent=1))
print(f"wrote motor_map.json: {len(out['cabinets'])} cabinets, {len(motors)} motors")
