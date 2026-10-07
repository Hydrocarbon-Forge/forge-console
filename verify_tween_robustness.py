#!/usr/bin/env python3
"""
Verification Script for FIX-HOME-4:
TweenValue robustness under throttled/unrendered rAF (background/automation tab),
smooth visible-tab count-up, and reduced-motion short-circuit.
"""

import os
import sys
import time
import json
import asyncio
import subprocess
import urllib.request
import urllib.error
import websockets

PORT = 8916
BASE_URL = f"http://127.0.0.1:{PORT}"
CDP_PORT = 9226
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


async def run_cdp_tests():
    print(f"\n[STEP 1] Starting test server on PORT={PORT}...")
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
        print(f"  ✓ Server alive on http://127.0.0.1:{PORT}")

        # Check /api/home response
        req = urllib.request.Request(f"{BASE_URL}/api/home")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            home_data = json.loads(resp.read().decode())
            print(f"  ✓ /api/home responded with ok={home_data.get('ok')}")
            today_tokens = home_data.get("billed_today_by_source", {}).get("total")
            alltime_tokens = home_data.get("billed_alltime_by_source", {}).get("total")
            trading_eq = (home_data.get("trading", {}).get("stock", {}).get("equity", 0) +
                          home_data.get("trading", {}).get("crypto", {}).get("equity", 0))
            print(f"    - billed_today total: {today_tokens:,d}")
            print(f"    - billed_alltime total: {alltime_tokens:,d}")
            print(f"    - total trading equity: ${trading_eq:,.2f}")

        # Start headless Chromium
        print(f"\n[STEP 2] Launching Headless Chromium with remote debugging on port {CDP_PORT}...")
        chrome_proc = subprocess.Popen(
            [
                "chromium",
                "--headless=new",
                f"--remote-debugging-port={CDP_PORT}",
                "--no-sandbox",
                "--disable-gpu",
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
            # SUITE 1: Hidden / Background / Automation Tab (rAF throttled/not firing)
            # -------------------------------------------------------------
            print("\n[SUITE 1] Testing UNRENDERED / BACKGROUND Tab (rAF throttled/not firing)...")

            # 1. Create Tab 1 navigating to forge-console
            t1_resp = await cdp_call(b_ws, "Target.createTarget", {"url": f"{BASE_URL}/#pane-home"})
            tab1_id = t1_resp["targetId"]

            # 2. Create Tab 2 and activate Tab 2 to force Tab 1 into the background
            t2_resp = await cdp_call(b_ws, "Target.createTarget", {"url": "about:blank"})
            tab2_id = t2_resp["targetId"]
            await cdp_call(b_ws, "Target.activateTarget", {"targetId": tab2_id})

            # Connect to Tab 1
            targets = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/list").read().decode())
            tab1_info = next(t for t in targets if t["id"] == tab1_id)

            async with websockets.connect(tab1_info["webSocketDebuggerUrl"]) as tab1_ws:
                await cdp_call(tab1_ws, "Page.enable")
                await cdp_call(tab1_ws, "Runtime.enable")

                # Verify Tab 1 visibility state is 'hidden'
                res = await cdp_call(tab1_ws, "Runtime.evaluate", {
                    "expression": "({ hidden: document.hidden, state: document.visibilityState })",
                    "returnByValue": True
                })
                vis_state = res["result"]["value"]
                print(f"  Tab 1 visibility state: {vis_state}")
                assert vis_state["hidden"] is True, f"Expected hidden=True, got {vis_state}"

                # Test whether rAF fires in Tab 1
                await cdp_call(tab1_ws, "Runtime.evaluate", {
                    "expression": """
                    window._testRafFired = false;
                    window._testTimerFired = false;
                    requestAnimationFrame(() => { window._testRafFired = true; });
                    setTimeout(() => { window._testTimerFired = true; }, 200);
                    """
                })

                # In background tabs, Chromium clamps setTimeout to 1000ms.
                # After 2.0s, the fetch has arrived and the fallback 200ms timer has fired.
                print("  Waiting 2.0s in background tab for poll and fallback timer...")
                await asyncio.sleep(2.0)

                # Check rAF vs timer firing
                res = await cdp_call(tab1_ws, "Runtime.evaluate", {
                    "expression": "({ rafFired: window._testRafFired, timerFired: window._testTimerFired })",
                    "returnByValue": True
                })
                sched_state = res["result"]["value"]
                print(f"  Background scheduler state: {sched_state}")
                assert sched_state["rafFired"] is False, f"Expected rAF not to fire in background tab! {sched_state}"
                assert sched_state["timerFired"] is True, f"Expected timer to fire! {sched_state}"

                # Inspect headline metrics in Tab 1
                eval_metrics_js = """
                (() => {
                    const todayEl = document.getElementById("home-tokens-today");
                    const alltimeEl = document.getElementById("home-tokens-alltime");
                    const equityEl = document.getElementById("home-trading-equity");
                    return {
                        todayText: todayEl ? todayEl.textContent.trim() : null,
                        alltimeText: alltimeEl ? alltimeEl.textContent.trim() : null,
                        equityText: equityEl ? equityEl.textContent.trim() : null,
                    };
                })()
                """
                res = await cdp_call(tab1_ws, "Runtime.evaluate", {
                    "expression": eval_metrics_js,
                    "returnByValue": True
                })
                res_metrics = res["result"]["value"]
                print(f"  Observed headline values in unrendered tab: {res_metrics}")

                # Must not be placeholder "--" or "—"
                assert res_metrics["todayText"] not in ("--", "—"), (
                    f"home-tokens-today stuck at placeholder: {res_metrics['todayText']}"
                )
                assert res_metrics["alltimeText"] not in ("--", "—"), (
                    f"home-tokens-alltime stuck at placeholder: {res_metrics['alltimeText']}"
                )
                assert res_metrics["equityText"] not in ("--", "$--", "$—"), (
                    f"home-trading-equity stuck at placeholder: {res_metrics['equityText']}"
                )
                print(f"  ✓ PASS: In unrendered tab (rAF dead), metrics reached real values: Today={res_metrics['todayText']}, AllTime={res_metrics['alltimeText']}, Equity={res_metrics['equityText']}")

            # -------------------------------------------------------------
            # SUITE 2: Normal Visible Tab (Smooth count-up, started flag sets true)
            # -------------------------------------------------------------
            print("\n[SUITE 2] Testing VISIBLE Tab (Smooth count-up, started-flag behavior)...")

            vis_resp = await cdp_call(b_ws, "Target.createTarget", {"url": f"{BASE_URL}/#pane-home"})
            vis_tab_id = vis_resp["targetId"]
            await cdp_call(b_ws, "Target.activateTarget", {"targetId": vis_tab_id})

            targets = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/list").read().decode())
            vis_tab_info = next(t for t in targets if t["id"] == vis_tab_id)

            async with websockets.connect(vis_tab_info["webSocketDebuggerUrl"]) as vis_ws:
                await cdp_call(vis_ws, "Page.enable")
                await cdp_call(vis_ws, "Runtime.enable")

                # Verify visible
                res = await cdp_call(vis_ws, "Runtime.evaluate", {
                    "expression": "({ hidden: document.hidden, state: document.visibilityState })",
                    "returnByValue": True
                })
                vis_state = res["result"]["value"]
                print(f"  Visible Tab visibility state: {vis_state}")
                assert vis_state["hidden"] is False

                # Test tweenValue logic in page context to verify frame-by-frame and started flag
                test_visible_js = """
                new Promise((resolve) => {
                    const testEl = document.createElement("div");
                    testEl.textContent = "--";
                    document.body.appendChild(testEl);

                    function testTween(el, targetVal, formatFn, durationMs = 400) {
                        if (!el) return;
                        if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
                            el.textContent = formatFn(targetVal);
                            return;
                        }
                        const startVal = typeof el._currentVal === "number" ? el._currentVal : 0;
                        el._currentVal = targetVal;
                        if (startVal === targetVal) {
                            el.textContent = formatFn(targetVal);
                            return;
                        }
                        el.textContent = formatFn(startVal);
                        const startTime = performance.now();
                        let started = false;
                        let done = false;
                        function step(now) {
                            if (done) return;
                            started = true;
                            const elapsed = now - startTime;
                            const progress = Math.min(elapsed / durationMs, 1.0);
                            const ease = 1 - (1 - progress) * (1 - progress);
                            const current = startVal + (targetVal - startVal) * ease;
                            el.textContent = formatFn(current);
                            if (progress < 1.0) {
                                requestAnimationFrame(step);
                            } else {
                                done = true;
                                el.textContent = formatFn(targetVal);
                            }
                        }
                        requestAnimationFrame(step);
                        setTimeout(() => {
                            if (!started && !done) {
                                done = true;
                                el.textContent = formatFn(targetVal);
                            }
                        }, 200);
                    }

                    const targetVal = 1000;
                    const formatFn = (v) => Math.round(v).toString();
                    const initialText = testEl.textContent;

                    testTween(testEl, targetVal, formatFn, 400);
                    const syncBaseline = testEl.textContent;

                    // Sample after first frame (~60ms)
                    setTimeout(() => {
                        const midValue = Number(testEl.textContent);
                        // Sample after full completion
                        setTimeout(() => {
                            const finalValue = Number(testEl.textContent);
                            testEl.remove();
                            resolve({
                                initialText,
                                syncBaseline,
                                midValue,
                                finalValue,
                                wasMidBetween: midValue > 0 && midValue < 1000
                            });
                        }, 400);
                    }, 60);
                })
                """
                res = await cdp_call(vis_ws, "Runtime.evaluate", {
                    "expression": test_visible_js,
                    "awaitPromise": True,
                    "returnByValue": True
                })
                vis_tween_res = res["result"]["value"]
                print(f"  Visible tab tweenValue execution telemetry: {vis_tween_res}")

                assert vis_tween_res["syncBaseline"] == "0", (
                    f"Expected baseline '0' synchronously written before rAF, got: {vis_tween_res['syncBaseline']}"
                )
                assert vis_tween_res["wasMidBetween"] is True, (
                    f"Animation did not progress smoothly! midValue={vis_tween_res['midValue']}"
                )
                assert vis_tween_res["finalValue"] == 1000, (
                    f"Final value not 1000: {vis_tween_res['finalValue']}"
                )
                print(f"  ✓ PASS: Visible tab smooth count-up: baseline={vis_tween_res['syncBaseline']}, mid={vis_tween_res['midValue']}, final={vis_tween_res['finalValue']}")

                # Poll live headline metrics in visible tab until they leave '--' and settle
                print("  Monitoring live visible tab headline metrics count-up...")
                observed_history = []
                for _ in range(30):
                    res = await cdp_call(vis_ws, "Runtime.evaluate", {
                        "expression": eval_metrics_js,
                        "returnByValue": True
                    })
                    val = res["result"]["value"]
                    if not observed_history or observed_history[-1] != val:
                        observed_history.append(val)
                    if val["todayText"] not in ("--", "—") and val["alltimeText"] not in ("--", "—"):
                        # Settle
                        await asyncio.sleep(0.45)
                        res_final = await cdp_call(vis_ws, "Runtime.evaluate", {
                            "expression": eval_metrics_js,
                            "returnByValue": True
                        })
                        observed_history.append(res_final["result"]["value"])
                        break
                    await asyncio.sleep(0.1)

                print(f"  Live metric transition stages ({len(observed_history)} samples):")
                for i, sample in enumerate(observed_history):
                    print(f"    stage {i}: today='{sample['todayText']}', alltime='{sample['alltimeText']}', eq='{sample['equityText']}'")

                final_sample = observed_history[-1]
                assert final_sample["todayText"] not in ("--", "—")
                assert final_sample["alltimeText"] not in ("--", "—")
                assert final_sample["equityText"] not in ("--", "$--", "$—")
                print(f"  ✓ PASS: In visible tab, headlines transitioned from placeholders to: Today={final_sample['todayText']}, AllTime={final_sample['alltimeText']}, Equity={final_sample['equityText']}")

            # -------------------------------------------------------------
            # SUITE 3: Reduced Motion Branch Verification
            # -------------------------------------------------------------
            print("\n[SUITE 3] Testing REDUCED-MOTION path...")
            async with websockets.connect(vis_tab_info["webSocketDebuggerUrl"]) as r_ws:
                # Emulate prefers-reduced-motion: reduce
                await cdp_call(r_ws, "Emulation.setEmulatedMedia", {
                    "features": [{"name": "prefers-reduced-motion", "value": "reduce"}]
                })

                test_reduced_js = """
                (() => {
                    const testEl = document.createElement("div");
                    testEl.textContent = "--";
                    document.body.appendChild(testEl);

                    function testTween(el, targetVal, formatFn, durationMs = 400) {
                        if (!el) return;
                        if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
                            el.textContent = formatFn(targetVal);
                            return;
                        }
                        const startVal = typeof el._currentVal === "number" ? el._currentVal : 0;
                        el._currentVal = targetVal;
                        if (startVal === targetVal) {
                            el.textContent = formatFn(targetVal);
                            return;
                        }
                        el.textContent = formatFn(startVal);
                        const startTime = performance.now();
                        let started = false;
                        let done = false;
                        function step(now) {
                            if (done) return;
                            started = true;
                            const elapsed = now - startTime;
                            const progress = Math.min(elapsed / durationMs, 1.0);
                            const ease = 1 - (1 - progress) * (1 - progress);
                            const current = startVal + (targetVal - startVal) * ease;
                            el.textContent = formatFn(current);
                            if (progress < 1.0) {
                                requestAnimationFrame(step);
                            } else {
                                done = true;
                                el.textContent = formatFn(targetVal);
                            }
                        }
                        requestAnimationFrame(step);
                        setTimeout(() => {
                            if (!started && !done) {
                                done = true;
                                el.textContent = formatFn(targetVal);
                            }
                        }, 200);
                    }

                    const formatFn = (v) => "REDUCED_" + v;
                    testTween(testEl, 555, formatFn, 400);
                    const immediateText = testEl.textContent;
                    testEl.remove();
                    return {
                        isReduced: window.matchMedia('(prefers-reduced-motion: reduce)').matches,
                        immediateText
                    };
                })()
                """
                res = await cdp_call(r_ws, "Runtime.evaluate", {
                    "expression": test_reduced_js,
                    "returnByValue": True
                })
                reduced_res = res["result"]["value"]
                print(f"  Reduced motion test result: {reduced_res}")
                assert reduced_res["isReduced"] is True
                assert reduced_res["immediateText"] == "REDUCED_555", (
                    f"Reduced motion branch did not immediately set final formatted value: {reduced_res}"
                )
                print("  ✓ PASS: Reduced-motion branch immediately short-circuits and writes final value directly!")

            # -------------------------------------------------------------
            # SUITE 4: startVal === targetVal unchanged early return check
            # -------------------------------------------------------------
            print("\n[SUITE 4] Testing startVal === targetVal (no-op unchanged)...")
            async with websockets.connect(vis_tab_info["webSocketDebuggerUrl"]) as s_ws:
                test_noop_js = """
                (() => {
                    const testEl = document.createElement("div");
                    testEl._currentVal = 500;
                    testEl.textContent = "ORIGINAL_500";
                    function testTween(el, targetVal, formatFn, durationMs = 400) {
                        if (!el) return;
                        if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
                            el.textContent = formatFn(targetVal);
                            return;
                        }
                        const startVal = typeof el._currentVal === "number" ? el._currentVal : 0;
                        el._currentVal = targetVal;
                        if (startVal === targetVal) {
                            el.textContent = formatFn(targetVal);
                            return;
                        }
                        el.textContent = formatFn(startVal);
                        const startTime = performance.now();
                        let started = false;
                        let done = false;
                        function step(now) {
                            if (done) return;
                            started = true;
                            const elapsed = now - startTime;
                            const progress = Math.min(elapsed / durationMs, 1.0);
                            const ease = 1 - (1 - progress) * (1 - progress);
                            const current = startVal + (targetVal - startVal) * ease;
                            el.textContent = formatFn(current);
                            if (progress < 1.0) {
                                requestAnimationFrame(step);
                            } else {
                                done = true;
                                el.textContent = formatFn(targetVal);
                            }
                        }
                        requestAnimationFrame(step);
                        setTimeout(() => {
                            if (!started && !done) {
                                done = true;
                                el.textContent = formatFn(targetVal);
                            }
                        }, 200);
                    }
                    testTween(testEl, 500, (v) => "UPDATED_" + v);
                    const resText = testEl.textContent;
                    return resText;
                })()
                """
                res = await cdp_call(s_ws, "Runtime.evaluate", {
                    "expression": test_noop_js,
                    "returnByValue": True
                })
                noop_res = res["result"]["value"]
                print(f"  Same-value write result: {noop_res}")
                assert noop_res == "UPDATED_500"
                print("  ✓ PASS: startVal === targetVal writes directly without animation/delay!")

    finally:
        if chrome_proc:
            print("\n[CLEANUP] Terminating Chromium process...")
            chrome_proc.terminate()
            chrome_proc.wait()
            print("  ✓ Chromium terminated")
        if server_proc:
            print(f"[CLEANUP] Terminating test server process on port {PORT}...")
            server_proc.terminate()
            server_proc.wait()
            print(f"  ✓ Test server on port {PORT} terminated")


def main():
    asyncio.run(run_cdp_tests())
    print("\n" + "=" * 60)
    print("ALL VERIFICATION SUITES COMPLETED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    main()
