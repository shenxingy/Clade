"""Worker lifecycle integration tests for EvidenceBundle attempts."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from agent_runtime import AgentRuntimeSelectionError
from worker_evidence import (
    append_worker_evidence,
    append_worker_terminal_evidence,
    begin_task_evidence,
    start_worker_with_evidence,
)
from worker_runtime import resolve_worker_execution


GITHUB_TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"


def _git(repo, *args):
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


async def test_worker_lifecycle_persists_terminal_evidence(task_queue, tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.name", "Evidence Test")
    _git(tmp_path, "config", "user.email", "evidence@example.test")
    (tmp_path / "base.txt").write_text("base\n")
    _git(tmp_path, "add", "base.txt")
    _git(tmp_path, "commit", "-q", "-m", "base")

    task = await task_queue.add("Implement lifecycle evidence")
    attempt = await begin_task_evidence(task, task_queue, tmp_path)
    assert attempt is not None
    worker = SimpleNamespace(
        id="worker-1",
        task_id=task["id"],
        _task_queue=task_queue,
        evidence_attempt_id=attempt["attempt_id"],
        evidence_base_sha=attempt["evidence"]["git"]["base_sha"],
        _project_dir=tmp_path,
        execution_envelope=None,
        status="running",
        transition_reason="process_started",
        started_at=100.0,
        elapsed_s=5,
        auto_committed=False,
        auto_pushed=False,
        verified=False,
        completion_summary=None,
        last_commit=None,
        test_evidence="",
        oracle_result=None,
        oracle_reason=None,
        failure_context=None,
        _oracle_requeue=False,
        _oracle_requeue_reason=None,
        _test_requeue_reason=None,
        _ownership_violation_reason=None,
        _handoff_type=None,
        _handoff_payload=None,
        _input_tokens=0,
        _output_tokens=0,
        _estimated_cost=0.0,
        _finished_at=None,
        branch_name=None,
        pr_url=None,
    )
    await append_worker_evidence(worker, "running")
    await append_worker_evidence(worker, "verifying")

    (tmp_path / "result.txt").write_text("done\n")
    _git(tmp_path, "add", "result.txt")
    _git(tmp_path, "commit", "-q", "-m", "result")
    worker.status = "done"
    worker.auto_committed = True
    worker.auto_pushed = True
    worker.verified = True
    worker.last_commit = _git(tmp_path, "log", "-1", "--oneline")
    worker.test_evidence = "12 passed"
    worker.oracle_result = "approved"
    worker.oracle_reason = f"reviewed without {GITHUB_TOKEN}"
    worker._input_tokens = 100
    worker._output_tokens = 25
    worker._estimated_cost = 0.05
    worker.branch_name = "orchestrator/task-test"
    await append_worker_terminal_evidence(worker)

    history = await task_queue.get_evidence_history(attempt["attempt_id"])
    assert [item["lifecycle_state"] for item in history] == [
        "created",
        "running",
        "verifying",
        "delivered",
    ]
    terminal = history[-1]
    assert terminal["evidence"]["git"]["head_sha"] == _git(
        tmp_path, "rev-parse", "HEAD"
    )
    assert terminal["evidence"]["artifacts"]["changed_files"] == ["result.txt"]
    assert terminal["evidence"]["verification"]["oracle_verdict"] == "approved"
    assert GITHUB_TOKEN not in str(terminal)
    assert terminal["redaction_metadata"]["count"] == 1
    assert terminal["evidence"]["usage"]["estimated_cost"] == 0.05
    assert terminal["evidence"]["delivery_candidate"]["pushed"] is True
    telemetry = terminal["evidence"]["telemetry"]
    assert telemetry["schema_version"] == "clade.attempt_telemetry/v1"
    assert telemetry["attempt_index"] == 1
    assert telemetry["parent_attempt_id"] is None
    assert telemetry["result"]["outcome"] == "delivered"
    assert telemetry["result"]["final_oracle"] == "approved"
    assert await task_queue.list_eval_candidates() == []

    rejected_task = await task_queue.add("Capture rejected oracle patch")
    rejected_attempt = await begin_task_evidence(
        rejected_task, task_queue, tmp_path
    )
    rejected = SimpleNamespace(**vars(worker))
    rejected.id = "worker-rejected"
    rejected.task_id = rejected_task["id"]
    rejected.evidence_attempt_id = rejected_attempt["attempt_id"]
    rejected.evidence_base_sha = rejected_attempt["evidence"]["git"]["base_sha"]
    rejected.status = "failed"
    rejected.auto_committed = False
    rejected.auto_pushed = False
    rejected.oracle_result = "rejected"
    rejected.oracle_reason = "unsafe behavior"
    rejected.eval_diff = "diff --git a/parser.py b/parser.py\n+unsafe\n"
    rejected.failure_context = "oracle rejected generated patch"
    await append_worker_terminal_evidence(rejected)

    candidates = await task_queue.list_eval_candidates()
    assert [item["trigger"] for item in candidates] == ["oracle_rejected"]
    assert candidates[0]["source_evidence_digest"] == (
        await task_queue.get_evidence_bundle(rejected_attempt["attempt_id"])
    )["digest"]


async def test_attempt_parent_links_same_task_retry_and_child_task(task_queue, tmp_path):
    task = await task_queue.add("Original attempt")
    first = await begin_task_evidence(task, task_queue, tmp_path)
    same_task_retry = await begin_task_evidence(task, task_queue, tmp_path)

    assert same_task_retry["evidence"]["attempt"]["parent_attempt_id"] == (
        first["attempt_id"]
    )

    child = await task_queue.add(
        "Retry as a child task", parent_task_id=task["id"]
    )
    child_attempt = await begin_task_evidence(child, task_queue, tmp_path)

    assert child_attempt["evidence"]["attempt"]["parent_attempt_id"] == (
        same_task_retry["attempt_id"]
    )


async def test_runtime_preflight_failure_closes_evidence_attempt(task_queue, tmp_path):
    task = await task_queue.add(
        "Reject an invalid runtime before spawn",
        provider="claud",
    )

    with pytest.raises(AgentRuntimeSelectionError):
        await resolve_worker_execution(task, {}, task_queue, tmp_path)

    attempts = await task_queue.list_evidence_attempts(task["id"])
    assert len(attempts) == 1
    assert (await task_queue.get(task["id"]))["attempt_count"] == 1
    assert attempts[0]["lifecycle_state"] == "failed"
    assert attempts[0]["evidence"]["failure"]["stage"] == "preflight"
    candidates = await task_queue.list_eval_candidates()
    assert len(candidates) == 1
    assert candidates[0]["trigger"] == "incident_failure"
    assert candidates[0]["source_evidence_digest"] == attempts[0]["digest"]


async def test_spawn_failure_closes_created_attempt(task_queue, tmp_path):
    task = await task_queue.add("Capture a worker spawn failure")
    attempt = await begin_task_evidence(task, task_queue, tmp_path)
    assert attempt is not None

    class FailingWorker:
        evidence_attempt_id = attempt["attempt_id"]
        status = "starting"
        failure_context = None

        async def start(self, task_queue):
            raise RuntimeError("spawn denied")

    worker = FailingWorker()
    with pytest.raises(RuntimeError, match="spawn denied"):
        await start_worker_with_evidence(worker, task_queue)

    latest = await task_queue.get_evidence_bundle(attempt["attempt_id"])
    assert latest["lifecycle_state"] == "failed"
    assert latest["evidence"]["failure"]["stage"] == "spawn"
    candidates = await task_queue.list_eval_candidates()
    assert len(candidates) == 1
    assert candidates[0]["trigger"] == "incident_failure"


# ─── Git control surface guard ────────────────────────────────────────────────


class TestGitControlSurfaceGuard:
    """A worktree bounds the working tree, not `.git`.

    From inside a `git worktree add` tree, `git rev-parse --git-common-dir`
    resolves to the PARENT repo's `.git`. An agent can therefore write
    `<main>/.git/hooks/pre-commit`, and that hook executes the next time the
    OPERATOR commits in the main checkout. Reproduced on a real repo before
    this guard was written. Workers spawn with permissions bypassed, so nothing
    else stands in the way.
    """

    @staticmethod
    def _repo(tmp_path):
        import subprocess

        repo = tmp_path / "main"
        repo.mkdir()
        for cmd in (
            ["git", "init", "-q"],
            ["git", "config", "user.email", "t@example.com"],
            ["git", "config", "user.name", "t"],
            ["git", "commit", "-q", "--allow-empty", "-m", "root"],
        ):
            subprocess.run(cmd, cwd=repo, check=True, capture_output=True)
        return repo

    def test_normal_worktree_traffic_does_not_move_the_digest(self, tmp_path):
        """Zero false positives is what makes this usable as a hard gate."""
        import subprocess

        from worker_utils import git_control_surface, git_control_surface_changes

        repo = self._repo(tmp_path)
        git_dir = repo / ".git"
        before = git_control_surface(git_dir)
        assert before, "surface should not be empty for a real repo"

        wt = tmp_path / "wt"
        subprocess.run(["git", "worktree", "add", "-q", str(wt), "-b", "feat"],
                       cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "work"],
                       cwd=wt, check=True, capture_output=True)
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)],
                       cwd=repo, check=True, capture_output=True)

        assert git_control_surface_changes(before, git_control_surface(git_dir)) == []

    def test_a_hook_planted_from_the_worktree_is_detected(self, tmp_path):
        import subprocess

        from worker_utils import git_control_surface, git_control_surface_changes

        repo = self._repo(tmp_path)
        before = git_control_surface(repo / ".git")

        wt = tmp_path / "wt"
        subprocess.run(["git", "worktree", "add", "-q", str(wt), "-b", "feat"],
                       cwd=repo, check=True, capture_output=True)
        # Exactly what an agent inside the worktree can do today.
        common = subprocess.run(["git", "rev-parse", "--git-common-dir"],
                                cwd=wt, check=True, capture_output=True, text=True).stdout.strip()
        hook = (wt / common).resolve() / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\necho pwned\n")

        changes = git_control_surface_changes(before, git_control_surface(repo / ".git"))
        assert changes == ["added hooks/pre-commit"]

    def test_config_tampering_is_detected(self, tmp_path):
        """core.fsmonitor / core.pager / aliases all execute a command."""
        import subprocess

        from worker_utils import git_control_surface, git_control_surface_changes

        repo = self._repo(tmp_path)
        before = git_control_surface(repo / ".git")
        subprocess.run(["git", "config", "core.fsmonitor", "/tmp/evil.sh"],
                       cwd=repo, check=True, capture_output=True)
        assert git_control_surface_changes(before, git_control_surface(repo / ".git")) == [
            "modified config"
        ]

    def test_missing_or_none_dir_is_empty_not_an_error(self, tmp_path):
        from worker_utils import git_control_surface

        assert git_control_surface(None) == {}
        assert git_control_surface(tmp_path / "nope") == {}

    async def test_verify_refuses_when_the_surface_moved(self, tmp_path):
        """The gate must stop before verify_and_commit, not after."""
        from unittest.mock import AsyncMock, MagicMock

        import worker_evidence

        worker = MagicMock()
        worker.id = "w1"
        worker._git_surface_before = {"hooks/pre-commit": "aaa"}
        worker._git_surface_common_dir = tmp_path / "nope"  # -> empty surface = "removed"
        worker._original_project_dir = tmp_path
        worker.verify_and_commit = AsyncMock(return_value=True)

        result = await worker_evidence.verify_worker_with_evidence(worker)

        assert result is False
        worker.verify_and_commit.assert_not_awaited()
        assert worker.transition_reason == "git_control_surface_modified"
        assert "operator" in worker.failure_context

    async def test_verify_proceeds_when_the_surface_is_intact(self, tmp_path):
        from unittest.mock import AsyncMock, MagicMock

        import worker_evidence

        worker = MagicMock()
        worker.id = "w1"
        worker._git_surface_before = {}  # guard off / nothing recorded
        worker.verify_and_commit = AsyncMock(return_value=True)

        assert await worker_evidence.verify_worker_with_evidence(worker) is True
        worker.verify_and_commit.assert_awaited_once()


# ─── Verification phases land as they happen, not only at the end ─────────────


async def test_each_verification_phase_is_its_own_revision(task_queue, tmp_path):
    """Tests, oracle and push must be answerable separately.

    They all reached disk in the single terminal append, so a crash between
    "tests passed" and "the oracle returned" lost both: the bundle could say an
    attempt failed and hand back a digest-chained final diff, but never say
    WHEN it went wrong — and the worktree holding that state was already gone.
    """
    task = await task_queue.add("Phase evidence")
    attempt = await begin_task_evidence(task, task_queue, tmp_path)
    assert attempt is not None
    worker = SimpleNamespace(
        id="worker-phase",
        task_id=task["id"],
        _task_queue=task_queue,
        evidence_attempt_id=attempt["attempt_id"],
        _project_dir=tmp_path,
        execution_envelope=None,
        status="running",
        transition_reason=None,
        started_at=100.0,
        elapsed_s=5,
    )

    await append_worker_evidence(worker, "running")
    await append_worker_evidence(worker, "verifying", phase="tests", passed=True)
    await append_worker_evidence(
        worker, "verifying", phase="oracle", verdict="rejected", reason="scope creep"
    )

    history = await task_queue.get_evidence_history(attempt["attempt_id"])
    phases = [
        rev["evidence"]["phase"]
        for rev in history
        if "phase" in rev.get("evidence", {})
    ]
    assert [p["name"] for p in phases] == ["tests", "oracle"]
    assert phases[0]["passed"] is True
    # The point of the change: the test result survives independently of the
    # oracle's, so "tests passed, then the oracle rejected" is recoverable.
    assert phases[1]["verdict"] == "rejected"
    assert phases[1]["reason"] == "scope creep"
    assert phases[0]["observed_at"] <= phases[1]["observed_at"]


async def test_a_crash_after_tests_still_leaves_the_test_result(task_queue, tmp_path):
    """The terminal append never happens; the tests phase must still be there."""
    task = await task_queue.add("Crash after tests")
    attempt = await begin_task_evidence(task, task_queue, tmp_path)
    worker = SimpleNamespace(
        id="worker-crash",
        task_id=task["id"],
        _task_queue=task_queue,
        evidence_attempt_id=attempt["attempt_id"],
        _project_dir=tmp_path,
        execution_envelope=None,
        status="running",
        transition_reason=None,
        started_at=1.0,
        elapsed_s=1,
    )
    await append_worker_evidence(worker, "running")
    await append_worker_evidence(worker, "verifying", phase="tests", passed=True)
    # …and nothing else: the process dies here.

    history = await task_queue.get_evidence_history(attempt["attempt_id"])
    recorded = [
        rev["evidence"]["phase"]["name"]
        for rev in history
        if "phase" in rev.get("evidence", {})
    ]
    assert recorded == ["tests"]


async def test_phase_is_absent_when_not_supplied(task_queue, tmp_path):
    """Existing callers must not start emitting an empty phase block."""
    task = await task_queue.add("No phase")
    attempt = await begin_task_evidence(task, task_queue, tmp_path)
    worker = SimpleNamespace(
        id="worker-nophase",
        task_id=task["id"],
        _task_queue=task_queue,
        evidence_attempt_id=attempt["attempt_id"],
        _project_dir=tmp_path,
        execution_envelope=None,
        status="running",
        transition_reason=None,
        started_at=1.0,
        elapsed_s=1,
    )
    await append_worker_evidence(worker, "running")
    await append_worker_evidence(worker, "verifying")

    history = await task_queue.get_evidence_history(attempt["attempt_id"])
    assert all("phase" not in rev.get("evidence", {}) for rev in history)
