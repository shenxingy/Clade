"""
Tests for leaf modules: event_stream, reactions, session_tree, tracing.
These modules have no project-level imports and are easy to unit test.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

# ─── EventStream Tests ────────────────────────────────────────────────────────

from event_stream import EventStream, WorkerEvent, build_causal_chain


class TestEventStreamEmit:
    def test_emit_creates_event(self):
        es = EventStream("w1")
        ev = es.emit("action", "tool_call", content={"cmd": "ls"})
        assert isinstance(ev, WorkerEvent)
        assert ev.event_type == "action"
        assert ev.event_kind == "tool_call"
        assert ev.worker_id == "w1"

    def test_emit_serializes_content(self):
        es = EventStream("w1")
        ev = es.emit("observation", "error", content={"msg": "fail"})
        assert '"msg"' in ev.content

    def test_emit_string_content(self):
        es = EventStream("w1")
        ev = es.emit("observation", "error", content="plain text")
        # json.dumps("plain text") = '"plain text"'
        assert "plain text" in ev.content

    def test_emit_none_content(self):
        es = EventStream("w1")
        ev = es.emit("state_change", "state_change", content=None)
        assert ev.content == ""

    def test_events_accumulate(self):
        es = EventStream("w1")
        es.emit("action", "tool_call")
        es.emit("observation", "error")
        assert len(es.events()) == 2

    def test_cause_stack(self):
        es = EventStream("w1")
        es.push_cause(42)
        ev = es.emit("observation", "error")
        assert ev.cause_id == 42
        es.pop_cause()
        ev2 = es.emit("observation", "error")
        assert ev2.cause_id is None

    def test_log_state_change(self):
        es = EventStream("w1")
        ev = es.log_state_change("running", "started")
        assert ev.event_type == "state_change"
        assert ev.source == "system"

    def test_log_error(self):
        es = EventStream("w1")
        ev = es.log_error("oops", "ctx")
        assert ev.event_kind == "error"
        assert "oops" in ev.content


class TestEventStreamGetRecent:
    def test_recent_returns_all_when_small(self):
        es = EventStream("w1")
        for _ in range(5):
            es.emit("action", "tool_call")
        result = es.get_recent_events(max_events=50)
        assert len(result) == 5
        assert all("content" in r for r in result)

    def test_recent_trims_and_adds_summary(self):
        es = EventStream("w1")
        for i in range(60):
            es.emit("action", "tool_call", content={"i": i})
        result = es.get_recent_events(max_events=10)
        assert len(result) == 11  # 10 events + 1 summary
        assert result[0]["type"] == "summary"
        assert "50" in result[0]["content"]  # 50 omitted

    def test_recent_empty(self):
        es = EventStream("w1")
        assert es.get_recent_events() == []


class TestEventStreamJsonl:
    def test_write_and_replay(self, tmp_path):
        path = tmp_path / "events.jsonl"
        es = EventStream("w1")
        es.set_jsonl_path(path)
        es.emit("action", "tool_call", content="first")
        es.emit("observation", "error", content="second")

        es2 = EventStream("w1")
        es2.set_jsonl_path(path)
        replayed = es2.replay()
        # session_start is skipped; 2 events remain
        assert len(replayed) == 2
        assert replayed[0].event_kind == "tool_call"
        assert replayed[1].event_kind == "error"


class TestBuildCausalChain:
    def test_groups_by_cause(self):
        e1 = WorkerEvent(id=1, worker_id="w", event_type="a", event_kind="k", source="s", cause_id=None)
        e2 = WorkerEvent(id=2, worker_id="w", event_type="a", event_kind="k", source="s", cause_id=1)
        e3 = WorkerEvent(id=3, worker_id="w", event_type="a", event_kind="k", source="s", cause_id=1)
        chain = build_causal_chain([e1, e2, e3])
        assert 1 in chain
        assert len(chain[1]) == 2

    def test_empty(self):
        assert build_causal_chain([]) == {}


# ─── Reactions Tests ──────────────────────────────────────────────────────────

from reactions import ReactionConfig, ReactionExecutor, create_executor_from_config


class TestReactionConfig:
    def test_matches_event_type(self):
        cfg = ReactionConfig(name="t", event_type="error")
        assert cfg.matches("error")
        assert not cfg.matches("tool_call")

    def test_matches_regex(self):
        cfg = ReactionConfig(name="t", event_type="error", event_match=r"fail.*ed")
        assert cfg.matches("error", event_name="task failed")
        assert not cfg.matches("error", event_name="task done")

    def test_matches_no_regex(self):
        cfg = ReactionConfig(name="t", event_type="error")
        assert cfg.matches("error", event_name="anything")


class TestReactionExecutor:
    def test_no_trigger_below_threshold(self):
        ex = ReactionExecutor()
        for _ in range(2):
            ex.record_event("error", "tool failed")
        assert ex.get_active_reactions() == []

    def test_triggers_at_threshold(self):
        ex = ReactionExecutor()
        for _ in range(3):
            reactions = ex.record_event("error", "tool failed", event_content="exit code 1")
        assert len(reactions) > 0
        assert reactions[0].config.name == "repeated_tool_failure"

    def test_cooldown_prevents_re_trigger(self):
        ex = ReactionExecutor()
        for _ in range(3):
            ex.record_event("error", "t", event_content="exit code 1")
        # Trigger again immediately — should be blocked by cooldown
        result = ex.record_event("error", "t", event_content="exit code 1")
        assert result == []

    def test_reset_clears_state(self):
        ex = ReactionExecutor()
        for _ in range(3):
            ex.record_event("error", "t", event_content="exit code 1")
        ex.reset()
        assert ex.get_active_reactions() == []

    def test_acknowledge_resolves(self):
        ex = ReactionExecutor()
        for _ in range(3):
            ex.record_event("error", "t", event_content="exit code 1")
        ex.acknowledge_reaction("repeated_tool_failure")
        assert ex.get_active_reactions() == []

    def test_summary_format(self):
        ex = ReactionExecutor()
        s = ex.get_reaction_summary()
        assert "active" in s
        assert "configs" in s


class TestCreateExecutorFromConfig:
    def test_empty_config(self):
        ex = create_executor_from_config(None)
        assert isinstance(ex, ReactionExecutor)
        assert len(ex.configs) > 0  # uses defaults

    def test_custom_config(self):
        cfg = {"reactions": [{"name": "my_r", "event_type": "error", "threshold": 2}]}
        ex = create_executor_from_config(cfg)
        assert any(c.name == "my_r" for c in ex.configs)

    def test_invalid_entry_skipped(self):
        cfg = {"reactions": [{"invalid_key": 999}]}
        ex = create_executor_from_config(cfg)
        # invalid entry skipped; falls back to defaults
        assert isinstance(ex, ReactionExecutor)


# ─── SessionTree Tests ────────────────────────────────────────────────────────

from session_tree import SessionTree


class TestSessionTree:
    def test_write_and_read(self, tmp_path):
        tree = SessionTree(tmp_path / "session.jsonl")
        tree.session_start({"project": "clade"})
        uid = tree.user("hello")
        assert uid is not None
        entries = tree.entries()
        assert len(entries) == 2
        assert entries[0]["type"] == "session_start"
        assert entries[1]["type"] == "user"

    def test_type_filter(self, tmp_path):
        tree = SessionTree(tmp_path / "session.jsonl")
        tree.session_start({})
        tree.user("q1")
        tree.assistant("a1")
        assert len(tree.entries("user")) == 1
        assert len(tree.entries("assistant")) == 1

    def test_tool_call_and_result(self, tmp_path):
        tree = SessionTree(tmp_path / "session.jsonl")
        tc_id = tree.tool_call("Bash", {"cmd": "ls"})
        tree.tool_result(tc_id, "file.py")
        entries = tree.entries()
        assert entries[0]["type"] == "tool_call"
        assert entries[1]["type"] == "tool_result"
        assert entries[1]["toolCallId"] == tc_id

    def test_branch_increments_count(self, tmp_path):
        tree = SessionTree(tmp_path / "session.jsonl")
        sid = tree.session_start({})
        b1 = tree.branch("alt-1", sid)
        b2 = tree.branch("alt-2", sid)
        entries = tree.entries("branch")
        assert entries[0]["branchIndex"] == 1
        assert entries[1]["branchIndex"] == 2

    def test_compaction(self, tmp_path):
        tree = SessionTree(tmp_path / "session.jsonl")
        sid = tree.session_start({})
        tree.user("q")
        tree.compact("summary text", sid)
        entries = tree.entries("compaction")
        assert len(entries) == 1
        assert entries[0]["summary"] == "summary text"

    def test_get_entry(self, tmp_path):
        tree = SessionTree(tmp_path / "session.jsonl")
        uid = tree.user("hello")
        entry = tree.get_entry(uid)
        assert entry is not None
        assert entry["content"] == "hello"

    def test_root_id(self, tmp_path):
        tree = SessionTree(tmp_path / "session.jsonl")
        sid = tree.session_start({"k": "v"})
        assert tree.root_id() == sid

    def test_latest_id(self, tmp_path):
        tree = SessionTree(tmp_path / "session.jsonl")
        tree.session_start({})
        uid = tree.user("last")
        assert tree.latest_id() == uid

    def test_build_context_max(self, tmp_path):
        tree = SessionTree(tmp_path / "session.jsonl")
        tree.session_start({})
        for i in range(10):
            tree.user(f"msg-{i}")
        ctx = tree.build_context(max_entries=5)
        assert len(ctx) <= 5

    def test_children_of(self, tmp_path):
        tree = SessionTree(tmp_path / "session.jsonl")
        sid = tree.session_start({})
        u1 = tree.user("child1", parent_id=sid)
        u2 = tree.user("child2", parent_id=sid)
        children = tree.children_of(sid)
        ids = [c["id"] for c in children]
        assert u1 in ids
        assert u2 in ids

    def test_empty_file_returns_empty(self, tmp_path):
        tree = SessionTree(tmp_path / "session.jsonl")
        assert tree.entries() == []
        assert tree.root_id() is None
        assert tree.latest_id() is None


# ─── Tracing Tests ────────────────────────────────────────────────────────────

from tracing import (
    Span, SpanContext, Tracer, TracingService,
    start_task_span, start_llm_span, end_llm_span, start_tool_span,
)


class TestSpan:
    def test_duration_ms_none_when_open(self):
        s = Span("id", "trace", "test", "task", time.time())
        assert s.duration_ms is None

    def test_duration_ms_positive(self):
        t = time.time()
        s = Span("id", "trace", "test", "task", t, end_time=t + 1.0)
        assert abs(s.duration_ms - 1000.0) < 1

    def test_to_dict_has_duration(self):
        t = time.time()
        s = Span("id", "trace", "test", "task", t, end_time=t + 0.5)
        d = s.to_dict()
        assert "duration_ms" in d
        assert d["span_id"] == "id"


class TestSpanContext:
    def test_push_pop(self):
        ctx = SpanContext()
        s = Span("id", "t", "n", "task", time.time())
        ctx.push(s)
        assert ctx.current is s
        ctx.pop()
        assert ctx.current is None

    def test_parent(self):
        ctx = SpanContext()
        s1 = Span("s1", "t", "n1", "task", time.time())
        s2 = Span("s2", "t", "n2", "task", time.time())
        ctx.push(s1)
        ctx.push(s2)
        assert ctx.parent is s1


class TestTracer:
    def test_start_span(self):
        tr = Tracer()
        s = tr.start("my-phase", span_type="phase")
        assert s.name == "my-phase"
        assert s.span_type == "phase"
        assert s.end_time is None

    def test_end_span(self):
        tr = Tracer()
        s = tr.start("p")
        tr.end(s)
        assert s.end_time is not None
        assert s.status == "ok"

    def test_nested_spans_have_parent_id(self):
        tr = Tracer()
        parent = tr.start("outer")
        child = tr.start("inner")
        assert child.parent_id == parent.span_id

    def test_add_event(self):
        tr = Tracer()
        s = tr.start("p")
        tr.add_event("checkpoint", {"key": "val"})
        assert "_events" in s.attributes
        assert s.attributes["_events"][0]["name"] == "checkpoint"

    def test_write_creates_jsonl(self, tmp_path):
        tr = Tracer(output_dir=tmp_path)
        s = tr.start("phase")
        tr.end(s)
        path = tr.write()
        assert path is not None
        assert path.exists()
        lines = path.read_text().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["name"] == "phase"

    def test_end_all(self):
        tr = Tracer()
        tr.start("outer")
        tr.start("inner")
        tr.end_all(status="cancelled")
        for s in tr.spans:
            assert s.status == "cancelled"


class TestTracingService:
    def test_get_or_create_reuses(self):
        svc = TracingService()
        t1 = svc.get_or_create_tracer("w1")
        t2 = svc.get_or_create_tracer("w1")
        assert t1 is t2

    def test_start_and_end_span(self):
        svc = TracingService()
        s = svc.start_span("w2", "test-span")
        assert s is not None
        svc.end_span("w2", s)
        assert s.end_time is not None

    def test_write_trace_removes_tracer(self, tmp_path):
        svc = TracingService(base_dir=tmp_path)
        s = svc.start_span("w3", "phase")
        svc.end_span("w3", s)
        path = svc.write_trace("w3")
        assert path is not None
        assert "w3" not in svc._tracers


class TestConvenienceHelpers:
    def test_start_task_span(self):
        # Reset singleton so tmp tracer doesn't bleed
        TracingService._instance = TracingService()
        s = start_task_span("worker-x", "implement feature", task_id="t1")
        assert s is not None
        assert "task" in s.name

    def test_start_llm_span(self):
        TracingService._instance = TracingService()
        s = start_llm_span("worker-y", "claude-sonnet-4-6", prompt_tokens=500)
        assert s is not None
        assert s.attributes.get("model") == "claude-sonnet-4-6"
        assert s.attributes.get("prompt_tokens") == 500

    def test_end_llm_span_none_safe(self):
        # Should not raise
        end_llm_span(None, response_tokens=100)

    def test_start_tool_span(self):
        TracingService._instance = TracingService()
        s = start_tool_span("worker-z", "Bash", args={"cmd": "ls"})
        assert s is not None
        assert s.attributes["tool"] == "Bash"
