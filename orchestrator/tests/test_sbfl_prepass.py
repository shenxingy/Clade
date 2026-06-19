"""SBFL pre-pass (AutoCodeRover §Gap3): rank suspect functions from failing-test
tracebacks before the first patch attempt. Covers the parse/score/rank logic and
the fail-open paths (passing suite, timeout, no parseable frames).

Loads real worker_tldr via importlib (conftest mocks it); same pattern as
test_repro_filter.py.
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

_ORCH = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("_real_worker_tldr_sbfl", _ORCH / "worker_tldr.py")
wt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wt)  # type: ignore[union-attr]


class FakeProc:
    def __init__(self, stdout: bytes = b"", returncode: int = 0):
        self._stdout = stdout
        self.returncode = returncode
        self.killed = False

    async def communicate(self):
        return self._stdout, b""

    def kill(self):
        self.killed = True


class AsyncioProxy:
    def __init__(self, **overrides):
        self._overrides = overrides

    def __getattr__(self, name):
        return self._overrides.get(name, getattr(asyncio, name))


def _exec_returning(proc):
    async def _fake_exec(*a, **k):
        return proc
    return _fake_exec


async def _timeout_wait_for(coro, timeout=None):
    coro.close()
    raise asyncio.TimeoutError


_FAILING_OUTPUT = b"""
=================================== FAILURES ===================================
_______________________________ test_divide ___________________________________
src/calculator.py:42: in divide
    return a / b
E   ZeroDivisionError: division by zero
_______________________________ test_chain ____________________________________
src/calculator.py:42: in divide
    return a / b
src/calculator.py:18: in validate
    return divide(x, y)
E   ZeroDivisionError
=========================== 2 failed in 0.10s ===============================
"""


class TestSbflPrepass:
    async def test_ranks_suspects_by_failing_test_coverage(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            wt, "asyncio",
            AsyncioProxy(create_subprocess_exec=_exec_returning(FakeProc(_FAILING_OUTPUT, 1))),
        )
        block = await wt._sbfl_prepass(tmp_path)
        assert "SBFL Pre-pass" in block
        assert "2 failing test" in block
        # divide is implicated by BOTH failing tests (test_divide + test_chain),
        # validate by only one → divide must rank above validate. Distinct-test
        # coverage (audit 2026-06-18), not raw frame frequency.
        assert block.index("divide") < block.index("validate")
        assert "implicated by 2 failing test" in block

    async def test_skips_test_functions(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            wt, "asyncio",
            AsyncioProxy(create_subprocess_exec=_exec_returning(FakeProc(_FAILING_OUTPUT, 1))),
        )
        block = await wt._sbfl_prepass(tmp_path)
        # the test_ frames must not be ranked as suspects (impl code only)
        assert "test_divide" not in block
        assert "test_chain" not in block

    async def test_passing_suite_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            wt, "asyncio",
            AsyncioProxy(create_subprocess_exec=_exec_returning(FakeProc(b"5 passed", 0))),
        )
        assert await wt._sbfl_prepass(tmp_path) == ""

    async def test_no_parseable_tracebacks_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            wt, "asyncio",
            AsyncioProxy(create_subprocess_exec=_exec_returning(FakeProc(b"1 failed\nassert 1==2", 1))),
        )
        assert await wt._sbfl_prepass(tmp_path) == ""

    async def test_timeout_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            wt, "asyncio",
            AsyncioProxy(
                create_subprocess_exec=_exec_returning(FakeProc(_FAILING_OUTPUT, 1)),
                wait_for=_timeout_wait_for,
            ),
        )
        assert await wt._sbfl_prepass(tmp_path) == ""


# ─── Assertion-aware SBFL (audit 2026-06-18; the owlcast blind-spot fix) ──────

class TestAssertionAwareSbfl:
    def _proj(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        (tmp_path / "src" / "videos.py").write_text(
            "def _pick_video_file(files):\n    return files[-1]\n")
        (tmp_path / "tests" / "test_videos.py").write_text(
            "from src import videos\n\n"
            "def test_pick_smallest():\n"
            "    files = ['a', 'b']\n"
            "    assert videos._pick_video_file(files) == 'a'\n")
        return tmp_path

    def test_assert_only_failure_finds_impl_symbol(self, tmp_path):
        """An assertion failure (no impl frame in the traceback) must still
        surface the impl function the test asserts on — the A1 blind spot."""
        d = self._proj(tmp_path)
        out = ("==== FAILURES ====\n_____ test_pick_smallest _____\n"
               "tests/test_videos.py:5: in test_pick_smallest\n"
               "    assert videos._pick_video_file(files) == 'a'\n"
               "E   AssertionError\n==== 1 failed ====\n")
        import re as _re
        blocks = _re.split(r'\n_{5,}.*\n', out)
        suspects = wt._assertion_suspects(out, d, blocks)
        assert suspects == {"src/videos.py::_pick_video_file": 1}

    def test_call_above_failing_line_is_found(self, tmp_path):
        """The asserted impl call may be on the line ABOVE the assert."""
        d = self._proj(tmp_path)
        (d / "tests" / "test_videos.py").write_text(
            "from src import videos\n\n"
            "def test_two_step():\n"
            "    got = videos._pick_video_file(['a', 'b'])\n"
            "    assert got == 'a'\n")
        out = ("_____ test_two_step _____\n"
               "tests/test_videos.py:5: in test_two_step\n    assert got == 'a'\nE AssertionError\n")
        import re as _re
        suspects = wt._assertion_suspects(out, d, _re.split(r'\n_{5,}.*\n', out))
        assert "src/videos.py::_pick_video_file" in suspects

    def test_builtins_filtered(self, tmp_path):
        d = self._proj(tmp_path)
        (d / "tests" / "test_videos.py").write_text(
            "def test_only_builtins():\n    assert len([1, 2]) == 3\n")
        out = ("_____ test_only_builtins _____\n"
               "tests/test_videos.py:2: in test_only_builtins\n    assert len([1,2])==3\nE AssertionError\n")
        import re as _re
        assert wt._assertion_suspects(out, d, _re.split(r'\n_{5,}.*\n', out)) == {}
