from __future__ import annotations

import importlib.util
import json
import subprocess
from argparse import Namespace
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
TASKS = REPO_ROOT / "configs" / "skills" / "tasks" / "scripts" / "tasks.py"


def _load_tasks():
    spec = importlib.util.spec_from_file_location("clade_shared_tasks", TASKS)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tasks = _load_tasks()


def _task(key: str, *, depends_on: list[str] | None = None,
          owns: list[str] | None = None, priority: int = 2) -> dict:
    return {
        "key": key,
        "title": f"Title {key}",
        "description": f"Description {key}",
        "acceptance": f"Acceptance {key}",
        "depends_on": depends_on or [],
        "owns": owns or [],
        "priority": priority,
    }


def _plan(*items: dict) -> dict:
    return {"plan_id": "plan-1", "tasks": list(items)}


def test_compile_plan_preserves_blocks_direction_and_allows_independent_paths() -> None:
    graph, _ = tasks.compile_plan(
        _plan(
            _task("A", depends_on=["B"], owns=["a.py"]),
            _task("B", owns=["b.py"]),
            _task("C", owns=["c.py"]),
        ),
        "clade",
    )

    assert {"from_key": "A", "to_key": "B", "type": "blocks"} in graph["edges"]
    assert {"from_key": "B", "to_key": "A", "type": "blocks"} not in graph["edges"]


@pytest.mark.parametrize(
    ("items", "message"),
    [
        ([_task("A", depends_on=["A"])], "dependency cycle"),
        ([_task("A", depends_on=["missing"])], "unknown dependency"),
        ([_task("A"), _task("A")], "duplicate task key"),
    ],
)
def test_compile_plan_rejects_cycles_duplicates_and_unknown_dependencies(
    items: list[dict], message: str,
) -> None:
    with pytest.raises(tasks.TaskError, match=message):
        tasks.compile_plan(_plan(*items), "clade")


def test_compile_plan_requires_transitive_dependency_for_overlapping_paths() -> None:
    with pytest.raises(tasks.TaskError, match="overlapping ownership"):
        tasks.compile_plan(
            _plan(
                _task("A", depends_on=["C"], owns=["src"]),
                _task("B", depends_on=["C"], owns=["src/file.py"]),
                _task("C"),
            ),
            "clade",
        )

    graph, _ = tasks.compile_plan(
        _plan(
            _task("A", depends_on=["B"], owns=["src"]),
            _task("B", depends_on=["C"], owns=["src/file.py"]),
            _task("C"),
        ),
        "clade",
    )
    assert len(graph["nodes"]) == 3


@pytest.mark.parametrize(
    "change",
    [
        {"owns": ["../outside"]},
        {"owns": ["src/*.py"]},
        {"priority": True},
        {"priority": 5},
    ],
)
def test_compile_plan_rejects_malformed_owns_and_priority(change: dict) -> None:
    item = _task("A")
    item.update(change)
    with pytest.raises(tasks.TaskError):
        tasks.compile_plan(_plan(item), "clade")


@pytest.mark.parametrize(("status", "phase"), [("blocked", "submitted"), ("closed", "accepted")])
def test_project_task_uses_submitting_session_and_excludes_private_fields(status: str, phase: str) -> None:
    projected = tasks.project_task(
        {
            "id": "clade-1",
            "title": "Submitted task",
            "status": status,
            "assignee": "old-holder",
            "updated_at": "2026-10-17T00:00:00Z",
            "heartbeat_at": None,
            "lease_expires_at": None,
            "workspace": "/private/workspace",
            "credential": "secret",
            "metadata": {
                "clade_submission": {"session_id": "submitter"},
                "clade_session": {"session_id": "observer"},
                "clade_owns": ["src"],
            },
            "dependency_count": 1,
            "acceptance_criteria": "reviewed",
        }
    )

    assert projected["state"] == phase
    assert projected["assignee"] == "submitter"
    assert "workspace" not in projected
    assert "credential" not in projected


def test_bd_environment_ignores_ambient_routing_and_keeps_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BEADS_PROJECT", "wrong-project")
    monkeypatch.setenv("BD_DATABASE", "/wrong/database")
    monkeypatch.setenv("GIT_DIR", "/wrong/git")
    monkeypatch.setenv("BEADS_DOLT_PASSWORD", "preserve-secret")

    environment = tasks.bd_environment()

    assert "BEADS_PROJECT" not in environment
    assert "BD_DATABASE" not in environment
    assert "GIT_DIR" not in environment
    assert environment["BEADS_DOLT_PASSWORD"] == "preserve-secret"
    assert environment["BD_DISABLE_METRICS"] == "1"
    assert environment["BD_DISABLE_EVENT_FLUSH"] == "1"
    assert environment["BD_LAST_TOUCHED_FALLBACK"] == "0"


def test_beads_timeout_is_unknown_and_does_not_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def timeout(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise subprocess.TimeoutExpired(kwargs.get("args", args[0]), 1)

    monkeypatch.setattr(tasks.subprocess, "run", timeout)
    backend = tasks.Beads(Path("/tmp/workspace"), "/usr/bin/bd", timeout=1)

    with pytest.raises(tasks.TaskError, match="write outcome is unknown"):
        backend.run("update", "clade-1")
    assert calls == 1


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True,
                            capture_output=True, text=True)
    return result.stdout.strip()


def _git_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    workspace = tmp_path / "beads-workspace"
    repo.mkdir()
    workspace.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.test")
    (repo / "README").write_text("fixture\n", encoding="utf-8")
    _git(repo, "add", "README")
    _git(repo, "commit", "-qm", "initial")
    worktree = tmp_path / "worktree"
    _git(repo, "worktree", "add", "-q", "-b", "agent", str(worktree), "main")
    return repo, worktree


def test_bind_persists_in_git_common_dir_and_rejects_mismatch_or_rebind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, worktree = _git_repo(tmp_path)
    other_workspace = tmp_path / "other-workspace"
    other_workspace.mkdir()
    monkeypatch.setattr(tasks.shutil, "which", lambda _: "/usr/bin/bd")
    monkeypatch.setattr(tasks.Beads, "context", lambda self: {
        "bd_version": tasks.BD_VERSION,
        "dolt_mode": "server",
        "project_id": "project-1",
        "database": "db-1",
    })
    monkeypatch.setattr(tasks.Beads, "run", lambda self, *args, **kwargs: [])

    mismatch = Namespace(repo=worktree, workspace=tmp_path / "first", bd="bd",
                         project_id="wrong-project", timeout=30)
    mismatch.workspace.mkdir()
    with pytest.raises(tasks.TaskError, match="project identity mismatch"):
        tasks.bind(mismatch)
    assert not (tasks.state_dir(repo) / "binding.json").exists()

    first = Namespace(repo=worktree, workspace=tmp_path / "first", bd="bd",
                      project_id="project-1", timeout=30)
    assert tasks.bind(first)["bound"] is True
    binding_path = tasks.state_dir(worktree) / "binding.json"
    assert binding_path.exists()
    assert json.loads(binding_path.read_text(encoding="utf-8"))["workspace"] == str(first.workspace.resolve())

    rebound = Namespace(repo=repo, workspace=other_workspace, bd="bd",
                        project_id="project-1", timeout=30)
    with pytest.raises(tasks.TaskError, match="different workspace"):
        tasks.bind(rebound)
