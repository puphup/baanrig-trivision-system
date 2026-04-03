"""Dual-motor sequential control logic with completion watchdog."""

import asyncio

from .modbus_interface import ModbusInterface
from .registers import (
    PR0_MODE, PR0_TRIGGER, PR0_TRIGGER_VAL,
    MOTION_STATUS, STATUS_CMD_OK,
    SW_ENABLE_REG, SW_ENABLE_VAL,
    ESTOP_REG, ESTOP_VAL,
    MODE_RELATIVE, degrees_to_pulses, split_32,
)


class DualMotorSequencer:
    def __init__(self, modbus: ModbusInterface, motor1_id: int = 1, motor2_id: int = 2):
        self.modbus = modbus
        self.m1_id = motor1_id
        self.m2_id = motor2_id
        self.phase: str = "idle"  # idle | enabling | moving_m1 | delay | moving_m2 | waiting | complete | error
        self.active: bool = False
        self.error: str | None = None
        self._cancelled: bool = False
        self._lock = asyncio.Lock()

    async def run_sequence(
        self,
        m1_angle: float, m1_speed: int, m1_accel: int, m1_decel: int,
        m2_angle: float, m2_speed: int, m2_accel: int, m2_decel: int,
        delay_s: float = 1.0,
        mode: int = MODE_RELATIVE,
    ):
        async with self._lock:
            self.active = True
            self._cancelled = False
            self.error = None
            try:
                await self._execute(
                    m1_angle, m1_speed, m1_accel, m1_decel,
                    m2_angle, m2_speed, m2_accel, m2_decel,
                    delay_s, mode,
                )
            except asyncio.CancelledError:
                self.phase = "idle"
                raise
            except Exception as e:
                self.phase = "error"
                self.error = str(e)
            finally:
                self.active = False

    async def _execute(
        self,
        m1_angle, m1_speed, m1_accel, m1_decel,
        m2_angle, m2_speed, m2_accel, m2_decel,
        delay_s, mode,
    ):
        # Step 1: Enable both motors
        self.phase = "enabling"
        await self.modbus.write_registers(self.m1_id, SW_ENABLE_REG, [SW_ENABLE_VAL])
        await self.modbus.write_registers(self.m2_id, SW_ENABLE_REG, [SW_ENABLE_VAL])

        if self._cancelled:
            self.phase = "idle"
            return

        # Step 2: Start Motor 1
        self.phase = "moving_m1"
        await self._send_move(self.m1_id, mode, m1_angle, m1_speed, m1_accel, m1_decel)

        if self._cancelled:
            self.phase = "idle"
            return

        # Step 3: Delay starts from when M1 was triggered (not when it finishes)
        self.phase = "delay"
        await asyncio.sleep(delay_s)

        if self._cancelled:
            self.phase = "idle"
            return

        # Step 4: Start Motor 2
        self.phase = "moving_m2"
        await self._send_move(self.m2_id, mode, m2_angle, m2_speed, m2_accel, m2_decel)

        # Step 5: Wait for both motors to finish
        self.phase = "waiting"
        await self._wait_completion(self.m1_id, timeout=30.0)
        await self._wait_completion(self.m2_id, timeout=30.0)

        self.phase = "complete"

    async def _send_move(self, slave_id: int, mode: int, angle_deg: float, speed: int, accel: int, decel: int):
        pulses = degrees_to_pulses(angle_deg)
        pos_h, pos_l = split_32(pulses)
        # Write PR0 registers as a contiguous block: mode, pos_h, pos_l, vel, accel, decel
        await self.modbus.write_registers(slave_id, PR0_MODE, [mode, pos_h, pos_l, speed, accel, decel])
        # Trigger
        await self.modbus.write_registers(slave_id, PR0_TRIGGER, [PR0_TRIGGER_VAL])

    async def _wait_completion(self, slave_id: int, timeout: float = 30.0):
        elapsed = 0.0
        while elapsed < timeout:
            if self._cancelled:
                return
            regs = await self.modbus.read_holding_registers(slave_id, MOTION_STATUS, 1)
            if regs[0] & STATUS_CMD_OK:
                return
            await asyncio.sleep(0.05)
            elapsed += 0.05
        raise TimeoutError(f"Motor {slave_id} did not complete within {timeout}s")

    async def emergency_stop_all(self):
        """Send e-stop to both motors."""
        self._cancelled = True
        await self.modbus.write_registers(self.m1_id, ESTOP_REG, [ESTOP_VAL])
        await self.modbus.write_registers(self.m2_id, ESTOP_REG, [ESTOP_VAL])
        self.phase = "idle"
        self.active = False

    def cancel(self):
        self._cancelled = True
