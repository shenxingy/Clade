"""configs/scripts/transcripts.py — the one Claude Code transcript reader.

Every fixture here is synthetic: record shapes copied from Claude Code 2.1.283
transcripts by keys and types only (the module docstring lists them), with
invented ids, commands and text. No real transcript content is committed.

configs/scripts/ is stdlib-only and imported the way workflow-scorecard.py
imports its siblings: by putting that directory on sys.path. With
CLADE_TRANSCRIPTS_DIR set, ``transcripts`` is imported from that directory
instead: test_transcripts_can_fire.py points it at a mutated copy.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO / "configs" / "scripts"
_UNDER_TEST = os.environ.get("CLADE_TRANSCRIPTS_DIR") or str(_SCRIPTS)
if _UNDER_TEST not in sys.path:
    sys.path.insert(0, _UNDER_TEST)

import transcripts as tr  # noqa: E402

# ─── Fixture builders ───────────────────────────────────────────────────────

SESSION = "11111111-2222-3333-4444-555555555555"


def _write(path: Path, records: list[object], tail: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [r if isinstance(r, str) else json.dumps(r, ensure_ascii=False) for r in records]
    path.write_text("".join(line + "\n" for line in lines) + tail, encoding="utf-8")
    return path


def _call(call_id: str, name: str, payload: dict, ts: str = "2026-11-05T10:00:00.000Z", **extra) -> dict:
    return {
        "type": "assistant", "timestamp": ts, "sessionId": SESSION, "isSidechain": False,
        "message": {"id": f"msg_{call_id}", "role": "assistant", "content": [
            {"type": "tool_use", "id": call_id, "name": name, "input": payload, "caller": {"type": "direct"}},
        ]},
        **extra,
    }


def _result(call_id: str, content: object, ts: str = "2026-11-05T10:00:01.000Z", is_error: object = None,
            **extra) -> dict:
    block: dict = {"type": "tool_result", "tool_use_id": call_id, "content": content}
    if is_error is not None:
        block["is_error"] = is_error
    return {"type": "user", "timestamp": ts, "sessionId": SESSION, "message": {"role": "user", "content": [block]},
            **extra}


def _hook(kind: str, ts: str = "2026-11-05T10:00:02.000Z", **body) -> dict:
    return {"type": "attachment", "timestamp": ts, "sessionId": SESSION, "attachment": {"type": kind, **body}}


def _tree(root: Path) -> dict[str, Path]:
    """One project with a main transcript, both subagent shapes, and the files beside them that are not transcripts."""

    slug = root / "-synthetic-project"
    paths = {
        "main": _write(slug / f"{SESSION}.jsonl", [{"type": "mode", "mode": "normal"}]),
        "agent": _write(slug / SESSION / "subagents" / "agent-a1.jsonl", [{"type": "user", "agentId": "a1"}]),
        "wf_agent": _write(slug / SESSION / "subagents" / "workflows" / "wf_x1" / "agent-b2.jsonl",
                           [{"type": "user", "agentId": "b2"}]),
        "journal": _write(slug / SESSION / "subagents" / "workflows" / "wf_x1" / "journal.jsonl",
                          [{"type": "started", "agentId": "b2"}]),
    }
    (slug / SESSION / "subagents" / "workflows" / "wf_x1" / "agent-b2.meta.json").write_text("{}", encoding="utf-8")
    (slug / "memory").mkdir()
    (slug / "memory" / "MEMORY.md").write_text("- note\n", encoding="utf-8")
    return paths


# ─── Discovery ──────────────────────────────────────────────────────────────


def test_main_thread_and_subagent_transcripts_are_told_apart(tmp_path):
    paths = _tree(tmp_path / "projects")
    roots = [tmp_path / "projects", tmp_path / "missing-root"]

    assert tr.find_transcripts(roots, None) == [paths["main"]]
    subagents = tr.find_subagent_transcripts(roots, None)
    assert sorted(subagents) == sorted([paths["agent"], paths["wf_agent"]])
    assert paths["journal"] not in subagents

    assert not tr.is_subagent_transcript(paths["main"])
    assert all(tr.is_subagent_transcript(p) for p in subagents)
    assert {tr.session_id(p) for p in [paths["main"], *subagents]} == {SESSION}


def test_a_root_reached_twice_through_a_symlink_is_read_once(tmp_path):
    paths = _tree(tmp_path / "projects")
    alias = tmp_path / "profile-projects"
    alias.symlink_to(tmp_path / "projects", target_is_directory=True)
    roots = [tmp_path / "projects", alias]

    assert tr.find_transcripts(roots, None) == [paths["main"]]
    assert len(tr.find_subagent_transcripts(roots, None)) == 2


def test_since_days_keeps_only_recent_files_and_sorts_oldest_first(tmp_path):
    paths = _tree(tmp_path / "projects")
    older = _write(tmp_path / "projects" / "-synthetic-project" / "older.jsonl", [{"type": "mode"}])
    stale = _write(tmp_path / "projects" / "-synthetic-project" / "stale.jsonl", [{"type": "mode"}])
    now = time.time()
    os.utime(older, (now - 2 * 86400, now - 2 * 86400))
    os.utime(stale, (now - 40 * 86400, now - 40 * 86400))
    os.utime(paths["agent"], (now - 40 * 86400, now - 40 * 86400))
    roots = [tmp_path / "projects"]

    assert tr.find_transcripts(roots, 30) == [older, paths["main"]]
    assert tr.find_transcripts(roots, None) == [stale, older, paths["main"]]
    assert tr.find_subagent_transcripts(roots, 30) == [paths["wf_agent"]]


def test_a_file_that_vanishes_mid_scan_is_skipped_not_fatal(tmp_path):
    """A dangling symlink is listed by the glob and cannot be stat'ed: the state
    of a transcript Claude Code's 30-day cleanup deletes between the glob and
    the stat. It used to abort the whole scan with FileNotFoundError."""

    paths = _tree(tmp_path / "projects")
    slug = tmp_path / "projects" / "-synthetic-project"
    (slug / "deleted-mid-scan.jsonl").symlink_to(tmp_path / "nowhere.jsonl")
    (slug / SESSION / "subagents" / "agent-gone.jsonl").symlink_to(tmp_path / "nowhere.jsonl")
    (slug / SESSION / "subagents" / "a-directory.jsonl").mkdir()  # matched by the glob, not a transcript
    roots = [tmp_path / "projects"]

    for window in (None, 30):
        assert tr.find_transcripts(roots, window) == [paths["main"]]
        assert sorted(tr.find_subagent_transcripts(roots, window)) == sorted([paths["agent"], paths["wf_agent"]])


def test_default_roots_covers_profiles_and_the_config_dir(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude-profiles" / "b").mkdir(parents=True)
    (home / ".claude-profiles" / "a").mkdir(parents=True)
    (home / ".claude-profiles" / "stray-file").write_text("", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))

    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    expected = [home / ".claude" / "projects",
                home / ".claude-profiles" / "a" / "projects",
                home / ".claude-profiles" / "b" / "projects"]
    assert tr.config_dir() == home / ".claude"
    assert tr.default_roots() == expected

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "")  # empty means unset, not the working directory
    assert tr.config_dir() == home / ".claude"
    assert tr.default_roots() == expected

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude-profiles" / "a"))
    assert tr.default_roots() == expected  # already a root: not listed twice

    elsewhere = tmp_path / "elsewhere"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(elsewhere))
    assert tr.default_roots() == [*expected, elsewhere / "projects"]


# ─── Records ────────────────────────────────────────────────────────────────


def test_iter_records_skips_bad_lines_and_says_how_many(tmp_path):
    # U+2028 and U+0085 are legal raw inside a JSON string; str.splitlines()
    # splits on both and would turn this one record into two broken halves.
    tricky = {"type": "user", "message": {"content": "before middle\u0085after"}}
    path = _write(tmp_path / "t.jsonl", [
        {"type": "mode", "mode": "normal"},
        "",
        "not json at all",
        "[1, 2, 3]",
        tricky,
        {"type": "ai-title", "aiTitle": "x"},
    ], tail='{"type": "assistant", "message": {"content": [{"type": "te')
    tally: dict[str, int] = {}

    records = list(tr.iter_records(path, tally))

    assert [r["type"] for r in records] == ["mode", "user", "ai-title"]
    assert records[1] == tricky
    assert tally == {"records": 3, "malformed": 2, "truncated": 1}


def test_iter_records_replaces_bytes_that_are_not_utf8(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_bytes(b'{"type": "user", "message": {"content": "caf\xe9"}}\n')
    assert [r["message"]["content"] for r in tr.iter_records(path)] == ["caf�"]


def test_an_unreadable_transcript_raises_rather_than_reading_as_empty(tmp_path):
    with pytest.raises(OSError):
        list(tr.iter_records(tmp_path / "gone.jsonl"))


# ─── Tool events ────────────────────────────────────────────────────────────

LONG_OUTPUT = "line of output\n" * 2000  # 30,000 characters: radar's tally clipped at 90


def _session_records() -> list[dict]:
    return [
        {"type": "permission-mode", "permissionMode": "default"},
        _call("toolu_deny", "Bash", {"command": "rm -rf build"}),
        _result("toolu_deny", "PreToolUse:Bash hook error: Refused: synthetic reason.\nUse the supported path.",
                is_error=True, toolDenialKind="permission-rule", toolUseResult="Error: PreToolUse:Bash hook error"),
        _call("toolu_long", "Bash", {"command": "make test"}, ts="2026-11-05T10:01:00.000Z"),
        _result("toolu_long", LONG_OUTPUT, ts="2026-11-05T10:01:30.000Z", is_error=False,
                toolUseResult={"stdout": "x", "stderr": "", "interrupted": False, "isImage": False,
                               "noOutputExpected": False}),
        _call("toolu_slow", "Bash", {"command": "sleep 900"}),
        _result("toolu_slow", "Command did not complete within its 120s timeout and was moved to the background.",
                is_error=False, toolUseResult={"stdout": "", "stderr": "", "interrupted": False,
                                               "backgroundTaskId": "bg1", "timedOutAfterMs": 120000}),
        _call("toolu_img", "Read", {"file_path": "/synthetic/shot.png"}),
        _result("toolu_img", [{"type": "text", "text": "a caption"},
                              {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AA"}},
                              {"type": "tool_reference", "tool_name": "Monitor"}]),
        _call("toolu_big", "Bash", {"command": "cat huge.log"}),
        _result("toolu_big", "<persisted-output>\nOutput too large (35KB). Full output saved to: /synthetic/out.txt",
                is_error=False, toolUseResult={"stdout": "", "stderr": "", "interrupted": False,
                                               "persistedOutputPath": "/synthetic/out.txt",
                                               "persistedOutputSize": 35827}),
        _call("toolu_inflight", "Monitor", {"command": "tail -f log"}),
    ]


def test_tool_events_pair_each_call_with_its_full_result():
    events = tr.tool_events(iter(_session_records()))  # a generator is read in one pass

    by_id = {e.id: e for e in events}
    assert [e.id for e in events] == ["toolu_deny", "toolu_long", "toolu_slow", "toolu_img", "toolu_big",
                                      "toolu_inflight"]

    deny = by_id["toolu_deny"]
    assert (deny.name, deny.input, deny.index, deny.result_index) == ("Bash", {"command": "rm -rf build"}, 1, 2)
    assert deny.is_error is True and deny.denial_kind == "permission-rule"
    assert deny.result.endswith("Use the supported path.")
    assert deny.timed_out_ms is None  # toolUseResult was a string, not an object

    long = by_id["toolu_long"]
    assert long.result == LONG_OUTPUT  # never clipped
    assert (long.timestamp, long.result_timestamp) == ("2026-11-05T10:01:00.000Z", "2026-11-05T10:01:30.000Z")
    assert long.is_error is False and long.denial_kind is None and long.interrupted is False

    slow = by_id["toolu_slow"]
    assert slow.timed_out_ms == 120000 and slow.is_error is False

    img = by_id["toolu_img"]
    assert img.result == "a caption\n[image]\n[tool_reference: Monitor]"
    assert img.is_error is False  # the flag is absent on this result: absent is not an error

    assert by_id["toolu_big"].persisted_output == "/synthetic/out.txt"

    inflight = by_id["toolu_inflight"]
    assert inflight.result is None and inflight.is_error is None and inflight.result_index is None


def test_tool_events_pair_by_id_when_parallel_results_arrive_out_of_order():
    """Several calls open at once, their results back in neither call order nor
    reverse call order: one API response with several tool_use blocks does
    this. Pairing by position (the latest call, the oldest open call or the
    newest open call) gets it wrong; only the id gets it right."""

    records = [
        _call("toolu_a", "Read", {"file_path": "/synthetic/a"}),
        _call("toolu_b", "Read", {"file_path": "/synthetic/b"}),
        _call("toolu_c", "Read", {"file_path": "/synthetic/c"}),
        _result("toolu_b", "text of b"),
        _result("toolu_a", "text of a", is_error=True),
        _result("toolu_c", "text of c"),
    ]
    tally: dict[str, int] = {}

    events = tr.tool_events(records, tally)

    assert [(e.id, e.input["file_path"], e.result, e.result_index, e.is_error) for e in events] == [
        ("toolu_a", "/synthetic/a", "text of a", 4, True),
        ("toolu_b", "/synthetic/b", "text of b", 3, False),
        ("toolu_c", "/synthetic/c", "text of c", 5, False),
    ]
    assert tally == {}


def test_tool_events_count_orphans_and_duplicates_instead_of_guessing():
    records = [
        _result("toolu_before_the_file_began", "ok"),
        _call("toolu_a", "Bash", {"command": "first"}),
        _call("toolu_a", "Bash", {"command": "second"}),
        _result("toolu_a", "first result"),
        _result("toolu_a", "second result"),
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {}}]}},
        {"type": "assistant", "message": {"content": "plain text, not a block list"}},
        "not even a dict",
        _call("toolu_null_input", "Bash", None),  # type: ignore[arg-type]
        _call("toolu_text_input", "mcp__synthetic__tool", "a bare string"),  # type: ignore[arg-type]
    ]
    tally: dict[str, int] = {}

    events = tr.tool_events(records, tally)  # type: ignore[arg-type]

    # An input that is not an object reads as {}, so a consumer can .get() on it.
    assert [(e.id, e.input, e.result) for e in events] == [
        ("toolu_a", {"command": "first"}, "first result"),
        ("toolu_null_input", {}, None),
        ("toolu_text_input", {}, None),
    ]
    assert tally == {"orphan_results": 1, "duplicate_calls": 1, "duplicate_results": 1}


def test_tool_events_carry_the_subagent_id_and_ignore_nested_progress_messages():
    nested = {"type": "progress", "data": {"message": {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "toolu_nested", "name": "Bash", "input": {"command": "x"}}]}}}}
    records = [_call("toolu_sub", "Grep", {"pattern": "x"}, agentId="a1", isSidechain=True), nested]

    events = tr.tool_events(records)

    assert [(e.id, e.agent_id) for e in events] == [("toolu_sub", "a1")]


def test_tool_events_read_a_transcript_end_to_end(tmp_path):
    path = _write(tmp_path / "t.jsonl", _session_records(), tail='{"type": "assistant", "mess')
    tally: dict[str, int] = {}
    events = tr.tool_events(tr.iter_records(path, tally), tally)
    assert len(events) == 6 and sum(e.is_error is True for e in events) == 1
    assert tally == {"records": 12, "truncated": 1}


# ─── Hook attachments ───────────────────────────────────────────────────────


def test_attachments_yield_hook_kinds_only_with_their_fields():
    records = [
        _hook("total_tokens_reminder", total=1),
        _hook("hook_success", hookName="PostToolUse:Bash", hookEvent="PostToolUse", toolUseID="toolu_1",
              content="", stdout="ok", stderr="", exitCode=0, command="synthetic-hook.sh", durationMs=12),
        _hook("hook_additional_context", hookName="PostToolUse:Bash", hookEvent="PostToolUse",
              toolUseID="toolu_1", content="[path-scoped rule: synthetic]"),
        _hook("hook_non_blocking_error", hookName="PreToolUse:Bash", hookEvent="PreToolUse", toolUseID="toolu_2",
              stdout="", stderr="boom", exitCode=1, command="synthetic-guard.sh", durationMs=5),
        _hook("hook_blocking_error", hookName="PostToolUse:Edit", hookEvent="PostToolUse", toolUseID="toolu_3",
              blockingError={"blockingError": "lint failed", "command": "synthetic-lint.sh"}),
        _hook("hook_cancelled", hookName="SessionStart:startup", hookEvent="SessionStart", toolUseID="opaque",
              command="slow.sh", durationMs=60000, timedOut=True, timeoutMs=60000),
        _hook("hook_permission_decision", hookEvent="PermissionRequest", toolUseID="toolu_4", decision="allow"),
        _hook("async_hook_response", hookName="PostToolUse:Write", hookEvent="PostToolUse", processId="p1",
              response={}, stdout="", stderr="", exitCode=0),
        _hook("hook_some_future_kind", hookEvent="Stop"),
        {"type": "system", "subtype": "stop_hook_summary", "hookInfos": [], "hookErrors": []},
        {"type": "attachment", "attachment": "not an object"},
        # A record of another type is not an attachment, whatever it carries.
        {"type": "user", "attachment": {"type": "hook_success", "hookEvent": "Stop"}},
        _hook("queued_command", prompt="typed while busy"),
    ]
    found = list(tr.attachments(records))
    kinds = [a.kind for a in found]
    assert kinds == ["hook_success", "hook_additional_context", "hook_non_blocking_error", "hook_blocking_error",
                     "hook_cancelled", "hook_permission_decision", "async_hook_response", "hook_some_future_kind"]
    by_kind = {a.kind: a for a in found}

    ok = by_kind["hook_success"]
    assert (ok.hook_event, ok.hook_name, ok.tool_use_id, ok.exit_code, ok.duration_ms, ok.stdout, ok.index) == \
        ("PostToolUse", "PostToolUse:Bash", "toolu_1", 0, 12, "ok", 1)
    assert ok.timestamp == "2026-11-05T10:00:02.000Z" and ok.raw["command"] == "synthetic-hook.sh"
    assert by_kind["hook_additional_context"].content == "[path-scoped rule: synthetic]"
    assert (by_kind["hook_non_blocking_error"].stderr, by_kind["hook_non_blocking_error"].exit_code) == ("boom", 1)
    assert by_kind["hook_blocking_error"].blocking_error == "lint failed"
    assert by_kind["hook_cancelled"].timed_out is True
    assert by_kind["hook_permission_decision"].decision == "allow"
    assert by_kind["async_hook_response"].tool_use_id is None
    assert tr.HOOK_ATTACHMENT_KINDS >= set(kinds) - {"hook_some_future_kind"}


def test_attachments_carry_the_subagent_id():
    record = _hook("hook_success", hookEvent="SubagentStop", exitCode=0)
    record["agentId"] = "b2"
    assert [a.agent_id for a in tr.attachments([record])] == ["b2"]


# ─── Heredocs ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("command,expected", [
    ("git status", "git status"),
    ("python3 - <<'EOF'\nimport os\nos.system('git reset --hard')\nEOF\necho done",
     "python3 - <<'EOF'\necho done"),
    ('cat > f.md <<"DOC" && git add f.md\ngit checkout -- a\nDOC\nls', 'cat > f.md <<"DOC" && git add f.md\nls'),
    ("cat <<EOF\nrm -rf /\nEOF", "cat <<EOF"),
    ("cat << EOF\nbody\nEOF\nnext", "cat << EOF\nnext"),
    ("cat <<\\EOF\nbody\nEOF\nnext", "cat <<\\EOF\nnext"),
    ("cat <<-EOF\n\tbody\n\t\tEOF\nnext", "cat <<-EOF\nnext"),
    ("cat <<EOF\nbody\n\tEOF\nstill body\nEOF\nnext", "cat <<EOF\nnext"),  # only <<- forgives tabs
    ("grep x <<< \"$s\"\ngit status", "grep x <<< \"$s\"\ngit status"),  # a here-string has no body
    ("tr a b <<<abc\ngit status", "tr a b <<<abc\ngit status"),  # not even a bare-word one
    ("paste <<A <<B\na1\nA\nb1\nB\nwc", "paste <<A <<B\nwc"),  # two on one line: both bodies go
    ("cat <<EOF\nbody <<NOT\nEOF\nnext", "cat <<EOF\nnext"),  # a << inside a body opens nothing
    ('git commit -m "$(cat <<\'EOF\'\nfix: x\n\nrm -rf\nEOF\n)"', "git commit -m \"$(cat <<'EOF'\n)\""),
    ("cat <<EOF\nnever closed\nrm -rf x", "cat <<EOF"),  # unterminated: the rest is body
    ("echo $((1<<2))", "echo $((1<<2))"),
    # A documented limit, failing toward stripping too much: only the leading
    # identifier of a non-identifier delimiter is captured, so it never closes.
    ("cat <<END-OF-FILE\nbody\nEND-OF-FILE\nnext", "cat <<END-OF-FILE"),
])
def test_strip_heredocs(command, expected):
    assert tr.strip_heredocs(command) == expected


# ─── The consumer ───────────────────────────────────────────────────────────


def test_workflow_scorecard_polls_scans_main_thread_transcripts_from_every_root(tmp_path):
    """What workflow-scorecard.py --polls hands out, read through its own main().

    The transcripts sit under ~/.claude/projects and are reached a second time
    through a profile symlink; a subagent transcript full of polls sits beside
    them, and so does a transcript deleted mid-scan (a dangling symlink). One
    session must come back, counted once, without the subagent's, and the
    deleted file must not abort the report.
    """

    home = tmp_path / "home"
    projects = home / ".claude" / "projects"
    polls = [_call(f"toolu_{n}", "Bash", {"command": "gh pr checks 7"}) for n in range(4)]
    _write(projects / "-synthetic-project" / f"{SESSION}.jsonl", polls)
    _write(projects / "-synthetic-project" / SESSION / "subagents" / "agent-a1.jsonl",
           [_call(f"toolu_s{n}", "Bash", {"command": "git status"}, agentId="a1") for n in range(5)])
    (projects / "-synthetic-project" / "deleted-mid-scan.jsonl").symlink_to(home / "nowhere.jsonl")
    (home / ".claude-profiles" / "p1").mkdir(parents=True)
    (home / ".claude-profiles" / "p1" / "projects").symlink_to(projects, target_is_directory=True)
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
    env["HOME"] = str(home)

    out = subprocess.run(
        [sys.executable, str(_SCRIPTS / "workflow-scorecard.py"), "--polls", "--json", "--since", "0"],
        capture_output=True, text=True, env=env, timeout=60, check=False,
    )

    assert out.returncode == 0, out.stderr
    rows = json.loads(out.stdout)
    assert [(r["session"], r["bash_calls"], r["polls"]) for r in rows] == [(SESSION, 4, 3)]
