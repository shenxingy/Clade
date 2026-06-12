"""Frozen-schema snapshot — task_queue's SQLite schema as a committed fixture.

The tasks DB is the autonomous loop's source of truth. A fresh install builds
it via CREATE TABLE; an upgraded install reaches the same point via CREATE
TABLE IF NOT EXISTS + try/except ALTER TABLE migrations. SQLite rewrites the
stored CREATE statement on ALTER TABLE ADD COLUMN, so one sqlite_master dump
covers both paths — if they ever fork, or a migration silently stops applying,
this snapshot catches it offline instead of mid-overnight-run.

Re-bless after an INTENTIONAL schema change:

    cd orchestrator && BLESS=1 .venv/bin/python -m pytest tests/test_schema_frozen.py -q
"""

from __future__ import annotations

import difflib
import os
from pathlib import Path

import aiosqlite

from config import _ALLOWED_TASK_COLS
from task_queue import TaskQueue

FIXTURE = Path(__file__).parent / "fixtures" / "schema.snapshot.sql"
BLESS_CMD = (
    "cd orchestrator && BLESS=1 .venv/bin/python -m pytest "
    "tests/test_schema_frozen.py -q"
)


async def _fresh_schema_dump(claude_dir: Path) -> str:
    """Build a brand-new DB via the real TaskQueue._ensure_db() and dump it."""
    tq = TaskQueue(claude_dir)
    await tq._ensure_db()
    async with aiosqlite.connect(str(claude_dir / "tasks.db")) as db:
        cur = await db.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' "
            "ORDER BY type, name"
        )
        rows = await cur.fetchall()
    assert rows, "fresh DB has no schema objects — _ensure_db() built nothing?"
    blocks = [f"-- {typ} {name}\n{sql.strip()};" for typ, name, sql in rows]
    return "\n\n".join(blocks) + "\n"


async def test_schema_matches_frozen_snapshot(tmp_claude_dir: Path) -> None:
    actual = await _fresh_schema_dump(tmp_claude_dir)

    if os.environ.get("BLESS") == "1":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(actual)

    assert FIXTURE.is_file(), (
        f"Missing committed fixture {FIXTURE} — generate and commit it with:\n"
        f"  {BLESS_CMD}"
    )
    expected = FIXTURE.read_text()
    if actual != expected:
        diff = "\n".join(
            difflib.unified_diff(
                expected.splitlines(),
                actual.splitlines(),
                fromfile="tests/fixtures/schema.snapshot.sql (committed)",
                tofile="TaskQueue._ensure_db() (fresh build)",
                lineterm="",
            )
        )
        raise AssertionError(
            "task_queue schema drifted from the committed snapshot. If this "
            "change is intentional (new table/column migration), re-bless and "
            "commit the fixture:\n"
            f"  {BLESS_CMD}\n\n{diff}"
        )


async def test_allowed_task_cols_all_exist_in_tasks_table(
    tmp_claude_dir: Path,
) -> None:
    """config._ALLOWED_TASK_COLS and the tasks table must not fork.

    CLAUDE.md documents the two-file migration dance in prose (try/except
    ALTER TABLE in _ensure_db() + column added to _ALLOWED_TASK_COLS in
    config.py). This enforces the half that fails silently at runtime: an
    allowed column with no backing table column breaks every UPDATE that
    touches it.
    """
    tq = TaskQueue(tmp_claude_dir)
    await tq._ensure_db()
    async with aiosqlite.connect(str(tmp_claude_dir / "tasks.db")) as db:
        cur = await db.execute("PRAGMA table_info(tasks)")
        cols = {row[1] for row in await cur.fetchall()}
    assert cols, "PRAGMA table_info(tasks) returned nothing — tasks table missing"

    missing = sorted(_ALLOWED_TASK_COLS - cols)
    assert not missing, (
        "config._ALLOWED_TASK_COLS lists columns absent from the tasks table — "
        "add the try/except ALTER TABLE migration in TaskQueue._ensure_db() "
        f"(see CLAUDE.md 'DB Migrations'): {missing}"
    )
