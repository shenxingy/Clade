"""An unresolvable range is its own outcome — not clean, not a crash.

The CI line was `--range origin/main...HEAD || true`. On a push to main
origin/main IS HEAD, so the range was empty and the gate printed the clean
sentence on every commit it was meant to examine. Making the range
`HEAD~1..HEAD` then crashed the job, because actions/checkout is shallow by
default and HEAD~1 was never fetched. Three outcomes, and each must look
different from the other two.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "configs" / "scripts" / "check-sibling-facts.py"


def _run(*args):
    return subprocess.run([sys.executable, str(GATE), *args],
                          capture_output=True, text=True, cwd=REPO, check=False)


def test_an_unresolvable_range_says_so_and_exits_zero():
    out = _run("--range", "definitely-not-a-ref-xyz..HEAD")
    assert out.returncode == 0
    assert "RANGE NOT CHECKED" in out.stdout


def test_an_unresolvable_range_never_prints_the_clean_sentence():
    # The whole defect: "nothing was examined" reading as "nothing was wrong".
    out = _run("--range", "definitely-not-a-ref-xyz..HEAD")
    assert "no changed fact survives anywhere else" not in out.stdout


def test_a_resolvable_range_still_reports():
    out = _run("--range", "HEAD~1..HEAD")
    assert out.returncode == 0
    assert "RANGE NOT CHECKED" not in out.stdout
    # THREE outcomes, not two. The third — a fact that survives only in an
    # append-only record (changelog, research doc, progress archive) — is a
    # deliberate branch at check-sibling-facts.py:426 and this assertion did not
    # know about it, so the suite went red the first time a real commit produced
    # one (deleting the "4-6 modules" rule from configs/CLAUDE.md while the
    # research doc that argued for its deletion kept quoting it, which is exactly
    # what an append-only record is FOR). A test that enumerates a subset of a
    # tool's outcomes fails on correct behaviour; keep this list in step with the
    # script's print sites.
    assert ("no changed fact survives" in out.stdout
            or "still present elsewhere" in out.stdout
            or "survive ONLY in append-only records" in out.stdout), out.stdout


def test_strict_does_not_fail_on_an_unavailable_range():
    # An environment limitation is not a finding.
    assert _run("--range", "nope..HEAD", "--strict").returncode == 0


def _ci_run_lines() -> list[str]:
    """The executable lines of the sibling-facts step, comments excluded.

    Checking the whole block matched the COMMENT that explains the past bug —
    the same trap the gate's own absence markers exist for, one level up.
    """
    workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    block = workflow.split("Sibling facts")[1].split("- name:")[0]
    return [ln.strip() for ln in block.splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def test_the_ci_step_does_not_use_the_empty_three_dot_range_on_push():
    lines = _ci_run_lines()
    assert any("check-sibling-facts.py" in ln for ln in lines)
    assert not any("origin/main...HEAD" in ln for ln in lines), (
        "on a push to main, actions/checkout leaves origin/main at the pushed "
        "SHA, so this range is empty and the gate reports a clean tree")
    assert any("--deepen=1" in ln for ln in lines), "the push branch needs HEAD~1"


def test_the_ci_step_no_longer_swallows_the_gates_exit_code():
    # `|| true` on the `git fetch --deepen` is fine: a full clone cannot deepen.
    # On the gate itself it hid the RuntimeError that exists to be loud.
    for line in _ci_run_lines():
        if "check-sibling-facts.py" in line:
            assert "|| true" not in line, line


# ─── The step as a local run executes it ───
# ci-local.py cannot evaluate a `${{ }}` expression, so a step holding one is
# skipped and its lane is unproven, and ci-local exits 2 on an unproven lane:
# this step made every local gate of this repository exit 2 (20 of 20 gate
# records on 2026-11-26 were PARTIAL or failed, each on this one lane). It now
# reads the runner's $GITHUB_EVENT_NAME and $GITHUB_BASE_REF, which a local run
# leaves unset, so it takes the push branch, and deepens only a shallow clone.

def _ci_step_script() -> str:
    """The step's `run: |` block, as the runner hands it to bash."""
    workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    block = workflow.split("- name: Sibling facts")[1].split("run: |\n", 1)[1]
    body = []
    for line in block.splitlines():
        if line.strip() and len(line) - len(line.lstrip()) < 10:
            break
        body.append(line[10:])
    return "\n".join(body) + "\n"


def test_a_local_run_executes_the_ci_step(monkeypatch, capsys):
    # Syntax Check is `runs-on: ubuntu-latest`, and ci-local skips a Linux job
    # on any other host: on a Mac the whole job read `[skip]`, this test failed
    # there every time, and the UNPROVEN check below would have passed without
    # looking at a step. So plan it as the Linux host it targets — this asserts
    # how the step is classified, not which OS the test happens to run on.
    monkeypatch.setattr(sys, "path", list(sys.path))   # ci-local.py prepends its dir
    spec = importlib.util.spec_from_file_location(
        "ci_local_cli", REPO / "configs" / "scripts" / "ci-local.py")
    ci_local = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "ci_local_cli", ci_local)   # its dataclasses resolve through it
    spec.loader.exec_module(ci_local)
    monkeypatch.setattr(ci_local, "local_platform", lambda: "Linux")
    monkeypatch.setattr(sys, "argv", ["ci-local.py", "--repo", str(REPO), "--list"])
    assert ci_local.main() == 0
    out = capsys.readouterr().out
    assert "[run ] Syntax Check" in out, out
    assert "UNPROVEN step Sibling facts" not in out, out
    assert "${{" not in _ci_step_script()


def _git(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "-c", "commit.gpgsign=false", *args], cwd=cwd, check=True, capture_output=True)


def _step_world(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    """A bare origin holding two commits (the gate among them), and the env the
    step runs with: no GITHUB_* event variables, and `git` on PATH logging
    every call it is asked to make before running the real one."""
    seed, origin = tmp_path / "seed", tmp_path / "origin.git"
    (seed / "configs" / "scripts").mkdir(parents=True)
    (seed / "configs" / "scripts" / "check-sibling-facts.py").write_bytes(GATE.read_bytes())
    (seed / "a.md").write_text("we ship 32 hooks\n", encoding="utf-8")
    (seed / "b.md").write_text("also 32 hooks\n", encoding="utf-8")
    _git("init", "-q", "-b", "main", str(seed))
    _git("add", "-A", cwd=seed)
    _git("commit", "-q", "-m", "base", cwd=seed)
    (seed / "a.md").write_text("we ship 33 hooks\n", encoding="utf-8")
    _git("commit", "-q", "-am", "change a fact", cwd=seed)
    _git("clone", "-q", "--bare", str(seed), str(origin))
    bindir, calls = tmp_path / "bin", tmp_path / "git-calls"
    bindir.mkdir()
    shim = bindir / "git"
    shim.write_text(f'#!/bin/sh\nprintf \'%s\\n\' "$*" >> "{calls}"\nexec "{shutil.which("git")}" "$@"\n',
                    encoding="utf-8")
    shim.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_EVENT_NAME", "GITHUB_BASE_REF")}
    env.update(PATH=f"{bindir}{os.pathsep}{env.get('PATH', '')}", HOME=str(tmp_path),
               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    return origin, env, calls


def _run_step(work: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", _ci_step_script()],
                          cwd=work, env=env, capture_output=True, text=True, check=False)


def _fetches(calls: Path) -> list[str]:
    lines = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    return [ln for ln in lines if ln.startswith("fetch")]


def test_the_ci_step_runs_offline_in_a_full_clone(tmp_path):
    # A local run: a full clone, no event variables. Its origin is gone, so a
    # fetch could only fail; the step must not need one.
    origin, env, calls = _step_world(tmp_path)
    work = tmp_path / "work"
    _git("clone", "-q", str(origin), str(work))
    _git("remote", "set-url", "origin", str(tmp_path / "gone.git"), cwd=work)
    out = _run_step(work, env)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "RANGE NOT CHECKED" not in out.stdout, out.stdout
    assert "still present elsewhere" in out.stdout, out.stdout
    assert _fetches(calls) == [], "a full clone holds HEAD~1: the step fetched anyway"


def test_the_ci_step_still_deepens_a_shallow_push_checkout(tmp_path):
    # The hosted push: actions/checkout's depth-1 clone has no HEAD~1.
    origin, env, calls = _step_world(tmp_path)
    work = tmp_path / "work"
    _git("clone", "-q", "--depth=1", f"file://{origin}", str(work))
    out = _run_step(work, env)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "RANGE NOT CHECKED" not in out.stdout, out.stdout
    assert _fetches(calls) == ["fetch --no-tags --deepen=1"]


def test_the_ci_step_reads_the_pull_request_event_from_the_runner_env(tmp_path):
    origin, env, calls = _step_world(tmp_path)
    work = tmp_path / "work"
    _git("clone", "-q", str(origin), str(work))
    (work / "b.md").write_text("also 34 hooks\n", encoding="utf-8")
    _git("commit", "-q", "-am", "a PR commit", cwd=work)
    out = _run_step(work, {**env, "GITHUB_EVENT_NAME": "pull_request", "GITHUB_BASE_REF": "main"})
    assert out.returncode == 0, out.stdout + out.stderr
    assert "RANGE NOT CHECKED" not in out.stdout, out.stdout
    assert _fetches(calls) == ["fetch --no-tags --depth=50 origin main"]


def _load():
    spec = importlib.util.spec_from_file_location("csf", GATE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["csf"] = module
    spec.loader.exec_module(module)
    return module


def test_skip_dirs_are_matched_relative_to_the_repository(tmp_path):
    # rglob yields ABSOLUTE paths, so testing path.parts tested every ancestor
    # above the checkout: a clone under any directory named logs/, build/,
    # dist/, .venv/ or node_modules/ scanned ZERO files and printed clean.
    gate = _load()
    nested = tmp_path / "logs" / "repo"
    (nested / "docs").mkdir(parents=True)
    (nested / "docs" / "a.md").write_text("we ship 32 hooks\n", encoding="utf-8")
    (nested / "docs" / "b.md").write_text("also 32 hooks\n", encoding="utf-8")
    gate.REPO = nested
    assert len(gate._tree_files()) == 2
