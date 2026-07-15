"""Tests for orchestrator settings loading (config._load_settings).

Covers the validation added so a corrupt file or a typo'd setting key surfaces a
warning instead of silently reverting to defaults / disabling a feature.
"""

from __future__ import annotations

import json
import logging

import config


def _point_at(tmp_path, monkeypatch, contents):
    settings_file = tmp_path / "orchestrator-settings.json"
    settings_file.write_text(
        contents if isinstance(contents, str) else json.dumps(contents)
    )
    monkeypatch.setattr(config, "_settings_file", settings_file)
    return settings_file


def test_missing_file_returns_defaults_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_settings_file", tmp_path / "absent.json")
    loaded = config._load_settings()
    assert loaded == config._SETTINGS_DEFAULTS
    assert loaded is not config._SETTINGS_DEFAULTS  # copy, never the shared dict


def test_known_keys_merge_without_warning(tmp_path, monkeypatch, caplog):
    _point_at(tmp_path, monkeypatch, {"auto_push": False})
    with caplog.at_level(logging.WARNING):
        loaded = config._load_settings()
    assert loaded["auto_push"] is False
    assert not caplog.records


def test_unknown_key_warns_and_real_key_keeps_default(tmp_path, monkeypatch, caplog):
    _point_at(tmp_path, monkeypatch, {"auto_pushh": False})  # typo of auto_push
    with caplog.at_level(logging.WARNING):
        loaded = config._load_settings()
    assert "unknown setting keys" in caplog.text
    assert "auto_pushh" in caplog.text
    assert loaded["auto_push"] == config._SETTINGS_DEFAULTS["auto_push"]


def test_corrupt_file_warns_and_falls_back(tmp_path, monkeypatch, caplog):
    _point_at(tmp_path, monkeypatch, "{ not valid json")
    with caplog.at_level(logging.WARNING):
        loaded = config._load_settings()
    assert "unreadable" in caplog.text
    assert loaded == config._SETTINGS_DEFAULTS


def test_non_object_json_warns_and_falls_back(tmp_path, monkeypatch, caplog):
    _point_at(tmp_path, monkeypatch, "[1, 2, 3]")
    with caplog.at_level(logging.WARNING):
        loaded = config._load_settings()
    assert "not a JSON object" in caplog.text
    assert loaded == config._SETTINGS_DEFAULTS
