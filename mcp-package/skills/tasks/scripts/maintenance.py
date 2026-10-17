#!/usr/bin/env python3
"""Bounded, local-only operations for one explicitly installed task service."""
from __future__ import annotations

import argparse
import configparser
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from typing import Any, Iterator

from tasks import Beads, TaskError, bd_environment, ident, private_write, read_json, state_dir
from service import server_command, unit_quote, write_unit

HEALTH_SCHEMA = "clade.task-service-health/v1"
BACKUP_SCHEMA = "clade.task-backup/v1"
MAX_HEALTH_AGE = 900
MAX_BACKUP_AGE = 36 * 3600
KEEP_BACKUPS = 7
LOG_BYTES = 1024 * 1024
BACKUP_NAME = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{8}\Z")


def load(root: Path) -> dict[str, Any]:
    if root.is_symlink() or not root.is_dir() or root.stat().st_uid != os.getuid():
        raise TaskError("service directory must be an owned real directory")
    if root.stat().st_mode & 0o077:
        raise TaskError("service directory must be private (mode 0700)")
    cfg = read_json(root / "service.json")
    if cfg.get("schema_version") != "clade.task-service/v1":
        raise TaskError("unsupported service manifest")
    ident(cfg.get("project_id"))
    for field, relative in (("workspace", "workspace"), ("credentials_file", "credentials.ini")):
        if Path(cfg[field]).resolve() != root / relative:
            raise TaskError("service manifest paths do not belong to this instance")
    return cfg


@contextmanager
def locked(root: Path) -> Iterator[None]:
    # Unix only: installation explicitly targets a systemd user manager.
    import fcntl
    directory = root / "maintenance"
    directory.mkdir(mode=0o700, exist_ok=True)
    with (directory / "lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise TaskError("maintenance already running; health observation is deferred") from exc
        yield


def run(command: list[str], *, cwd: Path | None = None, timeout: int = 60) -> str:
    result = subprocess.run(command, cwd=cwd, env={**bd_environment(), "GOMAXPROCS": "2"},
                            capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        # Never forward backend stderr: connection diagnostics can contain secrets.
        raise TaskError(f"{Path(command[0]).name} operation failed (exit {result.returncode})")
    return result.stdout.strip()


def control(*args: str) -> str:
    return run(["systemctl", "--user", *args])


def active(unit: str) -> bool:
    return control("show", unit, "--property=ActiveState", "--value") == "active"


def backend(root: Path, cfg: dict[str, Any]) -> Beads:
    return Beads(root / "workspace", cfg["bd"], timeout=15,
                 credentials_file=str(root / "credentials.ini"))


def probe(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    client = backend(root, cfg)
    context = client.context()
    if context["project_id"] != cfg["project_id"]:
        raise TaskError("project identity mismatch")
    if context.get("server_host") != "127.0.0.1" or context.get("server_port") != cfg["port"]:
        raise TaskError("client endpoint differs from this service")
    client.run("ready", "--limit", "1", readonly=True)
    values = client.run("sql", "SELECT @@global.secure_file_priv AS value", readonly=True)
    if values != [{"value": str(root / "sql-files")}]:
        raise TaskError("SQL file access policy is not loaded")
    return context


def wait_ready(root: Path, cfg: dict[str, Any]) -> None:
    deadline = time.monotonic() + 30
    while True:
        try:
            probe(root, cfg)
            return
        except TaskError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)


def event(root: Path, kind: str, detail: dict[str, Any]) -> None:
    path = root / "maintenance" / "events.jsonl"
    if path.exists() and path.stat().st_size >= LOG_BYTES:
        for number in (2, 1):
            source = path.with_name(path.name + f".{number}")
            if source.exists():
                os.replace(source, path.with_name(path.name + f".{number + 1}"))
        os.replace(path, path.with_name(path.name + ".1"))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(json.dumps({"at": time.time(), "event": kind, **detail}) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = read_json(path)
    if not isinstance(value, dict):
        raise TaskError("invalid maintenance record")
    return value


def status(root: Path) -> dict[str, Any]:
    """Read-only, also usable while the database or timer is unavailable."""
    cfg = load(root)
    state = optional_json(root / "maintenance" / "status.json")
    if (state.get("schema_version") != HEALTH_SCHEMA or state.get("project_id") != cfg["project_id"] or
            state.get("status") not in {"HEALTHY", "DEGRADED"} or
            not isinstance(state.get("concerns"), list) or
            any(not isinstance(item, str) for item in state["concerns"]) or
            not isinstance(state.get("backup"), dict) or
            not isinstance(state.get("observed_at"), (int, float)) or
            not math.isfinite(state["observed_at"])):
        return {"status": "UNKNOWN", "concerns": ["maintenance has no valid observation"],
                "project_id": cfg["project_id"]}
    concerns = list(state["concerns"])
    if state["status"] == "DEGRADED" and not concerns:
        concerns.append("last health check degraded")
    age = time.time() - float(state["observed_at"])
    if age > MAX_HEALTH_AGE or age < -60:
        concerns.append("health observation stale; inspect health timer")
    verified = state.get("backup", {}).get("verified_at")
    if not isinstance(verified, (int, float)) or not -60 <= time.time() - verified <= MAX_BACKUP_AGE:
        concerns.append("no fresh verified backup")
    return {**state, "status": "DEGRADED" if concerns else "HEALTHY",
            "concerns": sorted(set(concerns)), "age_seconds": round(age)}


def health(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    concerns = []
    try:
        probe(root, cfg)
    except (TaskError, OSError, ValueError, subprocess.TimeoutExpired):
        concerns.append("authenticated database probe failed")
    if cfg.get("supervisor") == "systemd-user":
        for unit in (cfg["unit"], *cfg["timers"]):
            try:
                if not active(unit):
                    concerns.append(f"inactive unit: {unit}")
                if control("is-enabled", unit) != "enabled":
                    concerns.append(f"unit not enabled: {unit}")
            except (TaskError, OSError, subprocess.TimeoutExpired):
                concerns.append(f"cannot verify unit: {unit}")
    receipt = optional_json(root / "maintenance" / "backup.json")
    verified = receipt.get("verified_at")
    if not verified or not -60 <= time.time() - float(verified) <= MAX_BACKUP_AGE:
        concerns.append("no fresh verified backup")
    if receipt.get("ok") is False:
        concerns.append("last backup or restore verification failed")
    previous = optional_json(root / "maintenance" / "status.json")
    current = {"schema_version": HEALTH_SCHEMA, "project_id": cfg["project_id"],
               "observed_at": time.time(), "status": "DEGRADED" if concerns else "HEALTHY",
               "concerns": sorted(concerns), "backup": receipt}
    if previous.get("concerns") != current["concerns"]:
        event(root, "health_transition", {"status": current["status"], "concerns": concerns})
        # A durable, local alert consumed by /status and /pipeline. stderr also
        # reaches this instance's journal; there is deliberately no outbound sender.
        private_write(root / "maintenance" / "alert.json", current)
        if concerns or previous:
            print("ALERT " + current["status"] + ": " + ("; ".join(concerns) or "recovered"),
                  file=sys.stderr)
    private_write(root / "maintenance" / "status.json", current)
    return current


def regular_tree(path: Path) -> list[Path]:
    members = [path, *path.rglob("*")]
    if any(p.is_symlink() or not (p.is_file() or p.is_dir()) for p in members):
        raise TaskError("backup refuses links and special files")
    return members


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def pack(source: Path, target: Path) -> dict[str, str]:
    hashes = {}
    with tarfile.open(target, "w:gz", dereference=False) as archive:
        for top in ("data", "workspace", "credentials.ini"):
            for member in regular_tree(source / top):
                name = member.relative_to(source).as_posix()
                archive.add(member, arcname=name, recursive=False)
                if member.is_file():
                    hashes[name] = digest(member)
    return hashes


def unpack(archive: Path, target: Path, hashes: dict[str, str]) -> None:
    """Extract only recorded regular files; reject traversal, aliases and bombs."""
    seen: set[str] = set()
    size = 0
    with tarfile.open(archive, "r:gz") as source:
        if any(target.iterdir()):
            raise TaskError("restore target must be empty")
        members = []
        for member in source:
            members.append(member)
            if len(members) > 100000:
                raise TaskError("backup has too many members")
            path = PurePosixPath(member.name)
            if (path.is_absolute() or ".." in path.parts or not path.parts or
                    path.parts[0] not in {"data", "workspace", "credentials.ini"} or
                    member.name in seen or not (member.isfile() or member.isdir())):
                raise TaskError("unsafe backup member")
            if path.as_posix() != member.name or (member.isfile() and member.name not in hashes):
                raise TaskError("unrecorded backup member")
            seen.add(member.name)
            size += member.size
            if size + 64 * 1024 * 1024 > shutil.disk_usage(target).free:
                raise TaskError("insufficient free disk for restore")
        for member in members:
            destination = target / member.name
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True, mode=0o700)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            stream = source.extractfile(member)
            if stream is None:
                raise TaskError("unreadable backup member")
            with stream, destination.open("xb") as output:
                shutil.copyfileobj(stream, output)
            destination.chmod(0o600)
        restored = {p.relative_to(target).as_posix(): digest(p) for p in target.rglob("*") if p.is_file()}
        if restored != hashes:
            raise TaskError("restored file hashes differ from backup")


def verify_archive(root: Path, cfg: dict[str, Any], archive: Path,
                   hashes: dict[str, str]) -> dict[str, Any]:
    # A fresh destination and port are mandatory; no production restore command.
    with tempfile.TemporaryDirectory(prefix="clade-restore-") as temporary:
        scratch = Path(temporary)
        unpack(archive, scratch, hashes)
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        metadata = scratch / "workspace" / ".beads" / "metadata.json"
        routing = read_json(metadata)
        if routing.get("project_id") != cfg["project_id"]:
            raise TaskError("restored project identity mismatch")
        routing.update(dolt_mode="server", dolt_server_host="127.0.0.1", dolt_server_port=port)
        routing.pop("dolt_server_socket", None)
        routing.pop("dolt_data_dir", None)
        private_write(metadata, routing)
        # Replace all inherited routing; never allow a restored client to query
        # the live endpoint through a config.yaml override.
        (metadata.parent / "config.yaml").write_text(
            f"dolt:\n  server:\n    host: 127.0.0.1\n    port: {port}\n")
        # This gitignored routing file wins over metadata and YAML in Beads
        # 1.3.1. Copying it unchanged would probe the original live service.
        (metadata.parent / "dolt-server.port").write_text(str(port) + "\n")
        credentials = configparser.ConfigParser(interpolation=None)
        credentials.read(scratch / "credentials.ini")
        old = f"127.0.0.1:{cfg['port']}"
        password = credentials[old]["password"]
        (scratch / "credentials.ini").write_text(f"[127.0.0.1:{port}]\npassword={password}\n")
        command = server_command(scratch, cfg["dolt"], port, readonly=True)
        with (scratch / "verify.log").open("w") as log:
            server = subprocess.Popen(command, cwd=scratch / "data", stdout=log, stderr=log,
                                      env={**bd_environment(), "GOMAXPROCS": "2"})
            try:
                wait_ready(scratch, {**cfg, "port": port})
                client = backend(scratch, cfg)
                tasks = client.run("list", "--all", "--limit", "0", readonly=True)
                counts = {}
                table_digests = {}
                for table in ("issues", "dependencies", "events"):
                    rows = client.run("sql", f"SELECT * FROM {table}", readonly=True)
                    counts[table] = len(rows)
                    canonical = sorted(json.dumps(row, sort_keys=True) for row in rows)
                    table_digests[table] = hashlib.sha256(json.dumps(canonical).encode()).hexdigest()
                return {"project_id": cfg["project_id"], "tasks": len(tasks), "rows": counts,
                        "table_digests": table_digests,
                        "verified_at": time.time()}
            finally:
                server.terminate()
                try:
                    server.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)


def recover(root: Path, cfg: dict[str, Any]) -> None:
    marker = root / "maintenance" / "restart-required.json"
    if not marker.exists():
        return
    saved = read_json(marker)
    if saved != {"unit": cfg["unit"], "project_id": cfg["project_id"]}:
        raise TaskError("restart marker identity mismatch")
    control("start", cfg["unit"])
    wait_ready(root, cfg)
    marker.unlink()
    event(root, "database_resumed", {})


def prune(root: Path, project_id: str) -> None:
    verified = []
    for path in (root / "backups").iterdir():
        if not BACKUP_NAME.fullmatch(path.name) or path.is_symlink() or not path.is_dir():
            continue
        try:
            receipt = read_json(path / "manifest.json")
            if (receipt.get("schema_version") == BACKUP_SCHEMA and
                    receipt.get("project_id") == project_id and receipt.get("verified_at") and
                    digest(path / "payload.tar.gz") == receipt["sha256"]):
                verified.append(path)
        except (TaskError, OSError, KeyError):
            continue
    for path in sorted(verified, reverse=True)[KEEP_BACKUPS:]:
        shutil.rmtree(path)


def backup(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    if cfg.get("supervisor") != "systemd-user":
        raise TaskError("install maintenance with a systemd user manager before backup")
    destination = root / "backups"
    destination.mkdir(mode=0o700, exist_ok=True)
    # SIGKILL can leave TemporaryDirectory copies behind. Only reap old,
    # private staging names created by this helper, under the maintenance lock.
    for abandoned in destination.iterdir():
        if (re.fullmatch(r"\.partial-[a-z0-9_]{8}", abandoned.name) and
                not abandoned.is_symlink() and abandoned.is_dir() and
                abandoned.stat().st_uid == os.getuid() and not abandoned.stat().st_mode & 0o077 and
                time.time() - abandoned.stat().st_mtime > 86400):
            shutil.rmtree(abandoned)
    previous = optional_json(root / "maintenance" / "backup.json")
    try:
        probe(root, cfg)
        if not active(cfg["unit"]):
            raise TaskError("database unit is not active; backup will not start a stopped service")
        members = [p for top in ("data", "workspace", "credentials.ini") for p in regular_tree(root / top)]
        size = sum(p.stat().st_size for p in members if p.is_file())
        if size * 3 + 64 * 1024 * 1024 > shutil.disk_usage(root).free:
            raise TaskError("insufficient free disk for backup")
        with tempfile.TemporaryDirectory(prefix=".partial-", dir=destination) as temporary:
            stage = Path(temporary)
            copied = stage / "copy"
            copied.mkdir(mode=0o700)
            private_write(root / "maintenance" / "restart-required.json",
                          {"unit": cfg["unit"], "project_id": cfg["project_id"]})
            try:
                control("stop", cfg["unit"])
                if control("show", cfg["unit"], "--property=ActiveState", "--value") != "inactive":
                    raise TaskError("database did not stop; backup refused")
                for top in ("data", "workspace"):
                    regular_tree(root / top)
                    shutil.copytree(root / top, copied / top)
                shutil.copy2(root / "credentials.ini", copied / "credentials.ini")
            finally:
                recover(root, cfg)
            archive = stage / "payload.tar.gz"
            hashes = pack(copied, archive)
            shutil.rmtree(copied)
            restored = verify_archive(root, cfg, archive, hashes)
            name = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8]
            receipt = {"schema_version": BACKUP_SCHEMA, **restored, "ok": True,
                       "sha256": digest(archive), "files": hashes, "archive": name,
                       "bytes": archive.stat().st_size, "attempted_at": time.time()}
            private_write(stage / "manifest.json", receipt)
            with archive.open("rb") as stream:
                os.fsync(stream.fileno())
            os.replace(stage, destination / name)
            # fsync directory entries before publishing the successful receipt.
            fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            public_receipt = {key: value for key, value in receipt.items() if key != "files"}
            private_write(root / "maintenance" / "backup.json", public_receipt)
            event(root, "backup_verified", public_receipt)
            prune(root, cfg["project_id"])
            return public_receipt
    except (TaskError, OSError, ValueError, tarfile.TarError, subprocess.TimeoutExpired):
        private_write(root / "maintenance" / "backup.json",
                      {**previous, "ok": False, "attempted_at": time.time()})
        event(root, "backup_failed", {"error": "backup or isolated restore failed"})
        raise
    finally:
        health(root, cfg)


def configure(root: Path, cfg: dict[str, Any], prefix: str) -> dict[str, Any]:
    """Prepare stable helpers/units without enabling or starting anything."""
    ident(prefix)
    if not re.fullmatch(r"[A-Za-z0-9-]{1,40}", prefix):
        raise TaskError("invalid service prefix")
    if any(c in str(root) for c in "\n\r\t\\$"):
        raise TaskError("unsupported service directory characters")
    routing = read_json(root / "workspace" / ".beads" / "metadata.json")
    port = int(routing["dolt_server_port"])
    dolt = cfg["command"][0]
    command = server_command(root, dolt, port)
    unit = write_unit(root, prefix, command)
    (root / "maintenance").mkdir(mode=0o700, exist_ok=True)
    runtime = root / "runtime"
    runtime.mkdir(mode=0o700, exist_ok=True)
    for name in ("tasks.py", "service.py", "maintenance.py"):
        source = Path(__file__).with_name(name)
        if source.resolve() != (runtime / name).resolve():
            fd, temporary = tempfile.mkstemp(dir=runtime)
            with os.fdopen(fd, "wb") as stream:
                stream.write(source.read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, runtime / name)
    invocation = " ".join(map(unit_quote, [str(Path(sys.executable).resolve()),
                           str(runtime / "maintenance.py"), "--directory", str(root)]))
    timers = []
    for action, schedule in (("health", "OnBootSec=2min\nOnUnitActiveSec=5min\n"),
                             ("backup", "OnCalendar=*-*-* 03:30:00\nPersistent=true\nRandomizedDelaySec=10min\n")):
        stem = unit.stem + "-" + action
        recovery = f"ExecStopPost={invocation} recover\n" if action == "backup" else ""
        (root / f"{stem}.service").write_text(
            f"[Unit]\nDescription=Clade tasks {action}\n\n[Service]\nType=oneshot\n"
            f"ExecStart={invocation} {action}\n{recovery}TimeoutStartSec=15min\n"
            "UMask=0077\nNoNewPrivileges=true\nStandardOutput=journal\nStandardError=journal\n")
        timer = stem + ".timer"
        (root / timer).write_text(f"[Unit]\nDescription=Clade tasks {action} schedule\n\n"
                                 f"[Timer]\n{schedule}Unit={stem}.service\n\n[Install]\nWantedBy=timers.target\n")
        timers.append(timer)
    cfg.update(command=command, dolt=dolt, port=port, prefix=prefix, unit=unit.name, timers=timers)
    private_write(root / "service.json", cfg)
    return cfg


def install(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    units = list(root.glob("clade-tasks-*.service"))
    database_units = [p for p in units if not p.stem.endswith(("-health", "-backup"))]
    if "prefix" in cfg:
        prefix = cfg["prefix"]
    elif len(database_units) == 1:
        prefix = database_units[0].stem.removeprefix("clade-tasks-")
    else:
        raise TaskError("cannot identify the existing service; no units changed")
    name = f"clade-tasks-{prefix}.service"
    for candidate in (name, *(f"clade-tasks-{prefix}-{action}.{suffix}"
                             for action in ("health", "backup") for suffix in ("service", "timer"))):
        loaded = control("show", candidate, "--property=FragmentPath", "--value")
        if loaded and Path(loaded).resolve() != root / candidate:
            raise TaskError("unit name belongs to another instance")
    registry = Path.home() / ".clade" / "task-services" / f"{cfg['project_id']}.json"
    if registry.exists() and read_json(registry).get("directory") != str(root):
        raise TaskError("project already registered at another directory")
    cfg = configure(root, cfg, prefix)
    for unit in (cfg["unit"], *(t.replace(".timer", ".service") for t in cfg["timers"]), *cfg["timers"]):
        control("link", str(root / unit))
    control("daemon-reload")
    control("enable", cfg["unit"], *cfg["timers"])
    cfg["supervisor"] = "systemd-user"
    private_write(root / "service.json", cfg)
    control("restart", cfg["unit"])
    wait_ready(root, cfg)
    private_write(registry, {"schema_version": "clade.task-service-registration/v1",
                            "directory": str(root), "project_id": cfg["project_id"], "name": prefix})
    # An initial actual backup, restore and health observation are part of
    # installation. A failed backup is a failed installation, not a green timer.
    receipt = backup(root, cfg)
    control("start", *cfg["timers"])
    observation = health(root, cfg)
    if observation["status"] != "HEALTHY":
        raise TaskError("installed units need attention; inspect maintenance status")
    return {"installed": True, "unit": cfg["unit"], "timers": cfg["timers"],
            "backup": receipt, "health": observation}


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    location = parser.add_mutually_exclusive_group()
    location.add_argument("--directory", type=Path)
    location.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("action", choices=("install", "health", "backup", "recover", "status", "verify"))
    parser.add_argument("--archive", type=Path, help="verified backup directory for an isolated restore drill")
    args = parser.parse_args()
    try:
        root = args.directory
        if root is None:
            bound = read_json(state_dir(args.repo) / "binding.json")
            root = Path(bound["workspace"]).parent
        root = root.absolute()
        cfg = load(root)
        if args.action == "status":
            result = status(root)
        else:
            with locked(root):
                if args.action == "install":
                    result = install(root, cfg)
                elif args.action == "health":
                    result = health(root, cfg)
                elif args.action == "backup":
                    result = backup(root, cfg)
                elif args.action == "recover":
                    recover(root, cfg)
                    result = {"recovery_checked": True}
                else:
                    if args.archive is None:
                        raise TaskError("verify requires --archive BACKUP_DIRECTORY")
                    receipt = read_json(args.archive / "manifest.json")
                    archive = args.archive / "payload.tar.gz"
                    if (receipt.get("schema_version") != BACKUP_SCHEMA or
                            receipt.get("project_id") != cfg["project_id"] or
                            digest(archive) != receipt["sha256"]):
                        raise TaskError("backup identity or archive checksum mismatch")
                    result = verify_archive(root, cfg, archive, receipt["files"])
                    event(root, "restore_verified", result)
        print(json.dumps(result, indent=2))
        return 0 if result.get("status", "HEALTHY") == "HEALTHY" else 1
    except (TaskError, OSError, ValueError, KeyError, TypeError, tarfile.TarError,
            subprocess.TimeoutExpired) as exc:
        message = str(exc) if isinstance(exc, TaskError) else "maintenance failed; inspect the private service directory"
        print(json.dumps({"error": message}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
