"""Offline tests for the versioned worker terminal envelope."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from worker_envelope import SCHEMA_VERSION, WorkerEnvelope, build_from_worker


def test_worker_envelope_round_trip():
    raw = {
        "v": SCHEMA_VERSION,
        "task_id": "task-17",
        "status": "done",
        "summary": "Added the typed completion contract.",
        "artifacts": {
            "commit": "abc123 feat: add envelope",
            "changed_files": ["worker_envelope.py"],
            "tests": "1 passed",
        },
        "next_handoff": {"type": "review", "payload": {"priority": 2}},
        "blockers": [],
        "execution": None,
    }

    envelope = WorkerEnvelope.from_dict(raw)

    assert envelope.to_dict() == raw
    assert WorkerEnvelope.from_dict(envelope.to_dict()) == envelope


@pytest.mark.parametrize(
    "mutate",
    [
        lambda data: data.update(v=SCHEMA_VERSION + 1),
        lambda data: data.pop("summary"),
        lambda data: data.update(status="running"),
        lambda data: data.update(artifacts={"changed_files": "worker.py"}),
        lambda data: data.update(next_handoff={"type": "review"}),
        lambda data: data.update(blockers=[None]),
    ],
)
def test_worker_envelope_rejects_version_mismatch_and_malformed(mutate):
    raw = {
        "v": SCHEMA_VERSION,
        "task_id": "task-17",
        "status": "done",
        "summary": "Complete.",
        "artifacts": {},
        "next_handoff": None,
        "blockers": [],
        "execution": None,
    }
    malformed = deepcopy(raw)
    mutate(malformed)

    with pytest.raises((TypeError, ValueError)):
        WorkerEnvelope.from_dict(malformed)


def test_build_from_worker_projects_existing_terminal_fields():
    worker = SimpleNamespace(
        task_id="task-22",
        status="done",
        completion_summary="Implementation complete.",
        last_commit="def456 feat: implement gap",
        changed_files=["worker.py", "worker_envelope.py"],
        test_evidence="Project tests PASSED.",
        oracle_result="rejected",
        oracle_reason="Missing malformed-input coverage.",
        _oracle_requeue=True,
        _oracle_requeue_reason="Missing malformed-input coverage.",
        _test_requeue_reason=None,
        _ownership_violation_reason=None,
        _handoff_type="repair",
        _handoff_payload={"focus": "validation"},
        failure_context=None,
        transition_reason="process_exited_rc_0",
    )

    envelope = build_from_worker(worker)

    assert envelope == WorkerEnvelope(
        v=SCHEMA_VERSION,
        task_id="task-22",
        status="rejected",
        summary="Implementation complete.",
        artifacts={
            "commit": "def456 feat: implement gap",
            "changed_files": ["worker.py", "worker_envelope.py"],
            "tests": "Project tests PASSED.",
        },
        next_handoff={"type": "repair", "payload": {"focus": "validation"}},
        blockers=["Missing malformed-input coverage."],
        execution=None,
    )


def test_legacy_v1_envelope_migrates_to_v2_with_unknown_execution():
    raw = {
        "v": 1,
        "task_id": "task-legacy",
        "status": "done",
        "summary": "Completed before execution envelopes existed.",
        "artifacts": {},
        "next_handoff": None,
        "blockers": [],
    }

    migrated = WorkerEnvelope.from_dict(raw)

    assert migrated.v == SCHEMA_VERSION
    assert migrated.execution is None
