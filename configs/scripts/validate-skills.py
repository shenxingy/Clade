#!/usr/bin/env python3
"""validate-skills.py — CI gate for the skill registry (configs/skills/*/SKILL.md).

One schema, one parser: all frontmatter reading goes through
skill_frontmatter.py (the same module mcp_server.py and install.sh use).

Checks (errors fail CI, warnings don't):
  - SKILL.md exists in every skill directory, with a --- frontmatter block
  - name present and matching the directory name
  - description present, non-empty, single-line in the raw frontmatter
    (no `>` / `|` block scalars, no multi-line plain scalars — line-based
    consumers like Claude Code's catalog renderer choke on them)
  - description is portable YAML: quoted when it contains `: `, ` #`, or
    starts with a YAML indicator character (`>`, `|`, `&`, `*`, ...)
  - description length <= 1024 chars
  - only known frontmatter keys (KNOWN_KEYS in skill_frontmatter.py)
  - warning: non-canonical invocable spelling (canonical: user_invocable;
    user-invokable / user-invocable tolerated for upstream-synced skills)

--fix rewrites only the description line(s): folds multi-line values to a
single line, strips inline/block `>` `|` markers, and quotes when needed.
Everything else in the file is left byte-identical.

Usage:
    validate-skills.py [skills_dir] [--fix] [--quiet]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import skill_frontmatter as sf  # noqa: E402

MAX_DESCRIPTION_LEN = 1024

# YAML indicator chars that make an unquoted plain scalar unsafe at position 0
_YAML_INDICATORS = set(">|&*!%@`\"'#-?:,[]{}")


def needs_quoting(text: str) -> bool:
    """True when `description: <text>` is not a safe plain YAML scalar."""
    if not text:
        return False
    return (
        text[0] in _YAML_INDICATORS
        or ": " in text
        or " #" in text
        or text.endswith(":")
        or text != text.strip()
    )


def quote_if_needed(text: str) -> str:
    # json.dumps produces a double-quoted scalar valid in both YAML and our
    # lenient line parser.
    return json.dumps(text, ensure_ascii=False) if needs_quoting(text) else text


def _description_span(fm_lines: list[str]) -> tuple[int, int] | None:
    """(start, end) line indexes of the description key + its continuations."""
    for i, line in enumerate(fm_lines):
        if re.match(r"^description:", line):
            end = i + 1
            while end < len(fm_lines) and (
                fm_lines[end][:1] in (" ", "\t") or not fm_lines[end].strip()
            ):
                end += 1
            # trim trailing blank lines out of the span
            while end > i + 1 and not fm_lines[end - 1].strip():
                end -= 1
            return i, end
    return None


def _folded_description(fm_lines: list[str], span: tuple[int, int]) -> str:
    """Single-line description text for the span (markers stripped)."""
    start, end = span
    raw = fm_lines[start].split(":", 1)[1].strip()
    if raw in (">", "|", ">-", "|-", ">+", "|+"):
        raw = ""
    elif raw[:2] in ("> ", "| "):
        raw = raw[2:].strip()  # inline block marker: `description: > text`
    else:
        raw = sf._unquote(raw)
    parts = [raw] if raw else []
    parts += [ln.strip() for ln in fm_lines[start + 1:end] if ln.strip()]
    return " ".join(parts).strip()


def validate_skill_dir(skill_dir: Path, fix: bool = False) -> tuple[list[str], list[str]]:
    """Validate one skill directory. Returns (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    name = skill_dir.name
    skill_md = skill_dir / "SKILL.md"

    if not skill_md.is_file():
        return [f"{name}: SKILL.md missing"], []

    text = skill_md.read_text()
    fm_text, _body = sf.split_frontmatter(text)
    if fm_text is None:
        return [f"{name}: no --- frontmatter block"], []

    fm_lines = fm_text.splitlines()
    fields = sf.parse_frontmatter(fm_text)

    # name
    fm_name = fields.get("name", "").strip()
    if not fm_name:
        errors.append(f"{name}: frontmatter has no name")
    elif fm_name != name:
        errors.append(f"{name}: name '{fm_name}' != directory name")

    # unknown keys (column-0 only)
    for line in fm_lines:
        m = sf._KEY_RE.match(line)
        if m and m.group(1) not in sf.KNOWN_KEYS:
            errors.append(f"{name}: unknown frontmatter key '{m.group(1)}'")

    # non-canonical invocable spelling
    for key in ("user-invokable", "user-invocable"):
        if key in fields:
            warnings.append(f"{name}: '{key}' — canonical spelling is user_invocable")

    # description
    span = _description_span(fm_lines)
    if span is None:
        errors.append(f"{name}: description missing")
        return errors, warnings

    desc = _folded_description(fm_lines, span)
    desc_errors: list[str] = []
    if not desc:
        errors.append(f"{name}: description empty")
        return errors, warnings
    if len(desc) > MAX_DESCRIPTION_LEN:
        errors.append(f"{name}: description too long ({len(desc)} > {MAX_DESCRIPTION_LEN})")

    start, end = span
    raw = fm_lines[start].split(":", 1)[1].strip()
    raw_is_quoted = len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"')
    if end - start > 1:
        desc_errors.append(f"{name}: description is multi-line (block scalar or continuation)")
    if raw[:1] in (">", "|") :
        desc_errors.append(f"{name}: description uses a `{raw[:1]}` block marker")
    elif not raw_is_quoted and needs_quoting(desc):
        desc_errors.append(f"{name}: description needs quoting (contains `: `/` #`/indicator char)")

    if desc_errors and fix:
        fm_lines[start:end] = [f"description: {quote_if_needed(desc)}"]
        body = _body_of(text)
        new_text = "---\n" + "\n".join(fm_lines) + "\n---"
        if body:
            new_text += "\n" + body
        if text.endswith("\n") and not new_text.endswith("\n"):
            new_text += "\n"  # preserve the original trailing newline
        skill_md.write_text(new_text)
        warnings.append(f"{name}: fixed — description normalized to a single quoted line")
    else:
        errors.extend(desc_errors)

    return errors, warnings


def _body_of(text: str) -> str:
    return sf.split_frontmatter(text)[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "skills_dir",
        nargs="?",
        default=str(Path(__file__).resolve().parent.parent / "skills"),
        help="skills directory (default: sibling skills/ of this script's parent)",
    )
    parser.add_argument("--fix", action="store_true", help="rewrite fixable description issues")
    parser.add_argument("--quiet", action="store_true", help="only print errors")
    args = parser.parse_args()

    skills_dir = Path(args.skills_dir).expanduser()
    if not skills_dir.is_dir():
        print(f"validate-skills: skills dir not found: {skills_dir}", file=sys.stderr)
        return 2

    all_errors: list[str] = []
    all_warnings: list[str] = []
    count = 0
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        count += 1
        errors, warnings = validate_skill_dir(skill_dir, fix=args.fix)
        all_errors.extend(errors)
        all_warnings.extend(warnings)

    for e in all_errors:
        print(f"ERROR   {e}")
    if not args.quiet:
        for w in all_warnings:
            print(f"warning {w}")
    status = "FAIL" if all_errors else "OK"
    print(f"validate-skills: {status} — {count} skills, {len(all_errors)} errors, {len(all_warnings)} warnings")
    return 1 if all_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
