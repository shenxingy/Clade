"""Tests for extracted worker modules: condensers, worker_utils, worker_hydrate, worker_tldr."""

import pytest

from worker_tldr import _extract_tldr_sections, _generate_code_tldr
from condensers import (
    NoOpCondenser,
    RecentEventsCondenser,
    ObservationMaskingCondenser,
)
from worker_utils import (
    _truncate_output,
    _strip_error_context,
    LoopDetectionService,
    MAX_LINES,
    MAX_BYTES,
)
from worker_hydrate import _parse_linked_references


# ─── condensers ───────────────────────────────────────────────────────────────

class TestNoOpCondenser:
    def test_returns_events_unchanged(self):
        events = [{"type": "msg", "content": "hi"}, {"type": "tool_result", "content": "out"}]
        assert NoOpCondenser().condense(events) == events

    def test_empty_list(self):
        assert NoOpCondenser().condense([]) == []


class TestRecentEventsCondenser:
    def test_passthrough_when_under_limit(self):
        events = [{"type": "msg", "content": str(i)} for i in range(5)]
        result = RecentEventsCondenser(keep=10).condense(events)
        assert result == events

    def test_truncates_older_events(self):
        events = [{"type": "msg", "content": str(i)} for i in range(20)]
        result = RecentEventsCondenser(keep=5).condense(events)
        assert len(result) == 6  # 1 summary + 5 recent
        assert result[0]["type"] == "summary"
        assert "15 earlier" in result[0]["content"]
        assert result[1:] == events[-5:]

    def test_exactly_at_limit(self):
        events = [{"type": "msg", "content": str(i)} for i in range(10)]
        result = RecentEventsCondenser(keep=10).condense(events)
        assert result == events


class TestObservationMaskingCondenser:
    def test_small_content_unchanged(self):
        events = [{"type": "tool_result", "content": "hello"}]
        result = ObservationMaskingCondenser(max_obs_bytes=100).condense(events)
        assert result[0]["content"] == "hello"

    def test_large_content_truncated(self):
        big = "x" * 5000
        events = [{"type": "tool_result", "content": big}]
        result = ObservationMaskingCondenser(max_obs_bytes=100).condense(events)
        content = result[0]["content"]
        assert len(content.encode()) < len(big)
        assert "truncated by condenser" in content

    def test_non_observation_type_unchanged(self):
        big = "x" * 5000
        events = [{"type": "msg", "content": big}]
        result = ObservationMaskingCondenser(max_obs_bytes=100).condense(events)
        assert result[0]["content"] == big

    def test_original_event_not_mutated(self):
        orig = {"type": "observation", "content": "y" * 5000}
        events = [orig]
        ObservationMaskingCondenser(max_obs_bytes=100).condense(events)
        assert len(orig["content"]) == 5000  # original unchanged


# ─── worker_utils ─────────────────────────────────────────────────────────────

class TestTruncateOutput:
    def test_short_text_unchanged(self):
        text = "hello\nworld"
        assert _truncate_output(text) == text

    def test_line_truncation(self):
        lines = "\n".join(str(i) for i in range(MAX_LINES + 50))
        result = _truncate_output(lines, max_lines=MAX_LINES)
        assert f"truncated 50 lines" in result
        assert len(result.splitlines()) <= MAX_LINES + 1  # content + marker line

    def test_byte_truncation(self):
        text = "a" * (MAX_BYTES + 1000)
        result = _truncate_output(text, max_bytes=MAX_BYTES)
        assert "truncated to" in result
        assert len(result.encode()) <= MAX_BYTES + 100  # marker adds a bit

    def test_empty_string(self):
        assert _truncate_output("") == ""


class TestStripErrorContext:
    def test_none_input(self):
        assert _strip_error_context(None) == ""

    def test_empty_string(self):
        assert _strip_error_context("") == ""

    def test_short_text_unchanged(self):
        result = _strip_error_context("error: file not found")
        assert "error: file not found" in result

    def test_long_text_truncated(self):
        long_error = "E" * 1000
        result = _strip_error_context(long_error)
        assert len(result) <= 500

    def test_newlines_replaced(self):
        result = _strip_error_context("line1\nline2\nline3")
        assert "\n" not in result


class TestLoopDetectionService:
    def test_no_loop_initially(self):
        svc = LoopDetectionService()
        assert not svc.is_looping
        assert svc.reason is None

    def test_tool_repetition_triggers_loop(self):
        svc = LoopDetectionService()
        for _ in range(4):
            svc.track_tool_call("Read", "/some/file.py")
            assert not svc.is_looping
        svc.track_tool_call("Read", "/some/file.py")
        assert svc.is_looping
        assert "repeated_tool_args" in svc.reason

    def test_different_args_no_loop(self):
        svc = LoopDetectionService()
        for i in range(10):
            svc.track_tool_call("Read", f"/file{i}.py")
        assert not svc.is_looping

    def test_content_repetition_triggers_loop(self):
        svc = LoopDetectionService()
        for _ in range(9):
            svc.track_content_hash("same output content")
            assert not svc.is_looping
        svc.track_content_hash("same output content")
        assert svc.is_looping
        assert "repeated_content" in svc.reason

    def test_excessive_turns_triggers_loop(self):
        svc = LoopDetectionService()
        for _ in range(29):
            svc.track_turn()
            assert not svc.is_looping
        svc.track_turn()
        assert svc.is_looping
        assert "excessive_turns" in svc.reason

    def test_empty_content_not_tracked(self):
        svc = LoopDetectionService()
        for _ in range(20):
            svc.track_content_hash("")
        assert not svc.is_looping


# ─── worker_hydrate ───────────────────────────────────────────────────────────

class TestParseLinkedReferences:
    def test_bare_issue_ref(self):
        refs = _parse_linked_references("see #123 for details")
        assert "#123" in refs["issues"]

    def test_owner_repo_issue_ref(self):
        refs = _parse_linked_references("fixes owner/repo#456")
        assert "owner/repo#456" in refs["issues"]

    def test_github_issue_url(self):
        refs = _parse_linked_references(
            "see https://github.com/acme/myrepo/issues/789"
        )
        assert "acme/myrepo#789" in refs["issues"]

    def test_github_pr_url(self):
        refs = _parse_linked_references(
            "merged https://github.com/acme/myrepo/pull/42"
        )
        assert "acme/myrepo#42" in refs["prs"]

    def test_generic_url(self):
        refs = _parse_linked_references("see https://example.com/docs for more")
        assert any("example.com" in u for u in refs["urls"])

    def test_url_trailing_punctuation_stripped(self):
        refs = _parse_linked_references("see https://example.com/path.")
        assert "https://example.com/path" in refs["urls"]

    def test_empty_text(self):
        refs = _parse_linked_references("")
        assert refs["issues"] == []
        assert refs["prs"] == []
        assert refs["urls"] == []

    def test_no_references(self):
        refs = _parse_linked_references("no links here at all")
        assert refs["issues"] == []
        assert refs["prs"] == []
        assert refs["urls"] == []


# ─── worker_tldr ──────────────────────────────────────────────────────────────

class TestExtractTldrSections:
    def test_single_section(self):
        tldr = "## foo/bar.py\nclass Foo\n  def method()"
        sections = _extract_tldr_sections(tldr)
        assert "foo/bar.py" in sections
        assert "class Foo" in sections["foo/bar.py"]

    def test_multiple_sections(self):
        tldr = "## a.py\nclass A\n\n## b.py\nclass B\n"
        sections = _extract_tldr_sections(tldr)
        assert set(sections.keys()) == {"a.py", "b.py"}

    def test_empty_string(self):
        assert _extract_tldr_sections("") == {}

    def test_no_sections(self):
        assert _extract_tldr_sections("no headers here") == {}

    def test_preserves_content(self):
        tldr = "## path/to/file.ts\nexport class Foo\n  constructor()\n  method()"
        sections = _extract_tldr_sections(tldr)
        assert "path/to/file.ts" in sections
        content = sections["path/to/file.ts"]
        assert "constructor()" in content
        assert "method()" in content
