"""
Clade MCP Server — Exposes Clade skills as MCP tools.

Skills are loaded from two sources (merged, bundled takes priority):
  1. Bundled skills shipped with the pip package
  2. User-installed skills at ~/.claude/skills/

Usage:
  pip install clade-mcp
  # Then configure in your MCP client:
  # { "command": "clade-mcp" }
  # or: { "command": "uvx", "args": ["clade-mcp"] }
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

# Bundled skills shipped with the package
BUNDLED_SKILLS_DIR = Path(__file__).parent / "skills"

# User-installed skills (from install.sh)
USER_SKILLS_DIR = Path(os.path.expanduser("~/.claude/skills"))


def parse_argument_hint(hint: str) -> dict[str, Any]:
    """Parse SKILL.md argument-hint into a JSON Schema.

    Handles forms like:
      '[--flag]'                    -> { type: "boolean" }
      '[path]'                      -> { type: "string" }
      '[--project=slug] [message]'  -> { type: "object", properties: {...} }
    """
    if not hint.strip():
        return {"type": "object", "properties": {}}

    hint_base = hint.split("|")[0].strip()

    props = {}

    # Match [--key] or [--key=value]
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

    if props:
        return {"type": "object", "properties": props}

    return {"type": "object", "properties": {}}


def _parse_skill_dir(skill_path: Path) -> dict | None:
    """Parse a single skill directory into a skill dict."""
    skill_md = skill_path / "SKILL.md"
    prompt_md = skill_path / "prompt.md"

    if not skill_md.exists():
        return None

    name = None
    description = None
    argument_hint = None
    user_invocable = False

    try:
        content = skill_md.read_text()
    except Exception:
        return None

    # Parse frontmatter
    in_frontmatter = False
    frontmatter_text = ""

    for line in content.splitlines():
        if line.strip() == "---":
            if not in_frontmatter:
                in_frontmatter = True
            else:
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

    prompt_content = ""
    if prompt_md.exists():
        try:
            prompt_content = prompt_md.read_text()
        except Exception:
            prompt_content = ""

    return {
        "name": name,
        "description": description or f"Clade skill: {name}",
        "argument_hint": argument_hint or "",
        "prompt_content": prompt_content,
        "user_invocable": user_invocable,
    }


def load_skills() -> list[dict]:
    """Load skills from bundled + user directories. Bundled takes priority on conflict."""
    skills_by_name: dict[str, dict] = {}

    # Load user skills first (lower priority)
    if USER_SKILLS_DIR.exists():
        for skill_path in USER_SKILLS_DIR.iterdir():
            if not skill_path.is_dir():
                continue
            skill = _parse_skill_dir(skill_path)
            if skill:
                skills_by_name[skill["name"]] = skill

    # Load bundled skills (higher priority — overrides user on conflict)
    if BUNDLED_SKILLS_DIR.exists():
        for skill_path in BUNDLED_SKILLS_DIR.iterdir():
            if not skill_path.is_dir():
                continue
            skill = _parse_skill_dir(skill_path)
            if skill:
                skills_by_name[skill["name"]] = skill

    return list(skills_by_name.values())


# ─── MCP Server ───────────────────────────────────────────────────────────────

app = Server(
    name=SERVER_NAME,
    version=SERVER_VERSION,
    instructions=(
        "Clade MCP Server — exposes installed Clade skills as callable tools.\n"
        "Skills are AI-augmented workflow automations for the full software development lifecycle.\n"
        "Each tool call executes the skill's prompt in the current project directory.\n"
        "Use 'clade_list_skills' first to discover available skills.\n\n"
        "Homepage: https://github.com/shenxingy/clade"
    ),
)


@app.list_tools()
async def list_tools() -> list[Tool]:
    """Advertise all Clade skills as MCP tools."""
    skills = load_skills()

    tools = [
        Tool(
            name="clade_list_skills",
            description="List all available Clade skills with descriptions and argument hints.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]

    for skill in skills:
        if not skill["prompt_content"]:
            continue

        input_schema = parse_argument_hint(skill["argument_hint"])

        desc = skill["description"]
        if skill["argument_hint"]:
            desc += f"\n\n[argument-hint: {skill['argument_hint']}]"

        tools.append(Tool(
            name=f"clade_{skill['name']}",
            description=desc,
            inputSchema=input_schema,
        ))

    return tools


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
    """Execute a Clade skill tool via `claude -p`."""

    # Built-in: list skills
    if name == "clade_list_skills":
        skills = load_skills()
        lines = [f"# Available Clade Skills ({len(skills)} installed)\n"]
        for s in sorted(skills, key=lambda x: x["name"]):
            hint = f" — args: {s['argument_hint']}" if s["argument_hint"] else ""
            lines.append(f"- **{s['name']}**: {s['description']}{hint}")
        lines.append(
            "\nTo invoke a skill, use the tool named `clade_<name>` "
            "(e.g. clade_commit for /commit)."
        )
        return CallToolResult(
            content=[TextContent(type="text", text="\n".join(lines))],
        )

    # Validate tool name
    if not name.startswith("clade_"):
        return CallToolResult(
            content=[TextContent(type="text", text=f"Unknown tool: {name}")],
            isError=True,
        )

    skill_name = name[len("clade_"):]
    skills = {s["name"]: s for s in load_skills()}

    if skill_name not in skills:
        return CallToolResult(
            content=[TextContent(type="text", text=f"Skill not found: {skill_name}")],
            isError=True,
        )

    skill = skills[skill_name]
    prompt = skill["prompt_content"]

    # Build arguments string
    args_str = ""
    if arguments:
        for key, value in arguments.items():
            if isinstance(value, bool) and value:
                args_str += f" --{key}"
            elif isinstance(value, str) and value:
                args_str += f" --{key} {shlex.quote(value)}"
            elif value is not None:
                args_str += f" --{key} {shlex.quote(str(value))}"

    exec_prompt = prompt
    if args_str:
        exec_prompt += f"\n\n## Skill Arguments\nReceived: {args_str}\n"

    project_dir = os.getcwd()

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
            timeout=300,
            env={**os.environ, "CLAUDE_CODE_EXPERIMENTAL_SKIP_INJECT": "1"},
        )

        if result.returncode == 0:
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
            content=[TextContent(type="text", text=f"Skill '{skill_name}' timed out after 300s")],
            isError=True,
        )
    except FileNotFoundError:
        return CallToolResult(
            content=[TextContent(
                type="text",
                text="claude CLI not found. Install Claude Code first: https://docs.anthropic.com/en/docs/claude-code"
            )],
            isError=True,
        )
    except Exception as exc:
        return CallToolResult(
            content=[TextContent(type="text", text=f"Error running skill '{skill_name}': {exc}")],
            isError=True,
        )


# ─── Entry Point ───────────────────────────────────────────────────────────────

async def run_server() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )
