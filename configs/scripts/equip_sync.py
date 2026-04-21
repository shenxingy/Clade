#!/usr/bin/env python3
"""equip_sync.py — Apply audit decisions to local skills.

Reads the most recent audit report for an upstream, parses decision checkboxes,
performs 3-way merge (base/ours/theirs), applies remediation transforms for
known red flags (NOI-01 marketing footer strip, DRF-01 retired model rename),
and writes changes.

Dry-run by default; `--apply` to write.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from equip_common import (
    Upstream,
    audits_dir,
    cache_dir,
    clone_or_update_cache,
    current_commit,
    detect_layout,
    detect_upstream_skills_dir,
    ensure_equipment_dir,
    file_hash,
    find_upstream,
    latest_tag,
    load_upstreams,
    save_upstreams,
    skills_root,
    tree_hash,
)


# ─── Remediation transforms (applied before write) ──────────────────────────

MODEL_ALIAS_REMAP = {
    "claude-3-opus-20240229": "claude-opus-4-7",
    "claude-3-sonnet-20240229": "claude-sonnet-4-6",
    "claude-3-5-sonnet-20241022": "claude-sonnet-4-6",
    "claude-2.1": "claude-opus-4-7",
    "claude-2.0": "claude-opus-4-7",
    "claude-instant-1.2": "claude-haiku-4-5-20251001",
}


# Patterns that begin a marketing footer block (strip from that line to EOF if matched late)
MARKETING_FOOTER_STARTS = [
    re.compile(r"(?i)^\s*#*\s*(Buy Pro|Join our community|AI Marketing Hub|Upgrade to Pro|Subscribe to)"),
    re.compile(r"(?i)^\s*#*\s*community CTA"),
]


def apply_remediations(content: str, flag_ids: set[str]) -> tuple[str, list[str]]:
    """Apply known remediations to content; return (new_content, applied_transforms)."""
    applied: list[str] = []
    new = content

    # DRF-01: retired model aliases
    if "DRF-01" in flag_ids:
        for old, new_alias in MODEL_ALIAS_REMAP.items():
            if old in new:
                new = new.replace(old, new_alias)
                applied.append(f"DRF-01: {old} → {new_alias}")

    # NOI-01: strip marketing footer (if it's in the last 30% of file)
    if "NOI-01" in flag_ids:
        lines = new.splitlines()
        threshold = int(len(lines) * 0.7)
        cut_at: Optional[int] = None
        for i, line in enumerate(lines):
            if i < threshold:
                continue
            for rx in MARKETING_FOOTER_STARTS:
                if rx.search(line):
                    cut_at = i
                    break
            if cut_at is not None:
                break
        if cut_at is not None:
            removed = len(lines) - cut_at
            lines = lines[:cut_at]
            # Trim trailing blanks
            while lines and lines[-1].strip() == "":
                lines.pop()
            new = "\n".join(lines) + "\n"
            applied.append(f"NOI-01: stripped {removed} trailing lines (marketing footer)")

    return new, applied


# ─── Audit report parser ────────────────────────────────────────────────────

SKILL_HEADER = re.compile(r"^###\s+\[([ xX])\]\s+`([^`]+)`")
FLAGS_IN_SECTION = re.compile(r"\*\*(SEC-\d+|NOI-\d+|DRF-\d+|BLT-\d+|QLT-\d+|LIC-\d+|DEP-\d+|OVR-\d+)\*\*")


def parse_audit_report(path: Path) -> list[tuple[str, bool, set[str]]]:
    """Return list of (skill_name, accepted, flag_ids).

    accepted = checkbox is [x] or [X].
    """
    if not path.is_file():
        return []
    out: list[tuple[str, bool, set[str]]] = []
    current_name: Optional[str] = None
    current_accepted = False
    current_flags: set[str] = set()
    for line in path.read_text().splitlines():
        m = SKILL_HEADER.match(line)
        if m:
            if current_name is not None:
                out.append((current_name, current_accepted, current_flags))
            current_name = m.group(2)
            current_accepted = m.group(1).strip().lower() == "x"
            current_flags = set()
            continue
        for fm in FLAGS_IN_SECTION.finditer(line):
            current_flags.add(fm.group(1))
    if current_name is not None:
        out.append((current_name, current_accepted, current_flags))
    return out


def find_latest_audit(project: Path, upstream_id: str) -> Optional[Path]:
    d = audits_dir(project)
    if not d.is_dir():
        return None
    candidates = sorted(d.glob(f"{upstream_id}-*.md"))
    return candidates[-1] if candidates else None


# ─── 3-way merge ────────────────────────────────────────────────────────────

def three_way_decision(
    base_hash: Optional[str],
    ours_hash: str,
    theirs_hash: str,
) -> str:
    """Return one of: 'identical', 'upstream-only', 'local-only', 'both-changed', 'new-upstream'."""
    if not ours_hash and theirs_hash:
        return "new-upstream"
    if ours_hash and not theirs_hash:
        return "deleted-upstream"
    if ours_hash == theirs_hash:
        return "identical"
    if base_hash is None:
        # No base recorded → assume both could be changed
        # But if ours != theirs and we have no base, treat conservatively as both-changed
        return "both-changed"
    if ours_hash == base_hash and theirs_hash != base_hash:
        return "upstream-only"
    if theirs_hash == base_hash and ours_hash != base_hash:
        return "local-only"
    return "both-changed"


# ─── Sync per skill ─────────────────────────────────────────────────────────

def sync_skill(
    skill_name: str,
    upstream_skill_dir: Path,
    local_skill_dir: Path,
    flag_ids: set[str],
    apply: bool,
    base_hashes: Optional[dict[str, str]] = None,
) -> dict:
    """Copy (with remediation) upstream_skill_dir → local_skill_dir.

    Returns a summary dict.
    """
    changes: list[str] = []
    remediations_applied: list[str] = []

    theirs_tree = tree_hash(upstream_skill_dir)
    ours_tree = tree_hash(local_skill_dir) if local_skill_dir.is_dir() else {}

    # Merge file-by-file
    all_paths = set(theirs_tree) | set(ours_tree)
    for rel in sorted(all_paths):
        ours_h = ours_tree.get(rel, "")
        theirs_h = theirs_tree.get(rel, "")
        base_h = base_hashes.get(rel) if base_hashes else None
        decision = three_way_decision(base_h, ours_h, theirs_h)

        theirs_path = upstream_skill_dir / rel
        ours_path = local_skill_dir / rel

        if decision == "identical":
            continue
        if decision == "local-only":
            changes.append(f"  = keep local: {rel}")
            continue
        if decision == "deleted-upstream":
            changes.append(f"  ? upstream deleted: {rel} (keeping local)")
            continue
        if decision == "both-changed":
            changes.append(f"  ! CONFLICT: {rel} (both changed — needs manual merge)")
            continue
        # upstream-only or new-upstream
        if not theirs_path.is_file():
            continue
        try:
            content = theirs_path.read_text(errors="replace")
        except Exception:
            content = ""
        new_content, applied = apply_remediations(content, flag_ids)
        remediations_applied.extend(applied)

        if apply:
            ours_path.parent.mkdir(parents=True, exist_ok=True)
            ours_path.write_text(new_content)
            changes.append(f"  + wrote: {rel}" + (f"  [{'; '.join(applied)}]" if applied else ""))
        else:
            changes.append(f"  + would write: {rel}" + (f"  [{'; '.join(applied)}]" if applied else ""))

    return {
        "skill": skill_name,
        "changes": changes,
        "remediations": remediations_applied,
    }


# ─── Main ───────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description="Apply audit decisions to local skills")
    p.add_argument("--project", type=Path, default=Path.cwd())
    p.add_argument("--upstream", type=str, required=True, help="Registered upstream id")
    p.add_argument("--apply", action="store_true", help="Actually write changes (default: dry-run)")
    p.add_argument("--diff-only", action="store_true", help="Show delta and exit, no sync")
    p.add_argument("--audit", type=Path, default=None,
                   help="Specific audit report path (default: latest for this upstream)")
    args = p.parse_args()

    project = args.project.resolve()
    ensure_equipment_dir(project)

    upstream = find_upstream(project, args.upstream)
    if not upstream:
        print(f"ERROR: upstream {args.upstream!r} not registered", file=sys.stderr)
        return 2

    cache_path = cache_dir(project) / upstream.id
    if not (cache_path / ".git").is_dir():
        print(f"Fetching {upstream.repo}...")
        clone_or_update_cache(project, upstream)

    upstream_skills = detect_upstream_skills_dir(cache_path)
    if not upstream_skills:
        print(f"ERROR: no skills dir in {upstream.repo}", file=sys.stderr)
        return 2

    local_root = skills_root(project)

    # --diff-only mode
    if args.diff_only:
        print(f"Diff: {upstream.repo} @ {current_commit(cache_path)[:7]} vs local")
        for skill_dir in sorted(upstream_skills.iterdir()):
            if not skill_dir.is_dir():
                continue
            local = local_root / skill_dir.name
            theirs = tree_hash(skill_dir)
            ours = tree_hash(local) if local.is_dir() else {}
            status = "NEW" if not ours else ("SAME" if ours == theirs else "DIFF")
            print(f"  {status:5s} {skill_dir.name}")
        return 0

    # Find audit report
    audit_path = args.audit or find_latest_audit(project, upstream.id)
    if not audit_path or not audit_path.is_file():
        print(f"ERROR: no audit report found for {upstream.id}. Run /equip audit first.", file=sys.stderr)
        return 2

    print(f"Audit report: {audit_path}")
    decisions = parse_audit_report(audit_path)
    accepted = [(n, flags) for n, a, flags in decisions if a]
    print(f"Decisions parsed: {len(decisions)} skills, {len(accepted)} accepted for sync")
    print()

    if not args.apply:
        print("[DRY RUN] — pass --apply to write changes")
        print()

    total_writes = 0
    summaries = []
    for name, flags in accepted:
        upstream_skill = upstream_skills / name
        if not upstream_skill.is_dir():
            print(f"  ! {name}: missing in upstream (deleted since audit?), skipping")
            continue
        local_skill = local_root / name
        summary = sync_skill(
            skill_name=name,
            upstream_skill_dir=upstream_skill,
            local_skill_dir=local_skill,
            flag_ids=flags,
            apply=args.apply,
            base_hashes=None,  # MVP: no base tracked yet — treat all deltas as upstream-forward
        )
        summaries.append(summary)
        print(f"Skill: {name}")
        for c in summary["changes"]:
            print(c)
        if summary["remediations"]:
            print(f"  ✓ remediations: {'; '.join(set(summary['remediations']))}")
        print()
        total_writes += sum(1 for c in summary["changes"] if c.strip().startswith("+"))

    if args.apply and accepted:
        # Update upstreams.yaml with new last_synced markers
        upstream.last_synced_commit = current_commit(cache_path)
        upstream.last_synced_version = latest_tag(cache_path)
        upstream.last_synced_at = datetime.now(timezone.utc).isoformat()
        ups = load_upstreams(project)
        ups = [u for u in ups if u.id != upstream.id] + [upstream]
        save_upstreams(project, ups)
        print(f"Updated last_synced: {upstream.last_synced_commit[:7]} ({upstream.last_synced_version or 'no-tag'})")

    print()
    print(f"Summary: {len(summaries)} skills processed, {total_writes} file writes {'(applied)' if args.apply else '(would apply)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
