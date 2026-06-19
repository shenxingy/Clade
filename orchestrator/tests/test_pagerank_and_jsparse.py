"""Audit 2026-06-18 follow-ups in worker_tldr.py:
- `_pagerank` / `_pagerank_centrality` — deterministic repo-map centrality (Aider
  PageRank lesson) so central-but-keyword-poor files survive localization.
- `_keyword_filter_tldr(centrality=...)` — central files kept despite no keyword.
- `_parse_js_ts_regex` — widened to TS interface/type/enum, arrow fns, exports,
  class methods (was Python-AST-real but JS-regex-thin).

Loads the REAL worker_tldr via importlib (conftest mocks it) — same pattern as
test_sbfl_prepass.py.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ORCH = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("_real_worker_tldr_pr", _ORCH / "worker_tldr.py")
wt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wt)  # type: ignore[union-attr]


# ─── _pagerank ────────────────────────────────────────────────────────────────

class TestPageRank:
    def test_widely_imported_file_ranks_highest(self):
        # base.py is imported by a, b, c; nobody imports leaf.py.
        graph = {
            "base.py": set(),
            "a.py": {"base.py"},
            "b.py": {"base.py"},
            "c.py": {"base.py"},
            "leaf.py": {"a.py"},
        }
        scores = wt._pagerank(graph)
        assert scores["base.py"] == max(scores.values())  # normalized to 1.0
        assert scores["base.py"] > scores["leaf.py"]

    def test_deterministic(self):
        graph = {"x.py": {"y.py"}, "y.py": set(), "z.py": {"y.py"}}
        assert wt._pagerank(graph) == wt._pagerank(graph)

    def test_empty_graph(self):
        assert wt._pagerank({}) == {}


# ─── _pagerank_centrality (real import-graph over a temp repo) ────────────────

class TestPageRankCentrality:
    def test_central_module_scores_high(self, tmp_path):
        (tmp_path / "base.py").write_text("class Base: pass\n")
        (tmp_path / "a.py").write_text("from base import Base\n")
        (tmp_path / "b.py").write_text("import base\n")
        (tmp_path / "c.py").write_text("from base import Base\n")
        scores = wt._pagerank_centrality(str(tmp_path))
        assert scores["base.py"] == max(scores.values())
        assert scores["base.py"] > scores.get("a.py", 0.0)

    def test_missing_dir(self):
        assert wt._pagerank_centrality("/no/such/dir") == {}

    def test_caps_huge_repos(self, tmp_path):
        for i in range(5):
            (tmp_path / f"m{i}.py").write_text("x = 1\n")
        assert wt._pagerank_centrality(str(tmp_path), max_files=3) == {}


# ─── _keyword_filter_tldr with centrality ────────────────────────────────────

class TestKeywordFilterCentrality:
    def test_central_file_kept_without_keyword(self):
        # Task keywords match foo/bar/baz; base mentions none, but is central.
        tldr = (
            "## foo.py\n  def handle_foo()\n"
            "## bar.py\n  def handle_bar()\n"
            "## baz.py\n  def handle_baz()\n"
            "## base.py\n  class AbstractThing()\n"
        )
        task = "fix handle_foo and handle_bar and handle_baz"
        without = wt._keyword_filter_tldr(task, tldr)
        assert "base.py" not in without  # keyword-only filter drops the central file
        with_cen = wt._keyword_filter_tldr(task, tldr, centrality={"base.py": 1.0})
        assert "base.py" in with_cen   # centrality safety-net keeps it


# ─── _parse_js_ts_regex coverage ─────────────────────────────────────────────

class TestJsTsParse:
    def test_catches_modern_constructs(self):
        src = (
            "export interface User { id: number }\n"
            "export type Id = string\n"
            "enum Color { Red, Blue }\n"
            "export const fetchUser = async (id) => {\n"
            "const double = x => x * 2\n"
            "export default function App() {\n"
            "class Service {\n"
            "  getUser(id: number): User {\n"
        )
        out = "\n".join(wt._parse_js_ts_regex(src))
        for needle in ["User", "Id", "Color", "fetchUser", "double", "App", "Service", "getUser"]:
            assert needle in out, f"missed {needle}"

    def test_guards_control_flow(self):
        # `if (...) {` and `for (...) {` must NOT be captured as methods.
        src = "  if (ready) {\n  for (const x of xs) {\n  return foo()\n"
        out = wt._parse_js_ts_regex(src)
        assert not any(line.startswith("if") or line.startswith("for") or line.startswith("return")
                       for line in out)


# ─── tree-sitter multi-language (B; audit 2026-06-18) ────────────────────────

import pytest  # noqa: E402

_HAS_GO = wt._get_ts_parser("tree_sitter_go") is not None


class TestTreeSitterParse:
    def test_unknown_ext_returns_none(self):
        # .py is handled by the stdlib ast path, not tree-sitter → None here.
        assert wt._parse_with_treesitter("def f(): pass", ".py") is None

    def test_graceful_when_grammar_absent(self):
        # A never-installed grammar must degrade to None, not raise.
        assert wt._parse_with_treesitter("x", ".nonexistent-lang") is None

    @pytest.mark.skipif(not _HAS_GO, reason="tree-sitter-go not installed")
    def test_go_definitions(self):
        src = ("package main\nfunc Handle(w int) error { return nil }\n"
               "type Server struct{ Port int }\nfunc (s Server) Start() {}\n")
        sigs = wt._parse_with_treesitter(src, ".go")
        joined = "\n".join(sigs)
        assert "func Handle(w int) error" in joined
        assert "type Server struct" in joined
        assert "func (s Server) Start()" in joined
        # bare keyword nodes filtered out
        assert "struct" not in sigs and "func" not in sigs

    @pytest.mark.skipif(not _HAS_GO, reason="tree-sitter not installed")
    def test_generate_tldr_includes_go(self, tmp_path):
        (tmp_path / "svc.go").write_text("package main\nfunc Ping() string { return \"ok\" }\n")
        tldr = wt._generate_code_tldr(str(tmp_path))
        assert "## svc.go" in tldr
        assert "func Ping() string" in tldr


# ─── Multi-language PageRank import graphs (audit 2026-06-19) ─────────────────

class TestMultiLangPageRank:
    def _top(self, scores):
        return max(scores, key=scores.get) if scores else None

    def test_go_module_import_graph(self, tmp_path):
        (tmp_path / "go.mod").write_text("module example.com/app\n")
        (tmp_path / "base").mkdir()
        (tmp_path / "base" / "base.go").write_text("package base\nfunc Core() {}\n")
        (tmp_path / "a.go").write_text('package main\nimport "example.com/app/base"\nfunc A(){}\n')
        (tmp_path / "b.go").write_text('package main\nimport ( "example.com/app/base" )\nfunc B(){}\n')
        scores = wt._pagerank_centrality(str(tmp_path))
        assert self._top(scores) == "base/base.go"

    def test_ts_relative_import_graph(self, tmp_path):
        (tmp_path / "util.ts").write_text("export const u = 1\n")
        (tmp_path / "x.ts").write_text("import { u } from './util'\n")
        (tmp_path / "y.ts").write_text("import { u } from './util.ts'\n")
        scores = wt._pagerank_centrality(str(tmp_path))
        assert self._top(scores) == "util.ts"

    def test_ts_bare_specifier_is_not_an_edge(self, tmp_path):
        # bare 'react' is a dep, not a repo file — must not create an edge
        (tmp_path / "a.ts").write_text("import React from 'react'\nimport {u} from './u'\n")
        (tmp_path / "u.ts").write_text("export const u = 1\n")
        scores = wt._pagerank_centrality(str(tmp_path))
        assert self._top(scores) == "u.ts"

    def test_rust_use_import_graph(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "config.rs").write_text("pub struct Cfg;\n")
        (tmp_path / "src" / "a.rs").write_text("use crate::config::Cfg;\n")
        (tmp_path / "src" / "b.rs").write_text("use crate::config::Cfg;\n")
        scores = wt._pagerank_centrality(str(tmp_path))
        assert self._top(scores) == "src/config.rs"


# ─── Import-resolver review fixes (audit 2026-06-19 adversarial review) ───────

class TestImportResolverFixes:
    def _top(self, scores):
        return max(scores, key=scores.get) if scores else None

    def test_rust_grouped_imports(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.rs").write_text("pub struct A;\n")
        (tmp_path / "src" / "b.rs").write_text("pub struct B;\n")
        (tmp_path / "src" / "user.rs").write_text("use crate::{a::A, b::B};\n")
        scores = wt._pagerank_centrality(str(tmp_path))
        # both a.rs and b.rs receive an edge from user.rs
        assert scores.get("src/a.rs", 0) > 0 and scores.get("src/b.rs", 0) > 0

    def test_rust_external_crate_not_resolved(self, tmp_path):
        # bare `use serde::X` is an external crate even if a local serde.rs exists
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "serde.rs").write_text("pub struct Local;\n")
        (tmp_path / "src" / "user.rs").write_text("use serde::Deserialize;\n")
        # no crate:: prefix → no edge to the local serde.rs
        targets = wt._file_import_targets("use serde::Deserialize;\n", ".rs", "src/user.rs",
                                          {"src/serde.rs", "src/user.rs"}, {}, None)
        assert targets == set()

    def test_go_commented_import_no_phantom_edge(self, tmp_path):
        (tmp_path / "go.mod").write_text("module ex.com/app\n")
        (tmp_path / "real").mkdir()
        (tmp_path / "real" / "r.go").write_text("package real\nfunc R(){}\n")
        (tmp_path / "main.go").write_text(
            'package main\nimport (\n\t"ex.com/app/real"\n\t// "ex.com/app/ghost"\n)\n')
        specs = wt._imports_go((tmp_path / "main.go").read_text())
        assert "ex.com/app/real" in specs and "ex.com/app/ghost" not in specs

    def test_js_commented_import_no_phantom_edge(self):
        text = "import {a} from './real'\n// import {b} from './ghost'\n/* import './blk' */\n"
        targets = wt._file_import_targets(text, ".ts", "x.ts", {"real.ts", "x.ts"}, {}, None)
        assert "real.ts" in targets

    def test_java_wildcard_import(self, tmp_path):
        (tmp_path / "com" / "x").mkdir(parents=True)
        (tmp_path / "com" / "x" / "A.java").write_text("package com.x; class A {}\n")
        (tmp_path / "com" / "x" / "B.java").write_text("package com.x; class B {}\n")
        targets = wt._file_import_targets("import com.x.*;\n", ".java", "Main.java",
                                          {"com/x/A.java", "com/x/B.java", "Main.java"}, {}, None)
        assert targets == {"com/x/A.java", "com/x/B.java"}

    def test_cache_invalidates_on_deletion(self, tmp_path):
        (tmp_path / "base.py").write_text("class B: pass\n")
        (tmp_path / "a.py").write_text("from base import B\n")
        (tmp_path / "b.py").write_text("from base import B\n")
        s1 = wt._pagerank_centrality(str(tmp_path))
        assert "b.py" in s1
        (tmp_path / "b.py").unlink()  # delete a file (max_mtime may not change)
        s2 = wt._pagerank_centrality(str(tmp_path))
        assert "b.py" not in s2  # stale cache would still contain it

    def test_ts_path_alias_resolves(self, tmp_path):
        import json as _json
        (tmp_path / "tsconfig.json").write_text(
            _json.dumps({"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]}}}))
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "util.ts").write_text("export const u = 1\n")
        (tmp_path / "src" / "x.ts").write_text("import { u } from '@/util'\n")
        (tmp_path / "src" / "y.ts").write_text("import { u } from '@/util'\n")
        scores = wt._pagerank_centrality(str(tmp_path))
        assert self._top(scores) == "src/util.ts"
