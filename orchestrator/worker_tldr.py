"""
Task-specific TLDR localization, fault location, repro generation and scoring.

The LLM/subprocess half of the old worker_tldr: every function here either
spawns a claude call, shells out to a test runner, or touches the task DB.
The pure structural analysis it builds on lives in repo_map.py, split out at
1459 of the 1500 lines test_conventions.py enforces.

Not a leaf in the "no project imports" sense — it depends on the stdlib-only
primitives lower in the DAG (fault_localize, pytest_report, runtime_redaction,
repo_map), which is the documented leaf allowance, not an absence of imports.
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import re
import shlex
from pathlib import Path

import aiosqlite
from pytest_report import color_free_env
from runtime_redaction import merge_metadata, redact_runtime

# fault_localize is a stdlib-only leaf (lower in the DAG); importing it keeps
# worker_tldr standalone-importable. Shared scan constants + symbol index live
# there so the multi-language SBFL path and the Python path agree.
from fault_localize import (  # noqa: E402
    _SRC_EXTS, _build_symbol_index, _is_test_file_name,
    detect_test_runner, run_runner_sbfl,
)

# repo_map holds the deterministic structural pass (also stdlib-only + one
# fault_localize import). The localizer consumes three of its helpers; the
# rest of its API is imported directly by session/routes/worker_taskfile.
from repo_map import (  # noqa: E402
    _extract_tldr_sections, _keyword_filter_tldr, _pagerank_centrality,
)

logger = logging.getLogger(__name__)

# Model for TLDR/localization/scoring claude calls. This is a documented leaf
# (no project imports — config included), so worker.py overwrites this at
# import time with config.HAIKU_MODEL (the pinned dated snapshot). The alias
# fallback keeps standalone imports (tests, REPL) working via the claude CLI.
HAIKU_MODEL = "haiku"

# Pure-judge containment: every claude -p call in this module has its stdout
# parsed (JSON / code extraction) — user settings must not load, or a
# prompt-type Stop hook's {"ok":true} reply replaces the real answer (see
# config.SETTING_SOURCES_NONE, commit 386a862). worker.py re-asserts this at
# import time (leaf module — cannot import config). Exec-argv sites expand it
# via shlex.split().
SETTING_SOURCES_NONE = '--setting-sources ""'
# Judges must not mutate files — denies Edit, Write, Bash. Leaf default mirrors
# config.DISALLOWED_TOOLS_JUDGE; worker.py re-asserts at import time.
DISALLOWED_TOOLS_JUDGE = "--disallowed-tools Edit,Write,Bash"

# ─── Two-Phase Task-Specific TLDR Localization (Moatless pattern) ─────────────

# Localizer prompt window. Was 3000 (~750 tokens) — the audit (2026-06-18) found
# that on a few-hundred-file repo the relevant file is often past the cutoff, so
# the localizer never sees it. 8000 (~2k tokens) is still cheap for haiku.
_LOCALIZE_MAP_CHARS = 8000

_LOCALIZE_PROMPT = """\
You are a code navigator. Given a task description and a codebase structure map, \
identify the top-5 most relevant files for completing the task.

Task:
{task}

Codebase structure:
{tldr}

Respond with ONLY a JSON array of file paths (relative paths as shown in the map), \
most relevant first. Example: ["path/to/file.py", "other/file.ts"]
No explanation, no markdown, just the JSON array."""


async def _localize_tldr_for_task(
    task_description: str, tldr: str, project_dir: Path
) -> str:
    """Hybrid: keyword pre-filter + haiku structural selection → top-5 relevant files.

    Moatless pattern: when TLDR is large (>4KB), use haiku to narrow to the
    top-5 most relevant files for this task. Saves tokens and focuses worker.

    Sweep §Gap4: now runs a keyword pre-filter first. If the task contains code
    identifiers, TLDR is pre-filtered to files that mention them. Haiku then
    applies structural understanding over the reduced result set — two-signal
    retrieval improves precision for complex queries.

    Falls back to original TLDR on any error.
    """
    # Sweep §Gap4: keyword pre-filter before haiku (hybrid retrieval), now
    # boosted by deterministic PageRank centrality (audit 2026-06-18) so central
    # files survive the keyword filter even when keyword-poor.
    centrality = _pagerank_centrality(str(project_dir))
    candidate_tldr = _keyword_filter_tldr(task_description, tldr, centrality=centrality)
    sections = _extract_tldr_sections(candidate_tldr)
    if not sections:
        return tldr

    # Build a compact map for haiku (just file paths + first symbol)
    compact_lines: list[str] = []
    for fpath, content in sections.items():
        first_sym = ""
        for line in content.splitlines()[1:]:
            if line.strip():
                first_sym = line.strip()[:60]
                break
        compact_lines.append(f"{fpath}: {first_sym}")
    compact_map = "\n".join(compact_lines)

    prompt = _LOCALIZE_PROMPT.format(
        task=task_description[:600],
        tldr=compact_map[:_LOCALIZE_MAP_CHARS],
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", prompt,
            "--model", HAIKU_MODEL,
            "--dangerously-skip-permissions",
            "--no-input-prompt",
            *shlex.split(SETTING_SOURCES_NONE),
            *shlex.split(DISALLOWED_TOOLS_JUDGE),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(project_dir),
        )
        try:
            stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return tldr

        output = stdout_bytes.decode("utf-8", errors="replace").strip()
        # Extract JSON array
        m = re.search(r'\[.*?\]', output, re.DOTALL)
        if not m:
            return tldr

        picked: list[str] = json.loads(m.group())
        if not isinstance(picked, list):
            return tldr

        # Build filtered TLDR from picked files (preserve original order)
        filtered: list[str] = []
        for fpath in picked[:5]:
            if fpath in sections:
                filtered.append(sections[fpath])
            else:
                # Fuzzy match — haiku might return slightly different paths
                for key in sections:
                    if key.endswith(fpath) or fpath.endswith(key):
                        filtered.append(sections[key])
                        break

        if not filtered:
            return tldr

        result = "\n\n".join(filtered)
        skipped = len(sections) - len(filtered)
        if skipped > 0:
            result += f"\n\n... ({skipped} files omitted — task-localized view)"
        return result

    except Exception:
        return tldr


# ─── Fault Localization Pre-pass (Agentless §6A pattern) ─────────────────────


async def _localize_fault(
    task_description: str, tldr: str, project_dir: Path
) -> str:
    """Structured fault localization pre-pass for bug-fix tasks (Agentless §6A).

    Calls haiku to predict which files and functions are most likely to need
    changes for the given task. Returns a formatted markdown block injected into
    the worker's task file to tighten focus before the repair phase.

    Falls back to empty string on any error (non-critical path).
    Only useful for fix/bug tasks — callers should gate on task type.
    """
    if not tldr or not task_description:
        return ""

    prompt = (
        "You are a code search expert. Given a bug report and codebase structure, "
        "identify the specific files and functions most likely to need changes.\n\n"
        f"Bug/Task:\n{task_description[:500]}\n\n"
        f"Codebase structure:\n{tldr[:_LOCALIZE_MAP_CHARS]}\n\n"
        "Respond ONLY with a JSON object — no preamble, no markdown:\n"
        '{"suspect_files":["path/to/file.py"],'
        '"suspect_functions":["ClassName.method_name","module.function_name"],'
        '"reason":"one-sentence explanation of why these locations are likely"}\n'
        "List at most 3 files and 5 functions. Be specific — prefer exact names over guesses."
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", prompt,
            "--model", HAIKU_MODEL,
            "--dangerously-skip-permissions",
            "--no-input-prompt",
            *shlex.split(SETTING_SOURCES_NONE),
            *shlex.split(DISALLOWED_TOOLS_JUDGE),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(project_dir),
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return ""
        raw = out.decode("utf-8", errors="replace").strip()

        # Extract JSON from response
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if not m:
            return ""
        data = json.loads(m.group())

        files = data.get("suspect_files", [])[:3]
        funcs = data.get("suspect_functions", [])[:5]
        reason = data.get("reason", "")

        if not files and not funcs:
            return ""

        lines = ["## Suspected Change Locations (pre-localized)"]
        if reason:
            lines.append(f"> {reason}\n")
        if files:
            lines.append("**Files most likely to change:**")
            for f in files:
                lines.append(f"- `{f}`")
        if funcs:
            lines.append("\n**Functions most likely to change:**")
            for fn in funcs:
                lines.append(f"- `{fn}`")
        lines.append("\n> Focus your changes on the above locations first.")
        return "\n".join(lines)

    except Exception:
        return ""


# ─── Caller Hints (Sweep §Gap2) ──────────────────────────────────────────────


async def _find_caller_hints(fault_locs_text: str, project_dir: Path) -> str:
    """Find callers of suspect functions to warn about cascade changes (Sweep §Gap2).

    Parses `_localize_fault()` output for function names, then greps to find
    where they're called. Returns a formatted hint block or empty string.
    Falls back to empty string on any error.
    """
    if not fault_locs_text:
        return ""

    # Extract function names from "- `ClassName.method` or `module.func`" lines
    fn_pattern = re.compile(r'`(?:[A-Za-z_]\w*\.)?([A-Za-z_]\w+)\(\)`')
    func_names = fn_pattern.findall(fault_locs_text)[:4]  # max 4 functions to grep
    if not func_names:
        return ""

    caller_map: dict[str, list[str]] = {}
    for fn_name in func_names:
        try:
            proc = await asyncio.create_subprocess_exec(
                "grep", "-rn", "--include=*.py", f"\\b{fn_name}\\b",
                ".",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=str(project_dir),
            )
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                continue
            lines = out.decode("utf-8", errors="replace").splitlines()
            # Filter out the definition line and test files
            callers = [
                l for l in lines
                if f"def {fn_name}" not in l and "test_" not in l
            ][:5]
            if callers:
                caller_map[fn_name] = callers
        except Exception:
            pass

    if not caller_map:
        return ""

    lines = ["**Caller hints** (if you change these functions, update these call sites):"]
    for fn_name, callers in caller_map.items():
        lines.append(f"- `{fn_name}` called at:")
        for c in callers[:3]:
            # Trim to file:line: prefix
            parts = c.split(":", 2)
            if len(parts) >= 2:
                lines.append(f"  - `{parts[0]}:{parts[1]}`")
    return "\n".join(lines)


# ─── SBFL Pre-pass: Failing Test Traceback Analysis (AutoCodeRover §Gap3) ─────


# ─── Assertion-aware SBFL (audit 2026-06-18; found blind in the owlcast run) ──
# A pure assertion failure (`assert foo(x) == y`, foo returns the wrong value
# with NO exception) leaves only the TEST frame in the traceback — the impl
# symbol lives only in the assert SOURCE LINE, invisible to a frame-frequency
# parser. So: parse the failing test's source, find the enclosing test function,
# extract the impl symbols it calls (nearest the failing line first), and resolve
# them to suspect files. Language-agnostic in spirit — the test names its target.

_PY_NONIMPL = {
    "len", "str", "int", "list", "dict", "set", "tuple", "print", "range", "sorted",
    "enumerate", "zip", "map", "filter", "isinstance", "getattr", "setattr", "super",
    "repr", "type", "abs", "min", "max", "sum", "any", "all", "open", "format", "bool",
    "float", "approx", "raises", "fixture", "mark", "fail", "skip", "warns",
    # unittest / mock helpers (assert*/expect* also filtered by prefix below)
    "setUp", "tearDown", "patch", "Mock", "MagicMock", "mock_open", "monkeypatch",
    "caplog", "capsys", "call", "ANY", "sentinel", "subTest", "addCleanup",
}
# _SRC_EXTS / _build_symbol_index now live in fault_localize (imported above) so the
# Python and multi-language SBFL paths share one cross-language symbol resolver.


def _assertion_suspects(output: str, project_dir: Path, blocks: list[str]) -> dict[str, int]:
    """Suspects inferred from the failing test's SOURCE when the traceback has no
    impl frame (assertion failures). Returns {file::symbol: distinct_failing_tests}."""
    suspects: dict[str, int] = {}
    frame_re = re.compile(r'(?P<fpath>[^\s:][^:\s]*\.py):(?P<line>\d+): in (?P<fn>\w+)')
    index: dict[str, str] | None = None
    for block in blocks:
        frames = list(frame_re.finditer(block))
        # The assert site is the last TEST frame in the block (test_ function or
        # a test/conftest file by naming convention — not the "test" substring).
        test_frames = [
            m for m in frames
            if m.group("fn").startswith("test_")
            or _is_test_file_name(m.group("fpath").rsplit("/", 1)[-1])
        ]
        if not test_frames:
            continue
        tf = test_frames[-1]
        fail_line = int(tf.group("line"))
        fpath = tf.group("fpath")
        test_file = Path(fpath) if Path(fpath).is_absolute() else project_dir / fpath
        try:
            tree = ast.parse(test_file.read_text(errors="replace"))
        except Exception:
            continue
        enc = None  # innermost test function containing the failing line
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.lineno <= fail_line <= (node.end_lineno or node.lineno):
                    if enc is None or node.lineno > enc.lineno:
                        enc = node
        if enc is None:
            continue
        calls: list[tuple[int, str]] = []
        for n in ast.walk(enc):
            if isinstance(n, ast.Call):
                name = (n.func.id if isinstance(n.func, ast.Name)
                        else n.func.attr if isinstance(n.func, ast.Attribute) else None)
                if (name and len(name) >= 2 and not name.startswith(("test_", "assert", "expect"))
                        and name not in _PY_NONIMPL):
                    calls.append((abs((n.lineno or fail_line) - fail_line), name))
        if not calls:
            continue
        calls.sort()
        if index is None:
            index = _build_symbol_index(project_dir)
        chosen: set[str] = set()
        for _, name in calls:
            if name in chosen:
                continue
            chosen.add(name)
            f = index.get(name)
            if f:
                suspects[f"{f}::{name}"] = suspects.get(f"{f}::{name}", 0) + 1
            if len(chosen) >= 3:
                break
    return suspects


async def _sbfl_prepass(project_dir: Path, timeout: int = 30) -> str:
    """Simplified SBFL pre-pass: run pytest, parse failing test tracebacks.

    AutoCodeRover §Gap3: Inject ranked suspect locations derived from failing tests
    BEFORE the first patch attempt. Avoids the expensive full Ochiai scoring by
    using traceback frequency as a lightweight proxy for suspiciousness.

    Process:
    1. Run pytest --tb=short with short timeout (non-destructive, read-only)
    2. Parse tracebacks: extract file:line:function triplets
    3. Score by frequency — functions appearing in most failure tracebacks first
    4. Return formatted context block with top-5 suspects

    Falls back to empty string if no pytest, no failures, or timeout.
    Only called for fix tasks with an existing test suite.

    Multi-language (2026-06-19): non-Python projects (Go/Rust/JS/TS detected via
    .claude/orchestrator.json test_cmd or file sniff) route to fault_localize's
    runner-specific SBFL. The Python path below is unchanged.
    """
    runner = detect_test_runner(Path(project_dir))
    if runner and runner["kind"] != "pytest":
        return await run_runner_sbfl(Path(project_dir), runner, timeout=max(timeout, 60))

    # Find pytest
    venv_pytest = project_dir / ".venv" / "bin" / "pytest"
    if venv_pytest.exists():
        pytest_cmd = [str(venv_pytest)]
    else:
        pytest_cmd = ["python", "-m", "pytest"]

    try:
        proc = await asyncio.create_subprocess_exec(
            *pytest_cmd, "--tb=short", "-q", "--no-header",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(project_dir),
            # _TRACE_RE below matches raw `path/file.py:N: in func` frames;
            # pytest colours those, and the escape codes break the match, so
            # SBFL would silently find zero suspects.
            env=color_free_env(),
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return ""

        if proc.returncode == 0:
            return ""  # All tests pass — no suspects needed

        output = out.decode("utf-8", errors="replace")
    except Exception:
        return ""

    # Parse tracebacks: match "  File 'path/file.py', line N, in function_name"
    # and "path/file.py:N: in function_name" (pytest short format)
    _TRACE_RE = re.compile(
        r'(?:File ["\'](?P<fpath1>[^"\']+)["\'], line \d+, in (?P<fn1>\w+))'
        # fpath2 must be a single whitespace-free token: [^:]+ also matched
        # newlines, so adjacent frames captured the preceding code line into the
        # path ("return a / b\nsrc/foo.py"), splitting one function across keys
        # and corrupting the frequency ranking.
        r'|(?:(?P<fpath2>[^\s:][^:\s]*\.py):(?:\d+): in (?P<fn2>\w+))'
    )
    # Count DISTINCT failing tests per function, not raw frame frequency (audit
    # 2026-06-18): split on pytest's per-failure underscore headers so a function
    # deep in one test's recursion no longer outranks one implicated by many
    # separate failures. This is "failing-test coverage" — a real suspiciousness
    # signal, not Ochiai (we have no passing-test coverage to subtract).
    blocks = re.split(r'\n_{5,}.*\n', output)
    if len(blocks) < 2:
        blocks = [output]
    scores: dict[str, int] = {}  # "file::function" → # of distinct failing tests
    for block in blocks:
        seen: set[str] = set()
        for m in _TRACE_RE.finditer(block):
            fpath = m.group("fpath1") or m.group("fpath2") or ""
            fn = m.group("fn1") or m.group("fn2") or ""
            if fpath and fn and fn not in ("<module>", "__init__"):
                # Skip test functions themselves — focus on implementation code
                if not fn.startswith("test_") and not fpath.startswith("test_"):
                    seen.add(f"{fpath}::{fn}")
        for key in seen:
            scores[key] = scores.get(key, 0) + 1

    # Assertion-aware pass: when the traceback had no impl frame (assert failures),
    # infer suspects from the failing test's source (the A1 blind-spot fix).
    traceback_keys = set(scores)
    try:
        for key, cnt in _assertion_suspects(output, project_dir, blocks).items():
            scores[key] = scores.get(key, 0) + cnt
    except Exception:
        pass

    if not scores:
        return ""

    # Rank by distinct-failing-test count; on ties, direct traceback evidence
    # outranks assertion-inferred suspects.
    top = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0] not in traceback_keys, kv[0]))[:5]

    # Count failures for context
    fail_match = re.search(r'(\d+) failed', output)
    fail_count = fail_match.group(1) if fail_match else "some"

    lines = [
        f"## SBFL Pre-pass (AutoCodeRover §Gap3)",
        f"> Found {fail_count} failing test(s). Functions implicated by failing tests (traceback + assertion analysis):",
        "",
        "**Ranked suspect functions** (higher = more suspect):",
    ]
    for loc, count in top:
        parts = loc.split("::")
        fpath_part = parts[0].split("/")[-1] if parts else loc
        fn_part = parts[1] if len(parts) > 1 else ""
        plural = "s" if count != 1 else ""
        lines.append(f"- `{fn_part}` in `{fpath_part}` (implicated by {count} failing test{plural})")
    lines.append("")
    lines.append("> Investigate these functions first — they're the most likely bug locations.")
    return "\n".join(lines)


# ─── Reproduction Test Generation (Agentless §6B) ────────────────────────────

_REPRO_TEST_PROMPT = (
    "Write a minimal Python pytest test that:\n"
    "1. FAILS with the current buggy code (via assertion error or exception)\n"
    "2. Would PASS after the bug is correctly fixed\n"
    "3. Uses only standard library or existing project imports\n"
    "4. Is 5-20 lines — no boilerplate, no docstrings, just the test function\n\n"
    "Bug/Task:\n{description}\n\n"
    "Codebase structure (for import hints):\n{tldr}\n\n"
    "Respond with ONLY Python code — no markdown fences, no explanation.\n"
    "Start with import/from statements, then one def test_...() function."
)


async def _generate_repro_test(
    task_description: str, tldr: str, project_dir: Path,
    claude_dir: Path | None = None, task_id=None,
) -> str:
    """Generate a failing reproduction test for a bug-fix task (Agentless §6B).

    Asks haiku to write a minimal pytest test that fails with current code.
    Runs pytest --collect-only to verify syntax, then runs the test to confirm
    it actually fails (non-zero exit). Returns a formatted context block.

    When claude_dir is given AND the test is confirmed failing pre-fix, the test
    code is persisted to {claude_dir}/repro-test.py so the validation half
    (_run_repro_filter) can re-run it after the fix to prove the bug is resolved.
    Only confirmed-failing repros are persisted — a test that passes on buggy
    code is a bad test and must never gate.

    Falls back to empty string on any error (non-critical path).
    Only valuable for tasks that describe a concrete, testable bug.
    """
    if not task_description or not tldr:
        return ""

    prompt = _REPRO_TEST_PROMPT.format(
        description=task_description[:500],
        tldr=tldr[:2000],
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", prompt,
            "--model", HAIKU_MODEL,
            "--dangerously-skip-permissions",
            "--no-input-prompt",
            *shlex.split(SETTING_SOURCES_NONE),
            *shlex.split(DISALLOWED_TOOLS_JUDGE),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(project_dir),
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=40)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return ""

        test_code = out.decode("utf-8", errors="replace").strip()
        if not test_code or "def test_" not in test_code:
            return ""

        # Strip markdown fences if haiku wrapped anyway
        if test_code.startswith("```"):
            lines = test_code.splitlines()
            test_code = "\n".join(
                l for l in lines if not l.startswith("```")
            ).strip()

        # Sanity-check syntax via py_compile
        import tempfile
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix="clade-repro-", delete=False,
            dir=str(project_dir)
        ) as tmp:
            tmp.write(test_code)
            tmp_path = tmp.name

        try:
            compile_proc = await asyncio.create_subprocess_exec(
                "python", "-m", "py_compile", tmp_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(compile_proc.communicate(), timeout=5)
            except asyncio.TimeoutError:
                compile_proc.kill()
                await compile_proc.communicate()
                return ""
            if compile_proc.returncode != 0:
                return ""  # Bad syntax — discard

            # Optionally run test to verify it actually fails
            # (non-blocking — if it passes or times out, still include as hint)
            run_proc = await asyncio.create_subprocess_exec(
                "python", "-m", "pytest", tmp_path, "-x", "-q", "--tb=no",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=str(project_dir),
            )
            try:
                run_out, _ = await asyncio.wait_for(run_proc.communicate(), timeout=20)
                test_output = run_out.decode("utf-8", errors="replace").strip()
                confirmed_failing = run_proc.returncode != 0
            except asyncio.TimeoutError:
                run_proc.kill()
                await run_proc.communicate()
                confirmed_failing = None
                test_output = "(timed out)"
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        # Persist confirmed-failing repros so the validation half can re-run them
        # post-fix (Agentless §6B). Only confirmed-failing — a repro that passes on
        # buggy code is a bad test and must never gate a commit. Namespaced by
        # task_id: claude_dir is shared across concurrent swarm workers.
        if confirmed_failing and claude_dir is not None and task_id is not None:
            try:
                (claude_dir / f"repro-test-{task_id}.py").write_text(
                    test_code, encoding="utf-8"
                )
            except Exception:
                pass  # persistence is best-effort; context hint still returned

        status_line = (
            "> ✓ Confirmed FAILING with current code — your fix must make this pass."
            if confirmed_failing
            else "> Note: test status unconfirmed — verify manually."
        )
        return (
            f"## Reproduction Test (Agentless §6B)\n"
            f"{status_line}\n"
            f"> Run with: `python -m pytest <test_file> -v`\n\n"
            f"```python\n{test_code}\n```"
        )

    except Exception:
        return ""


# ─── Scout Readiness Scoring ──────────────────────────────────────────────────


async def _score_task(task_id: str, description: str, db_path: Path, claude_dir: Path) -> None:
    """Background: score a task's autonomous-readiness using haiku (0-100)."""
    score_prompt = (
        "Score this task's readiness for autonomous execution by an AI agent (0-100):\n"
        "- 0-49: Needs clarification (vague goal, missing context, ambiguous scope)\n"
        "- 50-79: Acceptable (some uncertainty but workable with reasonable assumptions)\n"
        "- 80-100: Ready (clear, specific, self-contained, no ambiguity)\n\n"
        f"Task description:\n{description[:600]}\n\n"
        'Respond ONLY with a JSON object, no other text: {"score": <integer>, "note": "<max 12 words>"}'
    )
    score_file = claude_dir / f"score-{task_id}.md"
    try:
        score_file.write_text(score_prompt)
        proc = await asyncio.create_subprocess_shell(
            f'claude -p "$(cat {shlex.quote(str(score_file))})" --model {HAIKU_MODEL} --dangerously-skip-permissions {SETTING_SOURCES_NONE} {DISALLOWED_TOOLS_JUDGE}',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
            result = out.decode().strip()
            m = re.search(r'\{[^}]+\}', result)
            if m:
                data = json.loads(m.group())
                score = max(0, min(100, int(data.get("score", 50))))
                note_redaction = redact_runtime(
                    str(data.get("note", ""))[:100],
                    field_path="$.tasks.score_note",
                )
                note = str(note_redaction.value)
                async with aiosqlite.connect(str(db_path)) as db:
                    if note_redaction.metadata.redacted:
                        async with db.execute(
                            "SELECT redaction_metadata FROM tasks WHERE id = ?",
                            (task_id,),
                        ) as cursor:
                            row = await cursor.fetchone()
                        existing = {}
                        if row and row[0]:
                            try:
                                existing = json.loads(row[0])
                            except (TypeError, json.JSONDecodeError):
                                existing = {}
                        metadata = merge_metadata(
                            existing, note_redaction.metadata
                        ).to_dict()
                        await db.execute(
                            "UPDATE tasks SET score = ?, score_note = ?, "
                            "redaction_metadata = ? WHERE id = ?",
                            (score, note, json.dumps(metadata), task_id),
                        )
                    else:
                        await db.execute(
                            "UPDATE tasks SET score = ?, score_note = ? WHERE id = ?",
                            (score, note, task_id),
                        )
                    await db.commit()
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()  # drain stdout/stderr
            out = b""
        except Exception:
            pass
    finally:
        score_file.unlink(missing_ok=True)
