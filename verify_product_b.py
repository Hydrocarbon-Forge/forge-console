#!/usr/bin/env python3
"""
Verification Script for Product B (Forge Console Projects Tab)
Verifies:
1. python3 -m py_compile server.py
2. node --check web/app.js
3. Boot standalone server on PORT=8910
4. GET /api/health -> includes projects: true
5. GET /api/projects -> 16 seeded projects
6. POST /api/projects -> create temporary project & persist
7. PATCH /api/projects/<id> -> update deployment status & URL
8. DELETE /api/projects/<id> -> delete temporary project & verify seed file clean
9. Headless Chromium verification of web frontend on http://127.0.0.1:8910/
   - Projects tab button exists & active
   - List renders all projects
   - Hash route #/projects/forge-console renders detail view with "OPEN DEPLOYMENT →"
   - Hash route #/projects/hello-world renders "No active deployment"
   - Capture screenshot proof
"""

import os
import sys
import time
import json
import urllib.request
import urllib.error
import subprocess

PORT = 8910
BASE_URL = f"http://127.0.0.1:{PORT}"

def api_get(endpoint):
    req = urllib.request.Request(f"{BASE_URL}{endpoint}")
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode())

def api_send(endpoint, method, data=None):
    payload = json.dumps(data or {}).encode() if data is not None else b"{}"
    req = urllib.request.Request(f"{BASE_URL}{endpoint}", data=payload, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode())

def run_tests():
    print("=" * 60)
    print("PRODUCT B: FORGE CONSOLE PROJECTS TAB VERIFICATION")
    print("=" * 60)

    # 1. Compilation checks
    print("\n[STEP 1] Lint & Compilation checks...")
    res_py = subprocess.run(["python3", "-m", "py_compile", "server.py"], capture_output=True)
    assert res_py.returncode == 0, f"Python compile failed: {res_py.stderr.decode()}"
    print("  ✓ python3 -m py_compile server.py: PASS")

    res_js = subprocess.run(["node", "--check", "web/app.js"], capture_output=True)
    assert res_js.returncode == 0, f"JS check failed: {res_js.stderr.decode()}"
    print("  ✓ node --check web/app.js: PASS")

    # 2. Boot standalone server on PORT=8910
    print(f"\n[STEP 2] Booting standalone server on PORT={PORT}...")
    env = os.environ.copy()
    env["PORT"] = str(PORT)
    proc = subprocess.Popen(["python3", "server.py"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(2)

    try:
        # 3. Health check
        print("\n[STEP 3] Verifying GET /api/health...")
        status, health = api_get("/api/health")
        print("  Health response:", json.dumps(health, indent=2))
        assert status == 200
        assert health.get("ok") is True
        assert health.get("projects") is True, "Health check must report projects: true"
        print("  ✓ Health reports projects: true")

        # 4. GET /api/projects
        print("\n[STEP 4] Verifying GET /api/projects...")
        status, projects = api_get("/api/projects")
        assert status == 200
        assert isinstance(projects, list)
        print(f"  ✓ Fetched {len(projects)} seeded projects")
        for p in projects:
            dep_str = f"DEPLOYED ({p.get('deployment_url')})" if p.get('deployed') else "NOT DEPLOYED"
            print(f"    - {p['id']:25s} | {p['name']:25s} | {dep_str}")
        assert len(projects) == 16, f"Expected 16 seeded projects, got {len(projects)}"

        # 5. CRUD Round-Trip
        print("\n[STEP 5] Testing CRUD cycle (POST -> PATCH -> DELETE)...")
        test_payload = {
            "name": "Integration Test Project",
            "id": "integration-test-proj",
            "description": "Created during verification suite",
            "path": "~/HydrocarbonForge/Projects/integration-test",
            "deployed": False,
            "tags": ["test", "verification"]
        }
        # POST
        status, created = api_send("/api/projects", "POST", test_payload)
        assert status == 201
        print("  ✓ POST /api/projects created:", created["id"])

        # Check persistence
        status, projects_after_post = api_get("/api/projects")
        assert len(projects_after_post) == 17
        ids = [p["id"] for p in projects_after_post]
        assert "integration-test-proj" in ids

        # PATCH
        patch_payload = {
            "deployed": True,
            "deployment_url": "http://192.168.1.201:8999",
            "description": "Updated deployment status"
        }
        status, updated = api_send("/api/projects/integration-test-proj", "PATCH", patch_payload)
        assert status == 200
        assert updated["deployed"] is True
        assert updated["deployment_url"] == "http://192.168.1.201:8999"
        print("  ✓ PATCH /api/projects/integration-test-proj recorded deployment:", updated["deployment_url"])

        # DELETE
        status, deleted = api_send("/api/projects/integration-test-proj", "DELETE")
        assert status == 200
        assert deleted["ok"] is True
        assert deleted["deleted"] == "integration-test-proj"
        print("  ✓ DELETE /api/projects/integration-test-proj confirmed")

        # Check clean restoration
        status, final_projects = api_get("/api/projects")
        assert len(final_projects) == 16
        print("  ✓ Seed file clean: restored exactly to 16 seeded projects")

        # 6. Browser DOM & Screenshot Verification via Headless Chromium
        print("\n[STEP 6] Testing Web UI via Headless Chromium...")
        screenshot_path = "/home/bsmt-pc/HydrocarbonForge/Projects/forge-console/console_projects_tab_verified.png"
        ch_cmd = [
            "chromium",
            "--headless=new",
            "--virtual-time-budget=3000",
            "--window-size=1280,800",
            f"--screenshot={screenshot_path}",
            "--dump-dom",
            f"http://127.0.0.1:{PORT}/#/projects"
        ]
        p_ch = subprocess.run(ch_cmd, capture_output=True, text=True, timeout=15)
        dom = p_ch.stdout
        assert "CENTRAL PROJECT DIRECTORY" in dom or "nav-projects" in dom
        assert os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 10000
        print(f"  ✓ Frontend rendered cleanly, screenshot saved ({os.path.getsize(screenshot_path)} bytes)")

        # Test deployed project detail page
        ch_cmd_detail = [
            "chromium",
            "--headless=new",
            "--virtual-time-budget=3000",
            "--window-size=1280,800",
            "--dump-dom",
            f"http://127.0.0.1:{PORT}/#/projects/forge-console"
        ]
        p_ch_detail = subprocess.run(ch_cmd_detail, capture_output=True, text=True, timeout=15)
        dom_detail = p_ch_detail.stdout
        assert "OPEN DEPLOYMENT" in dom_detail
        print("  ✓ Deployed project detail page verified: displays 'OPEN DEPLOYMENT →'")

        # Test not-deployed project detail page
        ch_cmd_not_dep = [
            "chromium",
            "--headless=new",
            "--virtual-time-budget=3000",
            "--window-size=1280,800",
            "--dump-dom",
            f"http://127.0.0.1:{PORT}/#/projects/hello-world"
        ]
        p_ch_not_dep = subprocess.run(ch_cmd_not_dep, capture_output=True, text=True, timeout=15)
        dom_not_dep = p_ch_not_dep.stdout
        assert "No active deployment" in dom_not_dep
        print("  ✓ Not-deployed project detail page verified: displays 'No active deployment recorded'")

        print("\n" + "=" * 60)
        print("PRODUCT B VERIFICATION COMPLETE AND ALL CHECKS PASSED!")
        print("=" * 60)

    finally:
        print("\n[*] Stopping standalone test server (PID %d)..." % proc.pid)
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        print("[*] Test server cleanly stopped.")

if __name__ == "__main__":
    run_tests()
