"""Deterministic tests for the worker execution-provider abstraction.

Covers the invariants that matter: the claude provider still reproduces the
historical inline command in every part the provider abstraction was meant to
preserve, it asks the agent to report its own usage, and the codex provider
emits a well-formed `codex exec` command with none of the claude-only flags and
with stdin closed so a headless worker cannot hang.
"""

import json
import shlex
import stat
from pathlib import Path

import pytest

from agent_runtime import AgentRuntimeSelectionError
from config import SONNET_MODEL, _MODEL_ALIASES, _build_tool_flags, _fallback_flag
from worker_provider import (
    ClaudeProvider,
    CodexProvider,
    WorkerProvider,
    get_agent_runtime,
)
from worker_provider import _probe_runtime_version

TASK = Path("/tmp/task-abc.md")
NO_MCP = Path("/nonexistent/.claude/mcp.json")


# ─── ClaudeProvider: the historical inline command, plus self-reported usage ──
def test_claude_command_matches_legacy_apart_from_structured_output():
    """The legacy string, with `--output-format stream-json --verbose` added.

    This test pinned the pre-abstraction command byte-for-byte, which also
    pinned the defect that command carried: with no `--output-format`, the CLI
    printed prose, `_parse_token_usage` matched nothing, and every worker was
    recorded at $0.00 — the figure the token budget compares against and
    routing_break_even divides by. The byte-identity contract is deliberately
    relaxed here; everything the abstraction was meant to preserve still is.
    """
    legacy = (
        f'claude -p "$(cat {shlex.quote(str(TASK))})" '
        f"--model {SONNET_MODEL} --dangerously-skip-permissions"
        f"{_fallback_flag('sonnet')}{_build_tool_flags(None)}"
    )
    got = ClaudeProvider().build_command(
        task_file=TASK, requested_model="sonnet", task_type=None, mcp_config=NO_MCP
    )
    assert got == legacy + (
        " --output-format stream-json --verbose"
        " --exclude-dynamic-system-prompt-sections"
    )


def test_claude_command_lets_workers_share_a_prompt_cache():
    """Every worker gets its own git worktree, so every worker had its own cache.

    The default system prompt embeds cwd, env info, memory paths and git status.
    Worktree-per-worker makes those differ for every spawn by construction, so a
    fan-out of N was N cache WRITES (1.25x base input) where N-1 could have been
    reads (0.1x) — a 12.5x price difference on the shared prefix, paid on every
    fan-out this repository has ever run. The flag moves those sections into the
    first user message; the CLI's own help calls it "Improves cross-user
    prompt-cache reuse".
    """
    got = ClaudeProvider().build_command(
        task_file=TASK, requested_model="sonnet", task_type=None, mcp_config=NO_MCP
    )
    assert "--exclude-dynamic-system-prompt-sections" in got


def test_prompt_cache_sharing_is_switchable(monkeypatch):
    import config

    monkeypatch.setitem(config.GLOBAL_SETTINGS, "worker_shared_prompt_cache", False)
    got = ClaudeProvider().build_command(
        task_file=TASK, requested_model="sonnet", task_type=None, mcp_config=NO_MCP
    )
    assert "--exclude-dynamic-system-prompt-sections" not in got


def test_claude_command_asks_the_agent_to_report_its_own_usage():
    """--verbose is load-bearing, not decoration.

    `claude --print --output-format=stream-json` without it exits 1 with
    "requires --verbose" (CLI 2.1.236), so dropping it fails every spawn
    instead of degrading to the old behaviour.
    """
    for got in (
        ClaudeProvider().build_command(
            task_file=TASK, requested_model="sonnet", task_type=None, mcp_config=NO_MCP
        ),
        ClaudeProvider().build_continue_command(task_file=TASK, requested_model="sonnet"),
    ):
        assert "--output-format stream-json" in got
        assert "--verbose" in got


def test_structured_output_setting_is_a_kill_switch(monkeypatch):
    from config import GLOBAL_SETTINGS

    monkeypatch.setitem(GLOBAL_SETTINGS, "worker_structured_output", False)
    got = ClaudeProvider().build_command(
        task_file=TASK, requested_model="sonnet", task_type=None, mcp_config=NO_MCP
    )
    assert "--output-format" not in got


def test_claude_appends_mcp_config_only_when_present(tmp_path):
    mcp = tmp_path / "mcp.json"
    mcp.write_text("{}")
    with_mcp = ClaudeProvider().build_command(
        task_file=TASK, requested_model="sonnet", task_type=None, mcp_config=mcp
    )
    assert f"--mcp-config {shlex.quote(str(mcp))}" in with_mcp
    without = ClaudeProvider().build_command(
        task_file=TASK, requested_model="sonnet", task_type=None, mcp_config=NO_MCP
    )
    assert "--mcp-config" not in without


def test_claude_resolve_model_maps_aliases_and_preserves_opaque_ids():
    p = ClaudeProvider()
    assert p.resolve_model("sonnet") == _MODEL_ALIASES["sonnet"]
    assert p.resolve_model("opus") == _MODEL_ALIASES["opus"]
    # Model IDs belong to the selected connection, not a Clade allowlist.
    assert p.resolve_model("MiniMax-M2.5") == "MiniMax-M2.5"
    assert p.resolve_model("kimi-k2.5") == "kimi-k2.5"
    assert p.resolve_model(None) == SONNET_MODEL


def test_claude_shell_quotes_opaque_model_and_rejects_whitespace():
    cmd = ClaudeProvider().build_command(
        task_file=TASK,
        requested_model="vendor/model+2026.07",
        task_type=None,
        mcp_config=NO_MCP,
    )
    assert f"--model {shlex.quote('vendor/model+2026.07')}" in cmd
    with pytest.raises(ValueError, match="opaque identifier"):
        ClaudeProvider().build_command(
            task_file=TASK,
            requested_model="model; echo injected",
            task_type=None,
            mcp_config=NO_MCP,
        )


def test_claude_continue_command_uses_continue_flag():
    cmd = ClaudeProvider().build_continue_command(task_file=TASK, requested_model="sonnet")
    assert cmd is not None
    assert "claude -p --continue" in cmd
    assert f"--model {SONNET_MODEL}" in cmd


def test_claude_effort_is_passed_but_omitted_for_haiku():
    sonnet = ClaudeProvider().build_command(
        task_file=TASK, requested_model="sonnet", task_type=None,
        mcp_config=NO_MCP, effort="high",
    )
    haiku = ClaudeProvider().build_command(
        task_file=TASK, requested_model="haiku", task_type=None,
        mcp_config=NO_MCP, effort="high",
    )
    assert "--effort high" in sonnet
    assert "--effort" not in haiku


def test_claude_rejects_unknown_effort_at_command_boundary():
    cmd = ClaudeProvider().build_command(
        task_file=TASK, requested_model="sonnet", task_type=None,
        mcp_config=NO_MCP, effort="high; echo injected",
    )
    assert "--effort" not in cmd
    assert "injected" not in cmd


# ─── CodexProvider: well-formed codex exec, no claude-only flags ──────────────
def test_codex_command_shape_with_default_model():
    cmd = CodexProvider().build_command(
        task_file=TASK, requested_model="sonnet", task_type=None, mcp_config=NO_MCP
    )
    assert cmd.startswith("codex exec ")
    assert "--dangerously-bypass-approvals-and-sandbox" in cmd
    assert f'"$(cat {shlex.quote(str(TASK))})"' in cmd
    # stdin closed so codex exec never blocks on EOF (the real hang bug).
    assert cmd.rstrip().endswith("< /dev/null")
    # A claude alias is NOT forced onto codex -> no -m, no claude-only flags.
    assert " -m " not in f" {cmd} "
    assert "claude" not in cmd
    assert "--model" not in cmd
    assert "--dangerously-skip-permissions" not in cmd


def test_codex_command_passes_explicit_codex_model():
    cmd = CodexProvider().build_command(
        task_file=TASK, requested_model="gpt-5.6-sol", task_type=None, mcp_config=NO_MCP
    )
    assert "-m gpt-5.6-sol" in cmd


def test_codex_command_passes_reasoning_effort_as_config():
    cmd = CodexProvider().build_command(
        task_file=TASK, requested_model="gpt-5.6-sol", task_type=None,
        mcp_config=NO_MCP, effort="medium",
    )
    parts = shlex.split(cmd)
    effort_index = parts.index("-c")
    assert parts[effort_index:effort_index + 2] == [
        "-c", 'model_reasoning_effort="medium"'
    ]


def test_codex_connection_profile_is_bound_on_command():
    cmd = CodexProvider().build_command(
        task_file=TASK,
        requested_model="gateway/reasoner-v9",
        task_type=None,
        mcp_config=NO_MCP,
        connection={
            "discovery": {
                "store": "codex-config",
                "profile": "enterprise-work",
            }
        },
    )

    assert 'model_provider="enterprise-work"' in cmd


def test_claude_connection_profile_replaces_inherited_transport_env(
    tmp_path, monkeypatch
):
    profiles = tmp_path / "providers.json"
    profiles.write_text(
        json.dumps(
            {
                "providers": {
                    "work": {
                        "base_url": "https://gateway.example/anthropic/",
                        "api_key_env": "CLADE_TEST_GATEWAY_KEY",
                        "models": ["gateway/model-v1"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CLADE_CLAUDE_PROVIDERS_FILE", str(profiles))
    monkeypatch.setenv("CLADE_TEST_GATEWAY_KEY", "selected-secret")
    env = {
        "ANTHROPIC_BASE_URL": "https://wrong-account.example",
        "ANTHROPIC_API_KEY": "wrong-secret",
    }

    ClaudeProvider().apply_connection_env(
        {
            "discovery": {
                "adapter": "anthropic",
                "store": "claude-providers",
                "profile": "work",
            }
        },
        env,
    )

    assert env["ANTHROPIC_BASE_URL"] == "https://gateway.example/anthropic"
    assert env["ANTHROPIC_API_KEY"] == "selected-secret"


def test_codex_resolve_model_accepts_connection_scoped_opaque_ids():
    p = CodexProvider()
    assert p.resolve_model("gpt-5.6-sol") == "gpt-5.6-sol"
    assert p.resolve_model("o4-mini") == "o4-mini"
    assert p.resolve_model("custom/minimax-m2.5") == "custom/minimax-m2.5"
    assert p.resolve_model("sonnet") is None  # claude alias -> codex default
    assert p.resolve_model("") is None
    assert p.resolve_model(None) is None


def test_codex_has_no_continue_command():
    assert CodexProvider().build_continue_command(task_file=TASK, requested_model=None) is None


# ─── Agent-runtime factory / selection ────────────────────────────────────────
def test_factory_resolves_known_agent_runtimes():
    assert isinstance(get_agent_runtime("claude"), ClaudeProvider)
    assert isinstance(get_agent_runtime("codex"), CodexProvider)
    assert get_agent_runtime("codex").name == "codex"
    assert isinstance(get_agent_runtime("CODEX"), CodexProvider)  # normalized


@pytest.mark.parametrize("invalid", ["bogus", "", "shell; rm -rf /"])
def test_factory_unknown_runtime_fails_closed(invalid):
    with pytest.raises(AgentRuntimeSelectionError, match="Unsupported agent runtime"):
        get_agent_runtime(invalid)


def test_factory_none_reads_global_runtime_setting(monkeypatch):
    import config

    monkeypatch.setitem(config.GLOBAL_SETTINGS, "agent_runtime", "codex")
    assert isinstance(get_agent_runtime(None), CodexProvider)
    monkeypatch.setitem(config.GLOBAL_SETTINGS, "agent_runtime", "claude")
    assert isinstance(get_agent_runtime(None), ClaudeProvider)


def test_factory_invalid_global_runtime_fails_closed(monkeypatch):
    import config

    monkeypatch.setitem(config.GLOBAL_SETTINGS, "agent_runtime", "")
    with pytest.raises(AgentRuntimeSelectionError, match="<empty>"):
        get_agent_runtime(None)


def test_all_providers_are_workerprovider_subclasses():
    assert issubclass(ClaudeProvider, WorkerProvider)
    assert issubclass(CodexProvider, WorkerProvider)


def test_runtime_version_probe_isolated_from_repository_and_stdin(
    tmp_path, monkeypatch
):
    runtime = tmp_path / "probe-runtime"
    runtime.write_text(
        "#!/usr/bin/env bash\n"
        "set -eu\n"
        "test ! -t 0\n"
        "echo polluted > should-not-reach-repository.txt\n"
        "echo runtime-v1\n",
        encoding="utf-8",
    )
    runtime.chmod(runtime.stat().st_mode | stat.S_IXUSR)
    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.chdir(repository)

    assert _probe_runtime_version(str(runtime)) == "runtime-v1"
    assert not (repository / "should-not-reach-repository.txt").exists()
