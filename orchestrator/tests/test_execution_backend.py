"""Tests for execution_backend.py — the spawn/kill adapter.

Covers the three behaviours the task pins down:
  (a) backend selection reads from settings (factory + Worker default wiring)
  (b) LocalSubprocessBackend.spawn produces a live pid
  (c) kill terminates the whole process group (parent AND its children)

Plus the ClaudeNativeBackend stub contract (must fail loud, not silently no-op).
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import signal
from pathlib import Path

import pytest

import config
import execution_backend as eb
from execution_backend import (
    ClaudeNativeBackend,
    ExecutionBackend,
    LocalSubprocessBackend,
    get_execution_backend,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────


async def _spawn(backend: LocalSubprocessBackend, cmd: str, tmp_path: Path):
    """Spawn cmd through the backend with logs going to a temp file."""
    log_fd = open(tmp_path / "spawn.log", "w")
    proc = await backend.spawn(
        cmd,
        stdout=log_fd,
        stderr=log_fd,
        env=dict(os.environ),
        cwd=str(tmp_path),
    )
    log_fd.close()
    return proc


def _group_alive(pgid: int) -> bool:
    """True if the process group still exists (signal 0 = existence probe)."""
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


# ─── (a) backend selection reads from settings ───────────────────────────────


def test_setting_default_is_local() -> None:
    # The setting must exist with the documented default so GLOBAL_SETTINGS
    # always carries it.
    assert config._SETTINGS_DEFAULTS["execution_backend"] == "local"


def test_factory_selects_local_from_explicit_settings() -> None:
    backend = get_execution_backend({"execution_backend": "local"})
    assert isinstance(backend, LocalSubprocessBackend)
    assert backend.name == "local"


def test_factory_defaults_to_local_when_key_absent() -> None:
    # Empty dict / missing key → local (must not strand the pool).
    assert isinstance(get_execution_backend({}), LocalSubprocessBackend)


def test_factory_unknown_value_falls_back_to_local() -> None:
    assert isinstance(get_execution_backend({"execution_backend": "bogus"}), LocalSubprocessBackend)


def test_factory_reads_global_settings_when_settings_none(monkeypatch) -> None:
    monkeypatch.setitem(eb.__dict__, "_BACKENDS", dict(eb._BACKENDS))  # isolate
    monkeypatch.setitem(config.GLOBAL_SETTINGS, "execution_backend", "local")
    assert isinstance(get_execution_backend(), LocalSubprocessBackend)


def test_factory_rejects_planned_claude_native() -> None:
    with pytest.raises(NotImplementedError):
        get_execution_backend({"execution_backend": "claude-native"})


def test_worker_uses_local_backend_by_default(tmp_path: Path) -> None:
    """Worker wiring: default execution backend is LocalSubprocessBackend.

    conftest replaces sys.modules['worker'] with a mock, so load the real
    module under a private name (same trick as test_worker.py)."""
    worker_file = Path(__file__).parent.parent / "worker.py"
    spec = importlib.util.spec_from_file_location("_real_worker_eb", worker_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    w = mod.Worker(
        task_id="t1",
        description="noop",
        model="sonnet",
        project_dir=tmp_path,
        claude_dir=claude_dir,
    )
    assert isinstance(w._backend, LocalSubprocessBackend)


# ─── (b) LocalSubprocessBackend.spawn produces a live pid ────────────────────


async def test_spawn_produces_live_pid(tmp_path: Path) -> None:
    backend = LocalSubprocessBackend()
    proc = await _spawn(backend, "sleep 30", tmp_path)
    try:
        assert isinstance(proc.pid, int) and proc.pid > 0
        assert backend.is_alive(proc) is True
        # Spawned into its own session/group (setsid) → pgid == pid (leader).
        assert os.getpgid(proc.pid) == proc.pid
    finally:
        backend.kill(os.getpgid(proc.pid), signal.SIGKILL)
        await asyncio.wait_for(proc.wait(), timeout=5)


def test_is_alive_false_for_none() -> None:
    assert LocalSubprocessBackend().is_alive(None) is False


# ─── (c) kill terminates the process group ───────────────────────────────────


async def test_kill_terminates_process_group(tmp_path: Path) -> None:
    """Killing the group must reap the parent AND a backgrounded child.

    The shell forks `sleep 30` into the same group and records its pid, so we
    can prove the grandchild — not just the immediate child — was torn down.
    """
    backend = LocalSubprocessBackend()
    child_pid_file = tmp_path / "child.pid"
    cmd = f"sleep 30 & echo $! > {child_pid_file}; wait"
    proc = await _spawn(backend, cmd, tmp_path)
    pgid = os.getpgid(proc.pid)
    try:
        # Wait for the shell to record the backgrounded child's pid.
        for _ in range(50):
            if child_pid_file.exists() and child_pid_file.read_text().strip():
                break
            await asyncio.sleep(0.05)
        child_pid = int(child_pid_file.read_text().strip())
        assert _group_alive(pgid) is True

        backend.kill(pgid, signal.SIGTERM)
        await asyncio.wait_for(proc.wait(), timeout=5)

        assert backend.is_alive(proc) is False
        # Give the kernel a moment to reap the whole group, then assert the
        # backgrounded child is gone too.
        for _ in range(50):
            if not _group_alive(pgid):
                break
            await asyncio.sleep(0.05)
        assert _group_alive(pgid) is False
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
    finally:
        # Defensive: ensure nothing leaks if an assert above failed.
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_kill_swallows_missing_group() -> None:
    # killpg on a non-existent group raises ProcessLookupError; backend eats it.
    backend = LocalSubprocessBackend()
    # PID/PGID 999999 almost certainly does not exist; must not raise.
    backend.kill(999999, signal.SIGTERM)


# ─── ClaudeNativeBackend stub contract ───────────────────────────────────────


def test_claude_native_is_an_execution_backend() -> None:
    assert issubclass(ClaudeNativeBackend, ExecutionBackend)
    assert ClaudeNativeBackend.name == "claude-native"


async def test_claude_native_spawn_raises() -> None:
    with pytest.raises(NotImplementedError):
        await ClaudeNativeBackend().spawn("noop", stdout=None, stderr=None, env={}, cwd=".")


def test_claude_native_kill_and_is_alive_raise() -> None:
    stub = ClaudeNativeBackend()
    with pytest.raises(NotImplementedError):
        stub.is_alive(None)
    with pytest.raises(NotImplementedError):
        stub.kill(1, signal.SIGTERM)
