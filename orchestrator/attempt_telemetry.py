"""Pure builders for durable attempt-level routing and phase telemetry."""

from __future__ import annotations

import math
from typing import Any, Mapping


SCHEMA_VERSION = "clade.attempt_telemetry/v1"


def _timestamp(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    candidate = float(value)
    return candidate if math.isfinite(candidate) and candidate >= 0 else None


def _milliseconds(start: Any, finish: Any) -> float | None:
    start_at = _timestamp(start)
    finish_at = _timestamp(finish)
    if start_at is None or finish_at is None:
        return None
    return round(max(0.0, finish_at - start_at) * 1000, 3)


def _current(attempt: Mapping[str, Any]) -> dict[str, Any]:
    evidence = attempt.get("evidence")
    if not isinstance(evidence, Mapping):
        evidence = {}
    current = evidence.get("telemetry")
    telemetry = dict(current) if isinstance(current, Mapping) else {}
    telemetry["schema_version"] = SCHEMA_VERSION
    telemetry["attempt_index"] = attempt.get("attempt_index")
    attempt_metadata = evidence.get("attempt")
    telemetry["parent_attempt_id"] = (
        attempt_metadata.get("parent_attempt_id")
        if isinstance(attempt_metadata, Mapping)
        else None
    )
    telemetry["timing"] = dict(telemetry.get("timing") or {})
    telemetry["routing"] = dict(telemetry.get("routing") or {})
    telemetry["result"] = dict(telemetry.get("result") or {})
    return telemetry


def _routing(worker: Any) -> dict[str, Any]:
    connection = None
    envelope = getattr(worker, "execution_envelope", None)
    if envelope is not None:
        serialized = envelope.to_dict()
        resolved = serialized.get("resolved") or {}
        inference = resolved.get("inference") or {}
        connection = inference.get("connection") or resolved.get("connection")
    return {
        "agent_runtime": getattr(worker, "provider", None),
        "connection": connection,
        "model": getattr(worker, "model", None),
        "effort": getattr(worker, "effort", None),
        "route_reason": getattr(worker, "route_reason", None),
    }


def running_patch(
    attempt: Mapping[str, Any],
    worker: Any,
    *,
    observed_at: float,
) -> dict[str, Any]:
    """Record the resolved route and the instant provider inference begins."""

    telemetry = _current(attempt)
    created_at = (attempt.get("evidence") or {}).get("timing", {}).get(
        "attempt_created_at"
    )
    telemetry["timing"].update(
        {
            "queued_at": created_at,
            "inference_started_at": observed_at,
            "queue_ms": _milliseconds(created_at, observed_at),
            "inference_ms": None,
            "verify_ms": None,
        }
    )
    telemetry["routing"] = _routing(worker)
    return {"telemetry": telemetry}


def verifying_patch(
    attempt: Mapping[str, Any],
    *,
    observed_at: float,
) -> dict[str, Any]:
    """Close inference and begin the deterministic verification phase."""

    telemetry = _current(attempt)
    inference_started_at = telemetry["timing"].get("inference_started_at")
    telemetry["timing"].update(
        {
            "inference_finished_at": observed_at,
            "verify_started_at": observed_at,
            "inference_ms": _milliseconds(inference_started_at, observed_at),
        }
    )
    return {"telemetry": telemetry}


def terminal_patch(
    attempt: Mapping[str, Any],
    worker: Any,
    *,
    lifecycle_state: str,
    observed_at: float,
) -> dict[str, Any]:
    """Close the active phase and persist the final route, oracle, and outcome."""

    telemetry = _current(attempt)
    timing = telemetry["timing"]
    verify_started_at = timing.get("verify_started_at")
    inference_started_at = timing.get("inference_started_at")
    if verify_started_at is not None:
        timing.update(
            {
                "verify_finished_at": observed_at,
                "verify_ms": _milliseconds(verify_started_at, observed_at),
            }
        )
    elif inference_started_at is not None:
        timing.update(
            {
                "inference_finished_at": observed_at,
                "inference_ms": _milliseconds(inference_started_at, observed_at),
            }
        )
    telemetry["routing"] = _routing(worker)
    telemetry["result"] = {
        "outcome": lifecycle_state,
        "worker_status": getattr(worker, "status", None),
        "transition_reason": getattr(worker, "transition_reason", None),
        "verified": bool(getattr(worker, "verified", False)),
        "final_oracle": getattr(worker, "oracle_result", None),
    }
    return {"telemetry": telemetry}


def failure_patch(
    attempt: Mapping[str, Any],
    *,
    stage: str,
    observed_at: float,
) -> dict[str, Any]:
    """Persist a terminal result for failures before provider inference starts."""

    telemetry = _current(attempt)
    evidence = attempt.get("evidence") or {}
    created_at = evidence.get("timing", {}).get(
        "attempt_created_at"
    )
    requested = evidence.get("routing") or {}
    telemetry["timing"].update(
        {
            "queued_at": created_at,
            "queue_ms": _milliseconds(created_at, observed_at),
            "inference_ms": None,
            "verify_ms": None,
        }
    )
    telemetry["routing"] = {
        "agent_runtime": requested.get("requested_runtime"),
        "connection": requested.get("requested_connection"),
        "model": requested.get("requested_model"),
        "effort": requested.get("requested_effort"),
        "route_reason": f"{stage} failure",
    }
    telemetry["result"] = {
        "outcome": "failed",
        "worker_status": "failed",
        "transition_reason": f"{stage}_failure",
        "verified": False,
        "final_oracle": None,
    }
    return {"telemetry": telemetry}
