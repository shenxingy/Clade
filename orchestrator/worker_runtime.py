"""Runtime-route transition for queued workers.

Keeps runtime selection and its durable failure outcome out of the large
worker execution engine.
"""

from __future__ import annotations

from typing import Any, Mapping

from agent_runtime import AgentRuntimeSelectionError
from config import _parse_task_type
from worker_routing import WorkerRoute, resolve_worker_route


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
