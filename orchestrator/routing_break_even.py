"""Observational routing break-even metrics from immutable production evidence."""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import aiosqlite


SCHEMA_VERSION = "clade.routing_break_even/v1"
TELEMETRY_SCHEMA = "clade.attempt_telemetry/v1"
DEFAULT_MIN_SAMPLES = 30
BOOTSTRAP_SAMPLES = 1_000
_TERMINAL = {"delivery_pending", "delivered", "failed", "cancelled", "reverted"}
_DETERMINATE_FAILURES = {
    "failed",
    "no_diff",
    "scope_risk_expansion",
    "disagreement",
}


def _load_json(value: str | None) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def _ratio(numerator: int | float, denominator: int | float) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": round(numerator / denominator, 9) if denominator else None,
    }


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[int(quantile * (len(ordered) - 1))], 9)


def _bootstrap(rows: list[dict], seed: int) -> dict:
    """Return deterministic percentile intervals without inventing denominators."""

    if not rows:
        empty = {"lower": None, "upper": None}
        return {
            "confidence": 0.95,
            "samples": BOOTSTRAP_SAMPLES,
            "success_rate": empty,
            "success_per_usd": empty,
            "success_per_wall_hour": empty,
        }
    rng = random.Random(seed)
    n = len(rows)
    rates: list[float] = []
    per_usd: list[float] = []
    per_hour: list[float] = []
    for _ in range(BOOTSTRAP_SAMPLES):
        sample = [rows[rng.randrange(n)] for _ in range(n)]
        successes = sum(row["success"] for row in sample)
        cost = sum(row["cost_usd"] for row in sample)
        wall_hours = sum(row["wall_ms"] for row in sample) / 3_600_000
        rates.append(successes / n)
        if cost:
            per_usd.append(successes / cost)
        if wall_hours:
            per_hour.append(successes / wall_hours)
    return {
        "confidence": 0.95,
        "samples": BOOTSTRAP_SAMPLES,
        "success_rate": {
            "lower": _percentile(rates, 0.025),
            "upper": _percentile(rates, 0.975),
        },
        "success_per_usd": {
            "lower": _percentile(per_usd, 0.025),
            "upper": _percentile(per_usd, 0.975),
        },
        "success_per_wall_hour": {
            "lower": _percentile(per_hour, 0.025),
            "upper": _percentile(per_hour, 0.975),
        },
    }


def _project(row: dict) -> tuple[dict | None, str | None]:
    if row.get("lifecycle_state") not in _TERMINAL:
        return None, "non_terminal"
    evidence = _load_json(row.get("evidence_json"))
    task = evidence.get("task")
    telemetry = evidence.get("telemetry")
    usage = evidence.get("usage")
    task_class = task.get("type") if isinstance(task, dict) else None
    if not isinstance(task_class, str) or not task_class.strip():
        return None, "missing_task_class"
    source_ref = str(task.get("source_ref") or "")
    if source_ref.startswith(("constructed:", "eval:")):
        return None, "non_production_source"
    if not isinstance(telemetry, dict) or telemetry.get("schema_version") != TELEMETRY_SCHEMA:
        return None, "invalid_telemetry"
    routing = telemetry.get("routing")
    result = telemetry.get("result")
    timing = telemetry.get("timing")
    if not all(isinstance(value, dict) for value in (routing, result, timing)):
        return None, "invalid_telemetry"
    runtime = routing.get("agent_runtime")
    model = routing.get("model")
    effort = routing.get("effort")
    if (
        not isinstance(runtime, str)
        or not runtime
        or not isinstance(model, str)
        or not model
        or (effort is not None and not isinstance(effort, str))
    ):
        return None, "missing_route_identity"
    cost = _number(usage.get("estimated_cost") if isinstance(usage, dict) else None)
    if cost is None:
        return None, "missing_cost"
    phases = [_number(timing.get(key)) for key in ("queue_ms", "inference_ms", "verify_ms")]
    if any(value is None for value in phases):
        return None, "missing_phase_timing"
    verifier = result.get("verifier_status")
    oracle = result.get("final_oracle")
    verified = result.get("verified") is True
    if verifier == "passed" and oracle == "approved" and verified:
        success = 1
    elif verifier in _DETERMINATE_FAILURES or oracle == "rejected":
        success = 0
    else:
        return None, "unverifiable_outcome"
    return {
        "task_id": row.get("task_id"),
        "task_class": task_class.strip().lower(),
        "agent_runtime": runtime,
        "model": model,
        "effort": str(effort) if effort is not None else "default",
        "success": success,
        "cost_usd": cost,
        "wall_ms": sum(phases),
    }, None


def _attempts_to_match(candidate: float, target: float) -> int | None:
    """Independent-attempt estimate; callers must retain its observational caveat."""

    if target <= 0 or candidate >= target:
        return 1
    if candidate <= 0 or target >= 1:
        return None
    return max(1, math.ceil(math.log1p(-target) / math.log1p(-candidate)))


def _group_metrics(key: tuple[str, str, str, str], rows: list[dict], min_samples: int) -> dict:
    task_class, runtime, model, effort = key
    successes = sum(row["success"] for row in rows)
    total_cost = sum(row["cost_usd"] for row in rows)
    total_wall = sum(row["wall_ms"] for row in rows)
    seed = int.from_bytes(hashlib.sha256("|".join(key).encode()).digest()[:8], "big")
    return {
        "identity": {
            "task_class": task_class,
            "agent_runtime": runtime,
            "model": model,
            "effort": effort,
        },
        "attempt_count": len(rows),
        "task_count": len({row["task_id"] for row in rows}),
        "successes": successes,
        "success_rate": _ratio(successes, len(rows)),
        "cost": {
            "basis": "estimated_cost",
            "total_usd": round(total_cost, 9),
            "mean_usd_per_attempt": round(total_cost / len(rows), 9),
        },
        "wall": {
            "basis": "queue_ms + inference_ms + verify_ms",
            "total_ms": round(total_wall, 3),
            "mean_ms_per_attempt": round(total_wall / len(rows), 3),
        },
        "success_per_usd": _ratio(successes, round(total_cost, 9)),
        "success_per_wall_hour": _ratio(successes, round(total_wall / 3_600_000, 9)),
        "confidence_interval": _bootstrap(rows, seed),
        "sample_sufficient": len(rows) >= min_samples,
        "provenance": {
            "kind": "production_evidence_bundle",
            "constructed_fixture_count": 0,
        },
        "break_even_to_best_observed": None,
    }


def aggregate_break_even(rows: list[dict], min_samples: int = DEFAULT_MIN_SAMPLES) -> dict:
    """Aggregate latest evidence rows without making a causal routing claim."""

    if min_samples < 2:
        raise ValueError("min_samples must be at least 2")
    exclusions: Counter[str] = Counter()
    grouped: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        projected, reason = _project(row)
        if projected is None:
            exclusions[reason or "unknown"] += 1
            continue
        key = (
            projected["task_class"],
            projected["agent_runtime"],
            projected["model"],
            projected["effort"],
        )
        grouped[key].append(projected)

    metrics = [
        _group_metrics(key, grouped[key], min_samples)
        for key in sorted(grouped)
    ]
    by_class: dict[str, list[dict]] = defaultdict(list)
    for group in metrics:
        by_class[group["identity"]["task_class"]].append(group)

    classes = []
    for task_class, groups in sorted(by_class.items()):
        sufficient = [group for group in groups if group["sample_sufficient"]]
        reasons = []
        if len(sufficient) < 2:
            reasons.append("insufficient_comparable_groups")
        else:
            reasons.append("observational_without_matched_counterfactual")
            baseline = max(
                sufficient,
                key=lambda group: (
                    group["success_rate"]["value"],
                    group["success_per_usd"]["value"] or -1,
                    json.dumps(group["identity"], sort_keys=True),
                ),
            )
            target = baseline["success_rate"]["value"]
            for group in sufficient:
                attempts = _attempts_to_match(group["success_rate"]["value"], target)
                group["break_even_to_best_observed"] = {
                    "baseline": baseline["identity"],
                    "target_success_rate": target,
                    "independent_attempts": attempts,
                    "projected_cost_usd": (
                        round(attempts * group["cost"]["mean_usd_per_attempt"], 9)
                        if attempts is not None
                        else None
                    ),
                    "projected_serial_wall_ms": (
                        round(attempts * group["wall"]["mean_ms_per_attempt"], 3)
                        if attempts is not None
                        else None
                    ),
                    "assumption": "independent observational attempts",
                }
        classes.append({
            "task_class": task_class,
            "groups": groups,
            "recommendation": {
                "evaluated": False,
                "route": None,
                "reasons": reasons,
            },
        })

    if not classes:
        top_reasons = ["no_eligible_production_evidence"]
    elif not any(len([g for g in item["groups"] if g["sample_sufficient"]]) >= 2 for item in classes):
        top_reasons = ["insufficient_samples"]
    else:
        top_reasons = ["observational_without_matched_counterfactual"]
    return {
        "schema_version": SCHEMA_VERSION,
        "minimum_sample_size": min_samples,
        "source": "latest immutable production EvidenceBundle attempts",
        "included_attempts": sum(len(values) for values in grouped.values()),
        "excluded_attempts": sum(exclusions.values()),
        "exclusions": dict(sorted(exclusions.items())),
        "classes": classes,
        "recommendation": {
            "evaluated": False,
            "route": None,
            "reasons": top_reasons,
            "router_mutated": False,
        },
    }


async def compute_routing_break_even(
    db_path: Path,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> dict:
    async with aiosqlite.connect(str(db_path)) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT current.*
               FROM evidence_bundles AS current
               JOIN (
                   SELECT attempt_id, MAX(revision) AS revision
                   FROM evidence_bundles GROUP BY attempt_id
               ) AS latest
               ON current.attempt_id = latest.attempt_id
               AND current.revision = latest.revision
               ORDER BY current.task_id, current.attempt_index"""
        ) as cursor:
            rows = [dict(row) for row in await cursor.fetchall()]
    return aggregate_break_even(rows, min_samples=min_samples)
