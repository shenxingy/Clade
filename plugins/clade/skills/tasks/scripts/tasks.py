#!/usr/bin/env python3
"""Shared Clade tasks over the verified Beads CLI; no second task database."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any
import uuid

BD_VERSION = "1.3.1"
SCHEMA = "clade.tasks/v1"
LABEL = "clade-task"
PLAN_LABEL = "clade-plan-import"
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class TaskError(Exception):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ident(value: Any) -> str:
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise TaskError("expected a nonempty ID of letters, digits, dots, hyphens or underscores")
    return value


def nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TaskError(f"{field} must be nonempty text")
    return value


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TaskError(f"cannot read valid JSON from {path.name}") from exc


def private_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                            text=True, timeout=15, env=bd_environment())
    if result.returncode:
        raise TaskError("Git operation failed; use a valid repository and revision")
    return result.stdout.strip()


def state_dir(repo: Path) -> Path:
    return Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "clade" / "tasks"


def bd_environment() -> dict[str, str]:
    # A shell left in another project's environment must not redirect this binding.
    credentials = {"BEADS_DOLT_PASSWORD", "BEADS_CREDENTIALS_FILE",
                   "BEADS_DOLT_SERVER_TLS", "BEADS_PROXIED_SERVER_EXTERNAL_PASSWORD"}
    env = {k: v for k, v in os.environ.items()
           if (not k.startswith(("BEADS_", "BD_", "GIT_")) or k in credentials)}
    env.update(BD_DISABLE_METRICS="1", BD_DISABLE_EVENT_FLUSH="1",
               BD_LAST_TOUCHED_FALLBACK="0", NO_COLOR="1")
    return env


class Beads:
    def __init__(self, workspace: Path, binary: str, timeout: int = 30,
                 credentials_file: str | None = None):
        self.workspace = workspace.resolve()
        self.binary = binary
        self.timeout = timeout
        self.credentials_file = credentials_file

    def run(self, *args: str, actor: str = "clade-observer", readonly: bool = False) -> Any:
        command = [self.binary, "--json", "--sandbox", "--actor", ident(actor)]
        if readonly:
            command.append("--readonly")
        command.extend(args)
        env = bd_environment()
        if self.credentials_file:
            env["BEADS_CREDENTIALS_FILE"] = self.credentials_file
            env.pop("BEADS_DOLT_PASSWORD", None)
        try:
            result = subprocess.run(command, cwd=self.workspace, env=env,
                                    capture_output=True, text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired as exc:
            raise TaskError("Beads timed out; write outcome is unknown. Inspect the task before retrying; do not create a replacement database.") from exc
        except OSError as exc:
            raise TaskError("Beads could not start; check the bound executable and workspace") from exc
        if result.returncode:
            # Upstream diagnostics can contain credentials/endpoints; don't forward them.
            if result.returncode == 13:
                raise TaskError("task owner or status changed; this session's update was rejected")
            raise TaskError(f"Beads {args[0]} failed (exit {result.returncode}); check backend availability, ownership, dependencies and version with bd in the private workspace")
        try:
            return json.loads(result.stdout)
        except ValueError as exc:
            raise TaskError("Beads returned invalid JSON; write outcome is unknown, inspect before retrying") from exc

    def context(self) -> dict[str, Any]:
        context = self.run("context", readonly=True)
        if not isinstance(context, dict) or context.get("bd_version") != BD_VERSION:
            raise TaskError(f"this adapter requires verified Beads {BD_VERSION}")
        # v1.3.1's proxied default refuses strict readonly. Monitoring must not
        # silently drop that protection, so this adapter pins the server route.
        if context.get("dolt_mode") != "server":
            raise TaskError("shared tasks require explicit external server mode; Beads 1.3.1 proxied-server cannot guarantee readonly monitoring")
        ident(context.get("project_id"))
        return context


def binding(repo: Path, timeout: int = 30) -> tuple[Beads, dict[str, Any]]:
    data = read_json(state_dir(repo) / "binding.json")
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA:
        raise TaskError("unsupported task binding")
    backend = Beads(Path(data["workspace"]), data["bd"], timeout, data.get("credentials_file"))
    context = backend.context()
    if context["project_id"] != data["project_id"] or context["database"] != data["database"]:
        raise TaskError("project identity mismatch; refusing the connection")
    return backend, data


def bind(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(git(args.repo, "rev-parse", "--show-toplevel"))
    workspace = args.workspace.resolve()
    if workspace == root or root in workspace.parents:
        raise TaskError("use a private Beads workspace outside the code checkout")
    binary = shutil.which(args.bd)
    if not binary:
        raise TaskError(f"install verified Beads {BD_VERSION}, then pass --bd")
    credentials = getattr(args, "credentials_file", None)
    backend = Beads(workspace, str(Path(binary).resolve()), args.timeout,
                    str(credentials.resolve()) if credentials else None)
    context = backend.context()
    if context["project_id"] != ident(args.project_id):
        raise TaskError("project identity mismatch; binding was not written")
    # A real read opens the database and invokes Beads' server identity check.
    backend.run("ready", "--limit", "1", readonly=True)
    data = {"schema_version": SCHEMA, "project_id": context["project_id"],
            "database": context["database"], "workspace": str(workspace),
            "bd": backend.binary}
    if backend.credentials_file:
        data["credentials_file"] = backend.credentials_file
    path = state_dir(args.repo) / "binding.json"
    # Exclusive creation: two binders must not silently replace one another.
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if read_json(path) != data:
            raise TaskError("repository already bound to a different workspace; inspect the existing private binding")
    else:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
    return {"schema_version": SCHEMA, "project_id": data["project_id"], "bound": True}


def session(args: argparse.Namespace) -> dict[str, Any]:
    _, data = binding(args.repo, args.timeout)
    runtime = ident(args.runtime)
    record = {"session_id": f"{runtime}-{uuid.uuid4().hex}", "runtime": runtime,
              "parent_session_id": ident(args.parent_session) if args.parent_session else None,
              "started_at": now(), "project_id": data["project_id"]}
    private_write(state_dir(args.repo) / "sessions" / f"{record['session_id']}.json", record)
    return record


def load_session(repo: Path, session_id: str, project_id: str) -> dict[str, Any]:
    record = read_json(state_dir(repo) / "sessions" / f"{ident(session_id)}.json")
    if record.get("session_id") != session_id or record.get("project_id") != project_id:
        raise TaskError("session belongs to a different project")
    return record


def compile_plan(plan: Any, prefix: str) -> tuple[dict[str, Any], str]:
    if not isinstance(plan, dict) or set(plan) - {"plan_id", "tasks"}:
        raise TaskError("plan must contain only plan_id and tasks")
    plan_id = ident(plan.get("plan_id"))
    tasks = plan.get("tasks")
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 500:
        raise TaskError("plan needs 1–500 tasks")
    keyed: dict[str, dict[str, Any]] = {}
    for task in tasks:
        if not isinstance(task, dict) or set(task) - {"key", "title", "description", "acceptance", "depends_on", "owns", "priority"}:
            raise TaskError("task contains unsupported fields")
        key = ident(task.get("key"))
        if key in keyed:
            raise TaskError(f"duplicate task key: {key}")
        for field in ("title", "description", "acceptance"):
            nonempty(task.get(field), field)
        deps = task.get("depends_on", [])
        owns = task.get("owns", [])
        if not isinstance(deps, list) or len(set(map(ident, deps))) != len(deps):
            raise TaskError("depends_on must be a list of unique task keys")
        if not isinstance(owns, list) or not all(isinstance(x, str) and x for x in owns):
            raise TaskError("owns must be a list of relative files or directories")
        for path in owns:
            if PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts or any(c in path for c in "*?[]\\"):
                raise TaskError("owns uses literal relative paths, without parent traversal or globs")
        priority = task.get("priority", 2)
        if type(priority) is not int or not 0 <= priority <= 4:
            raise TaskError("priority must be an integer from 0 to 4")
        keyed[key] = task
    ancestors: dict[str, set[str]] = {}

    def visit(key: str, active: set[str]) -> set[str]:
        if key in active:
            raise TaskError("dependency cycle in plan")
        if key not in keyed:
            raise TaskError(f"unknown dependency: {key}")
        if key not in ancestors:
            found: set[str] = set()
            for dep in keyed[key].get("depends_on", []):
                found |= {dep} | visit(dep, active | {key})
            ancestors[key] = found
        return ancestors[key]

    for key in keyed:
        visit(key, set())
    items = list(keyed.items())
    for i, (left, a) in enumerate(items):
        for right, b in items[i + 1:]:
            overlap = any(x == y or x in y.parents or y in x.parents
                          for x in map(PurePosixPath, a.get("owns", []))
                          for y in map(PurePosixPath, b.get("owns", [])))
            if overlap and left not in ancestors[right] and right not in ancestors[left]:
                raise TaskError(f"overlapping ownership needs a dependency: {left}, {right}")
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    nodes, edges = [], []
    for key, task in keyed.items():
        token = hashlib.sha256(f"{plan_id}/{key}".encode()).hexdigest()[:16]
        nodes.append({"key": key, "id": f"{ident(prefix)}-{token}", "title": task["title"],
                      "type": "task", "description": task["description"],
                      "acceptance_criteria": task["acceptance"], "priority": task.get("priority", 2),
                      "labels": [LABEL], "metadata": {"clade_key": token,
                      "clade_plan": plan_id, "clade_plan_hash": digest,
                      "clade_owns": task.get("owns", [])}})
        edges.extend({"from_key": key, "to_key": dep, "type": "blocks"}
                     for dep in task.get("depends_on", []))
    return {"nodes": nodes, "edges": edges}, digest


def rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(x, dict) for x in value):
        raise TaskError("unexpected Beads response shape")
    return value


def show(backend: Beads, task_id: str) -> dict[str, Any]:
    found = rows(backend.run("show", ident(task_id), readonly=True))
    if len(found) != 1 or found[0].get("id") != task_id or LABEL not in found[0].get("labels", []):
        raise TaskError("expected an exact Clade task ID")
    return found[0]


def import_plan(backend: Beads, args: argparse.Namespace, actor: str) -> dict[str, Any]:
    prefix = backend.run("config", "get", "issue_prefix", readonly=True)["value"]
    plan = read_json(args.file)
    graph, digest = compile_plan(plan, prefix)
    expected = {node["key"]: node["id"] for node in graph["nodes"]}
    # A receipt shares the graph transaction and has an ID based only on the
    # plan ID. Concurrent revisions with completely different task keys must
    # conflict too; a preflight list alone cannot establish that uniqueness.
    receipt = f"{prefix}-plan-{hashlib.sha256(plan['plan_id'].encode()).hexdigest()[:16]}"
    graph["nodes"].append({"key": "_clade_plan_receipt", "id": receipt,
                          "title": f"Plan import: {plan['plan_id']}", "type": "task", "status": "closed",
                          "description": "Immutable import receipt. Closed records import, not task acceptance.",
                          "labels": [PLAN_LABEL], "metadata": {"clade_plan": plan["plan_id"],
                          "clade_plan_hash": digest}})
    if args.dry_run:
        return {"dry_run": True, "graph": graph}
    existing = rows(backend.run("list", "--all", "--limit", "0", "--label", LABEL, readonly=True))
    existing += rows(backend.run("list", "--all", "--limit", "0", "--label", PLAN_LABEL, readonly=True))
    expected_ids = set(expected.values()) | {receipt}
    matched = [row for row in existing if row["id"] in expected_ids]
    if matched:
        if {row["id"] for row in matched} == expected_ids and all(row.get("metadata", {}).get("clade_plan_hash") == digest for row in matched):
            return {"ids": expected, "already_imported": True}
        raise TaskError("plan ID already exists with different content; use a new plan ID")
    fd, path = tempfile.mkstemp(prefix="clade-plan-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(graph, stream)
        backend.run("create", "--graph", path, actor=actor)
        return {"ids": expected, "already_imported": False}
    finally:
        os.unlink(path)


def project_task(task: dict[str, Any]) -> dict[str, Any]:
    metadata = task.get("metadata", {})
    status = task["status"]
    phase = "accepted" if status == "closed" else (
        "submitted" if status == "blocked" and metadata.get("clade_submission") else status)
    submission = metadata.get("clade_submission")
    owner = submission.get("session_id") if phase in ("submitted", "accepted") and isinstance(submission, dict) else task.get("assignee")
    dependencies = None
    if isinstance(task.get("dependencies"), list):
        dependencies = []
        for dep in task["dependencies"]:
            # ready/list return edges; show returns resolved issue details.
            target = dep.get("depends_on_id", dep.get("id"))
            if not target:
                raise TaskError("dependency response is missing its target")
            dependencies.append({"task_id": target,
                                 "type": dep.get("dependency_type", dep.get("type")),
                                 "state": dep.get("status")})
    return {"task_id": task["id"], "title": task["title"], "state": phase,
            "assignee": owner, "updated_at": task.get("updated_at"),
            "heartbeat_at": task.get("heartbeat_at"), "lease_expires_at": task.get("lease_expires_at"),
            "session": metadata.get("clade_session"), "owns": metadata.get("clade_owns", []),
            "submission": metadata.get("clade_submission"),
            "dependency_count": task.get("dependency_count"),
            "dependencies": dependencies,
            "acceptance": task.get("acceptance_criteria"),
            "handoff": metadata.get("clade_handoff")}


def guarded_update(backend: Beads, task_id: str, holder: str, status: str,
                   actor: str, fields: list[str], metadata: dict[str, Any]) -> None:
    args = ["update", ident(task_id), "--if-assignee", ident(holder), "--if-status", status, *fields]
    if metadata:
        # --set-metadata parses scalar values only; --metadata merges nested
        # JSON inside the guarded transaction and preserves unrelated keys.
        args += ["--metadata", json.dumps(metadata, ensure_ascii=False)]
    backend.run(*args, actor=actor)


def dispatch(args: argparse.Namespace) -> Any:
    if args.command == "bind":
        return bind(args)
    if args.command == "session":
        return session(args)
    backend, data = binding(args.repo, args.timeout)
    if args.command in ("snapshot", "ready"):
        ready = rows(backend.run("ready", "--label", LABEL, "--unassigned", "--limit", "0", readonly=True))
        if args.command == "ready":
            return {"project_id": data["project_id"], "tasks": [project_task(x) for x in ready]}
        all_tasks = rows(backend.run("list", "--all", "--label", LABEL, "--limit", "0", readonly=True))
        return {"schema_version": "clade.task-snapshot/v1", "project_id": data["project_id"],
                "observed_at": now(), "source": "beads", "consistency": "sequential-reads",
                "ready_task_ids": [x["id"] for x in ready],
                "tasks": [project_task(x) for x in all_tasks],
                "liveness": "unknown; heartbeats are observations, not proof a process is alive"}
    if args.command == "show":
        return project_task(show(backend, args.task_id))
    if args.command == "history":
        show(backend, args.task_id)
        return backend.run("history", args.task_id, readonly=True)
    record = load_session(args.repo, args.session, data["project_id"])
    actor = record["session_id"]
    if args.command == "plan":
        return import_plan(backend, args, actor)
    task = show(backend, args.task_id)
    if args.command == "claim":
        if task.get("assignee") != actor or task["status"] != "in_progress":
            claimed = rows(backend.run("ready", "--claim", "--unassigned", "--label", LABEL,
                                      "--metadata-field", f"clade_key={task['metadata']['clade_key']}", actor=actor))
            if len(claimed) != 1 or claimed[0]["id"] != args.task_id:
                raise TaskError("task is not ready or another session holds it; no claim granted")
        guarded_update(backend, args.task_id, actor, "in_progress", actor, [], {"clade_session": record})
    elif args.command == "heartbeat":
        backend.run("heartbeat", args.task_id, actor=actor)
    elif args.command == "handoff":
        # Destination may have registered in another clone. IDs are correlation, not ACLs.
        destination = ident(args.to_session)
        if destination == actor:
            raise TaskError("handoff requires a fresh destination session")
        guarded_update(backend, args.task_id, actor, args.expected_status, actor,
                       ["--assignee", destination, "--status", "in_progress"],
                       {"clade_session": {"session_id": destination}, "clade_submission": None,
                        "clade_handoff": {"from": actor, "to": destination,
                                          "context": nonempty(args.context, "context"), "at": now()}})
    elif args.command == "submit":
        if git(args.repo, "status", "--porcelain"):
            raise TaskError("commit or preserve task work before submitting; checkout must be clean")
        head = git(args.repo, "rev-parse", "HEAD")
        if head != args.head:
            raise TaskError("submission head must match the current committed checkout")
        if args.delivery_id:
            delivery = read_json(state_dir(args.repo).parent / "deliveries" / f"{ident(args.delivery_id)}.json")
            expected_ref = {"project_id": data["project_id"], "task_id": args.task_id, "session_id": actor}
            if delivery.get("task_ref") != expected_ref or delivery.get("head_sha") != head:
                raise TaskError("delivery must link this project, task, session and committed head")
        # A unique review holder fences acceptance against an ABA race (a task
        # returned for changes and resubmitted by the same working session).
        review_token = f"review-{uuid.uuid4().hex}"
        submission = {"head_sha": head, "verification": nonempty(args.verification, "verification"),
                      "result": nonempty(args.result, "result"), "submitted_at": now(),
                      "review_token": review_token,
                      "session_id": actor, "delivery_id": ident(args.delivery_id) if args.delivery_id else None}
        guarded_update(backend, args.task_id, actor, "in_progress", actor,
                       ["--status", "blocked", "--assignee", review_token],
                       {"clade_submission": submission})
    elif args.command in ("accept", "request-changes"):
        submission = task.get("metadata", {}).get("clade_submission")
        if not isinstance(submission, dict) or submission.get("head_sha") != args.head or submission.get("session_id") != args.holder:
            raise TaskError("acceptance must name the exact submitted head")
        if actor == args.holder:
            raise TaskError("accept from a separate reviewing session or human session")
        review = {"head_sha": args.head, "review": nonempty(args.review, "review"),
                  "reviewer": actor, "reviewed_at": now()}
        if args.command == "accept":
            guarded_update(backend, args.task_id, submission["review_token"], "blocked", actor,
                           ["--status", "closed"], {"clade_acceptance": review})
        else:
            guarded_update(backend, args.task_id, submission["review_token"], "blocked", actor,
                           ["--status", "in_progress", "--assignee", ident(args.holder)],
                           {"clade_submission": None, "clade_review": review})
    return {"project_id": data["project_id"], "task": project_task(show(backend, args.task_id))}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=Path.cwd())
    p.add_argument("--timeout", type=int, default=30)
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("bind", help="bind all worktrees of this repo to an existing private Beads workspace")
    b.add_argument("--workspace", type=Path, required=True)
    b.add_argument("--project-id", required=True)
    b.add_argument("--bd", default="bd")
    b.add_argument("--credentials-file", type=Path)
    s = sub.add_parser("session", help="create a fresh session identity; retain the returned ID")
    s.add_argument("--runtime", required=True)
    s.add_argument("--parent-session")
    plan = sub.add_parser("plan", help="atomically import a dependency graph")
    plan.add_argument("--session", required=True)
    plan.add_argument("--file", type=Path, required=True)
    plan.add_argument("--dry-run", action="store_true")
    for command in ("snapshot", "ready"):
        sub.add_parser(command)
    for command in ("show", "history", "claim", "heartbeat", "handoff", "submit", "accept", "request-changes"):
        child = sub.add_parser(command)
        child.add_argument("task_id")
        if command not in ("show", "history"):
            child.add_argument("--session", required=True)
        if command == "handoff":
            child.add_argument("--to-session", required=True)
            child.add_argument("--expected-status", choices=("in_progress", "blocked"), required=True)
            child.add_argument("--context", required=True)
        if command in ("submit", "accept", "request-changes"):
            child.add_argument("--head", required=True)
        if command == "submit":
            child.add_argument("--verification", required=True)
            child.add_argument("--result", required=True)
            child.add_argument("--delivery-id")
        if command in ("accept", "request-changes"):
            child.add_argument("--holder", required=True)
            child.add_argument("--review", required=True)
    return p


def main() -> int:
    args = parser().parse_args()
    try:
        if not 1 <= args.timeout <= 300:
            raise TaskError("timeout must be between 1 and 300 seconds")
        if hasattr(args, "head") and not SHA.fullmatch(args.head):
            raise TaskError("head must be a full Git commit SHA")
        result = dispatch(args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (TaskError, OSError, KeyError, TypeError, RecursionError) as exc:
        message = str(exc) if isinstance(exc, TaskError) else "invalid task data or unavailable local state"
        print(json.dumps({"schema_version": SCHEMA, "error": message}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
