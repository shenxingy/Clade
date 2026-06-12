#!/usr/bin/env python3
"""Supervisor output-parsing eval — offline structural assertions on the LIVE
``node_supervisor`` parser embedded in ``configs/scripts/loop-runner.sh``.

The supervisor LLM returns a JSON array of tasks; loop-runner.sh extracts it
with an embedded ``python3 -c`` snippet. This eval pulls that snippet out of
the CURRENT loop-runner.sh (so the fixtures always exercise the deployed
parser, and drift fails loudly) and replays recorded supervisor outputs
through it, then runs structural checks on the parsed tasks:

  - every task is an object with a non-empty description
  - model is a valid tier (haiku | sonnet | opus)
  - files is a non-empty list
  - tasks in one iteration are independent (no file shared between tasks)

Two fixtures intentionally encode KNOWN parser weaknesses (single-object
replies leak their ``files`` array as a bogus task; brackets in prose break
array extraction). If you improve the parser, those fixtures must be updated
— that is the point: parser behavior changes become visible diffs.

Fidelity note: the snippet is executed via ``python3 -c`` exactly as the
shell does. The snippet contains no ``$``/backtick/escape sequences that
bash double-quote processing would rewrite, so raw extraction is equivalent
(asserted by the pytest round-trip in tests/test_evals.py).

Offline only — no API calls. Exit codes: 0 = all cases pass, 1 = mismatch,
2 = fixtures/parser unusable.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVALS_DIR.parent.parent
LOOP_RUNNER = REPO_ROOT / "configs" / "scripts" / "loop-runner.sh"
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


# ─── Live parser extraction ───────────────────────────────────────────────────


def extract_parser_snippet(loop_runner: Path = LOOP_RUNNER) -> str:
    """Pull the embedded JSON-extraction python out of node_supervisor().

    Raises RuntimeError when the snippet cannot be located — that means
    loop-runner.sh was restructured and this eval must be updated, which is a
    desired loud failure (silently testing a stale copy would be worse).
    """
    text = loop_runner.read_text()
    fn = re.search(r"node_supervisor\(\)\s*\{.*?\n\}", text, re.DOTALL)
    if not fn:
        raise RuntimeError("node_supervisor() not found in loop-runner.sh")
    snippet = re.search(r'python3 -c "\n(.*?)\n" 2>/dev/null', fn.group(), re.DOTALL)
    if not snippet:
        raise RuntimeError("embedded python3 -c parser not found in node_supervisor()")
    code = snippet.group(1)
    if "json.loads" not in code:
        raise RuntimeError("extracted snippet does not look like the JSON parser")
    return code


def parse_supervisor_output(raw_output: str, snippet: str | None = None):
    """Run a recorded supervisor reply through the live parser snippet.

    Mirrors the shell contract: parser failure (nonzero exit / empty stdout)
    yields ``[]``, exactly like ``... 2>/dev/null || echo "[]"``.
    """
    code = snippet if snippet is not None else extract_parser_snippet()
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
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


def run_case(case: dict, snippet: str) -> list[str]:
    """Replay one case; return mismatch descriptions (empty = pass)."""
    mismatches: list[str] = []
    cid = case["id"]
    parsed = parse_supervisor_output(case["raw_output"], snippet)
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
        snippet = extract_parser_snippet()
    except (RuntimeError, OSError) as e:
        print(f"PARSER EXTRACTION FAILED: {e}")
        return 2
    failures: list[str] = []
    for case in cases:
        mismatches = run_case(case, snippet)
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
