# Baanrig Trivision System

Controller for a **Trivision wall**: **231 Leadshine iCL-RS motors in 11 cabinets**,
each turning a 3-faced prism. The app flips the whole wall between faces with
synchronized starts and selectable transition effects.

Every cabinet is a Modbus-TCP→RTU gateway on its own IP —
**cabinet *n* = `192.168.20.(99 + 2n)`** (cabinet 1 = `.101`, cabinet 11 = `.121`),
with a spare gateway at **+1** (`.102`, … `.122`) that can be switched in per cabinet.
A simulation mode drives the same UI with no hardware attached.

Runs as a single double-clickable Windows `.exe` (no Python, no installer, no internet
needed) or directly from source on macOS / Linux / Windows.

## Download (Windows)

**[⬇ Download the latest Baanrig-Trivision.exe](https://github.com/puphup/baanrig-trivision-system/releases/latest/download/Baanrig-Trivision.exe)**

Or browse [all releases](https://github.com/puphup/baanrig-trivision-system/releases).

To run: copy the `.exe` to any folder on a Windows 10/11 PC and double-click. A
console window appears with logs, and your default browser opens to
`http://127.0.0.1:8000/`. Close the console to stop the app.

## The UI

**Control tab**

Open with `?touch=1` (or on any coarse-pointer device) for **touch mode**: 48 px targets, press feedback, a "Sent ✓" toast per command, and motor numbers drawn inside the prisms in cabinet tabs.
The header shows the system clock and the PC's IP address; the **Light** button switches to a light theme (remembered per browser, or force it with `?theme=light`).

- **Wall map** — all 231 prisms drawn at their real positions and apex angles.
  Colour = current face; grey = offline; amber = alarm. Click one to select it.
- **Show controls** — Next / Previous / go-to-face, transition effect, speed,
  accel/decel and step timing, plus an auto-cycle with a hold time (forward, backward or random face).
- **Seek Home** (selected motor) — drive-level DI3 home-switch homing. The server
  only allows it on cabinets listed in `home_sensor_cabinets`; progress shows in
  the header. **Seek Home All** (toolbar, shown once any cabinet has sensors) homes
  every sensored cabinet in parallel and resets the show to face 1 when all are done.
- **Seek Home Cab N** (cabinet tab toolbar, and each row of the cabinet table) homes one
  cabinet: each drive is enabled, then homes to its switch. Several cabinets can home at
  once. A motor that hasn't found its switch after 120 s is stopped and powered off; the
  header lists it as "not homed: cab N id M".
- **Selected motor** — position, status and alarm, manual absolute/relative moves,
  jog, enable/disable, Home, Set Zero, Set Home, alarm reset.

**Cabinets tab**

- Per-cabinet row: active IP, a **spare-IP** checkbox, motor count, online count.
- **Seek Home** for one cabinet — shown only for cabinets in `home_sensor_cabinets`.
- **Commission** for one cabinet — fresh-drive setup (DI1 → software enable,
  DI3 = home switch, homing speeds, EEPROM save). Power-cycle the cabinet after.
- **Register diagnostics** — raw holding-register read/write against the selected
  motor for bench checks.

Live status (position, face, running / enabled / alarm) is pushed to the browser
over a WebSocket; a background poller per cabinet keeps the bus load flat.

### Operator page (tablet)

Open `http://<server-ip>:8000/operator` on the tablet and add it to the home screen
(iPad: Share → Add to Home Screen; Android Chrome: menu → Add to Home screen) so it
runs full-screen. It has only wall-wide controls: hold-to-fire E-STOP with Enable all,
Prev / Next face, auto-cycle (random face), Home the wall with Cancel (which e-stops the drives —
`seek_home()` is fire-and-forget so cancelling can't just stop tracking), Alarm reset,
Reconnect, and a per-cabinet health list. Anyone on the network with the URL can use it.

The desktop Control page now opens on a tab row: **Whole wall** plus **Cab 1 … Cab 11**.
A cabinet tab zooms the map to that cabinet and lists its motors; the last tab used is
remembered per browser.

## Quick start

1. Edit `config.json`: `mode` (`tcp` for the wall, `simulation` to try it dry) and
   `map` (`motor_map.json` for the wall, `bench_map.json` for a single bench motor).
2. Start it:
   - Windows end user: double-click `Baanrig-Trivision.exe`.
   - From source: `./venv/bin/python launcher.py` (add `--setup-iclrs-enable` or
     `--setup-iclrs-home` for one-time drive commissioning from the CLI instead of
     starting the server; `run.py` is the auto-reload dev server).
3. Open <http://localhost:8000/> — the browser opens by itself when using
   `launcher.py` or the `.exe`.

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

## Touch-screen kiosk PC (Linux)

The `deploy/` folder holds what the Ubuntu control station uses: `trivision.service`
(user systemd unit for uvicorn on port 8000), `trivision-kiosk.desktop` +
`kiosk.sh` (Firefox `--kiosk http://localhost:8000/?touch=1`, relaunched if
closed) and `root-setup.sh` (one-time GDM auto-login + linger, needs sudo).

To update a running station:

```
rsync -az --delete --exclude venv --exclude .git --exclude "Doc and info" --exclude home_state.json --exclude config.json --exclude playlists ./ bannrig@<pc-ip>:~/trivision/
ssh bannrig@<pc-ip> 'systemctl --user restart trivision.service; sleep 3; pkill -x firefox'
```

To stop the station booting straight into this app (a desktop icon starts it on
demand instead; used while another controller runs day to day), run on the PC
`bash ~/trivision/deploy/switch-to-launcher.sh` — it removes the autostart,
disables the service at boot, installs `deploy/trivision.desktop` on the desktop
and reboots. To go back to kiosk boot: `cp ~/trivision/deploy/trivision-kiosk.desktop
~/.config/autostart/ && systemctl --user enable trivision.service`.

Restarting the service does not restart Firefox; killing Firefox makes `kiosk.sh`
relaunch it. The pages are served with `Cache-Control: no-cache` so Firefox
revalidates on every launch. If a station still shows an old page, kill Firefox
and delete `~/snap/firefox/common/.cache/mozilla/firefox/<profile>/cache2`
before it relaunches.

## Scenes / playlists

The Scenes tab plays BAANRIG simulator playlists (`app: lv-trivision-corridor`, version 3) on the
wall. Import the simulator's saved JSON, or build one in the step editor (same fields and face preview as the simulator) and Export it back to the
simulator. Files live in `playlists/` next to `config.json` (not synced to the kiosk).

Limits enforced on save/import (the wall cannot do more): `angle` 120 or 240; `turn` at least
`angle/72` seconds (1.7 s for 120°, 3.4 s for 240°, the 12 rpm cap in `config.MAX_RPM`; quote customers 10 rpm) and at most 20 s; `sweep` 0–60 s; `pauseAfter` 0–600 s; `runs` 1–99; the walls must turn
opposite. The next step starts at the later of "all motors stopped" and `nextAt`, plus `pauseAfter`,
so a slow turn never shortens a hold. Face A is the home face; a playlist homes the wall (shortest
path) before its first step if any motor is off face A. `config.json` → `wall_forward` says which
direction word (`cw`/`ccw`) means A→B→C on each wall; flip one if a wall is built the other way.

## Configuration

`config.json`: `mode` (tcp|simulation), `map` (motor_map.json or bench_map.json),
`use_spare` ([cabinet numbers]), `home_sensor_cabinets` ([cabinet numbers with wired
DI3 home switches; Seek Home is refused everywhere else]), `motion` (speed/accel/decel/step_ms).

Gateways and motors are read from the map file; regenerate it with
`./venv/bin/python gen_motor_map.py` after `Trivision_Motor_Map.md` changes.

## Modbus details

Register addresses, motion modes, and status bitmasks are documented in
[Motor_Control.md](Motor_Control.md) and live in
[app/registers.py](app/registers.py). The implementation targets the
Leadshine iCL-RS series but should work with any drive that uses the same
PR0 register layout.

## Project layout

```
app/                    FastAPI server, show controller, sequencer, simulator,
                        Modbus interface, per-family motor drivers
static/index.html       Single-file web UI (dark/light theme, touch mode)
static/operator.html    Tablet page (/operator): E-STOP, homing, show, cabinet health
test_*.py               Plain assert scripts: ./venv/bin/python test_<name>.py
motor_map.json          The wall: 11 cabinets + 231 motors (source of truth)
gen_motor_map.py        Regenerates motor_map.json from Trivision_Motor_Map.md
Trivision_Motor_Map.md  Hand-maintained wall layout (positions, apex angles, IDs)
bench_map.json          One-motor map for a USB-RS485 bench drive
launcher.py             PyInstaller entry point (opens browser + starts uvicorn)
run.py                  Dev-mode entry point (uvicorn --reload)
Pysim.spec              PyInstaller build descriptor
build_windows.bat       One-click local Windows build
.github/workflows/      Cloud Windows build (Actions)
config.json             User-editable settings
deploy/                 Linux kiosk PC: systemd unit, Firefox kiosk autostart, root setup
```

## License

Internal project. No license declared yet — contact the repo owner before
redistributing.
