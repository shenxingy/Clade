#!/usr/bin/env python3
"""Assert that exactly one root document carries open work.

`TODO.md`, `VISION.md`, `IMPLEMENTATION_PLAN.md` and `PROGRESS.md` describe
overlapping state, and until 2026-08-29 nothing said which one wins. The
measured answer was already unambiguous — only `TODO.md` held unchecked items
(4 open / 217 done; the other three had zero checkboxes between them) — but it
was a habit rather than a rule, and habits drift silently:

  * `VISION.md`'s milestone table stopped at Phase 13 while `TODO.md` tracked a
    fully-checked Phase 14, so the two disagreed about what shipped.
  * `BRAINSTORM.md` carried two `CONDITIONAL WATCH` items that were verbatim
    duplicates of entries in `TODO.md`, which is how one copy gets resolved and
    the other silently does not.

Each file now opens with a one-line role header. A header is prose, and prose
is what already failed here, so this makes the arrangement checkable:

  1. only `TODO.md` may carry an unchecked ``- [ ]``
  2. every roadmap document must state its role
  3. `TODO.md` must keep the sentence naming it the single source of open work

`BRAINSTORM.md` is deliberately out of scope: it is an inbox, and an inbox with
raw ideas in it is working as intended. Its own header already says an idea is
cleared once it lands in `TODO.md` — the rule this check enforces one level up.

Checkboxes inside fenced code blocks are ignored: a fenced ``- [ ]`` is an
example of the syntax, not a claim about this repository.

stdlib only, no imports from `orchestrator/` — CI's `syntax-check` job installs
no dependencies, and a gate that cannot run in the job that runs it is not a
gate. Exit 0 when the arrangement holds, 1 otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The one file whose unchecked boxes mean "not done yet".
AUTHORITY = "TODO.md"

#: Root documents that describe project state. Value = the marker each must
#: carry, proving it declares its own role rather than leaving it to be guessed.
ROADMAP_DOCS = {
    "TODO.md": "single source of open work",
    "VISION.md": "**Role:",
    "IMPLEMENTATION_PLAN.md": "**Role:",
    "PROGRESS.md": "**Role:",
}

OPEN_BOX = re.compile(r"^\s*[-*]\s+\[ \]")
FENCE = re.compile(r"^\s*(```|~~~)")

#: A role header belongs at the top; scanning the whole file would let a
#: matching phrase buried in a history entry pass for a declaration.
HEADER_LINES = 15


def _open_boxes(text: str) -> list[tuple[int, str]]:
    """Unchecked items outside fenced code blocks, as (line number, line)."""
    found: list[tuple[int, str]] = []
    fence: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        marker = FENCE.match(line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token == fence:
                fence = None
            continue
        if fence is None and OPEN_BOX.match(line):
            found.append((number, line.strip()))
    return found


def main() -> int:
    problems: list[str] = []

    for name, marker in ROADMAP_DOCS.items():
        path = REPO_ROOT / name
        if not path.exists():
            problems.append(f"{name}: missing — a roadmap document was deleted or renamed")
            continue
        text = path.read_text(encoding="utf-8")

        head = "\n".join(text.splitlines()[:HEADER_LINES])
        if marker not in head:
            problems.append(
                f"{name}: no role header in its first {HEADER_LINES} lines "
                f"(expected to contain {marker!r})"
            )

        if name == AUTHORITY:
            continue
        for number, line in _open_boxes(text):
            problems.append(
                f"{name}:{number}: open item outside {AUTHORITY} — {line[:70]}\n"
                f"    Move it to {AUTHORITY}, or close it here as a dated outcome."
            )

    if problems:
        print(f"Roadmap authority check FAILED ({len(problems)} problem(s)):\n", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print(
            f"\n{AUTHORITY} is the single source of open work. An unchecked '- [ ]'"
            f"\nanywhere else means two files disagree about what is left to do.",
            file=sys.stderr,
        )
        return 1

    open_count = len(_open_boxes((REPO_ROOT / AUTHORITY).read_text(encoding="utf-8")))
    others = ", ".join(n for n in ROADMAP_DOCS if n != AUTHORITY)
    print(
        f"Roadmap authority OK: {AUTHORITY} carries {open_count} open item(s); "
        f"{others} carry none and each states its role."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
