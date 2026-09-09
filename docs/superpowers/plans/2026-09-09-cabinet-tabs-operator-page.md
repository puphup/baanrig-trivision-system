# Cabinet Tabs + Operator Tablet Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the 231-motor Control page into a Whole wall tab plus one tab per cabinet, and add a self-contained `/operator` page for a 7-inch tablet with E-STOP, homing, show stepping, alarm reset, reconnect and a cabinet health list.

**Architecture:** Two pages share one FastAPI backend. `static/index.html` gains a tab row that swaps the existing SVG `viewBox` to a cabinet's bounding box and shows a per-cabinet table. `static/operator.html` is a new single-file page driven by the same `/ws` status feed and existing `/api/*` routes. The server gains only `GET /operator` and `POST /api/seek-home/cancel`.

**Tech Stack:** FastAPI + uvicorn, vanilla HTML/CSS/JS (no libraries), plain `assert` test scripts run with `./venv/bin/python <file>`.

**Spec:** `docs/superpowers/specs/2026-09-09-cabinet-tabs-operator-page-design.md`

## Global Constraints

- Branch `trivision-231`; never commit to `main`.
- No new Python or JS dependencies. `httpx` is not installed; tests call handlers directly.
- Tests are plain scripts that end with `print("ok")`, run as `./venv/bin/python test_<name>.py`. No pytest.
- Every commit message ends with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Ponytail mode: shortest correct diff; mark deliberate simplifications with a `// ponytail:` or `# ponytail:` comment.
- `curl` is blocked in this environment; use `./venv/bin/python` with `urllib` for HTTP checks.
- Whole-wall viewBox is exactly `250 600 2850 1120`; cabinet padding is exactly `60` SVG units.
- Tab memory key is exactly `localStorage["trivision.tab"]`, values `"wall"` or a cabinet number string.
- Operator page: E-STOP fires after a `1000` ms press-and-hold; fetch timeout `5000` ms; toast lasts `2000` ms; buttons `min-height: 64px`; base font `20px`; no external CSS/JS; must not scroll at 600×1024.
- Operator page copy (verbatim): `HOLD TO E-STOP`, `STOPPED`, `Enable all`, `◀ Prev`, `Next ▶`, `Start auto` / `Stop auto`, `Home the wall`, `Cancel`, `Alarm reset`, `Reconnect`, toast `No reply from controller`.

---

### Task 1: `POST /api/seek-home/cancel` + route test

**Files:**
- Modify: `app/server.py` (after `seek_home`, around line 584)
- Create: `test_operator_routes.py`

**Interfaces:**
- Consumes: existing `_stop_homing()`, `homing_state`, `_home_tasks`, `seek_home(SeekHomeRequest)`, `_reload_runtime()`, `_stop_pollers()`, `_teardown_runtime()`, `app.config.load_config()`.
- Produces: `async def seek_home_cancel() -> {"ok": True, "cancelled": bool}` registered at `POST /api/seek-home/cancel`. Task 3 extends this test file with the `/operator` handler check.

- [ ] **Step 1: Write the failing test**

Create `test_operator_routes.py`:

```python
"""Operator-page routes: seek-home/cancel stops a run and clears state.
Run: ./venv/bin/python test_operator_routes.py"""
import asyncio
from app import server as S
from app.config import load_config


async def main():
    cfg = load_config()
    cfg["mode"] = "simulation"          # never touch real gateways from a test
    S.config = cfg
    await S._reload_runtime()
    try:
        r = await S.seek_home_cancel()
        assert r == {"ok": True, "cancelled": False}, r

        r = await S.seek_home(S.SeekHomeRequest())
        assert r.get("ok") and r["total"] == len(S.drivers), r
        assert S.homing_state["active"] is True

        r = await S.seek_home_cancel()
        assert r == {"ok": True, "cancelled": True}, r
        assert S.homing_state["active"] is False and not S._home_tasks, S.homing_state

        # A cancelled run must not block the next one.
        r = await S.seek_home(S.SeekHomeRequest())
        assert r.get("ok"), r
        await S._stop_homing()
    finally:
        await S._stop_pollers()
        await S._teardown_runtime()
    print("ok")


asyncio.run(main())
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./venv/bin/python test_operator_routes.py`
Expected: `AttributeError: module 'app.server' has no attribute 'seek_home_cancel'`

- [ ] **Step 3: Add the route**

In `app/server.py`, directly after the `seek_home` function body (before `async def _seek_home_cabinet`), add:

```python
@app.post("/api/seek-home/cancel")
async def seek_home_cancel():
    """Operator-page Cancel. Always 200 so the tablet can press it any time."""
    was_active = homing_state["active"]
    await _stop_homing()
    return {"ok": True, "cancelled": was_active}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./venv/bin/python test_operator_routes.py`
Expected: `ok` (takes a few seconds; the sim runtime builds 231 motors)

Also run the existing scripts to be sure nothing regressed:
`./venv/bin/python test_pollers.py && ./venv/bin/python test_home_switch.py && ./venv/bin/python test_motor_map.py`
Expected: three `ok` lines.

- [ ] **Step 5: Commit**

```bash
git add app/server.py test_operator_routes.py
git commit -m "API: POST /api/seek-home/cancel for the operator page

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Cabinet tabs on the Control page

**Files:**
- Modify: `static/index.html` — CSS block near the `.cab-strip` rules (around line 268), markup around line 447-450 (`.map-wrap` / `#cab-strip`), JS: `onStatus` (~line 549), `loadMotors` (~line 618), `updateMap` (~line 653), the cabinet strip block (`renderCabinetStrip` … `toggleCabinetHighlight`, ~lines 669-689), `selectMotor` (~line 721), and the init section at the bottom.
- Create: `test_cabinet_box.py`

**Interfaces:**
- Consumes: `mapInv` from `GET /api/motors` (`cabinets[]` with `cabinet`, `active_host`, `motor_keys[]`; `motors[]` with `motor_key`, `label`, `motor`, `cabinet`, `slave_id`, `x`, `y`), status frames `d.motors[key]` with `offline`, `alarm`, `running`, `enabled`, `position_deg`, `current_face`; existing `lastData`, `selectedKey`, `selectMotor`, `updateMap`, `V`, `$$`.
- Produces: JS `cabinetBox(inv, n) -> {x, y, w, h} | null`, `renderCabinetTabs()`, `updateCabinetTabs(d)`, `selectTab(t)`, `applyTab()`, `renderCabinetTable()`, `updateCabinetTable(d)`, `activeTab` (`'wall'` or number).

- [ ] **Step 1: Write the failing bounding-box test**

Create `test_cabinet_box.py`:

```python
"""Cabinet bounding boxes — Python twin of cabinetBox() in static/index.html.
Run: ./venv/bin/python test_cabinet_box.py"""
import json

WALL = (250, 600, 2850, 1120)      # viewBox of #wall-map in static/index.html


def cabinet_box(motors, n):
    pts = [(m["x"], m["y"]) for m in motors if m["cabinet"] == n]
    if not pts:
        return None
    x = min(p[0] for p in pts)
    y = min(p[1] for p in pts)
    return (x, y, max(p[0] for p in pts) - x, max(p[1] for p in pts) - y)


motors = json.load(open("motor_map.json"))["motors"]
cabs = sorted({m["cabinet"] for m in motors})
assert cabs == list(range(1, 12)), cabs
for n in cabs:
    x, y, w, h = cabinet_box(motors, n)
    assert w > 0 or h > 0, (n, w, h)          # Cab 11 is a straight run: h == 0 is fine
    for m in motors:
        if m["cabinet"] == n:
            assert x <= m["x"] <= x + w and y <= m["y"] <= y + h, (n, m["motor"])
    assert WALL[0] <= x and x + w <= WALL[0] + WALL[2], (n, x, w)
    assert WALL[1] <= y and y + h <= WALL[1] + WALL[3], (n, y, h)
assert cabinet_box(motors, 99) is None
# The JS must use the same source: the rule text lives in index.html.
html = open("static/index.html").read()
assert "function cabinetBox(inv, n)" in html
assert "trivision.tab" in html
print("ok")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./venv/bin/python test_cabinet_box.py`
Expected: `AssertionError` on the `function cabinetBox(inv, n)` line (the geometry asserts pass; the HTML ones fail).

- [ ] **Step 3: Replace the cabinet-strip CSS**

In `static/index.html`, replace these five rules:

```css
  .cab-strip { display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }
  .cab-btn { font-size:.72rem; padding:4px 8px; border-radius:6px; border:1px solid var(--border); background:var(--surface); cursor:pointer; }
  .cab-btn.active { outline:2px solid #fff; }
  .cab-btn.offline { color:#888; }
  .cab-btn.alarm { border-color:#ef4444; color:#ef4444; }
```

with:

```css
  .cab-tabs { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:8px; }
  .cab-btn { font-size:.72rem; padding:4px 8px; border-radius:6px; border:1px solid var(--border); background:var(--surface); cursor:pointer; }
  .cab-btn.active { outline:2px solid #fff; }
  .cab-btn.warn { border-color:#fbbf24; color:#fbbf24; }
  .cab-btn.bad { border-color:#ef4444; color:#ef4444; }
  .cab-table { width:100%; border-collapse:collapse; font-size:.75rem; margin-top:8px; }
  .cab-table th, .cab-table td { padding:4px 8px; text-align:left; border-bottom:1px solid var(--border); }
  .cab-table th { color:var(--text-dim); font-weight:600; }
  .cab-table tbody tr { cursor:pointer; }
  .cab-table tbody tr:hover td { background:var(--surface2); }
  .cab-table tr.selected td { color:var(--accent); }
  .cab-table tr.offline td { color:var(--text-dimmer); }
  .cab-table tr.alarm td.alarm { color:#ef4444; }
```

And replace the rule `.prism.dim polygon { opacity:.25; }` with `.prism.off { display:none; }`.

- [ ] **Step 4: Replace the strip markup with the tab row and table**

Replace:

```html
      <div class="map-wrap">
        <svg id="wall-map" viewBox="250 600 2850 1120" preserveAspectRatio="xMidYMid meet"></svg>
      </div>
      <div class="cab-strip" id="cab-strip"></div>
```

with:

```html
      <div class="cab-tabs" id="cab-tabs"></div>
      <div class="map-wrap">
        <svg id="wall-map" viewBox="250 600 2850 1120" preserveAspectRatio="xMidYMid meet"></svg>
      </div>
      <table class="cab-table" id="cab-table" hidden></table>
```

- [ ] **Step 5: Replace the strip JS with the tab JS**

In `onStatus`, replace the line `updateCabinetStrip(data);` with:

```js
  updateCabinetTabs(data);
  updateCabinetTable(data);
```

In `loadMotors`, replace `renderCabinetStrip();` with `renderCabinetTabs();`.

Delete the line `let highlightCab = null;` and, in `updateMap`, delete the line
`g.classList.toggle('dim', highlightCab != null && String(highlightCab) !== g.dataset.cab);`.

Replace the whole block from the comment `// Buttons are built once per inventory load` through the end of `toggleCabinetHighlight` (functions `renderCabinetStrip`, `updateCabinetStrip`, `toggleCabinetHighlight`) with:

```js
// ============================ Cabinet tabs ============================
// Whole wall + one tab per cabinet. Buttons are built once per inventory load;
// per-tick updates only patch text + classes. The active tab survives reloads.
const WALL_VIEWBOX = '250 600 2850 1120';
const CAB_PAD = 60;                       // SVG units around a cabinet's motors
let activeTab = 'wall';                   // 'wall' or a cabinet number

function loadTab() {
  const v = localStorage.getItem('trivision.tab');
  activeTab = (v && v !== 'wall' && Number.isInteger(+v)) ? +v : 'wall';
}

// Pure: bounding box of one cabinet's motors, or null. Twin of test_cabinet_box.py.
function cabinetBox(inv, n) {
  const pts = inv.filter(m => m.cabinet === n && m.x != null);
  if (!pts.length) return null;
  const xs = pts.map(m => m.x), ys = pts.map(m => m.y);
  const x = Math.min(...xs), y = Math.min(...ys);
  return { x, y, w: Math.max(...xs) - x, h: Math.max(...ys) - y };
}

function renderCabinetTabs() {
  if (!mapInv) return;
  const tabs = [`<button type="button" class="cab-btn" id="cab-btn-wall" onclick="selectTab('wall')">Whole wall</button>`]
    .concat(mapInv.cabinets.map(c =>
      `<button type="button" class="cab-btn" id="cab-btn-${c.cabinet}" onclick="selectTab(${c.cabinet})" title="${c.active_host}">Cab ${c.cabinet}</button>`));
  V('cab-tabs').innerHTML = tabs.join('');
  applyTab();
}

function updateCabinetTabs(d) {
  if (!mapInv) return;
  const motors = d.motors || {};
  const wall = V('cab-btn-wall');
  if (wall) wall.className = 'cab-btn' + (activeTab === 'wall' ? ' active' : '');
  mapInv.cabinets.forEach(c => {
    const btn = V(`cab-btn-${c.cabinet}`);
    if (!btn) return;
    const sts = c.motor_keys.map(k => motors[k] || { offline: true });
    const online = sts.filter(s => !s.offline).length;
    const bad = online < sts.length || sts.some(s => !s.offline && s.alarm);
    const warn = sts.some(s => !s.offline && s.running);
    btn.textContent = `Cab ${c.cabinet} · ${online}/${sts.length}`;
    btn.className = ['cab-btn', bad ? 'bad' : (warn ? 'warn' : ''), activeTab === c.cabinet ? 'active' : ''].join(' ');
  });
}

function selectTab(t) {
  activeTab = t;
  localStorage.setItem('trivision.tab', String(t));
  applyTab();
}

function applyTab() {
  const svg = V('wall-map');
  const inv = (mapInv && mapInv.motors) || [];
  if (activeTab === 'wall') {
    svg.setAttribute('viewBox', WALL_VIEWBOX);
  } else {
    const b = cabinetBox(inv, activeTab);
    if (!b) { selectTab('wall'); return; }     // stale localStorage after a map change
    svg.setAttribute('viewBox', `${b.x - CAB_PAD} ${b.y - CAB_PAD} ${b.w + 2 * CAB_PAD} ${b.h + 2 * CAB_PAD}`);
  }
  for (const g of $$('.prism')) g.classList.toggle('off', activeTab !== 'wall' && String(activeTab) !== g.dataset.cab);
  renderCabinetTable();
  if (lastData) { updateMap(lastData); updateCabinetTabs(lastData); }
}

function renderCabinetTable() {
  const tbl = V('cab-table');
  if (activeTab === 'wall' || !mapInv) { tbl.hidden = true; tbl.innerHTML = ''; return; }
  const rows = mapInv.motors.filter(m => m.cabinet === activeTab).sort((a, b) => a.motor - b.motor);
  tbl.innerHTML = '<thead><tr><th>Motor</th><th>ID</th><th>Position °</th><th>Face</th><th>Status</th><th>Alarm</th></tr></thead><tbody>' +
    rows.map(m => `<tr data-key="${m.motor_key}" onclick="selectMotor('${m.motor_key}')"><td>${m.label}</td><td>${m.slave_id}</td><td class="pos">—</td><td class="face">—</td><td class="st">—</td><td class="alarm">—</td></tr>`).join('') +
    '</tbody>';
  tbl.hidden = false;
  if (lastData) updateCabinetTable(lastData);
}

function updateCabinetTable(d) {
  const tbl = V('cab-table');
  if (tbl.hidden) return;
  const motors = d.motors || {};
  for (const tr of tbl.querySelectorAll('tbody tr')) {
    const st = motors[tr.dataset.key] || { offline: true };
    tr.classList.toggle('offline', !!st.offline);
    tr.classList.toggle('alarm', !st.offline && !!st.alarm);
    tr.classList.toggle('selected', tr.dataset.key === selectedKey);
    tr.querySelector('.pos').textContent = st.offline ? '—' : (st.position_deg ?? 0).toFixed(1);
    tr.querySelector('.face').textContent = st.offline ? '—' : (st.current_face ?? '?');
    tr.querySelector('.st').textContent = st.offline ? 'offline' : (st.running ? 'moving' : (st.enabled ? 'enabled' : 'idle'));
    tr.querySelector('.alarm').textContent = st.alarm ? `0x${st.alarm.toString(16).toUpperCase()}` : '—';
  }
}
```

In `selectMotor`, after the line `renderFocus(lastData);` add:

```js
  updateCabinetTable(lastData);
```

In the `// ============================ Init ============================` section, before `loadShowEffects();`, add:

```js
loadTab();
```

- [ ] **Step 6: Run the test**

Run: `./venv/bin/python test_cabinet_box.py`
Expected: `ok`

- [ ] **Step 7: Check in the browser (simulation mode)**

Start the server: `./venv/bin/python run.py` (background). Confirm `config.json` has `"mode": "simulation"`; if not, open the page and pick SIM in the header badge. Open `http://127.0.0.1:8000/` and verify:

1. A tab row `Whole wall`, `Cab 1 · 21/21` … `Cab 11 · 24/24` sits above the map; no cabinet strip below it.
2. Click `Cab 7`: the map zooms to 11 prisms, everything else hidden; a table with 11 rows appears below the map; the tab is outlined white.
3. Click a table row: the prism highlights and the focus panel shows that motor.
4. Press `Next face ▶`: the tabs turn amber while motors move, table Face column changes 1 → 2, then tabs go plain.
5. Reload the page: it reopens on `Cab 7`. Click `Whole wall`: the full map returns, table hides.
6. Open DevTools console: no errors.

Stop the server afterwards.

- [ ] **Step 8: Commit**

```bash
git add static/index.html test_cabinet_box.py
git commit -m "UI: Control page gets Whole wall + per-cabinet tabs with a motor table

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Operator tablet page, `/operator` route, README

**Files:**
- Create: `static/operator.html`
- Modify: `app/server.py` (after the `index` route, ~line 472)
- Modify: `test_operator_routes.py` (from Task 1)
- Modify: `README.md`

**Interfaces:**
- Consumes: `POST /api/seek-home/cancel` from Task 1 (`{"ok", "cancelled"}`); existing routes `/api/estop` → `{ok}`, `/api/enable` → `{ok,total,done,failed[]}`, `/api/seek-home` body `{}` → `{ok,total}` or `{error}`, `/api/show/prev|next` body `{}` → show state or `{rejected, error}`, `/api/show/auto/start` body `{hold_s, direction}`, `/api/show/auto/stop` body `{}`, `/api/alarm-reset` body `{}` → `{ok,total,done,failed[]}`, `/api/reconnect` → `{ok}`; WebSocket `/ws` frames with `motors`, `inventory`, `show{current_page,busy,auto{running}}`, `homing{active,total,done,failed[]}`.
- Produces: `GET /operator` serving `static/operator.html`.

- [ ] **Step 1: Extend the route test (failing)**

In `test_operator_routes.py`, add `import os` under the existing imports, and as the first lines inside the `try:` block insert:

```python
        page = (await S.operator()).path
        assert str(page).endswith("operator.html") and os.path.exists(page), page
```

Run: `./venv/bin/python test_operator_routes.py`
Expected: `AttributeError: module 'app.server' has no attribute 'operator'`

- [ ] **Step 2: Add the route**

In `app/server.py`, directly after the `index` route:

```python
@app.get("/operator")
async def operator():
    """Tablet page: a few big buttons, no per-motor controls."""
    return FileResponse(STATIC_DIR / "operator.html")
```

- [ ] **Step 3: Create the page**

Create `static/operator.html` with exactly this content:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#0f1117">
<title>Trivision Operator</title>
<style>
  :root { --bg:#0f1117; --surface:#1a1d27; --surface2:#242836; --border:#2e3348; --text:#e2e4ed; --dim:#8b8fa3; --accent:#5b8def; --ok:#22c55e; --warn:#f59e0b; --bad:#ef4444; }
  * { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  [hidden] { display:none !important; }
  html, body { margin:0; min-height:100%; background:var(--bg); color:var(--text);
    font-family:-apple-system, system-ui, Roboto, sans-serif; font-size:20px;
    user-select:none; -webkit-user-select:none; touch-action:manipulation; }
  .page { max-width:720px; margin:0 auto; padding:12px; display:flex; flex-direction:column; gap:12px; }
  .bar { display:flex; align-items:center; gap:12px; padding:10px 14px; background:var(--surface);
    border:1px solid var(--border); border-radius:12px; font-size:18px; }
  .bar .dot { width:14px; height:14px; border-radius:50%; background:var(--bad); flex:none; }
  .bar .dot.ok { background:var(--ok); }
  .bar .spacer { flex:1; }
  body.dead .bar { border-color:var(--bad); }
  body.dead button { opacity:.35; pointer-events:none; }
  button { font:inherit; color:var(--text); background:var(--surface2); border:1px solid var(--border);
    border-radius:14px; min-height:64px; padding:0 16px; font-weight:600; }
  button:disabled { opacity:.45; }
  button:active:not(:disabled) { filter:brightness(1.25); }
  .row { display:flex; gap:12px; }
  .row > * { flex:1; }
  .estop { position:relative; overflow:hidden; min-height:110px; font-size:28px; letter-spacing:.06em;
    background:var(--bad); border-color:#b91c1c; color:#fff; touch-action:none; }
  .estop .fill { position:absolute; left:0; top:0; bottom:0; width:0; background:rgba(255,255,255,.35); pointer-events:none; }
  .estop.holding .fill { width:100%; transition:width 1s linear; }
  .estop .label { position:relative; }
  .estop.stopped { background:#3a3d4a; border-color:var(--border); color:var(--dim); }
  .primary { background:var(--accent); border-color:var(--accent); color:#fff; }
  .ok { background:#166534; border-color:#166534; color:#fff; }
  .face { text-align:center; font-size:44px; font-weight:700; line-height:1; align-self:center; }
  .face small { display:block; font-size:14px; color:var(--dim); font-weight:400; margin-bottom:4px; }
  .card { background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:12px;
    display:flex; flex-direction:column; gap:12px; }
  .card h2 { margin:0; font-size:13px; text-transform:uppercase; letter-spacing:.08em; color:var(--dim); font-weight:600; }
  .progress { min-height:64px; border-radius:14px; background:var(--surface2); border:1px solid var(--border);
    position:relative; overflow:hidden; display:flex; align-items:center; justify-content:center; font-weight:600; }
  .progress .fill { position:absolute; left:0; top:0; bottom:0; width:0; background:var(--accent); opacity:.5; }
  .progress span { position:relative; }
  .progress .failed { color:var(--warn); margin-left:8px; }
  .small button { min-height:52px; font-size:17px; font-weight:500; }
  .cabs { display:grid; grid-template-columns:repeat(auto-fill, minmax(150px, 1fr)); gap:8px; font-size:16px; }
  .cab { display:flex; align-items:center; gap:8px; padding:8px 10px; background:var(--surface2); border-radius:10px; }
  .cab .dot { width:12px; height:12px; border-radius:50%; background:var(--bad); flex:none; }
  .cab .dot.ok { background:var(--ok); }
  .cab .dot.warn { background:var(--warn); }
  .cab .n { color:var(--dim); margin-left:auto; }
  .toast { position:fixed; left:50%; bottom:24px; transform:translateX(-50%); background:#fff; color:#111;
    padding:12px 20px; border-radius:12px; font-weight:600; display:none; max-width:90vw; text-align:center; z-index:9; }
  .toast.error { background:var(--bad); color:#fff; }
</style>
</head>
<body>
<div class="page">

  <div class="bar">
    <span class="dot" id="ws-dot"></span><span id="ws-label">Connecting…</span>
    <span class="spacer"></span>
    <span id="online">–/–</span>
    <span id="bar-face">Face –</span>
    <span id="bar-homing" hidden></span>
  </div>

  <div class="row">
    <button type="button" class="estop" id="btn-estop"><span class="fill"></span><span class="label">HOLD TO E-STOP</span></button>
    <button type="button" class="ok" id="btn-enable" hidden onclick="enableAll(this)">Enable all</button>
  </div>

  <div class="card">
    <h2>Show</h2>
    <div class="row">
      <button type="button" id="btn-prev" onclick="act(this, 'show/prev', {}, () => null)">◀ Prev</button>
      <div class="face"><small>face</small><span id="face">–</span></div>
      <button type="button" id="btn-next" class="primary" onclick="act(this, 'show/next', {}, () => null)">Next ▶</button>
    </div>
    <button type="button" id="btn-auto" onclick="toggleAuto(this)">Start auto</button>
  </div>

  <div class="card">
    <h2>Homing</h2>
    <button type="button" id="btn-home" onclick="act(this, 'seek-home', {}, r => `Homing ${r.total} motors`)">Home the wall</button>
    <div class="row" id="home-progress" hidden>
      <div class="progress"><div class="fill" id="home-fill"></div><span id="home-text">0/0</span></div>
      <button type="button" id="btn-cancel" onclick="act(this, 'seek-home/cancel', {}, () => 'Homing cancelled')">Cancel</button>
    </div>
  </div>

  <div class="row small">
    <button type="button" onclick="act(this, 'alarm-reset', {}, r => bulk('Alarm reset on', r))">Alarm reset</button>
    <button type="button" onclick="act(this, 'reconnect', {}, () => 'Reconnected')">Reconnect</button>
  </div>

  <div class="card">
    <h2>Cabinets</h2>
    <div class="cabs" id="cabs"></div>
  </div>

</div>
<div class="toast" id="toast"></div>

<script>
const V = id => document.getElementById(id);
let autoRunning = false;

function toast(msg, err) {
  const t = V('toast');
  t.textContent = msg;
  t.className = 'toast' + (err ? ' error' : '');
  t.style.display = 'block';
  clearTimeout(t._t);
  t._t = setTimeout(() => { t.style.display = 'none'; }, 2000);
}

function bulk(prefix, r) {
  const k = (r.failed || []).length;
  return `${prefix} ${r.done} motors` + (k ? `, ${k} failed` : '');
}

async function post(path, body) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 5000);
  try {
    const res = await fetch(`/api/${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                             body: JSON.stringify(body), signal: ctl.signal });
    return await res.json();
  } catch {
    return { error: 'No reply from controller' };
  } finally {
    clearTimeout(timer);
  }
}

// One request per button at a time: grey it out, map the reply to a toast, never show raw JSON.
async function act(btn, path, body, okText) {
  if (btn.disabled) return null;
  btn.disabled = true;
  try {
    const r = await post(path, body);
    const err = r.error || r.detail;
    if (err) toast(String(err), true);
    else { const t = okText(r); if (t) toast(t); }
    return r;
  } finally {
    btn.disabled = false;
  }
}

// ---- E-STOP: press and hold 1 s. A tap does nothing. ----
const estop = V('btn-estop');
let holdTimer = null;
function holdStart(e) {
  if (estop.disabled || estop.classList.contains('stopped')) return;
  e.preventDefault();
  estop.classList.add('holding');
  holdTimer = setTimeout(fireEstop, 1000);
}
function holdEnd() {
  clearTimeout(holdTimer);
  holdTimer = null;
  estop.classList.remove('holding');
}
async function fireEstop() {
  holdEnd();
  const r = await act(estop, 'estop', {}, () => 'Stopped all motors');
  if (r && !r.error) {
    estop.classList.add('stopped');
    estop.querySelector('.label').textContent = 'STOPPED';
    V('btn-enable').hidden = false;
  }
}
estop.addEventListener('pointerdown', holdStart);
for (const ev of ['pointerup', 'pointercancel', 'pointerleave']) estop.addEventListener(ev, holdEnd);
estop.addEventListener('contextmenu', e => e.preventDefault());

// iCL-RS estop is a one-shot quick-stop with no latch, so "release" is just Enable all.
async function enableAll(btn) {
  const r = await act(btn, 'enable', {}, r => bulk('Enabled', r));
  if (r && !r.error) {
    estop.classList.remove('stopped');
    estop.querySelector('.label').textContent = 'HOLD TO E-STOP';
    btn.hidden = true;
  }
}

async function toggleAuto(btn) {
  if (autoRunning) await act(btn, 'show/auto/stop', {}, () => 'Auto stopped');
  else await act(btn, 'show/auto/start', { hold_s: 5, direction: 1 }, () => 'Auto started');
}

// ---- Live status ----
let ws = null, lastMsg = 0;
function setAlive(ok) {
  document.body.classList.toggle('dead', !ok);
  V('ws-dot').className = 'dot' + (ok ? ' ok' : '');
  V('ws-label').textContent = ok ? 'Connected' : 'Disconnected';
}
function connect() {
  ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
  ws.onopen = () => { lastMsg = Date.now(); setAlive(true); };
  ws.onclose = () => { setAlive(false); setTimeout(connect, 2000); };
  ws.onmessage = e => { lastMsg = Date.now(); setAlive(true); try { onStatus(JSON.parse(e.data)); } catch {} };
}
// Frames arrive 4-10x per second. 2 s of silence = show red and lock the buttons;
// 6 s = the socket is half-open (tablet slept), close it so onclose reconnects.
setInterval(() => {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const quiet = Date.now() - lastMsg;
  if (quiet > 2000) setAlive(false);
  if (quiet > 6000) { try { ws.close(); } catch {} }
}, 1000);
connect();

function onStatus(d) {
  const inv = d.inventory || [], motors = d.motors || {};
  const sts = inv.map(m => motors[m.motor_key] || { offline: true });
  V('online').textContent = `${sts.filter(s => !s.offline).length}/${inv.length}`;

  const show = d.show || {};
  const page = show.current_page || '–';
  V('face').textContent = page;
  V('bar-face').textContent = `Face ${page}`;
  autoRunning = !!(show.auto && show.auto.running);
  V('btn-auto').textContent = autoRunning ? 'Stop auto' : 'Start auto';
  V('btn-auto').className = autoRunning ? 'ok' : '';
  V('btn-prev').disabled = V('btn-next').disabled = !!show.busy;

  const h = d.homing || {};
  V('btn-home').hidden = !!h.active;
  V('home-progress').hidden = !h.active;
  V('bar-homing').hidden = !h.active;
  if (h.active) {
    const failed = (h.failed || []).length;
    V('home-fill').style.width = (h.total ? Math.round(100 * h.done / h.total) : 0) + '%';
    V('home-text').innerHTML = `${h.done}/${h.total}` + (failed ? `<span class="failed">${failed} failed</span>` : '');
    V('bar-homing').textContent = `Homing ${h.done}/${h.total}`;
  }
  renderCabs(inv, motors);
}

// Rows are built once (when the cabinet count changes); dots and counts patch every frame.
function renderCabs(inv, motors) {
  const byCab = new Map();
  for (const m of inv) {
    if (!byCab.has(m.cabinet)) byCab.set(m.cabinet, []);
    byCab.get(m.cabinet).push(m.motor_key);
  }
  const nums = [...byCab.keys()].sort((a, b) => a - b);
  const el = V('cabs');
  if (el.childElementCount !== nums.length) {
    el.innerHTML = nums.map(n => `<div class="cab" id="cab-${n}"><span class="dot"></span>Cab ${n}<span class="n"></span></div>`).join('');
  }
  for (const n of nums) {
    const sts = byCab.get(n).map(k => motors[k] || { offline: true });
    const online = sts.filter(s => !s.offline).length;
    const alarm = sts.filter(s => !s.offline && s.alarm).length;
    const moving = sts.some(s => !s.offline && s.running);
    const row = V(`cab-${n}`);
    row.querySelector('.dot').className = 'dot' + ((online < sts.length || alarm) ? '' : (moving ? ' warn' : ' ok'));
    row.querySelector('.n').textContent = `${online}/${sts.length}` + (alarm ? ` · ${alarm} alarm` : '');
  }
}
</script>
</body>
</html>
```

- [ ] **Step 4: Run the route test**

Run: `./venv/bin/python test_operator_routes.py`
Expected: `ok`

- [ ] **Step 5: Check the page on a 7-inch viewport (simulation mode)**

Start `./venv/bin/python run.py` in the background (simulation mode as in Task 2). Open `http://127.0.0.1:8000/operator` in a browser window sized to 600×1024 (DevTools device toolbar, responsive, 600 × 1024). Verify:

1. No vertical scrollbar; status bar shows a green dot, `231/231`, `Face 1`.
2. Tap `HOLD TO E-STOP` briefly: nothing happens. Hold 1 s: a white fill sweeps across, toast `Stopped all motors`, button becomes grey `STOPPED`, `Enable all` appears. Press `Enable all`: toast `Enabled 231 motors`, red button returns.
3. `Next ▶`: face becomes 2 within ~3 s; `◀ Prev` and `Next ▶` are greyed while motors move; cabinet dots turn amber while moving, then green.
4. `Start auto` turns into `Stop auto` and the face advances every few seconds; `Stop auto` stops it.
5. `Home the wall`: toast `Homing 231 motors`; the button is replaced by a progress bar with `n/231` counting up and a `Cancel` button; `Cancel` returns the button and the status bar text `Homing …` disappears.
6. `Alarm reset`: toast `Alarm reset on 231 motors`. `Reconnect`: toast `Reconnected`.
7. Stop the server: within 2 s the bar goes red, `Disconnected`, every button greys. Restart the server: it reconnects by itself.
8. Rotate to 1024×600 (landscape): content stays centred at 720 px max width and remains usable.
9. DevTools console: no errors.

Stop the server afterwards.

- [ ] **Step 6: README**

In `README.md`, under `## The UI`, after the paragraph that starts with `**Cabinets tab**` and before `## Quick start`, add:

```markdown
### Operator page (tablet)

Open `http://<server-ip>:8000/operator` on the tablet and add it to the home screen
(iPad: Share → Add to Home Screen; Android Chrome: menu → Add to Home screen) so it
runs full-screen. It has only wall-wide controls: hold-to-fire E-STOP with Enable all,
Prev / Next face, auto-cycle, Home the wall with Cancel, Alarm reset, Reconnect, and a
per-cabinet health list. Anyone on the network with the URL can use it.

The desktop Control page now opens on a tab row: **Whole wall** plus **Cab 1 … Cab 11**.
A cabinet tab zooms the map to that cabinet and lists its motors; the last tab used is
remembered per browser.
```

In the `## Project layout` code block, directly after the `static/index.html` line, add:

```
static/operator.html    Tablet page (/operator): E-STOP, homing, show, cabinet health
test_*.py               Plain assert scripts: ./venv/bin/python test_<name>.py
```

- [ ] **Step 7: Commit**

```bash
git add static/operator.html app/server.py test_operator_routes.py README.md
git commit -m "Operator tablet page at /operator: E-STOP, homing, show, alarms, cabinet health

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```
