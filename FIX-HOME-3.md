# Fix Brief — TASK-HOME round 3: metric definition + office redirect (C6, 2026-10-06)

Nathan called out two things. Fix both.

## Item 1 — Home token metrics disagree with the insights board (DEFINITION bug)

SYMPTOM (verified): home "ALL-TIME TOKENS" shows ~136.6M while the insights
board with range=all + source=all shows ~55–57M billed. They are different
metrics, not a data error:

- Home currently: `/api/summary?days=3650` (C6/hermes sessions ONLY)
  `total_tokens` = fresh input + output + cache re-reads. Cache re-reads
  dominate (~114M of 136.6M) — that's the model re-reading its own cached
  context; the insights board explicitly labels that "not billable".
- Insights board "all sources · all time" KPI "TOKENS (BILLABLE)" =
  SUM of billed tokens across ALL FOUR harnesses, where billed =
  fresh input + output + cache WRITES (cache reads excluded):
  - C6: `GET /api/summary?days=all` → `billed_tokens`
  - opencode: `GET /api/opencode?days=all` → `total` (input+output; no
    cache-write field)
  - claude code: `GET /api/claudecode?days=all` → `total`
  - antigravity: `GET /api/antigravity?days=all` → `total`
  (all from the insights engine, verified live; `?days=all` is supported on
  the per-source endpoints too.)

FIX — make home show the SAME metric as the insights board "all" source so
the two surfaces agree by construction (verified rule: match metric
definitions, not numbers):
- Both home token metrics (TODAY and ALL-TIME) become **billable tokens,
  all four sources combined**: today = each endpoint with `?days=1`,
  all-time = `?days=all`. Label them accordingly, e.g.
  "TODAY · BILLED (ALL SOURCES)" / "ALL-TIME · BILLED (ALL SOURCES)" —
  drop the "3650D WINDOW" label (we now query `?days=all`, true all-time).
- Keep the sub-line honest: show a compact breakdown so the number is
  explainable at a glance, e.g. `c6 22.3M · opencode 2.5M · claude 0.6M ·
  agy 29.6M` (live values, per-source, from the same four fetches).
- Keep or drop the cache-re-read count as a small tertiary line only if it
  stays clean (optional; the billed figure is the headline).
- Do this in `/api/home` (server-side aggregation, new keys e.g.
  `billed_today_by_source` / `billed_alltime_by_source` with a `total` and
  per-source map) AND/OR client-side — your call, but the four fetches must
  be cheap (small JSON, same-origin) and tolerant to a source being down
  (sum whatever came back, mark the missing one in the breakdown as `—`).
- The 7-day sparkline in the COMPUTE ENGINE card (added in round 2, if
  present) should then show the same billable-all-sources series if cheap to
  derive (`?days=7` per source, summed per day — the per-source `daily`
  arrays make this straightforward); if that gets messy, keep the sparkline
  on C6 billed and label it `c6 billed · 7d`.
- VERIFY: one script that fetches the four per-source endpoints +
  `/api/summary` for days=1 and days=all, computes the two sums, and asserts
  `/api/home` (or the home page's displayed values) match within a small
  live-drift tolerance (these numbers move as agents run — assert within
  e.g. 2%, not exact equality).

## Item 2 — OFFICE must REDIRECT, not iframe

SYMPTOM: home + nav treat Office as an embedded iframe pane
(`http://<host>:8904/`), like insights/ideas. Nathan wants the office to
**launch as a top-level navigation** instead — it's a full app (virtual
office + trading floor), not a pane.

FIX:
- The OFFICE nav tab becomes a **redirect**: clicking it (or visiting
  `#/office`) does `location.href = "http://" + location.hostname + ":8904/"`
  (keep the LAN-friendly hostname logic). It should look like an external
  destination in the nav (a small ↗ indicator is fine) — it no longer
  switches to an in-console pane.
- Remove the office iframe pane entirely (no orphan pane, no lazy-init of a
  pane that can't be shown). Keyboard `6` = redirect. `?` overlay updated.
- The home's OFFICE launchpad tile + the OFFICE TREASURY "LAUNCH OFFICE →"
  action also redirect top-level (same URL).
- Verify: on the test port, clicking/JS-invoking the office nav triggers a
  navigation to `http://127.0.0.1:8904/` (you can verify by stubbing/
  intercepting `location` in the test browser, or by asserting the handler
  code path + a real click in your browser check). Confirm the other five
  destinations still behave (panes in-console).

## Constraints (same as before)

No 8903 bind, no service restarts (C6 restarts the live service afterward),
no touching live engine data, vanilla JS + stdlib, test port of your choice
(not 8910/8911 — those may be stale; pick e.g. 8913), git commit in chunks,
kill your test server before finishing, append verification results (curl
snippets + the assertion script output) to this file under
`## C6 verification results`.
