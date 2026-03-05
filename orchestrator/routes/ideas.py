"""Ideas API routes for Claude Code Orchestrator."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from ideas import IdeasManager
from session import registry

logger = logging.getLogger(__name__)

# prevent fire-and-forget tasks from being GC'd (Python docs pattern)
_bg_tasks: set[asyncio.Task] = set()

router = APIRouter(prefix="/api/ideas", tags=["ideas"])


def _get_session(session_id: str | None = None):
    """Resolve and return the ProjectSession, or raise 404."""
    session = registry.get(session_id) if session_id else registry.default()
    if not session:
        raise HTTPException(status_code=404, detail="No active session")
    return session


def _get_ideas_mgr(session_id: str | None = None) -> IdeasManager:
    """Resolve session and return its IdeasManager."""
    return IdeasManager(_get_session(session_id).task_queue._db_path)


def _get_project_dir(session_id: str | None = None) -> Path | None:
    return _get_session(session_id).project_dir


# ─── Static routes (before parameterized /{idea_id}) ────────────────────────


@router.post("/sync-brainstorm")
async def sync_brainstorm(body: dict = None,
                          session: str = Query(default=None)):
    mgr = _get_ideas_mgr(session)
    project_dir = _get_project_dir(session)
    if not project_dir:
        raise HTTPException(status_code=400, detail="No project directory")
    direction = (body or {}).get("direction", "both")
    imported = 0
    exported = 0
    if direction in ("import", "both"):
        imported = await mgr.import_from_brainstorm(project_dir)
    if direction in ("export", "both"):
        exported = await mgr.sync_to_brainstorm(project_dir)
    return {"imported": imported, "exported": exported}


@router.post("/batch")
async def batch_ideas(body: dict, session: str = Query(default=None)):
    """Submit multiple ideas at once."""
    ideas_list = body.get("ideas", [])
    if not ideas_list:
        raise HTTPException(status_code=400, detail="ideas list is required")
    mgr = _get_ideas_mgr(session)
    results = []
    for item in ideas_list[:50]:  # cap at 50
        content = item if isinstance(item, str) else item.get("content", "")
        content = content.strip()
        if not content:
            continue
        source = "human" if isinstance(item, str) else item.get("source", "human")
        project = None if isinstance(item, str) else item.get("project")
        idea = await mgr.add_idea(content, source=source, project=project)
        results.append(idea)
        _create_bg_task(_eval_and_broadcast(mgr, idea["id"], session))
    return {"created": len(results), "ideas": results}


# ─── CRUD ────────────────────────────────────────────────────────────────────


@router.get("")
async def list_ideas(
    session: str = Query(default=None),
    status: str = Query(default=None),
    project: str = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    mgr = _get_ideas_mgr(session)
    return await mgr.list_ideas(status=status, project=project,
                                limit=limit, offset=offset)


@router.post("")
async def create_idea(body: dict, session: str = Query(default=None)):
    content = body.get("content", "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    mgr = _get_ideas_mgr(session)
    _ALLOWED_SOURCES = {"human", "ai", "brainstorm", "patrol"}
    source = body.get("source", "human")
    if source not in _ALLOWED_SOURCES:
        source = "human"
    project = body.get("project")
    idea = await mgr.add_idea(content, source=source, project=project)
    if body.get("auto_evaluate", True):
        _create_bg_task(_eval_and_broadcast(mgr, idea["id"], session))
    return idea


# ─── Parameterized routes ────────────────────────────────────────────────────


@router.get("/{idea_id}")
async def get_idea(idea_id: int, session: str = Query(default=None)):
    mgr = _get_ideas_mgr(session)
    idea = await mgr.get_idea(idea_id)
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")
    return idea


@router.patch("/{idea_id}")
async def update_idea(idea_id: int, body: dict,
                      session: str = Query(default=None)):
    mgr = _get_ideas_mgr(session)
    try:
        idea = await mgr.update_idea(idea_id, **body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")
    return idea


@router.delete("/{idea_id}")
async def archive_idea(idea_id: int, session: str = Query(default=None)):
    mgr = _get_ideas_mgr(session)
    idea = await mgr.archive_idea(idea_id)
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")
    return idea


@router.post("/{idea_id}/evaluate")
async def evaluate_idea(idea_id: int, session: str = Query(default=None)):
    mgr = _get_ideas_mgr(session)
    idea = await mgr.get_idea(idea_id)
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")
    _create_bg_task(_eval_and_broadcast(mgr, idea_id, session))
    return {"status": "evaluating", "idea_id": idea_id}


@router.post("/{idea_id}/messages")
async def add_message(idea_id: int, body: dict,
                      session: str = Query(default=None)):
    content = body.get("content", "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    mgr = _get_ideas_mgr(session)
    idea = await mgr.get_idea(idea_id)
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")
    msg = await mgr.discuss_idea(idea_id, content)
    _broadcast_idea_message(session, idea_id, msg)
    return msg


@router.post("/{idea_id}/promote")
async def promote_idea(idea_id: int, body: dict,
                       session: str = Query(default=None)):
    target = body.get("target", "todo")
    if target not in ("todo", "vision"):
        raise HTTPException(status_code=400, detail="target must be 'todo' or 'vision'")
    mgr = _get_ideas_mgr(session)
    project_dir = _get_project_dir(session)
    idea = await mgr.promote_idea(idea_id, target, project_dir)
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")
    return idea


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _create_bg_task(coro) -> asyncio.Task:
    """Create a background task and prevent it from being GC'd."""
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return task


async def _eval_and_broadcast(mgr: IdeasManager, idea_id: int,
                              session_id: str | None) -> None:
    """Evaluate idea and broadcast result via WebSocket."""
    try:
        idea = await mgr.evaluate_idea(idea_id)
        if idea:
            _broadcast_idea_update(session_id, idea)
    except Exception as e:
        logger.warning("_eval_and_broadcast(%s) failed: %s", idea_id, e)


def _broadcast_idea_update(session_id: str | None, idea: dict) -> None:
    """Broadcast idea update to all WebSocket status clients."""
    session = registry.get(session_id) if session_id else registry.default()
    if not session:
        return
    msg = json.dumps({
        "type": "idea_update",
        "idea_id": idea["id"],
        "status": idea["status"],
        "evaluation": idea.get("ai_evaluation_parsed"),
    })
    for ws in list(session.status_subscribers):
        try:
            asyncio.create_task(ws.send_text(msg))
        except Exception:
            pass


def _broadcast_idea_message(session_id: str | None, idea_id: int,
                            msg: dict) -> None:
    """Broadcast new idea message to WebSocket clients."""
    session = registry.get(session_id) if session_id else registry.default()
    if not session:
        return
    payload = json.dumps({
        "type": "idea_message",
        "idea_id": idea_id,
        "role": msg.get("role", "ai"),
        "content": msg.get("content", ""),
    })
    for ws in list(session.status_subscribers):
        try:
            asyncio.create_task(ws.send_text(payload))
        except Exception:
            pass
