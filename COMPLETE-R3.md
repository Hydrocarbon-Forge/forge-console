# COMPLETE-R3 — Claudecode & Antigravity Re-scan Storm Resolution

**Status:** COMPLETE (Stop Marker)  
**Date:** 2026-10-13  
**Branch:** master  

---

## 1. Diagnosis Verdict: Confirmed

All 4 diagnosed root causes were verified against the codebase and live baseline measurements:

1. **Un-cached 750 MB file scans per request (`insights/server.py:1904-1907`) — CONFIRMED:**
   - Lines 1904–1907 explicitly bypassed `cached()` with the comment `# TASK5: full re-scan per request (sources are small); no cache.`.
   - In reality, `scan_claudecode` walks `~/.claude/projects` (981 files, 47,998 lines, ~756 MB) taking **1.887s**, and `scan_antigravity` takes **1.987s**.
   - Running cold back-to-back took **3.874s** of continuous disk and CPU churn per un-cached request.

2. **Collector re-triggered scan storm every 5s (`collector.py:175-181, 204-211`) — CONFIRMED:**
   - `collector.py` called `http://127.0.0.1:8901/api/claudecode?days=1` and `/api/antigravity?days=1` with `timeout=0.8`.
   - Because the scans take ~1.9–2.0s, the client socket timed out at 0.8s while the server-side HTTP worker thread continued scanning to completion in the background.
   - A new collector tick triggered every 5s, permanently saturating the insights engine at ~100% CPU.

3. **Fanout amplification + silent drop (`server.py:162-172, 219, 227`) — CONFIRMED:**
   - `server.py:167` had a strict `timeout=5.0` in `_fetch_insights_json`.
   - When upstream :8901 was saturated mid-scan, requests timed out and returned `None`.
   - In `_compute_home_tokens_aggregate()`, `today_total = sum(v for v in today_by_src.values() if v is not None)` silently dropped `claudecode: None`, resulting in understated home totals.

4. **Proxy timeout mismatch (`server.py:865`) — CONFIRMED:**
   - `forward_http` had `timeout=10.0`. When upstream :8901 was processing long scans, proxying `:8903/api/summary?days=all` timed out at 10.0s and returned 502 Bad Gateway, even though HTTP handler timeouts were 30–60s.

---

## 2. Changes Implemented (5 Ranked Edits)

1. **`insights/server.py:1904-1907`** — Routed `build_claudecode` and `build_antigravity` through the existing `cached()` helper with 60s TTL (`CACHE_TTL = 60`), matching the board's warm-cache architecture.
2. **`collector.py:175-181, 204-211`** — Completely removed the 5s loopback HTTP calls to `:8901/api/claudecode` and `:8901/api/antigravity`. Implemented in-memory readers `_get_server_token_metric()` and `_get_server_session_metric()` that read directly from `server._home_tokens_cache` with zero network overhead and zero blocking.
3. **`server.py:167`** — Increased `_fetch_insights_json` timeout from `5.0s` to `15.0s`.
4. **`server.py:219, 227`** — Replaced silent dropping of `None` sources with last-known cached fallback from `_home_tokens_cache`. If any source fails and falls back, the aggregate payload marks it degraded (e.g. `"degraded": ["claudecode"]`) while preserving backward-compatible JSON structure. Exposed `get_cached_today_tokens()` and `get_cached_sessions()` accessors.
5. **`server.py:865`** — Increased `forward_http` proxy timeout from `10.0s` to `30.0s` to match handler socket timeouts.

---

## 3. Verification Performed (Without Restarting Service)

- **Bytecode compilation (`python3 -m py_compile`):**
  - `insights/server.py`: Clean (0 errors)
  - `server.py`: Clean (0 errors)
  - `collector.py`: Clean (0 errors)

- **Cached build path timing:**
  - `claudecode`:
    - Call 1 (cold miss): `1996.30ms` (age=0.000s)
    - Call 2 (cache hit): `0.019ms` (age=1.996s, <100ms pass)
  - `antigravity`:
    - Call 1 (cold miss): `2369.07ms` (age=0.000s)
    - Call 2 (cache hit): `0.016ms` (age=2.369s, <100ms pass)

- **Cold scan baseline:**
  - `scan_claudecode`: `1.887s` (981 files, 47,998 lines)
  - `scan_antigravity`: `1.987s` (94 conversations, 11,128 lines)
  - Combined: `3.874s`

- **Collector code path verification:**
  - Grep of changed collector path confirms no loopback HTTP calls to `:8901` for claudecode or antigravity.
  - Collector reads directly from `server._home_tokens_cache`.

- **Clean import verification:**
  - `python3 -c "import server, collector"` clean (0 errors, stdlib only).

- **Fallback & degraded unit test:**
  - Verified `_compute_home_tokens_aggregate()` correctly restores last-known tokens on upstream drop and populates `"degraded": ["claudecode"]`.

- **Service state:**
  - Service was NOT restarted; `systemctl` was NOT executed.

---

## 4. Git Commits

- `74e418f`: `fix(insights): cache claudecode and antigravity endpoints with 60s TTL`
- `e02a3f0`: `fix(server): increase fetch/proxy timeouts and handle degraded sources with cache fallback`
- `5c0124e`: `fix(collector): read claudecode and antigravity metrics from server in-memory cache`

---

## 5. C6 Post-Restart Verification Checklist

When C6 restarts `forge-console`:
1. **Thread count:** Remains flat under poller load (no thread accumulation or runaway workers).
2. **`/api/home` totals:** `by_source` shows `claudecode` as non-None within ~1 minute of boot (tokens populated from warm cache).
3. **No 502 on `days=all`:** `GET http://127.0.0.1:8903/api/summary?days=all` resolves with 200 OK within the 30s proxy window.
4. **CPU utilization:** Sustained idle CPU remains well below 50%.
