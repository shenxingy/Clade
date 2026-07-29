"""Pure, fail-closed policy helpers for verifier-aware cheap-to-strong routing."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


CHEAP_REASON = "verifier cascade cheap-first"
STRONG_SOURCE_PREFIX = "cascade:strong:"
LOW_RISK_TASK_TYPES = frozenset({"test", "tldr"})


@dataclass(frozen=True)
class VerifierContract:
    verifier_id: str
    command_digest: str
    deterministic: bool


@dataclass(frozen=True)
class CascadeDecision:
    stage: str | None
    reason: str
    signal: str | None = None


def load_verifier_contract(project_dir: Path | str | None) -> VerifierContract | None:
    """Read an explicit project verifier declaration without exposing its command."""

    if project_dir is None:
        return None
    path = Path(project_dir) / ".claude" / "orchestrator.json"
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    command = value.get("test_cmd") if isinstance(value, Mapping) else None
    if (
        not isinstance(command, str)
        or not command.strip()
        or value.get("test_cmd_deterministic") is not True
    ):
        return None
    verifier_id = value.get("test_cmd_id") or "project-test-cmd"
    if not isinstance(verifier_id, str) or not verifier_id.strip():
        return None
    digest = hashlib.sha256(command.encode()).hexdigest()
    return VerifierContract(
        verifier_id=verifier_id.strip(),
        command_digest=f"sha256:{digest}",
        deterministic=True,
    )


def decide(
    task: Mapping[str, Any],
    settings: Mapping[str, Any],
    verifier: VerifierContract | None,
) -> CascadeDecision:
    """Select no cascade, one cheap attempt, or an explicit strong fallback."""

    source_ref = str(task.get("source_ref") or "")
    if source_ref.startswith(STRONG_SOURCE_PREFIX):
        signal = source_ref.removeprefix(STRONG_SOURCE_PREFIX) or "unspecified"
        return CascadeDecision("strong", f"verifier cascade strong fallback: {signal}", signal)
    if not settings.get("verifier_cascade_enabled", False):
        return CascadeDecision(None, "verifier cascade disabled")
    if not settings.get("auto_model_routing", False):
        return CascadeDecision(None, "automatic model routing disabled")
    if verifier is None or not verifier.deterministic:
        return CascadeDecision(None, "deterministic verifier not declared")
    if bool(task.get("is_critical_path")):
        return CascadeDecision(None, "critical-path tasks require strong routing")
    score = task.get("score")
    try:
        min_score = int(settings.get("verifier_cascade_min_score", 80) or 80)
        max_files = int(settings.get("verifier_cascade_max_files", 8) or 0)
    except (TypeError, ValueError):
        return CascadeDecision(None, "invalid verifier cascade bounds")
    if min_score < 0 or max_files < 1:
        return CascadeDecision(None, "invalid verifier cascade bounds")
    if not isinstance(score, int | float) or isinstance(score, bool) or score < min_score:
        return CascadeDecision(None, "readiness below cascade threshold")
    allowed_types = settings.get("verifier_cascade_task_types") or LOW_RISK_TASK_TYPES
    if not isinstance(allowed_types, (list, tuple, set, frozenset)):
        return CascadeDecision(None, "invalid verifier cascade task types")
    task_type = str(task.get("task_type") or "").lower()
    if task_type not in {str(item).lower() for item in allowed_types}:
        return CascadeDecision(None, f"task type {task_type or 'unknown'} is not low-risk")
    own_files = task.get("own_files")
    if not isinstance(own_files, list) or not own_files:
        return CascadeDecision(None, "bounded own_files are required")
    return CascadeDecision(
        "cheap",
        f"{CHEAP_REASON}: {verifier.verifier_id}@{verifier.command_digest}",
    )


def is_cheap_route(route_reason: Any) -> bool:
    return CHEAP_REASON in str(route_reason or "")


def is_strong_route(route_reason: Any) -> bool:
    return "verifier cascade strong fallback:" in str(route_reason or "")


def route_stage(route_reason: Any) -> str | None:
    reason = str(route_reason or "")
    if CHEAP_REASON in reason:
        return "cheap"
    if is_strong_route(reason):
        return "strong"
    return None


def escalation_source(worker: Any, signal: str) -> str | None:
    if not is_cheap_route(getattr(worker, "route_reason", None)):
        return None
    return f"{STRONG_SOURCE_PREFIX}{signal}"


def retry_fields(
    worker: Any,
    task: Mapping[str, Any],
    signal: str,
) -> dict[str, Any]:
    """Preserve the queued execution contract on a child retry."""

    return {
        "own_files": list(getattr(worker, "own_files", []) or []),
        "forbidden_files": list(getattr(worker, "forbidden_files", []) or []),
        "is_critical_path": bool(task.get("is_critical_path")),
        "agent_runtime": getattr(worker, "agent_runtime", None),
        "effort": getattr(worker, "effort", None),
        "source_ref": escalation_source(worker, signal) or task.get("source_ref"),
        "parent_task_id": worker.task_id,
        "task_type": task.get("task_type", "AUTO"),
        "phase": task.get("phase", "implement"),
        "connection": task.get("connection"),
        "execution_profile": task.get("execution_profile"),
        "execution_requirements": task.get("execution_requirements"),
    }


def max_changed_files(settings: Mapping[str, Any]) -> int:
    try:
        return max(1, int(settings.get("verifier_cascade_max_files", 8) or 8))
    except (TypeError, ValueError):
        return 8


def test_requeue_signal(worker: Any) -> str:
    reason = str(getattr(worker, "_test_requeue_reason", "") or "").lower()
    return "no_diff" if "no diff" in reason or "nothing was changed" in reason else "test_failure"


def scope_result(
    result: tuple[bool, str],
    *,
    route_reason: Any,
    changed_files: list[str],
    max_files: int,
) -> tuple[bool, str]:
    """Promote a bounded-file overflow to the existing ownership hard gate."""

    ok, reason = result
    if not ok or not is_cheap_route(route_reason):
        return ok, reason
    if max_files > 0 and len(changed_files) > max_files:
        return (
            False,
            f"verifier cascade scope expansion: {len(changed_files)} changed files "
            f"exceeds limit {max_files}",
        )
    return True, ""


def verifier_status(worker: Any) -> str:
    if getattr(worker, "_ownership_violation", False):
        return "scope_risk_expansion"
    reason = str(getattr(worker, "_test_requeue_reason", "") or "").lower()
    if "no diff" in reason or "nothing was changed" in reason:
        return "no_diff"
    if getattr(worker, "_test_requeue", False) or "tests failed" in reason:
        return "failed"
    if getattr(worker, "judge_agreement", None) in {"oracle-lenient", "oracle-strict"}:
        return "disagreement"
    if getattr(worker, "oracle_result", None) == "unreviewed":
        return "unreliable"
    if bool(getattr(worker, "verified", False)):
        return "passed"
    return "failed"


def escalation_signal(worker: Any) -> str | None:
    if not is_cheap_route(getattr(worker, "route_reason", None)):
        return None
    status = verifier_status(worker)
    return {
        "no_diff": "no_diff",
        "failed": "test_failure",
        "disagreement": "verifier_disagreement",
        "unreliable": "unreliable_verifier",
        "scope_risk_expansion": "scope_risk_expansion",
    }.get(status)


async def handle_unreliable(worker: Any) -> bool:
    """Fail closed and prepare one strong fallback for a cheap unreviewed result."""

    if not is_cheap_route(getattr(worker, "route_reason", None)):
        return True
    await worker._undo_commit()
    worker.auto_committed = False
    worker._oracle_requeue = True
    worker._oracle_requeue_reason = "Cheap verifier/oracle was unreliable"
    worker._cascade_escalation_signal = "unreliable_verifier"
    return False
