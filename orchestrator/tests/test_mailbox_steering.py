"""Mid-flight worker steering (orchestrator side).

send_task_message persists to the worker_messages table (at-spawn channel,
durable) and *additionally* writes .claude/worker-inbox-<task_id>.md into the
running worker's project dir (mid-flight channel, drained by
configs/hooks/mailbox-drain.sh — covered by tests/test-mailbox-drain.sh).
worker_taskfile._clear_stale_inbox removes leftover inbox files at spawn so
the at-spawn injection never double-delivers.

routes.tasks is imported under the conftest mocks (worker / worker_review /
worker_tldr are MagicMocks), so no real Claude CLI or gh calls happen here.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import routes.tasks as rt
from worker_taskfile import _clear_stale_inbox


# ─── Test doubles ─────────────────────────────────────────────────────────────


def _fake_worker(project_dir: Path, task_id: str = "t1", status: str = "running"):
    return SimpleNamespace(task_id=task_id, status=status, _project_dir=project_dir)


def _fake_session(task_queue, workers):
    return SimpleNamespace(
        task_queue=task_queue,
        worker_pool=SimpleNamespace(workers={i: w for i, w in enumerate(workers)}),
    )


def _inbox(project_dir: Path, task_id: str = "t1") -> Path:
    return project_dir / ".claude" / f"worker-inbox-{task_id}.md"


# ─── send_task_message: mid-flight inbox write ────────────────────────────────


class TestSendMessageMidflight:
    async def test_running_worker_gets_inbox_file(self, task_queue, tmp_path):
        w = _fake_worker(tmp_path)
        s = _fake_session(task_queue, [w])

        msg = await rt.send_task_message("t1", {"content": "steer left"}, s=s)

        assert msg["midflight"] is True
        text = _inbox(tmp_path).read_text()
        assert "steer left" in text
        assert "[from supervisor]" in text
        # DB row persisted too — at-spawn channel remains the durable fallback
        rows = await task_queue.get_messages("t1", unread_only=True)
        assert len(rows) == 1 and rows[0]["content"] == "steer left"

    async def test_from_task_id_labels_sender(self, task_queue, tmp_path):
        w = _fake_worker(tmp_path)
        s = _fake_session(task_queue, [w])

        msg = await rt.send_task_message(
            "t1", {"content": "branch is stale", "from_task_id": "t9"}, s=s
        )

        assert msg["midflight"] is True
        assert "[from t9] branch is stale" in _inbox(tmp_path).read_text()

    async def test_second_message_appends(self, task_queue, tmp_path):
        w = _fake_worker(tmp_path)
        s = _fake_session(task_queue, [w])

        await rt.send_task_message("t1", {"content": "first nudge"}, s=s)
        await rt.send_task_message("t1", {"content": "second nudge"}, s=s)

        text = _inbox(tmp_path).read_text()
        assert "first nudge" in text and "second nudge" in text
        assert text.index("first nudge") < text.index("second nudge")

    async def test_no_running_worker_skips_file(self, task_queue, tmp_path):
        s = _fake_session(task_queue, [])

        msg = await rt.send_task_message("t1", {"content": "into the void"}, s=s)

        assert msg["midflight"] is False
        assert not _inbox(tmp_path).exists()
        # The message still lands in the DB for the next spawn
        rows = await task_queue.get_messages("t1", unread_only=True)
        assert len(rows) == 1

    async def test_starting_worker_is_not_midflight(self, task_queue, tmp_path):
        # While status is "starting", build_task_file may still inject the DB
        # row at spawn — writing the file too would risk double delivery.
        w = _fake_worker(tmp_path, status="starting")
        s = _fake_session(task_queue, [w])

        msg = await rt.send_task_message("t1", {"content": "too early"}, s=s)

        assert msg["midflight"] is False
        assert not _inbox(tmp_path).exists()

    async def test_other_tasks_worker_not_targeted(self, task_queue, tmp_path):
        w = _fake_worker(tmp_path, task_id="other-task")
        s = _fake_session(task_queue, [w])

        msg = await rt.send_task_message("t1", {"content": "wrong door"}, s=s)

        assert msg["midflight"] is False
        assert not _inbox(tmp_path, "other-task").exists()
        assert not _inbox(tmp_path, "t1").exists()

    async def test_empty_content_rejected(self, task_queue, tmp_path):
        w = _fake_worker(tmp_path)
        s = _fake_session(task_queue, [w])

        with pytest.raises(HTTPException) as exc:
            await rt.send_task_message("t1", {"content": "   "}, s=s)
        assert exc.value.status_code == 400
        assert not _inbox(tmp_path).exists()

    async def test_unwritable_project_dir_fails_soft(self, task_queue, tmp_path):
        # Worker's project dir vanished mid-flight (worktree cleanup race):
        # the request must still succeed — the DB row is the durable channel.
        w = _fake_worker(tmp_path / "gone", status="running")
        (tmp_path / "gone").write_text("not a directory")  # mkdir will fail

        s = _fake_session(task_queue, [w])
        msg = await rt.send_task_message("t1", {"content": "still recorded"}, s=s)

        assert msg["midflight"] is False
        rows = await task_queue.get_messages("t1", unread_only=True)
        assert len(rows) == 1


# ─── _write_worker_inbox unit behavior ────────────────────────────────────────


class TestWriteWorkerInbox:
    def test_no_tmp_file_left_behind(self, tmp_path):
        pool = SimpleNamespace(workers={0: _fake_worker(tmp_path)})

        assert rt._write_worker_inbox(pool, "t1", "clean write", None) is True

        leftovers = [p for p in (tmp_path / ".claude").iterdir() if ".tmp-" in p.name]
        assert leftovers == []

    def test_filename_uses_worker_task_id_not_url_param(self, tmp_path):
        # Defense in depth: even if a hostile task_id matched a worker, the
        # filename comes from the pool-sourced worker.task_id.
        w = _fake_worker(tmp_path, task_id="safe-id")
        pool = SimpleNamespace(workers={0: w})

        assert rt._write_worker_inbox(pool, "safe-id", "payload", None) is True
        assert _inbox(tmp_path, "safe-id").exists()

    def test_broken_pool_returns_false(self, tmp_path):
        pool = SimpleNamespace()  # no .workers attribute at all
        assert rt._write_worker_inbox(pool, "t1", "x", None) is False


# ─── Spawn-time stale-inbox cleanup ───────────────────────────────────────────


class TestClearStaleInbox:
    def test_removes_stale_file(self, tmp_path):
        w = _fake_worker(tmp_path)
        inbox = _inbox(tmp_path)
        inbox.parent.mkdir(parents=True)
        inbox.write_text("[from supervisor] never drained\n")

        _clear_stale_inbox(w)

        assert not inbox.exists()

    def test_missing_file_is_noop(self, tmp_path):
        _clear_stale_inbox(_fake_worker(tmp_path))  # no .claude dir at all

    def test_only_own_task_inbox_removed(self, tmp_path):
        w = _fake_worker(tmp_path, task_id="t1")
        other = _inbox(tmp_path, "t2")
        other.parent.mkdir(parents=True)
        other.write_text("for someone else\n")

        _clear_stale_inbox(w)

        assert other.exists()

    def test_oserror_swallowed(self, tmp_path):
        # _project_dir pointing at a file makes the path lookup blow up with
        # NotADirectoryError (an OSError) — must not propagate into spawn.
        bogus = tmp_path / "file"
        bogus.write_text("x")
        _clear_stale_inbox(_fake_worker(bogus))
