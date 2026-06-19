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

# fault_localize is a stdlib-only leaf (lower in the DAG); importing it keeps
# worker_tldr standalone-importable. Shared scan constants + symbol index live
# there so the multi-language SBFL path and the Python path agree.
from fault_localize import (  # noqa: E402
    _SKIP_DIRS, _SRC_EXTS, _build_symbol_index, _is_test_file_name,
    detect_test_runner, run_runner_sbfl,
)

logger = logging.getLogger(__name__)

# Model for TLDR/localization/scoring claude calls. This is a documented leaf
# (no project imports — config included), so worker.py overwrites this at
# import time with config.HAIKU_MODEL (the pinned dated snapshot). The alias
# fallback keeps standalone imports (tests, REPL) working via the claude CLI.
HAIKU_MODEL = "haiku"

# Pure-judge containment: every claude -p call in this module has its stdout
# parsed (JSON / code extraction) — user settings must not load, or a
# prompt-type Stop hook's {"ok":true} reply replaces the real answer (see
# config.SETTING_SOURCES_NONE, commit 386a862). worker.py re-asserts this at
# import time (leaf module — cannot import config). Exec-argv sites expand it
# via shlex.split().
SETTING_SOURCES_NONE = '--setting-sources ""'
# Judges must not mutate files — denies Edit, Write, Bash. Leaf default mirrors
# config.DISALLOWED_TOOLS_JUDGE; worker.py re-asserts at import time.
DISALLOWED_TOOLS_JUDGE = "--disallowed-tools Edit,Write,Bash"

# ─── Semantic Code TLDR ──────────────────────────────────────────────────────

_tldr_cache: dict[str, tuple[float, str]] = {}  # dir -> (max_mtime, tldr_text)



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


# Control-flow keywords the indented-method pattern must not mistake for a method.
_JS_KEYWORDS = {
    "if", "for", "while", "switch", "catch", "return", "function", "await",
    "typeof", "new", "else", "do", "with", "yield", "constructor",
}
_JS_PATTERNS = [
    re.compile(r'^\s*(?:export\s+(?:default\s+)?)?(?:abstract\s+)?class\s+(\w+)'),
    re.compile(r'^\s*(?:export\s+)?interface\s+(\w+)'),           # TS interface
    re.compile(r'^\s*(?:export\s+)?type\s+(\w+)\s*='),            # TS type alias
    re.compile(r'^\s*(?:export\s+)?(?:const\s+)?enum\s+(\w+)'),   # TS enum
    re.compile(r'^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s*\*?\s*(\w[\w$]*)'),
    # const/let/var X = ...  (arrow w/ or w/o parens, or a top-level value)
    re.compile(r'^\s*(?:export\s+(?:default\s+)?)?(?:const|let|var)\s+(\w[\w$]*)'),
    # indented class method:  name(args) {  /  name(args): Ret {  (keyword-guarded)
    re.compile(r'^\s+(?:public\s+|private\s+|protected\s+|readonly\s+|static\s+|async\s+|get\s+|set\s+)*(\w[\w$]*)\s*\([^;]*\)\s*[:{]'),
]


def _parse_js_ts_regex(source: str) -> list[str]:
    results = []
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*"):
            continue
        for pat in _JS_PATTERNS:
            m = pat.match(line)
            if m:
                # Guard: skip control-flow that looks like a method call.
                if m.groups() and m.group(1) in _JS_KEYWORDS:
                    continue
                # Trim to reasonable length
                sig = stripped[:120]
                if sig.endswith("{"):
                    sig = sig[:-1].rstrip()
                results.append(sig)
                break
    return results


# ─── Multi-language AST via tree-sitter (audit 2026-06-18; multi-lang unlock) ──
# Python uses the stdlib `ast`; JS/TS have a regex fallback. For Go/Rust/Java/etc.
# Clade was BLIND (no TLDR at all). tree-sitter gives real AST for ~any language.
# OPTIONAL by design: each `tree_sitter_<lang>` package is lazy-imported; if a
# language's grammar isn't installed the file falls back (regex for js/ts, skip
# otherwise), so CI / fresh installs without these wheels keep working unchanged.

# Languages that were previously BLIND (no TLDR at all). JS/TS deliberately stay
# on the tuned regex (_parse_js_ts_regex) — it catches the `export const x = …`
# idiom (schemas, arrow fns) that a function/class/interface node-set misses.
_TS_EXT_TO_MODULE = {
    ".go": "tree_sitter_go", ".rs": "tree_sitter_rust", ".java": "tree_sitter_java",
    ".rb": "tree_sitter_ruby", ".c": "tree_sitter_c", ".h": "tree_sitter_c",
    ".cpp": "tree_sitter_cpp", ".cc": "tree_sitter_cpp", ".hpp": "tree_sitter_cpp",
    ".cs": "tree_sitter_c_sharp", ".php": "tree_sitter_php",
}
_JS_TS_EXTS = (".js", ".ts", ".tsx", ".jsx")
# Exact tree-sitter node types that denote a top-level definition (across grammars).
_TS_DEF_NODE_TYPES = {
    "function_declaration", "function_definition", "function_item", "method_declaration",
    "method_definition", "method", "constructor_declaration", "function_signature_item",
    "class_declaration", "class_definition", "class_specifier", "class",
    "struct_item", "struct_specifier", "struct_declaration",
    "interface_declaration", "trait_item", "enum_declaration", "enum_item",
    "enum_specifier", "type_declaration", "type_alias_declaration", "type_item",
    "impl_item", "mod_item", "module", "namespace_definition",
}
_TS_BARE_KEYWORDS = {
    "class", "struct", "impl", "module", "method", "interface", "enum",
    "trait", "type", "func", "fn", "def", "namespace",
}
_ts_parser_cache: dict[str, Any] = {}  # module_name → Parser | None


def _get_ts_parser(module_name: str) -> Any:
    """Lazily build + cache a tree-sitter Parser for a language module. Returns
    None when tree-sitter or the grammar package isn't installed (graceful)."""
    if module_name in _ts_parser_cache:
        return _ts_parser_cache[module_name]
    parser = None
    try:
        import importlib
        import tree_sitter as ts
        mod = importlib.import_module(module_name)
        # Most expose language(); typescript/php export language_<variant>().
        lang_fn = getattr(mod, "language", None)
        if lang_fn is None:
            for attr in dir(mod):
                if attr.startswith("language") and callable(getattr(mod, attr)):
                    lang_fn = getattr(mod, attr)
                    break
        parser = ts.Parser(ts.Language(lang_fn())) if lang_fn else None
    except Exception:
        parser = None
    _ts_parser_cache[module_name] = parser
    return parser


def _parse_with_treesitter(source: str, ext: str) -> list[str] | None:
    """Extract definition signatures (one line each) via tree-sitter AST.
    Returns None when no parser is available for `ext` (caller falls back)."""
    module_name = _TS_EXT_TO_MODULE.get(ext)
    if not module_name:
        return None
    parser = _get_ts_parser(module_name)
    if parser is None:
        return None
    try:
        data = source.encode("utf-8", errors="replace")
        tree = parser.parse(data)
    except Exception:
        return None
    sigs: list[str] = []
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if node.type in _TS_DEF_NODE_TYPES:
            first_line = data[node.start_byte:node.end_byte].split(b"\n", 1)[0]
            sig = first_line.decode("utf-8", errors="replace").strip().rstrip("{").strip()[:120]
            # Skip bare keyword nodes (a `class`/`struct` token shares the node
            # type name with a real definition in some grammars).
            if sig and sig.lower() not in _TS_BARE_KEYWORDS and sig not in seen:
                seen.add(sig)
                sigs.append(sig)
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return sigs


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
                if ext == ".py" or ext in _JS_TS_EXTS or ext in _TS_EXT_TO_MODULE:
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

    sig = (max_mtime, len(files_to_scan))  # count → invalidate on deletion too
    cached = _tldr_cache.get(project_dir)
    if cached and cached[0] == sig:
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
            # Prefer real AST (tree-sitter) for any installed grammar; fall back
            # to the JS/TS regex when tree-sitter/grammar is absent (graceful).
            sigs = _parse_with_treesitter(source, ext)
            if sigs is None:
                sigs = _parse_js_ts_regex(source) if ext in _JS_TS_EXTS else []
        if sigs:
            lines.append(f"## {rel}")
            lines.extend(sigs)
            lines.append("")

    result = "\n".join(lines)
    _tldr_cache[project_dir] = (sig, result)
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


# ─── Hybrid Keyword Pre-Filter (Sweep §Gap4) ─────────────────────────────────


# ─── Deterministic repo-map centrality (Aider PageRank; audit 2026-06-18) ────
# Keyword + LLM localization misses central-but-keyword-poor files (a base class
# everything inherits, a shared config). PageRank over the import graph surfaces
# them — deterministic, reproducible, no LLM call. mtime-cached like the TLDR.

_pagerank_cache: dict[str, tuple[float, dict[str, float]]] = {}


def _pagerank(graph: dict[str, set[str]], damping: float = 0.85, iters: int = 20) -> dict[str, float]:
    """Power-iteration PageRank. Edge A→B means 'A imports B', so B accrues rank
    and widely-imported files score highest. Scores normalized to 0..1 (max=1)."""
    nodes = list(graph)
    n = len(nodes)
    if n == 0:
        return {}
    incoming: dict[str, list[str]] = {x: [] for x in nodes}
    outdeg: dict[str, int] = {x: len(graph[x]) for x in nodes}
    for src, dsts in graph.items():
        for d in dsts:
            if d in incoming:
                incoming[d].append(src)
    rank = {x: 1.0 / n for x in nodes}
    base = (1.0 - damping) / n
    for _ in range(iters):
        dangling = damping * sum(rank[x] for x in nodes if outdeg[x] == 0) / n
        rank = {
            x: base + dangling + damping * sum(
                rank[s] / outdeg[s] for s in incoming[x] if outdeg[s]
            )
            for x in nodes
        }
    mx = max(rank.values()) if rank else 0.0
    return {x: (rank[x] / mx if mx > 0 else 0.0) for x in nodes}


# ─── Multi-language import extraction for PageRank (audit 2026-06-19) ─────────
# Imports are simple top-of-file syntax, so regex extraction of the module STRING
# is reliable and dependency-free (tree-sitter's value is in TLDR signatures, not
# import strings). The resolver maps each module string to an in-repo file.
_PAGERANK_EXTS = (".py", ".go", ".rs", ".ts", ".tsx", ".js", ".jsx", ".java")
_RS_USE_RE = re.compile(r'\buse\s+((?:crate|self|super|\w+)(?:::\w+)*(?:::\{[^}]*\})?)')
_JS_IMPORT_RE = re.compile(
    r'''(?:\bfrom\s*|\brequire\(\s*|\bimport\(\s*|^\s*import\s*)['"]([^'"]+)['"]''', re.M)
_JAVA_IMPORT_RE = re.compile(r'^\s*import\s+(?:static\s+)?([\w.*]+)\s*;', re.M)
_GO_MOD_RE = re.compile(r'^\s*module\s+(\S+)', re.M)
_LINE_COMMENT_RE = re.compile(r'//[^\n]*')
_BLOCK_COMMENT_RE = re.compile(r'/\*.*?\*/', re.S)


def _strip_c_comments(text: str) -> str:
    """Drop // and /* */ comments so commented-out imports don't create phantom
    edges. (Lossy on // inside string literals — acceptable for import scanning.)"""
    return _LINE_COMMENT_RE.sub('', _BLOCK_COMMENT_RE.sub('', text))


def _imports_go(text: str) -> set[str]:
    text = _strip_c_comments(text)
    out: set[str] = set()
    for m in re.finditer(r'^\s*import\s+(?:[\w.]+\s+)?"([^"]+)"', text, re.M):
        out.add(m.group(1))
    for blk in re.finditer(r'import\s*\((.*?)\)', text, re.S):
        out.update(re.findall(r'"([^"]+)"', blk.group(1)))
    return out


def _resolve_import(spec: str, ext: str, src_rel: str,
                    relset: set[str], go_module: str | None) -> set[str]:
    """Map one import specifier to in-repo target relpaths (best-effort, lossy)."""
    targets: set[str] = set()
    if ext == ".go":
        if go_module and spec.startswith(go_module):
            sub = spec[len(go_module):].strip("/")
            for r in relset:
                if r.endswith(".go") and r.rsplit("/", 1)[0] == sub:
                    targets.add(r)
    elif ext == ".rs":
        # Only crate-relative paths refer to in-project modules; a bare `use foo`
        # is an external crate (2018+ edition) — don't collide with a local `foo`.
        if not spec.startswith(("crate::", "self::", "super::")):
            return targets
        parts = [p for p in spec.split("::") if p not in ("crate", "self", "super", "")]
        if parts:
            mod = "/".join(parts)
            for cand in (f"src/{mod}.rs", f"src/{mod}/mod.rs", f"src/{'/'.join(parts[:-1])}.rs", f"{mod}.rs"):
                if cand in relset:
                    targets.add(cand)
    elif ext in (".ts", ".tsx", ".js", ".jsx"):
        if spec.startswith("."):  # relative only — bare specifiers are deps, skip
            base = os.path.normpath(os.path.join(os.path.dirname(src_rel), spec)).replace("\\", "/")
            for cand in (base, *(f"{base}{e}" for e in (".ts", ".tsx", ".js", ".jsx")),
                         *(f"{base}/index{e}" for e in (".ts", ".tsx", ".js", ".jsx"))):
                if cand in relset:
                    targets.add(cand)
    elif ext == ".java":
        if spec.endswith(".*"):  # wildcard import → all files in that package dir
            pkgdir = spec[:-2].replace(".", "/")
            for r in relset:
                if r.endswith(".java") and r.rsplit("/", 1)[0].endswith(pkgdir):
                    targets.add(r)
        else:
            tail = spec.replace(".", "/") + ".java"
            for r in relset:
                if r.endswith(tail):
                    targets.add(r)
    return targets


def _file_import_targets(text: str, ext: str, src_rel: str,
                         relset: set[str], py_stem_to_rel: dict[str, str],
                         go_module: str | None) -> set[str]:
    """All in-repo files imported by one source file."""
    targets: set[str] = set()
    if ext == ".py":
        try:
            tree = ast.parse(text)
        except Exception:
            return targets
        for node in ast.walk(tree):
            mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                    else [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            for m in mods:
                tgt = py_stem_to_rel.get(m) or py_stem_to_rel.get(m.rsplit(".", 1)[-1])
                if tgt:
                    targets.add(tgt)
        return targets
    if ext == ".go":
        specs = _imports_go(text)
    elif ext == ".rs":
        specs = set()
        for s in _RS_USE_RE.findall(text):
            if "{" in s:  # use crate::a::{b, c::D} → crate::a::b, crate::a::c
                prefix, _, grp = s.partition("{")
                for member in grp.rstrip("}").split(","):
                    seg = member.strip().split("::", 1)[0].strip()
                    if seg and seg not in ("*", "self"):
                        specs.add(prefix + seg)
            else:
                specs.add(s)
    elif ext in (".ts", ".tsx", ".js", ".jsx"):
        specs = set(_JS_IMPORT_RE.findall(_strip_c_comments(text)))
    elif ext == ".java":
        specs = set(_JAVA_IMPORT_RE.findall(text))
    else:
        specs = set()
    for spec in specs:
        targets |= _resolve_import(spec, ext, src_rel, relset, go_module)
    return targets


def _pagerank_centrality(project_dir: str, max_files: int = 1200) -> dict[str, float]:
    """Build a MULTI-LANGUAGE import graph and rank files by PageRank centrality.

    Imports across Python/Go/Rust/JS/TS/Java are extracted and resolved to repo
    files; widely-imported files (base classes, shared config) score high.
    Returns {posix_relpath: score 0..1}. Empty on a missing/too-large repo."""
    root = Path(project_dir)
    if not root.is_dir():
        return {}
    files: list[Path] = []
    max_mtime = 0.0
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
            for fn in filenames:
                if fn.endswith(_PAGERANK_EXTS):
                    p = Path(dirpath) / fn
                    try:
                        max_mtime = max(max_mtime, p.stat().st_mtime)
                    except OSError:
                        continue
                    files.append(p)
    except OSError:
        return {}
    if not files or len(files) > max_files:
        return {}

    sig = (max_mtime, len(files))  # count → invalidate on deletion too
    cached = _pagerank_cache.get(project_dir)
    if cached and cached[0] == sig:
        return cached[1]

    rel = {p.relative_to(root).as_posix(): p for p in files}
    relset = set(rel)
    py_stem_to_rel: dict[str, str] = {}
    for r in rel:
        if r.endswith(".py"):
            py_stem_to_rel.setdefault(r[:-3].replace("/", "."), r)
            py_stem_to_rel.setdefault(r[:-3].rsplit("/", 1)[-1], r)
    go_module = None
    gomod = root / "go.mod"
    if gomod.exists():
        m = _GO_MOD_RE.search(gomod.read_text(errors="replace"))
        go_module = m.group(1) if m else None

    graph: dict[str, set[str]] = {r: set() for r in rel}
    for r, p in rel.items():
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        for tgt in _file_import_targets(text, p.suffix, r, relset, py_stem_to_rel, go_module):
            if tgt != r and tgt in graph:
                graph[r].add(tgt)

    scores = _pagerank(graph)
    _pagerank_cache[project_dir] = (sig, scores)
    return scores


def _keyword_filter_tldr(
    task_description: str, tldr: str, max_sections: int = 15,
    centrality: dict[str, float] | None = None,
) -> str:
    """Pre-filter TLDR sections by keyword matching before haiku structural selection.

    Sweep §Gap4: Hybrid retrieval — keyword grep provides a first-pass signal;
    haiku then applies structural understanding over the reduced result set.
    Falls back to full TLDR if fewer than 3 sections match (not enough signal).
    """
    # Extract code-like identifiers from task (snake_case, CamelCase, module names)
    keywords: set[str] = set()
    for word in re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b', task_description):
        keywords.add(word.lower())
    # Also include quoted strings as exact keywords
    for quoted in re.findall(r'["\']([a-zA-Z_][a-zA-Z0-9_]{2,})["\']', task_description):
        keywords.add(quoted.lower())

    if not keywords:
        return tldr

    sections = _extract_tldr_sections(tldr)
    if not sections:
        return tldr

    # Score each section by keyword hits, boosted by PageRank centrality so a
    # central-but-keyword-poor file (base class, shared config) still surfaces.
    scored: list[tuple[float, int, float, str, str]] = []
    for fpath, content in sections.items():
        content_lower = content.lower()
        kw = sum(1 for kwd in keywords if kwd in content_lower)
        cen = centrality.get(fpath.replace("\\", "/"), 0.0) if centrality else 0.0
        scored.append((kw + 2.0 * cen, kw, cen, fpath, content))

    scored.sort(key=lambda x: -x[0])

    # Keep sections with a keyword hit OR high centrality (deterministic safety
    # net — a top-central file is never pruned just for missing the keywords).
    matching = [t for t in scored if t[1] > 0 or t[2] >= 0.5]
    if len(matching) < 3:
        # Too sparse — return original to avoid over-filtering
        return tldr

    kept = matching[:max_sections]
    result = "\n\n".join(t[4] for t in kept)
    skipped = len(sections) - len(kept)
    if skipped > 0:
        result += f"\n\n... ({skipped} files omitted — keyword pre-filtered)"
    return result


# ─── Two-Phase Task-Specific TLDR Localization (Moatless pattern) ─────────────

# Localizer prompt window. Was 3000 (~750 tokens) — the audit (2026-06-18) found
# that on a few-hundred-file repo the relevant file is often past the cutoff, so
# the localizer never sees it. 8000 (~2k tokens) is still cheap for haiku.
_LOCALIZE_MAP_CHARS = 8000

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


# ─── Span-Level FileContext with Token Budgeting (Moatless §Gap3) ────────────


def _span_evict_tldr(
    tldr: str,
    budget_chars: int,
    priority_files: list[str] | None = None,
) -> tuple[str, int]:
    """Evict low-priority file spans when TLDR exceeds budget_chars.

    Moatless FileContext pattern: treat each file section as a span. Always
    preserve priority_files (e.g. from fault localization); evict others
    greedily until within budget.

    Returns (evicted_tldr, n_evicted). When n_evicted > 0, callers should
    inject a retrieval hint instructing workers to use clade_search_* MCP tools.
    """
    if not tldr or len(tldr) <= budget_chars:
        return tldr, 0

    sections = _extract_tldr_sections(tldr)
    if not sections:
        return tldr[:budget_chars], 0

    priority_set: set[str] = set()
    if priority_files:
        for pf in priority_files:
            # Match on basename or suffix to be robust to path differences
            for key in sections:
                if key == pf or key.endswith(f"/{pf}") or pf.endswith(f"/{key}"):
                    priority_set.add(key)

    kept: list[str] = []
    remaining_budget = budget_chars
    n_evicted = 0

    # Pass 1: always include priority spans
    for fname, section_text in sections.items():
        if fname in priority_set:
            kept.append(section_text)
            remaining_budget -= len(section_text) + 1  # +1 for newline separator

    # Pass 2: fill remaining budget with non-priority sections (original order)
    for fname, section_text in sections.items():
        if fname in priority_set:
            continue
        cost = len(section_text) + 1
        if remaining_budget >= cost:
            kept.append(section_text)
            remaining_budget -= cost
        else:
            n_evicted += 1

    return "\n".join(kept), n_evicted


async def _localize_tldr_for_task(
    task_description: str, tldr: str, project_dir: Path
) -> str:
    """Hybrid: keyword pre-filter + haiku structural selection → top-5 relevant files.

    Moatless pattern: when TLDR is large (>4KB), use haiku to narrow to the
    top-5 most relevant files for this task. Saves tokens and focuses worker.

    Sweep §Gap4: now runs a keyword pre-filter first. If the task contains code
    identifiers, TLDR is pre-filtered to files that mention them. Haiku then
    applies structural understanding over the reduced result set — two-signal
    retrieval improves precision for complex queries.

    Falls back to original TLDR on any error.
    """
    # Sweep §Gap4: keyword pre-filter before haiku (hybrid retrieval), now
    # boosted by deterministic PageRank centrality (audit 2026-06-18) so central
    # files survive the keyword filter even when keyword-poor.
    centrality = _pagerank_centrality(str(project_dir))
    candidate_tldr = _keyword_filter_tldr(task_description, tldr, centrality=centrality)
    sections = _extract_tldr_sections(candidate_tldr)
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
        tldr=compact_map[:_LOCALIZE_MAP_CHARS],
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", prompt,
            "--model", HAIKU_MODEL,
            "--dangerously-skip-permissions",
            "--no-input-prompt",
            *shlex.split(SETTING_SOURCES_NONE),
            *shlex.split(DISALLOWED_TOOLS_JUDGE),
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
        f"Codebase structure:\n{tldr[:_LOCALIZE_MAP_CHARS]}\n\n"
        "Respond ONLY with a JSON object — no preamble, no markdown:\n"
        '{"suspect_files":["path/to/file.py"],'
        '"suspect_functions":["ClassName.method_name","module.function_name"],'
        '"reason":"one-sentence explanation of why these locations are likely"}\n'
        "List at most 3 files and 5 functions. Be specific — prefer exact names over guesses."
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", prompt,
            "--model", HAIKU_MODEL,
            "--dangerously-skip-permissions",
            "--no-input-prompt",
            *shlex.split(SETTING_SOURCES_NONE),
            *shlex.split(DISALLOWED_TOOLS_JUDGE),
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


# ─── SBFL Pre-pass: Failing Test Traceback Analysis (AutoCodeRover §Gap3) ─────


# ─── Assertion-aware SBFL (audit 2026-06-18; found blind in the owlcast run) ──
# A pure assertion failure (`assert foo(x) == y`, foo returns the wrong value
# with NO exception) leaves only the TEST frame in the traceback — the impl
# symbol lives only in the assert SOURCE LINE, invisible to a frame-frequency
# parser. So: parse the failing test's source, find the enclosing test function,
# extract the impl symbols it calls (nearest the failing line first), and resolve
# them to suspect files. Language-agnostic in spirit — the test names its target.

_PY_NONIMPL = {
    "len", "str", "int", "list", "dict", "set", "tuple", "print", "range", "sorted",
    "enumerate", "zip", "map", "filter", "isinstance", "getattr", "setattr", "super",
    "repr", "type", "abs", "min", "max", "sum", "any", "all", "open", "format", "bool",
    "float", "approx", "raises", "fixture", "mark", "fail", "skip", "warns",
    # unittest / mock helpers (assert*/expect* also filtered by prefix below)
    "setUp", "tearDown", "patch", "Mock", "MagicMock", "mock_open", "monkeypatch",
    "caplog", "capsys", "call", "ANY", "sentinel", "subTest", "addCleanup",
}
# _SRC_EXTS / _build_symbol_index now live in fault_localize (imported above) so the
# Python and multi-language SBFL paths share one cross-language symbol resolver.


def _assertion_suspects(output: str, project_dir: Path, blocks: list[str]) -> dict[str, int]:
    """Suspects inferred from the failing test's SOURCE when the traceback has no
    impl frame (assertion failures). Returns {file::symbol: distinct_failing_tests}."""
    suspects: dict[str, int] = {}
    frame_re = re.compile(r'(?P<fpath>[^\s:][^:\s]*\.py):(?P<line>\d+): in (?P<fn>\w+)')
    index: dict[str, str] | None = None
    for block in blocks:
        frames = list(frame_re.finditer(block))
        # The assert site is the last TEST frame in the block (test_ function or
        # a test/conftest file by naming convention — not the "test" substring).
        test_frames = [
            m for m in frames
            if m.group("fn").startswith("test_")
            or _is_test_file_name(m.group("fpath").rsplit("/", 1)[-1])
        ]
        if not test_frames:
            continue
        tf = test_frames[-1]
        fail_line = int(tf.group("line"))
        fpath = tf.group("fpath")
        test_file = Path(fpath) if Path(fpath).is_absolute() else project_dir / fpath
        try:
            tree = ast.parse(test_file.read_text(errors="replace"))
        except Exception:
            continue
        enc = None  # innermost test function containing the failing line
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.lineno <= fail_line <= (node.end_lineno or node.lineno):
                    if enc is None or node.lineno > enc.lineno:
                        enc = node
        if enc is None:
            continue
        calls: list[tuple[int, str]] = []
        for n in ast.walk(enc):
            if isinstance(n, ast.Call):
                name = (n.func.id if isinstance(n.func, ast.Name)
                        else n.func.attr if isinstance(n.func, ast.Attribute) else None)
                if (name and len(name) >= 2 and not name.startswith(("test_", "assert", "expect"))
                        and name not in _PY_NONIMPL):
                    calls.append((abs((n.lineno or fail_line) - fail_line), name))
        if not calls:
            continue
        calls.sort()
        if index is None:
            index = _build_symbol_index(project_dir)
        chosen: set[str] = set()
        for _, name in calls:
            if name in chosen:
                continue
            chosen.add(name)
            f = index.get(name)
            if f:
                suspects[f"{f}::{name}"] = suspects.get(f"{f}::{name}", 0) + 1
            if len(chosen) >= 3:
                break
    return suspects


async def _sbfl_prepass(project_dir: Path, timeout: int = 30) -> str:
    """Simplified SBFL pre-pass: run pytest, parse failing test tracebacks.

    AutoCodeRover §Gap3: Inject ranked suspect locations derived from failing tests
    BEFORE the first patch attempt. Avoids the expensive full Ochiai scoring by
    using traceback frequency as a lightweight proxy for suspiciousness.

    Process:
    1. Run pytest --tb=short with short timeout (non-destructive, read-only)
    2. Parse tracebacks: extract file:line:function triplets
    3. Score by frequency — functions appearing in most failure tracebacks first
    4. Return formatted context block with top-5 suspects

    Falls back to empty string if no pytest, no failures, or timeout.
    Only called for fix tasks with an existing test suite.

    Multi-language (2026-06-19): non-Python projects (Go/Rust/JS/TS detected via
    .claude/orchestrator.json test_cmd or file sniff) route to fault_localize's
    runner-specific SBFL. The Python path below is unchanged.
    """
    runner = detect_test_runner(Path(project_dir))
    if runner and runner["kind"] != "pytest":
        return await run_runner_sbfl(Path(project_dir), runner, timeout=max(timeout, 60))

    # Find pytest
    venv_pytest = project_dir / ".venv" / "bin" / "pytest"
    if venv_pytest.exists():
        pytest_cmd = [str(venv_pytest)]
    else:
        pytest_cmd = ["python", "-m", "pytest"]

    try:
        proc = await asyncio.create_subprocess_exec(
            *pytest_cmd, "--tb=short", "-q", "--no-header",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(project_dir),
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return ""

        if proc.returncode == 0:
            return ""  # All tests pass — no suspects needed

        output = out.decode("utf-8", errors="replace")
    except Exception:
        return ""

    # Parse tracebacks: match "  File 'path/file.py', line N, in function_name"
    # and "path/file.py:N: in function_name" (pytest short format)
    _TRACE_RE = re.compile(
        r'(?:File ["\'](?P<fpath1>[^"\']+)["\'], line \d+, in (?P<fn1>\w+))'
        # fpath2 must be a single whitespace-free token: [^:]+ also matched
        # newlines, so adjacent frames captured the preceding code line into the
        # path ("return a / b\nsrc/foo.py"), splitting one function across keys
        # and corrupting the frequency ranking.
        r'|(?:(?P<fpath2>[^\s:][^:\s]*\.py):(?:\d+): in (?P<fn2>\w+))'
    )
    # Count DISTINCT failing tests per function, not raw frame frequency (audit
    # 2026-06-18): split on pytest's per-failure underscore headers so a function
    # deep in one test's recursion no longer outranks one implicated by many
    # separate failures. This is "failing-test coverage" — a real suspiciousness
    # signal, not Ochiai (we have no passing-test coverage to subtract).
    blocks = re.split(r'\n_{5,}.*\n', output)
    if len(blocks) < 2:
        blocks = [output]
    scores: dict[str, int] = {}  # "file::function" → # of distinct failing tests
    for block in blocks:
        seen: set[str] = set()
        for m in _TRACE_RE.finditer(block):
            fpath = m.group("fpath1") or m.group("fpath2") or ""
            fn = m.group("fn1") or m.group("fn2") or ""
            if fpath and fn and fn not in ("<module>", "__init__"):
                # Skip test functions themselves — focus on implementation code
                if not fn.startswith("test_") and not fpath.startswith("test_"):
                    seen.add(f"{fpath}::{fn}")
        for key in seen:
            scores[key] = scores.get(key, 0) + 1

    # Assertion-aware pass: when the traceback had no impl frame (assert failures),
    # infer suspects from the failing test's source (the A1 blind-spot fix).
    traceback_keys = set(scores)
    try:
        for key, cnt in _assertion_suspects(output, project_dir, blocks).items():
            scores[key] = scores.get(key, 0) + cnt
    except Exception:
        pass

    if not scores:
        return ""

    # Rank by distinct-failing-test count; on ties, direct traceback evidence
    # outranks assertion-inferred suspects.
    top = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0] not in traceback_keys, kv[0]))[:5]

    # Count failures for context
    fail_match = re.search(r'(\d+) failed', output)
    fail_count = fail_match.group(1) if fail_match else "some"

    lines = [
        f"## SBFL Pre-pass (AutoCodeRover §Gap3)",
        f"> Found {fail_count} failing test(s). Functions implicated by failing tests (traceback + assertion analysis):",
        "",
        "**Ranked suspect functions** (higher = more suspect):",
    ]
    for loc, count in top:
        parts = loc.split("::")
        fpath_part = parts[0].split("/")[-1] if parts else loc
        fn_part = parts[1] if len(parts) > 1 else ""
        plural = "s" if count != 1 else ""
        lines.append(f"- `{fn_part}` in `{fpath_part}` (implicated by {count} failing test{plural})")
    lines.append("")
    lines.append("> Investigate these functions first — they're the most likely bug locations.")
    return "\n".join(lines)


# ─── Reproduction Test Generation (Agentless §6B) ────────────────────────────

_REPRO_TEST_PROMPT = (
    "Write a minimal Python pytest test that:\n"
    "1. FAILS with the current buggy code (via assertion error or exception)\n"
    "2. Would PASS after the bug is correctly fixed\n"
    "3. Uses only standard library or existing project imports\n"
    "4. Is 5-20 lines — no boilerplate, no docstrings, just the test function\n\n"
    "Bug/Task:\n{description}\n\n"
    "Codebase structure (for import hints):\n{tldr}\n\n"
    "Respond with ONLY Python code — no markdown fences, no explanation.\n"
    "Start with import/from statements, then one def test_...() function."
)


async def _generate_repro_test(
    task_description: str, tldr: str, project_dir: Path,
    claude_dir: Path | None = None, task_id=None,
) -> str:
    """Generate a failing reproduction test for a bug-fix task (Agentless §6B).

    Asks haiku to write a minimal pytest test that fails with current code.
    Runs pytest --collect-only to verify syntax, then runs the test to confirm
    it actually fails (non-zero exit). Returns a formatted context block.

    When claude_dir is given AND the test is confirmed failing pre-fix, the test
    code is persisted to {claude_dir}/repro-test.py so the validation half
    (_run_repro_filter) can re-run it after the fix to prove the bug is resolved.
    Only confirmed-failing repros are persisted — a test that passes on buggy
    code is a bad test and must never gate.

    Falls back to empty string on any error (non-critical path).
    Only valuable for tasks that describe a concrete, testable bug.
    """
    if not task_description or not tldr:
        return ""

    prompt = _REPRO_TEST_PROMPT.format(
        description=task_description[:500],
        tldr=tldr[:2000],
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", prompt,
            "--model", HAIKU_MODEL,
            "--dangerously-skip-permissions",
            "--no-input-prompt",
            *shlex.split(SETTING_SOURCES_NONE),
            *shlex.split(DISALLOWED_TOOLS_JUDGE),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=str(project_dir),
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=40)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return ""

        test_code = out.decode("utf-8", errors="replace").strip()
        if not test_code or "def test_" not in test_code:
            return ""

        # Strip markdown fences if haiku wrapped anyway
        if test_code.startswith("```"):
            lines = test_code.splitlines()
            test_code = "\n".join(
                l for l in lines if not l.startswith("```")
            ).strip()

        # Sanity-check syntax via py_compile
        import tempfile
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix="clade-repro-", delete=False,
            dir=str(project_dir)
        ) as tmp:
            tmp.write(test_code)
            tmp_path = tmp.name

        try:
            compile_proc = await asyncio.create_subprocess_exec(
                "python", "-m", "py_compile", tmp_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(compile_proc.communicate(), timeout=5)
            except asyncio.TimeoutError:
                compile_proc.kill()
                await compile_proc.communicate()
                return ""
            if compile_proc.returncode != 0:
                return ""  # Bad syntax — discard

            # Optionally run test to verify it actually fails
            # (non-blocking — if it passes or times out, still include as hint)
            run_proc = await asyncio.create_subprocess_exec(
                "python", "-m", "pytest", tmp_path, "-x", "-q", "--tb=no",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=str(project_dir),
            )
            try:
                run_out, _ = await asyncio.wait_for(run_proc.communicate(), timeout=20)
                test_output = run_out.decode("utf-8", errors="replace").strip()
                confirmed_failing = run_proc.returncode != 0
            except asyncio.TimeoutError:
                run_proc.kill()
                await run_proc.communicate()
                confirmed_failing = None
                test_output = "(timed out)"
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        # Persist confirmed-failing repros so the validation half can re-run them
        # post-fix (Agentless §6B). Only confirmed-failing — a repro that passes on
        # buggy code is a bad test and must never gate a commit. Namespaced by
        # task_id: claude_dir is shared across concurrent swarm workers.
        if confirmed_failing and claude_dir is not None and task_id is not None:
            try:
                (claude_dir / f"repro-test-{task_id}.py").write_text(
                    test_code, encoding="utf-8"
                )
            except Exception:
                pass  # persistence is best-effort; context hint still returned

        status_line = (
            "> ✓ Confirmed FAILING with current code — your fix must make this pass."
            if confirmed_failing
            else "> Note: test status unconfirmed — verify manually."
        )
        return (
            f"## Reproduction Test (Agentless §6B)\n"
            f"{status_line}\n"
            f"> Run with: `python -m pytest <test_file> -v`\n\n"
            f"```python\n{test_code}\n```"
        )

    except Exception:
        return ""


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
            f'claude -p "$(cat {shlex.quote(str(score_file))})" --model {HAIKU_MODEL} --dangerously-skip-permissions {SETTING_SOURCES_NONE} {DISALLOWED_TOOLS_JUDGE}',
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
