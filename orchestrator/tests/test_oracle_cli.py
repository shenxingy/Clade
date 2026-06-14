"""oracle_cli — the strangler-extracted CLI gate must map verdicts to exit
codes exactly (0 approved/empty, 1 rejected, 2 unreviewed) and never let an
infra error read as approval. Mocks _oracle_review; no claude calls.
"""

import json
import subprocess

import pytest

import oracle_cli


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
