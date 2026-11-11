"""mainline-ci.py tests each new main tree once and traces a red one to its merge.

The cases live in configs/scripts/merge_then_test_cases.py, so this suite and the
script's own --self-test (which test_self_tests_can_fire.py mutates) run one table.
Each case drives the script's CLI as a subprocess against a bare origin, a fake gh
and a fake gate, and asserts on what it returns and leaves behind.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "configs" / "scripts" / "mainline-ci.py"
_spec = importlib.util.spec_from_file_location("merge_then_test_cases", SCRIPT.with_name("merge_then_test_cases.py"))
assert _spec is not None and _spec.loader is not None
cases = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cases)


@pytest.mark.parametrize("name,case", cases.MAINLINE_CASES, ids=[name for name, _ in cases.MAINLINE_CASES])
def test_case(name, case, tmp_path):
    case(tmp_path, SCRIPT)


def test_the_table_is_not_empty():
    assert len(cases.MAINLINE_CASES) >= 8
