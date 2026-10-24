#!/usr/bin/env python3
"""scorecard_ledger.py — keep what workflow-scorecard.py measured, and what the owner said next.

Three modes of ``workflow-scorecard.py`` live here, all added on 2026-10-23.

``--ledger [PATH]`` appends one row per finished run to a JSONL file. The
default is ``<config dir>/workflow-scorecard/runs.jsonl``, where the config dir
is ``$CLAUDE_CONFIG_DIR`` when it is set and non-empty, and ``~/.claude``
otherwise (claude-usage-watch.py resolves it the same way). The scan reads that
config dir's own ``projects/`` as well as the default roots, so a pass never
writes into a config dir whose transcripts it skipped. Claude Code deletes
transcripts after 30 days by default (``cleanupPeriodDays``), and every figure
derived from them goes with them. By 2026-10-22 nothing on disk could reproduce
the headline figures the guidance quoted. A row is the run's scorecard row
without its per-agent detail, so its turn and token counts are per API call
(distinct message ids), not per transcript record. The rows are every run the
scan saw, whichever profile wrote it, and ``config_dir`` says which one.

The file is append-only: existing bytes are never rewritten. A row records one
END of a run, keyed by run id and ``ended_at``, and an end already in the file is
skipped. A run still in flight is not written at all. A run can end and then be
resumed under the same run id with a new task id (5 of 358 run ids on the
author's host by 2026-10-23), so an end is provisional: when the resumed run
ends again it gets a new row, and a reader takes the LAST row per run id.
``task_id`` says which launch a row's end belongs to.

``--ledger-summary [PATH]`` reads the ledger back into the figures the guidance
quotes: runs, agents and hours over the parallel runs, the serial and outlived
shares weighted by makespan, and how many runs each flag would fire on.
``--recorded-before WHEN`` keeps only rows recorded before then, so a figure
stated from the ledger on one day still comes out the same after later rows
are appended.

``--outcome`` prints, per end of each finished run, what the owner typed in the
lead session in the 6 hours after it. The output is JSONL for weekly hand
labelling: ``run_id``, ``end`` and ``ends`` (1 of 1 unless the run was resumed),
``completed_at``, ``session``, ``messages`` and ``label``, which is always null.
Nothing here labels. A run's last window opens when its last agent stopped. A
resumed run also gets a window for each earlier end: it opens when the last
agent of that launch stopped and closes at the relaunch, because the owner's
reaction to that end is what prompted the relaunch. The 2026-10-22 audit built
these windows by hand, and this reproduces its definition of an owner message.
It is a user record that is not meta, not a compact summary, not a tool result
and not injected markup (a leading ``<``, or one of the harness prefixes below),
or a queued_command attachment whose origin kind is ``human``. Pasted blocks
become ``[pasted]``. Each message is redacted through redact.py and then cut to
300 characters, in that order: cutting first can leave a token too short to
match, and keep its head. Three kinds of run are skipped and counted on stderr:
one still in flight, one whose last window has not closed, and one whose lead
transcript is gone. That last window is unknowable, which is not the same as
empty. Windows overlap when runs end close together, so one message can sit in
several runs' windows. The audit gave each message to one run by hand; deciding
which run a message answers is the labeller's job here too, so per-run counts
from this output are not comparable with the audit's.

A run has finished when its lead transcript holds a task-notification with a
terminal status for the run's LAST launch. Without one, it has finished once
nothing in its directory has changed for 24 hours, because a session killed
mid-run never sends one.

Self-test: the checks below drive workflow-scorecard.py's ``main()``, the entry
point the owner runs, under a temporary HOME. That script's ``--self-test`` runs
them. ``python3 scorecard_ledger.py --self-test`` runs that script's self-test.

Stdlib only: the syntax-check CI job installs no dependencies.
"""

from __future__ import annotations

import contextlib
import datetime
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import IO, Any, Callable, Iterator

# ─── Constants ──────────────────────────────────────────────────────────────

LEDGER_VERSION = 1
_SETTLE_QUIET_S = 24 * 3600
# The statuses Claude Code 2.1.283 documents for a task-notification are
# `completed|failed|killed|blocked`; a blocked task has not ended.
_TERMINAL = frozenset({"completed", "failed", "killed"})
OUTCOME_WINDOW_S = 6 * 3600
_MESSAGE_CHARS = 300
# Harness text that arrives as a user record: the 2026-10-22 audit's list.
_HARNESS_PREFIXES = (
    "Stop hook feedback",
    "This session is being continued",
    "Base directory for this skill",
    "[Image",
    "[Request interrupted",
    "Your response above was stopped",
    "Caveat:",
    "[Workflow harness",
)
_PASTED = re.compile(r"<pasted_content.*?(?:</pasted_content>|$)", re.S)
_TASK_ID = re.compile(r"<task-id>([^<]+)</task-id>")
_STATUS = re.compile(r"<status>([^<]+)</status>")
_WITHHELD = "<withheld: redact.py unavailable>"

Scanned = list[tuple[Path, dict[str, Any]]]


# ─── Where things live ──────────────────────────────────────────────────────


def config_dir() -> Path:
    """$CLAUDE_CONFIG_DIR when set and non-empty, else ~/.claude."""

    override = os.environ.get("CLAUDE_CONFIG_DIR", "")
    return Path(override).expanduser() if override else Path.home() / ".claude"


def default_ledger_path() -> Path:
    return config_dir() / "workflow-scorecard" / "runs.jsonl"


def lead_transcript(directory: Path) -> Path:
    """``<project>/<session>.jsonl`` for a run at ``<project>/<session>/subagents/workflows/<run>``."""

    session = directory.parents[2]
    return session.with_name(session.name + ".jsonl")


def _parse_ts(raw: object) -> datetime.datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def completed_at(row: dict[str, Any]) -> datetime.datetime:
    """When the run's last agent stopped: its first record plus its makespan."""

    started = datetime.datetime.fromisoformat(row["started_at"])
    return started + datetime.timedelta(seconds=row["makespan_s"])


# ─── The lead transcript ────────────────────────────────────────────────────


class LeadSession:
    """What one lead transcript says: each run's launches, how each task ended, and what the owner typed."""

    def __init__(self) -> None:
        # run id -> [(task id, launched at)] in transcript order. A run resumed
        # under the same run id gets a second launch with a new task id.
        self.launches: dict[str, list[tuple[str, datetime.datetime]]] = {}
        # task id -> (terminal status, at): the first terminal notification.
        self.notified: dict[str, tuple[str, datetime.datetime]] = {}
        self.typed: list[tuple[datetime.datetime, str, str]] = []  # (at, source, text)

    def final(self, run_id: str) -> tuple[str, datetime.datetime, str] | None:
        """(status, at, task id) once the run's LAST launch has ended, else None.

        A run ended by its first launch and then resumed is running again: its
        first end was provisional.
        """

        launches = self.launches.get(run_id)
        if not launches:
            return None
        task = launches[-1][0]
        if task not in self.notified:
            return None
        status, at = self.notified[task]
        return status, at, task

    def last_task(self, run_id: str) -> str | None:
        launches = self.launches.get(run_id)
        return launches[-1][0] if launches else None

    def ends(self, run_id: str) -> list[tuple[datetime.datetime, datetime.datetime | None]]:
        """(ended at, relaunched at) for each launch a terminal notification ended, in order.

        ``relaunched at`` is the next launch's time, or None for the last launch.
        """

        launches = self.launches.get(run_id, [])
        found = []
        for index, (task, _) in enumerate(launches):
            if task in self.notified:
                relaunched = launches[index + 1][1] if index + 1 < len(launches) else None
                found.append((self.notified[task][1], relaunched))
        return found


def _content(record: dict) -> tuple[str, object] | None:
    """(kind, content) for a user record or a queued_command; None for anything else.

    The one role check: an assistant record, a summary or a system record is
    never a notification and never the owner.
    """

    if record.get("type") == "attachment":
        attachment = record.get("attachment")
        if isinstance(attachment, dict) and attachment.get("type") == "queued_command":
            return "queued", attachment.get("prompt")
        return None
    message = record.get("message")
    if record.get("type") == "user" and isinstance(message, dict):
        return "user", message.get("content")
    return None


def _prose(content: object) -> str | None:
    """The text of a message, or None when it carries a tool result: the harness, not a person."""

    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    if any(isinstance(block, dict) and block.get("type") == "tool_result" for block in content):
        return None
    return "\n".join(
        block["text"] for block in content
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
    )


def _owner_message(record: dict) -> tuple[str, str] | None:
    """(source, text) when the owner typed this record, else None."""

    found = _content(record)
    if found is None:
        return None
    source, content = found
    if source == "queued":
        attachment = record["attachment"]
        origin = attachment.get("origin")
        if not isinstance(origin, dict) or origin.get("kind") != "human":
            return None
    elif record.get("isMeta") or record.get("isCompactSummary"):
        return None
    text = _prose(content)
    if text is None:
        return None
    typed = _PASTED.sub("[pasted]", text).strip()
    if not typed or typed.startswith("<") or typed.startswith(_HARNESS_PREFIXES):
        return None
    return source, typed


def read_lead(path: Path) -> LeadSession | None:
    """One pass over a lead transcript; None when it cannot be read."""

    try:
        handle = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return None
    lead = LeadSession()
    with handle:
        for line in handle:
            # Everything wanted here is a user record or a queued_command. Only
            # a speed-up: the role check is _content's.
            if '"user"' not in line and "queued_command" not in line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            at = _parse_ts(record.get("timestamp"))
            if at is None:
                continue
            launched = record.get("toolUseResult")
            if isinstance(launched, dict) and isinstance(launched.get("runId"), str):
                task = str(launched.get("taskId"))
                runs = lead.launches.setdefault(launched["runId"], [])
                if task not in (known for known, _ in runs):
                    runs.append((task, at))
                continue
            found = _content(record)
            text = _prose(found[1]) if found else None
            if text is not None and text.lstrip().startswith("<task-notification>"):
                task_id, status = _TASK_ID.search(text), _STATUS.search(text)
                if task_id and status and status.group(1) in _TERMINAL:
                    lead.notified.setdefault(task_id.group(1), (status.group(1), at))
                continue
            owner = _owner_message(record)
            if owner:
                lead.typed.append((at, owner[0], owner[1]))
    lead.typed.sort(key=lambda entry: entry[0])
    return lead


def _lead_for(directory: Path, cache: dict[Path, LeadSession | None]) -> LeadSession | None:
    path = lead_transcript(directory)
    if path not in cache:
        cache[path] = read_lead(path)
    return cache[path]


def _newest_mtime(directory: Path) -> float:
    newest = directory.stat().st_mtime
    for path in directory.iterdir():
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    return newest


def run_end(directory: Path, lead: LeadSession | None) -> tuple[str, str, str | None] | None:
    """(how, when, task id) the run ended, or None while it may still be running."""

    final = lead.final(directory.name) if lead is not None else None
    if final is not None:
        return final[0], final[1].isoformat(), final[2]
    newest = _newest_mtime(directory)
    if time.time() - newest >= _SETTLE_QUIET_S:
        task = lead.last_task(directory.name) if lead is not None else None
        return "quiet", datetime.datetime.fromtimestamp(newest, datetime.timezone.utc).isoformat(), task
    return None


# ─── Ledger ─────────────────────────────────────────────────────────────────


def ledger_row(row: dict[str, Any], directory: Path, end: tuple[str, str, str | None]) -> dict[str, Any]:
    # The per-agent rows are about a hundred times the size of the rest; the run
    # figures the guidance quotes need none of them.
    kept = {key: value for key, value in row.items() if key != "agent_rows"}
    kept.update({
        "ledger": LEDGER_VERSION,
        "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "completed_at": completed_at(row).isoformat(),
        "ended": end[0],
        "ended_at": end[1],
        "task_id": end[2],
        "config_dir": str(directory.resolve().parents[5]),
    })
    return kept


def _key(row: dict[str, Any]) -> tuple[object, object]:
    """What one row records: this run, ended at this time. A resumed run that ends again is a new row."""

    return row.get("run_id"), row.get("ended_at")


def _recorded(text: str) -> set[tuple[object, object]]:
    keys: set[tuple[object, object]] = set()
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue  # a fragment stays in the file; it just names nothing
        if isinstance(row, dict) and isinstance(row.get("run_id"), str):
            keys.add(_key(row))
    return keys


def _lock(handle: IO[str]) -> None:
    try:
        import fcntl
    except ImportError:  # no advisory lock on Windows; appends still never rewrite
        return
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def append_ledger(path: Path, rows: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Append each row whose (run id, end) the file does not hold yet. Returns (appended, already present)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    appended: list[str] = []
    skipped: list[str] = []
    # "a+" opens with O_APPEND: every write lands at the end whatever the read
    # position, so nothing here can overwrite a byte already in the file.
    with path.open("a+", encoding="utf-8") as handle:
        _lock(handle)
        handle.seek(0)
        existing = handle.read()
        present = _recorded(existing)
        batch: set[str] = set()
        lines: list[str] = []
        for row in rows:
            run_id = row["run_id"]
            # One row per run per pass: a copy under a second root is the same run.
            if run_id in batch or _key(row) in present:
                skipped.append(run_id)
                continue
            batch.add(run_id)
            lines.append(json.dumps(row, ensure_ascii=False, sort_keys=True))
            appended.append(run_id)
        if lines:
            # A write cut off mid-line leaves no newline. Start on a fresh line
            # rather than glue the first new row onto the fragment.
            fresh = "" if not existing or existing.endswith("\n") else "\n"
            handle.write(fresh + "\n".join(lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    return appended, skipped


def record_ledger(scanned: Scanned, path: Path, as_json: bool) -> int:
    leads: dict[Path, LeadSession | None] = {}
    rows: list[dict[str, Any]] = []
    in_flight: list[str] = []
    for directory, row in scanned:
        end = run_end(directory, _lead_for(directory, leads))
        if end is None:
            in_flight.append(row["run_id"])
            continue
        rows.append(ledger_row(row, directory, end))
    appended, present = append_ledger(path, rows)
    if as_json:
        json.dump({
            "ledger": str(path), "appended": appended,
            "already_present": len(present), "in_flight": in_flight,
        }, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    print(
        f"workflow-scorecard: ledger {path}: appended {len(appended)} run(s), "
        f"{len(present)} already present, {len(in_flight)} still in flight "
        f"(recorded once they end)."
    )
    return 0


# ─── Reading the ledger back ────────────────────────────────────────────────


def _rows(text: str) -> list[dict]:
    """Every row a reader can get back, line by line; a fragment yields nothing."""

    rows = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def parse_when(text: str) -> datetime.datetime:
    """An ISO date or timestamp; one without a zone is UTC."""

    when = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    return when if when.tzinfo else when.replace(tzinfo=datetime.timezone.utc)


def read_ledger(
    path: Path, recorded_before: datetime.datetime | None,
) -> tuple[list[dict[str, Any]], int] | None:
    """The last row per run id among rows recorded before the cut, and how many earlier rows it superseded.

    None when there is no ledger to read, which is not a ledger of no runs.
    """

    latest: dict[str, dict[str, Any]] = {}
    superseded = 0
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for row in _rows(text):
        run_id = row.get("run_id")
        recorded = _parse_ts(row.get("recorded_at"))
        if not isinstance(run_id, str) or recorded is None or not isinstance(row.get("makespan_s"), (int, float)):
            continue  # not a row this script wrote
        if recorded_before is not None and recorded >= recorded_before:
            continue
        # A resumed run that ended again: its later row is the run.
        superseded += run_id in latest
        latest[run_id] = row
    return list(latest.values()), superseded


def summarize(rows: list[dict[str, Any]], outlived_flag: float, util_floor: float) -> dict[str, Any]:
    """The figures the guidance quotes, over the parallel runs, weighted by makespan."""

    parallel = [row for row in rows if row.get("peak", 0) > 1]
    makespan = sum(row["makespan_s"] for row in parallel)

    def share(field: str) -> float:
        return sum(row[field] * row["makespan_s"] for row in parallel) / makespan if makespan else 0.0

    starts = sorted(row["started_at"] for row in parallel)
    return {
        "runs": len(rows),
        "parallel_runs": len(parallel),
        "sequential_runs": len(rows) - len(parallel),
        "agents": sum(row["agents"] for row in parallel),
        "hours": makespan / 3600,
        "started_first": starts[0] if starts else None,
        "started_last": starts[-1] if starts else None,
        "single_agent_share": share("serial_frac") + share("outlived_frac"),
        "serial_share": share("serial_frac"),
        "outlived_share": share("outlived_frac"),
        "outlived_flagged": sum(row["outlived_frac"] >= outlived_flag for row in parallel),
        "tail_flagged": sum(row["tail_alone"] >= outlived_flag for row in parallel),
        "low_util": sum(row["util_vs_peak"] < util_floor for row in parallel),
    }


def print_ledger_summary(
    path: Path, recorded_before: datetime.datetime | None, as_json: bool,
    outlived_flag: float, util_floor: float,
) -> int:
    found = read_ledger(path, recorded_before)
    if found is None:
        print(f"workflow-scorecard: no ledger to read at {path}. That is not 0 runs; write one with --ledger.")
        return 1
    rows, superseded = found
    figures = summarize(rows, outlived_flag, util_floor)
    figures.update({
        "ledger": str(path),
        "recorded_before": recorded_before.isoformat() if recorded_before else None,
        "superseded": superseded,
    })
    if as_json:
        json.dump(figures, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    cut = f", rows recorded before {figures['recorded_before']}" if recorded_before else ""
    print(
        f"workflow-scorecard: ledger {path}{cut}: {figures['runs']} finished run(s), "
        f"{figures['parallel_runs']} parallel and {figures['sequential_runs']} one agent at a time "
        f"({superseded} earlier row(s) superseded by a resumed run's later end)."
    )
    if not figures["parallel_runs"]:
        return 0
    n = figures["parallel_runs"]
    print(
        f"Parallel runs: {n:,} started {figures['started_first'][:10]} → {figures['started_last'][:10]} UTC; "
        f"{figures['agents']:,} agents; {figures['hours']:.1f} h of makespan."
    )
    print(
        f"One agent alone: {figures['single_agent_share'] * 100:.1f}% of that makespan = "
        f"{figures['serial_share'] * 100:.1f}% serial + {figures['outlived_share'] * 100:.1f}% outlived."
    )
    print(
        f"outlived >= {outlived_flag:.0%}: {figures['outlived_flagged']} of {n}; merged tail >= "
        f"{outlived_flag:.0%}: {figures['tail_flagged']} of {n}; util_vs_peak < {util_floor:.0%}: "
        f"{figures['low_util']} of {n}."
    )
    return 0


# ─── Outcome windows ────────────────────────────────────────────────────────


def _mask(text: str) -> str:
    try:
        from redact import redact
    except ImportError:  # installed beside this file; without it, show nothing
        return _WITHHELD
    return redact(text)[0]


def _last_stop_before(row: dict[str, Any], ended: datetime.datetime) -> datetime.datetime:
    """When the last agent that stopped by ``ended`` stopped; ``ended`` itself if none had."""

    started = datetime.datetime.fromisoformat(row["started_at"])
    stops = [
        started + datetime.timedelta(seconds=agent["start_s"] + agent["seconds"])
        for agent in row.get("agent_rows", []) if agent.get("start_s") is not None
    ]
    before = [stop for stop in stops if stop <= ended]
    return max(before) if before else ended


def windows(row: dict[str, Any], lead: LeadSession) -> list[tuple[datetime.datetime, datetime.datetime]]:
    """(opens, closes) per end of the run the owner saw.

    A run resumed under its run id ended once before each relaunch, and the
    owner's reaction to that end is what prompted the relaunch. Its window
    opens when that end's last agent stopped and closes at the relaunch, or 6 h
    later if sooner. The last window opens when the run's last agent stopped.
    """

    found = []
    for ended, relaunched in lead.ends(row["run_id"]):
        if relaunched is None:
            continue  # the last launch: its window is the run's own, below
        opens = _last_stop_before(row, ended)
        found.append((opens, min(opens + datetime.timedelta(seconds=OUTCOME_WINDOW_S), relaunched)))
    done = completed_at(row)
    found.append((done, done + datetime.timedelta(seconds=OUTCOME_WINDOW_S)))
    return found


def owner_window(lead: LeadSession, done: datetime.datetime, close: datetime.datetime) -> list[dict[str, Any]]:
    """The owner's messages in (done, close], each once, redacted and then cut."""

    seen: set[str] = set()
    messages: list[dict[str, Any]] = []
    for at, source, typed in lead.typed:
        if at <= done or at > close:
            continue
        # A message typed while the lead was busy can be written twice: as a
        # queued_command, and again as a user record once it is delivered.
        if typed in seen:
            continue
        seen.add(typed)
        messages.append({
            "at": at.isoformat(),
            "after_min": round((at - done).total_seconds() / 60, 1),
            "source": source,
            "text": _mask(typed)[:_MESSAGE_CHARS],
        })
    return messages


def emit_outcomes(scanned: Scanned) -> int:
    leads: dict[Path, LeadSession | None] = {}
    now = datetime.datetime.now(datetime.timezone.utc)
    emitted = runs = in_flight = still_open = gone = 0
    for directory, row in scanned:
        lead = _lead_for(directory, leads)
        if run_end(directory, lead) is None:
            in_flight += 1
            continue
        done = completed_at(row)
        if now < done + datetime.timedelta(seconds=OUTCOME_WINDOW_S):
            still_open += 1
            continue
        if lead is None:
            gone += 1
            continue
        found = windows(row, lead)
        for index, (opens, closes) in enumerate(found, 1):
            print(json.dumps({
                "run_id": row["run_id"],
                "end": index,
                "ends": len(found),
                "completed_at": opens.isoformat(),
                "session": row["session"],
                "messages": owner_window(lead, opens, closes),
                "label": None,
            }, ensure_ascii=False))
            emitted += 1
        runs += 1
    print(
        f"workflow-scorecard: --outcome emitted {emitted} window(s) for {runs} run(s); skipped "
        f"{in_flight} in flight, {still_open} with the 6-hour window still open, {gone} whose lead "
        f"transcript is gone (unknowable, not empty).",
        file=sys.stderr,
    )
    return 0


# ─── Self-tests ─────────────────────────────────────────────────────────────
# Both go through workflow-scorecard.py's main(), passed in as `cli` so this
# module never imports that script: HOME and CLAUDE_CONFIG_DIR point into a
# temporary directory, the fixtures are written where default_roots() looks, and
# what main() writes or prints is read back. A check that called append_ledger()
# directly would stay green with the call removed from main().

Cli = Callable[[list[str]], int]


@contextlib.contextmanager
def _environment(**values: str | None) -> Iterator[None]:
    saved = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _call(cli: Cli, argv: list[str], failures: list[str]) -> tuple[str, str]:
    """main(argv) with HOME as the working directory, so a relative path stays in it."""

    out, err = io.StringIO(), io.StringIO()
    cwd = os.getcwd()
    try:
        os.chdir(os.environ["HOME"])
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli(argv)
    except (Exception, SystemExit) as exc:  # noqa: BLE001 — a crash or an argparse refusal is a finding
        failures.append(f"{' '.join(argv)} raised {type(exc).__name__}: {exc}")
        return "", ""
    finally:
        os.chdir(cwd)
    if code != 0:
        failures.append(f"{' '.join(argv)} exited {code}")
    return out.getvalue(), err.getvalue()


def _object(text: str) -> dict:
    """The JSON object a mode printed, or {} for anything else: a table, a list, nothing."""

    try:
        found = json.loads(text)
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def _readable_ids(text: str) -> list[str]:
    """Every run id a reader can get back, duplicates kept."""

    return [str(row.get("run_id")) for row in _rows(text)]


def _age(directory: Path, hours: float) -> None:
    then = time.time() - hours * 3600
    for path in [*directory.iterdir(), directory]:
        os.utime(path, (then, then))


def _report(failures: list[str], passed: str) -> int:
    if failures:
        for line in failures:
            print(f"SELF-TEST FAILED: {line}")
        return 1
    print(f"SELF-TEST PASSED: {passed}")
    return 0


def self_test_ledger(cli: Cli) -> int:
    """Append-only, one row per run id, per API call, and never a run in flight."""

    from scorecard_fixtures import (
        RUNS, lead_launch, lead_notification, write_agent, write_lead_session, write_sweep_fixtures,
    )

    failures: list[str] = []

    def expect(label: str, actual: object, wanted: object) -> None:
        if actual != wanted:
            failures.append(f"{label}: expected {wanted!r}, got {actual!r}")

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        projects = home / ".claude" / "projects"
        write_sweep_fixtures(projects)
        runs = projects / "-fixture-project" / "fixture-session" / "subagents" / "workflows"
        lead = write_lead_session(projects, [lead_launch(run, f"task-{run}", 0) for run in RUNS] + [
            lead_notification("task-wf_barrier", "completed", 30),
            lead_notification("task-wf_fanout_build", "completed", 44),
            lead_notification("task-wf_sequential", "completed", 15, queued=True),
            lead_notification("task-wf_edge_hit", "failed", 40),
            lead_notification("task-wf_edge_miss", "completed", 50),
            # wf_queue is blocked, which is not an end, and its files are fresh.
            lead_notification("task-wf_queue", "blocked", 10),
        ])
        # The same run under a second root, copied rather than symlinked: two
        # directories, one run id, one row.
        profile = home / ".claude-profiles" / "p1"
        copy = profile / "projects" / "-fixture-project"
        shutil.copytree(runs / "wf_barrier", copy / "fixture-session" / "subagents" / "workflows" / "wf_barrier")
        shutil.copy(lead, copy / lead.name)

        # A ledger already holding wf_edge_miss's end, and a last line a crash cut short.
        ledger = profile / "workflow-scorecard" / "runs.jsonl"
        ledger.parent.mkdir(parents=True)
        seed = '{"run_id": "wf_edge_miss", "ended_at": "2026-01-01T00:50:00+00:00", "seeded": true}\n{"run_id": "wf_cut'
        ledger.write_text(seed, encoding="utf-8")
        argv = ["--ledger", "--since", "0"]

        with _environment(HOME=str(home), CLAUDE_CONFIG_DIR=str(profile)):
            _call(cli, argv, failures)
            first = ledger.read_text(encoding="utf-8")
            expect("the existing bytes are untouched", first.startswith(seed), True)
            expect(
                "every finished run once, the seeded one not again, none glued to the fragment",
                sorted(_readable_ids(first)),
                ["wf_barrier", "wf_edge_hit", "wf_edge_miss", "wf_fanout_build", "wf_sequential"],
            )
            rows = {row.get("run_id"): row for row in _rows(first[len(seed):])}
            barrier = rows.get("wf_barrier", {})
            expect("turns are API calls, not records (24 records, 12 calls)", barrier.get("turns"), 12)
            expect("no per-agent detail", "agent_rows" in barrier, False)
            expect("the barrier's straggler share", barrier.get("outlived_frac"), 5 / 30)
            expect(
                "how each run ended, from both notification shapes",
                [rows.get(run, {}).get("ended") for run in ("wf_barrier", "wf_sequential", "wf_edge_hit")],
                ["completed", "completed", "failed"],
            )
            expect("the barrier's end time", barrier.get("completed_at"), "2026-01-01T00:30:00+00:00")
            expect(
                "CLAUDE_CONFIG_DIR is honoured: nothing written under ~/.claude",
                (home / ".claude" / "workflow-scorecard").exists(), False,
            )

            _call(cli, argv, failures)
            expect("a second pass appends nothing", ledger.read_text(encoding="utf-8") == first, True)

            _age(runs / "wf_queue", 23)
            _call(cli, argv, failures)
            expect("23 h of quiet is still in flight", ledger.read_text(encoding="utf-8") == first, True)

            _age(runs / "wf_queue", 25)
            _call(cli, argv, failures)
            later = ledger.read_text(encoding="utf-8")
            expect("the file only grows", later.startswith(first), True)
            tail = _rows(later[len(first):]) if later.startswith(first) else []
            expect(
                "25 h of quiet has ended",
                [(row.get("run_id"), row.get("ended")) for row in tail], [("wf_queue", "quiet")],
            )

        with _environment(HOME=str(home), CLAUDE_CONFIG_DIR=""):
            _call(cli, argv, failures)
            default = home / ".claude" / "workflow-scorecard" / "runs.jsonl"
            text = default.read_text(encoding="utf-8") if default.exists() else ""
            expect("an empty CLAUDE_CONFIG_DIR means ~/.claude", sorted(_readable_ids(text)), sorted(RUNS))

    # A config dir outside both default roots, holding one run that is resumed
    # under its run id after it ended. The scan must read the transcripts of
    # the config dir it writes into, and the resumed run's second end must be
    # recorded: its first row was provisional.
    with tempfile.TemporaryDirectory() as tmp:
        home, config = Path(tmp) / "home", Path(tmp) / "work-claude"
        home.mkdir()
        projects = config / "projects"
        run = projects / "-fixture-project" / "resume-session" / "subagents" / "workflows" / "wf_resumed"
        run.mkdir(parents=True)
        write_agent(run, "first-a", 0, 10)
        write_agent(run, "first-b", 0, 20)
        records = [lead_launch("wf_resumed", "task-r1", 0), lead_notification("task-r1", "completed", 21)]
        write_lead_session(projects, records, session="resume-session")
        ledger = config / "workflow-scorecard" / "runs.jsonl"
        argv = ["--ledger", "--since", "0", "--json"]

        def report() -> dict:
            return _object(_call(cli, argv, failures)[0])

        with _environment(HOME=str(home), CLAUDE_CONFIG_DIR=str(config)):
            expect("a config dir outside the default roots is scanned", report().get("appended"), ["wf_resumed"])
            first = ledger.read_text(encoding="utf-8") if ledger.exists() else ""

            write_agent(run, "second", 24, 40)
            records.append(lead_launch("wf_resumed", "task-r2", 23))
            write_lead_session(projects, records, session="resume-session")
            resumed = report()
            expect(
                "a resumed run is in flight again, not ended by its first launch",
                (resumed.get("appended"), resumed.get("in_flight")), ([], ["wf_resumed"]),
            )

            records.append(lead_notification("task-r2", "completed", 41))
            write_lead_session(projects, records, session="resume-session")
            expect("the resumed run's second end is recorded", report().get("appended"), ["wf_resumed"])
            later = ledger.read_text(encoding="utf-8") if ledger.exists() else ""
            expect("the first row stays", later.startswith(first) and bool(first), True)
            expect(
                "each end's agents, end time and task",
                [(row.get("agents"), row.get("ended_at"), row.get("task_id")) for row in _rows(later)],
                [(2, "2026-01-01T00:21:00+00:00", "task-r1"), (3, "2026-01-01T00:41:00+00:00", "task-r2")],
            )
            summary = _object(_call(cli, ["--ledger-summary", "--json"], failures)[0])
            expect(
                "a reader takes the last row per run id",
                (summary.get("runs"), summary.get("agents"), summary.get("superseded")), (1, 3, 1),
            )

    return _report(
        failures,
        "the ledger appends each finished run's end once, per API call, never rewrites a "
        "byte, waits for a run in flight, records a resumed run's later end, reads the "
        "config dir it writes into, and lands there.",
    )


def self_test_summary(cli: Cli) -> int:
    """--ledger-summary: last row per run id, the recorded-before cut, makespan weighting, the flags."""

    failures: list[str] = []

    def expect(label: str, actual: object, wanted: object) -> None:
        if actual != wanted:
            failures.append(f"{label}: expected {wanted!r}, got {actual!r}")

    def row(run_id: str, recorded: str, **figures: float) -> str:
        base = {
            "run_id": run_id, "recorded_at": f"2026-01-0{recorded}T12:00:00+00:00",
            "started_at": f"2026-01-0{recorded}T00:00:00+00:00", "peak": 4,
        }
        return json.dumps({**base, **figures}) + "\n"

    # a's 1-hour row is superseded by its 2-hour row (a resumed run's later
    # end). b sits ON both 15% flags and on the 55% util floor. c ran one agent
    # at a time. d was recorded after the cut. e and f are not rows this script
    # wrote: e has no recorded_at, f no figures.
    lines = [
        row("a", "2", agents=6, makespan_s=3600, serial_frac=0.25, outlived_frac=0.20, tail_alone=0.45, util_vs_peak=0.5),
        row("b", "2", agents=5, makespan_s=1800, serial_frac=0.0, outlived_frac=0.15, tail_alone=0.15, util_vs_peak=0.55),
        row("c", "2", agents=3, makespan_s=900, peak=1, serial_frac=1.0, outlived_frac=0.0, tail_alone=1.0, util_vs_peak=1.0),
        row("a", "3", agents=9, makespan_s=7200, serial_frac=0.5, outlived_frac=0.25, tail_alone=0.75, util_vs_peak=0.4),
        row("d", "5", agents=7, makespan_s=600, serial_frac=0.0, outlived_frac=0.0, tail_alone=0.0, util_vs_peak=0.9),
        '{"run_id": "e", "seeded": true}\n',
        '{"run_id": "f", "recorded_at": "2026-01-02T00:00:00+00:00"}\n{"run_id": "wf_cut',
    ]
    with tempfile.TemporaryDirectory() as tmp:
        ledger = Path(tmp) / "runs.jsonl"
        ledger.write_text("".join(lines), encoding="utf-8")
        with _environment(HOME=tmp, CLAUDE_CONFIG_DIR=None):
            out, _ = _call(cli, ["--ledger-summary", str(ledger), "--recorded-before", "2026-01-04", "--json"], failures)
            text, _ = _call(cli, ["--ledger-summary", str(ledger), "--recorded-before", "2026-01-04"], failures)
            everything, _ = _call(cli, ["--ledger-summary", str(ledger), "--json"], failures)
            refused: list[str] = []
            _call(cli, ["--recorded-before", "2026-01-04", "--since", "0"], refused)
            absent: list[str] = []
            missing, _ = _call(cli, ["--ledger-summary", str(Path(tmp) / "absent.jsonl")], absent)
    expect(
        "no ledger is said, and fails, rather than read as 0 runs",
        (missing.startswith("workflow-scorecard: no ledger to read at"), [line[-8:] for line in absent]),
        (True, ["exited 1"]),
    )
    expect(
        "--recorded-before without --ledger-summary is refused, not ignored",
        [line.rsplit(" raised ", 1)[-1] for line in refused], ["SystemExit: 2"],
    )
    figures, every = _object(out), _object(everything)
    expect(
        "runs: a's later row, b, c; d recorded after the cut",
        (figures.get("runs"), figures.get("parallel_runs"), figures.get("sequential_runs"), figures.get("superseded")),
        (3, 2, 1, 1),
    )
    expect("agents and hours over the parallel runs only", (figures.get("agents"), figures.get("hours")), (14, 2.5))
    # Weighted by makespan: (0.5 x 7200 + 0) / 9000, and (0.25 x 7200 + 0.15 x 1800) / 9000.
    expect(
        "shares weighted by makespan",
        [round(figures.get(key, -1), 4) for key in ("serial_share", "outlived_share", "single_agent_share")],
        [0.4, 0.23, 0.63],
    )
    expect(
        "the 15% flags count a run on them, the 55% floor does not",
        (figures.get("outlived_flagged"), figures.get("tail_flagged"), figures.get("low_util")), (2, 2, 1),
    )
    expect("the start range", (figures.get("started_first"), figures.get("started_last")),
           ("2026-01-02T00:00:00+00:00", "2026-01-03T00:00:00+00:00"))
    expect("without a cut, d counts", (every.get("runs"), every.get("parallel_runs")), (4, 3))
    expect(
        "the text names the population and the split",
        [line for line in text.splitlines() if line.startswith(("Parallel runs", "One agent"))],
        [
            "Parallel runs: 2 started 2026-01-02 → 2026-01-03 UTC; 14 agents; 2.5 h of makespan.",
            "One agent alone: 63.0% of that makespan = 40.0% serial + 23.0% outlived.",
        ],
    )
    return _report(
        failures,
        "the ledger summary reads the last row per run, honours the recorded-before cut, "
        "weights by makespan, and counts the flags from their thresholds.",
    )


def self_test_outcome(cli: Cli) -> int:
    """The 6-hour window from both sides, a window per end of a resumed run, the owner-message filter, redact-then-cut."""

    from scorecard_fixtures import (
        RUNS, T0, lead_assistant, lead_launch, lead_notification, lead_queued, lead_typed,
        write_agent, write_lead_session, write_sweep_fixtures,
    )

    failures: list[str] = []

    def expect(label: str, actual: object, wanted: object) -> None:
        if actual != wanted:
            failures.append(f"{label}: expected {wanted!r}, got {actual!r}")

    end = 30  # wf_barrier's last agent stops 30 minutes in
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        projects = home / ".claude" / "projects"
        write_sweep_fixtures(projects)
        runs = projects / "-fixture-project" / "fixture-session" / "subagents" / "workflows"

        # wf_recent ended an hour ago, so its window is open. wf_orphan ended long
        # ago in a session whose lead transcript is gone.
        recent = runs / "wf_recent"
        recent.mkdir()
        minutes_now = (datetime.datetime.now(datetime.timezone.utc) - T0).total_seconds() / 60
        write_agent(recent, "solo", minutes_now - 120, minutes_now - 60)
        orphan = projects / "-fixture-project" / "orphan-session" / "subagents" / "workflows" / "wf_orphan"
        orphan.mkdir(parents=True)
        write_agent(orphan, "solo", 0, 10)
        _age(orphan, 48)

        launched = [*RUNS, "wf_recent"]
        records = [lead_launch(run, f"task-{run}", 0) for run in launched]
        records += [lead_notification(f"task-{run}", "completed", 50) for run in launched if run != "wf_queue"]
        records += [
            lead_typed(end - 1, "typed while the run was still going"),
            lead_typed(end + 1, "不对，理解错了"),
            lead_typed(end + 1.5, [
                {"type": "tool_result", "tool_use_id": "toolu_x", "content": "ok"},
                {"type": "text", "text": "a hook's note beside a tool result"},
            ]),
            lead_typed(end + 2, "# A skill body the harness injected", isMeta=True),
            lead_typed(end + 3, "<command-name>/clear</command-name>"),
            lead_queued(end + 4, "the key is sk-ant-api03-" + "A" * 45 + ", rotate it"),
            lead_queued(end + 5, "build finished on the agent side", origin="agent"),
            lead_typed(end + 6, "y" * 500),
            lead_typed(end + 7, "[Request interrupted by user]"),
            lead_typed(end + 8, '看这个 <pasted_content id="p1">\nthe pasted body\n</pasted_content> 还是打不开'),
            lead_queued(end + 9, "不对，理解错了"),
            lead_typed(end + 10, "z" * 280 + " sk-ant-api03-" + "B" * 45),
            lead_assistant(end + 11, "I will fix it"),
            lead_typed(end + 360, "exactly six hours later"),
            lead_typed(end + 361, "six hours and a minute later"),
        ]
        write_lead_session(projects, records)

        # wf_resumed, in a session of its own: its first launch ends at 21 (last
        # agent stop 20), the owner reacts at 22 and it is relaunched at 23; a
        # message at 30 is typed while it runs again; it ends at 41 (last stop
        # 40) and the owner answers at 45. Two ends, two windows.
        resumed = projects / "-fixture-project" / "resume-session" / "subagents" / "workflows" / "wf_resumed"
        resumed.mkdir(parents=True)
        write_agent(resumed, "first-a", 0, 10)
        write_agent(resumed, "first-b", 0, 20)
        write_agent(resumed, "second", 24, 40)
        write_lead_session(projects, [
            lead_launch("wf_resumed", "task-r1", 0),
            lead_notification("task-r1", "completed", 21),
            lead_typed(22, "the second half is wrong, redo it"),
            lead_launch("wf_resumed", "task-r2", 23),
            lead_typed(30, "still going?"),
            lead_notification("task-r2", "completed", 41),
            lead_typed(45, "looks right now"),
        ], session="resume-session")

        with _environment(HOME=str(home), CLAUDE_CONFIG_DIR=None):
            out, err = _call(cli, ["--outcome", "--since", "0"], failures)

    emitted: dict[tuple[object, object], dict] = {}
    for line in out.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            failures.append(f"not a JSON line: {line[:80]!r}")
            continue
        emitted[(record.get("run_id"), record.get("end"))] = record
    expect(
        "windows emitted: one per end of each finished run whose window closed and whose lead transcript is present",
        sorted(emitted, key=str),
        sorted([(run, 1) for run in ("wf_barrier", "wf_edge_hit", "wf_edge_miss", "wf_fanout_build", "wf_sequential")]
               + [("wf_resumed", 1), ("wf_resumed", 2)], key=str),
    )
    expect(
        "the skipped runs are counted, not dropped",
        err.strip(),
        "workflow-scorecard: --outcome emitted 7 window(s) for 6 run(s); skipped 1 in flight, 1 with the "
        "6-hour window still open, 1 whose lead transcript is gone (unknowable, not empty).",
    )
    expect(
        "a resumed run: a window per end, the first closed by the relaunch, each from its last agent stop",
        [
            (record.get("ends"), record.get("completed_at"), record.get("session"),
             [(m.get("after_min"), m.get("text")) for m in record.get("messages", [])])
            for record in (emitted.get(("wf_resumed", 1), {}), emitted.get(("wf_resumed", 2), {}))
        ],
        [
            (2, "2026-01-01T00:20:00+00:00", "resume-session", [(2.0, "the second half is wrong, redo it")]),
            (2, "2026-01-01T00:40:00+00:00", "resume-session", [(5.0, "looks right now")]),
        ],
    )
    barrier = emitted.get(("wf_barrier", 1), {})
    expect("fields", sorted(barrier), ["completed_at", "end", "ends", "label", "messages", "run_id", "session"])
    expect("one end", (barrier.get("end"), barrier.get("ends")), (1, 1))
    expect("unlabelled", barrier.get("label", "missing"), None)
    expect("completed_at", barrier.get("completed_at"), "2026-01-01T00:30:00+00:00")
    expect("session", barrier.get("session"), "fixture-session")
    # 300 written out, not _MESSAGE_CHARS: a check derived from the constant
    # moves with it, and a changed cut would pass.
    secret_cut = ("z" * 280 + " <redacted:anthropic_key>")[:300]
    expect(
        "the owner's messages in (end, end + 6 h], each once, redacted and then cut",
        [(m.get("after_min"), m.get("source"), m.get("text")) for m in barrier.get("messages", [])],
        [
            (1.0, "user", "不对，理解错了"),
            (4.0, "queued", "the key is <redacted:anthropic_key>, rotate it"),
            (6.0, "user", "y" * 300),
            (8.0, "user", "看这个 [pasted] 还是打不开"),
            (10.0, "user", secret_cut),
            (360.0, "user", "exactly six hours later"),
        ],
    )
    leaked = [run for run, record in emitted.items() if "api03-" in json.dumps(record)]
    expect("no key survives, whole or in part", leaked, [])
    return _report(
        failures,
        "the outcome windows hold 6 hours from both sides, give a resumed run one per "
        "end, keep only what the owner typed, redact before cutting, and count every "
        "run they skip.",
    )


if __name__ == "__main__":
    if sys.argv[1:] != ["--self-test"]:
        print("usage: scorecard_ledger.py --self-test   (the modes are workflow-scorecard.py --ledger / --outcome)")
        sys.exit(2)
    # The checks here drive workflow-scorecard.py's main(), so that script's
    # self-test is this module's too, and it imports this file from disk. Not
    # through the shared bytecode cache: a .pyc is trusted when the source's
    # size and whole-second mtime match, so two same-length edits within one
    # second (a mutation, then the restore) would run the stale one. A fresh
    # cache prefix compiles this file as it is now.
    scorecard = Path(__file__).resolve().with_name("workflow-scorecard.py")
    with tempfile.TemporaryDirectory() as cache:
        sys.exit(subprocess.call(
            [sys.executable, "-X", f"pycache_prefix={cache}", str(scorecard), "--self-test"]
        ))
