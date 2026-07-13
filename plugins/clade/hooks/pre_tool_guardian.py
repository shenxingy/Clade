#!/usr/bin/env python3
"""Codex-native destructive-command guard for Clade."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


MIGRATIONS = (
    "db:push", "db:migrate", "prisma migrate", "drizzle-kit push",
    "alembic upgrade", "alembic downgrade", "rake db:migrate",
    "rake db:rollback", "knex migrate:latest", "knex migrate:rollback",
    "sequelize db:migrate", "flyway migrate", "liquibase update",
)


def _deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _rewrite(command: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": {"command": command},
        }
    }


def evaluate(command: str) -> dict | None:
    lower = command.lower()
    dev_mode = (Path.home() / ".clade" / ".dev-mode").exists()
    if not dev_mode:
        for pattern in MIGRATIONS:
            if pattern in lower:
                return _deny(
                    f"Database migration detected ({pattern}). Review and run it manually."
                )

    rm_lines = [line for line in command.splitlines() if re.search(r"\brm\b", line)]
    for line in rm_lines:
        recursive = re.search(r"\brm\b[^\n]*(?:-[a-zA-Z]*r|--recursive\b)", line)
        force = re.search(r"\brm\b[^\n]*(?:-[a-zA-Z]*f|--force\b)", line)
        dangerous = re.search(
            r'''(?:^|\s)["']?(?:/|~|\$HOME|\$\{HOME\})(?:\s|$|/|\*|["'])''',
            line,
        )
        if recursive and force and dangerous:
            return _deny(f"Catastrophic recursive deletion blocked: {line.strip()}")

    is_push = bool(re.search(r"\bgit\s+push\b", command))
    has_force = bool(
        re.search(r"--force(?![-\w])|(?<!\S)-f(?!\S)", command)
    )
    has_force_with_lease = "--force-with-lease" in command
    is_force_push = is_push and (has_force or has_force_with_lease)
    if is_force_push and re.search(r"\b(?:main|master)\b", command):
        return _deny("Force-pushing main/master is blocked because it destroys shared history.")
    if is_push and has_force:
        safer = re.sub(r"--force(?![-\w])", "--force-with-lease", command)
        safer = re.sub(r"(?<!\S)-f(?!\S)", "--force-with-lease", safer)
        return _rewrite(safer)

    if re.search(r"\bDROP\s+(?:DATABASE|TABLE|SCHEMA)\b", command, re.IGNORECASE):
        return _deny("Irreversible SQL DROP operation blocked; review and run it manually.")
    return None


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    if event.get("tool_name") != "Bash":
        return 0
    command = (event.get("tool_input") or {}).get("command") or ""
    decision = evaluate(command)
    if decision:
        json.dump(decision, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
