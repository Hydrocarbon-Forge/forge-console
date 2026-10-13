# FIX CONSOLE: thread pile-up → blank home/insights panels (2026-10-13)

## Symptom
- Home panel chips stuck at `-- tkns`, Insights tab renders nothing (both "insights" and "home" broken).
- `GET :8903/api/summary?days=1` → 502 after ~10s (proxy timeout).
- `GET :8901/api/summary?days=1` (direct, no proxy) → hangs past 30s (no response).
- Console process (single `python-scheme server.py` serving 8903 + embedded 8901 insights + 8902 ideas) had **~1435 threads** and ~59 CLOSE-WAIT sockets.

## C6's diagnosis — VERIFY THIS FIRST, note in your final summary if the real cause differs
1. `server.py` `ForgeConsoleHandler` (line ~360) sets `protocol_version = "HTTP/1.1"` (keep-alive) but **no socket `timeout`**. `insights/server.py` `Handler` (line ~1819) likely the same.
   → Every client that keeps a connection open (browsers, `pollInterval: 2`s home poller, curl sessions) pins **one thread in a blocking `recv()` forever**. Threads accumulate (1435 observed).
2. ~1400 idle threads hammering the GIL makes *every* handler request take 10–30s. The console's proxy uses `urlopen(timeout=10.0)` → the slow embedded :8901 handler misses it → **502** on all proxied data endpoints (`/api/summary`, `/api/opencode`, `/api/claudecode`, `/api/antigravity`, `/api/flow`, …).
3. Front-end `web/app.js` wraps every data fetch in `.catch(() => null)` → the 502 is swallowed → chips stay `-- tkns`, insights panel stays blank. (This is why it "silently" broke.)

So the panels are broken by: **missing handler socket timeout → thread leak → GIL thrash → proxy timeouts → front-end swallows the errors**.

## Fix (what to implement)
- Set a `timeout` on the request handlers so idle keep-alive connections close: `BaseHTTPRequestHandler.timeout` (class attr, e.g. `60`) on `ForgeConsoleHandler` and the embedded insights/ideas handlers. Confirm `daemon_threads = True` is set (it is, on the server classes).
- Confirm the embedded `insights` / `ideas` server classes get the same treatment (they're created in `server.py` around lines 1047–1074).
- Check `forge-office/server.js` (node, :8904) for the same class of issue; Node handles idle keep-alive itself, so likely no change — verify and say so.
- Do NOT redesign the warm-cache home aggregator or the proxy — the data layer is fine (endpoints return 200 with real data when the process isn't wedged).
- Optional (only if trivial and safe): a `threading.active_count()` guard/log line, or a startup log of handler timeout value, so the next wedge is diagnosable. Keep it minimal.

## Constraints
- Python 3.14 only. Vanilla stdlib, no new dependencies.
- Git: commit as you go (repo already init'd, repo-local identity set).
- **STOP before restarting the service.** C6 restarts `forge-console` separately. Do NOT run `systemctl`.
- Do not touch `web/app.js` unless the timeout fix alone is clearly insufficient — the front-end's silent-swallow is a known design choice (offline-ready), don't change behavior.

## Verification (run against the RUNNING service, then describe what a post-restart run should show)
- After code change + restart: with 2 browser tabs open and the home poller running for ~5 min, `ls /proc/<pid>/task | wc -l` stays low (tens, not thousands).
- `GET /api/summary?days=1` on :8903 returns 200 in <2s, repeated 3×.
- `GET /api/summary?days=1` on :8901 direct returns 200 in <2s.
- No new CLOSE-WAIT accumulation: `ss -tanp | grep -c CLOSE-WAIT` stays flat.
- Home chip `#dest-chip-insights` shows `NNNk tkns` (not `--`), Insights tab renders data.
- Leave a `COMPLETE.md` (or `BLOCKED.md` with reasons) in the project root as your stop marker, and end with a summary: what you verified about the diagnosis, what you changed, what to check after restart.
