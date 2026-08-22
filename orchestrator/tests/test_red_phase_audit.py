"""The red-phase audit must be able to go red, and to stay quiet.

`configs/scripts/red-phase-audit.py` runs the tests a commit ADDS against that
commit's parent. One that already passes did not need the change — the retroactive
form of the TDD red phase, and the additive half of the hole
`judge_diversity.test_integrity` is blind to (115 of the last 133 test-carrying
commits in this repo were purely additive).

The first version of this tool reported a clean 0% fire rate across every commit
it examined. The rate was an artifact: it passed `--timeout` to a pytest without
`pytest-timeout`, so every run exited with a usage error and reported zero passes.
Nothing in the output looked wrong. A positive control caught it, and that control
is now these tests — a measuring instrument that cannot go red measures nothing,
which is the exact defect the instrument exists to find.
"""

from __future__ import annotations

import os
import subprocess
import sys
import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "configs" / "scripts" / "red-phase-audit.py"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=str(repo), check=True,
        capture_output=True, text=True,
    )


@pytest.fixture
def audit(monkeypatch, tmp_path):
    """Load the script against a throwaway repo, flat layout, this interpreter."""
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    _git(repo.parent, "init", "-q", str(repo))
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "tests" / "test_base.py").write_text("def test_base():\n    assert True\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")

    monkeypatch.setenv("RED_PHASE_REPO", str(repo))
    monkeypatch.setenv("RED_PHASE_PYTHON", sys.executable)
    monkeypatch.setenv("RED_PHASE_SUBDIR", "")
    # spec/exec rather than load_module(), which is deprecated and removed in 3.15.
    spec = importlib.util.spec_from_file_location("red_phase_audit", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, repo


def _commit_test(repo: Path, name: str, body: str) -> str:
    (repo / "tests" / f"{name}.py").write_text(body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"test: {name}")
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo),
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def test_fires_on_a_test_that_passes_without_the_change(audit, tmp_path):
    # THE positive control. A test asserting a tautology needs nothing from the
    # commit that introduced it, so it passes at base and must be reported.
    mod, repo = audit
    sha = _commit_test(repo, "test_vacuous", "def test_vacuous():\n    assert True\n")
    passed, total, note = mod.run_at_base(sha, mod.added_tests(sha), tmp_path / "wt")
    assert total == 1, f"node id not built: {note}"
    assert passed == 1, f"the audit cannot detect a vacuous added test (note={note})"


def test_stays_quiet_when_the_test_needs_the_change(audit, tmp_path):
    # The other direction, which matters just as much: a test exercising code the
    # commit introduces cannot pass at base, and must not be reported.
    mod, repo = audit
    (repo / "feature.py").write_text("def added_later():\n    return 42\n")
    sha = _commit_test(
        repo, "test_real",
        "from feature import added_later\n\n\ndef test_real():\n    assert added_later() == 42\n",
    )
    passed, total, note = mod.run_at_base(sha, mod.added_tests(sha), tmp_path / "wt")
    assert passed == 0, f"reported a test that genuinely needed the change (note={note})"


def test_a_pytest_that_cannot_run_is_not_reported_as_a_clean_result(audit, tmp_path, monkeypatch):
    # The original bug, pinned. An unusable run must surface as a skip with a
    # reason, never as "0 added tests already pass" — those are indistinguishable
    # in the summary and one of them is a lie.
    mod, repo = audit
    sha = _commit_test(repo, "test_x", "def test_x():\n    assert True\n")

    real_run = subprocess.run

    def broken(cmd, **kw):
        if isinstance(cmd, list) and "pytest" in cmd:
            cmd = list(cmd) + ["--flag-that-does-not-exist"]
        return real_run(cmd, **kw)

    monkeypatch.setattr(mod.subprocess, "run", broken)
    passed, total, note = mod.run_at_base(sha, mod.added_tests(sha), tmp_path / "wt")
    assert total == 0, "an unrunnable pytest was counted as a real measurement"
    assert passed == 0
    assert "usage error" in note or "no result line" in note


def test_added_tests_reads_only_added_functions_in_test_files(audit):
    mod, repo = audit
    (repo / "app.py").write_text("def test_not_a_test_file():\n    pass\n")
    sha = _commit_test(repo, "test_mixed", "def test_added():\n    assert True\n")
    found = mod.added_tests(sha)
    names = [n for names in found.values() for n in names]
    assert names == ["test_added"]
    assert not any("app.py" in p for p in found), "non-test file treated as a test file"
