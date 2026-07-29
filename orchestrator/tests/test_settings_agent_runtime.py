"""Settings API guards the agent-runtime boundary before persistence."""

import pytest
from fastapi import HTTPException, Response

import compatibility_telemetry
import server
from routes.tasks import _validate_task


@pytest.fixture(autouse=True)
def _isolated_compatibility_telemetry(tmp_path, monkeypatch):
    monkeypatch.setattr(
        compatibility_telemetry,
        "_telemetry_file",
        tmp_path / "compatibility-telemetry.json",
    )


@pytest.mark.asyncio
async def test_settings_api_normalizes_known_agent_runtime(monkeypatch):
    saved = []
    monkeypatch.setattr(server, "_save_settings", lambda snapshot: saved.append(snapshot))
    monkeypatch.delitem(server.GLOBAL_SETTINGS, "worker_provider", raising=False)
    response = Response()

    result = await server.post_settings(
        {"worker_provider": " CODEX "}, response=response
    )

    assert "worker_provider" not in result
    assert result["agent_runtime"] == "codex"
    assert "worker_provider" not in saved[-1]
    assert response.headers["deprecation"] == "true"
    telemetry = compatibility_telemetry.read_compatibility_telemetry()
    assert telemetry["events"]["settings.worker_provider"]["count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["", "bogus", None])
async def test_settings_api_rejects_invalid_runtime_without_mutation(
    monkeypatch, invalid
):
    saved = []
    monkeypatch.setattr(server, "_save_settings", lambda snapshot: saved.append(snapshot))
    monkeypatch.setitem(server.GLOBAL_SETTINGS, "agent_runtime", "claude")

    with pytest.raises(HTTPException) as caught:
        await server.post_settings({"worker_provider": invalid})

    assert caught.value.status_code == 422
    assert "Unsupported agent runtime" in caught.value.detail
    assert server.GLOBAL_SETTINGS["agent_runtime"] == "claude"
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


@pytest.mark.asyncio
async def test_settings_api_rejects_native_store_runtime_mismatch(monkeypatch):
    monkeypatch.setattr(server, "_save_settings", lambda snapshot: None)
    connections = {
        "claude-work": {
            "agent_runtime": "claude",
            "inference_provider": "custom",
            "wire_protocol": "anthropic-compatible",
            "endpoint_identity": "trusted-profile",
            "models": {"strong": "gateway/model"},
            "capabilities": {},
            "discovery": {
                "adapter": "custom-openai",
                "store": "codex-config",
                "profile": "work",
            },
        },
        "codex-default": server.GLOBAL_SETTINGS["connections"]["codex-default"],
    }

    with pytest.raises(HTTPException) as caught:
        await server.post_settings(
            {
                "connections": connections,
                "runtime_connections": {
                    "claude": "claude-work",
                    "codex": "codex-default",
                },
            }
        )

    assert caught.value.status_code == 422
    assert "claude-providers" in caught.value.detail
