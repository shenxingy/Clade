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
    args = parser.parse_args()

    roots = default_roots()
    if args.root:
        roots.extend(Path(os.path.expanduser(r)) for r in args.root)

    directories = find_workflow_dirs(roots, None if args.since == 0 else args.since)
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
