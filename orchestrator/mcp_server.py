#!/usr/bin/env python3
"""
Clade MCP Server — Exposes Clade skills as MCP tools.

Run standalone:
    python mcp_server.py

Or configure in ~/.claude/settings.json:
    "mcpServers": {
        "clade": {
            "command": "python",
            "args": ["/path/to/orchestrator/mcp_server.py"]
        }
    }

Or add to Claude Code MCP servers via the official setup flow.

Usage from Claude Code:
    Once configured, use skills by name:
    /audit global
    /commit --dry-run
    etc.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, CallToolResult

# ─── Server Info ────────────────────────────────────────────────────────────────
SERVER_NAME = "clade"
SERVER_VERSION = "0.1.0"

# ─── Skill Discovery ───────────────────────────────────────────────────────────

SKILLS_DIR = Path(os.path.expanduser("~/.claude/skills"))


def parse_argument_hint(hint: str) -> dict[str, Any]:
    """Parse SKILL.md argument-hint into a JSON Schema.

    Handles forms like:
      '[--flag]'                    → { type: "boolean" }
      '[path]'                      → { type: "string" }
      '[--project=slug] [message]' → { type: "object", properties: {...} }
      '[step2 step4 ...] | ...'    → { type: "object" } (complex, use loose schema)
    """
    if not hint.strip():
        return {"type": "object", "properties": {}}

    # Split on | to handle alternation (only process first branch)
    hint_base = hint.split("|")[0].strip()

    # Find all optional flags [--name] and [--name=value]
    # Only those without = are boolean flags
    # = ones take a value
    props = {}
    required = []

    # Match [--key] or [--key=value] in brackets
    opt_flag_matches = re.findall(r'\[--([a-z][a-z0-9-]*)(?:[=]([^\]]*))?\]', hint_base)
    for key, default_val in opt_flag_matches:
        if default_val:
            props[key] = {"type": "string", "description": f"Flag: --{key}={default_val}"}
        else:
            props[key] = {"type": "boolean", "description": f"Flag: --{key}"}

    # Match positional args [name]
    pos_matches = re.findall(r'\[([a-z][a-z0-9-_]*)\]', hint_base)
    for pos in pos_matches:
        if pos not in props:
            props[pos] = {"type": "string", "description": f"Argument: {pos}"}

    # If we found anything, return schema (none are required — they're all optional)
    if props:
        return {
            "type": "object",
            "properties": props,
        }

    # Fallback: accept any object
    return {"type": "object", "properties": {}}


def load_skills() -> list[dict]:
    """Load all skills from ~/.claude/skills/."""
    skills = []

    if not SKILLS_DIR.exists():
        return skills

    for skill_path in SKILLS_DIR.iterdir():
        if not skill_path.is_dir():
            continue

        skill_md = skill_path / "SKILL.md"
        prompt_md = skill_path / "prompt.md"

        if not skill_md.exists():
            continue

        # Parse frontmatter
        name = None
        description = None
        argument_hint = None
        user_invocable = False

        try:
            content = skill_md.read_text()
        except Exception:
            continue

        in_frontmatter = False
        frontmatter_text = ""

        for line in content.splitlines():
            if line.strip() == "---":
                if not in_frontmatter:
                    in_frontmatter = True
                elif in_frontmatter:
                    in_frontmatter = False
                    break
            elif in_frontmatter:
                frontmatter_text += line + "\n"

        for line in frontmatter_text.splitlines():
            if line.startswith("name:"):
                name = line.split(":", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("description:"):
                description = line.split(":", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("argument-hint:"):
                argument_hint = line.split(":", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("user_invocable:"):
                user_invocable = line.split(":", 1)[1].strip().lower() in ("true", "1", "yes")

        if not name:
            name = skill_path.name

        # Load prompt content (for execution)
        prompt_content = ""
        if prompt_md.exists():
            try:
                prompt_content = prompt_md.read_text()
            except Exception:
                prompt_content = ""

        skills.append({
            "name": name,
            "description": description or f"Clade skill: {name}",
            "argument_hint": argument_hint or "",
            "prompt_content": prompt_content,
            "user_invocable": user_invocable,
        })

    return skills


# ─── MCP Server ───────────────────────────────────────────────────────────────

app = Server(
    name=SERVER_NAME,
    version=SERVER_VERSION,
    instructions=(
        "Clade MCP Server — exposes installed Clade skills as callable tools.\n"
        "Skills are AI-augmented workflow automations installed in ~/.claude/skills/.\n"
        "Each tool call executes the skill's prompt in the current project directory.\n"
        "Use 'clade_list_skills' first to discover available skills."
    ),
)


@app.list_tools()
async def list_tools() -> list[Tool]:
    """Advertise all installed Clade skills as MCP tools."""
    skills = load_skills()

    # Always include a "list skills" tool
    tools = [
        Tool(
            name="clade_list_skills",
            description="List all available Clade skills with their descriptions. Returns name, description, and argument hints.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]

    for skill in skills:
        if not skill["prompt_content"]:
            continue  # Skip skills without prompts (no-op)

        input_schema = parse_argument_hint(skill["argument_hint"])

        tools.append(Tool(
            name=f"clade_{skill['name']}",
            description=f"{skill['description']}\n\n[argument-hint: {skill['argument_hint']}]"
                        if skill["argument_hint"] else skill["description"],
            inputSchema=input_schema,
        ))

    return tools


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
    """Execute a Clade skill tool.

    Delegates to `claude -p` with the skill's prompt content,
    passing arguments as a string appended to the prompt.
    """
    # Handle built-in tools
    if name == "clade_list_skills":
        skills = load_skills()
        lines = [f"# Available Clade Skills ({len(skills)} installed)\n"]
        for s in sorted(skills, key=lambda x: x["name"]):
            hint = f" — args: {s['argument_hint']}" if s["argument_hint"] else ""
            lines.append(f"- **{s['name']}**: {s['description']}{hint}")
        lines.append("\nTo invoke a skill, use the tool named `clade_<name>` "
                     "(e.g. clade_commit for /commit).")
        return CallToolResult(
            content=[TextContent(type="text", text="\n".join(lines))],
        )

    # Handle skill tools
    if not name.startswith("clade_"):
        return CallToolResult(
            content=[TextContent(type="text", text=f"Unknown tool: {name}")],
            isError=True,
        )

    skill_name = name[len("clade_"):]

    # Load the skill
    skills = {s["name"]: s for s in load_skills()}
    if skill_name not in skills:
        return CallToolResult(
            content=[TextContent(type="text", text=f"Skill not found: {skill_name}")],
            isError=True,
        )

    skill = skills[skill_name]
    prompt = skill["prompt_content"]

    # Build arguments string to append to prompt
    args_str = ""
    if arguments:
        for key, value in arguments.items():
            if isinstance(value, bool) and value:
                args_str += f" --{key}"
            elif isinstance(value, str) and value:
                args_str += f" --{key} {shlex.quote(value)}"
            elif value is not None:
                args_str += f" --{key} {shlex.quote(str(value))}"

    # Append arguments to prompt
    exec_prompt = prompt
    if args_str:
        exec_prompt += f"\n\n## Skill Arguments\nReceived: {args_str}\n"

    # Determine project dir (wherever the user invoked from)
    project_dir = os.getcwd()

    # Build claude command
    cmd = [
        "claude", "-p", exec_prompt,
        "--project", project_dir,
        "--dangerously-skip-permissions",
        "--output-format", "json",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 min timeout per skill
            env={**os.environ, "CLAUDE_CODE_EXPERIMENTAL_SKIP_INJECT": "1"},
        )

        if result.returncode == 0:
            # Try to parse JSON output for structured result
            try:
                output = json.loads(result.stdout)
                if isinstance(output, dict):
                    summary = output.get("summary", result.stdout[:500])
                else:
                    summary = str(output)[:500]
            except (json.JSONDecodeError, ValueError):
                summary = result.stdout[:500] if result.stdout else "(no output)"

            return CallToolResult(
                content=[TextContent(type="text", text=summary)],
            )
        else:
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=f"Skill '{skill_name}' failed (exit {result.returncode}):\n{result.stderr[:500]}"
                )],
                isError=True,
            )

    except subprocess.TimeoutExpired:
        return CallToolResult(
            content=[TextContent(
                type="text",
                text=f"Skill '{skill_name}' timed out after 300s"
            )],
            isError=True,
        )
    except FileNotFoundError:
        return CallToolResult(
            content=[TextContent(
                type="text",
                text="claude command not found. Is Claude Code installed and in PATH?"
            )],
            isError=True,
        )
    except Exception as exc:
        return CallToolResult(
            content=[TextContent(type="text", text=f"Error running skill '{skill_name}': {exc}")],
            isError=True,
        )


# ─── Entry Point ───────────────────────────────────────────────────────────────

async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
