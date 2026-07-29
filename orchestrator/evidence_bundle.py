"""Versioned, immutable evidence snapshots for one execution attempt.

The bundle is a stdlib-only leaf. Persistence layers must redact runtime
content before constructing a bundle; this module validates the resulting
schema, lifecycle, digest chain, and JSON portability.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


SCHEMA_VERSION = "clade.evidence/v1"
REDACTION_SCHEMA_VERSION = "clade.redaction/v1"
_VALID_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,199}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class EvidenceValidationError(ValueError):
    """Raised when an evidence snapshot or digest chain is invalid."""


class EvidenceLifecycle(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    VERIFYING = "verifying"
    DELIVERY_PENDING = "delivery_pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REVERTED = "reverted"


_TRANSITIONS = {
    EvidenceLifecycle.CREATED: frozenset(
        {
            EvidenceLifecycle.RUNNING,
            EvidenceLifecycle.FAILED,
            EvidenceLifecycle.CANCELLED,
        }
    ),
    EvidenceLifecycle.RUNNING: frozenset(
        {
            EvidenceLifecycle.VERIFYING,
            EvidenceLifecycle.FAILED,
            EvidenceLifecycle.CANCELLED,
        }
    ),
    EvidenceLifecycle.VERIFYING: frozenset(
        {
            EvidenceLifecycle.DELIVERY_PENDING,
            EvidenceLifecycle.DELIVERED,
            EvidenceLifecycle.FAILED,
            EvidenceLifecycle.CANCELLED,
        }
    ),
    EvidenceLifecycle.DELIVERY_PENDING: frozenset(
        {
            EvidenceLifecycle.DELIVERED,
            EvidenceLifecycle.FAILED,
            EvidenceLifecycle.CANCELLED,
        }
    ),
    EvidenceLifecycle.DELIVERED: frozenset({EvidenceLifecycle.REVERTED}),
    EvidenceLifecycle.FAILED: frozenset(),
    EvidenceLifecycle.CANCELLED: frozenset(),
    EvidenceLifecycle.REVERTED: frozenset(),
}


def _identifier(value: Any, *, field_name: str) -> str:
    candidate = str(value or "").strip()
    if not candidate or not _VALID_ID.fullmatch(candidate):
        raise EvidenceValidationError(
            f"{field_name} must be a non-empty opaque identifier "
            "without whitespace/control characters"
        )
    return candidate


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise EvidenceValidationError(
        f"evidence values must be JSON-compatible, got {type(value).__name__}"
    )


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _deep_merge(base: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    merged = _thaw(base)
    for key, value in patch.items():
        if isinstance(value, Mapping) and isinstance(merged.get(str(key)), dict):
            merged[str(key)] = _deep_merge(merged[str(key)], value)
        else:
            merged[str(key)] = _thaw(value)
    return merged


def _canonical_json(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise EvidenceValidationError("evidence bundle is not canonical JSON") from exc


def _digest(value: Mapping[str, Any]) -> str:
    encoded = _canonical_json(value).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _validate_redaction_metadata(value: Mapping[str, Any]) -> None:
    expected = {"schema_version", "count", "kinds", "fields"}
    if set(value) != expected:
        raise EvidenceValidationError(
            f"redaction metadata fields must be exactly {sorted(expected)}"
        )
    if value.get("schema_version") != REDACTION_SCHEMA_VERSION:
        raise EvidenceValidationError("unsupported redaction metadata schema")
    count = value.get("count")
    kinds = value.get("kinds")
    fields = value.get("fields")
    if type(count) is not int or count < 0:
        raise EvidenceValidationError("redaction count must be a non-negative integer")
    if not isinstance(kinds, Mapping) or any(
        not isinstance(key, str) or type(item) is not int or item < 0
        for key, item in kinds.items()
    ):
        raise EvidenceValidationError("redaction kinds must map strings to counts")
    if sum(kinds.values()) != count:
        raise EvidenceValidationError("redaction kind counts must equal total count")
    if not isinstance(fields, list | tuple) or any(
        not isinstance(item, str) or not item for item in fields
    ):
        raise EvidenceValidationError("redaction fields must be non-empty strings")


@dataclass(frozen=True)
class EvidenceBundle:
    schema_version: str
    bundle_id: str
    attempt_id: str
    task_id: str
    attempt_index: int
    revision: int
    lifecycle_state: EvidenceLifecycle
    recorded_at: float
    evidence: Mapping[str, Any] = field(default_factory=dict)
    redaction_metadata: Mapping[str, Any] = field(default_factory=dict)
    previous_digest: str | None = None
    digest: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise EvidenceValidationError(
                f"unsupported evidence schema: {self.schema_version!r}"
            )
        for name in ("bundle_id", "attempt_id", "task_id"):
            _identifier(getattr(self, name), field_name=name)
        if type(self.attempt_index) is not int or self.attempt_index < 1:
            raise EvidenceValidationError("attempt_index must be a positive integer")
        if type(self.revision) is not int or self.revision < 1:
            raise EvidenceValidationError("revision must be a positive integer")
        if (
            not isinstance(self.recorded_at, int | float)
            or not math.isfinite(self.recorded_at)
            or self.recorded_at < 0
        ):
            raise EvidenceValidationError(
                "recorded_at must be a non-negative finite timestamp"
            )
        try:
            state = (
                self.lifecycle_state
                if isinstance(self.lifecycle_state, EvidenceLifecycle)
                else EvidenceLifecycle(str(self.lifecycle_state))
            )
        except ValueError as exc:
            raise EvidenceValidationError(
                f"unsupported evidence lifecycle state: {self.lifecycle_state!r}"
            ) from exc
        if self.revision == 1 and self.previous_digest is not None:
            raise EvidenceValidationError("initial evidence revision cannot have a predecessor")
        if self.revision > 1 and not (
            isinstance(self.previous_digest, str)
            and _DIGEST.fullmatch(self.previous_digest)
        ):
            raise EvidenceValidationError(
                "non-initial evidence revision requires a sha256 predecessor"
            )
        if not isinstance(self.evidence, Mapping):
            raise EvidenceValidationError("evidence must be an object")
        if not isinstance(self.redaction_metadata, Mapping):
            raise EvidenceValidationError("redaction_metadata must be an object")
        redaction_metadata = _thaw(self.redaction_metadata)
        _validate_redaction_metadata(redaction_metadata)
        evidence = _freeze(self.evidence)
        redaction = _freeze(redaction_metadata)
        object.__setattr__(self, "lifecycle_state", state)
        object.__setattr__(self, "evidence", evidence)
        object.__setattr__(self, "redaction_metadata", redaction)
        expected_digest = _digest(self._unsigned_dict())
        if self.digest and self.digest != expected_digest:
            raise EvidenceValidationError("evidence bundle digest mismatch")
        object.__setattr__(self, "digest", expected_digest)

    def _unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "bundle_id": self.bundle_id,
            "attempt_id": self.attempt_id,
            "task_id": self.task_id,
            "attempt_index": self.attempt_index,
            "revision": self.revision,
            "lifecycle_state": self.lifecycle_state.value,
            "recorded_at": self.recorded_at,
            "evidence": _thaw(self.evidence),
            "redaction_metadata": _thaw(self.redaction_metadata),
            "previous_digest": self.previous_digest,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._unsigned_dict(), "digest": self.digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> EvidenceBundle:
        expected = {
            "schema_version",
            "bundle_id",
            "attempt_id",
            "task_id",
            "attempt_index",
            "revision",
            "lifecycle_state",
            "recorded_at",
            "evidence",
            "redaction_metadata",
            "previous_digest",
            "digest",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise EvidenceValidationError(
                f"evidence bundle fields must be exactly {sorted(expected)}"
            )
        if not isinstance(value.get("digest"), str) or not _DIGEST.fullmatch(
            value["digest"]
        ):
            raise EvidenceValidationError(
                "persisted evidence bundle requires a sha256 digest"
            )
        return cls(**dict(value))


def create_evidence_bundle(
    *,
    task_id: str,
    attempt_index: int,
    recorded_at: float,
    evidence: Mapping[str, Any],
    redaction_metadata: Mapping[str, Any],
    attempt_id: str | None = None,
    bundle_id: str | None = None,
) -> EvidenceBundle:
    """Create the first immutable snapshot for an execution attempt."""

    return EvidenceBundle(
        schema_version=SCHEMA_VERSION,
        bundle_id=bundle_id or f"evb-{uuid.uuid4()}",
        attempt_id=attempt_id or f"att-{uuid.uuid4()}",
        task_id=task_id,
        attempt_index=attempt_index,
        revision=1,
        lifecycle_state=EvidenceLifecycle.CREATED,
        recorded_at=recorded_at,
        evidence=evidence,
        redaction_metadata=redaction_metadata,
    )


def advance_evidence_bundle(
    previous: EvidenceBundle,
    *,
    lifecycle_state: EvidenceLifecycle | str,
    recorded_at: float,
    evidence_patch: Mapping[str, Any],
    redaction_metadata: Mapping[str, Any],
) -> EvidenceBundle:
    """Append a validated snapshot to an existing attempt digest chain."""

    try:
        next_state = (
            lifecycle_state
            if isinstance(lifecycle_state, EvidenceLifecycle)
            else EvidenceLifecycle(str(lifecycle_state))
        )
    except ValueError as exc:
        raise EvidenceValidationError(
            f"unsupported evidence lifecycle state: {lifecycle_state!r}"
        ) from exc
    if (
        next_state is not previous.lifecycle_state
        and next_state not in _TRANSITIONS[previous.lifecycle_state]
    ):
        raise EvidenceValidationError(
            f"invalid evidence lifecycle transition: "
            f"{previous.lifecycle_state.value} -> {next_state.value}"
        )
    return EvidenceBundle(
        schema_version=SCHEMA_VERSION,
        bundle_id=previous.bundle_id,
        attempt_id=previous.attempt_id,
        task_id=previous.task_id,
        attempt_index=previous.attempt_index,
        revision=previous.revision + 1,
        lifecycle_state=next_state,
        recorded_at=recorded_at,
        evidence=_deep_merge(previous.evidence, evidence_patch),
        redaction_metadata=redaction_metadata,
        previous_digest=previous.digest,
    )


def validate_evidence_chain(bundles: list[EvidenceBundle]) -> None:
    """Validate identity, revision order, digest linkage, and lifecycle order."""

    if not bundles:
        return
    first = bundles[0]
    if first.revision != 1:
        raise EvidenceValidationError("evidence chain must start at revision 1")
    previous = first
    for current in bundles[1:]:
        if (
            current.bundle_id != first.bundle_id
            or current.attempt_id != first.attempt_id
            or current.task_id != first.task_id
            or current.attempt_index != first.attempt_index
        ):
            raise EvidenceValidationError("evidence chain identity changed")
        if current.revision != previous.revision + 1:
            raise EvidenceValidationError("evidence chain has a revision gap")
        if current.previous_digest != previous.digest:
            raise EvidenceValidationError("evidence chain predecessor mismatch")
        if (
            current.lifecycle_state is not previous.lifecycle_state
            and current.lifecycle_state not in _TRANSITIONS[previous.lifecycle_state]
        ):
            raise EvidenceValidationError("evidence chain has an invalid lifecycle transition")
        previous = current
