#!/usr/bin/env python3
"""Does an "added test already passes at base" signal actually fire on real history?

The proposal: for the tests a diff ADDS, run them against the diff's base commit.
One that already passes is testing behaviour that existed before the change --
superpowers states the same rule prospectively ("a test that passes immediately
is testing existing behavior and must be rewritten"), and it is the additive
half of the hole `judge_diversity.test_integrity` is blind to.

This measures it retrodictively BEFORE any of it ships, because the last gate
that was built on a plausible argument fired 0 times in 260 commits and had to
be deleted. If this one fires ~0 times too, it dies here at a cost of one script.

Method, per commit C with parent P:
  1. Extract test functions ADDED by C (a `+def test_*` / `+    def test_*` line
     in a file whose path looks like a test).
  2. Materialise P in a scratch worktree.
  3. Copy the test FILES from C over that worktree -- the new test does not exist
     at P, so it has to be carried back; that is the whole point.
  4. Run pytest on exactly those added node ids.
  5. A node that PASSES at base is a hit: it did not need C's source change.

Errors and collection failures are NOT hits. A test that cannot even import at
base is the healthy case -- it is exercising something C introduced.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = os.environ.get("RED_PHASE_REPO", os.getcwd())
# The project's own interpreter, because the tests need the project's deps.
# Resolved to an ABSOLUTE path: pytest runs with cwd inside a throwaway
# worktree, so the relative form CLAUDE.md documented
# (`RED_PHASE_PYTHON=orchestrator/.venv/bin/python`) raised FileNotFoundError
# on the first commit and took the whole audit with it.
_python = os.environ.get("RED_PHASE_PYTHON") or (
    str(Path(REPO) / "orchestrator" / ".venv" / "bin" / "python")
    if (Path(REPO) / "orchestrator" / ".venv" / "bin" / "python").exists()
    else sys.executable
)
# abspath, NOT resolve(): a venv interpreter is usually a symlink to the system
# python, and resolving it follows that link out of the venv — turning
# `orchestrator/.venv/bin/python` into `/usr/bin/python3.12`, which has no
# pytest, and reporting every commit as "no result line". A venv works by the
# path you invoke, not by the binary's identity.
PYTHON = _python if os.path.isabs(_python) else os.path.abspath(os.path.join(REPO, _python))
SUBDIR = os.environ.get("RED_PHASE_SUBDIR", "orchestrator")
TEST_PATH = re.compile(r"(^|/)tests?/.*\.py$|(^|/)test_[^/]+\.py$|_test\.py$")
ADDED_DEF = re.compile(r"^\+\s*def (test_[A-Za-z0-9_]+)")


def git(args, cwd=None, timeout=120):
    p = subprocess.run(["git", *args], cwd=cwd or REPO, capture_output=True,
                       text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def added_tests(sha):
    """{relative test file: [added test function names]} for one commit."""
    _, diff, _ = git(["show", "-U0", "--format=", sha])
    out, cur = {}, None
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:].strip()
            cur = path if TEST_PATH.search(path) else None
        elif cur:
            m = ADDED_DEF.match(line)
            if m:
                out.setdefault(cur, []).append(m.group(1))
    return {k: v for k, v in out.items() if v}


def run_at_base(sha, files_and_tests, workdir):
    """Run the added node ids against sha's parent. Returns (passed, total, note)."""
    rc, parent, _ = git(["rev-parse", f"{sha}~1"])
    if rc != 0:
        return 0, 0, "no parent"
    parent = parent.strip()

    rc, _, err = git(["worktree", "add", "--detach", "-f", str(workdir), parent])
    if rc != 0:
        return 0, 0, f"worktree failed: {err.strip()[:60]}"
    try:
        # Carry the new test files back to the base tree.
        for path in files_and_tests:
            rc, _, _ = git(["checkout", sha, "--", path], cwd=str(workdir))
            if rc != 0:
                return 0, 0, "checkout of test file failed"

        node_ids = []
        for path, names in files_and_tests.items():
            rel = path[len(SUBDIR) + 1:] if SUBDIR and path.startswith(SUBDIR + "/") else path
            for n in names:
                node_ids.append(f"{rel}::{n}")
        if not node_ids:
            return 0, 0, "no node ids"

        orch = Path(workdir) / SUBDIR if SUBDIR else Path(workdir)
        if not orch.is_dir():
            return 0, 0, f"no {SUBDIR} dir at base"
        # Tests outside SUBDIR cannot be addressed from this cwd. Name that
        # reason: it is a scope limit, not a collection failure, and lumping
        # the two hid how much of the tree this audit never looks at.
        if SUBDIR and all(not p.startswith(SUBDIR + "/") for p in files_and_tests):
            return 0, 0, f"out of scope: tests live outside {SUBDIR}/"
        proc = subprocess.run(
            # No --timeout: pytest-timeout is not installed in this venv, and an
            # unrecognized argument makes pytest exit with a usage error that
            # reports 0 passed for EVERY commit. That produced a clean-looking
            # 0% fire rate until the positive control caught it -- the harness
            # was the thing that could not go red.
            [PYTHON, "-m", "pytest", "-p", "no:cacheprovider", "--no-header", "-q",
             *node_ids],
            cwd=str(orch), capture_output=True, text=True, timeout=300,
            env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(workdir),
                 "PY_COLORS": "0", "NO_COLOR": "1"},
        )
        out = proc.stdout + proc.stderr
        # A run that could not execute must never be reported as "nothing fired".
        if "unrecognized arguments" in out or "usage:" in out.lower()[:400]:
            return 0, 0, "pytest usage error -- harness bug, not a finding"
        if not re.search(r"\d+ (passed|failed|error|skipped)", out):
            return 0, 0, f"no result line: {out.strip()[-60:]}"
        m_pass = re.search(r"(\d+) passed", out)
        passed = int(m_pass.group(1)) if m_pass else 0
        return passed, len(node_ids), "ran"
    except subprocess.TimeoutExpired:
        return 0, 0, "timeout"
    finally:
        git(["worktree", "remove", "--force", str(workdir)])


def self_test() -> int:
    """Prove the harness can fire, and can decline to.

    A measurement instrument that cannot go red is indistinguishable from a
    clean codebase — this script has already shipped that failure once (see
    the note beside the pytest invocation above: an unrecognised argument made
    every commit report 0 passed, and the 0% fire rate read as good news).
    So: build a throwaway repo with one commit whose added test genuinely
    needs the change, and one whose added test does not, then assert the
    audit distinguishes them.

    Exits non-zero if either control is wrong.
    """
    global REPO, SUBDIR

    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "repo"
        (repo / SUBDIR / "tests").mkdir(parents=True)

        def run(*args):
            subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)

        run("init", "-q")
        run("config", "user.email", "t@example.com")
        run("config", "user.name", "t")
        (repo / SUBDIR / "conftest.py").write_text("")
        (repo / SUBDIR / "feature.py").write_text("def answer():\n    return 41\n")
        (repo / SUBDIR / "tests" / "test_feature.py").write_text(
            "import sys, pathlib\n"
            "sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))\n"
            "from feature import answer\n\n\n"
            "def test_baseline():\n    assert answer() == 41\n"
        )
        run("add", "-A")
        run("commit", "-q", "-m", "base")

        # NEGATIVE control: the added test needs this commit's source change.
        (repo / SUBDIR / "feature.py").write_text("def answer():\n    return 42\n")
        (repo / SUBDIR / "tests" / "test_feature.py").write_text(
            "import sys, pathlib\n"
            "sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))\n"
            "from feature import answer\n\n\n"
            "def test_baseline():\n    assert answer() == 42\n\n\n"
            "def test_needs_the_change():\n    assert answer() == 42\n"
        )
        run("add", "-A")
        run("commit", "-q", "-m", "real red-phase test")
        _, out, _ = git(["rev-parse", "HEAD"], cwd=str(repo))
        sha_red = out.strip()

        # POSITIVE control: the added test passes without any source change.
        (repo / SUBDIR / "tests" / "test_feature.py").write_text(
            "import sys, pathlib\n"
            "sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))\n"
            "from feature import answer\n\n\n"
            "def test_baseline():\n    assert answer() == 42\n\n\n"
            "def test_needs_the_change():\n    assert answer() == 42\n\n\n"
            "def test_pins_existing_behaviour():\n    assert isinstance(answer(), int)\n"
        )
        run("add", "-A")
        run("commit", "-q", "-m", "test that already passed")
        _, out, _ = git(["rev-parse", "HEAD"], cwd=str(repo))
        sha_green = out.strip()

        prev_repo, REPO = REPO, str(repo)
        try:
            failures = []
            for sha, label, want_fire in (
                (sha_red, "test that needs the change", False),
                (sha_green, "test that pins existing behaviour", True),
            ):
                at = added_tests(sha)
                passed, total, note = run_at_base(sha, at, Path(td) / f"wt-{sha[:7]}")
                fired = total > 0 and passed > 0
                status = "FIRES" if fired else ("clean" if total else f"SKIP ({note})")
                print(f"  {label:38} -> {status}")
                if total == 0:
                    failures.append(f"{label}: harness could not run it ({note})")
                elif fired != want_fire:
                    failures.append(
                        f"{label}: expected {'FIRES' if want_fire else 'clean'}, got {status}"
                    )
        finally:
            REPO = prev_repo

    if failures:
        print("\nSELF-TEST FAILED — this audit cannot be trusted:")
        for f in failures:
            print(f"  {f}")
        return 1
    print("\nSELF-TEST PASSED: the harness fires on a test that passes at base, "
          "and stays clean on one that does not.")
    return 0


def main():
    if "--self-test" in sys.argv:
        return self_test()
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    _, log, _ = git(["log", "-n", "400", "--format=%H", "--no-merges"])
    shas = [s for s in log.split() if s]

    candidates = []
    for sha in shas:
        at = added_tests(sha)
        if at:
            candidates.append((sha, at))
    print(f"commits adding test functions, last {len(shas)}: {len(candidates)}")

    step = max(1, len(candidates) // limit)
    sample = candidates[::step][:limit]
    print(f"sampling {len(sample)} of them\n")

    fired = 0
    checked = 0
    skipped = 0
    skip_reasons: dict[str, int] = {}
    hits = []
    with tempfile.TemporaryDirectory() as td:
        for i, (sha, at) in enumerate(sample, 1):
            wd = Path(td) / f"wt{i}"
            passed, total, note = run_at_base(sha, at, wd)
            if total == 0:
                skipped += 1
                skip_reasons[note.split(":")[0]] = skip_reasons.get(note.split(":")[0], 0) + 1
                print(f"  [{i:>2}/{len(sample)}] {sha[:9]}  SKIP  {note}")
                continue
            checked += 1
            flag = ""
            if passed > 0:
                fired += 1
                hits.append((sha, passed, total, at))
                flag = "  <-- FIRES"
            print(f"  [{i:>2}/{len(sample)}] {sha[:9]}  {passed}/{total} added tests already pass at base{flag}")

    print(f"\n{'='*70}")
    print(f"checked {checked} commits, skipped {skipped}")
    for reason, n in sorted(skip_reasons.items(), key=lambda kv: -kv[1]):
        print(f"    {n:>3}  {reason}")
    print(f"FIRED on {fired} ({fired/max(1,checked)*100:.0f}% of checked)")
    print(f"\nSCOPE: python tests under {SUBDIR}/ only. Shell suites in tests/ "
          f"({len(list((Path(REPO) / 'tests').glob('test-*.sh')))} of them) are not "
          "measured by this audit at all.")
    if hits:
        print("\nCommits whose added tests already passed before the change:")
        for sha, p, t, at in hits[:10]:
            _, subj, _ = git(["log", "-1", "--format=%s", sha])
            print(f"  {sha[:9]}  {p}/{t}  {subj.strip()[:70]}")
            for f, names in list(at.items())[:2]:
                print(f"        {f}: {', '.join(names[:3])}")


if __name__ == "__main__":
    raise SystemExit(main() or 0)
