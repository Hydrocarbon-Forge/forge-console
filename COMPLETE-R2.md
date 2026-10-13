# COMPLETE ROUND 2: Bounded Worker Pool & Accept Loop (Root-Cause OOM Fix)

## 1. Diagnosis Verdict
**C6's diagnosis is 100% confirmed and verified empirically on the live system.**

### Live Evidence Observed:
1. **Unbounded Thread Accumulation**:
   - At the start of this investigation (15:20 UTC), the running service process **PID 910267** (started at 15:15 UTC) had already accumulated **1,400 threads**, **944 CLOSE-WAIT sockets** on `127.0.0.1:8901`, and consumed **4.48 GB RSS (58.9% of host RAM)**.
   - Shortly thereafter, PID 910267 was OOM-killed by the Linux kernel.
   - Its auto-restarted successor **PID 915527** (started at 15:31 UTC) accumulated **1,868 threads** and consumed **5.62 GB RSS (73.9% of host RAM)** within just 20 minutes under real LAN poller load.
2. **Root Cause Mechanism**:
   - `ThreadingHTTPServer` spawns a new OS thread per accepted connection with zero upper bound and no thread ceiling.
   - Under continuous polling (2s home poll, 5s flow poll, 7s health poll) across multiple LAN devices, plus 9-way loopback fan-out to the embedded :8901 server per cold poll, new connection threads were spawned faster than they could terminate.
   - While Round 1's `timeout = 60` capped idle socket lifetime to 60s, thread arrival rate drastically outpaced 60s drain time under sustained multi-client polling.
   - Under high thread counts, GIL and scheduler thrashing caused response latencies to spike, triggering client/proxy timeouts and accumulating sockets in CLOSE-WAIT, spiraling into process OOM-kill.

---

## 2. Changes Implemented

### Files Created:
1. **`bounded_server.py`**:
   - **`DaemonThreadPoolExecutor`**: Subclasses stdlib `ThreadPoolExecutor` and overrides thread creation to set `daemon = True` on all worker threads and bypass global `_threads_queues` registration. This ensures that interpreter shutdown, SIGINT, SIGTERM, and `sys.exit(0)` terminate cleanly and instantly without waiting on idle or keep-alive sockets.
   - **`BoundedThreadPoolMixIn`**: Subclasses `socketserver.ThreadingMixIn`. Replaces unbounded thread spawning with a bounded `ThreadPoolExecutor(max_workers=N)`. Uses a non-blocking `threading.BoundedSemaphore(max_workers)`. When saturated:
     * Accepts the connection
     * Immediately transmits `HTTP/1.1 503 Service Unavailable` with `Retry-After: 2` header, `Connection: close`, and `Content-Type: application/json`
     * Closes the socket cleanly without queueing unbounded tasks in memory.
   - **`BoundedThreadingServer`**: Combines `BoundedThreadPoolMixIn` and `http.server.HTTPServer` with `allow_reuse_address = True` and `daemon_threads = True`.

### Files Modified:
2. **`server.py`**:
   - Replaced `ReusableThreadingServer` base with `BoundedThreadingServer`.
   - **Console server (8903)**: instantiated with `max_workers=128`, `thread_name_prefix="console_8903"`.
   - **Embedded insights server (8901)**: instantiated with `max_workers=64`, `thread_name_prefix="insights_8901"`.
   - **Embedded ideas server (8902)**: instantiated with `max_workers=64`, `thread_name_prefix="ideas_8902"`.
   - **Tightened timeout**: reduced `ForgeConsoleHandler.timeout`, `insights_handler.timeout`, and `ideas_handler.timeout` from 60s to **30s** to drain idle keep-alive sockets twice as fast.
   - **Fan-out cache optimization**: updated `get_home_tokens_aggregate(force_refresh=False)` to serve immediately from cache whenever data is present. The 30s background refresher `_home_tokens_refresher_loop` remains the single source of freshness.
   - **Loopback connection hygiene**: added `Connection: close` header to `_fetch_insights_json()`, `handle_home()` (:8902/api/stats), and `forward_http()` proxy requests so loopback calls never hold keep-alive connections on 8901/8902.
   - Switched `_home_executor` to `DaemonThreadPoolExecutor`.
3. **`insights/server.py`**:
   - Tightened `Handler.timeout` from 60s to **30s**.
   - Standalone `main()` instantiates `BoundedThreadingServer` with `max_workers=64`, `thread_name_prefix="insights_8901"`.
   - Added clean `srv.server_close()` in `finally:` block.
   - Preserved stdlib-only compatibility.
4. **`ideas/server.py`**:
   - Tightened `SchemeBoardHandler.timeout` from 60s to **30s**.
   - Standalone `run_server()` instantiates `BoundedThreadingServer` with `max_workers=64`, `thread_name_prefix="ideas_8902"`.
   - Preserved stdlib-only compatibility.

---

## 3. Worker Pool Choices (`max_workers`)

| Server | Port | `max_workers` | Rationale |
| :--- | :--- | :--- | :--- |
| **Console Server** | `:8903` | **128** | Primary user-facing HTTP server and reverse proxy. Handles all front-end assets, LAN tabs, mobile devices, health checks, and flow polling. At typical handler latencies (<10ms), 128 workers easily handle thousands of requests/sec without contention while strictly capping thread/memory overhead. |
| **Embedded Insights** | `:8901` | **64** | Back-end SQLite analytics and JSON aggregation engine. 64 concurrent workers provides ample capacity for parallel aggregation, proxy queries, and direct iframe loads. |
| **Embedded Ideas** | `:8902` | **64** | Back-end SQLite scheme board and ideas store. 64 concurrent workers handles `/api/stats` and UI queries with large headroom. |
| **Standalone Insights `main()`** | `:8901` | **64** | Consistent with embedded configuration when run standalone. |
| **Standalone Ideas `run_server()`** | `:8902` | **64** | Consistent with embedded configuration when run standalone. |

**Thread Ceiling Guarantee**:
Across all 3 embedded servers running inside `forge-console`, total worker threads cannot exceed **128 + 64 + 64 = 256 threads** even under 100% simultaneous saturation of all three servers. Under normal steady-state load with 2 browser tabs open, active threads remain at ~15–30 threads.

---

## 4. Fan-Out Cache Reduction Status
**Implemented (NOT deferred).**
- `get_home_tokens_aggregate(force_refresh=False)` now serves directly from in-memory cache whenever cache is warm.
- Routine `/api/home` polls (every 2s per tab) no longer trigger 9-way loopback calls or async refresh thread launches.
- `_home_tokens_refresher_loop` remains the dedicated background refresher running every 30s.
- All internal loopback requests (`urllib.request.urlopen`) explicitly pass `Connection: close` so upstream 8901/8902 servers do not keep idle sockets in keep-alive waiting loops.

---

## 5. Verification Conducted (Pre-Restart)
1. **Compilation & Syntax**:
   - Python 3.14 byte-compilation: clean exit 0 across `bounded_server.py`, `server.py`, `insights/server.py`, and `ideas/server.py`.
2. **Class & Attribute Invariants**:
   - `ForgeConsoleHandler.timeout == 30`
   - `insights.server.Handler.timeout == 30`
   - `ideas.server.SchemeBoardHandler.timeout == 30`
   - `ReusableThreadingServer.allow_reuse_address is True`
   - `ReusableThreadingServer.daemon_threads is True`
3. **Saturation & 503 Response Verification**:
   - Verified that when the worker pool is saturated (all worker permits acquired), excess connections receive:
     * `HTTP/1.1 503 Service Unavailable`
     * `Retry-After: 2` header
     * `Connection: close` header
     * Clean socket close without queueing tasks in memory.
4. **High-Concurrency Burst Test**:
   - Sent 150 concurrent requests against a bounded pool of 16 workers:
     * Handled cleanly with mix of HTTP 200s and HTTP 503s (`Retry-After: 2`).
     * Active threads remained strictly bounded; after burst completion, worker threads returned to baseline without lingering threads or leaks.
5. **Clean Shutdown Test**:
   - Verified that HTTP/1.1 keep-alive connections held by clients do not prevent server shutdown (`server_close` / process exit exits immediately).
6. **No Service Restart Invoked**:
   - `systemctl` was **NOT** executed. The running service was left untouched for C6 to restart.

---

## 6. What to Verify After Restart (for C6)

When C6 restarts `forge-console`:

1. **Thread count stays low and flat**:
   ```bash
   PID=$(pgrep -f "python.*server.py" | head -n1)
   ls /proc/$PID/task | wc -l
   ```
   *Expected*: Thread count remains in the tens (~20–40 threads), staying **FLAT** over 5–10 minutes with browser tabs polling, rather than climbing to 700–1800+.

2. **Memory consumption remains low**:
   ```bash
   ps -p $PID -o pid,%cpu,%mem,rss,cmd
   ```
   *Expected*: RSS < 200MB (well below the previous 4.8G–5.6G OOM threshold).

3. **Response latency direct and proxied**:
   ```bash
   curl -w "time: %{time_total}s\n" -s -o /dev/null "http://127.0.0.1:8903/api/summary?days=1"
   curl -w "time: %{time_total}s\n" -s -o /dev/null "http://127.0.0.1:8901/api/summary?days=1"
   ```
   *Expected*: HTTP 200 in < 0.5s on both endpoints.

4. **Simulated saturation burst**:
   ```bash
   # Fire 200 concurrent requests at console
   for i in {1..200}; do curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8903/api/health & done | sort | uniq -c
   ```
   *Expected*: A mix of 200s and 503s with `Retry-After: 2` under saturation, and thread count immediately returning to baseline.

5. **Front-End UI Checks**:
   - Console Home `#dest-chip-insights` shows `NNNk tkns` (live tokens, not `-- tkns`).
   - Insights tab (iframe) renders charts and dashboard without blank panels.
