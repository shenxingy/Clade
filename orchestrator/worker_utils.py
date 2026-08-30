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
import fnmatch
import hashlib
import json
import logging
import os
import re
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

from pytest_report import color_free_env, force_verbose, parse_results

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

MAX_LINES = 2000
MAX_BYTES = 50 * 1024          # 50KB soft cap for log truncation
DISTILL_THRESHOLD = 200 * 1024  # 200KB — distill with LLM if log exceeds this
MAX_REFLECTION_RETRIES = 3

# Model for distill/lint-reflection claude calls. This is a documented leaf
# (no module-level project imports), so worker.py overwrites this at import
# time with config.HAIKU_MODEL (the pinned dated snapshot). The alias
# fallback keeps standalone imports (tests, REPL) working via the claude CLI.
HAIKU_MODEL = "haiku"

# Pure-judge containment: distill/rank claude -p calls have their stdout
# parsed — user settings must not load, or a prompt-type Stop hook's
# {"ok":true} reply replaces the real answer (see config.SETTING_SOURCES_NONE,
# commit 386a862). worker.py re-asserts this at import time (leaf module).
SETTING_SOURCES_NONE = '--setting-sources ""'

# ─── Task File Prompt Blocks (moved from worker.py for line-count budget) ─────

EDIT_DISCIPLINE_BLOCK = (
    "\n\n---\n\n"
    "## Edit Discipline\n"
    "- `old_string` must be unique in the file. Include 3+ surrounding lines of context if needed.\n"
    "- Never include line-number prefixes (e.g. `12\\t`) in `old_string` / `new_string` — strip them first.\n"
    "- Prefer minimal, targeted edits over large block replacements.\n"
)

SEARCH_CONVENTIONS_BLOCK = (
    "\n\n---\n\n"
    "## Search Conventions\n"
    "Use these shorthand patterns when navigating the codebase:\n"
    "- **FindClass `<ClassName>`** → `grep -rn 'class <ClassName>' --include='*.py'`\n"
    "- **FindFunction `<fn>`** → `grep -rn 'def <fn>' --include='*.py'`\n"
    "- **FindFunction `<fn>` in `<cls>`** → find method scoped to class\n"
    "- **FindSnippet `<exact_string>`** → `grep -rn '<exact_string>'`\n"
    "- **FindFile `<pattern>`** → `find . -name '<pattern>' -not -path '*/.*'`\n"
    "\n"
    "**Context Checkpoint (OpenHands CAT pattern)**: when you have finished reading "
    "files and understood the task, write a 2-3 sentence summary to "
    "`.claude/ctx-checkpoint.md` before making any edits. "
    "This helps you stay focused and avoids re-reading files unnecessarily.\n"
)

COMPLETION_CONTRACT_BLOCK = (
    "\n\n---\n\n"
    "## Completion Report\n"
    "When fully done, end your response with exactly this JSON block:\n"
    "```json\n"
    '{"status": "done", "summary": "1-2 sentences: what you did", '
    '"next_actions": [], "artifacts": ["path/to/changed/file.py"]}\n'
    "```\n"
    'Use `"status": "partial"` if you could not finish, `"blocked"` if stuck.\n'
    "In `summary`, also declare negative scope (controversial): anything you "
    "deliberately excluded, and anything you are uncertain about — reviewers "
    "should learn the weak spots from you, not discover them.\n"
)

# ─── Fallback Commit (bare git when committer.sh is not installed) ────────────
# POSIX-ERE secret patterns mirroring configs/scripts/checks.sh. The fallback
# path exists precisely because ~/.claude/scripts is not deployed, so the
# staged-secret scan is inlined here instead of shelling out to checks.sh.
_SECRET_ERE = (
    "-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}"
    "|gh[pousr]_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{22}"
    "|sk-ant-[A-Za-z0-9_-]{40}|AIza[0-9A-Za-z_-]{35}|xox[baprs]-[A-Za-z0-9-]{10}"
)


_TEST_FILE_RE = re.compile(
    r"(^|/)(test_[^/]+\.py"          # pytest: test_foo.py
    r"|[^/]+_test\.(py|go)"          # foo_test.py / foo_test.go
    r"|[^/]+\.(test|spec)\.[jt]sx?)$"  # JS/TS: foo.test.ts / foo.spec.tsx
)
_TEST_DIR_RE = re.compile(r"(^|/)(tests?|__tests__|spec)/")


def _is_test_file(path: str) -> bool:
    """True when a changed path is a test file (Agent-Fingerprint: test inclusion
    is both a quality signal and a merge-rate lever). Matches pytest/JS/TS/Go
    naming conventions and conventional test directories."""
    p = path.strip().replace("\\", "/")
    return bool(_TEST_FILE_RE.search(p) or _TEST_DIR_RE.search(p))


ORACLE_REJECT_MARKER = "REJECTED by oracle review"


def oracle_reject_depth(description: str) -> int:
    """How many times this task's lineage has already been oracle-rejected.

    Each requeue appends ORACLE_REJECT_MARKER to the retry description, so the
    count accumulates across the whole retry chain. Shared by
    oracle_retry_sample_count (fan-out width) and the reject-round cap
    (worker.py: total rounds before escalating instead of requeuing again).
    """
    return description.count(ORACLE_REJECT_MARKER)


def oracle_retry_sample_count(description: str, is_critical: bool, configured_n: int) -> int:
    """How many retry samples to spawn after an oracle rejection (Agentless §6C).

    Plateau escape (audit 2026-06-18): sequential `--continue` retry refines the
    SAME approach, so a fundamentally-wrong first attempt never escapes it. The
    first rejection gets ONE sequential retry (cheap, usually enough). If that is
    ALSO rejected — the lineage carries `ORACLE_REJECT_MARKER` once per prior
    rejection, so depth>=1 — the approach is plateauing: fan out `configured_n`
    DIVERSE attempts instead. Critical-path tasks fan out on the first rejection.
    Bounded to fire once (depth<2) so re-queues can't blow up exponentially.
    """
    depth = oracle_reject_depth(description)
    diverse = (depth >= 1 or is_critical) and depth < 2
    return max(1, configured_n) if diverse else 1


def _fallback_commit_cmd(commit_msg: str, files_arg: str, task_id: str | None = None) -> str:
    """Bare-git commit command used when committer.sh is not installed.

    Mirrors committer.sh's pre-commit gate: stage, scan ADDED staged-diff
    lines for secrets (fail-closed — CLADE_ALLOW_SECRETS=1 overrides), then
    commit. Exits 65 on a secret hit so callers can tell a policy abort from
    an ordinary git failure; the stage is reset so nothing is left half-done.

    When task_id is given, an X-Clade-Task trailer marks the commit
    agent-authored for commit-archeology's agent/human segmentation.
    """
    trailers = ""
    if task_id:
        trailers = " -m " + shlex.quote(f"X-Clade-Task: {task_id}")
    return (
        f"git add {files_arg} && "
        f'if [ "${{CLADE_ALLOW_SECRETS:-0}}" != "1" ] && '
        f'git diff --cached | grep -E "^\\+" | grep -vE "^\\+\\+\\+" | '
        f"grep -qE -e {shlex.quote(_SECRET_ERE)}; then "  # -e: pattern starts with '-'
        f'echo "checks: staged secret detected — commit aborted" >&2; '
        f"git reset -q; exit 65; fi && "
        f"git commit -m {shlex.quote(commit_msg)}{trailers}"
    )


def _parse_observation_contract(log_text: str) -> dict | None:
    """Extract the structured JSON completion report from a worker log.

    Looks for the last ```json ... ``` block containing status/summary keys.
    Returns the parsed dict or None if not found / invalid.
    """
    matches = list(re.finditer(r'```json\s*(\{[^`]+\})\s*```', log_text, re.DOTALL))
    for m in reversed(matches):
        try:
            data = json.loads(m.group(1))
            if "status" in data and "summary" in data:
                return data
        except (json.JSONDecodeError, KeyError):
            continue
    return None

def micro_compact(text: str, max_chars: int = 2000) -> str:
    """Synchronous micro-compaction for mid-task output (learn-cc s06).

    Truncates text to max_chars with a head+tail window to preserve both
    the start (import statements, function signatures) and the end (errors,
    results). Injects a [N chars omitted] marker at the cut point.
    """
    if not text or len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max_chars - head
    omitted = len(text) - max_chars
    return text[:head] + f"\n... [{omitted:,} chars omitted] ...\n" + text[-tail:]


def persist_large_output(text: str, output_dir: Path, prefix: str = "tool-output") -> str:
    """Write large output to a file and return a compact reference string (learn-cc s06).

    When tool output exceeds a threshold, the full content is saved to a file
    in output_dir so the agent can re-read it on demand. Returns a short
    reference string with the path and a micro_compact summary.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    import hashlib
    fname = f"{prefix}-{hashlib.md5(text[:200].encode()).hexdigest()[:8]}.txt"
    path = output_dir / fname
    try:
        path.write_text(text, encoding="utf-8")
        summary = micro_compact(text, max_chars=800)
        return f"[Full output saved to {path}]\n{summary}"
    except Exception:
        return micro_compact(text, max_chars=1200)


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
            "--model", HAIKU_MODEL,
            "--dangerously-skip-permissions",
            "--no-input-prompt",
            *shlex.split(SETTING_SOURCES_NONE),
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


async def _run_project_tests(
    project_dir: Path,
    timeout: int = 60,
    *,
    config_dir: Path | None = None,
    fail_closed: bool = False,
) -> tuple[bool, str]:
    """Run the project's test command after a worker commits (Sweep §Gap3).

    Reads `test_cmd` from `.claude/orchestrator.json`. Falls back to auto-detection:
    - pytest if .venv/bin/pytest or pytest exists
    Returns (passed, output_summary). Fails open on any error.
    """
    test_cmd: str | None = None
    config_file = (config_dir or project_dir) / ".claude" / "orchestrator.json"
    if config_file.exists():
        try:
            cfg = json.loads(config_file.read_text())
            test_cmd = cfg.get("test_cmd")
        except Exception:
            pass

    if not test_cmd:
        # Auto-detect: try .venv/bin/pytest first, then system pytest
        launcher = _pytest_launcher(project_dir)
        if launcher:
            test_cmd = f"{launcher} tests/ -q --tb=short -x 2>&1 | tail -20"

    if not test_cmd:
        return (
            (False, "[deterministic test_cmd unavailable]")
            if fail_closed
            else (True, "")
        )

    try:
        proc = await asyncio.create_subprocess_shell(
            test_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(project_dir),
            # The verdict here is the exit code, so colour cannot corrupt it —
            # but `output` below is handed to the model, and escape sequences
            # there are unreadable context billed as tokens.
            env=color_free_env(),
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return (
                not fail_closed,
                f"[test_cmd timed out after {timeout}s]",
            )
        passed = proc.returncode == 0
        output = out.decode("utf-8", errors="replace").strip()[-1000:]  # last 1KB
        return passed, output
    except Exception as e:
        return not fail_closed, f"[test_cmd error: {e}]"


# ─── Intramorphic Testing (OpenHands §Gap3) ───────────────────────────────────
# Compare test results before vs after a fix to detect regressions without a
# ground-truth test oracle. A test that was PASSING before and is now FAILING
# is a regression introduced by the fix — not a pre-existing failure.

def _parse_pytest_results(output: str) -> dict[str, bool]:
    """Parse pytest -v output into {test_id: passed} dict.

    Delegates to pytest_report, which strips terminal colour first — the local
    regex silently returned {} whenever the environment forced it on.
    """
    return parse_results(output)


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
    task_id=None,
) -> str:
    """Compare post-commit test results against pre-fix baseline.

    Reads baseline from {claude_dir}/test-baseline-{task_id}.json (written before
    the worker starts). Namespaced by task_id because claude_dir is shared across
    concurrent swarm workers — a fixed filename races. Returns a regression
    warning string, or "" if no regressions found. Cleans up the baseline file
    regardless of outcome.
    """
    baseline_file = claude_dir / f"test-baseline-{task_id}.json"
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


def _project_python(project_dir: Path) -> str:
    """Interpreter to run a project's tests with: the project venv if present,
    else the orchestrator's own interpreter (which has pytest). Never bare
    'python' — that may be py2 or lack the deps the repro test imports."""
    venv_py = project_dir / ".venv" / "bin" / "python"
    return str(venv_py) if venv_py.exists() else sys.executable


async def _run_repro_filter(
    project_dir: Path, claude_dir: Path, task_id, timeout: int = 30
) -> tuple[bool | None, str]:
    """Re-run the persisted reproduction test against the fixed code (Agentless §6B).

    _generate_repro_test persists a repro to {claude_dir}/repro-test-{task_id}.py
    ONLY when it was confirmed failing on the buggy code. Re-running it after the
    fix is the executable proof the bug is actually resolved: it must now PASS. The
    existing project suite can't catch an unfixed bug it has no test for — this
    closes that gap. Returns (passed, output):
      - (True,  ...)  repro now passes — fix verified
      - (False, ...)  repro still fails — the fix did NOT resolve the bug
      - (None,  "")   no repro persisted / couldn't run — fail-open, no signal

    The repro file is namespaced by task_id (claude_dir is shared across concurrent
    swarm workers — an un-namespaced file would race). It is run directly with
    cwd=project_dir (the worktree) so imports resolve against the FIXED code; no
    temp copy is written into the worktree. The persisted repro is removed in
    `finally` regardless of outcome.
    """
    repro_file = claude_dir / f"repro-test-{task_id}.py"
    if not repro_file.exists():
        return None, ""
    try:
        proc = await asyncio.create_subprocess_exec(
            _project_python(project_dir), "-m", "pytest", str(repro_file),
            "-x", "-q", "--tb=short",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            cwd=str(project_dir),
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return None, "(repro filter timed out)"
        output = out.decode("utf-8", errors="replace").strip()
        return (proc.returncode == 0), output
    except Exception as e:
        logger.debug("_run_repro_filter failed: %s", e)
        return None, ""
    finally:
        repro_file.unlink(missing_ok=True)


def _pytest_launcher(project_dir: Path) -> str | None:
    """How to invoke pytest for `project_dir`, or None when it cannot be.

    Order matters. The project's own venv wins, because the project's tests
    need the project's dependencies. A bare `pytest` is only correct when the
    name actually resolves — emitting it unchecked is how the baseline came
    back empty on every macOS run: the shell printed "command not found", the
    parser saw no result lines, and `_find_intramorphic_regressions` compared
    an empty dict against an empty dict and reported all-clear forever. A gate
    that measures nothing reports the same thing as a gate that passes.

    `sys.executable -m pytest` is the last resort rather than the first choice:
    it is guaranteed to resolve, but it runs the ORCHESTRATOR's pytest and
    dependency set against someone else's project, which is right often enough
    to beat measuring nothing and wrong often enough not to prefer it.
    """
    venv_pytest = project_dir / ".venv" / "bin" / "pytest"
    if venv_pytest.exists():
        return shlex.quote(str(venv_pytest))
    if not ((project_dir / "pytest.ini").exists() or (project_dir / "pyproject.toml").exists()):
        return None
    if shutil.which("pytest"):
        return "pytest"
    return f"{shlex.quote(sys.executable)} -m pytest"


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
        launcher = _pytest_launcher(project_dir)
        if launcher:
            test_cmd = f"{launcher} tests/ --tb=no 2>&1 | head -300"

    if not test_cmd:
        return {}

    # force_verbose, not a bare "add -v": pytest verbosity is count(-v) - count(-q),
    # so the old default (`-v --tb=no -q`) was verbosity 0 and printed dots. The
    # baseline came back empty every time, and an empty baseline makes
    # _find_intramorphic_regressions structurally incapable of reporting one.
    test_cmd = force_verbose(test_cmd)

    try:
        proc = await asyncio.create_subprocess_shell(
            test_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(project_dir),
            env=color_free_env(),
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
                "--model", HAIKU_MODEL,
                "--dangerously-skip-permissions",
                *shlex.split(SETTING_SOURCES_NONE),
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


# ─── Worker-state helpers (moved from worker.py for line-count budget) ────────


def _claude_transcript_root() -> Path:
    """Where Claude Code keeps per-project session transcripts."""
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    base = Path(override).expanduser() if override else Path.home() / ".claude"
    return base / "projects"


def _encode_project_path(project_dir: Path) -> str:
    """Claude Code's on-disk name for a project's transcript directory.

    Measured against the 60 transcript directories on a real machine: the
    absolute path has ``/``, ``.`` and ``_`` each replaced by ``-``
    (``/home/u/projects/snap_dragon_packaging`` ->
    ``-home-u-projects-snap-dragon-packaging``). The mapping is lossy — a
    ``foo_bar`` and a ``foo-bar`` sibling encode identically — which is
    tolerable here because the result only feeds an advisory activity
    heuristic, never a decision.
    """
    return re.sub(r"[/._]", "-", str(project_dir))


def _compute_activity_state(project_dir: Path | None) -> str:
    """Determine activity state by reading Claude Code's JSONL session file.

    Composio pattern: maps JSONL entry types to activity states.
    Returns: 'active', 'waiting_input', 'blocked', or 'unknown'.

    Takes the directory the agent RUNS in (a worktree, when the worker has
    one), because that is what Claude Code encodes into the transcript path.

    This returned "unknown" unconditionally until 2026-08-29, in three
    independent ways: it was handed ``<project>/.claude`` and took ``.parent``
    as if it were ``~/.claude``; it globbed ``projects/*/sessions/*.jsonl``
    when transcripts sit directly in ``projects/<encoded>/``; and the ``*``
    over projects would have reported an unrelated repository's session,
    whichever had the newest mtime. Its test built the wrong layout itself,
    so it stayed green over all three.
    """
    if not project_dir:
        return "unknown"
    try:
        session_dir = _claude_transcript_root() / _encode_project_path(project_dir)
        if not session_dir.is_dir():
            return "unknown"
        jsonl_files = sorted(
            (str(p) for p in session_dir.glob("*.jsonl")),
            key=lambda p: os.path.getmtime(p),
            reverse=True,
        )
        if not jsonl_files:
            return "unknown"
        with open(jsonl_files[0], "rb") as f:
            f.seek(max(0, os.path.getsize(jsonl_files[0]) - _ACTIVITY_TAIL_BYTES))
            tail = f.read().decode("utf-8", errors="replace")
        lines = tail.strip().splitlines()
        for line in reversed(lines):
            state = _activity_from_entry(line)
            if state:
                return state
        return "unknown"
    except Exception:
        return "unknown"


# How far back to read. The last line is very often bookkeeping rather than a
# turn, so the scan has to walk past several entries to find a conversational
# one; 4 KB was not reliably enough for that.
_ACTIVITY_TAIL_BYTES = 65536

# Entry types that are bookkeeping, not conversation. Counted over a real
# 900-entry transcript: assistant 282, attachment 156, user 147, then
# last-prompt / mode / permission-mode / bridge-session / atis-latch / ai-title
# / pr-link / queue-operation / file-history-* — every one of which can be the
# final line while the agent is mid-turn.
_ACTIVITY_TURN_TYPES = ("assistant", "user", "system")


def _content_block_types(entry: dict) -> set[str]:
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return {"text"}
    if isinstance(content, list):
        return {b.get("type") for b in content if isinstance(b, dict)}
    return set()


def _activity_from_entry(line: str) -> str | None:
    """Map one transcript line to an activity state, or None if it is not a turn.

    Grounded in the schema Claude Code actually writes, not the shape the
    original Composio port assumed. There is no top-level ``tool_use``,
    ``result``, ``error`` or ``permission_request`` entry type: tool calls are
    ``tool_use`` CONTENT BLOCKS inside an ``assistant`` entry, tool returns are
    ``tool_result`` blocks inside a ``user`` entry, and the one blocking signal
    is a ``system`` entry with ``preventedContinuation``.
    """
    line = line.strip()
    if not line or not line.startswith("{"):
        return None
    try:
        entry = json.loads(line)
    except (ValueError, TypeError):
        return None
    if not isinstance(entry, dict):
        return None
    entry_type = entry.get("type")
    if entry_type not in _ACTIVITY_TURN_TYPES:
        return None

    if entry_type == "system":
        # stop_hook_summary carries preventedContinuation when a Stop hook
        # refused to let the turn end — the agent is held, not working.
        return "blocked" if entry.get("preventedContinuation") else None

    blocks = _content_block_types(entry)
    if entry_type == "assistant":
        # A tool call means work is in flight; text/thinking alone means the
        # turn produced its answer and the agent is waiting.
        return "active" if "tool_use" in blocks else "waiting_input"
    # entry_type == "user": either a tool result feeding the next step, or a
    # fresh instruction. Both mean the agent has work to do.
    return "active"


# ─── Git control surface ──────────────────────────────────────────────────────
# A git worktree bounds the working tree, not the repository. `.git` is SHARED:
# from inside a worktree, `git rev-parse --git-common-dir` resolves to the
# PARENT repo's `.git`, so an agent can write `<main>/.git/hooks/pre-commit`
# and it executes the next time the operator commits in the main checkout.
# Reproduced on this machine — a hook written from a worktree ran for a commit
# made in the parent repo. Workers spawn with --dangerously-skip-permissions,
# so nothing else stops that.
#
# Prevention needs an OS sandbox: the worker must be able to write `.git` to
# commit at all, so no git-level setting closes it. What IS available cheaply
# is detection, and it is exact — measured across `worktree add`, a commit
# inside the worktree, and `worktree remove`, this digest does not move, while
# both a planted hook and a `core.fsmonitor` entry change it.

GIT_CONTROL_FILES = ("config",)
GIT_CONTROL_DIRS = ("hooks",)


async def preserve_worktree_wip(
    worktree_path: Path | None, branch_name: str | None, reason: str
) -> str | None:
    """Commit whatever the agent had written before its worktree is destroyed.

    A worker commits exactly once, at the end of verification. `stop()` skips
    verification by design and then runs `git worktree remove --force`, so
    every uncommitted byte was deleted — including on the AUTOMATIC paths
    (loop detection and the stuck-worker timeout), where nobody is watching.
    The branch itself survives worktree removal, so a WIP commit on it makes
    the work recoverable with `git checkout <branch>` while still freeing the
    disk.

    Returns the commit SHA, or None when there was nothing to save.
    """
    if not worktree_path or not branch_name:
        return None
    try:
        if not Path(worktree_path).is_dir():
            return None

        async def _run(*args: str) -> tuple[int, str]:
            proc = await asyncio.create_subprocess_exec(
                "git", *args, cwd=str(worktree_path),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            return proc.returncode or 0, out.decode(errors="replace").strip()

        code, dirty = await _run("status", "--porcelain")
        if code != 0 or not dirty:
            return None
        code, _ = await _run("add", "-A")
        if code != 0:
            return None
        code, _ = await _run(
            "-c", "core.hooksPath=/dev/null",  # never run repo hooks on a rescue commit
            "commit", "--no-verify", "-m", f"wip: worker stopped ({reason})",
        )
        if code != 0:
            return None
        code, sha = await _run("rev-parse", "HEAD")
        return sha if code == 0 else None
    except Exception:
        logger.exception("failed to preserve worktree WIP before cleanup")
        return None


def _as_env_patterns(value: Any) -> list[str]:
    """Normalise a settings value into a list of fnmatch patterns.

    A bare string would otherwise iterate per character, and a scalar or dict
    misconfiguration must never crash a spawn — a malformed denylist is a
    configuration bug, not a reason to stop working.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value]
    return []


def git_control_surface(git_common_dir: Path | None) -> dict[str, str]:
    """Digest every file that can turn a git command into code execution.

    Covers `.git/hooks/*` and `.git/config` — the latter because
    `core.fsmonitor`, `core.pager`, `diff.*.textconv` and aliases all execute
    a command the operator never typed. Returns {relative path: sha256}.
    """
    surface: dict[str, str] = {}
    if not git_common_dir:
        return surface
    try:
        base = Path(git_common_dir)
        targets: list[Path] = [base / name for name in GIT_CONTROL_FILES]
        for dirname in GIT_CONTROL_DIRS:
            d = base / dirname
            if d.is_dir():
                targets.extend(sorted(p for p in d.iterdir() if p.is_file()))
        for path in targets:
            try:
                surface[str(path.relative_to(base))] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
            except OSError:
                continue
    except Exception:
        return surface
    return surface


def git_control_surface_changes(
    before: Mapping[str, str], after: Mapping[str, str]
) -> list[str]:
    """Human-readable diff of two surfaces. Empty list means untouched."""
    changes: list[str] = []
    for name in sorted(set(after) - set(before)):
        changes.append(f"added {name}")
    for name in sorted(set(before) - set(after)):
        changes.append(f"removed {name}")
    for name in sorted(set(before) & set(after)):
        if before[name] != after[name]:
            changes.append(f"modified {name}")
    return changes


def _check_file_ownership(
    changed_files: list[str],
    own_files: list[str],
    forbidden_files: list[str],
) -> tuple[bool, str]:
    """Check changed files against own_files/forbidden_files globs. Returns (ok, reason)."""
    if not own_files and not forbidden_files:
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
        if forbidden_files and _matches(f, forbidden_files):
            return False, f"File '{f}' matches FORBIDDEN_FILES pattern"

    # Check own files (if set, every changed file must match at least one pattern)
    if own_files:
        for f in changed_files:
            if not _matches(f, own_files):
                return False, f"File '{f}' not in OWN_FILES patterns"

    return True, ""


async def _undo_last_commit(project_dir: Path) -> None:
    """git reset HEAD~1 — undo the just-made commit so it cannot be pushed later."""
    try:
        reset_proc = await asyncio.create_subprocess_exec(
            "git", "reset", "HEAD~1",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(project_dir),
        )
        try:
            await asyncio.wait_for(reset_proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            reset_proc.kill()
            await reset_proc.communicate()
    except Exception:
        pass


async def _maybe_enqueue_classify_retry(
    w: Any,
    task_queue: Any,
) -> bool:
    """If `auto_classify_retry` is on and this worker's failure is auto-retryable,
    enqueue a fresh task with the classifier's hint and (possibly) a downgraded
    model. Returns True if a retry task was enqueued.

    Skip rules (in order, all must pass):
      1. setting `auto_classify_retry` is True
      2. worker has a classified error object (not just a free-form failure)
      3. description is not a Loop/Plan/STUCK-RETRY descendant — those have their
         own retry pipelines
      4. attempt count parsed from existing `[AUTO-RETRY n/N]` prefix < N
      5. classifier's `derive_retry_decision()` returns non-None

    Failure modes are all logged-and-swallowed: a classifier crash must never
    block the normal failure persistence path.
    """
    try:
        # Lazy imports — worker_utils is a documented leaf module (stdlib-only
        # at module level); config/error_classifier are leaves too, but the
        # conventions gate counts module-level project imports.
        from config import GLOBAL_SETTINGS
        from error_classifier import (
            derive_retry_decision as _derive_retry_decision,
            parse_retry_prefix as _parse_retry_prefix,
        )
        from cascade_policy import (
            escalation_source,
            is_strong_route,
            retry_fields,
        )

        err = getattr(w, "_failure_classified", None)
        if err is None:
            return False
        if getattr(w, "_classify_retry_enqueued", False) or is_strong_route(
            getattr(w, "route_reason", None)
        ):
            return False
        cascade_source = escalation_source(w, "repeated_error")
        cascade_retry = _derive_retry_decision(
            err,
            attempt=1,
            max_attempts=2,
            current_model=w.model,
        )
        if cascade_source and cascade_retry is not None:
            original = await task_queue.get(w.task_id)
            await task_queue.add(
                f"{w.description}\n\n---\nCheap attempt hit a repeated runtime error; "
                "retry once on the strong tier.",
                w.model,
                **retry_fields(w, original or {}, "repeated_error"),
            )
            w._classify_retry_enqueued = True
            return True
        if not GLOBAL_SETTINGS.get("auto_classify_retry", False):
            return False

        desc = w.description or ""
        # Don't auto-retry tasks owned by other retry pipelines.
        for marker in ("[Loop-", "[Plan-", "[STUCK-RETRY]"):
            if desc.startswith(marker):
                return False

        # Parse existing retry prefix to know which attempt this is.
        parsed = _parse_retry_prefix(desc)
        if parsed is not None:
            attempt, max_attempts = parsed
        else:
            attempt = 1
            max_attempts = max(1, int(GLOBAL_SETTINGS.get("auto_classify_retry_max", 2)))

        decision = _derive_retry_decision(
            err,
            attempt=attempt,
            max_attempts=max_attempts,
            current_model=w.model,
            model_fallback=GLOBAL_SETTINGS.get("auto_classify_retry_model_fallback") or {},
        )
        if decision is None:
            return False

        # Strip any existing AUTO-RETRY prefix before re-prefixing.
        stripped = desc
        if parsed is not None:
            from error_classifier import _RETRY_PREFIX_RE  # local import — leaf reuse
            stripped = _RETRY_PREFIX_RE.sub("", desc, count=1)

        retry_desc = (
            f"{decision.new_description_prefix} {stripped}\n\n---\n"
            f"{decision.hint_block}"
        )
        await task_queue.add(
            retry_desc,
            decision.model,
            own_files=w.own_files,
            forbidden_files=w.forbidden_files,
            agent_runtime=getattr(w, "agent_runtime", None),
            effort=getattr(w, "effort", None),
            parent_task_id=w.task_id,
        )
        logger.info(
            "Auto-classify retry: task %s [%s] → enqueued retry (model=%s, attempt=%d/%d)",
            w.task_id, err.reason.value if hasattr(err, "reason") else "?",
            decision.model, attempt + 1, max_attempts,
        )
        return True
    except Exception:
        logger.exception("auto-classify retry helper raised; skipping retry")
        return False
