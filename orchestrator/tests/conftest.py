"""Shared fixtures for orchestrator tests."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

# Add orchestrator dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Mock worker modules before they get imported anywhere (prevents real Claude CLI calls
# from _score_task being scheduled during import_from_proposed tests).
# Pure functions (_extract_tldr_sections) are loaded from the real module so they
# can be tested directly in test_worker_modules.py.
import importlib.util as _ilu

_wt_spec = _ilu.spec_from_file_location(
    "worker_tldr_real",
    Path(__file__).parent.parent / "worker_tldr.py",
)
_wt_real = _ilu.module_from_spec(_wt_spec)
_wt_spec.loader.exec_module(_wt_real)  # type: ignore[union-attr]

_mock_worker_tldr = MagicMock()
_mock_worker_tldr._score_task = AsyncMock(return_value=None)
_mock_worker_tldr._generate_code_tldr = MagicMock(return_value="")
_mock_worker_tldr._extract_tldr_sections = _wt_real._extract_tldr_sections
_mock_worker_tldr._localize_tldr_for_task = AsyncMock(return_value="")
sys.modules.setdefault("worker_tldr", _mock_worker_tldr)

_wr_spec = _ilu.spec_from_file_location(
    "worker_review_real",
    Path(__file__).parent.parent / "worker_review.py",
)
_wr_real = _ilu.module_from_spec(_wr_spec)
_wr_spec.loader.exec_module(_wr_real)  # type: ignore[union-attr]

_mock_worker_review = MagicMock()
_mock_worker_review._write_pr_review = AsyncMock(return_value="")
_mock_worker_review._write_progress_entry = AsyncMock(return_value="")
_mock_worker_review._format_oracle_rejection = _wr_real._format_oracle_rejection
sys.modules.setdefault("worker_review", _mock_worker_review)

_mock_worker = MagicMock()
_mock_worker.SwarmManager = MagicMock()
_mock_worker.WorkerPool = MagicMock()
sys.modules.setdefault("worker", _mock_worker)

from task_queue import TaskQueue  # noqa: E402 — must come after sys.modules patch


@pytest.fixture
def tmp_claude_dir(tmp_path: Path) -> Path:
    """Temporary .claude directory with SQLite DB."""
    d = tmp_path / ".claude"
    d.mkdir()
    return d


@pytest_asyncio.fixture
async def task_queue(tmp_claude_dir: Path) -> TaskQueue:
    """Initialized TaskQueue backed by a temporary SQLite DB."""
    tq = TaskQueue(tmp_claude_dir)
    await tq._ensure_db()
    return tq
