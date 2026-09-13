#!/usr/bin/env python3
"""
check-sibling-facts.py — you changed the fact here; it is still wrong there.

Why this exists, with the measurement
-------------------------------------
Five convergence rounds over this repository found 61, 25, 34, (a round killed
by a quota) and 23 issues. The count did not fall, and the reason was not a long
tail of independent defects. It was this:

    round 2:  4 of 25 findings were siblings of round 1's own fixes
    round 3:  6 of 34   "        "        "     round 1-2's
    round 5: 10 of 23   "        "        "     round 1-4's   — 43%

A fact gets stated in four files. Someone corrects the one they are looking at.
The other three keep the old value, and only the NEXT audit sees them. Round 5
caught a sentence pointing at a section inverted one commit earlier, an hour
before.

So the class is mechanical and the fix is mechanical: when a commit removes a
distinctive factual string, ask whether that string survives elsewhere.

What it checks
--------------
For each line the diff DELETES, extract candidate facts — a number with a unit
or noun, a quoted name, a backticked identifier — and search the rest of the
tree for the same string. A survivor is a sibling site the change did not reach.

Deliberately conservative. It reports only strings distinctive enough that a
coincidental match is unlikely, and it reports rather than blocks by default:
this is a prompt to look, not a proof of error. The repository has learned twice
that a gate at low precision gets worked around, so `--strict` (exit 1) is
opt-in and the default exits 0 with its findings on stdout.

    check-sibling-facts.py                 # working tree vs HEAD
    check-sibling-facts.py --range A..B    # a commit range
    check-sibling-facts.py --strict        # exit 1 when a survivor is found
    check-sibling-facts.py --self-test

Stdlib only — the syntax-check CI job installs no dependencies.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# A "fact" distinctive enough to be worth chasing. Each pattern is anchored on
# something a coincidence rarely reproduces.
_FACT_PATTERNS = (
    # 32 hooks / 26 skills / 250 minutes / 9 handlers — number plus its noun.
    # SPELLED-OUT numbers count: the case that motivated this whole gate was
    # "bills **four minutes**, not three", corrected in three files and left in
    # PROGRESS.md. A digits-only pattern misses exactly the case it was built for.
    re.compile(r"\b(?:\d{1,4}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
               r"thirteen|fourteen|fifteen|twenty|thirty)\s+"
               r"(?:hooks?|skills?|agents?|scripts?|gates?|suites?|handlers?|"
               r"minutes?|signals?|routes?|modules?|entries|labels?|workflows?|commands?|"
               r"phases?|surfaces?|layers?|paths?)\b", re.I),
    # `symbol → percent → number → bar → off` and other arrow chains
    re.compile(r"`[^`\n]{4,60}(?:→|->)[^`\n]{4,60}`"),
    # version-ish literals: gpt-5.6-luna, v3.0.0
    re.compile(r"\b[a-z]+-\d+\.\d+-[a-z]+\b"),
)
# A bare backticked identifier was tried and dropped: a filename legitimately
# appears in many files, so `check-ci-checklist.py` matched a dozen places and
# said nothing about whether a FACT had changed. Precision matters more than
# reach here — a noisy prompt to look everywhere is a prompt nobody reads.

# Never chased: too common, or structural rather than factual.
_NOISE = re.compile(
    r"^\d+\.\d+\.\d+$"          # bare semver with no context is everywhere
    r"|^`(?:https?|www)"        # urls
    r"|^`[a-z]{1,3}`$",         # tiny identifiers
)

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "dist", "build", "logs"}
_TEXT_SUFFIX = {".md", ".py", ".sh", ".json", ".yml", ".yaml", ".toml", ".txt"}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                          text=True, check=False).stdout


def deleted_lines(rng: str | None) -> list[tuple[str, str]]:
    """(file, removed line) for every deletion in the diff."""
    args = ["diff", "-U0"] + ([rng] if rng else ["HEAD"])
    out, current, rows = _git(*args), "", []
    for line in out.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
        elif line.startswith("-") and not line.startswith("---"):
            rows.append((current, line[1:]))
    return rows


def facts_in(line: str) -> set[str]:
    found: set[str] = set()
    for pattern in _FACT_PATTERNS:
        for hit in pattern.findall(line):
            hit = hit.strip()
            if len(hit) >= 6 and not _NOISE.search(hit):
                found.add(hit)
    return found


def _tree_files() -> list[Path]:
    out = []
    for path in REPO.rglob("*"):
        if not path.is_file() or path.suffix not in _TEXT_SUFFIX:
            continue
        if _SKIP_DIRS & set(path.parts):
            continue
        if path.resolve() == Path(__file__).resolve():
            continue  # this file's docstring quotes the facts it exists to catch
        out.append(path)
    return out


def survivors(rng: str | None) -> list[tuple[str, str, list[str]]]:
    """(changed file, fact, [files where it survives])."""
    rows = deleted_lines(rng)
    if not rows:
        return []

    changed = {f for f, _ in rows}
    wanted: dict[str, set[str]] = {}
    for f, line in rows:
        for fact in facts_in(line):
            wanted.setdefault(fact, set()).add(f)
    if not wanted:
        return []

    hits: dict[str, list[str]] = {fact: [] for fact in wanted}
    for path in _tree_files():
        rel = str(path.relative_to(REPO))
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for fact in wanted:
            # A file the diff already touched is not a survivor of itself.
            if rel not in changed and fact in text:
                hits[fact].append(rel)

    return [
        (", ".join(sorted(wanted[fact])), fact, sorted(files))
        for fact, files in sorted(hits.items())
        if files
    ]


def self_test() -> int:
    problems: list[str] = []

    # The fact extractor is the whole instrument; test it directly.
    cases = [
        ("the tree holds 32 hooks today", "32 hooks", True),
        ("`symbol → percent → number → off`", "→", True),
        ("pinned at gpt-5.6-terra for now", "gpt-5.6-terra", True),
        # The motivating case: a spelled-out number, corrected in three files
        # and left in a fourth. A digits-only extractor missed it.
        ("bills **four minutes**, not three", "four minutes", True),
        ("just some ordinary prose with no facts", "", False),
        ("see `x`", "", False),
        # Deliberately NOT chased. A bare identifier appears in many files
        # legitimately, so chasing it said nothing about whether a fact moved.
        ("call `ai_opt_llm_ment_top_domains` for domains", "", False),
    ]
    for line, needle, should_find in cases:
        got = facts_in(line)
        if should_find and not any(needle in g for g in got):
            problems.append(f"missed a fact in {line!r} (got {got})")
        if not should_find and got:
            problems.append(f"invented a fact in {line!r}: {got}")

    if problems:
        for line in problems:
            print(f"SELF-TEST FAILED: {line}")
        return 1
    print(
        "SELF-TEST PASSED: the extractor finds counted nouns, arrow chains, "
        "versioned literals and spelled-out counts, and stays quiet on ordinary\n        prose and on bare identifiers."
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--range", dest="rng", help="Commit range, e.g. main..HEAD")
    ap.add_argument("--strict", action="store_true",
                    help="Exit 1 when a fact survives elsewhere (default: report and exit 0).")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    found = survivors(args.rng)
    if not found:
        print("check-sibling-facts: no changed fact survives anywhere else")
        return 0

    print(f"check-sibling-facts: {len(found)} changed fact(s) still present elsewhere —\n")
    for changed, fact, files in found:
        print(f"  {fact}")
        print(f"    changed in: {changed}")
        for f in files[:6]:
            print(f"    still in:   {f}")
        if len(files) > 6:
            print(f"    …and {len(files) - 6} more")
        print()
    print("Each is a site the change did not reach — or a coincidence. Check, do not assume.")
    return 1 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
