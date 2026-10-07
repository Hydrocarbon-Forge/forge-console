#!/usr/bin/env python3
"""
Verification Script for FIX-HOME-5:
Deployment-aware OFFICE redirect in forge-console.

Verifies:
1. Local context (http://127.0.0.1:8919/):
   officeUrl() resolves to http://127.0.0.1:8904/
2. Website context (real browser tabs for hydrocarbonforge.com and console.hydrocarbonforge.com):
   officeUrl() resolves to https://office.hydrocarbonforge.com/
3. Regex anchoring and subdomains:
   - hydrocarbonforge.com -> https://office.hydrocarbonforge.com/
   - console.hydrocarbonforge.com -> https://office.hydrocarbonforge.com/
   - office.hydrocarbonforge.com -> https://office.hydrocarbonforge.com/
   - dev.sub.hydrocarbonforge.com -> https://office.hydrocarbonforge.com/
   - HYDROCARBONFORGE.COM -> https://office.hydrocarbonforge.com/
   - notahydrocarbonforge.com -> http://notahydrocarbonforge.com:8904/ (unrelated domain does NOT match)
   - evil-hydrocarbonforge.com -> http://evil-hydrocarbonforge.com:8904/
   - hydrocarbonforge.com.attacker.com -> http://hydrocarbonforge.com.attacker.com:8904/
4. All 5 Office entry points under both Local and Website contexts:
   - Nav tab (#nav-office)
   - Launchpad tile (#launch-office)
   - Treasury card (#card-jump-office)
   - Keyboard shortcut '6'
   - Hash route #/office (and #office)
   All invoke officeUrl() and resolve to identical targets.
5. Codebase scan confirming no leftover hardcoded :8904 in any office path.
6. Clean process lifecycle on fresh test port (8919).
"""

import os
import sys
import re
import time
import json
import asyncio
import subprocess
import urllib.request
import websockets

PORT = 8919
BASE_URL = f"http://127.0.0.1:{PORT}"
CDP_PORT = 9227
_msg_id = 0


def wait_for_server(port, max_wait=10.0):
    start = time.time()
    while time.time() - start < max_wait:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/health")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


async def cdp_call(ws, method, params=None):
    global _msg_id
    _msg_id += 1
    req_id = _msg_id
    payload = {"id": req_id, "method": method}
    if params:
        payload["params"] = params
    await ws.send(json.dumps(payload))
    while True:
        raw = await ws.recv()
        msg = json.loads(raw)
        if msg.get("id") == req_id:
            if "error" in msg:
                raise RuntimeError(f"CDP error for {method}: {msg['error']}")
            return msg.get("result", {})


async def test_tab_entry_points(tab_ws, expected_url):
    eval_script = """
    (() => {
      const intercepted = [];
      window._officeRedirectInterceptor = (url) => {
        intercepted.push(url);
      };

      // 1. Nav Tab (#nav-office)
      document.getElementById("nav-office").click();
      const url1 = intercepted.pop();

      // 2. Launchpad Tile (#launch-office click & Enter)
      const launchTile = document.getElementById("launch-office");
      launchTile.click();
      const url2_click = intercepted.pop();
      launchTile.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
      const url2_enter = intercepted.pop();

      // 3. Treasury Card (#card-jump-office click & Enter)
      const cardOffice = document.getElementById("card-jump-office");
      cardOffice.click();
      const url3_click = intercepted.pop();
      cardOffice.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
      const url3_enter = intercepted.pop();

      // 4. Keyboard Shortcut '6'
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "6", bubbles: true }));
      const url4 = intercepted.pop();

      // 5. Hash Route #/office
      window.location.hash = "#/office";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
      const url5 = intercepted.pop();

      return {
        "1. Nav tab (#nav-office)": url1,
        "2a. Launchpad tile (#launch-office click)": url2_click,
        "2b. Launchpad tile (#launch-office Enter)": url2_enter,
        "3a. Treasury card (#card-jump-office click)": url3_click,
        "3b. Treasury card (#card-jump-office Enter)": url3_enter,
        "4. Keyboard shortcut (key '6')": url4,
        "5. Hash route (#/office)": url5
      };
    })()
    """
    res = await cdp_call(
        tab_ws,
        "Runtime.evaluate",
        {
            "expression": eval_script,
            "returnByValue": True,
            "awaitPromise": True,
        },
    )
    if "exceptionDetails" in res:
        raise RuntimeError(f"Entry points evaluation error: {res['exceptionDetails']}")
    triggers = res.get("result", {}).get("value", {})
    for name, u in triggers.items():
        print(f"    • {name} => {u}")
        assert u == expected_url, f"Trigger '{name}' resolved to '{u}', expected '{expected_url}'"
    return triggers


async def run_verification():
    print("=====================================================================")
    print("  TASK-HOME ROUND 5: DEPLOYMENT-AWARE OFFICE REDIRECT VERIFICATION")
    print("=====================================================================\n")

    # -----------------------------------------------------------------
    # STEP 1: Static Source Code Analysis
    # -----------------------------------------------------------------
    print("[1/5] Performing static source code analysis for office paths...")
    repo_root = os.path.dirname(os.path.abspath(__file__))
    web_dir = os.path.join(repo_root, "web")
    app_js_path = os.path.join(web_dir, "app.js")

    with open(app_js_path, "r", encoding="utf-8") as f:
        app_js_content = f.read()

    # Search for all occurrences of 8904 in web/app.js
    occurrences = [m.start() for m in re.finditer(r":8904", app_js_content)]
    print(f"  • Total ':8904' occurrences in web/app.js: {len(occurrences)}")
    assert len(occurrences) == 1, f"Expected exactly 1 occurrence of ':8904' in web/app.js, found {len(occurrences)}"

    # Confirm it is inside officeUrl()
    office_func_match = re.search(r"function officeUrl\b[\s\S]*?\{[\s\S]*?\n  \}", app_js_content)
    assert office_func_match is not None, "function officeUrl() not found in web/app.js"
    assert ":8904" in office_func_match.group(0), "':8904' must be housed inside officeUrl()"
    print("  ✓ ':8904' is strictly isolated inside officeUrl(). No hardcoded :8904 anywhere else in office paths.")

    # Check other web/ files
    for fname in os.listdir(web_dir):
        if fname == "app.js":
            continue
        fpath = os.path.join(web_dir, fname)
        if os.path.isfile(fpath):
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                assert ":8904" not in content, f"Found ':8904' in {fname}!"
    print("  ✓ Zero ':8904' occurrences across all other files in web/ directory.")

    # -----------------------------------------------------------------
    # STEP 2: Start Server on Port 8919
    # -----------------------------------------------------------------
    print(f"\n[2/5] Starting test server on dedicated PORT={PORT}...")
    server_env = os.environ.copy()
    server_env["PORT"] = str(PORT)
    server_proc = subprocess.Popen(
        [sys.executable, "server.py"],
        env=server_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    chrome_proc = None
    try:
        if not wait_for_server(PORT):
            stdout, stderr = server_proc.communicate(timeout=2)
            raise RuntimeError(f"Server failed to start on port {PORT}. Out: {stdout}, Err: {stderr}")
        print(f"  ✓ Test server live on {BASE_URL}")

        # -----------------------------------------------------------------
        # STEP 3: Launch Headless Chromium with Domain Mapping
        # -----------------------------------------------------------------
        print(f"\n[3/5] Launching Headless Chromium with domain resolver rules on CDP {CDP_PORT}...")
        chrome_proc = subprocess.Popen(
            [
                "chromium",
                "--headless=new",
                f"--remote-debugging-port={CDP_PORT}",
                "--no-sandbox",
                "--disable-gpu",
                "--host-resolver-rules=MAP hydrocarbonforge.com 127.0.0.1, MAP *.hydrocarbonforge.com 127.0.0.1",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1.5)

        v_req = urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/version")
        v_info = json.loads(v_req.read().decode())
        browser_ws_url = v_info["webSocketDebuggerUrl"]
        print(f"  ✓ Chromium CDP connected ({v_info.get('Browser')})")

        async with websockets.connect(browser_ws_url) as b_ws:
            # -------------------------------------------------------------
            # STEP 4: Test Suite A — Local / LAN Context (127.0.0.1)
            # -------------------------------------------------------------
            print(f"\n[4/5] Testing LOCAL / LAN Context (http://127.0.0.1:{PORT}/)...")
            t_local = await cdp_call(b_ws, "Target.createTarget", {"url": f"{BASE_URL}/"})
            t_local_id = t_local["targetId"]

            targets = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/list").read().decode())
            tab_info = next(t for t in targets if t["id"] == t_local_id)

            async with websockets.connect(tab_info["webSocketDebuggerUrl"]) as local_ws:
                await cdp_call(local_ws, "Page.enable")
                await cdp_call(local_ws, "Runtime.enable")
                await asyncio.sleep(1.0)

                eval_host = await cdp_call(local_ws, "Runtime.evaluate", {
                    "expression": "window.location.hostname", "returnByValue": True
                })
                print(f"  • Connected tab hostname: '{eval_host['result']['value']}'")
                assert eval_host['result']['value'] == "127.0.0.1"

                eval_url = await cdp_call(local_ws, "Runtime.evaluate", {
                    "expression": "window.officeUrl()", "returnByValue": True
                })
                local_office_url = eval_url["result"]["value"]
                print(f"  • window.officeUrl() => {local_office_url}")
                assert local_office_url == "http://127.0.0.1:8904/", f"Expected http://127.0.0.1:8904/, got {local_office_url}"
                print("    ✓ [PASS] Local context resolves to http://127.0.0.1:8904/")

                print("  • Verifying all 5 office entry points in Local context:")
                await test_tab_entry_points(local_ws, "http://127.0.0.1:8904/")
                print("    ✓ [PASS] All 5 entry points routed to http://127.0.0.1:8904/")

                # Also test pure function custom host / LAN simulation
                lan_tests = [
                    ("192.168.1.100", "http://192.168.1.100:8904/"),
                    ("forge-box.local", "http://forge-box.local:8904/"),
                    ("10.0.0.22", "http://10.0.0.22:8904/"),
                ]
                for host, expected_lan in lan_tests:
                    res = await cdp_call(local_ws, "Runtime.evaluate", {
                        "expression": f"window.officeUrl('{host}')", "returnByValue": True
                    })
                    val = res["result"]["value"]
                    print(f"  • LAN custom host '{host}' => {val}")
                    assert val == expected_lan, f"Expected {expected_lan}, got {val}"
                print("    ✓ [PASS] LAN custom hosts resolve to http://<host>:8904/")

            # -------------------------------------------------------------
            # STEP 5: Test Suite B — Website Context & Subdomains
            # -------------------------------------------------------------
            print(f"\n[5/5] Testing WEBSITE Context & Subdomains...")

            # Tab B1: Bare Domain hydrocarbonforge.com
            print("  --- Context B1: Bare domain (http://hydrocarbonforge.com:8919/) ---")
            t_bare = await cdp_call(b_ws, "Target.createTarget", {"url": f"http://hydrocarbonforge.com:{PORT}/"})
            t_bare_id = t_bare["targetId"]
            targets = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/list").read().decode())
            tab_bare_info = next(t for t in targets if t["id"] == t_bare_id)

            async with websockets.connect(tab_bare_info["webSocketDebuggerUrl"]) as bare_ws:
                await cdp_call(bare_ws, "Page.enable")
                await cdp_call(bare_ws, "Runtime.enable")
                await asyncio.sleep(1.0)

                eval_host = await cdp_call(bare_ws, "Runtime.evaluate", {
                    "expression": "window.location.hostname", "returnByValue": True
                })
                print(f"  • Tab hostname: '{eval_host['result']['value']}'")
                assert eval_host['result']['value'] == "hydrocarbonforge.com"

                eval_url = await cdp_call(bare_ws, "Runtime.evaluate", {
                    "expression": "window.officeUrl()", "returnByValue": True
                })
                bare_office_url = eval_url["result"]["value"]
                print(f"  • window.officeUrl() => {bare_office_url}")
                assert bare_office_url == "https://office.hydrocarbonforge.com/", f"Expected https://office.hydrocarbonforge.com/, got {bare_office_url}"
                print("    ✓ [PASS] Bare website domain resolves to https://office.hydrocarbonforge.com/")

                print("  • Verifying all 5 office entry points on bare domain:")
                await test_tab_entry_points(bare_ws, "https://office.hydrocarbonforge.com/")
                print("    ✓ [PASS] All 5 entry points routed to https://office.hydrocarbonforge.com/")

            # Tab B2: Subdomain console.hydrocarbonforge.com
            print("\n  --- Context B2: Subdomain (http://console.hydrocarbonforge.com:8919/) ---")
            t_sub = await cdp_call(b_ws, "Target.createTarget", {"url": f"http://console.hydrocarbonforge.com:{PORT}/"})
            t_sub_id = t_sub["targetId"]
            targets = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/list").read().decode())
            tab_sub_info = next(t for t in targets if t["id"] == t_sub_id)

            async with websockets.connect(tab_sub_info["webSocketDebuggerUrl"]) as sub_ws:
                await cdp_call(sub_ws, "Page.enable")
                await cdp_call(sub_ws, "Runtime.enable")
                await asyncio.sleep(1.0)

                eval_host = await cdp_call(sub_ws, "Runtime.evaluate", {
                    "expression": "window.location.hostname", "returnByValue": True
                })
                print(f"  • Tab hostname: '{eval_host['result']['value']}'")
                assert eval_host['result']['value'] == "console.hydrocarbonforge.com"

                eval_url = await cdp_call(sub_ws, "Runtime.evaluate", {
                    "expression": "window.officeUrl()", "returnByValue": True
                })
                sub_office_url = eval_url["result"]["value"]
                print(f"  • window.officeUrl() => {sub_office_url}")
                assert sub_office_url == "https://office.hydrocarbonforge.com/", f"Expected https://office.hydrocarbonforge.com/, got {sub_office_url}"
                print("    ✓ [PASS] Subdomain console.hydrocarbonforge.com resolves to https://office.hydrocarbonforge.com/")

                print("  • Verifying all 5 office entry points on console subdomain:")
                await test_tab_entry_points(sub_ws, "https://office.hydrocarbonforge.com/")
                print("    ✓ [PASS] All 5 entry points routed to https://office.hydrocarbonforge.com/")

                # Extended regex anchoring and subdomain assertions
                print("\n  --- Context B3: Regex Anchoring & Negative Domain Assertions ---")
                suite_assertions = [
                    # Website domains (must resolve to https://office.hydrocarbonforge.com/)
                    ("hydrocarbonforge.com", "https://office.hydrocarbonforge.com/", True),
                    ("console.hydrocarbonforge.com", "https://office.hydrocarbonforge.com/", True),
                    ("office.hydrocarbonforge.com", "https://office.hydrocarbonforge.com/", True),
                    ("dev.sub.hydrocarbonforge.com", "https://office.hydrocarbonforge.com/", True),
                    ("HYDROCARBONFORGE.COM", "https://office.hydrocarbonforge.com/", True),
                    ("CONSOLE.HYDROCARBONFORGE.COM", "https://office.hydrocarbonforge.com/", True),

                    # Anchoring tests: hosts that contain the string but are NOT website subdomains
                    ("notahydrocarbonforge.com", "http://notahydrocarbonforge.com:8904/", False),
                    ("evil-hydrocarbonforge.com", "http://evil-hydrocarbonforge.com:8904/", False),
                    ("hydrocarbonforge.com.attacker.com", "http://hydrocarbonforge.com.attacker.com:8904/", False),
                    ("myhydrocarbonforge.com", "http://myhydrocarbonforge.com:8904/", False),
                ]

                for host, expected_target, is_web in suite_assertions:
                    res = await cdp_call(sub_ws, "Runtime.evaluate", {
                        "expression": f"window.officeUrl('{host}')", "returnByValue": True
                    })
                    val = res["result"]["value"]
                    tag = "[WEBSITE]" if is_web else "[NON-WEBSITE FALLBACK]"
                    print(f"    {tag:22} '{host}' => {val}")
                    assert val == expected_target, f"Host '{host}' failed: expected {expected_target}, got {val}"
                print("    ✓ [PASS] Anchored regex correctly distinguishes website vs non-website domains.")

    finally:
        print("\n[TEARDOWN] Shutting down test infrastructure...")
        if chrome_proc:
            chrome_proc.terminate()
            chrome_proc.wait(timeout=3)
            print("  ✓ Headless Chromium terminated.")
        server_proc.terminate()
        server_proc.wait(timeout=3)
        print(f"  ✓ Test server on port {PORT} terminated.")

    print("\n=====================================================================")
    print("  ALL VERIFICATION TESTS COMPLETED AND ASSERTIONS PASSED (100% OK)")
    print("=====================================================================\n")


if __name__ == "__main__":
    asyncio.run(run_verification())
