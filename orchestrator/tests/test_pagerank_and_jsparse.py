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
