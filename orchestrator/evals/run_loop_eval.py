#!/usr/bin/env python3
"""Loop-review eval — the retry/convergence loop AROUND the oracle review.

The existing evals test the oracle *verdict* on one diff (oracle_cases/) and the
supervisor *parser* (supervisor_cases/). Neither tests what the loop DOES with a
SEQUENCE of verdicts: when does a rejection get one sequential retry vs. a diverse
fan-out (plateau escape), and when does the reject-round cap escalate instead of
requeuing forever. That convergence behavior is the whole point of the loop and
was previously unguarded — an edit to oracle_retry_sample_count or the cap could
silently change fan-out width or let a wrong approach requeue past the cap.

This harness drives the REAL decision functions over recorded verdict sequences,
OFFLINE (pure functions — no API, no subprocess, no worktree; runs in <1s):

  - worker_utils.oracle_reject_depth(description)          — lineage reject count
  - worker_utils.oracle_retry_sample_count(desc, crit, n)  — fan-out width per depth

The ONE piece of loop logic not yet extracted to a pure function is the
reject-round cap gate (worker.py:~994: `max_reject_rounds > 0 and depth >= cap`
-> escalate instead of requeue). It is replicated here as _hit_reject_cap() and
MUST be kept in sync with worker.py — see the SYNC comment there. Everything else
is the live code.

Each fixture in loop_cases/ declares a verdict sequence + is_critical + optional
config overrides + the expected per-attempt fan-out and terminal state. A run:
  - replays each sequence through the real functions,
  - records a per-attempt JSONL trace,
  - fails (exit 1) on any `expected` mismatch,
  - reports any drift vs loop_cases/_baseline.json (snapshot; --update-baseline).

Usage:
  python3 evals/run_loop_eval.py               # run all cases, assert `expected`
  python3 evals/run_loop_eval.py --json         # emit per-attempt JSONL to stdout
  python3 evals/run_loop_eval.py --update-baseline
Exit: 0 = all cases match `expected` (and, if present, baseline); 1 = mismatch.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# evals/ lives under orchestrator/; make the package importable from anywhere.
_ORCH = Path(__file__).resolve().parents[1]
if str(_ORCH) not in sys.path:
    sys.path.insert(0, str(_ORCH))

from worker_utils import (  # noqa: E402  (path set above)
    ORACLE_REJECT_MARKER,
    oracle_reject_depth,
    oracle_retry_sample_count,
)

CASES_DIR = Path(__file__).resolve().parent / "loop_cases"
BASELINE = CASES_DIR / "_baseline.json"

# Shipped defaults (config._SETTINGS_DEFAULTS). A case may override per-fixture so
# a threshold change is a visible fixture diff, not a hidden config dependency.
DEFAULT_SAMPLES = 3        # parallel_fix_samples
DEFAULT_MAX_REJECT = 5     # oracle_max_reject_rounds

_TERMINALS = {"converged", "escalated", "exhausted"}
_VERDICTS = {"approve", "reject"}


def _hit_reject_cap(depth: int, max_reject_rounds: int) -> bool:
    """Mirror of worker.py's reject-round-cap gate (worker.py: handle_oracle_requeue
    site, ``max_reject_rounds > 0 and depth >= max_reject_rounds`` -> escalate).

    SYNC: if that condition changes in worker.py, change it here. This is the only
    replicated (non-driven) loop logic; the fan-out width below is the live fn.
    """
    return max_reject_rounds > 0 and depth >= max_reject_rounds


def validate_case(case: dict, name: str) -> list[str]:
    errs: list[str] = []
    if not isinstance(case.get("verdicts"), list) or not case["verdicts"]:
        errs.append(f"{name}: 'verdicts' must be a non-empty list")
    else:
        for v in case["verdicts"]:
            if v not in _VERDICTS:
                errs.append(f"{name}: verdict {v!r} not in {sorted(_VERDICTS)}")
    exp = case.get("expected")
    if not isinstance(exp, dict):
        errs.append(f"{name}: 'expected' object required")
    else:
        if exp.get("terminal") not in _TERMINALS:
            errs.append(f"{name}: expected.terminal must be one of {sorted(_TERMINALS)}")
        if not isinstance(exp.get("attempts"), int):
            errs.append(f"{name}: expected.attempts (int) required")
        if not isinstance(exp.get("fanout_per_attempt"), list):
            errs.append(f"{name}: expected.fanout_per_attempt (list) required")
    return errs


def replay(case: dict) -> dict:
    """Drive the REAL decision functions over the verdict sequence.

    Returns {terminal, attempts, fanout_per_attempt, trace[]} — trace is the
    per-attempt JSONL record (attempt, reject-depth seen, verdict, decision, fanout).
    """
    cfg = case.get("config") or {}
    samples = int(cfg.get("parallel_fix_samples", DEFAULT_SAMPLES))
    max_reject = int(cfg.get("oracle_max_reject_rounds", DEFAULT_MAX_REJECT))
    is_critical = bool(case.get("is_critical", False))

    description = case.get("base_description", "loop-review eval task")
    fanout_per_attempt: list[int] = []
    trace: list[dict] = []
    terminal = "exhausted"
    attempts = 0

    for i, verdict in enumerate(case["verdicts"], start=1):
        attempts = i
        depth = oracle_reject_depth(description)  # LIVE: prior-rejection count
        if verdict == "approve":
            fanout_per_attempt.append(0)
            trace.append({"attempt": i, "depth": depth, "verdict": "approve",
                          "decision": "converge", "fanout": 0})
            terminal = "converged"
            break
        # verdict == "reject"
        if _hit_reject_cap(depth, max_reject):
            fanout_per_attempt.append(0)
            trace.append({"attempt": i, "depth": depth, "verdict": "reject",
                          "decision": "escalate", "fanout": 0})
            terminal = "escalated"
            break
        fanout = oracle_retry_sample_count(description, is_critical, samples)  # LIVE
        fanout_per_attempt.append(fanout)
        trace.append({"attempt": i, "depth": depth, "verdict": "reject",
                      "decision": "requeue", "fanout": fanout})
        # A requeue appends the marker (oracle_reject_depth docstring), so the next
        # attempt sees depth+1 — this is how the lineage accumulates.
        description = f"{description} {ORACLE_REJECT_MARKER}"

    return {"terminal": terminal, "attempts": attempts,
            "fanout_per_attempt": fanout_per_attempt, "trace": trace}


def load_cases() -> tuple[list[tuple[str, dict]], list[str]]:
    cases, errs = [], []
    for path in sorted(CASES_DIR.glob("*.json")):
        if path.name.startswith("_"):  # _baseline.json etc.
            continue
        try:
            case = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            errs.append(f"{path.name}: invalid JSON ({e})")
            continue
        errs.extend(validate_case(case, path.stem))
        cases.append((path.stem, case))
    if not cases:
        errs.append(f"no fixtures found in {CASES_DIR}")
    return cases, errs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="emit per-attempt JSONL traces to stdout")
    ap.add_argument("--update-baseline", action="store_true", help="write current results to _baseline.json and exit 0")
    args = ap.parse_args()

    cases, errs = load_cases()
    schema_errs = [e for e in errs if ":" in e]
    if schema_errs:
        for e in schema_errs:
            print(f"SCHEMA {e}", file=sys.stderr)
        return 1

    results: dict[str, dict] = {}
    failures: list[str] = []
    for name, case in cases:
        r = replay(case)
        summary = {"terminal": r["terminal"], "attempts": r["attempts"],
                   "fanout_per_attempt": r["fanout_per_attempt"]}
        results[name] = summary
        if args.json:
            for rec in r["trace"]:
                print(json.dumps({"case": name, **rec}))
        exp = case["expected"]
        got = summary
        want = {"terminal": exp["terminal"], "attempts": exp["attempts"],
                "fanout_per_attempt": exp["fanout_per_attempt"]}
        ok = got == want
        if not args.json:
            mark = "PASS" if ok else "FAIL"
            print(f"  [{mark}] {name}: {got['terminal']} in {got['attempts']} attempts, "
                  f"fanout={got['fanout_per_attempt']}")
        if not ok:
            failures.append(f"{name}: expected {want}, got {got}")

    if args.update_baseline:
        BASELINE.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
        print(f"\nBaseline written: {BASELINE} ({len(results)} cases)")
        return 0

    drift: list[str] = []
    if BASELINE.exists():
        base = json.loads(BASELINE.read_text())
        for name, summ in results.items():
            if name in base and base[name] != summ:
                drift.append(f"{name}: baseline {base[name]} -> now {summ}")

    if not args.json:
        if failures:
            print(f"\nFAIL: {len(failures)}/{len(cases)} cases mismatch `expected`:", file=sys.stderr)
            for f in failures:
                print(f"  - {f}", file=sys.stderr)
        if drift:
            print(f"\nDRIFT vs baseline ({len(drift)}) — run --update-baseline if intended:", file=sys.stderr)
            for d in drift:
                print(f"  - {d}", file=sys.stderr)
        if not failures and not drift:
            print(f"\nOK: {len(cases)} loop-review cases match `expected` and baseline.")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
