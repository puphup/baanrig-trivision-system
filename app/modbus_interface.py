"""Modbus interface abstraction with simulated and real RS485 implementations."""

import asyncio
from abc import ABC, abstractmethod

from .motor_sim import MotorSim
from .registers import (
    PR0_MODE, PR0_POS_HIGH, PR0_POS_LOW, PR0_VELOCITY,
    PR0_ACCEL, PR0_DECEL, PR0_TRIGGER, PR0_TRIGGER_VAL,
    MOTION_STATUS, FEEDBACK_POS_H, FEEDBACK_POS_L,
    FEEDBACK_VEL_H, FEEDBACK_VEL_L, CURRENT_ALARM,
    ESTOP_REG, ESTOP_VAL, SYSTEM_CMD_REG, ALARM_RESET_VAL, PERM_SAVE_VAL,
    SW_ENABLE_REG, SW_ENABLE_VAL,
    split_32, join_32, join_32_signed,
)


class ModbusInterface(ABC):
    @abstractmethod
    async def write_registers(self, slave_id: int, start_addr: int, values: list[int]) -> None:
        ...

    @abstractmethod
    async def read_holding_registers(self, slave_id: int, start_addr: int, count: int) -> list[int]:
        ...


class SimulatedModbus(ModbusInterface):
    """In-process motor simulation that responds to Modbus register reads/writes."""

    def __init__(self, motors: dict[int, MotorSim]):
        self.motors = motors
        # Buffered PR0 write values per slave
        self._pr0_buf: dict[int, dict[int, int]] = {sid: {} for sid in motors}

    async def write_registers(self, slave_id: int, start_addr: int, values: list[int]) -> None:
        motor = self.motors.get(slave_id)
        if motor is None:
            return

        # Map each register address to its value
        for offset, val in enumerate(values):
            addr = start_addr + offset
            self._handle_write(motor, slave_id, addr, val)

    async def read_holding_registers(self, slave_id: int, start_addr: int, count: int) -> list[int]:
        motor = self.motors.get(slave_id)
        if motor is None:
            return [0] * count

        result = []
        for offset in range(count):
            addr = start_addr + offset
            result.append(self._handle_read(motor, addr))
        return result

    def _handle_write(self, motor: MotorSim, slave_id: int, addr: int, value: int):
        buf = self._pr0_buf[slave_id]

        # PR0 motion registers — buffer until trigger
        if PR0_MODE <= addr <= PR0_DECEL:
            buf[addr] = value
            return

        if addr == PR0_TRIGGER and value == PR0_TRIGGER_VAL:
            # Execute buffered motion command
            mode = buf.get(PR0_MODE, 0x0001)
            pos_high = buf.get(PR0_POS_HIGH, 0)
            pos_low = buf.get(PR0_POS_LOW, 0)
            velocity = buf.get(PR0_VELOCITY, 100)
            accel = buf.get(PR0_ACCEL, 200)
            decel = buf.get(PR0_DECEL, 200)
            position = join_32_signed(pos_high, pos_low)
            motor.start_move(mode, position, velocity, accel, decel)
            buf.clear()
            return

        if addr == ESTOP_REG and value == ESTOP_VAL:
            motor.emergency_stop()
            return

        if addr == SYSTEM_CMD_REG:
            if value == ALARM_RESET_VAL:
                motor.reset_alarm()
                motor.clear_estop()
            return

        if addr == SW_ENABLE_REG:
            if value == SW_ENABLE_VAL:
                motor.enable()
            else:
                motor.disable()
            return

    def _handle_read(self, motor: MotorSim, addr: int) -> int:
        if addr == MOTION_STATUS:
            return motor.status_word

        pos_h, pos_l = split_32(int(motor.position))
        vel_h, vel_l = split_32(int(motor.velocity))

        if addr == FEEDBACK_POS_H:
            return pos_h
        if addr == FEEDBACK_POS_L:
            return pos_l
        if addr == FEEDBACK_VEL_H:
            return vel_h
        if addr == FEEDBACK_VEL_L:
            return vel_l
        if addr == CURRENT_ALARM:
            return motor.alarm_code

        return 0


class RealModbus(ModbusInterface):
    """Real Modbus RTU over RS485 using pymodbus sync client in a thread.

    The sync serial client is more reliable than the async one for USB-RS485
    adapters — it properly flushes TX bytes and waits for RX responses.
    All calls are run in a thread executor to stay async-compatible.
    """

    def __init__(self, port: str, baudrate: int = 38400, data_bits: int = 8,
                 parity: str = "none", stop_bits: int = 1):
        from pymodbus.client import ModbusSerialClient

        parity_map = {"none": "N", "even": "E", "odd": "O"}
        self._client = ModbusSerialClient(
            port=port,
            baudrate=baudrate,
            bytesize=data_bits,
            parity=parity_map.get(parity, "N"),
            stopbits=stop_bits,
            timeout=1,
        )
        self._lock = asyncio.Lock()
        self._connected = False

    async def connect(self):
        loop = asyncio.get_event_loop()
        self._connected = await loop.run_in_executor(None, self._client.connect)
        return self._connected

    async def disconnect(self):
        if self._connected:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._client.close)
            self._connected = False

    async def write_registers(self, slave_id: int, start_addr: int, values: list[int]) -> None:
        if not self._connected:
            raise ConnectionError("Not connected to serial port")
        async with self._lock:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: self._client.write_registers(start_addr, values, device_id=slave_id)
            )
            if result.isError():
                raise IOError(f"Write error: {result}")

    async def read_holding_registers(self, slave_id: int, start_addr: int, count: int) -> list[int]:
        if not self._connected:
            raise ConnectionError("Not connected to serial port")
        async with self._lock:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: self._client.read_holding_registers(start_addr, count=count, device_id=slave_id)
            )
            if result.isError():
                raise IOError(f"Read error: {result}")
            return list(result.registers)

    async def test_connection(self, slave_id: int) -> dict:
        """Try reading the motion status register to verify a motor responds."""
        try:
            if not self._connected:
                await self.connect()
            regs = await self.read_holding_registers(slave_id, MOTION_STATUS, 1)
            return {"ok": True, "slave_id": slave_id, "status": regs[0]}
        except Exception as e:
            return {"ok": False, "slave_id": slave_id, "error": str(e)}


class TcpModbus(ModbusInterface):
    """Modbus TCP client using pymodbus sync client in a thread."""

    def __init__(self, host: str = "192.168.1.100", port: int = 502):
        from pymodbus.client import ModbusTcpClient

        self._client = ModbusTcpClient(host=host, port=port, timeout=1)
        self._lock = asyncio.Lock()
        self._connected = False

    async def _run(self, fn):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fn)

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self):
        try:
            self._connected = await self._run(self._client.connect)
        except Exception:
            self._connected = False
        return self._connected

    async def ensure_connected(self) -> bool:
        """Reconnect a dropped gateway. Called OUT OF BAND by the server's
        reconnect loop — never from a read/write — so a down gateway's connect
        timeout can't slow the live status feed. Closes any half-open socket
        first so pymodbus actually re-dials."""
        if self._connected:
            return True
        try:
            await self._run(self._client.close)
        except Exception:
            pass
        return await self.connect()

    async def disconnect(self):
        if self._connected:
            try:
                await self._run(self._client.close)
            except Exception:
                pass
            self._connected = False

    async def _op(self, fn):
        """Run a client op, fast-failing if the gateway is marked down. On a
        failure we mark the gateway down and raise immediately — NO inline
        reconnect (that's what stalled every poll with a connect timeout). The
        background reconnect loop brings it back."""
        if not self._connected:
            raise ConnectionError("Modbus TCP host not connected")
        try:
            result = await self._run(fn)
            if result.isError():
                raise IOError(str(result))
            return result
        except Exception:
            self._connected = False     # flag down; reconnect loop will recover
            raise

    async def write_registers(self, slave_id: int, start_addr: int, values: list[int]) -> None:
        async with self._lock:
            await self._op(lambda: self._client.write_registers(start_addr, values, device_id=slave_id))

    async def read_holding_registers(self, slave_id: int, start_addr: int, count: int) -> list[int]:
        async with self._lock:
            result = await self._op(
                lambda: self._client.read_holding_registers(start_addr, count=count, device_id=slave_id)
            )
            return list(result.registers)

    async def test_connection(self, slave_id: int) -> dict:
        """Try reading the motion status register to verify a motor responds."""
        try:
            if not self._connected:
                await self.ensure_connected()
            regs = await self.read_holding_registers(slave_id, MOTION_STATUS, 1)
            return {"ok": True, "slave_id": slave_id, "status": regs[0]}
        except Exception as e:
            return {"ok": False, "slave_id": slave_id, "error": str(e)}
