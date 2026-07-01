"""Abstract base class for motor drivers."""

from abc import ABC, abstractmethod
from typing import TypedDict


class MotorStatus(TypedDict, total=False):
    """Normalized motor status returned by :meth:`MotorDriver.read_status`.

    All drivers return the same shape so the server / UI layer doesn't need to
    know which physical drive is on the other end of the bus.
    """

    position_deg: float       # current shaft angle, degrees; software zero applied by caller
    position_pulses: int      # raw encoder pulses (signed)
    velocity_rpm: int         # signed RPM feedback
    running: bool             # motor currently in motion
    enabled: bool             # software-enabled (motor energized)
    estopped: bool            # latched e-stop flag (sim-only on hardware)
    alarm: int                # current alarm code (0 = none)
    status_bits: int          # raw status register, motor-specific layout
    offline: bool             # True if the read transaction failed entirely


class MotorDriver(ABC):
    """High-level interface every motor type implements."""

    slave_id: int
    # Per-drive pulses-per-rev (set in each concrete __init__). command_ppr is
    # what the drive expects for move targets; encoder_ppr is what it reports
    # back for position. They differ on some drives (e.g. iCL-RS 10000/65536).
    command_ppr: int = 10000
    encoder_ppr: int = 10000
    # Rotation sense: +1 normal, -1 to reverse this drive family so a positive
    # commanded angle turns the shaft the same physical way as the others.
    # Applied to BOTH the command and the feedback, so the UI still reads a
    # positive angle for a positive command. (TL-R uses -1 to match iCL-RS.)
    direction: int = 1

    def deg_to_pulses(self, deg: float) -> int:
        return int(deg * self.direction * self.command_ppr / 360.0)

    def deg_to_pulses_rel(self, deg: float) -> int:
        """Relative-move pulses, carrying the sub-pulse rounding remainder so a
        repeated step never drifts on a drive whose ppr doesn't divide the step
        evenly (TL-R: 120° = 333.33 pulses → plain truncation loses 0.12°/flip).
        The carried remainder makes three 120° steps sum to exactly one rev."""
        resid = getattr(self, "_pulse_residual", 0.0)
        ideal = deg * self.direction * self.command_ppr / 360.0
        pulses = round(ideal + resid)
        self._pulse_residual = ideal + resid - pulses
        return int(pulses)

    def pulses_to_deg(self, pulses: int) -> float:
        return pulses * self.direction * 360.0 / self.encoder_ppr if self.encoder_ppr else 0.0

    @abstractmethod
    async def enable(self) -> None: ...

    @abstractmethod
    async def disable(self) -> None: ...

    @abstractmethod
    async def start_move(
        self,
        mode: str,           # "absolute" or "relative"
        angle_deg: float,
        speed_rpm: int,
        accel: int,
        decel: int,
    ) -> None: ...

    # --- Two-phase move (for synchronized group starts) -------------------
    # stage_move() writes the target/speed/accel/decel but does NOT start the
    # motion; trigger_move() then starts it. Staging every motor first and then
    # triggering them back-to-back collapses the start spread on a shared RS485
    # bus from ~6 writes/motor down to ~1. Default impl works for any driver by
    # remembering the args; concrete drivers override for a real split.
    async def stage_move(self, mode: str, angle_deg: float, speed_rpm: int,
                         accel: int, decel: int) -> None:
        self._staged = (mode, angle_deg, speed_rpm, accel, decel)

    async def trigger_move(self) -> None:
        staged = getattr(self, "_staged", None)
        if staged is not None:
            self._staged = None
            await self.start_move(*staged)

    @abstractmethod
    async def stop_motion(self) -> None:
        """Decelerate to stop without latching e-stop (used by jog release)."""

    @abstractmethod
    async def estop(self) -> None:
        """Emergency stop — may latch a fault depending on the drive."""

    @abstractmethod
    async def alarm_reset(self) -> None: ...

    @abstractmethod
    async def save_params(self) -> None:
        """Persist current parameters to non-volatile memory on the drive."""

    @abstractmethod
    async def read_status(self) -> MotorStatus: ...

    @abstractmethod
    async def test_connection(self) -> dict:
        """Lightweight ping: returns ``{"ok": bool, "slave_id": int, ...}``."""

    async def configure(self) -> None:
        """One-shot drive setup (filter time, etc.). Default = no-op so most
        drivers don't have to override. iCL-RS uses this to write its command
        filter register."""
        return None

    async def set_home(self) -> None:
        """Make the current physical position the drive's origin (zero) and
        persist it to EEPROM so it survives a power cycle. Default no-op;
        concrete drivers override."""
        return None

    async def jog_start(self, direction: int, speed_rpm: int, accel: int, decel: int) -> None:
        """Begin a continuous (hold-to-move) jog.

        Default implementation fakes it with a large relative positioning move,
        stopped by :meth:`stop_motion`. Drives with a native level-triggered jog
        mode should override (TL-R does — a missed stop on a positioning move
        leaves the motor running the full huge angle)."""
        angle = 36000.0 * (1 if direction >= 0 else -1)
        await self.start_move("relative", angle, speed_rpm, accel, decel)

    async def jog_stop(self) -> None:
        """Stop a jog. Default falls back to :meth:`stop_motion`."""
        await self.stop_motion()
