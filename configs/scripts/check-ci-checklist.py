#!/usr/bin/env python3
"""Assert CLAUDE.md's pre-commit checklist covers every gate CI enforces.

`CLAUDE.md` tells a contributor to run a numbered list "to ensure CI will
pass". Nothing checked that claim, and it has now drifted twice:

  2026-08-22 (`df802c3`)  the list covered 4 of CI's 7 gates
  2026-08-29              7 of 11 syntax-check gates, 0 of 18 shell suites,
                          and no mention of validate-plugin.yml at all

Both times the fix was to edit prose, and the file's closing instruction — "If
you add a CI step, add it here in the same commit" — was the only thing holding
the invariant. That is a convention, not a control, which is why a third
recurrence was a matter of time.

The check is deliberately coarse: it compares the set of INVOKED ARTEFACTS
(script paths, test files, eval entrypoints, and a few named commands) rather
than command strings, because a checklist entry legitimately differs from its
CI counterpart in flags, working directory, and shell quoting. What must not
differ is *which gates exist*.

Exit 0 when every CI-enforced artefact appears in the checklist, 1 otherwise.
"""

from __future__ import annotations

import os
import re
import shlex
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
CHECKLIST_HEADING = "## CI (GitHub Actions)"

# Workflows that cannot run on a contributor's machine, so the checklist has
# nothing to say about them. Both trigger on `pull_request_target` and act on
# the GitHub API rather than the working tree.
SKIP_WORKFLOWS = {
    "pr-honeypot-check.yml": "runs on the PR body via the GitHub API",
    "vouch-gate.yml": "acts on the PR author via the GitHub API",
}

# Jobs that need credentials a contributor is not expected to have. They print
# SKIP and exit 0 without them, so they are not part of a local pre-commit run.
SKIP_JOBS = {
    "real-api-loop": "key-gated live-API tier (workflow_dispatch/weekly only)",
    "provider-live-anthropic": "key-gated read-only catalog smoke",
    "provider-live-openai": "key-gated read-only catalog smoke",
    "dependency-audit": "weekly/dispatch only — advisories land without a code change",
}

# Artefacts CI invokes, recognised by shape. Each pattern's first group is the
# identity compared against the checklist.
ARTEFACT_PATTERNS = (
    re.compile(r"(configs/scripts/[A-Za-z0-9_.-]+\.(?:py|sh))"),
    re.compile(r"(tests/[A-Za-z0-9_.-]+\.sh)"),
    re.compile(r"(evals/[A-Za-z0-9_.-]+\.py)"),
    re.compile(r"\b(py_compile)\b"),
    re.compile(r"\b(pytest)\b"),
    re.compile(r"(claude plugin validate)"),
    re.compile(r"\b(ruff)\b"),
)

# ARTEFACT_PATTERNS is an ALLOWLIST, and that is this check's own blind spot:
# a CI step invoking a tool no pattern above names is invisible here, so the
# gate reports "covers all N gates" while the new step goes undocumented. It
# happened the day the ruff step landed — `ruff check --config ...` matched
# nothing, and this script stayed green with the checklist missing it. Adding a
# new KIND of gate to CI therefore means adding its pattern here in the same
# commit. Parsing arbitrary shell to do better is not worth it; noticing that
# the list is a list is.


def _job_blocks(text: str) -> dict[str, str]:
    """Split a workflow into {job name: body}. Jobs are two-space keys."""
    starts = [(m.group(1), m.start()) for m in re.finditer(r"^  ([a-z][\w-]*):\s*$", text, re.M)]
    blocks: dict[str, str] = {}
    for i, (name, start) in enumerate(starts):
        end = starts[i + 1][1] if i + 1 < len(starts) else len(text)
        blocks[name] = text[start:end]
    return blocks


def _artefacts(text: str) -> set[str]:
    found: set[str] = set()
    for pattern in ARTEFACT_PATTERNS:
        found.update(m.group(1) for m in pattern.finditer(text))
    return found


def ci_artefacts() -> dict[str, set[str]]:
    """Every artefact CI enforces on push/PR, grouped by "workflow:job"."""
    enforced: dict[str, set[str]] = {}
    for workflow in sorted(WORKFLOW_DIR.glob("*.yml")):
        if workflow.name in SKIP_WORKFLOWS:
            continue
        text = workflow.read_text(encoding="utf-8")
        for job, body in _job_blocks(text).items():
            if job in SKIP_JOBS:
                continue
            found = _artefacts(body)
            if found:
                enforced[f"{workflow.name}:{job}"] = found
    return enforced


def checklist_artefacts() -> set[str]:
    text = CLAUDE_MD.read_text(encoding="utf-8")
    start = text.find(CHECKLIST_HEADING)
    if start == -1:
        print(f"check-ci-checklist: '{CHECKLIST_HEADING}' section missing from CLAUDE.md",
              file=sys.stderr)
        raise SystemExit(1)
    end = text.find("\n## ", start + len(CHECKLIST_HEADING))
    section = text[start:end if end != -1 else len(text)]
    found = _artefacts(section)
    # The checklist loops over suite names rather than spelling out 18 paths:
    #   for t in loop checks skill-routing ...; do bash "tests/test-$t.sh"
    for match in re.finditer(r"for t in ([^;]+); do", section):
        for name in match.group(1).replace("\\", " ").split():
            found.add(f"tests/test-{name}.sh")
    return found


# A documented command that cannot execute is worse than a missing one: it
# reads as covered. `CLAUDE.md` carried
# `configs/scripts/checks.sh shellcheck …` for months — mode 100644, no `bash`
# prefix, so it exited 126 every time — while this script reported the gate
# covered, because coverage compares which artefacts are NAMED, not whether the
# line runs.
INTERPRETERS = {"bash", "sh", "zsh", "python", "python3", "node", "env", "sudo"}


def unrunnable_commands() -> list[str]:
    """Documented lines that invoke a repo file directly without an interpreter."""
    text = CLAUDE_MD.read_text(encoding="utf-8")
    start = text.find(CHECKLIST_HEADING)
    if start == -1:
        return []
    end = text.find("\n## ", start + len(CHECKLIST_HEADING))
    section = text[start:end if end != -1 else len(text)]

    problems: list[str] = []
    for raw in section.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("|"):
            continue
        try:
            first = shlex.split(line)[0]
        except ValueError:
            continue
        if Path(first).name in INTERPRETERS:
            continue
        if not first.startswith(("configs/", "tests/", "orchestrator/", "./")):
            continue
        target = REPO_ROOT / first
        if not target.exists():
            problems.append(f"  {first} — documented but does not exist")
        elif not os.access(target, os.X_OK):
            problems.append(
                f"  {first} — not executable, so this line exits 126; "
                f"prefix it with `bash` or chmod +x"
            )
    return problems


def main() -> int:
    unrunnable = unrunnable_commands()
    if unrunnable:
        print(
            "check-ci-checklist: the CLAUDE.md pre-commit checklist documents "
            "commands that cannot run:",
            file=sys.stderr,
        )
        for line in unrunnable:
            print(line, file=sys.stderr)
        return 1

    enforced = ci_artefacts()
    documented = checklist_artefacts()

    missing: list[tuple[str, str]] = []
    for where, artefacts in sorted(enforced.items()):
        for artefact in sorted(artefacts - documented):
            missing.append((where, artefact))

    if not missing:
        total = len({a for group in enforced.values() for a in group})
        print(
            f"check-ci-checklist: CLAUDE.md covers all {total} CI-enforced gates, "
            "and every documented command is runnable ✓"
        )
        return 0

    print(
        "check-ci-checklist: CI enforces gates the CLAUDE.md pre-commit checklist "
        "does not mention, so a local run can be green against a checklist that "
        "does not cover the build:",
        file=sys.stderr,
    )
    for where, artefact in missing:
        print(f"  {artefact}  (enforced by {where})", file=sys.stderr)
    print(
        f"\nAdd them under '{CHECKLIST_HEADING}' in CLAUDE.md, in the same commit "
        "as the CI change.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
