"""Offline tests for the resolve-rate eval harness (orchestrator/evals/).

Proves the FULL scoring pipeline (load → solve_fn → apply patch → run tests →
score) without network, Docker, or the claude CLI: the bundled synthetic
instances run through the canned solver and must score one RESOLVED and one
UNRESOLVED, and summarize() must compute the rate correctly.

Loaded via importlib by file path (evals/ is not a package) — same pattern as
test_evals.py for the oracle harness.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

EVALS_DIR = Path(__file__).parent.parent / "evals"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_eval_{name}", EVALS_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


rr = _load("run_resolve_eval")


# ─── Instance loading + schema ────────────────────────────────────────────────


def test_bundled_instances_validate():
    instances, errors = rr.load_instances()
    assert not errors, "instance schema errors:\n" + "\n".join(errors)
    ids = {i["instance_id"] for i in instances}
    assert {"synthetic-resolved", "synthetic-unresolved"} <= ids
    # both bundled cases must carry an inline repo + canned patch (offline-safe)
    for inst in instances:
        if inst.get("synthetic"):
            assert inst["synthetic"]["repo_files"]
            assert isinstance(inst["synthetic"]["canned_patch"], str)


def test_validate_instance_rejects_bad_shapes():
    base = {
        "instance_id": "x", "repo": "a/b", "base_commit": "abc",
        "problem_statement": "do x", "FAIL_TO_PASS": ["t::a"],
        "PASS_TO_PASS": [], "test_cmd": "pytest",
    }
    assert not rr.validate_instance(dict(base), "x")
    assert rr.validate_instance({**base, "FAIL_TO_PASS": []}, "x")        # empty F2P
    assert rr.validate_instance({**base, "FAIL_TO_PASS": "t::a"}, "x")    # not a list
    assert rr.validate_instance({k: v for k, v in base.items() if k != "test_cmd"}, "x")
    assert rr.validate_instance({**base, "problem_statement": "  "}, "x")  # blank
    assert rr.validate_instance({**base, "synthetic": {"repo_files": {}}}, "x")  # empty files


# ─── Scoring units ────────────────────────────────────────────────────────────


def test_parse_pytest_results():
    out = (
        "tests/test_calc.py::test_add PASSED\n"
        "tests/test_calc.py::test_mul FAILED\n"
        "tests/test_x.py::test_err ERROR\n"
    )
    parsed = rr.parse_pytest_results(out)
    assert parsed == {
        "tests/test_calc.py::test_add": True,
        "tests/test_calc.py::test_mul": False,
        "tests/test_x.py::test_err": False,
    }


def test_score_instance_contract():
    inst = {"FAIL_TO_PASS": ["t::a"], "PASS_TO_PASS": ["t::b"]}
    resolved, _ = rr.score_instance(inst, {"t::a": True, "t::b": True})
    assert resolved
    # F2P still failing → unresolved
    resolved, detail = rr.score_instance(inst, {"t::a": False, "t::b": True})
    assert not resolved and "FAIL_TO_PASS" in detail
    # P2P regressed → unresolved
    resolved, detail = rr.score_instance(inst, {"t::a": True, "t::b": False})
    assert not resolved and "PASS_TO_PASS" in detail


# ─── summarize() ──────────────────────────────────────────────────────────────


def test_summarize_rate_and_gate():
    rows = [
        {"instance_id": "a", "resolved": True, "cost": 1.0},
        {"instance_id": "b", "resolved": False, "cost": 0.5},
    ]
    s = rr.summarize(rows, threshold=0.40)
    assert s["resolved"] == 1 and s["total"] == 2
    assert s["rate"] == 0.5 and s["ok"]
    assert s["total_cost"] == 1.5 and s["avg_cost"] == 0.75
    assert not rr.summarize(rows, threshold=0.60)["ok"]      # 50% < 60%
    assert not rr.summarize([], threshold=0.0)["ok"]          # empty → not ok
    assert rr.summarize(rows, threshold=0.0)["ok"]            # 0.0 gate (dry-run) passes


# ─── Full pipeline through the canned solver (the core assertion) ─────────────


async def test_dry_run_pipeline_scores_both_verdicts():
    """End-to-end: materialize → canned solve → git apply → pytest → score, for
    the two bundled instances. The resolved case must score resolved, the
    unresolved case unresolved — proving both verdicts of the pipeline."""
    instances, errors = rr.load_instances()
    assert not errors
    by_id = {i["instance_id"]: i for i in instances}

    resolved_row = await rr.run_instance(by_id["synthetic-resolved"], rr.solve_canned)
    assert resolved_row["patched"], resolved_row["detail"]
    assert resolved_row["resolved"], f"expected resolved: {resolved_row['detail']}"

    unresolved_row = await rr.run_instance(by_id["synthetic-unresolved"], rr.solve_canned)
    # the canned patch applies but does NOT fix the bug → unresolved
    assert unresolved_row["patched"], unresolved_row["detail"]
    assert not unresolved_row["resolved"], unresolved_row["detail"]
    assert "FAIL_TO_PASS" in unresolved_row["detail"]


# ─── --dry-run CLI exits 0 ────────────────────────────────────────────────────


def test_dry_run_cli_exits_zero():
    proc = subprocess.run(
        [sys.executable, str(EVALS_DIR / "run_resolve_eval.py"), "--dry-run"],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "RESOLVED" in proc.stdout
    assert "resolve-rate:" in proc.stdout
    assert "peers (SWE-bench-Lite)" in proc.stdout
