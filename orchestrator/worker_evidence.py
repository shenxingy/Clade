"""Project worker lifecycle state into persisted EvidenceBundle attempts."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Mapping

from attempt_telemetry import (
    failure_patch,
    running_patch,
    terminal_patch,
    verifying_patch,
)
from worker_envelope import build_from_worker
from worker_utils import git_control_surface, git_control_surface_changes


logger = logging.getLogger(__name__)


async def _latest_attempt(task_queue: Any, task_id: str | None) -> dict | None:
    if not task_id or not hasattr(task_queue, "list_evidence_attempts"):
        return None
    attempts = await task_queue.list_evidence_attempts(task_id)
    return attempts[-1] if attempts else None


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
    parent = await _latest_attempt(task_queue, str(task["id"]))
    if parent is None:
        parent = await _latest_attempt(task_queue, task.get("parent_task_id"))
    return await create(
        str(task["id"]),
        evidence={
            "attempt": {
                "parent_attempt_id": parent["attempt_id"] if parent else None,
            },
            "task": {
                "type": task.get("task_type"),
                "phase": task.get("phase"),
                "source_ref": task.get("source_ref"),
            },
            "routing": {
                "requested_runtime": task.get("agent_runtime"),
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
        finished_at = time.time()
        bundle = await task_queue.append_evidence_bundle(
            attempt["attempt_id"],
            lifecycle_state="failed",
            evidence={
                "failure": {
                    "stage": "preflight",
                    "type": type(error).__name__,
                    "reason": str(error),
                },
                "timing": {"finished_at": finished_at},
                **failure_patch(
                    attempt, stage="preflight", observed_at=finished_at
                ),
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


async def append_worker_evidence(
    worker: Any, lifecycle_state: str, phase: str | None = None, **facts: Any
) -> None:
    """Append a non-terminal running/verifying snapshot if evidence is enabled.

    `phase` marks WHICH step of verification this revision records. Without it,
    tests, the oracle verdict and the push all landed in the single terminal
    append at the bottom of this module, so a crash between "tests passed" and
    "oracle returned" lost both — the bundle could say an attempt failed and
    hand back a digest-chained final diff, but never when it went wrong.

    Each phase is its own revision in the existing digest chain, so the
    timeline is answerable after the fact without a new lifecycle state or a
    new table.
    """

    task_queue = getattr(worker, "_task_queue", None)
    attempt_id = getattr(worker, "evidence_attempt_id", None)
    if not task_queue or not attempt_id:
        return
    observed_at = time.time()
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
    if phase is not None:
        evidence["phase"] = {"name": phase, "observed_at": observed_at, **facts}
    try:
        latest = await task_queue.get_evidence_bundle(attempt_id)
    except Exception:
        logger.exception("failed to read %s worker evidence", lifecycle_state)
        latest = None
    if latest is not None:
        if lifecycle_state == "running":
            evidence.update(running_patch(latest, worker, observed_at=observed_at))
        elif lifecycle_state == "verifying":
            evidence.update(verifying_patch(latest, observed_at=observed_at))
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


async def _git_common_dir(project_dir: Path) -> Path | None:
    """The SHARED .git a worktree writes through, resolved absolutely."""
    out = await _git(project_dir, "rev-parse", "--git-common-dir")
    if not out:
        return None
    path = Path(out)
    return path if path.is_absolute() else (Path(project_dir) / path).resolve()


async def _snapshot_git_surface(worker: Any) -> None:
    """Record the parent repo's hooks + config before the agent runs."""
    from config import GLOBAL_SETTINGS

    worker._git_surface_before = {}
    if not GLOBAL_SETTINGS.get("worker_git_surface_guard", True):
        return
    try:
        common = await _git_common_dir(Path(worker._project_dir))
        worker._git_surface_common_dir = common
        worker._git_surface_before = git_control_surface(common)
    except Exception:
        logger.exception("failed to snapshot the git control surface")


async def _assert_git_surface_untouched(worker: Any) -> list[str]:
    """Changes the agent made to the parent repo's hooks or config.

    A worktree bounds the working tree, not `.git`. An agent can write
    `<main>/.git/hooks/pre-commit` from inside its worktree and that hook then
    runs for the OPERATOR's next commit in the main checkout — reproduced, not
    theorised. Workers spawn with permissions bypassed, so this is the control.

    Detection rather than prevention because a worker must be able to write
    `.git` to commit at all; bounding that needs an OS sandbox. The digest is
    exact: `worktree add`, a commit inside the worktree, and `worktree remove`
    all leave it unchanged.
    """
    before = getattr(worker, "_git_surface_before", None)
    if not before:
        return []
    try:
        common = getattr(worker, "_git_surface_common_dir", None) or await _git_common_dir(
            Path(worker._original_project_dir)
        )
        return git_control_surface_changes(before, git_control_surface(common))
    except Exception:
        logger.exception("failed to re-read the git control surface")
        return []


async def verify_worker_with_evidence(worker: Any) -> bool:
    """Run worker verification while capturing its exact phase boundaries."""

    tampered = await _assert_git_surface_untouched(worker)
    if tampered:
        worker.status = "failed"
        worker.transition_reason = "git_control_surface_modified"
        worker.failure_context = (
            "Refusing to verify: the agent modified the parent repository's git "
            "control surface, which executes on the operator's machine — "
            + "; ".join(tampered[:5])
        )
        logger.error("Worker %s modified the git control surface: %s", worker.id, tampered)
        await append_worker_evidence(worker, "verifying")
        worker._evidence_verify_finished_at = time.time()
        return False

    await append_worker_evidence(worker, "verifying")
    try:
        return await worker.verify_and_commit()
    finally:
        worker._evidence_verify_finished_at = time.time()


async def start_worker_with_evidence(worker: Any, task_queue: Any) -> None:
    """Start a worker and close its created attempt if spawning fails."""

    await _snapshot_git_surface(worker)
    try:
        await worker.start(task_queue=task_queue)
    except Exception as exc:
        worker.status = "failed"
        worker.failure_context = str(exc)
        attempt_id = getattr(worker, "evidence_attempt_id", None)
        if attempt_id:
            try:
                finished_at = time.time()
                attempt = await task_queue.get_evidence_bundle(attempt_id)
                bundle = await task_queue.append_evidence_bundle(
                    attempt_id,
                    lifecycle_state="failed",
                    evidence={
                        "failure": {
                            "stage": "spawn",
                            "type": type(exc).__name__,
                            "reason": str(exc),
                        },
                        "timing": {"finished_at": finished_at},
                        **(
                            failure_patch(
                                attempt, stage="spawn", observed_at=finished_at
                            )
                            if attempt
                            else {}
                        ),
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


async def _checkpoint_summary(worker: Any) -> dict | None:
    """How many per-tool-call checkpoints this attempt recorded, and the last SHA.

    Read before `_cleanup_worktree` deletes the shadow repo (worker.py:752
    appends terminal evidence, :759 cleans up). Without this the checkpoints
    would exist only for the life of the run and leave no trace in the chain.
    """
    path = getattr(worker, "_shadow_repo_path", None)
    shadow = path() if callable(path) else None
    if shadow is None or not Path(shadow).exists():
        return None
    count = await _git(Path(shadow).parent, "--git-dir", str(shadow), "rev-list", "--count", "HEAD")
    head = await _git(Path(shadow).parent, "--git-dir", str(shadow), "rev-parse", "HEAD")
    if not count:
        return None
    return {"count": int(count), "head": head, "repo": str(shadow)}


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
        finished_at = (
            getattr(worker, "_evidence_verify_finished_at", None) or time.time()
        )
        latest = await task_queue.get_evidence_bundle(attempt_id)
        bundle = await task_queue.append_evidence_bundle(
            attempt_id,
            lifecycle_state=lifecycle_state,
            evidence={
                "worker_envelope": envelope.to_dict(),
                "timing": {
                    "started_at": getattr(worker, "started_at", None),
                    "finished_at": getattr(worker, "_finished_at", None) or finished_at,
                    "elapsed_s": getattr(worker, "elapsed_s", None),
                },
                **(
                    terminal_patch(
                        latest,
                        worker,
                        lifecycle_state=lifecycle_state,
                        observed_at=finished_at,
                    )
                    if latest
                    else {}
                ),
                "git": {
                    "base_sha": base_sha,
                    "head_sha": head_sha,
                    "commit": getattr(worker, "last_commit", None),
                },
                "checkpoints": await _checkpoint_summary(worker),
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
