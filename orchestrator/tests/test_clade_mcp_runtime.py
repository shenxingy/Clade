"""Provider runtime tests for the distributable clade-mcp package."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_SRC = REPO_ROOT / "mcp-package" / "src"
sys.path.insert(0, str(MCP_SRC))

from clade_mcp import __version__, runtime  # noqa: E402
from clade_mcp import server  # noqa: E402
from clade_mcp.server import SERVER_VERSION  # noqa: E402


def test_release_version_surfaces_are_aligned() -> None:
    expected = "0.3.1"
    server_manifest = json.loads(
        (REPO_ROOT / "mcp-package" / "server.json").read_text(encoding="utf-8")
    )
    assert __version__ == expected
    assert SERVER_VERSION == expected
    assert server_manifest["version"] == expected
    assert server_manifest["packages"][0]["version"] == expected


def test_mcp_dependency_requires_v2_without_a_v1_fallback() -> None:
    orchestrator_requirements = (
        REPO_ROOT / "orchestrator" / "requirements.txt"
    ).read_text(encoding="utf-8")
    package_manifest = (
        REPO_ROOT / "mcp-package" / "pyproject.toml"
    ).read_text(encoding="utf-8")

    assert "mcp>=2.0.0,<3" in orchestrator_requirements
    assert '"mcp>=2.0.0,<3"' in package_manifest
    assert "mcp>=1" not in orchestrator_requirements + package_manifest


def test_packaged_server_registers_v2_low_level_handlers() -> None:
    assert server.app.get_request_handler("tools/list") is not None
    assert server.app.get_request_handler("tools/call") is not None


def test_editable_install_resolves_curated_bundled_skills() -> None:
    expected = REPO_ROOT / "mcp-package" / "skills"
    assert server.BUNDLED_SKILLS_DIR == expected
    assert len(list(server.BUNDLED_SKILLS_DIR.glob("*/SKILL.md"))) == 34
    for name in ("delivery", "provider", "status"):
        assert (server.BUNDLED_SKILLS_DIR / name / "SKILL.md").is_file()


def test_bundled_skill_resolution_prefers_wheel_then_editable(tmp_path) -> None:
    module_file = tmp_path / "src" / "clade_mcp" / "server.py"
    module_file.parent.mkdir(parents=True)
    module_file.touch()

    editable_skill = tmp_path / "skills" / "delivery"
    editable_skill.mkdir(parents=True)
    (editable_skill / "SKILL.md").write_text("---\nname: delivery\n---\n")
    assert server.resolve_bundled_skills_dir(module_file) == tmp_path / "skills"

    wheel_skill = module_file.parent / "skills" / "status"
    wheel_skill.mkdir(parents=True)
    (wheel_skill / "SKILL.md").write_text("---\nname: status\n---\n")
    assert server.resolve_bundled_skills_dir(module_file) == module_file.parent / "skills"


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
