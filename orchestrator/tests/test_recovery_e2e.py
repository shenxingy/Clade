"""Offline recovery e2e — planted failures rehearse the failure→adapt→success chain.

Every recovery bug to date (stuck workers, requeue dedup, ownership loops) was
discovered in paid production runs. This suite drives the REAL Worker pipeline
(worktree setup, task-file build, verify, commit, pre-push tests, oracle gate,
requeue) against hermetic stand-ins:

- ``fixtures/mock-claude`` — turn-counting mock on PATH (test-loop.sh's
  MOCK_CLAUDE_* convention, extended with prompt-kind dispatch so verify /
  oracle / summary calls don't consume worker turns).
- ``fixtures/mock-gh``     — state-backed gh mock (.gh-state dir with issue
  JSON, PR JSON, and a scripted failing-then-passing CI run).
- tmpdir git repos + tmp HOME — no network, no real claude/gh, no committer.sh
  (the bare-git fallback commit path runs instead).

Covered planted-failure variants (breadth over cleverness):
1. pre-push test failure → commit undone → _test_requeue retry context carries
   the test output → adapted retry succeeds (wave 1 moved test runs pre-oracle
   into verify_and_commit; the retry path is _test_requeue, not reflection)
2. oracle infra error → commit survives tagged 'unreviewed' (never silent-approved)
3. oracle infra streak hits threshold → blockers.md escalation
4. oracle rejection → commit undone → requeue with reason → approved retry
5. classified subprocess failure (rate limit) → failed_reason persisted, no requeue
6. file-ownership violation → changes discarded → requeue with globs → adapted retry
7. mock-gh CI failure pre-hydrated into the task file; passing rerun drops the block
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

ORCHESTRATOR = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"

# ─── Load the real worker pipeline (bypassing conftest's safety mocks) ────────
# conftest.py replaces worker_review with a MagicMock so unit suites never spawn
# real claude subprocesses. This e2e NEEDS the genuine oracle pipeline (prompt
# file → subprocess → fence-strip parse → infra tagging) running against the
# PATH-mocked claude, so worker.py is loaded with the real worker_review bound.
# sys.modules is restored immediately — other test modules keep the mocks.


def _load_module(alias: str, filename: str):
    spec = importlib.util.spec_from_file_location(alias, ORCHESTRATOR / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


worker_review_real = _load_module("_e2e_worker_review", "worker_review.py")

_saved_wr = sys.modules.get("worker_review")
sys.modules["worker_review"] = worker_review_real
try:
    wmod = _load_module("_e2e_worker", "worker.py")
finally:
    if _saved_wr is None:
        sys.modules.pop("worker_review", None)
    else:
        sys.modules["worker_review"] = _saved_wr

import config  # noqa: E402
from event_stream import EventStream  # noqa: E402
from tracing import TracingService  # noqa: E402

# ─── Toy project seed ─────────────────────────────────────────────────────────

APP_PY = "def compute():\n    return 42\n"

# Plain-python test runner with pytest-style output: hermetic (no pytest dep in
# the subprocess) yet realistic enough for evidence/requeue assertions.
RUN_TESTS_PY = '''\
import sys

sys.path.insert(0, ".")
import app

failures = []
if app.compute() != 42:
    failures.append("FAILED tests/test_app.py::test_compute - assert compute() == 42")
square = getattr(app, "square", None)
if square is not None and square(3) != 9:
    failures.append(
        "FAILED tests/test_app.py::test_square - AssertionError: "
        "PLANTED_BUG square(3) returned %r, expected 9" % (square(3),)
    )
if failures:
    print("\\n".join(failures))
    print("%d failed, 1 passed" % len(failures))
    sys.exit(1)
print("2 passed")
'''

GITCONFIG = """\
[user]
\tname = Recovery E2E
\temail = e2e@example.invalid
[init]
\tdefaultBranch = main
"""

# Deterministic GLOBAL_SETTINGS for every scenario — the real settings file was
# loaded at config import time, so each key the worker path reads gets pinned.
PINNED_SETTINGS = {
    "auto_push": False,           # no remote in the tmp repo
    "auto_oracle": False,         # oracle scenarios flip this on explicitly
    "github_issues_sync": False,
    "auto_classify_retry": False,
    "auto_model_routing": False,
    "task_type_model_routing": {},
    "parallel_fix_samples": 1,
    "context_budget_warning": False,
    "agent_teams": False,
    "worker_token_budget": 0,
    "notification_webhook": "",
}


def _run_git(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True
    )
    return proc.stdout


# ─── Harness ──────────────────────────────────────────────────────────────────


class RecoveryHarness:
    """Tmp world for one scenario: repo, claude dir, mock state, worker pool."""

    def __init__(self, tmp_path: Path, monkeypatch, task_queue, claude_dir: Path):
        self.tmp_path = tmp_path
        self.monkeypatch = monkeypatch
        self.tq = task_queue
        self.claude_dir = claude_dir
        self.repo = tmp_path / "repo"
        self.mock_state = tmp_path / "mock-state"
        self.gh_state = tmp_path / "gh-state"
        self.scripts_dir = tmp_path / "worker-scripts"
        self.scripts_dir.mkdir()
        self.pool = wmod.WorkerPool()

    # — mock scripting —

    def worker_script(self, turn: int, body: str) -> None:
        """Script the n-th worker-run call (cwd = the worker's worktree)."""
        path = self.scripts_dir / f"turn-{turn}.sh"
        path.write_text("#!/usr/bin/env bash\nset -eu\n" + body)
        self.monkeypatch.setenv(f"MOCK_CLAUDE_WORKER_SCRIPT_{turn}", str(path))

    def worker_prompts(self) -> list[str]:
        """Prompts of worker-run calls only, in call order."""
        files = sorted(
            self.mock_state.glob("prompt-*-worker.txt"),
            key=lambda p: int(p.name.split("-")[1]),
        )
        return [f.read_text() for f in files]

    def claude_call_kinds(self) -> list[str]:
        log = self.mock_state / "calls.log"
        return log.read_text().split() if log.exists() else []

    # — worker lifecycle —

    async def spawn(self, description: str, **task_kwargs):
        task = await self.tq.add(description, "sonnet", **task_kwargs)
        return await self.pool.start_worker(task, self.tq, self.repo, self.claude_dir)

    async def start_task(self, task: dict):
        return await self.pool.start_worker(task, self.tq, self.repo, self.claude_dir)

    async def finish(self, w):
        """Drive the terminal transition deterministically.

        Mirrors Worker.poll()'s exit handling but AWAITS _on_worker_done inline
        instead of letting poll() fire it as an untracked asyncio task — the
        e2e must observe requeue flags only after verify/commit/tests/oracle
        actually completed.
        """
        import asyncio

        await asyncio.wait_for(w.proc.wait(), timeout=120)
        if w._finished_at is None:
            w._finished_at = time.time()
        rc = w.proc.returncode
        w.status = "done" if rc == 0 else "failed"
        w.transition_reason = f"process_exited_rc_{rc}"
        if w.status == "failed" and w._log_path and w._log_path.exists():
            text = w._log_path.read_text(errors="replace")
            w.failure_context = wmod._truncate_output(text)
            err = wmod._classify_error(text, exit_code=rc)
            w._failure_classified = err
            w.failure_class = wmod._summarize_error(err)
        w._verify_triggered = True  # poll_all must not double-run _on_worker_done
        await w._on_worker_done()
        return w

    async def run_task_to_done(self, description: str, **task_kwargs):
        w = await self.spawn(description, **task_kwargs)
        await self.finish(w)
        await self.pool.poll_all(self.tq)
        return w

    async def pending_tasks(self) -> list[dict]:
        return [t for t in await self.tq.list() if t["status"] == "pending"]

    # — git assertions —

    def git_show(self, branch: str, path: str) -> str:
        return _run_git(["show", f"{branch}:{path}"], self.repo)

    def branch_subject(self, branch: str) -> str:
        return _run_git(["log", "-1", "--format=%s", branch], self.repo)


@pytest.fixture
def harness(tmp_path: Path, monkeypatch, task_queue, tmp_claude_dir) -> RecoveryHarness:
    # Tmp HOME: hermetic git identity AND Path.home()/.claude/scripts/committer.sh
    # resolves to nothing, so verify_and_commit takes the bare-git fallback path.
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text(GITCONFIG)
    monkeypatch.setenv("HOME", str(home))

    # PATH-front bin with the fixture mocks installed as `claude` / `gh`.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for src, name in ((FIXTURES / "mock-claude", "claude"), (FIXTURES / "mock-gh", "gh")):
        dst = bin_dir / name
        shutil.copy(src, dst)
        dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{bin_dir}:{__import__('os').environ['PATH']}")

    h = RecoveryHarness(tmp_path, monkeypatch, task_queue, tmp_claude_dir)
    h.mock_state.mkdir()
    h.gh_state.mkdir()
    monkeypatch.setenv("MOCK_CLAUDE_STATE_DIR", str(h.mock_state))
    monkeypatch.setenv("GH_STATE_DIR", str(h.gh_state))
    monkeypatch.delenv("MOCK_CLAUDE_ORACLE_MODE", raising=False)
    monkeypatch.delenv("CLADE_ALLOW_SECRETS", raising=False)

    for key, value in PINNED_SETTINGS.items():
        monkeypatch.setitem(config.GLOBAL_SETTINGS, key, value)

    # Keep tracer output + the global event bus inside tmp.
    monkeypatch.setattr(
        TracingService, "_instance", TracingService(base_dir=tmp_path / "traces")
    )
    monkeypatch.setattr(EventStream, "_global_bus_path", None)

    # Seed the toy project (green baseline: compute() == 42, no square yet).
    h.repo.mkdir()
    (h.repo / "tests").mkdir()
    (h.repo / ".claude").mkdir()
    (h.repo / "app.py").write_text(APP_PY)
    (h.repo / "tests" / "run_tests.py").write_text(RUN_TESTS_PY)
    (h.repo / ".claude" / "orchestrator.json").write_text(
        json.dumps({"test_cmd": "python3 tests/run_tests.py"})
    )
    _run_git(["init", "-q"], h.repo)
    _run_git(["add", "-A"], h.repo)
    _run_git(["commit", "-qm", "chore: seed toy project"], h.repo)
    return h


# ─── 1. Pre-push test failure → _test_requeue → adapted retry → success ──────


PLANT_BUGGY_SQUARE = """\
cat >> app.py <<'PYEOF'


def square(n):
    return n + n  # planted bug: should be n * n
PYEOF
echo "Added square() to app.py."
"""

PLANT_CLEAN_SQUARE = """\
cat >> app.py <<'PYEOF'


def square(n):
    return n * n
PYEOF
echo '```json'
echo '{"status": "done", "summary": "Added square() helper to app.py", "next_actions": [], "artifacts": ["app.py"]}'
echo '```'
"""


async def test_planted_test_failure_requeues_with_evidence_then_retry_succeeds(
    harness: RecoveryHarness,
) -> None:
    h = harness
    h.worker_script(1, PLANT_BUGGY_SQUARE)
    h.worker_script(2, PLANT_CLEAN_SQUARE)

    # Attempt 1: worker exits 0 with a planted bug. verify passes (mock says
    # VERIFIED_OK), the commit lands, then the pre-push test run inside
    # verify_and_commit fails → commit undone, _test_requeue raised.
    desc = "Add square(n) helper to app.py returning the square of n"
    w1 = await h.spawn(desc)
    await h.finish(w1)

    assert w1.verified is True            # haiku verify ran before the commit
    assert w1.auto_committed is False     # commit was undone after tests failed
    assert w1._test_requeue is True
    assert w1.failure_context is not None
    assert w1.failure_context.startswith("Pre-push tests failed")
    assert "PLANTED_BUG" in w1._test_requeue_reason
    assert "Project tests FAILED" in w1._test_requeue_reason

    # poll_all consumes the flag: retry task carries the test output as context.
    await h.pool.poll_all(h.tq)
    pending = await h.pending_tasks()
    assert len(pending) == 1
    retry = pending[0]
    assert "Previous attempt FAILED the project test suite" in retry["description"]
    assert "PLANTED_BUG" in retry["description"]
    assert "Project tests FAILED" in retry["description"]
    orig = await h.tq.get(w1.task_id)
    assert orig["failed_reason"].startswith("Pre-push tests failed")

    # Attempt 2: adapted retry (mock turn 2) lands the clean fix.
    w2 = await h.start_task(retry)
    await h.finish(w2)
    await h.pool.poll_all(h.tq)

    assert w2.auto_committed is True
    assert w2.verified is True
    assert w2._test_requeue is False
    assert w2.completion_summary == "Added square() helper to app.py"
    branch = f"orchestrator/task-{w2.task_id}"
    assert "return n * n" in h.git_show(branch, "app.py")
    # The retry's task description ends with "Fix the failures …", so the
    # commit-type classifier (config._infer_commit_type) lands it as `fix:` —
    # a retry that repairs a failing suite is a fix, not a feat. (A first-pass
    # "Add square(n)" attempt with no failure evidence commits as `feat:`.)
    assert h.branch_subject(branch).startswith("fix: add square(n) helper")
    assert not await h.pending_tasks()  # chain converged — nothing requeued

    # The retry worker actually SAW the failure evidence in its task file.
    prompts = h.worker_prompts()
    assert len(prompts) == 2
    assert "Previous attempt FAILED the project test suite" in prompts[1]
    assert "PLANTED_BUG" in prompts[1]
    # Two worker turns + two verify calls; the oracle never ran (auto_oracle off).
    kinds = h.claude_call_kinds()
    assert kinds.count("worker") == 2
    assert kinds.count("verify") == 2
    assert "oracle" not in kinds
    assert (h.mock_state / "worker-turns").read_text().strip() == "2"


# ─── 2./3. Oracle infra error → 'unreviewed' (never a silent approval) ────────


WRITE_FEATURE = """\
cat > feature.py <<'PYEOF'
WIDGET_NOTE = "recovery e2e"
PYEOF
echo '```json'
echo '{"status": "done", "summary": "Created feature.py", "next_actions": [], "artifacts": ["feature.py"]}'
echo '```'
"""


async def test_oracle_infra_error_tags_commit_unreviewed(
    harness: RecoveryHarness, monkeypatch
) -> None:
    h = harness
    monkeypatch.setitem(config.GLOBAL_SETTINGS, "auto_oracle", True)
    monkeypatch.setenv("MOCK_CLAUDE_ORACLE_MODE", "garbage")
    h.worker_script(1, WRITE_FEATURE)

    w = await h.run_task_to_done("Create feature.py exposing WIDGET_NOTE")

    # Fail-open but visibly unreviewed — the commit survives with the tag.
    assert w.oracle_result == "unreviewed"
    assert "infra error" in w.oracle_reason
    assert w.auto_committed is True
    branch = f"orchestrator/task-{w.task_id}"
    assert "WIDGET_NOTE" in h.git_show(branch, "feature.py")
    # Streak recorded but below threshold → no escalation yet.
    assert worker_review_real._oracle_infra_streaks.get(str(h.claude_dir)) == 1
    assert not (h.claude_dir / "blockers.md").exists()
    assert not await h.pending_tasks()  # unreviewed ≠ rejected: no requeue


async def test_oracle_infra_streak_escalates_to_blockers(
    harness: RecoveryHarness, monkeypatch
) -> None:
    h = harness
    monkeypatch.setitem(config.GLOBAL_SETTINGS, "auto_oracle", True)
    monkeypatch.setenv("MOCK_CLAUDE_ORACLE_MODE", "garbage")
    h.worker_script(1, WRITE_FEATURE)
    # Two prior infra errors this session — this run crosses the threshold.
    monkeypatch.setitem(
        worker_review_real._oracle_infra_streaks, str(h.claude_dir), 2
    )

    w = await h.run_task_to_done("Create feature.py exposing WIDGET_NOTE")

    assert w.oracle_result == "unreviewed"
    assert w.auto_committed is True  # escalation must never break the commit flow
    assert worker_review_real._oracle_infra_streaks.get(str(h.claude_dir)) == 3
    blockers = h.claude_dir / "blockers.md"
    assert blockers.exists()
    text = blockers.read_text()
    assert "Oracle review infrastructure failing" in text
    assert "3 consecutive infra errors" in text


# ─── 4. Oracle rejection → requeue with reason → approved retry ───────────────


async def test_oracle_rejection_requeues_then_adapted_retry_approved(
    harness: RecoveryHarness, monkeypatch
) -> None:
    h = harness
    monkeypatch.setitem(config.GLOBAL_SETTINGS, "auto_oracle", True)
    monkeypatch.setenv("MOCK_CLAUDE_ORACLE_MODE", "reject")
    h.worker_script(1, WRITE_FEATURE)
    h.worker_script(2, WRITE_FEATURE)

    w1 = await h.spawn("Create feature.py exposing WIDGET_NOTE")
    await h.finish(w1)

    assert w1.oracle_result == "rejected"
    assert "PLANTED_ORACLE_REJECTION" in w1.oracle_reason
    assert w1.auto_committed is False  # rejected commit was undone
    # A real (parsed) verdict clears the infra streak.
    assert str(h.claude_dir) not in worker_review_real._oracle_infra_streaks

    await h.pool.poll_all(h.tq)
    pending = await h.pending_tasks()
    assert len(pending) == 1
    retry = pending[0]
    assert "REJECTED by oracle review" in retry["description"]
    assert "PLANTED_ORACLE_REJECTION" in retry["description"]

    # Oracle healthy again → the adapted retry is approved and pushed through.
    monkeypatch.setenv("MOCK_CLAUDE_ORACLE_MODE", "approve")
    w2 = await h.start_task(retry)
    await h.finish(w2)
    await h.pool.poll_all(h.tq)

    assert w2.oracle_result == "approved"
    assert w2.auto_committed is True
    branch = f"orchestrator/task-{w2.task_id}"
    assert "WIDGET_NOTE" in h.git_show(branch, "feature.py")
    assert not await h.pending_tasks()


# ─── 5. Classified subprocess failure → persisted reason, no requeue ──────────


async def test_classified_subprocess_failure_persists_reason_without_requeue(
    harness: RecoveryHarness,
) -> None:
    h = harness
    h.worker_script(
        1,
        'echo "Error: 429 Too Many Requests - rate limit exceeded while calling model"\n'
        "exit 1\n",
    )

    w = await h.run_task_to_done("Summarize the release readiness")

    assert w.status == "failed"
    assert w.auto_committed is False
    assert w.failure_class is not None
    assert "rate_limit" in w.failure_class
    task = await h.tq.get(w.task_id)
    assert task["status"] == "failed"
    assert "rate_limit" in task["failed_reason"]
    # auto_classify_retry is off → a plain failure must NOT spawn retries.
    assert not await h.pending_tasks()


# ─── 6. Ownership violation → discard + requeue with globs → adapted retry ────


async def test_ownership_violation_discards_and_requeues_with_globs(
    harness: RecoveryHarness,
) -> None:
    h = harness
    h.worker_script(
        1,
        'echo "rogue change" > rogue.py\necho "Wrote rogue.py at repo root."\n',
    )
    h.worker_script(
        2,
        "mkdir -p src\n"
        'echo "UTIL = 1" > src/util.py\n'
        'echo "Wrote src/util.py."\n',
    )

    w1 = await h.spawn(
        "Provide a util module under the src directory", own_files=["src/**"]
    )
    await h.finish(w1)

    assert w1._ownership_violation is True
    assert w1.auto_committed is False
    assert w1.verified is False  # verify never ran — changes were discarded first

    await h.pool.poll_all(h.tq)
    pending = await h.pending_tasks()
    assert len(pending) == 1
    retry = pending[0]
    assert "file ownership violation" in retry["description"]
    assert "rogue.py" in retry["description"]
    assert retry["own_files"] == ["src/**"]  # globs survive the requeue
    orig = await h.tq.get(w1.task_id)
    assert orig["failed_reason"].startswith("Ownership violation")

    w2 = await h.start_task(retry)
    await h.finish(w2)
    await h.pool.poll_all(h.tq)

    assert w2.auto_committed is True
    branch = f"orchestrator/task-{w2.task_id}"
    assert "UTIL = 1" in h.git_show(branch, "src/util.py")
    assert not await h.pending_tasks()


# ─── 7. mock-gh: CI failure pre-hydrated into the task; passing rerun drops it ─


HYDRATION_DESC = (
    "Investigate the widget CI failure at "
    "https://github.com/acme/widget/actions/runs/4242 — context: issue "
    "acme/widget#7 and https://github.com/acme/widget/pull/9 — then append "
    "what you learned to notes.md"
)


async def test_ci_failure_prehydrated_then_passing_run_drops_block(
    harness: RecoveryHarness,
) -> None:
    h = harness
    # Seed .gh-state: issue JSON, PR JSON, and call-1 CI failure log. No call-2
    # log file = the rerun PASSES (--log-failed prints nothing).
    (h.gh_state / "issue-7.json").write_text(json.dumps({
        "title": "Widget crashes on empty input",
        "body": "Steps: call the widget with []",
        "state": "OPEN",
        "labels": [{"name": "ci"}],
    }))
    (h.gh_state / "pr-9.json").write_text(json.dumps({
        "title": "Bump widget pipeline",
        "body": "WIP",
        "state": "OPEN",
        "additions": 3,
        "deletions": 1,
    }))
    (h.gh_state / "run-4242.1.log").write_text(
        "widget-ci  pytest  FAILED tests/test_widget.py::test_render - "
        "ImportError: PLANTED_CI_FAILURE\n##[error]Process completed with exit code 1.\n"
    )
    h.worker_script(1, 'echo "investigated" >> notes.md\necho "Appended notes."\n')

    # Worker 1: failing CI run is pre-hydrated into the task file.
    w1 = await h.run_task_to_done(HYDRATION_DESC)
    assert w1.auto_committed is True
    task_file_1 = (h.claude_dir / f"task-{w1.id}.md").read_text()
    assert "Pre-hydrated Issue acme/widget#7" in task_file_1
    assert "Widget crashes on empty input" in task_file_1
    assert "Pre-hydrated PR acme/widget#9" in task_file_1
    assert "PLANTED_CI_FAILURE" in task_file_1

    # Worker 2 (same refs): the CI run now passes — the failure block is gone,
    # while the static issue/PR context is still hydrated.
    w2 = await h.run_task_to_done(HYDRATION_DESC)
    assert w2.auto_committed is True
    task_file_2 = (h.claude_dir / f"task-{w2.id}.md").read_text()
    assert "Pre-hydrated Issue acme/widget#7" in task_file_2
    assert "PLANTED_CI_FAILURE" not in task_file_2

    calls = (h.gh_state / "calls.log").read_text().splitlines()
    run_calls = [c for c in calls if c.startswith("run view 4242")]
    assert len(run_calls) == 2
    assert (h.gh_state / "run-4242.calls").read_text().strip() == "2"
