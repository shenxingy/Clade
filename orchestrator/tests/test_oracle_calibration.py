"""Pure/offline unit tests for oracle calibration math and its ceiling gate."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ORCH = Path(__file__).resolve().parents[1]
_EVALS = _ORCH / "evals"
for path in (str(_ORCH), str(_EVALS)):
    if path not in sys.path:
        sys.path.insert(0, path)

import run_oracle_calibration as calibration  # noqa: E402


def test_known_confusion_metrics_are_exact():
    labels = {"a": "approve", "b": "approve", "c": "reject", "d": "reject"}
    predictions = {"a": "approve", "b": "reject", "c": "approve", "d": "reject"}
    metrics = calibration.compute_metrics(labels, predictions, bootstrap_samples=20)

    assert metrics["confusion_matrix"] == {
        "true_approve": 1, "false_approve": 1, "false_reject": 1, "true_reject": 1,
    }
    assert metrics["classes"] == {
        "approve": {"precision": 0.5, "recall": 0.5},
        "reject": {"precision": 0.5, "recall": 0.5},
    }
    assert metrics["false_approve_rate"] == 0.5
    assert metrics["false_reject_rate"] == 0.5
    assert metrics["false_approve_rate_ci"]["confidence"] == 0.95


def test_infra_labels_are_excluded_from_decision_metrics():
    metrics = calibration.compute_metrics(
        {"good": "approved", "bad": "rejected", "infra": "unreviewed"},
        {"good": "approve", "bad": "reject", "infra": "approve"},
        bootstrap_samples=20,
    )
    assert metrics["evaluated_cases"] == 2
    assert metrics["excluded_infra_cases"] == ["infra"]
    assert metrics["confusion_matrix"] == {
        "true_approve": 1, "false_approve": 0, "false_reject": 0, "true_reject": 1,
    }


def test_ceiling_gate_exits_nonzero_when_false_approves_exceed_it(tmp_path):
    predictions = tmp_path / "predictions.jsonl"
    cases, errors = calibration.oracle_eval.load_cases()
    assert not errors
    predictions.write_text("\n".join(
        json_line(case["id"], "approve" if case["expected_verdict"] == "rejected" else "reject")
        for case in cases if case["expected_verdict"] != "unreviewed"
    ) + "\n")
    proc = subprocess.run(
        [sys.executable, str(_EVALS / "run_oracle_calibration.py"),
         "--predictions", str(predictions), "--false-approve-ceiling", "0", "--json"],
        capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr


def json_line(case: str, predicted: str) -> str:
    return f'{{"case": "{case}", "predicted": "{predicted}"}}'
