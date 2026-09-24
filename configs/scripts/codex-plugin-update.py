#!/usr/bin/env python3
"""Reinstall Clade through Codex, retaining bundles referenced by old sessions.

Workaround for stale live hook engines: https://github.com/openai/codex/issues/36605
Pause other sessions during the CLI's cache replacement; restore is not atomic
with that external operation. Never edits hook code, trust or plugin settings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile


def cache_root(home: Path) -> Path:
    return home / "plugins/cache/clade/clade"


def plain_path(path: Path) -> None:
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError(f"refusing symlink: {path}")


def version_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]*", value):
        raise ValueError(f"invalid version: {value!r}")
    return value


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(home: Path, backups: Path) -> Path:
    """Save complete, validated installed bundles outside the replaceable cache."""
    root = cache_root(home)
    plain_path(root)
    plain_path(backups)
    if backups.resolve().is_relative_to((home / "plugins").resolve()):
        raise ValueError("backups must live outside the Codex plugins directory")
    backups.mkdir(parents=True, exist_ok=True)
    saved = Path(tempfile.mkdtemp(prefix="clade-", dir=backups))
    versions = {}
    for bundle in sorted(root.iterdir()) if root.exists() else []:
        if bundle.is_symlink() and not bundle.exists():
            # Historical aliases may outlive their target. They are already
            # unusable, not installed bundles; never follow or recreate them.
            print(f"Skipping dangling cache alias: {bundle}", flush=True)
            continue
        plain_path(bundle)
        name = version_name(bundle.name)
        manifest = bundle / ".codex-plugin/plugin.json"
        plain_path(manifest)
        data = json.loads(manifest.read_text())
        if data.get("name") != "clade" or data.get("version") != name:
            raise ValueError(f"bundle manifest does not match version: {bundle}")
        files = {}
        for source in sorted(bundle.rglob("*")):
            plain_path(source)
            if source.is_dir():
                continue
            if not source.is_file():
                raise ValueError(f"not a regular file: {source}")
            relative = source.relative_to(bundle)
            target = saved / "bundles" / name / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            files[relative.as_posix()] = checksum(target)
        versions[name] = files
    (saved / "snapshot.json").write_text(json.dumps({"schema": 1, "versions": versions}, indent=2) + "\n")
    return saved


def restore(saved: Path, home: Path) -> None:
    """Verify everything before restoring missing files; never replace a conflict."""
    plain_path(saved / "snapshot.json")
    index = json.loads((saved / "snapshot.json").read_text())
    if index.get("schema") != 1:
        raise ValueError("unsupported snapshot schema")
    pending = []
    for version, files in index["versions"].items():
        version_name(version)
        for relative, digest in files.items():
            path = PurePosixPath(relative)
            if path.is_absolute() or ".." in path.parts or "\\" in relative or ":" in relative or not path.parts:
                raise ValueError(f"invalid snapshot path: {relative!r}")
            source = saved / "bundles" / version / path
            target = cache_root(home) / version / path
            plain_path(source)
            plain_path(target)
            if checksum(source) != digest:
                raise ValueError(f"backup checksum mismatch: {source}")
            if target.exists():
                if not target.is_file() or checksum(target) != digest:
                    raise ValueError(f"cache conflict; preserved current file: {target}")
            else:
                pending.append((source, target))
    for source, target in pending:
        plain_path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation also refuses a file appearing since preflight.
        with target.open("xb") as output, source.open("rb") as input_file:
            shutil.copyfileobj(input_file, output)
        shutil.copystat(source, target)


def update(home: Path, backups: Path) -> int:
    plain_path(backups)
    backups.mkdir(parents=True, exist_ok=True)
    lock = backups / "update.lock"
    lock.mkdir()  # Serialize this helper; never silently steal a stale lock.
    try:
        saved = snapshot(home, backups)
        print(f"Backup: {saved}", flush=True)
        print("Pause other sessions during reinstall; start a new thread for new skills.", flush=True)
        try:
            result = subprocess.run(
                ["codex", "plugin", "add", "clade@clade"],
                env={**os.environ, "CODEX_HOME": str(home)},
                check=False,
                timeout=300,
            )
        finally:
            # A single process must own both steps: an already broken hook can
            # prevent the agent from issuing a separate restore command.
            try:
                restore(saved, home)
            except Exception:
                print(f"Restore failed; retain backup and retry with --restore {saved}", flush=True)
                raise
        print("Previous bundle paths verified; Codex installation exit code:", result.returncode)
        return result.returncode
    finally:
        lock.rmdir()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")))
    parser.add_argument("--backup-root", type=Path, default=Path.home() / ".clade/codex-plugin-backups")
    parser.add_argument("--restore", type=Path, help="restore missing files from a retained snapshot without reinstalling")
    args = parser.parse_args()
    home = args.codex_home.expanduser().absolute()
    backups = args.backup_root.expanduser().absolute()
    if args.restore:
        restore(args.restore.expanduser().absolute(), home)
        print("Previous bundle paths verified; no plugin reinstall performed.")
        return 0
    return update(home, backups)


if __name__ == "__main__":
    raise SystemExit(main())
