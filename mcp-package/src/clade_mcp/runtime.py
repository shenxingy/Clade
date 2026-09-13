"""Agent runtime adapters for executing Clade MCP skills.

The MCP transport is provider-neutral.  This module keeps the subprocess
runtime neutral too: existing installations default to Claude for backwards
compatibility, while ``CLADE_RUNTIME=codex`` executes the same skill prompt
through Codex non-interactive mode.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


SUPPORTED_RUNTIMES = ("claude", "codex")


# ─── Bounded, non-blocking shellout ───────────────────────────────────────────
# `server.call_tool` is `async def` and the MCP SDK dispatches tools/call
# concurrently, so a blocking `subprocess.run` here freezes the read loop, the
# stdout writer, every other in-flight tool call and cancellation handling for
# the whole 300-second timeout. The orchestrator's own `mcp_server.py` carries
# a comment saying exactly this and uses create_subprocess_exec; the
# distributable package — the one other people install — had the bug the
# in-repo copy documents and avoids.


def _kill_process_group(proc: Any) -> None:
    """SIGKILL the child's whole process group, falling back to the child.

    `claude -p` and `codex exec` spawn their own tool subprocesses; killing only
    the direct child leaves those grandchildren running and holding the pipes.
    """
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (OSError, AttributeError):
        with contextlib.suppress(Exception):
            proc.kill()


async def _run_bounded(
    command: list[str],
    *,
    timeout: float,
    env: Mapping[str, str] | None = None,
    stdin_text: str | None = None,
) -> tuple[int, str, str]:
    """Spawn `command` bounded, without blocking the MCP event loop.

    Raises FileNotFoundError when the executable is missing and
    asyncio.TimeoutError on expiry — after SIGKILLing the whole process group
    and draining the pipes, so a run that spawned its own tools leaves nothing
    behind. CancelledError takes the same reaping path, so a cancelled MCP
    request does not leak the child either.
    """
    proc = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE if stdin_text is not None
        else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=dict(env) if env is not None else None,
        start_new_session=True,  # its own group, so the kill reaches grandchildren
    )
    payload = stdin_text.encode() if stdin_text is not None else None
    try:
        out, err = await asyncio.wait_for(proc.communicate(payload), timeout=timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        _kill_process_group(proc)
        # Bounded: if killpg fell through to proc.kill(), a surviving
        # grandchild still holds the pipe and an unbounded drain would hang
        # forever — the exact failure this function exists to remove.
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.communicate(), timeout=5)
        raise
    return (proc.returncode or 0,
            out.decode(errors="replace"),
            err.decode(errors="replace"))


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

    async def aexecute(
        self,
        prompt: str,
        project_dir: Path,
        *,
        timeout: int = 300,
        env: Mapping[str, str] | None = None,
    ) -> RuntimeResult:
        """Run the prompt without blocking the caller's event loop."""
        raise NotImplementedError

    def execute(
        self,
        prompt: str,
        project_dir: Path,
        *,
        timeout: int = 300,
        env: Mapping[str, str] | None = None,
    ) -> RuntimeResult:
        """Synchronous wrapper, for callers that are not on an event loop.

        Refuses to run inside one rather than blocking it: this method is part
        of a published package's surface, so it stays, but the MCP server must
        await `aexecute`.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.aexecute(prompt, project_dir, timeout=timeout, env=env))
        raise RuntimeError(
            f"{type(self).__name__}.execute() was called from a running event "
            f"loop, where it would block every concurrent MCP call for up to "
            f"{timeout}s. Await aexecute() instead.")

    def _build_env(self, env: Mapping[str, str] | None) -> dict[str, str]:
        return dict(os.environ if env is None else env)


class ClaudeRuntime(AgentRuntime):
    name = "claude"
    executable = "claude"

    async def aexecute(self, prompt, project_dir, *, timeout=300, env=None) -> RuntimeResult:
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
        process_env = self._build_env(env)
        process_env["CLAUDE_CODE_EXPERIMENTAL_SKIP_INJECT"] = "1"
        code, out, err = await _run_bounded(
            command, timeout=timeout, env=process_env)
        if code:
            return RuntimeResult("", code, err[:2000])
        return RuntimeResult(_parse_claude_output(out))


class CodexRuntime(AgentRuntime):
    name = "codex"
    executable = "codex"

    async def aexecute(self, prompt, project_dir, *, timeout=300, env=None) -> RuntimeResult:
        process_env = self._build_env(env)
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
        code, out, err = await _run_bounded(
            command, timeout=timeout, env=process_env, stdin_text=prompt)
        if code:
            return RuntimeResult("", code, err[:2000])
        return RuntimeResult(_parse_codex_output(out))


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
