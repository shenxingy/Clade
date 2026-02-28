"""Tests for TaskQueue CRUD and import operations."""

from __future__ import annotations

import pytest

from task_queue import TaskQueue


# ─── Basic CRUD ───────────────────────────────────────────────────────────────


async def test_add_returns_task(task_queue: TaskQueue):
    task = await task_queue.add("Test task description")
    assert task["id"]
    assert task["description"] == "Test task description"
    assert task["status"] == "pending"


async def test_list_all_tasks(task_queue: TaskQueue):
    await task_queue.add("Task one")
    await task_queue.add("Task two")
    await task_queue.add("Task three")
    tasks = await task_queue.list()
    assert len(tasks) == 3


async def test_update_status_transitions(task_queue: TaskQueue):
    task = await task_queue.add("Status transition test")
    task_id = task["id"]

    updated = await task_queue.update(task_id, status="running")
    assert updated["status"] == "running"

    updated = await task_queue.update(task_id, status="done")
    assert updated["status"] == "done"


async def test_delete_removes_task(task_queue: TaskQueue):
    task = await task_queue.add("Task to delete")
    task_id = task["id"]

    deleted = await task_queue.delete(task_id)
    assert deleted is True

    tasks = await task_queue.list()
    assert all(t["id"] != task_id for t in tasks)


# ─── Import from proposed ─────────────────────────────────────────────────────


async def test_import_from_proposed_basic(task_queue: TaskQueue):
    content = "===TASK===\n---\nSimple task description\n===TASK==="
    added, skip_counts = await task_queue.import_from_proposed(content)
    assert len(added) == 1
    assert added[0]["description"] == "Simple task description"


async def test_import_type_field(task_queue: TaskQueue):
    content = "===TASK===\nTYPE: HORIZONTAL\n---\nHorizontal task\n===TASK==="
    added, _ = await task_queue.import_from_proposed(content)
    assert len(added) == 1
    assert added[0]["task_type"] == "HORIZONTAL"


async def test_import_dedup_by_description(task_queue: TaskQueue):
    """Importing the same description twice skips the second."""
    content = "===TASK===\n---\nDuplicate description\n===TASK==="
    added1, _ = await task_queue.import_from_proposed(content)
    added2, skip_counts = await task_queue.import_from_proposed(content)
    assert len(added1) == 1
    assert len(added2) == 0
    assert skip_counts.get("pending", 0) == 1


# ─── Source ref ───────────────────────────────────────────────────────────────


async def test_source_ref_stored(task_queue: TaskQueue):
    task = await task_queue.add("Task with source ref", source_ref="github/issue/42")
    fetched = await task_queue.get(task["id"])
    assert fetched["source_ref"] == "github/issue/42"


# ─── Priority score ───────────────────────────────────────────────────────────


async def test_priority_score_default(task_queue: TaskQueue):
    """New tasks should have priority_score of 0.0 (or None if column not yet migrated)."""
    task = await task_queue.add("Priority test task")
    fetched = await task_queue.get(task["id"])
    priority = fetched.get("priority_score")
    assert priority in (0.0, None, 0)
