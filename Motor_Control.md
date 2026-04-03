# Technical Specification: iCL-RS Series Dual-Motor Web Controller

This specification provides the Modbus RTU register mapping and sequencing logic for the STEPPERONLINE iCL-RS Series Integrated Closed Loop Stepper Motors.

## 1. Communication Architecture
- **Protocol:** Modbus RTU over RS485.
- **Default Baud Rate:** 38400 bps (configurable: 9600, 19200, 38400, 57600, 115200).
- **Data Format:** 8-bit data, no parity, 1 stop bit (Default).
- **Slave IDs:** 1-31 (Set via DIP switches SW1-SW5).
- **Configuration:** All connection parameters are stored in `config.json` and editable from the web UI Connection tab.

## 2. Motion Control Registers (Immediate Trigger Mode)
To control position (angle), speed, and ramping in a single command, use **Function Code 16 (0x10)** to write to the PR0 (Path 0) block.

| Parameter | Register (Hex) | Data Type | Scaling/Units | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Motion Mode** | `0x6200` | 16-bit | 1=Abs, 65=Rel | `0x0001` for Absolute; `0x0041` for Relative. |
| **Position High**| `0x6201` | 16-bit | Pulses | Upper 16 bits of target pulse count. |
| **Position Low** | `0x6202` | 16-bit | Pulses | Lower 16 bits. Command P/R = 10,000 (motor setting). |
| **Velocity** | `0x6203` | 16-bit | rpm | Target speed (max ~2500 rpm for iCL-RS). |
| **Acceleration** | `0x6204` | 16-bit | ms/1000rpm | Ramping time from 0 to 1000 rpm. |
| **Deceleration** | `0x6205` | 16-bit | ms/1000rpm | Ramping time from 1000 rpm to 0. |
| **Trigger** | `0x6207` | 16-bit | `0x0010` | Write `0x0010` to execute PR0 immediately. |

## 3. Real-Time Feedback & Status (Read-Only)
Poll these registers using **Function Code 03** to update the Web UI.

| Parameter | Register (Hex) | Data Type | Units | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Motion Status**| `0x1003` | 16-bit | Bitmap | Bit 4: Cmd OK; Bit 5: Path OK; Bit 2: Running. |
| **Feedback Pos** | `0x1014/15` | 32-bit signed | Pulses | Current position. Encoder P/R = 65,536. |
| **Feedback Vel** | `0x1046/47` | 32-bit | rpm | Current speed. Note: `0x1046` returns `0xFFFF` when idle; use `0x1047` only. |
| **Current Alarm** | `0x2203` | 16-bit | Code | `0x01`: Over-current; `0x02`: Over-voltage. |

### Important: Dual Pulse-Per-Revolution Values
The iCL-RS has two different PPR values:
- **Command P/R = 10,000** (`command_ppr`): Used when sending move commands via PR0 registers.
- **Encoder P/R = 65,536** (`encoder_ppr`): Used by the encoder for position feedback (32-bit signed).

These are configured independently in `config.json` under `motors.command_ppr` and `motors.encoder_ppr`.

## 4. Sequential Control Logic (Dual Motor with Delay)

The delay timer starts when Motor 1 **begins** its move (not after completion), so both motors can run simultaneously if the delay is shorter than Motor 1's move time.

1. **Enable Motors:** Write `1` to `0x000F` for software enable.
2. **Start Motor 1:** Send FC16 to `0x6200` (ID 01) with desired angle/speed.
3. **Delay Timer:** Non-blocking delay starts immediately after M1 trigger (`asyncio.sleep`).
4. **Start Motor 2:** Send FC16 to `0x6200` (ID 02) after delay expires.
5. **Wait for Completion:** Poll `0x1003` for both motors until Bit 4 (Cmd OK) returns `1`.

## 5. Critical System Commands
- **Emergency Stop:** Write `0x0040` to `0x6002` to stop all motion immediately. Also mapped to `Esc` key.
- **Reset Alarms:** Write `0x1111` to `0x1801` to clear active fault codes and E-stop state.
- **Permanent Save:** Write `0x2211` to `0x1801` to persist parameter changes after power-off.
- **Home:** Absolute move to position 0 (or software zero offset position).
- **Set Zero:** Software offset — stores current raw encoder position and subtracts it from all readings. The iCL-RS absolute encoder cannot be reset via Modbus.

## 6. Project Structure

```
Motors Pysim/
  config.json               # Connection, motor, and server settings
  requirements.txt          # Python dependencies
  run.py                    # Entry point (reads config for host/port)
  Motor_Control.md          # This specification
  app/
    __init__.py
    config.py               # Load/save config.json
    registers.py            # Modbus register constants, PPR conversion helpers
    motor_sim.py            # Trapezoidal velocity physics simulation
    modbus_interface.py     # ModbusInterface ABC, SimulatedModbus, RealModbus
    sequencer.py            # Dual-motor sequential control with watchdog
    server.py               # FastAPI REST + WebSocket routes
  static/
    index.html              # Single-page web UI (Control + Connection tabs)
```

## 7. Running

```bash
cd "Motors Pysim"
source venv/bin/activate
python run.py
```

Open `http://localhost:8000` in a browser. Use the **Connection** tab to configure serial port and motor settings. Use **Test Connection** to verify RS485 communication before switching to hardware mode.

## 8. Configuration (`config.json`)

| Section | Key | Default | Description |
| :--- | :--- | :--- | :--- |
| `connection.mode` | `simulation` / `hardware` | `simulation` | Sim mode or real RS485 |
| `connection.serial_port` | string | `/dev/ttyUSB0` | Serial port path |
| `connection.baudrate` | int | `38400` | Baud rate |
| `motors.motor1_slave_id` | int | `1` | Motor 1 Modbus slave ID |
| `motors.motor2_slave_id` | int | `2` | Motor 2 Modbus slave ID |
| `motors.command_ppr` | int | `10000` | Pulses/rev for move commands |
| `motors.encoder_ppr` | int | `65536` | Pulses/rev for encoder feedback |
| `server.host` | string | `0.0.0.0` | Web server bind address |
| `server.port` | int | `8000` | Web server port |
