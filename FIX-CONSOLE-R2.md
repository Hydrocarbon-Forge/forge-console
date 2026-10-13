# FIX CONSOLE ROUND 2: bound the thread pool (root cause of the OOM)

Context: ROUND 1 (commit b747e9d) added `timeout = 60` to all three handlers +
`daemon_threads`. That caps how long an *idle* keep-alive thread lingers, but
does NOT stop accumulation under sustained load. Verified on the running
service: fresh restart (56 threads) climbed to 707 threads in 90s with only
real LAN pollers connected. A prior instance OOM-killed at ~1050 threads / 4.8G.

## Why (C6 diagnosis — VERIFY FIRST, note if real cause differs)
1. `ThreadingHTTPServer` spawns one OS thread per accepted connection, with NO
   upper bound and no queue cap.
2. The console is polled hard: home panel `setInterval` every 2s per open tab
   (web/app.js:335 `state.home.pollInterval`), flow every 5s, health every ~7s,
   from at least two LAN devices. Each `/api/home` poll also fans out to ~9
   internal `urllib` loopback calls against the embedded :8901 server
   (`_compute_home_tokens_aggregate` / `_home_executor`, server.py ~line 189+),
   each of which spawns ANOTHER thread in the embedded insights server.
   So per poll you get ~1 client thread + up to ~9 embedded threads.
3. `timeout = 60` (round 1) means a thread from a closed-but-keep-alive socket
   can linger up to 60s, so the pool never drains fast enough under this rate.
   Net: unbounded growth until OOM-kill, then Restart=always respawns, repeat.

Net effect on the UI: as thread count climbs, GIL thrash makes requests slow
→ proxy's 10s `urlopen` timeout fires → 502 on data endpoints → web/app.js
`.catch(() => null)` swallows it → home chip stuck at `-- tkns`, insights
panel blank. (That was the original symptom.)

## What to implement
1. **Bound the accept loop.** Replace raw `ThreadingHTTPServer` for the console
   (8903) and the embedded insights (8901) / ideas (8902) servers with a
   bounded worker-pool server: a `socketserver.ThreadingMixIn` subclass whose
   `process_request` submits to a `ThreadPoolExecutor(max_workers=N)` instead
   of `threading.Thread(...)` per connection. N generous but capped (e.g. 128
   for console, 64 for embedded boards — you can tune, document your choice).
   When the pool is saturated: accept the connection, then respond `503` +
   `Retry-After: 2` and close — do NOT queue unbounded. Keep `daemon_threads`
   behavior so shutdown is clean, keep `timeout = 60` from round 1 (or tighten
   to ~30 — your call, document it), keep `allow_reuse_address = True`.
   Reuse the existing `ReusableThreadingServer` base if it fits, or subclass it.
   This applies to: console server, embedded insights server, embedded ideas
   server, and the standalone `main()` paths in `insights/server.py` and
   `ideas/server.py` (they may run standalone too).
2. **Drain faster**: if you keep `timeout`, consider 30s (browsers re-poll
   every 2-7s anyway; idle keep-alives are useless to us past a few seconds).
3. **Reduce the fan-out thread cost (the real multiplier)**: the embedded
   :8901 handler for `/api/summary` etc. is already warm-cached. The home
   poller's 9-way `_home_executor.map` over loopback is the biggest thread
   source. If trivial: keep the 30s background refresher as the single source
   of freshness (it already exists: `_home_tokens_refresher_loop`) and make
   `get_home_tokens_aggregate()` serve from cache with a stale-serve path
   instead of always fanning out 9 loopback requests per poll. If NOT trivial,
   do NOT attempt it this round — the bounded pool is the load-bearing fix —
   and say so in your summary.
4. Do NOT touch `web/app.js` poll intervals unless asked (that's a separate
   product decision). Do NOT change the warm-cache data definitions (billed
   tokens = sum of models[].billed_tokens) — that was just verified correct.

## Constraints
- Python 3.14 stdlib only, no new deps.
- Commit as you go. Leave `COMPLETE-R2.md` (or `BLOCKED-R2.md` + reasons) in
  project root. Do NOT run systemctl / restart the service — C6 restarts.
- Backwards-compatible on wire: same endpoints, same JSON shapes. 503+Retry-After
  is the only new response and only under saturation.

## Verification (against the RUNNING service after C6 restarts)
- With 2 browser tabs + home poller running 10 min: `ls /proc/<pid>/task | wc -l`
  stays bounded (tens to low hundreds, FLAT — no climb), memory < 2G.
- Saturate the pool deliberately (e.g. 300 concurrent curl) → expect a mix of
  200s and 503s with `Retry-After` header, NOT a thread explosion; threads
  return to baseline after the burst ends.
- `GET /api/summary?days=1` on :8903 and :8901 direct: 200 in <2s, 3×.
- Home chip `#dest-chip-insights` shows `NNNk tkns`; Insights tab renders.
- Report: thread count before/after a 5-min poll, peak memory, what you chose
  for max_workers and why, and whether you did the fan-out reduction or deferred it.
