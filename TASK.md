# TASK: Build the Forge Console

You are building the Forge Console — the central Hydrocarbon Forge control panel — in the current directory.

## Step 1 — Read the spec
Read `SPEC.md` in this directory **fully first**. It is the source of truth: product, the Flow tab node/edge spec, design system, server implementation notes, file layout, acceptance checklist, and verified environment facts (Linux, Python 3.14, stdlib only — no third-party packages exist, /proc available, agy/claude/opencode CLI facts). Do not edit SPEC.md.

Before coding, study the existing code you must mirror or reuse (read the actual files):
- `../insights-board/web/{index.html,app.js,style.css}` — replicate its dashboard views in the Insights tab
- `../scheme-board/site/app.js` + `../scheme-board/SPEC.md` §Frontend — port the working force simulation, palette, and idea rendering into the Ideas tab
- `../hydrocarbon-forge-website/ideas.html` (`#hf-mark` hexagon SVG) and `../hydrocarbon-forge-website/styles.css` (`--hex-pattern`) — port the logo mark and hex pattern

## Step 2 — Implement everything in the spec
File layout (exactly):

```
forge-console/
  server.py        stdlib-only HTTP server on port 8903 (PORT env override)
  collector.py     flow data gathering; importable, main-guarded
  web/index.html, web/app.js, web/style.css
  run.sh
  data/collector.log (created at runtime)
```

Server (`server.py`, stdlib only: http.server.ThreadingHTTPServer, json, sqlite3, urllib, urllib.request):
- `GET /api/health` → `{ok, port, services:[...]}`
- `GET /api/flow` → the flow doc from a background collector thread: `{harnesses:[...], filesystem:{recent:[...]}, projects:[...], services:[...], databases:[...], generated_at}`. All five node groups must always be present as keys (lists may be empty). Computed in a daemon collector thread on a 5s tick (never raises out of the loop; catch-all + log to `data/collector.log`); the endpoint itself must answer <20ms warm (serves cached data; first call may return `stale:true`).
- `GET /api/proxy/insights/{endpoint}?days=N` → fetch `http://127.0.0.1:8901/api/{endpoint}` and forward the JSON. `GET /api/proxy/scheme/{path}` → same for `http://127.0.0.1:8902`. Also pass through POST/PATCH for scheme endpoints (status edits, new ideas). If an upstream is down, return a well-formed error JSON `{error: "...", upstream:"down"}` with HTTP 502 — never crash.
- `GET /` → static `web/` files.
- All API responses: `Access-Control-Allow-Origin: *` + OPTIONS handling.
- Startup must not block: slow probes (health checks, db stat) happen in the thread.

Collector (`collector.py`) — all local, no LLM calls, no external services:
- **Harness nodes**: opencode (read `~/.local/share/opencode/opencode.db` sqlite read-only — recent `session`/`session_message` activity within ~10 min; count active sessions; subagent count if cheap), claude code (process scan for `claude` via `/proc/*/cmdline` reads, exclude self/grep, plus `~/.claude/sessions` if present), antigravity (same scan for `agy`). Each node: name, today's usage bar data (token/cost share, relative scale — derive cheaply from the insights API or skip the bar if not cheap), active session count.
- **Filesystem node**: recent writes under `~/HydrocarbonForge/Projects/` via shallow 2-level walk with a cached dir listing + stat of recently-modified files; keep it under ~50ms; show last few changed files (relative path, +X min ago).
- **Project nodes**: one per project dir under `~/HydrocarbonForge/Projects/` (skip dotdirs, node_modules, .venv): name, cached file count, activity = changes in last 60 min.
- **Service nodes**: insights-board :8901, scheme-board :8902, forge-console :8903, hermes gateway, website static dir — green/amber/red from a cheap health check (HEAD `http://127.0.0.1:<port>/api/health` where available else TCP connect, 3s timeout) run in the background thread.
- **Data nodes**: `~/.hermes/state.db`, `~/.local/share/opencode/opencode.db`, `~/HydrocarbonForge/Projects/scheme-board/data/board.db`, hermes cron/output dirs — size + last-write age.

Frontend (`web/` single page, no frameworks, no external JS):
- **Insights tab**: fetch `/api/proxy/insights/*` (summary, models, platforms, tools, skills, activity, cost, opencode, claudecode, antigravity, pricing) and render the existing board's views — summary cards, model table, platform breakdown, activity timeline, cost. Day-range selector 7/30/90. Stale/offline banner if the upstream proxy 502s.
- **Ideas tab**: fetch `/api/proxy/scheme/api/ideas|connections|themes|stats|analysis` and render stats chips, the idea list (title, editable status chip via PATCH through `/api/proxy/scheme/...`, category, owner, top scores, tags), the force-directed map (port scheme-board's simulation), stats/opp ranking. "New idea" button → POST through the proxy. 30s refresh.
- **Flow tab** (the centerpiece): canvas, full-tab, dark, animated. Hexagon hub ("Forge") in the center; harness nodes, filesystem node, project nodes, service nodes, data nodes around it. Static edges per the spec (harnesses + data dbs → hub; filesystem → projects; services → data nodes they read). Glowing dots travel along edges when a source is active, colored per source accent; running nodes get a pulsing glow; `requestAnimationFrame`; pause on `visibilitychange`; respect `prefers-reduced-motion`; hover tooltips; click → side detail panel. Structure the code so control actions can be added later. Poll `/api/flow` every 5s and lerp bars/dots toward it (don't snap).
- **Shared shell**: top nav with the HF hexagon mark + "FORGE" wordmark, tab buttons (Insights / Ideas / Flow), live clock + "all services: N up" three-dot strip. Hash routes `#/insights`, `#/ideas`, `#/flow` (no full reload, keep per-tab state, lazy-init). Keys `1`/`2`/`3` switch tabs, `?` shows a shortcut overlay.
- **Design system** (from the spec, verified house style): bg `#0a0a0a`, panel `#121212`/`#1a1a1a`, border `rgba(255,255,255,0.08)`, text `#ececee`, muted `#9d9d9d`/`#9d9ea5`; accent forge orange `#FF8C42` + `#5aa9e6`, `#5ad6a0`, `#ffb454`, `#3ddc84`, `#f25c54`, `#b185db`. Fonts: Oswald (display, uppercase, .12em tracking) + Inter (body) + JetBrains Mono (numbers) from Google Fonts `display=swap` with a system-font fallback stack (must degrade offline). Hexagon motif for the hub + subtle `--hex-pattern` background. 28px grid at ~1.5% white, 6px radius, uppercase 11px .14em micro-labels, ~150ms hover transitions, focus-visible rings, no layout shift on tab switch, subtle scroll-reveal. This is the flagship internal tool — make it genuinely beautiful.

## Step 3 — Verify the acceptance checklist as you go
Run these yourself and record the actual output:
1. `python3 -c "import server, collector"` clean; no third-party imports.
2. Start via `./run.sh`; `curl -s http://127.0.0.1:8903/api/health` → 200 JSON.
3. `curl -s http://127.0.0.1:8903/api/flow` → all five node-group keys present.
4. `curl -s "http://127.0.0.1:8903/api/proxy/insights/summary?days=7"` matches 8901's `curl -s "http://127.0.0.1:8901/api/summary?days=7"`; `curl -s http://127.0.0.1:8903/api/proxy/scheme/api/stats` matches 8902's `curl -s http://127.0.0.1:8902/api/stats`.
5. `curl -s http://127.0.0.1:8903/` serves the SPA HTML; time a warm `curl -s -o /dev/null -w "%{time_total}"` on `/api/flow` (should be <0.02s).
6. Grep `web/` for external `src=`/`href=` — Google Fonts is the only allowed external reference.
7. Then **kill the test server** — nothing may be left bound to 8903. Do not create any systemd service. Do not leave any other test servers or background processes running.

## Step 4 — Write FORGE-CONSOLE-REPORT.md
In this directory: what was built (per file, briefly), the acceptance checklist with your actual curl output snippets as evidence, anything skipped and why, and how to start it (`./run.sh`).

## Rules
- Python: clean, short functions, no over-abstraction. `app.js` organized with banner-comment sections (state, tabs, insights tab, ideas tab, flow tab, flow renderer, util).
- Do NOT create a README. Do not edit SPEC.md. No servers other than 8903; kill all test servers before finishing.
- Both upstreams (8901, 8902) are running right now — your proxy verification will work live.
