# TASK6 — use Claude Code's REAL reported cost as primary (not list-rate estimate)

Follow-up to TASK5 (build on top; do NOT redo). Board live on 0.0.0.0:8901 —
keep it running, verify live. Same constraints (stdlib, read-only, 0.0.0.0).

## Why
Claude Code's local transcripts carry its OWN billed dollars, which differ from
pay-per-token list estimates. Verified live: 9 sessions, sum of per-session
`totalCostUSD` = **$25.70** (opus-4-8 $18.00, opus-5-5 $7.00, sonnet-5-5
$0.00). The board currently shows a list-rate ESTIMATE (~$31) — wrong as the
primary figure. Reported cost is the real bill; estimates stay as the
projection option only.

## Data (verified — parse these, don't guess)
In each `~/.claude/projects/*/*.jsonl` (including `subagents/*.jsonl`), some
lines are `type == "cost-state"` (top-level, NOT under message). Fields
(values may be JSON STRINGS — coerce):
- `totalCostUSD` — cumulative cost for that session
- `startTime` — epoch **milliseconds**
- `modelUsage` — JSON **string** → `{model: {inputTokens, outputTokens,
  thinkingTokens, cacheReadInputTokens, cacheCreationInputTokens, costUSD,
  webSearchRequests, ...}}` — cumulative for that session
- `hasUnknownModelCost` — bool (string "True"/"False") — if true the cost may
  undercount

## Changes

### 1. Backend — extend the existing claudecode scan
- Per session file (top-level OR subagent), take the LAST cost-state line
  (values are cumulative within a session; they are monotonic non-decreasing).
- Reported cost per model = SUM across sessions of
  `modelUsage[model].costUSD` from each session's last cost-state.
- Add to `/api/claudecode`:
  - per model: `reported_cost_usd` (float, 0.0 if the model has no cost-state
    data)
  - total: `reported_cost_usd` (sum), `sessions_with_reported_cost` (int),
    `has_unknown_model_cost` (bool, true if ANY session flagged it)
- Window semantics: attribute a session's reported cost to the local date of
  its `startTime` (ms); `days` filter keeps cost-states whose startTime is in
  window. Document: a session still running is attributed to its start day
  (known limitation, fine for v1).
- Token counts stay sourced from assistant-line `message.usage` (existing).
  cost-state token fields are NOT used for token totals (they can disagree with
  assistant-line accounting); cost-state is the cost source only.

### 2. Frontend — claude code cost section
- Each claude code row's DEFAULT displayed cost = **reported** (real $), e.g.
  `claude-opus-5-5 $7.00 · reported`. The row's project-as dropdown DEFAULT
  becomes `actual (reported)`; picking a real model from it switches that row
  (and the panel Total / per-day) to the pay-per-token list-rate estimate and
  marks it `→ <model> (estimate)`.
- Section note becomes:
  `reported cost = what Claude Code bills · pick a model in a row to see a pay-per-token estimate`
  (replace the old "estimate only" note for this section ONLY).
- Models with $0.00 / missing reported cost: show `— reported`, fall back to
  estimate as the default for that row (marked `(estimate)`), so a model with
  no cost-state data never looks like it was free.
- If `has_unknown_model_cost` is true for the window, add a small flag to the
  section header: `· partial (unknown-model cost)`.
- Total / per-day / flow hover for source = claude code use the REPORTED
  numbers by default (flow hover: `≈ $X reported` on days that have
  cost-states; on days without, fall back to estimate with the `estimate`
  marker). Antigravity source is UNCHANGED (no reported cost exists there —
  stays estimate-only, keep its existing note).
- `all` source: claude code rows contribute reported cost; other sources
  contribute their existing behavior.

### 3. Safety + tests
- All access read-only (jsonl `"r"` only); existing mtime checks unchanged.
- `test_api.py` — extend: reported_cost_usd fields present on models + total;
  `total.reported_cost_usd == sum(models.reported_cost_usd)`; independent
  cross-check: recompute the all-time sum by scanning the jsonl yourself in the
  test and compare within $0.01 (drift-tolerant: recompute, don't hardcode —
  the DB grows); `sessions_with_reported_cost` >= 1.
- `verify_c6.py` — extend with a reported-cost presence check; keep all existing.
- Keep every TASK5 check green.

## Acceptance (real output, verbatim)
1. `python3 test_api.py` full output, all pass.
2. `python3 verify_c6.py` full output, all pass.
3. `curl /api/claudecode?days=all` — paste JSON (models + total with
   reported_cost_usd).
4. Browser: screenshot of the cost panel in claude code mode showing the
   reported $ figures as default (should sum to ~$25.70 all-time / window)
   and one row projected onto another model showing the estimate marker.
   Save to `docs/` (NOT browser-harness tmp).
5. Server still 0.0.0.0:8901; mtime checks pass.
6. Commit; paste the hash.

Report: files changed, test outputs verbatim, commit hash, deviations.
