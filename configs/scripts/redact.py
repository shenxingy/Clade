#!/usr/bin/env python3
"""
redact.py — Detect and redact common secret patterns from text.

Library + CLI. Used by hooks (e.g. secret-scanner.sh) before content
flows back into the agent's context.

Library:
    from redact import redact, scan
    masked, hits = redact("export OPENAI_API_KEY=sk-abc...")
    # masked = "export OPENAI_API_KEY=<redacted:openai_key>"
    # hits   = [Hit(kind="openai_key", start=22, end=46)]

CLI:
    echo "..." | redact.py            # prints redacted text
    echo "..." | redact.py --check    # exits 1 if any secret found
    echo "..." | redact.py --json     # prints {"redacted": ..., "hits": [...]}

Patterns are conservative — false-positive on a hit means we mask a
benign-looking string; that is a much smaller harm than leaking real
credentials. Add new patterns as you discover them in the wild.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from typing import Iterable


# ─── Patterns ─────────────────────────────────────────────────────────────────
# (kind, regex, group_index_for_value)
_PATTERNS: list[tuple[str, re.Pattern, int]] = [
    # Anthropic — sk-ant-{api03|admin01}-... (real keys are long; require ≥40 chars)
    ("anthropic_key", re.compile(r"\bsk-ant-[a-zA-Z0-9_-]{40,}\b"), 0),
    # OpenAI — sk-... or sk-proj-... (≥20 alnum after prefix to avoid matching
    # benign strings like "sk-foo" in code samples)
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"), 0),
    # GitHub — ghp_/gho_/ghu_/ghs_/ghr_ + 36 chars
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), 0),
    # AWS access key ID
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), 0),
    # AWS secret — only inside an env-style assignment so we don't mask
    # arbitrary 40-char b64 blobs.
    ("aws_secret_key",
     re.compile(r"AWS_SECRET_ACCESS_KEY[\s:=]+['\"]?([A-Za-z0-9/+=]{40})['\"]?"), 1),
    # Google API key
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), 0),
    # Slack tokens
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), 0),
    # Stripe live keys
    ("stripe_key", re.compile(r"\b(?:sk|rk|pk)_live_[A-Za-z0-9]{20,}\b"), 0),
    # JWT (header.payload.sig — three b64url segments)
    ("jwt", re.compile(
        r"\beyJ[A-Za-z0-9_=-]{10,}\.eyJ[A-Za-z0-9_=-]{10,}\.[A-Za-z0-9_=-]{10,}\b"
    ), 0),
    # Generic env-style assignments — last resort, narrow keyword list
    ("env_secret", re.compile(
        r"(?i)\b(?:api[_-]?key|secret|password|passwd|token|auth)"
        r"[\s:=]+['\"]([^'\"\s]{12,})['\"]"
    ), 1),
    # PEM private key blocks
    ("private_key", re.compile(
        r"-----BEGIN (?:RSA |OPENSSH |DSA |EC |PGP )?PRIVATE KEY-----"
        r"[\s\S]*?-----END (?:RSA |OPENSSH |DSA |EC |PGP )?PRIVATE KEY-----"
    ), 0),
]


# ─── Data ─────────────────────────────────────────────────────────────────────

@dataclass
class Hit:
    kind: str
    start: int
    end: int
    preview: str  # first 6 + last 4 chars only — never full secret

    def as_dict(self) -> dict:
        return asdict(self)


# ─── Public API ───────────────────────────────────────────────────────────────

def scan(text: str) -> list[Hit]:
    """Return all hits, ordered by start offset, non-overlapping (first wins)."""
    if not text:
        return []
    hits: list[Hit] = []
    occupied: list[tuple[int, int]] = []
    for kind, pat, gi in _PATTERNS:
        for m in pat.finditer(text):
            s, e = m.span(gi) if gi else m.span()
            if any(not (e <= os_ or s >= oe) for os_, oe in occupied):
                continue  # overlap with earlier hit — skip
            occupied.append((s, e))
            value = m.group(gi) if gi else m.group(0)
            preview = _preview(value)
            hits.append(Hit(kind=kind, start=s, end=e, preview=preview))
    hits.sort(key=lambda h: h.start)
    return hits


def redact(text: str, hits: Iterable[Hit] | None = None) -> tuple[str, list[Hit]]:
    """Return (masked_text, hits). Idempotent — re-running on masked text is a no-op."""
    if not text:
        return text, []
    found = list(hits) if hits is not None else scan(text)
    if not found:
        return text, []
    out: list[str] = []
    cursor = 0
    for h in found:
        out.append(text[cursor:h.start])
        out.append(f"<redacted:{h.kind}>")
        cursor = h.end
    out.append(text[cursor:])
    return "".join(out), found


def _preview(secret: str) -> str:
    if len(secret) <= 12:
        return "***"
    return f"{secret[:6]}...{secret[-4:]}"


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description="Redact secrets from stdin.")
    p.add_argument("--check", action="store_true",
                   help="Exit 1 if any secret found; print summary to stderr.")
    p.add_argument("--json", action="store_true",
                   help="Output JSON {redacted, hits[]} instead of plain text.")
    args = p.parse_args()

    text = sys.stdin.read()
    masked, hits = redact(text)

    if args.check:
        if hits:
            sys.stderr.write(
                f"redact: {len(hits)} secret(s) found: "
                + ", ".join(f"{h.kind}({h.preview})" for h in hits) + "\n"
            )
            return 1
        return 0

    if args.json:
        sys.stdout.write(json.dumps({
            "redacted": masked,
            "hits": [h.as_dict() for h in hits],
        }))
        return 0

    sys.stdout.write(masked)
    return 0


if __name__ == "__main__":
    sys.exit(main())
