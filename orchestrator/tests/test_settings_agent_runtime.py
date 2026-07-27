"""Settings API guards the agent-runtime boundary before persistence."""

import pytest
from fastapi import HTTPException

import server
from routes.tasks import _validate_task


@pytest.mark.asyncio
async def test_settings_api_normalizes_known_agent_runtime(monkeypatch):
    saved = []
    monkeypatch.setattr(server, "_save_settings", lambda snapshot: saved.append(snapshot))
    monkeypatch.setitem(server.GLOBAL_SETTINGS, "worker_provider", "claude")

    result = await server.post_settings({"worker_provider": " CODEX "})

    assert result["worker_provider"] == "codex"
    assert saved[-1]["worker_provider"] == "codex"


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["", "bogus", None])
async def test_settings_api_rejects_invalid_runtime_without_mutation(
    monkeypatch, invalid
):
    saved = []
    monkeypatch.setattr(server, "_save_settings", lambda snapshot: saved.append(snapshot))
    monkeypatch.setitem(server.GLOBAL_SETTINGS, "worker_provider", "claude")

    with pytest.raises(HTTPException) as caught:
        await server.post_settings({"worker_provider": invalid})

    assert caught.value.status_code == 422
    assert "Unsupported agent runtime" in caught.value.detail
    assert server.GLOBAL_SETTINGS["worker_provider"] == "claude"
    assert saved == []


@pytest.mark.parametrize("invalid", ["", "bogus"])
def test_task_validation_rejects_explicit_invalid_runtime(invalid):
    errors = _validate_task(
        {
            "description": "Implement a bounded change",
            "provider": invalid,
        }
    )

    assert any("Unsupported agent runtime" in error for error in errors)


def test_task_validation_accepts_normalizable_runtime():
    errors = _validate_task(
        {
            "description": "Implement a bounded change",
            "provider": " CODEX ",
        }
    )

    assert errors == []
