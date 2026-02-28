"""Shared fixtures for orchestrator tests."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

# Add orchestrator dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Mock worker module before it gets imported anywhere (prevents real Claude CLI calls
# from _score_task being scheduled during import_from_proposed tests).
_mock_worker = MagicMock()
_mock_worker._score_task = AsyncMock(return_value=None)
_mock_worker.SwarmManager = MagicMock()
_mock_worker.WorkerPool = MagicMock()
_mock_worker._generate_code_tldr = AsyncMock(return_value="")
_mock_worker._write_pr_review = AsyncMock(return_value="")
_mock_worker._write_progress_entry = AsyncMock(return_value="")
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
