# Cabinet Tabs + Operator Tablet Page — Design

Date: 2026-09-09. Branch: `trivision-231` (continues the unmerged 231-motor work).
Builds on `docs/superpowers/specs/2026-09-07-trivision-231-design.md`.

## 1. Problem

The Control page draws all 231 prisms on one wall map. At desktop size each prism
is a few pixels wide, so an operator cannot read status per motor without
zooming. Separately, the wall needs a tablet page (7-inch iPad or Android,
portrait) that gives an operator a few large, safe buttons: emergency stop,
re-home the wall, step the show, clear alarms, and see per-cabinet health.

## 2. Decisions taken during brainstorming

| Question | Decision |
|---|---|
| What is a group? | One tab per cabinet (11 tabs). No new map data. |
| Where do the tabs live? | On the Control page. Tab row replaces the cabinet strip. Whole wall stays as a tab. |
| Tablet actions | E-STOP ALL + Enable all, Home the wall (with Cancel), Prev/Next face + Auto start/stop, Alarm reset all, Reconnect, read-only cabinet list. |
| Tablet access | Separate URL `/operator`, no PIN, no IP lock. |
| Architecture | Two pages sharing one API: extend `static/index.html`; new self-contained `static/operator.html`. |

## 3. Cabinet tabs (Control page)

### 3.1 Tab row

- Sits directly above the wall map, where the cabinet strip is today. `renderCabinetStrip()` /
  `updateCabinetStrip(d)` become `renderCabinetTabs()` / `updateCabinetTabs(d)`; the strip markup
  and `highlightCab` toggle are removed.
- Buttons: `Whole wall`, then `Cab 1` … `Cab 11`, in cabinet order from `mapInv.cabinets`.
- Each cabinet button shows `online/total` (for example `21/21`). Button gets class `bad` when
  any motor in the cabinet is offline or has an alarm, `warn` when any is not homed, otherwise plain.
  Counts patch every WebSocket tick; buttons are built once per inventory change.
- Active tab is stored in `localStorage["trivision.tab"]` as `"wall"` or a cabinet number.
  Missing or invalid value → `wall`.

### 3.2 Views

- **Whole wall** — identical to today's map (viewBox `250 600 2850 1120`, all prisms visible).
- **Cabinet N** — the SVG `viewBox` is set to the bounding box of that cabinet's motors
  padded by 60 units on every side; aspect handled by the existing `preserveAspectRatio="xMidYMid meet"`.
  Prisms of other cabinets get the `hidden` attribute (they keep receiving status patches;
  only visibility changes). Prism click still selects the motor into the focus panel.
- Bounding box function: `cabinetBox(inv, n)` → `{x, y, w, h}` over inventory items with
  `cabinet === n` using their `x`, `y`; padding applied by the caller. Pure function, no DOM.
- Below the map in cabinet view only: a table with columns
  `Motor | ID | Position ° | Status | Alarm | Homed`, one row per motor in the cabinet, sorted by
  motor number. Row click selects the motor (same handler as prism click). Rows patch per tick;
  the table is rebuilt only on tab change or inventory change.

### 3.3 Unchanged

Toolbar, show panel, focus panel, sequence panel, Cabinets tab, all API calls.

## 4. Operator page (`/operator`)

### 4.1 Serving

- `GET /operator` returns `static/operator.html` (same static-dir lookup as `/`).
- `POST /api/seek-home/cancel` → calls `_stop_homing()`; returns `{"ok": true, "cancelled": <bool>}`
  where `cancelled` is whether a run was active. Always 200.
- No other server changes. Every other button uses an existing route:
  `/api/estop`, `/api/enable`, `/api/seek-home` (body `{}`), `/api/show/prev|next`,
  `/api/show/auto/start|stop`, `/api/alarm-reset` (body `{}`), `/api/reconnect`.

### 4.2 Page shell

- Single file, inline CSS + JS, no libraries. `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">`,
  `apple-mobile-web-app-capable`, `mobile-web-app-capable`, dark `theme-color`.
- Portrait, one column, fits 600×1024 without scrolling; still usable at 800×1280 and in landscape
  (content centred, max width 720 px).
- Touch targets ≥ 64 px tall, base font 20 px, `touch-action: manipulation`, no hover styling,
  `user-select: none`.
- Dark theme with the same colour tokens as `index.html`.

### 4.3 Layout, top to bottom

1. **Status bar** — connection dot + label, `online/total`, `Face N`, and, while homing,
   `Homing done/total`.
2. **E-STOP ALL** — full-width red button. Fires on press-and-hold of 1000 ms
   (`pointerdown` starts a CSS ring fill; `pointerup`/`pointercancel`/`pointerleave` before
   1000 ms aborts). After firing: button shows `STOPPED` in grey and an `Enable all` button
   appears beside it (`/api/enable`). `Enable all` restores the red button.
   Note: on iCL-RS the estop is a one-shot quick-stop; there is no drive latch to release, so
   `Enable all` is the only "release" needed.
3. **Show** — `◀ Prev`, `Face N` (large number), `Next ▶`, then a full-width `Start auto` /
   `Stop auto` toggle. Uses default transition options (body `{}`) — effect settings stay on the desktop page.
   Prev/Next disabled while `show.busy`.
4. **Home the wall** — one button. While `homing.active`: the button is replaced by a progress
   bar (`done/total`, failed count in amber) and a `Cancel` button (`/api/seek-home/cancel`).
5. **Maintenance** — two half-width buttons: `Alarm reset`, `Reconnect`.
6. **Cabinet list** — 11 rows: `Cab N`, `online/total`, alarm count if any, and a dot:
   green all online + no alarm + all homed, amber any not homed, red any offline or alarm.
   Read-only.

### 4.4 Behaviour

- One WebSocket to the existing status feed (same URL as `index.html`). Frames carry
  `motors`, `inventory`, `show`, `homing`; the page derives everything from those.
- Any button greys out while its request is in flight; a toast (2 s) shows the result.
- Fetch timeout 5 s → toast `No reply from controller`, button re-enabled.
- Socket closed for > 2 s → status bar red, all buttons disabled; reconnect every 2 s.
- Response mapping to toast text:
  `estop` → `Stopped all motors`; `enable` → `Enabled N motors` (+ `, K failed`);
  `seek-home` ok → `Homing N motors`; `seek-home` error → the server's `error` string verbatim;
  `alarm-reset` → `Alarm reset on N motors` (+ `, K failed`); `reconnect` → `Reconnected`;
  `show/*` with `error` → that string verbatim.
- Page never shows raw JSON.

### 4.5 Out of scope

Per-motor move/jog/home, commissioning, register access, effect settings, mode switch,
PIN or IP restriction.

## 5. Testing

- `test_cabinet_box.py` — pure-Python port of the bounding-box rule against `motor_map.json`:
  every cabinet box is non-empty, contains all of its motors, and the union of boxes lies
  within the wall viewBox `250 600 2850 1120`. Prints `ok`.
- `test_operator_routes.py` — FastAPI `TestClient` in simulation mode:
  `GET /operator` is 200 with `text/html`; `POST /api/seek-home/cancel` returns
  `{"ok": true, "cancelled": false}` when idle; after `POST /api/seek-home {}` it returns
  `cancelled: true` and `/api/status` then reports `homing.active == false`. Prints `ok`.
- Manual (simulation mode): switch tabs on the desktop page, confirm cabinet view zooms and table
  patches; open `/operator` in a 600×1024 window and exercise E-STOP → Enable all, Next/Prev,
  Auto start/stop, Home the wall → Cancel, Alarm reset, Reconnect.

## 6. Files

| File | Change |
|---|---|
| `static/index.html` | Tab row replaces cabinet strip; viewBox switching; cabinet table; localStorage tab memory. |
| `static/operator.html` | New. |
| `app/server.py` | `GET /operator`; `POST /api/seek-home/cancel`. |
| `README.md` | Operator page URL + add-to-home-screen note; cabinet tabs mention. |
| `test_cabinet_box.py`, `test_operator_routes.py` | New. |
