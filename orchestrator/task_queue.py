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

import logging

from evidence_bundle import (
    EvidenceBundle,
    EvidenceLifecycle,
    advance_evidence_bundle,
    create_evidence_bundle,
    validate_evidence_chain,
)
from eval_candidates import (
    SCHEMA_VERSION as EVAL_CANDIDATE_SCHEMA_VERSION,
    canonical_diff_digest,
    row_to_dict as eval_candidate_row_to_dict,
    validate_evidence_digest,
    validate_identifier,
    validate_status,
    validate_trigger,
)
from runtime_redaction import merge_metadata, redact_runtime
from task_schema import _redact_text_fields, ensure_schema
from compatibility_telemetry import TASKS_SQLITE_PROVIDER, record_compatibility_use
from config import (
    _ALLOWED_LOOP_COLS,
    _ALLOWED_TASK_COLS,
    _MODEL_ALIASES,
    GLOBAL_SETTINGS,
    _deps_met,
    _detect_dep_cycle,
)

logger = logging.getLogger(__name__)



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
        """Create the schema once. The DDL itself lives in task_schema.py."""
        async with self._init_lock:
            if self._initialized:
                return
            await ensure_schema(self._db_path, self._claude_dir)
            self._initialized = True

    def _row_to_dict(self, row) -> dict:
        d = dict(row)
        d.pop("provider", None)
        for key in (
            "depends_on",
            "own_files",
            "forbidden_files",
            "execution_requirements",
            "execution_envelope",
            "redaction_metadata",
        ):
            raw = d.get(key)
            if isinstance(raw, str):
                try:
                    d[key] = json.loads(raw)
                except Exception:
                    d[key] = (
                        []
                        if key in {"depends_on", "own_files", "forbidden_files"}
                        else ({} if key == "redaction_metadata" else None)
                    )
            elif raw is None:
                d[key] = (
                    []
                    if key in {"depends_on", "own_files", "forbidden_files"}
                    else ({} if key == "redaction_metadata" else None)
                )
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
                  parent_task_id: str | None = None,
                  phase: str = "implement",
                  agent_runtime: str | None = None,
                  provider: str | None = None,
                  connection: str | None = None,
                  execution_profile: str | None = None,
                  execution_requirements: dict | None = None,
                  effort: str | None = None) -> dict:
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
            "phase": phase,
            "agent_runtime": agent_runtime or provider,
            "connection": connection,
            "execution_profile": execution_profile,
            "execution_requirements": execution_requirements or {},
            "execution_envelope": None,
            "effort": effort,
            "route_reason": None,
        }
        task, redaction_metadata = _redact_text_fields(task)
        task["redaction_metadata"] = redaction_metadata
        async with aiosqlite.connect(str(self._db_path)) as db:
            await db.execute(
                """INSERT INTO tasks
                   (id, description, model, timeout, retries, status, worker_id,
                    started_at, elapsed_s, last_commit, log_file, failed_reason,
                    created_at, depends_on, score, score_note, own_files, forbidden_files,
                    is_critical_path, task_type, source_ref, parent_task_id, phase,
                    agent_runtime, provider, connection, execution_profile,
                    execution_requirements, execution_envelope, effort, route_reason,
                    redaction_metadata)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    task["id"], task["description"], task["model"],
                    task["timeout"], task["retries"], task["status"],
                    task["worker_id"], task["started_at"], task["elapsed_s"],
                    task["last_commit"], task["log_file"], task["failed_reason"],
                    task["created_at"], json.dumps(task["depends_on"]),
                    task["score"], task["score_note"],
                    json.dumps(task["own_files"]), json.dumps(task["forbidden_files"]),
                    task["is_critical_path"], task["task_type"], task["source_ref"],
                    task["parent_task_id"], task["phase"], task["agent_runtime"],
                    None, task["connection"], task["execution_profile"],
                    json.dumps(task["execution_requirements"]),
                    task["execution_envelope"], task["effort"], task["route_reason"],
                    json.dumps(task["redaction_metadata"]),
                ),
            )
            await db.commit()
        return task

    async def update(self, task_id: str, **kwargs) -> dict | None:
        await self._ensure_db()
        if not kwargs:
            return await self.get(task_id)
        kwargs, new_redaction_metadata = _redact_text_fields(kwargs)
        for key in (
            "depends_on",
            "own_files",
            "forbidden_files",
            "execution_requirements",
            "execution_envelope",
        ):
            if key in kwargs:
                val = kwargs[key]
                kwargs[key] = json.dumps(val) if not isinstance(val, str) else val
        for k in kwargs:
            if k not in _ALLOWED_TASK_COLS:
                raise ValueError(f"Unknown task column: {k}")
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [task_id]
        async with aiosqlite.connect(str(self._db_path)) as db:
            if new_redaction_metadata:
                async with db.execute(
                    "SELECT redaction_metadata FROM tasks WHERE id = ?", (task_id,)
                ) as cur:
                    row = await cur.fetchone()
                existing = {}
                if row and row[0]:
                    try:
                        existing = json.loads(row[0])
                    except (TypeError, json.JSONDecodeError):
                        existing = {}
                kwargs["redaction_metadata"] = json.dumps(
                    merge_metadata(existing, new_redaction_metadata).to_dict()
                )
                set_clause = ", ".join(f"{k} = ?" for k in kwargs)
                values = list(kwargs.values()) + [task_id]
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

    async def get_recent_completions(
        self, exclude_task_id: str | None = None, limit: int = 5, since_seconds: int = 86400
    ) -> list[dict]:
        """Return recently-done tasks with completion_summary (multi-agent context archival).

        Used by workers on startup to gain awareness of what sibling tasks accomplished.
        Returns compact dicts: {id, description (first 80 chars), completion_summary}.
        """
        await self._ensure_db()
        cutoff = time.time() - since_seconds
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            sql = (
                "SELECT id, description, completion_summary "
                "FROM tasks "
                "WHERE status = 'done' AND completion_summary IS NOT NULL "
                "AND created_at >= ?"
            )
            params: list = [cutoff]
            if exclude_task_id:
                sql += " AND id != ?"
                params.append(exclude_task_id)
            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            async with db.execute(sql, params) as cur:
                rows = await cur.fetchall()
        return [
            {
                "id": row["id"],
                "description": (row["description"] or "")[:80],
                "completion_summary": row["completion_summary"],
            }
            for row in rows
        ]

    # ─── Context Versioning (Multi-agent Gap 1) ──────────────────────────────

    async def get_context_version(self) -> int:
        """Return current context version = count of completed tasks.

        Used to detect stale context: if a worker was queued when version=N but
        N tasks have since completed, the codebase may have changed significantly.
        Workers receive their context_version at task-file build time.
        """
        await self._ensure_db()
        async with aiosqlite.connect(str(self._db_path)) as db:
            async with db.execute("SELECT COUNT(*) FROM tasks WHERE status='done'") as cur:
                row = await cur.fetchone()
                return row[0] if row else 0

    async def stamp_context_version(self, task_id: str) -> int:
        """Stamp a task with the current context version. Returns the version stamped."""
        version = await self.get_context_version()
        await self.update(task_id, context_version=version)
        return version

    async def clear_completed_dep(self, completed_task_id: str) -> int:
        """Remove completed_task_id from depends_on of all pending/queued sibling tasks.

        Called after a task auto-commits to keep dependency lists current (learn-cc s12
        bidirectional dep clearing). Returns number of tasks updated.
        """
        await self._ensure_db()
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, depends_on FROM tasks WHERE status IN ('pending','queued')"
            ) as cur:
                rows = await cur.fetchall()
        updated = 0
        for row in rows:
            deps_raw = row["depends_on"] or "[]"
            try:
                deps = json.loads(deps_raw) if isinstance(deps_raw, str) else (deps_raw or [])
            except Exception:
                deps = []
            if completed_task_id in deps:
                deps = [d for d in deps if d != completed_task_id]
                await self.update(row["id"], depends_on=deps)
                updated += 1
        return updated

    async def get_pass_at_k_metrics(self) -> dict:
        """Return pass@k style success metrics across all tasks (ECC eval-harness pattern).

        Returns aggregated stats: total tasks, success rate, oracle-pass rate by attempt count.
        """
        await self._ensure_db()
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT status, attempt_count FROM tasks WHERE status IN ('done','failed')"
            ) as cur:
                rows = await cur.fetchall()
        total = len(rows)
        if total == 0:
            return {"total": 0, "pass_rate": 0.0, "pass_at_1": 0.0, "pass_at_2": 0.0}
        done = sum(1 for r in rows if r["status"] == "done")
        pass_at_1 = sum(1 for r in rows if r["status"] == "done" and (r["attempt_count"] or 0) <= 1)
        pass_at_2 = sum(1 for r in rows if r["status"] == "done" and (r["attempt_count"] or 0) <= 2)
        return {
            "total": total,
            "done": done,
            "failed": total - done,
            "pass_rate": round(done / total, 3),
            "pass_at_1": round(pass_at_1 / total, 3),
            "pass_at_2": round(pass_at_2 / total, 3),
        }

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
                    "plan_item_reject_streak": 0,
                    "created_at": now,
                    "updated_at": now,
                }
                fields.update(kwargs)
                async with aiosqlite.connect(str(self._db_path)) as db:
                    await db.execute(
                        """INSERT INTO iteration_loops
                           (name, artifact_path, context_dir, status, iteration,
                            changes_history, deferred_items, convergence_k, convergence_n,
                            max_iterations, supervisor_model, mode, plan_phase,
                            plan_item_reject_streak, created_at, updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            fields["name"], fields["artifact_path"], fields["context_dir"],
                            fields["status"], fields["iteration"], fields["changes_history"],
                            fields["deferred_items"], fields["convergence_k"],
                            fields["convergence_n"], fields["max_iterations"],
                            fields["supervisor_model"], fields.get("mode", "review"),
                            fields.get("plan_phase", "plan"),
                            fields.get("plan_item_reject_streak", 0),
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
        # Multi-agent Gap 6: circular dependency detection (small effort).
        # Check newly-added tasks for cycles and log a warning if found.
        # We don't abort the import — let the swarm detect deadlock and report it.
        if added:
            cycle = _detect_dep_cycle(added)
            if cycle:
                logger.warning(
                    "import_from_proposed: circular dependency detected in new tasks: %s",
                    " → ".join(cycle)
                )
        return added, skip_counts

    # ─── Cross-worker Messages ────────────────────────────────────────────────

    async def send_message(self, to_task_id: str, content: str, from_task_id: str | None = None) -> dict:
        await self._ensure_db()
        redaction = redact_runtime(content, field_path="$.worker_messages.content")
        content = str(redaction.value)
        metadata = redaction.metadata.to_dict() if redaction.metadata.redacted else {}
        msg = {"to_task_id": to_task_id, "from_task_id": from_task_id,
               "content": content, "created_at": time.time(), "read": 0,
               "redaction_metadata": metadata}
        async with aiosqlite.connect(str(self._db_path)) as db:
            cur = await db.execute(
                "INSERT INTO worker_messages "
                "(to_task_id, from_task_id, content, created_at, read, redaction_metadata) "
                "VALUES (?,?,?,?,?,?)",
                (
                    to_task_id,
                    from_task_id,
                    content,
                    msg["created_at"],
                    0,
                    json.dumps(metadata),
                ),
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
                messages = [dict(r) for r in await cur.fetchall()]
        for message in messages:
            try:
                message["redaction_metadata"] = json.loads(
                    message.get("redaction_metadata") or "{}"
                )
            except (TypeError, json.JSONDecodeError):
                message["redaction_metadata"] = {}
        return messages

    async def mark_messages_read(self, task_id: str) -> int:
        await self._ensure_db()
        async with aiosqlite.connect(str(self._db_path)) as db:
            cur = await db.execute(
                "UPDATE worker_messages SET read = 1 WHERE to_task_id = ? AND read = 0",
                (task_id,),
            )
            await db.commit()
            return cur.rowcount

    # ─── Evidence Bundles ───────────────────────────────────────────────────

    @staticmethod
    def _evidence_row_to_bundle(row) -> EvidenceBundle:
        try:
            evidence = json.loads(row["evidence_json"])
            redaction_metadata = json.loads(row["redaction_metadata"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("persisted evidence bundle contains invalid JSON") from exc
        return EvidenceBundle.from_dict(
            {
                "schema_version": row["schema_version"],
                "bundle_id": row["bundle_id"],
                "attempt_id": row["attempt_id"],
                "task_id": row["task_id"],
                "attempt_index": row["attempt_index"],
                "revision": row["revision"],
                "lifecycle_state": row["lifecycle_state"],
                "recorded_at": row["recorded_at"],
                "evidence": evidence,
                "redaction_metadata": redaction_metadata,
                "previous_digest": row["previous_digest"],
                "digest": row["payload_digest"],
            }
        )

    @staticmethod
    async def _insert_evidence_bundle(db, bundle: EvidenceBundle) -> None:
        serialized = bundle.to_dict()
        await db.execute(
            """INSERT INTO evidence_bundles
               (attempt_id, revision, bundle_id, schema_version, task_id,
                attempt_index, lifecycle_state, recorded_at, evidence_json,
                redaction_metadata, previous_digest, payload_digest)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                bundle.attempt_id,
                bundle.revision,
                bundle.bundle_id,
                bundle.schema_version,
                bundle.task_id,
                bundle.attempt_index,
                bundle.lifecycle_state.value,
                bundle.recorded_at,
                json.dumps(serialized["evidence"], sort_keys=True),
                json.dumps(serialized["redaction_metadata"], sort_keys=True),
                bundle.previous_digest,
                bundle.digest,
            ),
        )

    async def create_evidence_attempt(
        self,
        task_id: str,
        *,
        attempt_index: int | None = None,
        attempt_id: str | None = None,
        bundle_id: str | None = None,
        evidence: dict | None = None,
        recorded_at: float | None = None,
    ) -> dict:
        """Create revision 1 for a task attempt and return its safe snapshot."""

        await self._ensure_db()
        redacted = redact_runtime(evidence or {}, field_path="$.evidence")
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            async with db.execute(
                "SELECT 1 FROM tasks WHERE id = ?", (task_id,)
            ) as cursor:
                if await cursor.fetchone() is None:
                    await db.rollback()
                    raise ValueError(f"unknown task for evidence attempt: {task_id}")
            if attempt_index is None:
                async with db.execute(
                    "SELECT COALESCE(MAX(attempt_index), 0) + 1 "
                    "FROM evidence_bundles WHERE task_id = ?",
                    (task_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                    attempt_index = int(row[0])
            bundle = create_evidence_bundle(
                task_id=task_id,
                attempt_index=attempt_index,
                attempt_id=attempt_id,
                bundle_id=bundle_id,
                recorded_at=recorded_at if recorded_at is not None else time.time(),
                evidence=redacted.value,
                redaction_metadata=redacted.metadata.to_dict(),
            )
            await self._insert_evidence_bundle(db, bundle)
            await db.commit()
        return bundle.to_dict()

    async def append_evidence_bundle(
        self,
        attempt_id: str,
        *,
        lifecycle_state: EvidenceLifecycle | str,
        evidence: dict | None = None,
        recorded_at: float | None = None,
    ) -> dict:
        """Atomically append one redacted snapshot to an attempt digest chain."""

        await self._ensure_db()
        redacted = redact_runtime(evidence or {}, field_path="$.evidence")
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            async with db.execute(
                "SELECT * FROM evidence_bundles WHERE attempt_id = ? "
                "ORDER BY revision DESC LIMIT 1",
                (attempt_id,),
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                await db.rollback()
                raise ValueError(f"unknown evidence attempt: {attempt_id}")
            previous = self._evidence_row_to_bundle(row)
            bundle = advance_evidence_bundle(
                previous,
                lifecycle_state=lifecycle_state,
                recorded_at=recorded_at if recorded_at is not None else time.time(),
                evidence_patch=redacted.value,
                redaction_metadata=merge_metadata(
                    previous.redaction_metadata, redacted.metadata
                ).to_dict(),
            )
            await self._insert_evidence_bundle(db, bundle)
            await db.commit()
        serialized = bundle.to_dict()
        if bundle.lifecycle_state is EvidenceLifecycle.REVERTED:
            try:
                await self.create_eval_candidate(
                    bundle.attempt_id,
                    trigger="managed_revert",
                    diff=(evidence or {}).get("diff", evidence or {}),
                    payload={"lifecycle_state": "reverted", "evidence": evidence or {}},
                    source_attempt_revision=bundle.revision,
                    source_evidence_digest=bundle.digest,
                    created_at=bundle.recorded_at,
                )
            except Exception:
                logger.exception("failed to create managed-revert eval candidate")
        return serialized

    async def get_evidence_bundle(self, attempt_id: str) -> dict | None:
        """Return the latest verified snapshot for one attempt."""

        await self._ensure_db()
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM evidence_bundles WHERE attempt_id = ? "
                "ORDER BY revision DESC LIMIT 1",
                (attempt_id,),
            ) as cursor:
                row = await cursor.fetchone()
        return self._evidence_row_to_bundle(row).to_dict() if row else None

    async def get_evidence_history(self, attempt_id: str) -> list[dict]:
        """Return and verify every immutable snapshot for one attempt."""

        await self._ensure_db()
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM evidence_bundles WHERE attempt_id = ? "
                "ORDER BY revision ASC",
                (attempt_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        bundles = [self._evidence_row_to_bundle(row) for row in rows]
        validate_evidence_chain(bundles)
        return [bundle.to_dict() for bundle in bundles]

    async def list_evidence_attempts(self, task_id: str) -> list[dict]:
        """Return the latest verified snapshot for every attempt of a task."""

        await self._ensure_db()
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT current.*
                   FROM evidence_bundles AS current
                   JOIN (
                       SELECT attempt_id, MAX(revision) AS revision
                       FROM evidence_bundles
                       WHERE task_id = ?
                       GROUP BY attempt_id
                   ) AS latest
                   ON current.attempt_id = latest.attempt_id
                   AND current.revision = latest.revision
                   ORDER BY current.attempt_index ASC""",
                (task_id,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._evidence_row_to_bundle(row).to_dict() for row in rows]

    # ─── Quarantined Eval Candidates ────────────────────────────────────────

    async def create_eval_candidate(
        self,
        source_attempt_id: str,
        *,
        trigger: str,
        diff,
        payload: dict | None = None,
        source_attempt_revision: int | None = None,
        source_evidence_digest: str | None = None,
        created_at: float | None = None,
    ) -> tuple[dict, bool]:
        """Create one redacted quarantined candidate pinned to exact evidence."""

        await self._ensure_db()
        attempt_id = validate_identifier(
            source_attempt_id, field_name="source_attempt_id"
        )
        trigger_name = validate_trigger(trigger)
        if source_attempt_revision is not None and (
            isinstance(source_attempt_revision, bool)
            or not isinstance(source_attempt_revision, int)
            or source_attempt_revision < 1
        ):
            raise ValueError("source_attempt_revision must be a positive integer")
        if source_evidence_digest is not None:
            validate_evidence_digest(source_evidence_digest)
        redacted = redact_runtime(
            {"diff": diff, "signal": payload or {}},
            field_path="$.eval_candidate",
        )
        safe_payload = redacted.value
        diff_digest = canonical_diff_digest(safe_payload["diff"])
        candidate_id = f"eval-{uuid.uuid4().hex}"
        timestamp = created_at if created_at is not None else time.time()

        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            revision_clause = (
                "AND revision = ?" if source_attempt_revision is not None else ""
            )
            params: tuple = (
                (attempt_id, source_attempt_revision)
                if source_attempt_revision is not None
                else (attempt_id,)
            )
            async with db.execute(
                "SELECT * FROM evidence_bundles WHERE attempt_id = ? "
                f"{revision_clause} ORDER BY revision DESC LIMIT 1",
                params,
            ) as cursor:
                evidence_row = await cursor.fetchone()
            if evidence_row is None:
                await db.rollback()
                raise ValueError(f"unknown evidence attempt or revision: {attempt_id}")
            evidence = self._evidence_row_to_bundle(evidence_row)
            if (
                source_evidence_digest is not None
                and evidence.digest != source_evidence_digest
            ):
                await db.rollback()
                raise ValueError("source evidence digest does not match revision")
            cur = await db.execute(
                """INSERT OR IGNORE INTO eval_candidates
                   (candidate_id, schema_version, source_task_id,
                    source_attempt_id, source_attempt_revision,
                    source_evidence_digest, trigger, diff_digest, payload_json,
                    redaction_metadata, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'quarantined', ?)""",
                (
                    candidate_id,
                    EVAL_CANDIDATE_SCHEMA_VERSION,
                    evidence.task_id,
                    evidence.attempt_id,
                    evidence.revision,
                    evidence.digest,
                    trigger_name,
                    diff_digest,
                    json.dumps(safe_payload, sort_keys=True),
                    json.dumps(redacted.metadata.to_dict(), sort_keys=True),
                    timestamp,
                ),
            )
            created = cur.rowcount == 1
            async with db.execute(
                """SELECT * FROM eval_candidates
                   WHERE source_attempt_id = ? AND trigger = ? AND diff_digest = ?""",
                (attempt_id, trigger_name, diff_digest),
            ) as cursor:
                row = await cursor.fetchone()
            await db.commit()
        if row is None:
            raise RuntimeError("eval candidate insert did not produce a row")
        return eval_candidate_row_to_dict(row), created

    async def get_eval_candidate(self, candidate_id: str) -> dict | None:
        await self._ensure_db()
        candidate = validate_identifier(candidate_id, field_name="candidate_id")
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM eval_candidates WHERE candidate_id = ?",
                (candidate,),
            ) as cursor:
                row = await cursor.fetchone()
        return eval_candidate_row_to_dict(row) if row else None

    async def list_eval_candidates(
        self, *, status: str = "quarantined", limit: int = 100
    ) -> list[dict]:
        await self._ensure_db()
        try:
            status = validate_status(status)
        except ValueError as exc:
            raise ValueError("invalid eval candidate status") from exc
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be an integer from 1 to 1000")
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT * FROM eval_candidates
                   WHERE status = ? ORDER BY created_at ASC LIMIT ?""",
                (status, limit),
            ) as cursor:
                rows = await cursor.fetchall()
        return [eval_candidate_row_to_dict(row) for row in rows]

    async def decide_eval_candidate(
        self,
        candidate_id: str,
        *,
        status: str,
        reviewer: str,
        reason: str,
        promotion_kind: str | None = None,
        promotion_ref: str | None = None,
        decided_at: float | None = None,
    ) -> dict:
        """Apply one explicit human decision with a quarantined-state CAS."""

        await self._ensure_db()
        candidate = validate_identifier(candidate_id, field_name="candidate_id")
        reviewer_check = redact_runtime(
            str(reviewer or "").strip(), field_path="$.decided_by"
        )
        if reviewer_check.metadata.redacted:
            raise ValueError("reviewer must be a non-sensitive stable identifier")
        reviewer_id = validate_identifier(
            reviewer_check.value, field_name="reviewer"
        )
        if status not in {"promoted", "rejected"}:
            raise ValueError("decision status must be promoted or rejected")
        decision = redact_runtime(str(reason or "").strip(), field_path="$.decision_reason")
        if not decision.value:
            raise ValueError("decision reason is required")
        if len(decision.value) > 4000:
            raise ValueError("decision reason must be at most 4000 characters")
        if status == "promoted":
            kind = validate_identifier(promotion_kind, field_name="promotion_kind")
            ref = validate_identifier(promotion_ref, field_name="promotion_ref")
        else:
            kind = ref = None
        timestamp = decided_at if decided_at is not None else time.time()
        async with aiosqlite.connect(str(self._db_path)) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            async with db.execute(
                "SELECT * FROM eval_candidates WHERE candidate_id = ?",
                (candidate,),
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                await db.rollback()
                raise ValueError(f"unknown eval candidate: {candidate}")
            if row["status"] != "quarantined":
                await db.rollback()
                raise ValueError(
                    f"eval candidate already decided: {row['status']}"
                )
            try:
                prior_metadata = json.loads(row["redaction_metadata"])
            except (TypeError, json.JSONDecodeError):
                prior_metadata = {}
            metadata = merge_metadata(
                prior_metadata, decision.metadata
            ).to_dict()
            cur = await db.execute(
                """UPDATE eval_candidates
                   SET status = ?, decision_reason = ?, decided_by = ?,
                       decided_at = ?, promotion_kind = ?, promotion_ref = ?,
                       redaction_metadata = ?
                   WHERE candidate_id = ? AND status = 'quarantined'""",
                (
                    status,
                    decision.value,
                    reviewer_id,
                    timestamp,
                    kind,
                    ref,
                    json.dumps(metadata, sort_keys=True),
                    candidate,
                ),
            )
            if cur.rowcount != 1:
                await db.rollback()
                raise ValueError("eval candidate decision lost a concurrent race")
            async with db.execute(
                "SELECT * FROM eval_candidates WHERE candidate_id = ?",
                (candidate,),
            ) as cursor:
                decided = await cursor.fetchone()
            await db.commit()
        return eval_candidate_row_to_dict(decided)

    # ─── Interventions ───────────────────────────────────────────────────────

    async def record_intervention(
        self, failure_pattern: str, correction: str,
        task_description_hint: str | None = None,
        source_task_id: str | None = None,
        spawned_task_id: str | None = None,
    ) -> int:
        await self._ensure_db()
        redaction = redact_runtime(
            {
                "failure_pattern": failure_pattern,
                "correction": correction,
                "task_description_hint": task_description_hint,
            },
            field_path="$.interventions",
        )
        values = redaction.value
        metadata = redaction.metadata.to_dict() if redaction.metadata.redacted else {}
        async with aiosqlite.connect(str(self._db_path)) as db:
            cur = await db.execute(
                """INSERT INTO interventions
                   (failure_pattern, correction, task_description_hint,
                    source_task_id, spawned_task_id, created_at, redaction_metadata)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    values["failure_pattern"],
                    values["correction"],
                    values["task_description_hint"],
                    source_task_id,
                    spawned_task_id,
                    time.time(),
                    json.dumps(metadata),
                ),
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
