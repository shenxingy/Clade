"""Offline tests for the deterministic judge-diversity leaf."""

import sys
from pathlib import Path

_ORCH = Path(__file__).resolve().parents[1]
if str(_ORCH) not in sys.path:
    sys.path.insert(0, str(_ORCH))

import judge_diversity as jd  # noqa: E402


def test_python_compile_catches_changed_syntax_error(tmp_path):
    (tmp_path / "good.py").write_text("value = 1\n")
    (tmp_path / "broken.py").write_text("def nope(:\n    pass\n")

    result = jd.deterministic_checks(tmp_path, ["good.py", "broken.py"])

    assert result["passed"] is False
    compile_check = next(check for check in result["checks"] if check["name"] == "py_compile")
    assert compile_check["ok"] is False
    assert "broken.py" in compile_check["evidence"]


def test_shell_syntax_check_accepts_good_and_rejects_broken(tmp_path):
    (tmp_path / "good.sh").write_text("#!/usr/bin/env bash\necho ok\n")
    (tmp_path / "broken.sh").write_text("#!/usr/bin/env bash\nif true; then\n")

    result = jd.deterministic_checks(tmp_path, ["good.sh", "broken.sh"])

    assert result["passed"] is False
    shell_check = next(check for check in result["checks"] if check["name"] == "bash_n")
    assert shell_check["ok"] is False
    assert "broken.sh" in shell_check["evidence"]


def test_detected_test_command_is_recorded(tmp_path):
    config_dir = tmp_path / ".claude"
    config_dir.mkdir()
    config_dir.joinpath("orchestrator.json").write_text(
        '{"test_cmd": "python3 -c \\\"print(123)\\\""}'
    )

    result = jd.deterministic_checks(tmp_path, [])

    assert result["passed"] is True
    test_check = next(check for check in result["checks"] if check["name"] == "test_suite")
    assert test_check == {"name": "test_suite", "ok": True, "evidence": "123"}


def test_oracle_agreement_labels_all_outcomes():
    passed = {"passed": True, "checks": []}
    failed = {"passed": False, "checks": []}

    assert jd.oracle_agreement(True, passed) == "agree"
    assert jd.oracle_agreement(False, failed) == "agree"
    assert jd.oracle_agreement(True, failed) == "oracle-lenient"
    assert jd.oracle_agreement(False, passed) == "oracle-strict"


# ─── Test-integrity signals ──────────────────────────────────────────────────
# The deterministic counterpart to worker_review's LLM integrity criterion. It
# must catch the documented reward hack (reach green by weakening the tests) and
# must NOT fire on honest test work, because a signal that cries wolf gets
# routed around and leaves the project worse off than no signal at all.


def _diff(path: str, body: str) -> str:
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1,4 +1,4 @@\n{body}"


def test_removed_assertion_is_counted():
    d = _diff("tests/test_calc.py", "-    assert add(1, 2) == 3\n     pass\n")
    s = jd.test_integrity(d)
    assert s["assertions_removed"] == 1
    assert s["eroded"] is True
    assert s["test_files"] == 1


def test_added_skip_marker_is_counted():
    d = _diff("tests/test_calc.py", "+@pytest.mark.skip(reason='flaky')\n def test_add():\n")
    assert jd.test_integrity(d)["skips_added"] == 1


def test_deleted_test_function_is_counted():
    d = _diff("tests/test_calc.py", "-def test_edge_case():\n-    assert f(0) == 0\n")
    s = jd.test_integrity(d)
    assert s["tests_deleted"] == 1 and s["assertions_removed"] == 1


def test_rewritten_assertion_nets_to_zero():
    # Same count out as in: a reworded assertion is not an erosion signal.
    d = _diff("tests/test_calc.py", "-    assert add(1, 2) == 3\n+    assert add(1, 2) == 3, 'sum'\n")
    s = jd.test_integrity(d)
    assert s["assertions_removed"] == 0 and s["eroded"] is False


def test_added_tests_do_not_report_negative_erosion():
    d = _diff("tests/test_calc.py", "+def test_new():\n+    assert g() == 1\n")
    s = jd.test_integrity(d)
    assert s["assertions_removed"] == 0 and s["tests_deleted"] == 0
    assert s["eroded"] is False


def test_non_test_files_are_ignored():
    d = _diff("src/calc.py", "-    assert isinstance(a, int)\n+    pass\n")
    s = jd.test_integrity(d)
    assert s["eroded"] is False and s["test_files"] == 0


def test_empty_diff_reports_nothing_examined():
    s = jd.test_integrity("")
    assert s["eroded"] is False and s["test_files"] == 0


def test_test_files_distinguishes_clean_from_unexamined():
    # The whole point of the field: an all-zero result means nothing without it.
    clean = jd.test_integrity(_diff("tests/test_a.py", "+    assert h() == 2\n"))
    unexamined = jd.test_integrity(_diff("README.md", "-old\n+new\n"))
    assert clean["test_files"] == 1 and unexamined["test_files"] == 0
    assert clean["eroded"] == unexamined["eroded"] is False


def test_recognizes_go_and_javascript_test_paths():
    go = jd.test_integrity(_diff("pkg/calc_test.go", "-\tt.Fatalf('bad')\n+\tt.Skip()\n"))
    assert go["assertions_removed"] == 1 and go["skips_added"] == 1
    js = jd.test_integrity(_diff("src/calc.test.ts", "-  expect(add(1,2)).toBe(3)\n"))
    assert js["assertions_removed"] == 1


def test_signals_are_excluded_from_the_pass_fail_aggregate(tmp_path):
    # Erosion is suspicion, not proof: deterministic_checks must not fail on it.
    (tmp_path / "ok.py").write_text("x = 1\n")
    result = jd.deterministic_checks(tmp_path, ["ok.py"])
    assert "test_integrity" not in [c["name"] for c in result["checks"]]


def test_evidence_line_is_empty_when_clean_and_actionable_when_not():
    assert jd.test_integrity_evidence(jd.test_integrity("")) == ""
    line = jd.test_integrity_evidence(
        jd.test_integrity(_diff("tests/test_a.py", "-    assert a == b\n"))
    )
    assert "1 assertion(s) removed" in line and "justified" in line
