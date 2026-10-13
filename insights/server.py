#!/usr/bin/env python3
"""Insights Board — local usage board for Hermes state.db.

Stdlib only. Read-only on the DB. Serves JSON API + static web/.
"""
import argparse
import json
import os
import re
import sqlite3
import time
import threading
from collections import Counter, defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

BASE_DIR = Path(__file__).resolve().parent
PRICING_PATH = BASE_DIR / "pricing.json"
WEB_DIR = BASE_DIR / "web"

DEFAULT_DB = os.environ.get("HERMES_DB") or os.path.expanduser("~/.hermes/state.db")
DEFAULT_OPENCODE_DB = os.environ.get("OPENCODE_DB") or os.path.expanduser("~/.local/share/opencode/opencode.db")

DB_PATH = DEFAULT_DB
OPENCODE_DB_PATH = DEFAULT_OPENCODE_DB
CACHE_TTL = 60

_CACHE = {}
_CACHE_LOCK = threading.Lock()
_LAST_BUILD = {"ts": 0.0}


def get_db_mtime():
    try:
        return os.path.getmtime(DB_PATH)
    except OSError:
        return 0.0


def get_opencode_mtime():
    try:
        return os.path.getmtime(OPENCODE_DB_PATH)
    except OSError:
        return 0.0


def open_ro():
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


def open_opencode_ro():
    return sqlite3.connect(f"file:{OPENCODE_DB_PATH}?mode=ro", uri=True)


def parse_days(qs):
    raw = qs.get("days", ["30"])
    v = raw[0] if raw else "30"
    if isinstance(v, list):
        v = v[0] if v else "30"
    v = str(v).strip().lower()
    if v == "all":
        return "all", None, None
    try:
        d = int(v)
    except (ValueError, TypeError):
        return "30", time.time() - 30 * 86400, 30
    if d not in (7, 30, 90, 365):
        # allow any positive int but spec lists these; default to given if positive
        if d <= 0:
            return "30", time.time() - 30 * 86400, 30
        return str(d), time.time() - d * 86400, d
    return str(d), time.time() - d * 86400, d


def cutoff_for(days_str, now=None):
    if now is None:
        now = time.time()
    if days_str == "all":
        return None
    try:
        d = int(days_str)
    except Exception:
        d = 30
    return now - d * 86400


# ---------- pricing ----------

def load_pricing():
    try:
        with open(PRICING_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"models": {}}
    if not isinstance(data, dict) or not isinstance(data.get("models"), dict):
        return {"models": {}}
    return data


def _candidates(model_id):
    m = str(model_id or "")
    low = m.lower()
    parts = []
    parts.append(low)
    if "/" in m:
        # basename (strip dir path)
        parts.append(m.rsplit("/", 1)[-1].lower())
        # strip provider prefix (after first slash)
        parts.append(m.split("/", 1)[1].lower())
    # also handle backslash paths just in case
    if "\\" in m:
        parts.append(m.rsplit("\\", 1)[-1].lower())
    # dedupe preserve order
    seen = set()
    out = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _pricing_base(model_id):
    """TASK5: source-prefix rule for the cost engine.

    Labels starting `claudecode:` / `antigravity:` strip the prefix and match
    the remainder against pricing keys AND `also` aliases. The `opencode:`
    prefix never matches pricing (free-tier via opencode-go). Unknowns stay
    unpriced.
    """
    s = str(model_id or "")
    low = s.lower()
    if low.startswith("opencode:"):
        return None
    for p in ("claudecode:", "antigravity:"):
        if low.startswith(p):
            return s[len(p):]
    return s


def match_pricing(model_id, pricing):
    models = pricing.get("models", {}) if isinstance(pricing, dict) else {}
    # build lookup: normalized key -> entry, plus alias -> entry
    lookup = {}
    for k, v in models.items():
        if not isinstance(v, dict):
            continue
        lookup[str(k).lower()] = v
        also = v.get("also")
        if isinstance(also, list):
            for a in also:
                if isinstance(a, str):
                    lookup[a.lower()] = v
    s = str(model_id or "")
    low = s.lower()
    if low.startswith("opencode:"):
        return None  # opencode: prefix never matches pricing (free-tier)
    if low.startswith("claudecode:") or low.startswith("antigravity:"):
        s = s.split(":", 1)[1]  # strip prefix, match the remainder only
    for cand in _candidates(s):
        if cand in lookup:
            return lookup[cand]
    return None


def cost_for_model(model_id, inp, outp, cr, cw, pricing):
    entry = match_pricing(model_id, pricing)
    if entry is None:
        return 0.0, False, None
    try:
        rin = float(entry.get("input", 0) or 0)
        rout = float(entry.get("output", 0) or 0)
        rcr = float(entry.get("cache_read", 0) or 0)
        rcw = float(entry.get("cache_write", 0) or 0)
    except (TypeError, ValueError):
        return 0.0, False, None
    # Billable cost: input + output + cache WRITE. Cache RE-READS (cache_read)
    # are process traffic (model re-reading its own cached context), never
    # billable — excluded from the default view. Frontend adds
    # cr*cache_read back only when the "Include cache re-reads" toggle is on.
    cost = (inp * rin + outp * rout + cw * rcw) / 1e6
    rates = {}
    for k in ("input", "output", "cache_read", "cache_write", "note", "also", "provider"):
        if k in entry:
            rates[k] = entry[k]
    # ensure numeric rates present
    for k, v in (("input", rin), ("output", rout), ("cache_read", rcr), ("cache_write", rcw)):
        if k not in rates:
            rates[k] = v
    return cost, True, rates


# ---------- shared DB helpers ----------

def fetch_sessions(cur, cutoff):
    if cutoff is None:
        cur.execute(
            "SELECT id, source, model, billing_provider, billing_mode, cost_status,"
            " started_at, ended_at, message_count, tool_call_count, api_call_count,"
            " input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,"
            " reasoning_tokens, estimated_cost_usd, actual_cost_usd, title"
            " FROM sessions"
        )
    else:
        cur.execute(
            "SELECT id, source, model, billing_provider, billing_mode, cost_status,"
            " started_at, ended_at, message_count, tool_call_count, api_call_count,"
            " input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,"
            " reasoning_tokens, estimated_cost_usd, actual_cost_usd, title"
            " FROM sessions WHERE started_at >= ?", (cutoff,)
        )
    rows = cur.fetchall()
    sessions = []
    for r in rows:
        sessions.append({
            "id": r[0],
            "source": r[1],
            "model": r[2],
            "billing_provider": r[3],
            "billing_mode": r[4],
            "cost_status": r[5],
            "started_at": r[6],
            "ended_at": r[7],
            "message_count": r[8] or 0,
            "tool_call_count": r[9] or 0,
            "api_call_count": r[10] or 0,
            "input_tokens": r[11] or 0,
            "output_tokens": r[12] or 0,
            "cache_read_tokens": r[13] or 0,
            "cache_write_tokens": r[14] or 0,
            "reasoning_tokens": r[15] or 0,
            "estimated_cost_usd": r[16] or 0.0,
            "actual_cost_usd": r[17] or 0.0,
            "title": r[18] or "",
        })
    return sessions


def compute_tool_reconciled(cur, cutoff):
    """Reconcile per (session_id, tool): max of two representations, sum across sessions."""
    if cutoff is None:
        cur.execute(
            "SELECT messages.session_id, messages.tool_name, COUNT(*) FROM messages"
            " JOIN sessions ON sessions.id = messages.session_id"
            " WHERE messages.role='tool' AND messages.tool_name IS NOT NULL"
            " GROUP BY messages.session_id, messages.tool_name"
        )
        rows_a = cur.fetchall()
    else:
        cur.execute(
            "SELECT messages.session_id, messages.tool_name, COUNT(*) FROM messages"
            " JOIN sessions ON sessions.id = messages.session_id"
            " WHERE messages.role='tool' AND messages.tool_name IS NOT NULL"
            " AND sessions.started_at >= ?"
            " GROUP BY messages.session_id, messages.tool_name", (cutoff,)
        )
        rows_a = cur.fetchall()
    per_session = defaultdict(Counter)
    for sid, tool, cnt in rows_a:
        if tool:
            per_session[sid][tool] += cnt
    if cutoff is None:
        cur.execute(
            "SELECT messages.session_id, messages.tool_calls FROM messages"
            " JOIN sessions ON sessions.id = messages.session_id"
            " WHERE messages.role='assistant' AND messages.tool_calls IS NOT NULL"
        )
        rows_b = cur.fetchall()
    else:
        cur.execute(
            "SELECT messages.session_id, messages.tool_calls FROM messages"
            " JOIN sessions ON sessions.id = messages.session_id"
            " WHERE messages.role='assistant' AND messages.tool_calls IS NOT NULL"
            " AND sessions.started_at >= ?", (cutoff,)
        )
        rows_b = cur.fetchall()
    for sid, tc in rows_b:
        if not tc:
            continue
        try:
            arr = json.loads(tc)
        except Exception:
            continue
        if not isinstance(arr, list):
            continue
        for e in arr:
            try:
                fn = (e.get("function") or {}).get("name")
            except Exception:
                continue
            if fn:
                per_session[sid][fn] += 1
    total = Counter()
    for sid, c in per_session.items():
        for tool, cnt in c.items():
            total[tool] += cnt
    # NOTE: per spec, reconcile takes max of the two representations per
    # (session, tool). The gateway writes both representations for the same
    # underlying call in many sessions (role='tool' rows + assistant
    # tool_calls JSON), so counting both would double-count. Above we summed
    # both; fix by recomputing max properly:
    # Recompute correctly: separate A and B then max.
    # We already merged; redo precisely:
    # Build A and B separately.
    # (Cheap: DB is small, redo queries in Python already have data? Instead
    #  recompute from rows_a/rows_b.)
    a_map = defaultdict(Counter)
    for sid, tool, cnt in rows_a:
        if tool:
            a_map[sid][tool] = cnt
    b_map = defaultdict(Counter)
    for sid, tc in rows_b:
        if not tc:
            continue
        try:
            arr = json.loads(tc)
        except Exception:
            continue
        if not isinstance(arr, list):
            continue
        for e in arr:
            try:
                fn = (e.get("function") or {}).get("name")
            except Exception:
                continue
            if fn:
                b_map[sid][fn] += 1
    reconciled = Counter()
    for sid in set(list(a_map.keys()) + list(b_map.keys())):
        for tool in set(list(a_map[sid].keys()) + list(b_map[sid].keys())):
            reconciled[tool] += max(a_map[sid][tool], b_map[sid][tool])
    return reconciled


def build_models_aggregate(cur, cutoff):
    sessions = fetch_sessions(cur, cutoff)
    by_id = {s["id"]: s for s in sessions}
    if cutoff is None:
        cur.execute(
            "SELECT session_model_usage.session_id, session_model_usage.model,"
            " session_model_usage.billing_provider, session_model_usage.billing_mode,"
            " session_model_usage.task, session_model_usage.api_call_count,"
            " session_model_usage.input_tokens, session_model_usage.output_tokens,"
            " session_model_usage.cache_read_tokens, session_model_usage.cache_write_tokens,"
            " session_model_usage.reasoning_tokens, session_model_usage.estimated_cost_usd,"
            " session_model_usage.cost_status, session_model_usage.first_seen,"
            " session_model_usage.last_seen"
            " FROM session_model_usage JOIN sessions ON sessions.id = session_model_usage.session_id"
        )
        smu_rows = cur.fetchall()
    else:
        cur.execute(
            "SELECT session_model_usage.session_id, session_model_usage.model,"
            " session_model_usage.billing_provider, session_model_usage.billing_mode,"
            " session_model_usage.task, session_model_usage.api_call_count,"
            " session_model_usage.input_tokens, session_model_usage.output_tokens,"
            " session_model_usage.cache_read_tokens, session_model_usage.cache_write_tokens,"
            " session_model_usage.reasoning_tokens, session_model_usage.estimated_cost_usd,"
            " session_model_usage.cost_status, session_model_usage.first_seen,"
            " session_model_usage.last_seen"
            " FROM session_model_usage JOIN sessions ON sessions.id = session_model_usage.session_id"
            " WHERE sessions.started_at >= ?", (cutoff,)
        )
        smu_rows = cur.fetchall()

    agg = {}
    # per-session smu sums for residual
    per_session_sums = defaultdict(lambda: {
        "input": 0, "output": 0, "cr": 0, "cw": 0, "reason": 0,
        "api": 0, "est": 0.0,
    })

    def ensure(m):
        if m not in agg:
            agg[m] = {
                "model": m, "provider": "", "_providers": Counter(),
                "sessions_set": set(), "input": 0, "output": 0, "cr": 0,
                "cw": 0, "reason": 0, "api": 0, "est": 0.0,
                "cost_statuses": Counter(), "last_used": 0.0,
                "aux_tokens": 0, "_tool_sessions": set(),
            }
        return agg[m]

    for (sid, model, bprov, bmode, task, api, inp, outp, cr, cw,
         reason, est, cstat, first_seen, last_seen) in smu_rows:
        if sid not in by_id:
            continue
        m = model if model is not None else ""
        e = ensure(m)
        inp = inp or 0; outp = outp or 0; cr = cr or 0; cw = cw or 0
        reason = reason or 0; api = api or 0; est = est or 0.0
        e["input"] += inp; e["output"] += outp; e["cr"] += cr; e["cw"] += cw
        e["reason"] += reason; e["api"] += api; e["est"] += est or 0.0
        e["sessions_set"].add(sid)
        if bprov:
            e["_providers"][bprov] += 1
        e["cost_statuses"][cstat or "unknown"] += 1
        for ts in (last_seen, first_seen):
            if ts:
                try:
                    if float(ts) > e["last_used"]:
                        e["last_used"] = float(ts)
                except Exception:
                    pass
        tot = inp + outp + cr + cw
        if task is not None and task != "":
            e["aux_tokens"] += tot
        ps = per_session_sums[sid]
        ps["input"] += inp; ps["output"] += outp; ps["cr"] += cr
        ps["cw"] += cw; ps["reason"] += reason; ps["api"] += api
        ps["est"] += est or 0.0

    # fold residuals attributed to session's model
    for s in sessions:
        sid = s["id"]
        sm = s["model"] if s["model"] is not None else ""
        ps = per_session_sums.get(sid)
        if ps is None:
            ps = {"input": 0, "output": 0, "cr": 0, "cw": 0, "reason": 0, "api": 0, "est": 0.0}
        ri = s["input_tokens"] - ps["input"]
        ro = s["output_tokens"] - ps["output"]
        rc = s["cache_read_tokens"] - ps["cr"]
        rw = s["cache_write_tokens"] - ps["cw"]
        rr = s["reasoning_tokens"] - ps["reason"]
        ra = s["api_call_count"] - ps["api"]
        re_ = (s["estimated_cost_usd"] or 0.0) - ps["est"]
        if ri == 0 and ro == 0 and rc == 0 and rw == 0 and rr == 0 and ra == 0 and re_ == 0:
            # still register session for its model for sessions/tool counts
            if sm != "":
                e = ensure(sm)
                e["sessions_set"].add(sid)
            continue
        if sm == "":
            continue
        e = ensure(sm)
        e["input"] += ri; e["output"] += ro; e["cr"] += rc; e["cw"] += rw
        e["reason"] += rr; e["api"] += ra; e["est"] += re_
        e["sessions_set"].add(sid)
        if s.get("billing_provider"):
            e["_providers"][s["billing_provider"]] += 1
        e["cost_statuses"][s.get("cost_status") or "unknown"] += 1

    # session-model tool_calls + last_used fallback + provider
    for s in sessions:
        sm = s["model"] if s["model"] is not None else ""
        if sm != "" and sm in agg:
            agg[sm]["_tool_sessions"].add(s["id"])
            if s["started_at"] and s["started_at"] > agg[sm]["last_used"]:
                # only if no smu last_seen bigger; keep max
                pass
    # provider + tool_calls + last_used fallback
    # map session model -> tool sum + started max
    tool_by_model = Counter()
    started_max = {}
    for s in sessions:
        sm = s["model"] if s["model"] is not None else ""
        if sm == "":
            continue
        tool_by_model[sm] += s["tool_call_count"]
        if sm not in started_max or (s["started_at"] or 0) > started_max[sm]:
            started_max[sm] = s["started_at"] or 0

    out = []
    for m, e in agg.items():
        total = e["input"] + e["output"] + e["cr"] + e["cw"]
        prov = ""
        if e["_providers"]:
            prov = e["_providers"].most_common(1)[0][0]
        cs = "unknown"
        if e["cost_statuses"]:
            top = e["cost_statuses"].most_common(1)[0][0]
            cs = top if top in ("priced", "included", "unknown") else "unknown"
        last_used = e["last_used"] or started_max.get(m, 0) or 0
        aux_share = (e["aux_tokens"] / total) if total > 0 else 0.0
        billed_m = e["input"] + e["output"] + e["cw"]
        out.append({
            "model": m,
            "provider": prov or "",
            "sessions": len(e["sessions_set"]),
            "input_tokens": e["input"],
            "output_tokens": e["output"],
            "cache_read_tokens": e["cr"],
            "cache_write_tokens": e["cw"],
            "reasoning_tokens": e["reason"],
            "total_tokens": total,
            "billed_tokens": billed_m,
            "cache_tokens": e["cr"],
            "api_calls": e["api"],
            "tool_calls": tool_by_model.get(m, 0),
            "estimated_cost_usd": e["est"],
            "cost_status": cs,
            "last_used_at": last_used,
            "is_aux_share": aux_share,
        })
    out.sort(key=lambda x: x["total_tokens"], reverse=True)
    return out, sessions


# ---------- endpoint builders ----------

def build_summary(cutoff):
    con = open_ro()
    try:
        cur = con.cursor()
        sessions = fetch_sessions(cur, cutoff)
        n = len(sessions)
        msg_sum = sum(s["message_count"] for s in sessions)
        api_sum = sum(s["api_call_count"] for s in sessions)
        inp = sum(s["input_tokens"] for s in sessions)
        outp = sum(s["output_tokens"] for s in sessions)
        cr = sum(s["cache_read_tokens"] for s in sessions)
        cw = sum(s["cache_write_tokens"] for s in sessions)
        rs = sum(s["reasoning_tokens"] for s in sessions)
        total = inp + outp + cr + cw
        # billable = what a conventional API bill would cover: fresh input + output
        # + cache WRITES. cache_read = the model re-reading its own cached context
        # (llama.cpp prompt cache); it is process traffic, not billable usage.
        billed = inp + outp + cw
        est = sum(s["estimated_cost_usd"] or 0.0 for s in sessions)
        act = sum(s["actual_cost_usd"] or 0.0 for s in sessions)
        dur_total = 0.0
        dur_n = 0
        for s in sessions:
            st, en = s["started_at"], s["ended_at"]
            if st is not None and en is not None:
                try:
                    d = float(en) - float(st)
                except Exception:
                    continue
                if d > 0:
                    dur_total += d
                    dur_n += 1
        hours = dur_total / 3600.0
        avg_dur = (dur_total / dur_n) if dur_n else 0.0
        avg_tok = (total / n) if n else 0.0
        if sessions:
            starts = [s["started_at"] for s in sessions if s["started_at"] is not None]
            dr_start = min(starts) if starts else None
            dr_end = max(starts) if starts else None
        else:
            dr_start, dr_end = None, None
        # user_messages
        if cutoff is None:
            cur.execute("SELECT COUNT(*) FROM messages JOIN sessions ON sessions.id=messages.session_id WHERE messages.role='user'")
            um = cur.fetchone()[0] or 0
        else:
            cur.execute("SELECT COUNT(*) FROM messages JOIN sessions ON sessions.id=messages.session_id WHERE messages.role='user' AND sessions.started_at >= ?", (cutoff,))
            um = cur.fetchone()[0] or 0
        recon = compute_tool_reconciled(cur, cutoff)
        tool_total = sum(recon.values())
        return {
            "sessions": n,
            "messages": msg_sum,
            "user_messages": um,
            "tool_calls": tool_total,
            "api_calls": api_sum,
            "input_tokens": inp,
            "output_tokens": outp,
            "cache_read_tokens": cr,
            "cache_write_tokens": cw,
            "reasoning_tokens": rs,
            "total_tokens": total,
            "billed_tokens": billed,
            "cache_tokens": cr,
            "estimated_cost_usd": est,
            "actual_cost_usd": act,
            "total_hours_active": hours,
            "avg_session_duration_s": avg_dur,
            "avg_tokens_per_session": avg_tok,
            "date_range_start": dr_start,
            "date_range_end": dr_end,
        }
    finally:
        con.close()


def build_models(cutoff):
    con = open_ro()
    try:
        cur = con.cursor()
        rows, _ = build_models_aggregate(cur, cutoff)
        return {"models": rows}
    finally:
        con.close()


def build_platforms(cutoff):
    con = open_ro()
    try:
        cur = con.cursor()
        if cutoff is None:
            cur.execute("SELECT source, COUNT(*), SUM(message_count), SUM(input_tokens+output_tokens+cache_write_tokens), SUM(input_tokens+output_tokens+cache_read_tokens+cache_write_tokens), SUM(tool_call_count) FROM sessions GROUP BY source")
        else:
            cur.execute("SELECT source, COUNT(*), SUM(message_count), SUM(input_tokens+output_tokens+cache_write_tokens), SUM(input_tokens+output_tokens+cache_read_tokens+cache_write_tokens), SUM(tool_call_count) FROM sessions WHERE started_at >= ? GROUP BY source", (cutoff,))
        out = []
        for src, cnt, msgs, billed, total, tools in cur.fetchall():
            out.append({
                "source": src if src is not None else "unknown",
                "sessions": cnt or 0,
                "messages": msgs or 0,
                "billed_tokens": billed or 0,
                "total_tokens": total or 0,
                "tool_calls": tools or 0,
            })
    finally:
        con.close()
    # opencode as its own platform row (read-only second DB, never 500)
    try:
        cutoff_ms = None if cutoff is None else int(float(cutoff) * 1000)
        ocon = open_opencode_ro()
        try:
            ocur = ocon.cursor()
            try:
                if cutoff_ms is None:
                    ocur.execute("SELECT COUNT(*) FROM session_v2")
                else:
                    ocur.execute("SELECT COUNT(*) FROM session_v2 WHERE time_created >= ?", (cutoff_ms,))
                orow = ocur.fetchone()
                osess = (orow[0] or 0) if orow else 0
            except (OSError, sqlite3.Error):
                osess = 0
            try:
                if cutoff_ms is None:
                    ocur.execute("SELECT COUNT(*) FROM session_message")
                else:
                    ocur.execute("SELECT COUNT(*) FROM session_message WHERE time_created >= ?", (cutoff_ms,))
                orow = ocur.fetchone()
                omsgs = (orow[0] or 0) if orow else 0
            except (OSError, sqlite3.Error):
                omsgs = 0
            obilled = ototal = 0
            try:
                if cutoff_ms is None:
                    ocur.execute("SELECT data FROM session_message WHERE type='assistant'")
                    odatas = ocur.fetchall()
                else:
                    ocur.execute("SELECT data FROM session_message WHERE type='assistant' AND time_created >= ?", (cutoff_ms,))
                    odatas = ocur.fetchall()
                for (d,) in odatas:
                    try:
                        j = json.loads(d) if isinstance(d, str) else {}
                    except Exception:
                        continue
                    if not isinstance(j, dict):
                        continue
                    t = j.get("tokens") or {}
                    if not isinstance(t, dict):
                        continue
                    c = t.get("cache") or {}
                    if not isinstance(c, dict):
                        c = {}
                    try:
                        ii = int(t.get("input") or 0)
                    except Exception:
                        ii = 0
                    try:
                        oo = int(t.get("output") or 0)
                    except Exception:
                        oo = 0
                    try:
                        crr = int(c.get("read") or 0)
                    except Exception:
                        crr = 0
                    try:
                        cww = int(c.get("write") or 0)
                    except Exception:
                        cww = 0
                    obilled += ii + oo + cww
                    ototal += ii + oo + crr + cww
            except (OSError, sqlite3.Error):
                pass
            if osess or omsgs or obilled or ototal:
                out.append({
                    "source": "opencode",
                    "sessions": osess,
                    "messages": omsgs,
                    "billed_tokens": obilled,
                    "total_tokens": ototal,
                    "tool_calls": 0,
                })
        finally:
            try:
                ocon.close()
            except Exception:
                pass
    except (OSError, sqlite3.Error):
        pass
    # TASK5: claude code + antigravity rows (same window cutoff; read-only scans,
    # never 500). Always present (zeros when the source has no data) so the
    # platform table is stable across windows.
    try:
        cc = scan_claudecode(cutoff)
        cb = cc["tot"][0] + cc["tot"][1] + cc["tot"][3]
        ct = cb + cc["tot"][2]
        out.append({
            "source": "claudecode",
            "sessions": len(cc["top_files"]),
            "messages": cc["lines"],
            "billed_tokens": cb,
            "total_tokens": ct,
            "tool_calls": 0,
        })
    except Exception:
        pass
    try:
        ag = scan_antigravity(cutoff)
        ab = ag["tot"][0] + ag["tot"][1] + ag["tot"][3]
        at = ab + ag["tot"][2]
        out.append({
            "source": "antigravity",
            "sessions": len(ag["convs"]),
            "messages": ag["lines"],
            "billed_tokens": ab,
            "total_tokens": at,
            "tool_calls": 0,
        })
    except Exception:
        pass
    out.sort(key=lambda x: x["total_tokens"], reverse=True)
    return {"platforms": out}


def build_tools(cutoff):
    con = open_ro()
    try:
        cur = con.cursor()
        recon = compute_tool_reconciled(cur, cutoff)
        total = sum(recon.values())
        items = []
        for tool, cnt in recon.most_common(20):
            pct = (cnt / total * 100.0) if total else 0.0
            items.append({"tool": tool, "count": cnt, "pct": pct})
        return {"tools": items, "total": total}
    finally:
        con.close()


def _parse_skill_args(args_str):
    names = []
    is_view = False
    # args_str is JSON string; try parse
    try:
        if isinstance(args_str, dict):
            aj = args_str
        else:
            aj = json.loads(args_str) if isinstance(args_str, str) else {}
    except Exception:
        return []
    if not isinstance(aj, dict):
        return []
    if isinstance(aj.get("name"), str) and aj.get("name"):
        return [aj["name"]]
    ops = aj.get("operations")
    if isinstance(ops, list):
        for op in ops:
            if isinstance(op, dict) and isinstance(op.get("name"), str) and op.get("name"):
                names.append(op["name"])
    # also handle 'skill' key variants
    for k in ("skill", "skill_name"):
        if isinstance(aj.get(k), str) and aj.get(k):
            names.append(aj[k])
    return names


def build_skills(cutoff):
    con = open_ro()
    try:
        cur = con.cursor()
        if cutoff is None:
            cur.execute(
                "SELECT messages.tool_calls, messages.timestamp FROM messages"
                " JOIN sessions ON sessions.id=messages.session_id"
                " WHERE messages.role='assistant' AND messages.tool_calls IS NOT NULL"
            )
            rows = cur.fetchall()
        else:
            cur.execute(
                "SELECT messages.tool_calls, messages.timestamp FROM messages"
                " JOIN sessions ON sessions.id=messages.session_id"
                " WHERE messages.role='assistant' AND messages.tool_calls IS NOT NULL"
                " AND sessions.started_at >= ?", (cutoff,)
            )
            rows = cur.fetchall()
        views = Counter()
        manages = Counter()
        last_used = {}
        for tc, ts in rows:
            if not tc or "skill" not in tc:
                continue
            try:
                arr = json.loads(tc)
            except Exception:
                continue
            if not isinstance(arr, list):
                continue
            for e in arr:
                try:
                    fn = (e.get("function") or {}).get("name")
                    args = (e.get("function") or {}).get("arguments", "{}")
                except Exception:
                    continue
                if fn not in ("skill_view", "skill_manage"):
                    continue
                for name in _parse_skill_args(args):
                    if fn == "skill_view":
                        views[name] += 1
                    else:
                        manages[name] += 1
                    if ts:
                        try:
                            fts = float(ts)
                        except Exception:
                            continue
                        if name not in last_used or fts > last_used[name]:
                            last_used[name] = fts
        skills = set(list(views.keys()) + list(manages.keys()))
        lst = []
        for s in skills:
            lst.append({
                "skill": s,
                "view_count": views.get(s, 0),
                "manage_count": manages.get(s, 0),
                "last_used_at": last_used.get(s, 0) or 0,
            })
        lst.sort(key=lambda x: (x["view_count"] + x["manage_count"]), reverse=True)
        loads = sum(views.values())
        edits = sum(manages.values())
        return {
            "summary": {"loads": loads, "edits": edits, "distinct": len(skills)},
            "skills": lst,
        }
    finally:
        con.close()


def build_activity(cutoff, days_str, days_int):
    con = open_ro()
    try:
        cur = con.cursor()
        sessions = fetch_sessions(cur, cutoff)
        by_day = [0] * 7
        by_hour = [0] * 24
        for s in sessions:
            st = s["started_at"]
            if st is None:
                continue
            try:
                lt = time.localtime(float(st))
            except Exception:
                continue
            by_day[lt.tm_wday] += 1
            by_hour[lt.tm_hour] += 1
        # daily
        if days_int is None:
            n_daily = 30
        else:
            n_daily = min(days_int, 30)
        now = time.time()
        today_lt = time.localtime(now)
        # midnight of today local
        # compute date ordinals via time.mktime
        days = []
        # build map date_str -> (sessions, tokens)
        bucket = defaultdict(lambda: [0, 0])
        day_detail = defaultdict(lambda: [0, 0, 0, 0])
        for s in sessions:
            st = s["started_at"]
            if st is None:
                continue
            lt = time.localtime(float(st))
            ds = time.strftime("%Y-%m-%d", lt)
            tot = s["input_tokens"] + s["output_tokens"] + s["cache_read_tokens"] + s["cache_write_tokens"]
            bucket[ds][0] += 1
            bucket[ds][1] += tot
            day_detail[ds][0] += s["input_tokens"]
            day_detail[ds][1] += s["output_tokens"]
            day_detail[ds][2] += s["cache_read_tokens"]
            day_detail[ds][3] += s["cache_write_tokens"]
        # generate last n_daily days ending today
        # use mktime on local midnights
        base_mid = time.mktime((today_lt.tm_year, today_lt.tm_mon, today_lt.tm_mday, 0, 0, 0, 0, 0, -1))
        for i in range(n_daily - 1, -1, -1):
            t = base_mid - i * 86400
            # DST edge: normalize via localtime
            lt = time.localtime(t)
            ds = time.strftime("%Y-%m-%d", lt)
            c, toks = bucket.get(ds, (0, 0))
            det = day_detail.get(ds, (0, 0, 0, 0))
            days.append({"date": ds, "sessions": c, "total_tokens": toks,
                         "input_tokens": det[0], "output_tokens": det[1],
                         "cache_read_tokens": det[2], "cache_write_tokens": det[3]})
        # busiest
        busiest_hour = max(range(24), key=lambda h: by_hour[h]) if sessions else 0
        if days:
            bd = max(days, key=lambda d: d["sessions"])
            busiest_day = bd["date"] if bd["sessions"] > 0 else (days[-1]["date"] if days else None)
        else:
            busiest_day = None
        # active_days + streak from distinct dates in window
        distinct = sorted(bucket.keys())
        active_days = len([d for d in distinct if bucket[d][0] > 0])
        # streak: longest consecutive calendar days
        max_streak = 0
        if distinct:
            # convert to ordinals
            import datetime as _dt
            ords = []
            for d in distinct:
                try:
                    y, mth, dd = map(int, d.split("-"))
                    ords.append(_dt.date(y, mth, dd).toordinal())
                except Exception:
                    continue
            ords.sort()
            cur_streak = 1
            max_streak = 1
            for i in range(1, len(ords)):
                if ords[i] == ords[i - 1] + 1:
                    cur_streak += 1
                elif ords[i] == ords[i - 1]:
                    continue
                else:
                    cur_streak = 1
                if cur_streak > max_streak:
                    max_streak = cur_streak
        # top sessions
        def loc_date(st):
            try:
                return time.strftime("%Y-%m-%d", time.localtime(float(st)))
            except Exception:
                return ""
        tops = []
        if sessions:
            # longest
            best = None
            best_d = -1
            for s in sessions:
                st, en = s["started_at"], s["ended_at"]
                if st is None or en is None:
                    continue
                try:
                    d = float(en) - float(st)
                except Exception:
                    continue
                if d > best_d:
                    best_d = d
                    best = s
            if best is not None and best_d >= 0:
                tops.append({"label": "longest", "session_id": (best["id"] or "")[:16],
                             "value": best_d, "date": loc_date(best["started_at"]), "title": best["title"] or ""})
            # most messages
            bm = max(sessions, key=lambda s: s["message_count"])
            tops.append({"label": "most_messages", "session_id": (bm["id"] or "")[:16],
                         "value": bm["message_count"], "date": loc_date(bm["started_at"]), "title": bm["title"] or ""})
            # most tokens
            bt = max(sessions, key=lambda s: s["input_tokens"] + s["output_tokens"] + s["cache_read_tokens"] + s["cache_write_tokens"])
            tv = bt["input_tokens"] + bt["output_tokens"] + bt["cache_read_tokens"] + bt["cache_write_tokens"]
            tops.append({"label": "most_tokens", "session_id": (bt["id"] or "")[:16],
                         "value": tv, "date": loc_date(bt["started_at"]), "title": bt["title"] or ""})
            # most tool calls
            bc = max(sessions, key=lambda s: s["tool_call_count"])
            tops.append({"label": "most_tool_calls", "session_id": (bc["id"] or "")[:16],
                         "value": bc["tool_call_count"], "date": loc_date(bc["started_at"]), "title": bc["title"] or ""})
        # tool breakdown for the window (same reconciled logic as /api/tools).
        # Filter by sessions.started_at within the window via JOIN, so
        # days=7/1 stay non-empty and subset-consistent with days=30.
        recon = compute_tool_reconciled(cur, cutoff)
        tools_total = sum(recon.values())
        tools_list = []
        for tool, cnt in recon.most_common(20):
            pct = (cnt / tools_total * 100.0) if tools_total else 0.0
            tools_list.append({"tool": tool, "count": cnt, "pct": pct})
        return {
            "by_day": by_day,
            "by_hour": by_hour,
            "daily": days,
            "busiest_day": busiest_day,
            "busiest_hour": busiest_hour,
            "active_days": active_days,
            "max_streak": max_streak,
            "top_sessions": tops,
            "tools": tools_list,
            "tools_total": tools_total,
        }
    finally:
        con.close()


def _opencode_label_from_session_model(raw):
    """Parse session_v2.model (JSON or NULL) -> 'opencode:<id>' or None."""
    if raw is None:
        return None
    try:
        if isinstance(raw, dict):
            mid = raw.get("id")
            return f"opencode:{mid}" if mid else None
        if isinstance(raw, str):
            s = raw.strip()
            if not s:
                return None
            try:
                j = json.loads(s)
            except Exception:
                # plain string id
                return f"opencode:{s}" if s else None
            if isinstance(j, dict):
                mid = j.get("id")
                return f"opencode:{mid}" if mid else None
            if isinstance(j, str) and j:
                return f"opencode:{j}"
            return None
        return None
    except Exception:
        return None


def _opencode_empty(days_str, days_int):
    if days_int is None:
        n_daily = 30
    else:
        try:
            n_daily = min(int(days_int), 30)
        except Exception:
            n_daily = 30
    now = time.time()
    today_lt = time.localtime(now)
    base_mid = time.mktime((today_lt.tm_year, today_lt.tm_mon, today_lt.tm_mday, 0, 0, 0, 0, 0, -1))
    daily = []
    for i in range(n_daily - 1, -1, -1):
        t = base_mid - i * 86400
        lt = time.localtime(t)
        ds = time.strftime("%Y-%m-%d", lt)
        daily.append({"date": ds, "input_tokens": 0, "output_tokens": 0,
                      "cache_read_tokens": 0, "cache_write_tokens": 0, "sessions": 0})
    return {
        "source": "opencode",
        "sessions": 0,
        "models": [],
        "daily": daily,
        "total": {"input_tokens": 0, "output_tokens": 0,
                  "cache_read_tokens": 0, "reported_cost_usd": 0.0},
        "active_days": 0,
    }


def build_opencode(cutoff, days_str, days_int):
    """Aggregate opencode usage from session_message (type='assistant').

    Window uses message time_created (ms). Read-only on the opencode DB;
    missing file -> 200 with empty shapes, never 500.
    """
    if days_int is None:
        n_daily = 30
    else:
        try:
            n_daily = min(int(days_int), 30)
        except Exception:
            n_daily = 30
    cutoff_ms = None if cutoff is None else int(float(cutoff) * 1000)
    try:
        con = open_opencode_ro()
    except (OSError, sqlite3.Error):
        return _opencode_empty(days_str, days_int)
    try:
        cur = con.cursor()
        # session -> fallback model label
        sess_fallback = {}
        try:
            cur.execute("SELECT id, model FROM session_v2")
            for sid, mraw in cur.fetchall():
                lbl = _opencode_label_from_session_model(mraw)
                if lbl:
                    sess_fallback[sid] = lbl
        except (OSError, sqlite3.Error):
            pass
        # sessions count in window (session_v2.time_created is ms epoch)
        try:
            if cutoff_ms is None:
                cur.execute("SELECT COUNT(*) FROM session_v2")
            else:
                cur.execute("SELECT COUNT(*) FROM session_v2 WHERE time_created >= ?", (cutoff_ms,))
            row = cur.fetchone()
            n_sessions = (row[0] or 0) if row else 0
        except (OSError, sqlite3.Error):
            n_sessions = 0
        # assistant messages in window
        try:
            if cutoff_ms is None:
                cur.execute("SELECT session_id, time_created, data FROM session_message WHERE type='assistant'")
            else:
                cur.execute("SELECT session_id, time_created, data FROM session_message WHERE type='assistant' AND time_created >= ?", (cutoff_ms,))
            msg_rows = cur.fetchall()
        except (OSError, sqlite3.Error):
            msg_rows = []
        agg = {}
        bucket = defaultdict(lambda: [0, 0, 0, 0])
        bucket_sess = defaultdict(set)
        active_dates = set()
        tot_in = tot_out = tot_cr = 0
        tot_cost = 0.0

        def ensure(m):
            if m not in agg:
                agg[m] = {"model": m, "sessions_set": set(), "input": 0, "output": 0,
                          "reason": 0, "cr": 0, "cw": 0, "cost": 0.0}
            return agg[m]

        for sid, tc_ms, data in msg_rows:
            try:
                j = json.loads(data) if isinstance(data, str) else {}
            except Exception:
                j = {}
            if not isinstance(j, dict):
                j = {}
            label = None
            m = j.get("model")
            if isinstance(m, dict):
                mid = m.get("id")
                if isinstance(mid, str) and mid:
                    label = f"opencode:{mid}"
            if label is None:
                label = sess_fallback.get(sid) or "opencode:unknown"
            t = j.get("tokens") or {}
            if not isinstance(t, dict):
                t = {}
            c = t.get("cache") or {}
            if not isinstance(c, dict):
                c = {}
            try:
                inp = int(t.get("input") or 0)
            except Exception:
                inp = 0
            try:
                outp = int(t.get("output") or 0)
            except Exception:
                outp = 0
            try:
                rs = int(t.get("reasoning") or 0)
            except Exception:
                rs = 0
            try:
                cr = int(c.get("read") or 0)
            except Exception:
                cr = 0
            try:
                cw = int(c.get("write") or 0)
            except Exception:
                cw = 0
            try:
                cost = float(j.get("cost") or 0.0)
            except Exception:
                cost = 0.0
            e = ensure(label)
            e["sessions_set"].add(sid)
            e["input"] += inp; e["output"] += outp; e["reason"] += rs
            e["cr"] += cr; e["cw"] += cw; e["cost"] += cost
            tot_in += inp; tot_out += outp; tot_cr += cr; tot_cost += cost
            # daily bucket (local date)
            try:
                ts_s = float(tc_ms) / 1000.0
                ds = time.strftime("%Y-%m-%d", time.localtime(ts_s))
            except Exception:
                continue
            b = bucket[ds]
            b[0] += inp; b[1] += outp; b[2] += cr; b[3] += cw
            if sid:
                bucket_sess[ds].add(sid)
            active_dates.add(ds)
        models_out = []
        for mname, e in agg.items():
            billed = e["input"] + e["output"] + e["cw"]
            models_out.append({
                "model": mname,
                "sessions": len(e["sessions_set"]),
                "input_tokens": e["input"],
                "output_tokens": e["output"],
                "reasoning_tokens": e["reason"],
                "cache_read_tokens": e["cr"],
                "cache_write_tokens": e["cw"],
                "billed_tokens": billed,
                "reported_cost_usd": e["cost"],
            })
        models_out.sort(key=lambda x: (x["input_tokens"] + x["output_tokens"] + x["cache_read_tokens"] + x["cache_write_tokens"]), reverse=True)
        # zero-filled daily (last n_daily days ending today, local)
        now = time.time()
        today_lt = time.localtime(now)
        base_mid = time.mktime((today_lt.tm_year, today_lt.tm_mon, today_lt.tm_mday, 0, 0, 0, 0, 0, -1))
        daily = []
        for i in range(n_daily - 1, -1, -1):
            t = base_mid - i * 86400
            lt = time.localtime(t)
            ds = time.strftime("%Y-%m-%d", lt)
            b = bucket.get(ds, (0, 0, 0, 0))
            daily.append({"date": ds, "input_tokens": b[0], "output_tokens": b[1],
                          "cache_read_tokens": b[2], "cache_write_tokens": b[3],
                          "sessions": len(bucket_sess.get(ds, ()))})
        return {
            "source": "opencode",
            "sessions": n_sessions,
            "models": models_out,
            "daily": daily,
            "total": {"input_tokens": tot_in, "output_tokens": tot_out,
                      "cache_read_tokens": tot_cr, "reported_cost_usd": tot_cost},
            "active_days": len(active_dates),
        }
    finally:
        try:
            con.close()
        except Exception:
            pass


# ---------- claude code + antigravity (TASK5, additive) ----------

CLAUDE_PROJECTS_DIR = os.path.expanduser("~/.claude/projects")
AGY_BASE_DIR = os.path.expanduser("~/.gemini/antigravity-cli")

# Model literal inside the raw bytes of conversations/<conv>.db (v1 heuristic:
# most frequent match wins; acceptable for v1 — documented in TASK5).
AGY_MODEL_RE = re.compile(rb"(gemini-[\d.]+[a-z-]*|claude-[a-z0-9.-]+|gpt-[\w.-]+|grok-[\d.]+)")


def _parse_iso_ts(s):
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _int0(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _coerce_cost_float(v):
    """Coerce a cost value that may be a JSON string to float (TASK6)."""
    try:
        if v is None:
            return 0.0
        if isinstance(v, bool):
            return 1.0 if v else 0.0
        if isinstance(v, str):
            s = v.strip()
            if s == "":
                return 0.0
            return float(s)
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _parse_cost_model_usage(mu):
    """modelUsage may be a dict OR a JSON string (TASK6) -> dict."""
    if mu is None:
        return {}
    if isinstance(mu, str):
        s = mu.strip()
        if not s:
            return {}
        try:
            mu = json.loads(s)
        except Exception:
            return {}
    if not isinstance(mu, dict):
        return {}
    return mu


def _parse_cost_unknown(v):
    """hasUnknownModelCost may be bool or string 'True'/'False' (TASK6)."""
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() == "true"
    if isinstance(v, (int, float)):
        return bool(v)
    return False


def _parse_cost_start_ms(v):
    """startTime is epoch milliseconds, may be a JSON string (TASK6)."""
    try:
        if v is None:
            return None
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _daily_from_scan(scan, n_daily):
    """Zero-filled last n_daily days (local), mirroring build_opencode daily."""
    now = time.time()
    today_lt = time.localtime(now)
    base_mid = time.mktime((today_lt.tm_year, today_lt.tm_mon, today_lt.tm_mday, 0, 0, 0, 0, 0, -1))
    daily = []
    bucket_rep = scan.get("bucket_reported") or {}
    cost_days = scan.get("cost_days") or set(bucket_rep.keys())
    for i in range(n_daily - 1, -1, -1):
        t = base_mid - i * 86400
        lt = time.localtime(t)
        ds = time.strftime("%Y-%m-%d", lt)
        b = scan["bucket"].get(ds, (0, 0, 0, 0))
        daily.append({"date": ds, "input_tokens": b[0], "output_tokens": b[1],
                      "cache_read_tokens": b[2], "cache_write_tokens": b[3],
                      "sessions": len(scan["bucket_sess"].get(ds, ())),
                      "reported_cost_usd": float(bucket_rep.get(ds, 0.0) or 0.0),
                      "has_reported_cost": bool(ds in cost_days)})
    return daily


def _rows_from_scan(scan, sess_key):
    rep = scan.get("reported_by_model") or {}
    rep_sess = scan.get("reported_sess") or {}
    rows = []
    for label, e in scan["agg"].items():
        billed = e["input"] + e["output"] + e["cw"]
        rows.append({
            "model": label,
            "sessions": len(e[sess_key]),
            "input_tokens": e["input"],
            "output_tokens": e["output"],
            "reasoning_tokens": 0,
            "cache_read_tokens": e["cr"],
            "cache_write_tokens": e["cw"],
            "billed_tokens": billed,
            "reported_cost_usd": float(rep.get(label, 0.0) or 0.0),
        })
    # Models that appear only in cost-state (no assistant-line tokens in
    # window) still get a row so reported cost is never hidden.
    for label, cost in rep.items():
        if label not in scan["agg"]:
            ss = rep_sess.get(label) or set()
            rows.append({
                "model": label,
                "sessions": len(ss),
                "input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "billed_tokens": 0,
                "reported_cost_usd": float(cost or 0.0),
            })
    rows.sort(key=lambda x: (x["input_tokens"] + x["output_tokens"]
                             + x["cache_read_tokens"] + x["cache_write_tokens"]),
              reverse=True)
    return rows


def _cc_session_key(path):
    """Conversation-level session key: a subagent file maps to its parent
    conversation file (<proj>/<conv>/subagents/<agent>.jsonl -> <proj>/<conv>.jsonl)."""
    norm = path.replace(os.sep, "/")
    if "/subagents/" in norm:
        parts = norm.split("/")
        try:
            idx = parts.index("subagents")
            conv = parts[idx - 1]
            return "/".join(parts[:idx - 1] + [conv + ".jsonl"])
        except (ValueError, IndexError):
            pass
    return path


def _claudecode_files():
    out = []
    try:
        for root, _dirs, files in os.walk(CLAUDE_PROJECTS_DIR):
            for fn in files:
                if fn.endswith(".jsonl"):
                    out.append(os.path.join(root, fn))
    except Exception:
        pass
    out.sort()
    return out


def scan_claudecode(cutoff):
    """Read-only scan of ~/.claude/projects/**/*.jsonl (open(...,"r") only).

    Counts lines with type=="assistant" and a message.usage object. Subagent
    files count toward the same model but NOT toward sessions (sessions =
    distinct top-level files with >=1 usage line in the window).

    TASK6: also parses top-level (NOT under message) type=="cost-state" lines
    as the REAL reported cost. Per session FILE (top-level OR subagent) the
    LAST cost-state line wins (values are cumulative, monotonic
    non-decreasing). Reported cost per model = SUM across session files of
    modelUsage[model].costUSD from each file's last cost-state. Window: a
    session's reported cost is attributed to the local date of its startTime
    (ms); days filter keeps cost-states whose startTime is in window. Known
    limitation (v1): a still-running session is attributed to its start day.
    Token counts stay sourced from assistant-line message.usage; cost-state
    token fields are NOT used for token totals.
    """
    agg = {}
    bucket = defaultdict(lambda: [0, 0, 0, 0])
    bucket_sess = defaultdict(set)
    active = set()
    top_files = set()
    n_lines = 0
    tot = [0, 0, 0, 0]
    seen = set()
    # TASK6 reported-cost accumulators
    reported_by_model = defaultdict(float)
    reported_sess = defaultdict(set)
    bucket_reported = defaultdict(float)
    sessions_with_reported = 0
    has_unknown = False

    def ensure(m):
        if m not in agg:
            agg[m] = {"model": m, "sess": set(), "input": 0, "output": 0, "cr": 0, "cw": 0}
        return agg[m]

    for path in _claudecode_files():
        is_sub = "/subagents/" in path.replace(os.sep, "/")
        skey = _cc_session_key(path)
        last_cost = None
        try:
            fh = open(path, "r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    j = json.loads(line)
                except Exception:
                    continue
                if not isinstance(j, dict):
                    continue
                # TASK6: cost-state lines are top-level, NOT under message.
                if j.get("type") == "cost-state":
                    last_cost = j
                    continue
                if j.get("type") != "assistant":
                    continue
                msg = j.get("message")
                if not isinstance(msg, dict):
                    continue
                u = msg.get("usage")
                if not isinstance(u, dict):
                    continue
                uuid = j.get("uuid")
                if uuid is not None:
                    k = (path, uuid)
                    if k in seen:
                        continue
                    seen.add(k)
                ts = _parse_iso_ts(j.get("timestamp"))
                if ts is None:
                    continue
                if cutoff is not None and ts < cutoff:
                    continue
                model = msg.get("model")
                if not isinstance(model, str) or not model:
                    model = "unknown"
                label = "claudecode:" + model
                ii = _int0(u.get("input_tokens"))
                oo = _int0(u.get("output_tokens"))
                cr = _int0(u.get("cache_read_input_tokens"))
                cw = _int0(u.get("cache_creation_input_tokens"))
                e = ensure(label)
                e["sess"].add(skey)
                e["input"] += ii
                e["output"] += oo
                e["cr"] += cr
                e["cw"] += cw
                n_lines += 1
                tot[0] += ii
                tot[1] += oo
                tot[2] += cr
                tot[3] += cw
                if not is_sub:
                    top_files.add(path)
                try:
                    ds = time.strftime("%Y-%m-%d", time.localtime(ts))
                except Exception:
                    continue
                b = bucket[ds]
                b[0] += ii
                b[1] += oo
                b[2] += cr
                b[3] += cw
                bucket_sess[ds].add(skey)
                active.add(ds)
        # TASK6: attribute this file's LAST cost-state (cumulative) to the
        # local date of its startTime (ms). Days filter keeps cost-states
        # whose startTime is in window.
        if last_cost is not None:
            try:
                start_ms = _parse_cost_start_ms(last_cost.get("startTime"))
                start_s = (start_ms / 1000.0) if start_ms is not None else None
            except Exception:
                start_s = None
            if cutoff is not None and start_s is not None and start_s < cutoff:
                pass
            else:
                mu = _parse_cost_model_usage(last_cost.get("modelUsage"))
                sess_cost = 0.0
                for bare, entry in mu.items():
                    if not isinstance(bare, str) or not bare:
                        continue
                    if not isinstance(entry, dict):
                        continue
                    c = _coerce_cost_float(entry.get("costUSD"))
                    if c:
                        label_c = "claudecode:" + bare
                        reported_by_model[label_c] += c
                        reported_sess[label_c].add(path)
                        sess_cost += c
                    elif bare:
                        # Ensure the model key exists even when cost is 0 so
                        # rows can show "— reported" instead of hiding.
                        label_c = "claudecode:" + bare
                        if label_c not in reported_by_model:
                            reported_by_model[label_c] += 0.0
                        reported_sess[label_c].add(path)
                # hasUnknownModelCost may be bool or "True"/"False" string.
                try:
                    if _parse_cost_unknown(last_cost.get("hasUnknownModelCost")):
                        has_unknown = True
                except Exception:
                    pass
                sessions_with_reported += 1
                if sess_cost and start_s is not None:
                    try:
                        ds_c = time.strftime("%Y-%m-%d", time.localtime(start_s))
                    except Exception:
                        ds_c = None
                    if ds_c is not None:
                        bucket_reported[ds_c] += sess_cost
                elif start_s is not None and sess_cost == 0.0:
                    # Zero-cost sessions still mark the day as having a
                    # cost-state (so hover can show "— reported" vs estimate).
                    # We record the day with +0.0 to distinguish "has data"
                    # from "no data" via a separate set below.
                    try:
                        ds_c = time.strftime("%Y-%m-%d", time.localtime(start_s))
                    except Exception:
                        ds_c = None
                    if ds_c is not None and ds_c not in bucket_reported:
                        bucket_reported[ds_c] += 0.0
    # Days that have at least one in-window cost-state (even $0).
    cost_days = set()
    for _ds, _v in bucket_reported.items():
        cost_days.add(_ds)
    # Re-derive cost_days from sessions: bucket_reported only has entries for
    # days with cost-states (we pre-seed +0.0 above), so keys == days with data.
    return {"agg": agg, "bucket": bucket, "bucket_sess": bucket_sess,
            "active": active, "top_files": top_files, "lines": n_lines, "tot": tot,
            "reported_by_model": dict(reported_by_model),
            "reported_sess": {k: set(v) for k, v in reported_sess.items()},
            "bucket_reported": dict(bucket_reported),
            "cost_days": cost_days,
            "sessions_with_reported_cost": sessions_with_reported,
            "has_unknown_model_cost": has_unknown}


def agy_model_for_conv(conv_id):
    """Most frequent model literal in the raw bytes of conversations/<conv>.db.

    v1 heuristic (documented): no match or missing file -> antigravity:unknown.
    """
    p = os.path.join(AGY_BASE_DIR, "conversations", conv_id + ".db")
    try:
        with open(p, "rb") as f:
            raw = f.read()
    except OSError:
        return "antigravity:unknown"
    try:
        hits = AGY_MODEL_RE.findall(raw)
    except Exception:
        return "antigravity:unknown"
    if not hits:
        return "antigravity:unknown"
    c = Counter(m.decode("ascii", "ignore") for m in hits)
    best = c.most_common(1)
    if not best or not best[0][0]:
        return "antigravity:unknown"
    return "antigravity:" + best[0][0]


def scan_antigravity(cutoff):
    """Read-only scan of brain/*/.system_generated/logs/transcript.jsonl.

    Only lines carrying input_tokens count. No cache-write field exists
    (cache_write = 0). Model comes from the companion conversations/<conv>.db
    raw bytes (see agy_model_for_conv). conversation_summaries.db is NOT used.
    """
    agg = {}
    bucket = defaultdict(lambda: [0, 0, 0, 0])
    bucket_sess = defaultdict(set)
    active = set()
    convs_hit = set()
    n_lines = 0
    tot = [0, 0, 0, 0]
    model_cache = {}
    brain = os.path.join(AGY_BASE_DIR, "brain")
    try:
        names = sorted(os.listdir(brain))
    except OSError:
        names = []

    def ensure(m):
        if m not in agg:
            agg[m] = {"model": m, "convs": set(), "input": 0, "output": 0, "cr": 0, "cw": 0}
        return agg[m]

    for conv in names:
        tp = os.path.join(brain, conv, ".system_generated", "logs", "transcript.jsonl")
        if not os.path.isfile(tp):
            continue
        try:
            fh = open(tp, "r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    j = json.loads(line)
                except Exception:
                    continue
                if not isinstance(j, dict) or "input_tokens" not in j:
                    continue
                ts = _parse_iso_ts(j.get("created_at"))
                if ts is None:
                    continue
                if cutoff is not None and ts < cutoff:
                    continue
                if conv not in model_cache:
                    model_cache[conv] = agy_model_for_conv(conv)
                label = model_cache[conv]
                ii = _int0(j.get("input_tokens"))
                oo = _int0(j.get("output_tokens"))
                cr = _int0(j.get("cache_read_tokens"))
                e = ensure(label)
                e["convs"].add(conv)
                e["input"] += ii
                e["output"] += oo
                e["cr"] += cr
                n_lines += 1
                tot[0] += ii
                tot[1] += oo
                tot[2] += cr
                convs_hit.add(conv)
                try:
                    ds = time.strftime("%Y-%m-%d", time.localtime(ts))
                except Exception:
                    continue
                b = bucket[ds]
                b[0] += ii
                b[1] += oo
                b[2] += cr
                bucket_sess[ds].add(conv)
                active.add(ds)
    return {"agg": agg, "bucket": bucket, "bucket_sess": bucket_sess,
            "active": active, "convs": convs_hit, "lines": n_lines, "tot": tot}


def _n_daily(days_int):
    try:
        return min(int(days_int), 30)
    except Exception:
        return 30


def build_claudecode(cutoff, days_str, days_int):
    """Same shape as /api/opencode; TASK6 adds REAL reported cost.

    Per-model reported_cost_usd = SUM across session files of
    modelUsage[model].costUSD from each file's LAST cost-state (values may be
    JSON strings — coerced). Total reported_cost_usd = sum of models.
    sessions_with_reported_cost = # files with an in-window cost-state.
    has_unknown_model_cost = True if ANY in-window session flagged it.
    """
    n_daily = 30 if days_int is None else _n_daily(days_int)
    scan = scan_claudecode(cutoff)
    rows = _rows_from_scan(scan, "sess")
    t = scan["tot"]
    rep_total = float(sum((m.get("reported_cost_usd") or 0.0) for m in rows))
    sess_rep = int(scan.get("sessions_with_reported_cost", 0) or 0)
    has_unk = bool(scan.get("has_unknown_model_cost", False))
    return {
        "source": "claudecode",
        "sessions": len(scan["top_files"]),
        "models": rows,
        "daily": _daily_from_scan(scan, n_daily),
        "total": {"input_tokens": t[0], "output_tokens": t[1],
                  "cache_read_tokens": t[2], "reported_cost_usd": rep_total,
                  "sessions_with_reported_cost": sess_rep,
                  "has_unknown_model_cost": has_unk},
        "sessions_with_reported_cost": sess_rep,
        "has_unknown_model_cost": has_unk,
        "active_days": len(scan["active"]),
    }


def build_antigravity(cutoff, days_str, days_int):
    """Same shape as /api/opencode; reported_cost_usd always 0 (no local cost)."""
    n_daily = 30 if days_int is None else _n_daily(days_int)
    scan = scan_antigravity(cutoff)
    rows = _rows_from_scan(scan, "convs")
    t = scan["tot"]
    return {
        "source": "antigravity",
        "sessions": len(scan["convs"]),
        "models": rows,
        "daily": _daily_from_scan(scan, n_daily),
        "total": {"input_tokens": t[0], "output_tokens": t[1],
                  "cache_read_tokens": t[2], "reported_cost_usd": 0.0},
        "active_days": len(scan["active"]),
    }


def build_cost(cutoff):
    con = open_ro()
    try:
        cur = con.cursor()
        rows, sessions = build_models_aggregate(cur, cutoff)
    finally:
        con.close()
    pricing = load_pricing()
    models_out = []
    total_usd = 0.0
    unpriced_tokens = 0
    for r in rows:
        cost, priced, rates = cost_for_model(
            r["model"], r["input_tokens"], r["output_tokens"],
            r["cache_read_tokens"], r["cache_write_tokens"], pricing)
        billed_r = r["input_tokens"] + r["output_tokens"] + r["cache_write_tokens"]
        if priced:
            total_usd += cost
        else:
            unpriced_tokens += billed_r
        prov = ""
        if isinstance(rates, dict) and isinstance(rates.get("provider"), str):
            prov = rates.get("provider") or ""
        models_out.append({
            "model": r["model"],
            "provider": prov,
            "cost_usd": cost,
            "priced": priced,
            "rates": rates,
            "total_tokens": r["total_tokens"],
            "billed_tokens": billed_r,
            "input_tokens": r["input_tokens"],
            "output_tokens": r["output_tokens"],
            "cache_read_tokens": r["cache_read_tokens"],
            "cache_write_tokens": r["cache_write_tokens"],
        })
    # distinct active days in window
    dates = set()
    for s in sessions:
        st = s["started_at"]
        if st is None:
            continue
        try:
            dates.add(time.strftime("%Y-%m-%d", time.localtime(float(st))))
        except Exception:
            continue
    per_day = (total_usd / len(dates)) if dates else 0.0
    return {
        "models": models_out,
        "total_usd": total_usd,
        "unpriced_tokens": unpriced_tokens,
        "per_day_usd": per_day,
        "active_days": len(dates),
    }


# ---------- cache wrapper ----------

def cached(endpoint, days_str, builder):
    now = time.time()
    mtime = get_db_mtime()
    omtime = get_opencode_mtime()
    # pricing mtime also invalidates cost/pricing
    try:
        pmtime = os.path.getmtime(PRICING_PATH)
    except OSError:
        pmtime = 0.0
    key = (endpoint, days_str)
    with _CACHE_LOCK:
        ent = _CACHE.get(key)
        if ent is not None:
            age = now - ent["at"]
            if age < CACHE_TTL and ent["mtime"] == mtime and ent.get("omtime", 0) == omtime and ent.get("pmtime", 0) == pmtime:
                return ent["data"], age
    data = builder()
    with _CACHE_LOCK:
        _CACHE[key] = {"data": data, "at": now, "mtime": mtime, "omtime": omtime, "pmtime": pmtime}
        _LAST_BUILD["ts"] = now
    return data, 0.0


def invalidate_all():
    with _CACHE_LOCK:
        _CACHE.clear()
        _LAST_BUILD["ts"] = time.time()


# ---------- HTTP handler ----------

class Handler(BaseHTTPRequestHandler):
    server_version = "InsightsBoard/1.0"
    timeout = 60

    def log_message(self, fmt, *args):
        pass

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        qs = parse_qs(u.query)
        now = time.time()
        mtime = get_db_mtime()
        if path == "/api/health":
            with _CACHE_LOCK:
                last = _LAST_BUILD["ts"]
            age = (now - last) if last else 0.0
            self._send_json({"ok": True, "db": DB_PATH, "db_mtime": mtime,
                             "opencode_db": OPENCODE_DB_PATH,
                             "opencode_mtime": get_opencode_mtime(),
                             "cache_age_s": age})
            return
        if path == "/api/pricing":
            pricing = load_pricing()
            out = {"generated_at": now, "db_mtime": mtime}
            if isinstance(pricing, dict):
                out.update(pricing)
            else:
                out["models"] = {}
            self._send_json(out)
            return
        if path in ("/api/summary", "/api/insights", "/api/models", "/api/platforms", "/api/tools",
                    "/api/skills", "/api/activity", "/api/cost", "/api/opencode",
                    "/api/claudecode", "/api/antigravity"):
            days_str, cutoff, days_int = parse_days(qs)
            endpoint = path.split("/")[-1]
            # /api/insights is a documented alias of /api/summary (canonical).
            if endpoint == "insights":
                endpoint = "summary"
            if endpoint == "summary":
                data, _age = cached(endpoint, days_str, lambda: build_summary(cutoff))
            elif endpoint == "models":
                data, _age = cached(endpoint, days_str, lambda: build_models(cutoff))
            elif endpoint == "platforms":
                data, _age = cached(endpoint, days_str, lambda: build_platforms(cutoff))
            elif endpoint == "tools":
                data, _age = cached(endpoint, days_str, lambda: build_tools(cutoff))
            elif endpoint == "skills":
                data, _age = cached(endpoint, days_str, lambda: build_skills(cutoff))
            elif endpoint == "activity":
                data, _age = cached(endpoint, days_str, lambda: build_activity(cutoff, days_str, days_int))
            elif endpoint == "cost":
                data, _age = cached(endpoint, days_str, lambda: build_cost(cutoff))
            elif endpoint == "opencode":
                data, _age = cached(endpoint, days_str, lambda: build_opencode(cutoff, days_str, days_int))
            elif endpoint == "claudecode":
                # TASK5: full re-scan per request (sources are small); no cache.
                data = build_claudecode(cutoff, days_str, days_int)
            elif endpoint == "antigravity":
                data = build_antigravity(cutoff, days_str, days_int)
            else:
                self._send_json({"error": "unknown"}, 404)
                return
            out = {"generated_at": now, "db_mtime": mtime, "opencode_mtime": get_opencode_mtime(), "days": days_str}
            # cached data already computed; use fresh generated_at? keep now for freshness
            # but preserve cache semantics: if hit, generated_at should reflect original?
            # Use the cache entry's time for generated_at to show staleness.
            if endpoint in ("claudecode", "antigravity"):
                gen = now
            else:
                with _CACHE_LOCK:
                    ent = _CACHE.get((endpoint, days_str))
                    gen = ent["at"] if ent else now
            out["generated_at"] = gen
            out.update(data)
            # keep the requested window echo even if a builder ever sets it
            out["days"] = days_str
            self._send_json(out)
            return
        # static - redirect root UI to console
        if path == "/" or path == "/index.html":
            host = self.headers.get("Host", "localhost:8901").split(":")[0]
            self.send_response(302)
            self.send_header("Location", f"http://{host}:8903/#/insights")
            self.end_headers()
            return
        if path == "/app.js":
            self._send_file(WEB_DIR / "app.js", "text/javascript; charset=utf-8")
            return
        if path == "/style.css":
            self._send_file(WEB_DIR / "style.css", "text/css; charset=utf-8")
            return
        self.send_response(404)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"not found")

    def do_HEAD(self):
        u = urlparse(self.path)
        path = u.path
        if path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            return
        if path == "/app.js":
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.end_headers()
            return
        if path == "/style.css":
            self.send_response(200)
            self.send_header("Content-Type", "text/css; charset=utf-8")
            self.end_headers()
            return
        if path.startswith("/api/"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            return
        self.send_response(404)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/api/pricing":
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"not found")
            return
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            length = 0
        if length <= 0 or length > 1_000_000:
            self._send_json({"error": "empty or too large body"}, 400)
            return
        try:
            raw = self.rfile.read(length)
            data = json.loads(raw.decode("utf-8"))
        except Exception as e:
            self._send_json({"error": f"invalid JSON: {e}"}, 400)
            return
        err = validate_pricing(data)
        if err:
            self._send_json({"error": err}, 400)
            return
        # atomic write tmp+rename
        tmp = PRICING_PATH.with_suffix(".json.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.write("\n")
            os.replace(tmp, PRICING_PATH)
        except OSError as e:
            self._send_json({"error": f"write failed: {e}"}, 500)
            return
        invalidate_all()
        self._send_json({"ok": True, "models": data["models"]})


def validate_pricing(data):
    if not isinstance(data, dict):
        return "body must be a JSON object"
    if "models" not in data:
        return "missing 'models'"
    models = data["models"]
    if not isinstance(models, dict):
        return "'models' must be an object"
    for name, entry in models.items():
        if not isinstance(name, str) or not name:
            return f"invalid model name: {name!r}"
        if not isinstance(entry, dict):
            return f"entry for {name!r} must be an object"
        for req in ("input", "output"):
            if req not in entry:
                return f"entry for {name!r} missing '{req}'"
            v = entry[req]
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                return f"entry for {name!r} field '{req}' must be a number"
            if v < 0:
                return f"entry for {name!r} field '{req}' must be >= 0"
        for opt in ("cache_read", "cache_write"):
            if opt in entry:
                v = entry[opt]
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    return f"entry for {name!r} field '{opt}' must be a number"
                if v < 0:
                    return f"entry for {name!r} field '{opt}' must be >= 0"
        if "note" in entry and not isinstance(entry["note"], str):
            return f"entry for {name!r} field 'note' must be a string"
        if "provider" in entry and not isinstance(entry["provider"], str):
            return f"entry for {name!r} field 'provider' must be a string"
        if "also" in entry:
            if not isinstance(entry["also"], list):
                return f"entry for {name!r} field 'also' must be a list"
            for a in entry["also"]:
                if not isinstance(a, str):
                    return f"entry for {name!r} field 'also' must be list of strings"
        # Any other future extra fields are allowed and preserved verbatim
        # (POST writes the body as-is via atomic tmp+rename).
    return None


def main():
    global DB_PATH, OPENCODE_DB_PATH
    ap = argparse.ArgumentParser(description="Insights Board server (stdlib only)")
    ap.add_argument("--host", default="0.0.0.0",
                    help="bind address (default 0.0.0.0 — project rule: projects host on the LAN)")
    ap.add_argument("--port", type=int, default=8901)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--opencode-db", default=DEFAULT_OPENCODE_DB)
    args = ap.parse_args()
    DB_PATH = args.db
    OPENCODE_DB_PATH = args.opencode_db
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    srv.daemon_threads = True
    print(f"insights-board serving {WEB_DIR} + API on http://{args.host}:{args.port}/ (timeout={Handler.timeout}s) db={DB_PATH} opencode_db={OPENCODE_DB_PATH}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
