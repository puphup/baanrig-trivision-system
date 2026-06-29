"""Config loader — reads/writes config.json.

Schema (v2, multi-gateway):

    {
      "mode": "tcp" | "simulation",
      "gateways": [
        {"id": "gw1", "host": "192.168.10.201", "port": 502},
        ...
      ],
      "motors": [
        {"gateway": "gw1", "slave_id": 1, "driver_type": "tl_r"},
        ...
      ],
      "motor_defaults": {"command_ppr": 4000, "encoder_ppr": 4000},
      "server": {"host": "0.0.0.0", "port": 8000},

      // legacy block kept for one-shot serial RTU access. Optional in v2.
      "connection": { "serial_port": ..., "baudrate": ..., ... }
    }

A motor's globally-unique key is ``"{gateway}.{slave_id}"`` (e.g. ``"gw1.5"``).
Its human-friendly label is computed: ``"GW{gw_index}-M{slave_id:02d}"`` (e.g.
``"GW1-M05"``).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

CONFIG_PATH_ENV = "PYSIM_CONFIG_DIR"


def _config_path() -> Path:
    env = os.environ.get(CONFIG_PATH_ENV)
    if env:
        return Path(env) / "config.json"
    return Path(__file__).parent.parent / "config.json"


CONFIG_PATH = _config_path()

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------
MAX_GATEWAYS = 8
MAX_MOTORS_PER_GATEWAY = 20      # bounded by typical RS485 fan-out
MAX_TOTAL_MOTORS = 60            # MAX_GATEWAYS * MAX_MOTORS_PER_GATEWAY, capped

# Legacy alias still imported by older modules; resolves to the new total cap.
MAX_MOTORS = MAX_TOTAL_MOTORS

# ---------------------------------------------------------------------------
# Driver types
# ---------------------------------------------------------------------------
DEFAULT_DRIVER_TYPE = "icl_rs"
ALLOWED_DRIVER_TYPES = ("icl_rs", "tl_r")


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULTS = {
    "mode": "simulation",
    "gateways": [
        {"id": "gw1", "host": "192.168.10.201", "port": 502},
    ],
    "motors": [
        {"gateway": "gw1", "slave_id": 1, "driver_type": "icl_rs"},
        {"gateway": "gw1", "slave_id": 2, "driver_type": "icl_rs"},
    ],
    "motor_defaults": {"command_ppr": 4000, "encoder_ppr": 4000},
    "server": {"host": "0.0.0.0", "port": 8000},
    "connection": {
        "serial_port": "",
        "baudrate": 115200,
        "data_bits": 8,
        "parity": "none",
        "stop_bits": 1,
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_GW_ID_RE = re.compile(r"^gw\d+$")


def motor_key(gateway_id: str, slave_id: int) -> str:
    return f"{gateway_id}.{int(slave_id)}"


def motor_label(gateway_id: str, slave_id: int) -> str:
    """'gw1' + 5 → 'GW1-M05'. Falls back to uppercase id if non-standard."""
    m = re.match(r"^gw(\d+)$", gateway_id)
    if m:
        return f"GW{int(m.group(1))}-M{int(slave_id):02d}"
    return f"{gateway_id.upper()}-M{int(slave_id):02d}"


def _validate_gateway(gw: dict) -> dict | None:
    if not isinstance(gw, dict):
        return None
    gid = str(gw.get("id", "")).strip()
    if not gid:
        return None
    host = str(gw.get("host", "")).strip()
    try:
        port = int(gw.get("port", 502))
    except (TypeError, ValueError):
        port = 502
    return {"id": gid, "host": host, "port": port}


def _validate_motor(m: dict, known_gw_ids: set[str]) -> dict | None:
    if not isinstance(m, dict):
        return None
    gw = str(m.get("gateway", "")).strip()
    try:
        sid = int(m.get("slave_id"))
    except (TypeError, ValueError):
        return None
    if gw not in known_gw_ids:
        return None
    if not (1 <= sid <= 31):
        return None
    drv = str(m.get("driver_type", DEFAULT_DRIVER_TYPE)).lower()
    if drv not in ALLOWED_DRIVER_TYPES:
        drv = DEFAULT_DRIVER_TYPE
    return {"gateway": gw, "slave_id": sid, "driver_type": drv}


def _normalize(cfg: dict) -> dict:
    """Normalize raw JSON into the v2 shape, migrating v1 if present."""
    # ---- mode ---------------------------------------------------------------
    mode = str(cfg.get("mode", DEFAULTS["mode"])).lower()
    # v1 had `connection.mode` ∈ {simulation, hardware, tcp}. Map.
    legacy_conn_mode = str(cfg.get("connection", {}).get("mode", "")).lower()
    if "mode" not in cfg and legacy_conn_mode:
        if legacy_conn_mode in ("tcp", "hardware"):
            mode = "tcp" if legacy_conn_mode == "tcp" else "simulation"
        else:
            mode = "simulation"
    if mode not in ("tcp", "simulation"):
        mode = "tcp"
    cfg["mode"] = mode

    # ---- gateways -----------------------------------------------------------
    raw_gws = cfg.get("gateways")
    gateways: list[dict] = []
    if isinstance(raw_gws, list) and raw_gws:
        for gw in raw_gws[:MAX_GATEWAYS]:
            v = _validate_gateway(gw)
            if v:
                gateways.append(v)
    else:
        # Migrate from v1: single TCP gateway derived from connection.tcp_host
        conn = cfg.get("connection", {}) or {}
        host = conn.get("tcp_host") or conn.get("host") or "192.168.10.201"
        try:
            port = int(conn.get("tcp_port", 502))
        except (TypeError, ValueError):
            port = 502
        gateways.append({"id": "gw1", "host": str(host), "port": port})

    # Dedupe gateway ids (first wins) and reassign sequential ones if needed.
    seen_ids = set()
    cleaned_gws = []
    for gw in gateways:
        if gw["id"] in seen_ids:
            continue
        seen_ids.add(gw["id"])
        cleaned_gws.append(gw)
    cfg["gateways"] = cleaned_gws
    known_gw_ids = {gw["id"] for gw in cleaned_gws}

    # ---- motors -------------------------------------------------------------
    raw_motors = cfg.get("motors")
    motors: list[dict] = []

    if isinstance(raw_motors, list) and raw_motors and isinstance(raw_motors[0], dict) and "gateway" in raw_motors[0]:
        # Already v2 shape.
        for m in raw_motors:
            v = _validate_motor(m, known_gw_ids)
            if v:
                motors.append(v)
    else:
        # Migrate v1: motors.slave_ids + motors.driver_types are flat.
        legacy_motors = cfg.get("motors", {}) if isinstance(cfg.get("motors"), dict) else {}
        slave_ids = legacy_motors.get("slave_ids") or []
        drv_map = legacy_motors.get("driver_types") or {}
        first_gw = cleaned_gws[0]["id"] if cleaned_gws else "gw1"
        for sid in slave_ids:
            try:
                sid_int = int(sid)
            except (TypeError, ValueError):
                continue
            if not (1 <= sid_int <= 31):
                continue
            drv = drv_map.get(str(sid_int), DEFAULT_DRIVER_TYPE)
            if drv not in ALLOWED_DRIVER_TYPES:
                drv = DEFAULT_DRIVER_TYPE
            motors.append({"gateway": first_gw, "slave_id": sid_int, "driver_type": drv})

    # Cap per-gateway and overall, dedupe within a gateway.
    per_gw_count: dict[str, int] = {}
    seen_keys = set()
    capped_motors = []
    for m in motors:
        key = motor_key(m["gateway"], m["slave_id"])
        if key in seen_keys:
            continue
        if per_gw_count.get(m["gateway"], 0) >= MAX_MOTORS_PER_GATEWAY:
            continue
        if len(capped_motors) >= MAX_TOTAL_MOTORS:
            break
        seen_keys.add(key)
        per_gw_count[m["gateway"]] = per_gw_count.get(m["gateway"], 0) + 1
        capped_motors.append(m)
    cfg["motors"] = capped_motors

    # ---- defaults / server / legacy connection ------------------------------
    md = cfg.get("motor_defaults") or {}
    # v1 placed these inside motors{}; carry across.
    legacy_motors = cfg.get("motors") if isinstance(cfg.get("motors"), dict) else None
    if isinstance(legacy_motors, dict):
        md.setdefault("command_ppr", legacy_motors.get("command_ppr"))
        md.setdefault("encoder_ppr", legacy_motors.get("encoder_ppr"))
    md["command_ppr"] = int(md.get("command_ppr") or DEFAULTS["motor_defaults"]["command_ppr"])
    md["encoder_ppr"] = int(md.get("encoder_ppr") or DEFAULTS["motor_defaults"]["encoder_ppr"])
    cfg["motor_defaults"] = md

    server = cfg.get("server") or {}
    server.setdefault("host", DEFAULTS["server"]["host"])
    try:
        server["port"] = int(server.get("port", DEFAULTS["server"]["port"]))
    except (TypeError, ValueError):
        server["port"] = DEFAULTS["server"]["port"]
    cfg["server"] = server

    cfg.setdefault("connection", DEFAULTS["connection"].copy())

    return cfg


def _bundled_default_path() -> Path | None:
    """config.json shipped inside the frozen bundle (sys._MEIPASS), used as the
    built-in default when there's no config.json next to the exe yet."""
    env = os.environ.get("PYSIM_RESOURCE_ROOT")
    return Path(env) / "config.json" if env else None


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            raw = json.load(f)
    else:
        # No local config next to the exe → seed from the bundled default
        # (the 50-motor / 3-gateway setup), falling back to DEFAULTS.
        bundled = _bundled_default_path()
        if bundled and bundled.exists() and bundled != CONFIG_PATH:
            with open(bundled) as f:
                raw = json.load(f)
        else:
            raw = {k: (v.copy() if isinstance(v, (dict, list)) else v) for k, v in DEFAULTS.items()}
    return _normalize(raw)


def save_config(cfg: dict):
    normalized = _normalize(cfg)
    with open(CONFIG_PATH, "w") as f:
        json.dump(normalized, f, indent=2)


def driver_type_for(cfg: dict, gateway_id: str, slave_id: int) -> str:
    """Look up the driver type for a (gateway, slave_id) pair (or default)."""
    for m in cfg.get("motors", []):
        if m["gateway"] == gateway_id and int(m["slave_id"]) == int(slave_id):
            return m["driver_type"]
    return DEFAULT_DRIVER_TYPE
