"""Deterministic review checks independent of the LLM oracle.

Leaf module: stdlib only.  Checks are deliberately small and bounded; they add
an independent evidence dimension without attempting to replace code review.
"""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
from pathlib import Path


_SYNTAX_TIMEOUT = 20
_TEST_TIMEOUT = 60
_EVIDENCE_LIMIT = 4000


def _run(
    command: list[str] | str,
    cwd: Path,
    timeout: int,
    *,
    env: dict[str, str] | None = None,
) -> tuple[bool, str]:
    """Run one bounded check, killing its process group and draining on timeout."""
    try:
        proc = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=env,
            shell=isinstance(command, str),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        try:
            output, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                proc.kill()
            output, _ = proc.communicate()
            detail = (output or "").strip()
            evidence = f"timed out after {timeout}s"
            if detail:
                evidence += f"\n{detail}"
            return False, evidence[:_EVIDENCE_LIMIT]
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"could not run check: {type(exc).__name__}: {exc}"[:_EVIDENCE_LIMIT]

    output = (output or "").strip()
    evidence = output or ("passed" if proc.returncode == 0 else f"exit code {proc.returncode}")
    return proc.returncode == 0, evidence[:_EVIDENCE_LIMIT]


def _existing_changed_files(worktree_dir: Path, changed_files: list[str]) -> list[Path]:
    """Return existing files confined to the worktree (deleted files are skipped)."""
    root = worktree_dir.resolve()
    found: list[Path] = []
    for raw in changed_files:
        candidate = (root / raw).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if candidate.is_file():
            found.append(candidate)
    return found


def _detect_test_command(project_dir: Path) -> str | None:
    """Detect a runnable test command using fault_localize's marker strategy."""
    config_path = project_dir / ".claude" / "orchestrator.json"
    try:
        configured = json.loads(config_path.read_text()).get("test_cmd")
        if isinstance(configured, str) and configured.strip():
            return configured
    except (OSError, ValueError, AttributeError):
        pass

    venv_pytest = project_dir / ".venv" / "bin" / "pytest"
    if venv_pytest.is_file():
        return shlex.join([str(venv_pytest)])
    if (project_dir / "go.mod").is_file():
        return "go test ./..."
    if (project_dir / "Cargo.toml").is_file():
        return "cargo test"

    package_json = project_dir / "package.json"
    try:
        package = json.loads(package_json.read_text())
        deps = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
        if "vitest" in deps:
            return "npx vitest run"
        if "jest" in deps:
            return "npx jest"
        test_script = package.get("scripts", {}).get("test", "")
        if "--test" in test_script:
            return "npm test"
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return None


def deterministic_checks(worktree_dir: str | Path, changed_files: list[str]) -> dict:
    """Run model-independent syntax checks and a detected bounded test command."""
    root = Path(worktree_dir).resolve()
    files = _existing_changed_files(root, changed_files)
    checks: list[dict] = []

    python_files = [str(path) for path in files if path.suffix == ".py"]
    if python_files:
        with tempfile.TemporaryDirectory(prefix="clade-pycache-") as cache_dir:
            env = os.environ.copy()
            env["PYTHONPYCACHEPREFIX"] = cache_dir
            ok, evidence = _run(
                [sys.executable, "-m", "py_compile", *python_files],
                root,
                _SYNTAX_TIMEOUT,
                env=env,
            )
        checks.append({"name": "py_compile", "ok": ok, "evidence": evidence})

    shell_files = [str(path) for path in files if path.suffix == ".sh"]
    if shell_files:
        shell_results = [
            (path, *_run(["bash", "-n", path], root, _SYNTAX_TIMEOUT))
            for path in shell_files
        ]
        ok = all(result[1] for result in shell_results)
        evidence = "\n".join(
            f"{Path(path).name}: {detail}"
            for path, file_ok, detail in shell_results
            if not file_ok or detail != "passed"
        ) or "passed"
        checks.append({
            "name": "bash_n",
            "ok": ok,
            "evidence": evidence[:_EVIDENCE_LIMIT],
        })

    test_command = _detect_test_command(root)
    if test_command:
        ok, evidence = _run(test_command, root, _TEST_TIMEOUT)
        checks.append({"name": "test_suite", "ok": ok, "evidence": evidence})

    return {"passed": all(check["ok"] for check in checks), "checks": checks}


def changed_files_from_diff(diff: str) -> list[str]:
    """Extract existing-side paths from a standard ``git diff`` patch."""
    return [line[6:] for line in diff.splitlines() if line.startswith("+++ b/")]


def check_error(exc: Exception) -> dict:
    """Represent a check-infrastructure error as failed deterministic evidence."""
    return {
        "passed": False,
        "checks": [{
            "name": "judge_diversity",
            "ok": False,
            "evidence": f"check error: {type(exc).__name__}",
        }],
    }


def oracle_agreement(oracle_approved: bool, diversity: dict) -> str:
    """Classify whether the oracle and deterministic evidence agree."""
    deterministic_passed = bool(diversity.get("passed", False))
    if oracle_approved and not deterministic_passed:
        return "oracle-lenient"
    if not oracle_approved and deterministic_passed:
        return "oracle-strict"
    return "agree"
