"""Runtime-route transition for queued workers.

Keeps runtime selection and its durable failure outcome out of the large
worker execution engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from agent_runtime import AgentRuntimeSelectionError
from config import _parse_task_type
from execution_envelope import ExecutionEnvelope, ExecutionResolutionError
from execution_resolver import resolve_execution
from worker_provider import get_agent_runtime
from worker_routing import WorkerRoute, resolve_worker_route
from worker_evidence import begin_task_evidence, fail_preflight_evidence


@dataclass(frozen=True)
class WorkerExecutionPlan:
    route: WorkerRoute
    envelope: ExecutionEnvelope
    evidence_attempt_id: str | None = None
    evidence_attempt_index: int | None = None
    evidence_base_sha: str | None = None


async def resolve_runtime_route(
    task: Mapping[str, Any],
    settings: Mapping[str, Any],
    task_queue: Any,
) -> WorkerRoute:
    """Resolve a route or persist one terminal configuration failure."""

    route_task = dict(task)
    route_task["task_type"] = (
        _parse_task_type(str(task["description"]))
        or task.get("task_type")
        or "AUTO"
    )
    try:
        return resolve_worker_route(route_task, settings)
    except AgentRuntimeSelectionError as exc:
        # Prevent auto-start from retrying the same invalid selection on every
        # status-loop tick. No Worker or subprocess exists at this point.
        await task_queue.update(
            task["id"],
            status="failed",
            failed_reason=str(exc),
            route_reason="agent runtime selection failed",
        )
        raise


async def resolve_worker_execution(
    task: Mapping[str, Any],
    settings: Mapping[str, Any],
    task_queue: Any,
    project_dir: Any = None,
) -> WorkerExecutionPlan:
    """Resolve route + immutable envelope or persist one preflight failure."""

    attempt = (
        await begin_task_evidence(task, task_queue, project_dir)
        if project_dir is not None
        else None
    )
    if attempt:
        await task_queue.update(
            task["id"], attempt_count=attempt["attempt_index"]
        )
    try:
        route = await resolve_runtime_route(task, settings, task_queue)
        adapter = get_agent_runtime(route.agent_runtime)
        envelope = resolve_execution(
            task=task,
            settings=settings,
            route=route,
            adapter=adapter,
        )
        await task_queue.update(
            task["id"],
            agent_runtime=route.agent_runtime,
            provider=route.agent_runtime,
            execution_envelope=envelope.to_dict(),
            route_reason=route.reason,
        )
        return WorkerExecutionPlan(
            route=route,
            envelope=envelope,
            evidence_attempt_id=attempt["attempt_id"] if attempt else None,
            evidence_attempt_index=attempt["attempt_index"] if attempt else None,
            evidence_base_sha=(
                attempt.get("evidence", {}).get("git", {}).get("base_sha")
                if attempt
                else None
            ),
        )
    except AgentRuntimeSelectionError as exc:
        # resolve_runtime_route already persisted the typed failure.
        await fail_preflight_evidence(task_queue, attempt, exc)
        raise
    except ExecutionResolutionError as exc:
        await task_queue.update(
            task["id"],
            status="failed",
            failed_reason=str(exc),
            route_reason="execution capability resolution failed",
        )
        await fail_preflight_evidence(task_queue, attempt, exc)
        raise
