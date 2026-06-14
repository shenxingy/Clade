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


class TestProjectIsFrontend:
    """The combined gate: CLAUDE.md text signal OR package.json framework dep.
    package.json is the authoritative signal for real projects."""

    def _w(self, tmp_path):
        class W:
            _project_dir = tmp_path
            _original_project_dir = tmp_path
            _claude_dir = tmp_path / ".claude"
        return W()

    def test_detects_via_package_json_when_claude_md_is_prose(self, tmp_path):
        # Regression: scamai-landing's CLAUDE.md says "Built with Next.js 15" in
        # prose (no structured 'Frontend:' line) — text signal alone returns False.
        (tmp_path / "CLAUDE.md").write_text("# Project\nBuilt with Next.js 15 (App Router).\n")
        (tmp_path / "package.json").write_text(
            '{"dependencies": {"next": "15.0.0", "react": "18.0.0"}}'
        )
        assert wtf._is_frontend_project((tmp_path / "CLAUDE.md").read_text()) is False
        assert wtf._project_is_frontend(self._w(tmp_path)) is True  # package.json catches it

    def test_detects_via_claude_md_when_no_package_json(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("- Frontend: Vite + React\n")
        assert wtf._project_is_frontend(self._w(tmp_path)) is True

    def test_backend_only_python_project_is_not_frontend(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("- Type: api-only\n- Frontend: N/A\n")
        (tmp_path / "package.json").write_text('{"dependencies": {"express": "4.0.0"}}')
        assert wtf._project_is_frontend(self._w(tmp_path)) is False

    def test_no_signals_is_not_frontend(self, tmp_path):
        assert wtf._project_is_frontend(self._w(tmp_path)) is False


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
