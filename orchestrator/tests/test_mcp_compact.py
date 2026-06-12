"""Tests for MCP compact mode (claude-cookbooks search-then-load):
CLADE_MCP_COMPACT=1 (default) exposes clade_list_skills / clade_search_skills /
clade_run_skill instead of ~95 per-skill tool definitions; CLADE_MCP_COMPACT=0
restores full enumeration.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

pytest.importorskip("mcp")
sys.path.insert(0, str(REPO_ROOT / "orchestrator"))
try:
    import mcp_server
finally:
    sys.path.pop(0)


def _write_skill(root: Path, name: str, description: str) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\nuser_invocable: true\n---\n"
    )
    (d / "prompt.md").write_text(f"Prompt body for {name}")


@pytest.fixture
def skills_dir(tmp_path: Path, monkeypatch) -> Path:
    _write_skill(tmp_path, "alpha", "Commit helper for git workflows")
    _write_skill(tmp_path, "beta", "Blog SEO audit and scoring")
    monkeypatch.setattr(mcp_server, "SKILLS_DIR", tmp_path)
    return tmp_path


# ─── mode flag ────────────────────────────────────────────────────────────────


class TestCompactFlag:
    def test_default_is_on(self, monkeypatch):
        monkeypatch.delenv("CLADE_MCP_COMPACT", raising=False)
        assert mcp_server._compact_mode() is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", " OFF "])
    def test_disabled_values(self, monkeypatch, value):
        monkeypatch.setenv("CLADE_MCP_COMPACT", value)
        assert mcp_server._compact_mode() is False

    @pytest.mark.parametrize("value", ["1", "true", "yes", "anything"])
    def test_enabled_values(self, monkeypatch, value):
        monkeypatch.setenv("CLADE_MCP_COMPACT", value)
        assert mcp_server._compact_mode() is True


# ─── list_tools in both modes ─────────────────────────────────────────────────


class TestListTools:
    async def test_compact_mode_exposes_fixed_tool_set(self, skills_dir, monkeypatch):
        monkeypatch.delenv("CLADE_MCP_COMPACT", raising=False)
        names = {t.name for t in await mcp_server.list_tools()}
        assert {"clade_list_skills", "clade_search_skills", "clade_run_skill"} <= names
        # no per-skill enumeration — tool count is constant regardless of skills
        assert "clade_alpha" not in names and "clade_beta" not in names
        assert names == {
            "clade_list_skills", "clade_search_skills", "clade_run_skill",
            "clade_search_class", "clade_search_method", "clade_search_code",
        }

    async def test_enumeration_mode_exposes_per_skill_tools(self, skills_dir, monkeypatch):
        monkeypatch.setenv("CLADE_MCP_COMPACT", "0")
        names = {t.name for t in await mcp_server.list_tools()}
        assert {"clade_alpha", "clade_beta", "clade_list_skills"} <= names
        assert "clade_run_skill" not in names
        assert "clade_search_skills" not in names


# ─── search_skills ────────────────────────────────────────────────────────────


class TestSearchSkills:
    SKILLS = [
        {"name": "commit", "description": "Analyze changes, commit and push"},
        {"name": "blog-write", "description": "Write blog posts optimized for SEO"},
        {"name": "seo-audit", "description": "Full SEO site audit"},
    ]

    def test_matches_name_and_description(self):
        assert [s["name"] for s in mcp_server.search_skills("commit", self.SKILLS)] == ["commit"]
        assert {s["name"] for s in mcp_server.search_skills("seo", self.SKILLS)} == {
            "blog-write", "seo-audit"
        }

    def test_multi_term_scoring_ranks_better_matches_first(self):
        out = mcp_server.search_skills("seo audit", self.SKILLS)
        assert out[0]["name"] == "seo-audit"  # matches both terms

    def test_empty_query_and_no_match(self):
        assert mcp_server.search_skills("", self.SKILLS) == []
        assert mcp_server.search_skills("   ", self.SKILLS) == []
        assert mcp_server.search_skills("kubernetes", self.SKILLS) == []

    def test_limit_caps_results(self):
        many = [{"name": f"s{i}", "description": "tool"} for i in range(30)]
        assert len(mcp_server.search_skills("tool", many, limit=5)) == 5


# ─── call_tool: compact handlers ─────────────────────────────────────────────


class TestCallToolCompact:
    async def test_search_skills_tool_returns_matches(self, skills_dir):
        result = await mcp_server.call_tool("clade_search_skills", {"query": "blog seo"})
        text = result.content[0].text
        assert "beta" in text and "clade_run_skill" in text
        assert "alpha" not in text

    async def test_search_skills_no_match_suggests_list(self, skills_dir):
        result = await mcp_server.call_tool("clade_search_skills", {"query": "zzz-nothing"})
        assert "No skills match" in result.content[0].text

    async def test_search_skills_requires_query(self, skills_dir):
        result = await mcp_server.call_tool("clade_search_skills", {})
        assert result.isError

    async def test_run_skill_requires_name(self, skills_dir):
        result = await mcp_server.call_tool("clade_run_skill", {})
        assert result.isError

    async def test_run_skill_unknown_name_is_error(self, skills_dir):
        result = await mcp_server.call_tool("clade_run_skill", {"name": "nope"})
        assert result.isError
        assert "Skill not found: nope" in result.content[0].text

    async def test_run_skill_executes_via_claude(self, skills_dir, monkeypatch):
        captured = {}

        def _fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return SimpleNamespace(returncode=0, stdout='{"summary": "all done"}', stderr="")

        monkeypatch.setattr(mcp_server.subprocess, "run", _fake_run)
        result = await mcp_server.call_tool(
            "clade_run_skill", {"name": "alpha", "args": "--dry-run"}
        )
        assert not getattr(result, "isError", False)
        assert result.content[0].text == "all done"
        prompt = captured["cmd"][2]
        assert "Prompt body for alpha" in prompt
        assert "--dry-run" in prompt  # args reached the skill prompt

    async def test_per_skill_tool_name_still_works(self, skills_dir, monkeypatch):
        """Clients with cached enumeration-mode tool lists must not break."""
        def _fake_run(cmd, **kwargs):
            return SimpleNamespace(returncode=0, stdout='{"summary": "ok"}', stderr="")

        monkeypatch.setattr(mcp_server.subprocess, "run", _fake_run)
        result = await mcp_server.call_tool("clade_beta", {})
        assert result.content[0].text == "ok"
