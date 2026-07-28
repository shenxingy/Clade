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
    assert result["agent_runtime"] == "codex"
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


def test_task_validation_rejects_runtime_connection_mismatch(monkeypatch):
    monkeypatch.setitem(
        server.GLOBAL_SETTINGS,
        "connections",
        {
            "codex-work": {
                "agent_runtime": "codex",
                "inference_provider": "openai",
                "wire_protocol": "responses",
                "endpoint_identity": "codex-user-config",
            }
        },
    )

    errors = _validate_task(
        {
            "description": "Implement a bounded change",
            "agent_runtime": "claude",
            "connection": "codex-work",
        }
    )

    assert any("belongs to runtime" in error for error in errors)


def test_task_validation_rejects_malformed_capability_requirements():
    errors = _validate_task(
        {
            "description": "Implement a bounded change",
            "execution_requirements": {"repository_write": "maybe"},
        }
    )

    assert any("invalid capability requirement" in error for error in errors)


@pytest.mark.asyncio
async def test_settings_api_rejects_secret_bearing_connection(monkeypatch):
    saved = []
    monkeypatch.setattr(server, "_save_settings", lambda snapshot: saved.append(snapshot))
    unsafe = {
        "unsafe": {
            "agent_runtime": "claude",
            "inference_provider": "private-gateway",
            "wire_protocol": "anthropic-compatible",
            "endpoint_identity": "user-config",
            "api_key": "must-not-persist",
        }
    }

    with pytest.raises(HTTPException) as caught:
        await server.post_settings(
            {
                "connections": unsafe,
                "runtime_connections": {
                    "claude": "unsafe",
                    "codex": "codex-default",
                },
            }
        )

    assert caught.value.status_code == 422
    assert "secret-bearing" in caught.value.detail
    assert saved == []


@pytest.mark.asyncio
async def test_settings_api_rejects_unknown_key(monkeypatch):
    monkeypatch.setattr(server, "_save_settings", lambda snapshot: None)

    with pytest.raises(HTTPException) as caught:
        await server.post_settings({"agent_runtim": "codex"})

    assert caught.value.status_code == 422
    assert "Unknown settings: agent_runtim" == caught.value.detail
