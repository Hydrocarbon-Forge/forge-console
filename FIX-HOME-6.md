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

## C6 verification results

Verification performed on test port 8920 on 2026-10-07 without binding port 8903, modifying engines, or restarting live services. Test port 8920 was cleanly terminated after test completion.

### 1. 10 Timed `/api/home` Curls Across TTL Boundaries (>60s Span)

Test: Spanned 72.1 seconds covering both the 30s background refresher interval and the 60s TTL boundary.

```
Starting 10 timed calls to http://127.0.0.1:8920/api/home spanning >60s...
Call  1 | T+  0.0s | Latency:   4.53 ms | Status: 200 | Bytes: 13652
Call  2 | T+  5.0s | Latency:   2.78 ms | Status: 200 | Bytes: 13652
Call  3 | T+ 10.0s | Latency:   7.17 ms | Status: 200 | Bytes: 13652
Call  4 | T+ 20.0s | Latency:   2.66 ms | Status: 200 | Bytes: 13652
Call  5 | T+ 32.0s | Latency:   2.62 ms | Status: 200 | Bytes: 13651 (post-30s background refresh)
Call  6 | T+ 40.0s | Latency:   3.01 ms | Status: 200 | Bytes: 13653
Call  7 | T+ 50.0s | Latency:   5.13 ms | Status: 200 | Bytes: 13652
Call  8 | T+ 62.0s | Latency:  22.93 ms | Status: 200 | Bytes: 13653 (post-60s TTL boundary)
Call  9 | T+ 67.1s | Latency:  18.09 ms | Status: 200 | Bytes: 13653
Call 10 | T+ 72.1s | Latency:  11.76 ms | Status: 200 | Bytes: 13645

Finished 10 calls in 72.1s.
Max latency: 22.93 ms (all < 200 ms: True)
```

Result: Cache is permanently warm. No request ever blocked on the cold antigravity scan (~2.4s).

### 2. Metric Drift and Board Definition Alignment (`verify_home_metrics.py 8920`)

Ran `python3 verify_home_metrics.py 8920` with updated board definition (`sum(models[].billed_tokens)`):

```
=== VERIFYING HOME TOKEN METRICS (Console Port: 8920, Insights Port: 8901) ===
Insights Engine days=1 (Today) Billed Tokens:
  - C6 (Hermes):           2,114,864 tokens (2.11M)
  - OpenCode:                      0 tokens (0.00M)
  - Claude Code:                   0 tokens (0.00M)
  - Antigravity (AGY):    15,865,599 tokens (15.87M)
  TOTAL EXPECTED TODAY:   17,980,463 tokens (17.98M)

Insights Engine days=all (All-Time) Billed Tokens:
  - C6 (Hermes):          25,961,956 tokens (25.96M)
  - OpenCode:              2,536,343 tokens (2.54M)
  - Claude Code:           3,561,787 tokens (3.56M)
  - Antigravity (AGY):    39,047,859 tokens (39.05M)
  TOTAL EXPECTED ALL:     71,107,945 tokens (71.11M)

Forge Console http://127.0.0.1:8920/api/home returned:
  - billed_today_by_source.total:     17,966,347 tokens (17.97M)
    breakdown: {'c6': 2114864, 'opencode': 0, 'claudecode': 0, 'antigravity': 15851483}
  - billed_alltime_by_source.total:   71,093,829 tokens (71.09M)
    breakdown: {'c6': 25961956, 'opencode': 2536343, 'claudecode': 3561787, 'antigravity': 39033743}

=== NUMERIC DRIFT ASSERTIONS (Tolerance <= 2.0%) ===
Today drift:   0.0785% (expected 17,980,463 vs actual 17,966,347)
Alltime drift: 0.0199% (expected 71,107,945 vs actual 71,093,829)

[PASS] Home token metrics match insights engine all-sources billable definition!
```

Key points:
- Claude Code all-time billed tokens: 3,561,787 tokens (~3.56M) in both expected and home payload.
- All-time drift: 0.0199% (well within 2.0% live drift threshold).
- Today drift: 0.0785% (well within 2.0% live drift threshold).

### 3. Browser Unrendered Tab Verification (CDP Headless Chromium)

Test: Tab 1 loaded `http://127.0.0.1:8920/#pane-home`, deactivated and forced into background by activating Tab 2.
- CDP confirmed `document.hidden === true` and `visibilityState === 'hidden'`.
- Scheduler check confirmed `requestAnimationFrame` was frozen (`rafFired: False`) and fallback timer fired (`timerFired: True`).
- Headline values and per-source breakdown settled on real values:
  - `home-tokens-today`: `17.98M` (breakdown: `c6 2.1M · opencode 0 · claude 0 · agy 15.9M`)
  - `home-tokens-alltime`: `71.1M` (breakdown: `c6 26.0M · opencode 2.5M · claude 3.6M · agy 39.1M`)
  - `home-trading-equity`: `$196.01`
- None remained stuck at `--` or `—`.
- Claude breakdown shows `claude 3.6M` consistent with the insights board.
