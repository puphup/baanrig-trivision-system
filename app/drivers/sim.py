"""Simulator driver — drives a :class:`MotorSim` directly, no Modbus involved."""

from __future__ import annotations

from ..motor_sim import MotorSim
from ..registers import (
    MODE_ABSOLUTE, MODE_RELATIVE,
    STATUS_RUNNING, STATUS_CMD_OK, STATUS_PATH_OK,
    degrees_to_pulses, pulses_to_degrees,
)
from .base import MotorDriver, MotorStatus


class SimDriver(MotorDriver):
    """Wraps an in-process :class:`MotorSim`. Useful for hardware-free testing."""

    def __init__(self, motor: MotorSim):
        self.motor = motor
        self.slave_id = motor.slave_id
        # Sim runs one config at a time; mirror the global PPR so the base
        # pulses_to_deg helper (used by the server) matches the simulator.
        from .. import registers
        self.command_ppr = registers.COMMAND_PPR
        self.encoder_ppr = registers.ENCODER_PPR

    async def enable(self) -> None:
        self.motor.enable()

    async def disable(self) -> None:
        self.motor.disable()

    async def start_move(self, mode, angle_deg, speed_rpm, accel, decel):
        mode_val = MODE_ABSOLUTE if mode == "absolute" else MODE_RELATIVE
        # Relative moves carry the sub-pulse remainder (matches the real drivers)
        # so repeated 120° flips don't drift; absolute moves are exact as-is.
        pulses = (degrees_to_pulses(angle_deg) if mode == "absolute"
                  else self.deg_to_pulses_rel(angle_deg))
        self.motor.start_move(mode_val, pulses, int(speed_rpm), int(accel), int(decel))

    async def stop_motion(self) -> None:
        self.motor.stop_motion()

    async def estop(self) -> None:
        self.motor.emergency_stop()

    async def alarm_reset(self) -> None:
        self.motor.reset_alarm()
        self.motor.clear_estop()

    async def save_params(self) -> None:
        # No-op in sim; real drives persist to NVRAM.
        return

    async def set_home(self) -> None:
        # Make the current sim position the origin.
        self.motor.position = 0.0

    async def read_status(self) -> MotorStatus:
        status = self.motor.status_word
        return {
            "position_deg": round(pulses_to_degrees(int(self.motor.position)), 2),
            "position_pulses": int(self.motor.position),
            "velocity_rpm": int(self.motor.velocity),
            "running": self.motor.running,
            "enabled": self.motor.enabled,
            "estopped": self.motor.estopped,
            "alarm": self.motor.alarm_code,
            "status_bits": status,
            "offline": False,
        }

    async def test_connection(self) -> dict:
        return {"ok": True, "slave_id": self.slave_id, "status": self.motor.status_word}
