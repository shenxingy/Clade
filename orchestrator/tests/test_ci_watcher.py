"""Tests for task_factory.ci_watcher — jobs-payload parsing + fail-open detail fetch.

Pure helpers are driven with fixture JSON; the async fetcher is exercised with
duck-typed stub clients so no network or httpx mocking is needed.
"""

import asyncio
import os
import subprocess

from task_factory import ci_watcher
from task_factory.ci_watcher import (
    _GUARDRAILS,
    _fetch_failure_details,
    _git_remote_url,
    _log_tail,
    _summarize_failed_jobs,
    check_ci_failures,
)

# ─── Fixture JSON (shape of /repos/{o}/{r}/actions/runs/{id}/jobs) ────────────

JOBS_ONE_FAILED = [
    {
        "id": 111,
        "name": "pytest",
        "conclusion": "failure",
        "steps": [
            {"name": "Set up job", "conclusion": "success"},
            {"name": "Run tests", "conclusion": "failure"},
        ],
    },
    {"id": 222, "name": "lint", "conclusion": "success", "steps": []},
]

JOBS_TWO_FAILED = [
    {"id": 1, "name": "build", "conclusion": "failure", "steps": []},
    {
        "id": 2,
        "name": "deploy",
        "conclusion": "failure",
        "steps": [{"name": "Push image", "conclusion": "failure"}],
    },
]


# ─── _summarize_failed_jobs ───────────────────────────────────────────────────

class TestSummarizeFailedJobs:
    def test_failed_job_and_step_named(self):
        summary, job_id = _summarize_failed_jobs(JOBS_ONE_FAILED)
        assert "pytest" in summary
        assert "Run tests" in summary
        assert "Set up job" not in summary  # successful steps excluded
        assert "lint" not in summary  # successful jobs excluded
        assert job_id == 111

    def test_multiple_failed_jobs_listed(self):
        summary, job_id = _summarize_failed_jobs(JOBS_TWO_FAILED)
        assert "build" in summary
        assert "deploy" in summary
        assert "Push image" in summary
        assert job_id == 1  # first failed job's id wins (its log gets fetched)

    def test_no_failed_jobs(self):
        jobs = [{"id": 9, "name": "ok", "conclusion": "success", "steps": []}]
        assert _summarize_failed_jobs(jobs) == ("", None)

    def test_empty_payload(self):
        assert _summarize_failed_jobs([]) == ("", None)

    def test_missing_steps_key(self):
        summary, job_id = _summarize_failed_jobs(
            [{"id": 5, "name": "nostep", "conclusion": "failure"}]
        )
        assert "nostep" in summary
        assert job_id == 5

    def test_steps_none(self):
        summary, job_id = _summarize_failed_jobs(
            [{"id": 6, "name": "nullstep", "conclusion": "failure", "steps": None}]
        )
        assert "nullstep" in summary
        assert job_id == 6

    def test_non_dict_entries_ignored(self):
        summary, job_id = _summarize_failed_jobs(["garbage", None, 42])
        assert summary == ""
        assert job_id is None

    def test_non_int_job_id_returns_none(self):
        summary, job_id = _summarize_failed_jobs(
            [{"id": "not-an-int", "name": "weird", "conclusion": "failure"}]
        )
        assert "weird" in summary
        assert job_id is None

    def test_caps_at_five_jobs(self):
        jobs = [
            {"id": i, "name": f"job-{i}", "conclusion": "failure"} for i in range(8)
        ]
        summary, _ = _summarize_failed_jobs(jobs)
        assert "job-4" in summary
        assert "job-7" not in summary


# ─── _log_tail ────────────────────────────────────────────────────────────────

class TestLogTail:
    def test_empty(self):
        assert _log_tail("") == ""

    def test_short_log_unchanged(self):
        assert _log_tail("a\nb\nc", 40) == "a\nb\nc"

    def test_long_log_tailed(self):
        text = "\n".join(f"L{i}" for i in range(100))
        tail = _log_tail(text, 40)
        lines = tail.splitlines()
        assert len(lines) == 40
        assert lines[0] == "L60"
        assert lines[-1] == "L99"


# ─── _fetch_failure_details (duck-typed stub clients, no network) ─────────────

class _StubResp:
    def __init__(self, json_data=None, text=""):
        self._json = json_data
        self.text = text

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


class _StubClient:
    """Returns jobs payload for the /jobs URL and log text for the /logs URL."""

    def __init__(self, jobs, log_text="", log_error=False):
        self._jobs = jobs
        self._log_text = log_text
        self._log_error = log_error

    async def get(self, url, **kwargs):
        if url.endswith("/jobs"):
            return _StubResp(json_data={"jobs": self._jobs})
        if self._log_error:
            raise RuntimeError("log fetch failed")
        return _StubResp(text=self._log_text)


class _BoomClient:
    async def get(self, *args, **kwargs):
        raise RuntimeError("network down")


class TestFetchFailureDetails:
    async def test_details_include_steps_and_log_tail(self):
        client = _StubClient(JOBS_ONE_FAILED, log_text="line1\nline2\nFAILED here")
        out = await _fetch_failure_details(client, "o", "r", 1, {})
        assert "pytest" in out
        assert "Run tests" in out
        assert "FAILED here" in out
        assert "```" in out  # log tail is fenced

    async def test_jobs_fetch_failure_is_fail_open(self):
        out = await _fetch_failure_details(_BoomClient(), "o", "r", 1, {})
        assert out == ""

    async def test_log_fetch_failure_keeps_job_summary(self):
        client = _StubClient(JOBS_ONE_FAILED, log_error=True)
        out = await _fetch_failure_details(client, "o", "r", 1, {})
        assert "pytest" in out  # summary survives the log-fetch failure
        assert "```" not in out  # but no fenced tail

    async def test_no_failed_jobs_returns_empty(self):
        client = _StubClient([{"id": 1, "name": "ok", "conclusion": "success"}])
        out = await _fetch_failure_details(client, "o", "r", 1, {})
        assert out == ""


# ─── guardrails text ──────────────────────────────────────────────────────────

class TestGuardrails:
    def test_both_bad_fix_guardrails_present(self):
        assert "CI infrastructure" in _GUARDRAILS
        assert "downgrading or pinning dependencies" in _GUARDRAILS


# ─── _git_remote_url (bounded, off the shared event loop) ────────────────────

def _git(*args: str, cwd) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True,
                   capture_output=True, text=True, timeout=30)


class _StuckProc:
    """A spawned child that never finishes — communicate() blocks forever."""

    def __init__(self) -> None:
        self.killed = False
        self.returncode = None

    async def communicate(self):
        if self.killed:
            return b"", b""
        await asyncio.Event().wait()  # never returns

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class TestGitRemoteUrl:
    async def test_reads_origin_from_a_real_repo(self, tmp_path):
        _git("init", "-q", str(tmp_path), cwd=tmp_path.parent)
        _git("remote", "add", "origin", "git@github.com:o/r.git", cwd=tmp_path)
        assert await _git_remote_url(str(tmp_path)) == "git@github.com:o/r.git"

    async def test_missing_origin_returns_none(self, tmp_path):
        _git("init", "-q", str(tmp_path), cwd=tmp_path.parent)
        assert await _git_remote_url(str(tmp_path)) is None

    async def test_nonexistent_project_dir_returns_none(self, tmp_path):
        # OSError on spawn (cwd does not exist) must not escape.
        assert await _git_remote_url(str(tmp_path / "gone")) is None

    async def test_timeout_kills_the_child_and_returns_none(self, monkeypatch):
        """The regression: an unbounded `git remote get-url` on a wedged mount
        froze the shared loop for the life of the process."""
        proc = _StuckProc()

        async def _fake_spawn(*args, **kwargs):
            return proc

        monkeypatch.setattr(
            ci_watcher.asyncio, "create_subprocess_exec", _fake_spawn
        )
        result = await asyncio.wait_for(
            _git_remote_url("/anywhere", timeout=0.05), timeout=5
        )
        assert result is None
        assert proc.killed, "timed-out git child was never reaped"

    async def test_does_not_block_the_shared_event_loop(self, tmp_path, monkeypatch):
        """check_ci_failures is create_task'd onto the shared loop, so a slow
        git must not stop the status loop / worker polls / HTTP handlers."""
        fake_git = tmp_path / "git"
        fake_git.write_text("#!/bin/sh\nsleep 0.3\necho git@github.com:o/r.git\n")
        fake_git.chmod(0o755)
        monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

        ticks = 0

        async def _ticker():
            nonlocal ticks
            for _ in range(30):
                await asyncio.sleep(0.005)
                ticks += 1

        url, _ = await asyncio.gather(_git_remote_url(str(tmp_path)), _ticker())
        assert url == "git@github.com:o/r.git"
        assert ticks > 5, f"event loop was blocked during git ({ticks} ticks)"


class _RecordingQueue:
    def __init__(self) -> None:
        self.added: list[dict] = []

    async def list(self):
        return []

    async def add(self, **kwargs):
        self.added.append(kwargs)
        return {"id": "t1"}


class TestCheckCiFailuresFailOpen:
    async def test_returns_empty_when_remote_unresolvable(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "x")

        async def _none(project_dir, timeout=10.0):
            return None

        monkeypatch.setattr(ci_watcher, "_git_remote_url", _none)
        queue = _RecordingQueue()
        assert await check_ci_failures(queue, ".") == []
        assert queue.added == []
