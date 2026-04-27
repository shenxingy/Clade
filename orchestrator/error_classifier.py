"""
error_classifier.py — Structured taxonomy for Claude Code subprocess failures.

Leaf module. No internal deps.

Worker (worker.py) and SwarmManager (swarm.py) call `classify(stderr, exit_code)`
to turn an opaque subprocess failure into a `ClassifiedError` with recovery
hints (retryable / should_compress / should_rotate / should_fallback / abort).

Inspired by Hermes Agent's `agent/error_classifier.py` taxonomy, narrowed
to the failure modes Clade actually sees from `claude -p` subprocesses.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from typing import Optional


# ─── Error taxonomy ───────────────────────────────────────────────────────────

class FailoverReason(enum.Enum):
    """Why a Claude subprocess failed — drives the recovery strategy."""

    # Auth
    auth = "auth"                          # 401/403 — token refresh / re-login
    auth_permanent = "auth_permanent"      # auth refresh failed — abort

    # Quota / billing / rate
    rate_limit = "rate_limit"              # 429 — exponential backoff
    billing = "billing"                    # 402 / credits exhausted — abort
    long_context_tier = "long_context_tier"  # 1M-context tier gating — drop to 200k

    # Server-side
    overloaded = "overloaded"              # 503/529 — provider overloaded, backoff
    server_error = "server_error"          # 500/502 — retry with backoff
    timeout = "timeout"                    # subprocess wall-clock timeout

    # Context / payload
    context_overflow = "context_overflow"  # too many tokens — compress + retry
    payload_too_large = "payload_too_large"  # 413 — drop large attachments

    # Request format
    format_error = "format_error"          # 400 bad request — abort
    model_not_found = "model_not_found"    # 404 / unknown model — fallback model

    # Subprocess control
    process_killed = "process_killed"      # SIGKILL/SIGTERM — likely user/system
    process_crashed = "process_crashed"    # non-zero exit, no recognizable msg

    # Catch-all
    unknown = "unknown"                    # unclassifiable — single retry then surface


# ─── Classification result ────────────────────────────────────────────────────

@dataclass
class ClassifiedError:
    """Structured classification with recovery hints. The retry layer reads
    the boolean hints rather than re-classifying the same error repeatedly."""

    reason: FailoverReason
    status_code: Optional[int] = None
    message: str = ""
    raw_excerpt: str = ""

    retryable: bool = True
    backoff_seconds: float = 2.0
    should_compress: bool = False
    should_rotate_credential: bool = False
    should_fallback_model: bool = False
    abort: bool = False

    extra: dict = field(default_factory=dict)


# ─── Classification rules ─────────────────────────────────────────────────────
# Order matters — earlier patterns win. Keep most specific first.

_STATUS_RE = re.compile(r"\b(?:status|HTTP)\s*[:=]?\s*(\d{3})\b", re.IGNORECASE)
_PATTERNS: list[tuple[re.Pattern, FailoverReason]] = [
    # Context overflow comes first — Anthropic returns this as a 400 sometimes,
    # so we want our specific signal to beat the generic format_error rule.
    (re.compile(r"context.{0,8}(window|length|too.{0,4}long|exceed)", re.I), FailoverReason.context_overflow),
    (re.compile(r"prompt is too long|reduce.{0,8}(prompt|input)", re.I), FailoverReason.context_overflow),
    (re.compile(r"long.context.{0,12}tier|extra usage tier", re.I), FailoverReason.long_context_tier),

    (re.compile(r"\b401\b|unauthorized|invalid[_ -]?api[_ -]?key|authentication", re.I), FailoverReason.auth),
    (re.compile(r"\b403\b|forbidden|permission.denied", re.I), FailoverReason.auth),
    (re.compile(r"\b402\b|insufficient.{0,4}credit|out of credits|credit.{0,4}exhausted|payment required", re.I), FailoverReason.billing),
    (re.compile(r"\b429\b|rate.?limit|too many requests|quota.exceeded", re.I), FailoverReason.rate_limit),

    (re.compile(r"\b503\b|\b529\b|overloaded|service unavailable", re.I), FailoverReason.overloaded),
    (re.compile(r"\b502\b|bad gateway", re.I), FailoverReason.server_error),
    (re.compile(r"\b500\b|internal server error", re.I), FailoverReason.server_error),

    (re.compile(r"timed?.out|timeout|deadline exceeded", re.I), FailoverReason.timeout),

    (re.compile(r"\b413\b|payload too large|request.{0,4}too.{0,4}large", re.I), FailoverReason.payload_too_large),

    (re.compile(r"\b404\b.{0,80}(model|not found)|unknown.model|model.{0,8}not.{0,4}found", re.I), FailoverReason.model_not_found),
    (re.compile(r"\b400\b|bad request|invalid request", re.I), FailoverReason.format_error),

    (re.compile(r"killed|sigkill|sigterm|terminated by signal", re.I), FailoverReason.process_killed),
]


def _extract_status(text: str) -> Optional[int]:
    m = _STATUS_RE.search(text)
    if m:
        try:
            return int(m.group(1))
        except (TypeError, ValueError):
            return None
    return None


def _excerpt(text: str, limit: int = 240) -> str:
    """Pick the shortest informative slice of stderr for logging."""
    if not text:
        return ""
    # Prefer a line that contains 'error' or a status code.
    for line in text.splitlines():
        if re.search(r"\berror\b|\b[45]\d\d\b", line, re.I):
            return line.strip()[:limit]
    return text.strip()[:limit]


# ─── Public API ───────────────────────────────────────────────────────────────

def classify(
    stderr: str = "",
    *,
    exit_code: Optional[int] = None,
    timed_out: bool = False,
) -> ClassifiedError:
    """Classify a Claude Code subprocess failure.

    Args:
        stderr: combined stderr/stdout text from the failed subprocess.
        exit_code: process exit code (None if killed/timed out).
        timed_out: True if the wall-clock timeout fired.
    """
    text = stderr or ""
    excerpt = _excerpt(text)
    status = _extract_status(text)

    if timed_out:
        return ClassifiedError(
            reason=FailoverReason.timeout, status_code=status,
            message="wall-clock timeout", raw_excerpt=excerpt,
            retryable=True, backoff_seconds=8.0,
        )

    # Pattern match
    matched: Optional[FailoverReason] = None
    for pat, reason in _PATTERNS:
        if pat.search(text):
            matched = reason
            break

    if matched is None:
        if exit_code is not None and exit_code != 0:
            return ClassifiedError(
                reason=FailoverReason.process_crashed, status_code=status,
                message=f"non-zero exit ({exit_code}), unrecognized stderr",
                raw_excerpt=excerpt,
                retryable=True, backoff_seconds=4.0,
            )
        return ClassifiedError(
            reason=FailoverReason.unknown, status_code=status,
            message="unclassifiable failure", raw_excerpt=excerpt,
            retryable=True, backoff_seconds=4.0,
        )

    # Reason-specific recovery hints
    hints: dict = {"retryable": True, "backoff_seconds": 2.0}
    if matched in (FailoverReason.context_overflow, FailoverReason.payload_too_large):
        hints |= {"should_compress": True, "backoff_seconds": 0.0}
    elif matched is FailoverReason.long_context_tier:
        hints |= {"should_compress": True, "should_fallback_model": True, "backoff_seconds": 1.0}
    elif matched is FailoverReason.rate_limit:
        hints |= {"backoff_seconds": 30.0}
    elif matched is FailoverReason.overloaded:
        hints |= {"backoff_seconds": 12.0}
    elif matched is FailoverReason.server_error:
        hints |= {"backoff_seconds": 6.0}
    elif matched is FailoverReason.timeout:
        hints |= {"backoff_seconds": 8.0}
    elif matched is FailoverReason.auth:
        hints |= {"should_rotate_credential": True, "backoff_seconds": 1.0}
    elif matched is FailoverReason.billing:
        hints |= {"abort": True, "retryable": False}
    elif matched is FailoverReason.format_error:
        hints |= {"abort": True, "retryable": False}
    elif matched is FailoverReason.model_not_found:
        hints |= {"should_fallback_model": True, "backoff_seconds": 0.0}
    elif matched is FailoverReason.process_killed:
        # Don't auto-retry kills — usually user/system intent.
        hints |= {"retryable": False, "abort": True}

    return ClassifiedError(
        reason=matched, status_code=status,
        message=matched.value, raw_excerpt=excerpt,
        **hints,
    )


def summarize(err: ClassifiedError) -> str:
    """One-line human-readable summary for logs / UI."""
    parts = [f"[{err.reason.value}]"]
    if err.status_code is not None:
        parts.append(f"http={err.status_code}")
    if err.abort:
        parts.append("abort")
    elif not err.retryable:
        parts.append("non-retryable")
    else:
        parts.append(f"retry+{err.backoff_seconds:g}s")
    if err.should_compress:
        parts.append("compress")
    if err.should_fallback_model:
        parts.append("fallback-model")
    if err.should_rotate_credential:
        parts.append("rotate-cred")
    if err.raw_excerpt:
        parts.append(f"— {err.raw_excerpt}")
    return " ".join(parts)
