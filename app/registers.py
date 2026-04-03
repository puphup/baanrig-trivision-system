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
SYSTEM_CMD_REG = 0x1801
ALARM_RESET_VAL = 0x1111
PERM_SAVE_VAL = 0x2211

# Motor enable
SW_ENABLE_REG = 0x000F
SW_ENABLE_VAL = 1

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
