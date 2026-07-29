"""Worker status serialization kept outside the execution engine."""

from __future__ import annotations

from typing import Any

from status_snapshot import build_worker_status
from worker_utils import _truncate_output


def worker_to_dict(w: Any) -> dict[str, Any]:
    log_tail = ""
    if w._log_path and w._log_path.exists():
        try:
            text = w._log_path.read_text(errors="replace")
            log_tail = _truncate_output(text, max_lines=4, max_bytes=4096)
        except Exception:
            pass
    estimated_tokens = w._estimate_tokens()
    return {
        "id": w.id,
        "task_id": w.task_id,
        "description": w.description[:80],
        "model": w.model,
        "agent_runtime": w.agent_runtime,
        "effort": w.effort,
        "route_reason": w.route_reason,
        "execution_envelope": (
            w.execution_envelope.to_dict() if w.execution_envelope else None
        ),
        "status_snapshot": build_worker_status(w).to_dict(),
        "status": w.status,
        "pid": w.pid,
        "elapsed_s": w.elapsed_s,
        "last_commit": w.last_commit,
        "log_file": w.log_file,
        "verified": w.verified,
        "auto_committed": w.auto_committed,
        "auto_pushed": w.auto_pushed,
        "branch_name": w.branch_name,
        "pr_url": w.pr_url,
        "pr_merged": w.pr_merged,
        "log_tail": log_tail,
        "failure_context": w.failure_context,
        "failure_class": w.failure_class,
        "worktree_path": str(w._worktree_path) if w._worktree_path else None,
        "oracle_result": w.oracle_result,
        "oracle_reason": w.oracle_reason,
        "transition_reason": w.transition_reason,
        "completion_summary": w.completion_summary,
        "model_score": w.model_score,
        "estimated_tokens": estimated_tokens,
        "context_warning": estimated_tokens > 160000,
        "input_tokens": w._input_tokens,
        "output_tokens": w._output_tokens,
        "estimated_cost": w._estimated_cost,
        "loop_detected": w._loop_detector.is_looping,
        "loop_reason": w._loop_detector.reason,
    }
