"""Cross-platform interface-pipeline distribution and detector tests."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL = REPO_ROOT / "configs" / "skills" / "frontend-design"
PLUGIN = REPO_ROOT / "plugins" / "clade" / "skills" / "frontend-design"
MCP = REPO_ROOT / "mcp-package" / "skills" / "frontend-design"


def _load_detector():
    path = CANONICAL / "scripts" / "detect_interface_platform.py"
    spec = importlib.util.spec_from_file_location("interface_platform_detector", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_detector_prefers_desktop_shell_over_shared_web_runtime(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"electron": "1", "react": "1"}}),
        encoding="utf-8",
    )
    (tmp_path / "index.html").write_text("<!doctype html>", encoding="utf-8")

    result = _load_detector().detect(tmp_path)

    assert result["schema"] == "clade.interface-platform/v1"
    assert result["primary"] == "electron"
    assert [item["platform"] for item in result["candidates"]][:2] == [
        "electron",
        "web",
    ]


def test_detector_finds_web_runtime_in_a_shallow_monorepo(tmp_path: Path) -> None:
    web = tmp_path / "apps" / "dashboard"
    web.mkdir(parents=True)
    (web / "package.json").write_text(
        json.dumps({"dependencies": {"react": "1"}}), encoding="utf-8"
    )
    (web / "vite.config.ts").write_text("export default {}", encoding="utf-8")

    result = _load_detector().detect(tmp_path)

    assert result["primary"] == "web"
    assert any(
        "apps/dashboard/package.json" in signal
        for signal in result["candidates"][0]["signals"]
    )


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ({"Product.xcodeproj/project.pbxproj": ""}, "apple-native"),
        ({"app/src/main/AndroidManifest.xml": "<manifest />"}, "android-native"),
        ({"Product/App.xaml": "<Application />"}, "windows-native"),
        ({"pubspec.yaml": "flutter:\n  uses-material-design: true\n"}, "flutter"),
        ({"src-tauri/tauri.conf.json": "{}"}, "tauri"),
    ],
)
def test_detector_recognizes_platform_markers(
    tmp_path: Path, files: dict[str, str], expected: str
) -> None:
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    assert _load_detector().detect(tmp_path)["primary"] == expected


def test_pipeline_contract_and_resources_ship_to_every_distribution() -> None:
    prompt = (CANONICAL / "prompt.md").read_text(encoding="utf-8")
    for required in (
        "## Seven-phase pipeline",
        "## Scope lane",
        "HTML is allowed as a clearly labelled **visual hypothesis only**",
        "platform skeleton",
        "product brain",
        "brand expression",
        "## Required handoff",
    ):
        assert required in prompt

    expected_references = {
        "platform-android.md",
        "platform-apple.md",
        "platform-cross-platform.md",
        "platform-presentation.md",
        "platform-web.md",
        "platform-windows.md",
        "ui-ux-benchmark.md",
    }
    expected_scripts = {"detect_interface_platform.py"}

    for distributed in (CANONICAL, PLUGIN, MCP):
        assert {
            path.name for path in (distributed / "references").glob("*.md")
        } == expected_references
        assert {
            path.name for path in (distributed / "scripts").glob("*.py")
        } == expected_scripts

    plugin_skill = (PLUGIN / "SKILL.md").read_text(encoding="utf-8")
    for trigger in (
        "responsive/mobile web",
        "iOS/iPadOS/macOS",
        "Android",
        "Windows",
        "Electron/Tauri",
        "优化网页/界面/UI",
    ):
        assert trigger in plugin_skill
