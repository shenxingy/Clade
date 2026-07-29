#!/usr/bin/env python3
"""Offline replay of matched, recorded execution-routing arms."""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "clade.routing_case/v1"
TELEMETRY_VERSION = "clade.attempt_telemetry/v1"
CASES_DIR = Path(__file__).resolve().parent / "routing_cases"
POLICIES = ("strong_self", "native_cheap", "cheap_to_strong")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SHA = re.compile(r"^git:[0-9a-f]{40}$")
_VERIFIER_STATUSES = {"passed", "failed", "no_diff", "unreliable"}
_ORACLE_VERDICTS = {"approved", "rejected", "unreviewed", None}


def _number(value: Any, *, positive: bool = False) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, int | float)
        and math.isfinite(float(value))
        and (value > 0 if positive else value >= 0)
    )


def validate_attempt(attempt: Any, label: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(attempt, dict):
        return [f"{label}: attempt must be an object"]
    required = {
        "source_attempt_id",
        "cost_usd",
        "telemetry",
        "verification",
        "outcome",
    }
    missing = required - set(attempt)
    if missing:
        errors.append(f"{label}: missing {sorted(missing)}")
        return errors
    if not isinstance(attempt["source_attempt_id"], str) or not attempt["source_attempt_id"]:
        errors.append(f"{label}: source_attempt_id must be non-empty")
    if not _number(attempt["cost_usd"]):
        errors.append(f"{label}: cost_usd must be finite and non-negative")
    telemetry = attempt["telemetry"]
    if not isinstance(telemetry, dict) or telemetry.get("schema_version") != TELEMETRY_VERSION:
        errors.append(f"{label}: unsupported telemetry schema")
    else:
        for field in ("queue_ms", "inference_ms", "verify_ms"):
            if not _number(telemetry.get(field)):
                errors.append(f"{label}: telemetry.{field} must be finite and non-negative")
        route = telemetry.get("routing")
        if not isinstance(route, dict):
            errors.append(f"{label}: telemetry.routing must be an object")
        else:
            for field in ("agent_runtime", "model", "effort", "route_reason"):
                if not isinstance(route.get(field), str) or not route[field]:
                    errors.append(f"{label}: telemetry.routing.{field} must be non-empty")
    verification = attempt["verification"]
    if not isinstance(verification, dict):
        errors.append(f"{label}: verification must be an object")
    else:
        if verification.get("status") not in _VERIFIER_STATUSES:
            errors.append(f"{label}: unsupported verifier status")
        if verification.get("final_oracle") not in _ORACLE_VERDICTS:
            errors.append(f"{label}: unsupported final oracle")
    if attempt["outcome"] not in {"delivered", "delivery_pending", "failed"}:
        errors.append(f"{label}: unsupported outcome")
    return errors


def validate_case(case: Any, source_name: str = "?") -> list[str]:
    if not isinstance(case, dict):
        return [f"{source_name}: case must be an object"]
    errors: list[str] = []
    required = {"schema_version", "id", "source", "task", "base", "verifier", "attempts"}
    missing = required - set(case)
    if missing:
        errors.append(f"{source_name}: missing {sorted(missing)}")
        return errors
    if case["schema_version"] != SCHEMA_VERSION:
        errors.append(f"{source_name}: unsupported schema")
    if not isinstance(case["id"], str) or not case["id"]:
        errors.append(f"{source_name}: id must be non-empty")
    if not isinstance(case["source"], str) or not case["source"].startswith(
        ("constructed:", "eval:")
    ):
        errors.append(f"{source_name}: source must be constructed: or eval:")
    task = case["task"]
    if not isinstance(task, dict) or not _DIGEST.fullmatch(str(task.get("input_digest", ""))):
        errors.append(f"{source_name}: task.input_digest must be sha256")
    elif not isinstance(task.get("class"), str) or not task["class"]:
        errors.append(f"{source_name}: task.class must be non-empty")
    base = case["base"]
    if not isinstance(base, dict) or not _SHA.fullmatch(str(base.get("ref", ""))):
        errors.append(f"{source_name}: base.ref must pin an exact git SHA")
    elif not _DIGEST.fullmatch(str(base.get("tree_digest", ""))):
        errors.append(f"{source_name}: base.tree_digest must be sha256")
    verifier = case["verifier"]
    if not isinstance(verifier, dict):
        errors.append(f"{source_name}: verifier must be an object")
    else:
        if verifier.get("deterministic") is not True:
            errors.append(f"{source_name}: verifier must be deterministic")
        for field in ("id", "version"):
            if not isinstance(verifier.get(field), str) or not verifier[field]:
                errors.append(f"{source_name}: verifier.{field} must be non-empty")
        if not _DIGEST.fullmatch(str(verifier.get("digest", ""))):
            errors.append(f"{source_name}: verifier.digest must be sha256")
    attempts = case["attempts"]
    if not isinstance(attempts, dict):
        errors.append(f"{source_name}: attempts must be an object")
    else:
        for arm in ("cheap", "strong"):
            errors.extend(validate_attempt(attempts.get(arm), f"{source_name}:{arm}"))
    return errors


def load_cases(cases_dir: Path = CASES_DIR) -> tuple[list[dict], list[str]]:
    cases: list[dict] = []
    errors: list[str] = []
    seen: set[str] = set()
    for path in sorted(cases_dir.glob("*.json")):
        try:
            case = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path.name}: unreadable JSON ({exc})")
            continue
        errors.extend(validate_case(case, path.name))
        case_id = case.get("id") if isinstance(case, dict) else None
        if case_id:
            if case_id != path.stem:
                errors.append(f"{path.name}: id must match filename")
            if case_id in seen:
                errors.append(f"{path.name}: duplicate id")
            seen.add(case_id)
        if isinstance(case, dict):
            cases.append(case)
    if not cases:
        errors.append(f"no routing fixtures found in {cases_dir}")
    return cases, errors


def attempt_success(attempt: dict) -> bool:
    verification = attempt["verification"]
    return (
        attempt["outcome"] in {"delivered", "delivery_pending"}
        and verification["status"] == "passed"
        and verification["final_oracle"] != "rejected"
    )


def replay_case(case: dict) -> dict[str, list[dict]]:
    cheap = case["attempts"]["cheap"]
    strong = case["attempts"]["strong"]
    return {
        "strong_self": [strong],
        "native_cheap": [cheap],
        "cheap_to_strong": [cheap] if attempt_success(cheap) else [cheap, strong],
    }


def _ratio(numerator: float, denominator: float) -> dict[str, float | None]:
    return {
        "numerator": round(numerator, 9),
        "denominator": round(denominator, 9),
        "value": round(numerator / denominator, 9) if denominator else None,
    }


def summarize(cases: list[dict], *, k: int = 2) -> dict:
    report: dict[str, Any] = {
        "schema_version": "clade.routing_eval/v1",
        "k": k,
        "case_count": len(cases),
        "policies": {},
    }
    for policy in POLICIES:
        traces = [replay_case(case)[policy] for case in cases]
        first_successes = sum(
            bool(trace and attempt_success(trace[0])) for trace in traces
        )
        k_successes = sum(
            any(attempt_success(attempt) for attempt in trace[:k]) for trace in traces
        )
        attempts = [attempt for trace in traces for attempt in trace[:k]]
        total_cost = sum(float(attempt["cost_usd"]) for attempt in attempts)
        wall_by_case = [
            sum(
                sum(float(attempt["telemetry"][field]) for field in (
                    "queue_ms", "inference_ms", "verify_ms"
                ))
                for attempt in trace[:k]
            )
            for trace in traces
        ]
        total_wall_ms = sum(wall_by_case)
        total_queue_ms = sum(
            float(attempt["telemetry"]["queue_ms"]) for attempt in attempts
        )
        report["policies"][policy] = {
            "sample_count": len(cases),
            "attempt_count": len(attempts),
            "pass_at_1": _ratio(first_successes, len(cases)),
            "pass_at_k": _ratio(k_successes, len(cases)),
            "success_per_usd": _ratio(k_successes, total_cost),
            "success_per_wall_hour": _ratio(
                k_successes, total_wall_ms / 3_600_000
            ),
            "queue_overhead": _ratio(total_queue_ms, total_wall_ms),
            "total_cost_usd": round(total_cost, 9),
            "total_wall_ms": round(total_wall_ms, 3),
            "wall_ms_variance": {
                "sample_count": len(wall_by_case),
                "value": (
                    round(statistics.pvariance(wall_by_case), 3)
                    if wall_by_case
                    else None
                ),
            },
        }
    return report


def evaluate_thresholds(
    report: dict,
    *,
    min_samples: int = 6,
    allowed_pass_at_k_drop: float = 0.0,
) -> dict:
    if not math.isfinite(allowed_pass_at_k_drop) or allowed_pass_at_k_drop < 0:
        raise ValueError("allowed_pass_at_k_drop must be finite and non-negative")
    strong = report["policies"]["strong_self"]
    cascade = report["policies"]["cheap_to_strong"]
    reasons: list[str] = []
    if report["case_count"] < min_samples:
        return {
            "evaluated": False,
            "passed": None,
            "reasons": [f"sample_count {report['case_count']} < {min_samples}"],
        }
    strong_pass = strong["pass_at_k"]["value"]
    cascade_pass = cascade["pass_at_k"]["value"]
    if cascade_pass < strong_pass - allowed_pass_at_k_drop:
        reasons.append("cascade pass@k regressed versus strong-self")
    for metric in ("success_per_usd", "success_per_wall_hour"):
        strong_value = strong[metric]["value"]
        cascade_value = cascade[metric]["value"]
        if strong_value is None or cascade_value is None:
            reasons.append(f"{metric} has an empty denominator")
        elif cascade_value < strong_value:
            reasons.append(f"cascade {metric} regressed versus strong-self")
    return {"evaluated": True, "passed": not reasons, "reasons": reasons}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases-dir", type=Path, default=CASES_DIR)
    parser.add_argument("--k", type=int, default=2)
    parser.add_argument("--min-samples", type=int, default=6)
    parser.add_argument("--allowed-pass-at-k-drop", type=float, default=0.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if (
        args.k < 1
        or args.min_samples < 1
        or not math.isfinite(args.allowed_pass_at_k_drop)
        or args.allowed_pass_at_k_drop < 0
    ):
        parser.error(
            "k/min-samples must be positive and allowed drop finite and non-negative"
        )
    cases, errors = load_cases(args.cases_dir)
    if errors:
        for error in errors:
            print(f"SCHEMA {error}", file=sys.stderr)
        return 2
    report = summarize(cases, k=args.k)
    report["thresholds"] = evaluate_thresholds(
        report,
        min_samples=args.min_samples,
        allowed_pass_at_k_drop=args.allowed_pass_at_k_drop,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for policy in POLICIES:
            metrics = report["policies"][policy]
            print(
                f"{policy}: n={metrics['sample_count']} "
                f"pass@1={metrics['pass_at_1']['value']} "
                f"pass@{args.k}={metrics['pass_at_k']['value']} "
                f"success/$={metrics['success_per_usd']['value']} "
                f"success/wall-hour={metrics['success_per_wall_hour']['value']}"
            )
        gate = report["thresholds"]
        print(
            "thresholds: "
            + ("NOT EVALUATED" if not gate["evaluated"] else "PASS" if gate["passed"] else "FAIL")
        )
        for reason in gate["reasons"]:
            print(f"  - {reason}")
    return 0 if report["thresholds"]["passed"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
