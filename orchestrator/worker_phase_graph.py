"""Declared worker/task/loop lifecycle graph for additive observability.

The phase names mirror writes in task_queue.py (pending/running), worker.py
(starting/running/paused/blocked/done/failed and oracle-review/requeue execution
phases), worker_review.py (requeue), and session.py (idle/running/paused/
cancelled/converged/exhausted/budget_exceeded plus supervisor/worker alternation).
``grouped`` and ``interrupted`` are task states written by session.py/config.py.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


PHASES = frozenset({
    "pending", "starting", "running", "paused", "oracle-review", "requeue",
    "supervisor", "worker", "grouped", "idle", "blocked", "interrupted",
    "done", "failed", "cancelled", "converged", "exhausted",
    "budget_exceeded",
})

# A shared graph intentionally unions the real task, worker, and loop lifecycles.
# Terminal outcomes are present with empty adjacency sets so their terminal nature
# is structural rather than an implicit convention in callers.
ALLOWED = {
    "pending": {"running", "grouped", "interrupted"},
    "starting": {"running", "failed"},
    "running": {
        "paused", "oracle-review", "supervisor", "worker", "blocked",
        "interrupted", "done", "failed", "cancelled", "converged",
        "exhausted", "budget_exceeded",
    },
    "paused": {"running", "cancelled"},
    "oracle-review": {"done", "failed", "requeue"},
    "requeue": {"running"},
    "supervisor": {
        "worker", "cancelled", "converged", "exhausted", "budget_exceeded",
    },
    "worker": {"supervisor", "oracle-review", "blocked", "done", "failed"},
    "grouped": {"done"},
    "idle": {"running"},
    "blocked": set(),
    "interrupted": set(),
    "done": set(),
    "failed": set(),
    "cancelled": set(),
    "converged": set(),
    "exhausted": set(),
    "budget_exceeded": set(),
}


def validate_transition(frm: str, to: str) -> tuple[bool, str | None]:
    """Return whether a phase transition is declared, without side effects."""
    if frm not in PHASES:
        return False, f"unknown source phase: {frm!r}"
    if to not in PHASES:
        return False, f"unknown destination phase: {to!r}"
    if to not in ALLOWED[frm]:
        return False, f"undeclared phase transition: {frm!r} -> {to!r}"
    return True, None


def record_transition(
    emit: Callable[[dict[str, Any]], Any] | None,
    run_id: str,
    frm: str,
    to: str,
    *,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a transition event and optionally pass it to an existing emitter."""
    event: dict[str, Any] = {
        "type": "phase_transition",
        "run_id": run_id,
        "from": frm,
        "to": to,
    }
    if extra:
        event.update(extra)
    if callable(emit):
        emit(event)
    return event
