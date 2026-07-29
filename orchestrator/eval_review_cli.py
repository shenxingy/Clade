#!/usr/bin/env python3
"""Review quarantined eval candidates and explicitly promote or reject them."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from eval_review import EVALS_ROOT, promote_candidate, reject_candidate
from task_queue import TaskQueue


async def _run(args: argparse.Namespace) -> dict | list:
    queue = TaskQueue(args.claude_dir)
    if args.command == "list":
        return await queue.list_eval_candidates(
            status=args.status, limit=args.limit
        )
    if args.command == "show":
        candidate = await queue.get_eval_candidate(args.candidate_id)
        if candidate is None:
            raise ValueError(f"unknown eval candidate: {args.candidate_id}")
        return candidate
    if args.command == "reject":
        return await reject_candidate(
            queue,
            args.candidate_id,
            reviewer=args.reviewer,
            reason=args.reason,
        )
    case = json.loads(args.case_file.read_text(encoding="utf-8"))
    return await promote_candidate(
        queue,
        args.candidate_id,
        target=args.target,
        reviewer=args.reviewer,
        reason=args.reason,
        case=case,
        evals_root=args.evals_root,
    )


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--claude-dir",
        type=Path,
        default=Path(".claude"),
        help="project .claude directory containing tasks.db",
    )
    parser.add_argument(
        "--evals-root",
        type=Path,
        default=EVALS_ROOT,
        help="trusted evals directory receiving promoted cases",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list")
    listing.add_argument("--status", default="quarantined")
    listing.add_argument("--limit", type=int, default=100)
    showing = commands.add_parser("show")
    showing.add_argument("candidate_id")
    rejecting = commands.add_parser("reject")
    rejecting.add_argument("candidate_id")
    rejecting.add_argument("--reviewer", required=True)
    rejecting.add_argument("--reason", required=True)
    promoting = commands.add_parser("promote")
    promoting.add_argument("candidate_id")
    promoting.add_argument("--target", choices=("oracle", "resolve"), required=True)
    promoting.add_argument("--reviewer", required=True)
    promoting.add_argument("--reason", required=True)
    promoting.add_argument("--case-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(_run(args))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
