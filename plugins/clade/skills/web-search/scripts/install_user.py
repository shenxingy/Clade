#!/usr/bin/env python3
"""Install only web-search and its owned routing block; preserve other user setup."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time

BEGIN = "<!-- BEGIN CLADE WEB SEARCH -->"
END = "<!-- END CLADE WEB SEARCH -->"


def merge_block(path, body, backups):
    old = path.read_text() if path.exists() else ""
    block = BEGIN + "\n" + body.rstrip() + "\n" + END
    if BEGIN in old or END in old:
        if old.count(BEGIN) != 1 or old.count(END) != 1 or old.index(BEGIN) > old.index(END):
            raise ValueError("Malformed web-search markers; instructions left unchanged")
        start, stop = old.index(BEGIN), old.index(END) + len(END)
        new = old[:start] + block + old[stop:]
    else:
        new = old + ("\n\n" if old and not old.endswith("\n\n") else "") + block + "\n"
    if new == old:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        name = hashlib.sha256(str(path).encode()).hexdigest()[:12] + "-" + str(time.time_ns())
        shutil.copyfile(path, backups / name)
        (backups / name).chmod(0o600)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".web-search-")
    with os.fdopen(fd, "w") as stream:
        stream.write(new)
    os.replace(temporary, path)
    return True


def install(source, home, kind, blocked, backups):
    target = home / "skills" / "web-search"
    marker = target / ".clade-web-search.json"
    previous = json.loads(marker.read_text()) if marker.exists() else {}
    blocked = sorted(set(blocked) | set(previous.get("blocked_providers", [])))
    if target.exists() and not marker.exists():
        # The normal Clade installer may already have copied this exact skill.
        if not (target / "SKILL.md").exists() or (target / "SKILL.md").read_bytes() != (source / "SKILL.md").read_bytes():
            raise ValueError("Unowned web-search skill exists; left unchanged")
    target.mkdir(parents=True, exist_ok=True)
    if source.resolve() != target.resolve():
        shutil.copytree(source, target, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".clade-web-search.json"))
    marker.write_text(json.dumps({"owner": "clade-web-search", "blocked_providers": blocked,
                                 "source_hash": hashlib.sha256((source / "SKILL.md").read_bytes()).hexdigest()}))
    if kind == "claude":
        instructions = home / "rules" / "clade-web-search.md"
    else:
        override = home / "AGENTS.override.md"
        instructions = override if override.is_file() and override.stat().st_size else home / "AGENTS.md"
    body = ("For external web searches and URL reading, load the web-search skill at "
            + str(target / "SKILL.md") + ". Follow its automatic native/TinyFish routing in the current session. "
            "A native handoff must execute the actual native tool; do not spawn another model CLI. "
            "Use official documentation tools first when required. Repository/file searches are unaffected.")
    if blocked:
        body += "\nUser-excluded search providers: " + ", ".join(blocked) + ". Do not call their tools or APIs."
    merge_block(instructions, body, backups)
    return {"runtime": kind, "skill": str(target), "instructions": str(instructions), "reload": "new_session"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claude-home", type=Path, default=Path(os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude")).expanduser())
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser())
    parser.add_argument("--block-provider", action="append", choices=("brave",), default=[])
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    backups = Path(os.environ.get("CLADE_SEARCH_STATE_DIR", "~/.clade/search")).expanduser() / "install-backups"
    backups.mkdir(parents=True, exist_ok=True, mode=0o700)
    backups.chmod(0o700)
    results = [install(source, args.claude_home, "claude", args.block_provider, backups),
               install(source, args.codex_home, "codex", args.block_provider, backups)]
    print(json.dumps({"installed": results, "credentials_copied": False}))


if __name__ == "__main__":
    main()
