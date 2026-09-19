"""Tests for the Kimi Code usage helper bundled with the kimi-usage skill.

The helper's data path is Kimi's documented local server API, so the tests
stand up a fake `kimi web` (an HTTP server answering the two routes the
helper uses) and register it the way a real instance registers itself —
nothing here needs Kimi installed, and nothing spawns one.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "configs" / "skills" / "kimi-usage" / "scripts" / "kimi_usage.py"
LAUNCHER = REPO_ROOT / "configs" / "kimi-hooks" / "statusline.sh"
SPEC = importlib.util.spec_from_file_location("clade_kimi_usage", SCRIPT)
assert SPEC and SPEC.loader
kimi_usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(kimi_usage)

NOW = 1_800_000_000.0  # 2027-01-15T08:00:00Z — a fixed "now" for pace maths
FIVE_H = 5 * 3600


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _quota(**usages: dict[str, Any]) -> dict[str, Any]:
    return {"usages": usages, "extraUsage": None}


# ─── Principle: the documented local API, never the credential file ───


def test_helper_never_touches_credentials_or_the_upstream_usage_endpoint() -> None:
    """codex_usage.py is held to `auth.json` never appearing; this helper's
    docstring names the paths it refuses to use, so the check is on CODE:
    no string literal reaches for the credential store or api.kimi.*."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    # Drop docstrings: every module/class/function body's leading string.
    doc_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                doc_ids.add(doc)
    code_strings = [text for text in literals if text not in doc_ids]
    offenders = [
        text
        for text in code_strings
        if "credentials" in text or "api.kimi." in text or "coding/v1" in text
    ]
    assert offenders == []
    assert "/api/v1/oauth/usage" in code_strings or any(
        "/api/v1/oauth/usage" in text for text in code_strings
    )


def test_spawned_server_is_loopback_only_headless_and_update_free() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"--no-open"' in source
    assert 'env["KIMI_CODE_NO_AUTO_UPDATE"] = "1"' in source
    assert 'env["KIMI_DISABLE_TELEMETRY"] = "1"' in source
    assert "--host" not in source


# ─── Normalisation ───


def test_normalize_month_window_uses_the_billing_month_and_carries_the_code_split() -> None:
    # A month that resets 15 days from now on a 30-day cycle: 50% elapsed.
    reset = NOW + 15 * 86400
    period = kimi_usage._month_period(reset)
    assert period == 31 * 86400  # Dec 30 -> Jan 30 spans 31 days
    quota = _quota(
        monthTotal={"usedRatio": 0.6, "resetAt": _iso(reset)},
        monthCode={"usedRatio": 0.1, "resetAt": _iso(reset)},
    )
    (row,) = kimi_usage.normalize(quota, now=NOW)
    elapsed = (NOW - (reset - period)) / period * 100
    assert row["window"] == "month"
    assert row["used_percent"] == 60.0
    assert row["code_percent"] == 10.0
    assert row["kimi_percent"] == 50.0
    assert row["pace_delta"] == round(60 - elapsed * 0.95, 1)
    assert row["resets_in"] == "15d"


def test_month_period_clamps_the_day_when_the_previous_month_is_shorter() -> None:
    march_31 = datetime(2027, 3, 31, tzinfo=timezone.utc).timestamp()
    assert kimi_usage._month_period(march_31) == 31 * 86400  # Feb 28 -> Mar 31 (2027)


def test_normalize_keeps_payload_order_skips_absent_windows_and_bad_ratios() -> None:
    quota = _quota(
        limit5h={"usedRatio": "0.25", "resetAt": _iso(NOW + 3 * 3600)},
        limit7d={"usedRatio": "not a number"},
        monthTotal={"usedRatio": 0.05, "resetAt": _iso(NOW + 20 * 86400)},
    )
    rows = kimi_usage.normalize(quota, now=NOW)
    assert [row["window"] for row in rows] == ["5h", "month"]
    five = rows[0]
    assert five["used_percent"] == 25.0
    assert five["elapsed_percent"] == 40.0  # 2h into a 5h window
    assert five["resets_in"] == "3h"
    assert "code_percent" not in rows[1]


def test_normalize_without_usages_is_empty() -> None:
    assert kimi_usage.normalize({}, now=NOW) == []
    assert kimi_usage.normalize({"usages": "nope"}, now=NOW) == []


def test_pace_window_prefers_weekly_when_the_plan_has_one() -> None:
    weekly = _quota(
        limit7d={"usedRatio": 0.5, "resetAt": _iso(NOW + 3 * 86400)},
        monthTotal={"usedRatio": 0.2, "resetAt": _iso(NOW + 10 * 86400)},
        limit5h={"usedRatio": 0.0, "resetAt": _iso(NOW + FIVE_H)},
    )
    rows = kimi_usage.normalize(weekly, now=NOW)
    assert kimi_usage.pace_row(rows)["window"] == "week"
    assert kimi_usage.burst_row(rows)["window"] == "5h"
    monthly_only = kimi_usage.normalize(
        _quota(monthTotal={"usedRatio": 0.2, "resetAt": _iso(NOW + 10 * 86400)}), now=NOW
    )
    assert kimi_usage.pace_row(monthly_only)["window"] == "month"
    assert kimi_usage.burst_row(monthly_only) is None


# ─── Presentation ───


def _rows_ahead() -> list[dict[str, Any]]:
    reset = NOW + 15 * 86400
    return kimi_usage.normalize(
        _quota(
            limit5h={"usedRatio": 0.4, "resetAt": _iso(NOW + 3 * 3600)},
            monthTotal={"usedRatio": 0.6, "resetAt": _iso(reset)},
        ),
        now=NOW,
    )


def test_usage_segment_styles() -> None:
    rows = _rows_ahead()
    delta = kimi_usage._signed(float(kimi_usage.pace_row(rows)["pace_delta"]))
    assert kimi_usage.usage_segment(rows, "icon", "circles", NOW, color=False) == (
        f"◉ {delta} (15d) · 5h 40% (3h)"
    )
    assert kimi_usage.usage_segment(rows, "detail", "circles", NOW, color=False) == (
        f"◉ month {delta} (15d) · 5h 40% (3h)"
    )
    assert kimi_usage.usage_segment(rows, "minimal", "circles", NOW, color=False) == (
        f"{delta} (15d) · 5h 40%"
    )
    assert kimi_usage.usage_segment(rows, "off", "circles", NOW, color=False) == ""
    assert kimi_usage.usage_segment([], "icon", "circles", NOW, color=False) == ""


def test_usage_segment_marks_a_rolled_over_window_as_stale() -> None:
    rows = kimi_usage.normalize(
        _quota(monthTotal={"usedRatio": 0.3, "resetAt": _iso(NOW - 60)}), now=NOW - 3600
    )
    assert kimi_usage.usage_segment(rows, "icon", "circles", NOW, color=False) == "● (?)"


def test_symbol_thresholds_and_theme_fallback() -> None:
    assert kimi_usage._symbol(-20, "circles") == "○"
    assert kimi_usage._symbol(-10, "circles") == "◑"
    assert kimi_usage._symbol(0, "circles") == "●"
    assert kimi_usage._symbol(6, "dragon") == "👑"
    assert kimi_usage._signed(-0.4) == "+0%"
    assert kimi_usage._signed(-7.6) == "-8%"


def test_format_rows_reads_like_the_usage_panel_plus_pace() -> None:
    text = kimi_usage.format_rows(_rows_ahead(), "circles", NOW)
    lines = text.splitlines()
    assert lines[0].startswith("  5h limit")
    assert "40% used" in lines[0] and "pace" not in lines[0]
    assert lines[1].startswith("  Monthly limit")
    assert "60% used" in lines[1] and "◉ +" in lines[1] and "resets in 15d" in lines[1]
    assert kimi_usage.format_rows([], "circles", NOW).startswith("No Kimi Code plan-usage")


def test_format_extra_usage_handles_both_wallet_shapes() -> None:
    capped = {
        "balanceCents": 1250, "totalCents": 5000, "monthlyChargeLimitEnabled": True,
        "monthlyChargeLimitCents": 2000, "monthlyUsedCents": 750, "currency": "USD",
    }
    assert kimi_usage.format_extra_usage(capped) == (
        "  Extra usage   $7.50 of $20.00 this month · balance $12.50"
    )
    uncapped = dict(capped, monthlyChargeLimitEnabled=False, currency="CNY")
    assert "¥7.50 this month · no monthly limit · balance ¥12.50" in kimi_usage.format_extra_usage(uncapped)
    assert kimi_usage.format_extra_usage(None) == ""


# ─── Refresh policy ───


def _cache(age: float, seen: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "fetched_at": NOW - age,
        "rows": [{"window": "month", "resets_at": NOW + 10 * 86400}],
        "seen": seen or {},
    }
    data.update(extra)
    return data


def test_needs_refresh_policy() -> None:
    needs = kimi_usage.needs_refresh
    assert needs(None, "s", 1, NOW) is True
    assert needs(_cache(10, {"s": 1}), "s", 1, NOW) is False  # fresh
    assert needs(_cache(400, {"s": 1}), "s", 1, NOW) is False  # stale, but this session idle
    assert needs(_cache(400, {"s": 1}), "s", 2, NOW) is True  # stale and this session worked
    assert needs(_cache(400, {"other": 1}), "s", 1, NOW) is True  # never seen this session
    assert needs(_cache(400, {"s": 1}), None, 1, NOW) is True  # no session id: plain TTL
    assert needs(_cache(2000, {"s": 1}), "s", 1, NOW) is True  # hard TTL
    rolled = _cache(10, {"s": 1})
    rolled["rows"][0]["resets_at"] = NOW - 1
    assert needs(rolled, "s", 1, NOW) is True  # window rolled over
    assert needs(_cache(400, error="boom", error_at=NOW - 30), "s", 2, NOW) is False  # backoff
    assert needs(_cache(400, error="boom", error_at=NOW - 700), "s", 2, NOW) is True
    assert needs({"rows": []}, "s", 1, NOW) is True  # no fetched_at at all


def test_refresh_is_detached_once_and_throttled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    class FakePopen:
        def __init__(self, argv: list[str], **kwargs: Any) -> None:
            calls.append(argv)
            assert kwargs["start_new_session"] is True
            assert kwargs["stdin"] is kwargs["stdout"] is kwargs["stderr"]

    import subprocess

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    kimi_usage._detach_refresh(tmp_path, "sess", 42)
    kimi_usage._detach_refresh(tmp_path, "sess", 43)  # within PENDING_TTL: no second spawn
    assert len(calls) == 1
    assert calls[0][1:] == [str(SCRIPT.resolve()), "refresh", "--session", "sess", "--context-tokens", "42"]
    assert (tmp_path / (kimi_usage.LOCK_NAME + ".pending")).exists()


# ─── Status line ───


def _payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "model": "K2.8 Preview",
        "cwd": "/tmp/proj",
        "gitBranch": "main",
        "permissionMode": "auto",
        "planMode": True,
        "contextTokens": 10,
        "sessionId": "s1",
        "version": "2.0.1",
    }
    payload.update(overrides)
    return payload


def _plain(text: str) -> str:
    import re

    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def test_statusline_renders_from_the_cache_without_refreshing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kimi_usage.write_cache(
        {"fetched_at": NOW - 10, "source": "test", "rows": _rows_ahead(), "seen": {"s1": 10}},
        tmp_path,
    )
    monkeypatch.setattr(kimi_usage, "_detach_refresh", lambda *a: pytest.fail("no refresh due"))
    line = _plain(kimi_usage.statusline(_payload(), tmp_path, NOW))
    delta = kimi_usage._signed(float(kimi_usage.pace_row(_rows_ahead())["pace_delta"]))
    assert line == f"proj git:(main)  ◉ {delta} (15d) · 5h 40% (3h)"


def test_statusline_honors_kimis_own_items_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kimi_usage.write_cache(
        {"fetched_at": NOW - 10, "source": "test", "rows": _rows_ahead(), "seen": {"s1": 10}},
        tmp_path,
    )
    monkeypatch.setattr(kimi_usage, "_detach_refresh", lambda *a: None)
    delta = kimi_usage._signed(float(kimi_usage.pace_row(_rows_ahead())["pace_delta"]))
    tui = tmp_path / "tui.toml"
    tui.write_text(STOCK_TUI + '\n[status_line]\nitems = ["mode", "goal", "model", "tasks", "cwd", "git", "tips"]\n', encoding="utf-8")
    assert kimi_usage.status_line_items(tmp_path) == ("mode", "model", "cwd", "git")
    line = _plain(kimi_usage.statusline(_payload(), tmp_path, NOW))
    assert line == f"[Never Ask] [plan]  K2.8 Preview  proj git:(main)  ◉ {delta} (15d) · 5h 40% (3h)"
    tui.write_text(STOCK_TUI + '\n[status_line]\nitems = ["git", "mode"]\n', encoding="utf-8")
    line = _plain(kimi_usage.statusline(_payload(planMode=False), tmp_path, NOW))
    assert line == f"git:(main)  [Never Ask]  ◉ {delta} (15d) · 5h 40% (3h)"
    tui.write_text(STOCK_TUI, encoding="utf-8")  # no active table: the default
    assert kimi_usage.status_line_items(tmp_path) == kimi_usage.DEFAULT_ITEMS
    tui.write_text(STOCK_TUI + '\n[status_line]\nitems = ["tips"]\n', encoding="utf-8")
    assert _plain(kimi_usage.statusline(_payload(), tmp_path, NOW)) == f"◉ {delta} (15d) · 5h 40% (3h)"


def test_statusline_cold_cache_detaches_a_refresh_and_still_draws_the_rest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    detached: list[tuple[Any, ...]] = []
    monkeypatch.setattr(kimi_usage, "_detach_refresh", lambda *a: detached.append(a))
    line = _plain(kimi_usage.statusline(_payload(permissionMode="manual", planMode=False), tmp_path, NOW))
    assert line == "proj git:(main)"
    assert detached == [(tmp_path, "s1", 10)]


def test_statusline_off_yields_nothing_and_error_only_cache_shows_a_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kimi_usage, "_detach_refresh", lambda *a: None)
    (tmp_path / kimi_usage.STYLE_NAME).write_text("off\n", encoding="utf-8")
    assert kimi_usage.statusline(_payload(), tmp_path, NOW) == ""
    (tmp_path / kimi_usage.STYLE_NAME).unlink()
    kimi_usage.write_cache({"error": "boom", "error_at": NOW - 5, "seen": {}}, tmp_path)
    assert _plain(kimi_usage.statusline(_payload(), tmp_path, NOW)).endswith("proj git:(main)  quota ?")


def test_statusline_falls_back_to_git_head_for_the_branch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kimi_usage, "_detach_refresh", lambda *a: None)
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/feat/kimi\n", encoding="utf-8")
    nested = repo / "sub"
    nested.mkdir()
    assert kimi_usage._git_branch(str(nested)) == "feat/kimi"
    # A linked worktree: .git is a FILE pointing at the main repository.
    main_git = tmp_path / "main" / ".git" / "worktrees" / "wt"
    main_git.mkdir(parents=True)
    (main_git / "HEAD").write_text("ref: refs/heads/wt-branch\n", encoding="utf-8")
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {main_git}\n", encoding="utf-8")
    assert kimi_usage._git_branch(str(worktree)) == "wt-branch"
    (repo / ".git" / "HEAD").write_text("0123456789abcdef\n", encoding="utf-8")
    assert kimi_usage._git_branch(str(repo)) == "0123456"
    assert kimi_usage._git_branch(str(tmp_path / "nowhere")) is None
    line = _plain(kimi_usage.statusline(_payload(cwd=str(worktree), gitBranch=None), tmp_path, NOW))
    assert "wt git:(wt-branch)" in line


def test_launcher_hands_off_to_the_helper_and_stays_silent_without_it(tmp_path: Path) -> None:
    import subprocess
    import time

    env = dict(os.environ, KIMI_CODE_HOME=str(tmp_path), CLADE_KIMI_USAGE_HELPER=str(SCRIPT))
    (tmp_path / kimi_usage.STYLE_NAME).write_text("icon\n", encoding="utf-8")
    kimi_usage.write_cache(
        {"fetched_at": NOW, "source": "test", "rows": _rows_ahead(), "seen": {"s1": 10}}, tmp_path
    )
    # `now` inside the helper is real time, so the fixture's windows must be
    # unexpired relative to it — rebuild rows against the wall clock.
    import time as _time

    rows = kimi_usage.normalize(
        _quota(
            limit5h={"usedRatio": 0.4, "resetAt": _iso(_time.time() + 3 * 3600)},
            monthTotal={"usedRatio": 0.6, "resetAt": _iso(_time.time() + 15 * 86400)},
        )
    )
    kimi_usage.write_cache({"fetched_at": _time.time(), "source": "test", "rows": rows, "seen": {"s1": 10}}, tmp_path)
    result = subprocess.run(
        ["bash", str(LAUNCHER)], input=json.dumps(_payload()), capture_output=True, text=True, env=env, timeout=30
    )
    assert result.returncode == 0
    assert result.stdout.count("\n") == 1
    assert "proj git:(main)" in _plain(result.stdout) and "5h 40%" in _plain(result.stdout)

    # An idle Kimi session re-runs the command every second with the same
    # snapshot: the launcher must replay its memo without starting Python.
    # Prove it by swapping the helper for a file Python cannot run — a fresh
    # render would print nothing, so any output here came from the memo.
    broken = tmp_path / "broken.py"
    broken.write_text("this is not python\n", encoding="utf-8")
    env["CLADE_KIMI_USAGE_HELPER"] = str(broken)
    replay = subprocess.run(
        ["bash", str(LAUNCHER)], input=json.dumps(_payload()), capture_output=True, text=True, env=env, timeout=30
    )
    assert replay.returncode == 0 and replay.stdout == result.stdout
    assert [path.name for path in tmp_path.glob(".clade-usage-memo-*")] == [".clade-usage-memo-s1"]
    # Another session's snapshot is a miss; the broken helper then yields the
    # documented silence, exit 0.
    silent = subprocess.run(
        ["bash", str(LAUNCHER)], input=json.dumps(_payload(sessionId="s2")), capture_output=True, text=True, env=env, timeout=30
    )
    assert silent.returncode == 0 and silent.stdout == ""
    # A rewritten cache invalidates the memo inside the minute.
    os.utime(tmp_path / kimi_usage.CACHE_NAME, (time.time() + 5, time.time() + 5))
    stale = subprocess.run(
        ["bash", str(LAUNCHER)], input=json.dumps(_payload()), capture_output=True, text=True, env=env, timeout=30
    )
    assert stale.returncode == 0 and stale.stdout == ""
    # Missing helper: silent and green, before anything else is consulted.
    env["CLADE_KIMI_USAGE_HELPER"] = str(tmp_path / "missing.py")
    missing = subprocess.run(
        ["bash", str(LAUNCHER)], input="{}", capture_output=True, text=True, env=env, timeout=30
    )
    assert missing.returncode == 0 and missing.stdout == ""


# ─── tui.toml wiring ───

STOCK_TUI = """# ~/.kimi-code/tui.toml
theme = "auto" # "auto" | "dark" | "light" | custom theme name

[editor]
command = "" # Empty uses $VISUAL / $EDITOR

# [status_line]
# command = "~/.kimi-code/statusline.sh"
"""
OURS = "/home/u/.kimi-code/hooks/statusline.sh"


def test_merge_appends_a_table_when_none_is_active_and_is_idempotent() -> None:
    wired, changed = kimi_usage.merge_status_line(STOCK_TUI, OURS)
    assert changed
    assert wired.endswith(f'\n[status_line]\ncommand = "{OURS}"\n')
    assert '# command = "~/.kimi-code/statusline.sh"' in wired  # the comment survives
    assert 'command = "" # Empty uses' in wired  # [editor] is another table
    assert kimi_usage.merge_status_line(wired, OURS) == (wired, False)
    assert kimi_usage.status_line_wired(wired) is True
    assert kimi_usage.status_line_wired(STOCK_TUI) is False  # the comment is not wiring


def test_merge_off_removes_only_ours_and_round_trips_the_original() -> None:
    wired, _ = kimi_usage.merge_status_line(STOCK_TUI, OURS)
    restored, changed = kimi_usage.merge_status_line(wired, None)
    assert changed and restored == STOCK_TUI
    assert kimi_usage.merge_status_line(STOCK_TUI, None) == (STOCK_TUI, False)


def test_merge_inserts_into_an_existing_table_and_keeps_its_other_keys() -> None:
    text = STOCK_TUI + '\n[status_line]\nitems = ["mode", "model"]\n'
    wired, changed = kimi_usage.merge_status_line(text, OURS)
    assert changed
    assert f'[status_line]\ncommand = "{OURS}"\nitems = ["mode", "model"]\n' in wired
    back, _ = kimi_usage.merge_status_line(wired, None)
    assert back == text  # the items line — and its table — stay


def test_merge_never_touches_a_user_authored_command() -> None:
    theirs = STOCK_TUI + '\n[status_line]\ncommand = "~/my-hud.sh"\n'
    with pytest.raises(kimi_usage.UsageError, match="its own status line command"):
        kimi_usage.merge_status_line(theirs, OURS)
    assert kimi_usage.merge_status_line(theirs, None) == (theirs, False)
    assert kimi_usage.status_line_wired(theirs) is False


def test_merge_updates_a_stale_clade_path_in_place() -> None:
    old = STOCK_TUI + '\n[status_line]\ncommand = "/old/home/.kimi-code/hooks/statusline.sh"\n'
    wired, changed = kimi_usage.merge_status_line(old, OURS)
    assert changed and f'command = "{OURS}"' in wired and "/old/home" not in wired


def test_setup_writes_tui_toml_and_requires_the_deployed_launcher(tmp_path: Path) -> None:
    (tmp_path / "tui.toml").write_text(STOCK_TUI, encoding="utf-8")
    with pytest.raises(kimi_usage.UsageError, match="install.sh"):
        kimi_usage.setup_status_line(tmp_path)
    launcher = tmp_path / "hooks" / "statusline.sh"
    launcher.parent.mkdir()
    launcher.write_text("#!/bin/sh\n", encoding="utf-8")
    assert kimi_usage.setup_status_line(tmp_path) is True
    assert kimi_usage.setup_status_line(tmp_path) is False
    assert f'command = "{launcher}"' in (tmp_path / "tui.toml").read_text(encoding="utf-8")
    assert kimi_usage.setup_status_line(tmp_path, enable=False) is True
    assert (tmp_path / "tui.toml").read_text(encoding="utf-8") == STOCK_TUI


# ─── Server discovery and the documented API ───


class _FakeKimiWeb(BaseHTTPRequestHandler):
    """The two `kimi web` routes the helper uses, behind Kimi's envelope."""

    token = "fake-tok"  # under 12 chars: the staged-secret scan flags longer literals
    usage_data: dict[str, Any] = {}
    seen_auth: list[str | None] = []

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path == "/api/v1/healthz":
            self._send(200, {"code": 0, "msg": "success", "data": {"ok": True}})
            return
        if self.path.startswith("/api/v1/oauth/usage"):
            auth = self.headers.get("Authorization")
            type(self).seen_auth.append(auth)
            if auth != f"Bearer {self.token}":
                self._send(401, {"code": 40101, "msg": "unauthorized", "data": None})
                return
            self._send(200, {"code": 0, "msg": "success", "data": self.usage_data})
            return
        self._send(404, {"code": 40400, "msg": "not found", "data": None})

    def _send(self, status: int, body: dict[str, Any]) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_args: Any) -> None:
        pass


@pytest.fixture
def fake_kimi_web(tmp_path: Path):
    server = HTTPServer(("127.0.0.1", 0), _FakeKimiWeb)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _FakeKimiWeb.seen_auth = []
    _FakeKimiWeb.usage_data = {
        "kind": "ok",
        "quota": _quota(
            limit5h={"usedRatio": 0.1, "resetAt": _iso(NOW + FIVE_H)},
            monthTotal={"usedRatio": 0.3, "resetAt": _iso(NOW + 9 * 86400)},
        ),
    }
    (tmp_path / "server.token").write_text(_FakeKimiWeb.token + "\n", encoding="utf-8")
    registry = tmp_path / "server" / "instances"
    registry.mkdir(parents=True)
    (registry / "01LIVE.json").write_text(
        json.dumps({"pid": os.getpid(), "host": "127.0.0.1", "port": server.server_port, "startedAt": 1}),
        encoding="utf-8",
    )
    try:
        yield server, tmp_path
    finally:
        server.shutdown()
        server.server_close()


def test_live_instances_keeps_only_answering_loopback_pids(tmp_path: Path) -> None:
    registry = tmp_path / "server" / "instances"
    registry.mkdir(parents=True)
    dead_pid = 2**22 - 1  # above the Linux default pid_max; not a live pid on any sane box
    entries = {
        "01DEAD.json": {"pid": dead_pid, "host": "127.0.0.1", "port": 1, "startedAt": 2},
        "02LAN.json": {"pid": os.getpid(), "host": "10.0.0.5", "port": 2, "startedAt": 3},
        "03OK.json": {"pid": os.getpid(), "host": "0.0.0.0", "port": 3, "startedAt": 4},
        "04OLDER.json": {"pid": os.getpid(), "host": "127.0.0.1", "port": 4, "startedAt": 1},
        "05JUNK.json": "not json at all",
        "notes.txt": {"pid": os.getpid(), "host": "127.0.0.1", "port": 5},
    }
    for name, body in entries.items():
        (registry / name).write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
    assert [row["port"] for row in kimi_usage.live_instances(tmp_path)] == [4, 3]
    assert kimi_usage.live_instances(tmp_path / "nothing-here") == []


def test_fetch_quota_reuses_a_live_instance_with_the_server_token(fake_kimi_web, monkeypatch: pytest.MonkeyPatch) -> None:
    _server, home = fake_kimi_web
    monkeypatch.setattr(kimi_usage, "SpawnedServer", lambda *a, **k: pytest.fail("must not spawn"))
    quota, source = kimi_usage.fetch_quota(home)
    assert quota["usages"]["monthTotal"]["usedRatio"] == 0.3
    assert source.startswith("via the running kimi web on 127.0.0.1:")
    assert _FakeKimiWeb.seen_auth == ["Bearer fake-tok"]


def test_fetch_quota_surfaces_kimis_in_band_error_and_a_rejected_token(fake_kimi_web, monkeypatch: pytest.MonkeyPatch) -> None:
    _server, home = fake_kimi_web
    # Neither answer is the instance's fault, so neither may trigger a spawn.
    monkeypatch.setattr(kimi_usage, "SpawnedServer", lambda *a, **k: pytest.fail("must not spawn"))
    _FakeKimiWeb.usage_data = {"kind": "error", "message": "Run /login to authenticate.", "status": 401}
    with pytest.raises(kimi_usage.UsageError, match="Run /login"):
        kimi_usage.fetch_quota(home)
    (home / "server.token").write_text("wrong\n", encoding="utf-8")
    with pytest.raises(kimi_usage.UsageError, match="rotate-token"):
        kimi_usage.fetch_quota(home)


def test_fetch_quota_skips_an_instance_that_is_not_a_kimi_web(fake_kimi_web, monkeypatch: pytest.MonkeyPatch) -> None:
    _server, home = fake_kimi_web
    spawned: list[Path] = []

    class NoServer:
        def __init__(self, home_dir: Path) -> None:
            spawned.append(home_dir)

        def __enter__(self) -> "NoServer":
            raise kimi_usage.UsageError("would spawn here")

        def __exit__(self, *_exc: object) -> None:
            pass

    monkeypatch.setattr(kimi_usage, "SpawnedServer", NoServer)
    monkeypatch.setattr(_FakeKimiWeb, "do_GET", lambda self: self._send(404, {"code": 40400, "msg": "nope", "data": None}))
    with pytest.raises(kimi_usage.UsageError, match="would spawn here"):
        kimi_usage.fetch_quota(home)
    assert spawned == [home]


def test_fetch_quota_without_kimi_on_path_is_a_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil

    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(kimi_usage.UsageError, match="not installed"):
        kimi_usage.fetch_quota(tmp_path)
    with pytest.raises(kimi_usage.UsageError, match="does not exist"):
        kimi_usage.fetch_quota(tmp_path / "absent")


def test_refresh_cache_records_rows_seen_and_errors(fake_kimi_web, monkeypatch: pytest.MonkeyPatch) -> None:
    _server, home = fake_kimi_web
    data = kimi_usage.refresh_cache(home, "s1", 7)
    assert [row["window"] for row in data["rows"]] == ["5h", "month"]
    assert data["seen"] == {"s1": 7}
    assert (home / kimi_usage.CACHE_NAME).stat().st_mode & 0o777 == 0o600
    assert kimi_usage.read_cache(home) == data
    monkeypatch.setattr(kimi_usage, "fetch_quota", lambda _home: (_ for _ in ()).throw(kimi_usage.UsageError("down")))
    failed = kimi_usage.refresh_cache(home, "s2", 8)
    assert failed["error"] == "down" and failed["rows"] == data["rows"]  # last good rows kept
    assert failed["seen"] == {"s1": 7, "s2": 8}


def test_refresh_command_writes_the_cache_under_a_lock(fake_kimi_web, monkeypatch: pytest.MonkeyPatch) -> None:
    _server, home = fake_kimi_web
    monkeypatch.setenv("KIMI_CODE_HOME", str(home))
    old_memo = home / ".clade-usage-memo-gone"
    old_memo.write_text("k\nline\n", encoding="utf-8")
    os.utime(old_memo, (1, 1))
    fresh_memo = home / ".clade-usage-memo-live"
    fresh_memo.write_text("k\nline\n", encoding="utf-8")
    assert kimi_usage.main(["refresh", "--session", "s9", "--context-tokens", "3"]) == 0
    assert not old_memo.exists() and fresh_memo.exists()  # day-old memos are pruned
    cache = kimi_usage.read_cache(home)
    assert cache is not None and cache["seen"] == {"s9": 3}
    assert [row["window"] for row in cache["rows"]] == ["5h", "month"]
    fetched = len(_FakeKimiWeb.seen_auth)
    # A second refresher arriving while one holds the lock must leave, not fetch.
    import fcntl

    with open(home / kimi_usage.LOCK_NAME, "a+") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert kimi_usage.main(["refresh", "--session", "s10", "--context-tokens", "4"]) == 0
    assert len(_FakeKimiWeb.seen_auth) == fetched
    assert kimi_usage.read_cache(home) == cache


def test_show_prints_the_report_and_json(fake_kimi_web, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    _server, home = fake_kimi_web
    monkeypatch.setenv("KIMI_CODE_HOME", str(home))
    assert kimi_usage.main([]) == 0
    text = capsys.readouterr().out
    assert text.startswith("Kimi Code plan usage  (via the running kimi web on 127.0.0.1:")
    assert "  5h limit        10% used · resets in " in text
    assert "  Monthly limit   30% used ·" in text
    assert "not wired — run `setup`" in text
    assert kimi_usage.main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [row["window"] for row in payload["rows"]] == ["5h", "month"]
    assert payload["extra_usage"] is None


def test_main_reports_usage_errors_on_stderr_with_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KIMI_CODE_HOME", str(tmp_path / "absent"))
    assert kimi_usage.main(["theme", "nope"]) == 2
    assert "Unknown theme" in capsys.readouterr().err
    monkeypatch.setenv("KIMI_CODE_HOME", str(tmp_path))
    assert kimi_usage.main(["style", "icon"]) == 0
    assert (tmp_path / kimi_usage.STYLE_NAME).read_text(encoding="utf-8") == "icon\n"
    assert kimi_usage.main(["setup", "sideways"]) == 2
