"""
Process manager — start.sh lifecycle control from the GUI.
Manages start.sh processes across multiple projects.
Depends on: config.py (leaf)
"""

from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import signal
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# ─── StartProcess ────────────────────────────────────────────────────────────


class StartProcess:
    """Wraps a single start.sh subprocess for a project."""

    def __init__(self, project_dir: Path, mode: str = "--run",
                 args: list[str] | None = None):
        self.project_dir = project_dir
        self.mode = mode
        self.args = args or []
        self.proc: asyncio.subprocess.Process | None = None
        self.pid: int | None = None
        self.started_at: float = 0
        self._stopped_at: float | None = None
        self.status = "stopped"  # running | stopped | converged | failed | blocked
        self._log_buf: list[str] = []

    @property
    def project_name(self) -> str:
        return self.project_dir.name

    @property
    def elapsed_s(self) -> int:
        if not self.started_at:
            return 0
        end = time.time() if self.status == "running" else (self._stopped_at or time.time())
        return int(end - self.started_at)

    async def start(self) -> bool:
        """Launch start.sh. Returns False if lock is held."""
        if self.status == "running" and self.proc:
            return True
        # Check flock before launching
        lock_file = self.project_dir / ".claude" / "start.lock"
        if lock_file.exists() and _is_locked(lock_file):
            logger.warning("start.lock is held for %s — skipping", self.project_dir)
            self.status = "blocked"
            return False

        start_sh = Path.home() / ".claude" / "scripts" / "start.sh"
        if not start_sh.exists():
            logger.error("start.sh not found at %s", start_sh)
            self.status = "failed"
            return False

        cmd = ["bash", str(start_sh), self.mode] + self.args
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(self.project_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                preexec_fn=os.setsid,
            )
            self.pid = self.proc.pid
            self.started_at = time.time()
            self._stopped_at = None
            self.status = "running"
            asyncio.create_task(self._read_output())
            logger.info("Started start.sh for %s (pid=%s, mode=%s)",
                        self.project_name, self.pid, self.mode)
            return True
        except Exception as e:
            logger.error("Failed to start start.sh for %s: %s", self.project_dir, e)
            self.status = "failed"
            return False

    async def _read_output(self) -> None:
        """Read stdout/stderr and buffer last 100 lines."""
        if not self.proc or not self.proc.stdout:
            return
        try:
            while True:
                line = await self.proc.stdout.readline()
                if not line:
                    break
                text = line.decode(errors="replace").rstrip()
                self._log_buf.append(text)
                if len(self._log_buf) > 100:
                    self._log_buf = self._log_buf[-100:]
        except Exception as e:
            logger.warning("_read_output(%s) error: %s", self.project_name, e)
        # Process finished
        self._stopped_at = time.time()
        rc = self.proc.returncode
        if rc == 0:
            self.status = "converged"
        elif self.status == "running":
            self.status = "failed"

    async def stop(self) -> None:
        """Send SIGTERM (start.sh traps it gracefully)."""
        if self.proc and self.proc.returncode is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
                try:
                    await asyncio.wait_for(self.proc.wait(), timeout=15)
                except asyncio.TimeoutError:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                    await self.proc.wait()
            except ProcessLookupError:
                pass
        self.status = "stopped"
        self._stopped_at = time.time()

    def read_report(self) -> str | None:
        """Read latest session-report-*.md from project's .claude dir."""
        claude_dir = self.project_dir / ".claude"
        reports = sorted(claude_dir.glob("session-report-*.md"), reverse=True)
        if reports:
            try:
                return reports[0].read_text(errors="replace")[:10000]
            except Exception:
                pass
        return None

    def read_progress(self) -> str | None:
        """Read session-progress.md for live stats."""
        progress_file = self.project_dir / ".claude" / "session-progress.md"
        if progress_file.exists():
            try:
                return progress_file.read_text(errors="replace")[:5000]
            except Exception:
                pass
        return None

    def read_cost(self) -> float:
        """Read total cost from loop-cost.log."""
        cost_file = self.project_dir / ".claude" / "loop-cost.log"
        if not cost_file.exists():
            return 0.0
        try:
            lines = cost_file.read_text().strip().splitlines()
            return sum(float(l.strip()) for l in lines if l.strip())
        except Exception:
            return 0.0

    @property
    def log_tail(self) -> str:
        return "\n".join(self._log_buf[-20:])

    def to_dict(self) -> dict:
        return {
            "project_dir": str(self.project_dir),
            "project_name": self.project_name,
            "mode": self.mode,
            "status": self.status,
            "pid": self.pid,
            "started_at": self.started_at,
            "elapsed_s": self.elapsed_s,
            "cost": self.read_cost(),
            "log_tail": self.log_tail,
        }


# ─── ProcessPool ─────────────────────────────────────────────────────────────


class ProcessPool:
    """Manages multiple StartProcess instances across projects."""

    def __init__(self):
        self._processes: dict[str, StartProcess] = {}  # keyed by project_dir str

    async def start(self, project_dir: Path, mode: str = "--run",
                    args: list[str] | None = None) -> StartProcess:
        key = str(project_dir)
        # Stop existing if any
        if key in self._processes and self._processes[key].status == "running":
            await self._processes[key].stop()
        proc = StartProcess(project_dir, mode, args)
        self._processes[key] = proc
        await proc.start()
        return proc

    async def stop(self, project_dir: str | Path) -> bool:
        key = str(project_dir)
        if key in self._processes:
            await self._processes[key].stop()
            return True
        return False

    async def stop_all(self) -> int:
        count = 0
        for proc in list(self._processes.values()):
            if proc.status == "running":
                await proc.stop()
                count += 1
        return count

    def get(self, project_dir: str | Path) -> StartProcess | None:
        return self._processes.get(str(project_dir))

    def list_all(self) -> list[StartProcess]:
        return list(self._processes.values())

    def list_active(self) -> list[StartProcess]:
        return [p for p in self._processes.values() if p.status == "running"]

    async def poll(self) -> None:
        """Check process health — called from status_loop."""
        for key, proc in list(self._processes.items()):
            # Only update status for processes we think are running
            if proc.status != "running" or not proc.proc:
                continue
            if proc.proc.returncode is not None:
                proc._stopped_at = time.time()
                proc.status = "converged" if proc.proc.returncode == 0 else "failed"

    def to_list(self) -> list[dict]:
        return [p.to_dict() for p in self._processes.values()]


# Global process pool (shared across sessions)
process_pool = ProcessPool()


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _is_locked(lock_path: Path) -> bool:
    """Check if a file is flock-ed by another process."""
    try:
        fd = os.open(str(lock_path), os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False  # we got the lock, so it's not held
        except (IOError, OSError):
            return True  # lock is held
        finally:
            os.close(fd)
    except Exception:
        return False
