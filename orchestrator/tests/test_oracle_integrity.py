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

    async def test_fenced_json_is_parsed_not_infra(self, tmp_path, monkeypatch):
        """Haiku fences its JSON despite 'no markdown' — caught live 2026-06-12.

        A fenced verdict must parse as a real review, never an infra error
        (before the fix, a healthy oracle was 100% 'unreviewed' in production).
        """
        payload = json.dumps({"pass": False, "confidence": "high", "issues": ["bad guard"]})
        out = f"```json\n{payload}\n```".encode()
        monkeypatch.setattr(
            wr, "asyncio",
            AsyncioProxy(create_subprocess_shell=_shell_returning(FakeProc(out))),
        )
        passed, conf, issues, infra = await wr._oracle_pass("prompt", tmp_path)
        assert (passed, infra) == (False, False)
        assert "bad guard" in issues


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

    async def test_fenced_chunk_json_is_parsed_not_infra(self, tmp_path, monkeypatch):
        """The chunked path must also unwrap fenced verdicts (live 2026-06-12)."""
        payload = json.dumps({
            "decision": "REJECTED", "confidence": "high",
            "findings": [{"dimension": "correctness", "severity": "error",
                          "fix_suggestion": "guard the index at api.py:10"}],
            "fix_guidance": "fix the bounds check",
        })
        out = f"```json\n{payload}\n```".encode()
        monkeypatch.setattr(
            wr, "asyncio",
            AsyncioProxy(create_subprocess_shell=_shell_returning(FakeProc(out))),
        )
        approved, reason, infra = await wr._oracle_review_chunk("task", "diff", "", tmp_path)
        assert (approved, infra) == (False, False)
        assert "Oracle rejected" in reason

    async def test_grader_cwd_confined_to_scratch_dir(self, tmp_path, monkeypatch):
        """Agentic-grader containment (live eval 2026-06-12: graders wrote to
        the repo, committed, and pushed). Both grader entry points must pin
        the subprocess cwd to the .claude scratch dir."""
        out = json.dumps({"pass": True, "confidence": "high", "issues": []}).encode()
        captured: dict = {}

        async def _capturing_shell(cmd, **kwargs):
            captured.update(kwargs, cmd=cmd)
            return FakeProc(out)

        monkeypatch.setattr(
            wr, "asyncio", AsyncioProxy(create_subprocess_shell=_capturing_shell)
        )
        await wr._oracle_pass("prompt", tmp_path)
        assert captured.get("cwd") == str(tmp_path)
        assert "--dangerously-skip-permissions" not in captured["cmd"]
        assert "--append-system-prompt" in captured["cmd"]
        assert "code-review oracle" in captured["cmd"]
        assert '--setting-sources ""' in captured["cmd"]

        captured.clear()
        chunk_out = json.dumps({"decision": "APPROVED", "findings": []}).encode()

        async def _capturing_shell_chunk(cmd, **kwargs):
            captured.update(kwargs, cmd=cmd)
            return FakeProc(chunk_out)

        monkeypatch.setattr(
            wr, "asyncio", AsyncioProxy(create_subprocess_shell=_capturing_shell_chunk)
        )
        await wr._oracle_review_chunk("task", "diff", "", tmp_path)
        assert captured.get("cwd") == str(tmp_path)
        assert "--dangerously-skip-permissions" not in captured["cmd"]
        assert "--append-system-prompt" in captured["cmd"]
        assert '--setting-sources ""' in captured["cmd"]

    def test_strip_json_fence_edge_cases(self):
        assert wr._strip_json_fence('```json\n{"pass":true}\n```') == '{"pass":true}'
        assert wr._strip_json_fence('```\n{"pass":true}\n```') == '{"pass":true}'
        assert wr._strip_json_fence('  ```json\n{"a":1}\n```  ') == '{"a":1}'
        # untouched: bare JSON, legacy text verdicts, partial fences, garbage
        assert wr._strip_json_fence('{"pass":true}') == '{"pass":true}'
        assert wr._strip_json_fence("APPROVED: looks good") == "APPROVED: looks good"
        assert wr._strip_json_fence("prefix ```json\n{}\n```") == "prefix ```json\n{}\n```"
        assert wr._strip_json_fence("Error: rate limited") == "Error: rate limited"
        assert wr._strip_json_fence("") == ""

    async def test_garbage_output_is_infra(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            wr, "asyncio",
            AsyncioProxy(create_subprocess_shell=_shell_returning(
                FakeProc(b"503 Service Unavailable"))),
        )
        approved, reason, infra = await wr._oracle_review_chunk("task", "diff", "", tmp_path)
        assert infra is True


# ─── Chunked-path severity gate (domdomegg) ──────────────────────────────────


def _chunk_json(decision: str, findings: list, fix_guidance: str = "") -> bytes:
    return json.dumps({
        "decision": decision,
        "confidence": "medium",
        "dimensions": {"correctness": "pass", "completeness": "pass", "code_quality": "warn — nits"},
        "findings": findings,
        "fix_guidance": fix_guidance,
    }).encode()


class TestChunkSeverityGate:
    async def test_rejected_with_only_warnings_is_demoted(self, tmp_path, monkeypatch):
        findings = [
            {"dimension": "code_quality", "severity": "warning", "fix_suggestion": "rename var x"},
            {"dimension": "code_quality", "severity": "info", "fix_suggestion": "add docstring"},
        ]
        monkeypatch.setattr(
            wr, "asyncio",
            AsyncioProxy(create_subprocess_shell=_shell_returning(
                FakeProc(_chunk_json("REJECTED", findings)))),
        )
        approved, reason, infra = await wr._oracle_review_chunk("task", "diff", "1/2", tmp_path)
        assert (approved, infra) == (True, False)
        assert "follow-ups" in reason
        content = (tmp_path / "skipped.md").read_text()
        assert "[AI]" in content
        assert "rename var x" in content
        assert "chunk 1/2" in content

    async def test_rejected_with_error_finding_stays_rejected(self, tmp_path, monkeypatch):
        findings = [
            {"dimension": "correctness", "severity": "error", "fix_suggestion": "null deref in auth.py"},
            {"dimension": "code_quality", "severity": "warning", "fix_suggestion": "rename var"},
        ]
        monkeypatch.setattr(
            wr, "asyncio",
            AsyncioProxy(create_subprocess_shell=_shell_returning(
                FakeProc(_chunk_json("REJECTED", findings, "fix the null deref")))),
        )
        approved, reason, infra = await wr._oracle_review_chunk("task", "diff", "", tmp_path)
        assert (approved, infra) == (False, False)
        assert "null deref" in reason

    async def test_rejected_with_no_findings_keeps_decision(self, tmp_path, monkeypatch):
        # Legacy fix_guidance-only rejection: decision is honored (no findings to gate on)
        monkeypatch.setattr(
            wr, "asyncio",
            AsyncioProxy(create_subprocess_shell=_shell_returning(
                FakeProc(_chunk_json("REJECTED", [], "rework the approach")))),
        )
        approved, reason, infra = await wr._oracle_review_chunk("task", "diff", "", tmp_path)
        assert (approved, infra) == (False, False)

    async def test_approved_with_warnings_logs_followups(self, tmp_path, monkeypatch):
        findings = [
            {"dimension": "code_quality", "severity": "warning", "fix_suggestion": "extract helper"},
        ]
        monkeypatch.setattr(
            wr, "asyncio",
            AsyncioProxy(create_subprocess_shell=_shell_returning(
                FakeProc(_chunk_json("APPROVED", findings)))),
        )
        approved, reason, infra = await wr._oracle_review_chunk("task", "diff", "2/3", tmp_path)
        assert (approved, infra) == (True, False)
        assert "extract helper" in (tmp_path / "skipped.md").read_text()

    def test_prompt_template_contains_severity_rule(self):
        assert "severity 'error'" in wr._ORACLE_PROMPT_TEMPLATE
        assert "NEVER justify rejection" in wr._ORACLE_PROMPT_TEMPLATE


class TestAppendFollowupFindings:
    def test_creates_file_with_header(self, tmp_path):
        wr._append_followup_findings(
            tmp_path,
            [{"dimension": "code_quality", "severity": "warning", "fix_suggestion": "do X"}],
            "chunk 1/1",
        )
        content = (tmp_path / "skipped.md").read_text()
        assert content.startswith("# Skipped / Follow-up Findings")
        assert "[warning/code_quality] do X" in content

    def test_appends_without_duplicate_header(self, tmp_path):
        for fix in ("first", "second"):
            wr._append_followup_findings(
                tmp_path,
                [{"dimension": "x", "severity": "info", "fix_suggestion": fix}],
                "chunk 1/1",
            )
        content = (tmp_path / "skipped.md").read_text()
        assert content.count("# Skipped / Follow-up Findings") == 1
        assert "first" in content and "second" in content

    def test_error_findings_not_written(self, tmp_path):
        wr._append_followup_findings(
            tmp_path,
            [{"dimension": "correctness", "severity": "error", "fix_suggestion": "fatal"}],
            "chunk 1/1",
        )
        assert not (tmp_path / "skipped.md").exists()

    def test_malformed_findings_fail_open(self, tmp_path):
        wr._append_followup_findings(
            tmp_path, [None, "a string", {"severity": "warning"}], "chunk 1/1"
        )  # must not raise; nothing useful to write
        assert not (tmp_path / "skipped.md").exists()


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

        async def fake_review(desc, diff, cdir, **kwargs):
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

        async def fake_review(desc, diff, cdir, **kwargs):
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

        async def fake_review(desc, diff, cdir, **kwargs):
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

        async def fake_review(desc, diff, cdir, **kwargs):
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

        async def fake_review(desc, diff, cdir, **kwargs):
            return True, "approved (spec+quality passed)", False

        monkeypatch.setattr(wmod, "_oracle_review", fake_review)
        monkeypatch.setattr(wmod, "_reset_oracle_infra_streak", resets.append)

        assert await gate_worker._run_oracle_gate() is True
        assert gate_worker.oracle_result == "approved"
        assert len(resets) == 1


# ─── Criteria injection + rubric (claude-cookbooks) ──────────────────────────


class TestBuildOracleTaskBlock:
    def test_full_description_not_truncated_at_400(self):
        desc = "x" * 399 + "MARKER_BEYOND_400" + "y" * 500
        block = wr._build_oracle_task_block(desc, None)
        assert "MARKER_BEYOND_400" in block

    def test_caps_at_task_desc_cap(self):
        desc = "x" * (wr._ORACLE_TASK_DESC_CAP + 1000)
        block = wr._build_oracle_task_block(desc, None)
        assert len(block) == wr._ORACLE_TASK_DESC_CAP

    def test_criteria_rendered_as_numbered_list(self):
        block = wr._build_oracle_task_block(
            "do the thing", ["All auth tests pass", "No new imports"]
        )
        assert "Acceptance criteria (give a verdict for EACH):" in block
        assert "1. All auth tests pass" in block
        assert "2. No new imports" in block

    def test_no_criteria_no_header(self):
        block = wr._build_oracle_task_block("do the thing", None)
        assert "Acceptance criteria" not in block
        assert block == "do the thing"

    def test_criteria_capped_at_ten(self):
        block = wr._build_oracle_task_block("t", [f"c{i}" for i in range(15)])
        assert "10. c9" in block
        assert "11." not in block


class TestCriteriaReachTheOracle:
    async def test_two_pass_spec_prompt_contains_criteria_and_full_desc(
        self, tmp_path, monkeypatch
    ):
        prompts: list[str] = []

        async def fake_pass(prompt, cdir):
            prompts.append(prompt)
            return True, "high", "", False

        monkeypatch.setattr(wr, "_oracle_pass", fake_pass)
        desc = "Implement the feature. " + "detail " * 100  # > 400 chars
        await wr._oracle_review(
            desc, "small diff", tmp_path,
            acceptance_criteria=["All 12 tests pass", "API unchanged"],
        )
        spec_prompt = prompts[0]
        assert "All 12 tests pass" in spec_prompt
        assert "API unchanged" in spec_prompt
        assert desc[:wr._ORACLE_TASK_DESC_CAP][-50:] in spec_prompt  # beyond old 400 cap

    async def test_chunked_path_receives_criteria(self, tmp_path, monkeypatch):
        seen_tasks: list[str] = []

        async def fake_chunk(task, chunk, label, cdir):
            seen_tasks.append(task)
            return True, "approved", False

        monkeypatch.setattr(wr, "_oracle_review_chunk", fake_chunk)
        await wr._oracle_review(
            "big refactor", "x" * 9000, tmp_path,
            acceptance_criteria=["No circular imports"],
        )
        assert seen_tasks and all("No circular imports" in t for t in seen_tasks)


class TestOraclePromptFixtures:
    def test_spec_prompt_keeps_parser_contract(self):
        # _oracle_pass parses pass/confidence/issues — the rewrite must keep them
        assert '"pass":true' in wr._ORACLE_SPEC_PROMPT
        assert '"pass":false' in wr._ORACLE_SPEC_PROMPT
        assert '"confidence"' in wr._ORACLE_SPEC_PROMPT
        assert '"issues"' in wr._ORACLE_SPEC_PROMPT

    def test_spec_prompt_has_per_criterion_verdicts_and_evidence(self):
        assert '"criteria"' in wr._ORACLE_SPEC_PROMPT
        assert '"verdict"' in wr._ORACLE_SPEC_PROMPT
        assert "file:line" in wr._ORACLE_SPEC_PROMPT

    def test_spec_prompt_has_no_fire_list(self):
        assert "Do NOT fail for" in wr._ORACLE_SPEC_PROMPT
        assert "style preferences" in wr._ORACLE_SPEC_PROMPT
        assert "pre-existing issues" in wr._ORACLE_SPEC_PROMPT

    def test_quality_prompt_has_no_fire_list_and_contract(self):
        assert "Do NOT fail for" in wr._ORACLE_QUALITY_PROMPT
        assert '"pass":true' in wr._ORACLE_QUALITY_PROMPT

    def test_chunk_template_has_evidence_and_no_fire_list(self):
        assert "file:line evidence" in wr._ORACLE_PROMPT_TEMPLATE
        assert "Do NOT reject for" in wr._ORACLE_PROMPT_TEMPLATE

    def test_spec_prompt_formats_cleanly(self):
        # {task}/{diff} placeholders survive the rewrite ({{ }} escapes intact)
        rendered = wr._ORACLE_SPEC_PROMPT.format(task="T", diff="D")
        assert "Task: T" in rendered and "Diff:\nD" in rendered
        rendered = wr._ORACLE_PROMPT_TEMPLATE.format(task="T", diff="D")
        assert "Task: T" in rendered


class TestGatePassesCriteria:
    async def test_gate_extracts_schema_criteria(self, tmp_path, monkeypatch):
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        claude_dir = repo / ".claude"
        claude_dir.mkdir()
        desc = (
            "Implement auth\n\n```json\n"
            '{"acceptance_criteria": ["All auth tests pass"]}\n```\n'
        )
        w = wmod.Worker(
            task_id="task-crit1", description=desc, model="haiku",
            project_dir=repo, claude_dir=claude_dir,
        )
        monkeypatch.setitem(wmod.GLOBAL_SETTINGS, "auto_oracle", True)
        captured: dict = {}

        async def fake_review(desc_, diff, cdir, acceptance_criteria=None, **kwargs):
            captured["criteria"] = acceptance_criteria
            return True, "approved", False

        monkeypatch.setattr(wmod, "_oracle_review", fake_review)
        monkeypatch.setattr(wmod, "_reset_oracle_infra_streak", lambda d: None)
        assert await w._run_oracle_gate() is True
        assert captured["criteria"] == ["All auth tests pass"]

    async def test_gate_passes_none_without_schema(self, gate_worker, monkeypatch):
        monkeypatch.setitem(wmod.GLOBAL_SETTINGS, "auto_oracle", True)
        captured: dict = {"criteria": "sentinel"}

        async def fake_review(desc_, diff, cdir, acceptance_criteria=None, **kwargs):
            captured["criteria"] = acceptance_criteria
            return True, "approved", False

        monkeypatch.setattr(wmod, "_oracle_review", fake_review)
        monkeypatch.setattr(wmod, "_reset_oracle_infra_streak", lambda d: None)
        assert await gate_worker._run_oracle_gate() is True
        assert captured["criteria"] is None


# ─── Evidence before verdict (mic92) ─────────────────────────────────────────


class TestBuildTestEvidence:
    def test_empty_when_nothing_ran(self):
        assert wr._build_test_evidence(True, "", "") == ""

    def test_passed_with_output(self):
        ev = wr._build_test_evidence(True, "5 passed in 1.2s", "")
        assert ev.startswith("Project tests PASSED.")
        assert "5 passed" in ev

    def test_failed_with_output(self):
        ev = wr._build_test_evidence(False, "2 failed, 3 passed", "")
        assert ev.startswith("Project tests FAILED.")
        assert "2 failed" in ev

    def test_regression_warning_included(self):
        ev = wr._build_test_evidence(False, "1 failed", "Intramorphic regression detected — 1 test(s)")
        assert "Intramorphic regression" in ev


class TestEvidenceReachesPrompts:
    async def test_two_pass_prompts_carry_evidence(self, tmp_path, monkeypatch):
        prompts: list[str] = []

        async def fake_pass(prompt, cdir):
            prompts.append(prompt)
            return True, "high", "", False

        monkeypatch.setattr(wr, "_oracle_pass", fake_pass)
        await wr._oracle_review(
            "task", "small diff", tmp_path,
            test_evidence="Project tests PASSED.\n12 passed in 2.1s",
        )
        assert len(prompts) == 2
        for p in prompts:  # spec AND quality pass both see the evidence
            assert "Test results (run before this review):" in p
            assert "12 passed" in p

    async def test_chunked_path_carries_evidence(self, tmp_path, monkeypatch):
        seen: list[str] = []

        async def fake_chunk(task, chunk, label, cdir):
            seen.append(task)
            return True, "approved", False

        monkeypatch.setattr(wr, "_oracle_review_chunk", fake_chunk)
        await wr._oracle_review(
            "task", "x" * 9000, tmp_path,
            test_evidence="Project tests FAILED.\n1 failed",
        )
        assert seen and all("Project tests FAILED." in t for t in seen)

    def test_quality_prompt_formats_with_evidence_placeholder(self):
        rendered = wr._ORACLE_QUALITY_PROMPT.format(diff="D", evidence="EVIDENCE\n\n")
        assert "EVIDENCE" in rendered and "Diff:\nD" in rendered
        rendered = wr._ORACLE_QUALITY_PROMPT.format(diff="D", evidence="")
        assert "Diff:\nD" in rendered


class TestVerifyAndCommitTestGate:
    """Pre-push test gate inside verify_and_commit: tests run BEFORE the oracle
    gate and BEFORE auto_push; failure undoes the commit and flags requeue."""

    @pytest.fixture(autouse=True)
    def _real_evidence_builder(self, monkeypatch):
        # conftest mocks the worker_review module — restore the real builder
        monkeypatch.setattr(wmod, "_build_test_evidence", wr._build_test_evidence)

    def _make_worker(self, tmp_path, test_cmd: str):
        repo = tmp_path / "repo"
        repo.mkdir()
        _init_git_repo(repo)
        claude_dir = repo / ".claude"
        claude_dir.mkdir()
        (claude_dir / "orchestrator.json").write_text(json.dumps({"test_cmd": test_cmd}))
        w = wmod.Worker(
            task_id="task-ev1", description="implement feature",
            model="haiku", project_dir=repo, claude_dir=claude_dir,
        )
        # Dirty the tree so verify_and_commit sees changed files
        (repo / "file0.txt").write_text("modified content\n")
        return w

    def _fake_shell_sequence(self, calls: list[str]):
        """1st shell call = haiku verify (VERIFIED_OK), 2nd = commit (rc 0)."""
        async def fake_shell(cmd, *args, **kwargs):
            calls.append(cmd)
            return FakeProc(b"VERIFIED_OK" if len(calls) == 1 else b"")
        return fake_shell

    async def test_failure_skips_push_and_requeues(self, tmp_path, monkeypatch):
        w = self._make_worker(tmp_path, "echo FAILING_TEST_OUTPUT; exit 1")
        calls: list[str] = []
        monkeypatch.setattr(
            wmod, "asyncio",
            AsyncioProxy(create_subprocess_shell=self._fake_shell_sequence(calls)),
        )
        gate_calls: list[str] = []

        async def fake_gate(self_, test_evidence=""):
            gate_calls.append(test_evidence)
            return True

        monkeypatch.setattr(wmod.Worker, "_run_oracle_gate", fake_gate)

        assert await w.verify_and_commit() is False
        assert w._test_requeue is True
        assert "FAILING_TEST_OUTPUT" in w._test_requeue_reason
        assert w.auto_committed is False
        assert "Pre-push tests failed" in w.failure_context
        assert gate_calls == []           # oracle gate never reached
        assert len(calls) == 2            # verify + commit only — no push
        assert _commit_count(w._project_dir) == 1  # commit undone

    async def test_pass_reaches_gate_with_evidence_then_push_skipped(self, tmp_path, monkeypatch):
        w = self._make_worker(tmp_path, "echo TESTS_OK")
        calls: list[str] = []
        monkeypatch.setattr(
            wmod, "asyncio",
            AsyncioProxy(create_subprocess_shell=self._fake_shell_sequence(calls)),
        )
        monkeypatch.setitem(wmod.GLOBAL_SETTINGS, "auto_push", False)
        gate_calls: list[str] = []

        async def fake_gate(self_, test_evidence=""):
            gate_calls.append(test_evidence)
            return True

        monkeypatch.setattr(wmod.Worker, "_run_oracle_gate", fake_gate)

        assert await w.verify_and_commit() is True
        assert w._test_requeue is False
        # Tests ran BEFORE the gate, and the gate saw their output as evidence
        assert len(gate_calls) == 1
        assert "Project tests PASSED." in gate_calls[0]
        assert "TESTS_OK" in gate_calls[0]

    async def test_no_test_cmd_gate_gets_empty_evidence(self, tmp_path, monkeypatch):
        w = self._make_worker(tmp_path, "")
        (w._claude_dir / "orchestrator.json").unlink()  # no test_cmd, no auto-detect
        calls: list[str] = []
        monkeypatch.setattr(
            wmod, "asyncio",
            AsyncioProxy(create_subprocess_shell=self._fake_shell_sequence(calls)),
        )
        monkeypatch.setitem(wmod.GLOBAL_SETTINGS, "auto_push", False)
        gate_calls: list[str] = []

        async def fake_gate(self_, test_evidence=""):
            gate_calls.append(test_evidence)
            return True

        monkeypatch.setattr(wmod.Worker, "_run_oracle_gate", fake_gate)

        assert await w.verify_and_commit() is True
        assert gate_calls == [""]  # no fake green-suite claim


# ─── Fix-intent completeness criterion (item 15 part 1) ─────────────────────


class TestDetectFixIntent:
    @pytest.mark.parametrize("desc", [
        "fix: login crash on empty password",
        "Fix the bug in auth flow",
        "regression in parser since v2",
        "hotfix for prod outage",
        "BUG: dates render off-by-one",
    ])
    def test_fix_intent_detected(self, desc):
        assert wr._detect_fix_intent(desc) is True

    @pytest.mark.parametrize("desc", [
        "implement new feature for exports",
        "debug logging improvements",     # 'debug' must not match 'bug'
        "prefix: rename the config keys",  # 'prefix:' must not match 'fix:'
        "refactor module layout",
        "",
    ])
    def test_no_fix_intent(self, desc):
        assert wr._detect_fix_intent(desc) is False


class TestFixIntentCriterion:
    def test_fix_task_gets_covering_test_criterion(self):
        block = wr._build_oracle_task_block("fix: crash on empty input", None)
        assert "bug-fix task" in block
        assert "test covering the previously-failing input" in block

    def test_infra_yes_with_evidence(self):
        block = wr._build_oracle_task_block(
            "fix: crash on empty input", None,
            test_evidence="Project tests PASSED.\n3 passed",
        )
        assert "Test infrastructure present in this project: yes" in block

    def test_infra_unknown_without_evidence(self):
        block = wr._build_oracle_task_block("fix: crash on empty input", None)
        assert "Test infrastructure present in this project: unknown" in block

    def test_non_fix_task_has_no_criterion(self):
        block = wr._build_oracle_task_block("implement exports feature", None)
        assert "bug-fix task" not in block

    async def test_criterion_reaches_spec_prompt(self, tmp_path, monkeypatch):
        prompts: list[str] = []

        async def fake_pass(prompt, cdir):
            prompts.append(prompt)
            return True, "high", "", False

        monkeypatch.setattr(wr, "_oracle_pass", fake_pass)
        await wr._oracle_review("fix: crash on empty input", "small diff", tmp_path)
        assert "bug-fix task" in prompts[0]

    async def test_criterion_reaches_chunked_path(self, tmp_path, monkeypatch):
        seen: list[str] = []

        async def fake_chunk(task, chunk, label, cdir):
            seen.append(task)
            return True, "approved", False

        monkeypatch.setattr(wr, "_oracle_review_chunk", fake_chunk)
        await wr._oracle_review("fix: regression in worker pool", "x" * 9000, tmp_path)
        assert seen and all("bug-fix task" in t for t in seen)


async def test_poll_all_requeues_on_pre_push_test_failure(task_queue, tmp_path):
    pool = wmod.WorkerPool()
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(exist_ok=True)
    w = wmod.Worker(
        task_id="task-tf1", description="implement feature X",
        model="haiku", project_dir=tmp_path, claude_dir=claude_dir,
    )
    w.status = "done"
    w._terminal_persisted = True
    w._test_requeue = True
    w._test_requeue_reason = "Project tests FAILED.\n2 failed, 1 passed"
    pool.workers[w.id] = w

    await pool.poll_all(task_queue, None)

    assert w._test_requeue is False
    tasks = await task_queue.list()
    retries = [t for t in tasks if "FAILED the project test suite" in t["description"]]
    assert len(retries) == 1
    assert "2 failed" in retries[0]["description"]
    assert "implement feature X" in retries[0]["description"]
