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
    """Map relative-path → sha256 for every file under root."""
    if not root.is_dir():
        return {}
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = str(p.relative_to(root))
            out[rel] = file_hash(p)
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

    Returns the cache path for this upstream.
    """
    cache = cache_dir(project) / upstream.id
    cache.parent.mkdir(parents=True, exist_ok=True)
    url = upstream.repo
    if not url.startswith(("http://", "https://", "git@")):
        url = f"https://github.com/{upstream.repo}.git"

    if cache.is_dir() and (cache / ".git").is_dir():
        # Update
        try:
            run(["git", "fetch", "--depth", "1", "origin", upstream.branch], cwd=cache)
            run(["git", "reset", "--hard", f"origin/{upstream.branch}"], cwd=cache)
        except subprocess.CalledProcessError as e:
            print(f"WARNING: fetch failed for {upstream.id}: {e.stderr}", file=sys.stderr)
    else:
        if cache.exists():
            shutil.rmtree(cache)
        run(["git", "clone", "--depth", "1", "--branch", upstream.branch, url, str(cache)])
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

def detect_upstream_skills_dir(upstream_root: Path) -> Optional[Path]:
    """Find where skills live in a cloned upstream repo."""
    for candidate in ("skills", "configs/skills"):
        p = upstream_root / candidate
        if p.is_dir():
            return p
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
