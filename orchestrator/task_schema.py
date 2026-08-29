"""The tasks.db schema: table creation and additive column migrations.

Extracted from task_queue.py on 2026-08-29. That file sat at 1498 of its
1500-line budget, and this one method was 344 of them — a third of the module
was DDL sharing a file with the CRUD that reads it. The seam is real: nothing
here queries; everything here shapes the database.

Migrations stay additive `try/except ALTER TABLE` blocks, unchanged. A new
column is added here and to `_ALLOWED_TASK_COLS` in config.py.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import aiosqlite

from compatibility_telemetry import TASKS_SQLITE_PROVIDER, record_compatibility_use
from runtime_redaction import redact_runtime


_RUNTIME_TEXT_FIELDS = {
    "description",
    "failed_reason",
    "score_note",
    "handoff_payload",
    "completion_summary",
    "oracle_reason",
    "route_reason",
}


def _redact_text_fields(values: dict) -> tuple[dict, dict]:
    selected = {key: value for key, value in values.items() if key in _RUNTIME_TEXT_FIELDS}
    if not selected:
        return values, {}
    result = redact_runtime(selected, field_path="$.tasks")
    updated = dict(values)
    updated.update(result.value)
    metadata = result.metadata.to_dict() if result.metadata.redacted else {}
    return updated, metadata


async def ensure_schema(db_path: Path, claude_dir: Path) -> None:
    """Create every table and apply every additive migration, once.

    Caller owns the "run this only once" lock; this function is idempotent on
    its own (every statement is CREATE IF NOT EXISTS or a guarded ALTER).
    """
    claude_dir.mkdir(parents=True, exist_ok=True)
    # tasks.db can hold task descriptions / GH issue bodies / commit
    # messages with embedded credentials. Owner-only is a low-cost guard.
    try:
        import os as _os
        _os.chmod(claude_dir, 0o700)
    except (OSError, NotImplementedError):
        pass
    async with aiosqlite.connect(str(db_path)) as db:
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
                redaction_metadata TEXT DEFAULT '{}',
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
                plan_phase TEXT DEFAULT 'plan',
                plan_item_reject_streak INTEGER DEFAULT 0
            )
        """)
        # ─── Migrations (ALTER TABLE — safe to re-run, duplicate column = ignored) ───
        async def _migrate(sql: str) -> None:
            try:
                await db.execute(sql)
            except Exception:
                pass  # column already exists

        await _migrate("ALTER TABLE iteration_loops ADD COLUMN mode TEXT DEFAULT 'review'")
        await _migrate("ALTER TABLE iteration_loops ADD COLUMN plan_phase TEXT DEFAULT 'plan'")
        await _migrate("ALTER TABLE iteration_loops ADD COLUMN plan_item_reject_streak INTEGER DEFAULT 0")
        await _migrate("ALTER TABLE tasks ADD COLUMN own_files TEXT DEFAULT '[]'")
        await _migrate("ALTER TABLE tasks ADD COLUMN forbidden_files TEXT DEFAULT '[]'")
        await _migrate("ALTER TABLE tasks ADD COLUMN gh_issue_number INTEGER")
        await _migrate("ALTER TABLE tasks ADD COLUMN is_critical_path INTEGER DEFAULT 0")
        await _migrate("ALTER TABLE tasks ADD COLUMN input_tokens INTEGER")
        await _migrate("ALTER TABLE tasks ADD COLUMN output_tokens INTEGER")
        await _migrate("ALTER TABLE tasks ADD COLUMN estimated_cost REAL")
        await _migrate("ALTER TABLE tasks ADD COLUMN task_type TEXT DEFAULT 'AUTO'")
        await _migrate("ALTER TABLE tasks ADD COLUMN source_ref TEXT")
        await _migrate("ALTER TABLE tasks ADD COLUMN parent_task_id TEXT")
        await _migrate("ALTER TABLE tasks ADD COLUMN priority_score REAL DEFAULT 0.0")
        await _migrate("ALTER TABLE tasks ADD COLUMN handoff_type TEXT")
        await _migrate("ALTER TABLE tasks ADD COLUMN handoff_payload TEXT DEFAULT '{}'")
        await _migrate("ALTER TABLE tasks ADD COLUMN completion_summary TEXT")
        await _migrate("ALTER TABLE tasks ADD COLUMN token_budget INTEGER DEFAULT 0")
        await _migrate("ALTER TABLE tasks ADD COLUMN context_version INTEGER DEFAULT 0")
        await _migrate("ALTER TABLE tasks ADD COLUMN attempt_count INTEGER DEFAULT 0")
        await _migrate("ALTER TABLE tasks ADD COLUMN phase TEXT DEFAULT 'implement'")
        await _migrate("ALTER TABLE tasks ADD COLUMN oracle_result TEXT")
        await _migrate("ALTER TABLE tasks ADD COLUMN oracle_reason TEXT")
        await _migrate("ALTER TABLE tasks ADD COLUMN pgid INTEGER")
        await _migrate("ALTER TABLE tasks ADD COLUMN provider TEXT")
        await _migrate("ALTER TABLE tasks ADD COLUMN agent_runtime TEXT")
        cursor = await db.execute(
            "UPDATE tasks SET agent_runtime = provider WHERE "
            "(agent_runtime IS NULL OR trim(agent_runtime) = '') "
            "AND provider IS NOT NULL AND trim(provider) != ''"
        )
        if cursor.rowcount:
            record_compatibility_use(TASKS_SQLITE_PROVIDER, cursor.rowcount)
        await _migrate("ALTER TABLE tasks ADD COLUMN connection TEXT")
        await _migrate("ALTER TABLE tasks ADD COLUMN execution_profile TEXT")
        await _migrate("ALTER TABLE tasks ADD COLUMN execution_requirements TEXT DEFAULT '{}'")
        await _migrate("ALTER TABLE tasks ADD COLUMN execution_envelope TEXT")
        await _migrate("ALTER TABLE tasks ADD COLUMN effort TEXT")
        await _migrate("ALTER TABLE tasks ADD COLUMN route_reason TEXT")
        await _migrate("ALTER TABLE tasks ADD COLUMN redaction_metadata TEXT DEFAULT '{}'")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS worker_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                to_task_id TEXT NOT NULL,
                from_task_id TEXT,
                content TEXT NOT NULL,
                created_at REAL,
                read INTEGER DEFAULT 0,
                redaction_metadata TEXT DEFAULT '{}'
            )
        """)
        await _migrate(
            "ALTER TABLE worker_messages ADD COLUMN redaction_metadata TEXT DEFAULT '{}'"
        )
        await db.execute("""
            CREATE TABLE IF NOT EXISTS evidence_bundles (
                attempt_id TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK (revision > 0),
                bundle_id TEXT NOT NULL,
                schema_version TEXT NOT NULL
                    CHECK (schema_version = 'clade.evidence/v1'),
                task_id TEXT NOT NULL,
                attempt_index INTEGER NOT NULL CHECK (attempt_index > 0),
                lifecycle_state TEXT NOT NULL CHECK (
                    lifecycle_state IN (
                        'created', 'running', 'verifying',
                        'delivery_pending', 'delivered', 'failed',
                        'cancelled', 'reverted'
                    )
                ),
                recorded_at REAL NOT NULL CHECK (recorded_at >= 0),
                evidence_json TEXT NOT NULL,
                redaction_metadata TEXT NOT NULL,
                previous_digest TEXT,
                payload_digest TEXT NOT NULL,
                PRIMARY KEY (attempt_id, revision),
                UNIQUE (bundle_id, revision),
                UNIQUE (task_id, attempt_index, revision),
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_evidence_bundles_task_attempt
            ON evidence_bundles(task_id, attempt_index, revision)
        """)
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS evidence_bundles_no_update
            BEFORE UPDATE ON evidence_bundles
            BEGIN
                SELECT RAISE(ABORT, 'evidence bundles are append-only');
            END
        """)
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS evidence_bundles_insert_guard
            BEFORE INSERT ON evidence_bundles
            BEGIN
                SELECT CASE
                    WHEN NEW.revision != COALESCE((
                        SELECT MAX(revision) + 1
                        FROM evidence_bundles
                        WHERE attempt_id = NEW.attempt_id
                    ), 1)
                    THEN RAISE(ABORT, 'evidence revision must append')
                END;
                SELECT CASE
                    WHEN EXISTS (
                        SELECT 1 FROM evidence_bundles
                        WHERE task_id = NEW.task_id
                          AND attempt_index = NEW.attempt_index
                          AND attempt_id != NEW.attempt_id
                    )
                    THEN RAISE(ABORT, 'evidence attempt identity changed')
                END;
                SELECT CASE
                    WHEN NEW.revision = 1 AND (
                        NEW.lifecycle_state != 'created'
                        OR NEW.previous_digest IS NOT NULL
                    )
                    THEN RAISE(ABORT, 'invalid initial evidence revision')
                END;
                SELECT CASE
                    WHEN NEW.revision > 1 AND NEW.previous_digest IS NOT (
                        SELECT payload_digest
                        FROM evidence_bundles
                        WHERE attempt_id = NEW.attempt_id
                        ORDER BY revision DESC LIMIT 1
                    )
                    THEN RAISE(ABORT, 'evidence predecessor mismatch')
                END;
            END
        """)
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS evidence_bundles_no_delete
            BEFORE DELETE ON evidence_bundles
            BEGIN
                SELECT RAISE(ABORT, 'evidence bundles are append-only');
            END
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS eval_candidates (
                candidate_id TEXT PRIMARY KEY,
                schema_version TEXT NOT NULL CHECK (
                    schema_version = 'clade.eval_candidate/v1'
                ),
                source_task_id TEXT NOT NULL,
                source_attempt_id TEXT NOT NULL,
                source_attempt_revision INTEGER NOT NULL CHECK (
                    source_attempt_revision > 0
                ),
                source_evidence_digest TEXT NOT NULL,
                trigger TEXT NOT NULL CHECK (
                    trigger IN (
                        'incident_failure', 'oracle_rejected',
                        'oracle_unreviewed', 'oracle_disagreement',
                        'managed_revert', 'explicit_correction'
                    )
                ),
                diff_digest TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                redaction_metadata TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'quarantined' CHECK (
                    status IN (
                        'quarantined', 'promoted', 'rejected', 'expired'
                    )
                ),
                decision_reason TEXT,
                decided_by TEXT,
                decided_at REAL,
                promotion_kind TEXT,
                promotion_ref TEXT,
                created_at REAL NOT NULL,
                UNIQUE (source_attempt_id, trigger, diff_digest),
                FOREIGN KEY (source_task_id) REFERENCES tasks(id)
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_eval_candidates_status_created
            ON eval_candidates(status, created_at)
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
                created_at REAL,
                redaction_metadata TEXT DEFAULT '{}'
            )
        """)
        await _migrate(
            "ALTER TABLE interventions ADD COLUMN redaction_metadata TEXT DEFAULT '{}'"
        )
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
    # Restrict tasks.db to owner-only — see _ensure_db comment above.
    try:
        import os as _os
        if db_path.exists():
            _os.chmod(db_path, 0o600)
    except (OSError, NotImplementedError):
        pass
    # Migrate from JSON if present
    json_file = claude_dir / "task-queue.json"
    if json_file.exists():
        try:
            existing = json.loads(json_file.read_text())
            if existing:
                async with aiosqlite.connect(str(db_path)) as db:
                    for t in existing:
                        t, legacy_metadata = _redact_text_fields(dict(t))
                        await db.execute(
                            """INSERT OR IGNORE INTO tasks
                               (id, description, model, timeout, retries, status, worker_id,
                                started_at, elapsed_s, last_commit, log_file, failed_reason,
                                created_at, depends_on, redaction_metadata)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (
                                t.get("id"), t.get("description", ""),
                                t.get("model", "sonnet"), t.get("timeout", 600),
                                t.get("retries", 2), t.get("status", "pending"),
                                t.get("worker_id"), t.get("started_at"),
                                t.get("elapsed_s", 0), t.get("last_commit"),
                                t.get("log_file"), t.get("failed_reason"),
                                t.get("created_at", time.time()),
                                json.dumps(t.get("depends_on", [])),
                                json.dumps(legacy_metadata),
                            ),
                        )
                    await db.commit()
            json_file.rename(json_file.with_suffix(".json.migrated"))
        except Exception:
            pass
