"""Opt-in real Beads/Dolt boundary tests; no fake store can prove these claims.

CLADE_TEST_BD=/path/to/bd CLADE_TEST_DOLT=/path/to/dolt pytest ... -q
Creates only temporary repositories/databases; never uses a personal task store.
"""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import socket
import shutil
import sys
import time
from argparse import Namespace
from threading import Barrier

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "configs/skills/tasks/scripts/tasks.py"
BD = os.environ.get("CLADE_TEST_BD")
DOLT = os.environ.get("CLADE_TEST_DOLT")
pytestmark = pytest.mark.skipif(not BD or not DOLT, reason="requires explicit verified Beads/Dolt binaries")


@pytest.fixture
def service(tmp_path, monkeypatch, request):
    monkeypatch.setenv("PATH", f"{Path(DOLT).parent}:{Path(BD).parent}:{os.environ['PATH']}")
    monkeypatch.setenv("GOMAXPROCS", "2")
    monkeypatch.setenv("BD_DISABLE_METRICS", "1")
    spec = importlib.util.spec_from_file_location("shared_tasks_live", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    repo, workspace = tmp_path / "code", tmp_path / "beads"
    for directory in (repo, workspace):
        directory.mkdir(mode=0o700)
        subprocess.run(["git", "init", "-q", str(directory)], check=True)
        for key, value in (("user.name", "Fixture"), ("user.email", "fixture@example.invalid")):
            subprocess.run(["git", "-C", str(directory), "config", key, value], check=True)
    (repo / "README").write_text("fixture\n")
    subprocess.run(["git", "-C", str(repo), "add", "README"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)
    data = tmp_path / "data"
    data.mkdir(mode=0o700)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    command = [DOLT, "sql-server", "--host", "127.0.0.1", "--port", str(port),
               "--data-dir", str(data), "--socket", str(tmp_path / "mysql.sock"), "--max-connections", "16"]
    log = (tmp_path / "server.log").open("w+")

    def start():
        process = subprocess.Popen(command, cwd=data, env=module.bd_environment(), stdout=log, stderr=log)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            assert process.poll() is None, "Dolt test server exited"
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    return process
            except OSError:
                time.sleep(0.05)
        process.terminate()
        process.wait(timeout=10)
        pytest.fail("Dolt test server did not become ready")

    process = start()

    def cleanup():
        process.terminate()
        process.wait(timeout=15)
        log.close()

    request.addfinalizer(cleanup)
    init = subprocess.run([BD, "init", "--prefix", "fixture", "--server", "--external",
                           "--server-host", "127.0.0.1", "--server-port", str(port), "--skip-agents",
                           "--skip-hooks", "--non-interactive"], cwd=workspace,
                          env=module.bd_environment(), capture_output=True, text=True, timeout=60)
    assert init.returncode == 0, init.stderr
    backend = module.Beads(workspace, BD)
    project_id = backend.context()["project_id"]

    def cli(*args, expected=0, at=None):
        result = subprocess.run([sys.executable, str(HELPER), "--repo", str(at or repo), *args],
                                text=True, capture_output=True, timeout=45)
        assert result.returncode == expected, result.stdout + result.stderr
        return json.loads(result.stdout if result.returncode == 0 else result.stderr)

    cli("bind", "--workspace", str(workspace), "--project-id", project_id, "--bd", BD)
    def restart(restore=False, during_stop=None):
        nonlocal process, data
        process.terminate()
        process.wait(timeout=15)
        if during_stop:
            during_stop()
        if restore:
            backup = tmp_path / "backup"
            shutil.copytree(data, backup)
            data = tmp_path / "restored"
            shutil.copytree(backup, data)
            command[command.index("--data-dir") + 1] = str(data)
        process = start()

    yield module, repo, workspace, backend, cli, restart


def test_real_claim_dependency_review_handoff_worktree_and_restart(service, tmp_path):
    module, repo, workspace, backend, cli, restart = service
    a = cli("session", "--runtime", "codex")["session_id"]
    b = cli("session", "--runtime", "claude", "--parent-session", a)["session_id"]
    human = cli("session", "--runtime", "human")["session_id"]
    plan = {"plan_id": "integration", "tasks": [
        {"key": "api", "title": "API", "description": "Define API", "acceptance": "Contract reviewed", "owns": ["api/"]},
        {"key": "docs", "title": "Docs", "description": "Write docs", "acceptance": "Examples checked", "owns": ["docs/"]},
        {"key": "ui", "title": "UI", "description": "Use API", "acceptance": "Integration passes", "depends_on": ["api"], "owns": ["ui/"]},
    ]}
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    ids = cli("plan", "--session", human, "--file", str(path))["ids"]
    assert cli("plan", "--session", human, "--file", str(path))["already_imported"]
    ready = {x["task_id"] for x in cli("ready")["tasks"]}
    assert ready == {ids["api"], ids["docs"]}
    cli("claim", ids["ui"], "--session", a, expected=2)

    # Two real processes compete through the SQL server, not a Python lock.
    def claim(session_id):
        return subprocess.run([sys.executable, str(HELPER), "--repo", str(repo), "claim", ids["api"],
                               "--session", session_id], text=True, capture_output=True, timeout=45)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, (a, b)))
    assert sorted(x.returncode for x in results) == [0, 2], [x.stdout + x.stderr for x in results]
    owner, other = (a, b) if results[0].returncode == 0 else (b, a)
    assert backend.run("show", ids["api"], readonly=True)[0]["assignee"] == owner
    cli("heartbeat", ids["api"], "--session", owner)
    cli("claim", ids["docs"], "--session", other)
    transferred = cli("handoff", ids["api"], "--session", owner, "--to-session", human,
                      "--expected-status", "in_progress", "--context", "Contract drafted, check examples")
    assert transferred["task"]["session"]["session_id"] == human
    # The former holder's runtime/parent must not be attributed to a
    # recipient that has not attached its own session metadata yet.
    for field in ("runtime", "parent_session_id", "started_at"):
        assert transferred["task"]["session"].get(field) is None
    head = module.git(repo, "rev-parse", "HEAD")
    submit_args = ("--head", head, "--verification", "fixture contract review", "--result", "passed")
    cli("submit", ids["api"], "--session", owner, *submit_args, expected=2)
    cli("claim", ids["api"], "--session", human)  # attaches receiving session identity
    cli("heartbeat", ids["api"], "--session", human)
    cli("submit", ids["api"], "--session", human, *submit_args)
    assert ids["ui"] not in {x["task_id"] for x in cli("ready")["tasks"]}
    cli("accept", ids["api"], "--session", human, "--holder", human, "--head", head,
        "--review", "self review", expected=2)
    cli("request-changes", ids["api"], "--session", owner, "--holder", human,
        "--head", head, "--review", "Clarify examples")
    cli("submit", ids["api"], "--session", human, *submit_args)
    cli("accept", ids["api"], "--session", owner, "--holder", human,
        "--head", head, "--review", "Contract and examples checked")
    assert ids["ui"] in {x["task_id"] for x in cli("ready")["tasks"]}
    assert backend.run("show", ids["api"], readonly=True)[0]["status"] == "closed"
    assert cli("show", ids["api"])["assignee"] == human
    assert cli("history", ids["api"])

    second = tmp_path / "worktree"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "--detach", str(second)],
                   check=True, capture_output=True)
    snapshot = cli("snapshot", at=second)
    assert snapshot["schema_version"] == "clade.task-snapshot/v1"
    assert {t["task_id"] for t in snapshot["tasks"]} == set(ids.values())
    assert str(workspace) not in json.dumps(snapshot)
    assert snapshot["project_id"] == cli("snapshot")["project_id"]
    def while_stopped():
        cli("ready", expected=2)
        assert not (repo / ".beads").exists()

    restart(during_stop=while_stopped)
    assert {t["task_id"] for t in cli("snapshot")["tasks"]} == set(ids.values())
    assert cli("show", ids["api"])["state"] == "accepted"
    restart(restore=True)
    assert cli("snapshot")["project_id"] == snapshot["project_id"]
    assert {t["task_id"] for t in cli("snapshot")["tasks"]} == set(ids.values())
    assert cli("show", ids["api"])["state"] == "accepted"


def test_real_stale_review_cannot_accept_resubmitted_head(service, tmp_path, monkeypatch):
    module, repo, _, backend, cli, _ = service
    worker = cli("session", "--runtime", "kimi")["session_id"]
    reviewer = cli("session", "--runtime", "human")["session_id"]
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"plan_id": "aba", "tasks": [
        {"key": "work", "title": "Work", "description": "Do work", "acceptance": "Reviewed"}]}))
    task = cli("plan", "--session", reviewer, "--file", str(path))["ids"]["work"]
    cli("claim", task, "--session", worker)
    head = module.git(repo, "rev-parse", "HEAD")
    submit = ("submit", task, "--session", worker, "--head", head, "--verification", "check", "--result", "pass")
    cli(*submit)
    stale = module.show(backend, task)
    cli("request-changes", task, "--session", reviewer, "--holder", worker,
        "--head", head, "--review", "Revise")
    cli(*submit)
    # Resume an acceptance operation that read the old submission before the
    # return/resubmit. Its old review holder must fail inside the real DB.
    with pytest.raises(module.TaskError, match="owner or status changed"):
        module.guarded_update(backend, task, stale["metadata"]["clade_submission"]["review_token"],
                              "blocked", reviewer, ["--status", "closed"], {})
    assert module.show(backend, task)["status"] == "blocked"


def test_real_plan_identity_rejects_replacement_and_competing_graphs(service, tmp_path, monkeypatch):
    module, _, _, backend, cli, _ = service
    actor = cli("session", "--runtime", "human")["session_id"]
    files = []
    for key in ("first", "replacement"):
        path = tmp_path / f"{key}.json"
        path.write_text(json.dumps({"plan_id": "one-plan", "tasks": [
            {"key": key, "title": key, "description": key, "acceptance": "Reviewed"}]}))
        files.append(path)
    original_run = backend.run
    barrier = Barrier(2)

    def concurrent_run(*args, **kwargs):
        if args[0] == "create":
            barrier.wait(timeout=10)  # both imports have observed an empty plan
        return original_run(*args, **kwargs)

    monkeypatch.setattr(backend, "run", concurrent_run)

    def import_one(path):
        try:
            return module.import_plan(backend, Namespace(file=path, dry_run=False), actor)
        except module.TaskError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(import_one, files))
    assert sum(isinstance(result, dict) for result in results) == 1
    winning = next(result for result in results if isinstance(result, dict))
    assert {task["task_id"] for task in cli("snapshot")["tasks"]} == set(winning["ids"].values())
    losing_path = files[next(i for i, result in enumerate(results) if isinstance(result, module.TaskError))]
    cli("plan", "--session", actor, "--file", str(losing_path), expected=2)
    assert {task["task_id"] for task in cli("snapshot")["tasks"]} == set(winning["ids"].values())


def test_prepared_service_has_private_auth_and_no_anonymous_root(tmp_path, monkeypatch):
    monkeypatch.setenv("GOMAXPROCS", "2")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    root = tmp_path / "personal"
    result = subprocess.run([sys.executable, str(HELPER.with_name("service.py")),
                             "--directory", str(root), "--prefix", "personal", "--port", str(port),
                             "--bd", BD, "--dolt", DOLT], text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    prepared = json.loads(result.stdout)
    assert prepared["running"] is False
    assert root.stat().st_mode & 0o077 == 0
    credentials = Path(prepared["credentials_file"])
    assert credentials.stat().st_mode & 0o077 == 0
    assert "password=" not in result.stdout
    config = json.loads((root / "service.json").read_text())
    with (root / "verify.log").open("w") as log:
        server = subprocess.Popen(config["command"], cwd=root / "data", stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 10
            while True:
                assert server.poll() is None
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                        break
                except OSError:
                    assert time.monotonic() < deadline
                    time.sleep(0.05)
            env = {**os.environ, "BEADS_CREDENTIALS_FILE": str(credentials), "BD_DISABLE_METRICS": "1"}
            read = subprocess.run([BD, "--readonly", "--json", "ready"], cwd=prepared["workspace"],
                                  env=env, capture_output=True, text=True, timeout=15)
            assert read.returncode == 0, read.stderr
            assert json.loads(read.stdout) == []
            # Exercise the installed client boundary too: an empty checkout
            # binds to this authenticated store despite stale shell routing.
            code = tmp_path / "empty-code"
            subprocess.run(["git", "init", "-q", str(code)], check=True)
            stale_env = {**os.environ, "BEADS_DOLT_PASSWORD": "wrong-ambient-password",
                         "BEADS_DIR": str(tmp_path / "wrong-store"), "GIT_DIR": str(tmp_path / "wrong-git")}
            client = [sys.executable, str(HELPER), "--repo", str(code)]
            bound = subprocess.run([*client, "bind", "--workspace", prepared["workspace"],
                                    "--project-id", prepared["project_id"], "--bd", BD,
                                    "--credentials-file", str(credentials)], env=stale_env,
                                   capture_output=True, text=True, timeout=15)
            assert bound.returncode == 0, bound.stderr
            snapshot = subprocess.run([*client, "snapshot"], env=stale_env,
                                      capture_output=True, text=True, timeout=15)
            assert snapshot.returncode == 0, snapshot.stderr
            observed = json.loads(snapshot.stdout)
            assert observed["project_id"] == prepared["project_id"]
            assert observed["tasks"] == []
            anonymous = subprocess.run([DOLT, "--host", "127.0.0.1", "--port", str(port),
                                       "--user", "root", "--password", "", "--no-tls", "sql", "-q", "SELECT 1"],
                                      cwd=root, text=True, capture_output=True, timeout=15)
            assert anonymous.returncode != 0
            # Failed authentication is different from a dead/unreachable service.
            assert "Access denied" in anonymous.stderr
            # Observe SQL's file boundary, not just a configured variable or log.
            export = tmp_path / "must-not-export.txt"
            file_probe = subprocess.run([BD, "--json", "sql",
                                         f"SELECT 'canary' INTO OUTFILE '{export}'"],
                                        cwd=prepared["workspace"], env=env,
                                        text=True, capture_output=True, timeout=15)
            assert file_probe.returncode != 0, "SQL can export outside its private file directory"
            assert not export.exists()
            value = subprocess.run([BD, "--readonly", "--json", "sql",
                                    "SELECT @@global.secure_file_priv AS value"],
                                   cwd=prepared["workspace"], env=env,
                                   text=True, capture_output=True, timeout=15)
            assert value.returncode == 0, value.stderr
            assert json.loads(value.stdout) == [{"value": str(root / "sql-files")}]
        finally:
            server.terminate()
            server.wait(timeout=15)
    repeated = subprocess.run([sys.executable, str(HELPER.with_name("service.py")),
                               "--directory", str(root), "--prefix", "personal", "--port", str(port),
                               "--bd", BD, "--dolt", DOLT], text=True, capture_output=True, timeout=15)
    assert repeated.returncode == 2
    assert json.loads((root / "service.json").read_text()) == config
