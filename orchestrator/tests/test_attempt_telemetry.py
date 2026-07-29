"""Deterministic contract tests for attempt routing and phase telemetry."""

from __future__ import annotations

from types import SimpleNamespace

from attempt_telemetry import (
    SCHEMA_VERSION,
    failure_patch,
    running_patch,
    terminal_patch,
    verifying_patch,
)


def _merge(left, right):
    merged = dict(left)
    for key, value in right.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _advance(attempt, patch):
    return {
        **attempt,
        "evidence": _merge(attempt["evidence"], patch),
    }


def _worker():
    envelope = SimpleNamespace(
        to_dict=lambda: {
            "resolved": {
                "inference": {"connection": "openai-primary"},
            }
        }
    )
    return SimpleNamespace(
        provider="codex",
        model="gpt-5.6-terra",
        effort="medium",
        route_reason="high readiness: cheap Codex tier",
        execution_envelope=envelope,
        status="done",
        transition_reason="process_exited_rc_0",
        verified=True,
        oracle_result="approved",
    )


def test_phase_telemetry_has_explicit_millisecond_denominators():
    attempt = {
        "attempt_index": 2,
        "evidence": {
            "attempt": {"parent_attempt_id": "att-parent"},
            "timing": {"attempt_created_at": 100.0},
        },
    }
    worker = _worker()

    attempt = _advance(attempt, running_patch(attempt, worker, observed_at=101.25))
    attempt = _advance(attempt, verifying_patch(attempt, observed_at=106.5))
    patch = terminal_patch(
        attempt, worker, lifecycle_state="delivered", observed_at=108.75
    )
    telemetry = patch["telemetry"]

    assert telemetry["schema_version"] == SCHEMA_VERSION
    assert telemetry["attempt_index"] == 2
    assert telemetry["parent_attempt_id"] == "att-parent"
    assert telemetry["timing"] == {
        "queued_at": 100.0,
        "inference_started_at": 101.25,
        "queue_ms": 1250.0,
        "inference_ms": 5250.0,
        "verify_ms": 2250.0,
        "inference_finished_at": 106.5,
        "verify_started_at": 106.5,
        "verify_finished_at": 108.75,
    }
    assert telemetry["routing"] == {
        "agent_runtime": "codex",
        "connection": "openai-primary",
        "model": "gpt-5.6-terra",
        "effort": "medium",
        "route_reason": "high readiness: cheap Codex tier",
    }
    assert telemetry["result"] == {
        "outcome": "delivered",
        "worker_status": "done",
        "transition_reason": "process_exited_rc_0",
        "verified": True,
        "final_oracle": "approved",
        "verifier_status": "passed",
        "cascade_stage": None,
        "cascade_signal": None,
    }


def test_failed_inference_closes_without_fabricating_verify_time():
    attempt = {
        "attempt_index": 1,
        "evidence": {
            "attempt": {"parent_attempt_id": None},
            "timing": {"attempt_created_at": 10.0},
        },
    }
    worker = _worker()
    worker.status = "failed"
    worker.transition_reason = "process_exited_rc_1"
    worker.verified = False
    worker.oracle_result = None
    attempt = _advance(attempt, running_patch(attempt, worker, observed_at=11.0))

    telemetry = terminal_patch(
        attempt, worker, lifecycle_state="failed", observed_at=13.5
    )["telemetry"]

    assert telemetry["timing"]["inference_ms"] == 2500.0
    assert telemetry["timing"]["verify_ms"] is None
    assert "verify_started_at" not in telemetry["timing"]
    assert telemetry["result"]["outcome"] == "failed"
    assert telemetry["result"]["final_oracle"] is None


def test_preflight_failure_records_queue_only_and_clamps_clock_skew():
    attempt = {
        "attempt_index": 1,
        "evidence": {
            "attempt": {"parent_attempt_id": None},
            "timing": {"attempt_created_at": 20.0},
            "routing": {
                "requested_runtime": "codex",
                "requested_connection": "openai-primary",
                "requested_model": "gpt-5.6-terra",
                "requested_effort": "medium",
            },
        },
    }

    telemetry = failure_patch(
        attempt, stage="preflight", observed_at=19.0
    )["telemetry"]

    assert telemetry["timing"]["queue_ms"] == 0.0
    assert telemetry["timing"]["inference_ms"] is None
    assert telemetry["timing"]["verify_ms"] is None
    assert telemetry["routing"]["model"] == "gpt-5.6-terra"
    assert telemetry["routing"]["route_reason"] == "preflight failure"
    assert telemetry["result"]["transition_reason"] == "preflight_failure"
    assert telemetry["result"]["verifier_status"] is None
