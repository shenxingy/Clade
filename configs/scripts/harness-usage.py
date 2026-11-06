#!/usr/bin/env python3
"""harness-usage.py — which shipped skills and hooks actually fire.

Why this exists
---------------
Zaninotto, *The State Of AI Harness Engineering 2026* (Marmelab, 2026-09-24):
"give every control an expiry condition, and write down the incident it exists
for". A control is cost: a skill is a listing line and a prompt, a hook runs on
every matching event. Nothing on the terminal path counted which of Clade's
controls fire. This report counts, per skill shipped in ``configs/skills/`` and
per hook wired in ``configs/settings-hooks.json``: fires, denies, rejections,
timeouts and the last fire, over whole UTC days.

What it cannot tell you
-----------------------
- **Invocation is not behaviour change.** A fire says a skill was loaded or a
  hook ran. Whether what the agent did changed because of it is not measured
  here; that needs an ablation (a session with and without the control).
- **Zero traces is not zero runs.** Claude Code writes a ``stop_hook_summary``
  listing every Stop hook on every run, but a hook on any other event leaves a
  trace only when it printed, injected context, denied, errored or timed out.
  A hook that exits 0 silently, by design, reads as never fired.
- **Never fired means review candidate, not retire candidate.** The report says
  so in its output. A preventive control (wired synchronously on PreToolUse, the
  one event that refuses an action before it happens) is never retired by zero
  fires: it exists for the rare day it fires. Retiring one needs an ablation or
  a written retire-when condition.

Sources, and what each one counts
---------------------------------
``skillUsage`` in each profile's ``.claude.json`` (``~/.claude.json``,
``~/.claude-profiles/*/.claude.json``, ``$CLAUDE_CONFIG_DIR/.claude.json``):
``{name: {usageCount, lastUsedAt}}``. Read from the Claude Code 2.1.283 binary
on 2026-11-06, one function increments it, and three call paths call it: the
Skill tool (main thread AND subagents; not a coordinator-mode main thread), a
typed ``/name`` of a prompt-type, user-invocable command, and stacked skills.
A repeat of the same name within 60 s in one session is not counted. The Skill
tool records the name as the model typed it, so ``clade:x`` and ``x`` are two
keys; both are summed here. ``usageCount`` is a lifetime total that never
resets, so it is printed as lifetime, never as window activity. Only
``lastUsedAt`` says anything about the window, and only that the skill ran at
least once in it, somewhere.

Transcripts, read through ``transcripts.py`` (main thread; ``--include-subagents``
adds subagent transcripts), deduplicated on tool-use id and record uuid:

- a ``Skill`` tool call naming a shipped skill (a leading ``/`` and a
  ``clade:`` prefix are stripped). An error result is a rejection; a denied one
  a deny.
- a user record holding ``<command-name>/name</command-name>``: a slash command.
- hook attachments. A trace whose ``command`` names a shipped script (basename,
  in a ``hooks/`` or ``scripts/`` directory) or equals a shipped hook's
  ``statusMessage`` (Claude Code logs the status message in its place) is that
  hook's. A trace with no command (``hook_additional_context``,
  ``async_hook_response``, ``hook_permission_decision``) goes to the hook whose
  ``hook_success`` it pairs with, else to the only Clade hook wired for that
  event and tool, else, among several, to the one whose script name its output
  names (a bash error names its script). Anything left is UNATTRIBUTED and
  reported with its candidates; a hook Clade does not wire on that event is
  FOREIGN. A plugin hook on the same event as exactly one Clade hook is
  credited to the Clade one: the known limit of this rule.
- a tool result starting ``PreToolUse:<Tool> hook error:``: a deny. Claude Code
  writes no attachment for it, so it goes to the only synchronous Clade
  PreToolUse hook matching the tool.
- ``stop_hook_summary.hookInfos``: one fire per Stop hook per run. A Stop
  hook's ``hook_success`` is the same run and is not counted again.

Ledger
------
Claude Code deletes transcripts after ``cleanupPeriodDays`` (30 by default), so
a 60-day window needs a record kept outside them. ``--ledger`` appends one row
per COMPLETE UTC day and scope (main, subagents) to
``<config dir>/harness-usage/days.jsonl``, under the advisory lock
``scorecard_ledger.py`` takes for the Workflow ledger. A day is recorded only
when it is over and every transcript holding it is still on disk: an event on
day D sits in a file modified on or after D, and the cleanup deletes by
modification time, so the days from ``today - (retention - 1)`` to yesterday are
whole. The retention is the smallest ``cleanupPeriodDays`` across the scanned
config dirs. A per-run snapshot would overlap the previous one and could not be
summed; a day row can. A day already in the file is skipped: the file is
append-only and a row is never rewritten. The report reads it back: a day the
ledger holds is taken from the ledger; any other day from live transcripts, and
a day older than the retention with no ledger row is reported as PARTIAL.

Stdlib only: the syntax-check CI job installs no dependencies.
"""

from __future__ import annotations

import argparse
import bisect
import datetime
import importlib.util
import json
import os
import re
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import skill_frontmatter as sf  # noqa: E402
from scorecard_ledger import _lock  # noqa: E402  (the Workflow ledger's lock: one definition)
from transcripts import (  # noqa: E402
    HookAttachment,
    ToolEvent,
    attachments,
    config_dir,
    default_roots,
    find_subagent_transcripts,
    find_transcripts,
    is_subagent_transcript,
    iter_records,
    tool_events,
)

# ─── Constants ──────────────────────────────────────────────────────────────

REPO = Path(__file__).resolve().parents[2]
LEDGER_VERSION = 1
DEFAULT_SINCE = 30
DEFAULT_RETENTION = 30  # Claude Code's cleanupPeriodDays default
STOP_EVENTS = frozenset({"Stop", "SubagentStop"})
FIELDS = ("fires", "tool", "slash", "context", "denies", "rejections", "timeouts")
REVIEW_LABEL = "review candidates, not retire candidates"
_COMMAND_NAME = re.compile(r"<command-name>/([^<\s]+)\s*</command-name>")
_DENY = re.compile(r"^PreToolUse:(\S+) hook error:")

CAVEATS = (
    "Invocation is not behaviour change: a fire says a skill was loaded or a hook ran, not that what the "
    "agent did changed because of it. That needs an ablation.",
    "Zero traces is not zero runs: a Stop hook is listed on every run, but a hook on any other event leaves "
    "a trace only when it printed, injected context, denied, errored or timed out.",
    "skillUsage is a lifetime count per profile, never windowed. Claude Code 2.1.283 increments it for a "
    "Skill tool call (main thread and subagents, not a coordinator-mode main thread), a typed /name of a "
    "prompt skill, and a stacked skill; a repeat of the same name within 60 s in one session is not "
    "counted. Only lastUsedAt speaks for the window.",
    "Never fired lists review candidates, not retire candidates. A preventive control (synchronous on "
    "PreToolUse) is never retired by zero fires; retiring one needs an ablation or a written retire-when.",
)


def _hub_families() -> tuple[str, ...]:
    """``regen-skill-overrides.py``'s HUB_FAMILIES, so the families are defined once."""

    path = Path(__file__).resolve().parent / "regen-skill-overrides.py"
    spec = importlib.util.spec_from_file_location("regen_skill_overrides", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return tuple(module.HUB_FAMILIES)


# ─── Shipped controls ───────────────────────────────────────────────────────


@dataclass
class Wiring:
    event: str
    matcher: str | None
    is_async: bool


@dataclass
class Hook:
    """One shipped hook: a script, or a prompt hook named for its event. ``source`` is the script's text."""

    name: str
    script: str | None
    status: set[str] = field(default_factory=set)
    wirings: list[Wiring] = field(default_factory=list)
    source: str = ""

    @property
    def preventive(self) -> bool:
        return any(w.event == "PreToolUse" and not w.is_async for w in self.wirings)


def _script_of(command: str | None) -> str | None:
    """The basename of the first .sh/.py path in a hook command that sits in a hooks/ or scripts/ directory."""

    for token in (command or "").split():
        token = token.strip("'\"")
        if "/" in token and token.endswith((".sh", ".py")):
            path = Path(token)
            if path.parent.name in ("hooks", "scripts"):
                return path.name
    return None


def load_skills(repo: Path) -> dict[str, str | None]:
    """Every shipped skill name, mapped to its hub, or None for a skill that is not a hub sub-skill."""

    names = [skill["name"] for skill in sf.iter_skills(repo / "configs" / "skills")]
    shipped = set(names)
    hubs = _hub_families()
    out: dict[str, str | None] = {}
    for name in names:
        family = name.split("-", 1)[0]
        out[name] = family if family in hubs and family != name and family in shipped else None
    return out


def load_hooks(repo: Path) -> dict[str, Hook]:
    data = json.loads((repo / "configs" / "settings-hooks.json").read_text(encoding="utf-8"))
    hooks: dict[str, Hook] = {}
    for event, groups in (data.get("hooks") or {}).items():
        for group in groups or []:
            matcher = group.get("matcher")
            for entry in group.get("hooks") or []:
                kind = entry.get("type", "command")
                script = _script_of(entry.get("command")) if kind == "command" else None
                name = script or f"{event} {kind} hook"
                hook = hooks.setdefault(name, Hook(name, script))
                status = entry.get("statusMessage")
                if isinstance(status, str) and status.strip():
                    hook.status.add(status)
                hook.wirings.append(Wiring(event, matcher if isinstance(matcher, str) else None,
                                           bool(entry.get("async"))))
    for hook in hooks.values():
        for folder in ("hooks", "scripts"):
            path = repo / "configs" / folder / (hook.script or "")
            if hook.script and path.is_file():
                hook.source = path.read_text(encoding="utf-8", errors="replace")
                break
    return hooks


def _matches(matcher: str | None, target: str | None) -> bool:
    if matcher in (None, "", "*") or target is None:
        return True
    try:
        return re.fullmatch(matcher, target) is not None
    except re.error:
        return target in matcher.split("|")


class Attributor:
    """Which shipped hook a trace belongs to: ``hook:<name>``, ``foreign:hook`` or ``unattributed:<label>``."""

    def __init__(self, hooks: dict[str, Hook]):
        self.hooks = hooks
        self.by_status = {status: hook.name for hook in hooks.values() for status in hook.status}
        self.by_script = {hook.script: hook.name for hook in hooks.values() if hook.script}

    def by_command(self, command: str | None) -> str:
        if command in self.by_status:
            return "hook:" + self.by_status[command]
        script = _script_of(command)
        if script in self.by_script:
            return "hook:" + self.by_script[script]
        return "foreign:hook"

    def candidates(self, event: str | None, target: str | None, is_async: bool | None) -> list[str]:
        return sorted({
            hook.name for hook in self.hooks.values() for wiring in hook.wirings
            if wiring.event == event and (is_async is None or wiring.is_async == is_async)
            and _matches(wiring.matcher, target)
        })

    def resolve(self, label: str, event: str | None, target: str | None, is_async: bool, output: str) -> str:
        """A trace with no command: the only candidate, else the one its output names, else the one that wrote it."""

        found = self.candidates(event, target, is_async)
        if not found:
            return "foreign:hook"
        if len(found) == 1:
            return "hook:" + found[0]
        named = [name for name in found if (script := self.hooks[name].script) is not None and script in output]
        if len(named) == 1:
            return "hook:" + named[0]
        head = _signature(output)
        wrote = [name for name in found if head and head in self.hooks[name].source]
        if len(wrote) == 1:
            return "hook:" + wrote[0]
        return "unattributed:" + label


# The literal opening of an injected text, compared against each candidate script's source. Shorter than
# _MIN_SIGNATURE and a phrase matches by accident; longer than _MAX_SIGNATURE and it runs into a value the hook
# filled in that stops short of a digit or a bracket.
_MIN_SIGNATURE = 12
_MAX_SIGNATURE = 40
_FILLED_IN = re.compile(r"[\d'\"`(\[{<$]")


def _signature(output: str) -> str | None:
    """The literal a hook's message opens with: its first non-empty line up to the first digit, quote or bracket,
    at most 40 characters, and at least 12, or None.

    A hook builds its message from a literal and a few values (``asked for 3 times``, ``(keyword: 'x')``); the
    literal before the first value is what its source spells out. A message an older version of the hook
    printed matches nothing and stays unattributed.
    """

    for line in output.splitlines():
        line = line.strip()
        if line:
            head = _FILLED_IN.split(line, maxsplit=1)[0].strip()[:_MAX_SIGNATURE]
            return head if len(head) >= _MIN_SIGNATURE else None
    return None


def label_parts(label: str) -> tuple[str, str | None]:
    event, _, target = label.partition(":")
    return event, target or None


# ─── Counting ───────────────────────────────────────────────────────────────

Counts = dict[str, dict[str, Any]]  # control key -> {field: int, "last": ISO}


def _stamp(raw: object) -> datetime.datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        when = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=datetime.timezone.utc)


def _iso(when: datetime.datetime) -> str:
    return when.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def merge(into: Counts, more: Counts) -> None:
    for key, values in more.items():
        row = into.setdefault(key, {})
        for name, value in values.items():
            if name == "last":
                row["last"] = max(row.get("last") or "", value or "") or None
            else:
                row[name] = row.get(name, 0) + value


def _typed_texts(record: dict[str, Any]) -> list[str]:
    """The text a user record carries, or nothing for a meta record (a skill Claude Code attached itself)."""

    if record.get("type") != "user" or record.get("isMeta"):
        return []
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        return [str(b.get("text") or "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return []


def _content_text(trace: HookAttachment) -> str:
    """A context trace's content as one string. 2.1.283 writes a list of strings; a string is taken as it is."""

    raw = trace.raw.get("content")
    if isinstance(raw, list):
        return "\n".join(item for item in raw if isinstance(item, str))
    return raw if isinstance(raw, str) else ""


def _carried(stdout: str | None, kind: str) -> str | None:
    """What a hook_success's JSON stdout handed Claude Code: its additionalContext, or for a system-message
    trace its systemMessage. None for plain-text stdout, whose text Claude Code keeps in the success itself."""

    try:
        data = json.loads(stdout or "")
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    if kind == "hook_system_message":
        value = data.get("systemMessage")
    else:
        output = data.get("hookSpecificOutput")
        value = output.get("additionalContext") if isinstance(output, dict) else None
    return value if isinstance(value, str) else None


def _run_starts(records: list[dict[str, Any]]) -> list[int]:
    """For each record, the index where its unbroken run of attachment records began."""

    starts: list[int] = []
    start = 0
    for index, record in enumerate(records):
        if record.get("type") != "attachment":
            start = index + 1
        starts.append(start)
    return starts


class Scan:
    """Per (scope, UTC day) counts of every control, from the transcripts handed to ``scan_file``."""

    def __init__(self, start_day: str, skills: dict[str, str | None], attributor: Attributor):
        self.start_day = start_day
        self.skills = skills
        self.attr = attributor
        self.days: dict[tuple[str, str], Counts] = {}
        self.files: dict[tuple[str, str], set[str]] = {}
        self.read = {"transcripts": 0, "unreadable": 0, "malformed": 0, "truncated": 0, "undated": 0}
        self.seen: set[str] = set()

    def skill_name(self, raw: object) -> str | None:
        name = str(raw or "").strip().lstrip("/")
        prefix, _, rest = name.partition(":")
        if rest and prefix == "clade":
            name = rest
        return name if name in self.skills else None

    def _once(self, key: str | None) -> bool:
        if key is None:
            return True
        if key in self.seen:
            return False
        self.seen.add(key)
        return True

    def add(self, scope: str, path: Path, raw: object, control: str, fields: tuple[str, ...]) -> None:
        when = _stamp(raw)
        if when is None:
            self.read["undated"] += 1
            return
        day = when.astimezone(datetime.timezone.utc).date().isoformat()
        if day < self.start_day:  # memory only: the report and the ledger pick their days themselves
            return
        row = self.days.setdefault((scope, day), {}).setdefault(control, {})
        for name in fields:
            row[name] = row.get(name, 0) + 1
        row["last"] = max(row.get("last") or "", _iso(when))
        self.files.setdefault((scope, day), set()).add(str(path))

    def scan_file(self, path: Path) -> None:
        scope = "subagents" if is_subagent_transcript(path) else "main"
        tally: dict[str, int] = {}
        try:
            records = list(iter_records(path, tally))
        except OSError:
            self.read["unreadable"] += 1
            return
        self.read["transcripts"] += 1
        for name in ("malformed", "truncated"):
            self.read[name] += tally.get(name, 0)
        self._tool_calls(scope, path, tool_events(records))
        self._system(scope, path, records)
        self._slash(scope, path, records)
        self._attachments(scope, path, records)

    def _tool_calls(self, scope: str, path: Path, events: list[ToolEvent]) -> None:
        for event in events:
            if not self._once("tool:" + event.id):
                continue
            # The events a tool hook is wired on: every call reaches PreToolUse; a result decides which of
            # PostToolUse and PostToolUseFailure follows; a denied call never ran, so neither does.
            self.add(scope, path, event.timestamp, f"event:PreToolUse:{event.name}", ("events",))
            if event.result_index is not None and not event.denial_kind:
                after = "PostToolUseFailure" if event.is_error else "PostToolUse"
                self.add(scope, path, event.result_timestamp or event.timestamp, f"event:{after}:{event.name}",
                         ("events",))
            if event.name == "Skill":
                name = self.skill_name(event.input.get("skill"))
                outcome = ("denies",) if event.denial_kind else ("rejections",) if event.is_error else ()
                control = "skill:" + name if name else "foreign:skill"
                self.add(scope, path, event.timestamp, control, ("fires", "tool") + outcome)
            denied = _DENY.match(event.result or "") if event.is_error else None
            if denied:
                tool = denied.group(1)
                reason = (event.result or "")[denied.end():]  # the hook's own words, after Claude Code's prefix
                control = self.attr.resolve("PreToolUse:" + tool, "PreToolUse", tool, False, reason)
                self.add(scope, path, event.result_timestamp or event.timestamp, control, ("fires", "denies"))

    def _slash(self, scope: str, path: Path, records: list[dict[str, Any]]) -> None:
        for record in records:
            uuid = record.get("uuid")
            for at, text in enumerate(_typed_texts(record)):
                for match in _COMMAND_NAME.finditer(text):
                    name = self.skill_name(match.group(1))
                    key = f"slash:{uuid}:{at}:{match.start()}" if isinstance(uuid, str) else None
                    if name and self._once(key):
                        self.add(scope, path, record.get("timestamp"), "skill:" + name, ("fires", "slash"))

    def _system(self, scope: str, path: Path, records: list[dict[str, Any]]) -> None:
        """Stop hooks, one fire each per stop_hook_summary entry, and compactions, the PreCompact event."""

        for record in records:
            if record.get("type") != "system":
                continue
            uuid = record.get("uuid")
            if record.get("subtype") == "compact_boundary":
                if self._once(f"compact:{uuid}" if isinstance(uuid, str) else None):
                    self.add(scope, path, record.get("timestamp"), "event:PreCompact", ("events",))
                continue
            if record.get("subtype") != "stop_hook_summary":
                continue
            infos = record.get("hookInfos")
            for at, info in enumerate(infos if isinstance(infos, list) else []):
                command = info.get("command") if isinstance(info, dict) else None
                if isinstance(command, str) and self._once(f"stop:{uuid}:{at}" if isinstance(uuid, str) else None):
                    self.add(scope, path, record.get("timestamp"), self.attr.by_command(command), ("fires",))

    def _attachments(self, scope: str, path: Path, records: list[dict[str, Any]]) -> None:
        traces = list(attachments(records))
        successes = [trace for trace in traces if trace.kind == "hook_success"]
        by_call: dict[tuple[str | None, str | None], list[HookAttachment]] = {}
        for trace in successes:
            if trace.tool_use_id:
                by_call.setdefault((trace.tool_use_id, trace.hook_name), []).append(trace)
        positions = [trace.index for trace in successes]
        starts = _run_starts(records)
        for trace in traces:
            uuid = records[trace.index].get("uuid")
            if not self._once(f"att:{uuid}" if isinstance(uuid, str) else None):
                continue
            group = by_call.get((trace.tool_use_id, trace.hook_name), []) if trace.tool_use_id else []
            if not group and trace.hook_name == trace.hook_event:
                # An event-wide context (hookName "SessionStart", not "SessionStart:startup") has its own id:
                # its run is a success on the same event earlier in the same burst of attachments.
                run = successes[bisect.bisect_left(positions, starts[trace.index]):
                                bisect.bisect_left(positions, trace.index)]
                group = [s for s in run if s.hook_event == trace.hook_event]
            result = self._credit(trace, group)
            if result is not None:
                self.add(scope, path, trace.timestamp, *result)

    def _named(self, command: str | None, label: str, event: str | None, target: str | None, is_async: bool,
               output: str) -> str:
        return self.attr.by_command(command) if command else self.attr.resolve(label, event, target, is_async, output)

    def _credit(self, trace: HookAttachment, group: list[HookAttachment]) -> tuple[str, tuple[str, ...]] | None:
        """(control, fields) for one hook attachment, or None when it is a run already counted elsewhere.

        ``group`` is the hook_success records a command-less context trace may belong to: the ones for the same
        tool call and hook name, else the ones on the same event earlier in the same burst of attachments.
        """

        event, target = label_parts(trace.hook_name) if trace.hook_name else (trace.hook_event, None)
        label = trace.hook_name or trace.hook_event or trace.kind
        output = (trace.stdout or "") + "\n" + (trace.stderr or "")
        # A Stop hook's run is counted once, from stop_hook_summary; its other traces only add an outcome.
        fire: tuple[str, ...] = () if event in STOP_EVENTS else ("fires",)
        kind = trace.kind
        if kind == "hook_success":
            return None if event in STOP_EVENTS else (self._named(trace.command, label, event, target, False,
                                                                   output), ("fires",))
        if kind in ("hook_additional_context", "hook_system_message"):
            text = _content_text(trace)
            if group:  # the run is a hook_success beside it, already counted as a fire
                carried = [s for s in group if _carried(s.stdout, kind) is not None]
                match = group if len(group) == 1 else (
                    [s for s in carried if _carried(s.stdout, kind) == text] or carried)
                control = self.attr.by_command(match[0].command) if len(match) == 1 else "unattributed:" + label
                return control, ("context",)
            return self.attr.resolve(label, event, target, False, text), fire + ("context",)
        if kind == "hook_non_blocking_error":
            return self._named(trace.command, label, event, target, False, output), fire + ("rejections",)
        if kind == "hook_blocking_error":
            blocking = trace.raw.get("blockingError")
            command = blocking.get("command") if isinstance(blocking, dict) else trace.command
            return self._named(command, label, event, target, False, output), fire + ("denies",)
        if kind == "hook_cancelled":
            return self._named(trace.command, label, event, target, False, output), fire + ("timeouts",)
        if kind == "async_hook_response":
            failed = ("rejections",) if trace.exit_code not in (0, None) else ()
            return self.attr.resolve(label, event, target, True, output), fire + failed
        return self._named(trace.command, label, event, target, False, output), fire


# ─── skillUsage ─────────────────────────────────────────────────────────────


def usage_files() -> list[Path]:
    """Every profile's .claude.json: ~/.claude.json, ~/.claude-profiles/*/.claude.json, $CLAUDE_CONFIG_DIR's."""

    home = Path.home()
    found = [home / ".claude.json"]
    profiles = home / ".claude-profiles"
    if profiles.is_dir():
        found.extend(sorted(p / ".claude.json" for p in profiles.iterdir() if p.is_dir()))
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        found.append(config_dir() / ".claude.json")
    unique: dict[Path, Path] = {}
    for path in found:
        if path.is_file():
            unique.setdefault(path.resolve(), path)
    return list(unique.values())


def read_usage(scan: Scan) -> tuple[dict[str, dict[str, Any]], int, list[str]]:
    """Per shipped skill: lifetime count summed over profiles and key spellings, and the newest lastUsedAt."""

    usage: dict[str, dict[str, Any]] = {}
    files = usage_files()
    unreadable: list[str] = []
    for path in files:
        try:
            entries = json.loads(path.read_text(encoding="utf-8")).get("skillUsage") or {}
        except (OSError, ValueError, AttributeError):
            unreadable.append(str(path))
            continue
        for key, entry in entries.items() if isinstance(entries, dict) else []:
            name = scan.skill_name(key)
            if not name or not isinstance(entry, dict):
                continue
            row = usage.setdefault(name, {"lifetime": 0, "last_ms": 0})
            row["lifetime"] += int(entry.get("usageCount") or 0)
            row["last_ms"] = max(row["last_ms"], int(entry.get("lastUsedAt") or 0))
    return usage, len(files), unreadable


# ─── Ledger ─────────────────────────────────────────────────────────────────


def default_ledger_path() -> Path:
    return config_dir() / "harness-usage" / "days.jsonl"


def retention_days(roots: list[Path]) -> int:
    """The smallest cleanupPeriodDays among the scanned config dirs' settings.json, else 30."""

    found: list[int] = []
    for root in roots:
        try:
            value = json.loads((root.parent / "settings.json").read_text(encoding="utf-8")).get("cleanupPeriodDays")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            found.append(int(value))
    return min(found) if found else DEFAULT_RETENTION


def read_ledger(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """Every (day, scope) row in the ledger; the first row for a key wins, a line that does not parse is skipped."""

    rows: dict[tuple[str, str], dict[str, Any]] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return rows
    for line in text.split("\n"):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("day"), str) and isinstance(row.get("scope"), str):
            rows.setdefault((row["day"], row["scope"]), row)
    return rows


def append_days(path: Path, rows: list[dict[str, Any]]) -> tuple[int, int]:
    """Append each row whose (day, scope) the file does not hold yet. Returns (appended, already present)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    appended = present_count = 0
    # "a+" opens with O_APPEND: every write lands at the end, so no byte already in the file is rewritten.
    with path.open("a+", encoding="utf-8") as handle:
        _lock(handle)
        handle.seek(0)
        existing = handle.read()
        present = {(r.get("day"), r.get("scope")) for r in _rows(existing)}
        lines: list[str] = []
        for row in rows:
            key = (row["day"], row["scope"])
            if key in present:
                present_count += 1
                continue
            present.add(key)
            lines.append(json.dumps(row, ensure_ascii=False, sort_keys=True))
            appended += 1
        if lines:
            fresh = "" if not existing or existing.endswith("\n") else "\n"
            handle.write(fresh + "\n".join(lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    return appended, present_count


def _rows(text: str) -> list[dict[str, Any]]:
    out = []
    for line in text.split("\n"):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


# ─── Window ─────────────────────────────────────────────────────────────────


def _today() -> datetime.date:
    return datetime.datetime.now(datetime.timezone.utc).date()


def _days(first: datetime.date, last: datetime.date) -> list[str]:
    return [(first + datetime.timedelta(days=n)).isoformat() for n in range((last - first).days + 1)]


def run_scan(roots: list[Path], scopes: tuple[str, ...], since: int, start_day: str,
             skills: dict[str, str | None], attributor: Attributor) -> Scan:
    scan = Scan(start_day, skills, attributor)
    paths = find_transcripts(roots, since + 1)
    if "subagents" in scopes:
        paths += find_subagent_transcripts(roots, since + 1)
    for path in paths:
        scan.scan_file(path)
    return scan


def record_ledger(path: Path, roots: list[Path], skills: dict[str, str | None], attributor: Attributor,
                  as_json: bool) -> int:
    today = _today()
    retention = retention_days(roots)
    if retention < 2:
        print(f"harness-usage: cleanupPeriodDays is {retention}; no whole day survives it, nothing recorded.")
        return 0
    first = today - datetime.timedelta(days=retention - 1)
    days = _days(first, today - datetime.timedelta(days=1))
    scan = run_scan(roots, ("main", "subagents"), retention, first.isoformat(), skills, attributor)
    now = _iso(datetime.datetime.now(datetime.timezone.utc))
    rows = [{
        "ledger": LEDGER_VERSION, "day": day, "scope": scope, "recorded_at": now, "config_dir": str(config_dir()),
        "transcripts": len(scan.files.get((scope, day), ())), "counts": scan.days.get((scope, day), {}),
    } for day in days for scope in ("main", "subagents")]
    appended, present = append_days(path, rows)
    summary = {"ledger": str(path), "appended": appended, "already_present": present, "days": [days[0], days[-1]]
               if days else [], "retention_days": retention, "read": scan.read}
    if as_json:
        print(json.dumps(summary, indent=2))
    else:
        span = f"{days[0]} → {days[-1]}" if days else "none"
        print(f"harness-usage: ledger {path}: appended {appended} day-row(s), {present} already present "
              f"(whole UTC days {span}, main + subagents; retention {retention} days).")
    return 0


# ─── Report ─────────────────────────────────────────────────────────────────


# The hook events a transcript shows happening: a tool call (PreToolUse), its result (PostToolUse or
# PostToolUseFailure) and a compaction (PreCompact). SessionStart, UserPromptSubmit, Stop, Notification and the
# rest are not counted, so a hook wired only on those has no event count.
TOOL_EVENTS = frozenset({"PreToolUse", "PostToolUse", "PostToolUseFailure"})


def wired_events(hook: Hook, totals: Counts) -> int | None:
    """How many times an event this hook is wired on happened in the window, or None when none is observable.

    It bounds how often a synchronous hook RAN: a silent run leaves no trace, so for a guard it says how many
    calls it passed. Each event is counted once even when two of the hook's wirings match it.
    """

    keys: set[str] = set()
    observable = False
    for wiring in hook.wirings:
        if wiring.event in TOOL_EVENTS:
            observable = True
            prefix = f"event:{wiring.event}:"
            keys.update(key for key in totals if key.startswith(prefix)
                        and _matches(wiring.matcher, key[len(prefix):]))
        elif wiring.event == "PreCompact":
            observable = True
            keys.add("event:PreCompact")
    return sum(int(totals.get(key, {}).get("events", 0)) for key in keys) if observable else None


def build_report(scan: Scan, ledger: dict[tuple[str, str], dict[str, Any]], ledger_path: Path,
                 scopes: tuple[str, ...], window: list[str], retention: int,
                 skills: dict[str, str | None], hooks: dict[str, Hook], attributor: Attributor) -> dict[str, Any]:
    first_whole = (_today() - datetime.timedelta(days=retention - 1)).isoformat()
    totals: Counts = {}
    sources = {"live": 0, "ledger": 0, "partial": 0}
    for scope in scopes:
        for day in window:
            if (day, scope) in ledger:
                counts = ledger[(day, scope)].get("counts")
                merge(totals, counts if isinstance(counts, dict) else {})
                sources["ledger"] += 1
                continue
            merge(totals, scan.days.get((scope, day), {}))
            sources["live" if day >= first_whole else "partial"] += 1

    def row(key: str) -> dict[str, Any]:
        values = totals.get(key, {})
        out: dict[str, Any] = {name: int(values.get(name, 0)) for name in FIELDS}
        out["last"] = values.get("last")
        return out

    usage, profiles, unreadable_usage = read_usage(scan)
    window_ms = datetime.datetime.combine(datetime.date.fromisoformat(window[0]), datetime.time(),
                                          datetime.timezone.utc).timestamp() * 1000
    skill_rows = []
    for name, hub in sorted(skills.items()):
        entry = {"name": name, "hub": hub, **row("skill:" + name)}
        used = usage.get(name, {})
        entry["lifetime"] = used.get("lifetime", 0)
        last_ms = used.get("last_ms", 0)
        entry["lifetime_last"] = _iso(datetime.datetime.fromtimestamp(last_ms / 1000, datetime.timezone.utc)) \
            if last_ms else None
        entry["used_in_window"] = bool(entry["fires"]) or last_ms >= window_ms
        skill_rows.append(entry)
    by_name = {r["name"]: r for r in skill_rows}
    hub_rows = []
    for hub in sorted({h for h in skills.values() if h}):
        subs = [r for r in skill_rows if r["hub"] == hub]
        hub_rows.append({
            "name": hub, "fires": by_name[hub]["fires"],
            "family_fires": by_name[hub]["fires"] + sum(r["fires"] for r in subs),
            "family_used_in_window": by_name[hub]["used_in_window"] or any(r["used_in_window"] for r in subs),
            "sub_skills": len(subs), "sub_skills_fired": sum(1 for r in subs if r["used_in_window"]),
        })
    family_used = {h["name"]: h["family_used_in_window"] for h in hub_rows}

    unattributed = []
    for key in sorted(k for k in totals if k.startswith("unattributed:")):
        label = key.split(":", 1)[1]
        event, target = label_parts(label)
        unattributed.append({"label": label, **row(key), "candidates": attributor.candidates(event, target, None)})
    hook_rows = []
    for name, hook in sorted(hooks.items()):
        entry = {"name": name, **row("hook:" + name), "preventive": hook.preventive,
                 "wired": sorted({w.event + (":" + w.matcher if w.matcher else "") + (" async" if w.is_async else "")
                                  for w in hook.wirings})}
        entry["may_hide_in"] = [u["label"] for u in unattributed if name in u["candidates"]]
        entry["events"] = wired_events(hook, totals)
        hook_rows.append(entry)

    never_hooks = [h for h in hook_rows if not h["fires"]]
    return {
        "window": {"days": len(window), "first": window[0], "last": window[-1], "scope": "+".join(scopes),
                   "sources": sources, "retention_days": retention, "ledger": str(ledger_path)},
        "read": dict(scan.read, usage_profiles=profiles, usage_unreadable=unreadable_usage),
        "skills": skill_rows,
        "hubs": hub_rows,
        "hooks": hook_rows,
        "unattributed": unattributed,
        "foreign": {"skill_calls": row("foreign:skill")["fires"], "hook_traces": row("foreign:hook")["fires"]},
        "never_fired": {
            "label": REVIEW_LABEL,
            "skills": [r["name"] for r in skill_rows if not r["hub"] and not r["used_in_window"]
                       and not (r["name"] in family_used and family_used[r["name"]])],
            "sub_skills": [r["name"] for r in skill_rows if r["hub"] and not r["used_in_window"]],
            "hooks": [h["name"] for h in never_hooks if not h["preventive"]],
            "preventive": [h["name"] for h in never_hooks if h["preventive"]],
        },
        "caveats": list(CAVEATS),
    }


def _day(stamp: str | None) -> str:
    return stamp[:10] if stamp else "-"


def _wrap(names: list[str], indent: str = "    ") -> str:
    return textwrap.fill(", ".join(names) or "none", width=100, initial_indent=indent, subsequent_indent=indent)


def _events(hook: dict[str, Any]) -> str:
    return "-" if hook["events"] is None else str(hook["events"])


def _never_hook(hook: dict[str, Any]) -> str:
    notes = [] if hook["events"] is None else [f"silent on {hook['events']} wired events"]
    if hook["may_hide_in"]:
        notes.append("unattributed traces on " + ", ".join(hook["may_hide_in"]))
    return hook["name"] + (f" ({'; '.join(notes)})" if notes else "")


def print_report(report: dict[str, Any]) -> None:
    w, read = report["window"], report["read"]
    scope = "main thread only" if w["scope"] == "main" else "main thread and subagents"
    print(f"harness-usage — {w['days']} whole UTC days, {w['first']} → {w['last']} (today is partial), {scope}.")
    src = w["sources"]
    print(f"Read {read['transcripts']} transcripts ({read['unreadable']} unreadable; {read['malformed']} malformed "
          f"and {read['truncated']} truncated lines; {read['undated']} undated traces). Day-scopes: {src['live']} "
          f"live, {src['ledger']} from the ledger, {src['partial']} PARTIAL (older than the {w['retention_days']}-day "
          f"transcript retention with no ledger row).")
    print(f"skillUsage read from {read['usage_profiles']} profile(s)"
          + (f"; unreadable: {', '.join(read['usage_unreadable'])}" if read["usage_unreadable"] else "") + ".")
    print("\n" + report["caveats"][0])

    skills = report["skills"]
    fired = sorted((r for r in skills if r["fires"]), key=lambda r: (-r["fires"], r["name"]))
    subs = sum(1 for r in skills if r["hub"])
    print(f"\nSKILLS — {len(skills)} shipped ({len(skills) - subs} standalone incl. {len(report['hubs'])} hubs, "
          f"{subs} hub sub-skills); {len(fired)} fired in the window.")
    print(f"  {'skill':<26}{'fires':>6}{'tool':>6}{'slash':>6}{'denied':>7}{'errored':>8}  {'last fired':<11}"
          f"lifetime (skillUsage, last)")
    for r in fired:
        print(f"  {r['name']:<26}{r['fires']:>6}{r['tool']:>6}{r['slash']:>6}{r['denies']:>7}{r['rejections']:>8}  "
              f"{_day(r['last']):<11}{r['lifetime']} ({_day(r['lifetime_last'])})")
    print("  Hubs (a hub's family is the hub plus its sub-skills):")
    for h in report["hubs"]:
        print(f"    {h['name']:<8} hub {h['fires']}, family {h['family_fires']}; "
              f"{h['sub_skills_fired']} of {h['sub_skills']} sub-skills used in the window")
    print("  " + report["caveats"][2])

    hooks = report["hooks"]
    traced = sorted((h for h in hooks if h["fires"]), key=lambda h: (-h["fires"], h["name"]))
    print(f"\nHOOKS — {len(hooks)} shipped ({sum(len(h['wired']) for h in hooks)} wirings); {len(traced)} left a trace.")
    print(f"  {'hook':<30}{'fires':>7}{'of events':>11}{'context':>8}{'denies':>7}{'rejected':>9}{'timeouts':>9}"
          f"  last fired")
    for h in traced:
        print(f"  {h['name']:<30}{h['fires']:>7}{_events(h):>11}{h['context']:>8}{h['denies']:>7}"
              f"{h['rejections']:>9}{h['timeouts']:>9}  {_day(h['last'])}")
    print("  'of events' counts the tool calls, results and compactions a hook is wired on ('-': its event is "
          "not visible in a transcript).")
    print("  " + report["caveats"][1])
    if report["unattributed"]:
        print("  UNATTRIBUTED — traces with no command on an event where several Clade hooks are wired:")
        for u in report["unattributed"]:
            print(f"    {u['label']:<28} {u['fires']} fire(s), {u['context']} context; "
                  f"candidates: {', '.join(u['candidates'])}")
    f = report["foreign"]
    print(f"  FOREIGN — {f['hook_traces']} hook trace(s) and {f['skill_calls']} Skill call(s) from controls Clade "
          f"does not ship; not counted above.")

    never = report["never_fired"]
    print(f"\nNEVER FIRED IN THE WINDOW — {never['label'].upper()}.")
    print(f"  Skills ({len(never['skills'])}; no transcript invocation and no skillUsage lastUsedAt in the window):")
    print(_wrap(never["skills"]))
    print(f"  Hub sub-skills ({len(never['sub_skills'])}; undercounted: a hub can read a sub-skill's files "
          f"without a Skill call):")
    print(_wrap(never["sub_skills"]))
    by_hook = {h["name"]: h for h in hooks}
    print(f"  Hooks ({len(never['hooks'])}; a hook that runs silently by design reads as never fired):")
    print(_wrap([_never_hook(by_hook[n]) for n in never["hooks"]]))
    print(f"  Preventive hooks ({len(never['preventive'])}): zero fires never retires these.")
    print(_wrap([_never_hook(by_hook[n]) for n in never["preventive"]]))
    print("  " + report["caveats"][3])


def report_mode(args: argparse.Namespace, roots: list[Path], skills: dict[str, str | None],
                hooks: dict[str, Hook], attributor: Attributor) -> int:
    today = _today()
    first = today - datetime.timedelta(days=args.since - 1)
    window = _days(first, today)
    scopes = ("main", "subagents") if args.include_subagents else ("main",)
    scan = run_scan(roots, scopes, args.since, window[0], skills, attributor)
    ledger_path = Path(args.ledger_path).expanduser() if args.ledger_path else default_ledger_path()
    report = build_report(scan, read_ledger(ledger_path), ledger_path, scopes, window, retention_days(roots),
                          skills, hooks, attributor)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_report(report)
    return 0


# ─── Entry point ────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="harness-usage.py",
        description="Which shipped skills and hooks fire: fires, denies, rejections, timeouts, last fire. "
                    "Report-only; never fired means review candidate, not retire candidate.")
    parser.add_argument("--since", type=int, default=DEFAULT_SINCE, metavar="DAYS",
                        help="Window in whole UTC days, today included (default 30). Past the transcript "
                             "retention, days come from the ledger or are reported PARTIAL.")
    parser.add_argument("--include-subagents", action="store_true",
                        help="Also count subagent transcripts (default: main thread only).")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a report.")
    parser.add_argument("--ledger", action="store_true",
                        help="Append one row per whole UTC day and scope not yet recorded, then exit.")
    parser.add_argument("--ledger-path", metavar="PATH",
                        help="Ledger file to read and append (default <config dir>/harness-usage/days.jsonl).")
    parser.add_argument("--repo", metavar="DIR", default=str(REPO),
                        help="The Clade checkout whose shipped skills and hooks are counted (default: this one).")
    parser.add_argument("--self-test", action="store_true", help="Run the controls in harness_usage_selftest.py.")
    args = parser.parse_args(argv)
    if args.self_test:
        import harness_usage_selftest

        return harness_usage_selftest.run(main)
    if args.since < 1:
        parser.error("--since must be at least 1")
    repo = Path(args.repo).expanduser()
    skills, hooks = load_skills(repo), load_hooks(repo)
    attributor = Attributor(hooks)
    roots = default_roots()
    if args.ledger:
        path = Path(args.ledger_path).expanduser() if args.ledger_path else default_ledger_path()
        return record_ledger(path, roots, skills, attributor, args.json)
    return report_mode(args, roots, skills, hooks, attributor)


if __name__ == "__main__":
    sys.exit(main())
