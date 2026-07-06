"""Tests for worker_hydrate.py's Round-4 additions:

  (A) Epistemic caveat — every hydrated GitHub issue/PR block carries a
      one-line "this is the reporter's account, not a confirmed root cause"
      note, unconditionally (regardless of fix vs non-fix task wording).
  (B) Clean-room hydration distillation — an OPTIONAL (default-off) pass that
      routes fetched issue/PR body text through a pinned Haiku judge before
      it is folded into the task file. Off by default (raw text unchanged);
      when on, the judge subprocess is invoked with the same containment
      flags as worker_review._oracle_pass_once and its output replaces the
      raw text; on judge failure/timeout, hydration fails open to raw text.

worker_hydrate.py is a documented leaf module (zero project imports) and is
NOT mocked in tests/conftest.py, so it is imported directly here.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import worker_hydrate as wh

ISSUE_BODY = (
    "Steps to reproduce:\n1. Open the app\n2. Click save\n\n"
    "Expected: saves cleanly.\nActual: crashes with a null pointer.\n\n"
    "## Acceptance Criteria\n- [ ] no crash on save\n- [ ] regression test added\n"
)

PR_BODY = "This PR fixes the save crash by adding a null check before dereference.\n"


class FakeProc:
    """Stand-in for an asyncio subprocess (mirrors tests/test_oracle_integrity.py)."""

    def __init__(self, stdout: bytes = b"", returncode: int = 0):
        self._stdout = stdout
        self.returncode = returncode
        self.killed = False

    async def communicate(self):
        return self._stdout, b""

    def kill(self):
        self.killed = True


class SlowFakeProc(FakeProc):
    """A subprocess whose communicate() never returns before the timeout."""

    async def communicate(self):
        await asyncio.sleep(2)
        return self._stdout, b""


def _issue_json(body: str = ISSUE_BODY) -> bytes:
    return json.dumps({
        "title": "Crash on save",
        "body": body,
        "state": "OPEN",
        "labels": [{"name": "bug"}],
    }).encode()


def _pr_json(body: str = PR_BODY) -> bytes:
    return json.dumps({
        "title": "Fix save crash",
        "body": body,
        "state": "OPEN",
        "additions": 5,
        "deletions": 1,
    }).encode()


def _make_gh_and_claude_fake(
    issue_body: str = ISSUE_BODY,
    pr_body: str = PR_BODY,
    claude_response: bytes = b"DISTILLED: reporter claims a crash on save.",
    claude_returncode: int = 0,
    claude_raises: bool = False,
    calls: list | None = None,
):
    """Fake asyncio.create_subprocess_exec serving gh issue/pr view + claude -p."""

    async def _fake(*args, **kwargs):
        if calls is not None:
            calls.append(args)
        if args[0] == "gh":
            if len(args) > 2 and args[1] == "issue" and args[2] == "view":
                return FakeProc(_issue_json(issue_body))
            if len(args) > 2 and args[1] == "pr" and args[2] == "view":
                return FakeProc(_pr_json(pr_body))
            return FakeProc(b"{}", returncode=1)
        if args[0] == "claude":
            if claude_raises:
                raise RuntimeError("judge subprocess spawn failed")
            return FakeProc(claude_response, returncode=claude_returncode)
        return FakeProc(b"{}", returncode=1)

    return _fake


# ─── Gap A: epistemic caveat ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "task_desc",
    [
        "fix: crash reported in acme/myrepo#123",  # fix-intent wording
        "Investigate report acme/myrepo#123",  # non-fix wording
    ],
)
async def test_caveat_present_on_issue_block_regardless_of_task_wording(
    monkeypatch, task_desc
):
    monkeypatch.setattr(wh.asyncio, "create_subprocess_exec", _make_gh_and_claude_fake())
    result = await wh._pre_hydrate(task_desc, project_dir=None)
    assert wh._EPISTEMIC_CAVEAT in result
    assert "Pre-hydrated Issue" in result


async def test_caveat_present_on_pr_block(monkeypatch):
    monkeypatch.setattr(wh.asyncio, "create_subprocess_exec", _make_gh_and_claude_fake())
    result = await wh._pre_hydrate(
        "see https://github.com/acme/myrepo/pull/42", project_dir=None
    )
    assert wh._EPISTEMIC_CAVEAT in result
    assert "Pre-hydrated PR" in result


async def test_no_hydration_no_caveat_emitted() -> None:
    """No linked references → empty hydrate block, nothing to caveat."""
    result = await wh._pre_hydrate("just a plain task with no links", project_dir=None)
    assert result == ""


# ─── Gap B: distillation default-off ───────────────────────────────────────────


async def test_distillation_off_by_default_raw_body_passes_through(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        wh.asyncio, "create_subprocess_exec",
        _make_gh_and_claude_fake(calls=calls),
    )
    # distill kwarg omitted entirely — must default to False.
    result = await wh._pre_hydrate("acme/myrepo#123", project_dir=None)
    assert "crashes with a null pointer" in result  # raw body verbatim
    assert "no crash on save" in result  # acceptance criteria extracted from raw body
    assert not any(c[0] == "claude" for c in calls), (
        "distillation must not spawn the judge subprocess when off"
    )


async def test_distillation_explicitly_off_raw_body_passes_through(monkeypatch):
    monkeypatch.setattr(wh.asyncio, "create_subprocess_exec", _make_gh_and_claude_fake())
    result = await wh._pre_hydrate("acme/myrepo#123", project_dir=None, distill=False)
    assert "crashes with a null pointer" in result


# ─── Gap B: distillation on ────────────────────────────────────────────────────


async def test_distillation_on_calls_pinned_judge_with_containment_flags(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        wh.asyncio, "create_subprocess_exec",
        _make_gh_and_claude_fake(calls=calls),
    )
    result = await wh._pre_hydrate(
        "acme/myrepo#123", project_dir=None, claude_dir=None, distill=True,
    )
    claude_calls = [c for c in calls if c[0] == "claude"]
    assert len(claude_calls) == 1
    argv = claude_calls[0]
    assert "--model" in argv
    assert argv[argv.index("--model") + 1] == wh.HAIKU_MODEL
    assert "--setting-sources" in argv  # pure-judge containment: no user settings
    assert "--disallowed-tools" in argv  # judge cannot Edit/Write/Bash

    # The judge's summary replaces the raw body in the final block...
    assert "DISTILLED: reporter claims a crash on save." in result
    assert "crashes with a null pointer" not in result
    # ...but acceptance criteria, extracted BEFORE distillation, still surfaces.
    assert "no crash on save" in result


async def test_distillation_on_applies_to_pr_block_too(monkeypatch):
    monkeypatch.setattr(wh.asyncio, "create_subprocess_exec", _make_gh_and_claude_fake())
    result = await wh._pre_hydrate(
        "see https://github.com/acme/myrepo/pull/42",
        project_dir=None, distill=True,
    )
    assert "DISTILLED: reporter claims a crash on save." in result
    assert "adding a null check" not in result


# ─── Gap B: fail-open ──────────────────────────────────────────────────────────


async def test_distillation_subprocess_error_falls_back_to_raw_never_raises(monkeypatch):
    monkeypatch.setattr(
        wh.asyncio, "create_subprocess_exec",
        _make_gh_and_claude_fake(claude_raises=True),
    )
    # Must not raise even though the judge subprocess spawn errors.
    result = await wh._pre_hydrate("acme/myrepo#123", project_dir=None, distill=True)
    assert "crashes with a null pointer" in result  # raw body preserved
    assert wh._EPISTEMIC_CAVEAT in result


async def test_distillation_nonzero_exit_falls_back_to_raw(monkeypatch):
    monkeypatch.setattr(
        wh.asyncio, "create_subprocess_exec",
        _make_gh_and_claude_fake(claude_returncode=1, claude_response=b"error"),
    )
    result = await wh._pre_hydrate("acme/myrepo#123", project_dir=None, distill=True)
    assert "crashes with a null pointer" in result


async def test_distillation_empty_output_falls_back_to_raw(monkeypatch):
    monkeypatch.setattr(
        wh.asyncio, "create_subprocess_exec",
        _make_gh_and_claude_fake(claude_response=b"   "),
    )
    result = await wh._pre_hydrate("acme/myrepo#123", project_dir=None, distill=True)
    assert "crashes with a null pointer" in result


async def test_distill_helper_timeout_falls_back_to_raw(monkeypatch):
    async def _fake(*args, **kwargs):
        return SlowFakeProc()

    monkeypatch.setattr(wh.asyncio, "create_subprocess_exec", _fake)
    result = await wh._distill_github_text("raw untrusted text", timeout=0.05)
    assert result == "raw untrusted text"


async def test_distill_helper_blank_input_short_circuits(monkeypatch):
    called = False

    async def _fake(*args, **kwargs):
        nonlocal called
        called = True
        return FakeProc(b"should not be reached")

    monkeypatch.setattr(wh.asyncio, "create_subprocess_exec", _fake)
    result = await wh._distill_github_text("   ", claude_dir=None)
    assert result == "   "
    assert not called
