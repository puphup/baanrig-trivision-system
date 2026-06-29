# Baanrig Trivision System

Multi-gateway controller for a **Trivision / triangular-prism advertising display** —
each motor turns a 3-faced prism, and the app flips the whole array between faces with
synchronized starts and selectable transition effects. Drives **Leadshine iCL-RS** and
**TL-R** motors across multiple **Modbus-TCP→RTU gateways** (up to ~50 motors), with a
built-in simulation mode for hardware-free testing.

Runs as a single double-clickable Windows `.exe` (no Python, no installer, no internet
needed) or directly from source on macOS / Linux / Windows.

## Download (Windows)

**[⬇ Download the latest Baanrig-Trivision.exe](https://github.com/puphup/baanrig-trivision-system/releases/latest/download/Baanrig-Trivision.exe)**

Or browse [all releases](https://github.com/puphup/baanrig-trivision-system/releases).

To run: copy the `.exe` to any folder on a Windows 10/11 PC and double-click. A
console window appears with logs, and your default browser opens to
`http://127.0.0.1:8000/`. Close the console to stop the app.

## Features

- **Up to 5 motors** — configurable slave IDs (DIP-switch addresses) from the UI.
- **Live status** — position (degrees), velocity (rpm), enable / running / alarm
  flags pushed over WebSocket at 4–10 Hz.
- **Manual move** — absolute or relative angular moves with configurable speed,
  acceleration and deceleration.
- **Jog (hold-to-move)** — press-and-hold reverse / forward buttons with an inline
  jog-speed input. Releases cleanly without latching an e-stop.
- **Multi-motor sequence** — trigger motors one after another with a configurable
  delay between triggers and an include / exclude checkbox per motor.
- **System commands** — software enable / disable, per-motor Home and Set-Zero,
  per-motor alarm reset, persistent-parameter save, emergency stop (Esc key).
- **Connection tab** — switch between simulation, Modbus RTU (RS485) and Modbus
  TCP at runtime, scan serial ports, edit motor IDs, change pulse-per-revolution
  settings, and test connectivity before applying.

## Quick start (Windows, end user)

1. Download `Baanrig-Trivision.exe` (link above).
2. Plug your USB ↔ RS485 adapter in (for RTU) or note the drive's IP (for TCP).
3. Double-click the exe.
4. In the **Connection** tab, pick the right mode + port / host, list the motor
   IDs, click **Save & Apply**, then close the console window and re-launch so
   the new settings take effect.
5. Use the **Control** tab to enable motors, jog them, run sequences, etc.

`config.json` (created next to the exe on first save) is plain JSON and editable
by hand if you prefer.

## Running from source

Requires Python 3.11+.

```bash
git clone https://github.com/puphup/baanrig-trivision-system.git
cd baanrig-trivision-system
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python run.py                     # dev server with auto-reload
# or:
python launcher.py                # same flow the .exe uses (auto-opens browser)
```

Open http://localhost:8000/.

## Building the Windows .exe yourself

Two options:

### Option A — Cloud build (GitHub Actions)

Push to `main`, or push a tag like `v1.2.3`:

```bash
git tag v1.2.3
git push origin v1.2.3
```

The **[Build Windows EXE](.github/workflows/build-windows.yml)** workflow builds
on a `windows-latest` runner, uploads the `.exe` as a 90-day artifact on every
push, and attaches it to a GitHub Release on every tag.

### Option B — Local Windows build

See [BUILD_WINDOWS.md](BUILD_WINDOWS.md). TL;DR: install Python 3.11+, double-click
`build_windows.bat`, find the output in `dist\Baanrig-Trivision.exe`.

## Configuration reference

`config.json` (auto-created on first save):

```json
{
  "connection": {
    "mode": "simulation",           // "simulation" | "hardware" | "tcp"
    "serial_port": "COM3",          // RTU only
    "baudrate": 38400,
    "data_bits": 8,
    "parity": "none",
    "stop_bits": 1,
    "tcp_host": "192.168.1.100",    // TCP only
    "tcp_port": 502
  },
  "motors": {
    "slave_ids": [1, 2, 3],         // 1..5 IDs, each 1..31
    "command_ppr": 10000,           // Pr0.01 on the drive
    "encoder_ppr": 65536            // encoder feedback PPR
  },
  "server": {
    "host": "0.0.0.0",
    "port": 8000
  }
}
```

Changing connection mode, slave IDs, baud rate, or port requires a restart
(close console, re-launch).

## Modbus details

Register addresses, motion modes, and status bitmasks are documented in
[Motor_Control.md](Motor_Control.md) and live in
[app/registers.py](app/registers.py). The implementation targets the
Leadshine iCL-RS series but should work with any drive that uses the same
PR0 register layout.

## Project layout

```
app/                    FastAPI server, sequencer, simulator, Modbus interface
static/index.html       Single-file dark-themed web UI
launcher.py             PyInstaller entry point (opens browser + starts uvicorn)
run.py                  Dev-mode entry point (uvicorn --reload)
Pysim.spec              PyInstaller build descriptor
build_windows.bat       One-click local Windows build
.github/workflows/      Cloud Windows build (Actions)
config.json             User-editable settings
```

## License

Internal project. No license declared yet — contact the repo owner before
redistributing.
