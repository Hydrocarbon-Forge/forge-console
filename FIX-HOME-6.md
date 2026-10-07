# Fix Brief — TASK-HOME round 6: home load-time variance + 70.1M claudecode definition

Nathan reports: (a) home reload sometimes takes a few seconds longer than the
insights page to show token data, and it's a different amount each time;
(b) home all-time consistently differs from the insights board's "all sources"
number (board = 70.1M). C6 diagnosed BOTH with live measurements — verify
them yourself and note if they differ.

## Item 1 — load-time variance (cold-cache aggregation)

DIAGNOSIS (verified live 2026-10-07):
- `/api/home` → `get_home_tokens_aggregate()` (server.py) fans out to 9
  insights-engine endpoints and caches the result only **3.0s**
  (`_home_tokens_cache`, TTL check `now - timestamp < 3.0`).
- Per-endpoint latency (all-time): c6 0.00s, opencode 0.03s, claudecode
  0.03s, **antigravity 2.76s** (its engine-side scan is slow when cold).
- Observed `/api/home` timings: 2.42s (cold) then 0.00–0.08s (warm).
- Net: any home load/poll that lands just after the 3s TTL expires blocks on
  the full fan-out dominated by the 2.8s antigravity scan → "a few seconds,
  different each time" (depends on where in the 3s cycle + engine cache
  state you land).

FIX — make `/api/home` (and the home poll) never block on a cold aggregation:
1. **Background refresher**: a daemon thread in server.py that re-runs
   `get_home_tokens_aggregate()` every ~30–60s (reuse the existing lock +
   cache structures), so the cache is essentially always warm. First run at
   startup (warm on boot). Keep it tolerant: if a refresh fails, keep the
   last good data and retry next tick (never crash the refresher; the cache
   keeps serving stale-but-real values).
2. **TTL as safety net**: keep the existing "refetch if older than TTL" path
   but raise the TTL to ~60s so a direct request only triggers a synchronous
   fan-out if the refresher somehow fell behind — and even then only the
   stale path matters (consider: on a cold-cache direct hit, serve the last
   cached data immediately if it is < a few minutes old, and let the
   refresher catch up; only block synchronously when there is NO cache at
   all yet).
3. The client poll interval (home metrics polling in web/app.js) can stay as
   is — with the server always warm, every poll is fast. Don't poll faster
   than the data can meaningfully change (the token data is effectively
   static per engine scan).
4. Do NOT touch the insights ENGINE (8901) — its own caching is fine; the
   fix is entirely in the console server.

VERIFY: 10 consecutive `time curl /api/home` calls spanning >60s — all under
~200ms (cache warm), including calls deliberately spaced past the TTL. Show
the timings.

## Item 2 — claudecode definition (the 70.1M gap)

DIAGNOSIS (verified live): the board (insights/web/app.js `sourceBilled` /
`summaryForSource`) computes each non-C6 source as **sum of
`models[].billed_tokens`**; C6 as `summary.billed_tokens`. The console's
`_extract_source_billed()` (server.py) instead computes non-C6 sources as
`total.input_tokens + total.output_tokens` — identical for opencode and
antigravity, but for **claudecode** that field is a strict subset
(total in+out = 642,413 vs sum models.billed_tokens = 3,561,787; delta
2,919,374). All-time board total = 70.5M at measurement time (Nathan's
70.1M, live drift) vs home 67.6M.

FIX — make home use the BOARD'S definition exactly, in BOTH code paths:
1. **server.py `_extract_source_billed`**: for non-C6 sources, PREFER
   `sum(models[].billed_tokens)` when `models` is a non-empty list and the
   models carry `billed_tokens`; fall back to `total.input_tokens +
   total.output_tokens` only when the models array is missing/empty (defence
   against engine shape changes). C6 stays `summary.billed_tokens`.
2. **web/app.js client fallback `extractBilled`**: same preference order
   (models.billed_tokens sum → total in+out fallback), so the fallback path
   can't reintroduce the old definition if `/api/home` is unavailable.
3. **7d sparkline** (`activity_7d` daily rows in server.py): the board's
   daily view uses `row.billed_tokens || row.total_tokens` per row. If the
   daily rows from the engine carry `billed_tokens`, prefer that field
   (per row, per source) to stay consistent with the board; fall back to the
   current `in+out(+cache_write for c6)` formula when the field is absent.
   Check the actual shape of `/api/opencode|claudecode|antigravity` and
   `/api/activity` daily rows before coding (they are under
   `docs.daily[]`/`daily[]` — inspect them).
4. **verify_home_metrics.py**: update the expected-side computation to the
   board definition (sum models.billed_tokens for non-C6) so the assertion
   proves home == board-by-construction, then re-run it and show the new
   output (expect ~0% drift and a claudecode figure of ~3.5M).

The per-source breakdown line under the headline will now show claude ≈ 3.5M
instead of 0.6M — that is the board-consistent number, keep the same format.

## VERIFY (both items, one test port e.g. 8920)

- 10 timed `/api/home` curls as above (all fast, even across TTL boundaries).
- `python3 verify_home_metrics.py 8920` with the UPDATED board definition —
  drift ≤ 2% today + all-time, and claudecode ≈ 3.5M in both home and
  expected columns.
- Browser (unrendered tab, rAF dead — the round-4 scenario): headlines still
  settle on real values.
- Constraints: no 8903 bind, no service restarts (C6 restarts the live
  service after), no engine changes, no live-data writes, vanilla + stdlib,
  git commit in chunks, kill test ports, append verification to this file
  under `## C6 verification results`.
