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
import json
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


# ─── Post-Commit Test Runner (Sweep §Gap3) ───────────────────────────────────


async def _run_project_tests(project_dir: Path, timeout: int = 60) -> tuple[bool, str]:
    """Run the project's test command after a worker commits (Sweep §Gap3).

    Reads `test_cmd` from `.claude/orchestrator.json`. Falls back to auto-detection:
    - pytest if .venv/bin/pytest or pytest exists
    Returns (passed, output_summary). Fails open on any error.
    """
    test_cmd: str | None = None
    config_file = project_dir / ".claude" / "orchestrator.json"
    if config_file.exists():
        try:
            cfg = json.loads(config_file.read_text())
            test_cmd = cfg.get("test_cmd")
        except Exception:
            pass

    if not test_cmd:
        # Auto-detect: try .venv/bin/pytest first, then system pytest
        venv_pytest = project_dir / ".venv" / "bin" / "pytest"
        if venv_pytest.exists():
            test_cmd = f"{venv_pytest} tests/ -q --tb=short -x 2>&1 | tail -20"
        elif (project_dir / "pytest.ini").exists() or (project_dir / "pyproject.toml").exists():
            test_cmd = "pytest tests/ -q --tb=short -x 2>&1 | tail -20"

    if not test_cmd:
        return True, ""  # no test command configured; skip silently

    try:
        proc = await asyncio.create_subprocess_shell(
            test_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(project_dir),
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return True, f"[test_cmd timed out after {timeout}s]"
        passed = proc.returncode == 0
        output = out.decode("utf-8", errors="replace").strip()[-1000:]  # last 1KB
        return passed, output
    except Exception as e:
        return True, f"[test_cmd error: {e}]"


# ─── Intramorphic Testing (OpenHands §Gap3) ───────────────────────────────────
# Compare test results before vs after a fix to detect regressions without a
# ground-truth test oracle. A test that was PASSING before and is now FAILING
# is a regression introduced by the fix — not a pre-existing failure.

_PYTEST_RESULT_RE = re.compile(r'^(.+::.+?)\s+(PASSED|FAILED|ERROR)')


def _parse_pytest_results(output: str) -> dict[str, bool]:
    """Parse pytest -v output into {test_id: passed} dict."""
    results: dict[str, bool] = {}
    for line in output.splitlines():
        m = _PYTEST_RESULT_RE.match(line.strip())
        if m:
            results[m.group(1).strip()] = m.group(2) == "PASSED"
    return results


def _find_intramorphic_regressions(
    baseline: dict[str, bool],
    post_edit: dict[str, bool],
) -> list[str]:
    """Return test IDs that were passing before the fix but are now failing."""
    return [
        tid for tid, was_passing in baseline.items()
        if was_passing and not post_edit.get(tid, True)
    ]


async def _run_intramorphic_check(
    project_dir: Path,
    claude_dir: Path,
    test_output: str,
) -> str:
    """Compare post-commit test results against pre-fix baseline.

    Reads baseline from {claude_dir}/test-baseline.json (written before worker starts).
    Returns a regression warning string, or "" if no regressions found.
    Cleans up the baseline file regardless of outcome.
    """
    baseline_file = claude_dir / "test-baseline.json"
    if not baseline_file.exists() or not test_output:
        return ""
    try:
        baseline = json.loads(baseline_file.read_text())
        post_results = _parse_pytest_results(test_output)
        regressions = _find_intramorphic_regressions(baseline, post_results)
        if regressions:
            return (
                f"Intramorphic regression detected — "
                f"{len(regressions)} test(s) newly failing after fix:\n"
                + "\n".join(f"  - {t}" for t in regressions[:5])
            )
        return ""
    except Exception as e:
        logger.debug("_run_intramorphic_check failed: %s", e)
        return ""
    finally:
        baseline_file.unlink(missing_ok=True)


async def _capture_test_baseline(project_dir: Path, timeout: int = 30) -> dict[str, bool]:
    """Run tests on the clean worktree (before worker edits) to capture baseline.

    Returns {test_id: passed} mapping or {} if tests can't be run.
    Only activates for projects with detectable test commands.
    Short timeout: must not delay worker startup significantly.
    """
    test_cmd: str | None = None
    config_file = project_dir / ".claude" / "orchestrator.json"
    if config_file.exists():
        try:
            test_cmd = json.loads(config_file.read_text()).get("test_cmd")
        except Exception:
            pass

    if not test_cmd:
        venv_pytest = project_dir / ".venv" / "bin" / "pytest"
        if venv_pytest.exists():
            test_cmd = f"{venv_pytest} tests/ -v --tb=no -q 2>&1 | head -300"
        elif (project_dir / "pytest.ini").exists() or (project_dir / "pyproject.toml").exists():
            test_cmd = "pytest tests/ -v --tb=no -q 2>&1 | head -300"

    if not test_cmd:
        return {}

    # Ensure -v for per-test result parsing
    if "pytest" in test_cmd and " -v" not in test_cmd:
        test_cmd = test_cmd.replace("pytest ", "pytest -v ", 1)

    try:
        proc = await asyncio.create_subprocess_shell(
            test_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(project_dir),
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            logger.debug("_capture_test_baseline timed out after %ds", timeout)
            return {}
        return _parse_pytest_results(out.decode("utf-8", errors="replace"))
    except Exception as e:
        logger.debug("_capture_test_baseline failed: %s", e)
        return {}


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


# ─── Task Ranking (extracted from worker.py) ──────────────────────────────────


async def _rank_tasks(task_queue: Any, claude_dir: Path) -> None:
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
        m = re.search(r'\[.*?\]', text, re.DOTALL)
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
