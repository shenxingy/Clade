"""
fault_localize.py — multi-language fault localization primitives (leaf module).

Extracted from worker_tldr.py (2026-06-19, ultracode multi-language completion) so
SBFL is not pytest-only. Holds: the language/test-runner detector, a cross-language
symbol index, per-runner failure parsers (pytest output is parsed in worker_tldr;
here: go test / vitest / jest / node:test), a language-agnostic "test source names
the impl" assertion fallback, and the shared suspect-block formatter.

Leaf: depends only on stdlib (+ os/re/ast/json/asyncio). worker_tldr imports from
here; this module imports nothing from the project (keeps the DAG acyclic).

Imports:
    from fault_localize import (
        _SKIP_DIRS, _SRC_EXTS, _build_symbol_index,
        detect_test_runner, run_runner_sbfl, format_suspect_block,
    )
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

# ─── Shared scan constants (single source of truth; worker_tldr re-imports) ───
_SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", "dist", "build",
    ".venv", "venv", "target", "vendor", ".next", ".nuxt", "coverage",
    ".mypy_cache", ".tox", ".pytest_cache",
}
_SRC_EXTS = (".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".rb",
             ".c", ".cpp", ".cs", ".php")
# A definition site in most languages: def/function/func/fn/fun/sub <name>.
_DEF_GREP_RE = re.compile(r'(?:^|[^.\w])(?:def|function|func|fn|fun|sub)\s+([A-Za-z_]\w+)')
# A call-like identifier (for the language-agnostic test-source fallback).
_CALL_RE = re.compile(r'\b([A-Za-z_]\w{1,})\s*\(')
# Identifiers that are never the impl-under-test (builtins, test/assert helpers).
_NONIMPL = {
    "len", "str", "int", "list", "dict", "set", "tuple", "print", "range", "sorted",
    "enumerate", "zip", "map", "filter", "isinstance", "getattr", "setattr", "super",
    "repr", "type", "abs", "min", "max", "sum", "any", "all", "open", "format", "bool",
    "float", "approx", "raises", "fixture", "mark", "fail", "skip", "warns",
    # JS/TS test + builtins
    "expect", "describe", "it", "test", "beforeEach", "afterEach", "beforeAll",
    "afterAll", "assert", "strictEqual", "deepEqual", "equal", "ok", "toBe",
    "toEqual", "Array", "Object", "Number", "String", "Boolean", "JSON", "Math",
    "require", "console", "Promise", "Error",
}


def _build_symbol_index(project_dir: Path, max_files: int = 1500) -> dict[str, str]:
    """Map a defined symbol name → the first non-test source file that defines it.
    Language-agnostic (def/function/func/fn/fun/sub). Bounded + skip-dir filtered."""
    import os
    index: dict[str, str] = {}
    n = 0
    for dirpath, dirnames, filenames in os.walk(project_dir):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for fname in filenames:
            if not fname.endswith(_SRC_EXTS) or "test" in fname.lower():
                continue
            n += 1
            if n > max_files:
                return index
            p = Path(dirpath) / fname
            try:
                text = p.read_text(errors="replace")
            except OSError:
                continue
            rel = str(p.relative_to(project_dir))
            for m in _DEF_GREP_RE.finditer(text):
                index.setdefault(m.group(1), rel)
    return index


# ─── Test-runner / language detection ────────────────────────────────────────

def detect_test_runner(project_dir: Path) -> dict | None:
    """Detect the project's test runner. Returns {lang, kind, cmd} or None.

    Priority: .claude/orchestrator.json test_cmd (the canonical per-project channel,
    already honored by worker_utils._run_project_tests) → file-presence sniff. NOT a
    global config setting — the orchestrator runs many repos."""
    cmd = None
    oj = project_dir / ".claude" / "orchestrator.json"
    if oj.exists():
        try:
            data = json.loads(oj.read_text())
            cmd = data.get("test_cmd")
            explicit = (data.get("language") or "").lower()
            if explicit in ("go", "rust", "js", "ts", "python"):
                lang = "js" if explicit == "ts" else explicit
                kind = {"go": "gotest", "rust": "cargo", "js": "nodetest",
                        "python": "pytest"}[lang]
                return {"lang": lang, "kind": kind, "cmd": cmd}
        except Exception:
            pass
    if cmd:
        low = cmd.lower()
        if "pytest" in low:
            return {"lang": "python", "kind": "pytest", "cmd": cmd}
        if "cargo test" in low:  # before "go test" — "go test" is a substring of "cargo test"
            return {"lang": "rust", "kind": "cargo", "cmd": cmd}
        if "go test" in low:
            return {"lang": "go", "kind": "gotest", "cmd": cmd}
        if "vitest" in low:
            return {"lang": "js", "kind": "vitest", "cmd": cmd}
        if "jest" in low:
            return {"lang": "js", "kind": "jest", "cmd": cmd}
        if "--test" in low or "node:test" in low:
            return {"lang": "js", "kind": "nodetest", "cmd": cmd}
    # File-presence sniff
    if (project_dir / ".venv" / "bin" / "pytest").exists() or (project_dir / "pyproject.toml").exists():
        return {"lang": "python", "kind": "pytest", "cmd": cmd}
    if (project_dir / "go.mod").exists():
        return {"lang": "go", "kind": "gotest", "cmd": cmd or "go test ./..."}
    if (project_dir / "Cargo.toml").exists():
        return {"lang": "rust", "kind": "cargo", "cmd": cmd or "cargo test"}
    pkg = project_dir / "package.json"
    if pkg.exists():
        try:
            p = json.loads(pkg.read_text())
            deps = {**p.get("dependencies", {}), **p.get("devDependencies", {})}
            if "vitest" in deps:
                return {"lang": "js", "kind": "vitest", "cmd": cmd or "npx vitest run"}
            if "jest" in deps:
                return {"lang": "js", "kind": "jest", "cmd": cmd or "npx jest"}
            ts = p.get("scripts", {}).get("test", "")
            if "--test" in ts:
                return {"lang": "js", "kind": "nodetest", "cmd": cmd or ts}
        except Exception:
            pass
    return None


# ─── Failure parsers (per language) ──────────────────────────────────────────

# Go panic frame pairs: `pkg/path.Func(args)\n\t/abs/file.go:LINE +0xHEX`
_GO_FRAME_RE = re.compile(
    r'^(?P<func>[\w./*()\[\]-]+(?:\.[\w*]+)+)\([^\n]*\)\n'
    r'\s+(?P<file>[\w./@+-]+\.go):(?P<line>\d+)', re.M)
_GO_FAIL_RE = re.compile(r'^--- FAIL: (?P<test>\S+)', re.M)
_GO_ASSERT_RE = re.compile(r'^\s+(?P<file>[\w./-]+_test\.go):(?P<line>\d+):', re.M)

# JS/TS V8 stack frame (vitest ❯ / jest+node `at` / node:test file:// URLs):
_JS_FRAME_RE = re.compile(
    r'^\s*(?:at\s+(?:async\s+)?)?(?:❯\s+)?'
    r'(?:(?P<func>[\w$.<>\[\] ]+?)\s+)?\(?(?:file://)?'
    r'(?P<path>[^\s():]+?\.(?:[cm]?[jt]sx?)):(?P<line>\d+):(?P<col>\d+)\)?\s*$', re.M)


def _is_test_path(path: str) -> bool:
    base = path.rsplit("/", 1)[-1]
    return bool(re.search(r'\.(test|spec)\.[cm]?[jt]sx?$', path)
                or "__tests__/" in path or base.startswith("test")
                or path.endswith("_test.go"))


def _is_noise_path(path: str) -> bool:
    return ("node_modules/" in path or path.startswith("node:")
            or "/src/runtime/" in path or "/src/testing/" in path or "/src/reflect/" in path
            or any(s in path for s in ("vitest/dist", "@vitest", "jest-", "expect/build", "@jest")))


def _func_tail(func: str) -> str:
    """Bare function name from a dotted/qualified frame label."""
    func = func.strip().split("[as ")[-1].rstrip("]").strip() if "[as " in func else func.strip()
    tail = func.rsplit("/", 1)[-1].rsplit(".", 1)[-1]
    return tail.strip("()*").strip()


def _stack_frame_suspects(output: str, lang: str) -> dict[str, int]:
    """Impl suspects from exception/panic stack frames (strong signal)."""
    scores: dict[str, int] = {}
    rx = _GO_FRAME_RE if lang == "go" else _JS_FRAME_RE
    for m in rx.finditer(output):
        path, func = m.group("file" if lang == "go" else "path"), m.group("func") or ""
        if not path or _is_test_path(path) or _is_noise_path(path):
            continue
        fn = _func_tail(func)
        if not fn or fn in _NONIMPL or fn.startswith("test"):
            continue
        key = f"{path.lstrip('./')}::{fn}"
        scores[key] = scores.get(key, 0) + 1
    return scores


def _test_source_suspects(output: str, lang: str, project_dir: Path,
                          index: dict[str, str]) -> dict[str, int]:
    """Assertion fallback: the failing test's SOURCE names the impl under test.
    Extract called identifiers in a window around the failing test line and resolve
    them via the symbol index. Language-agnostic (regex over the test source)."""
    suspects: dict[str, int] = {}
    sites: list[tuple[str, int]] = []  # (test_file, line)
    if lang == "go":
        for m in _GO_ASSERT_RE.finditer(output):
            sites.append((m.group("file"), int(m.group("line"))))
    else:  # js/ts
        for m in _JS_FRAME_RE.finditer(output):
            if _is_test_path(m.group("path")) and not _is_noise_path(m.group("path")):
                sites.append((m.group("path"), int(m.group("line"))))
        for m in re.finditer(r"location:\s*'([^']+\.[cm]?[jt]sx?):(\d+):\d+'", output):
            sites.append((m.group(1), int(m.group(2))))
    for raw_path, fail_line in dict.fromkeys(sites):  # dedup (path, line)
        path = raw_path.replace("file://", "")
        tf = Path(path) if Path(path).is_absolute() else project_dir / path
        try:
            src_lines = tf.read_text(errors="replace").splitlines()
        except OSError:
            continue
        lo, hi = max(0, fail_line - 20), min(len(src_lines), fail_line + 1)
        window = "\n".join(src_lines[lo:hi])
        chosen: set[str] = set()
        for cm in _CALL_RE.finditer(window):
            name = cm.group(1)
            if name in chosen or name in _NONIMPL or name.startswith("test"):
                continue
            chosen.add(name)
            f = index.get(name)
            if f:
                suspects[f"{f}::{name}"] = suspects.get(f"{f}::{name}", 0) + 1
            if len(chosen) >= 4:
                break
    return suspects


def format_suspect_block(scores: dict[str, int], fail_count: str,
                         traceback_keys: set[str] | None = None) -> str:
    """Shared SBFL suspect-block formatter (same shape across languages)."""
    if not scores:
        return ""
    tb = traceback_keys or set()
    top = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0] not in tb, kv[0]))[:5]
    lines = [
        "## SBFL Pre-pass (AutoCodeRover §Gap3)",
        f"> Found {fail_count} failing test(s). Functions implicated by failing tests "
        "(stack frames + assertion analysis):",
        "",
        "**Ranked suspect functions** (higher = more suspect):",
    ]
    for loc, count in top:
        fpath, _, fn = loc.partition("::")
        plural = "s" if count != 1 else ""
        lines.append(f"- `{fn}` in `{fpath.split('/')[-1]}` (implicated by {count} failing test{plural})")
    lines.append("")
    lines.append("> Investigate these functions first — they're the most likely bug locations.")
    return "\n".join(lines)


async def run_runner_sbfl(project_dir: Path, runner: dict, timeout: int = 60) -> str:
    """Run a non-Python project's test runner and build an SBFL suspect block from
    its failure output (Go panics/asserts, JS stack frames + assertion fallback).
    Fail-open: returns '' on no runner cmd, all-pass, timeout, or any error."""
    cmd = runner.get("cmd")
    if not cmd:
        return ""
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            cwd=str(project_dir),
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return ""
        if proc.returncode == 0:
            return ""  # suite green — nothing to localize
        output = out.decode("utf-8", errors="replace")
    except Exception:
        return ""

    lang = runner["lang"]
    scores = _stack_frame_suspects(output, lang)
    traceback_keys = set(scores)
    try:
        index = _build_symbol_index(project_dir)
        for key, cnt in _test_source_suspects(output, lang, project_dir, index).items():
            scores[key] = scores.get(key, 0) + cnt
    except Exception:
        pass
    fail_match = re.search(r'(\d+) (?:failed|fail|FAIL)', output)
    fail_count = fail_match.group(1) if fail_match else "some"
    return format_suspect_block(scores, fail_count, traceback_keys)
