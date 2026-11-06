#!/usr/bin/env python3
"""friction-rank.py — harness verdicts, ranked by how many sessions hit them.

Friction is not a defect. A refusal can be a guard doing its job. A family at
the top of this report is where the harness most often told the agent no, or
where the agent most often failed, not where the harness is wrong. Read the
full refusal text and the calls that followed it before calling it a defect,
and test before rewording a refusal: the essay below records a guard whose
added recovery guidance bought nothing (2 calls to recover before, 3 after).

Why this exists
---------------
Gorokh, *The loop learned slowly from corrections and faster from verdicts*
(2026-10-08), one operator's fleet: the correction channel adopted 1 rule in
11 weeks, and an A/B of 7 rules mined from it found 0 helped and 3 hurt (the
author says the 2-net-solve floor used there is not a significance test). The
harness's own verdicts, ranked by how many sessions they recur in, yielded
one-sentence harness repairs. Nothing on Clade's terminal path ranked them:
``failure-detector.sh`` counts consecutive failures inside one session and
keeps nothing, and radar's hand-run ``hook_non_blocking_error`` tally clipped
stderr to 90 characters, which is the defect the essay names: the text the
agent was told is the thing to read. This script never clips a verdict text.

What counts as a verdict
------------------------
Read from Claude Code's own transcripts through ``transcripts.py`` (beside this
file); its docstring holds the record shapes and the counts behind them.

``hook_denial``         a tool result whose text starts ``PreToolUse:`` and that
                        is an error or carries ``toolDenialKind``. Both are
                        required: a ``cat`` of a file that begins with that
                        word is output, not a refusal.
``permission_refusal``  any other result with ``toolDenialKind``: a permission
                        rule, Claude Code's own permission checker, or a person
                        declining at the prompt (``permission-rule`` and
                        ``user-rejected`` are counted per family).
``timeout``             a Bash call that outran its timeout and was moved to
                        the background. Read from ``timedOutAfterMs`` where the
                        Bash result object was recorded, and from the result
                        text's ``Command did not complete within its`` template
                        only where it was not (nearly every Workflow agent
                        success): where the object is there, it is the answer.
``is_error``            any other result flagged ``is_error``. A failing
                        command's exit status lands here, and so does Claude
                        Code's own ``<tool_use_error>Blocked:`` (a bare
                        ``sleep``), which is why ``Bash:sleep`` can rank high.
``retry``               a call identical to the call just before it (same
                        tool, same input, same agent) when that call drew one
                        of the four verdicts above and the call was issued
                        after that verdict arrived: the agent was told no and
                        asked again unchanged. An identical call after a
                        success is a poll, and two identical calls sent in one
                        parallel batch were both sent before either answer;
                        neither is counted. The text shown is the verdict it
                        retried past.
``hook_non_blocking_error``  a hook whose output Claude Code rejected or that
                        failed without blocking. The hook still ran and its
                        suite may be green; this attachment is the only record
                        that it delivered nothing. The text is its full stderr.

Not counted: ``hook_blocking_error`` (a PostToolUse or Stop hook blocking on
purpose), ``hook_cancelled``, and a persisted (oversized) output.

Families, ranking and held-out weeks
------------------------------------
A family is the verdict class plus the tool, and for Bash the command's leading
tokens: heredoc bodies are stripped first (``transcripts.strip_heredocs``), the
rest is cut with ``shlex``, and what sets the scene is skipped: a leading ``cd
DIR &&`` (and ``set``, ``export``, ``source``, ``pushd`` up to their
separator), ``(``, ``{`` and ``!``, ``VAR=value`` assignments, and
``sudo``/``env``/``nohup``/``time``/``timeout N`` with their options. A loop
keeps its keyword (``Bash:for``, ``Bash:until``): the loop is the command.
Then ``git commit`` keeps its subcommand (``_SUBCOMMANDS``), ``python3
x/tool.py`` its script's basename, ``python3 -m pytest`` its module, ``bash -c``
its flag (so does ``bash -lc``, and ``perl -ne`` is ``perl -e``), and anything
else its command word alone. An option that takes a value takes the next word
with it (``_VALUE_OPTIONS``), so that word is never read as the command or the
subcommand: ``sudo -u postgres psql`` is ``Bash:psql``, ``kubectl -n web get``
is ``Bash:kubectl get``. A command shlex cannot cut is
``Bash:<unparsed>``, never a guess. The family is the FIRST command: a guard
that objects to an ``rm`` after ``git status &&`` files it under ``Bash:git
status``, and the refusal text says why. The "refusals by first sentence"
table regroups denials and hook errors by what they said, across families.

Ranked by distinct sessions, then by count: a family that fires once in each of
14 sessions outranks one that fires 40 times in one session, because one bad
session can retry anything 40 times. A subagent's session is its lead
session's. ISO weeks split the window: the last ``--holdout-weeks`` (default 1,
counting the week ``now`` falls in) are held out, the rest are discovery. The
ranking uses discovery only, and the held-out columns say whether a family
recurred in weeks that did not choose it. A family seen only in held-out weeks
ranks after every family seen in discovery. The report prints how many days the
held-out weeks span and warns below 7: early in a week the current one holds
only hours, and a family missing from hours of data is not shown to be a
burst. ``radar-cron.sh`` runs on Monday morning, so it passes
``--holdout-weeks 2``.

Each family shows its most common verdict text in full (between equally
common texts, the most recent), and that text's latest occurrence: its
provenance (session, file, record index) and the 3 calls after it.

Main thread only by default: a Workflow agent's denials are a script's, and
one fan-out can repeat one refusal a hundred times. ``--subagents`` adds
subagent transcripts. A verdict with no timestamp cannot be placed in a week
and is counted as undated, not ranked.

What it cannot see
------------------
- Whether a verdict was right. Friction is the input to a judgement, not one.
- A denial that left no transcript: a session deleted by Claude Code's 30-day
  cleanup, or another agent runtime (Codex and Kimi are not read).
- A timeout or interruption in a Workflow agent whose result text does not use
  the template (no interruption marker is known; see ``transcripts.py``).

Stdlib only, on purpose: the syntax-check CI job installs no dependencies.
Report-only: it exits 0 whatever it finds, and 1 only when nothing could be
read (no transcript in the window, or none that would open), which it says as
NOT MEASURED rather than as a clean zero. A transcript that will not open is
named in the report and counted in neither transcripts nor sessions.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import io
import json
import os
import re
import shlex
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

import transcripts as tr

CAVEAT = ("Friction is not a defect: a refusal can be a guard doing its job. A family ranked first is where "
          "the harness most often said no, not where it is wrong. Read the full text and the next calls before "
          "changing anything, and test a reworded refusal before keeping it.")

# ─── Verdict classes ────────────────────────────────────────────────────────

HOOK_DENIAL = "hook_denial"
PERMISSION = "permission_refusal"
TIMEOUT = "timeout"
IS_ERROR = "is_error"
RETRY = "retry"
HOOK_ERROR = "hook_non_blocking_error"
# The classes whose text is a refusal someone wrote, regrouped by first sentence.
_REFUSALS = (HOOK_DENIAL, PERMISSION, HOOK_ERROR)

_TIMEOUT_TEMPLATE = "Command did not complete within its"
_NEXT_CALLS = 3
# Fewer held-out days than this, and a family missing from them is not shown to be a burst.
_SHORT_HOLDOUT_DAYS = 7


def result_class(event: tr.ToolEvent) -> str | None:
    """The verdict a tool result carries, or None for a success or a call with no result."""

    if event.result is None:
        return None
    text = event.result
    refused = bool(event.is_error) or event.denial_kind is not None
    if refused and text.startswith("PreToolUse:"):
        return HOOK_DENIAL
    if event.denial_kind is not None:
        return PERMISSION
    if event.timed_out_ms is not None:
        return TIMEOUT
    # ``interrupted`` is set exactly when a Bash result object was read; then the
    # object answered "not a timeout", and output that merely starts with the
    # template (a cat of a log) is not one.
    if event.interrupted is None and not event.is_error and text.startswith(_TIMEOUT_TEMPLATE):
        return TIMEOUT
    if event.is_error:
        return IS_ERROR
    return None


def _same_call(a: tr.ToolEvent, b: tr.ToolEvent) -> bool:
    return (a.name, a.agent_id, json.dumps(a.input, sort_keys=True)) == \
        (b.name, b.agent_id, json.dumps(b.input, sort_keys=True))


def first_sentence(text: str) -> str:
    """The first line of ``text``, cut after its first ". ": what a refusal says, without its echo of the command."""

    line = text.strip().split("\n", 1)[0].strip()
    cut = line.find(". ")
    return line[:cut + 1] if cut != -1 else line


# ─── Families ───────────────────────────────────────────────────────────────

# Commands whose first word argument is a subcommand worth keeping apart:
# `git commit` and `git push` are different frictions.
_SUBCOMMANDS = frozenset({
    "apt", "apt-get", "aws", "brew", "cargo", "claude", "codex", "conda", "docker", "gcloud", "gh", "git",
    "go", "helm", "kubectl", "make", "npm", "npx", "pip", "pip3", "pm2", "pnpm", "poetry", "rustup",
    "systemctl", "terraform", "tmux", "uv", "yarn",
})
_INTERPRETERS = frozenset({"bash", "bun", "deno", "node", "perl", "python", "python3", "ruby", "sh", "tsx", "zsh"})
# Prefixes that run the next word: skipped, with their options (and timeout's duration).
_WRAPPERS = frozenset({"command", "env", "exec", "nice", "nohup", "sudo", "time", "timeout"})
_SEPARATORS = frozenset({"&&", "||", ";", "|", "&", ";;", "|&"})
# Statements that set the scene for the command after them, skipped up to the next separator.
_PRELUDES = frozenset({"cd", "pushd", "set", "export", "source", "."})
# A subshell, a group or a negation: the command is inside.
_OPENERS = frozenset({"(", "{", "!"})
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_WORD = re.compile(r"^[a-z][a-z0-9_-]*$")
_CLUSTER = re.compile(r"^-[A-Za-z]{2,}$")
# Options that take the next word as their value: before the wrapped command
# (`sudo -u postgres psql`), before the subcommand (`kubectl -n web get`), or
# before an interpreter's script (`bash -o pipefail -c`). That word is neither
# the command nor the subcommand. `--opt=value` is one token and needs no entry.
_VALUE_OPTIONS: dict[str, frozenset[str]] = {name: frozenset(opts.split()) for name, opts in {
    "sudo": "-u -g -C -D -h -p -r -t -T -U --user --group --chdir --host --prompt --role --type --other-user "
            "--close-from --command-timeout",
    "env": "-u -C -P --unset --chdir", "nice": "-n --adjustment", "timeout": "-s -k --signal --kill-after",
    "time": "-f -o --format --output", "exec": "-a",
    "git": "-C -c --git-dir --work-tree --namespace --config-env",
    "docker": "-c -H -l --context --host --config --log-level", "gh": "-R --repo --hostname",
    "kubectl": "-n -s --namespace --context --kubeconfig --cluster --server --user",
    "helm": "-n --namespace --kube-context --kubeconfig",
    "make": "-C -f -I -o -W --directory --file --makefile --include-dir",
    "npm": "-w --prefix --workspace", "pnpm": "-C -F --dir --filter", "yarn": "--cwd",
    "cargo": "-C -Z --manifest-path --config --color", "go": "-C", "uv": "-p --directory --project --python",
    "poetry": "-C -P --directory --project", "tmux": "-L -S -f",
    "systemctl": "-H -M -t -p -n -o -s --host --machine --type --property --lines --output --signal",
    "aws": "--profile --region --output --endpoint-url", "gcloud": "--project --account --configuration --format",
    "codex": "-m -c -C -s -a -p --model --config --cd --sandbox --ask-for-approval --profile",
    "claude": "--model --permission-mode --output-format --settings --mcp-config",
    "bash": "-o -O +o +O --rcfile --init-file", "sh": "-o +o", "zsh": "-o +o", "python": "-W -X", "python3": "-W -X",
    "node": "-r --require --import --loader",
}.items()}
# The letter that makes an interpreter run inline text, inside a flag cluster too (`bash -lc`, `perl -ne`).
_INLINE_LETTER = {"bash": "c", "sh": "c", "zsh": "c", "perl": "e", "ruby": "e", "node": "e", "bun": "e", "tsx": "e"}


def _tokens(command: str) -> list[str] | None:
    """Shell tokens of ``command`` with heredoc bodies and comment lines removed; None if shlex cannot cut it."""

    text = tr.strip_heredocs(command).replace("\\\n", " ")
    lines = [line for line in text.split("\n") if not line.lstrip().startswith("#")]
    lexer = shlex.shlex(" ; ".join(lines), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        return None


def bash_family(command: str) -> str:
    """``Bash:`` plus the leading tokens of the first command (module docstring: Families)."""

    tokens = _tokens(command)
    if tokens is None:
        return "Bash:<unparsed>"
    i, n = 0, len(tokens)
    while i < n:
        tok = tokens[i]
        if tok in _SEPARATORS or tok in _OPENERS:
            i += 1
        elif tok in _PRELUDES:
            j = i + 1
            while j < n and tokens[j] not in _SEPARATORS:
                j += 1
            if j >= n:
                break  # a bare `cd DIR` is the command itself
            i = j + 1
        elif _ASSIGNMENT.match(tok):
            i += 1
        elif tok in _WRAPPERS:
            takes_value = _VALUE_OPTIONS.get(tok, frozenset())
            i += 1
            while i < n and tokens[i].startswith("-"):
                i += 2 if tokens[i] in takes_value else 1
            if tok == "timeout" and i < n:
                i += 1  # the duration
        else:
            break
    if i >= n:
        return "Bash:<empty>"
    name = os.path.basename(tokens[i]) or tokens[i]
    rest = []
    for tok in tokens[i + 1:]:
        if tok in _SEPARATORS:
            break
        rest.append(tok)
    if name in _SUBCOMMANDS:
        sub = _subcommand(name, rest)
        return f"Bash:{name} {sub}" if sub else f"Bash:{name}"
    if name in _INTERPRETERS:
        takes_value = _VALUE_OPTIONS.get(name, frozenset())
        at = 0
        while at < len(rest):
            tok = rest[at]
            flag = _inline_flag(name, tok)
            if flag == "-m":
                module = rest[at + 1] if at + 1 < len(rest) else ""
                return f"Bash:{name} -m {module}".rstrip()
            if flag or tok == "-":
                return f"Bash:{name} {flag or tok}"
            if tok in takes_value:
                at += 2
                continue
            if not tok.startswith(("-", "+")):
                return f"Bash:{name} {os.path.basename(tok) or tok}"
            at += 1
    return f"Bash:{name}"


def _subcommand(name: str, rest: list[str]) -> str | None:
    """The first plain word after ``name``, never the value of a global option before it (``git -C repo status``)."""

    skip = False
    for tok in rest:
        if skip:
            skip = False
        elif tok in _VALUE_OPTIONS.get(name, ()):
            skip = True
        elif _WORD.match(tok):
            return tok
    return None


def _inline_flag(name: str, tok: str) -> str | None:
    """``-c``, ``-e`` or ``-m`` when ``tok`` makes interpreter ``name`` run inline text or a module, else None."""

    if tok in ("-c", "-e", "-m"):
        return tok
    if not _CLUSTER.match(tok):
        return None
    if name in ("python", "python3"):  # python reads the text or the module after the cluster's LAST letter
        return f"-{tok[-1]}" if tok[-1] in "cm" else None
    letter = _INLINE_LETTER.get(name)
    return f"-{letter}" if letter and letter in tok[1:] else None


def tool_family(event: tr.ToolEvent) -> str:
    command = event.input.get("command")
    if event.name == "Bash" and isinstance(command, str):
        return bash_family(command)
    return event.name or "<unnamed>"


def hook_family(att: tr.HookAttachment) -> str:
    """``hook:<hookName> <script>``: the script's basename, or the command itself for a prompt hook."""

    command = (att.command or "").strip()
    try:
        words = shlex.split(command)
    except ValueError:
        words = command.split()
    script = next((w for w in words if "/" in w or w.endswith((".sh", ".py", ".js", ".mjs", ".ts"))), None)
    label = os.path.basename(script) if script else command
    return f"hook:{att.hook_name or '?'} {label}".rstrip()


# ─── Scanning one transcript ────────────────────────────────────────────────


def _next_calls(events: list[tr.ToolEvent], families: list[str], labels: list[list[str]],
                start: int) -> list[dict[str, str]]:
    rows = []
    for j in range(start, min(start + _NEXT_CALLS, len(events))):
        verdict = "+".join(labels[j]) or ("ok" if events[j].result is not None else "no result")
        rows.append({"tool": events[j].name, "family": families[j], "verdict": verdict})
    return rows


def scan_transcript(path: Path, tally: dict[str, int]) -> list[dict[str, Any]]:
    """Every verdict in one transcript, with its provenance and the calls that followed it."""

    records = list(tr.iter_records(path, tally))
    events = tr.tool_events(records, tally)
    tally["tool_calls"] = tally.get("tool_calls", 0) + len(events)
    session = tr.session_id(path)
    classes = [result_class(e) for e in events]
    families = [tool_family(e) for e in events]
    labels: list[list[str]] = []
    for i, event in enumerate(events):
        found: list[str] = []
        if i and classes[i - 1] and _same_call(events[i - 1], event) \
                and event.index > (events[i - 1].result_index or 0):
            found.append(RETRY)
        own = classes[i]
        if own:
            found.append(own)
        labels.append(found)

    def occurrence(cls: str, family: str, record: int | None, when: object, text: str,
                   after: int, denial: str | None = None) -> dict[str, Any]:
        return {"class": cls, "family": family, "session": session, "file": str(path), "record": record,
                "timestamp": when if isinstance(when, str) else None, "text": text, "denial_kind": denial,
                "next_calls": _next_calls(events, families, labels, after)}

    found_here: list[dict[str, Any]] = []
    for i, event in enumerate(events):
        for cls in labels[i]:
            if cls == RETRY:
                prior = events[i - 1]
                found_here.append(occurrence(RETRY, families[i], event.index, event.timestamp,
                                             prior.result or "", i + 1, prior.denial_kind))
            else:
                found_here.append(occurrence(cls, families[i], event.result_index,
                                             event.result_timestamp or event.timestamp, event.result or "",
                                             i + 1, event.denial_kind))
    for att in tr.attachments(records):
        if att.kind == HOOK_ERROR:
            text = att.stderr or att.stdout or "(no stderr or stdout recorded)"
            after = next((j for j, e in enumerate(events) if e.index > att.index), len(events))
            found_here.append(occurrence(HOOK_ERROR, hook_family(att), att.index, att.timestamp, text, after))
    return found_here


# ─── Ranking ────────────────────────────────────────────────────────────────


def _parse_when(stamp: object) -> datetime.datetime | None:
    if not isinstance(stamp, str) or not stamp:
        return None
    try:
        when = datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=datetime.timezone.utc)


def iso_week(when: datetime.datetime) -> str:
    year, week, _ = when.astimezone(datetime.timezone.utc).isocalendar()
    return f"{year}-W{week:02d}"


def _week_start(when: datetime.datetime) -> datetime.datetime:
    """Monday 00:00 UTC of the ISO week ``when`` falls in."""

    utc = when.astimezone(datetime.timezone.utc)
    return (utc - datetime.timedelta(days=utc.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


def _split() -> dict[str, Any]:
    return {"sessions": set(), "count": 0}


def _rank_key(group: dict[str, Any]) -> tuple:
    disc, held = group["discovery"], group["held_out"]
    return (-len(disc["sessions"]), -disc["count"], -len(held["sessions"]), -held["count"],
            group["class"], group.get("family") or group.get("sentence") or "")


def _latest(occ: dict[str, Any]) -> dict[str, Any]:
    return {key: occ[key] for key in ("session", "file", "record", "timestamp", "next_calls")}


def rank(occurrences: list[dict[str, Any]], start: datetime.datetime, now: datetime.datetime,
         holdout_weeks: int, counts: dict[str, int]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict]:
    """Families and refusal sentences, ranked; plus which ISO weeks were discovery and which held out."""

    held_weeks = {iso_week(now - datetime.timedelta(days=7 * k)) for k in range(holdout_weeks)}
    held_start = max(_week_start(now) - datetime.timedelta(weeks=holdout_weeks - 1), start)
    window_weeks = {iso_week(now)}
    day = start
    while day < now:
        window_weeks.add(iso_week(day))
        day += datetime.timedelta(days=1)
    families: dict[tuple[str, str], dict[str, Any]] = {}
    sentences: dict[tuple[str, str], dict[str, Any]] = {}
    for occ in occurrences:
        when = _parse_when(occ["timestamp"])
        if when is None:
            counts["undated"] += 1
            continue
        if when < start or when > now:
            counts["outside_window"] += 1
            continue
        week = iso_week(when)
        occ["week"] = week
        occ["at"] = when.timestamp()
        part = "held_out" if week in held_weeks else "discovery"
        counts["verdicts"] += 1
        group = families.setdefault((occ["class"], occ["family"]), {
            "class": occ["class"], "family": occ["family"], "discovery": _split(), "held_out": _split(),
            "denial_kinds": {}, "texts": {}, "occurrences": []})
        group[part]["sessions"].add(occ["session"])
        group[part]["count"] += 1
        group["occurrences"].append(occ)
        if occ["denial_kind"]:
            group["denial_kinds"][occ["denial_kind"]] = group["denial_kinds"].get(occ["denial_kind"], 0) + 1
        text = group["texts"].setdefault(occ["text"], {"count": 0, "sessions": set(), "latest": occ})
        text["count"] += 1
        text["sessions"].add(occ["session"])
        if occ["at"] >= text["latest"]["at"]:
            text["latest"] = occ
        if occ["class"] in _REFUSALS:
            said = first_sentence(occ["text"])
            sentence = sentences.setdefault((occ["class"], said), {
                "class": occ["class"], "sentence": said, "discovery": _split(), "held_out": _split(),
                "families": set(), "latest": occ})
            sentence[part]["sessions"].add(occ["session"])
            sentence[part]["count"] += 1
            sentence["families"].add(occ["family"])
            if occ["at"] >= sentence["latest"]["at"]:
                sentence["latest"] = occ

    def finish(group: dict[str, Any]) -> None:
        for part in ("discovery", "held_out"):
            group[part] = {"sessions": len(group[part]["sessions"]), "count": group[part]["count"]}

    ranked_families = sorted(families.values(), key=_rank_key)
    for at, group in enumerate(ranked_families, 1):
        # Between equally common texts the most recent leads, so a family of unique texts shows its newest one,
        # not whichever the oldest file happened to hold.
        texts = sorted(group["texts"].items(), key=lambda item: (-item[1]["count"], -len(item[1]["sessions"]),
                                                                 -item[1]["latest"]["at"]))
        group["rank"] = at
        group["distinct_texts"] = len(texts)
        group["texts"] = [{"text": text, "count": info["count"], "sessions": len(info["sessions"]),
                           "latest": _latest(info["latest"])} for text, info in texts[:5]]
        group["occurrences"] = [{key: occ[key] for key in ("session", "file", "record", "timestamp", "week")}
                                for occ in group["occurrences"]]
        finish(group)
    ranked_sentences = sorted(sentences.values(), key=_rank_key)
    for at, sentence in enumerate(ranked_sentences, 1):
        sentence["rank"] = at
        sentence["families"] = sorted(sentence["families"])
        sentence["latest"] = _latest(sentence["latest"])
        finish(sentence)
    weeks = {"held_out": sorted(held_weeks),
             "discovery": sorted(week for week in window_weeks if week not in held_weeks),
             "held_out_days": round((now - held_start).total_seconds() / 86400, 1)}
    return ranked_families, ranked_sentences, weeks


# ─── Report ─────────────────────────────────────────────────────────────────


def _indent(text: str, pad: str = "      ") -> str:
    return "\n".join(pad + line for line in text.split("\n"))


def _calls(rows: list[dict[str, str]]) -> str:
    return "; ".join(f"{row['family']} {row['verdict']}" for row in rows) or "(none: the transcript ends)"


def print_report(report: dict[str, Any], top: int) -> None:
    read, window, weeks = report["read"], report["window"], report["weeks"]
    print("friction-rank — harness verdicts ranked by distinct sessions")
    print(CAVEAT)
    print()
    print(f"Window: {window['start'][:10]} → {window['end'][:10]} ({window['days']:g} days), {report['scope']}; "
          f"{read['transcripts']} transcripts, {read['sessions']} sessions, {read['tool_calls']} tool calls.")
    held_days = weeks["held_out_days"]
    print(f"Discovery weeks: {', '.join(weeks['discovery']) or 'none'}; held out: {', '.join(weeks['held_out'])} "
          f"({held_days:g} days). Ranked on discovery; held out says whether a family recurred in weeks that did not "
          "choose it.")
    if held_days < _SHORT_HOLDOUT_DAYS:
        print(f"The held-out weeks span only {held_days:g} days: a family missing from them is not shown to be a "
              "burst. --holdout-weeks 2 adds the week before.")
    skipped = [f"{read[key]} {label}" for key, label in (
        ("undated", "undated verdicts (not ranked)"), ("outside_window", "verdicts before the window"),
        ("malformed", "malformed lines"), ("truncated", "truncated last lines"))
        if read.get(key)]
    if read["unreadable"]:
        skipped.append(f"{len(read['unreadable'])} unreadable transcripts")
    print(f"Verdicts ranked: {read['verdicts']}" + (f"; also {', '.join(skipped)}." if skipped else "."))
    families = report["families"]
    if not families:
        print("\nNo verdicts in the window.")
        return
    print(f"\n  #  sessions disc/held  count disc/held  class / family")
    for group in families[:top]:
        disc, held = group["discovery"], group["held_out"]
        print(f"{group['rank']:>3}  {disc['sessions']:>8} / {held['sessions']:<5}  {disc['count']:>5} / {held['count']:<5}"
              f"  {group['class']} · {group['family']}")
    if len(families) > top:
        print(f"  … {len(families) - top} more families (--top, or --json for all)")
    for group in families[:top]:
        head = group["texts"][0]
        latest = head["latest"]
        kinds = ", ".join(f"{k} {n}" for k, n in sorted(group["denial_kinds"].items()))
        print(f"\n── {group['rank']}. {group['class']} · {group['family']}" + (f"  ({kinds})" if kinds else ""))
        print(f"   {group['distinct_texts']} distinct texts; the most common, ×{head['count']} in "
              f"{head['sessions']} sessions, in full:")
        print(_indent(head["text"]))
        print(f"   this text's latest occurrence: session {latest['session']}, {latest['file']}, "
              f"record {latest['record']}, {latest['timestamp']}")
        print(f"   the next {_NEXT_CALLS} calls after it: {_calls(latest['next_calls'])}")
    refusals = report["refusals"]
    if refusals:
        print("\nRefusals by first sentence (hook denials, permission refusals, hook errors), across families:")
        for sentence in refusals[:top]:
            disc, held = sentence["discovery"], sentence["held_out"]
            print(f"{sentence['rank']:>3}  {disc['sessions']:>3} / {held['sessions']} sessions, "
                  f"{disc['count']} / {held['count']} times  {sentence['class']}: {sentence['sentence']}")
            print(f"       families: {', '.join(sentence['families'])}")


def _unmeasured(reason: str, as_json: bool) -> int:
    if as_json:
        json.dump({"measured": False, "reason": reason, "caveat": CAVEAT}, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"friction-rank: NOT MEASURED — {reason}")
    return 1


# ─── Self-test ──────────────────────────────────────────────────────────────
# Through main(), the entry point the CLI uses, on synthetic transcripts under a
# temporary --root with --now pinned to Friday 2026-11-06, so 2026-W45 is held
# out and 2026-W44 is discovery. Every guard has a control that fires and one
# that must not; their mutations are in orchestrator/tests/
# can_fire_friction_rank.py, which test_self_tests_can_fire.py runs.

_NOW = "2026-11-06T12:00:00Z"
_DISC, _HELD, _OLD = "2026-10-28T10:00:00Z", "2026-11-04T10:00:00Z", "2026-09-20T10:00:00Z"
_RM = ("PreToolUse:Bash hook error: Catastrophic rm -rf blocked on system/home directory. Command: {}. "
       "If intentional, run it manually in your terminal; this guard does not distinguish a heredoc body "
       "or a quoted grep pattern from a command, which is why the full text matters here.")
_HOOK_STDERR = ("Hook JSON output validation failed — hookSpecificOutput is missing required field "
                "\"hookEventName\"\n\nThe hook's output was: {\"hookSpecificOutput\": {}}\n")


class _Transcript:
    """A synthetic transcript: Bash calls, their results, and attachments, in order."""

    def __init__(self, when: str | None, sidechain: bool = False) -> None:
        self.records: list[dict[str, Any]] = []
        self.when = when
        self.sidechain = sidechain
        self.ids = 0

    def _stamp(self, record: dict[str, Any]) -> dict[str, Any]:
        if self.when is not None:
            record["timestamp"] = self.when
        if self.sidechain:
            record["agentId"] = "a1"
        self.records.append(record)
        return record

    def bash(self, command: str, text: str = "ok", error: bool = False, denial: str | None = None,
             timed_out: bool = False, object_: bool = True) -> int:
        """One call and its result; returns the result's record index."""
        self.ids += 1
        call_id = f"toolu_{self.ids:03d}"
        self._stamp({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": call_id, "name": "Bash", "input": {"command": command}}]}})
        result: dict[str, Any] = {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": call_id, "content": text, "is_error": error}]}}
        if error or denial:
            result["toolUseResult"] = "Error: " + text
            if denial:
                result["toolDenialKind"] = denial
        elif object_:
            result["toolUseResult"] = {"stdout": text, "stderr": "", "interrupted": False}
            if timed_out:
                result["toolUseResult"].update(timedOutAfterMs=120000, backgroundTaskId="b1")
        self._stamp(result)
        return len(self.records) - 1

    def parallel(self, command: str, text: str) -> None:
        """Two identical calls sent in one batch, then their two error results."""
        ids = []
        for _ in range(2):
            self.ids += 1
            ids.append(f"toolu_{self.ids:03d}")
            self._stamp({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": ids[-1], "name": "Bash", "input": {"command": command}}]}})
        for call_id in ids:
            self._stamp({"type": "user", "toolUseResult": "Error: " + text, "message": {"content": [
                {"type": "tool_result", "tool_use_id": call_id, "content": text, "is_error": True}]}})

    def hook(self, kind: str, stderr: str) -> None:
        self._stamp({"type": "attachment", "attachment": {
            "type": kind, "hookName": "PostToolUse:Edit", "hookEvent": "PostToolUse", "toolUseID": "toolu_x",
            "command": "~/.claude/hooks/skill-suggest.sh", "stderr": stderr, "stdout": "", "exitCode": 0}})

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in self.records), encoding="utf-8")


def _blocked(seconds: int) -> str:
    return f"<tool_use_error>Blocked: sleep {seconds} followed by: tail log. To wait for a condition, use Monitor."


def _build_fixture(root: Path) -> dict[str, Any]:
    proj = root / "-proj"
    s1 = _Transcript(_DISC)
    rm_record = s1.bash("cd /repo && rm -rf /x", _RM.format("cd /repo && rm -rf /x"), error=True,
                        denial="permission-rule")
    s1.bash("rm -r /x")
    s1.bash("ls /x")
    s1.bash("echo done")
    s1.bash("pwd")
    s1.bash("sleep 60", _blocked(60), error=True)
    s1.hook("hook_non_blocking_error", _HOOK_STDERR)
    s1.hook("hook_success", "")
    s1.bash("git commit -m 'x'", "Exit code 1\nnothing to commit", error=True)
    s1.write(proj / "s1.jsonl")

    s2 = _Transcript(_DISC)
    s2.bash("ssh host1 'ls'", _RM.format("ssh host1 'ls'"), error=True, denial="permission-rule")
    s2.bash("sleep 60", _blocked(60), error=True)
    s2.when = "2026-10-28T10:30:00Z"  # the later of the two hook errors: the report's next calls are this one's
    s2.hook("hook_non_blocking_error", _HOOK_STDERR)
    s2.bash("git push", "Exit code 1\nrejected", error=True)
    s2.parallel("npm run lint", "Exit code 1\nlint")
    s2.write(proj / "s2.jsonl")

    s3 = _Transcript(_HELD)
    s3.bash("sleep 30", _blocked(30), error=True)
    s3.bash("cat notes.txt", "PreToolUse:Bash hook error: a note quoting a refusal, read back by cat")
    s3.bash("tail -n 3 old.log", _TIMEOUT_TEMPLATE + " timeout: a log line quoting it, read by tail")
    s3.bash("rm -rf /y", _RM.format("rm -rf /y"), error=True, denial="permission-rule")
    s3.write(proj / "s3.jsonl")

    s4 = _Transcript(_DISC)
    pytest_record = -1
    for minute, part in enumerate("abcd"):  # one text four times, a minute apart: its latest is the last
        s4.when = f"2026-10-28T09:0{minute}:00Z"
        pytest_record = s4.bash(f"python3 -m pytest tests/{part} -q", "Exit code 1\n1 failed", error=True)
    s4.when = _DISC
    s4.bash("npm test", _TIMEOUT_TEMPLATE + " 2m timeout and was moved to the background.", timed_out=True)
    s4.bash("curl https://example.invalid", "The user doesn't want to proceed with this tool use.",
            error=True, denial="user-rejected")
    s4.bash("make test", "Exit code 2\nFAIL", error=True)
    s4.bash("make test", "Exit code 2\nFAIL again", error=True)  # the retry's own result is not its text
    s4.bash("tail -n 5 log.txt", "line")
    s4.bash("tail -n 5 log.txt", "line")
    s4.bash("make lint", "Exit code 2\nlint", error=True)
    s4.bash("make lint FIX=1", "fixed")
    s4.bash("cd /repo && cat > notes.md <<'EOF'\nit's a note\nEOF", "Exit code 1\nPermission denied", error=True)
    s4.bash("python3 configs/scripts/tool.py --check", "Exit code 1\ndrift", error=True)
    s4.when = "2026-10-28T11:00:00Z"  # two texts once each, in file order: the newer one is shown
    s4.bash("ruff check a.py", "Exit code 1\nE501 a.py", error=True)
    s4.when = "2026-10-28T11:10:00Z"
    ruff_record = s4.bash("ruff check b.py", "Exit code 1\nF401 b.py", error=True)
    s4.write(proj / "s4.jsonl")
    (proj / "s9.jsonl").mkdir()  # listed as a transcript, and open() refuses it on every platform

    old = _Transcript(_OLD)
    old.bash("docker build .", "Exit code 1\nno Dockerfile", error=True)
    old.write(proj / "s5.jsonl")
    undated = _Transcript(None)
    undated.bash("terraform plan", "Exit code 1\nno state", error=True)
    undated.write(proj / "s6.jsonl")

    agent = _Transcript(_DISC, sidechain=True)
    agent.bash("go test ./...", "Exit code 1\nFAIL", error=True)
    agent.bash("sleep 60", _blocked(60), error=True)
    agent.bash("cargo build", _TIMEOUT_TEMPLATE + " 2m timeout and was moved to the background.", object_=False)
    agent.write(proj / "s1" / "subagents" / "agent-a1.jsonl")
    return {"rm_record": rm_record, "rm_file": str(proj / "s1.jsonl"), "rm_text": _RM.format("cd /repo && rm -rf /x"),
            "pytest_record": pytest_record, "ruff_record": ruff_record}


def self_test(entry: Callable[[list[str]], int]) -> int:
    failures: list[str] = []

    def run(args: list[str]) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = entry(args)
        return code, out.getvalue()

    def run_json(what: str, args: list[str]) -> dict[str, Any]:
        code, text = run([*args, "--json"])
        if code != 0:
            failures.append(f"{what}: exit {code}")
        try:
            return json.loads(text)
        except ValueError:
            failures.append(f"{what}: --json printed no JSON: {text[-300:]}")
            return {}

    def expect(what: str, got: object, want: object) -> None:
        if got != want:
            failures.append(f"{what}: got {got!r}, want {want!r}")

    def fams(report: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
        return {(g["class"], g["family"]): g for g in report.get("families", [])}

    def split(group: dict[str, Any] | None) -> tuple | None:
        if group is None:
            return None
        return (group["discovery"]["sessions"], group["discovery"]["count"],
                group["held_out"]["sessions"], group["held_out"]["count"])

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "projects"
        fixture = _build_fixture(root)
        base = ["--root", str(root), "--now", _NOW]
        report = run_json("the default run", base)
        found = fams(report)
        hook = "hook:PostToolUse:Edit skill-suggest.sh"
        expect("the window's weeks", report.get("weeks"),
               {"discovery": ["2026-W41", "2026-W42", "2026-W43", "2026-W44"], "held_out": ["2026-W45"],
                "held_out_days": 4.5})
        expect("the families found, main thread, --since 30", sorted(found), sorted([
            (HOOK_DENIAL, "Bash:rm"), (HOOK_DENIAL, "Bash:ssh"), (IS_ERROR, "Bash:sleep"),
            (IS_ERROR, "Bash:git commit"), (IS_ERROR, "Bash:git push"), (IS_ERROR, "Bash:python3 -m pytest"),
            (IS_ERROR, "Bash:make test"), (IS_ERROR, "Bash:make lint"), (IS_ERROR, "Bash:cat"),
            (IS_ERROR, "Bash:python3 tool.py"), (IS_ERROR, "Bash:npm run"), (TIMEOUT, "Bash:npm test"),
            (PERMISSION, "Bash:curl"), (IS_ERROR, "Bash:ruff"),
            (RETRY, "Bash:make test"), (HOOK_ERROR, hook)]))
        expect("the order: sessions first, then count", [(g["class"], g["family"]) for g in
                                                          report.get("families", [])[:4]],
               [(IS_ERROR, "Bash:sleep"), (HOOK_ERROR, hook), (IS_ERROR, "Bash:python3 -m pytest"),
                (IS_ERROR, "Bash:make test")])
        expect("Bash:sleep discovery/held-out sessions and counts", split(found.get((IS_ERROR, "Bash:sleep"))),
               (2, 2, 1, 1))
        expect("Bash:rm discovery/held-out", split(found.get((HOOK_DENIAL, "Bash:rm"))), (1, 1, 1, 1))
        expect("the retry is counted once", split(found.get((RETRY, "Bash:make test"))), (1, 1, 0, 0))
        expect("permission refusals by kind", (found.get((PERMISSION, "Bash:curl")) or {}).get("denial_kinds"),
               {"user-rejected": 1})
        read = report.get("read", {})
        expect("undated verdicts", read.get("undated"), 1)
        expect("verdicts before the window", read.get("outside_window"), 1)
        expect("an unreadable transcript is named, and counted in neither transcripts nor sessions",
               ([u.split(": ")[0].endswith("s9.jsonl") for u in read.get("unreadable", [])],
                read.get("transcripts"), read.get("sessions")), ([True], 6, 6))
        rm = found.get((HOOK_DENIAL, "Bash:rm")) or {"texts": [{}]}
        latest_disc: dict[str, Any] = next((t for t in rm["texts"] if t.get("text") == fixture["rm_text"]), {})
        expect("the refusal text, in full", bool(latest_disc), True)
        prov = latest_disc.get("latest", {})
        expect("provenance", (prov.get("session"), prov.get("file"), prov.get("record")),
               ("s1", fixture["rm_file"], fixture["rm_record"]))
        expect("the next calls", [c["family"] for c in prov.get("next_calls", [])],
               ["Bash:rm", "Bash:ls", "Bash:echo"])
        hook_head = (found.get((HOOK_ERROR, hook)) or {"texts": [{}]})["texts"][0]
        expect("the hook's stderr, in full", hook_head.get("text"), _HOOK_STDERR)
        hook_latest = hook_head.get("latest", {})
        expect("a hook error's next calls are the ones after it",
               (hook_latest.get("session"), [c["family"] for c in hook_latest.get("next_calls", [])]),
               ("s2", ["Bash:git push", "Bash:npm run", "Bash:npm run"]))
        pytest_latest = ((found.get((IS_ERROR, "Bash:python3 -m pytest")) or {"texts": [{}]})["texts"][0]
                         ).get("latest", {})
        expect("a text's latest occurrence is its last, not its first",
               (pytest_latest.get("record"), [c["family"] for c in pytest_latest.get("next_calls", [])]),
               (fixture["pytest_record"], ["Bash:npm test", "Bash:curl", "Bash:make test"]))
        ruff_head = (found.get((IS_ERROR, "Bash:ruff")) or {"texts": [{}]})["texts"][0]
        expect("between equally common texts, the most recent is shown",
               (ruff_head.get("text"), ruff_head.get("latest", {}).get("record")),
               ("Exit code 1\nF401 b.py", fixture["ruff_record"]))
        expect("a retry's text is the verdict it retried past",
               [t["text"] for t in (found.get((RETRY, "Bash:make test")) or {"texts": []})["texts"]],
               ["Exit code 2\nFAIL"])
        expect("the refusals table holds hook denials, permission refusals and hook errors, and nothing else",
               sorted((r["class"], r["sentence"]) for r in report.get("refusals", [])), sorted([
                   (HOOK_DENIAL, "PreToolUse:Bash hook error: Catastrophic rm -rf blocked on system/home directory."),
                   (PERMISSION, "The user doesn't want to proceed with this tool use."),
                   (HOOK_ERROR, _HOOK_STDERR.split("\n", 1)[0])]))
        refusals = {r["sentence"]: r for r in report.get("refusals", [])}
        guard = refusals.get("PreToolUse:Bash hook error: Catastrophic rm -rf blocked on system/home directory.")
        expect("one refusal sentence across families",
               guard and (guard["discovery"]["sessions"], guard["held_out"]["sessions"], guard["families"]),
               (2, 1, ["Bash:rm", "Bash:ssh"]))

        code, text = run(base)
        expect("exit code of the text report", code, 0)
        for needle, why in ((CAVEAT, "the caveat"), (_RM.format("rm -rf /y"), "the newer refusal text, in full"),
                            (_indent(_HOOK_STDERR.rstrip("\n")), "the hook stderr in full"),
                            ("1 unreadable transcripts", "the unreadable transcript"),
                            ("held out: 2026-W45 (4.5 days)", "the held-out span"),
                            ("is not shown to be a burst", "the warning that 4.5 held-out days are too few")):
            if needle not in text:
                failures.append(f"the text report lacks {why}")

        two = run_json("the --holdout-weeks 2 run", [*base, "--holdout-weeks", "2"])
        expect("--holdout-weeks 2 holds out the week before as well", two.get("weeks"),
               {"discovery": ["2026-W41", "2026-W42", "2026-W43"], "held_out": ["2026-W44", "2026-W45"],
                "held_out_days": 11.5})
        expect("Bash:sleep with two weeks held out", split(fams(two).get((IS_ERROR, "Bash:sleep"))), (0, 0, 3, 3))
        code, text = run([*base, "--holdout-weeks", "2"])
        if "is not shown to be a burst" in text:
            failures.append("11.5 held-out days drew the too-few-days warning")

        wide = fams(run_json("the --subagents run", [*base, "--subagents"]))
        expect("Bash:sleep with subagents: still 2 lead sessions", split(wide.get((IS_ERROR, "Bash:sleep"))),
               (2, 3, 1, 1))
        expect("a subagent's error is counted with --subagents", split(wide.get((IS_ERROR, "Bash:go test"))),
               (1, 1, 0, 0))
        expect("a timeout read from the text where no object was recorded",
               split(wide.get((TIMEOUT, "Bash:cargo build"))), (1, 1, 0, 0))
        older = fams(run_json("the --since 60 run", [*base, "--since", "60"]))
        expect("an older verdict inside a wider window", split(older.get((IS_ERROR, "Bash:docker build"))),
               (1, 1, 0, 0))

        empty = Path(tmp) / "empty"
        empty.mkdir()
        code, text = run(["--root", str(empty), "--now", _NOW])
        expect("exit code with no transcripts", code, 1)
        if "NOT MEASURED" not in text:
            failures.append(f"no transcripts must read as NOT MEASURED, not as zero friction: {text[-200:]}")
        locked = Path(tmp) / "unreadable"
        (locked / "-p" / "s.jsonl").mkdir(parents=True)
        code, text = run(["--root", str(locked), "--now", _NOW])
        expect("exit code when no transcript would open", code, 1)
        if "NOT MEASURED" not in text:
            failures.append(f"no readable transcript must read as NOT MEASURED, not as zero friction: {text[-200:]}")

    for command, family in (("FOO=1 timeout 60 git -C /r status", "Bash:git status"),
                            ("sudo -n systemctl restart x", "Bash:systemctl restart"),
                            ("python3 - <<'EOF'\nimport os\nEOF", "Bash:python3 -"),
                            ("# a note\nls -la", "Bash:ls"), ("echo \"it's", "Bash:<unparsed>"),
                            ("/usr/bin/grep -n x f", "Bash:grep"), ("cd /tmp", "Bash:cd"),
                            ("( cd /x && make build )", "Bash:make build"), ("set -e; npm ci", "Bash:npm ci"),
                            ("sudo -u postgres psql -c 'select 1'", "Bash:psql"),
                            ("timeout -s KILL 60 pytest -q", "Bash:pytest"), ("git -C repo status", "Bash:git status"),
                            ("kubectl -n web get pods", "Bash:kubectl get"), ("bash -lc 'cd /x && make'", "Bash:bash -c"),
                            ("python3 -um pytest", "Bash:python3 -m pytest"),
                            ("bash -o pipefail -c 'a | b'", "Bash:bash -c"), ("bash -ex run.sh", "Bash:bash run.sh")):
        expect(f"the family of {command!r}", bash_family(command), family)

    if failures:
        for line in failures:
            print(f"SELF-TEST FAILED: {line}")
        return 1
    print("SELF-TEST PASSED: every verdict class (hook denial, permission refusal, timeout by object and by text, "
          "is_error, unchanged retry, hook error), the families (heredocs stripped, cd and wrappers skipped, "
          "option values skipped, subcommands kept, bash -lc is bash -c), the ranking by sessions, the held-out "
          "weeks (1 and 2) and their span, the window, main thread by default, the refusals table's classes, full "
          "texts, the latest occurrence and the next calls after it, and unreadable transcripts all fire on their "
          "controls and stay quiet on the rest.")
    return 0


# ─── Entry point ────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Harness verdicts (errors, denials, refusals, timeouts, unchanged retries, hook errors) from "
                    "Claude Code transcripts, ranked by distinct sessions. Report-only.",
        epilog=CAVEAT)
    parser.add_argument("--since", type=float, default=30.0, metavar="DAYS",
                        help="Window in days (default 30, as long as Claude Code keeps transcripts).")
    parser.add_argument("--holdout-weeks", type=int, default=1, metavar="N",
                        help="The last N ISO weeks, counting the current one, are held out (default 1).")
    parser.add_argument("--subagents", action="store_true",
                        help="Also read subagent and Workflow agent transcripts (default: main thread only).")
    parser.add_argument("--top", type=int, default=10, metavar="N", help="Families shown in the report (default 10).")
    parser.add_argument("--json", action="store_true", help="Emit every family as JSON instead of a report.")
    parser.add_argument("--root", action="append", metavar="DIR",
                        help="A projects/ directory to read (repeatable). Default: every Claude Code profile's.")
    parser.add_argument("--now", metavar="ISO", help="The report's clock (tests). Default: the current time.")
    parser.add_argument("--self-test", action="store_true",
                        help="Ask every verdict class, family rule and ranking rule whether it can still go red.")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test(main)
    if args.since <= 0:
        parser.error("--since must be a positive number of days")
    if args.holdout_weeks < 1:
        parser.error("--holdout-weeks must be at least 1")
    real_now = datetime.datetime.now(datetime.timezone.utc)
    now = _parse_when(args.now) if args.now else real_now
    if now is None:
        parser.error(f"--now {args.now!r} is not an ISO timestamp")
    start = now - datetime.timedelta(days=args.since)

    roots = [Path(r).expanduser() for r in args.root] if args.root else tr.default_roots()
    # Files are picked by mtime against the real clock; a --now in the past widens that, never narrows it.
    file_days = args.since + max(0.0, (real_now - now).total_seconds() / 86400)
    paths = tr.find_transcripts(roots, file_days)
    if args.subagents:
        paths += tr.find_subagent_transcripts(roots, file_days)
    if not paths:
        return _unmeasured(f"no transcripts modified in the last {file_days:g} days under "
                           + ", ".join(str(r) for r in roots), args.json)

    tally: dict[str, int] = {}
    unreadable: list[str] = []
    readable: list[Path] = []
    occurrences: list[dict[str, Any]] = []
    for path in paths:
        try:
            occurrences.extend(scan_transcript(path, tally))
        except OSError as exc:
            unreadable.append(f"{path}: {exc.strerror or exc}")
        else:
            readable.append(path)
    if not readable:
        return _unmeasured(f"none of the {len(paths)} transcripts could be read; the first: {unreadable[0]}",
                           args.json)
    counts = {"undated": 0, "outside_window": 0, "verdicts": 0}
    families, refusals, weeks = rank(occurrences, start, now, args.holdout_weeks, counts)
    report: dict[str, Any] = {
        "measured": True,
        "caveat": CAVEAT,
        "window": {"start": start.isoformat(), "end": now.isoformat(), "days": args.since},
        "scope": "main thread and subagents" if args.subagents else "main thread only",
        "weeks": weeks,
        "read": {"transcripts": len(readable), "sessions": len({tr.session_id(p) for p in readable}),
                 "tool_calls": tally.get("tool_calls", 0), "records": tally.get("records", 0),
                 "malformed": tally.get("malformed", 0), "truncated": tally.get("truncated", 0),
                 "unreadable": unreadable, **counts},
        "families": families,
        "refusals": refusals,
    }
    if args.json:
        json.dump(report, sys.stdout, indent=2, default=sorted)
        sys.stdout.write("\n")
    else:
        print_report(report, args.top)
    return 0


if __name__ == "__main__":
    sys.exit(main())
