"""Quarantined eval candidates retain safe, exact failure provenance."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiosqlite
import pytest

from eval_candidates import EvalCandidateValidationError
from routes.workers import message_worker


GITHUB_TOKEN = "ghp_" + "A" * 40


async def _attempt(task_queue, *, attempt_id="attempt-eval"):
    task = await task_queue.add("Generate a regression candidate")
    bundle = await task_queue.create_evidence_attempt(
        task["id"],
        attempt_id=attempt_id,
        bundle_id=f"bundle-{attempt_id}",
        recorded_at=100.0,
    )
    return task, bundle


async def test_candidate_is_redacted_deduplicated_and_pinned(task_queue):
    task, source = await _attempt(task_queue)
    raw_diff = f"fix {GITHUB_TOKEN} in /home/alex/private/repo"
    first, created = await task_queue.create_eval_candidate(
        source["attempt_id"],
        trigger="oracle_rejected",
        diff=raw_diff,
        payload={"reason": raw_diff},
        source_attempt_revision=source["revision"],
        source_evidence_digest=source["digest"],
        created_at=101.0,
    )
    duplicate, duplicate_created = await task_queue.create_eval_candidate(
        source["attempt_id"],
        trigger="oracle_rejected",
        diff=raw_diff,
        payload={"reason": "a later duplicate cannot mutate the first row"},
        source_attempt_revision=source["revision"],
        source_evidence_digest=source["digest"],
    )

    assert created is True
    assert duplicate_created is False
    assert duplicate == first
    assert first["schema_version"] == "clade.eval_candidate/v1"
    assert first["source_task_id"] == task["id"]
    assert first["status"] == "quarantined"
    assert first["decision_reason"] is None
    assert first["promotion_ref"] is None
    assert GITHUB_TOKEN not in json.dumps(first)
    assert "/home/alex" not in json.dumps(first)
    assert first["redaction_metadata"]["count"] == 4

    await task_queue.append_evidence_bundle(
        source["attempt_id"], lifecycle_state="running", recorded_at=102.0
    )
    persisted = await task_queue.get_eval_candidate(first["candidate_id"])
    assert persisted["source_attempt_revision"] == source["revision"]
    assert persisted["source_evidence_digest"] == source["digest"]

    async with aiosqlite.connect(str(task_queue._db_path)) as db:
        async with db.execute(
            "SELECT payload_json, redaction_metadata FROM eval_candidates"
        ) as cursor:
            stored = await cursor.fetchone()
    assert GITHUB_TOKEN not in stored[0]
    assert "/home/alex" not in stored[0]
    assert GITHUB_TOKEN not in stored[1]


async def test_candidate_identity_includes_trigger_and_sanitized_diff(task_queue):
    _, source = await _attempt(task_queue)
    one, _ = await task_queue.create_eval_candidate(
        source["attempt_id"], trigger="oracle_rejected", diff="patch one"
    )
    two, _ = await task_queue.create_eval_candidate(
        source["attempt_id"], trigger="oracle_disagreement", diff="patch one"
    )
    three, _ = await task_queue.create_eval_candidate(
        source["attempt_id"], trigger="oracle_rejected", diff="patch two"
    )

    assert len({one["candidate_id"], two["candidate_id"], three["candidate_id"]}) == 3
    assert len(await task_queue.list_eval_candidates()) == 3


async def test_candidate_validation_fails_closed(task_queue):
    _, source = await _attempt(task_queue)
    with pytest.raises(EvalCandidateValidationError, match="trigger"):
        await task_queue.create_eval_candidate(
            source["attempt_id"], trigger="model_says_correct", diff=""
        )
    with pytest.raises(ValueError, match="positive integer"):
        await task_queue.create_eval_candidate(
            source["attempt_id"],
            trigger="incident_failure",
            diff="",
            source_attempt_revision=0,
        )
    with pytest.raises(EvalCandidateValidationError, match="canonical sha256"):
        await task_queue.create_eval_candidate(
            source["attempt_id"],
            trigger="incident_failure",
            diff="",
            source_evidence_digest="not-a-digest",
        )
    with pytest.raises(ValueError, match="invalid eval candidate status"):
        await task_queue.list_eval_candidates(status="accepted")


async def test_managed_revert_creates_quarantined_candidate(task_queue):
    _, source = await _attempt(task_queue)
    await task_queue.append_evidence_bundle(
        source["attempt_id"], lifecycle_state="running"
    )
    await task_queue.append_evidence_bundle(
        source["attempt_id"], lifecycle_state="verifying"
    )
    await task_queue.append_evidence_bundle(
        source["attempt_id"], lifecycle_state="delivered"
    )
    reverted = await task_queue.append_evidence_bundle(
        source["attempt_id"],
        lifecycle_state="reverted",
        evidence={"diff": "revert patch", "reason": "production regression"},
    )

    candidates = await task_queue.list_eval_candidates()
    assert len(candidates) == 1
    assert candidates[0]["trigger"] == "managed_revert"
    assert candidates[0]["source_attempt_revision"] == reverted["revision"]
    assert candidates[0]["source_evidence_digest"] == reverted["digest"]


async def test_explicit_correction_links_latest_attempt(task_queue):
    task, source = await _attempt(task_queue)
    worker = SimpleNamespace(
        id="worker-correction",
        task_id=task["id"],
        description="Implement the original request",
        failure_context="Tests failed in parser",
        model="sonnet",
        agent_runtime="claude",
        effort=None,
        stop=AsyncMock(),
    )
    new_worker = SimpleNamespace(id="worker-retry")
    worker_pool = SimpleNamespace(
        get=lambda worker_id: worker if worker_id == worker.id else None,
        start_worker=AsyncMock(return_value=new_worker),
    )
    session = SimpleNamespace(
        task_queue=task_queue,
        worker_pool=worker_pool,
        project_dir=None,
        claude_dir=None,
    )

    response = await message_worker(
        worker.id,
        {"message": f"Preserve comments; token {GITHUB_TOKEN}"},
        s=session,
    )

    assert response["new_worker_id"] == new_worker.id
    candidates = await task_queue.list_eval_candidates()
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["trigger"] == "explicit_correction"
    assert candidate["source_attempt_id"] == source["attempt_id"]
    assert GITHUB_TOKEN not in json.dumps(candidate)
    assert candidate["status"] == "quarantined"
