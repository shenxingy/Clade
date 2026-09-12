#!/usr/bin/env python3
"""
check-skill-contracts.py — a skill must not advertise what it does not do.

Why this is a gate and not a review note
----------------------------------------
Three convergence rounds over this repository found 61, 25 and 26 issues. The
counts are not falling, and the reason is that the issues are not independent —
they are the same few CLASSES recurring across 138 skills. Fixing instances by
hand does not converge; a gate on the class does.

This gates the largest of those classes: a promise in the front matter that the
workflow never keeps. Found by hand so far:

  /create-pr        advertised --dry-run; the workflow only ever published.
                    The side effect is an externally visible PR, so a run asked
                    to preview opened one.
  /document-release advertised --dry-run; the workflow wrote and committed.
  /brief            advertised --all; nothing read it.
  /ship             advertised --skip-tests, which does not exist, and hid
                    --no-bump, which does.
  /incident         promised follow-up tasks in TODO.md; the six-step workflow
                    stopped before writing any.

Two checks, both deliberately conservative — a false alarm here costs more than
a missed cosmetic one, because the fix is to edit a skill:

  1. Every ``--flag`` in ``argument-hint`` must appear somewhere in the skill's
     body (SKILL.md after the front matter, plus prompt.md). Prose that names
     the mode counts: the point is that the workflow knows the flag exists.
  2. Every path the front matter references must resolve.

Not checked, on purpose: whether the body's handling is CORRECT. That needs a
reader. This catches the flag nobody wired at all, which is the case that keeps
shipping.

Stdlib only — the syntax-check CI job installs no dependencies.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKILLS = REPO / "configs" / "skills"

_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_HINT = re.compile(r"^argument-hint:\s*(.+?)\s*$", re.M)
_FLAG = re.compile(r"--([a-z][a-z0-9-]*)")
_PATH = re.compile(r"`(references/[\w./-]+|scripts/[\w./-]+|assets/[\w./-]+)`")

# Skills synced from an upstream author are not ours to rewrite; report them
# separately rather than failing the build on someone else's front matter.
_UPSTREAM_AUTHORS = ("AgriciDaniel",)


def front_matter(text: str) -> tuple[str, str]:
    """Return (front_matter, body). Empty front matter when there is none."""
    match = _FRONT.match(text)
    if not match:
        return "", text
    return match.group(1), text[match.end():]


def is_upstream(front: str) -> bool:
    return any(f"author: {a}" in front for a in _UPSTREAM_AUTHORS)


def check_skill(directory: Path) -> tuple[list[str], list[str]]:
    """Return (failures, upstream_notes) for one skill."""
    skill_md = directory / "SKILL.md"
    if not skill_md.is_file():
        return [], []

    text = skill_md.read_text(encoding="utf-8", errors="replace")
    front, body = front_matter(text)
    prompt = directory / "prompt.md"
    if prompt.is_file():
        body += "\n" + prompt.read_text(encoding="utf-8", errors="replace")
    for extra in sorted(directory.glob("references/*.md")):
        body += "\n" + extra.read_text(encoding="utf-8", errors="replace")

    failures: list[str] = []
    upstream: list[str] = []
    sink = upstream if is_upstream(front) else failures

    hint = _HINT.search(front)
    if hint:
        for flag in sorted(set(_FLAG.findall(hint.group(1)))):
            # The LITERAL `--flag` must appear. Accepting the bare word instead
            # was the first version, and it could not fire: flag names are
            # common English words, so `\ball\b` matched somewhere in every
            # prompt and /brief passed with its --all handling deleted. A gate
            # that cannot fail on the very case it was written for is the
            # defect this repository keeps finding in its own instruments.
            #
            # Prose describing the mode is not the same as a branch keyed on
            # the flag, which is what a reader typing it needs.
            if f"--{flag}" not in body:
                sink.append(
                    f"{directory.name}: argument-hint offers --{flag}, "
                    f"which appears nowhere in the body"
                )

    for rel in sorted(set(_PATH.findall(front))):
        if not (directory / rel).exists():
            sink.append(f"{directory.name}: front matter references {rel}, which does not exist")

    return failures, upstream


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--dir", type=Path, default=SKILLS)
    ap.add_argument("--self-test", action="store_true",
                    help="Ask this gate whether it can still go red.")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    if not args.dir.is_dir():
        print(f"no skills directory at {args.dir}")
        return 1

    failures: list[str] = []
    upstream: list[str] = []
    checked = 0
    for directory in sorted(args.dir.iterdir()):
        if not directory.is_dir():
            continue
        checked += 1
        f, u = check_skill(directory)
        failures.extend(f)
        upstream.extend(u)

    for note in upstream:
        print(f"  (upstream, not failed) {note}")

    if failures:
        print(f"check-skill-contracts: {len(failures)} skill(s) advertise what they do not do —")
        for line in failures:
            print(f"  {line}")
        print("\nEither wire the flag in the body, or remove it from argument-hint.")
        return 1

    print(
        f"check-skill-contracts: {checked} skills — every advertised flag is wired "
        f"and every referenced path resolves"
        + (f" ({len(upstream)} upstream note(s))" if upstream else "")
    )
    return 0


def self_test() -> int:
    """One positive and one negative control.

    This repository has now shipped three instruments that could not fire, so a
    new gate arrives with the question already answered.
    """
    import tempfile

    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        good = root / "good-skill"
        good.mkdir()
        (good / "SKILL.md").write_text(
            "---\nname: good-skill\nargument-hint: '[--wired]'\n---\n\nBody.\n",
            encoding="utf-8",
        )
        (good / "prompt.md").write_text("When --wired is passed, do the thing.\n", encoding="utf-8")

        bad = root / "bad-skill"
        bad.mkdir()
        (bad / "SKILL.md").write_text(
            "---\nname: bad-skill\nargument-hint: '[--phantom]'\n---\n\nBody.\n",
            encoding="utf-8",
        )
        (bad / "prompt.md").write_text("This workflow does one thing, always.\n", encoding="utf-8")

        missing = root / "missing-path"
        missing.mkdir()
        (missing / "SKILL.md").write_text(
            "---\nname: missing-path\ndescription: reads `references/gone.md`\n---\n\nBody.\n",
            encoding="utf-8",
        )

        good_f, _ = check_skill(good)
        bad_f, _ = check_skill(bad)
        missing_f, _ = check_skill(missing)

    if good_f:
        problems.append(f"negative control fired: a wired flag was reported ({good_f})")
    if not bad_f:
        problems.append("positive control did not fire: a phantom flag went unreported")
    if not missing_f:
        problems.append("positive control did not fire: a dangling path went unreported")

    if problems:
        for line in problems:
            print(f"SELF-TEST FAILED: {line}")
        return 1
    print(
        "SELF-TEST PASSED: the contract gate fires on a phantom flag and a "
        "dangling path, and stays quiet on a wired one."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
