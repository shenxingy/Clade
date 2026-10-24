#!/usr/bin/env python3
"""codex_children.py — count what a headless Codex worker delegated.

Split out of ``workflow-scorecard.py`` on 2026-10-23, when that script's main
mode grew past the 1500-line cap. This half reads a different data source (the
Codex state database, not Claude Code transcripts), so it is the seam, and its
self-test came with it. The CLI is still ``workflow-scorecard.py
--codex-children``, and that script's ``--self-test`` runs this one's too, so CI
exercises it unchanged. Alone: ``python3 codex_children.py --self-test``.

Stdlib only, on purpose: the syntax-check CI job installs no dependencies.
"""

from __future__ import annotations

import datetime
import json
import os
import sqlite3
import sys
from pathlib import Path

# ─── Codex children ─────────────────────────────────────────────────────────
# A Claude agent's fan-out is in the transcripts workflow-scorecard.py reads. A
# Codex worker's is nowhere this repository could see it. Reproduced on 2026-09-05 against CLI
# 0.153.4: a headless `codex exec --json` run spawned a depth-1
# `clade_cheap_explorer` child, and the event stream carried only the `wait`
# item — with an empty `receiver_thread_ids`. The spawn itself never appears in
# the JSONL, so a supervisor watching the stream cannot know its worker fanned
# out, and every wall-clock comparison drawn between a Claude worker and a Codex
# worker was made against an unknown number of uncounted children.
#
# They are on disk. `~/.codex/state_5.sqlite` persists every spawn as a row in
# `thread_spawn_edges`, and the parent's `threads.source` says whether the run
# was headless (`exec`) or interactive (`cli`) — a subagent's own source is the
# JSON `{"subagent": {"thread_spawn": {...}}}` carrying its parent, depth and
# agent role. Read-only, stdlib `sqlite3`, no write of any kind.
#
# The one thing this must never do is answer 0 when it could not look. A missing
# database and a worker that never delegated produce the same number, and that
# confusion is the whole finding here — so an unreadable database RAISES and
# only a real read returns a count.

_CODEX_STATE_DB = "~/.codex/state_5.sqlite"

# `id` and `source` are the only two columns this needs. The rest arrived over
# the 0.1xx series, so ask the schema rather than assume it: an older or newer
# Codex should degrade to fewer details, not to an exception.
_THREAD_COLUMNS = (
    "id",
    "source",
    "cwd",
    "cli_version",
    "created_at",
    "updated_at",
    "tokens_used",
    "agent_role",
    "agent_nickname",
    "model",
)


class CodexStateUnavailable(RuntimeError):
    """The state database could not be read.

    Deliberately not degraded into an empty result: "there was nothing to read"
    and "the worker spawned nothing" are different findings and must not print
    the same number.
    """


def _open_codex_state(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise CodexStateUnavailable(f"no Codex state database at {path}")
    try:
        # mode=ro is a real read-only handle: it cannot write, and it still
        # reads a live WAL correctly. `immutable=1` would be faster and wrong —
        # Codex may be writing this file right now.
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    except sqlite3.Error as exc:
        raise CodexStateUnavailable(f"cannot read {path}: {exc}") from exc
    missing = sorted({"threads", "thread_spawn_edges"} - tables)
    if missing:
        connection.close()
        raise CodexStateUnavailable(
            f"{path} has no {', '.join(missing)} table — Codex's schema has moved"
        )
    return connection


def _spawn_meta(raw: object) -> dict:
    """The `thread_spawn` block out of a subagent thread's ``source``, or ``{}``."""

    if not isinstance(raw, str) or "{" not in raw:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    subagent = payload.get("subagent") if isinstance(payload, dict) else None
    spawn = subagent.get("thread_spawn") if isinstance(subagent, dict) else None
    return spawn if isinstance(spawn, dict) else {}


def _source_kind(raw: object) -> str:
    """``threads.source`` is a bare word for a root and JSON for a subagent."""

    if not isinstance(raw, str):
        return "unknown"
    text = raw.strip()
    if text.startswith("{"):
        return "subagent" if _spawn_meta(text) else "unknown"
    return text.strip('"').lower()


def _descend(root: str, edges: dict[str, list[str]]) -> list[tuple[str, int]]:
    """Every thread below one root, breadth-first, with cycles refused.

    Grandchildren count: a child that delegates again is still work the parent
    caused, and 12 of this host's edges have a subagent parent.
    """

    found: list[tuple[str, int]] = []
    seen = {root}
    queue = [(child, 1) for child in edges.get(root, ())]
    while queue:
        thread_id, level = queue.pop(0)
        if thread_id in seen:
            continue
        seen.add(thread_id)
        found.append((thread_id, level))
        queue.extend((grandchild, level + 1) for grandchild in edges.get(thread_id, ()))
    return found


def scan_codex_children(
    db_path: str | None = None,
    since_days: float | None = None,
    cwd_filter: str | None = None,
    parent_filter: str | None = None,
) -> dict:
    """Count the subagents each headless ``codex exec`` thread spawned.

    Raises ``CodexStateUnavailable`` rather than returning zeros when the
    database is absent, unreadable, or no longer carries these tables.
    """

    path = Path(os.path.expanduser(db_path or _CODEX_STATE_DB)).resolve()
    connection = _open_codex_state(path)
    try:
        present = {row[1] for row in connection.execute("PRAGMA table_info(threads)")}
        columns = [name for name in _THREAD_COLUMNS if name in present]
        if "id" not in columns or "source" not in columns:
            raise CodexStateUnavailable(f"{path}: threads carries no id/source column")
        threads: dict[str, dict] = {}
        for row in connection.execute(f"SELECT {', '.join(columns)} FROM threads"):
            record = dict(zip(columns, row))
            threads[record["id"]] = record
        edges: dict[str, list[str]] = {}
        for parent, child in connection.execute(
            "SELECT parent_thread_id, child_thread_id FROM thread_spawn_edges"
        ):
            edges.setdefault(parent, []).append(child)
    except sqlite3.Error as exc:
        raise CodexStateUnavailable(f"cannot read {path}: {exc}") from exc
    finally:
        connection.close()

    cutoff = None
    if since_days:
        cutoff = datetime.datetime.now().timestamp() - since_days * 86400

    roots = []
    for record in threads.values():
        if _source_kind(record.get("source")) != "exec":
            continue
        if cutoff is not None and (record.get("created_at") or 0) < cutoff:
            continue
        if cwd_filter and cwd_filter not in (record.get("cwd") or ""):
            continue
        if parent_filter and not record["id"].startswith(parent_filter):
            continue
        roots.append(record)
    roots.sort(key=lambda record: record.get("created_at") or 0)

    runs: list[dict] = []
    roles: dict[str, int] = {}
    direct_total = 0
    child_tokens = 0
    deepest = 0
    for record in roots:
        descendants = _descend(record["id"], edges)
        if not descendants:
            continue
        children: list[dict] = []
        run_tokens = 0
        for thread_id, level in descendants:
            child = threads.get(thread_id, {})
            meta = _spawn_meta(child.get("source"))
            depth = meta.get("depth")
            if not isinstance(depth, int):
                depth = level
            role = meta.get("agent_role") or child.get("agent_role") or "(unnamed)"
            tokens = child.get("tokens_used") or 0
            started = child.get("created_at") or 0
            ended = child.get("updated_at") or 0
            children.append(
                {
                    "thread": thread_id,
                    "depth": depth,
                    "role": role,
                    "nickname": meta.get("agent_nickname") or child.get("agent_nickname"),
                    "model": child.get("model"),
                    "tokens": tokens,
                    "seconds": max(0, ended - started) if started and ended else 0,
                    # An edge whose thread row is gone is still evidence a spawn
                    # happened; say so rather than dropping it.
                    "thread_row": bool(child),
                }
            )
            roles[role] = roles.get(role, 0) + 1
            run_tokens += tokens
            deepest = max(deepest, depth)
        direct = len(edges.get(record["id"], ()))
        direct_total += direct
        child_tokens += run_tokens
        runs.append(
            {
                "parent": record["id"],
                "cwd": record.get("cwd"),
                "cli_version": record.get("cli_version"),
                "model": record.get("model"),
                "parent_tokens": record.get("tokens_used") or 0,
                "started_at": record.get("created_at") or 0,
                "direct": direct,
                "descendants": len(children),
                "child_tokens": run_tokens,
                "children": children,
            }
        )

    return {
        "db": str(path),
        "exec_threads": len(roots),
        "exec_parents": len(runs),
        "direct_children": direct_total,
        "descendants": sum(run["descendants"] for run in runs),
        "child_tokens": child_tokens,
        "max_depth": deepest,
        "roles": dict(sorted(roles.items(), key=lambda pair: (-pair[1], pair[0]))),
        "runs": runs,
    }


def print_codex_children(report: dict) -> None:
    if report["runs"]:
        print(
            f"{'parent':14} {'started':17} {'cli':>8} {'kids':>5} {'sub':>4} "
            f"{'tokens':>10}  roles"
        )
    for run in report["runs"]:
        when = (
            datetime.datetime.fromtimestamp(run["started_at"]).strftime("%Y-%m-%d %H:%M")
            if run["started_at"]
            else "?"
        )
        names = sorted({child["role"] for child in run["children"]})
        print(
            f"{run['parent'][:13]:14} {when:17} {(run['cli_version'] or '?'):>8} "
            f"{run['direct']:5d} {run['descendants']:4d} {run['child_tokens']:10,d}  "
            f"{', '.join(names)}"
        )
        if run["cwd"]:
            print(f"{'':14} {run['cwd']}")
    print()
    if report["exec_parents"]:
        print(
            f"{report['exec_parents']} of {report['exec_threads']} headless "
            f"`codex exec` threads fanned out: {report['descendants']} "
            f"{'child' if report['descendants'] == 1 else 'children'} "
            f"({report['direct_children']} direct, depth {report['max_depth']}), "
            f"{report['child_tokens']:,} tokens."
        )
        print(
            "None of that is in `codex exec --json` — the spawn item never reaches "
            "the stream, so this database is the only place to count it."
        )
    else:
        print(
            f"0 of {report['exec_threads']} headless `codex exec` threads spawned a "
            f"subagent in this window. The database was read, so this is a measured "
            f"zero, not a blind one."
        )


# ─── Self-test ──────────────────────────────────────────────────────────────

def _codex_fixture(path: Path, threads: list[tuple], edges: list[tuple[str, str]]) -> None:
    """A minimal `state_5.sqlite` — the two tables and the columns this reads."""

    connection = sqlite3.connect(str(path))
    with connection:
        connection.execute(
            "CREATE TABLE threads (id TEXT PRIMARY KEY, source TEXT NOT NULL, cwd TEXT,"
            " cli_version TEXT, created_at INTEGER, updated_at INTEGER,"
            " tokens_used INTEGER, agent_role TEXT, agent_nickname TEXT, model TEXT)"
        )
        connection.execute(
            "CREATE TABLE thread_spawn_edges (parent_thread_id TEXT NOT NULL,"
            " child_thread_id TEXT PRIMARY KEY, status TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO threads (id, source, cwd, cli_version, created_at, updated_at,"
            " tokens_used, agent_role, agent_nickname, model) VALUES (?,?,?,?,?,?,?,?,?,?)",
            threads,
        )
        connection.executemany(
            "INSERT INTO thread_spawn_edges VALUES (?, ?, 'open')", edges
        )
    connection.close()


def _child_source(parent: str, depth: int, role: str) -> str:
    return json.dumps(
        {"subagent": {"thread_spawn": {
            "parent_thread_id": parent, "depth": depth,
            "agent_path": f"/root/{role}", "agent_nickname": "Volta", "agent_role": role,
        }}}
    )


def self_test_codex_children() -> int:
    """Can the Codex child counter tell a real zero from a blind one?

    The failure this guards against is the one the poll detector already shipped
    once: an instrument that cannot look reports the same 0 as a worker that
    never delegated. So there are four controls — a run that fanned out, a run
    that genuinely did not, a database that is not there, and a schema that has
    moved. The last two must refuse to answer rather than answer zero.
    """

    import tempfile

    now = int(datetime.datetime.now().timestamp())
    failures: list[str] = []

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        # Positive: one headless parent with a child and a grandchild, one
        # headless parent that spawned nothing (the denominator), and an
        # interactive parent whose child must not be counted as headless.
        hot = root / "hot.sqlite"
        _codex_fixture(
            hot,
            [
                ("p-exec", "exec", "/w/clade", "0.153.4", now - 600, now, 54856, None, None, "gpt-5.6-terra"),
                ("c1", _child_source("p-exec", 1, "clade_cheap_explorer"), "/w/clade", "0.153.4",
                 now - 500, now - 100, 55549, "clade_cheap_explorer", "Volta", "gpt-5.6-terra"),
                ("c2", _child_source("c1", 2, "clade_cheap_worker"), "/w/clade", "0.153.4",
                 now - 400, now - 200, 1000, "clade_cheap_worker", "Ampere", "gpt-5.6-luna"),
                ("p-quiet", "exec", "/w/clade", "0.153.4", now - 900, now - 800, 700, None, None, "gpt-5.6-sol"),
                ("p-cli", "cli", "/w/other", "0.153.4", now - 900, now - 800, 900, None, None, "gpt-5.6-sol"),
                ("c3", _child_source("p-cli", 1, "reviewer"), "/w/other", "0.153.4",
                 now - 880, now - 810, 4242, "reviewer", "Curie", "gpt-5.6-sol"),
            ],
            [("p-exec", "c1"), ("c1", "c2"), ("p-cli", "c3")],
        )

        # Negative: a database with only interactive work in it. Zero here is a
        # measurement, and must be reported as one.
        cold = root / "cold.sqlite"
        _codex_fixture(
            cold,
            [
                ("q-cli", "cli", "/w/clade", "0.153.4", now - 900, now - 800, 900, None, None, "gpt-5.6-sol"),
                ("q-child", _child_source("q-cli", 1, "reviewer"), "/w/clade", "0.153.4",
                 now - 880, now - 810, 4242, "reviewer", "Curie", "gpt-5.6-sol"),
            ],
            [("q-cli", "q-child")],
        )

        # Schema drift: the threads table alone. Answering 0 from this would be
        # the same lie as answering 0 from a missing file.
        partial = root / "partial.sqlite"
        connection = sqlite3.connect(str(partial))
        with connection:
            connection.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, source TEXT NOT NULL)")
        connection.close()

        try:
            fired = scan_codex_children(str(hot), since_days=None)
        except CodexStateUnavailable as exc:
            fired = None
            failures.append(f"positive control could not read its own fixture: {exc}")

        if fired is not None:
            if fired["exec_parents"] != 1:
                failures.append(f"positive control: expected 1 headless parent, got {fired['exec_parents']}")
            if fired["exec_threads"] != 2:
                failures.append(f"positive control: expected 2 headless threads, got {fired['exec_threads']}")
            if fired["direct_children"] != 1:
                failures.append(f"positive control: expected 1 direct child, got {fired['direct_children']}")
            if fired["descendants"] != 2:
                failures.append(
                    f"positive control: expected 2 descendants (the grandchild counts), "
                    f"got {fired['descendants']}"
                )
            if fired["child_tokens"] != 56549:
                failures.append(f"positive control: expected 56,549 child tokens, got {fired['child_tokens']}")
            if fired["max_depth"] != 2:
                failures.append(f"positive control: expected depth 2, got {fired['max_depth']}")
            if "clade_cheap_explorer" not in fired["roles"]:
                failures.append(f"positive control: lost the agent roles, got {fired['roles']}")
            if "reviewer" in fired["roles"]:
                failures.append("positive control: counted an interactive parent's child as headless")

        try:
            quiet = scan_codex_children(str(cold), since_days=None)
        except CodexStateUnavailable as exc:
            quiet = None
            failures.append(f"negative control refused a readable database: {exc}")

        if quiet is not None and (quiet["descendants"] or quiet["exec_parents"]):
            failures.append(
                f"negative control fired: {quiet['exec_parents']} parents, "
                f"{quiet['descendants']} children"
            )

        try:
            scan_codex_children(str(root / "absent.sqlite"), since_days=None)
        except CodexStateUnavailable:
            pass
        else:
            failures.append(
                "a missing database answered instead of refusing — its 0 would read "
                "as 'the worker never fanned out'"
            )

        try:
            scan_codex_children(str(partial), since_days=None)
        except CodexStateUnavailable:
            pass
        else:
            failures.append("a database with no thread_spawn_edges answered instead of refusing")

    if failures:
        for line in failures:
            print(f"SELF-TEST FAILED: {line}")
        return 1
    print(
        "SELF-TEST PASSED: the Codex child counter finds a headless fan-out, "
        "reports a real zero as measured, and refuses to answer when it cannot read."
    )
    return 0


if __name__ == "__main__":
    if sys.argv[1:] != ["--self-test"]:
        print("usage: codex_children.py --self-test   (the report is workflow-scorecard.py --codex-children)")
        sys.exit(2)
    sys.exit(self_test_codex_children())
