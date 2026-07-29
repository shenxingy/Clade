"""Offline policy-comparison tests for recorded routing replay fixtures."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest


EVALS = Path(__file__).resolve().parents[1] / "evals"
if str(EVALS) not in sys.path:
    sys.path.insert(0, str(EVALS))

import run_routing_eval as routing_eval  # noqa: E402


def test_routing_cases_load_clean_and_sanitized():
    cases, errors = routing_eval.load_cases()

    assert errors == []
    assert len(cases) == 6
    serialized = str(cases)
    assert "/home/" not in serialized
    assert "sk-proj-" not in serialized
    assert "ghp_" not in serialized


def test_cascade_short_circuits_or_executes_strong_fallback():
    cases, _ = routing_eval.load_cases()
    by_id = {case["id"]: case for case in cases}

    short = routing_eval.replay_case(by_id["cheap-pass-transform"])
    fallback = routing_eval.replay_case(by_id["cheap-fail-test"])

    assert len(short["cheap_to_strong"]) == 1
    assert len(fallback["cheap_to_strong"]) == 2
    assert routing_eval.attempt_success(fallback["cheap_to_strong"][0]) is False
    assert routing_eval.attempt_success(fallback["cheap_to_strong"][1]) is True


def test_report_has_explicit_denominators_and_passes_thresholds():
    cases, _ = routing_eval.load_cases()
    report = routing_eval.summarize(cases)
    strong = report["policies"]["strong_self"]
    cascade = report["policies"]["cheap_to_strong"]

    assert strong["pass_at_k"] == {
        "numerator": 4,
        "denominator": 6,
        "value": 0.666666667,
    }
    assert cascade["pass_at_1"]["value"] == 0.5
    assert cascade["pass_at_k"]["value"] == 0.833333333
    assert cascade["success_per_usd"]["value"] == 14.492753623
    assert cascade["success_per_wall_hour"]["value"] == 60.0
    assert cascade["queue_overhead"]["value"] == 0.04
    assert cascade["wall_ms_variance"]["sample_count"] == 6
    assert routing_eval.evaluate_thresholds(report)["passed"] is True


def test_empty_denominators_are_null_and_threshold_is_not_evaluated():
    report = routing_eval.summarize([])

    for policy in routing_eval.POLICIES:
        metrics = report["policies"][policy]
        assert metrics["pass_at_1"]["value"] is None
        assert metrics["pass_at_k"]["value"] is None
        assert metrics["success_per_usd"]["value"] is None
        assert metrics["success_per_wall_hour"]["value"] is None
        assert metrics["queue_overhead"]["value"] is None
        assert metrics["wall_ms_variance"]["value"] is None
    gate = routing_eval.evaluate_thresholds(report)
    assert gate["evaluated"] is False
    assert gate["passed"] is None


def test_threshold_gate_fails_a_cascade_efficiency_regression():
    cases, _ = routing_eval.load_cases()
    report = routing_eval.summarize(cases)
    regressed = copy.deepcopy(report)
    regressed["policies"]["cheap_to_strong"]["success_per_usd"]["value"] = 1.0

    gate = routing_eval.evaluate_thresholds(regressed)

    assert gate["evaluated"] is True
    assert gate["passed"] is False
    assert "cascade success_per_usd regressed versus strong-self" in gate["reasons"]


@pytest.mark.parametrize("allowed_drop", [float("nan"), float("inf"), float("-inf")])
def test_threshold_gate_rejects_non_finite_allowed_drop(allowed_drop):
    cases, _ = routing_eval.load_cases()
    report = routing_eval.summarize(cases)

    with pytest.raises(ValueError, match="finite and non-negative"):
        routing_eval.evaluate_thresholds(
            report, allowed_pass_at_k_drop=allowed_drop
        )


@pytest.mark.parametrize("allowed_drop", ["nan", "inf", "-inf"])
def test_cli_rejects_non_finite_allowed_drop(allowed_drop, capsys):
    with pytest.raises(SystemExit) as caught:
        routing_eval.main([f"--allowed-pass-at-k-drop={allowed_drop}"])

    assert caught.value.code == 2
    assert "allowed drop finite and non-negative" in capsys.readouterr().err


def test_schema_rejects_unmatched_or_unreliable_input_contract():
    cases, _ = routing_eval.load_cases()
    case = copy.deepcopy(cases[0])
    case["verifier"]["deterministic"] = False
    del case["attempts"]["strong"]

    errors = routing_eval.validate_case(case, "broken.json")

    assert "broken.json: verifier must be deterministic" in errors
    assert any("broken.json:strong" in error for error in errors)


def test_cli_gate_passes_for_committed_corpus(capsys):
    assert routing_eval.main([]) == 0
    assert "thresholds: PASS" in capsys.readouterr().out
