# TASK5 — Claude Code + Antigravity usage as their own platforms

Follow-up to TASK4 (build on top; do NOT redo TASK3/TASK4). Board live on
0.0.0.0:8901 — keep it running, verify live. Same constraints as always
(stdlib only, read-only access, 0.0.0.0 bind). All new sources are additive —
C6 and opencode behavior must not change.

## New data sources (already inspected — do not re-invent, but verify at runtime)

### A. Claude Code — `~/.claude/projects/`
- Files: `~/.claude/projects/*/*.jsonl` AND `~/.claude/projects/*/subagents/*.jsonl`
  (include subagent files — their usage counts toward the same model).
- Each line is one JSON object. Only lines with `type == "assistant"` AND a
  `message.usage` object carry token data:
  - `message.usage.input_tokens`, `.output_tokens`,
    `.cache_read_input_tokens`, `.cache_creation_input_tokens`
  - `message.model` (e.g. `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-opus-4-8`)
  - line-level `timestamp` — ISO-8601 UTC (`2026-10-02T14:17:07.749Z`)
  - line-level `uuid` — verified unique across all files (no cross-file
    overlap), but still dedupe on (file, uuid) as a free safety net.
- Skip malformed lines (try/except per line). Missing model → `claudecode:unknown`.
- Model label: `claudecode:<model>` (e.g. `claudecode:claude-opus-5-5`).
- Billed vs cache semantics same as everywhere: billed = in+out+cache_creation,
  cache = cache_read.
- There is NO local cost field — cost comes only from the pricing overlay.
- Expected non-empty data (30d): claude-opus-5-5 ~24M total tokens,
  claude-opus-4-8 ~12M, claude-sonnet-5-5 ~15K. If your scan shows wildly
  different numbers, print what you saw in the report instead of guessing.

### B. Antigravity (agy) — `~/.gemini/antigravity-cli/`
- Token data lives at `brain/<conv_id>/.system_generated/logs/transcript.jsonl`
  (there is also a `transcript_full.jsonl` WITHOUT token fields — use
  `transcript.jsonl`). Lines that carry usage have keys:
  `input_tokens`, `output_tokens`, `cache_read_tokens`, `created_at`
  (ISO-8601 `2026-10-02T22:45:17Z`), `step_index`, `type` (e.g.
  `PLANNER_RESPONSE`). Only count lines that have `input_tokens`.
  No cache-write field exists → cache_write = 0.
- Model name: NOT in the transcript. The companion
  `conversations/<conv_id>.db` (protobuf blobs) contains the model string
  (verified: the conv run with gemini-3.8-flash-low has that literal in the
  file). Locate it by scanning the RAW BYTES of that file with a regex like
  `(gemini-[\d.]+[a-z-]*|claude-[a-z0-9.-]+|gpt-[\w.-]+|grok-[\d.]+)` and
  taking the most frequent match; no match or missing file →
  `antigravity:unknown`. This is acceptable for v1 — document it.
- `conversation_summaries.db` currently has 0 rows — do NOT depend on it, but
  a future version may populate it; code defensively.
- Model label: `antigravity:<model>` (e.g. `antigravity:gemini-3.8-flash-low`).
- Data is tiny today (one test run: ~12.5K in / 1 out) — that's expected.

## Features

### 1. Backend endpoints
- `GET /api/claudecode?days=1|7|30|90|all` and `GET /api/antigravity?days=...`
  with the EXACT shape TASK4 established for /api/opencode:
  `{source, sessions, models: [{model, sessions, input_tokens, output_tokens,
  cache_read_tokens, cache_write_tokens, billed_tokens, reported_cost_usd: 0}],
  daily: [{date, input_tokens, output_tokens, cache_read_tokens}],
  total: {...}, active_days}`.
  - claudecode: `sessions` = distinct top-level (non-subagent) files with ≥1
    usage line in the window; `reported_cost_usd` always 0 (no local cost).
  - antigravity: `sessions` = brain dirs with ≥1 usage line in the window.
  - daily zero-filled like /api/activity. Window on local date of the line
    timestamp.
- Add rows to `/api/platforms`: `claudecode` and `antigravity` (sessions,
  messages/lines, billable tokens, total tokens) alongside c6 sources and
  opencode.
- Cache/invalidation: follow the pattern TASK4 used for opencode (mtime
  stamped re-scan is fine — claudecode is ~3.6MB of jsonl total, antigravity
  tiny; a full re-scan per request is acceptable and simplest).

### 2. Pricing resolution for the new labels
- Cost engine: for labels starting `claudecode:` or `antigravity:`, STRIP the
  prefix and match the remainder against pricing keys AND `also` aliases.
  (pricing.json already carries the aliases: claude-opus-5-5,
  claude-sonnet-5-5, claude-opus-4-8, claude-opus-4-6(+thinking),
  gemini-3.8-flash-{high,medium,low}, gemini-3.1-pro-{high,low}.)
- Keep the TASK4 rule: `opencode:` prefix never matches pricing (free-tier).
  No other prefix changes.
- `claudecode:unknown` / `antigravity:unknown` → unpriced.

### 3. Frontend
- Cost panel source selector becomes:
  `[ C6 (Hermes) ] [ opencode ] [ claude code ] [ antigravity ] [ all ]`
  (default stays C6). It filters cost-table sections AND the flow series
  exactly as TASK4's picker does; `all` = sum of all four.
- Cost table gains a **claude code** section and an **antigravity** section
  (rows per model, each with its own project-as dropdown, in/out split,
  include-cache toggle — all existing machinery). These two sections render
  with a small note under the section header:
  `plan-based · $ shown = pay-per-token API-rate estimate` (both Claude Code
  and Antigravity run on plans; the $ is what the same tokens would cost at
  list API rates).
- Because of the prefix-stripping pricing rule, claude code rows show a $ out
  of the box (e.g. opus-5-5 at $4/$20) and antigravity gemini rows too —
  unlike opencode which defaults to `—`.
- Flow chart: follows the selected source (new sources' daily series); hover
  tooltip computes $ at the selected projection model's rates, per source.
- Per-day / Total KPIs follow selected source + projection, as in TASK4.

### 4. Safety
- All new sources opened read-only (jsonl = open(...,"r") only; the
  antigravity .db via `sqlite3 file:...?mode=ro` if you end up using it).
- The existing mtime-unchanged check (state.db + opencode.db) must still pass;
  the jsonl/db sources are read-only by construction.
- `test_api.py` — extend: /api/claudecode + /api/antigravity shape, claudecode
  models non-empty AND contains `claudecode:claude-opus-5-5` with billed
  formula correct, totals == sum of rows, both platform rows present, cost
  panel has claude code + antigravity sections + 5-button source picker in the
  frontend. Keep ALL existing checks.
- `verify_c6.py` — extend similarly (shape checks must pass even if
  antigravity has zero rows — it's empty-tolerant; claudecode must be
  non-empty). Keep all existing checks.

## Acceptance (real output, verbatim)
1. `python3 test_api.py` — full output, all pass.
2. `python3 verify_c6.py` — full output, all pass.
3. `curl /api/claudecode?days=all` and `curl /api/antigravity?days=all` —
   paste the JSON (first 40 lines each if long).
4. Browser evidence: (a) cost panel with source = "claude code" — opus-5-5
   row showing a $ out of the box with its note, (b) flow chart in claude code
   mode with hover tooltip showing $ estimate, (c) source picker showing all 5
   buttons. Screenshots to `docs/` (not browser-harness tmp — that doesn't
   deliver to Discord).
5. state.db + opencode.db mtimes unchanged; server still 0.0.0.0:8901.
6. Commit with a clear message; paste the hash.

Report: files changed, all test outputs verbatim, commit hash, deviations.
