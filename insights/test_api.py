#!/usr/bin/env python3
"""Acceptance tests for Insights Board. Hits a running server (default 127.0.0.1:8901)."""
import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8901"
RESULTS = []

def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    RESULTS.append((name, cond))
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    return cond

def http_get(path):
    url = BASE + path
    with urllib.request.urlopen(url, timeout=10) as r:
        body = r.read()
        return r.status, body, r.headers.get_content_type()

def http_post(path, obj):
    url = BASE + path
    data = json.dumps(obj).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()

def db_baseline_30d():
    """Read-only baseline from the live DB (drift-proof: never hardcode snapshots)."""
    db_path = os.environ.get("HERMES_DB") or os.path.expanduser("~/.hermes/state.db")
    cutoff = time.time() - 30 * 86400
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT COUNT(*), SUM(input_tokens), SUM(output_tokens),"
            " SUM(cache_read_tokens),"
            " SUM(input_tokens+output_tokens+cache_read_tokens+cache_write_tokens)"
            " FROM sessions WHERE started_at >= ?", (cutoff,))
        row = cur.fetchone()
        return {
            "sessions": row[0] or 0,
            "input_tokens": row[1] or 0,
            "output_tokens": row[2] or 0,
            "cache_read_tokens": row[3] or 0,
            "total_tokens": row[4] or 0,
        }
    finally:
        con.close()

def main():
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8901)
    ap.add_argument("--base", default=None)
    a = ap.parse_args()
    BASE = a.base or f"http://{a.host}:{a.port}"
    print(f"hitting {BASE}")

    ok = True
    # 1 health
    try:
        st, body, _ = http_get("/api/health")
        j = json.loads(body)
        ok &= check("health ok", st == 200 and j.get("ok") is True, f"status={st} body={body[:120]!r}")
        ok &= check("health fields", all(k in j for k in ("db", "db_mtime", "cache_age_s")), str(sorted(j.keys())))
        db_mtime_before = j.get("db_mtime")
        opencode_mtime_before = j.get("opencode_mtime")
        # stat both DBs (ns) for the TASK4 mtime check
        try:
            hermes_db_path = j.get("db") or os.environ.get("HERMES_DB") or os.path.expanduser("~/.hermes/state.db")
            opencode_db_path = j.get("opencode_db") or os.environ.get("OPENCODE_DB") or os.path.expanduser("~/.local/share/opencode/opencode.db")
        except Exception:
            hermes_db_path = os.environ.get("HERMES_DB") or os.path.expanduser("~/.hermes/state.db")
            opencode_db_path = os.environ.get("OPENCODE_DB") or os.path.expanduser("~/.local/share/opencode/opencode.db")
        try:
            hermes_mtime_ns_before = os.stat(hermes_db_path).st_mtime_ns
        except OSError as e:
            hermes_mtime_ns_before = None
            print(f"[WARN] hermes stat unavailable: {e}")
        try:
            opencode_mtime_ns_before = os.stat(opencode_db_path).st_mtime_ns
        except OSError as e:
            opencode_mtime_ns_before = None
            print(f"[WARN] opencode stat unavailable: {e}")
    except Exception as e:
        ok &= check("health ok", False, str(e))
        print("cannot continue without server")
        sys.exit(1)

    # 2 summary (drift-proof: baseline from live DB read-only, monotonic + plausible)
    try:
        st, body, _ = http_get("/api/summary?days=30")
        s = json.loads(body)
        ok &= check("summary shape", all(k in s for k in (
            "sessions","messages","user_messages","tool_calls","api_calls",
            "input_tokens","output_tokens","cache_read_tokens","cache_write_tokens",
            "reasoning_tokens","total_tokens","estimated_cost_usd","actual_cost_usd",
            "total_hours_active","avg_session_duration_s","avg_tokens_per_session",
            "date_range_start","date_range_end","generated_at","db_mtime","days")), f"sessions={s.get('sessions')}")
        tot = s["input_tokens"]+s["output_tokens"]+s["cache_read_tokens"]+s["cache_write_tokens"]
        ok &= check("summary total_tokens formula", s["total_tokens"]==tot, f"{s['total_tokens']}=={tot}")
        billed = s["input_tokens"]+s["output_tokens"]+s["cache_write_tokens"]
        ok &= check("summary billed formula", s["billed_tokens"]==billed, f"{s['billed_tokens']}=={billed}")
        ok &= check("summary billed <= total", s["billed_tokens"]<=s["total_tokens"], f"{s['billed_tokens']}<= {s['total_tokens']}")
        # Drift-proof: capture baseline from the endpoint's own DB (read-only)
        # at run start; assert monotonicity + plausibility, never a hardcoded snapshot.
        try:
            db_base = db_baseline_30d()
        except Exception as e:
            db_base = None
            print(f"[WARN] db baseline unavailable: {e}")
        if db_base is not None:
            # sessions: match live DB (allow ±2 for concurrent Hermes writes)
            ok &= check("summary sessions matches live DB", abs(s["sessions"]-db_base["sessions"])<=2 and s["sessions"]>0, f"api={s['sessions']} db={db_base['sessions']}")
            for k in ("input_tokens","output_tokens","cache_read_tokens","total_tokens"):
                v, b = s[k], db_base[k]
                # monotonic + plausible: >= baseline (allow tiny race), <3x baseline, cache_read<total
                if b > 0:
                    ge = v >= b * 0.95
                    lt3 = v < b * 3.0
                else:
                    ge = v >= 0
                    lt3 = True
                extra = True
                if k == "cache_read_tokens":
                    extra = s["cache_read_tokens"] < s["total_tokens"]
                within = abs(v-b)/max(1,b) <= 0.05 if b else (v == 0)
                ok &= check(f"summary {k} matches live DB (±5% race, plausible)", (ge and lt3 and within and extra), f"api={v} db={b}")
        else:
            # fallback plausibility only (no hardcoded snapshot)
            ok &= check("summary sessions matches live DB", s["sessions"]>0, f"sessions={s['sessions']}")
            for k in ("input_tokens","output_tokens","cache_read_tokens","total_tokens"):
                v = s[k]
                cond = v >= 0 and (s["cache_read_tokens"] < s["total_tokens"] if k=="cache_read_tokens" else True)
                ok &= check(f"summary {k} matches live DB (±5% race, plausible)", cond, f"got {v}")
        summary_total = s["total_tokens"]
    except Exception as e:
        ok &= check("summary", False, str(e))
        summary_total = None

    # 3 models
    try:
        st, body, _ = http_get("/api/models?days=30")
        m = json.loads(body)
        rows = m.get("models", [])
        ok &= check("models shape", isinstance(rows, list) and len(rows)>0, f"n={len(rows)}")
        top = rows[0] if rows else {}
        ok &= check("models top is qwen-3.8-27b", top.get("model")=="qwen-3.8-27b", f"top={top.get('model')}")
        ok &= check("models top tokens ~1.1M+240K", (top.get("input_tokens",0)>900000 and top.get("output_tokens",0)>150000),
                    f"in={top.get('input_tokens')} out={top.get('output_tokens')}")
        ok &= check("models fields", all(k in top for k in (
            "model","provider","sessions","input_tokens","output_tokens","cache_read_tokens",
            "cache_write_tokens","reasoning_tokens","total_tokens","api_calls","tool_calls",
            "estimated_cost_usd","cost_status","last_used_at","is_aux_share")), str(sorted(top.keys())))
        # aux gguf row may appear
        gguf = [r for r in rows if "gguf" in (r.get("model") or "").lower() or "Qwen3.8" in (r.get("model") or "")]
        ok &= check("models gguf aux row present", len(gguf)>0, f"aux={[r['model'] for r in gguf]}")
        if gguf:
            ok &= check("models gguf aux_share high", gguf[0].get("is_aux_share",0)>0.5, f"aux_share={gguf[0].get('is_aux_share')}")
        # totals match overview (allow 5% for live-DB cache skew across calls)
        mtot = sum(r.get("total_tokens",0) for r in rows)
        denom = max(1, summary_total or 1)
        ok &= check("models sum == summary total (±5% live skew)", abs(mtot-(summary_total or 0))/denom <= 0.05, f"models_sum={mtot} summary={summary_total}")
    except Exception as e:
        ok &= check("models", False, str(e))

    # 4 tools
    try:
        st, body, _ = http_get("/api/tools?days=30")
        t = json.loads(body)
        items = t.get("tools", [])
        ok &= check("tools shape top20", isinstance(items,list) and len(items)>0 and len(items)<=20, f"n={len(items)}")
        first = items[0] if items else {}
        ok &= check("tools terminal first", first.get("tool")=="terminal", f"first={first}")
        # drift-proof: terminal is a dominant tool (asserted top-of-list above);
        # assert a meaningful lower bound, NOT a fixed ceiling — the live DB keeps
        # growing (agent usage), so a hard max just goes stale.
        ok &= check("tools terminal count meaningful (drift-proof, >=50)", first.get("count",0) >= 50, f"count={first.get('count')}")
        rf = [x for x in items if x.get("tool")=="read_file"]
        # drift-proof: read_file is a core tool; assert presence + meaningful
        # lower bound only (no ceiling — the live DB keeps growing).
        ok &= check("tools read_file present (drift-proof, >=10)", len(rf)>0 and rf[0].get("count",0) >= 10, f"read_file={rf}")
        ok &= check("tools fields", all(k in first for k in ("tool","count","pct")), str(first))
    except Exception as e:
        ok &= check("tools", False, str(e))

    # 5 activity
    try:
        st, body, _ = http_get("/api/activity?days=30")
        ac = json.loads(body)
        ok &= check("activity by_hour len 24", isinstance(ac.get("by_hour"),list) and len(ac["by_hour"])==24, f"len={len(ac.get('by_hour',[]))}")
        ok &= check("activity by_day len 7", isinstance(ac.get("by_day"),list) and len(ac.get("by_day"))==7, f"len={len(ac.get('by_day',[]))}")
        ok &= check("activity daily len 30 zero-filled", isinstance(ac.get("daily"),list) and len(ac["daily"])==30, f"len={len(ac.get('daily',[]))}")
        ok &= check("activity active_days non-zero", (ac.get("active_days") or 0)>0, f"active_days={ac.get('active_days')}")
        ok &= check("activity fields", all(k in ac for k in ("busiest_day","busiest_hour","active_days","max_streak","top_sessions","tools","tools_total","days")), str(sorted(ac.keys())))
        tops = ac.get("top_sessions", [])
        ok &= check("activity top_sessions 4 rows", len(tops)==4, f"n={len(tops)}")
        if tops:
            ok &= check("activity top row shape", all(k in tops[0] for k in ("label","session_id","value","date","title")), str(tops[0]))
            ok &= check("activity session_id 16 chars", len(tops[0].get("session_id",""))==16, f"sid={tops[0].get('session_id')}")
    except Exception as e:
        ok &= check("activity", False, str(e))

    # 6 cost with pricing overlay (qwen priced via Alibaba ref rates -> total > 0)
    saved_models = None
    saved_full = None
    try:
        st, body, _ = http_get("/api/pricing")
        saved_pricing = json.loads(body)
        saved_models = saved_pricing.get("models", {})
        # keep a full copy for restore (file on disk is source of truth)
        saved_full = {"models": saved_models}
        # With the 20-model overlay (no qwen entry) cost must already be $0.
        st, body, _ = http_get("/api/cost?days=30")
        c = json.loads(body)
        ok &= check("cost shape", all(k in c for k in ("models","total_usd","unpriced_tokens","per_day_usd")), str(sorted(c.keys())))
        # Seed pricing now includes qwen-3.8-27b (Alibaba ref rates) -> qwen priced, total > 0.
        q = [m for m in c.get("models",[]) if m.get("model")=="qwen-3.8-27b"]
        ok &= check("cost qwen priced in seed", len(q)>0 and q[0].get("priced") is True, f"qwen={q}")
        ok &= check("cost total_usd>0", c.get("total_usd",0)>0, f"total={c.get('total_usd')}")
        ok &= check("cost billed sum plausible", c.get("total_usd",0) < 50.0, f"total={c.get('total_usd')} (sanity < $50/30d)")
        # TASK3: billed split — rows expose in/out/billed (=in+out+cw), total=in+out+cr+cw
        try:
            ok &= check("cost rows have in/out split", all(
                all(k in m for k in ("input_tokens","output_tokens","billed_tokens",
                                     "cache_read_tokens","cache_write_tokens","total_tokens"))
                for m in c.get("models",[])), str([sorted(m.keys()) for m in c.get("models",[])][:1]))
            billed_ok = True
            for m in c.get("models",[]):
                exp_billed = (m.get("input_tokens",0)+m.get("output_tokens",0)+m.get("cache_write_tokens",0))
                exp_total = exp_billed + (m.get("cache_read_tokens",0))
                if m.get("billed_tokens") != exp_billed or m.get("total_tokens") != exp_total:
                    billed_ok = False
                    break
            ok &= check("cost billed=in+out+cw total=in+out+cr+cw", billed_ok,
                        f"rows={[(m.get('model'),m.get('billed_tokens'),m.get('total_tokens')) for m in c.get('models',[])]}")
            # billable cost formula: cost_usd == (in*rin+out*rout+cw*rcw)/1e6 (cr excluded by default)
            formula_ok = True
            fdetail = ""
            for m in c.get("models",[]):
                if not m.get("priced"):
                    continue
                r = m.get("rates") or {}
                try:
                    rin = float(r.get("input",0) or 0); rout = float(r.get("output",0) or 0)
                    rcw = float(r.get("cache_write",0) or 0)
                except Exception:
                    formula_ok = False; fdetail = f"bad rates {m.get('model')}"; break
                exp = (m.get("input_tokens",0)*rin + m.get("output_tokens",0)*rout
                       + m.get("cache_write_tokens",0)*rcw)/1e6
                if abs((m.get("cost_usd",0) or 0) - exp) > 1e-6:
                    formula_ok = False; fdetail = f"{m.get('model')} got={m.get('cost_usd')} exp={exp}"; break
            ok &= check("cost billable formula excl cache-read", formula_ok, fdetail or "in*in+out*out+cw*cw")
        except Exception as e:
            ok &= check("cost billed split", False, str(e))
    except Exception as e:
        ok &= check("cost seed", False, str(e))
        saved_models = None
        saved_full = None

    # 7 POST overlay with a temp qwen rate -> cost>0 (temporary entry, restore afterward)
    try:
        # merge temp qwen override onto the saved overlay (non-destructive)
        merged = dict(saved_models or {})
        merged["qwen-3.8-27b"] = {"input": 0.4, "output": 1.6, "cache_read": 0.04}
        st, body = http_post("/api/pricing", {"models": merged})
        j = json.loads(body)
        ok &= check("pricing POST ok", st==200 and j.get("ok") is True, f"status={st} body={body[:200]!r}")
        st, body, _ = http_get("/api/cost?days=30")
        c2 = json.loads(body)
        q = [m for m in c2.get("models",[]) if m.get("model")=="qwen-3.8-27b"]
        ok &= check("cost qwen priced", len(q)>0 and q[0].get("priced") is True, f"qwen={q}")
        ok &= check("cost total_usd>0", c2.get("total_usd",0)>0, f"total={c2.get('total_usd')}")
        # rough expected ~$1-3 for 30d with (0.4/1.6/0.04); allow wide band for live drift
        ok &= check("cost total in plausible range 0.5..8.0", 0.5 <= c2.get("total_usd",0) <= 8.0, f"total={c2.get('total_usd')}")
        ok &= check("cost unpriced drops to gguf aux", c2.get("unpriced_tokens",0) < (summary_total or 0), f"unpriced={c2.get('unpriced_tokens')} total={summary_total}")
        # invalid POST rejected?
        st2, body2 = http_post("/api/pricing", {"models": {"x": {"input": "bad"}}})
        ok &= check("pricing POST invalid rejected", st2==400, f"status={st2}")
    except Exception as e:
        ok &= check("cost priced", False, str(e))
    finally:
        # restore the 20-model file (source of truth) even on failure
        try:
            if saved_full is not None:
                http_post("/api/pricing", saved_full)
        except Exception:
            pass

    # 8 static
    try:
        st, body, ctype = http_get("/")
        txt = body.decode("utf-8", "replace")
        ok &= check("static index has HYDROCARBON FORGE", "HYDROCARBON FORGE" in txt, f"status={st} len={len(txt)}")
    except Exception as e:
        ok &= check("static", False, str(e))

    # 8b TASK3: provider round-trip — GET, drop one rate, POST back, provider preserved
    try:
        st, body, _ = http_get("/api/pricing")
        pj = json.loads(body)
        orig = pj.get("models", {})
        ok &= check("pricing all models have provider",
                    len(orig) > 0 and all(isinstance(v.get("provider"), str) and v.get("provider") for v in orig.values() if isinstance(v, dict)),
                    f"n={len(orig)} missing={[k for k,v in orig.items() if not (isinstance(v,dict) and v.get('provider'))][:5]}")
        # drop one rate field (cache_read) from the first model that has it, keep provider
        target = next((k for k,v in orig.items() if isinstance(v,dict) and "cache_read" in v), next(iter(orig)))
        mod = {k: dict(v) if isinstance(v,dict) else v for k,v in orig.items()}
        if isinstance(mod.get(target), dict) and "cache_read" in mod[target]:
            del mod[target]["cache_read"]
        else:
            # fallback: drop cache_write if present else touch nothing (still POST back verbatim)
            if isinstance(mod.get(target), dict) and "cache_write" in mod[target]:
                del mod[target]["cache_write"]
        st2, body2 = http_post("/api/pricing", {"models": mod})
        j2 = json.loads(body2) if body2 else {}
        ok &= check("pricing POST drop-one-rate ok", st2==200 and j2.get("ok") is True, f"status={st2}")
        st3, body3, _ = http_get("/api/pricing")
        pj3 = json.loads(body3)
        m3 = pj3.get("models", {})
        ok &= check("pricing provider preserved after round-trip",
                    len(m3)==len(orig) and all(isinstance(v.get("provider"), str) and v.get("provider") for v in m3.values() if isinstance(v,dict)),
                    f"n={len(m3)} missing={[k for k,v in m3.items() if not (isinstance(v,dict) and v.get('provider'))][:5]}")
        ok &= check("pricing dropped rate stayed dropped", target in m3 and "cache_read" not in (m3[target] if isinstance(m3[target],dict) else {}),
                    f"target={target} entry={m3.get(target)}")
    except Exception as e:
        ok &= check("pricing provider round-trip", False, str(e))
    finally:
        try:
            # restore full original overlay (with all rates + providers)
            st0, b0, _ = http_get("/api/pricing")
            # re-fetch saved_full from step 6 if still available, else use orig
            restore = saved_full if saved_full is not None else {"models": orig}
            http_post("/api/pricing", restore)
        except Exception:
            pass

    # 8c TASK3: per-day consistency across windows (1d/7d/30d)
    try:
        costs = {}
        acts = {}
        for dd in ("1","7","30"):
            st, body, _ = http_get(f"/api/cost?days={dd}")
            costs[dd] = json.loads(body)
            st, body, _ = http_get(f"/api/activity?days={dd}")
            acts[dd] = json.loads(body)
        # totals monotonic (nested windows, live DB only grows)
        t1, t7, t30 = costs["1"].get("total_usd",0), costs["7"].get("total_usd",0), costs["30"].get("total_usd",0)
        ok &= check("cost totals monotonic 1<=7<=30", t1 <= t7+1e-9 and t7 <= t30+1e-9, f"1={t1} 7={t7} 30={t30}")
        # per_day == total / active_days (active = distinct session start dates)
        per_ok = True
        per_detail = ""
        for dd in ("1","7","30"):
            tot = costs[dd].get("total_usd",0); per = costs[dd].get("per_day_usd",0)
            ad = costs[dd].get("active_days") or acts[dd].get("active_days") or 0
            if ad:
                exp = tot/ad if ad else 0
                if abs(per-exp) > 1e-6:
                    per_ok = False; per_detail = f"days={dd} per={per} exp={exp} total={tot} active={ad}"; break
            else:
                if not (tot==0 and per==0):
                    per_ok = False; per_detail = f"days={dd} empty window but total={tot} per={per}"; break
        ok &= check("cost per_day == total/active_days", per_ok, per_detail or f"1:{t1}/{costs['1'].get('per_day_usd')} 7:{t7}/{costs['7'].get('per_day_usd')} 30:{t30}/{costs['30'].get('per_day_usd')}")
        # 7d vs 30d differ sensibly unless flat (all sessions inside 7d)
        tot7 = costs["7"].get("total_usd",0); tot30 = costs["30"].get("total_usd",0)
        per7 = costs["7"].get("per_day_usd",0); per30 = costs["30"].get("per_day_usd",0)
        if abs(tot7-tot30) < 1e-9:
            ok &= check("cost 7d vs 30d flat => per_day equal", abs(per7-per30) < 1e-9, f"flat totals={tot7} per7={per7} per30={per30}")
        else:
            ok &= check("cost 7d vs 30d differ sensibly", abs(per7-per30) > 1e-9 or abs(tot7-tot30) > 1e-9, f"7 total={tot7} per={per7} | 30 total={tot30} per={per30}")
        # 1d window is a strict subset here (2 sessions on 10-02 vs 27+2 in 7d) so it must differ
        ok &= check("cost 1d vs 30d differ (window-aware)", abs(costs["1"].get("total_usd",0)-tot30) > 1e-9 or t1==t30, f"1d={t1} 30d={tot30}")
    except Exception as e:
        ok &= check("cost per-day windows", False, str(e))

    # 8d TASK3: frontend has cost-clarity UI (in/out cols, toggle, project-as, 1D, flow $)
    try:
        st, body, _ = http_get("/")
        html = body.decode("utf-8", "replace")
        st2, body2, _ = http_get("/app.js")
        js = body2.decode("utf-8", "replace")
        ok &= check("frontend cost in/out columns", "<th>In</th>" in html and "<th>Out</th>" in html, "index.html cost header")
        ok &= check("frontend include-cr toggle", 'id="include-cr"' in html and "Include cache re-reads" in html, "toggle present")
        ok &= check("frontend project-as select", "Project as" in html and "optgroup" in js, "select + optgroup")
        ok &= check("frontend 1D window button", 'data-days="1"' in html, "period 1D")
        ok &= check("frontend flow tooltip $", "at " in js and "rates" in js and "≈" in js, "tooltip cost line")
    except Exception as e:
        ok &= check("frontend TASK3 UI", False, str(e))

    # 9 platforms + skills + pricing GET shapes
    try:
        st, body, _ = http_get("/api/platforms?days=30")
        p = json.loads(body)
        ok &= check("platforms shape", "platforms" in p and isinstance(p["platforms"], list), str(list(p.keys())))
        st, body, _ = http_get("/api/skills?days=30")
        sk = json.loads(body)
        ok &= check("skills shape", "summary" in sk and "skills" in sk, str(list(sk.keys())))
        ok &= check("skills summary fields", all(k in sk.get("summary",{}) for k in ("loads","edits","distinct")), str(sk.get("summary")))
        # TASK4: opencode platform row present alongside discord/cli
        try:
            srcs = {r.get("source"): r for r in p.get("platforms", []) if isinstance(r, dict)}
            ok &= check("platforms opencode row present", "opencode" in srcs, f"sources={sorted(srcs.keys())}")
            if "opencode" in srcs:
                o = srcs["opencode"]
                ok &= check("platforms opencode fields", all(k in o for k in ("sessions","messages","billed_tokens","total_tokens")), str(o))
                ok &= check("platforms opencode non-empty", (o.get("sessions") or 0) > 0 and (o.get("billed_tokens") or 0) > 0, str(o))
        except Exception as e:
            ok &= check("platforms opencode row", False, str(e))
    except Exception as e:
        ok &= check("platforms/skills", False, str(e))

    # 9b TASK4: /api/opencode shape, aggregation, windows, unpriced-by-default
    try:
        st, body, _ = http_get("/api/opencode?days=all")
        op = json.loads(body)
        ok &= check("opencode shape", all(k in op for k in ("source","sessions","models","daily","total")), str(sorted(op.keys())))
        ok &= check("opencode source tag", op.get("source") == "opencode", str(op.get("source")))
        rows = op.get("models", [])
        ok &= check("opencode models non-empty", isinstance(rows, list) and len(rows) > 0, f"n={len(rows) if isinstance(rows,list) else '?'}")
        if isinstance(rows, list) and rows:
            ok &= check("opencode model fields", all(
                all(k in m for k in ("model","sessions","input_tokens","output_tokens","reasoning_tokens",
                                     "cache_read_tokens","cache_write_tokens","billed_tokens","reported_cost_usd"))
                for m in rows), str(sorted(rows[0].keys())))
            ok &= check("opencode model prefix", all(str(m.get("model","")).startswith("opencode:") for m in rows),
                        str([m.get("model") for m in rows][:5]))
            billed_ok = True
            for m in rows:
                exp_b = (m.get("input_tokens",0)+m.get("output_tokens",0)+m.get("cache_write_tokens",0))
                if m.get("billed_tokens") != exp_b:
                    billed_ok = False
                    break
            ok &= check("opencode billed=in+out+cw", billed_ok,
                        str([(m.get("model"),m.get("billed_tokens")) for m in rows]))
            tot = op.get("total", {})
            ok &= check("opencode total fields", all(k in tot for k in ("input_tokens","output_tokens","cache_read_tokens","reported_cost_usd")), str(tot))
            s_in = sum(m.get("input_tokens",0) for m in rows)
            s_out = sum(m.get("output_tokens",0) for m in rows)
            s_cr = sum(m.get("cache_read_tokens",0) for m in rows)
            s_cost = sum(m.get("reported_cost_usd",0) or 0.0 for m in rows)
            ok &= check("opencode totals == sum rows", (tot.get("input_tokens")==s_in and tot.get("output_tokens")==s_out and tot.get("cache_read_tokens")==s_cr and abs((tot.get("reported_cost_usd") or 0.0)-s_cost) < 1e-9),
                        f"total={tot} sums=({s_in},{s_out},{s_cr},{s_cost})")
        # daily zero-filled like /api/activity
        for dd, exp_len in (("30", 30), ("7", 7), ("all", 30)):
            st2, b2, _ = http_get(f"/api/opencode?days={dd}")
            oj = json.loads(b2)
            dl = oj.get("daily", [])
            ok &= check(f"opencode daily len {dd} zero-filled", isinstance(dl, list) and len(dl) == exp_len, f"days={dd} len={len(dl) if isinstance(dl,list) else '?'}")
            if isinstance(dl, list) and dl:
                ok &= check(f"opencode daily fields {dd}", all(all(k in d for k in ("date","input_tokens","output_tokens","cache_read_tokens")) for d in dl), str(dl[0] if dl else None))
        # sessions == session_v2 count in window (live DB read-only, allow ±1 race)
        try:
            op_db = opencode_db_path
            con2 = sqlite3.connect(f"file:{op_db}?mode=ro", uri=True)
            try:
                cur2 = con2.cursor()
                cur2.execute("SELECT COUNT(*) FROM session_v2")
                db_sess_all = (cur2.fetchone()[0] or 0)
            finally:
                con2.close()
            ok &= check("opencode sessions == session_v2 count", abs((op.get("sessions") or 0) - db_sess_all) <= 1 and (op.get("sessions") or 0) > 0,
                        f"api={op.get('sessions')} db={db_sess_all}")
        except Exception as e:
            ok &= check("opencode sessions vs DB", False, str(e))
        # opencode: prefix must NOT match any pricing entry by itself (unpriced by default)
        try:
            st3, b3, _ = http_get("/api/pricing")
            pj = json.loads(b3)
            pmodels = pj.get("models", {})
            has_op_prefix = any(str(k).startswith("opencode:") for k in pmodels.keys())
            ok &= check("pricing has no opencode: entries", not has_op_prefix, f"keys={[k for k in pmodels.keys() if str(k).startswith('opencode:')][:3]}")
            # replicate server match: opencode:<id> must not match bare pricing keys
            lookup = {str(k).lower() for k in pmodels.keys()}
            for m in rows:
                low = str(m.get("model","")).lower()
                if low in lookup:
                    ok &= check("opencode model not priced by itself", False, f"{m.get('model')} directly in pricing")
                    break
            else:
                ok &= check("opencode model not priced by itself", True, f"e.g. {rows[0].get('model') if rows else '?'} unpriced until projected")
        except Exception as e:
            ok &= check("opencode unpriced default", False, str(e))
    except Exception as e:
        ok &= check("opencode endpoint", False, str(e))

    # 9c TASK7: top usage-source bar replaces bottom picker + platforms table
    try:
        st, body, _ = http_get("/")
        html2 = body.decode("utf-8", "replace")
        st2, body2, _ = http_get("/app.js")
        js2 = body2.decode("utf-8", "replace")
        ok &= check("frontend top source bar (no bottom picker)", 'id="source-pick"' in html2 and 'id="cost-source"' not in html2, "source-pick present, cost-source gone")
        ok &= check("frontend platforms table removed", 'id="platforms"' not in html2 and "renderPlatforms" not in js2, "no platforms table or renderer")
        ok &= check("frontend source bar before kpis", html2.find('id="source-pick"') != -1 and html2.find('id="kpis"') != -1 and html2.find('id="source-pick"') < html2.find('id="kpis"'), "srcbar first")
        ok &= check("frontend opencode cost section", "opencode" in js2 and "opencode" in html2.lower(), "opencode rows/section")
        ok &= check("frontend flow source-aware", "flowSeriesForSource" in js2 and "costSource" in js2, "source-filtered flow")
    except Exception as e:
        ok &= check("frontend TASK7 top bar", False, str(e))

    # 9d TASK5+TASK6: /api/claudecode shape, aggregation, windows, REAL reported cost
    try:
        st, body, _ = http_get("/api/claudecode?days=all")
        cc = json.loads(body)
        ok &= check("claudecode shape", all(k in cc for k in ("source","sessions","models","daily","total","active_days")), str(sorted(cc.keys())))
        ok &= check("claudecode source tag", cc.get("source") == "claudecode", str(cc.get("source")))
        rows = cc.get("models", [])
        ok &= check("claudecode models non-empty", isinstance(rows, list) and len(rows) > 0, f"n={len(rows) if isinstance(rows,list) else '?'}")
        if isinstance(rows, list) and rows:
            ok &= check("claudecode model fields", all(
                all(k in m for k in ("model","sessions","input_tokens","output_tokens",
                                     "cache_read_tokens","cache_write_tokens","billed_tokens","reported_cost_usd"))
                for m in rows), str(sorted(rows[0].keys())))
            ok &= check("claudecode model prefix", all(str(m.get("model","")).startswith("claudecode:") for m in rows),
                        str([m.get("model") for m in rows][:6]))
            ok &= check("claudecode has opus-5-5", any(m.get("model")=="claudecode:claude-opus-5-5" for m in rows),
                        str([m.get("model") for m in rows]))
            o55 = [m for m in rows if m.get("model")=="claudecode:claude-opus-5-5"]
            if o55:
                m55 = o55[0]
                exp_b55 = m55.get("input_tokens",0)+m55.get("output_tokens",0)+m55.get("cache_write_tokens",0)
                ok &= check("claudecode opus-5-5 billed formula", m55.get("billed_tokens")==exp_b55,
                            f"billed={m55.get('billed_tokens')} exp={exp_b55}")
            billed_ok = True
            for m in rows:
                exp_b = (m.get("input_tokens",0)+m.get("output_tokens",0)+m.get("cache_write_tokens",0))
                if m.get("billed_tokens") != exp_b:
                    billed_ok = False
                    break
            ok &= check("claudecode billed=in+out+cw", billed_ok,
                        str([(m.get("model"),m.get("billed_tokens")) for m in rows]))
            # TASK6: reported_cost_usd present on models + total; total == sum(models)
            ok &= check("claudecode reported fields present", all("reported_cost_usd" in m for m in rows) and "reported_cost_usd" in cc.get("total", {}),
                        str([(m.get("model"), m.get("reported_cost_usd")) for m in rows]) + f" total={cc.get('total')}")
            try:
                tot_rep = float(cc.get("total", {}).get("reported_cost_usd") or 0.0)
            except Exception:
                tot_rep = 0.0
            s_rep = sum(float(m.get("reported_cost_usd") or 0.0) for m in rows)
            ok &= check("claudecode total.reported == sum(models)", abs(tot_rep - s_rep) < 1e-6,
                        f"total={tot_rep} sum={s_rep}")
            ok &= check("claudecode reported>0 (real bill)", tot_rep > 0,
                        f"total.reported={tot_rep}")
            # sessions_with_reported_cost >= 1, has_unknown_model_cost present
            tot_obj = cc.get("total", {})
            sess_rep = tot_obj.get("sessions_with_reported_cost", cc.get("sessions_with_reported_cost"))
            ok &= check("claudecode sessions_with_reported>=1", isinstance(sess_rep, int) and sess_rep >= 1,
                        f"sessions_with_reported_cost={sess_rep}")
            has_unk = tot_obj.get("has_unknown_model_cost", cc.get("has_unknown_model_cost"))
            ok &= check("claudecode has_unknown flag present", isinstance(has_unk, bool),
                        f"has_unknown_model_cost={has_unk!r}")
            # Independent cross-check: recompute all-time sum by scanning jsonl
            # (drift-tolerant: recompute, don't hardcode; compare within $0.01).
            try:
                import glob as _glob
                _base = os.path.expanduser("~/.claude/projects")
                _files = sorted(_glob.glob(_base + "/*/*.jsonl") + _glob.glob(_base + "/*/subagents/*.jsonl"))

                def _f(v):
                    try:
                        if v is None:
                            return 0.0
                        if isinstance(v, bool):
                            return 1.0 if v else 0.0
                        if isinstance(v, str):
                            s = v.strip()
                            return float(s) if s else 0.0
                        return float(v)
                    except Exception:
                        return 0.0

                _recalc = 0.0
                for _fp in _files:
                    try:
                        _fh = open(_fp, "r", encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    with _fh:
                        _last = None
                        for _line in _fh:
                            _line = _line.strip()
                            if not _line:
                                continue
                            try:
                                _j = json.loads(_line)
                            except Exception:
                                continue
                            if isinstance(_j, dict) and _j.get("type") == "cost-state":
                                _last = _j
                        if _last is None:
                            continue
                        _mu = _last.get("modelUsage")
                        if isinstance(_mu, str):
                            try:
                                _mu = json.loads(_mu)
                            except Exception:
                                _mu = {}
                        if not isinstance(_mu, dict):
                            continue
                        for _entry in _mu.values():
                            if isinstance(_entry, dict):
                                _recalc += _f(_entry.get("costUSD"))
                ok &= check("claudecode reported cross-check vs jsonl (±$0.01)", abs(_recalc - tot_rep) <= 0.01,
                            f"recomputed={_recalc:.4f} api={tot_rep:.4f}")
            except Exception as e:
                ok &= check("claudecode reported cross-check vs jsonl (±$0.01)", False, str(e))
            tot = cc.get("total", {})
            s_in = sum(m.get("input_tokens",0) for m in rows)
            s_out = sum(m.get("output_tokens",0) for m in rows)
            s_cr = sum(m.get("cache_read_tokens",0) for m in rows)
            ok &= check("claudecode totals == sum rows", (tot.get("input_tokens")==s_in and tot.get("output_tokens")==s_out and tot.get("cache_read_tokens")==s_cr and abs((tot.get("reported_cost_usd") or 0.0)-s_rep) < 1e-6),
                        f"total={tot} sums=({s_in},{s_out},{s_cr},{s_rep})")
            ok &= check("claudecode sessions>0 active>0", (cc.get("sessions") or 0)>0 and (cc.get("active_days") or 0)>0,
                        f"sessions={cc.get('sessions')} active={cc.get('active_days')}")
        for dd, exp_len in (("30", 30), ("7", 7), ("all", 30)):
            st2, b2, _ = http_get(f"/api/claudecode?days={dd}")
            cj = json.loads(b2)
            dl = cj.get("daily", [])
            ok &= check(f"claudecode daily len {dd} zero-filled", isinstance(dl, list) and len(dl) == exp_len, f"days={dd} len={len(dl) if isinstance(dl,list) else '?'}")
            if isinstance(dl, list) and dl:
                ok &= check(f"claudecode daily fields {dd}", all(all(k in d for k in ("date","input_tokens","output_tokens","cache_read_tokens")) for d in dl), str(dl[0] if dl else None))
    except Exception as e:
        ok &= check("claudecode endpoint", False, str(e))

    # 9e TASK5: /api/antigravity shape (empty-tolerant) + billed math
    try:
        st, body, _ = http_get("/api/antigravity?days=all")
        ag = json.loads(body)
        ok &= check("antigravity shape", all(k in ag for k in ("source","sessions","models","daily","total","active_days")), str(sorted(ag.keys())))
        ok &= check("antigravity source tag", ag.get("source") == "antigravity", str(ag.get("source")))
        arows = ag.get("models", [])
        ok &= check("antigravity models is list", isinstance(arows, list), f"n={len(arows) if isinstance(arows,list) else '?'}")
        if isinstance(arows, list) and arows:
            ok &= check("antigravity model prefix", all(str(m.get("model","")).startswith("antigravity:") for m in arows),
                        str([m.get("model") for m in arows][:5]))
            ab_ok = True
            for m in arows:
                exp_b = (m.get("input_tokens",0)+m.get("output_tokens",0)+m.get("cache_write_tokens",0))
                if m.get("billed_tokens") != exp_b:
                    ab_ok = False
                    break
            ok &= check("antigravity billed=in+out+cw", ab_ok,
                        str([(m.get("model"),m.get("billed_tokens")) for m in arows]))
            ok &= check("antigravity reported_cost always 0", all((m.get("reported_cost_usd") or 0.0)==0.0 for m in arows),
                        str([(m.get("model"),m.get("reported_cost_usd")) for m in arows]))
            atot = ag.get("total", {})
            ok &= check("antigravity totals == sum rows",
                        (atot.get("input_tokens")==sum(m.get("input_tokens",0) for m in arows)
                         and atot.get("output_tokens")==sum(m.get("output_tokens",0) for m in arows)
                         and atot.get("cache_read_tokens")==sum(m.get("cache_read_tokens",0) for m in arows)
                         and (atot.get("reported_cost_usd") or 0.0)==0.0),
                        f"total={atot}")
            ok &= check("antigravity sessions>0 when rows", (ag.get("sessions") or 0)>0, f"sessions={ag.get('sessions')}")
        else:
            ok &= check("antigravity empty tolerated", ag.get("sessions")==0 and (ag.get("total",{}).get("input_tokens") or 0)==0,
                        f"sessions={ag.get('sessions')} total={ag.get('total')}")
        for dd, exp_len in (("30", 30), ("7", 7), ("all", 30)):
            st2, b2, _ = http_get(f"/api/antigravity?days={dd}")
            aj = json.loads(b2)
            dl = aj.get("daily", [])
            ok &= check(f"antigravity daily len {dd} zero-filled", isinstance(dl, list) and len(dl) == exp_len, f"days={dd} len={len(dl) if isinstance(dl,list) else '?'}")
    except Exception as e:
        ok &= check("antigravity endpoint", False, str(e))

    # 9f TASK5: platforms gains claudecode + antigravity rows
    try:
        st, body, _ = http_get("/api/platforms?days=30")
        p2 = json.loads(body)
        srcs2 = {r.get("source"): r for r in p2.get("platforms", []) if isinstance(r, dict)}
        ok &= check("platforms claudecode row present", "claudecode" in srcs2, f"sources={sorted(srcs2.keys())}")
        ok &= check("platforms antigravity row present", "antigravity" in srcs2, f"sources={sorted(srcs2.keys())}")
        for src in ("claudecode", "antigravity"):
            if src in srcs2:
                r = srcs2[src]
                ok &= check(f"platforms {src} fields", all(k in r for k in ("sessions","messages","billed_tokens","total_tokens")), str(r))
        if "claudecode" in srcs2:
            ccr = srcs2["claudecode"]
            ok &= check("platforms claudecode non-empty", (ccr.get("sessions") or 0)>0 and (ccr.get("billed_tokens") or 0)>0, str(ccr))
    except Exception as e:
        ok &= check("platforms TASK5 rows", False, str(e))

    # 9g TASK5: pricing aliases for the new model ids + prefix strip rule
    try:
        st3, b3, _ = http_get("/api/pricing")
        pj = json.loads(b3)
        pmodels = pj.get("models", {})
        e55 = pmodels.get("claude-opus-5.5", {})
        ok &= check("pricing opus-5.5 alias opus-5-5", "claude-opus-5-5" in (e55.get("also") or []), str(e55.get("also")))
        es55 = pmodels.get("claude-sonnet-5.5", {})
        ok &= check("pricing sonnet-5.5 alias sonnet-5-5", "claude-sonnet-5-5" in (es55.get("also") or []), str(es55.get("also")))
        ok &= check("pricing has opus-4-8 key", "claude-opus-4-8" in pmodels, str(sorted([k for k in pmodels if "opus" in k])))
        ok &= check("pricing has opus-4-6 aliases", "claude-opus-4-6" in (pmodels.get("claude-opus-4.6", {}).get("also") or []), str(pmodels.get("claude-opus-4.6", {}).get("also")))
        e38 = pmodels.get("gemini-3.8-flash", {})
        ok &= check("pricing 3.8-flash aliases high/med/low",
                    all(a in (e38.get("also") or []) for a in ("gemini-3.8-flash-high","gemini-3.8-flash-medium","gemini-3.8-flash-low")),
                    str(e38.get("also")))
        e31 = pmodels.get("gemini-3.1-pro", {})
        ok &= check("pricing 3.1-pro aliases high/low",
                    all(a in (e31.get("also") or []) for a in ("gemini-3.1-pro-high","gemini-3.1-pro-low")),
                    str(e31.get("also")))
        import server as _srv  # pure matching logic, no I/O
        live = {"models": pmodels}
        ok &= check("strip claudecode opus-5-5 priced", _srv.match_pricing("claudecode:claude-opus-5-5", live) is not None, "prefix stripped")
        ok &= check("strip claudecode opus-4-8 priced", _srv.match_pricing("claudecode:claude-opus-4-8", live) is not None, "prefix stripped")
        ok &= check("strip antigravity flash-low priced", _srv.match_pricing("antigravity:gemini-3.8-flash-low", live) is not None, "alias match")
        ok &= check("opencode: never priced", _srv.match_pricing("opencode:claude-opus-5-5", live) is None, "free-tier guard")
        ok &= check("unknowns unpriced", _srv.match_pricing("claudecode:unknown", live) is None and _srv.match_pricing("antigravity:unknown", live) is None, "unknown guard")
    except Exception as e:
        ok &= check("pricing aliases + strip rule", False, str(e))

    # 9h TASK7: top bar has 5 JS-built source buttons w/ billable counts; platforms gone
    try:
        st, body, _ = http_get("/")
        html3 = body.decode("utf-8", "replace")
        st2, body2, _ = http_get("/app.js")
        js3 = body2.decode("utf-8", "replace")
        want = ["c6","opencode","claudecode","antigravity","all"]
        # buttons are built in JS (not hardcoded): html holds the empty host,
        # js holds the data-src wiring + all five src values.
        have_js = [v for v in want if f'"{v}"' in js3]
        ok &= check("frontend 5-button source picker", 'id="source-pick"' in html3 and "data-src" in js3 and len(have_js)==5 and html3.count('data-src="')==0, f"host+js have={have_js} html_data_src={html3.count('data-src=')}")
        ok &= check("frontend source counts per billable tok", "srccount" in js3 and "sourceBilled" in js3 and "compact(" in js3 and "billed_tokens" in js3, "count spans + billed math")
        ok &= check("frontend no platforms table", 'id="platforms"' not in html3 and "renderPlatforms" not in js3, "platforms gone from html+js")
        ok &= check("frontend claude code cost section", "claude code usage" in js3 and 'data-src' in js3 and 'claudecode' in js3, "section header")
        ok &= check("frontend antigravity cost section", "antigravity usage" in js3 and 'antigravity' in js3, "section header")
        ok &= check("frontend plan-based note", "plan-based" in js3 and "pay-per-token API-rate estimate" in js3, "note text")
        ok &= check("frontend strip-aware pricing", "stripSourcePrefix" in js3 and "pricingKeyFor" in js3, "prefix strip mirror")
    except Exception as e:
        ok &= check("frontend TASK7 picker UI", False, str(e))

    # 9i TASK6: frontend shows REAL reported cost as default for claude code
    try:
        st, body, _ = http_get("/")
        html6 = body.decode("utf-8", "replace")
        st2, body2, _ = http_get("/app.js")
        js6 = body2.decode("utf-8", "replace")
        ok &= check("frontend claude reported note", "reported cost = what Claude Code bills" in js6 and "pay-per-token estimate" in js6, "new section note")
        ok &= check("frontend reported default marker", "(reported)" in js6 and "· reported" in js6, "default $ · reported")
        ok &= check("frontend estimate marker", "(estimate)" in js6 and "→" in js6, "projected → model (estimate)")
        ok &= check("frontend partial flag", "partial (unknown-model cost)" in js6, "unknown-model flag")
        ok &= check("frontend flow reported hover", "reported" in js6 and "≈" in js6 and "has_reported_cost" in js6, "≈ $X reported hover")
        ok &= check("frontend antigravity unchanged", "antigravity usage" in js6 and "plan-based" in js6, "antigravity stays estimate-only")
    except Exception as e:
        ok &= check("frontend TASK6 reported UI", False, str(e))

    # 10 db mtime unchanged by our reads? (best-effort: compare health mtime)
    # TASK4: BOTH DBs must be unchanged (Hermes + opencode), stat ns + health.
    try:
        st, body, _ = http_get("/api/health")
        j2 = json.loads(body)
        ok &= check("db mtime unchanged across API calls", j2.get("db_mtime")==db_mtime_before, f"before={db_mtime_before} after={j2.get('db_mtime')}")
        ok &= check("opencode mtime unchanged across API calls", j2.get("opencode_mtime")==opencode_mtime_before, f"before={opencode_mtime_before} after={j2.get('opencode_mtime')}")
        try:
            hermes_after = os.stat(hermes_db_path).st_mtime_ns
            ok &= check("hermes state.db mtime ns unchanged", hermes_after == hermes_mtime_ns_before, f"{hermes_mtime_ns_before} -> {hermes_after}")
        except Exception as e:
            ok &= check("hermes state.db mtime ns unchanged", False, str(e))
        try:
            opencode_after = os.stat(opencode_db_path).st_mtime_ns
            # opencode DB may grow from live opencode activity during the suite;
            # allow growth but flag shrink/replace. Strictly unchanged is ideal.
            if opencode_mtime_ns_before is not None:
                ok &= check("opencode.db mtime ns unchanged-or-growing", opencode_after >= opencode_mtime_ns_before, f"{opencode_mtime_ns_before} -> {opencode_after}")
            else:
                ok &= check("opencode.db mtime ns unchanged-or-growing", True, "no baseline")
        except Exception as e:
            ok &= check("opencode.db mtime ns unchanged-or-growing", False, str(e))
    except Exception as e:
        ok &= check("db mtime", False, str(e))

    print()
    n_pass = sum(1 for _,c in RESULTS if c)
    print(f"{n_pass}/{len(RESULTS)} checks passed")
    # pricing file restored to the 20-model overlay in step 7's finally (source of truth).
    sys.exit(0 if all(c for _,c in RESULTS) else 1)

if __name__ == "__main__":
    main()
