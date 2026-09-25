# LV Trivision Corridor — Simulator Reference & Motor-Controller Build Guide

> **Corrections from the real rig (2026-09-25, controller side):** gateways and drives run **38400** baud, not
> 115200. Cabinet 7's DI3 home switches are wired **N.O. (0x0149 = 0x27)**, not N.C. 0xA7. Drives boot
> **disabled** under software enable; the controller enables before every move. The real motion profile is a
> trapezoid (accel/decel in ms, then constant rpm), not the cubic ease shown here. Triggers on one RS485 bus
> go out one drive at a time (≈7 ms each, ≈150 ms across a 21-drive cabinet). Our controller imports and
> exports this document format unchanged; see README "Scenes / playlists" for the limits it enforces.

Reference for Claude Code. It describes how the web simulator (built by BAANRIG) models the prism
motion, the playlist JSON format it loads, and how to turn the same logic into the real controller
that drives the 231 motors.

**Goal:** one playlist JSON file is the single source of truth. The simulator previews it; the
controller plays it on the real prisms using the same scheduling logic.

- Simulator (reference implementation): https://lv-trivision.vercel.app/ (password protected, single
  HTML page, Three.js). All motion logic lives in `buildSchedule()` in its inline module script.
- Companion data file: `trivision_layout.json` (prism X/Z positions for both walls, corridor centre
  line, prism dimensions, face layout, Face C gradient colours), exported from the simulator.
- Project: Louis Vuitton "Visionary Journeys Bangkok Extension" trivision room. Drawing:
  `TRIVISION_ROOM_09052026.svg`. Per-motor data: `Trivision_Motor_Map.md` (x/y, apex angle, IP, slave
  ID, cable length).

Items marked **CONFIRM** are assumptions that must be checked on site or with BAANRIG before relying on them.

---

## 1. Physical system

| Item | Value |
|---|---|
| Prisms / motors | 231 (one motor per prism) |
| Long wall | 137 prisms, panel numbers 1–137 |
| Short wall | 94 prisms, panel numbers 138–231 |
| Numbering | Counts up from the **exit** end on both walls (simulator `panelNumber()`); array index `i` runs from the **entrance** |
| Prism | Triangular, 3 faces, 1.70 m tall, 15 cm per face, 5 cm above floor, ~15 cm pitch |
| One face step | 120° of prism rotation |

### Faces (scenes)

| Face | Scene | Notes |
|---|---|---|
| A | Silver Mirror | Home / start scene |
| B | Monogram on Black Mirror | Simulator shows stars as a placeholder for the monogram |
| C | Gradient Color | Yellow at entrance → dark at exit |

### Face layout is mirrored between walls

```js
const FACE_LAYOUT = { long: ['A', 'B', 'C'], short: ['A', 'C', 'B'] };
```

- Long wall: turning **clockwise** (seen from above) goes A → B → C → A.
- Short wall: turning **counter-clockwise** goes A → B → C → A.
- The walls face each other, so they are mirror images. **CONFIRM** the real prisms are built this way.

### Control hardware (from project setup doc Rev 3)

| Item | Value |
|---|---|
| Drives | STEPPERONLINE iCL-RS integrated closed-loop steppers, Modbus RTU |
| Buses | 11 cabinets, one RS-485 bus per cabinet |
| Gateways | Waveshare RS485-TO-ETH, Modbus TCP → RTU mode, port 502, 115200-8-N-1, named `Cab1_1` … |
| Gateway IPs | 192.168.20.101–.121, odd = active, even = spare (one active gateway per cabinet) |
| Homing | C-MSX951N slot sensor (NPN) → drive CN2 DI3 (pin 3), DI3 configured as ORG N.C. (0xA7) |

| Cabinet | Motors | Count | Wall |
|---|---|---|---|
| C1–C6 | 1–126 (21 each) | 126 | Long |
| C7 | 127–137 | 11 | Long |
| C8 | 138–159 | 22 | Short |
| C9 | 160–183 | 24 | Short |
| C10 | 184–207 | 24 | Short |
| C11 | 208–231 | 24 | Short |

Motor numbers match the simulator panel numbers (long wall = C1–C7, short wall = C8–C11).
**CONFIRM** against `Trivision_Motor_Map.md`. Cabinet 6 has a different connection layout.
Motors 133–137 have estimated positions in the drawing.

---

## 2. Rotation rules

| Transition | Simulator `seq` | Long wall | Short wall | Faces sweep toward |
|---|---|---|---|---|
| Wave in (entrance → exit) | 1 | cw | ccw | exit |
| All together | 2 | cw | ccw | — |
| Wave out (exit → entrance) | 3 | **ccw** | **cw** | entrance |
| Every other prism | 2 (two steps) | cw | ccw | — |

- The two walls **always** turn in opposite directions.
- Prisms roll in the direction the wave travels, so wave out reverses both walls.
- Because wave out turns backward, reaching the next scene in the order A → B → C takes **two face
  steps (240°)**. The middle face shows briefly as it passes. **CONFIRM** with BAANRIG that this matches
  their controller (the simulator's own default for wave out was backward + 240°).
- "All together" and "Every other" use the forward direction by default. **CONFIRM**.
- Sign convention in the simulator: `cw` → negative angle, `ccw` → positive angle (Three.js Y-up, seen from above).

---

## 3. Simulator timing model (port this exactly)

A playlist is an ordered list of **steps**. Each step moves some or all prisms, then waits.

### Step fields

| Field | Type | Meaning |
|---|---|---|
| `seq` | 1 \| 2 \| 3 | 1 = wave entrance→exit, 2 = all at once, 3 = wave exit→entrance |
| `turn` | seconds | Duration of one prism's rotation (ease-in-out) |
| `sweep` | seconds | Time for the wave start-line to travel the whole wall (waves only) |
| `nextAt` | seconds | Time from this step's start to the next step's start (per run) |
| `pauseAfter` | seconds | Extra wait after the step before the next one starts |
| `runs` | int | Repeat count of this step |
| `odd` / `even` | rule | What odd- / even-numbered prisms do (see below) |
| `dirLong` / `dirShort` | `cw` \| `ccw` | Rotation direction per wall |
| `angle` | 120 \| 240 | Step size used by the `next` rule |
| `note` | string | Human-readable label; ignored by the simulator |

Rules for `odd` / `even`:
- `stay`: no movement.
- `next`: advance one face (or two if `angle` is 240) in the given direction.
- `A` / `B` / `C` ("turn to"): rotate in the given direction until that face shows; this can be 0, 1 or 2 face steps. The playlists use "turn to" so any transition order always lands on the right scene.

Parity uses the panel number: `number % 2 ? 'odd' : 'even'`.

### Scheduling algorithm (from `buildSchedule`)

```text
t = 0
faces[wall][parity] = 0            # 0=A, 1=B, 2=C; tracked per wall and per parity
for each step:
  for each wall, parity:
     fwd  = is this wall's direction the forward sense (long cw / short ccw)?
     k    = 1 or 2 for 'next' (2 if angle == 240); for 'A'|'B'|'C':
            k = (fwd ? target - cur : cur - target) mod 3; for 'stay': 0
     angle = sign(direction) * k * 120°
  for run in 0..runs-1:
     t0 = t + run * nextAt
     for each prism (wall, index i from entrance, normalized position s in [0,1] from entrance):
        if k == 0: skip
        progress = 1 if seq == 2 else (s if seq == 1 else 1 - s)
        start    = t0 if seq == 2 else t0 + progress * sweep
        emit event {start, dur: turn, angle, wall, index}
  update faces[wall][parity] by k in the chosen direction
  t += runs * nextAt + pauseAfter      # stepDuration()
cycle = t ; total = max(t, last event end)
```

`s` is computed from the drawing X coordinate across **both** walls, so prisms at the same X on the
two walls start together:

```js
const allX = [...LAYOUT.long, ...LAYOUT.short].map(p => p[0]);
const X_MAX = Math.max(...allX), X_MIN = Math.min(...allX);
p.s = (X_MAX - p.x) / (X_MAX - X_MIN);   // 0 at the entrance (right), 1 at the exit (left)
```

Rotation of each prism over time uses a cubic ease-in-out:

```js
const easeInOut = t => t < 0.5 ? 4*t*t*t : 1 - Math.pow(-2*t + 2, 3) / 2;
angle(t) = a0 + (a1 - a0) * easeInOut(clamp((t - t0) / dur, 0, 1));
```

On the real drives the motion profile comes from the drive's speed/acceleration settings; the
simulator curve is only a visual approximation.

### Hold time (the important number for the customer)

- A scene is **still** from the moment the last prism stops until the next step starts.
- To get a hold of H seconds:
  - **Wave step:** `nextAt = sweep + turn`, `pauseAfter = H`.
  - **All-together step:** `nextAt = turn`, `pauseAfter = H`.
- **Hold times must be exact on the real system.** Turn speed, acceleration and wave speed are tuned on
  site for smooth, vibration-free motion, so turn durations may differ from the simulator. Never
  let a slower turn eat into the hold: schedule the next step from "all motors reported done" + H,
  not from a fixed clock.

### "Every other prism, 4 s apart" = two all-together steps

```json
[
  { "seq": 2, "turn": 2, "nextAt": 4, "pauseAfter": 0, "odd": "B",    "even": "stay",
    "dirLong": "cw", "dirShort": "ccw", "angle": 120, "runs": 1, "sweep": 10 },
  { "seq": 2, "turn": 2, "nextAt": 2, "pauseAfter": 8, "odd": "stay", "even": "B",
    "dirLong": "cw", "dirShort": "ccw", "angle": 120, "runs": 1, "sweep": 10 }
]
```

---

## 4. Playlist JSON file format

```json
{
  "app": "lv-trivision-corridor",
  "version": 3,
  "title": "Wave in | All together | Wave out",
  "playlist": [
    { "seq": 2, "turn": 2,   "nextAt": 0,    "pauseAfter": 8, "odd": "stay", "even": "stay",
      "dirLong": "cw",  "dirShort": "ccw", "angle": 120, "runs": 1, "sweep": 10,
      "note": "Opening hold: Silver Mirror 8s" },
    { "seq": 1, "turn": 2.5, "nextAt": 12.5, "pauseAfter": 8, "odd": "B", "even": "B",
      "dirLong": "cw",  "dirShort": "ccw", "angle": 120, "runs": 1, "sweep": 10,
      "note": "Wave in to Monogram, hold 8s" },
    { "seq": 2, "turn": 2,   "nextAt": 2,    "pauseAfter": 8, "odd": "C", "even": "C",
      "dirLong": "cw",  "dirShort": "ccw", "angle": 120, "runs": 1, "sweep": 10,
      "note": "All together to Gradient, hold 8s" },
    { "seq": 3, "turn": 2.5, "nextAt": 12.5, "pauseAfter": 0, "odd": "A", "even": "A",
      "dirLong": "ccw", "dirShort": "cw",  "angle": 240, "runs": 1, "sweep": 10,
      "note": "Wave out (backward) to Silver Mirror" }
  ]
}
```

- Extra keys (`note`, `total_seconds`) are ignored by the simulator's `normalizeStep()`; the
  controller should ignore unknown keys too. `total_seconds` is informational only.
- The simulator loads/saves this via **Save & export → Load playlist / Save playlist**.
- Every existing playlist starts and ends on face A (Silver Mirror) on both walls.

### Existing playlist sets

| Set | Contents |
|---|---|
| `01_customer-test_...json` | Requested sequence: Silver hold → wave in → Monogram → all together → Gradient → wave out → Silver |
| `02_new-transition_every-other-prism-4s.json` | Every-other style for all three scene changes |
| `lv-trivision-12-versions/` | The 12 customer versions: first and second change vary (4 × 3), return to Silver Mirror fixed as wave out; `00_all-12-versions-back-to-back` chains all 12; `other-return-options/` holds the same set for each other return style |
| `lv-trivision-playlists/all-24-combinations/` | All 24 orders with every style used at most once per cycle |

Style names used everywhere: **Wave in**, **All together**, **Wave out**, **Every other**.

---

## 5. Building the real controller

### Recommended architecture

```text
playlist.json ──► schedule engine (port of buildSchedule) ──► per-motor event list
                                                               │
                         ┌─────────────────────────────────────┘
                         ▼
             11 bus workers (one per cabinet gateway, Modbus TCP :502)
                         ▼
               iCL-RS drives (Modbus RTU, slave IDs per Motor_Map)
```

- **Schedule engine:** a pure function with the same inputs and outputs as the simulator. Write unit
  tests that compare its event list with the simulator's for every playlist in the repo.
- **Motor state:** track each motor's absolute face (0/1/2) and absolute position in steps. Re-home
  (ORG sensor) at startup and whenever a drive reports an alarm or position error.
- **Angle → steps:** `steps = k * (steps_per_rev * gear_ratio / 3)`. **CONFIRM** the microstep setting
  and whether there is any gearing between motor and prism.
- **Direction:** map `cw`/`ccw` seen from above to the drive's +/− direction per wall. Depending on
  mounting, this may need a per-motor inversion flag in the motor map.
- **Hold-driven sequencing:** advance to the next step only after all motors involved report motion
  complete (or a timeout raises an alarm), then wait exactly `pauseAfter`.

### Timing across 231 motors on 11 buses

- Each bus runs at 115200 baud with 21–24 drives. Writing drives one by one adds a few ms per drive,
  so a naive "all together" start could skew by a noticeable fraction of a second across one bus.
- Recommended approach:
  1. **Preload** each move (target position, speed, acceleration) during the hold.
  2. **Trigger** with as few writes as possible: a broadcast write if the drive supports it, or a
     DI/trigger input, or back-to-back trigger writes. Check the iCL-RS Modbus manual for PR (path)
     mode and trigger registers; do not guess register addresses.
- Run the 11 bus workers in parallel. Wave offsets (up to `sweep` seconds) are large compared with bus
  latency, so waves are easy; "all together" and "every other" need the preload-and-trigger approach.
- Speed and acceleration are set on site for smooth, vibration-free motion. Keep them in a
  config file, not hard-coded. A slower turn must never shorten a hold (see section 3).

### Safety and operations

- E-stop / pause: stop issuing new steps, let moves finish or stop with controlled deceleration, then
  re-home before resuming.
- Detect and report drive alarms, closed-loop position errors, and offline slaves per cabinet.
- Provide a manual jog / test page per motor and per cabinet, plus a "go to face A/B/C" command for
  the whole room.
- Log every step start, completion time and fault, so real turn durations can be compared with the
  simulator and fed back into the playlists.

---

## 7. 3D rendering (reuse in the app)

The simulator's 3D view can be reused as the live preview / monitoring view in the controller app:
drive it from the same schedule (preview), or from real motor positions reported by the drives
(live mirror of the room).

### Stack

- Three.js **0.170.0** via import map from jsDelivr (`three` + `three/addons/`), single HTML page, no
  build step. `OrbitControls` from addons.
- `WebGLRenderer({ antialias, alpha, preserveDrawingBuffer, powerPreference: 'high-performance' })`,
  pixel ratio capped at 2, `SRGBColorSpace`, `ACESFilmicToneMapping` (exposure 1.0), PCF soft shadows
  with `shadowMap.autoUpdate = false` (shadows re-rendered only when needed).

### Coordinates and layout

- Units are metres. Drawing X → Three.js X, drawing "down" → Three.js +Z, Y is up.
- `trivision_layout.json` holds `long` (137 points) and `short` (94 points), each listed from the
  **entrance** (right end) to the **exit** (left end), plus a 34-point corridor `centerline`.
- Panel number: `long[i]` → `137 - i`, `short[i]` → `231 - i`.
- Each prism's resting orientation `theta0` points face A into the corridor:

```js
// for prism i on a wall: tangent from neighbours, normal toward the corridor
const a = pts[Math.max(0, i-1)], b = pts[Math.min(pts.length-1, i+1)];
let tx = b[0]-a[0], tz = b[1]-a[1]; const len = Math.hypot(tx, tz); tx/=len; tz/=len;
const sign = { long: -1, short: 1 }[wall];          // CORRIDOR_SIGN
const nx = -tz*sign, nz = tx*sign;
const theta0 = Math.atan2(nx, nz);                    // rotation about +Y
```

- Per frame: `quaternion = axisAngle(+Y, theta0 + angle(t))`, position `(x, PRISM.lift, z)`.

### Prism geometry

Equilateral triangular prism, side `face = 0.15`, height `1.70`, built as a `BufferGeometry` with 4
material groups: face 0, face 1, face 2, caps. Face 0 faces local +Z.

```js
function makePrismGeometry(s, H) {
  const r = s / (2*Math.sqrt(3)), R = 2*r;
  const V = [[-s/2, r], [s/2, r], [0, -R]];          // face k = edge V[k] -> V[k+1]
  // 3 side quads (normals outward, uv 0..1), top cap (+Y), bottom cap (-Y)
  // groups: (0,6,0) (6,6,1) (12,6,2) (18,6,3)
}
```

- Geometry face 0 = front (A). Face 1 = the face that comes to the front on a **clockwise** turn,
  face 2 = the one that comes to the front on a counter-clockwise turn.
- Materials per wall follow `FACE_LAYOUT` (`long: A,B,C`, `short: A,C,B`) plus a cap material.
- One `InstancedMesh` per wall (137 and 94 instances), `DynamicDrawUsage`, shadows on,
  `frustumCulled = false`. Matrices updated with `setMatrixAt` each frame.
- Top and bottom rails: `TubeGeometry` along a Catmull-Rom curve through the prism centres at
  y = 0.03 and y = lift + height + 0.035, radius 0.03.

### Materials

| Face | Material |
|---|---|
| A Silver Mirror | `MeshPhysicalMaterial` metalness 1, roughness 0.04, `envMap` = live cube camera |
| B Monogram on Black | `MeshPhysicalMaterial` metalness 0.1, roughness 0.18, clearcoat 1, clearcoatRoughness 0.06, stars canvas texture (8 random variants per prism), `envMap` = cube camera |
| C Gradient | `MeshPhysicalMaterial` metalness 0, roughness 0.45, tinted per instance with `gradientColor(i / (n-1))` along each wall |
| Caps | `MeshStandardMaterial` 0x17191c, roughness 0.6, metalness 0.4 |
| Rails | `MeshStandardMaterial` 0x2a2d31, roughness 0.5, metalness 0.6 |

- `gradientColor(f)` linearly interpolates the 25 colours in `face_c_gradient_entrance_to_exit`.
- Face B texture: canvas 192 × 2176 px per variant, black `#050506` background, a vertical column of
  star shapes. Replace with the real monogram artwork when it is available.
- A shared `onBeforeCompile` shader patch adds instance attributes (`aCorridor`, `aNumber`, `aTint`,
  `aVariant`) for: per-prism tint, display modes (all faces / inside faces only / outline), and
  optional face letters and panel numbers drawn from a glyph atlas.

### Lighting and reflections

- `scene.environment` = PMREM of a simple "gallery" scene (grey box room with bright ceiling light
  panels), `environmentIntensity` 1.1.
- Live reflections: `WebGLCubeRenderTarget(256, HalfFloat, mipmaps)` + `CubeCamera(0.1, 120)` placed on
  the corridor centre line nearest the camera at y = 1.2. Letters/numbers are hidden during the
  cube render so they never appear in reflections.
- `DirectionalLight` 2.4 intensity with 2048² shadow map, plus `HemisphereLight(0xdfe6ee, 0x1a1c20, 0.7)`.
- Floor `MeshStandardMaterial` 0x2b2f35 + `GridHelper`, fog `Fog(0x15171a, 30, 80)`.
- Floor labels "ENTRANCE" / "EXIT" on camera layer 1 (seen by the main camera, not by reflections).

### Camera views

`PerspectiveCamera(45°, near 0.05, far 250)` with damped `OrbitControls` (max polar angle just above
the floor). Preset views: **overview**, **top** (26 m above centre), **entrance** and **exit** (eye
height 1.6 m on the centre line, looking 4 m down the corridor), plus a walk-through mode along the
centre line. Views tween over 0.9 s.

### Video export

Offline, frame-by-frame render to H.264 MP4 using WebCodecs `VideoEncoder` + `mp4-muxer@5` (tries
avc1 High → Main → Baseline). Falls back to real-time `MediaRecorder` capture if WebCodecs is missing.

### Using it in the controller app

- **Preview mode:** feed the schedule engine's events into the renderer (same as the simulator).
- **Live mode:** poll drive positions (steps → degrees → radians) and set each instance to
  `theta0 + measured_angle`, so the 3D view mirrors the real room. Colour-code prisms with alarms,
  offline drives or position errors using the existing per-instance tint attribute.
- Keep the renderer in its own module so the schedule engine and the Modbus layer have no Three.js
  dependency.

---

## 8. Open questions (CONFIRM before final programming)

1. Real prism face order matches the mirrored layout (long A-B-C, short A-C-B).
2. Wave out turns backward with a 240° move (middle face passes briefly), as in the simulator.
3. Direction for "All together" and "Every other" (forward assumed).
4. Motor microsteps per revolution, any gearing, and cw/ccw polarity per wall or per motor.
5. Numbering in `Trivision_Motor_Map.md` equals the simulator panel numbers (1–137 long wall from the
   exit end, 138–231 short wall from the exit end).
6. Final hold time per scene (8 s requested; customer to confirm it is enough for photos).
7. Which style the customer wants for the fixed return to Silver Mirror in the 12 versions.
8. Monogram artwork for face B (simulator placeholder only; no effect on motor control).
