"""Provider-neutral status snapshots never turn unknown data into fake zeroes."""

from types import SimpleNamespace

from status_snapshot import SCHEMA_VERSION, build_worker_status


def test_running_worker_keeps_progress_and_limits_unknown():
    snapshot = build_worker_status(
        SimpleNamespace(
            task_id="task-1",
            status="running",
            branch_name="worker/task-1",
            last_commit=None,
            execution_envelope=None,
        )
    ).to_dict()

    assert snapshot["schema_version"] == SCHEMA_VERSION
    assert snapshot["task"]["progress"] == {
        "completed": None,
        "total": None,
        "source": "unknown",
    }
    assert snapshot["limits"] == []
    assert snapshot["freshness"]["limits"] == "unknown"


def test_terminal_worker_reports_fact_not_estimate():
    snapshot = build_worker_status(
        SimpleNamespace(
            task_id="task-2",
            status="done",
            branch_name="worker/task-2",
            last_commit="abc123",
            execution_envelope=None,
        )
    ).to_dict()

    assert snapshot["task"]["progress"]["completed"] == 1
    assert snapshot["task"]["progress"]["total"] == 1
    assert snapshot["task"]["progress"]["source"] == "worker-terminal-state"
