# Fix Brief — TASK-HOME fix round 1 (C6 audit, 2026-10-06)

One verified bug found by C6's live audit of the HOME build:

## Item 1 — IDEAS launchpad always shows "0 ideas"

SYMTOM (verified in a live browser on a test instance): the home's IDEAS
destination tile chip reads "0 ideas" while the ideas board actually has 12
ideas (`curl 127.0.0.1:8902/api/stats` → `counts.total = 12`; same via the
console proxy `/api/proxy/scheme/api/stats`).

ROOT CAUSE (verified, but verify it yourself and note if different):
`server.py` ~line 421 computes the home aggregate's `ideas_count` as:
    stats_doc.get("total_ideas", stats_doc.get("ideas_count", 0))
but the scheme-board `/api/stats` payload has NO `total_ideas` / `ideas_count`
top-level key — the total lives at `counts.total`. So the lookup always falls
through to the `0` default. The frontend `web/app.js` has the same wrong
fallback chain (it reads `d.total_ideas || d.ideas_count || 0` from the stats
doc) — fix BOTH the server aggregate and the frontend fallback so the chip
shows the real count. Read the live `/api/stats` shape first (`curl
http://127.0.0.1:8902/api/stats`) — it is
`{ counts: { total, by_status: {...}, by_category: {...}, seeded_count },
top_opportunities: [...] }`.

SCOPE: minimal. Only this one metric. Do not rework anything else.

VERIFY: on a fresh test port (e.g. PORT=8912, do NOT bind 8903, do NOT
restart the live service, do NOT touch live engine data):
1. `curl -s localhost:<port>/api/home` → `ideas_count` equals the
   `counts.total` from `127.0.0.1:8902/api/stats` (both live values, compare
   in one script).
2. Browser: home IDEAS tile chip shows the real count (not "0 ideas").
3. `git commit` the fix. Kill the test port before finishing.
