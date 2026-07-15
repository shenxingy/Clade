#!/usr/bin/env python3
"""Oracle calibration — measure the dangerous asymmetric oracle error.

``run_oracle_eval.py`` reports whether oracle verdicts match fixture labels. A
flat pass rate hides the costly failure mode: approving a defective autonomous
change. This offline-first harness compares recorded predictions with the
ground-truth ``expected_verdict`` labels in ``oracle_cases/`` and reports a
confusion matrix, both classes' precision/recall, false-approve/reject rates,
and a deterministic bootstrap confidence interval for the false-approve rate.

By default it uses a small recorded sample; pass ``--predictions FILE`` for a
JSONL file of ``{"case": "fixture-id", "predicted": "approve|reject"}``.
``--live`` is manual/scheduled only: it reuses run_oracle_eval's real oracle
replay path to create predictions. Infra/unreviewed fixture labels are excluded
from decision metrics and reported separately.

Exit: 0 = calibration completed and the false-approve ceiling (if supplied)
was met; 1 = bad input or the ceiling was exceeded.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

import run_oracle_eval as oracle_eval


DECISION_LABELS = {"approve", "reject"}
LABEL_ALIASES = {"approved": "approve", "rejected": "reject"}
DEFAULT_BOOTSTRAP_SAMPLES = 1_000
# A deliberately small, checked-in sample makes the default command useful
# without pretending it is a full live replay. Supply --predictions for a
# production calibration run.
RECORDED_PREDICTIONS = [
    {"case": "approve-feature-with-tests", "predicted": "approve"},
    {"case": "approve-fix-with-covering-test", "predicted": "approve"},
    {"case": "reject-stub-implementation", "predicted": "reject"},
    {"case": "reject-wrong-scope", "predicted": "approve"},
]


def normalize_label(value: object) -> str | None:
    """Return the decision-class spelling for a fixture label, if applicable."""
    if not isinstance(value, str):
        return None
    value = LABEL_ALIASES.get(value, value)
    return value if value in DECISION_LABELS else None


def load_predictions(path: Path) -> tuple[dict[str, str], list[str]]:
    """Load prediction JSONL and return ``(case -> prediction, errors)``."""
    predictions: dict[str, str] = {}
    errors: list[str] = []
    try:
        lines = path.read_text().splitlines()
    except OSError as exc:
        return {}, [f"cannot read predictions {path}: {exc}"]
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"{path}:{number}: invalid JSON ({exc})")
            continue
        if not isinstance(record, dict):
            errors.append(f"{path}:{number}: prediction must be a JSON object")
            continue
        case, predicted = record.get("case"), record.get("predicted")
        if not isinstance(case, str) or not case:
            errors.append(f"{path}:{number}: 'case' must be a non-empty string")
            continue
        if predicted not in DECISION_LABELS:
            errors.append(f"{path}:{number}: 'predicted' must be approve or reject")
            continue
        if case in predictions:
            errors.append(f"{path}:{number}: duplicate prediction for {case!r}")
            continue
        predictions[case] = predicted
    return predictions, errors


def bootstrap_false_approve_ci(
    reject_outcomes: list[int], samples: int = DEFAULT_BOOTSTRAP_SAMPLES, seed: int = 0
) -> dict[str, float | int | None]:
    """Return a deterministic percentile bootstrap CI for false-approve rate.

    ``reject_outcomes`` is one 0/1 item per ground-truth reject, where 1 means
    the oracle incorrectly approved it. The function is deliberately pure so
    calibration math is unit-testable without loading an oracle or API client.
    """
    if not reject_outcomes:
        return {"confidence": 0.95, "lower": None, "upper": None, "samples": samples}
    rng = random.Random(seed)
    n = len(reject_outcomes)
    rates = sorted(sum(rng.choice(reject_outcomes) for _ in range(n)) / n for _ in range(samples))
    return {
        "confidence": 0.95,
        "lower": rates[int(0.025 * (samples - 1))],
        "upper": rates[int(0.975 * (samples - 1))],
        "samples": samples,
    }


def compute_metrics(
    labels: dict[str, str], predictions: dict[str, str], *, bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES
) -> dict:
    """Compute decision metrics from fixture labels and recorded predictions.

    Labels outside approve/reject (the oracle fixtures' ``unreviewed`` infra
    cases) are excluded. Unknown or missing predictions are reported rather
    than silently counted as correct or incorrect.
    """
    confusion = {"true_approve": 0, "false_approve": 0, "false_reject": 0, "true_reject": 0}
    excluded: list[str] = []
    missing: list[str] = []
    unknown: list[str] = []
    reject_outcomes: list[int] = []
    for case, raw_label in sorted(labels.items()):
        label = normalize_label(raw_label)
        if label is None:
            excluded.append(case)
            continue
        predicted = predictions.get(case)
        if predicted is None:
            missing.append(case)
            continue
        if predicted not in DECISION_LABELS:
            unknown.append(case)
            continue
        if label == "approve" and predicted == "approve":
            confusion["true_approve"] += 1
        elif label == "reject" and predicted == "approve":
            confusion["false_approve"] += 1
            reject_outcomes.append(1)
        elif label == "approve":  # predicted reject
            confusion["false_reject"] += 1
        else:
            confusion["true_reject"] += 1
            reject_outcomes.append(0)

    ta, fa = confusion["true_approve"], confusion["false_approve"]
    fr, tr = confusion["false_reject"], confusion["true_reject"]

    def ratio(numerator: int, denominator: int) -> float | None:
        return numerator / denominator if denominator else None

    return {
        "confusion_matrix": confusion,
        "classes": {
            "approve": {"precision": ratio(ta, ta + fa), "recall": ratio(ta, ta + fr)},
            "reject": {"precision": ratio(tr, tr + fr), "recall": ratio(tr, tr + fa)},
        },
        "false_approve_rate": ratio(fa, fa + tr),
        "false_reject_rate": ratio(fr, fr + ta),
        "false_approve_rate_ci": bootstrap_false_approve_ci(reject_outcomes, bootstrap_samples),
        "evaluated_cases": ta + fa + fr + tr,
        "excluded_infra_cases": excluded,
        "missing_predictions": missing,
        "unknown_prediction_cases": unknown,
    }


def ceiling_passes(metrics: dict, ceiling: float | None) -> bool:
    """Whether a supplied false-approve ceiling is met (empty reject set passes)."""
    rate = metrics["false_approve_rate"]
    return ceiling is None or rate is None or rate <= ceiling


def _fixture_labels(cases: list[dict]) -> dict[str, str]:
    return {case["id"]: case["expected_verdict"] for case in cases}


def _format_rate(rate: float | None) -> str:
    return "n/a" if rate is None else f"{rate:.1%}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--predictions", type=Path, help="JSONL {case, predicted: approve|reject}")
    parser.add_argument("--live", action="store_true", help="run live oracle replay (manual/scheduled only)")
    parser.add_argument("--false-approve-ceiling", type=float, help="fail when false-approve rate exceeds this")
    parser.add_argument("--bootstrap-samples", type=int, default=DEFAULT_BOOTSTRAP_SAMPLES)
    parser.add_argument("--concurrency", type=int, default=4, help="parallel live cases (default 4)")
    parser.add_argument("--model", default="", help="override live grader model")
    parser.add_argument("--cases-dir", type=Path, default=oracle_eval.ORACLE_CASES_DIR)
    parser.add_argument("--json", action="store_true", help="emit one JSON metrics object")
    args = parser.parse_args(argv)

    argument_error = None
    if args.predictions and args.live:
        argument_error = "--predictions and --live are mutually exclusive"
    elif args.false_approve_ceiling is not None and not 0 <= args.false_approve_ceiling <= 1:
        argument_error = "--false-approve-ceiling must be between 0 and 1"
    elif args.bootstrap_samples < 1:
        argument_error = "--bootstrap-samples must be at least 1"
    if argument_error:
        if args.json:
            print(json.dumps({"error": "arguments", "details": [argument_error]}))
        else:
            print(f"ERROR: {argument_error}", file=sys.stderr)
        return 1

    cases, errors = oracle_eval.load_cases(args.cases_dir)
    if errors:
        if args.json:
            print(json.dumps({"error": "fixture schema", "details": errors}))
        else:
            print("FIXTURE SCHEMA ERRORS:", *[f"  - {e}" for e in errors], sep="\n", file=sys.stderr)
        return 1

    source = "recorded sample"
    if args.live:
        source = "live oracle replay"
        raw = asyncio.run(oracle_eval._run_live(cases, args.concurrency, args.model or None))
        predictions = {result["id"]: normalize_label(result["got"]) for result in raw if not result.get("_meta")}
        predictions = {case: verdict for case, verdict in predictions.items() if verdict is not None}
    elif args.predictions:
        source = str(args.predictions)
        predictions, errors = load_predictions(args.predictions)
        if errors:
            if args.json:
                print(json.dumps({"error": "prediction input", "details": errors}))
            else:
                print("PREDICTION INPUT ERRORS:", *[f"  - {e}" for e in errors], sep="\n", file=sys.stderr)
            return 1
    else:
        predictions = {record["case"]: record["predicted"] for record in RECORDED_PREDICTIONS}

    metrics = compute_metrics(_fixture_labels(cases), predictions, bootstrap_samples=args.bootstrap_samples)
    metrics["prediction_source"] = source
    metrics["ceiling"] = args.false_approve_ceiling
    metrics["ceiling_passed"] = ceiling_passes(metrics, args.false_approve_ceiling)
    if args.json:
        print(json.dumps(metrics, sort_keys=True))
    else:
        cm = metrics["confusion_matrix"]
        print(f"oracle calibration ({source}): {metrics['evaluated_cases']} evaluated")
        print(f"confusion: true-approve={cm['true_approve']} false-approve={cm['false_approve']} "
              f"false-reject={cm['false_reject']} true-reject={cm['true_reject']}")
        for name, values in metrics["classes"].items():
            print(f"{name}: precision={_format_rate(values['precision'])} recall={_format_rate(values['recall'])}")
        ci = metrics["false_approve_rate_ci"]
        print(f"false-approve rate: {_format_rate(metrics['false_approve_rate'])} "
              f"(95% bootstrap CI {_format_rate(ci['lower'])}–{_format_rate(ci['upper'])})")
        print(f"false-reject rate: {_format_rate(metrics['false_reject_rate'])}")
        print(f"excluded infra labels: {len(metrics['excluded_infra_cases'])}; "
              f"missing predictions: {len(metrics['missing_predictions'])}")
        if args.false_approve_ceiling is not None:
            verdict = "PASS" if metrics["ceiling_passed"] else "FAIL"
            print(f"false-approve ceiling {args.false_approve_ceiling:.1%}: {verdict}")
    return 0 if metrics["ceiling_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
