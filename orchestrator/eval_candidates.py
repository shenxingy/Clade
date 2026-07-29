"""Validated identifiers and digests for quarantined eval candidates."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


SCHEMA_VERSION = "clade.eval_candidate/v1"
VALID_STATUSES = frozenset({"quarantined", "promoted", "rejected", "expired"})
VALID_TRIGGERS = frozenset(
    {
        "incident_failure",
        "oracle_rejected",
        "oracle_unreviewed",
        "oracle_disagreement",
        "managed_revert",
        "explicit_correction",
    }
)
_VALID_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,199}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class EvalCandidateValidationError(ValueError):
    """Raised when candidate provenance is malformed."""


def validate_identifier(value: Any, *, field_name: str) -> str:
    candidate = str(value or "").strip()
    if not candidate or not _VALID_ID.fullmatch(candidate):
        raise EvalCandidateValidationError(
            f"{field_name} must be a non-empty opaque identifier"
        )
    return candidate


def validate_trigger(value: Any) -> str:
    trigger = str(value or "")
    if trigger not in VALID_TRIGGERS:
        raise EvalCandidateValidationError(
            f"trigger must be one of: {', '.join(sorted(VALID_TRIGGERS))}"
        )
    return trigger


def validate_status(value: Any) -> str:
    status = str(value or "")
    if status not in VALID_STATUSES:
        raise EvalCandidateValidationError(
            f"status must be one of: {', '.join(sorted(VALID_STATUSES))}"
        )
    return status


def validate_evidence_digest(value: Any) -> str:
    digest = str(value or "")
    if not _DIGEST.fullmatch(digest):
        raise EvalCandidateValidationError(
            "source evidence digest must be canonical sha256"
        )
    return digest


def canonical_diff_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def row_to_dict(row) -> dict:
    """Decode one trusted SQLite eval-candidate row."""

    try:
        payload = json.loads(row["payload_json"])
        redaction_metadata = json.loads(row["redaction_metadata"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("persisted eval candidate contains invalid JSON") from exc
    return {
        "schema_version": row["schema_version"],
        "candidate_id": row["candidate_id"],
        "source_task_id": row["source_task_id"],
        "source_attempt_id": row["source_attempt_id"],
        "source_attempt_revision": row["source_attempt_revision"],
        "source_evidence_digest": row["source_evidence_digest"],
        "trigger": row["trigger"],
        "diff_digest": row["diff_digest"],
        "payload": payload,
        "redaction_metadata": redaction_metadata,
        "status": row["status"],
        "decision_reason": row["decision_reason"],
        "decided_by": row["decided_by"],
        "decided_at": row["decided_at"],
        "promotion_kind": row["promotion_kind"],
        "promotion_ref": row["promotion_ref"],
        "created_at": row["created_at"],
    }
