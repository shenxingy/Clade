"""Worker control and inspection routes."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from session import ProjectSession, _resolve_session, registry
from worker_tldr import _generate_code_tldr

logger = logging.getLogger(__name__)

router = APIRouter(tags=["workers"])


@router.get("/api/workers")
async def list_workers(s: ProjectSession = Depends(_resolve_session)):
    return [w.to_dict() for w in s.worker_pool.all()]


@router.post("/api/workers/{worker_id}/pause")
async def pause_worker(worker_id: str, s: ProjectSession = Depends(_resolve_session)):
    w = s.worker_pool.get(worker_id)
    if not w:
        raise HTTPException(status_code=404, detail="Worker not found")
    w.pause()
    await s.task_queue.update(w.task_id, status="paused")
    return {"status": w.status}


@router.post("/api/workers/{worker_id}/resume")
async def resume_worker(worker_id: str, s: ProjectSession = Depends(_resolve_session)):
    w = s.worker_pool.get(worker_id)
    if not w:
        raise HTTPException(status_code=404, detail="Worker not found")
    w.resume()
    await s.task_queue.update(w.task_id, status="running")
    return {"status": w.status}


@router.post("/api/workers/{worker_id}/message")
async def message_worker(
    worker_id: str, body: dict, s: ProjectSession = Depends(_resolve_session)
):
    w = s.worker_pool.get(worker_id)
    if not w:
        raise HTTPException(status_code=404, detail="Worker not found")
    user_message = body.get("message", "")
    original_desc = w.description
    failure_ctx = w.failure_context or ""
    await w.stop()
    new_desc = f"{original_desc}\n\n---\n**Additional context from user:**\n{user_message}"
    new_task = await s.task_queue.add(new_desc, w.model)
    # Record intervention for future auto-injection
    try:
        if failure_ctx:
            await s.task_queue.record_intervention(
                failure_pattern=failure_ctx,
                correction=user_message,
                task_description_hint=original_desc[:200],
                source_task_id=w.task_id,
                spawned_task_id=new_task["id"],
            )
    except Exception:
        pass
    new_worker = await s.worker_pool.start_worker(
        new_task, s.task_queue, s.project_dir, s.claude_dir
    )
    return {"new_worker_id": new_worker.id, "new_task_id": new_task["id"]}


@router.post("/api/sessions/{session_id}/workers/broadcast")
async def broadcast_to_workers(session_id: str, body: dict):
    session = registry.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    message = body.get("message", "").strip()
    if not message:
        return {"error": "message required"}
    sent_to = []
    for worker in list(session.worker_pool.workers.values()):
        if worker.status == "running":
            original_desc = worker.description
            await worker.stop()
            new_desc = f"{original_desc}\n\n---\n**Broadcast message:** {message}"
            new_task = await session.task_queue.add(new_desc, worker.model)
            await session.worker_pool.start_worker(
                new_task, session.task_queue, session.project_dir, session.claude_dir
            )
            sent_to.append(worker.id)
    return {"sent_to": sent_to, "count": len(sent_to)}


@router.get("/api/sessions/{session_id}/agents-md")
async def get_agents_md(session_id: str):
    session = registry.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "log", "--name-only", "--format=%D", "--max-count=200",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            cwd=str(session.project_dir),
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
    except Exception as e:
        logger.warning("get_agents_md git error: %s", e)
        return {"agents_md": "# File Ownership\n\n(error generating map)\n"}
    file_to_branch: dict[str, str] = {}
    current_branch = "main"
    for line in out.decode(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        if "orchestrator/task-" in line:
            for part in line.split(","):
                part = part.strip()
                if "orchestrator/task-" in part:
                    current_branch = part.replace("HEAD -> ", "").replace("origin/", "").strip()
                    break
        elif ("/" in line or "." in line) and current_branch not in ("main", "HEAD"):
            file_to_branch.setdefault(line, current_branch)
    branch_files: dict[str, list[str]] = {}
    for f, b in file_to_branch.items():
        branch_files.setdefault(b, []).append(f)
    out_lines = ["# File Ownership", ""]
    for branch, files in sorted(branch_files.items()):
        out_lines.append(f"### {branch}")
        for f in sorted(files)[:15]:
            out_lines.append(f"- owns: {f}")
        out_lines.append("")
    if not branch_files:
        out_lines.append("No branch-specific ownership detected.")
    return {"agents_md": "\n".join(out_lines)}


@router.get("/api/sessions/{session_id}/code-tldr")
async def get_code_tldr(session_id: str):
    session = registry.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        tldr = await asyncio.to_thread(
            _generate_code_tldr, str(session.project_dir)
        )
    except Exception as e:
        logger.warning("code-tldr generation failed: %s", e)
        tldr = "(error generating code TLDR)"
    return {"tldr": tldr or "(no code files found)"}


@router.get("/api/interventions")
async def list_interventions(s: ProjectSession = Depends(_resolve_session)):
    return await s.task_queue.list_interventions()


@router.get("/api/workers/{worker_id}/log")
async def get_worker_log(
    worker_id: str, lines: int = 100, s: ProjectSession = Depends(_resolve_session)
):
    lines = min(lines, 5000)
    w = s.worker_pool.get(worker_id)
    if not w:
        raise HTTPException(status_code=404, detail="Worker not found")
    if not w._log_path or not w._log_path.exists():
        return {"log": ""}
    try:
        text = w._log_path.read_text(errors="replace")
        tail = "\n".join(text.splitlines()[-lines:])
        return {"log": tail, "path": str(w._log_path)}
    except Exception as e:
        logger.warning("get_worker_log read error: %s", e)
        return {"log": "Error reading log"}
