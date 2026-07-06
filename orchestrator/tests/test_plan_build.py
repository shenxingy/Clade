"""Tests for session.py's plan_build BUILD-phase plan-drift guard (Round-4 gap).

Bug: worker.py computed oracle_result/oracle_reason as in-memory Worker attrs
but never persisted them to the task's DB row; session.py:_run_plan_build marked
a plan checklist item "- [x]" the instant the worker's task hit ANY terminal
status — before checking whether the oracle gate had actually rejected (and
undone) the commit. A rejected/reverted commit still showed checked off.

Fix: worker.py:_persist_oracle_result() writes oracle_result/oracle_reason to
the DB the moment they're computed; _run_plan_build now reads that column and
refuses to mark the checklist item done when oracle_result == "rejected".
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


async def _run_one_iteration(tmp_path, monkeypatch, terminal_oracle_result):
    """1-item plan; mock worker_pool.start_worker to instantly resolve the
    spawned task to a terminal status + the given oracle_result; run exactly
    one BUILD-phase iteration (max_iterations=2 bounds it); return plan text."""
    import session as sess_mod

    monkeypatch.setitem(sess_mod.GLOBAL_SETTINGS, "github_issues_sync", False)
    monkeypatch.setitem(sess_mod.GLOBAL_SETTINGS, "auto_merge", False)
    # Every scenario here hits "all items resolved" (converged) on the same
    # pass, which fires a REAL `claude -p` subprocess via _suggest_next_goals
    # (60s timeout) as a fire-and-forget background task — mock both
    # notification hooks so the test doesn't pay a real subprocess spawn.
    monkeypatch.setattr(sess_mod, "_fire_notification", AsyncMock())
    monkeypatch.setattr(sess_mod, "_suggest_next_goals", AsyncMock())

    plan_path = tmp_path / "IMPLEMENTATION_PLAN.md"
    plan_path.write_text("# Plan\n\n- [ ] do the thing\n")

    s = sess_mod.ProjectSession(str(tmp_path))
    await s.task_queue.upsert_loop(
        status="running", plan_phase="build", context_dir=str(tmp_path),
        artifact_path=str(tmp_path / "artifact.md"),
        iteration=1, max_iterations=2, supervisor_model="sonnet",
    )

    async def _fake_start_worker(task, task_queue, project_dir, claude_dir):
        await task_queue.update(
            task["id"], status="done",
            oracle_result=terminal_oracle_result, oracle_reason="test",
        )
        return None

    monkeypatch.setattr(s.worker_pool, "start_worker", _fake_start_worker)

    await s._run_plan_build()
    return plan_path.read_text()


class TestPlanDriftGuard:
    async def test_oracle_rejected_item_not_marked_done(self, tmp_path, monkeypatch):
        text = await _run_one_iteration(tmp_path, monkeypatch, "rejected")
        assert "- [ ] do the thing" in text
        assert "- [x] do the thing" not in text

    async def test_oracle_approved_item_marked_done(self, tmp_path, monkeypatch):
        text = await _run_one_iteration(tmp_path, monkeypatch, "approved")
        assert "- [x] do the thing" in text

    async def test_oracle_unreviewed_item_still_marked_done(self, tmp_path, monkeypatch):
        # Fail-open parity: an infra-error 'unreviewed' commit DID survive
        # (worker.py:_run_oracle_gate's own fail-open semantics), so the plan
        # must not block on it either.
        text = await _run_one_iteration(tmp_path, monkeypatch, "unreviewed")
        assert "- [x] do the thing" in text

    async def test_no_oracle_result_still_marked_done(self, tmp_path, monkeypatch):
        # auto_oracle off entirely (oracle_result stays None/absent) — unaffected.
        text = await _run_one_iteration(tmp_path, monkeypatch, None)
        assert "- [x] do the thing" in text
