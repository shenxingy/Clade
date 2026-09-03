"""Codex-native plugin distribution and hook compatibility tests."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import shutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "clade"


_PLUGIN_PYCACHE = PLUGIN_ROOT / "hooks" / "__pycache__"


def _load_module(name: str, path: Path):
    # Start from a known state so the assertion after the load means something.
    shutil.rmtree(_PLUGIN_PYCACHE, ignore_errors=True)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def test_codex_plugin_manifest_and_marketplace_are_wired() -> None:
    manifest = json.loads((PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text())
    marketplace = json.loads(
        (REPO_ROOT / ".agents" / "plugins" / "marketplace.json").read_text()
    )
    assert manifest["name"] == "clade"
    assert re.fullmatch(
        r"0\.3\.1(?:\+codex\.[0-9A-Za-z.-]+)?",
        manifest["version"],
    )
    assert manifest["skills"] == "./skills/"
    assert manifest["interface"]["category"] == "Developer Tools"
    entry = next(plugin for plugin in marketplace["plugins"] if plugin["name"] == "clade")
    assert entry["source"]["path"] == "./plugins/clade"
    assert entry["policy"]["installation"] == "AVAILABLE"


def test_codex_plugin_skills_are_generated_and_provider_native() -> None:
    result = subprocess.run(
        [sys.executable, "configs/scripts/regen-codex-plugin.py", "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    skills = list((PLUGIN_ROOT / "skills").glob("*/SKILL.md"))
    assert len(skills) == 26
    assert "green" in {path.parent.name for path in skills}
    merged = "\n".join(path.read_text(encoding="utf-8") for path in skills).lower()
    for forbidden in ("claude -p", "--dangerously-skip-permissions", "~/.claude/", ".claude/"):
        assert forbidden not in merged
    assert "agents.md (or claude.md" not in merged
    assert "&& claude" not in merged
    lifecycle = {"commit", "create-pr", "delivery", "merge-pr", "review-pr", "worktree"}
    assert lifecycle <= {path.parent.name for path in skills}
    for name in lifecycle:
        text = (PLUGIN_ROOT / "skills" / name / "SKILL.md").read_text()
        assert "core contract: `clade.delivery/v1`" in text
        assert "surface adapter: `codex/v1`" in text
        assert f"explicit invocation: `$clade:{name}`" in text
    assert "`$clade:delivery`" in (
        PLUGIN_ROOT / "skills" / "commit" / "SKILL.md"
    ).read_text()
    assert "core contract: `clade.execution/v1`" in (
        PLUGIN_ROOT / "skills" / "provider" / "SKILL.md"
    ).read_text()
    assert "core contract: `clade.status/v1`" in (
        PLUGIN_ROOT / "skills" / "status" / "SKILL.md"
    ).read_text()
    assert "missing progress or quota data as `0`" in (
        PLUGIN_ROOT / "skills" / "status" / "SKILL.md"
    ).read_text()


def test_delivery_lifecycle_has_semantic_parity_across_distributions() -> None:
    lifecycle = {"commit", "create-pr", "delivery", "merge-pr", "review-pr", "worktree"}
    codex = {
        line.strip()
        for line in (PLUGIN_ROOT / "skills.list").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    mcp = {
        line.strip()
        for line in (REPO_ROOT / "mcp-package" / "skills.list").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    canonical = {
        path.name
        for path in (REPO_ROOT / "configs" / "skills").iterdir()
        if path.is_dir()
    }
    assert lifecycle <= codex
    assert lifecycle <= mcp
    assert lifecycle <= canonical


def test_all_codex_skills_end_with_delivery_completion_guard() -> None:
    skills = list((PLUGIN_ROOT / "skills").glob("*/SKILL.md"))
    for path in skills:
        text = path.read_text(encoding="utf-8")
        assert "## Delivery completion" in text, path
        assert "Never report `DONE` while task-owned changes are uncommitted." in text, path
        assert '"not committed/pushed/deployed" caveat after `DONE`' in text, path

    frontend = (PLUGIN_ROOT / "skills" / "frontend-design" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert frontend.rfind("## Delivery completion") > frontend.rfind(
        "## Completion Status"
    )


def test_execution_and_status_semantics_have_distribution_parity() -> None:
    semantic_core = {"provider", "status"}
    codex = {
        line.strip()
        for line in (PLUGIN_ROOT / "skills.list").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    mcp = {
        line.strip()
        for line in (REPO_ROOT / "mcp-package" / "skills.list").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert semantic_core <= codex
    assert semantic_core <= mcp


def test_codex_guardian_denies_and_rewrites_supported_commands() -> None:
    guardian = _load_module(
        "clade_codex_guardian", PLUGIN_ROOT / "hooks" / "pre_tool_guardian.py"
    )
    denied = guardian.evaluate("git push --force origin main")
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    rewritten = guardian.evaluate("git push --force origin feature/native-codex")
    output = rewritten["hookSpecificOutput"]
    assert output["permissionDecision"] == "allow"
    assert "--force-with-lease" in output["updatedInput"]["command"]
    assert "--force-with-lease-with-lease" not in output["updatedInput"]["command"]
    assert guardian.evaluate("git push --force-with-lease origin feature/native-codex") is None
    lease_to_main = guardian.evaluate("git push --force-with-lease origin main")
    assert lease_to_main["hookSpecificOutput"]["permissionDecision"] == "deny"
    recursive_home = guardian.evaluate('rm --recursive --force "$HOME"')
    assert recursive_home["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert guardian.evaluate("git status --short") is None
    # The property is that THIS load writes no bytecode into the shipped
    # plugin, not that the directory happens to be absent. Asserting absence
    # alone made the test pass only on a fresh checkout: a __pycache__ left by
    # any earlier interpreter run (one here dated from a month before this was
    # written) failed it forever afterwards, on a machine where CI could never
    # reproduce it. Clear it first, then assert the loader did not recreate it.
    assert not _PLUGIN_PYCACHE.exists(), (
        f"{_PLUGIN_PYCACHE} was recreated by _load_module — sys.dont_write_bytecode "
        "is no longer taking effect, and the shipped plugin will accumulate .pyc files"
    )


def test_codex_hooks_use_supported_command_handlers() -> None:
    hooks = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    assert set(hooks) == {"SessionStart", "PreToolUse"}
    for groups in hooks.values():
        for group in groups:
            for hook in group["hooks"]:
                assert hook["type"] == "command"
                assert "${PLUGIN_ROOT}" in hook["command"]


def test_codex_session_context_emits_read_only_repository_guidance(tmp_path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "AGENTS.md").write_text("# Test guidance\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "hooks" / "session_context.py")],
        input=json.dumps({"cwd": str(tmp_path)}),
        capture_output=True,
        text=True,
        check=True,
    )
    output = json.loads(result.stdout)["hookSpecificOutput"]
    assert output["hookEventName"] == "SessionStart"
    assert "AGENTS.md" in output["additionalContext"]
    assert "Adaptive delegation" in output["additionalContext"]
    assert "Cross-vendor calls are explicit-only" in output["additionalContext"]
    assert "Delivery completion" in output["additionalContext"]
    assert "Never report DONE with task-owned uncommitted changes" in output[
        "additionalContext"
    ]
    assert "not a DONE caveat" in output["additionalContext"]
    assert "Uncommitted changes" in output["additionalContext"]
    assert not (tmp_path / ".clade").exists()
