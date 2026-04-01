"""
Orchestrator worker — execution engine.
Worker, WorkerPool, SwarmManager.
TLDR/scoring in worker_tldr.py, oracle/review in worker_review.py.
GitHub sync functions live in github_sync.py.
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
import os
import re
import shlex
import signal
import time
import uuid
from pathlib import Path
from typing import Any

from config import (
    GLOBAL_SETTINGS,
    _MODEL_ALIASES,
    _estimate_cost,
    _parse_token_usage,
)
from task_queue import TaskQueue
from github_sync import _gh_update_issue_status
from session_tree import SessionTree
from worker_tldr import _generate_code_tldr
from worker_review import _oracle_review
from event_stream import EventStream
from tracing import TracingService, start_task_span, start_llm_span, end_llm_span, start_tool_span, end_tool_span
from reactions import ReactionExecutor

logger = logging.getLogger(__name__)

# ─── Output Truncation Helpers ───────────────────────────────────────────────
MAX_LINES = 2000
MAX_BYTES = 50 * 1024  # 50KB
DISTILL_THRESHOLD = 200 * 1024  # 200KB — distill if output exceeds this

DISTILL_PROMPT = """Extract key facts from this tool output. Focus on:
- Error messages and their types
- File paths and line numbers
- Definite conclusions or results
- Commands executed and their effects

Respond with ONLY the distilled facts, no commentary. If no errors or key facts, say "No significant output."

---
{output}
---"""


async def _distill_output(text: str, project_dir: Path) -> str:
    """Use lightweight LLM to distill large tool output into key facts.

    Saves full output to a .distilled-orig file and returns a summary.
    This preserves error details and file paths that simple truncation loses.
    """
    import tempfile
    # Save full output to temp file (never lose information)
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".log", prefix="clade-distill-", delete=False
    )
    tmp.write(text)
    tmp.close()
    tmp_path = tmp.name

    distill_prompt = DISTILL_PROMPT.format(output=text[:180 * 1024])  # limit input to 180KB

    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", distill_prompt,
            "--model", "claude-haiku-4-5-20251001",
            "--dangerously-skip-permissions",
            "--no-input-prompt",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(project_dir),
        )
        stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        summary = stdout_bytes.decode("utf-8", errors="replace").strip()

        if summary and summary != "No significant output.":
            return (
                f"{summary}\n\n"
                f"[Tool output was large ({len(text) // 1024}KB). "
                f"Full output saved to: {tmp_path}]\n"
            )
        else:
            # Haiku found nothing significant — just return truncated version
            return _truncate_output(text)
    except Exception:
        # On any error (timeout, subprocess failure), fall back to truncation
        return _truncate_output(text)
    finally:
        # Clean up temp file after 1 hour (consumer should copy if needed)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _truncate_output(text: str, max_lines: int = MAX_LINES, max_bytes: int = MAX_BYTES) -> str:
    """Truncate output to max_lines and max_bytes, preferring line limit.

    Adds [...truncated...] marker only when actual truncation occurs.
    """
    lines = text.splitlines()
    if len(lines) > max_lines:
        truncated = "\n".join(lines[:max_lines])
        marker = f"\n[...truncated {len(lines) - max_lines} lines...]"
    else:
        truncated = text

    if len(truncated.encode("utf-8")) > max_bytes:
        # Find truncation point by byte index
        encoded = truncated.encode("utf-8")
        truncated = encoded[:max_bytes].decode("utf-8", errors="replace")
        marker = f"\n[...truncated to {max_bytes} bytes...]"

    if "truncated" in locals() or "marker" in locals():
        if len(lines) > max_lines or len(text.encode("utf-8")) > max_bytes:
            return truncated + marker

    return truncated


def _strip_error_context(text: str | None) -> str:
    """Strip verbose error messages from retry context, keeping summary.

    Removes stack traces, long error output. Keeps first 500 chars of the
    error message which is enough for LLM to understand the issue.
    """
    if not text:
        return ""
    # Keep first 500 chars — enough context, not enough to overflow
    return text[:500].replace("\n", " ").strip()


# ─── Reflection Loop (Aider pattern) ─────────────────────────────────────────
# After worker runs and produces changes, check for lint errors and re-run with
# error context injected. Up to MAX_REFLECTION_RETRIES rounds.
# Aider pattern: lint output → inject as message → retry. Not one-shot fix.

MAX_REFLECTION_RETRIES = 3


async def _run_lint_check(project_dir: Path) -> str:
    """Run linters on changed files. Returns formatted lint output or empty string.

    Checks: ruff (Python), shellcheck (Shell), tsc --noEmit (TypeScript/TSX).
    Runs only on files that were actually modified.
    """
    # Get list of changed files via git
    diff_proc = await asyncio.create_subprocess_exec(
        "git", "diff", "--name-only", "HEAD",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        cwd=str(project_dir),
    )
    try:
        stdout, _ = await asyncio.wait_for(diff_proc.communicate(), timeout=10)
    except asyncio.TimeoutError:
        diff_proc.kill()
        return ""
    changed = [f.strip() for f in stdout.decode().splitlines() if f.strip()]
    if not changed:
        return ""

    lint_lines: list[str] = []

    # Python: ruff (fastest, preferred) or pylint fallback
    py_files = [f for f in changed if f.endswith(".py")]
    if py_files:
        ruff_proc = await asyncio.create_subprocess_exec(
            "ruff", "check", *py_files,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(project_dir),
        )
        try:
            out, err = await asyncio.wait_for(ruff_proc.communicate(), timeout=30)
            if ruff_proc.returncode != 0 and out:
                lint_lines.append("## Ruff (Python)\n")
                lint_lines.append(out.decode(errors="replace"))
        except asyncio.TimeoutError:
            ruff_proc.kill()
        # If ruff not available, try pylint
        if not lint_lines:
            pylint_proc = await asyncio.create_subprocess_exec(
                "pylint", *py_files[:10],  # cap at 10 files
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=str(project_dir),
            )
            try:
                out, err = await asyncio.wait_for(pylint_proc.communicate(), timeout=30)
                if pylint_proc.returncode != 0 and out:
                    lint_lines.append("## Pylint (Python)\n")
                    lint_lines.append(out.decode(errors="replace")[:3000])
            except asyncio.TimeoutError:
                pylint_proc.kill()

    # Shell: shellcheck
    sh_files = [f for f in changed if f.endswith((".sh", ".bash"))]
    if sh_files:
        sc_proc = await asyncio.create_subprocess_exec(
            "shellcheck", "-S", "warning", *sh_files,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(project_dir),
        )
        try:
            out, err = await asyncio.wait_for(sc_proc.communicate(), timeout=30)
            if out:
                lint_lines.append("## ShellCheck (Shell)\n")
                lint_lines.append(out.decode(errors="replace"))
        except asyncio.TimeoutError:
            sc_proc.kill()

    # TypeScript/TSX: tsc --noEmit
    ts_files = [f for f in changed if f.endswith((".ts", ".tsx"))]
    if ts_files:
        tsc_proc = await asyncio.create_subprocess_exec(
            "npx", "tsc", "--noEmit",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(project_dir),
        )
        try:
            out, err = await asyncio.wait_for(tsc_proc.communicate(), timeout=30)
            if tsc_proc.returncode != 0 and (out or err):
                lint_lines.append("## TypeScript (tsc --noEmit)\n")
                lint_lines.append((out + err).decode(errors="replace")[:3000])
        except asyncio.TimeoutError:
            tsc_proc.kill()

    result = "\n".join(lint_lines)
    # Only return if there are actual lint errors (non-empty, non-"no errors" output)
    if result and "error" in result.lower():
        return result[:5000]  # cap at 5000 chars for context injection
    return ""


class LoopDetectionService:
    """Detect behavioral loops within a worker run (Gemini CLI pattern).

    Tracks:
    - tool+args repetition: same tool called with same args ≥5×
    - content repetition: same output hash seen ≥10×
    - turn count: total LLM turns ≥30 (signals infinite loop without progress)

    On detection, sets worker status to "blocked" with reason.
    """

    def __init__(self) -> None:
        self._tool_args_counts: dict[str, int] = {}
        self._content_hashes: dict[str, int] = {}
        self._turn_count: int = 0
        self._loop_detected: bool = False
        self._loop_reason: str | None = None

    def track_tool_call(self, tool: str, args: str) -> None:
        """Record a tool call. Call from session tree or log parsing."""
        key = f"{tool}:{args[:200]}"
        self._tool_args_counts[key] = self._tool_args_counts.get(key, 0) + 1
        if self._tool_args_counts[key] == 5:
            self._loop_detected = True
            self._loop_reason = f"repeated_tool_args:{tool} (seen {5} times)"

    def track_content_hash(self, content: str) -> None:
        """Record output content hash. Call after each tool result."""
        if not content:
            return
        h = str(hash(content[:1000]))
        self._content_hashes[h] = self._content_hashes.get(h, 0) + 1
        if self._content_hashes[h] == 10:
            self._loop_detected = True
            self._loop_reason = f"repeated_content (same output seen {10} times)"

    def track_turn(self) -> None:
        """Increment turn counter. Call after each LLM assistant message."""
        self._turn_count += 1
        if self._turn_count >= 30 and not self._loop_detected:
            self._loop_detected = True
            self._loop_reason = f"excessive_turns:{self._turn_count}"

    @property
    def is_looping(self) -> bool:
        return self._loop_detected

    @property
    def reason(self) -> str | None:
        return self._loop_reason


# ─── Condensers (OpenHands pattern) ──────────────────────────────────────────
# Context compression strategies for large conversation histories.
# Clade applies these at distillation time (large tool output) and can apply
# them to build_task_file context when it grows large.

from abc import ABC, abstractmethod


class Condenser(ABC):
    """Abstract base for context compression strategies."""

    @abstractmethod
    def condense(self, events: list[dict], **kwargs) -> list[dict]:
        """Compress event list. Returns compressed list."""
        ...


class NoOpCondenser(Condenser):
    """Pass through unchanged."""
    def condense(self, events: list[dict], **kwargs) -> list[dict]:
        return events


class RecentEventsCondenser(Condenser):
    """Keep only the last N events. Drop older ones."""
    def __init__(self, keep: int = 50):
        self.keep = keep

    def condense(self, events: list[dict], **kwargs) -> list[dict]:
        if len(events) <= self.keep:
            return events
        removed = len(events) - self.keep
        summary = {
            "type": "summary",
            "role": "system",
            "content": f"[{removed} earlier events omitted — showing last {self.keep}]",
        }
        return [summary] + events[-self.keep:]


class LLMSummarizingCondenser(Condenser):
    """Summarize older events with LLM. Keep recent events intact."""

    def __init__(self, keep_recent: int = 20, summarize_older: bool = True):
        self.keep_recent = keep_recent
        self.summarize_older = summarize_older

    async def _summarize(self, events: list[dict], project_dir: Path) -> str:
        """Use haiku to summarize a list of events."""
        import tempfile
        events_text = "\n".join(
            f"[{e.get('type','?')}] {e.get('content','')[:300]}"
            for e in events[:50]
        )
        prompt = f"""Summarize this agent conversation history. Return a concise paragraph capturing:
- What was accomplished
- What errors or issues were encountered
- What the current state is

Conversation:\n{events_text[:3000]}\n\nSummary:"""

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", prefix="clade-condense-", delete=False
        )
        tmp.write(prompt)
        tmp.close()

        try:
            proc = await asyncio.create_subprocess_exec(
                "claude", "-p", prompt,
                "--model", "claude-haiku-4-5-20251001",
                "--dangerously-skip-permissions", "--no-input-prompt",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                cwd=str(project_dir),
            )
            stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
            summary = stdout_bytes.decode("utf-8", errors="replace").strip()
            return summary[:500] if summary else "[no summary]"
        except Exception:
            return "[summarization failed]"
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    def condense(self, events: list[dict], **kwargs) -> list[dict]:
        if len(events) <= self.keep_recent:
            return events
        project_dir = kwargs.get("project_dir")
        # Return placeholder — actual LLM summarization is async, call separately
        older = events[:-self.keep_recent]
        summary = {
            "type": "summary",
            "role": "system",
            "content": f"[{len(older)} events summarized — async LLM condense pending]",
        }
        return [summary] + events[-self.keep_recent:]


class ObservationMaskingCondenser(Condenser):
    """Mask or truncate large observation/tool result content."""

    def __init__(self, max_obs_bytes: int = 2000):
        self.max_obs_bytes = max_obs_bytes

    def condense(self, events: list[dict], **kwargs) -> list[dict]:
        result = []
        for e in events:
            if e.get("type") in ("tool_result", "observation", "compaction"):
                content = e.get("content", "")
                if len(content.encode()) > self.max_obs_bytes:
                    e = dict(e)
                    e["content"] = (
                        content[:self.max_obs_bytes]
                        + f"\n[...output truncated by condenser ({len(content) - self.max_obs_bytes} bytes omitted)...]\n"
                    )
            result.append(e)
        return result


# ─── Tool Subsets per Task Type ────────────────────────────────────────────────
# Stripe Blueprint pattern: different agent types get different tool subsets.
# Claude Code supports --allowed-tools and --disallowed-tools to constrain tools.

# Tool subset definitions by task type
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

    # Check for metadata format first
    import re as _re

    meta_match = _re.search(r"type:\s*(\w+)", desc_lower)
    if meta_match:
        t = meta_match.group(1)
        if t in _TOOL_SUBSETS:
            return t

    # Keyword inference (lower priority than explicit metadata)
    if any(k in desc_lower for k in ["review", "code review", "static analysis", "audit"]):
        return "review"
    if any(k in desc_lower for k in ["fix", "bug", "patch", "hotfix"]):
        return "fix"
    if any(k in desc_lower for k in ["test", "spec", "e2e"]):
        return "test"

    return None  # default: implement (full tools)


def _build_tool_flags(task_type: str | None) -> str:
    """Build --allowed-tools or --disallowed-tools flags for claude -p.

    Returns empty string if task_type is None (default full tools).
    """
    if not task_type or task_type not in _TOOL_SUBSETS:
        return ""
    allowed, disallowed = _TOOL_SUBSETS[task_type]
    if allowed:
        tools_str = ",".join(allowed)
        return f' --allowed-tools "{tools_str}"'
    elif disallowed:
        tools_str = ",".join(disallowed)
        return f' --disallowed-tools "{tools_str}"'
    return ""


# ─── Pre-hydration ───────────────────────────────────────────────────────────
# Stripe Blueprint pattern: deterministic MCP pre-fetch of linked resources
# before the agent starts. Clade does this via gh CLI + URL fetching.


def _parse_linked_references(text: str) -> dict[str, list[str]]:
    """Parse task description for explicit resource references.

    Returns dict with keys: 'issues', 'prs', 'urls'
    Matches: #123, owner/repo#123, https://github.com/owner/repo/issues/123
    """
    refs: dict[str, list[str]] = {"issues": [], "prs": [], "urls": []}

    # GitHub issue/PR references: #123, owner/repo#123
    issue_refs = re.findall(r"(?:([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+))?#(\d+)", text)
    for owner_repo, _, num in issue_refs:
        ref = f"{owner_repo}#{num}" if owner_repo else f"#{num}"
        refs["issues"].append(ref)

    # GitHub full URLs: https://github.com/owner/repo/issues/123
    gh_urls = re.findall(
        r"https://github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+)/(issues|pull)/(\d+)",
        text,
    )
    for owner, repo, kind, num in gh_urls:
        if kind == "issues":
            refs["issues"].append(f"{owner}/{repo}#{num}")
        elif kind == "pull":
            refs["prs"].append(f"{owner}/{repo}#{num}")

    # Generic URLs
    urls = re.findall(r"https?://[^\s\)>\]\"']+", text)
    refs["urls"] = [u.rstrip(".,;:") for u in urls if u.startswith("http")]

    return refs


async def _pre_hydrate(task_description: str, project_dir: Path | None = None) -> str:
    """Fetch linked resources before agent starts (Stripe Blueprint pre-hydration).

    This is the pre-hydration hook: deterministically fetch content that the agent
    would otherwise have to retrieve via tools. Saves tokens + latency.

    Returns a markdown block with fetched content, or empty string if nothing found.
    """
    refs = _parse_linked_references(task_description)
    blocks: list[str] = []
    fetched: set[str] = set()

    # Fetch GitHub issues
    for ref in refs["issues"]:
        if ref in fetched:
            continue
        try:
            if "#" in ref:
                parts = ref.split("#")
                if len(parts) == 2 and "/" in parts[0]:
                    owner_repo, num = parts
                else:
                    # Local issue #123 — requires gh repo context
                    num = parts[1]
                    owner_repo = None
                    if project_dir:
                        try:
                            proc = await asyncio.create_subprocess_exec(
                                "gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner",
                                cwd=str(project_dir),
                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                            )
                            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
                            if proc.returncode == 0:
                                import json
                                data = json.loads(stdout.decode())
                                owner_repo = data.get("nameWithOwner")
                        except Exception:
                            pass
                    if not owner_repo:
                        continue
                # Fetch issue body
                proc = await asyncio.create_subprocess_exec(
                    "gh", "issue", "view", num, "--json", "title,body,state,labels",
                    cwd=str(project_dir) if project_dir else None,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
                if proc.returncode == 0:
                    import json
                    data = json.loads(stdout.decode())
                    labels = [l["name"] for l in data.get("labels", [])]
                    label_str = f" [{', '.join(labels)}]" if labels else ""
                    blocks.append(
                        f"## Pre-hydrated Issue {owner_repo}#{num}{label_str}\n"
                        f"**State**: {data['state']}\n"
                        f"**Title**: {data['title']}\n\n"
                        f"{data.get('body', '(no body)')[:2000]}"
                    )
                    fetched.add(ref)
        except Exception:
            pass

    # Fetch GitHub PRs
    for ref in refs["prs"]:
        if ref in fetched:
            continue
        try:
            parts = ref.split("#")
            if len(parts) == 2:
                owner_repo, num = parts
                proc = await asyncio.create_subprocess_exec(
                    "gh", "pr", "view", num, "--json", "title,body,state,additions,deletions",
                    cwd=str(project_dir) if project_dir else None,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
                if proc.returncode == 0:
                    import json
                    data = json.loads(stdout.decode())
                    blocks.append(
                        f"## Pre-hydrated PR {owner_repo}#{num}\n"
                        f"**State**: {data['state']}\n"
                        f"**Title**: {data['title']}\n"
                        f"**Changes**: +{data.get('additions', 0)} -{data.get('deletions', 0)}\n\n"
                        f"{data.get('body', '(no body)')[:2000]}"
                    )
                    fetched.add(ref)
        except Exception:
            pass

    if not blocks:
        return ""

    return "\n\n---\n\n# Pre-hydrated Resources (fetched before agent start)\n\n" + "\n\n---\n\n".join(blocks)


# ─── Worker ───────────────────────────────────────────────────────────────────


class Worker:
    def __init__(
        self,
        task_id: str,
        description: str,
        model: str,
        project_dir: Path,
        claude_dir: Path,
        task_type: str | None = None,
    ):
        self.id = str(uuid.uuid4())[:8]
        self.task_id = task_id
        self.description = description
        self.model = model
        self._project_dir = project_dir
        self.task_type = task_type or _parse_task_type(description)
        self._original_project_dir = project_dir  # preserved for restore after worktree cleanup
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
        self._session_tree: SessionTree | None = None  # Pi-style JSONL session tree
        self.verified: bool = False
        self.auto_committed: bool = False
        self.auto_pushed: bool = False
        self.oracle_result: str | None = None
        self.oracle_reason: str | None = None
        self._oracle_requeue: bool = False
        self._oracle_requeue_reason: str | None = None
        self._handoff_requeue: bool = False
        self._handoff_content: str | None = None
        self.model_score: int | None = None
        self.branch_name: str | None = None
        self.pr_url: str | None = None
        self.pr_merged: bool = False
        self._verify_triggered: bool = False
        self.task_timeout: int = 600  # default 10 min
        self.failure_context: str | None = None
        self._worktree_path: Path | None = None
        self._branch_name: str | None = None
        self.own_files: list[str] = []
        self.forbidden_files: list[str] = []
        self._ownership_violation: bool = False
        self._ownership_violation_reason: str | None = None
        self._stuck_detected: bool = False
        self._terminal_persisted: bool = False
        self._loop_detector = LoopDetectionService()
        self._reflection_retries: int = 0
        self._event_stream = EventStream(worker_id=self.id)
        self._tracer = TracingService.get_instance().get_or_create_tracer(self.id)
        self._reaction_executor = ReactionExecutor()
        self._input_tokens: int = 0
        self._output_tokens: int = 0
        self._estimated_cost: float = 0.0
        self._task_span: Any = None

    @property
    def elapsed_s(self) -> int:
        return int((self._finished_at or time.time()) - self.started_at)

    def to_dict(self) -> dict:
        log_tail = ""
        if self._log_path and self._log_path.exists():
            try:
                text = self._log_path.read_text(errors="replace")
                log_tail = _truncate_output(text, max_lines=4, max_bytes=4096)
            except Exception:
                pass
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
            "auto_pushed": self.auto_pushed,
            "branch_name": self.branch_name,
            "pr_url": self.pr_url,
            "pr_merged": self.pr_merged,
            "log_tail": log_tail,
            "failure_context": self.failure_context,
            "worktree_path": str(self._worktree_path) if self._worktree_path else None,
            "oracle_result": self.oracle_result,
            "oracle_reason": self.oracle_reason,
            "model_score": self.model_score,
            "estimated_tokens": self._estimate_tokens(),
            "context_warning": self._estimate_tokens() > 160000,
            "input_tokens": self._input_tokens,
            "output_tokens": self._output_tokens,
            "estimated_cost": self._estimated_cost,
            "loop_detected": self._loop_detector.is_looping,
            "loop_reason": self._loop_detector.reason,
        }

    def _estimate_tokens(self) -> int:
        desc_tokens = len(self.description) // 4
        log_tokens = 0
        if self._log_path and self._log_path.exists():
            try:
                log_tokens = self._log_path.stat().st_size // 4
            except Exception:
                pass
        return desc_tokens + log_tokens

    async def _setup_worktree(self) -> None:
        """Create an isolated git worktree for this worker. Updates self._project_dir on success."""
        worktree_base = self._claude_dir / "worktrees"
        worktree_base.mkdir(parents=True, exist_ok=True)
        self._worktree_path = worktree_base / f"worker-{self.id}"
        self._branch_name = f"orchestrator/task-{self.task_id}"

        wt_proc = await asyncio.create_subprocess_exec(
            "git", "worktree", "add", str(self._worktree_path), "-b", self._branch_name,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(self._project_dir),
        )
        try:
            wt_out, wt_err = await asyncio.wait_for(wt_proc.communicate(), timeout=30)
            if wt_proc.returncode == 0:
                self._project_dir = self._worktree_path
            else:
                try:
                    wt_proc2 = await asyncio.create_subprocess_exec(
                        "git", "worktree", "add", str(self._worktree_path), self._branch_name,
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                        cwd=str(self._project_dir),
                    )
                    try:
                        await asyncio.wait_for(wt_proc2.communicate(), timeout=30)
                    except asyncio.TimeoutError:
                        wt_proc2.kill()
                        await wt_proc2.communicate()
                    if wt_proc2.returncode == 0:
                        self._project_dir = self._worktree_path
                    else:
                        self._worktree_path = None
                except Exception:
                    self._worktree_path = None
        except asyncio.TimeoutError:
            wt_proc.kill()
            await wt_proc.communicate()
            self._worktree_path = None
        except Exception:
            self._worktree_path = None

    async def _build_task_file(self, task_queue: TaskQueue | None) -> Path:
        """Set up log path and write the task file with injected context. Returns task file path."""
        logs = self._claude_dir / "orchestrator-logs"
        logs.mkdir(parents=True, exist_ok=True)
        self._log_path = logs / f"worker-{self.id}.log"
        self.log_file = str(self._log_path)

        # Initialize EventStream JSONL path for crash-safe event logging
        jsonl_path = logs / f"events-{self.id}.jsonl"
        self._event_stream.set_jsonl_path(jsonl_path)
        self._event_stream.emit(
            event_type="state_change",
            event_kind="state_change",
            source="supervisor",
            content={"state": "started", "task_id": self.task_id, "model": self.model},
        )

        task_file = self._claude_dir / f"task-{self.id}.md"
        task_file.parent.mkdir(parents=True, exist_ok=True)

        # Prepend project CLAUDE.md + AGENTS.md for context injection
        effective_description = self.description
        context_blocks = []
        claude_md = self._claude_dir / "CLAUDE.md"
        if claude_md.exists():
            try:
                claude_content = claude_md.read_text(errors="replace").strip()
                if claude_content:
                    context_blocks.append(f"# Project Context (from .claude/CLAUDE.md)\n\n{claude_content}")
            except Exception:
                pass
        agents_md = self._claude_dir / "AGENTS.md"
        if not agents_md.exists():
            agents_md = self._project_dir / "AGENTS.md"
        if agents_md.exists():
            try:
                agents_content = agents_md.read_text(errors="replace").strip()
                if agents_content:
                    context_blocks.append(f"# File Ownership (from AGENTS.md)\n\n{agents_content}")
            except Exception:
                pass
        try:
            tldr = _generate_code_tldr(str(self._original_project_dir))
            if tldr:
                context_blocks.append(f"# Codebase Structure (auto-generated)\n\n{tldr}")
        except Exception:
            pass
        # Pre-hydration: fetch linked GitHub issues/PRs before agent starts (Stripe Blueprint pattern)
        try:
            hydrate_block = await _pre_hydrate(self.description, self._project_dir)
            if hydrate_block:
                context_blocks.append(hydrate_block)
        except Exception:
            pass
        if context_blocks:
            effective_description = "\n\n---\n\n".join(context_blocks) + f"\n\n---\n\n# Task\n\n{self.description}"
        # Inject unread messages from other tasks
        if task_queue:
            try:
                messages = await task_queue.get_messages(self.task_id, unread_only=True)
                if messages:
                    msg_block = "\n\n---\n**Messages from other tasks:**\n"
                    for m in messages:
                        sender = m.get("from_task_id") or "human"
                        msg_block += f"- [{sender}]: {m['content']}\n"
                    effective_description += msg_block
                    await task_queue.mark_messages_read(self.task_id)
            except Exception:
                pass
        task_file.write_text(effective_description)
        return task_file

    def _build_cmd_and_env(self, task_file: Path) -> tuple[str, dict]:
        """Resolve model alias, build shell command, and prepare env dict."""
        _ALLOWED_MODELS = {
            "claude-opus-4-6", "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
            "claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5",
        }
        model = _MODEL_ALIASES.get(self.model, self.model)
        model = model if model in _ALLOWED_MODELS else "claude-sonnet-4-6"
        shell_cmd = (
            f'claude -p "$(cat {shlex.quote(str(task_file))})" --model {model} --dangerously-skip-permissions'
        )
        # Tool subsets per task type (Stripe Blueprint pattern)
        tool_flags = _build_tool_flags(self.task_type)
        if tool_flags:
            shell_cmd += tool_flags
        mcp_config = self._project_dir / ".claude" / "mcp.json"
        if mcp_config.exists():
            shell_cmd += f" --mcp-config {shlex.quote(str(mcp_config))}"

        env = {**os.environ}
        # Unset CLAUDECODE so workers can launch even when the orchestrator itself
        # is started from inside a Claude Code session (prevents "nested session" error)
        env.pop("CLAUDECODE", None)
        if GLOBAL_SETTINGS.get("agent_teams"):
            env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "1"

        return shell_cmd, env

    async def start(self, task_queue: TaskQueue | None = None) -> None:
        await self._setup_worktree()
        task_file = await self._build_task_file(task_queue)
        shell_cmd, env = self._build_cmd_and_env(task_file)

        # Initialize Pi-style JSONL session tree for this worker
        tree_path = self._log_path.with_suffix(".tree.jsonl")
        self._session_tree = SessionTree(tree_path)
        self._session_tree.session_start({
            "worker_id": self.id,
            "task_id": self.task_id,
            "model": self.model,
            "task_type": self.task_type,
            "description": self.description[:200],  # truncate for log
        })
        # Record the task description as the first user entry
        root_id = self._session_tree.user(self.description[:5000])

        with open(self._log_path, "w") as log_fd:
            self.proc = await asyncio.create_subprocess_shell(
                shell_cmd,
                stdout=log_fd,
                stderr=log_fd,
                preexec_fn=os.setsid,
                env=env,
                cwd=str(self._project_dir),
            )
        self.pid = self.proc.pid
        try:
            self.pgid = os.getpgid(self.proc.pid)
        except ProcessLookupError:
            self.pgid = self.proc.pid
        self.status = "running"
        self._event_stream.emit(
            event_type="action",
            event_kind="tool_call",
            source="worker",
            content={"shell_cmd": shell_cmd[:500], "pid": self.pid},
        )
        # Start task span for tracing
        self._task_span = start_task_span(self.id, self.description, self.task_id)

    def is_alive(self) -> bool:
        if self.proc is None:
            return False
        return self.proc.returncode is None

    def _get_activity_state(self) -> str:
        """Determine activity state by reading Claude Code's JSONL session file.

        Composio pattern: maps JSONL entry types to activity states.
        Returns: 'active', 'waiting_input', 'blocked', or 'unknown'.
        """
        if not self._claude_dir:
            return "unknown"
        try:
            # Claude Code session JSONL lives in ~/.claude/projects/{encoded-path}/
            # Each session has a .jsonl file we can read
            projects_dir = self._claude_dir.parent  # typically ~/.claude
            if not projects_dir.exists():
                return "unknown"
            # Find the most recent session .jsonl for this project
            import glob as _glob
            session_pattern = str(projects_dir / "projects" / "*" / "sessions" / "*.jsonl")
            jsonl_files = sorted(
                _glob.glob(session_pattern),
                key=lambda p: os.path.getmtime(p),
                reverse=True,
            )
            if not jsonl_files:
                return "unknown"
            # Read last entry from most recent session file
            with open(jsonl_files[0], "rb") as f:
                f.seek(max(0, os.path.getsize(jsonl_files[0]) - 4096))
                tail = f.read().decode("utf-8", errors="replace")
            lines = tail.strip().splitlines()
            if not lines:
                return "unknown"
            last_line = lines[-1]
            entry = json.loads(last_line)
            last_type = entry.get("type", "")
            # Composio mapping
            if last_type in ("tool_use", "user"):
                return "active"
            elif last_type in ("assistant", "summary", "result"):
                return "waiting_input"
            elif last_type == "error":
                return "blocked"
            elif last_type == "permission_request":
                return "waiting_input"
            return "unknown"
        except Exception:
            return "unknown"

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
        self._verify_triggered = True  # prevent _on_worker_done from running after forced stop
        await self._cleanup_worktree()

    async def poll(self) -> None:
        if not self.is_alive():
            if self._finished_at is None:
                self._finished_at = time.time()
            rc = self.proc.returncode if self.proc else -1
            self.status = "done" if rc == 0 else "failed"
            if self.status == "failed" and self._log_path and self._log_path.exists():
                try:
                    text = self._log_path.read_text(errors="replace")
                    self.failure_context = _truncate_output(text)
                except Exception:
                    pass
            if not self._verify_triggered:
                self._verify_triggered = True
                asyncio.create_task(self._on_worker_done())
            elif self._worktree_path and self._worktree_path.exists():
                asyncio.create_task(self._cleanup_worktree())
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

        # Track activity state via Claude Code JSONL (Composio pattern)
        activity = self._get_activity_state()
        self._event_stream.emit(
            event_type="observation",
            event_kind="llm_call",
            source="worker",
            content={"activity_state": activity},
        )

        # Track turn for loop detection (Gemini CLI pattern)
        self._loop_detector.track_turn()

        # Emit activity to reaction executor
        triggered = self._reaction_executor.record_event(
            "state_change",
            event_name=f"poll:{activity}",
            event_content=activity,
        )
        for reaction in triggered:
            logger.warning(
                "Worker %s reaction triggered: %s — %s",
                self.id, reaction.config.name, reaction.message
            )

    async def _cleanup_worktree(self) -> None:
        if not self._worktree_path:
            return
        cleanup = await asyncio.create_subprocess_exec(
            "git", "worktree", "remove", "--force", str(self._worktree_path),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            cwd=str(self._original_project_dir),
        )
        try:
            await asyncio.wait_for(cleanup.communicate(), timeout=15)
        except Exception:
            pass
        self._worktree_path = None
        self._project_dir = self._original_project_dir  # restore so git cmds still work

    async def _on_worker_done(self) -> None:
        """Run after process exits: verify+commit while worktree is still alive, then clean up."""
        # Write session tree completion entry (Pi-style append-only record)
        if self._session_tree:
            try:
                self._session_tree._write({
                    "type": "worker_done",
                    "status": self.status,
                    "verified": self.verified,
                    "auto_committed": self.auto_committed,
                    "elapsed_s": round(time.time() - self.started_at, 1),
                    "input_tokens": getattr(self, "_input_tokens", None),
                    "output_tokens": getattr(self, "_output_tokens", None),
                    "estimated_cost": getattr(self, "_estimated_cost", None),
                    "failure_context": self.failure_context[:500] if self.failure_context else None,
                })
            except Exception:
                pass
        # Emit completion event to EventStream
        self._event_stream.emit(
            event_type="state_change",
            event_kind="state_change",
            source="supervisor",
            content={
                "state": "done",
                "status": self.status,
                "verified": self.verified,
                "elapsed_s": round(time.time() - self.started_at, 1),
            },
        )
        # Record completion in reaction executor
        if self.status == "failed" and self.failure_context:
            triggered = self._reaction_executor.record_event(
                "error",
                event_name="worker_failed",
                event_content=self.failure_context[:500],
            )
            for reaction in triggered:
                logger.warning("Worker %s reaction: %s — %s", self.id, reaction.config.name, reaction.message)
        elif self.status == "done":
            self._reaction_executor.record_event("state_change", event_name="worker_done")

        # End tracing span
        if self._task_span:
            svc = TracingService.get_instance()
            svc.end_span(self.id, self._task_span,
                         status="ok" if self.status == "done" else "error")
            svc.write_trace(self.id)
            self._task_span = None

        if self.status == "done":
            try:
                verified = await self.verify_and_commit()
            except Exception:
                logger.exception("verify_and_commit failed for worker %s", self.id)
                verified = False
            # Reflection loop (Aider pattern): if verification failed, run lint check and retry
            if not verified and self._reflection_retries < MAX_REFLECTION_RETRIES:
                try:
                    lint_output = await _run_lint_check(self._project_dir)
                    if lint_output:
                        self._reflection_retries += 1
                        logger.info(
                            "Worker %s: reflection retry %d/%d — lint errors found, re-running with context",
                            self.id, self._reflection_retries, MAX_REFLECTION_RETRIES
                        )
                        # Inject lint output as additional context and re-run
                        retry_context = (
                            f"\n\n---\n"
                            f"**IMPORTANT: Previous attempt had lint/verification errors. Fix them.**\n\n"
                            f"Lint output:\n{_strip_error_context(lint_output)}\n\n"
                            f"Task: {self.description}\n"
                        )
                        # Re-run in the same worktree with lint context
                        retry_success = await self._run_with_context(retry_context)
                        if retry_success:
                            self.status = "done"
                            self._loop_detector._loop_detected = False  # reset loop detection on retry
                            self._reflection_retries = 0  # reset on success
                        else:
                            self._reflection_retries += 0  # already incremented
                except Exception:
                    pass
        # Parse token usage from log
        if self._log_path and self._log_path.exists():
            try:
                self._input_tokens, self._output_tokens = _parse_token_usage(self._log_path)
                self._estimated_cost = _estimate_cost(self._input_tokens, self._output_tokens)
            except Exception:
                pass
            # Distill large output: replace log in-place with LLM summary + full output reference
            # This preserves error details that simple truncation loses
            if self._project_dir:
                try:
                    log_size = self._log_path.stat().st_size
                    if log_size > DISTILL_THRESHOLD:
                        raw_text = self._log_path.read_text(errors="replace")
                        distilled = await _distill_output(raw_text, self._project_dir)
                        self._log_path.write_text(distilled, encoding="utf-8")
                        logger.info("Worker %s: distilled %dKB log to %d chars",
                                     self.id, log_size // 1024, len(distilled))
                except Exception:
                    pass
        # Check for handoff file — worker wrote it to signal continuation needed
        handoff_path = self._claude_dir / f"handoff-{self.task_id}.md"
        if handoff_path.exists():
            try:
                self._handoff_content = handoff_path.read_text(errors="replace").strip()
                self._handoff_requeue = bool(self._handoff_content)
                handoff_path.unlink(missing_ok=True)
                logger.info("Handoff file found for task %s — flagging for continuation", self.task_id)
            except Exception:
                pass
        await self._cleanup_worktree()

    def _check_file_ownership(self, changed_files: list[str]) -> tuple[bool, str]:
        """Check changed files against own_files/forbidden_files globs. Returns (ok, reason)."""
        if not self.own_files and not self.forbidden_files:
            return True, ""

        def _matches(filepath: str, patterns: list[str]) -> bool:
            for pat in patterns:
                if pat.endswith("/**"):
                    prefix = pat[:-3]  # "src/db/**" → "src/db"
                    if filepath == prefix or filepath.startswith(prefix + "/"):
                        return True
                if fnmatch.fnmatch(filepath, pat):
                    return True
            return False

        # Check forbidden files
        for f in changed_files:
            if self.forbidden_files and _matches(f, self.forbidden_files):
                return False, f"File '{f}' matches FORBIDDEN_FILES pattern"

        # Check own files (if set, every changed file must match at least one pattern)
        if self.own_files:
            for f in changed_files:
                if not _matches(f, self.own_files):
                    return False, f"File '{f}' not in OWN_FILES patterns"

        return True, ""

    async def verify_and_commit(self) -> bool:
        diff_proc = await asyncio.create_subprocess_exec(
            "git", "diff", "--name-only", "HEAD",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            cwd=str(self._project_dir),
        )
        try:
            stdout, _ = await asyncio.wait_for(diff_proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            diff_proc.kill()
            await diff_proc.communicate()
            return False
        except Exception:
            return False
        untracked_proc = await asyncio.create_subprocess_exec(
            "git", "ls-files", "--others", "--exclude-standard",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            cwd=str(self._project_dir),
        )
        try:
            ut_out, _ = await asyncio.wait_for(untracked_proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            untracked_proc.kill()
            await untracked_proc.communicate()
            return False
        except Exception:
            return False
        changed_files = [
            f for f in (stdout.decode().strip() + "\n" + ut_out.decode().strip()).splitlines()
            if f.strip()
        ]
        if not changed_files:
            return False

        # File ownership enforcement
        ok, reason = self._check_file_ownership(changed_files)
        if not ok:
            self._ownership_violation = True
            self._ownership_violation_reason = reason
            # Discard all changes in worktree
            discard = await asyncio.create_subprocess_exec(
                "git", "checkout", ".",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                cwd=str(self._project_dir),
            )
            try:
                await asyncio.wait_for(discard.communicate(), timeout=10)
            except Exception:
                pass
            clean = await asyncio.create_subprocess_exec(
                "git", "clean", "-fd",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                cwd=str(self._project_dir),
            )
            try:
                await asyncio.wait_for(clean.communicate(), timeout=10)
            except Exception:
                pass
            return False

        diff_summary_proc = await asyncio.create_subprocess_exec(
            "git", "diff", "HEAD", "--stat",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            cwd=str(self._project_dir),
        )
        try:
            diff_out, _ = await asyncio.wait_for(diff_summary_proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            diff_summary_proc.kill()
            await diff_summary_proc.communicate()
            return False

        task_first_line = self.description.splitlines()[0][:80]
        verify_prompt = (
            f"Task was: {task_first_line}\n\n"
            f"Git diff stat:\n{diff_out.decode()}\n\n"
            "If the changes look complete and correct for the task, output exactly: VERIFIED_OK\n"
            "If there are obvious issues or nothing was changed, output: VERIFIED_FAIL: <reason>\n"
            "Output ONLY one of those two responses, nothing else."
        )

        verify_file = self._claude_dir / f"verify-{self.id}.md"
        verify_file.write_text(verify_prompt)
        try:
            verify_proc = await asyncio.create_subprocess_shell(
                f'claude -p "$(cat {shlex.quote(str(verify_file))})" --model claude-haiku-4-5-20251001 --dangerously-skip-permissions',
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                cwd=str(self._project_dir),
            )
            try:
                v_out, _ = await asyncio.wait_for(verify_proc.communicate(), timeout=120)
                result = v_out.decode().strip()
            except asyncio.TimeoutError:
                verify_proc.kill()
                await verify_proc.communicate()
                return False
        finally:
            verify_file.unlink(missing_ok=True)

        if "VERIFIED_OK" not in result:
            return False

        self.verified = True

        commit_msg = f"feat: {task_first_line.lower()}"
        files_arg = " ".join(shlex.quote(f) for f in changed_files[:20])
        committer_path = Path.home() / ".claude/scripts/committer.sh"
        if committer_path.exists():
            commit_cmd = (
                f'bash {shlex.quote(str(committer_path))} '
                f'{shlex.quote(commit_msg)} {files_arg}'
            )
        else:
            commit_cmd = f'git add {files_arg} && git commit -m {shlex.quote(commit_msg)}'
        commit_proc = await asyncio.create_subprocess_shell(
            commit_cmd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(self._project_dir),
        )
        try:
            c_out, c_err = await asyncio.wait_for(commit_proc.communicate(), timeout=30)
            if commit_proc.returncode == 0:
                self.auto_committed = True

                # Oracle validation gate
                if GLOBAL_SETTINGS.get("auto_oracle", False):
                    try:
                        diff_proc = await asyncio.create_subprocess_exec(
                            "git", "diff", "HEAD~1", "HEAD",
                            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                            cwd=str(self._project_dir),
                        )
                        diff_out, _ = await asyncio.wait_for(diff_proc.communicate(), timeout=15)
                        approved, reason = await _oracle_review(
                            self.description, diff_out.decode(), self._claude_dir
                        )
                        self.oracle_result = "approved" if approved else "rejected"
                        self.oracle_reason = reason
                        if not approved:
                            # Undo the commit so rejected work is not accidentally pushed later
                            reset_proc = await asyncio.create_subprocess_exec(
                                "git", "reset", "HEAD~1",
                                stdout=asyncio.subprocess.DEVNULL,
                                stderr=asyncio.subprocess.DEVNULL,
                                cwd=str(self._project_dir),
                            )
                            try:
                                await asyncio.wait_for(reset_proc.communicate(), timeout=10)
                            except asyncio.TimeoutError:
                                reset_proc.kill()
                                await reset_proc.communicate()
                            self.auto_committed = False
                            # Flag for requeue — poll_all will pick this up
                            self._oracle_requeue = True
                            self._oracle_requeue_reason = reason
                            return False
                    except Exception:
                        pass  # fail-open

                branch = f"orchestrator/task-{self.task_id}"
                self.branch_name = branch
                if GLOBAL_SETTINGS.get("auto_push", True):
                    push_proc = await asyncio.create_subprocess_shell(
                        f'git push origin HEAD:{branch} --force-with-lease',
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                        cwd=str(self._project_dir),
                    )
                    try:
                        p_out, p_err = await asyncio.wait_for(push_proc.communicate(), timeout=30)
                        if push_proc.returncode == 0:
                            self.auto_pushed = True
                    except asyncio.TimeoutError:
                        push_proc.kill()
                        await push_proc.communicate()

                log_proc = await asyncio.create_subprocess_exec(
                    "git", "log", "-1", "--oneline",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    cwd=str(self._project_dir),
                )
                try:
                    log_out, _ = await asyncio.wait_for(log_proc.communicate(), timeout=5)
                    self.last_commit = log_out.decode().strip() or self.last_commit
                except asyncio.TimeoutError:
                    log_proc.kill()
                    await log_proc.communicate()
        except asyncio.TimeoutError:
            pass
        return self.auto_committed

    async def _run_with_context(self, extra_context: str) -> bool:
        """Re-run the worker with additional context injected (used by reflection loop).

        Runs in the SAME worktree with a new task file that appends extra_context.
        Returns True if the re-run succeeded (commit made).
        """
        if not self._project_dir or not self._worktree_path:
            return False
        task_file = self._claude_dir / f"task-{self.id}-retry{self._reflection_retries}.md"
        retry_desc = self.description + f"\n\n{extra_context}"
        task_file.write_text(retry_desc, encoding="utf-8")

        shell_cmd, env = self._build_cmd_and_env(task_file)

        # Append to existing log
        log_fd = open(self._log_path, "a") if self._log_path else None
        try:
            self.proc = await asyncio.create_subprocess_shell(
                shell_cmd,
                stdout=log_fd,
                stderr=log_fd,
                preexec_fn=os.setsid,
                env=env,
                cwd=str(self._project_dir),
            )
            self.pid = self.proc.pid
            self.status = "running"
            self._finished_at = None
            self.started_at = time.time()
            # Wait for completion (simple wait, no polling)
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=self.task_timeout)
            except asyncio.TimeoutError:
                self.proc.kill()
                await self.proc.wait()
            rc = self.proc.returncode if self.proc else -1
            self.status = "done" if rc == 0 else "failed"
            if log_fd:
                log_fd.close()
                log_fd = None
            if self.status == "done":
                return await self.verify_and_commit()
            return False
        except Exception:
            if log_fd:
                log_fd.close()
            return False

# ─── Task Ranking ─────────────────────────────────────────────────────────────


async def _rank_tasks(task_queue: "TaskQueue", claude_dir: Path) -> None:
    """Score all unranked pending tasks by impact/urgency using haiku.
    Updates priority_score (0.0–1.0) in DB. 1.0 = highest priority."""
    try:
        all_tasks = await task_queue.list()
        unranked = [t for t in all_tasks
                    if t["status"] == "pending" and not (t.get("priority_score") or 0)]
        if not unranked:
            return
        items = unranked[:20]
        task_lines = "\n".join(
            f'{t["id"]}: {str(t.get("description") or "")[:120]}'
            for t in items
        )
        prompt = (
            "Score these tasks by impact and urgency (0.0=low, 1.0=high). "
            "Return ONLY a JSON array: [{\"id\": \"...\", \"score\": 0.0}, ...]\n\n"
            + task_lines
        )
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                "claude", "-p", prompt,
                "--model", "claude-haiku-4-5-20251001",
                "--dangerously-skip-permissions",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=str(claude_dir),
            ),
            timeout=60,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        text = stdout.decode() if stdout else ""
        # Extract JSON array from response
        import re as _re
        m = _re.search(r'\[.*?\]', text, _re.DOTALL)
        if not m:
            return
        scores = json.loads(m.group())
        for entry in scores:
            tid = entry.get("id")
            score = float(entry.get("score", 0.0))
            if tid:
                await task_queue.update(tid, priority_score=score)
    except Exception:
        pass  # fail-open


# ─── Worker Pool ──────────────────────────────────────────────────────────────


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
        # Guard: prevent spawning a second worker for the same task
        existing = next(
            (w for w in self.workers.values() if w.task_id == task["id"] and w.status in ("running", "starting")),
            None,
        )
        if existing:
            return existing
        model = task.get("model", GLOBAL_SETTINGS.get("default_model", "sonnet"))
        model = _MODEL_ALIASES.get(model, model)
        description = task["description"]
        if GLOBAL_SETTINGS.get("auto_model_routing", False):
            score = task.get("score")
            if score is not None:
                if score >= 80:
                    model = "haiku"
                elif score < 50:
                    model = "sonnet"
                    description = (
                        "⚠ This task scored low on readiness (<50). "
                        "Ask clarifying questions before writing any code. "
                        "Do NOT start implementing until requirements are clear.\n\n"
                        + description
                    )
                if task.get("is_critical_path"):
                    model = {"haiku": "sonnet", "sonnet": "opus"}.get(model, model)
        # Auto-inject past intervention corrections for retried/failed tasks
        failed_reason = task.get("failed_reason")
        if failed_reason:
            try:
                match = await task_queue.find_matching_intervention(failed_reason)
                if match:
                    description = (
                        f"{description}\n\n---\n"
                        f"**Auto-injected correction (from past intervention):**\n"
                        f"{match['correction']}"
                    )
            except Exception:
                pass
        model = _MODEL_ALIASES.get(model, model)
        worker = Worker(
            task["id"],
            description,
            model,
            project_dir,
            claude_dir,
        )
        worker.model_score = task.get("score")
        worker.task_timeout = task.get("timeout", 600)
        worker.own_files = task.get("own_files", [])
        worker.forbidden_files = task.get("forbidden_files", [])
        self.workers[worker.id] = worker
        await task_queue.update(task["id"], status="running", worker_id=worker.id)
        await worker.start(task_queue=task_queue)
        return worker

    async def _handoff_to_worker(
        self,
        parent_task: dict,
        task_queue: TaskQueue,
        project_dir: Path,
        claude_dir: Path,
    ) -> Worker | None:
        """Spawn a child worker from a typed handoff (Codex SDK pattern).

        The parent task has handoff_type (str) and handoff_payload (dict) fields.
        The child worker is spawned with the handoff context injected into its description.
        """
        handoff_type = parent_task.get("handoff_type")
        handoff_payload = parent_task.get("handoff_payload")

        if not handoff_type or not handoff_payload:
            return None

        # Build typed handoff description
        handoff_desc = (
            f"[Handoff: {handoff_type}]\n\n"
            f"**Handoff Type:** {handoff_type}\n"
            f"**Handoff Payload:**\n```json\n{json.dumps(handoff_payload, indent=2)}\n```\n\n"
            f"**Parent Task:** {parent_task.get('description', 'N/A')}\n\n"
            f"## Instructions\n"
            f"Process this typed handoff. The payload contains structured context from the parent worker.\n"
            f"Resume work based on the payload. Use /pickup if available, otherwise continue from the handoff state."
        )

        # Create continuation task
        child_desc = (
            f"{parent_task.get('description', '')}\n\n"
            f"---\n"
            f"**Typed Handoff ({handoff_type}):**\n"
            f"{json.dumps(handoff_payload, indent=2)}\n"
        )

        model = parent_task.get("model", GLOBAL_SETTINGS.get("default_model", "sonnet"))
        model = _MODEL_ALIASES.get(model, model)

        # Add as new task
        new_task_id = await task_queue.add(
            child_desc,
            model,
            own_files=parent_task.get("own_files", []),
            forbidden_files=parent_task.get("forbidden_files", []),
            parent_task_id=parent_task.get("id"),
        )

        # Get the new task and spawn worker
        new_task = await task_queue.get(new_task_id)
        if not new_task:
            return None

        return await self.start_worker(new_task, task_queue, project_dir, claude_dir)

    def get(self, worker_id: str) -> Worker | None:
        return self.workers.get(worker_id)

    def all(self) -> list[Worker]:
        return list(self.workers.values())

    async def poll_all(self, task_queue: TaskQueue, project_dir: Path | None = None) -> None:
        for w in list(self.workers.values()):
            if w.status == "running" and w.task_timeout and w.task_timeout > 0 and w.elapsed_s > w.task_timeout:
                await w.stop()
                w.status = "failed"
                if w._log_path and w._log_path.exists():
                    try:
                        text = w._log_path.read_text(errors="replace")
                        w.failure_context = _truncate_output(text)
                    except Exception:
                        pass
                await task_queue.update(
                    w.task_id,
                    status="failed",
                    elapsed_s=w.elapsed_s,
                    last_commit=w.last_commit,
                )
                if w.failure_context:
                    await task_queue.update(w.task_id, failed_reason=w.failure_context)
                if project_dir and GLOBAL_SETTINGS.get("github_issues_sync"):
                    t = await task_queue.get(w.task_id)
                    if t:
                        asyncio.create_task(_gh_update_issue_status(t, project_dir))
                continue
            # Stuck worker detection: log file mtime unchanged for N minutes
            stuck_timeout = GLOBAL_SETTINGS.get("stuck_timeout_minutes", 15)
            if (w.status == "running" and not w._stuck_detected
                    and stuck_timeout > 0 and w._log_path and w._log_path.exists()):
                try:
                    idle_s = time.time() - w._log_path.stat().st_mtime
                    if idle_s > stuck_timeout * 60:
                        w._stuck_detected = True
                        logger.warning("Worker %s stuck (no log output for %dm) — killing", w.id, stuck_timeout)
                        await w.stop()
                        w.status = "failed"
                        stuck_reason = f"[STUCK] No log output for {int(idle_s)}s (threshold: {stuck_timeout}min)"
                        w.failure_context = stuck_reason
                        await task_queue.update(w.task_id, status="failed",
                                                elapsed_s=w.elapsed_s, failed_reason=stuck_reason)
                        # Requeue with stuck context (skip: already retried, or loop-managed tasks)
                        _is_loop_task = w.description.startswith("[Loop-") or w.description.startswith("[Plan-")
                        if not w.description.startswith("[STUCK-RETRY]") and not _is_loop_task:
                            retry_desc = f"[STUCK-RETRY] {w.description}"
                            await task_queue.add(retry_desc, w.model,
                                                 own_files=w.own_files, forbidden_files=w.forbidden_files)
                        else:
                            logger.warning("Worker %s stuck — not re-queuing (retry=%s, loop=%s)",
                                           w.id, w.description.startswith("[STUCK-RETRY]"), _is_loop_task)
                        if project_dir and GLOBAL_SETTINGS.get("github_issues_sync"):
                            t = await task_queue.get(w.task_id)
                            if t:
                                asyncio.create_task(_gh_update_issue_status(t, project_dir))
                        continue
                except Exception:
                    pass
            # Guard: don't poll() workers already in a terminal state — poll() would
            # overwrite "blocked" with "failed" based on process exit code
            if w.status not in ("done", "failed", "blocked"):
                await w.poll()
            if w.status in ("done", "failed", "blocked"):
                if not w._terminal_persisted:
                    w._terminal_persisted = True
                    await task_queue.update(
                        w.task_id,
                        status=w.status,
                        elapsed_s=w.elapsed_s,
                        last_commit=w.last_commit,
                    )
                    # Persist token/cost data
                    if w._input_tokens or w._output_tokens:
                        await task_queue.update(
                            w.task_id,
                            input_tokens=w._input_tokens,
                            output_tokens=w._output_tokens,
                            estimated_cost=w._estimated_cost,
                        )
                    if w.status == "failed" and w.failure_context:
                        await task_queue.update(w.task_id, failed_reason=w.failure_context)
                    if w.status == "done":
                        try:
                            await task_queue.mark_intervention_success(w.task_id)
                        except Exception:
                            pass
                    if project_dir and GLOBAL_SETTINGS.get("github_issues_sync"):
                        t = await task_queue.get(w.task_id)
                        if t:
                            asyncio.create_task(_gh_update_issue_status(t, project_dir))
                # Oracle rejected → re-queue with rejection reason as context
                if w._oracle_requeue:
                    w._oracle_requeue = False
                    error_summary = _strip_error_context(w._oracle_requeue_reason)
                    retry_desc = (
                        f"{w.description}\n\n---\n"
                        f"Previous attempt was REJECTED by oracle review:\n"
                        f"{error_summary}\n"
                        f"Fix the issue described above. Do NOT repeat the same approach."
                    )
                    await task_queue.add(retry_desc, w.model,
                                        own_files=w.own_files, forbidden_files=w.forbidden_files)
                    logger.info("Oracle rejected task %s — re-queued with reason", w.task_id)
                # File ownership violation → re-queue with violation context
                if w._ownership_violation:
                    w._ownership_violation = False
                    error_summary = _strip_error_context(w._ownership_violation_reason)
                    retry_desc = (
                        f"{w.description}\n\n---\n"
                        f"Previous attempt REJECTED — file ownership violation:\n"
                        f"{error_summary}\n\n"
                        f"You MUST only edit files matching your OWN_FILES patterns. "
                        f"Do NOT touch FORBIDDEN_FILES. Find an alternative approach."
                    )
                    await task_queue.add(retry_desc, w.model,
                                        own_files=w.own_files, forbidden_files=w.forbidden_files)
                    await task_queue.update(
                        w.task_id,
                        failed_reason=f"Ownership violation: {error_summary[:200]}"
                    )
                    logger.info("Ownership violation task %s — re-queued with reason", w.task_id)
                # Worker wrote handoff file → create continuation task
                if w._handoff_requeue:
                    w._handoff_requeue = False
                    continuation_desc = (
                        f"{w.description}\n\n---\n"
                        f"**Continuation — previous session handed off:**\n"
                        f"{w._handoff_content}\n\n"
                        f"Run /pickup if available, then continue from where the previous worker left off."
                    )
                    await task_queue.add(continuation_desc, w.model,
                                        own_files=w.own_files, forbidden_files=w.forbidden_files)
                    logger.info("Handoff task %s → continuation queued", w.task_id)
            else:
                await task_queue.update(
                    w.task_id,
                    elapsed_s=w.elapsed_s,
                    last_commit=w.last_commit,
                )
            # verify_and_commit() is triggered in poll() via _on_worker_done() to ensure
            # it runs before worktree cleanup — no separate trigger needed here
        if GLOBAL_SETTINGS.get("context_budget_warning", True):
            for w in list(self.workers.values()):
                if w.status == "running":
                    tokens = w._estimate_tokens()
                    if tokens > 160000:
                        warn_file = w._claude_dir / f"context-warning-{w.id}.md"
                        if not warn_file.exists():
                            warn_file.write_text(
                                "CONTEXT WARNING: ~80% context window used. "
                                "Run /compact now — preserve current task state, files modified, next steps."
                            )

# ─── Swarm Manager ────────────────────────────────────────────────────────────


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

        # Calculate how many slots to fill
        # Also respect global max_workers
        from config import _deps_met as deps_met_check
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
                blocked_pending = [t for t in pending if not deps_met_check(t, done_ids)]
                if len(blocked_pending) == len(pending):
                    # All pending tasks are blocked and nothing is running to unblock them
                    self._status = "done"
                    self._done_reason = "blocked"
                # else: some tasks have deps met but were claimed by another path — wait
