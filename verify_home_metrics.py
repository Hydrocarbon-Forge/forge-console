#!/usr/bin/env python3
"""
Verification script for FIX-HOME-3 (Item 1 & Item 2).
Asserts that /api/home token metrics match the insights engine all-sources billable token sums
within 2% live drift tolerance.
"""

import sys
import json
import urllib.request
import urllib.error

def fetch_json(url):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "ForgeConsoleVerify/1.0")
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        return json.loads(resp.read().decode("utf-8"))

def billed_tokens(src, doc):
    if not doc:
        return 0
    if src == "c6":
        return int(doc.get("billed_tokens", 0) or 0)
    models = doc.get("models")
    if isinstance(models, list) and len(models) > 0 and any("billed_tokens" in m for m in models):
        return sum(int(m.get("billed_tokens", 0) or 0) for m in models)
    total = doc.get("total") or {}
    return int(total.get("input_tokens", 0) or 0) + int(total.get("output_tokens", 0) or 0)

def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8913
    print(f"=== VERIFYING HOME TOKEN METRICS (Console Port: {port}, Insights Port: 8901) ===")

    # 1. Fetch live insights engine (8901) per-source endpoints
    c6_1d = billed_tokens("c6", fetch_json("http://127.0.0.1:8901/api/summary?days=1"))
    op_1d = billed_tokens("opencode", fetch_json("http://127.0.0.1:8901/api/opencode?days=1"))
    cc_1d = billed_tokens("claudecode", fetch_json("http://127.0.0.1:8901/api/claudecode?days=1"))
    ag_1d = billed_tokens("antigravity", fetch_json("http://127.0.0.1:8901/api/antigravity?days=1"))
    expected_today = c6_1d + op_1d + cc_1d + ag_1d

    print("Insights Engine days=1 (Today) Billed Tokens:")
    print(f"  - C6 (Hermes):        {c6_1d:>12,d} tokens ({c6_1d/1e6:.2f}M)")
    print(f"  - OpenCode:           {op_1d:>12,d} tokens ({op_1d/1e6:.2f}M)")
    print(f"  - Claude Code:        {cc_1d:>12,d} tokens ({cc_1d/1e6:.2f}M)")
    print(f"  - Antigravity (AGY):  {ag_1d:>12,d} tokens ({ag_1d/1e6:.2f}M)")
    print(f"  TOTAL EXPECTED TODAY: {expected_today:>12,d} tokens ({expected_today/1e6:.2f}M)")

    c6_all = billed_tokens("c6", fetch_json("http://127.0.0.1:8901/api/summary?days=all"))
    op_all = billed_tokens("opencode", fetch_json("http://127.0.0.1:8901/api/opencode?days=all"))
    cc_all = billed_tokens("claudecode", fetch_json("http://127.0.0.1:8901/api/claudecode?days=all"))
    ag_all = billed_tokens("antigravity", fetch_json("http://127.0.0.1:8901/api/antigravity?days=all"))
    expected_alltime = c6_all + op_all + cc_all + ag_all

    print("\nInsights Engine days=all (All-Time) Billed Tokens:")
    print(f"  - C6 (Hermes):        {c6_all:>12,d} tokens ({c6_all/1e6:.2f}M)")
    print(f"  - OpenCode:           {op_all:>12,d} tokens ({op_all/1e6:.2f}M)")
    print(f"  - Claude Code:        {cc_all:>12,d} tokens ({cc_all/1e6:.2f}M)")
    print(f"  - Antigravity (AGY):  {ag_all:>12,d} tokens ({ag_all/1e6:.2f}M)")
    print(f"  TOTAL EXPECTED ALL:   {expected_alltime:>12,d} tokens ({expected_alltime/1e6:.2f}M)")

    # 2. Fetch console dashboard payload
    try:
        home_doc = fetch_json(f"http://127.0.0.1:{port}/api/home")
    except urllib.error.URLError as e:
        print(f"\n[ERROR] Could not connect to Forge Console on http://127.0.0.1:{port}/api/home: {e}")
        print(f"Make sure the console server is running (e.g. PORT={port} python3 server.py).")
        sys.exit(1)
    today_block = home_doc.get("billed_today_by_source", {})
    alltime_block = home_doc.get("billed_alltime_by_source", {})

    actual_today = today_block.get("total", 0)
    actual_alltime = alltime_block.get("total", 0)

    print(f"\nForge Console http://127.0.0.1:{port}/api/home returned:")
    print(f"  - billed_today_by_source.total:   {actual_today:>12,d} tokens ({actual_today/1e6:.2f}M)")
    print(f"    breakdown: {today_block.get('by_source')}")
    print(f"  - billed_alltime_by_source.total: {actual_alltime:>12,d} tokens ({actual_alltime/1e6:.2f}M)")
    print(f"    breakdown: {alltime_block.get('by_source')}")

    # 3. Assert tolerance <= 2.0%
    drift_today = abs(actual_today - expected_today) / max(1, expected_today) * 100.0
    drift_alltime = abs(actual_alltime - expected_alltime) / max(1, expected_alltime) * 100.0

    print("\n=== NUMERIC DRIFT ASSERTIONS (Tolerance <= 2.0%) ===")
    print(f"Today drift:   {drift_today:.4f}% (expected {expected_today:,d} vs actual {actual_today:,d})")
    print(f"Alltime drift: {drift_alltime:.4f}% (expected {expected_alltime:,d} vs actual {actual_alltime:,d})")

    assert drift_today <= 2.0, f"Today drift {drift_today}% exceeds 2.0% threshold"
    assert drift_alltime <= 2.0, f"Alltime drift {drift_alltime}% exceeds 2.0% threshold"

    print("\n[PASS] Home token metrics match insights engine all-sources billable definition!")

if __name__ == "__main__":
    main()
