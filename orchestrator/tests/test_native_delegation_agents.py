"""Native Claude/Codex/Kimi delegation profiles preserve the v1 safety contract."""

from pathlib import Path
import re
import tomllib

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]


# ─── What each consumer loads ────────────────────────────────────────────────
# install.sh copies configs/agents/ to ~/.claude/agents/, the plugin loader
# reads the generated mirror at agents/, and install.sh copies the Codex and
# Kimi profiles to their respective agents/ directories. Each one hands the
# model a different text: the body after the front matter, or
# developer_instructions.

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


def _agent_frontmatter(path: Path) -> dict:
    text = path.read_text()
    assert text.startswith("---\n"), path
    return yaml.safe_load(text[4:].split("\n---\n", 1)[0])


# What the lead reads when it decides whether to delegate at all.
KIMI_EXPLORER = ROOT / "configs" / "kimi-agents" / "clade-explorer.md"
KIMI_IMPLEMENTER = ROOT / "configs" / "kimi-agents" / "clade-implementer.md"

IMPLEMENTER_DESCRIPTIONS = {
    "claude-installed": lambda: _agent_description(ROOT / "configs" / "agents" / "bounded-implementer.md"),
    "claude-plugin": lambda: _agent_description(ROOT / "agents" / "bounded-implementer.md"),
    "codex-installed": lambda: tomllib.loads(
        (ROOT / "configs" / "codex-agents" / "clade_cheap_worker.toml").read_text())["description"],
    "kimi-installed": lambda: _agent_description(KIMI_IMPLEMENTER),
}

IMPLEMENTER_PROMPTS = {
    "claude-installed": lambda: _agent_body(ROOT / "configs" / "agents" / "bounded-implementer.md"),
    "claude-plugin": lambda: _agent_body(ROOT / "agents" / "bounded-implementer.md"),
    "codex-installed": lambda: _codex_instructions(ROOT / "configs" / "codex-agents" / "clade_cheap_worker.toml"),
    "kimi-installed": lambda: _agent_body(KIMI_IMPLEMENTER),
}

EXPLORER_DESCRIPTIONS = {
    "codex-installed": lambda: tomllib.loads(
        (ROOT / "configs" / "codex-agents" / "clade_cheap_explorer.toml").read_text())["description"],
    "kimi-installed": lambda: _agent_description(KIMI_EXPLORER),
}

EXPLORER_PROMPTS = {
    "codex-installed": lambda: _codex_instructions(ROOT / "configs" / "codex-agents" / "clade_cheap_explorer.toml"),
    "kimi-installed": lambda: _agent_body(KIMI_EXPLORER),
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
    text = (ROOT / "configs" / "agents" / "bounded-implementer.md").read_text()
    frontmatter, body = text[4:].split("\n---\n", 1)
    profile = yaml.safe_load(frontmatter)
    assert profile["model"] == "sonnet"
    assert profile["effort"] == "medium"
    assert "deterministic verifier" in profile["description"]
    assert "Never spawn another agent" in body
    assert "lead session owns" in body


def test_kimi_agents_use_supported_frontmatter_and_enforced_tool_contracts():
    supported_keys = {
        "name", "description", "whenToUse", "override", "tools",
        "disallowedTools", "subagents",
    }
    profiles = {
        path.stem: _agent_frontmatter(path)
        for path in (KIMI_EXPLORER, KIMI_IMPLEMENTER)
    }
    for name, profile in profiles.items():
        assert profile["name"] == name
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", profile["name"])
        assert profile["name"] not in {"agent", "coder", "explore", "plan"}
        assert set(profile) <= supported_keys
        assert not {"model", "effort", "maxTurns"}.intersection(profile)
        assert profile["subagents"] == []

    explorer_tools = profiles["clade-explorer"]["tools"]
    assert explorer_tools == ["Read", "ReadMediaFile", "Grep", "Glob", "FetchURL", "WebSearch"]
    assert not {"Bash", "Edit", "Write", "Agent", "AgentSwarm"}.intersection(explorer_tools)
    assert profiles["clade-implementer"]["tools"] == [
        "Read", "Bash", "Write", "Edit", "Grep", "Glob",
    ]


@pytest.mark.parametrize("consumer", sorted(EXPLORER_DESCRIPTIONS))
def test_explorer_description_is_bounded_and_read_only(consumer):
    description = EXPLORER_DESCRIPTIONS[consumer]().lower()
    assert "bounded" in description
    assert "read-only" in description
    assert "do not use for architecture or final decisions" in description


@pytest.mark.parametrize("consumer", sorted(EXPLORER_PROMPTS))
def test_explorer_is_non_recursive_and_returns_evidence(consumer):
    prompt = " ".join(EXPLORER_PROMPTS[consumer]().split()).lower()
    assert "file-and-line evidence" in prompt
    assert "do not edit files" in prompt
    assert "architectural decisions" in prompt
    assert "spawn" in prompt and "another agent" in prompt
    assert "retry" in prompt and "more than once" in prompt


def test_kimi_policy_carries_every_codex_section_in_order():
    def headings(path: Path) -> list[str]:
        return re.findall(r"^## .+$", path.read_text(), flags=re.MULTILINE)

    assert headings(ROOT / "configs" / "KIMI_AGENTS.md") == headings(
        ROOT / "configs" / "CODEX_AGENTS.md"
    )


@pytest.mark.parametrize("tool", ["Workflow", "ScheduleWakeup", "Monitor", "Artifact"])
def test_kimi_policy_does_not_name_claude_only_tools(tool):
    lines = (ROOT / "configs" / "KIMI_AGENTS.md").read_text().splitlines()
    # This required Codex heading names a report category, not the tool.
    content = "\n".join(line for line in lines if line != "## Artifact reports across projects")
    assert not re.search(rf"\b{re.escape(tool)}\b", content)


def test_kimi_policy_uses_native_tools_roles_and_delivery_commands():
    policy = (ROOT / "configs" / "KIMI_AGENTS.md").read_text()
    for snippet in (
        'Agent(subagent_type="clade-explorer"',
        'Agent(subagent_type="clade-implementer"',
        "`TodoList`", "`FetchURL`", "`WebSearch`", "`AskUserQuestion`",
        'Skill(skill="delivery")', 'committer "type: message" file1 file2',
        "--no-push", "ci-local.py", "`manual`", "`yolo`", "`auto`",
    ):
        assert snippet in policy
    assert len(policy.splitlines()) <= 200


@pytest.mark.parametrize("consumer", sorted(IMPLEMENTER_DESCRIPTIONS))
def test_implementer_description_is_bounded_with_explicit_ownership(consumer):
    description = " ".join(IMPLEMENTER_DESCRIPTIONS[consumer]().split()).lower()
    assert "one bounded, low-risk implementation" in description
    assert "explicit file ownership" in description
    assert "deterministic verifier" in description


@pytest.mark.parametrize("consumer", sorted(IMPLEMENTER_PROMPTS))
def test_implementer_prompt_preserves_ownership_retry_and_lead_contract(consumer):
    prompt = " ".join(IMPLEMENTER_PROMPTS[consumer]().split()).lower()
    assert "smallest coherent change" in prompt
    assert "never spawn another agent" in prompt
    assert "never retry a failed approach more than once" in prompt
    assert re.search(r"lead(?: session)? owns architecture", prompt)
    assert "acceptance" in prompt


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


@pytest.mark.parametrize("policy", ["CLAUDE.md", "CODEX_AGENTS.md", "KIMI_AGENTS.md"])
def test_global_policies_disallow_recursive_and_cross_vendor_auto_delegation(policy):
    policies = (ROOT / "configs" / policy).read_text().lower()
    assert "must not delegate recursively" in policies
    assert "cross-vendor delegation" in policies
    assert "explicit-only" in policies
    assert "one cheap retry" in policies
