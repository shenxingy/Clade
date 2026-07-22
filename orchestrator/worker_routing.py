"""Pure provider-aware worker routing.

This module decides the execution envelope before a worker reads the repository:
provider, model, effort, and a compact audit reason.  It deliberately does not
decide whether an interactive lead should delegate; native Claude/Codex agents
own that lifecycle and Clade only routes tasks that have already been queued.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from config import _MODEL_ALIASES


VALID_PROVIDERS = frozenset({"claude", "codex"})
VALID_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
_CODEX_MODEL_PREFIXES = ("gpt-", "gpt5", "o1", "o3", "o4", "codex")


@dataclass(frozen=True)
class WorkerRoute:
    provider: str
    model: str
    effort: str | None
    reason: str
    needs_clarification: bool = False


def normalize_provider(value: Any, default: str = "claude") -> str:
    candidate = str(value or "").strip().lower()
    if candidate in VALID_PROVIDERS:
        return candidate
    fallback = str(default or "claude").strip().lower()
    return fallback if fallback in VALID_PROVIDERS else "claude"


def normalize_effort(value: Any) -> str | None:
    candidate = str(value or "").strip().lower()
    return candidate if candidate in VALID_EFFORTS else None


def resolve_worker_route(task: Mapping[str, Any], settings: Mapping[str, Any]) -> WorkerRoute:
    """Resolve a task to a safe provider/model/effort envelope.

    Explicit task effort wins unless a safety upgrade is required. Automatic
    routing is intentionally conservative: critical or low-readiness work gets
    the strong tier at high effort; only high-readiness work gets the cheap
    tier. A middle-score or unscored task keeps the configured/default model.
    """
    provider = normalize_provider(task.get("provider"), settings.get("worker_provider", "claude"))
    requested_model = str(task.get("model") or settings.get("default_model") or "sonnet").strip()
    effort = normalize_effort(task.get("effort"))
    score = task.get("score")
    critical = bool(task.get("is_critical_path"))
    auto = bool(settings.get("auto_model_routing", False))
    needs_clarification = score is not None and score < 50
    reason = "task override" if task.get("provider") or task.get("model") or effort else "configured default"

    if provider == "claude":
        model = next(
            (alias for alias, concrete in _MODEL_ALIASES.items() if concrete == requested_model),
            requested_model,
        )
        if auto and (score is not None or critical):
            if score is not None and score >= 80:
                model = "haiku"
                reason = "high readiness: cheap Claude tier"
            elif score is not None and score < 50:
                model = "sonnet"
                effort = "high"
                reason = "low readiness: strong Claude tier"
            if critical:
                model = {"haiku": "sonnet", "sonnet": "opus"}.get(model, model)
                effort = "high"
                reason += "; critical-path upgrade"
        model = _MODEL_ALIASES.get(model, model)
    else:
        model = requested_model
        if auto and (score is not None or critical):
            if critical or (score is not None and score < 50):
                model = str(settings.get("codex_strong_model") or "gpt-5.6-sol")
                effort = "high"
                reason = "critical/low readiness: strong Codex tier"
            elif score is not None and score >= 80:
                model = str(settings.get("codex_cheap_model") or "gpt-5.6-terra")
                effort = effort or "low"
                reason = "high readiness: cheap Codex tier"

    routing_map = settings.get("task_type_model_routing") or {}
    task_type = str(task.get("task_type") or "AUTO").lower()
    if isinstance(routing_map, Mapping) and task_type in routing_map:
        candidate = str(routing_map[task_type])
        if critical and auto:
            reason += f"; ignored task-type override on critical task ({task_type})"
        elif provider == "codex" and not candidate.lower().startswith(_CODEX_MODEL_PREFIXES):
            reason += f"; ignored incompatible Codex task-type override ({task_type})"
        else:
            model = _MODEL_ALIASES.get(candidate, candidate) if provider == "claude" else candidate
            reason += f"; task-type override ({task_type})"

    # Claude Haiku does not support the effort control. Apply this after every
    # model override so the stored audit envelope matches the command actually run.
    if provider == "claude" and model == _MODEL_ALIASES["haiku"]:
        effort = None

    return WorkerRoute(
        provider=provider,
        model=model,
        effort=effort,
        reason=reason,
        needs_clarification=needs_clarification,
    )
