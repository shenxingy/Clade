#!/usr/bin/env python3
"""Install only web-search and its owned routing block; preserve other user setup."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import sys
import tempfile
import time
import tomllib

BEGIN = "<!-- BEGIN CLADE WEB SEARCH -->"
END = "<!-- END CLADE WEB SEARCH -->"


def merge_block(path, body, backups, begin=BEGIN, end=END, dry_run=False):
    old = path.read_text() if path.exists() else ""
    block = begin + "\n" + body.rstrip() + "\n" + end
    if begin in old or end in old:
        if old.count(begin) != 1 or old.count(end) != 1 or old.index(begin) > old.index(end):
            raise ValueError("Malformed web-search markers; instructions left unchanged")
        start, stop = old.index(begin), old.index(end) + len(end)
        new = old[:start] + block + old[stop:]
    else:
        new = old + ("\n\n" if old and not old.endswith("\n\n") else "") + block + "\n"
    if new == old:
        return False
    if path.suffix == ".toml":
        tomllib.loads(new)
    if not dry_run:
        replace_config(path, old, new, backups)
    return True


def replace_config(path, old, new, backups):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        name = hashlib.sha256(str(path).encode()).hexdigest()[:12] + "-" + str(time.time_ns())
        shutil.copyfile(path, backups / name)
        (backups / name).chmod(0o600)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".web-search-")
    with os.fdopen(fd, "w") as stream:
        stream.write(new)
    if (path.read_text() if path.exists() else "") != old:
        os.unlink(temporary)
        raise ValueError("Configuration changed during installation; retry from its latest state")
    os.replace(temporary, path)


def install_mcp(cc, cx, cc_state, backups, dry_run=False):
    endpoint = "https://agent.tinyfish.ai/mcp"
    def helper(home):
        return shlex.join([sys.executable, str(home / "skills/web-search/scripts/mcp_headers.py")])
    cx_path = cx / "config.toml"
    cx_old = cx_path.read_text() if cx_path.exists() else ""
    cx_obj = tomllib.loads(cx_old)
    if not isinstance(cx_obj.get("mcp_servers", {}), dict):
        raise ValueError("Invalid Codex MCP configuration object")
    begin, end = "# BEGIN CLADE TINYFISH MCP", "# END CLADE TINYFISH MCP"
    if "tinyfish" in cx_obj.get("mcp_servers", {}) and begin not in cx_old:
        raise ValueError("Unowned Codex tinyfish MCP entry exists; left unchanged")
    cc_old = cc_state.read_text() if cc_state.exists() else ""
    cc_obj = json.loads(cc_old) if cc_old else {}
    if not isinstance(cc_obj, dict) or not isinstance(cc_obj.get("mcpServers", {}), dict):
        raise ValueError("Invalid Claude MCP configuration object")
    entry = {"type": "http", "url": endpoint, "headersHelper": helper(cc)}
    existing = cc_obj.get("mcpServers", {}).get("tinyfish")
    if existing is not None and existing != entry:
        raise ValueError("Unowned Claude tinyfish MCP entry exists; left unchanged")
    body = ('[mcp_servers.tinyfish]\nurl = ' + json.dumps(endpoint)
            + '\nhttp_headers_helper = ' + json.dumps(helper(cx))
            + '\nenabled_tools = ["search", "fetch_content"]\nstartup_timeout_sec = 20\ntool_timeout_sec = 90')
    merge_block(cx_path, body, backups, begin, end, dry_run)
    cc_obj.setdefault("mcpServers", {})["tinyfish"] = entry
    cc_new = json.dumps(cc_obj, ensure_ascii=False, indent=2) + "\n"
    if cc_new != cc_old and not dry_run:
        replace_config(cc_state, cc_old, cc_new, backups)
    return {"endpoint": endpoint, "codex_config": str(cx_path), "claude_config": str(cc_state),
            "credential_storage": "existing_private_key_file", "reload": "new_session"}


def install(source, home, kind, blocked, backups, dry_run=False):
    target = home / "skills" / "web-search"
    marker = target / ".clade-web-search.json"
    previous = json.loads(marker.read_text()) if marker.exists() else {}
    blocked = sorted(set(blocked) | set(previous.get("blocked_providers", [])))
    if target.exists() and not marker.exists():
        # The normal Clade installer may already have copied this exact skill.
        if not (target / "SKILL.md").exists() or (target / "SKILL.md").read_bytes() != (source / "SKILL.md").read_bytes():
            raise ValueError("Unowned web-search skill exists; left unchanged")
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
    merge_block(instructions, body, backups, dry_run=True)
    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)
        if source.resolve() != target.resolve():
            shutil.copytree(source, target, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".clade-web-search.json"))
        marker.write_text(json.dumps({"owner": "clade-web-search", "blocked_providers": blocked,
                                     "source_hash": hashlib.sha256((source / "SKILL.md").read_bytes()).hexdigest()}))
        merge_block(instructions, body, backups)
    return {"runtime": kind, "skill": str(target), "instructions": str(instructions), "reload": "new_session"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claude-home", type=Path, default=Path(os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude")).expanduser())
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser())
    parser.add_argument("--block-provider", action="append", choices=("brave",), default=[])
    parser.add_argument("--with-mcp", action="store_true")
    parser.add_argument("--claude-state", type=Path)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    backups = Path(os.environ.get("CLADE_SEARCH_STATE_DIR", "~/.clade/search")).expanduser() / "install-backups"
    backups.mkdir(parents=True, exist_ok=True, mode=0o700)
    backups.chmod(0o700)
    cc_state = args.claude_state or (args.claude_home / ".claude.json"
               if os.environ.get("CLAUDE_CONFIG_DIR") or args.claude_home != Path.home() / ".claude"
               else Path.home() / ".claude.json")
    # Validate all owned blocks and existing MCP entries before changing either profile.
    install(source, args.claude_home, "claude", args.block_provider, backups, dry_run=True)
    install(source, args.codex_home, "codex", args.block_provider, backups, dry_run=True)
    if args.with_mcp:
        install_mcp(args.claude_home, args.codex_home, cc_state, backups, dry_run=True)
    results = [install(source, args.claude_home, "claude", args.block_provider, backups),
               install(source, args.codex_home, "codex", args.block_provider, backups)]
    result = {"installed": results, "credentials_copied": False}
    if args.with_mcp:
        result["mcp"] = install_mcp(args.claude_home, args.codex_home, cc_state, backups)
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, TypeError):
        print(json.dumps({"status": "error", "code": "invalid_conflicting_or_changed_user_configuration",
                          "next_action": "inspect_existing_config_and_retry_without_overwriting_unowned_entries"}))
        raise SystemExit(2)
