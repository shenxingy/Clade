#!/usr/bin/env python3
"""workflow-scorecard.py — measure how well a multi-agent run used its parallelism.

Why this exists
---------------
Clade already mines outcomes. ``/retro`` reads git history, ``session-scorecard.sh``
reads the corrections log, ``commit-archeology.sh`` reads commits. Nothing read
the *process*: every ``Workflow`` run writes a full per-agent transcript under

    ~/.claude*/projects/<slug>/<session>/subagents/workflows/wf_*/agent-*.jsonl

and as of 2026-09-02 not one line of code in this repository opened those files.
80 MB of them existed for this project alone, across 56 projects, and the only
way anyone learned whether a fan-out was efficient was to notice it felt slow.

What it measures, and why these five numbers
--------------------------------------------
A fan-out costs a slot for its whole makespan whether or not the slot is doing
anything, so "how many agents" is not the interesting number. These are:

``peak``       the most agents ever running at once — the parallelism actually
               reached, which is usually below the configured cap.
``mean``       average concurrency across the run, from a timeline sweep.
``util``       mean/peak. Capacity bought that was actually in use.
``tail1``      share of the makespan spent with exactly ONE agent still running.
               This is the straggler tax in its purest form: everyone else has
               finished and paid, and the run cannot end.
``straggler``  slowest/median agent duration.

The first run of this script, on the session that wrote it, found the result
that matters: a 90-agent ``pipeline()`` scored 77% utilisation with a 0% tail
despite a 6.7x straggler, while a 10-agent ``parallel()`` barrier scored 55%
with 19% of its makespan waiting on one agent. Agent count is not the problem.
Barriers are.

Reading the output
------------------
High ``tail1`` means the shape is wrong: a barrier where a pipeline would do, or
units so coarse that one of them dominates. High ``straggler`` with low
``tail1`` is fine — that is a pipeline absorbing variance, which is what it is
for. Low ``util`` with low ``tail1`` means the run never had enough queued work
to fill its slots.

Stdlib only, on purpose: the syntax-check CI job installs no dependencies.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import statistics
import sys
from pathlib import Path

# One assistant turn can carry several usage blocks; these are the fields that
# together make up what the run actually cost to read and to write.
_INPUT_FIELDS = (
    "input_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def _parse_ts(raw: str) -> datetime.datetime | None:
    if not raw:
        return None
    try:
        return datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _first_text(message: object) -> str:
    """First prose out of a transcript message, whatever shape it is in."""

    if isinstance(message, str):
        return message
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    return block["text"]
    return ""


def _identity(prompt: str) -> str:
    """A short tag for an agent, derived from its brief.

    There is no label field in the transcript — the ``label:`` a workflow script
    passes does not survive into the file — so this reads the brief. Workflow
    prompts in this repository put the distinguishing text on a line starting
    with a heading-ish marker, so prefer one of those; otherwise fall back to
    the first non-empty line.
    """

    lines = [ln.strip() for ln in prompt.splitlines() if ln.strip()]

    # A brief that names plan files is describing itself better than any prose
    # line in it does: those identifiers are what the run was actually about.
    plans = re.findall(r"/([A-Z]\d{2}|R\d{2})\.md\b", prompt)
    if plans:
        seen: list[str] = []
        for item in plans:
            if item not in seen:
                seen.append(item)
        return "plans " + ",".join(seen[:6])

    for line in lines:
        marker = re.match(r"^(?:DIMENSION|LANE)\b[: ]*(.*)", line)
        if marker:
            tail = marker.group(1).strip(" :—-")
            if tail:
                return tail[:58]

    # Otherwise the first line that says something, skipping boilerplate the
    # briefs in this repository all share.
    boilerplate = ("You are ", "READ FIRST", "STRICTLY READ-ONLY", "Do NOT", "Read ")
    for line in lines:
        if not line.startswith(boilerplate) and len(line) > 12:
            return line[:58]
    return (lines[0] if lines else "(empty brief)")[:58]


class AgentRun:
    __slots__ = ("agent_id", "start", "end", "out_tokens", "in_tokens", "turns", "tag")

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        self.start: datetime.datetime | None = None
        self.end: datetime.datetime | None = None
        self.out_tokens = 0
        self.in_tokens = 0
        self.turns = 0
        self.tag = ""

    @property
    def seconds(self) -> float:
        if not self.start or not self.end:
            return 0.0
        return (self.end - self.start).total_seconds()


def read_agent(path: Path) -> AgentRun:
    run = AgentRun(path.stem.replace("agent-", ""))
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except (ValueError, TypeError):
                continue
            stamp = _parse_ts(record.get("timestamp", ""))
            if stamp:
                run.start = stamp if run.start is None else min(run.start, stamp)
                run.end = stamp if run.end is None else max(run.end, stamp)
            if record.get("type") == "assistant":
                run.turns += 1
            message = record.get("message") or {}
            usage = message.get("usage") if isinstance(message, dict) else None
            if isinstance(usage, dict):
                run.out_tokens += usage.get("output_tokens") or 0
                for field in _INPUT_FIELDS:
                    run.in_tokens += usage.get(field) or 0
            if not run.tag and record.get("type") == "user":
                run.tag = _identity(_first_text(message))
    return run


def sweep(runs: list[AgentRun]) -> dict:
    """Timeline sweep over agent spans: peak, mean, and the single-agent tail."""

    spans = [(r.start, r.end) for r in runs if r.start and r.end]
    if not spans:
        return {}
    first = min(s for s, _ in spans)
    last = max(e for _, e in spans)
    makespan = (last - first).total_seconds()
    if makespan <= 0:
        return {}

    events: list[tuple[datetime.datetime, int]] = []
    for start, end in spans:
        events.append((start, 1))
        events.append((end, -1))
    events.sort(key=lambda pair: (pair[0], -pair[1]))

    running = 0
    peak = 0
    area = 0.0
    alone = 0.0
    previous = first
    for stamp, delta in events:
        width = (stamp - previous).total_seconds()
        area += running * width
        if running == 1:
            alone += width
        running += delta
        peak = max(peak, running)
        previous = stamp

    durations = sorted(r.seconds for r in runs if r.seconds)
    median = statistics.median(durations) if durations else 0.0
    slowest = max(durations) if durations else 0.0
    mean_conc = area / makespan
    return {
        "agents": len(spans),
        "makespan_s": makespan,
        "peak": peak,
        "mean_concurrency": mean_conc,
        "utilisation": (mean_conc / peak) if peak else 0.0,
        "tail_alone": alone / makespan,
        "straggler": (slowest / median) if median else 0.0,
        "median_s": median,
        "slowest_s": slowest,
        "started_at": first.isoformat(),
    }


def scan_workflow(directory: Path) -> dict | None:
    runs = [read_agent(p) for p in sorted(directory.glob("agent-*.jsonl"))]
    runs = [r for r in runs if r.start]
    if not runs:
        return None
    stats = sweep(runs)
    if not stats:
        return None
    slowest = max(runs, key=lambda r: r.seconds)
    stats.update(
        {
            "sequential": stats["peak"] <= 1,
            "run_id": directory.name,
            "out_tokens": sum(r.out_tokens for r in runs),
            "in_tokens": sum(r.in_tokens for r in runs),
            "turns": sum(r.turns for r in runs),
            "slowest_tag": slowest.tag,
            "slowest_agent": slowest.agent_id,
        }
    )
    return stats


def find_workflow_dirs(roots: list[Path], since_days: float | None) -> list[Path]:
    """Every workflow run in the window, each one once.

    ``sync-link-projects.sh`` symlinks ``~/.claude/projects`` and the per-profile
    projects directory at the same transcripts, so scanning both roots naively
    reports every run twice. Deduplicate on the resolved path rather than on the
    run id: two genuinely different sessions can hold runs with the same id
    prefix, and the resolved path is the only thing that identifies one run.
    """

    found: dict[Path, Path] = {}
    cutoff = None
    if since_days is not None:
        cutoff = datetime.datetime.now().timestamp() - since_days * 86400
    for root in roots:
        if not root.exists():
            continue
        for path in root.glob("*/*/subagents/workflows/wf_*"):
            if not path.is_dir():
                continue
            if cutoff is not None and path.stat().st_mtime < cutoff:
                continue
            found.setdefault(path.resolve(), path)
    return sorted(found.values(), key=lambda p: p.stat().st_mtime)


def default_roots() -> list[Path]:
    home = Path.home()
    roots = [home / ".claude" / "projects"]
    profiles = home / ".claude-profiles"
    if profiles.is_dir():
        roots.extend(sorted(p / "projects" for p in profiles.iterdir() if p.is_dir()))
    return roots


# ─── Polling ────────────────────────────────────────────────────────────────
# The polling rule — start one Monitor, then yield, rather than re-running a
# status command until something changes — lived only as prose in the global
# instructions. Nothing enforced it and nothing counted violations, which is the
# same shape as every gate this audit found broken. Measured on the session that
# wrote this code: 81 of 321 Bash calls were pure status reads against work
# already running, against 3 Monitor calls. A quarter of the shell budget spent
# asking "is it done yet".
#
# A poll is a Bash call that (a) only reads status and (b) is not the first of
# its kind. The repetition is what makes it a poll: checking once is a check.

_POLL_SHAPES = (
    re.compile(r"^\s*gh\s+(pr|run)\s+(checks|view|list|watch)\b"),
    re.compile(r"^\s*git\s+(status|log)\b"),
    re.compile(r"^\s*(tail|head|cat|wc)\b[^|;&]*\.(out|output|log|jsonl)\b"),
    re.compile(r"^\s*(ps|pgrep)\b"),
    re.compile(r"^\s*sleep\b"),
    re.compile(r"^\s*(ls|stat)\b[^|;&]*$"),
)
# A command that changes anything is never a poll, however it starts.
#
# The redirect clause used to be a bare `>>?[^&]`, which matched the `>/` of
# `2>/dev/null` — so every status command that silenced stderr was classified as
# mutating and the poll count came out 0 on every session ever recorded. An
# instrument that cannot fire reports a clean run exactly like a clean run does,
# which is why `--self-test` below exists and why CI runs it.
_MUTATES = re.compile(
    r"\b(rm|mv|cp|mkdir|touch|tee|install|npm|pip|pytest|committer)\b"
    r"|\bsed\s+-i\b"
    r"|\bgit\s+(push|commit|add|reset|checkout|merge|rebase)\b"
    r"|(?<![0-9&])>>?\s*(?!/dev/null)\S"
)


def _is_poll_shape(command: str) -> bool:
    if _MUTATES.search(command):
        return False
    return any(shape.search(command) for shape in _POLL_SHAPES)


def scan_session_polls(transcript: Path) -> dict | None:
    """Count repeated status reads against the background work in one session."""
    bash_calls = 0
    poll_candidates: list[str] = []
    monitors = 0
    background = 0
    agents = 0

    try:
        lines = transcript.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    for line in lines:
        try:
            record = json.loads(line)
        except (ValueError, TypeError):
            continue
        content = (record.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name")
            payload = block.get("input") or {}
            if name == "Monitor":
                monitors += 1
            elif name in ("Agent", "Task", "Workflow"):
                agents += 1
            elif name == "Bash":
                bash_calls += 1
                if payload.get("run_in_background"):
                    background += 1
                    continue
                command = str(payload.get("command") or "")
                if _is_poll_shape(command):
                    poll_candidates.append(command.strip()[:80])

    # Only repeats count. The first `gh pr checks` is a check; the fourth is a poll.
    seen: dict[str, int] = {}
    polls = 0
    for command in poll_candidates:
        key = re.sub(r"\s+", " ", command)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            polls += 1

    jobs = monitors + background + agents
    return {
        "session": transcript.stem,
        "bash_calls": bash_calls,
        "poll_shaped": len(poll_candidates),
        "polls": polls,
        "poll_share": (polls / bash_calls) if bash_calls else 0.0,
        "monitors": monitors,
        "background": background,
        "agents": agents,
        "jobs": jobs,
        "polls_per_job": (polls / jobs) if jobs else float(polls),
    }


def find_transcripts(roots: list[Path], since_days: float | None) -> list[Path]:
    found: dict[Path, Path] = {}
    cutoff = None
    if since_days is not None:
        cutoff = datetime.datetime.now().timestamp() - since_days * 86400
    for root in roots:
        if not root.exists():
            continue
        for path in root.glob("*/*.jsonl"):
            if cutoff is not None and path.stat().st_mtime < cutoff:
                continue
            found.setdefault(path.resolve(), path)
    return sorted(found.values(), key=lambda p: p.stat().st_mtime)


def self_test_polls() -> int:
    """Can the poll detector still go red?

    A detector that cannot fire reports a disciplined session exactly like an
    undisciplined one — and this one shipped that failure: `2>/dev/null` matched
    the mutation guard, so every session ever scanned reported zero polls. One
    positive and one negative control, the same shape red-phase-audit.py uses.
    """
    import tempfile

    def _session(commands: list[str], monitors: int = 0) -> list[str]:
        rows = []
        for command in commands:
            rows.append(json.dumps({"message": {"content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": command}}
            ]}}))
        for _ in range(monitors):
            rows.append(json.dumps({"message": {"content": [
                {"type": "tool_use", "name": "Monitor", "input": {}}
            ]}}))
        return rows

    polling = _session([
        "gh pr checks 90 2>/dev/null",
        "gh pr checks 90 2>/dev/null",
        "gh pr checks 90 2>/dev/null",
        "tail -5 /tmp/run.output 2>/dev/null",
        "tail -5 /tmp/run.output 2>/dev/null",
        "sleep 30",
        "sleep 30",
    ], monitors=0)
    disciplined = _session([
        "gh pr checks 90 2>/dev/null",
        "committer 'fix: x' a.py",
        "python3 -m pytest tests/ -q",
        "npm ci",
    ], monitors=1)

    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        hot = root / "hot.jsonl"
        hot.write_text("\n".join(polling) + "\n", encoding="utf-8")
        cold = root / "cold.jsonl"
        cold.write_text("\n".join(disciplined) + "\n", encoding="utf-8")

        fired = scan_session_polls(hot)
        quiet = scan_session_polls(cold)

    if not fired or fired["polls"] < 4:
        failures.append(
            f"positive control did not fire: expected >=4 polls, got "
            f"{fired['polls'] if fired else 'nothing'}"
        )
    if not quiet or quiet["polls"] != 0:
        failures.append(
            f"negative control fired: expected 0 polls, got "
            f"{quiet['polls'] if quiet else 'nothing'}"
        )
    if quiet and quiet["bash_calls"] != 4:
        failures.append(f"negative control miscounted bash calls: {quiet['bash_calls']}")

    if failures:
        for line in failures:
            print(f"SELF-TEST FAILED: {line}")
        return 1
    print(
        "SELF-TEST PASSED: the poll detector fires on repeated status reads "
        "and stays quiet on real work."
    )
    return 0


def _poll_verdict(stats: dict) -> str:
    if stats["jobs"] == 0:
        return "no background work — nothing to poll"
    if stats["polls_per_job"] >= 5:
        return "polling instead of yielding — one Monitor replaces all of these"
    if stats["monitors"] == 0 and stats["polls"] > 0:
        return "polled without ever starting a Monitor"
    if stats["poll_share"] >= 0.15:
        return "a sixth of the shell budget spent asking whether it is done"
    return "yielded"


def _verdict(stats: dict) -> str:
    """One phrase naming the dominant inefficiency, or none.

    A run that never had two agents in flight is not a straggler problem — its
    tail is 100% by construction, because one agent alone IS the whole run.
    Counting those as tails inflates the aggregate badly: they were 4 of the 5
    worst-looking runs the first time this was measured.
    """

    if stats["peak"] <= 1:
        return "sequential — one agent at a time, no parallelism to waste"
    if stats["tail_alone"] >= 0.15:
        return "straggler tail — a barrier where a pipeline would do, or units too coarse"
    if stats["utilisation"] < 0.55:
        return "slots idle — not enough queued work to keep them full"
    if stats["straggler"] >= 4 and stats["tail_alone"] < 0.05:
        return "wide spread, absorbed — this is what a pipeline is for"
    return "packed"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure parallel efficiency of past Workflow runs.",
        epilog="With no arguments, scans every profile for runs in the last 7 days.",
    )
    parser.add_argument("--project", help="Substring of the project slug to filter on.")
    parser.add_argument("--session", help="Session id (or a prefix) to filter on.")
    parser.add_argument("--since", type=float, default=7.0, help="Days back (default 7; 0 = all).")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")
    parser.add_argument("--root", action="append", help="Extra projects/ root to scan.")
    parser.add_argument(
        "--polls",
        action="store_true",
        help="Report status-polling per background job from lead-session transcripts.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Ask the poll detector whether it can still go red.",
    )
    args = parser.parse_args()

    if args.self_test:
        return self_test_polls()

    roots = default_roots()
    if args.root:
        roots.extend(Path(os.path.expanduser(r)) for r in args.root)

    window = None if args.since == 0 else args.since

    if args.polls:
        transcripts = find_transcripts(roots, window)
        if args.project:
            transcripts = [t for t in transcripts if args.project in str(t)]
        if args.session:
            transcripts = [t for t in transcripts if args.session in t.stem]
        poll_rows = [r for r in (scan_session_polls(t) for t in transcripts) if r]
        poll_rows = [r for r in poll_rows if r["bash_calls"]]
        if args.json:
            json.dump(poll_rows, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0
        if not poll_rows:
            print("workflow-scorecard: no sessions with tool calls in the window.")
            return 0
        print(
            f"{'session':10} {'bash':>5} {'polls':>6} {'share':>6} "
            f"{'jobs':>5} {'mon':>4} {'per job':>8}"
        )
        for row in sorted(poll_rows, key=lambda r: -r["polls_per_job"]):
            print(
                f"{row['session'][:10]:10} {row['bash_calls']:5d} {row['polls']:6d} "
                f"{row['poll_share'] * 100:5.0f}% {row['jobs']:5d} "
                f"{row['monitors']:4d} {row['polls_per_job']:7.1f}"
            )
            print(f"{'':10} {_poll_verdict(row)}")
        return 0

    directories = find_workflow_dirs(roots, window)
    if args.project:
        directories = [d for d in directories if args.project in str(d)]
    if args.session:
        directories = [d for d in directories if args.session in str(d)]

    rows = []
    for directory in directories:
        stats = scan_workflow(directory)
        if stats:
            stats["project"] = directory.parts[-5]
            stats["session"] = directory.parts[-4]
            rows.append(stats)

    if args.json:
        json.dump(rows, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if not rows:
        print("workflow-scorecard: no Workflow runs found in the window.")
        print("Widen it with --since 0, or point at a root with --root.")
        return 0

    print(
        f"{'run':16} {'n':>4} {'makespan':>9} {'peak':>5} {'mean':>5} "
        f"{'util':>5} {'tail1':>6} {'strag':>6} {'out tok':>9}"
    )
    for row in rows:
        print(
            f"{row['run_id'][:16]:16} {row['agents']:4d} "
            f"{row['makespan_s'] / 60:8.1f}m {row['peak']:5d} "
            f"{row['mean_concurrency']:5.1f} {row['utilisation'] * 100:4.0f}% "
            f"{row['tail_alone'] * 100:5.0f}% {row['straggler']:5.1f}x "
            f"{row['out_tokens']:9,d}"
        )
        print(f"{'':16} {_verdict(row)}")
        if row["tail_alone"] >= 0.15:
            print(
                f"{'':16} slowest: {row['slowest_s'] / 60:.1f}m vs "
                f"{row['median_s'] / 60:.1f}m median — {row['slowest_tag']}"
            )

    # Rank by minutes lost, not by the largest fraction: 19% of 20 minutes is a
    # worse run than 21% of 10, and the fraction alone inverts that.
    parallel_rows = [r for r in rows if r["peak"] > 1]
    if not parallel_rows:
        return 0
    worst = max(parallel_rows, key=lambda r: r["makespan_s"] * r["tail_alone"])
    if worst["tail_alone"] >= 0.15:
        recovered = worst["makespan_s"] * worst["tail_alone"] / 60
        print()
        print(
            f"Largest tail: {worst['run_id']} spent {worst['tail_alone'] * 100:.0f}% of "
            f"{worst['makespan_s'] / 60:.1f}m waiting on one agent "
            f"(~{recovered:.0f} min of wall clock)."
        )
        print("Split that unit, or move the stage into a pipeline() so freed slots refill.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
