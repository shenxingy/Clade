"""Tests for the orphan-process reaping fix (Round-4, Guillermo Rauch).

Prior bug: workers spawn via setsid (survive an orchestrator restart), but
_recover_orphaned_tasks() only relabeled DB rows to 'interrupted' without
checking whether the underlying OS process group was still alive — a real
orphaned `claude -p` process kept running, able to race a fresh retry into
the same branch/worktree. Fix: persist pgid at spawn time; on recovery,
check-and-killpg the persisted pgid (best-effort, PID-reuse-guarded) BEFORE
marking the row interrupted.

Uses REAL detached subprocesses (via os.setsid) so the kill mechanics are
verified against actual OS process groups, not mocked. `exec -a NAME` renames
argv[0] so a plain `sleep` binary can stand in for a "claude-like" process
without invoking the real Claude CLI.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time

import config as cfg


# ─── Test doubles: real detached processes ────────────────────────────────────

_SPAWNED: list[subprocess.Popen] = []


def _spawn_detached(argv0: str, seconds: float = 20) -> tuple[subprocess.Popen, int]:
    """A real, detached (own process group) subprocess whose /proc cmdline
    starts with `argv0` — a cheap stand-in for 'looks like a claude worker'
    without running the real CLI. Tracked for guaranteed teardown."""
    proc = subprocess.Popen(
        ["bash", "-c", f"exec -a {argv0} sleep {seconds}"],
        preexec_fn=os.setsid,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    _SPAWNED.append(proc)
    time.sleep(0.15)  # let exec -a replace argv0 before any /proc read
    return proc, os.getpgid(proc.pid)


def _is_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)  # signal 0: existence check only, no actual kill
        return True
    except ProcessLookupError:
        return False


def teardown_module(module):
    for proc in _SPAWNED:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            pass
        try:
            proc.wait(timeout=2)
        except Exception:
            pass


# ─── _pgid_alive_and_claude_like ───────────────────────────────────────────────


def test_claude_like_cmdline_returns_true():
    proc, pgid = _spawn_detached("claude-worker-test")
    try:
        assert cfg._pgid_alive_and_claude_like(pgid) is True
    finally:
        os.killpg(pgid, signal.SIGKILL)
        proc.wait(timeout=2)


def test_non_claude_cmdline_returns_false():
    # PID-reuse safety net: a live process that does NOT look like a claude
    # worker must not be silently killed just because its number was recycled.
    proc, pgid = _spawn_detached("totally-unrelated-process")
    try:
        assert cfg._pgid_alive_and_claude_like(pgid) is False
    finally:
        os.killpg(pgid, signal.SIGKILL)
        proc.wait(timeout=2)


class TestWithoutProc:
    """The no-/proc branch, forced on whatever platform is running.

    These three assertions are the only thing standing between a macOS
    developer and orphan recovery killpg-ing a recycled pgid that belongs to
    somebody else. They cannot be left to run only where /proc is absent: CI is
    Linux-only, so the branch that actually executes on the primary development
    machine would otherwise never be exercised by any gate. Forcing the branch
    here means Linux CI protects the macOS path.
    """

    @staticmethod
    def _no_proc(monkeypatch):
        monkeypatch.setattr(cfg.Path, "exists", lambda self: False)

    def test_claude_like_process_is_still_recognised(self, monkeypatch):
        proc, pgid = _spawn_detached("claude-worker-test")
        try:
            self._no_proc(monkeypatch)
            assert cfg._pgid_alive_and_claude_like(pgid) is True
        finally:
            os.killpg(pgid, signal.SIGKILL)
            proc.wait(timeout=2)

    def test_unrelated_process_is_protected(self, monkeypatch):
        # The whole point: without a /proc reader this used to return True for
        # every pgid, so the PID-reuse net did not exist off Linux.
        proc, pgid = _spawn_detached("totally-unrelated-process")
        try:
            self._no_proc(monkeypatch)
            assert cfg._pgid_alive_and_claude_like(pgid) is False
        finally:
            os.killpg(pgid, signal.SIGKILL)
            proc.wait(timeout=2)

    def test_dead_pgid_still_fails_open(self, monkeypatch):
        self._no_proc(monkeypatch)
        assert cfg._pgid_alive_and_claude_like(999_999_999) is True

    def test_unusable_ps_fails_open(self, monkeypatch):
        # Fail-open is the documented contract: a machine where the check
        # cannot run must still reap real orphans rather than never reap.
        self._no_proc(monkeypatch)

        def _boom(*a, **k):
            raise OSError("no ps on this box")

        monkeypatch.setattr(cfg.subprocess, "run", _boom)
        assert cfg._pgid_alive_and_claude_like(4242) is True


def test_nonexistent_pgid_returns_true():
    # No /proc entry (already exited, or non-Linux) — proceed, matching the
    # original unconditional-kill behavior; killpg's own ProcessLookupError
    # handles the "already gone" case harmlessly.
    assert cfg._pgid_alive_and_claude_like(999_999_999) is True


# ─── _recover_orphaned_tasks ────────────────────────────────────────────────────


async def test_kills_live_claude_like_pgid_before_marking_interrupted(task_queue):
    proc, pgid = _spawn_detached("claude-worker-test")
    task = await task_queue.add("test task", "haiku")
    await task_queue.update(task["id"], status="running", pgid=pgid)

    count = await cfg._recover_orphaned_tasks(task_queue)

    assert count == 1
    row = await task_queue.get(task["id"])
    assert row["status"] == "interrupted"
    # wait() both waits for AND reaps the child — checking killpg(pgid, 0)
    # before reaping can see a lingering zombie entry and false-report "alive".
    proc.wait(timeout=2)
    assert _is_alive(pgid) is False


async def test_skips_kill_for_non_claude_like_pgid(task_queue):
    # Safety net: even though this pgid is "orphaned" per the DB row, its
    # cmdline doesn't look like a claude worker — must not be killed (could be
    # an unrelated process that inherited a recycled PID).
    proc, pgid = _spawn_detached("totally-unrelated-process")
    task = await task_queue.add("test task", "haiku")
    await task_queue.update(task["id"], status="running", pgid=pgid)

    count = await cfg._recover_orphaned_tasks(task_queue)

    assert count == 1
    row = await task_queue.get(task["id"])
    assert row["status"] == "interrupted"  # still marked — DB relabel unaffected
    time.sleep(0.2)
    assert _is_alive(pgid) is True  # but the process itself survives
    os.killpg(pgid, signal.SIGKILL)
    proc.wait(timeout=2)


async def test_already_dead_pgid_is_a_noop_not_a_crash(task_queue):
    proc, pgid = _spawn_detached("claude-worker-test", seconds=1)
    proc.wait(timeout=3)  # let it exit naturally first
    task = await task_queue.add("test task", "haiku")
    await task_queue.update(task["id"], status="running", pgid=pgid)

    count = await cfg._recover_orphaned_tasks(task_queue)  # must not raise

    assert count == 1
    row = await task_queue.get(task["id"])
    assert row["status"] == "interrupted"


async def test_no_pgid_still_marks_interrupted(task_queue):
    # Tasks predating this migration (or ones that never got a pgid persisted)
    # must still be recovered — just without a process to kill.
    task = await task_queue.add("test task", "haiku")
    await task_queue.update(task["id"], status="starting")

    count = await cfg._recover_orphaned_tasks(task_queue)

    assert count == 1
    row = await task_queue.get(task["id"])
    assert row["status"] == "interrupted"


async def test_non_running_tasks_are_untouched(task_queue):
    task = await task_queue.add("test task", "haiku")
    await task_queue.update(task["id"], status="done")

    count = await cfg._recover_orphaned_tasks(task_queue)

    assert count == 0
    row = await task_queue.get(task["id"])
    assert row["status"] == "done"
