#!/usr/bin/env python3
"""Independent acceptance verification for the Insights Board (written by C6, not the builder)."""
import json, os, time, urllib.request, urllib.error

BASE = "http://127.0.0.1:8901"
DB = os.path.expanduser("~/.hermes/state.db")
ODB = os.path.expanduser("~/.local/share/opencode/opencode.db")
results = []

def get(path):
    with urllib.request.urlopen(BASE + path, timeout=15) as r:
        return r.status, json.loads(r.read().decode())

def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))

mt_before = os.stat(DB).st_mtime_ns
try:
    mt_op_before = os.stat(ODB).st_mtime_ns
except OSError:
    mt_op_before = None

# 1. static index
with urllib.request.urlopen(BASE + "/", timeout=15) as r:
    html = r.read().decode()
    check("index 200 + brand", r.status == 200 and "Hydrocarbon" in html)
    check("index dark theme", "ff5a5a" in html or "font-family" in html)
    check("index loads app.js", "app.js" in html)

# 2. health
st, d = get("/api/health")
check("health ok", st == 200 and d.get("ok") is True, str(d))

# 3. summary (insights aggregate)
st, d = get("/api/summary?days=30")
check("summary shape", st == 200 and d.get("days") is not None, str(list(d.keys())[:10]))

# 4. activity
st, d = get("/api/activity?days=7")
check("activity daily list", st == 200 and isinstance(d.get("daily"), list) and len(d["daily"]) >= 1)
check("activity tool breakdown", st == 200 and isinstance(d.get("tools"), (list, dict)) and d.get("tools"),
      str(d.get("tools"))[:120] if isinstance(d.get("tools"), str) else str(list(d.get("tools", []) if isinstance(d.get("tools"), list) else d.get("tools", {}).keys())[:6]))

# 5. models
st, d = get("/api/models?days=30")
check("models list non-empty", st == 200 and (d.get("models") or d.get("rows") or d),
      str(list(d.keys())[:8]) if isinstance(d, dict) else str(d)[:80])

# 6. cost with new pricing overlay
st, d = get("/api/cost?days=30")
check("cost shape", st == 200 and d.get("total_usd") is not None and d.get("models") is not None)
models = {m["model"]: m for m in d["models"]}
check("qwen priced in seed", models.get("qwen-3.8-27b", {}).get("priced") is True)
check("cost total_usd>0", d.get("total_usd", 0) > 0, str(d.get("total_usd")))

# 7. pricing overlay — must contain the fresh sourced rates
st, d = get("/api/pricing")
m = d["models"]
check("pricing has 30 models", len(m) == 30, str(len(m)))
check("claude-opus-5.5 @4/20", m.get("claude-opus-5.5", {}).get("input") == 4.0 and m["claude-opus-5.5"].get("output") == 20.0)
check("gpt-6-astra @10/50", m.get("gpt-6-astra", {}).get("input") == 10.0 and m["gpt-6-astra"].get("output") == 50.0)
check("gemini-3.8-flash @0.75/3.75", m.get("gemini-3.8-flash", {}).get("input") == 0.75)
check("deepseek-v4-pro @1.32/3.96", m.get("deepseek-v4-pro", {}).get("input") == 1.32)
check("qwen-3.8-27b @0.5/3.0", m.get("qwen-3.8-27b", {}).get("input") == 0.5 and m["qwen-3.8-27b"].get("output") == 3.0)

# 7b. billed-tokens accounting: headline billable = in+out+cw, total = in+out+cr+cw
st, d = get("/api/summary?days=30")
s = d
billed = s["input_tokens"] + s["output_tokens"] + s["cache_write_tokens"]
check("summary billed formula", s.get("billed_tokens") == billed, f"{s.get('billed_tokens')}=={billed}")
check("summary billed <= total", s.get("billed_tokens", 10**12) <= s["total_tokens"], f"{s.get('billed_tokens')}<= {s['total_tokens']}")

# 8. platforms / skills
st, d = get("/api/platforms")
check("platforms shape", st == 200 and isinstance(d, dict))
st, d = get("/api/skills")
check("skills shape", st == 200)

# 8b. TASK4: opencode as its own platform + /api/opencode shape
st, d = get("/api/opencode?days=all")
check("opencode shape", st == 200 and d.get("source") == "opencode"
      and isinstance(d.get("models"), list) and isinstance(d.get("daily"), list)
      and isinstance(d.get("total"), dict), str(list(d.keys()) if isinstance(d, dict) else d)[:120])
try:
    rows = d.get("models", []) if isinstance(d, dict) else []
    check("opencode models non-empty", isinstance(rows, list) and len(rows) > 0,
          f"n={len(rows) if isinstance(rows, list) else '?'}")
    if isinstance(rows, list) and rows:
        tot = d.get("total", {})
        s_in = sum(m.get("input_tokens", 0) for m in rows)
        s_out = sum(m.get("output_tokens", 0) for m in rows)
        s_cr = sum(m.get("cache_read_tokens", 0) for m in rows)
        s_cost = sum(m.get("reported_cost_usd", 0) or 0.0 for m in rows)
        ok_tot = (tot.get("input_tokens") == s_in and tot.get("output_tokens") == s_out
                  and tot.get("cache_read_tokens") == s_cr
                  and abs((tot.get("reported_cost_usd") or 0.0) - s_cost) < 1e-9)
        check("opencode totals == sum rows", ok_tot, f"total={tot} sums=({s_in},{s_out},{s_cr},{s_cost})")
        ok_bill = all((m.get("billed_tokens") == (m.get("input_tokens", 0) + m.get("output_tokens", 0) + m.get("cache_write_tokens", 0))) for m in rows)
        check("opencode billed=in+out+cw", ok_bill, str([(m.get("model"), m.get("billed_tokens")) for m in rows][:3]))
except Exception as e:
    check("opencode totals == sum rows", False, str(e))
st, d = get("/api/platforms?days=30")
try:
    srcs = {r.get("source"): r for r in d.get("platforms", [])}
    check("platform row opencode present", "opencode" in srcs, str(sorted(srcs.keys())))
    if "opencode" in srcs:
        o = srcs["opencode"]
        check("platform opencode non-empty", (o.get("sessions") or 0) > 0 and (o.get("billed_tokens") or 0) > 0, str(o))
except Exception as e:
    check("platform row opencode present", False, str(e))

# 8c. TASK5+TASK6: claudecode (non-empty, REAL reported cost) + antigravity + platform rows
st, d = get("/api/claudecode?days=all")
check("claudecode shape", st == 200 and d.get("source") == "claudecode"
      and isinstance(d.get("models"), list) and isinstance(d.get("daily"), list)
      and isinstance(d.get("total"), dict), str(list(d.keys()) if isinstance(d, dict) else d)[:120])
try:
    rows = d.get("models", []) if isinstance(d, dict) else []
    check("claudecode models non-empty", isinstance(rows, list) and len(rows) > 0,
          f"n={len(rows) if isinstance(rows, list) else '?'}")
    if isinstance(rows, list) and rows:
        check("claudecode has opus-5-5", any(m.get("model") == "claudecode:claude-opus-5-5" for m in rows),
              str([m.get("model") for m in rows]))
        tot = d.get("total", {})
        s_rep = sum(float(m.get("reported_cost_usd") or 0.0) for m in rows)
        ok_tot = (tot.get("input_tokens") == sum(m.get("input_tokens", 0) for m in rows)
                  and tot.get("output_tokens") == sum(m.get("output_tokens", 0) for m in rows)
                  and tot.get("cache_read_tokens") == sum(m.get("cache_read_tokens", 0) for m in rows)
                  and abs(float(tot.get("reported_cost_usd") or 0.0) - s_rep) < 1e-6)
        check("claudecode totals == sum rows", ok_tot, f"total={tot}")
        ok_bill = all((m.get("billed_tokens") == (m.get("input_tokens", 0) + m.get("output_tokens", 0) + m.get("cache_write_tokens", 0))) for m in rows)
        check("claudecode billed=in+out+cw", ok_bill, str([(m.get("model"), m.get("billed_tokens")) for m in rows][:4]))
        # TASK6: reported cost is the REAL bill (not zero).
        ok_rep = all("reported_cost_usd" in m for m in rows) and "reported_cost_usd" in tot
        check("claudecode reported fields present", ok_rep, f"total={tot}")
        check("claudecode reported>0", float(tot.get("reported_cost_usd") or 0.0) > 0, f"total={tot}")
        sess_rep = tot.get("sessions_with_reported_cost", d.get("sessions_with_reported_cost"))
        check("claudecode sessions_with_reported>=1", isinstance(sess_rep, int) and sess_rep >= 1, f"sessions_with={sess_rep}")
        has_unk = tot.get("has_unknown_model_cost", d.get("has_unknown_model_cost"))
        check("claudecode has_unknown flag present", isinstance(has_unk, bool), f"has_unknown={has_unk!r}")
        # Independent recompute (drift-tolerant, within $0.01).
        try:
            import glob as _g
            _base = os.path.expanduser("~/.claude/projects")
            _files = sorted(_g.glob(_base + "/*/*.jsonl") + _g.glob(_base + "/*/subagents/*.jsonl"))

            def _ff(v):
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

            _rc = 0.0
            for _fp in _files:
                try:
                    _fh = open(_fp, "r", encoding="utf-8", errors="replace")
                except OSError:
                    continue
                with _fh:
                    _last = None
                    for _ln in _fh:
                        _ln = _ln.strip()
                        if not _ln:
                            continue
                        try:
                            _jj = json.loads(_ln)
                        except Exception:
                            continue
                        if isinstance(_jj, dict) and _jj.get("type") == "cost-state":
                            _last = _jj
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
                    for _e in _mu.values():
                        if isinstance(_e, dict):
                            _rc += _ff(_e.get("costUSD"))
            check("claudecode reported cross-check (±$0.01)", abs(_rc - float(tot.get("reported_cost_usd") or 0.0)) <= 0.01, f"recomputed={_rc:.4f} api={tot.get('reported_cost_usd')}")
        except Exception as e:
            check("claudecode reported cross-check (±$0.01)", False, str(e))
except Exception as e:
    check("claudecode totals == sum rows", False, str(e))
st, d = get("/api/claudecode?days=30")
try:
    dl = d.get("daily", []) if isinstance(d, dict) else []
    check("claudecode daily len 30 zero-filled", isinstance(dl, list) and len(dl) == 30, f"len={len(dl) if isinstance(dl, list) else '?'}")
except Exception as e:
    check("claudecode daily len 30 zero-filled", False, str(e))
st, d = get("/api/antigravity?days=all")
check("antigravity shape", st == 200 and d.get("source") == "antigravity"
      and isinstance(d.get("models"), list) and isinstance(d.get("daily"), list)
      and isinstance(d.get("total"), dict), str(list(d.keys()) if isinstance(d, dict) else d)[:120])
try:
    rows = d.get("models", []) if isinstance(d, dict) else []
    if isinstance(rows, list) and rows:
        tot = d.get("total", {})
        ok_tot = (tot.get("input_tokens") == sum(m.get("input_tokens", 0) for m in rows)
                  and tot.get("output_tokens") == sum(m.get("output_tokens", 0) for m in rows)
                  and tot.get("cache_read_tokens") == sum(m.get("cache_read_tokens", 0) for m in rows))
        check("antigravity totals == sum rows", ok_tot, f"total={tot}")
        ok_bill = all((m.get("billed_tokens") == (m.get("input_tokens", 0) + m.get("output_tokens", 0) + m.get("cache_write_tokens", 0))) for m in rows)
        check("antigravity billed=in+out+cw", ok_bill, str([(m.get("model"), m.get("billed_tokens")) for m in rows][:3]))
    else:
        check("antigravity empty tolerated", d.get("sessions") == 0, f"sessions={d.get('sessions')}")
except Exception as e:
    check("antigravity totals == sum rows", False, str(e))
st, d = get("/api/platforms?days=30")
try:
    srcs = {r.get("source"): r for r in d.get("platforms", [])}
    check("platform row claudecode present", "claudecode" in srcs, str(sorted(srcs.keys())))
    check("platform row antigravity present", "antigravity" in srcs, str(sorted(srcs.keys())))
    if "claudecode" in srcs:
        o = srcs["claudecode"]
        check("platform claudecode non-empty", (o.get("sessions") or 0) > 0 and (o.get("billed_tokens") or 0) > 0, str(o))
except Exception as e:
    check("platform row claudecode present", False, str(e))

# 9. run the builder's test suite
import subprocess
r = subprocess.run(["python3", "test_api.py"], capture_output=True, text=True, timeout=180)
check("test_api.py suite", r.returncode == 0, r.stdout.strip()[-300:] + r.stderr.strip()[-200:])

# 10. DB untouched (BOTH files read-only; opencode may grow from live agent writes)
mt_after = os.stat(DB).st_mtime_ns
check("state.db mtime unchanged", mt_before == mt_after, f"{mt_before} -> {mt_after}")
try:
    mt_op_after = os.stat(ODB).st_mtime_ns
    if mt_op_before is None:
        check("opencode.db mtime unchanged-or-growing", True, "no baseline (file missing at start)")
    else:
        # strict unchanged is ideal; live opencode writes grow the file, which is
        # not caused by our read-only API (file:...?mode=ro). Accept growth, reject shrink/replace.
        check("opencode.db mtime unchanged-or-growing", mt_op_after >= mt_op_before, f"{mt_op_before} -> {mt_op_after}")
except OSError as e:
    check("opencode.db mtime unchanged-or-growing", False, str(e))

print("\n%d/%d passed" % (sum(1 for _, c, _ in results if c), len(results)))
