#!/usr/bin/env python3
"""Inventory every hand-typed measurement this repository asserts about itself.

Five audit rounds fixed individual numbers and the count would not fall, because
the mechanism was never named: a measurement gets written into prose once and
nothing ever re-derives it. A re-verification pass on 2026-09-14 put numbers to
that. Of the self-measurements checked, these did not survive:

  "~17% of checked commits"   no invocation reproduces it (19/29/29/33% by
                              sample size); the commit that introduced it is
                              docs-only with no run output
  "241 commits"               not reproducible under any git range tried
                              (256/231/188/258/227)
  "115 of the last 133"       unreproducible: "purely additive" was never
                              defined, and two readings give 75 and 82 of 133
  "~94k lines"                the population named in the same sentence
                              measures 138,115
  "~0.03% of the window"      wrong by roughly two orders of magnitude
  "100% recall / 7.1%"        true when written, ungated, and silently false
                              the moment the corpus or the detector changed

Only the last one had a mechanism available to catch it, and nothing used it.

This script does NOT check whether a number is right — it cannot, and pretending
otherwise is the failure it exists to expose. It reports WHICH self-measurements
are asserted and WHETHER anything derives them, so an underived one is a visible
choice rather than an accident. Report-only by default; --strict exits non-zero
when a NEW underived assertion appears (the baseline below shrinks, never grows).

Stdlib only: CI's syntax-check job installs no project dependencies.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", "dist", "build"}

# A self-measurement is a number this repository states ABOUT ITSELF. Third-party
# statistics (a vendor's benchmark, a cited paper) are somebody else's claim and
# are out of scope — hence the "here/this repo/our" proximity requirement.
SELF_SCOPE_RE = re.compile(
    r"\b(this repo(sitory)?|here|our own|in this tree|measured on this|of ours)\b", re.I
)

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("rate", re.compile(r"fires on (?:~|roughly |about )?(\d+(?:\.\d+)?)\s?%")),
    ("recall", re.compile(r"(\d+(?:\.\d+)?)\s?% recall")),
    ("false-alarms", re.compile(r"(\d+(?:\.\d+)?)\s?% false alarms?")),
    ("corpus-size", re.compile(r"\b(\d+)-case\b")),
    ("coverage", re.compile(r"\b(\d+(?:\.\d+)?)\s?% of (?:what|test-diff|checked)")),
    ("count-of-n", re.compile(r"\b(\d+) of (?:the last )?(\d+)\b")),
    ("multiple", re.compile(r"\b(\d+(?:\.\d+)?)x more\b")),
    ("loc", re.compile(r"\b(\d+(?:\.\d+)?)k[- ]line\b")),
    ("window-share", re.compile(r"\b(\d+(?:\.\d+)?)\s?% of the window\b")),
]

# Assertions known to be underived, each a deliberate standing choice rather than
# an oversight. This list SHRINKS. A new entry means either wiring a derivation
# or deleting the claim — not appending here.
BASELINE: set[tuple[str, str]] = {
    # (path, kind) — line numbers deliberately excluded: they churn.
    ("CHANGELOG.md", "count-of-n"),
    ("CHANGELOG.zh-CN.md", "count-of-n"),
    ("docs/research/2026-09-13-ai-legible-code-standards.md", "count-of-n"),
    ("docs/research/2026-09-13-ai-legible-code-standards.md", "coverage"),
    ("docs/research/2026-09-13-ai-legible-code-standards.md", "multiple"),
}

# What actually re-derives a number, and where. Everything else is a literal.
DERIVED_BY = {
    ("CLAUDE.md", "recall"): "orchestrator/tests/test_judge_diversity.py"
                             "::test_documented_detector_score_is_derived",
    ("CLAUDE.md", "false-alarms"): "orchestrator/tests/test_judge_diversity.py"
                                   "::test_documented_detector_score_is_derived",
    ("CLAUDE.md", "corpus-size"): "orchestrator/tests/test_judge_diversity.py"
                                  "::test_documented_detector_score_is_derived",
}


def iter_markdown(root: Path):
    for path in sorted(root.rglob("*.md")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def scan(root: Path) -> list[dict]:
    findings: list[dict] = []
    for path in iter_markdown(root):
        rel = str(path.relative_to(root))
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, 1):
            # Self-scope is judged over a small window: the claim and its
            # sentence often wrap, and "here" lands on the next line as often
            # as on this one.
            window = " ".join(lines[max(0, lineno - 3):lineno + 2])
            for kind, pattern in PATTERNS:
                match = pattern.search(line)
                if not match:
                    continue
                if kind in {"count-of-n", "multiple", "loc"} and not SELF_SCOPE_RE.search(window):
                    continue
                findings.append({
                    "file": rel,
                    "line": lineno,
                    "kind": kind,
                    "value": match.group(0).strip(),
                    "derived_by": DERIVED_BY.get((rel, kind)),
                    "text": line.strip()[:120],
                })
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on an underived assertion outside the baseline")
    ap.add_argument("--self-test", action="store_true",
                    help="prove this script can still report a finding")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    findings = scan(REPO)
    derived = [f for f in findings if f["derived_by"]]
    undederived = [f for f in findings if not f["derived_by"]]
    new = [f for f in undederived if (f["file"], f["kind"]) not in BASELINE]

    if args.json:
        print(json.dumps({
            "total": len(findings),
            "derived": len(derived),
            "underived": len(undederived),
            "new": new,
            "findings": findings,
        }, indent=2))
    else:
        print(f"self-measurements asserted in prose: {len(findings)}")
        print(f"  derived by something            : {len(derived)}")
        print(f"  underived                       : {len(undederived)}"
              f" ({len(BASELINE)} baselined, {len(new)} new)")
        for f in derived:
            print(f"  ok   {f['file']}:{f['line']}  {f['kind']}={f['value']}"
                  f"  <- {f['derived_by']}")
        for f in undederived:
            mark = "NEW " if (f["file"], f["kind"]) not in BASELINE else "base"
            print(f"  {mark} {f['file']}:{f['line']}  {f['kind']}={f['value']}")
            print(f"        {f['text']}")
        if new:
            print("\nA new underived self-measurement is a choice to make explicit:")
            print("  derive it, delete it, or add it to BASELINE with a reason.")

    return 1 if (args.strict and new) else 0


def self_test() -> int:
    """One positive and one negative control, on a throwaway tree.

    The whole point of this script is that an instrument reporting a clean zero
    and an instrument that cannot fire look identical.
    """
    import tempfile

    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "docs").mkdir()

        # NEGATIVE control: a third-party statistic must NOT be reported.
        (root / "docs" / "vendor.md").write_text(
            "Their benchmark shows 2.3x more verbose output than the baseline.\n",
            encoding="utf-8",
        )
        found = scan(root)
        if found:
            failures.append(f"negative control fired on a third-party number: {found}")

        # POSITIVE control: the same shape, scoped to this repo, must be reported.
        (root / "docs" / "ours.md").write_text(
            "Agent code in this repository is 2.3x more verbose than ours was.\n",
            encoding="utf-8",
        )
        found = scan(root)
        if not any(f["kind"] == "multiple" for f in found):
            failures.append(f"positive control did not fire: {found}")

        # POSITIVE control 2: a rate claim, which needs no self-scope window.
        (root / "docs" / "rate.md").write_text("It fires on ~17% of commits.\n",
                                               encoding="utf-8")
        found = scan(root)
        if not any(f["kind"] == "rate" for f in found):
            failures.append(f"rate control did not fire: {found}")

    if failures:
        for f in failures:
            print(f"SELF-TEST FAILED: {f}")
        return 1
    print("SELF-TEST PASSED: negative control silent, both positive controls fired")
    return 0


if __name__ == "__main__":
    sys.exit(main())
