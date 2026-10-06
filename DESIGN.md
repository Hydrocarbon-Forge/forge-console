# Hydrocarbon Forge Console — HOME Dashboard Design Specification

## 1. Design Study & Architectural Philosophy

### The "Forge" Concept
Hydrocarbon Forge is not a generic software dashboard or an off-the-shelf observability tool. Its foundational identity is physical, industrial, and transformative:
> *"You bring the weird idea. We forge the whole thing."*

A forge is an energetic crucible where raw, unrefined material (wild pitches, user prompts, token inference, code fragments) is subjected to computational heat and forged into resilient, production-grade machines (bots, web apps, tools, games, automated trading desks).

In our design study, we explored three distinct paradigms:
1. **The Smelting Hearth (Thermal Core)**: A purely radial/crucible interface centered on a heat gradient from input to output. *Critique*: High thematic atmosphere, but compromises rectangular scanning speed and tabular data density.
2. **The Hexagonal Master Terminal (Aerospace Switchboard)**: A dense geometric matrix of hardware-style telemetry. *Critique*: Highly functional, but risks feeling like a retro sci-fi novelty rather than a modern, elegant engineering platform.
3. **The Living Foundry Floor / Master Control Bay (Chosen Direction)**: A synthesis combining an unmistakable living brand signature with ruthless ergonomic clarity. An architectural ambient layer (slow spinning hex ring + breathing thermal glow) anchors the console, while high-contrast, hairline-bordered industrial bays present live metrics with zero cognitive friction.

---

## 2. Layout Grammar & Information Architecture

The HOME viewport is structured as a non-scrolling, high-density command deck organized into three primary operational tiers:

```
+-------------------------------------------------------------------------------------------------------+
| TOPBAR: Brand Mark  |  [Home] [Insights] [Ideas] [Flow] [Projects] [Office]  |  Services Strip  Clock ? |
+-------------------------------------------------------------------------------------------------------+
| HERO REVEAL: Live Foundry Focal Mark (Slow 90s Orbiting #hf-ring + 9s Luminous Breath Backdrop)      |
|                                                                                                       |
| +---------------------------------------------------+ +-----------------------------------------------+ |
| | OPERATIONAL HORIZON: COMPUTE HEAT                 | | OPERATIONAL HORIZON: OFFICE TREASURY          | |
| | - Today's Tokens (Billed & Total) + All-Time Sum  | | - Total Equity, Day P/L, Total P/L            | |
| | - Activity Pulse & Token Tween Gauges             | | - Stock & Crypto Split + Holdings Count       | |
| +---------------------------------------------------+ +-----------------------------------------------+ |
|                                                                                                       |
| +---------------------------------------------------+ +-----------------------------------------------+ |
| | ACTIVE HARNESS FLEET                              | | ACTIVE FORGE WORKBENCH                        | |
| | - Running harnesses (Antigravity, C6, Claude...)  | | - Projects modified in last 60m               | |
| | - Live pulsing status pips, sessions, PIDs        | | - Change velocity, file counts, last write    | |
| +---------------------------------------------------+ +-----------------------------------------------+ |
|                                                                                                       |
| +---------------------------------------------------------------------------------------------------+ |
| | DESTINATION LAUNCHPADS (Tactile Monoliths with Live Telemetry Chips)                               | |
| |  [ INSIGHTS ]     [ IDEAS ]        [ FLOW ]         [ PROJECTS ]     [ OFFICE ]                   | |
| |  Token telemetry  Idea graph & DB  System canvas    Directory & DB   Desk & Trading               | |
| +---------------------------------------------------------------------------------------------------+ |
+-------------------------------------------------------------------------------------------------------+
```

### Component Hierarchy
1. **The Ambient Foundry Stage**:
   - Anchored behind the top metric row is the `#hf-ring` SVG symbol (`width: min(45vw, 560px)`), slowly rotating at `90s linear infinite` with `color: rgba(255, 140, 66, 0.04)`.
   - Centered inside is a soft radial breath glow (`9s ease-in-out infinite`) providing depth without obstructing foreground contrast.
2. **Tier 1: Operational Horizons**:
   - **Compute Core (Tokens)**: Features big JetBrains Mono numerals with uppercase Oswald labels. Displays today's `total_tokens` (and sub-labeled `billed_tokens`), alongside all-time tokens formatted cleanly (e.g., `135.1M`).
   - **Office Treasury (Trading)**: Real-time net equity across books (`$197.91`), with Day P/L and Total P/L chips color-coded green (`#3DDC84`) or red (`#F25C54`) based on sign. Displays Stock (`META`, `AMD`, `CRWD`...) vs Crypto (`AVAX`, `LINK`, `SOL`...) breakdown and holding counts. Clickable to jump straight to the Office pane.
3. **Tier 2: The Living Engines**:
   - **Active Harnesses**: Lists active agent harnesses (`antigravity`, `c6`, etc.) with a pulsing emerald/amber live dot, process ID tags, and active session counts. Displays a clean "No active harnesses" status badge when idle.
   - **Active Projects**: Lists projects receiving changes in the past 60 minutes (`forge-console`, `forge-office`, `stock-playground`) with change count pills and relative time badges. Falls back gracefully to recently modified projects if none were edited in the last hour.
4. **Tier 3: The Five Destination Launchpads**:
   - Large, clickable destination cards (`INSIGHTS`, `IDEAS`, `FLOW`, `PROJECTS`, `OFFICE`).
   - Each card hosts a dedicated 24px line SVG icon, an Oswald title, a 1-line description, and an at-a-glance dynamic telemetry chip (e.g. `21.4M tkns`, `19 projects`, `3/3 UP`, `$197.91 eq`).

---

## 3. Kinetic & Motion Language

The motion system directly imports the signature vocabulary established by the Hydrocarbon Forge web identity:
- **Orbital Spin**: `@keyframes spin { to { transform: rotate(360deg); } }` at 90s linear infinite for the faint background `#hf-ring`.
- **Luminous Breathe**: `@keyframes breathe { 0%, 100% { opacity: 0.5; transform: scale(1); } 50% { opacity: 0.9; transform: scale(1.08); } }` at 9s ease-in-out infinite.
- **Micro-Pulse**: `@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }` for active harness and service status indicators with hexagonal clip paths.
- **Entrance Reveal**: Staggered entrance animations on page mount using `.reveal-in` (`opacity: 0, translateY(16px)` transitions smoothly to `opacity: 1, translateY(0)` with `cubic-bezier(0.2, 0.8, 0.2, 1)` over 450ms).
- **Number Tweens**: Subtle count-up tweening (~400ms ease-out) on numeric cards when updated.
- **Accessibility & Reduced Motion**:
  - Full `@media (prefers-reduced-motion: reduce)` support: all background spins, breathing scales, and entrance translations are disabled, rendering clean static elements.

---

## 4. Color, Materials & Typography

### Palette Tokens
- **Chassis Base**: `--bg: #0a0a0a` with `--hex-pattern` faint background lattice.
- **Panel Surface**: `--panel: #121212` and `--card: #151515` with `--border: rgba(255, 255, 255, 0.08)`.
- **Forge Heat Accent**: `--accent: #FF8C42` (Forge Orange) used for active tabs, heat badges, hover borders, and hero ring highlights.
- **Status Accents**:
  - Positive / Live: `--accent-green: #3DDC84`
  - Warning / Caution: `--accent-amber: #FFB454`
  - Alert / Negative: `--accent-red: #F25C54`
  - Steel / Tech: `--accent-steel: #5AA9E6`
  - Machine Purple: `--accent-purple: #B185DB`

### Typography Hierarchy
- **Display & Section Kickers**: `Oswald` (weights 500, 600, 700) in condensed uppercase with letter spacing `0.08em`–`0.14em`.
- **Primary Data Readouts**: `JetBrains Mono` (weights 500, 600, 700) for all currency, token metrics, percentages, and timestamps.
- **Descriptive Body**: `Inter` (weight 400, 500) for readable subtitles and functional guides.

---

## 5. Navigation & Ergonomics

### Six-Tab Icon Bar
Replacing the numbered labels with bespoke line SVG icons (viewBox `0 0 24 24`, `stroke-width: 1.8`, `stroke: currentColor`):
1. **Home**: Hexagonal shelter mark with centered core dot (`M12 2L20.66 7V17L12 22L3.34 17V7L12 2Z`).
2. **Insights**: Telemetry activity / sparkline pulse gauge (`polyline 3 12 7 12 10 5 14 19 17 12 21 12`).
3. **Ideas**: Hexagonal node cluster / sparked thought matrix.
4. **Flow**: Connected network graph nodes and directional data conduits.
5. **Projects**: Multi-tiered hexagonal component layers / directory repository.
6. **Office**: Architectural building grid / command outpost.

### Shortcut & Routing Conventions
- Direct keyboard switching: `1`=Home, `2`=Insights, `3`=Ideas, `4`=Flow, `5`=Projects, `6`=Office.
- Dim, elegant key hints displayed unobtrusively on hover or in the shortcut modal (`?`).
- Hash routing preserves deep links: `#/`, `#/home`, `#/insights`, `#/ideas`, `#/flow`, `#/projects`, `#/office`.
