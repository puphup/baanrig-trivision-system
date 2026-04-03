"""Simulated stepper motor with trapezoidal velocity profile."""

import asyncio
import time

from . import registers


class MotorSim:
    def __init__(self, slave_id: int = 1):
        self.slave_id = slave_id
        self.position: float = 0.0  # pulses
        self.velocity: float = 0.0  # rpm
        self.target_position: float = 0.0
        self.target_velocity: float = 0.0
        self.accel_ms: int = 200  # ms per 1000rpm
        self.decel_ms: int = 200
        self.enabled: bool = False
        self.running: bool = False
        self.cmd_complete: bool = False
        self.path_complete: bool = False
        self.estopped: bool = False
        self.alarm_code: int = 0
        self._task: asyncio.Task | None = None
        self._last_tick: float = 0.0

    def start(self):
        """Start the background simulation loop."""
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self):
        """Stop the simulation loop."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def start_move(self, mode: int, pos_pulses: int, velocity: int, accel: int, decel: int):
        """Begin a new motion command."""
        if self.estopped or not self.enabled:
            return

        from .registers import MODE_ABSOLUTE, MODE_RELATIVE

        if mode == MODE_ABSOLUTE:
            self.target_position = float(pos_pulses)
        elif mode == MODE_RELATIVE:
            self.target_position = self.position + float(pos_pulses)
        else:
            return

        self.target_velocity = float(velocity)
        self.accel_ms = accel if accel > 0 else 200
        self.decel_ms = decel if decel > 0 else 200
        self.running = True
        self.cmd_complete = False
        self.path_complete = False

    def emergency_stop(self):
        """Immediate stop."""
        self.velocity = 0.0
        self.running = False
        self.estopped = True

    def clear_estop(self):
        self.estopped = False

    def reset_alarm(self):
        self.alarm_code = 0

    def enable(self):
        self.enabled = True

    def disable(self):
        self.enabled = False
        self.velocity = 0.0
        self.running = False

    @property
    def status_word(self) -> int:
        """Build the motion status register bitmap."""
        from .registers import STATUS_RUNNING, STATUS_CMD_OK, STATUS_PATH_OK
        status = 0
        if self.running:
            status |= STATUS_RUNNING
        if self.cmd_complete:
            status |= STATUS_CMD_OK
        if self.path_complete:
            status |= STATUS_PATH_OK
        return status

    async def _run_loop(self):
        """Physics tick loop at ~100Hz."""
        self._last_tick = time.monotonic()
        while True:
            await asyncio.sleep(0.01)
            now = time.monotonic()
            dt = now - self._last_tick
            self._last_tick = now

            if not self.enabled or self.estopped or not self.running:
                continue

            self._tick(dt)

    def _tick(self, dt: float):
        """Single physics step using trapezoidal velocity profile."""
        distance_remaining = self.target_position - self.position
        direction = 1.0 if distance_remaining >= 0 else -1.0
        abs_remaining = abs(distance_remaining)

        if abs_remaining < 1.0:
            # Arrived
            self.position = self.target_position
            self.velocity = 0.0
            self.running = False
            self.cmd_complete = True
            self.path_complete = True
            return

        # Convert target_velocity (rpm) to pulses/sec
        max_pps = self.target_velocity * registers.COMMAND_PPR / 60.0

        # Acceleration rate: accel_ms is ms to go from 0 to 1000rpm
        # So rate in rpm/s = 1000 / (accel_ms / 1000) = 1_000_000 / accel_ms
        accel_rpms = 1_000_000.0 / self.accel_ms if self.accel_ms > 0 else 5000.0
        decel_rpms = 1_000_000.0 / self.decel_ms if self.decel_ms > 0 else 5000.0

        # Convert to pulses/s^2
        accel_pps2 = accel_rpms * registers.COMMAND_PPR / 60.0
        decel_pps2 = decel_rpms * registers.COMMAND_PPR / 60.0

        current_pps = abs(self.velocity) * registers.COMMAND_PPR / 60.0

        # Stopping distance at current speed
        stopping_dist = (current_pps ** 2) / (2.0 * decel_pps2) if decel_pps2 > 0 else 0

        if abs_remaining <= stopping_dist:
            # Decelerate
            current_pps = max(0.0, current_pps - decel_pps2 * dt)
        elif current_pps < max_pps:
            # Accelerate
            current_pps = min(max_pps, current_pps + accel_pps2 * dt)

        # Ensure minimum speed to avoid stalling near target
        if current_pps < 10.0 and abs_remaining > 1.0:
            current_pps = min(100.0, max_pps)

        # Update position
        step = current_pps * dt * direction
        self.position += step

        # Convert back to rpm for status
        self.velocity = current_pps * 60.0 / registers.COMMAND_PPR if registers.COMMAND_PPR > 0 else 0.0

        # Overshoot check
        new_remaining = self.target_position - self.position
        if (direction > 0 and new_remaining <= 0) or (direction < 0 and new_remaining >= 0):
            self.position = self.target_position
            self.velocity = 0.0
            self.running = False
            self.cmd_complete = True
            self.path_complete = True
