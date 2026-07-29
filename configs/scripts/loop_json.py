#!/usr/bin/env python3
"""Extract the last valid Loop task array from mixed planner output."""

from __future__ import annotations

import argparse
import json
import sys


def extract_task_array(text: str, *, require_nonempty: bool = False) -> list[dict]:
    """Return the last JSON array whose items have string descriptions."""
    decoder = json.JSONDecoder()
    candidates: list[object] = []
    for start, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        candidates.append(parsed)
    for parsed in reversed(candidates):
        if (
            isinstance(parsed, list)
            and (parsed or not require_nonempty)
            and all(
                isinstance(item, dict)
                and isinstance(item.get("description"), str)
                for item in parsed
            )
        ):
            return parsed
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-nonempty", action="store_true")
    args = parser.parse_args(argv)
    tasks = extract_task_array(
        sys.stdin.read(), require_nonempty=args.require_nonempty
    )
    print(json.dumps(tasks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
