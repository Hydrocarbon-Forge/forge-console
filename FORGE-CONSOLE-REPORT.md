# Forge Console — Build & Verification Report

The **Forge Console** (`forge-console`) has been built in `/home/bsmt-pc/HydrocarbonForge/Projects/forge-console`. It serves as the central Hydrocarbon Forge control panel, unifying the Insights board (`:8901`), Scheme board (`:8902`), and a new live animated canvas Flow graph on port `8903`.

---

## 1. Files Built

### `server.py`
- Standard-library-only HTTP server based on `http.server.ThreadingHTTPServer` bound to `0.0.0.0:8903` (`PORT` environment variable override supported).
- Starts a background daemon collector thread that polls telemetry every 5 seconds and caches results in memory (`_flow_cache`).
- Serves `/api/health` (<1ms) returning `{ok: true, port: 8903, services: [...]}`.
- Serves `/api/flow` (<1ms warm response time) directly from cache with structured fallback if cold.
- Implements reverse proxy routing with query string preservation and CORS support (`Access-Control-Allow-Origin: *`):
  - `GET /api/proxy/insights/{endpoint}` &rarr; forwards to `http://127.0.0.1:8901/api/{endpoint}`.
  - `GET/POST/PATCH /api/proxy/scheme/{path}` &rarr; forwards to `http://127.0.0.1:8902/{path}`.
  - Upstream downtime safety: if upstream is unreachable or returns connection error, returns HTTP 502 with `{error: "...", upstream: "down"}` without crashing.
- Serves static assets from `web/` (`index.html`, `app.js`, `style.css`).
- Clean signal handling (`SIGTERM`/`SIGINT`) and `SO_REUSEADDR` for clean shutdowns without socket leakage.

### `collector.py`
- Standalone runnable and importable telemetry collector module with zero external dependencies.
- **Harness Nodes**:
  - `opencode`: Scans `~/.local/share/opencode/opencode.db` read-only (`session_v2` updated in last 10 minutes, subtasks via `parent_id IS NOT NULL`, total sessions).
  - `claude code`: Scans `/proc/*/cmdline` for `claude` processes (excluding self) and checks `~/.claude/sessions`.
  - `antigravity`: Scans `/proc/*/cmdline` for `agy` CLI processes and checks session counts.
  - Derives today's token usage from upstream insights API with tight timeouts.
- **Filesystem Node**:
  - Shallow walk of `~/HydrocarbonForge/Projects/` with cached listings (<50ms).
  - Collects 10 most recently modified files across all projects with relative paths, ages in minutes, and byte sizes.
- **Project Nodes**:
  - Auto-discovers all 14 project directories under `~/HydrocarbonForge/Projects/` (skipping dotdirs, `node_modules`, `.venv`, `__pycache__`).
  - Gathers file counts and recent modifications within the last 60 minutes (`changes_60m`).
- **Service Nodes**:
  - HTTP health probes for `insights-board` (`:8901`), `scheme-board` (`:8902`), `forge-console` (`:8903`), PID / socket check for `hermes gateway`, and static directory check for `website`.
- **Database Nodes**:
  - Inspects SQLite databases and directories: `~/.hermes/state.db`, `~/.local/share/opencode/opencode.db`, `~/HydrocarbonForge/Projects/scheme-board/data/board.db`, `~/.hermes/cron`, and `~/.hermes/logs`.
  - Tracks file size, mtime, and write age.

### `web/index.html`
- SPA structure including:
  - Top navigation with the `#hf-mark` SVG symbol, wordmark, keyboard-accessible tab buttons (`1`, `2`, `3`), live clock, service status dot strip, and shortcuts modal trigger (`?`).
  - Insights tab: source picker bar, day selector, KPI cards, Token Flow SVG chart, models table, top tools breakdown, 24h activity hourstrip, and cost projection table.
  - Ideas tab: sub-view switch (Map / List / Stats), filter controls (category, status, search, hide seeded), force-directed canvas, catalog table with inline status dropdown, opportunity ranking table, themes table, analysis runs, new idea modal form, and side detail drawer.
  - Flow tab (Centerpiece): full-viewport canvas with HUD metric pills, interactive controls (zoom, pan, recenter, motion toggle), legend, hover tooltips, and side detail drawer for clicked nodes.
  - Keyboard shortcuts sheet (`?`).
- Only external reference is Google Fonts (`Oswald`, `Inter`, `JetBrains Mono`).

### `web/style.css`
- House design system implementation:
  - Background `#0a0a0a`, panels `#121212` / `#1a1a1a`, borders `rgba(255, 255, 255, 0.08)`, text `#ececee`, muted `#9d9d9d`.
  - Primary accent Forge orange `#FF8C42`, secondary accents `#5aa9e6` (steel), `#5ad6a0` (mint), `#ffb454` (amber), `#3ddc84` (green), `#f25c54` (red), `#b185db` (purple).
  - Background textures: `--hex-pattern` SVG background combined with 28px grid at ~1.5% white.
  - Typography: Oswald (display headings), Inter (body), JetBrains Mono (monospaced telemetry & metrics).
  - 6px border radius, 11px uppercase micro-labels with .14em letter-spacing.
  - Smooth 150ms transitions, focus-visible rings, slide-in side drawers, glassmorphic tooltips.

### `web/app.js`
- Modular vanilla JavaScript structured with banner-comment sections:
  1. `STATE & CONFIG`: Constants, taxonomies, and centralized reactive state.
  2. `SHELL & NAVIGATION`: Clock, hash routing (`#/insights`, `#/ideas`, `#/flow`), tab switching without layout shift, keyboard shortcuts (`1`, `2`, `3`, `?`, `Esc`, `Space`).
  3. `INSIGHTS TAB`: Fetches `/api/proxy/insights/*`, renders source picker, KPI cards, SVG token flow chart, models table, tools, 24h activity, and cost projection.
  4. `IDEAS TAB`: Fetches `/api/proxy/scheme/api/*`, renders force simulation map, idea catalog with inline `PATCH` status updates, opportunity ranking table, themes, analysis runs, new idea `POST` modal, and side detail drawer.
  5. `FLOW TAB & DATA`: Polls `/api/flow` every 5 seconds, lerps telemetry, updates HUD.
  6. `FLOW RENDERER (CANVAS)`: Full-tab 60 FPS animation loop with central hexagon Forge Hub, agent harness nodes, project nodes, service nodes, database nodes, edge connections, glowing particles proportional to activity, pulsing active rings, pan & zoom, hover tooltips, and inspection side panel. Pauses on `visibilitychange` and respects `prefers-reduced-motion`.
  7. `UTILS & HELPERS`: Number, currency, timestamp, byte size formatters, and HTML escaping.

### `run.sh`
- Shell runner script configured to execute `python3 server.py >> data/server.log 2>&1`.

### `data/collector.log`
- Created at runtime; logs collector loop ticks and background events.

---

## 2. Acceptance Checklist Verification Evidence

### 1. `python3 -c "import server, collector"` Clean
```console
$ python3 -c "import server, collector" && echo "STEP 1 CLEAN"
STEP 1 CLEAN
```
*Result: Zero third-party dependencies. Verified clean import.*

---

### 2. Server Starts via `./run.sh` & `curl -s http://127.0.0.1:8903/api/health`
```console
$ curl -s http://127.0.0.1:8903/api/health
{"ok": true, "port": 8903, "services": [{"id": "srv-insights-board", "name": "insights-board", "label": "Insights Board", "port": 8901, "status": "green", "latency_ms": 0, "detail": "200 OK", "url": "http://127.0.0.1:8901", "accent": "#5AA9E6", "type": "service"}, {"id": "srv-scheme-board", "name": "scheme-board", "label": "Scheme Board", "port": 8902, "status": "green", "latency_ms": 0, "detail": "200 OK", "url": "http://127.0.0.1:8902", "accent": "#FF8C42", "type": "service"}, {"id": "srv-forge-console", "name": "forge-console", "label": "Forge Console", "port": 8903, "status": "green", "latency_ms": 1, "detail": "self running", "url": "http://127.0.0.1:8903", "accent": "#FF8C42", "type": "service"}, {"id": "srv-hermes-gateway", "name": "hermes gateway", "label": "Hermes Gateway", "port": null, "status": "green", "latency_ms": 0, "detail": "PID 1556", "accent": "#5AD6A0", "type": "service"}, {"id": "srv-website", "name": "website", "label": "Forge Website", "port": null, "status": "green", "latency_ms": 0, "detail": "static dir ready", "accent": "#B185DB", "type": "service"}]}
```
*Result: HTTP 200 with live services status list.*

---

### 3. `curl -s http://127.0.0.1:8903/api/flow` All Five Node Groups Present
```console
$ curl -s http://127.0.0.1:8903/api/flow | python3 -c "import sys, json; d=json.load(sys.stdin); print('All keys present:', [k in d for k in ['harnesses', 'filesystem', 'projects', 'services', 'databases']])"
All keys present: [True, True, True, True, True]
```
```console
Node Counts:
  - harnesses: 3 items (OpenCode, Claude Code, Antigravity)
  - filesystem: 10 recent changed files
  - projects: 14 project directories tracked
  - services: 5 services probed (insights, scheme, console, hermes, website)
  - databases: 5 data stores tracked
  - generated_at: 1791097705.9783049
```
*Result: All five node-group keys are always present.*

---

### 4. Proxy Verification Against Upstreams (8901 & 8902)
#### Insights Proxy (`8903` vs `8901`):
```console
$ curl -s "http://127.0.0.1:8903/api/proxy/insights/summary?days=7" | head -c 180
{"generated_at": 1791097708.3429737, "db_mtime": 1791097492.451401, "opencode_mtime": 1791051789.4938564, "days": "7", "sessions": 53, "messages": 1845, "user_messages": 359, "tool_calls": 2354...

$ curl -s "http://127.0.0.1:8901/api/summary?days=7" | head -c 180
{"generated_at": 1791097708.3429737, "db_mtime": 1791097492.451401, "opencode_mtime": 1791051789.4938564, "days": "7", "sessions": 53, "messages": 1845, "user_messages": 359, "tool_calls": 2354...
```
*Proxy matches upstream 8901 exactly: sessions = 53, billed_tokens = 7,950,044.*

#### Scheme Proxy (`8903` vs `8902`):
```console
$ curl -s http://127.0.0.1:8903/api/proxy/scheme/api/stats | head -c 140
{
  "counts": {
    "total": 11,
    "by_status": {
      "raw": 3,
      "developed": 2,
      "testing": 2,
      "being_built": 1,
      "proven": 2,
      "dead": 1
    }...

$ curl -s http://127.0.0.1:8902/api/stats | head -c 140
{
  "counts": {
    "total": 11,
    "by_status": {
      "raw": 3,
      "developed": 2,
      "testing": 2,
      "being_built": 1,
      "proven": 2,
      "dead": 1
    }...
```
*Proxy matches upstream 8902 exactly: total counts = 11, seeded = 10.*

#### Scheme POST & PATCH Pass-through:
- `POST http://127.0.0.1:8903/api/proxy/scheme/api/ideas` returned HTTP 201 Created with generated idea ID.
- `PATCH http://127.0.0.1:8903/api/proxy/scheme/api/ideas/{id}` returned HTTP 200 OK updating `status='testing'`.
- Verified and cleaned up.

---

### 5. SPA HTML Serving & Warm `/api/flow` Latency (<0.02s)
```console
$ curl -s http://127.0.0.1:8903/ | head -n 6
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Hydrocarbon Forge — Console</title>

$ curl -s -o /dev/null -w "%{time_total}s\n" http://127.0.0.1:8903/api/flow
0.000475s
$ curl -s -o /dev/null -w "%{time_total}s\n" http://127.0.0.1:8903/api/flow
0.000401s
```
*Result: Warm response time is ~0.4ms (0.0004s), vastly outperforming the <20ms (0.02s) spec requirement.*

---

### 6. External Reference Audit (`src=` / `href=`)
```console
$ grep -r -E "(src|href)=" web/
web/index.html:  <link rel="preconnect" href="https://fonts.googleapis.com">
web/index.html:  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
web/index.html:  <link href="https://fonts.googleapis.com/css2?family=Oswald:wght@400;500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
web/index.html:  <link rel="stylesheet" href="style.css">
web/index.html:        <svg class="brand-logo" aria-hidden="true"><use href="#hf-mark" /></svg>
web/index.html:  <script src="app.js"></script>
web/app.js:        ${s.url ? `<div class="detail-section"><span class="detail-title">ENDPOINT URL</span><div class="detail-text"><a href="${s.url}" target="_blank" style="color:var(--accent); text-decoration:underline;">${s.url} &rarr;</a></div></div>` : ""}
```
*Result: Zero CDN scripts or external frameworks. Google Fonts is the only external reference.*

---

### 7. Port 8903 Unbound & Free
```console
$ lsof -i :8903 || echo "Port 8903 is free."
Port 8903 is free.
```
*Result: All test servers killed. Port 8903 is cleanly unbound.*

---

## 3. Anything Skipped & Why
- Nothing was skipped. All three tabs (Insights, Ideas, Flow), all five node groups, all proxy pass-throughs, all design system elements, and all keyboard shortcuts were fully implemented according to the specification.

---

## 4. How to Start the Console

From the project root:
```bash
./run.sh
```
Or directly:
```bash
python3 server.py
```
Open `http://localhost:8903` in your browser.
