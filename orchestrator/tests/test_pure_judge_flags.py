"""Pure-judge containment: parsed-output `claude -p` subprocesses must pass
--setting-sources "" so user-level hooks cannot hijack the printed result.

Background (commit 386a862 + this fix): a prompt-type Stop hook in
~/.claude/settings.json makes nested `claude -p` print the hook's own
{"ok":true} decision instead of the model reply. Every call here parses or
stores stdout, so each one must drop user settings. Worker spawns are the
deliberate exception (commit-discipline hooks are core value) — asserted in
test_worker_spawn_keeps_user_settings.

Loads the REAL worker_tldr / worker_review via importlib to bypass the
conftest sys.modules mocks (same pattern as test_oracle_integrity.py).
"""

from __future__ import annotations

import asyncio
import importlib.util
import shlex
from pathlib import Path

import pytest

_ORCH = Path(__file__).resolve().parents[1]


def _load_real(filename: str, alias: str):
    spec = importlib.util.spec_from_file_location(alias, _ORCH / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


wt = _load_real("worker_tldr.py", "_real_worker_tldr_flags")
wr = _load_real("worker_review.py", "_real_worker_review_flags")

import condensers as cd  # noqa: E402 — not mocked by conftest
import worker_utils as wu  # noqa: E402 — not mocked by conftest
import session as ss  # noqa: E402
from config import SETTING_SOURCES_NONE, DISALLOWED_TOOLS_JUDGE  # noqa: E402

# conftest replaces `worker` in sys.modules with a MagicMock — load the real
# module by path for the spawn-command assertion (test_oracle_integrity pattern).
w = _load_real("worker.py", "_real_worker_flags")

FLAG_STR = '--setting-sources ""'
FLAG_ARGV = shlex.split(FLAG_STR)  # ["--setting-sources", ""]

DISALLOWED_FLAG_STR = "--disallowed-tools Edit,Write,Bash"
DISALLOWED_FLAG_ARGV = shlex.split(DISALLOWED_FLAG_STR)  # ["--disallowed-tools", "Edit,Write,Bash"]


def _assert_argv_has_flag(argv: list):
    assert "--setting-sources" in argv, argv
    idx = argv.index("--setting-sources")
    assert argv[idx + 1] == "", f"--setting-sources value not empty: {argv}"


def _assert_argv_has_disallowed(argv: list):
    assert "--disallowed-tools" in argv, f"--disallowed-tools missing from judge argv: {argv}"
    idx = argv.index("--disallowed-tools")
    assert argv[idx + 1] == "Edit,Write,Bash", f"unexpected --disallowed-tools value: {argv[idx + 1]}"


# ─── Capture plumbing (same shape as test_oracle_integrity) ───────────────────


class _FakeProc:
    def __init__(self, stdout: bytes = b""):
        self._stdout = stdout
        self.returncode = 0

    async def communicate(self):
        return self._stdout, b""

    def kill(self):
        pass


class _AsyncioProxy:
    """Overridden names hit stubs; everything else passes through to asyncio."""

    def __init__(self, **overrides):
        self._overrides = overrides

    def __getattr__(self, name):
        if name in self._overrides:
            return self._overrides[name]
        return getattr(asyncio, name)


def _capture_proxy(captured: list, stdout: bytes = b""):
    async def _exec(*args, **kwargs):
        captured.append({"argv": list(args), "kwargs": kwargs})
        return _FakeProc(stdout)

    async def _shell(cmd, **kwargs):
        captured.append({"cmd": cmd, "kwargs": kwargs})
        return _FakeProc(stdout)

    return _AsyncioProxy(create_subprocess_exec=_exec, create_subprocess_shell=_shell)


# ─── Single source of truth ───────────────────────────────────────────────────


def test_config_constant_matches_oracle_precedent():
    assert SETTING_SOURCES_NONE == FLAG_STR


def test_config_disallowed_tools_constant():
    assert DISALLOWED_TOOLS_JUDGE == DISALLOWED_FLAG_STR


def test_leaf_module_defaults_match_config():
    # Leaves cannot import config — their literal defaults must stay in sync
    # (worker.py re-asserts at import time, but standalone imports rely on these).
    assert wt.SETTING_SOURCES_NONE == SETTING_SOURCES_NONE
    assert wr.SETTING_SOURCES_NONE == SETTING_SOURCES_NONE
    assert wu.SETTING_SOURCES_NONE == SETTING_SOURCES_NONE
    assert cd.SETTING_SOURCES_NONE == SETTING_SOURCES_NONE
    assert wt.DISALLOWED_TOOLS_JUDGE == DISALLOWED_TOOLS_JUDGE
    assert wr.DISALLOWED_TOOLS_JUDGE == DISALLOWED_TOOLS_JUDGE
    assert cd.DISALLOWED_TOOLS_JUDGE == DISALLOWED_TOOLS_JUDGE


# ─── 2026-06-18: read-only judge hardening (opencode) ────────────────────────
# DISALLOWED_TOOLS_JUDGE was defined + applied to the leaf judges but NOT to the
# worker verify judge or the session.py supervisor/decompose/suggest judges — a
# defined-≠-wired gap. These guard the now-wired spawns.


def test_worker_verify_judge_disallows_tools():
    """The pre-commit verify judge (worker.py) reads an embedded git-diff stat
    and emits VERIFIED_OK/FAIL — it must not retain Edit/Write/Bash."""
    src = (_ORCH / "worker.py").read_text()
    assert "--dangerously-skip-permissions {SETTING_SOURCES_NONE} {DISALLOWED_TOOLS_JUDGE}" in src


def test_session_pure_judges_disallow_tools():
    """The supervisor / horizontal-decompose / suggest-goals judges in session.py
    are pure stdout-parsed verdicts and must disallow Edit/Write/Bash. The
    interactive PTY session at the top of session.py is NOT a judge — it keeps
    full tools and must stay excluded."""
    src = (_ORCH / "session.py").read_text()
    assert src.count("{SETTING_SOURCES_NONE} {DISALLOWED_TOOLS_JUDGE}") >= 2  # 2 shell supervisor judges
    assert src.count("shlex.split(DISALLOWED_TOOLS_JUDGE)") >= 2              # decompose + suggest-goals


# ─── worker_tldr: TLDR localization / fault / repro / scoring ─────────────────


@pytest.mark.asyncio
async def test_localize_tldr_argv_has_flag(tmp_path, monkeypatch):
    captured: list = []
    monkeypatch.setattr(wt, "asyncio", _capture_proxy(captured))
    await wt._localize_tldr_for_task("pick files", "## a.py\n  def f()", tmp_path)
    assert captured, "claude was not invoked"
    _assert_argv_has_flag(captured[0]["argv"])


@pytest.mark.asyncio
async def test_localize_fault_argv_has_flag(tmp_path, monkeypatch):
    captured: list = []
    monkeypatch.setattr(wt, "asyncio", _capture_proxy(captured))
    await wt._localize_fault("fix the bug", "## a.py\n  def f()", tmp_path)
    assert captured
    _assert_argv_has_flag(captured[0]["argv"])


@pytest.mark.asyncio
async def test_generate_repro_test_argv_has_flag(tmp_path, monkeypatch):
    captured: list = []
    monkeypatch.setattr(wt, "asyncio", _capture_proxy(captured))
    await wt._generate_repro_test("fix crash", "## a.py\n  def f()", tmp_path)
    assert captured
    _assert_argv_has_flag(captured[0]["argv"])


@pytest.mark.asyncio
async def test_score_task_cmd_has_flag(tmp_path, monkeypatch):
    captured: list = []
    monkeypatch.setattr(wt, "asyncio", _capture_proxy(captured))
    await wt._score_task("t1", "score me", tmp_path / "db.sqlite", tmp_path)
    assert captured
    assert FLAG_STR in captured[0]["cmd"]


# ─── worker_review: summary / progress / PR review (oracle covered in
#     test_oracle_integrity.py::test_grader_cwd_confined_to_scratch_dir) ──────


@pytest.mark.asyncio
async def test_summarize_worker_completion_cmd_has_flag(tmp_path, monkeypatch):
    captured: list = []
    monkeypatch.setattr(wr, "asyncio", _capture_proxy(captured))
    log = tmp_path / "worker.log"
    log.write_text("did things\n")
    await wr._summarize_worker_completion("task", log, tmp_path)
    assert captured
    assert FLAG_STR in captured[0]["cmd"]


@pytest.mark.asyncio
async def test_write_progress_entry_cmd_has_flag(tmp_path, monkeypatch):
    captured: list = []
    monkeypatch.setattr(wr, "asyncio", _capture_proxy(captured))
    await wr._write_progress_entry("task", None, tmp_path)
    assert captured
    assert FLAG_STR in captured[0]["cmd"]


@pytest.mark.asyncio
async def test_write_pr_review_claude_cmd_has_flag(tmp_path, monkeypatch):
    captured: list = []
    monkeypatch.setattr(wr, "asyncio", _capture_proxy(captured))
    await wr._write_pr_review("https://github.com/x/y/pull/1", "task", tmp_path)
    claude_cmds = [c["cmd"] for c in captured if c["cmd"].startswith("claude ")]
    assert claude_cmds, f"no claude call captured: {captured}"
    assert all(FLAG_STR in c for c in claude_cmds)
    # gh calls must NOT get the claude-only flag
    gh_cmds = [c["cmd"] for c in captured if c["cmd"].startswith("gh ")]
    assert all(FLAG_STR not in c for c in gh_cmds)


# ─── worker_utils: distill + rank ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_distill_output_argv_has_flag(tmp_path, monkeypatch):
    captured: list = []
    monkeypatch.setattr(wu, "asyncio", _capture_proxy(captured))
    await wu._distill_output("big output " * 50, tmp_path)
    assert captured
    _assert_argv_has_flag(captured[0]["argv"])


class _StubQueue:
    async def list(self):
        return [{"id": "t1", "status": "pending", "priority_score": 0,
                 "description": "rank me"}]

    async def update(self, *args, **kwargs):
        pass


@pytest.mark.asyncio
async def test_rank_tasks_argv_has_flag(tmp_path, monkeypatch):
    captured: list = []
    monkeypatch.setattr(wu, "asyncio", _capture_proxy(captured))
    await wu._rank_tasks(_StubQueue(), tmp_path)
    assert captured
    _assert_argv_has_flag(captured[0]["argv"])


# ─── condensers: LLM summarize ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_summarize_argv_has_flag(tmp_path, monkeypatch):
    captured: list = []
    monkeypatch.setattr(cd, "asyncio", _capture_proxy(captured))
    await cd.LLMSummarizingCondenser()._summarize(
        [{"type": "msg", "content": "hello"}], tmp_path
    )
    assert captured
    _assert_argv_has_flag(captured[0]["argv"])


# ─── session: decompose + goal suggestion ─────────────────────────────────────


class _StubSession:
    def __init__(self, tmp_path: Path):
        self.project_dir = tmp_path
        self.claude_dir = tmp_path
        self.session_id = "s1"
        self.status_subscribers: list = []
        self.task_queue = _StubQueue()


@pytest.mark.asyncio
async def test_decompose_horizontal_argv_has_flag(tmp_path, monkeypatch):
    captured: list = []
    monkeypatch.setattr(ss, "asyncio", _capture_proxy(captured))
    await ss._decompose_horizontal(
        {"id": "t1", "description": "split this"}, _StubSession(tmp_path)
    )
    assert captured
    _assert_argv_has_flag(captured[0]["argv"])


@pytest.mark.asyncio
async def test_suggest_next_goals_argv_has_flag(tmp_path, monkeypatch):
    captured: list = []
    monkeypatch.setattr(ss, "asyncio", _capture_proxy(captured))
    await ss._suggest_next_goals(_StubSession(tmp_path))
    assert captured
    _assert_argv_has_flag(captured[0]["argv"])


def test_session_supervisor_and_plan_cmds_carry_flag():
    """The two shell-string judge sites in session.py (status_loop supervisor,
    plan_build PLAN phase) embed SETTING_SOURCES_NONE in their f-strings —
    assert at source level since both live inside long-running loops."""
    src = (_ORCH / "session.py").read_text()
    assert src.count(
        "--dangerously-skip-permissions {SETTING_SOURCES_NONE}"
    ) >= 2, "session.py judge command strings lost the pure-judge flag"


# ─── worker spawns: the deliberate exception ──────────────────────────────────


def test_worker_spawn_keeps_user_settings(tmp_path):
    """Workers EDIT files — commit-discipline hooks are core value, so the
    main spawn must NOT drop user settings."""
    wk = w.Worker("t1", "do work", "sonnet", tmp_path, tmp_path)
    cmd, _env = wk._build_cmd_and_env(tmp_path / "task.md")
    assert "--setting-sources" not in cmd
    assert "claude -p" in cmd


def test_worker_verify_judge_cmd_carries_flag():
    """worker.py's VERIFIED_OK/FAIL judge parses stdout → must drop user
    settings (source-level: the call sits deep inside verify_and_commit)."""
    src = (_ORCH / "worker.py").read_text()
    assert "--dangerously-skip-permissions {SETTING_SOURCES_NONE}" in src


# ─── ideas: eval + discuss ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ideas_calls_carry_flag(tmp_path, monkeypatch):
    import ideas as idm

    captured: list = []
    monkeypatch.setattr(idm, "asyncio", _capture_proxy(captured))
    mgr = idm.IdeasManager(tmp_path / "ideas.db")
    idea = await mgr.add_idea("an idea worth judging")
    await mgr.evaluate_idea(idea["id"])
    assert captured
    _assert_argv_has_flag(captured[0]["argv"])

    captured.clear()
    await mgr.discuss_idea(idea["id"], "what do you think?")
    assert captured
    _assert_argv_has_flag(captured[0]["argv"])


# ─── --disallowed-tools: judge calls include it, worker spawns do not ─────────


@pytest.mark.asyncio
async def test_judge_localize_tldr_has_disallowed(tmp_path, monkeypatch):
    captured: list = []
    monkeypatch.setattr(wt, "asyncio", _capture_proxy(captured))
    await wt._localize_tldr_for_task("pick files", "## a.py\n  def f()", tmp_path)
    assert captured, "claude was not invoked"
    _assert_argv_has_disallowed(captured[0]["argv"])


@pytest.mark.asyncio
async def test_judge_localize_fault_has_disallowed(tmp_path, monkeypatch):
    captured: list = []
    monkeypatch.setattr(wt, "asyncio", _capture_proxy(captured))
    await wt._localize_fault("fix the bug", "## a.py\n  def f()", tmp_path)
    assert captured
    _assert_argv_has_disallowed(captured[0]["argv"])


@pytest.mark.asyncio
async def test_judge_summarize_completion_has_disallowed(tmp_path, monkeypatch):
    captured: list = []
    monkeypatch.setattr(wr, "asyncio", _capture_proxy(captured))
    log = tmp_path / "worker.log"
    log.write_text("did things\n")
    await wr._summarize_worker_completion("task", log, tmp_path)
    assert captured
    assert DISALLOWED_FLAG_STR in captured[0]["cmd"]


@pytest.mark.asyncio
async def test_judge_llm_condenser_has_disallowed(tmp_path, monkeypatch):
    captured: list = []
    monkeypatch.setattr(cd, "asyncio", _capture_proxy(captured))
    await cd.LLMSummarizingCondenser()._summarize(
        [{"type": "msg", "content": "hello"}], tmp_path
    )
    assert captured
    _assert_argv_has_disallowed(captured[0]["argv"])


def test_worker_spawn_no_disallowed_tools(tmp_path):
    """Workers EDIT files — --disallowed-tools must NOT appear in the main spawn."""
    wk = w.Worker("t1", "do work", "sonnet", tmp_path, tmp_path)
    cmd, _env = wk._build_cmd_and_env(tmp_path / "task.md")
    assert "--disallowed-tools" not in cmd
