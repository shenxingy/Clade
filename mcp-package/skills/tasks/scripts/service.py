#!/usr/bin/env python3
"""Prepare one private Beads service. Installs no tools and enables no service."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time

from tasks import BD_VERSION, Beads, TaskError, bd_environment, ident, private_write

DOLT_VERSION = "2.2.0"


def server_command(root: Path, dolt: str, port: int, *, readonly: bool = False) -> list[str]:
    """Use JSON's YAML subset; SQL file access is confined before listening."""
    files = root / "sql-files"
    files.mkdir(mode=0o700, exist_ok=True)
    private_write(root / "server.yaml", {
        "listener": {"host": "127.0.0.1", "port": port, "max_connections": 32,
                     "socket": str(root / "mysql.sock")},
        "data_dir": str(root / "data"), "log_level": "info", "log_format": "json",
        "behavior": {"read_only": readonly},
        "system_variables": {"secure_file_priv": str(files)},
    })
    # In pinned 2.2.0 this flag is read independently of YAML config. Keep the
    # anonymous-root integration probe: the help's blanket 'flags ignored' is
    # misleading here (sqlserver.go passes apr.Contains directly to Serve).
    return [dolt, "sql-server", "--config", str(root / "server.yaml"),
            "--skip-root-user-initialization"]


def unit_quote(value: str) -> str:
    if any(char in value for char in "\n\r\t$"):
        raise TaskError("service paths must not contain control characters or dollar signs")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def write_unit(root: Path, prefix: str, command: list[str]) -> Path:
    unit = root / f"clade-tasks-{prefix}.service"
    unit.write_text("[Unit]\nDescription=Clade personal task database\n\n[Service]\n"
                    f"WorkingDirectory={unit_quote(str(root / 'data'))}\n"
                    f"ExecStart={' '.join(map(unit_quote, command))}\n"
                    "Environment=GOMAXPROCS=2\nRestart=on-failure\nRestartSec=3\nUMask=0077\n"
                    "NoNewPrivileges=true\nStandardOutput=journal\nStandardError=journal\n"
                    "\n[Install]\nWantedBy=default.target\n")
    return unit


def checked(command: list[str], cwd: Path, env: dict[str, str], stdin: str | None = None) -> str:
    result = subprocess.run(command, cwd=cwd, env=env, input=stdin, text=True,
                            capture_output=True, timeout=60)
    if result.returncode:
        # SQL input and connection diagnostics may contain the generated password.
        raise TaskError(f"{Path(command[0]).name} setup failed (exit {result.returncode}); private directory retained for diagnosis")
    return result.stdout


def prepare(args: argparse.Namespace) -> dict:
    root = args.directory.resolve()
    if any(char in str(root) for char in "\n\r\t\\$"):
        raise TaskError("choose a service path without control characters, backslashes or dollar signs")
    prefix = ident(args.prefix)
    if len(prefix) > 40 or not prefix.replace("-", "").isalnum():
        raise TaskError("prefix must be at most 40 letters, digits or hyphens")
    if not 1024 <= args.port <= 65535:
        raise TaskError("choose an explicit unprivileged port between 1024 and 65535")
    bd, dolt = shutil.which(args.bd), shutil.which(args.dolt)
    if not bd or not dolt:
        raise TaskError(f"install Beads {BD_VERSION} and Dolt {DOLT_VERSION} first")
    bd, dolt = str(Path(bd).resolve()), str(Path(dolt).resolve())
    env = bd_environment()
    env.update(GOMAXPROCS="2")
    inside_git = subprocess.run(["git", "-C", str(root.parent), "rev-parse", "--show-toplevel"],
                                capture_output=True, env=env, timeout=10)
    if inside_git.returncode == 0:
        raise TaskError("place private service data outside any Git checkout")
    if f"version {DOLT_VERSION}\n" not in checked([dolt, "version"], Path.cwd(), env):
        raise TaskError(f"requires verified Dolt {DOLT_VERSION}")
    version = checked([bd, "version", "--json"], Path.cwd(), env)
    if json.loads(version).get("version") != BD_VERSION:
        raise TaskError(f"requires verified Beads {BD_VERSION}")
    # Existing directories are never reinitialized, even after failed setup.
    root.mkdir(mode=0o700)
    data, workspace = root / "data", root / "workspace"
    data.mkdir(mode=0o700)
    workspace.mkdir(mode=0o700)
    password = secrets.token_hex(32)
    # Bootstrap privileges before opening any socket. Never put SQL/passwords in argv.
    checked([dolt, "sql"], data, env,
            f"CREATE USER 'clade'@'%' IDENTIFIED BY '{password}';\n"
            "GRANT ALL ON *.* TO 'clade'@'%';\nDROP USER IF EXISTS 'root'@'localhost';\n")
    credentials = root / "credentials.ini"
    fd = os.open(credentials, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(f"[127.0.0.1:{args.port}]\npassword={password}\n")
    command = server_command(root, dolt, args.port)
    env["BEADS_CREDENTIALS_FILE"] = str(credentials)
    checked(["git", "init", "-q", str(workspace)], root, env)
    for key, value in (("user.name", "Clade Tasks"), ("user.email", "tasks@localhost")):
        checked(["git", "config", key, value], workspace, env)
    with (root / "setup.log").open("w") as log:
        process = subprocess.Popen(command, cwd=data, env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 10
            while True:
                if process.poll() is not None:
                    raise TaskError("Dolt exited during setup; inspect private setup.log")
                try:
                    with socket.create_connection(("127.0.0.1", args.port), timeout=0.1):
                        break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TaskError("Dolt did not start within 10 seconds")
                    time.sleep(0.1)
            # init's connection path reads the password environment directly;
            # ordinary commands resolve the private credentials file.
            init_env = {**env, "BEADS_DOLT_PASSWORD": password}
            checked([bd, "init", "--server", "--external", "--server-host", "127.0.0.1",
                     "--server-port", str(args.port), "--server-user", "clade", "--prefix", prefix,
                     "--skip-agents", "--skip-hooks", "--non-interactive"], workspace, init_env)
            backend = Beads(workspace, bd, credentials_file=str(credentials))
            context = backend.context()
            backend.run("ready", "--limit", "1", readonly=True)
            # Anonymous root must be refused before any persistent service is offered.
            probe = subprocess.run([dolt, "--host", "127.0.0.1", "--port", str(args.port),
                                    "--user", "root", "--password", "", "--no-tls", "sql", "-q", "SELECT 1"],
                                   cwd=root, env=env, capture_output=True, text=True, timeout=15)
            if probe.returncode == 0:
                raise TaskError("anonymous root still has access; service was stopped")
            if "Access denied" not in probe.stderr:
                raise TaskError("could not verify anonymous root rejection; service was stopped")
        finally:
            process.terminate()
            process.wait(timeout=15)
    private_write(root / "service.json", {"schema_version": "clade.task-service/v1",
                  "command": command, "workspace": str(workspace), "project_id": context["project_id"],
                  "credentials_file": str(credentials), "bd": bd})
    unit = write_unit(root, prefix, command)
    return {"prepared": True, "running": False, "project_id": context["project_id"],
            "workspace": str(workspace), "credentials_file": str(credentials),
            "unit": str(unit), "bd": bd}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True, help="new directory on verified local disk")
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--bd", default="bd")
    parser.add_argument("--dolt", default="dolt")
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args), indent=2))
        return 0
    except (TaskError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        message = str(exc) if isinstance(exc, TaskError) else "setup failed; inspect the private directory, do not overwrite it"
        print(json.dumps({"error": message}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
