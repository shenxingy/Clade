#!/usr/bin/env python3
"""Loop attempt ledger: what each task tried, whether it landed, and why not.

The supervisor used to see only commit counts per iteration. A task that failed
or changed nothing left no trace it could read, so the next iteration planned
the same task again, the same way, until a stuck detector or --max-iter ended
the run. ScientistTwo (arXiv:2609.19644, §3.2-3.3) does two things this loop
lacked:

  * it evolves the next attempt from execution traces, failures included, and
  * it gives an idea a bounded number of engineering rounds (one attempt plus
    two refinements in its configuration), then prunes it.

`record` appends one JSON line per task after an iteration's gates. `context`
renders the attempts that did not land, with the worker's own last message, for
the supervisor's prompt. `filter` drops tasks bound to a goal item that has used
its attempts. The loop then parks that item in .claude/skipped.md for a human
instead of spending more iterations on it.

Stdlib only: loop-runner.sh runs it wherever the loop runs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import time
from typing import Any

TASK_MARKER = "===TASK==="
GOAL_ITEMS_PREFIX = "goal_items_json:"
CHECKED = re.compile(r"^- \[[xX]\] (.+?)\s*$")
UNCHECKED = re.compile(r"^- \[ \] (.+?)\s*$")
TEXT_LIMIT = 300
DEFAULT_MAX_ATTEMPTS = 3


# ─── Inputs ───────────────────────────────────────────────────────────


def _clip(text: str, limit: int = TEXT_LIMIT) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def goal_state(goal: Path) -> tuple[set[str], set[str]]:
    """(checked texts, unchecked texts) of the goal file's checkbox items."""
    checked: set[str] = set()
    unchecked: set[str] = set()
    for line in goal.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if match := CHECKED.match(stripped):
            checked.add(match.group(1).strip())
        elif match := UNCHECKED.match(stripped):
            unchecked.add(match.group(1).strip())
    return checked, unchecked


def parse_tasks(task_file: Path) -> dict[int, dict[str, Any]]:
    """1-based task index -> {description, goal_items}, in run-tasks*.sh order."""
    tasks: dict[int, dict[str, Any]] = {}
    index = 0
    in_body = False
    for raw in task_file.read_text(encoding="utf-8").splitlines():
        if raw.strip() == TASK_MARKER:
            index += 1
            tasks[index] = {"description": "", "goal_items": []}
            in_body = False
            continue
        if index == 0:
            continue
        task = tasks[index]
        if raw.startswith(GOAL_ITEMS_PREFIX):
            try:
                items = json.loads(raw[len(GOAL_ITEMS_PREFIX):].strip())
            except json.JSONDecodeError:
                items = []
            task["goal_items"] = [
                item["text"].strip() for item in items
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            ]
        elif raw.strip() == "---" and not in_body:
            in_body = True
        elif in_body and not task["description"] and raw.strip():
            task["description"] = _clip(raw)
    return tasks


def read_outcomes(path: Path) -> dict[int, tuple[str, str]]:
    """idx -> (outcome, log path); the last line for an index wins."""
    outcomes: dict[int, tuple[str, str]] = {}
    if not path.is_file():
        return outcomes
    for raw in path.read_text(encoding="utf-8").splitlines():
        parts = raw.strip().split("\t")
        if len(parts) >= 2 and parts[0].isdigit():
            outcomes[int(parts[0])] = (parts[1].strip(), parts[2].strip() if len(parts) > 2 else "")
    return outcomes


def worker_said(log_path: str) -> str:
    """The worker's final message: the last stream-json `result`, else the last
    line that is not a heartbeat. Empty when there is no readable log."""
    if not log_path:
        return ""
    try:
        lines = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    fallback = ""
    for raw in reversed(lines):
        line = raw.strip()
        if not line or line.startswith("[heartbeat"):
            continue
        if line.startswith("{"):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                event = None
            if isinstance(event, dict):
                if event.get("type") == "result" and isinstance(event.get("result"), str):
                    return _clip(event["result"])
                continue
        if not fallback:
            fallback = _clip(line)
    return fallback


def read_ledger(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not path.is_file():
        return entries
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


# ─── Derived state ────────────────────────────────────────────────────


def misses_by_item(entries: list[dict[str, Any]], open_items: set[str]) -> dict[str, list[dict[str, Any]]]:
    """Attempts that did not land, per goal item that is still open."""
    misses: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        if entry.get("landed"):
            continue
        for item in entry.get("goal_items") or []:
            if item in open_items:
                misses.setdefault(item, []).append(entry)
    return misses


def parked_items(ledger: Path, goal: Path, max_attempts: int) -> dict[str, int]:
    _, open_items = goal_state(goal)
    misses = misses_by_item(read_ledger(ledger), open_items)
    return {item: len(tries) for item, tries in misses.items() if len(tries) >= max_attempts}


def _reason(outcome: str, gates: str) -> str:
    if outcome == "failed":
        return "worker failed"
    if outcome == "unchanged":
        return "worker changed nothing"
    if outcome == "changed":
        return f"changed files, but {gates or 'an iteration gate did not pass'}"
    return "no outcome recorded"


# ─── Commands ─────────────────────────────────────────────────────────


def cmd_record(args: argparse.Namespace) -> int:
    checked, open_items = goal_state(args.goal)
    tasks = parse_tasks(args.task_file)
    outcomes = read_outcomes(args.outcomes)
    before = misses_by_item(read_ledger(args.ledger), open_items)
    new_entries: list[dict[str, Any]] = []
    for index, task in sorted(tasks.items()):
        outcome, log_path = outcomes.get(index, ("missing", ""))
        items: list[str] = task["goal_items"]
        landed = outcome == "changed" and all(item in checked for item in items)
        entry: dict[str, Any] = {
            "iteration": args.iteration,
            "task": index,
            "description": task["description"],
            "goal_items": items,
            "outcome": outcome,
            "landed": landed,
        }
        if not landed:
            entry["reason"] = _reason(outcome, args.gates)
            said = worker_said(log_path)
            if said:
                entry["worker_said"] = said
        new_entries.append(entry)
    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    with args.ledger.open("a", encoding="utf-8") as stream:
        for entry in new_entries:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")

    after = misses_by_item(read_ledger(args.ledger), open_items)
    newly_parked = [
        item for item, tries in after.items()
        if len(tries) >= args.max_attempts > len(before.get(item, []))
    ]
    if newly_parked and args.skipped:
        stamp = time.strftime("%Y-%m-%d %H:%M")
        with args.skipped.open("a", encoding="utf-8") as stream:
            for item in newly_parked:
                last = after[item][-1]
                stream.write(
                    f"\n## [{stamp}] Skipped: goal item \"{item}\"\n"
                    f"Reason: {len(after[item])} loop attempts did not land "
                    f"(last: {last.get('reason', '?')}"
                    + (f"; worker said: {last['worker_said']}" if last.get("worker_said") else "")
                    + f") / Attempted: {last.get('description', '?')}\n"
                )
    for item in newly_parked:
        print(f"parked goal item after {args.max_attempts} attempts: {item}", file=sys.stderr)
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    _, open_items = goal_state(args.goal)
    misses = misses_by_item(read_ledger(args.ledger), open_items)
    if not misses:
        return 0
    print("## Prior attempts that did not land")
    print(
        "These open goal items were attempted and did not land. Do not re-plan the "
        "same approach: use the recorded reason to change it, or plan other work. "
        f"After {args.max_attempts} attempts an item is parked: the loop drops any "
        "task bound to it and lists it in .claude/skipped.md for a human."
    )
    print()
    for item, tries in sorted(misses.items(), key=lambda pair: -len(pair[1])):
        label = "PARKED" if len(tries) >= args.max_attempts else f"{len(tries)} of {args.max_attempts} attempts used"
        print(f"- \"{item}\" — {label}")
        for entry in tries[-args.max_attempts:]:
            said = f"; worker said: \"{entry['worker_said']}\"" if entry.get("worker_said") else ""
            print(f"  - iter {entry.get('iteration')}: {entry.get('description', '')} → {entry.get('reason', '')}{said}")
    print()
    return 0


def cmd_filter(args: argparse.Namespace) -> int:
    raw = sys.stdin.read()
    try:
        tasks = json.loads(raw)
    except json.JSONDecodeError:
        sys.stdout.write(raw)
        return 0
    if not isinstance(tasks, list):
        sys.stdout.write(raw)
        return 0
    parked = parked_items(args.ledger, args.goal, args.max_attempts)
    kept = []
    for task in tasks:
        items = task.get("goal_items") if isinstance(task, dict) else None
        bound = [
            item["text"].strip() for item in (items if isinstance(items, list) else [])
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ]
        hit = next((item for item in bound if item in parked), None)
        if hit is not None:
            description = _clip(str(task.get("description", "")), 120)
            print(f"dropped task bound to parked goal item \"{hit}\" ({parked[hit]} attempts): {description}", file=sys.stderr)
            continue
        kept.append(task)
    print(json.dumps(kept))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("record", "context", "filter"):
        command = sub.add_parser(name)
        command.add_argument("--ledger", required=True, type=Path)
        command.add_argument("--goal", required=True, type=Path)
        command.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
        if name == "record":
            command.add_argument("--task-file", required=True, type=Path)
            command.add_argument("--outcomes", required=True, type=Path)
            command.add_argument("--iteration", required=True, type=int)
            command.add_argument("--gates", default="", help="which iteration gates failed, if any")
            command.add_argument("--skipped", type=Path, help="Tier-2 skip log to park items in")
    args = parser.parse_args()
    if args.max_attempts < 1:
        parser.error("--max-attempts must be at least 1")
    try:
        return {"record": cmd_record, "context": cmd_context, "filter": cmd_filter}[args.command](args)
    except OSError as exc:
        print(f"loop_attempts: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
