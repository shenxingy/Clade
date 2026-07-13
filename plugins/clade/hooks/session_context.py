#!/usr/bin/env python3
"""Inject concise, read-only repository context into native Codex sessions."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=5, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    cwd = Path(event.get("cwd") or ".").resolve()
    if _git(cwd, "rev-parse", "--is-inside-work-tree") != "true":
        return 0

    parts: list[str] = ["Clade native Codex context:"]
    branch = _git(cwd, "branch", "--show-current")
    if branch:
        parts.append(f"Branch: {branch}")
    recent = _git(cwd, "log", "-5", "--oneline")
    if recent:
        parts.append(f"Recent commits:\n{recent}")
    status = _git(cwd, "status", "--short")
    if status:
        parts.append(f"Uncommitted changes:\n" + "\n".join(status.splitlines()[:20]))
    if (cwd / ".clade").is_dir():
        handoffs = sorted((cwd / ".clade").glob("handoff-*.md"), reverse=True)
        if handoffs:
            parts.append(f"Latest handoff: {handoffs[0].relative_to(cwd)}")
    guidance = []
    if (cwd / "AGENTS.md").is_file():
        guidance.append("AGENTS.md")
    if (cwd / "CLAUDE.md").is_file():
        guidance.append("CLAUDE.md (legacy fallback)")
    if guidance:
        parts.append("Repository guidance available: " + ", ".join(guidance))

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n\n".join(parts),
        }
    }
    json.dump(output, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
