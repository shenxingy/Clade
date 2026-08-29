"""Conventions gate — the prose Code Rules from CLAUDE.md as failing tests.

Clade's own history proves prose rules decay (worker.py crossed 1500 lines,
index.html hit 2945, str(e) leaked into a 500 response in server.py) — so the
rules are enforced here, where a violating change fails CI and a worker's
local pytest run instead of waiting for a human audit.

Covers:
  1. File size: every tracked *.py / *.sh / *.ts / *.tsx source file
     stays <= 1500 lines (Read tool default is 2000 — under 1500 reads in
     one shot).
  2. Import DAG: module-level imports across orchestrator/*.py form a strict
     DAG (lazy imports inside functions are the sanctioned escape hatch and
     are deliberately not counted).
  3. 500-response hygiene: no caught exception text flows into
     HTTPException / JSONResponse bodies with a 5xx status in server.py or
     routes/*.py.
  4. Model-ID single source: dated model snapshots (claude-*-YYYYMMDD) live
     only in config.py (_MODEL_ALIASES / HAIKU_MODEL etc.) — everywhere else
     imports them or has them threaded in (documented leaf modules), so a
     model rotation is a one-line change instead of a repo-wide grep.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR = REPO_ROOT / "orchestrator"

MAX_LINES = 1500

# Path fragments that mark non-first-party / generated trees.
EXCLUDED_PARTS = {".venv", "node_modules", "__pycache__", "dist", "mcp"}

# Files allowed to exceed MAX_LINES — upstream-synced third-party skill
# tooling that Clade mirrors via /equip, not first-party code we refactor.
# This list must SHRINK, never grow: adding a first-party file here defeats
# the gate. Each entry is re-checked below — if a file drops back under the
# limit (or disappears), the test fails until it is removed from this list.
LINE_LIMIT_EXCEPTIONS = {
    "configs/scripts/seo/google_report.py",  # upstream claude-seo sync (2400+ lines)
    "configs/scripts/blog/analyze_blog.py",  # upstream claude-blog sync (1800+ lines)
}

SOURCE_SUFFIXES = {".py", ".sh", ".ts", ".tsx"}


def _tracked_source_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git not available — file-size gate needs git ls-files")
    files = []
    for rel in out.split("\0"):
        if not rel:
            continue
        p = Path(rel)
        if p.suffix not in SOURCE_SUFFIXES:
            continue
        if EXCLUDED_PARTS.intersection(p.parts):
            continue
        if (REPO_ROOT / p).is_file():
            files.append(p)
    return files


# ─── 1. File size ────────────────────────────────────────────────────────────


def test_source_files_stay_under_1500_lines() -> None:
    files = _tracked_source_files()
    assert len(files) > 50, "file scan looks hollow — filter is eating everything"

    violations = []
    for rel in files:
        if str(rel) in LINE_LIMIT_EXCEPTIONS:
            continue
        n_lines = sum(1 for _ in (REPO_ROOT / rel).open("rb"))
        if n_lines > MAX_LINES:
            violations.append(f"{rel}: {n_lines} lines (max {MAX_LINES})")
    assert not violations, (
        "Files exceed the 1500-line rule (CLAUDE.md Code Rules). Split per the "
        "module map, or — ONLY for upstream-synced code — add to "
        f"LINE_LIMIT_EXCEPTIONS with justification:\n" + "\n".join(violations)
    )


def test_line_limit_exceptions_still_needed() -> None:
    """Exception entries must keep earning their place."""
    stale = []
    for rel in sorted(LINE_LIMIT_EXCEPTIONS):
        path = REPO_ROOT / rel
        if not path.is_file():
            stale.append(f"{rel}: file gone — remove from LINE_LIMIT_EXCEPTIONS")
            continue
        n_lines = sum(1 for _ in path.open("rb"))
        if n_lines <= MAX_LINES:
            stale.append(
                f"{rel}: now {n_lines} lines (<= {MAX_LINES}) — remove from "
                "LINE_LIMIT_EXCEPTIONS"
            )
    assert not stale, "\n".join(stale)


# ─── 2. Import DAG ───────────────────────────────────────────────────────────


def _module_level_imports(tree: ast.Module) -> set[str]:
    """Top-level imported module names (incl. inside top-level if/try blocks).

    Imports inside functions/methods are lazy imports — the documented way to
    break potential cycles — so they are intentionally not collected.
    """
    found: set[str] = set()

    def visit(stmts: list[ast.stmt]) -> None:
        for stmt in stmts:
            if isinstance(stmt, ast.Import):
                found.update(alias.name.split(".")[0] for alias in stmt.names)
            elif isinstance(stmt, ast.ImportFrom):
                if stmt.module and stmt.level == 0:
                    found.add(stmt.module.split(".")[0])
            elif isinstance(stmt, ast.If):
                visit(stmt.body)
                visit(stmt.orelse)
            elif isinstance(stmt, ast.Try):
                visit(stmt.body)
                for handler in stmt.handlers:
                    visit(handler.body)
                visit(stmt.orelse)
                visit(stmt.finalbody)

    visit(tree.body)
    return found


def _import_graph() -> dict[str, set[str]]:
    local_modules = {p.stem for p in ORCHESTRATOR.glob("*.py")}
    local_modules |= {"routes", "task_factory"}

    graph: dict[str, set[str]] = {}
    py_files = (
        sorted(ORCHESTRATOR.glob("*.py"))
        + sorted(ORCHESTRATOR.glob("routes/*.py"))
        + sorted(ORCHESTRATOR.glob("task_factory/*.py"))
    )
    for path in py_files:
        if path.parent == ORCHESTRATOR:
            mod = path.stem
        else:
            mod = f"{path.parent.name}.{path.stem}"
        tree = ast.parse(path.read_text(), filename=str(path))
        graph[mod] = {
            name for name in _module_level_imports(tree)
            if name in local_modules and name != path.stem
        }
    return graph


def test_import_graph_is_a_strict_dag() -> None:
    graph = _import_graph()
    assert "worker" in graph and "config" in graph, "import scan looks hollow"

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {}
    cycle: list[str] = []

    def dfs(node: str, path: list[str]) -> bool:
        color[node] = GRAY
        for dep in sorted(graph.get(node, ())):
            state = color.get(dep, WHITE)
            if state == GRAY:
                cycle.extend(path + [dep])
                return True
            if state == WHITE and dfs(dep, path + [dep]):
                return True
        color[node] = BLACK
        return False

    for node in sorted(graph):
        if color.get(node, WHITE) == WHITE and dfs(node, [node]):
            break

    assert not cycle, (
        "Circular module-level import (CLAUDE.md: deps must form a strict DAG; "
        "use a lazy import to break it): " + " -> ".join(cycle)
    )


def test_documented_leaf_modules_import_no_project_code() -> None:
    """CLAUDE.md's module map declares these as leaves (no project imports except
    config, cascade_policy, fault_localize, pytest_report, and worker_utils — all
    stdlib-only constants/primitive modules lower in the DAG that other leaves may
    depend on without becoming non-leaves themselves; worker_review -> worker_utils
    mirrors the pre-existing worker_tldr -> fault_localize precedent, and
    pytest_report is shared by worker_utils, worker_tldr and evals/ precisely so
    they cannot drift on what a passing test looks like; worker_review ->
    judge_diversity pairs the LLM test-integrity criterion with the deterministic
    count that backs it)."""
    leaves = {
        "ideas", "process_manager", "worker_tldr", "worker_review",
        "worker_utils", "worker_hydrate", "condensers", "event_stream",
        "tracing", "error_classifier", "session_tree", "usage_tracker",
        "compression_feedback", "fault_localize", "runtime_redaction",
    }
    graph = _import_graph()
    violations = []
    for leaf in sorted(leaves):
        if leaf not in graph:
            violations.append(f"{leaf}: missing — update CLAUDE.md module map")
            continue
        heavy = graph[leaf] - {
            "config", "cascade_policy", "fault_localize", "worker_utils",
            "runtime_redaction", "pytest_report", "judge_diversity",
        }
        if heavy:
            violations.append(f"{leaf}: imports {sorted(heavy)} at module level")
    assert not violations, (
        "Documented leaf modules grew project imports:\n" + "\n".join(violations)
    )


# ─── 3. 500-response hygiene ─────────────────────────────────────────────────

_RESPONSE_CALLS = {"HTTPException", "JSONResponse"}


def _status_of(call: ast.Call) -> int | None:
    for kw in call.keywords:
        if kw.arg == "status_code" and isinstance(kw.value, ast.Constant):
            if isinstance(kw.value.value, int):
                return kw.value.value
    if call.args and isinstance(call.args[0], ast.Constant):
        if isinstance(call.args[0].value, int):
            return call.args[0].value
    return None


def _references_name(node: ast.AST, name: str) -> bool:
    return any(
        isinstance(sub, ast.Name) and sub.id == name for sub in ast.walk(node)
    )


def _exception_text_in_5xx(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    violations: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler) or not node.name:
            continue
        exc_name = node.name
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            func = sub.func
            func_name = (
                func.id if isinstance(func, ast.Name)
                else func.attr if isinstance(func, ast.Attribute)
                else ""
            )
            if func_name not in _RESPONSE_CALLS:
                continue
            status = _status_of(sub)
            if status is None or status < 500:
                continue
            payload = [a for a in sub.args if not isinstance(a, ast.Constant)]
            payload += [kw.value for kw in sub.keywords if kw.arg != "status_code"]
            if any(_references_name(p, exc_name) for p in payload):
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{sub.lineno}: "
                    f"{func_name} 5xx body references caught exception "
                    f"'{exc_name}'"
                )
    return violations


def test_no_exception_text_in_5xx_responses() -> None:
    files = [ORCHESTRATOR / "server.py"] + sorted(ORCHESTRATOR.glob("routes/*.py"))
    assert files and files[0].is_file()

    violations: list[str] = []
    for path in files:
        violations.extend(_exception_text_in_5xx(path))
    assert not violations, (
        "CLAUDE.md Code Rules: never return error.message in 500 responses "
        "(leaks internals). Use a generic message and log the exception:\n"
        + "\n".join(violations)
    )


# ─── 4. Model-ID single source ───────────────────────────────────────────────

# Dated model snapshot, e.g. claude-haiku-<major>-<minor>-<YYYYMMDD>. Undated
# ids (claude-sonnet-4-6) and aliases (haiku) deliberately do not match.
_DATED_MODEL_ID = re.compile(r"claude-[a-z0-9.-]*-20\d{6}")

# The single source of truth for dated model IDs. This set must not grow:
# new code imports HAIKU_MODEL / SONNET_MODEL / OPUS_MODEL from config (or,
# for documented leaf modules, gets them threaded in by worker.py).
DATED_MODEL_ID_ALLOWED = {"orchestrator/config.py"}


def test_dated_model_ids_live_only_in_config() -> None:
    scanned = [
        rel for rel in _tracked_source_files()
        if (rel.suffix == ".py" and rel.parts[0] == "orchestrator")
        or (
            rel.suffix == ".sh"
            and rel.parts[:2] in {("configs", "scripts"), ("configs", "hooks")}
        )
    ]
    assert len(scanned) > 20, "model-id scan looks hollow — filter is eating everything"

    allowed_hits = 0
    violations: list[str] = []
    for rel in scanned:
        text = (REPO_ROOT / rel).read_text(errors="replace")
        if not _DATED_MODEL_ID.search(text):
            continue
        if str(rel) in DATED_MODEL_ID_ALLOWED:
            allowed_hits += 1
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if _DATED_MODEL_ID.search(line):
                violations.append(f"{rel}:{lineno}: {line.strip()[:100]}")

    assert allowed_hits, (
        "config.py no longer contains a dated model id — _MODEL_ALIASES moved? "
        "Update DATED_MODEL_ID_ALLOWED to the new single source."
    )
    assert not violations, (
        "Hardcoded dated model IDs outside config.py rot silently when models "
        "rotate. Import HAIKU_MODEL/SONNET_MODEL/OPUS_MODEL from config "
        "(leaf modules: thread it in from worker.py instead):\n"
        + "\n".join(violations)
    )


# ─── Model pricing ────────────────────────────────────────────────────────────


def test_estimate_cost_prices_each_model_tier_separately() -> None:
    """Every model was billed at Sonnet's rate until 2026-08-29.

    That single figure is what `run_budget` enforces against and what
    `routing_break_even` divides by for success-per-dollar, so an Opus task
    was understated 1.67x and a Haiku task overstated 3x on the numbers the
    router uses to choose between them.
    """
    from config import _estimate_cost

    mtok = 1_000_000
    # Anthropic first-party rates, USD per MTok (input, output), 2026-08-29.
    for model, want_in, want_out in [
        ("claude-opus-5", 5.0, 25.0),
        ("claude-sonnet-5", 3.0, 15.0),
        ("claude-haiku-4-5", 1.0, 5.0),
        ("claude-fable-5", 10.0, 50.0),
    ]:
        assert _estimate_cost(mtok, 0, model) == want_in, model
        assert _estimate_cost(0, mtok, model) == want_out, model

    # Aliases resolve to their model's rate, not to the default.
    assert _estimate_cost(mtok, 0, "opus") == 5.0
    assert _estimate_cost(mtok, 0, "haiku") == 1.0

    # Dated snapshots share their base model's rate. Referenced through the
    # config constant, since this file must not hardcode a dated id either.
    from config import HAIKU_MODEL

    assert _estimate_cost(mtok, 0, HAIKU_MODEL) == 1.0

    # Unknown gateway ids and the two-argument form both fall back to Sonnet,
    # so nothing silently reprices when a caller has no model to pass.
    assert _estimate_cost(mtok, 0, "some-gateway/mystery-model") == 3.0
    assert _estimate_cost(mtok, 0) == 3.0


def test_model_aliases_point_at_the_current_generation() -> None:
    """A stale alias silently routes every task to a superseded model."""
    from config import _MODEL_ALIASES, ALLOWED_MODEL_IDS

    assert _MODEL_ALIASES["opus"] == "claude-opus-5"
    assert _MODEL_ALIASES["sonnet"] == "claude-sonnet-5"
    # Superseded ids must stay resolvable — task rows and evidence bundles
    # written before an alias moved still reference them.
    for legacy in ("claude-opus-4-6", "claude-sonnet-4-6", "claude-opus-4-5"):
        assert legacy in ALLOWED_MODEL_IDS, legacy
