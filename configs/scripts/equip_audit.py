#!/usr/bin/env python3
"""equip_audit.py — Intelligent review of an upstream (or self).

For each skill in the target, runs red-flag checks from audit-criteria.md and
produces a markdown audit report with per-skill ADOPT/NEEDS-REVIEW/SKIP decisions.

Usage:
  equip_audit.py --project <path> --target <owner/repo|id|.>
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
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
)


# ─── Red flag patterns (mirror references/audit-criteria.md) ────────────────

@dataclass
class Flag:
    id: str
    severity: str       # "block" | "warn" | "info"
    line: Optional[int]
    snippet: str
    remediation: str


PATTERNS: list[tuple[str, str, str, re.Pattern[str], str]] = [
    # (id, severity, category, compiled pattern, remediation)
    ("SEC-01", "block", "security", re.compile(r"\beval\s*\("), "Remove eval()"),
    ("SEC-02", "block", "security",
     re.compile(r"\bcurl\s+[^|\n]*\|\s*(bash|sh)\b"),
     "Replace curl|bash with download+verify+execute"),
    ("SEC-03", "block", "security",
     re.compile(r"""(api_key|secret|token|password)\s*[:=]\s*["'][A-Za-z0-9_\-]{20,}""", re.IGNORECASE),
     "Hardcoded credential — reject or move to env var"),
    ("SEC-05", "block", "security",
     re.compile(r"^\s*sudo\s+", re.MULTILINE),
     "Skills should never require sudo"),
    ("NOI-01", "warn", "noise",
     re.compile(r"\b(Buy Pro|Join (our )?community|AI Marketing Hub|Upgrade to Pro|Subscribe to )", re.IGNORECASE),
     "Strip marketing footer/CTA before adopting"),
    ("NOI-02", "warn", "noise",
     re.compile(r"[?&](utm_source|ref|affiliate|partnerid)=", re.IGNORECASE),
     "Strip tracking/affiliate params"),
    ("DRF-01", "warn", "drift",
     re.compile(r"\b(claude-3-opus-20240229|claude-3-sonnet-20240229|claude-2\.[01]|claude-instant-1\.\d+)\b"),
     "Rewrite retired model alias → current (see ~/.claude/models.env)"),
    ("DRF-02", "warn", "drift",
     re.compile(r"anthropic-version:\s*2023-", re.IGNORECASE),
     "Bump anthropic-version to 2024-10-22 or later"),
    ("DRF-03", "block", "drift",
     re.compile(r"/v1/complete\b"),
     "Rewrite deprecated /v1/complete to /v1/messages"),
]


def scan_text_for_flags(text: str) -> list[Flag]:
    """Scan a prompt/script for all defined red-flag patterns."""
    flags: list[Flag] = []
    for flag_id, severity, _cat, rx, remediation in PATTERNS:
        for m in rx.finditer(text):
            # Compute line number
            line = text.count("\n", 0, m.start()) + 1
            snippet = text[max(0, m.start() - 10):m.end() + 30].replace("\n", "\\n")
            flags.append(Flag(
                id=flag_id,
                severity=severity,
                line=line,
                snippet=snippet.strip()[:120],
                remediation=remediation,
            ))
    return flags


def check_bloat(path: Path, flags: list[Flag]) -> None:
    if not path.is_file():
        return
    try:
        lines = path.read_text(errors="replace").count("\n")
    except Exception:
        return
    if lines > 1500:
        flags.append(Flag(id="BLT-02", severity="warn", line=None,
                          snippet=f"{lines} lines",
                          remediation="Exceeds 1-shot Read limit — split into files"))
    elif lines > 500:
        flags.append(Flag(id="BLT-01", severity="info", line=None,
                          snippet=f"{lines} lines",
                          remediation="Verbose prompt — human review"))


def check_quality(skill_dir: Path, flags: list[Flag]) -> None:
    """Quality signals that aren't regex-based."""
    prompt = skill_dir / "prompt.md"
    skill_md = skill_dir / "SKILL.md"
    if prompt.is_file():
        content = prompt.read_text(errors="replace")
        if content.strip().count("\n") < 20:
            flags.append(Flag(id="QLT-02", severity="info", line=None,
                              snippet=f"{content.count(chr(10))} lines",
                              remediation="Trivial prompt — confirm this skill is worth adopting"))
    if not (skill_dir / "references").is_dir():
        flags.append(Flag(id="QLT-01", severity="info", line=None,
                          snippet="", remediation="No references/ dir — less RAG coverage"))
    if skill_md.is_file():
        front = skill_md.read_text(errors="replace")
        required = ["name:", "description:"]
        missing = [r for r in required if r not in front]
        if missing:
            flags.append(Flag(id="QLT-03", severity="warn", line=None,
                              snippet=", ".join(missing),
                              remediation="SKILL.md missing required frontmatter"))


# ─── Per-skill audit ────────────────────────────────────────────────────────

@dataclass
class SkillAudit:
    name: str
    path: str
    flags: list[Flag] = field(default_factory=list)
    local_exists: bool = False
    local_modified: bool = False
    decision: str = "ADOPT"
    score: float = 10.0

    def compute_decision(self, overlap_native: bool) -> None:
        blocks = [f for f in self.flags if f.severity == "block"]
        warns = [f for f in self.flags if f.severity == "warn"]

        # Hard-skip on viral-license or credential leak
        if any(f.id == "SEC-03" for f in blocks):
            self.decision = "SKIP"
        elif overlap_native:
            # Conflicts with a native skill — default skip
            self.decision = "SKIP"
        elif blocks:
            self.decision = "NEEDS-REVIEW"
        elif len(warns) >= 3:
            self.decision = "NEEDS-REVIEW"
        elif warns:
            self.decision = "ADOPT"    # ADOPT with remediation notes
        else:
            self.decision = "ADOPT"

        self.score = max(0.0, 10.0 - 2.0 * len(blocks) - 1.0 * len(warns))


def audit_skill(skill_dir: Path, local_skill_dir: Optional[Path]) -> SkillAudit:
    a = SkillAudit(name=skill_dir.name, path=str(skill_dir))
    # Scan all text files for patterns
    for tf in list(skill_dir.rglob("*.md")) + list(skill_dir.rglob("*.sh")) + list(skill_dir.rglob("*.py")):
        if not tf.is_file():
            continue
        try:
            text = tf.read_text(errors="replace")
        except Exception:
            continue
        a.flags.extend(scan_text_for_flags(text))
    # Bloat check on main prompt
    check_bloat(skill_dir / "prompt.md", a.flags)
    # Quality heuristics
    check_quality(skill_dir, a.flags)
    # Overlap with local
    if local_skill_dir and local_skill_dir.is_dir():
        a.local_exists = True
        # Check if local differs from upstream
        from equip_scan import combined_hash
        if combined_hash(local_skill_dir) != combined_hash(skill_dir):
            a.local_modified = True
    return a


# ─── Report writing ─────────────────────────────────────────────────────────

def format_flag_line(f: Flag) -> str:
    sev_icon = {"block": "🛑", "warn": "⚠️ ", "info": "ℹ️ "}.get(f.severity, "•")
    line_str = f" (L{f.line})" if f.line else ""
    return f"  - {sev_icon} **{f.id}**{line_str}: {f.remediation}" + (f"\n    `{f.snippet}`" if f.snippet else "")


def decision_icon(d: str) -> str:
    return {"ADOPT": "[x]", "NEEDS-REVIEW": "[ ]", "SKIP": "[ ]"}.get(d, "[ ]")


def build_report(
    upstream_id: str,
    upstream_repo: str,
    upstream_ref: str,
    upstream_version: Optional[str],
    audits: list[SkillAudit],
    native_names: set[str],
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    adopt = [a for a in audits if a.decision == "ADOPT"]
    review = [a for a in audits if a.decision == "NEEDS-REVIEW"]
    skip = [a for a in audits if a.decision == "SKIP"]

    lines = []
    lines.append(f"# Equip Audit: {upstream_repo}")
    lines.append("")
    lines.append(f"- **Audited:** {now}")
    lines.append(f"- **Ref:** `{upstream_ref}`" + (f" (tag {upstream_version})" if upstream_version else ""))
    lines.append(f"- **Skills evaluated:** {len(audits)}")
    lines.append(f"- **Decisions:** {len(adopt)} ADOPT · {len(review)} NEEDS-REVIEW · {len(skip)} SKIP")
    lines.append("")
    lines.append("## How to use this report")
    lines.append("")
    lines.append("Each skill below has a checkbox. **`[x]` = approve for sync, `[ ]` = skip.**")
    lines.append("Edit this file to change any decision, then run:")
    lines.append(f"  `/equip sync {upstream_id} --apply`")
    lines.append("")

    def section(title: str, items: list[SkillAudit]) -> None:
        if not items:
            return
        lines.append(f"## {title} ({len(items)})")
        lines.append("")
        for a in items:
            marker = decision_icon(a.decision)
            mod_tag = " [MODIFIED-LOCALLY]" if a.local_modified else ""
            native_tag = " [OVERLAPS-NATIVE]" if a.name in native_names else ""
            lines.append(f"### {marker} `{a.name}`  — score {a.score:.1f}/10{mod_tag}{native_tag}")
            if a.flags:
                lines.append("")
                lines.append("**Flags:**")
                for f in a.flags:
                    lines.append(format_flag_line(f))
            else:
                lines.append("")
                lines.append("**Flags:** none — clean.")
            lines.append("")
        lines.append("")

    section("ADOPT (safe, or adopt with auto-remediation)", adopt)
    section("NEEDS-REVIEW (block-severity flags or ≥3 warnings — human decision required)", review)
    section("SKIP (defaults — flip to `[x]` to override)", skip)

    return "\n".join(lines)


# ─── Main ───────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description="Audit an upstream (or self) for adoption")
    p.add_argument("--project", type=Path, default=Path.cwd())
    p.add_argument("--target", type=str, required=True,
                   help="owner/repo, registered id, or '.' for self-audit")
    args = p.parse_args()

    project = args.project.resolve()
    ensure_equipment_dir(project)

    target = args.target
    upstream: Optional[Upstream] = None
    audit_root: Path
    upstream_id: str
    upstream_repo: str
    upstream_ref: str

    # Self-audit
    if target == ".":
        upstream_id = "self"
        upstream_repo = f"(local project {project.name})"
        try:
            upstream_ref = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=project, capture_output=True, text=True
            ).stdout.strip()[:7] or "workdir"
        except Exception:
            upstream_ref = "workdir"
        audit_root = skills_root(project)
        upstream_version = None
    else:
        # Is it a registered id, or a new repo?
        upstream = find_upstream(project, target)
        if not upstream:
            if "/" not in target:
                print(f"ERROR: {target!r} is not registered and not a valid owner/repo", file=sys.stderr)
                return 2
            # Auto-register
            uid = target.split("/", 1)[1]
            upstream = Upstream(id=uid, repo=target)
            ups = load_upstreams(project)
            ups.append(upstream)
            save_upstreams(project, ups)
            print(f"Auto-registered upstream: {uid} → {target}")

        print(f"Fetching {upstream.repo}...")
        cache_path = clone_or_update_cache(project, upstream)
        skills_dir = detect_upstream_skills_dir(cache_path)
        if not skills_dir:
            print(f"ERROR: no skills/ or configs/skills/ dir in {upstream.repo}", file=sys.stderr)
            return 2
        audit_root = skills_dir
        upstream_id = upstream.id
        upstream_repo = upstream.repo
        upstream_ref = current_commit(cache_path)[:7]
        upstream_version = latest_tag(cache_path)

    # Overlap detection:
    # A skill from this upstream "overlaps with native" ONLY if a local skill
    # with the same name is classified as `native` (no upstream origin) OR is
    # absorbed from a DIFFERENT upstream. Same-upstream absorbed/modified is
    # an update, not an overlap.
    native_names: set[str] = set()
    inv_path = project / ".claude/equipment/inventory.yaml"
    if inv_path.is_file():
        import yaml
        inv = yaml.safe_load(inv_path.read_text()) or {}
        for s in inv.get("skills", []):
            cls = s.get("class")
            origin = s.get("upstream")
            if cls == "native":
                native_names.add(s["name"])
            elif cls in ("absorbed", "modified-absorbed") and origin and origin != upstream_id:
                native_names.add(s["name"])

    local_root = skills_root(project)
    audits: list[SkillAudit] = []
    print(f"Auditing skills under: {audit_root}")
    for skill_dir in sorted(audit_root.iterdir()):
        if not skill_dir.is_dir() or skill_dir.name.startswith("."):
            continue
        local_mirror = local_root / skill_dir.name
        a = audit_skill(skill_dir, local_mirror if local_mirror.is_dir() else None)
        overlap = a.name in native_names and target != "."
        a.compute_decision(overlap_native=overlap)
        audits.append(a)

    # Write report
    today = date.today().isoformat()
    report_path = audits_dir(project) / f"{upstream_id}-{today}.md"
    report = build_report(
        upstream_id=upstream_id,
        upstream_repo=upstream_repo,
        upstream_ref=upstream_ref,
        upstream_version=upstream_version if target != "." else None,
        audits=audits,
        native_names=native_names,
    )
    report_path.write_text(report)

    # Summary
    adopt_n = sum(1 for a in audits if a.decision == "ADOPT")
    review_n = sum(1 for a in audits if a.decision == "NEEDS-REVIEW")
    skip_n = sum(1 for a in audits if a.decision == "SKIP")
    print()
    print(f"Audit report: {report_path}")
    print(f"  ADOPT:        {adopt_n}")
    print(f"  NEEDS-REVIEW: {review_n}")
    print(f"  SKIP:         {skip_n}")
    print()
    if review_n:
        print("Top needs-review items:")
        for a in [x for x in audits if x.decision == "NEEDS-REVIEW"][:5]:
            flag_ids = ", ".join(sorted({f.id for f in a.flags}))
            print(f"  • {a.name:30s} flags: {flag_ids}")
    print()
    print(f"Next: review the report, edit [x]/[ ], then `/equip sync {upstream_id} --apply`")
    return 0


if __name__ == "__main__":
    sys.exit(main())
