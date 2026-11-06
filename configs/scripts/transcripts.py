#!/usr/bin/env python3
"""transcripts.py — one Claude Code transcript reader for the report scripts.

Why this exists
---------------
Every report script that mines Claude Code's own transcripts grew its own reader:
``workflow-scorecard.py`` (agents, polls), ``scorecard_ledger.py`` (owner messages
after a run), ``outcome-scorecard.py`` (tokens), and radar's manual tallies. Each
re-derived where the files live, how a malformed line is skipped, and how a tool
call meets its result, and they drifted. ``scan_session_polls`` splits files
with ``str.splitlines()``, which also splits on U+2028, U+2029 and U+0085. JSON
leaves those raw inside strings, so a record holding one breaks into two
unparseable halves. Measured 2026-11-05: 2 of 240 main-thread transcripts
modified in the previous 30 days on the author's host lost one record each that
way. Both were tool results, which ``--polls`` does not count, so its figures
are unaffected; a reader of results would not be. This module is the one place
those answers live. It is a library, not a CLI.

Where transcripts live
----------------------
Under each root returned by ``default_roots()`` (``~/.claude/projects``, every
``~/.claude-profiles/*/projects`` and ``$CLAUDE_CONFIG_DIR/projects``):

    <root>/<slug>/<session>.jsonl                              main thread
    <root>/<slug>/<session>/subagents/agent-<id>.jsonl         Agent/Task subagent
    <root>/<slug>/<session>/subagents/workflows/wf_<run>/agent-<id>.jsonl
                                                               Workflow agent

Beside a Workflow agent sit ``agent-<id>.meta.json`` (agentType, description,
workflowPhase, spawnDepth, …) and the run's ``journal.jsonl``. The journal is not
a transcript, so subagent discovery skips it. ``<slug>/memory/`` holds Markdown
and is never matched. Two roots can be the same directory through a symlink, so
every finder deduplicates on the resolved path.

What a record holds (Claude Code 2.1.283)
-----------------------------------------
Inspected 2026-11-05 with ``jq`` over keys and types only, never content: the
240 main-thread transcripts above, plus one Workflow agent and one plain Agent
transcript for the subagent shape. Everything about tool results was
re-derived 2026-11-06 over the transcripts modified in the previous 30 days on
the same host: all 335 main-thread, all 124 plain Agent and all 6,165 Workflow
agent transcripts, with a 600-transcript random sample of the Workflow ones
for the record fields and text markers. That census read keys, types and tool
names, plus whether a result's text starts with one of two Claude Code
templates quoted below, and printed counts only, never content. Each line is
one JSON object with a ``type``:

``assistant``   ``message`` is one API response block: ``message.content`` is a
                list holding ONE block (thinking, text or tool_use), and a
                response with several blocks is several records sharing
                ``message.id``. A tool_use block has ``id``, ``name``, ``input``
                and ``caller``. Also ``requestId``, ``timestamp``, ``uuid``,
                ``parentUuid``, ``sessionId``, ``isSidechain``, ``cwd``,
                ``gitBranch``, ``effort``/``perTurnEffort``, and on most
                tool calls ``wireToolInputs`` (``{tool_use_id: input}``), the
                input as the API carried it. In one transcript it differed from
                ``input`` on 183 of 825 calls, mostly by a leading ``cd <dir>
                &&`` that ``input`` lacks. ``tool_events`` reports ``input``.
``user``        ``message.content`` is a string (typed text) or a list. A list
                can hold tool_result blocks: ``tool_use_id``, ``content`` (a
                string, or a list of ``text``, ``image`` and ``tool_reference``
                items) and ``is_error``, which is absent on 3,843 of the
                31,777 main-thread results not flagged as errors. The record
                can carry ``toolUseResult``; which transcript kinds do is
                below the record types. Its type varies. On a successful
                built-in call it is an OBJECT, the tool's structured output.
                On every error or denied result it is a STRING (it starts
                ``Error`` on 878 of the 888 main-thread errors), and so it is
                on 4 MCP results that have no ``is_error`` but whose string
                starts ``Error``. On a successful MCP call it is a LIST of
                ``text`` items. Main thread: 31,624 objects, 892 strings, 149
                lists, and none missing.

                Only Bash's object holds the three fields ``tool_events``
                reads (main thread and plain Agent; Workflow below). Every Bash
                object has ``stdout``, ``stderr``, ``interrupted``,
                ``isImage`` and ``noOutputExpected``. ``interrupted`` was
                ``false`` on all 35,818 seen (27,401 main-thread, 8,417 plain
                Agent), so no interruption has been observed through it.
                ``timedOutAfterMs`` (119 main-thread, 25 plain Agent) marks a
                command that outran its timeout and was moved to the
                background: every one also has ``backgroundTaskId``, is NOT
                ``is_error``, and its result text starts ``Command did not
                complete within its``. ``backgroundTaskId`` alone does not
                mean a timeout: ``run_in_background`` sets it too.
                ``persistedOutputPath`` (110 main-thread, 56 plain Agent)
                marks an output too large to keep: the result text is only a
                preview that starts ``<persisted-output>`` and names that
                path, a file under the LEAD session's
                ``<slug>/<session>/tool-results/`` even for a subagent. A
                persisted Grep, WebFetch or MCP result has the same preview
                but no such field (8 on the main thread).

                A denied call adds ``toolDenialKind``, only ever seen beside
                an error string: ``permission-rule`` (a permission rule, or a
                PreToolUse hook: the result text starts ``PreToolUse:<Tool>
                hook error:`` and the string ``Error: PreToolUse:``) or
                ``user-rejected``. Main thread: 95 and 53.
``attachment``  ``attachment.type`` names it. Hook kinds seen:
                ``hook_success`` (command, content, stdout, stderr, exitCode,
                durationMs), ``hook_additional_context`` (content),
                ``hook_non_blocking_error`` (command, stdout, stderr, exitCode),
                ``hook_blocking_error`` (``blockingError`` is an object with
                ``blockingError`` and ``command``), ``hook_cancelled``
                (``timedOut``, ``timeoutMs``), ``hook_permission_decision``
                (``decision``), ``hook_system_message`` (content) and
                ``async_hook_response`` (``response`` object, ``processId``, no
                ``toolUseID``). All but the last carry ``hookEvent`` and
                ``toolUseID``: a ``toolu_`` id for tool events, an opaque id
                for Stop, SessionStart and UserPromptSubmit. All but
                ``hook_permission_decision`` carry ``hookName``
                (``PostToolUse:Bash``). Non-hook kinds outnumber them
                (``total_tokens_reminder``, ``deferred_tools_record``,
                ``queued_command``, …).
``system``      ``subtype``: ``stop_hook_summary`` (``hookInfos``,
                ``hookErrors``, ``preventedContinuation``), ``turn_duration``,
                ``compact_boundary``, ``away_summary``, ``informational``, …
other           ``permission-mode``, ``mode``, ``last-prompt``, ``ai-title``,
                ``pr-link``, ``queue-operation``, ``file-history-*``: no
                ``message``.

Subagent records carry ``agentId`` and ``isSidechain: true``, and their
``sessionId`` is the lead session's: every user and assistant record of the 124
plain Agent and the 600 sampled Workflow agent transcripts did. Whether a tool
result carries ``toolUseResult`` depends on the transcript kind:

main thread     Always: 32,665 of 32,665 results, typed as above.
plain Agent     On every error (202 strings) and on most successes (9,850
                objects, same fields as the main thread's). 402 of the 10,252
                successes have none: all 292 in the 5 transcripts whose records
                say ``entrypoint: "sdk-cli"``, and 110 in 4 of the 119 whose
                records say ``"cli"``.
Workflow agent  On every error (8,192 strings), almost never on a success:
                356,861 of 356,981 successes have none. The other 120 are
                objects in 4 of the 6,165 transcripts, each after a first run
                of successes without one. 94 are Bash objects, with
                ``interrupted`` (false on all 94) and without
                ``timedOutAfterMs`` or ``persistedOutputPath``.

Where the object is missing, a timeout and a persisted output still show in
the result TEXT through the two templates above (in the 600 sampled Workflow
transcripts, 139 results start with the timeout template and 297 with the
persisted one, which names the path), but ``tool_events`` reads only the
object, so it leaves both None. No text marker for an interruption is known.
All three kinds carry ``toolDenialKind`` beside a denied result's error string:
148 main-thread, 28 plain Agent and 482 Workflow agent results. Every result
whose text starts ``PreToolUse:`` had it (72 main-thread, 12 plain Agent, 29 in
the Workflow sample). A PreToolUse hook that DENIES a call leaves no hook
attachment: the denial is visible only as the tool_result and the
``toolDenialKind`` beside it.

Stdlib only, on purpose: the syntax-check CI job installs no dependencies.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

# ─── Where transcripts live ─────────────────────────────────────────────────

# Files under subagents/ that end in .jsonl and are not transcripts. Named
# rather than matching agent-*.jsonl, so a transcript Claude Code renames shows
# up as an extra file instead of vanishing into a zero.
_NOT_TRANSCRIPTS = frozenset({"journal.jsonl"})


def config_dir() -> Path:
    """$CLAUDE_CONFIG_DIR when set and non-empty, else ~/.claude."""

    override = os.environ.get("CLAUDE_CONFIG_DIR", "")
    return Path(override).expanduser() if override else Path.home() / ".claude"


def default_roots() -> list[Path]:
    """Every ``projects/`` directory Claude Code may have written transcripts into.

    ``~/.claude/projects``, then each ``~/.claude-profiles/<profile>/projects``
    in name order, then the config dir's own ``projects/`` when it is none of
    those. A root that does not exist is still listed: the finders skip it.
    """

    home = Path.home()
    roots = [home / ".claude" / "projects"]
    profiles = home / ".claude-profiles"
    if profiles.is_dir():
        roots.extend(sorted(p / "projects" for p in profiles.iterdir() if p.is_dir()))
    # The config dir --ledger writes into, wherever $CLAUDE_CONFIG_DIR puts it.
    # Without it a ledger pass from elsewhere scanned nothing and said so as 0.
    configured = config_dir() / "projects"
    if all(configured.resolve() != root.resolve() for root in roots):
        roots.append(configured)
    return roots


def _find(roots: list[Path], pattern: str, since_days: float | None, in_subagents_dir: bool) -> list[Path]:
    """The files under ``roots`` matching ``pattern``, oldest first; the finders below share it.

    ``in_subagents_dir`` also skips a run's journal and anything that is not a
    regular file. The main-thread finder keeps the filter it had inside
    workflow-scorecard.py before the move, which had neither.

    Each file's mtime is read ONCE, inside ``try``. A file that is gone by
    then is skipped: Claude Code's 30-day cleanup can delete one between the
    glob and the stat, and a dangling symlink is listed by the glob and cannot
    be stat'ed. Reading it twice (once to filter, again to sort) used to let
    such a file abort the whole scan with FileNotFoundError.
    """

    cutoff = None
    if since_days is not None:
        cutoff = datetime.datetime.now().timestamp() - since_days * 86400
    found: dict[Path, tuple[float, Path]] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in root.glob(pattern):
            if in_subagents_dir and (path.name in _NOT_TRANSCRIPTS or not path.is_file()):
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if cutoff is not None and mtime < cutoff:
                continue
            found.setdefault(path.resolve(), (mtime, path))
    return [path for _, path in sorted(found.values(), key=lambda item: item[0])]


def find_transcripts(roots: list[Path], since_days: float | None) -> list[Path]:
    """Main-thread transcripts, ``<root>/<slug>/<session>.jsonl``, oldest first.

    ``since_days`` keeps files modified in that many days (None keeps all). A
    file reached through two roots is listed once, under the first root's path.
    A file that vanishes during the scan is left out.
    """

    return _find(roots, "*/*.jsonl", since_days, in_subagents_dir=False)


def find_subagent_transcripts(roots: list[Path], since_days: float | None) -> list[Path]:
    """Subagent transcripts, ``<root>/<slug>/<session>/subagents/**/*.jsonl``, oldest first.

    Plain Agent/Task subagents and Workflow agents alike. A run's
    ``journal.jsonl`` is skipped, and so is anything that is not a regular
    file. ``since_days``, deduplication and a vanished file work as in
    ``find_transcripts``.
    """

    return _find(roots, "*/*/subagents/**/*.jsonl", since_days, in_subagents_dir=True)


def is_subagent_transcript(path: Path) -> bool:
    """True for a file under a session's ``subagents/`` directory.

    Judged from the path alone, by any parent component named ``subagents``.
    Known limit: a root that itself sits under a directory of that name
    (``CLAUDE_CONFIG_DIR=/x/subagents``) makes every transcript under it a
    subagent's. Not anchored tighter on purpose: ``find_subagent_transcripts``
    accepts any depth below ``subagents/``, so that a layout Claude Code adds
    later is still found, and a classifier that knew only today's two layouts
    would disagree with it.
    """

    return "subagents" in path.parts[:-1]


def session_id(path: Path) -> str:
    """The lead session a transcript belongs to: the file stem, or the directory above ``subagents/``.

    Counting distinct sessions needs this: a subagent's file name is its agent
    id, and its records' ``sessionId`` is the lead's. The innermost
    ``subagents`` component is used; the limit ``is_subagent_transcript``
    names applies here too.
    """

    parts = path.parts[:-1]
    if "subagents" in parts:
        at = len(parts) - 1 - parts[::-1].index("subagents")
        if at > 0:
            return parts[at - 1]
    return path.stem


# ─── Records ────────────────────────────────────────────────────────────────


def _bump(tally: dict[str, int] | None, key: str) -> None:
    if tally is not None:
        tally[key] = tally.get(key, 0) + 1


def iter_records(path: Path, tally: dict[str, int] | None = None) -> Iterator[dict[str, Any]]:
    """Each JSON object in a transcript, in file order. Bad lines are skipped, not fatal.

    Lines are split on ``\\n`` only. ``str.splitlines()`` also splits on
    U+2028/U+2029/U+0085, which JSON leaves raw inside strings, and turns one
    record into two unparseable halves. Bytes that are not UTF-8 are replaced.

    A blank line is ignored. A line that is not JSON, or is JSON but not an
    object, is counted ``malformed``. A last line with no newline that does not
    parse is counted ``truncated``: a session killed mid-write, or one still
    being written while it is read. Every record yielded is counted
    ``records``. Pass ``tally`` to receive those counts, so a report can say
    what it could not read instead of reading it as nothing.

    An OSError opening or reading the file propagates. A transcript that cannot
    be read is unknowable, which is not the same thing as empty.
    """

    with open(path, encoding="utf-8", errors="replace", newline="\n") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                _bump(tally, "malformed" if line.endswith("\n") else "truncated")
                continue
            if not isinstance(record, dict):
                _bump(tally, "malformed")
                continue
            _bump(tally, "records")
            yield record


# ─── Tool calls and their results ───────────────────────────────────────────


@dataclass
class ToolEvent:
    """One tool call and, once it arrived, its result.

    ``index`` and ``result_index`` are positions in the record sequence passed
    to ``tool_events`` (with ``iter_records``, the n-th parsed record, not the
    file line). ``result`` is None until a result arrives: a call in flight, or
    a session killed mid-call. It is never clipped: the whole text the
    transcript holds, which for a persisted output is Claude Code's preview
    (it starts ``<persisted-output>`` and names the file holding the full
    output). ``is_error`` is None without a result and False when the result
    omits the flag.

    ``timed_out_ms``, ``interrupted`` and ``persisted_output`` are read only
    from a ``toolUseResult`` OBJECT, and only Bash's object holds them (the
    module docstring has the counts). For a Bash call whose object is there,
    ``interrupted`` is a bool (False on every one seen), and None in
    ``timed_out_ms`` or ``persisted_output`` means "no". So, on the data seen,
    ``interrupted is not None`` tells "this Bash call's object was read".
    Anywhere else None means "not recorded", not "no": any other tool (a
    persisted Grep, WebFetch or MCP result has ``persisted_output`` None even
    on the main thread), an error or denied result (a string there), and a
    success with no object, which is nearly every Workflow agent success and
    some plain Agent ones. A timeout or persisted output with no object still
    shows in ``result`` by its text template; this module does not parse it.
    ``denial_kind`` comes from ``toolDenialKind``, which all three transcript
    kinds carry beside a denied result's error string.
    """

    id: str
    name: str
    input: dict[str, Any]
    index: int
    timestamp: str | None
    agent_id: str | None
    result: str | None = None
    is_error: bool | None = None
    result_index: int | None = None
    result_timestamp: str | None = None
    denial_kind: str | None = None
    timed_out_ms: int | None = None
    interrupted: bool | None = None
    persisted_output: str | None = None


def result_text(content: object) -> str:
    """A tool_result's ``content`` as one string, in full.

    A string is returned as it is. A list contributes each ``text`` item's text
    and a ``[image]`` or ``[tool_reference: <tool>]`` marker for the rest, one
    per line, so an image result is not mistaken for an empty one.
    """

    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for item in content:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "text":
            parts.append(str(item.get("text") or ""))
        elif kind == "tool_reference":
            parts.append(f"[tool_reference: {item.get('tool_name') or '?'}]")
        else:
            parts.append(f"[{kind or 'unknown'}]")
    return "\n".join(parts)


def _attach_result(event: ToolEvent, block: dict[str, Any], record: dict[str, Any], index: int) -> None:
    event.result = result_text(block.get("content"))
    event.is_error = bool(block.get("is_error"))
    event.result_index = index
    event.result_timestamp = record.get("timestamp")
    denial = record.get("toolDenialKind")
    event.denial_kind = denial if isinstance(denial, str) else None
    meta = record.get("toolUseResult")
    if isinstance(meta, dict):
        timed_out = meta.get("timedOutAfterMs")
        event.timed_out_ms = timed_out if isinstance(timed_out, int) else None
        interrupted = meta.get("interrupted")
        event.interrupted = interrupted if isinstance(interrupted, bool) else None
        persisted = meta.get("persistedOutputPath")
        event.persisted_output = persisted if isinstance(persisted, str) else None


def tool_events(records: Iterable[dict[str, Any]], tally: dict[str, int] | None = None) -> list[ToolEvent]:
    """Every tool call in ``records``, paired with its result by id, in call order.

    Reads any record whose ``message.content`` is a list, whatever its
    ``type``, so a fixture need not spell out every field. Only the record's own
    ``message`` is read: an older transcript nesting a subagent's messages under
    ``data`` does not have them counted as the lead's calls. One pass, so a
    generator such as ``iter_records(path)`` is fine.

    Counted in ``tally``: ``orphan_results`` (a result whose call is not in the
    records: a transcript that starts mid-conversation), ``duplicate_calls`` and
    ``duplicate_results`` (an id seen again; the first one is kept).
    """

    events: dict[str, ToolEvent] = {}
    for index, record in enumerate(records):
        message = record.get("message") if isinstance(record, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "tool_use":
                call_id = block.get("id")
                if not isinstance(call_id, str):
                    continue
                if call_id in events:
                    _bump(tally, "duplicate_calls")
                    continue
                payload = block.get("input")
                agent = record.get("agentId")
                events[call_id] = ToolEvent(
                    id=call_id,
                    name=str(block.get("name") or ""),
                    input=payload if isinstance(payload, dict) else {},
                    index=index,
                    timestamp=record.get("timestamp"),
                    agent_id=agent if isinstance(agent, str) else None,
                )
            elif kind == "tool_result":
                event = events.get(str(block.get("tool_use_id")))
                if event is None:
                    _bump(tally, "orphan_results")
                elif event.result_index is not None:
                    _bump(tally, "duplicate_results")
                else:
                    _attach_result(event, block, record, index)
    return list(events.values())


# ─── Hook attachments ───────────────────────────────────────────────────────

# The hook kinds seen on 2.1.283. ``is_hook_attachment`` accepts any
# ``hook_*`` kind, so a new one is reported rather than dropped; this set is
# the documentation, not the filter.
HOOK_ATTACHMENT_KINDS = frozenset({
    "hook_success",
    "hook_additional_context",
    "hook_non_blocking_error",
    "hook_blocking_error",
    "hook_cancelled",
    "hook_permission_decision",
    "hook_system_message",
    "async_hook_response",
})


@dataclass
class HookAttachment:
    """One hook outcome Claude Code wrote into a transcript.

    The named fields are the ones the kinds above share, None where a kind does
    not carry one. ``blocking_error`` is the text of a ``hook_blocking_error``.
    ``raw`` is the attachment object itself, for any field not named here.
    """

    kind: str
    hook_event: str | None
    hook_name: str | None
    tool_use_id: str | None
    index: int
    timestamp: str | None
    agent_id: str | None
    command: str | None = None
    exit_code: int | None = None
    duration_ms: int | None = None
    content: str | None = None
    stdout: str | None = None
    stderr: str | None = None
    blocking_error: str | None = None
    decision: str | None = None
    timed_out: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def is_hook_attachment(kind: object) -> bool:
    """True for ``hook_*`` attachment kinds and ``async_hook_response``."""

    return isinstance(kind, str) and (kind.startswith("hook_") or kind == "async_hook_response")


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def attachments(records: Iterable[dict[str, Any]]) -> Iterator[HookAttachment]:
    """The hook attachments in ``records``, in order; every other attachment is skipped.

    ``index`` is the record's position in ``records``. A Stop hook also shows up
    in the ``stop_hook_summary`` system record; that record is not an attachment
    and is not yielded.
    """

    for index, record in enumerate(records):
        if not isinstance(record, dict) or record.get("type") != "attachment":
            continue
        body = record.get("attachment")
        if not isinstance(body, dict) or not is_hook_attachment(body.get("type")):
            continue
        blocking = body.get("blockingError")
        if isinstance(blocking, dict):
            blocking = blocking.get("blockingError")
        timed_out = body.get("timedOut")
        yield HookAttachment(
            kind=str(body["type"]),
            hook_event=_text(body.get("hookEvent")),
            hook_name=_text(body.get("hookName")),
            tool_use_id=_text(body.get("toolUseID")),
            index=index,
            timestamp=_text(record.get("timestamp")),
            agent_id=_text(record.get("agentId")),
            command=_text(body.get("command")),
            exit_code=_int(body.get("exitCode")),
            duration_ms=_int(body.get("durationMs")),
            content=_text(body.get("content")),
            stdout=_text(body.get("stdout")),
            stderr=_text(body.get("stderr")),
            blocking_error=_text(blocking),
            decision=_text(body.get("decision")),
            timed_out=timed_out if isinstance(timed_out, bool) else None,
            raw=body,
        )


# ─── Heredocs ───────────────────────────────────────────────────────────────

# `<<WORD`, `<<'WORD'`, `<<"WORD"`, `<<\WORD` and `<<-WORD`, never the
# here-string `<<<`.
_HEREDOC = re.compile(r"""(?<!<)<<(-?)[ \t]*\\?["']?([A-Za-z_][A-Za-z0-9_]*)["']?""")


def strip_heredocs(command: str) -> str:
    """``command`` with every heredoc BODY removed. The line that opens one is kept.

    Agents write files through ``python3 - <<'EOF'`` and ``cat > f <<EOF``, and
    the body is often prose ABOUT a command: a README documenting ``git
    checkout``, a fixture holding ``rm -rf``. Classify the command, not its
    data. The Python twin of ``rd_strip_heredocs`` in
    ``configs/hooks/revert-detector.sh``, with two differences: every heredoc
    opened on a line is tracked, in order, where the shell version tracks only
    the first; and the backslash-quoted ``<<\\WORD`` is recognised, which the
    shell version's pattern does not. A ``<<-`` terminator may be indented with
    tabs.

    Known limits, all failing toward stripping too much: a ``<<word`` inside a
    quoted string or an arithmetic ``$((a<<b))`` opens a heredoc that is never
    closed; so does a delimiter holding a character outside ``[A-Za-z0-9_]``
    (``<<END-OF-FILE``, ``<<'EOF.txt'``), of which only the leading identifier
    is captured, so its real terminator never matches. Each swallows the rest of
    the command.
    """

    kept: list[str] = []
    pending: list[tuple[str, bool]] = []
    for line in command.split("\n"):
        if pending:
            delimiter, tabs = pending[0]
            if (line.lstrip("\t") if tabs else line) == delimiter:
                pending.pop(0)
            continue
        kept.append(line)
        pending = [(m.group(2), bool(m.group(1))) for m in _HEREDOC.finditer(line)]
    return "\n".join(kept)


# ─── Self-test ──────────────────────────────────────────────────────────────
# Not a CLI. What this module does is pinned by orchestrator/tests/
# test_transcripts.py; `--self-test` runs the self-tests of the scripts that
# import it, for test_self_tests_can_fire.py, which mutates a guard in this
# file and needs an entry point here that notices. Each consumer runs under a
# fresh bytecode cache: a .pyc is trusted when the source's size and
# whole-second mtime match, so a mutation and its restore of the same length
# within one second would otherwise run the stale one.
_CONSUMERS = ("workflow-scorecard.py", "keep-sessions.py")


def _self_test() -> int:
    here = Path(__file__).resolve().parent
    worst = 0
    with tempfile.TemporaryDirectory() as cache:
        for name in _CONSUMERS:
            code = subprocess.call(
                [sys.executable, "-X", f"pycache_prefix={cache}", str(here / name), "--self-test"]
            )
            worst = worst or code
    return worst


if __name__ == "__main__":
    if sys.argv[1:] != ["--self-test"]:
        print(
            "usage: transcripts.py --self-test   (a library: it runs the self-tests of "
            + ", ".join(_CONSUMERS)
            + ")",
            file=sys.stderr,
        )
        sys.exit(2)
    sys.exit(_self_test())
