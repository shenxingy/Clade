"""The distributable MCP package ran a blocking subprocess on the event loop.

CLAUDE.md states the rule and the reason: `server.call_tool` is `async def`, the
MCP SDK dispatches tools/call concurrently, and a bare `subprocess.run` there
freezes the read loop, the stdout writer, every other in-flight call and
cancellation handling for the whole timeout — 300 seconds here.

The orchestrator's own `mcp_server.py` carries a comment saying exactly that and
uses `create_subprocess_exec`. `mcp-package/src/clade_mcp/runtime.py`, the copy
other people pip-install, called `subprocess.run` twice.

These measure the property rather than asserting the spelling: two concurrent
runs must overlap, a timeout must not leave a grandchild behind, and the
synchronous wrapper must refuse rather than block.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import re
import signal
import sys
import time
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2] / "mcp-package" / "src" / "clade_mcp"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_clade_{name}", PKG / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"_clade_{name}"] = module
    spec.loader.exec_module(module)
    return module


runtime = _load("runtime")


def test_no_blocking_subprocess_call_remains():
    body = (PKG / "runtime.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in body.splitlines()
                     if not line.lstrip().startswith("#"))
    code = re.sub(r'"""_.*?"""', "", code, flags=re.S)
    assert not re.search(r"(?<!asyncio\.)\bsubprocess\.(run|call|check_output|Popen)\b", code), \
        "a blocking shellout is back on the event loop"


def test_the_server_awaits_the_async_path():
    body = (PKG / "server.py").read_text(encoding="utf-8")
    assert "await runtime.aexecute(" in body
    assert "runtime.execute(" not in body, "the sync wrapper is still called from async code"


@pytest.mark.parametrize("attr", ["aexecute"])
def test_both_runtimes_expose_the_async_entry_point(attr):
    for cls in (runtime.ClaudeRuntime, runtime.CodexRuntime):
        assert asyncio.iscoroutinefunction(getattr(cls, attr))


def test_two_runs_overlap_instead_of_queueing():
    # The property, not the spelling. Blocking, these take ~1.6s; concurrent,
    # ~0.8s. The threshold sits between, with room for a slow machine.
    async def scenario():
        started = time.monotonic()
        await asyncio.gather(
            runtime._run_bounded(["sleep", "0.8"], timeout=20),
            runtime._run_bounded(["sleep", "0.8"], timeout=20),
        )
        return time.monotonic() - started

    assert asyncio.run(scenario()) < 1.4


def test_stdout_and_exit_code_come_back():
    code, out, err = asyncio.run(
        runtime._run_bounded([sys.executable, "-c", "print('hi')"], timeout=20))
    assert code == 0 and out.strip() == "hi" and err == ""


def test_stdin_reaches_the_child():
    # CodexRuntime pipes the prompt in; DEVNULL would silently send an empty one.
    code, out, _ = asyncio.run(runtime._run_bounded(
        [sys.executable, "-c", "import sys;print(sys.stdin.read().strip())"],
        timeout=20, stdin_text="the prompt"))
    assert code == 0 and out.strip() == "the prompt"


def test_a_missing_executable_raises_filenotfound():
    with pytest.raises(FileNotFoundError):
        asyncio.run(runtime._run_bounded(["definitely-not-a-real-binary-xyz"], timeout=5))


def test_a_timeout_raises_and_does_not_hang():
    started = time.monotonic()
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(runtime._run_bounded(["sleep", "30"], timeout=0.5))
    assert time.monotonic() - started < 8, "the timeout path itself blocked"


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="POSIX process groups only")
def test_a_timeout_kills_the_grandchild_too(tmp_path):
    # `claude -p` spawns its own tools. Killing only the direct child leaves
    # those running and holding the pipes — which is why the drain is bounded
    # and the child gets its own session.
    marker = tmp_path / "grandchild-alive"
    script = tmp_path / "parent.py"
    script.write_text(
        "import subprocess,sys,time\n"
        f"subprocess.Popen([sys.executable,'-c',\"import time,pathlib;\"\n"
        f"  \"[ (pathlib.Path(r'{marker}').write_text(str(i)), time.sleep(0.2)) \"\n"
        f"  \"for i in range(50) ]\"])\n"
        "time.sleep(30)\n", encoding="utf-8")

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(runtime._run_bounded([sys.executable, str(script)], timeout=1.5))

    time.sleep(0.5)
    first = marker.read_text() if marker.exists() else ""
    time.sleep(1.0)
    second = marker.read_text() if marker.exists() else ""
    assert first == second, f"a grandchild survived the kill (wrote {first!r} then {second!r})"


def test_the_sync_wrapper_refuses_inside_a_running_loop():
    # It stays on the published surface, but blocking an event loop for 300s is
    # the failure this whole change removes.
    async def scenario():
        with pytest.raises(RuntimeError, match="running event loop"):
            runtime.ClaudeRuntime().execute("p", Path("."), timeout=1)

    asyncio.run(scenario())


def test_the_sync_wrapper_still_works_off_a_loop(monkeypatch):
    async def fake(self, prompt, project_dir, *, timeout=300, env=None):
        return runtime.RuntimeResult("ok")

    monkeypatch.setattr(runtime.ClaudeRuntime, "aexecute", fake)
    assert runtime.ClaudeRuntime().execute("p", Path("."), timeout=1).text == "ok"


def test_the_child_gets_its_own_session():
    code, out, _ = asyncio.run(runtime._run_bounded(
        [sys.executable, "-c", "import os;print(os.getpid()==os.getpgid(0))"], timeout=20))
    assert code == 0 and out.strip() == "True", \
        "the child shares our process group, so killpg would signal us too"


def test_cancellation_reaps_the_child():
    async def scenario():
        task = asyncio.ensure_future(runtime._run_bounded(["sleep", "30"], timeout=60))
        await asyncio.sleep(0.3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    started = time.monotonic()
    asyncio.run(scenario())
    assert time.monotonic() - started < 8, "cancellation left the child holding the pipes"


def test_signal_module_is_actually_imported():
    # _kill_process_group references signal.SIGKILL; an unimported name here
    # turns the timeout path into a NameError inside an except block.
    assert runtime.signal.SIGKILL == signal.SIGKILL
