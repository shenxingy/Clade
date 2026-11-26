"""The two gates that pin a document read it from docs/, and fail when it is gone.

On 2026-11-16 the CI checklist moved from CLAUDE.md to docs/ci-gates.md and the
orchestrator map to docs/orchestrator-architecture.md, so that every Clade
session stops loading them. A gate still reading CLAUDE.md would then compare CI
against the few pointer lines left there, and `check-arch-map.py` used to treat
a missing doc as a silent no-op, which a renamed docs/ file would trigger with
CI green. These run both scripts as CI does, on the live tree and on small
synthetic trees.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ARCH_MAP = REPO / "configs" / "scripts" / "check-arch-map.py"
CI_CHECKLIST = REPO / "configs" / "scripts" / "check-ci-checklist.py"


def _run(script: Path, *args: str, cwd: Path = REPO) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(script), *args], cwd=cwd,
                          capture_output=True, text=True, timeout=60)


# ─── check-arch-map.py ───────────────────────────────────────────────────────


def _orchestrator_tree(root: Path) -> None:
    (root / "orchestrator" / "routes").mkdir(parents=True)
    (root / "orchestrator" / "alpha.py").write_text("", encoding="utf-8")
    (root / "orchestrator" / "routes" / "beta.py").write_text("", encoding="utf-8")
    (root / "docs").mkdir()


def test_arch_map_passes_on_the_live_tree_and_names_its_doc():
    result = _run(ARCH_MAP)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "docs/orchestrator-architecture.md" in result.stdout


def test_arch_map_passes_when_every_module_is_listed(tmp_path):
    _orchestrator_tree(tmp_path)
    (tmp_path / "docs" / "orchestrator-architecture.md").write_text(
        "alpha.py ← one\nroutes/beta.py ← two\n", encoding="utf-8")
    result = _run(ARCH_MAP, "--root", str(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr


def test_arch_map_names_a_module_missing_from_the_doc(tmp_path):
    _orchestrator_tree(tmp_path)
    (tmp_path / "docs" / "orchestrator-architecture.md").write_text(
        "alpha.py ← one\n", encoding="utf-8")
    result = _run(ARCH_MAP, "--root", str(tmp_path))
    assert result.returncode == 1
    assert "orchestrator/routes/beta.py" in result.stdout


def test_arch_map_reads_the_docs_file_not_claude_md(tmp_path):
    _orchestrator_tree(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("alpha.py\nroutes/beta.py\n", encoding="utf-8")
    (tmp_path / "docs" / "orchestrator-architecture.md").write_text(
        "alpha.py ← one\n", encoding="utf-8")
    result = _run(ARCH_MAP, "--root", str(tmp_path))
    assert result.returncode == 1
    assert "orchestrator/routes/beta.py" in result.stdout


def test_arch_map_fails_when_the_doc_is_missing(tmp_path):
    _orchestrator_tree(tmp_path)
    result = _run(ARCH_MAP, "--root", str(tmp_path))
    assert result.returncode == 1, "a missing map must not pass silently"
    assert "docs/orchestrator-architecture.md" in result.stderr


def test_arch_map_is_a_no_op_without_an_orchestrator_dir(tmp_path):
    result = _run(ARCH_MAP, "--root", str(tmp_path))
    assert result.returncode == 0
    assert "silent no-op" in result.stderr


# ─── check-ci-checklist.py ───────────────────────────────────────────────────
# The script finds its repository from its own path, so each synthetic tree
# gets a copy of it at configs/scripts/.

_WORKFLOW = """\
name: CI
on: [push]
jobs:
  shell-tests:
    runs-on: ubuntu-latest
    steps:
      - name: Run foo suite
        run: bash tests/test-foo.sh
"""


def _ci_tree(root: Path, doc: str | None, claude_md: str = "", *,
             workflow: str = _WORKFLOW, files: tuple[str, ...] = ("tests/test-foo.sh",),
             source: str | None = None) -> Path:
    (root / "configs" / "scripts").mkdir(parents=True)
    script = root / "configs" / "scripts" / CI_CHECKLIST.name
    shutil.copy2(CI_CHECKLIST, script)
    if source is not None:
        script.write_text(source, encoding="utf-8")
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "workflows" / "ci.yml").write_text(workflow, encoding="utf-8")
    (root / "CLAUDE.md").write_text(claude_md, encoding="utf-8")
    for rel in files:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("", encoding="utf-8")
    if doc is not None:
        (root / "docs").mkdir(exist_ok=True)
        (root / "docs" / "ci-gates.md").write_text(doc, encoding="utf-8")
    return script


def test_ci_checklist_passes_on_the_live_tree_and_names_its_doc():
    result = _run(CI_CHECKLIST)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "docs/ci-gates.md covers all" in result.stdout


def test_ci_checklist_passes_when_the_doc_names_every_gate(tmp_path):
    script = _ci_tree(tmp_path, "# CI gates\n\n## CI (GitHub Actions)\n\nbash tests/test-foo.sh\n")
    result = _run(script, cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_ci_checklist_names_a_gate_the_doc_omits(tmp_path):
    script = _ci_tree(tmp_path, "# CI gates\n\n## CI (GitHub Actions)\n\nnothing here\n")
    result = _run(script, cwd=tmp_path)
    assert result.returncode == 1
    assert "tests/test-foo.sh" in result.stderr
    assert "docs/ci-gates.md" in result.stderr


def test_ci_checklist_reads_the_docs_file_not_claude_md(tmp_path):
    script = _ci_tree(tmp_path, "# CI gates\n\n## CI (GitHub Actions)\n\nnothing here\n",
                      claude_md="## CI (GitHub Actions)\n\nbash tests/test-foo.sh\n")
    result = _run(script, cwd=tmp_path)
    assert result.returncode == 1
    assert "tests/test-foo.sh" in result.stderr


def test_ci_checklist_fails_when_the_doc_is_missing(tmp_path):
    script = _ci_tree(tmp_path, None, claude_md="## CI (GitHub Actions)\n\nbash tests/test-foo.sh\n")
    result = _run(script, cwd=tmp_path)
    assert result.returncode == 1
    assert "docs/ci-gates.md is missing" in result.stderr


# A suite CI runs and the doc lists, but that is not in the tree, used to pass:
# coverage compares which artefacts are NAMED, so the gate stayed green while
# CI's own `bash tests/test-foo.sh` step would fail (#208 review).

_FOO_DOC = "# CI gates\n\n## CI (GitHub Actions)\n\nbash tests/test-foo.sh\n"
_LOOP_DOC = ('# CI gates\n\n## CI (GitHub Actions)\n\n'
             'for t in foo bar; do bash "tests/test-$t.sh"; done\n')
_EVALS_WORKFLOW = _WORKFLOW + """\
  evals:
    runs-on: ubuntu-latest
    steps:
      - name: Score the corpus
        run: |
          cd orchestrator
          python evals/run_x.py
"""
_EVALS_DOC = _FOO_DOC + "cd orchestrator && .venv/bin/python evals/run_x.py\n"


def test_ci_checklist_names_a_suite_that_ci_runs_but_the_tree_lacks(tmp_path):
    script = _ci_tree(tmp_path, _FOO_DOC, files=())
    result = _run(script, cwd=tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "tests/test-foo.sh" in result.stderr
    assert "ci.yml:shell-tests" in result.stderr
    assert "no such file" in result.stderr


def test_ci_checklist_names_a_looped_suite_name_with_no_file(tmp_path):
    script = _ci_tree(tmp_path, _LOOP_DOC)
    result = _run(script, cwd=tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "tests/test-bar.sh" in result.stderr
    assert "listed in docs/ci-gates.md" in result.stderr
    assert "tests/test-foo.sh" not in result.stderr


def test_ci_checklist_finds_evals_under_orchestrator(tmp_path):
    # CI and the doc both reach evals/ through `cd orchestrator`, so a root-level
    # evals/run_x.py is not the file they run.
    script = _ci_tree(tmp_path, _EVALS_DOC, workflow=_EVALS_WORKFLOW,
                      files=("tests/test-foo.sh", "orchestrator/evals/run_x.py"))
    result = _run(script, cwd=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr

    wrong = tmp_path / "wrong-home"
    wrong.mkdir()
    script = _ci_tree(wrong, _EVALS_DOC, workflow=_EVALS_WORKFLOW,
                      files=("tests/test-foo.sh", "evals/run_x.py"))
    result = _run(script, cwd=wrong)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "evals/run_x.py" in result.stderr


# Each guard of the file check, removed from a copy of the script: the fixture
# that claims it must flip. An anchor that no longer matches fails here rather
# than mutating nothing.
_FILE_GUARD_MUTATIONS = [
    ("the existence test itself",
     "        if not (home / artefact).is_file():\n",
     "        if False:\n",
     dict(doc=_FOO_DOC, files=()), 0),
    ("the call site in main()",
     "    if absent:\n",
     "    if False:\n",
     dict(doc=_FOO_DOC, files=()), 0),
    ("the checklist's own names",
     '        named.setdefault(artefact, []).append(f"listed in {CHECKLIST_REL}")\n',
     "        pass\n",
     dict(doc=_LOOP_DOC), 0),
    ("evals/ resolved against orchestrator/",
     'ARTEFACT_HOMES = {"evals": "orchestrator"}\n',
     "ARTEFACT_HOMES: dict[str, str] = {}\n",
     dict(doc=_EVALS_DOC, workflow=_EVALS_WORKFLOW,
          files=("tests/test-foo.sh", "orchestrator/evals/run_x.py")), 1),
]


@pytest.mark.parametrize("what,old,new,tree,mutant_rc", _FILE_GUARD_MUTATIONS,
                         ids=[m[0] for m in _FILE_GUARD_MUTATIONS])
def test_ci_checklist_file_guards_can_fire(tmp_path, what, old, new, tree, mutant_rc):
    source = CI_CHECKLIST.read_text(encoding="utf-8")
    assert source.count(old) == 1, f"mutation anchor moved: {what}"
    real = _run(_ci_tree(tmp_path / "real", **tree), cwd=tmp_path / "real")
    mutant = _run(_ci_tree(tmp_path / "mutant", source=source.replace(old, new), **tree),
                  cwd=tmp_path / "mutant")
    assert real.returncode == 1 - mutant_rc, real.stdout + real.stderr
    assert mutant.returncode == mutant_rc, f"removing {what} went unnoticed"
