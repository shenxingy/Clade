#!/usr/bin/env python3
"""
archive-progress.py — hold PROGRESS.md to the cap its own skill sets.

The `/sync` skill says: keep PROGRESS.md under 100 lines, and move older
entries to `docs/progress-archive/YYYY-MM.md`. It said that in prose only, so
the file reached 1,209 lines and the archive directory was never created. A cap
stated in prose is a cap that drifts; this is the same file, stated as code.

    python3 configs/scripts/archive-progress.py            # report
    python3 configs/scripts/archive-progress.py --apply    # move entries
    python3 configs/scripts/archive-progress.py --check    # CI gate, exit 1 if over

Entries are `### YYYY-MM-DD — Title` blocks, newest first. The newest that fit
under the cap stay; the rest move to the archive file for their own month, and
an entry marked [ACTIVE] never moves regardless of age.

Stdlib only — the syntax-check job installs no project dependencies.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PROGRESS = REPO / "PROGRESS.md"
ARCHIVE_DIR = REPO / "docs" / "progress-archive"
CAP = 100

_ENTRY = re.compile(r"^### (\d{4})-(\d{2})-\d{2}\b")
_SEPARATOR = "---"


def split_entries(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Return (header, [(YYYY-MM, entry_text), …]) in file order."""
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if _ENTRY.match(line)]
    if not starts:
        return text, []

    # The separator line immediately above an entry belongs to that entry, so
    # removing the entry does not leave a dangling rule behind.
    def block_start(idx: int) -> int:
        i = starts[idx]
        while i > 0 and lines[i - 1].strip() in ("", _SEPARATOR):
            if lines[i - 1].strip() == _SEPARATOR:
                return i - 1
            i -= 1
        return starts[idx]

    header = "".join(lines[: block_start(0)])
    entries: list[tuple[str, str]] = []
    for n, idx in enumerate(starts):
        lo = block_start(n)
        hi = block_start(n + 1) if n + 1 < len(starts) else len(lines)
        body = "".join(lines[lo:hi])
        match = _ENTRY.match(lines[idx])
        entries.append((f"{match.group(1)}-{match.group(2)}", body))
    return header, entries


def plan(header: str, entries: list[tuple[str, str]]) -> tuple[list, list]:
    """Newest entries that fit under the cap stay; [ACTIVE] always stays."""
    kept: list[tuple[str, str]] = []
    moved: list[tuple[str, str]] = []
    used = len(header.splitlines())
    for month, body in entries:
        size = len(body.splitlines())
        if "[ACTIVE]" in body or used + size <= CAP:
            kept.append((month, body))
            used += size
        else:
            moved.append((month, body))
    return kept, moved


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    if not PROGRESS.is_file():
        print("PROGRESS.md not found")
        return 0

    text = PROGRESS.read_text(encoding="utf-8")
    total = len(text.splitlines())
    header, entries = split_entries(text)
    kept, moved = plan(header, entries)

    if not moved:
        print(f"PROGRESS.md: {total} lines, {len(entries)} entries — under the {CAP}-line cap")
        return 0

    print(f"PROGRESS.md: {total} lines, {len(entries)} entries — over the {CAP}-line cap")
    print(f"  keep {len(kept)} newest entr(y/ies), archive {len(moved)}")
    by_month: dict[str, list[str]] = {}
    for month, body in moved:
        by_month.setdefault(month, []).append(body)
    for month in sorted(by_month, reverse=True):
        print(f"  → docs/progress-archive/{month}.md  ({len(by_month[month])} entries)")

    if args.check:
        print("\nRun: python3 configs/scripts/archive-progress.py --apply")
        return 1
    if not args.apply:
        print("\nNothing written. Re-run with --apply.")
        return 0

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    for month, bodies in by_month.items():
        target = ARCHIVE_DIR / f"{month}.md"
        existing = target.read_text(encoding="utf-8") if target.is_file() else ""
        if not existing:
            existing = (
                f"# Progress archive — {month}\n\n"
                "> Entries moved out of [PROGRESS.md](../../PROGRESS.md) to hold it to\n"
                "> its 100-line cap. History, not current state; open work lives in\n"
                "> [TODO.md](../../TODO.md).\n\n"
            )
        target.write_text(existing.rstrip("\n") + "\n\n" + "".join(bodies).strip("\n") + "\n",
                          encoding="utf-8")
        print(f"  wrote {target.relative_to(REPO)}")

    pointer = (
        f"\nOlder entries live in [docs/progress-archive/]"
        f"(docs/progress-archive/) — {len(moved)} archived,"
        f" newest month first.\n"
    )
    new_header = header.rstrip("\n") + "\n" + pointer
    PROGRESS.write_text(new_header + "\n" + "".join(b for _, b in kept).lstrip("\n"),
                        encoding="utf-8")
    print(f"  PROGRESS.md now {len(PROGRESS.read_text(encoding='utf-8').splitlines())} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
