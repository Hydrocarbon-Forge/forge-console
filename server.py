#!/usr/bin/env python3
"""
Forge Console - Central Hydrocarbon Forge Control Panel
Stdlib-only HTTP server and reverse proxy on port 8903.
"""

import os
import sys
import time
import json
import threading
import signal
import urllib.request
import urllib.error
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import importlib.util
from concurrent.futures import ThreadPoolExecutor

import collector

PORT = int(os.environ.get("PORT", 8903))
INSIGHTS_PORT = 8901
IDEAS_PORT = 8902

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = os.path.join(str(BASE_DIR), "web")
DATA_DIR = os.path.join(str(BASE_DIR), "data")
LOG_FILE = os.path.join(DATA_DIR, "collector.log")
INSIGHTS_WEB_DIR = os.path.join(str(BASE_DIR), "insights", "web")
IDEAS_SITE_DIR = os.path.join(str(BASE_DIR), "ideas", "site")

# In-memory flow cache
_flow_cache = None
_flow_lock = threading.Lock()

PROJECTS_FILE = os.path.join(DATA_DIR, "projects.json")
_projects_lock = threading.Lock()

OFFICE_TRADING_PATH = Path.home() / "HydrocarbonForge" / "Projects" / "forge-office" / "data" / "trading.json"


def fetch_trading_data():
    """
    Fetches trading stats from forge-office (8904) or falls back to data/trading.json.
    Returns (dict_or_None, error_str_or_None).
    """
    # 1. urllib fetch http://127.0.0.1:8904/data/trading.json (timeout ~1.5s)
    try:
        req = urllib.request.Request("http://127.0.0.1:8904/data/trading.json")
        req.add_header("User-Agent", "ForgeConsole/1.0")
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                body = resp.read()
                return json.loads(body.decode("utf-8")), None
    except Exception:
        pass

    # 2. Fall back to reading ~/HydrocarbonForge/Projects/forge-office/data/trading.json
    try:
        if OFFICE_TRADING_PATH.exists():
            with open(OFFICE_TRADING_PATH, "r", encoding="utf-8") as f:
                return json.load(f), None
    except Exception as e:
        return None, f"Failed reading local trading.json: {e}"

    # 3. Both failed
    return None, "Office trading service unreachable and trading.json not found"


def load_projects_data():
    with _projects_lock:
        if not os.path.exists(PROJECTS_FILE):
            return {"projects": []}
        try:
            with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"projects": []}


def save_projects_data(data):
    with _projects_lock:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp_file = os.path.join(DATA_DIR, f"projects.tmp.{os.getpid()}.{time.time()}")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_file, PROJECTS_FILE)


def log_collector(msg):
    """Appends timestamped message to data/collector.log."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def collector_loop():
    """Background daemon thread: gathers flow data every 5s."""
    global _flow_cache
    log_collector("Collector loop started")
    while True:
        try:
            doc = collector.collect()
            with _flow_lock:
                _flow_cache = doc
        except Exception as e:
            log_collector(f"Collector error: {e}")
        time.sleep(5.0)


INSIGHTS_PROXY_ENDPOINTS = {
    "/api/summary",
    "/api/insights",
    "/api/models",
    "/api/platforms",
    "/api/tools",
    "/api/skills",
    "/api/activity",
    "/api/cost",
    "/api/opencode",
    "/api/claudecode",
    "/api/antigravity",
    "/api/health-insights",
    "/api/pricing",
}

SCHEME_EXACT_ENDPOINTS = {
    "/api/ideas",
    "/api/connections",
    "/api/themes",
    "/api/stats",
    "/api/analysis",
}


_home_tokens_cache = {
    "timestamp": 0.0,
    "data": None,
}
_home_tokens_lock = threading.Lock()
_home_executor = ThreadPoolExecutor(max_workers=9, thread_name_prefix="home_tokens")


def _fetch_insights_json(endpoint):
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{INSIGHTS_PORT}{endpoint}")
        req.add_header("User-Agent", "ForgeConsole/1.0")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode("utf-8"))
    except Exception:
        pass
    return None


def _extract_source_billed(src, doc):
    if doc is None:
        return None
    if src == "c6":
        return doc.get("billed_tokens", 0)
    total = doc.get("total")
    if isinstance(total, dict):
        return int(total.get("input_tokens", 0) or 0) + int(total.get("output_tokens", 0) or 0)
    models = doc.get("models") or []
    return sum(int(m.get("input_tokens", 0) or 0) + int(m.get("output_tokens", 0) or 0) for m in models)


def get_home_tokens_aggregate():
    """
    Fetches token metrics across all 4 harnesses (C6, OpenCode, Claude Code, Antigravity)
    for today (days=1) and all-time (days=all) plus 7d daily series.
    Cached for up to 3.0 seconds to keep repeated/parallel requests fast.
    """
    now = time.time()
    with _home_tokens_lock:
        if _home_tokens_cache["data"] is not None and (now - _home_tokens_cache["timestamp"] < 3.0):
            return _home_tokens_cache["data"]

    endpoints = {
        "c6_1d": "/api/summary?days=1",
        "op_1d": "/api/opencode?days=1",
        "cc_1d": "/api/claudecode?days=1",
        "ag_1d": "/api/antigravity?days=1",
        "c6_all": "/api/summary?days=all",
        "op_all": "/api/opencode?days=all",
        "cc_all": "/api/claudecode?days=all",
        "ag_all": "/api/antigravity?days=all",
        "c6_act7": "/api/activity?days=7",
    }

    keys = list(endpoints.keys())
    futures = _home_executor.map(_fetch_insights_json, [endpoints[k] for k in keys])
    res = dict(zip(keys, futures))

    today_by_src = {
        "c6": _extract_source_billed("c6", res["c6_1d"]),
        "opencode": _extract_source_billed("opencode", res["op_1d"]),
        "claudecode": _extract_source_billed("claudecode", res["cc_1d"]),
        "antigravity": _extract_source_billed("antigravity", res["ag_1d"]),
    }
    today_total = sum(v for v in today_by_src.values() if v is not None)

    alltime_by_src = {
        "c6": _extract_source_billed("c6", res["c6_all"]),
        "opencode": _extract_source_billed("opencode", res["op_all"]),
        "claudecode": _extract_source_billed("claudecode", res["cc_all"]),
        "antigravity": _extract_source_billed("antigravity", res["ag_all"]),
    }
    alltime_total = sum(v for v in alltime_by_src.values() if v is not None)

    daily_billed_map = {}
    for doc, is_c6 in [(res["c6_act7"], True), (res["op_all"], False), (res["cc_all"], False), (res["ag_all"], False)]:
        if not doc:
            continue
        daily = doc.get("daily") or []
        if len(daily) > 7:
            daily = daily[-7:]
        for row in daily:
            dt = row.get("date")
            if not dt:
                continue
            cw = row.get("cache_write_tokens", 0) if is_c6 else 0
            b = int(row.get("input_tokens", 0) or 0) + int(row.get("output_tokens", 0) or 0) + int(cw or 0)
            daily_billed_map[dt] = daily_billed_map.get(dt, 0) + b

    sorted_dates = sorted(daily_billed_map.keys())
    activity_7d = {
        "days": "7",
        "daily": [{"date": dt, "billed_tokens": daily_billed_map[dt]} for dt in sorted_dates],
        "total": sum(daily_billed_map.values()),
    }

    data = {
        "billed_today_by_source": {
            "total": today_total,
            "by_source": today_by_src,
        },
        "billed_alltime_by_source": {
            "total": alltime_total,
            "by_source": alltime_by_src,
        },
        "activity_7d": activity_7d,
        "summary_today": res["c6_1d"],
        "summary_alltime": res["c6_all"],
    }

    with _home_tokens_lock:
        _home_tokens_cache["timestamp"] = time.time()
        _home_tokens_cache["data"] = data

    return data


class ForgeConsoleHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        # Suppress routine logging to keep console clean, or log to debug
        pass

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = parsed.query

        # 1. /api/health (console own)
        if path == "/api/health":
            self.handle_health()
            return

        # 2. /api/flow (console own)
        if path == "/api/flow":
            self.handle_flow()
            return

        # 2b. /api/projects (console own)
        if path == "/api/projects":
            self.handle_get_projects()
            return

        if path.startswith("/api/projects/"):
            proj_id = path[len("/api/projects/"):].strip("/")
            self.handle_get_project_detail(proj_id)
            return

        # 2c. /api/trading (console own: office trading stats)
        if path == "/api/trading":
            self.handle_trading()
            return

        # 2d. /api/home (console own: aggregated home payload)
        if path == "/api/home":
            self.handle_home()
            return

        # 3. Existing proxy routes (backward compat)
        if path.startswith("/api/proxy/insights"):
            self.handle_proxy_insights(path, query)
            return

        if path.startswith("/api/proxy/scheme"):
            self.handle_proxy_scheme(path, query, method="GET")
            return

        # 4. Transparent routes to 8901 (insights-board)
        if path in INSIGHTS_PROXY_ENDPOINTS:
            target_path = "/api/health" if path == "/api/health-insights" else path
            upstream_url = f"http://127.0.0.1:8901{target_path}" + (f"?{query}" if query else "")
            self.forward_http(upstream_url, method="GET", upstream_name="insights")
            return

        # 5. Transparent routes to 8902 (scheme-board)
        if path in SCHEME_EXACT_ENDPOINTS or path.startswith("/api/ideas/"):
            upstream_url = f"http://127.0.0.1:8902{path}" + (f"?{query}" if query else "")
            self.forward_http(upstream_url, method="GET", upstream_name="scheme")
            return

        # 6. Static files
        self.handle_static(path, query=query)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = parsed.query

        if path == "/api/projects":
            self.handle_post_project()
            return

        if path.startswith("/api/proxy/scheme"):
            self.handle_proxy_scheme(path, query, method="POST")
            return

        if path.startswith("/api/proxy/insights"):
            self.handle_proxy_insights(path, query, method="POST")
            return

        # Transparent route to 8901 (pricing)
        if path == "/api/pricing":
            upstream_url = f"http://127.0.0.1:8901/api/pricing" + (f"?{query}" if query else "")
            self.forward_http(upstream_url, method="POST", upstream_name="insights")
            return

        # Transparent route to 8902 (ideas)
        if path == "/api/ideas" or path.startswith("/api/ideas/"):
            upstream_url = f"http://127.0.0.1:8902{path}" + (f"?{query}" if query else "")
            self.forward_http(upstream_url, method="POST", upstream_name="scheme")
            return

        self.send_error_json(404, "Not Found")

    def do_PATCH(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = parsed.query

        if path.startswith("/api/projects/"):
            proj_id = path[len("/api/projects/"):].strip("/")
            self.handle_patch_project(proj_id)
            return

        if path.startswith("/api/proxy/scheme"):
            self.handle_proxy_scheme(path, query, method="PATCH")
            return

        if path == "/api/ideas" or path.startswith("/api/ideas/"):
            upstream_url = f"http://127.0.0.1:8902{path}" + (f"?{query}" if query else "")
            self.forward_http(upstream_url, method="PATCH", upstream_name="scheme")
            return

        self.send_error_json(404, "Not Found")

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = parsed.query

        if path.startswith("/api/projects/"):
            proj_id = path[len("/api/projects/"):].strip("/")
            self.handle_delete_project(proj_id)
            return

        if path.startswith("/api/proxy/scheme"):
            self.handle_proxy_scheme(path, query, method="DELETE")
            return

        if path == "/api/ideas" or path.startswith("/api/ideas/"):
            upstream_url = f"http://127.0.0.1:8902{path}" + (f"?{query}" if query else "")
            self.forward_http(upstream_url, method="DELETE", upstream_name="scheme")
            return

        self.send_error_json(404, "Not Found")

    def handle_health(self):
        """Returns {ok, port, services:[...], projects:bool}."""
        with _flow_lock:
            cached = _flow_cache
        services_list = cached.get("services", []) if cached else []
        projects_ok = False
        try:
            pdata = load_projects_data()
            projects_ok = isinstance(pdata.get("projects"), list)
        except Exception:
            projects_ok = False

        body = json.dumps({
            "ok": True,
            "port": PORT,
            "services": services_list,
            "projects": projects_ok
        }).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def handle_flow(self):
        """Returns cached flow doc or structured fallback."""
        with _flow_lock:
            doc = _flow_cache

        if doc is None:
            # Fallback if first collector tick hasn't finished
            doc = {
                "stale": True,
                "harnesses": [],
                "filesystem": {"recent": []},
                "projects": [],
                "services": [],
                "databases": [],
                "generated_at": time.time()
            }

        body = json.dumps(doc).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def handle_get_projects(self):
        """Returns array of projects from data/projects.json."""
        pdata = load_projects_data()
        projects_list = pdata.get("projects", [])
        body = json.dumps(projects_list, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def handle_get_project_detail(self, proj_id):
        """Returns single project by id."""
        pdata = load_projects_data()
        for p in pdata.get("projects", []):
            if p.get("id") == proj_id:
                body = json.dumps(p, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(body)
                return
        self.send_error_json(404, f"Project '{proj_id}' not found")

    def handle_trading(self):
        """Returns forge-office trading.json data with 502 fallback."""
        data, err = fetch_trading_data()
        if data is None:
            self.send_upstream_down_json(502, err or "Trading upstream unavailable", "office")
            return

        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)



    def handle_home(self):
        """Returns consolidated home dashboard payload with all-sources billable tokens."""
        with _flow_lock:
            cached_flow = _flow_cache or {}

        trading_data, _ = fetch_trading_data()

        # Scheme stats (ideas count)
        ideas_count = 0
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{IDEAS_PORT}/api/stats")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status == 200:
                    stats_doc = json.loads(resp.read().decode("utf-8"))
                    counts = stats_doc.get("counts") if isinstance(stats_doc.get("counts"), dict) else {}
                    ideas_count = counts.get("total", stats_doc.get("total_ideas", stats_doc.get("ideas_count", 0)))
        except Exception:
            pass

        tokens_data = get_home_tokens_aggregate()

        payload = {
            "ok": True,
            "billed_today_by_source": tokens_data["billed_today_by_source"],
            "billed_alltime_by_source": tokens_data["billed_alltime_by_source"],
            "summary_today": tokens_data["summary_today"],
            "summary_alltime": tokens_data["summary_alltime"],
            "activity_7d": tokens_data["activity_7d"],
            "flow": {
                "harnesses": cached_flow.get("harnesses", []),
                "projects": cached_flow.get("projects", []),
                "services": cached_flow.get("services", []),
            },
            "trading": trading_data,
            "ideas_count": ideas_count,
            "projects_count": len(cached_flow.get("projects", [])),
            "generated_at": time.time(),
        }

        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def handle_post_project(self):
        """Creates a new project in data/projects.json."""
        try:
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len == 0:
                self.send_error_json(400, "Missing request body")
                return
            body_bytes = self.rfile.read(content_len)
            payload = json.loads(body_bytes.decode("utf-8"))
        except Exception as e:
            self.send_error_json(400, f"Malformed JSON: {e}")
            return

        if not isinstance(payload, dict):
            self.send_error_json(400, "Request body must be a JSON object")
            return

        name = payload.get("name", "").strip()
        if not name:
            self.send_error_json(400, "Field 'name' is required")
            return

        import re
        raw_id = payload.get("id", "").strip().lower()
        if not raw_id:
            raw_id = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-")

        if not re.match(r"^[a-z0-9_-]+$", raw_id):
            self.send_error_json(400, "Field 'id' must consist only of lowercase letters, digits, '-', or '_'")
            return

        dep_url = payload.get("deployment_url")
        if dep_url:
            dep_url = dep_url.strip()
            if not (dep_url.startswith("http://") or dep_url.startswith("https://")):
                self.send_error_json(400, "Field 'deployment_url' must be a valid http:// or https:// URL")
                return

        pdata = load_projects_data()
        projects = pdata.get("projects", [])
        for p in projects:
            if p.get("id") == raw_id:
                self.send_error_json(400, f"Project with id '{raw_id}' already exists")
                return

        new_project = {
            "id": raw_id,
            "name": name,
            "path": payload.get("path", f"~/HydrocarbonForge/Projects/{raw_id}").strip(),
            "description": payload.get("description", "").strip(),
            "deployed": bool(payload.get("deployed", False)),
            "tags": payload.get("tags", []),
            "updated": payload.get("updated", time.strftime("%Y-%m-%d"))
        }
        if payload.get("service"):
            new_project["service"] = payload["service"].strip()
        if dep_url and new_project["deployed"]:
            new_project["deployment_url"] = dep_url

        projects.append(new_project)
        pdata["projects"] = projects
        save_projects_data(pdata)

        body = json.dumps(new_project, indent=2).encode("utf-8")
        self.send_response(201)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def handle_patch_project(self, proj_id):
        """Updates project in data/projects.json."""
        try:
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len == 0:
                self.send_error_json(400, "Missing request body")
                return
            body_bytes = self.rfile.read(content_len)
            payload = json.loads(body_bytes.decode("utf-8"))
        except Exception as e:
            self.send_error_json(400, f"Malformed JSON: {e}")
            return

        if not isinstance(payload, dict):
            self.send_error_json(400, "Request body must be a JSON object")
            return

        if "deployment_url" in payload and payload["deployment_url"]:
            dep_url = str(payload["deployment_url"]).strip()
            if not (dep_url.startswith("http://") or dep_url.startswith("https://")):
                self.send_error_json(400, "Field 'deployment_url' must be a valid http:// or https:// URL")
                return

        pdata = load_projects_data()
        projects = pdata.get("projects", [])
        target = None
        for p in projects:
            if p.get("id") == proj_id:
                target = p
                break

        if not target:
            self.send_error_json(404, f"Project '{proj_id}' not found")
            return

        for field in ("name", "description", "path", "service", "tags", "deployed", "deployment_url"):
            if field in payload:
                target[field] = payload[field]

        if target.get("deployed") is False and "deployment_url" in target:
            del target["deployment_url"]

        if "updated" in payload:
            target["updated"] = str(payload["updated"])
        else:
            target["updated"] = time.strftime("%Y-%m-%d")

        pdata["projects"] = projects
        save_projects_data(pdata)

        body = json.dumps(target, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def handle_delete_project(self, proj_id):
        """Deletes a project from data/projects.json."""
        pdata = load_projects_data()
        projects = pdata.get("projects", [])
        found_idx = None
        for idx, p in enumerate(projects):
            if p.get("id") == proj_id:
                found_idx = idx
                break

        if found_idx is None:
            self.send_error_json(404, f"Project '{proj_id}' not found")
            return

        deleted_project = projects.pop(found_idx)
        pdata["projects"] = projects
        save_projects_data(pdata)

        body = json.dumps({"ok": True, "deleted": proj_id, "project": deleted_project}, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def handle_proxy_insights(self, path, query, method="GET"):
        """Proxies requests to insights-board on port 8901."""
        prefix = "/api/proxy/insights"
        subpath = path[len(prefix):].lstrip("/")
        if not subpath:
            subpath = "summary"

        # Ensure upstream path format: http://127.0.0.1:8901/api/{endpoint}
        if not subpath.startswith("api/"):
            target_path = f"/api/{subpath}"
        else:
            target_path = f"/{subpath}"

        upstream_url = f"http://127.0.0.1:8901{target_path}"
        if query:
            upstream_url += f"?{query}"

        self.forward_http(upstream_url, method=method, upstream_name="insights")

    def handle_proxy_scheme(self, path, query, method="GET"):
        """Proxies requests to scheme-board on port 8902."""
        prefix = "/api/proxy/scheme"
        subpath = path[len(prefix):].lstrip("/")
        if not subpath:
            subpath = "api/stats"

        # Ensure upstream path format: http://127.0.0.1:8902/{subpath}
        if not subpath.startswith("api/"):
            target_path = f"/api/{subpath}"
        else:
            target_path = f"/{subpath}"

        upstream_url = f"http://127.0.0.1:8902{target_path}"
        if query:
            upstream_url += f"?{query}"

        self.forward_http(upstream_url, method=method, upstream_name="scheme")

    def forward_http(self, upstream_url, method="GET", upstream_name="upstream"):
        """Forwards HTTP request and streams response back with 502 error handling."""
        body_data = None
        if method in ("POST", "PATCH", "PUT", "DELETE"):
            try:
                content_len = int(self.headers.get("Content-Length", 0))
                if content_len > 0:
                    body_data = self.rfile.read(content_len)
            except Exception as e:
                self.send_error_json(400, f"Error reading body: {e}")
                return

        req = urllib.request.Request(upstream_url, data=body_data, method=method)
        req.add_header("User-Agent", "ForgeConsoleProxy/1.0")
        if self.headers.get("Content-Type"):
            req.add_header("Content-Type", self.headers.get("Content-Type"))

        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                resp_body = resp.read()
                resp_status = resp.status
                resp_content_type = resp.headers.get("Content-Type", "application/json; charset=utf-8")

                self.send_response(resp_status)
                if resp_content_type and resp_status != 204:
                    self.send_header("Content-Type", resp_content_type)
                self.send_header("Content-Length", str(len(resp_body)))
                self.send_cors_headers()
                self.end_headers()
                if resp_body:
                    self.wfile.write(resp_body)
        except urllib.error.HTTPError as he:
            # Pass through HTTP error responses (e.g. 400, 404 from upstream)
            try:
                err_body = he.read()
                self.send_response(he.code)
                self.send_header("Content-Type", he.headers.get("Content-Type", "application/json; charset=utf-8"))
                self.send_header("Content-Length", str(len(err_body)))
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(err_body)
            except Exception:
                self.send_upstream_down_json(502, str(he), upstream_name)
        except Exception as e:
            # Network/Connection error -> 502 with upstream: "down"
            self.send_upstream_down_json(502, str(e), upstream_name)

    def send_upstream_down_json(self, status, message, upstream_name):
        body = json.dumps({
            "error": message,
            "upstream": "down",
            "service": upstream_name
        }).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status, message):
        body = json.dumps({"error": message}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def handle_static(self, path, query=""):
        """Serves files from web/, insights/web/, or ideas/site/ directory."""
        if path in ("", "/"):
            path = "/index.html"

        if path == "/insights":
            self.send_response(301)
            new_loc = "/insights/" + (f"?{query}" if query else "")
            self.send_header("Location", new_loc)
            self.end_headers()
            return

        if path == "/ideas":
            self.send_response(301)
            new_loc = "/ideas/" + (f"?{query}" if query else "")
            self.send_header("Location", new_loc)
            self.end_headers()
            return

        if path.startswith("/insights/"):
            root_dir = INSIGHTS_WEB_DIR
            rel_path = path[len("/insights/"):].lstrip("/")
            is_sub_app = True
        elif path.startswith("/ideas/"):
            root_dir = IDEAS_SITE_DIR
            rel_path = path[len("/ideas/"):].lstrip("/")
            is_sub_app = True
        else:
            root_dir = WEB_DIR
            rel_path = path.lstrip("/")
            is_sub_app = False

        if not rel_path:
            rel_path = "index.html"

        # Prevent directory traversal
        norm_path = os.path.normpath(rel_path)
        if norm_path.startswith("..") or os.path.isabs(norm_path):
            self.send_error_json(403, "Forbidden")
            return

        file_path = os.path.join(root_dir, norm_path)
        if os.path.isdir(file_path):
            if not path.endswith("/"):
                self.send_response(301)
                new_loc = path + "/" + (f"?{query}" if query else "")
                self.send_header("Location", new_loc)
                self.end_headers()
                return
            candidate = os.path.join(file_path, "index.html")
            if os.path.exists(candidate):
                file_path = candidate
            elif not is_sub_app:
                file_path = os.path.join(WEB_DIR, "index.html")
            else:
                self.send_error_json(404, "File Not Found")
                return
        elif not os.path.exists(file_path):
            if not is_sub_app:
                # Fallback to index.html for SPA client-side routes
                file_path = os.path.join(WEB_DIR, "index.html")
            else:
                self.send_error_json(404, "File Not Found")
                return

        if not os.path.exists(file_path):
            self.send_error_json(404, "File Not Found")
            return

        ext = os.path.splitext(file_path)[1].lower()
        content_types = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".svg": "image/svg+xml",
            ".json": "application/json; charset=utf-8",
            ".png": "image/png",
            ".ico": "image/x-icon",
            ".woff2": "font/woff2"
        }
        ctype = content_types.get(ext, "application/octet-stream")

        try:
            with open(file_path, "rb") as f:
                content = f.read()

            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(content)))
            if ext in (".js", ".html"):
                self.send_header("Cache-Control", "no-cache")
            else:
                self.send_header("Cache-Control", "max-age=300")
            self.send_cors_headers()
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(content)
        except Exception as e:
            self.send_error_json(500, f"Error reading file: {e}")


class ReusableThreadingServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(WEB_DIR, exist_ok=True)

    # 1. Main console server on 8903
    try:
        server = ReusableThreadingServer(("0.0.0.0", PORT), ForgeConsoleHandler)
    except OSError as e:
        msg = f"ERROR: Port {PORT} already in use (failed to bind forge-console server): {e}"
        print(msg, file=sys.stderr)
        log_collector(msg)
        raise

    # 2. Insights engine server on 8901
    insights_server = None
    try:
        spec_insights = importlib.util.spec_from_file_location(
            "insights_engine", str(BASE_DIR / "insights" / "server.py")
        )
        insights_engine = importlib.util.module_from_spec(spec_insights)
        sys.modules["insights_engine"] = insights_engine
        spec_insights.loader.exec_module(insights_engine)
        insights_handler = insights_engine.Handler

        ThreadingHTTPServer.allow_reuse_address = True
        insights_server = ThreadingHTTPServer(("0.0.0.0", INSIGHTS_PORT), insights_handler)
        insights_server.daemon_threads = True
        insights_thread = threading.Thread(target=insights_server.serve_forever, daemon=True)
        insights_thread.start()
    except OSError as e:
        msg = f"Port {INSIGHTS_PORT} already in use (forwarding to existing service): {e}"
        print(f"[*] {msg}")
        log_collector(msg)

    # 3. Ideas engine server on 8902
    ideas_server = None
    try:
        ideas_dir = str(BASE_DIR / "ideas")
        if ideas_dir not in sys.path:
            sys.path.insert(0, ideas_dir)
        spec_ideas = importlib.util.spec_from_file_location(
            "ideas_engine", str(BASE_DIR / "ideas" / "server.py")
        )
        ideas_engine = importlib.util.module_from_spec(spec_ideas)
        sys.modules["ideas_engine"] = ideas_engine
        spec_ideas.loader.exec_module(ideas_engine)
        ideas_handler = ideas_engine.SchemeBoardHandler

        ThreadingHTTPServer.allow_reuse_address = True
        ideas_server = ThreadingHTTPServer(("0.0.0.0", IDEAS_PORT), ideas_handler)
        ideas_server.daemon_threads = True
        ideas_thread = threading.Thread(target=ideas_server.serve_forever, daemon=True)
        ideas_thread.start()
    except OSError as e:
        msg = f"Port {IDEAS_PORT} already in use (forwarding to existing service): {e}"
        print(f"[*] {msg}")
        log_collector(msg)

    # 4. Collector thread (starts AFTER engine servers are listening)
    collector_thread = threading.Thread(target=collector_loop, daemon=True)
    collector_thread.start()

    def handle_exit(signum, frame):
        # Raise SystemExit so main thread enters finally block immediately
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_exit)
    signal.signal(signal.SIGINT, handle_exit)

    print(f"Forge Console server running at http://0.0.0.0:{PORT}")
    print(f"Insights engine running at http://0.0.0.0:{INSIGHTS_PORT}")
    print(f"Ideas engine running at http://0.0.0.0:{IDEAS_PORT}")
    try:
        server.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        server.server_close()
        if insights_server:
            try:
                insights_server.server_close()
            except Exception:
                pass
        if ideas_server:
            try:
                ideas_server.server_close()
            except Exception:
                pass
        print("Forge Console server closed cleanly.")


if __name__ == "__main__":
    main()
