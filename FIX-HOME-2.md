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
