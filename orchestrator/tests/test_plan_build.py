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


class TestPlanItemRejectStreakEscalation:
    """Round-2 adversarial-review finding (regression, MEDIUM): exempting loop/
    plan tasks from worker.py's handle_oracle_requeue also silently dropped the
    reject-round-cap escalation for them — and since each BUILD iteration
    regenerates a fresh task description with no marker to count, that
    escalation was actually UNREACHABLE for this task class, not merely
    skipped once. session.py now tracks consecutive rejections of the
    front-of-plan item itself (plan_item_reject_streak) and escalates via the
    same _escalate_oracle_reject_plateau at the same configured cap.
    """

    async def test_escalates_at_the_configured_cap_then_exhausts(self, tmp_path, monkeypatch):
        import session as sess_mod

        monkeypatch.setitem(sess_mod.GLOBAL_SETTINGS, "github_issues_sync", False)
        monkeypatch.setitem(sess_mod.GLOBAL_SETTINGS, "auto_merge", False)
        monkeypatch.setitem(sess_mod.GLOBAL_SETTINGS, "oracle_max_reject_rounds", 3)
        monkeypatch.setattr(sess_mod, "_fire_notification", AsyncMock())
        monkeypatch.setattr(sess_mod, "_suggest_next_goals", AsyncMock())

        escalated = []

        async def fake_escalate(project_dir, claude_dir, webhook, task_id, streak):
            escalated.append((task_id, streak))

        monkeypatch.setattr(sess_mod, "_escalate_oracle_reject_plateau", fake_escalate)

        plan_path = tmp_path / "IMPLEMENTATION_PLAN.md"
        plan_path.write_text("# Plan\n\n- [ ] genuinely stuck item\n")

        s = sess_mod.ProjectSession(str(tmp_path))
        # max_iterations == oracle_max_reject_rounds: escalation fires on the
        # LAST real attempt, then the very next check exhausts — no infinite loop.
        await s.task_queue.upsert_loop(
            status="running", plan_phase="build", context_dir=str(tmp_path),
            artifact_path=str(tmp_path / "artifact.md"),
            iteration=1, max_iterations=3, supervisor_model="sonnet",
        )

        async def _always_rejected(task, task_queue, project_dir, claude_dir):
            await task_queue.update(task["id"], status="done", oracle_result="rejected", oracle_reason="no")

        monkeypatch.setattr(s.worker_pool, "start_worker", _always_rejected)

        await s._run_plan_build()

        assert len(escalated) == 1
        assert escalated[0][1] == 3  # streak reached the configured cap

        loop_state = await s.task_queue.get_loop()
        assert loop_state["status"] == "exhausted"
        assert loop_state["plan_item_reject_streak"] == 0  # reset after escalating

        # the item stays unmarked — none of this was a real completion
        assert "- [ ] genuinely stuck item" in plan_path.read_text()

    async def test_streak_resets_on_success_after_rejections(self, tmp_path, monkeypatch):
        import session as sess_mod

        monkeypatch.setitem(sess_mod.GLOBAL_SETTINGS, "github_issues_sync", False)
        monkeypatch.setitem(sess_mod.GLOBAL_SETTINGS, "auto_merge", False)
        monkeypatch.setitem(sess_mod.GLOBAL_SETTINGS, "oracle_max_reject_rounds", 5)
        monkeypatch.setattr(sess_mod, "_fire_notification", AsyncMock())
        monkeypatch.setattr(sess_mod, "_suggest_next_goals", AsyncMock())

        escalated = []

        async def fake_escalate(*a, **k):
            escalated.append(a)

        monkeypatch.setattr(sess_mod, "_escalate_oracle_reject_plateau", fake_escalate)

        plan_path = tmp_path / "IMPLEMENTATION_PLAN.md"
        plan_path.write_text("# Plan\n\n- [ ] flaky then fixed\n")

        s = sess_mod.ProjectSession(str(tmp_path))
        # This is the FIRST upsert_loop call for this session (no prior loop
        # row), so seeding plan_item_reject_streak here exercises upsert_loop's
        # INSERT branch, not just UPDATE — a real bug once dropped exactly this
        # kwarg on that branch (see test_task_queue.py's dedicated coverage),
        # which would have made this test pass for the wrong reason (starting
        # from an already-0 streak instead of genuinely resetting one).
        await s.task_queue.upsert_loop(
            status="running", plan_phase="build", context_dir=str(tmp_path),
            artifact_path=str(tmp_path / "artifact.md"),
            iteration=1, max_iterations=10, supervisor_model="sonnet",
            plan_item_reject_streak=2,  # 2 prior rejections already recorded
        )

        async def _approved(task, task_queue, project_dir, claude_dir):
            await task_queue.update(task["id"], status="done", oracle_result="approved", oracle_reason="ok")

        monkeypatch.setattr(s.worker_pool, "start_worker", _approved)

        await s._run_plan_build()

        assert escalated == []  # well below the cap, and this attempt succeeded
        loop_state = await s.task_queue.get_loop()
        assert loop_state["plan_item_reject_streak"] == 0
        assert "- [x] flaky then fixed" in plan_path.read_text()


class TestConvergedVsExhausted:
    """Round-4 gap: distinguish 'genuinely nothing left to do' (converged) from
    'hit max_iterations while items are still open' (exhausted) — Pieter Levels.
    Before this fix both BUILD-phase termination sites set status="converged"
    and fired the identical loop_converged notification, so a stuck loop was
    indistinguishable from a clean finish in the DB/UI.
    """

    async def test_max_iter_with_open_item_is_exhausted(self, tmp_path, monkeypatch):
        import session as sess_mod

        monkeypatch.setattr(sess_mod, "_fire_notification", AsyncMock())
        monkeypatch.setattr(sess_mod, "_suggest_next_goals", AsyncMock())

        plan_path = tmp_path / "IMPLEMENTATION_PLAN.md"
        plan_path.write_text("# Plan\n\n- [ ] still open\n")

        s = sess_mod.ProjectSession(str(tmp_path))
        await s.task_queue.upsert_loop(
            status="running", plan_phase="build", context_dir=str(tmp_path),
            artifact_path=str(tmp_path / "artifact.md"),
            # Genuinely PAST the ceiling (iteration > max_iterations) — all
            # max_iterations=2 real attempts have already happened, with an
            # unchecked item still in the plan.
            iteration=3, max_iterations=2, supervisor_model="sonnet",
        )

        start_worker = AsyncMock()
        monkeypatch.setattr(s.worker_pool, "start_worker", start_worker)

        await s._run_plan_build()

        loop_state = await s.task_queue.get_loop()
        assert loop_state["status"] == "exhausted"
        start_worker.assert_not_called()  # already past every allowed iteration

        fired = [c.args[0] for c in sess_mod._fire_notification.call_args_list]
        assert fired == ["loop_exhausted"]
        assert "loop_converged" not in fired

        # ceiling hit with zero attempts made this pass — item stays untouched
        assert "- [ ] still open" in plan_path.read_text()

    async def test_final_allowed_iteration_still_spawns_a_worker(self, tmp_path, monkeypatch):
        # Adversarial-review finding (correctness, MEDIUM): the ceiling check
        # used to fire on iteration == max_iterations (not just iteration >
        # max_iterations), silently consuming the LAST allowed iteration's
        # budget with zero work done — inconsistent with _run_supervisor
        # (review-mode), which does that iteration's work first and only
        # checks the ceiling afterward, giving exactly max_iterations real
        # attempts. iteration == max_iterations must still be a real attempt.
        import session as sess_mod

        monkeypatch.setattr(sess_mod, "_fire_notification", AsyncMock())
        monkeypatch.setattr(sess_mod, "_suggest_next_goals", AsyncMock())

        plan_path = tmp_path / "IMPLEMENTATION_PLAN.md"
        plan_path.write_text("# Plan\n\n- [ ] still open\n")

        s = sess_mod.ProjectSession(str(tmp_path))
        await s.task_queue.upsert_loop(
            status="running", plan_phase="build", context_dir=str(tmp_path),
            artifact_path=str(tmp_path / "artifact.md"),
            iteration=2, max_iterations=2, supervisor_model="sonnet",
        )

        async def _fake_start_worker(task, *a, **k):
            await s.task_queue.update(task["id"], status="done")

        start_worker = AsyncMock(side_effect=_fake_start_worker)
        monkeypatch.setattr(s.worker_pool, "start_worker", start_worker)

        await s._run_plan_build()

        start_worker.assert_called_once()  # the final allowed iteration IS attempted
        # the attempt succeeded — the item IS marked done, unlike the exhausted case
        assert "- [x] still open" in plan_path.read_text()

    async def test_all_items_done_is_converged_even_at_ceiling(self, tmp_path, monkeypatch):
        """If the checklist is actually empty, that's a genuine finish — even
        when iteration happens to already be >= max_iterations, it must stay
        "converged", not "exhausted" (the task_line_idx-is-None check runs
        before the max_iter check)."""
        import session as sess_mod

        monkeypatch.setattr(sess_mod, "_fire_notification", AsyncMock())
        monkeypatch.setattr(sess_mod, "_suggest_next_goals", AsyncMock())

        plan_path = tmp_path / "IMPLEMENTATION_PLAN.md"
        plan_path.write_text("# Plan\n\n- [x] already done\n")

        s = sess_mod.ProjectSession(str(tmp_path))
        await s.task_queue.upsert_loop(
            status="running", plan_phase="build", context_dir=str(tmp_path),
            artifact_path=str(tmp_path / "artifact.md"),
            iteration=2, max_iterations=2, supervisor_model="sonnet",
        )

        await s._run_plan_build()

        loop_state = await s.task_queue.get_loop()
        assert loop_state["status"] == "converged"

        fired = [c.args[0] for c in sess_mod._fire_notification.call_args_list]
        assert fired == ["loop_converged"]
        assert "loop_exhausted" not in fired
