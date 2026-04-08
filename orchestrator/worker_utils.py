"""
worker_utils.py — Output helpers, lint reflection loop, and LoopDetectionService.

Extracted from worker.py to keep that file under 1500 lines.

Imports:
    from worker_utils import (
        _distill_output, _truncate_output, _strip_error_context,
        _run_lint_check, LoopDetectionService,
        MAX_LINES, MAX_BYTES, DISTILL_THRESHOLD, MAX_REFLECTION_RETRIES,
    )
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

MAX_LINES = 2000
MAX_BYTES = 50 * 1024          # 50KB soft cap for log truncation
DISTILL_THRESHOLD = 200 * 1024  # 200KB — distill with LLM if log exceeds this
MAX_REFLECTION_RETRIES = 3

DISTILL_PROMPT = """Extract key facts from this tool output. Focus on:
- Error messages and their types
- File paths and line numbers
- Definite conclusions or results
- Commands executed and their effects

Respond with ONLY the distilled facts, no commentary. If no errors or key facts, say "No significant output."

---
{output}
---"""


# ─── Output Truncation Helpers ────────────────────────────────────────────────

async def _distill_output(text: str, project_dir: Path) -> str:
    """Use lightweight LLM to distill large tool output into key facts.

    Saves full output to a temp file and returns a summary. Preserves error
    details and file paths that simple head/tail truncation loses.
    """
    import tempfile
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".log", prefix="clade-distill-", delete=False
    )
    tmp.write(text)
    tmp.close()
    tmp_path = tmp.name

    distill_prompt = DISTILL_PROMPT.format(output=text[:180 * 1024])

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
            return _truncate_output(text)
    except Exception:
        return _truncate_output(text)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _truncate_output(text: str, max_lines: int = MAX_LINES, max_bytes: int = MAX_BYTES) -> str:
    """Truncate output to max_lines and max_bytes. Adds marker when truncation occurs."""
    lines = text.splitlines()
    marker = ""
    if len(lines) > max_lines:
        truncated = "\n".join(lines[:max_lines])
        marker = f"\n[...truncated {len(lines) - max_lines} lines...]"
    else:
        truncated = text

    if len(truncated.encode("utf-8")) > max_bytes:
        encoded = truncated.encode("utf-8")
        truncated = encoded[:max_bytes].decode("utf-8", errors="replace")
        marker = f"\n[...truncated to {max_bytes} bytes...]"

    return truncated + marker if marker else truncated


def _strip_error_context(text: str | None) -> str:
    """Strip verbose error messages, keeping first 500 chars for LLM context."""
    if not text:
        return ""
    return text[:500].replace("\n", " ").strip()


# ─── Minimal-Patch Lint Target Extraction (Recursive Debugging pattern) ──────

# Matches ruff/mypy/pylint style: path/to/file.py:42: or path/to/file.py:42:5:
_LINT_LOCATION_RE = re.compile(
    r"^(?P<file>[^\s:][^:]*\.(?:py|sh|ts|tsx|js|jsx))"
    r":(?P<line>\d+)"
    r"(?::\d+)?:\s*(?P<rest>.+)$"
)


def _extract_lint_targets(lint_output: str, max_targets: int = 5) -> list[str]:
    """Parse lint output and return up to max_targets 'file:line: message' strings.

    Used to generate targeted fix directives (Recursive Debugging pattern).
    Handles ruff/pylint output format: 'path/to/file.py:42:5: E501 Line too long'.
    Returns empty list if no parseable locations found.
    """
    targets: list[str] = []
    seen: set[str] = set()
    for line in lint_output.splitlines():
        m = _LINT_LOCATION_RE.match(line.strip())
        if m:
            key = f"{m.group('file')}:{m.group('line')}"
            if key not in seen:
                seen.add(key)
                targets.append(f"{key}: {m.group('rest')[:120]}")
            if len(targets) >= max_targets:
                break
    return targets


# ─── Reflection Loop (Aider pattern) ─────────────────────────────────────────
# After worker runs and produces changes, check for lint errors and re-run with
# error context injected. Up to MAX_REFLECTION_RETRIES rounds.

async def _run_lint_check(project_dir: Path) -> str:
    """Run linters on changed files. Returns formatted lint output or empty string.

    Checks: ruff (Python), shellcheck (Shell), tsc --noEmit (TypeScript/TSX).
    Runs only on files actually modified (via git diff --name-only HEAD).
    """
    diff_proc = await asyncio.create_subprocess_exec(
        "git", "diff", "--name-only", "HEAD",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        cwd=str(project_dir),
    )
    try:
        stdout, _ = await asyncio.wait_for(diff_proc.communicate(), timeout=10)
    except asyncio.TimeoutError:
        diff_proc.kill()
        await diff_proc.communicate()
        return ""
    changed = [f.strip() for f in stdout.decode().splitlines() if f.strip()]
    if not changed:
        return ""

    lint_lines: list[str] = []

    # Python: ruff preferred, pylint fallback
    py_files = [f for f in changed if f.endswith(".py")]
    if py_files:
        ruff_proc = await asyncio.create_subprocess_exec(
            "ruff", "check", *py_files,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(project_dir),
        )
        try:
            out, _ = await asyncio.wait_for(ruff_proc.communicate(), timeout=30)
            if ruff_proc.returncode != 0 and out:
                lint_lines.append("## Ruff (Python)\n")
                lint_lines.append(out.decode(errors="replace"))
        except asyncio.TimeoutError:
            ruff_proc.kill()
            await ruff_proc.communicate()
        if not lint_lines:
            pylint_proc = await asyncio.create_subprocess_exec(
                "pylint", *py_files[:10],
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=str(project_dir),
            )
            try:
                out, _ = await asyncio.wait_for(pylint_proc.communicate(), timeout=30)
                if pylint_proc.returncode != 0 and out:
                    lint_lines.append("## Pylint (Python)\n")
                    lint_lines.append(out.decode(errors="replace")[:3000])
            except asyncio.TimeoutError:
                pylint_proc.kill()
                await pylint_proc.communicate()

    # Shell: shellcheck
    sh_files = [f for f in changed if f.endswith((".sh", ".bash"))]
    if sh_files:
        sc_proc = await asyncio.create_subprocess_exec(
            "shellcheck", "-S", "warning", *sh_files,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=str(project_dir),
        )
        try:
            out, _ = await asyncio.wait_for(sc_proc.communicate(), timeout=30)
            if out:
                lint_lines.append("## ShellCheck (Shell)\n")
                lint_lines.append(out.decode(errors="replace"))
        except asyncio.TimeoutError:
            sc_proc.kill()
            await sc_proc.communicate()

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
            await tsc_proc.communicate()

    result = "\n".join(lint_lines)
    if result and "error" in result.lower():
        return result[:5000]
    return ""


# ─── Loop Detection Service (Gemini CLI pattern) ──────────────────────────────

class LoopDetectionService:
    """Detect behavioral loops within a worker run.

    Tracks:
    - tool+args repetition: same tool called with same args ≥5×
    - content repetition: same output hash seen ≥10×
    - turn count: total LLM turns ≥30 (signals infinite loop without progress)
    """

    def __init__(self) -> None:
        self._tool_args_counts: dict[str, int] = {}
        self._content_hashes: dict[str, int] = {}
        self._turn_count: int = 0
        self._loop_detected: bool = False
        self._loop_reason: str | None = None

    def track_tool_call(self, tool: str, args: str) -> None:
        """Record a tool call."""
        key = f"{tool}:{args[:200]}"
        self._tool_args_counts[key] = self._tool_args_counts.get(key, 0) + 1
        if self._tool_args_counts[key] == 5:
            self._loop_detected = True
            self._loop_reason = f"repeated_tool_args:{tool} (seen 5 times)"

    def track_content_hash(self, content: str) -> None:
        """Record output content hash."""
        if not content:
            return
        h = str(hash(content[:1000]))
        self._content_hashes[h] = self._content_hashes.get(h, 0) + 1
        if self._content_hashes[h] == 10:
            self._loop_detected = True
            self._loop_reason = f"repeated_content (same output seen 10 times)"

    def track_turn(self) -> None:
        """Increment turn counter."""
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
