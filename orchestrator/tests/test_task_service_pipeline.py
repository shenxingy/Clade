"""Integration checks for task-service maintenance health in pipeline-check."""

import json
import os
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "configs" / "scripts" / "pipeline-check.sh"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _run(tmp_path: Path, *, project_filter: str = "") -> list[str]:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    result = subprocess.run(
        ["bash", str(SCRIPT), project_filter],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _register(tmp_path: Path, *, project_id: str = "Project-Alpha", name: str = "alpha") -> Path:
    instance = tmp_path / "private-instance"
    _write_json(
        tmp_path / ".clade" / "task-services" / "alpha.json",
        {
            "schema_version": "clade.task-service-registration/v1",
            "directory": str(instance),
            "project_id": project_id,
            "name": name,
        },
    )
    return instance


def _health(instance: Path, *, project_id: str = "Project-Alpha", **overrides: object) -> None:
    payload = {
        "schema_version": "clade.task-service-health/v1",
        "project_id": project_id,
        "observed_at": time.time(),
        "status": "HEALTHY",
        "concerns": [],
        "backup": {"verified_at": time.time()},
    }
    payload.update(overrides)
    _write_json(instance / "maintenance" / "status.json", payload)


def test_valid_health_is_reported_without_legacy_registry(tmp_path: Path) -> None:
    instance = _register(tmp_path)
    _health(instance)

    assert _run(tmp_path) == ["HEALTHY|tasks-alpha|maintenance|status healthy"]


def test_degraded_health_includes_sanitized_concerns(tmp_path: Path) -> None:
    instance = _register(tmp_path)
    _health(instance, status="DEGRADED", concerns=["queue\nblocked", "worker|late"])

    assert _run(tmp_path) == [
        "DEGRADED|tasks-alpha|maintenance|status degraded; concerns: queue blocked, worker late"
    ]


def test_healthy_health_with_concerns_is_degraded(tmp_path: Path) -> None:
    instance = _register(tmp_path)
    _health(instance, concerns=["backup delayed"])

    assert _run(tmp_path) == [
        "DEGRADED|tasks-alpha|maintenance|status healthy; concerns: backup delayed"
    ]


def test_stale_health_is_degraded(tmp_path: Path) -> None:
    instance = _register(tmp_path)
    old = time.time() - 901
    _health(instance, observed_at=old, backup={"verified_at": time.time()})

    output = _run(tmp_path)
    assert output[0].startswith("DEGRADED|tasks-alpha|maintenance|stale health")


def test_future_backup_is_degraded(tmp_path: Path) -> None:
    instance = _register(tmp_path)
    _health(instance, backup={"verified_at": time.time() + 61})

    assert _run(tmp_path)[0].startswith(
        "DEGRADED|tasks-alpha|maintenance|backup not verified or stale"
    )


def test_bad_health_identity_is_unknown(tmp_path: Path) -> None:
    instance = _register(tmp_path)
    _health(instance, project_id="Project-Beta")

    assert _run(tmp_path) == [
        "UNKNOWN|tasks-alpha|maintenance|invalid health status (schema or project mismatch)"
    ]


def test_missing_health_is_unknown(tmp_path: Path) -> None:
    _register(tmp_path)

    assert _run(tmp_path) == [
        "UNKNOWN|tasks-alpha|maintenance|invalid health status (schema or project mismatch)"
    ]


def test_filter_matches_emitted_task_name_case_insensitively(tmp_path: Path) -> None:
    instance = _register(tmp_path, project_id="Project-Other")
    _health(instance, project_id="Project-Other")

    assert _run(tmp_path, project_filter="alpha") == [
        "HEALTHY|tasks-alpha|maintenance|status healthy"
    ]
    assert _run(tmp_path, project_filter="beta") == []


def test_registry_overflow_is_reported(tmp_path: Path) -> None:
    registry = tmp_path / ".clade" / "task-services"
    registry.mkdir(parents=True)
    for index in range(257):
        _write_json(registry / f"service-{index:03d}.json", {})

    assert _run(tmp_path)[0] == (
        "UNKNOWN|task-service-monitor|maintenance|registry has more than 256 entries"
    )


def test_filter_suppresses_malformed_registration_when_name_is_known(tmp_path: Path) -> None:
    _write_json(
        tmp_path / ".clade" / "task-services" / "alpha.json",
        {"name": "alpha", "project_id": "Project-Alpha"},
    )

    assert _run(tmp_path, project_filter="beta") == []
