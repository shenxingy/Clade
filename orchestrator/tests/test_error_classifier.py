"""Tests for orchestrator/error_classifier.py.

Cover the failure-mode-to-action mapping. Failure paths matter more than
happy paths — wrong classification = wrong retry strategy = wasted cost.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from error_classifier import (  # noqa: E402
    ClassifiedError,
    FailoverReason,
    RetryDecision,
    classify,
    derive_retry_decision,
    parse_retry_prefix,
    summarize,
)


# ─── Status-code routing ─────────────────────────────────────────────────────

def test_401_is_auth() -> None:
    err = classify("401 Unauthorized: invalid api key")
    assert err.reason is FailoverReason.auth
    assert err.should_rotate_credential is True
    assert err.retryable is True


def test_403_is_auth() -> None:
    err = classify("HTTP 403 Forbidden")
    assert err.reason is FailoverReason.auth


def test_429_is_rate_limit() -> None:
    err = classify("429 Too Many Requests: rate limit exceeded")
    assert err.reason is FailoverReason.rate_limit
    assert err.backoff_seconds >= 10  # rate limit deserves a long backoff


def test_402_is_billing_and_aborts() -> None:
    err = classify("402 Payment Required: out of credits")
    assert err.reason is FailoverReason.billing
    assert err.abort is True
    assert err.retryable is False


def test_503_is_overloaded() -> None:
    err = classify("503 Service Unavailable: overloaded")
    assert err.reason is FailoverReason.overloaded
    assert err.retryable is True


def test_500_is_server_error() -> None:
    err = classify("500 Internal Server Error")
    assert err.reason is FailoverReason.server_error


def test_400_bad_request_aborts() -> None:
    err = classify("400 Bad Request: malformed body")
    assert err.reason is FailoverReason.format_error
    assert err.abort is True


def test_404_model_not_found_falls_back() -> None:
    err = classify("HTTP 404: model claude-foo-99 not found")
    assert err.reason is FailoverReason.model_not_found
    assert err.should_fallback_model is True


# ─── Pattern matches that beat status codes ─────────────────────────────────

def test_context_overflow_beats_400() -> None:
    """Anthropic returns context overflow as a 400 — the specific signal must win."""
    err = classify("400 Bad Request: prompt is too long for context window")
    assert err.reason is FailoverReason.context_overflow
    assert err.should_compress is True


def test_long_context_tier_marker() -> None:
    err = classify("This request requires the long-context tier")
    assert err.reason is FailoverReason.long_context_tier
    assert err.should_compress is True
    assert err.should_fallback_model is True


def test_payload_too_large() -> None:
    err = classify("413 Payload Too Large")
    assert err.reason is FailoverReason.payload_too_large
    assert err.should_compress is True


# ─── Subprocess control signals ──────────────────────────────────────────────

def test_timed_out_keyword_arg() -> None:
    err = classify("", timed_out=True)
    assert err.reason is FailoverReason.timeout
    assert err.retryable is True


def test_killed_signal_does_not_retry() -> None:
    err = classify("Process killed by SIGKILL")
    assert err.reason is FailoverReason.process_killed
    assert err.retryable is False


def test_nonzero_exit_unknown_stderr() -> None:
    err = classify("garbage output that doesn't match anything", exit_code=42)
    assert err.reason is FailoverReason.process_crashed
    assert err.retryable is True


def test_zero_exit_no_match_is_unknown() -> None:
    err = classify("success", exit_code=0)
    assert err.reason is FailoverReason.unknown


# ─── Edge cases ──────────────────────────────────────────────────────────────

def test_empty_stderr_no_exit() -> None:
    err = classify("")
    assert err.reason is FailoverReason.unknown
    assert err.retryable is True


def test_status_extraction() -> None:
    err = classify("status: 429 — too fast")
    assert err.status_code == 429


# ─── Retry decision (drives swarm-level requeueing) ────────────────────────

_FALLBACK = {"opus": "sonnet", "sonnet": "haiku"}


def _decide(stderr: str, *, attempt=1, max_attempts=2, model="sonnet", **kw):
    err = classify(stderr, **kw)
    return derive_retry_decision(
        err, attempt=attempt, max_attempts=max_attempts,
        current_model=model, model_fallback=_FALLBACK,
    )


def test_retry_rate_limit_returns_decision() -> None:
    d = _decide("429 Too Many Requests")
    assert d is not None
    assert d.new_description_prefix == "[AUTO-RETRY 2/2]"
    assert "rate_limit" in d.hint_block
    # rate_limit doesn't trigger model fallback
    assert d.model == "sonnet"


def test_retry_overloaded_returns_decision() -> None:
    d = _decide("503 Service Unavailable: overloaded")
    assert d is not None and "overloaded" in d.hint_block


def test_retry_timeout_returns_decision() -> None:
    d = _decide("", timed_out=True)
    assert d is not None and "timed out" in d.hint_block.lower()


def test_retry_context_overflow_compresses_and_downgrades() -> None:
    d = _decide("prompt is too long: 215000 tokens", model="sonnet")
    assert d is not None
    assert d.model == "haiku"  # fallback because should_compress=True
    assert "concise" in d.hint_block.lower()


def test_retry_long_context_tier_downgrades() -> None:
    d = _decide("requires long-context tier", model="opus")
    assert d is not None and d.model == "sonnet"


def test_retry_model_not_found_downgrades() -> None:
    d = _decide("HTTP 404: model claude-foo not found", model="opus")
    assert d is not None and d.model == "sonnet"


def test_no_retry_on_auth() -> None:
    """Auth errors need a human — never auto-retry."""
    assert _decide("401 Unauthorized: invalid api key") is None


def test_no_retry_on_billing() -> None:
    assert _decide("402 Payment Required: out of credits") is None


def test_no_retry_on_format_error() -> None:
    """Bad request = our request is malformed. Retrying won't fix it."""
    assert _decide("400 Bad Request: malformed body") is None


def test_no_retry_on_killed() -> None:
    assert _decide("Process killed by SIGKILL") is None


def test_no_retry_when_at_max_attempts() -> None:
    assert _decide("503 overloaded", attempt=2, max_attempts=2) is None


def test_no_retry_when_past_max_attempts() -> None:
    assert _decide("503 overloaded", attempt=5, max_attempts=2) is None


def test_retry_when_under_max_attempts() -> None:
    d = _decide("503 overloaded", attempt=1, max_attempts=3)
    assert d is not None and d.new_description_prefix == "[AUTO-RETRY 2/3]"


def test_retry_unknown_failures_are_retried() -> None:
    """Unknown class is retryable but conservative — single retry."""
    d = _decide("unknown weirdness", exit_code=1)
    assert d is not None  # process_crashed is retryable


def test_retry_decision_no_fallback_map() -> None:
    """Caller may pass empty/None fallback — model stays put."""
    err = classify("prompt is too long")
    d = derive_retry_decision(err, attempt=1, max_attempts=2,
                              current_model="opus", model_fallback={})
    assert d is not None
    assert d.model == "opus"  # no downgrade without map


# ─── parse_retry_prefix ────────────────────────────────────────────────────

def test_parse_prefix_basic() -> None:
    assert parse_retry_prefix("[AUTO-RETRY 2/3] hello") == (2, 3)


def test_parse_prefix_extra_whitespace() -> None:
    assert parse_retry_prefix("[AUTO-RETRY  10 / 20]  task body") == (10, 20)


def test_parse_prefix_no_match() -> None:
    assert parse_retry_prefix("hello world") is None
    assert parse_retry_prefix("") is None
    assert parse_retry_prefix("[STUCK-RETRY] foo") is None


def test_parse_prefix_only_at_start() -> None:
    """Must be a prefix — embedded mention doesn't count."""
    assert parse_retry_prefix("did [AUTO-RETRY 1/2] in middle") is None


def test_summarize_format() -> None:
    err = ClassifiedError(
        reason=FailoverReason.rate_limit,
        status_code=429,
        message="rate_limit",
        raw_excerpt="429 too many",
        backoff_seconds=30.0,
    )
    s = summarize(err)
    assert "rate_limit" in s
    assert "429" in s
    assert "retry+30s" in s
