"""Process management API routes for Claude Code Orchestrator."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from process_manager import process_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/processes", tags=["processes"])


@router.get("")
async def list_processes():
    """List all tracked start.sh processes."""
    return process_pool.to_list()


@router.post("")
async def start_process(body: dict):
    """Start a new start.sh process for a project."""
    project_dir = body.get("project_dir", "").strip()
    if not project_dir:
        raise HTTPException(status_code=400, detail="project_dir is required")
    path = Path(project_dir).expanduser().resolve()
    if not path.is_dir():
        raise HTTPException(status_code=400, detail="project_dir does not exist")

    _ALLOWED_MODES = {"--run", "--morning", "--patrol", "--goal"}
    mode = body.get("mode", "--run")
    if mode not in _ALLOWED_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid mode. Allowed: {sorted(_ALLOWED_MODES)}")
    args = []
    if body.get("budget"):
        try:
            args += ["--budget", str(int(body["budget"]))]
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="budget must be a number")
    if body.get("hours"):
        try:
            args += ["--hours", str(int(body["hours"]))]
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="hours must be a number")
    if body.get("goal"):
        goal = str(body["goal"]).strip()
        if len(goal) > 500:
            raise HTTPException(status_code=400, detail="goal too long (max 500 chars)")
        args += ["--goal", goal]

    proc = await process_pool.start(path, mode=mode, args=args)
    return proc.to_dict()


@router.delete("/{project_dir:path}")
async def stop_process(project_dir: str):
    """Stop a running start.sh process."""
    success = await process_pool.stop(project_dir)
    if not success:
        raise HTTPException(status_code=404, detail="Process not found")
    return {"status": "stopped", "project_dir": project_dir}


@router.get("/{project_dir:path}/report")
async def get_report(project_dir: str):
    """Get latest session report for a project."""
    proc = process_pool.get(project_dir)
    if not proc:
        raise HTTPException(status_code=404, detail="Process not found")
    report = proc.read_report()
    return {"project_dir": project_dir, "report": report}


@router.get("/{project_dir:path}/progress")
async def get_progress(project_dir: str):
    """Get live progress for a running process."""
    proc = process_pool.get(project_dir)
    if not proc:
        raise HTTPException(status_code=404, detail="Process not found")
    progress = proc.read_progress()
    return {"project_dir": project_dir, "progress": progress,
            "status": proc.status, "cost": proc.read_cost()}
