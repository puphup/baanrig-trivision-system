# Trivision 231-motor controller — design

Date: 2026-09-07. Status: approved in chat, awaiting written review.

## 1. Goal

Scale the existing FastAPI + pymodbus controller from a 60-motor bench setup to
the production wall: 231 iCL-RS motors in 11 cabinets on 192.168.20.0/24, each
with a DI3 home switch. Replace the tile grid with a wall map drawn from
`Trivision_Motor_Map.md` and make homing and drive commissioning one-click per
cabinet. Keep every driver and show routine already verified on the bench.

Out of scope: TL-R drives (kept in code, not used), per-section effects, any
database, any frontend framework.

## 2. Data model and configuration

### 2.1 Motor map file (source of truth)

`motor_map.json` at repo root, generated once by a small script from the JSON
block in `Trivision_Motor_Map.md`. Never written by the app.

```json
{
  "cabinets": [
    {"cabinet": 1, "host": "192.168.20.101", "spare": "192.168.20.102", "port": 502}
  ],
  "motors": [
    {"motor": 1, "cabinet": 1, "slave_id": 1, "x": 287.8, "y": 1003.4,
     "apex_deg": -95.5, "estimated": false}
  ]
}
```

- 11 cabinets, IP rule `192.168.20.(99 + 2n)` primary, `+1` spare. Motor
  counts per cabinet: 21,21,21,21,21,21,11,22,24,24,24 (total 231).
- Coordinates are the drawing's SVG space (`viewBox 0 0 3371 2384`, y down,
  wall bbox x 288–3060, y 650–1676). Triangle is rotated by `apex_deg + 90`.
- Motors 133–137 carry `estimated: true`.
- Cabinet `host` may be a serial device (`/dev/...` or `COMn`), in which case
  `port` is the baud rate. `bench_map.json` holds the single bench motor this
  way (cabinet 1, `/dev/cu.usbserial-2140`, 115200, slave 1).

### 2.2 config.json (small, app-owned)

```json
{
  "mode": "tcp",
  "map": "motor_map.json",
  "use_spare": [],
  "motion": {"speed": 5, "accel": 500, "decel": 900, "step_ms": 200}
}
```

- `mode`: `tcp` or `simulation`. Simulation loads the same map so the wall UI
  can be exercised with 231 fake motors.
- `use_spare`: list of cabinet numbers whose spare IP is used instead of the
  primary. Toggled from the Cabinets tab, saved to config.json.
- Old-format `gateways`/`motors` keys are ignored; the Setup editor is
  removed. Limits become `MAX_GATEWAYS = 16`, `MAX_MOTORS_PER_GATEWAY = 32`,
  `MAX_TOTAL_MOTORS = 512`.

### 2.3 Runtime identity

- Gateway id stays `gwN` where N is the cabinet number; the internal motor key
  stays `gwN.slave`. Server internals, show.py and the drivers are unchanged.
- The loader also builds, per motor: `motor` (1–231), `label` (`M001`),
  `cabinet`, `x`, `y`, `apex_deg`, `estimated`. These ride along in every
  status record and in `/api/motors` (static inventory, fetched once by the
  UI).
- Ordered motor list (used by effects, Home All, Seek Home All) is by wall
  number.

## 3. Status feed

Today's loop reads four registers per motor every 0.25 s. At ~20 ms per RTU
transaction that is ~1.7 s per bus for 21 motors, so the loop is replaced by:

- One asyncio task per cabinet, started in `_build_runtime`, running in the
  executor with that cabinet's client. It loops over the cabinet's motors and
  performs **two reads** per motor instead of four: a block read
  `0x1003 .. 0x1015` (19 registers: status word and position counter) and the
  alarm register `0x2203`. Velocity (`0x1046`) is dropped; the UI derives
  "moving" from the status running bit. Driver gets `read_status_fast()`
  which returns the existing status dict shape with `velocity_rpm = 0`.
- Results go into a per-key cache; `/api/status` and the WebSocket broadcast
  (still every 0.25 s) serve the cache. Zero offsets are applied on read as
  today.
- Cabinets poll independently, so refresh per motor is ~0.8–1 s regardless
  of cabinet count. A cabinet whose client is disconnected marks its motors
  offline and retries connect every 5 s; other cabinets are unaffected.
- Motion commands share the per-client lock with the poller, as today.

## 4. UI

Single page, two tabs. Vanilla JS + inline SVG, no build step.

### 4.1 Control tab

- Toolbar: Prev face, Next face, auto-cycle Start/Stop with interval, effect
  picker, Seek Home All, Stop All. Online counter `online/231`.
- Wall map: `<svg viewBox="250 600 2850 1120">`. One `<g>` per motor, a
  triangle at (x, y) rotated `apex_deg + 90`, size ~22 units. Fill = colour of
  the face currently facing out (three fixed colours). Stroke: grey offline,
  red alarm, amber moving, blue selected, dashed outline for `estimated`.
  Hover tooltip shows label, cabinet, ID, angle. Click selects. Map is
  rendered once from `/api/motors`; status updates only patch class/fill.
- Cabinet strip: 11 buttons `Cab n  21/21`, red count if any alarm, grey if
  offline. Click highlights that cabinet's motors on the map; click again to
  clear.
- Side panel (selected motor): label, cabinet, slave ID, angle, face, status,
  alarm code; buttons Go to face 1/2/3, jog CW/CCW (hold), Seek Home, Set
  Zero, Alarm reset.

### 4.2 Cabinets tab

- Table, one row per cabinet: number, active IP, spare toggle, online count,
  buttons Seek Home cabinet, Commission cabinet.
- Motion settings (speed/accel/decel/step) with the existing caps and hints.
- Diagnostics box for the selected motor: register read/write (existing
  `/api/reg` endpoints).

### 4.3 Removed

Setup tab gateway/motor editor, driver-type picker, per-gateway band colours,
TL-R specific UI.

## 5. Homing and commissioning

### 5.1 Seek Home All / cabinet

`POST /api/seek-home {cabinet?: n}` (no body = all). For each targeted cabinet
in parallel: for each motor in wall order, trigger `seek_home()` then sleep
200 ms (stagger). Each motor spawns the existing `_zero_display_after_homing`
task. The endpoint returns immediately with the targeted count; progress is
visible on the map (amber while homing, then normal). When every targeted
motor's homing task finishes, the show face index resets to face 1 if the
target was the whole wall.

Per-motor Seek Home keeps the existing `motor_key` request form.

### 5.2 Commission cabinet

`POST /api/commission {cabinet: n}`. For each motor in the cabinet:
`configure_software_enable()` then `configure_home_switch(normally_closed=False,
high_rpm=3, low_rpm=1)` (both existing driver methods; they save EEPROM).
Returns `{ok, done, failed: [{key, error}]}`. The UI shows the result list and
the message "Power-cycle cabinet n now, then press Reconnect". The launcher
flags `--setup-iclrs-enable` / `--setup-iclrs-home` remain for CLI use.

## 6. Show and effects

Unchanged apart from ordering by wall number and reading the motion defaults
from `config.json → motion`. Relative ±120° flips with pulse-remainder carry
stay as implemented.

## 7. Error handling

- Offline cabinet: motors grey, commands to them skipped and listed in the
  `failed` array of bulk endpoints (existing `_bulk_result` shape).
- Map load errors (missing file, duplicate motor number, cabinet without
  motors, count over limit) fail startup with a clear message; the app does
  not fall back to an empty config.
- Commission or homing failures never retry automatically.

## 8. Testing

- `test_motor_map.py`: assert-based check of the loader (IP rule for
  cabinets 1 and 11, 231 motors, per-cabinet counts, key `gw4.10` ↔ motor 73,
  estimated flags on 133–137, serial host detection for the bench map).
- `test_status_block.py`: FakeModbus block read parses to the same dict as
  the four-read path.
- Manual: simulation mode with the full map (UI, Seek Home All flow); bench
  map with the real serial motor (commission, seek home, show); then one
  production cabinet before the full wall.

## 9. Implementation order

1. Map generator script + `motor_map.json` + `bench_map.json`; loader in
   `config.py`; raise limits; `/api/motors`.
2. Per-cabinet status poller with block read.
3. Wall map UI (Control tab), cabinet strip, side panel.
4. Cabinets tab: spare toggle, Seek Home cabinet, Commission cabinet.
5. Seek Home All with stagger and face reset.
6. Remove old Setup editor and dead UI.
