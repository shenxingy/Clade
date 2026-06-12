"""Stale-process guard: /api/version exposes the commit the orchestrator is
actually running, so /status can diff it against repo HEAD. A long-lived
process once sat 9 days behind the repo with no warning — PM2 doesn't watch
files, and the kit's .kit-checksum drift guard only covers ~/.claude/ copies.
"""

from fastapi.testclient import TestClient


def test_version_endpoint_reports_commit_and_start_time():
    import server

    client = TestClient(server.app)
    r = client.get("/api/version")
    assert r.status_code == 200
    data = r.json()
    # Full 40-char SHA from git rev-parse, or the documented fallback.
    assert len(data["running_commit"]) == 40 or data["running_commit"] == "unknown"
    assert data["started_at"]


def test_capture_running_commit_matches_repo_head():
    import subprocess
    from pathlib import Path

    import server

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(server.__file__).parent, capture_output=True, text=True,
    ).stdout.strip()
    assert server.RUNNING_COMMIT == head
