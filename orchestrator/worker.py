"""
Orchestrator worker — execution engine.
SwarmManager is in swarm.py.

Supporting concerns are extracted into sibling ``worker_*`` and service modules
(see CLADE.md "Key File Map"); keep this file under 1500 lines.
"""
from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
import os
import re
import shlex
import shutil
import signal
import time
import uuid
from pathlib import Path
from typing import Any

from config import (
    GLOBAL_SETTINGS,
    _MODEL_ALIASES,
    HAIKU_MODEL,
    SETTING_SOURCES_NONE,
    DISALLOWED_TOOLS_JUDGE,
    resolve_worker_usage,
    _resolve_fallback_model,
    _parse_task_type, _parse_task_class,
    _parse_task_schema,
    _infer_commit_type,
)
from task_queue import TaskQueue
from github_sync import _gh_update_issue_status
from session_tree import SessionTree
from execution_backend import LocalSubprocessBackend, get_execution_backend
from execution_envelope import ExecutionEnvelope
from worker_provider import get_agent_runtime
from worker_runtime import connection_for_envelope, resolve_worker_execution
from worker_status import worker_to_dict
import condensers
import worker_review
import worker_tldr
import worker_utils
import worker_hydrate
import judge_diversity
import cascade_policy
from worker_review import (
    _oracle_review, _read_constitution, _summarize_worker_completion,
    _record_oracle_infra_error, _reset_oracle_infra_streak,
    _escalate_oracle_outage, _ORACLE_INFRA_THRESHOLD,
    handle_oracle_requeue, handle_test_requeue, handle_ownership_requeue, handle_handoff_requeue,
    _build_test_evidence,
)
from worker_taskfile import build_task_file
from event_stream import EventStream
from worker_envelope import build_from_worker
import worker_evidence
import worker_sandbox
from worker_phase_graph import record_transition, validate_transition
from handoff_registry import project_handoff, validate_handoff
from tracing import TracingService, start_task_span
from reactions import ReactionExecutor
from runtime_redaction import capture_provider_output
from error_classifier import (
    classify as _classify_error,
    summarize as _summarize_error,
)
from agent_output import absorb_agent_result
from worker_utils import (
    _distill_output, _truncate_output, _strip_error_context,
    _run_lint_check, _extract_lint_targets, _run_project_tests, LoopDetectionService,
    _run_intramorphic_check, _run_repro_filter, _rank_tasks,
    _parse_observation_contract, _fallback_commit_cmd, _is_test_file,
    _compute_activity_state, _undo_last_commit,
    _check_file_ownership as _check_ownership_globs,
    _as_env_patterns,
    _maybe_enqueue_classify_retry,  # re-export: moved to worker_utils (leaf)
    MAX_LINES, MAX_BYTES, DISTILL_THRESHOLD, MAX_REFLECTION_RETRIES,
)

logger = logging.getLogger(__name__)
# Documented leaf modules cannot import config — thread the pinned haiku
# snapshot and the pure-judge settings flag into them here (they default to
# the 'haiku' alias / the same flag literal when imported standalone).
# config.py is the single source of truth for both.
for _leaf_mod in (condensers, worker_review, worker_tldr, worker_utils, worker_hydrate):
    _leaf_mod.HAIKU_MODEL = HAIKU_MODEL
    _leaf_mod.SETTING_SOURCES_NONE = SETTING_SOURCES_NONE
    _leaf_mod.DISALLOWED_TOOLS_JUDGE = DISALLOWED_TOOLS_JUDGE

# ─── Worker ───────────────────────────────────────────────────────────────────


class Worker:
    def __init__(
        self,
        task_id: str,
        description: str,
        model: str,
        project_dir: Path,
        claude_dir: Path,
        task_type: str | None = None,
        agent_runtime: str | None = None,
        effort: str | None = None,
        route_reason: str | None = None,
        execution_envelope: ExecutionEnvelope | None = None,
    ):
        self.id = str(uuid.uuid4())[:8]
        self.task_id = task_id
        self.description = description
        self.execution_envelope = execution_envelope
        self.model = (
            execution_envelope.resolved.model
            if execution_envelope and execution_envelope.resolved.model
            else model
        )
        self._project_dir = project_dir
        self.task_type = task_type or _parse_task_type(description)
        self._original_project_dir = project_dir  # preserved for restore after worktree cleanup
        self._claude_dir = claude_dir
        self.proc: asyncio.subprocess.Process | None = None
        self.pgid: int | None = None
        self.pid: int | None = None
        # Execution backend (spawn/kill adapter). Resolved from the
        # `execution_backend` setting; defaults to LocalSubprocessBackend
        # (OS subprocess + setsid). A reserved/unbuilt backend falls back to
        # the local default so a typo'd setting never strands the pool.
        try:
            self._backend = get_execution_backend()
        except NotImplementedError:
            self._backend = LocalSubprocessBackend()
        # Agent runtime (which CLI owns the loop: Claude Code vs Codex).
        runtime_name = (
            execution_envelope.resolved.runtime_id
            if execution_envelope
            else agent_runtime
        )
        self._runtime_adapter = get_agent_runtime(runtime_name)
        self.agent_runtime = self._runtime_adapter.name
        self.effort = (
            execution_envelope.resolved.effort
            if execution_envelope
            else effort
        )
        self.route_reason = route_reason
        self.started_at = time.time()
        self._finished_at: float | None = None
        self.status = "starting"  # starting/running/paused/blocked/done/failed
        self.transition_reason: str = "initialized"  # learn-cc s00a: Query Control Plane
        self.last_commit: str | None = None
        self.log_file: str | None = None
        self._log_path: Path | None = None
        self._agent_result: Any = None  # agent_output.AgentResult when structured
        self._log_capture_task: asyncio.Task | None = None
        self._session_tree: SessionTree | None = None  # Pi-style JSONL session tree
        self.verified: bool = False
        self.auto_committed: bool = False
        self.auto_pushed: bool = False
        self.oracle_result: str | None = None
        self.oracle_reason: str | None = None
        self.test_evidence: str = ""  # pre-push test results (shown in PR body)
        self.tests_added: list[str] = []  # test files in the diff (Agent-Fingerprint signal)
        self._oracle_requeue: bool = False
        self._oracle_requeue_reason: str | None = None
        self._test_requeue: bool = False
        self._test_requeue_reason: str | None = None
        self._handoff_requeue: bool = False
        self._handoff_content: str | None = None
        self._handoff_type: str | None = None   # typed handoff (Codex SDK pattern)
        self._handoff_payload: dict | None = None
        self.model_score: int | None = None
        self.branch_name: str | None = None
        self.pr_url: str | None = None
        self.pr_merged: bool = False
        self._verify_triggered: bool = False
        self.task_timeout: int = 600  # default 10 min
        self.failure_context: str | None = None
        # One-line classified summary of subprocess failures (set by error_classifier).
        # Kept distinct from failure_context (which is the raw log tail) so the UI
        # can show "[rate_limit] retry+30s — 429 …" without repeating the body.
        self.failure_class: str | None = None
        # Full ClassifiedError preserved so swarm-level retry logic can read
        # retryable / should_compress / should_fallback_model / backoff_seconds.
        # Kept Any-typed in the annotation to avoid introducing a hard import
        # cycle in the worker.py header (error_classifier is already imported).
        self._failure_classified: Any = None
        self._worktree_path: Path | None = None
        self._worktree_error: str = ""
        # What the Landlock sandbox confined for this spawn (worker_sandbox.describe).
        self._sandbox: dict = {}
        self._branch_name: str | None = None
        self.own_files: list[str] = []
        self.forbidden_files: list[str] = []
        self._ownership_violation: bool = False
        self._ownership_violation_reason: str | None = None
        self._stuck_detected: bool = False
        self._terminal_persisted: bool = False
        self._task_queue: TaskQueue | None = None  # stored for dep clearing on completion
        self._loop_detector = LoopDetectionService()
        self._reflection_retries: int = 0
        self._event_stream = EventStream(worker_id=self.id)
        self._tracer = TracingService.get_instance().get_or_create_tracer(self.id)
        self._reaction_executor = ReactionExecutor()
        self.completion_summary: str | None = None  # 1-sentence summary (multi-agent context archival)
        self._failure_reflections: list[str] = []  # Reflexion pattern: accumulated failure notes
        self.token_budget: int = 0  # max total tokens (0 = unlimited); multi-agent Gap 2
        self.context_version: int = 0  # codebase version when task file was built; multi-agent Gap 1
        self._input_tokens: int = 0
        self._output_tokens: int = 0
        self._estimated_cost: float = 0.0
        self._task_span: Any = None

    @property
    def elapsed_s(self) -> int:
        return int((self._finished_at or time.time()) - self.started_at)

    def to_dict(self) -> dict:
        return worker_to_dict(self)

    def _estimate_tokens(self) -> int:
        desc_tokens = len(self.description) // 4
        log_tokens = 0
        if self._log_path and self._log_path.exists():
            try:
                log_tokens = self._log_path.stat().st_size // 4
            except Exception:
                pass
        return desc_tokens + log_tokens

    async def _setup_worktree(self) -> bool:
        """Create an isolated git worktree. Updates self._project_dir on success.

        Returns False when isolation could not be obtained. Every failure path
        here used to set _worktree_path = None, discard git's stderr, and leave
        _project_dir on the shared checkout — so a permission-bypassed worker
        ran in the user's own tree, silently. See CLAUDE.md on parallel writers.
        """
        # NOT .claude/worktrees/: CLI 2.1.236 claims that directory as its own
        # managed pool and deletes a session's worktree with it. An autonomous
        # worker must not share a namespace something else prunes.
        worktree_base = self._claude_dir / "orchestrator-worktrees"
        worktree_base.mkdir(parents=True, exist_ok=True)
        self._worktree_path = worktree_base / f"worker-{self.id}"
        self._branch_name = f"orchestrator/task-{self.task_id}"
        # Second attempt reuses the branch: a requeued task keeps its own.
        for branch_args in (["-b", self._branch_name], [self._branch_name]):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "git", "worktree", "add", str(self._worktree_path), *branch_args,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    cwd=str(self._project_dir),
                )
                try:
                    _, err = await asyncio.wait_for(proc.communicate(), timeout=30)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.communicate()
                    err = b"git worktree add timed out after 30s"
                if proc.returncode == 0:
                    self._project_dir = self._worktree_path
                    return True
                self._worktree_error = err.decode(errors="replace").strip()[:300]
            except Exception as exc:
                self._worktree_error = f"{type(exc).__name__}: {exc}"[:300]
        self._worktree_path = None
        logger.error("Worker %s: worktree isolation failed — %s", self.id, self._worktree_error)
        return False

    async def _build_task_file(self, task_queue: TaskQueue | None) -> Path:
        """Write the task file with injected context (see worker_taskfile.py)."""
        return await build_task_file(self, task_queue)

    def _build_cmd_and_env(self, task_file: Path) -> tuple[str, dict]:
        """Build the worker shell command (via the runtime adapter) + env dict.

        Worker spawn keeps full user settings deliberately (NO --setting-sources ""):
        commit-discipline hooks (post-edit-check etc.) are core value. Pure judges
        drop them — see config.SETTING_SOURCES_NONE (Stop-hook -p poisoning, 386a862).
        The Claude adapter reproduces the historical inline command byte-for-byte.
        """
        mcp_config = self._project_dir / ".claude" / "mcp.json"
        connection = connection_for_envelope(self.execution_envelope, GLOBAL_SETTINGS)
        shell_cmd = self._runtime_adapter.build_command(
            task_file=task_file,
            requested_model=self.model,
            task_type=self.task_type,
            mcp_config=mcp_config,
            effort=self.effort,
            connection=connection,
        )

        env = {**os.environ}
        # Unset CLAUDECODE so workers can launch even when the orchestrator itself
        # is started from inside a Claude Code session (prevents "nested session" error)
        env.pop("CLAUDECODE", None)
        # Per-tool-call workspace checkpoints. The hook is inert without these,
        # so interactive sessions are untouched — only a worker asks for them.
        # The shadow repo lives OUTSIDE the worktree: a separate --git-dir means
        # a separate index, so it cannot contend with the worker's own commits.
        if self._shadow_repo_path() is not None:
            env["CLADE_WORKER_SHADOW_DIR"] = str(self._shadow_repo_path())
            env["CLADE_WORKER_WORKTREE"] = str(self._project_dir)
        # Spawn-time env denylist: strips secrets an untrusted-text worker shouldn't read. Off by default.
        # Patterns, not an enumeration: a hand-listed set of secret names goes
        # stale the moment a new one appears, and a stale denylist reads exactly
        # like a working one. fnmatch means `*_API_KEY` covers the key nobody
        # has added yet. Allow wins over deny, for the few the toolchain needs.
        _deny = _as_env_patterns(GLOBAL_SETTINGS.get("worker_env_deny"))
        _allow = _as_env_patterns(GLOBAL_SETTINGS.get("worker_env_allow"))
        for _key in list(env):
            if any(fnmatch.fnmatchcase(_key, p) for p in _deny) and not any(
                fnmatch.fnmatchcase(_key, p) for p in _allow
            ):
                env.pop(_key, None)
        self._runtime_adapter.apply_connection_env(connection, env)
        # The X-Clade-Task traceability trailer makes worker commits segmentable.
        env["CLADE_WORKER_TASK_ID"] = str(self.task_id)
        # Model provenance (Round-4 gap, Yegge pattern): record the primary model
        # for this spawn — CLADE_WORKER_TASK_ID alone can't tell you which model
        # wrote a given commit. committer.sh appends an Agent-Signature trailer
        # from this.
        # Adversarial-review finding (concurrency, MEDIUM): --fallback-model is a
        # NATIVE claude CLI behavior, switching model for an individual overloaded
        # TURN entirely inside the long-lived `claude -p` process — invisible to
        # this orchestrator. If a fallback fires on the exact turn that produces a
        # commit, the fallback model (not `model` below) actually wrote it, and
        # there is no hook available to know which turn that was. Disclose the
        # uncertainty in the trailer value itself rather than silently asserting
        # a single model name that may be wrong.
        model = self._runtime_adapter.resolve_model(self.model) or self.model
        env["CLADE_WORKER_MODEL"] = model
        _fb_model = _resolve_fallback_model(self.model)
        if _fb_model:
            env["CLADE_WORKER_MODEL"] = (
                f"{model} (fallback-configured: {_fb_model}, exact per-commit model not tracked)"
            )
        # Non-interactive git (mic92): rebase/amend/merge must never park an
        # unattended worker on an editor; `cat` accepts the default sequence and
        # prints it, so the rebase plan lands in the worker log.
        env.setdefault("GIT_EDITOR", "cat")
        env.setdefault("GIT_SEQUENCE_EDITOR", "cat")
        env.setdefault("GIT_PAGER", "cat")
        if GLOBAL_SETTINGS.get("agent_teams"):
            env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "1"

        return shell_cmd, env

    async def start(self, task_queue: TaskQueue | None = None) -> None:
        self._task_queue = task_queue
        if not await self._setup_worktree() and GLOBAL_SETTINGS.get("worker_require_worktree", True):
            raise RuntimeError(
                f"worktree isolation failed, refusing to run in the shared checkout: "
                f"{self._worktree_error}")
        task_file = await self._build_task_file(task_queue)
        shell_cmd, env = self._build_cmd_and_env(task_file)

        # Initialize Pi-style JSONL session tree for this worker
        tree_path = self._log_path.with_suffix(".tree.jsonl")
        self._session_tree = SessionTree(tree_path)
        self._session_tree.session_start({
            "worker_id": self.id,
            "task_id": self.task_id,
            "model": self.model,
            "agent_runtime": self.agent_runtime, "effort": self.effort, "route_reason": self.route_reason,
            "execution_envelope": (
                self.execution_envelope.to_dict()
                if self.execution_envelope
                else None
            ),
            "task_type": self.task_type,
            "description": self.description[:200],  # truncate for log
        })
        # Record the task description as the first user entry
        root_id = self._session_tree.user(self.description[:5000])

        await self._spawn_with_redacted_log(shell_cmd, env, append=False)
        self.pid = self.proc.pid
        try:
            self.pgid = os.getpgid(self.proc.pid)
        except ProcessLookupError:
            self.pgid = self.proc.pid
        # Persist pgid (survives a restart via setsid) so config._recover_orphaned_tasks
        # can reap it later; fire-and-forget, losing this write is non-fatal.
        if self._task_queue:
            asyncio.create_task(self._task_queue.update(self.task_id, pgid=self.pgid))
        _phase_from = self.status
        self.status = "running"
        self.transition_reason = "process_started"
        _phase_extra = {"worker_id": self.id}
        if GLOBAL_SETTINGS.get("phase_graph_validate", False):
            _phase_ok, _phase_reason = validate_transition(_phase_from, self.status)
            if not _phase_ok:
                _phase_extra.update(illegal=True, reason=_phase_reason)
                logger.warning("Illegal phase transition for task %s: %s", self.task_id, _phase_reason)
        _emit_phase = lambda event: self._event_stream.emit("state_change", "phase_transition", source="system", content=event)  # noqa: E731
        record_transition(_emit_phase, self.task_id, _phase_from, self.status, extra=_phase_extra)
        self._event_stream.emit(
            event_type="action",
            event_kind="tool_call",
            source="worker",
            content={"shell_cmd": shell_cmd[:500], "pid": self.pid},
        )
        self._task_span = start_task_span(self.id, self.description, self.task_id)
        await worker_evidence.append_worker_evidence(self, "running")

    async def _build_sandbox_plan(self) -> tuple[Any, dict]:
        """Compile the Landlock ruleset for this spawn, if one was asked for.

        Built in the parent so the forked child only pays a `prctl` plus one
        `landlock_restrict_self`; almost nothing is safe to do between fork and
        exec, and installing thousands of rules there would be.

        A `SandboxUnavailable` raised under `worker_sandbox_fail_closed`
        propagates and fails the spawn on purpose — the operator asked for
        confinement and did not get it.
        """
        enabled = bool(GLOBAL_SETTINGS.get("worker_sandbox", False))
        if not enabled:
            return None, worker_sandbox.describe(None, "worker_sandbox is off")
        common = await worker_evidence._git_common_dir(Path(self._project_dir))
        plan, shape = worker_sandbox.plan_for_git_surface(
            str(common) if common else None,
            enabled=True,
            fail_closed=bool(GLOBAL_SETTINGS.get("worker_sandbox_fail_closed", True)),
        )
        if plan is not None:
            logger.info(
                "Worker %s: sandboxed with %d Landlock rules (ABI %d), protecting %s",
                self.id, plan.rule_count, plan.abi, ", ".join(plan.protect),
            )
        return plan, shape

    async def _spawn_with_redacted_log(
        self, shell_cmd: str, env: dict[str, str], *, append: bool
    ) -> None:
        """Spawn provider output through the redaction boundary before disk."""
        if self._log_path is None:
            raise RuntimeError("worker log path must be initialized before spawn")
        plan, self._sandbox = await self._build_sandbox_plan()
        try:
            self.proc = await self._backend.spawn(
                shell_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                cwd=str(self._project_dir),
                preexec=plan.preexec() if plan else None,
            )
        finally:
            # The ruleset fd is inherited across fork and consumed before exec,
            # so it is dead weight in the parent the moment spawn returns.
            if plan is not None:
                plan.close()
        self._log_capture_task = asyncio.create_task(
            capture_provider_output(self.proc.stdout, self._log_path, append=append)
        )

    async def _finish_log_capture(self) -> None:
        task = self._log_capture_task
        if task is None:
            return
        self._log_capture_task = None
        try:
            await task
        except Exception:
            logger.exception("provider log capture failed for worker %s", self.id)

    def is_alive(self) -> bool:
        return self._backend.is_alive(self.proc)

    def _get_activity_state(self) -> str:
        """Activity state from Claude Code's session JSONL (Composio pattern).

        Logic lives in worker_utils._compute_activity_state (moved for the
        1500-line budget). Returns 'active'/'waiting_input'/'blocked'/'unknown'.
        Takes the RUN dir (worktree while active) — that is what Claude Code
        encodes into the transcript path, unlike the config dir passed before.
        """
        return _compute_activity_state(self._project_dir)

    def pause(self) -> None:
        if self.pgid and self.is_alive():
            try:
                os.killpg(self.pgid, signal.SIGSTOP)
                self.status = "paused"
            except ProcessLookupError:
                pass

    def resume(self) -> None:
        if self.pgid and self.status == "paused":
            try:
                os.killpg(self.pgid, signal.SIGCONT)
                self.status = "running"
            except ProcessLookupError:
                pass

    async def stop(self) -> None:
        if self.pgid and self.is_alive():
            # kill path routes through the execution backend; LocalSubprocessBackend
            # swallows ProcessLookupError (group already reaped) exactly as the
            # historical inline try/except did.
            self._backend.kill(self.pgid, signal.SIGTERM)
            await asyncio.sleep(0.5)
            if self.is_alive():
                self._backend.kill(self.pgid, signal.SIGKILL)
        await self._finish_log_capture()
        if self._finished_at is None:
            self._finished_at = time.time()
        self._verify_triggered = True  # prevent _on_worker_done from running after forced stop
        await preserve_worktree_wip(self._worktree_path, self._branch_name, "stopped")  # before force-remove
        await self._cleanup_worktree()

    async def poll(self) -> None:
        if not self.is_alive():
            await self._finish_log_capture()
            # Absorb usage + project events to prose before ANY log consumer.
            self._agent_result = absorb_agent_result(self._log_path)
            if self._finished_at is None:
                self._finished_at = time.time()
            rc = self.proc.returncode if self.proc else -1
            self.status = "done" if rc == 0 else "failed"
            self.transition_reason = f"process_exited_rc_{rc}"
            if self.status == "failed" and self._log_path and self._log_path.exists():
                try:
                    text = self._log_path.read_text(errors="replace")
                    self.failure_context = _truncate_output(text)
                    # Classify for richer failure_reason — pure logging, never
                    # changes retry control flow. Wrapped so any classifier
                    # exception falls back to plain failure_context.
                    try:
                        err = _classify_error(text, exit_code=rc)
                        self._failure_classified = err
                        self.failure_class = _summarize_error(err)
                        logger.info("Worker %s classified failure: %s",
                                    self.id, self.failure_class)
                    except Exception:
                        logger.debug("classify_error raised", exc_info=True)
                except Exception:
                    pass
            if not self._verify_triggered:
                self._verify_triggered = True
                asyncio.create_task(self._on_worker_done())
            elif self._worktree_path and self._worktree_path.exists():
                asyncio.create_task(self._cleanup_worktree())
            return

        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "log", "-1", "--oneline",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=str(self._project_dir),
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3)
            self.last_commit = stdout.decode().strip() or None
        except Exception:
            pass

        # Track activity state via Claude Code JSONL (Composio pattern)
        activity = self._get_activity_state()
        self._event_stream.emit(
            event_type="observation",
            event_kind="llm_call",
            source="worker",
            content={"activity_state": activity},
        )

        # Track turn for loop detection (Gemini CLI pattern)
        self._loop_detector.track_turn()

        # Emit activity to reaction executor
        triggered = self._reaction_executor.record_event(
            "state_change",
            event_name=f"poll:{activity}",
            event_content=activity,
        )
        for reaction in triggered:
            logger.warning(
                "Worker %s reaction triggered: %s — %s",
                self.id, reaction.config.name, reaction.message
            )

    def _shadow_repo_path(self) -> Path | None:
        """Where this worker's per-tool-call checkpoints live, or None if off."""
        if not GLOBAL_SETTINGS.get("worker_checkpoint_shadow", True):
            return None
        if not self._worktree_path:
            return None
        return self._claude_dir / "orchestrator-worktrees" / ".shadow" / f"{self.id}.git"

    async def _cleanup_worktree(self) -> None:
        if not self._worktree_path:
            return
        # Remove the checkpoint history with the worktree it describes. Kept
        # first so a failure below cannot strand it; the final SHA is already
        # in the evidence bundle by this point.
        shadow = self._shadow_repo_path()
        if shadow is not None and shadow.exists():
            try:
                shutil.rmtree(shadow)
            except OSError:
                logger.warning("could not remove checkpoint repo %s", shadow)
        cleanup = await asyncio.create_subprocess_exec(
            "git", "worktree", "remove", "--force", str(self._worktree_path),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            cwd=str(self._original_project_dir),
        )
        try:
            await asyncio.wait_for(cleanup.communicate(), timeout=15)
        except Exception:
            pass
        self._worktree_path = None
        self._project_dir = self._original_project_dir  # restore so git cmds still work

    async def _on_worker_done(self) -> None:
        """Run after process exits: verify+commit while worktree is still alive, then clean up."""
        # Write session tree completion entry (Pi-style append-only record)
        if self._session_tree:
            try:
                self._session_tree._write({
                    "type": "worker_done",
                    "status": self.status,
                    "verified": self.verified,
                    "auto_committed": self.auto_committed,
                    "elapsed_s": round(time.time() - self.started_at, 1),
                    "input_tokens": getattr(self, "_input_tokens", None),
                    "output_tokens": getattr(self, "_output_tokens", None),
                    "estimated_cost": getattr(self, "_estimated_cost", None),
                    "failure_context": self.failure_context[:500] if self.failure_context else None,
                })
            except Exception:
                pass
        # Emit completion event to EventStream
        self._event_stream.emit(
            event_type="state_change",
            event_kind="state_change",
            source="supervisor",
            content={
                "state": "done",
                "status": self.status,
                "verified": self.verified,
                "elapsed_s": round(time.time() - self.started_at, 1),
            },
        )
        if self.status == "failed" and self.failure_context:
            triggered = self._reaction_executor.record_event(
                "error",
                event_name="worker_failed",
                event_content=self.failure_context[:500],
            )
            for reaction in triggered:
                logger.warning("Worker %s reaction: %s — %s", self.id, reaction.config.name, reaction.message)
        elif self.status == "done":
            self._reaction_executor.record_event("state_change", event_name="worker_done")

        if self._task_span:
            svc = TracingService.get_instance()
            svc.end_span(self.id, self._task_span,
                         status="ok" if self.status == "done" else "error")
            svc.write_trace(self.id)
            self._task_span = None

        if self.status == "done":
            try:
                verified = await worker_evidence.verify_worker_with_evidence(self)
            except Exception:
                logger.exception("verify_and_commit failed for worker %s", self.id)
                verified = False
            # Reflection loop (Aider pattern): if verification failed, run lint check and retry
            # Token budget gate: parse current usage first; skip retry if budget exceeded.
            _current_tokens = 0
            if self.token_budget > 0:
                _in, _out, _ = resolve_worker_usage(self._agent_result, self._log_path, self.model)
                _current_tokens = _in + _out
            _budget_ok = (self.token_budget == 0 or _current_tokens < self.token_budget)
            if not verified and self._reflection_retries < MAX_REFLECTION_RETRIES and _budget_ok and not (self._test_requeue or self._ownership_violation or self._oracle_requeue):
                try:
                    lint_output = await _run_lint_check(self._project_dir)
                    if lint_output:
                        self._reflection_retries += 1
                        logger.info(
                            "Worker %s: reflection retry %d/%d — lint errors found, re-running with context",
                            self.id, self._reflection_retries, MAX_REFLECTION_RETRIES
                        )
                        # Reflexion pattern: accumulate failure note and prepend history
                        stripped = _strip_error_context(lint_output)
                        failure_note = f"Retry {self._reflection_retries}: {stripped[:300]}"
                        self._failure_reflections.append(failure_note)
                        history_lines = "\n".join(
                            f"  - {n}" for n in self._failure_reflections[-3:]
                        )
                        # Recursive Debugging pattern: parse specific file:line:error locations
                        # to generate targeted fix directives instead of dumping all lint output.
                        lint_targets = _extract_lint_targets(lint_output)
                        if lint_targets:
                            targeted = (
                                "Fix ONLY these specific errors (do not modify anything else):\n"
                                + "\n".join(f"  • {t}" for t in lint_targets)
                                + "\n"
                            )
                        else:
                            targeted = ""
                        # Inject lint output + episodic failure history as additional context
                        retry_context = (
                            f"Previous attempts failed:\n{history_lines}\n\n"
                            f"Your previous edit introduced lint/verification errors. Fix them now.\n\n"
                            f"{targeted}"
                            f"Full lint output:\n{lint_output[:3000]}\n"
                        )
                        # AutoCodeRover pattern: use --continue to preserve session context.
                        # Agent remembers which files it edited, so we only send the error.
                        retry_success = await self._run_with_context(retry_context, use_continue=True)
                        if retry_success:
                            self.status = "done"
                            self.transition_reason = "lint_retry_success"
                            self._loop_detector._loop_detected = False  # reset loop detection on retry
                            self._reflection_retries = 0  # reset on success
                            self._failure_reflections.clear()  # clear episodic memory on success
                except Exception:
                    pass
        # Parse token usage from log and enforce token budget
        if self._log_path and self._log_path.exists():
            try:
                self._input_tokens, self._output_tokens, self._estimated_cost = resolve_worker_usage(self._agent_result, self._log_path, self.model)
                total_tokens = self._input_tokens + self._output_tokens
                if self.token_budget > 0 and total_tokens > self.token_budget and self.status != "done":
                    self.status = "failed"
                    self.transition_reason = "token_budget_exceeded"
                    self.failure_context = (
                        f"Token budget exceeded: {total_tokens:,} tokens used, "
                        f"budget was {self.token_budget:,}"
                    )
                    logger.warning(
                        "Worker %s: token budget exceeded (%d > %d)",
                        self.id, total_tokens, self.token_budget
                    )
            except Exception:
                pass
            # Distill large output: replace log in-place with LLM summary + full output reference
            # This preserves error details that simple truncation loses
            if self._project_dir:
                try:
                    log_size = self._log_path.stat().st_size
                    if log_size > DISTILL_THRESHOLD:
                        raw_text = self._log_path.read_text(errors="replace")
                        distilled = await _distill_output(raw_text, self._project_dir)
                        self._log_path.write_text(distilled, encoding="utf-8")
                        logger.info("Worker %s: distilled %dKB log to %d chars",
                                     self.id, log_size // 1024, len(distilled))
                except Exception:
                    pass
        # NOTE: project tests + intramorphic check moved INTO verify_and_commit
        # (mic92: evidence before verdict — they now run before oracle gate + push).
        # Parse structured observation contract; extract summary directly if present.
        _obs_summary: str | None = None
        if self._log_path and self._log_path.exists():
            try:
                obs = _parse_observation_contract(
                    self._log_path.read_text(errors="replace")
                )
                if obs:
                    _obs_summary = obs.get("summary", "")[:150] or None
                    if obs.get("status") == "blocked" and _obs_summary and not self.failure_context:
                        self.failure_context = f"Worker blocked: {_obs_summary}"
            except Exception:
                pass
        # Completion summary: prefer obs contract, fall back to haiku summarization.
        if self.auto_committed and self._project_dir:
            try:
                if _obs_summary:
                    self.completion_summary = _obs_summary
                else:
                    self.completion_summary = await _summarize_worker_completion(
                        self.description, self._log_path, self._project_dir
                    )
                logger.debug("Worker %s completion summary: %s", self.id, self.completion_summary)
            except Exception:
                pass
        if self.auto_committed and self._task_queue:  # bidirectional dep clear (learn-cc s12)
            try: await self._task_queue.clear_completed_dep(self.task_id)
            except Exception as e: logger.warning("Worker %s dep clear failed: %s", self.id, e)
        # Check for handoff file — worker wrote it to signal continuation needed
        handoff_path = self._claude_dir / f"handoff-{self.task_id}.md"
        if handoff_path.exists():
            try:
                self._handoff_content = handoff_path.read_text(errors="replace").strip()
                self._handoff_requeue = bool(self._handoff_content)
                handoff_path.unlink(missing_ok=True)
                logger.info("Handoff file found for task %s — flagging for continuation", self.task_id)
            except Exception:
                pass
        await worker_evidence.append_worker_terminal_evidence(self)
        self._event_stream.emit(
            event_type="state_change",
            event_kind="worker_envelope",
            source="worker",
            content=build_from_worker(self).to_dict(),
        )
        await self._cleanup_worktree()

    def _check_file_ownership(self, changed_files: list[str]) -> tuple[bool, str]:
        """Check changed files against own_files/forbidden_files globs. Returns (ok, reason).

        Glob logic lives in worker_utils._check_file_ownership (moved for the
        1500-line budget).
        """
        return cascade_policy.scope_result(_check_ownership_globs(changed_files, self.own_files, self.forbidden_files), route_reason=self.route_reason, changed_files=changed_files, max_files=cascade_policy.max_changed_files(GLOBAL_SETTINGS))

    async def verify_and_commit(self) -> bool:
        diff_proc = await asyncio.create_subprocess_exec(
            "git", "diff", "--name-only", "HEAD",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            cwd=str(self._project_dir),
        )
        try:
            stdout, _ = await asyncio.wait_for(diff_proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            diff_proc.kill()
            await diff_proc.communicate()
            return False
        except Exception:
            return False
        untracked_proc = await asyncio.create_subprocess_exec(
            "git", "ls-files", "--others", "--exclude-standard",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            cwd=str(self._project_dir),
        )
        try:
            ut_out, _ = await asyncio.wait_for(untracked_proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            untracked_proc.kill()
            await untracked_proc.communicate()
            return False
        except Exception:
            return False
        changed_files = [
            f for f in (stdout.decode().strip() + "\n" + ut_out.decode().strip()).splitlines()
            if f.strip()
        ]
        if not changed_files:
            if cascade_policy.is_cheap_route(self.route_reason):
                self._test_requeue, self._test_requeue_reason = True, "No diff produced by cheap attempt"
            return False

        # Agent-Fingerprint: record whether the diff includes test files (a
        # quality + merge-rate signal, surfaced in the PR body).
        self.tests_added = [f for f in changed_files if _is_test_file(f)]

        # File ownership enforcement
        ok, reason = self._check_file_ownership(changed_files)
        if not ok:
            self._ownership_violation = True
            self._ownership_violation_reason = reason
            # Discard all changes in worktree
            discard = await asyncio.create_subprocess_exec(
                "git", "checkout", ".",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                cwd=str(self._project_dir),
            )
            try:
                await asyncio.wait_for(discard.communicate(), timeout=10)
            except Exception:
                pass
            clean = await asyncio.create_subprocess_exec(
                "git", "clean", "-fd",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                cwd=str(self._project_dir),
            )
            try:
                await asyncio.wait_for(clean.communicate(), timeout=10)
            except Exception:
                pass
            return False

        diff_summary_proc = await asyncio.create_subprocess_exec(
            "git", "diff", "HEAD", "--stat",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            cwd=str(self._project_dir),
        )
        try:
            diff_out, _ = await asyncio.wait_for(diff_summary_proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            diff_summary_proc.kill()
            await diff_summary_proc.communicate()
            return False

        task_first_line = self.description.splitlines()[0][:80]
        verify_prompt = (
            f"Task was: {task_first_line}\n\n"
            f"Git diff stat:\n{diff_out.decode()}\n\n"
            "If the changes look complete and correct for the task, output exactly: VERIFIED_OK\n"
            "If there are obvious issues or nothing was changed, output: VERIFIED_FAIL: <reason>\n"
            "Output ONLY one of those two responses, nothing else."
        )

        verify_file = self._claude_dir / f"verify-{self.id}.md"
        verify_file.write_text(verify_prompt)
        try:
            # Pure judge (VERIFIED_OK/FAIL parsed from stdout) — drop user settings.
            verify_proc = await asyncio.create_subprocess_shell(
                f'claude -p "$(cat {shlex.quote(str(verify_file))})" --model {HAIKU_MODEL} '
                f'--dangerously-skip-permissions {SETTING_SOURCES_NONE} {DISALLOWED_TOOLS_JUDGE}',
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                cwd=str(self._project_dir),
            )
            try:
                v_out, _ = await asyncio.wait_for(verify_proc.communicate(), timeout=120)
                result = v_out.decode().strip()
            except asyncio.TimeoutError:
                verify_proc.kill()
                await verify_proc.communicate()
                return False
        finally:
            verify_file.unlink(missing_ok=True)

        if "VERIFIED_OK" not in result:
            return False

        self.verified = True

        commit_msg = f"{_infer_commit_type(self.description)}: {task_first_line.lower()}"
        files_arg = " ".join(shlex.quote(f) for f in changed_files[:20])
        committer_path = Path.home() / ".claude/scripts/committer.sh"
        if committer_path.exists():
            commit_cmd = (
                f'bash {shlex.quote(str(committer_path))} '
                f'{shlex.quote(commit_msg)} {files_arg}'
            )
        else:
            # Bare-git fallback runs the same staged-secret scan committer.sh
            # gets from checks.sh (fail-closed, CLADE_ALLOW_SECRETS=1 overrides)
            commit_cmd = _fallback_commit_cmd(commit_msg, files_arg, str(self.task_id))
        commit_proc = await asyncio.create_subprocess_shell(
            commit_cmd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(self._project_dir),
            # committer.sh adds attribution trailers when this is set
            env={**os.environ, "CLADE_WORKER_TASK_ID": str(self.task_id)},
        )
        try:
            c_out, c_err = await asyncio.wait_for(commit_proc.communicate(), timeout=30)
            if commit_proc.returncode == 0:
                self.auto_committed = True

                # Evidence before verdict (mic92): run project tests + intramorphic
                # regression check BEFORE the oracle gate and BEFORE auto_push.
                # On failure: undo the commit, skip push, requeue with the output.
                test_evidence = ""
                try:
                    tests_passed, test_output = await _run_project_tests(self._project_dir, config_dir=self._original_project_dir, fail_closed=cascade_policy.is_cheap_route(self.route_reason))
                    reg_warning = await _run_intramorphic_check(
                        self._project_dir, self._claude_dir, test_output, self.task_id
                    )
                    # Agentless §6B validation half: re-run the confirmed-failing repro
                    # against the fix. The project suite can't catch an unfixed bug it
                    # has no test for; the repro can. Result always feeds oracle evidence;
                    # hard-block only when repro_test_gate is set (default off, advisory).
                    repro_passed, repro_output = await _run_repro_filter(
                        self._project_dir, self._claude_dir, self.task_id
                    )
                    test_evidence = _build_test_evidence(tests_passed, test_output, reg_warning)
                    # Record the test outcome NOW. It used to reach disk only in
                    # the terminal append, so a crash before the oracle returned
                    # lost the fact that tests had already passed.
                    await worker_evidence.append_worker_evidence(
                        self, "verifying", phase="tests",
                        passed=tests_passed, repro_passed=repro_passed,
                    )
                    if repro_passed is not None:
                        test_evidence += (
                            "\nReproduction test: "
                            + ("PASSED ✓ (bug verified fixed)" if repro_passed
                               else "STILL FAILING ✗ (fix did not resolve the bug)")
                        )
                    if not tests_passed:
                        logger.warning(
                            "Worker %s: pre-push tests FAILED — commit undone, push skipped:\n%s",
                            self.id, test_output[:500]
                        )
                        await self._undo_commit()
                        self.auto_committed = False
                        self.failure_context = f"Pre-push tests failed:\n{test_output[:300]}"
                        self._test_requeue = True
                        self._test_requeue_reason = test_evidence or test_output
                        return False
                    if repro_passed is False and GLOBAL_SETTINGS.get("repro_test_gate", False):
                        logger.warning(
                            "Worker %s: reproduction test STILL FAILING after fix — commit undone",
                            self.id
                        )
                        await self._undo_commit()
                        self.auto_committed = False
                        self.failure_context = (
                            f"Reproduction test still failing after fix:\n{repro_output[:300]}"
                        )
                        self._test_requeue = True
                        self._test_requeue_reason = test_evidence
                        return False
                    if reg_warning:
                        logger.warning("Worker %s: %s", self.id, reg_warning)
                        self.failure_context = (
                            f"{self.failure_context}\n{reg_warning}" if self.failure_context
                            else reg_warning
                        )
                except Exception:
                    pass  # fail-open: a broken test runner must not block commits
                self.test_evidence = test_evidence  # surfaced later in the PR body

                # Oracle validation gate (rejection requeues; infra errors tag 'unreviewed')
                oracle_ok = await self._run_oracle_gate(test_evidence)
                await worker_evidence.append_worker_evidence(
                    self, "verifying", phase="oracle",
                    verdict=self.oracle_result, reason=self.oracle_reason,
                )
                if not oracle_ok:
                    return False

                branch = f"orchestrator/task-{self.task_id}"
                self.branch_name = branch
                if GLOBAL_SETTINGS.get("auto_push", True):
                    push_proc = await asyncio.create_subprocess_shell(
                        f'git push origin HEAD:{branch} --force-with-lease',
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                        cwd=str(self._project_dir),
                    )
                    try:
                        p_out, p_err = await asyncio.wait_for(push_proc.communicate(), timeout=30)
                        if push_proc.returncode == 0:
                            self.auto_pushed = True
                        await worker_evidence.append_worker_evidence(
                            self, "verifying", phase="push",
                            pushed=self.auto_pushed, branch=branch,
                        )
                    except asyncio.TimeoutError:
                        push_proc.kill()
                        await push_proc.communicate()

                log_proc = await asyncio.create_subprocess_exec(
                    "git", "log", "-1", "--oneline",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    cwd=str(self._project_dir),
                )
                try:
                    log_out, _ = await asyncio.wait_for(log_proc.communicate(), timeout=5)
                    self.last_commit = log_out.decode().strip() or self.last_commit
                except asyncio.TimeoutError:
                    log_proc.kill()
                    await log_proc.communicate()
        except asyncio.TimeoutError:
            pass
        return self.auto_committed

    async def _undo_commit(self) -> None:
        """git reset HEAD~1 — undo the just-made commit so it cannot be pushed later."""
        await _undo_last_commit(self._project_dir)

    async def _persist_oracle_result(self) -> None:
        """Write oracle_result/oracle_reason to the DB row the moment they're
        computed. poll_all's terminal-persist block runs synchronously right
        after the subprocess exits and can complete BEFORE this async oracle
        gate finishes, so persistence can't be deferred to that block — a
        consumer (session.py:_run_plan_build) reads this column to decide
        whether a plan checklist item may be marked done."""
        if not self._task_queue:
            return
        try:
            await self._task_queue.update(
                self.task_id, oracle_result=self.oracle_result, oracle_reason=self.oracle_reason,
            )
        except Exception:
            pass

    async def _run_oracle_gate(self, test_evidence: str = "") -> bool:
        """Oracle validation gate. Returns False when the commit was rejected (undone + flagged for requeue).

        Oracle liveness (lovesegfault): infra failures (timeout/subprocess error/
        unparseable output) tag oracle_result='unreviewed' — never a silent
        approval. After _ORACLE_INFRA_THRESHOLD consecutive infra errors, the
        outage escalates via notification webhook + .claude/blockers.md.
        test_evidence (mic92): pre-push test results shown to the grader.
        """
        if not GLOBAL_SETTINGS.get("auto_oracle", False):
            return True
        try:
            diff_proc = await asyncio.create_subprocess_exec(
                "git", "diff", "HEAD~1", "HEAD",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                cwd=str(self._project_dir),
            )
            diff_out, _ = await asyncio.wait_for(diff_proc.communicate(), timeout=15)
            self.eval_diff = diff_out.decode()
            criteria = _parse_task_schema(self.description).get("acceptance_criteria") or None
            constitution = _read_constitution(self._project_dir)
            # Resample the verdict K× and require a clean majority to approve; a bad
            # config value degrades to single-shot rather than crashing to fail-open.
            try:
                verdict_samples = max(1, int(GLOBAL_SETTINGS.get("oracle_verdict_samples", 1) or 1))
            except (TypeError, ValueError):
                verdict_samples = 1
            # Task-class-aware override (judgment-heavy 'generate' tasks get more
            # scrutiny up front than mechanical 'transform' ones), same precedence
            # pattern as task_type_model_routing — only applies when configured.
            class_map = GLOBAL_SETTINGS.get("task_class_resampling") or {}
            if class_map:
                task_class = _parse_task_class(self.description)
                if task_class in class_map:
                    try:
                        verdict_samples = max(1, int(class_map[task_class]))
                    except (TypeError, ValueError):
                        pass
            approved, reason, infra_error = await _oracle_review(
                self.description, diff_out.decode(), self._claude_dir,
                acceptance_criteria=criteria, test_evidence=test_evidence,
                constitution=constitution, verdict_samples=verdict_samples,
            )
        except Exception:
            approved, reason, infra_error = True, "oracle gate error", True
        if infra_error:
            # Fail-open (commit survives) but visibly unreviewed, with escalation
            self.oracle_result = "unreviewed"
            self.oracle_reason = reason
            await self._persist_oracle_result()
            try:
                streak = _record_oracle_infra_error(self._claude_dir)
                if streak and streak % _ORACLE_INFRA_THRESHOLD == 0:
                    await _escalate_oracle_outage(
                        self._project_dir, self._claude_dir,
                        GLOBAL_SETTINGS.get("notification_webhook", ""), streak,
                    )
            except Exception:
                pass  # escalation must never break the commit flow
            return await cascade_policy.handle_unreliable(self)
        _reset_oracle_infra_streak(self._claude_dir)
        self.oracle_result = "approved" if approved else "rejected"
        self.oracle_reason = reason
        await self._persist_oracle_result()
        agreement = None
        if GLOBAL_SETTINGS.get("judge_diversity_enabled", False):
            try:
                diversity = await asyncio.to_thread(
                    judge_diversity.deterministic_checks, self._project_dir,
                    judge_diversity.changed_files_from_diff(diff_out.decode()))
            except Exception as exc:
                diversity = judge_diversity.check_error(exc)
            agreement = judge_diversity.oracle_agreement(approved, diversity)
            self.judge_agreement = agreement
            logger.info("Worker %s judge diversity: agreement=%s evidence=%s", self.id, agreement, diversity)
            self._event_stream.emit(
                event_type="state_change", event_kind="judge_diversity", source="system",
                content={"oracle_result": self.oracle_result, "agreement": agreement,
                         "diversity": diversity})
        if approved:
            if (GLOBAL_SETTINGS.get("judge_diversity_block", False) or cascade_policy.is_cheap_route(self.route_reason)) and agreement == "oracle-lenient":
                block_reason = "Deterministic review failed despite oracle approval"
                await self._undo_commit()
                self.auto_committed = False
                self._oracle_requeue = True
                self._oracle_requeue_reason = block_reason
                return False
            return True
        # Undo the commit so rejected work is not accidentally pushed later
        await self._undo_commit()
        self.auto_committed = False
        # Flag for requeue — poll_all will pick this up
        self._oracle_requeue = True
        self._oracle_requeue_reason = reason
        return False

    async def _run_with_context(self, extra_context: str, use_continue: bool = False) -> bool:
        """Re-run the worker with additional context injected (used by reflection loop).

        Runs in the SAME worktree with a new task file that appends extra_context.
        When use_continue=True, uses --continue to preserve the previous session's
        context (agent remembers files it read/modified). Falls back to fresh start
        if --continue fails (AutoCodeRover inline retry pattern).

        Returns True if the re-run succeeded (commit made).
        """
        if not self._project_dir or not self._worktree_path:
            return False
        task_file = self._claude_dir / f"task-{self.id}-retry{self._reflection_retries}.md"

        _continue_cmd = (
            self._runtime_adapter.build_continue_command(
                task_file=task_file, requested_model=self.model, effort=self.effort
            )
            if use_continue else None
        )
        if _continue_cmd is not None:
            # --continue preserves agent context; send only the follow-up context, not
            # the full task. Providers without a continue equivalent (codex) return
            # None -> a fresh retry with the full task + context (the else branch).
            task_file.write_text(extra_context.strip(), encoding="utf-8")
            shell_cmd = _continue_cmd
        else:
            retry_desc = self.description + f"\n\n{extra_context}"
            task_file.write_text(retry_desc, encoding="utf-8")
            shell_cmd, _ = self._build_cmd_and_env(task_file)

        _, env = self._build_cmd_and_env(task_file)

        try:
            await self._spawn_with_redacted_log(shell_cmd, env, append=True)
            self.pid = self.proc.pid
            self.status = "running"
            self._finished_at = None
            self.started_at = time.time()
            # Wait for completion (simple wait, no polling)
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=self.task_timeout)
            except asyncio.TimeoutError:
                self.proc.kill()
                await self.proc.wait()
            await self._finish_log_capture()
            rc = self.proc.returncode if self.proc else -1
            self.status = "done" if rc == 0 else "failed"
            if self.status == "done":
                return await self.verify_and_commit()
            # If --continue failed (e.g. no prior session), fall back to full restart
            if use_continue and not self.auto_committed:
                logger.info("Worker %s: --continue failed, falling back to full restart", self.id)
                return await self._run_with_context(extra_context, use_continue=False)
            return False
        except Exception:
            await self._finish_log_capture()
            return False


# Auto-classify retry helper lives in worker_utils.py and is re-exported above.


# ─── Worker Pool ──────────────────────────────────────────────────────────────


# ─── Swarm Manager ────────────────────────────────────────────────────────────


# SwarmManager moved to swarm.py
from swarm import SwarmManager

# WorkerPool moved to worker_pool.py — same seam, same reason: this file had
# reached the 1500-line ceiling exactly, so every change to it started by
# reclaiming a line. Imported at the bottom so worker_pool's lazy `from worker
# import Worker` resolves against a fully-loaded module.
from worker_pool import WorkerPool as _BaseWorkerPool


class WorkerPool(_BaseWorkerPool):
    """The pool, bound to THIS module's Worker.

    Test suites load worker.py privately (importlib) to bind a real
    worker_review past conftest's mocks. Subclassing here keeps that isolation:
    a private copy of this module gets a pool that builds its own Worker.
    """

    worker_cls = Worker

    def _requeue_handlers(self):
        """This module's bindings, looked up per call.

        Suites that privately load worker.py rebind these names on the module;
        resolving here rather than in worker_pool keeps that working.
        """
        return {
            "oracle": handle_oracle_requeue,
            "test": handle_test_requeue,
            "ownership": handle_ownership_requeue,
            "handoff": handle_handoff_requeue,
        }
