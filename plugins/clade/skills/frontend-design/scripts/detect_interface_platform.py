#!/usr/bin/env python3
"""Detect likely interface runtimes from bounded repository signals.

The result is advisory. User intent and declared ship targets take precedence.
The detector reads only common manifests and shallow project markers; it never
modifies the project.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path


SCHEMA = "clade.interface-platform/v1"


EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".next",
    ".svn",
    ".venv",
    "DerivedData",
    "Pods",
    "build",
    "dist",
    "node_modules",
    "target",
    "vendor",
}


def _load_package_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _dependency_names(package: dict) -> set[str]:
    names: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        value = package.get(key, {})
        if isinstance(value, dict):
            names.update(str(name).lower() for name in value)
    return names


def _bounded_entries(root: Path, max_depth: int = 4) -> list[Path]:
    """Return files and project-bundle dirs without entering generated trees."""
    entries: list[Path] = []
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        relative = current_path.relative_to(root)
        depth = 0 if relative == Path(".") else len(relative.parts)
        dirs[:] = sorted(
            name
            for name in dirs
            if name not in EXCLUDED_DIRS and not name.startswith(".") and depth < max_depth
        )
        for name in dirs:
            if name.endswith((".xcodeproj", ".xcworkspace")):
                entries.append(current_path / name)
        entries.extend(current_path / name for name in sorted(files))
    return entries


def detect(root: Path) -> dict:
    root = root.resolve()
    scores: dict[str, int] = defaultdict(int)
    signals: dict[str, list[str]] = defaultdict(list)

    def add(platform: str, score: int, signal: str) -> None:
        scores[platform] += score
        if signal not in signals[platform]:
            signals[platform].append(signal)

    entries = _bounded_entries(root)

    web_deps = {
        "@angular/core",
        "astro",
        "next",
        "nuxt",
        "react",
        "solid-js",
        "svelte",
        "vue",
    }
    for package_path in (path for path in entries if path.name == "package.json"):
        deps = _dependency_names(_load_package_json(package_path))
        relative = package_path.relative_to(root).as_posix()
        for dep in sorted(deps & web_deps):
            add("web", 2, f"{relative} dependency: {dep}")
        if "electron" in deps or any(name.startswith("@electron/") for name in deps):
            add("electron", 8, f"{relative} dependency: electron")
        if "@tauri-apps/api" in deps or "@tauri-apps/cli" in deps:
            add("tauri", 8, f"{relative} dependency: @tauri-apps")
        if "react-native" in deps or "expo" in deps:
            add("react-native", 8, f"{relative} dependency: react-native/expo")

    for path in entries:
        relative = path.relative_to(root).as_posix()
        name = path.name
        lower = name.lower()
        if (
            name == "index.html"
            or lower.startswith(("vite.config.", "next.config.", "astro.config.", "svelte.config."))
        ):
            add("web", 2, relative)
        if name.endswith((".xcodeproj", ".xcworkspace")) or name == "Package.swift":
            add("apple-native", 5, relative)
        if name in {"settings.gradle", "settings.gradle.kts", "AndroidManifest.xml"}:
            add("android-native", 5, relative)
        if path.suffix.lower() in {".sln", ".csproj", ".vcxproj", ".xaml"} or name == "Package.appxmanifest":
            add("windows-native", 5, relative)
        if name in {"tauri.conf.json", "tauri.conf.json5"} and "src-tauri" in path.parts:
            add("tauri", 5, relative)
        if name == "pubspec.yaml":
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if "flutter:" in content:
                add("flutter", 5, relative)

    priority = {
        "electron": 8,
        "tauri": 8,
        "flutter": 8,
        "react-native": 8,
        "apple-native": 6,
        "android-native": 6,
        "windows-native": 6,
        "web": 2,
    }
    ordered = sorted(
        scores,
        key=lambda name: (-scores[name], -priority.get(name, 0), name),
    )
    candidates = [
        {
            "platform": name,
            "score": scores[name],
            "confidence": "high" if scores[name] >= 6 else "medium" if scores[name] >= 3 else "low",
            "signals": signals[name],
        }
        for name in ordered
    ]
    primary = ordered[0] if ordered else "unknown"
    ambiguous = len(ordered) > 1 and scores[ordered[0]] == scores[ordered[1]]
    return {
        "schema": SCHEMA,
        "project_root": str(root),
        "primary": primary,
        "ambiguous": ambiguous,
        "candidates": candidates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", nargs="?", default=".")
    args = parser.parse_args()
    root = Path(args.project_root).expanduser()
    if not root.is_dir():
        parser.error(f"project root is not a directory: {root}")
    print(json.dumps(detect(root), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
