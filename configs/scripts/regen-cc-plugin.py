#!/usr/bin/env python3
"""Sync the Claude Code plugin manifest and its generated component tree.

``.claude-plugin/plugin.json`` (the Claude Code marketplace/plugin manifest)
carries fields that drift silently if hand-edited:

- ``version`` — must track the canonical semver base published in the Codex
  plugin manifest (``plugins/clade/.codex-plugin/plugin.json``), with Codex's
  cache-busting build metadata (``+codex.<timestamp>``) stripped.
- ``skills`` — a directory path. The loader accepts a directory string here.
- ``description`` — advertises component counts. It said "37 agents" while the
  loader resolved zero of them; see below.

``agents`` is NOT a manifest field this loader honours. That belief was
encoded here until 2026-08-29 and it was wrong in both directions, measured
against the installed CLI (2.1.236) with ``claude --plugin-dir . plugin
details clade``:

    "agents": ["./configs/agents/a.md", ...]   ->  Agents (0)   # shipped state
    "agents": "./configs/agents"               ->  plugin fails to load
    "agents": ["./configs/agents"]             ->  plugin fails to load
    (no agents key) + ./agents/ directory      ->  Agents (37)  # correct

So the manifest must carry no ``agents`` key at all, and the agent definitions
must live in an ``agents/`` directory at the plugin root, which the loader
discovers by convention. ``agents/`` is therefore a GENERATED MIRROR of
``configs/agents/`` — the same derived-copy contract ``mcp-package/skills/``
and ``plugins/clade/skills/`` already use. Real files rather than a symlink:
git clones on Windows without symlink support would otherwise deliver 37
one-line text files to the loader.

Hooks are deliberately NOT shipped by this plugin. ``configs/hooks/`` holds 31
scripts, several of which are coupled to the maintainer's environment
(``notify-telegram.sh`` wants a bot token, ``memory-sync.sh`` and
``sync-pull.sh`` touch a personal sync remote). Which subset is safe to run on
a stranger's machine is a product decision, not a drift-gate decision, so the
manifest says what actually ships instead of advertising hooks it does not
install. The loader looks for ``hooks/hooks.json`` at the plugin root; create
that file when the curation question is settled and teach this script to
generate it.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CODEX_MANIFEST = REPO_ROOT / "plugins" / "clade" / ".codex-plugin" / "plugin.json"
CC_MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"
CC_MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"
AGENTS_SRC = REPO_ROOT / "configs" / "agents"
AGENTS_OUT = REPO_ROOT / "agents"
SKILLS_SRC = REPO_ROOT / "configs" / "skills"
SKILLS_PATH = "./configs/skills"

def canonical_version() -> str:
    codex_version = json.loads(CODEX_MANIFEST.read_text(encoding="utf-8"))["version"]
    return codex_version.split("+", 1)[0]


def agent_names() -> list[str]:
    return sorted(p.name for p in AGENTS_SRC.glob("*.md"))


def skill_count() -> int:
    return sum(1 for p in SKILLS_SRC.iterdir() if p.is_dir() and (p / "SKILL.md").exists())


# Rendered from the tree, so a new skill or agent cannot leave a false count
# in the shipped manifest — the failure mode doc-align.py guards for
# README/docs. Generated whole rather than patched in place, so running this
# script twice produces the same string.
DESCRIPTION_TEMPLATE = (
    "Autonomous coding toolkit for Claude Code. {skills} skills, {agents} agents, "
    "a safety guardian, and a correction learning loop — Claude codes better, "
    "catches its own mistakes, and runs unattended overnight. Hooks ship via "
    "install.sh, not this plugin."
)


def expected_description() -> str:
    return DESCRIPTION_TEMPLATE.format(skills=skill_count(), agents=len(agent_names()))


def expected_marketplace() -> dict:
    """marketplace.json carries its own copy of the description.

    It had drifted the same way plugin.json had — advertising hooks the plugin
    does not install — and it is the copy a browsing user reads first.
    """
    entry = json.loads(CC_MARKETPLACE.read_text(encoding="utf-8"))
    entry["description"] = expected_description()
    return entry


def expected_manifest() -> dict:
    manifest = json.loads(CC_MANIFEST.read_text(encoding="utf-8"))
    manifest.pop("agents", None)  # not a field this loader honours — see module docstring
    manifest["version"] = canonical_version()
    manifest["skills"] = SKILLS_PATH
    manifest["description"] = expected_description()
    return manifest


def expected_agent_files() -> dict[str, str]:
    return {name: (AGENTS_SRC / name).read_text(encoding="utf-8") for name in agent_names()}


def generate() -> None:
    CC_MANIFEST.write_text(
        json.dumps(expected_manifest(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    CC_MARKETPLACE.write_text(
        json.dumps(expected_marketplace(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if AGENTS_OUT.is_symlink() or AGENTS_OUT.is_file():
        AGENTS_OUT.unlink()
    elif AGENTS_OUT.is_dir():
        shutil.rmtree(AGENTS_OUT)
    AGENTS_OUT.mkdir(parents=True)
    for name, body in expected_agent_files().items():
        (AGENTS_OUT / name).write_text(body, encoding="utf-8")


def check() -> int:
    problems: list[str] = []

    expected = expected_manifest()
    actual = json.loads(CC_MANIFEST.read_text(encoding="utf-8"))
    if "agents" in actual:
        problems.append(
            "  plugin.json still carries an 'agents' key — the loader resolves 0 agents from it"
        )
    for key in ("version", "skills", "description"):
        if actual.get(key) != expected[key]:
            problems.append(f"  {key}: have={actual.get(key)!r} want={expected[key]!r}")

    market_have = json.loads(CC_MARKETPLACE.read_text(encoding="utf-8"))
    market_want = expected_marketplace()
    if market_have.get("description") != market_want["description"]:
        problems.append(
            f"  marketplace.json description: have={market_have.get('description')!r} "
            f"want={market_want['description']!r}"
        )

    if AGENTS_OUT.is_symlink():
        problems.append(f"  {AGENTS_OUT} is a symlink — Windows clones deliver a text file instead")
    elif not AGENTS_OUT.is_dir():
        problems.append(f"  {AGENTS_OUT} is missing — the loader would resolve 0 agents")
    else:
        want = expected_agent_files()
        have = {p.name: p.read_text(encoding="utf-8") for p in AGENTS_OUT.glob("*.md")}
        for name in sorted(set(want) - set(have)):
            problems.append(f"  agents/{name}: missing")
        for name in sorted(set(have) - set(want)):
            problems.append(f"  agents/{name}: stale (no longer in configs/agents/)")
        for name in sorted(set(want) & set(have)):
            if want[name] != have[name]:
                problems.append(f"  agents/{name}: drifted from configs/agents/{name}")

    if not problems:
        return 0
    print(
        f"{CC_MANIFEST} / {CC_MARKETPLACE} / {AGENTS_OUT} are out of date; "
        "run configs/scripts/regen-cc-plugin.py",
        file=sys.stderr,
    )
    for line in problems:
        print(line, file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        return check()
    generate()
    print(
        f"Synced {CC_MANIFEST} (version {canonical_version()}, "
        f"{skill_count()} skills) and {AGENTS_OUT} ({len(agent_names())} agents)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
