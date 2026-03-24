#!/usr/bin/env python3
"""Clade Monitor — lightweight HTTP bridge for OpenClaw integration.

Reads CLI tool state files (.claude/loop-state, logs/loop/, session reports)
and exposes them as REST endpoints. No dependency on the orchestrator.

Usage:
    CLADE_API_KEY=secret python monitor.py --project /path/to/project --port 9100
    # or monitor multiple projects:
    python monitor.py --project /proj1 --project /proj2
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import json
import os
import re
import subprocess
from pathlib import Path
from http import HTTPStatus

from aiohttp import web

# ─── Config ───────────────────────────────────────────────────────────────────

VERSION = "1.0.0"
API_KEY = os.environ.get("CLADE_API_KEY", "")


# ─── Auth Middleware ──────────────────────────────────────────────────────────

@web.middleware
async def auth_middleware(request: web.Request, handler):
    if not API_KEY:
        return await handler(request)
    if request.path == "/health":
        return await handler(request)
    token = request.headers.get("Authorization", "")
    if token != f"Bearer {API_KEY}":
        return web.json_response({"error": "Unauthorized"}, status=401)
    return await handler(request)


# ─── State File Parsers ──────────────────────────────────────────────────────

def _parse_kv_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE file (loop-state, session-progress)."""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text().splitlines():
        if "=" in line:
            key, _, val = line.partition("=")
            result[key.strip()] = val.strip()
    return result


def _parse_cost_log(path: Path) -> list[dict]:
    """Parse .claude/loop-cost.log — space-separated KV pairs per line."""
    entries: list[dict] = []
    if not path.exists():
        return entries
    for line in path.read_text().splitlines():
        entry: dict[str, str] = {}
        for token in line.split():
            if "=" in token:
                k, _, v = token.partition("=")
                entry[k] = v.lstrip("$")
        if entry:
            entries.append(entry)
    return entries


def _latest_file(pattern: str) -> Path | None:
    """Find most recently modified file matching glob pattern."""
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    return Path(files[0]) if files else None


def _read_tail(path: Path, lines: int = 30) -> str:
    """Read last N lines of a file."""
    if not path.exists():
        return ""
    all_lines = path.read_text().splitlines()
    return "\n".join(all_lines[-lines:])


def _git_log(project: Path, n: int = 5) -> list[str]:
    """Get recent git commits."""
    try:
        result = subprocess.run(
            ["git", "log", f"--oneline", f"-{n}"],
            capture_output=True, text=True, timeout=5, cwd=project,
        )
        return result.stdout.strip().splitlines() if result.returncode == 0 else []
    except Exception:
        return []


# ─── Route Handlers ──────────────────────────────────────────────────────────

def _resolve_project(request: web.Request, projects: list[Path]) -> Path | None:
    """Resolve project from query param or default to first registered."""
    p = request.query.get("project", "")
    if p:
        path = Path(p)
        return path if path.is_dir() else None
    return projects[0] if projects else None


async def handle_status(request: web.Request) -> web.Response:
    projects: list[Path] = request.app["projects"]
    proj = _resolve_project(request, projects)
    if not proj:
        return web.json_response({"error": "No project found"}, status=404)

    # Loop state
    loop_state = _parse_kv_file(proj / ".claude" / "loop-state")
    # Also check inner loop state from start.sh
    start_state = _parse_kv_file(proj / ".claude" / "loop-state-start")
    if start_state and not loop_state:
        loop_state = start_state

    # Session progress (from start.sh)
    session = _parse_kv_file(proj / ".claude" / "session-progress.md")

    # Latest supervisor log
    latest_sup = _latest_file(str(proj / "logs" / "loop" / "iter-*-supervisor.log"))
    supervisor_log = _read_tail(latest_sup, 20) if latest_sup else ""

    # Latest progress file
    latest_prog = _latest_file(str(proj / "logs" / "loop" / "*-progress"))
    progress = _parse_kv_file(latest_prog) if latest_prog else {}

    # Cost
    cost_entries = _parse_cost_log(proj / ".claude" / "loop-cost.log")
    total_cost = cost_entries[-1].get("CUMULATIVE", "0") if cost_entries else "0"
    last_cost = cost_entries[-1].get("COST", "0") if cost_entries else "0"

    # Recent commits
    commits = _git_log(proj)

    # Blockers
    blockers_file = proj / ".claude" / "blockers.md"
    has_blockers = blockers_file.exists() and blockers_file.stat().st_size > 0

    return web.json_response({
        "project": str(proj),
        "loop": {
            "iteration": int(loop_state.get("ITERATION", "0")),
            "converged": loop_state.get("CONVERGED", "false") == "true",
            "goal": loop_state.get("GOAL", ""),
            "started": loop_state.get("STARTED", ""),
        },
        "session": {
            "mode": session.get("MODE", ""),
            "status": session.get("STATUS", progress.get("STATUS", "unknown")),
            "outer_iter": int(session.get("OUTER_ITER", "0")),
            "feature": session.get("CURRENT_FEATURE", ""),
        },
        "cost": {"total": total_cost, "last_iter": last_cost},
        "recent_commits": commits,
        "last_supervisor": supervisor_log[:2000],
        "has_blockers": has_blockers,
    })


async def handle_report(request: web.Request) -> web.Response:
    projects: list[Path] = request.app["projects"]
    proj = _resolve_project(request, projects)
    if not proj:
        return web.json_response({"error": "No project found"}, status=404)

    # Find latest session report
    report_pattern = str(proj / ".claude" / "session-report-*.md")
    latest_report = _latest_file(report_pattern)
    report_text = latest_report.read_text() if latest_report else "No session report found."

    # Cost history
    cost_entries = _parse_cost_log(proj / ".claude" / "loop-cost.log")

    # Blockers + skipped
    blockers = (proj / ".claude" / "blockers.md").read_text() if (proj / ".claude" / "blockers.md").exists() else ""
    skipped = (proj / ".claude" / "skipped.md").read_text() if (proj / ".claude" / "skipped.md").exists() else ""

    return web.json_response({
        "project": str(proj),
        "report": report_text,
        "cost_history": cost_entries,
        "blockers": blockers,
        "skipped": skipped,
    })


async def handle_control(request: web.Request) -> web.Response:
    projects: list[Path] = request.app["projects"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    project_path = body.get("project", str(projects[0]) if projects else "")
    proj = Path(project_path)
    if not proj.is_dir():
        return web.json_response({"error": f"Project not found: {project_path}"}, status=404)

    action = body.get("action", "")

    if action == "stop":
        sentinel = proj / ".claude" / "stop-start"
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.touch()
        return web.json_response({"ok": True, "action": "stop", "sentinel": str(sentinel)})

    elif action == "start":
        goal = body.get("goal", "")
        max_iter = body.get("max_iter", 10)
        max_workers = body.get("max_workers", 4)
        model = body.get("model", "sonnet")

        if not goal:
            return web.json_response({"error": "goal is required for start"}, status=400)

        # Remove stop sentinel if present
        sentinel = proj / ".claude" / "stop-start"
        if sentinel.exists():
            sentinel.unlink()

        # Write inline goal to temp file if not a path
        goal_path = Path(goal)
        if not goal_path.is_absolute() or not goal_path.exists():
            goal_file = proj / ".claude" / "monitor-goal.md"
            goal_file.parent.mkdir(parents=True, exist_ok=True)
            goal_file.write_text(goal)
            goal_path = goal_file

        # Launch start.sh --goal
        start_sh = Path.home() / ".claude" / "scripts" / "start.sh"
        if not start_sh.exists():
            return web.json_response({"error": "start.sh not found"}, status=500)

        cmd = [
            "bash", str(start_sh),
            "--goal", str(goal_path),
            "--max-iter", str(max_iter),
            "--max-workers", str(max_workers),
            "--model", model,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(proj),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return web.json_response({
            "ok": True, "action": "start", "pid": proc.pid,
            "goal": str(goal_path), "max_iter": max_iter,
        })

    elif action == "clear-blockers":
        blockers = proj / ".claude" / "blockers.md"
        if blockers.exists():
            blockers.unlink()
        return web.json_response({"ok": True, "action": "clear-blockers"})

    else:
        return web.json_response(
            {"error": f"Unknown action: {action}. Use: start, stop, clear-blockers"},
            status=400,
        )


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "version": VERSION})


# ─── App Setup ────────────────────────────────────────────────────────────────

def create_app(projects: list[Path]) -> web.Application:
    app = web.Application(middlewares=[auth_middleware])
    app["projects"] = projects
    app.router.add_get("/health", handle_health)
    app.router.add_get("/status", handle_status)
    app.router.add_get("/report", handle_report)
    app.router.add_post("/control", handle_control)
    return app


def main():
    parser = argparse.ArgumentParser(description="Clade Monitor")
    parser.add_argument(
        "--project", "-p", action="append", default=[],
        help="Project directory to monitor (can specify multiple)",
    )
    parser.add_argument("--port", type=int, default=9100, help="Port (default: 9100)")
    parser.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")
    args = parser.parse_args()

    projects = [Path(p).resolve() for p in args.project] if args.project else [Path.cwd()]
    for p in projects:
        if not p.is_dir():
            parser.error(f"Not a directory: {p}")

    app = create_app(projects)
    print(f"Clade Monitor v{VERSION} — {len(projects)} project(s) on :{args.port}")
    if API_KEY:
        print("Auth: Bearer token required")
    else:
        print("Auth: disabled (set CLADE_API_KEY to enable)")
    for p in projects:
        print(f"  → {p}")
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
