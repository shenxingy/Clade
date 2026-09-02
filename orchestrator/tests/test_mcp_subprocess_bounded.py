"""The MCP server's shellouts must not block its event loop.

mcp_server handlers run on a single asyncio loop and the SDK dispatches
tools/call concurrently (start_soon per request). A blocking subprocess.run in
any handler froze the read loop, the stdout writer and every other in-flight
tool call for the whole timeout — up to 300s for a skill run, 15s per code
search. These pin the bounded, non-blocking replacement.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

import pytest

pytest.importorskip("mcp")

import mcp_server  # noqa: E402 — conftest puts orchestrator/ on sys.path


# ─── _run_bounded ─────────────────────────────────────────────────────────────


class TestRunBounded:
    async def test_returns_output_and_exit_code(self):
        assert await mcp_server._run_bounded(
            [sys.executable, "-c", "print('hi')"], timeout=30
        ) == (0, "hi\n", "")

    async def test_reports_nonzero_exit_and_stderr(self):
        rc, out, err = await mcp_server._run_bounded(
            [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"],
            timeout=30,
        )
        assert (rc, out) == (3, "")
        assert "boom" in err

    async def test_missing_executable_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            await mcp_server._run_bounded(
                ["clade-no-such-binary-12345"], timeout=30
            )

    async def test_env_is_passed_through(self):
        rc, out, _ = await mcp_server._run_bounded(
            [sys.executable, "-c", "import os; print(os.environ['CLADE_PROBE'])"],
            timeout=30,
            env={**os.environ, "CLADE_PROBE": "set"},
        )
        assert (rc, out) == (0, "set\n")

    async def test_timeout_reaps_the_whole_process_group(self, tmp_path):
        """`claude -p` spawns its own tool subprocesses. subprocess.run's
        timeout kills only the direct child, so a hung skill leaked its
        grandchildren; start_new_session + killpg is what closes that."""
        pidfile = tmp_path / "grandchild.pid"
        script = (
            "import subprocess, sys, time\n"
            "gc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            f"open({str(pidfile)!r}, 'w').write(str(gc.pid))\n"
            "time.sleep(60)\n"
        )
        with pytest.raises(asyncio.TimeoutError):
            await mcp_server._run_bounded(
                [sys.executable, "-c", script], timeout=2.5
            )

        assert pidfile.exists(), "grandchild never started; test is inconclusive"
        pid = int(pidfile.read_text())
        for _ in range(60):  # reaping is asynchronous; poll rather than sleep once
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.05)
        os.kill(pid, 9)  # don't leak it out of the test either
        pytest.fail(f"grandchild {pid} survived the timeout kill")


# ─── _execute_skill ───────────────────────────────────────────────────────────


@pytest.fixture
def one_skill(monkeypatch):
    monkeypatch.setattr(
        mcp_server,
        "load_skills",
        lambda: [
            {"name": "alpha", "prompt_content": "Prompt body for alpha"},
            {"name": "beta", "prompt_content": "Prompt body for beta"},
        ],
    )


class TestExecuteSkill:
    async def test_reports_timeout(self, one_skill, monkeypatch):
        async def _boom(*args, **kwargs):
            raise asyncio.TimeoutError

        monkeypatch.setattr(mcp_server, "_run_bounded", _boom)
        result = await mcp_server._execute_skill("alpha", "")
        assert result.is_error
        assert "timed out after 300s" in result.content[0].text

    async def test_summary_comes_from_the_bounded_run(self, one_skill, monkeypatch):
        captured = {}

        async def _fake(cmd, *, timeout, env=None):
            captured["cmd"] = cmd
            captured["timeout"] = timeout
            return 0, '{"summary": "all done"}', ""

        monkeypatch.setattr(mcp_server, "_run_bounded", _fake)
        result = await mcp_server._execute_skill("alpha", "--dry-run")
        assert not result.is_error
        assert result.content[0].text == "all done"
        assert "Prompt body for alpha" in captured["cmd"][2]
        assert "--dry-run" in captured["cmd"][2]
        assert captured["timeout"] == mcp_server.SKILL_TIMEOUT_S

    async def test_run_skill_tool_executes_via_the_bounded_run(
        self, one_skill, monkeypatch
    ):
        """Same coverage test_mcp_compact's test_run_skill_executes_via_claude
        had before the seam moved off `subprocess.run`."""
        captured = {}

        async def _fake(cmd, *, timeout, env=None):
            captured["cmd"] = cmd
            return 0, '{"summary": "all done"}', ""

        monkeypatch.setattr(mcp_server, "_run_bounded", _fake)
        result = await mcp_server.call_tool(
            "clade_run_skill", {"name": "alpha", "args": "--dry-run"}
        )
        assert not getattr(result, "is_error", False)
        assert result.content[0].text == "all done"
        prompt = captured["cmd"][2]
        assert "Prompt body for alpha" in prompt
        assert "--dry-run" in prompt  # args reached the skill prompt

    async def test_per_skill_tool_name_still_works(self, one_skill, monkeypatch):
        """Clients with cached enumeration-mode tool lists must not break."""

        async def _fake(cmd, *, timeout, env=None):
            return 0, '{"summary": "ok"}', ""

        monkeypatch.setattr(mcp_server, "_run_bounded", _fake)
        result = await mcp_server.call_tool("clade_beta", {})
        assert result.content[0].text == "ok"

    async def test_nonzero_exit_is_an_error_result(self, one_skill, monkeypatch):
        async def _fake(cmd, *, timeout, env=None):
            return 2, "", "traceback here"

        monkeypatch.setattr(mcp_server, "_run_bounded", _fake)
        result = await mcp_server._execute_skill("alpha", "")
        assert result.is_error
        assert "exit 2" in result.content[0].text
        assert "traceback here" in result.content[0].text


# ─── clade_search_code ────────────────────────────────────────────────────────


def _fake_rg(tmp_path, body: str, monkeypatch):
    """Put a stub `rg` first on PATH so the search shells out to it."""
    rg = tmp_path / "rg"
    rg.write_text(f"#!/bin/sh\n{body}\n")
    rg.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")


class TestSearchCode:
    async def test_does_not_block_the_event_loop(self, tmp_path, monkeypatch):
        """THE regression. Against the old synchronous subprocess.run the
        ticker below gets zero ticks: every other MCP request is frozen for the
        duration of the search."""
        _fake_rg(tmp_path, "sleep 0.4", monkeypatch)
        ticks = 0

        async def _ticker():
            nonlocal ticks
            for _ in range(40):
                await asyncio.sleep(0.005)
                ticks += 1

        result, _ = await asyncio.gather(
            mcp_server.call_tool(
                "clade_search_code", {"snippet": "x", "project_dir": str(tmp_path)}
            ),
            _ticker(),
        )
        assert "No matches" in result.content[0].text
        assert ticks > 5, f"event loop was blocked during the search ({ticks} ticks)"

    async def test_timeout_is_reported_not_raised(self, tmp_path, monkeypatch):
        _fake_rg(tmp_path, "sleep 30", monkeypatch)
        monkeypatch.setattr(mcp_server, "SEARCH_TIMEOUT_S", 0.3)
        result = await mcp_server.call_tool(
            "clade_search_code", {"snippet": "x", "project_dir": str(tmp_path)}
        )
        assert "timed out after 0.3s" in result.content[0].text

    async def test_matches_are_returned(self, tmp_path, monkeypatch):
        _fake_rg(tmp_path, "echo 'file.py:1:needle'", monkeypatch)
        result = await mcp_server.call_tool(
            "clade_search_code", {"snippet": "needle", "project_dir": str(tmp_path)}
        )
        assert "file.py:1:needle" in result.content[0].text
