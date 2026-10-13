#!/usr/bin/env python3
"""
Forge Console - Flow Data Collector
Gathers live metrics for harnesses, filesystem, projects, services, and databases.
Importable and runnable standalone.
"""

import os
import sys
import time
import json
import sqlite3
import socket
import urllib.request
import urllib.error

# Paths
HOME = os.path.expanduser("~")
PROJECTS_DIR = os.path.join(HOME, "HydrocarbonForge", "Projects")
OPENCODE_DB = os.path.join(HOME, ".local", "share", "opencode", "opencode.db")
CLAUDE_DIR = os.path.join(HOME, ".claude")
HERMES_DIR = os.path.join(HOME, ".hermes")
SCHEME_DB = os.path.join(PROJECTS_DIR, "forge-console", "ideas", "data", "board.db")

# Short active window for project highlights/dots in Flow (10 minutes)
PROJECT_ACTIVE_WINDOW_S = 600

# Cache for filesystem file counts to ensure <50ms walk
_project_cache = {}
_last_project_scan = 0.0


def scan_processes_by_name():
    """
    Scans /proc/*/cmdline without psutil or external dependencies.
    Returns dict mapping target name ('claude', 'agy', 'hermes', 'opencode') to list of pids.
    """
    found = {"claude": [], "agy": [], "hermes": [], "opencode": []}
    my_pid = os.getpid()

    try:
        proc_entries = os.listdir("/proc")
    except Exception:
        return found

    for pid_str in proc_entries:
        if not pid_str.isdigit() or int(pid_str) == my_pid:
            continue
        cmd_path = os.path.join("/proc", pid_str, "cmdline")
        try:
            with open(cmd_path, "rb") as f:
                raw = f.read()
            if not raw:
                continue
            parts = [p.decode("utf-8", errors="ignore") for p in raw.split(b"\x00") if p]
            if not parts:
                continue

            exe_name = os.path.basename(parts[0])
            first_arg = os.path.basename(parts[1]) if len(parts) > 1 else ""

            # Check agy
            if exe_name == "agy" or "/.local/bin/agy" in parts[0]:
                found["agy"].append(int(pid_str))

            # Check claude
            if exe_name == "claude" or "/bin/claude" in parts[0] or exe_name.startswith("claude"):
                found["claude"].append(int(pid_str))

            # Check opencode (skip the persistent background daemon
            # `opencode serve --service`; real runs are `opencode run ...`)
            if exe_name == "opencode" or "opencode-go" in parts[0] or "/bin/opencode" in parts[0]:
                if "serve" in parts and "--service" in parts:
                    continue
                found["opencode"].append(int(pid_str))

            # Check hermes gateway (scan for processes whose argv matches hermes + gateway,
            # excluding shells, other agent wrappers, and daemons)
            has_hermes = ("hermes" in parts[0]) or (exe_name == "hermes") or (len(parts) > 1 and "hermes" in parts[1])
            has_gateway = "gateway" in parts
            if has_hermes and has_gateway and exe_name not in ("bash", "sh", "zsh", "agy", "claude", "opencode"):
                found["hermes"].append(int(pid_str))

        except Exception:
            continue

    return found


def _get_server_token_metric(source):
    """
    Reads today's token count for `source` directly from server._home_tokens_cache
    without loopback HTTP pings.
    """
    for mod_name in ("server", "__main__"):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "_home_tokens_cache"):
            try:
                fn = getattr(mod, "get_cached_today_tokens", None)
                if callable(fn):
                    return fn(source)
                cache = getattr(mod, "_home_tokens_cache", None)
                if isinstance(cache, dict) and cache.get("data"):
                    by_src = cache["data"].get("billed_today_by_source", {}).get("by_source", {})
                    val = by_src.get(source)
                    if val is not None:
                        return int(val)
            except Exception:
                pass
    return 0


def _get_server_session_metric(source):
    """
    Reads session count for `source` directly from server._home_tokens_cache.
    """
    for mod_name in ("server", "__main__"):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "_home_tokens_cache"):
            try:
                fn = getattr(mod, "get_cached_sessions", None)
                if callable(fn):
                    return fn(source)
                cache = getattr(mod, "_home_tokens_cache", None)
                if isinstance(cache, dict) and cache.get("data"):
                    sessions = cache["data"].get("sessions_today", {})
                    val = sessions.get(source)
                    if val is not None:
                        return int(val)
            except Exception:
                pass
    return 0


def get_harnesses(procs):
    """
    Returns the four agent harness nodes: opencode, claude code, antigravity, C6 (Hermes).
    """
    harnesses = []
    now_ms = int(time.time() * 1000)
    ten_min_ago = now_ms - (10 * 60 * 1000)
    day_ago = now_ms - (24 * 60 * 60 * 1000)

    # 1. OpenCode
    opencode_active = 0
    opencode_subtasks = 0
    opencode_total = 0
    if os.path.exists(OPENCODE_DB):
        try:
            uri = f"file:{OPENCODE_DB}?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=2.0) as conn:
                cur = conn.cursor()
                # Active sessions updated in last 10 minutes
                cur.execute("SELECT count(*) FROM session_v2 WHERE time_updated > ?", (ten_min_ago,))
                row = cur.fetchone()
                if row:
                    opencode_active = row[0]

                # Subtasks (parent_id IS NOT NULL) in last 24h
                cur.execute("SELECT count(*) FROM session_v2 WHERE parent_id IS NOT NULL AND time_updated > ?", (day_ago,))
                row = cur.fetchone()
                if row:
                    opencode_subtasks = row[0]

                cur.execute("SELECT count(*) FROM session_v2")
                row = cur.fetchone()
                if row:
                    opencode_total = row[0]
        except Exception:
            pass

    # OpenCode process check
    opencode_pids = procs.get("opencode", [])
    if opencode_pids and opencode_active == 0:
        opencode_active = len(opencode_pids)

    # Try fetching today's usage from insights API (fast 500ms timeout)
    op_tokens = 0
    try:
        req = urllib.request.Request("http://127.0.0.1:8901/api/opencode?days=1", headers={"User-Agent": "ForgeConsole/1.0"})
        with urllib.request.urlopen(req, timeout=0.8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            tot = data.get("total", {})
            op_tokens = tot.get("input_tokens", 0) + tot.get("output_tokens", 0)
    except Exception:
        pass

    harnesses.append({
        "id": "harness-opencode",
        "name": "opencode",
        "label": "OpenCode",
        "active_sessions": opencode_active,
        "subtasks": opencode_subtasks,
        "total_sessions": opencode_total,
        "tokens_today": op_tokens,
        "running": opencode_active > 0 or len(opencode_pids) > 0,
        "pids": opencode_pids,
        "accent": "#38BDF8",
        "type": "harness"
    })

    # 2. Claude Code
    claude_pids = procs.get("claude", [])
    claude_active = len(claude_pids)
    claude_sessions_dir = os.path.join(CLAUDE_DIR, "sessions")
    claude_recent_files = 0
    if os.path.exists(claude_sessions_dir):
        try:
            now_s = time.time()
            for entry in os.scandir(claude_sessions_dir):
                if entry.is_file() and (now_s - entry.stat().st_mtime) < 600:
                    claude_recent_files += 1
            if claude_recent_files > claude_active:
                claude_active = claude_recent_files
        except Exception:
            pass

    cc_tokens = _get_server_token_metric("claudecode")

    harnesses.append({
        "id": "harness-claude",
        "name": "claude code",
        "label": "Claude Code",
        "active_sessions": claude_active,
        "subtasks": 0,
        "total_sessions": claude_active,
        "tokens_today": cc_tokens,
        "running": claude_active > 0,
        "pids": claude_pids,
        "accent": "#FF8C42",
        "type": "harness"
    })

    # 3. Antigravity (agy)
    agy_pids = procs.get("agy", [])
    agy_active = len(agy_pids)

    ag_tokens = _get_server_token_metric("antigravity")
    ag_sessions = _get_server_session_metric("antigravity")

    harnesses.append({
        "id": "harness-antigravity",
        "name": "antigravity",
        "label": "Antigravity (AGY)",
        "active_sessions": agy_active,
        "subtasks": 0,
        "total_sessions": max(agy_active, ag_sessions),
        "tokens_today": ag_tokens,
        "running": agy_active > 0,
        "pids": agy_pids,
        "accent": "#3DDC84",
        "type": "harness"
    })

    # 4. C6 (Hermes)
    hermes_pids = procs.get("hermes", [])
    hermes_alive = len(hermes_pids) > 0
    if not hermes_alive:
        hermes_pid_file = os.path.join(HERMES_DIR, "gateway.pid")
        if os.path.exists(hermes_pid_file):
            try:
                with open(hermes_pid_file, "r") as f:
                    g_data = json.loads(f.read())
                g_pid = g_data.get("pid")
                if g_pid and os.path.exists(f"/proc/{g_pid}"):
                    hermes_alive = True
                    hermes_pids = [int(g_pid)]
            except Exception:
                pass

    c6_active_sessions = 0
    c6_last_active_s = None
    c6_subtasks = 0
    hermes_db = os.path.join(HERMES_DIR, "state.db")
    if os.path.exists(hermes_db):
        conn = None
        try:
            conn = sqlite3.connect(f"file:{os.path.abspath(hermes_db)}?mode=ro", uri=True, timeout=2.0)
            cur = conn.cursor()
            now = time.time()
            cur.execute("SELECT COUNT(DISTINCT session_id) FROM messages WHERE timestamp > ?", (now - 300,))
            row = cur.fetchone()
            if row and row[0] is not None:
                c6_active_sessions = int(row[0])

            cur.execute("SELECT MAX(timestamp) FROM messages")
            row = cur.fetchone()
            if row and row[0] is not None:
                c6_last_active_s = round(max(0.0, now - float(row[0])), 1)

            try:
                cur.execute("SELECT COUNT(*) FROM session_turn_leases")
                row = cur.fetchone()
                if row and row[0] is not None:
                    c6_subtasks = int(row[0])
            except Exception:
                c6_subtasks = 0
        except Exception:
            c6_active_sessions = 0
            c6_last_active_s = None
            c6_subtasks = 0
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    c6_tokens = 0
    try:
        req = urllib.request.Request("http://127.0.0.1:8901/api/summary?days=1", headers={"User-Agent": "ForgeConsole/1.0"})
        with urllib.request.urlopen(req, timeout=0.8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            c6_tokens = data.get("input_tokens", 0) + data.get("output_tokens", 0)
    except Exception:
        pass

    harnesses.append({
        "id": "harness-c6",
        "name": "c6",
        "label": "C6 (Hermes)",
        "active_sessions": c6_active_sessions,
        "last_active_s": c6_last_active_s,
        "subtasks": c6_subtasks,
        "total_sessions": 0,
        "tokens_today": c6_tokens,
        "running": hermes_alive,
        "pids": hermes_pids,
        "accent": "#C792EA",
        "type": "harness"
    })

    return harnesses


def get_filesystem_and_projects():
    """
    Scans ~/HydrocarbonForge/Projects/ efficiently with cached listings.
    Returns (filesystem_dict, projects_list).
    """
    global _project_cache, _last_project_scan

    now = time.time()
    recent_files = []
    projects = []

    if not os.path.exists(PROJECTS_DIR):
        return {"recent": []}, []

    # Refresh project scan every 10 seconds or use cache
    do_deep_scan = (now - _last_project_scan) > 10.0
    if do_deep_scan:
        _last_project_scan = now

    skip_dirs = {".git", "node_modules", ".venv", "__pycache__", "dist", "build", ".next", ".cache"}

    try:
        entries = [e for e in os.scandir(PROJECTS_DIR) if e.is_dir() and not e.name.startswith(".")]
    except Exception:
        entries = []

    for entry in entries:
        proj_name = entry.name
        proj_path = entry.path

        cached = _project_cache.get(proj_name, {"file_count": 0, "changes_60m": 0, "last_scan": 0, "newest_mtime": None})
        file_count = cached["file_count"]
        changes_60m = 0
        newest_mtime = None

        # Scan files in project (up to 2 levels deep for high speed)
        if do_deep_scan:
            count = 0
            try:
                for root, dirs, files in os.walk(proj_path):
                    dirs[:] = [d for d in dirs if not d.startswith(".") and d not in skip_dirs]
                    count += len(files)
                    for f in files:
                        fp = os.path.join(root, f)
                        try:
                            st = os.stat(fp)
                            age = now - st.st_mtime
                            if age < 3600:
                                changes_60m += 1
                                if newest_mtime is None or st.st_mtime > newest_mtime:
                                    newest_mtime = st.st_mtime
                                rel_path = os.path.relpath(fp, PROJECTS_DIR)
                                recent_files.append({
                                    "path": rel_path,
                                    "project": proj_name,
                                    "mtime": st.st_mtime,
                                    "age_m": round(age / 60.0, 1),
                                    "size": st.st_size
                                })
                        except Exception:
                            pass
                file_count = count
                _project_cache[proj_name] = {
                    "file_count": file_count,
                    "changes_60m": changes_60m,
                    "newest_mtime": newest_mtime,
                    "last_scan": now
                }
            except Exception:
                pass
        else:
            # Quick stat on root and subdirs level 1
            changes_60m = cached.get("changes_60m", 0)
            newest_mtime = cached.get("newest_mtime")
            try:
                for sub in os.scandir(proj_path):
                    if sub.name.startswith(".") or sub.name in skip_dirs:
                        continue
                    if sub.is_file():
                        st = sub.stat()
                        age = now - st.st_mtime
                        if age < 3600:
                            if newest_mtime is None or st.st_mtime > newest_mtime:
                                newest_mtime = st.st_mtime
                            rel_path = os.path.relpath(sub.path, PROJECTS_DIR)
                            recent_files.append({
                                "path": rel_path,
                                "project": proj_name,
                                "mtime": st.st_mtime,
                                "age_m": round(age / 60.0, 1),
                                "size": st.st_size
                            })
            except Exception:
                pass

        if newest_mtime is not None:
            newest_age = max(0.0, now - newest_mtime)
            last_write_age_min = round(newest_age / 60.0, 1)
            is_active = newest_age < PROJECT_ACTIVE_WINDOW_S
        else:
            last_write_age_min = None
            is_active = False

        projects.append({
            "id": f"proj-{proj_name}",
            "name": proj_name,
            "path": proj_name,
            "file_count": file_count,
            "changes_60m": changes_60m,
            "last_write_age_min": last_write_age_min,
            "active": is_active,
            "accent": "#5AA9E6" if is_active else "#9D9EA5",
            "type": "project"
        })

    # Sort recent files by mtime desc, take top 10
    recent_files.sort(key=lambda x: x["mtime"], reverse=True)
    recent_files = recent_files[:10]

    return {"recent": recent_files}, projects


def check_http_endpoint(url, timeout=1.5):
    """
    Checks HTTP endpoint health and measures latency.
    Returns (status_str, latency_ms, detail).
    """
    t0 = time.time()
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "ForgeConsole/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            latency = int((time.time() - t0) * 1000)
            if resp.status in (200, 204):
                return "green", latency, f"{resp.status} OK"
            return "amber", latency, f"HTTP {resp.status}"
    except Exception:
        # Fallback to GET if HEAD method not allowed
        try:
            req = urllib.request.Request(url, method="GET", headers={"User-Agent": "ForgeConsole/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                latency = int((time.time() - t0) * 1000)
                if resp.status in (200, 204):
                    return "green", latency, f"{resp.status} OK"
                return "amber", latency, f"HTTP {resp.status}"
        except Exception as e:
            return "red", 0, str(e)


def get_services(procs):
    """
    Checks status for insights-board, scheme-board, forge-console, hermes gateway, website.
    """
    services = []

    # 1. Insights Board :8901
    st_insights, lat_insights, det_insights = check_http_endpoint("http://127.0.0.1:8901/api/health")
    services.append({
        "id": "srv-insights-board",
        "name": "insights-board",
        "label": "Insights Board",
        "port": 8901,
        "status": st_insights,
        "latency_ms": lat_insights,
        "detail": det_insights,
        "url": "http://127.0.0.1:8901",
        "accent": "#5AA9E6",
        "type": "service"
    })

    # 2. Scheme Board :8902
    st_scheme, lat_scheme, det_scheme = check_http_endpoint("http://127.0.0.1:8902/api/health")
    services.append({
        "id": "srv-scheme-board",
        "name": "scheme-board",
        "label": "Scheme Board",
        "port": 8902,
        "status": st_scheme,
        "latency_ms": lat_scheme,
        "detail": det_scheme,
        "url": "http://127.0.0.1:8902",
        "accent": "#FF8C42",
        "type": "service"
    })

    # 3. Forge Console :8903 (self)
    port = int(os.environ.get("PORT", 8903))
    services.append({
        "id": "srv-forge-console",
        "name": "forge-console",
        "label": "Forge Console",
        "port": port,
        "status": "green",
        "latency_ms": 1,
        "detail": "self running",
        "url": f"http://127.0.0.1:{port}",
        "accent": "#FF8C42",
        "type": "service"
    })

    # 4. Hermes Gateway
    hermes_pids = procs.get("hermes", [])
    hermes_pid_file = os.path.join(HERMES_DIR, "gateway.pid")
    hermes_sock = os.path.join(HERMES_DIR, "gateway.sock")
    hermes_alive = False
    hermes_detail = "stopped"

    if os.path.exists(hermes_pid_file):
        try:
            with open(hermes_pid_file, "r") as f:
                data = json.loads(f.read())
            g_pid = data.get("pid")
            if g_pid and os.path.exists(f"/proc/{g_pid}"):
                hermes_alive = True
                hermes_detail = f"PID {g_pid}"
        except Exception:
            pass

    if not hermes_alive and hermes_pids:
        hermes_alive = True
        hermes_detail = f"PID {hermes_pids[0]}"

    services.append({
        "id": "srv-hermes-gateway",
        "name": "hermes gateway",
        "label": "Hermes Gateway",
        "port": None,
        "status": "green" if hermes_alive else "amber" if os.path.exists(hermes_sock) else "red",
        "latency_ms": 0,
        "detail": hermes_detail,
        "accent": "#5AD6A0",
        "type": "service"
    })

    # 5. Website static dir
    web_dir = os.path.join(PROJECTS_DIR, "hydrocarbon-forge-website", "index.html")
    web_exists = os.path.exists(web_dir)
    services.append({
        "id": "srv-website",
        "name": "website",
        "label": "Forge Website",
        "port": None,
        "status": "green" if web_exists else "red",
        "latency_ms": 0,
        "detail": "static dir ready" if web_exists else "index.html missing",
        "accent": "#B185DB",
        "type": "service"
    })

    return services


def format_size(bytes_val):
    """Formats bytes to human string."""
    if bytes_val is None or bytes_val < 0:
        return "—"
    if bytes_val >= 1024 * 1024 * 1024:
        return f"{bytes_val / (1024*1024*1024):.1f} GB"
    if bytes_val >= 1024 * 1024:
        return f"{bytes_val / (1024*1024):.1f} MB"
    if bytes_val >= 1024:
        return f"{bytes_val / 1024:.1f} KB"
    return f"{bytes_val} B"


def format_age(seconds):
    """Formats seconds to age string."""
    if seconds is None:
        return "—"
    s = int(seconds)
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


def get_databases():
    """
    Returns data nodes: state.db, opencode.db, board.db, hermes cron/logs.
    """
    targets = [
        {"id": "data-hermes-state", "name": "hermes state.db", "path": os.path.join(HERMES_DIR, "state.db"), "reader": "insights-board"},
        {"id": "data-opencode", "name": "opencode.db", "path": OPENCODE_DB, "reader": "insights-board"},
        {"id": "data-scheme-board", "name": "scheme board.db", "path": SCHEME_DB, "reader": "scheme-board"},
        {"id": "data-hermes-cron", "name": "hermes cron", "path": os.path.join(HERMES_DIR, "cron"), "reader": "hermes gateway"},
        {"id": "data-hermes-logs", "name": "hermes logs", "path": os.path.join(HERMES_DIR, "logs"), "reader": "hermes gateway"},
    ]

    databases = []
    now = time.time()

    for t in targets:
        p = t["path"]
        exists = os.path.exists(p)
        size_bytes = None
        mtime = None
        age_s = None

        if exists:
            try:
                st = os.stat(p)
                size_bytes = st.st_size
                mtime = st.st_mtime
                age_s = max(0.0, now - mtime)
            except Exception:
                pass

        databases.append({
            "id": t["id"],
            "name": t["name"],
            "path": p,
            "reader": t["reader"],
            "exists": exists,
            "size_bytes": size_bytes,
            "size_str": format_size(size_bytes),
            "mtime": mtime,
            "last_write_age_s": round(age_s, 1) if age_s is not None else None,
            "last_write_age_str": format_age(age_s),
            "accent": "#B5E48C",
            "type": "database"
        })

    return databases


def collect():
    """
    Gathers all 5 node groups and returns the flow document.
    Never raises out of the function.
    """
    t0 = time.time()
    procs = scan_processes_by_name()
    harnesses = get_harnesses(procs)
    fs, projects = get_filesystem_and_projects()
    services = get_services(procs)
    databases = get_databases()

    doc = {
        "harnesses": harnesses,
        "filesystem": fs,
        "projects": projects,
        "services": services,
        "databases": databases,
        "generated_at": time.time(),
        "elapsed_ms": round((time.time() - t0) * 1000, 2)
    }
    return doc


if __name__ == "__main__":
    data = collect()
    print(json.dumps(data, indent=2))
