"""Tests for the skill registry: configs/scripts/skill_frontmatter.py (the ONE
SKILL.md frontmatter parser) and configs/scripts/validate-skills.py (CI gate).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "configs" / "scripts"


def _load(module_path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, module_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sf = _load(SCRIPTS_DIR / "skill_frontmatter.py", "clade_sf")
vs = _load(SCRIPTS_DIR / "validate-skills.py", "clade_validate_skills")


def _write_skill(tmp_path: Path, name: str, content: str) -> Path:
    skill_dir = tmp_path / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(content)
    return skill_dir


# ─── split_frontmatter / parse_frontmatter ───────────────────────────────────

def test_split_frontmatter_basic() -> None:
    fm, body = sf.split_frontmatter("---\nname: x\n---\nbody here\n")
    assert fm == "name: x"
    assert body == "body here"


def test_split_frontmatter_missing() -> None:
    fm, body = sf.split_frontmatter("# Just markdown\n")
    assert fm is None
    assert body == "# Just markdown\n"


def test_split_frontmatter_unterminated() -> None:
    fm, _ = sf.split_frontmatter("---\nname: x\nno closing fence\n")
    assert fm is None


def test_parse_single_line_and_quoted() -> None:
    fields = sf.parse_frontmatter(
        'name: demo\ndescription: "A quoted, plain description."\n'
        "argument-hint: '[url]'\n"
    )
    assert fields["name"] == "demo"
    assert fields["description"] == "A quoted, plain description."
    assert fields["argument-hint"] == "[url]"


def test_parse_folded_block_scalar() -> None:
    fields = sf.parse_frontmatter(
        "name: demo\ndescription: >\n  first line\n  second line\nlicense: MIT\n"
    )
    assert fields["description"] == "first line second line"
    assert fields["license"] == "MIT"


def test_parse_literal_block_scalar() -> None:
    fields = sf.parse_frontmatter("description: |\n  one\n  two\n")
    assert fields["description"] == "one two"


def test_parse_multiline_plain_continuation() -> None:
    fields = sf.parse_frontmatter("description: starts here\n  and continues\n")
    assert fields["description"] == "starts here and continues"


def test_nested_mapping_keys_not_promoted_to_top_level() -> None:
    fields = sf.parse_frontmatter(
        "name: demo\nmetadata:\n  source: upstream\n  version: 2\n"
    )
    assert fields["name"] == "demo"
    assert "source" not in fields  # indented keys belong to metadata
    assert "version" not in fields


def test_unquote_only_strips_matching_pairs() -> None:
    assert sf._unquote('"quoted"') == "quoted"
    assert sf._unquote("'quoted'") == "quoted"
    # leading quote without a matching trailing quote is left alone
    assert sf._unquote('"half quoted — rest. more') == '"half quoted — rest. more'


# ─── load_skill / iter_skills / catalog ──────────────────────────────────────

def test_load_skill_defaults_and_invocable_spellings(tmp_path: Path) -> None:
    for spelling in ("user_invocable", "user-invokable", "user-invocable"):
        d = _write_skill(
            tmp_path, f"skill-{spelling}",
            f"---\nname: skill-{spelling}\ndescription: D.\n{spelling}: true\n---\n",
        )
        skill = sf.load_skill(d / "SKILL.md")
        assert skill["user_invocable"] is True, spelling

    d = _write_skill(tmp_path, "noname", "---\ndescription: D.\n---\n")
    skill = sf.load_skill(d / "SKILL.md")
    assert skill["name"] == "noname"  # falls back to directory name


def test_catalog_renders_skills(tmp_path: Path) -> None:
    _write_skill(
        tmp_path, "alpha",
        "---\nname: alpha\ndescription: Does alpha things.\nuser_invocable: true\n---\n",
    )
    _write_skill(
        tmp_path, "beta",
        "---\nname: beta\ndescription: >\n  Folded beta\n  description.\n---\n",
    )
    out = sf.catalog(tmp_path)
    assert "## alpha\nDoes alpha things.\n(can be invoked with /alpha)" in out
    assert "## beta\nFolded beta description.\n" in out
    assert "(can be invoked with /beta)" not in out
    # no mangled block-marker lines (the old awk parser emitted bare '>')
    assert "\n>\n" not in out


def test_iter_skills_empty_dir(tmp_path: Path) -> None:
    assert sf.iter_skills(tmp_path / "missing") == []


# ─── validate_skill_dir ──────────────────────────────────────────────────────

# ≥40 chars — validate-skills warns on suspiciously short descriptions (1a5d09d)
GOOD = "---\nname: {n}\ndescription: A fine single-line description for testing.\nuser_invocable: true\n---\nBody.\n"


def test_validator_accepts_good_skill(tmp_path: Path) -> None:
    d = _write_skill(tmp_path, "good", GOOD.format(n="good"))
    errors, warnings = vs.validate_skill_dir(d)
    assert errors == []
    assert warnings == []


def test_validator_missing_skill_md(tmp_path: Path) -> None:
    d = tmp_path / "empty-skill"
    d.mkdir()
    errors, _ = vs.validate_skill_dir(d)
    assert errors and "SKILL.md missing" in errors[0]


def test_validator_no_frontmatter(tmp_path: Path) -> None:
    d = _write_skill(tmp_path, "nofm", "# no frontmatter\n")
    errors, _ = vs.validate_skill_dir(d)
    assert errors and "frontmatter" in errors[0]


def test_validator_name_mismatch(tmp_path: Path) -> None:
    d = _write_skill(tmp_path, "dirname", GOOD.format(n="othername"))
    errors, _ = vs.validate_skill_dir(d)
    assert any("!= directory name" in e for e in errors)


def test_validator_unknown_key(tmp_path: Path) -> None:
    d = _write_skill(
        tmp_path, "typo",
        "---\nname: typo\ndescription: D.\ndescripton: oops\n---\n",
    )
    errors, _ = vs.validate_skill_dir(d)
    assert any("unknown frontmatter key 'descripton'" in e for e in errors)


def test_validator_noncanonical_spelling_is_warning(tmp_path: Path) -> None:
    d = _write_skill(
        tmp_path, "upstream",
        "---\nname: upstream\ndescription: D.\nuser-invokable: true\n---\n",
    )
    errors, warnings = vs.validate_skill_dir(d)
    assert errors == []
    assert any("user_invocable" in w for w in warnings)


def test_validator_too_long_description_not_fixable(tmp_path: Path) -> None:
    d = _write_skill(
        tmp_path, "long",
        f"---\nname: long\ndescription: {'x' * 1100}\n---\n",
    )
    errors, _ = vs.validate_skill_dir(d, fix=True)
    assert any("too long" in e for e in errors)


# ─── --fix behavior ──────────────────────────────────────────────────────────

def _strict_yaml_ok(skill_md: Path) -> None:
    yaml = pytest.importorskip("yaml")
    fm, _ = sf.split_frontmatter(skill_md.read_text())
    data = yaml.safe_load(fm)
    assert isinstance(data, dict)
    assert str(data.get("description", "")).strip()


def test_fix_folds_block_scalar_description(tmp_path: Path) -> None:
    d = _write_skill(
        tmp_path, "folded",
        "---\nname: folded\ndescription: >\n  Line one of folded text here.\n"
        "  Line two of folded text here.\nuser_invocable: true\n---\nBody stays.\n",
    )
    errors, _ = vs.validate_skill_dir(d)
    assert errors  # red before fix

    errors, warnings = vs.validate_skill_dir(d, fix=True)
    assert errors == []
    assert any("fixed" in w for w in warnings)

    text = (d / "SKILL.md").read_text()
    assert "description: Line one of folded text here. Line two of folded text here.\n" in text
    assert text.endswith("Body stays.\n")  # body + trailing newline preserved
    assert vs.validate_skill_dir(d) == ([], [])  # green after fix
    _strict_yaml_ok(d / "SKILL.md")


def test_fix_strips_inline_block_marker(tmp_path: Path) -> None:
    d = _write_skill(
        tmp_path, "inline",
        "---\nname: inline\ndescription: > Text after marker on same line\n---\n",
    )
    vs.validate_skill_dir(d, fix=True)
    text = (d / "SKILL.md").read_text()
    assert "description: Text after marker on same line\n" in text
    assert vs.validate_skill_dir(d)[0] == []
    _strict_yaml_ok(d / "SKILL.md")


def test_fix_quotes_description_with_colon(tmp_path: Path) -> None:
    d = _write_skill(
        tmp_path, "colon",
        "---\nname: colon\ndescription: Iron Law: no fix without hypothesis\n---\n",
    )
    errors, _ = vs.validate_skill_dir(d)
    assert any("needs quoting" in e for e in errors)
    vs.validate_skill_dir(d, fix=True)
    text = (d / "SKILL.md").read_text()
    assert 'description: "Iron Law: no fix without hypothesis"\n' in text
    assert vs.validate_skill_dir(d)[0] == []
    _strict_yaml_ok(d / "SKILL.md")


def test_needs_quoting_rules() -> None:
    assert vs.needs_quoting("contains: colon-space")
    assert vs.needs_quoting("> starts with indicator")
    assert vs.needs_quoting('"leading quote')
    assert vs.needs_quoting("trailing colon:")
    assert not vs.needs_quoting("Plain text, with commas. And periods...")


# ─── the real repo gates ─────────────────────────────────────────────────────

def test_repo_skills_validate_clean() -> None:
    """The actual configs/skills tree passes the validator (CI parity)."""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "validate-skills.py"),
         str(REPO_ROOT / "configs" / "skills"), "--quiet"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_repo_skills_are_strict_yaml() -> None:
    """Every SKILL.md frontmatter parses as strict YAML with a description
    (Claude Code's native loader is YAML-based — drift here silently breaks
    the skill catalog)."""
    yaml = pytest.importorskip("yaml")
    bad = []
    for skill_md in sorted((REPO_ROOT / "configs" / "skills").glob("*/SKILL.md")):
        fm, _ = sf.split_frontmatter(skill_md.read_text())
        if fm is None:
            bad.append(f"{skill_md.parent.name}: no frontmatter")
            continue
        try:
            data = yaml.safe_load(fm)
        except Exception as exc:  # noqa: BLE001 — collecting all parse failures
            bad.append(f"{skill_md.parent.name}: {type(exc).__name__}")
            continue
        if not isinstance(data, dict) or not str(data.get("description", "")).strip():
            bad.append(f"{skill_md.parent.name}: missing/empty description")
    assert not bad, "SKILL.md frontmatter drift:\n" + "\n".join(bad)


def test_mcp_server_uses_shared_parser(tmp_path: Path) -> None:
    """mcp_server.load_skills delegates to skill_frontmatter (one parser)."""
    pytest.importorskip("mcp")
    sys.path.insert(0, str(REPO_ROOT / "orchestrator"))
    try:
        import mcp_server
    finally:
        sys.path.pop(0)

    _write_skill(
        tmp_path, "shared",
        "---\nname: shared\ndescription: >\n  Folded text\n  here.\n"
        "user_invocable: true\nargument-hint: '[x]'\n---\n",
    )
    (tmp_path / "shared" / "prompt.md").write_text("Prompt body")

    old = mcp_server.SKILLS_DIR
    mcp_server.SKILLS_DIR = tmp_path
    try:
        skills = mcp_server.load_skills()
    finally:
        mcp_server.SKILLS_DIR = old

    assert len(skills) == 1
    assert skills[0]["name"] == "shared"
    assert skills[0]["description"] == "Folded text here."  # folded, not '>'
    assert skills[0]["argument_hint"] == "[x]"
    assert skills[0]["user_invocable"] is True
    assert skills[0]["prompt_content"] == "Prompt body"
