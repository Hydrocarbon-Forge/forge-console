# FIX-CONSOLE-R4 — Home chip shows all-time billable tokens

## Request (Nathan, 2026-10-13)
The `dest-chip-insights` chip on the home page currently shows **today's** billable tokens (54.75M). Nathan wants it to show the **all-time** billable total (~369M) instead. The All-Time Tokens card below already shows the same number; this is just the chip value.

## Required change (single file: `web/app.js`)
In the token rendering block (~line 793-825, search for `dest-chip-insights`):
- The chip line currently reads the **today** total:
  `setText("dest-chip-insights", `${formatCompactTokens(todayBilled)} tkns`);`
- Change it to prefer the **all-time** total: if `billedAlltime && billedAlltime.total != null` use that value; otherwise fall back to the today total (so the chip never blanks out).
- Keep the ` tkns` suffix and `formatCompactTokens` formatting.
- Do NOT change the today card, the all-time card, the sub-label breakdowns, or anything else. No other files. No server-side changes.

## Constraints
- Only `web/app.js` may be modified. No `index.html`, no server code, no dependencies.
- Do NOT run systemctl or restart the service — C6 handles restarts (check whether app.js is read from disk per request or cached at startup; if it needs a restart to take effect, note that in the stop marker instead of doing it yourself).
- Commit as you go.

## Verification
- `node --check web/app.js` (or `python3 -m json.tool`-style syntax sanity) must pass.
- Show the exact before/after of the changed line(s).
- Leave `COMPLETE-R4.md` (or `BLOCKED-R4.md`) in the project root.

## End with:
what line(s) changed, whether a service restart is needed for the change to be served, and what C6 should check in a browser (chip should read ~369M tkns after a hard refresh).
