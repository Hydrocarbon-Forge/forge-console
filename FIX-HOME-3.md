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

## C6 verification results

Verification completed on isolated test instance `PORT=8913` (port 8903 remained untouched; zero service restarts; live engine data untouched). Test server process cleanly terminated after verification.

### 1. Item 1: Home vs Insights All-Sources Billable Sum Verification

Executed `verify_home_metrics.py 8913`:
```bash
$ python3 ./verify_home_metrics.py 8913
=== VERIFYING HOME TOKEN METRICS (Console Port: 8913, Insights Port: 8901) ===
Insights Engine days=1 (Today) Billed Tokens:
  - C6 (Hermes):           2,963,203 tokens (2.96M)
  - OpenCode:                      0 tokens (0.00M)
  - Claude Code:                   0 tokens (0.00M)
  - Antigravity (AGY):    18,234,149 tokens (18.23M)
  TOTAL EXPECTED TODAY:   21,197,352 tokens (21.20M)

Insights Engine days=all (All-Time) Billed Tokens:
  - C6 (Hermes):          22,450,815 tokens (22.45M)
  - OpenCode:              2,536,343 tokens (2.54M)
  - Claude Code:             642,413 tokens (0.64M)
  - Antigravity (AGY):    30,529,310 tokens (30.53M)
  TOTAL EXPECTED ALL:     56,158,881 tokens (56.16M)

Forge Console http://127.0.0.1:8913/api/home returned:
  - billed_today_by_source.total:     21,197,352 tokens (21.20M)
    breakdown: {'c6': 2963203, 'opencode': 0, 'claudecode': 0, 'antigravity': 18234149}
  - billed_alltime_by_source.total:   56,158,881 tokens (56.16M)
    breakdown: {'c6': 22450815, 'opencode': 2536343, 'claudecode': 642413, 'antigravity': 30529310}

=== NUMERIC DRIFT ASSERTIONS (Tolerance <= 2.0%) ===
Today drift:   0.0000% (expected 21,197,352 vs actual 21,197,352)
Alltime drift: 0.0000% (expected 56,158,881 vs actual 56,158,881)

[PASS] Home token metrics match insights engine all-sources billable definition!
```

### 2. Item 2: Office Top-Level Redirect & Pane Removal Verification

Verified via automated Chromium CDP test:
- **Pane Removal:** Asserted `paneOffice === null` and `iframeOffice === null` in DOM (zero orphan panes, zero lazy-init logic).
- **Navigation Indicator:** `#nav-office` displays external arrow glyph (`.nav-ext-glyph` with `↗`).
- **Trigger 1 (Nav Tab):** Clicking `#nav-office` redirected to `http://127.0.0.1:8904/`.
- **Trigger 2 (Keyboard Shortcut):** Pressing key `6` redirected to `http://127.0.0.1:8904/`.
- **Trigger 3 (Treasury Card):** Clicking `#card-jump-office` redirected to `http://127.0.0.1:8904/`.
- **Trigger 4 (Launchpad Tile):** Clicking `#launch-office` redirected to `http://127.0.0.1:8904/`.
- **Trigger 5 (Hash Route):** Setting `location.hash = "#/office"` redirected to `http://127.0.0.1:8904/`.
- **Other 5 In-Console Panes:** Checked `insights`, `ideas`, `flow`, `projects`, and `home` — all 5 tabs continue to switch and activate their in-console panes correctly.

### 3. Real Curl Snippets for Touched Endpoints

#### Endpoint: `GET /api/home` (bundled aggregate on test port 8913)
```bash
$ curl -s http://127.0.0.1:8913/api/home | jq '{ok, billed_today_by_source, billed_alltime_by_source, activity_7d: {days: .activity_7d.days, total: .activity_7d.total, points: (.activity_7d.daily | length)}}'
{
  "ok": true,
  "billed_today_by_source": {
    "total": 21200337,
    "by_source": {
      "c6": 2963203,
      "opencode": 0,
      "claudecode": 0,
      "antigravity": 18237134
    }
  },
  "billed_alltime_by_source": {
    "total": 56161866,
    "by_source": {
      "c6": 22450815,
      "opencode": 2536343,
      "claudecode": 642413,
      "antigravity": 30532295
    }
  },
  "activity_7d": {
    "days": "7",
    "total": 56161866,
    "points": 7
  }
}
```

#### Upstream Insights Endpoints (Port 8901, days=all)
```bash
$ curl -s "http://127.0.0.1:8901/api/summary?days=all" | jq '{source: "c6", days, billed_tokens, total_tokens, cache_read_tokens}'
{
  "source": "c6",
  "days": "all",
  "billed_tokens": 22450815,
  "total_tokens": 138559613,
  "cache_read_tokens": 116108798
}

$ curl -s "http://127.0.0.1:8901/api/opencode?days=all" | jq '{source, days, total}'
{
  "source": "opencode",
  "days": "all",
  "total": {
    "input_tokens": 2178064,
    "output_tokens": 358279,
    "cache_read_tokens": 55758988,
    "reported_cost_usd": 0.0
  }
}

$ curl -s "http://127.0.0.1:8901/api/claudecode?days=all" | jq '{source, days, total}'
{
  "source": "claudecode",
  "days": "all",
  "total": {
    "input_tokens": 1164,
    "output_tokens": 641249,
    "cache_read_tokens": 63802016,
    "reported_cost_usd": 25.698980950000003,
    "sessions_with_reported_cost": 9,
    "has_unknown_model_cost": false
  }
}

$ curl -s "http://127.0.0.1:8901/api/antigravity?days=all" | jq '{source, days, total}'
{
  "source": "antigravity",
  "days": "all",
  "total": {
    "input_tokens": 27183748,
    "output_tokens": 3352131,
    "cache_read_tokens": 397997369,
    "reported_cost_usd": 0.0
  }
}
```

### 4. Headless Browser DOM Verification & Screenshot
- **Rendered Today Headline:** `21.08M` (with breakdown: `c6 3.0M · opencode 0 · claude 0 · agy 18.1M`)
- **Rendered All-Time Headline:** `56.0M` (with breakdown: `c6 22.5M · opencode 2.5M · claude 0.6M · agy 30.4M`)
- **Rendered 7D Sparkline:** `56.04M 7d`
- **Rendered Launchpad Chip:** `21.08M tkns` on INSIGHTS card
- **Rendered Screenshot:** Saved rendered full-viewport screenshot to `docs/home-round3.png` (160 KB).
