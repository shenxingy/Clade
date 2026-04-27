"""
compression_feedback.py — User-facing feedback for context compression.

Leaf module. No internal deps.

Used by:
- /handoff skill (after dumping handoff doc)
- worker condensers (when manual `/compact` is requested)

Output is a small dict the caller renders into the UI / TUI / chat. We
don't print here — separation lets the same logic feed both terminal and
web UIs without reformatting.

Inspired by Hermes Agent's `agent/manual_compression_feedback.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass
class CompressionReport:
    noop: bool
    headline: str
    token_line: str
    note: str | None = None

    def to_dict(self) -> dict:
        return {
            "noop": self.noop,
            "headline": self.headline,
            "token_line": self.token_line,
            "note": self.note,
        }

    def render(self) -> str:
        """Multi-line plain-text rendering for terminals."""
        out = [self.headline, self.token_line]
        if self.note:
            out.append(self.note)
        return "\n".join(out)


def _count(items: Iterable) -> int:
    if items is None:
        return 0
    try:
        return len(items)  # type: ignore[arg-type]
    except TypeError:
        return sum(1 for _ in items)


def summarize(
    before_messages: Sequence,
    after_messages: Sequence,
    before_tokens: int,
    after_tokens: int,
) -> CompressionReport:
    """Build a CompressionReport from before/after compression state.

    Edge cases this handles (learned the hard way in upstream):
    - No-op compression (list unchanged) — say so explicitly, don't pretend.
    - Fewer messages but MORE tokens — denser summaries can grow byte count
      after rewriting; explain so the user doesn't think the metric is broken.
    """
    # Defensive normalization — accept tuples, generators, anything sequence-y.
    before_count = _count(before_messages)
    after_count = _count(after_messages)
    noop = list(before_messages) == list(after_messages)

    if noop:
        headline = f"No changes from compression: {before_count} messages"
        if before_tokens == after_tokens:
            token_line = f"Rough transcript estimate: ~{before_tokens:,} tokens (unchanged)"
        else:
            token_line = (
                f"Rough transcript estimate: ~{before_tokens:,} → ~{after_tokens:,} tokens"
            )
        return CompressionReport(noop=True, headline=headline, token_line=token_line)

    headline = f"Compressed: {before_count} → {after_count} messages"
    token_line = f"Rough transcript estimate: ~{before_tokens:,} → ~{after_tokens:,} tokens"
    note = None
    if after_count < before_count and after_tokens > before_tokens:
        note = (
            "Note: fewer messages can still raise this rough estimate when "
            "compression rewrites the transcript into denser summaries."
        )
    return CompressionReport(
        noop=False, headline=headline, token_line=token_line, note=note,
    )
