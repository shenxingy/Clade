#!/usr/bin/env python3
"""Apply coordinator-owned Loop goal completions from a verified task file."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile

GOAL_ITEMS_PREFIX = "goal_items_json:"
UNCHECKED = re.compile(r"^- \[ \] (.+?)(\r?\n)?$")
CHECKED = re.compile(r"^- \[[xX]\] (.+?)(\r?\n)?$")


def _mapped_items(task_file: Path) -> dict[int, str]:
    mapped: dict[int, str] = {}
    for raw_line in task_file.read_text(encoding="utf-8").splitlines():
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
            if line in mapped and mapped[line] != text:
                raise ValueError(f"conflicting goal text for line {line}")
            mapped[line] = text
    return mapped


def apply(goal: Path, task_file: Path) -> int:
    mapped = _mapped_items(task_file)
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
    args = parser.parse_args()
    try:
        return apply(args.goal.resolve(), args.task_file.resolve())
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"goal reconciliation refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
