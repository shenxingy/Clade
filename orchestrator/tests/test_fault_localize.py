"""Multi-language fault localization (fault_localize.py): runner detection + the
go/js failure parsers + the language-agnostic assertion fallback. Stdlib-only leaf,
so it imports directly (no conftest mock needed)."""

from __future__ import annotations

import asyncio
import json
import shutil

import pytest

import fault_localize as fl


# ─── detect_test_runner ──────────────────────────────────────────────────────

class TestDetectRunner:
    def _oj(self, tmp_path, cmd):
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "orchestrator.json").write_text(json.dumps({"test_cmd": cmd}))

    def test_orchestrator_json_classifies(self, tmp_path):
        cases = {
            "cd backend && pytest tests/": ("python", "pytest"),
            "go test ./...": ("go", "gotest"),
            "npx vitest run": ("js", "vitest"),
            "npx jest": ("js", "jest"),
            "node --experimental-strip-types --test 'tests/**/*.test.ts'": ("js", "nodetest"),
            "cargo test": ("rust", "cargo"),
        }
        for cmd, (lang, kind) in cases.items():
            (tmp_path / ".claude").mkdir(exist_ok=True)
            (tmp_path / ".claude" / "orchestrator.json").write_text(json.dumps({"test_cmd": cmd}))
            r = fl.detect_test_runner(tmp_path)
            assert r and r["lang"] == lang and r["kind"] == kind, (cmd, r)

    def test_go_mod_sniff(self, tmp_path):
        (tmp_path / "go.mod").write_text("module x\n")
        r = fl.detect_test_runner(tmp_path)
        assert r["kind"] == "gotest" and "go test" in r["cmd"]

    def test_package_json_vitest_sniff(self, tmp_path):
        (tmp_path / "package.json").write_text(json.dumps({"devDependencies": {"vitest": "^1"}}))
        r = fl.detect_test_runner(tmp_path)
        assert r["kind"] == "vitest"

    def test_no_signal_returns_none(self, tmp_path):
        assert fl.detect_test_runner(tmp_path) is None


# ─── stack-frame suspects ────────────────────────────────────────────────────

_GO_PANIC = """--- FAIL: TestDivide (0.00s)
panic: runtime error: integer divide by zero

goroutine 18 [running]:
github.com/me/calc.divide(...)
\t/home/u/calc/math.go:12 +0x11
github.com/me/calc.TestDivide(0xc0000d2340)
\t/home/u/calc/math_test.go:8 +0x18
testing.tRunner(0xc0000d2340, 0x5b2a30)
\t/usr/local/go/src/testing/testing.go:1689 +0xfb
FAIL\tgithub.com/me/calc\t0.002s
"""


class TestStackFrames:
    def test_go_panic_excludes_test_and_stdlib(self):
        s = fl._stack_frame_suspects(_GO_PANIC, "go")
        assert any(k.endswith("::divide") for k in s), s
        assert not any("_test.go" in k for k in s)
        assert not any("testing" in k or "tRunner" in k for k in s)

    def test_js_stack_excludes_node_internals_and_tests(self):
        out = (
            "at Object.parseConfig (/app/src/config.ts:14:9)\n"
            "at /app/tests/config.test.ts:7:3\n"
            "at processTicksAndRejections (node:internal/process/task_queues:95:5)\n"
            "at runTest (/app/node_modules/vitest/dist/runner.js:1:1)\n"
        )
        s = fl._stack_frame_suspects(out, "js")
        assert any(k.endswith("::parseConfig") for k in s), s
        assert not any("test" in k or "node_modules" in k or "node:" in k for k in s)


# ─── assertion fallback ──────────────────────────────────────────────────────

class TestAssertionFallback:
    def test_js_test_source_names_impl(self, tmp_path):
        (tmp_path / "lib").mkdir()
        (tmp_path / "tests").mkdir()
        (tmp_path / "lib" / "platform.ts").write_text(
            "export function classify(x){ return x>0?'neg':'pos'; }\n")
        (tmp_path / "tests" / "p.test.ts").write_text(
            "import {classify} from '../lib/platform.ts';\n"
            "test('x', () => { assert.strictEqual(classify(5), 'pos'); });\n")
        # node:test-style output: only the test frame in the location/stack
        out = "not ok 1 - x\n  location: 'tests/p.test.ts:2:1'\n  stack: |-\n    at file://tests/p.test.ts:2:30\n"
        idx = fl._build_symbol_index(tmp_path)
        s = fl._test_source_suspects(out, "js", tmp_path, idx)
        assert "lib/platform.ts::classify" in s, s


# ─── format + end-to-end (live node:test if available) ───────────────────────

def test_format_suspect_block_empty():
    assert fl.format_suspect_block({}, "0") == ""


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_run_runner_sbfl_live_nodetest(tmp_path):
    (tmp_path / "lib").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "lib" / "platform.ts").write_text(
        "export function classify(x){ return x>0?'neg':'pos'; }\n")
    (tmp_path / "tests" / "p.test.ts").write_text(
        "import { test } from 'node:test';\nimport assert from 'node:assert';\n"
        "import { classify } from '../lib/platform.ts';\n"
        "test('positive', () => { assert.strictEqual(classify(5), 'pos'); });\n")
    runner = {"lang": "js", "kind": "nodetest",
              "cmd": "node --experimental-strip-types --no-warnings --test tests/p.test.ts"}
    block = asyncio.run(fl.run_runner_sbfl(tmp_path, runner, timeout=60))
    assert "classify" in block and "platform.ts" in block


# ─── Parser review fixes (audit 2026-06-19 adversarial review) ───────────────

class TestParserReviewFixes:
    def test_go_generic_free_function(self):
        out = "github.com/x/col.Map[...]({0x1})\n\t/home/u/col/collection.go:55 +0x88\n"
        s = fl._stack_frame_suspects(out, "go")
        assert any(k.endswith("collection.go::Map") for k in s), s

    def test_go_generic_method(self):
        out = "github.com/x/col.(*Tree[...]).Insert(0x1)\n\t/home/u/col/tree.go:7 +0x1\n"
        s = fl._stack_frame_suspects(out, "go")
        assert any(k.endswith("tree.go::Insert") for k in s), s

    def test_go_redos_long_line_is_fast(self):
        import time
        t0 = time.time()
        fl._stack_frame_suspects("a" + ".a" * 40000 + "\n", "go")
        assert time.time() - t0 < 1.0  # was ~56s before the fix

    def test_js_new_and_anonymous_frames(self):
        out = ("at new OrderService (/app/src/order.ts:9:5)\n"
               "at <anonymous> (/app/src/x.ts:3:1)\n")
        s = fl._stack_frame_suspects(out, "js")
        assert any(k.endswith("order.ts::OrderService") for k in s)  # 'new ' stripped
        assert not any("anonymous" in k for k in s)                  # junk dropped

    def test_test_name_predicate_word_boundary(self):
        for non in ("attestation.py", "latest.py", "contest.py", "fastest.go"):
            assert not fl._is_test_file_name(non), non
        for yes in ("test_x.py", "x_test.go", "x.test.ts", "foo.spec.tsx", "conftest.py"):
            assert fl._is_test_file_name(yes), yes
