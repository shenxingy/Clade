"""
Orchestrator config — constants, settings, utilities.
Leaf module: no internal dependencies.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

_ALLOWED_TASK_COLS = {"status", "description", "model", "depends_on", "score",
                      "worker_id", "started_at", "elapsed_s", "last_commit", "log_file",
                      "failed_reason", "score_note", "own_files", "forbidden_files",
                      "gh_issue_number", "is_critical_path",
                      "input_tokens", "output_tokens", "estimated_cost",
                      "task_type", "source_ref", "parent_task_id", "priority_score"}

_ALLOWED_LOOP_COLS = {
    "name", "artifact_path", "context_dir", "status", "iteration",
    "changes_history", "deferred_items", "convergence_k", "convergence_n",
    "max_iterations", "supervisor_model", "mode", "plan_phase", "updated_at",
}

_MODEL_ALIASES = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
}

# ─── Paths ────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
WEB_DIR = BASE_DIR / "web"

# Kept for backward compat / default session init; not used in new code paths
PROJECT_DIR = Path(os.environ.get("ORCHESTRATOR_PROJECT_DIR", str(Path.cwd())))

# ─── Global Settings ──────────────────────────────────────────────────────────

_settings_file = Path.home() / ".claude" / "orchestrator-settings.json"


_SETTINGS_DEFAULTS = {
    "max_workers": 0,
    "auto_start": True,
    "auto_push": True,
    "auto_merge": True,
    "auto_review": True,
    "default_model": "sonnet",
    "loop_supervisor_model": "sonnet",
    "loop_convergence_k": 2,
    "loop_convergence_n": 3,
    "loop_max_iterations": 20,
    "auto_oracle": False,
    "auto_model_routing": False,
    "context_budget_warning": True,
    "github_issues_sync": False,
    "github_issues_label": "orchestrator",
    "agent_teams": False,
    "stuck_timeout_minutes": 15,
    "cost_budget": 0,
    "notification_webhook": "",
    "auto_scale": False,
    "min_workers": 1,
    "webhook_secret": "",
    "coverage_scan": False,
    "dep_update_scan": False,
}


def _load_settings() -> dict:
    defaults = dict(_SETTINGS_DEFAULTS)
    if _settings_file.exists():
        try:
            defaults.update(json.loads(_settings_file.read_text()))
        except Exception:
            pass
    return defaults


def _save_settings(s: dict) -> None:
    _settings_file.parent.mkdir(parents=True, exist_ok=True)
    _settings_file.write_text(json.dumps(s, indent=2))


GLOBAL_SETTINGS: dict = _load_settings()

# ─── Project Scanner ──────────────────────────────────────────────────────────


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

# ─── Dependency Check ─────────────────────────────────────────────────────────


def _deps_met(task: dict, done_ids: set) -> bool:
    """Return True if all depends_on task IDs are done."""
    deps = task.get("depends_on") or []
    if isinstance(deps, str):
        try:
            deps = json.loads(deps)
        except Exception:
            deps = []
    return all(dep_id in done_ids for dep_id in deps)

# ─── Token/Cost Tracking ─────────────────────────────────────────────────────

_TOKEN_PATTERNS = [
    # Claude CLI: "Total tokens: input=1234, output=5678"
    re.compile(r"[Tt]otal\s+tokens?.*?input\s*=\s*(\d+).*?output\s*=\s*(\d+)"),
    # "Input tokens: 1234" / "Output tokens: 5678" on separate lines
    re.compile(r"[Ii]nput\s+tokens?\s*[:=]\s*(\d+)"),
    re.compile(r"[Oo]utput\s+tokens?\s*[:=]\s*(\d+)"),
    # Compact: "tokens: 1234/5678" or "1234 in / 5678 out"
    re.compile(r"(\d+)\s*(?:in|input)\s*/\s*(\d+)\s*(?:out|output)"),
]


def _parse_token_usage(log_path: Path) -> tuple[int, int]:
    """Scan log file bottom-up for token usage. Returns (input_tokens, output_tokens)."""
    try:
        text = log_path.read_text(errors="replace")
    except Exception:
        return 0, 0
    lines = text.splitlines()
    input_t, output_t = 0, 0
    # Scan from bottom (most likely near end)
    for line in reversed(lines[-200:]):
        m = _TOKEN_PATTERNS[0].search(line)
        if m:
            return int(m.group(1)), int(m.group(2))
        m3 = _TOKEN_PATTERNS[3].search(line)
        if m3:
            return int(m3.group(1)), int(m3.group(2))
    # Fallback: separate input/output lines
    for line in reversed(lines[-200:]):
        if not input_t:
            m1 = _TOKEN_PATTERNS[1].search(line)
            if m1:
                input_t = int(m1.group(1))
        if not output_t:
            m2 = _TOKEN_PATTERNS[2].search(line)
            if m2:
                output_t = int(m2.group(1))
        if input_t and output_t:
            break
    return input_t, output_t


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost using Sonnet pricing ($3/MTok input, $15/MTok output)."""
    return round(input_tokens * 3.0 / 1_000_000 + output_tokens * 15.0 / 1_000_000, 4)

# ─── Session Recovery ─────────────────────────────────────────────────────────


async def _recover_orphaned_tasks(task_queue: Any) -> int:
    """Mark running/starting tasks as interrupted after server restart. Fail-open."""
    try:
        await task_queue._ensure_db()
        async with aiosqlite.connect(str(task_queue._db_path)) as db:
            cursor = await db.execute(
                "UPDATE tasks SET status = 'interrupted' WHERE status IN ('running', 'starting')"
            )
            count = cursor.rowcount
            await db.commit()
            return count
    except Exception as e:
        logger.warning("_recover_orphaned_tasks failed (fail-open): %s", e)
        return 0

# ─── Notifications ────────────────────────────────────────────────────────────


async def _fire_notification(event: str, session: Any, extra: dict | None = None) -> None:
    """Fire webhook notification. Fail-open (no deps, follows _gh_update_issue_status pattern)."""
    webhook = GLOBAL_SETTINGS.get("notification_webhook", "")
    if not webhook:
        return
    try:
        tasks = await session.task_queue.list()
        done = sum(1 for t in tasks if t["status"] == "done")
        failed = sum(1 for t in tasks if t["status"] == "failed")
        failed_list = [t["description"][:120] for t in tasks if t["status"] == "failed"]
        payload = json.dumps({
            "event": event,
            "session_id": session.session_id,
            "project_name": session.name,
            "project_path": str(session.project_dir),
            "total": len(tasks), "done": done, "failed": failed,
            "failed_tasks": failed_list[:10],
            **(extra or {}),
        })
        proc = await asyncio.create_subprocess_exec(
            "curl", "-s", "-X", "POST", "--max-time", "10",
            "-H", "Content-Type: application/json",
            "-d", payload, webhook,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=15)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
    except Exception:
        pass  # fail-open
