"""MCP derived-package generation excludes interpreter-local bytecode."""

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
REGEN = REPO_ROOT / "configs" / "scripts" / "regen-mcp-package.sh"


def test_mcp_regenerator_excludes_python_bytecode(tmp_path):
    source_cache = (
        REPO_ROOT
        / "configs"
        / "skills"
        / "delivery"
        / "scripts"
        / "__pycache__"
    )
    source_cache.mkdir(exist_ok=True)
    sentinel = source_cache / "generator-sentinel.pyc"
    sentinel.write_bytes(b"machine-local bytecode")
    destination = tmp_path / "skills"
    try:
        subprocess.run(
            ["bash", str(REGEN), str(destination)],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
    finally:
        sentinel.unlink(missing_ok=True)

    assert not list(destination.rglob("__pycache__"))
    assert not list(destination.rglob("*.pyc"))
    assert not list(destination.rglob("*.pyo"))
