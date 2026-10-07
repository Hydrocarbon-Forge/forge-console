# Fix Brief — TASK-HOME round 5: deployment-aware OFFICE redirect

Nathan: the office is NOT on a dashboard subdomain — it lives at the
**`office.hydrocarbonforge.com`** subdomain on the website. The console must
work BOTH locally AND when deployed on hydrocarbonforge.com, with the
website taking priority.

## Current behavior

`web/app.js` line ~166:
```
return `http://${window.location.hostname}:8904/`;
```
This is the single source of the office URL (used by the nav tab, launchpad
tile, treasury card, keyboard `6`, and `#/office`). It only works on the LAN
where :8904 is the office.

## Required behavior (deployment-aware, single source of truth)

Make the office URL function pick the RIGHT target based on how the console
itself is being served, so both environments work:

- **Deployed on the website** — when `window.location.hostname` matches the
  website/office context (i.e. hostname is `hydrocarbonforge.com` OR a
  subdomain of it, e.g. the console may be served from the site), the office
  redirect should go to **`https://office.hydrocarbonforge.com/`**.
- **Local / LAN** — when served from a LAN IP or localhost (current behavior),
  keep redirecting to **`http://<same-host>:8904/`** so it keeps working
  locally.

Decision logic (keep it simple and robust):
```
function officeUrl() {
  const host = window.location.hostname;
  // Website context (bare domain or any subdomain of it) → website-priority:
  // the office subdomain. Anchored so unrelated hosts containing the string
  // (e.g. "notahydrocarbonforge.com") never match.
  const isWebsite = /(^|\.)hydrocarbonforge\.com$/i.test(host);
  if (isWebsite) return "https://office.hydrocarbonforge.com/";
  // Local / LAN: keep working exactly as today. Reuse the page's own protocol
  // so an https-served LAN page doesn't force an http office (and an http
  // LAN page behaves identically to before).
  return `${window.location.protocol}//${host}:8904/`;
}
```
- This single function stays the ONLY place the office URL is constructed —
  confirm all office entry points (nav tab `#nav-office`, `#launch-office`,
  `#card-jump-office`, keyboard `6`, `#/office` hash route) call it. If any
  of them hardcode `:8904` or `location.hostname` directly, route them through
  this function.
- The `isWebsite` test must match the bare domain and any subdomain of
  hydrocarbonforge.com, but NOT match a different site that merely contains
  the string (the anchored regex above does this correctly — keep it anchored).
- LAN/localhost falls through to the existing `http://<host>:8904/` (unchanged
  local behavior — this satisfies "don't break local").
- Keep the nav tab's external `↗` indicator and "Launch Office (external)"
  title as-is.

## VERIFY

1. **Local** (test port, e.g. 8919): office redirect still resolves to
   `http://127.0.0.1:8904/` (or the LAN host's :8904).
2. **Website context**: with the page's `location.hostname` set to
   `hydrocarbonforge.com` (or `console.hydrocarbonforge.com`) — verify
   `officeUrl()` returns `https://office.hydrocarbonforge.com/`. You can test
   the pure function by evaluating it in a page loaded with that host (e.g. a
   test server on a hostname, or by temporarily stubbing
   `window.location.hostname` in an eval to both values and asserting the
   returned URL). Show both assertions.
3. Confirm all five office entry points resolve to the same `officeUrl()`
   output (no leftover hardcoded `:8904` in the office-path code).
4. Constraints: fresh test port (not 8903), no service restarts (C6 restarts
   8903 after), no touching live data, vanilla JS only, git commit in chunks,
   kill your test port, append verification to this file under
   `## C6 verification results`.

## C6 verification results

### 1. Code Diff

```diff
--- a/web/app.js
+++ b/web/app.js
@@ -162,12 +162,27 @@
     },
   };

-  function getOfficeUrl() {
-    return `http://${window.location.hostname}:8904/`;
+  function officeUrl(customHost) {
+    const host = customHost || (window._officeHostOverride || window.location.hostname);
+    // Website context (bare domain or any subdomain of it) → website-priority:
+    // the office subdomain. Anchored so unrelated hosts containing the string
+    // (e.g. "notahydrocarbonforge.com") never match.
+    const isWebsite = /(^|\.)hydrocarbonforge\.com$/i.test(host);
+    if (isWebsite) return "https://office.hydrocarbonforge.com/";
+    // Local / LAN: keep working exactly as today. Reuse the page's own protocol
+    // so an https-served LAN page doesn't force an http office (and an http
+    // LAN page behaves identically to before).
+    const proto = (window.location && window.location.protocol) || "http:";
+    const p = proto.endsWith(":") ? proto : `${proto}:`;
+    return `${p}//${host}:8904/`;
+  }
+
+  function getOfficeUrl() {
+    return officeUrl();
   }

   function launchOffice() {
-    const url = getOfficeUrl();
+    const url = officeUrl();
     if (typeof window._officeRedirectInterceptor === "function") {
       window._officeRedirectInterceptor(url);
       return;
@@ -2961,8 +2976,11 @@
     }
   }

-  // Expose state for inspection
+  // Expose state and utilities for inspection
   window.state = state;
+  window.officeUrl = officeUrl;
+  window.getOfficeUrl = officeUrl;
+  window.launchOffice = launchOffice;

   // Self-initialize on DOM load
   if (document.readyState === "loading") {
```

### 2. Context URL Resolution Assertions

Verified via automated Headless Chromium CDP suite (`verify_office_redirect.py`) against isolated test server on port 8919:

#### (1) Local / LAN Context
- Real browser tab loaded at `http://127.0.0.1:8919/`:
  - `window.location.hostname`: `'127.0.0.1'`
  - `officeUrl()` resolution: **`http://127.0.0.1:8904/`** [PASS]
- Simulated LAN custom hosts:
  - `officeUrl('192.168.1.100')`: **`http://192.168.1.100:8904/`** [PASS]
  - `officeUrl('forge-box.local')`: **`http://forge-box.local:8904/`** [PASS]
  - `officeUrl('10.0.0.22')`: **`http://10.0.0.22:8904/`** [PASS]

#### (2) Website Context & Anchored Subdomains
- Real browser tab loaded at `http://hydrocarbonforge.com:8919/` (via Chromium host-resolver mapping):
  - `window.location.hostname`: `'hydrocarbonforge.com'`
  - `officeUrl()` resolution: **`https://office.hydrocarbonforge.com/`** [PASS]
- Real browser tab loaded at `http://console.hydrocarbonforge.com:8919/`:
  - `window.location.hostname`: `'console.hydrocarbonforge.com'`
  - `officeUrl()` resolution: **`https://office.hydrocarbonforge.com/`** [PASS]
- Subdomains and Case-insensitivity:
  - `officeUrl('office.hydrocarbonforge.com')`: **`https://office.hydrocarbonforge.com/`** [PASS]
  - `officeUrl('dev.sub.hydrocarbonforge.com')`: **`https://office.hydrocarbonforge.com/`** [PASS]
  - `officeUrl('HYDROCARBONFORGE.COM')`: **`https://office.hydrocarbonforge.com/`** [PASS]
  - `officeUrl('CONSOLE.HYDROCARBONFORGE.COM')`: **`https://office.hydrocarbonforge.com/`** [PASS]
- Negative Regex Anchoring Tests (must NOT match website regex; fall through to LAN logic):
  - `officeUrl('notahydrocarbonforge.com')`: **`http://notahydrocarbonforge.com:8904/`** [PASS]
  - `officeUrl('evil-hydrocarbonforge.com')`: **`http://evil-hydrocarbonforge.com:8904/`** [PASS]
  - `officeUrl('hydrocarbonforge.com.attacker.com')`: **`http://hydrocarbonforge.com.attacker.com:8904/`** [PASS]
  - `officeUrl('myhydrocarbonforge.com')`: **`http://myhydrocarbonforge.com:8904/`** [PASS]

### 3. Entry-Point Check (All 5 Entry Points)

Tested using `window._officeRedirectInterceptor` in live browser tabs across both local and website contexts:

| Entry Point | Local Context Target | Website Context Target | Result |
| :--- | :--- | :--- | :--- |
| **1. Nav tab (`#nav-office`)** | `http://127.0.0.1:8904/` | `https://office.hydrocarbonforge.com/` | Verified [PASS] |
| **2. Launchpad tile (`#launch-office` click & Enter)** | `http://127.0.0.1:8904/` | `https://office.hydrocarbonforge.com/` | Verified [PASS] |
| **3. Treasury card (`#card-jump-office` click & Enter)** | `http://127.0.0.1:8904/` | `https://office.hydrocarbonforge.com/` | Verified [PASS] |
| **4. Keyboard shortcut (`6`)** | `http://127.0.0.1:8904/` | `https://office.hydrocarbonforge.com/` | Verified [PASS] |
| **5. Hash route (`#/office` & `#office`)** | `http://127.0.0.1:8904/` | `https://office.hydrocarbonforge.com/` | Verified [PASS] |

- Static audit: exactly **1** occurrence of `:8904` in `web/app.js` (inside `officeUrl()`), and **0** occurrences across all other files in `web/`.
- UI inspection: `#nav-office` retains title `"Launch Office (external)"`, tab label `"OFFICE"`, and external indicator glyph `↗` (`&nearr;`).
- Lifecycle: test server on port 8919 and Headless Chromium CDP instances cleanly terminated after test run. Port 8903 remained untouched.

