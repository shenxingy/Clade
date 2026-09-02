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

import ast
import asyncio
import contextlib
import json
import os
import re
import shlex
import signal
import sys
from pathlib import Path
from typing import Any

from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)

# ─── Server Info ────────────────────────────────────────────────────────────────
SERVER_NAME = "clade"
SERVER_VERSION = "0.1.0"

# Module constants, deliberately NOT config.py:_SETTINGS_DEFAULTS entries:
# mcp_server.py is a standalone stdio entrypoint that imports nothing from the
# orchestrator package (no aiosqlite, no settings file), and adding keys here
# would drift from the generated settings reference.
SKILL_TIMEOUT_S = 300
SEARCH_TIMEOUT_S = 15

# ─── Skill Discovery ───────────────────────────────────────────────────────────

SKILLS_DIR = Path(os.path.expanduser("~/.claude/skills"))

# ─── Compact Mode (claude-cookbooks) ──────────────────────────────────────────
# Default ON: expose search-then-load (clade_list_skills / clade_search_skills /
# clade_run_skill) instead of enumerating ~95 per-skill tool definitions — the
# same system-prompt overflow Clade diagnosed in itself via the repo-root
# .mcp.json incident, now hitting Cursor/Cline users.
# Set CLADE_MCP_COMPACT=0 to restore full per-skill enumeration.


def _compact_mode() -> bool:
    return os.environ.get("CLADE_MCP_COMPACT", "1").strip().lower() not in (
        "0", "false", "no", "off"
    )


# Negative-routing clauses ("… — NOT for the corrections-rules meta-audit
# (use /audit)") must not score as positive triggers: before this strip,
# "audit corrections rules" ranked ads-audit ABOVE audit because the sibling
# skills carry the negated vocabulary verbatim. Uppercase NOT is the
# frontmatter disambiguation convention, so match it case-sensitively BEFORE
# lowercasing; the clause runs to the next delimiter (, ; . —).
_NEGATIVE_CLAUSE_RE = re.compile(r"NOT (?:for|the)\b[^,;.—]*")


def search_skills(query: str, skills: list[dict], limit: int = 20) -> list[dict]:
    """Keyword search over skill name + description + when_to_use.

    Each whitespace-separated term that appears in the haystack scores a
    point; results sorted by score (desc) then name. Empty query → [].
    when_to_use matters: several families (blog-*) keep their trigger
    phrases there rather than in description. "NOT for X (use /Y)"
    disambiguation clauses are stripped so they can't outrank /X itself.
    """
    terms = [t for t in query.lower().split() if t]
    if not terms:
        return []
    scored: list[tuple[int, dict]] = []
    for skill in skills:
        raw = f"{skill['name']} {skill['description']} {skill.get('when_to_use', '')}"
        hay = _NEGATIVE_CLAUSE_RE.sub(" ", raw).lower()
        score = sum(1 for t in terms if t in hay)
        if score:
            scored.append((score, skill))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["name"]))
    return [skill for _, skill in scored[:limit]]


def _load_frontmatter_module():
    """Load the ONE shared SKILL.md frontmatter parser (skill_frontmatter.py).

    Candidate locations:
      - same dir as this file        (installed: ~/.claude/scripts/)
      - ../configs/scripts/          (repo: orchestrator/mcp_server.py)
    install.sh deploys both files to ~/.claude/scripts/, so the sibling copy
    is always present on installed setups. Do NOT inline a fallback parser
    here — the whole point is a single parser (see validate-skills.py).
    """
    import importlib.util

    here = Path(__file__).resolve().parent
    candidates = [
        here / "skill_frontmatter.py",
        here.parent / "configs" / "scripts" / "skill_frontmatter.py",
    ]
    for path in candidates:
        if path.is_file():
            spec = importlib.util.spec_from_file_location("clade_skill_frontmatter", path)
            assert spec and spec.loader
            mod = importlib.util.module_from_spec(spec)
            sys.modules["clade_skill_frontmatter"] = mod
            spec.loader.exec_module(mod)
            return mod
    raise ImportError(
        "skill_frontmatter.py not found next to mcp_server.py or in configs/scripts/ "
        "— re-run install.sh (it deploys both to ~/.claude/scripts/)"
    )


skill_frontmatter = _load_frontmatter_module()


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
    """Load all skills from ~/.claude/skills/ via the shared frontmatter parser."""
    skills = []

    for parsed in skill_frontmatter.iter_skills(SKILLS_DIR):
        name = parsed["name"]

        # Load prompt content (for execution)
        prompt_content = ""
        prompt_md = SKILLS_DIR / name / "prompt.md"
        if prompt_md.exists():
            try:
                prompt_content = prompt_md.read_text()
            except Exception:
                prompt_content = ""

        skills.append({
            "name": name,
            "description": parsed["description"] or f"Clade skill: {name}",
            "when_to_use": parsed["when_to_use"],
            "argument_hint": parsed["argument_hint"],
            "prompt_content": prompt_content,
            "user_invocable": parsed["user_invocable"],
        })

    return skills


# ─── Bounded, non-blocking shellout ───────────────────────────────────────────
# Every handler below runs on the MCP server's single event loop, and the SDK
# dispatches tools/call concurrently (mcp.shared.jsonrpc_dispatcher spawns each
# non-inline request with start_soon). A blocking subprocess.run here freezes
# the read loop, the stdout writer, every other in-flight tool call and any
# notifications/cancelled handling for the whole timeout.


def _kill_process_group(proc: Any) -> None:
    """SIGKILL the child's whole process group, falling back to the child.

    `claude -p` spawns its own tool subprocesses; killing only the direct child
    leaves those grandchildren running and holding the pipes.
    """
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (OSError, AttributeError):
        with contextlib.suppress(Exception):
            proc.kill()


async def _run_bounded(
    cmd: list[str], *, timeout: float, env: dict[str, str] | None = None
) -> tuple[int, str, str]:
    """Spawn cmd bounded, without blocking the MCP event loop.

    Raises FileNotFoundError when the executable is missing and
    asyncio.TimeoutError on expiry — after SIGKILLing the whole process group
    and draining the pipes, so a claude run that spawned its own tools leaves
    nothing behind. CancelledError takes the same reaping path, so a cancelled
    MCP request does not leak the child either.
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        start_new_session=True,  # own group, so the kill reaches grandchildren
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        _kill_process_group(proc)
        # Bounded: if killpg fell through to proc.kill(), a surviving
        # grandchild still holds the pipe and an unbounded drain would hang
        # forever — the exact failure this function exists to remove.
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.communicate(), timeout=5)
        raise
    return (
        proc.returncode or 0,
        out.decode(errors="replace"),
        err.decode(errors="replace"),
    )


# ─── AST Code Search (AutoCodeRover §Gap1) ────────────────────────────────────

_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", "dist", "build"}
_MAX_SCAN_FILES = 500


def _iter_py_files(root: Path) -> list[Path]:
    """Walk project directory and return .py files (skipping common noise dirs)."""
    results: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in filenames:
            if fname.endswith(".py"):
                results.append(Path(dirpath) / fname)
                if len(results) >= _MAX_SCAN_FILES:
                    return results
    return results


def _func_sig(node: Any) -> str:
    """Simple function signature from an AST FunctionDef/AsyncFunctionDef node."""
    params = [a.arg for a in node.args.args]
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({', '.join(params)})"


def _ast_search_class(class_name: str, root: Path) -> str:
    """Search for a class definition using AST. Returns file:line + base classes + methods."""
    hits: list[str] = []
    for py_file in _iter_py_files(root):
        try:
            source = py_file.read_text(errors="replace")
            tree = ast.parse(source)
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                bases: list[str] = []
                for b in node.bases:
                    try:
                        bases.append(ast.unparse(b))
                    except Exception:
                        pass
                base_str = f"({', '.join(bases)})" if bases else ""
                methods = [
                    f"  {_func_sig(item)}"
                    for item in node.body
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                try:
                    rel = str(py_file.relative_to(root))
                except ValueError:
                    rel = str(py_file)
                hits.append(
                    f"**{rel}:{node.lineno}** — `class {class_name}{base_str}`\n"
                    + "\n".join(methods[:30])
                )
    return "\n\n".join(hits) if hits else f"Class `{class_name}` not found."


def _ast_search_method(method_name: str, class_name: str | None, root: Path) -> str:
    """Find a method or function by name, optionally scoped to a class."""
    hits: list[str] = []
    for py_file in _iter_py_files(root):
        try:
            source = py_file.read_text(errors="replace")
            tree = ast.parse(source)
        except Exception:
            continue
        lines = source.splitlines()
        try:
            rel = str(py_file.relative_to(root))
        except ValueError:
            rel = str(py_file)

        if class_name:
            # Scoped search: find method inside matching class
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name:
                            end = min((item.end_lineno or item.lineno + 20), item.lineno + 40)
                            snippet = "\n".join(lines[item.lineno - 1:end])
                            hits.append(f"**{rel}:{item.lineno}** (in `{class_name}`)\n```python\n{snippet}\n```")
        else:
            # Unscoped: top-level and class methods alike
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name:
                    end = min((node.end_lineno or node.lineno + 20), node.lineno + 40)
                    snippet = "\n".join(lines[node.lineno - 1:end])
                    hits.append(f"**{rel}:{node.lineno}**\n```python\n{snippet}\n```")
    return "\n\n".join(hits) if hits else f"Method `{method_name}` not found."


async def _grep_search_code(snippet: str, root: Path, context: int = 3) -> str:
    """Search for a code snippet using rg (with grep fallback)."""
    for cmd in (
        ["rg", "--no-heading", "-n", f"-C{context}", snippet, str(root)],
        ["grep", "-rn", f"--context={context}", snippet, str(root)],
    ):
        try:
            returncode, stdout, _ = await _run_bounded(cmd, timeout=SEARCH_TIMEOUT_S)
            output = stdout.strip()
            if output:
                return output[:4000]
            # grep exits 1 when no match — don't fall through to next cmd
            if returncode in (0, 1):
                return f"No matches for: {snippet!r}"
        except FileNotFoundError:
            continue
        except asyncio.TimeoutError:
            return f"Search timed out after {SEARCH_TIMEOUT_S}s for: {snippet!r}"
        except Exception as exc:
            return f"Search failed: {exc}"
    return f"Neither rg nor grep available; cannot search for: {snippet!r}"


async def list_tools() -> list[Tool]:
    """Advertise Clade skills as MCP tools.

    Compact mode (default): 3 skill tools (list/search/run) + code search.
    Enumeration mode (CLADE_MCP_COMPACT=0): one tool per installed skill.
    """
    # Always include a "list skills" tool
    tools = [
        Tool(
            name="clade_list_skills",
            description="List all available Clade skills with their descriptions. Returns name, description, and argument hints.",
            input_schema={
                "type": "object",
                "properties": {},
            },
        ),
        # Code search tools (AutoCodeRover §Gap1)
        Tool(
            name="clade_search_class",
            description=(
                "Find a class definition in the Python codebase using AST. "
                "Returns file path, line number, base classes, and method signatures."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "class_name": {
                        "type": "string",
                        "description": "Class name to search for",
                        "examples": ["Worker", "TaskQueue", "SwarmManager"],
                    },
                    "project_dir": {"type": "string", "description": "Project root (defaults to cwd)"},
                },
                "required": ["class_name"],
            },
        ),
        Tool(
            name="clade_search_method",
            description=(
                "Find a method or function definition by name. "
                "Optionally scope to a specific class. Returns file path, line, and source snippet."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "method_name": {
                        "type": "string",
                        "description": "Method or function name",
                        "examples": ["verify_and_commit", "_oracle_review", "build_task_file"],
                    },
                    "class_name": {
                        "type": "string",
                        "description": "Class name to scope the search (optional)",
                        "examples": ["Worker", "WorkerPool"],
                    },
                    "project_dir": {"type": "string", "description": "Project root (defaults to cwd)"},
                },
                "required": ["method_name"],
            },
        ),
        Tool(
            name="clade_search_code",
            description=(
                "Search for a code pattern or literal snippet in the codebase using grep. "
                "Returns matching lines with surrounding context."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "snippet": {
                        "type": "string",
                        "description": "Code pattern or literal string to search for",
                        "examples": ["GLOBAL_SETTINGS.get(", "async def _run", "raise HTTPException"],
                    },
                    "project_dir": {"type": "string", "description": "Project root (defaults to cwd)"},
                    "context_lines": {
                        "type": "integer",
                        "description": "Lines of context around each match (default: 3)",
                        "examples": [3, 5],
                    },
                },
                "required": ["snippet"],
            },
        ),
    ]

    if _compact_mode():
        # Search-then-load: 2 extra tools replace the ~95 per-skill definitions
        tools.append(Tool(
            name="clade_search_skills",
            description=(
                "Keyword-search installed Clade skills by name and description. "
                "Returns matching skills with argument hints. "
                "Execute one with clade_run_skill."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords, e.g. 'blog seo audit'",
                        "examples": ["blog seo audit", "commit push", "code review", "email write"],
                    },
                },
                "required": ["query"],
            },
        ))
        tools.append(Tool(
            name="clade_run_skill",
            description=(
                "Execute an installed Clade skill by name. Discover names via "
                "clade_list_skills or clade_search_skills."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Skill name, e.g. 'commit'",
                        "examples": ["commit", "blog-write", "seo-audit", "review-pr", "code-review"],
                    },
                    "args": {
                        "type": "string",
                        "description": "Arguments appended to the skill prompt (optional)",
                        "examples": ["--fix", "--comment", "low", "high", "ultra"],
                    },
                },
                "required": ["name"],
            },
        ))
        return tools

    for skill in load_skills():
        if not skill["prompt_content"]:
            continue  # Skip skills without prompts (no-op)

        input_schema = parse_argument_hint(skill["argument_hint"])

        tools.append(Tool(
            name=f"clade_{skill['name']}",
            description=f"{skill['description']}\n\n[argument-hint: {skill['argument_hint']}]"
                        if skill["argument_hint"] else skill["description"],
            input_schema=input_schema,
        ))

    return tools


def _format_args(arguments: dict[str, Any]) -> str:
    """Render a tool-arguments dict as a CLI-style string for the skill prompt."""
    args_str = ""
    for key, value in (arguments or {}).items():
        if isinstance(value, bool) and value:
            args_str += f" --{key}"
        elif isinstance(value, str) and value:
            args_str += f" --{key} {shlex.quote(value)}"
        elif value is not None:
            args_str += f" --{key} {shlex.quote(str(value))}"
    return args_str


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
        if _compact_mode():
            lines.append("\nRun a skill with clade_run_skill(name=..., args=...).")
        else:
            lines.append("\nTo invoke a skill, use the tool named `clade_<name>` "
                         "(e.g. clade_commit for /commit).")
        return CallToolResult(
            content=[TextContent(type="text", text="\n".join(lines))],
        )

    if name == "clade_search_skills":
        query = str(arguments.get("query", "")).strip()
        if not query:
            return CallToolResult(
                content=[TextContent(type="text", text="query is required")],
                is_error=True,
            )
        matches = search_skills(query, load_skills())
        if not matches:
            return CallToolResult(content=[TextContent(
                type="text",
                text=f"No skills match {query!r}. Try clade_list_skills for the full catalog.",
            )])
        lines = [f"# Skills matching {query!r} ({len(matches)})\n"]
        for s in matches:
            hint = f" — args: {s['argument_hint']}" if s["argument_hint"] else ""
            lines.append(f"- **{s['name']}**: {s['description']}{hint}")
        lines.append("\nRun one with clade_run_skill(name=..., args=...).")
        return CallToolResult(content=[TextContent(type="text", text="\n".join(lines))])

    if name == "clade_run_skill":
        skill_name = str(arguments.get("name", "")).strip()
        if not skill_name:
            return CallToolResult(
                content=[TextContent(type="text", text="name is required")],
                is_error=True,
            )
        raw_args = arguments.get("args", "")
        args_str = raw_args.strip() if isinstance(raw_args, str) else _format_args(raw_args or {})
        return await _execute_skill(skill_name, args_str)

    # Code search tools (AutoCodeRover §Gap1)
    _search_root = Path(arguments.get("project_dir") or os.getcwd())
    if name == "clade_search_class":
        cn = arguments.get("class_name", "").strip()
        if not cn:
            return CallToolResult(content=[TextContent(type="text", text="class_name is required")], is_error=True)
        # AST walk + ast.parse over every .py file: pure CPU, seconds on a big
        # repo. Off the loop so it cannot stall concurrent MCP requests.
        text = await asyncio.to_thread(_ast_search_class, cn, _search_root)
        return CallToolResult(content=[TextContent(type="text", text=text)])

    if name == "clade_search_method":
        mn = arguments.get("method_name", "").strip()
        if not mn:
            return CallToolResult(content=[TextContent(type="text", text="method_name is required")], is_error=True)
        cn = arguments.get("class_name") or None
        text = await asyncio.to_thread(_ast_search_method, mn, cn, _search_root)
        return CallToolResult(content=[TextContent(type="text", text=text)])

    if name == "clade_search_code":
        sp = arguments.get("snippet", "").strip()
        if not sp:
            return CallToolResult(content=[TextContent(type="text", text="snippet is required")], is_error=True)
        ctx = int(arguments.get("context_lines", 3))
        text = await _grep_search_code(sp, _search_root, ctx)
        return CallToolResult(content=[TextContent(type="text", text=text)])

    # Handle per-skill tools (enumeration mode names; kept working in compact
    # mode too so clients with cached tool lists don't break)
    if not name.startswith("clade_"):
        return CallToolResult(
            content=[TextContent(type="text", text=f"Unknown tool: {name}")],
            is_error=True,
        )

    return await _execute_skill(name[len("clade_"):], _format_args(arguments))


async def _execute_skill(skill_name: str, args_str: str) -> CallToolResult:
    """Run a skill's prompt via `claude -p` (shared by per-skill tools and the
    compact-mode clade_run_skill dispatcher)."""
    skills = {s["name"]: s for s in load_skills()}
    if skill_name not in skills:
        return CallToolResult(
            content=[TextContent(type="text", text=f"Skill not found: {skill_name}")],
            is_error=True,
        )

    skill = skills[skill_name]

    # Append arguments to prompt
    exec_prompt = skill["prompt_content"]
    if args_str:
        exec_prompt += f"\n\n## Skill Arguments\nReceived: {args_str}\n"

    # Determine project dir (wherever the user invoked from)
    project_dir = os.getcwd()

    # Build claude command. Skill executions are worker-style (skills may edit
    # files / commit), so they keep full user settings deliberately — pure
    # judges drop them via --setting-sources "" (see config.SETTING_SOURCES_NONE).
    cmd = [
        "claude", "-p", exec_prompt,
        "--project", project_dir,
        "--dangerously-skip-permissions",
        "--output-format", "json",
    ]

    try:
        returncode, stdout, stderr = await _run_bounded(
            cmd,
            timeout=SKILL_TIMEOUT_S,
            env={**os.environ, "CLAUDE_CODE_EXPERIMENTAL_SKIP_INJECT": "1"},
        )

        if returncode == 0:
            # Try to parse JSON output for structured result
            try:
                output = json.loads(stdout)
                if isinstance(output, dict):
                    summary = output.get("summary", stdout[:500])
                else:
                    summary = str(output)[:500]
            except (json.JSONDecodeError, ValueError):
                summary = stdout[:500] if stdout else "(no output)"

            return CallToolResult(
                content=[TextContent(type="text", text=summary)],
            )
        else:
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=f"Skill '{skill_name}' failed (exit {returncode}):\n{stderr[:500]}"
                )],
                is_error=True,
            )

    except asyncio.TimeoutError:
        return CallToolResult(
            content=[TextContent(
                type="text",
                text=f"Skill '{skill_name}' timed out after {SKILL_TIMEOUT_S}s"
            )],
            is_error=True,
        )
    except FileNotFoundError:
        return CallToolResult(
            content=[TextContent(
                type="text",
                text="claude command not found. Is Claude Code installed and in PATH?"
            )],
            is_error=True,
        )
    except Exception as exc:
        return CallToolResult(
            content=[TextContent(type="text", text=f"Error running skill '{skill_name}': {exc}")],
            is_error=True,
        )


# ─── MCP v2 adapters ──────────────────────────────────────────────────────────

async def _handle_list_tools(
    _ctx: ServerRequestContext,
    _params: PaginatedRequestParams | None,
) -> ListToolsResult:
    """Adapt the testable catalog function to the SDK v2 low-level contract."""
    return ListToolsResult(tools=await list_tools())


async def _handle_call_tool(
    _ctx: ServerRequestContext,
    params: CallToolRequestParams,
) -> CallToolResult:
    """Adapt typed SDK v2 params while preserving Clade's tool behavior."""
    return await call_tool(params.name, params.arguments or {})


app = Server(
    SERVER_NAME,
    version=SERVER_VERSION,
    instructions=(
        "Clade MCP Server — exposes installed Clade skills as callable tools.\n"
        "Skills are AI-augmented workflow automations installed in ~/.claude/skills/.\n"
        "Each tool call executes the skill's prompt in the current project directory.\n"
        "Use 'clade_list_skills' first to discover available skills."
    ),
    on_list_tools=_handle_list_tools,
    on_call_tool=_handle_call_tool,
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
