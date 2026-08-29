"""WorkerPool — scheduling and lifecycle for N concurrent workers.

Extracted from worker.py on 2026-08-29, the same way SwarmManager was extracted
into swarm.py. worker.py had reached the 1500-line ceiling exactly, so every
change to the two most central modules began by reclaiming a line, and logic
was being pushed into leaves for budget reasons rather than cohesion.

The split is along a real seam: Worker executes ONE task (spawn, verify,
commit, evidence); WorkerPool decides which workers exist and polls them. It is
re-exported from worker.py, so `from worker import WorkerPool` still resolves.

Which Worker class the pool constructs is an explicit attribute, not a hidden
import. Several test suites load `worker.py` privately via importlib to bind a
real `worker_review` past conftest's safety mocks; when the pool resolved
`Worker` by importing the shared module, those privately-loaded copies silently
got the MOCKED Worker and bound a MagicMock into SQLite. `worker.py` therefore
subclasses this with its own Worker, so a private copy stays private.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

# No `TYPE_CHECKING: from worker import Worker` here. The DAG gate in
# tests/test_conventions.py descends into top-level `if` blocks — it cannot
# tell a typing-only import from a real one, and treating it as real is the
# safe choice — so that block would register a worker -> worker_pool -> worker
# cycle. The pool does not need the type: it takes a constructor via
# `worker_cls`, which is the honest dependency.

import cascade_policy
from config import GLOBAL_SETTINGS, _MODEL_ALIASES
import worker_evidence
from error_classifier import classify as _classify_error, summarize as _summarize_error
from event_stream import EventStream
from github_sync import _gh_update_issue_status
from handoff_registry import project_handoff, validate_handoff
from task_queue import TaskQueue
from worker_review import (
    handle_handoff_requeue,
    handle_oracle_requeue,
    handle_ownership_requeue,
    handle_test_requeue,
)
from worker_runtime import resolve_worker_execution
from worker_utils import _maybe_enqueue_classify_retry, _truncate_output

logger = logging.getLogger(__name__)


class WorkerPool:
    def __init__(self):
        self.workers: dict[str, Any] = {}

    #: Set by the module that re-exports this class, so a privately-loaded
    #: worker.py binds ITS Worker rather than the shared one.
    worker_cls: Any = None

    def _requeue_handlers(self) -> dict[str, Any]:
        """The four requeue implementations, resolved at call time.

        Overridden by worker.py's subclass so it reads ITS module globals.
        Several suites rebind `wmod.handle_oracle_requeue = <real one>` on a
        privately-loaded worker.py to exercise the real requeue path past
        conftest's mocks; binding these at import time here would silently
        ignore that and run the mock.
        """
        return {
            "oracle": handle_oracle_requeue,
            "test": handle_test_requeue,
            "ownership": handle_ownership_requeue,
            "handoff": handle_handoff_requeue,
        }

    def _worker_class(self) -> Any:
        if self.worker_cls is not None:
            return self.worker_cls
        from worker import Worker as _Worker  # lazy: avoids the import cycle

        return _Worker

    async def start_worker(
        self,
        task: dict,
        task_queue: TaskQueue,
        project_dir: Path,
        claude_dir: Path,
    ) -> Any:
        # Guard: prevent spawning a second worker for the same task
        existing = next(
            (w for w in self.workers.values() if w.task_id == task["id"] and w.status in ("running", "starting")),
            None,
        )
        if existing:
            return existing
        description = task["description"]
        plan = await resolve_worker_execution(task, GLOBAL_SETTINGS, task_queue, project_dir)
        route = plan.route
        if route.needs_clarification:
            description = (
                "⚠ Low readiness (<50): ask clarifying questions before coding. "
                "Do NOT implement until requirements are clear.\n\n" + description
            )
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
        # Wire global EventBus JSONL for aggregate lifecycle observability (learn-cc s18)
        EventStream.set_global_bus_path(claude_dir / "events.jsonl")
        worker = self._worker_class()(
            task["id"],
            description,
            plan.envelope.resolved.model or route.model,
            project_dir,
            claude_dir,
            agent_runtime=route.agent_runtime,
            effort=plan.envelope.resolved.effort,
            route_reason=route.reason,
            execution_envelope=plan.envelope,
        )
        worker.model_score = task.get("score")
        worker.task_timeout = task.get("timeout", 600)
        worker.own_files = task.get("own_files", [])
        worker.forbidden_files = task.get("forbidden_files", [])
        worker.evidence_attempt_id = plan.evidence_attempt_id
        worker.evidence_base_sha = plan.evidence_base_sha
        # Per-task token budget (0 = use global setting or unlimited)
        _per_task_budget = task.get("token_budget") or 0
        _global_budget = GLOBAL_SETTINGS.get("worker_token_budget", 0)
        worker.token_budget = _per_task_budget or _global_budget
        # Typed handoff fields (Codex SDK pattern)
        if task.get("handoff_type"):
            worker._handoff_type = task["handoff_type"]
            worker._handoff_payload = task.get("handoff_payload")
        self.workers[worker.id] = worker
        _cur_attempts = plan.evidence_attempt_index or (task.get("attempt_count") or 0) + 1
        await task_queue.update(
            task["id"], status="running", worker_id=worker.id,
            attempt_count=_cur_attempts, model=worker.model,
            agent_runtime=route.agent_runtime,
            effort=worker.effort, route_reason=route.reason,
            execution_envelope=plan.envelope.to_dict(),
        )
        await worker_evidence.start_worker_with_evidence(worker, task_queue)
        return worker

    async def _handoff_to_worker(
        self,
        parent_task: dict,
        task_queue: TaskQueue,
        project_dir: Path,
        claude_dir: Path,
    ) -> Any | None:
        """Spawn a child worker from a typed handoff (Codex SDK pattern).

        The parent task has handoff_type (str) and handoff_payload (dict) fields.
        The child worker is spawned with the handoff context injected into its description.
        """
        handoff_type = parent_task.get("handoff_type")
        handoff_payload = parent_task.get("handoff_payload")

        if not handoff_type or not handoff_payload:
            return None

        for validation_message in validate_handoff(handoff_type, handoff_payload):
            logger.warning(
                "Typed handoff validation warning for task %s: %s",
                parent_task.get("id"), validation_message,
            )
        prompt_payload = project_handoff(handoff_type, handoff_payload)

        # Build typed handoff description
        handoff_desc = (
            f"[Handoff: {handoff_type}]\n\n"
            f"**Handoff Type:** {handoff_type}\n"
            f"**Handoff Payload:**\n```json\n{json.dumps(prompt_payload, indent=2)}\n```\n\n"
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
            f"{json.dumps(prompt_payload, indent=2)}\n"
        )

        model = parent_task.get("model", GLOBAL_SETTINGS.get("default_model", "sonnet"))
        model = _MODEL_ALIASES.get(model, model)

        # Add as new task
        new_task = await task_queue.add(
            child_desc,
            model,
            own_files=parent_task.get("own_files", []),
            forbidden_files=parent_task.get("forbidden_files", []),
            parent_task_id=parent_task.get("id"),
            agent_runtime=parent_task.get("agent_runtime"),
            effort=parent_task.get("effort"),
        )

        return await self.start_worker(new_task, task_queue, project_dir, claude_dir)

    def get(self, worker_id: str) -> Any | None:
        return self.workers.get(worker_id)

    def all(self) -> list[Any]:
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
                        # Forced wall-clock timeout — let the classifier tag it as such.
                        try:
                            err = _classify_error(text, timed_out=True)
                            w._failure_classified = err
                            w.failure_class = _summarize_error(err)
                        except Exception:
                            pass
                    except Exception:
                        pass
                await task_queue.update(
                    w.task_id,
                    status="failed",
                    elapsed_s=w.elapsed_s,
                    last_commit=w.last_commit,
                )
                if w.failure_context:
                    # Prefix the persisted reason with the classifier verdict so
                    # downstream UI / interventions see the structured tag first.
                    reason = (
                        f"[{w.failure_class}] {w.failure_context}"
                        if w.failure_class else w.failure_context
                    )
                    await task_queue.update(w.task_id, failed_reason=reason)
                # Opt-in: auto-retry on classified API errors.
                await _maybe_enqueue_classify_retry(w, task_queue)
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
                        if not w.description.startswith("[STUCK-RETRY]") and not _is_loop_task and not cascade_policy.is_strong_route(w.route_reason):
                            retry_desc = f"[STUCK-RETRY] {w.description}"
                            original = await task_queue.get(w.task_id)
                            await task_queue.add(retry_desc, w.model, **cascade_policy.retry_fields(w, original or {}, "repeated_error"))
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
                        reason = (
                            f"[{w.failure_class}] {w.failure_context}"
                            if w.failure_class else w.failure_context
                        )
                        await task_queue.update(w.task_id, failed_reason=reason)
                        # Opt-in: auto-retry on classified API errors. No-op when
                        # the setting is off, when no classifier object exists,
                        # or when the failure class is non-retryable.
                        await _maybe_enqueue_classify_retry(w, task_queue)
                    if w.status == "done":
                        try:
                            await task_queue.mark_intervention_success(w.task_id)
                        except Exception:
                            pass
                    if project_dir and GLOBAL_SETTINGS.get("github_issues_sync"):
                        t = await task_queue.get(w.task_id)
                        if t:
                            asyncio.create_task(_gh_update_issue_status(t, project_dir))
                # Loop/plan-managed tasks have their OWN retry pipeline (session.py's
                # plan-drift guard re-spawns "[Plan-N+1]" next iteration, bounded by
                # max_iterations) — same skip as the stuck-worker requeue above, and
                # shared by ALL FOUR requeue paths below (oracle/test/ownership/
                # handoff): spawning an untracked retry for any of them would race a
                # second worker against the plan/loop's own tracked one on the same
                # item (adversarial-review finding, HIGH — the first pass of this
                # fix only covered the oracle-requeue site, missing 3 siblings that
                # reproduce the identical bug).
                _is_loop_task = w.description.startswith("[Loop-") or w.description.startswith("[Plan-")
                # Oracle rejected → re-queue (diverse fan-out on plateau, or escalate
                # past the reject-round cap). Logic lives in worker_review.py's
                # handle_oracle_requeue — extracted to stay under the 1500-line cap.
                if w._oracle_requeue:
                    w._oracle_requeue = False
                    if not _is_loop_task:
                        await self._requeue_handlers()["oracle"](
                            w, task_queue,
                            int(GLOBAL_SETTINGS.get("oracle_max_reject_rounds", 5) or 0),
                            GLOBAL_SETTINGS.get("notification_webhook", ""),
                            int(GLOBAL_SETTINGS.get("parallel_fix_samples", 3)),
                        )
                    else:
                        logger.info(
                            "Worker %s oracle-rejected but is loop/plan-managed — "
                            "not requeuing via handle_oracle_requeue (has its own retry pipeline)",
                            w.task_id,
                        )
                # Pre-push test failure / ownership violation / handoff → re-queue with
                # context (mic92: evidence before verdict). Logic lives in
                # worker_review.py alongside handle_oracle_requeue — extracted to
                # stay under the 1500-line cap.
                if w._test_requeue:
                    w._test_requeue = False
                    await self._requeue_handlers()["test"](w, task_queue, _is_loop_task)
                if w._ownership_violation:
                    w._ownership_violation = False
                    await self._requeue_handlers()["ownership"](w, task_queue, _is_loop_task)
                if w._handoff_requeue:
                    w._handoff_requeue = False
                    await self._requeue_handlers()["handoff"](w, task_queue, _is_loop_task)
                # Typed worker handoff (Codex SDK pattern) — spawn child worker on completion
                if w._handoff_type and w._handoff_payload and w.status == "done":
                    parent_task = await task_queue.get(w.task_id)
                    if parent_task:
                        try:
                            child = await self._handoff_to_worker(
                                parent_task, task_queue, w._project_dir, w._claude_dir
                            )
                            if child is not None:
                                logger.info(
                                    "Typed handoff %s → child worker spawned for task %s",
                                    w._handoff_type, w.task_id
                                )
                            else:
                                logger.warning(
                                    "Typed handoff %s for task %s did not spawn a child worker "
                                    "(missing handoff fields on the row, or the new task "
                                    "row could not be re-fetched)",
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
                        # Keyed by task_id — the only id context-warning-drain.sh's hook env has.
                        warn_file = w._claude_dir / f"context-warning-{w.task_id}.md"
                        if not warn_file.exists():
                            warn_file.write_text(
                                "CONTEXT WARNING: ~80% context window used. "
                                "Run /compact now — preserve current task state, files modified, next steps."
                            )
