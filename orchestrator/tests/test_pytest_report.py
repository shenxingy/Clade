"""Tests for pytest_report — the shared reader for pytest subprocess output.

These exist because CI could not have caught the bug they cover. GitHub Actions
sets no colour variable, so pytest ran uncoloured there and every parse
succeeded; on a developer machine under an agent harness (Claude Code exports
``FORCE_COLOR=3``) the identical code parsed nothing and the resolve-rate eval
reported a clean 0%. So the environment is set *explicitly* here rather than
inherited — a test that only passes because the runner happens to be colourless
is the same blind gate wearing a different hat.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pytest_report import (  # noqa: E402
    color_free_env,
    force_verbose,
    parse_results,
    strip_ansi,
)

ORCH_DIR = Path(__file__).resolve().parent.parent


# ─── ANSI tolerance ───────────────────────────────────────────────────────────

class TestAnsiTolerance:
    COLOURED = (
        "tests/test_calc.py::test_add \x1b[32mPASSED\x1b[0m\x1b[32m   [ 50%]\x1b[0m\n"
        "tests/test_calc.py::test_sub \x1b[31mFAILED\x1b[0m\x1b[31m   [100%]\x1b[0m\n"
    )

    def test_parses_coloured_output(self):
        results = parse_results(self.COLOURED)
        assert results == {
            "tests/test_calc.py::test_add": True,
            "tests/test_calc.py::test_sub": False,
        }

    def test_plain_output_still_parses(self):
        plain = strip_ansi(self.COLOURED)
        assert "\x1b" not in plain
        assert parse_results(plain) == parse_results(self.COLOURED)

    def test_osc8_hyperlinks_are_stripped(self):
        # Some terminal plugins wrap the path in an OSC-8 hyperlink.
        line = "\x1b]8;;file:///x\x07tests/t.py::test_a\x1b]8;;\x07 PASSED\n"
        assert parse_results(line) == {"tests/t.py::test_a": True}

    def test_parametrized_ids_survive(self):
        out = "tests/t.py::test_x[a-1] \x1b[32mPASSED\x1b[0m\n"
        assert parse_results(out) == {"tests/t.py::test_x[a-1]": True}

    def test_summary_lines_are_not_results(self):
        assert parse_results("=== 2 passed in 0.5s ===\nplatform linux\n") == {}


# ─── Verbosity arithmetic ─────────────────────────────────────────────────────

class TestForceVerbose:
    def test_strips_quiet_that_would_cancel_verbose(self):
        # pytest verbosity is count(-v) - count(-q): this command printed dots.
        assert force_verbose("pytest tests/ -v --tb=no -q") == "pytest tests/ -v --tb=no"

    def test_adds_verbose_when_absent(self):
        assert "-v" in force_verbose("pytest tests/")

    def test_strips_no_header_and_quiet_together(self):
        out = force_verbose("python -m pytest -p no:cacheprovider --no-header -q")
        assert "-q" not in out and "--no-header" not in out and " -v" in out

    def test_leaves_non_pytest_commands_alone(self):
        assert force_verbose("go test ./... -q") == "go test ./... -q"

    def test_does_not_strip_flags_that_merely_start_with_q(self):
        assert "--quiet-ish" in force_verbose("pytest --quiet-ish tests/")


# ─── Environment ──────────────────────────────────────────────────────────────

class TestColorFreeEnv:
    def test_removes_force_color_rather_than_zeroing_it(self):
        # pytest treats FORCE_COLOR as truthy when merely present, so
        # FORCE_COLOR=0 still colours. It has to be absent.
        env = color_free_env({"FORCE_COLOR": "3", "PATH": "/bin"})
        assert "FORCE_COLOR" not in env

    def test_sets_the_variables_pytest_and_friends_read(self):
        env = color_free_env({})
        assert env["PY_COLORS"] == "0"
        assert env["NO_COLOR"] == "1"

    def test_preserves_the_rest_of_the_environment(self):
        env = color_free_env({"PATH": "/bin", "VIRTUAL_ENV": "/x/.venv"})
        assert env["PATH"] == "/bin" and env["VIRTUAL_ENV"] == "/x/.venv"

    def test_defaults_to_the_live_environment(self):
        assert "PATH" in color_free_env()


# ─── End-to-end: a real pytest subprocess under forced colour ────────────────

class TestAgainstRealPytest:
    """The contract that matters: a suite run through color_free_env parses,
    and the same suite run with colour forced on does not — which is exactly
    what every caller used to do."""

    @pytest.fixture
    def repo(self, tmp_path: Path) -> Path:
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_s.py").write_text(
            "def test_ok():\n    assert True\n"
        )
        return tmp_path

    def _run(self, repo: Path, env: dict) -> str:
        # `sys.executable -m pytest`, not a bare `pytest`: the bare name only
        # resolves when the venv's bin is on PATH, which it is not when the
        # suite is run as `.venv/bin/python -m pytest` — the normal way to run
        # it here. That made these two assertions fail on every local run while
        # CI stayed green, and a test that is red for everyone locally is a
        # test everyone learns to ignore. force_verbose rewrites the first
        # "pytest" token it finds, which is the one after -m.
        proc = subprocess.run(
            force_verbose(f"{shlex.quote(sys.executable)} -m pytest tests/ -p no:cacheprovider -q"),
            cwd=str(repo), shell=True, capture_output=True, text=True,
            timeout=120, env=env,
        )
        return proc.stdout + proc.stderr

    def test_color_free_env_yields_parseable_results(self, repo: Path):
        out = self._run(repo, color_free_env({**os.environ, "FORCE_COLOR": "3"}))
        assert parse_results(out) == {"tests/test_s.py::test_ok": True}

    def test_parser_survives_colour_even_if_env_leaks(self, repo: Path):
        # Defence in depth: if some caller forgets color_free_env, the parser
        # must still cope rather than silently returning {}.
        out = self._run(repo, {**os.environ, "FORCE_COLOR": "3"})
        assert parse_results(out) == {"tests/test_s.py::test_ok": True}


# ─── Regression: the resolve eval under a forced-colour environment ──────────

def test_resolve_eval_dry_run_is_colour_proof():
    """The original failure, reproduced end to end: the harness inherits
    FORCE_COLOR, pytest colourizes, and before the fix every instance scored
    UNRESOLVED with a straight-faced 0% resolve rate."""
    proc = subprocess.run(
        [sys.executable, str(ORCH_DIR / "evals" / "run_resolve_eval.py"), "--dry-run"],
        capture_output=True, text=True, timeout=180,
        env={**os.environ, "FORCE_COLOR": "3"},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "RESOLVED" in proc.stdout, proc.stdout
    assert "UNMEASURED" not in proc.stdout, proc.stdout
    # Pinned on the property, not on a ratio: the bug reported a real-looking
    # 0% for every instance, so what matters is that some instance resolved and
    # the rate is non-zero. Asserting an exact fraction only meant the test
    # broke the next time someone added a case, which is behaviour to encourage.
    rate_line = next(l for l in proc.stdout.splitlines() if l.startswith("resolve-rate:"))
    resolved, _, total = rate_line.split()[1].partition("/")
    assert int(resolved) > 0, rate_line
    assert int(total) >= 2, rate_line
