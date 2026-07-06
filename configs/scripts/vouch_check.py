#!/usr/bin/env python3
"""vouch_check.py — Round-4 gap (Mitchell Hashimoto): decide whether a GitHub
issue/PR author is trusted (existing collaborator or explicitly vouched for
in TRUSTED_CONTRIBUTORS.txt). Used by .github/workflows/vouch-gate.yml.

Extracted as a standalone, testable script rather than leaving the decision
buried in inline actions/github-script JS with no test coverage.

Usage:
  vouch_check.py --author USERNAME --association ASSOCIATION --trusted-file PATH

Exit 0 = trusted (workflow takes no action).
Exit 1 = untrusted (workflow should close the issue/PR + comment).
Either way, prints one line explaining the decision (stdout).
"""

from __future__ import annotations

import argparse
import sys

# GitHub's author_association values that already imply repo write access —
# these authors are trusted via repo permissions, no vouch needed.
TRUSTED_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}


def _read_trusted_list(path: str) -> set[str] | None:
    """None means the file is missing — caller must fail OPEN (never lock
    out every contributor just because the trust list itself vanished)."""
    try:
        with open(path) as f:
            return {
                line.strip() for line in f
                if line.strip() and not line.strip().startswith("#")
            }
    except FileNotFoundError:
        return None


def is_trusted(author: str, association: str, trusted_file: str) -> tuple[bool, str]:
    if association in TRUSTED_ASSOCIATIONS:
        return True, "existing collaborator (author_association)"
    vouched = _read_trusted_list(trusted_file)
    if vouched is None:
        return True, f"{trusted_file} missing — failing open"
    if author in vouched:
        return True, "explicitly vouched in " + trusted_file
    return False, "not a collaborator and not vouched"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--author", required=True)
    parser.add_argument("--association", required=True)
    parser.add_argument("--trusted-file", required=True)
    args = parser.parse_args()

    trusted, reason = is_trusted(args.author, args.association, args.trusted_file)
    print(reason)
    sys.exit(0 if trusted else 1)


if __name__ == "__main__":
    main()
