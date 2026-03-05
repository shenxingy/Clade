"""
Claude Code Orchestrator — FastAPI server
Routes, WebSocket endpoints, and application entry point.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import (
    BASE_DIR,
    GLOBAL_SETTINGS,
    PROJECT_DIR,
    WEB_DIR,
    _SETTINGS_DEFAULTS,
    _deps_met,
    _recover_orphaned_tasks,
    _save_settings,
    scan_projects,
)
from session import (
    ProjectSession,
    _resolve_session,
    registry,
    status_loop,
)
from github_sync import (
    _gh_pull_issues,
    _gh_push_all,
)

logger = logging.getLogger(__name__)

# ─── App ──────────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.environ.get("ORCHESTRATOR_PROJECT_DIR"):
        default_session = registry.create(str(PROJECT_DIR))
        recovered = await _recover_orphaned_tasks(default_session.task_queue)
        if recovered:
            logger.info("Recovered %d orphaned tasks as 'interrupted'", recovered)
        default_session.start_watch()
    asyncio.create_task(status_loop())
    yield
    # Shutdown: stop all managed background processes
    from process_manager import process_pool
    stopped = await process_pool.stop_all()
    if stopped:
        logger.info("Stopped %d background processes on shutdown", stopped)


app = FastAPI(title="Claude Code Orchestrator", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from routes.webhooks import router as webhooks_router  # noqa: E402
from routes.ideas import router as ideas_router  # noqa: E402
from routes.process import router as process_router  # noqa: E402
from routes.tasks import router as tasks_router  # noqa: E402
from routes.workers import router as workers_router  # noqa: E402
app.include_router(webhooks_router)
app.include_router(ideas_router)
app.include_router(process_router)
app.include_router(tasks_router)
app.include_router(workers_router)

# Serve static files (web UI)
app.mount("/web", StaticFiles(directory=str(WEB_DIR)), name="web")

# ─── REST: Sessions ───────────────────────────────────────────────────────────


@app.get("/api/sessions")
async def list_sessions():
    return [s.to_dict() for s in registry.all()]


@app.post("/api/sessions")
async def create_session(body: dict):
    path_str = body.get("path", "").strip()
    if not path_str:
        raise HTTPException(status_code=400, detail="path is required")
    path = Path(path_str).expanduser().resolve()
    if not path.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory not found: {path}")
    try:
        rows = int(body.get("rows", 24))
        cols = int(body.get("cols", 80))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="rows and cols must be integers")
    session = registry.create(str(path))
    try:
        recovered = await _recover_orphaned_tasks(session.task_queue)
        if recovered:
            logger.info("Recovered %d orphaned tasks as 'interrupted' for new session", recovered)
        session.orchestrator.start(session.project_dir, rows=rows, cols=cols)
        session.start_watch()
    except Exception:
        registry.remove(session.session_id)
        raise
    return session.to_dict()



@app.get("/api/sessions/overview")
async def sessions_overview():
    result = []
    for s in registry.all():
        try:
            tasks = await s.task_queue.list()
        except Exception:
            tasks = []
        pending = sum(1 for t in tasks if t["status"] in ("pending", "queued"))
        running = sum(1 for t in tasks if t["status"] == "running")
        done = sum(1 for t in tasks if t["status"] == "done")
        failed = sum(1 for t in tasks if t["status"] == "failed")
        total_attempted = done + failed
        success_rate = round(done / total_attempted * 100) if total_attempted else None
        done_workers = [w for w in s.worker_pool.all() if w.status == "done"]
        avg_s = (sum(w.elapsed_s for w in done_workers) / len(done_workers)) if done_workers else None
        eta_s = round(avg_s * pending / max(1, running)) if (avg_s and pending) else None
        # Cost metrics
        try:
            total_cost = sum((t.get("estimated_cost") or 0.0) for t in tasks)
            started_ats = [t["started_at"] for t in tasks if t.get("started_at") is not None]
            if started_ats:
                first_started = min(started_ats)
                elapsed_hours = (time.time() - first_started) / 3600
                cost_rate_per_hour = total_cost / elapsed_hours if elapsed_hours > 0 else None
            else:
                cost_rate_per_hour = None
        except Exception:
            total_cost = 0.0
            cost_rate_per_hour = None
        result.append({
            "session_id": s.session_id,
            "name": s.name,
            "pending": pending,
            "running": running,
            "done": done,
            "failed": failed,
            "success_rate": success_rate,
            "eta_seconds": eta_s,
            "total_cost": round(total_cost, 6),
            "cost_rate_per_hour": round(cost_rate_per_hour, 6) if cost_rate_per_hour is not None else None,
        })
    return result


@app.get("/api/sessions/{session_id}/analytics")
async def session_analytics(session_id: str):
    s = registry.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    tasks = await s.task_queue.list()
    total = len(tasks)
    done = sum(1 for t in tasks if t["status"] == "done")
    failed = sum(1 for t in tasks if t["status"] == "failed")
    interrupted = sum(1 for t in tasks if t["status"] == "interrupted")
    pending = sum(1 for t in tasks if t["status"] in ("pending", "queued"))
    attempted = done + failed
    success_rate = round(done / attempted * 100, 1) if attempted else 0

    total_cost = 0.0
    total_input = 0
    total_output = 0
    model_stats: dict[str, dict] = {}
    for t in tasks:
        model = t.get("model", "sonnet")
        cost = t.get("estimated_cost") or 0
        inp = t.get("input_tokens") or 0
        out = t.get("output_tokens") or 0
        total_cost += cost
        total_input += inp
        total_output += out
        if model not in model_stats:
            model_stats[model] = {"count": 0, "done": 0, "failed": 0,
                                  "total_elapsed_s": 0, "total_cost": 0.0,
                                  "total_input_tokens": 0, "total_output_tokens": 0}
        ms = model_stats[model]
        ms["count"] += 1
        if t["status"] == "done":
            ms["done"] += 1
        elif t["status"] == "failed":
            ms["failed"] += 1
        ms["total_elapsed_s"] += t.get("elapsed_s") or 0
        ms["total_cost"] += cost
        ms["total_input_tokens"] += inp
        ms["total_output_tokens"] += out

    for ms in model_stats.values():
        ms["avg_elapsed_s"] = round(ms["total_elapsed_s"] / ms["count"], 1) if ms["count"] else 0
        ms["total_cost"] = round(ms["total_cost"], 4)

    return {
        "total": total, "done": done, "failed": failed,
        "interrupted": interrupted, "pending": pending,
        "success_rate": success_rate,
        "model_stats": model_stats,
        "total_cost": round(total_cost, 4),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
    }


@app.post("/api/sessions/start-all-queued")
async def global_start_all():
    total_started = 0
    session_results = []
    for s in registry.all():
        tasks = await s.task_queue.list()
        done_ids = {t["id"] for t in tasks if t["status"] == "done"}
        pending = [t for t in tasks if t["status"] in ("pending", "queued")]
        max_w = GLOBAL_SETTINGS.get("max_workers", 0)
        running_count = sum(1 for w in s.worker_pool.all() if w.status == "running")
        available = max(0, max_w - running_count) if max_w > 0 else len(pending)
        started = []
        for task in pending:
            if not _deps_met(task, done_ids) or available <= 0:
                continue
            await s.worker_pool.start_worker(task, s.task_queue, s.project_dir, s.claude_dir)
            started.append(task["id"])
            available -= 1
        total_started += len(started)
        session_results.append({"session_id": s.session_id, "name": s.name, "started": len(started)})
    return {"total_started": total_started, "sessions": session_results}

# ─── REST: Iteration Loop ────────────────────────────────────────────────────


@app.post("/api/sessions/{session_id}/loop/start")
async def start_loop(session_id: str, body: dict):
    s = registry.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    # Mutual exclusion with swarm
    if s._swarm and s._swarm.status in ("active", "draining"):
        raise HTTPException(status_code=409, detail="Cannot start loop while swarm is active")
    artifact_path = body.get("artifact_path", "").strip()
    if not artifact_path:
        raise HTTPException(status_code=400, detail="artifact_path required")
    context_dir = body.get("context_dir") or None
    try:
        convergence_k = int(body.get("convergence_k", GLOBAL_SETTINGS.get("loop_convergence_k", 2)))
        convergence_n = int(body.get("convergence_n", GLOBAL_SETTINGS.get("loop_convergence_n", 3)))
        max_iterations = int(body.get("max_iterations", GLOBAL_SETTINGS.get("loop_max_iterations", 20)))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="convergence_k, convergence_n, max_iterations must be integers")
    supervisor_model = body.get("supervisor_model", GLOBAL_SETTINGS.get("loop_supervisor_model", "sonnet"))
    mode = body.get("mode", "review")

    # Cancel any running loop coroutine — await to prevent race
    if s._loop_task and not s._loop_task.done():
        s._loop_task.cancel()
        try:
            await s._loop_task
        except (asyncio.CancelledError, Exception):
            pass
        s._loop_task = None

    # Reset loop state (delete old row, create fresh)
    await s.task_queue.delete_loop()
    await s.task_queue.upsert_loop(
        artifact_path=artifact_path,
        context_dir=context_dir,
        status="running",
        iteration=0,
        changes_history=[],
        deferred_items=[],
        convergence_k=convergence_k,
        convergence_n=convergence_n,
        max_iterations=max_iterations,
        supervisor_model=supervisor_model,
        mode=mode,
    )

    s._loop_task = asyncio.create_task(s._run_supervisor())
    return await s.task_queue.get_loop()


@app.get("/api/sessions/{session_id}/loop")
async def get_loop_state(session_id: str):
    s = registry.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return await s.task_queue.get_loop() or {}


@app.post("/api/sessions/{session_id}/loop/pause")
async def pause_loop(session_id: str):
    s = registry.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    if s._loop_task and not s._loop_task.done():
        s._loop_task.cancel()
        try:
            await s._loop_task
        except (asyncio.CancelledError, Exception):
            pass
        s._loop_task = None
    await s.task_queue.upsert_loop(status="paused")
    return await s.task_queue.get_loop()


@app.post("/api/sessions/{session_id}/loop/resume")
async def resume_loop(session_id: str):
    s = registry.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    loop_state = await s.task_queue.get_loop()
    if not loop_state:
        raise HTTPException(status_code=404, detail="No loop to resume")
    await s.task_queue.upsert_loop(status="running")
    if s._loop_task is None or s._loop_task.done():
        s._loop_task = asyncio.create_task(s._run_supervisor())
    return await s.task_queue.get_loop()


@app.delete("/api/sessions/{session_id}/loop")
async def cancel_loop(session_id: str):
    s = registry.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    if s._loop_task and not s._loop_task.done():
        s._loop_task.cancel()
        try:
            await s._loop_task
        except (asyncio.CancelledError, Exception):
            pass
        s._loop_task = None
    await s.task_queue.upsert_loop(
        status="cancelled", iteration=0, changes_history=[], deferred_items=[]
    )
    return {"ok": True}


@app.get("/api/sessions/{session_id}/loop/sources")
async def get_loop_sources(session_id: str):
    s = registry.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    project_dir = s.project_dir
    priority_names = ["BRAINSTORM.md", "TODO.md", "VISION.md", "PROGRESS.md"]
    results: list[dict] = []
    seen: set[str] = set()
    for name in priority_names:
        p = project_dir / name
        if p.exists():
            results.append({"label": name, "path": str(p)})
            seen.add(str(p))
    candidates: list[Path] = []
    for pattern in ("*.tex", "*.md"):
        for p in project_dir.glob(pattern):
            if str(p) not in seen:
                candidates.append(p)
    def _mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0
    candidates.sort(key=_mtime, reverse=True)
    for p in candidates[:5]:
        results.append({"label": p.name, "path": str(p)})
    return results


# ─── REST: Swarm ──────────────────────────────────────────────────────────────


@app.post("/api/sessions/{session_id}/swarm/start")
async def start_swarm(session_id: str, body: dict):
    from worker import SwarmManager
    s = registry.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    # Mutual exclusion with iteration loop
    loop_state = await s.task_queue.get_loop()
    if loop_state and loop_state.get("status") == "running":
        raise HTTPException(status_code=409, detail="Cannot start swarm while iteration loop is running")
    if s._swarm and s._swarm.status == "active":
        raise HTTPException(status_code=409, detail="Swarm already active")
    # Cancel old refill loop if still running
    if s._swarm and s._swarm._task and not s._swarm._task.done():
        s._swarm._task.cancel()
        try:
            await s._swarm._task
        except (asyncio.CancelledError, Exception):
            pass
    try:
        slots = int(body.get("slots", 3))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="slots must be an integer")
    s._swarm = SwarmManager(s)
    return s._swarm.start(slots)


@app.post("/api/sessions/{session_id}/swarm/stop")
async def stop_swarm(session_id: str, body: dict = Body(default={})):
    s = registry.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    if not s._swarm:
        raise HTTPException(status_code=404, detail="No swarm active")
    force = (body or {}).get("force", False)
    if force:
        return await s._swarm.force_stop()
    return s._swarm.stop()


@app.post("/api/sessions/{session_id}/swarm/resize")
async def resize_swarm(session_id: str, body: dict):
    s = registry.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    if not s._swarm:
        raise HTTPException(status_code=404, detail="No swarm active")
    try:
        slots = int(body.get("slots", 3))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="slots must be an integer")
    return s._swarm.resize(slots)


@app.get("/api/sessions/{session_id}/swarm")
async def get_swarm(session_id: str):
    s = registry.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    if not s._swarm:
        return {"status": "idle"}
    return s._swarm.to_dict()


@app.get("/api/sessions/{session_id}")
async def get_session_detail(session_id: str):
    s = registry.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return s.to_dict()


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    s = registry.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    registry.remove(session_id)
    return {"ok": True}

# ─── REST: Scheduler ──────────────────────────────────────────────────────────


@app.post("/api/sessions/{session_id}/schedule")
async def set_schedule(session_id: str, body: dict):
    """Schedule auto-start at HH:MM (24h). Past today => schedules for tomorrow."""
    s = registry.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    time_str = body.get("time", "")
    now = datetime.now()
    try:
        h, m = map(int, time_str.split(":"))
        scheduled = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if scheduled <= now:
            scheduled += timedelta(days=1)
        s._scheduled_start = scheduled
        s._schedule_triggered = False
        await s.task_queue.save_schedule(scheduled.isoformat())
        in_sec = int((scheduled - now).total_seconds())
        return {"scheduled_at": scheduled.isoformat(), "in_seconds": in_sec}
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid time format. Use HH:MM (24h), e.g. 09:00")


@app.delete("/api/sessions/{session_id}/schedule")
async def cancel_schedule(session_id: str):
    s = registry.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    s._scheduled_start = None
    s._schedule_triggered = False
    await s.task_queue.save_schedule(None)
    return {"ok": True}


@app.get("/api/sessions/{session_id}/schedule")
async def get_schedule(session_id: str):
    s = registry.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    if not s._scheduled_start:
        return {"scheduled": False}
    now = datetime.now()
    return {
        "scheduled": True,
        "at": s._scheduled_start.isoformat(),
        "in_seconds": max(0, int((s._scheduled_start - now).total_seconds())),
        "triggered": s._schedule_triggered,
    }

# ─── REST: PROGRESS.md ────────────────────────────────────────────────────────


@app.post("/api/sessions/{session_id}/set-orchestrate-goal")
async def set_orchestrate_goal(session_id: str, body: dict):
    """Save goal + PROGRESS.md context to .claude/orchestrate-goal.md so the
    orchestrate skill can read it without a separate PTY message (avoids race)."""
    s = registry.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    goal = body.get("goal", "").strip()
    if not goal:
        raise HTTPException(status_code=422, detail="Goal must not be empty")

    # Build context: recent PROGRESS.md + goal
    lines = ["# Orchestrate Goal\n"]
    progress_file = s.project_dir / "PROGRESS.md"
    if progress_file.exists():
        try:
            content = progress_file.read_text(errors="replace")
            recent = content[-3000:] if len(content) > 3000 else content
            lines.append(f"## PROGRESS.md (recent lessons)\n{recent}\n---\n")
        except Exception:
            pass
    lines.append(f"## Goal\n{goal}\n")

    goal_file = s.project_dir / ".claude" / "orchestrate-goal.md"
    goal_file.parent.mkdir(parents=True, exist_ok=True)
    goal_file.write_text("".join(lines))
    return {"ok": True, "path": str(goal_file)}


@app.get("/api/sessions/{session_id}/progress-md")
async def get_progress_md(session_id: str, chars: int = 3000):
    """Return recent PROGRESS.md content for injection into orchestrate prompt."""
    s = registry.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    progress_file = s.project_dir / "PROGRESS.md"
    if not progress_file.exists():
        return {"content": ""}
    try:
        content = progress_file.read_text(errors="replace")
        return {"content": content[-chars:] if len(content) > chars else content}
    except Exception:
        return {"content": ""}

# ─── REST: Project (backward compat) ──────────────────────────────────────────


@app.get("/api/project")
async def get_project():
    s = registry.default()
    if not s:
        return {"path": str(PROJECT_DIR), "name": PROJECT_DIR.name}
    return {"path": str(s.project_dir), "name": s.name}


@app.post("/api/project")
async def switch_project(body: dict):
    path_str = body.get("path", "").strip()
    if not path_str:
        raise HTTPException(status_code=400, detail="path is required")
    new_path = Path(path_str).expanduser().resolve()
    if not new_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory not found: {new_path}")
    old = registry.default()
    if old:
        registry.remove(old.session_id)
    new_session = registry.create(str(new_path))
    await _recover_orphaned_tasks(new_session.task_queue)
    await asyncio.sleep(0.3)
    new_session.start_watch()
    return {"path": str(new_session.project_dir), "name": new_session.name}


@app.get("/api/projects")
async def list_projects(base: str | None = None):
    base_path = Path(base).expanduser() if base else None
    return await asyncio.to_thread(scan_projects, base_path)


@app.get("/")
async def root():
    return FileResponse(str(WEB_DIR / "index.html"))

# ─── WebSocket: /ws/chat ──────────────────────────────────────────────────────


@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket, session: str | None = Query(default=None)):
    await websocket.accept()
    s = registry.get(session) if session else registry.default()
    if s is None:
        await websocket.close(code=4004)
        return

    s.orchestrator.clients.append(websocket)

    if not s.orchestrator.is_alive():
        rows, cols = 24, 80
        try:
            first_data = await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
            first_msg = json.loads(first_data)
            if first_msg.get("type") == "resize":
                rows = int(first_msg.get("rows", rows))
                cols = int(first_msg.get("cols", cols))
        except Exception:
            pass
        s.orchestrator.start(s.project_dir, rows=rows, cols=cols)
        await asyncio.sleep(0.3)

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "input":
                s.orchestrator.send_input(msg.get("data", ""))
            elif msg.get("type") == "resize":
                s.orchestrator.resize(msg.get("rows", 24), msg.get("cols", 80))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("ws_chat unexpected error: %s", e)
    finally:
        if websocket in s.orchestrator.clients:
            s.orchestrator.clients.remove(websocket)

# ─── WebSocket: /ws/status ────────────────────────────────────────────────────


@app.websocket("/ws/status")
async def ws_status(websocket: WebSocket, session: str | None = Query(default=None)):
    await websocket.accept()
    s = registry.get(session) if session else registry.default()
    if s is None:
        await websocket.close(code=4004)
        return

    s.status_subscribers.append(websocket)
    s.proposed_tasks_subscribers.append(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep alive
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("ws_status unexpected error: %s", e)
    finally:
        if websocket in s.status_subscribers:
            s.status_subscribers.remove(websocket)
        if websocket in s.proposed_tasks_subscribers:
            s.proposed_tasks_subscribers.remove(websocket)

# ─── REST: Usage ──────────────────────────────────────────────────────────────


def _get_usage() -> dict:
    stats_file = Path.home() / ".claude" / "stats-cache.json"
    today_str = date.today().isoformat()
    cutoff = datetime.now() - timedelta(hours=24)

    daily: list[dict] = []
    last_updated = "?"
    total_sessions = 0

    if stats_file.exists():
        try:
            stats = json.loads(stats_file.read_text())
            last_updated = stats.get("lastComputedDate", "?")
            total_sessions = stats.get("totalSessions", 0)
            cutoff_date = (date.today() - timedelta(days=6)).isoformat()
            daily = [
                {
                    "date": e["date"],
                    "messages": e.get("messageCount", 0),
                    "sessions": e.get("sessionCount", 0),
                }
                for e in stats.get("dailyActivity", [])
                if e.get("date", "") >= cutoff_date
            ]
        except Exception:
            pass

    today_messages = 0
    today_sessions: set[str] = set()
    today_tool_calls = 0
    projects_dir = Path.home() / ".claude" / "projects"
    if projects_dir.exists():
        for jsonl_file in projects_dir.rglob("*.jsonl"):
            try:
                mtime = datetime.fromtimestamp(jsonl_file.stat().st_mtime)
                if mtime < cutoff:
                    continue
                for line in jsonl_file.read_text(errors="replace").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except Exception:
                        continue
                    ts = entry.get("timestamp", "")
                    if isinstance(ts, str) and ts[:10] != today_str:
                        continue
                    if entry.get("type") == "user":
                        today_messages += 1
                        sid = entry.get("sessionId")
                        if sid:
                            today_sessions.add(sid)
            except Exception:
                pass

    cached_today = next((e for e in daily if e["date"] == today_str), None)
    if today_messages > 0 or cached_today is None:
        today_entry = {
            "messages": today_messages,
            "sessions": len(today_sessions),
            "tool_calls": today_tool_calls,
        }
        if cached_today is None:
            daily.append({"date": today_str, "messages": today_messages, "sessions": len(today_sessions)})
    else:
        today_entry = {
            "messages": cached_today["messages"],
            "sessions": cached_today["sessions"],
            "tool_calls": 0,
        }

    week_messages = sum(e["messages"] for e in daily)
    week_sessions = sum(e["sessions"] for e in daily)

    result = {
        "today": today_entry,
        "this_week": {"messages": week_messages, "sessions": week_sessions},
        "daily": sorted(daily, key=lambda e: e["date"]),
        "last_updated": last_updated,
        "total_sessions": total_sessions,
    }

    # slt-style pace data from usage-watch cache
    pace_file = Path.home() / ".claude" / "usage-watch-cache.json"
    if pace_file.exists():
        try:
            pace_data = json.loads(pace_file.read_text())
            usage_pct = pace_data.get("usage_pct", 0)
            elapsed_pct = pace_data.get("elapsed_pct", 0)
            delta = round(usage_pct - elapsed_pct * 0.95, 1)
            remaining_d = pace_data.get("remaining_days", 0)
            # Bird theme symbols: egg/chick/bird/swan
            symbols = ["🥚", "🐣", "🐥", "🦢"]
            abs_delta = abs(delta)
            if abs_delta < 3:
                symbol = symbols[0]
            elif abs_delta < 8:
                symbol = symbols[1]
            elif abs_delta < 15:
                symbol = symbols[2]
            else:
                symbol = symbols[3]
            result["pace"] = {
                "delta": delta,
                "symbol": symbol,
                "remaining": f"{remaining_d:.1f}d" if remaining_d else "?",
                "usage_pct": round(usage_pct, 1),
                "elapsed_pct": round(elapsed_pct, 1),
            }
        except Exception:
            pass

    return result


@app.get("/api/usage")
async def get_usage():
    return await asyncio.to_thread(_get_usage)

# ─── REST: GitHub Issues Sync ─────────────────────────────────────────────────


@app.post("/api/issues/sync-pull")
async def issues_sync_pull(s: ProjectSession = Depends(_resolve_session)):
    if not GLOBAL_SETTINGS.get("github_issues_sync"):
        raise HTTPException(status_code=400, detail="GitHub Issues sync is disabled")
    result = await _gh_pull_issues(s.project_dir, s.task_queue)
    return result


@app.post("/api/issues/sync-push")
async def issues_sync_push(s: ProjectSession = Depends(_resolve_session)):
    if not GLOBAL_SETTINGS.get("github_issues_sync"):
        raise HTTPException(status_code=400, detail="GitHub Issues sync is disabled")
    result = await _gh_push_all(s.project_dir, s.task_queue)
    return result

# ─── REST: Settings ───────────────────────────────────────────────────────────


@app.get("/api/settings")
async def get_settings():
    return GLOBAL_SETTINGS


@app.post("/api/settings")
async def post_settings(body: dict = Body(...)):
    valid_keys = set(_SETTINGS_DEFAULTS.keys())
    for k, v in body.items():
        if k in valid_keys:
            GLOBAL_SETTINGS[k] = v
    snapshot = dict(GLOBAL_SETTINGS)
    await asyncio.to_thread(_save_settings, snapshot)
    return GLOBAL_SETTINGS

# ─── REST: Status ─────────────────────────────────────────────────────────────


@app.get("/api/status")
async def get_status(s: ProjectSession = Depends(_resolve_session)):
    tasks = await s.task_queue.list()
    workers = [w.to_dict() for w in s.worker_pool.all()]
    total = len(tasks)
    done = sum(1 for t in tasks if t["status"] in ("done", "failed"))
    return {
        "workers": workers,
        "queue": tasks,
        "progress_pct": int(done / total * 100) if total > 0 else 0,
        "orchestrator_alive": s.orchestrator.is_alive(),
        "session_id": s.session_id,
        "schedule": s._schedule_dict(),
    }
