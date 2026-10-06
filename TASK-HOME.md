# Forge Console — "HOME" dashboard + icon nav (reimagining the :8903 console)

Requested by Nathan 2026-10-06. This task reimagines the console's front door:
replace the numbered 1/2/3/4 tabs with a **HOME dashboard** (the new default
landing view) plus an **icon-based navigation** that launches into Insights,
Ideas, Flow, Projects, and the Office. Whatever you make here is the new face of
the console on port 8903. The existing Insights/Ideas/Flow/Projects panes keep
working — you are ADDING a home + office pane, redesigning the nav, and setting
HOME as the default. You are NOT rebuilding the sub-apps.

## Read first (do this before writing any code)

- `web/index.html` — current topbar, nav tabs (numbered), the four panes
  (insights/ideas = iframes to `/insights/` and `/ideas/`, flow = canvas,
  projects = table). Understand the existing structure so the new work slots
  in cleanly.
- `web/app.js` — the tab system (`state.activeTab`, `isTabInitialized`,
  `setTab`/switch logic, keyboard `1`/`2`/`3`/`4`, service-strip polling, the
  `/api/flow`, `/api/health`, `/api/proxy/*` fetch patterns). Keep the
  existing tab machinery; extend it.
- `web/style.css` — the house design system (CSS vars at top: `--bg #0a0a0a`,
  `--panel #121212`, `--accent #FF8C42` forge orange, `--accent-steel
  #5aa9e6`, `--accent-mint #5ad6a0`, `--accent-amber #ffb454`, `--accent-green
  #3ddc84`, `--accent-red #f25c54`, `--accent-purple #b185db`, Oswald display /
  Inter body / JetBrains Mono, the hex `--hex-pattern` background, focus rings).
  Reuse these — do not invent a second palette.
- `server.py` — stdlib `ThreadingHTTPServer` on 8903. It already proxies
  `/api/summary`, `/api/activity`, `/api/flow`, etc. (see
  `INSIGHTS_PROXY_ENDPOINTS`, `SCHEME_EXACT_ENDPOINTS`, and the console-own
  `/api/flow`, `/api/health`, `/api/projects`). You will ADD one route
  (`/api/trading`) — see Server changes.
- The site's motion language (the signature to channel):
  `../hydrocarbon-forge-website/index.html` + `styles.css` — the `#hf-mark`
  hex logo symbol, the `#hf-ring` spinning hex (`.hero-hex`, `spin 90s linear
  infinite`, large, faint, `rgba(255,255,255,0.05)`), the `breathe` 9s
  scale-glow, `pulse` dots, `drip` scroll line, `marquee`, and `reveal`
  scroll-in (`opacity 0 / translateY(28px)` → in-view). Port this feel.

## What to build

### 1. Navigation: icons, not numbers

Replace the topbar's four numbered tabs with **six icon tabs**:

  Home · Insights · Ideas · Flow · Projects · Office

Each tab shows a **clean line SVG icon** (draw your own — 24px viewBox,
`stroke: currentColor`, ~1.8px, no emoji) + a short uppercase label. The
**icon is the primary** affordance; you may keep a *small, dim* keyboard hint
if it aids usability, but numbers must no longer be the visual identity.
Pick icons that fit the forge/hex aesthetic and are instantly legible:
- Home → a hexagon (the house mark) or a hex-enclosed dot.
- Insights → a pulse/sparkline line or a gauge.
- Ideas → a hexagon with a node cluster / a spark.
- Flow → connected nodes / a flowing line.
- Projects → stacked hexes / a folder-hex.
- Office → a building / map hex.

Active tab = forge-orange icon + label with a subtle glowing underline or
fill; hover raises a faint panel; `aria-selected` + `role=tab` preserved.
Re-map keyboard shortcuts so all six switch (e.g. `1`=Home `2`=Insights
`3`=Ideas `4`=Flow `5`=Projects `6`=Office — verify `?` overlay lists them).
Keep the existing `?` shortcut overlay, updated for the six keys.

### 2. HOME — the new default dashboard (the centerpiece)

HOME is the first thing you land on (it replaces Flow as the default active
pane). It is a **modern, beautiful dashboard** of the forge's most important
live metrics. It must feel genuinely *Hydrocarbon Forge* — not a generic
Grafana/Notion dashboard. Requirements:

- **Layout:** a real dashboard composition (a hero/summary row + a grid of
  metric cards/tiles + a couple of wider panels), responsive, no layout shift
  on load, subtle `reveal`-style entrance. Use the hex motif and forge-orange
  accents from the design system. It must stay **clean and usable** — obvious
  where the numbers are, obvious where you click to go deeper. Do not make it
  wonky just to be unique.

- **Metrics to display (all live, polling every ~5s like the rest of the app):**
  1. **Today's tokens** — from `/api/summary?days=1` (use `total_tokens` or
     `billed_tokens`; label clearly which).
  2. **All-time tokens** — from `/api/summary?days=3650` (big window ≈
     all-time; use `total_tokens`). Show a humanized count (e.g. 134.1M) in
     JetBrains Mono.
  3. **Currently running harnesses** — from `/api/flow` → `harnesses[]`
     where `running` or `active_sessions > 0`. Show a count badge and list the
     active ones by name with a pulsing "live" dot; if none are running, show
     "no active harnesses" (not an error).
  4. **Projects being worked on** — from `/api/flow` → `projects[]` where
     `active` or `changes_60m > 0` (fall back to most-recently-written if
     nothing is active, so the panel is never empty). Show name + a small
     activity indicator (changes in last 60 min / last-write age).
  5. **Trading stats (from the Office)** — from the NEW `/api/trading`
     endpoint (see Server changes), which mirrors the office's
     `data/trading.json`. Show at minimum: overall **equity**, **total P/L**
     and **day P/L** for both `stock` and `crypto` books (green/red by sign),
     and the number of holdings. Clicking the trading panel should let you
     jump to the Office.

- **The logo/motion (make it the signature):** bring in the site's `#hf-mark`
  hex and give the home a **focal animated hex** — e.g. a large faint spinning
  `#hf-ring` (like the site's `.hero-hex`) behind/around the summary, with a
  breathing glow, so the home opens on the Forge's mark, not a blank grid.
  Respect `prefers-reduced-motion` (no spin/breathe; static). This is what
  separates it from "every other dashboard".

- **Navigation tiles:** the home should also carry the five destination
  tiles (Insights / Ideas / Flow / Projects / Office) as large, clickable,
  icon-bearing cards that launch into those panes (or, for Office, into the
  Office pane). These are the "navigation that lets you launch into" each
  section. They should read as a coherent set, each with a one-line descriptor
  and a live at-a-glance chip where cheap (e.g. Insights → today's tokens,
  Ideas → idea count from `/api/proxy/scheme/api/stats`, Projects → project
  count, Flow → services-up count, Office → equity). Hover = lift + orange
  edge.

- **Live elements:** a live clock (the app already has one in the topbar —
  reuse/don't duplicate), and keep the topbar's service-health strip working.
  Numbers should count up / tween on load (subtle, ~400ms) and on refresh.

### 3. OFFICE — new pane

Add an **Office** pane (iframe, exactly like the existing insights/ideas
iframe panes) that loads the live office from **8904**. Compute the office URL
as `http://${location.hostname}:8904/` (so it works both locally and when
browsed on the LAN — never hardcode 127.0.0.1). Lazy-init on first visit
(`isTabInitialized.office`), keep state alive on tab switch. Title it
"Office".

### 4. HOME becomes the default

On load, HOME is the active pane (not Flow). Direct URL `#/` or `#/home`
→ HOME. Keep existing hash routes (`#/insights`, `#/ideas`, `#/flow`,
`#/projects`) working; add `#/office`.

## Server changes (server.py)

Add **`GET /api/trading`** — same-origin so the home never needs to reach
8904 cross-origin. Implementation: server-side, on request (it's a small JSON
file), try in order:
1. `urllib` fetch `http://127.0.0.1:8904/data/trading.json` (timeout ~1.5s).
2. fall back to reading the file
   `~/HydrocarbonForge/Projects/forge-office/data/trading.json` directly.
3. if both fail, return a well-formed `{ "error": "...", "upstream": "down" }`
   with HTTP 502 (never crash, never 500).
Return the trading JSON as-is with `Content-Type: application/json` and the
standard CORS headers (reuse `send_cors_headers`). Keep it consistent with the
existing handlers (stdlib only, no new deps). The trading doc shape is:
`{ updated, updated_ts, stock:{ label, equity, start, total_pnl, total_pct,
day_pnl, day_pct, cash, cash_pct, n_trades, holdings:[{sym,qty,px,val,w}],
trades_now:[...] }, crypto:{...same shape...}, errors:[] }`.

Optionally also expose `GET /api/home` that aggregates summary(days=1),
summary(days=3650), the flow harnesses/projects, and trading in ONE payload so
the home does one fetch instead of four — **your call** on whether to add it;
if you do, keep the individual endpoints working too. (Note the existing
`/api/summary`, `/api/activity`, `/api/flow` are already reachable on 8903.)

## Design direction (the part that matters most)

Nathan's ask, verbatim intent: *"make it not feel like every other dashboard
in existence, but also don't make it feel too complicated to use if the design
is too wonky, but make it unique. Do a study into design and how different
things can work. Maybe make a design subagent that figures out this unique
Hydrocarbon Forge style. Do something with the logo and animation like the
site has."*

So — **do a real design pass first, then build.** Concretely:

1. **Design study (do this before coding the home):** spend real thought on
   2–3 *distinct* dashboard concepts (not "a card grid" — think about what a
   "forge" is: a place where raw material is refined into value under heat).
   The HF identity is: dark industrial, hexagonal geometry, forge-orange heat
   accent, the hex-mark logo, the site's slow spin + breathe + reveal motion,
   Oswald condensed uppercase labels, mono numerals, thin hairline borders, a
   faint hex grid background. Pick **one** strong concept that is both
   distinctive AND clean/usable. You are encouraged to **spawn a design
   subagent** (or just reason it through) to pressure-test the unique HF
   style and propose the concept. **Write your chosen concept to
   `DESIGN.md`** in this project (2–4 short sections: the concept, the layout
   grammar, the motion, the color/accent usage) so the reasoning is recorded.
   This is the artifact that proves you studied it.
2. **Uniqueness with restraint:** the home should open on something only a
   forge would do (the living hex mark, an industrial "control panel"
   framing, heat/glow accents tied to *active* things). But navigation and
   the metric tiles must stay dead simple to read — a newcomer should find the
   numbers and the buttons within a second. Unique in concept, conventional in
   affordances.
3. **Motion:** lean on the site's existing motion vocabulary (slow hex spin,
   breathe glow, pulse on active, reveal-in, count-up) rather than flashy
   effects. Respect `prefers-reduced-motion`.
4. **No external deps.** Vanilla JS, stdlib server, offline-safe (Google Fonts
   is the only allowed external reference; degrade to system fonts). No
   frameworks, no CDN scripts.

## Constraints & house rules

- **Do NOT restart any running service.** You are editing the live 8903
  service's code. Implement + verify syntax/logic and **stop before** any
  `systemctl` restart — C6 restarts `forge-console` separately afterward.
  (You may run a *separate* test instance on a different port, e.g. `PORT=8910
  python3 server.py`, to verify — but do not bind 8903 yourself, and kill any
  test server before finishing.)
- **Do NOT touch the live data** the office/insights/ideas engines write
  (`forge-office/data/*`, insights DB, ideas `db.py` store). The console only
  *reads* them.
- **Git (required):** the project is already a git repo. `git add` + `git
  commit` as you go — commit the design pass, the nav, the home, the office
  pane, and the server route in logical chunks. Do not leave uncommitted work.
- Keep the four existing panes working (insights/ideas iframes, flow canvas,
  projects table). This is additive + nav redesign, not a rip-out.
- Stdlib-only server. No third-party imports.
- After implementing, verify: `python3 -c "import server, collector"` clean;
  a test instance (PORT=8910) serves `/`, `/api/trading` returns the office
  trading JSON (200, correct shape), `/api/summary?days=1` and `?days=3650`
  proxy through, `/api/flow` works, and the six nav tabs + home render. Report
  actual curl output snippets.

## File layout (expected)

```
forge-console/
  DESIGN.md          (NEW — your design study + chosen concept)
  server.py          (add /api/trading, optionally /api/home)
  web/index.html     (nav icons + HOME pane + OFFICE pane + default HOME)
  web/app.js         (tab system extended to 6; home data + rendering; office pane)
  web/style.css      (home dashboard styles, icon nav, motion)
```

## Acceptance checklist

1. `python3 -c "import server, collector"` clean, stdlib only.
2. Test instance (PORT=8910): `GET /` serves the new console; `GET
   /api/trading` 200 with the office trading shape (or a well-formed 502 JSON
   if the office is down — never a crash).
3. `GET /api/summary?days=1` and `?days=3650` return the 8901 summary;
   `GET /api/flow` returns harnesses+projects.
4. Home is the default landing; it renders all five metric groups (today
   tokens, all-time tokens, running harnesses, active projects, office
   trading) with live polling; the animated hex logo is present and respects
   `prefers-reduced-motion`.
5. Six icon nav tabs (Home/Insights/Ideas/Flow/Projects/Office), keyboard
   `1`–`6` switch, `?` overlay updated; Office pane iframes
   `http://${location.hostname}:8904/`.
6. Existing panes (insights/ideas/flow/projects) still work after the change.
7. `DESIGN.md` written. Git committed. No leftover test server, nothing bound
   to 8903 by you, live data untouched.
8. Report: what you built, the chosen design concept (1–2 lines), and the real
   curl/browser verification snippets. Note anything skipped.
