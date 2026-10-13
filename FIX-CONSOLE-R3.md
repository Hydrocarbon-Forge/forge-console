# FIX-CONSOLE-R3 — Kill the claudecode/antigravity re-scan storm

## Symptoms (measured 2026-10-13 by C6)
- `GET :8901/api/summary?days=30` = 19.1s; `GET :8903/api/summary?days=all` = 502 after 10s
- `/api/home` by_source shows `claudecode: None`; home totals silently understated
- Console process at ~100% CPU continuously

## Root causes (diagnosed by agy 2026-10-13, spot-verified by C6 — VERIFY THEM, note if the real cause differs)
1. **Un-cached 750 MB file scans per request.** `insights/server.py:1904-1907` explicitly bypasses the `cached()` helper for the `claudecode` and `antigravity` endpoints (`# TASK5: full re-scan per request`), while c6/opencode/cost/opencode endpoints use it. `scan_claudecode` walks `~/.claude/projects` (now 756 MB, ~985 .jsonl files) per call (~2-4s), `scan_antigravity` ~2s.
2. **Collector re-triggers every 5s.** `collector.py:175-181` and `:204-211` call `http://127.0.0.1:8901/api/claudecode?days=1` and `/api/antigravity?days=1` with `timeout=0.8` — the client aborts, the server keeps scanning to completion, so the process is permanently scanning.
3. **Fanout amplification + silent drop.** `server.py:191-207` (home aggregator, 9-way loopback fanout every 30s) hits both endpoints concurrently; `_fetch_insights_json` (`server.py:167`) times out at 5.0s and returns None (`:170-172`); `_compute_home_tokens_aggregate` sums with `sum(v for v in ... if v is not None)` (`server.py:219, 227`) silently dropping None sources.
4. **Proxy timeout mismatch.** `server.py:865` forwards to :8901 with `timeout=10.0` → 502 whenever the upstream is mid-scan; handler timeouts are 60s (R1).

## Required changes (ranked)
1. `insights/server.py:1904-1907` — route `build_claudecode` and `build_antigravity` through the existing `cached()` helper like the other endpoints. 60s TTL (matches the board's always-warm pattern). Do NOT change the scan logic itself.
2. `collector.py:175-181, 204-211` — stop the 5s loopback pings to `/api/claudecode` and `/api/antigravity`. Preferred: read the values directly from `server.py`'s in-memory `_home_tokens_cache` if that's importable/clean; otherwise a lightweight mtime-based check. The 0.8s-timeout + server-side-keeps-going pattern must go.
3. `server.py:167` — `_fetch_insights_json` timeout 5.0 → 15.0.
4. `server.py:219, 227` — don't silently drop None sources from totals: fall back to that source's last-known cached value (from `_home_tokens_cache` or equivalent) and mark the aggregate degraded (e.g. include `"degraded": ["claudecode"]` in the payload when any source fell back). Keep the payload shape backward-compatible.
5. `server.py:865` — `forward_http` proxy timeout 10.0 → 30.0 (matches handler timeouts).

## Constraints
- Python 3.14 stdlib only. No new dependencies.
- No changes to `web/` (app.js, index.html, anything in web/).
- Do NOT run systemctl, do NOT restart the service — C6 restarts after you finish.
- Commit as you go. Leave `COMPLETE-R3.md` (or `BLOCKED-R3.md` with reasons) in the project root as your stop marker.
- Verify each root cause claim against the code before editing; if the real cause differs, note it in COMPLETE-R3.md.

## Verification (what you CAN do without restarting the service)
- `python3 -m py_compile` on every touched file.
- Standalone: import/execute the cached build path for `claudecode` and `antigravity` twice back-to-back — second call must hit the cache (age > 0) and be <100ms.
- Time a cold `scan_claudecode` + `scan_antigravity` once to confirm the baseline.
- Show the collector no longer pings 8901 for tokens (grep the changed code path).
- Do NOT hammer the live service; C6 verifies live behavior after restart.

## End with a summary:
diagnosis verdict (confirmed/differs + why), files changed, TTL choice, collector change approach, and what C6 should verify post-restart (thread count flat under poller load, `/api/home` by_source with claudecode non-None within ~1 min of restart, no 502 on `days=all`, CPU < 50% at idle).
