"""Provider semantics stay aligned across canonical and generated surfaces."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL = REPO_ROOT / "configs" / "skills" / "provider"
PLUGIN = REPO_ROOT / "plugins" / "clade" / "skills" / "provider"
MCP = REPO_ROOT / "mcp-package" / "skills" / "provider"


def _normalized(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_canonical_workflow_carries_registry_safety_contract():
    prompt = _normalized(CANONICAL / "prompt.md")

    for required in (
        "Never infer provider/capabilities from a model prefix.",
        "catalog state (`fresh`, `stale`, `unavailable`, or `declared`)",
        "continue only when the resolved opaque model ID is explicitly pinned",
        "never substitute another model, account, or provider",
        "Do not read or print credentials",
    ):
        assert required in prompt


def test_every_surface_names_native_ownership_and_stale_behavior():
    required = {
        "claude-code.md": (
            "user-scoped Claude Code configuration",
            "safe error categories",
        ),
        "codex.md": (
            "user-scoped Codex `model_provider`",
            "neither value may enter repository settings",
        ),
        "mcp.md": (
            "MCP client/runtime owns endpoint",
            "explicit pinned model",
        ),
        "generic.md": (
            "Never invent a live catalog",
            "Never emulate another runtime",
        ),
    }

    for filename, markers in required.items():
        text = _normalized(CANONICAL / "surfaces" / filename)
        for marker in markers:
            assert marker in text, f"{filename}: missing {marker!r}"


def test_generated_distributions_preserve_canonical_provider_semantics():
    canonical_prompt = (CANONICAL / "prompt.md").read_text(encoding="utf-8")
    mcp_prompt = (MCP / "prompt.md").read_text(encoding="utf-8")
    codex_skill = _normalized(PLUGIN / "SKILL.md")

    assert mcp_prompt == canonical_prompt
    for marker in (
        "catalog state (`fresh`, `stale`, `unavailable`, or `declared`)",
        "explicitly pinned",
        "never substitute another model, account, or provider",
        "surface adapter: `codex/v1`",
        "# Codex connection adapter",
    ):
        assert marker in codex_skill
