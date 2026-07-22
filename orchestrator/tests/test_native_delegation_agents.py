"""Native Claude/Codex delegation profiles preserve the v1 safety contract."""

from pathlib import Path
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_codex_cheap_agents_are_valid_and_non_recursive():
    agents = ROOT / "configs" / "codex-agents"
    explorer = tomllib.loads((agents / "clade_cheap_explorer.toml").read_text())
    worker = tomllib.loads((agents / "clade_cheap_worker.toml").read_text())
    for profile in (explorer, worker):
        assert profile["name"]
        assert profile["description"]
        assert profile["developer_instructions"]
        assert profile["model"] == "gpt-5.6-terra"
        instructions = profile["developer_instructions"].lower()
        assert "spawn another agent" in instructions
        assert "more than once" in instructions
    assert explorer["sandbox_mode"] == "read-only"
    assert explorer["model_reasoning_effort"] == "low"
    assert worker["sandbox_mode"] == "workspace-write"
    assert worker["model_reasoning_effort"] == "medium"


def test_claude_bounded_implementer_requires_verifier_and_lead_review():
    yaml = pytest.importorskip("yaml")
    text = (ROOT / "configs" / "agents" / "bounded-implementer.md").read_text()
    frontmatter, body = text[4:].split("\n---\n", 1)
    profile = yaml.safe_load(frontmatter)
    assert profile["model"] == "sonnet"
    assert profile["effort"] == "medium"
    assert "deterministic verifier" in profile["description"]
    assert "Never spawn another agent" in body
    assert "lead session owns" in body


def test_global_policies_disallow_recursive_and_cross_vendor_auto_delegation():
    policies = "\n".join([
        (ROOT / "configs" / "CLAUDE.md").read_text(),
        (ROOT / "configs" / "CODEX_AGENTS.md").read_text(),
    ]).lower()
    assert "must not delegate recursively" in policies
    assert "cross-vendor delegation" in policies
    assert "explicit-only" in policies
    assert "one cheap retry" in policies
