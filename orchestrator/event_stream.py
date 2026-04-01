"""
EventStream — OpenHands-style immutable event log for workers.

Each worker produces events: action → observation, linked by causal `cause_id`.
Supports replay from log on crash recovery.

Schema:
    worker_events(id, worker_id, event_type, event_kind, source,
                  cause_id, content, timestamp)

event_type: 'action' | 'observation' | 'state_change'
event_kind:  'tool_call' | 'llm_call' | 'file_change' | 'error' | 'interrupt'
source:     'worker' | 'system' | 'supervisor'
cause_id:   FK → parent event (causal chain)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class WorkerEvent:
    id: int | None = None
    worker_id: str = ""
    event_type: str = ""   # action | observation | state_change
    event_kind: str = ""    # tool_call | llm_call | file_change | error | interrupt
    source: str = ""       # worker | system | supervisor
    cause_id: int | None = None
    content: str = ""      # JSON payload
    timestamp: float = field(default_factory=time.time)


class EventStream:
    """Append-only event log for a single worker.

    Events are written to SQLite (via task_queue) and also to a local
    JSONL file for fast append and crash-safe replay.
    """

    def __init__(self, worker_id: str, db_path: str | Path | None = None):
        self.worker_id = worker_id
        self._db_path = db_path or ":memory:"
        self._jsonl_path: Path | None = None
        self._next_local_id = 1
        self._pending_events: list[WorkerEvent] = []
        self._cause_stack: list[int] = []  # stack of active cause IDs for nesting

    def set_jsonl_path(self, path: Path) -> None:
        """Set JSONL file path for crash-safe append."""
        self._jsonl_path = path
        # Initialize with session marker
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a") as f:
                f.write(json.dumps({
                    "type": "session_start",
                    "worker_id": self.worker_id,
                    "ts": time.time(),
                }) + "\n")
        except Exception:
            pass

    def begin(self, event_kind: str) -> int:
        """Begin a new event (action/llm_call). Pushes to cause stack. Returns local ID."""
        local_id = self._next_local_id
        self._next_local_id += 1
        return local_id

    def emit(
        self,
        event_type: str,
        event_kind: str,
        source: str = "worker",
        cause_id: int | None = None,
        content: Any = None,
    ) -> WorkerEvent:
        """Emit a completed event. Writes to JSONL immediately (crash-safe)."""
        if cause_id is None and self._cause_stack:
            cause_id = self._cause_stack[-1]

        event = WorkerEvent(
            id=None,
            worker_id=self.worker_id,
            event_type=event_type,
            event_kind=event_kind,
            source=source,
            cause_id=cause_id,
            content=json.dumps(content) if content is not None else "",
            timestamp=time.time(),
        )

        # Append to JSONL immediately
        if self._jsonl_path:
            try:
                with open(self._jsonl_path, "a") as f:
                    f.write(json.dumps({
                        "id": event.id,
                        "worker_id": event.worker_id,
                        "event_type": event.event_type,
                        "event_kind": event.event_kind,
                        "source": event.source,
                        "cause_id": event.cause_id,
                        "content": event.content,
                        "timestamp": event.timestamp,
                    }) + "\n")
            except Exception:
                pass

        self._pending_events.append(event)
        return event

    def push_cause(self, event_id: int) -> None:
        """Push an event ID onto the cause stack (enter nested scope)."""
        self._cause_stack.append(event_id)

    def pop_cause(self) -> None:
        """Pop from cause stack (exit nested scope)."""
        if self._cause_stack:
            self._cause_stack.pop()

    def log_state_change(self, state: str, reason: str = "") -> WorkerEvent:
        """Convenience: emit a state change event."""
        return self.emit(
            event_type="state_change",
            event_kind="state_change",
            source="system",
            content={"state": state, "reason": reason},
        )

    def log_error(self, error: str, context: str = "") -> WorkerEvent:
        """Convenience: emit an error event."""
        return self.emit(
            event_type="observation",
            event_kind="error",
            source="system",
            content={"error": error, "context": context},
        )

    def events(self) -> list[WorkerEvent]:
        """Return all recorded events (in-order)."""
        return list(self._pending_events)

    def replay(self) -> list[WorkerEvent]:
        """Replay events from JSONL file (for crash recovery).

        Reads all events from JSONL (excluding session_start marker) and
        returns them in chronological order.
        """
        if not self._jsonl_path or not self._jsonl_path.exists():
            return []

        events = []
        try:
            with open(self._jsonl_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get("type") == "session_start":
                        continue
                    events.append(WorkerEvent(
                        id=obj.get("id"),
                        worker_id=obj.get("worker_id", ""),
                        event_type=obj.get("event_type", ""),
                        event_kind=obj.get("event_kind", ""),
                        source=obj.get("source", ""),
                        cause_id=obj.get("cause_id"),
                        content=obj.get("content", ""),
                        timestamp=obj.get("timestamp", 0),
                    ))
        except Exception:
            pass
        return events


def build_causal_chain(events: list[WorkerEvent]) -> dict[int, list[WorkerEvent]]:
    """Build a causal chain map: cause_id → list of child events.

    Useful for replay visualization and debugging.
    """
    chain: dict[int, list[WorkerEvent]] = {}
    for e in events:
        if e.cause_id is not None:
            chain.setdefault(e.cause_id, []).append(e)
    return chain
