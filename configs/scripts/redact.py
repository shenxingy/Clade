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
import bisect
import json
import re
import sys
from dataclasses import dataclass, asdict
from typing import Iterable, Tuple


# ─── Patterns ─────────────────────────────────────────────────────────────────
# (kind, regex, group_index_for_value)
#
# Every pattern below compiles with re.ASCII, and that flag is load-bearing
# rather than tidy. Python's \w — and therefore \b — is Unicode-aware by
# default, so 是 and к are word characters and there is NO word boundary between
# them and the `s` of `sk-`. A key pasted inside Chinese or Cyrillic prose
# escaped every \b-anchored pattern here entirely:
#
#     不对，改回原来的写法，key是sk-ant-api03-<45 chars>   → 0 hits before
#
# That is not an edge case for this repository. correction-detector.sh is the
# main caller and its own trigger list is 不要|别用|错了|改回|不对 — the CJK path
# is the one the redactor exists to serve, and it was the one path that did not
# work. re.ASCII restores ASCII \b semantics; the `task_<32 alnum>` exclusion
# the generic pattern depends on is unaffected, because `k` and `_` are ASCII
# word characters either way.
#
# A pattern whose character class contains `-` (anthropic, openai, google,
# slack, jwt) has NO trailing \b, and that is load-bearing too. `-` is not a
# word character, so a key ending in `-` before a space has no boundary after
# it: an open count backtracked off the dashes, and at its minimum length — or
# at google's old fixed {35} — matched nothing at all, so the whole key went
# out. `sk-` + 19 alnum + `-` and `AIza` + 34 + `-` both did, until
# tests/test_redact_properties.py generated them. A greedy count consumes the
# whole run of its class, so no trailing assertion is needed; the leading \b
# stays, because that is what keeps `task_…` and `xsk-…` out.
_A = re.ASCII
_PATTERNS: list[tuple[str, re.Pattern, int]] = [
    # Anthropic — sk-ant-{api03|admin01}-... (real keys are long; require ≥40 chars)
    ("anthropic_key", re.compile(r"\bsk-ant-[a-zA-Z0-9_-]{40,}", _A), 0),
    # OpenAI — sk-... or sk-proj-... (≥20 alnum after prefix to avoid matching
    # benign strings like "sk-foo" in code samples)
    ("openai_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}", _A), 0),
    # GitHub — ghp_/gho_/ghu_/ghs_/ghr_ + 36 chars
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b", _A), 0),
    # AWS access key ID
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b", _A), 0),
    # AWS secret — only inside an env-style assignment so we don't mask
    # arbitrary 40-char b64 blobs.
    ("aws_secret_key",
     re.compile(r"AWS_SECRET_ACCESS_KEY[\s:=]+['\"]?([A-Za-z0-9/+=]{40})['\"]?", _A), 1),
    # Google API key
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35,}", _A), 0),
    # Slack tokens
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}", _A), 0),
    # Stripe keys — test keys leak as readily as live ones and were previously
    # matched by nothing: the generic entry below cannot span `test_` either.
    ("stripe_key", re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{20,}\b", _A), 0),
    # Underscore-prefixed vendor keys (sk_<hex> and the same shape from other
    # vendors). Placed after stripe_key for readability only: sk_live_/sk_test_
    # can never reach 32 alnum before the second underscore, so the specific
    # label always wins regardless of order. The \b is what keeps `task_<32
    # alnum>` out — measured 0 hits repo-wide and 0 in a 2.8MB real prompt
    # corpus, where every one of the 14 `sk_` occurrences sits inside `task_…`.
    ("generic_secret_key", re.compile(r"\b(?:sk|rk|ak)_[A-Za-z0-9]{32,}\b", _A), 0),
    # JWT (header.payload.sig — three b64url segments)
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_=-]{10,}\.eyJ[A-Za-z0-9_=-]{10,}\.[A-Za-z0-9_=-]{10,}", _A), 0),
    # Generic env-style assignments — last resort, narrow keyword list. The
    # lookahead refuses a value that is exactly one of this module's own
    # markers: after `token: `, a quoted <redacted:github_token> is 21+
    # non-quote characters in quotes, so without it a second pass re-masked the
    # marker, and scrub-corrections.py — which re-scans history the hooks
    # already masked — reported `<redacted:…>` to the owner as a key to rotate.
    ("env_secret", re.compile(
        r"(?i)\b(?:api[_-]?key|secret|password|passwd|token|auth)"
        r"[\s:=]+['\"](?!<redacted:[a-z_]+>['\"])([^'\"\s]{12,})['\"]",
        _A,
    ), 1),
    # PEM private key blocks
    ("private_key", re.compile(r"-----BEGIN (?:RSA |OPENSSH |DSA |EC |PGP )?PRIVATE KEY-----"
        r"[\s\S]*?-----END (?:RSA |OPENSSH |DSA |EC |PGP )?PRIVATE KEY-----", _A), 0),
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


# One run of verbatim text or one marker in a redacted string, with the span it
# occupies there and the span of the input it stands for. A verbatim piece maps
# one to one; a marker maps its whole width onto the hit it replaced.
#
# typing.Tuple, not `tuple[...]`: this line runs at import, and a subscripted
# builtin raises TypeError there on Python 3.8, the oldest python3 this
# repository names (context-policy.py). A redact.py that cannot import is not
# a no-op: `--check` exits 1, so checks.sh refuses every commit that adds a
# line and secret-scanner.sh flags every prompt. Annotations may say `tuple[...]`:
# `from __future__ import annotations` never evaluates them.
# tests/test_redact.py checks this file against that floor.
_Piece = Tuple[int, int, int, int, bool]  # (out_start, out_end, in_start, in_end, is_marker)

# How many times scan() reads the text, counting the first read. A later read
# happens only when the one before it found something new, so text costs one read
# when it holds no secret and two when it does. Three is the most any input needs
# with today's patterns: only two things make a later read find more — a PEM
# hiding its whitespace from env_secret's value class, and aws_secret_key's fixed 40-char
# value ending on a word character, which takes the \b from whatever is glued
# after it — and what the second read masks ends on a non-word character or
# inside quotes, so it unlocks nothing further. Measured, not only argued: no
# text among 7,000 generated ones (2026-11-06) needed a fourth. The fourth is
# headroom for a pattern added later. The loop ends without a bound too (each
# read either widens the hits or stops it); the bound caps what an adversarial
# input can cost the hook, and the idempotence property fails the day four reads
# are not enough.
_MAX_PASSES = 4


# ─── Public API ───────────────────────────────────────────────────────────────

def scan(text: str) -> list[Hit]:
    """Return all hits, ordered by start offset and non-overlapping.

    Overlapping matches are MERGED into one hit spanning their union, never
    resolved by dropping one. "First listed wins" used to drop the later match
    whole, and the later one is often the wider: a JWT whose segment holds
    `-sk-ant-…` or `-AKIA…` kept its header, payload and signature in the clear
    because aws_access_key / anthropic_key are listed before jwt, and an env
    value or PEM body lost everything outside the inner token the same way. The
    merged hit is labelled by its widest member (ties: the earlier-listed
    pattern, so `sk-ant-…` stays anthropic_key and a stripe key stays
    stripe_key). Found by tests/test_redact_properties.py.

    The hits are also a FIXED POINT: scan() re-reads its own redaction and
    widens the hits until that redaction matches nothing more. One read is not
    enough, because masking changes what the patterns see. A PEM inside an env
    value (`token: "k=<PEM>"`) is invisible to env_secret, whose value cannot
    span the PEM's whitespace, until the PEM is a marker — and then the value
    `k=<redacted:private_key>` matches; an AKIA run glued to the end of an AWS
    secret has no \b until the secret is a marker. A single read left the
    value's own characters in the clear and handed scrub-corrections.py, which
    re-scans history the hooks already masked, a marker to report as a key to
    rotate. A match in the redaction is mapped back onto the input (a span that
    touches a marker takes the marker's whole input span) and merged with the
    rest. Both shapes are generated and pinned in tests/test_redact_properties.py.
    """
    if not text:
        return []
    spans = _matches(text)
    hits = _merge(text, spans)
    for _ in range(_MAX_PASSES - 1):
        if not hits:
            break
        masked, pieces = _render(text, hits)
        extra = _matches(masked)
        if not extra:
            break
        spans += [(*_to_input(pieces, s, e), order, kind) for s, e, order, kind in extra]
        widened = _merge(text, spans)
        if widened == hits:
            break  # nothing new: every later match lies inside what is already masked
        hits = widened
    return hits


def redact(text: str, hits: Iterable[Hit] | None = None) -> tuple[str, list[Hit]]:
    """Return (masked_text, hits).

    Idempotent on its own output — a second pass changes nothing and finds
    nothing — because scan() returns a fixed point (bounded at _MAX_PASSES
    reads). Hits passed in explicitly are applied as given.
    """
    if not text:
        return text, []
    found = list(hits) if hits is not None else scan(text)
    if not found:
        return text, []
    return _render(text, found)[0], found


# ─── Internals ────────────────────────────────────────────────────────────────

def _matches(text: str) -> list[tuple[int, int, int, str]]:
    """Every match of every pattern, as (start, end, pattern order, kind)."""
    spans: list[tuple[int, int, int, str]] = []
    for order, (kind, pat, gi) in enumerate(_PATTERNS):
        for m in pat.finditer(text):
            s, e = m.span(gi) if gi else m.span()
            spans.append((s, e, order, kind))
    return spans


def _merge(text: str, spans: list[tuple[int, int, int, str]]) -> list[Hit]:
    """Overlapping spans become one hit over their union, labelled by its widest member."""
    hits: list[Hit] = []
    cur_s = cur_e = -1
    best: tuple[int, int, str] | None = None  # (-width, order, kind)
    for s, e, order, kind in sorted(spans):
        if best is not None and s < cur_e:  # overlaps the open cluster
            cur_e = max(cur_e, e)
            best = min(best, (-(e - s), order, kind))
            continue
        if best is not None:
            hits.append(Hit(kind=best[2], start=cur_s, end=cur_e, preview=_preview(text[cur_s:cur_e])))
        cur_s, cur_e, best = s, e, (-(e - s), order, kind)
    if best is not None:
        hits.append(Hit(kind=best[2], start=cur_s, end=cur_e, preview=_preview(text[cur_s:cur_e])))
    return hits


def _render(text: str, hits: list[Hit]) -> tuple[str, list[_Piece]]:
    """The redacted text, and where each of its pieces came from in `text`."""
    out: list[str] = []
    pieces: list[_Piece] = []
    pos = cursor = 0
    for h in hits:
        for chunk, in_s, in_e, marker in ((text[cursor:h.start], cursor, h.start, False),
                                          (f"<redacted:{h.kind}>", h.start, h.end, True)):
            if chunk:
                out.append(chunk)
                pieces.append((pos, pos + len(chunk), in_s, in_e, marker))
                pos += len(chunk)
        cursor = h.end
    tail = text[cursor:]
    out.append(tail)
    if tail:
        pieces.append((pos, pos + len(tail), cursor, len(text), False))
    return "".join(out), pieces


def _to_input(pieces: list[_Piece], s: int, e: int) -> tuple[int, int]:
    """Map the span [s, e) of a redacted text back onto the text it was made from."""
    i = bisect.bisect_right([p[0] for p in pieces], s) - 1
    out_s, _, in_s, _, marker = pieces[i]
    start = in_s if marker else in_s + (s - out_s)
    j = bisect.bisect_left([p[1] for p in pieces], e)
    out_s, _, in_s, in_e, marker = pieces[j]
    end = in_e if marker else in_s + (e - out_s)
    return start, end


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
