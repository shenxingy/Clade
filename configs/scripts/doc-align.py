#!/usr/bin/env python3
"""
doc-align — Detect and fix doc drift against a single source of truth.

Universal Claude Code capability: works on any repo with `docs/facts.json`.
Silent no-op for repos that haven't opted in.

Usage:
  doc-align.py check                  # Report drift, exit non-zero if any
  doc-align.py apply                  # Rewrite drifting values in-place
  doc-align.py verify                 # Check derived facts + doc references without writing
  doc-align.py refresh                # Re-derive auto-derivable facts (counts from filesystem)
  doc-align.py sync                   # refresh + apply (one-shot)
  doc-align.py --root <dir> <mode>    # Operate on a specific repo
  doc-align.py --facts <path> <mode>  # Use non-default facts file
  doc-align.py --self-test            # Run the built-in fixtures (can the dated-row report fire?)

apply and sync never change a date. A value they rewrite on a line that
carries a YYYY-MM-DD (a dated VERIFY.md row) is reported after the fixes as
"re-verify, then update its date": the row records a check made that day, and
the tool did not run it. Report-only; the exit code is unchanged.

Schema (docs/facts.json):
  {
    "facts": [
      {
        "name": "skills",
        "value": 103,
        "derive": {"type": "count_glob", "pattern": "configs/skills/*/"},
        "patterns": [
          "^## Skills\\s*\\((\\d+)\\)",
          "^(\\d+) skills,"
        ]
      }
    ]
  }

Each `pattern` must contain exactly ONE capture group — the value to compare
against `value`. Patterns are matched with re.MULTILINE.

Derive types (V1):
  count_glob   — len(glob.glob(<root>/<pattern>))

If `derive` is omitted, the fact is manually maintained (e.g. pricing).
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path

EXCLUDE_DIRS = {"node_modules", "__pycache__", ".venv", ".git", "dist", "build", "target"}

# A row that carries a date records a check made on that day. On 2026-10-23 a
# sync rewrote the hook count in VERIFY.md H6/SH1 to 35 under a 2026-07-13
# date, a day the 33rd hook did not exist. The tool never bumps the date (it
# would date a check it never ran); apply/sync name the row instead.
DATE_RE = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")


# ─── Facts file I/O ────────────────────────────────────────────────────
def load_facts(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_facts(path: Path, facts: dict) -> None:
    path.write_text(json.dumps(facts, indent=2) + "\n")


# ─── Derive engine (safe primitives only — no shell injection) ─────────
def derive_value(spec: dict, repo_root: Path):
    kind = spec.get("type")
    if kind == "count_glob":
        pattern = spec.get("pattern", "")
        # glob.glob expects a string path
        return len(glob.glob(str(repo_root / pattern), recursive=True))
    # Future: count_lines, file_exists, http_get_json, etc.
    return None


# ─── Markdown discovery ────────────────────────────────────────────────
def find_md(root: Path):
    for p in root.rglob("*.md"):
        # skip hidden dirs and well-known noise
        bad = False
        for seg in p.parts:
            if seg in EXCLUDE_DIRS or (seg.startswith(".") and seg not in (".",)):
                bad = True
                break
        if not bad:
            yield p


# ─── Drift detection ───────────────────────────────────────────────────
def find_drifts(facts: dict, repo_root: Path):
    drifts = []
    md_files = list(find_md(repo_root))
    for fact in facts.get("facts", []):
        expected = fact["value"]
        for pat in fact.get("patterns", []):
            try:
                rx = re.compile(pat, re.MULTILINE)
            except re.error as e:
                print(f"warn: bad pattern '{pat}' for fact '{fact['name']}': {e}", file=sys.stderr)
                continue
            for md in md_files:
                try:
                    content = md.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                for m in rx.finditer(content):
                    if not m.lastindex:
                        continue
                    found = m.group(1)
                    try:
                        eq = int(found) == int(expected)
                    except (ValueError, TypeError):
                        eq = str(found) == str(expected)
                    if eq:
                        continue
                    # The row is the line holding the VALUE (a pattern may
                    # start a line earlier); the value itself is blanked so a
                    # date-valued fact does not count as its own row's date.
                    row_start = content.rfind("\n", 0, m.start(1)) + 1
                    row_end = content.find("\n", m.end(1))
                    row_end = len(content) if row_end == -1 else row_end
                    around = content[row_start:m.start(1)] + " " + content[m.end(1):row_end]
                    drifts.append({
                        "file": str(md.relative_to(repo_root)),
                        "abs_path": md,
                        "fact": fact["name"],
                        "expected": expected,
                        "found": found,
                        "line": content[:m.start()].count("\n") + 1,
                        "match_text": m.group(0).strip(),
                        "group_start": m.start(1),
                        "group_end": m.end(1),
                        "pattern": pat,
                        "row_line": content.count("\n", 0, m.start(1)) + 1,
                        "dated": bool(DATE_RE.search(around)),
                    })
    return drifts


def dated_rows(ds: list, content: str) -> list[tuple[str, int, str]]:
    """The rows of one rewritten file that carry a date, once each, in file order."""
    lines = content.split("\n")
    seen: set[int] = set()
    rows = []
    for d in sorted(ds, key=lambda d: d["row_line"]):
        if not d["dated"] or d["row_line"] in seen:
            continue
        seen.add(d["row_line"])
        rows.append((d["file"], d["row_line"], lines[d["row_line"] - 1].strip()))
    return rows


# ─── Commands ──────────────────────────────────────────────────────────
def cmd_check(facts: dict, repo_root: Path, fix: bool = False) -> int:
    drifts = find_drifts(facts, repo_root)
    if not drifts:
        print("doc-align: no drift detected ✓")
        return 0

    if fix:
        # group by file; apply edits in reverse-position order so offsets stay valid
        by_file: dict[Path, list] = {}
        for d in drifts:
            by_file.setdefault(d["abs_path"], []).append(d)
        dated: list[tuple[str, int, str]] = []
        for path, ds in by_file.items():
            content = path.read_text(encoding="utf-8")
            ds.sort(key=lambda d: -d["group_start"])
            for d in ds:
                content = content[: d["group_start"]] + str(d["expected"]) + content[d["group_end"]:]
            path.write_text(content)
            print(f"doc-align: fixed {len(ds)} in {ds[0]['file']}")
            dated.extend(dated_rows(ds, content))
        print(f"doc-align: applied {len(drifts)} fix(es) ✓")
        if dated:
            # Report-only: the fix stands and the exit stays 0. The date is the
            # owner's to move, after re-running the check the row records.
            print(f"doc-align: {len(dated)} rewritten row(s) carry a date this run did not check "
                  f"— re-verify, then update its date:")
            for file, line, row in dated:
                print(f"  {file}:{line}  {row}")
        return 0

    print(f"doc-align: {len(drifts)} drift(s):")
    for d in drifts:
        print(f"  {d['file']}:{d['line']}  {d['fact']}={d['expected']} "
              f"but found {d['found']!r} in: {d['match_text']!r}")
    return 1


def cmd_refresh(facts: dict, facts_path: Path, repo_root: Path) -> int:
    changed = 0
    for fact in facts.get("facts", []):
        spec = fact.get("derive")
        if not spec:
            continue
        new_val = derive_value(spec, repo_root)
        if new_val is None:
            continue
        old_val = fact.get("value")
        if new_val != old_val:
            print(f"doc-align: {fact['name']}: {old_val} → {new_val}")
            fact["value"] = new_val
            changed += 1
    if changed:
        save_facts(facts_path, facts)
        print(f"doc-align: refreshed {changed} fact(s) in {facts_path.name}")
    else:
        print("doc-align: facts up to date")
    return 0


def cmd_verify(facts: dict, repo_root: Path) -> int:
    stale = []
    for fact in facts.get("facts", []):
        spec = fact.get("derive")
        if not spec:
            continue
        derived = derive_value(spec, repo_root)
        if derived is not None and derived != fact.get("value"):
            stale.append((fact["name"], fact.get("value"), derived))

    if stale:
        print(f"doc-align: {len(stale)} stale derived fact(s):")
        for name, recorded, derived in stale:
            print(f"  {name}: recorded={recorded!r}, derived={derived!r}")

    drift_result = cmd_check(facts, repo_root, fix=False)
    return 1 if stale or drift_result else 0


def cmd_sync(facts: dict, facts_path: Path, repo_root: Path) -> int:
    cmd_refresh(facts, facts_path, repo_root)
    facts = load_facts(facts_path)  # reload after refresh
    return cmd_check(facts, repo_root, fix=True)


# ─── Self-test ─────────────────────────────────────────────────────────
def _run(argv: list[str]) -> tuple[int, str]:
    """main() as the CLI runs it, with its stdout captured."""
    import contextlib
    import io

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(argv)
    return code, out.getvalue()


def _fixture(root: Path, facts: list, doc: str, hooks: int = 0) -> Path:
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "facts.json").write_text(json.dumps({"facts": facts}), encoding="utf-8")
    (root / "hooks").mkdir()
    for i in range(hooks):
        (root / "hooks" / f"h{i}.sh").write_text("", encoding="utf-8")
    (root / "VERIFY.md").write_text(doc, encoding="utf-8")
    return root / "VERIFY.md"


def _listed(out: str) -> list[int]:
    return [int(m.group(1)) for m in re.finditer(r"^  VERIFY\.md:(\d+)  ", out, re.M)]


def self_test() -> int:
    """Drive main() on fixture repos: a fix that lands in a dated row names that row, once; nothing else does."""
    import tempfile

    problems: list[str] = []
    hooks = {"name": "hooks", "value": 2, "derive": {"type": "count_glob", "pattern": "hooks/*.sh"},
             "patterns": ["all (\\d+) hooks pass", "^Hook count\\s+(\\d+)"]}
    release = {"name": "release", "value": "2026-11-20", "patterns": ["released (\\d{4}-\\d{2}-\\d{2})"]}
    doc = (
        "| H6 | hooks pass `bash -n` | ok | 2026-07-13 | all 2 hooks pass |\n"  # 1 dated, rewritten
        "Undated prose: all 2 hooks pass.\n"                                    # 2 rewritten, no date
        "| H7 | already right | ok | 2026-07-14 | all 3 hooks pass |\n"       # 3 dated, not rewritten
        "| H8 | 2026-08-01 | all 2 hooks pass, and all 2 hooks pass |\n"        # 4 dated, two fixes in one row
        "We released 2026-11-01 to users.\n"                                    # 5 its only date is the value
        "Hook count\n"                                                          # 6 the match starts here,
        "2 (as of 2026-07-01)\n"                                                # 7 the value and date are here
        "Build 12026-07-130: all 2 hooks pass\n"                                # 8 digits, not a date
        "| 2026-07-13T10:00Z | all 2 hooks pass |\n"                            # 9 a timestamp is a date
    )
    with tempfile.TemporaryDirectory() as tmp:
        # sync: refresh derives 3 hooks, then every drift is rewritten.
        md = _fixture(Path(tmp) / "sync", [hooks, release], doc, hooks=3)
        code, out = _run(["sync", "--root", str(md.parent)])
        lines = md.read_text(encoding="utf-8").split("\n")
        if code != 0:
            problems.append(f"sync exited {code}; the dated-row report is report-only\n{out}")
        if lines[0] != "| H6 | hooks pass `bash -n` | ok | 2026-07-13 | all 3 hooks pass |":
            problems.append(f"sync did not rewrite the count under an unchanged date: {lines[0]!r}")
        if "re-verify, then update its date" not in out:
            problems.append(f"sync rewrote dated rows and did not say re-verify, then update its date\n{out}")
        if _listed(out) != [1, 4, 7, 9]:
            problems.append(f"sync named rows {_listed(out)}, want [1, 4, 7, 9]: dated and rewritten, once "
                            f"each, on the line holding the value; not the undated rows 2 and 8, the "
                            f"untouched row 3 or row 5, whose only date is the value\n{out}")
        if f"  VERIFY.md:1  {lines[0]}" not in out:
            problems.append(f"sync did not print row 1 as it now reads\n{out}")

        # apply, the other mode that writes: same report.
        md = _fixture(Path(tmp) / "apply", [dict(hooks, value=3)], doc.split("\n")[0] + "\n")
        code, out = _run(["apply", "--root", str(md.parent)])
        if code != 0 or _listed(out) != [1] or "re-verify, then update its date" not in out:
            problems.append(f"apply rewrote a dated row and did not name it (exit {code})\n{out}")

        # Nothing dated was rewritten: no report at all.
        md = _fixture(Path(tmp) / "undated", [dict(hooks, value=3)], "Undated prose: all 2 hooks pass.\n")
        code, out = _run(["apply", "--root", str(md.parent)])
        if code != 0 or "all 3 hooks pass" not in md.read_text(encoding="utf-8"):
            problems.append(f"apply did not rewrite an undated row (exit {code})\n{out}")
        if "re-verify" in out:
            problems.append(f"apply printed the dated-row report with no dated row rewritten\n{out}")

    if problems:
        for line in problems:
            print(f"SELF-TEST FAILED: {line}")
        return 1
    print("SELF-TEST PASSED: sync and apply rewrite a count under an unchanged date and name each dated row "
          "they rewrote, once, on the line holding the value; an undated row, an untouched dated row and a "
          "date that is itself the value are not named, and a run with no dated rewrite prints no report.")
    return 0


# ─── Entrypoint ────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Doc drift checker against docs/facts.json")
    ap.add_argument("mode", nargs="?", choices=["check", "verify", "apply", "refresh", "sync"])
    ap.add_argument("--root", default=".", help="Repo root (default: cwd)")
    ap.add_argument("--facts", default="docs/facts.json", help="Path to facts file relative to --root")
    ap.add_argument("--quiet", action="store_true", help="Suppress 'no facts file' message")
    ap.add_argument("--self-test", action="store_true", help="Run the built-in fixtures and exit")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    if args.mode is None:
        ap.error("a mode is required")

    repo_root = Path(args.root).resolve()
    facts_path = (repo_root / args.facts).resolve()
    if not facts_path.exists():
        if not args.quiet:
            print(f"doc-align: no {args.facts} at {repo_root} (silent no-op)", file=sys.stderr)
        return 0

    facts = load_facts(facts_path)
    if not facts or not facts.get("facts"):
        return 0

    if args.mode == "check":
        return cmd_check(facts, repo_root, fix=False)
    if args.mode == "verify":
        return cmd_verify(facts, repo_root)
    if args.mode == "apply":
        return cmd_check(facts, repo_root, fix=True)
    if args.mode == "refresh":
        return cmd_refresh(facts, facts_path, repo_root)
    if args.mode == "sync":
        return cmd_sync(facts, facts_path, repo_root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
