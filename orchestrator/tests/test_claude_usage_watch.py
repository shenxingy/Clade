"""Tests for the Claude Code status-line pace helper (`slt`).

This script drives the status line on every session and had no test of any
kind, which is how its scale kept a defect nobody could see: the same `+5`
delta earns the top badge at every point in the window, but what it implies
about the overshoot is `95 + 500/elapsed%` — 145% projected a tenth of the
way in, 101% at nine tenths. The tests below pin both halves of the scale
and the fact that the colour agrees with the symbol.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "configs" / "scripts" / "claude-usage-watch.py"
SPEC = importlib.util.spec_from_file_location("clade_claude_usage_watch", SCRIPT)
assert SPEC and SPEC.loader
watch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watch)

PEACH = "\033[38;2;210;160;135m"
HONEY = "\033[38;2;212;180;119m"


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


def test_a_blowout_projection_loses_the_top_badge_and_turns_peach(circles) -> None:
    """Ahead of target is the top grade only while the projection stays sane."""
    # Full use of the window, landing just past target: still the top badge.
    assert watch._symbol(10.9, 106.6) == "◉"
    assert watch._color(106.6, 10.9) == HONEY
    # Same "ahead", but the quota empties with a fifth of the window to run.
    assert watch._symbol(10.9, 125.1) == "○"
    assert watch._color(125.1, 10.9) == PEACH
    assert watch._symbol(19.1, 262.0) == "○"
    assert watch._color(262.0, 19.1) == PEACH
    # Being behind, or on track, is untouched by the guard.
    assert watch._symbol(0.0, 300.0) == "●"
    assert watch._symbol(-20.0, 300.0) == "○"
    assert watch._color(0.0, -20.0) == HONEY


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
    assert HONEY in out and PEACH not in out


def test_burning_the_week_down_early_reports_the_failure(circles, monkeypatch, capsys) -> None:
    """30% used with 6.2 days left projects 262% — dry by Wednesday."""
    out = _render(monkeypatch, capsys, 30.0, 6.2 * 24)
    assert out.startswith("○ ") and PEACH in out and HONEY not in out


def test_off_mode_prints_nothing(circles, monkeypatch, capsys) -> None:
    (circles / "mode").write_text("off")
    assert _render(monkeypatch, capsys, 100.0, 10.4) == ""


# ─── Which account: CLAUDE_CONFIG_DIR, never the primary profile's files ───
#
# Under a profile (CLAUDE_CONFIG_DIR=~/.claude-profiles/<name>) the script read
# the token and the cache from ~/.claude, so the status line showed the primary
# account's quota and refreshed the primary cache, while the profile's own cache
# went months without a write. Each test loads a FRESH copy of the script after
# pointing HOME and CLAUDE_CONFIG_DIR at temp dirs, so neither this code nor an
# older copy that resolves its paths at import time can touch the real
# ~/.claude. The Keychain call and the network are stubbed in every test, and
# the working directory is a temp dir holding a decoy .credentials.json: Claude
# Code itself reads an EMPTY CLAUDE_CONFIG_DIR, or one starting with a literal
# ~, relative to its working directory, and this script deliberately does not,
# so any path that leaks into the cwd shows up as the decoy token being sent.

PRIMARY_TOKEN = "fake-primary-token"
PROFILE_TOKEN = "fake-profile-token"
CWD_TOKEN = "fake-cwd-decoy-token"


def _fake_creds(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"claudeAiOauth": {"accessToken": "%s"}}' % token)


def _api_reading(seven_day: float, five_hour: float) -> dict:
    later = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    soon = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    return {
        "five_hour": {"utilization": five_hour, "resets_at": soon},
        "seven_day": {"utilization": seven_day, "resets_at": later},
    }


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


def _load_under(monkeypatch, home: Path, config_dir, *, api=None, keychain=None):
    """A fresh module with HOME/CLAUDE_CONFIG_DIR set BEFORE it is executed.

    Returns (module, sent) where `sent` collects the bearer tokens the module
    tried to use. `api` is the JSON the fake endpoint returns (None = the call
    fails); `keychain` is the token the fake `security` returns (None = no
    Keychain item), consulted only when the test claims to be on macOS.
    """
    monkeypatch.setenv("HOME", str(home))
    if config_dir is None:
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
    primary = home / ".claude"
    primary.mkdir(parents=True, exist_ok=True)
    (primary / ".statusline-mode").write_text("percent")
    (primary / ".statusline-theme").write_text("circles")
    cwd = home.parent / "cwd"
    _fake_creds(cwd / ".credentials.json", CWD_TOKEN)
    monkeypatch.chdir(cwd)

    spec = importlib.util.spec_from_file_location("clade_claude_usage_watch_acct", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    sent: list = []
    services: list = []

    def fake_urlopen(req, timeout=None):
        sent.append(req.get_header("Authorization"))
        if api is None:
            raise OSError("no network in tests")
        return _FakeResponse(json.dumps(api).encode())

    def fake_check_output(cmd, **kwargs):
        services.append(cmd[cmd.index("-s") + 1])
        if keychain is None:
            raise subprocess.CalledProcessError(44, cmd)
        return '{"claudeAiOauth": {"accessToken": "%s"}}' % keychain

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(mod.subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(mod.sys, "argv", ["claude-usage-watch.py"])
    mod.services = services
    return mod, sent


def test_a_profile_fetches_with_its_own_token_and_caches_in_its_own_dir(
    tmp_path, monkeypatch, capsys
) -> None:
    home, profile = tmp_path / "home", tmp_path / "profiles" / "work"
    _fake_creds(home / ".claude" / ".credentials.json", PRIMARY_TOKEN)
    _fake_creds(profile / ".credentials.json", PROFILE_TOKEN)
    # The primary cache is EXPIRED, so code that reads ~/.claude would refetch
    # and overwrite it — exactly what the profile must never do.
    primary_cache = home / ".claude" / "usage-watch-cache.json"
    stale = dict(_api_reading(10.0, 5.0), _at=0)
    primary_cache.write_text(json.dumps(stale))
    before = primary_cache.read_bytes()

    mod, sent = _load_under(monkeypatch, home, profile, api=_api_reading(40.0, 23.0))
    monkeypatch.setattr(mod.sys, "platform", "linux")
    mod.run()

    assert sent == [f"Bearer {PROFILE_TOKEN}"]
    profile_cache = profile / "usage-watch-cache.json"
    assert profile_cache.exists(), "the profile's reading must be cached under CLAUDE_CONFIG_DIR"
    cached = json.loads(profile_cache.read_text())
    assert cached["seven_day"]["utilization"] == 40.0
    # The 5-hour window is what a pre-launch quota gate reads; keep it.
    assert cached["five_hour"]["utilization"] == 23.0
    assert primary_cache.read_bytes() == before, "the primary cache must be untouched"
    assert capsys.readouterr().out, "the profile's own reading must render"


def test_a_profile_never_renders_the_primary_accounts_reading(
    tmp_path, monkeypatch, capsys
) -> None:
    """A fresh primary cache and a failed fetch: show nothing, not someone else."""
    home, profile = tmp_path / "home", tmp_path / "profiles" / "work"
    _fake_creds(home / ".claude" / ".credentials.json", PRIMARY_TOKEN)
    _fake_creds(profile / ".credentials.json", PROFILE_TOKEN)
    fresh = dict(_api_reading(99.0, 80.0), _at=time.time())
    (home / ".claude" / "usage-watch-cache.json").write_text(json.dumps(fresh))

    mod, sent = _load_under(monkeypatch, home, profile, api=None)
    monkeypatch.setattr(mod.sys, "platform", "linux")
    mod.run()

    assert capsys.readouterr().out == "", "rendered another account's reading"
    assert sent == [f"Bearer {PROFILE_TOKEN}"]
    assert not (profile / "usage-watch-cache.json").exists()


@pytest.mark.parametrize("config_dir_value", [None, ""])
def test_without_a_profile_the_primary_dir_is_used(
    tmp_path, monkeypatch, capsys, config_dir_value
) -> None:
    """Unset and empty both mean ~/.claude.

    Unset is Claude Code's own rule. Empty is NOT: Claude Code 2.1.283 reads an
    empty CLAUDE_CONFIG_DIR as a relative path and loads ./.credentials.json
    from its working directory. This script deliberately falls back to
    ~/.claude instead, so a status line never sends a token planted in a
    project's working directory — the decoy there must not be the one sent.
    """
    home = tmp_path / "home"
    _fake_creds(home / ".claude" / ".credentials.json", PRIMARY_TOKEN)

    mod, sent = _load_under(monkeypatch, home, config_dir_value, api=_api_reading(40.0, 23.0))
    monkeypatch.setattr(mod.sys, "platform", "linux")
    mod.run()

    assert sent == [f"Bearer {PRIMARY_TOKEN}"]
    cached = json.loads((home / ".claude" / "usage-watch-cache.json").read_text())
    assert cached["five_hour"]["utilization"] == 23.0
    assert capsys.readouterr().out


# Each case is (raw CLAUDE_CONFIG_DIR, as Claude Code hashes it; the dir the
# credentials and cache resolve to). Built from tmp_path at run time.
_KEYCHAIN_CASES = {
    "plain": lambda t: (str(t / "profiles" / "work"), t / "profiles" / "work"),
    # macOS hands out decomposed (NFD) paths; Claude Code hashes the NFC form.
    "nfd": lambda t: (str(t / "profiles" / "cafe\u0301"), t / "profiles" / "cafe\u0301"),
    # Shell tab completion adds the slash. Claude Code hashes the raw string, so
    # the slash changes the item; hashing the resolved path would drop it and
    # pick another account's item.
    "trailing-slash": lambda t: (str(t / "profiles" / "work") + "/", t / "profiles" / "work"),
    # An explicit CLAUDE_CONFIG_DIR=$HOME/.claude is still "set": Claude Code
    # suffixes it, so it is NOT the primary's unsuffixed item.
    "explicit-home-claude": lambda t: (str(t / "home" / ".claude"), t / "home" / ".claude"),
    # A literal ~ (quoted in the shell): hashed raw, as Claude Code does, but
    # the dir is expanded — the script's deliberate departure (see its comment).
    "literal-tilde": lambda t: ("~/profiles/work", t / "home" / "profiles" / "work"),
}


@pytest.mark.parametrize("case", sorted(_KEYCHAIN_CASES))
def test_macos_reads_the_profiles_own_keychain_item(tmp_path, monkeypatch, case) -> None:
    """Claude Code names a profile's Keychain item after a hash of CLAUDE_CONFIG_DIR.

    Expected suffix is computed here, independently of the script, from the rule
    in the Claude Code 2.1.283 binary: "-" + sha256(NFC(raw value))[:8], over the
    environment string exactly as set — not the resolved, normalised path.
    """
    home = tmp_path / "home"
    raw, config_dir = _KEYCHAIN_CASES[case](tmp_path)
    config_dir.mkdir(parents=True, exist_ok=True)
    mod, sent = _load_under(
        monkeypatch, home, raw, api=_api_reading(40.0, 23.0), keychain=PROFILE_TOKEN
    )
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    mod.run()

    suffix = hashlib.sha256(unicodedata.normalize("NFC", raw).encode("utf-8")).hexdigest()[:8]
    assert mod.services == [f"Claude Code-credentials-{suffix}"]
    assert sent == [f"Bearer {PROFILE_TOKEN}"]
    assert (config_dir / "usage-watch-cache.json").exists()


def test_macos_primary_keeps_the_unsuffixed_keychain_item(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    mod, sent = _load_under(
        monkeypatch, home, None, api=_api_reading(40.0, 23.0), keychain=PRIMARY_TOKEN
    )
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    mod.run()
    assert mod.services == ["Claude Code-credentials"]
    assert sent == [f"Bearer {PRIMARY_TOKEN}"]


# ─── --refresh-only: the cache a launch gate reads ───
#
# The Workflow preflight (check-workflow-script.py) warns before a launch when
# the profile's cached 7-day or 5-hour reading is high, and ignores a cache
# older than 10 minutes. The status line rarely writes that cache (with
# --statusline-input it neither reads nor writes it), so the preflight asks
# this script to refresh it first. A plain run returns before fetching when
# the status line is switched off (`slt off`), which would leave the gate
# silent forever on that machine; --refresh-only must refresh regardless and
# print nothing, since its output is discarded.


def test_refresh_only_writes_the_profile_cache_even_with_the_status_line_off(
    tmp_path, monkeypatch, capsys
) -> None:
    home, profile = tmp_path / "home", tmp_path / "profiles" / "work"
    _fake_creds(profile / ".credentials.json", PROFILE_TOKEN)
    mod, sent = _load_under(monkeypatch, home, profile, api=_api_reading(91.0, 40.0))
    (home / ".claude" / ".statusline-mode").write_text("off")
    monkeypatch.setattr(mod.sys, "platform", "linux")
    mod.main(["--refresh-only"])

    assert sent == [f"Bearer {PROFILE_TOKEN}"]
    cached = json.loads((profile / "usage-watch-cache.json").read_text())
    assert cached["seven_day"]["utilization"] == 91.0
    assert cached["five_hour"]["utilization"] == 40.0
    assert time.time() - cached["_at"] < 60
    assert capsys.readouterr().out == "", "refresh-only renders nothing"


def test_refresh_only_leaves_a_fresh_cache_alone(tmp_path, monkeypatch, capsys) -> None:
    home, profile = tmp_path / "home", tmp_path / "profiles" / "work"
    _fake_creds(profile / ".credentials.json", PROFILE_TOKEN)
    fresh = dict(_api_reading(12.0, 3.0), _at=time.time())
    profile.mkdir(parents=True, exist_ok=True)
    (profile / "usage-watch-cache.json").write_text(json.dumps(fresh))
    mod, sent = _load_under(monkeypatch, home, profile, api=_api_reading(91.0, 40.0))
    monkeypatch.setattr(mod.sys, "platform", "linux")
    mod.main(["--refresh-only"])

    assert sent == [], "a cache younger than CACHE_TTL must not be refetched"
    assert json.loads((profile / "usage-watch-cache.json").read_text())["seven_day"]["utilization"] == 12.0
    assert capsys.readouterr().out == ""


def test_main_without_flags_still_renders(tmp_path, monkeypatch, capsys) -> None:
    home, profile = tmp_path / "home", tmp_path / "profiles" / "work"
    _fake_creds(profile / ".credentials.json", PROFILE_TOKEN)
    mod, sent = _load_under(monkeypatch, home, profile, api=_api_reading(40.0, 23.0))
    monkeypatch.setattr(mod.sys, "platform", "linux")
    mod.main([])
    assert sent == [f"Bearer {PROFILE_TOKEN}"]
    assert capsys.readouterr().out, "the status-line path must still render"
