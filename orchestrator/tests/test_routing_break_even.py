"""Production-only routing break-even reports stay denominator-explicit."""

from __future__ import annotations

import json
from types import SimpleNamespace

from routes.evals import routing_break_even as routing_break_even_route
from routing_break_even import aggregate_break_even, compute_routing_break_even


def _row(
    *,
    attempt: int,
    task_class: str = "test",
    model: str = "gpt-cheap",
    effort: str | None = "low",
    success: bool = True,
    cost: float = 0.1,
    wall_ms: float = 1000,
    source_ref: str | None = None,
    lifecycle: str = "delivered",
):
    verifier = "passed" if success else "failed"
    oracle = "approved" if success else None
    return {
        "task_id": f"task-{attempt}",
        "attempt_index": attempt,
        "lifecycle_state": lifecycle,
        "evidence_json": json.dumps({
            "task": {
                "type": task_class,
                "source_ref": source_ref,
            },
            "usage": {"estimated_cost": cost},
            "telemetry": {
                "schema_version": "clade.attempt_telemetry/v1",
                "routing": {
                    "agent_runtime": "codex",
                    "model": model,
                    "effort": effort,
                },
                "timing": {
                    "queue_ms": wall_ms * 0.1,
                    "inference_ms": wall_ms * 0.7,
                    "verify_ms": wall_ms * 0.2,
                },
                "result": {
                    "verified": success,
                    "final_oracle": oracle,
                    "verifier_status": verifier,
                },
            },
        }),
    }


def test_groups_production_attempts_and_reports_fixed_uncertainty():
    rows = [
        _row(attempt=1, success=True, cost=0.1, wall_ms=1000),
        _row(attempt=2, success=False, cost=0.1, wall_ms=1200),
        _row(
            attempt=3,
            model="gpt-strong",
            effort="high",
            success=True,
            cost=0.4,
            wall_ms=2000,
        ),
        _row(
            attempt=4,
            model="gpt-strong",
            effort="high",
            success=True,
            cost=0.4,
            wall_ms=2200,
        ),
    ]

    report = aggregate_break_even(rows, min_samples=2)
    groups = report["classes"][0]["groups"]
    cheap, strong = groups

    assert report["schema_version"] == "clade.routing_break_even/v1"
    assert report["included_attempts"] == 4
    assert cheap["identity"] == {
        "task_class": "test",
        "agent_runtime": "codex",
        "model": "gpt-cheap",
        "effort": "low",
    }
    assert cheap["success_rate"] == {
        "numerator": 1,
        "denominator": 2,
        "value": 0.5,
    }
    assert cheap["success_per_usd"]["value"] == 5.0
    assert cheap["confidence_interval"]["samples"] == 1000
    assert cheap["confidence_interval"]["success_rate"] == {
        "lower": 0.0,
        "upper": 1.0,
    }
    assert strong["break_even_to_best_observed"]["independent_attempts"] == 1
    assert report["recommendation"] == {
        "evaluated": False,
        "route": None,
        "reasons": ["observational_without_matched_counterfactual"],
        "router_mutated": False,
    }


def test_insufficient_samples_refuse_break_even_and_recommendation():
    report = aggregate_break_even([_row(attempt=1)], min_samples=30)
    group = report["classes"][0]["groups"][0]

    assert group["sample_sufficient"] is False
    assert group["break_even_to_best_observed"] is None
    assert report["classes"][0]["recommendation"]["evaluated"] is False
    assert report["recommendation"]["reasons"] == ["insufficient_samples"]


def test_constructed_and_unverifiable_rows_are_excluded_with_reasons():
    constructed = _row(attempt=1, source_ref="constructed:routing-1")
    missing_cost = _row(attempt=2)
    evidence = json.loads(missing_cost["evidence_json"])
    evidence["usage"]["estimated_cost"] = None
    missing_cost["evidence_json"] = json.dumps(evidence)
    missing_timing = _row(attempt=3)
    evidence = json.loads(missing_timing["evidence_json"])
    evidence["telemetry"]["timing"]["verify_ms"] = None
    missing_timing["evidence_json"] = json.dumps(evidence)
    unreviewed = _row(attempt=4)
    evidence = json.loads(unreviewed["evidence_json"])
    evidence["telemetry"]["result"].update({
        "final_oracle": "unreviewed",
        "verifier_status": "unreliable",
    })
    unreviewed["evidence_json"] = json.dumps(evidence)

    report = aggregate_break_even(
        [constructed, missing_cost, missing_timing, unreviewed],
        min_samples=2,
    )

    assert report["included_attempts"] == 0
    assert report["exclusions"] == {
        "missing_cost": 1,
        "missing_phase_timing": 1,
        "non_production_source": 1,
        "unverifiable_outcome": 1,
    }
    assert report["recommendation"]["reasons"] == [
        "no_eligible_production_evidence"
    ]


def test_invalid_identity_schema_and_lifecycle_are_auditable_exclusions():
    non_terminal = _row(attempt=1, lifecycle="running")
    missing_class = _row(attempt=2, task_class="")
    invalid_telemetry = _row(attempt=3)
    evidence = json.loads(invalid_telemetry["evidence_json"])
    evidence["telemetry"]["schema_version"] = "unknown"
    invalid_telemetry["evidence_json"] = json.dumps(evidence)
    missing_identity = _row(attempt=4)
    evidence = json.loads(missing_identity["evidence_json"])
    evidence["telemetry"]["routing"]["model"] = ""
    missing_identity["evidence_json"] = json.dumps(evidence)

    report = aggregate_break_even(
        [non_terminal, missing_class, invalid_telemetry, missing_identity],
        min_samples=2,
    )

    assert report["exclusions"] == {
        "invalid_telemetry": 1,
        "missing_route_identity": 1,
        "missing_task_class": 1,
        "non_terminal": 1,
    }


async def test_database_report_and_route_use_latest_session_evidence(
    task_queue,
):
    task = await task_queue.add("Measured route", task_type="test")
    attempt = await task_queue.create_evidence_attempt(
        task["id"],
        evidence={
            "task": {"type": "test", "source_ref": None},
            "usage": {"estimated_cost": 0.1},
            "telemetry": {
                "schema_version": "clade.attempt_telemetry/v1",
                "routing": {
                    "agent_runtime": "codex",
                    "model": "gpt-cheap",
                    "effort": "low",
                },
                "timing": {
                    "queue_ms": 10,
                    "inference_ms": 80,
                    "verify_ms": 10,
                },
                "result": {
                    "verified": True,
                    "final_oracle": "approved",
                    "verifier_status": "passed",
                },
            },
        },
    )
    await task_queue.append_evidence_bundle(
        attempt["attempt_id"],
        lifecycle_state="running",
    )
    await task_queue.append_evidence_bundle(
        attempt["attempt_id"],
        lifecycle_state="verifying",
    )
    await task_queue.append_evidence_bundle(
        attempt["attempt_id"],
        lifecycle_state="delivered",
    )

    direct = await compute_routing_break_even(
        task_queue._db_path, min_samples=2
    )
    routed = await routing_break_even_route(
        min_samples=2,
        s=SimpleNamespace(task_queue=task_queue),
    )

    assert direct == routed
    assert direct["included_attempts"] == 1
