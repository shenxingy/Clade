#!/usr/bin/env python3
"""
check-layers.py — keep docs/layers.json honest about what actually runs.

An audit of this repository spent most of its effort on the orchestrator, a
layer the owner had switched off months earlier. Nothing in the tree said so:
the code compiled, CI was green, and the module map described it as if it were
in service. The finding is not "delete it" — it may be rebuilt — but "say so
where a reader and a skill will both see it".

This checks the declaration rather than the layers:

  * every declared status is one the file itself defines
  * every declared path exists (a marker pointing at nothing is worse than none)
  * every source directory in the tree is covered by exactly one layer
  * a dormant or generated layer states a reason and a date

Stdlib only — the syntax-check CI job installs no dependencies.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LAYERS = REPO / "docs" / "layers.json"

# Top-level directories that are NOT surfaces: docs, tests, CI config, build
# output, and anything git ignores. Everything else at the top level holds
# source and must be claimed by a layer.
#
# This was a hard-coded allowlist of five names, which made the gate's claim
# false: TODO.md said "an unclaimed source directory fails it", and a NEW
# top-level directory — the case that actually happens — was invisible because
# it was not one of the five. The list is derived from the tree now, so adding
# a surface and forgetting to declare it is what fails.
NOT_SURFACES = frozenset({
    # "logs" is runtime output and gitignored; the rest are docs/CI/build.
    "docs", "tests", "evals", "examples", "scripts", "logs",
    ".github", ".git", ".claude", ".claude-plugin", ".agents", ".venv",
    "node_modules", "__pycache__", "dist", "build",
})

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def main() -> int:
    if not LAYERS.is_file():
        print(f"missing {LAYERS.relative_to(REPO)}")
        return 1
    try:
        data = json.loads(LAYERS.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(f"docs/layers.json is not valid JSON: {exc}")
        return 1

    problems: list[str] = []
    statuses = data.get("statuses") or {}
    layers = data.get("layers") or []

    if not statuses:
        problems.append("no statuses defined — the vocabulary must be in the file itself")
    if not layers:
        problems.append("no layers declared")

    claimed: dict[str, str] = {}
    for layer in layers:
        name = layer.get("name", "<unnamed>")
        status = layer.get("status")
        if status not in statuses:
            problems.append(f"{name}: status {status!r} is not one of {sorted(statuses)}")
        paths = layer.get("paths") or []
        if not paths:
            problems.append(f"{name}: declares no paths")
        for raw in paths:
            path = REPO / raw
            if not path.exists():
                problems.append(f"{name}: declared path does not exist: {raw}")
                continue
            previous = claimed.get(raw)
            if previous:
                problems.append(f"path {raw} is claimed by both {previous} and {name}")
            claimed[raw] = name
        if status in ("dormant", "generated"):
            if not (layer.get("reason") or "").strip():
                problems.append(f"{name}: {status} without a reason")
            if not _DATE.match(str(layer.get("since", ""))):
                problems.append(f"{name}: {status} without a YYYY-MM-DD 'since'")

    # Coverage: every top-level source directory reaches a declared path.
    # Derived from the tree, not from a list — a directory added tomorrow is
    # checked without anyone remembering to add its name here.
    for base in sorted(REPO.iterdir()):
        if not base.is_dir() or base.name in NOT_SURFACES or base.name.startswith("."):
            continue
        root = base.name
        covered = any(raw == root or raw.startswith(f"{root}/") for raw in claimed)
        if not covered:
            problems.append(
                f"source directory {root}/ is not claimed by any layer in docs/layers.json"
            )

    # configs/ has sub-surfaces; each immediate child holding source must be claimed.
    configs = REPO / "configs"
    if configs.is_dir():
        for child in sorted(configs.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            rel = f"configs/{child.name}"
            if rel not in claimed and "configs" not in claimed:
                problems.append(f"{rel} is not claimed by any layer")

    if problems:
        print("check-layers: docs/layers.json does not describe the tree —")
        for line in problems:
            print(f"  {line}")
        return 1

    summary = ", ".join(
        f"{layer['name']}={layer['status']}" for layer in layers
    )
    print(f"check-layers: {len(layers)} layers declared and consistent — {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
