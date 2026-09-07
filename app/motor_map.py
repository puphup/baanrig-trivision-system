"""Motor map file -> config v2 gateways/motors + per-key display extras.

The map (see docs/superpowers/specs/2026-09-07-trivision-231-design.md §2.1)
is the source of truth for the wall; the app never writes it."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Iterable

from .config import MAX_MOTORS_PER_GATEWAY, MAX_TOTAL_MOTORS, motor_key


class MapError(ValueError):
    pass


def _read(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        raise MapError(f"motor map not found: {p}")
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise MapError(f"motor map is not valid JSON: {e}") from e


def cabinet_summary(path: str | Path, use_spare: Iterable[int] = ()) -> list[dict]:
    spare = {int(n) for n in use_spare}
    out = []
    for c in sorted(_read(path)["cabinets"], key=lambda c: int(c["cabinet"])):
        n = int(c["cabinet"])
        active = c["spare"] if n in spare and c.get("spare") else c["host"]
        out.append({"cabinet": n, "host": c["host"], "spare": c.get("spare", ""),
                    "port": int(c.get("port", 502)), "active_host": active})
    return out


def load_map(path: str | Path, use_spare: Iterable[int] = ()):
    raw = _read(path)
    cabs = cabinet_summary(path, use_spare)
    gateways = [{"id": f"gw{c['cabinet']}", "host": c["active_host"], "port": c["port"]} for c in cabs]
    known = {g["id"] for g in gateways}

    # Limits are fatal here, not silently trimmed downstream: _normalize would
    # drop the overflow motors and the wall would come up quietly incomplete.
    if len(raw["motors"]) > MAX_TOTAL_MOTORS:
        raise MapError(f"map has {len(raw['motors'])} motors, more than the {MAX_TOTAL_MOTORS} supported")
    per_cab = Counter(int(m["cabinet"]) for m in raw["motors"])
    over = sorted(c for c, n in per_cab.items() if n > MAX_MOTORS_PER_GATEWAY)
    if over:
        raise MapError(
            f"cabinet(s) {over} have more than {MAX_MOTORS_PER_GATEWAY} motors "
            f"(max per gateway); largest is {max(per_cab.values())}")

    motors, extras, seen = [], {}, set()
    for m in sorted(raw["motors"], key=lambda m: int(m["motor"])):
        num = int(m["motor"])
        if num in seen:
            raise MapError(f"duplicate motor number {num}")
        seen.add(num)
        gw = f"gw{int(m['cabinet'])}"
        if gw not in known:
            raise MapError(f"motor {num} references unknown cabinet {m['cabinet']}")
        sid = int(m["slave_id"])
        if not (1 <= sid <= MAX_MOTORS_PER_GATEWAY):
            raise MapError(f"motor {num}: slave id {sid} outside 1..{MAX_MOTORS_PER_GATEWAY}")
        key = motor_key(gw, sid)
        if key in extras:
            raise MapError(f"motor {num}: slave id {sid} already used in cabinet {m['cabinet']}")
        motors.append({"gateway": gw, "slave_id": sid, "driver_type": "icl_rs"})
        extras[key] = {
            "motor": num, "label": f"M{num:03d}", "cabinet": int(m["cabinet"]),
            "x": float(m["x"]), "y": float(m["y"]), "apex_deg": float(m["apex_deg"]),
            "estimated": bool(m.get("estimated", False)),
        }
    used = {m["gateway"] for m in motors}
    empty = sorted(known - used)
    if empty:
        raise MapError(f"cabinets without motors: {empty}")
    return gateways, motors, extras
