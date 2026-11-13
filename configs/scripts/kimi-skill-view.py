#!/usr/bin/env python3
"""Build Clade's marker-owned Kimi skill view without changing Claude skills.

The source root may itself be a symlink into a dotfiles sync store. It is only
read. The managed view links ordinary and unknown user skills, and materializes
only claude-only SKILL.md files with model invocation disabled. Every deletion
unlinks the entry itself; no recursive delete follows a symlink.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python < 3.11: only the conservative textual migration rule below is used.
    tomllib = None  # type: ignore[assignment]

MARKER = ".clade-managed"
MARKER_TEXT = "clade-kimi-skill-view-v1\n"
DISABLE_KEY = re.compile(
    r"^[ \t]*[\"']?(?:disableModelInvocation|disable-model-invocation|"
    r"disable_model_invocation)[\"']?[ \t]*:"
)
ROOT_EXTRA = re.compile(
    r"^[ \t]*(?P<prefix>extra_skill_dirs[ \t]*=[ \t]*)(?P<array>\[.*\])"
    r"(?P<suffix>[ \t]*(?:#.*)?(?:\r?\n)?)$"
)
ROOT_KEY = re.compile(
    r"^[ \t]*(?:extra_skill_dirs|\"extra_skill_dirs\"|'extra_skill_dirs')[ \t]*="
)


class SkipView(Exception):
    """An expected safe skip; config must remain unchanged."""


class InvalidSkill(Exception):
    """A claude-only skill whose front matter cannot produce a valid Kimi skill."""


def remove_no_follow(path: Path) -> None:
    if not os.path.lexists(path):
        return
    if path.is_symlink() or not path.is_dir():
        path.unlink()
        return
    for child in path.iterdir():
        remove_no_follow(child)
    path.rmdir()


def link(target: Path, destination: Path) -> None:
    if destination.is_symlink() and os.readlink(destination) == str(target):
        return
    remove_no_follow(destination)
    result = subprocess.run(
        ["ln", "-s", str(target), str(destination)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0 or not destination.is_symlink():
        detail = result.stderr.strip() or "ln -s did not produce a symlink"
        raise SkipView(f"Kimi skill view needs symlink support: {detail}")


def validate_view_location(view: Path) -> None:
    if not view.is_absolute() or view.name != "clade-skills":
        raise ValueError("view must be an absolute path named clade-skills")
    if not os.path.lexists(view):
        return
    marker = view / MARKER
    if (
        view.is_symlink()
        or not view.is_dir()
        or marker.is_symlink()
        or not marker.is_file()
        or marker.read_text(encoding="utf-8") != MARKER_TEXT
    ):
        raise SkipView(
            f"{view} exists without the Clade marker; left it and config.toml untouched"
        )


def preflight_symlinks(source: Path, parent: Path) -> None:
    probe = Path(tempfile.mkdtemp(prefix=".clade-symlink-probe-", dir=parent))
    try:
        link(source, probe / "skill-link")
    finally:
        remove_no_follow(probe)


def flagged_skill_text(source: Path) -> str:
    with source.open("r", encoding="utf-8", newline="") as handle:
        text = handle.read()
    lines = text.splitlines(keepends=True)
    if not lines:
        raise InvalidSkill("no front matter")
    first = lines[0][1:] if lines[0].startswith("\ufeff") else lines[0]
    if first.strip() != "---":
        raise InvalidSkill("no front matter")
    closing = next(
        (index for index in range(1, len(lines)) if lines[index].strip() == "---"),
        None,
    )
    if closing is None:
        raise InvalidSkill("unclosed front matter")
    if any(DISABLE_KEY.match(line) for line in lines[1:closing]):
        return text
    newline = "\r\n" if lines[closing].endswith("\r\n") else "\n"
    lines.insert(closing, "disableModelInvocation: true" + newline)
    return "".join(lines)


def write_text_if_changed(path: Path, text: str) -> None:
    if os.path.lexists(path) and not path.is_symlink() and path.is_file():
        with path.open("r", encoding="utf-8", newline="") as handle:
            if handle.read() == text:
                return
    remove_no_follow(path)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def materialize_claude_only(source: Path, destination: Path) -> None:
    if destination.is_symlink() or (os.path.lexists(destination) and not destination.is_dir()):
        remove_no_follow(destination)
    destination.mkdir(exist_ok=True)
    source_children = {path.name for path in source.iterdir()}
    for child in destination.iterdir():
        if child.name not in source_children:
            remove_no_follow(child)
    write_text_if_changed(destination / "SKILL.md", flagged_skill_text(source / "SKILL.md"))
    for child in source.iterdir():
        if child.name != "SKILL.md":
            link(child, destination / child.name)


def build_view(report_path: Path, source: Path, view: Path) -> tuple[int, int]:
    if not source.is_absolute() or not source.is_dir():
        raise ValueError(f"skill source is not a directory: {source}")
    validate_view_location(view)
    preflight_symlinks(source, view.parent)
    if not os.path.lexists(view):
        view.mkdir()
        (view / MARKER).write_text(MARKER_TEXT, encoding="utf-8")

    report = json.loads(report_path.read_text(encoding="utf-8"))
    claude_only = {
        row["name"] for row in report["skills"] if row["classification"] == "claude-only"
    }
    skills = sorted(
        path for path in source.iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    )
    expected = {path.name for path in skills}
    for child in view.iterdir():
        if child.name != MARKER and child.name not in expected:
            remove_no_follow(child)

    linked = copied = 0
    for skill in skills:
        destination = view / skill.name
        if skill.name in claude_only:
            try:
                materialize_claude_only(skill, destination)
            except InvalidSkill as exc:
                # catalog/parser.ts requires name AND description for directory
                # skills, so key-only replacement front matter would not load.
                print(f"Omitted claude-only skill {skill.name}: {exc}")
                remove_no_follow(destination)
                continue
            copied += 1
        else:
            link(skill, destination)
            linked += 1
    return linked, copied


def _array_delta(line: str) -> int:
    depth = 0
    quote = ""
    escaped = False
    for char in line:
        if quote:
            if escaped:
                escaped = False
            elif char == "\\" and quote == '"':
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char == "#":
            break
        if char in ("'", '"'):
            quote = char
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
    return depth


def _root_extra_candidates(lines: list[str]) -> tuple[list[tuple[int, re.Match[str] | None]], int]:
    candidates: list[tuple[int, re.Match[str] | None]] = []
    depth = 0
    for index, line in enumerate(lines):
        if depth > 0:
            depth = max(0, depth + _array_delta(line))
            continue
        if line.lstrip().startswith("["):
            return candidates, index
        if ROOT_KEY.match(line):
            candidates.append((index, ROOT_EXTRA.match(line)))
        depth = max(0, depth + _array_delta(line))
    return candidates, len(lines)


def _config_validation_error(original: str, updated: str, view: Path) -> str | None:
    if tomllib is None:
        return None
    try:
        original_document = tomllib.loads(original)
    except tomllib.TOMLDecodeError as exc:
        return f"original config.toml does not parse: {exc}"
    try:
        updated_document = tomllib.loads(updated)
    except tomllib.TOMLDecodeError as exc:
        return f"updated config.toml does not parse: {exc}"
    if updated_document.get("extra_skill_dirs") != [str(view)]:
        return "updated root extra_skill_dirs does not equal the Kimi skill view"
    original_keys = set(original_document)
    updated_keys = set(updated_document)
    if original_keys - updated_keys:
        return "the update would remove a root key or table"
    if updated_keys - original_keys - {"extra_skill_dirs"}:
        return "the update would add a root key or table other than extra_skill_dirs"
    for key in original_keys - {"extra_skill_dirs"}:
        if original_document[key] != updated_document[key]:
            return f"the update would change root key or table {key}"
    return None


def configure_view(source: Path, view: Path, config: Path) -> None:
    if not config.is_file():
        print(f"Kimi skill view: {view}; no config.toml exists, left unchanged")
        return
    with config.open("r", encoding="utf-8", newline="") as handle:
        text = handle.read()
    lines = text.splitlines(keepends=True)
    candidates, first_table = _root_extra_candidates(lines)
    desired_json = json.dumps(str(view), ensure_ascii=False)

    if len(candidates) > 1:
        print(f"Kimi skill view: {view}; root extra_skill_dirs is ambiguous, left unchanged")
        return
    if candidates and candidates[0][1] is None:
        print(f"Kimi skill view: {view}; non-canonical user-set extra_skill_dirs left unchanged")
        return
    if candidates:
        index, match = candidates[0]
        assert match is not None
        try:
            value = ast.literal_eval(match.group("array"))
        except (SyntaxError, ValueError):
            value = None
        if value == [str(view)]:
            print(f"Kimi skill view: {view}; extra_skill_dirs already points there")
            return
        if value != [str(source)]:
            print(f"Kimi skill view: {view}; user-set extra_skill_dirs left unchanged")
            return
        lines[index] = (
            f"{match.group('prefix')}[{desired_json}]{match.group('suffix')}"
        )
    else:
        newline = "\r\n" if any(line.endswith("\r\n") for line in lines) else "\n"
        if first_table == len(lines) and lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] += newline
        lines.insert(first_table, f"extra_skill_dirs = [{desired_json}]{newline}")

    updated = "".join(lines)
    problem = _config_validation_error(text, updated, view)
    if problem is not None:
        print(f"Kimi skill view: {view}; left config.toml unchanged: {problem}")
        return
    with config.open("w", encoding="utf-8", newline="") as handle:
        handle.write(updated)
    print(f"Kimi skill view: {view}; extra_skill_dirs points there")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--view", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    source = args.source.absolute()
    view = args.view.absolute()
    try:
        linked, copied = build_view(args.report, source, view)
    except SkipView as exc:
        print(f"Skipped: {exc}")
        return 0
    except (OSError, ValueError, SyntaxError, json.JSONDecodeError) as exc:
        print(f"kimi-skill-view: {exc}", file=sys.stderr)
        return 1
    print(f"Kimi skill view: {view} ({linked} linked, {copied} claude-only copies)")
    configure_view(source, view, args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
