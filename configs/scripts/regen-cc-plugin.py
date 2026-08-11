#!/usr/bin/env python3
"""Sync the Claude Code plugin manifest with its sources of truth.

``.claude-plugin/plugin.json`` (the Claude Code marketplace/plugin manifest)
carries two fields that drift silently if hand-edited:

- ``version`` — must track the canonical semver base published in the Codex
  plugin manifest (``plugins/clade/.codex-plugin/plugin.json``), with Codex's
  cache-busting build metadata (``+codex.<timestamp>``) stripped.
- ``agents`` — Claude Code's ``agents`` manifest field only accepts explicit
  ``.md`` file paths, not a directory (unlike ``skills``, which does accept a
  directory). It must list every file under ``configs/agents/`` or newly
  added agents silently fail to load as Claude Code plugin agents.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CODEX_MANIFEST = REPO_ROOT / "plugins" / "clade" / ".codex-plugin" / "plugin.json"
CC_MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"
AGENTS_DIR = REPO_ROOT / "configs" / "agents"
SKILLS_PATH = "./configs/skills"


def canonical_version() -> str:
    codex_version = json.loads(CODEX_MANIFEST.read_text(encoding="utf-8"))["version"]
    return codex_version.split("+", 1)[0]


def agents_manifest_paths() -> list[str]:
    return sorted(f"./configs/agents/{p.name}" for p in AGENTS_DIR.glob("*.md"))


def expected_manifest() -> dict:
    manifest = json.loads(CC_MANIFEST.read_text(encoding="utf-8"))
    manifest["version"] = canonical_version()
    manifest["skills"] = SKILLS_PATH
    manifest["agents"] = agents_manifest_paths()
    return manifest


def generate() -> None:
    manifest = expected_manifest()
    CC_MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def check() -> int:
    expected = expected_manifest()
    actual = json.loads(CC_MANIFEST.read_text(encoding="utf-8"))
    drift = {
        key: (actual.get(key), expected[key])
        for key in ("version", "skills", "agents")
        if actual.get(key) != expected[key]
    }
    if not drift:
        return 0
    print(f"{CC_MANIFEST} is out of date; run configs/scripts/regen-cc-plugin.py", file=sys.stderr)
    for key, (have, want) in drift.items():
        print(f"  {key}: have={have!r} want={want!r}", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        return check()
    generate()
    print(f"Synced {CC_MANIFEST} (version {canonical_version()}, {len(agents_manifest_paths())} agents)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
