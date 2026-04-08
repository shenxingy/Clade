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


# ─── Completion summary / recent completions ──────────────────────────────────


async def test_completion_summary_stored(task_queue: TaskQueue):
    task = await task_queue.add("Task with summary")
    await task_queue.update(task["id"], status="done", completion_summary="Added auth module, tests pass.")
    fetched = await task_queue.get(task["id"])
    assert fetched["completion_summary"] == "Added auth module, tests pass."


async def test_get_recent_completions_returns_done_with_summary(task_queue: TaskQueue):
    t1 = await task_queue.add("Done task with summary")
    await task_queue.update(t1["id"], status="done", completion_summary="Implemented feature X.")
    t2 = await task_queue.add("Done task without summary")
    await task_queue.update(t2["id"], status="done")
    t3 = await task_queue.add("Pending task")

    results = await task_queue.get_recent_completions()
    ids = [r["id"] for r in results]
    assert t1["id"] in ids         # done + has summary → included
    assert t2["id"] not in ids     # done but no summary → excluded
    assert t3["id"] not in ids     # pending → excluded


async def test_get_recent_completions_excludes_self(task_queue: TaskQueue):
    t1 = await task_queue.add("Task A")
    await task_queue.update(t1["id"], status="done", completion_summary="Did A.")
    results = await task_queue.get_recent_completions(exclude_task_id=t1["id"])
    assert all(r["id"] != t1["id"] for r in results)


async def test_get_recent_completions_respects_limit(task_queue: TaskQueue):
    for i in range(8):
        t = await task_queue.add(f"Task {i}")
        await task_queue.update(t["id"], status="done", completion_summary=f"Done {i}.")
    results = await task_queue.get_recent_completions(limit=3)
    assert len(results) <= 3


# ─── Priority score ───────────────────────────────────────────────────────────


async def test_priority_score_default(task_queue: TaskQueue):
    """New tasks should have priority_score of 0.0."""
    task = await task_queue.add("Priority test task")
    fetched = await task_queue.get(task["id"])
    priority = fetched.get("priority_score")
    assert priority == 0.0


# ─── Context versioning ────────────────────────────────────────────────────────


async def test_context_version_zero_on_empty(task_queue: TaskQueue):
    """Context version is 0 when no tasks are done."""
    version = await task_queue.get_context_version()
    assert version == 0


async def test_context_version_increments_with_completions(task_queue: TaskQueue):
    t1 = await task_queue.add("Task A")
    await task_queue.update(t1["id"], status="done")
    t2 = await task_queue.add("Task B")
    await task_queue.update(t2["id"], status="done")
    version = await task_queue.get_context_version()
    assert version == 2


async def test_stamp_context_version(task_queue: TaskQueue):
    t1 = await task_queue.add("Completed task")
    await task_queue.update(t1["id"], status="done")
    t2 = await task_queue.add("Pending task")
    stamped = await task_queue.stamp_context_version(t2["id"])
    assert stamped == 1
    fetched = await task_queue.get(t2["id"])
    assert fetched.get("context_version") == 1
