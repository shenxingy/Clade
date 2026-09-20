"""Tests for the Claude Code status-line pace helper (`slt`).

This script drives the status line on every session and had no test of any
kind, which is how its scale kept a defect nobody could see: the same `+5`
delta earns the top badge at every point in the window, but what it implies
about the overshoot is `95 + 500/elapsed%` — 145% projected a tenth of the
way in, 101% at nine tenths. The tests below pin both halves of the scale
and the fact that the colour agrees with the symbol.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "configs" / "scripts" / "claude-usage-watch.py"
SPEC = importlib.util.spec_from_file_location("clade_claude_usage_watch", SCRIPT)
assert SPEC and SPEC.loader
watch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watch)

RED = "\033[38;2;185;28;28m"
GREEN = "\033[38;2;85;160;85m"


@pytest.fixture()
def circles(tmp_path, monkeypatch):
    """Pin mode/theme to files we own — the module reads ~/.claude at call time."""
    mode, theme = tmp_path / "mode", tmp_path / "theme"
    mode.write_text("percent")
    theme.write_text("circles")
    monkeypatch.setattr(watch, "MODE_FILE", mode)
    monkeypatch.setattr(watch, "THEME_FILE", theme)
    return tmp_path


# ─── The pace maths ───


def test_elapsed_and_remaining_read_the_window(circles) -> None:
    resets = datetime.now(timezone.utc) + timedelta(hours=10, minutes=24)
    assert watch._elapsed_pct(resets.isoformat()) == pytest.approx(93.8, abs=0.1)
    assert watch._remaining(resets.isoformat()) == "10h"
    assert watch._remaining((datetime.now(timezone.utc) + timedelta(days=3)).isoformat()) == "3d"
    assert watch._remaining("not a timestamp") == "?"


def test_a_window_longer_than_the_assumed_period_clamps_to_zero(circles) -> None:
    """`_elapsed_pct` assumes 7 days. A longer window clamps rather than going
    negative, which makes `delta` collapse to raw usage — worth knowing about
    before this helper is ever pointed at a monthly window."""
    far = (datetime.now(timezone.utc) + timedelta(days=27)).isoformat()
    assert watch._elapsed_pct(far) == 0.0


# ─── The scale ───


def test_symbol_covers_both_sides_of_the_scale(circles) -> None:
    assert watch._symbol(-20, 20.0) == "○"
    assert watch._symbol(-10, 60.0) == "◑"
    assert watch._symbol(0, 95.0) == "●"
    assert watch._symbol(6, 110.0) == "◉"


def test_a_blowout_projection_loses_the_top_badge_and_turns_red(circles) -> None:
    """Ahead of target is the top grade only while the projection stays sane."""
    # Full use of the window, landing just past target: still the top badge.
    assert watch._symbol(10.9, 106.6) == "◉"
    assert watch._color(106.6, 10.9) == GREEN
    # Same "ahead", but the quota empties with a fifth of the window to run.
    assert watch._symbol(10.9, 125.1) == "○"
    assert watch._color(125.1, 10.9) == RED
    assert watch._symbol(19.1, 262.0) == "○"
    assert watch._color(262.0, 19.1) == RED
    # Being behind, or on track, is untouched by the guard.
    assert watch._symbol(0.0, 300.0) == "●"
    assert watch._symbol(-20.0, 300.0) == "○"
    assert watch._color(0.0, -20.0) != RED


# ─── End to end, through the real statusline input ───


def _render(monkeypatch, capsys, usage, hours_left) -> str:
    resets = datetime.now(timezone.utc) + timedelta(hours=hours_left)
    payload = (
        '{"rate_limits": {"seven_day": {"used_percentage": %s, "resets_at": "%s"}}}'
        % (usage, resets.isoformat())
    )
    monkeypatch.setattr(watch.sys, "argv", ["x", "--statusline-input"])
    monkeypatch.setattr(watch.sys, "stdin", __import__("io").StringIO(payload))
    watch.run()
    return capsys.readouterr().out


def test_a_week_used_well_keeps_the_top_badge(circles, monkeypatch, capsys) -> None:
    """100% used with 10.4h left is near-perfect utilisation, not a failure."""
    out = _render(monkeypatch, capsys, 100.0, 10.4)
    assert out.startswith("◉ ") and "+11%" in out and "(10h)" in out
    assert GREEN in out and RED not in out


def test_burning_the_week_down_early_reports_the_failure(circles, monkeypatch, capsys) -> None:
    """30% used with 6.2 days left projects 262% — dry by Wednesday."""
    out = _render(monkeypatch, capsys, 30.0, 6.2 * 24)
    assert out.startswith("○ ") and RED in out and GREEN not in out


def test_off_mode_prints_nothing(circles, monkeypatch, capsys) -> None:
    (circles / "mode").write_text("off")
    assert _render(monkeypatch, capsys, 100.0, 10.4) == ""
