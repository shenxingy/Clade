"""Declared Claude-to-Codex migration coverage and portable native assets."""

from __future__ import annotations

import fnmatch
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "configs" / "codex-migration.json"


def _manifest_names(path: Path) -> set[str]:
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def _migration() -> dict:
    return json.loads(MIGRATION.read_text(encoding="utf-8"))


def test_codex_migration_surfaces_and_policy_markers_are_real() -> None:
    migration = _migration()
    assert migration["schema_version"] == "clade.codex-migration/v1"

    for surface in migration["surfaces"]:
        assert surface["status"] in {
            "native",
            "native-subset",
            "semantic-adaptation",
            "intentional-exclusion",
        }
        for key in ("claude_source", "codex_target"):
            value = surface.get(key)
            if value is not None:
                assert (ROOT / value).exists(), (surface["id"], key, value)
        assert surface["reason"].strip()

    for policy in migration["policy_parity"]:
        source = (ROOT / policy["source"]).read_text(encoding="utf-8")
        target = (ROOT / policy["target"]).read_text(encoding="utf-8")
        assert policy["source_contains"] in source, policy["id"]
        assert policy["target_contains"] in target, policy["id"]


def test_every_canonical_skill_has_exactly_one_codex_disposition() -> None:
    migration = _migration()
    canonical = {
        path.name for path in (ROOT / "configs" / "skills").iterdir() if path.is_dir()
    }
    native = _manifest_names(ROOT / "plugins" / "clade" / "skills.list")

    matched: dict[str, list[str]] = {name: [] for name in canonical}
    for group in migration["skill_exclusions"]:
        assert group["reason"].strip()
        for pattern in group["patterns"]:
            hits = {name for name in canonical if fnmatch.fnmatchcase(name, pattern)}
            assert hits, (group["id"], pattern)
            for name in hits:
                matched[name].append(group["id"])

    assert native <= canonical
    assert not {name for name in native if matched[name]}, "native skills cannot be excluded"
    assert canonical == native | {name for name, groups in matched.items() if groups}
    assert not {
        name: groups for name, groups in matched.items() if len(groups) > 1
    }, "an excluded skill must have one unambiguous reason"


def test_green_is_native_and_bundles_the_exact_local_ci_runner() -> None:
    native = _manifest_names(ROOT / "plugins" / "clade" / "skills.list")
    assert "green" in native

    source = ROOT / "configs" / "scripts" / "ci-local.py"
    bundled = ROOT / "plugins" / "clade" / "skills" / "green" / "scripts" / "ci-local.py"
    assert bundled.read_bytes() == source.read_bytes()

    generated = (
        ROOT / "plugins" / "clade" / "skills" / "green" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "<plugin-root>/skills/green/scripts/ci-local.py" in generated
    assert "~/.claude/" not in generated
    assert '; echo "exit=$?"' not in generated

    result = subprocess.run(
        [sys.executable, str(bundled), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "--repo" in result.stdout
