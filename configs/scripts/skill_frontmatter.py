#!/usr/bin/env python3
"""skill_frontmatter.py — the ONE parser for SKILL.md frontmatter.

Shared by (do not add a second parser — import this one):
  - configs/scripts/validate-skills.py  (CI gate + --fix normalizer)
  - orchestrator/mcp_server.py          (load_skills for external MCP clients)
  - install.sh                          (available_skills.md via `catalog` CLI)

Stdlib-only on purpose: install.sh and the deployed ~/.claude/scripts/ copy
must work without any pip install. The parser is deliberately lenient
(line-based, folds `>` / `|` block scalars and indented plain continuations)
because real SKILL.md files in the wild — including upstream-synced ones —
are not always strict YAML. validate-skills.py is the strictness gate.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# ─── Schema ──────────────────────────────────────────────────────────────────

# Canonical key spellings. user-invokable / user-invocable are tolerated
# aliases carried by upstream-synced skills (see install.sh comment).
INVOCABLE_KEYS = ("user_invocable", "user-invokable", "user-invocable")

KNOWN_KEYS = frozenset({
    "name",
    "description",
    "when_to_use",
    "argument-hint",
    "allowed-tools",
    "tested_date",
    "tested_with",
    "metadata",
    "license",
    "compatibility",
    *INVOCABLE_KEYS,
})

_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(.*)$")

# ─── Parsing ─────────────────────────────────────────────────────────────────


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Split a SKILL.md into (frontmatter_text, body).

    frontmatter_text is None when the file has no leading ``---`` block.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1:])
    return None, text


def _unquote(value: str) -> str:
    """Strip one matching pair of surrounding quotes, if present."""
    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v


def parse_frontmatter(fm_text: str) -> dict[str, str]:
    """Parse frontmatter into {key: folded_single_line_value}.

    Only column-0 keys count as keys; indented lines are folded into the
    value of the key above them (covers `>` / `|` block scalars, multi-line
    plain scalars, and nested mappings like `metadata:`).
    """
    data: dict[str, str] = {}
    current: str | None = None
    for line in fm_text.splitlines():
        m = _KEY_RE.match(line)
        if m:
            key, raw = m.group(1), m.group(2).strip()
            if raw in (">", "|", ">-", "|-", ">+", "|+"):
                data[key] = ""  # block scalar — value comes from continuations
            else:
                data[key] = _unquote(raw)
            current = key
        elif line[:1] in (" ", "\t") and current is not None and line.strip():
            existing = data.get(current, "")
            data[current] = (existing + " " + line.strip()).strip()
        # blank / comment / pre-key lines: ignored
    return data


def parse_bool(value: str) -> bool:
    return value.strip().lower() in ("true", "1", "yes")


def load_skill(skill_md: Path) -> dict | None:
    """Load one SKILL.md into the shape mcp_server / install.sh consume.

    Returns None when the file is unreadable. Missing name falls back to the
    directory name; missing description falls back to "".
    """
    try:
        # Explicit utf-8: Windows Python defaults read_text() to cp1252
        # ('charmap'), which crashes on the Chinese text in skill descriptions.
        text = skill_md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    fm_text, _body = split_frontmatter(text)
    fields = parse_frontmatter(fm_text) if fm_text is not None else {}
    user_invocable = any(parse_bool(fields.get(k, "")) for k in INVOCABLE_KEYS)
    return {
        "name": fields.get("name", "").strip() or skill_md.parent.name,
        "description": fields.get("description", "").strip(),
        "argument_hint": fields.get("argument-hint", "").strip(),
        "when_to_use": fields.get("when_to_use", "").strip(),
        "user_invocable": user_invocable,
        "fields": fields,
    }


def iter_skills(skills_dir: Path) -> list[dict]:
    """All parsed skills under skills_dir/*/SKILL.md, sorted by directory."""
    skills = []
    if not skills_dir.is_dir():
        return skills
    for skill_path in sorted(skills_dir.iterdir()):
        skill_md = skill_path / "SKILL.md"
        if not skill_path.is_dir() or not skill_md.is_file():
            continue
        skill = load_skill(skill_md)
        if skill is not None:
            skills.append(skill)
    return skills


# ─── Catalog generation (used by install.sh) ─────────────────────────────────


def catalog(skills_dir: Path) -> str:
    """Render available_skills.md content (same format install.sh produced)."""
    out = [
        "# Available Skills",
        "",
        "These skills are installed. Use them by mentioning their name naturally.",
        "",
    ]
    for skill in iter_skills(skills_dir):
        out.append(f"## {skill['name']}")
        out.append(skill["description"])
        if skill["user_invocable"]:
            out.append(f"(can be invoked with /{skill['name']})")
        out.append("")
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "catalog":
        sys.stdout.write(catalog(Path(argv[2]).expanduser()))
        return 0
    sys.stderr.write("usage: skill_frontmatter.py catalog <skills_dir>\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
