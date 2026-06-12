"""Tests for task_factory.ci_watcher — jobs-payload parsing + fail-open detail fetch.

Pure helpers are driven with fixture JSON; the async fetcher is exercised with
duck-typed stub clients so no network or httpx mocking is needed.
"""

from task_factory.ci_watcher import (
    _GUARDRAILS,
    _fetch_failure_details,
    _log_tail,
    _summarize_failed_jobs,
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
