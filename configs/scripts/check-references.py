#!/usr/bin/env python3
"""Fail when a markdown link, anchor, or shipped path does not resolve.

Clade already recomputes *counts* (`doc-align.py`) and *module coverage*
(`check-arch-map.py`), but nothing checked that a link points at something
that exists. It shipped 150 dead links inside two published skills for months
because the absorbing sync flattened an upstream's numbered tree into
`references/` without rewriting the cross-links inside it.

The hard part is not resolution, it is suppressing false positives without
suppressing real ones — prose, regexes, and templates all look like links.
Every exclusion below is deliberate and narrow; when in doubt the checker
reports, because a silenced class is a class nobody looks at again.

Usage:
  check-references.py [--root REPO_ROOT] [--quiet]
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path

# Directories whose markdown is not addressed by this repo's own layout.
EXCLUDE_DIRS = {
    ".git", "node_modules", ".venv", "__pycache__", "dist", "build",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
    # Templates are shipped INTO other repositories; their links resolve there.
    "templates",
    # Regenerated verbatim from configs/ — checking them double-reports every
    # finding and makes the fix look twice as large as it is.
    "mcp-package", "plugins",
}

_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_HEADING = re.compile(r"^#{1,6}\s+(.*)$", re.M)
_FENCE = re.compile(r"^```.*?^```", re.M | re.S)
# Inline code spans document link *syntax* (`[keyword](filename.md)`) rather
# than linking anywhere. Stripping fences but not spans reports every such
# example as a dead link.
_INLINE_CODE = re.compile(r"`[^`\n]+`")
_EXTERNAL = re.compile(r"^(https?:|mailto:|tel:|ftp:|data:)", re.I)
# Bare words used as link-syntax placeholders in authoring examples.
_PLACEHOLDER = re.compile(
    r"^(url|path|link|href|filename|file|target|dir|slug|anchor|title|name)$", re.I)
# A plausible repo-relative path: no spaces, no regex alternation, no globs.
_PATHLIKE = re.compile(r"^[A-Za-z0-9._~/-]+$")


def slug_of(heading: str) -> str:
    """GitHub-style heading anchor. Keeps CJK: the zh README is anchored too."""
    s = re.sub(r"<[^>]+>", "", heading)            # inline html
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)  # links keep their text
    s = re.sub(r"[`*_~]", "", s).strip().lower()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    return s.replace(" ", "-")


def anchors_of(text: str) -> set[str]:
    out: set[str] = set()
    seen: collections.Counter[str] = collections.Counter()
    for heading in _HEADING.findall(_FENCE.sub("", text)):
        base = slug_of(heading)
        n = seen[base]
        seen[base] += 1
        out.add(base if n == 0 else f"{base}-{n}")
    return out


def markdown_files(root: Path):
    for p in sorted(root.rglob("*.md")):
        parts = p.relative_to(root).parts
        if any(seg in EXCLUDE_DIRS or seg.startswith(".") for seg in parts[:-1]):
            continue
        yield p


def check(root: Path) -> list[str]:
    anchor_cache: dict[Path, set[str]] = {}
    problems: list[str] = []

    for md in markdown_files(root):
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            problems.append(f"{md.relative_to(root)}: unreadable ({exc})")
            continue
        body = _INLINE_CODE.sub("", _FENCE.sub("", text))   # neither fences nor spans link
        own = anchors_of(text)
        rel = md.relative_to(root)

        for _, target in _LINK.findall(body):
            if _EXTERNAL.match(target) or "<" in target or ">" in target:
                continue
            path_part, _, anchor = target.partition("#")

            if not path_part:                        # same-document anchor
                if anchor and anchor not in own:
                    problems.append(f"{rel}: dead anchor #{anchor}")
                continue

            if path_part.startswith("/"):
                continue        # site-absolute URL — resolves on a website, never in a repo
            if _PLACEHOLDER.match(path_part) or not _PATHLIKE.match(path_part):
                continue                             # authoring example or prose

            dest = (md.parent / path_part).resolve()
            if not dest.exists():
                problems.append(f"{rel}: dead path -> {target}")
                continue
            if anchor and dest.suffix == ".md":
                if dest not in anchor_cache:
                    anchor_cache[dest] = anchors_of(
                        dest.read_text(encoding="utf-8", errors="replace"))
                if anchor not in anchor_cache[dest]:
                    problems.append(f"{rel}: dead anchor -> {target}")

    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", help="Repo root (default: cwd)")
    ap.add_argument("--quiet", action="store_true", help="only print failures")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    problems = check(root)

    if problems:
        print(f"check-references: {len(problems)} unresolved reference(s):")
        for p in problems:
            print(f"  {p}")
        return 1
    if not args.quiet:
        print("check-references: every markdown link, anchor, and path resolves ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
