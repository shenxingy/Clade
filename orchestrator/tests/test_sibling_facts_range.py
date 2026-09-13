"""An unresolvable range is its own outcome — not clean, not a crash.

The CI line was `--range origin/main...HEAD || true`. On a push to main
origin/main IS HEAD, so the range was empty and the gate printed the clean
sentence on every commit it was meant to examine. Making the range
`HEAD~1..HEAD` then crashed the job, because actions/checkout is shallow by
default and HEAD~1 was never fetched. Three outcomes, and each must look
different from the other two.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "configs" / "scripts" / "check-sibling-facts.py"


def _run(*args):
    return subprocess.run([sys.executable, str(GATE), *args],
                          capture_output=True, text=True, cwd=REPO, check=False)


def test_an_unresolvable_range_says_so_and_exits_zero():
    out = _run("--range", "definitely-not-a-ref-xyz..HEAD")
    assert out.returncode == 0
    assert "RANGE NOT CHECKED" in out.stdout


def test_an_unresolvable_range_never_prints_the_clean_sentence():
    # The whole defect: "nothing was examined" reading as "nothing was wrong".
    out = _run("--range", "definitely-not-a-ref-xyz..HEAD")
    assert "no changed fact survives anywhere else" not in out.stdout


def test_a_resolvable_range_still_reports():
    out = _run("--range", "HEAD~1..HEAD")
    assert out.returncode == 0
    assert "RANGE NOT CHECKED" not in out.stdout
    assert ("no changed fact survives" in out.stdout
            or "still present elsewhere" in out.stdout)


def test_strict_does_not_fail_on_an_unavailable_range():
    # An environment limitation is not a finding.
    assert _run("--range", "nope..HEAD", "--strict").returncode == 0


def _ci_run_lines() -> list[str]:
    """The executable lines of the sibling-facts step, comments excluded.

    Checking the whole block matched the COMMENT that explains the past bug —
    the same trap the gate's own absence markers exist for, one level up.
    """
    workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    block = workflow.split("Sibling facts")[1].split("- name:")[0]
    return [ln.strip() for ln in block.splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def test_the_ci_step_does_not_use_the_empty_three_dot_range_on_push():
    lines = _ci_run_lines()
    assert any("check-sibling-facts.py" in ln for ln in lines)
    assert not any("origin/main...HEAD" in ln for ln in lines), (
        "on a push to main, actions/checkout leaves origin/main at the pushed "
        "SHA, so this range is empty and the gate reports a clean tree")
    assert any("--deepen=1" in ln for ln in lines), "the push branch needs HEAD~1"


def test_the_ci_step_no_longer_swallows_the_gates_exit_code():
    # `|| true` on the `git fetch --deepen` is fine: a full clone cannot deepen.
    # On the gate itself it hid the RuntimeError that exists to be loud.
    for line in _ci_run_lines():
        if "check-sibling-facts.py" in line:
            assert "|| true" not in line, line


def _load():
    spec = importlib.util.spec_from_file_location("csf", GATE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["csf"] = module
    spec.loader.exec_module(module)
    return module


def test_skip_dirs_are_matched_relative_to_the_repository(tmp_path):
    # rglob yields ABSOLUTE paths, so testing path.parts tested every ancestor
    # above the checkout: a clone under any directory named logs/, build/,
    # dist/, .venv/ or node_modules/ scanned ZERO files and printed clean.
    gate = _load()
    nested = tmp_path / "logs" / "repo"
    (nested / "docs").mkdir(parents=True)
    (nested / "docs" / "a.md").write_text("we ship 32 hooks\n", encoding="utf-8")
    (nested / "docs" / "b.md").write_text("also 32 hooks\n", encoding="utf-8")
    gate.REPO = nested
    assert len(gate._tree_files()) == 2
