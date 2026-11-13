"""Real-tree Kimi skill compatibility and hermetic installer-view tests."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCANNER = REPO_ROOT / "configs" / "scripts" / "kimi-skill-compat.py"
SKILLS = REPO_ROOT / "configs" / "skills"


def test_real_scan_classifies_every_skill_directory_without_dropping_one() -> None:
    expected = sorted(path.parent.name for path in SKILLS.glob("*/SKILL.md"))
    assert expected, "the completeness control needs a non-empty real skill tree"
    result = subprocess.run(
        [sys.executable, str(SCANNER), "--root", str(SKILLS), "--json"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    report = json.loads(result.stdout)
    rows = report["skills"]
    assert len(rows) == len(expected)
    assert sorted(row["name"] for row in rows) == expected
    assert report["totals"]["skills"] == len(expected)
    assert sum(report["totals"][name] for name in
               ("native", "adapted", "degraded", "claude-only")) == len(expected)
    for row in rows:
        assert row["classification"] in {"native", "adapted", "degraded", "claude-only"}
        assert row["scanned_files"], f"{row['name']}: no files scanned"
        if row["classification"] != "native":
            assert row["evidence"], f"{row['name']}: classification has no evidence"
        for item in row["evidence"]:
            assert item["line"] >= 1
            assert item["path"] in row["scanned_files"]
            assert item["text"]
            assert item["fact"]


def _base_config(home: Path, extra: str | None = None) -> str:
    root = [
        "# keep this comment",
        'default_model = "synthetic"',
        'default_permission_mode = "manual"',
    ]
    if extra is not None:
        root.append(extra)
    return "\n".join([
        *root,
        "",
        *_clade_hook_tables(home),
        *_clade_subagent_table(),
        "[user-table]",
        'extra_skill_dirs = ["$HOME/custom"]',
        'other = "keep"',
        "",
    ])


def _clade_hook_tables(home: Path) -> list[str]:
    """Every [[hooks]] table install.sh writes, read from its own declarative list.

    install.sh appends any of these that are missing, so a fixture without them
    would change by those appended tables on every install, and each assertion
    that the skill view leaves config.toml byte-identical would fail on a line
    the view never wrote. Seeding all of them keeps those assertions about the
    view. Parsed from install.sh rather than copied, so the two cannot drift.
    """
    text = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
    start = text.index("_kimi_hook_present \"$_event\"")
    body = text[text.index("<<'EOF'\n", start) + len("<<'EOF'\n"):]
    body = body[:body.index("\nEOF\n")]
    tables: list[str] = []
    for row in body.splitlines():
        event, matcher, hook, timeout, mode = row.split("^")
        command = f"{home}/.kimi-code/hooks/decision-to-kimi.sh"
        if mode == "once":
            command += " --once-per-session"
        command += f" {home}/.claude/hooks/{hook}"
        tables += [
            "[[hooks]]",
            f'event = "{event}"',
            f'matcher = "{matcher}"',
            f'command = "{command}"',
            f"timeout = {timeout}",
            "",
        ]
    assert len(tables) == 12 * 6, "install.sh's hook list changed size; recheck this fixture"
    return tables


def _clade_subagent_table() -> list[str]:
    """The [subagent] table install.sh appends when config.toml has none.

    Same reason as the hook tables above: without it every install appends the
    table, and the view's byte-identical assertions fail on lines the view
    never wrote. The value is read from install.sh's own append line.
    """
    text = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
    match = re.search(r"printf '\\n\[subagent\]\\ntimeout_ms = (\d+)\\n'", text)
    assert match, "install.sh no longer appends [subagent] timeout_ms; recheck this fixture"
    return ["[subagent]", f"timeout_ms = {match.group(1)}", ""]


@pytest.fixture
def install_sandbox():
    sandbox = Path(subprocess.check_output(["mktemp", "-d"], text=True).strip())
    try:
        home = sandbox / "home"
        kimi_home = home / ".kimi-code"
        kimi_home.mkdir(parents=True)
        config = kimi_home / "config.toml"
        config.write_text(_base_config(home), encoding="utf-8")
        store = sandbox / "store"
        store.mkdir()
        (home / ".claude").mkdir()
        (home / ".claude" / "skills").symlink_to(store, target_is_directory=True)

        repo = sandbox / "repo"
        shutil.copytree(
            REPO_ROOT,
            repo,
            ignore=shutil.ignore_patterns(
                ".git", ".venv", "node_modules", "__pycache__", "dist", ".self-test-mutation"
            ),
        )
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        no_claude = sandbox / "no-claude-bin"
        no_claude.mkdir()
        claude = no_claude / "claude"
        claude.write_text("#!/usr/bin/env bash\nexit 127\n", encoding="utf-8")
        claude.chmod(0o755)
        env = {
            "HOME": str(home),
            "KIMI_CODE_HOME": str(kimi_home),
            "PATH": str(no_claude) + os.pathsep + os.environ.get("PATH", ""),
            "TMPDIR": str(sandbox),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
        }
        yield {
            "sandbox": sandbox,
            "repo": repo,
            "home": home,
            "store": store,
            "kimi_home": kimi_home,
            "config": config,
            "env": env,
            "no_claude": no_claude,
        }
    finally:
        shutil.rmtree(sandbox)


def _insert_frontmatter(path: Path, entry: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    closing = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    lines.insert(closing, entry + "\n")
    path.write_text("".join(lines), encoding="utf-8")


def _tree_state(root: Path) -> dict[str, tuple[str, str]]:
    state: dict[str, tuple[str, str]] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            state[rel] = ("link", os.readlink(path))
        elif path.is_file():
            state[rel] = ("file", hashlib.sha256(path.read_bytes()).hexdigest())
        elif path.is_dir():
            state[rel] = ("dir", "")
    return state


def _run_install(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["bash", str(repo / "install.sh")],
        cwd=repo,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_install_builds_view_without_touching_claude_store(install_sandbox) -> None:
    repo = install_sandbox["repo"]
    home = install_sandbox["home"]
    store = install_sandbox["store"]
    config = install_sandbox["config"]
    env = install_sandbox["env"]
    source_batch = repo / "configs" / "skills" / "batch-tasks" / "SKILL.md"
    _insert_frontmatter(source_batch, "disable-model-invocation: false")
    loop_source = repo / "configs" / "skills" / "loop" / "SKILL.md"
    loop_source.write_bytes(loop_source.read_bytes().replace(b"\n", b"\r\n"))
    blog_source = repo / "configs" / "skills" / "blog" / "SKILL.md"
    blog_source.write_text(
        "\ufeff" + blog_source.read_text(encoding="utf-8") + "\n---\nbody horizontal rule\n",
        encoding="utf-8",
    )
    source_before = _tree_state(repo / "configs" / "skills")
    for skill in (repo / "configs" / "skills").iterdir():
        if skill.is_dir():
            shutil.copytree(skill, store / skill.name, dirs_exist_ok=True)
    pristine_store = _tree_state(store)

    _run_install(repo, env)
    assert _tree_state(store) == pristine_store, "the first install mutated Claude's pristine store"
    user_skill = store / "user-native"
    (user_skill / "references").mkdir(parents=True)
    (user_skill / "SKILL.md").write_text(
        "---\nname: user-native\ndescription: User-owned native skill\n---\nRead me.\n",
        encoding="utf-8",
    )
    (user_skill / "references" / "note.txt").write_text("keep me\n", encoding="utf-8")
    store_before = _tree_state(store)
    config_before = config.read_bytes()

    second = _run_install(repo, env)
    assert _tree_state(store) == store_before, "Claude's sync store changed byte-for-byte"
    assert config.read_bytes() == config_before
    # The summary counts wirings in config.toml, not the one adapter file.
    assert "12 Clade hooks wired in config.toml" in second.stdout, second.stdout[-800:]
    assert _tree_state(repo / "configs" / "skills") == source_before

    view = home / ".kimi-code" / "clade-skills"
    assert view.is_dir() and not view.is_symlink()
    assert (view / ".clade-managed").read_text() == "clade-kimi-skill-view-v1\n"
    for name in ("commit", "user-native"):
        assert (view / name).is_symlink()
        assert os.readlink(view / name) == str(home / ".claude" / "skills" / name)
    assert (view / "user-native" / "references" / "note.txt").read_text() == "keep me\n"

    flagged = view / "blog"
    assert flagged.is_dir() and not flagged.is_symlink()
    assert not (flagged / "SKILL.md").is_symlink()
    flagged_text = (flagged / "SKILL.md").read_text(encoding="utf-8")
    assert flagged_text.count("disableModelInvocation: true") == 1
    assert flagged_text.startswith("\ufeff---\n")
    frontmatter_close = flagged_text.index("\n---\n", len("\ufeff---\n"))
    assert flagged_text.index("disableModelInvocation: true") < frontmatter_close
    assert "\n---\nbody horizontal rule" in flagged_text
    assert (flagged / "references").is_symlink()
    assert (flagged / "prompt.md").is_symlink()
    assert (flagged / "references" / "content-templates.md").read_bytes() == (
        store / "blog" / "references" / "content-templates.md"
    ).read_bytes()
    preserved = (view / "batch-tasks" / "SKILL.md").read_text()
    assert "disable-model-invocation: false" in preserved
    assert "disableModelInvocation: true" not in preserved
    assert "disableModelInvocation: true" not in (store / "blog" / "SKILL.md").read_text()
    assert b"disableModelInvocation: true\r\n" in (view / "loop" / "SKILL.md").read_bytes()

    view_before = _tree_state(view)
    flagged_mtime = (flagged / "SKILL.md").stat().st_mtime_ns
    link_mtime = (view / "commit").lstat().st_mtime_ns
    config_mtime = config.stat().st_mtime_ns
    config_before = config.read_bytes()
    _run_install(repo, env)
    assert _tree_state(view) == view_before
    assert (flagged / "SKILL.md").stat().st_mtime_ns == flagged_mtime
    assert (view / "commit").lstat().st_mtime_ns == link_mtime
    assert config.stat().st_mtime_ns == config_mtime
    assert config.read_bytes() == config_before
    assert _tree_state(store) == store_before

    (view / "stale").symlink_to(home / ".claude" / "skills" / "commit", target_is_directory=True)
    shutil.rmtree(user_skill)
    shutil.rmtree(repo / "configs" / "skills" / "blog" / "references")
    _run_install(repo, env)
    assert not os.path.lexists(view / "stale")
    assert not os.path.lexists(view / "user-native")
    assert not os.path.lexists(flagged / "references")
    assert (store / "commit" / "SKILL.md").is_file(), "pruning followed a symlink into the store"

    saved_view = install_sandbox["sandbox"] / "saved-view"
    view.rename(saved_view)
    view.mkdir()
    (view / "sentinel").write_text("unowned\n", encoding="utf-8")
    unmarked_config = config.read_bytes()
    skipped = _run_install(repo, env)
    assert (view / "sentinel").read_text() == "unowned\n"
    assert not (view / ".clade-managed").exists()
    assert config.read_bytes() == unmarked_config
    assert "without the Clade marker" in skipped.stdout


@pytest.mark.parametrize("mode", ["absent", "compact", "spaced", "custom"])
def test_extra_skill_dirs_migration_is_root_scoped_and_lossless(install_sandbox, mode: str) -> None:
    repo = install_sandbox["repo"]
    home = install_sandbox["home"]
    config = install_sandbox["config"]
    env = install_sandbox["env"]
    old = str(home / ".claude" / "skills")
    old_lines = {
        "compact": f'extra_skill_dirs = ["{old}"]',
        "spaced": f'extra_skill_dirs = [ "{old}" ]',
        "custom": 'extra_skill_dirs = ["$HOME/team-skills"]',
    }
    extra = old_lines.get(mode)
    config.write_text(_base_config(home, extra), encoding="utf-8")
    before = config.read_text()
    result = _run_install(repo, env)
    after = config.read_text()
    view = home / ".kimi-code" / "clade-skills"

    if mode == "custom":
        assert after == before
        assert str(view) in result.stdout
        assert "user-set extra_skill_dirs left unchanged" in result.stdout
        lines = config.read_text().splitlines()
        first_extra = next(i for i, line in enumerate(lines) if line.startswith("extra_skill_dirs"))
        lines[first_extra] = f'extra_skill_dirs = ["{old}"]'
        first_table = next(i for i, line in enumerate(lines) if line.startswith("["))
        lines.insert(first_table, 'extra_skill_dirs = ["$HOME/other-skills"]')
        config.write_text("\n".join(lines) + "\n", encoding="utf-8")
        ambiguous_before = config.read_bytes()
        ambiguous = _run_install(repo, env)
        assert config.read_bytes() == ambiguous_before
        assert "root extra_skill_dirs is ambiguous" in ambiguous.stdout
        return

    parsed = tomllib.loads(after)
    assert parsed["extra_skill_dirs"] == [str(view)]
    assert parsed["user-table"]["extra_skill_dirs"] == ["$HOME/custom"]
    desired = f'extra_skill_dirs = ["{view}"]'
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    if mode == "absent":
        assert [line for line in after_lines if line != desired] == before_lines
    else:
        assert len(after_lines) == len(before_lines)
        changed = [index for index, pair in enumerate(zip(before_lines, after_lines)) if pair[0] != pair[1]]
        assert len(changed) == 1
        index = changed[0]
        assert before_lines[index] == old_lines[mode]
        assert after_lines[index] == desired
        assert before_lines[index + 1:] == after_lines[index + 1:]


@pytest.mark.parametrize("form", ["multiline", "quoted", "nested", "multiline-bracket"])
def test_noncanonical_extra_skill_dirs_never_gets_a_duplicate(install_sandbox, form: str) -> None:
    repo = install_sandbox["repo"]
    home = install_sandbox["home"]
    config = install_sandbox["config"]
    env = install_sandbox["env"]
    old = str(home / ".claude" / "skills")
    extras = {
        "multiline": f'extra_skill_dirs = [\n  "{old}",\n]',
        "quoted": f'"extra_skill_dirs" = ["{old}"]',
        "nested": f'extra_skill_dirs = [["{old}"]]',
        "multiline-bracket": f'extra_skill_dirs = [\n  [ "{old}" ],\n]',
    }
    config.write_text(_base_config(home, extras[form]), encoding="utf-8")
    before = config.read_bytes()
    tomllib.loads(before.decode())
    result = _run_install(repo, env)
    assert config.read_bytes() == before
    tomllib.loads(config.read_text())
    assert "left unchanged" in result.stdout
    assert (home / ".kimi-code" / "clade-skills" / ".clade-managed").is_file()


def test_original_invalid_toml_is_not_repaired_or_rewritten(install_sandbox) -> None:
    repo = install_sandbox["repo"]
    home = install_sandbox["home"]
    config = install_sandbox["config"]
    env = install_sandbox["env"]
    adjacent_strings = f'extra_skill_dirs = [ "{home}/" ".claude/skills" ]'
    config.write_text(_base_config(home, adjacent_strings), encoding="utf-8")
    before = config.read_bytes()
    with pytest.raises(tomllib.TOMLDecodeError):
        tomllib.loads(before.decode())
    result = _run_install(repo, env)
    assert config.read_bytes() == before
    assert "original config.toml does not parse" in result.stdout


@pytest.mark.parametrize("form", ["missing", "unclosed"])
def test_malformed_claude_only_frontmatter_is_omitted_without_traceback(install_sandbox, form: str) -> None:
    repo = install_sandbox["repo"]
    home = install_sandbox["home"]
    config = install_sandbox["config"]
    env = install_sandbox["env"]
    source = repo / "configs" / "skills" / "loop" / "SKILL.md"
    view_skill = home / ".kimi-code" / "clade-skills" / "loop" / "SKILL.md"
    _run_install(repo, env)
    assert view_skill.is_file()
    malformed = {
        "missing": "no front matter\n\n---\n\nrule above\n",
        "unclosed": "---\nname: loop\ndescription: no closing fence\nbody\n",
    }
    source.write_text(malformed[form], encoding="utf-8")
    config_before = config.read_bytes()

    result = _run_install(repo, env)
    assert "Omitted claude-only skill loop" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr
    assert not os.path.lexists(view_skill)
    assert config.read_bytes() == config_before
    tomllib.loads(config.read_text())
    assert (home / ".kimi-code" / "clade-skills" / "commit").is_symlink()


@pytest.mark.parametrize("failure_kind", ["exit", "empty"])
def test_symlink_failure_keeps_old_config_and_creates_no_view(install_sandbox, failure_kind: str) -> None:
    repo = install_sandbox["repo"]
    home = install_sandbox["home"]
    config = install_sandbox["config"]
    env = install_sandbox["env"]
    old = str(home / ".claude" / "skills")
    config.write_text(_base_config(home, f'extra_skill_dirs = ["{old}"]'), encoding="utf-8")
    before = config.read_bytes()
    real_ln = shutil.which("ln")
    assert real_ln
    fake_ln = install_sandbox["no_claude"] / "ln"
    exit_code = "1" if failure_kind == "exit" else "0"
    fake_ln.write_text(
        "#!/usr/bin/env bash\n"
        "for arg in \"$@\"; do\n"
        f"  case \"$arg\" in *clade-symlink-probe*|*clade-skills*) exit {exit_code} ;; esac\n"
        "done\n"
        f"exec \"{real_ln}\" \"$@\"\n",
        encoding="utf-8",
    )
    fake_ln.chmod(0o755)

    result = _run_install(repo, env)
    assert "symlink support" in result.stdout
    assert config.read_bytes() == before
    assert not os.path.lexists(home / ".kimi-code" / "clade-skills")

    if failure_kind != "exit":
        return
    fake_ln.unlink()
    scanner = repo / "configs" / "scripts" / "kimi-skill-compat.py"
    scanner_text = scanner.read_text()
    scanner.write_text("deliberately invalid Python\n", encoding="utf-8")
    failed_scan = _run_install(repo, env)
    assert "compatibility scan failed" in failed_scan.stdout
    assert config.read_bytes() == before
    assert not os.path.lexists(home / ".kimi-code" / "clade-skills")

    scanner.write_text(scanner_text, encoding="utf-8")
    for executable in ("python", "python3"):
        stub = install_sandbox["no_claude"] / executable
        stub.write_text("#!/usr/bin/env bash\nexit 127\n", encoding="utf-8")
        stub.chmod(0o755)
    no_python = _run_install(repo, env)
    assert "no working Python or scanner" in no_python.stdout
    assert config.read_bytes() == before
    assert not os.path.lexists(home / ".kimi-code" / "clade-skills")



def _write_transition_skill(root: Path, name: str, disable: bool) -> None:
    (root / "references").mkdir(parents=True)
    (root / "scripts").mkdir()
    disabled = "disableModelInvocation: true\n" if disable else ""
    (root / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Transition test skill\n{disabled}---\nRead the source.\n",
        encoding="utf-8",
    )
    (root / "prompt.md").write_text("Use Read and Bash.\n", encoding="utf-8")
    (root / "references" / "note.txt").write_text("source reference\n", encoding="utf-8")
    (root / "scripts" / "run.sh").write_text("#!/bin/sh\nprintf 'source script'\n", encoding="utf-8")


def _assert_source_matches_repo(repo: Path, store: Path, name: str) -> None:
    expected = _tree_state(repo / "configs" / "skills" / name)
    assert _tree_state(store / name) == expected
    assert all(kind != "link" for kind, _ in expected.values()), "source gained a symlink"


def test_classification_transitions_never_write_through_source(install_sandbox) -> None:
    repo = install_sandbox["repo"]
    home = install_sandbox["home"]
    store = install_sandbox["store"]
    env = install_sandbox["env"]
    names = ("transition-skill", "same-content-skill")
    for name in names:
        source = repo / "configs" / "skills" / name
        source.mkdir()
        _write_transition_skill(source, name, disable=name == "same-content-skill")

    _run_install(repo, env)
    view = home / ".kimi-code" / "clade-skills"
    for name in names:
        assert (view / name).is_symlink()
        _assert_source_matches_repo(repo, store, name)

    same_view = view / "same-content-skill"
    same_view.unlink()
    same_view.mkdir()
    (same_view / "SKILL.md").symlink_to(store / "same-content-skill" / "SKILL.md")

    for name in names:
        (repo / "configs" / "skills" / name / "prompt.md").write_text(
            "Run claude -p for the worker.\n", encoding="utf-8"
        )
    _run_install(repo, env)
    for name in names:
        flagged = view / name
        assert flagged.is_dir() and not flagged.is_symlink()
        assert not (flagged / "SKILL.md").is_symlink()
        assert (flagged / "SKILL.md").read_text().count("disableModelInvocation: true") == 1
        for child in ("prompt.md", "references", "scripts"):
            assert (flagged / child).is_symlink()
        assert (flagged / "references" / "note.txt").read_text() == "source reference\n"
        _assert_source_matches_repo(repo, store, name)
    assert "disableModelInvocation: true" not in (
        store / "transition-skill" / "SKILL.md"
    ).read_text()

    (repo / "configs" / "skills" / "transition-skill" / "prompt.md").write_text(
        "Use Read and Bash.\n", encoding="utf-8"
    )
    _run_install(repo, env)
    assert (view / "transition-skill").is_symlink()
    assert os.readlink(view / "transition-skill") == str(
        home / ".claude" / "skills" / "transition-skill"
    )
    for name in names:
        _assert_source_matches_repo(repo, store, name)


def test_text_only_config_rule_when_tomllib_is_unavailable(tmp_path, monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location(
        "kimi_skill_view_text_only", REPO_ROOT / "configs" / "scripts" / "kimi-skill-view.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "tomllib", None)
    source = tmp_path / "source"
    source.mkdir()
    view = tmp_path / ".kimi-code" / "clade-skills"
    config = tmp_path / "config.toml"
    old = str(source)
    extras = (
        f'extra_skill_dirs = [\n  "{old}",\n]',
        f'"extra_skill_dirs" = ["{old}"]',
        f'extra_skill_dirs = [["{old}"]]',
    )
    for extra in extras:
        config.write_text(_base_config(tmp_path, extra), encoding="utf-8")
        before = config.read_bytes()
        module.configure_view(source, view, config)
        assert config.read_bytes() == before

    for extra in (f'extra_skill_dirs = ["{old}"]', f'extra_skill_dirs = [ "{old}" ]'):
        config.write_text(_base_config(tmp_path, extra), encoding="utf-8")
        before = config.read_text()
        module.configure_view(source, view, config)
        after = config.read_text()
        assert tomllib.loads(after)["extra_skill_dirs"] == [str(view)]
        before_lines = before.splitlines()
        after_lines = after.splitlines()
        assert len(before_lines) == len(after_lines)
        changed = [i for i, pair in enumerate(zip(before_lines, after_lines)) if pair[0] != pair[1]]
        assert len(changed) == 1


def test_kimi_agents_tool_map_matches_every_scanner_rule() -> None:
    """KIMI_AGENTS.md's map is what a Kimi session reads; the scanner's RULES
    are what classified the skills. One stated mapping, checked from both ends."""
    spec = importlib.util.spec_from_file_location("kimi_skill_compat_rules", SCANNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    text = (REPO_ROOT / "configs" / "KIMI_AGENTS.md").read_text(encoding="utf-8")
    section = text[text.index("### Clade Skills Written for Claude Code"):]
    section = section[:section.index("\n## ")]
    pairs = re.findall(r"`([^`]+)` → `([^`]+)`", section)
    stated = dict(pairs)
    assert len(stated) == len(pairs), "a Claude name is mapped twice"
    # test_native_delegation_agents.py keeps these names out of the policy
    # entirely, so the scanner's ScheduleWakeup → CronCreate rule is not stated.
    unstated = {"ScheduleWakeup"}
    mapped = {rule.primitive: rule.kimi.split()[0] for rule in module.RULES
              if rule.kimi is not None and rule.primitive not in unstated}
    assert len(mapped) >= 10, "an empty rule table would make this test vacuous"
    assert stated == mapped
