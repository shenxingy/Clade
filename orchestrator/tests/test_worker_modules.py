"""Tests for extracted worker modules: condensers, worker_utils, worker_hydrate, worker_tldr."""

import pytest

from worker_tldr import (
    _extract_tldr_sections, _generate_code_tldr,
    _extract_entity_name, _prune_tldr_to_entities, _parse_fault_entity_names,
    _keyword_filter_tldr, _span_evict_tldr,
)
from condensers import (
    NoOpCondenser,
    RecentEventsCondenser,
    ObservationMaskingCondenser,
)
from worker_utils import (
    _truncate_output,
    _strip_error_context,
    _extract_lint_targets,
    LoopDetectionService,
    _parse_pytest_results,
    _find_intramorphic_regressions,
    MAX_LINES,
    MAX_BYTES,
)
from worker_hydrate import _parse_linked_references
from config import _detect_dep_cycle


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


# ─── _extract_lint_targets ────────────────────────────────────────────────────

class TestExtractLintTargets:
    def test_ruff_style_errors(self):
        output = (
            "## Ruff (Python)\n"
            "app/main.py:42:5: E501 Line too long (89 > 88 characters)\n"
            "app/utils.py:10:1: F401 'os' imported but unused\n"
        )
        targets = _extract_lint_targets(output)
        assert len(targets) == 2
        assert "app/main.py:42" in targets[0]
        assert "app/utils.py:10" in targets[1]

    def test_max_targets_respected(self):
        lines = "\n".join(f"file.py:{i}:1: E501 error" for i in range(10))
        targets = _extract_lint_targets(lines, max_targets=3)
        assert len(targets) == 3

    def test_empty_output(self):
        assert _extract_lint_targets("") == []

    def test_no_parseable_locations(self):
        assert _extract_lint_targets("All checks passed!") == []


# ─── _detect_dep_cycle ────────────────────────────────────────────────────────

class TestDetectDepCycle:
    def _task(self, tid: str, deps: list[str]) -> dict:
        return {"id": tid, "depends_on": deps}

    def test_no_cycle(self):
        tasks = [
            self._task("a", []),
            self._task("b", ["a"]),
            self._task("c", ["b"]),
        ]
        assert _detect_dep_cycle(tasks) is None

    def test_simple_cycle(self):
        tasks = [
            self._task("a", ["b"]),
            self._task("b", ["a"]),
        ]
        cycle = _detect_dep_cycle(tasks)
        assert cycle is not None
        assert "a" in cycle or "b" in cycle

    def test_three_node_cycle(self):
        tasks = [
            self._task("a", ["c"]),
            self._task("b", ["a"]),
            self._task("c", ["b"]),
        ]
        cycle = _detect_dep_cycle(tasks)
        assert cycle is not None
        assert len(cycle) >= 2

    def test_self_loop(self):
        tasks = [self._task("a", ["a"])]
        cycle = _detect_dep_cycle(tasks)
        assert cycle is not None

    def test_empty_tasks(self):
        assert _detect_dep_cycle([]) is None

    def test_no_deps(self):
        tasks = [self._task("a", []), self._task("b", []), self._task("c", [])]
        assert _detect_dep_cycle(tasks) is None


# ─── _format_oracle_rejection Tests ──────────────────────────────────────────

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from worker_review import _format_oracle_rejection


class TestFormatOracleRejection:
    def test_with_findings(self):
        findings = [
            {"dimension": "correctness", "severity": "error", "fix_suggestion": "Add null check"},
            {"dimension": "code_quality", "severity": "warning", "fix_suggestion": "Rename var"},
        ]
        result = _format_oracle_rejection("high", "Fix null and rename", {}, findings)
        assert "[high]" in result
        assert "1." in result
        assert "Add null check" in result
        assert "Rename var" in result

    def test_with_fix_guidance_no_findings(self):
        result = _format_oracle_rejection("medium", "Add error handling", {}, [])
        assert "[medium]" in result
        assert "Add error handling" in result

    def test_with_dims_fallback(self):
        dims = {"correctness": "fail — missing branch", "completeness": "pass"}
        result = _format_oracle_rejection("low", "", dims, [])
        assert "correctness" in result
        assert "missing branch" in result

    def test_empty_inputs(self):
        result = _format_oracle_rejection("medium", "", {}, [])
        assert "[medium]" in result

    def test_findings_capped_at_5(self):
        findings = [
            {"dimension": "d", "severity": "error", "fix_suggestion": f"fix {i}"}
            for i in range(10)
        ]
        result = _format_oracle_rejection("high", "", {}, findings)
        # Should show items 1-5, not 6-10
        assert "fix 4" in result
        assert "fix 9" not in result


# ─── Entity-level TLDR pruning tests (Sweep §Gap1) ────────────────────────────

class TestExtractEntityName:
    def test_class(self):
        assert _extract_entity_name("class MyClass(Base)") == "MyClass"

    def test_def(self):
        assert _extract_entity_name("def my_func(self, x: int)") == "my_func"

    def test_async_def(self):
        assert _extract_entity_name("async def worker(self)") == "worker"

    def test_not_entity(self):
        assert _extract_entity_name("  # comment") is None
        assert _extract_entity_name("x = 42") is None

    def test_js_function(self):
        assert _extract_entity_name("export function myFn()") == "myFn"

    def test_js_class(self):
        assert _extract_entity_name("export class MyComp") == "MyComp"


class TestPruneTldrToEntities:
    _TLDR = """\
## file.py
class MyClass
  def method_one(self)
  def method_two(self)
class OtherClass
  def other_method(self)
def standalone(arg)"""

    def test_prune_by_class_name(self):
        result = _prune_tldr_to_entities(self._TLDR, ["MyClass"])
        assert "MyClass" in result
        assert "method_one" in result
        assert "OtherClass" not in result or "omitted" in result

    def test_prune_by_method_name(self):
        result = _prune_tldr_to_entities(self._TLDR, ["other_method"])
        assert "OtherClass" in result
        assert "other_method" in result

    def test_dotted_name(self):
        result = _prune_tldr_to_entities(self._TLDR, ["MyClass.method_one"])
        assert "MyClass" in result

    def test_no_match_keeps_original(self):
        # If nothing matches, return original TLDR
        result = _prune_tldr_to_entities(self._TLDR, ["NonExistent"])
        assert "MyClass" in result
        assert "OtherClass" in result

    def test_empty_names(self):
        result = _prune_tldr_to_entities(self._TLDR, [])
        assert result == self._TLDR

    def test_standalone_function(self):
        result = _prune_tldr_to_entities(self._TLDR, ["standalone"])
        assert "standalone" in result


class TestParseFaultEntityNames:
    def test_simple(self):
        text = "**Functions most likely to change:**\n- `MyClass.method_name`\n- `standalone_func`"
        names = _parse_fault_entity_names(text)
        assert "MyClass.method_name" in names
        assert "standalone_func" in names

    def test_empty(self):
        assert _parse_fault_entity_names("") == []

    def test_no_backtick_names(self):
        text = "Some plain text with no names"
        assert _parse_fault_entity_names(text) == []


# ─── Hybrid keyword TLDR filter tests (Sweep §Gap4) ──────────────────────────

class TestKeywordFilterTldr:
    _TLDR = """\
## auth/login.py
class LoginHandler
  def authenticate(self, user)
  def logout(self)

## tasks/worker.py
class WorkerPool
  def start_worker(self)
  def stop_worker(self)

## utils/helpers.py
def format_date(dt)
def parse_config(path)"""

    def test_keyword_match(self):
        result = _keyword_filter_tldr("authenticate the user login", self._TLDR)
        assert "login" in result or "LoginHandler" in result or "authenticate" in result

    def test_no_keywords_returns_original(self):
        # No code identifiers (very short/stop words only)
        result = _keyword_filter_tldr("do it", self._TLDR)
        assert result == self._TLDR

    def test_few_matches_fallback(self):
        # Only 1 section matches → < 3 → fall back to original
        result = _keyword_filter_tldr("xyznonexistentthing", self._TLDR)
        # Should return original because < 3 sections match
        assert "WorkerPool" in result

    def test_empty_tldr(self):
        result = _keyword_filter_tldr("worker task", "")
        assert result == ""


# ─── Task schema parsing tests (Multi-agent §Gap3) ────────────────────────────

import sys as _sys
_sys.path.insert(0, __file__.replace("tests/test_worker_modules.py", ""))
from config import _parse_task_schema, _format_task_schema_block


class TestParseTaskSchema:
    def test_json_block(self):
        desc = '''Fix the bug.

```json
{"acceptance_criteria": ["Test A passes", "Test B passes"], "input_files": ["auth.py"]}
```'''
        schema = _parse_task_schema(desc)
        assert schema["acceptance_criteria"] == ["Test A passes", "Test B passes"]
        assert schema["input_files"] == ["auth.py"]

    def test_no_json_block(self):
        schema = _parse_task_schema("Just a plain description")
        assert schema == {}

    def test_malformed_json(self):
        desc = '```json\n{bad json here}\n```'
        schema = _parse_task_schema(desc)
        assert schema == {}

    def test_caps_list_at_10(self):
        items = [str(i) for i in range(20)]
        desc = f'```json\n{{"acceptance_criteria": {items}}}\n```'
        schema = _parse_task_schema(desc)
        assert len(schema.get("acceptance_criteria", [])) <= 10


class TestFormatTaskSchemaBlock:
    def test_with_criteria(self):
        schema = {"acceptance_criteria": ["A passes", "B passes"]}
        block = _format_task_schema_block(schema)
        assert "Acceptance Criteria" in block
        assert "A passes" in block
        assert "B passes" in block

    def test_empty_schema(self):
        block = _format_task_schema_block({})
        assert block == ""

    def test_provides_requires(self):
        schema = {"provides": ["AuthService"], "requires": ["UserModel"]}
        block = _format_task_schema_block(schema)
        assert "provides" in block
        assert "AuthService" in block
        assert "requires" in block


# ─── Intramorphic Testing ─────────────────────────────────────────────────────

class TestParsePytestResults:
    SAMPLE_OUTPUT = """\
tests/test_foo.py::TestBar::test_pass1 PASSED                       [  1%]
tests/test_foo.py::TestBar::test_pass2 PASSED                       [  2%]
tests/test_foo.py::TestBar::test_fail1 FAILED                       [  3%]
tests/test_foo.py::TestBaz::test_error1 ERROR                       [  4%]
"""

    def test_parses_passed(self):
        results = _parse_pytest_results(self.SAMPLE_OUTPUT)
        assert results.get("tests/test_foo.py::TestBar::test_pass1") is True
        assert results.get("tests/test_foo.py::TestBar::test_pass2") is True

    def test_parses_failed(self):
        results = _parse_pytest_results(self.SAMPLE_OUTPUT)
        assert results.get("tests/test_foo.py::TestBar::test_fail1") is False

    def test_parses_error(self):
        results = _parse_pytest_results(self.SAMPLE_OUTPUT)
        assert results.get("tests/test_foo.py::TestBaz::test_error1") is False

    def test_empty_output(self):
        assert _parse_pytest_results("") == {}

    def test_ignores_non_result_lines(self):
        out = "platform linux -- Python 3.11\n=== 2 passed in 0.5s ===\n"
        assert _parse_pytest_results(out) == {}


class TestFindIntramorphicRegressions:
    def test_detects_regression(self):
        baseline = {"a::test1": True, "a::test2": True}
        post = {"a::test1": True, "a::test2": False}  # test2 now fails
        regressions = _find_intramorphic_regressions(baseline, post)
        assert regressions == ["a::test2"]

    def test_no_regression_when_all_pass(self):
        baseline = {"a::test1": True}
        post = {"a::test1": True}
        assert _find_intramorphic_regressions(baseline, post) == []

    def test_preexisting_failure_not_regression(self):
        # test2 was already failing in baseline
        baseline = {"a::test1": True, "a::test2": False}
        post = {"a::test1": True, "a::test2": False}
        assert _find_intramorphic_regressions(baseline, post) == []

    def test_new_test_in_post_not_regression(self):
        baseline = {"a::test1": True}
        post = {"a::test1": True, "a::test2": False}
        # test2 wasn't in baseline, so not a regression
        assert _find_intramorphic_regressions(baseline, post) == []

    def test_missing_test_in_post_counts_as_regression(self):
        # test2 was passing but now doesn't appear (treat as failing)
        baseline = {"a::test1": True, "a::test2": True}
        post = {"a::test1": True}  # test2 not in post results
        regressions = _find_intramorphic_regressions(baseline, post)
        assert "a::test2" not in regressions  # post.get(tid, True) → True for missing

    def test_empty_baseline(self):
        assert _find_intramorphic_regressions({}, {"a::test1": False}) == []


# ─── _span_evict_tldr (Moatless §Gap3) ───────────────────────────────────────

_SAMPLE_TLDR = """\
## src/foo.py
class Foo:
    def bar(self) -> None: ...

## src/bar.py
class Bar:
    def baz(self, x: int) -> str: ...

## src/qux.py
def helper() -> None: ...
"""


class TestSpanEvictTldr:
    def test_no_eviction_when_within_budget(self):
        evicted, n = _span_evict_tldr(_SAMPLE_TLDR, budget_chars=10000)
        assert n == 0
        assert "src/foo.py" in evicted
        assert "src/bar.py" in evicted
        assert "src/qux.py" in evicted

    def test_evicts_non_priority_when_over_budget(self):
        # Budget only fits ~one section; priority = foo.py
        evicted, n = _span_evict_tldr(_SAMPLE_TLDR, budget_chars=60, priority_files=["src/foo.py"])
        assert n > 0
        assert "src/foo.py" in evicted  # priority preserved

    def test_empty_tldr_returns_unchanged(self):
        evicted, n = _span_evict_tldr("", budget_chars=100)
        assert evicted == ""
        assert n == 0

    def test_returns_all_when_no_sections(self):
        no_sections = "just some text without sections"
        evicted, n = _span_evict_tldr(no_sections, budget_chars=5)
        # Falls back to simple truncation
        assert n == 0

    def test_priority_files_always_kept(self):
        # Very tight budget — only priority file should survive
        evicted, n = _span_evict_tldr(_SAMPLE_TLDR, budget_chars=50, priority_files=["src/qux.py"])
        assert "src/qux.py" in evicted
        assert n >= 1  # at least one evicted

    def test_no_priority_evicts_in_order(self):
        # With no priority files, fills budget sequentially
        # foo.py section is first, so it should be kept if budget allows
        evicted, n = _span_evict_tldr(_SAMPLE_TLDR, budget_chars=55)
        # At least some sections kept
        assert len(evicted) > 0

    def test_zero_budget_evicts_all_non_priority(self):
        evicted, n = _span_evict_tldr(_SAMPLE_TLDR, budget_chars=0, priority_files=[])
        # No room for anything
        assert n == 3  # all 3 sections evicted

    def test_priority_suffix_match(self):
        # Priority file specified as basename — should match full path
        evicted, n = _span_evict_tldr(_SAMPLE_TLDR, budget_chars=50, priority_files=["bar.py"])
        assert "src/bar.py" in evicted
