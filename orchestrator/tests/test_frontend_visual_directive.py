"""Visual self-verification directive (Anthropic visual feedback loop).

Frontend projects get a directive telling the worker to verify UI changes in a
real browser AS IT WORKS. Covers the pure frontend detector and that the directive
is injected only for frontend projects.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ORCH = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("_real_taskfile_fv", _ORCH / "worker_taskfile.py")
wtf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wtf)  # type: ignore[union-attr]


class TestIsFrontendProject:
    def test_web_fullstack_type(self):
        assert wtf._is_frontend_project("# Project Type\n- Type: web-fullstack\n")

    def test_frontend_line_with_framework(self):
        assert wtf._is_frontend_project("- Type: cli\n- Frontend: Next.js, port 3000\n")

    def test_frontend_na_is_not_frontend(self):
        assert not wtf._is_frontend_project("- Type: api-only\n- Frontend: N/A\n")

    def test_frontend_none_is_not_frontend(self):
        assert not wtf._is_frontend_project("- Frontend: none\n")

    def test_pure_cli_is_not_frontend(self):
        assert not wtf._is_frontend_project("- Type: cli\n- Backend: FastAPI, port 8000\n")

    def test_empty_is_not_frontend(self):
        assert not wtf._is_frontend_project("")


class TestReadProjectClaudeMd:
    def test_reads_repo_root_claude_md(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("- Type: web-fullstack\n")

        class W:
            _project_dir = tmp_path
            _original_project_dir = tmp_path
            _claude_dir = tmp_path / ".claude"
        assert "web-fullstack" in wtf._read_project_claude_md(W())

    def test_missing_returns_empty(self, tmp_path):
        class W:
            _project_dir = tmp_path
            _original_project_dir = tmp_path
            _claude_dir = tmp_path / ".claude"
        assert wtf._read_project_claude_md(W()) == ""


class TestDirectiveContent:
    """The directive must encode Anthropic's loop, not a post-hoc gate."""

    def test_block_mentions_browser_loop_and_evidence(self):
        b = wtf.FRONTEND_VISUAL_BLOCK
        assert "mcp__playwright__browser_navigate" in b
        assert "screenshot" in b.lower()
        assert "console" in b.lower()
        assert "iterat" in b.lower()  # iterate/iteration
        # self-gating phrasing so it's a no-op for backend-only tasks
        assert "renders or alters" in b.lower() or "any ui" in b.lower()
