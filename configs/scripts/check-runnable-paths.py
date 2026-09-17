#!/usr/bin/env python3
"""
check-runnable-paths.py — if a skill tells you to run it, it must exist.

Why this is the second attempt
------------------------------
`check-references.py` strips inline code spans by design: a span showing link
syntax is documenting that syntax, not linking. Every runnable path is inside a
code span, so all of them are invisible to it — which is how five installer
paths that had never existed survived every gate in this repository, and how the
whole `/blog` delivery contract came to name four scripts that were not there.

A first replacement was written, iterated three times, and WITHDRAWN at roughly
30% precision. The reason was recorded: a skill's own `scripts/X.py` and a skill
legitimately naming a file in the READER's project (`lib/github-client.ts`) were
indistinguishable without knowing intent. A gate at 30% precision gets ignored or
worked around, which is worse than none.

Two things changed, and both were prerequisites:

1. The reference convention is settled. A shared script is cited by its
   installed path, `~/.claude/scripts/<sub>/<name>`; a skill's own script is
   cited skill-relative as `scripts/<name>`. 67 sites were converted.
2. Only paths in a SKILL'S OWN NAMESPACE are checked — `scripts/`,
   `references/`, `assets/`, `agents/`, and anything under `~/.claude/`.
   `lib/github-client.ts` is not one of those and is never examined, which is
   precisely the class that produced the false alarms.

Resolution order for a bare `scripts/X`, and the order matters:

  1. `configs/skills/<skill>/scripts/X`   — the skill's own. Correct as written.
  2. `configs/scripts/<sub>/X`            — shared, but MISSING ITS SEGMENT.
  3. nowhere                              — a phantom.

Getting (1) wrong is how the first count of this defect came out at 145 when the
real number was 67: 88 references were skill-local and already correct, and a
basename match called them broken.

    check-runnable-paths.py           # report, exit 1 on a phantom
    check-runnable-paths.py --quiet   # count only
    check-runnable-paths.py --self-test

Stdlib only — the syntax-check CI job installs no dependencies.
"""

from __future__ import annotations

import argparse
import collections
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKILLS = REPO / "configs" / "skills"
SHARED = REPO / "configs" / "scripts"
AGENTS = REPO / "configs" / "agents"

# Only these prefixes are a claim about THIS repository. Everything else in a
# code span may be the reader's project, an example, or a shell fragment.
_OWNED = re.compile(
    r"`[^`\n]*?(?<![\w/.-])"
    r"(?P<path>(?:~/\.claude/[\w./-]+"
    r"|(?:scripts|references|assets|agents)/[\w./-]+\.[A-Za-z0-9]{1,6}))"
)

# A path inside one of these is illustrative by construction.
_EXAMPLE_MARKERS = ("e.g.", "for example", "hypothetical", "such as",
                    "for illustration", "your-", "<slug>", "<name>", "<file>")

# Runtime state a skill CREATES, inside its own directory. blog-notebooklm says
# "All data stored inside the skill directory: scripts/data/auth_info.json" —
# describing where it will write, not a file that ships. These were the only 2
# false positives in the 85 this gate reported on its first restricted run.
_RUNTIME_SEGMENTS = ("/data/", "/cache/", "/state/", "/tmp/", "/logs/")

# A placeholder in a template or an example command. `skill-new` teaches you to
# write `scripts/x.py`; `equip` shows `~/.claude/skills/xyz`. Neither is a claim.
_PLACEHOLDERS = ("/x.py", "/y.py", "/foo", "/bar", "/xyz", "/abc",
                 "/my-", "/example", "/placeholder", "/skill-name")

# A line that says the thing is GONE is documenting its absence, not asserting
# its presence. blog-flow explains at length that `scripts/sync_flow.py` never
# existed and should not; reporting that sentence as a dead path is reporting
# the fix as the defect.
# "phantom" was tried and dropped: a path may legitimately contain the word, and
# a marker that a FILENAME can satisfy suppresses the finding it was meant to
# explain. Every marker here is a phrase prose uses, not a word a path can hold.
_ABSENCE_MARKERS = ("never existed", "does not exist", "no longer", "was removed",
                    "there is no", "not shipped", "was withdrawn")


# ─── The ratchet ───────────────────────────────────────────────────────────────
#
# 19 distinct (file, path) phantoms remain — 22 occurrences — in the email and
# seo families and in blog-discourse. They are recorded here so the gate can
# BLOCK from day one instead of reporting into a void: a path not on this list
# fails the build, and a path on it is a known debt with a date on it.
#
# **This list shrinks and never grows.** Same rule as `orchestrator/ruff.toml`'s
# ignore baseline, and for the same reason: a gate whose exception list can grow
# is a gate that will be routed around instead of satisfied. Adding an entry
# requires deleting one, or a commit that argues why the path is legitimately
# unresolvable.
#
# A stale entry is also reported. An exception nobody removes after the fix is
# how a baseline becomes permanent.
#
# Recorded 2026-09-12. Several of these name a DataForSEO helper, and DataForSEO
# is a paid API — under "Paid APIs are opt-in, never a dependency" those sites
# want reworking rather than a new script, which is why they are debt and not a
# quick fix.
BASELINE = {
    ("configs/skills/blog-discourse/SKILL.md", "scripts/discourse_research.py"),
    ("configs/skills/email-audit/SKILL.md", "references/deliverability-rules.md"),
    ("configs/skills/email-audit/SKILL.md", "references/mcp-integration.md"),
    ("configs/skills/email-audit/SKILL.md", "scripts/check_deliverability.py"),
    ("configs/skills/email-plan/SKILL.md", "references/mcp-integration.md"),
    ("configs/skills/email-review/SKILL.md", "references/deliverability-rules.md"),
    ("configs/skills/email-review/SKILL.md", "references/technical-standards.md"),
    ("configs/skills/email-review/SKILL.md", "scripts/analyze_email_html.py"),
    ("configs/skills/email-review/SKILL.md", "scripts/score_subject_line.py"),
    ("configs/skills/seo-audit/prompt.md", "scripts/drift_history.py"),
    ("configs/skills/seo-cluster/SKILL.md", "scripts/dataforseo_costs.py"),
    ("configs/skills/seo-dataforseo/references/cost-tiers.md", "scripts/dataforseo_costs.py"),
    ("configs/skills/seo-ecommerce/references/marketplace-endpoints.md", "scripts/dataforseo_normalize.py"),
    ("configs/skills/seo-hreflang/references/machine-translation-qa.md", "scripts/content_quality.py"),
    ("configs/skills/seo-image-gen/prompt.md", "scripts/cost_tracker.py"),
    ("configs/skills/seo-technical/prompt.md", "scripts/render_page.py"),
    ("configs/skills/seo-technical/references/agent-friendly-pages.md", "scripts/render_page.py"),
    ("configs/skills/seo/prompt.md", "scripts/drift_history.py"),
    ("configs/skills/seo/references/thinking-framework.md", "scripts/render_page.py"),
}


def shared_index() -> dict[str, list[str]]:
    index: dict[str, list[str]] = collections.defaultdict(list)
    for path in SHARED.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(SHARED)
        if len(rel.parts) > 1:
            index[path.name].append("/".join(rel.parts[:-1]))
    return index


def _paragraph_at(lines: list[str], line_no: int) -> str:
    """The contiguous non-blank block containing line_no (1-indexed), lowered."""
    i = line_no - 1
    start = i
    while start > 0 and lines[start - 1].strip():
        start -= 1
    end = i
    while end + 1 < len(lines) and lines[end + 1].strip():
        end += 1
    return " ".join(lines[start:end + 1]).lower()


def skill_root_of(path: Path) -> Path:
    root = path
    while root.parent != SKILLS:
        root = root.parent
    return root


# Only these subtrees of ~/.claude are INSTALLED from this repository. The rest
# — corrections/, orchestrator/, rules/, settings.json — are created at runtime
# by the hooks and the server, so a skill naming one is describing state, not a
# shipped file. Checking them produced 29 of this gate's first 111 findings and
# every one of the 29 was wrong.
_INSTALLED_PREFIXES = ("scripts/", "skills/", "agents/", "hooks/", "output-styles/")


def claude_target(rel: str):
    """Source in this repository for a ~/.claude/... citation.

    False when the path is runtime state and therefore not ours to check, None
    when it should install and does not, and the Path otherwise.
    """
    rel = rel[len("~/.claude/"):]
    if not any(rel.startswith(prefix) for prefix in _INSTALLED_PREFIXES):
        return False
    for base in (REPO / "configs", REPO):
        candidate = base / rel
        if candidate.exists():
            return candidate
    return None


def scan() -> tuple[list[str], list[str], int]:
    """(phantoms, missing_segment, checked)."""
    index = shared_index()
    phantoms: list[str] = []
    missing: list[str] = []
    checked = 0

    for doc in sorted(SKILLS.rglob("*.md")):
        root = skill_root_of(doc)
        skill = root.name
        lines = doc.read_text(encoding="utf-8", errors="replace").splitlines()
        for line_no, line in enumerate(lines, 1):
            low = line.lower()
            if any(marker in low for marker in _EXAMPLE_MARKERS):
                continue
            # The PARAGRAPH, not a fixed line window. Prose wraps inside a
            # paragraph, so blog-flow's explanation of why sync_flow.py must not
            # exist puts the path on one line and "never existed" on the next.
            # A fixed +/-2 window was too loose in the other direction: the
            # `audit` skill discusses absent files throughout, so a genuinely new
            # phantom appended to it was suppressed by an unrelated sentence five
            # lines away. A blank line ends the excuse.
            if any(marker in _paragraph_at(lines, line_no) for marker in _ABSENCE_MARKERS):
                continue
            for match in _OWNED.finditer(line):
                rel = match.group("path")
                # A glob is not a path. `~/.claude/scripts/equip_*.py` matched up
                # to the asterisk and was reported as a dead file.
                if line[match.end("path"):match.end("path") + 1] in ("*", "?", "["):
                    continue
                checked += 1
                where = f"{doc.relative_to(REPO)}:{line_no}"

                if rel.startswith("~/.claude/"):
                    if any(ph in "/" + rel.lower() for ph in _PLACEHOLDERS):
                        checked -= 1
                        continue
                    target = claude_target(rel)
                    if target is False:
                        checked -= 1      # runtime state; not a claim about the repo
                    elif target is None:
                        phantoms.append(f"{where}: {rel} — installs from nothing")
                    continue

                kind, _, tail = rel.partition("/")
                if kind == "agents":
                    if not (AGENTS / tail).exists() and not (root / rel).exists():
                        phantoms.append(f"{where}: {rel} — no such agent")
                    continue

                if (root / rel).exists():
                    continue                                   # skill's own. correct.

                if any(seg in "/" + rel for seg in _RUNTIME_SEGMENTS):
                    checked -= 1                               # state it writes, not ships
                    continue
                if any(ph in "/" + rel.lower() for ph in _PLACEHOLDERS):
                    checked -= 1                               # a template's own example
                    continue

                name = Path(tail).name
                if kind == "scripts" and "/" not in tail and name in index:
                    missing.append(
                        f"{where}: scripts/{name} — shared script, cite it as "
                        f"~/.claude/scripts/{index[name][0]}/{name}")
                    continue

                phantoms.append(f"{where}: {rel} — {skill} names it and it does not exist")

    return phantoms, missing, checked


# A path documented as a BARE COMMAND must be executable. `oracle-review.sh` was
# mode 100644 while CLAUDE.md documented running it directly, so the documented
# control exited 126 — a gate that cannot start, which is this repository's most
# repeated defect shape. Scope is deliberately narrow: only paths a doc invokes
# with no interpreter in front of them. The wider rule ("a shebang implies +x")
# was measured first and rejected — it fires on 20+ files, every sourced
# `hooks/lib/*.sh` and every hook `settings-hooks.json` calls as `bash <path>`,
# which is a gate that fires on honest work. Today this one covers 3 paths and
# has no false positives.
_BARE_CMD = re.compile(r"^\s*(configs/(?:scripts|hooks)/[A-Za-z0-9_./-]+\.(?:sh|py))\b", re.M)


def scan_exec_bits() -> list[str]:
    """Paths a doc tells you to run directly that are not executable."""
    docs = [REPO / "CLAUDE.md", *(REPO / "docs").rglob("*.md"),
            *(SKILLS.rglob("*.md"))]
    bad: list[str] = []
    seen: set[str] = set()
    for doc in docs:
        if not doc.is_file():
            continue
        try:
            text = doc.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _BARE_CMD.finditer(text):
            rel = m.group(1)
            if rel in seen:
                continue
            target = REPO / rel
            if not target.is_file():
                continue          # a phantom; the path scan above owns that case
            seen.add(rel)
            if not os.access(target, os.X_OK):
                bad.append(f"{doc.relative_to(REPO)}: {rel} — documented as a bare "
                           f"command but not executable (would exit 126)")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    phantoms, missing, checked = scan()
    not_exec = scan_exec_bits()

    if args.quiet:
        unknown = sum(
            1 for line in phantoms
            if (lambda m: (m.group(1), m.group(2)) not in BASELINE if m else True)(
                re.match(r"(\S+?):\d+: (\S+) —", line)))
        print(f"check-runnable-paths: {checked} checked, {len(phantoms)} phantom(s) "
              f"({unknown} not on the baseline), {len(missing)} missing a path segment, "
              f"{len(not_exec)} not executable")
        return 1 if (unknown or not_exec) else 0

    if missing:
        print(f"{len(missing)} reference(s) name a SHARED script without its "
              f"subdirectory — they resolve neither in the repo nor after install:")
        for line in missing:
            print(f"  {line}")
        print()

    known, fresh = [], []
    seen = set()
    for line in phantoms:
        match = re.match(r"(\S+?):\d+: (\S+) —", line)
        key = (match.group(1), match.group(2)) if match else None
        if key in BASELINE:
            known.append(line)
            seen.add(key)
        else:
            fresh.append(line)

    stale = BASELINE - seen
    if stale:
        print(f"{len(stale)} baseline entry(ies) no longer fire — delete them, "
              f"the list only shrinks:")
        for entry in sorted(stale):
            print(f"  {entry[0]}: {entry[1]}")
        print()

    if known and not args.quiet:
        print(f"{len(known)} known phantom(s) on the baseline (debt, not new):")
        for line in known[:5]:
            print(f"  {line}")
        if len(known) > 5:
            print(f"  …and {len(known) - 5} more")
        print()

    if not_exec:
        print(f"{len(not_exec)} path(s) documented as a bare command but not executable:")
        for line in not_exec:
            print(f"  {line}")
        print("\nFix with `chmod +x`. A documented control that exits 126 is a lie in "
              "the docs, and it reads as a gate that passed.")
        return 1

    if fresh:
        print(f"{len(fresh)} NEW path(s) a skill tells you to use, which do not exist:")
        for line in fresh:
            print(f"  {line}")
        print("\nEither create the file or stop naming it. A skill that instructs a "
              "run to execute a missing file fails at the step that names it.")
        return 1
    if stale:
        return 1

    print(f"check-runnable-paths: {checked} owned path(s) across "
          f"{len(list(SKILLS.iterdir()))} skills — every one resolves"
          + (f" ({len(missing)} cite a shared script without its segment)" if missing else "")
          + ", and every bare-command path is executable")
    return 1 if missing else 0


def self_test() -> int:
    """Positive and negative controls, including the case that broke attempt one."""
    import tempfile

    problems: list[str] = []
    global SKILLS, SHARED, AGENTS, REPO
    saved = (SKILLS, SHARED, AGENTS, REPO)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        REPO = root
        SKILLS = root / "configs" / "skills"
        SHARED = root / "configs" / "scripts"
        AGENTS = root / "configs" / "agents"
        (SHARED / "seo").mkdir(parents=True)
        (SHARED / "seo" / "moz_api.py").write_text("x", encoding="utf-8")
        AGENTS.mkdir(parents=True)
        (AGENTS / "real-agent.md").write_text("x", encoding="utf-8")

        good = SKILLS / "good"
        (good / "scripts").mkdir(parents=True)
        (good / "scripts" / "local.py").write_text("x", encoding="utf-8")
        (good / "references").mkdir()
        (good / "references" / "there.md").write_text("x", encoding="utf-8")
        (good / "SKILL.md").write_text(
            "Run `scripts/local.py` and read `references/there.md`.\n"
            "Spawn the `agents/real-agent.md` agent.\n"
            "Edit `lib/github-client.ts` in the user's project.\n"
            "Rename `src/components/Button.tsx` as needed.\n", encoding="utf-8")

        bad = SKILLS / "bad"
        bad.mkdir(parents=True)
        (bad / "SKILL.md").write_text(
            "Run `scripts/ghost.py` first.\n"
            "Then `~/.claude/scripts/never_shipped.py`.\n"
            "Read `references/absent.md`.\n"
            "Spawn the `agents/no-such-agent.md` agent.\n"
            "State accumulates in `~/.claude/corrections/rules.md`.\n",
            encoding="utf-8")

        seg = SKILLS / "seo-thing"
        seg.mkdir(parents=True)
        (seg / "SKILL.md").write_text("Run `scripts/moz_api.py` now.\n", encoding="utf-8")

        phantoms, missing, checked = scan()
    not_exec = scan_exec_bits()

    SKILLS, SHARED, AGENTS, REPO = saved

    joined = " ".join(phantoms)
    for expected in ("ghost.py", "never_shipped.py", "absent.md", "no-such-agent"):
        if expected not in joined:
            problems.append(f"positive control did not fire: {expected}")
    for quiet in ("local.py", "there.md", "real-agent"):
        if quiet in joined:
            problems.append(f"negative control fired on a real path: {quiet}")
    # The class that withdrew attempt one: a reader-project path is not ours.
    for reader in ("github-client", "Button.tsx"):
        if reader in joined:
            problems.append(f"a reader-project path was reported: {reader}")
    if "corrections/rules.md" in joined:
        problems.append("runtime state under ~/.claude was reported as a phantom")
    if len(missing) != 1 or "moz_api.py" not in missing[0]:
        problems.append(f"the missing-segment case was not recognised: {missing}")
    if checked < 6:
        problems.append(f"only {checked} paths were examined; the scan is too narrow")

    if problems:
        for line in problems:
            print(f"SELF-TEST FAILED: {line}")
        return 1
    print("SELF-TEST PASSED: fires on a phantom script, a phantom install path, a "
          "phantom reference and a phantom agent; stays quiet on a skill's own "
          "files, on runtime state, and on paths in the READER's project; and tells a shared script "
          "missing its segment apart from one that does not exist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
