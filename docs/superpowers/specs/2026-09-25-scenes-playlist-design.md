# Scenes / Playlists with Simulator Import-Export — Design

Date: 2026-09-25. Status: draft for review.

## Goal

Let an operator build, run, import and export **playlists** (ordered scene
transitions) on the real 231-motor wall, using **exactly the JSON the BAANRIG
web simulator saves and loads** (`app: "lv-trivision-corridor", version: 3`),
so a show designed in the simulator plays the same on the hardware and a show
tuned on the hardware can be replayed in the simulator.

## Decisions taken with the user

- Every cabinet will get DI3 home sensors like cabinet 7. Homing is therefore a
  normal first step; the remembered-face fallback (`home_state.json`) stays only
  as the bridge until all cabinets are wired.
- Face A (Silver) is the face showing at the home / face-1 position on both
  walls. Our face 1/2/3 = simulator A/B/C.
- Odd / even parity is by **panel number** (`motor % 2`), as in the simulator.
- The Scenes tab lives on the **Control page only** for now.

## Facts verified in the repo

- `trivision_layout.json` numbering equals `motor_map.json`: long index i is
  panel 137−i, short index i is panel 231−i. Long wall = motors 1…137
  (cabinets 1…7), short wall = 138…231 (cabinets 8…11).
- The layout is in metres. `motor_map.json` x/y are drawing units (≈192 per
  metre), the short wall is mirrored relative to the layout, and per-wall x is
  not strictly monotonic. **Wave order and the entrance→exit position `s` must
  come from the layout file, never from motor_map x.**
- Per-motor face is already known: the poller gives `position_deg` (zero-offset
  and remembered across restarts) and `face_for_position()` turns it into
  face 1…3. No new per-motor state is needed for "turn to face" rules.
- `show.py` already does preload + trigger, relative moves with pulse-remainder
  carry, and wait-all-stopped before hold. Playlists reuse that path.

## Corrections to send BAANRIG (doc does not match the rig)

| Doc says | Rig | Action |
|---|---|---|
| Gateways 115200 baud | 38400 on every gateway and drive | fix doc |
| DI3 0x0149 = 0xA7 (N.C.) | 0x27 (N.O.), cabinet 7 commissioned that way | fix doc, or confirm sensor type before wiring the rest |
| (not mentioned) drives boot enabled | drives boot **disabled** under software enable | controller enables before every run (already done) |
| Cubic ease-in-out | trapezoid: accel/decel ms then constant rpm | sim should use linear with ramps for timing parity |
| All 231 triggers start together | one trigger write per drive per RS485 bus, ≈7 ms each, 21 drives → ≈150 ms skew per cabinet | sim can add this as per-panel lag |

CONFIRM items answered by this design: #1 assumed true (mirrored A-B-C /
A-C-B) with a config knob if wrong; #2 wave out = backward 240° supported as
one 240° relative move; #3 forward for all-together / every-other, taken from
the step's `dirLong`/`dirShort`; #4 direction polarity is a per-wall config
knob; #5 numbering confirmed equal.

## Architecture

Three units, one new file.

1. **`app/playlist.py`** (new) — pure logic plus the runner.
   - `load_layout(path) -> dict[int, tuple[str, float]]`: panel number →
     (wall, s). `s = (X_MAX − x) / (X_MAX − X_MIN)` over both walls, exactly the
     simulator formula. Layout path is `trivision_layout.json` next to
     `motor_map.json`; the file ships with the app.
   - `validate(doc, limits) -> list[str]`: returns human-readable errors
     (empty = valid). Rules in "Restrictions" below. Unknown keys are ignored
     and preserved.
   - `plan_step(step, faces, wall_forward) -> list[Move]` where
     `faces: dict[motor_key, int]` (0=A,1=B,2=C, from the status cache) and
     `Move = (motor_key, delta_deg, delay_ms)`. Per motor:
     `wall, s` from its panel number; `parity = "odd" if motor % 2 else "even"`;
     `rule = step[parity]`; `fwd = step["dir"+Wall] == wall_forward[wall]`;
     `k = 0 (stay) | 1 or 2 (next, by angle) | (target−cur) mod 3 if fwd else (cur−target) mod 3`;
     `delta_deg = (+1 if fwd else −1) * k * 120`; motors with k = 0 are omitted.
     `delay_ms = 0 (seq 2) | s*sweep*1000 (seq 1) | (1−s)*sweep*1000 (seq 3)`.
   - `rpm_for(turn_s, angle_deg) -> int`:
     `rpm = angle*60 / (360 * turn)`, rounded, clamped
     to 1…40. The clamp is what "hardware can do"; validation rejects a turn
     that would clamp, so a valid playlist never silently runs at a different
     speed than the simulator shows.
   - `PlaylistRunner`: one asyncio task, `start(doc, loop: bool)`, `stop()`,
     `state()`. Loop per step, per run:
     1. `t0 = now`; plan moves from the current faces; fire them through
        `show.fire_moves()` (below).
     2. Wait all stopped (existing `_wait_all_stopped`).
     3. Between runs sleep `max(0, nextAt − elapsed)`; after the last run sleep
        `max(0, nextAt − elapsed) + pauseAfter`. This keeps the simulator's
        rhythm when the hardware is fast enough and never lets a slow turn eat
        into the hold (doc §3 hold rule), and it reproduces the 4 s gap of the
        "every other prism" pattern.
     4. Before step 1 of a run, if any online motor is not on face A, call the
        existing software home (`/api/home` body) and wait stopped, so every
        playlist starts on Silver as the simulator assumes.
     After every step `show.current_page` is set to the face of the first
     online motor (keeps Next/Prev display sane; the per-motor truth is the
     status cache).
2. **`app/show.py`** — one generalisation: `_fire_transition` is split so a
   new `fire_moves(drivers, moves: list[Move], speed_rpm, accel, decel)` takes
   an explicit per-motor delta and delay (enable → stage → trigger, unchanged
   ordering). The existing effects call it with a uniform delta. No other
   behaviour change.
3. **`app/server.py`** — routes, all JSON:
   - `GET /api/playlists` → `[{name, title, steps}]` from `playlists/*.json`
     next to `config.json` (rsync excludes it like `home_state.json`).
   - `GET /api/playlists/{name}` → the document verbatim (this is "export";
     the UI offers it as a download).
   - `PUT /api/playlists/{name}` body = simulator document → validate, save
     (this is "import" and "save from the editor"). Errors returned as
     `{error: [..]}`, nothing saved.
   - `DELETE /api/playlists/{name}`.
   - `POST /api/playlists/{name}/run` `{loop: bool}`, `POST /api/playlists/stop`,
     `GET /api/playlists/state` → `{running, name, step, run, phase, started_at}`.
   - `/api/estop` and `/api/show/auto/start` stop a running playlist first;
     the runner refuses to start while `show.busy`, auto-cycle or seek-home is
     active.
   - `GET /api/limits` gains the playlist limits (min turn formula inputs, max
     rpm) so the UI can show ranges.
4. **`static/index.html`** — a **Scenes** tab beside Control / Cabinets:
   playlist picker, Import (file input → PUT), Export (download link),
   New / Duplicate / Delete, a step table with one row per step (all simulator
   fields as inputs, `note` free text), Save (PUT with validation errors shown
   inline), Run / Run loop / Stop, and a status line (step n/N, run, phase,
   remaining hold). Touch-sized like the rest of the page.
5. **`app/config.py`** — one new persisted knob:
   `"wall_forward": {"long": "cw", "short": "ccw"}` = which simulator
   direction word means A→B→C (our +120°) on each wall. Default is the
   simulator's mirrored assumption; flip one word if a wall turns out to be
   built the other way. Accel/decel for playlists come from the existing
   `motion` defaults.

## Data format

The stored and exchanged document **is** the simulator document. Nothing is
added; `note` and `total_seconds` pass through untouched. Our app never needs
`nextAt` to be recomputed: the runner uses it as a minimum spacing, the
simulator uses it as the exact one.

## Restrictions (validation on import and on save)

| Field | Rule | Why |
|---|---|---|
| `seq` | 1, 2 or 3 | only three transition shapes exist |
| `angle` | 120 or 240 | anything else leaves a face off-axis |
| `turn` | `turn ≥ angle/240 and turn ≤ 20` | 40 rpm cap (drive ramps are ms per 1000 rpm, ≤ ~30 ms at 40 rpm); upper bound keeps rpm ≥ 1 |
| `sweep` | 0 … 60 s | sanity; sweep 0 is just seq 2 |
| `nextAt` | ≥ 0; for waves warn if `< sweep + turn`, for seq 2 warn if `< turn` | the simulator would overlap moves; the runner will not, so timing would differ |
| `pauseAfter` | 0 … 600 s | sanity |
| `runs` | 1 … 99 | sanity |
| `odd`, `even` | `stay`, `next`, `A`, `B`, `C` | simulator rule set |
| `dirLong`, `dirShort` | `cw` or `ccw`, and **opposite to each other** | doc §2: walls always turn opposite |
| step count | 1 … 200 | sanity |
| document | `app == "lv-trivision-corridor"`, `version == 3` | refuse foreign files |

Warnings are shown but do not block saving; errors block. Motion accel/decel
remain 200…2000 ms (existing UI cap, and below 200 ms the drive stalls with the
prism inertia at 40 rpm).

## Error handling

- A motor that is offline or fails to stage is skipped for that step and
  listed in `state().failed`; the step continues. Same policy as effects today.
- `_wait_all_stopped` timeout (60 s) ends the wait, the runner logs the stuck
  motors and continues; the operator sees them in the status line.
- Stop / E-STOP cancels the task; drives get `estop` via the existing route.
- Validation errors name the step index and field.

## Testing

`test_playlist.py` (plain asserts, no framework, like the other test scripts):

- layout: panel 137 has s = 0 (entrance), panel 1 has s = 1, panel 231 s = 0,
  and s for panel 138 equals the layout formula value.
- `plan_step` on the doc's example step 4 (seq 3, angle 240, `A`, ccw/cw) from
  faces all = C gives every motor delta −240 on both walls (backward in
  face units; the physical cw/ccw difference is the mirrored prism build,
  not a sign in our driver units) and delays `(1−s)*sweep`.
- "every other" step: only odd motors move, k = 1 to B from A, even omitted.
- turn-to-face with k = 0 omits the motor; `next` with angle 240 gives k = 2.
- `rpm_for(2.5, 120)` = 8, `rpm_for(1.5, 120)` = 13; `rpm_for(0.3, 120)` clamps
  and `validate` rejects that turn.
- `validate` rejects same-direction walls, angle 90, seq 4, foreign `app`.
- Runner: with the simulation driver, the customer-test playlist runs one
  cycle and every motor ends on face 1; a run started from face B homes
  first.

## Out of scope (YAGNI)

- Per-step accel/decel or per-motor speed overrides.
- A 3D preview in our app; the simulator does that.
- Scheduling playlists by clock time.
- Operator-page controls for playlists (added once homing on all cabinets is
  proven).
