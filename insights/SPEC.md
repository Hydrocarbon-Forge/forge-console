# INSIGHTS BOARD — Build Spec

A standalone, always-local usage board for the Hydrocarbon Forge Hermes instance.
It visualizes what `hermes insights` reports (sessions, tokens, tools, skills,
costs) from the local Hermes state DB, with a "what would this cost if we were
paying" overlay from a hand-maintained pricing file. **No LLM calls, ever** —
pure SQL over a SQLite DB plus static frontend.

## Hard constraints

1. **Backend: Python 3 standard library only.** No pip installs, no fastapi/uvicorn.
   Use `http.server.ThreadingHTTPServer` + `sqlite3` (open the DB in
   read-only mode: `sqlite3.connect(f"file:{DB}?mode=ro", uri=True)`).
   Run with the system python3.
2. **Frontend: static files, no build step, no npm.** Plain HTML/CSS/vanilla JS
   in `web/`. Charts hand-rolled in SVG or canvas. Google Fonts via `<link>`
   (Oswald, Inter, JetBrains Mono) — must still render fine offline (font fallbacks).
3. **Read-only on the DB.** Never write to `~/.hermes/state.db`.
4. **Bind 127.0.0.1 by default** (flag `--host`, `--port`, `--db` override).
5. All timestamps in the DB are **epoch seconds (REAL)**. Use local time for
   date bucketing (`time.localtime`).

## Data source (READ-ONLY)

DB: `~/.hermes/state.db` (env `HERMES_DB` or `--db` overrides).

### `sessions` table (relevant columns)
`id TEXT, source TEXT, model TEXT, display_name TEXT, title TEXT,
started_at REAL, ended_at REAL, message_count INTEGER, tool_call_count INTEGER,
input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER,
cache_write_tokens INTEGER, reasoning_tokens INTEGER, billing_provider TEXT,
billing_mode TEXT, estimated_cost_usd REAL, actual_cost_usd REAL,
cost_status TEXT, api_call_count INTEGER, last_activity_at REAL,
last_activity_description TEXT`

### `session_model_usage` table (per-model + aux usage)
`session_id TEXT, model TEXT, billing_provider TEXT, task TEXT,
api_call_count INTEGER, input_tokens INTEGER, output_tokens INTEGER,
cache_read_tokens INTEGER, cache_write_tokens INTEGER, reasoning_tokens INTEGER,
estimated_cost_usd REAL, actual_cost_usd REAL, first_seen REAL, last_seen REAL`
- Rows with `task = ''` are main-loop usage; `task` in
  `title_generation/approval/background_review/...` are auxiliary.
- A session's per-model rows may not sum to the session totals (reconciled
  residuals exist). For the **per-model breakdown**, aggregate
  `session_model_usage` by `model` for the window, then fold residual
  (session totals minus per-model sums, attributed to the session's `model`)
  into that model so the model table matches the overview totals.

### `messages` table (tool calls)
`session_id TEXT, role TEXT, tool_name TEXT, tool_calls TEXT (JSON),
timestamp REAL`
- Tool counts: `role='tool'` rows have `tool_name` populated by the gateway
  (discord sessions). CLI sessions instead carry `tool_calls` JSON on
  `role='assistant'` rows: `[{"function": {"name": "...", "arguments": "..."}}]`.
- **Reconcile per (session_id, tool): take max of the two representations,
  then sum across sessions.**
- Skill usage: from `tool_calls` JSON, entries whose `function.name` is
  `skill_view` or `skill_manage`; `arguments` is a JSON string with a `name`
  field = the skill name. Count view vs manage per skill + last_used.
- Filter both sources by joining to `sessions` on `session_id` and
  `sessions.started_at` within the window.

## Backend — `server.py` (single file ok; may add `db.py`)

Serves JSON API + static `web/` on `http://127.0.0.1:8901`.

### Cache/refresh model
- Recompute aggregates when `state.db` mtime changes OR forced; TTL 60s.
- Each API handler takes `?days=7|30|90|365|all` (default 30; `all` = no cutoff).
- Return `{"generated_at": epoch, "db_mtime": epoch, "days": "30"|"7"|... , ...}`
  so the frontend can show freshness + the requested window echo.

### Endpoints
- `GET /api/summary?days=` — window totals (canonical; `GET /api/insights?days=`
  is a documented alias returning the identical payload):
  `sessions, messages (sum message_count), user_messages, tool_calls,
  api_calls, input_tokens, output_tokens, cache_read_tokens,
  cache_write_tokens, reasoning_tokens, total_tokens (in+out+cr+cw),
  estimated_cost_usd, actual_cost_usd, total_hours_active (sum
  ended_at-started_at where both present and positive),
  avg_session_duration_s, avg_tokens_per_session, date_range_start,
  date_range_end`.
- `GET /api/models?days=` — list, one row per model (fold residuals as above):
  `model, provider (billing_provider or ''), sessions (distinct),
  input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
  reasoning_tokens, total_tokens, api_calls, tool_calls (session attr),
  estimated_cost_usd, cost_status ('priced'|'included'|'unknown'),
  last_used_at, is_aux_share (fraction of tokens from task!='' rows)`.
  Sort by total_tokens desc. Include aux-only models.
- `GET /api/platforms?days=` — per `source`: sessions, messages, total_tokens,
  tool_calls.
- `GET /api/tools?days=` — top 20: `tool, count, pct`.
- `GET /api/skills?days=` — `summary {loads, edits, distinct}` + list
  `skill, view_count, manage_count, last_used_at`.
- `GET /api/activity?days=` — `by_day` (Mon..Sun counts), `by_hour`
  (24 buckets), `daily` (last `min(days,30)` days: date, sessions, total_tokens
  — **include zero-filled gaps**), `busiest_day, busiest_hour, active_days,
  max_streak`, `top_sessions` (longest, most messages, most tokens, most tool
  calls → `{label, session_id (first 16 chars), value, date, title}`),
  plus `tools` (top-20 reconciled tool breakdown for the window, same
  `JOIN sessions … WHERE sessions.started_at >= ?` logic as `/api/tools`:
  `{tool, count, pct}`) and `tools_total`.
- `GET /api/cost?days=` — the "what if we were paying" overlay:
  for each model with usage, look up `pricing.json`; compute
  `cost_usd = (input*in + output*out + cache_read*cr + cache_write*cw)/1e6`;
  return `models: [{model, cost_usd, priced: bool, rates: {...}|null}]`,
  `total_usd` (sum of priced models), `unpriced_tokens` (total tokens on
  unpriced models), `per_day_usd` (total / distinct active days).
- `GET /api/health` — `{ok: true, db: path, db_mtime, cache_age_s}`.
- `GET /api/pricing` — the current pricing file contents.
- `POST /api/pricing` — replace pricing file (body = JSON). Validate:
  `{"models": {name: {input, output, cache_read?, cache_write?, note?, also?}}}`
  rates are $/million tokens. Atomically write `pricing.json` (tmp+rename).
  This lets the frontend have an "edit prices" panel (or curl it).
- Static: `GET /` → `web/index.html`, `/app.js`, `/style.css` from `web/`.
  404 otherwise. `Content-Type` set correctly.

### `pricing.json` (seed provided)
```json
{"models": {"<model-id>": {"input": 0.4, "output": 1.2,
  "cache_read": 0.04, "cache_write": 0.5, "note": "...",
  "also": ["lowercase-alias", "..."]}}}
```
Matching: normalize model id (lowercase, strip leading dir path, strip
provider prefix before first `/` for aliasing purposes but keep full id as
primary key). Match = normalized full id in `models` keys or in any entry's
`also` list, case-insensitive.

## Frontend — `web/` (index.html + app.js + style.css)

**Brand: Hydrocarbon Forge.** Dark industrial forge aesthetic, matching the
company website:
- Backgrounds: `#0a0a0a` page, panels `#121212`/`#1a1a1a`, 1px borders
  `rgba(255,255,255,0.08)`.
- Text: `#ececee` primary, `#9d9ea5` muted, `#6a6b72` faint.
- Accent: `#ff5a5a` (ember red) for highlights, live dot, key numbers;
  secondary chart hues: amber `#ffb454`, steel `#5aa9e6`, mint `#5ad6a0`.
- Fonts: Oswald (display/headers, uppercase, letter-spaced), Inter (body),
  JetBrains Mono (numbers, labels, tick marks). Google Fonts `<link>`.
- Vibe: control-room / foundry dashboard. Sharp corners (2-4px radius max),
  uppercase micro-labels with letter-spacing, thin rules, big tabular numerals.
  Subtle scanline or grid texture OK but restrained. NO gradient-mesh
  purple AI-slop, no glassmorphism.

### Layout (single page, responsive)
1. **Header bar**: left `HYDROCARBON FORGE` wordmark + `INSIGHTS` tag;
   right: period switcher `[7D][30D][90D][ALL]` (segmented control) +
   LIVE dot (pulses green when data <90s old, amber if stale) +
   `updated HH:MM:SS`.
2. **KPI strip** (6 cards): TOTAL TOKENS (compact K/M), SESSIONS, TOOL CALLS,
   API CALLS, CACHE HIT RATE (% of input-side tokens that were cache reads:
   `cache_read/(input+cache_read+cache_write)`), EST. COST / D (from cost
   endpoint; shows `—` when $0 and unpriced → use `$0.00*` with footnote).
3. **TOKEN FLOW** chart: stacked area/line of daily tokens (input, output,
   cache read) for the window (30-day daily buckets; for 90/all, weekly
   buckets). SVG, axis ticks in JetBrains Mono, legend, hover tooltip with
   exact numbers.
4. **MODELS** leaderboard: rows `model · provider`, token bar (relative to
   max), sessions, tokens, and cost column from `/api/cost` (per-model $;
   `—` when unpriced, with a small `+` button opening the price editor for
   that model).
5. **PLATFORMS** (small) + **TOP TOOLS** (top 10 horizontal bars) side by side.
6. **ACTIVITY**: 24-hour bar strip (sessions by hour, local), busiest day/hour
   callouts, streak; **NOTABLE SESSIONS** table (4 rows: label, value, date,
   title truncated).
7. **COST PANEL** ("WHAT IT WOULD COST IF WE WERE PAYING"): big total $,
   per-model table, per-day average, and a clear note:
   `estimates from pricing.json · models without pricing excluded` + count of
   unpriced tokens. Plus `EDIT PRICES` button → inline form (per model:
   input/output/cache_read/cache_write $/M) posting to `/api/pricing`.
8. Footer: `hermes state.db · updated <age> · hydrocarbon forge`.

### Behavior
- On load and on period change: fetch all endpoints in parallel, render.
- Auto-refresh every 60s (only re-fetch; cheap). Show spin/flash on update.
- All numbers: tabular-nums, compact formatting (1.2M, 348K), costs as $X.XX.
- Errors: if API unreachable show a big `BOARD OFFLINE` state, retry 5s.
- Zero-state (empty window): friendly `NO SESSIONS IN WINDOW`.
- No frameworks. Vanilla JS (module script). Must work from `file://`
  is NOT required — it's served by the backend.

## Files
```
~/HydrocarbonForge/Projects/insights-board/
  server.py         # API + static server (stdlib only)
  pricing.json      # seed (below)
  web/index.html
  web/app.js
  web/style.css
  test_api.py       # see acceptance
  README.md         # run instructions
```

## Acceptance (run all, show output)
1. `python3 server.py --port 8901 &` → `curl -s localhost:8901/api/health`
   returns `{"ok": true, ...}`.
2. `curl -s localhost:8901/api/summary?days=30` → 27 sessions,
   input_tokens 1,143,554, output_tokens 239,996, cache_read_tokens
   10,017,655 (±drift), total_tokens 11,400,165.
3. `curl -s localhost:8901/api/models?days=30` → top model `qwen-3.8-27b`
   with ~1.1M+240K tokens; a `Qwen3.8-27B` gguf aux row may appear
   (title/approval aux usage) — that's correct.
4. `curl -s localhost:8901/api/tools?days=30` → `terminal` first (~187),
   `read_file` ~27.
5. `curl -s localhost:8901/api/activity?days=30` → 24-length `by_hour`,
   30-length zero-filled `daily`, non-zero `active_days`.
6. `curl -s localhost:8901/api/cost?days=30` → all models unpriced with the
   seed pricing.json (no qwen entry) → `total_usd: 0.0`,
   `unpriced_tokens` == window total_tokens.
7. `curl -s -X POST localhost:8901/api/pricing -d '{"models":
   {"qwen-3.8-27b": {"input": 0.4, "output": 1.6, "cache_read": 0.04}}}'`
   → subsequent `/api/cost?days=30` shows `total_usd > 0` for qwen (roughly
   (1143554*0.4 + 239996*1.6 + 10017655*0.04)/1e6 ≈ $3.56) and
   `unpriced_tokens` drops to the gguf aux tokens.
8. `curl -s localhost:8901/ | head` → index.html with `HYDROCARBON FORGE`.
9. `python3 test_api.py` → all green (it hits the running server, asserts
   the shapes + the invariants above, prints PASS/FAIL per check).
10. DB untouched: `stat` mtime unchanged after all API calls.

## Do NOT
- No LLM/API calls, no network fetches from the backend.
- No writes to the hermes DB.
- No build tooling, no node, no npm.
- No auth (localhost board), but do NOT bind 0.0.0.0 by default.
