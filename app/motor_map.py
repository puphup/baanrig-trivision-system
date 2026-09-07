"""Motor map file -> config v2 gateways/motors + per-key display extras.

The map (see docs/superpowers/specs/2026-09-07-trivision-231-design.md §2.1)
is the source of truth for the wall; the app never writes it."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .config import motor_key


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

    motors, extras, seen = [], {}, set()
    for m in sorted(raw["motors"], key=lambda m: int(m["motor"])):
        num = int(m["motor"])
        if num in seen:
            raise MapError(f"duplicate motor number {num}")
        seen.add(num)
        gw = f"gw{int(m['cabinet'])}"
        if gw not in known:
            raise MapError(f"motor {num} references unknown cabinet {m['cabinet']}")
        key = motor_key(gw, int(m["slave_id"]))
        if key in extras:
            raise MapError(f"motor {num}: slave id {m['slave_id']} already used in cabinet {m['cabinet']}")
        motors.append({"gateway": gw, "slave_id": int(m["slave_id"]), "driver_type": "icl_rs"})
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
