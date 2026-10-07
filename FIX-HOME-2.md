# Fix Brief — TASK-HOME round 2: IDEAS count bug + design polish (C6 audit, 2026-10-06)

Two inputs, fix ALL of them in one pass:

## A. Data bug (details in FIX-HOME-1.md — read it)

The IDEAS launchpad chip shows "0 ideas" while the board has 12. Root cause
(verify it yourself, note if different): server.py ~line 421 reads
`stats_doc.get("total_ideas", stats_doc.get("ideas_count", 0))` but the
scheme-board `/api/stats` shape is `{counts: {total, by_status, by_category,
seeded_count}, top_opportunities: [...]}` — total lives at `counts.total`.
Fix BOTH the server aggregate (`/api/home` ideas_count) and the frontend
fallback chain in web/app.js (`d.total_ideas || d.ideas_count || 0`).

## B. Design polish (from a pixel-level audit of the rendered home; the audit
screenshot is at docs/home-audit-8911.png — view it with your vision tools
before making changes)

The home is structurally strong (identity, type, framing all read well) but
lands ~7/10 on polish. Fix these:

1. **Cyan clash.** The ALL-TIME TOKENS value renders in bright electric
   cyan (#38bdf8-ish) while every other primary metric is white and the
   brand accent is forge orange — it reads as a broken/out-of-theme stat.
   Unify: primary metric values = white; reserve palette accents for deltas
   and live dots. If you want a secondary tint for all-time, use the design
   system's steel `#5aa9e6` at reduced emphasis — not hot cyan.
2. **Native scrollbar.** A light/white native scrollbar leaks through the
   right edge and breaks the dark boundary. Style it (webkit-scrollbar,
   thin, dark track, subtle thumb) to match the UI.
3. **Harness-fleet dead space.** The ACTIVE HARNESS FLEET card matches the
   workbench card's height but only lists the RUNNING harnesses, leaving a
   big empty void when one is running. Fix: list ALL harnesses from
   `/api/flow` — running ones on top with the pulsing live dot + "N active" +
   PID, idle ones below, dimmed with a small "IDLE" tag. Fills the card and
   answers "what's running" AND "what's available".
4. **Currency formatting.** P&L pills render `$-1.63` / `$-2.09` — wrong
   order. Use `- $1.63` or `-$1.63` style (sign before the dollar sign)
   everywhere currency is shown, green for positive, red for negative.
5. **Low-contrast microcopy.** Subtitles/dim labels (~#555–#600 on near-
   black) are marginal. Bump dim text to at least the design system's
   `--text-dim` equivalent that stays legible (contrast ≥ ~4.5:1 for the
   smaller body copy); keep the hierarchy (primary white, secondary ~#9d9ea5,
   tertiary lighter than today's).
6. **Static-feel cards → add micro-visualization.** The single biggest thing
   missing from a premium command-console feel: cards are dominated by static
   numbers with dead space. Add subtle inline visualizations:
   - COMPUTE ENGINE panel: a small 7-day token sparkline (from
     `/api/activity?days=7` → `by_day`/`daily` `total_tokens`), thin SVG
     line, orange stroke, ~200×36px, under the two token metrics.
   - HARNESSES card (with item 3's full fleet list): a relative usage bar
     per harness (from `/api/flow` `tokens_today`, relative scale), thin.
   Keep them subtle (thin strokes, no chart junk, no axes), respect
   `prefers-reduced-motion` (static is fine for sparklines), and keep the
   cards' existing structure — these fill the dead space, not replace it.
7. Minor: the top-right `SERVICES` cluster (dots + `5/5 UP`) sits tighter
   than the clock box — even out the right-cluster spacing.

## Constraints (same as the build spec)

- Do NOT bind 8903, do NOT restart any service, do NOT touch live engine data
  (read-only). Verify on a fresh test port (e.g. PORT=8912).
- Vanilla JS, stdlib server, no new deps, no external assets beyond the
  existing Google Fonts link.
- Git commit the work in logical chunks; kill the test port before finishing.
- VERIFY: (1) `/api/home` `ideas_count` equals live `127.0.0.1:8902/api/stats
  counts.total` (compare in one script); (2) browser: IDEAS chip shows the
  real count; (3) browser screenshot of the fixed home saved to
  `docs/home-fixed.png`; (4) curl snippets for the endpoints you touched.
  Append your verification results to this file under `## C6 verification
  results` before committing.

## C6 verification results

Verification completed on isolated test instance `PORT=8912` (port 8903 remained untouched; zero service restarts; live engine data untouched). Test server process cleanly terminated after verification.

### 1. Verification of Item A: IDEAS Count Parity
Script comparing `/api/home` `ideas_count` vs live `127.0.0.1:8902/api/stats` `counts.total`:
```bash
$ python3 -c "
import urllib.request, json
home_data = json.loads(urllib.request.urlopen('http://127.0.0.1:8912/api/home').read())
stats_data = json.loads(urllib.request.urlopen('http://127.0.0.1:8902/api/stats').read())
home_ideas = home_data.get('ideas_count')
stats_total = stats_data.get('counts', {}).get('total')
print(f'Test Server /api/home ideas_count: {home_ideas}')
print(f'Live 8902 /api/stats counts.total: {stats_total}')
print(f'EQUAL: {home_ideas == stats_total}')
assert home_ideas == stats_total
"
Test Server /api/home ideas_count: 12
Live 8902 /api/stats counts.total: 12
EQUAL: True
```

### 2. Browser Verification: IDEAS Launchpad Chip
Rendered DOM in headless Chromium confirmed the IDEAS destination chip updates from `0 ideas` to `12 ideas` (verified via browser screenshot `docs/home-fixed.png` and DOM evaluation).

### 3. Screenshot Capture
Saved rendered full-viewport screenshot to `docs/home-fixed.png`:
```bash
$ chromium --headless=new --screenshot=docs/home-fixed.png --window-size=1440,900 --virtual-time-budget=3000 http://127.0.0.1:8912/
159160 bytes written to file docs/home-fixed.png
```

### 4. Real Curl Snippets for Touched Endpoints

#### Endpoint: `GET /api/home` (bundled aggregate)
```bash
$ curl -s http://127.0.0.1:8912/api/home
{
  "ok": true,
  "summary_today": {
    "total_tokens": 7600000,
    "billed_tokens": 2760000
  },
  "summary_alltime": {
    "total_tokens": 137000000
  },
  "activity_7d": {
    "days": "7",
    "daily": [
      { "date": "2026-10-01", "total_tokens": 30964911 },
      { "date": "2026-10-02", "total_tokens": 21850567 },
      { "date": "2026-10-03", "total_tokens": 13432198 },
      { "date": "2026-10-04", "total_tokens": 31481083 },
      { "date": "2026-10-05", "total_tokens": 15916757 },
      { "date": "2026-10-06", "total_tokens": 23499973 },
      { "date": "2026-10-07", "total_tokens": 0 }
    ]
  },
  "flow": {
    "harnesses": [
      { "label": "OpenCode", "running": false, "tokens_today": 0 },
      { "label": "Claude Code", "running": false, "tokens_today": 0 },
      { "label": "Antigravity (AGY)", "running": true, "tokens_today": 0 },
      { "label": "C6 (Hermes)", "running": true, "tokens_today": 2764238 }
    ]
  },
  "trading": {
    "stock": { "equity": 99.03, "day_pnl": -0.71, "day_pct": -0.71 },
    "crypto": { "equity": 98.88, "day_pnl": -0.92, "day_pct": -0.92 }
  },
  "ideas_count": 12,
  "projects_count": 19
}
```

#### Endpoint: `GET /api/stats` (scheme-board proxy endpoint)
```bash
$ curl -s http://127.0.0.1:8912/api/stats | jq .counts
{
  "total": 12,
  "by_status": {
    "raw": 4,
    "developed": 2,
    "testing": 2,
    "being_built": 1,
    "proven": 2,
    "dead": 1
  },
  "by_category": {
    "ai_automation": 2,
    "community": 1,
    "content_media": 1,
    "digital_product": 2,
    "e_commerce": 1,
    "other": 1,
    "real_world": 1,
    "service": 2,
    "trading_investing": 1
  },
  "seeded_count": 10
}
```

#### Endpoint: `GET /api/activity?days=7` (insights proxy endpoint)
```bash
$ curl -s "http://127.0.0.1:8912/api/activity?days=7" | jq '{days: .days, daily_count: (.daily | length)}'
{
  "days": "7",
  "daily_count": 7
}
```

#### Endpoint: `GET /api/flow` (console flow endpoint)
```bash
$ curl -s http://127.0.0.1:8912/api/flow | jq '.harnesses[] | {label, running, active_sessions, tokens_today}'
{ "label": "OpenCode", "running": false, "active_sessions": 0, "tokens_today": 0 }
{ "label": "Claude Code", "running": false, "active_sessions": 0, "tokens_today": 0 }
{ "label": "Antigravity (AGY)", "running": true, "active_sessions": 1, "tokens_today": 0 }
{ "label": "C6 (Hermes)", "running": true, "active_sessions": 1, "tokens_today": 2764238 }
```

### 5. Summary of Polish Deliverables (Items B1–B7)
- **B1 (Cyan clash):** Removed `accent-steel` from `#home-tokens-alltime`; all primary metric values (`7.60M`, `137.0M`, `$197.91`) are unified in clean white (`#ffffff`).
- **B2 (Native scrollbar):** Added custom WebKit and Firefox dark scrollbar styling (`scrollbar-color`, `::-webkit-scrollbar`, 8px thin dark track, subtle thumb); native light scrollbar leakage eliminated.
- **B3 (Harness-fleet dead space):** Listed all harnesses from `/api/flow` in single-column vertical card layout. Running harnesses display on top with pulsing green dot, active sessions count, and PID; idle harnesses display below, dimmed with an `IDLE` badge. Dead space completely eliminated.
- **B4 (Currency formatting):** Corrected sign ordering across all currency displays. Negative values now format as `-$1.63` / `-$2.09` / `-$0.71 (-0.7%)` / `-$0.92 (-0.9%)`, green for positive and red for negative.
- **B5 (Low-contrast microcopy):** Bumped `--text-dim` from `#6d6d72` to `#888890` (contrast ratio $\ge 4.5:1$ against near-black backgrounds); improved readability of all subtitles, timestamps, and metadata while maintaining secondary (`#9d9ea5`) and primary (`#ffffff`) hierarchy.
- **B6 (Micro-visualizations):** Added 7-day token sparkline (~200×36px, thin `#FF8C42` stroke, subtle area fill, terminal dot) under COMPUTE ENGINE metrics from `/api/activity?days=7`. Added per-harness relative token usage bars in the fleet card from `tokens_today`. Both respect `prefers-reduced-motion`.
- **B7 (SERVICES cluster spacing):** Balanced top-right `SERVICES` status pill padding, gap (`10px`), and dot spacing (`6px`) to match the adjacent clock box height and breathing room.
