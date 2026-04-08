"""
swarm.py — SwarmManager: N-slot autonomous task execution.

Extracted from worker.py to keep that file under 1500 lines.

Imports:
    from swarm import SwarmManager
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from config import GLOBAL_SETTINGS, _deps_met

logger = logging.getLogger(__name__)


class SwarmManager:
    """N-slot swarm: auto-claims tasks and fills worker slots.

    State machine: idle → active → draining → done/stopped
    """

    def __init__(self, session: Any):
        self._session = session
        self._status = "idle"  # idle/active/draining/done/stopped
        self._done_reason: str | None = None
        self._target_slots = 0
        self._active_worker_ids: set[str] = set()
        self._stats = {"started": 0, "done": 0, "failed": 0}
        self._task: asyncio.Task | None = None
        self._started_at: float | None = None

    @property
    def status(self) -> str:
        return self._status

    def to_dict(self) -> dict:
        running = sum(
            1 for wid in self._active_worker_ids
            if (w := self._session.worker_pool.workers.get(wid)) and w.status in ("running", "starting")
        )
        elapsed = int(time.time() - self._started_at) if self._started_at else 0
        return {
            "status": self._status,
            "target_slots": self._target_slots,
            "running": running,
            "stats": dict(self._stats),
            "done_reason": self._done_reason,
            "elapsed_s": elapsed,
        }

    def start(self, slots: int) -> dict:
        if self._status == "active":
            return {"error": "Swarm already active"}
        self._status = "active"
        self._done_reason = None
        self._target_slots = max(1, min(slots, 20))
        self._active_worker_ids = set()
        self._stats = {"started": 0, "done": 0, "failed": 0}
        self._started_at = time.time()
        self._task = asyncio.create_task(self._refill_loop())
        return self.to_dict()

    def stop(self) -> dict:
        if self._status != "active":
            return {"error": f"Swarm is {self._status}, not active"}
        self._status = "draining"
        return self.to_dict()

    async def force_stop(self) -> dict:
        self._status = "stopped"
        self._done_reason = "force_stopped"
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None
        # Kill all swarm-tracked workers
        for wid in list(self._active_worker_ids):
            w = self._session.worker_pool.workers.get(wid)
            if w and w.status in ("running", "starting"):
                await w.stop()
                await self._session.task_queue.update(w.task_id, status="failed")
                w.status = "failed"
        self._active_worker_ids.clear()
        return self.to_dict()

    def resize(self, new_slots: int) -> dict:
        if self._status != "active":
            return {"error": f"Swarm is {self._status}, cannot resize"}
        self._target_slots = max(1, min(new_slots, 20))
        return self.to_dict()

    async def _refill_loop(self) -> None:
        """Core loop: count running → clean finished → claim tasks → fill slots → wait."""
        try:
            while self._status in ("active", "draining"):
                await self._refill_once()
                # Wait before next check (faster than status_loop's 1s)
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Swarm refill_loop error")
            self._status = "stopped"
            self._done_reason = "error"

    async def _refill_once(self) -> None:
        pool = self._session.worker_pool
        tq = self._session.task_queue

        # Clean up finished workers from tracking set
        finished_ids = set()
        for wid in list(self._active_worker_ids):
            w = pool.workers.get(wid)
            if w is None or w.status in ("done", "failed"):
                finished_ids.add(wid)
                if w and w.status == "done":
                    self._stats["done"] += 1
                elif w and w.status == "failed":
                    self._stats["failed"] += 1
        self._active_worker_ids -= finished_ids

        # Count currently running swarm workers
        running = sum(
            1 for wid in self._active_worker_ids
            if (w := pool.workers.get(wid)) and w.status in ("running", "starting")
        )

        # If draining, just wait for current workers to finish
        if self._status == "draining":
            if running == 0:
                self._status = "stopped"
                self._done_reason = "drained"
            return

        # Calculate how many slots to fill; also respect global max_workers
        global_max = GLOBAL_SETTINGS.get("max_workers", 0)
        total_running = sum(1 for w in pool.workers.values() if w.status in ("running", "starting"))
        if global_max > 0:
            global_available = max(0, global_max - total_running)
        else:
            global_available = self._target_slots  # no global limit
        to_fill = min(self._target_slots - running, global_available)

        if to_fill <= 0:
            if running > 0:
                return  # slots full, wait for workers to finish
            # Global cap held by non-swarm workers — don't conclude completion
            if global_max > 0 and global_available == 0 and total_running > 0:
                return

        # Get done task IDs for dependency checks
        all_tasks = await tq.list()
        done_ids = {t["id"] for t in all_tasks if t["status"] == "done"}

        # Try to claim and start tasks
        claimed_any = False
        for _ in range(max(to_fill, 0)):
            task = await tq.claim_next_pending(done_ids)
            if task is None:
                break
            claimed_any = True
            worker = await pool.start_worker(
                task, tq, self._session.project_dir, self._session.claude_dir
            )
            self._active_worker_ids.add(worker.id)
            self._stats["started"] += 1

        # Check completion conditions
        if not claimed_any and running == 0:
            # No tasks claimed, no workers running — check why
            pending = [t for t in all_tasks if t["status"] == "pending"]
            if not pending:
                # No pending tasks at all → all complete
                self._status = "done"
                self._done_reason = "all_complete"
            else:
                # Pending tasks exist but none were claimable (all blocked by deps)
                blocked_pending = [t for t in pending if not _deps_met(t, done_ids)]
                if len(blocked_pending) == len(pending):
                    # All pending tasks are blocked and nothing is running to unblock them
                    self._status = "done"
                    self._done_reason = "blocked"
                # else: some tasks have deps met but were claimed by another path — wait
