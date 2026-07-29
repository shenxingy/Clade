"""Regression checks for dependency compatibility boundaries."""

from pathlib import Path
import tomllib

from packaging.requirements import Requirement
from packaging.version import Version


REPO_ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = Path(__file__).resolve().parents[1] / "requirements.txt"
MCP_PACKAGE = REPO_ROOT / "mcp-package" / "pyproject.toml"


def _assert_mcp_v2_contract(raw_requirement: str) -> None:
    requirement = Requirement(raw_requirement)
    assert Version("1.28.1") not in requirement.specifier
    assert Version("2.0.0") in requirement.specifier
    assert Version("2.99.0") in requirement.specifier
    assert Version("3.0.0") not in requirement.specifier


def test_orchestrator_mcp_dependency_requires_v2_and_excludes_v3() -> None:
    raw_requirement = next(
        line
        for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.startswith("mcp")
    )
    _assert_mcp_v2_contract(raw_requirement)


def test_mcp_package_dependency_requires_v2_and_excludes_v3() -> None:
    project = tomllib.loads(MCP_PACKAGE.read_text(encoding="utf-8"))["project"]
    raw_requirement = next(
        requirement
        for requirement in project["dependencies"]
        if requirement.startswith("mcp")
    )
    _assert_mcp_v2_contract(raw_requirement)
