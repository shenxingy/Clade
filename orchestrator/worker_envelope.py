"""Versioned terminal contract emitted by workers.

This module is intentionally a stdlib-only leaf so terminal reports can be
validated without importing the worker engine.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal, TypedDict


SCHEMA_VERSION = 1
WorkerStatus = Literal["done", "rejected", "failed", "blocked"]


class WorkerArtifacts(TypedDict, total=False):
    commit: str
    changed_files: list[str]
    tests: str


class WorkerHandoff(TypedDict):
    type: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class WorkerEnvelope:
    v: int
    task_id: str
    status: WorkerStatus
    summary: str
    artifacts: WorkerArtifacts
    next_handoff: WorkerHandoff | None
    blockers: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable copy of the envelope."""
        return {
            "v": self.v,
            "task_id": self.task_id,
            "status": self.status,
            "summary": self.summary,
            "artifacts": deepcopy(self.artifacts),
            "next_handoff": deepcopy(self.next_handoff),
            "blockers": list(self.blockers),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkerEnvelope:
        """Validate and deserialize a worker envelope."""
        if not isinstance(data, dict):
            raise TypeError("worker envelope must be an object")

        required = {
            "v", "task_id", "status", "summary", "artifacts",
            "next_handoff", "blockers",
        }
        if set(data) != required:
            missing = required - set(data)
            extra = set(data) - required
            raise ValueError(f"invalid worker envelope fields: missing={missing}, extra={extra}")
        if type(data["v"]) is not int or data["v"] != SCHEMA_VERSION:
            raise ValueError(f"unsupported worker envelope version: {data['v']!r}")
        if not isinstance(data["task_id"], str) or not data["task_id"]:
            raise ValueError("task_id must be a non-empty string")
        if data["status"] not in {"done", "rejected", "failed", "blocked"}:
            raise ValueError("invalid worker envelope status")
        if not isinstance(data["summary"], str):
            raise TypeError("summary must be a string")

        artifacts = data["artifacts"]
        if not isinstance(artifacts, dict) or not set(artifacts) <= {
            "commit", "changed_files", "tests",
        }:
            raise ValueError("artifacts must contain only commit, changed_files, and tests")
        if "commit" in artifacts and not isinstance(artifacts["commit"], str):
            raise TypeError("artifacts.commit must be a string")
        if "tests" in artifacts and not isinstance(artifacts["tests"], str):
            raise TypeError("artifacts.tests must be a string")
        if "changed_files" in artifacts and not _is_string_list(artifacts["changed_files"]):
            raise TypeError("artifacts.changed_files must be a list of strings")

        next_handoff = data["next_handoff"]
        if next_handoff is not None:
            if not isinstance(next_handoff, dict) or set(next_handoff) != {"type", "payload"}:
                raise ValueError("next_handoff must contain type and payload")
            if not isinstance(next_handoff["type"], str) or not next_handoff["type"]:
                raise ValueError("next_handoff.type must be a non-empty string")
            if not isinstance(next_handoff["payload"], dict):
                raise TypeError("next_handoff.payload must be an object")

        blockers = data["blockers"]
        if not _is_string_list(blockers):
            raise TypeError("blockers must be a list of strings")

        return cls(
            v=SCHEMA_VERSION,
            task_id=data["task_id"],
            status=data["status"],
            summary=data["summary"],
            artifacts=deepcopy(artifacts),
            next_handoff=deepcopy(next_handoff),
            blockers=list(blockers),
        )


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def build_from_worker(w: Any) -> WorkerEnvelope:
    """Project a worker's existing terminal fields into the versioned contract."""
    raw_status = getattr(w, "status", None)
    oracle_rejected = (
        getattr(w, "oracle_result", None) == "rejected"
        or bool(getattr(w, "_oracle_requeue", False))
    )
    if raw_status == "blocked":
        status: WorkerStatus = "blocked"
    elif oracle_rejected:
        status = "rejected"
    elif raw_status == "done":
        status = "done"
    else:
        status = "failed"

    summary = getattr(w, "completion_summary", None)
    if not isinstance(summary, str) or not summary:
        candidates = (
            getattr(w, "oracle_reason", None) if status == "rejected" else None,
            getattr(w, "failure_context", None),
            getattr(w, "transition_reason", None),
        )
        summary = next((item for item in candidates if isinstance(item, str) and item), "")

    artifacts: WorkerArtifacts = {}
    commit = getattr(w, "last_commit", None)
    if isinstance(commit, str) and commit:
        artifacts["commit"] = commit
    changed_files = getattr(w, "changed_files", None)
    if _is_string_list(changed_files):
        artifacts["changed_files"] = list(changed_files)
    tests = getattr(w, "test_evidence", None)
    if isinstance(tests, str) and tests:
        artifacts["tests"] = tests

    handoff_type = getattr(w, "_handoff_type", None)
    handoff_payload = getattr(w, "_handoff_payload", None)
    next_handoff: WorkerHandoff | None = None
    if isinstance(handoff_type, str) and handoff_type and isinstance(handoff_payload, dict):
        next_handoff = {"type": handoff_type, "payload": deepcopy(handoff_payload)}

    blockers: list[str] = []
    existing_blockers = getattr(w, "blockers", None)
    if _is_string_list(existing_blockers):
        blockers.extend(existing_blockers)
    blocker_fields = (
        "_oracle_requeue_reason",
        "_test_requeue_reason",
        "_ownership_violation_reason",
    )
    for field in blocker_fields:
        blocker = getattr(w, field, None)
        if isinstance(blocker, str) and blocker and blocker not in blockers:
            blockers.append(blocker)
    if status in {"failed", "blocked"}:
        failure = getattr(w, "failure_context", None)
        if isinstance(failure, str) and failure and failure not in blockers:
            blockers.append(failure)

    return WorkerEnvelope(
        v=SCHEMA_VERSION,
        task_id=str(getattr(w, "task_id")),
        status=status,
        summary=summary,
        artifacts=artifacts,
        next_handoff=next_handoff,
        blockers=blockers,
    )
