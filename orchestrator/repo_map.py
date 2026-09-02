"""repo_map.py — deterministic repository-structure analysis (leaf module).

Extracted from worker_tldr.py at 1459 of the 1500 test_conventions.py
enforces. Everything here is pure and synchronous: no LLM call, no
subprocess, no DB — that invariant is what the split buys, and
test_repo_map.py asserts it. worker_tldr.py keeps the async half that
spends money and imports the three helpers it needs from here.

Deliberately NOT named worker_* : it is code analysis, a peer of
fault_localize.py, and session.py / routes/workers.py consume it without
ever touching a Worker.
"""

from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path
from typing import Any

# fault_localize is a stdlib-only leaf (lower in the DAG); the shared scan
# constants live there so the SBFL path and this structural pass agree on
# which directories are skipped.
from fault_localize import _SKIP_DIRS

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
            name = re.split(r'[\s(:]', rest, maxsplit=1)[0]
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


def _read_ts_aliases(root: Path) -> dict[str, list[str]]:
    """Parse tsconfig/jsconfig `compilerOptions.paths` + `baseUrl` into
    {alias_prefix: [target_dir_prefix]} so `@/x` imports resolve to real files."""
    aliases: dict[str, list[str]] = {}
    for fn in ("tsconfig.json", "jsconfig.json"):
        f = root / fn
        if not f.exists():
            continue
        try:
            raw = _strip_c_comments(f.read_text(errors="replace"))
            raw = re.sub(r',(\s*[}\]])', r'\1', raw)  # tolerate trailing commas (jsonc)
            cfg = json.loads(raw)
        except Exception:
            continue
        co = cfg.get("compilerOptions", {}) or {}
        base = (co.get("baseUrl") or ".").strip("/")
        for k, v in (co.get("paths") or {}).items():
            if not isinstance(v, list) or not v:
                continue
            key = k.rstrip("*").rstrip("/")
            vals = []
            for t in v:
                t = str(t).rstrip("*").rstrip("/")
                if base not in (".", ""):
                    t = os.path.normpath(os.path.join(base, t)).replace("\\", "/")
                vals.append(t.lstrip("./"))
            if key:
                aliases[key] = vals
    return aliases


def _imports_go(text: str) -> set[str]:
    text = _strip_c_comments(text)
    out: set[str] = set()
    for m in re.finditer(r'^\s*import\s+(?:[\w.]+\s+)?"([^"]+)"', text, re.M):
        out.add(m.group(1))
    for blk in re.finditer(r'import\s*\((.*?)\)', text, re.S):
        out.update(re.findall(r'"([^"]+)"', blk.group(1)))
    return out


def _ts_file_candidates(base: str, relset: set[str], targets: set[str]) -> None:
    for cand in (base, *(f"{base}{e}" for e in (".ts", ".tsx", ".js", ".jsx")),
                 *(f"{base}/index{e}" for e in (".ts", ".tsx", ".js", ".jsx"))):
        if cand in relset:
            targets.add(cand)


def _resolve_import(spec: str, ext: str, src_rel: str, relset: set[str],
                    go_module: str | None, ts_aliases: dict[str, list[str]] | None = None) -> set[str]:
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
        if spec.startswith("."):  # relative
            base = os.path.normpath(os.path.join(os.path.dirname(src_rel), spec)).replace("\\", "/")
            _ts_file_candidates(base, relset, targets)
        elif ts_aliases:  # tsconfig path alias, e.g. @/x → src/x
            for prefix, tdirs in ts_aliases.items():
                if spec == prefix or spec.startswith(prefix + "/"):
                    rest = spec[len(prefix):].lstrip("/")
                    for td in tdirs:
                        _ts_file_candidates(f"{td}/{rest}".strip("/") if rest else td, relset, targets)
                    break
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
                         go_module: str | None,
                         ts_aliases: dict[str, list[str]] | None = None) -> set[str]:
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
        targets |= _resolve_import(spec, ext, src_rel, relset, go_module, ts_aliases)
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
    ts_aliases = _read_ts_aliases(root)

    graph: dict[str, set[str]] = {r: set() for r in rel}
    for r, p in rel.items():
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        for tgt in _file_import_targets(text, p.suffix, r, relset, py_stem_to_rel, go_module, ts_aliases):
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
