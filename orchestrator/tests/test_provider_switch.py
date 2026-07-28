"""Claude compatibility connection adapter safety tests."""

import json
import os
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "configs" / "scripts" / "provider-switch.sh"


def _run(registry: Path, env_file: Path, *args: str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "CLADE_CLAUDE_PROVIDERS_FILE": str(registry),
        "CLADE_CLAUDE_PROVIDER_ENV_FILE": str(env_file),
        "TEST_GATEWAY_KEY": "never-print-this-secret",
    }
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def _write_registry(path: Path, *, model: str = "vendor/model+2026.07") -> None:
    path.write_text(
        json.dumps(
            {
                "active": "native",
                "providers": {
                    "native": {
                        "runtime": "claude",
                        "name": "Native login",
                        "models": ["claude-default"],
                    },
                    "gateway": {
                        "runtime": "claude",
                        "name": "User gateway",
                        "base_url": "https://gateway.invalid/anthropic",
                        "api_key_env": "TEST_GATEWAY_KEY",
                        "models": [model],
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def test_missing_registry_fails_without_bootstrapping(tmp_path):
    registry = tmp_path / "providers.json"

    result = _run(registry, tmp_path / "provider-env.sh")

    assert result.returncode == 2
    assert "will not bootstrap stale endpoints" in result.stderr
    assert not registry.exists()


def test_select_uses_opaque_model_and_never_copies_secret(tmp_path):
    registry = tmp_path / "providers.json"
    env_file = tmp_path / "provider-env.sh"
    _write_registry(registry)

    result = _run(registry, env_file, "gateway")

    assert result.returncode == 0, result.stderr
    assert "vendor/model+2026.07" in result.stdout
    assert "never-print-this-secret" not in result.stdout + result.stderr
    env_text = env_file.read_text(encoding="utf-8")
    assert "TEST_GATEWAY_KEY" in env_text
    assert "never-print-this-secret" not in env_text
    assert json.loads(registry.read_text())["active"] == "gateway"


def test_model_shell_syntax_is_rejected_before_writing(tmp_path):
    registry = tmp_path / "providers.json"
    env_file = tmp_path / "provider-env.sh"
    _write_registry(registry, model="model; touch /tmp/injected")

    result = _run(registry, env_file, "gateway")

    assert result.returncode == 2
    assert "valid opaque identifier" in result.stderr
    assert not env_file.exists()
