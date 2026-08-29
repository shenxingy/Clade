"""GitHub issue sync must not fork a task into a growing pair of duplicates.

`_format_issue_body` stamps `task_id` into every issue body. Until 2026-08-29
nothing read it back — `grep -n task_id orchestrator/github_sync.py` returned
exactly one hit, the write. The issue NUMBER was the only join key, and
`_gh_create_issue` returns after a 30s local timeout that says nothing about
whether GitHub created the issue. The cascade:

    create times out  ->  task keeps gh_issue_number = NULL
    next pull         ->  sees an issue no task owns -> invents a SECOND task
    next push         ->  that task has no issue -> opens a SECOND issue
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from github_sync import (  # noqa: E402
    _format_issue_body,
    _gh_find_issue_by_task_id,
    _gh_pull_issues,
    _parse_issue_body,
)


class FakeQueue:
    """The four methods _gh_pull_issues actually uses."""

    def __init__(self, tasks):
        self.tasks = {t["id"]: dict(t) for t in tasks}
        self.added = []

    async def list(self):
        return [dict(t) for t in self.tasks.values()]

    async def update(self, task_id, **fields):
        self.tasks[task_id].update(fields)

    async def delete(self, task_id):
        self.tasks.pop(task_id, None)

    async def add(self, **fields):
        new = {"id": f"new-{len(self.added)}", "status": "pending", **fields}
        self.added.append(new)
        self.tasks[new["id"]] = new
        return new


def _issue(number, task, state="OPEN"):
    return {
        "number": number,
        "title": task["description"][:40],
        "body": _format_issue_body(task),
        "state": state,
        "labels": [],
    }


def _patched_gh(payload):
    """Patch the subprocess so _gh_pull_issues sees `payload` as gh output."""
    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(json.dumps(payload).encode(), b""))
    return patch("github_sync.asyncio.create_subprocess_shell", AsyncMock(return_value=proc))


class TestTaskIdRoundTrip:
    def test_the_id_written_into_the_body_can_be_read_back(self):
        task = {"id": "t-abc", "description": "fix the thing", "model": "opus"}
        meta, desc = _parse_issue_body(_format_issue_body(task))
        assert meta["task_id"] == "t-abc"
        assert desc == "fix the thing"


class TestPullReconcilesOnTaskId:
    @pytest.mark.asyncio
    async def test_an_orphaned_issue_is_adopted_not_duplicated(self, tmp_path):
        """The exact state a timed-out create leaves behind."""
        task = {"id": "t-abc", "description": "fix the thing", "model": "opus",
                "status": "pending", "gh_issue_number": None}
        queue = FakeQueue([task])

        with _patched_gh([_issue(42, task)]):
            stats = await _gh_pull_issues(tmp_path, queue)

        assert stats["adopted"] == 1
        assert stats["created"] == 0, "a second task must not be invented"
        assert queue.added == [], "no task was added"
        assert queue.tasks["t-abc"]["gh_issue_number"] == 42

    @pytest.mark.asyncio
    async def test_an_issue_from_elsewhere_still_creates_a_task(self, tmp_path):
        """The control case: adoption must not swallow genuinely new issues."""
        queue = FakeQueue([])
        foreign = {"number": 7, "title": "please fix", "body": "no meta here",
                   "state": "OPEN", "labels": []}

        with _patched_gh([foreign]):
            stats = await _gh_pull_issues(tmp_path, queue)

        assert stats["created"] == 1
        assert len(queue.added) == 1

    @pytest.mark.asyncio
    async def test_a_task_already_bound_to_another_issue_is_not_rebound(self, tmp_path):
        """Adoption applies only when the receipt is missing."""
        task = {"id": "t-abc", "description": "fix the thing", "model": "opus",
                "status": "pending", "gh_issue_number": 11}
        queue = FakeQueue([task])

        with _patched_gh([_issue(99, task)]):
            stats = await _gh_pull_issues(tmp_path, queue)

        assert stats["adopted"] == 0
        assert queue.tasks["t-abc"]["gh_issue_number"] == 11


class TestCreateTimeoutRecovery:
    @pytest.mark.asyncio
    async def test_find_by_task_id_matches_on_the_body_not_the_search_rank(self, tmp_path):
        """gh's search is fuzzy; the meta block is the authority."""
        mine = {"id": "t-abc", "description": "fix the thing", "model": "opus"}
        other = {"id": "t-zzz", "description": "mentions t-abc in passing",
                 "model": "opus"}
        payload = [
            {"number": 5, "body": _format_issue_body(other)},
            {"number": 42, "body": _format_issue_body(mine)},
        ]
        db = tmp_path / "tasks.db"

        import aiosqlite

        async with aiosqlite.connect(str(db)) as conn:
            await conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, gh_issue_number INT)")
            await conn.execute("INSERT INTO tasks VALUES ('t-abc', NULL)")
            await conn.commit()

        with _patched_gh(payload):
            found = await _gh_find_issue_by_task_id("t-abc", tmp_path, db)

        assert found == 42

        async with aiosqlite.connect(str(db)) as conn:
            row = await (await conn.execute(
                "SELECT gh_issue_number FROM tasks WHERE id='t-abc'")).fetchone()
        assert row[0] == 42, "the recovered number must be persisted"

    @pytest.mark.asyncio
    async def test_no_match_returns_none_rather_than_guessing(self, tmp_path):
        with _patched_gh([{"number": 5, "body": "unrelated"}]):
            assert await _gh_find_issue_by_task_id("t-abc", tmp_path, tmp_path / "x.db") is None

    @pytest.mark.asyncio
    async def test_a_failing_lookup_never_raises(self, tmp_path):
        with patch("github_sync.asyncio.create_subprocess_shell",
                   AsyncMock(side_effect=OSError("gh missing"))):
            assert await _gh_find_issue_by_task_id("t-abc", tmp_path, tmp_path / "x.db") is None
