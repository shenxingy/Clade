#!/usr/bin/env python3
"""Append Clade's portable hook groups to Codex's hooks.json without reordering it.

With --remove (uninstall.sh) it takes them out again: every handler whose command
starts with the quoted adapter path, then any group or event list that removal
emptied. Nothing else changes, and a file with nothing to remove is not rewritten.
A user handler that sat behind a removed one moves up, and Codex keys hook trust
by position, so each such handler is named for review in /hooks.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Any


WARNING = "WARNING: Codex hooks unchanged"


def shell_quote(value: str) -> str:
    """Quote one path for the login shell Codex uses to run command hooks."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`") + '"'


def load_specs(stream: Any, adapter: str, claude_hooks: Path) -> list[dict[str, Any]]:
    specs = []
    for raw in stream:
        line = raw.rstrip("\n")
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) != 5:
            raise ValueError("invalid declarative hook spec")
        event, matcher, hook, timeout_text, mode = fields
        if not event or not hook or mode not in {"sync", "async"}:
            raise ValueError("invalid declarative hook spec")
        timeout = int(timeout_text)
        if timeout < 1 or Path(hook).name != hook:
            raise ValueError("invalid declarative hook spec")
        command = f"{shell_quote(adapter)} {shell_quote(str(claude_hooks / hook))}"
        handler: dict[str, Any] = {
            "type": "command",
            "command": command,
            "timeout": timeout,
        }
        if mode == "async":
            handler["async"] = True
        specs.append(
            {
                "event": event,
                "matcher": matcher,
                "command": command,
                "group": {"matcher": matcher, "hooks": [handler]},
            }
        )
    if not specs:
        raise ValueError("empty declarative hook list")
    return specs


def validate_document(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ValueError("top level is not an object")
    hooks = document.get("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("hooks is not an object")
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            raise ValueError(f"{event} is not an event list")
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                raise ValueError(f"{event} contains an invalid matcher group")
            matcher = group.get("matcher")
            if matcher is not None and not isinstance(matcher, str):
                raise ValueError(f"{event} contains a non-string matcher")
            for handler in group["hooks"]:
                if not isinstance(handler, dict):
                    raise ValueError(f"{event} contains a non-object handler")
                if "command" in handler and not isinstance(handler["command"], str):
                    raise ValueError(f"{event} contains a non-string command")
    document.setdefault("hooks", {})
    return document


def present(document: dict[str, Any], spec: dict[str, Any]) -> bool:
    for group in document["hooks"].get(spec["event"], []):
        if group.get("matcher") or "":
            if group.get("matcher") != spec["matcher"]:
                continue
        elif spec["matcher"]:
            continue
        if any(handler.get("command") == spec["command"] for handler in group["hooks"]):
            return True
    return False


def wired_count(document: dict[str, Any], adapter: str) -> int:
    prefix = shell_quote(adapter) + " "
    return sum(
        1
        for groups in document["hooks"].values()
        for group in groups
        for handler in group["hooks"]
        if handler.get("command", "").startswith(prefix)
    )


def write_preserving_target(target: Path, document: dict[str, Any]) -> None:
    write_target = target.resolve() if target.is_symlink() else target
    write_target.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = stat.S_IMODE(write_target.stat().st_mode)
    except FileNotFoundError:
        mode = 0o600
    payload = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=".hooks.json.", dir=str(write_target.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, write_target)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def merge(target: Path, adapter: str, claude_hooks: Path, stream: Any) -> str:
    specs = load_specs(stream, adapter, claude_hooks)
    if target.exists() or target.is_symlink():
        try:
            with target.open("r", encoding="utf-8") as handle:
                document = json.load(handle)
        except FileNotFoundError:
            if not target.is_symlink():
                raise
            document = {}
    else:
        document = {}
    document = validate_document(document)

    additions = []
    for spec in specs:
        if not present(document, spec):
            additions.append(spec)
    for spec in additions:
        document["hooks"].setdefault(spec["event"], []).append(spec["group"])

    if additions:
        write_preserving_target(target, document)
    wired = wired_count(document, adapter)
    return (
        f"Codex hooks: {wired} wired, {len(additions)} new; "
        "review new Clade hooks in the Codex TUI with /hooks before trusting them."
    )


def trust_position(event: str, group_index: int, handler_index: int) -> str:
    """The part of Codex's trust-state key after the hooks.json path.

    Codex keys trust as `<path>:<event label>:<group>:<handler>`
    (codex-rs/hooks/src/lib.rs hook_key), and the label is the event in snake case.
    """
    label = re.sub(r"(?<!^)(?=[A-Z])", "_", event).lower()
    return f"{label}:{group_index}:{handler_index}"


def remove(target: Path, adapter: str) -> str:
    if not target.exists():
        return f"Codex hooks: nothing to remove in {target}"
    with target.open("r", encoding="utf-8") as handle:
        document = validate_document(json.load(handle))
    prefix = shell_quote(adapter) + " "
    removed = 0
    moved = []
    for event in list(document["hooks"]):
        kept_groups: list[dict[str, Any]] = []
        event_removed = 0
        for group_index, group in enumerate(document["hooks"][event]):
            handlers = [
                (index, h) for index, h in enumerate(group["hooks"])
                if not h.get("command", "").startswith(prefix)
            ]
            dropped = len(group["hooks"]) - len(handlers)
            event_removed += dropped
            if dropped:
                if not handlers:
                    continue
                group["hooks"] = [handler for _, handler in handlers]
            # A handler behind a removed group or handler takes a new position,
            # and Codex finds its trust by position, not by content.
            for new_index, (old_index, handler) in enumerate(handlers):
                old = trust_position(event, group_index, old_index)
                new = trust_position(event, len(kept_groups), new_index)
                if old != new:
                    moved.append(f"  {old} -> {new}  {handler.get('command', '')}")
            kept_groups.append(group)
        removed += event_removed
        if event_removed and not kept_groups:
            del document["hooks"][event]
        else:
            document["hooks"][event] = kept_groups

    if removed:
        write_preserving_target(target, document)
    report = [f"Codex hooks: {removed} removed from {target}"]
    if moved:
        report.append(
            f"WARNING: {len(moved)} of your Codex hooks moved, and Codex keys hook trust by "
            "position, so each needs review in the Codex TUI with /hooks before it runs again:"
        )
        report.extend(moved)
    return "\n".join(report)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--claude-hooks", type=Path, help="required unless --remove")
    parser.add_argument("--remove", action="store_true", help="take Clade's handlers out instead")
    args = parser.parse_args()
    if not args.remove and args.claude_hooks is None:
        parser.error("--claude-hooks is required unless --remove is given")
    try:
        if args.remove:
            print(remove(args.target, args.adapter))
        else:
            print(merge(args.target, args.adapter, args.claude_hooks, sys.stdin))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"{WARNING}: {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
