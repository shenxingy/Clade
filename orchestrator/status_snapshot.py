"""Provider-neutral status truth rendered by surface adapters."""

from __future__ import annotations

import datetime as dt
from copy import deepcopy
from dataclasses import dataclass
from typing import Any


SCHEMA_VERSION = "clade.status/v1"


@dataclass(frozen=True)
class StatusSnapshot:
    observed_at: str
    task: dict[str, Any]
    git: dict[str, Any]
    execution: dict[str, Any] | None
    limits: list[dict[str, Any]]
    freshness: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "observed_at": self.observed_at,
            "task": deepcopy(self.task),
            "git": deepcopy(self.git),
            "execution": deepcopy(self.execution),
            "limits": deepcopy(self.limits),
            "freshness": dict(self.freshness),
        }


def build_worker_status(w: Any) -> StatusSnapshot:
    """Project durable worker/task facts without inventing progress or limits."""

    status = str(getattr(w, "status", "unknown"))
    terminal = status in {"done", "failed", "blocked"}
    execution = getattr(w, "execution_envelope", None)
    return StatusSnapshot(
        observed_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        task={
            "id": str(getattr(w, "task_id", "")),
            "state": status,
            "progress": {
                "completed": 1 if terminal else None,
                "total": 1 if terminal else None,
                "source": "worker-terminal-state" if terminal else "unknown",
            },
        },
        git={
            "branch": getattr(w, "branch_name", None),
            "dirty": None,
            "checkpoint_sha": getattr(w, "last_commit", None),
        },
        execution=execution.to_dict() if execution else None,
        limits=[],
        freshness={
            "task": "worker-state",
            "progress": "worker-terminal-state" if terminal else "unknown",
            "limits": "unknown",
            "git": "worker-state",
        },
    )
