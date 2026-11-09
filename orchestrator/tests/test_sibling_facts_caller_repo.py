"""check-sibling-facts.py examines the CALLER's repository, not its own checkout.

REPO was `Path(__file__).resolve().parents[2]`. The global rules tell every
project to run the script, and install.sh deploys it to ~/.claude/scripts/, so
from any other repository it diffed and searched Clade (or the parent of
~/.claude) and printed a clean result about a tree it had never read. Found
from docforensics, which had to grep by hand instead (its TODO-154).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "configs" / "scripts" / "check-sibling-facts.py"


def _env(ceiling: Path | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    if ceiling is not None:
        env["GIT_CEILING_DIRECTORIES"] = str(ceiling)
    return env


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                    "-c", "commit.gpgsign=false", *args],
                   cwd=root, env=_env(), check=True, capture_output=True)


def _other_repo(tmp_path: Path) -> Path:
    root = tmp_path / "other"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "a.md").write_text("the gate runs 61 suites\n", encoding="utf-8")
    (root / "README.md").write_text("we keep 61 suites green\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    (root / "docs" / "a.md").write_text("the gate runs 62 suites\n", encoding="utf-8")
    return root


def _run(cwd: Path, *args: str, env: dict[str, str] | None = None):
    return subprocess.run([sys.executable, str(GATE), *args], cwd=cwd,
                          env=env or _env(), capture_output=True, text=True,
                          check=False, timeout=120)


def test_run_from_another_repo_reports_that_repos_sibling(tmp_path):
    out = _run(_other_repo(tmp_path))
    assert out.returncode == 0, out.stderr
    assert "61 suites" in out.stdout, out.stdout
    assert "still in:   README.md" in out.stdout, out.stdout
    assert "changed in: docs/a.md" in out.stdout, out.stdout


def test_run_from_a_subdirectory_searches_the_whole_repo(tmp_path):
    # git diff names files from the top level; a cwd-rooted tree search would
    # miss README.md one level up and print the clean sentence.
    out = _run(_other_repo(tmp_path) / "docs")
    assert "still in:   README.md" in out.stdout, out.stdout


def test_strict_fails_on_the_callers_survivor(tmp_path):
    assert _run(_other_repo(tmp_path), "--strict").returncode == 1


def test_outside_any_repo_says_not_checked(tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()
    out = _run(bare, env=_env(ceiling=tmp_path))
    assert out.returncode == 0
    assert "NOT CHECKED" in out.stdout, out.stdout
    assert "no changed fact survives anywhere else" not in out.stdout
