"""
Semantic code TLDR generation and scout readiness scoring.
Leaf module — no internal project imports.
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import os
import re
import shlex
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

# ─── Semantic Code TLDR ──────────────────────────────────────────────────────

_tldr_cache: dict[str, tuple[float, str]] = {}  # dir -> (max_mtime, tldr_text)

_SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", "dist", "build",
              ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache", ".next", ".nuxt"}


def _python_func_sig(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    params = []
    for a in node.args.args:
        p = a.arg
        if a.annotation:
            try:
                p += f": {ast.unparse(a.annotation)}"
            except Exception:
                pass
        params.append(p)
    ret = ""
    if node.returns:
        try:
            ret = f" -> {ast.unparse(node.returns)}"
        except Exception:
            pass
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({', '.join(params)}){ret}"


def _parse_python_ast(source: str) -> list[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    results = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            bases = []
            for b in node.bases:
                try:
                    bases.append(ast.unparse(b))
                except Exception:
                    pass
            base_str = f"({', '.join(bases)})" if bases else ""
            results.append(f"class {node.name}{base_str}")
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    results.append(f"  {_python_func_sig(item)}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            results.append(_python_func_sig(node))
    return results


_JS_PATTERNS = [
    re.compile(r'^\s*(?:export\s+)?class\s+(\w+)'),
    re.compile(r'^\s*(?:export\s+)?(?:async\s+)?function\s+(\w[\w$]*)'),
    re.compile(r'^\s*(?:export\s+)?(?:const|let|var)\s+(\w[\w$]*)\s*=\s*(?:async\s+)?\('),
    re.compile(r'^\s*(?:export\s+default\s+)?(?:async\s+)?function\s*\('),
]


def _parse_js_ts_regex(source: str) -> list[str]:
    results = []
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("/*"):
            continue
        for pat in _JS_PATTERNS:
            m = pat.match(line)
            if m:
                # Trim to reasonable length
                sig = stripped[:120]
                if sig.endswith("{"):
                    sig = sig[:-1].rstrip()
                results.append(sig)
                break
    return results


def _generate_code_tldr(project_dir: str) -> str:
    root = Path(project_dir)
    if not root.is_dir():
        return ""

    # Check mtime-based cache
    max_mtime = 0.0
    files_to_scan: list[tuple[Path, str]] = []  # (path, ext)
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
            for fname in filenames:
                ext = Path(fname).suffix.lower()
                if ext in (".py", ".js", ".ts", ".tsx", ".jsx"):
                    fpath = Path(dirpath) / fname
                    try:
                        mt = fpath.stat().st_mtime
                        if mt > max_mtime:
                            max_mtime = mt
                        files_to_scan.append((fpath, ext))
                    except OSError:
                        pass
    except OSError:
        return ""

    cached = _tldr_cache.get(project_dir)
    if cached and cached[0] >= max_mtime:
        return cached[1]

    lines: list[str] = []
    for fpath, ext in sorted(files_to_scan, key=lambda x: str(x[0])):
        try:
            source = fpath.read_text(errors="replace")
        except OSError:
            continue
        rel = str(fpath.relative_to(root))
        if ext == ".py":
            sigs = _parse_python_ast(source)
        else:
            sigs = _parse_js_ts_regex(source)
        if sigs:
            lines.append(f"## {rel}")
            lines.extend(sigs)
            lines.append("")

    result = "\n".join(lines)
    _tldr_cache[project_dir] = (max_mtime, result)
    return result


# ─── Entity-Level TLDR Pruning (Sweep §Gap1) ─────────────────────────────────


def _extract_entity_name(stripped_line: str) -> str | None:
    """Extract entity name from a stripped TLDR line (class/function definition).

    Handles Python (class/def/async def) and JS/TS patterns.
    Returns None if the line is not an entity definition.
    """
    # Python: class Foo, def foo, async def foo
    for prefix in ("class ", "def ", "async def "):
        if stripped_line.startswith(prefix):
            rest = stripped_line[len(prefix):]
            name = re.split(r'[\s(:]', rest, 1)[0]
            return name if name else None
    # JS/TS: export class Foo, export function foo, export const foo
    m = re.match(r'(?:export\s+)?(?:async\s+)?(?:function|class)\s+(\w+)', stripped_line)
    if m:
        return m.group(1)
    m = re.match(r'(?:export\s+)?(?:const|let|var)\s+(\w[\w$]*)', stripped_line)
    if m:
        return m.group(1)
    return None


def _prune_tldr_to_entities(tldr: str, entity_names: list[str]) -> str:
    """Filter TLDR entity lines within each section to only show relevant entities.

    Sweep §Gap1: After file-level localization, further prune to entity level.
    Reduces context noise 3-5× for large files. Falls back to full TLDR on errors.

    entity_names may include "ClassName.method_name" or bare "function_name".
    For class blocks: keeps the block if the class name OR any method name matches.
    """
    if not entity_names or not tldr:
        return tldr

    # Build lookup set: both dotted and bare names, lowercase
    name_set: set[str] = set()
    for en in entity_names:
        if not en:
            continue
        parts = en.split(".")
        name_set.update(p.strip().lower() for p in parts if p.strip())

    sections = _extract_tldr_sections(tldr)
    if not sections:
        return tldr

    result_sections: list[str] = []
    for _fpath, content in sections.items():
        lines = content.splitlines()
        if not lines:
            continue
        header = lines[0]
        body = lines[1:]

        # Group body into top-level blocks: (header_line, [method_lines])
        # A block starts at a non-indented entity line; method lines are indented
        blocks: list[tuple[str, list[str]]] = []
        for line in body:
            if not line.strip():
                continue
            if not (line.startswith("  ") or line.startswith("\t")):
                blocks.append((line, []))
            elif blocks:
                blocks[-1][1].append(line)

        if not blocks:
            result_sections.append(content)
            continue

        kept_blocks: list[tuple[str, list[str]]] = []
        for top_line, method_lines in blocks:
            top_name = _extract_entity_name(top_line.strip())
            if top_name is None:
                # Unknown format — keep as-is
                kept_blocks.append((top_line, method_lines))
                continue
            top_lower = top_name.lower()
            # Keep if top entity name matches
            if top_lower in name_set:
                kept_blocks.append((top_line, method_lines))
                continue
            # Keep class block if any method name matches
            for ml in method_lines:
                mname = _extract_entity_name(ml.strip())
                if mname and mname.lower() in name_set:
                    kept_blocks.append((top_line, method_lines))
                    break

        skipped = len(blocks) - len(kept_blocks)
        if skipped == 0 or not kept_blocks:
            # Nothing pruned, or everything pruned → include original
            result_sections.append(content)
            continue

        pruned_lines = [header]
        for top_line, method_lines in kept_blocks:
            pruned_lines.append(top_line)
            pruned_lines.extend(method_lines)
        if skipped > 0:
            pruned_lines.append(f"  ... ({skipped} entities omitted — entity-localized)")
        result_sections.append("\n".join(pruned_lines))

    return "\n\n".join(result_sections) if result_sections else tldr


def _parse_fault_entity_names(fault_locs_text: str) -> list[str]:
    """Extract entity names from `_localize_fault()` formatted output.

    Parses lines like:
      - `ClassName.method_name`
      - `module.function_name`
    Returns list of dotted names for use with `_prune_tldr_to_entities`.
    """
    # Match backtick-quoted names (with optional dot separator)
    pattern = re.compile(r'`([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)`')
    return pattern.findall(fault_locs_text)


# ─── Two-Phase Task-Specific TLDR Localization (Moatless pattern) ─────────────

_LOCALIZE_PROMPT = """\
You are a code navigator. Given a task description and a codebase structure map, \
identify the top-5 most relevant files for completing the task.

Task:
{task}

Codebase structure:
{tldr}

Respond with ONLY a JSON array of file paths (relative paths as shown in the map), \
most relevant first. Example: ["path/to/file.py", "other/file.ts"]
No explanation, no markdown, just the JSON array."""


def _extract_tldr_sections(tldr: str) -> dict[str, str]:
    """Parse TLDR into a dict of {filepath: section_text}."""
    sections: dict[str, str] = {}
    current_file: str | None = None
    current_lines: list[str] = []
    for line in tldr.splitlines():
        if line.startswith("## "):
            if current_file is not None:
                sections[current_file] = "\n".join(current_lines)
            current_file = line[3:].strip()
            current_lines = [line]
        elif current_file is not None:
            current_lines.append(line)
    if current_file is not None:
        sections[current_file] = "\n".join(current_lines)
    return sections


async def _localize_tldr_for_task(
    task_description: str, tldr: str, project_dir: Path
) -> str:
    """Two-phase: pick top-5 relevant files via haiku, return filtered TLDR.

    Moatless pattern: when TLDR is large (>4KB), use haiku to narrow to the
    files most relevant to the task before injecting into context. Saves tokens
    and focuses worker attention on the right files.

    Falls back to original TLDR on any error.
    """
    sections = _extract_tldr_sections(tldr)
    if not sections:
        return tldr

    # Build a compact map for haiku (just file paths + first symbol)
    compact_lines: list[str] = []
    for fpath, content in sections.items():
        first_sym = ""
        for line in content.splitlines()[1:]:
            if line.strip():
                first_sym = line.strip()[:60]
                break
        compact_lines.append(f"{fpath}: {first_sym}")
    compact_map = "\n".join(compact_lines)

    prompt = _LOCALIZE_PROMPT.format(
        task=task_description[:600],
        tldr=compact_map[:3000],
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", prompt,
            "--model", "claude-haiku-4-5-20251001",
            "--dangerously-skip-permissions",
            "--no-input-prompt",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(project_dir),
        )
        try:
            stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return tldr

        output = stdout_bytes.decode("utf-8", errors="replace").strip()
        # Extract JSON array
        m = re.search(r'\[.*?\]', output, re.DOTALL)
        if not m:
            return tldr

        picked: list[str] = json.loads(m.group())
        if not isinstance(picked, list):
            return tldr

        # Build filtered TLDR from picked files (preserve original order)
        filtered: list[str] = []
        for fpath in picked[:5]:
            if fpath in sections:
                filtered.append(sections[fpath])
            else:
                # Fuzzy match — haiku might return slightly different paths
                for key in sections:
                    if key.endswith(fpath) or fpath.endswith(key):
                        filtered.append(sections[key])
                        break

        if not filtered:
            return tldr

        result = "\n\n".join(filtered)
        skipped = len(sections) - len(filtered)
        if skipped > 0:
            result += f"\n\n... ({skipped} files omitted — task-localized view)"
        return result

    except Exception:
        return tldr


# ─── Fault Localization Pre-pass (Agentless §6A pattern) ─────────────────────


async def _localize_fault(
    task_description: str, tldr: str, project_dir: Path
) -> str:
    """Structured fault localization pre-pass for bug-fix tasks (Agentless §6A).

    Calls haiku to predict which files and functions are most likely to need
    changes for the given task. Returns a formatted markdown block injected into
    the worker's task file to tighten focus before the repair phase.

    Falls back to empty string on any error (non-critical path).
    Only useful for fix/bug tasks — callers should gate on task type.
    """
    if not tldr or not task_description:
        return ""

    prompt = (
        "You are a code search expert. Given a bug report and codebase structure, "
        "identify the specific files and functions most likely to need changes.\n\n"
        f"Bug/Task:\n{task_description[:500]}\n\n"
        f"Codebase structure:\n{tldr[:3000]}\n\n"
        "Respond ONLY with a JSON object — no preamble, no markdown:\n"
        '{"suspect_files":["path/to/file.py"],'
        '"suspect_functions":["ClassName.method_name","module.function_name"],'
        '"reason":"one-sentence explanation of why these locations are likely"}\n'
        "List at most 3 files and 5 functions. Be specific — prefer exact names over guesses."
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", prompt,
            "--model", "claude-haiku-4-5-20251001",
            "--dangerously-skip-permissions",
            "--no-input-prompt",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(project_dir),
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return ""
        raw = out.decode("utf-8", errors="replace").strip()

        # Extract JSON from response
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if not m:
            return ""
        data = json.loads(m.group())

        files = data.get("suspect_files", [])[:3]
        funcs = data.get("suspect_functions", [])[:5]
        reason = data.get("reason", "")

        if not files and not funcs:
            return ""

        lines = ["## Suspected Change Locations (pre-localized)"]
        if reason:
            lines.append(f"> {reason}\n")
        if files:
            lines.append("**Files most likely to change:**")
            for f in files:
                lines.append(f"- `{f}`")
        if funcs:
            lines.append("\n**Functions most likely to change:**")
            for fn in funcs:
                lines.append(f"- `{fn}`")
        lines.append("\n> Focus your changes on the above locations first.")
        return "\n".join(lines)

    except Exception:
        return ""


# ─── Caller Hints (Sweep §Gap2) ──────────────────────────────────────────────


async def _find_caller_hints(fault_locs_text: str, project_dir: Path) -> str:
    """Find callers of suspect functions to warn about cascade changes (Sweep §Gap2).

    Parses `_localize_fault()` output for function names, then greps to find
    where they're called. Returns a formatted hint block or empty string.
    Falls back to empty string on any error.
    """
    if not fault_locs_text:
        return ""

    # Extract function names from "- `ClassName.method` or `module.func`" lines
    fn_pattern = re.compile(r'`(?:[A-Za-z_]\w*\.)?([A-Za-z_]\w+)\(\)`')
    func_names = fn_pattern.findall(fault_locs_text)[:4]  # max 4 functions to grep
    if not func_names:
        return ""

    caller_map: dict[str, list[str]] = {}
    for fn_name in func_names:
        try:
            proc = await asyncio.create_subprocess_exec(
                "grep", "-rn", "--include=*.py", f"\\b{fn_name}\\b",
                ".",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=str(project_dir),
            )
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()
                continue
            lines = out.decode("utf-8", errors="replace").splitlines()
            # Filter out the definition line and test files
            callers = [
                l for l in lines
                if f"def {fn_name}" not in l and "test_" not in l
            ][:5]
            if callers:
                caller_map[fn_name] = callers
        except Exception:
            pass

    if not caller_map:
        return ""

    lines = ["**Caller hints** (if you change these functions, update these call sites):"]
    for fn_name, callers in caller_map.items():
        lines.append(f"- `{fn_name}` called at:")
        for c in callers[:3]:
            # Trim to file:line: prefix
            parts = c.split(":", 2)
            if len(parts) >= 2:
                lines.append(f"  - `{parts[0]}:{parts[1]}`")
    return "\n".join(lines)


# ─── Scout Readiness Scoring ──────────────────────────────────────────────────


async def _score_task(task_id: str, description: str, db_path: Path, claude_dir: Path) -> None:
    """Background: score a task's autonomous-readiness using haiku (0-100)."""
    score_prompt = (
        "Score this task's readiness for autonomous execution by an AI agent (0-100):\n"
        "- 0-49: Needs clarification (vague goal, missing context, ambiguous scope)\n"
        "- 50-79: Acceptable (some uncertainty but workable with reasonable assumptions)\n"
        "- 80-100: Ready (clear, specific, self-contained, no ambiguity)\n\n"
        f"Task description:\n{description[:600]}\n\n"
        'Respond ONLY with a JSON object, no other text: {"score": <integer>, "note": "<max 12 words>"}'
    )
    score_file = claude_dir / f"score-{task_id}.md"
    try:
        score_file.write_text(score_prompt)
        proc = await asyncio.create_subprocess_shell(
            f'claude -p "$(cat {shlex.quote(str(score_file))})" --model claude-haiku-4-5-20251001 --dangerously-skip-permissions',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
            result = out.decode().strip()
            m = re.search(r'\{[^}]+\}', result)
            if m:
                data = json.loads(m.group())
                score = max(0, min(100, int(data.get("score", 50))))
                note = str(data.get("note", ""))[:100]
                async with aiosqlite.connect(str(db_path)) as db:
                    await db.execute(
                        "UPDATE tasks SET score = ?, score_note = ? WHERE id = ?",
                        (score, note, task_id),
                    )
                    await db.commit()
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()  # drain stdout/stderr
            out = b""
        except Exception:
            pass
    finally:
        score_file.unlink(missing_ok=True)
