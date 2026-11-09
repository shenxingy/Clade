#!/usr/bin/env python3
"""Apply coordinator-owned Loop goal completions from a verified task file.

A goal item is checked only when the task bound to it recorded `changed` in the
worker runners' outcomes file (record_task_outcome, run_tasks_common.sh). Exit 0
says a worker did not crash, not that it did anything: a worker that gives up
the Tier-2 way exits 0 having changed nothing, and its item used to be checked
off with every gate green, because there was nothing for the gates to fail on.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile

GOAL_ITEMS_PREFIX = "goal_items_json:"
TASK_MARKER = "===TASK==="
LANDED = "changed"
UNCHECKED = re.compile(r"^- \[ \] (.+?)(\r?\n)?$")
CHECKED = re.compile(r"^- \[[xX]\] (.+?)(\r?\n)?$")


def read_outcomes(path: Path) -> dict[int, str]:
    """`<idx>\t<outcome>` lines; the last line for an index wins (a merge
    conflict is re-run serially and recorded again). A missing file is an
    error, not an empty map: without it no task can be shown to have landed."""
    outcomes: dict[int, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        parts = raw_line.strip().split("\t")
        if len(parts) == 2 and parts[0].isdigit():
            outcomes[int(parts[0])] = parts[1].strip()
    return outcomes


def _mapped_items(task_file: Path) -> dict[int, list[tuple[int, str]]]:
    """Goal items keyed by 1-based task index — the order run-tasks*.sh number
    the ===TASK=== blocks in."""
    by_task: dict[int, list[tuple[int, str]]] = {}
    seen: dict[int, str] = {}
    task_index = 0
    for raw_line in task_file.read_text(encoding="utf-8").splitlines():
        if raw_line.strip() == TASK_MARKER:
            task_index += 1
            continue
        if not raw_line.startswith(GOAL_ITEMS_PREFIX):
            continue
        payload = json.loads(raw_line[len(GOAL_ITEMS_PREFIX) :].strip())
        if not isinstance(payload, list):
            raise ValueError("goal_items_json must contain a list")
        for item in payload:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("line"), int)
                or item["line"] < 1
                or not isinstance(item.get("text"), str)
                or not item["text"].strip()
            ):
                raise ValueError("goal item must have a positive line and text")
            line = item["line"]
            text = item["text"].strip()
            if line in seen and seen[line] != text:
                raise ValueError(f"conflicting goal text for line {line}")
            seen[line] = text
            by_task.setdefault(task_index, []).append((line, text))
    return by_task


def apply(goal: Path, task_file: Path, outcomes_file: Path) -> int:
    outcomes = read_outcomes(outcomes_file)
    mapped: dict[int, str] = {}
    for task_index, items in sorted(_mapped_items(task_file).items()):
        outcome = outcomes.get(task_index, "no outcome recorded")
        if outcome == LANDED:
            mapped.update(items)
            continue
        for line, text in items:
            print(
                f"withheld goal line {line} ({text!r}): task {task_index} "
                + ("changed nothing" if outcome == "unchanged" else outcome),
                file=sys.stderr,
            )
    if not mapped:
        print(0)
        return 0

    lines = goal.read_text(encoding="utf-8").splitlines(keepends=True)
    marked = 0
    for line_number, expected_text in sorted(mapped.items()):
        if line_number > len(lines):
            raise ValueError(f"goal line {line_number} no longer exists")
        current = lines[line_number - 1]
        unchecked = UNCHECKED.match(current)
        checked = CHECKED.match(current)
        match = unchecked or checked
        if match is None or match.group(1).strip() != expected_text:
            raise ValueError(f"goal line {line_number} no longer matches task evidence")
        if unchecked is not None:
            newline = unchecked.group(2) or ""
            lines[line_number - 1] = f"- [x] {unchecked.group(1)}{newline}"
            marked += 1

    if marked:
        fd, temporary = tempfile.mkstemp(prefix=".loop-goal-", dir=goal.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.writelines(lines)
            os.replace(temporary, goal)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    print(marked)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goal", required=True, type=Path)
    parser.add_argument("--task-file", required=True, type=Path)
    parser.add_argument(
        "--outcomes",
        required=True,
        type=Path,
        help="per-task outcomes written by run-tasks*.sh via CLADE_TASK_OUTCOMES",
    )
    args = parser.parse_args()
    try:
        return apply(args.goal.resolve(), args.task_file.resolve(), args.outcomes.resolve())
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"goal reconciliation refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
