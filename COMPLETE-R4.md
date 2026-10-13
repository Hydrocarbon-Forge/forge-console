# COMPLETE-R4 — Home Insights Chip All-Time Billable Tokens

**Status:** COMPLETE (Stop Marker)  
**Date:** 2026-10-13  
**Branch:** master  

---

## 1. Summary of Changes

Modified `web/app.js` in the token rendering section (`renderHomeMetrics`) so the `dest-chip-insights` chip prefers the **all-time** billable tokens total when available (`billedAlltime && billedAlltime.total != null`), and gracefully falls back to today's total (`todayBilled`) if all-time data is absent.

No other files were modified. No server code, no HTML, and no dependencies were changed.

---

## 2. Exact Before / After

**File:** `web/app.js` (lines 802–803 and 810–811)

### Primary branch (`billedToday && billedToday.total != null`):
**Before:**
```javascript
      setText("dest-chip-insights", `${formatCompactTokens(todayBilled)} tkns`);
```
**After:**
```javascript
      const chipTokens = (billedAlltime && billedAlltime.total != null) ? billedAlltime.total : todayBilled;
      setText("dest-chip-insights", `${formatCompactTokens(chipTokens)} tkns`);
```

### Fallback branch (`summaryToday`):
**Before:**
```javascript
      setText("dest-chip-insights", `${formatCompactTokens(todayBilled)} tkns`);
```
**After:**
```javascript
      const chipTokens = (billedAlltime && billedAlltime.total != null) ? billedAlltime.total : todayBilled;
      setText("dest-chip-insights", `${formatCompactTokens(chipTokens)} tkns`);
```

---

## 3. Service Restart Assessment

**Is a service restart needed?**  
**NO.** A service restart is **NOT** needed for this change to be served.

### Technical Rationale:
In `server.py` (`handle_static`, lines 1074–1081):
```python
with open(file_path, "rb") as f:
    content = f.read()

self.send_response(200)
self.send_header("Content-Type", ctype)
self.send_header("Content-Length", str(len(content)))
if ext in (".js", ".html"):
    self.send_header("Cache-Control", "no-cache")
```
- `web/app.js` is read directly from disk per incoming HTTP request.
- The HTTP response includes `Cache-Control: no-cache`.
- Verified live against running service `:8903`: `curl -s http://127.0.0.1:8903/app.js` immediately returned the updated `chipTokens` logic without restarting the process.
- As requested in constraints, `systemctl` was **NOT** executed and the service was **NOT** restarted.

---

## 4. Verification

1. **Syntax sanity check:**
   - Command: `node --check web/app.js`
   - Exit code: `0` (Clean, syntax valid)

2. **HTTP delivery verification:**
   - Command: `curl -s http://127.0.0.1:8903/app.js | grep -C 2 "chipTokens"`
   - Output confirmed the updated code is actively served by `:8903`.

3. **Data evaluation test:**
   - Home API endpoint `/api/home` currently returns:
     - `billed_today_by_source.total`: `54,630,034` (~54.63M)
     - `billed_alltime_by_source.total`: `369,777,507` (~369.78M)
   - Formatting `formatCompactTokens(369777507) + " tkns"` yields: `369.78M tkns`.

---

## 5. What C6 Should Check in a Browser

1. Open Forge Console in browser at `http://127.0.0.1:8903/` (or the reverse proxy URL).
2. Perform a hard refresh (`Ctrl+F5` / `Ctrl+Shift+R` / `Cmd+Shift+R`) to bypass browser-level client cache.
3. Observe the `INSIGHTS` card chip (`#dest-chip-insights`) on the Home page:
   - It should now read **`~369M tkns`** (specifically `369.78M tkns`), matching the **All-Time Tokens** metric card below it, instead of today's `54.75M tkns`.
