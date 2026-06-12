"""Tests for pure-logic Worker methods (no subprocess needed)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# ─── Load real Worker module bypassing conftest mock ──────────────────────────
# conftest.py patches sys.modules["worker"] with a MagicMock to prevent
# subprocess side-effects during task_queue tests. We need the real class here,
# so we load worker.py under a private name to bypass that mock.

_WORKER_FILE = Path(__file__).parent.parent / "worker.py"
_spec = importlib.util.spec_from_file_location("_real_worker", _WORKER_FILE)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
Worker = _mod.Worker


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def worker(tmp_path: Path) -> Worker:
    """A Worker instance backed by tmp_path directories."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    return Worker(
        task_id="task-abc123",
        description="Fix the login bug",
        model="sonnet",
        project_dir=tmp_path,
        claude_dir=claude_dir,
    )


# ─── Tests ────────────────────────────────────────────────────────────────────


def test_worker_init(worker: Worker) -> None:
    assert worker.status == "starting"
    assert len(worker.id) == 8
    assert worker.description == "Fix the login bug"


def test_worker_to_dict_keys(worker: Worker) -> None:
    d = worker.to_dict()
    expected_keys = {
        "id", "task_id", "description", "model", "status", "pid",
        "elapsed_s", "last_commit", "log_file", "verified",
        "auto_committed", "auto_pushed", "branch_name", "pr_url",
        "pr_merged", "log_tail", "failure_context", "worktree_path",
        "oracle_result", "oracle_reason", "model_score",
        "estimated_tokens", "context_warning",
        "input_tokens", "output_tokens", "estimated_cost",
    }
    assert expected_keys.issubset(d.keys())
    # description truncated to 80 chars
    assert len(d["description"]) <= 80


def test_worker_is_alive_false_when_no_proc(worker: Worker) -> None:
    assert worker.proc is None
    assert worker.is_alive() is False


def test_worker_elapsed_s(worker: Worker) -> None:
    t0 = worker.elapsed_s
    # elapsed_s should be non-negative and stable (same-second call)
    assert t0 >= 0
    t1 = worker.elapsed_s
    assert t1 >= t0


def test_worker_build_cmd_and_env(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    w = Worker(
        task_id="task-xyz",
        description="Write tests",
        model="haiku",
        project_dir=tmp_path,
        claude_dir=claude_dir,
    )
    task_file = tmp_path / "task.md"
    task_file.write_text("do the thing")

    cmd, env = w._build_cmd_and_env(task_file)

    assert "--dangerously-skip-permissions" in cmd
    # model alias resolved: "haiku" → full model name
    assert "claude-haiku" in cmd
    # CLAUDECODE must not be in the env dict
    assert "CLAUDECODE" not in env
    # attribution: committer.sh appends Co-Authored-By + X-Clade-Task trailers
    # when this is set, so every worker-session commit is agent-segmentable
    assert env["CLADE_WORKER_TASK_ID"] == "task-xyz"


# ─── Delegation to worker_utils (wave-2 extraction for the 1500-line cap) ─────


def test_check_file_ownership_delegates_to_worker_utils(worker: Worker) -> None:
    """Worker._check_file_ownership is a thin delegate over the moved glob logic."""
    worker.own_files = ["src/**"]
    worker.forbidden_files = ["secrets/**"]

    ok, reason = worker._check_file_ownership(["src/a.py"])
    assert ok is True
    assert reason == ""

    ok, reason = worker._check_file_ownership(["other/b.py"])
    assert ok is False
    assert "OWN_FILES" in reason

    ok, reason = worker._check_file_ownership(["secrets/key.pem"])
    assert ok is False
    assert "FORBIDDEN_FILES" in reason


def test_get_activity_state_delegates(worker: Worker) -> None:
    """No session JSONL under tmp claude_dir → 'unknown' via the moved helper."""
    assert worker._get_activity_state() == "unknown"


def test_classify_retry_helper_is_reexported_from_worker_utils() -> None:
    """Pure move + re-export: worker exposes the worker_utils function object."""
    import worker_utils

    assert _mod._maybe_enqueue_classify_retry is worker_utils._maybe_enqueue_classify_retry
