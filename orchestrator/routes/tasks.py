"""Task CRUD and bulk-action routes."""

from __future__ import annotations

import asyncio
import logging
import shlex

from fastapi import APIRouter, Body, Depends, HTTPException

from config import (
    GLOBAL_SETTINGS,
    _ALLOWED_TASK_COLS,
    _MODEL_ALIASES,
    _deps_met,
    _fire_notification,
)
from session import ProjectSession, _resolve_session
from github_sync import _gh_create_issue
from worker_tldr import _score_task
from worker_review import _write_pr_review, _write_progress_entry

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tasks"])


@router.get("/api/tasks")
async def list_tasks(s: ProjectSession = Depends(_resolve_session)):
    return await s.task_queue.list()


@router.post("/api/tasks")
async def create_task(body: dict, s: ProjectSession = Depends(_resolve_session)):
    description = body.get("description", "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="description is required")
    task = await s.task_queue.add(
        description=description,
        model=body.get("model") or GLOBAL_SETTINGS.get("default_model", "sonnet"),
        is_critical_path=bool(body.get("is_critical_path", 0)),
    )
    asyncio.create_task(
        _score_task(task["id"], task["description"], s.task_queue._db_path, s.claude_dir)
    )
    if GLOBAL_SETTINGS.get("github_issues_sync"):
        asyncio.create_task(_gh_create_issue(task, s.project_dir, s.task_queue._db_path))
    return task


@router.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str, s: ProjectSession = Depends(_resolve_session)):
    ok = await s.task_queue.delete(task_id)
    return {"ok": ok}


@router.post("/api/tasks/import-proposed")
async def import_proposed(
    body: dict = Body(default={}),
    s: ProjectSession = Depends(_resolve_session),
):
    content = (body or {}).get("content")
    tasks, skip_counts = await s.task_queue.import_from_proposed(content=content)
    if GLOBAL_SETTINGS.get("github_issues_sync") and tasks:
        for t in tasks:
            asyncio.create_task(_gh_create_issue(t, s.project_dir, s.task_queue._db_path))
    return {"imported": len(tasks), "tasks": tasks, "skipped": skip_counts}


@router.post("/api/tasks/start-all")
async def start_all(s: ProjectSession = Depends(_resolve_session)):
    tasks = await s.task_queue.list()
    done_ids = {t["id"] for t in tasks if t["status"] == "done"}
    pending = [t for t in tasks if t["status"] in ("pending", "queued")]
    started = []
    skipped_deps = []
    # Enforce max workers limit
    max_w = GLOBAL_SETTINGS.get("max_workers", 0)
    if max_w > 0:
        running_count = sum(1 for w in s.worker_pool.all() if w.status == "running")
        available = max(0, max_w - running_count)
    else:
        available = len(pending)
    for task in pending:
        if not _deps_met(task, done_ids):
            skipped_deps.append(task["id"])
            continue
        if available <= 0:
            break
        worker = await s.worker_pool.start_worker(
            task, s.task_queue, s.project_dir, s.claude_dir
        )
        started.append({"task_id": task["id"], "worker_id": worker.id})
        available -= 1
    return {"started": len(started), "workers": started, "skipped_deps": skipped_deps}


@router.post("/api/tasks/retry-failed")
async def retry_failed(s: ProjectSession = Depends(_resolve_session)):
    """Requeue all failed tasks with their failure context injected."""
    tasks = await s.task_queue.list()
    failed = [t for t in tasks if t["status"] == "failed"]
    retried = []
    for t in failed:
        failed_reason = t.get("failed_reason", "")
        retry_desc = t["description"]
        if failed_reason:
            retry_desc += (
                f"\n\n---\n**Previous attempt failed. Error context:**\n```\n{failed_reason[:2000]}\n```\n"
                "Do NOT repeat the same approach. Analyze the error above and try a different strategy."
            )
        model = _MODEL_ALIASES.get(t.get("model", "sonnet"), t.get("model", "sonnet"))
        new_task = await s.task_queue.add(retry_desc, model)
        retried.append(new_task["id"])
    return {"retried": len(retried), "task_ids": retried}


@router.post("/api/tasks/merge-all-done")
async def merge_all_done(s: ProjectSession = Depends(_resolve_session)):
    """Create PRs for done+pushed workers. Auto-merge orchestrator branches."""
    eligible = [
        w for w in s.worker_pool.all()
        if w.status == "done" and w.auto_pushed and not w.pr_url
    ]
    results = []
    created = 0
    merged = 0
    for w in eligible:
        branch = w.branch_name or f"orchestrator/task-{w.task_id}"
        try:
            pr_proc = await asyncio.create_subprocess_shell(
                f'gh pr create --head {shlex.quote(branch)} --base main --fill',
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=str(s.project_dir),
            )
            try:
                pr_out, pr_err = await asyncio.wait_for(pr_proc.communicate(), timeout=60)
            except asyncio.TimeoutError:
                pr_proc.kill()
                await pr_proc.communicate()
                results.append({"worker_id": w.id, "error": "gh pr create timed out"})
                continue
            if pr_proc.returncode != 0:
                results.append({"worker_id": w.id, "error": pr_err.decode().strip()})
                continue
            pr_url = pr_out.decode().strip()
            w.pr_url = pr_url
            created += 1
            if GLOBAL_SETTINGS.get("auto_review", True):
                asyncio.create_task(_write_pr_review(pr_url, w.description, s.project_dir))
            if branch.startswith("orchestrator/task-") and GLOBAL_SETTINGS.get("auto_merge", True):
                merge_proc = await asyncio.create_subprocess_shell(
                    f'gh pr merge {pr_url} --squash --delete-branch',
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    cwd=str(s.project_dir),
                )
                try:
                    await asyncio.wait_for(merge_proc.communicate(), timeout=60)
                except asyncio.TimeoutError:
                    merge_proc.kill()
                    await merge_proc.communicate()
                    results.append({"worker_id": w.id, "error": "gh pr merge timed out"})
                    continue
                if merge_proc.returncode == 0:
                    w.pr_merged = True
                    merged += 1
                    asyncio.create_task(_write_progress_entry(
                        task_description=w.description,
                        log_path=w._log_path,
                        project_dir=s.project_dir,
                    ))
            results.append({"worker_id": w.id, "pr_url": pr_url})
        except Exception as e:
            logger.warning("merge_all_done worker %s failed: %s", w.id, e)
            results.append({"worker_id": w.id, "error": "PR merge failed"})
    return {"created": created, "merged": merged, "results": results}


# NOTE: This parameterized route must come AFTER all static /api/tasks/<name> routes
# (import-proposed, start-all, retry-failed, merge-all-done) or FastAPI will
# match those paths as task_id and return 404.
@router.post("/api/tasks/{task_id}")
async def update_task(task_id: str, body: dict, s: ProjectSession = Depends(_resolve_session)):
    task = await s.task_queue.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    updates = {k: v for k, v in body.items() if k in _ALLOWED_TASK_COLS}
    if not updates:
        return task
    return await s.task_queue.update(task_id, **updates)


@router.post("/api/tasks/{task_id}/retry")
async def retry_task(task_id: str, s: ProjectSession = Depends(_resolve_session)):
    """Reset an interrupted or failed task back to pending for retry."""
    task = await s.task_queue.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] not in ("interrupted", "failed"):
        return {"error": f"Task status is '{task['status']}', can only retry interrupted/failed"}
    await s.task_queue.update(
        task_id, status="pending", worker_id=None,
        started_at=None, elapsed_s=0, failed_reason=None,
    )
    return {"ok": True, "task_id": task_id}


@router.post("/api/tasks/{task_id}/run")
async def run_task(task_id: str, s: ProjectSession = Depends(_resolve_session)):
    task = await s.task_queue.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] not in ("pending", "queued"):
        return {"error": f"Task status is '{task['status']}', cannot run"}
    deps = task.get("depends_on") or []
    if deps:
        all_tasks = await s.task_queue.list()
        done_ids = {t["id"] for t in all_tasks if t["status"] == "done"}
        unmet = [d for d in deps if d not in done_ids]
        if unmet:
            return {"error": f"Blocked by unfinished dependencies: {unmet}"}
    worker = await s.worker_pool.start_worker(
        task, s.task_queue, s.project_dir, s.claude_dir
    )
    return {"worker_id": worker.id}


@router.post("/api/tasks/{task_id}/depends-on")
async def set_task_depends_on(
    task_id: str, body: dict, s: ProjectSession = Depends(_resolve_session)
):
    """Set the depends_on list for a task."""
    task = await s.task_queue.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    depends_on = body.get("depends_on", [])
    await s.task_queue.update(task_id, depends_on=depends_on)
    return {"ok": True, "depends_on": depends_on}


@router.post("/api/tasks/{task_id}/messages")
async def send_task_message(task_id: str, body: dict, s: ProjectSession = Depends(_resolve_session)):
    content = (body.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    from_task_id = body.get("from_task_id")
    msg = await s.task_queue.send_message(task_id, content, from_task_id=from_task_id)
    return msg


@router.get("/api/tasks/{task_id}/messages")
async def get_task_messages(task_id: str, s: ProjectSession = Depends(_resolve_session)):
    return await s.task_queue.get_messages(task_id, unread_only=False)
