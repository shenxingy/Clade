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
