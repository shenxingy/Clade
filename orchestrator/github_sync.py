"""
Orchestrator GitHub sync — Issue create/update/pull/push via gh CLI.
Leaf module: imported by worker.py. No internal deps except config + task_queue.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shlex
from pathlib import Path
from typing import Any

import aiosqlite

from config import GLOBAL_SETTINGS
from task_queue import TaskQueue

logger = logging.getLogger(__name__)

# ─── GitHub Issues Sync ───────────────────────────────────────────────────────


def _format_issue_body(task: dict) -> str:
    """Encode task metadata in HTML comment + description body."""
    meta: dict[str, Any] = {"task_id": task["id"], "model": task.get("model", "sonnet")}
    if task.get("own_files"):
        meta["own_files"] = task["own_files"]
    if task.get("forbidden_files"):
        meta["forbidden_files"] = task["forbidden_files"]
    if task.get("depends_on"):
        meta["depends_on"] = task["depends_on"]
    return f"<!-- orchestrator-meta\n{json.dumps(meta, indent=2)}\n-->\n\n{task['description']}"


def _parse_issue_body(body: str) -> tuple[dict, str]:
    """Extract (metadata_dict, description) from issue body."""
    m = re.search(r'<!-- orchestrator-meta\n(.*?)\n-->', body, re.DOTALL)
    if m:
        try:
            meta = json.loads(m.group(1))
        except Exception:
            meta = {}
        desc = body[m.end():].strip()
        return meta, desc
    return {}, body.strip()


def _gh_label() -> str:
    return GLOBAL_SETTINGS.get("github_issues_label", "orchestrator")


async def _gh_create_issue(task: dict, project_dir: Path, db_path: Path) -> int | None:
    """Create GitHub Issue from task. Returns issue number or None."""
    if not GLOBAL_SETTINGS.get("github_issues_sync"):
        return None
    label = _gh_label()
    first_line = (task["description"].splitlines()[0][:120]) if task["description"] else "Orchestrator task"
    body = _format_issue_body(task)
    cmd = (
        f'gh issue create --title {shlex.quote(first_line)} '
        f'--body {shlex.quote(body)} '
        f'--label {shlex.quote(label + ",pending")}'
    )
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(project_dir),
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return None
        if proc.returncode != 0:
            logger.warning("gh issue create failed: %s", err.decode()[:200])
            return None
        # stdout is the issue URL, e.g. https://github.com/owner/repo/issues/42
        url = out.decode().strip()
        m = re.search(r'/issues/(\d+)', url)
        if not m:
            return None
        issue_num = int(m.group(1))
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("UPDATE tasks SET gh_issue_number = ? WHERE id = ?", (issue_num, task["id"]))
            await db.commit()
        return issue_num
    except Exception as e:
        logger.warning("gh issue create error: %s", e)
        return None


async def _gh_update_issue_status(task: dict, project_dir: Path) -> bool:
    """Update issue labels/state to match task status."""
    if not GLOBAL_SETTINGS.get("github_issues_sync"):
        return False
    num = task.get("gh_issue_number")
    if not num:
        return False
    label = _gh_label()
    status = task.get("status", "pending")
    try:
        if status in ("done", "failed"):
            status_label = "done" if status == "done" else "failed"
            cmd = (
                f'gh issue close {num} && '
                f'gh issue edit {num} '
                f'--add-label {shlex.quote(status_label)} '
                f'--remove-label pending,running'
            )
        elif status == "running":
            cmd = (
                f'gh issue edit {num} '
                f'--add-label running '
                f'--remove-label pending'
            )
        else:
            return False
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            cwd=str(project_dir),
        )
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return False
        if proc.returncode != 0:
            logger.warning("gh issue update failed for #%s: %s", num, err.decode()[:200])
        return proc.returncode == 0
    except Exception as e:
        logger.warning("gh issue update error: %s", e)
        return False


async def _gh_pull_issues(project_dir: Path, task_queue: TaskQueue) -> dict:
    """Fetch orchestrator-labeled issues, sync to local DB."""
    label = _gh_label()
    cmd = (
        f'gh issue list --label {shlex.quote(label)} --state all '
        f'--json number,title,body,state,labels --limit 200'
    )
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(project_dir),
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return {"error": "timeout"}
        if proc.returncode != 0:
            return {"error": err.decode()[:200]}
        issues = json.loads(out.decode())
    except Exception as e:
        return {"error": str(e)}

    stats = {"created": 0, "updated": 0, "deleted": 0, "skipped": 0}
    local_tasks = await task_queue.list()
    by_issue = {t["gh_issue_number"]: t for t in local_tasks if t.get("gh_issue_number")}

    for issue in issues:
        num = issue["number"]
        meta, desc = _parse_issue_body(issue.get("body") or "")
        is_closed = issue.get("state", "").upper() == "CLOSED"

        if num in by_issue:
            local = by_issue[num]
            if is_closed and local["status"] == "pending":
                await task_queue.delete(local["id"])
                stats["deleted"] += 1
            elif not is_closed and local["status"] == "pending" and desc and desc != local["description"]:
                await task_queue.update(local["id"], description=desc)
                stats["updated"] += 1
            else:
                stats["skipped"] += 1
        else:
            if not is_closed:
                title = issue.get("title", "")
                description = desc or title
                model = meta.get("model", GLOBAL_SETTINGS.get("default_model", "sonnet"))
                own_files = meta.get("own_files")
                forbidden_files = meta.get("forbidden_files")
                task = await task_queue.add(
                    description=description, model=model,
                    own_files=own_files, forbidden_files=forbidden_files,
                )
                await task_queue.update(task["id"], gh_issue_number=num)
                stats["created"] += 1
            else:
                stats["skipped"] += 1

    return stats


async def _gh_push_all(project_dir: Path, task_queue: TaskQueue) -> dict:
    """Push all local tasks to GitHub Issues."""
    stats = {"created": 0, "updated": 0, "errors": []}
    tasks = await task_queue.list()
    db_path = task_queue._db_path

    for task in tasks:
        if task.get("gh_issue_number"):
            ok = await _gh_update_issue_status(task, project_dir)
            if ok:
                stats["updated"] += 1
        else:
            num = await _gh_create_issue(task, project_dir, db_path)
            if num:
                stats["created"] += 1
            else:
                stats["errors"].append(task["id"])

    return stats
