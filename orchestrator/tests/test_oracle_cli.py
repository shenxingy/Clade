"""oracle_cli — the strangler-extracted CLI gate must map verdicts to exit
codes exactly (0 approved/empty, 1 rejected, 2 unreviewed) and never let an
infra error read as approval. Mocks _oracle_review; no claude calls.
"""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

import oracle_cli

# oracle_cli's `_resolve_oracle_plan` (dry-run preview) reads real constants/
# functions off the `worker_review` module (_ORACLE_CHUNK_SIZE, _classify_diff_risk)
# — conftest.py replaces sys.modules['worker_review'] with a MagicMock for other
# test files' safety, so those attributes would otherwise be MagicMocks, not the
# real int/function. Load the real module under a private name (bypasses the
# conftest mock, same pattern as test_oracle_integrity.py / test_worker.py) and
# monkeypatch just those attributes onto the mocked module for TestDryRun.
_WR_FILE = Path(__file__).parent.parent / "worker_review.py"
_wr_spec = importlib.util.spec_from_file_location("_real_worker_review_oracle_cli", _WR_FILE)
_real_wr = importlib.util.module_from_spec(_wr_spec)
_wr_spec.loader.exec_module(_real_wr)  # type: ignore[union-attr]


def _stub_review(approved, reason, infra):
    async def stub(task, diff, claude_dir, acceptance_criteria=None, test_evidence="",
                   constitution=""):
        return approved, reason, infra
    return stub


@pytest.fixture
def diff_file(tmp_path):
    f = tmp_path / "change.diff"
    f.write_text("--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n")
    return str(f)


class TestExitCodes:
    def test_approved_exits_0(self, monkeypatch, tmp_path, diff_file, capsys):
        monkeypatch.setattr(oracle_cli, "_oracle_review", _stub_review(True, "ok", False))
        rc = oracle_cli.run(["--task", "t", "--diff-file", diff_file,
                             "--project-dir", str(tmp_path)])
        assert rc == 0
        assert json.loads(capsys.readouterr().out)["verdict"] == "approved"

    def test_rejected_exits_1(self, monkeypatch, tmp_path, diff_file, capsys):
        monkeypatch.setattr(oracle_cli, "_oracle_review",
                            _stub_review(False, "spec violated", False))
        rc = oracle_cli.run(["--task", "t", "--diff-file", diff_file,
                             "--project-dir", str(tmp_path)])
        assert rc == 1
        out = json.loads(capsys.readouterr().out)
        assert out["verdict"] == "rejected"
        assert "spec violated" in out["reason"]

    def test_infra_error_exits_2_never_approved(self, monkeypatch, tmp_path,
                                                diff_file, capsys):
        # _oracle_review fail-open returns approved=True on infra error; the
        # CLI must surface 'unreviewed', not 'approved' (lovesegfault).
        monkeypatch.setattr(oracle_cli, "_oracle_review",
                            _stub_review(True, "timeout", True))
        rc = oracle_cli.run(["--task", "t", "--diff-file", diff_file,
                             "--project-dir", str(tmp_path)])
        assert rc == 2
        assert json.loads(capsys.readouterr().out)["verdict"] == "unreviewed"

    def test_empty_diff_exits_0_without_review(self, monkeypatch, tmp_path, capsys):
        empty = tmp_path / "empty.diff"
        empty.write_text("")

        async def boom(*a, **k):  # must not be called for an empty diff
            raise AssertionError("review ran on empty diff")

        monkeypatch.setattr(oracle_cli, "_oracle_review", boom)
        rc = oracle_cli.run(["--task", "t", "--diff-file", str(empty),
                             "--project-dir", str(tmp_path)])
        assert rc == 0
        assert json.loads(capsys.readouterr().out)["verdict"] == "empty"


class TestInputs:
    def test_task_required(self, tmp_path, diff_file):
        with pytest.raises(SystemExit):
            oracle_cli.run(["--diff-file", diff_file, "--project-dir", str(tmp_path)])

    def test_staged_git_diff(self, monkeypatch, tmp_path, capsys):
        # First run / fresh repo: staged change is picked up via git diff --cached.
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        (tmp_path / "a.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "a.py"], cwd=tmp_path, check=True)
        monkeypatch.setattr(oracle_cli, "_oracle_review", _stub_review(True, "ok", False))
        rc = oracle_cli.run(["--task", "t", "--staged", "--project-dir", str(tmp_path)])
        assert rc == 0
        assert json.loads(capsys.readouterr().out)["verdict"] == "approved"

    def test_creates_claude_dir(self, monkeypatch, tmp_path, diff_file):
        monkeypatch.setattr(oracle_cli, "_oracle_review", _stub_review(True, "ok", False))
        oracle_cli.run(["--task", "t", "--diff-file", diff_file,
                        "--project-dir", str(tmp_path)])
        assert (tmp_path / ".claude").is_dir()

    def test_model_override_sets_module_global(self, monkeypatch, tmp_path, diff_file):
        import worker_review
        monkeypatch.setattr(oracle_cli, "_oracle_review", _stub_review(True, "ok", False))
        monkeypatch.setattr(worker_review, "HAIKU_MODEL", "haiku")
        oracle_cli.run(["--task", "t", "--diff-file", diff_file,
                        "--project-dir", str(tmp_path), "--model", "sonnet"])
        assert worker_review.HAIKU_MODEL == "sonnet"


class TestDryRun:
    """--dry-run must print the resolved plan and never touch _oracle_review
    (no subprocess, no API call) or the filesystem (.claude/ untouched)."""

    @pytest.fixture(autouse=True)
    def _real_oracle_constants(self, monkeypatch):
        # Give the (conftest-mocked) worker_review module the REAL chunking/
        # risk-classifier behavior so a wrong _resolve_oracle_plan implementation
        # (off-by-one chunk math, missing risk bump, etc.) actually fails these
        # tests instead of passing by MagicMock coincidence.
        import worker_review
        monkeypatch.setattr(worker_review, "_ORACLE_CHUNK_SIZE", _real_wr._ORACLE_CHUNK_SIZE)
        monkeypatch.setattr(worker_review, "_classify_diff_risk", _real_wr._classify_diff_risk)
        monkeypatch.setattr(worker_review, "HAIKU_MODEL", "haiku")

    def test_dry_run_never_calls_oracle_review(self, monkeypatch, tmp_path, diff_file, capsys):
        async def boom(*a, **k):
            raise AssertionError("oracle review ran despite --dry-run")

        monkeypatch.setattr(oracle_cli, "_oracle_review", boom)
        rc = oracle_cli.run(["--task", "t", "--diff-file", diff_file,
                             "--project-dir", str(tmp_path), "--dry-run"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["verdict"] == "dry-run"

    def test_dry_run_does_not_create_claude_dir(self, monkeypatch, tmp_path, diff_file):
        # Real code path (not stubbed with a fake _oracle_review) — dry-run
        # must short-circuit before the claude_dir.mkdir call, unlike the
        # real/empty-diff paths which always create it.
        oracle_cli.run(["--task", "t", "--diff-file", diff_file,
                        "--project-dir", str(tmp_path), "--dry-run"])
        assert not (tmp_path / ".claude").exists()

    def test_dry_run_reports_model_and_diff_size(self, monkeypatch, tmp_path, diff_file, capsys):
        import worker_review
        monkeypatch.setattr(worker_review, "HAIKU_MODEL", "haiku")
        rc = oracle_cli.run(["--task", "t", "--diff-file", diff_file,
                             "--project-dir", str(tmp_path), "--dry-run", "--model", "opus"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["model"] == "opus"
        assert out["diff_chars"] == len(Path(diff_file).read_text())
        assert out["criteria_count"] == 0

    def test_dry_run_reports_two_pass_for_small_diff(self, tmp_path, diff_file, capsys):
        rc = oracle_cli.run(["--task", "t", "--diff-file", diff_file,
                             "--project-dir", str(tmp_path), "--dry-run"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert "two-pass" in out["strategy"]
        assert out["verdict_samples"] == 1
        assert out["risk_flagged"] is False

    def test_dry_run_reports_chunked_strategy_for_large_diff(self, tmp_path, capsys):
        import worker_review
        big = tmp_path / "big.diff"
        chunk_size = worker_review._ORACLE_CHUNK_SIZE
        # Just over one chunk's worth — triggers the chunked path (2 total
        # chunks; both reviewed since 2 <= the chunks[:3] review cap).
        big.write_text("+" * (chunk_size + 500))
        rc = oracle_cli.run(["--task", "t", "--diff-file", str(big),
                             "--project-dir", str(tmp_path), "--dry-run"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert "chunked" in out["strategy"]
        assert "2/2" in out["strategy"]
        assert out["diff_chars"] == len(big.read_text())

    def test_dry_run_flags_risk_and_bumps_verdict_samples(self, tmp_path, capsys):
        # _classify_diff_risk matches security-sensitive paths/keywords — a
        # risky diff must be flagged AND get the same >=3 resample bump the
        # real _oracle_review applies, so the preview never understates cost.
        risky = tmp_path / "risky.diff"
        risky.write_text("--- a/auth.py\n+++ b/auth.py\n@@ -1 +1 @@\n-old\n+password = 'x'\n")
        rc = oracle_cli.run(["--task", "t", "--diff-file", str(risky),
                             "--project-dir", str(tmp_path), "--dry-run"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["risk_flagged"] is True
        assert out["verdict_samples"] == 3

    def test_dry_run_works_on_empty_diff_without_review(self, monkeypatch, tmp_path, capsys):
        empty = tmp_path / "empty.diff"
        empty.write_text("")

        async def boom(*a, **k):
            raise AssertionError("review ran on empty diff under --dry-run")

        monkeypatch.setattr(oracle_cli, "_oracle_review", boom)
        rc = oracle_cli.run(["--task", "t", "--diff-file", str(empty),
                             "--project-dir", str(tmp_path), "--dry-run"])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["verdict"] == "dry-run"
        assert out["diff_chars"] == 0
