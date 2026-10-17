"""Maintenance observations, archive boundaries and failure recovery."""
import importlib.util
import io
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tarfile
import time
from argparse import Namespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "configs/skills/tasks/scripts"


@pytest.fixture
def ops(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("clade_task_maintenance", SCRIPTS / "maintenance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def instance(tmp_path, ops):
    root = tmp_path / "instance"
    root.mkdir(mode=0o700)
    (root / "maintenance").mkdir()
    cfg = {"schema_version": "clade.task-service/v1", "project_id": "fixture",
           "workspace": str(root / "workspace"), "credentials_file": str(root / "credentials.ini"),
           "bd": "/unused", "unit": "clade-tasks-fixture.service", "supervisor": "systemd-user",
           "timers": ["clade-tasks-fixture-health.timer", "clade-tasks-fixture-backup.timer"]}
    ops.private_write(root / "service.json", cfg)
    return root, cfg


def test_observer_reports_stale_timer_and_backup_without_database(instance, ops):
    root, cfg = instance
    state = {"schema_version": ops.HEALTH_SCHEMA, "project_id": cfg["project_id"],
             "observed_at": time.time(), "status": "HEALTHY", "concerns": [],
             "backup": {"verified_at": time.time()}}
    ops.private_write(root / "maintenance/status.json", state)
    assert ops.status(root)["status"] == "HEALTHY"
    state["observed_at"] -= 901
    ops.private_write(root / "maintenance/status.json", state)
    assert "health observation stale; inspect health timer" in ops.status(root)["concerns"]
    state.update(observed_at=time.time(), backup={})
    ops.private_write(root / "maintenance/status.json", state)
    assert ops.status(root)["status"] == "DEGRADED"
    state["project_id"] = "other"
    ops.private_write(root / "maintenance/status.json", state)
    assert ops.status(root)["status"] == "UNKNOWN"


def test_health_failure_and_recovery_are_durable_and_deduplicated(instance, ops, monkeypatch, capsys):
    root, cfg = instance
    ops.private_write(root / "maintenance/backup.json", {"verified_at": time.time(), "ok": True})
    monkeypatch.setattr(ops, "active", lambda unit: True)
    monkeypatch.setattr(ops, "control", lambda *args: "enabled")
    def unavailable(*args):
        raise ops.TaskError("hidden connection details")
    monkeypatch.setattr(ops, "probe", unavailable)
    assert ops.health(root, cfg)["status"] == "DEGRADED"
    ops.health(root, cfg)
    assert (root / "maintenance/events.jsonl").read_text().count("health_transition") == 1
    assert "hidden connection" not in capsys.readouterr().err
    monkeypatch.setattr(ops, "probe", lambda *args: {})
    assert ops.health(root, cfg)["status"] == "HEALTHY"
    assert json.loads((root / "maintenance/alert.json").read_text())["status"] == "HEALTHY"
    assert "recovered" in capsys.readouterr().err
    assert (root / "maintenance/events.jsonl").read_text().count("health_transition") == 2


def test_maintenance_lock_rejects_concurrency_and_releases_after_exception(instance, ops):
    root, _ = instance
    with ops.locked(root):
        with pytest.raises(ops.TaskError, match="already running"):
            with ops.locked(root):
                pytest.fail("concurrent writer entered")
    with ops.locked(root):
        pass


@pytest.mark.parametrize("kind,name", [("file", "../escape"), ("symlink", "data/link"),
                                       ("hardlink", "data/hard"), ("file", "/absolute"),
                                       ("file", "data/../escape"), ("file", "runtime/evil.py")])
def test_restore_rejects_unsafe_archive_members_before_writing(tmp_path, ops, kind, name):
    archive = tmp_path / "unsafe.tar.gz"
    target = tmp_path / "target"
    target.mkdir()
    with tarfile.open(archive, "w:gz") as out:
        entry = tarfile.TarInfo(name)
        entry.size = 1
        if kind != "file":
            entry.type = tarfile.SYMTYPE if kind == "symlink" else tarfile.LNKTYPE
            entry.linkname = "../../escape"
            entry.size = 0
        out.addfile(entry, io.BytesIO(b"x"))
    with pytest.raises(ops.TaskError, match="unsafe backup"):
        ops.unpack(archive, target, {name: "dummy"})
    assert list(target.iterdir()) == []
    assert not (tmp_path / "escape").exists()


def test_backup_copy_failure_restores_service_and_preserves_previous_backup(instance, ops, monkeypatch):
    root, cfg = instance
    for name in ("data", "workspace"):
        (root / name).mkdir()
        (root / name / "important").write_text("preserved")
    (root / "credentials.ini").write_text("secret fixture")
    previous = {"ok": True, "verified_at": time.time(), "archive": "previous"}
    ops.private_write(root / "maintenance/backup.json", previous)
    running = {"value": True}
    def control(*args):
        if args[0] in ("stop", "start"):
            assert args[1] == cfg["unit"]
            running["value"] = args[0] == "start"
        return "active" if running["value"] else "inactive"
    monkeypatch.setattr(ops, "control", control)
    monkeypatch.setattr(ops, "active", lambda unit: running["value"])
    monkeypatch.setattr(ops, "probe", lambda *args: {})
    monkeypatch.setattr(ops, "health", lambda *args: {})
    def failed_copy(*args, **kwargs):
        assert running["value"] is False
        raise OSError("copy failed")
    monkeypatch.setattr(ops.shutil, "copytree", failed_copy)
    with pytest.raises(OSError, match="copy failed"):
        ops.backup(root, cfg)
    assert running["value"] is True
    assert not (root / "maintenance/restart-required.json").exists()
    receipt = json.loads((root / "maintenance/backup.json").read_text())
    assert receipt["ok"] is False
    assert receipt["verified_at"] == previous["verified_at"]
    assert (root / "data/important").read_text() == "preserved"
    assert list((root / "backups").iterdir()) == []


def test_retention_only_deletes_verified_same_project_archives(instance, ops):
    root, cfg = instance
    directory = root / "backups"
    directory.mkdir()
    names = [f"20261017T{n:06}Z-1234abcd" for n in range(10)]
    for name in names:
        path = directory / name
        path.mkdir()
        (path / "payload.tar.gz").write_bytes(b"fixture")
        ops.private_write(path / "manifest.json", {"schema_version": ops.BACKUP_SCHEMA,
                          "project_id": cfg["project_id"], "verified_at": time.time(),
                          "sha256": ops.digest(path / "payload.tar.gz")})
    unknown = directory / "operator-snapshot"
    unknown.mkdir()
    (directory / names[0] / "payload.tar.gz").write_bytes(b"corrupt")
    foreign = json.loads((directory / names[1] / "manifest.json").read_text())
    foreign["project_id"] = "another-project"
    ops.private_write(directory / names[1] / "manifest.json", foreign)
    ops.prune(root, cfg["project_id"])
    assert not (directory / names[2]).exists()
    assert all((directory / name).exists() for name in [names[0], names[1], *names[3:]])
    assert unknown.exists()


def test_event_log_is_bounded_and_private(instance, ops, monkeypatch):
    root, _ = instance
    monkeypatch.setattr(ops, "LOG_BYTES", 64)
    for n in range(20):
        ops.event(root, "fixture", {"n": n, "detail": "x" * 64})
    paths = list((root / "maintenance").glob("events.jsonl*"))
    assert len(paths) == 4
    assert all(p.stat().st_mode & 0o077 == 0 for p in paths)
    assert all(p.stat().st_size < 256 for p in paths)


@pytest.mark.skipif(not os.environ.get("CLADE_TEST_BD") or not os.environ.get("CLADE_TEST_DOLT"),
                    reason="requires explicit verified Beads/Dolt binaries")
def test_stopped_backup_restores_real_tasks_dependencies_and_history(tmp_path, ops, monkeypatch):
    from service import prepare
    monkeypatch.setenv("GOMAXPROCS", "2")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    root = tmp_path / "personal"
    prepared = prepare(Namespace(directory=root, prefix="fixture", port=port,
                       bd=os.environ["CLADE_TEST_BD"], dolt=os.environ["CLADE_TEST_DOLT"]))
    assert prepared["running"] is False
    assert (root / "runtime/maintenance.py").is_file()
    cfg = ops.load(root)
    cfg["supervisor"] = "systemd-user"
    ops.private_write(root / "service.json", cfg)
    processes = []
    log = (root / "live-test.log").open("w")

    def control(*args):
        # Replace only the supervisor transport. The database, credentials,
        # shutdown, backup extraction and restored queries are all real.
        if args[0] == "start":
            assert args[1] == cfg["unit"]
            if not processes or processes[-1].poll() is not None:
                processes.append(subprocess.Popen(cfg["command"], cwd=root / "data", stdout=log,
                                                  stderr=log, env={**os.environ, "GOMAXPROCS": "2"}))
        elif args[0] == "stop":
            assert args[1] == cfg["unit"]
            processes[-1].terminate()
            processes[-1].wait(timeout=15)
        elif args[0] == "show":
            if args[1] in cfg["timers"]:
                return "active"
            return "active" if processes and processes[-1].poll() is None else "inactive"
        elif args[0] == "is-enabled":
            return "enabled"
        else:
            pytest.fail(f"unexpected supervisor operation: {args}")
        return ""

    monkeypatch.setattr(ops, "control", control)
    try:
        control("start", cfg["unit"])
        ops.wait_ready(root, cfg)
        client = ops.backend(root, cfg)
        first = client.run("create", "First", "--type", "task")["id"]
        second = client.run("create", "Blocked", "--type", "task")["id"]
        client.run("dep", "add", second, first)
        client.run("update", first, "--status", "in_progress", "--assignee", "codex-fixture")
        expected = {}
        for table in ("issues", "dependencies", "events"):
            rows = client.run("sql", f"SELECT * FROM {table}", readonly=True)
            canonical = sorted(json.dumps(row, sort_keys=True) for row in rows)
            expected[table] = hashlib.sha256(json.dumps(canonical).encode()).hexdigest()
        pid = processes[-1].pid
        with ops.locked(root):
            receipt = ops.backup(root, cfg)
        assert processes[-1].pid != pid
        assert receipt["tasks"] == 2
        assert receipt["rows"]["dependencies"] == 1
        assert receipt["rows"]["events"] >= 3
        assert receipt["table_digests"] == expected
        assert ops.status(root)["status"] == "HEALTHY"
        assert not (root / "maintenance/restart-required.json").exists()
        task = client.run("show", first, readonly=True)[0]
        assert task["assignee"] == "codex-fixture"
        assert task["status"] == "in_progress"
        assert [t["id"] for t in client.run("ready", readonly=True)] == []
        saved = root / "backups" / receipt["archive"]
        assert ops.digest(saved / "payload.tar.gz") == receipt["sha256"]
        # The stable installed helper can perform a second isolated drill even
        # while the original service stays live, without changing its tasks.
        result = subprocess.run([os.sys.executable, str(root / "runtime/maintenance.py"),
                                 "--directory", str(root), "verify", "--archive", str(saved)],
                                text=True, capture_output=True, timeout=60)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["table_digests"] == expected
        assert client.run("show", first, readonly=True)[0]["status"] == "in_progress"
    finally:
        if processes and processes[-1].poll() is None:
            processes[-1].terminate()
            processes[-1].wait(timeout=15)
        log.close()
