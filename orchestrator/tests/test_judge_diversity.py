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
