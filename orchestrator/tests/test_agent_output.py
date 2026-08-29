"""Tests for reading a spawned agent's own usage report.

Fixtures are trimmed from real `claude -p` output captured against CLI 2.1.236
on 2026-08-29, not invented — the whole defect this module fixes was code that
parsed a shape the CLI has never emitted.
"""

import json

import pytest

from agent_output import AgentResult, absorb_agent_result, parse_agent_output
from config import HAIKU_MODEL  # dated snapshots may only be literals in config.py

# Trimmed from a real `--output-format stream-json --verbose` run. The hook and
# thinking_tokens system events are kept because a real log is full of them and
# the parser has to walk past them to the result.
STREAM_EVENTS = [
    {"type": "system", "subtype": "hook_started"},
    {"type": "system", "subtype": "init"},
    {"type": "system", "subtype": "thinking_tokens"},
    {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "hm"}]}},
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "OK"}]}},
    {"type": "rate_limit_event"},
    {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "num_turns": 1,
        "total_cost_usd": 0.01279555,
        "usage": {
            "input_tokens": 10,
            "output_tokens": 57,
            "cache_read_input_tokens": 37218,
            "cache_creation_input_tokens": 0,
        },
        "modelUsage": {
            HAIKU_MODEL: {
                "inputTokens": 13,
                "outputTokens": 98,
                "costUSD": 0.01279555,
                "canonicalModel": "claude-haiku-4-5",
            }
        },
        "result": "OK",
    },
    {"type": "system", "subtype": "hook_response"},
]

# The single object `--output-format json` emits.
SINGLE_RESULT = STREAM_EVENTS[-2]


def _stream(events=None) -> str:
    return "\n".join(json.dumps(e) for e in (events or STREAM_EVENTS)) + "\n"


class TestParseAgentOutput:
    def test_stream_json_yields_the_agents_own_cost(self):
        r = parse_agent_output(_stream())
        assert isinstance(r, AgentResult)
        assert r.total_cost_usd == pytest.approx(0.01279555)
        assert (r.input_tokens, r.output_tokens) == (10, 57)
        assert r.cache_read_input_tokens == 37218
        assert r.total_tokens == 67
        assert r.subtype == "success"
        assert r.is_error is False

    def test_single_json_object_is_read_the_same_way(self):
        r = parse_agent_output(json.dumps(SINGLE_RESULT))
        assert r is not None
        assert r.total_cost_usd == pytest.approx(0.01279555)
        assert r.text == "OK"

    def test_per_model_usage_survives(self):
        """Needed to price a run that spanned models; nothing had it before."""
        r = parse_agent_output(_stream())
        assert list(r.model_usage) == [HAIKU_MODEL]
        assert r.model_usage[HAIKU_MODEL]["costUSD"] == pytest.approx(0.01279555)

    def test_text_excludes_thinking_and_tool_calls(self):
        """Only prose reaches downstream consumers, not reasoning or tool JSON."""
        events = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "thinking", "thinking": "secret reasoning"},
                        {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
                        {"type": "text", "text": "done"},
                    ]
                },
            },
            SINGLE_RESULT,
        ]
        r = parse_agent_output(_stream(events))
        assert "secret reasoning" not in r.text
        assert "Bash" not in r.text
        assert "done" in r.text

    def test_multi_turn_text_is_accumulated_not_truncated_to_the_last(self):
        """`result` holds only the final turn; earlier output must not be lost."""
        events = [
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "first"}]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "second"}]}},
            {**SINGLE_RESULT, "result": "second"},
        ]
        r = parse_agent_output(_stream(events))
        assert "first" in r.text and "second" in r.text

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "OK\n",  # plain --output-format text, the pre-2026-08-29 default
            "Some prose the agent wrote.\nMore prose.\n",
            "   ",
        ],
    )
    def test_non_structured_output_is_none_not_a_zero_cost_run(self, raw):
        """None means "no report", which is not the same as "cost nothing".

        Conflating the two is the original defect: a $12 Opus run recorded as
        $0.00 looks exactly like a free one to the budget gate.
        """
        assert parse_agent_output(raw) is None

    def test_stream_without_a_result_event_is_none(self):
        """A crash or kill mid-run has no totals to report."""
        assert parse_agent_output(_stream(STREAM_EVENTS[:5])) is None

    def test_truncated_and_garbage_lines_are_skipped(self):
        raw = _stream() + '{"type": "result", "total_cost'  # cut off mid-write
        r = parse_agent_output(raw)
        assert r is not None and r.total_cost_usd == pytest.approx(0.01279555)

    def test_missing_usage_block_does_not_raise(self):
        r = parse_agent_output(json.dumps({"type": "result", "total_cost_usd": 0.5}))
        assert r is not None
        assert r.total_cost_usd == 0.5
        assert (r.input_tokens, r.output_tokens) == (0, 0)

    def test_cost_absent_is_none_so_the_caller_can_fall_back_to_estimating(self):
        r = parse_agent_output(json.dumps({"type": "result", "usage": {"input_tokens": 5}}))
        assert r is not None
        assert r.total_cost_usd is None


class TestAbsorbAgentResult:
    def test_collapses_the_log_to_prose_for_downstream_consumers(self, tmp_path):
        """Failure context, TLDR, distillation and the observation contract all
        read this file as text; they must not start seeing JSONL."""
        log = tmp_path / "worker.log"
        log.write_text(_stream())
        r = absorb_agent_result(log)
        assert r is not None
        assert log.read_text() == "OK"
        assert "{" not in log.read_text()

    def test_leaves_a_plain_text_log_untouched(self, tmp_path):
        log = tmp_path / "worker.log"
        log.write_text("just prose\n")
        assert absorb_agent_result(log) is None
        assert log.read_text() == "just prose\n"

    def test_none_and_missing_paths_are_safe(self, tmp_path):
        assert absorb_agent_result(None) is None
        assert absorb_agent_result(tmp_path / "nope.log") is None

    def test_unwritable_log_still_returns_the_numbers(self, tmp_path, monkeypatch):
        """A worker must not fail because its log could not be rewritten."""
        log = tmp_path / "worker.log"
        log.write_text(_stream())
        real_write = type(log).write_text

        def boom(self, *a, **k):
            if self == log:
                raise OSError("read-only")
            return real_write(self, *a, **k)

        monkeypatch.setattr(type(log), "write_text", boom)
        r = absorb_agent_result(log)
        assert r is not None and r.total_cost_usd == pytest.approx(0.01279555)


class TestResolveWorkerUsage:
    """config.resolve_worker_usage picks which figure to trust."""

    def test_prefers_the_agents_own_cost_over_any_local_estimate(self):
        from config import resolve_worker_usage

        r = parse_agent_output(_stream())
        tokens_in, tokens_out, cost = resolve_worker_usage(r, None, "claude-opus-5")
        assert (tokens_in, tokens_out) == (10, 57)
        # Not the Opus rate applied to 10/57 tokens — the agent's real figure,
        # which includes the 37k cache read no local estimate can see.
        assert cost == pytest.approx(0.01279555)

    def test_estimates_when_the_report_carries_no_cost(self):
        from config import resolve_worker_usage

        r = parse_agent_output(json.dumps({"type": "result", "usage": {"output_tokens": 1_000_000}}))
        _, _, cost = resolve_worker_usage(r, None, "claude-opus-5")
        assert cost == pytest.approx(25.0)  # Opus output rate, not Sonnet's 15.0

    def test_falls_back_to_scraping_when_there_is_no_report(self, tmp_path):
        from config import resolve_worker_usage

        log = tmp_path / "worker.log"
        log.write_text("input tokens: 1000\noutput tokens: 2000\n")
        tokens_in, tokens_out, cost = resolve_worker_usage(None, log, "claude-haiku-4-5")
        assert (tokens_in, tokens_out) == (1000, 2000)
        assert cost == pytest.approx(1000 * 1.0 / 1e6 + 2000 * 5.0 / 1e6)

    def test_no_report_and_no_log_is_zero_not_a_crash(self):
        from config import resolve_worker_usage

        assert resolve_worker_usage(None, None, "claude-opus-5") == (0, 0, 0.0)
