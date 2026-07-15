"""Offline contract tests for the declared worker lifecycle graph."""

from config import _SETTINGS_DEFAULTS
from worker_phase_graph import ALLOWED, PHASES, record_transition, validate_transition


def test_declared_edges_validate():
    for frm, destinations in ALLOWED.items():
        for to in destinations:
            assert validate_transition(frm, to) == (True, None)


def test_undeclared_edge_and_unknown_phase_are_rejected_with_reasons():
    ok, reason = validate_transition("done", "running")
    assert not ok
    assert reason and "undeclared" in reason

    ok, reason = validate_transition("not-a-real-phase", "running")
    assert not ok
    assert reason and "unknown" in reason


def test_terminal_states_have_no_outgoing_edges():
    for phase in ("done", "failed", "blocked", "interrupted", "cancelled",
                  "converged", "exhausted", "budget_exceeded"):
        assert ALLOWED[phase] == set()


def test_record_transition_builds_event_and_emits_once():
    emitted = []

    event = record_transition(
        emitted.append, "run-123", "oracle-review", "requeue",
        extra={"attempt": 2},
    )

    assert event == {
        "type": "phase_transition",
        "run_id": "run-123",
        "from": "oracle-review",
        "to": "requeue",
        "attempt": 2,
    }
    assert emitted == [event]


def test_phases_cover_source_states_listed_in_module_comment():
    source_states = {
        "pending", "starting", "running", "paused", "oracle-review", "requeue",
        "supervisor", "worker", "grouped", "idle", "blocked", "interrupted",
        "done", "failed", "cancelled", "converged", "exhausted",
        "budget_exceeded",
    }
    assert PHASES == source_states
    assert set(ALLOWED) == PHASES


def test_validation_is_opt_in_by_default():
    assert _SETTINGS_DEFAULTS["phase_graph_validate"] is False
