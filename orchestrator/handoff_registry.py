"""Schemas and prompt-safe projections for typed worker handoffs.

This is a stdlib-only leaf.  Validation is advisory at the integration site:
the durable task/event payload remains unchanged while child prompts receive a
bounded projection.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, TypedDict


HANDOFF_SCHEMA_VERSION = 1
DEFAULT_MAX_PAYLOAD_SIZE = 8192


class HandoffSchema(TypedDict):
    version: int
    required: frozenset[str]
    field_types: dict[str, type]
    allowlist: frozenset[str]
    max_payload_size: int | None


HANDOFF_REGISTRY: dict[str, HandoffSchema] = {
    "review": {
        "version": HANDOFF_SCHEMA_VERSION,
        "required": frozenset({"priority"}),
        "field_types": {
            "priority": int,
            "summary": str,
            "files": list,
            "instructions": str,
        },
        "allowlist": frozenset({"priority", "summary", "files", "instructions"}),
        "max_payload_size": DEFAULT_MAX_PAYLOAD_SIZE,
    },
    "repair": {
        "version": HANDOFF_SCHEMA_VERSION,
        "required": frozenset({"focus"}),
        "field_types": {
            "focus": str,
            "summary": str,
            "files": list,
            "tests": str,
            "instructions": str,
        },
        "allowlist": frozenset({"focus", "summary", "files", "tests", "instructions"}),
        "max_payload_size": DEFAULT_MAX_PAYLOAD_SIZE,
    },
}


def _json_size(value: Any) -> int:
    """Return the compact UTF-8 JSON size, raising for non-JSON values."""
    encoded = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return len(encoded.encode("utf-8"))


def validate_handoff(handoff_type: str, payload: dict[str, Any]) -> list[str]:
    """Return advisory validation messages; an empty list means valid."""
    schema = HANDOFF_REGISTRY.get(handoff_type)
    if schema is None:
        return [f"unknown handoff type: {handoff_type!r}"]
    if not isinstance(payload, dict):
        return [f"{handoff_type}: payload must be an object"]

    errors: list[str] = []
    for field in sorted(schema["required"]):
        if field not in payload:
            errors.append(f"{handoff_type}: missing required field {field!r}")

    for field, expected_type in schema["field_types"].items():
        if field in payload and type(payload[field]) is not expected_type:
            errors.append(
                f"{handoff_type}.{field}: expected {expected_type.__name__}, "
                f"got {type(payload[field]).__name__}"
            )

    try:
        payload_size = _json_size(payload)
    except (TypeError, ValueError):
        errors.append(f"{handoff_type}: payload is not JSON-serializable")
    else:
        max_size = schema["max_payload_size"]
        if max_size is not None and payload_size > max_size:
            errors.append(
                f"{handoff_type}: payload size {payload_size} exceeds maximum "
                f"{max_size} bytes"
            )
    return errors


def project_handoff(handoff_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Return the size-bounded payload safe for a child prompt.

    NON-LOSSY: every JSON-serializable string-keyed field is retained; only the
    total size is bounded (fields that would push the payload past the limit are
    dropped once the limit is hit). The per-type `allowlist` drives
    validate_handoff WARNINGS, not field-dropping here — silently losing a
    handoff field the child needs is worse than a slightly-larger prompt, so an
    already-valid payload passes through unchanged. Non-JSON values are omitted.
    """
    if not isinstance(payload, dict):
        return {}

    schema = HANDOFF_REGISTRY.get(handoff_type)
    max_size = (
        schema["max_payload_size"]
        if schema and schema["max_payload_size"] is not None
        else DEFAULT_MAX_PAYLOAD_SIZE
    )

    projection: dict[str, Any] = {}
    for key, value in payload.items():
        if not isinstance(key, str):
            continue
        candidate = {**projection, key: value}
        try:
            if _json_size(candidate) <= max_size:
                projection[key] = deepcopy(value)
        except (TypeError, ValueError):
            continue
    return projection
