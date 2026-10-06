# TASK3 — Cost clarity, projection, per-day cost

Board is live on 0.0.0.0:8901 — keep it running, verify against the live server.
All constraints from SPEC.md still apply: Python 3 stdlib only, read-only DB
(file:...?mode=ro), no LLM/network from backend, bind stays 0.0.0.0.

Context: `pricing.json` now has a `provider` field on every model (Anthropic,
OpenAI, Google, xAI, DeepSeek, Meta, Moonshot, Zhipu, "Alibaba (local)").
`/api/cost` rows and `/api/summary` expose `billed_tokens` (= in+out+cw).
Cache RE-READS (cache_read_tokens) are process traffic, never billable —
the focus of the cost story is input, output, and billable tokens.

## Features

### 1. Cost panel clarity (input/output front and center)
- In the cost table, split the token column into **in** and **out** (billable,
  = input+output+cache_write) with cache re-reads OUT of the default view.
- Add an opt-in checkbox/toggle: **"Include cache re-reads"** (default OFF).
  When on, each row's cost adds `cache_read_tokens × rate.cache_read` and the
  token column shows them (labeled, e.g. `+20.5M cr`). Default off because
  the focus is billable in/out.
- Row layout suggestion: `model | in | out | billable $ | project-as select | cache re-reads (muted)`.

### 2. Project usage onto another model (per-row, grouped dropdown)
- Each cost row gets a **project-as** select listing every model from the
  pricing file, grouped by `provider` via `<optgroup>` (alphabetical
  providers; within a provider alphabetical model name).
- Default selection = the row's own actual model.
- When a different model is chosen, that row's cost is recomputed client-side:
  `in_tokens × rate.input + out_tokens × rate.output` (+cache_read if the
  toggle is on), using the SELECTED model's rates (from /api/pricing).
  The row's cost cell shows the projected cost with a small marker (e.g. a
  dashed underline or `→ gpt-6-astra` suffix) so it's obvious it's projected.
- Panel totals (Total, Per day, Unpriced) recompute from the projected rows.
  A row projected onto a priced model counts as priced; if the actual model
  has no pricing entry, its row shows "—" until projected.
- The rates used are shown on hover/tooltip (in/out $/M of the selected model).

### 3. Daily cost on the token-flow graph (hover)
- The existing daily flow chart (input/output/cache-read per day) tooltip must
  show, for the hovered day: `in X · out Y · cr Z` AND the **estimated cost
  for that day in $** at the currently selected projection model's rates
  (the cost panel's selection; default = the dominant actual model). Label it
  clearly, e.g. `≈ $1.24 at gpt-5.6-sol rates`. Cache re-reads only enter the
  dollar figure when the "include cache re-reads" toggle is on.
- If no rates apply (unpriced, unprojected), show `≈ — (unpriced)`.

### 4. Window-aware cost-per-day for the selected model
- The global days selector (1d/7d/30d/90d/all) must drive the **est. cost /d**
  KPI and the cost panel per-day figure, computed for the selected model
  (or the panel's projection when set). Per-day = total in window / active
  days in window (active days = distinct session start dates, server already
  returns `per_day_usd` for the panel window — extend the server to accept and
  use the `days` param consistently, or compute client-side from
  `/api/cost?days=N` — your choice, but the KPI and panel must agree).
- KPI sublabel should read e.g. `at <model> · <N>d`.

### 5. Round-trip safety
- `POST /api/pricing` must preserve the `provider` field (and any future
  extra fields) — add a test: GET pricing, drop one rate, POST back, GET
  again, assert `provider` still present on all models.

## Acceptance (run and paste real output)
1. `python3 test_api.py` — extend the suite for the new checks (billed split,
   provider round-trip, per-day consistency across windows). All pass.
2. `python3 verify_c6.py` — untouched, still 23/23. Do NOT delete or weaken it.
3. `GET /api/cost?days=7` and `?days=30` return `per_day_usd` values that
   differ sensibly (7d window ≠ 30d window unless flat).
4. Browser: screenshot the cost panel showing in/out columns, a projected row
   (e.g. projected onto gpt-6-astra), and the flow chart tooltip with a $
   figure.
5. `state.db` mtime unchanged; server still bound to 0.0.0.0:8901.
6. Commit at the end with a clear message; paste the hash.

Report: files changed, all test outputs verbatim, commit hash, and any
deviations.
