# Fix Brief — TASK-HOME round 4: headline metrics stuck at `--` when rAF is throttled

C6's live-browser audit (unrendered/automation tab) found that the home
HEADLINE metric values — `home-tokens-today`, `home-tokens-alltime`, and the
office equity values — can stay at their `--` placeholder, while the
sub-breakdown lines (set with direct `textContent`) render correctly.

## Root cause (verified by C6 — verify it yourself, note if different)

All the headline values are set through `tweenValue()` (web/app.js ~line 463),
which, when `prefers-reduced-motion` is NOT set, does:
  - compute `startVal`
  - `requestAnimationFrame(step)` to drive the count-up
and does NOT write any baseline text first. So the first paint of the value
depends entirely on rAF firing. In a background/hidden tab (or under heavy
throttling) rAF callbacks are deferred/skipped, so the element never leaves
its initial `--`. The sub-lines bypass rAF (direct `el.textContent = ...`)
and therefore always render — which is exactly the asymmetry observed.

C6 confirmed in the audit browser: `window.matchMedia('(prefers-reduced-motion:
reduce)').matches === false`, `typeof requestAnimationFrame === 'function'`,
yet a scheduled `requestAnimationFrame(() => flag=true)` did NOT set the flag
within 1.5s (tab unrendered). So the code path is reachable and real.

## Fix

Make `tweenValue` robust to rAF never firing (hidden/throttled tab), WITHOUT
disturbing the normal visible-tab count-up. Key: a `started` flag — the
fallback timer only writes the final value if the first rAF frame never fired,
so a healthy visible-tab animation is never cut short.

Replace the body of `tweenValue` with (logic, not verbatim — adapt to the
existing code, keep the existing ease and duration):

```
function tweenValue(el, targetVal, formatFn, durationMs = 400) {
  if (!el) return;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const startVal = typeof el._currentVal === "number" ? el._currentVal : 0;
  el._currentVal = targetVal;
  if (reduce) { el.textContent = formatFn(targetVal); return; }
  if (startVal === targetVal) { el.textContent = formatFn(targetVal); return; }
  el.textContent = formatFn(startVal);        // continuity baseline (no flicker)
  const startTime = performance.now();
  let started = false, done = false;
  const step = (now) => {
    if (done) return;
    started = true;                            // first frame fired -> rAF is alive
    const elapsed = now - startTime;
    const progress = Math.min(elapsed / durationMs, 1.0);
    const ease = 1 - (1 - progress) * (1 - progress);
    el.textContent = formatFn(startVal + (targetVal - startVal) * ease);
    if (progress < 1.0) requestAnimationFrame(step);
    else { done = true; el.textContent = formatFn(targetVal); }
  };
  requestAnimationFrame(step);
  // Fallback: if rAF never fires (hidden/throttled tab), write the final
  // value so the headline doesn't stay at its `--` placeholder.
  setTimeout(() => { if (!started && !done) { done = true; el.textContent = formatFn(targetVal); } }, 200);
}
```

Behavior by case:
- **visible tab** — first rAF frame fires ~16ms, sets `started=true`; the 200ms
  fallback is a no-op; the count-up runs cleanly start→final exactly as today.
- **reduced-motion** — unchanged (direct write, early return).
- **hidden/throttled tab** — rAF never fires, `started` stays false, the
  200ms timer (which runs even in background tabs) writes the final value.
- `startVal === targetVal` (no change) — direct write, no timer.

Keep the existing `el._currentVal` memory slot exactly as the current code
uses it (start value read before overwrite) — do not introduce a second slot
like `el._prevVal`; the snippet above is logic, not verbatim. Do NOT touch the
reduced-motion branch or the `formatCompactTokens` / `formatAllTimeTokens`
formatters. Apply the change to `tweenValue` only, so every headline value
(tokens today, tokens all-time, office equity, etc.) inherits the fix.

## VERIFY

- On a fresh test port (e.g. 8916; do NOT bind 8903, do NOT restart any
  service, do NOT touch live data), with an UNRENDERED/background tab (the
  way C6 audits — automation tab, rAF not firing): confirm the headline
  metrics show their REAL values (not `--`) within a couple seconds of load.
  If you can't force an unrendered tab, at minimum confirm the code writes the
  baseline textContent before rAF (show the diff) AND that a normal visible-tab
  load still count-ups correctly.
- Reduced-motion path unchanged (verify the branch still short-circuits).
- Git commit the fix; kill your test port before finishing; append verification
  (the code diff + your verification method) to this file under
  `## C6 verification results`.

## C6 verification results

Verification completed on isolated test instance `PORT=8916` (port 8903 remained untouched; zero service restarts; live engine data untouched). All test server and Chromium processes cleanly terminated upon completion.

### 1. The `tweenValue` Code Diff

```diff
--- a/web/app.js
+++ b/web/app.js
@@ -472,8 +472,13 @@
       el.textContent = formatFn(targetVal);
       return;
     }
+    el.textContent = formatFn(startVal); // continuity baseline (no flicker)
     const startTime = performance.now();
+    let started = false;
+    let done = false;
     function step(now) {
+      if (done) return;
+      started = true; // first frame fired -> rAF is alive
       const elapsed = now - startTime;
       const progress = Math.min(elapsed / durationMs, 1.0);
       const ease = 1 - (1 - progress) * (1 - progress);
@@ -482,10 +487,19 @@
       if (progress < 1.0) {
         requestAnimationFrame(step);
       } else {
+        done = true;
         el.textContent = formatFn(targetVal);
       }
     }
     requestAnimationFrame(step);
+    // Fallback: if rAF never fires (hidden/throttled tab), write the final
+    // value so the headline doesn't stay at its `--` placeholder.
+    setTimeout(() => {
+      if (!started && !done) {
+        done = true;
+        el.textContent = formatFn(targetVal);
+      }
+    }, 200);
   }
```

### 2. Verification Method

Automated end-to-end verification executed via `verify_tween_robustness.py` against `http://127.0.0.1:8916`:
1. **Server Lifecycle**: Standalone server started with `PORT=8916 python3 server.py`. Confirmed `/api/health` and aggregated `/api/home` responding correctly.
2. **Headless Chromium CDP Automation (`--headless=new`, CDP port 9226)**:
   - **Case 1 (Unrendered / Hidden Background Tab)**:
     - Target Tab 1 created navigating to `http://127.0.0.1:8916/#pane-home`.
     - Target Tab 2 created and activated via `Target.activateTarget`, forcing Tab 1 into background state.
     - Confirmed Tab 1 visibility state: `hidden: true`, `state: 'hidden'`.
     - Confirmed rAF vs timer behavior: `requestAnimationFrame` did NOT fire within observation window (`rafFired: false`), while `setTimeout` fired (`timerFired: true`).
     - Asserted that all headline DOM metrics (`#home-tokens-today`, `#home-tokens-alltime`, `#home-trading-equity`) escaped `--` and reached their real values via the fallback timer.
   - **Case 2 (Visible Tab with Smooth Count-Up)**:
     - Active target created and focused: `hidden: false`, `state: 'visible'`.
     - Tested `tweenValue` frame execution telemetry: verified synchronous baseline write (`0`), sampled mid-flight count-up (`midValue = 245`, between 0 and 1000), and final completion (`1000`).
     - Polled live DOM elements to verify transition: captured initial `--` placeholder, mid-animation in-flight values, and final settled values. Confirmed fallback timer was a no-op because `started = true`.
   - **Case 3 (Reduced Motion)**:
     - Emulated media feature `prefers-reduced-motion: reduce`.
     - Evaluated `tweenValue` to verify immediate synchronous write of final formatted value (`REDUCED_555`) with early return.
   - **Case 4 (Same Value `startVal === targetVal`)**:
     - Verified immediate write and early return without animation or timers.
3. **Process Teardown**: Both Chromium and test server `PORT=8916` cleanly terminated; port closed.

### 3. Observed Values

- **Server `/api/home` payload**:
  - `billed_today_by_source.total`: 20,992,241 tokens
  - `billed_alltime_by_source.total`: 57,108,514 tokens
  - `trading.total_equity`: $197.60

- **Suite 1: Unrendered / Background Tab (rAF dead)**:
  - Background scheduler state: `rafFired: False`, `timerFired: True`
  - `#home-tokens-today`: `20.99M` (not `--` or `0`)
  - `#home-tokens-alltime`: `57.1M` (not `--` or `0`)
  - `#home-trading-equity`: `$197.60` (not `$--` or `$0.00`)

- **Suite 2: Visible Tab (Live count-up stages)**:
  - Stage 0 (initial DOM): `today='--', alltime='--', eq='$--'`
  - Stage 1 (in-flight smooth tween): `today='3.48M', alltime='9.4M', eq='$32.25'`
  - Stage 2 (final settled): `today='20.98M', alltime='57.1M', eq='$197.60'`

- **Suite 3: Reduced Motion**:
  - `isReduced: True`, `immediateText: 'REDUCED_555'`
