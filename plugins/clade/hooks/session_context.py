#!/usr/bin/env python3
"""Inject concise, read-only repository context into native Codex sessions."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType


USAGE_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "codex-usage"
    / "scripts"
    / "codex_usage.py"
)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=5, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _load_usage_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("clade_codex_usage", USAGE_SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load Codex usage helper: {USAGE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def _usage_message(cwd: Path) -> str:
    """Return the configured live pace indicator without delaying startup on errors."""
    try:
        usage = _load_usage_module()
        rows = usage.normalize(usage.fetch_rate_limits(timeout=6.0))
        project, branch = usage._project_context(cwd)
        return usage.format_rows(rows, project=project, branch=branch).splitlines()[0]
    except Exception:
        # SessionStart hooks must fail open: usage visibility is optional and a
        # transient app-server failure must never prevent Codex from opening.
        return ""


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    cwd = Path(event.get("cwd") or ".").resolve()

    output: dict[str, object] = {}
    usage_message = _usage_message(cwd)
    if usage_message:
        output["systemMessage"] = f"Usage · {usage_message}"

    if _git(cwd, "rev-parse", "--is-inside-work-tree") == "true":
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
        output["hookSpecificOutput"] = {
            "hookEventName": "SessionStart",
            "additionalContext": "\n\n".join(parts),
        }
    if output:
        json.dump(output, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
