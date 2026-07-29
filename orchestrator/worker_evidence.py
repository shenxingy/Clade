"""Project worker lifecycle state into persisted EvidenceBundle attempts."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Mapping

from worker_envelope import build_from_worker


logger = logging.getLogger(__name__)


async def _git(project_dir: Path, *args: str) -> str | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(project_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode == 0:
            return stdout.decode(errors="replace").strip() or None
    except (OSError, asyncio.TimeoutError):
        return None
    return None


async def begin_task_evidence(
    task: Mapping[str, Any],
    task_queue: Any,
    project_dir: Path,
) -> dict[str, Any] | None:
    """Create one attempt identity before runtime/capability preflight."""

    create = getattr(task_queue, "create_evidence_attempt", None)
    if create is None:
        return None
    base_sha = await _git(project_dir, "rev-parse", "HEAD")
    return await create(
        str(task["id"]),
        evidence={
            "task": {
                "type": task.get("task_type"),
                "phase": task.get("phase"),
                "source_ref": task.get("source_ref"),
            },
            "routing": {
                "requested_runtime": task.get("agent_runtime") or task.get("provider"),
                "requested_connection": task.get("connection"),
                "requested_model": task.get("model"),
                "requested_effort": task.get("effort"),
                "profile": task.get("execution_profile"),
                "requirements": task.get("execution_requirements") or {},
            },
            "git": {"base_sha": base_sha},
            "timing": {"attempt_created_at": time.time()},
        },
    )


async def fail_preflight_evidence(
    task_queue: Any,
    attempt: Mapping[str, Any] | None,
    error: Exception,
) -> None:
    """Close an attempt when runtime resolution fails before a Worker exists."""

    if not attempt or not hasattr(task_queue, "append_evidence_bundle"):
        return
    try:
        bundle = await task_queue.append_evidence_bundle(
            attempt["attempt_id"],
            lifecycle_state="failed",
            evidence={
                "failure": {
                    "stage": "preflight",
                    "type": type(error).__name__,
                    "reason": str(error),
                },
                "timing": {"finished_at": time.time()},
            },
        )
        if hasattr(task_queue, "create_eval_candidate"):
            await task_queue.create_eval_candidate(
                attempt["attempt_id"],
                trigger="incident_failure",
                diff={"stage": "preflight", "type": type(error).__name__},
                payload={"reason": str(error)},
                source_attempt_revision=bundle["revision"],
                source_evidence_digest=bundle["digest"],
            )
    except Exception:
        logger.exception("failed to close preflight evidence attempt")


async def append_worker_evidence(worker: Any, lifecycle_state: str) -> None:
    """Append a non-terminal running/verifying snapshot if evidence is enabled."""

    task_queue = getattr(worker, "_task_queue", None)
    attempt_id = getattr(worker, "evidence_attempt_id", None)
    if not task_queue or not attempt_id:
        return
    evidence: dict[str, Any] = {
        "worker": {
            "id": getattr(worker, "id", None),
            "status": getattr(worker, "status", None),
            "transition_reason": getattr(worker, "transition_reason", None),
        },
        "timing": {
            "started_at": getattr(worker, "started_at", None),
            "elapsed_s": getattr(worker, "elapsed_s", None),
        },
    }
    execution = getattr(worker, "execution_envelope", None)
    if execution is not None:
        evidence["execution"] = execution.to_dict()
    try:
        await task_queue.append_evidence_bundle(
            attempt_id,
            lifecycle_state=lifecycle_state,
            evidence=evidence,
        )
    except Exception:
        logger.exception("failed to append %s worker evidence", lifecycle_state)


async def start_worker_with_evidence(worker: Any, task_queue: Any) -> None:
    """Start a worker and close its created attempt if spawning fails."""

    try:
        await worker.start(task_queue=task_queue)
    except Exception as exc:
        worker.status = "failed"
        worker.failure_context = str(exc)
        attempt_id = getattr(worker, "evidence_attempt_id", None)
        if attempt_id:
            try:
                bundle = await task_queue.append_evidence_bundle(
                    attempt_id,
                    lifecycle_state="failed",
                    evidence={
                        "failure": {
                            "stage": "spawn",
                            "type": type(exc).__name__,
                            "reason": str(exc),
                        },
                        "timing": {"finished_at": time.time()},
                    },
                )
                if hasattr(task_queue, "create_eval_candidate"):
                    await task_queue.create_eval_candidate(
                        attempt_id,
                        trigger="incident_failure",
                        diff={"stage": "spawn", "type": type(exc).__name__},
                        payload={"reason": str(exc)},
                        source_attempt_revision=bundle["revision"],
                        source_evidence_digest=bundle["digest"],
                    )
            except Exception:
                logger.exception("failed to close spawn evidence attempt")
        raise


async def append_worker_terminal_evidence(worker: Any) -> None:
    """Persist terminal verification, artifact, cost, and delivery evidence."""

    task_queue = getattr(worker, "_task_queue", None)
    attempt_id = getattr(worker, "evidence_attempt_id", None)
    if not task_queue or not attempt_id:
        return
    project_dir = Path(getattr(worker, "_project_dir"))
    head_sha = await _git(project_dir, "rev-parse", "HEAD")
    base_sha = getattr(worker, "evidence_base_sha", None)
    eval_diff = getattr(worker, "eval_diff", None)
    changed_files: list[str] = []
    if base_sha and head_sha and base_sha != head_sha:
        changed = await _git(project_dir, "diff", "--name-only", f"{base_sha}..{head_sha}")
        changed_files = changed.splitlines() if changed else []
        if eval_diff is None:
            eval_diff = await _git(project_dir, "diff", f"{base_sha}..{head_sha}")
    setattr(worker, "changed_files", changed_files)

    if getattr(worker, "auto_committed", False):
        lifecycle_state = (
            "delivered" if getattr(worker, "auto_pushed", False) else "delivery_pending"
        )
    elif getattr(worker, "status", None) == "blocked":
        lifecycle_state = "cancelled"
    else:
        lifecycle_state = "failed"

    optional_artifacts = {
        name: getattr(worker, name, None)
        for name in ("screenshots", "video", "artifact_paths")
        if getattr(worker, name, None)
    }
    envelope = build_from_worker(worker)
    bundle = None
    try:
        bundle = await task_queue.append_evidence_bundle(
            attempt_id,
            lifecycle_state=lifecycle_state,
            evidence={
                "worker_envelope": envelope.to_dict(),
                "timing": {
                    "started_at": getattr(worker, "started_at", None),
                    "finished_at": getattr(worker, "_finished_at", None) or time.time(),
                    "elapsed_s": getattr(worker, "elapsed_s", None),
                },
                "git": {
                    "base_sha": base_sha,
                    "head_sha": head_sha,
                    "commit": getattr(worker, "last_commit", None),
                },
                "verification": {
                    "judge_verified": bool(getattr(worker, "verified", False)),
                    "tests": getattr(worker, "test_evidence", ""),
                    "oracle_verdict": getattr(worker, "oracle_result", None),
                    "oracle_reason": getattr(worker, "oracle_reason", None),
                    "judge_agreement": getattr(worker, "judge_agreement", None),
                },
                "usage": {
                    "input_tokens": getattr(worker, "_input_tokens", 0),
                    "output_tokens": getattr(worker, "_output_tokens", 0),
                    "estimated_cost": getattr(worker, "_estimated_cost", 0.0),
                },
                "artifacts": {
                    "changed_files": changed_files,
                    **optional_artifacts,
                },
                "delivery_candidate": {
                    "eligible": bool(getattr(worker, "auto_committed", False)),
                    "branch": getattr(worker, "branch_name", None),
                    "pushed": bool(getattr(worker, "auto_pushed", False)),
                    "head_sha": head_sha,
                    "pr_url": getattr(worker, "pr_url", None),
                },
            },
        )
    except Exception:
        logger.exception("failed to append terminal worker evidence")
        return

    triggers: list[str] = []
    oracle_result = getattr(worker, "oracle_result", None)
    agreement = getattr(worker, "judge_agreement", None)
    if oracle_result == "rejected":
        triggers.append("oracle_rejected")
    elif oracle_result == "unreviewed":
        triggers.append("oracle_unreviewed")
    if agreement in {"oracle-lenient", "oracle-strict"}:
        triggers.append("oracle_disagreement")
    if lifecycle_state == "failed" and not triggers:
        triggers.append("incident_failure")
    for trigger in triggers:
        try:
            await task_queue.create_eval_candidate(
                attempt_id,
                trigger=trigger,
                diff=eval_diff or "",
                payload={
                    "failure": getattr(worker, "failure_context", None),
                    "verification": bundle["evidence"].get("verification", {}),
                    "changed_files": changed_files,
                },
                source_attempt_revision=bundle["revision"],
                source_evidence_digest=bundle["digest"],
            )
        except Exception:
            logger.exception("failed to create %s eval candidate", trigger)
