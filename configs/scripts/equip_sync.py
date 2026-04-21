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
    run,
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


# ─── Path mapping ───────────────────────────────────────────────────────────

# Files we never sync (per-skill license spam, upstream-only CI crud)
SKIP_FILES = {"LICENSE.txt", "LICENSE", "LICENSE.md", ".gitkeep"}


def map_upstream_to_local_path(rel: str, local_is_split: bool) -> Optional[str]:
    """Map an upstream file path to where it should land locally.

    If local uses split layout (SKILL.md + prompt.md) and upstream is single-file,
    upstream's SKILL.md body is what Clade calls prompt.md. Don't overwrite local
    SKILL.md (it has Clade-specific frontmatter: user_invocable, when_to_use).

    Returns None to skip the file.
    """
    base = rel
    parts = rel.split("/", 1)
    if local_is_split:
        if rel == "SKILL.md":
            # upstream SKILL.md = full body → local prompt.md
            return "prompt.md"
        if parts[0] in SKIP_FILES or rel in SKIP_FILES:
            return None
    if base in SKIP_FILES or Path(base).name in SKIP_FILES:
        return None
    return rel


# ─── Base (v1.8.2) tree loading ─────────────────────────────────────────────

def load_upstream_base_hashes(cache_path: Path, base_ref: str, skill_name: str) -> dict[str, str]:
    """Load {rel_path: git_blob_sha} for skills/<skill_name>/ at base_ref.

    Used to do a real 3-way merge: if local prompt.md hash == upstream v1.8.2
    SKILL.md hash, then local is unmodified vs absorption baseline → safe to adopt.
    """
    try:
        r = run(
            ["git", "ls-tree", "-r", f"{base_ref}:skills/{skill_name}"],
            cwd=cache_path,
            check=False,
        )
    except Exception:
        return {}
    if r.returncode != 0:
        return {}
    out: dict[str, str] = {}
    for line in r.stdout.splitlines():
        # Format: "100644 blob <sha>\t<path>"
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        meta = parts[0].split()
        if len(meta) < 3 or meta[1] != "blob":
            continue
        out[parts[1]] = meta[2]
    return out


def git_blob_hash_of_file(path: Path) -> str:
    """Compute git blob SHA (matches what git ls-tree returns) for a local file."""
    if not path.is_file():
        return ""
    try:
        r = run(["git", "hash-object", str(path)], check=False)
        return r.stdout.strip()
    except Exception:
        return ""


# ─── Sync per skill ─────────────────────────────────────────────────────────

def sync_skill(
    skill_name: str,
    upstream_skill_dir: Path,
    local_skill_dir: Path,
    flag_ids: set[str],
    apply: bool,
    base_blob_hashes: Optional[dict[str, str]] = None,
    cache_path: Optional[Path] = None,
) -> dict:
    """Copy (with layout transform + remediation) upstream → local.

    Smart mode (default):
    - Map upstream SKILL.md → local prompt.md when local uses split layout
    - Skip LICENSE.txt
    - Use v1.8.2 git blob hashes as base; if local == base, safe to overwrite
    - Apply NOI-01 / DRF-01 auto-remediations

    Returns summary dict.
    """
    changes: list[str] = []
    remediations_applied: list[str] = []

    local_is_split = (
        (local_skill_dir / "SKILL.md").is_file()
        and (local_skill_dir / "prompt.md").is_file()
    )

    theirs_tree = tree_hash(upstream_skill_dir)

    for rel, theirs_content_hash in sorted(theirs_tree.items()):
        local_rel = map_upstream_to_local_path(rel, local_is_split)
        if local_rel is None:
            changes.append(f"  - skip: {rel}")
            continue

        theirs_path = upstream_skill_dir / rel
        ours_path = local_skill_dir / local_rel

        if not theirs_path.is_file():
            continue

        # 3-way check when we have a base and local file exists
        base_blob = base_blob_hashes.get(rel) if base_blob_hashes else None
        ours_blob = git_blob_hash_of_file(ours_path) if ours_path.is_file() else ""
        theirs_blob = git_blob_hash_of_file(theirs_path)

        if ours_blob and theirs_blob and ours_blob == theirs_blob:
            # Already identical (after layout mapping)
            continue

        try:
            content = theirs_path.read_text(errors="replace")
        except Exception:
            content = ""

        # Apply auto-remediations
        new_content, applied = apply_remediations(content, flag_ids)
        remediations_applied.extend(applied)

        # Decision:
        # - If base exists and ours == base → pure version drift, safe upgrade
        # - If base exists and ours != base → local has customization; keep ours
        # - If no base (first sync / new file) → take theirs
        decision_note = ""
        if ours_blob and base_blob:
            if ours_blob == base_blob:
                decision_note = "version-drift"
            else:
                # Real local customization — skip to preserve it
                changes.append(f"  = keep local (customized): {local_rel}")
                continue
        elif not ours_blob:
            decision_note = "new"
        else:
            # No base available — fall back to overwriting (first-time smart sync)
            decision_note = "no-base"

        if apply:
            ours_path.parent.mkdir(parents=True, exist_ok=True)
            ours_path.write_text(new_content)
            tag = f"  [{decision_note}" + (f"; {'; '.join(applied)}" if applied else "") + "]"
            changes.append(f"  + wrote: {local_rel}{tag}")
        else:
            tag = f"  [{decision_note}" + (f"; {'; '.join(applied)}" if applied else "") + "]"
            changes.append(f"  + would write: {local_rel}{tag}")

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
    p.add_argument("--base-ref", type=str, default=None,
                   help="Upstream git ref to use as 3-way merge base (e.g., v1.8.2). "
                        "If set, files that locally match this base are treated as "
                        "pure version drift and safely overwritten.")
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

    base_ref = args.base_ref
    if base_ref:
        print(f"Using base ref {base_ref} for 3-way merge")

    total_writes = 0
    summaries = []
    for name, flags in accepted:
        upstream_skill = upstream_skills / name
        if not upstream_skill.is_dir():
            print(f"  ! {name}: missing in upstream (deleted since audit?), skipping")
            continue
        local_skill = local_root / name
        base_blob_hashes = None
        if base_ref:
            base_blob_hashes = load_upstream_base_hashes(cache_path, base_ref, name)
        summary = sync_skill(
            skill_name=name,
            upstream_skill_dir=upstream_skill,
            local_skill_dir=local_skill,
            flag_ids=flags,
            apply=args.apply,
            base_blob_hashes=base_blob_hashes,
            cache_path=cache_path,
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
