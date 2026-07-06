"""Round-4 gap: distinguish "converged" (genuinely nothing left to do) from
"exhausted" (max_iterations hit while items are still open) in the
_run_supervisor review-mode loop — the sibling termination site to
_run_plan_build's BUILD-phase split (see
tests/test_plan_build.py::TestConvergedVsExhausted).

Before this fix, session.py had a single
`if is_converged or iteration >= max_iter:` branch that always wrote
status="converged" and fired "loop_converged" regardless of which condition
tripped it — a loop that ran out of iterations while still actively changing
things was indistinguishable, downstream, from one that had genuinely
finished.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import session as sess_mod

# ─── Subprocess fakes (same shape as tests/test_pure_judge_flags.py) ──────────


class _FakeProc:
    def __init__(self, stdout: bytes = b""):
        self._stdout = stdout
        self.returncode = 0

    async def communicate(self):
        return self._stdout, b""

    def kill(self):
        pass


class _AsyncioProxy:
    """Overridden names hit stubs; everything else passes through to real asyncio."""

    def __init__(self, **overrides):
        self._overrides = overrides

    def __getattr__(self, name):
        if name in self._overrides:
            return self._overrides[name]
        import asyncio as _real_asyncio
        return getattr(_real_asyncio, name)


async def _run_one_supervisor_pass(tmp_path, monkeypatch, supervisor_response: str, **loop_overrides):
    """Sets up a fresh loop row, runs exactly one _run_supervisor pass with the
    supervisor's `claude -p` call faked to return `supervisor_response`, and
    `git diff --stat` faked to return no output (semantic-hash path never
    fires — count-based convergence is the only signal under test). Returns
    (final loop_state, [fired notification event names], [captured prompt
    text written to disk for the claude -p call])."""
    s = sess_mod.ProjectSession(str(tmp_path))
    artifact = tmp_path / "artifact.md"
    artifact.write_text("# Artifact\nsome content\n")

    loop_fields = dict(
        status="running", mode="review", context_dir=str(tmp_path),
        artifact_path=str(artifact), iteration=0, changes_history=[],
        supervisor_model="sonnet",
    )
    loop_fields.update(loop_overrides)
    await s.task_queue.upsert_loop(**loop_fields)

    captured_prompts: list[str] = []

    async def _fake_shell(cmd, **kwargs):
        # cmd embeds `$(cat <prompt_file_path>)`; the file still exists at this
        # point in the real code (unlinked only after communicate() returns, in
        # the `finally` block) — read it back to assert the budget-awareness
        # injection actually reached the model prompt.
        for candidate in s.claude_dir.glob("supervisor-iter-*.md"):
            captured_prompts.append(candidate.read_text())
        return _FakeProc(supervisor_response.encode())

    async def _fake_exec(*args, **kwargs):
        return _FakeProc(b"")  # empty `git diff --stat` => semantic_hash stays ""

    monkeypatch.setattr(
        sess_mod, "asyncio",
        _AsyncioProxy(create_subprocess_shell=_fake_shell, create_subprocess_exec=_fake_exec),
    )
    monkeypatch.setattr(sess_mod, "_fire_notification", AsyncMock())
    monkeypatch.setattr(sess_mod, "_suggest_next_goals", AsyncMock())

    await s._run_supervisor()

    loop_state = await s.task_queue.get_loop()
    fired = [c.args[0] for c in sess_mod._fire_notification.call_args_list]
    return loop_state, fired, captured_prompts


class TestSupervisorConvergedVsExhausted:
    async def test_converged_self_report_is_converged_regardless_of_iteration(self, tmp_path, monkeypatch):
        """The supervisor's own {"type":"CONVERGED"} verdict is a genuine
        'nothing left to do' signal — must stay "converged" even far from the
        iteration ceiling."""
        response = json.dumps([{"type": "CONVERGED", "description": "no significant issues"}])
        loop_state, fired, _ = await _run_one_supervisor_pass(
            tmp_path, monkeypatch, response, max_iterations=20,
        )
        assert loop_state["status"] == "converged"
        assert fired == ["loop_converged"]

    async def test_dual_heuristic_converged_at_ceiling_stays_converged(self, tmp_path, monkeypatch):
        """Diff activity has quiesced (count-based heuristic satisfied) on the
        exact iteration the ceiling is also hit — genuine convergence must win
        over "exhausted": it isn't a coincidence that the loop stopped, the
        artifact really is done."""
        loop_state, fired, _ = await _run_one_supervisor_pass(
            tmp_path, monkeypatch, "[]",
            max_iterations=1, convergence_k=0, convergence_n=1,
        )
        assert loop_state["status"] == "converged"
        assert fired == ["loop_converged"]
        assert "loop_exhausted" not in fired

    async def test_ceiling_hit_without_convergence_is_exhausted(self, tmp_path, monkeypatch):
        """convergence_k=-1 makes count_converged structurally impossible
        (a change count is never < 0) — reaching max_iterations here means the
        loop was cut off mid-work, not that it finished."""
        loop_state, fired, prompts = await _run_one_supervisor_pass(
            tmp_path, monkeypatch, "[]",
            max_iterations=1, convergence_k=-1, convergence_n=1,
        )
        assert loop_state["status"] == "exhausted"
        assert fired == ["loop_exhausted"]
        assert "loop_converged" not in fired

        # budget-awareness injection reached the model prompt, without asking
        # the model to let it affect the CONVERGED verdict
        assert prompts, "supervisor prompt was never captured"
        assert "iteration 1 of 1" in prompts[0]
        assert "must NOT influence your CONVERGED judgment" in prompts[0]

    async def test_exhausted_still_persists_changes_history(self, tmp_path, monkeypatch):
        """The exhausted branch must not silently drop changes_history — it
        still needs to reflect the final iteration's diff-count entry."""
        loop_state, _, _ = await _run_one_supervisor_pass(
            tmp_path, monkeypatch, "[]",
            max_iterations=1, convergence_k=-1, convergence_n=1,
        )
        assert loop_state["changes_history"]
        assert loop_state["changes_history"][-1]["count"] == 0
