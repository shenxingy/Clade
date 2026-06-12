"""Regression tests for the second-opinion relay agents (mic92 pattern):
configs/agents/second-opinion-{codex,gemini}.md must stay cheap (haiku),
Bash-only, read-only, and verbatim relays with a graceful CLI-missing path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO_ROOT / "configs" / "agents"

_AGENTS = {
    "second-opinion-codex": "codex",
    "second-opinion-gemini": "gemini",
}


def _parse_agent(name: str) -> tuple[dict, str]:
    yaml = pytest.importorskip("yaml")
    text = (AGENTS_DIR / f"{name}.md").read_text()
    assert text.startswith("---\n"), f"{name}: missing frontmatter fence"
    fm, body = text[4:].split("\n---\n", 1)
    return yaml.safe_load(fm), body


@pytest.mark.parametrize("agent_name,cli", sorted(_AGENTS.items()))
def test_agent_frontmatter_is_cheap_bash_only_readonly(agent_name, cli):
    fm, _body = _parse_agent(agent_name)
    assert fm["name"] == agent_name
    assert fm["model"] == "haiku"  # relay needs no reasoning horsepower
    assert fm["tools"] == "Bash"  # Bash only — no file tools
    assert "Write" in fm["disallowedTools"] and "Edit" in fm["disallowedTools"]
    assert cli in fm["description"].lower()
    assert "explicitly asks" in fm["description"]  # invoked on request only


@pytest.mark.parametrize("agent_name,cli", sorted(_AGENTS.items()))
def test_agent_body_relays_verbatim_and_handles_missing_cli(agent_name, cli):
    _fm, body = _parse_agent(agent_name)
    assert f"command -v {cli}" in body  # graceful not-installed check
    assert "not installed" in body
    assert "verbatim" in body  # relay, never a synthesis
    assert "STOP" in body  # no answer-it-yourself fallback


def test_codex_invocation_is_sandboxed_readonly():
    _fm, body = _parse_agent("second-opinion-codex")
    assert "codex exec --sandbox read-only" in body


def test_gemini_invocation_avoids_yolo_approval():
    _fm, body = _parse_agent("second-opinion-gemini")
    assert "gemini -p" in body
    # the one place yolo may appear is the prohibition itself
    assert "Never pass `--approval-mode yolo`" in body
