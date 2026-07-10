#!/usr/bin/env python3
"""equip_common.py — Shared helpers for the /equip skill.

Also dispatches the `list`, `add`, `remove` subcommands directly.

Project-agnostic: operates on any project whose root is passed via --project.
State lives under `<project>/.claude/equipment/`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    import yaml  # PyYAML
except ImportError:
    print("ERROR: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(2)


# ─── Constants ──────────────────────────────────────────────────────────────

EQUIPMENT_DIR_NAME = ".claude/equipment"
CACHE_DIR_NAME = ".cache"
INVENTORY_FILE = "inventory.yaml"
UPSTREAMS_FILE = "upstreams.yaml"
AUDITS_DIR = "audits"

LAYOUT_A = "kit-style"         # configs/skills/
LAYOUT_B = "plugin-style"      # skills/
LAYOUT_C = "dotfiles"          # ~/.claude/skills/
LAYOUT_D = "vault-style"       # vault + skills/
LAYOUT_UNKNOWN = "unknown"


# ─── Data classes ───────────────────────────────────────────────────────────

@dataclass
class Upstream:
    id: str
    repo: str                           # "owner/repo"
    branch: str = "main"
    # If set, sync/scan/audit checkout this exact commit/tag (detached HEAD)
    # instead of tracking `branch` HEAD — for reproducible absorption. Unset
    # (None) preserves the original branch-tracking behavior.
    pinned_ref: Optional[str] = None
    last_synced_commit: Optional[str] = None
    last_synced_version: Optional[str] = None
    last_synced_at: Optional[str] = None
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Upstream":
        return cls(
            id=d["id"],
            repo=d["repo"],
            branch=d.get("branch", "main"),
            pinned_ref=d.get("pinned_ref"),
            last_synced_commit=d.get("last_synced_commit"),
            last_synced_version=d.get("last_synced_version"),
            last_synced_at=d.get("last_synced_at"),
            include=d.get("include", []) or [],
            exclude=d.get("exclude", []) or [],
            notes=d.get("notes", "") or "",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "repo": self.repo,
            "branch": self.branch,
            "pinned_ref": self.pinned_ref,
            "last_synced_commit": self.last_synced_commit,
            "last_synced_version": self.last_synced_version,
            "last_synced_at": self.last_synced_at,
            "include": self.include,
            "exclude": self.exclude,
            "notes": self.notes,
        }


# ─── Paths ──────────────────────────────────────────────────────────────────

def project_equipment_dir(project: Path) -> Path:
    return project / EQUIPMENT_DIR_NAME


def cache_dir(project: Path) -> Path:
    return project_equipment_dir(project) / CACHE_DIR_NAME


def audits_dir(project: Path) -> Path:
    return project_equipment_dir(project) / AUDITS_DIR


def ensure_equipment_dir(project: Path) -> Path:
    d = project_equipment_dir(project)
    d.mkdir(parents=True, exist_ok=True)
    (d / CACHE_DIR_NAME).mkdir(exist_ok=True)
    (d / AUDITS_DIR).mkdir(exist_ok=True)
    up = d / UPSTREAMS_FILE
    if not up.exists():
        up.write_text("# Registered upstreams — edit via /equip add/remove\nupstreams: []\n")
    gi = d / ".gitignore"
    if not gi.exists():
        gi.write_text(".cache/\n")
    return d


# ─── Layout detection ───────────────────────────────────────────────────────

def detect_layout(project: Path) -> str:
    """Identify the project's skill-layout convention."""
    if (project / "configs" / "skills").is_dir():
        return LAYOUT_A
    if (project / "skills").is_dir() and (
        (project / "install.sh").exists() or (project / "plugin.json").exists()
    ):
        if (project / "WIKI.md").exists():
            return LAYOUT_D
        return LAYOUT_B
    if project.resolve() == Path.home().joinpath(".claude").resolve():
        return LAYOUT_C
    # soft fallback: if skills/ exists at all, call it plugin-style
    if (project / "skills").is_dir():
        return LAYOUT_B
    return LAYOUT_UNKNOWN


def skills_root(project: Path, layout: Optional[str] = None) -> Path:
    """Return the directory containing skill subdirs for the given project."""
    layout = layout or detect_layout(project)
    if layout == LAYOUT_A:
        return project / "configs" / "skills"
    if layout in (LAYOUT_B, LAYOUT_D):
        return project / "skills"
    if layout == LAYOUT_C:
        return project / "skills"
    # fallback: best guess
    for candidate in ("configs/skills", "skills"):
        p = project / candidate
        if p.is_dir():
            return p
    return project / "skills"


def agents_root(project: Path, layout: Optional[str] = None) -> Path:
    layout = layout or detect_layout(project)
    if layout == LAYOUT_A:
        return project / "configs" / "agents"
    return project / "agents"


def scripts_root(project: Path, layout: Optional[str] = None) -> Path:
    layout = layout or detect_layout(project)
    if layout == LAYOUT_A:
        return project / "configs" / "scripts"
    return project / "scripts"


def hooks_root(project: Path, layout: Optional[str] = None) -> Path:
    layout = layout or detect_layout(project)
    if layout == LAYOUT_A:
        return project / "configs" / "hooks"
    return project / "hooks"


# ─── Hashing ────────────────────────────────────────────────────────────────

def file_hash(path: Path) -> str:
    """sha256 of file bytes, or empty string if file missing."""
    if not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_hash(root: Path) -> dict[str, str]:
    """Map relative-path → sha256 for every file under root.

    Skips `.git/` — a single-skill upstream repo's root IS the skill dir,
    and its git internals must never be hashed or synced as skill content.
    """
    if not root.is_dir():
        return {}
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel_parts = p.relative_to(root).parts
            if ".git" in rel_parts:
                continue
            out["/".join(rel_parts)] = file_hash(p)
    return out


# ─── YAML I/O ───────────────────────────────────────────────────────────────

def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    return data


def dump_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False, allow_unicode=True)


def load_upstreams(project: Path) -> list[Upstream]:
    path = project_equipment_dir(project) / UPSTREAMS_FILE
    data = load_yaml(path)
    return [Upstream.from_dict(u) for u in (data.get("upstreams") or [])]


def save_upstreams(project: Path, upstreams: list[Upstream]) -> None:
    path = project_equipment_dir(project) / UPSTREAMS_FILE
    dump_yaml(path, {"upstreams": [u.to_dict() for u in upstreams]})


def find_upstream(project: Path, id_or_repo: str) -> Optional[Upstream]:
    ups = load_upstreams(project)
    for u in ups:
        if u.id == id_or_repo or u.repo == id_or_repo:
            return u
    # partial: match by repo suffix
    for u in ups:
        if u.repo.endswith("/" + id_or_repo):
            return u
    return None


# ─── Git ops ────────────────────────────────────────────────────────────────

def run(cmd: list[str], cwd: Optional[Path] = None, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=check,
        capture_output=capture,
        text=True,
    )


def clone_or_update_cache(project: Path, upstream: Upstream) -> Path:
    """Shallow-clone the upstream into cache, or pull latest if already there.

    If `upstream.pinned_ref` is set, checks out that exact commit/tag
    (detached HEAD) instead of tracking `upstream.branch` HEAD — trading
    "always latest" for reproducibility. Unset (None, the default) preserves
    the original branch-tracking behavior.

    Returns the cache path for this upstream.
    """
    cache = cache_dir(project) / upstream.id
    cache.parent.mkdir(parents=True, exist_ok=True)
    url = upstream.repo
    if not url.startswith(("http://", "https://", "git@")):
        url = f"https://github.com/{upstream.repo}.git"

    ref = upstream.pinned_ref or upstream.branch

    if cache.is_dir() and (cache / ".git").is_dir():
        # Update
        try:
            run(["git", "fetch", "--depth", "1", "origin", ref], cwd=cache)
            if upstream.pinned_ref:
                run(["git", "checkout", "--detach", "FETCH_HEAD"], cwd=cache)
            else:
                run(["git", "reset", "--hard", f"origin/{ref}"], cwd=cache)
        except subprocess.CalledProcessError as e:
            print(f"WARNING: fetch failed for {upstream.id}: {e.stderr}", file=sys.stderr)
    else:
        if cache.exists():
            shutil.rmtree(cache)
        if upstream.pinned_ref:
            # Clone the repo shallowly, then fetch+checkout the pinned ref
            # specifically (it may not be on the default branch's tip).
            run(["git", "clone", "--depth", "1", url, str(cache)])
            try:
                run(["git", "fetch", "--depth", "1", "origin", ref], cwd=cache)
                run(["git", "checkout", "--detach", "FETCH_HEAD"], cwd=cache)
            except subprocess.CalledProcessError as e:
                print(f"WARNING: could not fetch pinned ref {ref!r} for {upstream.id}: {e.stderr}", file=sys.stderr)
        else:
            run(["git", "clone", "--depth", "1", "--branch", ref, url, str(cache)])
    return cache


def current_commit(repo_path: Path) -> str:
    try:
        r = run(["git", "rev-parse", "HEAD"], cwd=repo_path)
        return r.stdout.strip()
    except subprocess.CalledProcessError:
        return ""


def latest_tag(repo_path: Path) -> Optional[str]:
    try:
        r = run(["git", "describe", "--tags", "--abbrev=0"], cwd=repo_path, check=False)
        tag = r.stdout.strip()
        return tag or None
    except Exception:
        return None


# ─── Layout detection of upstream ───────────────────────────────────────────

def detect_upstream_dir(upstream_root: Path, candidates: list[str]) -> Optional[Path]:
    """Find the first existing candidate subdir in a cloned upstream repo."""
    for candidate in candidates:
        p = upstream_root / candidate
        if p.is_dir():
            return p
    return None


def detect_upstream_skills_dir(upstream_root: Path) -> Optional[Path]:
    """Find where skills live in a cloned upstream repo."""
    return detect_upstream_dir(upstream_root, ["skills", "configs/skills"])


def is_single_skill_repo(upstream_root: Path) -> bool:
    """True when the repo IS one skill: SKILL.md at root, no skills container.

    Layout E ("skill-at-root") — e.g. a company design-system repo packaging
    SKILL.md + tokens + components + brand assets as one portable skill.
    """
    return (
        (upstream_root / "SKILL.md").is_file()
        and detect_upstream_skills_dir(upstream_root) is None
    )


def upstream_skill_dirs(upstream_root: Path) -> list[Path]:
    """Every skill directory in a cloned upstream repo.

    Container layouts (skills/, configs/skills/) yield the container's
    subdirectories; a single-skill repo (Layout E) yields the repo root
    itself — its dir name is the cache dir name, which equals the upstream
    id, so `dir.name` stays a valid skill name in both cases.
    """
    container = detect_upstream_skills_dir(upstream_root)
    if container:
        return [
            p for p in sorted(container.iterdir())
            if p.is_dir() and not p.name.startswith(".")
        ]
    if is_single_skill_repo(upstream_root):
        return [upstream_root]
    return []


def detect_upstream_agents_dir(upstream_root: Path) -> Optional[Path]:
    """Find where agent definitions live in a cloned upstream repo."""
    return detect_upstream_dir(upstream_root, ["agents", "configs/agents"])


def detect_upstream_scripts_dir(upstream_root: Path) -> Optional[Path]:
    """Find where scripts live in a cloned upstream repo."""
    return detect_upstream_dir(upstream_root, ["scripts", "configs/scripts"])


def detect_upstream_hooks_dir(upstream_root: Path) -> Optional[Path]:
    """Find where hooks live in a cloned upstream repo."""
    return detect_upstream_dir(upstream_root, ["hooks", "configs/hooks"])


# ─── Frontmatter + tool-permission classification ──────────────────────────

FRONTMATTER_RE = re.compile(r"^---[ \t]*\n(.*?\n)---[ \t]*(?:\n|$)", re.DOTALL)

# Tokens that grant unrestricted tool access outright.
WILDCARD_TOOL_TOKENS = {"*", "all"}
# 6+ distinct tools declared counts as an "unusually broad" allowlist — worth
# a human glance even without an explicit wildcard token.
BROAD_TOOL_THRESHOLD = 6


def read_frontmatter(path: Path) -> dict[str, Any]:
    """Parse the leading `---\\n...\\n---` YAML frontmatter block of a markdown file.

    Returns {} if the file is missing, has no frontmatter, or it fails to parse
    (never raises — this is a best-effort scan helper).
    """
    if not path.is_file():
        return {}
    try:
        text = path.read_text(errors="replace")
    except Exception:
        return {}
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    try:
        data = yaml.safe_load(m.group(1))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def classify_tool_permission(front: dict[str, Any]) -> Optional[str]:
    """Inspect parsed frontmatter for a wildcard or unusually broad tool grant.

    Checks `tools` (subagent convention — Claude Code grants ALL tools when
    this key is absent, so this function only judges what's *declared*) and
    `allowed-tools` (Clade skill convention). Both may be a comma-separated
    string or a YAML list.

    Returns "wildcard", "broad", or None.
    """
    raw = front.get("tools")
    if raw is None:
        raw = front.get("allowed-tools")
    if raw is None:
        return None

    if isinstance(raw, str):
        items = [t.strip() for t in raw.split(",") if t.strip()]
    elif isinstance(raw, list):
        items = [str(t).strip() for t in raw if str(t).strip()]
    else:
        return None

    normalized = {i.strip("'\"").lower() for i in items}
    if normalized & WILDCARD_TOOL_TOKENS:
        return "wildcard"
    if len(normalized) >= BROAD_TOOL_THRESHOLD:
        return "broad"
    return None


# ─── Dispatchers for list / add / remove ────────────────────────────────────

def cmd_list(project: Path) -> int:
    ensure_equipment_dir(project)
    upstreams = load_upstreams(project)
    if not upstreams:
        print("No upstreams registered. Run: /equip add <owner/repo>")
        return 0
    rows = []
    for u in upstreams:
        rows.append(f"{u.id:24s}  {u.repo:40s}  v={u.last_synced_version or '-':8s}  sha={(u.last_synced_commit or '-')[:7]}  @ {u.last_synced_at or '-'}")
    print("Registered upstreams:")
    print()
    for r in rows:
        print("  " + r)
    return 0


def cmd_add(project: Path, repo: str, id_override: Optional[str] = None) -> int:
    ensure_equipment_dir(project)
    if "/" not in repo:
        print(f"ERROR: repo must be owner/name form, got {repo!r}", file=sys.stderr)
        return 2
    upstreams = load_upstreams(project)
    uid = id_override or repo.split("/", 1)[1]
    if find_upstream(project, uid):
        print(f"Upstream {uid!r} already registered. Use /equip remove first.", file=sys.stderr)
        return 1
    u = Upstream(id=uid, repo=repo)
    upstreams.append(u)
    save_upstreams(project, upstreams)
    print(f"Registered: {uid} → {repo}")
    # Prefetch
    try:
        clone_or_update_cache(project, u)
        print(f"  Cached to {cache_dir(project) / uid}")
    except subprocess.CalledProcessError as e:
        print(f"  WARNING: initial clone failed: {e.stderr}", file=sys.stderr)
    return 0


def cmd_remove(project: Path, id_or_repo: str) -> int:
    upstreams = load_upstreams(project)
    before = len(upstreams)
    upstreams = [u for u in upstreams if u.id != id_or_repo and u.repo != id_or_repo]
    if len(upstreams) == before:
        print(f"No upstream matched {id_or_repo!r}", file=sys.stderr)
        return 1
    save_upstreams(project, upstreams)
    print(f"Unregistered: {id_or_repo}. Cache kept at {cache_dir(project) / id_or_repo} (delete manually if unwanted).")
    return 0


# ─── CLI ────────────────────────────────────────────────────────────────────

def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Equip common helpers / simple subcommands")
    p.add_argument("subcommand", choices=["list", "add", "remove"])
    p.add_argument("--project", type=Path, default=Path.cwd())
    p.add_argument("--repo", type=str, help="owner/repo (for add)")
    p.add_argument("--id", type=str, help="upstream id override (for add) or target id (for remove)")
    args = p.parse_args(argv)

    project = args.project.resolve()

    if args.subcommand == "list":
        return cmd_list(project)
    if args.subcommand == "add":
        if not args.repo:
            p.error("--repo is required for add")
        return cmd_add(project, args.repo, id_override=args.id)
    if args.subcommand == "remove":
        if not args.id:
            p.error("--id is required for remove")
        return cmd_remove(project, args.id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
