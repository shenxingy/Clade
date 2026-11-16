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


def _ci_tree(root: Path, doc: str | None, claude_md: str = "") -> Path:
    (root / "configs" / "scripts").mkdir(parents=True)
    script = root / "configs" / "scripts" / CI_CHECKLIST.name
    shutil.copy2(CI_CHECKLIST, script)
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "workflows" / "ci.yml").write_text(_WORKFLOW, encoding="utf-8")
    (root / "CLAUDE.md").write_text(claude_md, encoding="utf-8")
    if doc is not None:
        (root / "docs").mkdir()
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
