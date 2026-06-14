"""Reproduction-test filter (Agentless §6B validation half).

Clade already GENERATED a repro test confirming a bug fails pre-fix, then threw
it away. These tests cover the closed half: persist the confirmed-failing repro
and re-run it post-fix as an executable proof the bug is resolved.

Loads real worker_tldr via importlib (conftest mocks it); worker_utils is not
mocked. Same pattern as test_pure_judge_flags / test_oracle_integrity.
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

_ORCH = Path(__file__).resolve().parents[1]


def _load_real(filename: str, alias: str):
    spec = importlib.util.spec_from_file_location(alias, _ORCH / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


wt = _load_real("worker_tldr.py", "_real_worker_tldr_repro")
import worker_utils as wu  # noqa: E402 — not mocked by conftest


# ─── Test doubles ─────────────────────────────────────────────────────────────


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
    """Proxy asyncio, overriding subprocess entry points without mutating the global."""

    def __init__(self, **overrides):
        self._overrides = overrides

    def __getattr__(self, name):
        if name in self._overrides:
            return self._overrides[name]
        return getattr(asyncio, name)


def _exec_returning(*procs):
    """Return create_subprocess_exec that yields the given procs in sequence
    (last one repeats once exhausted)."""
    seq = list(procs)

    async def _fake_exec(*args, **kwargs):
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return _fake_exec


async def _timeout_wait_for(coro, timeout=None):
    coro.close()
    raise asyncio.TimeoutError


# ─── _run_repro_filter ────────────────────────────────────────────────────────


class TestRunReproFilter:
    async def test_no_repro_file_returns_none(self, tmp_path):
        """No persisted repro → no signal, fail-open. Never touches a subprocess."""
        passed, output = await wu._run_repro_filter(tmp_path, tmp_path)
        assert passed is None
        assert output == ""

    async def test_repro_passes_after_fix(self, tmp_path, monkeypatch):
        (tmp_path / "repro-test.py").write_text("def test_x():\n    assert True\n")
        monkeypatch.setattr(
            wu, "asyncio",
            AsyncioProxy(create_subprocess_exec=_exec_returning(FakeProc(b"1 passed", 0))),
        )
        passed, output = await wu._run_repro_filter(tmp_path, tmp_path)
        assert passed is True
        assert "passed" in output
        # persisted repro is cleaned up regardless of outcome
        assert not (tmp_path / "repro-test.py").exists()

    async def test_repro_still_failing_after_fix(self, tmp_path, monkeypatch):
        (tmp_path / "repro-test.py").write_text("def test_x():\n    assert False\n")
        monkeypatch.setattr(
            wu, "asyncio",
            AsyncioProxy(create_subprocess_exec=_exec_returning(FakeProc(b"1 failed", 1))),
        )
        passed, output = await wu._run_repro_filter(tmp_path, tmp_path)
        assert passed is False
        assert "failed" in output
        assert not (tmp_path / "repro-test.py").exists()

    async def test_timeout_is_none_and_cleans_up(self, tmp_path, monkeypatch):
        (tmp_path / "repro-test.py").write_text("def test_x():\n    assert True\n")
        monkeypatch.setattr(
            wu, "asyncio",
            AsyncioProxy(
                create_subprocess_exec=_exec_returning(FakeProc(b"", 0)),
                wait_for=_timeout_wait_for,
            ),
        )
        passed, output = await wu._run_repro_filter(tmp_path, tmp_path)
        assert passed is None  # timeout = no signal, not a failure
        assert not (tmp_path / "repro-test.py").exists()

    async def test_temp_file_not_left_in_project_dir(self, tmp_path, monkeypatch):
        (tmp_path / "repro-test.py").write_text("def test_x():\n    assert True\n")
        monkeypatch.setattr(
            wu, "asyncio",
            AsyncioProxy(create_subprocess_exec=_exec_returning(FakeProc(b"1 passed", 0))),
        )
        await wu._run_repro_filter(tmp_path, tmp_path)
        leaked = list(tmp_path.glob("clade-reprofilter-*.py"))
        assert leaked == []


# ─── _generate_repro_test persistence gate ────────────────────────────────────


class TestReproPersistence:
    """Only CONFIRMED-FAILING repros are persisted; a test that passes on buggy
    code is a bad test and must never be persisted (it would gate good fixes)."""

    _TEST_CODE = b"def test_repro():\n    assert buggy() == 'fixed'\n"

    def _proxy(self, monkeypatch, run_returncode: int):
        # Three exec calls in _generate_repro_test: (1) haiku writes test code,
        # (2) py_compile (must be 0), (3) pytest run (returncode decides confirmed).
        haiku = FakeProc(self._TEST_CODE, 0)
        compile_ok = FakeProc(b"", 0)
        run = FakeProc(b"1 failed" if run_returncode else b"1 passed", run_returncode)
        monkeypatch.setattr(
            wt, "asyncio",
            AsyncioProxy(create_subprocess_exec=_exec_returning(haiku, compile_ok, run)),
        )

    async def test_persists_when_confirmed_failing(self, tmp_path, monkeypatch):
        self._proxy(monkeypatch, run_returncode=1)  # test fails on buggy code → confirmed
        block = await wt._generate_repro_test(
            "fix the crash", "## a.py\n  def buggy()", tmp_path, tmp_path
        )
        assert "Reproduction Test" in block
        assert (tmp_path / "repro-test.py").exists()
        assert b"test_repro" in (tmp_path / "repro-test.py").read_bytes()

    async def test_does_not_persist_when_test_passes_on_buggy_code(self, tmp_path, monkeypatch):
        self._proxy(monkeypatch, run_returncode=0)  # passes on buggy code → bad repro
        await wt._generate_repro_test(
            "fix the crash", "## a.py\n  def buggy()", tmp_path, tmp_path
        )
        assert not (tmp_path / "repro-test.py").exists()

    async def test_no_persist_without_claude_dir(self, tmp_path, monkeypatch):
        self._proxy(monkeypatch, run_returncode=1)
        # claude_dir omitted → back-compat path, nothing persisted
        await wt._generate_repro_test("fix the crash", "## a.py\n  def buggy()", tmp_path)
        assert not (tmp_path / "repro-test.py").exists()
