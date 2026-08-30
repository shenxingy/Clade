#!/usr/bin/env python3
"""Assert every GitHub Action is pinned to a commit SHA, not a mutable tag.

`uses: actions/checkout@v4` resolves through a tag the upstream owner can move.
Whoever controls that tag controls what runs in this repository's CI. Pinning
to a 40-character commit SHA makes the reference immutable; the human-readable
version goes in a trailing comment.

This repository had already decided to pin — eight `uses:` lines carried full
SHAs with `# v4.3.1`-style comments. Four did not, and they were the four that
mattered most: both `uses:` in `pr-honeypot-check.yml` and both in
`vouch-gate.yml`. Those two workflows trigger on `pull_request_target`, so they
run with `issues: write` / `pull-requests: write` **and repository secrets**
against pull requests from forks — the one context where a moved tag executes
attacker-influenced code with the repository's own token.

Nothing was enforcing the decision, so the gap was invisible: every workflow
file looked fine on its own, and the inconsistency only showed up when all
`uses:` lines were listed together.

Local actions (`./.github/actions/...`) and reusable workflows in this same
repository are exempt: they are this repository's own code, already covered by
review.

stdlib only, no YAML parser — CI's `syntax-check` job installs no dependencies,
and `uses:` is a line-oriented key that a regex reads correctly. Exit 0 when
every reference is pinned, 1 otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

#: `uses: owner/repo@ref` or `uses: owner/repo/path@ref`, with optional quotes.
USES = re.compile(r"^\s*(?:-\s*)?uses:\s*['\"]?(?P<ref>[^'\"\s#]+)['\"]?")
SHA = re.compile(r"^[0-9a-f]{40}$")

#: Docker actions carry their own supply-chain story (a digest, not a git SHA);
#: none is used here, and one appearing should be a deliberate review, not a
#: silent pass.
DOCKER_PREFIX = "docker://"


def _problems() -> list[str]:
    found: list[str] = []
    for path in sorted(WORKFLOW_DIR.glob("*.yml")) + sorted(WORKFLOW_DIR.glob("*.yaml")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = USES.match(line)
            if not match:
                continue
            ref = match.group("ref")
            if ref.startswith("./"):
                continue  # this repository's own action
            where = f".github/workflows/{path.name}:{number}"
            if ref.startswith(DOCKER_PREFIX):
                found.append(f"{where}: docker action needs a deliberate review — {ref}")
                continue
            if "@" not in ref:
                found.append(f"{where}: no version at all — {ref}")
                continue
            version = ref.rsplit("@", 1)[1]
            if not SHA.match(version):
                found.append(
                    f"{where}: pinned to the mutable tag {version!r} — {ref}\n"
                    f"    Resolve it: gh api repos/{ref.split('@')[0]}/git/ref/tags/{version} "
                    f"-q .object.sha\n"
                    f"    then write `uses: owner/repo@<sha>  # {version}`."
                )
    return found


def main() -> int:
    if not WORKFLOW_DIR.is_dir():
        print(f"no workflow directory at {WORKFLOW_DIR}", file=sys.stderr)
        return 1

    problems = _problems()
    if problems:
        print(
            f"Action pinning check FAILED ({len(problems)} unpinned reference(s)):\n",
            file=sys.stderr,
        )
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print(
            "\nA tag can be moved by whoever owns the action. On a "
            "`pull_request_target`\nworkflow that means attacker-influenced code "
            "running with this repository's\nwrite token.",
            file=sys.stderr,
        )
        return 1

    total = sum(
        1
        for path in list(WORKFLOW_DIR.glob("*.yml")) + list(WORKFLOW_DIR.glob("*.yaml"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if USES.match(line)
    )
    print(f"check-action-pinning: all {total} action reference(s) pinned to a commit SHA ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
