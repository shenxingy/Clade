#!/usr/bin/env python3
"""
Setup script for nanobanana-mcp in claude-blog.

Configures @ycse/nanobanana-mcp in the project's .mcp.json (default)
or Claude Code's global settings.json (with --global flag).

Usage:
    python3 setup_image_mcp.py                    # Interactive (prompts for key)
    python3 setup_image_mcp.py --key YOUR_KEY     # Non-interactive
    python3 setup_image_mcp.py --check            # Verify existing setup
    python3 setup_image_mcp.py --remove           # Remove MCP config
    python3 setup_image_mcp.py --global           # Write to ~/.claude/settings.json
    python3 setup_image_mcp.py --help             # Show usage
"""

import json
import sys
import os
from pathlib import Path

MCP_NAME = "nanobanana-mcp"
MCP_PACKAGE = "@ycse/nanobanana-mcp"
DEFAULT_MODEL = "gemini-3.1-flash-image-preview"
GLOBAL_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"


def find_project_mcp_json() -> Path:
    """Find the project-level .mcp.json by looking for .claude-plugin/plugin.json."""
    current = Path(__file__).resolve().parent
    for _ in range(10):  # Max 10 levels up
        candidate = current / ".claude-plugin" / "plugin.json"
        if candidate.exists():
            return current / ".mcp.json"
        parent = current.parent
        if parent == current:
            break
        current = parent
    # Fallback: look from cwd
    current = Path.cwd()
    for _ in range(10):
        candidate = current / ".claude-plugin" / "plugin.json"
        if candidate.exists():
            return current / ".mcp.json"
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def get_config_path(use_global: bool) -> Path:
    """Get the appropriate config file path."""
    if use_global:
        return GLOBAL_SETTINGS_PATH
    project_path = find_project_mcp_json()
    if project_path:
        return project_path
    print("Warning: Could not find project root (.claude-plugin/plugin.json).")
    print("Falling back to global settings.")
    return GLOBAL_SETTINGS_PATH


def load_config(path: Path) -> dict:
    """Load config file."""
    if not path.exists():
        return {}
    with open(path, "r") as f:
        return json.load(f)


def save_config(path: Path, config: dict) -> None:
    """Save config file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    print(f"Config saved to {path}")


def check_setup(use_global: bool) -> bool:
    """Check if MCP is already configured."""
    # Check project-level first, then global
    paths_to_check = []
    if not use_global:
        project_path = find_project_mcp_json()
        if project_path:
            paths_to_check.append(("Project .mcp.json", project_path))
    paths_to_check.append(("Global settings.json", GLOBAL_SETTINGS_PATH))

    for label, path in paths_to_check:
        config = load_config(path)
        servers = config.get("mcpServers", {})
        if MCP_NAME in servers:
            env = servers[MCP_NAME].get("env", {})
            key = env.get("GOOGLE_AI_API_KEY", "")
            masked = key[:8] + "..." + key[-4:] if len(key) > 12 else "(not set)"
            print(f"MCP server '{MCP_NAME}' found in {label}.")
            print(f"  Path:    {path}")
            print(f"  Package: {MCP_PACKAGE}")
            print(f"  API Key: {masked}")
            print(f"  Model:   {env.get('NANOBANANA_MODEL', DEFAULT_MODEL)}")
            return True

    print(f"MCP server '{MCP_NAME}' is NOT configured.")
    return False


def remove_mcp(use_global: bool) -> None:
    """Remove MCP configuration."""
    path = get_config_path(use_global)
    config = load_config(path)
    servers = config.get("mcpServers", {})
    if MCP_NAME in servers:
        del servers[MCP_NAME]
        config["mcpServers"] = servers
        save_config(path, config)
        print(f"Removed '{MCP_NAME}' from {path}.")
    else:
        print(f"'{MCP_NAME}' not found in {path}.")


def setup_mcp(api_key: str, use_global: bool) -> None:
    """Configure MCP server."""
    if not api_key or not api_key.strip():
        print("Error: API key cannot be empty.")
        sys.exit(1)

    api_key = api_key.strip()
    path = get_config_path(use_global)
    config = load_config(path)

    if "mcpServers" not in config:
        config["mcpServers"] = {}

    config["mcpServers"][MCP_NAME] = {
        "command": "npx",
        "args": ["-y", MCP_PACKAGE],
        "env": {
            "GOOGLE_AI_API_KEY": api_key,
            "NANOBANANA_MODEL": DEFAULT_MODEL,
        },
    }

    save_config(path, config)
    print(f"\nMCP server '{MCP_NAME}' configured successfully!")
    print(f"  Package: {MCP_PACKAGE}")
    print(f"  Model:   {DEFAULT_MODEL}")
    print(f"  Config:  {path}")
    print(f"\nRestart Claude Code for changes to take effect.")
    print(f"Generated images will be saved to: ~/Documents/nanobanana_generated/")


def main() -> None:
    args = sys.argv[1:]
    use_global = "--global" in args

    if "--help" in args or "-h" in args:
        print("Usage: python3 setup_image_mcp.py [OPTIONS]")
        print()
        print("Options:")
        print("  --key KEY        Provide API key non-interactively")
        print("  --check          Verify existing setup")
        print("  --remove         Remove MCP configuration")
        print("  --global         Write to ~/.claude/settings.json (default: project .mcp.json)")
        print("  --help, -h       Show this help message")
        print()
        print("Get a free API key at: https://aistudio.google.com/apikey")
        sys.exit(0)

    if "--check" in args:
        check_setup(use_global)
        return

    if "--remove" in args:
        remove_mcp(use_global)
        return

    # Get API key
    api_key = None
    for i, arg in enumerate(args):
        if arg == "--key" and i + 1 < len(args):
            api_key = args[i + 1]
            break

    if not api_key:
        api_key = os.environ.get("GOOGLE_AI_API_KEY")

    if not api_key:
        print("claude-blog - Image Generation MCP Setup")
        print("=" * 45)
        print(f"\nGet your free API key at: https://aistudio.google.com/apikey")
        print()
        try:
            api_key = input("Enter your Google AI API key: ")
        except (EOFError, KeyboardInterrupt):
            print("\nError: No input received. Provide a key with --key or set GOOGLE_AI_API_KEY env var.")
            sys.exit(1)

    setup_mcp(api_key, use_global)


if __name__ == "__main__":
    main()
