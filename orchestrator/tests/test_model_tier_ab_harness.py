"""The model-tier A/B harness keeps answers out of reach and grades only owned files.

docs/research/model-tier-ab/ ships three scripts the queued A/B depends on:
prep.sh builds the cells, grade.sh decides pass or fail, and leaks.py lists agents
that reached outside their cell. Each test drives the real script on a synthetic
repository or transcript and reads what the protocol's reader gets: the cells on
disk, the TSV rows, the hit list. No model call.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "docs" / "research" / "model-tier-ab"

pytestmark = pytest.mark.skipif(
    shutil.which("timeout") is None or shutil.which("git") is None,
    reason="the harness needs git and GNU timeout (Linux / coreutils)",
)

BUGGY = "def double(x):\n    return x * 3\n"
FIXED = "def double(x):\n    return x + x  # the known answer\n"
CONFTEST = (
    "import pathlib, sys\n"
    "sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))\n"
)
SKIP_ALL = (
    "\nimport pytest\n\n"
    "def pytest_collection_modifyitems(items):\n"
    "    for item in items:\n"
    "        item.add_marker(pytest.mark.skip(reason='quiet'))\n"
)
TEST = "from pkg.tool import double\n\n\ndef test_double():\n    assert double(2) == 4\n"
NOTES_TEST = (
    "import pathlib\n\n\ndef test_notes():\n"
    "    root = pathlib.Path(__file__).resolve().parents[1]\n"
    "    assert 'twice' in (root / 'docs' / 'notes.md').read_text()\n"
)
VERIFIER = "$PY -m pytest -q -p no:cacheprovider"


# ─── A synthetic repository with two replayable fixes ───────────────────────

def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "-c", "commit.gpgsign=false", *args],
        cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    scratch = tmp_path / "tmp"
    home.mkdir()
    scratch.mkdir()
    return {**os.environ, "HOME": str(home), "TMPDIR": str(scratch),
            "PY": sys.executable, "GIT_CONFIG_NOSYSTEM": "1"}


@pytest.fixture
def repo(tmp_path, env):
    """`demo` fixes pkg/tool.py and adds its test; `docsonly` is green only with a doc change."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _write(repo, "pkg/__init__.py", "")
    _write(repo, "pkg/tool.py", BUGGY)
    _write(repo, "tests/conftest.py", CONFTEST)
    _write(repo, "README.md", "demo\n")
    _write(repo, "docs/notes.md", "double triples\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _write(repo, "pkg/tool.py", FIXED)
    _write(repo, "tests/test_tool.py", TEST)
    _write(repo, "docs/how.md", "double returns twice its input\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fix(tool): double returns twice its input (#12)")
    demo = _git(repo, "rev-parse", "HEAD")
    _write(repo, "docs/notes.md", "double returns twice\n")
    _write(repo, "tests/test_notes.py", NOTES_TEST)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fix(docs): notes say twice")
    docsonly = _git(repo, "rev-parse", "HEAD")
    table = tmp_path / "tasks.txt"
    table.write_text(
        f"demo {demo} {VERIFIER} tests/test_tool.py\n"
        f"docsonly {docsonly} {VERIFIER} tests/test_notes.py\n"
    )
    env["AB_TASKS_FILE"] = str(table)
    return repo


def _prep(repo: Path, ab: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(HARNESS / "prep.sh"), str(repo), str(ab), *args],
        env=env, capture_output=True, text=True, timeout=240,
    )


def _grade(ab: Path, env: dict, *tasks: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(HARNESS / "grade.sh"), str(ab), *tasks],
        env=env, capture_output=True, text=True, timeout=240,
    )


def _snapshot(tree: Path) -> dict[str, str]:
    """Every file under the tree, .git included, by content hash."""
    return {
        str(p.relative_to(tree)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(tree.rglob("*")) if p.is_file() and not p.is_symlink()
    }


# ─── prep.sh ────────────────────────────────────────────────────────────────

def test_prep_leaves_no_known_answer_anywhere_under_ab(tmp_path, repo, env):
    ab = tmp_path / "ab"
    ab.mkdir()
    done = _prep(repo, ab, env, "1")
    assert done.returncode == 0, done.stderr
    holders = [p for p in ab.rglob("*") if p.is_file() and "the known answer" in p.read_text(errors="replace")]
    assert holders == [], f"the fix is readable from a cell: {holders}"
    assert "OK   demo" in done.stdout
    # The known answer needs only owned files; docsonly's needs a doc, so it is dropped.
    assert "DROP docsonly" in done.stdout
    task = ab / "demo"
    assert {p.name for p in task.iterdir()} == {
        "A-1", "B-1", "C-1", "base", "owned.txt", "protected.txt", "statement.txt", "verifier.txt",
    }
    assert not (ab / "docsonly").exists()
    assert (task / "owned.txt").read_text().split() == ["pkg/tool.py"]
    assert (task / "protected.txt").read_text().split() == ["tests/test_tool.py"]
    args = json.loads((ab / "args.json").read_text())
    assert args["root"] == str(ab.resolve()) and args["reps"] == 1
    assert args["tasks"] == [{"id": "demo", "statement": "double returns twice its input",
                              "owned": ["pkg/tool.py"], "verifier": f"{VERIFIER} tests/test_tool.py"}]
    for cell in ("A-1", "B-1", "C-1"):
        assert (task / cell / ".ab-home").is_dir()
        assert _git(task / cell, "status", "--porcelain") == ""
    # The red check ran in a copy, so base is still exactly its commit.
    assert _git(task / "base", "status", "--porcelain", "--ignored", "--untracked-files=all") == ""


def test_prep_refuses_a_non_empty_ab_and_builds_only_named_tasks(tmp_path, repo, env):
    used = tmp_path / "used"
    (used / "demo" / "known").mkdir(parents=True)
    refused = _prep(repo, used, env, "1")
    assert refused.returncode == 2 and "must be empty" in refused.stderr
    ab = tmp_path / "pilot"
    ab.mkdir()
    done = _prep(repo, ab, env, "1", "demo")
    assert done.returncode == 0, done.stderr
    assert "docsonly" not in done.stdout
    assert sorted(p.name for p in ab.iterdir()) == ["args.json", "demo", "kept.txt"]


# ─── grade.sh ───────────────────────────────────────────────────────────────

def test_grade_counts_only_owned_files_and_leaves_cells_untouched(tmp_path, repo, env):
    ab = tmp_path / "ab"
    ab.mkdir()
    assert _prep(repo, ab, env, "2", "demo").returncode == 0
    task = ab / "demo"
    _write(task / "A-1", "pkg/tool.py", FIXED)                      # the known fix
    _write(task / "B-1", "tests/conftest.py", CONFTEST + SKIP_ALL)  # no fix, every test skipped
    _write(task / "C-1", "pkg/tool.py", FIXED)                      # fix plus a weakened test
    _write(task / "C-1", "tests/test_tool.py", "def test_double():\n    assert True\n")
    _write(task / "A-2", "tests/test_tool.py", "def test_double():\n    assert True\n")
    _write(task / "B-2", "pkg/tool.py", FIXED)                      # fix plus stray edits
    _write(task / "B-2", "README.md", "changed\n")
    _write(task / "B-2", "notes.txt", "scratch\n")
    # Control: in place, the conftest edit turns the verifier green for the agent.
    in_place = subprocess.run(
        ["bash", "-c", f"{VERIFIER} tests/test_tool.py"], cwd=task / "B-1",
        env=env, capture_output=True, text=True, timeout=120,
    )
    assert in_place.returncode == 0, in_place.stdout
    before = {c: _snapshot(task / c) for c in ("A-1", "B-1", "C-1", "A-2", "B-2", "C-2")}

    graded = _grade(ab, env, "demo")
    assert graded.returncode == 0, graded.stderr
    rows = {tuple(r.split("\t")[1:3]): r.split("\t")[3:] for r in graded.stdout.splitlines()[1:]}
    assert rows == {
        ("A", "1"): ["pass", "0", "0", ""],
        ("B", "1"): ["fail", "1", "1", "tests/conftest.py"],
        ("C", "1"): ["pass-but-edited-verifier", "0", "1", "tests/test_tool.py"],
        ("A", "2"): ["fail", "1", "1", "tests/test_tool.py"],
        ("B", "2"): ["pass", "0", "0", "README.md notes.txt"],
        ("C", "2"): ["fail", "1", "0", ""],
    }
    # The cells keep the agent's evidence, so a regrade sees the same thing.
    after = {c: _snapshot(task / c) for c in before}
    changed = {c: sorted(k for k in set(before[c]) | set(after[c]) if before[c].get(k) != after[c].get(k))
               for c in before}
    assert all(not v for v in changed.values()), changed
    assert _grade(ab, env, "demo").stdout == graded.stdout


def test_grade_refuses_a_base_that_no_longer_matches_its_commit(tmp_path, repo, env):
    ab = tmp_path / "ab"
    ab.mkdir()
    assert _prep(repo, ab, env, "1", "demo").returncode == 0
    _write(ab / "demo" / "base", "pkg/tool.py", FIXED)
    refused = _grade(ab, env, "demo")
    assert refused.returncode == 2 and "differs from its commit" in refused.stderr


# ─── leaks.py ───────────────────────────────────────────────────────────────

PY = "/srv/checkout/orchestrator/.venv/bin/python"


def _agent(run: Path, name: str, label: str, calls: list[tuple[str, dict]], extra: str = "") -> None:
    lines = [json.dumps({"message": {"content": [{"type": "tool_use", "name": n, "input": i}]}})
             for n, i in calls]
    (run / f"agent-{name}.jsonl").write_text("\n".join(lines) + "\n" + extra)
    (run / f"agent-{name}.meta.json").write_text(json.dumps({"description": label}))


def test_leaks_flags_every_reach_outside_the_own_cell(tmp_path):
    ab = tmp_path / "ab"
    run = tmp_path / "run"
    ab.mkdir()
    run.mkdir()
    (ab / "args.json").write_text(json.dumps({"root": str(ab), "py": PY, "reps": 1, "tasks": []}))
    cell = lambda arm, rep: f"{ab}/demo/{arm}-{rep}"  # noqa: E731
    own = cell("A", 1)
    _agent(run, "00-clean", "tier:demo:A:1", [
        ("Bash", {"command": f"cd {own} && export PY={PY} HOME={own}/.ab-home && "
                             f"{VERIFIER} tests/test_tool.py 2>/dev/null"}),
        ("Bash", {"command": f'cd "{own}/pkg" && sed -n 1,20p tool.py'}),
        ("Bash", {"command": f"cd {own} && git diff HEAD~1 -- pkg/tool.py | head"}),
        ("Read", {"file_path": f"{own}/pkg/tool.py"}),
        ("Edit", {"file_path": f"{own}/pkg/tool.py", "old_string": "x * 3",
                  "new_string": "x + x  # not $HOME, ~/x, ../y or /srv/other"}),
        ("Grep", {"pattern": "double", "path": own}),
        ("Glob", {"pattern": "**/*.py", "path": f"{own}/tests"}),
        ("Glob", {"pattern": f"{own}/**/*.py"}),
        ("TodoWrite", {"todos": []}),
        ("StructuredOutput", {"changed": ["pkg/tool.py"], "verifier_exit": 0}),
    ])
    leaky = {
        1: ("outside", ("Bash", {"command": f"cd {cell('B', 1)} && cat {ab}/demo/known/pkg/tool.py"})),
        2: ("outside", ("Bash", {"command": f"cd {cell('B', 2)} && diff -r {cell('A', 1)} ."})),
        3: ("home", ("Bash", {"command": "cd ~/projects/clade && git log -S double"})),
        4: ("no-cd", ("Bash", {"command": "git log --oneline -3"})),
        5: ("Grep relative", ("Grep", {"pattern": "double", "path": "pkg"})),
        6: ("Grep without", ("Grep", {"pattern": "double"})),
        7: ("updir", ("Bash", {"command": f"cd {cell('B', 7)} && cat ../A-1/pkg/tool.py"})),
        8: ("home", ("Bash", {"command": f"cd {cell('B', 8)} && cat $HOME/.claude/settings.json"})),
        9: ("Read outside", ("Read", {"file_path": f"{cell('B', 9)}/../A-1/pkg/tool.py"})),
        10: ("Read relative", ("Read", {"file_path": "pkg/tool.py"})),
        11: ("Glob without", ("Glob", {"pattern": "**/*.py"})),
        12: ("tool: WebFetch", ("WebFetch", {"url": "https://example.invalid", "prompt": "x"})),
        13: ("no-cd", ("Bash", {"command": f"cd {cell('B', 13)}0 && ls"})),
        14: ("updir", ("Bash", {"command": f"cd {cell('B', 14)} && cd .. && ls"})),
        15: ("Edit outside", ("Edit", {"file_path": f"{cell('A', 1)}/pkg/tool.py",
                                       "old_string": "a", "new_string": "b"})),
        16: ("tool: Task", ("Task", {"prompt": "read the fix"})),
    }
    for n, (_, call) in leaky.items():
        _agent(run, f"{n:02d}", f"tier:demo:B:{n}", [call])
    # A truncated line hides a call, and must not stop the agents after it being read.
    _agent(run, "17", "tier:demo:C:1",
           [("Bash", {"command": f"cd {cell('C', 1)} && ls"})], extra="{truncated\n")
    _agent(run, "18", "ab:c10:xhigh", [("Bash", {"command": f"cd {own} && ls"})])

    done = subprocess.run([sys.executable, str(HARNESS / "leaks.py"), str(run), str(ab)],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 1, done.stderr
    hits = {line.split("\t")[0]: line for line in done.stdout.splitlines() if "\t" in line}
    assert "tier:demo:A:1" not in hits, hits.get("tier:demo:A:1")
    for n, (reason, _) in leaky.items():
        label = f"tier:demo:B:{n}"
        assert label in hits, f"{label} ({reason}) was not flagged"
        assert reason in hits[label], hits[label]
    assert "unreadable: 1" in hits["tier:demo:C:1"]
    assert "label is not tier" in hits["ab:c10:xhigh"]
    assert done.stdout.splitlines()[-1] == f"scanned 19 agent(s), {len(leaky) + 2} with hits"
