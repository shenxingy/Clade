"""
Tracing — simple JSON spans for worker execution (not OpenTelemetry).

Architecture:
- Span: a timed interval with type, name, attributes, and optional parent
- SpanTree: a collection of spans per worker, written to logs/traces/worker-{id}/
- TracingService: creates spans, manages context, writes trace files

This is intentionally NOT OpenTelemetry — too heavy for our use case.
Simple JSON spans with causal chaining are sufficient.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class Span:
    """A single timed interval in a trace."""
    span_id: str
    trace_id: str
    name: str
    span_type: str  # "task" | "llm" | "tool" | "worker" | "phase"
    start_time: float
    end_time: float | None = None
    parent_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"  # "ok" | "error" | "cancelled"

    @property
    def duration_ms(self) -> float | None:
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time) * 1000

    def to_dict(self) -> dict:
        d = asdict(self)
        d["duration_ms"] = self.duration_ms
        return d

    def __repr__(self) -> str:
        return f"<Span {self.span_type}:{self.name} {self.duration_ms:.1f}ms>"


class SpanContext:
    """Manages the current span stack for causal chaining."""
    def __init__(self):
        self._stack: list[Span] = []

    def push(self, span: Span) -> None:
        self._stack.append(span)

    def pop(self) -> Span | None:
        if self._stack:
            return self._stack.pop()
        return None

    @property
    def current(self) -> Span | None:
        if self._stack:
            return self._stack[-1]
        return None

    @property
    def parent(self) -> Span | None:
        if len(self._stack) >= 2:
            return self._stack[-2]
        return None


class Tracer:
    """Creates and manages spans for a single trace (one worker)."""

    def __init__(self, trace_id: str | None = None, output_dir: Path | None = None):
        self.trace_id = trace_id or str(uuid.uuid4())[:16]
        self.output_dir = output_dir
        self._spans: list[Span] = []
        self._ctx = SpanContext()
        self._started = False
        self._finished = False

    def start(self, name: str, span_type: str = "phase",
              attributes: dict[str, Any] | None = None,
              parent_id: str | None = None) -> Span:
        """Start a new span (automatically nested under current)."""
        parent = self._ctx.current
        span = Span(
            span_id=str(uuid.uuid4())[:16],
            trace_id=self.trace_id,
            name=name,
            span_type=span_type,
            start_time=time.time(),
            parent_id=parent_id or (parent.span_id if parent else None),
            attributes=attributes or {},
        )
        self._spans.append(span)
        self._ctx.push(span)
        self._started = True
        return span

    def end(self, span: Span, status: str = "ok") -> None:
        """End a span and detach from context stack."""
        span.end_time = time.time()
        span.status = status
        self._ctx.pop()
        if span is self._ctx.current:
            self._ctx.pop()  # safety: ensure we don't have stale refs

    def end_all(self, status: str = "ok") -> None:
        """End all open spans (for cleanup on error)."""
        while self._ctx.current:
            span = self._ctx.pop()
            span.end_time = time.time()
            span.status = status

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        """Add a zero-duration event to the current span."""
        if not self._ctx.current:
            return
        # Events are stored as a special attribute
        events = self._ctx.current.attributes.get("_events", [])
        events.append({"name": name, "time": time.time(), **(attributes or {})})
        self._ctx.current.attributes["_events"] = events

    @property
    def spans(self) -> list[Span]:
        return list(self._spans)

    def write(self, output_path: Path | None = None) -> Path | None:
        """Write all spans as JSONL to the output directory."""
        if not self._started:
            return None

        # End any remaining open spans
        self.end_all(status="cancelled")

        path = output_path or (self.output_dir / f"{self.trace_id}.jsonl" if self.output_dir else None)
        if not path:
            return None

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            for span in self._spans:
                f.write(json.dumps(span.to_dict()) + "\n")

        self._finished = True
        return path


class TracingService:
    """Global tracing service — creates Tracer instances per worker.

    Writes traces to logs/traces/worker-{worker_id}/
    """
    _instance: TracingService | None = None

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or Path("logs/traces")
        self._tracers: dict[str, Tracer] = {}

    @classmethod
    def get_instance(cls) -> TracingService:
        if cls._instance is None:
            cls._instance = TracingService()
        return cls._instance

    def get_or_create_tracer(self, worker_id: str) -> Tracer:
        """Get existing or create new tracer for a worker."""
        if worker_id in self._tracers:
            return self._tracers[worker_id]

        trace_dir = self.base_dir / f"worker-{worker_id}"
        tracer = Tracer(output_dir=trace_dir)
        self._tracers[worker_id] = tracer
        return tracer

    def start_span(self, worker_id: str, name: str,
                   span_type: str = "phase",
                   attributes: dict[str, Any] | None = None,
                   parent_id: str | None = None) -> Span | None:
        """Start a span on a worker's tracer."""
        tracer = self.get_or_create_tracer(worker_id)
        return tracer.start(name, span_type, attributes, parent_id)

    def end_span(self, worker_id: str, span: Span, status: str = "ok") -> None:
        """End a span on a worker's tracer."""
        if worker_id in self._tracers:
            self._tracers[worker_id].end(span, status)

    def write_trace(self, worker_id: str) -> Path | None:
        """Write a worker's trace to disk and remove from memory."""
        if worker_id not in self._tracers:
            return None
        tracer = self._tracers[worker_id]
        path = tracer.write()
        del self._tracers[worker_id]
        return path

    def add_event(self, worker_id: str, name: str,
                  attributes: dict[str, Any] | None = None) -> None:
        """Add an event to the current span of a worker's tracer."""
        if worker_id in self._tracers:
            self._tracers[worker_id].add_event(name, attributes)


# ─── Convenience helpers ───────────────────────────────────────────────────────

def start_task_span(worker_id: str, task_description: str,
                    task_id: str | None = None) -> Span | None:
    """Start a top-level task span."""
    svc = TracingService.get_instance()
    attrs = {"task_id": task_id} if task_id else {}
    return svc.start_span(worker_id, f"task: {task_description[:80]}",
                          span_type="task", attributes=attrs)


def start_llm_span(worker_id: str, model: str, prompt_tokens: int | None = None) -> Span | None:
    """Start an LLM call span."""
    svc = TracingService.get_instance()
    attrs = {"model": model}
    if prompt_tokens is not None:
        attrs["prompt_tokens"] = prompt_tokens
    return svc.start_span(worker_id, f"llm: {model}", span_type="llm", attributes=attrs)


def end_llm_span(span: Span | None, response_tokens: int | None = None,
                 status: str = "ok") -> None:
    """End an LLM call span with token counts."""
    if span is None:
        return
    if response_tokens is not None:
        span.attributes["response_tokens"] = response_tokens
    svc = TracingService.get_instance()
    svc.end_span(span.trace_id, span, status)


def start_tool_span(worker_id: str, tool_name: str, args: dict | None = None) -> Span | None:
    """Start a tool call span."""
    svc = TracingService.get_instance()
    attrs = {"tool": tool_name}
    if args:
        # Truncate large args for trace
        args_str = json.dumps(args)
        attrs["args_len"] = len(args_str)
        attrs["args_preview"] = args_str[:200]
    return svc.start_span(worker_id, f"tool: {tool_name}", span_type="tool", attributes=attrs)


def end_tool_span(span: Span | None, status: str = "ok") -> None:
    """End a tool call span."""
    if span is None:
        return
    svc = TracingService.get_instance()
    svc.end_span(span.trace_id, span, status)
