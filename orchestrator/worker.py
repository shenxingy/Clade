"""
Orchestrator worker — execution engine.
Worker, WorkerPool, SwarmManager + code_tldr, scoring, oracle, github sync.
"""

from __future__ import annotations

import ast
import asyncio
import fnmatch
import json
import logging
import os
import re
import shlex
import signal
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import aiosqlite

from config import (
    GLOBAL_SETTINGS,
    _MODEL_ALIASES,
    _estimate_cost,
    _parse_token_usage,
)
from task_queue import TaskQueue

logger = logging.getLogger(__name__)

# ─── Semantic Code TLDR ──────────────────────────────────────────────────────

_tldr_cache: dict[str, tuple[float, str]] = {}  # dir -> (max_mtime, tldr_text)

_SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", "dist", "build",
              ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache", ".next", ".nuxt"}


def _python_func_sig(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    params = []
    for a in node.args.args:
        p = a.arg
        if a.annotation:
            try:
                p += f": {ast.unparse(a.annotation)}"
            except Exception:
                pass
        params.append(p)
    ret = ""
    if node.returns:
        try:
            ret = f" -> {ast.unparse(node.returns)}"
        except Exception:
            pass
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({', '.join(params)}){ret}"


def _parse_python_ast(source: str) -> list[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    results = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            bases = []
            for b in node.bases:
                try:
                    bases.append(ast.unparse(b))
                except Exception:
                    pass
            base_str = f"({', '.join(bases)})" if bases else ""
            results.append(f"class {node.name}{base_str}")
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    results.append(f"  {_python_func_sig(item)}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            results.append(_python_func_sig(node))
    return results


_JS_PATTERNS = [
    re.compile(r'^\s*(?:export\s+)?class\s+(\w+)'),
    re.compile(r'^\s*(?:export\s+)?(?:async\s+)?function\s+(\w[\w$]*)'),
    re.compile(r'^\s*(?:export\s+)?(?:const|let|var)\s+(\w[\w$]*)\s*=\s*(?:async\s+)?\('),
    re.compile(r'^\s*(?:export\s+default\s+)?(?:async\s+)?function\s*\('),
]


def _parse_js_ts_regex(source: str) -> list[str]:
    results = []
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("/*"):
            continue
        for pat in _JS_PATTERNS:
            m = pat.match(line)
            if m:
                # Trim to reasonable length
                sig = stripped[:120]
                if sig.endswith("{"):
                    sig = sig[:-1].rstrip()
                results.append(sig)
                break
    return results


def _generate_code_tldr(project_dir: str) -> str:
    root = Path(project_dir)
    if not root.is_dir():
        return ""

    # Check mtime-based cache
    max_mtime = 0.0
    files_to_scan: list[tuple[Path, str]] = []  # (path, ext)
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
            for fname in filenames:
                ext = Path(fname).suffix.lower()
                if ext in (".py", ".js", ".ts", ".tsx", ".jsx"):
                    fpath = Path(dirpath) / fname
                    try:
                        mt = fpath.stat().st_mtime
                        if mt > max_mtime:
                            max_mtime = mt
                        files_to_scan.append((fpath, ext))
                    except OSError:
                        pass
    except OSError:
        return ""

    cached = _tldr_cache.get(project_dir)
    if cached and cached[0] >= max_mtime:
        return cached[1]

    lines: list[str] = []
    for fpath, ext in sorted(files_to_scan, key=lambda x: str(x[0])):
        try:
            source = fpath.read_text(errors="replace")
        except OSError:
            continue
        rel = str(fpath.relative_to(root))
        if ext == ".py":
            sigs = _parse_python_ast(source)
        else:
            sigs = _parse_js_ts_regex(source)
        if sigs:
            lines.append(f"## {rel}")
            lines.extend(sigs)
            lines.append("")

    result = "\n".join(lines)
    if len(result) > 3000:
        result = result[:3000] + "\n... (truncated)"
    _tldr_cache[project_dir] = (max_mtime, result)
    return result

# ─── Scout Readiness Scoring ──────────────────────────────────────────────────


async def _score_task(task_id: str, description: str, db_path: Path, claude_dir: Path) -> None:
    """Background: score a task's autonomous-readiness using haiku (0-100)."""
    score_prompt = (
        "Score this task's readiness for autonomous execution by an AI agent (0-100):\n"
        "- 0-49: Needs clarification (vague goal, missing context, ambiguous scope)\n"
        "- 50-79: Acceptable (some uncertainty but workable with reasonable assumptions)\n"
        "- 80-100: Ready (clear, specific, self-contained, no ambiguity)\n\n"
        f"Task description:\n{description[:600]}\n\n"
        'Respond ONLY with a JSON object, no other text: {"score": <integer>, "note": "<max 12 words>"}'
    )
    score_file = claude_dir / f"score-{task_id}.md"
    try:
        score_file.write_text(score_prompt)
        proc = await asyncio.create_subprocess_shell(
            f'claude -p "$(cat {shlex.quote(str(score_file))})" --model claude-haiku-4-5-20251001 --dangerously-skip-permissions',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
            result = out.decode().strip()
            m = re.search(r'\{[^}]+\}', result)
            if m:
                data = json.loads(m.group())
                score = max(0, min(100, int(data.get("score", 50))))
                note = str(data.get("note", ""))[:100]
                async with aiosqlite.connect(str(db_path)) as db:
                    await db.execute(
                        "UPDATE tasks SET score = ?, score_note = ? WHERE id = ?",
                        (score, note, task_id),
                    )
                    await db.commit()
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()  # drain stdout/stderr
            out = b""
        except Exception:
            pass
    finally:
        score_file.unlink(missing_ok=True)

# ─── Progress / PR Review / Oracle ────────────────────────────────────────────


async def _write_progress_entry(
    task_description: str, log_path: Path | None, project_dir: Path
) -> None:
    """After merge: summarize worker log and append a lesson entry to PROGRESS.md."""
    title = task_description.splitlines()[0][:80] if task_description else "Unknown task"
    log_tail = ""
    if log_path and log_path.exists():
        try:
            text = log_path.read_text(errors="replace")
            log_tail = "\n".join(text.splitlines()[-80:])
        except Exception:
            pass

    prompt = (
        f"A Claude Code worker completed this task:\n**{title}**\n\n"
        f"Last 80 lines of worker log:\n```\n{log_tail}\n```\n\n"
        "Write a concise PROGRESS.md entry (2-4 bullet points) in this exact format:\n"
        f"### [{date.today().isoformat()}] Task: {title}\n"
        "- What worked: [1 sentence]\n"
        "- Watch out for: [1 sentence]\n\n"
        "RESPOND WITH ONLY the markdown entry, no preamble."
    )
    try:
        proc = await asyncio.create_subprocess_shell(
            f'claude -p {shlex.quote(prompt)} --model claude-haiku-4-5-20251001',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()  # drain stdout/stderr
            out = b""
        entry = out.decode().strip()
        if entry:
            progress_file = project_dir / "PROGRESS.md"
            existing = await asyncio.to_thread(progress_file.read_text, errors="replace") if progress_file.exists() else "# Progress Log\n"
            lines = existing.splitlines(keepends=True)
            insert_at = 1 if lines and lines[0].startswith("#") else 0
            lines.insert(insert_at, f"\n{entry}\n")
            await asyncio.to_thread(progress_file.write_text, "".join(lines))
    except Exception:
        pass  # non-critical — don't break the merge flow


async def _write_pr_review(pr_url: str, task_description: str, project_dir: Path) -> None:
    """After PR creation: generate AI review and post as PR comment."""
    title = task_description.splitlines()[0][:80] if task_description else "Unknown task"
    try:
        diff_proc = await asyncio.create_subprocess_shell(
            f'gh pr diff {shlex.quote(pr_url)}',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(project_dir),
        )
        try:
            diff_out, _ = await asyncio.wait_for(diff_proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            diff_proc.kill()
            await diff_proc.communicate()  # drain stdout/stderr
            diff_out = b""
        diff_text = diff_out.decode()[:4000]

        prompt = (
            f"Review this PR for the task: **{title}**\n\n"
            f"Diff:\n```diff\n{diff_text}\n```\n\n"
            "Write a brief code review (3-5 bullet points):\n"
            "- **Summary**: what changed\n"
            "- **Correctness**: does it solve the task?\n"
            "- **Risks**: any concerns or edge cases?\n"
            "RESPOND WITH ONLY the review markdown, no preamble."
        )
        review_proc = await asyncio.create_subprocess_shell(
            f'claude -p {shlex.quote(prompt)} --model claude-haiku-4-5-20251001',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            review_out, _ = await asyncio.wait_for(review_proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            review_proc.kill()
            await review_proc.communicate()  # drain stdout/stderr
            review_out = b""
        review_text = review_out.decode().strip()

        if review_text:
            comment_proc = await asyncio.create_subprocess_shell(
                f'gh pr comment {shlex.quote(pr_url)} --body {shlex.quote(review_text)}',
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=str(project_dir),
            )
            try:
                await asyncio.wait_for(comment_proc.communicate(), timeout=30)
            except asyncio.TimeoutError:
                comment_proc.kill()
                await comment_proc.communicate()  # drain stdout/stderr
    except Exception:
        pass  # non-critical


async def _oracle_review(task_description: str, diff_text: str, claude_dir: Path) -> tuple[bool, str]:
    """Independent second-model review of a diff. Returns (approved, reason). Fails open."""
    prompt = (
        "You are an independent code reviewer with no prior context.\n"
        "Review the diff and task description. Output ONLY one of:\n"
        "  APPROVED: <one-line reason>\n"
        "  REJECTED: <one-line reason>\n\n"
        f"Task: {task_description[:400]}\n\nDiff:\n{diff_text[:3000]}"
    )
    prompt_file = claude_dir / f"oracle-{uuid.uuid4().hex[:8]}.md"
    try:
        prompt_file.write_text(prompt)
        proc = await asyncio.create_subprocess_shell(
            f'claude -p "$(cat {shlex.quote(str(prompt_file))})" '
            f'--model claude-haiku-4-5-20251001 --dangerously-skip-permissions',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()  # drain stdout/stderr
            out = b""
        result = out.decode().strip()
        approved = result.startswith("APPROVED")
        reason = result.split(":", 1)[-1].strip()[:80] if ":" in result else result[:80]
        return approved, reason
    except Exception as e:
        return True, f"oracle error: {e}"
    finally:
        prompt_file.unlink(missing_ok=True)

# ─── GitHub Issues Sync ──────────────────────────────────────────────────────


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
            # Close the issue + update labels
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
            # Closed on GitHub + local pending → delete local task
            if is_closed and local["status"] == "pending":
                await task_queue.delete(local["id"])
                stats["deleted"] += 1
            # Open + local pending + body changed → update description
            elif not is_closed and local["status"] == "pending" and desc and desc != local["description"]:
                await task_queue.update(local["id"], description=desc)
                stats["updated"] += 1
            else:
                stats["skipped"] += 1
        else:
            # No local match — if open, create local task
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
            # not counting failures as errors — silent skip
        else:
            num = await _gh_create_issue(task, project_dir, db_path)
            if num:
                stats["created"] += 1
            else:
                stats["errors"].append(task["id"])

    return stats

# ─── Worker ───────────────────────────────────────────────────────────────────


class Worker:
    def __init__(
        self,
        task_id: str,
        description: str,
        model: str,
        project_dir: Path,
        claude_dir: Path,
    ):
        self.id = str(uuid.uuid4())[:8]
        self.task_id = task_id
        self.description = description
        self.model = model
        self._project_dir = project_dir
        self._original_project_dir = project_dir  # preserved for restore after worktree cleanup
        self._claude_dir = claude_dir
        self.proc: asyncio.subprocess.Process | None = None
        self.pgid: int | None = None
        self.pid: int | None = None
        self.started_at = time.time()
        self._finished_at: float | None = None
        self.status = "starting"  # starting/running/paused/blocked/done/failed
        self.last_commit: str | None = None
        self.log_file: str | None = None
        self._log_path: Path | None = None
        self.verified: bool = False
        self.auto_committed: bool = False
        self.auto_pushed: bool = False
        self.oracle_result: str | None = None
        self.oracle_reason: str | None = None
        self._oracle_requeue: bool = False
        self._oracle_requeue_reason: str | None = None
        self._handoff_requeue: bool = False
        self._handoff_content: str | None = None
        self.model_score: int | None = None
        self.branch_name: str | None = None
        self.pr_url: str | None = None
        self.pr_merged: bool = False
        self._verify_triggered: bool = False
        self.task_timeout: int = 600  # default 10 min
        self.failure_context: str | None = None
        self._worktree_path: Path | None = None
        self._branch_name: str | None = None
        self.own_files: list[str] = []
        self.forbidden_files: list[str] = []
        self._ownership_violation: bool = False
        self._ownership_violation_reason: str | None = None
        self._stuck_detected: bool = False
        self._terminal_persisted: bool = False
        self._input_tokens: int = 0
        self._output_tokens: int = 0
        self._estimated_cost: float = 0.0

    @property
    def elapsed_s(self) -> int:
        return int((self._finished_at or time.time()) - self.started_at)

    def to_dict(self) -> dict:
        log_tail = ""
        if self._log_path and self._log_path.exists():
            try:
                text = self._log_path.read_text(errors="replace")
                non_empty = [l for l in text.splitlines() if l.strip()]
                log_tail = "\n".join(non_empty[-4:])
            except Exception:
                pass
        return {
            "id": self.id,
            "task_id": self.task_id,
            "description": self.description[:80],
            "model": self.model,
            "status": self.status,
            "pid": self.pid,
            "elapsed_s": self.elapsed_s,
            "last_commit": self.last_commit,
            "log_file": self.log_file,
            "verified": self.verified,
            "auto_committed": self.auto_committed,
            "auto_pushed": self.auto_pushed,
            "branch_name": self.branch_name,
            "pr_url": self.pr_url,
            "pr_merged": self.pr_merged,
            "log_tail": log_tail,
            "failure_context": self.failure_context,
            "worktree_path": str(self._worktree_path) if self._worktree_path else None,
            "oracle_result": self.oracle_result,
            "oracle_reason": self.oracle_reason,
            "model_score": self.model_score,
            "estimated_tokens": self._estimate_tokens(),
            "context_warning": self._estimate_tokens() > 160000,
            "input_tokens": self._input_tokens,
            "output_tokens": self._output_tokens,
            "estimated_cost": self._estimated_cost,
        }

    def _estimate_tokens(self) -> int:
        desc_tokens = len(self.description) // 4
        log_tokens = 0
        if self._log_path and self._log_path.exists():
            try:
                log_tokens = self._log_path.stat().st_size // 4
            except Exception:
                pass
        return desc_tokens + log_tokens

    async def start(self, task_queue: TaskQueue | None = None) -> None:
        # Create isolated git worktree for this worker
        worktree_base = self._claude_dir / "worktrees"
        worktree_base.mkdir(parents=True, exist_ok=True)
        self._worktree_path = worktree_base / f"worker-{self.id}"
        self._branch_name = f"orchestrator/task-{self.task_id}"

        wt_proc = await asyncio.create_subprocess_exec(
            "git", "worktree", "add", str(self._worktree_path), "-b", self._branch_name,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(self._project_dir),
        )
        try:
            wt_out, wt_err = await asyncio.wait_for(wt_proc.communicate(), timeout=30)
            if wt_proc.returncode == 0:
                self._project_dir = self._worktree_path
            else:
                try:
                    wt_proc2 = await asyncio.create_subprocess_exec(
                        "git", "worktree", "add", str(self._worktree_path), self._branch_name,
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                        cwd=str(self._project_dir),
                    )
                    try:
                        await asyncio.wait_for(wt_proc2.communicate(), timeout=30)
                    except asyncio.TimeoutError:
                        wt_proc2.kill()
                        await wt_proc2.communicate()
                    if wt_proc2.returncode == 0:
                        self._project_dir = self._worktree_path
                    else:
                        self._worktree_path = None
                except Exception:
                    self._worktree_path = None
        except asyncio.TimeoutError:
            wt_proc.kill()
            await wt_proc.communicate()
            # Fall through to wt_proc2 retry or failure handling
            self._worktree_path = None
        except Exception:
            self._worktree_path = None

        logs = self._claude_dir / "orchestrator-logs"
        logs.mkdir(parents=True, exist_ok=True)
        self._log_path = logs / f"worker-{self.id}.log"
        self.log_file = str(self._log_path)

        task_file = self._claude_dir / f"task-{self.id}.md"
        task_file.parent.mkdir(parents=True, exist_ok=True)

        # Prepend project CLAUDE.md + AGENTS.md for context injection
        effective_description = self.description
        context_blocks = []
        claude_md = self._claude_dir / "CLAUDE.md"
        if claude_md.exists():
            try:
                claude_content = claude_md.read_text(errors="replace").strip()
                if claude_content:
                    context_blocks.append(f"# Project Context (from .claude/CLAUDE.md)\n\n{claude_content}")
            except Exception:
                pass
        agents_md = self._claude_dir / "AGENTS.md"
        if not agents_md.exists():
            agents_md = self._project_dir / "AGENTS.md"
        if agents_md.exists():
            try:
                agents_content = agents_md.read_text(errors="replace").strip()
                if agents_content:
                    context_blocks.append(f"# File Ownership (from AGENTS.md)\n\n{agents_content}")
            except Exception:
                pass
        try:
            tldr = _generate_code_tldr(str(self._original_project_dir))
            if tldr:
                context_blocks.append(f"# Codebase Structure (auto-generated)\n\n{tldr}")
        except Exception:
            pass
        if context_blocks:
            effective_description = "\n\n---\n\n".join(context_blocks) + f"\n\n---\n\n# Task\n\n{self.description}"
        # Inject unread messages from other tasks
        if task_queue:
            try:
                messages = await task_queue.get_messages(self.task_id, unread_only=True)
                if messages:
                    msg_block = "\n\n---\n**Messages from other tasks:**\n"
                    for m in messages:
                        sender = m.get("from_task_id") or "human"
                        msg_block += f"- [{sender}]: {m['content']}\n"
                    effective_description += msg_block
                    await task_queue.mark_messages_read(self.task_id)
            except Exception:
                pass
        task_file.write_text(effective_description)

        _ALLOWED_MODELS = {
            "claude-opus-4-6", "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
            "claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5",
        }
        model = _MODEL_ALIASES.get(self.model, self.model)
        model = model if model in _ALLOWED_MODELS else "claude-sonnet-4-6"
        shell_cmd = (
            f'claude -p "$(cat {shlex.quote(str(task_file))})" --model {model} --dangerously-skip-permissions'
        )

        env = {**os.environ}
        if GLOBAL_SETTINGS.get("agent_teams"):
            env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "1"

        log_fd = open(self._log_path, "w")  # noqa: WPS515
        try:
            self.proc = await asyncio.create_subprocess_shell(
                shell_cmd,
                stdout=log_fd,
                stderr=log_fd,
                preexec_fn=os.setsid,
                env=env,
                cwd=str(self._project_dir),
            )
        finally:
            log_fd.close()
        self.pid = self.proc.pid
        try:
            self.pgid = os.getpgid(self.proc.pid)
        except ProcessLookupError:
            self.pgid = self.proc.pid
        self.status = "running"

    def is_alive(self) -> bool:
        if self.proc is None:
            return False
        return self.proc.returncode is None

    def pause(self) -> None:
        if self.pgid and self.is_alive():
            try:
                os.killpg(self.pgid, signal.SIGSTOP)
                self.status = "paused"
            except ProcessLookupError:
                pass

    def resume(self) -> None:
        if self.pgid and self.status == "paused":
            try:
                os.killpg(self.pgid, signal.SIGCONT)
                self.status = "running"
            except ProcessLookupError:
                pass

    async def stop(self) -> None:
        if self.pgid and self.is_alive():
            try:
                os.killpg(self.pgid, signal.SIGTERM)
                await asyncio.sleep(0.5)
                if self.is_alive():
                    os.killpg(self.pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if self._finished_at is None:
            self._finished_at = time.time()
        self._verify_triggered = True  # prevent _on_worker_done from running after forced stop
        await self._cleanup_worktree()

    async def poll(self) -> None:
        if not self.is_alive():
            if self._finished_at is None:
                self._finished_at = time.time()
            rc = self.proc.returncode if self.proc else -1
            self.status = "done" if rc == 0 else "failed"
            if self.status == "failed" and self._log_path and self._log_path.exists():
                try:
                    text = self._log_path.read_text(errors="replace")
                    lines = [l for l in text.splitlines() if l.strip()]
                    self.failure_context = "\n".join(lines[-50:])
                except Exception:
                    pass
            if not self._verify_triggered:
                self._verify_triggered = True
                asyncio.ensure_future(self._on_worker_done())
            elif self._worktree_path and self._worktree_path.exists():
                asyncio.ensure_future(self._cleanup_worktree())
            return

        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "log", "-1", "--oneline",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=str(self._project_dir),
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3)
            self.last_commit = stdout.decode().strip() or None
        except Exception:
            pass

    async def _cleanup_worktree(self) -> None:
        if not self._worktree_path:
            return
        cleanup = await asyncio.create_subprocess_exec(
            "git", "worktree", "remove", "--force", str(self._worktree_path),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            cwd=str(self._original_project_dir),
        )
        try:
            await asyncio.wait_for(cleanup.communicate(), timeout=15)
        except Exception:
            pass
        self._worktree_path = None
        self._project_dir = self._original_project_dir  # restore so git cmds still work

    async def _on_worker_done(self) -> None:
        """Run after process exits: verify+commit while worktree is still alive, then clean up."""
        if self.status == "done":
            try:
                await self.verify_and_commit()
            except Exception:
                logger.exception("verify_and_commit failed for worker %s", self.id)
        # Parse token usage from log
        if self._log_path and self._log_path.exists():
            try:
                self._input_tokens, self._output_tokens = _parse_token_usage(self._log_path)
                self._estimated_cost = _estimate_cost(self._input_tokens, self._output_tokens)
            except Exception:
                pass
        # Check for handoff file — worker wrote it to signal continuation needed
        handoff_path = self._claude_dir / f"handoff-{self.task_id}.md"
        if handoff_path.exists():
            try:
                self._handoff_content = handoff_path.read_text(errors="replace").strip()
                self._handoff_requeue = bool(self._handoff_content)
                handoff_path.unlink(missing_ok=True)
                logger.info("Handoff file found for task %s — flagging for continuation", self.task_id)
            except Exception:
                pass
        await self._cleanup_worktree()

    def _check_file_ownership(self, changed_files: list[str]) -> tuple[bool, str]:
        """Check changed files against own_files/forbidden_files globs. Returns (ok, reason)."""
        if not self.own_files and not self.forbidden_files:
            return True, ""

        def _matches(filepath: str, patterns: list[str]) -> bool:
            for pat in patterns:
                if pat.endswith("/**"):
                    prefix = pat[:-3]  # "src/db/**" → "src/db"
                    if filepath == prefix or filepath.startswith(prefix + "/"):
                        return True
                if fnmatch.fnmatch(filepath, pat):
                    return True
            return False

        # Check forbidden files
        for f in changed_files:
            if self.forbidden_files and _matches(f, self.forbidden_files):
                return False, f"File '{f}' matches FORBIDDEN_FILES pattern"

        # Check own files (if set, every changed file must match at least one pattern)
        if self.own_files:
            for f in changed_files:
                if not _matches(f, self.own_files):
                    return False, f"File '{f}' not in OWN_FILES patterns"

        return True, ""

    async def verify_and_commit(self) -> bool:
        diff_proc = await asyncio.create_subprocess_exec(
            "git", "diff", "--name-only", "HEAD",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            cwd=str(self._project_dir),
        )
        try:
            stdout, _ = await asyncio.wait_for(diff_proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            diff_proc.kill()
            await diff_proc.communicate()
            return False
        except Exception:
            return False
        untracked_proc = await asyncio.create_subprocess_exec(
            "git", "ls-files", "--others", "--exclude-standard",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            cwd=str(self._project_dir),
        )
        try:
            ut_out, _ = await asyncio.wait_for(untracked_proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            untracked_proc.kill()
            await untracked_proc.communicate()
            return False
        except Exception:
            return False
        changed_files = [
            f for f in (stdout.decode().strip() + "\n" + ut_out.decode().strip()).splitlines()
            if f.strip()
        ]
        if not changed_files:
            return False

        # File ownership enforcement
        ok, reason = self._check_file_ownership(changed_files)
        if not ok:
            self._ownership_violation = True
            self._ownership_violation_reason = reason
            # Discard all changes in worktree
            discard = await asyncio.create_subprocess_exec(
                "git", "checkout", ".",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                cwd=str(self._project_dir),
            )
            try:
                await asyncio.wait_for(discard.communicate(), timeout=10)
            except Exception:
                pass
            clean = await asyncio.create_subprocess_exec(
                "git", "clean", "-fd",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                cwd=str(self._project_dir),
            )
            try:
                await asyncio.wait_for(clean.communicate(), timeout=10)
            except Exception:
                pass
            return False

        diff_summary_proc = await asyncio.create_subprocess_exec(
            "git", "diff", "HEAD", "--stat",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            cwd=str(self._project_dir),
        )
        try:
            diff_out, _ = await asyncio.wait_for(diff_summary_proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            diff_summary_proc.kill()
            await diff_summary_proc.communicate()
            return False

        task_first_line = self.description.splitlines()[0][:80]
        verify_prompt = (
            f"Task was: {task_first_line}\n\n"
            f"Git diff stat:\n{diff_out.decode()}\n\n"
            "If the changes look complete and correct for the task, output exactly: VERIFIED_OK\n"
            "If there are obvious issues or nothing was changed, output: VERIFIED_FAIL: <reason>\n"
            "Output ONLY one of those two responses, nothing else."
        )

        verify_file = self._claude_dir / f"verify-{self.id}.md"
        verify_file.write_text(verify_prompt)
        try:
            verify_proc = await asyncio.create_subprocess_shell(
                f'claude -p "$(cat {shlex.quote(str(verify_file))})" --model claude-haiku-4-5-20251001 --dangerously-skip-permissions',
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                cwd=str(self._project_dir),
            )
            try:
                v_out, _ = await asyncio.wait_for(verify_proc.communicate(), timeout=120)
                result = v_out.decode().strip()
            except asyncio.TimeoutError:
                verify_proc.kill()
                await verify_proc.communicate()
                return False
        finally:
            verify_file.unlink(missing_ok=True)

        if "VERIFIED_OK" not in result:
            return False

        self.verified = True

        commit_msg = f"feat: {task_first_line.lower()}"
        files_arg = " ".join(shlex.quote(f) for f in changed_files[:20])
        committer_path = Path.home() / ".claude/scripts/committer.sh"
        if committer_path.exists():
            commit_cmd = (
                f'bash {shlex.quote(str(committer_path))} '
                f'{shlex.quote(commit_msg)} {files_arg}'
            )
        else:
            commit_cmd = f'git add {files_arg} && git commit -m {shlex.quote(commit_msg)}'
        commit_proc = await asyncio.create_subprocess_shell(
            commit_cmd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(self._project_dir),
        )
        try:
            c_out, c_err = await asyncio.wait_for(commit_proc.communicate(), timeout=30)
            if commit_proc.returncode == 0:
                self.auto_committed = True

                # Oracle validation gate
                if GLOBAL_SETTINGS.get("auto_oracle", False):
                    try:
                        diff_proc = await asyncio.create_subprocess_exec(
                            "git", "diff", "HEAD~1", "HEAD",
                            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                            cwd=str(self._project_dir),
                        )
                        diff_out, _ = await asyncio.wait_for(diff_proc.communicate(), timeout=15)
                        approved, reason = await _oracle_review(
                            self.description, diff_out.decode(), self._claude_dir
                        )
                        self.oracle_result = "approved" if approved else "rejected"
                        self.oracle_reason = reason
                        if not approved:
                            # Undo the commit so rejected work is not accidentally pushed later
                            reset_proc = await asyncio.create_subprocess_exec(
                                "git", "reset", "HEAD~1",
                                stdout=asyncio.subprocess.DEVNULL,
                                stderr=asyncio.subprocess.DEVNULL,
                                cwd=str(self._project_dir),
                            )
                            try:
                                await asyncio.wait_for(reset_proc.communicate(), timeout=10)
                            except asyncio.TimeoutError:
                                reset_proc.kill()
                                await reset_proc.communicate()
                            self.auto_committed = False
                            # Flag for requeue — poll_all will pick this up
                            self._oracle_requeue = True
                            self._oracle_requeue_reason = reason
                            return False
                    except Exception:
                        pass  # fail-open

                branch = f"orchestrator/task-{self.task_id}"
                self.branch_name = branch
                if GLOBAL_SETTINGS.get("auto_push", True):
                    push_proc = await asyncio.create_subprocess_shell(
                        f'git push origin HEAD:{branch} --force-with-lease',
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                        cwd=str(self._project_dir),
                    )
                    try:
                        p_out, p_err = await asyncio.wait_for(push_proc.communicate(), timeout=30)
                        if push_proc.returncode == 0:
                            self.auto_pushed = True
                    except asyncio.TimeoutError:
                        push_proc.kill()
                        await push_proc.communicate()

                log_proc = await asyncio.create_subprocess_exec(
                    "git", "log", "-1", "--oneline",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    cwd=str(self._project_dir),
                )
                try:
                    log_out, _ = await asyncio.wait_for(log_proc.communicate(), timeout=5)
                    self.last_commit = log_out.decode().strip() or self.last_commit
                except asyncio.TimeoutError:
                    log_proc.kill()
                    await log_proc.communicate()
        except asyncio.TimeoutError:
            pass
        return self.auto_committed

# ─── Worker Pool ──────────────────────────────────────────────────────────────


class WorkerPool:
    def __init__(self):
        self.workers: dict[str, Worker] = {}

    async def start_worker(
        self,
        task: dict,
        task_queue: TaskQueue,
        project_dir: Path,
        claude_dir: Path,
    ) -> Worker:
        # Guard: prevent spawning a second worker for the same task
        existing = next(
            (w for w in self.workers.values() if w.task_id == task["id"] and w.status in ("running", "starting")),
            None,
        )
        if existing:
            return existing
        model = task.get("model", GLOBAL_SETTINGS.get("default_model", "sonnet"))
        model = _MODEL_ALIASES.get(model, model)
        description = task["description"]
        if GLOBAL_SETTINGS.get("auto_model_routing", False):
            score = task.get("score")
            if score is not None:
                if score >= 80:
                    model = "haiku"
                elif score < 50:
                    model = "sonnet"
                    description = (
                        "⚠ This task scored low on readiness (<50). "
                        "Ask clarifying questions before writing any code. "
                        "Do NOT start implementing until requirements are clear.\n\n"
                        + description
                    )
                if task.get("is_critical_path"):
                    model = {"haiku": "sonnet", "sonnet": "opus"}.get(model, model)
        # Auto-inject past intervention corrections for retried/failed tasks
        failed_reason = task.get("failed_reason")
        if failed_reason:
            try:
                match = await task_queue.find_matching_intervention(failed_reason)
                if match:
                    description = (
                        f"{description}\n\n---\n"
                        f"**Auto-injected correction (from past intervention):**\n"
                        f"{match['correction']}"
                    )
            except Exception:
                pass
        model = _MODEL_ALIASES.get(model, model)
        worker = Worker(
            task["id"],
            description,
            model,
            project_dir,
            claude_dir,
        )
        worker.model_score = task.get("score")
        worker.task_timeout = task.get("timeout", 600)
        worker.own_files = task.get("own_files", [])
        worker.forbidden_files = task.get("forbidden_files", [])
        self.workers[worker.id] = worker
        await task_queue.update(task["id"], status="running", worker_id=worker.id)
        await worker.start(task_queue=task_queue)
        return worker

    def get(self, worker_id: str) -> Worker | None:
        return self.workers.get(worker_id)

    def all(self) -> list[Worker]:
        return list(self.workers.values())

    async def poll_all(self, task_queue: TaskQueue, project_dir: Path | None = None) -> None:
        for w in list(self.workers.values()):
            if w.status == "running" and w.task_timeout and w.task_timeout > 0 and w.elapsed_s > w.task_timeout:
                await w.stop()
                w.status = "failed"
                if w._log_path and w._log_path.exists():
                    try:
                        text = w._log_path.read_text(errors="replace")
                        lines = [l for l in text.splitlines() if l.strip()]
                        w.failure_context = "\n".join(lines[-50:])
                    except Exception:
                        pass
                await task_queue.update(
                    w.task_id,
                    status="failed",
                    elapsed_s=w.elapsed_s,
                    last_commit=w.last_commit,
                )
                if w.failure_context:
                    await task_queue.update(w.task_id, failed_reason=w.failure_context)
                if project_dir and GLOBAL_SETTINGS.get("github_issues_sync"):
                    t = await task_queue.get(w.task_id)
                    if t:
                        asyncio.ensure_future(_gh_update_issue_status(t, project_dir))
                continue
            # Stuck worker detection: log file mtime unchanged for N minutes
            stuck_timeout = GLOBAL_SETTINGS.get("stuck_timeout_minutes", 15)
            if (w.status == "running" and not w._stuck_detected
                    and stuck_timeout > 0 and w._log_path and w._log_path.exists()):
                try:
                    idle_s = time.time() - w._log_path.stat().st_mtime
                    if idle_s > stuck_timeout * 60:
                        w._stuck_detected = True
                        logger.warning("Worker %s stuck (no log output for %dm) — killing", w.id, stuck_timeout)
                        await w.stop()
                        w.status = "failed"
                        stuck_reason = f"[STUCK] No log output for {int(idle_s)}s (threshold: {stuck_timeout}min)"
                        w.failure_context = stuck_reason
                        await task_queue.update(w.task_id, status="failed",
                                                elapsed_s=w.elapsed_s, failed_reason=stuck_reason)
                        # Requeue with stuck context (skip: already retried, or loop-managed tasks)
                        _is_loop_task = w.description.startswith("[Loop-") or w.description.startswith("[Plan-")
                        if not w.description.startswith("[STUCK-RETRY]") and not _is_loop_task:
                            retry_desc = f"[STUCK-RETRY] {w.description}"
                            await task_queue.add(retry_desc, w.model,
                                                 own_files=w.own_files, forbidden_files=w.forbidden_files)
                        else:
                            logger.warning("Worker %s stuck — not re-queuing (retry=%s, loop=%s)",
                                           w.id, w.description.startswith("[STUCK-RETRY]"), _is_loop_task)
                        if project_dir and GLOBAL_SETTINGS.get("github_issues_sync"):
                            t = await task_queue.get(w.task_id)
                            if t:
                                asyncio.ensure_future(_gh_update_issue_status(t, project_dir))
                        continue
                except Exception:
                    pass
            # Guard: don't poll() workers already in a terminal state — poll() would
            # overwrite "blocked" with "failed" based on process exit code
            if w.status not in ("done", "failed", "blocked"):
                await w.poll()
            if w.status in ("done", "failed", "blocked"):
                if not w._terminal_persisted:
                    w._terminal_persisted = True
                    await task_queue.update(
                        w.task_id,
                        status=w.status,
                        elapsed_s=w.elapsed_s,
                        last_commit=w.last_commit,
                    )
                    # Persist token/cost data
                    if w._input_tokens or w._output_tokens:
                        await task_queue.update(
                            w.task_id,
                            input_tokens=w._input_tokens,
                            output_tokens=w._output_tokens,
                            estimated_cost=w._estimated_cost,
                        )
                    if w.status == "failed" and w.failure_context:
                        await task_queue.update(w.task_id, failed_reason=w.failure_context)
                    if w.status == "done":
                        try:
                            await task_queue.mark_intervention_success(w.task_id)
                        except Exception:
                            pass
                    if project_dir and GLOBAL_SETTINGS.get("github_issues_sync"):
                        t = await task_queue.get(w.task_id)
                        if t:
                            asyncio.ensure_future(_gh_update_issue_status(t, project_dir))
                # Oracle rejected → re-queue with rejection reason as context
                if w._oracle_requeue:
                    w._oracle_requeue = False
                    retry_desc = (
                        f"{w.description}\n\n---\n"
                        f"Previous attempt was REJECTED by oracle review:\n"
                        f"{w._oracle_requeue_reason}\n"
                        f"Fix the issue described above. Do NOT repeat the same approach."
                    )
                    await task_queue.add(retry_desc, w.model,
                                        own_files=w.own_files, forbidden_files=w.forbidden_files)
                    logger.info("Oracle rejected task %s — re-queued with reason", w.task_id)
                # File ownership violation → re-queue with violation context
                if w._ownership_violation:
                    w._ownership_violation = False
                    retry_desc = (
                        f"{w.description}\n\n---\n"
                        f"Previous attempt REJECTED — file ownership violation:\n"
                        f"{w._ownership_violation_reason}\n\n"
                        f"You MUST only edit files matching your OWN_FILES patterns. "
                        f"Do NOT touch FORBIDDEN_FILES. Find an alternative approach."
                    )
                    await task_queue.add(retry_desc, w.model,
                                        own_files=w.own_files, forbidden_files=w.forbidden_files)
                    await task_queue.update(
                        w.task_id,
                        failed_reason=f"Ownership violation: {(w._ownership_violation_reason or '')[:200]}"
                    )
                    logger.info("Ownership violation task %s — re-queued with reason", w.task_id)
                # Worker wrote handoff file → create continuation task
                if w._handoff_requeue:
                    w._handoff_requeue = False
                    continuation_desc = (
                        f"{w.description}\n\n---\n"
                        f"**Continuation — previous session handed off:**\n"
                        f"{w._handoff_content}\n\n"
                        f"Run /pickup if available, then continue from where the previous worker left off."
                    )
                    await task_queue.add(continuation_desc, w.model,
                                        own_files=w.own_files, forbidden_files=w.forbidden_files)
                    logger.info("Handoff task %s → continuation queued", w.task_id)
            else:
                await task_queue.update(
                    w.task_id,
                    elapsed_s=w.elapsed_s,
                    last_commit=w.last_commit,
                )
            # verify_and_commit() is triggered in poll() via _on_worker_done() to ensure
            # it runs before worktree cleanup — no separate trigger needed here
        if GLOBAL_SETTINGS.get("context_budget_warning", True):
            for w in list(self.workers.values()):
                if w.status == "running":
                    tokens = w._estimate_tokens()
                    if tokens > 160000:
                        warn_file = w._claude_dir / f"context-warning-{w.id}.md"
                        if not warn_file.exists():
                            warn_file.write_text(
                                "CONTEXT WARNING: ~80% context window used. "
                                "Run /compact now — preserve current task state, files modified, next steps."
                            )

# ─── Swarm Manager ────────────────────────────────────────────────────────────


class SwarmManager:
    """N-slot swarm: auto-claims tasks and fills worker slots.

    State machine: idle → active → draining → done/stopped
    """

    def __init__(self, session: Any):
        self._session = session
        self._status = "idle"  # idle/active/draining/done/stopped
        self._done_reason: str | None = None
        self._target_slots = 0
        self._active_worker_ids: set[str] = set()
        self._stats = {"started": 0, "done": 0, "failed": 0}
        self._task: asyncio.Task | None = None
        self._started_at: float | None = None

    @property
    def status(self) -> str:
        return self._status

    def to_dict(self) -> dict:
        running = sum(
            1 for wid in self._active_worker_ids
            if (w := self._session.worker_pool.workers.get(wid)) and w.status in ("running", "starting")
        )
        elapsed = int(time.time() - self._started_at) if self._started_at else 0
        return {
            "status": self._status,
            "target_slots": self._target_slots,
            "running": running,
            "stats": dict(self._stats),
            "done_reason": self._done_reason,
            "elapsed_s": elapsed,
        }

    def start(self, slots: int) -> dict:
        if self._status == "active":
            return {"error": "Swarm already active"}
        self._status = "active"
        self._done_reason = None
        self._target_slots = max(1, min(slots, 20))
        self._active_worker_ids = set()
        self._stats = {"started": 0, "done": 0, "failed": 0}
        self._started_at = time.time()
        self._task = asyncio.ensure_future(self._refill_loop())
        return self.to_dict()

    def stop(self) -> dict:
        if self._status != "active":
            return {"error": f"Swarm is {self._status}, not active"}
        self._status = "draining"
        return self.to_dict()

    async def force_stop(self) -> dict:
        self._status = "stopped"
        self._done_reason = "force_stopped"
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None
        # Kill all swarm-tracked workers
        for wid in list(self._active_worker_ids):
            w = self._session.worker_pool.workers.get(wid)
            if w and w.status in ("running", "starting"):
                await w.stop()
                w.status = "failed"
                await self._session.task_queue.update(w.task_id, status="failed")
        self._active_worker_ids.clear()
        return self.to_dict()

    def resize(self, new_slots: int) -> dict:
        if self._status != "active":
            return {"error": f"Swarm is {self._status}, cannot resize"}
        self._target_slots = max(1, min(new_slots, 20))
        return self.to_dict()

    async def _refill_loop(self) -> None:
        """Core loop: count running → clean finished → claim tasks → fill slots → wait."""
        try:
            while self._status in ("active", "draining"):
                await self._refill_once()
                # Wait before next check (faster than status_loop's 1s)
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Swarm refill_loop error")
            self._status = "stopped"
            self._done_reason = "error"

    async def _refill_once(self) -> None:
        pool = self._session.worker_pool
        tq = self._session.task_queue

        # Clean up finished workers from tracking set
        finished_ids = set()
        for wid in list(self._active_worker_ids):
            w = pool.workers.get(wid)
            if w is None or w.status in ("done", "failed"):
                finished_ids.add(wid)
                if w and w.status == "done":
                    self._stats["done"] += 1
                elif w and w.status == "failed":
                    self._stats["failed"] += 1
        self._active_worker_ids -= finished_ids

        # Count currently running swarm workers
        running = sum(
            1 for wid in self._active_worker_ids
            if (w := pool.workers.get(wid)) and w.status in ("running", "starting")
        )

        # If draining, just wait for current workers to finish
        if self._status == "draining":
            if running == 0:
                self._status = "stopped"
                self._done_reason = "drained"
            return

        # Calculate how many slots to fill
        # Also respect global max_workers
        from config import _deps_met as deps_met_check
        global_max = GLOBAL_SETTINGS.get("max_workers", 0)
        total_running = sum(1 for w in pool.workers.values() if w.status in ("running", "starting"))
        if global_max > 0:
            global_available = max(0, global_max - total_running)
        else:
            global_available = self._target_slots  # no global limit
        to_fill = min(self._target_slots - running, global_available)

        if to_fill <= 0:
            if running > 0:
                return  # slots full, wait for workers to finish
            # Global cap held by non-swarm workers — don't conclude completion
            if global_max > 0 and global_available == 0 and total_running > 0:
                return

        # Get done task IDs for dependency checks
        all_tasks = await tq.list()
        done_ids = {t["id"] for t in all_tasks if t["status"] == "done"}

        # Try to claim and start tasks
        claimed_any = False
        for _ in range(max(to_fill, 0)):
            task = await tq.claim_next_pending(done_ids)
            if task is None:
                break
            claimed_any = True
            worker = await pool.start_worker(
                task, tq, self._session.project_dir, self._session.claude_dir
            )
            self._active_worker_ids.add(worker.id)
            self._stats["started"] += 1

        # Check completion conditions
        if not claimed_any and running == 0:
            # No tasks claimed, no workers running — check why
            pending = [t for t in all_tasks if t["status"] == "pending"]
            if not pending:
                # No pending tasks at all → all complete
                self._status = "done"
                self._done_reason = "all_complete"
            else:
                # Pending tasks exist but none were claimable (all blocked by deps)
                blocked_pending = [t for t in pending if not deps_met_check(t, done_ids)]
                if len(blocked_pending) == len(pending):
                    # All pending tasks are blocked and nothing is running to unblock them
                    self._status = "done"
                    self._done_reason = "blocked"
                # else: some tasks have deps met but were claimed by another path — wait
