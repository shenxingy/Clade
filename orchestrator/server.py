"""
Claude Code Orchestrator — FastAPI server
Manages multiple project sessions, each with an interactive orchestrator (PTY) + N workers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import signal
import time
import uuid

logger = logging.getLogger(__name__)
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite
import ptyprocess
from fastapi import Body, Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from watchfiles import awatch

# ─── Constants ────────────────────────────────────────────────────────────────

_ALLOWED_TASK_COLS = {"status", "description", "model", "depends_on", "mode", "result", "score",
                      "worker_id", "started_at", "elapsed_s", "last_commit", "log_file",
                      "failed_reason", "score_note"}

_MODEL_ALIASES = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
}

# ─── Paths ────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
WEB_DIR = BASE_DIR / "web"

# Kept for backward compat / default session init; not used in new code paths
PROJECT_DIR = Path(os.environ.get("ORCHESTRATOR_PROJECT_DIR", str(Path.cwd())))

# ─── Global Settings ──────────────────────────────────────────────────────────

_settings_file = Path.home() / ".claude" / "orchestrator-settings.json"


_SETTINGS_DEFAULTS = {
    "max_workers": 0,
    "auto_start": True,
    "auto_push": True,
    "auto_merge": True,
    "auto_review": True,
    "default_model": "sonnet",
    "loop_supervisor_model": "sonnet",
    "loop_convergence_k": 2,
    "loop_convergence_n": 3,
    "loop_max_iterations": 20,
    "auto_oracle": False,
    "auto_model_routing": False,
    "context_budget_warning": True,
}


def _load_settings() -> dict:
    defaults = dict(_SETTINGS_DEFAULTS)
    if _settings_file.exists():
        try:
            defaults.update(json.loads(_settings_file.read_text()))
        except Exception:
            pass
    return defaults


def _save_settings(s: dict) -> None:
    _settings_file.parent.mkdir(parents=True, exist_ok=True)
    _settings_file.write_text(json.dumps(s, indent=2))


GLOBAL_SETTINGS: dict = _load_settings()


def scan_projects(base: Path | None = None, max_depth: int = 3) -> list[dict]:
    """Find git repos under base dir (default: home)."""
    if base is None:
        base = Path.home()
    results = []

    def _scan(p: Path, depth: int) -> None:
        if depth > max_depth or not p.is_dir():
            return
        try:
            if (p / ".git").exists():
                results.append({"name": p.name, "path": str(p)})
                return  # don't recurse into git repos
            for child in sorted(p.iterdir()):
                if child.is_dir() and not child.name.startswith("."):
                    _scan(child, depth + 1)
        except PermissionError:
            pass

    _scan(base, 0)
    return results[:50]  # cap at 50


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="Claude Code Orchestrator")

# Serve static files (web UI)
app.mount("/web", StaticFiles(directory=str(WEB_DIR)), name="web")


# ─── Task Queue (SQLite-backed) ───────────────────────────────────────────────

class TaskQueue:
    """SQLite-backed task queue. Cross-session persistence, task history retained."""

    def __init__(self, claude_dir: Path):
        self._claude_dir = claude_dir
        self._db_path = claude_dir / "tasks.db"
        self._initialized = False
        self._init_lock = asyncio.Lock()
        self._upsert_lock = asyncio.Lock()

    def _proposed_tasks_file(self) -> Path:
        return self._claude_dir / "proposed-tasks.md"

    async def _ensure_db(self) -> None:
        async with self._init_lock:
            if self._initialized:
                return
            self._claude_dir.mkdir(parents=True, exist_ok=True)
            async with aiosqlite.connect(str(self._db_path)) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS tasks (
                        id TEXT PRIMARY KEY,
                        description TEXT NOT NULL,
                        model TEXT DEFAULT 'sonnet',
                        timeout INTEGER DEFAULT 600,
                        retries INTEGER DEFAULT 2,
                        status TEXT DEFAULT 'pending',
                        worker_id TEXT,
                        started_at REAL,
                        elapsed_s INTEGER DEFAULT 0,
                        last_commit TEXT,
                        log_file TEXT,
                        failed_reason TEXT,
                        created_at REAL,
                        depends_on TEXT DEFAULT '[]',
                        score INTEGER,
                        score_note TEXT
                    )
                """)
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS commits (
                        id TEXT PRIMARY KEY,
                        task_id TEXT,
                        hash TEXT,
                        branch TEXT,
                        committed_at REAL,
                        pushed_at REAL,
                        merged_at REAL,
                        FOREIGN KEY (task_id) REFERENCES tasks(id)
                    )
                """)
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS schedule (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        scheduled_at TEXT,
                        triggered INTEGER DEFAULT 0
                    )
                """)
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS iteration_loops (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL DEFAULT 'default',
                        artifact_path TEXT NOT NULL DEFAULT '',
                        context_dir TEXT,
                        status TEXT DEFAULT 'idle',
                        iteration INTEGER DEFAULT 0,
                        changes_history TEXT DEFAULT '[]',
                        deferred_items TEXT DEFAULT '[]',
                        convergence_k INTEGER DEFAULT 2,
                        convergence_n INTEGER DEFAULT 3,
                        max_iterations INTEGER DEFAULT 20,
                        supervisor_model TEXT DEFAULT 'sonnet',
                        created_at TEXT,
                        updated_at TEXT,
                        mode TEXT DEFAULT 'review'
                    )
                """)
                # Migration: add mode column for existing DBs that predate this column
                try:
                    await db.execute("ALTER TABLE iteration_loops ADD COLUMN mode TEXT DEFAULT 'review'")
                except Exception:
                    pass  # column already exists
                await db.commit()
            # Migrate from JSON if present
            json_file = self._claude_dir / "task-queue.json"
            if json_file.exists():
                try:
                    existing = json.loads(json_file.read_text())
                    if existing:
                        async with aiosqlite.connect(str(self._db_path)) as db:
                            for t in existing:
                                await db.execute(
                                    """INSERT OR IGNORE INTO tasks
                                       (id, description, model, timeout, retries, status, worker_id,
                                        started_at, elapsed_s, last_commit, log_file, failed_reason,
                                        created_at, depends_on)
                                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                    (
                                        t.get("id"), t.get("description", ""),
                                        t.get("model", "sonnet"), t.get("timeout", 600),
                                        t.get("retries", 2), t.get("status", "pending"),
                                        t.get("worker_id"), t.get("started_at"),
                                        t.get("elapsed_s", 0), t.get("last_commit"),
                                        t.get("log_file"), t.get("failed_reason"),
                                        t.get("created_at", time.time()),
                                        json.dumps(t.get("depends_on", [])),
                                    ),
                                )
                            await db.commit()
                    json_file.rename(json_file.with_suffix(".json.migrated"))
                except Exception:
                    pass
            self._initialized = True

    def _row_to_dict(self, row) -> dict:
        d = dict(row)
        raw_deps = d.get("depends_on")
        if isinstance(raw_deps, str):
            try:
                d["depends_on"] = json.loads(raw_deps)
            except Exception:
                d["depends_on"] = []
        elif raw_deps is None:
            d["depends_on"] = []
        return d

    async def list(self) -> list[dict]:
        await self._ensure_db()
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM tasks ORDER BY created_at") as cur:
                rows = await cur.fetchall()
        return [self._row_to_dict(r) for r in rows]

    async def add(self, description: str, model: str = "sonnet") -> dict:
        await self._ensure_db()
        task = {
            "id": str(uuid.uuid4())[:8],
            "description": description,
            "model": model,
            "timeout": 600,
            "retries": 2,
            "status": "pending",
            "worker_id": None,
            "started_at": None,
            "elapsed_s": 0,
            "last_commit": None,
            "log_file": None,
            "failed_reason": None,
            "created_at": time.time(),
            "depends_on": [],
            "score": None,
            "score_note": None,
        }
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.execute(
                """INSERT INTO tasks
                   (id, description, model, timeout, retries, status, worker_id,
                    started_at, elapsed_s, last_commit, log_file, failed_reason,
                    created_at, depends_on, score, score_note)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    task["id"], task["description"], task["model"],
                    task["timeout"], task["retries"], task["status"],
                    task["worker_id"], task["started_at"], task["elapsed_s"],
                    task["last_commit"], task["log_file"], task["failed_reason"],
                    task["created_at"], json.dumps(task["depends_on"]),
                    task["score"], task["score_note"],
                ),
            )
            await db.commit()
        return task

    async def update(self, task_id: str, **kwargs) -> dict | None:
        await self._ensure_db()
        if not kwargs:
            return await self.get(task_id)
        if "depends_on" in kwargs:
            val = kwargs["depends_on"]
            kwargs["depends_on"] = json.dumps(val) if not isinstance(val, str) else val
        for k in kwargs:
            if k not in _ALLOWED_TASK_COLS:
                raise ValueError(f"Unknown task column: {k}")
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [task_id]
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", values)
            await db.commit()
        return await self.get(task_id)

    async def delete(self, task_id: str) -> bool:
        await self._ensure_db()
        async with aiosqlite.connect(str(self._db_path)) as db:
            cur = await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            await db.commit()
            return cur.rowcount > 0

    async def get(self, task_id: str) -> dict | None:
        await self._ensure_db()
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)) as cur:
                row = await cur.fetchone()
        return self._row_to_dict(row) if row else None

    async def get_schedule(self) -> dict | None:
        await self._ensure_db()
        async with aiosqlite.connect(str(self._db_path)) as db:
            async with db.execute("SELECT scheduled_at, triggered FROM schedule WHERE id=1") as cur:
                row = await cur.fetchone()
                if not row or not row[0]:
                    return None
                return {"scheduled_at": row[0], "triggered": bool(row[1])}

    async def save_schedule(self, scheduled_at: str | None, triggered: bool = False) -> None:
        await self._ensure_db()
        async with aiosqlite.connect(str(self._db_path)) as db:
            if scheduled_at is None:
                await db.execute("DELETE FROM schedule WHERE id=1")
            else:
                await db.execute(
                    "INSERT OR REPLACE INTO schedule (id, scheduled_at, triggered) VALUES (1, ?, ?)",
                    (scheduled_at, int(triggered)),
                )
            await db.commit()

    async def get_loop(self) -> dict | None:
        await self._ensure_db()
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM iteration_loops ORDER BY id DESC LIMIT 1"
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        for key in ("changes_history", "deferred_items"):
            if isinstance(d.get(key), str):
                try:
                    d[key] = json.loads(d[key])
                except Exception:
                    d[key] = []
        return d

    async def delete_loop(self) -> None:
        await self._ensure_db()
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.execute("DELETE FROM iteration_loops")
            await db.commit()

    async def upsert_loop(self, **kwargs) -> dict | None:
        """Update existing loop row, or create one with provided fields."""
        await self._ensure_db()
        async with self._upsert_lock:
            existing = await self.get_loop()
            now = datetime.now().isoformat()
            for key in ("changes_history", "deferred_items"):
                if key in kwargs and not isinstance(kwargs[key], str):
                    kwargs[key] = json.dumps(kwargs[key])
            if existing is None:
                fields = {
                    "name": "default",
                    "artifact_path": "",
                    "context_dir": None,
                    "status": "idle",
                    "iteration": 0,
                    "changes_history": "[]",
                    "deferred_items": "[]",
                    "convergence_k": 2,
                    "convergence_n": 3,
                    "max_iterations": 20,
                    "supervisor_model": "sonnet",
                    "mode": "review",
                    "created_at": now,
                    "updated_at": now,
                }
                fields.update(kwargs)
                async with aiosqlite.connect(str(self._db_path)) as db:
                    await db.execute(
                        """INSERT INTO iteration_loops
                           (name, artifact_path, context_dir, status, iteration,
                            changes_history, deferred_items, convergence_k, convergence_n,
                            max_iterations, supervisor_model, mode, created_at, updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            fields["name"], fields["artifact_path"], fields["context_dir"],
                            fields["status"], fields["iteration"], fields["changes_history"],
                            fields["deferred_items"], fields["convergence_k"],
                            fields["convergence_n"], fields["max_iterations"],
                            fields["supervisor_model"], fields.get("mode", "review"),
                            fields["created_at"], fields["updated_at"],
                        ),
                    )
                    await db.commit()
            else:
                update = dict(kwargs)
                update["updated_at"] = now
                set_clause = ", ".join(f"{k} = ?" for k in update)
                values = list(update.values()) + [existing["id"]]
                async with aiosqlite.connect(str(self._db_path)) as db:
                    await db.execute(
                        f"UPDATE iteration_loops SET {set_clause} WHERE id = ?", values
                    )
                    await db.commit()
            return await self.get_loop()

    async def import_from_proposed(self, content: str | None = None) -> list[dict]:
        """Parse ===TASK=== blocks and add to queue, skipping duplicates."""
        if content is None:
            f = self._proposed_tasks_file()
            if not f.exists():
                return []
            content = f.read_text()
        blocks = content.split("===TASK===")
        added = []
        await self._ensure_db()
        existing = await self.list()
        existing_descriptions = {t["description"] for t in existing}
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            lines = block.splitlines()
            model = GLOBAL_SETTINGS.get("default_model", "sonnet")
            timeout = 600
            retries = 2
            depends_on: list[str] = []
            desc_lines = []
            in_header = True
            for line in lines:
                if in_header and line.startswith("model:"):
                    model = line.split(":", 1)[1].strip()
                elif in_header and line.startswith("timeout:"):
                    try:
                        timeout = int(line.split(":", 1)[1].strip())
                    except Exception:
                        pass
                elif in_header and line.startswith("retries:"):
                    try:
                        retries = int(line.split(":", 1)[1].strip())
                    except Exception:
                        pass
                elif in_header and line.startswith("depends_on:"):
                    try:
                        val = line.split(":", 1)[1].strip()
                        depends_on = json.loads(val)
                    except Exception:
                        pass
                elif in_header and line.strip() == "---":
                    in_header = False
                elif not in_header:
                    desc_lines.append(line)
            description = "\n".join(desc_lines).strip()
            if description and description not in existing_descriptions:
                task_id = str(uuid.uuid4())[:8]
                task = {
                    "id": task_id,
                    "description": description,
                    "model": model,
                    "timeout": timeout,
                    "retries": retries,
                    "status": "pending",
                    "worker_id": None,
                    "started_at": None,
                    "elapsed_s": 0,
                    "last_commit": None,
                    "log_file": None,
                    "failed_reason": None,
                    "created_at": time.time(),
                    "depends_on": depends_on,
                    "score": None,
                    "score_note": None,
                }
                async with aiosqlite.connect(str(self._db_path)) as db:
                    await db.execute(
                        """INSERT INTO tasks
                           (id, description, model, timeout, retries, status, worker_id,
                            started_at, elapsed_s, last_commit, log_file, failed_reason,
                            created_at, depends_on, score, score_note)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            task["id"], task["description"], task["model"],
                            task["timeout"], task["retries"], task["status"],
                            None, None, 0, None, None, None,
                            task["created_at"], json.dumps(depends_on), None, None,
                        ),
                    )
                    await db.commit()
                existing_descriptions.add(description)
                added.append(task)
                # Background scout scoring
                asyncio.ensure_future(
                    _score_task(task_id, description, self._db_path, self._claude_dir)
                )
        return added


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
    score_file.write_text(score_prompt)
    try:
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


# ─── Worker Pool ──────────────────────────────────────────────────────────────

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
        self.model_score: int | None = None
        self.branch_name: str | None = None
        self.pr_url: str | None = None
        self.pr_merged: bool = False
        self._verify_triggered: bool = False
        self.task_timeout: int = 600  # default 10 min
        self.failure_context: str | None = None
        self._worktree_path: Path | None = None
        self._branch_name: str | None = None

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

    async def start(self) -> None:
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
                except Exception:
                    pass
                if wt_proc2.returncode == 0:
                    self._project_dir = self._worktree_path
                else:
                    self._worktree_path = None
        except Exception:
            self._worktree_path = None

        logs = self._claude_dir / "orchestrator-logs"
        logs.mkdir(parents=True, exist_ok=True)
        self._log_path = logs / f"worker-{self.id}.log"
        self.log_file = str(self._log_path)

        task_file = self._claude_dir / f"task-{self.id}.md"
        task_file.parent.mkdir(parents=True, exist_ok=True)

        # Prepend project CLAUDE.md for context injection
        effective_description = self.description
        claude_md = self._claude_dir / "CLAUDE.md"
        if claude_md.exists():
            try:
                claude_content = claude_md.read_text(errors="replace").strip()
                if claude_content:
                    effective_description = (
                        f"# Project Context (from .claude/CLAUDE.md)\n\n{claude_content}\n\n"
                        f"---\n\n# Task\n\n{self.description}"
                    )
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

        log_fd = open(self._log_path, "w")  # noqa: WPS515
        try:
            self.proc = await asyncio.create_subprocess_shell(
                shell_cmd,
                stdout=log_fd,
                stderr=log_fd,
                preexec_fn=os.setsid,
                env={**os.environ},
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
        self.status = "done"
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
            await self.verify_and_commit()
        await self._cleanup_worktree()

    async def verify_and_commit(self) -> bool:
        diff_proc = await asyncio.create_subprocess_exec(
            "git", "diff", "--name-only", "HEAD",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            cwd=str(self._project_dir),
        )
        stdout, _ = await asyncio.wait_for(diff_proc.communicate(), timeout=10)
        untracked_proc = await asyncio.create_subprocess_exec(
            "git", "ls-files", "--others", "--exclude-standard",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            cwd=str(self._project_dir),
        )
        ut_out, _ = await asyncio.wait_for(untracked_proc.communicate(), timeout=10)
        changed_files = [
            f for f in (stdout.decode().strip() + "\n" + ut_out.decode().strip()).splitlines()
            if f.strip()
        ]
        if not changed_files:
            return False

        diff_summary_proc = await asyncio.create_subprocess_exec(
            "git", "diff", "HEAD", "--stat",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            cwd=str(self._project_dir),
        )
        diff_out, _ = await asyncio.wait_for(diff_summary_proc.communicate(), timeout=10)

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
                        pass

                log_proc = await asyncio.create_subprocess_exec(
                    "git", "log", "-1", "--oneline",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    cwd=str(self._project_dir),
                )
                log_out, _ = await asyncio.wait_for(log_proc.communicate(), timeout=5)
                self.last_commit = log_out.decode().strip() or self.last_commit
        except asyncio.TimeoutError:
            pass
        return self.auto_committed


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
        self.workers[worker.id] = worker
        await task_queue.update(task["id"], status="running", worker_id=worker.id)
        await worker.start()
        return worker

    def get(self, worker_id: str) -> Worker | None:
        return self.workers.get(worker_id)

    def all(self) -> list[Worker]:
        return list(self.workers.values())

    async def poll_all(self, task_queue: TaskQueue) -> None:
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
                continue
            await w.poll()
            if w.status in ("done", "failed"):
                await task_queue.update(
                    w.task_id,
                    status=w.status,
                    elapsed_s=w.elapsed_s,
                    last_commit=w.last_commit,
                )
                if w.status == "failed" and w.failure_context:
                    await task_queue.update(w.task_id, failed_reason=w.failure_context)
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


# ─── Orchestrator Session (PTY) ───────────────────────────────────────────────

class OrchestratorSession:
    def __init__(self):
        self.pty: ptyprocess.PtyProcess | None = None
        self.clients: list[WebSocket] = []
        self._running = False
        self._read_task: asyncio.Task | None = None

    def start(self, project_dir: Path, rows: int = 24, cols: int = 80) -> None:
        if self.pty and self.pty.isalive():
            return
        env = {**os.environ, "TERM": "xterm-256color"}
        self.pty = ptyprocess.PtyProcess.spawn(
            ["claude", "--dangerously-skip-permissions"],
            env=env,
            dimensions=(rows, cols),
            cwd=str(project_dir),
        )
        self._running = True
        self._read_task = asyncio.ensure_future(self._read_loop())

    async def _read_loop(self) -> None:
        loop = asyncio.get_event_loop()
        while self._running and self.pty and self.pty.isalive():
            try:
                data = await loop.run_in_executor(None, self._read_chunk)
                if data:
                    msg = json.dumps({"type": "output", "data": data})
                    dead = []
                    for ws in self.clients:
                        try:
                            await ws.send_text(msg)
                        except Exception:
                            dead.append(ws)
                    for ws in dead:
                        self.clients.remove(ws)
            except Exception:
                await asyncio.sleep(0.05)

    def _read_chunk(self) -> str:
        try:
            raw = self.pty.read(4096)
            return raw.decode("utf-8", errors="replace")
        except Exception:
            return ""

    def send_input(self, text: str) -> None:
        if self.pty and self.pty.isalive():
            self.pty.write(text.encode())

    def resize(self, rows: int, cols: int) -> None:
        if self.pty and self.pty.isalive():
            self.pty.setwinsize(rows, cols)

    def stop(self) -> None:
        self._running = False
        if hasattr(self, '_read_task') and self._read_task and not self._read_task.done():
            self._read_task.cancel()
        if self.pty and self.pty.isalive():
            self.pty.terminate()

    def is_alive(self) -> bool:
        return self.pty is not None and self.pty.isalive()


# ─── Project Session ──────────────────────────────────────────────────────────

class ProjectSession:
    def __init__(self, path: str):
        self.session_id = str(uuid.uuid4())[:8]
        self.project_dir = Path(path)
        self.orchestrator = OrchestratorSession()
        self.worker_pool = WorkerPool()
        self.task_queue = TaskQueue(self.project_dir / ".claude")
        self.created_at = time.time()
        self.status_subscribers: list[WebSocket] = []
        self.proposed_tasks_subscribers: list[WebSocket] = []
        self._blockers_mtime: float = 0.0
        self._watch_task: asyncio.Task | None = None
        # Scheduler state
        self._scheduled_start: datetime | None = None
        self._schedule_triggered: bool = False
        self._schedule_loaded: bool = False
        # Run-complete notification state
        self._run_complete: bool = False
        # Iteration loop coroutine
        self._loop_task: asyncio.Task | None = None

    @property
    def name(self) -> str:
        return self.project_dir.name

    @property
    def claude_dir(self) -> Path:
        return self.project_dir / ".claude"

    def _schedule_dict(self) -> dict | None:
        if not self._scheduled_start:
            return None
        now = datetime.now()
        return {
            "at": self._scheduled_start.isoformat(),
            "in_seconds": max(0, int((self._scheduled_start - now).total_seconds())),
            "triggered": self._schedule_triggered,
        }

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "name": self.name,
            "path": str(self.project_dir),
            "worker_count": len(self.worker_pool.all()),
            "running_count": sum(
                1 for w in self.worker_pool.all() if w.status == "running"
            ),
            "alive": self.orchestrator.is_alive(),
            "schedule": self._schedule_dict(),
        }

    def start_watch(self) -> None:
        if self._watch_task is None or self._watch_task.done():
            self._watch_task = asyncio.ensure_future(
                _watch_session_proposed_tasks(self)
            )

    async def _run_supervisor(self) -> None:
        """Iterative review-fix loop (Ralph-style supervisor)."""
        _MODEL_MAP = {
            "haiku": "claude-haiku-4-5-20251001",
            "sonnet": "claude-sonnet-4-6",
            "opus": "claude-opus-4-6",
        }
        consecutive_empty = 0
        while True:
            loop_state = await self.task_queue.get_loop()
            if not loop_state or loop_state["status"] != "running":
                return

            mode = loop_state.get("mode", "review")
            # plan_build mode: two-phase PLAN then BUILD (stub — falls through to review)

            iteration = loop_state["iteration"] + 1
            await self.task_queue.upsert_loop(iteration=iteration)

            # Read artifact
            artifact_path = loop_state["artifact_path"]
            try:
                content = Path(artifact_path).read_text(errors="replace")
            except Exception:
                await self.task_queue.upsert_loop(status="cancelled")
                return

            model_short = loop_state.get("supervisor_model", "sonnet")
            model = _MODEL_MAP.get(model_short, "claude-sonnet-4-6")

            prompt = (
                "Review the following artifact. Output ONLY a JSON array, no prose.\n"
                "Each element must be exactly one of:\n"
                '  {"type":"FIXABLE","description":"...","task":"imperative task description for a worker"}\n'
                '  {"type":"DATA_CHECK","description":"...","query":"what to verify in codebase"}\n'
                '  {"type":"DEFERRED","description":"...","reason":"why human/retraining needed"}\n'
                '  {"type":"CONVERGED","description":"no significant issues"}\n\n'
                "Artifact:\n---ARTIFACT---\n"
                f"{content}\n"
                "---END---"
            )

            prompt_file = self.claude_dir / f"supervisor-iter-{iteration}.md"
            response = ""
            try:
                prompt_file.write_text(prompt)
                proc = await asyncio.create_subprocess_shell(
                    f'claude -p "$(cat {shlex.quote(str(prompt_file))})" '
                    f'--model {model} --dangerously-skip-permissions',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    out, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
                    response = out.decode().strip()
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.communicate()
                    response = ""
            except Exception:
                response = ""
            finally:
                prompt_file.unlink(missing_ok=True)

            if not response.strip():
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    await self.task_queue.upsert_loop(status="cancelled")
                    logger.warning("Loop cancelled: 3 consecutive empty supervisor responses")
                    return
                await asyncio.sleep(5)
                continue
            consecutive_empty = 0

            # Extract JSON array (supervisor may include prose around it)
            findings = []
            m = re.search(r'\[.*\]', response, re.DOTALL)
            if m:
                try:
                    findings = json.loads(m.group())
                except Exception:
                    findings = []

            # Re-check status after supervisor call
            loop_state = await self.task_queue.get_loop()
            if not loop_state or loop_state["status"] != "running":
                return

            context_dir = loop_state.get("context_dir") or str(self.project_dir)
            deferred_items = list(loop_state.get("deferred_items") or [])
            spawned_task_ids: list[str] = []
            converged = False

            for finding in findings:
                ftype = finding.get("type", "")
                if ftype == "CONVERGED":
                    converged = True
                    break
                elif ftype == "FIXABLE":
                    task_desc = (
                        f"[Loop-{iteration}] "
                        f"{finding.get('task', finding.get('description', ''))}"
                    )
                    task = await self.task_queue.add(task_desc, model_short)
                    spawned_task_ids.append(task["id"])
                    _max_w = GLOBAL_SETTINGS.get("max_workers", 0)
                    _running = sum(1 for w in self.worker_pool.workers.values() if w.status == "running")
                    if _max_w <= 0 or _running < _max_w:
                        await self.worker_pool.start_worker(
                            task, self.task_queue, self.project_dir, self.claude_dir
                        )
                    # else: task is queued; status_loop will auto-start it when a slot opens
                elif ftype == "DATA_CHECK":
                    query = finding.get("query", finding.get("description", ""))
                    task_desc = (
                        f"[Loop-{iteration}] Cross-check the following claim against "
                        f"the codebase at {context_dir}.\n"
                        f"Report what you find. Do NOT modify any files.\nQuery: {query}"
                    )
                    task = await self.task_queue.add(task_desc, model_short)
                    spawned_task_ids.append(task["id"])
                    _max_w = GLOBAL_SETTINGS.get("max_workers", 0)
                    _running = sum(1 for w in self.worker_pool.workers.values() if w.status == "running")
                    if _max_w <= 0 or _running < _max_w:
                        await self.worker_pool.start_worker(
                            task, self.task_queue, self.project_dir, self.claude_dir
                        )
                    # else: task is queued; status_loop will auto-start it when a slot opens
                elif ftype == "DEFERRED":
                    deferred_items.append({
                        "description": finding.get("description", ""),
                        "reason": finding.get("reason", ""),
                        "iteration": iteration,
                    })

            await self.task_queue.upsert_loop(deferred_items=deferred_items)

            if converged:
                await self.task_queue.upsert_loop(status="converged")
                return

            # Wait for all spawned workers to finish
            if spawned_task_ids:
                while True:
                    loop_state = await self.task_queue.get_loop()
                    if not loop_state or loop_state["status"] != "running":
                        return
                    all_done = all(
                        (await self.task_queue.get(tid) or {}).get("status") in ("done", "failed")
                        for tid in spawned_task_ids
                    )
                    if all_done:
                        break
                    await asyncio.sleep(3)

            changes_this_iter = len(spawned_task_ids)
            loop_state = await self.task_queue.get_loop()
            if not loop_state:
                return

            changes_history = list(loop_state.get("changes_history") or [])
            changes_history.append(changes_this_iter)

            k = loop_state.get("convergence_k", 2)
            n = loop_state.get("convergence_n", 3)
            max_iter = loop_state.get("max_iterations", 20)

            is_converged = (
                len(changes_history) >= n
                and all(c <= k for c in changes_history[-n:])
            )

            if is_converged or iteration >= max_iter:
                await self.task_queue.upsert_loop(
                    changes_history=changes_history,
                    status="converged",
                )
                return

            await self.task_queue.upsert_loop(changes_history=changes_history)

            # Check if paused/cancelled before starting next iteration
            loop_state = await self.task_queue.get_loop()
            if not loop_state or loop_state["status"] != "running":
                return


# ─── Session Registry ─────────────────────────────────────────────────────────

class SessionRegistry:
    def __init__(self):
        self.sessions: dict[str, ProjectSession] = {}
        self._default_id: str | None = None

    def create(self, path: str) -> ProjectSession:
        s = ProjectSession(path)
        self.sessions[s.session_id] = s
        if self._default_id is None:
            self._default_id = s.session_id
        return s

    def get(self, session_id: str) -> ProjectSession | None:
        return self.sessions.get(session_id)

    def default(self) -> ProjectSession | None:
        return self.sessions.get(self._default_id) if self._default_id else None

    def all(self) -> list[ProjectSession]:
        return list(self.sessions.values())

    def remove(self, session_id: str) -> None:
        s = self.sessions.pop(session_id, None)
        if s:
            s.orchestrator.stop()
            if s._watch_task and not s._watch_task.done():
                s._watch_task.cancel()
            if s._loop_task and not s._loop_task.done():
                s._loop_task.cancel()
        if self._default_id == session_id:
            self._default_id = next(iter(self.sessions), None)


registry = SessionRegistry()


# ─── Dependency: resolve session from ?session= query param ───────────────────

def _resolve_session(session: str | None = Query(default=None)) -> ProjectSession:
    s = registry.get(session) if session else registry.default()
    if s is None:
        raise HTTPException(status_code=404, detail="No active session")
    return s


# ─── Helper: check task dependencies ─────────────────────────────────────────

def _deps_met(task: dict, done_ids: set) -> bool:
    """Return True if all depends_on task IDs are done."""
    deps = task.get("depends_on") or []
    if isinstance(deps, str):
        try:
            deps = json.loads(deps)
        except Exception:
            deps = []
    return all(dep_id in done_ids for dep_id in deps)


# ─── Proposed-tasks watcher ───────────────────────────────────────────────────

async def _watch_session_proposed_tasks(session: ProjectSession) -> None:
    target = session.claude_dir / "proposed-tasks.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch(exist_ok=True)
    try:
        async for _changes in awatch(str(target)):
            content = await asyncio.to_thread(target.read_text) if target.exists() else ""
            msg = json.dumps({
                "type": "proposed_tasks",
                "session_id": session.session_id,
                "content": content,
            })
            dead = []
            for ws in session.proposed_tasks_subscribers:
                try:
                    await ws.send_text(msg)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                session.proposed_tasks_subscribers.remove(ws)
    except asyncio.CancelledError:
        pass


# ─── Blockers check ───────────────────────────────────────────────────────────

async def _check_blockers(session: ProjectSession) -> None:
    f = session.claude_dir / "blockers.md"
    if not f.exists():
        return
    mtime = f.stat().st_mtime
    if mtime <= session._blockers_mtime:
        return
    session._blockers_mtime = mtime
    running = [w for w in session.worker_pool.all() if w.status == "running"]
    if running:
        newest = max(running, key=lambda w: w.started_at)
        newest.status = "blocked"
        await session.task_queue.update(newest.task_id, status="blocked")


# ─── Status broadcast loop ────────────────────────────────────────────────────

async def status_loop():
    while True:
        await asyncio.sleep(1)
        for session in registry.all():
            try:
                # On first tick, restore persisted schedule
                if not session._schedule_loaded:
                    session._schedule_loaded = True
                    saved = await session.task_queue.get_schedule()
                    if saved and not saved["triggered"]:
                        session._scheduled_start = datetime.fromisoformat(saved["scheduled_at"])
                        session._schedule_triggered = False

                await session.worker_pool.poll_all(session.task_queue)
                await _check_blockers(session)

                # Auto-start tasks whose dependencies just became satisfied
                _auto_tasks = await session.task_queue.list()
                _done_ids = {t["id"] for t in _auto_tasks if t["status"] == "done"}
                _newly_ready = [
                    t for t in _auto_tasks
                    if t["status"] == "pending"
                    and _deps_met(t, _done_ids)
                ]
                if _newly_ready and GLOBAL_SETTINGS.get("auto_start", True):
                    _max_w = GLOBAL_SETTINGS.get("max_workers", 0)
                    _running = [w for w in session.worker_pool.all() if w.status == "running"]
                    for _task in _newly_ready:
                        if _max_w > 0 and len(_running) >= _max_w:
                            break
                        _w = await session.worker_pool.start_worker(
                            _task, session.task_queue,
                            session.project_dir, session.claude_dir,
                        )
                        _running.append(_w)

                # Scheduler: auto-start pending tasks at scheduled time
                if session._scheduled_start and not session._schedule_triggered:
                    if datetime.now() >= session._scheduled_start:
                        session._schedule_triggered = True
                        await session.task_queue.save_schedule(
                            session._scheduled_start.isoformat(), triggered=True
                        )
                        tasks = await session.task_queue.list()
                        done_ids = {t["id"] for t in tasks if t["status"] == "done"}
                        pending = [t for t in tasks if t["status"] in ("pending", "queued")]
                        for task in pending:
                            if _deps_met(task, done_ids):
                                await session.worker_pool.start_worker(
                                    task, session.task_queue,
                                    session.project_dir, session.claude_dir,
                                )

                tasks = await session.task_queue.list()
                workers = [w.to_dict() for w in session.worker_pool.all()]

                # Detect run-complete (all workers idle, no pending tasks, but some done)
                running_workers = [w for w in session.worker_pool.all() if w.status == "running"]
                pending_tasks = [t for t in tasks if t["status"] in ("pending", "queued")]
                done_tasks = [t for t in tasks if t["status"] in ("done", "failed")]
                if not running_workers and not pending_tasks and done_tasks and not session._run_complete:
                    session._run_complete = True
                elif pending_tasks or running_workers:
                    session._run_complete = False

                total = len(tasks)
                done_count = sum(1 for t in tasks if t["status"] in ("done", "failed"))
                success_count = sum(1 for t in tasks if t["status"] == "done")
                progress_pct = int(done_count / total * 100) if total > 0 else 0
                success_rate = int(success_count / done_count * 100) if done_count > 0 else 0

                done_workers = [w for w in session.worker_pool.all() if w.status in ("done", "failed")]
                avg_s = (
                    sum(w.elapsed_s for w in done_workers) / len(done_workers)
                    if done_workers else 300
                )
                remaining = total - done_count
                eta_seconds = int(avg_s * remaining) if remaining > 0 else 0

                loop_state = await session.task_queue.get_loop()
                msg = json.dumps({
                    "type": "status",
                    "session_id": session.session_id,
                    "workers": workers,
                    "queue": tasks,
                    "progress_pct": progress_pct,
                    "eta_seconds": eta_seconds,
                    "success_rate": success_rate,
                    "schedule": session._schedule_dict(),
                    "run_complete": session._run_complete,
                    "loop_state": loop_state,
                })
                dead = []
                for ws in session.status_subscribers:
                    try:
                        await ws.send_text(msg)
                    except Exception:
                        dead.append(ws)
                for ws in dead:
                    session.status_subscribers.remove(ws)
            except Exception as exc:
                logger.exception("status_loop error for session %s: %s", getattr(session, 'session_id', '?'), exc)


@app.on_event("startup")
async def startup():
    if os.environ.get("ORCHESTRATOR_PROJECT_DIR"):
        default_session = registry.create(str(PROJECT_DIR))
        default_session.start_watch()
    asyncio.ensure_future(status_loop())


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
    session = registry.create(str(path))
    rows = int(body.get("rows", 24))
    cols = int(body.get("cols", 80))
    session.orchestrator.start(session.project_dir, rows=rows, cols=cols)
    session.start_watch()
    return session.to_dict()



@app.get("/api/sessions/overview")
async def sessions_overview():
    result = []
    for s in registry.all():
        tasks = await s.task_queue.list()
        pending = sum(1 for t in tasks if t["status"] in ("pending", "queued"))
        running = sum(1 for t in tasks if t["status"] == "running")
        done = sum(1 for t in tasks if t["status"] == "done")
        failed = sum(1 for t in tasks if t["status"] == "failed")
        total_attempted = done + failed
        success_rate = round(done / total_attempted * 100) if total_attempted else None
        done_workers = [w for w in s.worker_pool.all() if w.status == "done"]
        avg_s = (sum(w.elapsed_s for w in done_workers) / len(done_workers)) if done_workers else None
        eta_s = round(avg_s * pending / max(1, running)) if (avg_s and pending) else None
        result.append({
            "session_id": s.session_id,
            "name": s.name,
            "pending": pending,
            "running": running,
            "done": done,
            "failed": failed,
            "success_rate": success_rate,
            "eta_seconds": eta_s,
        })
    return result


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
    artifact_path = body.get("artifact_path", "").strip()
    if not artifact_path:
        raise HTTPException(status_code=400, detail="artifact_path required")
    context_dir = body.get("context_dir") or None
    convergence_k = int(body.get("convergence_k", GLOBAL_SETTINGS.get("loop_convergence_k", 2)))
    convergence_n = int(body.get("convergence_n", GLOBAL_SETTINGS.get("loop_convergence_n", 3)))
    max_iterations = int(body.get("max_iterations", GLOBAL_SETTINGS.get("loop_max_iterations", 20)))
    supervisor_model = body.get("supervisor_model", GLOBAL_SETTINGS.get("loop_supervisor_model", "sonnet"))
    mode = body.get("mode", "review")

    # Cancel any running loop coroutine
    if s._loop_task and not s._loop_task.done():
        s._loop_task.cancel()
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

    s._loop_task = asyncio.ensure_future(s._run_supervisor())
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
        s._loop_task = asyncio.ensure_future(s._run_supervisor())
    return await s.task_queue.get_loop()


@app.delete("/api/sessions/{session_id}/loop")
async def cancel_loop(session_id: str):
    s = registry.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    if s._loop_task and not s._loop_task.done():
        s._loop_task.cancel()
        s._loop_task = None
    await s.task_queue.upsert_loop(
        status="cancelled", iteration=0, changes_history=[], deferred_items=[]
    )
    return {"ok": True}


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
        raise HTTPException(status_code=400, detail=f"Invalid time format: {e}")


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
                s.orchestrator.send_input(msg["data"])
            elif msg.get("type") == "resize":
                s.orchestrator.resize(msg.get("rows", 24), msg.get("cols", 80))
    except WebSocketDisconnect:
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
        if websocket in s.status_subscribers:
            s.status_subscribers.remove(websocket)
        if websocket in s.proposed_tasks_subscribers:
            s.proposed_tasks_subscribers.remove(websocket)


# ─── REST: Tasks ──────────────────────────────────────────────────────────────

@app.get("/api/tasks")
async def list_tasks(s: ProjectSession = Depends(_resolve_session)):
    return await s.task_queue.list()


@app.post("/api/tasks")
async def create_task(body: dict, s: ProjectSession = Depends(_resolve_session)):
    description = body.get("description", "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="description is required")
    task = await s.task_queue.add(
        description=description,
        model=body.get("model") or GLOBAL_SETTINGS.get("default_model", "sonnet"),
    )
    asyncio.ensure_future(
        _score_task(task["id"], task["description"], s.task_queue._db_path, s.claude_dir)
    )
    return task


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str, s: ProjectSession = Depends(_resolve_session)):
    ok = await s.task_queue.delete(task_id)
    return {"ok": ok}


@app.post("/api/tasks/import-proposed")
async def import_proposed(
    body: dict = Body(default={}),
    s: ProjectSession = Depends(_resolve_session),
):
    content = (body or {}).get("content")
    tasks = await s.task_queue.import_from_proposed(content=content)
    return {"imported": len(tasks), "tasks": tasks}


@app.post("/api/tasks/start-all")
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


@app.post("/api/tasks/retry-failed")
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
        new_task = await s.task_queue.add(retry_desc, t.get("model") or GLOBAL_SETTINGS.get("default_model", "sonnet"))
        retried.append(new_task["id"])
    return {"retried": len(retried), "task_ids": retried}


@app.post("/api/tasks/{task_id}/run")
async def run_task(task_id: str, s: ProjectSession = Depends(_resolve_session)):
    task = await s.task_queue.get(task_id)
    if not task:
        return {"error": "Task not found"}
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


@app.post("/api/tasks/{task_id}/depends-on")
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


# ─── REST: Workers ────────────────────────────────────────────────────────────

@app.get("/api/workers")
async def list_workers(s: ProjectSession = Depends(_resolve_session)):
    return [w.to_dict() for w in s.worker_pool.all()]


@app.post("/api/workers/{worker_id}/pause")
async def pause_worker(worker_id: str, s: ProjectSession = Depends(_resolve_session)):
    w = s.worker_pool.get(worker_id)
    if not w:
        return {"error": "Worker not found"}
    w.pause()
    await s.task_queue.update(w.task_id, status="paused")
    return {"status": w.status}


@app.post("/api/workers/{worker_id}/resume")
async def resume_worker(worker_id: str, s: ProjectSession = Depends(_resolve_session)):
    w = s.worker_pool.get(worker_id)
    if not w:
        return {"error": "Worker not found"}
    w.resume()
    await s.task_queue.update(w.task_id, status="running")
    return {"status": w.status}


@app.post("/api/workers/{worker_id}/message")
async def message_worker(
    worker_id: str, body: dict, s: ProjectSession = Depends(_resolve_session)
):
    w = s.worker_pool.get(worker_id)
    if not w:
        return {"error": "Worker not found"}
    user_message = body.get("message", "")
    original_desc = w.description
    await w.stop()
    new_desc = f"{original_desc}\n\n---\n**Additional context from user:**\n{user_message}"
    new_task = await s.task_queue.add(new_desc, w.model)
    new_worker = await s.worker_pool.start_worker(
        new_task, s.task_queue, s.project_dir, s.claude_dir
    )
    return {"new_worker_id": new_worker.id, "new_task_id": new_task["id"]}


@app.post("/api/sessions/{session_id}/workers/broadcast")
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


@app.get("/api/sessions/{session_id}/agents-md")
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
        return {"agents_md": f"# File Ownership\n\n(error: {e})\n"}
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


@app.get("/api/workers/{worker_id}/log")
async def get_worker_log(
    worker_id: str, lines: int = 100, s: ProjectSession = Depends(_resolve_session)
):
    w = s.worker_pool.get(worker_id)
    if not w:
        return {"error": "Worker not found"}
    if not w._log_path or not w._log_path.exists():
        return {"log": ""}
    try:
        text = w._log_path.read_text(errors="replace")
        tail = "\n".join(text.splitlines()[-lines:])
        return {"log": tail, "path": str(w._log_path)}
    except Exception as e:
        return {"log": f"Error reading log: {e}"}


# ─── REST: Merge All Done → AI PR Pipeline ────────────────────────────────────

@app.post("/api/tasks/merge-all-done")
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
            pr_out, pr_err = await asyncio.wait_for(pr_proc.communicate(), timeout=60)
            if pr_proc.returncode != 0:
                results.append({"worker_id": w.id, "error": pr_err.decode().strip()})
                continue
            pr_url = pr_out.decode().strip()
            w.pr_url = pr_url
            created += 1
            if GLOBAL_SETTINGS.get("auto_review", True):
                asyncio.ensure_future(_write_pr_review(pr_url, w.description, s.project_dir))
            if branch.startswith("orchestrator/task-") and GLOBAL_SETTINGS.get("auto_merge", True):
                merge_proc = await asyncio.create_subprocess_shell(
                    f'gh pr merge {pr_url} --squash --delete-branch',
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    cwd=str(s.project_dir),
                )
                await asyncio.wait_for(merge_proc.communicate(), timeout=60)
                if merge_proc.returncode == 0:
                    w.pr_merged = True
                    merged += 1
                    asyncio.ensure_future(_write_progress_entry(
                        task_description=w.description,
                        log_path=w._log_path,
                        project_dir=s.project_dir,
                    ))
            results.append({"worker_id": w.id, "pr_url": pr_url})
        except Exception as e:
            results.append({"worker_id": w.id, "error": str(e)})
    return {"created": created, "merged": merged, "results": results}


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

    return {
        "today": today_entry,
        "this_week": {"messages": week_messages, "sessions": week_sessions},
        "daily": sorted(daily, key=lambda e: e["date"]),
        "last_updated": last_updated,
        "total_sessions": total_sessions,
    }


@app.get("/api/usage")
async def get_usage():
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _get_usage)


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
