#!/usr/bin/env python3
"""equip_scan.py — Build an inventory of a project's equipment.

Classifies every skill/agent/script as:
  - native           : no matching upstream
  - absorbed         : exact match with a registered upstream (clean)
  - modified-absorbed: name/path match but content differs (local edits on top)
  - orphan           : looks like it came from somewhere but no upstream registered

Writes <project>/.claude/equipment/inventory.yaml.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from equip_common import (
    AUDITS_DIR,
    Upstream,
    agents_root,
    cache_dir,
    classify_tool_permission,
    clone_or_update_cache,
    detect_layout,
    detect_upstream_agents_dir,
    detect_upstream_hooks_dir,
    detect_upstream_scripts_dir,
    detect_upstream_skills_dir,
    dump_yaml,
    ensure_equipment_dir,
    file_hash,
    hooks_root,
    load_upstreams,
    project_equipment_dir,
    read_frontmatter,
    scripts_root,
    skills_root,
    tree_hash,
)


# ─── Hint heuristics for orphan detection ───────────────────────────────────

# If a skill's prompt mentions an AgriciDaniel-flavored pattern, it's likely
# absorbed from there even if no upstream is registered yet.
ORPHAN_HINTS = [
    ("AgriciDaniel/", "AgriciDaniel-ecosystem"),
    ("claude-seo", "claude-seo"),
    ("claude-ads", "claude-ads"),
    ("claude-blog", "claude-blog"),
    ("banana-claude", "banana-claude"),
    ("PleasePrompto/", "PleasePrompto-ecosystem"),
    ("YCSE/", "YCSE-ecosystem"),
]


def scan_upstream_skill_hashes(project: Path, upstreams: list[Upstream]) -> dict[str, dict[str, str]]:
    """For each upstream, return a map of skill_name → merged-content-hash.

    Uses cached clones (updates if possible, falls back to existing cache).
    """
    out: dict[str, dict[str, str]] = {}
    for u in upstreams:
        cache = cache_dir(project) / u.id
        if not (cache / ".git").is_dir():
            try:
                clone_or_update_cache(project, u)
            except subprocess.CalledProcessError:
                print(f"  WARN: could not clone {u.id}, skipping", file=sys.stderr)
                continue
        else:
            # best-effort refresh, silent on failure
            try:
                clone_or_update_cache(project, u)
            except Exception:
                pass
        upstream_skills = detect_upstream_skills_dir(cache)
        if not upstream_skills:
            continue
        skill_map: dict[str, str] = {}
        for skill_dir in sorted(upstream_skills.iterdir()):
            if not skill_dir.is_dir():
                continue
            # Combined hash of all files under this skill
            h = combined_hash(skill_dir)
            skill_map[skill_dir.name] = h
        out[u.id] = skill_map
    return out


def combined_hash(skill_dir: Path) -> str:
    """Hash of a skill directory = hash of its file tree (name:hash pairs)."""
    import hashlib
    th = tree_hash(skill_dir)
    combined = "\n".join(f"{k}={v}" for k, v in sorted(th.items()))
    return hashlib.sha256(combined.encode()).hexdigest()


def scan_file_hint(path: Path) -> Optional[str]:
    """Peek at a single file's content and return an orphan hint if a known
    upstream-flavored pattern is found."""
    if not path.is_file():
        return None
    try:
        text = path.read_text(errors="replace")
    except Exception:
        return None
    for needle, hint in ORPHAN_HINTS:
        if needle in text:
            return hint
    return None


def scan_skill_hint(skill_dir: Path) -> Optional[str]:
    """Peek at skill files and return orphan hint if any known pattern found."""
    for fname in ("prompt.md", "SKILL.md"):
        hint = scan_file_hint(skill_dir / fname)
        if hint:
            return hint
    return None


def scan_upstream_flat_hashes(
    project: Path,
    upstreams: list[Upstream],
    detect_fn,
) -> dict[str, dict[str, str]]:
    """Generic sibling of scan_upstream_skill_hashes for flat (file-per-item)
    inventories such as agents/, scripts/, hooks/ — no per-item directory,
    so the hash is just the file's own content hash.

    Assumes upstream caches were already cloned/updated (e.g. by
    scan_upstream_skill_hashes running first) — does not clone here.
    `detect_fn` locates the relevant dir inside a cloned upstream cache
    (e.g. detect_upstream_agents_dir).
    """
    out: dict[str, dict[str, str]] = {}
    for u in upstreams:
        cache = cache_dir(project) / u.id
        if not (cache / ".git").is_dir():
            continue
        target_dir = detect_fn(cache)
        if not target_dir:
            continue
        file_map: dict[str, str] = {}
        for f in sorted(target_dir.iterdir()):
            if f.is_file() and not f.name.startswith("."):
                file_map[f.name] = file_hash(f)
        out[u.id] = file_map
    return out


def classify_skill(
    skill_dir: Path,
    upstream_hashes: dict[str, dict[str, str]],
) -> dict:
    """Classify a single local skill directory."""
    name = skill_dir.name
    local_hash = combined_hash(skill_dir)
    # Look for exact name match in upstreams
    for uid, skill_map in upstream_hashes.items():
        if name in skill_map:
            if skill_map[name] == local_hash:
                return {
                    "path": str(skill_dir),
                    "name": name,
                    "class": "absorbed",
                    "upstream": uid,
                    "local_hash": local_hash[:16],
                }
            else:
                return {
                    "path": str(skill_dir),
                    "name": name,
                    "class": "modified-absorbed",
                    "upstream": uid,
                    "local_hash": local_hash[:16],
                    "upstream_hash": skill_map[name][:16],
                }
    # No upstream match — check for hints
    hint = scan_skill_hint(skill_dir)
    if hint:
        return {
            "path": str(skill_dir),
            "name": name,
            "class": "orphan",
            "hint": hint,
            "local_hash": local_hash[:16],
        }
    return {
        "path": str(skill_dir),
        "name": name,
        "class": "native",
        "local_hash": local_hash[:16],
    }


def classify_flat_item(path: Path, kind: str, upstream_hashes: dict[str, dict[str, str]]) -> dict:
    """Classify a single flat (non-directory) equipment item — agent, script,
    or hook — the same way classify_skill classifies a skill directory: exact
    content-hash match against a registered upstream, drift detection, and
    orphan-hint scanning. `kind` is tagged onto the result for downstream
    reporting (skill / agent / script / hook).
    """
    name = path.stem if kind == "agent" else path.name
    local_hash = file_hash(path)
    entry: dict = {"path": str(path), "name": name, "kind": kind}

    matched = False
    for uid, file_map in upstream_hashes.items():
        upstream_hash = file_map.get(path.name)
        if upstream_hash is None:
            continue
        matched = True
        if upstream_hash == local_hash:
            entry.update({"class": "absorbed", "upstream": uid, "local_hash": local_hash[:16]})
        else:
            entry.update({
                "class": "modified-absorbed",
                "upstream": uid,
                "local_hash": local_hash[:16],
                "upstream_hash": upstream_hash[:16],
            })
        break

    if not matched:
        hint = scan_file_hint(path)
        if hint:
            entry.update({"class": "orphan", "hint": hint, "local_hash": local_hash[:16]})
        else:
            entry.update({"class": "native", "local_hash": local_hash[:16]})

    # Wildcard/broad tool-permission surfacing — only meaningful for agents,
    # which declare a `tools:` frontmatter field (Claude Code subagent
    # convention). Scripts/hooks have no such frontmatter concept.
    if kind == "agent":
        front = read_frontmatter(path)
        perm = classify_tool_permission(front)
        if perm:
            entry["tool_permission"] = perm

    return entry


def classify_agents(agents_dir: Path, upstream_hashes: dict[str, dict[str, str]]) -> list[dict]:
    """Agents are single .md files, not dirs."""
    results = []
    if not agents_dir.is_dir():
        return results
    for f in sorted(agents_dir.glob("*.md")):
        results.append(classify_flat_item(f, "agent", upstream_hashes))
    return results


def classify_scripts(scripts_dir: Path, upstream_hashes: dict[str, dict[str, str]]) -> list[dict]:
    """Scripts are flat files (.sh/.py/...) directly under scripts_dir.

    Subdirectories (e.g. a scripts/ads/ bundle) are not descended into — this
    is a top-level inventory pass, not a recursive one.
    """
    results = []
    if not scripts_dir.is_dir():
        return results
    for f in sorted(scripts_dir.iterdir()):
        if f.is_file() and not f.name.startswith("."):
            results.append(classify_flat_item(f, "script", upstream_hashes))
    return results


def classify_hooks(hooks_dir: Path, upstream_hashes: dict[str, dict[str, str]]) -> list[dict]:
    """Hooks are flat files directly under hooks_dir (hooks/lib/ helpers are
    not themselves hooks and are not descended into)."""
    results = []
    if not hooks_dir.is_dir():
        return results
    for f in sorted(hooks_dir.iterdir()):
        if f.is_file() and not f.name.startswith("."):
            results.append(classify_flat_item(f, "hook", upstream_hashes))
    return results


# ─── Main ───────────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description="Scan a project and build equipment inventory")
    p.add_argument("--project", type=Path, default=Path.cwd())
    p.add_argument("--refresh-cache", action="store_true",
                   help="Force re-clone all upstream caches before scanning")
    args = p.parse_args()

    project = args.project.resolve()
    ensure_equipment_dir(project)
    layout = detect_layout(project)
    print(f"Project: {project}")
    print(f"Layout:  {layout}")

    upstreams = load_upstreams(project)
    print(f"Registered upstreams: {len(upstreams)}")
    if args.refresh_cache and upstreams:
        for u in upstreams:
            try:
                clone_or_update_cache(project, u)
            except subprocess.CalledProcessError as e:
                print(f"  WARN: refresh {u.id}: {e.stderr}", file=sys.stderr)

    print("Building upstream skill-hash maps...")
    upstream_hashes = scan_upstream_skill_hashes(project, upstreams)
    for uid, m in upstream_hashes.items():
        print(f"  {uid}: {len(m)} upstream skills indexed")

    # Scan local skills
    s_root = skills_root(project, layout)
    print(f"Scanning skills under: {s_root}")
    skills = []
    if s_root.is_dir():
        for skill_dir in sorted(s_root.iterdir()):
            if skill_dir.is_dir() and not skill_dir.name.startswith("."):
                skills.append(classify_skill(skill_dir, upstream_hashes))

    # Scan agents / scripts / hooks (flat-file equipment kinds)
    agent_hashes = scan_upstream_flat_hashes(project, upstreams, detect_upstream_agents_dir)
    script_hashes = scan_upstream_flat_hashes(project, upstreams, detect_upstream_scripts_dir)
    hook_hashes = scan_upstream_flat_hashes(project, upstreams, detect_upstream_hooks_dir)

    a_root = agents_root(project, layout)
    print(f"Scanning agents under: {a_root}")
    agents = classify_agents(a_root, agent_hashes)

    sc_root = scripts_root(project, layout)
    print(f"Scanning scripts under: {sc_root}")
    scripts = classify_scripts(sc_root, script_hashes)

    h_root = hooks_root(project, layout)
    print(f"Scanning hooks under: {h_root}")
    hooks = classify_hooks(h_root, hook_hashes)

    # Summary
    by_class: dict[str, int] = {}
    for s in skills:
        by_class[s["class"]] = by_class.get(s["class"], 0) + 1

    inventory = {
        "project": str(project),
        "layout": layout,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "upstreams_registered": [u.id for u in upstreams],
        "summary": {
            "skills": len(skills),
            "by_class": by_class,
            "agents": len(agents),
            "scripts": len(scripts),
            "hooks": len(hooks),
        },
        "skills": skills,
        "agents": agents,
        "scripts": scripts,
        "hooks": hooks,
    }

    out_path = project_equipment_dir(project) / "inventory.yaml"
    dump_yaml(out_path, inventory)

    print()
    print(f"Inventory written: {out_path}")
    print(f"  Skills by class: {by_class}")
    print(f"  Agents: {len(agents)}  Scripts: {len(scripts)}  Hooks: {len(hooks)}")
    orphans = [s for s in skills if s["class"] == "orphan"]
    if orphans:
        print()
        print(f"  {len(orphans)} orphan skill(s) (look absorbed, no upstream registered):")
        # group by hint
        by_hint: dict[str, list[str]] = {}
        for o in orphans:
            by_hint.setdefault(o.get("hint", "unknown"), []).append(o["name"])
        for hint, names in by_hint.items():
            preview = ", ".join(names[:4]) + (f" (+{len(names)-4} more)" if len(names) > 4 else "")
            print(f"    • {hint}: {preview}")
        print()
        print("  Suggestion: /equip add <owner/repo> to register them.")

    wildcard_agents = [a for a in agents if a.get("tool_permission") == "wildcard"]
    broad_agents = [a for a in agents if a.get("tool_permission") == "broad"]
    if wildcard_agents or broad_agents:
        print()
        if wildcard_agents:
            names = ", ".join(a["name"] for a in wildcard_agents)
            print(f"  {len(wildcard_agents)} agent(s) declare a WILDCARD tool grant — requires explicit human consent: {names}")
        if broad_agents:
            names = ", ".join(a["name"] for a in broad_agents)
            print(f"  {len(broad_agents)} agent(s) declare an unusually broad tool allowlist — review before adopting: {names}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
