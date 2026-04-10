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
                      "task_type", "source_ref", "parent_task_id", "priority_score",
                      "handoff_type", "handoff_payload", "completion_summary",
                      "token_budget", "context_version", "attempt_count",
                      "phase", "oracle_result", "oracle_reason"}

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
    "worker_token_budget": 0,  # max tokens per worker (0 = unlimited)
    "notification_webhook": "",
    "auto_scale": False,
    "min_workers": 1,
    "webhook_secret": "",
    "coverage_scan": False,
    "dep_update_scan": False,
    "patrol_schedule": "",
    "patrol_auto_ideas": False,
    "research_schedule": "",
    "usage_provider": "claude",
    "minimax_api_key": "",
    "minimax_group_id": "",
    "parallel_fix_samples": 1,  # Agentless §6C: N parallel workers for critical-path oracle rejections (1=sequential)
    "context_span_budget": 6000,  # Moatless §Gap3: max chars for TLDR span block; excess spans evicted
    "task_type_model_routing": {},  # per-task type model override e.g. {"tldr": "haiku", "fix": "sonnet"}
    "replay_interrupted_on_startup": False,  # re-queue interrupted tasks on server restart (opt-in)
    "reactions_enabled": True,
    "reaction_configs": [
        {
            "name": "repeated_tool_failure",
            "event_type": "error",
            "event_match": r"(?:tool|command).*failed|exit code [1-9]",
            "threshold": 3,
            "window_seconds": 300,
            "action": "escalate",
            "action_payload": {"strategy": "suggest_alternative"},
        },
        {
            "name": "same_tool_repeated",
            "event_type": "tool_call",
            "event_match": r"^(?:bash|shell|exec):",
            "threshold": 5,
            "window_seconds": 180,
            "action": "warn",
            "action_payload": {"message": "Same tool called 5+ times — consider alternative approach"},
        },
        {
            "name": "loop_detected",
            "event_type": "state_change",
            "event_match": r"loop.*detected",
            "threshold": 1,
            "window_seconds": 0,
            "action": "abort",
            "action_payload": {"message": "Behavioral loop detected — aborting task"},
        },
    ],
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


def _detect_dep_cycle(tasks: list[dict]) -> list[str] | None:
    """Detect circular dependencies in a task list using DFS.

    Returns a list of task IDs forming the cycle, or None if no cycle found.
    Used before importing tasks or starting a swarm batch to prevent deadlock.
    """
    # Build adjacency: task_id → set of dependency IDs (only within this task set)
    task_ids = {t["id"] for t in tasks if t.get("id")}
    adj: dict[str, set[str]] = {}
    for task in tasks:
        tid = task.get("id")
        if not tid:
            continue
        deps = task.get("depends_on") or []
        if isinstance(deps, str):
            try:
                deps = json.loads(deps)
            except Exception:
                deps = []
        # Only consider deps that exist in the same batch (intra-batch cycles)
        adj[tid] = {d for d in deps if d in task_ids}

    # DFS cycle detection (white/grey/black coloring)
    WHITE, GREY, BLACK = 0, 1, 2
    color = {tid: WHITE for tid in adj}
    path: list[str] = []

    def dfs(node: str) -> list[str] | None:
        color[node] = GREY
        path.append(node)
        for neighbor in adj.get(node, set()):
            if color.get(neighbor) == GREY:
                # Cycle found — extract the cycle portion of path
                cycle_start = path.index(neighbor)
                return path[cycle_start:]
            if color.get(neighbor) == WHITE:
                result = dfs(neighbor)
                if result is not None:
                    return result
        path.pop()
        color[node] = BLACK
        return None

    for tid in list(adj.keys()):
        if color[tid] == WHITE:
            cycle = dfs(tid)
            if cycle is not None:
                return cycle
    return None

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

async def _replay_interrupted_tasks(task_queue: Any, claude_dir: Path) -> list[tuple[str, str]]:
    """Build resume descriptions for interrupted tasks with prior event context.

    Reads events.jsonl to find workers that started but never completed, then
    reads per-worker JSONL for the last 3 state changes as resume context.
    Returns list of (task_id, resume_description) for the caller to re-queue.
    Only runs when replay_interrupted_on_startup=True.
    """
    if not GLOBAL_SETTINGS.get("replay_interrupted_on_startup", False):
        return []
    try:
        await task_queue._ensure_db()
        async with aiosqlite.connect(str(task_queue._db_path)) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, description, worker_id FROM tasks WHERE status = 'interrupted'"
            ) as cur:
                interrupted = [dict(r) for r in await cur.fetchall()]
        if not interrupted:
            return []

        # Load global events.jsonl to find which worker_ids actually started
        started_workers: set[str] = set()
        done_workers: set[str] = set()
        global_bus = claude_dir / "events.jsonl"
        if global_bus.exists():
            try:
                with open(global_bus) as f:
                    for line in f:
                        try:
                            obj = json.loads(line.strip())
                        except Exception:
                            continue
                        wid = obj.get("worker_id", "")
                        state = ""
                        try:
                            state = json.loads(obj.get("data", "{}")).get("state", "")
                        except Exception:
                            pass
                        if state == "started":
                            started_workers.add(wid)
                        elif state in ("done", "failed"):
                            done_workers.add(wid)
            except Exception:
                pass

        results: list[tuple[str, str]] = []
        for task in interrupted:
            worker_id = task.get("worker_id") or ""
            # Skip if worker never started or completed cleanly
            if worker_id and worker_id in done_workers:
                continue

            # Read per-worker JSONL for last 3 state_change events
            prior_context = ""
            log_dir = claude_dir / "orchestrator-logs"
            worker_jsonl = log_dir / f"events-{worker_id}.jsonl" if worker_id else None
            if worker_jsonl and worker_jsonl.exists():
                state_events: list[str] = []
                try:
                    with open(worker_jsonl) as f:
                        for line in f:
                            try:
                                obj = json.loads(line.strip())
                            except Exception:
                                continue
                            if obj.get("event_type") == "state_change":
                                try:
                                    content = json.loads(obj.get("content", "{}"))
                                    state_events.append(
                                        f"  - {content.get('state', '?')}: {content.get('reason', '')}"
                                    )
                                except Exception:
                                    pass
                    if state_events:
                        prior_context = (
                            "\n\n---\n**Prior execution context (last events before interruption):**\n"
                            + "\n".join(state_events[-3:])
                            + "\nCheck git log for any partial commits before continuing."
                        )
                except Exception:
                    pass

            resume_desc = (
                f"{task['description']}\n\n"
                f"**Note:** This task was previously interrupted mid-execution and is being resumed."
                f"{prior_context}"
            )
            results.append((task["id"], resume_desc))
        return results
    except Exception as e:
        logger.warning("_replay_interrupted_tasks failed (fail-open): %s", e)
        return []

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


# ─── Tool Subsets per Task Type ────────────────────────────────────────────────
# Stripe Blueprint pattern: different agent types get different tool subsets.
# Claude Code supports --allowed-tools and --disallowed-tools to constrain tools.

_TOOL_SUBSETS: dict[str, tuple[list[str], list[str]]] = {
    # review: read-only — no editing, no file creation
    "review": (
        ["Read", "Grep", "Glob", "Bash", "WebSearch", "WebFetch", "NotebookRead"],
        ["Edit", "Write", "NotebookEdit", "MultiEdit"],
    ),
    # fix: same as implement but focused
    "fix": (
        ["Read", "Edit", "Write", "Bash", "Grep", "Glob"],
        [],
    ),
    # implement: full tools (default — no restriction needed)
    "implement": ([], []),
    # test: allows test file creation but not broad refactoring
    "test": (
        ["Read", "Edit", "Write", "Bash", "Grep", "Glob", "NotebookEdit"],
        [],
    ),
}


def _parse_task_type(description: str) -> str | None:
    """Infer task type from description text.

    Looks for patterns like:
    - ===TASK=== metadata: "type: review"
    - Keywords: "review", "fix", "implement", "test"
    Returns None for implement (default = full tools).
    """
    desc_lower = description.lower()
    meta_match = re.search(r"type:\s*(\w+)", desc_lower)
    if meta_match:
        t = meta_match.group(1)
        if t in _TOOL_SUBSETS:
            return t

    if any(k in desc_lower for k in ["review", "code review", "static analysis", "audit"]):
        return "review"
    if any(k in desc_lower for k in ["fix", "bug", "patch", "hotfix"]):
        return "fix"
    if any(k in desc_lower for k in ["test", "spec", "e2e"]):
        return "test"
    if any(k in desc_lower for k in ["tldr", "summarize", "summary"]):
        return "tldr"
    return None  # default: implement (full tools)


def _build_tool_flags(task_type: str | None) -> str:
    """Build --allowed-tools or --disallowed-tools flags for claude -p.

    Returns empty string if task_type is None (default full tools).
    """
    if not task_type or task_type not in _TOOL_SUBSETS:
        return ""
    allowed, disallowed = _TOOL_SUBSETS[task_type]
    if allowed:
        return f' --allowed-tools "{",".join(allowed)}"'
    elif disallowed:
        return f' --disallowed-tools "{",".join(disallowed)}"'
    return ""


# ─── Task Schema / JSON Envelope (Multi-agent Gap 3) ─────────────────────────


def _format_task_schema_block(task_schema: dict) -> str:
    """Format a parsed task schema into a markdown block for injection into task files."""
    if not task_schema:
        return ""
    lines = ["\n\n---\n\n## Task Contracts (Multi-agent §Gap3)"]
    if criteria := task_schema.get("acceptance_criteria"):
        lines.append("**Acceptance Criteria** (oracle will check these):")
        for c in criteria:
            lines.append(f"- {c}")
    if inputs := task_schema.get("input_files"):
        lines.append("\n**Expected Input Files:**")
        for f in inputs:
            lines.append(f"- `{f}`")
    if provides := task_schema.get("provides"):
        lines.append("\n**This task provides:**")
        for p in provides:
            lines.append(f"- {p}")
    if requires := task_schema.get("requires"):
        lines.append("\n**This task requires:**")
        for r in requires:
            lines.append(f"- {r}")
    return "\n".join(lines)


def _parse_task_schema(description: str) -> dict:
    """Extract optional JSON schema envelope from a task description.

    Multi-agent Gap 3: structured input/output contracts for swarm tasks.
    Workers that include a JSON block specify explicit acceptance criteria,
    required input files, and expected output artifacts for the oracle to check.

    Format (embedded JSON block in description):
    ```json
    {
      "acceptance_criteria": ["All auth tests pass", "No imports added"],
      "input_files": ["src/auth.py"],
      "provides": ["AuthService class"],
      "requires": ["UserModel from users.py"]
    }
    ```

    Returns parsed dict or {} if no valid JSON block found.
    """
    # Look for ```json ... ``` or raw JSON object embedded in description
    m = re.search(r'```json\s*(\{.*?\})\s*```', description, re.DOTALL)
    if not m:
        # Try inline JSON object
        m = re.search(r'\{[^{}]*"acceptance_criteria"[^{}]*\}', description, re.DOTALL)
    if not m:
        return {}
    try:
        data = json.loads(m.group(1) if m.lastindex else m.group())
        if not isinstance(data, dict):
            return {}
        # Normalize fields — only keep known keys
        result: dict = {}
        for key in ("acceptance_criteria", "input_files", "provides", "requires"):
            if key in data and isinstance(data[key], list):
                result[key] = [str(v)[:200] for v in data[key][:10]]
        return result
    except (json.JSONDecodeError, AttributeError):
        return {}
