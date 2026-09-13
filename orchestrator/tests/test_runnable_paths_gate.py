"""The gate that was withdrawn once, and what changed before it shipped.

`check-references.py` strips inline code spans by design, so every runnable path
was invisible to it — which is how five installer paths that had never existed
survived every gate in this repository. A first replacement ran at roughly 30%
precision and was not shipped, because a gate at that precision gets routed
around instead of satisfied.

These pin the discriminations that took it from 111 findings to 22, all real:
what counts as the skill's own namespace, what is the reader's project, what is
runtime state, and what a paragraph has already declared absent. And they pin
the ratchet, because a baseline that can grow is an exception list.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "configs" / "scripts" / "check-runnable-paths.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_runnable_paths", GATE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_runnable_paths"] = module
    spec.loader.exec_module(module)
    return module


gate = _load()


def test_self_test_passes():
    # A gate that cannot fire reports a clean tree exactly like a clean tree.
    assert gate.self_test() == 0


def test_the_tree_is_clean_against_the_baseline():
    out = subprocess.run([sys.executable, str(GATE)], capture_output=True, text=True,
                         check=False)
    assert out.returncode == 0, out.stdout


def test_the_baseline_is_not_empty_and_every_entry_is_a_pair():
    # An empty baseline would mean the ratchet has nothing to hold and the
    # 22 known phantoms silently stopped being reported.
    assert gate.BASELINE
    for entry in gate.BASELINE:
        assert isinstance(entry, tuple) and len(entry) == 2
        assert entry[0].startswith("configs/skills/")


def test_every_baseline_entry_still_fires():
    # A stale exception is how a baseline becomes permanent.
    phantoms, _missing, _checked = gate.scan()
    seen = set()
    for line in phantoms:
        match = re.match(r"(\S+?):\d+: (\S+) —", line)
        if match:
            seen.add((match.group(1), match.group(2)))
    stale = gate.BASELINE - seen
    assert not stale, f"baseline entries that no longer fire: {sorted(stale)}"


def test_a_readers_project_path_is_never_examined():
    # The exact class that withdrew attempt one.
    for path in ("lib/github-client.ts", "src/components/Button.tsx",
                 "app/models/user.rb", "pkg/server/main.go"):
        assert not gate._OWNED.search(f"Edit `{path}` in the project.")


def test_a_skills_own_namespace_is_examined():
    for path in ("scripts/thing.py", "references/notes.md", "assets/logo.svg",
                 "agents/some-agent.md", "~/.claude/scripts/x.py"):
        assert gate._OWNED.search(f"Run `{path}` now."), path


def test_runtime_state_under_claude_is_not_an_install_claim():
    for path in ("corrections/rules.md", "orchestrator/usage.db", "rules/x.md"):
        assert gate.claude_target(f"~/.claude/{path}") is False, path


def test_an_installed_subtree_under_claude_is_an_install_claim():
    assert gate.claude_target("~/.claude/scripts/committer.sh") is not False
    assert gate.claude_target("~/.claude/scripts/never-shipped-xyz.py") is None


def test_a_glob_is_not_a_path():
    # `~/.claude/scripts/equip_*.py` matched up to the asterisk.
    line = "Scripts live at `~/.claude/scripts/equip_*.py`."
    match = gate._OWNED.search(line)
    assert match
    assert line[match.end("path"):match.end("path") + 1] == "*"


def test_the_absence_exemption_is_scoped_to_the_paragraph():
    # Too narrow and it reports the fix as the defect; too wide and an unrelated
    # sentence five lines away suppresses a real finding. Both happened.
    lines = ["There is no sync script.", "It never existed.", "", "Run `scripts/x.py`."]
    assert "never existed" in gate._paragraph_at(lines, 1)
    assert "never existed" not in gate._paragraph_at(lines, 4)


def test_no_absence_marker_is_a_word_a_filename_could_contain():
    # "phantom" was a marker until a test file named brand-new-phantom.py
    # suppressed its own finding.
    for marker in gate._ABSENCE_MARKERS:
        assert " " in marker, f"{marker!r} is a single word a path could contain"


def test_a_new_phantom_fails_the_build(tmp_path, monkeypatch):
    skills = tmp_path / "configs" / "skills" / "thing"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("Run `scripts/nope.py`.\n", encoding="utf-8")
    monkeypatch.setattr(gate, "REPO", tmp_path)
    monkeypatch.setattr(gate, "SKILLS", tmp_path / "configs" / "skills")
    monkeypatch.setattr(gate, "SHARED", tmp_path / "configs" / "scripts")
    monkeypatch.setattr(gate, "AGENTS", tmp_path / "configs" / "agents")
    (tmp_path / "configs" / "scripts").mkdir(parents=True)
    (tmp_path / "configs" / "agents").mkdir(parents=True)
    phantoms, _missing, _checked = gate.scan()
    assert any("nope.py" in line for line in phantoms)
