"""Tests for configs/scripts/vouch_check.py — the trust decision behind
.github/workflows/vouch-gate.yml (Round-4 gap, Mitchell Hashimoto).

Extracted as a standalone, testable script rather than leaving the decision
buried in the workflow's inline actions/github-script JS with no coverage.

Standalone CLI-layer script with no orchestrator dependency — load it via
sys.path insertion (same pattern as test_equip.py), not the conftest
MagicMock-bypass pattern used for worker_*.py.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _REPO_ROOT / "configs" / "scripts"
_SCRIPT = _SCRIPTS_DIR / "vouch_check.py"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import vouch_check as vc  # noqa: E402


# ─── is_trusted (unit-level) ─────────────────────────────────────────────────

class TestIsTrusted:
    def test_owner_is_trusted_without_a_list(self, tmp_path):
        missing = tmp_path / "no-such-file.txt"
        trusted, reason = vc.is_trusted("anyone", "OWNER", str(missing))
        assert trusted is True
        assert "collaborator" in reason

    def test_member_and_collaborator_are_trusted(self, tmp_path):
        missing = tmp_path / "no-such-file.txt"
        assert vc.is_trusted("x", "MEMBER", str(missing))[0] is True
        assert vc.is_trusted("x", "COLLABORATOR", str(missing))[0] is True

    def test_vouched_non_collaborator_is_trusted(self, tmp_path):
        f = tmp_path / "trusted.txt"
        f.write_text("alice\nbob\n")
        trusted, reason = vc.is_trusted("alice", "NONE", str(f))
        assert trusted is True
        assert "vouched" in reason

    def test_unvouched_non_collaborator_is_untrusted(self, tmp_path):
        f = tmp_path / "trusted.txt"
        f.write_text("alice\nbob\n")
        trusted, reason = vc.is_trusted("mallory", "NONE", str(f))
        assert trusted is False
        assert "not vouched" in reason

    def test_first_time_contributor_association_is_untrusted_unless_vouched(self, tmp_path):
        f = tmp_path / "trusted.txt"
        f.write_text("alice\n")
        assert vc.is_trusted("mallory", "FIRST_TIME_CONTRIBUTOR", str(f))[0] is False
        assert vc.is_trusted("mallory", "CONTRIBUTOR", str(f))[0] is False

    def test_missing_trusted_file_fails_open(self, tmp_path):
        # A vanished/misconfigured trust list must never lock out every
        # contributor — fail open (skip the gate) rather than closing all.
        missing = tmp_path / "does-not-exist.txt"
        trusted, reason = vc.is_trusted("mallory", "NONE", str(missing))
        assert trusted is True
        assert "missing" in reason

    def test_comments_and_blank_lines_ignored_in_trusted_file(self, tmp_path):
        f = tmp_path / "trusted.txt"
        f.write_text("# a comment\n\nalice\n\n# another\nbob\n")
        assert vc.is_trusted("alice", "NONE", str(f))[0] is True
        assert vc.is_trusted("# a comment", "NONE", str(f))[0] is False

    def test_whitespace_in_trusted_file_is_stripped(self, tmp_path):
        f = tmp_path / "trusted.txt"
        f.write_text("  alice  \n\tbob\t\n")
        assert vc.is_trusted("alice", "NONE", str(f))[0] is True
        assert vc.is_trusted("bob", "NONE", str(f))[0] is True


# ─── CLI (subprocess, exit-code contract the workflow depends on) ───────────

class TestCli:
    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_SCRIPT), *args],
            capture_output=True, text=True,
        )

    def test_trusted_exits_zero(self, tmp_path):
        f = tmp_path / "trusted.txt"
        f.write_text("alice\n")
        proc = self._run("--author", "alice", "--association", "NONE", "--trusted-file", str(f))
        assert proc.returncode == 0
        assert "vouched" in proc.stdout

    def test_untrusted_exits_one(self, tmp_path):
        f = tmp_path / "trusted.txt"
        f.write_text("alice\n")
        proc = self._run("--author", "mallory", "--association", "NONE", "--trusted-file", str(f))
        assert proc.returncode == 1
        assert "not vouched" in proc.stdout

    def test_missing_required_arg_exits_nonzero(self):
        proc = self._run("--author", "alice")
        assert proc.returncode != 0
