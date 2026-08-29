"""Worker agent-runtime adapters — abstract WHICH agent CLI a worker runs.

Parallel to ``execution_backend.py`` (which abstracts *how* a process is
spawned / torn down), this abstracts *what command* runs inside it: the
``claude`` CLI or the ``codex`` CLI. A worker's completion (process exit) and
its results (``git diff`` of the worktree) are already provider-agnostic in
worker.py, so once the command + env are right a Codex worker is a first-class
member of the same WorkerPool / oracle-gate / WorkerEnvelope pipeline as a
Claude worker — not a bolt-on special case.

Leaf module (import DAG): stdlib + ``agent_runtime.py`` + ``config.py`` only.
It MUST NOT import worker.py / session.py at module scope — those import this
module, and a top-level back-edge would create an import cycle.

Runtime adapters
----------------
* :class:`ClaudeProvider` (default) — reproduces byte-for-byte the historical
  ``claude -p "$(cat <task>)" --model <m> --dangerously-skip-permissions`` +
  ``--fallback-model`` + tool-subset + ``--mcp-config`` command worker.py built
  inline, and the ``claude -p --continue`` lint-reflection retry.
* :class:`CodexProvider` — runs ``codex exec`` headlessly:
  ``--dangerously-bypass-approvals-and-sandbox`` (the worktree is throwaway and
  the oracle gate still guards every merge), an optional ``-m`` when an explicit
  Codex model is requested, and — critically — ``< /dev/null`` so ``codex exec``
  does not block reading stdin to EOF even though the prompt is a positional arg.
  Codex has no ``--continue`` equivalent wired yet, so it retries fresh with the
  full task + context.

Selection
---------
The canonical ``agent_runtime`` setting (default ``"claude"``) or per-task
runtime selects an **agent runtime**, not an inference provider.
Unknown and empty values fail before command construction. They must never run
Claude accidentally with the wrong credentials, model, or billing account.

Phase-2 (documented, not yet wired): consume ``codex exec --json`` JSONL
(persist ``thread_id`` from ``thread.started``), enforce ``--output-schema`` on
the result + capture it (``-o``) into ``completion_summary``, and resume a thread
by id on retry instead of a fresh run.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import os
import tempfile
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Mapping, MutableMapping

from agent_runtime import normalize_agent_runtime
from config import (
    SONNET_MODEL,
    _MODEL_ALIASES,
    _build_tool_flags,
    _fallback_flag,
)
from execution_envelope import (
    CapabilitySet,
    CapabilityState,
    InvalidExecutionConfig,
    validate_model_id,
)
from provider_registry import DiscoveryFailure, NativeProfileResolver


_ALLOWED_EFFORTS: Final = frozenset({"low", "medium", "high", "xhigh", "max"})


def _structured_output_flags() -> str:
    """Ask the agent to report its own usage instead of guessing from its prose.

    `--verbose` is not optional: `--print` with `--output-format=stream-json`
    exits 1 with "requires --verbose", so omitting it would fail every spawn
    rather than degrade quietly. Verified against CLI 2.1.236.

    Reading the result back is agent_output.absorb_agent_result, which also
    projects the event stream to plain text, so every downstream prose consumer
    (failure context, TLDR, distillation, the observation contract) is
    unaffected by the format change.
    """
    from config import GLOBAL_SETTINGS  # lazy: keep this module a leaf

    if not GLOBAL_SETTINGS.get("worker_structured_output", True):
        return ""
    return " --output-format stream-json --verbose"


def _safe_effort(value: str | None) -> str | None:
    effort = str(value or "").strip().lower()
    return effort if effort in _ALLOWED_EFFORTS else None


@lru_cache(maxsize=None)
def _probe_runtime_version(executable: str) -> str | None:
    """Probe each installed runtime once per process.

    Envelope construction happens for every task, so repeated subprocess
    probes would otherwise add latency and make runtime availability racey
    within one orchestrator process.
    """

    probe_env = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR"}
    }
    try:
        with tempfile.TemporaryDirectory(prefix="clade-runtime-probe-") as probe_dir:
            result = subprocess.run(
                [executable, "--version"],
                text=True,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                cwd=probe_dir,
                env=probe_env,
                timeout=2,
                check=False,
            )
    except (OSError, subprocess.TimeoutExpired):
        return None
    version = result.stdout.strip() or result.stderr.strip()
    return version[:120] or None


# ─── WorkerProvider ABC ──────────────────────────────────────────────────────
class WorkerProvider(ABC):
    """Legacy-named strategy for one agent runtime's worker command."""

    #: Stable agent-runtime id matched against legacy config/task fields.
    name: str = "base"
    adapter_version: str = "1"

    @abstractmethod
    def resolve_model(self, requested: str | None) -> str | None:
        """Resolve the requested model for this provider.

        Returns the concrete model id to pass on the command line, or ``None``
        when the provider should fall back to its own configured default.
        """

    @abstractmethod
    def build_command(
        self,
        *,
        task_file: Path,
        requested_model: str | None,
        task_type: str | None,
        mcp_config: Path | None,
        effort: str | None = None,
        connection: Mapping[str, Any] | None = None,
    ) -> str:
        """Build the full shell command string for this worker."""

    def apply_connection_env(
        self,
        connection: Mapping[str, Any] | None,
        env: MutableMapping[str, str],
    ) -> None:
        """Apply a trusted connection to one worker process environment."""

    def build_continue_command(
        self, *, task_file: Path, requested_model: str | None, effort: str | None = None
    ) -> str | None:
        """A retry command that resumes prior CLI context, or None if unsupported."""
        return None

    def capabilities(self) -> CapabilitySet:
        """Capabilities implemented by this Clade runtime adapter."""

        return CapabilitySet()

    def runtime_version(self) -> str | None:
        """Best-effort CLI version; absence remains unknown."""

        executable = shutil.which(self.name)
        if not executable:
            return None
        return _probe_runtime_version(executable)

    def resolve_effort(
        self, requested: str | None, resolved_model: str | None
    ) -> tuple[str | None, str | None]:
        """Return (wire effort, degradation reason)."""

        effort = _safe_effort(requested)
        if requested and effort is None:
            return None, f"unsupported effort {requested!r}"
        return effort, None


# ─── ClaudeProvider (default) ─────────────────────────────────────────────────
class ClaudeProvider(WorkerProvider):
    """Default provider — byte-identical to worker.py's historical inline command."""

    name = "claude"

    def resolve_model(self, requested: str | None) -> str:
        model = _MODEL_ALIASES.get(requested, requested)
        return validate_model_id(model, allow_none=True) or SONNET_MODEL

    def capabilities(self) -> CapabilitySet:
        source = f"claude-code-adapter@{self.adapter_version}"
        states = {
            "tools": CapabilityState.SUPPORTED,
            "repository_read": CapabilityState.SUPPORTED,
            "repository_write": CapabilityState.SUPPORTED,
            "structured_events": CapabilityState.UNKNOWN,
            "native_resume": CapabilityState.SUPPORTED,
            "subagents": CapabilityState.SUPPORTED,
            "hooks": CapabilityState.SUPPORTED,
            "status_renderer": CapabilityState.SUPPORTED,
            "native_rate_limits": CapabilityState.CONDITIONAL,
            "image_input": CapabilityState.CONDITIONAL,
            "reasoning_control": CapabilityState.CONDITIONAL,
        }
        return CapabilitySet(states, {name: source for name in states})

    def resolve_effort(
        self, requested: str | None, resolved_model: str | None
    ) -> tuple[str | None, str | None]:
        effort, degradation = super().resolve_effort(requested, resolved_model)
        if effort and resolved_model == _MODEL_ALIASES["haiku"]:
            return None, "selected Claude Haiku model does not accept effort control"
        return effort, degradation

    def build_command(
        self,
        *,
        task_file: Path,
        requested_model: str | None,
        task_type: str | None,
        mcp_config: Path | None,
        effort: str | None = None,
        connection: Mapping[str, Any] | None = None,
    ) -> str:
        model = self.resolve_model(requested_model)
        cmd = (
            f'claude -p "$(cat {shlex.quote(str(task_file))})" '
            f"--model {shlex.quote(model)} --dangerously-skip-permissions"
        )
        cmd += _structured_output_flags()
        wire_effort, _ = self.resolve_effort(effort, model)
        if wire_effort:
            cmd += f" --effort {wire_effort}"
        # Native lossless overload failover, off unless worker_fallback_model is set.
        cmd += _fallback_flag(requested_model)
        # Tool subsets per task type (Stripe Blueprint pattern).
        tool_flags = _build_tool_flags(task_type)
        if tool_flags:
            cmd += tool_flags
        if mcp_config is not None and mcp_config.exists():
            cmd += f" --mcp-config {shlex.quote(str(mcp_config))}"
        return cmd

    def apply_connection_env(
        self,
        connection: Mapping[str, Any] | None,
        env: MutableMapping[str, str],
    ) -> None:
        discovery = connection.get("discovery") if connection else None
        if not isinstance(discovery, Mapping):
            return
        try:
            profile = NativeProfileResolver().resolve(discovery)
        except DiscoveryFailure as exc:
            raise InvalidExecutionConfig(
                f"Claude connection profile is unavailable: {exc.category}"
            ) from exc
        if profile.base_url:
            env["ANTHROPIC_BASE_URL"] = profile.base_url
        else:
            env.pop("ANTHROPIC_BASE_URL", None)
        if profile.api_key:
            env["ANTHROPIC_API_KEY"] = profile.api_key
        else:
            env.pop("ANTHROPIC_API_KEY", None)

    def build_continue_command(
        self, *, task_file: Path, requested_model: str | None, effort: str | None = None
    ) -> str:
        # AutoCodeRover pattern: --continue preserves agent context across retries;
        # the caller sends only the follow-up context as the task file.
        model = self.resolve_model(requested_model)
        cmd = (
            f'claude -p --continue "$(cat {shlex.quote(str(task_file))})"'
            f" --model {shlex.quote(model)} --dangerously-skip-permissions"
            f"{_fallback_flag(requested_model)}"
        )
        cmd += _structured_output_flags()
        wire_effort, _ = self.resolve_effort(effort, model)
        if wire_effort:
            cmd += f" --effort {wire_effort}"
        return cmd


# ─── CodexProvider ────────────────────────────────────────────────────────────
class CodexProvider(WorkerProvider):
    """Run a worker on the ``codex exec`` headless CLI as a first-class backend."""

    name = "codex"

    def resolve_model(self, requested: str | None) -> str | None:
        model = (requested or "").strip()
        # Preserve legacy behavior for Claude aliases while accepting every
        # other opaque model id (custom Responses gateways included).
        if not model or model in _MODEL_ALIASES:
            return None
        return validate_model_id(model)

    def capabilities(self) -> CapabilitySet:
        source = f"codex-adapter@{self.adapter_version}"
        states = {
            "tools": CapabilityState.SUPPORTED,
            "repository_read": CapabilityState.SUPPORTED,
            "repository_write": CapabilityState.SUPPORTED,
            "structured_events": CapabilityState.UNSUPPORTED,
            "native_resume": CapabilityState.UNSUPPORTED,
            "subagents": CapabilityState.CONDITIONAL,
            "hooks": CapabilityState.SUPPORTED,
            "status_renderer": CapabilityState.CONDITIONAL,
            "native_rate_limits": CapabilityState.CONDITIONAL,
            "image_input": CapabilityState.CONDITIONAL,
            "reasoning_control": CapabilityState.SUPPORTED,
        }
        return CapabilitySet(states, {name: source for name in states})

    def build_command(
        self,
        *,
        task_file: Path,
        requested_model: str | None,
        task_type: str | None,
        mcp_config: Path | None,
        effort: str | None = None,
        connection: Mapping[str, Any] | None = None,
    ) -> str:
        model = self.resolve_model(requested_model)
        parts = ["codex exec", "--dangerously-bypass-approvals-and-sandbox"]
        if model:
            parts.append(f"-m {shlex.quote(model)}")
        discovery = connection.get("discovery") if connection else None
        if isinstance(discovery, Mapping) and discovery.get("store") == "codex-config":
            profile = validate_model_id(discovery.get("profile"), allow_none=False)
            parts.append(f"-c {shlex.quote(f'model_provider=\"{profile}\"')}")
        effort = _safe_effort(effort)
        if effort:
            parts.append(f"-c {shlex.quote(f'model_reasoning_effort=\"{effort}\"')}")
        parts.append(f'"$(cat {shlex.quote(str(task_file))})"')
        # CRITICAL: codex exec blocks reading stdin to EOF even with a positional
        # prompt — close stdin so a headless worker never hangs until timeout.
        parts.append("< /dev/null")
        return " ".join(parts)


# ─── Runtime factory ──────────────────────────────────────────────────────────
_RUNTIMES: dict[str, type[WorkerProvider]] = {
    "claude": ClaudeProvider,
    "codex": CodexProvider,
}


def get_agent_runtime(name: str | None = None) -> WorkerProvider:
    """Resolve an agent-runtime adapter by name.

    ``name`` comes from the per-task ``agent_runtime`` value or canonical
    setting (read lazily when ``None``). Unsupported,
    missing, and empty configured values fail closed before a subprocess can
    start.
    """
    if name is None:
        from config import GLOBAL_SETTINGS  # lazy: keep this module a leaf

        name = GLOBAL_SETTINGS.get("agent_runtime")
    runtime = normalize_agent_runtime(name)
    return _RUNTIMES[runtime]()
