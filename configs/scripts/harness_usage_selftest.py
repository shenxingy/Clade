#!/usr/bin/env python3
"""harness_usage_selftest.py — the controls behind harness-usage.py's self-test.

Every check drives harness-usage.py's ``main()``, the entry point the owner
runs, under a temporary HOME that holds fixture transcripts, two profiles'
``.claude.json`` and a fixture Clade checkout passed as ``--repo``. Nothing
reads the real HOME, and nothing touches the network.

What is proven checked is the list in orchestrator/tests/can_fire/harness_usage.py:
each entry removes one guard from harness-usage.py and must turn this red. A
guard that list does not name is not claimed checked, and not every rule has
both a positive and a negative control. Not covered: the advisory lock (two
processes racing would make the check flaky; it is the Workflow ledger's own
``_lock``), and a project dir that exists and cannot be listed (making one needs
a permission the test cannot rely on: root ignores it); the same branch is
checked through a ``projects`` that is a file.

Stdlib only: the syntax-check CI job installs no dependencies.
"""

from __future__ import annotations

import contextlib
import datetime
import io
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterator

_UTC = datetime.timezone.utc
_TODAY = datetime.datetime.now(_UTC).date()


def _ts(days_ago: int, hour: int = 12) -> str:
    """Midday ``days_ago`` UTC days back; today's events sit at midnight, so they are never in the future."""

    base = datetime.datetime.combine(_TODAY - datetime.timedelta(days=days_ago), datetime.time(), _UTC)
    return (base + datetime.timedelta(hours=0 if days_ago == 0 else hour)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _ms(days_ago: int) -> int:
    return int(datetime.datetime.fromisoformat(_ts(days_ago).replace("Z", "+00:00")).timestamp() * 1000)


def _day(days_ago: int) -> str:
    return (_TODAY - datetime.timedelta(days=days_ago)).isoformat()


def _iso(days_ago: int) -> str:
    """``_ts`` as the report prints a timestamp: no milliseconds."""

    return _ts(days_ago).replace(".000Z", "Z")


D1, D3, OLD = 1, 3, 40

# ─── Fixture checkout ───────────────────────────────────────────────────────

# beta-pr sits beside beta the way the real tree's review-pr sits beside review: a prefix that is a skill but not a
# hub family does not make a sub-skill.
SKILLS = ("alpha", "beta", "beta-pr", "gamma", "delta", "errs", "subby", "blog", "blog-write", "blog-audit")


def _hook(command: str, **extra: Any) -> dict[str, Any]:
    return {"type": "command", "command": command, **extra}


HOOKS = {
    "PreToolUse": [
        {"matcher": "Bash", "hooks": [_hook("~/.claude/hooks/guard.sh"), _hook("~/.claude/hooks/rev.sh", **{"async": True})]},
        {"matcher": "Edit|Write", "hooks": [_hook("~/.claude/hooks/lint-guard.sh")]},
    ],
    "PostToolUse": [
        # drain.sh is wired here and under "*": two wirings that both match an Edit, which counts once.
        {"matcher": "Edit|Write", "hooks": [_hook("~/.claude/hooks/inject.sh"),
                                            _hook("~/.claude/hooks/suggest.sh", statusMessage="Suggesting skills..."),
                                            _hook("~/.claude/hooks/drain.sh")]},
        {"matcher": "Bash", "hooks": [_hook("~/.claude/hooks/mem.sh", **{"async": True}),
                                      _hook("~/.claude/hooks/ckpt.sh", **{"async": True})]},
        {"matcher": "*", "hooks": [_hook("~/.claude/hooks/drain.sh")]},
    ],
    "SessionStart": [
        {"matcher": "startup", "hooks": [_hook("~/.claude/hooks/ctx.sh", statusMessage="Loading project context..."),
                                         _hook("~/.claude/hooks/slow.sh", statusMessage="Reading lessons...")]},
    ],
    "UserPromptSubmit": [{"hooks": [_hook("~/.claude/hooks/corr.sh"), _hook("~/.claude/hooks/track.sh")]}],
    "PermissionRequest": [{"hooks": [_hook("~/.claude/hooks/perm.sh")]}],
    "Stop": [{"hooks": [_hook("~/.claude/hooks/loop.sh"),
                        {"type": "prompt", "prompt": "done?", "statusMessage": "Checking completion..."},
                        _hook("~/.claude/hooks/check.sh")]}],
    "Notification": [{"hooks": [_hook("~/.claude/hooks/quiet.sh", **{"async": True})]}],
    "PostToolUseFailure": [{"hooks": [_hook("~/.claude/hooks/fail.sh")]}],
    "PreCompact": [{"hooks": [_hook("bash ~/.claude/hooks/precompact.sh")]}],
}

# The scripts behind two UserPromptSubmit hooks, for attribution by the literal a message opens with. Each
# literal is followed by a value the hook fills in: a quote, a bracket, or (track.sh) a name, which the
# 40-character cap stops short of. track.sh also says "note", the fixture's too-short message.
SOURCES = {
    "corr.sh": 'echo "Correction noticed (word: \'$K\') in it"\n',
    "track.sh": '# note: counts briefs\necho "Brief repeated across sessions, most recently by $WHO"\n',
}


def _write_repo(repo: Path) -> None:
    for name in SKILLS:
        folder = repo / "configs" / "skills" / name
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: fixture {name}\n---\nbody\n")
    (repo / "configs" / "settings-hooks.json").write_text(json.dumps({"hooks": HOOKS}))
    (repo / "configs" / "hooks").mkdir()
    for name, text in SOURCES.items():
        (repo / "configs" / "hooks" / name).write_text(text)


# ─── Fixture transcripts ────────────────────────────────────────────────────

_counter = [0]


def _uuid() -> str:
    _counter[0] += 1
    return f"u{_counter[0]:04d}"


def _call(tool_id: str, name: str, payload: dict[str, Any], days_ago: int, result: str = "ok",
          error: bool = False, denial: str | None = None, agent: str | None = None) -> list[dict[str, Any]]:
    call: dict[str, Any] = {"type": "assistant", "uuid": _uuid(), "timestamp": _ts(days_ago),
                            "message": {"content": [{"type": "tool_use", "id": tool_id, "name": name, "input": payload}]}}
    done: dict[str, Any] = {"type": "user", "uuid": _uuid(), "timestamp": _ts(days_ago), "message": {"content": [
        {"type": "tool_result", "tool_use_id": tool_id, "content": result, "is_error": error}]}}
    if denial:
        done["toolDenialKind"] = denial
    if agent:
        call["agentId"] = done["agentId"] = agent
    return [call, done]


def _att(days_ago: int, kind: str, **body: Any) -> dict[str, Any]:
    return {"type": "attachment", "uuid": _uuid(), "timestamp": _ts(days_ago), "attachment": {"type": kind, **body}}


def _ctx(text: str, event: str = "PostToolUse") -> str:
    return json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}})


def _start(days_ago: int, kind: str, hook_id: str, **body: Any) -> dict[str, Any]:
    return _att(days_ago, kind, hookName="SessionStart:startup", hookEvent="SessionStart", toolUseID=hook_id, **body)


def _wide(days_ago: int, event: str, text: str) -> dict[str, Any]:
    """An event-wide context trace: hookName is the bare event and the id is its own, as SessionStart writes it."""

    return _att(days_ago, "hook_additional_context", hookName=event, hookEvent=event, toolUseID=f"{event}-x",
                content=[text])


def _typed(days_ago: int, text: str, **extra: Any) -> dict[str, Any]:
    return {"type": "user", "uuid": _uuid(), "timestamp": _ts(days_ago), "message": {"content": text}, **extra}


def _main_records() -> list[dict[str, Any]]:
    edit = {"hookName": "PostToolUse:Edit", "hookEvent": "PostToolUse", "toolUseID": "t8"}
    return [
        *_call("t1", "Skill", {"skill": "alpha"}, D1),
        *_call("t2", "Skill", {"skill": "/alpha", "args": "x"}, D1),
        *_call("t3", "Skill", {"skill": "clade:blog-write"}, D1),
        *_call("t4", "Skill", {"skill": "errs"}, D1, result="Unknown skill", error=True),
        *_call("t5", "Skill", {"skill": "elsewhere"}, D1),
        *_call("t11", "Skill", {"skill": "beta"}, D1, result="Permission to use Skill has been denied.", error=True,
               denial="permission-rule"),
        *_call("t6", "Skill", {"skill": "alpha"}, OLD),
        {"type": "user", "uuid": _uuid(), "timestamp": _ts(D1),
         "message": {"content": "<command-message>beta</command-message>\n<command-name>/beta</command-name>"}},
        *_call("t7", "Bash", {"command": "rm -rf /"}, D3, result="PreToolUse:Bash hook error: refused",
               error=True, denial="permission-rule"),
        *_call("t8", "Edit", {"file_path": "x"}, D1),
        _att(D1, "hook_success", command="~/.claude/hooks/inject.sh", content="", **edit,
             stdout=json.dumps({**json.loads(_ctx("A")), "systemMessage": "Heads up"})),
        _att(D1, "hook_success", command="Suggesting skills...", stdout=_ctx("B"), content="", **edit),
        _att(D1, "hook_additional_context", content="A", **edit),
        _att(D1, "hook_additional_context", content="B", **edit),
        # A system message pairs by the systemMessage its success handed over, not by additionalContext.
        _att(D1, "hook_system_message", content="Heads up", **edit),
        _att(D1, "hook_blocking_error", blockingError={"blockingError": "no", "command": "~/.claude/hooks/inject.sh"},
             **edit),
        _att(D1, "async_hook_response", hookName="PostToolUse:Bash", hookEvent="PostToolUse", exitCode=1, stdout="",
             stderr="/h/.claude/hooks/mem.sh: line 57: FILE_PATH: unbound variable", response={}, processId=1),
        _att(D1, "async_hook_response", hookName="PreToolUse:Bash", hookEvent="PreToolUse", exitCode=0, stdout="",
             stderr="", response={}, processId=2),
        _att(D1, "hook_additional_context", hookName="UserPromptSubmit", hookEvent="UserPromptSubmit",
             toolUseID="opaque-1", content=["note"]),
        _att(D1, "hook_permission_decision", hookEvent="PermissionRequest", toolUseID="t8", decision="allow"),
        _att(D1, "hook_cancelled", command="Reading lessons...", hookName="SessionStart:startup",
             hookEvent="SessionStart", toolUseID="opaque-2", timedOut=True, timeoutMs=15000),
        _att(D1, "hook_success", command="Loading project context...", hookName="SessionStart:startup",
             hookEvent="SessionStart", toolUseID="opaque-3", stdout="", content=""),
        _att(D1, "hook_non_blocking_error", command="~/.claude/hooks/guard.sh", hookName="PreToolUse:Bash",
             hookEvent="PreToolUse", toolUseID="t7", stderr="line 9: oops", exitCode=1),
        _att(D1, "hook_success", command="/tmp/elsewhere/guard.sh", hookName="PreToolUse:Bash",
             hookEvent="PreToolUse", toolUseID="t7", stdout="x", content=""),
        _att(D1, "hook_success", command="~/.claude/hooks/new-thing.sh", hookName="PostToolUse:Bash",
             hookEvent="PostToolUse", toolUseID="t7", stdout="x", content=""),
        {"type": "system", "subtype": "stop_hook_summary", "uuid": _uuid(), "timestamp": _ts(D1),
         "hookInfos": [{"command": "~/.claude/hooks/loop.sh"}, {"command": "~/.claude/hooks/check.sh"},
                       {"command": "Checking completion...", "promptText": "done?"}]},
        _att(D1, "hook_success", command="~/.claude/hooks/check.sh", hookName="Stop", hookEvent="Stop",
             toolUseID="opaque-4", stdout="", content=""),
        _att(D1, "hook_non_blocking_error", command="Checking completion...", hookName="Stop", hookEvent="Stop",
             toolUseID="opaque-4", stderr="", exitCode=1),
        _att(OLD, "hook_success", command="~/.claude/hooks/drain.sh", hookName="PostToolUse:Read",
             hookEvent="PostToolUse", toolUseID="t0", stdout="x", content=""),
        # No hook_success beside it: drain.sh is the one synchronous hook a "*" matcher wires on Read.
        _att(D1, "hook_additional_context", hookName="PostToolUse:Read", hookEvent="PostToolUse",
             toolUseID="t10", content="read note"),
        # An event no Clade hook is wired on: foreign, not unattributed.
        _att(D1, "hook_additional_context", hookName="TeammateIdle", hookEvent="TeammateIdle",
             toolUseID="opaque-5", content="idle"),
        # UserPromptSubmit writes no success, so the message names its hook by the literal it opens with.
        _wide(D1, "UserPromptSubmit", "Correction noticed (word: 'nope') in it"),
        _wide(D1, "UserPromptSubmit", "Brief repeated across sessions, most recently by someone"),
        # A typed /gamma inside a meta record is a skill Claude Code attached, and a bare name is not typed.
        _typed(D1, "<command-name>/gamma</command-name>", isMeta=True),
        _typed(D1, "<command-name>delta</command-name>"),
        # Burst 1: two SessionStart hooks hand JSON context; the event-wide trace carries slow.sh's.
        _start(D1, "hook_success", "s-1", command="Loading project context...", stdout=_ctx("S1", "SessionStart")),
        _start(D1, "hook_success", "s-2", command="Reading lessons...", stdout=_ctx("S2", "SessionStart")),
        _wide(D1, "SessionStart", "S2"),
        _typed(D1, "a typed prompt ends the burst"),
        # Burst 2: the context was persisted, so no content matches: the one success that handed JSON context.
        _start(D1, "hook_success", "s-3", command="Loading project context...", stdout=_ctx("S3", "SessionStart")),
        _start(D1, "hook_success", "s-4", command="Reading lessons...", stdout="plain lessons", content="plain"),
        _wide(D1, "SessionStart", "<persisted-output>\nOutput too large"),
        _typed(D1, "a typed prompt ends the burst"),
        # Burst 3: nothing on SessionStart since the last typed prompt: two candidates, unattributed, a fire.
        _wide(D1, "SessionStart", "S1"),
        {"type": "system", "subtype": "compact_boundary", "uuid": _uuid(), "timestamp": _ts(D1)},
    ]


def _write_lines(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def _first(records: list[dict[str, Any]], test: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    return next(record for record in records if test(record))


def _write_home(home: Path, broken: bool = True) -> None:
    project = home / ".claude" / "projects" / "-p"
    records = _main_records()
    _write_lines(project / "s1.jsonl", records)
    # A forked session copies records it inherited: same tool ids, same uuids. Each is counted once: a tool call,
    # an attachment, a typed /name, a stop_hook_summary and a compaction.
    _write_lines(project / "s2.jsonl", records[:2] + [
        _first(records, lambda r: r["type"] == "attachment"),
        _first(records, lambda r: "<command-name>/beta" in str(r.get("message", {}).get("content"))),
        _first(records, lambda r: r.get("subtype") == "stop_hook_summary"),
        _first(records, lambda r: r.get("subtype") == "compact_boundary"),
    ])
    # The subagent's hook error is older than the main thread's last inject.sh trace: merged after it, it must
    # not move the last fire back.
    subagent = [*_call("t9", "Skill", {"skill": "subby"}, D1, agent="a1"),
                _att(D3, "hook_non_blocking_error", command="~/.claude/hooks/inject.sh", hookName="PostToolUse:Edit",
                     hookEvent="PostToolUse", toolUseID="t9", stderr="", exitCode=1)]
    _write_lines(project / "s1" / "subagents" / "agent-a1.jsonl", subagent)
    if broken:
        (project / "broken.jsonl").mkdir()  # matched by the main-thread glob, cannot be opened: unreadable, not empty
    (home / ".claude.json").write_text(json.dumps({"skillUsage": {
        "alpha": {"usageCount": 5, "lastUsedAt": _ms(D1)},
        "gamma": {"usageCount": 3, "lastUsedAt": _ms(2)},
        "delta": {"usageCount": 1, "lastUsedAt": _ms(90)},
    }}))
    profile = home / ".claude-profiles" / "p1"
    profile.mkdir(parents=True)
    # gamma's newest use is in the profile read FIRST: the later profile's older lastUsedAt must not replace it.
    (profile / ".claude.json").write_text(json.dumps({"skillUsage": {
        "clade:alpha": {"usageCount": 2, "lastUsedAt": _ms(100)},
        "elsewhere": {"usageCount": 9, "lastUsedAt": _ms(D1)},
        "gamma": {"usageCount": 1, "lastUsedAt": _ms(100)},
    }}))


def _old_transcript(path: Path, days_ago: int) -> None:
    """A transcript last written ``days_ago`` days back: the oldest survivor of an earlier cleanup."""

    _write_lines(path, [_typed(days_ago, "an old session")])
    stamp = datetime.datetime.fromisoformat(_ts(days_ago).replace("Z", "+00:00")).timestamp()
    os.utime(path, (stamp, stamp))


# ─── Running main() ─────────────────────────────────────────────────────────


@contextlib.contextmanager
def _home(home: Path, config_dir: Path | None = None) -> Iterator[None]:
    saved = {key: os.environ.get(key) for key in ("HOME", "CLAUDE_CONFIG_DIR")}
    os.environ["HOME"] = str(home)
    if config_dir is None:
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
    else:
        os.environ["CLAUDE_CONFIG_DIR"] = str(config_dir)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _invoke(main: Callable[[list[str]], int], home: Path, repo: Path, argv: list[str],
            config_dir: Path | None = None) -> tuple[object, str, str]:
    """(exit code, stdout, stderr) of one main() call; the code is a 'raised …' string when it crashed."""

    out, err = io.StringIO(), io.StringIO()
    with _home(home, config_dir), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code: object = main(["--repo", str(repo), *argv])
        except Exception as exc:  # a crash is a failed control, reported with the rest
            code = f"raised {type(exc).__name__}: {exc}"
    return code, out.getvalue(), err.getvalue()


def _run(main: Callable[[list[str]], int], home: Path, repo: Path, argv: list[str],
         failures: list[str], expect: int = 0, config_dir: Path | None = None) -> str:
    code, out, _ = _invoke(main, home, repo, argv, config_dir)
    if code != expect:
        failures.append(f"{argv}: exit {code}, expected {expect}")
    return out


def _json(text: str, failures: list[str], what: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except ValueError:
        failures.append(f"{what}: output is not JSON")
        return {}
    return value if isinstance(value, dict) else {}


def _by_name(report: dict[str, Any], section: str) -> dict[str, dict[str, Any]]:
    return {row["name"]: row for row in report.get(section) or []}


def _expect(failures: list[str], what: str, actual: object, expected: object) -> None:
    if actual != expected:
        failures.append(f"{what}: expected {expected!r}, got {actual!r}")


# ─── Controls ───────────────────────────────────────────────────────────────


def _report_checks(main: Callable[[list[str]], int], home: Path, repo: Path, failures: list[str]) -> None:
    report = _json(_run(main, home, repo, ["--json"], failures), failures, "report")
    skills, hooks = _by_name(report, "skills"), _by_name(report, "hooks")
    s = lambda name, key: skills.get(name, {}).get(key)  # noqa: E731
    h = lambda name, key: hooks.get(name, {}).get(key)  # noqa: E731

    # Skills: the Skill tool, prefix spellings, slash commands, errors, the window, the fork.
    _expect(failures, "alpha fires (two calls, '/alpha' stripped; the 40-day-old call and the fork's copy left out)",
            s("alpha", "fires"), 2)
    _expect(failures, "alpha tool calls", s("alpha", "tool"), 2)
    _expect(failures, "clade:blog-write counts as blog-write", s("blog-write", "fires"), 1)
    _expect(failures, "a typed /beta is a slash fire, its fork copy is not; a denied Skill call is a deny",
            tuple(s("beta", key) for key in ("fires", "tool", "slash", "denies", "rejections")), (2, 1, 1, 1, 0))
    _expect(failures, "an errored Skill call is a rejection", (s("errs", "fires"), s("errs", "rejections")), (1, 1))
    _expect(failures, "a subagent's Skill call is not main thread", s("subby", "fires"), 0)
    _expect(failures, "a skill Clade does not ship is foreign", report.get("foreign", {}).get("skill_calls"), 1)
    _expect(failures, "skillUsage sums profiles and the clade: spelling", s("alpha", "lifetime"), 7)
    _expect(failures, "skillUsage lastUsedAt in the window counts as use", s("gamma", "used_in_window"), True)
    _expect(failures, "the newest lastUsedAt across profiles wins, not the profile read last",
            s("gamma", "lifetime_last"), _iso(2))
    _expect(failures, "a prefix that is a shipped skill but not a hub family makes no sub-skill",
            (s("beta-pr", "hub"), sorted(_by_name(report, "hubs"))), (None, ["blog"]))
    hubs = _by_name(report, "hubs")
    _expect(failures, "a hub's family includes its sub-skills", hubs.get("blog", {}).get("family_fires"), 1)
    never = report.get("never_fired") or {}
    _expect(failures, "never-fired skills (no fire, no lastUsedAt in the window; a used hub family is not listed)",
            never.get("skills"), ["beta-pr", "delta", "subby"])
    _expect(failures, "never-fired hub sub-skills", never.get("sub_skills"), ["blog-audit"])
    _expect(failures, "the never-fired label", never.get("label"), "review candidates, not retire candidates")

    # Hooks: every attribution rule.
    _expect(failures, "guard.sh: a PreToolUse deny with no attachment, plus a non-blocking error",
            (h("guard.sh", "fires"), h("guard.sh", "denies"), h("guard.sh", "rejections")), (2, 1, 1))
    _expect(failures, "inject.sh: its success, its paired context and system message, its blocking error",
            (h("inject.sh", "fires"), h("inject.sh", "context"), h("inject.sh", "denies")), (2, 2, 1))
    _expect(failures, "suggest.sh: named by its statusMessage, context paired by content",
            (h("suggest.sh", "fires"), h("suggest.sh", "context")), (1, 1))
    _expect(failures, "mem.sh: an async failure named by its stderr", (h("mem.sh", "fires"), h("mem.sh", "rejections")),
            (1, 1))
    _expect(failures, "ckpt.sh: the other async candidate gets nothing", h("ckpt.sh", "fires"), 0)
    _expect(failures, "rev.sh: the only ASYNC hook on PreToolUse:Bash", h("rev.sh", "fires"), 1)
    _expect(failures, "perm.sh: a permission decision with no hookName", h("perm.sh", "fires"), 1)
    _expect(failures, "slow.sh: a cancelled hook is a timeout; two successes, named by statusMessage",
            (h("slow.sh", "fires"), h("slow.sh", "timeouts")), (3, 1))
    _expect(failures, "ctx.sh: three successes named by statusMessage", h("ctx.sh", "fires"), 3)
    _expect(failures, "an event-wide context goes to the success in its burst that handed it that text",
            h("slow.sh", "context"), 1)
    _expect(failures, "a persisted context goes to the one success in its burst that handed JSON context",
            h("ctx.sh", "context"), 1)
    _expect(failures, "a UserPromptSubmit message is its hook's by the literal it opens with, up to a quote",
            (h("corr.sh", "fires"), h("corr.sh", "context")), (1, 1))
    _expect(failures, "... and up to 40 characters, short of a name the hook filled in",
            (h("track.sh", "fires"), h("track.sh", "context")), (1, 1))
    _expect(failures, "a meta record's /gamma and a bare <command-name>delta are not typed commands",
            (s("gamma", "fires"), s("delta", "fires")), (0, 0))
    events = {name: h(name, "events") for name in ("guard.sh", "lint-guard.sh", "inject.sh", "drain.sh", "fail.sh",
                                                   "precompact.sh", "perm.sh")}
    _expect(failures, "wired events: calls, results by matcher, failures that are not denials, compactions (the "
            "fork's copy not again); an Edit counts once for drain.sh's two wirings; None where the event is not in "
            "a transcript", events,
            {"guard.sh": 1, "lint-guard.sh": 1, "inject.sh": 1, "drain.sh": 5, "fail.sh": 1, "precompact.sh": 1,
             "perm.sh": None})
    _expect(failures, "Stop hooks: one fire per stop_hook_summary entry, the hook_success and the fork's copy of "
            "the summary not counted again",
            (h("loop.sh", "fires"), h("check.sh", "fires"), h("Stop prompt hook", "fires")), (1, 1, 1))
    _expect(failures, "a Stop hook's error is an outcome, not a second fire", h("Stop prompt hook", "rejections"), 1)
    _expect(failures, "drain.sh: the only candidate through its '*' matcher; the 40-day-old trace is outside",
            (h("drain.sh", "fires"), h("drain.sh", "context")), (1, 1))
    _expect(failures, "foreign: a shipped basename outside hooks/, a script Clade does not ship, an unwired event",
            report.get("foreign", {}).get("hook_traces"), 3)
    _expect(failures, "a command-less trace with two candidates and nothing to pair it with is unattributed, "
            "and a burst ends at the first record that is not an attachment",
            [(u.get("label"), u.get("fires"), u.get("context"), u.get("candidates"))
             for u in report.get("unattributed") or []],
            [("SessionStart", 1, 1, ["ctx.sh", "slow.sh"]), ("UserPromptSubmit", 1, 1, ["corr.sh", "track.sh"])])
    _expect(failures, "a candidate that may hide in it says so", h("corr.sh", "may_hide_in"), ["UserPromptSubmit"])
    _expect(failures, "never-fired hooks", never.get("hooks"), ["ckpt.sh", "fail.sh", "precompact.sh", "quiet.sh"])
    _expect(failures, "a preventive hook is listed apart", never.get("preventive"), ["lint-guard.sh"])
    _expect(failures, "preventive means synchronous on PreToolUse", (h("guard.sh", "preventive"), h("rev.sh", "preventive")),
            (True, False))
    _expect(failures, "an unreadable transcript is counted, not read as empty", report.get("read", {}).get("unreadable"), 1)
    _expect(failures, "skillUsage profiles read", report.get("read", {}).get("usage_profiles"), 2)
    _expect(failures, "a 30-day window inside the retention is all live", report.get("window", {}).get("sources"),
            {"live": 30, "ledger": 0, "partial": 0})

    wide = _json(_run(main, home, repo, ["--json", "--include-subagents"], failures), failures, "subagents")
    wide_skills, wide_hooks = _by_name(wide, "skills"), _by_name(wide, "hooks")
    _expect(failures, "--include-subagents counts a subagent's Skill call", wide_skills.get("subby", {}).get("fires"), 1)
    _expect(failures, "--include-subagents counts a subagent's hook error",
            wide_hooks.get("inject.sh", {}).get("rejections"), 1)
    _expect(failures, "the last fire is the newest across scopes, not the scope merged last",
            wide_hooks.get("inject.sh", {}).get("last"), _iso(D1))

    longer = _json(_run(main, home, repo, ["--json", "--since", "50"], failures), failures, "since 50")
    _expect(failures, "--since 50 reaches the 40-day-old call and trace",
            (_by_name(longer, "skills").get("alpha", {}).get("fires"), _by_name(longer, "hooks").get("drain.sh", {}).get("fires")),
            (3, 2))
    _expect(failures, "past the retention with no ledger row, days are PARTIAL",
            longer.get("window", {}).get("sources"), {"live": 30, "ledger": 0, "partial": 20})

    text = _run(main, home, repo, [], failures)
    for phrase in ("REVIEW CANDIDATES, NOT RETIRE CANDIDATES", "Invocation is not behaviour change",
                   "within 60 s in one session is not counted", "zero fires never retires these", "UNATTRIBUTED",
                   "Zero traces is not zero runs", "lint-guard.sh (silent on 1 wired events)"):
        if phrase not in text:
            failures.append(f"text report: missing {phrase!r}")

    # The copy install.sh puts in ~/.claude/scripts/ resolves its default --repo to $HOME: no checkout there.
    code, out, err = _invoke(main, home, home, ["--json"])
    _expect(failures, "a --repo that is not a checkout exits 2 with a message naming --repo, not a traceback",
            (code, out, "pass --repo" in err), (2, "", True))


def _usage_checks(main: Callable[[list[str]], int], home: Path, repo: Path, failures: list[str]) -> None:
    """$CLAUDE_CONFIG_DIR's .claude.json is read, and one reached twice is read once."""

    link = home / "link-p1"  # CLAUDE_CONFIG_DIR spelled through a link to a profile already read
    link.symlink_to(home / ".claude-profiles" / "p1")
    twice = _json(_run(main, home, repo, ["--json"], failures, config_dir=link), failures, "config dir = profile")
    _expect(failures, "a profile reached again through $CLAUDE_CONFIG_DIR is read once",
            (twice.get("read", {}).get("usage_profiles"), _by_name(twice, "skills").get("alpha", {}).get("lifetime")),
            (2, 7))
    other = home / "elsewhere"
    other.mkdir()
    (other / ".claude.json").write_text(json.dumps({"skillUsage": {"delta": {"usageCount": 4,
                                                                              "lastUsedAt": _ms(D1)}}}))
    own = _json(_run(main, home, repo, ["--json"], failures, config_dir=other), failures, "config dir elsewhere")
    delta = _by_name(own, "skills").get("delta", {})
    _expect(failures, "$CLAUDE_CONFIG_DIR's own .claude.json is a profile",
            (own.get("read", {}).get("usage_profiles"), delta.get("lifetime"), delta.get("used_in_window")),
            (3, 5, True))


def _refused(main: Callable[[list[str]], int], home: Path, repo: Path, ledger: Path, failures: list[str],
             what: str, needle: str) -> None:
    """A ledger pass that must write nothing, exit 1 and name ``needle`` among its problems."""

    out = _run(main, home, repo, ["--ledger", "--ledger-path", str(ledger), "--json"], failures, expect=1)
    result = _json(out, failures, what)
    _expect(failures, f"{what}: the ledger is not written and the problem is named",
            (ledger.exists(), result.get("appended"), any(needle in p for p in result.get("refused") or [])),
            (False, 0, True))


def _ledger_checks(main: Callable[[list[str]], int], home: Path, repo: Path, failures: list[str]) -> None:
    ledger = home / "ledger.jsonl"
    project = home / ".claude" / "projects"
    # A day read short would be kept forever (the first row wins), so a pass that cannot read everything refuses.
    _refused(main, home, repo, ledger, failures, "an unreadable transcript", "broken.jsonl: unreadable transcript")
    (project / "-p" / "broken.jsonl").rmdir()
    (home / ".claude-profiles" / "p2").mkdir()
    (home / ".claude-profiles" / "p2" / "projects").write_text("")
    _refused(main, home, repo, ledger, failures, "a projects/ that cannot be listed", "p2/projects: cannot be listed")
    (home / ".claude-profiles" / "p2" / "projects").unlink()
    (project / "-gone").symlink_to(home / "unmounted")
    _refused(main, home, repo, ledger, failures, "a project dir linked to nothing", "-gone: a link to nothing")
    (project / "-gone").unlink()
    (home / ".claude-profiles" / "p3").symlink_to(home / "unmounted")
    _refused(main, home, repo, ledger, failures, "a profile linked to nothing", "p3: a link to nothing")
    (home / ".claude-profiles" / "p3").unlink()

    first = _json(_run(main, home, repo, ["--ledger", "--ledger-path", str(ledger), "--json"], failures),
                  failures, "ledger")
    _expect(failures, "--ledger appends one row per whole day and scope (29 days x 2)",
            (first.get("appended"), first.get("already_present")), (58, 0))
    rows = [json.loads(line) for line in ledger.read_text().splitlines()] if ledger.exists() else []
    days = {r["day"] for r in rows}
    _expect(failures, "today is not a whole day, so it is not recorded", _day(0) in days, False)
    _expect(failures, "the oldest whole day inside the retention is recorded", _day(29) in days, True)
    keyed = {(r["day"], r["scope"]): r for r in rows}
    _expect(failures, "a day row holds that day's counts",
            keyed.get((_day(D1), "main"), {}).get("counts", {}).get("skill:alpha", {}).get("fires"), 2)
    _expect(failures, "the subagents scope is its own row",
            keyed.get((_day(D1), "subagents"), {}).get("counts", {}).get("skill:subby", {}).get("fires"), 1)
    again = _json(_run(main, home, repo, ["--ledger", "--ledger-path", str(ledger), "--json"], failures),
                  failures, "ledger again")
    _expect(failures, "a second pass appends nothing: the file is append-only and keyed by day and scope",
            (again.get("appended"), again.get("already_present")), (0, 58))
    _expect(failures, "a second pass leaves the bytes alone", len(ledger.read_text().splitlines()), 58)

    with ledger.open("a") as handle:  # a second row for a recorded key: the first one recorded wins
        handle.write(json.dumps({"ledger": 1, "day": _day(D1), "scope": "main",
                                 "counts": {"skill:alpha": {"fires": 99, "last": _ts(D1)}}}) + "\n")
    both = _json(_run(main, home, repo, ["--json", "--ledger-path", str(ledger)], failures), failures, "ledger+live")
    _expect(failures, "a day in the ledger is not counted twice, and its first row wins",
            _by_name(both, "skills").get("alpha", {}).get("fires"), 2)
    _expect(failures, "the window says which days came from the ledger", both.get("window", {}).get("sources"),
            {"live": 1, "ledger": 29, "partial": 0})

    with ledger.open("a") as handle:  # a day the transcripts lost long ago
        handle.write(json.dumps({"ledger": 1, "day": _day(45), "scope": "main",
                                 "counts": {"skill:alpha": {"fires": 5, "tool": 5, "last": _ts(45)}}}) + "\n")
    old = _json(_run(main, home, repo, ["--json", "--since", "50", "--ledger-path", str(ledger)], failures),
                failures, "ledger since 50")
    _expect(failures, "a ledger day past the retention is read back (2 + 1 live old + 5)",
            _by_name(old, "skills").get("alpha", {}).get("fires"), 8)
    _expect(failures, "--since 50 sources with one old ledger day", old.get("window", {}).get("sources"),
            {"live": 1, "ledger": 30, "partial": 19})

    for name in ("s1.jsonl", "s2.jsonl"):  # Claude Code's cleanup deletes the transcripts
        (home / ".claude" / "projects" / "-p" / name).unlink()
    gone = _json(_run(main, home, repo, ["--json", "--ledger-path", str(ledger)], failures), failures, "ledger only")
    _expect(failures, "after the transcripts are deleted, the ledger still answers",
            _by_name(gone, "skills").get("alpha", {}).get("fires"), 2)


def _settings(home: Path, value: object) -> None:
    (home / ".claude" / "settings.json").write_text(json.dumps({"cleanupPeriodDays": value}))


def _pass(main: Callable[[list[str]], int], home: Path, repo: Path, failures: list[str], name: str) -> dict[str, Any]:
    """One --ledger --json pass into a fresh ledger file."""

    ledger = home / f"ledger-{name}.jsonl"
    return _json(_run(main, home, repo, ["--ledger", "--ledger-path", str(ledger), "--json"], failures),
                 failures, f"ledger {name}")


def _retention_checks(main: Callable[[list[str]], int], home: Path, repo: Path, failures: list[str]) -> None:
    _settings(home, 5)
    ledger = home / "ledger.jsonl"
    ledger.write_text('{"day": "torn')  # a write cut off mid-line: the next row must start on a fresh line
    result = _json(_run(main, home, repo, ["--ledger", "--ledger-path", str(ledger), "--json"], failures),
                   failures, "retention ledger")
    parsed = [line for line in ledger.read_text().splitlines()[1:] if line.startswith("{") and line.endswith("}")]
    _expect(failures, "every appended row after a torn line is whole", len(parsed), 8)
    _expect(failures, "cleanupPeriodDays 5 keeps only 4 whole days (x 2 scopes)", result.get("appended"), 8)
    days = {json.loads(line)["day"] for line in parsed}
    _expect(failures, "no day older than the retention is recorded", min(days) if days else None, _day(4))
    report = _json(_run(main, home, repo, ["--json", "--ledger-path", str(home / "none.jsonl")], failures),
                   failures, "retention report")
    _expect(failures, "a shorter retention makes the older days PARTIAL", report.get("window", {}).get("sources"),
            {"live": 5, "ledger": 0, "partial": 25})

    _settings(home, 1)
    one = _pass(main, home, repo, failures, "one")
    _expect(failures, "cleanupPeriodDays 1 leaves no whole day: nothing scanned, no ledger file",
            (one.get("days"), one.get("appended"), (home / "ledger-one.jsonl").exists()), ([], 0, False))
    _settings(home, True)
    _expect(failures, "cleanupPeriodDays true is not 1: Claude Code stays on its default 30",
            _pass(main, home, repo, failures, "bool").get("appended"), 58)

    # Past the default 30 days, a day needs a transcript older than it: none here is.
    _settings(home, 90)
    _expect(failures, "a raised cleanupPeriodDays with no older transcript still records the default 29 days",
            (lambda r: (r.get("appended"), r.get("first_whole")))(_pass(main, home, repo, failures, "raised")),
            (58, _day(29)))
    _old_transcript(home / ".claude" / "projects" / "-p" / "s0.jsonl", 70)
    _expect(failures, "... and reaches back to the day after its oldest transcript (69 days x 2)",
            (lambda r: (r.get("appended"), r.get("first_whole")))(_pass(main, home, repo, failures, "older")),
            (138, _day(69)))

    # A second config dir on the default deletes at 30 days, whatever the first one keeps.
    other = home / ".claude-profiles" / "p2"
    _old_transcript(other / "projects" / "-q" / "old.jsonl", 70)
    (other / "settings.json").write_text(json.dumps({"model": "any"}))
    _expect(failures, "a config dir that does not set cleanupPeriodDays holds the ledger to the default 30",
            (lambda r: (r.get("appended"), r.get("first_whole"), r.get("retention_days")))(
                _pass(main, home, repo, failures, "mixed")), (58, _day(29), 30))
    shutil.rmtree(other)

    # "Keep forever": no day older than every transcript is whole, and no date runs past year 1. The 99999 case
    # is read through the report: a ledger pass without the bound would write 199,996 rows.
    _settings(home, 99999)
    forever = _json(_run(main, home, repo, ["--json", "--ledger-path", str(home / "none.jsonl")], failures),
                    failures, "forever report")
    _expect(failures, "cleanupPeriodDays 99999 (clamped to ten years): whole back to the oldest transcript, not 1753",
            (forever.get("window", {}).get("retention_days"), forever.get("window", {}).get("first_whole")),
            (3650, _day(69)))
    _settings(home, 10**9)
    huge = _json(_run(main, home, repo, ["--json", "--ledger-path", str(home / "none.jsonl")], failures),
                 failures, "huge report")
    _expect(failures, "cleanupPeriodDays 10**9 is clamped in the report, not an OverflowError",
            (huge.get("window", {}).get("retention_days"), huge.get("window", {}).get("first_whole")),
            (3650, _day(69)))
    _expect(failures, "... and in the ledger, which records back to the oldest transcript (69 days x 2)",
            _pass(main, home, repo, failures, "huge").get("appended"), 138)


def run(main: Callable[[list[str]], int]) -> int:
    failures: list[str] = []
    root = Path(tempfile.mkdtemp(prefix="harness-usage-selftest-"))
    try:
        repo = root / "repo"
        _write_repo(repo)
        for name, checks, broken in (("report", _report_checks, True), ("usage", _usage_checks, True),
                                     ("ledger", _ledger_checks, True), ("retention", _retention_checks, False)):
            home = root / name
            home.mkdir()
            _write_home(home, broken)
            checks(main, home, repo, failures)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    if failures:
        print("harness-usage self-test: FAILED")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("harness-usage self-test: all controls passed (report, attribution, window, profiles, ledger, retention).")
    return 0
