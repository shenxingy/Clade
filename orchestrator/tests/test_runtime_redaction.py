"""Runtime persistence redaction contract tests."""

from __future__ import annotations

import asyncio
import json

import aiosqlite

from event_stream import EventStream
from ideas import IdeasManager
from runtime_redaction import (
    RedactingStreamCapture,
    merge_metadata,
    redact_runtime,
    write_redaction_metadata,
)
from session_tree import SessionTree
from tracing import Tracer


GITHUB_TOKEN = "ghp_" + "A" * 40
OPENAI_TOKEN = "sk-proj-" + "B" * 32


def test_recursive_redaction_masks_sensitive_keys_tokens_and_machine_paths():
    result = redact_runtime(
        {
            "authorization": "Bearer never-store-this",
            "nested": {
                "output": f"token={GITHUB_TOKEN} at /home/alex/private/repo",
                "input_tokens": 123,
            },
        }
    )

    assert result.value["authorization"] == "<redacted:sensitive_key>"
    assert GITHUB_TOKEN not in result.value["nested"]["output"]
    assert "/home/alex" not in result.value["nested"]["output"]
    assert result.value["nested"]["input_tokens"] == 123
    metadata = result.metadata.to_dict()
    assert metadata["schema_version"] == "clade.redaction/v1"
    assert metadata["count"] == 3
    assert "sensitive_key" in metadata["kinds"]
    assert all(GITHUB_TOKEN not in field for field in metadata["fields"])


def test_redaction_is_idempotent_and_metadata_never_contains_original():
    first = redact_runtime(f"credential {OPENAI_TOKEN}")
    second = redact_runtime(first.value)
    assert OPENAI_TOKEN not in first.value
    assert second.value == first.value
    assert second.metadata.count == 0
    assert OPENAI_TOKEN not in json.dumps(first.metadata.to_dict())


def test_merge_metadata_accumulates_safe_counts():
    one = redact_runtime(GITHUB_TOKEN).metadata
    two = redact_runtime(f"/Users/alex/repo {OPENAI_TOKEN}").metadata
    merged = merge_metadata(one, two)
    assert merged.count == one.count + two.count
    assert merged.kinds["github_token"] == 1
    assert merged.kinds["openai_key"] == 1
    assert merged.kinds["home_path"] == 1


async def test_provider_stream_is_redacted_before_log_write(tmp_path):
    reader = asyncio.StreamReader()
    reader.feed_data(f"before {GITHUB_TOKEN}\n".encode())
    reader.feed_data(
        b"-----BEGIN PRIVATE KEY-----\nraw-private-material\n"
        b"-----END PRIVATE KEY-----\nafter\n"
    )
    reader.feed_eof()
    log_path = tmp_path / "worker.log"
    capture = RedactingStreamCapture()

    metadata = await capture.capture(reader, log_path)
    write_redaction_metadata(log_path, metadata)

    persisted = log_path.read_text()
    assert GITHUB_TOKEN not in persisted
    assert "raw-private-material" not in persisted
    assert "<redacted:github_token>" in persisted
    assert "<redacted:private_key>" in persisted
    sidecar = json.loads((tmp_path / "worker.log.redaction.json").read_text())
    assert sidecar["kinds"]["github_token"] == 1
    assert sidecar["kinds"]["private_key"] == 1
    assert GITHUB_TOKEN not in json.dumps(sidecar)


def test_event_stream_redacts_before_memory_and_jsonl(tmp_path):
    path = tmp_path / "events.jsonl"
    stream = EventStream("w1")
    stream.set_jsonl_path(path)
    event = stream.emit(
        "observation",
        "llm_call",
        content={"provider_output": GITHUB_TOKEN, "password": "super-secret-value"},
    )

    assert GITHUB_TOKEN not in event.content
    content = json.loads(event.content)
    assert content["password"] == "<redacted:sensitive_key>"
    assert content["_redaction"]["count"] == 2
    assert GITHUB_TOKEN not in path.read_text()


def test_session_tree_and_trace_redact_jsonl(tmp_path):
    tree_path = tmp_path / "session.jsonl"
    tree = SessionTree(tree_path)
    tree.tool_result("call-1", f"result {OPENAI_TOKEN}")

    trace_path = tmp_path / "trace.jsonl"
    tracer = Tracer("trace-1")
    tracer.start(
        "provider",
        attributes={"authorization": "Bearer raw", "result": GITHUB_TOKEN},
    )
    tracer.write(trace_path)

    tree_record = json.loads(tree_path.read_text())
    trace_record = json.loads(trace_path.read_text())
    assert OPENAI_TOKEN not in json.dumps(tree_record)
    assert GITHUB_TOKEN not in json.dumps(trace_record)
    assert tree_record["_redaction"]["count"] == 1
    assert trace_record["_redaction"]["count"] == 2


async def test_task_queue_redacts_sqlite_text_and_records_metadata(task_queue):
    task = await task_queue.add(f"Investigate {GITHUB_TOKEN}")
    assert GITHUB_TOKEN not in task["description"]
    assert task["redaction_metadata"]["kinds"]["github_token"] == 1

    updated = await task_queue.update(
        task["id"], failed_reason=f"provider failed with {OPENAI_TOKEN}"
    )
    assert OPENAI_TOKEN not in updated["failed_reason"]
    assert updated["redaction_metadata"]["count"] == 2

    message = await task_queue.send_message(task["id"], f"look at {GITHUB_TOKEN}")
    assert GITHUB_TOKEN not in message["content"]
    assert message["redaction_metadata"]["count"] == 1

    intervention_id = await task_queue.record_intervention(
        f"failure {GITHUB_TOKEN}",
        f"rotate {OPENAI_TOKEN}",
        source_task_id=task["id"],
    )
    async with aiosqlite.connect(str(task_queue._db_path)) as db:
        async with db.execute(
            "SELECT failure_pattern, correction, redaction_metadata "
            "FROM interventions WHERE id = ?",
            (intervention_id,),
        ) as cursor:
            row = await cursor.fetchone()
    assert GITHUB_TOKEN not in row[0]
    assert OPENAI_TOKEN not in row[1]
    assert json.loads(row[2])["count"] == 2


async def test_ideas_manager_redacts_provider_evaluation_and_messages(tmp_path):
    manager = IdeasManager(tmp_path / "ideas.db")
    try:
        idea = await manager.add_idea(f"Build around {GITHUB_TOKEN}")
        assert GITHUB_TOKEN not in idea["content"]
        assert idea["redaction_metadata"]["count"] == 1

        idea = await manager.update_idea(
            idea["id"], ai_evaluation=f'{{"summary": "{OPENAI_TOKEN}"}}'
        )
        assert OPENAI_TOKEN not in idea["ai_evaluation"]
        assert idea["redaction_metadata"]["count"] == 2

        message = await manager.add_message(
            idea["id"], "ai", f"provider replied {GITHUB_TOKEN}"
        )
        assert GITHUB_TOKEN not in message["content"]
        assert message["redaction_metadata"]["count"] == 1
    finally:
        await manager.close()
