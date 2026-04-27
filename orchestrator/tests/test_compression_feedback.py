"""Tests for orchestrator/compression_feedback.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from compression_feedback import CompressionReport, summarize  # noqa: E402


def _msgs(n: int) -> list[dict]:
    return [{"role": "user", "content": f"msg {i}"} for i in range(n)]


def test_noop_unchanged_messages() -> None:
    msgs = _msgs(5)
    rep = summarize(msgs, msgs, before_tokens=1000, after_tokens=1000)
    assert rep.noop is True
    assert "5 messages" in rep.headline
    assert "unchanged" in rep.token_line


def test_noop_with_token_drift() -> None:
    """Noop on messages but token estimate moved (e.g., re-count) — should not lie."""
    msgs = _msgs(3)
    rep = summarize(msgs, msgs, before_tokens=1000, after_tokens=900)
    assert rep.noop is True
    assert "1,000" in rep.token_line
    assert "900" in rep.token_line


def test_real_compression() -> None:
    rep = summarize(_msgs(10), _msgs(3), before_tokens=5000, after_tokens=1500)
    assert rep.noop is False
    assert "10 → 3" in rep.headline
    assert "5,000" in rep.token_line
    assert "1,500" in rep.token_line
    assert rep.note is None  # tokens dropped, no caveat needed


def test_fewer_messages_more_tokens_emits_note() -> None:
    """Compression rewrote into denser summaries — flag the surprising delta."""
    rep = summarize(_msgs(20), _msgs(2), before_tokens=3000, after_tokens=3500)
    assert rep.noop is False
    assert rep.note is not None
    assert "denser" in rep.note


def test_render_includes_all_lines() -> None:
    rep = CompressionReport(
        noop=False, headline="H", token_line="T", note="N",
    )
    out = rep.render()
    assert "H" in out and "T" in out and "N" in out


def test_to_dict_serializable() -> None:
    rep = summarize(_msgs(2), _msgs(1), before_tokens=200, after_tokens=100)
    d = rep.to_dict()
    assert set(d.keys()) == {"noop", "headline", "token_line", "note"}


def test_empty_input() -> None:
    rep = summarize([], [], before_tokens=0, after_tokens=0)
    assert rep.noop is True
    assert "0 messages" in rep.headline
