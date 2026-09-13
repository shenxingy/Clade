"""Provider runtime tests for the distributable clade-mcp package."""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_SRC = REPO_ROOT / "mcp-package" / "src"
sys.path.insert(0, str(MCP_SRC))

from clade_mcp import __version__, runtime  # noqa: E402
from clade_mcp import server  # noqa: E402
from clade_mcp.server import SERVER_VERSION  # noqa: E402


def _declared_release_version() -> str:
    """The one version every other surface must agree with."""
    with (REPO_ROOT / "mcp-package" / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def test_release_version_surfaces_are_aligned() -> None:
    """Cutting a release must not require editing this test.

    The expected version used to be a literal here, so bumping the package meant
    hand-editing the gate that exists to catch a missed hand-edit — the failure
    it was written to prevent, one level up. It is derived now.

    It also covered four surfaces and there are six: the Claude Code plugin
    manifest and the generated Codex plugin manifest both carry a version and
    neither was checked, so either could have shipped stale with the suite green.
    """
    expected = _declared_release_version()
    server_manifest = json.loads(
        (REPO_ROOT / "mcp-package" / "server.json").read_text(encoding="utf-8")
    )
    cc_plugin = json.loads(
        (REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    codex_plugin = json.loads(
        (REPO_ROOT / "plugins" / "clade" / ".codex-plugin" / "plugin.json").read_text(
            encoding="utf-8"
        )
    )

    assert __version__ == expected
    assert SERVER_VERSION == expected
    assert server_manifest["version"] == expected
    assert server_manifest["packages"][0]["version"] == expected
    assert cc_plugin["version"] == expected

    # The Codex manifest is regenerated with semver build metadata appended
    # (0.3.1+codex.<stamp>). Everything before the plus sign is the release.
    assert codex_plugin["version"].split("+", 1)[0] == expected


def test_mcp_dependency_requires_v2_without_a_v1_fallback() -> None:
    orchestrator_requirements = (
        REPO_ROOT / "orchestrator" / "requirements.txt"
    ).read_text(encoding="utf-8")
    package_manifest = (
        REPO_ROOT / "mcp-package" / "pyproject.toml"
    ).read_text(encoding="utf-8")

    assert "mcp>=2.0.0,<3" in orchestrator_requirements
    assert '"mcp>=2.0.0,<3"' in package_manifest
    assert "mcp>=1" not in orchestrator_requirements + package_manifest


def test_packaged_server_registers_v2_low_level_handlers() -> None:
    assert server.app.get_request_handler("tools/list") is not None
    assert server.app.get_request_handler("tools/call") is not None


def test_editable_install_resolves_curated_bundled_skills() -> None:
    expected = REPO_ROOT / "mcp-package" / "skills"
    assert server.BUNDLED_SKILLS_DIR == expected
    assert len(list(server.BUNDLED_SKILLS_DIR.glob("*/SKILL.md"))) == 34
    for name in ("delivery", "provider", "status"):
        assert (server.BUNDLED_SKILLS_DIR / name / "SKILL.md").is_file()


def test_bundled_skill_resolution_prefers_wheel_then_editable(tmp_path) -> None:
    module_file = tmp_path / "src" / "clade_mcp" / "server.py"
    module_file.parent.mkdir(parents=True)
    module_file.touch()

    editable_skill = tmp_path / "skills" / "delivery"
    editable_skill.mkdir(parents=True)
    (editable_skill / "SKILL.md").write_text("---\nname: delivery\n---\n")
    assert server.resolve_bundled_skills_dir(module_file) == tmp_path / "skills"

    wheel_skill = module_file.parent / "skills" / "status"
    wheel_skill.mkdir(parents=True)
    (wheel_skill / "SKILL.md").write_text("---\nname: status\n---\n")
    assert server.resolve_bundled_skills_dir(module_file) == module_file.parent / "skills"


def test_runtime_selection_is_backwards_compatible() -> None:
    assert runtime.get_runtime({}).name == "claude"
    assert runtime.get_runtime({"CLADE_RUNTIME": "codex"}).name == "codex"
    with pytest.raises(ValueError, match="Unsupported CLADE_RUNTIME"):
        runtime.get_runtime({"CLADE_RUNTIME": "unknown"})


def _async(fn):
    """Adapt a sync stub to the async seam `_run_bounded` now occupies."""
    async def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)
    return wrapper


def test_codex_runtime_uses_stdin_jsonl_and_safe_sandbox(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return (
            0,
            '{"type":"thread.started","thread_id":"abc"}\n'
            '{"type":"item.completed","item":{"type":"agent_message",'
            '"text":"native result"}}\n',
            "",
        )

    monkeypatch.setattr(runtime, "_run_bounded", _async(fake_run))
    result = runtime.CodexRuntime().execute(
        "do the work", tmp_path, env={"CLADE_RUNTIME": "codex"}
    )
    assert result.ok and result.text == "native result"
    assert captured["stdin_text"] == "do the work"
    assert captured["command"][:4] == ["codex", "exec", "--json", "--ephemeral"]
    assert ["--sandbox", "workspace-write"] == captured["command"][6:8]
    assert captured["command"][-1] == "-"


def test_codex_runtime_requires_explicit_permission_bypass(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return (0, "", "")

    monkeypatch.setattr(runtime, "_run_bounded", _async(fake_run))
    runtime.CodexRuntime().execute(
        "work", tmp_path, env={"CLADE_CODEX_BYPASS_PERMISSIONS": "true"}
    )
    assert "--dangerously-bypass-approvals-and-sandbox" in captured["command"]
    assert "--sandbox" not in captured["command"]


def test_claude_runtime_preserves_existing_behavior(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return (0, '{"result":"legacy result"}', "")

    monkeypatch.setattr(runtime, "_run_bounded", _async(fake_run))
    result = runtime.ClaudeRuntime().execute("work", tmp_path, env={})
    assert result.text == "legacy result"
    assert captured["command"][0:2] == ["claude", "-p"]
    assert "--dangerously-skip-permissions" in captured["command"]


def test_invalid_codex_sandbox_fails_before_spawn(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        runtime,
        "_run_bounded",
        _async(lambda *args, **kwargs: pytest.fail("no process should be spawned")),
    )
    result = runtime.CodexRuntime().execute(
        "work", tmp_path, env={"CLADE_CODEX_SANDBOX": "invalid"}
    )
    assert not result.ok
    assert "CLADE_CODEX_SANDBOX" in result.error


# ─── README skill tables ──────────────────────────────────────────────────────
# Both package READMEs carry a hand-maintained table of the shipped skills, and
# nothing generated or checked it. It had drifted: the `commit` row promised
# "push" outright while the skill's own description says publication remains
# separately authorized — an outward-facing action advertised unconditionally by
# the document a reader installs from.
#
# The wording is a human call, but the COVERAGE is mechanical: a row for a skill
# that is not shipped, or a shipped skill with no row, is a defect either way.

def _shipped_skills() -> set[str]:
    import pathlib
    manifest = pathlib.Path(__file__).resolve().parents[2] / "mcp-package" / "skills.list"
    return {line.strip() for line in manifest.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")}


def _readme_rows(name: str) -> set[str]:
    import pathlib
    import re as _re
    path = pathlib.Path(__file__).resolve().parents[2] / "mcp-package" / name
    return set(_re.findall(r"^\| \*\*([a-z0-9-]+)\*\*", path.read_text(encoding="utf-8"), _re.M))


def test_both_readme_tables_cover_exactly_the_shipped_skills():
    shipped = _shipped_skills()
    assert shipped, "skills.list is empty"
    for name in ("README.md", "README.zh-CN.md"):
        rows = _readme_rows(name)
        assert not rows - shipped, f"{name} lists skills that are not shipped: {sorted(rows - shipped)}"
        assert not shipped - rows, f"{name} omits shipped skills: {sorted(shipped - rows)}"


def test_the_two_readmes_describe_the_same_skill_set():
    assert _readme_rows("README.md") == _readme_rows("README.zh-CN.md")


def test_the_commit_row_does_not_promise_an_unconditional_push():
    # /commit's own description: "publication remains separately authorized".
    # A README that says "push" flat is telling an installer the opposite.
    import pathlib
    import re as _re
    root = pathlib.Path(__file__).resolve().parents[2]
    for name, verb in (("README.md", "push"), ("README.zh-CN.md", "推送")):
        text = (root / "mcp-package" / name).read_text(encoding="utf-8")
        row = _re.search(r"^\| \*\*commit\*\* \| (.*?) \|$", text, _re.M)
        assert row, f"{name} has no commit row"
        cell = row.group(1)
        if verb in cell:
            assert any(word in cell.lower() for word in
                       ("authorized", "authorised", "授权", "另行")), \
                f"{name} promises {verb!r} with no mention that it is gated: {cell!r}"
