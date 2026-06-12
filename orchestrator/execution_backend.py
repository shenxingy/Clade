"""
Execution backend adapter — abstracts *how* a worker's shell command is
spawned and torn down, so the execution engine can target different runtimes
without touching Worker logic.

Leaf module (import DAG): depends only on the stdlib plus a lazy, function-local
import of ``config.GLOBAL_SETTINGS`` inside the factory. It MUST NOT import
worker.py / session.py at module scope — those import this module, and a
top-level back-edge would create an import cycle.

Backends
--------
* ``LocalSubprocessBackend`` — the only real backend today. Reproduces the
  historical inline semantics worker.py used before the adapter existed:
  ``asyncio.create_subprocess_shell(cmd, …, preexec_fn=os.setsid)`` to detach
  the child into its own session / process group, and ``os.killpg(pgid, sig)``
  to signal that whole group. Killing the group (not just the immediate child)
  is essential — the claude CLI forks git, node, ripgrep, … and signalling only
  the direct child would orphan them.
* ``ClaudeNativeBackend`` — PLANNED, docstring-only stub for a future in-process
  Claude runtime. Selecting it raises ``NotImplementedError`` (fail loud rather
  than silently fall back).

Selection
---------
Driven by the ``execution_backend`` setting (``config.py:_SETTINGS_DEFAULTS``,
default ``"local"``). Call :func:`get_execution_backend` to resolve the
configured backend instance.
"""

from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from typing import Any


# ─── ExecutionBackend ABC ───────────────────────────────────────────────────
class ExecutionBackend(ABC):
    """Strategy for spawning and terminating a worker's process.

    Three primitives mirror the lifecycle the WorkerPool depends on:

    * :meth:`spawn`    — launch the shell command, return the asyncio process
    * :meth:`is_alive` — has the process exited yet?
    * :meth:`kill`     — send a signal to the process *group*

    Implementations MUST place the spawned process in its own session /
    process group so that :meth:`kill` can tear down the entire descendant
    tree. This is the invariant the local OS backend provides via ``setsid``.
    """

    #: Stable identifier matched against the ``execution_backend`` setting.
    name: str = "base"

    @abstractmethod
    async def spawn(
        self,
        shell_cmd: str,
        *,
        stdout: Any,
        stderr: Any,
        env: dict[str, str],
        cwd: str,
    ) -> asyncio.subprocess.Process:
        """Launch ``shell_cmd`` in a fresh process group; return the process."""

    @abstractmethod
    def is_alive(self, proc: asyncio.subprocess.Process | None) -> bool:
        """True iff ``proc`` was spawned and has not yet exited."""

    @abstractmethod
    def kill(self, pgid: int, sig: int) -> None:
        """Send signal ``sig`` to process group ``pgid``.

        A missing group (already reaped) is not an error and is swallowed.
        """


# ─── LocalSubprocessBackend (default) ───────────────────────────────────────
class LocalSubprocessBackend(ExecutionBackend):
    """Default backend: a local OS subprocess detached into its own session.

    Wraps the exact semantics worker.py used inline before this adapter:
    ``asyncio.create_subprocess_shell(shell_cmd, stdout=…, stderr=…,
    preexec_fn=os.setsid, env=…, cwd=…)`` to start a new process group, and
    ``os.killpg(pgid, sig)`` to signal that group. ``ProcessLookupError`` (the
    group reaped itself between the liveness check and the signal) is swallowed
    — matching the historical try/except around every ``killpg`` call.
    """

    name = "local"

    async def spawn(
        self,
        shell_cmd: str,
        *,
        stdout: Any,
        stderr: Any,
        env: dict[str, str],
        cwd: str,
    ) -> asyncio.subprocess.Process:
        return await asyncio.create_subprocess_shell(
            shell_cmd,
            stdout=stdout,
            stderr=stderr,
            preexec_fn=os.setsid,
            env=env,
            cwd=cwd,
        )

    def is_alive(self, proc: asyncio.subprocess.Process | None) -> bool:
        if proc is None:
            return False
        return proc.returncode is None

    def kill(self, pgid: int, sig: int) -> None:
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            pass


# ─── ClaudeNativeBackend (PLANNED — stub) ───────────────────────────────────
class ClaudeNativeBackend(ExecutionBackend):
    """PLANNED — not yet implemented. Docstring-only stub.

    Intended to run the agent against an in-process / SDK-driven Claude runtime
    rather than shelling out to the ``claude`` CLI. The motivation is to drop
    the per-task subprocess + worktree-shell overhead and to gain structured
    access to the turn stream (tool calls, token usage) without scraping a log
    file.

    Open design questions before this can be built:

    * How does "kill" map when there is no OS process group? (cooperative
      cancellation token vs. task abort).
    * How is per-task isolation (cwd, env, worktree) enforced in-process?
    * How do stdout/stderr log capture and the JSONL session tree get fed?

    Until those are resolved the methods deliberately raise so that selecting
    this backend fails loudly instead of silently no-op'ing. :func:`get_execution_backend`
    rejects ``"claude-native"`` for the same reason.
    """

    name = "claude-native"

    async def spawn(self, shell_cmd, *, stdout, stderr, env, cwd):  # noqa: D401
        """Reserved for the future in-process runtime — not implemented."""
        raise NotImplementedError("claude-native execution backend is not implemented yet")

    def is_alive(self, proc):  # noqa: D401
        """Reserved for the future in-process runtime — not implemented."""
        raise NotImplementedError("claude-native execution backend is not implemented yet")

    def kill(self, pgid, sig):  # noqa: D401
        """Reserved for the future in-process runtime — not implemented."""
        raise NotImplementedError("claude-native execution backend is not implemented yet")


# ─── Factory ────────────────────────────────────────────────────────────────
_BACKENDS: dict[str, type[ExecutionBackend]] = {
    "local": LocalSubprocessBackend,
}


def get_execution_backend(settings: dict | None = None) -> ExecutionBackend:
    """Resolve the configured :class:`ExecutionBackend`.

    Reads the ``execution_backend`` key from ``settings`` (defaults to
    ``config.GLOBAL_SETTINGS`` when ``None``). Unknown values fall back to
    ``"local"`` — a typo'd setting must not strand the worker pool. The reserved
    ``"claude-native"`` value raises :class:`NotImplementedError` because the
    stub backend has no real implementation yet.
    """
    if settings is None:
        from config import GLOBAL_SETTINGS  # lazy: keep this module a leaf

        settings = GLOBAL_SETTINGS
    name = settings.get("execution_backend") or "local"
    if name == "claude-native":
        raise NotImplementedError(
            "execution_backend='claude-native' is reserved for a future "
            "in-process runtime; only 'local' is implemented today."
        )
    backend_cls = _BACKENDS.get(name, LocalSubprocessBackend)
    return backend_cls()
