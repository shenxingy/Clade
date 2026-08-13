#!/usr/bin/env python3
"""Fail when an orchestrator module is missing from the CLAUDE.md architecture map.

CLAUDE.md's "Orchestrator Layer" import DAG and Key File Map are how an agent
orients before touching orchestrator/. A module that exists but is absent from
that map is worse than undocumented: the map reads as complete, so the agent
concludes the module does not exist. This gate keeps the map honest by making
"add a module" and "describe it" the same commit.

Usage:
  check-arch-map.py [--root REPO_ROOT] [--doc CLAUDE.md] [--dir orchestrator]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Private/dunder modules and generated trees carry no architectural meaning.
SKIP_NAMES = {"__init__.py", "conftest.py"}
SKIP_DIRS = {"tests", "evals", "task_factory", "__pycache__", ".venv", "web"}


def orchestrator_modules(base: Path) -> list[Path]:
    found = []
    for p in sorted(base.rglob("*.py")):
        if p.name in SKIP_NAMES:
            continue
        if any(seg in SKIP_DIRS for seg in p.relative_to(base).parts[:-1]):
            continue
        found.append(p)
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", help="Repo root (default: cwd)")
    ap.add_argument("--doc", default="CLAUDE.md", help="Architecture doc, relative to --root")
    ap.add_argument("--dir", default="orchestrator", help="Module dir, relative to --root")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    doc_path = root / args.doc
    base = root / args.dir

    if not doc_path.exists():
        print(f"check-arch-map: no {args.doc} at {root} (silent no-op)", file=sys.stderr)
        return 0
    if not base.is_dir():
        print(f"check-arch-map: no {args.dir}/ at {root} (silent no-op)", file=sys.stderr)
        return 0

    doc = doc_path.read_text(encoding="utf-8")
    missing = []
    for mod in orchestrator_modules(base):
        rel = mod.relative_to(base).as_posix()
        # Accept either the bare filename or the subdir-qualified path, since
        # the map writes top-level modules as `worker.py` and nested ones as
        # `routes/tasks.py`.
        if rel not in doc and mod.name not in doc:
            missing.append(rel)

    if missing:
        print(f"check-arch-map: {len(missing)} module(s) missing from {args.doc}:")
        for m in missing:
            print(f"  {args.dir}/{m}")
        print(f"\nAdd each to the {args.doc} import DAG (leaf/mid-tier/root) with a one-line purpose.")
        return 1

    print(f"check-arch-map: all {args.dir}/ modules documented in {args.doc} ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
