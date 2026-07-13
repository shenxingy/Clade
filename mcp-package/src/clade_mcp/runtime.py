"""Agent runtime adapters for executing Clade MCP skills.

The MCP transport is provider-neutral.  This module keeps the subprocess
runtime neutral too: existing installations default to Claude for backwards
compatibility, while ``CLADE_RUNTIME=codex`` executes the same skill prompt
through Codex non-interactive mode.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


SUPPORTED_RUNTIMES = ("claude", "codex")


@dataclass(frozen=True)
class RuntimeResult:
    text: str
    returncode: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class AgentRuntime:
    name = "base"
    executable = ""

    def execute(
        self,
        prompt: str,
        project_dir: Path,
        *,
        timeout: int = 300,
        env: Mapping[str, str] | None = None,
    ) -> RuntimeResult:
        raise NotImplementedError


class ClaudeRuntime(AgentRuntime):
    name = "claude"
    executable = "claude"

    def execute(self, prompt, project_dir, *, timeout=300, env=None) -> RuntimeResult:
        command = [
            self.executable,
            "-p",
            prompt,
            "--project",
            str(project_dir),
            "--dangerously-skip-permissions",
            "--output-format",
            "json",
        ]
        process_env = dict(os.environ if env is None else env)
        process_env["CLAUDE_CODE_EXPERIMENTAL_SKIP_INJECT"] = "1"
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=process_env,
        )
        if result.returncode:
            return RuntimeResult("", result.returncode, result.stderr[:2000])
        return RuntimeResult(_parse_claude_output(result.stdout))


class CodexRuntime(AgentRuntime):
    name = "codex"
    executable = "codex"

    def execute(self, prompt, project_dir, *, timeout=300, env=None) -> RuntimeResult:
        process_env = dict(os.environ if env is None else env)
        command = [self.executable, "exec", "--json", "--ephemeral", "-C", str(project_dir)]
        if _truthy(process_env.get("CLADE_CODEX_BYPASS_PERMISSIONS", "")):
            command.append("--dangerously-bypass-approvals-and-sandbox")
        else:
            sandbox = process_env.get("CLADE_CODEX_SANDBOX", "workspace-write")
            if sandbox not in {"read-only", "workspace-write", "danger-full-access"}:
                return RuntimeResult(
                    "",
                    2,
                    "CLADE_CODEX_SANDBOX must be read-only, workspace-write, or danger-full-access",
                )
            command.extend(("--sandbox", sandbox))
        command.append("-")
        result = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=process_env,
        )
        if result.returncode:
            return RuntimeResult("", result.returncode, result.stderr[:2000])
        return RuntimeResult(_parse_codex_output(result.stdout))


def get_runtime(env: Mapping[str, str] | None = None) -> AgentRuntime:
    runtime_env = os.environ if env is None else env
    name = runtime_env.get("CLADE_RUNTIME", "claude").strip().lower()
    if name == "auto":
        # Auto remains conservative: prefer the historical runtime when both
        # CLIs exist, then fall back to Codex.
        import shutil

        name = "claude" if shutil.which("claude") else "codex"
    if name == "claude":
        return ClaudeRuntime()
    if name == "codex":
        return CodexRuntime()
    supported = ", ".join((*SUPPORTED_RUNTIMES, "auto"))
    raise ValueError(f"Unsupported CLADE_RUNTIME={name!r}; expected one of: {supported}")


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_claude_output(stdout: str) -> str:
    try:
        output = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return stdout[:2000] if stdout else "(no output)"
    if isinstance(output, dict):
        for key in ("summary", "result", "content"):
            value = output.get(key)
            if isinstance(value, str) and value:
                return value
    return str(output)[:2000]


def _parse_codex_output(stdout: str) -> str:
    """Extract the final assistant message from ``codex exec --json`` JSONL."""
    messages: list[str] = []
    fallbacks: list[str] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            fallbacks.append(line)
            continue
        if not isinstance(event, dict):
            continue
        item = event.get("item")
        if event.get("type") == "item.completed" and isinstance(item, dict):
            if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                messages.append(item["text"])
        message = event.get("message")
        if isinstance(message, str) and message:
            fallbacks.append(message)
    if messages:
        return messages[-1]
    if fallbacks:
        return "\n".join(fallbacks)[-2000:]
    return stdout[-2000:] if stdout else "(no output)"
