"""Deterministic tests for the worker execution-provider abstraction.

Covers the two invariants that matter: the claude provider reproduces the
historical inline command byte-for-byte (default path unchanged), and the codex
provider emits a well-formed `codex exec` command with none of the claude-only
flags and with stdin closed so a headless worker cannot hang.
"""

import shlex
from pathlib import Path

from config import SONNET_MODEL, _MODEL_ALIASES, _build_tool_flags, _fallback_flag
from worker_provider import (
    ClaudeProvider,
    CodexProvider,
    WorkerProvider,
    get_worker_provider,
)

TASK = Path("/tmp/task-abc.md")
NO_MCP = Path("/nonexistent/.claude/mcp.json")


# ─── ClaudeProvider: byte-identical to the historical inline command ──────────
def test_claude_command_is_byte_identical_to_legacy():
    # The exact string worker.py built inline before the provider abstraction.
    expected = (
        f'claude -p "$(cat {shlex.quote(str(TASK))})" '
        f"--model {SONNET_MODEL} --dangerously-skip-permissions"
        f"{_fallback_flag('sonnet')}{_build_tool_flags(None)}"
    )
    got = ClaudeProvider().build_command(
        task_file=TASK, requested_model="sonnet", task_type=None, mcp_config=NO_MCP
    )
    assert got == expected


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


def test_claude_resolve_model_maps_aliases_and_falls_back():
    p = ClaudeProvider()
    assert p.resolve_model("sonnet") == _MODEL_ALIASES["sonnet"]
    assert p.resolve_model("opus") == _MODEL_ALIASES["opus"]
    # An unknown/garbage model degrades to the sonnet default, never crashes.
    assert p.resolve_model("gpt-5.6-sol") == SONNET_MODEL
    assert p.resolve_model(None) == SONNET_MODEL


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


def test_codex_resolve_model_only_accepts_codex_ids():
    p = CodexProvider()
    assert p.resolve_model("gpt-5.6-sol") == "gpt-5.6-sol"
    assert p.resolve_model("o4-mini") == "o4-mini"
    assert p.resolve_model("sonnet") is None  # claude alias -> codex default
    assert p.resolve_model("") is None
    assert p.resolve_model(None) is None


def test_codex_has_no_continue_command():
    assert CodexProvider().build_continue_command(task_file=TASK, requested_model=None) is None


# ─── Factory / selection ──────────────────────────────────────────────────────
def test_factory_resolves_known_providers():
    assert isinstance(get_worker_provider("claude"), ClaudeProvider)
    assert isinstance(get_worker_provider("codex"), CodexProvider)
    assert get_worker_provider("codex").name == "codex"


def test_factory_unknown_name_falls_back_to_claude():
    # A typo'd provider must never strand the pool on an unrunnable command.
    assert isinstance(get_worker_provider("bogus"), ClaudeProvider)
    assert isinstance(get_worker_provider(""), ClaudeProvider)
    assert isinstance(get_worker_provider("CODEX"), CodexProvider)  # case-insensitive


def test_factory_none_reads_global_setting(monkeypatch):
    import config

    monkeypatch.setitem(config.GLOBAL_SETTINGS, "worker_provider", "codex")
    assert isinstance(get_worker_provider(None), CodexProvider)
    monkeypatch.setitem(config.GLOBAL_SETTINGS, "worker_provider", "claude")
    assert isinstance(get_worker_provider(None), ClaudeProvider)


def test_all_providers_are_workerprovider_subclasses():
    assert issubclass(ClaudeProvider, WorkerProvider)
    assert issubclass(CodexProvider, WorkerProvider)
