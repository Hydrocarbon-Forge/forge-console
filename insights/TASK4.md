# TASK4 — opencode usage as its own platform + cost projection picker

Follow-up to TASK3 (implement AFTER TASK3's features are done). Board live on
0.0.0.0:8901 — keep it running, verify live. Same constraints as always
(stdlib only, read-only DBs, 0.0.0.0 bind).

## New data source: opencode
opencode v2 keeps its own store: `~/.local/share/opencode/opencode.db`
(read-only, `file:...?mode=ro`). Do NOT modify it.

Relevant tables (already inspected):
- `session_message(id, session_id, type, seq, time_created, data JSON)` —
  type='assistant' rows have `data.tokens = {input, output, reasoning,
  cache:{read, write}}`, `data.cost`, `data.model = {id, providerID, variant?}`.
  This is the BEST per-model source.
- `session_v2(...)` — per-session totals `tokens_input/output/reasoning/
  cache_read/cache_write`, `cost`, `model` (JSON or NULL for older sessions),
  `time_created` (ms epoch).
- `workspace(provider, binding, last_used_at)`.

Model labels: parse `data.model` JSON → `opencode:<id>` (e.g.
`opencode:muse-spark-1.3-contributor-free`, `opencode:longcat-2.5-preview-free`).
If a message has no model info, fall back to its session's `session_v2.model`;
if still unknown, `opencode:unknown`.

## Features

### 1. Backend: `/api/opencode`
Return:
```json
{
  "source": "opencode",
  "sessions": <count of session_v2 rows in window>,
  "models": [ {"model": "opencode:<id>", "sessions": n,
               "input_tokens": .., "output_tokens": .., "reasoning_tokens": ..,
               "cache_read_tokens": .., "cache_write_tokens": ..,
               "billed_tokens": in+out+cw, "reported_cost_usd": sum(data.cost)} ],
  "daily": [ {"date": "YYYY-MM-DD", "input_tokens": .., "output_tokens": ..,
              "cache_read_tokens": ..} ],
  "total": { "input_tokens": .., "output_tokens": ..,
             "cache_read_tokens": .., "reported_cost_usd": .. }
}
```
- Window via the same `days` param (1/7/30/90/all) using message
  `time_created` (ms). daily zero-filled like /api/activity.
- Aggregate from `session_message` where type='assistant' (per-message model +
  tokens are authoritative); keep a read-only connection to the opencode DB
  (a second `open_ro` for that file; handle missing file gracefully ->
  200 with empty shapes, never 500).
- Add a `source='opencode'` row to `/api/platforms` (sessions, messages,
  billable tokens) so opencode shows up alongside discord/cli in the platform
  table with its own total.

### 2. Cost panel: opencode as its own section + projection picker
- Cost table gets an **opencode** section (or clearly-grouped rows): one row
  per `opencode:<model>` with its own in/out and its own project-as dropdown
  (same grouped-by-provider dropdown machinery from TASK3). So you can answer
  "what would opencode's usage cost at claude-opus-5.5 rates?".
- Add a top-level **usage source** selector in the cost panel:
  `[ C6 (Hermes) ] [ opencode ] [ all ]` (default C6). It filters the cost
  table rows AND the flow-chart series:
  - C6 → the existing Hermes daily series (as today)
  - opencode → the opencode daily series from /api/opencode
  - all → combined
- The flow-chart hover (TASK3's per-day $ estimate) must compute at the
  selected projection model's rates for WHATEVER source is selected, and the
  panel's Total / Per-day figures follow the selected source + projection.
- opencode rows are priced exactly like Hermes rows (billable in/out × rates;
  cache re-reads only when the opt-in toggle is on). `opencode:` prefix must
  NOT match any pricing entry by itself — opencode models are free-tier via
  the opencode-go provider, so they are unpriced by default and only get a
  number when projected onto a priced model.

### 3. Safety
- Both DBs opened `?mode=ro`; mtime of BOTH `~/.hermes/state.db` and
  `~/.local/share/opencode/opencode.db` must be unchanged after the API
  batch (extend the existing mtime check to both files).
- `verify_c6.py` — extend with: `/api/opencode` shape check, models non-empty,
  totals == sum of rows, platform row present. Keep all existing checks.
- `test_api.py` — extend likewise.

## Acceptance (real output, verbatim)
1. `python3 test_api.py` all pass (extended).
2. `python3 verify_c6.py` all pass (extended).
3. `curl /api/opencode?days=all` — paste the JSON (or first 40 lines).
4. Browser: screenshot (a) the cost panel in "opencode" source mode with one
   row projected onto a frontier model (e.g. claude-opus-5.5) showing a $
   total, (b) the flow chart in opencode mode with the hover tooltip showing
   that day's tokens and $ estimate.
5. Both DB mtimes unchanged; server still 0.0.0.0:8901.
6. Commit with a clear message; paste the hash.

Report: files changed, all test outputs verbatim, commit hash, deviations.
