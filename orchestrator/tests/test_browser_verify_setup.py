"""End-to-end browser verification wiring (Playwright MCP).

Covers the setup script that enables it (merge into .claude/mcp.json, preserve
other servers, idempotent, remove) and the tool-allowlist that lets fix/test
workers reach the browser tools.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "configs" / "scripts" / "setup-browser-verify.sh"


def _run(project_dir: Path, *flags: str):
    return subprocess.run(
        ["bash", str(_SCRIPT), str(project_dir), "--no-install", *flags],
        capture_output=True, text=True,
    )


def _servers(project_dir: Path) -> dict:
    return json.loads((project_dir / ".claude" / "mcp.json").read_text())["mcpServers"]


class TestSetupScript:
    def test_enables_playwright_on_empty_project(self, tmp_path):
        r = _run(tmp_path)
        assert r.returncode == 0, r.stderr
        servers = _servers(tmp_path)
        assert "playwright" in servers
        assert servers["playwright"]["command"] == "npx"
        assert "@playwright/mcp@latest" in servers["playwright"]["args"]
        assert "--headless" in servers["playwright"]["args"]

    def test_preserves_existing_servers(self, tmp_path):
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "mcp.json").write_text(
            json.dumps({"mcpServers": {"clade": {"command": "python", "args": ["mcp_server.py"]}}})
        )
        _run(tmp_path)
        servers = _servers(tmp_path)
        assert "clade" in servers and "playwright" in servers  # both present

    def test_idempotent(self, tmp_path):
        _run(tmp_path)
        first = (tmp_path / ".claude" / "mcp.json").read_text()
        _run(tmp_path)
        assert (tmp_path / ".claude" / "mcp.json").read_text() == first

    def test_remove_drops_only_playwright(self, tmp_path):
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "mcp.json").write_text(
            json.dumps({"mcpServers": {"clade": {"command": "python"}}})
        )
        _run(tmp_path)
        _run(tmp_path, "--remove")
        servers = _servers(tmp_path)
        assert "playwright" not in servers
        assert "clade" in servers  # untouched

    def test_survives_corrupt_mcp_json(self, tmp_path):
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "mcp.json").write_text("{not valid json")
        r = _run(tmp_path)
        assert r.returncode == 0  # fail-open: rebuilds rather than crashing
        assert "playwright" in _servers(tmp_path)


class TestToolAllowlist:
    """fix/test workers must be allowed to reach the browser MCP tools."""

    def test_fix_and_test_allow_playwright(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_real_config_bv", _REPO / "orchestrator" / "config.py"
        )
        cfg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cfg)
        assert "mcp__playwright" in cfg._TOOL_SUBSETS["fix"][0]
        assert "mcp__playwright" in cfg._TOOL_SUBSETS["test"][0]
        # review stays read-only — no browser tools
        assert "mcp__playwright" not in cfg._TOOL_SUBSETS["review"][0]

    def test_build_tool_flags_includes_playwright_for_fix(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_real_config_bv2", _REPO / "orchestrator" / "config.py"
        )
        cfg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cfg)
        flags = cfg._build_tool_flags("fix")
        assert "mcp__playwright" in flags
        assert "--allowed-tools" in flags
