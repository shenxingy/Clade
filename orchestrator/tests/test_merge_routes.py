"""Tests for merge_all_done: structured PR bodies (controversial + felixrieseberg)
and the auto-merge / do-not-merge flow (domdomegg).

routes.tasks is imported under the conftest mocks (worker / worker_review /
worker_tldr are MagicMocks), so no real Claude CLI or gh calls happen here —
subprocess entry points are replaced via the AsyncioProxy pattern from
test_oracle_integrity.py.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import routes.tasks as rt


# ─── Test doubles ─────────────────────────────────────────────────────────────


class FakeProc:
    """Stand-in for an asyncio subprocess."""

    def __init__(self, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self.killed = False

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True


class AsyncioProxy:
    """Proxy for the asyncio module that lets tests override subprocess entry
    points without mutating the global asyncio module."""

    def __init__(self, **overrides):
        self._overrides = overrides

    def __getattr__(self, name):
        if name in self._overrides:
            return self._overrides[name]
        return getattr(asyncio, name)


def _shell_dispatcher(responses: list[tuple[str, FakeProc]]):
    """Fake create_subprocess_shell: first substring match in `responses` wins.
    Returns (calls, fake_shell) — calls records every command string."""
    calls: list[str] = []

    async def _fake_shell(cmd, **kwargs):
        calls.append(cmd)
        for needle, proc in responses:
            if needle in cmd:
                return proc
        return FakeProc(stderr=b"unexpected command", returncode=1)

    return calls, _fake_shell


class FakeWorker:
    def __init__(self, **kw):
        self.id = kw.get("id", 1)
        self.task_id = kw.get("task_id", "t1")
        self.status = kw.get("status", "done")
        self.auto_pushed = kw.get("auto_pushed", True)
        self.pr_url = kw.get("pr_url")
        self.pr_merged = False
        self.branch_name = kw.get("branch_name", "orchestrator/task-t1")
        self.description = kw.get("description", "feat: add widget\n\nDetails of the widget.")
        self.completion_summary = kw.get("completion_summary")
        self.oracle_result = kw.get("oracle_result")
        self.oracle_reason = kw.get("oracle_reason")
        self.test_evidence = kw.get("test_evidence", "")
        self._log_path = None


def _fake_session(workers: list[FakeWorker], tmp_path: Path):
    return SimpleNamespace(
        worker_pool=SimpleNamespace(all=lambda: workers),
        project_dir=tmp_path,
    )


PR_URL = b"https://github.com/o/r/pull/7\n"


# ─── _build_pr_body / _pr_title ───────────────────────────────────────────────


class TestBuildPrBody:
    def test_full_worker_includes_all_sections(self):
        w = FakeWorker(
            completion_summary="Added the widget and wired it up.",
            oracle_result="approved",
            oracle_reason="all criteria satisfied",
            test_evidence="Project tests PASSED.\n3 passed in 0.2s",
        )
        body = rt._build_pr_body(w)
        assert "## Task" in body and "feat: add widget" in body
        assert "## Completion Summary" in body and "wired it up" in body
        assert "**Oracle review:** approved — all criteria satisfied" in body
        assert "## Test Evidence (pre-push)" in body and "3 passed" in body
        assert "Authored by Clade worker 1 (task t1)" in body

    def test_minimal_worker_states_missing_evidence(self):
        w = FakeWorker(description="")
        body = rt._build_pr_body(w)
        assert "(no task description)" in body
        assert "**Oracle review:** not run" in body
        assert "no pre-push test run recorded" in body
        assert "Completion Summary" not in body

    def test_oracle_reason_truncated(self):
        w = FakeWorker(oracle_result="rejected", oracle_reason="x" * 1000)
        body = rt._build_pr_body(w)
        assert "x" * 400 in body
        assert "x" * 401 not in body

    def test_pr_title_first_line_capped(self):
        assert rt._pr_title("fix: thing\nmore lines") == "fix: thing"
        assert rt._pr_title("a" * 100) == "a" * 72
        assert rt._pr_title("") == "Orchestrator task"
        assert rt._pr_title(None) == "Orchestrator task"


# ─── merge_all_done: PR creation ─────────────────────────────────────────────


class TestMergeAllDonePrCreate:
    async def test_pr_created_with_structured_body_not_fill(self, tmp_path, monkeypatch):
        w = FakeWorker(oracle_result="approved", test_evidence="Project tests PASSED.")
        calls, fake_shell = _shell_dispatcher([("gh pr create", FakeProc(PR_URL))])
        monkeypatch.setattr(rt, "asyncio", AsyncioProxy(create_subprocess_shell=fake_shell))
        monkeypatch.setitem(rt.GLOBAL_SETTINGS, "auto_review", False)
        monkeypatch.setitem(rt.GLOBAL_SETTINGS, "auto_merge", False)

        out = await rt.merge_all_done(s=_fake_session([w], tmp_path))

        assert out["created"] == 1
        assert w.pr_url == "https://github.com/o/r/pull/7"
        create_cmd = next(c for c in calls if "gh pr create" in c)
        assert "--fill" not in create_cmd
        assert "--title" in create_cmd and "--body" in create_cmd
        assert "Oracle review:" in create_cmd  # body actually carries the verdict

    async def test_pr_create_failure_is_skipped_not_raised(self, tmp_path, monkeypatch):
        w = FakeWorker()
        calls, fake_shell = _shell_dispatcher(
            [("gh pr create", FakeProc(stderr=b"gh: not logged in", returncode=1))]
        )
        monkeypatch.setattr(rt, "asyncio", AsyncioProxy(create_subprocess_shell=fake_shell))
        monkeypatch.setitem(rt.GLOBAL_SETTINGS, "auto_review", False)
        monkeypatch.setitem(rt.GLOBAL_SETTINGS, "auto_merge", True)

        out = await rt.merge_all_done(s=_fake_session([w], tmp_path))

        assert out["created"] == 0
        assert out["results"][0]["error"]
        assert w.pr_url is None
