"""Native Claude/Codex delegation profiles preserve the v1 safety contract."""

from pathlib import Path
import re
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[2]


# ─── What each consumer loads ────────────────────────────────────────────────
# install.sh copies configs/agents/ to ~/.claude/agents/, the plugin loader
# reads the generated mirror at agents/, and install.sh copies the Codex
# profile to ~/.codex/agents/. Each one hands the model a different text: the
# body after the front matter, or developer_instructions.

def _agent_body(path: Path) -> str:
    text = path.read_text()
    assert text.startswith("---\n"), path
    return text[4:].split("\n---\n", 1)[1]


def _codex_instructions(path: Path) -> str:
    return tomllib.loads(path.read_text())["developer_instructions"]


def _agent_description(path: Path) -> str:
    text = path.read_text()
    assert text.startswith("---\n"), path
    frontmatter = text[4:].split("\n---\n", 1)[0]
    line = next(l for l in frontmatter.splitlines() if l.startswith("description:"))
    return line.split(":", 1)[1].strip()


# What the lead reads when it decides whether to delegate at all.
IMPLEMENTER_DESCRIPTIONS = {
    "claude-installed": lambda: _agent_description(ROOT / "configs" / "agents" / "bounded-implementer.md"),
    "claude-plugin": lambda: _agent_description(ROOT / "agents" / "bounded-implementer.md"),
    "codex-installed": lambda: tomllib.loads(
        (ROOT / "configs" / "codex-agents" / "clade_cheap_worker.toml").read_text())["description"],
}

IMPLEMENTER_PROMPTS = {
    "claude-installed": lambda: _agent_body(ROOT / "configs" / "agents" / "bounded-implementer.md"),
    "claude-plugin": lambda: _agent_body(ROOT / "agents" / "bounded-implementer.md"),
    "codex-installed": lambda: _codex_instructions(ROOT / "configs" / "codex-agents" / "clade_cheap_worker.toml"),
}


def _sentences(text: str) -> list[str]:
    folded = " ".join(text.split()).lower()
    return re.split(r"(?<=[.!?:])\s+", folded)


def test_codex_cheap_agents_are_valid_and_non_recursive():
    agents = ROOT / "configs" / "codex-agents"
    explorer = tomllib.loads((agents / "clade_cheap_explorer.toml").read_text())
    worker = tomllib.loads((agents / "clade_cheap_worker.toml").read_text())
    for profile in (explorer, worker):
        assert profile["name"]
        assert profile["description"]
        assert profile["developer_instructions"]
        assert profile["model"] == "gpt-5.6-luna"
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


@pytest.mark.parametrize("consumer", sorted(IMPLEMENTER_PROMPTS))
def test_implementer_treats_its_verifier_and_fixtures_as_read_only(consumer):
    """The verifier is the independent sensor, so the implementer may not edit it.

    Read per consumer copy: a contract line that reaches the source but not
    the plugin mirror (or the Codex twin) is a line one runtime never sees.
    """
    sentences = _sentences(IMPLEMENTER_PROMPTS[consumer]())
    read_only = [s for s in sentences if "read-only" in s]
    assert read_only, f"{consumer}: no sentence makes anything read-only"
    scope = " ".join(read_only)
    for sensor in ("verifier", "tests", "fixtures"):
        assert sensor in scope, f"{consumer}: read-only clause omits {sensor}"
    assert any(
        "never weaken" in s and "assertion" in s and "fixture" in s for s in sentences
    ), f"{consumer}: adding a test may still weaken an existing assertion or fixture"
    assert any(
        "verifier" in s and "stop and report" in s and "instead of changing it" in s
        for s in sentences
    ), f"{consumer}: a wrong verifier is not routed back to the lead"


@pytest.mark.parametrize("consumer", sorted(IMPLEMENTER_DESCRIPTIONS))
def test_implementer_description_tells_the_lead_the_verifier_is_read_only(consumer):
    """The lead picks the agent from its description, so the limit belongs there too."""
    sentences = _sentences(IMPLEMENTER_DESCRIPTIONS[consumer]())
    assert any("verifier" in s and "read-only" in s for s in sentences), (
        f"{consumer}: the description does not say the verifier is read-only")
    assert any("do not use" in s and "edit the verifier" in s for s in sentences), (
        f"{consumer}: the description does not exclude a change that edits the verifier")


def test_global_policies_disallow_recursive_and_cross_vendor_auto_delegation():
    policies = "\n".join([
        (ROOT / "configs" / "CLAUDE.md").read_text(),
        (ROOT / "configs" / "CODEX_AGENTS.md").read_text(),
    ]).lower()
    assert "must not delegate recursively" in policies
    assert "cross-vendor delegation" in policies
    assert "explicit-only" in policies
    assert "one cheap retry" in policies
