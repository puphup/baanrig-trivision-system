"""Leadshine iCL-RS / DM-RS driver — PR0 register layout."""

from __future__ import annotations

from ..modbus_interface import ModbusInterface
from ..registers import (
    PR0_MODE, PR0_TRIGGER, PR0_TRIGGER_VAL,
    MOTION_STATUS, FEEDBACK_POS_H, FEEDBACK_VEL_H, CURRENT_ALARM,
    ESTOP_REG, ESTOP_VAL, SYSTEM_CMD_REG, ALARM_RESET_VAL, PERM_SAVE_VAL,
    SW_ENABLE_REG, SW_ENABLE_VAL,
    SET_ORIGIN_REG, SET_ORIGIN_VAL,
    DI1_FUNC_REG, DI1_FUNC_INVALID,
    MODE_ABSOLUTE, MODE_RELATIVE,
    STATUS_RUNNING, STATUS_CMD_OK, STATUS_PATH_OK,
    CMD_FILTER_REG, COMMAND_FILTER_MS, CMD_FILTER_MAX_REG,
    degrees_to_pulses, split_32, join_32, join_32_signed, pulses_to_degrees,
)
from .base import MotorDriver, MotorStatus


class ICLRSDriver(MotorDriver):
    """Leadshine iCL-RS family. Move semantics: write PR0 block, then trigger."""

    def __init__(self, modbus: ModbusInterface, slave_id: int,
                 command_ppr: int = 10000, encoder_ppr: int = 65536):
        self.modbus = modbus
        self.slave_id = slave_id
        self.command_ppr = command_ppr
        self.encoder_ppr = encoder_ppr

    def _filter_reg_value(self) -> int:
        """Command-filter register value, clamped to the drive's 0–512 range.
        Out-of-range writes are rejected by the drive, so we clamp here."""
        return max(0, min(CMD_FILTER_MAX_REG, round(COMMAND_FILTER_MS * 10)))

    async def configure(self) -> None:
        """Write the command filter (S-curve smoothing) on this drive — applied
        to RAM on every startup so it's active even if not yet saved. The
        commissioning step (configure_software_enable) is what persists it to
        EEPROM. The iCL-RS does only linear accel/decel; this filter rounds the
        ramp ends into an S-shape so the motor doesn't jolt at stop. 0.1 ms units.
        """
        try:
            await self.modbus.write_registers(
                self.slave_id, CMD_FILTER_REG, [self._filter_reg_value()],
            )
        except Exception:
            pass  # one bad drive shouldn't kill the startup

    async def configure_software_enable(self) -> None:
        """One-time commissioning: hand enable control from DI1 to software.

        Writes Pr4.02 (``DI1_FUNC_REG`` / ``0x0145``) = 0x0000 so the
        Normally-Closed hardware enable signal stops auto-asserting on
        power-up, then persists every drive parameter via
        :meth:`save_params` so the change survives a power cycle. After
        this runs, :meth:`enable` / :meth:`disable` (Pr0.07 /
        ``SW_ENABLE_REG``) actually take effect — before, the drive
        ignored those writes because DI1 was permanently forcing enable.

        iCL-RS series only. Other driver types in this codebase use
        different DI register layouts; do NOT call this on them. The
        method is idempotent: every write is deterministic, so it's
        safe to re-run.
        """
        sid = self.slave_id
        try:
            before_regs = await self.modbus.read_holding_registers(sid, DI1_FUNC_REG, 1)
            before = f"0x{before_regs[0]:04X}"
        except Exception as e:
            before = f"read err: {e}"
        print(f"[iCL-RS sid={sid}] Pr4.02 before = {before}")
        await self.modbus.write_registers(sid, DI1_FUNC_REG, [DI1_FUNC_INVALID])
        # Also write the command filter here so the smooth-stop tuning gets
        # persisted in the same EEPROM save (configure() only sets RAM).
        filt = self._filter_reg_value()
        await self.modbus.write_registers(sid, CMD_FILTER_REG, [filt])
        # save_params() writes PERM_SAVE_VAL to SYSTEM_CMD_REG — the existing
        # iCL-RS save helper. Persists every parameter to EEPROM.
        await self.save_params()
        try:
            after_regs = await self.modbus.read_holding_registers(sid, DI1_FUNC_REG, 1)
            filt_regs = await self.modbus.read_holding_registers(sid, CMD_FILTER_REG, 1)
            after = f"0x{after_regs[0]:04X}, filter={filt_regs[0]}"
        except Exception as e:
            after = f"read err: {e}"
        print(f"[iCL-RS sid={sid}] Pr4.02 after  = {after} (saved)")

    async def enable(self) -> None:
        """Energize / hold the shaft.

        iCL-RS only. Other driver families have their own enable
        mechanisms. Writes Pr0.07 (SW_ENABLE_REG / 0x000F) = 1; only
        effective after :meth:`configure_software_enable` has flipped
        Pr4.02 to 0x0000, otherwise DI1 is still forcing enable.
        """
        await self.modbus.write_registers(self.slave_id, SW_ENABLE_REG, [SW_ENABLE_VAL])

    async def disable(self) -> None:
        """Release the shaft (free to turn by hand).

        iCL-RS only. Writes Pr0.07 = 0.

        DANGER: do NOT call while the motor is holding a load that
        could drop or back-drive — there's no holding torque after
        this. Re-energize with :meth:`enable` first if there's any
        gravity or spring force on the output.
        """
        await self.modbus.write_registers(self.slave_id, SW_ENABLE_REG, [0])

    async def start_move(self, mode, angle_deg, speed_rpm, accel, decel):
        await self.stage_move(mode, angle_deg, speed_rpm, accel, decel)
        await self.trigger_move()

    async def stage_move(self, mode, angle_deg, speed_rpm, accel, decel):
        """Write the PR0 motion block (mode/pos/vel/accel/decel) but don't fire
        the trigger. Pair with :meth:`trigger_move` for synchronized starts."""
        mode_val = MODE_ABSOLUTE if mode == "absolute" else MODE_RELATIVE
        pulses = (self.deg_to_pulses(angle_deg) if mode == "absolute"
                  else self.deg_to_pulses_rel(angle_deg))
        pos_h, pos_l = split_32(pulses)
        await self.modbus.write_registers(
            self.slave_id, PR0_MODE,
            [mode_val, pos_h, pos_l, speed_rpm, accel, decel],
        )

    async def trigger_move(self) -> None:
        """Fire the staged PR0 move — a single register write (0x6207)."""
        await self.modbus.write_registers(self.slave_id, PR0_TRIGGER, [PR0_TRIGGER_VAL])

    async def stop_motion(self) -> None:
        # iCL-RS doesn't expose a separate "clean stop" register — the e-stop
        # value also acts as a controlled-stop on most drives in this family,
        # and the display flag for estopped is computed locally in sim only.
        await self.modbus.write_registers(self.slave_id, ESTOP_REG, [ESTOP_VAL])

    async def estop(self) -> None:
        await self.modbus.write_registers(self.slave_id, ESTOP_REG, [ESTOP_VAL])

    async def alarm_reset(self) -> None:
        await self.modbus.write_registers(self.slave_id, SYSTEM_CMD_REG, [ALARM_RESET_VAL])

    async def save_params(self) -> None:
        await self.modbus.write_registers(self.slave_id, SYSTEM_CMD_REG, [PERM_SAVE_VAL])

    async def set_home(self) -> None:
        """Set the current position as origin (write 0x21 to 0x6002), then
        persist to EEPROM. iCL-RS — see manual 'manual set-to-zero'."""
        await self.modbus.write_registers(self.slave_id, SET_ORIGIN_REG, [SET_ORIGIN_VAL])
        await self.save_params()

    async def read_status(self) -> MotorStatus:
        try:
            status_regs = await self.modbus.read_holding_registers(self.slave_id, MOTION_STATUS, 1)
            pos_regs = await self.modbus.read_holding_registers(self.slave_id, FEEDBACK_POS_H, 2)
            vel_regs = await self.modbus.read_holding_registers(self.slave_id, FEEDBACK_VEL_H, 2)
            alarm_regs = await self.modbus.read_holding_registers(self.slave_id, CURRENT_ALARM, 1)
        except Exception:
            return {
                "position_deg": 0.0, "position_pulses": 0, "velocity_rpm": 0,
                "running": False, "enabled": False, "estopped": False,
                "alarm": 0, "status_bits": 0, "offline": True,
            }

        raw_pulses = join_32_signed(pos_regs[0], pos_regs[1])
        status = status_regs[0]
        # Velocity: high register reads 0xFFFF when idle/invalid; use low only in that case.
        vel_rpm = vel_regs[1] if vel_regs[0] == 0xFFFF else join_32(vel_regs[0], vel_regs[1])
        running = bool(status & STATUS_RUNNING)
        enabled = bool(status & (STATUS_CMD_OK | STATUS_PATH_OK | STATUS_RUNNING))
        return {
            "position_deg": round(self.pulses_to_deg(raw_pulses), 2),
            "position_pulses": raw_pulses,
            "velocity_rpm": vel_rpm,
            "running": running,
            "enabled": enabled,
            "estopped": False,   # no per-drive estop latch on real hw
            "alarm": alarm_regs[0],
            "status_bits": status,
            "offline": False,
        }

    async def test_connection(self) -> dict:
        try:
            regs = await self.modbus.read_holding_registers(self.slave_id, MOTION_STATUS, 1)
            return {"ok": True, "slave_id": self.slave_id, "status": regs[0]}
        except Exception as e:
            return {"ok": False, "slave_id": self.slave_id, "error": str(e)}
