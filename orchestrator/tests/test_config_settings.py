"""Tests for orchestrator settings loading (config._load_settings).

Covers the validation added so a corrupt file or a typo'd setting key surfaces a
warning instead of silently reverting to defaults / disabling a feature.
"""

from __future__ import annotations

import json
import logging

import compatibility_telemetry
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


def test_legacy_runtime_setting_is_migrated_once_and_persisted(
    tmp_path, monkeypatch
):
    settings_file = _point_at(
        tmp_path,
        monkeypatch,
        {"worker_provider": "codex", "auto_push": False},
    )
    monkeypatch.setattr(
        compatibility_telemetry,
        "_telemetry_file",
        tmp_path / "compatibility-telemetry.json",
    )

    loaded = config._load_settings()
    persisted = json.loads(settings_file.read_text())

    assert loaded["agent_runtime"] == "codex"
    assert "worker_provider" not in loaded
    assert persisted == {"agent_runtime": "codex", "auto_push": False}
    assert settings_file.stat().st_mode & 0o777 == 0o600
    assert (
        compatibility_telemetry.read_compatibility_telemetry()["events"]
        ["settings.worker_provider"]["count"]
        == 1
    )

    config._load_settings()
    assert (
        compatibility_telemetry.read_compatibility_telemetry()["events"]
        ["settings.worker_provider"]["count"]
        == 1
    )


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


# ─── Every published setting must have a backend reader ──────────────────────
# `_SETTINGS_DEFAULTS` is not just defaults: regen-settings-example.py publishes
# every key in it to templates/orchestrator-settings.example.json, whose promise
# is "every supported key", and server.py accepts POST /api/settings for exactly
# those keys. A key nothing reads is therefore a documented lie the user can
# set, save and watch do nothing. Four shipped that way (min_workers,
# patrol_auto_ideas, reactions_enabled, reaction_configs) before 2026-09.

import ast
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PY = REPO_ROOT / "orchestrator" / "config.py"

# Keys knowingly published with no backend reader. Must stay EMPTY: the whole
# point is that there is no such thing as a legitimately unread setting.
SETTINGS_WITHOUT_BACKEND_READER: set[str] = set()

# Attribute/`.get()` receivers whose name marks a settings mapping.
_SETTINGS_RECEIVER = "settings"
_READ_METHODS = {"get", "setdefault", "pop"}


def _defaults_and_span() -> tuple[dict, tuple[int, int]]:
    """The literal `_SETTINGS_DEFAULTS` dict plus the line span it occupies.

    The span is what the scan below excludes — NOT config.py as a whole.
    `_replay_interrupted_tasks` lives in config.py and is the only reader of
    `replay_interrupted_on_startup`, so a whole-file exclusion reports a
    correctly-wired key as dead. That false positive is why the first version
    of this invariant, run as a throwaway script, counted five dead keys
    instead of four.
    """
    tree = ast.parse(CONFIG_PY.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_SETTINGS_DEFAULTS"
            for t in node.targets
        ):
            return ast.literal_eval(node.value), (node.lineno, node.end_lineno)
    raise AssertionError("_SETTINGS_DEFAULTS assignment not found in config.py")


def _receiver_text(node: ast.expr) -> str:
    """Flatten `GLOBAL_SETTINGS` / `self.settings` / `s.settings` to a name."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _scanned_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "orchestrator", "configs"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git not available — settings-reader gate needs git ls-files")
    files = []
    for rel in out.split("\0"):
        if not rel or not rel.endswith(".py"):
            continue
        p = Path(rel)
        if {".venv", "node_modules", "__pycache__"}.intersection(p.parts):
            continue
        # A test-only reader is not a reader of production behaviour.
        if p.parts[:2] == ("orchestrator", "tests"):
            continue
        if (REPO_ROOT / p).is_file():
            files.append(p)
    return files


def _keys_read_by_backend(skip_span: tuple[int, int]) -> set[str]:
    read: set[str] = set()
    for rel in _scanned_files():
        path = REPO_ROOT / rel
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError):
            continue
        is_config = path == CONFIG_PY
        for node in ast.walk(tree):
            lineno = getattr(node, "lineno", None)
            if (is_config and lineno is not None
                    and skip_span[0] <= lineno <= skip_span[1]):
                continue  # the defaults literal itself is not a reader
            # GLOBAL_SETTINGS.get("key") / run_settings.setdefault("key", ...)
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in _READ_METHODS
                    and _SETTINGS_RECEIVER in _receiver_text(node.func.value).lower()
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                read.add(node.args[0].value)
            # settings["key"]
            elif (isinstance(node, ast.Subscript)
                    and _SETTINGS_RECEIVER in _receiver_text(node.value).lower()
                    and isinstance(node.slice, ast.Constant)
                    and isinstance(node.slice.value, str)):
                read.add(node.slice.value)
    return read


def test_every_setting_has_a_backend_reader():
    """A published setting nothing reads is a lie in a generated reference."""
    defaults, span = _defaults_and_span()
    read = _keys_read_by_backend(span)

    # Hollow-scan guards: a broken parser must not report a clean pass the
    # same way a clean tree does (test_conventions.py uses the same idiom).
    assert len(defaults) > 50, "defaults parse looks hollow"
    assert len(read) > 40, "reader scan looks hollow — the AST walk found nothing"

    dead = sorted(set(defaults) - read - SETTINGS_WITHOUT_BACKEND_READER)
    assert not dead, (
        "Settings published in config.py:_SETTINGS_DEFAULTS with no backend "
        "reader. regen-settings-example.py advertises them as supported and "
        "POST /api/settings accepts them, so each one is a knob the user can "
        "set that does nothing. Wire a reader, or delete the key and rerun "
        "`python3 configs/scripts/regen-settings-example.py`:\n  "
        + "\n  ".join(dead)
    )


def test_settings_reader_exceptions_still_needed():
    """An exception that has acquired a reader must be removed."""
    defaults, span = _defaults_and_span()
    read = _keys_read_by_backend(span)
    stale = sorted(
        k for k in SETTINGS_WITHOUT_BACKEND_READER
        if k not in defaults or k in read
    )
    assert not stale, (
        "These keys no longer need to be in SETTINGS_WITHOUT_BACKEND_READER "
        "(they are read, or gone from _SETTINGS_DEFAULTS): " + ", ".join(stale)
    )


def test_wired_settings_defaults_are_pinned():
    """The two keys wired in 2026-09 keep their published defaults.

    `reactions_enabled` is a kill switch — inverting the default would silence
    the subsystem for everyone. `min_workers` is the auto-scale floor, and at 1
    it is a deliberate no-op relative to auto_start.
    """
    assert config._SETTINGS_DEFAULTS["reactions_enabled"] is True
    assert config._SETTINGS_DEFAULTS["min_workers"] == 1


def test_removed_settings_keys_stay_removed():
    """`reaction_configs` was a drifted partial copy of a leaf's own defaults.

    config.py carried 3 of the 5 rules in reactions.ReactionExecutor
    .DEFAULT_CONFIGS, and __init__ REPLACES rather than merges — so wiring the
    published copy would have silently deleted two reaction rules for anyone
    who copied the generated reference file. The rule list is owned by
    reactions.py; only the on/off switch is a setting.
    """
    assert "reaction_configs" not in config._SETTINGS_DEFAULTS
    assert "patrol_auto_ideas" not in config._SETTINGS_DEFAULTS
