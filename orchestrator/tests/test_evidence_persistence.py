"""SQLite persistence tests for append-only EvidenceBundle attempts."""

from __future__ import annotations

import asyncio

import aiosqlite
import pytest

from evidence_bundle import EvidenceValidationError
from task_queue import TaskQueue


OPENAI_TOKEN = "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789"


async def test_create_append_and_read_verified_evidence_chain(task_queue: TaskQueue):
    task = await task_queue.add("Collect evidence")
    initial = await task_queue.create_evidence_attempt(
        task["id"],
        attempt_id="attempt-1",
        bundle_id="bundle-1",
        recorded_at=100.0,
        evidence={
            "execution": {"schema_version": "clade.execution/v1"},
            "diagnostics": f"provider emitted {OPENAI_TOKEN}",
        },
    )
    running = await task_queue.append_evidence_bundle(
        "attempt-1",
        lifecycle_state="running",
        recorded_at=101.0,
        evidence={"git": {"base_sha": "abc"}},
    )
    verifying = await task_queue.append_evidence_bundle(
        "attempt-1",
        lifecycle_state="verifying",
        recorded_at=102.0,
        evidence={"git": {"head_sha": "def"}, "tests": {"status": "passed"}},
    )

    assert OPENAI_TOKEN not in str(initial)
    assert initial["redaction_metadata"]["count"] == 1
    assert running["previous_digest"] == initial["digest"]
    assert verifying["previous_digest"] == running["digest"]
    assert verifying["evidence"]["git"] == {"base_sha": "abc", "head_sha": "def"}

    history = await task_queue.get_evidence_history("attempt-1")
    assert [item["revision"] for item in history] == [1, 2, 3]
    assert await task_queue.get_evidence_bundle("attempt-1") == history[-1]
    assert await task_queue.list_evidence_attempts(task["id"]) == [history[-1]]


async def test_attempt_indices_are_allocated_atomically(task_queue: TaskQueue):
    task = await task_queue.add("Concurrent retries")

    attempts = await asyncio.gather(
        *[
            task_queue.create_evidence_attempt(
                task["id"],
                attempt_id=f"attempt-{index}",
                bundle_id=f"bundle-{index}",
            )
            for index in range(4)
        ]
    )

    assert sorted(item["attempt_index"] for item in attempts) == [1, 2, 3, 4]
    listed = await task_queue.list_evidence_attempts(task["id"])
    assert [item["attempt_index"] for item in listed] == [1, 2, 3, 4]


async def test_explicit_duplicate_attempt_index_is_rejected(task_queue: TaskQueue):
    task = await task_queue.add("Duplicate retry identity")
    await task_queue.create_evidence_attempt(
        task["id"],
        attempt_index=1,
        attempt_id="attempt-a",
        bundle_id="bundle-a",
    )

    with pytest.raises(aiosqlite.IntegrityError):
        await task_queue.create_evidence_attempt(
            task["id"],
            attempt_index=1,
            attempt_id="attempt-b",
            bundle_id="bundle-b",
        )


async def test_unknown_task_and_attempt_fail_closed(task_queue: TaskQueue):
    with pytest.raises(ValueError, match="unknown task"):
        await task_queue.create_evidence_attempt("missing-task")
    with pytest.raises(ValueError, match="unknown evidence attempt"):
        await task_queue.append_evidence_bundle(
            "missing-attempt",
            lifecycle_state="running",
        )
    assert await task_queue.get_evidence_bundle("missing-attempt") is None
    assert await task_queue.get_evidence_history("missing-attempt") == []


async def test_database_rejects_evidence_update_and_delete(task_queue: TaskQueue):
    task = await task_queue.add("Immutable audit")
    initial = await task_queue.create_evidence_attempt(
        task["id"], attempt_id="attempt-immutable"
    )

    async with aiosqlite.connect(str(task_queue._db_path)) as db:
        with pytest.raises(aiosqlite.IntegrityError, match="append-only"):
            await db.execute(
                "UPDATE evidence_bundles SET lifecycle_state = 'failed' "
                "WHERE attempt_id = ?",
                (initial["attempt_id"],),
            )
        await db.rollback()
        with pytest.raises(aiosqlite.IntegrityError, match="append-only"):
            await db.execute(
                "DELETE FROM evidence_bundles WHERE attempt_id = ?",
                (initial["attempt_id"],),
            )


async def test_persisted_digest_corruption_is_detected(task_queue: TaskQueue):
    task = await task_queue.add("Detect corruption")
    await task_queue.create_evidence_attempt(
        task["id"], attempt_id="attempt-corrupt"
    )

    async with aiosqlite.connect(str(task_queue._db_path)) as db:
        await db.execute("DROP TRIGGER evidence_bundles_no_update")
        await db.execute(
            "UPDATE evidence_bundles SET payload_digest = ? WHERE attempt_id = ?",
            ("sha256:" + ("0" * 64), "attempt-corrupt"),
        )
        await db.commit()

    with pytest.raises(EvidenceValidationError, match="digest mismatch"):
        await task_queue.get_evidence_bundle("attempt-corrupt")
