#!/usr/bin/env python3
"""Generate the native Codex plugin skills from Clade's canonical skills.

Clade's Claude distribution executes ``prompt.md`` while Codex executes the
body of ``SKILL.md`` directly.  This generator combines both files, applies a
small compatibility layer, and copies references/assets into the plugin.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "configs" / "skills"
PLUGIN_ROOT = REPO_ROOT / "plugins" / "clade"
DEFAULT_DEST = PLUGIN_ROOT / "skills"
MANIFEST = PLUGIN_ROOT / "skills.list"

COMPATIBILITY_HEADER = """# Clade for Codex

This workflow runs **directly in Codex**. Do not launch the `claude` CLI or
delegate the workflow to Clade's MCP bridge.

Codex compatibility rules:

- Read the nearest `AGENTS.md` files for repository instructions. If a project
  has only `CLAUDE.md`, treat it as legacy project guidance and read it too.
- Store new Clade working state under `.clade/` (or `~/.clade/` for personal
  state). Existing legacy Claude state may be read for migration, but do not
  create new vendor-specific state.
- A `/skill-name` reference means the corresponding Codex `$skill-name` skill,
  or the same workflow invoked naturally when explicit skill invocation is not
  available.
- Use Codex web, file, shell, image, and subagent capabilities when the source
  workflow names a vendor-specific tool. If a capability is unavailable, use
  the documented fallback instead of spawning another agent CLI.
- Paths such as `<plugin-root>/...` are relative to the installed Clade plugin
  containing this `SKILL.md`; resolve that root before invoking a helper.

"""

REPLACEMENTS = (
    ("`claude -p` session", "Codex session"),
    ("claude -p", "Codex"),
    ("--dangerously-skip-permissions", "the configured Codex permission policy"),
    ("~/.claude/", "~/.clade/"),
    (".claude/", ".clade/"),
    ("CLAUDE_PROJECT_DIR", "PWD"),
    # Keep generated commands and file lists syntactically valid. The
    # compatibility header above carries the legacy CLAUDE.md fallback rule.
    ("CLAUDE.md", "AGENTS.md"),
    ("Claude Code session", "Codex session"),
    ("Claude session", "Codex session"),
    ("Claude Code", "Codex"),
    ("Claude:", "Codex:"),
    ("Claude is", "Codex is"),
    ("&& claude", "&& codex"),
    ("Use the Agent tool with", "Use a Codex subagent when available with"),
    ("Use the Agent tool", "Use a Codex subagent when available"),
    ("WebSearch", "web search"),
    ("WebFetch", "web page fetch"),
    ("Read tool", "file-reading tools"),
    ("Write tool", "file-editing tools"),
    ("Edit tool", "file-editing tools"),
)

FORBIDDEN_NATIVE_TEXT = (
    "claude -p",
    "--dangerously-skip-permissions",
    "~/.claude/",
    ".claude/",
)


def _read_manifest() -> list[str]:
    names: list[str] = []
    for raw in MANIFEST.read_text(encoding="utf-8").splitlines():
        name = raw.strip()
        if name and not name.startswith("#"):
            names.append(name)
    if len(names) != len(set(names)):
        raise ValueError("duplicate skill in plugins/clade/skills.list")
    return names


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, text
    fields: dict[str, str] = {}
    current: str | None = None
    for line in lines[1:end]:
        if line and not line[0].isspace() and ":" in line:
            current, value = line.split(":", 1)
            fields[current] = value.strip().strip("\"'")
        elif current and line.strip():
            fields[current] = f"{fields[current]} {line.strip()}".strip()
    return fields, "\n".join(lines[end + 1 :]).strip()


def _adapt(text: str) -> str:
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    return text


def _render_skill(name: str) -> str:
    source_dir = SOURCE_ROOT / name
    skill_md = source_dir / "SKILL.md"
    prompt_md = source_dir / "prompt.md"
    if not skill_md.is_file():
        raise FileNotFoundError(f"missing canonical skill: {skill_md}")

    fields, reference_body = _split_frontmatter(skill_md.read_text(encoding="utf-8"))
    description = fields.get("description", "").strip()
    if not description:
        raise ValueError(f"{name}: missing description")
    prompt_body = prompt_md.read_text(encoding="utf-8").strip() if prompt_md.is_file() else ""
    canonical = prompt_body or reference_body
    if not canonical:
        raise ValueError(f"{name}: no executable instructions")

    sections = [
        "---",
        f"name: {name}",
        f"description: {json.dumps(_adapt(description), ensure_ascii=False)}",
        "---",
        "",
        COMPATIBILITY_HEADER.rstrip(),
        "",
        "## Canonical Clade workflow",
        "",
        _adapt(canonical),
    ]
    if prompt_body and reference_body:
        sections.extend(("", "## Additional skill reference", "", _adapt(reference_body)))
    rendered = "\n".join(sections).rstrip() + "\n"
    for forbidden in FORBIDDEN_NATIVE_TEXT:
        if forbidden.lower() in rendered.lower():
            raise ValueError(f"{name}: generated Codex skill contains forbidden text: {forbidden}")
    return rendered


def _copy_resources(source_dir: Path, dest_dir: Path) -> None:
    for child in sorted(source_dir.iterdir()):
        if child.name in {"SKILL.md", "prompt.md", "README.md", "__pycache__"}:
            continue
        if child.suffix in {".pyc", ".pyo"}:
            continue
        target = dest_dir / child.name
        if child.is_dir():
            shutil.copytree(
                child,
                target,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
            )
        elif child.is_file():
            shutil.copy2(child, target)


def generate(dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for name in _read_manifest():
        skill_dest = dest / name
        skill_dest.mkdir()
        (skill_dest / "SKILL.md").write_text(_render_skill(name), encoding="utf-8")
        _copy_resources(SOURCE_ROOT / name, skill_dest)


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def check() -> int:
    with tempfile.TemporaryDirectory(prefix="clade-codex-skills-") as tmp:
        expected = Path(tmp) / "skills"
        generate(expected)
        actual_hashes = _tree_hashes(DEFAULT_DEST) if DEFAULT_DEST.exists() else {}
        expected_hashes = _tree_hashes(expected)
        if actual_hashes == expected_hashes:
            return 0
        missing = sorted(expected_hashes.keys() - actual_hashes.keys())
        extra = sorted(actual_hashes.keys() - expected_hashes.keys())
        changed = sorted(
            path for path in actual_hashes.keys() & expected_hashes.keys()
            if actual_hashes[path] != expected_hashes[path]
        )
        print("Codex plugin skills are out of date; run configs/scripts/regen-codex-plugin.py", file=sys.stderr)
        for label, paths in (("missing", missing), ("extra", extra), ("changed", changed)):
            for path in paths:
                print(f"  {label}: {path}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dest", nargs="?", type=Path, default=DEFAULT_DEST)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        return check()
    generate(args.dest.resolve())
    print(f"Generated {len(_read_manifest())} Codex skills in {args.dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
