"""Deterministic tests for the opt-in autonomous-run budget policy."""

from run_budget import RunBudget, attribution, budget_from_settings, check_budget


def test_unlimited_budget_never_exceeded():
    assert check_budget(999_999.0, 999_999_999, RunBudget()) == (False, None)


def test_usd_budget_exceeded_exactly_at_cap():
    budget = RunBudget(max_usd=1.25)
    assert check_budget(1.249, 0, budget) == (False, None)
    assert check_budget(1.25, 0, budget) == (True, "run_budget_usd_exceeded")
    assert check_budget(2.0, 0, budget) == (True, "run_budget_usd_exceeded")


def test_token_budget_exceeded_exactly_at_cap():
    budget = RunBudget(max_tokens=1000)
    assert check_budget(0.0, 999, budget) == (False, None)
    assert check_budget(0.0, 1000, budget) == (True, "run_budget_tokens_exceeded")
    assert check_budget(0.0, 1001, budget) == (True, "run_budget_tokens_exceeded")


def test_budget_from_settings_reads_caps_and_normalizes_unlimited():
    assert budget_from_settings({}) == RunBudget()
    assert budget_from_settings({"run_budget_usd": 0, "run_budget_tokens": None}) == RunBudget()
    assert budget_from_settings({"run_budget_usd": 2.5, "run_budget_tokens": 4000}) == RunBudget(
        max_usd=2.5, max_tokens=4000
    )


def test_attribution_returns_run_tags():
    assert attribution("org/repo", "clade", "sonnet") == {
        "repo": "org/repo",
        "harness": "clade",
        "model": "sonnet",
    }
