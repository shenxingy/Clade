#!/usr/bin/env python3
"""
mainline-ci.py — the post-merge runner: test every new main tree, find the merge that broke it.

The other half of "Merge, then test: no queue, no re-gate" (configs/CLAUDE.md).
PRs merge on the gate of their own head (land-pr.py) without re-gating when main
moves, so main can carry a combination no presubmit ran. This runner closes
that: each tick tests the default branch's tree once, and a red tree is traced
to the first-parent merge that turned it red, so the fix goes forward.

Usage
-----
    mainline-ci.py tick   [--repo .] [--gate CMD] [--max-probes 6] [--blockers FILE]
    mainline-ci.py status [--repo .] [--fresh-hours 36] [--json]
    mainline-ci.py --self-test

One tick:
  1. Takes <state>/lock; another run holding it exits 75 (EX_TEMPFAIL), which a
     timer reads as "next tick". <state> defaults to <git common dir>/clade-mainline.
  2. Fetches the default branch. Its tree equal to the newest record's: exit 0,
     nothing run. A red tree is tested once, not every tick.
  3. Runs the gate (default `python3 <this dir>/ci-local.py --json`) in the
     dedicated worktree <state>/worktree, reset to that commit and cleaned.
     Green is exit 0 and, when the output is ci-local JSON, a verdict other than
     fail or none (nothing ran is not green).
  4. Red: runs it once more. Green then: `flaky`, exit 3, no bisect: a failure
     nobody explained, never a culprit.
  5. Still red: bisects the first-parent commits after the newest green record
     (the merges, never a side branch's own commits), at most --max-probes gate
     runs (log2 n are needed), and writes red/<sha8>.json naming the culprit, or
     `unbisected` with the reason: no green record, a green record that is not
     an ancestor, or the probe budget spent. Rewritten after every probe, so a
     killed run leaves its evidence. With --blockers, appends one line there.
     Exit 1.
Each tick appends its record to history.jsonl and replaces latest.json
atomically: {kind, head, tree, status, exit, summary, started, ended, seconds, log}.

`status` answers the question a narrowed presubmit asks: was main green
recently? It exits 0 when a green record is younger than --fresh-hours, falling
back through history past a red or flaky latest, and 1 otherwise. A red main
does not stop PRs from landing while that window holds; it stops narrowing
when the window closes.

Exit codes: 0 green or nothing to do, 1 red, 3 flaky, 4 git failed, 75 locked.
A timer example: configs/templates/mainline-ci.{service,timer}.example.

POSIX only (fcntl). Stdlib only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import math
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import IO, Any

EXIT_RED = 1
EXIT_FLAKY = 3
EXIT_GIT = 4
EXIT_LOCKED = 75
DEFAULT_GATE = f"{shlex.quote(sys.executable)} {shlex.quote(str(Path(__file__).resolve().with_name('ci-local.py')))} --json"


class GitError(Exception):
    pass


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def git(repo: Path, *args: str, check: bool = True) -> str:
    out = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, timeout=600)
    if check and out.returncode != 0:
        raise GitError(f"git {' '.join(args[:3])}: {out.stderr.strip()[-400:]}")
    return out.stdout.strip() if out.returncode == 0 else ""


# ─── Records ─────────────────────────────────────────────────────────────────

def read_history(state: Path) -> list[dict[str, Any]]:
    path = state / "history.jsonl"
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def newest_green(history: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in reversed(history):
        if row.get("status") == "green":
            return row
    return None


def write_atomic(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def append_record(state: Path, record: dict[str, Any]) -> None:
    with (state / "history.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    write_atomic(state / "latest.json", record)


def take_lock(state: Path) -> IO[str] | None:
    fh = (state / "lock").open("a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        return None
    return fh


# ─── One gate run ────────────────────────────────────────────────────────────

def summarize(output: str) -> tuple[str, str | None]:
    """(one-line summary, ci-local verdict when the output is its JSON)."""
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict) and isinstance(data.get("verdict"), str):
        verdict = data["verdict"]
        failed = ", ".join(f"{f.get('job')} > {f.get('step')}" for f in data.get("failed") or [])
        return (f"ci-local verdict {verdict}" + (f": {failed}" if failed else ""))[:300], verdict
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    return (lines[-1] if lines else "(no output)")[:300], None


def run_gate(repo: Path, state: Path, sha: str, gate: str, timeout: int, role: str) -> dict[str, Any]:
    """Check sha out in the dedicated worktree, clean it, and run the gate there."""
    wt = state / "worktree"
    git(repo, "worktree", "prune")
    if (wt / ".git").exists():
        git(wt, "checkout", "-q", "--detach", "--force", sha)
        git(wt, "clean", "-qffdx")
    else:
        git(repo, "worktree", "add", "-q", "--detach", "--force", str(wt), sha)
    logs = state / "logs"
    logs.mkdir(exist_ok=True)
    log = logs / f"{sha[:8]}-{role}.log"
    started = time.monotonic()
    env = {**os.environ, "MAINLINE_CI_SHA": sha, "MAINLINE_CI_ROLE": role}
    try:
        out = subprocess.run(["bash", "-c", gate], cwd=str(wt), env=env, capture_output=True,
                             text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        code, stdout, stderr = out.returncode, out.stdout, out.stderr
    except subprocess.TimeoutExpired as exc:
        code = 124
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = f"timed out after {timeout} s"
    log.write_text(stdout + ("\n--- stderr ---\n" + stderr if stderr else ""), encoding="utf-8")
    summary, verdict = summarize(stdout)
    if code == 124 and stderr.startswith("timed out"):
        summary = stderr
    if code != 0 or verdict in ("fail", "none"):
        status = "red"
    elif verdict == "flaky":
        status = "flaky"
    else:
        status = "green"
    return {"sha": sha, "exit": code, "status": status, "summary": summary,
            "seconds": round(time.monotonic() - started, 1), "log": str(log)}


# ─── The culprit ─────────────────────────────────────────────────────────────

def subject(repo: Path, sha: str) -> str:
    return git(repo, "log", "-1", "--format=%s", sha, check=False)


def bisect(repo: Path, state: Path, red: dict[str, Any], last_green: dict[str, Any] | None,
           args: argparse.Namespace) -> dict[str, Any]:
    head = red["head"]
    out: dict[str, Any] = {"head": head, "tree": red["tree"], "classification": "running", "reason": "",
                           "last_green": last_green.get("head") if last_green else None,
                           "culprit": None, "probes": [], "started": now()}
    path = state / "red" / f"{head[:8]}.json"
    path.parent.mkdir(exist_ok=True)

    def finish(classification: str, reason: str) -> dict[str, Any]:
        out.update(classification=classification, reason=reason, ended=now())
        write_atomic(path, out)
        return out

    if last_green is None:
        return finish("unbisected", "no green record in history to bisect from")
    good = str(last_green.get("head"))
    if subprocess.run(["git", "merge-base", "--is-ancestor", good, head], cwd=str(repo)).returncode != 0:
        return finish("unbisected", f"the last green {good[:12]} is not an ancestor of {head[:12]} (history rewritten?)")
    commits = git(repo, "rev-list", "--first-parent", "--reverse", f"{good}..{head}").split()
    out["candidates"] = len(commits)
    out["needed_probes"] = math.ceil(math.log2(len(commits))) if commits else 0
    lo, hi = -1, len(commits) - 1  # commits[lo] (or the last green) passes, commits[hi] fails
    while hi - lo > 1 and len(out["probes"]) < args.max_probes:
        mid = (lo + hi) // 2
        probe = run_gate(repo, state, commits[mid], args.gate, args.timeout, "probe")
        out["probes"].append({k: probe[k] for k in ("sha", "exit", "status", "seconds", "log")})
        write_atomic(path, out)
        if probe["status"] == "green":
            lo = mid
        else:
            hi = mid
    out["range"] = [commits[lo] if lo >= 0 else good, commits[hi]] if commits else [good, head]
    if commits and hi - lo == 1:
        out["culprit"] = {"sha": commits[hi], "subject": subject(repo, commits[hi])}
        return finish("culprit", f"first red first-parent commit after {good[:12]}")
    return finish("unbisected", f"probe budget of {args.max_probes} spent with {hi - lo} commits left "
                                f"between {out['range'][0][:12]} and {out['range'][1][:12]}")


def note_blocker(path: Path, red: dict[str, Any], culprit: dict[str, Any], record: Path) -> None:
    who = culprit.get("culprit") or {}
    what = (f"culprit {who['sha'][:12]} {who.get('subject', '')}" if who
            else f"unbisected: {culprit.get('reason')}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n## Blocker {now()}\nmain is red at {red['head'][:12]} ({red['summary']}); {what}. "
                 f"Fix forward. Record: {record}\n")


# ─── Commands ────────────────────────────────────────────────────────────────

def state_dir(repo: Path, explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
    else:
        path = Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "clade-mainline"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_branch(repo: Path, remote: str) -> str:
    ref = git(repo, "symbolic-ref", "-q", "--short", f"refs/remotes/{remote}/HEAD", check=False)
    return ref.split("/", 1)[1] if "/" in ref else "main"


def cmd_tick(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    state = state_dir(repo, args.state_dir)
    lock = take_lock(state)
    if lock is None:
        print("mainline-ci: another run holds the lock; the next tick asks again")
        return EXIT_LOCKED
    try:
        branch = args.branch or default_branch(repo, args.remote)
        git(repo, "fetch", "-q", args.remote, f"+refs/heads/{branch}:refs/remotes/{args.remote}/{branch}")
        sha = git(repo, "rev-parse", f"{args.remote}/{branch}^{{commit}}")
        tree = git(repo, "rev-parse", f"{sha}^{{tree}}")
        history = read_history(state)
        newest = history[-1] if history else None
        if newest and newest.get("tree") == tree:
            print(f"mainline-ci: tree of {sha[:12]} already tested ({newest.get('status')} at "
                  f"{str(newest.get('head'))[:12]}); nothing to run")
            return 0
        started = now()
        result = run_gate(repo, state, sha, args.gate, args.timeout, "head")
        record: dict[str, Any] = {"kind": "mainline", "head": sha, "tree": tree, "branch": branch,
                                  "status": result["status"], "exit": result["exit"], "summary": result["summary"],
                                  "started": started, "ended": now(), "seconds": result["seconds"],
                                  "log": result["log"]}
        if result["status"] == "red" and not args.no_rerun:
            rerun = run_gate(repo, state, sha, args.gate, args.timeout, "rerun")
            record["rerun"] = {k: rerun[k] for k in ("exit", "status", "summary", "log")}
            if rerun["status"] == "green":
                record["status"] = "flaky"
        record["ended"] = now()
        append_record(state, record)
        print(f"mainline-ci: {sha[:12]} {record['status']}: {record['summary']}")
        if record["status"] == "green":
            return 0
        if record["status"] == "flaky":
            print("mainline-ci: red, then green on the rerun: flaky, not green; no bisect")
            return EXIT_FLAKY
        culprit = bisect(repo, state, record, newest_green(history), args)
        red_path = state / "red" / f"{sha[:8]}.json"
        found = culprit.get("culprit")
        print(f"mainline-ci: {culprit['classification']}: "
              + (f"{found['sha'][:12]} {found['subject']}" if found else culprit["reason"])
              + f" ({len(culprit['probes'])} probe(s)); {red_path}")
        if args.blockers:
            note_blocker(Path(args.blockers), record, culprit, red_path)
        return EXIT_RED
    except GitError as exc:
        print(f"mainline-ci: {exc}", file=sys.stderr)
        return EXIT_GIT
    finally:
        lock.close()


def age_hours(stamp: str | None) -> float | None:
    try:
        when = dt.datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None
    return (dt.datetime.now(dt.timezone.utc) - when).total_seconds() / 3600


def cmd_status(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    history = read_history(state_dir(repo, args.state_dir))
    latest = history[-1] if history else None
    green = newest_green(history)
    age = age_hours(green.get("ended")) if green else None
    fresh = age is not None and age <= args.fresh_hours
    report = {
        "fresh": fresh, "fresh_hours": args.fresh_hours,
        "latest": {k: latest.get(k) for k in ("head", "status", "ended")} if latest else None,
        "green": {k: green.get(k) for k in ("head", "ended")} if green else None,
        "green_age_hours": round(age, 2) if age is not None else None,
        "fell_back": bool(latest and green and latest is not green),
    }
    if args.json:
        print(json.dumps(report))
    elif not history:
        print("mainline-ci: no record; main has never been tested here")
    elif green is None:
        print(f"mainline-ci: STALE: no green record (latest {latest and latest.get('status')})")
    else:
        lead = "FRESH" if fresh else "STALE"
        note = (f"; latest is {latest.get('status')} at {str(latest.get('head'))[:12]}, so this is the newest green"
                if report["fell_back"] and latest else "")
        age_text = f"{age:.1f} h" if age is not None else "an unreadable time"
        print(f"mainline-ci: {lead}: main green at {str(green.get('head'))[:12]} {age_text} ago "
              f"(window {args.fresh_hours:g} h){note}")
    return 0 if fresh else 1


def self_test() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import merge_then_test_cases as cases

    return cases.run_all(cases.MAINLINE_CASES, Path(__file__).resolve())


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["--self-test"]:
        return self_test()
    ap = argparse.ArgumentParser(description="Post-merge runner: test each new main tree, bisect a red one.",
                                 epilog="Exit: 0 green/nothing to do, 1 red, 3 flaky, 4 git failed, 75 locked.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("tick", "status"):
        p = sub.add_parser(name)
        p.add_argument("--repo", default=".", help="a checkout of the repository (default: cwd)")
        p.add_argument("--state-dir", help="records and worktree (default <git common dir>/clade-mainline)")
    tick = sub.choices["tick"]
    tick.add_argument("--remote", default="origin")
    tick.add_argument("--branch", help="default: <remote>/HEAD, else main")
    tick.add_argument("--gate", default=os.environ.get("MAINLINE_CI_GATE", DEFAULT_GATE),
                      help="shell command run in the worktree (default: ci-local.py --json; env MAINLINE_CI_GATE)")
    tick.add_argument("--timeout", type=int, default=3 * 3600, help="seconds per gate run (default 10800)")
    tick.add_argument("--max-probes", type=int, default=6, help="gate runs the bisect may spend (default 6: 64 merges)")
    tick.add_argument("--no-rerun", action="store_true", help="a red run is red at once; no flaky check")
    tick.add_argument("--blockers", help="append one line per red tree to this file (e.g. .claude/blockers.md)")
    status = sub.choices["status"]
    status.add_argument("--fresh-hours", type=float, default=36.0, help="green within this window (default 36)")
    status.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    return cmd_tick(args) if args.cmd == "tick" else cmd_status(args)


if __name__ == "__main__":
    sys.exit(main())
