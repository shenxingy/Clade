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
