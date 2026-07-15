"""Offline tests for typed handoff validation and prompt projection."""

import json
import sys
from pathlib import Path


_ORCH = Path(__file__).resolve().parents[1]
if str(_ORCH) not in sys.path:
    sys.path.insert(0, str(_ORCH))

from handoff_registry import (  # noqa: E402
    DEFAULT_MAX_PAYLOAD_SIZE,
    HANDOFF_SCHEMA_VERSION,
    project_handoff,
    validate_handoff,
)


def test_valid_payload_has_no_errors():
    payload = {"focus": "validation", "files": ["worker.py"]}
    assert validate_handoff("repair", payload) == []


def test_unknown_type_reports_error():
    assert validate_handoff("mystery", {"context": "safe"}) == [
        "unknown handoff type: 'mystery'"
    ]


def test_missing_required_field_reports_error():
    assert validate_handoff("review", {"summary": "check this"}) == [
        "review: missing required field 'priority'"
    ]


def test_wrong_field_type_reports_error():
    assert validate_handoff("review", {"priority": "high"}) == [
        "review.priority: expected int, got str"
    ]


def test_oversize_payload_reports_error():
    errors = validate_handoff(
        "repair", {"focus": "validation", "summary": "x" * DEFAULT_MAX_PAYLOAD_SIZE}
    )
    assert len(errors) == 1
    assert "payload size" in errors[0]
    assert f"maximum {DEFAULT_MAX_PAYLOAD_SIZE} bytes" in errors[0]


def test_projection_is_non_lossy_and_bounds_only_size():
    # NON-LOSSY: a non-allowlisted field ("extra") is KEPT — the allowlist only
    # drives validate_handoff warnings, it must not silently drop a field the
    # child may need. Only the OVERSIZED field is dropped, by the size bound.
    projected = project_handoff(
        "repair",
        {
            "focus": "validation",
            "extra": "not in the allowlist but kept",
            "summary": "x" * DEFAULT_MAX_PAYLOAD_SIZE,  # oversized -> size-bounded out
            "files": ["worker.py"],
        },
    )
    assert "focus" in projected and "extra" in projected and "files" in projected
    assert "summary" not in projected  # dropped purely by the size bound, not the allowlist
    compact = json.dumps(projected, ensure_ascii=False, separators=(",", ":"))
    assert len(compact.encode("utf-8")) <= DEFAULT_MAX_PAYLOAD_SIZE


def test_known_type_round_trip_preserves_declared_payload():
    payload = {
        "priority": 2,
        "summary": "review validation changes",
        "files": ["handoff_registry.py"],
        "instructions": "check size bounds",
    }
    assert HANDOFF_SCHEMA_VERSION == 1
    assert validate_handoff("review", payload) == []
    assert project_handoff("review", payload) == payload
    assert project_handoff("review", payload) is not payload


def test_unknown_projection_is_safe_bounded_passthrough():
    payload = {"context": "keep", "large": "x" * DEFAULT_MAX_PAYLOAD_SIZE}
    projected = project_handoff("mystery", payload)
    assert projected == {"context": "keep"}
