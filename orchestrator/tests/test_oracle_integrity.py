"""Tests for oracle integrity: liveness (infra errors → 'unreviewed', never silent
approval), the chunked-path severity gate, criteria injection, and test-evidence
gating in verify_and_commit.

Loads the REAL worker_review.py / worker.py via importlib to bypass the conftest
MagicMock (same pattern as test_worker.py).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

# ─── Load real modules bypassing conftest mocks ───────────────────────────────

_WR_FILE = Path(__file__).parent.parent / "worker_review.py"
_wr_spec = importlib.util.spec_from_file_location("_real_worker_review", _WR_FILE)
wr = importlib.util.module_from_spec(_wr_spec)
_wr_spec.loader.exec_module(wr)  # type: ignore[union-attr]

_W_FILE = Path(__file__).parent.parent / "worker.py"
_w_spec = importlib.util.spec_from_file_location("_real_worker_oracle", _W_FILE)
wmod = importlib.util.module_from_spec(_w_spec)
_w_spec.loader.exec_module(wmod)  # type: ignore[union-attr]


# ─── Test doubles ─────────────────────────────────────────────────────────────


class FakeProc:
    """Stand-in for an asyncio subprocess."""

    def __init__(self, stdout: bytes = b""):
        self._stdout = stdout
        self.returncode = 0
        self.killed = False

    async def communicate(self):
        return self._stdout, b""

    def kill(self):
        self.killed = True


class AsyncioProxy:
    """Proxy for the asyncio module that lets tests override subprocess entry points
    without mutating the global asyncio module."""

    def __init__(self, **overrides):
        self._overrides = overrides

    def __getattr__(self, name):
        if name in self._overrides:
            return self._overrides[name]
        return getattr(asyncio, name)


def _shell_returning(proc: FakeProc):
    async def _fake_shell(*args, **kwargs):
        return proc
    return _fake_shell


def _shell_raising(exc: Exception):
    async def _fake_shell(*args, **kwargs):
        raise exc
    return _fake_shell


async def _timeout_wait_for(coro, timeout=None):
    coro.close()  # avoid "never awaited" warning
    raise asyncio.TimeoutError


# ─── _oracle_pass liveness ────────────────────────────────────────────────────


class TestOraclePassLiveness:
    async def test_timeout_is_infra_error(self, tmp_path, monkeypatch):
        proc = FakeProc()
        monkeypatch.setattr(
            wr, "asyncio",
            AsyncioProxy(create_subprocess_shell=_shell_returning(proc),
                         wait_for=_timeout_wait_for),
        )
        passed, conf, issues, infra = await wr._oracle_pass("prompt", tmp_path)
        assert infra is True
        assert "timeout" in issues
        assert proc.killed

    async def test_subprocess_exception_is_infra_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            wr, "asyncio",
            AsyncioProxy(create_subprocess_shell=_shell_raising(OSError("no claude"))),
        )
        passed, conf, issues, infra = await wr._oracle_pass("prompt", tmp_path)
        assert infra is True

    async def test_unparseable_output_is_infra_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            wr, "asyncio",
            AsyncioProxy(create_subprocess_shell=_shell_returning(
                FakeProc(b"Error: rate limited"))),
        )
        passed, conf, issues, infra = await wr._oracle_pass("prompt", tmp_path)
        assert infra is True
        assert "unparseable" in issues

    async def test_valid_approval_not_infra(self, tmp_path, monkeypatch):
        out = json.dumps({"pass": True, "confidence": "high", "issues": []}).encode()
        monkeypatch.setattr(
            wr, "asyncio",
            AsyncioProxy(create_subprocess_shell=_shell_returning(FakeProc(out))),
        )
        passed, conf, issues, infra = await wr._oracle_pass("prompt", tmp_path)
        assert (passed, conf, infra) == (True, "high", False)

    async def test_valid_rejection_not_infra(self, tmp_path, monkeypatch):
        out = json.dumps(
            {"pass": False, "confidence": "high", "issues": ["missing null check"]}
        ).encode()
        monkeypatch.setattr(
            wr, "asyncio",
            AsyncioProxy(create_subprocess_shell=_shell_returning(FakeProc(out))),
        )
        passed, conf, issues, infra = await wr._oracle_pass("prompt", tmp_path)
        assert passed is False
        assert infra is False
        assert "missing null check" in issues


# ─── _oracle_review_chunk liveness ───────────────────────────────────────────


class TestOracleChunkLiveness:
    async def test_timeout_is_infra_not_rejection(self, tmp_path, monkeypatch):
        proc = FakeProc()
        monkeypatch.setattr(
            wr, "asyncio",
            AsyncioProxy(create_subprocess_shell=_shell_returning(proc),
                         wait_for=_timeout_wait_for),
        )
        approved, reason, infra = await wr._oracle_review_chunk("task", "diff", "1/1", tmp_path)
        assert infra is True
        assert "timeout" in reason

    async def test_legacy_text_approved(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            wr, "asyncio",
            AsyncioProxy(create_subprocess_shell=_shell_returning(
                FakeProc(b"APPROVED: looks good"))),
        )
        approved, reason, infra = await wr._oracle_review_chunk("task", "diff", "", tmp_path)
        assert (approved, infra) == (True, False)

    async def test_legacy_text_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            wr, "asyncio",
            AsyncioProxy(create_subprocess_shell=_shell_returning(
                FakeProc(b"REJECTED: wrong file"))),
        )
        approved, reason, infra = await wr._oracle_review_chunk("task", "diff", "", tmp_path)
        assert (approved, infra) == (False, False)
        assert "wrong file" in reason

    async def test_garbage_output_is_infra(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            wr, "asyncio",
            AsyncioProxy(create_subprocess_shell=_shell_returning(
                FakeProc(b"503 Service Unavailable"))),
        )
        approved, reason, infra = await wr._oracle_review_chunk("task", "diff", "", tmp_path)
        assert infra is True


# ─── _oracle_review aggregation ──────────────────────────────────────────────


class TestOracleReviewAggregation:
    async def test_chunked_rejection_wins_over_infra(self, tmp_path, monkeypatch):
        results = iter([
            (True, "oracle timeout (60s)", True),
            (False, "[high] Oracle rejected.", False),
            (True, "approved", False),
        ])

        async def fake_chunk(task, chunk, label, cdir):
            return next(results)

        monkeypatch.setattr(wr, "_oracle_review_chunk", fake_chunk)
        approved, reason, infra = await wr._oracle_review("task", "x" * 9000, tmp_path)
        assert (approved, infra) == (False, False)
        assert "rejected" in reason.lower()

    async def test_chunked_infra_only_is_unreviewed(self, tmp_path, monkeypatch):
        async def fake_chunk(task, chunk, label, cdir):
            return True, "oracle timeout (60s)", True

        monkeypatch.setattr(wr, "_oracle_review_chunk", fake_chunk)
        approved, reason, infra = await wr._oracle_review("task", "x" * 9000, tmp_path)
        assert infra is True
        assert "infra" in reason

    async def test_chunked_all_approved(self, tmp_path, monkeypatch):
        async def fake_chunk(task, chunk, label, cdir):
            return True, "approved", False

        monkeypatch.setattr(wr, "_oracle_review_chunk", fake_chunk)
        approved, reason, infra = await wr._oracle_review("task", "x" * 9000, tmp_path)
        assert (approved, infra) == (True, False)

    async def test_two_pass_spec_infra_is_unreviewed(self, tmp_path, monkeypatch):
        async def fake_pass(prompt, cdir):
            return True, "none", "oracle timeout (45s)", True

        monkeypatch.setattr(wr, "_oracle_pass", fake_pass)
        approved, reason, infra = await wr._oracle_review("task", "small diff", tmp_path)
        assert infra is True
        assert "spec pass" in reason

    async def test_two_pass_quality_infra_is_unreviewed(self, tmp_path, monkeypatch):
        calls = []

        async def fake_pass(prompt, cdir):
            calls.append(prompt)
            if len(calls) == 1:
                return True, "high", "", False
            return True, "none", "oracle subprocess error", True

        monkeypatch.setattr(wr, "_oracle_pass", fake_pass)
        approved, reason, infra = await wr._oracle_review("task", "small diff", tmp_path)
        assert infra is True
        assert "quality pass" in reason

    async def test_two_pass_real_rejection_not_infra(self, tmp_path, monkeypatch):
        async def fake_pass(prompt, cdir):
            return False, "high", "spec violation", False

        monkeypatch.setattr(wr, "_oracle_pass", fake_pass)
        approved, reason, infra = await wr._oracle_review("task", "small diff", tmp_path)
        assert (approved, infra) == (False, False)

    async def test_two_pass_both_pass_approved(self, tmp_path, monkeypatch):
        async def fake_pass(prompt, cdir):
            return True, "high", "", False

        monkeypatch.setattr(wr, "_oracle_pass", fake_pass)
        approved, reason, infra = await wr._oracle_review("task", "small diff", tmp_path)
        assert (approved, infra) == (True, False)


# ─── Infra-error streak + escalation ─────────────────────────────────────────


class TestOracleInfraStreak:
    def setup_method(self):
        wr._oracle_infra_streaks.clear()

    def test_record_increments(self, tmp_path):
        assert wr._record_oracle_infra_error(tmp_path) == 1
        assert wr._record_oracle_infra_error(tmp_path) == 2
        assert wr._record_oracle_infra_error(tmp_path) == 3

    def test_reset_clears(self, tmp_path):
        wr._record_oracle_infra_error(tmp_path)
        wr._record_oracle_infra_error(tmp_path)
        wr._reset_oracle_infra_streak(tmp_path)
        assert wr._record_oracle_infra_error(tmp_path) == 1

    def test_streaks_are_per_session(self, tmp_path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        wr._record_oracle_infra_error(a)
        assert wr._record_oracle_infra_error(b) == 1

    def test_reset_unknown_session_is_noop(self, tmp_path):
        wr._reset_oracle_infra_streak(tmp_path)  # must not raise

    async def test_escalate_writes_blockers(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        await wr._escalate_oracle_outage(tmp_path, claude_dir, "", 3)
        content = (claude_dir / "blockers.md").read_text()
        assert "## Blocker" in content
        assert "3 consecutive infra errors" in content
        assert "unreviewed" in content

    async def test_escalate_appends_to_existing_blockers(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "blockers.md").write_text("## Blocker [old]\nprevious entry\n")
        await wr._escalate_oracle_outage(tmp_path, claude_dir, "", 6)
        content = (claude_dir / "blockers.md").read_text()
        assert "previous entry" in content
        assert "6 consecutive infra errors" in content

    async def test_escalate_fires_webhook(self, tmp_path, monkeypatch):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        captured: list[tuple] = []

        async def fake_exec(*args, **kwargs):
            captured.append(args)
            return FakeProc()

        monkeypatch.setattr(
            wr, "asyncio", AsyncioProxy(create_subprocess_exec=fake_exec)
        )
        await wr._escalate_oracle_outage(tmp_path, claude_dir, "http://hook.example/x", 3)
        assert len(captured) == 1
        args = captured[0]
        assert args[0] == "curl"
        assert "http://hook.example/x" in args
        payload = json.loads(args[args.index("-d") + 1])
        assert payload["event"] == "oracle_outage"
        assert payload["consecutive_infra_errors"] == 3

    async def test_escalate_no_webhook_no_curl(self, tmp_path, monkeypatch):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        async def fake_exec(*args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("curl must not be called when webhook is empty")

        monkeypatch.setattr(
            wr, "asyncio", AsyncioProxy(create_subprocess_exec=fake_exec)
        )
        await wr._escalate_oracle_outage(tmp_path, claude_dir, "", 3)


# ─── Worker._run_oracle_gate ─────────────────────────────────────────────────


def _init_git_repo(repo: Path, commits: int = 2) -> None:
    """Create a git repo with N commits for gate tests."""
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for i in range(commits):
        (repo / f"file{i}.txt").write_text(f"content {i}\n")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(repo),
             "-c", "user.email=test@test", "-c", "user.name=Test",
             "commit", "-q", "-m", f"commit {i}"],
            check=True,
        )


def _commit_count(repo: Path) -> int:
    out = subprocess.run(
        ["git", "-C", str(repo), "rev-list", "--count", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return int(out.stdout.strip())


@pytest.fixture
def gate_worker(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    claude_dir = repo / ".claude"
    claude_dir.mkdir()
    w = wmod.Worker(
        task_id="task-gate1",
        description="fix: the login bug",
        model="haiku",
        project_dir=repo,
        claude_dir=claude_dir,
    )
    w.auto_committed = True
    return w


class TestRunOracleGate:
    async def test_gate_disabled_returns_true(self, gate_worker, monkeypatch):
        monkeypatch.setitem(wmod.GLOBAL_SETTINGS, "auto_oracle", False)
        assert await gate_worker._run_oracle_gate() is True
        assert gate_worker.oracle_result is None

    async def test_infra_error_tags_unreviewed_not_approved(self, gate_worker, monkeypatch):
        monkeypatch.setitem(wmod.GLOBAL_SETTINGS, "auto_oracle", True)

        async def fake_review(desc, diff, cdir):
            return True, "oracle timeout (45s)", True

        monkeypatch.setattr(wmod, "_oracle_review", fake_review)
        monkeypatch.setattr(wmod, "_record_oracle_infra_error", lambda d: 1)
        monkeypatch.setattr(wmod, "_ORACLE_INFRA_THRESHOLD", 3)

        assert await gate_worker._run_oracle_gate() is True  # fail-open
        assert gate_worker.oracle_result == "unreviewed"
        assert "timeout" in gate_worker.oracle_reason
        assert gate_worker.auto_committed is True  # commit survives

    async def test_infra_streak_escalates_at_threshold(self, gate_worker, monkeypatch):
        monkeypatch.setitem(wmod.GLOBAL_SETTINGS, "auto_oracle", True)
        monkeypatch.setitem(wmod.GLOBAL_SETTINGS, "notification_webhook", "http://h/x")
        escalations: list[tuple] = []

        async def fake_review(desc, diff, cdir):
            return True, "oracle subprocess error", True

        async def fake_escalate(project_dir, claude_dir, webhook, streak):
            escalations.append((webhook, streak))

        monkeypatch.setattr(wmod, "_oracle_review", fake_review)
        monkeypatch.setattr(wmod, "_record_oracle_infra_error", lambda d: 3)
        monkeypatch.setattr(wmod, "_ORACLE_INFRA_THRESHOLD", 3)
        monkeypatch.setattr(wmod, "_escalate_oracle_outage", fake_escalate)

        assert await gate_worker._run_oracle_gate() is True
        assert escalations == [("http://h/x", 3)]

    async def test_infra_below_threshold_no_escalation(self, gate_worker, monkeypatch):
        monkeypatch.setitem(wmod.GLOBAL_SETTINGS, "auto_oracle", True)
        escalations: list[int] = []

        async def fake_review(desc, diff, cdir):
            return True, "oracle subprocess error", True

        async def fake_escalate(*args):
            escalations.append(1)

        monkeypatch.setattr(wmod, "_oracle_review", fake_review)
        monkeypatch.setattr(wmod, "_record_oracle_infra_error", lambda d: 2)
        monkeypatch.setattr(wmod, "_ORACLE_INFRA_THRESHOLD", 3)
        monkeypatch.setattr(wmod, "_escalate_oracle_outage", fake_escalate)

        assert await gate_worker._run_oracle_gate() is True
        assert escalations == []

    async def test_rejection_undoes_commit_and_flags_requeue(self, gate_worker, monkeypatch):
        monkeypatch.setitem(wmod.GLOBAL_SETTINGS, "auto_oracle", True)

        async def fake_review(desc, diff, cdir):
            return False, "[high] Oracle rejected.", False

        monkeypatch.setattr(wmod, "_oracle_review", fake_review)
        monkeypatch.setattr(wmod, "_reset_oracle_infra_streak", lambda d: None)

        assert _commit_count(gate_worker._project_dir) == 2
        assert await gate_worker._run_oracle_gate() is False
        assert gate_worker.oracle_result == "rejected"
        assert gate_worker.auto_committed is False
        assert gate_worker._oracle_requeue is True
        assert gate_worker._oracle_requeue_reason == "[high] Oracle rejected."
        assert _commit_count(gate_worker._project_dir) == 1  # commit undone

    async def test_approval_resets_streak(self, gate_worker, monkeypatch):
        monkeypatch.setitem(wmod.GLOBAL_SETTINGS, "auto_oracle", True)
        resets: list[Path] = []

        async def fake_review(desc, diff, cdir):
            return True, "approved (spec+quality passed)", False

        monkeypatch.setattr(wmod, "_oracle_review", fake_review)
        monkeypatch.setattr(wmod, "_reset_oracle_infra_streak", resets.append)

        assert await gate_worker._run_oracle_gate() is True
        assert gate_worker.oracle_result == "approved"
        assert len(resets) == 1
