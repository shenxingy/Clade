"""
Claude Code Orchestrator — FastAPI server
Manages multiple project sessions, each with an interactive orchestrator (PTY) + N workers.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import ptyprocess
from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from watchfiles import awatch

# ─── Paths ────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
WEB_DIR = BASE_DIR / "web"

# Kept for backward compat / default session init; not used in new code paths
PROJECT_DIR = Path(os.environ.get("ORCHESTRATOR_PROJECT_DIR", str(Path.cwd())))


def scan_projects(base: Path | None = None, max_depth: int = 3) -> list[dict]:
    """Find git repos under base dir (default: home)."""
    if base is None:
        base = Path.home()
    results = []

    def _scan(p: Path, depth: int) -> None:
        if depth > max_depth or not p.is_dir():
            return
        try:
            if (p / ".git").exists():
                results.append({"name": p.name, "path": str(p)})
                return  # don't recurse into git repos
            for child in sorted(p.iterdir()):
                if child.is_dir() and not child.name.startswith("."):
                    _scan(child, depth + 1)
        except PermissionError:
            pass

    _scan(base, 0)
    return results[:50]  # cap at 50


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="Claude Code Orchestrator")

# Serve static files (web UI)
app.mount("/web", StaticFiles(directory=str(WEB_DIR)), name="web")


# ─── Task Queue ───────────────────────────────────────────────────────────────

class TaskQueue:
    def __init__(self, claude_dir: Path):
        self._claude_dir = claude_dir
        self._lock = asyncio.Lock()

    def _task_queue_file(self) -> Path:
        return self._claude_dir / "task-queue.json"

    def _proposed_tasks_file(self) -> Path:
        return self._claude_dir / "proposed-tasks.md"

    def _load(self) -> list[dict]:
        f = self._task_queue_file()
        if f.exists():
            try:
                return json.loads(f.read_text())
            except Exception:
                return []
        return []

    def _save(self, tasks: list[dict]) -> None:
        f = self._task_queue_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(tasks, indent=2))

    async def list(self) -> list[dict]:
        async with self._lock:
            return self._load()

    async def add(self, description: str, model: str = "sonnet") -> dict:
        async with self._lock:
            tasks = self._load()
            task = {
                "id": str(uuid.uuid4())[:8],
                "description": description,
                "model": model,
                "status": "pending",
                "worker_id": None,
                "started_at": None,
                "elapsed_s": 0,
                "last_commit": None,
                "log_file": None,
            }
            tasks.append(task)
            self._save(tasks)
            return task

    async def update(self, task_id: str, **kwargs) -> dict | None:
        async with self._lock:
            tasks = self._load()
            for t in tasks:
                if t["id"] == task_id:
                    t.update(kwargs)
                    self._save(tasks)
                    return t
            return None

    async def delete(self, task_id: str) -> bool:
        async with self._lock:
            tasks = self._load()
            before = len(tasks)
            tasks = [t for t in tasks if t["id"] != task_id]
            self._save(tasks)
            return len(tasks) < before

    async def get(self, task_id: str) -> dict | None:
        async with self._lock:
            for t in self._load():
                if t["id"] == task_id:
                    return t
            return None

    async def import_from_proposed(self) -> list[dict]:
        """Parse .claude/proposed-tasks.md and add tasks to queue."""
        f = self._proposed_tasks_file()
        if not f.exists():
            return []
        content = f.read_text()
        blocks = content.split("===TASK===")
        added = []
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            lines = block.splitlines()
            model = "sonnet"
            desc_lines = []
            in_header = True
            for line in lines:
                if in_header and line.startswith("model:"):
                    model = line.split(":", 1)[1].strip()
                elif in_header and line.strip() == "---":
                    in_header = False
                elif not in_header:
                    desc_lines.append(line)
            description = "\n".join(desc_lines).strip()
            if description:
                task = await self.add(description, model)
                added.append(task)
        return added


# ─── Worker Pool ──────────────────────────────────────────────────────────────

class Worker:
    def __init__(
        self,
        task_id: str,
        description: str,
        model: str,
        project_dir: Path,
        claude_dir: Path,
    ):
        self.id = str(uuid.uuid4())[:8]
        self.task_id = task_id
        self.description = description
        self.model = model
        self._project_dir = project_dir
        self._claude_dir = claude_dir
        self.proc: asyncio.subprocess.Process | None = None
        self.pgid: int | None = None
        self.pid: int | None = None
        self.started_at = time.time()
        self._finished_at: float | None = None
        self.status = "starting"  # starting/running/paused/blocked/done/failed
        self.last_commit: str | None = None
        self.log_file: str | None = None
        self._log_path: Path | None = None
        self.verified: bool = False
        self.auto_committed: bool = False
        self._verify_triggered: bool = False

    @property
    def elapsed_s(self) -> int:
        return int((self._finished_at or time.time()) - self.started_at)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "description": self.description[:80],
            "model": self.model,
            "status": self.status,
            "pid": self.pid,
            "elapsed_s": self.elapsed_s,
            "last_commit": self.last_commit,
            "log_file": self.log_file,
            "verified": self.verified,
            "auto_committed": self.auto_committed,
        }

    async def start(self) -> None:
        logs = self._claude_dir / "orchestrator-logs"
        logs.mkdir(parents=True, exist_ok=True)
        self._log_path = logs / f"worker-{self.id}.log"
        self.log_file = str(self._log_path)

        task_file = self._claude_dir / f"task-{self.id}.md"
        task_file.parent.mkdir(parents=True, exist_ok=True)
        task_file.write_text(self.description)

        shell_cmd = (
            f'claude -p "$(cat {task_file})" --dangerously-skip-permissions'
        )

        log_fd = open(self._log_path, "w")
        self.proc = await asyncio.create_subprocess_shell(
            shell_cmd,
            stdout=log_fd,
            stderr=log_fd,
            preexec_fn=os.setsid,
            env={**os.environ},
            cwd=str(self._project_dir),
        )
        self.pid = self.proc.pid
        try:
            self.pgid = os.getpgid(self.proc.pid)
        except ProcessLookupError:
            self.pgid = self.proc.pid
        self.status = "running"

    def is_alive(self) -> bool:
        if self.proc is None:
            return False
        return self.proc.returncode is None

    def pause(self) -> None:
        if self.pgid and self.is_alive():
            try:
                os.killpg(self.pgid, signal.SIGSTOP)
                self.status = "paused"
            except ProcessLookupError:
                pass

    def resume(self) -> None:
        if self.pgid and self.status == "paused":
            try:
                os.killpg(self.pgid, signal.SIGCONT)
                self.status = "running"
            except ProcessLookupError:
                pass

    async def stop(self) -> None:
        if self.pgid and self.is_alive():
            try:
                os.killpg(self.pgid, signal.SIGTERM)
                await asyncio.sleep(0.5)
                if self.is_alive():
                    os.killpg(self.pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if self._finished_at is None:
            self._finished_at = time.time()
        self.status = "done"

    async def poll(self) -> None:
        """Update last_commit and check if process finished."""
        if not self.is_alive():
            if self._finished_at is None:
                self._finished_at = time.time()
            rc = self.proc.returncode if self.proc else -1
            self.status = "done" if rc == 0 else "failed"
            return

        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "log", "-1", "--oneline",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=str(self._project_dir),
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3)
            self.last_commit = stdout.decode().strip() or None
        except Exception:
            pass

    async def verify_and_commit(self) -> bool:
        """Run AI verification, auto-commit if OK. Returns True if committed."""
        # Check for uncommitted changes
        diff_proc = await asyncio.create_subprocess_exec(
            "git", "diff", "--name-only", "HEAD",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            cwd=str(self._project_dir),
        )
        stdout, _ = await asyncio.wait_for(diff_proc.communicate(), timeout=10)
        untracked_proc = await asyncio.create_subprocess_exec(
            "git", "ls-files", "--others", "--exclude-standard",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            cwd=str(self._project_dir),
        )
        ut_out, _ = await asyncio.wait_for(untracked_proc.communicate(), timeout=10)
        changed_files = [
            f for f in (stdout.decode().strip() + "\n" + ut_out.decode().strip()).splitlines()
            if f.strip()
        ]
        if not changed_files:
            return False  # nothing to commit

        # Build verification prompt
        diff_summary_proc = await asyncio.create_subprocess_exec(
            "git", "diff", "HEAD", "--stat",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            cwd=str(self._project_dir),
        )
        diff_out, _ = await asyncio.wait_for(diff_summary_proc.communicate(), timeout=10)

        task_first_line = self.description.splitlines()[0][:80]
        verify_prompt = (
            f"Task was: {task_first_line}\n\n"
            f"Git diff stat:\n{diff_out.decode()}\n\n"
            "If the changes look complete and correct for the task, output exactly: VERIFIED_OK\n"
            "If there are obvious issues or nothing was changed, output: VERIFIED_FAIL: <reason>\n"
            "Output ONLY one of those two responses, nothing else."
        )

        # Run claude verification
        verify_proc = await asyncio.create_subprocess_shell(
            f'claude -p "{verify_prompt.replace(chr(34), chr(39))}" --dangerously-skip-permissions',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            cwd=str(self._project_dir),
        )
        try:
            v_out, _ = await asyncio.wait_for(verify_proc.communicate(), timeout=120)
            result = v_out.decode().strip()
        except asyncio.TimeoutError:
            return False

        if "VERIFIED_OK" not in result:
            return False

        self.verified = True

        # Commit using committer script
        commit_msg = f"feat: {task_first_line.lower()}"
        files_arg = " ".join(f'"{f}"' for f in changed_files[:20])
        committer_path = Path.home() / ".claude/scripts/committer.sh"
        commit_proc = await asyncio.create_subprocess_shell(
            f'bash {committer_path} "{commit_msg}" {files_arg}',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(self._project_dir),
        )
        try:
            c_out, c_err = await asyncio.wait_for(commit_proc.communicate(), timeout=30)
            if commit_proc.returncode == 0:
                self.auto_committed = True
                # Update last_commit
                log_proc = await asyncio.create_subprocess_exec(
                    "git", "log", "-1", "--oneline",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    cwd=str(self._project_dir),
                )
                log_out, _ = await asyncio.wait_for(log_proc.communicate(), timeout=5)
                self.last_commit = log_out.decode().strip() or self.last_commit
        except asyncio.TimeoutError:
            pass
        return self.auto_committed


class WorkerPool:
    def __init__(self):
        self.workers: dict[str, Worker] = {}

    async def start_worker(
        self,
        task: dict,
        task_queue: TaskQueue,
        project_dir: Path,
        claude_dir: Path,
    ) -> Worker:
        worker = Worker(
            task["id"],
            task["description"],
            task.get("model", "sonnet"),
            project_dir,
            claude_dir,
        )
        self.workers[worker.id] = worker
        await task_queue.update(task["id"], status="running", worker_id=worker.id)
        await worker.start()
        return worker

    def get(self, worker_id: str) -> Worker | None:
        return self.workers.get(worker_id)

    def all(self) -> list[Worker]:
        return list(self.workers.values())

    async def poll_all(self, task_queue: TaskQueue) -> None:
        for w in list(self.workers.values()):
            await w.poll()
            if w.status in ("done", "failed"):
                await task_queue.update(
                    w.task_id,
                    status=w.status,
                    elapsed_s=w.elapsed_s,
                    last_commit=w.last_commit,
                )
            else:
                await task_queue.update(
                    w.task_id,
                    elapsed_s=w.elapsed_s,
                    last_commit=w.last_commit,
                )
            if w.status == "done" and not w._verify_triggered:
                w._verify_triggered = True
                asyncio.ensure_future(w.verify_and_commit())


# ─── Orchestrator Session (PTY) ───────────────────────────────────────────────

class OrchestratorSession:
    def __init__(self):
        self.pty: ptyprocess.PtyProcess | None = None
        self.clients: list[WebSocket] = []
        self._running = False
        self._read_task: asyncio.Task | None = None

    def start(self, project_dir: Path) -> None:
        if self.pty and self.pty.isalive():
            return
        env = {**os.environ, "TERM": "xterm-256color"}
        self.pty = ptyprocess.PtyProcess.spawn(
            ["claude", "--dangerously-skip-permissions"],
            env=env,
            dimensions=(40, 120),
            cwd=str(project_dir),
        )
        self._running = True
        self._read_task = asyncio.ensure_future(self._read_loop())

    async def _read_loop(self) -> None:
        loop = asyncio.get_event_loop()
        while self._running and self.pty and self.pty.isalive():
            try:
                data = await loop.run_in_executor(None, self._read_chunk)
                if data:
                    msg = json.dumps({"type": "output", "data": data})
                    dead = []
                    for ws in self.clients:
                        try:
                            await ws.send_text(msg)
                        except Exception:
                            dead.append(ws)
                    for ws in dead:
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
        self.status_subscribers: list[WebSocket] = []
        self.proposed_tasks_subscribers: list[WebSocket] = []
        self._blockers_mtime: float = 0.0
        self._watch_task: asyncio.Task | None = None

    @property
    def name(self) -> str:
        return self.project_dir.name

    @property
    def claude_dir(self) -> Path:
        return self.project_dir / ".claude"

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
        }

    def start_watch(self) -> None:
        """Start watching proposed-tasks.md for this session."""
        if self._watch_task is None or self._watch_task.done():
            self._watch_task = asyncio.ensure_future(
                _watch_session_proposed_tasks(self)
            )


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
    """Watch a session's proposed-tasks.md and notify its subscribers."""
    target = session.claude_dir / "proposed-tasks.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch(exist_ok=True)
    try:
        async for _changes in awatch(str(target)):
            content = target.read_text() if target.exists() else ""
            msg = json.dumps({
                "type": "proposed_tasks",
                "session_id": session.session_id,
                "content": content,
            })
            dead = []
            for ws in session.proposed_tasks_subscribers:
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
    if not f.exists():
        return
    mtime = f.stat().st_mtime
    if mtime <= session._blockers_mtime:
        return
    session._blockers_mtime = mtime
    running = [w for w in session.worker_pool.all() if w.status == "running"]
    if running:
        newest = max(running, key=lambda w: w.started_at)
        newest.status = "blocked"


# ─── Status broadcast loop ────────────────────────────────────────────────────

async def status_loop():
    while True:
        await asyncio.sleep(1)
        for session in registry.all():
            try:
                await session.worker_pool.poll_all(session.task_queue)
                await _check_blockers(session)

                tasks = await session.task_queue.list()
                workers = [w.to_dict() for w in session.worker_pool.all()]

                total = len(tasks)
                done = sum(1 for t in tasks if t["status"] in ("done", "failed"))
                progress_pct = int(done / total * 100) if total > 0 else 0

                done_workers = [
                    w for w in session.worker_pool.all()
                    if w.status in ("done", "failed")
                ]
                avg_s = (
                    sum(w.elapsed_s for w in done_workers) / len(done_workers)
                    if done_workers
                    else 300
                )
                remaining = total - done
                eta_seconds = int(avg_s * remaining) if remaining > 0 else 0

                msg = json.dumps({
                    "type": "status",
                    "session_id": session.session_id,
                    "workers": workers,
                    "queue": tasks,
                    "progress_pct": progress_pct,
                    "eta_seconds": eta_seconds,
                })
                dead = []
                for ws in session.status_subscribers:
                    try:
                        await ws.send_text(msg)
                    except Exception:
                        dead.append(ws)
                for ws in dead:
                    session.status_subscribers.remove(ws)
            except Exception:
                pass  # Don't crash the loop


@app.on_event("startup")
async def startup():
    # Create default session from PROJECT_DIR; orchestrator lazy-started on first WS connect
    default_session = registry.create(str(PROJECT_DIR))
    default_session.start_watch()
    asyncio.ensure_future(status_loop())


# ─── REST: Sessions ───────────────────────────────────────────────────────────

@app.get("/api/sessions")
async def list_sessions():
    return [s.to_dict() for s in registry.all()]


@app.post("/api/sessions")
async def create_session(body: dict):
    path = Path(body["path"]).expanduser().resolve()
    if not path.is_dir():
        return {"error": f"Directory not found: {path}"}
    session = registry.create(str(path))
    session.orchestrator.start(session.project_dir)
    session.start_watch()
    return session.to_dict()


@app.get("/api/sessions/{session_id}")
async def get_session_detail(session_id: str):
    s = registry.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return s.to_dict()


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    s = registry.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    registry.remove(session_id)
    return {"ok": True}


# ─── REST: Project (backward compat, targets default session) ─────────────────

@app.get("/api/project")
async def get_project():
    s = registry.default()
    if not s:
        return {"path": str(PROJECT_DIR), "name": PROJECT_DIR.name}
    return {"path": str(s.project_dir), "name": s.name}


@app.post("/api/project")
async def switch_project(body: dict):
    new_path = Path(body["path"]).expanduser().resolve()
    if not new_path.is_dir():
        return {"error": f"Directory not found: {new_path}"}
    # Remove old default session and replace with new one
    old = registry.default()
    if old:
        registry.remove(old.session_id)
    new_session = registry.create(str(new_path))
    await asyncio.sleep(0.3)
    new_session.start_watch()
    return {"path": str(new_session.project_dir), "name": new_session.name}


@app.get("/api/projects")
async def list_projects(base: str | None = None):
    base_path = Path(base).expanduser() if base else None
    return scan_projects(base_path)


@app.get("/")
async def root():
    return FileResponse(str(WEB_DIR / "index.html"))


# ─── WebSocket: /ws/chat ──────────────────────────────────────────────────────

@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket, session: str | None = Query(default=None)):
    await websocket.accept()
    s = registry.get(session) if session else registry.default()
    if s is None:
        await websocket.close(code=4004)
        return

    s.orchestrator.clients.append(websocket)

    # Lazy-start orchestrator on first connection
    if not s.orchestrator.is_alive():
        s.orchestrator.start(s.project_dir)
        await asyncio.sleep(0.5)

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "input":
                s.orchestrator.send_input(msg["data"])
            elif msg.get("type") == "resize":
                s.orchestrator.resize(msg.get("rows", 24), msg.get("cols", 80))
    except WebSocketDisconnect:
        if websocket in s.orchestrator.clients:
            s.orchestrator.clients.remove(websocket)


# ─── WebSocket: /ws/status ────────────────────────────────────────────────────

@app.websocket("/ws/status")
async def ws_status(websocket: WebSocket, session: str | None = Query(default=None)):
    await websocket.accept()
    s = registry.get(session) if session else registry.default()
    if s is None:
        await websocket.close(code=4004)
        return

    s.status_subscribers.append(websocket)
    s.proposed_tasks_subscribers.append(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep alive
    except WebSocketDisconnect:
        if websocket in s.status_subscribers:
            s.status_subscribers.remove(websocket)
        if websocket in s.proposed_tasks_subscribers:
            s.proposed_tasks_subscribers.remove(websocket)


# ─── REST: Tasks ──────────────────────────────────────────────────────────────

@app.get("/api/tasks")
async def list_tasks(s: ProjectSession = Depends(_resolve_session)):
    return await s.task_queue.list()


@app.post("/api/tasks")
async def create_task(body: dict, s: ProjectSession = Depends(_resolve_session)):
    return await s.task_queue.add(
        description=body["description"],
        model=body.get("model", "sonnet"),
    )


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str, s: ProjectSession = Depends(_resolve_session)):
    ok = await s.task_queue.delete(task_id)
    return {"ok": ok}


@app.post("/api/tasks/import-proposed")
async def import_proposed(s: ProjectSession = Depends(_resolve_session)):
    tasks = await s.task_queue.import_from_proposed()
    return {"imported": len(tasks), "tasks": tasks}


@app.post("/api/tasks/start-all")
async def start_all(s: ProjectSession = Depends(_resolve_session)):
    tasks = await s.task_queue.list()
    pending = [t for t in tasks if t["status"] in ("pending", "queued")]
    started = []
    for task in pending:
        worker = await s.worker_pool.start_worker(
            task, s.task_queue, s.project_dir, s.claude_dir
        )
        started.append({"task_id": task["id"], "worker_id": worker.id})
    return {"started": len(started), "workers": started}


@app.post("/api/tasks/{task_id}/run")
async def run_task(task_id: str, s: ProjectSession = Depends(_resolve_session)):
    task = await s.task_queue.get(task_id)
    if not task:
        return {"error": "Task not found"}
    if task["status"] not in ("pending", "queued"):
        return {"error": f"Task status is '{task['status']}', cannot run"}
    worker = await s.worker_pool.start_worker(
        task, s.task_queue, s.project_dir, s.claude_dir
    )
    return {"worker_id": worker.id}


# ─── REST: Workers ────────────────────────────────────────────────────────────

@app.get("/api/workers")
async def list_workers(s: ProjectSession = Depends(_resolve_session)):
    return [w.to_dict() for w in s.worker_pool.all()]


@app.post("/api/workers/{worker_id}/pause")
async def pause_worker(worker_id: str, s: ProjectSession = Depends(_resolve_session)):
    w = s.worker_pool.get(worker_id)
    if not w:
        return {"error": "Worker not found"}
    w.pause()
    await s.task_queue.update(w.task_id, status="paused")
    return {"status": w.status}


@app.post("/api/workers/{worker_id}/resume")
async def resume_worker(worker_id: str, s: ProjectSession = Depends(_resolve_session)):
    w = s.worker_pool.get(worker_id)
    if not w:
        return {"error": "Worker not found"}
    w.resume()
    await s.task_queue.update(w.task_id, status="running")
    return {"status": w.status}


@app.post("/api/workers/{worker_id}/message")
async def message_worker(
    worker_id: str, body: dict, s: ProjectSession = Depends(_resolve_session)
):
    """Stop worker, inject a message, and restart with injected context."""
    w = s.worker_pool.get(worker_id)
    if not w:
        return {"error": "Worker not found"}

    user_message = body.get("message", "")
    original_desc = w.description

    await w.stop()

    new_desc = f"{original_desc}\n\n---\n**Additional context from user:**\n{user_message}"
    new_task = await s.task_queue.add(new_desc, w.model)
    new_worker = await s.worker_pool.start_worker(
        new_task, s.task_queue, s.project_dir, s.claude_dir
    )
    return {"new_worker_id": new_worker.id, "new_task_id": new_task["id"]}


@app.get("/api/workers/{worker_id}/log")
async def get_worker_log(
    worker_id: str, lines: int = 100, s: ProjectSession = Depends(_resolve_session)
):
    w = s.worker_pool.get(worker_id)
    if not w:
        return {"error": "Worker not found"}
    if not w._log_path or not w._log_path.exists():
        return {"log": ""}
    try:
        text = w._log_path.read_text(errors="replace")
        tail = "\n".join(text.splitlines()[-lines:])
        return {"log": tail, "path": str(w._log_path)}
    except Exception as e:
        return {"log": f"Error reading log: {e}"}


# ─── REST: Usage ──────────────────────────────────────────────────────────────

def _get_usage() -> dict:
    stats_file = Path.home() / ".claude" / "stats-cache.json"
    today_str = date.today().isoformat()
    cutoff = datetime.now() - timedelta(hours=24)

    # Defaults
    daily: list[dict] = []
    last_updated = "?"
    total_sessions = 0

    if stats_file.exists():
        try:
            stats = json.loads(stats_file.read_text())
            last_updated = stats.get("lastComputedDate", "?")
            total_sessions = stats.get("totalSessions", 0)
            cutoff_date = (date.today() - timedelta(days=6)).isoformat()
            daily = [
                {
                    "date": e["date"],
                    "messages": e.get("messageCount", 0),
                    "sessions": e.get("sessionCount", 0),
                }
                for e in stats.get("dailyActivity", [])
                if e.get("date", "") >= cutoff_date
            ]
        except Exception:
            pass

    # Supplement today's data from JSONL files (for dates after lastComputedDate)
    today_messages = 0
    today_sessions: set[str] = set()
    today_tool_calls = 0
    projects_dir = Path.home() / ".claude" / "projects"
    if projects_dir.exists():
        for jsonl_file in projects_dir.rglob("*.jsonl"):
            try:
                mtime = datetime.fromtimestamp(jsonl_file.stat().st_mtime)
                if mtime < cutoff:
                    continue
                for line in jsonl_file.read_text(errors="replace").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except Exception:
                        continue
                    ts = entry.get("timestamp", "")
                    if isinstance(ts, str) and ts[:10] != today_str:
                        continue
                    if entry.get("type") == "user":
                        today_messages += 1
                        sid = entry.get("sessionId")
                        if sid:
                            today_sessions.add(sid)
            except Exception:
                pass

    # Build today entry: prefer JSONL live data if stats are stale
    cached_today = next((e for e in daily if e["date"] == today_str), None)
    if today_messages > 0 or cached_today is None:
        today_entry = {
            "messages": today_messages,
            "sessions": len(today_sessions),
            "tool_calls": today_tool_calls,
        }
        if cached_today is None:
            daily.append({"date": today_str, "messages": today_messages, "sessions": len(today_sessions)})
    else:
        today_entry = {
            "messages": cached_today["messages"],
            "sessions": cached_today["sessions"],
            "tool_calls": 0,
        }

    week_messages = sum(e["messages"] for e in daily)
    week_sessions = sum(e["sessions"] for e in daily)

    return {
        "today": today_entry,
        "this_week": {"messages": week_messages, "sessions": week_sessions},
        "daily": sorted(daily, key=lambda e: e["date"]),
        "last_updated": last_updated,
        "total_sessions": total_sessions,
    }


@app.get("/api/usage")
async def get_usage():
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _get_usage)


# ─── REST: Status ─────────────────────────────────────────────────────────────

@app.get("/api/status")
async def get_status(s: ProjectSession = Depends(_resolve_session)):
    tasks = await s.task_queue.list()
    workers = [w.to_dict() for w in s.worker_pool.all()]
    total = len(tasks)
    done = sum(1 for t in tasks if t["status"] in ("done", "failed"))
    return {
        "workers": workers,
        "queue": tasks,
        "progress_pct": int(done / total * 100) if total > 0 else 0,
        "orchestrator_alive": s.orchestrator.is_alive(),
        "session_id": s.session_id,
    }
