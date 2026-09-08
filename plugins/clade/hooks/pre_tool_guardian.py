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


# Kept deliberately in step with configs/hooks/pre-tool-guardian.sh.
# configs/codex-migration.json records the two as a parity pair, and
# tests/test-pre-tool-guardian.sh now feeds one command to both hooks and fails
# when their verdicts differ — which is how the drift below was found. Until
# 2026-09-05 this mirror matched only /, ~ and $HOME, so it allowed a recursive
# delete of /home, /etc, /usr, /var, /sys, /proc and /boot that the shell hook
# blocked; and it split on LINES where the shell splits on statements, so a
# home path merely sharing a line with a benign delete read differently here.
_DANGEROUS_TILDE = r"(?:^|[\s=])~[A-Za-z0-9._-]*(?:/|\s|$)"
_DANGEROUS_NAMED = (
    r"(?:" + _DANGEROUS_TILDE + r"|\$\{?HOME\}?"
    r"|(?:/home|/etc|/usr|/var|/sys|/proc|/boot)\b)"
)
_DANGEROUS_ROOT = r"(?:^|\s)/(?:\s|$|\*)"

# Names the shell always provides, so requiring them proves nothing. HOME is
# on this list and is also caught by _DANGEROUS_NAMED; that block wins.
_SHELL_OWNED = frozenset(
    {"HOME", "PWD", "OLDPWD", "TMPDIR", "XDG_RUNTIME_DIR", "CLAUDE_PROJECT_DIR"}
)


def _statements(command: str) -> list[str]:
    """Split the way the shell hook does — on ; | & — not on newlines.

    Per-line matching was too coarse in both directions; the reasoning is
    recorded at length in pre-tool-guardian.sh. Matching per statement means
    every condition has to be met by the same statement.
    """
    return re.split(r"[;|&\n]", command)


def _recursive_force(statement: str) -> bool:
    """Read -r and -f from the OPTION tokens of an rm statement, never operands.

    This used to test the whole statement for ``-[a-zA-Z]*r`` and
    ``-[a-zA-Z]*f``, so any hyphen inside a FILENAME supplied the flags.
    Reproduced 2026-09-07: a plain ``rm -f`` on a path under /home whose
    basename contains a hyphen, letters and an r was blocked as a catastrophic
    recursive delete with no -r in the command at all.

    It is the over-blocking mirror of the under-blocking fixed on 2026-09-05,
    and one root cause serves both: matching command TEXT instead of
    classifying tokens. A token supplies flags only when it starts with ``-``,
    and after a ``--`` nothing does. GNU rm permutes, so an option may follow
    an operand — what an operand may never do is BE one.
    """
    recursive = force = False
    end_of_options = False
    after = re.sub(r"^.*\brm\b", "", statement, count=1)
    for token in after.split():
        if token == "--":
            end_of_options = True
            continue
        if end_of_options or not token.startswith("-") or token == "-":
            continue
        if token.startswith("--"):
            name = token.split("=", 1)[0]
            if name == "--recursive":
                recursive = True
            elif name == "--force":
                force = True
            continue
        if "r" in token:
            recursive = True
        if "f" in token:
            force = True
    return recursive and force


def _delete_targets(statement: str) -> list[str]:
    after = re.sub(r"^.*\brm\b", "", statement, count=1)
    return [token for token in after.split() if not token.startswith("-")]


def _unresolved_delete(command: str) -> tuple[str, str] | None:
    """A recursive delete whose target this guardian cannot resolve.

    Returns ("refuse", why) when nothing can be made safe — a command
    substitution or a bare glob is decided at run time and offers no name to
    require — or ("rewrite", name) when there is a name to make required.

    The danger is the shell lifecycle rather than the text: each Bash tool call
    is a fresh shell, so a variable assigned in an earlier call is unset in this
    one and the target expands to the filesystem root.
    """
    # A delete written inside a single-quoted string is text, not a command,
    # and rewriting it would corrupt the string it sits in.
    head = re.split(r"\brm\b", command, maxsplit=1)[0]
    if head.count("'") % 2 == 1:
        return None

    for statement in _statements(command):
        if not _recursive_force(statement):
            continue
        for token in _delete_targets(statement):
            bare = token.replace('"', "")
            if "$(" in bare or "`" in bare:
                return ("refuse", "a command substitution decides the target at run time")
            if re.fullmatch(r"\.?/?\*+|\.|\./", bare):
                return (
                    "refuse",
                    "a bare glob resolves against whatever the working "
                    "directory happens to be",
                )
            match = re.match(r"^\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", bare)
            if not match:
                continue
            name = match.group(1)
            if name in _SHELL_OWNED:
                continue
            # Assigned in this same command, so this shell will have it.
            if re.search(rf"(?:^|[\s;&|(])(?:export\s+)?{re.escape(name)}=", command):
                continue
            return ("rewrite", name)
    return None


def evaluate(command: str) -> dict | None:
    lower = command.lower()
    dev_mode = (Path.home() / ".clade" / ".dev-mode").exists()
    if not dev_mode:
        for pattern in MIGRATIONS:
            if pattern in lower:
                return _deny(
                    f"Database migration detected ({pattern}). Review and run it manually."
                )

    for statement in _statements(command):
        if not _recursive_force(statement):
            continue
        if re.search(_DANGEROUS_NAMED, statement) or re.search(_DANGEROUS_ROOT, statement):
            return _deny(f"Catastrophic recursive deletion blocked: {statement.strip()}")

    unresolved = _unresolved_delete(command)
    if unresolved is not None:
        kind, detail = unresolved
        if kind == "refuse":
            return _deny(
                f"Recursive delete refused: {detail}. Name the directory explicitly, "
                f"or run it manually after checking what it expands to. Command: {command}"
            )
        guard = f"pre_tool_guardian: refusing a recursive delete on unset {detail}"
        safer = command.replace("${" + detail + "}", "${" + detail + ":?" + guard + "}")
        safer = re.sub(
            r"\$" + re.escape(detail) + r"\b",
            "${" + detail + ":?" + guard + "}",
            safer,
        )
        return _rewrite(safer)

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
