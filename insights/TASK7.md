# TASK7 — Promote source picker to top of board, replace Platforms table

## Context

The board currently has:
- A **static Platforms table** (mid-page, row 2, left side) — C6-only data: `renderPlatforms()` renders `/api/platforms` rows (source / sess / msgs / billable tok).
- A **source picker** (`#cost-source`, 5 buttons: C6 (Hermes) / opencode / claude code / antigravity / all) buried at the bottom of the "What it would cost" panel. Clicking sets `costSource`, which re-filters the cost panel, KPI cost card, and flow chart.

The user wants the picker **promoted to the top of the board** (above the KPI strip) where it **replaces the Platforms table** — so the first thing you see is: tap C6 / opencode / claude code / antigravity / all, each button showing that source's **billable token count**, and the static Platforms table gone.

## Changes

### 1. New top source bar (`web/index.html`)

Add a new section as the FIRST child of `<div id="board">` (before `<section class="kpis" id="kpis">`):

```html
<section class="panel srcbar">
  <h2>Usage source</h2>
  <div class="rule"></div>
  <div class="seg" id="source-pick" role="tablist" aria-label="usage source"></div>
  <div class="micro" id="srcbar-sub" style="margin-top:8px">billable tokens in window · click a source to filter the board</div>
</section>
```

Buttons are built in JS (not hardcoded) into `#source-pick`. Five buttons in this order:
`C6 (Hermes)` (data-src=c6), `opencode` (data-src=opencode), `claude code` (data-src=claudecode), `antigravity` (data-src=antigravity), `all` (data-src=all).

Each button contains the label plus that source's **billable token count** (compact-formatted, e.g. `5.7M`, `2.2M`, `642K`, `1.5M`, `10M`), right-aligned in a monospace span:

```html
<button data-src="c6" class="active"><span class="lbl">C6 (Hermes)</span><span class="num srccount" data-count="c6">—</span></button>
```

Styling (in `style.css`): buttons in a row (wrap on narrow screens), each button min-width ~130px, label left / count right; `.srccount` uses the monospace font, accent color when the button is `.active`; reuse the existing `.seg`/`.active` visual language so it looks like the period selector. Count of a source with zero data shows `0`.

### 2. Billable-token counts per source (`web/app.js`)

Data shapes (verified live, all with `?days=<window>`):

| source | billable tokens |
|---|---|
| c6 | `summary.billed_tokens` |
| opencode | sum of `opencode.models[].billed_tokens` (each row has `billed_tokens`; the `total` object lacks cache_write, so sum model rows) |
| claudecode | sum of `claudecode.models[].billed_tokens` |
| antigravity | sum of `antigravity.models[].billed_tokens` |
| all | sum of the four above |

- Fallback if a source object is null or models empty: `0`.
- Use the existing `compact()` formatter for the displayed number.
- Recompute counts on every `render(d)` (they depend on the window/DAYS).
- Button click: sets `costSource`, toggles `.active` on the new bar, and runs the EXACT same effect as the old `#cost-source` handler (renderCost + updateCostHeadline + refreshKPIOnly + renderFlowForSource). Keep a single shared handler function used by the bar.

### 3. Remove the old bottom picker

- Remove the `#cost-source` seg block from the "What it would cost" panel in `index.html` (the include-cache checkbox and Edit prices button stay in that panel).
- Remove the `#cost-source` click-listener and the `#cost-source` active-sync in `app.js` (render() currently does `document.querySelectorAll("#cost-source button")`). Replace both with the new `#source-pick` equivalents.
- The `#cost-src-label` line in the cost panel ("usage source: …") stays — it still describes the active source for the cost math.

### 4. Remove the Platforms table

- Delete the Platforms `<section class="panel">` (the left half of the first `row2`) from `index.html`. Keep the Top Tools panel in that row; make it full-width (adjust the `row2` wrapper so Tools spans, or drop the wrapper to a single full-width section — pick whichever keeps the existing layout cleanest).
- Remove `renderPlatforms()` and its call in `render()`.
- Stop fetching `/api/platforms` in `refresh()` (drop it from the Promise.all + data object). Leave the server endpoint itself untouched (other consumers/tests may use it).

## Do NOT touch

- Backend endpoints (all unchanged; `/api/platforms` stays served).
- KPI strip logic, flow chart, cost panel rows, projection machinery, include-cache toggle, window selector.
- `pricing.json`, `server.py`.

## Tests

- Existing `test_api.py` and `verify_c6.py` must keep passing (148 + 47). If any test asserts on `#platforms` or `#cost-source` DOM presence, update it to assert the new reality: `#source-pick` present with 5 `data-src` buttons, `#platforms` absent. Keep checks drift-proof (no hardcoded data values).
- Add a couple of drift-proof checks: index.html contains `id="source-pick"`, contains all five `data-src` values, does NOT contain `id="platforms"`.

## Acceptance (verify all before finishing)

1. `python3 test_api.py` → all pass. `python3 verify_c6.py` → all pass.
2. Server live on 8901: GET `/` shows the source bar HTML before the KPI section; no `#platforms` in the page.
3. In a browser: top bar shows 5 buttons with non-zero compact counts for c6/opencode/claudecode/antigravity (all = their sum); clicking each button filters the cost panel + flow + KPI cost card exactly as the old picker did; active state moves.
4. `git diff --stat` shows changes confined to `web/` + test file(s) — no `server.py` or `pricing.json` changes.
5. Commit with message `TASK7: top source picker replaces platforms table`.

Run all commands from `~/HydrocarbonForge/Projects/insights-board`. Do not restart the board server; it serves static files fresh and reloads app.js on browser refresh.
