"""
Orchestrator task queue — SQLite-backed CRUD for tasks, loops, messages, interventions.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path

import aiosqlite

from config import (
    _ALLOWED_LOOP_COLS,
    _ALLOWED_TASK_COLS,
    _MODEL_ALIASES,
    GLOBAL_SETTINGS,
    _deps_met,
)

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
                        score_note TEXT,
                        own_files TEXT DEFAULT '[]',
                        forbidden_files TEXT DEFAULT '[]',
                        gh_issue_number INTEGER,
                        is_critical_path INTEGER DEFAULT 0
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
                        mode TEXT DEFAULT 'review',
                        plan_phase TEXT DEFAULT 'plan'
                    )
                """)
                # Migration: add mode column for existing DBs that predate this column
                try:
                    await db.execute("ALTER TABLE iteration_loops ADD COLUMN mode TEXT DEFAULT 'review'")
                except Exception:
                    pass  # column already exists
                try:
                    await db.execute("ALTER TABLE iteration_loops ADD COLUMN plan_phase TEXT DEFAULT 'plan'")
                except Exception:
                    pass  # column already exists
                # Migration: add file ownership columns for existing DBs
                try:
                    await db.execute("ALTER TABLE tasks ADD COLUMN own_files TEXT DEFAULT '[]'")
                except Exception:
                    pass
                try:
                    await db.execute("ALTER TABLE tasks ADD COLUMN forbidden_files TEXT DEFAULT '[]'")
                except Exception:
                    pass
                try:
                    await db.execute("ALTER TABLE tasks ADD COLUMN gh_issue_number INTEGER")
                except Exception:
                    pass
                try:
                    await db.execute("ALTER TABLE tasks ADD COLUMN is_critical_path INTEGER DEFAULT 0")
                except Exception:
                    pass
                # Token/cost tracking columns
                try:
                    await db.execute("ALTER TABLE tasks ADD COLUMN input_tokens INTEGER")
                except Exception:
                    pass
                try:
                    await db.execute("ALTER TABLE tasks ADD COLUMN output_tokens INTEGER")
                except Exception:
                    pass
                try:
                    await db.execute("ALTER TABLE tasks ADD COLUMN estimated_cost REAL")
                except Exception:
                    pass
                try:
                    await db.execute("ALTER TABLE tasks ADD COLUMN task_type TEXT DEFAULT 'AUTO'")
                except Exception:
                    pass
                try:
                    await db.execute("ALTER TABLE tasks ADD COLUMN source_ref TEXT")
                except Exception:
                    pass
                try:
                    await db.execute("ALTER TABLE tasks ADD COLUMN parent_task_id TEXT")
                except Exception:
                    pass
                try:
                    await db.execute("ALTER TABLE tasks ADD COLUMN priority_score REAL DEFAULT 0.0")
                except Exception:
                    pass
                try:
                    await db.execute("ALTER TABLE tasks ADD COLUMN handoff_type TEXT")
                except Exception:
                    pass
                try:
                    await db.execute("ALTER TABLE tasks ADD COLUMN handoff_payload TEXT DEFAULT '{}'")
                except Exception:
                    pass
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS worker_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        to_task_id TEXT NOT NULL,
                        from_task_id TEXT,
                        content TEXT NOT NULL,
                        created_at REAL,
                        read INTEGER DEFAULT 0
                    )
                """)
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS interventions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        failure_pattern TEXT NOT NULL,
                        correction TEXT NOT NULL,
                        task_description_hint TEXT,
                        success INTEGER DEFAULT 0,
                        source_task_id TEXT,
                        spawned_task_id TEXT,
                        created_at REAL
                    )
                """)
                # Ideas tables (Phase 13)
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS ideas (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        content TEXT NOT NULL,
                        status TEXT DEFAULT 'raw',
                        ai_evaluation TEXT,
                        priority INTEGER DEFAULT 0,
                        source TEXT DEFAULT 'human',
                        project TEXT,
                        promoted_to TEXT,
                        created_at TEXT DEFAULT (datetime('now')),
                        updated_at TEXT DEFAULT (datetime('now'))
                    )
                """)
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS idea_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        idea_id INTEGER NOT NULL REFERENCES ideas(id),
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at TEXT DEFAULT (datetime('now'))
                    )
                """)
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
        for key in ("depends_on", "own_files", "forbidden_files"):
            raw = d.get(key)
            if isinstance(raw, str):
                try:
                    d[key] = json.loads(raw)
                except Exception:
                    d[key] = []
            elif raw is None:
                d[key] = []
        return d

    # ─── Task CRUD ───────────────────────────────────────────────────────────

    async def list(self) -> list[dict]:
        await self._ensure_db()
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM tasks ORDER BY priority_score DESC, created_at ASC") as cur:
                rows = await cur.fetchall()
        return [self._row_to_dict(r) for r in rows]

    async def add(self, description: str, model: str = "sonnet",
                  own_files: list[str] | None = None,
                  forbidden_files: list[str] | None = None,
                  is_critical_path: bool = False,
                  task_type: str = "AUTO",
                  source_ref: str | None = None,
                  parent_task_id: str | None = None) -> dict:
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
            "own_files": own_files or [],
            "forbidden_files": forbidden_files or [],
            "is_critical_path": int(is_critical_path),
            "task_type": task_type,
            "source_ref": source_ref,
            "parent_task_id": parent_task_id,
        }
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.execute(
                """INSERT INTO tasks
                   (id, description, model, timeout, retries, status, worker_id,
                    started_at, elapsed_s, last_commit, log_file, failed_reason,
                    created_at, depends_on, score, score_note, own_files, forbidden_files,
                    is_critical_path, task_type, source_ref, parent_task_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    task["id"], task["description"], task["model"],
                    task["timeout"], task["retries"], task["status"],
                    task["worker_id"], task["started_at"], task["elapsed_s"],
                    task["last_commit"], task["log_file"], task["failed_reason"],
                    task["created_at"], json.dumps(task["depends_on"]),
                    task["score"], task["score_note"],
                    json.dumps(task["own_files"]), json.dumps(task["forbidden_files"]),
                    task["is_critical_path"], task["task_type"], task["source_ref"],
                    task["parent_task_id"],
                ),
            )
            await db.commit()
        return task

    async def update(self, task_id: str, **kwargs) -> dict | None:
        await self._ensure_db()
        if not kwargs:
            return await self.get(task_id)
        for key in ("depends_on", "own_files", "forbidden_files"):
            if key in kwargs:
                val = kwargs[key]
                kwargs[key] = json.dumps(val) if not isinstance(val, str) else val
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

    # ─── Scheduling ──────────────────────────────────────────────────────────

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

    # ─── Iteration Loops ─────────────────────────────────────────────────────

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
            from datetime import datetime
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
                    "plan_phase": "plan",
                    "created_at": now,
                    "updated_at": now,
                }
                fields.update(kwargs)
                async with aiosqlite.connect(str(self._db_path)) as db:
                    await db.execute(
                        """INSERT INTO iteration_loops
                           (name, artifact_path, context_dir, status, iteration,
                            changes_history, deferred_items, convergence_k, convergence_n,
                            max_iterations, supervisor_model, mode, plan_phase, created_at, updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            fields["name"], fields["artifact_path"], fields["context_dir"],
                            fields["status"], fields["iteration"], fields["changes_history"],
                            fields["deferred_items"], fields["convergence_k"],
                            fields["convergence_n"], fields["max_iterations"],
                            fields["supervisor_model"], fields.get("mode", "review"),
                            fields.get("plan_phase", "plan"),
                            fields["created_at"], fields["updated_at"],
                        ),
                    )
                    await db.commit()
            else:
                update = dict(kwargs)
                update["updated_at"] = now
                for k in update:
                    if k not in _ALLOWED_LOOP_COLS:
                        raise ValueError(f"Unknown loop column: {k}")
                set_clause = ", ".join(f"{k} = ?" for k in update)
                values = list(update.values()) + [existing["id"]]
                async with aiosqlite.connect(str(self._db_path)) as db:
                    await db.execute(
                        f"UPDATE iteration_loops SET {set_clause} WHERE id = ?", values
                    )
                    await db.commit()
            return await self.get_loop()

    # ─── Import from proposed-tasks.md ───────────────────────────────────────

    async def import_from_proposed(self, content: str | None = None) -> tuple[list[dict], dict]:
        """Parse ===TASK=== blocks and add to queue, skipping duplicates.
        Returns (added_tasks, skip_counts) where skip_counts maps status→count."""
        if content is None:
            f = self._proposed_tasks_file()
            if not f.exists():
                return [], {}
            content = f.read_text()
        blocks = content.split("===TASK===")
        added = []
        skip_counts: dict[str, int] = {}
        await self._ensure_db()
        existing = await self.list()
        existing_by_desc = {t["description"]: t["status"] for t in existing}
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            lines = block.splitlines()
            model = GLOBAL_SETTINGS.get("default_model", "sonnet")
            timeout = 600
            retries = 2
            task_type = "AUTO"
            depends_on: list[str] = []
            desc_lines = []
            in_header = True
            for line in lines:
                if in_header and line.startswith("model:"):
                    model = line.split(":", 1)[1].strip()
                    model = _MODEL_ALIASES.get(model, model)
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
                elif in_header and line.startswith("TYPE:"):
                    val = line.split(":", 1)[1].strip().upper()
                    task_type = val if val in ("HORIZONTAL", "VERTICAL", "AUTO") else "AUTO"
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
            # Parse OWN_FILES / FORBIDDEN_FILES from description body
            own_files: list[str] = []
            forbidden_files: list[str] = []
            for dl in desc_lines:
                stripped = dl.strip()
                if stripped.startswith("OWN_FILES:"):
                    own_files = [p.strip() for p in stripped.split(":", 1)[1].split(",") if p.strip()]
                elif stripped.startswith("FORBIDDEN_FILES:"):
                    forbidden_files = [p.strip() for p in stripped.split(":", 1)[1].split(",") if p.strip()]
            if description and description in existing_by_desc:
                st = existing_by_desc[description]
                skip_counts[st] = skip_counts.get(st, 0) + 1
                continue
            if description:
                task = await self.add(
                    description=description,
                    model=model,
                    own_files=own_files,
                    forbidden_files=forbidden_files,
                    task_type=task_type,
                )
                if depends_on:
                    await self.update(task["id"], depends_on=depends_on)
                    task["depends_on"] = depends_on
                existing_by_desc[description] = "pending"
                added.append(task)
        return added, skip_counts

    # ─── Cross-worker Messages ────────────────────────────────────────────────

    async def send_message(self, to_task_id: str, content: str, from_task_id: str | None = None) -> dict:
        await self._ensure_db()
        msg = {"to_task_id": to_task_id, "from_task_id": from_task_id,
               "content": content, "created_at": time.time(), "read": 0}
        async with aiosqlite.connect(str(self._db_path)) as db:
            cur = await db.execute(
                "INSERT INTO worker_messages (to_task_id, from_task_id, content, created_at, read) VALUES (?,?,?,?,?)",
                (to_task_id, from_task_id, content, msg["created_at"], 0),
            )
            await db.commit()
            msg["id"] = cur.lastrowid
        return msg

    async def get_messages(self, task_id: str, unread_only: bool = True) -> list[dict]:
        await self._ensure_db()
        sql = "SELECT * FROM worker_messages WHERE to_task_id = ?"
        if unread_only:
            sql += " AND read = 0"
        sql += " ORDER BY created_at"
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, (task_id,)) as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def mark_messages_read(self, task_id: str) -> int:
        await self._ensure_db()
        async with aiosqlite.connect(str(self._db_path)) as db:
            cur = await db.execute(
                "UPDATE worker_messages SET read = 1 WHERE to_task_id = ? AND read = 0",
                (task_id,),
            )
            await db.commit()
            return cur.rowcount

    # ─── Interventions ───────────────────────────────────────────────────────

    async def record_intervention(
        self, failure_pattern: str, correction: str,
        task_description_hint: str | None = None,
        source_task_id: str | None = None,
        spawned_task_id: str | None = None,
    ) -> int:
        await self._ensure_db()
        async with aiosqlite.connect(str(self._db_path)) as db:
            cur = await db.execute(
                """INSERT INTO interventions
                   (failure_pattern, correction, task_description_hint,
                    source_task_id, spawned_task_id, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (failure_pattern, correction, task_description_hint,
                 source_task_id, spawned_task_id, time.time()),
            )
            await db.commit()
            return cur.lastrowid

    async def mark_intervention_success(self, spawned_task_id: str) -> None:
        await self._ensure_db()
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.execute(
                "UPDATE interventions SET success = 1 WHERE spawned_task_id = ?",
                (spawned_task_id,),
            )
            await db.commit()

    async def find_matching_intervention(self, failure_pattern: str) -> dict | None:
        if not failure_pattern or len(failure_pattern.strip()) < 10:
            return None
        await self._ensure_db()
        first_line = failure_pattern.strip().splitlines()[0].strip().lower()
        if len(first_line) < 10:
            return None
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM interventions WHERE success = 1 ORDER BY created_at DESC"
            ) as cur:
                rows = await cur.fetchall()
        for row in rows:
            stored = (row["failure_pattern"] or "").strip().splitlines()
            if stored and first_line in stored[0].strip().lower():
                return dict(row)
        return None

    async def list_interventions(self, limit: int = 50) -> list[dict]:
        await self._ensure_db()
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM interventions ORDER BY created_at DESC LIMIT ?", (limit,)
            ) as cur:
                return [dict(r) for r in await cur.fetchall()]

    # ─── Swarm Claiming ──────────────────────────────────────────────────────

    async def claim_next_pending(self, done_ids: set[str]) -> dict | None:
        """Atomically claim the next pending task whose deps are met.

        Uses SQLite serialized writes: UPDATE ... WHERE status='pending'
        with rowcount > 0 meaning we won the claim. No Python lock needed.
        """
        await self._ensure_db()
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM tasks WHERE status = 'pending' ORDER BY priority_score DESC, created_at ASC"
            ) as cur:
                candidates = [self._row_to_dict(r) for r in await cur.fetchall()]

        for task in candidates:
            if not _deps_met(task, done_ids):
                continue
            # Atomic CAS: only succeeds if still pending
            async with aiosqlite.connect(str(self._db_path)) as db:
                cur = await db.execute(
                    "UPDATE tasks SET status = 'running' WHERE id = ? AND status = 'pending'",
                    (task["id"],),
                )
                await db.commit()
                if cur.rowcount > 0:
                    task["status"] = "running"
                    return task
        return None
