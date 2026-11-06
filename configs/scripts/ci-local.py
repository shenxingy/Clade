#!/usr/bin/env python3
"""
ci-local.py — run this repository's GitHub Actions gates on the machine you own.

Why
---
Hosted CI minutes are billed per job, rounded UP to the minute, per job, and
multiplied by platform: Linux 1x, Windows 2x, macOS 10x. A four-job workflow
whose jobs take 24s, 39s, 60s and 73s bills **five minutes**, not three. Push
fifty times in a day and that is 250 minutes for work a 32-core machine sitting
idle on the same desk would have done in ninety seconds.

The saving is only real on PRIVATE repositories — public repos get standard
runners free — but the *latency* saving is real everywhere: a local run answers
in seconds and does not need a push to start.

Why derive instead of duplicate
-------------------------------
This repository already had a hand-written "run these before committing"
checklist in CLAUDE.md, and it drifted twice: 4 of 7 gates in 2026-08, then 7
of 11 plus 0 of 17 shell suites. A second gate (`check-ci-checklist.py`) now
compares the two lists, which works but means maintaining both. This script
does not maintain a list at all — it reads the workflow files and runs what
they run, so it cannot drift by construction.

Usage
-----
    ci-local.py                 run every job runnable on this machine
    ci-local.py --list          what would run, what would be skipped, and why
    ci-local.py --job pytest    one job
    ci-local.py --all           also run jobs whose `if:` keeps them off this run
    ci-local.py --json          machine-readable result, for an automatic fixer
    ci-local.py --repo PATH     another repository
    ci-local.py --strict        exit 2 when the run is not green (see below)

A skipped job is reported, never silently dropped: "nothing ran" and
"everything passed" must not look the same, which is the failure mode two
instruments in this repository have already shipped.

Skips come in two kinds, and only one of them leaves the result intact:

  skipped    a workflow triggered by pull_request_target and by no push or
             pull_request, or a job whose `if:` is false on every push and
             pull_request — a schedule/dispatch tier, failure() (the hosted
             push/PR run does not execute it either); a job for another
             platform (proven on the machine that has it).
  unproven   a lane this runner cannot reproduce: a job using services:,
             container:, strategy:, a reusable workflow, a defaults: other
             than `run: shell: bash`, an env block scalar, a steps: block or a
             job body it cannot parse; a runs-on: or job-level `if:` it cannot
             evaluate; a step whose `if:` or `${{ }}` expression it cannot
             evaluate; a step that needs a repository secret — declared,
             inherited from job or workflow env, or used in run: — which never
             runs here, because a tool run without it falls back to this
             machine's own credentials; an action step other than checkout,
             cache, artifact upload/download or a setup-* action (a lint
             action, a local composite), so a job whose only gates are actions
             is unproven, not setup-only. A step whose INHERITED env holds a
             non-secret `${{ }}` value runs with that variable unset, and its
             pass is unproven too. The hosted run executes these lanes; this
             run did not prove them, so a green here says nothing.

Exit 1 when a job that ran failed. Otherwise any unproven lane makes the
summary read PARTIAL, and a run in which no job ran at all reads NOTHING RAN;
the JSON `verdict` is pass, partial, none or fail, and only pass is green.
During the report-only rollout the exit code for partial and none is still 0;
--strict makes it 2, and the default flips on the date TODO.md names.

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
import tempfile
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# ─── Workflow parsing ────────────────────────────────────────────────────────
# Line-based, not a YAML parser: configs/scripts/ is stdlib-only and workflow
# files are highly regular. check-ci-checklist.py already reads them this way.

# Every line at the jobs: indent IS a job in YAML. A lowercase-only regex read
# `  Build:`, `  _lint:` and `  backend:  # note` as nothing, and every key
# under them then landed on the job BEFORE — its name overwritten, its steps
# merged, the lane gone from the plan. So a header is read loosely (any id, a
# quoted one, a trailing comment) and a line it still cannot read becomes a
# flagged job of its own, never part of its neighbour.
_JOB_HEADER = re.compile(r"""("[^"]*"|'[^']*'|[^\s"'#][^:]*?)\s*:(?:\s(.*))?""")
_KEY = re.compile(r"^    ([a-z-]+):\s*(.*)$")
# `on:`, or `"on":` — quoted by projects whose yamllint flags a bare `on` as
# a truthy value. Missed, a pull_request_target workflow had no triggers and
# its job ran here, against the GitHub API it exists to call.
_ON_KEY = re.compile(r"""^(on|"on"|'on')\s*:""")
# The first `- ` under a job's `steps:` fixes the column its steps sit at: 6
# in most workflows, 4 in GitHub's own starter templates, which put the dash
# level with `steps:`. A fixed 6 read every step of that shape as nothing, and
# the job was reported as a setup-only skip — a reasoned class, not unproven.
_STEP_DASH = re.compile(r"^( {4,})- \S")
_EXPR = re.compile(r"\$\{\{")
_EXPR_SPAN = re.compile(r"\$\{\{(.*?)\}\}", re.S)
# A credential a developer machine should not be holding. Every other
# expression (github.*, runner.*, steps.*, matrix.*) is context this runner
# does not have — which is a different thing, and was labelled as a secret
# until 2026-11, hiding an E2E suite's only real step behind a "good reason".
_SECRET_REF = re.compile(r"\bsecrets\.|\bgithub\.token\b")
# `NAME: value` pairs of an env: block, at workflow, job and step depth.
_ENV_PAIR_WORKFLOW = re.compile(r"^  ([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")
_ENV_PAIR_JOB = re.compile(r"^      ([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")
# `NAME: |` or `NAME: >-`: the value is the indented block below, which this
# parser does not fold. Read as the indicator itself it set OPTS='>-' and the
# run still reported pass, so such an env makes the job unproven instead.
_BLOCK_SCALAR = re.compile(r"[|>][1-9]?[+-]?|[|>][+-]?[1-9]?")

# Job-level keys whose semantics this runner does not reproduce. `defaults:`
# is handled on its own (see _defaults_modelled), and `uses:` — a reusable
# workflow — names the workflow it calls rather than the key.
_UNMODELLED_JOB_KEYS = frozenset({"strategy", "container", "services"})
# Step-level keys likewise. A step-level `if:` used to be here and made the
# whole job a skip; it is evaluated per step now (success_path_if), because
# most of them guard an upload action and the job is perfectly runnable.
_UNMODELLED_STEP_KEYS = frozenset({"continue-on-error"})

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
    condition: str = ""
    env: dict[str, str] = field(default_factory=dict)
    # Keys of `env` the step did not declare itself: they came from the job or
    # the workflow. A `${{ }}` declared ON a step says that step reads it; one
    # inherited from above says nothing about whether this step does. (A
    # secret is the exception: own or inherited, the step does not run.)
    inherited: frozenset[str] = frozenset()

    @property
    def display(self) -> str:
        # GitHub names an unnamed run step "Run <first line>"; so do we, so a
        # lane named in a report can be found in the Actions log.
        if self.name:
            return self.name
        if self.run:
            return "Run " + self.run.strip().splitlines()[0][:60]
        return self.uses or "?"


@dataclass
class Job:
    id: str
    name: str
    workflow: str
    runs_on: str = ""
    condition: str = ""
    env: dict[str, str] = field(default_factory=dict)
    steps: list[Step] = field(default_factory=list)
    # Workflow constructs this line-based parser does NOT model. Anything here
    # makes the job a loud skip rather than a partial run: a matrix job silently
    # collapsed to one leg, or a container job run on the host, is a green that
    # covered less than it appears to — the failure this tool exists to prevent,
    # arriving from a new direction.
    unmodelled: list[str] = field(default_factory=list)
    # A `steps:` key was seen. One that yields no step at all is a block this
    # parser could not read (flow style, an indent it does not expect), and
    # must not be reported as a setup-only job — that is a reasoned skip.
    declares_steps: bool = False
    # The children of a job-level `defaults:`, decided after the parse.
    defaults: list[str] | None = None
    # Job-level keys read at four spaces. A job with neither `runs-on:` nor
    # `uses:` is one whose body this parser did not read (keys at another
    # indent, flow style): it reported "setup-only", a reasoned skip.
    keys: set[str] = field(default_factory=set)

    @property
    def display(self) -> str:
        return self.name or self.id


def _dedent(lines: list[str]) -> str:
    body = [ln for ln in lines if ln.strip()]
    if not body:
        return ""
    pad = min(len(ln) - len(ln.lstrip()) for ln in body)
    return "\n".join(ln[pad:] if ln.strip() else "" for ln in lines).strip("\n")


def _scalar(value: str) -> str:
    """A one-line YAML scalar as the runner sees it: surrounding quotes removed,
    a trailing comment dropped. `CI: '1'` is the string 1, not '1' with quotes —
    which is what every env value here was until 2026-11."""
    v = value.strip()
    if v[:1] == "'":
        out, i = [], 1
        while i < len(v):
            if v[i] == "'":
                if v[i + 1:i + 2] == "'":       # '' is an escaped quote
                    out.append("'")
                    i += 2
                    continue
                return "".join(out)
            out.append(v[i])
            i += 1
        return v                                # unterminated: leave it alone
    if v[:1] == '"':
        out, i = [], 1
        while i < len(v):
            if v[i] == "\\" and i + 1 < len(v):
                out.append(v[i + 1])
                i += 2
                continue
            if v[i] == '"':
                return "".join(out)
            out.append(v[i])
            i += 1
        return v
    return re.sub(r"(^|\s)#.*$", "", v).strip()


def _is_block_scalar(value: str) -> bool:
    return bool(_BLOCK_SCALAR.fullmatch(_scalar(value)))


def _defaults_modelled(lines: list[str]) -> bool:
    """True when a `defaults:` block says only `run: shell: bash`, which is what
    this runner already does (`bash -eo pipefail`, GitHub's own bash flags).
    Anything else — a working-directory, another shell, flow style — moves or
    reinterprets every step, and dropping it silently runs them in the wrong
    place, so that job is unproven."""
    pairs = []
    for ln in lines:
        key, _, value = ln.strip().partition(":")
        pairs.append((len(ln) - len(ln.lstrip()), key.strip(), _scalar(value)))
    return (len(pairs) == 2 and pairs[0][1:] == ("run", "")
            and pairs[1][1:] == ("shell", "bash") and pairs[1][0] > pairs[0][0])


def _job_header(raw: str) -> tuple[str, str]:
    """(job id, whatever follows its colon) for a line at the jobs: indent.
    A line that does not read as `id:` comes back as its own text twice, so it
    is still a job — flagged — rather than a key of the job above it."""
    body = raw.strip()
    m = _JOB_HEADER.fullmatch(body)
    if m is None:
        return body[:60], body
    return _scalar(m.group(1)), _scalar(m.group(2) or "")


def _flow_names(text: str) -> list[str]:
    """Top-level names of a flow value: `push`, `[push, pull_request]`, or
    `{push: {branches: [main]}, pull_request: {}}`."""
    t = text.strip()
    if t[:1] in ("[", "{"):
        t = t[1:-1] if t[-1:] in ("]", "}") else t[1:]
    items, depth, cur = [], 0, ""
    for c in t:
        depth += (c in "[{") - (c in "]}")
        if c == "," and depth == 0:
            items.append(cur)
            cur = ""
        else:
            cur += c
    items.append(cur)
    return [it.split(":", 1)[0].strip().strip("'\"") for it in items if it.strip()]


def workflow_triggers(on_block: str) -> set[str]:
    """The event names an `on:` block lists, comments ignored. Until 2026-11
    the classification was a substring test over the raw block: a comment
    reading `pull_request:` ran a pull_request_target job here, and
    `[push, pull_request_target]` was labelled GitHub-side only."""
    lines = [re.sub(r"(^|\s)#.*$", "", ln).rstrip() for ln in on_block.splitlines()]
    lines = [ln for ln in lines if ln.strip()]
    if not lines:
        return set()
    head = lines[0].split(":", 1)[1].strip() if ":" in lines[0] else ""
    if head:
        return set(_flow_names(head))
    body = lines[1:]
    if not body:
        return set()
    pad = min(len(ln) - len(ln.lstrip()) for ln in body)
    names: set[str] = set()
    for ln in body:
        if len(ln) - len(ln.lstrip()) != pad:
            continue
        item = ln.strip()
        item = item[2:] if item.startswith("- ") else item.split(":", 1)[0]
        names.add(item.strip().strip("'\""))
    return names


def parse_workflow(path: Path) -> tuple[list[Job], str]:
    """Return (jobs, on-block text). Tolerant by design: anything it cannot read
    becomes a skip with a reason, never a silent omission."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    on_block = ""
    start = next((i for i, ln in enumerate(lines) if _ON_KEY.match(ln)), None)
    if start is not None:
        # A column-0 comment does not end the block; the next key does.
        end = next(
            (i for i in range(start + 1, len(lines))
             if lines[i] and not lines[i][0].isspace() and not lines[i].startswith("#")),
            len(lines),
        )
        on_block = "\n".join(lines[start:end])

    jobs: list[Job] = []
    current: Job | None = None
    step: Step | None = None
    collecting: list[str] | None = None
    collect_indent = 0
    # Which top-level key we are under. Only two-space keys UNDER `jobs:` are
    # jobs — without this the trigger names in the `on:` block (push,
    # pull_request, schedule…) parse as jobs and the plan lists four phantom
    # entries per workflow. `env:` and `defaults:` up here apply to every job.
    section = ""
    workflow_env: dict[str, str] = {}
    workflow_unmodelled: list[str] = []
    workflow_defaults: list[str] | None = None
    # Whose children are being read: a job-level "env" or "defaults", or "".
    job_block = ""
    # Inside the current job's `steps:`, and the column its dashes sit at once
    # the first one has been seen (-1 until then).
    in_steps = False
    dash = -1
    # The column of the first line under `jobs:`: every line there is a job.
    # The rest of this parser reads job keys at four spaces, so jobs at any
    # other indent are listed and flagged, not dropped as they used to be.
    job_indent = -1
    # The open step's own key whose children follow. Only `env:` children are
    # environment: a uses-step's `with: script: |` is not, and read as one it
    # made every github-script job an unproven "env block scalar".
    step_block = ""

    def close_step() -> None:
        nonlocal step, collecting
        if step is not None and current is not None:
            if collecting is not None:
                step.run = _dedent(collecting)
            current.steps.append(step)
        step = None
        collecting = None

    def step_key(key: str, value: str) -> None:
        """One `key: value` of the open step, whether it opened the step
        (`- name: …`) or sat under it."""
        nonlocal collecting, collect_indent, step_block
        assert step is not None and current is not None
        step_block = key
        if key == "run":
            if value == "|" or value.startswith("|"):
                collecting, collect_indent = [], dash + 2
            else:
                step.run = value
        elif key == "uses":
            # Pinned actions carry `# v4.3.1` after the SHA, and the name of
            # an unnamed action step is what a lane is reported as.
            step.uses = _scalar(value)
        elif key == "name":
            step.name = _scalar(value)
        elif key == "working-directory":
            step.working_directory = _scalar(value)
        elif key == "if":
            step.condition = value
        elif key in _UNMODELLED_STEP_KEYS:
            current.unmodelled.append(f"step-level {key}")

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

        # A comment is not a key. At column 0 it used to read as a new
        # top-level section and silently end `jobs:` — every job after it
        # vanished from the plan, not even listed as skipped.
        if raw.lstrip().startswith("#"):
            continue
        if not raw.strip():
            continue

        if not raw[0].isspace():
            close_step()
            section = raw.split(":", 1)[0].strip().strip("'\"")
            # `env: # note` is still an empty key with a mapping below it.
            rest = _scalar(raw.split(":", 1)[1]) if ":" in raw else ""
            current = None
            job_block = ""
            in_steps = False
            if section == "defaults":
                # Flow style on this line is kept so it reads as not modelled.
                workflow_defaults = [raw] if rest else []
            elif section == "env" and rest:
                workflow_unmodelled.append("workflow-level env that is not a plain mapping")
            continue

        if section == "defaults":
            if workflow_defaults is not None:
                workflow_defaults.append(raw)
            continue

        if section == "env":
            pair = _ENV_PAIR_WORKFLOW.match(raw)
            if pair:
                if _is_block_scalar(pair.group(2)):
                    workflow_unmodelled.append("a workflow-level env block scalar")
                workflow_env[pair.group(1)] = _scalar(pair.group(2))
            continue

        indent = len(raw) - len(raw.lstrip())
        if section == "jobs" and job_indent < 0:
            job_indent = indent
        if section == "jobs" and indent == job_indent:
            close_step()
            job_id, rest = _job_header(raw)
            current = Job(id=job_id, name="", workflow=path.name)
            if rest:
                # `build: {runs-on: …, steps: […]}`, an alias, or a line
                # that is not `id:` at all: its keys are not on later lines.
                current.unmodelled.append(f"a job written on its key line ({rest[:40]})")
            if job_indent != 2:
                current.unmodelled.append(f"a jobs: block indented {job_indent} spaces")
            jobs.append(current)
            job_block = ""
            in_steps = False
            dash = -1
            continue

        if current is None:
            continue

        if in_steps:
            if dash < 0:
                first = _STEP_DASH.match(raw)
                if first:
                    dash = len(first.group(1))
            pad = " " * dash
            if dash >= 0 and raw.startswith(pad + "- ") and raw[dash + 2:dash + 3].strip():
                close_step()
                step = Step(name="")
                step_block = ""
                key_match = re.match(r"([a-z-]+):\s*(.*)$", raw[dash + 2:])
                if key_match:
                    step_key(key_match.group(1), key_match.group(2).strip())
                continue
            if dash >= 0 and step is not None:
                sk = re.match(rf"{pad}  ([a-z-]+):\s*(.*)$", raw)
                if sk:
                    step_key(sk.group(1), sk.group(2).strip())
                    continue
                # `env:` children sit deeper; capture simple literal pairs only.
                env_match = re.match(rf"{pad}    ([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", raw)
                if env_match:
                    if step_block == "env":
                        if _is_block_scalar(env_match.group(2)):
                            current.unmodelled.append("a step env block scalar")
                        step.env[env_match.group(1)] = _scalar(env_match.group(2))
                    continue

        if job_block == "env":
            pair = _ENV_PAIR_JOB.match(raw)
            if pair:
                if _is_block_scalar(pair.group(2)):
                    current.unmodelled.append("a job-level env block scalar")
                current.env[pair.group(1)] = _scalar(pair.group(2))
                continue
        elif job_block == "defaults" and len(raw) - len(raw.lstrip()) > 4:
            assert current.defaults is not None
            current.defaults.append(raw)
            continue

        jk = _KEY.match(raw)
        if jk:
            # A four-space key is the job's, never a step's: the steps are over.
            close_step()
            key, value = jk.group(1), jk.group(2).strip()
            current.keys.add(key)
            # `env: # note` is a mapping like `env:` — a comment is not a value.
            bare = not _scalar(value)
            # A job's own `env:` — every step inherits it. Dropped until
            # 2026-11, so a job declaring DATABASE_URL=sqlite ran against
            # whatever DATABASE_URL the developer's shell happened to export.
            job_block = key if key in ("env", "defaults") and bare else ""
            in_steps = key == "steps"
            if key == "steps":
                current.declares_steps = True
            elif key == "env" and not bare:
                current.unmodelled.append("job-level env that is not a plain mapping")
            elif key == "defaults":
                current.defaults = [] if bare else [raw.strip()]
            elif key == "uses":
                # A reusable workflow: the hosted run executes ITS jobs, and
                # with no steps here this read as a setup-only (reasoned) skip.
                current.unmodelled.append(f"a reusable workflow ({_scalar(value)[:60]})")
            if key in _UNMODELLED_JOB_KEYS:
                current.unmodelled.append(key)
            if key == "name":
                current.name = _scalar(value)
            elif key == "runs-on":
                current.runs_on = value
            elif key == "if":
                current.condition = value

    close_step()
    if workflow_defaults is not None and not _defaults_modelled(workflow_defaults):
        # `defaults: run: working-directory/shell` moves or reinterprets every
        # step. Dropping it silently runs them in the wrong place.
        workflow_unmodelled.append("workflow-level defaults")
    for job in jobs:
        if job.defaults is not None and not _defaults_modelled(job.defaults):
            job.unmodelled.append("defaults")
        if job.declares_steps and not job.steps:
            job.unmodelled.append("a steps: block it could not parse")
        if not job.keys & {"runs-on", "uses"}:
            job.unmodelled.append("a job body it could not read (no runs-on: at four spaces)")
        job.unmodelled.extend(workflow_unmodelled)
        for st in job.steps:
            # Workflow env < job env < step env, the precedence GitHub applies.
            st.inherited = frozenset((workflow_env.keys() | job.env.keys()) - st.env.keys())
            st.env = {**workflow_env, **job.env, **st.env}
    return jobs, on_block


# ─── What can run here ───────────────────────────────────────────────────────

def local_platform() -> str:
    return platform.system()


# Step-level `if:` on the SUCCESS path — the only path a passing job takes,
# since a failed step ends the job here as it does on GitHub. There the status
# functions have fixed values and nothing else does: `steps.x.outputs`,
# `github.ref` and `matrix.*` are context this runner does not have, so such a
# step is skipped and the lane is UNPROVEN rather than guessed at.
_SUCCESS_PATH_IF = {
    "success()": True, "always()": True, "!cancelled()": True,
    "!failure()": True, "true": True,
    "failure()": False, "cancelled()": False, "!success()": False,
    "false": False,
}


def _unwrap(condition: str) -> str:
    """An `if:` as an expression: YAML quotes and a `${{ }}` wrapper removed."""
    cond = _scalar(condition)
    wrapped = re.fullmatch(r"\$\{\{(.*)\}\}", cond, re.S)
    return (wrapped.group(1) if wrapped else cond).strip()


def success_path_if(condition: str) -> bool | None:
    """True or False when `condition` has a fixed value on the success path,
    None when it depends on anything this runner cannot know."""
    return _SUCCESS_PATH_IF.get(re.sub(r"\s+", "", _unwrap(condition)))


# ─── Job-level if: ───────────────────────────────────────────────────────────
# A job whose `if:` is false on every push and pull_request belongs to another
# trigger's tier (schedule, workflow_dispatch, release…): the hosted push/PR
# run skips it too, so skipping it here leaves nothing unproven. Any other `if:`
# this runner cannot evaluate — `github.ref == 'refs/heads/main'`, a draft
# check, `github.event_name == 'pull_request'` — guards a lane the hosted run
# executes, and was labelled "conditional (use --all)" like a schedule tier
# until 2026-11.

_PUSH_PR_EVENTS = frozenset({"push", "pull_request"})
_EVENT_EQ = re.compile(
    r"github\.event_name\s*==\s*'([^']*)'|'([^']*)'\s*==\s*github\.event_name")


def _split_top(expr: str, op: str) -> list[str]:
    """`expr` split at `op` outside parentheses and quoted strings."""
    parts: list[str] = []
    depth, quoted, start, i = 0, False, 0, 0
    while i < len(expr):
        c = expr[i]
        if c == "'":
            quoted = not quoted          # '' inside a string toggles twice
        elif not quoted and c == "(":
            depth += 1
        elif not quoted and c == ")":
            depth -= 1
        elif not quoted and depth == 0 and expr.startswith(op, i):
            parts.append(expr[start:i].strip())
            i += len(op)
            start = i
            continue
        i += 1
    parts.append(expr[start:].strip())
    return parts


def _strip_parens(expr: str) -> str:
    """`(a && b)` -> `a && b`, repeatedly; `(a) || (b)` is left alone."""
    e = expr.strip()
    while e.startswith("(") and e.endswith(")"):
        depth = 0
        for c in e[1:-1]:
            depth += (c == "(") - (c == ")")
            if depth < 0:
                return e                 # the first "(" closes before the end
        e = e[1:-1].strip()
    return e


def _off_push_pr(expr: str) -> bool:
    """True only when `expr` is certainly false on a push and on a
    pull_request event. Unknown terms count as possibly true."""
    e = _strip_parens(expr)
    disjuncts = _split_top(e, "||")
    if len(disjuncts) > 1:
        return all(_off_push_pr(d) for d in disjuncts)
    conjuncts = _split_top(e, "&&")
    if len(conjuncts) > 1:
        return any(_off_push_pr(c) for c in conjuncts)
    m = _EVENT_EQ.fullmatch(e)
    if m is None:
        return False
    return (m.group(1) or m.group(2) or "").lower() not in _PUSH_PR_EVENTS


def job_condition(condition: str) -> str:
    """"run" (true on a passing push/PR run), "off" (false there: GitHub skips
    it too) or "unknown" (this runner cannot tell)."""
    fixed = success_path_if(condition)
    if fixed is not None:
        return "run" if fixed else "off"
    return "off" if _off_push_pr(_unwrap(condition)) else "unknown"


# ─── Steps ───────────────────────────────────────────────────────────────────

def _expression_kind(text: str) -> str | None:
    """None, "secret" (a credential), or "expression" (GitHub context)."""
    if not _EXPR.search(text):
        return None
    spans = _EXPR_SPAN.findall(text) or [text]
    return "secret" if any(_SECRET_REF.search(sp) for sp in spans) else "expression"


@dataclass(frozen=True)
class StepPlan:
    run: bool                # executes on the success path
    reason: str = ""         # why not, or what it runs without
    unproven: bool = False   # the hosted run's lane is not proven by this one


# Actions that prepare the runner or move files, and test nothing: skipping
# one leaves no lane unproven. Every other action — a lint action, a local
# composite (`./.github/actions/test`), a test-runner action — is a gate the
# hosted run executes and this runner does not. Until 2026-11 all of them were
# "action, not a gate", and a job whose only gate was an action read as a
# setup-only skip, so a lint lane counted toward a pass it never ran in.
_SETUP_ACTIONS = frozenset({"checkout", "cache", "upload-artifact", "download-artifact"})


def is_setup_action(uses: str) -> bool:
    ref, at, _ = uses.partition("@")
    if not at:
        return False      # ./local composite or docker://image: may be anything
    parts = ref.lower().split("/")
    if parts[0] == "actions" and len(parts) > 1 and parts[1] in _SETUP_ACTIONS:
        return True
    return any(p.startswith("setup-") or p == "action-setup" for p in parts[1:])


def plan_step(step: Step) -> StepPlan:
    """What this runner does with one step on the success path, and whether a
    skip leaves the lane unproven or is the same thing GitHub would do."""
    if step.uses and not step.run:
        if is_setup_action(step.uses):
            return StepPlan(False, "action, not a gate")
        if step.condition and success_path_if(step.condition) is False:
            return StepPlan(False, f"if: {_scalar(step.condition)[:60]} is false on the success path")
        return StepPlan(False, f"action {step.uses[:60]}: this runner executes only run: steps",
                        unproven=True)
    if not step.run:
        return StepPlan(False, "no run: block")
    if step.condition:
        verdict = success_path_if(step.condition)
        cond = _scalar(step.condition)[:60]
        if verdict is None:
            return StepPlan(False, f"step-level if: {cond} cannot be evaluated locally",
                            unproven=True)
        if not verdict:
            # GitHub skips it on a passing run too: nothing is left unproven.
            return StepPlan(False, f"if: {cond} is false on the success path")
    in_run = _expression_kind(step.run)
    # A secret the step declares, inherits from job or workflow env, or uses in
    # run: keeps it from running at all. Run with the variable unset — what
    # this runner did with an inherited one until 2026-11 — aws, gh, npm and
    # docker fall back to ~/.aws, gh auth, ~/.npmrc and ~/.docker/config.json:
    # this machine's own credentials, acting on whatever the step targets.
    # The hosted run executes the step and this one did not: unproven.
    secrets = sorted(k for k, v in step.env.items() if _expression_kind(v) == "secret")
    if in_run == "secret":
        secrets.append("in run:")
    if secrets:
        return StepPlan(False, f"needs a repository secret ({', '.join(secrets)}); run without "
                               "it, a tool falls back to this machine's own credentials",
                        unproven=True)
    own = {_expression_kind(v) for k, v in step.env.items() if k not in step.inherited} - {None}
    if in_run:
        return StepPlan(False, "uses a GitHub expression that cannot be evaluated locally",
                        unproven=True)
    if own:
        return StepPlan(False, "its env uses a GitHub expression that cannot be evaluated locally",
                        unproven=True)
    # An inherited non-secret `${{ }}` (github.repository, vars.*) may not be
    # read by this step at all, so skipping it would throw away coverage the
    # old runner had. Run it with those variables unset instead, and do not
    # let its pass speak for the hosted lane.
    unset = sorted(k for k in step.inherited if _EXPR.search(step.env[k]))
    if unset:
        return StepPlan(True, f"runs without {', '.join(unset)}, inherited env that only the "
                              "hosted run can set", unproven=True)
    return StepPlan(True)


@dataclass(frozen=True)
class Skip:
    reason: str
    # True for the fifth class: the hosted push/PR run executes this lane and
    # this run could not, so a local green says nothing about it.
    unproven: bool = False


def skip_reason(job: Job, on_block: str, include_conditional: bool) -> Skip | None:
    """Why this job will not run here, or None if it will.

    The reasoned classes are tested FIRST. A pull_request_target workflow or a
    schedule tier does not run on the hosted push/PR path either, so it must not
    be reported as an unproven lane merely because it also uses a construct this
    runner cannot model — this repository's own honeypot-check and vouch-gate
    were, until 2026-11, because the unmodelled test came first.
    """
    triggers = workflow_triggers(on_block)
    if "pull_request_target" in triggers and not triggers & _PUSH_PR_EVENTS:
        return Skip("runs on GitHub's side only (pull_request_target)")
    cond = job_condition(job.condition) if job.condition else "run"
    if cond == "off" and not include_conditional:
        if success_path_if(job.condition) is False:
            return Skip(f"if: {_scalar(job.condition)[:60]} is false on a passing run")
        shown = job.condition.replace("github.event_name ==", "").strip()
        return Skip(f"conditional — {shown[:60]} (use --all)")
    # An expression runs-on names no platform yet: it is decided below.
    if "${{" not in job.runs_on:
        for label, system in _PLATFORM.items():
            if label in job.runs_on:
                if system != local_platform():
                    return Skip(f"needs {system}; this machine is {local_platform()}")
                break
    # The fifth class: the hosted run executes these, this runner cannot.
    if job.unmodelled:
        what = ", ".join(sorted(set(job.unmodelled)))
        return Skip(f"uses {what}, which this runner does not model — run it hosted, "
                    "or split the job", unproven=True)
    if "${{" in job.runs_on:
        return Skip("runs-on is an expression (matrix leg) — run each leg on its own machine",
                    unproven=True)
    if cond == "unknown" and not include_conditional:
        return Skip(f"job-level if: {_scalar(job.condition)[:60]} cannot be evaluated "
                    "locally (--all runs it anyway)", unproven=True)
    gates = [(s, plan_step(s)) for s in job.steps if s.run or s.uses]
    if not any(s.run for s in job.steps):
        actions = [s.display for s, p in gates if p.unproven]
        if actions:
            return Skip("its gates are actions, which this runner does not execute: "
                        + ", ".join(actions)[:120], unproven=True)
        return Skip("no run: steps (setup-only job)")
    if not any(p.run for _, p in gates):
        # Every step was individually skipped. Reporting the job as PASSED
        # would be the exact lie this tool exists to prevent: it executed
        # nothing. Unproven if any of those skips was.
        reasons = sorted({p.reason for s, p in gates if s.run or p.unproven})
        return Skip(f"every step skipped — {'; '.join(reasons)}",
                    unproven=any(p.unproven for _, p in gates))
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
    unproven: bool = False


@dataclass
class JobResult:
    job: Job
    status: str            # pass | fail | skip
    reason: str = ""
    seconds: float = 0.0
    steps: list[StepResult] = field(default_factory=list)
    unproven: bool = False   # a skipped job of the fifth class

    @property
    def failed_step(self) -> StepResult | None:
        return next((s for s in self.steps if s.status == "fail"), None)

    @property
    def unproven_steps(self) -> list[StepResult]:
        # Skipped for want of hosted context, or passed without part of it.
        return [s for s in self.steps if s.unproven and s.status != "fail"]


def run_job(job: Job, repo: Path, tail_lines: int, echo: bool, timeout: int) -> JobResult:
    result = JobResult(job=job, status="pass")
    started = time.time()

    extra_path: str | None = None
    if job_needs_python(job):
        bindir = ensure_python_env(repo, echo)
        if bindir is not None:
            extra_path = str(bindir)

    for step in job.steps:
        plan = plan_step(step)
        if not plan.run:
            if step.run or step.uses:
                # The job goes on: a skipped step is not a failed one. Whether
                # the skip leaves the lane unproven is recorded, not decided here.
                result.steps.append(StepResult(step.display, "skip", reason=plan.reason,
                                               unproven=plan.unproven))
            continue
        assert step.run is not None

        cwd = repo / step.working_directory if step.working_directory else repo
        env = dict(os.environ)
        if _CLEAN_HOME:
            # A hosted runner has no ~/.claude, no installed skills, no agents,
            # no shell history. A test that passes here because THIS machine has
            # that state is the one class a local runner cannot otherwise see —
            # measured: three consecutive pushes were green locally and red
            # hosted, on a test that found an agent only because install.sh had
            # run. Not a substitute for the clean-machine property, but it
            # catches the cheap half of it.
            env["HOME"] = str(_CLEAN_HOME)
            env["CLAUDE_CONFIG_DIR"] = str(_CLEAN_HOME / ".claude")
            env["XDG_CACHE_HOME"] = str(_CLEAN_HOME / ".cache")
        for key, value in step.env.items():
            if _EXPR.search(value):
                # Only the hosted run can set it (plan_step). Unset, not the
                # developer's own exported value standing in for it.
                env.pop(key, None)
            else:
                env[key] = value
        # CI=true is what most tools read to pick non-interactive output.
        env.setdefault("CI", "true")
        if extra_path:
            env["PATH"] = extra_path + os.pathsep + env.get("PATH", "")
            env["VIRTUAL_ENV"] = str(Path(extra_path).parent)
            # A venv already on PATH makes an inherited PYTHONHOME poisonous.
            env.pop("PYTHONHOME", None)

        if echo:
            print(f"    · {step.display} … ", end="", flush=True)
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
                    step.display, "fail", elapsed, 124,
                    reason="; ".join(filter(None, [f"exceeded the {timeout}s step timeout",
                                                   plan.reason])),
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
                StepResult(step.display, "pass", elapsed, command=step.run,
                           reason=plan.reason, unproven=plan.unproven)
            )
            continue

        if echo:
            print(f"FAILED ({elapsed:.0f}s, exit {proc.returncode})")
        result.steps.append(
            StepResult(
                step.display, "fail", elapsed, proc.returncode,
                # A step that ran without inherited env says so: that may be
                # the whole cause, and a fixer should not chase it in the code.
                reason=plan.reason,
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

def collect_jobs(repo: Path, include_conditional: bool) -> list[tuple[Job, Skip | None]]:
    workflow_dir = repo / ".github" / "workflows"
    if not workflow_dir.is_dir():
        return []
    out: list[tuple[Job, Skip | None]] = []
    for path in sorted(workflow_dir.glob("*.y*ml")):
        jobs, on_block = parse_workflow(path)
        for job in jobs:
            out.append((job, skip_reason(job, on_block, include_conditional)))
    return out


@dataclass(frozen=True)
class Lane:
    """One thing the hosted run executes that this run did not prove: a whole
    job (step == "") or a single step of a job that otherwise ran."""
    job: Job
    step: str
    reason: str

    @property
    def label(self) -> str:
        return f"{self.job.display} › {self.step}" if self.step else self.job.display


def unproven_lanes(results: list[JobResult]) -> list[Lane]:
    lanes: list[Lane] = []
    for r in results:
        if r.status == "skip":
            if r.unproven:
                lanes.append(Lane(r.job, "", r.reason))
            continue
        lanes.extend(Lane(r.job, s.name, s.reason) for s in r.unproven_steps)
    return lanes


def print_plan(repo: Path, plan: list[tuple[Job, Skip | None]]) -> None:
    print(f"ci-local: {repo.name} on {local_platform()}\n")
    lanes: list[str] = []
    for job, skip in plan:
        # Action steps are planned too: a gate action is an unproven lane.
        plans = [(s, plan_step(s)) for s in job.steps if s.run or s.uses]
        runs = sum(1 for _, p in plans if p.run)
        total = sum(1 for s, _ in plans if s.run)
        mark = "run " if skip is None else "skip"
        print(f"  [{mark}] {job.display:32} {job.workflow:22} {runs}/{total} runnable")
        if skip is not None:
            print(f"         ↳ {'UNPROVEN — ' if skip.unproven else ''}{skip.reason}")
            if skip.unproven:
                lanes.append(job.display)
            continue
        for step, p in plans:
            if p.unproven:
                print(f"         ↳ UNPROVEN step {step.display}: {p.reason}")
                lanes.append(f"{job.display} › {step.display}")
    if lanes:
        print(f"\n  {len(lanes)} lane(s) would be UNPROVEN — a run here cannot speak for: "
              + ", ".join(lanes))


_CLEAN_HOME: Path | None = None


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Run this repository's GitHub Actions gates locally.",
        epilog="A skipped job is always reported: nothing-ran must not look like all-passed. "
               "Exit 1: a job failed. Exit 2: --strict and the verdict is partial or none.",
    )
    ap.add_argument("--repo", type=Path, default=Path.cwd())
    ap.add_argument("--job", action="append", help="Job id or name (repeatable).")
    ap.add_argument("--all", action="store_true",
                    help="Also run jobs whose job-level if: keeps them off this run — "
                         "schedule/dispatch tiers, and conditions it cannot evaluate. "
                         "The tiers a repo deliberately keeps off every push; some "
                         "spend real money. Prints what it is about to run first.")
    ap.add_argument("--list", action="store_true", help="Show the plan and exit.")
    ap.add_argument("--clean-home", action="store_true",
                    help="Run every step with HOME pointed at an empty directory, "
                         "so a step that passes only because this machine has "
                         "~/.claude installed fails here instead of on the runner.")
    ap.add_argument("--json", action="store_true", help="Machine-readable result.")
    # Report-only for one week, then the default (TODO.md names the date):
    # exit 2 changes what /green --json callers see, so it is opt-in first.
    ap.add_argument("--strict", action=argparse.BooleanOptionalAction, default=False,
                    help="Exit 2 when nothing failed but the run is not green: a lane is "
                         "unproven (a job or step the hosted run executes and this runner "
                         "could not prove), or no job ran at all.")
    ap.add_argument("--tail", type=int, default=40, help="Failure output lines (default 40).")
    ap.add_argument("--timeout", type=int, default=900,
                    help="Per-step timeout in seconds (default 900). A hung step is a failure.")
    args = ap.parse_args()

    repo = args.repo.resolve()
    if not (repo / ".github" / "workflows").is_dir():
        print(f"ci-local: no .github/workflows under {repo}")
        return 1

    # An explicitly named job runs even if it is conditional — but it is still
    # planned in full. Clearing only the "conditional" verdict afterwards would
    # now run a conditional job that also uses services:, because the reasoned
    # classes are tested first and the unproven one was never reached.
    plan = collect_jobs(repo, include_conditional=args.all or bool(args.job))

    if args.job:
        wanted = {w.lower() for w in args.job}
        plan = [
            (j, r) for j, r in plan
            if j.id.lower() in wanted or j.name.lower() in wanted
        ]
        if not plan:
            print(f"ci-local: no job matching {args.job}")
            return 1

    if args.all and not args.list:
        # The conditional tier is conditional for a reason. In this repository
        # one of those jobs makes a live billed API call (~$0.05) and another
        # runs `npm audit` against the network; on someone else's repo it could
        # be a deploy. Name them before running, rather than after — and only
        # the ones that survived the --job filter, or the warning names work
        # that is not about to happen.
        conditional = [j for j, r in plan
                       if j.condition and r is None and job_condition(j.condition) != "run"]
        if conditional:
            print("--all also runs these normally-skipped jobs:")
            for job in conditional:
                print(f"  · {job.display}   ({job.workflow})")
            print("  Some conditional tiers spend money or touch the network.\n")

    global _CLEAN_HOME
    if args.clean_home:
        _CLEAN_HOME = Path(tempfile.mkdtemp(prefix="ci-local-home-"))
        (_CLEAN_HOME / ".claude").mkdir(parents=True, exist_ok=True)
        print(f"clean HOME: {_CLEAN_HOME}  (no ~/.claude, no installed skills)")

    if args.list:
        print_plan(repo, plan)
        return 0

    if not shutil.which("bash"):
        print("ci-local: bash not found")
        return 1

    results: list[JobResult] = []
    for job, skip in plan:
        if skip is not None:
            results.append(JobResult(job=job, status="skip", reason=skip.reason,
                                     unproven=skip.unproven))
            continue
        if not args.json:
            print(f"  {job.display}")
        results.append(run_job(job, repo, args.tail, echo=not args.json, timeout=args.timeout))

    ran = [r for r in results if r.status != "skip"]
    failed = [r for r in ran if r.status == "fail"]
    skipped = [r for r in results if r.status == "skip"]
    lanes = unproven_lanes(results)
    # Nothing ran is not a pass: every job was skipped, or none was parsed.
    # It read "pass" when this verdict was first added, and /green read that
    # as green — on a GitHub starter workflow whose steps were never parsed.
    if failed:
        verdict = "fail"
    elif not ran:
        verdict = "none"
    elif lanes:
        verdict = "partial"
    else:
        verdict = "pass"
    exit_code = 1 if failed else (2 if verdict != "pass" and args.strict else 0)

    if args.json:
        json.dump(
            {
                "repo": str(repo),
                "platform": local_platform(),
                # pass | partial | none | fail. PARTIAL: nothing that ran
                # failed, and each lane in `unproven` was not proven here.
                # NONE: no job ran at all. Only `pass` is green.
                "verdict": verdict,
                # /green's report contract asks how long the whole thing took.
                # A stated field with no way to obtain it gets omitted or invented.
                "seconds": round(sum(r.seconds for r in ran), 1),
                # Jobs that ran with no step failing — as before. Those that
                # also skipped an unproven step are named again in `partial`.
                "passed": [r.job.display for r in ran if r.status == "pass"],
                "partial": [r.job.display for r in ran
                            if r.status == "pass" and r.unproven_steps],
                "unproven": [
                    {"job": ln.job.display, "workflow": ln.job.workflow,
                     "step": ln.step, "reason": ln.reason}
                    for ln in lanes
                ],
                "skipped": [{"job": r.job.display, "reason": r.reason, "unproven": r.unproven}
                            for r in skipped],
                "failed": [
                    {
                        "job": r.job.display,
                        "workflow": r.job.workflow,
                        "step": (r.failed_step.name if r.failed_step else ""),
                        "exit_code": (r.failed_step.exit_code if r.failed_step else 0),
                        # e.g. a timeout, or env the step ran without.
                        "reason": (r.failed_step.reason if r.failed_step else ""),
                        "command": (r.failed_step.command if r.failed_step else ""),
                        "output_tail": (r.failed_step.output_tail if r.failed_step else ""),
                    }
                    for r in failed
                ],
            },
            sys.stdout, indent=2,
        )
        sys.stdout.write("\n")
        return exit_code

    print()
    for r in failed:
        step = r.failed_step
        print(f"FAILED  {r.job.display}  ({r.job.workflow})")
        if step:
            print(f"  step: {step.name}   exit {step.exit_code}")
            if step.reason:
                print(f"  note: {step.reason}")
            first = step.command.strip().splitlines()[0] if step.command.strip() else ""
            print(f"  command: {first}")
            if step.output_tail:
                for line in step.output_tail.splitlines():
                    print(f"  | {line}")
        print()

    total_seconds = sum((r.seconds for r in ran), 0.0)
    summary = (
        f"{len(ran) - len(failed)}/{len(ran)} job(s) passed in {total_seconds:.0f}s"
        + ("  [clean HOME]" if _CLEAN_HOME else "")
        + (f", {len(failed)} failed" if failed else "")
    )
    if lanes:
        summary += f", {len(lanes)} lane(s) unproven: " + ", ".join(ln.label for ln in lanes)
    prefix = {"partial": "PARTIAL: ", "none": "NOTHING RAN: "}.get(verdict, "")
    print(f"ci-local: {prefix}{summary}")
    for ln in lanes:
        print(f"  unproven {ln.label}: {ln.reason}")
    for r in skipped:
        if not r.unproven:
            print(f"  skipped {r.job.display}: {r.reason}")
    strict_note = " — exit 2 under --strict." if not args.strict else "."
    if verdict == "partial":
        print("  PARTIAL is not green: the hosted run executes the lanes above and this one "
              "did not prove them. Prove them hosted (or where their services exist)"
              + strict_note)
    elif verdict == "none":
        print("  NOTHING RAN is not green: every job was skipped (reasons above)" + strict_note)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
