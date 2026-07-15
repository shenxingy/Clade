"""CI gate for the loop-review eval (evals/run_loop_eval.py).

Runs the offline loop-review fixtures through the REAL decision functions
(worker_utils.oracle_reject_depth / oracle_retry_sample_count + the reject-round
cap mirror) and asserts each fixture's convergence behavior matches its declared
`expected`. Pure/offline — no API, no subprocess. Mirrors run_oracle_eval's
offline path so an edit to the retry/fan-out logic fails CI here, not in prod.
"""
import sys
from pathlib import Path

_ORCH = Path(__file__).resolve().parents[1]
for p in (str(_ORCH), str(_ORCH / "evals")):
    if p not in sys.path:
        sys.path.insert(0, p)

import run_loop_eval as rle  # noqa: E402


def test_loop_cases_load_clean():
    cases, errs = rle.load_cases()
    schema_errs = [e for e in errs if ":" in e]
    assert not schema_errs, schema_errs
    assert cases, "no loop_cases fixtures found"


def test_loop_review_convergence_matches_expected():
    cases, _ = rle.load_cases()
    mismatches = []
    for name, case in cases:
        got = rle.replay(case)
        exp = case["expected"]
        want = {"terminal": exp["terminal"], "attempts": exp["attempts"],
                "fanout_per_attempt": exp["fanout_per_attempt"]}
        have = {"terminal": got["terminal"], "attempts": got["attempts"],
                "fanout_per_attempt": got["fanout_per_attempt"]}
        if have != want:
            mismatches.append(f"{name}: expected {want}, got {have}")
    assert not mismatches, mismatches


def test_baseline_in_sync_with_expected():
    """The committed baseline snapshot must equal the live results (so drift is a
    visible fixture/baseline diff in review, not a surprise)."""
    import json
    cases, _ = rle.load_cases()
    if not rle.BASELINE.exists():
        return
    base = json.loads(rle.BASELINE.read_text())
    drift = []
    for name, case in cases:
        got = rle.replay(case)
        summ = {"terminal": got["terminal"], "attempts": got["attempts"],
                "fanout_per_attempt": got["fanout_per_attempt"]}
        if name in base and base[name] != summ:
            drift.append(f"{name}: baseline {base[name]} != live {summ}")
    assert not drift, drift
