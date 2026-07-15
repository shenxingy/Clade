"""Offline contract tests for reset-with-structured-handoff context."""

import json
from unittest.mock import AsyncMock, MagicMock

from reset_handoff import LoopContextMode, build_handoff_seed, render_seed


def test_build_handoff_seed_distills_envelope_to_compact_fields():
    envelope = {
        "v": 1,
        "task_id": "task-7",
        "status": "blocked",
        "summary": "Implemented parsing and added regression coverage.",
        "artifacts": {
            "commit": "abc123",
            "changed_files": ["orchestrator/parser.py", "orchestrator/tests/test_parser.py"],
            "tests": "42 passed",
        },
        "next_handoff": {
            "type": "repair",
            "payload": {
                "next_steps": ["Fix the remaining Windows path case"],
                "invariants": ["Default behavior stays unchanged"],
            },
        },
        "blockers": ["Windows fixture is missing"],
        "ignored_transcript": "x" * 100_000,
    }

    seed = build_handoff_seed(envelope, "Last check stopped at parser.py:91")

    assert seed == {
        "goal_status": "blocked",
        "done": [
            "Implemented parsing and added regression coverage.",
            "Last check stopped at parser.py:91",
        ],
        "next": ["Fix the remaining Windows path case"],
        "key_files": ["orchestrator/parser.py", "orchestrator/tests/test_parser.py"],
        "blockers": ["Windows fixture is missing"],
        "invariants": ["Default behavior stays unchanged"],
    }
    assert len(json.dumps(seed).encode()) < 8192
    assert "ignored_transcript" not in json.dumps(seed)


def test_seed_is_bounded_for_adversarial_envelope():
    huge = "z" * 100_000
    envelope = {
        "status": huge,
        "summary": huge,
        "artifacts": {"changed_files": [huge] * 1000},
        "next_handoff": {
            "type": huge,
            "payload": {"next": [huge] * 1000, "invariants": [huge] * 1000},
        },
        "blockers": [huge] * 1000,
    }
    assert len(json.dumps(build_handoff_seed(envelope, huge)).encode()) <= 8192


def test_render_seed_is_stable_and_json_parseable():
    seed = build_handoff_seed({"status": "done", "summary": "Finished."})
    rendered = render_seed(seed)
    assert rendered == render_seed(seed)
    payload = rendered.split("```json\n", 1)[1].rsplit("\n```", 1)[0]
    assert json.loads(payload) == seed


def test_unknown_or_empty_envelope_is_safe_minimal_seed():
    expected = {
        "goal_status": "unknown",
        "done": [],
        "next": [],
        "key_files": [],
        "blockers": [],
        "invariants": [],
    }
    assert build_handoff_seed({}) == expected
    assert build_handoff_seed({"future_field": {"anything": True}}) == expected
    assert build_handoff_seed(None) == expected


def test_loop_context_modes_are_explicit():
    import config

    assert set(LoopContextMode) == {"carry", "reset"}
    assert config._SETTINGS_DEFAULTS["loop_context_mode"] == "carry"


async def test_reset_mode_replaces_accumulated_task_context(tmp_path, monkeypatch):
    import session
    import worker_taskfile

    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "CLAUDE.md").write_text("ACCUMULATED PROJECT CONTEXT")
    worker = MagicMock()
    worker._claude_dir = claude_dir
    worker._project_dir = tmp_path
    worker._original_project_dir = tmp_path
    prior_envelope = {
        "status": "done",
        "summary": "Prior iteration completed parser changes.",
        "artifacts": {"changed_files": ["parser.py"]},
        "next_handoff": None,
        "blockers": [],
    }
    monkeypatch.setitem(worker_taskfile.GLOBAL_SETTINGS, "loop_context_mode", "reset")
    worker.description = session._with_reset_seed(
        "[Loop-2] Continue the loop task", prior_envelope
    )
    worker.id = "w-reset"
    worker.task_id = "t-reset"
    worker.model = "sonnet"
    worker._event_stream = MagicMock()
    queue = MagicMock()
    queue.get_recent_completions = AsyncMock(return_value=[{
        "id": "old", "completion_summary": "must not leak",
    }])
    monkeypatch.setattr(worker_taskfile, "_generate_code_tldr", lambda _: "OLD TLDR")
    monkeypatch.setattr(worker_taskfile, "_pre_hydrate", AsyncMock(return_value="OLD HYDRATION"))

    text = (await worker_taskfile.build_task_file(worker, queue)).read_text()

    assert "# Clean Reset Handoff" in text
    assert worker.description.startswith("[Loop-2]")
    assert text.count("# Clean Reset Handoff") == 1
    assert "Prior iteration completed parser changes." in text
    assert '"key_files": [\n    "parser.py"' in text
    assert "ACCUMULATED PROJECT CONTEXT" not in text
    assert "OLD TLDR" not in text
    assert "OLD HYDRATION" not in text
    queue.get_recent_completions.assert_not_awaited()
