"""Modbus register addresses, constants, and helpers for iCL-RS series motors."""

# PR0 Motion Control (FC16 write targets)
PR0_MODE = 0x6200
PR0_POS_HIGH = 0x6201
PR0_POS_LOW = 0x6202
PR0_VELOCITY = 0x6203
PR0_ACCEL = 0x6204
PR0_DECEL = 0x6205
PR0_TRIGGER = 0x6207
PR0_TRIGGER_VAL = 0x0010

# Motion modes
MODE_ABSOLUTE = 0x0001
MODE_RELATIVE = 0x0041

# Status registers (FC03 read targets)
MOTION_STATUS = 0x1003
FEEDBACK_POS_H = 0x1014
FEEDBACK_POS_L = 0x1015
FEEDBACK_VEL_H = 0x1046
FEEDBACK_VEL_L = 0x1047
CURRENT_ALARM = 0x2203

# Status bitmasks
STATUS_RUNNING = 1 << 2
STATUS_CMD_OK = 1 << 4
STATUS_PATH_OK = 1 << 5

# System commands
ESTOP_REG = 0x6002
ESTOP_VAL = 0x0040
# Same control word (0x6002): value 0x21 sets the current position as the
# origin/zero ("manual set-to-zero", iCL-RS manual). Persist with PERM_SAVE_VAL.
SET_ORIGIN_REG = 0x6002
SET_ORIGIN_VAL = 0x0021
SYSTEM_CMD_REG = 0x1801
ALARM_RESET_VAL = 0x1111
PERM_SAVE_VAL = 0x2211

# Motor enable
SW_ENABLE_REG = 0x000F          # Pr0.07 "Forced enable by software" — iCL-RS only
SW_ENABLE_VAL = 1

# DI1 input function (Pr4.02). Factory default 0x0088 = "Enable input, Normally-
# Closed", which asserts enable on power-up so the shaft can't be turned by
# hand. Write 0x0000 to make DI1 invalid, hand control to Pr0.07 / SW_ENABLE_REG,
# then PERM_SAVE_VAL to 0x1801 (SYSTEM_CMD_REG) to persist. iCL-RS only — other
# driver families have totally different DI register layouts.
DI1_FUNC_REG     = 0x0145
DI1_FUNC_INVALID = 0x0000

# Home switch on DI3 (Pr4.04). 0x27 = ORG normally-open, 0xA7 = normally-closed.
# Like every DI-function change it only takes effect after an EEPROM save AND a
# drive power-cycle (manual 4.3.2 note 2).
DI3_FUNC_REG        = 0x0149
DI_FUNC_HOME_SWITCH = 0x0027
DI_FUNC_NC_BIT      = 0x0080
# Homing (Pr8.10-8.18). Pr8.10 bit0 = direction, bit1 = go to Pr8.13 after
# homing, bit2 = 1 → home-switch homing (0 = limit-switch). Velocities in rpm,
# acc/dec in ms per 1000 rpm. Trigger = write 0x20 to 0x6002 (0x21 is manual
# set-zero, used by SET_ORIGIN_VAL — don't confuse the two).
HOMING_MODE_REG       = 0x600A
HOMING_BY_HOME_SWITCH = 0x0004
HOMING_DIR_BIT        = 0x0001
HOMING_VEL_HIGH_REG   = 0x600F
HOMING_VEL_LOW_REG    = 0x6010
HOMING_ACC_REG        = 0x6011
HOMING_DEC_REG        = 0x6012
HOMING_TRIGGER_VAL    = 0x0020

# Command filter — rounds the linear accel/decel ramp into an S-curve so the
# motor doesn't jolt at the end of a move. Register unit is 0.1 ms; we write
# round(COMMAND_FILTER_MS * 10). Drive applies the filter to position commands.
# If the motor *oscillates* at the stop instead of jolting, the levers are
# Pr4.25 / 0x0173 (in-position de-jitter) and Pr1.00 / 0x0051 (position-loop Kp).
CMD_FILTER_REG = 0x00A1
# Pr2.00 command filter time, register units 0.1 ms, hardware range 0–512
# (= max 51.2 ms). Values above that are REJECTED by the drive, not clamped, so
# keep COMMAND_FILTER_MS ≤ 51. 50 ms (register 500) is the practical max smooth.
COMMAND_FILTER_MS = 50
CMD_FILTER_MAX_REG = 512

# Physical constants (overridden by config)
# command_ppr: what the motor expects for move commands (Pr0.01, default 10000)
# encoder_ppr: what the encoder reports back for position feedback
COMMAND_PPR = 10000
ENCODER_PPR = 10000


def set_pulses_per_rev(command_ppr: int, encoder_ppr: int):
    global COMMAND_PPR, ENCODER_PPR
    COMMAND_PPR = command_ppr
    ENCODER_PPR = encoder_ppr


def split_32(value: int) -> tuple[int, int]:
    """Split a 32-bit integer into (high16, low16)."""
    value = int(value) & 0xFFFFFFFF
    return (value >> 16) & 0xFFFF, value & 0xFFFF


def join_32(high: int, low: int) -> int:
    """Join two 16-bit words into a 32-bit unsigned integer."""
    return ((high & 0xFFFF) << 16) | (low & 0xFFFF)


def join_32_signed(high: int, low: int) -> int:
    """Join two 16-bit words into a signed 32-bit integer (for position feedback)."""
    raw = ((high & 0xFFFF) << 16) | (low & 0xFFFF)
    if raw >= 0x80000000:
        raw -= 0x100000000
    return raw


def degrees_to_pulses(degrees: float) -> int:
    """Convert degrees to pulse count for move commands."""
    return int(degrees * COMMAND_PPR / 360.0)


def pulses_to_degrees(pulses: int) -> float:
    """Convert encoder pulse count to degrees for display."""
    return pulses * 360.0 / ENCODER_PPR
