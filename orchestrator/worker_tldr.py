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
