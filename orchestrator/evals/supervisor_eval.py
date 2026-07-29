#!/usr/bin/env python3
"""Supervisor output-parsing eval — offline structural assertions on the LIVE
parser invoked by ``configs/scripts/loop-runner.sh``.

The supervisor LLM returns a JSON array of tasks; loop-runner.sh extracts it
through the sibling ``loop_json.py`` helper. This eval resolves that helper
from the CURRENT loop-runner.sh (so fixtures always exercise the deployed
parser and drift fails loudly), replays recorded outputs through it, then runs
structural checks on the parsed tasks:

  - every task is an object with a non-empty description
  - model is a valid tier (haiku | sonnet | opus)
  - files is a non-empty list
  - tasks in one iteration are independent (no file shared between tasks)

Fixtures cover prose/fences, bracketed preambles, malformed objects, garbage,
and structural task violations. The same helper is used by supervisor and
fix-task paths, eliminating parser drift between shell call sites.

Offline only — no API calls. Exit codes: 0 = all cases pass, 1 = mismatch,
2 = fixtures/parser unusable.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVALS_DIR.parent.parent
LOOP_RUNNER = REPO_ROOT / "configs" / "scripts" / "loop-runner.sh"
PARSER = REPO_ROOT / "configs" / "scripts" / "loop_json.py"
SUPERVISOR_CASES_DIR = EVALS_DIR / "supervisor_cases"

VALID_MODELS = {"haiku", "sonnet", "opus"}
REQUIRED_FIELDS = {"id", "description", "raw_output", "expected_task_count", "expected_issue_kinds"}
KNOWN_ISSUE_KINDS = {
    "not_a_list",
    "task_not_object",
    "missing_description",
    "bad_model",
    "missing_files",
    "file_overlap",
}


# ─── Live parser resolution ───────────────────────────────────────────────────


def resolve_parser(loop_runner: Path = LOOP_RUNNER, parser: Path = PARSER) -> Path:
    """Resolve the parser actually wired into ``node_supervisor``."""
    text = loop_runner.read_text()
    if text.count("_sibling_script loop_json.py") < 2:
        raise RuntimeError(
            "loop-runner.sh must invoke loop_json.py for supervisor and fix tasks"
        )
    if not parser.is_file():
        raise RuntimeError("loop_json.py not found")
    return parser


def parse_supervisor_output(raw_output: str, parser: Path | None = None):
    """Run a recorded supervisor reply through the live parser.

    Mirrors the shell contract: parser failure (nonzero exit / empty stdout)
    yields ``[]``, exactly like ``... 2>/dev/null || echo "[]"``.
    """
    parser_path = parser if parser is not None else resolve_parser()
    try:
        proc = subprocess.run(
            [sys.executable, str(parser_path)],
            input=raw_output,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    out = proc.stdout.strip()
    if proc.returncode != 0 or not out:
        return []
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return []


def live_task_count(parsed) -> int:
    """Task count exactly as node_score_and_write computes it
    (``len(t) if isinstance(t, list) else 0``)."""
    return len(parsed) if isinstance(parsed, list) else 0


# ─── Structural checks ────────────────────────────────────────────────────────


def structural_check(parsed) -> list[str]:
    """Issue kinds found in a parsed supervisor reply (deduplicated, sorted)."""
    if not isinstance(parsed, list):
        return ["not_a_list"]
    issues: set[str] = set()
    seen_files: set[str] = set()
    for task in parsed:
        if not isinstance(task, dict):
            issues.add("task_not_object")
            continue
        if not str(task.get("description", "")).strip():
            issues.add("missing_description")
        if task.get("model") not in VALID_MODELS:
            issues.add("bad_model")
        files = task.get("files")
        if not isinstance(files, list) or not files:
            issues.add("missing_files")
            continue
        for f in files:
            if f in seen_files:
                issues.add("file_overlap")
            seen_files.add(f)
    return sorted(issues)


# ─── Fixture loading ──────────────────────────────────────────────────────────


def validate_case(case: dict, source_name: str = "?") -> list[str]:
    errors: list[str] = []
    if not isinstance(case, dict):
        return [f"{source_name}: case is not a JSON object"]
    cid = case.get("id", source_name)
    missing = REQUIRED_FIELDS - set(case)
    if missing:
        errors.append(f"{cid}: missing required fields: {sorted(missing)}")
    if "raw_output" in case and not isinstance(case["raw_output"], str):
        errors.append(f"{cid}: raw_output must be a string")
    if "expected_task_count" in case and not isinstance(case["expected_task_count"], int):
        errors.append(f"{cid}: expected_task_count must be an int")
    kinds = case.get("expected_issue_kinds")
    if kinds is not None:
        if not isinstance(kinds, list):
            errors.append(f"{cid}: expected_issue_kinds must be a list")
        else:
            unknown = set(kinds) - KNOWN_ISSUE_KINDS
            if unknown:
                errors.append(f"{cid}: unknown issue kinds: {sorted(unknown)}")
    return errors


def load_cases(cases_dir: Path = SUPERVISOR_CASES_DIR) -> tuple[list[dict], list[str]]:
    cases: list[dict] = []
    errors: list[str] = []
    paths = sorted(cases_dir.glob("*.json"))
    if not paths:
        return [], [f"no supervisor cases found in {cases_dir}"]
    for path in paths:
        try:
            case = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            errors.append(f"{path.name}: unreadable JSON ({e})")
            continue
        errors.extend(validate_case(case, path.name))
        if isinstance(case, dict) and case.get("id") and case["id"] != path.stem:
            errors.append(f"{path.name}: id {case['id']!r} != filename stem {path.stem!r}")
        if isinstance(case, dict):
            cases.append(case)
    return cases, errors


# ─── Runner ───────────────────────────────────────────────────────────────────


def run_case(case: dict, parser: Path) -> list[str]:
    """Replay one case; return mismatch descriptions (empty = pass)."""
    mismatches: list[str] = []
    cid = case["id"]
    parsed = parse_supervisor_output(case["raw_output"], parser)
    count = live_task_count(parsed)
    if count != case["expected_task_count"]:
        mismatches.append(
            f"{cid}: task count {count} != expected {case['expected_task_count']}"
        )
    issues = structural_check(parsed)
    expected_issues = sorted(set(case["expected_issue_kinds"]))
    if issues != expected_issues:
        mismatches.append(f"{cid}: issues {issues} != expected {expected_issues}")
    return mismatches


def main(argv: list[str] | None = None) -> int:
    cases, errors = load_cases()
    if errors:
        print(f"SUPERVISOR FIXTURE ERRORS ({len(errors)}):")
        for e in errors:
            print(f"  - {e}")
        return 2
    try:
        parser = resolve_parser()
    except (RuntimeError, OSError) as e:
        print(f"PARSER EXTRACTION FAILED: {e}")
        return 2
    failures: list[str] = []
    for case in cases:
        mismatches = run_case(case, parser)
        status = "ok  " if not mismatches else "MISS"
        print(f"{case['id']:<36} {status}")
        failures.extend(mismatches)
    if failures:
        print(f"\nFAILURES ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"\nall {len(cases)} supervisor cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
