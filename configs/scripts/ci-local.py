#!/usr/bin/env python3
"""
ci-local.py — run this repository's GitHub Actions gates on the machine you own.

Why
---
Hosted CI minutes are billed per job, rounded UP to the minute, per job, and
multiplied by platform: Linux 1x, Windows 2x, macOS 10x. A four-job workflow
whose jobs take 24s, 39s, 60s and 73s bills **four minutes**, not three. Push
fifty times in a day and that is 200 minutes for work a 32-core machine sitting
idle on the same desk would have done in ninety seconds.

The saving is only real on PRIVATE repositories — public repos get standard
runners free — but the *latency* saving is real everywhere: a local run answers
in seconds and does not need a push to start.

Why derive instead of duplicate
-------------------------------
This repository already had a hand-written "run these before committing"
checklist in CLAUDE.md, and it drifted twice: 4 of 7 gates in 2026-08, then 7
of 11 plus 0 of 18 shell suites. A second gate (`check-ci-checklist.py`) now
compares the two lists, which works but means maintaining both. This script
does not maintain a list at all — it reads the workflow files and runs what
they run, so it cannot drift by construction.

Usage
-----
    ci-local.py                 run every job runnable on this machine
    ci-local.py --list          what would run, what would be skipped, and why
    ci-local.py --job pytest    one job
    ci-local.py --all           include conditional (schedule/dispatch) jobs
    ci-local.py --json          machine-readable result, for an automatic fixer
    ci-local.py --repo PATH     another repository

Exit code is 0 only when every job that ran passed. A skipped job is reported,
never silently dropped: "nothing ran" and "everything passed" must not look the
same, which is the failure mode two instruments in this repository have already
shipped.

Stdlib only — the syntax-check job installs no dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# ─── Workflow parsing ────────────────────────────────────────────────────────
# Line-based, not a YAML parser: configs/scripts/ is stdlib-only and workflow
# files are highly regular. check-ci-checklist.py already reads them this way.

_JOB = re.compile(r"^  ([a-z][\w-]*):\s*$")
_KEY = re.compile(r"^    ([a-z-]+):\s*(.*)$")
_STEP = re.compile(r"^      - (\S.*)$")
_STEP_KEY = re.compile(r"^        ([a-z-]+):\s*(.*)$")
_EXPR = re.compile(r"\$\{\{")

# Runner label -> the platform.system() value that can execute it.
_PLATFORM = {
    "ubuntu": "Linux",
    "macos": "Darwin",
    "windows": "Windows",
}


@dataclass
class Step:
    name: str
    run: str | None = None
    uses: str | None = None
    working_directory: str | None = None
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class Job:
    id: str
    name: str
    workflow: str
    runs_on: str = ""
    condition: str = ""
    steps: list[Step] = field(default_factory=list)

    @property
    def display(self) -> str:
        return self.name or self.id


def _dedent(lines: list[str]) -> str:
    body = [ln for ln in lines if ln.strip()]
    if not body:
        return ""
    pad = min(len(ln) - len(ln.lstrip()) for ln in body)
    return "\n".join(ln[pad:] if ln.strip() else "" for ln in lines).strip("\n")


def parse_workflow(path: Path) -> tuple[list[Job], str]:
    """Return (jobs, on-block text). Tolerant by design: anything it cannot read
    becomes a skip with a reason, never a silent omission."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    on_block = ""
    if "\non:" in "\n" + text:
        start = next(i for i, ln in enumerate(lines) if ln.startswith("on:"))
        end = next(
            (i for i in range(start + 1, len(lines))
             if lines[i] and not lines[i][0].isspace()),
            len(lines),
        )
        on_block = "\n".join(lines[start:end])

    jobs: list[Job] = []
    current: Job | None = None
    step: Step | None = None
    collecting: list[str] | None = None
    collect_indent = 0
    # Only two-space keys UNDER `jobs:` are jobs. Without this the trigger names
    # in the `on:` block (push, pull_request, schedule…) parse as jobs and the
    # plan lists four phantom entries per workflow.
    in_jobs = False

    def close_step() -> None:
        nonlocal step, collecting
        if step is not None and current is not None:
            if collecting is not None:
                step.run = _dedent(collecting)
            current.steps.append(step)
        step = None
        collecting = None

    for raw in lines:
        # A block scalar under `run: |` continues while indented past its key.
        if collecting is not None:
            if not raw.strip() or (len(raw) - len(raw.lstrip())) > collect_indent:
                collecting.append(raw)
                continue
            close_step_run = _dedent(collecting)
            collecting = None
            if step is not None:
                step.run = close_step_run

        if raw and not raw[0].isspace():
            close_step()
            in_jobs = raw.startswith("jobs:")
            current = None
            continue

        job_match = _JOB.match(raw) if in_jobs else None
        if job_match:
            close_step()
            current = Job(id=job_match.group(1), name="", workflow=path.name)
            jobs.append(current)
            continue

        if current is None:
            continue

        step_match = _STEP.match(raw)
        if step_match:
            close_step()
            step = Step(name="")
            rest = step_match.group(1)
            key_match = re.match(r"([a-z-]+):\s*(.*)$", rest)
            if key_match:
                key, value = key_match.group(1), key_match.group(2).strip()
                if key == "uses":
                    step.uses = value
                elif key == "name":
                    step.name = value
                elif key == "run":
                    if value == "|" or value.startswith("|"):
                        collecting, collect_indent = [], 8
                    else:
                        step.run = value
            continue

        if step is not None:
            sk = _STEP_KEY.match(raw)
            if sk:
                key, value = sk.group(1), sk.group(2).strip()
                if key == "run":
                    if value == "|" or value.startswith("|"):
                        collecting, collect_indent = [], 8
                    else:
                        step.run = value
                elif key == "uses":
                    step.uses = value
                elif key == "name":
                    step.name = value
                elif key == "working-directory":
                    step.working_directory = value
                continue
            # `env:` children sit deeper; capture simple literal pairs only.
            env_match = re.match(r"^          ([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", raw)
            if env_match:
                step.env[env_match.group(1)] = env_match.group(2).strip()
                continue

        jk = _KEY.match(raw)
        if jk:
            key, value = jk.group(1), jk.group(2).strip()
            if key == "name":
                current.name = value.strip('"')
            elif key == "runs-on":
                current.runs_on = value
            elif key == "if":
                current.condition = value

    close_step()
    return jobs, on_block


# ─── What can run here ───────────────────────────────────────────────────────

def local_platform() -> str:
    return platform.system()


def step_skip_reason(step: Step) -> str | None:
    if step.uses and not step.run:
        return "action, not a gate"
    if step.run and _EXPR.search(step.run):
        return "uses a GitHub expression that cannot be evaluated locally"
    if any(_EXPR.search(v) for v in step.env.values()):
        return "needs a repository secret"
    return None

def skip_reason(job: Job, on_block: str, include_conditional: bool) -> str | None:
    """Why this job will not run here, or None if it will."""
    if "pull_request_target" in on_block and "pull_request:" not in on_block:
        return "runs on GitHub's side only (pull_request_target)"
    if job.condition and not include_conditional:
        cond = job.condition.replace("github.event_name ==", "").strip()
        return f"conditional — {cond[:60]} (use --all)"
    for label, system in _PLATFORM.items():
        if label in job.runs_on:
            if system != local_platform():
                return f"needs {system}; this machine is {local_platform()}"
            break
    if not any(s.run for s in job.steps):
        return "no run: steps (setup-only job)"
    runnable = [s for s in job.steps if s.run and not step_skip_reason(s)]
    if not runnable:
        # Every step was individually skipped — a secret, or a GitHub
        # expression. Reporting the job as PASSED would be the exact lie this
        # tool exists to prevent: it executed nothing.
        reasons = sorted({step_skip_reason(s) or "" for s in job.steps if s.run})
        return f"every step skipped — {'; '.join(r for r in reasons if r)}"
    return None


# ─── Emulating actions/setup-python ──────────────────────────────────────────
# A hosted runner's `actions/setup-python` hands the job an ISOLATED Python, so
# `pip install` in a later step just works. A developer machine usually has a
# distribution-managed Python that refuses it outright (PEP 668,
# "externally-managed-environment"), which made two of this repository's five
# jobs fail locally for a reason that has nothing to do with the code.
#
# Reporting that as a build failure would be wrong, and skipping the job would
# hide real coverage. So provide what the action provides: a venv, created once
# per repository, reused across runs, kept OUT of the working tree so it can
# never be committed or confuse a `git status`.

def _venv_for(repo: Path) -> Path:
    import hashlib

    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    digest = hashlib.sha256(str(repo).encode()).hexdigest()[:10]
    return cache / "clade" / "ci-local" / f"{repo.name}-{digest}" / "venv"


def ensure_python_env(repo: Path, echo: bool) -> Path | None:
    """Create/reuse the venv that stands in for actions/setup-python."""
    venv = _venv_for(repo)
    bindir = venv / ("Scripts" if platform.system() == "Windows" else "bin")
    if (bindir / "python").exists() or (bindir / "python.exe").exists():
        return bindir
    if echo:
        print(f"    · creating the python env actions/setup-python would give ({venv})")
    venv.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, "-m", "venv", str(venv)],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        if echo:
            print(f"      could not create it: {proc.stderr.strip()[:120]}")
        return None
    return bindir


def job_needs_python(job: Job) -> bool:
    return any(s.uses and "actions/setup-python" in s.uses for s in job.steps)


# ─── Execution ───────────────────────────────────────────────────────────────

@dataclass
class StepResult:
    name: str
    status: str            # pass | fail | skip
    seconds: float = 0.0
    exit_code: int = 0
    reason: str = ""
    command: str = ""
    output_tail: str = ""


@dataclass
class JobResult:
    job: Job
    status: str            # pass | fail | skip
    reason: str = ""
    seconds: float = 0.0
    steps: list[StepResult] = field(default_factory=list)

    @property
    def failed_step(self) -> StepResult | None:
        return next((s for s in self.steps if s.status == "fail"), None)


def run_job(job: Job, repo: Path, tail_lines: int, echo: bool, timeout: int) -> JobResult:
    result = JobResult(job=job, status="pass")
    started = time.time()

    extra_path: str | None = None
    if job_needs_python(job):
        bindir = ensure_python_env(repo, echo)
        if bindir is not None:
            extra_path = str(bindir)

    for step in job.steps:
        reason = step_skip_reason(step)
        if reason:
            result.steps.append(StepResult(step.name or step.uses or "?", "skip", reason=reason))
            continue
        if not step.run:
            continue

        cwd = repo / step.working_directory if step.working_directory else repo
        env = dict(os.environ)
        env.update({k: v for k, v in step.env.items() if not _EXPR.search(v)})
        # CI=true is what most tools read to pick non-interactive output.
        env.setdefault("CI", "true")
        if extra_path:
            env["PATH"] = extra_path + os.pathsep + env.get("PATH", "")
            env["VIRTUAL_ENV"] = str(Path(extra_path).parent)
            # A venv already on PATH makes an inherited PYTHONHOME poisonous.
            env.pop("PYTHONHOME", None)

        if echo:
            print(f"    · {step.name or '(unnamed step)'} … ", end="", flush=True)
        t0 = time.time()
        try:
            proc = subprocess.run(
                ["bash", "-eo", "pipefail", "-c", step.run],
                cwd=cwd, env=env, capture_output=True, text=True,
                # A hosted runner gives a step no interactive stdin. Inheriting
                # the terminal's instead means one `read` anywhere in a suite
                # hangs the whole run with no output and no clue why — measured
                # at 13 minutes and 9% CPU before this was added.
                stdin=subprocess.DEVNULL,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            elapsed = time.time() - t0
            if echo:
                print(f"TIMED OUT ({elapsed:.0f}s)")
            tail = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            result.steps.append(
                StepResult(
                    step.name or "(unnamed)", "fail", elapsed, 124,
                    reason=f"exceeded the {timeout}s step timeout",
                    command=step.run,
                    output_tail="\n".join(tail.splitlines()[-tail_lines:]),
                )
            )
            result.status = "fail"
            break

        elapsed = time.time() - t0
        combined = (proc.stdout or "") + (proc.stderr or "")

        if proc.returncode == 0:
            if echo:
                print(f"ok ({elapsed:.0f}s)")
            result.steps.append(
                StepResult(step.name or "(unnamed)", "pass", elapsed, command=step.run)
            )
            continue

        if echo:
            print(f"FAILED ({elapsed:.0f}s, exit {proc.returncode})")
        result.steps.append(
            StepResult(
                step.name or "(unnamed)", "fail", elapsed, proc.returncode,
                command=step.run,
                output_tail="\n".join(combined.splitlines()[-tail_lines:]),
            )
        )
        result.status = "fail"
        # GitHub stops a job at its first failed step; match that.
        break

    result.seconds = time.time() - started
    return result


# ─── Reporting ───────────────────────────────────────────────────────────────

def collect_jobs(repo: Path, include_conditional: bool) -> list[tuple[Job, str | None]]:
    workflow_dir = repo / ".github" / "workflows"
    if not workflow_dir.is_dir():
        return []
    out: list[tuple[Job, str | None]] = []
    for path in sorted(workflow_dir.glob("*.y*ml")):
        jobs, on_block = parse_workflow(path)
        for job in jobs:
            out.append((job, skip_reason(job, on_block, include_conditional)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Run this repository's GitHub Actions gates locally.",
        epilog="A skipped job is always reported: nothing-ran must not look like all-passed.",
    )
    ap.add_argument("--repo", type=Path, default=Path.cwd())
    ap.add_argument("--job", action="append", help="Job id or name (repeatable).")
    ap.add_argument("--all", action="store_true",
                    help="Include conditional (schedule/dispatch) jobs. These are "
                         "the tiers a repo deliberately keeps off every push; some "
                         "spend real money. Prints what it is about to run first.")
    ap.add_argument("--list", action="store_true", help="Show the plan and exit.")
    ap.add_argument("--json", action="store_true", help="Machine-readable result.")
    ap.add_argument("--tail", type=int, default=40, help="Failure output lines (default 40).")
    ap.add_argument("--timeout", type=int, default=900,
                    help="Per-step timeout in seconds (default 900). A hung step is a failure.")
    args = ap.parse_args()

    repo = args.repo.resolve()
    if not (repo / ".github" / "workflows").is_dir():
        print(f"ci-local: no .github/workflows under {repo}")
        return 1

    plan = collect_jobs(repo, args.all)

    if args.job:
        wanted = {w.lower() for w in args.job}
        plan = [
            (j, r) for j, r in plan
            if j.id.lower() in wanted or j.name.lower() in wanted
        ]
        if not plan:
            print(f"ci-local: no job matching {args.job}")
            return 1
        # An explicitly named job runs even if it is conditional.
        plan = [(j, None if r and r.startswith("conditional") else r) for j, r in plan]

    if args.all and not args.list:
        # The conditional tier is conditional for a reason. In this repository
        # one of those jobs makes a live billed API call (~$0.05) and another
        # runs `npm audit` against the network; on someone else's repo it could
        # be a deploy. Name them before running, rather than after — and only
        # the ones that survived the --job filter, or the warning names work
        # that is not about to happen.
        conditional = [j for j, r in plan if j.condition and r is None]
        if conditional:
            print("--all also runs these normally-skipped jobs:")
            for job in conditional:
                print(f"  · {job.display}   ({job.workflow})")
            print("  Some conditional tiers spend money or touch the network.\n")

    if args.list:
        print(f"ci-local: {repo.name} on {local_platform()}\n")
        for job, reason in plan:
            runs = sum(1 for s in job.steps if s.run and not step_skip_reason(s))
            total = sum(1 for s in job.steps if s.run)
            mark = "run " if reason is None else "skip"
            print(f"  [{mark}] {job.display:32} {job.workflow:22} {runs}/{total} runnable")
            if reason:
                print(f"         ↳ {reason}")
        return 0

    if not shutil.which("bash"):
        print("ci-local: bash not found")
        return 1

    results: list[JobResult] = []
    for job, reason in plan:
        if reason:
            results.append(JobResult(job=job, status="skip", reason=reason))
            continue
        if not args.json:
            print(f"  {job.display}")
        results.append(run_job(job, repo, args.tail, echo=not args.json, timeout=args.timeout))

    ran = [r for r in results if r.status != "skip"]
    failed = [r for r in ran if r.status == "fail"]
    skipped = [r for r in results if r.status == "skip"]

    if args.json:
        json.dump(
            {
                "repo": str(repo),
                "platform": local_platform(),
                "passed": [r.job.display for r in ran if r.status == "pass"],
                "skipped": [{"job": r.job.display, "reason": r.reason} for r in skipped],
                "failed": [
                    {
                        "job": r.job.display,
                        "workflow": r.job.workflow,
                        "step": (r.failed_step.name if r.failed_step else ""),
                        "exit_code": (r.failed_step.exit_code if r.failed_step else 0),
                        "command": (r.failed_step.command if r.failed_step else ""),
                        "output_tail": (r.failed_step.output_tail if r.failed_step else ""),
                    }
                    for r in failed
                ],
            },
            sys.stdout, indent=2,
        )
        sys.stdout.write("\n")
        return 1 if failed else 0

    print()
    for r in failed:
        step = r.failed_step
        print(f"FAILED  {r.job.display}  ({r.job.workflow})")
        if step:
            print(f"  step: {step.name}   exit {step.exit_code}")
            first = step.command.strip().splitlines()[0] if step.command.strip() else ""
            print(f"  command: {first}")
            if step.output_tail:
                for line in step.output_tail.splitlines():
                    print(f"  | {line}")
        print()

    total = sum(r.seconds for r in ran)
    print(
        f"ci-local: {len(ran) - len(failed)}/{len(ran)} job(s) passed in {total:.0f}s"
        f"{f', {len(failed)} failed' if failed else ''}"
    )
    for r in skipped:
        print(f"  skipped {r.job.display}: {r.reason}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
