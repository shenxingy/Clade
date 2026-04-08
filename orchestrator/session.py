"""
Orchestrator session — PTY wrapper, project sessions, registry, status loop.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shlex
import time
import uuid
from datetime import datetime
from pathlib import Path

import ptyprocess
from fastapi import HTTPException, Query
from watchfiles import awatch

from config import (
    GLOBAL_SETTINGS,
    _MODEL_ALIASES,
    _deps_met,
    _fire_notification,
    _recover_orphaned_tasks,
)
from task_queue import TaskQueue
from swarm import SwarmManager
from worker import WorkerPool, _rank_tasks
from worker_tldr import _generate_code_tldr

logger = logging.getLogger(__name__)

# ─── Orchestrator Session (PTY) ───────────────────────────────────────────────


class OrchestratorSession:
    def __init__(self):
        self.pty: ptyprocess.PtyProcess | None = None
        self.clients: list = []
        self._running = False
        self._read_task: asyncio.Task | None = None

    def start(self, project_dir: Path, rows: int = 24, cols: int = 80) -> None:
        if self.pty and self.pty.isalive():
            return
        env = {**os.environ, "TERM": "xterm-256color"}
        self.pty = ptyprocess.PtyProcess.spawn(
            ["claude", "--dangerously-skip-permissions"],
            env=env,
            dimensions=(rows, cols),
            cwd=str(project_dir),
        )
        self._running = True
        self._read_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while self._running and self.pty and self.pty.isalive():
            try:
                data = await loop.run_in_executor(None, self._read_chunk)
                if data:
                    msg = json.dumps({"type": "output", "data": data})
                    dead = []
                    for ws in list(self.clients):
                        try:
                            await ws.send_text(msg)
                        except Exception:
                            dead.append(ws)
                    for ws in dead:
                        if ws in self.clients:
                            self.clients.remove(ws)
            except Exception:
                await asyncio.sleep(0.05)

    def _read_chunk(self) -> str:
        try:
            raw = self.pty.read(4096)
            return raw.decode("utf-8", errors="replace")
        except Exception:
            return ""

    def send_input(self, text: str) -> None:
        if self.pty and self.pty.isalive():
            self.pty.write(text.encode())

    def resize(self, rows: int, cols: int) -> None:
        if self.pty and self.pty.isalive():
            self.pty.setwinsize(rows, cols)

    def stop(self) -> None:
        self._running = False
        if hasattr(self, '_read_task') and self._read_task and not self._read_task.done():
            self._read_task.cancel()
        if self.pty and self.pty.isalive():
            self.pty.terminate()

    def is_alive(self) -> bool:
        return self.pty is not None and self.pty.isalive()

# ─── Project Session ──────────────────────────────────────────────────────────


class ProjectSession:
    def __init__(self, path: str):
        self.session_id = str(uuid.uuid4())[:8]
        self.project_dir = Path(path)
        self.orchestrator = OrchestratorSession()
        self.worker_pool = WorkerPool()
        self.task_queue = TaskQueue(self.project_dir / ".claude")
        self.created_at = time.time()
        self.status_subscribers: list = []
        self.proposed_tasks_subscribers: list = []
        self._blockers_mtime: float = 0.0
        self._watch_task: asyncio.Task | None = None
        # Scheduler state
        self._scheduled_start: datetime | None = None
        self._schedule_triggered: bool = False
        self._schedule_loaded: bool = False
        # Run-complete notification state
        self._run_complete: bool = False
        # Iteration loop coroutine
        self._loop_task: asyncio.Task | None = None
        # Swarm manager
        self._swarm: SwarmManager | None = None
        self._budget_exceeded: bool = False
        self._failure_notified: bool = False
        # Status loop timer attrs (used by status_loop via getattr fallback)
        self._last_autoscale: float = 0.0
        self._ci_watcher_last: float = 0.0
        self._coverage_scan_last: float = 0.0
        self._dep_update_last: float = 0.0
        self._priority_rank_last: float = 0.0

    @property
    def name(self) -> str:
        return self.project_dir.name

    @property
    def claude_dir(self) -> Path:
        return self.project_dir / ".claude"

    def _schedule_dict(self) -> dict | None:
        if not self._scheduled_start:
            return None
        now = datetime.now()
        return {
            "at": self._scheduled_start.isoformat(),
            "in_seconds": max(0, int((self._scheduled_start - now).total_seconds())),
            "triggered": self._schedule_triggered,
        }

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "name": self.name,
            "path": str(self.project_dir),
            "worker_count": len(self.worker_pool.all()),
            "running_count": sum(
                1 for w in self.worker_pool.all() if w.status == "running"
            ),
            "alive": self.orchestrator.is_alive(),
            "schedule": self._schedule_dict(),
        }

    def start_watch(self) -> None:
        if self._watch_task is None or self._watch_task.done():
            self._watch_task = asyncio.create_task(
                _watch_session_proposed_tasks(self)
            )

    async def _run_supervisor(self) -> None:
        """Iterative review-fix loop (Ralph-style supervisor)."""
        consecutive_empty = 0
        while True:
            loop_state = await self.task_queue.get_loop()
            if not loop_state or loop_state["status"] != "running":
                return

            mode = loop_state.get("mode", "review")
            if mode == "plan_build":
                await self._run_plan_build()
                return

            iteration = loop_state["iteration"] + 1
            await self.task_queue.upsert_loop(iteration=iteration)

            # Read artifact
            artifact_path = loop_state["artifact_path"]
            try:
                content = Path(artifact_path).read_text(errors="replace")
            except Exception:
                await self.task_queue.upsert_loop(status="cancelled")
                return

            model_short = loop_state.get("supervisor_model", "sonnet")
            model = _MODEL_ALIASES.get(model_short, "claude-sonnet-4-6")

            prompt = (
                "Review the following artifact. Output ONLY a JSON array, no prose.\n"
                "Each element must be exactly one of:\n"
                '  {"type":"FIXABLE","description":"...","task":"imperative task description for a worker"}\n'
                '  {"type":"DATA_CHECK","description":"...","query":"what to verify in codebase"}\n'
                '  {"type":"DEFERRED","description":"...","reason":"why human/retraining needed"}\n'
                '  {"type":"CONVERGED","description":"no significant issues"}\n\n'
                "Artifact:\n---ARTIFACT---\n"
                f"{content}\n"
                "---END---"
            )

            prompt_file = self.claude_dir / f"supervisor-iter-{iteration}.md"
            response = ""
            try:
                prompt_file.write_text(prompt, errors="replace")
                _env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
                proc = await asyncio.create_subprocess_shell(
                    f'claude -p "$(cat {shlex.quote(str(prompt_file))})" '
                    f'--model {model} --dangerously-skip-permissions',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    env=_env,
                )
                try:
                    out, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
                    response = out.decode().strip()
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.communicate()
                    response = ""
            except Exception:
                response = ""
            finally:
                prompt_file.unlink(missing_ok=True)

            if not response.strip():
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    await self.task_queue.upsert_loop(status="cancelled")
                    logger.warning("Loop cancelled: 3 consecutive empty supervisor responses")
                    return
                await asyncio.sleep(5)
                continue
            consecutive_empty = 0

            # Extract JSON array (supervisor may include prose around it)
            findings = []
            # Try direct parse first, then extract balanced JSON array
            try:
                findings = json.loads(response.strip())
            except Exception:
                start = response.find('[')
                if start != -1:
                    depth = 0
                    for i, ch in enumerate(response[start:], start):
                        if ch == '[': depth += 1
                        elif ch == ']': depth -= 1
                        if depth == 0:
                            try:
                                findings = json.loads(response[start:i+1])
                            except Exception:
                                pass
                            break

            # Re-check status after supervisor call
            loop_state = await self.task_queue.get_loop()
            if not loop_state or loop_state["status"] != "running":
                return

            context_dir = loop_state.get("context_dir") or str(self.project_dir)
            deferred_items = list(loop_state.get("deferred_items") or [])
            spawned_task_ids: list[str] = []
            converged = False

            for finding in findings:
                ftype = finding.get("type", "")
                if ftype == "CONVERGED":
                    converged = True
                    break
                elif ftype == "FIXABLE":
                    task_desc = (
                        f"[Loop-{iteration}] "
                        f"{finding.get('task', finding.get('description', ''))}"
                    )
                    task = await self.task_queue.add(task_desc, model_short)
                    spawned_task_ids.append(task["id"])
                    _max_w = GLOBAL_SETTINGS.get("max_workers", 0)
                    _running = sum(1 for w in self.worker_pool.workers.values() if w.status == "running")
                    if _max_w <= 0 or _running < _max_w:
                        await self.worker_pool.start_worker(
                            task, self.task_queue, self.project_dir, self.claude_dir
                        )
                    # else: task is queued; status_loop will auto-start it when a slot opens
                elif ftype == "DATA_CHECK":
                    query = finding.get("query", finding.get("description", ""))
                    task_desc = (
                        f"[Loop-{iteration}] Cross-check the following claim against "
                        f"the codebase at {context_dir}.\n"
                        f"Report what you find. Do NOT modify any files.\nQuery: {query}"
                    )
                    task = await self.task_queue.add(task_desc, model_short)
                    spawned_task_ids.append(task["id"])
                    _max_w = GLOBAL_SETTINGS.get("max_workers", 0)
                    _running = sum(1 for w in self.worker_pool.workers.values() if w.status == "running")
                    if _max_w <= 0 or _running < _max_w:
                        await self.worker_pool.start_worker(
                            task, self.task_queue, self.project_dir, self.claude_dir
                        )
                    # else: task is queued; status_loop will auto-start it when a slot opens
                elif ftype == "DEFERRED":
                    deferred_items.append({
                        "description": finding.get("description", ""),
                        "reason": finding.get("reason", ""),
                        "iteration": iteration,
                    })

            await self.task_queue.upsert_loop(deferred_items=deferred_items)

            if converged:
                await self.task_queue.upsert_loop(status="converged")
                asyncio.create_task(_fire_notification("loop_converged", self))
                asyncio.create_task(_suggest_next_goals(self))
                return

            # Wait for all spawned workers to finish
            if spawned_task_ids:
                while True:
                    loop_state = await self.task_queue.get_loop()
                    if not loop_state or loop_state["status"] != "running":
                        return
                    all_done = all(
                        (await self.task_queue.get(tid) or {}).get("status") in ("done", "failed", "blocked", "interrupted")
                        for tid in spawned_task_ids
                    )
                    if all_done:
                        break
                    await asyncio.sleep(3)

            changes_this_iter = len(spawned_task_ids)

            # Compute semantic diff hash for oscillation detection
            semantic_hash = ""
            try:
                diff_dir = loop_state.get("context_dir") or str(self.project_dir)
                diff_proc = await asyncio.create_subprocess_exec(
                    "git", "diff", "--stat",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    cwd=diff_dir,
                )
                try:
                    diff_out, _ = await asyncio.wait_for(diff_proc.communicate(), timeout=15)
                except asyncio.TimeoutError:
                    diff_proc.kill()
                    await diff_proc.communicate()
                    diff_out = b""
                if diff_out.strip():
                    sorted_lines = sorted(diff_out.decode().strip().splitlines())
                    semantic_hash = hashlib.md5("\n".join(sorted_lines).encode()).hexdigest()[:12]
            except Exception:
                pass

            loop_state = await self.task_queue.get_loop()
            if not loop_state:
                return

            changes_history = list(loop_state.get("changes_history") or [])
            # Migration: wrap old int entries as dicts
            changes_history = [
                e if isinstance(e, dict) else {"count": e, "hash": ""}
                for e in changes_history
            ]
            changes_history.append({"count": changes_this_iter, "hash": semantic_hash})

            k = loop_state.get("convergence_k", 2)
            n = loop_state.get("convergence_n", 3)
            max_iter = loop_state.get("max_iterations", 20)

            # Dual convergence: count-based OR semantic hash repetition
            recent_n = changes_history[-n:] if len(changes_history) >= n else []
            count_converged = len(recent_n) >= n and all(e["count"] <= k for e in recent_n)
            semantic_converged = (
                len(changes_history) >= 2
                and changes_history[-1]["hash"]
                and changes_history[-1]["hash"] == changes_history[-2]["hash"]
            )
            is_converged = count_converged or semantic_converged

            if is_converged or iteration >= max_iter:
                await self.task_queue.upsert_loop(
                    changes_history=changes_history,
                    status="converged",
                )
                asyncio.create_task(_fire_notification("loop_converged", self))
                asyncio.create_task(_suggest_next_goals(self))
                return

            await self.task_queue.upsert_loop(changes_history=changes_history)

            # Check if paused/cancelled before starting next iteration
            loop_state = await self.task_queue.get_loop()
            if not loop_state or loop_state["status"] != "running":
                return

    async def _run_plan_build(self) -> None:
        """Two-phase plan_build supervisor.

        PLAN phase: reads the artifact + codebase file listing, calls Claude to
        write IMPLEMENTATION_PLAN.md (a markdown checklist) in context_dir.

        BUILD phase: reads the plan, picks the first unchecked item, spawns ONE
        FIXABLE worker, waits for it to complete, marks the item done, and
        repeats until no unchecked items remain or max_iterations is reached.
        """
        loop_state = await self.task_queue.get_loop()
        if not loop_state:
            return

        model_short = loop_state.get("supervisor_model", "sonnet")
        model = _MODEL_ALIASES.get(model_short, "claude-sonnet-4-6")
        context_dir = loop_state.get("context_dir") or str(self.project_dir)
        artifact_path = loop_state["artifact_path"]
        plan_path = Path(context_dir) / "IMPLEMENTATION_PLAN.md"

        # ── PLAN phase ────────────────────────────────────────────────────────
        plan_phase = loop_state.get("plan_phase") or "plan"
        if plan_phase == "plan":
            try:
                artifact_content = Path(artifact_path).read_text(errors="replace")
            except Exception:
                await self.task_queue.upsert_loop(status="cancelled")
                logger.warning("plan_build: cannot read artifact; cancelling")
                return

            # Collect codebase context — prefer TLDR, fallback to find
            try:
                file_listing = await asyncio.to_thread(
                    _generate_code_tldr, context_dir
                )
            except Exception:
                file_listing = ""
            if not file_listing:
                try:
                    proc = await asyncio.create_subprocess_shell(
                        f'find {shlex.quote(context_dir)} -type f -not -path "*/.*" | head -200',
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
                    file_listing = out.decode().strip() or "(no files found)"
                except Exception:
                    file_listing = "(could not list files)"

            prompt = (
                "You are a planning agent. Given an artifact and a codebase file listing, "
                "produce a concrete implementation plan.\n\n"
                "Output ONLY a markdown document (to be saved as IMPLEMENTATION_PLAN.md).\n"
                "The document must contain a checklist of concrete, self-contained tasks "
                "that can each be executed by a single Claude Code worker. "
                "Use this exact format for each task:\n"
                "  - [ ] <imperative task description>\n\n"
                "You may add a brief # header and a short context paragraph before the checklist, "
                "but do not add prose between checklist items.\n\n"
                f"Codebase files ({context_dir}):\n{file_listing}\n\n"
                f"Artifact:\n---ARTIFACT---\n{artifact_content}\n---END---"
            )

            prompt_file = self.claude_dir / "plan-build-plan.md"
            response = ""
            try:
                prompt_file.write_text(prompt, errors="replace")
                _env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
                proc = await asyncio.create_subprocess_shell(
                    f'claude -p "$(cat {shlex.quote(str(prompt_file))})" '
                    f'--model {model} --dangerously-skip-permissions',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    env=_env,
                )
                try:
                    out, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
                    response = out.decode().strip()
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.communicate()
                    response = ""
            except Exception:
                response = ""
            finally:
                prompt_file.unlink(missing_ok=True)

            if not response.strip():
                await self.task_queue.upsert_loop(status="cancelled")
                logger.warning("plan_build: PLAN phase got empty response; cancelling")
                return

            plan_path.write_text(response, errors="replace")
            await self.task_queue.upsert_loop(plan_phase="build", iteration=1)

        # ── BUILD phase ───────────────────────────────────────────────────────
        while True:
            loop_state = await self.task_queue.get_loop()
            if not loop_state or loop_state["status"] != "running":
                return

            if not plan_path.exists():
                await self.task_queue.upsert_loop(status="cancelled")
                logger.warning("plan_build: IMPLEMENTATION_PLAN.md missing; cancelling")
                return

            plan_text = plan_path.read_text(errors="replace")
            lines = plan_text.splitlines()

            # Find first unchecked item
            task_line_idx = None
            task_desc = None
            for i, line in enumerate(lines):
                m = re.match(r'^\s*-\s*\[ \]\s*(.*)', line)
                if m:
                    task_line_idx = i
                    task_desc = m.group(1).strip()
                    break

            if task_line_idx is None:
                # All tasks done
                await self.task_queue.upsert_loop(status="converged")
                asyncio.create_task(_fire_notification("loop_converged", self))
                asyncio.create_task(_suggest_next_goals(self))
                return

            iteration = loop_state.get("iteration", 1)
            max_iter = loop_state.get("max_iterations", 20)
            if iteration >= max_iter:
                await self.task_queue.upsert_loop(status="converged")
                asyncio.create_task(_fire_notification("loop_converged", self))
                asyncio.create_task(_suggest_next_goals(self))
                return

            # Spawn one worker for this task
            worker_task_desc = f"[Plan-{iteration}] {task_desc}"
            task = await self.task_queue.add(worker_task_desc, model_short)
            _max_w = GLOBAL_SETTINGS.get("max_workers", 0)
            _running = sum(1 for w in self.worker_pool.workers.values() if w.status == "running")
            if _max_w <= 0 or _running < _max_w:
                await self.worker_pool.start_worker(
                    task, self.task_queue, self.project_dir, self.claude_dir
                )

            # Wait for the worker to finish
            while True:
                loop_state = await self.task_queue.get_loop()
                if not loop_state or loop_state["status"] != "running":
                    return
                t = await self.task_queue.get(task["id"])
                if (t or {}).get("status") in ("done", "failed", "blocked", "interrupted"):
                    break
                await asyncio.sleep(3)

            # Mark item done in the plan (- [ ] → - [x])
            lines[task_line_idx] = re.sub(
                r'^(\s*-\s*)\[ \]', r'\1[x]', lines[task_line_idx]
            )
            try:
                plan_path.write_text("\n".join(lines), errors="replace")
            except OSError as e:
                logger.error("plan_build: failed to write plan checkpoint: %s", e)
                await self.task_queue.upsert_loop(status="cancelled")
                return

            await self.task_queue.upsert_loop(iteration=iteration + 1)

# ─── Session Registry ─────────────────────────────────────────────────────────


class SessionRegistry:
    def __init__(self):
        self.sessions: dict[str, ProjectSession] = {}
        self._default_id: str | None = None

    def create(self, path: str) -> ProjectSession:
        s = ProjectSession(path)
        self.sessions[s.session_id] = s
        if self._default_id is None:
            self._default_id = s.session_id
        return s

    def get(self, session_id: str) -> ProjectSession | None:
        return self.sessions.get(session_id)

    def default(self) -> ProjectSession | None:
        return self.sessions.get(self._default_id) if self._default_id else None

    def all(self) -> list[ProjectSession]:
        return list(self.sessions.values())

    def remove(self, session_id: str) -> None:
        s = self.sessions.pop(session_id, None)
        if s:
            s.orchestrator.stop()
            if s._watch_task and not s._watch_task.done():
                s._watch_task.cancel()
            if s._loop_task and not s._loop_task.done():
                s._loop_task.cancel()
            if s._swarm:
                asyncio.create_task(s._swarm.force_stop())
            # Stop all running workers and schedule worktree cleanup
            for w in list(s.worker_pool.workers.values()):
                if w.status in ("running", "starting", "paused"):
                    asyncio.create_task(w.stop())
        if self._default_id == session_id:
            self._default_id = next(iter(self.sessions), None)


registry = SessionRegistry()

# ─── Dependency: resolve session from ?session= query param ───────────────────


def _resolve_session(session: str | None = Query(default=None)) -> ProjectSession:
    s = registry.get(session) if session else registry.default()
    if s is None:
        raise HTTPException(status_code=404, detail="No active session")
    return s

# ─── Proposed-tasks watcher ───────────────────────────────────────────────────


async def _watch_session_proposed_tasks(session: ProjectSession) -> None:
    target = session.claude_dir / "proposed-tasks.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch(exist_ok=True)
    try:
        async for _changes in awatch(str(target)):
            content = await asyncio.to_thread(target.read_text) if target.exists() else ""
            msg = json.dumps({
                "type": "proposed_tasks",
                "session_id": session.session_id,
                "content": content,
            })
            dead = []
            for ws in list(session.proposed_tasks_subscribers):
                try:
                    await ws.send_text(msg)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                session.proposed_tasks_subscribers.remove(ws)
    except asyncio.CancelledError:
        pass

# ─── Blockers check ───────────────────────────────────────────────────────────


async def _check_blockers(session: ProjectSession) -> None:
    f = session.claude_dir / "blockers.md"
    try:
        mtime = f.stat().st_mtime
    except FileNotFoundError:
        return
    if mtime <= session._blockers_mtime:
        return
    session._blockers_mtime = mtime
    running = [w for w in session.worker_pool.all() if w.status == "running"]
    if running:
        newest = max(running, key=lambda w: w.started_at)
        await newest.stop()
        newest.status = "blocked"
        await session.task_queue.update(newest.task_id, status="blocked")

# ─── Horizontal task decomposition ───────────────────────────────────────────


async def _decompose_horizontal(task: dict, session) -> None:
    """Decompose a HORIZONTAL task into per-file VERTICAL child tasks."""
    desc = task.get("description", "")
    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "--dangerously-skip-permissions", "--model", "claude-haiku-4-5-20251001", "-p",
            f"List the source files that need changes for this task. Output one file path per line, no explanation:\n{desc}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(session.project_dir),
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            stdout = b""
    except Exception as e:
        logger.warning("_decompose_horizontal failed: %s", e)
        return

    lines = [l.strip() for l in stdout.decode().splitlines() if l.strip() and not l.strip().startswith("#")]
    files = lines[:20]
    if not files:
        return

    for path in files:
        await session.task_queue.add(
            description=f"[file: {path}] {desc}",
            parent_task_id=task["id"],
            task_type="VERTICAL",
        )
    await session.task_queue.update(task["id"], status="grouped")


# ─── Goal suggestion helper ───────────────────────────────────────────────────


async def _suggest_next_goals(session: "ProjectSession") -> None:
    """After loop converges: use haiku to suggest 3 next goals. Writes to .claude/suggested-goals.md."""
    try:
        context_parts = []
        for fname, max_chars, label in [
            ("PROGRESS.md", 2000, "PROGRESS"),
            ("VISION.md", 1000, "VISION"),
            ("TODO.md", 500, "TODO (open items)"),
        ]:
            fpath = session.project_dir / fname
            if fpath.exists():
                text = fpath.read_text(encoding="utf-8", errors="replace")
                if fname == "TODO.md":
                    lines = [l for l in text.splitlines() if "- [ ]" in l]
                    text = "\n".join(lines)
                context_parts.append(f"=== {label} ===\n{text[-max_chars:]}")

        context = "\n\n".join(context_parts)
        prompt = (
            "Based on this project context, suggest exactly 3 concrete next goals for an autonomous loop. "
            "Format:\n1. [Goal title]: [2-sentence description of what to build/fix and why]\n"
            "2. ...\n3. ...\n\nContext:\n" + context
        )

        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                "claude", "-p", prompt,
                "--model", "claude-haiku-4-5-20251001",
                "--dangerously-skip-permissions",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=str(session.project_dir),
            ),
            timeout=60,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        content = stdout.decode().strip() if stdout else ""
        if not content:
            return

        goals_file = session.claude_dir / "suggested-goals.md"
        goals_file.write_text(content, encoding="utf-8")

        msg = json.dumps({
            "type": "suggested_goals",
            "session_id": session.session_id,
            "content": content,
        })
        dead = []
        for ws in list(session.status_subscribers):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in session.status_subscribers:
                session.status_subscribers.remove(ws)
    except Exception:
        pass  # fail-open


# ─── Status broadcast loop ────────────────────────────────────────────────────


async def status_loop():
    while True:
        await asyncio.sleep(1)
        for session in registry.all():
            try:
                # On first tick, restore persisted schedule
                if not session._schedule_loaded:
                    session._schedule_loaded = True
                    saved = await session.task_queue.get_schedule()
                    if saved and not saved["triggered"]:
                        session._scheduled_start = datetime.fromisoformat(saved["scheduled_at"])
                        session._schedule_triggered = False

                await session.worker_pool.poll_all(session.task_queue, session.project_dir)
                # Poll start.sh processes (Phase 13)
                from process_manager import process_pool as _pp
                await _pp.poll()
                # Auto-patrol scheduling (Phase 13.7)
                _patrol_sched = GLOBAL_SETTINGS.get("patrol_schedule", "")
                if _patrol_sched and not getattr(session, "_patrol_triggered_today", False):
                    try:
                        now = datetime.now()
                        hh, mm = _patrol_sched.split(":")
                        if now.hour == int(hh) and now.minute == int(mm):
                            session._patrol_triggered_today = True
                            _patrol_mode = "--patrol"
                            _existing = _pp.get(str(session.project_dir))
                            if not _existing or _existing.status != "running":
                                await _pp.start(session.project_dir, mode=_patrol_mode)
                                logger.info("Auto-patrol triggered at %s", _patrol_sched)
                    except Exception as e:
                        logger.warning("Patrol schedule parse error: %s", e)
                # Auto-research scheduling (mirrors patrol pattern)
                _research_sched = GLOBAL_SETTINGS.get("research_schedule", "")
                if _research_sched and not getattr(session, "_research_triggered_today", False):
                    try:
                        now = datetime.now()
                        hh, mm = _research_sched.split(":")
                        if now.hour == int(hh) and now.minute == int(mm):
                            session._research_triggered_today = True
                            _existing_r = _pp.get(str(session.project_dir))
                            if not _existing_r or _existing_r.status != "running":
                                await _pp.start(session.project_dir, mode="--research")
                                logger.info("Auto-research triggered at %s", _research_sched)
                    except Exception as e:
                        logger.warning("Research schedule parse error: %s", e)
                # Reset patrol + research triggers at midnight
                if datetime.now().hour == 0:
                    if hasattr(session, "_patrol_triggered_today"):
                        session._patrol_triggered_today = False
                    if hasattr(session, "_research_triggered_today"):
                        session._research_triggered_today = False
                await _check_blockers(session)

                # Auto-start tasks whose dependencies just became satisfied
                # Skip auto_start when swarm owns task dispatch for this session
                _swarm_active = session._swarm and session._swarm.status in ("active", "draining")
                _auto_tasks = await session.task_queue.list()
                _done_ids = {t["id"] for t in _auto_tasks if t["status"] == "done"}
                _newly_ready = [
                    t for t in _auto_tasks
                    if t["status"] == "pending"
                    and _deps_met(t, _done_ids)
                ]

                # Priority ranking: re-rank unranked pending tasks every 5 minutes
                if (GLOBAL_SETTINGS.get("auto_start", True)
                        and time.time() - session._priority_rank_last > 300):
                    _unranked = [t for t in _auto_tasks
                                 if t["status"] == "pending" and not (t.get("priority_score") or 0)]
                    if _unranked:
                        session._priority_rank_last = time.time()
                        asyncio.create_task(
                            _rank_tasks(session.task_queue, session.claude_dir)
                        )

                # Cost budget check — pause auto-start if budget exceeded
                _cost_budget = GLOBAL_SETTINGS.get("cost_budget", 0)
                if _cost_budget > 0:
                    _session_cost = sum(t.get("estimated_cost") or 0 for t in _auto_tasks)
                    session._budget_exceeded = _session_cost >= _cost_budget
                else:
                    session._budget_exceeded = False

                # Worker pool router: enforce max_workers as a global ceiling across all sessions
                _global_max = GLOBAL_SETTINGS.get("max_workers", 0)
                if _global_max > 0:
                    _global_running = sum(
                        sum(1 for w in s.worker_pool.all() if w.status == "running")
                        for s in registry.all()
                    )
                    if _global_running >= _global_max:
                        _newly_ready = []  # global cap hit — skip auto-start this tick

                if _newly_ready and GLOBAL_SETTINGS.get("auto_start", True) and not _swarm_active:
                    _max_w = GLOBAL_SETTINGS.get("max_workers", 0)
                    for _task in _newly_ready:
                        # Budget gate: skip non-loop tasks when budget exceeded
                        _desc = _task.get("description", "")
                        _is_loop_task = _desc.startswith("[Loop-") or _desc.startswith("[Plan-")
                        if session._budget_exceeded and not _is_loop_task:
                            continue
                        # Re-count running workers each iteration to avoid overshoot race
                        if _max_w > 0 and sum(
                            1 for w in session.worker_pool.all() if w.status == "running"
                        ) >= _max_w:
                            break
                        if _task.get("task_type") == "HORIZONTAL":
                            await _decompose_horizontal(_task, session)
                            continue
                        await session.worker_pool.start_worker(
                            _task, session.task_queue,
                            session.project_dir, session.claude_dir,
                        )

                # Auto-scaling: spawn extra workers when queue is backlogged
                if GLOBAL_SETTINGS.get("auto_scale", False) and not _swarm_active:
                    _running_now = sum(1 for w in session.worker_pool.all() if w.status == "running")
                    _pending_now = len([t for t in _auto_tasks if t["status"] == "pending"])
                    _max_w = GLOBAL_SETTINGS.get("max_workers", 8) or 8
                    _spawn_cooldown = getattr(session, '_last_autoscale', 0)
                    if _global_max > 0 and _global_running >= _global_max:
                        pass  # skip auto-scaling, global cap hit
                    elif (_pending_now > _running_now * 2
                            and _running_now < _max_w
                            and time.time() - _spawn_cooldown > 30):
                        _ready = [t for t in _auto_tasks if t["status"] == "pending" and _deps_met(t, _done_ids)]
                        if _ready and not getattr(session, '_budget_exceeded', False):
                            await session.worker_pool.start_worker(
                                _ready[0], session.task_queue,
                                session.project_dir, session.claude_dir,
                            )
                            session._last_autoscale = time.time()

                # ─── Task factory polling ────────────────────────────────────────────────
                _factory_now = time.time()
                if GLOBAL_SETTINGS.get("github_issues_sync", False):
                    if _factory_now - getattr(session, '_ci_watcher_last', 0) > 300:
                        session._ci_watcher_last = _factory_now
                        try:
                            from task_factory.ci_watcher import check_ci_failures
                            asyncio.create_task(check_ci_failures(session.task_queue, str(session.project_dir)))
                        except Exception as e:
                            logger.warning("CI watcher error: %s", e)
                if GLOBAL_SETTINGS.get("coverage_scan", False):
                    if _factory_now - getattr(session, '_coverage_scan_last', 0) > 1800:
                        session._coverage_scan_last = _factory_now
                        try:
                            from task_factory.coverage_scan import check_coverage_gaps
                            asyncio.create_task(check_coverage_gaps(session.task_queue, str(session.project_dir)))
                        except Exception as e:
                            logger.warning("Coverage scan error: %s", e)
                if GLOBAL_SETTINGS.get("dep_update_scan", False):
                    if _factory_now - getattr(session, '_dep_update_last', 0) > 3600:
                        session._dep_update_last = _factory_now
                        try:
                            from task_factory.dep_update import check_outdated_deps
                            asyncio.create_task(check_outdated_deps(session.task_queue, str(session.project_dir)))
                        except Exception as e:
                            logger.warning("Dep update error: %s", e)

                # Complete grouped parents when all children are done
                _grouped = [t for t in _auto_tasks if t["status"] == "grouped"]
                for _gp in _grouped:
                    _children = [t for t in _auto_tasks if t.get("parent_task_id") == _gp["id"]]
                    if _children and all(c["status"] in ("done", "failed") for c in _children):
                        await session.task_queue.update(_gp["id"], status="done")

                # Scheduler: auto-start pending tasks at scheduled time
                if session._scheduled_start and not session._schedule_triggered:
                    if datetime.now() >= session._scheduled_start:
                        session._schedule_triggered = True
                        await session.task_queue.save_schedule(
                            session._scheduled_start.isoformat(), triggered=True
                        )
                        tasks = await session.task_queue.list()
                        done_ids = {t["id"] for t in tasks if t["status"] == "done"}
                        pending = [t for t in tasks if t["status"] in ("pending", "queued")]
                        for task in pending:
                            if _deps_met(task, done_ids):
                                await session.worker_pool.start_worker(
                                    task, session.task_queue,
                                    session.project_dir, session.claude_dir,
                                )

                tasks = await session.task_queue.list()
                workers = [w.to_dict() for w in session.worker_pool.all()]
                loop_state = await session.task_queue.get_loop()

                # Detect run-complete (all workers idle, no pending tasks, but some done)
                # Suppress during active loop — loop has its own loop_converged notification
                running_workers = [w for w in session.worker_pool.all() if w.status == "running"]
                pending_tasks = [t for t in tasks if t["status"] in ("pending", "queued")]
                done_tasks = [t for t in tasks if t["status"] in ("done", "failed")]
                _loop_running = loop_state and loop_state.get("status") == "running"
                if not running_workers and not pending_tasks and done_tasks and not session._run_complete and not _loop_running:
                    session._run_complete = True
                    asyncio.create_task(_fire_notification("run_complete", session))
                    # High failure rate notification (one-shot)
                    _fail_count = sum(1 for t in done_tasks if t["status"] == "failed")
                    if len(done_tasks) >= 2 and _fail_count / len(done_tasks) > 0.5 and not session._failure_notified:
                        session._failure_notified = True
                        asyncio.create_task(_fire_notification("high_failure_rate", session))
                elif pending_tasks or running_workers:
                    session._run_complete = False
                    session._failure_notified = False

                total = len(tasks)
                done_count = sum(1 for t in tasks if t["status"] in ("done", "failed"))
                success_count = sum(1 for t in tasks if t["status"] == "done")
                progress_pct = int(done_count / total * 100) if total > 0 else 0
                success_rate = int(success_count / done_count * 100) if done_count > 0 else 0

                done_workers = [w for w in session.worker_pool.all() if w.status in ("done", "failed")]
                avg_s = (
                    sum(w.elapsed_s for w in done_workers) / len(done_workers)
                    if done_workers else 300
                )
                remaining = total - done_count
                eta_seconds = int(avg_s * remaining) if remaining > 0 else 0

                swarm_state = session._swarm.to_dict() if session._swarm else None
                from process_manager import process_pool as _pp2
                msg = json.dumps({
                    "type": "status",
                    "session_id": session.session_id,
                    "workers": workers,
                    "queue": tasks,
                    "progress_pct": progress_pct,
                    "eta_seconds": eta_seconds,
                    "success_rate": success_rate,
                    "schedule": session._schedule_dict(),
                    "run_complete": session._run_complete,
                    "budget_exceeded": session._budget_exceeded,
                    "budget_limit": GLOBAL_SETTINGS.get("cost_budget", 0),
                    "loop_state": loop_state,
                    "swarm_state": swarm_state,
                    "processes": _pp2.to_list(),
                })
                dead = []
                for ws in list(session.status_subscribers):
                    try:
                        await ws.send_text(msg)
                    except Exception:
                        dead.append(ws)
                for ws in dead:
                    if ws in session.status_subscribers:
                        session.status_subscribers.remove(ws)
            except Exception as exc:
                logger.exception("status_loop error for session %s: %s", getattr(session, 'session_id', '?'), exc)
