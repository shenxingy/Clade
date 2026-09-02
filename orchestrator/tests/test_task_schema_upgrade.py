"""The UPGRADE path through task_schema.ensure_schema().

Every other schema test builds a fresh database, where the CREATE TABLE
statements already carry the columns and each matching `ALTER TABLE ADD COLUMN`
can only fail and be swallowed by `_migrate`'s bare `except Exception: pass`.
Five migrations are in that position permanently — their column is in the
CREATE block, so they have never once executed successfully in a test run:

    task_schema.py  ALTER TABLE iteration_loops ADD COLUMN mode
    task_schema.py  ALTER TABLE iteration_loops ADD COLUMN plan_phase
    task_schema.py  ALTER TABLE iteration_loops ADD COLUMN plan_item_reject_streak
    task_schema.py  ALTER TABLE worker_messages  ADD COLUMN redaction_metadata
    task_schema.py  ALTER TABLE interventions    ADD COLUMN redaction_metadata

A typo in any of them is invisible until a real upgraded install queries the
column. These tests run ensure_schema against a pre-migration database so the
migrations fire for real.

LEGACY_SCHEMA below is today's DDL with every ALTER-added column removed —
which is, by construction, what the old schema was, since each such column was
once absent. `test_legacy_schema_predates_every_migration` keeps it honest:
add a migration without removing its column here and that test fails.
"""

from __future__ import annotations

import re
from pathlib import Path

import aiosqlite

from config import _ALLOWED_TASK_COLS
from task_queue import TaskQueue
from task_schema import ensure_schema

TASK_SCHEMA_SRC = Path(__file__).parent.parent / "task_schema.py"

# Deliberately no commits / schedule / evidence_bundles / eval_candidates /
# ideas tables: ensure_schema creates those with CREATE TABLE IF NOT EXISTS, so
# leaving them out also proves the mixed create-and-migrate path works on a
# partially-old database.
LEGACY_SCHEMA = """
CREATE TABLE tasks (
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
);

CREATE TABLE iteration_loops (
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
    updated_at TEXT
);

CREATE TABLE worker_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    to_task_id TEXT NOT NULL,
    from_task_id TEXT,
    content TEXT NOT NULL,
    created_at REAL,
    read INTEGER DEFAULT 0
);

CREATE TABLE interventions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    failure_pattern TEXT NOT NULL,
    correction TEXT NOT NULL,
    task_description_hint TEXT,
    success INTEGER DEFAULT 0,
    source_task_id TEXT,
    spawned_task_id TEXT,
    created_at REAL
);
"""


async def _legacy_db(claude_dir: Path) -> Path:
    """Materialize a pre-migration tasks.db."""
    db_path = claude_dir / "tasks.db"
    async with aiosqlite.connect(str(db_path)) as db:
        await db.executescript(LEGACY_SCHEMA)
        await db.commit()
    return db_path


async def _columns(db_path: Path, table: str) -> set[str]:
    async with aiosqlite.connect(str(db_path)) as db:
        cur = await db.execute(f"PRAGMA table_info({table})")
        return {row[1] for row in await cur.fetchall()}


# ─── Upgrade path ─────────────────────────────────────────────────────────────


async def test_upgrade_from_legacy_schema_adds_every_allowed_column(
    tmp_claude_dir: Path,
) -> None:
    """config._ALLOWED_TASK_COLS must be satisfiable on an UPGRADED database,
    not only a freshly created one (test_schema_frozen covers the fresh path)."""
    db_path = await _legacy_db(tmp_claude_dir)
    await ensure_schema(db_path, tmp_claude_dir)

    cols = await _columns(db_path, "tasks")
    missing = sorted(_ALLOWED_TASK_COLS - cols)
    assert not missing, (
        "Migrations did not add these columns on upgrade — a broken ALTER is "
        f"swallowed by task_schema._migrate: {missing}"
    )


async def test_upgrade_adds_redaction_metadata_to_message_tables(
    tmp_claude_dir: Path,
) -> None:
    """These two ALTERs have never succeeded in a test run: on a fresh DB the
    column is already in the CREATE block and the statement fails silently."""
    db_path = await _legacy_db(tmp_claude_dir)
    await ensure_schema(db_path, tmp_claude_dir)

    assert "redaction_metadata" in await _columns(db_path, "worker_messages")
    assert "redaction_metadata" in await _columns(db_path, "interventions")


async def test_upgrade_adds_iteration_loop_mode_columns(
    tmp_claude_dir: Path,
) -> None:
    db_path = await _legacy_db(tmp_claude_dir)
    await ensure_schema(db_path, tmp_claude_dir)

    cols = await _columns(db_path, "iteration_loops")
    assert {"mode", "plan_phase", "plan_item_reject_streak"} <= cols


async def test_upgrade_preserves_rows_and_backfills_defaults(
    tmp_claude_dir: Path,
) -> None:
    """The property a user actually cares about on upgrade: existing rows
    survive, and SQLite's ADD COLUMN default lands on them."""
    db_path = await _legacy_db(tmp_claude_dir)
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute(
            "INSERT INTO tasks (id, description, status, created_at) "
            "VALUES ('t-old', 'legacy row', 'done', 1.0)"
        )
        await db.commit()

    await ensure_schema(db_path, tmp_claude_dir)

    async with aiosqlite.connect(str(db_path)) as db:
        cur = await db.execute(
            "SELECT description, own_files, task_type, handoff_payload, "
            "redaction_metadata FROM tasks WHERE id = 't-old'"
        )
        row = await cur.fetchone()
    assert row is not None, "the legacy row did not survive the upgrade"
    assert row == ("legacy row", "[]", "AUTO", "{}", "{}")


async def test_upgrade_is_idempotent(tmp_claude_dir: Path) -> None:
    """ensure_schema re-runs on every process start."""
    db_path = await _legacy_db(tmp_claude_dir)
    await ensure_schema(db_path, tmp_claude_dir)
    first = await _columns(db_path, "tasks")

    await ensure_schema(db_path, tmp_claude_dir)
    assert await _columns(db_path, "tasks") == first


async def test_upgraded_schema_has_the_same_columns_as_a_fresh_one(
    tmp_claude_dir: Path, tmp_path: Path,
) -> None:
    """The fresh and upgraded paths must not fork.

    Column sets, not the sqlite_master text: SQLite appends an ALTERed column
    to the stored CREATE statement, so the two paths legitimately differ in
    column ORDER and in SQL text — which is the assumption
    test_schema_frozen.py's docstring gets wrong, and the reason one snapshot
    of a fresh DB does not in fact cover both paths.
    """
    upgraded_db = await _legacy_db(tmp_claude_dir)
    await ensure_schema(upgraded_db, tmp_claude_dir)

    fresh_dir = tmp_path / "fresh"
    fresh_dir.mkdir()
    await TaskQueue(fresh_dir)._ensure_db()
    fresh_db = fresh_dir / "tasks.db"

    for table in ("tasks", "iteration_loops", "worker_messages", "interventions"):
        assert await _columns(upgraded_db, table) == await _columns(fresh_db, table), (
            f"fresh and upgraded schemas disagree on {table}'s columns"
        )


# ─── Anti-staleness guard for LEGACY_SCHEMA ──────────────────────────────────

_ALTER_RE = re.compile(r"ALTER TABLE (\w+) ADD COLUMN (\w+)")
_CREATE_RE = re.compile(
    r"CREATE TABLE (\w+) \((.*?)\n\);", re.DOTALL
)


def test_legacy_schema_predates_every_migration() -> None:
    """A migration whose column is already in LEGACY_SCHEMA cannot fire, so the
    tests above would silently stop exercising it. Adding a migration means
    removing its column from LEGACY_SCHEMA."""
    statements = _ALTER_RE.findall(TASK_SCHEMA_SRC.read_text())
    assert len(statements) >= 30, (
        f"only {len(statements)} ALTER TABLE statements matched in "
        f"{TASK_SCHEMA_SRC.name} — the DDL style changed and this guard is now "
        "passing vacuously; fix the regex."
    )

    legacy_blocks = {t: body for t, body in _CREATE_RE.findall(LEGACY_SCHEMA)}
    assert legacy_blocks, "LEGACY_SCHEMA parsed to nothing — fix _CREATE_RE"

    stale = [
        f"{table}.{column}"
        for table, column in statements
        if table in legacy_blocks
        and re.search(rf"^\s*{column}\s", legacy_blocks[table], re.MULTILINE)
    ]
    assert not stale, (
        "These columns are in LEGACY_SCHEMA, so their migration is a no-op and "
        "the upgrade path is untested for them. Remove them from LEGACY_SCHEMA "
        f"in this file: {sorted(stale)}"
    )
