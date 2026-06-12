#!/usr/bin/env python3
"""Standalone oracle gate — CLI-layer access to the orchestrator's judge.

Strangler extraction (2026-06-12 refactor): the oracle's value is the gate,
not the server. This CLI exposes worker_review._oracle_review (a stdlib-only
leaf module) without a running orchestrator, so /commit, loop-runner, and
hooks can cross-check a diff with a second model. The orchestrator keeps
importing the same module — single source, no fork.

Usage:
  oracle_cli.py --task "fix: handle empty input" --staged
  oracle_cli.py --task-file task.md --range origin/main...HEAD
  git diff | oracle_cli.py --task "..." --diff-file -

Exit codes: 0 approved (or empty diff), 1 rejected, 2 unreviewed (infra
error — a dead judge must read as "unreviewed", never "approved").
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import worker_review
from worker_review import _oracle_review


def _git_diff(project_dir: Path, staged: bool, git_range: str | None) -> str:
    cmd = ["git", "diff"]
    if git_range:
        cmd.append(git_range)
    elif staged:
        cmd.append("--cached")
    out = subprocess.run(
        cmd, cwd=project_dir, capture_output=True, text=True, timeout=30
    )
    if out.returncode != 0:
        raise RuntimeError(f"git diff failed: {out.stderr.strip()[:200]}")
    return out.stdout


def _read_diff(args: argparse.Namespace, project_dir: Path) -> str:
    if args.diff_file == "-":
        return sys.stdin.read()
    if args.diff_file:
        return Path(args.diff_file).read_text()
    return _git_diff(project_dir, staged=args.staged, git_range=args.git_range)


def run(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--task", help="task description text")
    p.add_argument("--task-file", help="file containing the task description")
    p.add_argument(
        "--diff-file",
        help="diff to review; '-' reads stdin; default: git diff in --project-dir",
    )
    p.add_argument("--staged", action="store_true", help="review `git diff --cached`")
    p.add_argument(
        "--range", dest="git_range", help="review `git diff <range>` (e.g. main...HEAD)"
    )
    p.add_argument(
        "--project-dir", default=".", help="project root (verdict state lives in .claude/)"
    )
    p.add_argument("--test-evidence-file", help="pre-run test output to thread into prompts")
    p.add_argument("--model", help="override judge model (default: haiku alias)")
    args = p.parse_args(argv)

    task = args.task or (Path(args.task_file).read_text() if args.task_file else "")
    if not task.strip():
        p.error("--task or --task-file is required")
    if args.model:
        worker_review.HAIKU_MODEL = args.model

    project_dir = Path(args.project_dir).resolve()
    claude_dir = project_dir / ".claude"
    claude_dir.mkdir(exist_ok=True)

    diff_text = _read_diff(args, project_dir)
    if not diff_text.strip():
        print(json.dumps({"verdict": "empty", "reason": "no diff to review"}))
        return 0

    test_evidence = (
        Path(args.test_evidence_file).read_text()[:2000]
        if args.test_evidence_file
        else ""
    )

    approved, reason, infra_error = asyncio.run(
        _oracle_review(task, diff_text, claude_dir, test_evidence=test_evidence)
    )
    verdict = "unreviewed" if infra_error else ("approved" if approved else "rejected")
    print(json.dumps({"verdict": verdict, "reason": reason}))
    return {"approved": 0, "rejected": 1, "unreviewed": 2}[verdict]


if __name__ == "__main__":
    sys.exit(run())
