#!/usr/bin/env python3
"""Measure THIS repository's own code erosion over its own history.

The literature figure everyone quotes — agent-authored code 2.3x more verbose
and 2.0x more eroded than human-maintained repositories, erosion rising in 77%
of trajectories (arXiv:2603.24755 v2, 473 repos, 196 checkpoints) — is somebody
else's corpus. It has been cited in this repository's own research as grounds
for and against a complexity gate, and nobody has ever looked at the git
history sitting on the same disk. This script looks.

WHAT IT CANNOT DO, said plainly because the alternative is a misleading number:
it cannot separate agent-written from human-written code. Every commit here
carries the same author, agency is recorded nowhere in the tree, and a
Claude-Session trailer appears on some commits and not others for reasons that
have to do with when the convention landed, not with who wrote the code. So
this measures a TREND OVER TIME, not a human-vs-agent contrast. A rising trend
is consistent with the erosion literature and does not confirm it; the
confounds (the project simply growing, subsystems arriving, test code landing
in bulk) are real and unremoved.

What it measures, per sampled commit, over the files a given path filter selects:

  complexity      mean cyclomatic complexity per function (ast-walked: each
                  if/for/while/except/with/boolop/comprehension/ternary adds 1)
  max_complexity  the worst single function, which moves before the mean does
  docstring_pct   share of functions and classes carrying a docstring
  fn_len          mean statement count per function body
  comment_ratio   comment lines over code lines

Stdlib only: CI's syntax-check job installs no project dependencies.

  python3 configs/scripts/erosion-trend.py                 # 24 samples over all history
  python3 configs/scripts/erosion-trend.py --samples 40 --path configs/
  python3 configs/scripts/erosion-trend.py --json
  python3 configs/scripts/erosion-trend.py --self-test
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

_BRANCHING = (
    ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
    ast.With, ast.AsyncWith, ast.Assert, ast.IfExp,
    ast.comprehension, ast.BoolOp, ast.Match,
)


def _complexity(node: ast.AST) -> int:
    """Cyclomatic complexity of one function body: 1 + each branching construct.

    A BoolOp counts once per extra operand (``a and b and c`` is two branches),
    which is the standard reading and the one that makes a collapsed
    multi-condition guard score the same as the nested ifs it replaced.
    """
    score = 1
    for child in ast.walk(node):
        if isinstance(child, ast.BoolOp):
            score += len(child.values) - 1
        elif isinstance(child, _BRANCHING):
            score += 1
    return score


def measure_source(text: str) -> dict | None:
    """Return the metrics for one Python source string, or None if it will not parse."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None

    functions = [n for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    documentable = functions + classes

    complexities = [_complexity(f) for f in functions]
    lengths = [len(f.body) for f in functions]
    documented = sum(1 for n in documentable if ast.get_docstring(n))

    lines = text.splitlines()
    comments = sum(1 for line in lines if line.lstrip().startswith("#"))
    code = sum(1 for line in lines if line.strip() and not line.lstrip().startswith("#"))

    return {
        "functions": len(functions),
        "documentable": len(documentable),
        "documented": documented,
        "complexity_sum": sum(complexities),
        "complexity_max": max(complexities, default=0),
        "fn_stmt_sum": sum(lengths),
        "comments": comments,
        "code_lines": code,
    }


def _git(args: list[str]) -> str:
    proc = subprocess.run(["git", *args], cwd=str(REPO),
                          capture_output=True, text=True)
    if proc.returncode:
        return ""
    return proc.stdout


def measure_commit(sha: str, path_filter: str) -> dict | None:
    """Aggregate every tracked .py under path_filter at one commit."""
    listing = _git(["ls-tree", "-r", "--name-only", sha, "--", path_filter])
    files = [f for f in listing.splitlines()
             if f.endswith(".py")
             and not any(part in {".venv", "node_modules", "__pycache__"}
                         for part in Path(f).parts)]
    if not files:
        return None

    agg = {k: 0 for k in ("functions", "documentable", "documented",
                          "complexity_sum", "fn_stmt_sum", "comments", "code_lines")}
    agg["complexity_max"] = 0
    parsed = skipped = 0
    for f in files:
        text = _git(["show", f"{sha}:{f}"])
        if not text:
            continue
        m = measure_source(text)
        if m is None:
            skipped += 1
            continue
        parsed += 1
        for k in agg:
            if k == "complexity_max":
                agg[k] = max(agg[k], m[k])
            else:
                agg[k] += m[k]

    if not agg["functions"]:
        return None
    return {
        "sha": sha[:9],
        "files": parsed,
        "unparseable": skipped,
        "functions": agg["functions"],
        "complexity": round(agg["complexity_sum"] / agg["functions"], 3),
        "complexity_max": agg["complexity_max"],
        "docstring_pct": round(100 * agg["documented"] / max(1, agg["documentable"]), 1),
        "fn_len": round(agg["fn_stmt_sum"] / agg["functions"], 2),
        "comment_ratio": round(agg["comments"] / max(1, agg["code_lines"]), 3),
    }


def sample_commits(n: int) -> list[tuple[str, str]]:
    """Evenly spaced commits, oldest first, each with its author date."""
    out = _git(["log", "--no-merges", "--reverse", "--format=%H %cI"])
    rows = [line.split(None, 1) for line in out.splitlines() if line.strip()]
    if len(rows) <= n:
        return [(r[0], r[1]) for r in rows]
    step = len(rows) / n
    picked = [rows[min(len(rows) - 1, int(i * step))] for i in range(n)]
    if picked[-1][0] != rows[-1][0]:
        picked[-1] = rows[-1]
    return [(r[0], r[1]) for r in picked]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--samples", type=int, default=24)
    ap.add_argument("--path", default=".", help="path filter, e.g. configs/ or orchestrator/")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    series = []
    for sha, date in sample_commits(args.samples):
        row = measure_commit(sha, args.path)
        if row:
            row["date"] = date[:10]
            series.append(row)

    if not series:
        print(f"no commit under '{args.path}' carried a parseable Python file")
        return 0

    if args.json:
        print(json.dumps({"path": args.path, "series": series}, indent=2))
        return 0

    print(f"erosion trend for '{args.path}' — {len(series)} samples, oldest first")
    print(f"{'date':12}{'sha':11}{'files':>6}{'fns':>7}{'cplx':>8}{'max':>6}"
          f"{'doc%':>8}{'fnlen':>8}{'cmnt':>7}")
    for r in series:
        print(f"{r['date']:12}{r['sha']:11}{r['files']:>6}{r['functions']:>7}"
              f"{r['complexity']:>8}{r['complexity_max']:>6}{r['docstring_pct']:>8}"
              f"{r['fn_len']:>8}{r['comment_ratio']:>7}")

    # Compare over a COMPARABLE population, not first-to-last. The early samples
    # of any repository are a handful of files, so a first-to-last delta measures
    # the project being born, not its code eroding: on configs/ that reads +93%
    # complexity, of which essentially all is the tree going from 1 file to 139.
    # The baseline is the earliest sample holding at least half the final file
    # count — stated here because a comparison window chosen and not stated is
    # how a number stops being reproducible.
    threshold = max(1, series[-1]["files"] // 2)
    comparable = [r for r in series if r["files"] >= threshold] or series
    first, last = comparable[0], series[-1]
    print()
    print(f"  baseline {first['date']} ({first['files']} files, the earliest sample with "
          f">= {threshold}); final {last['date']} ({last['files']} files)")
    for key, label in (("complexity", "mean complexity"), ("docstring_pct", "docstring %"),
                       ("fn_len", "mean fn length"), ("comment_ratio", "comment ratio")):
        a, b = first[key], last[key]
        delta = "—" if not a else f"{(b - a) / a * 100:+.1f}%"
        print(f"  {label:18} {a:>8} -> {b:>8}   {delta}")
    if comparable[0] is not series[0]:
        f0 = series[0]
        print(f"  (first-to-last from {f0['date']} would read "
              f"{(last['complexity'] - f0['complexity']) / f0['complexity'] * 100:+.1f}% "
              f"complexity, but {f0['files']} file(s) is not a comparable population.)")
    print("\n  Trend only. This cannot separate agent-written from human-written code —")
    print("  agency is recorded nowhere in this tree — and the confounds (growth, new")
    print("  subsystems, bulk test landings) are real and unremoved. Read it as local")
    print("  evidence about direction, never as a replication of arXiv:2603.24755.")
    return 0


def self_test() -> int:
    """Positive and negative controls on the metric itself.

    A trend script that reports a flat line when the code is eroding, and the
    same flat line when it is not, is the failure this repository keeps finding
    in its own instruments.
    """
    simple = (
        "def f(a):\n"
        '    """Doc."""\n'
        "    return a + 1\n"
    )
    eroded = (
        "def f(a):\n"
        "    if a:\n"
        "        for i in range(a):\n"
        "            if i and a:\n"
        "                try:\n"
        "                    pass\n"
        "                except ValueError:\n"
        "                    pass\n"
        "    return a\n"
    )
    failures = []

    m_simple = measure_source(simple)
    m_eroded = measure_source(eroded)
    if m_simple is None or m_eroded is None:
        return _fail(["a control failed to parse"])

    if not m_eroded["complexity_sum"] > m_simple["complexity_sum"]:
        failures.append(
            f"complexity did not rise on the branch-heavy control: "
            f"{m_simple['complexity_sum']} -> {m_eroded['complexity_sum']}")
    if m_simple["documented"] != 1:
        failures.append(f"docstring not counted on the documented control: {m_simple}")
    if m_eroded["documented"] != 0:
        failures.append(f"docstring counted where there is none: {m_eroded}")
    if measure_source("def broken(:\n") is not None:
        failures.append("unparseable source was measured instead of skipped — "
                        "a syntax error must never silently score as clean")

    # A guard collapsed into one multi-condition line must score the same as the
    # nested ifs it replaced, or the metric rewards hiding branches on one line —
    # which is the perceptual class deciding a checkable measurement. This control
    # isolates the BoolOp arm: without it the branch-heavy control above still
    # rises on its if/for/try and both BoolOp mutations stay green.
    nested = ("def g(a, b, c):\n"
              "    if a:\n"
              "        if b:\n"
              "            if c:\n"
              "                return 1\n"
              "    return 0\n")
    collapsed = ("def g(a, b, c):\n"
                 "    if a and b and c:\n"
                 "        return 1\n"
                 "    return 0\n")
    m_nested, m_collapsed = measure_source(nested), measure_source(collapsed)
    if m_nested is None or m_collapsed is None:
        return _fail(["a BoolOp control failed to parse"])
    if m_nested["complexity_sum"] != m_collapsed["complexity_sum"]:
        failures.append(
            f"collapsing three nested ifs into one `and` chain moved complexity "
            f"{m_nested['complexity_sum']} -> {m_collapsed['complexity_sum']}; each "
            f"extra boolean operand must count as one branch")

    # NEGATIVE control: reformatting without changing logic must not move complexity.
    reflowed = (
        "def f(a):\n"
        '    """Doc."""\n'
        "\n"
        "    return (\n"
        "        a\n"
        "        + 1\n"
        "    )\n"
    )
    m_reflowed = measure_source(reflowed)
    if m_reflowed is None:
        return _fail(["the reformatting control failed to parse"])
    if m_reflowed["complexity_sum"] != m_simple["complexity_sum"]:
        failures.append(
            f"pure reformatting moved complexity "
            f"{m_simple['complexity_sum']} -> {m_reflowed['complexity_sum']} — this "
            f"metric must be blind to the perceptual class")
    return _fail(failures) if failures else _pass()


def _fail(failures: list[str]) -> int:
    for f in failures:
        print(f"SELF-TEST FAILED: {f}")
    return 1


def _pass() -> int:
    print("SELF-TEST PASSED: complexity rises on branching, docstrings are counted "
          "both ways, unparseable source is skipped not scored, and pure "
          "reformatting moves nothing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
