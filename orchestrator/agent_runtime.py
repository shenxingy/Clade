"""Agent-runtime identity and validation.

An agent runtime owns the coding-agent loop (for example Claude Code or
Codex).  It is deliberately distinct from an inference provider such as
Anthropic, OpenAI, MiniMax, or Moonshot.

This leaf module is the single source of truth for runtime identifiers so
routing, settings validation, and command construction cannot disagree or
silently select a different runtime.
"""

from __future__ import annotations

from typing import Any, Final


SUPPORTED_AGENT_RUNTIMES: Final = frozenset({"claude", "codex"})
_NO_DEFAULT: Final = object()


class AgentRuntimeSelectionError(ValueError):
    """Raised when an agent runtime is missing, empty, or unsupported."""

    def __init__(self, value: Any):
        if value is None:
            display = "<missing>"
        elif not str(value).strip():
            display = "<empty>"
        else:
            display = repr(str(value).strip())
        supported = ", ".join(sorted(SUPPORTED_AGENT_RUNTIMES))
        super().__init__(
            f"Unsupported agent runtime {display}. Supported runtimes: {supported}."
        )
        self.value = value


def normalize_agent_runtime(value: Any, default: Any = _NO_DEFAULT) -> str:
    """Return a canonical runtime id, or fail closed.

    ``None`` means "not specified" only when the caller provides ``default``.
    Empty strings and unknown values never fall back: doing so could execute
    the task with the wrong CLI, credentials, model, and billing account.
    """

    selected = default if value is None and default is not _NO_DEFAULT else value
    candidate = str(selected or "").strip().lower()
    if candidate not in SUPPORTED_AGENT_RUNTIMES:
        raise AgentRuntimeSelectionError(selected)
    return candidate
