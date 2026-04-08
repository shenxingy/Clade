"""
Orchestrator worker — execution engine.
Worker, WorkerPool.
SwarmManager is in swarm.py.

Extracted modules (keep worker.py under 1500 lines):
- condensers.py      — Condenser ABC + 4 implementations
- worker_utils.py    — output helpers, lint reflection, LoopDetectionService
- worker_hydrate.py  — _pre_hydrate (Stripe Blueprint pre-hydration)
- config.py          — _build_tool_flags, _parse_task_type, _TOOL_SUBSETS
- worker_tldr.py     — _generate_code_tldr, _score_task
- worker_review.py   — _oracle_review, _write_pr_review
- github_sync.py     — GitHub CLI wrappers
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
import os
import re
import shlex
import signal
import time
import uuid
from pathlib import Path
from typing import Any

from config import (
    GLOBAL_SETTINGS,
    _MODEL_ALIASES,
    _estimate_cost,
    _parse_token_usage,
    _build_tool_flags,
    _parse_task_type,
    _parse_task_schema,
    _format_task_schema_block,
)
from task_queue import TaskQueue
from github_sync import _gh_update_issue_status
from session_tree import SessionTree
from worker_tldr import (
    _generate_code_tldr, _localize_tldr_for_task, _localize_fault,
    _prune_tldr_to_entities, _parse_fault_entity_names,
    _generate_repro_test, _sbfl_prepass, _span_evict_tldr,
)
from worker_review import _oracle_review, _summarize_worker_completion
from event_stream import EventStream
from tracing import TracingService, start_task_span
from reactions import ReactionExecutor
from condensers import ObservationMaskingCondenser
from worker_utils import (
    _distill_output, _truncate_output, _strip_error_context,
    _run_lint_check, _extract_lint_targets, _run_project_tests, LoopDetectionService,
    _capture_test_baseline, _run_intramorphic_check, _rank_tasks,
    _parse_observation_contract,
    MAX_LINES, MAX_BYTES, DISTILL_THRESHOLD, MAX_REFLECTION_RETRIES,
    EDIT_DISCIPLINE_BLOCK, SEARCH_CONVENTIONS_BLOCK, COMPLETION_CONTRACT_BLOCK,
)
from worker_hydrate import _pre_hydrate

logger = logging.getLogger(__name__)

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
    ):
        self.id = str(uuid.uuid4())[:8]
        self.task_id = task_id
        self.description = description
        self.model = model
        self._project_dir = project_dir
        self.task_type = task_type or _parse_task_type(description)
        self._original_project_dir = project_dir  # preserved for restore after worktree cleanup
        self._claude_dir = claude_dir
        self.proc: asyncio.subprocess.Process | None = None
        self.pgid: int | None = None
        self.pid: int | None = None
        self.started_at = time.time()
        self._finished_at: float | None = None
        self.status = "starting"  # starting/running/paused/blocked/done/failed
        self.transition_reason: str = "initialized"  # learn-cc s00a: Query Control Plane
        self.last_commit: str | None = None
        self.log_file: str | None = None
        self._log_path: Path | None = None
        self._session_tree: SessionTree | None = None  # Pi-style JSONL session tree
        self.verified: bool = False
        self.auto_committed: bool = False
        self.auto_pushed: bool = False
        self.oracle_result: str | None = None
        self.oracle_reason: str | None = None
        self._oracle_requeue: bool = False
        self._oracle_requeue_reason: str | None = None
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
        self._worktree_path: Path | None = None
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
        log_tail = ""
        if self._log_path and self._log_path.exists():
            try:
                text = self._log_path.read_text(errors="replace")
                log_tail = _truncate_output(text, max_lines=4, max_bytes=4096)
            except Exception:
                pass
        return {
            "id": self.id,
            "task_id": self.task_id,
            "description": self.description[:80],
            "model": self.model,
            "status": self.status,
            "pid": self.pid,
            "elapsed_s": self.elapsed_s,
            "last_commit": self.last_commit,
            "log_file": self.log_file,
            "verified": self.verified,
            "auto_committed": self.auto_committed,
            "auto_pushed": self.auto_pushed,
            "branch_name": self.branch_name,
            "pr_url": self.pr_url,
            "pr_merged": self.pr_merged,
            "log_tail": log_tail,
            "failure_context": self.failure_context,
            "worktree_path": str(self._worktree_path) if self._worktree_path else None,
            "oracle_result": self.oracle_result,
            "oracle_reason": self.oracle_reason,
            "transition_reason": self.transition_reason,
            "completion_summary": self.completion_summary,
            "model_score": self.model_score,
            "estimated_tokens": self._estimate_tokens(),
            "context_warning": self._estimate_tokens() > 160000,
            "input_tokens": self._input_tokens,
            "output_tokens": self._output_tokens,
            "estimated_cost": self._estimated_cost,
            "loop_detected": self._loop_detector.is_looping,
            "loop_reason": self._loop_detector.reason,
        }

    def _estimate_tokens(self) -> int:
        desc_tokens = len(self.description) // 4
        log_tokens = 0
        if self._log_path and self._log_path.exists():
            try:
                log_tokens = self._log_path.stat().st_size // 4
            except Exception:
                pass
        return desc_tokens + log_tokens

    async def _setup_worktree(self) -> None:
        """Create an isolated git worktree for this worker. Updates self._project_dir on success."""
        worktree_base = self._claude_dir / "worktrees"
        worktree_base.mkdir(parents=True, exist_ok=True)
        self._worktree_path = worktree_base / f"worker-{self.id}"
        self._branch_name = f"orchestrator/task-{self.task_id}"

        wt_proc = await asyncio.create_subprocess_exec(
            "git", "worktree", "add", str(self._worktree_path), "-b", self._branch_name,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(self._project_dir),
        )
        try:
            wt_out, wt_err = await asyncio.wait_for(wt_proc.communicate(), timeout=30)
            if wt_proc.returncode == 0:
                self._project_dir = self._worktree_path
            else:
                try:
                    wt_proc2 = await asyncio.create_subprocess_exec(
                        "git", "worktree", "add", str(self._worktree_path), self._branch_name,
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                        cwd=str(self._project_dir),
                    )
                    try:
                        await asyncio.wait_for(wt_proc2.communicate(), timeout=30)
                    except asyncio.TimeoutError:
                        wt_proc2.kill()
                        await wt_proc2.communicate()
                    if wt_proc2.returncode == 0:
                        self._project_dir = self._worktree_path
                    else:
                        self._worktree_path = None
                except Exception:
                    self._worktree_path = None
        except asyncio.TimeoutError:
            wt_proc.kill()
            await wt_proc.communicate()
            self._worktree_path = None
        except Exception:
            self._worktree_path = None

    async def _build_task_file(self, task_queue: TaskQueue | None) -> Path:
        """Set up log path and write the task file with injected context. Returns task file path."""
        logs = self._claude_dir / "orchestrator-logs"
        logs.mkdir(parents=True, exist_ok=True)
        self._log_path = logs / f"worker-{self.id}.log"
        self.log_file = str(self._log_path)

        # Initialize EventStream JSONL path for crash-safe event logging
        jsonl_path = logs / f"events-{self.id}.jsonl"
        self._event_stream.set_jsonl_path(jsonl_path)
        self._event_stream.emit(
            event_type="state_change",
            event_kind="state_change",
            source="supervisor",
            content={"state": "started", "task_id": self.task_id, "model": self.model},
        )

        task_file = self._claude_dir / f"task-{self.id}.md"
        task_file.parent.mkdir(parents=True, exist_ok=True)

        # Prepend project CLAUDE.md + AGENTS.md for context injection
        effective_description = self.description
        context_blocks = []
        claude_md = self._claude_dir / "CLAUDE.md"
        if claude_md.exists():
            try:
                claude_content = claude_md.read_text(errors="replace").strip()
                if claude_content:
                    context_blocks.append(f"# Project Context (from .claude/CLAUDE.md)\n\n{claude_content}")
            except Exception:
                pass
        agents_md = self._claude_dir / "AGENTS.md"
        if not agents_md.exists():
            agents_md = self._project_dir / "AGENTS.md"
        if agents_md.exists():
            try:
                agents_content = agents_md.read_text(errors="replace").strip()
                if agents_content:
                    context_blocks.append(f"# File Ownership (from AGENTS.md)\n\n{agents_content}")
            except Exception:
                pass
        try:
            tldr = _generate_code_tldr(str(self._original_project_dir))
            if tldr:
                # Two-phase localization (Moatless pattern): when TLDR is large,
                # ask haiku to narrow to the top-5 most relevant files for this task.
                if len(tldr) > 4096:
                    tldr = await _localize_tldr_for_task(
                        self.description, tldr, self._original_project_dir
                    )
                # Fault localization pre-pass (Agentless §6A): for fix/bug tasks,
                # predict likely change locations to tighten worker focus.
                # Run before appending TLDR so we can entity-prune it (Sweep §Gap1).
                task_type = _parse_task_type(self.description)
                fault_locs = ""
                if task_type == "fix":
                    fault_locs = await _localize_fault(
                        self.description, tldr, self._original_project_dir
                    )
                    if fault_locs:
                        # Sweep §Gap1: entity-level TLDR pruning.
                        # Use suspect_functions from fault localization to filter
                        # TLDR down to only the relevant entities in each file.
                        entity_names = _parse_fault_entity_names(fault_locs)
                        if entity_names:
                            tldr = _prune_tldr_to_entities(tldr, entity_names)
                        # Sweep §Gap2: add caller hints for suspect functions.
                        caller_hints = await _find_caller_hints(
                            fault_locs, self._original_project_dir
                        )
                        if caller_hints:
                            fault_locs += f"\n\n{caller_hints}"
                # Moatless §Gap3: span-level FileContext with token budget.
                # Preserve fault-localized files; evict others. Inject hint
                # when spans dropped so worker fetches more via MCP tools.
                span_budget = int(GLOBAL_SETTINGS.get("context_span_budget", 6000))
                priority_files = re.findall(r'`([^`]+\.(?:py|js|ts|tsx))`', fault_locs) if fault_locs else []
                tldr, n_evicted = _span_evict_tldr(tldr, span_budget, priority_files)
                context_blocks.append(f"# Codebase Structure (auto-generated)\n\n{tldr}")
                if n_evicted > 0:
                    context_blocks.append(
                        f"# Context Retrieval\n\n{n_evicted} file span(s) evicted to fit budget. "
                        f"Use clade_search_class / clade_search_method / clade_search_code "
                        f"MCP tools to retrieve additional spans on demand."
                    )
                if fault_locs:
                    context_blocks.append(fault_locs)
                # For fix tasks: run repro test generation + SBFL pre-pass concurrently.
                if task_type == "fix":
                    repro_task = asyncio.create_task(
                        _generate_repro_test(self.description, tldr, self._original_project_dir)
                    )
                    sbfl_task = asyncio.create_task(
                        _sbfl_prepass(self._original_project_dir)
                    )
                    repro_test, sbfl_block = await asyncio.gather(repro_task, sbfl_task)
                    if sbfl_block:
                        context_blocks.append(sbfl_block)
                    if repro_test:
                        context_blocks.append(repro_test)
        except Exception:
            pass
        # Pre-hydration: fetch linked GitHub issues/PRs before agent starts (Stripe Blueprint pattern)
        try:
            hydrate_block = await _pre_hydrate(self.description, self._project_dir)
            if hydrate_block:
                context_blocks.append(hydrate_block)
        except Exception:
            pass
        # Apply ObservationMaskingCondenser to truncate any oversized context block before
        # writing the task file — prevents multi-hundred-KB task files from large GitHub issues
        # or deeply nested project structures. Each block treated as an observation event.
        if context_blocks:
            _ctx_condenser = ObservationMaskingCondenser(max_obs_bytes=8192)
            _ctx_events = [{"type": "observation", "content": b} for b in context_blocks]
            context_blocks = [e["content"] for e in _ctx_condenser.condense(_ctx_events)]
            effective_description = "\n\n---\n\n".join(context_blocks) + f"\n\n---\n\n# Task\n\n{self.description}"
        # Inject recent sibling completions (multi-agent context archival).
        # Workers gain awareness of what was recently accomplished — prevents duplicate
        # work and allows continuation of previously established patterns.
        if task_queue:
            try:
                recent = await task_queue.get_recent_completions(
                    exclude_task_id=self.task_id, limit=5, since_seconds=86400
                )
                if recent:
                    lines = ["## Recently Completed Tasks"]
                    for r in recent:
                        lines.append(f"- [{r['id']}] {r['completion_summary']}")
                    effective_description += "\n\n---\n\n" + "\n".join(lines) + "\n"
            except Exception:
                pass
            # Context versioning (Multi-agent Gap 1): stamp this worker's task file
            # with the current completion count. If codebase has changed since the task
            # was queued, inject a staleness warning so the agent knows to re-read key files.
            try:
                current_version = await task_queue.get_context_version()
                task_context_version = 0
                task = await task_queue.get(self.task_id)
                if task:
                    task_context_version = task.get("context_version") or 0
                self.context_version = current_version
                await task_queue.stamp_context_version(self.task_id)
                stale_count = current_version - task_context_version
                if stale_count > 0:
                    effective_description += (
                        f"\n\n---\n\n"
                        f"⚠ **Context Staleness Warning**: {stale_count} task(s) completed since "
                        f"this task was queued. Codebase may have changed — re-read key files "
                        f"before making assumptions about current state.\n"
                    )
            except Exception:
                pass
        # Inject unread messages from other tasks — also condense individual messages
        # to prevent a large tool-output dump from one worker flooding another's context
        if task_queue:
            try:
                messages = await task_queue.get_messages(self.task_id, unread_only=True)
                if messages:
                    _msg_condenser = ObservationMaskingCondenser(max_obs_bytes=2000)
                    msg_block = "\n\n---\n**Messages from other tasks:**\n"
                    for m in messages:
                        sender = m.get("from_task_id") or "human"
                        condensed = _msg_condenser.condense(
                            [{"type": "observation", "content": m["content"]}]
                        )
                        msg_block += f"- [{sender}]: {condensed[0]['content']}\n"
                    effective_description += msg_block
                    await task_queue.mark_messages_read(self.task_id)
            except Exception:
                pass
        # Multi-agent Gap 3: inject task schema (acceptance criteria + contracts) if present.
        _schema_block = _format_task_schema_block(_parse_task_schema(self.description))

        # AutoCodeRover §Gap2 + ECC strategic-compact: for fix tasks, inject explicit
        # two-phase directive with phase-boundary checkpoint (not arbitrary token count).
        _fix_two_phase = ""
        if _parse_task_type(self.description) == "fix":
            _fix_two_phase = (
                "\n\n---\n\n"
                "## Two-Phase Approach (AutoCodeRover §Gap2)\n"
                "**Phase 1 — Explore first (make NO code changes):**\n"
                "1. Read the suspect files identified above\n"
                "2. Trace the execution path to the root cause\n"
                "3. Identify the exact 1-5 lines that need to change\n"
                "4. **Phase boundary**: write your findings to `.claude/ctx-checkpoint.md` "
                "before making any edits (root cause, affected lines, intended fix).\n\n"
                "**Phase 2 — Patch (after checkpoint written):**\n"
                "1. Make the minimal targeted change — prefer 1-3 line edits\n"
                "2. Verify the reproduction test passes (if provided above)\n"
                "3. Run lint before committing\n"
            )
        task_file.write_text(
            effective_description + _schema_block + _fix_two_phase
            + EDIT_DISCIPLINE_BLOCK + SEARCH_CONVENTIONS_BLOCK + COMPLETION_CONTRACT_BLOCK
        )

        # OpenHands §Gap3: capture test baseline before worker edits (fix tasks only).
        if _parse_task_type(self.description) == "fix" and self._project_dir:
            try:
                baseline = await _capture_test_baseline(self._project_dir, timeout=30)
                if baseline:
                    (self._claude_dir / "test-baseline.json").write_text(
                        json.dumps(baseline)
                    )
                    logger.debug("Intramorphic baseline: %d tests for %s", len(baseline), self.task_id)
            except Exception:
                pass

        return task_file

    def _build_cmd_and_env(self, task_file: Path) -> tuple[str, dict]:
        """Resolve model alias, build shell command, and prepare env dict."""
        _ALLOWED_MODELS = {
            "claude-opus-4-6", "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
            "claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5",
        }
        model = _MODEL_ALIASES.get(self.model, self.model)
        model = model if model in _ALLOWED_MODELS else "claude-sonnet-4-6"
        shell_cmd = (
            f'claude -p "$(cat {shlex.quote(str(task_file))})" --model {model} --dangerously-skip-permissions'
        )
        # Tool subsets per task type (Stripe Blueprint pattern)
        tool_flags = _build_tool_flags(self.task_type)
        if tool_flags:
            shell_cmd += tool_flags
        mcp_config = self._project_dir / ".claude" / "mcp.json"
        if mcp_config.exists():
            shell_cmd += f" --mcp-config {shlex.quote(str(mcp_config))}"

        env = {**os.environ}
        # Unset CLAUDECODE so workers can launch even when the orchestrator itself
        # is started from inside a Claude Code session (prevents "nested session" error)
        env.pop("CLAUDECODE", None)
        if GLOBAL_SETTINGS.get("agent_teams"):
            env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "1"

        return shell_cmd, env

    async def start(self, task_queue: TaskQueue | None = None) -> None:
        self._task_queue = task_queue
        await self._setup_worktree()
        task_file = await self._build_task_file(task_queue)
        shell_cmd, env = self._build_cmd_and_env(task_file)

        # Initialize Pi-style JSONL session tree for this worker
        tree_path = self._log_path.with_suffix(".tree.jsonl")
        self._session_tree = SessionTree(tree_path)
        self._session_tree.session_start({
            "worker_id": self.id,
            "task_id": self.task_id,
            "model": self.model,
            "task_type": self.task_type,
            "description": self.description[:200],  # truncate for log
        })
        # Record the task description as the first user entry
        root_id = self._session_tree.user(self.description[:5000])

        with open(self._log_path, "w") as log_fd:
            self.proc = await asyncio.create_subprocess_shell(
                shell_cmd,
                stdout=log_fd,
                stderr=log_fd,
                preexec_fn=os.setsid,
                env=env,
                cwd=str(self._project_dir),
            )
        self.pid = self.proc.pid
        try:
            self.pgid = os.getpgid(self.proc.pid)
        except ProcessLookupError:
            self.pgid = self.proc.pid
        self.status = "running"
        self.transition_reason = "process_started"
        self._event_stream.emit(
            event_type="action",
            event_kind="tool_call",
            source="worker",
            content={"shell_cmd": shell_cmd[:500], "pid": self.pid},
        )
        # Start task span for tracing
        self._task_span = start_task_span(self.id, self.description, self.task_id)

    def is_alive(self) -> bool:
        if self.proc is None:
            return False
        return self.proc.returncode is None

    def _get_activity_state(self) -> str:
        """Determine activity state by reading Claude Code's JSONL session file.

        Composio pattern: maps JSONL entry types to activity states.
        Returns: 'active', 'waiting_input', 'blocked', or 'unknown'.
        """
        if not self._claude_dir:
            return "unknown"
        try:
            # Claude Code session JSONL lives in ~/.claude/projects/{encoded-path}/
            # Each session has a .jsonl file we can read
            projects_dir = self._claude_dir.parent  # typically ~/.claude
            if not projects_dir.exists():
                return "unknown"
            # Find the most recent session .jsonl for this project
            import glob as _glob
            session_pattern = str(projects_dir / "projects" / "*" / "sessions" / "*.jsonl")
            jsonl_files = sorted(
                _glob.glob(session_pattern),
                key=lambda p: os.path.getmtime(p),
                reverse=True,
            )
            if not jsonl_files:
                return "unknown"
            # Read last entry from most recent session file
            with open(jsonl_files[0], "rb") as f:
                f.seek(max(0, os.path.getsize(jsonl_files[0]) - 4096))
                tail = f.read().decode("utf-8", errors="replace")
            lines = tail.strip().splitlines()
            if not lines:
                return "unknown"
            last_line = lines[-1]
            entry = json.loads(last_line)
            last_type = entry.get("type", "")
            # Composio mapping
            if last_type in ("tool_use", "user"):
                return "active"
            elif last_type in ("assistant", "summary", "result"):
                return "waiting_input"
            elif last_type == "error":
                return "blocked"
            elif last_type == "permission_request":
                return "waiting_input"
            return "unknown"
        except Exception:
            return "unknown"

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
            try:
                os.killpg(self.pgid, signal.SIGTERM)
                await asyncio.sleep(0.5)
                if self.is_alive():
                    os.killpg(self.pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if self._finished_at is None:
            self._finished_at = time.time()
        self._verify_triggered = True  # prevent _on_worker_done from running after forced stop
        await self._cleanup_worktree()

    async def poll(self) -> None:
        if not self.is_alive():
            if self._finished_at is None:
                self._finished_at = time.time()
            rc = self.proc.returncode if self.proc else -1
            self.status = "done" if rc == 0 else "failed"
            self.transition_reason = f"process_exited_rc_{rc}"
            if self.status == "failed" and self._log_path and self._log_path.exists():
                try:
                    text = self._log_path.read_text(errors="replace")
                    self.failure_context = _truncate_output(text)
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

    async def _cleanup_worktree(self) -> None:
        if not self._worktree_path:
            return
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
                verified = await self.verify_and_commit()
            except Exception:
                logger.exception("verify_and_commit failed for worker %s", self.id)
                verified = False
            # Reflection loop (Aider pattern): if verification failed, run lint check and retry
            # Token budget gate: parse current usage first; skip retry if budget exceeded.
            _current_tokens = 0
            if self.token_budget > 0 and self._log_path and self._log_path.exists():
                try:
                    _in, _out = _parse_token_usage(self._log_path)
                    _current_tokens = _in + _out
                except Exception:
                    pass
            _budget_ok = (self.token_budget == 0 or _current_tokens < self.token_budget)
            if not verified and self._reflection_retries < MAX_REFLECTION_RETRIES and _budget_ok:
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
                        else:
                            self._reflection_retries += 0  # already incremented
                except Exception:
                    pass
        # Parse token usage from log and enforce token budget
        if self._log_path and self._log_path.exists():
            try:
                self._input_tokens, self._output_tokens = _parse_token_usage(self._log_path)
                self._estimated_cost = _estimate_cost(self._input_tokens, self._output_tokens)
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
        # Post-commit test runner (Sweep §Gap3): run project tests after successful commit.
        # Catches functional regressions that lint check misses. Fail-open: test failures
        # are logged but don't mark the worker as failed.
        if self.auto_committed and self._project_dir:
            try:
                tests_passed, test_output = await _run_project_tests(self._project_dir)
                if not tests_passed and test_output:
                    logger.warning(
                        "Worker %s: post-commit tests FAILED:\n%s",
                        self.id, test_output[:500]
                    )
                    # Inject test failure into failure_context so it appears in task status
                    if not self.failure_context:
                        self.failure_context = f"Post-commit tests failed:\n{test_output[:300]}"
                    elif "test" not in self.failure_context.lower():
                        self.failure_context += f"\nPost-commit tests failed:\n{test_output[:200]}"

                # OpenHands §Gap3: intramorphic regression check
                reg_warning = await _run_intramorphic_check(
                    self._project_dir, self._claude_dir, test_output
                )
                if reg_warning:
                    logger.warning("Worker %s: %s", self.id, reg_warning)
                    self.failure_context = (
                        f"{self.failure_context}\n{reg_warning}" if self.failure_context
                        else reg_warning
                    )
            except Exception:
                pass
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
            except Exception: pass
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
        await self._cleanup_worktree()

    def _check_file_ownership(self, changed_files: list[str]) -> tuple[bool, str]:
        """Check changed files against own_files/forbidden_files globs. Returns (ok, reason)."""
        if not self.own_files and not self.forbidden_files:
            return True, ""

        def _matches(filepath: str, patterns: list[str]) -> bool:
            for pat in patterns:
                if pat.endswith("/**"):
                    prefix = pat[:-3]  # "src/db/**" → "src/db"
                    if filepath == prefix or filepath.startswith(prefix + "/"):
                        return True
                if fnmatch.fnmatch(filepath, pat):
                    return True
            return False

        # Check forbidden files
        for f in changed_files:
            if self.forbidden_files and _matches(f, self.forbidden_files):
                return False, f"File '{f}' matches FORBIDDEN_FILES pattern"

        # Check own files (if set, every changed file must match at least one pattern)
        if self.own_files:
            for f in changed_files:
                if not _matches(f, self.own_files):
                    return False, f"File '{f}' not in OWN_FILES patterns"

        return True, ""

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
            return False

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
            verify_proc = await asyncio.create_subprocess_shell(
                f'claude -p "$(cat {shlex.quote(str(verify_file))})" --model claude-haiku-4-5-20251001 --dangerously-skip-permissions',
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

        commit_msg = f"feat: {task_first_line.lower()}"
        files_arg = " ".join(shlex.quote(f) for f in changed_files[:20])
        committer_path = Path.home() / ".claude/scripts/committer.sh"
        if committer_path.exists():
            commit_cmd = (
                f'bash {shlex.quote(str(committer_path))} '
                f'{shlex.quote(commit_msg)} {files_arg}'
            )
        else:
            commit_cmd = f'git add {files_arg} && git commit -m {shlex.quote(commit_msg)}'
        commit_proc = await asyncio.create_subprocess_shell(
            commit_cmd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(self._project_dir),
        )
        try:
            c_out, c_err = await asyncio.wait_for(commit_proc.communicate(), timeout=30)
            if commit_proc.returncode == 0:
                self.auto_committed = True

                # Oracle validation gate
                if GLOBAL_SETTINGS.get("auto_oracle", False):
                    try:
                        diff_proc = await asyncio.create_subprocess_exec(
                            "git", "diff", "HEAD~1", "HEAD",
                            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                            cwd=str(self._project_dir),
                        )
                        diff_out, _ = await asyncio.wait_for(diff_proc.communicate(), timeout=15)
                        approved, reason = await _oracle_review(
                            self.description, diff_out.decode(), self._claude_dir
                        )
                        self.oracle_result = "approved" if approved else "rejected"
                        self.oracle_reason = reason
                        if not approved:
                            # Undo the commit so rejected work is not accidentally pushed later
                            reset_proc = await asyncio.create_subprocess_exec(
                                "git", "reset", "HEAD~1",
                                stdout=asyncio.subprocess.DEVNULL,
                                stderr=asyncio.subprocess.DEVNULL,
                                cwd=str(self._project_dir),
                            )
                            try:
                                await asyncio.wait_for(reset_proc.communicate(), timeout=10)
                            except asyncio.TimeoutError:
                                reset_proc.kill()
                                await reset_proc.communicate()
                            self.auto_committed = False
                            # Flag for requeue — poll_all will pick this up
                            self._oracle_requeue = True
                            self._oracle_requeue_reason = reason
                            return False
                    except Exception:
                        pass  # fail-open

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

        if use_continue:
            # AutoCodeRover pattern: --continue preserves agent context across retries.
            # Send only the lint error context as a follow-up message, not the full task.
            task_file.write_text(extra_context.strip(), encoding="utf-8")
            model = _MODEL_ALIASES.get(self.model, self.model)
            shell_cmd = (
                f'claude -p --continue "$(cat {shlex.quote(str(task_file))})"'
                f" --model {model} --dangerously-skip-permissions"
            )
        else:
            retry_desc = self.description + f"\n\n{extra_context}"
            task_file.write_text(retry_desc, encoding="utf-8")
            shell_cmd, _ = self._build_cmd_and_env(task_file)

        _, env = self._build_cmd_and_env(task_file)

        # Append to existing log
        log_fd = open(self._log_path, "a") if self._log_path else None
        try:
            self.proc = await asyncio.create_subprocess_shell(
                shell_cmd,
                stdout=log_fd,
                stderr=log_fd,
                preexec_fn=os.setsid,
                env=env,
                cwd=str(self._project_dir),
            )
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
            rc = self.proc.returncode if self.proc else -1
            self.status = "done" if rc == 0 else "failed"
            if log_fd:
                log_fd.close()
                log_fd = None
            if self.status == "done":
                return await self.verify_and_commit()
            # If --continue failed (e.g. no prior session), fall back to full restart
            if use_continue and not self.auto_committed:
                logger.info("Worker %s: --continue failed, falling back to full restart", self.id)
                return await self._run_with_context(extra_context, use_continue=False)
            return False
        except Exception:
            if log_fd:
                log_fd.close()
            return False


# ─── Worker Pool ──────────────────────────────────────────────────────────────

class WorkerPool:
    def __init__(self):
        self.workers: dict[str, Worker] = {}

    async def start_worker(
        self,
        task: dict,
        task_queue: TaskQueue,
        project_dir: Path,
        claude_dir: Path,
    ) -> Worker:
        # Guard: prevent spawning a second worker for the same task
        existing = next(
            (w for w in self.workers.values() if w.task_id == task["id"] and w.status in ("running", "starting")),
            None,
        )
        if existing:
            return existing
        model = task.get("model", GLOBAL_SETTINGS.get("default_model", "sonnet"))
        model = _MODEL_ALIASES.get(model, model)
        description = task["description"]
        if GLOBAL_SETTINGS.get("auto_model_routing", False):
            score = task.get("score")
            if score is not None:
                if score >= 80:
                    model = "haiku"
                elif score < 50:
                    model = "sonnet"
                    description = (
                        "⚠ This task scored low on readiness (<50). "
                        "Ask clarifying questions before writing any code. "
                        "Do NOT start implementing until requirements are clear.\n\n"
                        + description
                    )
                if task.get("is_critical_path"):
                    model = {"haiku": "sonnet", "sonnet": "opus"}.get(model, model)
        # Auto-inject past intervention corrections for retried/failed tasks
        failed_reason = task.get("failed_reason")
        if failed_reason:
            try:
                match = await task_queue.find_matching_intervention(failed_reason)
                if match:
                    description = (
                        f"{description}\n\n---\n**Auto-injected correction:**\n{match['correction']}"
                    )
            except Exception:
                pass
        model = _MODEL_ALIASES.get(model, model)
        # Wire global EventBus JSONL for aggregate lifecycle observability (learn-cc s18)
        EventStream.set_global_bus_path(claude_dir / "events.jsonl")
        worker = Worker(
            task["id"],
            description,
            model,
            project_dir,
            claude_dir,
        )
        worker.model_score = task.get("score")
        worker.task_timeout = task.get("timeout", 600)
        worker.own_files = task.get("own_files", [])
        worker.forbidden_files = task.get("forbidden_files", [])
        # Per-task token budget (0 = use global setting or unlimited)
        _per_task_budget = task.get("token_budget") or 0
        _global_budget = GLOBAL_SETTINGS.get("worker_token_budget", 0)
        worker.token_budget = _per_task_budget or _global_budget
        # Typed handoff fields (Codex SDK pattern)
        if task.get("handoff_type"):
            worker._handoff_type = task["handoff_type"]
            worker._handoff_payload = task.get("handoff_payload")
        self.workers[worker.id] = worker
        await task_queue.update(task["id"], status="running", worker_id=worker.id)
        await worker.start(task_queue=task_queue)
        return worker

    async def _handoff_to_worker(
        self,
        parent_task: dict,
        task_queue: TaskQueue,
        project_dir: Path,
        claude_dir: Path,
    ) -> Worker | None:
        """Spawn a child worker from a typed handoff (Codex SDK pattern).

        The parent task has handoff_type (str) and handoff_payload (dict) fields.
        The child worker is spawned with the handoff context injected into its description.
        """
        handoff_type = parent_task.get("handoff_type")
        handoff_payload = parent_task.get("handoff_payload")

        if not handoff_type or not handoff_payload:
            return None

        # Build typed handoff description
        handoff_desc = (
            f"[Handoff: {handoff_type}]\n\n"
            f"**Handoff Type:** {handoff_type}\n"
            f"**Handoff Payload:**\n```json\n{json.dumps(handoff_payload, indent=2)}\n```\n\n"
            f"**Parent Task:** {parent_task.get('description', 'N/A')}\n\n"
            f"## Instructions\n"
            f"Process this typed handoff. The payload contains structured context from the parent worker.\n"
            f"Resume work based on the payload. Use /pickup if available, otherwise continue from the handoff state."
        )

        # Create continuation task
        child_desc = (
            f"{parent_task.get('description', '')}\n\n"
            f"---\n"
            f"**Typed Handoff ({handoff_type}):**\n"
            f"{json.dumps(handoff_payload, indent=2)}\n"
        )

        model = parent_task.get("model", GLOBAL_SETTINGS.get("default_model", "sonnet"))
        model = _MODEL_ALIASES.get(model, model)

        # Add as new task
        new_task_id = await task_queue.add(
            child_desc,
            model,
            own_files=parent_task.get("own_files", []),
            forbidden_files=parent_task.get("forbidden_files", []),
            parent_task_id=parent_task.get("id"),
        )

        # Get the new task and spawn worker
        new_task = await task_queue.get(new_task_id)
        if not new_task:
            return None

        return await self.start_worker(new_task, task_queue, project_dir, claude_dir)

    def get(self, worker_id: str) -> Worker | None:
        return self.workers.get(worker_id)

    def all(self) -> list[Worker]:
        return list(self.workers.values())

    async def poll_all(self, task_queue: TaskQueue, project_dir: Path | None = None) -> None:
        for w in list(self.workers.values()):
            if w.status == "running" and w.task_timeout and w.task_timeout > 0 and w.elapsed_s > w.task_timeout:
                await w.stop()
                w.status = "failed"
                if w._log_path and w._log_path.exists():
                    try:
                        text = w._log_path.read_text(errors="replace")
                        w.failure_context = _truncate_output(text)
                    except Exception:
                        pass
                await task_queue.update(
                    w.task_id,
                    status="failed",
                    elapsed_s=w.elapsed_s,
                    last_commit=w.last_commit,
                )
                if w.failure_context:
                    await task_queue.update(w.task_id, failed_reason=w.failure_context)
                if project_dir and GLOBAL_SETTINGS.get("github_issues_sync"):
                    t = await task_queue.get(w.task_id)
                    if t:
                        asyncio.create_task(_gh_update_issue_status(t, project_dir))
                continue
            # Stuck worker detection: log file mtime unchanged for N minutes
            stuck_timeout = GLOBAL_SETTINGS.get("stuck_timeout_minutes", 15)
            if (w.status == "running" and not w._stuck_detected
                    and stuck_timeout > 0 and w._log_path and w._log_path.exists()):
                try:
                    idle_s = time.time() - w._log_path.stat().st_mtime
                    if idle_s > stuck_timeout * 60:
                        w._stuck_detected = True
                        logger.warning("Worker %s stuck (no log output for %dm) — killing", w.id, stuck_timeout)
                        await w.stop()
                        w.status = "failed"
                        stuck_reason = f"[STUCK] No log output for {int(idle_s)}s (threshold: {stuck_timeout}min)"
                        w.failure_context = stuck_reason
                        await task_queue.update(w.task_id, status="failed",
                                                elapsed_s=w.elapsed_s, failed_reason=stuck_reason)
                        # Requeue with stuck context (skip: already retried, or loop-managed tasks)
                        _is_loop_task = w.description.startswith("[Loop-") or w.description.startswith("[Plan-")
                        if not w.description.startswith("[STUCK-RETRY]") and not _is_loop_task:
                            retry_desc = f"[STUCK-RETRY] {w.description}"
                            await task_queue.add(retry_desc, w.model,
                                                 own_files=w.own_files, forbidden_files=w.forbidden_files)
                        else:
                            logger.warning("Worker %s stuck — not re-queuing (retry=%s, loop=%s)",
                                           w.id, w.description.startswith("[STUCK-RETRY]"), _is_loop_task)
                        if project_dir and GLOBAL_SETTINGS.get("github_issues_sync"):
                            t = await task_queue.get(w.task_id)
                            if t:
                                asyncio.create_task(_gh_update_issue_status(t, project_dir))
                        continue
                except Exception:
                    pass
            # Guard: don't poll() workers already in a terminal state — poll() would
            # overwrite "blocked" with "failed" based on process exit code
            if w.status not in ("done", "failed", "blocked"):
                await w.poll()
            if w.status in ("done", "failed", "blocked"):
                if not w._terminal_persisted:
                    w._terminal_persisted = True
                    await task_queue.update(
                        w.task_id,
                        status=w.status,
                        elapsed_s=w.elapsed_s,
                        last_commit=w.last_commit,
                    )
                    # Persist token/cost data
                    if w._input_tokens or w._output_tokens:
                        await task_queue.update(
                            w.task_id,
                            input_tokens=w._input_tokens,
                            output_tokens=w._output_tokens,
                            estimated_cost=w._estimated_cost,
                        )
                    # Persist completion summary (multi-agent context archival)
                    if w.completion_summary:
                        try:
                            await task_queue.update(w.task_id, completion_summary=w.completion_summary)
                        except Exception:
                            pass
                    if w.status == "failed" and w.failure_context:
                        await task_queue.update(w.task_id, failed_reason=w.failure_context)
                    if w.status == "done":
                        try:
                            await task_queue.mark_intervention_success(w.task_id)
                        except Exception:
                            pass
                    if project_dir and GLOBAL_SETTINGS.get("github_issues_sync"):
                        t = await task_queue.get(w.task_id)
                        if t:
                            asyncio.create_task(_gh_update_issue_status(t, project_dir))
                # Oracle rejected → re-queue (Agentless §6C: N parallel samples for critical tasks)
                if w._oracle_requeue:
                    w._oracle_requeue = False
                    error_summary = _strip_error_context(w._oracle_requeue_reason)
                    n_samples = max(1, int(GLOBAL_SETTINGS.get("parallel_fix_samples", 1)))
                    orig_task = await task_queue.get(w.task_id)
                    if not (orig_task and orig_task.get("is_critical_path")):
                        n_samples = 1
                    _DIVERSE_HINTS = [
                        "Try a different algorithmic approach than your previous attempt.",
                        "Focus on the root cause rather than symptoms — consider upstream fixes.",
                        "Prefer minimal diff — find the smallest correct change.",
                    ]
                    for i in range(n_samples):
                        hint = f"\n{_DIVERSE_HINTS[i % len(_DIVERSE_HINTS)]}" if n_samples > 1 else ""
                        retry_desc = (
                            f"{w.description}\n\n---\n"
                            f"Previous attempt was REJECTED by oracle review:\n"
                            f"{error_summary}\n"
                            f"Fix the issue described above. Do NOT repeat the same approach.{hint}"
                        )
                        await task_queue.add(retry_desc, w.model,
                                             own_files=w.own_files, forbidden_files=w.forbidden_files)
                    if n_samples > 1:
                        logger.info(
                            "Oracle rejected critical task %s — spawned %d parallel samples",
                            w.task_id, n_samples
                        )
                    else:
                        logger.info("Oracle rejected task %s — re-queued with reason", w.task_id)
                # File ownership violation → re-queue with violation context
                if w._ownership_violation:
                    w._ownership_violation = False
                    error_summary = _strip_error_context(w._ownership_violation_reason)
                    retry_desc = (
                        f"{w.description}\n\n---\n"
                        f"Previous attempt REJECTED — file ownership violation:\n"
                        f"{error_summary}\n\n"
                        f"You MUST only edit files matching your OWN_FILES patterns. "
                        f"Do NOT touch FORBIDDEN_FILES. Find an alternative approach."
                    )
                    await task_queue.add(retry_desc, w.model,
                                        own_files=w.own_files, forbidden_files=w.forbidden_files)
                    await task_queue.update(
                        w.task_id,
                        failed_reason=f"Ownership violation: {error_summary[:200]}"
                    )
                    logger.info("Ownership violation task %s — re-queued with reason", w.task_id)
                # Worker wrote handoff file → create continuation task
                if w._handoff_requeue:
                    w._handoff_requeue = False
                    continuation_desc = (
                        f"{w.description}\n\n---\n"
                        f"**Continuation — previous session handed off:**\n"
                        f"{w._handoff_content}\n\n"
                        f"Run /pickup if available, then continue from where the previous worker left off."
                    )
                    await task_queue.add(continuation_desc, w.model,
                                        own_files=w.own_files, forbidden_files=w.forbidden_files)
                    logger.info("Handoff task %s → continuation queued", w.task_id)
                # Typed worker handoff (Codex SDK pattern) — spawn child worker on completion
                if w._handoff_type and w._handoff_payload and w.status == "done":
                    parent_task = await task_queue.get(w.task_id)
                    if parent_task:
                        try:
                            await self._handoff_to_worker(
                                parent_task, task_queue, w._project_dir, w._claude_dir
                            )
                            logger.info(
                                "Typed handoff %s → child worker spawned for task %s",
                                w._handoff_type, w.task_id
                            )
                        except Exception:
                            logger.exception("Handoff to worker failed for task %s", w.task_id)
            else:
                await task_queue.update(
                    w.task_id,
                    elapsed_s=w.elapsed_s,
                    last_commit=w.last_commit,
                )
            # verify_and_commit() is triggered in poll() via _on_worker_done() to ensure
            # it runs before worktree cleanup — no separate trigger needed here
        if GLOBAL_SETTINGS.get("context_budget_warning", True):
            for w in list(self.workers.values()):
                if w.status == "running":
                    tokens = w._estimate_tokens()
                    if tokens > 160000:
                        warn_file = w._claude_dir / f"context-warning-{w.id}.md"
                        if not warn_file.exists():
                            warn_file.write_text(
                                "CONTEXT WARNING: ~80% context window used. "
                                "Run /compact now — preserve current task state, files modified, next steps."
                            )

# ─── Swarm Manager ────────────────────────────────────────────────────────────


# SwarmManager moved to swarm.py
from swarm import SwarmManager
