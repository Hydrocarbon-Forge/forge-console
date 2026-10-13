# COMPLETE: Console Thread Pile-up & Socket Timeout Fix

## 1. Diagnosis Verdict
**Diagnosis confirmed: C6's diagnosis is 100% accurate.**

### Detailed verification:
1. **Missing socket timeout on HTTP/1.1 keep-alive handlers**:
   - `server.py` `ForgeConsoleHandler` set `protocol_version = "HTTP/1.1"`, enabling HTTP keep-alive by default, but left `BaseHTTPRequestHandler.timeout = None`.
   - `insights/server.py` `Handler` and `ideas/server.py` `SchemeBoardHandler` also had `timeout = None`.
   - Under HTTP/1.1 keep-alive, `BaseHTTPRequestHandler.handle()` continuously loops on `handle_one_request()`. When an HTTP client (browser, curl session, home poller) stops sending data, `self.rfile.readline()` blocks in `socket.recv()` with no timeout.
   - Because `ThreadingHTTPServer` spawns a new OS thread for every incoming connection, each persistent connection held an OS thread open indefinitely.
2. **Current state of running service (PID 889912)**:
   - Verified thread count: peaked at ~438 threads (oscillating ~173–397 threads).
   - Verified established connections: ~60–119 active ESTAB connections on port 8903 from LAN clients (e.g. 192.168.1.202).
   - Verified CLOSE-WAIT accumulation: ~259–277 sockets in CLOSE-WAIT state on port 8901.
   - Mechanism: Massive thread accumulation created intense GIL and scheduler thrashing. Requests to 8901 that normally take <100ms took 10–30s or timed out. When the console proxy's `urllib.request.urlopen(..., timeout=10.0)` timed out and severed the client connection, the still-running handler thread on 8901 was left with a socket in CLOSE-WAIT.
3. **Front-end silent failure**:
   - `web/app.js` wraps API fetches in `.catch(() => null)`. When the proxy timed out and returned 502 Bad Gateway, the errors were silently swallowed, keeping chip values at `-- tkns` and leaving panels blank.
4. **Forge Office (`forge-office/server.js`)**:
   - Verified `forge-office` (Node.js on :8904, PID 6438). Node handles keep-alive connections on its single-threaded event loop with built-in `server.keepAliveTimeout` (5s default). Verified `ls /proc/6438/task | wc -l` is stable at 11 threads (libuv threadpool) with only 4 active sockets. No changes required.

---

## 2. Changes Implemented

### Files modified:
1. **`server.py`**:
   - Added class attribute `timeout = 60` to `ForgeConsoleHandler`.
   - Explicitly configured `insights_handler.timeout = 60` and `ideas_handler.timeout = 60` upon dynamic import in `main()`.
   - Replaced raw `ThreadingHTTPServer` instantiations for `insights_server` and `ideas_server` with `ReusableThreadingServer` (`allow_reuse_address = True`, `daemon_threads = True`).
   - Added thread count monitoring warning to `collector_loop()` (`if active_t > 100: log_collector(...)`).
   - Added startup logging displaying handler timeout values for console (8903), insights (8901), and ideas (8902).
2. **`insights/server.py`**:
   - Added class attribute `timeout = 60` to `Handler`.
   - Set `srv.daemon_threads = True` in standalone `main()`.
   - Updated standalone startup log to report `timeout=60s`.
3. **`ideas/server.py`**:
   - Added class attribute `timeout = 60` to `SchemeBoardHandler`.
   - Set `httpd.daemon_threads = True` in `run_server()`.
   - Updated standalone startup log to report `timeout=60s`.

---

## 3. Verification Conducted

1. **Python syntax & compilation**:
   - Compiled with Python 3.14 (`python3 -m py_compile server.py insights/server.py ideas/server.py`): exited 0 cleanly.
   - Class assertions verified: `ForgeConsoleHandler.timeout == 60`, `insights.server.Handler.timeout == 60`, `ideas.server.SchemeBoardHandler.timeout == 60`, `ReusableThreadingServer.daemon_threads is True`.
2. **Keep-alive timeout behavior test**:
   - Executed scratch verification test simulating HTTP/1.1 persistent connection with `timeout = 2`.
   - Verified that after 2.5s of inactivity, the server socket handler raised `TimeoutError`, cleanly terminated the worker thread (active thread count decremented), and closed the socket connection (client received EOF `b''`).
3. **Running service responsiveness (PID 889912)**:
   - Repeated 3× direct check: `GET :8901/api/summary?days=1` returned HTTP 200 in ~0.27s – 0.33s.
   - Repeated 3× proxied check: `GET :8903/api/summary?days=1` returned HTTP 200 in ~0.45s – 0.59s.
4. **Service restart constraint**:
   - As instructed, the running service was **NOT** restarted and `systemctl` was **NOT** invoked.

---

## 4. Post-Restart Verification Steps (for C6)

When C6 restarts `forge-console`:
1. **Thread count stays low**:
   ```bash
   PID=$(pgrep -f "python.*server.py" | head -n1)
   ls /proc/$PID/task | wc -l
   ```
   *Expected*: Thread count remains low (typically ~15–30 threads, not hundreds or thousands), even with browser tabs open and home poller querying every 2 seconds.
2. **Response latency**:
   ```bash
   curl -w "time: %{time_total}s\n" -s -o /dev/null "http://127.0.0.1:8903/api/summary?days=1"
   curl -w "time: %{time_total}s\n" -s -o /dev/null "http://127.0.0.1:8901/api/summary?days=1"
   ```
   *Expected*: HTTP 200 in < 2.0s on both endpoints.
3. **No CLOSE-WAIT socket accumulation**:
   ```bash
   ss -tanp | grep -c CLOSE-WAIT
   ```
   *Expected*: Socket count stays flat / near zero.
4. **UI validation**:
   - Check Console Home `#dest-chip-insights` chips: displays `NNNk tkns` (not `-- tkns`).
   - Navigate to `/ #/insights`: Insights dashboard loads and charts render without blank panels.
