"""Tests for oracle criteria injection, magnitude/risk-based dispatch, the
constitution channel, and verdict resampling.

Split out of test_oracle_integrity.py (which covers liveness/persistence/
severity-gate mechanics) to stay under the 1500-line convention cap. Loads the
REAL worker_review.py / worker.py via importlib to bypass the conftest
MagicMock (same pattern as test_oracle_integrity.py).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

# ─── Load real modules bypassing conftest mocks ───────────────────────────────

_WR_FILE = Path(__file__).parent.parent / "worker_review.py"
_wr_spec = importlib.util.spec_from_file_location("_real_worker_review_criteria", _WR_FILE)
wr = importlib.util.module_from_spec(_wr_spec)
_wr_spec.loader.exec_module(wr)  # type: ignore[union-attr]

_W_FILE = Path(__file__).parent.parent / "worker.py"
_w_spec = importlib.util.spec_from_file_location("_real_worker_oracle_criteria", _W_FILE)
wmod = importlib.util.module_from_spec(_w_spec)
_w_spec.loader.exec_module(wmod)  # type: ignore[union-attr]

# worker.py's own `from worker_review import handle_oracle_requeue` resolved
# against conftest's mocked sys.modules['worker_review'] at exec time (a whole
# separate fake module from the real `wr` loaded above), not our real `wr` —
# rebind so poll_all's requeue path exercises the real implementation.
wmod.handle_oracle_requeue = wr.handle_oracle_requeue
wmod.handle_test_requeue = wr.handle_test_requeue
wmod.handle_ownership_requeue = wr.handle_ownership_requeue
wmod.handle_handoff_requeue = wr.handle_handoff_requeue


# ─── Fix-intent completeness criterion (item 15 part 1) ─────────────────────


class TestDetectFixIntent:
    @pytest.mark.parametrize("desc", [
        "fix: login crash on empty password",
        "Fix the bug in auth flow",
        "regression in parser since v2",
        "hotfix for prod outage",
        "BUG: dates render off-by-one",
    ])
    def test_fix_intent_detected(self, desc):
        assert wr._detect_fix_intent(desc) is True

    @pytest.mark.parametrize("desc", [
        "implement new feature for exports",
        "debug logging improvements",     # 'debug' must not match 'bug'
        "prefix: rename the config keys",  # 'prefix:' must not match 'fix:'
        "refactor module layout",
        "",
    ])
    def test_no_fix_intent(self, desc):
        assert wr._detect_fix_intent(desc) is False


class TestFixIntentCriterion:
    def test_fix_task_gets_covering_test_criterion(self):
        block = wr._build_oracle_task_block("fix: crash on empty input", None)
        assert "bug-fix task" in block
        assert "test covering the previously-failing input" in block

    def test_infra_yes_with_evidence(self):
        block = wr._build_oracle_task_block(
            "fix: crash on empty input", None,
            test_evidence="Project tests PASSED.\n3 passed",
        )
        assert "Test infrastructure present in this project: yes" in block

    def test_infra_unknown_without_evidence(self):
        block = wr._build_oracle_task_block("fix: crash on empty input", None)
        assert "Test infrastructure present in this project: unknown" in block

    def test_non_fix_task_has_no_criterion(self):
        block = wr._build_oracle_task_block("implement exports feature", None)
        assert "bug-fix task" not in block

    def test_fix_task_gets_one_step_removed_criterion(self):
        # lovesegfault r25: fixes verified only against the original claim
        # introduced 8/12 of the next round's regressions.
        block = wr._build_oracle_task_block("fix: crash on empty input", None)
        assert "one step removed" in block
        assert "inverse input case" in block
        assert "sibling consumer" in block

    def test_non_fix_task_has_no_one_step_criterion(self):
        block = wr._build_oracle_task_block("implement exports feature", None)
        assert "one step removed" not in block

    async def test_criterion_reaches_spec_prompt(self, tmp_path, monkeypatch):
        prompts: list[str] = []

        async def fake_pass(prompt, cdir, samples=1):
            prompts.append(prompt)
            return True, "high", "", False

        monkeypatch.setattr(wr, "_oracle_pass", fake_pass)
        await wr._oracle_review("fix: crash on empty input", "small diff", tmp_path)
        assert "bug-fix task" in prompts[0]

    async def test_criterion_reaches_chunked_path(self, tmp_path, monkeypatch):
        seen: list[str] = []

        async def fake_chunk(task, chunk, label, cdir, constitution="", samples=1):
            seen.append(task)
            return True, "approved", False

        monkeypatch.setattr(wr, "_oracle_review_chunk", fake_chunk)
        await wr._oracle_review("fix: regression in worker pool", "x" * 9000, tmp_path)
        assert seen and all("bug-fix task" in t for t in seen)

    def test_fix_task_gets_test_integrity_criterion(self):
        # Kent Beck: a diff that reaches "tests pass" by weakening/deleting the
        # failing assertion is not a fix — the oracle must check for that too.
        block = wr._build_oracle_task_block("fix: crash on empty input", None)
        assert "WEAKENING OR DELETING" in block
        assert "test that got weaker to pass" in block

    def test_non_fix_task_has_no_test_integrity_criterion(self):
        block = wr._build_oracle_task_block("implement exports feature", None)
        assert "WEAKENING OR DELETING" not in block

    async def test_test_integrity_criterion_reaches_spec_prompt(self, tmp_path, monkeypatch):
        prompts: list[str] = []

        async def fake_pass(prompt, cdir, samples=1):
            prompts.append(prompt)
            return True, "high", "", False

        monkeypatch.setattr(wr, "_oracle_pass", fake_pass)
        await wr._oracle_review("fix: off-by-one in pagination", "small diff", tmp_path)
        assert "WEAKENING OR DELETING" in prompts[0]


# ─── Magnitude-anomaly skepticism for perf claims (Round-4, Mitchell Hashimoto) ──


class TestDetectPerfIntent:
    @pytest.mark.parametrize("desc", [
        "perf: cut request latency in half",
        "optimize the hot path in the parser",
        "speed up the ingest pipeline 10x",
        "sped up cold start by removing sync IO",
        "benchmark and improve throughput",
        "reduce latency on the search endpoint",
    ])
    def test_perf_intent_detected(self, desc):
        assert wr._detect_perf_intent(desc) is True

    @pytest.mark.parametrize("desc", [
        "implement new feature for exports",
        "fix: crash on empty input",
        "refactor module layout",
        "",
    ])
    def test_no_perf_intent(self, desc):
        assert wr._detect_perf_intent(desc) is False


class TestPerfMagnitudeCriterion:
    def test_perf_task_gets_magnitude_criterion(self):
        block = wr._build_oracle_task_block("optimize: cut latency 10x", None)
        assert "performance/optimization task" in block
        assert "agent psychosis" in block
        assert "magnitude claim at face value" in block

    def test_non_perf_task_has_no_criterion(self):
        block = wr._build_oracle_task_block("implement exports feature", None)
        assert "performance/optimization task" not in block

    def test_fix_and_perf_criteria_can_coexist(self):
        # a task can be both a fix and a perf claim (e.g. "fix: N+1 query, 50x faster")
        block = wr._build_oracle_task_block("fix: N+1 query, now 50x faster", None)
        assert "bug-fix task" in block
        assert "performance/optimization task" in block

    async def test_criterion_reaches_spec_prompt(self, tmp_path, monkeypatch):
        prompts: list[str] = []

        async def fake_pass(prompt, cdir, samples=1):
            prompts.append(prompt)
            return True, "high", "", False

        monkeypatch.setattr(wr, "_oracle_pass", fake_pass)
        await wr._oracle_review("optimize: cut latency 10x", "small diff", tmp_path)
        assert "performance/optimization task" in prompts[0]

    async def test_criterion_reaches_chunked_path(self, tmp_path, monkeypatch):
        seen: list[str] = []

        async def fake_chunk(task, chunk, label, cdir, constitution="", samples=1):
            seen.append(task)
            return True, "approved", False

        monkeypatch.setattr(wr, "_oracle_review_chunk", fake_chunk)
        await wr._oracle_review("optimize: reduce p99 latency", "x" * 9000, tmp_path)
        assert seen and all("performance/optimization task" in t for t in seen)


# ─── Risk-based diff dispatch (Round-4, Takanori Sano) ───────────────────────


class TestClassifyDiffRisk:
    @pytest.mark.parametrize("diff,expected", [
        ("diff --git a/orchestrator/billing/charge.py b/orchestrator/billing/charge.py\n+x=1", True),
        ("diff --git a/auth/login.py b/auth/login.py\n+x=1", True),
        ("diff --git a/migrations/0001_init.py b/migrations/0001_init.py\n+x", True),
        ("+ os.system('rm -rf /')", True),
        ("+ subprocess.run(cmd, shell=True)", True),
        ("+ cursor.execute('DELETE FROM users WHERE id=5')", True),  # safe-biased: extra scrutiny either way
        ("+ chmod 777 /etc/passwd", True),
        ("diff --git a/src/foo_authors.py b/src/foo_authors.py\n+x=1", False),  # 'authors' != 'auth'
        ("diff --git a/README.md b/README.md\n+docstring typo fix", False),
        ("diff --git a/orchestrator/config.py b/orchestrator/config.py\n+x=1", False),
        ("+ def executive_summary(): pass", False),  # 'exec' inside 'executive' must not false-positive
        ("", False),
    ])
    def test_classify_diff_risk(self, diff, expected):
        assert wr._classify_diff_risk(diff) is expected

    async def test_risky_short_diff_forces_extra_samples(self, tmp_path, monkeypatch):
        seen: list[int] = []

        async def fake_pass(prompt, cdir, samples=1):
            seen.append(samples)
            return True, "high", "", False

        monkeypatch.setattr(wr, "_oracle_pass", fake_pass)
        # default verdict_samples=1, but the diff touches a risky path
        await wr._oracle_review(
            "task", "diff --git a/auth/login.py b/auth/login.py\n+x=1", tmp_path,
        )
        assert seen == [3, 3]  # spec + quality passes both bumped to 3

    async def test_nonrisky_short_diff_keeps_requested_samples(self, tmp_path, monkeypatch):
        seen: list[int] = []

        async def fake_pass(prompt, cdir, samples=1):
            seen.append(samples)
            return True, "high", "", False

        monkeypatch.setattr(wr, "_oracle_pass", fake_pass)
        await wr._oracle_review("task", "docstring typo", tmp_path)
        assert seen == [1, 1]  # unaffected — no risk signal

    async def test_risky_diff_does_not_downgrade_higher_requested_samples(self, tmp_path, monkeypatch):
        seen: list[int] = []

        async def fake_pass(prompt, cdir, samples=1):
            seen.append(samples)
            return True, "high", "", False

        monkeypatch.setattr(wr, "_oracle_pass", fake_pass)
        await wr._oracle_review(
            "task", "diff --git a/auth/login.py b/auth/login.py\n+x=1", tmp_path,
            verdict_samples=5,
        )
        assert seen == [5, 5]  # already >= 3 — risk bump never lowers it

    async def test_risky_large_diff_forces_extra_samples_on_chunks(self, tmp_path, monkeypatch):
        seen: list[int] = []

        async def fake_chunk(task, chunk, label, cdir, constitution="", samples=1):
            seen.append(samples)
            return True, "approved", False

        monkeypatch.setattr(wr, "_oracle_review_chunk", fake_chunk)
        big_risky_diff = "diff --git a/auth/login.py b/auth/login.py\n" + "+x\n" * wr._ORACLE_CHUNK_SIZE
        await wr._oracle_review("task", big_risky_diff, tmp_path)
        assert seen and all(s == 3 for s in seen)


async def test_poll_all_requeues_on_pre_push_test_failure(task_queue, tmp_path):
    pool = wmod.WorkerPool()
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(exist_ok=True)
    w = wmod.Worker(
        task_id="task-tf1", description="implement feature X",
        model="haiku", project_dir=tmp_path, claude_dir=claude_dir,
    )
    w.status = "done"
    w._terminal_persisted = True
    w._test_requeue = True
    w._test_requeue_reason = "Project tests FAILED.\n2 failed, 1 passed"
    pool.workers[w.id] = w

    await pool.poll_all(task_queue, None)

    assert w._test_requeue is False
    tasks = await task_queue.list()
    retries = [t for t in tasks if "FAILED the project test suite" in t["description"]]
    assert len(retries) == 1
    assert "2 failed" in retries[0]["description"]
    assert "implement feature X" in retries[0]["description"]


# ─── Reject-round circuit breaker (Round-4, fennu2333/Chorus) ────────────────
# oracle_retry_sample_count bounds the FAN-OUT WIDTH on plateau but not the
# TOTAL round count. A task's oracle-reject depth hitting oracle_max_reject_rounds
# must stop requeuing and escalate instead — never requeue forever.


def _rejected_desc(n_rejections: int) -> str:
    marker = wr.ORACLE_REJECT_MARKER
    return "implement feature X" + "".join(f"\n--- Previous attempt was {marker}: ..." for _ in range(n_rejections))


async def test_poll_all_requeues_below_reject_cap(task_queue, tmp_path, monkeypatch):
    monkeypatch.setitem(wmod.GLOBAL_SETTINGS, "oracle_max_reject_rounds", 5)
    pool = wmod.WorkerPool()
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(exist_ok=True)
    w = wmod.Worker(
        task_id="task-cap1", description=_rejected_desc(2),  # depth 2 < cap 5
        model="haiku", project_dir=tmp_path, claude_dir=claude_dir,
    )
    w.status = "done"
    w._terminal_persisted = True
    w._oracle_requeue = True
    w._oracle_requeue_reason = "[high] still wrong"
    pool.workers[w.id] = w

    escalated = []

    async def fake_escalate(*a, **k):
        escalated.append(a)

    monkeypatch.setattr(wr, "_escalate_oracle_reject_plateau", fake_escalate)

    await pool.poll_all(task_queue, None)

    assert w._oracle_requeue is False
    assert escalated == []  # below the cap — no escalation
    tasks = await task_queue.list()
    retries = [t for t in tasks if "Previous attempt was" in t["description"]]
    assert len(retries) >= 1  # requeued as usual


async def test_poll_all_skips_oracle_requeue_for_loop_managed_tasks(task_queue, tmp_path, monkeypatch):
    # Adversarial-review finding (correctness, HIGH): loop/plan-managed tasks have
    # their OWN retry pipeline (session.py's plan-drift guard re-spawns "[Plan-N+1]"
    # next iteration) — spawning an untracked handle_oracle_requeue retry too would
    # race a second worker against the plan/loop's own tracked one on the same item.
    # Mirrors the pre-existing guard on the stuck-worker requeue path (worker.py ~1302).
    monkeypatch.setitem(wmod.GLOBAL_SETTINGS, "oracle_max_reject_rounds", 5)
    pool = wmod.WorkerPool()
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(exist_ok=True)
    for prefix in ("[Loop-3]", "[Plan-2]"):
        w = wmod.Worker(
            task_id=f"task-{prefix}", description=f"{prefix} implement feature X",
            model="haiku", project_dir=tmp_path, claude_dir=claude_dir,
        )
        w.status = "done"
        w._terminal_persisted = True
        w._oracle_requeue = True
        w._oracle_requeue_reason = "[high] still wrong"
        pool.workers[w.id] = w

    handled = []

    async def fake_handle(*a, **k):
        handled.append(a)

    monkeypatch.setattr(wmod, "handle_oracle_requeue", fake_handle)

    await pool.poll_all(task_queue, None)

    assert handled == []  # neither loop- nor plan-prefixed task calls handle_oracle_requeue
    for w in pool.workers.values():
        assert w._oracle_requeue is False  # flag still cleared, just no requeue spawned
    tasks = await task_queue.list()
    assert not any("Previous attempt was" in t["description"] for t in tasks)


async def test_poll_all_skips_test_requeue_for_loop_managed_tasks(task_queue, tmp_path):
    # Round-2 adversarial-review finding (correctness, HIGH): the loop/plan guard
    # above only covered the oracle-requeue site — this sibling site (pre-push
    # test failure) reproduced the identical untracked-duplicate-task bug.
    # failed_reason is still recorded (pure diagnostic on the existing row, no
    # new task, so no race) — only the task_queue.add() spawn is skipped.
    pool = wmod.WorkerPool()
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(exist_ok=True)
    task = await task_queue.add("[Plan-2] implement feature X", "haiku")
    w = wmod.Worker(
        task_id=task["id"], description="[Plan-2] implement feature X",
        model="haiku", project_dir=tmp_path, claude_dir=claude_dir,
    )
    w.status = "done"
    w._terminal_persisted = True
    w._test_requeue = True
    w._test_requeue_reason = "Project tests FAILED.\n2 failed, 1 passed"
    pool.workers[w.id] = w

    await pool.poll_all(task_queue, None)

    assert w._test_requeue is False
    tasks = await task_queue.list()
    assert not any("FAILED the project test suite" in t["description"] for t in tasks)
    row = await task_queue.get(task["id"])
    assert "Pre-push tests failed" in (row.get("failed_reason") or "")


async def test_poll_all_skips_ownership_requeue_for_loop_managed_tasks(task_queue, tmp_path):
    pool = wmod.WorkerPool()
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(exist_ok=True)
    task = await task_queue.add("[Loop-4] implement feature X", "haiku")
    w = wmod.Worker(
        task_id=task["id"], description="[Loop-4] implement feature X",
        model="haiku", project_dir=tmp_path, claude_dir=claude_dir,
    )
    w.status = "done"
    w._terminal_persisted = True
    w._ownership_violation = True
    w._ownership_violation_reason = "edited forbidden.py"
    pool.workers[w.id] = w

    await pool.poll_all(task_queue, None)

    assert w._ownership_violation is False
    tasks = await task_queue.list()
    assert not any("file ownership violation" in t["description"] for t in tasks)
    row = await task_queue.get(task["id"])
    assert "Ownership violation" in (row.get("failed_reason") or "")


async def test_poll_all_skips_handoff_requeue_for_loop_managed_tasks(task_queue, tmp_path):
    pool = wmod.WorkerPool()
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(exist_ok=True)
    w = wmod.Worker(
        task_id="task-plan-ho", description="[Plan-1] implement feature X",
        model="haiku", project_dir=tmp_path, claude_dir=claude_dir,
    )
    w.status = "done"
    w._terminal_persisted = True
    w._handoff_requeue = True
    w._handoff_content = "ran out of context, see notes.md"
    pool.workers[w.id] = w

    await pool.poll_all(task_queue, None)

    assert w._handoff_requeue is False
    tasks = await task_queue.list()
    assert not any("previous session handed off" in t["description"] for t in tasks)


async def test_poll_all_still_requeues_all_three_siblings_for_non_loop_tasks(task_queue, tmp_path):
    # Regression guard: the shared _is_loop_task hoist must not accidentally
    # disable these paths for ordinary (non-loop/plan) tasks.
    pool = wmod.WorkerPool()
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(exist_ok=True)
    specs = [
        ("task-tf", "_test_requeue", "_test_requeue_reason", "tests failed", "FAILED the project test suite"),
        ("task-ov", "_ownership_violation", "_ownership_violation_reason", "bad edit", "file ownership violation"),
        ("task-ho", "_handoff_requeue", "_handoff_content", "handoff notes", "previous session handed off"),
    ]
    for task_id, flag, reason_attr, reason_val, expect_substr in specs:
        w = wmod.Worker(
            task_id=task_id, description="implement feature X (no prefix)",
            model="haiku", project_dir=tmp_path, claude_dir=claude_dir,
        )
        w.status = "done"
        w._terminal_persisted = True
        setattr(w, flag, True)
        setattr(w, reason_attr, reason_val)
        pool.workers[w.id] = w

    await pool.poll_all(task_queue, None)

    tasks = await task_queue.list()
    for _, _, _, _, expect_substr in specs:
        assert any(expect_substr in t["description"] for t in tasks), (
            f"expected a requeued task containing {expect_substr!r}"
        )


async def test_poll_all_escalates_instead_of_requeuing_at_reject_cap(task_queue, tmp_path, monkeypatch):
    monkeypatch.setitem(wmod.GLOBAL_SETTINGS, "oracle_max_reject_rounds", 3)
    pool = wmod.WorkerPool()
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(exist_ok=True)
    w = wmod.Worker(
        task_id="task-cap2", description=_rejected_desc(3),  # depth 3 == cap 3
        model="haiku", project_dir=tmp_path, claude_dir=claude_dir,
    )
    w.status = "done"
    w._terminal_persisted = True
    w._oracle_requeue = True
    w._oracle_requeue_reason = "[high] fundamentally wrong approach"
    pool.workers[w.id] = w

    escalated = []

    async def fake_escalate(project_dir, cdir, webhook, task_id, rounds):
        escalated.append((task_id, rounds))

    monkeypatch.setattr(wr, "_escalate_oracle_reject_plateau", fake_escalate)

    tasks_before = await task_queue.list()

    await pool.poll_all(task_queue, None)

    assert w._oracle_requeue is False
    assert escalated == [("task-cap2", 3)]
    tasks_after = await task_queue.list()
    # No new task was added — escalation replaces the requeue, not adds to it.
    assert len(tasks_after) == len(tasks_before)


async def test_reject_cap_zero_disables_the_breaker(task_queue, tmp_path, monkeypatch):
    # 0 = unbounded (prior behavior) — even a very deep lineage still requeues.
    monkeypatch.setitem(wmod.GLOBAL_SETTINGS, "oracle_max_reject_rounds", 0)
    pool = wmod.WorkerPool()
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(exist_ok=True)
    w = wmod.Worker(
        task_id="task-cap3", description=_rejected_desc(50),
        model="haiku", project_dir=tmp_path, claude_dir=claude_dir,
    )
    w.status = "done"
    w._terminal_persisted = True
    w._oracle_requeue = True
    w._oracle_requeue_reason = "[high] still wrong"
    pool.workers[w.id] = w

    escalated = []

    async def fake_escalate(*a, **k):
        escalated.append(a)

    monkeypatch.setattr(wr, "_escalate_oracle_reject_plateau", fake_escalate)

    await pool.poll_all(task_queue, None)

    assert escalated == []
    tasks = await task_queue.list()
    retries = [t for t in tasks if "Previous attempt was" in t["description"]]
    assert len(retries) >= 1


class TestEscalateOracleRejectPlateau:
    async def test_writes_blockers_md(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        await wr._escalate_oracle_reject_plateau(tmp_path, claude_dir, "", "task-1", 5)
        blockers = (claude_dir / "blockers.md").read_text()
        assert "task-1" in blockers
        assert "5 times" in blockers
        assert "Blocker" in blockers

    async def test_no_webhook_skips_http(self, tmp_path, monkeypatch):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        async def fail_if_called(*a, **k):
            raise AssertionError("must not attempt a webhook POST when webhook=''")

        monkeypatch.setattr(wr.asyncio, "create_subprocess_exec", fail_if_called)
        await wr._escalate_oracle_reject_plateau(tmp_path, claude_dir, "", "task-1", 5)  # must not raise

    async def test_fires_webhook_with_distinct_event_name(self, tmp_path, monkeypatch):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        captured = {}

        class _FakeProc:
            async def communicate(self):
                return b"", b""
            def kill(self):
                pass

        async def fake_exec(*args, **kwargs):
            captured["args"] = args
            return _FakeProc()

        monkeypatch.setattr(wr.asyncio, "create_subprocess_exec", fake_exec)
        await wr._escalate_oracle_reject_plateau(tmp_path, claude_dir, "http://h/x", "task-1", 5)
        payload = captured["args"][captured["args"].index("-d") + 1]
        assert '"event": "oracle_reject_plateau"' in payload
        assert '"task_id": "task-1"' in payload

    async def test_escalation_failure_does_not_raise(self, tmp_path, monkeypatch):
        # blockers.md write itself fails (e.g. read-only claude_dir) — fail-open.
        claude_dir = tmp_path / "nonexistent-dir-that-cannot-be-written"
        await wr._escalate_oracle_reject_plateau(tmp_path, claude_dir, "", "task-1", 5)  # must not raise


# ─── Constitutional check (reflection-agents §Gap4) ───────────────────────────


class TestReadConstitution:
    """_read_constitution extracts the CLAUDE.md 'Code Rules' section, fail-open."""

    def test_extracts_code_rules_section(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text(
            "# Project\n\nintro\n\n"
            "## Code Rules\n\n- Keep files < 1500 lines\n- No circular imports\n\n"
            "## Next Section\n\n- unrelated\n",
            encoding="utf-8",
        )
        rules = wr._read_constitution(tmp_path)
        assert "Keep files < 1500 lines" in rules
        assert "No circular imports" in rules
        # bounded: must NOT bleed into the following section
        assert "unrelated" not in rules

    def test_no_claude_md_returns_empty(self, tmp_path):
        assert wr._read_constitution(tmp_path) == ""

    def test_claude_md_without_code_rules_returns_empty(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text(
            "# Project\n\n## Architecture\n\n- modules\n", encoding="utf-8"
        )
        assert wr._read_constitution(tmp_path) == ""

    def test_section_is_capped(self, tmp_path):
        big = "\n".join(f"- rule {i}" for i in range(500))
        (tmp_path / "CLAUDE.md").write_text(
            f"## Code Rules\n\n{big}\n", encoding="utf-8"
        )
        assert len(wr._read_constitution(tmp_path)) <= 1500


class TestConstitutionInjection:
    """The constitution must reach the grader on BOTH oracle routes, and never
    leak a header when no rules are declared."""

    _SENTINEL = "Keep files < 1500 lines (sentinel-XYZ)"

    async def test_constitution_reaches_quality_pass_short_diff(self, tmp_path, monkeypatch):
        captured: list[str] = []

        async def fake_pass(prompt, claude_dir, samples=1):
            captured.append(prompt)
            return True, "high", "", False  # passed, conf, issues, infra

        monkeypatch.setattr(wr, "_oracle_pass", fake_pass)
        approved, reason, infra = await wr._oracle_review(
            "task", "small diff", tmp_path, constitution=self._SENTINEL
        )
        assert approved and not infra
        # spec pass (captured[0]) is task-only; quality pass (captured[1]) carries it
        assert any("PROJECT CODE RULES" in p and self._SENTINEL in p for p in captured)
        # constitution is a quality concern, NOT a spec concern — must not leak
        # into the spec pass (captured[0]).
        assert "PROJECT CODE RULES" not in captured[0]

    async def test_no_constitution_no_header_leak(self, tmp_path, monkeypatch):
        captured: list[str] = []

        async def fake_pass(prompt, claude_dir, samples=1):
            captured.append(prompt)
            return True, "high", "", False

        monkeypatch.setattr(wr, "_oracle_pass", fake_pass)
        await wr._oracle_review("task", "small diff", tmp_path, constitution="")
        assert all("PROJECT CODE RULES" not in p for p in captured)

    async def test_constitution_threaded_to_chunks_large_diff(self, tmp_path, monkeypatch):
        captured: dict = {}

        async def fake_chunk(task, chunk, label, claude_dir, constitution="", samples=1):
            captured["constitution"] = constitution
            return True, "ok", False  # approved, reason, infra

        monkeypatch.setattr(wr, "_oracle_review_chunk", fake_chunk)
        big_diff = "+x\n" * (wr._ORACLE_CHUNK_SIZE)  # well over one chunk
        approved, reason, infra = await wr._oracle_review(
            "task", big_diff, tmp_path, constitution=self._SENTINEL
        )
        assert approved and not infra
        assert captured.get("constitution") == self._SENTINEL


# ─── Verdict resampling / majority vote (Round 3 gap B) ──────────────────────


class TestOracleVerdictResampling:
    """Judge non-determinism mitigation: resample K× and require a CLEAN MAJORITY
    to APPROVE (safe bias — a false-approve gates auto-merge; a false-reject only
    costs a retry). Default samples=1 stays single-shot (no extra cost)."""

    # _aggregate_oracle_votes truth table (pure function)
    def test_aggregate_all_pass(self):
        P = (True, "high", "", False)
        assert wr._aggregate_oracle_votes([P, P, P]) == (True, "high", "", False)

    def test_aggregate_all_fail_surfaces_issue(self):
        F = (False, "medium", "bug", False)
        passed, conf, issues, infra = wr._aggregate_oracle_votes([F, F, F])
        assert (passed, infra, issues) == (False, False, "bug")

    def test_aggregate_majority_pass(self):
        P, F = (True, "high", "", False), (False, "high", "x", False)
        assert wr._aggregate_oracle_votes([P, P, F])[0] is True

    def test_aggregate_majority_fail(self):
        P, F = (True, "high", "", False), (False, "high", "x", False)
        assert wr._aggregate_oracle_votes([P, F, F])[0] is False

    def test_aggregate_tie_biases_to_reject(self):
        # no clean majority → safe direction (reject)
        P, F = (True, "high", "", False), (False, "low", "x", False)
        assert wr._aggregate_oracle_votes([P, F])[0] is False

    def test_aggregate_all_infra_is_unreviewed(self):
        I = (True, "none", "boom", True)
        assert wr._aggregate_oracle_votes([I, I, I])[3] is True

    def test_aggregate_ignores_infra_samples(self):
        I, F = (True, "none", "boom", True), (False, "high", "x", False)
        # 2 non-reviews + 1 real fail → the one valid vote decides: fail
        assert wr._aggregate_oracle_votes([I, I, F]) == (False, "high", "x", False)

    # _oracle_pass resampling wrapper
    async def test_pass_samples_resamples_and_votes(self, tmp_path, monkeypatch):
        # LOSING verdict FIRST: a single-shot degradation returns the first _once
        # result (reject) and would FAIL this assertion — only real resample+vote
        # (2 of 3 pass) yields approve. This pins the resample-and-vote wiring.
        seq = iter([
            (False, "high", "spurious", False),  # first sample flips — loses the vote
            (True, "high", "", False),
            (True, "medium", "", False),
        ])
        calls = []
        async def fake_once(prompt, cdir):
            calls.append(1)
            return next(seq)
        monkeypatch.setattr(wr, "_oracle_pass_once", fake_once)
        passed, conf, issues, infra = await wr._oracle_pass("p", tmp_path, samples=3)
        assert (passed, infra) == (True, False)
        assert len(calls) == 3  # actually resampled K times, not single-shot

    async def test_pass_samples_1_is_single_shot(self, tmp_path, monkeypatch):
        calls = []
        async def fake_once(prompt, cdir):
            calls.append(1)
            return (True, "high", "", False)
        monkeypatch.setattr(wr, "_oracle_pass_once", fake_once)
        await wr._oracle_pass("p", tmp_path, samples=1)
        assert len(calls) == 1  # default path runs once — no extra Haiku cost

    # _oracle_review_chunk resampling wrapper (side effects applied ONCE)
    async def test_chunk_samples_majority_writes_followups_once(self, tmp_path, monkeypatch):
        # LOSING verdict FIRST (reject) so a single-shot degradation returns reject
        # and FAILS the (True,False) assertion — only real resample+vote approves.
        seq = iter([
            (False, "[high] rejected", False, [], False),  # first sample loses the vote
            (True, "approved", False, [{"severity": "info", "fix_suggestion": "x"}], True),
            (True, "approved", False, [{"severity": "info", "fix_suggestion": "y"}], True),
        ])
        calls = []
        async def fake_once(prompt, cdir):
            calls.append(1)
            return next(seq)
        writes = []
        monkeypatch.setattr(wr, "_oracle_review_chunk_once", fake_once)
        monkeypatch.setattr(wr, "_append_followup_findings",
                            lambda cdir, findings, label: writes.append(findings))
        approved, reason, infra = await wr._oracle_review_chunk("t", "d", "1/1", tmp_path, samples=3)
        assert (approved, infra) == (True, False)
        assert len(calls) == 3  # actually resampled, not single-shot
        assert len(writes) == 1  # exactly one follow-up write despite 3 samples
        # ...and it is the WINNING (first approve) sample's payload, not a loser's
        assert writes[0] == [{"severity": "info", "fix_suggestion": "x"}]

    async def test_chunk_samples_mixed_infra_excluded_from_denominator(self, tmp_path, monkeypatch):
        # [approve(valid), infra, infra] → the lone valid vote decides: approve.
        # Guards the chunk denominator (len(valid), not len(results)): a regression
        # to len(results) would flip 1*2>1 (approve) to 1*2>3 (reject).
        seq = iter([
            (True, "approved", False, [], False),
            (True, "oracle timeout (60s)", True, [], False),
            (True, "oracle timeout (60s)", True, [], False),
        ])
        async def fake_once(prompt, cdir):
            return next(seq)
        monkeypatch.setattr(wr, "_oracle_review_chunk_once", fake_once)
        monkeypatch.setattr(wr, "_append_followup_findings", lambda *a, **k: None)
        approved, reason, infra = await wr._oracle_review_chunk("t", "d", "", tmp_path, samples=3)
        assert (approved, infra) == (True, False)

    # _oracle_review threads verdict_samples down to the pass/chunk functions
    async def test_review_threads_samples_to_two_pass(self, tmp_path, monkeypatch):
        seen = []
        async def fake_pass(prompt, cdir, samples=1):
            seen.append(samples)
            return True, "high", "", False
        monkeypatch.setattr(wr, "_oracle_pass", fake_pass)
        await wr._oracle_review("task", "small diff", tmp_path, verdict_samples=3)
        assert seen == [3, 3]  # spec + quality passes both get samples=3

    async def test_review_threads_samples_to_chunks(self, tmp_path, monkeypatch):
        seen = []
        async def fake_chunk(task, chunk, label, cdir, constitution="", samples=1):
            seen.append(samples)
            return True, "ok", False
        monkeypatch.setattr(wr, "_oracle_review_chunk", fake_chunk)
        big = "+x\n" * wr._ORACLE_CHUNK_SIZE  # forces the chunked path
        await wr._oracle_review("task", big, tmp_path, verdict_samples=3)
        assert seen and all(s == 3 for s in seen)

    async def test_chunk_samples_majority_reject(self, tmp_path, monkeypatch):
        # LOSING verdict FIRST (approve) so single-shot would wrongly approve;
        # only real resample+vote (2 of 3 reject) yields reject.
        seq = iter([
            (True, "approved", False, [], True),  # first sample loses the vote
            (False, "[high] a", False, [], False),
            (False, "[high] b", False, [], False),
        ])
        async def fake_once(prompt, cdir):
            return next(seq)
        monkeypatch.setattr(wr, "_oracle_review_chunk_once", fake_once)
        monkeypatch.setattr(wr, "_append_followup_findings", lambda *a, **k: None)
        approved, reason, infra = await wr._oracle_review_chunk("t", "d", "", tmp_path, samples=3)
        assert (approved, infra) == (False, False)

    async def test_chunk_samples_all_infra_is_unreviewed(self, tmp_path, monkeypatch):
        async def fake_once(prompt, cdir):
            return (True, "oracle timeout (60s)", True, [], False)
        monkeypatch.setattr(wr, "_oracle_review_chunk_once", fake_once)
        approved, reason, infra = await wr._oracle_review_chunk("t", "d", "", tmp_path, samples=3)
        assert infra is True
