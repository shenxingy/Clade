#!/usr/bin/env python3
"""
doc-align — Detect and fix doc drift against a single source of truth.

Universal Claude Code capability: works on any repo with `docs/facts.json`.
Silent no-op for repos that haven't opted in.

Usage:
  doc-align.py check                  # Report drift, exit non-zero if any
  doc-align.py apply                  # Rewrite drifting values in-place
  doc-align.py refresh                # Re-derive auto-derivable facts (counts from filesystem)
  doc-align.py sync                   # refresh + apply (one-shot)
  doc-align.py --root <dir> <mode>    # Operate on a specific repo
  doc-align.py --facts <path> <mode>  # Use non-default facts file

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
                    })
    return drifts


# ─── Commands ──────────────────────────────────────────────────────────
def cmd_check(facts: dict, repo_root: Path, fix: bool = False) -> int:
    drifts = find_drifts(facts, repo_root)
    if not drifts:
        print("doc-align: no drift detected ✓")
        return 0

    if fix:
        # group by file; apply edits in reverse-position order so offsets stay valid
        by_file = {}
        for d in drifts:
            by_file.setdefault(d["abs_path"], []).append(d)
        for path, ds in by_file.items():
            content = path.read_text(encoding="utf-8")
            ds.sort(key=lambda d: -d["group_start"])
            for d in ds:
                content = content[: d["group_start"]] + str(d["expected"]) + content[d["group_end"]:]
            path.write_text(content)
            print(f"doc-align: fixed {len(ds)} in {ds[0]['file']}")
        print(f"doc-align: applied {len(drifts)} fix(es) ✓")
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


def cmd_sync(facts: dict, facts_path: Path, repo_root: Path) -> int:
    cmd_refresh(facts, facts_path, repo_root)
    facts = load_facts(facts_path)  # reload after refresh
    return cmd_check(facts, repo_root, fix=True)


# ─── Entrypoint ────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="Doc drift checker against docs/facts.json")
    ap.add_argument("mode", choices=["check", "apply", "refresh", "sync"])
    ap.add_argument("--root", default=".", help="Repo root (default: cwd)")
    ap.add_argument("--facts", default="docs/facts.json", help="Path to facts file relative to --root")
    ap.add_argument("--quiet", action="store_true", help="Suppress 'no facts file' message")
    args = ap.parse_args()

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
    if args.mode == "apply":
        return cmd_check(facts, repo_root, fix=True)
    if args.mode == "refresh":
        return cmd_refresh(facts, facts_path, repo_root)
    if args.mode == "sync":
        return cmd_sync(facts, facts_path, repo_root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
