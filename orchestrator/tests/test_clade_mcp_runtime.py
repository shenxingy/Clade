"""Provider runtime tests for the distributable clade-mcp package."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_SRC = REPO_ROOT / "mcp-package" / "src"
sys.path.insert(0, str(MCP_SRC))

from clade_mcp import runtime  # noqa: E402


def test_runtime_selection_is_backwards_compatible() -> None:
    assert runtime.get_runtime({}).name == "claude"
    assert runtime.get_runtime({"CLADE_RUNTIME": "codex"}).name == "codex"
    with pytest.raises(ValueError, match="Unsupported CLADE_RUNTIME"):
        runtime.get_runtime({"CLADE_RUNTIME": "unknown"})


def test_codex_runtime_uses_stdin_jsonl_and_safe_sandbox(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(
            returncode=0,
            stdout=(
                '{"type":"thread.started","thread_id":"abc"}\n'
                '{"type":"item.completed","item":{"type":"agent_message",'
                '"text":"native result"}}\n'
            ),
            stderr="",
        )

    monkeypatch.setattr(runtime.subprocess, "run", fake_run)
    result = runtime.CodexRuntime().execute(
        "do the work", tmp_path, env={"CLADE_RUNTIME": "codex"}
    )
    assert result.ok and result.text == "native result"
    assert captured["input"] == "do the work"
    assert captured["command"][:4] == ["codex", "exec", "--json", "--ephemeral"]
    assert ["--sandbox", "workspace-write"] == captured["command"][6:8]
    assert captured["command"][-1] == "-"


def test_codex_runtime_requires_explicit_permission_bypass(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runtime.subprocess, "run", fake_run)
    runtime.CodexRuntime().execute(
        "work", tmp_path, env={"CLADE_CODEX_BYPASS_PERMISSIONS": "true"}
    )
    assert "--dangerously-bypass-approvals-and-sandbox" in captured["command"]
    assert "--sandbox" not in captured["command"]


def test_claude_runtime_preserves_existing_behavior(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return SimpleNamespace(returncode=0, stdout='{"result":"legacy result"}', stderr="")

    monkeypatch.setattr(runtime.subprocess, "run", fake_run)
    result = runtime.ClaudeRuntime().execute("work", tmp_path, env={})
    assert result.text == "legacy result"
    assert captured["command"][0:2] == ["claude", "-p"]
    assert "--dangerously-skip-permissions" in captured["command"]


def test_invalid_codex_sandbox_fails_before_spawn(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("subprocess should not run"),
    )
    result = runtime.CodexRuntime().execute(
        "work", tmp_path, env={"CLADE_CODEX_SANDBOX": "invalid"}
    )
    assert not result.ok
    assert "CLADE_CODEX_SANDBOX" in result.error
