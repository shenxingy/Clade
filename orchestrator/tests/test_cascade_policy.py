"""Fail-closed contract tests for verifier-aware cheap-to-strong routing."""

from __future__ import annotations

import json
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import cascade_policy
from error_classifier import ClassifiedError, FailoverReason
from worker_routing import resolve_worker_route
from worker_utils import _maybe_enqueue_classify_retry, _run_project_tests

_WR_SPEC = importlib.util.spec_from_file_location(
    "_cascade_worker_review", Path(__file__).parent.parent / "worker_review.py"
)
_WR = importlib.util.module_from_spec(_WR_SPEC)
_WR_SPEC.loader.exec_module(_WR)


SETTINGS = {
    "agent_runtime": "codex",
    "default_model": "gpt-5.6-sol",
    "auto_model_routing": True,
    "verifier_cascade_enabled": True,
    "verifier_cascade_min_score": 80,
    "verifier_cascade_task_types": ["test", "tldr"],
    "codex_cheap_model": "gpt-5.6-terra",
    "codex_strong_model": "gpt-5.6-sol",
    "task_type_model_routing": {},
}


def _task(**overrides):
    return {
        "agent_runtime": "codex",
        "model": "gpt-5.6-sol",
        "score": 92,
        "task_type": "test",
        "is_critical_path": 0,
        "own_files": ["tests/**"],
        **overrides,
    }


def _verifier():
    return cascade_policy.VerifierContract(
        verifier_id="pytest-targeted",
        command_digest="sha256:" + ("a" * 64),
        deterministic=True,
    )


def test_default_off_and_missing_verifier_preserve_requested_route():
    baseline = resolve_worker_route(_task(), SETTINGS, None)
    disabled = resolve_worker_route(
        _task(), {**SETTINGS, "verifier_cascade_enabled": False}, _verifier()
    )
    missing = resolve_worker_route(_task(), SETTINGS, None)

    assert disabled == baseline
    assert missing == baseline
    assert cascade_policy.route_stage(disabled.reason) is None


def test_eligible_bounded_task_routes_cheap_once():
    route = resolve_worker_route(_task(), SETTINGS, _verifier())

    assert route.model == "gpt-5.6-terra"
    assert route.effort == "low"
    assert cascade_policy.route_stage(route.reason) == "cheap"
    assert "pytest-targeted@sha256:" in route.reason


def test_critical_unbounded_or_high_risk_tasks_fail_closed():
    cases = [
        _task(is_critical_path=1),
        _task(own_files=[]),
        _task(task_type="implement"),
        _task(score=79),
    ]

    assert all(
        cascade_policy.route_stage(
            resolve_worker_route(task, SETTINGS, _verifier()).reason
        )
        is None
        for task in cases
    )


def test_malformed_policy_settings_fail_closed_without_crashing():
    invalid = [
        {**SETTINGS, "verifier_cascade_min_score": "many"},
        {**SETTINGS, "verifier_cascade_max_files": 0},
        {**SETTINGS, "verifier_cascade_task_types": "test"},
    ]

    assert all(
        cascade_policy.route_stage(
            resolve_worker_route(_task(), settings, _verifier()).reason
        )
        is None
        for settings in invalid
    )
    assert cascade_policy.max_changed_files(
        {"verifier_cascade_max_files": "many"}
    ) == 8


def test_explicit_escalation_routes_strong_even_after_setting_disabled():
    task = _task(source_ref="cascade:strong:test_failure")
    route = resolve_worker_route(
        task,
        {**SETTINGS, "verifier_cascade_enabled": False},
        None,
    )

    assert route.model == "gpt-5.6-sol"
    assert route.effort == "high"
    assert cascade_policy.route_stage(route.reason) == "strong"
    assert "test_failure" in route.reason


def test_project_verifier_requires_explicit_determinism(tmp_path):
    config = tmp_path / ".claude" / "orchestrator.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"test_cmd": "pytest -q"}))
    assert cascade_policy.load_verifier_contract(tmp_path) is None

    config.write_text(
        json.dumps(
            {
                "test_cmd": "pytest -q",
                "test_cmd_deterministic": True,
                "test_cmd_id": "pytest-suite",
            }
        )
    )
    contract = cascade_policy.load_verifier_contract(tmp_path)

    assert contract.verifier_id == "pytest-suite"
    assert contract.command_digest.startswith("sha256:")
    assert "pytest -q" not in contract.command_digest


def test_scope_expansion_promotes_existing_ownership_gate():
    reason = cascade_policy.CHEAP_REASON

    assert cascade_policy.scope_result(
        (True, ""), route_reason=reason, changed_files=["a", "b"], max_files=2
    ) == (True, "")
    blocked = cascade_policy.scope_result(
        (True, ""), route_reason=reason, changed_files=["a", "b", "c"], max_files=2
    )
    assert blocked[0] is False
    assert "scope expansion" in blocked[1]


async def test_fail_closed_project_test_runner_rejects_missing_command(tmp_path):
    assert await _run_project_tests(tmp_path) == (True, "")
    passed, output = await _run_project_tests(tmp_path, fail_closed=True)
    assert passed is False
    assert "unavailable" in output


async def test_test_failure_requeue_preserves_contract_and_marks_strong(task_queue):
    original = await task_queue.add(
        "Write a bounded test",
        model="gpt-5.6-sol",
        own_files=["tests/**"],
        task_type="test",
        phase="verify",
        agent_runtime="codex",
        connection="codex-default",
        execution_profile="default",
        execution_requirements=[],
    )
    worker = SimpleNamespace(
        task_id=original["id"],
        description=original["description"],
        model="gpt-5.6-terra",
        own_files=["tests/**"],
        forbidden_files=[],
        agent_runtime="codex",
        effort="low",
        route_reason=cascade_policy.CHEAP_REASON,
        _test_requeue_reason="tests failed",
    )

    await _WR.handle_test_requeue(worker, task_queue, False)
    children = [
        task for task in await task_queue.list()
        if task["parent_task_id"] == original["id"]
    ]

    assert len(children) == 1
    child = children[0]
    assert child["source_ref"] == "cascade:strong:test_failure"
    assert child["task_type"] == "test"
    assert child["phase"] == "verify"
    assert child["connection"] == "codex-default"
    route = resolve_worker_route(child, SETTINGS, None)
    assert cascade_policy.route_stage(route.reason) == "strong"
    assert cascade_policy.escalation_source(
        SimpleNamespace(route_reason=route.reason), "test_failure"
    ) is None


async def test_no_diff_gets_truthful_signal_and_strong_fallback_is_terminal(task_queue):
    original = await task_queue.add(
        "Write a bounded test",
        own_files=["tests/**"],
        task_type="test",
        agent_runtime="codex",
    )
    cheap = SimpleNamespace(
        task_id=original["id"],
        description=original["description"],
        model="gpt-5.6-terra",
        own_files=["tests/**"],
        forbidden_files=[],
        agent_runtime="codex",
        effort="low",
        route_reason=cascade_policy.CHEAP_REASON,
        _test_requeue_reason="No diff produced by cheap attempt",
    )

    await _WR.handle_test_requeue(cheap, task_queue, False)
    children = [
        task for task in await task_queue.list()
        if task["parent_task_id"] == original["id"]
    ]
    assert len(children) == 1
    assert children[0]["source_ref"] == "cascade:strong:no_diff"
    assert "produced no diff" in children[0]["description"]

    strong_route = resolve_worker_route(children[0], SETTINGS, None)
    strong = SimpleNamespace(**{
        **cheap.__dict__,
        "task_id": children[0]["id"],
        "route_reason": strong_route.reason,
        "_test_requeue_reason": "tests failed",
        "_oracle_requeue_reason": "oracle rejected",
    })
    await _WR.handle_test_requeue(strong, task_queue, False)
    await _WR.handle_oracle_requeue(strong, task_queue, 5, "", 3)
    assert len(await task_queue.list()) == 2


async def test_repeated_error_is_idempotent_and_preserves_execution_contract(task_queue):
    original = await task_queue.add(
        "Write a bounded test",
        own_files=["tests/**"],
        forbidden_files=["secrets/**"],
        task_type="test",
        phase="verify",
        agent_runtime="codex",
        connection="codex-default",
        execution_profile="isolated",
        execution_requirements={"network": False},
    )
    worker = SimpleNamespace(
        task_id=original["id"],
        description=original["description"],
        model="gpt-5.6-terra",
        own_files=["tests/**"],
        forbidden_files=["secrets/**"],
        agent_runtime="codex",
        effort="low",
        route_reason=cascade_policy.CHEAP_REASON,
        _failure_classified=ClassifiedError(reason=FailoverReason.rate_limit),
    )

    assert await _maybe_enqueue_classify_retry(worker, task_queue) is True
    assert await _maybe_enqueue_classify_retry(worker, task_queue) is False
    children = [
        task for task in await task_queue.list()
        if task["parent_task_id"] == original["id"]
    ]
    assert len(children) == 1
    child = children[0]
    assert child["source_ref"] == "cascade:strong:repeated_error"
    assert child["task_type"] == "test"
    assert child["phase"] == "verify"
    assert child["connection"] == "codex-default"
    assert child["execution_profile"] == "isolated"
    assert child["execution_requirements"] == {"network": False}

    auth_worker = SimpleNamespace(**{
        **worker.__dict__,
        "_failure_classified": ClassifiedError(reason=FailoverReason.auth),
        "_classify_retry_enqueued": False,
    })
    assert await _maybe_enqueue_classify_retry(auth_worker, task_queue) is False
    assert len(await task_queue.list()) == 2
