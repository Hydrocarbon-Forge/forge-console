# Hydrocarbon Forge Console — HOME Dashboard & Icon Nav Implementation Report

**Date:** 2026-10-06  
**Target:** Hydrocarbon Forge Console (`forge-console`, port 8903)  
**Spec Document:** `TASK-HOME.md`  
**Design Study Artifact:** `DESIGN.md`  

---

## 1. Executive Summary

We have redesigned and modernized the Hydrocarbon Forge console's front door:
1. **Designed and Delivered the HOME Dashboard (Default Landing):** Replaced the Flow canvas as the default pane with an industrial, living command deck (**"The Living Foundry Floor / Master Control Bay"**). The dashboard features the signature background animated `#hf-ring` (90s slow spin) with breathing glow, along with five real-time live metric groups:
   - **Today's Tokens** (from `/api/summary?days=1`): prominently displays `total_tokens` with sub-labeled `billed_tokens` and smooth number tweening.
   - **All-Time Tokens** (from `/api/summary?days=3650`): humanized (e.g., `135.1M`) in JetBrains Mono.
   - **Currently Running Harnesses** (from `/api/flow`): live badge (`1 RUNNING`), active status pips, active session counts, and PID tags.
   - **Forge Workbench** (from `/api/flow`): projects modified in the last 60 minutes (`changes_60m`) with change frequency and relative time badges, falling back gracefully to recent projects when idle.
   - **Office Treasury** (from `/api/trading`): total equity (`$197.91`), Day P/L and Total P/L pills (color-coded green/red with signs), Stocks vs Crypto book breakdown, and total active positions. Clicking jumps straight into the Office tab.
   - **Facility Conduits (Launchpads):** Five large, tactile cards with custom 24px line icons, titles, one-line descriptors, and live at-a-glance chips (`INSIGHTS`, `IDEAS`, `FLOW`, `PROJECTS`, `OFFICE`).
2. **Icon-Based Six-Tab Navigation:** Replaced the previous 4 numbered tabs (`1`, `2`, `3`, `4`) with 6 line SVG icon tabs:
   - **Home** (Hexagon house mark with core pip) `[1]`
   - **Insights** (Sparkline pulse activity) `[2]`
   - **Ideas** (Hexagon thought/constellation) `[3]`
   - **Flow** (Connected network stream) `[4]`
   - **Projects** (Directory folder hex) `[5]`
   - **Office** (Headquarters building outpost) `[6]`
   - Active tab features Forge Orange (`#FF8C42`) glow, icon color, and bottom highlight; hover raises a faint panel.
   - Keyboard shortcuts re-mapped (`1`–`6`); shortcut overlay modal (`?`) updated.
3. **New Office Pane:** Lazy-loads the live office from `http://${location.hostname}:8904/` in an iframe, preserving LAN compatibility and keeping session state alive across tab switches.
4. **Server-Side API Implementation (`server.py`):**
   - Added `GET /api/trading`: fetches from `http://127.0.0.1:8904/data/trading.json` with a 1.5s timeout, falls back to direct read of `~/HydrocarbonForge/Projects/forge-office/data/trading.json`, and returns a structured `{ "error": "...", "upstream": "down", "service": "office" }` with HTTP 502 on failure (never crashes or 500s).
   - Added `GET /api/home`: optional high-performance aggregation endpoint bundling summary, flow, trading, and ideas metrics in a single payload.
5. **Strict Constraint Adherence:**
   - No running services were restarted (`systemctl` untouched).
   - Port 8903 was never bound by our test instances.
   - Verification executed on isolated test port `8910` and cleanly killed.
   - Live engine data files remained strictly read-only.
   - Zero third-party runtime dependencies; vanilla JS and standard library Python only.

---

## 2. Chosen Design Concept

Documented in depth in `DESIGN.md`:
- **Concept Name:** *The Living Foundry Floor / Master Control Bay*
- **Metaphor:** A cyber-physical industrial command bridge. The interface rejects generic SaaS card grids in favor of high-contrast graphite bays (`#0a0a0a` / `#121212`) bounded by hairline borders (`rgba(255, 255, 255, 0.08)`) and illuminated by Forge Orange thermal energy (`#FF8C42`).
- **Signature Motion:**
  - Ambient `#hf-ring` SVG symbol rotating at 90s linear infinite in the background (`color: rgba(255, 140, 66, 0.04)`).
  - Ambient breathing radial glow (`hf-breathe` 9s ease-in-out infinite).
  - Micro-pulsing indicator lamps (`hf-pulse` 2s infinite) with hexagonal clip paths for active systems.
  - Staggered cubic-bezier entrance reveals (`.reveal-in` -> `.in` with `0.45s cubic-bezier(0.2, 0.8, 0.2, 1)`).
  - Tabular count-up number tweening (~400ms duration).
  - Full `@media (prefers-reduced-motion: reduce)` accessibility compliance.

---

## 3. Verification Report & Terminal Output Snippets

All verification was performed against a test server instance running on **PORT 8910** (`PORT=8910 python3 server.py`).

### 3.1. Standard Library & Import Hygiene
```bash
$ python3 -c "import server, collector; print('Imports clean!'); t_data, t_err = server.fetch_trading_data(); print('Trading data ok:', t_data is not None, 'keys:', list(t_data.keys()) if t_data else None)"
Imports clean!
Trading data ok: True keys: ['updated', 'updated_ts', 'stock', 'crypto', 'errors']
```

### 3.2. Static Serving & Root Endpoint (`GET /`)
```bash
$ curl -s -I http://127.0.0.1:8910/
HTTP/1.1 200 OK
Server: BaseHTTP/0.6 Python/3.14.7
Date: Tue, 06 Oct 2026 23:55:29 GMT
Content-Type: text/html; charset=utf-8
Content-Length: 29028
Cache-Control: no-cache
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, PATCH, DELETE, OPTIONS
Access-Control-Allow-Headers: Content-Type, Authorization, X-Requested-With
```

Verification of key DOM nodes in HTML payload:
```bash
$ curl -s http://127.0.0.1:8910/ | grep -E "nav-home|nav-office|pane-home|pane-office|hf-ring"
    <symbol id="hf-ring" viewBox="0 0 100 100">
        <button class="nav-tab active" id="nav-home" data-tab="home" role="tab" aria-selected="true">
        <button class="nav-tab" id="nav-office" data-tab="office" role="tab" aria-selected="false">
    <section class="tab-pane active" id="pane-home" role="tabpanel">
          <svg class="home-hero-ring"><use href="#hf-ring" /></svg>
    <section class="tab-pane iframe-pane" id="pane-office" role="tabpanel" style="display:none;">
```

### 3.3. Office Trading Endpoint (`GET /api/trading`)
```bash
$ curl -s -i http://127.0.0.1:8910/api/trading | head -n 30
HTTP/1.1 200 OK
Server: BaseHTTP/0.6 Python/3.14.7
Date: Tue, 06 Oct 2026 23:55:40 GMT
Content-Type: application/json; charset=utf-8
Content-Length: 2418
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, PATCH, DELETE, OPTIONS
Access-Control-Allow-Headers: Content-Type, Authorization, X-Requested-With

{
  "updated": "2026-10-06T23:18:58.083278+00:00",
  "updated_ts": 1791328738.083278,
  "stock": {
    "label": "STOCKS",
    "subtitle": "aggressive high R:R",
    "equity": 99.03,
    "start": 100.0,
    "total_pnl": -0.97,
    "total_pct": -0.97,
    "day_pnl": -0.71,
    "day_pct": -0.71,
    "cash": 4.94,
    "cash_pct": 5.0,
    "total_fees": 0.14,
    "tax_rate": 0.15,
    "taxable_gains": 0.0,
    "capital_gains_tax": 0.0,
    "real_total": 99.03,
    "taxed_total": 99.03,
    "holdings": [
      {
        "sym": "META",
        "qty": 0.03,
        "px": 743.79,
        "val": 19.93,
        "w": 20.1
      }
```

### 3.4. Aggregated Home Payload (`GET /api/home`)
```bash
$ curl -s http://127.0.0.1:8910/api/home | python3 -c "import sys, json; d = json.load(sys.stdin); print('alltime tokens:', d['summary_alltime']['total_tokens']); print('harnesses count:', len(d['flow']['harnesses'])); print('active harnesses:', [h['label'] for h in d['flow']['harnesses'] if h.get('running') or h.get('active_sessions', 0) > 0]); print('trading equity:', d['trading']['stock']['equity'] + d['trading']['crypto']['equity']); print('ideas count:', d['ideas_count'])"
alltime tokens: 135084455
harnesses count: 4
active harnesses: ['Antigravity (AGY)', 'C6 (Hermes)']
trading equity: 197.91
ideas count: 0
```

### 3.5. Existing Proxies (`GET /api/summary?days=1`, `?days=3650`, and `/api/flow`)
```bash
$ curl -s "http://127.0.0.1:8910/api/summary?days=1" | python3 -c "import sys, json; d = json.load(sys.stdin); print('proxy days=1 total_tokens:', d.get('total_tokens'), 'billed_tokens:', d.get('billed_tokens'))"
proxy days=1 total_tokens: 21438939 billed_tokens: 6955057

$ curl -s "http://127.0.0.1:8910/api/summary?days=3650" | python3 -c "import sys, json; d = json.load(sys.stdin); print('proxy days=3650 total_tokens:', d.get('total_tokens'), 'billed_tokens:', d.get('billed_tokens'))"
proxy days=3650 total_tokens: 135084455 billed_tokens: 21974943

$ curl -s "http://127.0.0.1:8910/api/flow" | python3 -c "import sys, json; d = json.load(sys.stdin); print('flow keys:', list(d.keys())); print('harnesses count:', len(d.get('harnesses', []))); print('projects count:', len(d.get('projects', [])))"
flow keys: ['harnesses', 'filesystem', 'projects', 'services', 'databases', 'generated_at', 'elapsed_ms']
harnesses count: 4
projects count: 19
```

### 3.6. Static Assets & Syntax Verification
```bash
$ curl -s -I http://127.0.0.1:8910/style.css
HTTP/1.1 200 OK
Content-Type: text/css; charset=utf-8
Content-Length: 46491

$ curl -s -I http://127.0.0.1:8910/app.js
HTTP/1.1 200 OK
Content-Type: text/javascript; charset=utf-8
Content-Length: 96001

$ node --check web/app.js
(Exited with status 0, clean syntax)
```

### 3.7. 502 Upstream Fallback Robustness Test
```bash
$ python3 -c "import server, json, unittest.mock as mock;
mock_path = mock.MagicMock()
mock_path.exists.return_value = False
with mock.patch('server.urllib.request.urlopen', side_effect=Exception('Connection refused')):
    with mock.patch('server.OFFICE_TRADING_PATH', mock_path):
        d, err = server.fetch_trading_data()
        assert d is None
        print('Error handling verified:', err)
"
Error handling verified: Office trading service unreachable and trading.json not found
```
Output shape verified: `{'error': 'Trading upstream unavailable', 'upstream': 'down', 'service': 'office'}` with HTTP 502.

### 3.8. Browser Rendering & Headless Visual Verification
Headless Chromium was executed across the dashboard and destination panes:
- **HOME Dashboard:** Verified in `home_console_verified.png`. Renders complete 6-tab nav bar with active HOME highlight, live clock, 5/5 services up badge, background spinning `#hf-ring`, today's tokens `21.44M` (`6.96M billed`), all-time tokens `135.1M`, trading equity `$197.91` with Day and Total P/L pills, active running harness `ANTIGRAVITY (AGY)` (PID 660019), active projects (`forge-office`, `forge-console`, `stock-playground`), and 5 clickable destination launchpad cards.
- **PROJECTS Pane:** Verified in `projects_tab_verified.png`. Highlights `PROJECTS 5` tab and renders the central project directory table.
- **FLOW Pane:** Verified in `flow_tab_verified.png`. Highlights `FLOW 4` tab and mounts the interactive canvas, HUD pills, and force graph.
- **OFFICE Pane:** Verified in `office_tab_verified.png`. Highlights `OFFICE 6` tab and loads the virtual LAN headquarters from port 8904.
- **INSIGHTS Pane:** Verified in `insights_tab_verified.png`. Highlights `INSIGHTS 2` tab and displays token telemetry and cost charts.
- **IDEAS Pane:** Verified in `ideas_tab_verified.png`. Highlights `IDEAS 3` tab and loads the scheme board constellation graph.

### 3.9. Process & Port Cleanup
```bash
$ manage_task kill 01c2ca3b-2bb4-4087-8bb8-c76e2015a07c/task-231
Task "01c2ca3b-2bb4-4087-8bb8-c76e2015a07c/task-231" cancelled.

$ ss -tulpn | grep 8910
(No output, port 8910 is cleanly unassigned)
```

---

## 4. Git Commit History for this Task

1. `9f48d16` — `design: add comprehensive DESIGN.md specification for HOME dashboard and icon navigation`
2. `113a706` — `server: add /api/trading route with office fallback and /api/home aggregate endpoint`
3. `fa72dfa` — `html: add 6-tab icon navigation, HOME dashboard markup, and OFFICE pane container`
4. `dfa4c68` — `css: add icon navigation, HOME dashboard layout, kinetic animations, and responsive styles`
5. `c59e52b` — `js: implement HOME dashboard data fetching, live polling, tweening, and 6-tab navigation`
