"""transcripts.py's guards must be able to go red in test_transcripts.py.

The same question test_hook_guards_can_fire.py asks of a shell hook, asked of
the transcript reader: remove one guard, and the suite that claims it must
fail. transcripts.py is mutated in a COPY, and test_transcripts.py imports that
copy through CLADE_TRANSCRIPTS_DIR, so the tree is never written. The suite's
consumer test runs the real workflow-scorecard.py and is deselected here: it
cannot see the copy.

Not mutated, on purpose: ``newline="\\n"`` on open() (text mode never splits on
U+2028 either way; splitlines() is what did, and that mutation is listed), the
profile sort in default_roots() (iterdir order often IS sorted, so a mutation
could pass by luck), the ``at > 0`` guard in session_id() (only a relative path
that starts at ``subagents/`` reaches it), and the code under ``__main__``
(test_self_tests_can_fire.py runs it).

A mutation that would pass by luck is written so it cannot: "oldest first" is
mutated to newest first, not to unsorted, because an unsorted glob of three
files can come back already in mtime order: about one chance in six wherever
directory order is arbitrary.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "configs" / "scripts" / "transcripts.py"
SUITE = "tests/test_transcripts.py"

# (what the mutation removes, exact source before, exact source after)
MUTATIONS: list[tuple[str, str, str]] = [
    # ─── Records ───
    ("no splitlines(): U+2028 inside a string stays one record",
     "        for line in handle:\n            if not line.strip():",
     "        for line in handle.read().splitlines(keepends=True):\n            if not line.strip():"),
    ("blank lines are ignored, not counted malformed",
     "            if not line.strip():\n                continue\n", ""),
    ("a cut-off last line is truncated, not malformed",
     '_bump(tally, "malformed" if line.endswith("\\n") else "truncated")', '_bump(tally, "malformed")'),
    ("a JSON value that is not an object is skipped",
     '            if not isinstance(record, dict):\n                _bump(tally, "malformed")\n                continue\n', ""),
    ("bytes that are not UTF-8 are replaced",
     'encoding="utf-8", errors="replace", newline="\\n"', 'encoding="utf-8", newline="\\n"'),
    # ─── Discovery ───
    ("the journal is not a transcript",
     "if in_subagents_dir and (path.name in _NOT_TRANSCRIPTS or not path.is_file()):",
     "if in_subagents_dir and not path.is_file():"),
    ("only regular files under subagents/",
     "if in_subagents_dir and (path.name in _NOT_TRANSCRIPTS or not path.is_file()):",
     "if in_subagents_dir and path.name in _NOT_TRANSCRIPTS:"),
    ("transcripts deduplicate on the resolved path",
     "found.setdefault(path.resolve(), (mtime, path))", "found.setdefault(path, (mtime, path))"),
    ("the since-days cutoff",
     "            if cutoff is not None and mtime < cutoff:", "            if False:"),
    ("oldest first",
     "sorted(found.values(), key=lambda item: item[0])]",
     "sorted(found.values(), key=lambda item: item[0], reverse=True)]"),
    ("a file that vanished mid-scan is skipped, not fatal",
     "            try:\n                mtime = path.stat().st_mtime\n            except OSError:\n                continue\n",
     "            mtime = path.stat().st_mtime\n"),
    ("a file under subagents/ is a subagent transcript",
     '    return "subagents" in path.parts[:-1]', "    return False"),
    ("a subagent's session is the directory above subagents/",
     "            return parts[at - 1]", "            return path.stem"),
    # ─── Tool events ───
    # Three ways to pair by position instead of by id: the latest call, the
    # oldest open call, the newest open call.
    ("a result is paired by id, not with the latest call",
     'event = events.get(str(block.get("tool_use_id")))',
     "event = list(events.values())[-1] if events else None"),
    ("a result is paired by id, not with the oldest open call",
     'event = events.get(str(block.get("tool_use_id")))',
     "event = next((e for e in events.values() if e.result_index is None), None)"),
    ("a result is paired by id, not with the newest open call",
     'event = events.get(str(block.get("tool_use_id")))',
     "event = next((e for e in reversed(list(events.values())) if e.result_index is None), None)"),
    ("an input that is not an object reads as {}",
     "input=payload if isinstance(payload, dict) else {},", "input=payload,"),
    ("a repeated call id keeps the first call",
     '                if call_id in events:\n                    _bump(tally, "duplicate_calls")\n                    continue\n', ""),
    ("a repeated result keeps the first result",
     '                elif event.result_index is not None:\n                    _bump(tally, "duplicate_results")\n', ""),
    ("an orphan result is counted",
     '                    _bump(tally, "orphan_results")', "                    pass"),
    ("an absent is_error is False, not None",
     'event.is_error = bool(block.get("is_error"))', 'event.is_error = block.get("is_error")'),
    ("the denial kind is carried",
     "event.denial_kind = denial if isinstance(denial, str) else None", "event.denial_kind = None"),
    ("a timeout is carried",
     "event.timed_out_ms = timed_out if isinstance(timed_out, int) else None", "event.timed_out_ms = None"),
    ("a persisted output path is carried",
     "event.persisted_output = persisted if isinstance(persisted, str) else None", "event.persisted_output = None"),
    ("the interrupted flag is carried",
     "event.interrupted = interrupted if isinstance(interrupted, bool) else None", "event.interrupted = None"),
    ("a result with no object leaves interrupted None (not recorded), not False",
     "    interrupted: bool | None = None\n", "    interrupted: bool | None = False\n"),
    ("a call carries its subagent id",
     "agent_id=agent if isinstance(agent, str) else None,", "agent_id=None,"),
    ("a result item that is not text leaves a marker",
     "            parts.append(f\"[{kind or 'unknown'}]\")", "            pass"),
    ("the tool_reference marker names the tool",
     "parts.append(f\"[tool_reference: {item.get('tool_name') or '?'}]\")", "pass"),
    # ─── Hook attachments ───
    ("an unknown hook_* kind is reported, not dropped",
     'kind.startswith("hook_") or kind == "async_hook_response"', "kind in HOOK_ATTACHMENT_KINDS"),
    ("async_hook_response is a hook kind",
     'kind.startswith("hook_") or kind == "async_hook_response"', 'kind.startswith("hook_")'),
    ("only attachment records are attachments",
     'if not isinstance(record, dict) or record.get("type") != "attachment":', "if not isinstance(record, dict):"),
    ("a blocking error's text is unwrapped",
     '        if isinstance(blocking, dict):\n            blocking = blocking.get("blockingError")\n', ""),
    ("a hook's exit code is read",
     'exit_code=_int(body.get("exitCode")),', "exit_code=None,"),
    ("a hook attachment carries its subagent id",
     'agent_id=_text(record.get("agentId")),\n            command=', "agent_id=None,\n            command="),
    # ─── Heredocs ───
    ("a here-string opens no heredoc",
     '_HEREDOC = re.compile(r"""(?<!<)<<', '_HEREDOC = re.compile(r"""<<'),
    ("only <<- forgives a tab-indented terminator",
     'if (line.lstrip("\\t") if tabs else line) == delimiter:', 'if line.lstrip("\\t") == delimiter:'),
    ("every heredoc opened on a line is tracked",
     "pending = [(m.group(2), bool(m.group(1))) for m in _HEREDOC.finditer(line)]",
     "pending = [(m.group(2), bool(m.group(1))) for m in list(_HEREDOC.finditer(line))[:1]]"),
    ("heredocs close in the order they opened",
     "                pending.pop(0)", "                pending.pop()"),
    ("a body line opens nothing",
     "                pending.pop(0)\n            continue\n", "                pending.pop(0)\n"),
    ("the line that opens a heredoc is kept",
     "        kept.append(line)\n        pending =", "        pending ="),
]


def _run(directory: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "CLADE_TRANSCRIPTS_DIR": str(directory), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        [sys.executable, "-m", "pytest", SUITE, "-x", "-q", "-p", "no:cacheprovider", "-k", "not workflow_scorecard"],
        cwd=REPO / "orchestrator", env=env, capture_output=True, text=True, timeout=240,
    )


def _copy(tmp: Path, name: str, text: str) -> Path:
    directory = tmp / name
    directory.mkdir()
    (directory / "transcripts.py").write_text(text, encoding="utf-8")
    return directory


def test_an_unmutated_copy_passes_through_the_override(tmp_path):
    """The control. If the copy could not be imported, every mutation below
    would turn the suite red and prove nothing."""

    result = _run(_copy(tmp_path, "control", SOURCE.read_text(encoding="utf-8")))
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-1000:]


def test_removing_a_transcripts_guard_turns_its_suite_red():
    """One test, the mutations run concurrently: the suite takes about a second
    and there are dozens of them."""

    source = SOURCE.read_text(encoding="utf-8")
    unanchored = [name for name, old, _ in MUTATIONS if source.count(old) != 1]
    assert not unanchored, (
        f"these mutation anchors do not occur exactly once in transcripts.py: {unanchored}. The code moved; "
        f"update the anchor, do not delete the case — an unanchored mutation silently stops testing.")

    with tempfile.TemporaryDirectory() as tmp:
        def one(item: tuple[int, tuple[str, str, str]]) -> tuple[str, subprocess.CompletedProcess]:
            i, (name, old, new) = item
            return name, _run(_copy(Path(tmp), f"m{i}", source.replace(old, new, 1)))

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(one, enumerate(MUTATIONS)))

    stayed_green = [name for name, result in results if result.returncode == 0]
    assert not stayed_green, (
        f"{SUITE} still PASSES with these removed from transcripts.py: {stayed_green}.\n"
        f"Those properties are claimed and not checked.")
