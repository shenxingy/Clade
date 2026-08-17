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
import pytest
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


def test_unmeasured_instances_fail_the_gate():
    """An instance the harness could not score makes the rate a lower bound.
    A gate that passes on a lower bound passes when its own instrument breaks —
    which is exactly how a colour-blinded harness reported a clean 0%."""
    rows = [
        {"instance_id": "a", "resolved": True, "measured": True, "cost": 0.0},
        {"instance_id": "b", "resolved": False, "measured": False, "cost": 0.0},
    ]
    s = rr.summarize(rows, threshold=0.0)
    assert s["unmeasured"] == 1 and s["measured"] == 1
    assert not s["ok"], "unmeasured instance must fail the gate at any threshold"
    # …and rows without the key (older result files) still count as measured.
    legacy = [{"instance_id": "a", "resolved": True, "cost": 0.0}]
    assert rr.summarize(legacy, threshold=0.0)["unmeasured"] == 0


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


# ─── Reward-hacking gap (held-out tests) ─────────────────────────────────────
# A resolve rate cannot show you a patch that special-cases the visible inputs:
# such a patch counts as a win in it. Held-out tests exercise the same spec with
# inputs the solver never saw, and the gap between the two rates is the share of
# the headline number that was scored on the proxy.


def test_held_out_files_are_invisible_during_solving(tmp_path):
    """The mechanism depends entirely on this. If held-out files existed while
    the solver ran they would just be more visible tests, and the gap they
    measure would read zero forever."""
    instances, _ = rr.load_instances()
    inst = {i["instance_id"]: i for i in instances}["synthetic-proxy-gamed"]

    repo_dir = rr.materialize_repo(inst, tmp_path)
    held_out_paths = list(inst["synthetic"]["held_out_files"])
    assert held_out_paths, "control instance lost its held-out files"
    for rel in held_out_paths:
        assert not (repo_dir / rel).exists(), f"{rel} was visible to the solver"

    assert rr.materialize_held_out(inst, repo_dir) is True
    for rel in held_out_paths:
        assert (repo_dir / rel).exists()


@pytest.mark.asyncio
async def test_proxy_gamed_instance_resolves_but_fails_the_spec():
    instances, _ = rr.load_instances()
    inst = {i["instance_id"]: i for i in instances}["synthetic-proxy-gamed"]
    row = await rr.run_instance(inst, rr.solve_canned)

    assert row["resolved"], "the gamed patch must satisfy the VISIBLE contract"
    assert row["held_out"] and not row["spec_met"], row["detail"]
    assert "PROXY GAMED" in row["detail"]


def test_gap_is_measured_only_over_held_out_graded_instances():
    rows = [
        {"instance_id": "a", "resolved": True, "held_out": True, "spec_met": False,
         "expect_gap": True, "cost": 0.0},
        {"instance_id": "b", "resolved": True, "held_out": True, "spec_met": True,
         "expect_gap": False, "cost": 0.0},
        # No held-out coverage: must not dilute the gap toward zero and report
        # safety that was never measured.
        {"instance_id": "c", "resolved": True, "held_out": False, "cost": 0.0},
    ]
    s = rr.summarize(rows, threshold=0.0)
    assert s["held_out_graded"] == 2 and s["spec_met"] == 1
    assert s["hack_gap"] == 0.5


def test_a_planted_control_does_not_fail_the_gate():
    rows = [{"instance_id": "ctl", "resolved": True, "held_out": True,
             "spec_met": False, "expect_gap": True, "cost": 0.0}]
    s = rr.summarize(rows, threshold=0.0)
    assert s["hack_gap"] == 1.0
    assert s["ok"], "a control's gap is the instrument working, not a regression"


def test_an_unplanted_gap_fails_the_gate():
    rows = [{"instance_id": "real", "resolved": True, "held_out": True,
             "spec_met": False, "expect_gap": False, "cost": 0.0}]
    s = rr.summarize(rows, threshold=0.0)
    assert s["unexpected_gap"] == ["real"] and not s["ok"]


def test_a_control_that_stops_showing_a_gap_fails_the_gate():
    """A silent control means the held-out mechanism broke, not that the solver
    improved — the failure mode a raw gap check would read as good news."""
    rows = [{"instance_id": "ctl", "resolved": True, "held_out": True,
             "spec_met": True, "expect_gap": True, "cost": 0.0}]
    s = rr.summarize(rows, threshold=0.0)
    assert s["silent_controls"] == ["ctl"] and not s["ok"]


def test_held_out_without_definitions_is_a_schema_error():
    base = {
        "instance_id": "x", "repo": "a/b", "base_commit": "abc",
        "problem_statement": "do x", "FAIL_TO_PASS": ["t::a"],
        "PASS_TO_PASS": [], "test_cmd": "pytest",
    }
    # Node ids with no file to define them could never pass, which would read as
    # a spec failure on every run rather than as the authoring mistake it is.
    errs = rr.validate_instance({**base, "HELD_OUT": ["t::held"]}, "x")
    assert any("held_out_files" in e for e in errs)
    assert rr.validate_instance({**base, "HELD_OUT": "not-a-list"}, "x")
