#!/usr/bin/env python3
"""Daily token usage report generator for Hydrocarbon Forge.

Generates:
1. usage-report.png: Dark Discord-native styled bar chart for last 7 ET days (tokens in / out).
2. report.txt: Compact, skimmable text summary under 8 lines.
3. embed.json: Ready-to-POST Discord embed object with dynamic activity status.

Only uses Python stdlib + PIL + numpy.
"""

from datetime import datetime, timedelta
import json
import os
import sys
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo
import numpy as np
from PIL import Image, ImageDraw, ImageFont

BOARD_BASE = os.environ.get("INSIGHTS_BOARD_URL", "http://127.0.0.1:8901")
TZ = ZoneInfo("America/New_York")
FONTS_DIR = "/usr/share/fonts/truetype/dejavu"


def fetch_json(endpoint: str, timeout: float = 10.0):
  """Fetch and parse JSON from the insights-board API."""
  url = f"{BOARD_BASE}{endpoint}"
  req = urllib.request.Request(url, headers={"User-Agent": "DailyUsageReport/2.0"})
  try:
    with urllib.request.urlopen(req, timeout=timeout) as resp:
      return json.loads(resp.read().decode("utf-8"))
  except Exception as e:
    return {"error": str(e)}


def fmt_compact(n: float | int | None) -> str:
  """Format numbers into compact strings with clean precision (e.g. 1.2K, 2.6M, 47.4M, 901K)."""
  n = float(n or 0)
  if n >= 1_000_000:
    val = n / 1_000_000
    return f"{val:.1f}M"
  if n >= 10_000:
    return f"{round(n / 1_000)}K"
  if n >= 1_000:
    val = n / 1_000
    s = f"{val:.1f}K"
    return s[:-3] + "K" if s.endswith(".0K") else s
  return str(int(round(n)))


def fmt_money(v: float | int | None) -> str:
  """Format USD currency."""
  v = float(v or 0)
  return f"${v:.2f}"


def load_font(filename: str, size: int) -> ImageFont.FreeTypeFont:
  """Load DejaVu font with fallback to default."""
  path = os.path.join(FONTS_DIR, filename)
  try:
    return ImageFont.truetype(path, size)
  except Exception:
    return ImageFont.load_default()


def collect_data():
  """Collect usage metrics across all platform endpoints."""
  now = datetime.now(TZ)
  today = now.date()
  day_dates = [today - timedelta(days=i) for i in range(6, -1, -1)]
  day_strs = [d.isoformat() for d in day_dates]
  yesterday = today - timedelta(days=1)
  yesterday_str = yesterday.isoformat()

  # Platform sources to query
  source_defs = [
      ("opencode", "opencode"),
      ("claudecode", "Claude Code"),
      ("antigravity", "Antigravity"),
      ("hermes", "Hermes"),
  ]

  sources = []
  for key, label in source_defs:
    data = fetch_json(f"/api/{key}?days=all")
    if data.get("error") and key == "hermes":
      # Fallback to Hermes summary endpoint if /api/hermes 404s
      h = fetch_json("/api/summary?days=all")
      if not h.get("error"):
        data = {
            "total": {
                "input_tokens": h.get("input_tokens", 0),
                "output_tokens": h.get("output_tokens", 0),
                "cache_read_tokens": h.get("cache_read_tokens", 0),
                "cache_write_tokens": h.get("cache_write_tokens", 0),
                "reported_cost_usd": (h.get("estimated_cost_usd") or 0)
                + (h.get("actual_cost_usd") or 0),
            },
            "sessions": h.get("sessions", 0),
            "daily": [],
            "models": [],
        }
    if not data.get("error"):
      sources.append((label, data))

  # Aggregate by ET day (last 7 days)
  by_day = {
      ds: {
          "in": 0,
          "out": 0,
          "cache_read": 0,
          "cache_write": 0,
          "sess": 0,
      }
      for ds in day_strs
  }

  for label, data in sources:
    for day in data.get("daily", []):
      ds = day.get("date")
      if ds in by_day:
        by_day[ds]["in"] += int(day.get("input_tokens", 0) or 0)
        by_day[ds]["out"] += int(day.get("output_tokens", 0) or 0)
        by_day[ds]["cache_read"] += int(day.get("cache_read_tokens", 0) or 0)
        by_day[ds]["cache_write"] += int(day.get("cache_write_tokens", 0) or 0)
        by_day[ds]["sess"] += int(day.get("sessions", 0) or 0)

  # Today totals
  today_str = today.isoformat()
  today_data = by_day.get(
      today_str,
      {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0, "sess": 0},
  )

  # Yesterday totals for delta
  yest_data = by_day.get(
      yesterday_str,
      {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0, "sess": 0},
  )
  yest_total = yest_data["in"] + yest_data["out"]
  today_total = today_data["in"] + today_data["out"]

  delta_str = ""
  delta_pct = None
  if yest_total > 0:
    delta_pct = round(((today_total - yest_total) / yest_total) * 100)
    if delta_pct > 0:
      delta_str = f" — ▲ {delta_pct}% vs yesterday"
    elif delta_pct < 0:
      delta_str = f" — ▼ {abs(delta_pct)}% vs yesterday"
    else:
      delta_str = " — 0% vs yesterday"

  # All-time totals across sources
  all_time = {"in": 0, "out": 0, "cache_read": 0, "cost": 0.0, "sess": 0}
  for label, data in sources:
    t = data.get("total") or {}
    all_time["in"] += int(t.get("input_tokens", 0) or 0)
    all_time["out"] += int(t.get("output_tokens", 0) or 0)
    all_time["cache_read"] += int(t.get("cache_read_tokens", 0) or 0)
    all_time["cost"] += float(t.get("reported_cost_usd", 0) or 0)
    all_time["sess"] += int(data.get("sessions", 0) or 0)

  # Today per-source breakdown
  today_by_src = []
  for label, data in sources:
    for day in data.get("daily", []):
      if day.get("date") == today_str:
        s_in = int(day.get("input_tokens", 0) or 0)
        s_out = int(day.get("output_tokens", 0) or 0)
        if s_in > 0 or s_out > 0 or day.get("sessions", 0):
          today_by_src.append((label, s_in, s_out))
        break

  # Top model all-time (by input + output tokens)
  all_models = []
  for label, data in sources:
    for m in data.get("models", []):
      m_toks = int(m.get("input_tokens", 0) or 0) + int(
          m.get("output_tokens", 0) or 0
      )
      m_name = m.get("model", "unknown")
      all_models.append((m_toks, m_name))
  all_models.sort(key=lambda x: x[0], reverse=True)
  top_model_toks, top_model_raw = all_models[0] if all_models else (0, "none")
  top_model_name = (
      top_model_raw.split(":", 1)[-1]
      if ":" in top_model_raw
      else top_model_raw
  )

  return {
      "now": now,
      "today": today,
      "day_dates": day_dates,
      "day_strs": day_strs,
      "by_day": by_day,
      "today_data": today_data,
      "today_total": today_total,
      "yest_total": yest_total,
      "delta_pct": delta_pct,
      "delta_str": delta_str,
      "all_time": all_time,
      "today_by_src": today_by_src,
      "top_model_name": top_model_name,
      "top_model_toks": top_model_toks,
  }


def render_chart(data, out_path: str):
  """Render high-contrast, polished dark Discord-native usage chart (1200x675)."""
  w, h = 1200, 675
  # Canvas base: Discord dark #1e1f22
  canvas = Image.new("RGBA", (w, h), (30, 31, 34, 255))
  draw = ImageDraw.Draw(canvas)

  # Inner Card Panel: #232428 with subtle #2f3136 border
  card_box = [24, 20, w - 24, h - 20]
  draw.rounded_rectangle(
      card_box,
      radius=16,
      fill=(35, 36, 40, 255),
      outline=(47, 49, 54, 255),
      width=1,
  )

  # Fonts
  font_title = load_font("DejaVuSans-Bold.ttf", 24)
  font_sub = load_font("DejaVuSans.ttf", 13)
  font_legend = load_font("DejaVuSans-Bold.ttf", 13)
  font_axis = load_font("DejaVuSans.ttf", 12)
  font_day = load_font("DejaVuSans-Bold.ttf", 15)
  font_date = load_font("DejaVuSans.ttf", 12)
  font_sess = load_font("DejaVuSans.ttf", 11)
  font_bar_val = load_font("DejaVuSans-Bold.ttf", 11)
  font_badge = load_font("DejaVuSans-Bold.ttf", 10)

  # Header
  title_text = "Token usage — last 7 days (ET)"
  draw.text((56, 42), title_text, fill=(242, 243, 245), font=font_title)

  start_str = data["day_dates"][0].strftime("%b %d")
  end_str = data["day_dates"][-1].strftime("%b %d, %Y")
  sub_text = f"{start_str} – {end_str} · Daily snapshot"
  draw.text((56, 76), sub_text, fill=(148, 155, 164), font=font_sub)

  # Delta badge next to subtitle if delta available
  if data["delta_pct"] is not None:
    pct = data["delta_pct"]
    sub_bbox = font_sub.getbbox(sub_text)
    badge_x = 56 + (sub_bbox[2] - sub_bbox[0]) + 16
    badge_y = 74
    if pct > 0:
      b_txt = f"▲ {pct}% vs yesterday"
      b_bg = (35, 60, 48, 255)
      b_border = (45, 120, 75, 255)
      b_fg = (87, 242, 135, 255)
    elif pct < 0:
      b_txt = f"▼ {abs(pct)}% vs yesterday"
      b_bg = (60, 35, 40, 255)
      b_border = (120, 50, 60, 255)
      b_fg = (242, 87, 87, 255)
    else:
      b_txt = "— 0% vs yesterday"
      b_bg = (45, 48, 55, 255)
      b_border = (70, 75, 85, 255)
      b_fg = (180, 185, 195, 255)

    tb = font_badge.getbbox(b_txt)
    bw = (tb[2] - tb[0]) + 16
    bh = 18
    draw.rounded_rectangle(
        [badge_x, badge_y, badge_x + bw, badge_y + bh],
        radius=9,
        fill=b_bg,
        outline=b_border,
        width=1,
    )
    draw.text(
        (badge_x + bw // 2, badge_y + bh // 2),
        b_txt,
        fill=b_fg,
        font=font_badge,
        anchor="mm",
    )

  # Legend on top right
  # In Pill: #5865f2 Blurple
  draw.rounded_rectangle(
      [860, 54, 878, 66], radius=3, fill=(88, 101, 242, 255)
  )
  draw.text((886, 60), "Tokens In", fill=(219, 222, 225), font=font_legend, anchor="lm")
  # Out Pill: #57f287 Mint Green
  draw.rounded_rectangle(
      [980, 54, 998, 66], radius=3, fill=(87, 242, 135, 255)
  )
  draw.text(
      (1006, 60), "Tokens Out", fill=(219, 222, 225), font=font_legend, anchor="lm"
  )

  # Plot area geometry
  plot_l, plot_r = 110, 1140
  plot_t, plot_b = 130, 535
  plot_w = plot_r - plot_l
  plot_h = plot_b - plot_t

  # Compute nice Y-axis max with ~4 horizontal gridlines (3 intervals)
  all_vals = []
  for ds in data["day_strs"]:
    all_vals.append(data["by_day"][ds]["in"])
    all_vals.append(data["by_day"][ds]["out"])
  max_val = max(all_vals) if all_vals else 0
  if max_val == 0:
    max_val = 100_000

  headroom_target = max_val * 1.15
  nice_steps = [
      10_000,
      25_000,
      50_000,
      100_000,
      200_000,
      250_000,
      500_000,
      750_000,
      1_000_000,
      1_500_000,
      2_000_000,
      2_500_000,
      3_000_000,
      4_000_000,
      5_000_000,
      10_000_000,
      20_000_000,
      50_000_000,
  ]
  chosen_step = nice_steps[-1]
  for st in nice_steps:
    if st * 3 >= headroom_target:
      chosen_step = st
      break

  y_max = chosen_step * 3
  ticks = [0, chosen_step, chosen_step * 2, y_max]

  # Draw horizontal gridlines and Y-axis labels
  for tick in ticks:
    gy = plot_b - int((tick / y_max) * plot_h)
    line_color = (64, 66, 73, 255) if tick == 0 else (45, 48, 54, 255)
    draw.line([(plot_l, gy), (plot_r, gy)], fill=line_color, width=1)
    lbl = fmt_compact(tick)
    draw.text(
        (plot_l - 12, gy),
        lbl,
        fill=(128, 132, 142),
        font=font_axis,
        anchor="rm",
    )

  # Day slots (7 days)
  slot_w = plot_w / 7.0
  bar_w = 34
  bar_gap = 6

  for i, d_date in enumerate(data["day_dates"]):
    ds = d_date.isoformat()
    day_entry = data["by_day"][ds]
    is_today = d_date == data["today"]
    center_x = plot_l + i * slot_w + slot_w / 2.0
    slot_x0 = plot_l + i * slot_w
    slot_x1 = slot_x0 + slot_w

    # Highlight column for Today: soft translucent Blurple card behind today's bars
    if is_today:
      overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
      odraw = ImageDraw.Draw(overlay)
      odraw.rounded_rectangle(
          [slot_x0 + 8, plot_t - 5, slot_x1 - 8, plot_b + 5],
          radius=10,
          fill=(88, 101, 242, 22),
          outline=(88, 101, 242, 60),
          width=1,
      )
      canvas = Image.alpha_composite(canvas, overlay)
      draw = ImageDraw.Draw(canvas)

    # In and Out bar coordinates
    x0_in = center_x - bar_gap / 2.0 - bar_w
    x1_in = center_x - bar_gap / 2.0
    x0_out = center_x + bar_gap / 2.0
    x1_out = center_x + bar_gap / 2.0 + bar_w

    in_val = day_entry["in"]
    out_val = day_entry["out"]

    in_h = int((in_val / y_max) * plot_h)
    out_h = int((out_val / y_max) * plot_h)

    # Palette
    if is_today:
      color_in = (88, 101, 242, 255)  # Bright Blurple
      color_out = (87, 242, 135, 255)  # Bright Mint
      text_color = (255, 255, 255)
    else:
      color_in = (71, 82, 196, 255)  # Muted Blurple
      color_out = (35, 165, 90, 255)  # Muted Green
      text_color = (181, 186, 193)

    # Render In Bar
    if in_h > 0:
      y0_in = plot_b - in_h
      r_in = min(6, in_h)
      draw.rounded_rectangle(
          [x0_in, y0_in, x1_in, plot_b],
          radius=r_in,
          fill=color_in,
          corners=(True, True, False, False),
      )
      # Value label above bar
      draw.text(
          ((x0_in + x1_in) / 2.0, y0_in - 6),
          fmt_compact(in_val),
          fill=text_color,
          font=font_bar_val,
          anchor="mb",
      )
    else:
      draw.rectangle([x0_in, plot_b - 2, x1_in, plot_b], fill=(50, 52, 58, 255))

    # Render Out Bar
    if out_h > 0:
      y0_out = plot_b - out_h
      r_out = min(6, out_h)
      draw.rounded_rectangle(
          [x0_out, y0_out, x1_out, plot_b],
          radius=r_out,
          fill=color_out,
          corners=(True, True, False, False),
      )
      # Value label above bar
      draw.text(
          ((x0_out + x1_out) / 2.0, y0_out - 6),
          fmt_compact(out_val),
          fill=text_color,
          font=font_bar_val,
          anchor="mb",
      )
    else:
      draw.rectangle(
          [x0_out, plot_b - 2, x1_out, plot_b], fill=(50, 52, 58, 255)
      )

    # X-axis Day of week (Mon–Sun short form)
    day_name = d_date.strftime("%a")
    draw.text(
        (center_x, 552),
        day_name,
        fill=(255, 255, 255) if is_today else (181, 186, 193),
        font=font_day,
        anchor="mt",
    )

    # Date (e.g. Oct 02)
    date_name = d_date.strftime("%b %d")
    draw.text(
        (center_x, 574),
        date_name,
        fill=(148, 155, 164) if is_today else (109, 114, 122),
        font=font_date,
        anchor="mt",
    )

    # Session marker
    sess_cnt = day_entry["sess"]
    sess_str = f"{sess_cnt} sess"
    sess_color = (
        (87, 242, 135)
        if (is_today and sess_cnt > 0)
        else ((128, 132, 142) if sess_cnt > 0 else (78, 80, 88))
    )
    draw.text(
        (center_x, 594), sess_str, fill=sess_color, font=font_sess, anchor="mt"
    )

    # If Today: draw accent TODAY pill badge and underline
    if is_today:
      pill_w, pill_h = 52, 18
      pill_x0 = center_x - pill_w / 2.0
      pill_y0 = 616
      draw.rounded_rectangle(
          [pill_x0, pill_y0, pill_x0 + pill_w, pill_y0 + pill_h],
          radius=9,
          fill=(88, 101, 242, 255),
      )
      draw.text(
          (center_x, pill_y0 + pill_h / 2.0),
          "TODAY",
          fill=(255, 255, 255),
          font=font_badge,
          anchor="mm",
      )

  # Convert to RGB and save PNG
  final_img = canvas.convert("RGB")
  final_img.save(out_path, format="PNG", optimize=True)


def build_text_report(data) -> str:
  """Build compact, skimmable summary under 8 lines."""
  now = data["now"]
  t = data["today_data"]
  all_t = data["all_time"]

  # Header with 10 PM ET style snapshot label
  time_label = now.strftime("%-I %p ET") if hasattr(now, "strftime") else "ET"
  date_header = (
      f"📊 Daily usage — {now.strftime('%a %b %d, %Y')} ({time_label})"
  )

  # Today line
  today_line = (
      f"• Today: {fmt_compact(t['in'])} in / {fmt_compact(t['out'])} out"
      f" ({t['sess']} sessions){data['delta_str']}"
  )

  # Per-source breakdown line (only if today is non-zero)
  src_parts = []
  for label, s_in, s_out in data["today_by_src"]:
    src_parts.append(f"{label} {fmt_compact(s_in)} in / {fmt_compact(s_out)} out")
  src_line = f"  {' · '.join(src_parts)}" if src_parts else None

  # All-time line
  all_time_line = (
      f"• All-time: {fmt_compact(all_t['in'])} in /"
      f" {fmt_compact(all_t['out'])} out · {all_t['sess']} sessions ·"
      f" {fmt_money(all_t['cost'])}"
  )

  # Top model line
  top_model_line = f"• Top model: {data['top_model_name']}"

  # Cache reads today note
  cache_read = t["cache_read"]
  cache_write = t["cache_write"]
  write_note = (
      f" ({fmt_compact(cache_write)} writes)" if cache_write > 0 else ""
  )
  cache_line = (
      f"• Cache reads today: {fmt_compact(cache_read)}{write_note} — note only"
  )

  lines = [date_header, today_line]
  if src_line:
    lines.append(src_line)
  lines.append(all_time_line)
  lines.append(top_model_line)
  lines.append(cache_line)

  return "\n".join(lines) + "\n"


def build_embed(data) -> dict:
  """Build Discord embed object."""
  now = data["now"]
  today = data["today"]
  t = data["today_data"]
  all_t = data["all_time"]

  # Color: green #57f287 active / amber #f0b232 quiet / gray #9599a6 idle
  if t["sess"] >= 5 or data["today_total"] >= 100_000:
    color = 0x57F287  # active
  elif t["sess"] > 0 or data["today_total"] > 0:
    color = 0xF0B232  # quiet
  else:
    color = 0x9599A6  # idle

  title = f"Daily usage — {today.strftime('%a %b %d')} (ET)"

  # Human summary description
  if data["today_total"] > 0:
    desc = (
        f"Today recorded {fmt_compact(t['in'])} in and {fmt_compact(t['out'])}"
        f" out across {t['sess']} sessions{data['delta_str']}."
    )
  else:
    desc = (
        f"No token activity recorded today ({today.strftime('%a %b %d')})."
        " Systems idle."
    )

  fields = [
      {
          "name": "Today",
          "value": (
              f"{fmt_compact(t['in'])} in / {fmt_compact(t['out'])} out ·"
              f" {t['sess']} sess"
          ),
          "inline": True,
      },
      {
          "name": "All-time",
          "value": (
              f"{fmt_compact(all_t['in'])} in / {fmt_compact(all_t['out'])} out"
              f" · {all_t['sess']} sess · {fmt_money(all_t['cost'])}"
          ),
          "inline": True,
      },
      {
          "name": "Top model",
          "value": (
              f"`{data['top_model_name']}` ·"
              f" {fmt_compact(data['top_model_toks'])}"
          ),
          "inline": True,
      },
  ]

  footer_time = now.strftime("%-I:%M %p ET")
  embed = {
      "title": title,
      "description": desc,
      "color": color,
      "fields": fields,
      "footer": {
          "text": f"insights-board · generated {footer_time}",
      },
      "timestamp": now.isoformat(),
      "image": {"url": ""},
  }
  return embed


def main():
  out_dir = (
      sys.argv[1]
      if len(sys.argv) > 1
      else os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
  )
  os.makedirs(out_dir, exist_ok=True)

  # Collect data
  data = collect_data()

  # Output file paths
  chart_file = os.path.join(out_dir, "usage-report.png")
  report_file = os.path.join(out_dir, "report.txt")
  embed_file = os.path.join(out_dir, "embed.json")

  # 1. Render chart PNG
  render_chart(data, chart_file)

  # 2. Write text summary
  report_text = build_text_report(data)
  with open(report_file, "w", encoding="utf-8") as f:
    f.write(report_text)

  # 3. Write Discord embed JSON
  embed_obj = build_embed(data)
  with open(embed_file, "w", encoding="utf-8") as f:
    json.dump(embed_obj, f, indent=2, ensure_ascii=False)

  print(f"Report generated successfully in {out_dir}:")
  print(f"  Chart: {chart_file}")
  print(f"  Text:  {report_file}")
  print(f"  Embed: {embed_file}")


if __name__ == "__main__":
  main()
