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
    classify,
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
