"""Tests for the native Codex usage helper bundled with the Clade plugin."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (
    REPO_ROOT
    / "configs"
    / "skills"
    / "codex-usage"
    / "scripts"
    / "codex_usage.py"
)
SPEC = importlib.util.spec_from_file_location("clade_codex_usage", SCRIPT)
assert SPEC and SPEC.loader
codex_usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(codex_usage)


def test_app_server_request_never_reads_credentials() -> None:
    messages = codex_usage._messages()
    assert [message["method"] for message in messages] == [
        "initialize",
        "initialized",
        "account/rateLimits/read",
    ]
    assert "auth.json" not in SCRIPT.read_text(encoding="utf-8")


def test_normalize_calculates_weekly_pace_and_orders_codex_first() -> None:
    # A weekly window halfway through its cycle: 60% used versus a 47.5%
    # target means the user is 12.5 points ahead of pace.
    now = 1_700_000_000
    duration = 7 * 24 * 60
    reset = now + duration * 60 / 2
    snapshot = {
        "rateLimitsByLimitId": {
            "codex_spark": {
                "limitId": "codex_spark",
                "limitName": "Spark",
                "primary": {
                    "usedPercent": 10,
                    "windowDurationMins": duration,
                    "resetsAt": reset,
                },
            },
            "codex": {
                "limitId": "codex",
                "primary": {
                    "usedPercent": 60,
                    "windowDurationMins": duration,
                    "resetsAt": reset,
                },
            },
        }
    }

    rows = codex_usage.normalize(snapshot, now=now)

    assert rows[0] == {
        "limit_id": "codex",
        "name": "Codex",
        "window": "week",
        "duration_mins": duration,
        "used_percent": 60,
        "remaining_percent": 40,
        "resets_at": reset,
        "resets_in": "4d",
        "pace_delta": 12.5,
        "projected_percent": 120.0,
    }
    assert rows[1]["name"] == "Spark"
    assert "◉ +12% pace" in codex_usage.format_rows(
        rows, theme="circles", style="detail"
    )
    assert codex_usage.format_rows(
        rows, style="minimal", project="xingyushen", branch="main"
    ) == "xingyushen(main)+12% (4d)"
    assert codex_usage.format_rows(
        rows, theme="bird", style="icon", project="xingyushen", branch="main"
    ) == "xingyushen(main) 🦢 +12% (4d)"


def test_setup_adds_recommended_footer_when_tui_is_missing(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text('model = "gpt-5.6"\n', encoding="utf-8")

    assert codex_usage.setup_status_line(config) is True
    updated = config.read_text(encoding="utf-8")
    assert updated.startswith('model = "gpt-5.6"\n')
    assert "[tui]" in updated
    for item in codex_usage.FULL_STATUS_LINE:
        assert f'"{item}"' in updated
    assert codex_usage.setup_status_line(config) is False


def test_setup_merges_usage_fields_without_replacing_existing_items(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        '[tui]\nstatus_line = ["model", "git-branch", "current-dir"]\n\n'
        '[projects."/work"]\ntrust_level = "trusted"\n',
        encoding="utf-8",
    )

    assert codex_usage.setup_status_line(config) is True
    status_line = next(
        line.split("=", 1)[1].strip()
        for line in config.read_text(encoding="utf-8").splitlines()
        if line.startswith("status_line")
    )
    assert json.loads(status_line) == [
        "model",
        "git-branch",
        "five-hour-limit",
        "weekly-limit",
        "current-dir",
    ]
    assert '[projects."/work"]' in config.read_text(encoding="utf-8")


def test_setup_rejects_unsupported_multiline_status_line(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        '[tui]\nstatus_line = [\n  "model",\n  "current-dir",\n]\n',
        encoding="utf-8",
    )

    with pytest.raises(codex_usage.UsageError, match="multi-line"):
        codex_usage.setup_status_line(config)


def test_explicit_minimal_layout_replaces_only_status_line(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        'model = "gpt-5.6"\n[tui]\nstatus_line = ["model", "current-dir"]\n',
        encoding="utf-8",
    )
    config.chmod(0o600)

    assert codex_usage.setup_status_line(config, layout="minimal") is True
    updated = config.read_text(encoding="utf-8")
    assert 'model = "gpt-5.6"' in updated
    assert f"status_line = {json.dumps(codex_usage.MINIMAL_STATUS_LINE)}" in updated
    assert config.stat().st_mode & 0o777 == 0o600
