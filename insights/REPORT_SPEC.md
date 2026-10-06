# Daily Usage Report — Visual Redesign

## Context
Hydrocarbon Forge (Discord-centric dev team) gets a daily token-usage report at 10 PM ET,
posted to the Discord channel #usage (via cron job `daily-usage-report`, no-agent script job).
The current report (`~/.hermes/scripts/daily_usage_report.py`, stdlib + PIL) is fine on data
but ugly in presentation. Nathan's feedback:

- The **cache-read column dwarfs everything** in the chart (50M+ vs ~2M in/out) → **exclude
  cache from the chart entirely**. Cache numbers stay only as a one-line note in the text summary.
- The text block is **busy and dense** → make it a short, skimmable, pleasant summary.
- Make it **flashy for Discord**: polished chart image + a Discord embed (colored border,
  fields, footer). Buttons/interaction components are NOT available (headless bot, no
  interaction handler) — so the "fancy" comes from the image design + embed layout, not widgets.

## Deliverables (all under this project dir)
1. `report/build_report.py` — the new generator. MUST run on system `python3` (3.14) with
   **stdlib + PIL + numpy** (all confirmed present; no other deps, no network beyond the API).
   CLI: `python3 report/build_report.py [out_dir]` (default `report/out/`).
   It must:
   - fetch from the insights-board at `http://127.0.0.1:8901` (endpoints + schemas below),
   - write `report/out/usage-report.png` — the main chart (design brief below),
   - write `report/out/report.txt` — the compact text summary,
   - write `report/out/embed.json` — a ready-to-POST Discord embed object (fields below).
   - All dates/labels in **America/New_York** (zoneinfo). "Today" = current ET day.
2. `report/README.md` — one-paragraph note on how to regenerate.
3. Run it once; verify all three artifacts exist and look right. Save the generated sample in
   `report/out/` for review. Do NOT post anything to Discord — a human (C6) posts it.
   Do NOT modify anything outside `report/`.

## Chart design brief (`usage-report.png`, ~1200x675 px, PNG)
- **Data:** last 7 ET days, grouped bars: **tokens in** and **tokens out ONLY** (no cache).
- **Style:** dark Discord-native theme (bg #1e1f22-ish panel, grid lines subtle #2b2d31).
  Distinct, pleasing hues for in/out (e.g. cyan #5865f2 / green #57f287 Discord-ish palette,
  or your taste — must be high-contrast on dark). Rounded bar tops, generous spacing,
  no clutter: max ~4 horizontal gridlines, values in compact form (2.6M / 901K / 12K).
- **Today's bar** highlighted (brighter + small "today" tag or accent underline).
- Title like "Token usage — last 7 days (ET)", day labels Mon–Sun short form.
- Optional tasteful extras: tiny session-count markers under the x-axis, a small sparkline
  strip or delta arrow vs previous day for "today". Keep it clean — less is more.
- No matplotlib required; PIL is fine. (numpy available if you want it.)

## Text summary (`report.txt`) — keep it under ~8 lines, e.g.:
```
📊 Daily usage — Fri Oct 02, 2026 (10 PM ET)
• Today: 2.6M in / 901K out (17 sessions) — ▲ 43% vs yesterday
• All-time: 47.4M in / 2.9M out · 65 sessions · $0.00
• Top model: claude-sonnet-4-5
• Cache reads today: 110.7M (13.2M writes) — note only
```
Rules: compact numbers (M/K), deltas vs yesterday with ▲/▼ (only when yesterday > 0),
cache appears in at most ONE short line, per-source breakdown only if today is non-zero
and fits in one line separated by ` · `. No giant tables — the chart carries the trend.

## Embed (`embed.json`) — Discord embed object:
- `color`: pick from today's activity (green #57f287 active / amber #f0b232 quiet / gray #9599a6 idle).
- `title`: `Daily usage — Fri Oct 02 (ET)`.
- `description`: 1–2 sentence human summary (today vs yesterday).
- `fields` (max 3): Today, All-time, Top model — short values.
- `footer.text`: `insights-board · generated 10:00 PM ET` + `timestamp`.
- `image.url` stays empty (C6 attaches the PNG as the message image separately).

## API (all GET, JSON, at http://127.0.0.1:8901)
- `/api/opencode`, `/api/claudecode`, `/api/antigravity`, `/api/hermes` → each:
  `{ total: {input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
     reported_cost_usd}, sessions: int, daily: [{date: "YYYY-MM-DD", input_tokens,
     output_tokens, cache_read_tokens, cache_write_tokens, sessions}],
     models: [{model, sessions, input_tokens, output_tokens, reported_cost_usd}] }`
  (some endpoints return 404 — handle gracefully, skip source.)
- `/api/summary?days=all` → flat totals: `{input_tokens, output_tokens,
  cache_read_tokens, cache_write_tokens, sessions, estimated_cost_usd,
  actual_cost_usd, total_tokens, ...}` (Hermes-only totals; prefer the per-source
  endpoints above; this is a fallback/cross-check).

## Constraints
- Timezone: `zoneinfo.ZoneInfo("America/New_York")` everywhere.
- Font: DejaVu at `/usr/share/fonts/truetype/dejavu/` (DejaVuSans.ttf, -Bold.ttf exist).
- Numbers: compact format (1.2K / 2.6M / 47.4M, one decimal).
- Robustness: an endpoint down or a day missing must not crash — degrade gracefully.
- System python3 is 3.14; verify with `python3 report/build_report.py` (exit 0).
- Do NOT install packages, do NOT touch Discord, do NOT edit files outside `report/`.

## Verify before finishing
1. `python3 report/build_report.py` exits 0.
2. `report/out/usage-report.png`, `report/out/report.txt`, `report/out/embed.json` exist.
3. `embed.json` is valid JSON.
4. Chart is visually sensible (you can check pixel dimensions and non-background pixel
   count; you cannot see the image — be conservative about layout math).
