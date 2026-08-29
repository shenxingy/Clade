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
from merge_policy import enabled_merge_methods
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


# ─── Repo Invariants Preflight (domdomegg) ────────────────────────────────────

_STATUS_LABELS = ("pending", "running", "done", "failed")


async def _run_gh(cmd: str, project_dir: Path, timeout: int = 20) -> tuple[int, str, str]:
    """Run a gh command. Returns (returncode, stdout, stderr); rc=-1 with the
    failure reason in stderr on timeout/spawn errors — callers stay fail-open."""
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(project_dir),
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return -1, "", "timeout"
        return proc.returncode or 0, out.decode(), err.decode()
    except Exception as e:  # gh missing, fork failure, …
        return -1, "", str(e)


async def ensure_repo_invariants(
    project_dir: Path, *, ensure_labels: bool = True, check_merge: bool = True
) -> dict:
    """Preflight the GitHub-facing invariants the orchestrator relies on.

    - ensure_labels: `gh label create --force` for the orchestrator label +
      pending/running/done/failed (idempotent). Without these, Issues sync is
      silently DOA on fresh repos — every fail-open label call returns None.
    - check_merge: inspect viewer permission and every enabled history method
      so missing authority or an unmergeable repository surfaces before a run.

    Fail-open by design: every gh failure lands in findings["warnings"] with a
    logged warning, never raised. On machines without gh auth or network this
    is a harmless no-op that only records warnings.
    """
    findings: dict = {
        "labels_ensured": [], "warnings": [],
        "viewer_permission": None, "merge_methods_allowed": [],
    }
    if ensure_labels:
        for label in (_gh_label(), *_STATUS_LABELS):
            rc, _out, err = await _run_gh(
                f'gh label create {shlex.quote(label)} --force', project_dir
            )
            if rc == 0:
                findings["labels_ensured"].append(label)
            else:
                findings["warnings"].append(
                    f"label '{label}': {err.strip()[:120] or 'gh failed'}"
                )
    if check_merge:
        rc, out, err = await _run_gh(
            "gh repo view --json viewerPermission,mergeCommitAllowed,"
            "rebaseMergeAllowed,squashMergeAllowed",
            project_dir,
        )
        if rc != 0:
            findings["warnings"].append(
                f"gh repo view: {err.strip()[:120] or 'gh failed'}"
            )
        else:
            try:
                data = json.loads(out)
                findings["viewer_permission"] = data.get("viewerPermission")
                findings["merge_methods_allowed"] = sorted(
                    enabled_merge_methods(data)
                )
                if findings["viewer_permission"] not in ("WRITE", "MAINTAIN", "ADMIN"):
                    findings["warnings"].append(
                        f"viewerPermission={findings['viewer_permission']} — push/merge will fail"
                    )
                if not findings["merge_methods_allowed"]:
                    findings["warnings"].append(
                        "repository has no enabled pull-request merge method"
                    )
            except Exception:
                findings["warnings"].append("gh repo view returned unparseable JSON")
    for warning in findings["warnings"]:
        logger.warning("repo invariants preflight: %s", warning)
    return findings


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
            # The timeout says we stopped waiting, not that GitHub did nothing.
            # Look for an issue carrying this task's id before giving up, or the
            # next push creates a second one for the same task.
            return await _gh_find_issue_by_task_id(task["id"], project_dir, db_path)
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


async def _gh_find_issue_by_task_id(
    task_id: str, project_dir: Path, db_path: str | Path
) -> int | None:
    """Find an issue this orchestrator already created for `task_id`.

    Used only to recover from a create that timed out locally. Searches the
    body text for the id stamped by `_format_issue_body`, then re-binds it so
    the next push updates that issue instead of opening another.
    """
    try:
        cmd = (
            f"gh issue list --search {shlex.quote(task_id)} --state all "
            f"--limit 20 --json number,body"
        )
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            cwd=str(project_dir),
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            return None
        for issue in json.loads(out.decode() or "[]"):
            meta, _desc = _parse_issue_body(issue.get("body") or "")
            if meta.get("task_id") == task_id:
                num = int(issue["number"])
                async with aiosqlite.connect(str(db_path)) as db:
                    await db.execute(
                        "UPDATE tasks SET gh_issue_number = ? WHERE id = ?", (num, task_id)
                    )
                    await db.commit()
                logger.info("recovered orphaned issue #%s for task %s", num, task_id)
                return num
    except Exception:
        logger.exception("issue recovery lookup failed for task %s", task_id)
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
        logger.warning("gh_pull_issues failed: %s", e)
        return {"error": "GitHub sync failed"}

    stats = {"created": 0, "updated": 0, "deleted": 0, "skipped": 0, "adopted": 0}
    local_tasks = await task_queue.list()
    by_issue = {t["gh_issue_number"]: t for t in local_tasks if t.get("gh_issue_number")}
    # `_format_issue_body` stamps the task id into every issue body, and until
    # 2026-08-29 nothing ever read it back — `grep -n task_id` on this file
    # returned exactly one hit. That made the issue NUMBER the only join key,
    # and `_gh_create_issue` returns None on its 30s timeout AFTER GitHub may
    # already have created the issue. The task then keeps gh_issue_number NULL,
    # the next pull sees an unowned issue, invents a second task, and the next
    # push gives that one its own issue. One timeout, a growing pair of
    # duplicates. Reconciling on the id we wrote closes the loop.
    by_task_id = {t["id"]: t for t in local_tasks}

    for issue in issues:
        num = issue["number"]
        meta, desc = _parse_issue_body(issue.get("body") or "")
        is_closed = issue.get("state", "").upper() == "CLOSED"

        if num not in by_issue:
            orphan = by_task_id.get(meta.get("task_id"))
            if orphan is not None and not orphan.get("gh_issue_number"):
                # This issue is ours; we just lost the receipt.
                await task_queue.update(orphan["id"], gh_issue_number=num)
                orphan["gh_issue_number"] = num
                by_issue[num] = orphan
                stats["adopted"] += 1

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
    stats: dict[str, Any] = {"created": 0, "updated": 0, "errors": []}
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
