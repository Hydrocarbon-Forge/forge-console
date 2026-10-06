# Forge Console — build spec

Central Hydrocarbon Forge control panel: one dark UI with seamless tabs that
aggregate every dashboard/insight service we already run, plus a live
node-based "flow" view of the whole forge.

Requested by Nathan 2026-10-04. Build in this directory.

## Product

A local web app served on port **8903** (bound `0.0.0.0`), stdlib-only
Python server + vanilla JS frontend (no build step, no CDN — must work
offline on LAN). Tabs (top nav, keyboard-accessible):

1. **Insights** — the existing usage board: model/platform/cost/activity
   charts and tables. Do NOT rebuild this: fetch data from the
   **insights-board API at `http://127.0.0.1:8901/api/*`** (endpoints:
   `/api/summary`, `/api/models`, `/api/platforms`, `/api/tools`,
   `/api/skills`, `/api/activity`, `/api/cost`, `/api/opencode`,
   `/api/claudecode`, `/api/antigravity`, `/api/pricing`, `/api/health`;
   all take `?days=N`, default 30). Reimplement its dashboard rendering in
   this tab (the existing board lives in
   `../insights-board/web/{index.html,app.js,style.css}` — study it and
   replicate the views: summary cards, model table, platform breakdown,
   activity timeline, cost). Day-range selector (7/30/90). Show a stale/
   offline banner if 8901 is unreachable.

2. **Ideas** — the scheme board ("super idea organizer",
   `../scheme-board`, port **8902**): fetch `/api/ideas`,
   `/api/connections`, `/api/themes`, `/api/stats`, `/api/analysis` and
   render: stats chips, the idea list (title, status chip editable via
   PATCH, category, owner, top scores, tags), a force-directed map (ideas
   as nodes colored by category, edges by connection type — palette from
   `../scheme-board/SPEC.md` §Frontend), stats/opp ranking. "New idea"
   button → POST. 30s refresh. Reuse patterns from
   `../scheme-board/site/app.js` (it already has a working force sim —
   port it).

3. **Flow** — NEW, the centerpiece: a live node-graph "where data is
   flowing" view (visual only — no controls yet, but structure the code so
   control actions can be added later).

### Flow tab spec

Canvas-based, one full-tab scene, dark, animated. Node types:

- **Harness nodes** — one per agent harness: `opencode`, `claude code`,
  `antigravity` (agy). Each node shows: name, a small usage bar (today's
  token/cost share — derive cheaply from insights API or the usage report;
  the bar just needs relative scale), active session count, and a pulsing
  highlight ring while active sessions exist.
  - Active-session detection:
    - opencode: read `~/.local/share/opencode/opencode.db` (sqlite,
      read-only) — recent `session` rows (updated within ~10 min) and
      `session_message` activity; count = active sessions.
    - claude code: `pgrep -f` / `ps` scan for `claude` processes (exclude
      self, exclude grep); also check `~/.claude/sessions` if present.
    - antigravity: same for `agy` processes.
  - Sub-task/chats: if cheap to derive (e.g. opencode subagent sessions
    in the same DB), show a "subtasks: N" line.
- **Filesystem node** — recent writes/changes in
  `~/HydrocarbonForge/Projects/`: walk with mtime (cache dir list, stat
  recently-modified files — no full recursive walk per tick, keep it under
  ~50ms; a shallow 2-level walk with cached dirs is fine). Show last few
  changed files (path relative, +X min ago, size delta if known). No LLM,
  no external services — local only, must never slow the server.
- **Project nodes** — one node per project dir under
  `~/HydrocarbonForge/Projects/` (auto-discovered, skip dotdirs,
  `node_modules`, `.venv`): name, file count (cached), "activity" bar =
  changes in last 60 min, link/dock to the filesystem node.
- **Site/service nodes** — the running services: insights-board :8901,
  scheme-board :8902, forge-console :8903, hermes gateway (check
  `~/.hermes` process or a health probe on the known port), website
  static dir status. Green/amber/red dot from a cheap HTTP health check
  (HEAD `http://127.0.0.1:<port>/api/health` where available, else TCP
  connect) — 3s timeout, run from a background thread, never block
  request handling.
- **Data nodes** — SQLite databases: `~/.hermes/state.db`,
  `~/.local/share/opencode/opencode.db`, `~/HydrocarbonForge/Projects/scheme-board/data/board.db`,
  hermes cron/output dirs. Show size + last-write age.

**Edges & animation:** static edges connect logical parents (harness →
projects it touches is too smart to derive reliably — instead: harnesses
and data dbs → a central "Forge" hub node; filesystem node → project
nodes; services → data nodes they read). Dots (small glowing circles)
travel along edges when the source is active: e.g. a harness with an
active session emits dots toward the hub at a rate proportional to
activity; filesystem node emits dots toward a project node when that
project had writes in the last ~5 min; a service emits a slow steady
drift when healthy. Running nodes get a soft pulsing glow; the dot color
matches the source node's accent color. `requestAnimationFrame`, pause
when tab hidden (`visibilitychange`), respect `prefers-reduced-motion`
(no dots, just static highlights). Node hover → tooltip with details
(active sessions, last activity, recent files). Click project/harness
node → side panel with details.

**Server side for Flow:** a single `GET /api/flow` endpoint returning one
JSON doc: `{harnesses:[...], filesystem:{recent:[...]}, projects:[...],
services:[...], databases:[...], generated_at}` — computed by a background
collector thread refreshing every 5–10s (process scan + stat cache), so
the endpoint itself is always <10ms. Frontend polls every 5s and animates
toward it (lerp bars/dots, don't snap).

### Shared shell

- Top nav: FORGE logo (hex mark — reuse the SVG from
  `../hydrocarbon-forge-website/ideas.html`, the `#hf-mark` symbol),
  tab buttons (Insights / Ideas / Flow), right side: live clock +
  "all services: N up" mini-status strip (three colored dots).
- URL routing: `#/insights`, `#/ideas`, `#/flow` — hash routes so refresh
  and bookmarking work; seamless tab switching (no full reload, keep
  per-tab state alive, lazy-init each tab on first visit).
- Keyboard: `1`/`2`/`3` switch tabs, `?` shows a shortcut overlay.

### Design system (match the house style — verified from existing projects)

- Base dark: bg `#0a0a0a` / panel `#121212` / `#1a1a1a`, border
  `rgba(255,255,255,0.08)`, text `#ececee`, muted `#9d9ea5`.
- Accent: forge orange `#FF8C42` (scheme board) as primary accent;
  secondary palette from insights board: `#5aa9e6` steel, `#5ad6a0`
  mint, `#ffb454` amber, `#3ddc84` green, `#f25c54` red, `#b185db`
  purple.
- Typography: **Oswald** (display, uppercase, letter-spacing .12em for
  headings) + **Inter** (body) + **JetBrains Mono** (numbers/paths) —
  loaded from Google Fonts with `display=swap`, but the site must
  degrade to system fonts when offline (font-display + fallback stack).
- Hexagon motif (the HF logo mark) used as node shape for the Flow hub
  and as subtle background pattern (the website uses an SVG hex
  pattern — port `--hex-pattern` from
  `../hydrocarbon-forge-website/styles.css`).
- Chips, thin borders, subtle grid background
  (`linear-gradient` 28px grid at ~1.5% white, from insights board),
  6px radius, uppercase micro-labels (11px, .14em spacing).
- Make it genuinely beautiful: consistent spacing scale, hover
  transitions (~150ms ease), focus-visible rings, no layout shift on
  tab switch, subtle scroll-reveal on cards. This is the flagship
  internal tool — spend real effort on polish.

## Server implementation notes

- `server.py`: stdlib only (`http.server.ThreadingHTTPServer`, `json`,
  `sqlite3`, `urllib`, `sqlite3` read-only URIs, `subprocess` for
  `pgrep`/`ps` — or just `os.scandir` + `psutil`-free process detection
  via `/proc/*/cmdline` read, which is cheap and dependency-free).
- Port **8903** hardcoded default, `PORT` env override.
- API surface (all JSON, `Access-Control-Allow-Origin: *` + OPTIONS):
  - `GET /api/health` → `{ok, port, services:[...]}`
  - `GET /api/flow` → the flow document (cached in a background thread)
  - `GET /api/proxy/insights/{endpoint}?days=N` → fetches from
    127.0.0.1:8901 and forwards (so the browser only ever talks to 8903 —
    this is what makes the "unified port" work; same-origin, no CORS
    pain)
  - `GET /api/proxy/scheme/{path}` → same for 8902
  - proxy pass-through for POST/PATCH to scheme endpoints (for status
    edits + new ideas)
  - `GET /` → static `web/` files (index.html, app.js, style.css)
- Static dir `web/`: **single page**, `index.html` + `app.js` +
  `style.css`. No frameworks, no external JS.
- Collector thread: daemon, 5s tick, never raises out of the loop
  (catch-all + log to `data/collector.log`).
- Startup must not block: all slow probes (health checks, db stat)
  happen in the thread; first `/api/flow` may return `{stale:true}` with
  last-known or empty-but-structured data.

## File layout

```
forge-console/
  SPEC.md (this file — do not edit)
  server.py
  collector.py     (flow data gathering; importable, main-guarded)
  web/index.html  web/app.js  web/style.css
  run.sh
  data/collector.log
```

## Acceptance checklist (self-check before finishing)

1. `python3 -c "import server, collector"` clean; no third-party imports.
2. Server starts on 8903; `curl :8903/api/health` 200; `curl :8903/api/flow`
   returns a full structured doc with all five node groups (some may be
   empty lists, never missing keys).
3. Proxy: `curl :8903/api/proxy/insights/summary?days=7` returns the 8901
   JSON; `curl :8903/api/proxy/scheme/api/stats` returns the 8902 JSON
   (both upstreams are running — if one is down, proxy returns a
   well-formed error JSON with `upstream:"down"`, HTTP 502, not a crash).
4. `curl :8903/` serves the SPA; `app.js` has all three tabs; no
   external `src=`/`href=` to CDN hosts (Google Fonts link is the only
   allowed external reference).
5. `/api/flow` response time under 20ms on a warm cache (the collector
   thread does the work).
6. No port other than 8903 bound at the end; no leftover processes.
7. Report: endpoints verified with actual curl output snippets, anything
   skipped.

## Environment facts (verified — do not guess)

- Linux, Python 3.14, `fastapi`/`flask` NOT installed → stdlib only.
- Upstreams running: insights-board `:8901` (systemd user service
  `insights-board`, read-only usage API), scheme-board `:8902`
  (ThreadingHTTPServer, `../scheme-board/server.py`).
- `/proc` is available (read cmdline for process detection); no
  `psutil`.
- The antigravity harness CLI is `agy` (not `gemini`); claude code is
  `claude`; opencode v2 store is `~/.local/share/opencode/opencode.db`.
- Do NOT query any LLM from the console — everything local/proxy.
- `PORT` 8903 is currently free.

## Style

- Python: clean, short functions, no over-abstraction.
- Site: the design system above. Vanilla JS, one `app.js` is fine but
  keep it organized (sections with banner comments: state, tabs,
  insights tab, ideas tab, flow tab, flow renderer, util).
- Do NOT create a README (C6 writes notes separately). Do not start any
  server other than 8903 and kill test servers before finishing.
