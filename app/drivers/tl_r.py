"""TL-R series RS485-integrated controller driver.

The TL-R has **two distinct positioning systems**:

* **Single positioning** (PA_033–PA_038, regs 51-56) — triggered over RS485
  by writing Bit 0 of the **control word** (PA_04E). This is the path we use.
* **Internal multi-segment positioning** (PA_050+, regs 80+, "Path 0..15") —
  triggered by **digital input pins**, NOT over the bus. Leaving Path 0
  registers alone has no effect on a Bit-0 trigger.

Register map (all addresses DECIMAL, per the TL-R manual sections 3.1 & 3.5):

==========  =========  ===========================================  =====
Param       Address    Description                                  Mode
==========  =========  ===========================================  =====
PA_004        4        Operating Status                              RO
PA_005        5        Current Alarm                                 RO
PA_008/009    8/9      Current Position H/L (signed 32-bit pulses)   RO
PA_00A       10        Current Speed (signed r/min)                  RO
PA_034       52        Positioning Acceleration Time (ms)            RW
PA_035       53        Positioning Deceleration Time (ms)            RW
PA_036       54        Positioning Speed (r/min)                     RW
PA_037       55        Positioning Target H (signed pulses)          RW
PA_038       56        Positioning Target L                          RW
PA_04E       78        Control Word (bit-packed)                     RW
PA_04F       79        Auxiliary Control (command codes)             RW
==========  =========  ===========================================  =====

**Move sequence**: write the single-positioning block (regs 52-56, contiguous
5-reg write of accel/decel/speed/target_h/target_l), then write the control
word (reg 78) with Bit0=1 (positioning enable) | Bit1=mode (rel=0/abs=1) |
Bit2=1 (interrupt current motion if any). The drive picks up the rising edge
of Bit0 and executes the move.

**Operating status bits (reg 4)**: Bit0=in-position, Bit1=homing-complete,
Bit2=motor-running, Bit3=fault, Bit4=motor-enabled, Bit5/6=soft limits.
"""

from __future__ import annotations

from ..modbus_interface import ModbusInterface
from ..registers import (
    degrees_to_pulses, split_32, join_32_signed, pulses_to_degrees,
)
from .base import MotorDriver, MotorStatus


# ---------------------------------------------------------------------------
# Register addresses (decimal)
# ---------------------------------------------------------------------------
PA_OPERATING_STATUS = 4
PA_CURRENT_ALARM   = 5
PA_CURRENT_POS_H   = 8
PA_CURRENT_POS_L   = 9
PA_CURRENT_SPEED   = 10

# JOG parameters (used with control word Bit 3, a held level)
PA_JOG_SPEED = 48                # PA_030 — JOG Operating Speed (r/min), signed -3000..3000
PA_JOG_ACCEL = 49                # PA_031 — JOG Acceleration Time (ms)
PA_JOG_DECEL = 50                # PA_032 — JOG Deceleration Time (ms)

# Single positioning parameters (used when triggering via control word Bit 0)
PA_POS_START_SPEED = 51          # PA_033 (not written by us — leave at NVRAM default)
PA_POS_ACCEL       = 52          # PA_034 — Positioning Acceleration Time (ms)
PA_POS_DECEL       = 53          # PA_035 — Positioning Deceleration Time (ms)
PA_POS_SPEED       = 54          # PA_036 — Positioning Speed (r/min)
PA_POS_TARGET_H    = 55          # PA_037 — Positioning Target H (pulses)
PA_POS_TARGET_L    = 56          # PA_038 — Positioning Target L

PA_CONTROL_WORD    = 78          # PA_04E
PA_AUX_CONTROL     = 79          # PA_04F

# ---------------------------------------------------------------------------
# Control word bit layout (PA_04E)
# ---------------------------------------------------------------------------
CW_POS_ENABLE      = 1 << 0      # rising edge starts the move
CW_POS_ABSOLUTE    = 1 << 1      # 0 = relative, 1 = absolute
CW_INTERRUPT       = 1 << 2      # 1 = interrupt current motion, 0 = queue/ignore
CW_JOG_ENABLE      = 1 << 3
CW_HOME_ENABLE     = 1 << 4
CW_STOP            = 1 << 5
CW_ESTOP           = 1 << 6

# ---------------------------------------------------------------------------
# Auxiliary control codes (PA_04F)
# ---------------------------------------------------------------------------
AUX_NONE              = 0x0000
AUX_RESTORE_FACTORY   = 0x0100
AUX_SAVE_PARAMETERS   = 0x0200
AUX_CLEAR_ALARM       = 0x0300
AUX_CLEAR_POSITION    = 0x0400
AUX_MOTOR_ENABLE      = 0x0500
AUX_MOTOR_RELEASE     = 0x0600

# ---------------------------------------------------------------------------
# Operating status bits (PA_004 / reg 4)
# ---------------------------------------------------------------------------
OS_IN_POSITION       = 1 << 0
OS_HOMING_COMPLETE   = 1 << 1
OS_MOTOR_RUNNING     = 1 << 2
OS_FAULT             = 1 << 3
# Bit 4: the manual labels this "Motor Enabled", but on this firmware it is
# actually set when the motor is RELEASED (free) and clear when energized —
# verified: enabled idle=0x0001, enabled moving=0x0004, released=0x0010. So
# enabled = NOT this bit.
OS_MOTOR_RELEASED    = 1 << 4


def _signed16(raw: int) -> int:
    """Decode a 16-bit unsigned register as signed int16."""
    return raw - 0x10000 if raw >= 0x8000 else raw


class TLRDriver(MotorDriver):
    """TL-R RS485 integrated controller."""

    # Reverse the TL-R's rotation sense so it flips the same physical direction
    # as the iCL-RS drives in the array. Applied to moves, jog, and feedback.
    direction = -1

    def __init__(self, modbus: ModbusInterface, slave_id: int,
                 command_ppr: int = 1000, encoder_ppr: int = 1000):
        self.modbus = modbus
        self.slave_id = slave_id
        self.command_ppr = command_ppr
        self.encoder_ppr = encoder_ppr

    async def _aux(self, code: int) -> None:
        await self.modbus.write_registers(self.slave_id, PA_AUX_CONTROL, [code])
        # Clear the aux command so the next write is fresh — the drive latches
        # on the value transition; some firmware versions require an explicit
        # clear before re-issuing the same code.
        await self.modbus.write_registers(self.slave_id, PA_AUX_CONTROL, [AUX_NONE])

    async def _control(self, bits: int) -> None:
        """Write the control word, briefly hold, then clear so the next op sees
        a fresh rising edge. The small hold matters for CW_STOP / CW_ESTOP —
        without it the drive sometimes never sees the edge."""
        import asyncio as _asyncio
        await self.modbus.write_registers(self.slave_id, PA_CONTROL_WORD, [bits])
        await _asyncio.sleep(0.05)
        await self.modbus.write_registers(self.slave_id, PA_CONTROL_WORD, [0])

    async def enable(self, state: bool = True) -> None:
        """Energize/hold (state=True) or release/free (state=False) the shaft.

        TL-R only. Unlike the iCL-RS (persistent level in Pr0.07), the TL-R
        uses an action CODE written to the Auxiliary Control register
        PA_04F (0x004F):
            0x0500 = Motor Enabled   (energize/hold)
            0x0600 = Motor Release   (free shaft)
        After issuing the code we read back status word 0x0004 and raise if the
        actual state doesn't match the request.

        DANGER: do NOT release (state=False) while the motor is holding a load
        that could drop or back-drive — there's no torque once released.
        """
        code = AUX_MOTOR_ENABLE if state else AUX_MOTOR_RELEASE
        await self._aux(code)
        import asyncio as _asyncio
        await _asyncio.sleep(0.1)            # let the status word settle
        actual = await self.is_enabled()
        if actual != state:
            raise IOError(
                f"TL-R sid={self.slave_id}: enable({state}) not confirmed "
                f"(is_enabled={actual})"
            )

    async def disable(self) -> None:
        """Release the shaft. TL-R only. See :meth:`enable` for the load warning."""
        await self.enable(False)

    async def is_enabled(self) -> bool:
        """Read status word 0x0004 and report whether the motor is energized.

        TL-R only. The manual labels bit 4 "Motor Enabled", but on this
        firmware bit 4 is set when the motor is RELEASED (verified on hardware:
        enabled-idle=0x0001, enabled-moving=0x0004, released=0x0010). So the
        true enabled state is the INVERSE of bit 4.
        """
        regs = await self.modbus.read_holding_registers(self.slave_id, PA_OPERATING_STATUS, 1)
        return not bool(regs[0] & OS_MOTOR_RELEASED)

    async def save_parameters(self) -> None:
        """Persist current parameters to EEPROM. TL-R only — writes the
        Auxiliary Control 'Save Current Parameters' code (0x0200) to PA_04F."""
        await self._aux(AUX_SAVE_PARAMETERS)

    async def set_home(self) -> None:
        """Clear the current position (AUX 0x0400) so the present spot becomes
        the origin, then persist to EEPROM. TL-R only."""
        await self._aux(AUX_CLEAR_POSITION)
        await self.save_parameters()

    async def start_move(self, mode, angle_deg, speed_rpm, accel, decel):
        await self.stage_move(mode, angle_deg, speed_rpm, accel, decel)
        await self.trigger_move()

    async def stage_move(self, mode, angle_deg, speed_rpm, accel, decel):
        """Write the single-positioning params (PA_034..038) but don't trigger.
        Remembers the mode so :meth:`trigger_move` knows abs vs rel."""
        pulses = (self.deg_to_pulses(angle_deg) if mode == "absolute"
                  else self.deg_to_pulses_rel(angle_deg))
        pos_h, pos_l = split_32(pulses)
        # One register at a time — a 5-register block write is silently
        # truncated by this firmware.
        await self.modbus.write_registers(self.slave_id, PA_POS_ACCEL,    [int(accel)])
        await self.modbus.write_registers(self.slave_id, PA_POS_DECEL,    [int(decel)])
        await self.modbus.write_registers(self.slave_id, PA_POS_SPEED,    [int(speed_rpm)])
        await self.modbus.write_registers(self.slave_id, PA_POS_TARGET_H, [pos_h])
        await self.modbus.write_registers(self.slave_id, PA_POS_TARGET_L, [pos_l])
        bits = CW_POS_ENABLE | CW_INTERRUPT
        if mode == "absolute":
            bits |= CW_POS_ABSOLUTE
        self._trigger_bits = bits

    async def trigger_move(self) -> None:
        """Fire the staged move with a clean low→high edge on the control word.
        Leaves the bits set (clearing Bit0 mid-move truncates it on this
        firmware)."""
        bits = getattr(self, "_trigger_bits", CW_POS_ENABLE | CW_INTERRUPT)
        await self.modbus.write_registers(self.slave_id, PA_CONTROL_WORD, [0])
        await self.modbus.write_registers(self.slave_id, PA_CONTROL_WORD, [bits])

    async def jog_start(self, direction, speed_rpm, accel, decel):
        """True TL-R jog: Bit 3 of the control word is a HELD level, not an
        edge. Speed + direction come from PA_030 (signed). We set the params
        then raise Bit 3 and leave it high — :meth:`jog_stop` drops it. This
        is what hold-to-jog should be: nothing keeps spinning if a single
        stop write is missed, because the motor only moves while the bit is
        held (and the drive re-reads it continuously)."""
        # self.direction flips the TL-R to match the iCL-RS rotation sense.
        spd = int(speed_rpm) * (1 if direction >= 0 else -1) * self.direction
        await self.modbus.write_registers(self.slave_id, PA_JOG_ACCEL, [int(accel)])
        await self.modbus.write_registers(self.slave_id, PA_JOG_DECEL, [int(decel)])
        # signed → 16-bit two's complement
        await self.modbus.write_registers(self.slave_id, PA_JOG_SPEED, [spd & 0xFFFF])
        # Raise JOG bit and leave it asserted (do NOT clear).
        await self.modbus.write_registers(self.slave_id, PA_CONTROL_WORD, [CW_JOG_ENABLE])

    async def jog_stop(self):
        """Assert the Stop bit (Bit 5) to halt the jog.

        Clearing the control word to 0 is NOT enough — verified on hardware:
        a move in progress keeps running until Stop is explicitly asserted.
        _control() pulses Bit 5 high (held 50 ms so the drive catches the
        edge) then clears it."""
        await self._control(CW_STOP)

    async def stop_motion(self) -> None:
        # Use the "Stop" bit (not e-stop) so the drive decelerates without
        # latching a fault — the right primitive for jog-release.
        await self._control(CW_STOP)

    async def estop(self) -> None:
        await self._control(CW_ESTOP)

    async def alarm_reset(self) -> None:
        await self._aux(AUX_CLEAR_ALARM)

    async def save_params(self) -> None:
        # Base-interface name used by the server's /api/save; delegate to the
        # explicitly-named TL-R method so there's one EEPROM-save code path.
        await self.save_parameters()

    async def read_status(self) -> MotorStatus:
        try:
            # Status + alarm in two single reads (different banks).
            status_regs = await self.modbus.read_holding_registers(self.slave_id, PA_OPERATING_STATUS, 1)
            alarm_regs = await self.modbus.read_holding_registers(self.slave_id, PA_CURRENT_ALARM, 1)
            pos_regs = await self.modbus.read_holding_registers(self.slave_id, PA_CURRENT_POS_H, 2)
            vel_regs = await self.modbus.read_holding_registers(self.slave_id, PA_CURRENT_SPEED, 1)
        except Exception:
            return {
                "position_deg": 0.0, "position_pulses": 0, "velocity_rpm": 0,
                "running": False, "enabled": False, "estopped": False,
                "alarm": 0, "status_bits": 0, "offline": True,
            }

        status = status_regs[0]
        raw_pulses = join_32_signed(pos_regs[0], pos_regs[1])
        vel_rpm = _signed16(vel_regs[0])
        return {
            "position_deg": round(self.pulses_to_deg(raw_pulses), 2),
            "position_pulses": raw_pulses,
            "velocity_rpm": vel_rpm,
            "running": bool(status & OS_MOTOR_RUNNING),
            "enabled": not bool(status & OS_MOTOR_RELEASED),
            "estopped": False,
            "alarm": alarm_regs[0],
            "status_bits": status,
            "offline": False,
        }

    async def test_connection(self) -> dict:
        try:
            regs = await self.modbus.read_holding_registers(self.slave_id, PA_OPERATING_STATUS, 1)
            return {"ok": True, "slave_id": self.slave_id, "status": regs[0]}
        except Exception as e:
            return {"ok": False, "slave_id": self.slave_id, "error": str(e)}
