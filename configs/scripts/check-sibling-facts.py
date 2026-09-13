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
import pathlib
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
    """Raise on a failed git call.

    This returned only .stdout with check=False, so a bad revision range, a
    detached worktree or a missing origin produced an empty diff — and an empty
    diff is indistinguishable from "nothing changed". The CI line runs
    `--range origin/main...HEAD`, which is exactly the invocation that fails on
    a fresh clone with no origin/main, and it reported a clean result.
    """
    proc = subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                          text=True, check=False)
    if proc.returncode:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({proc.returncode}): "
            f"{proc.stderr.strip()[:300]}")
    return proc.stdout


def diff_lines(rng: str | None) -> tuple[list[tuple[str, str]], dict[str, str]]:
    """((file, removed line)..., {file: all added text}).

    The added text matters as much as the removed. Rewriting one number in a
    long line deletes and re-adds the WHOLE line, so every other fact on it
    looks removed. Checking the additions is what tells the two apart.
    """
    args = ["diff", "-U0"] + ([rng] if rng else ["HEAD"])
    out, current, rows = _git(*args), "", []
    added: dict[str, list[str]] = {}
    for line in out.splitlines():
        if line.startswith("+++ "):
            # A DELETED file's header is `+++ /dev/null`. Only reassigning on
            # `+++ b/` left `current` pointing at whichever file came before it
            # in the diff, so every line of a deleted file was attributed there.
            tail = line[4:]
            current = tail[2:] if tail.startswith("b/") else ""
        elif line.startswith("--- ") or line.startswith("+++ "):
            continue
        elif line.startswith("-") and not line.startswith("---"):
            rows.append((current, line[1:]))
        elif line.startswith("+") and not line.startswith("+++"):
            added.setdefault(current, []).append(line[1:])
    return rows, {f: "\n".join(v) for f, v in added.items()}


# Append-only records by this repository's own convention. A past value is
# SUPPOSED to survive here — "the plugin advertised 37 agents and loaded none"
# is history, and correcting it would be falsifying the record. Reported in a
# separate bucket rather than mixed in with the likely misses.
_HISTORICAL = ("CHANGELOG.md", "docs/research/", "docs/progress-archive/",
               "PROGRESS.md", "docs/incidents/")


def is_historical(rel: str) -> bool:
    return any(marker in rel for marker in _HISTORICAL)


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


def survivors(rng: str | None) -> list[tuple[str, str, list[str], list[str]]]:
    """(changed file, fact, [live survivors], [historical survivors])."""
    rows, added = diff_lines(rng)
    if not rows:
        return []

    wanted: dict[str, set[str]] = {}
    for f, line in rows:
        for fact in facts_in(line):
            # Present in what the same file ADDED? Then it did not change; the
            # line around it did. This was 1 of the 3 findings on the gate's
            # first real run — "138 skills" on a line whose agent count moved.
            if fact in added.get(f, ""):
                continue
            wanted.setdefault(fact, set()).add(f)
    if not wanted:
        return []

    # Word-boundary search, case-insensitively, because the extractor is
    # case-insensitive: "Five Gates" was extracted verbatim and then looked for
    # with a case-SENSITIVE test, so a title-cased fact never found its
    # lower-cased sibling. And a bare `in` made "22 gates" match "122 gates".
    probes = {fact: re.compile(r"(?<![\w-])" + re.escape(fact) + r"(?![\w-])", re.I)
              for fact in wanted}

    hits: dict[str, list[str]] = {fact: [] for fact in wanted}
    for path in _tree_files():
        rel = str(path.relative_to(REPO))
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for fact, probe in probes.items():
            # PER-FACT, not global. The exemption is only "a file that changed
            # this fact is not a survivor of itself"; excluding every file the
            # diff touched silenced the tool on exactly the commits it exists
            # for — one that fixes a fact in two of four places touches both.
            if rel in wanted[fact]:
                continue
            if probe.search(text):
                hits[fact].append(rel)

    return [
        (", ".join(sorted(wanted[fact])), fact,
         sorted(f for f in files if not is_historical(f)),
         sorted(f for f in files if is_historical(f)))
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

    problems.extend(_survivor_controls())

    if problems:
        for line in problems:
            print(f"SELF-TEST FAILED: {line}")
        return 1
    print(
        "SELF-TEST PASSED: the extractor finds counted nouns, arrow chains, "
        "versioned literals and spelled-out counts and stays quiet on ordinary "
        "prose and bare identifiers; and the survivor search reports a sibling "
        "in a file the same commit touched, matches case-insensitively, "
        "respects word boundaries, and stays quiet on a fact the diff re-added."
    )
    return 0


def _survivor_controls() -> list[str]:
    """Exercise survivors(), not just the extractor.

    The first version of this self-test called facts_in and nothing else. Three
    separate mutations of the survivor search — making the changed-file
    exemption global, dropping the word boundary, dropping case-insensitivity —
    all left it green. A gate whose self-test covers only its cheapest half is
    the failure this repository keeps finding in its own instruments, and this
    one shipped it while its docstring argued against exactly that.
    """
    import tempfile

    problems: list[str] = []
    saved_diff, saved_tree, saved_repo = diff_lines, _tree_files, REPO

    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        (root / "a.md").write_text("we ship 32 hooks today\n", encoding="utf-8")
        (root / "b.md").write_text("also 32 hooks here\n", encoding="utf-8")
        (root / "c.md").write_text("Thirty Hooks, title-cased\n", encoding="utf-8")
        (root / "d.md").write_text("we counted 132 hooks in total\n", encoding="utf-8")

        globals()["REPO"] = root
        globals()["_tree_files"] = lambda: sorted(root.glob("*.md"))

        def scenario(rows, added):
            globals()["diff_lines"] = lambda _rng: (rows, added)
            return {fact: (live, hist) for _c, fact, live, hist in survivors(None)}

        # 1. The motivating case, and the one the global exemption broke: a.md
        #    changed "32 hooks", b.md changed a DIFFERENT fact in the same
        #    commit, and b.md still holds "32 hooks" so it is a survivor.
        #
        #    b.md must change a fact of its own. With b.md changing nothing the
        #    global and per-fact exemptions are the same set, and the mutation
        #    that made the exemption global left this test green — a control
        #    that cannot distinguish the defect is not testing for it.
        found = scenario([("a.md", "we ship 32 hooks today"),
                          ("b.md", "and 9 agents run nightly")],
                         {"a.md": "we ship 33 hooks today",
                          "b.md": "and 10 agents run nightly"})
        if "32 hooks" not in found:
            problems.append("survivor search missed a sibling entirely")
        elif "b.md" not in found["32 hooks"][0]:
            problems.append("a file the same commit touched was exempted globally")

        # 2. The file that changed the fact is not a survivor of itself.
        if "a.md" in found.get("32 hooks", ([], []))[0]:
            problems.append("the changing file was reported as its own survivor")

        # 3. A boundary: 132 must not satisfy a search for 32.
        if "d.md" in found.get("32 hooks", ([], []))[0]:
            problems.append("substring match: '132 hooks' satisfied '32 hooks'")

        # 4. Case-insensitive, because the extractor is.
        found = scenario([("a.md", "thirty hooks were shipped")],
                         {"a.md": "forty hooks were shipped"})
        if "c.md" not in found.get("thirty hooks", ([], []))[0]:
            problems.append("case-sensitive search missed a title-cased sibling")

        # 5. A fact the diff RE-ADDED did not change; the line around it did.
        found = scenario([("a.md", "we ship 32 hooks today")],
                         {"a.md": "we ship 32 hooks today, plus one more"})
        if "32 hooks" in found:
            problems.append("a fact present in the diff's own additions was chased")

        # 6. A deleted file's hunk header is `+++ /dev/null`. Attributing its
        #    removed lines to whichever file preceded it in the diff makes every
        #    fact in a deleted file look like a change to an unrelated one.
        # Restore the REAL diff_lines: scenario() replaced it, and leaving the
        # stub in place made this whole control read a fixed row list instead of
        # parsing anything. The mutation harness is what exposed that — a dead
        # assertion inside the self-test written to catch dead assertions.
        globals()["diff_lines"] = saved_diff
        globals()["REPO"] = saved_repo
        saved_git = _git
        globals()["_git"] = lambda *a: (
            "--- a/keep.md\n+++ b/keep.md\n@@ -1 +1 @@\n-we ship 32 hooks\n+we ship 33 hooks\n"
            "--- a/gone.md\n+++ /dev/null\n@@ -1 +0,0 @@\n-this had 77 agents in it\n")
        try:
            rows, _added = diff_lines(None)
        finally:
            globals()["_git"] = saved_git
        misattributed = [line for f, line in rows if f == "keep.md" and "77 agents" in line]
        if misattributed:
            problems.append("a deleted file's lines were attributed to the file before it")
        globals()["REPO"] = root

        # 7. A failed git call must raise rather than read as a clean tree.
        globals()["diff_lines"] = saved_diff
        globals()["REPO"] = saved_repo
        try:
            _git("rev-parse", "definitely-not-a-ref-xyz")
            problems.append("a failing git call returned quietly")
        except RuntimeError:
            pass

    globals()["diff_lines"] = saved_diff
    globals()["_tree_files"] = saved_tree
    globals()["REPO"] = saved_repo
    return problems


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
    live = [row for row in found if row[2]]
    if not found:
        print("check-sibling-facts: no changed fact survives anywhere else")
        return 0

    if live:
        print(f"check-sibling-facts: {len(live)} changed fact(s) still present elsewhere —\n")
        for changed, fact, files, hist in live:
            print(f"  {fact}")
            print(f"    changed in: {changed}")
            for f in files[:6]:
                print(f"    still in:   {f}")
            if len(files) > 6:
                print(f"    …and {len(files) - 6} more")
            if hist:
                print(f"    (also in {len(hist)} historical record(s), which is correct)")
            print()
        print("Each is a site the change did not reach — or a coincidence. "
              "Check, do not assume.")

    hist_only = [row for row in found if not row[2] and row[3]]
    if hist_only:
        print(f"\n{len(hist_only)} fact(s) survive ONLY in append-only records "
              f"(changelog, research, progress archive). That is correct — a past "
              f"value is supposed to stay in the record:")
        for _, fact, _, hist in hist_only:
            print(f"  {fact} — {', '.join(hist[:3])}")

    return 1 if (args.strict and live) else 0


if __name__ == "__main__":
    raise SystemExit(main())
