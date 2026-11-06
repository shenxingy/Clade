#!/usr/bin/env python3
"""Identity-bound phase checkpoints for loop-runner.sh."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

SCHEMA_VERSION = 1
PHASES = {"pre-done", "workers-done", "post-done"}
# The --holdout fields are additive within schema 1: a checkpoint written
# before they existed came from a run that had no holdout, so a missing
# holdout_dir reads as "" and still matches a resume without --holdout.


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def _identity(goal: str) -> dict[str, str]:
    checkout_root = str(Path(_git("rev-parse", "--show-toplevel")).resolve())
    goal_path = str(Path(goal).resolve())
    return {
        "checkout_root": checkout_root,
        "goal_file": goal_path,
        "branch": _git("branch", "--show-current"),
        "head_sha": _git("rev-parse", "HEAD"),
    }


def _checkpoint_dir(identity: dict[str, str]) -> Path:
    root_name = Path(identity["checkout_root"]).name
    root_hash = hashlib.sha256(identity["checkout_root"].encode()).hexdigest()[:12]
    goal_hash = hashlib.sha256(identity["goal_file"].encode()).hexdigest()[:16]
    return (
        Path.home()
        / ".claude"
        / "loop-checkpoints"
        / f"{root_name}-{root_hash}"
        / goal_hash
    )


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".checkpoint-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save(args: argparse.Namespace) -> int:
    if args.phase not in PHASES:
        raise ValueError(f"unsupported checkpoint phase: {args.phase}")
    identity = _identity(args.goal)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        **identity,
        "iteration": args.iteration,
        "phase": args.phase,
        "extra": args.extra,
        "consecutive_no_commits": args.no_commits,
        "consecutive_worker_failures": args.worker_failures,
        "iteration_start_commit": args.iteration_start_commit,
        "holdout_dir": args.holdout,
        "holdout_fingerprint": args.holdout_fingerprint,
        "holdout_changed_at": args.holdout_changed_at,
    }
    directory = _checkpoint_dir(identity)
    path = directory / f"iter-{args.iteration:06d}-{args.phase}.json"
    _write_atomic(path, payload)
    print(path)
    return 0


def _holdout_hint(recorded: object, current: str) -> str:
    """Say which --holdout the interrupted run had, so the fix is one flag."""
    if not recorded:
        return (
            "  the interrupted run had no --holdout; resume without it, "
            "or start a fresh run without --resume"
        )
    if not current:
        return (
            f"  the interrupted run had --holdout {recorded}; resume with the "
            "same --holdout, or start a fresh run without --resume"
        )
    return (
        f"  the interrupted run had --holdout {recorded}, not {current}; resume "
        "with the same --holdout, or start a fresh run without --resume"
    )


def recover(args: argparse.Namespace) -> int:
    identity = _identity(args.goal)
    directory = _checkpoint_dir(identity)
    candidates = list(directory.glob("iter-*.json")) if directory.is_dir() else []
    if not candidates:
        print("no checkpoint exists for this checkout and goal", file=sys.stderr)
        return 2

    path = max(candidates, key=lambda item: item.stat().st_mtime_ns)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"checkpoint is unreadable: {path}: {exc}", file=sys.stderr)
        return 2

    expected = {
        "schema_version": SCHEMA_VERSION,
        "checkout_root": identity["checkout_root"],
        "goal_file": identity["goal_file"],
        "branch": identity["branch"],
        "head_sha": identity["head_sha"],
    }
    mismatches = [
        key for key, value in expected.items() if payload.get(key) != value
    ]
    recorded_holdout = payload.get("holdout_dir", "")
    if recorded_holdout != args.holdout:
        mismatches.append("holdout_dir")
    if payload.get("phase") not in PHASES:
        mismatches.append("phase")
    if not isinstance(payload.get("iteration"), int) or payload["iteration"] < 1:
        mismatches.append("iteration")
    if mismatches:
        print(
            f"checkpoint does not match current run ({', '.join(sorted(set(mismatches)))}): {path}",
            file=sys.stderr,
        )
        if "holdout_dir" in mismatches:
            print(_holdout_hint(recorded_holdout, args.holdout), file=sys.stderr)
        return 2

    payload["checkpoint_file"] = str(path)
    print(json.dumps(payload, sort_keys=True))
    return 0


def clear(args: argparse.Namespace) -> int:
    identity = _identity(args.goal)
    directory = _checkpoint_dir(identity)
    if not directory.is_dir():
        return 0
    for path in directory.glob("iter-*.json"):
        path.unlink()
    try:
        directory.rmdir()
        directory.parent.rmdir()
    except OSError:
        pass
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    save_parser = subparsers.add_parser("save")
    save_parser.add_argument("--goal", required=True)
    save_parser.add_argument("--iteration", required=True, type=int)
    save_parser.add_argument("--phase", required=True)
    save_parser.add_argument("--extra", default="")
    save_parser.add_argument("--no-commits", default=0, type=int)
    save_parser.add_argument("--worker-failures", default=0, type=int)
    save_parser.add_argument("--iteration-start-commit", default="")
    # Physical path of the run's --holdout directory; "" = no holdout.
    save_parser.add_argument("--holdout", default="")
    save_parser.add_argument("--holdout-fingerprint", default="")
    save_parser.add_argument("--holdout-changed-at", default="")
    save_parser.set_defaults(func=save)

    recover_parser = subparsers.add_parser("recover")
    recover_parser.add_argument("--goal", required=True)
    recover_parser.add_argument("--holdout", default="")
    recover_parser.set_defaults(func=recover)

    clear_parser = subparsers.add_parser("clear")
    clear_parser.add_argument("--goal", required=True)
    clear_parser.set_defaults(func=clear)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"checkpoint error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
