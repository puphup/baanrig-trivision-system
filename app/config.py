"""Config loader — reads/writes config.json."""

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config.json"

DEFAULTS = {
    "connection": {
        "mode": "simulation",
        "serial_port": "/dev/ttyUSB0",
        "baudrate": 38400,
        "data_bits": 8,
        "parity": "none",
        "stop_bits": 1,
    },
    "motors": {
        "motor1_slave_id": 1,
        "motor2_slave_id": 2,
        "pulses_per_rev": 10000,
    },
    "server": {
        "host": "0.0.0.0",
        "port": 8000,
    },
}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return DEFAULTS.copy()


def save_config(cfg: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
