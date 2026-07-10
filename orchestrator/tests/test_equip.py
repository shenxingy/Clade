"""Tests for /equip's scanner (equip_scan.py), auditor (equip_audit.py), and
shared helpers (equip_common.py).

Round-4 elite-learnings gap: extend /equip audits to agents/scripts/hooks
(classify_agents() was a literal TODO stub), add a wildcard-tool-consent
flag (tw93/Waza pattern), and add a `pinned_ref` to the Upstream tracking
model for reproducible absorption.

configs/scripts/equip_*.py are standalone CLI-layer scripts with no
orchestrator dependency — load them via sys.path insertion (not the
conftest MagicMock-bypass pattern used for worker_*.py; nothing in conftest
mocks anything named `equip_*`, so a plain import is safe).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _REPO_ROOT / "configs" / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import equip_audit as ea  # noqa: E402
import equip_common as ec  # noqa: E402
import equip_scan as es  # noqa: E402


# ─── Git test helpers ───────────────────────────────────────────────────────

def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q", "-b", "main"], cwd=path)
    _git(["config", "user.email", "test@example.com"], cwd=path)
    _git(["config", "user.name", "Test"], cwd=path)


def _rev_parse(ref: str, cwd: Path) -> str:
    return _git(["rev-parse", ref], cwd=cwd).stdout.strip()


# ─── Upstream.pinned_ref: dataclass + backward compat ──────────────────────

def test_upstream_pinned_ref_defaults_none_and_round_trips():
    u = ec.Upstream(id="foo", repo="owner/foo")
    assert u.pinned_ref is None
    assert u.to_dict()["pinned_ref"] is None

    # Old upstreams.yaml entries written before this feature existed have no
    # pinned_ref key at all — from_dict must default it, not KeyError.
    legacy = ec.Upstream.from_dict({"id": "foo", "repo": "owner/foo"})
    assert legacy.pinned_ref is None

    pinned = ec.Upstream.from_dict({"id": "foo", "repo": "owner/foo", "pinned_ref": "v1.2.3"})
    assert pinned.pinned_ref == "v1.2.3"
    assert pinned.to_dict()["pinned_ref"] == "v1.2.3"


# ─── clone_or_update_cache: pinned_ref vs branch-tracking (real git) ───────
#
# Upstream.repo is deliberately a placeholder in these tests: equip_common
# rewrites any non-URL-looking `repo` into a github.com URL (owner/repo
# shorthand), which would mangle a local test-fixture path. Pre-seeding the
# cache with a manual `git clone` from the local fixture repo (bypassing that
# rewrite) puts `clone_or_update_cache` on its "cache already exists → update"
# branch, which is exactly where the new ref-selection logic lives — `repo`
# is never consulted on that branch.

def test_clone_or_update_cache_tracks_branch_head_when_unpinned(tmp_path):
    upstream_repo = tmp_path / "upstream"
    _init_repo(upstream_repo)
    (upstream_repo / "a.txt").write_text("v1\n")
    _git(["add", "a.txt"], cwd=upstream_repo)
    _git(["commit", "-q", "-m", "v1"], cwd=upstream_repo)
    _git(["tag", "v1.0"], cwd=upstream_repo)
    (upstream_repo / "a.txt").write_text("v2\n")
    _git(["add", "a.txt"], cwd=upstream_repo)
    _git(["commit", "-q", "-m", "v2"], cwd=upstream_repo)
    v2_sha = _rev_parse("HEAD", upstream_repo)
    v1_sha = _rev_parse("v1.0", upstream_repo)
    assert v1_sha != v2_sha

    project = tmp_path / "project"
    project.mkdir()
    cache = ec.cache_dir(project) / "up"
    cache.parent.mkdir(parents=True, exist_ok=True)
    _git(["clone", "-q", "--branch", "v1.0", str(upstream_repo), str(cache)], cwd=tmp_path)

    u = ec.Upstream(id="up", repo="placeholder/unused", branch="main", pinned_ref=None)
    ec.clone_or_update_cache(project, u)

    assert _rev_parse("HEAD", cache) == v2_sha  # tracked main's HEAD, not the old v1.0 checkout


def test_clone_or_update_cache_checks_out_pinned_ref_not_branch_head(tmp_path):
    upstream_repo = tmp_path / "upstream"
    _init_repo(upstream_repo)
    (upstream_repo / "a.txt").write_text("v1\n")
    _git(["add", "a.txt"], cwd=upstream_repo)
    _git(["commit", "-q", "-m", "v1"], cwd=upstream_repo)
    _git(["tag", "v1.0"], cwd=upstream_repo)
    (upstream_repo / "a.txt").write_text("v2\n")
    _git(["add", "a.txt"], cwd=upstream_repo)
    _git(["commit", "-q", "-m", "v2"], cwd=upstream_repo)
    v1_sha = _rev_parse("v1.0", upstream_repo)

    project = tmp_path / "project"
    project.mkdir()
    cache = ec.cache_dir(project) / "up"
    cache.parent.mkdir(parents=True, exist_ok=True)
    _git(["clone", "-q", str(upstream_repo), str(cache)], cwd=tmp_path)
    assert _rev_parse("HEAD", cache) != v1_sha  # precondition: cloned at main HEAD (v2)

    u = ec.Upstream(id="up", repo="placeholder/unused", branch="main", pinned_ref="v1.0")
    ec.clone_or_update_cache(project, u)

    assert _rev_parse("HEAD", cache) == v1_sha  # pinned, NOT main's current HEAD


def test_clone_or_update_cache_fresh_clone_command_sequence(tmp_path, monkeypatch):
    """No pre-existing cache: verify the exact git command sequence issued for
    both the unpinned (single --branch clone) and pinned (clone + fetch +
    detached checkout) cases, without touching the network."""
    calls: list[list[str]] = []

    def fake_run(cmd, cwd=None, check=True, capture=True):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(ec, "run", fake_run)

    project = tmp_path / "project"
    project.mkdir()

    # Unpinned: single clone --branch <branch>, backward-compatible.
    u1 = ec.Upstream(id="unpinned", repo="owner/repo", branch="main")
    ec.clone_or_update_cache(project, u1)
    assert calls == [["git", "clone", "--depth", "1", "--branch", "main",
                       "https://github.com/owner/repo.git", str(ec.cache_dir(project) / "unpinned")]]

    calls.clear()

    # Pinned: shallow clone (no --branch) then fetch + detached checkout of the pin.
    u2 = ec.Upstream(id="pinned", repo="owner/repo", branch="main", pinned_ref="deadbeef")
    ec.clone_or_update_cache(project, u2)
    cache2 = str(ec.cache_dir(project) / "pinned")
    assert calls[0] == ["git", "clone", "--depth", "1", "https://github.com/owner/repo.git", cache2]
    assert calls[1] == ["git", "fetch", "--depth", "1", "origin", "deadbeef"]
    assert calls[2] == ["git", "checkout", "--detach", "FETCH_HEAD"]


# ─── read_frontmatter / classify_tool_permission ───────────────────────────

def test_read_frontmatter_parses_yaml_block(tmp_path):
    f = tmp_path / "agent.md"
    f.write_text("---\nname: foo\ntools:\n  - Read\n  - Bash\n---\nBody text\n")
    front = ec.read_frontmatter(f)
    assert front["name"] == "foo"
    assert front["tools"] == ["Read", "Bash"]


def test_read_frontmatter_missing_block_returns_empty(tmp_path):
    f = tmp_path / "plain.md"
    f.write_text("# just a heading, no frontmatter\n")
    assert ec.read_frontmatter(f) == {}


def test_read_frontmatter_missing_file_returns_empty(tmp_path):
    assert ec.read_frontmatter(tmp_path / "nope.md") == {}


def test_classify_tool_permission_wildcard_string_token():
    assert ec.classify_tool_permission({"tools": "*"}) == "wildcard"
    assert ec.classify_tool_permission({"allowed-tools": "all"}) == "wildcard"


def test_classify_tool_permission_wildcard_inside_list():
    assert ec.classify_tool_permission({"tools": ["Read", "*"]}) == "wildcard"


def test_classify_tool_permission_broad_allowlist_without_wildcard():
    perm = ec.classify_tool_permission(
        {"tools": ["Read", "Write", "Edit", "Bash", "WebFetch", "WebSearch"]}
    )
    assert perm == "broad"


def test_classify_tool_permission_normal_allowlist_is_none():
    assert ec.classify_tool_permission({"tools": "Read, Bash, Grep, Glob"}) is None


def test_classify_tool_permission_no_tools_key_is_none():
    assert ec.classify_tool_permission({"name": "foo"}) is None


# ─── detect_upstream_*_dir / hooks_root ─────────────────────────────────────

def test_detect_upstream_dirs_for_each_kind(tmp_path):
    (tmp_path / "agents").mkdir()
    (tmp_path / "configs" / "scripts").mkdir(parents=True)
    assert ec.detect_upstream_agents_dir(tmp_path) == tmp_path / "agents"
    assert ec.detect_upstream_scripts_dir(tmp_path) == tmp_path / "configs" / "scripts"
    assert ec.detect_upstream_hooks_dir(tmp_path) is None  # not present → None, no crash


def test_hooks_root_kit_style_vs_plugin_style(tmp_path):
    kit = tmp_path / "kit"
    (kit / "configs" / "skills").mkdir(parents=True)
    assert ec.hooks_root(kit) == kit / "configs" / "hooks"

    plugin = tmp_path / "plugin"
    (plugin / "skills").mkdir(parents=True)
    (plugin / "install.sh").touch()
    assert ec.hooks_root(plugin) == plugin / "hooks"


# ─── equip_scan: classify_agents() for real (not the TODO stub) ───────────

def test_classify_agents_absorbed_modified_native_orphan(tmp_path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "clean.md").write_text("---\nname: clean\n---\nbody\n")
    (agents_dir / "edited.md").write_text("---\nname: edited\n---\nlocal edit\n")
    (agents_dir / "mine.md").write_text("---\nname: mine\n---\nnative body\n")
    (agents_dir / "orphaned.md").write_text("Sourced from AgriciDaniel/some-repo\n")

    upstream_hashes = {
        "up1": {
            "clean.md": es.file_hash(agents_dir / "clean.md"),
            "edited.md": "deadbeef" * 8,  # deliberately different from local
        }
    }
    results = {r["name"]: r for r in es.classify_agents(agents_dir, upstream_hashes)}

    assert results["clean"]["class"] == "absorbed"
    assert results["clean"]["upstream"] == "up1"
    assert results["clean"]["kind"] == "agent"
    assert results["edited"]["class"] == "modified-absorbed"
    assert results["mine"]["class"] == "native"
    assert results["orphaned"]["class"] == "orphan"
    assert results["orphaned"]["hint"] == "AgriciDaniel-ecosystem"


def test_classify_agents_surfaces_wildcard_tool_permission(tmp_path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "yolo.md").write_text('---\nname: yolo\ntools: "*"\n---\nbody\n')
    (agents_dir / "scoped.md").write_text("---\nname: scoped\ntools: Read, Grep\n---\nbody\n")

    results = {r["name"]: r for r in es.classify_agents(agents_dir, {})}
    assert results["yolo"]["tool_permission"] == "wildcard"
    assert "tool_permission" not in results["scoped"]


def test_classify_scripts_and_hooks_are_flat_and_tagged_by_kind(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "run.sh").write_text("#!/bin/bash\necho hi\n")
    (scripts_dir / "sub").mkdir()  # subdir must be skipped (non-recursive, top-level pass)
    (scripts_dir / "sub" / "nested.sh").write_text("echo nested\n")

    script_results = es.classify_scripts(scripts_dir, {})
    assert {r["name"] for r in script_results} == {"run.sh"}
    assert script_results[0]["kind"] == "script"
    assert script_results[0]["class"] == "native"

    hooks_dir = tmp_path / "hooks"
    hooks_dir.mkdir()
    (hooks_dir / "pre.sh").write_text("echo pre\n")
    (hooks_dir / "lib").mkdir()

    hook_results = es.classify_hooks(hooks_dir, {})
    assert {r["name"] for r in hook_results} == {"pre.sh"}
    assert hook_results[0]["kind"] == "hook"


def test_equip_scan_main_includes_agents_scripts_hooks_in_inventory(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    (project / "configs" / "skills" / "sample-skill").mkdir(parents=True)
    (project / "configs" / "skills" / "sample-skill" / "SKILL.md").write_text(
        "---\nname: sample-skill\ndescription: x\n---\nbody\n"
    )
    (project / "configs" / "agents").mkdir(parents=True)
    (project / "configs" / "agents" / "myagent.md").write_text(
        "---\nname: myagent\ndescription: y\ntools: Read, Bash\n---\nbody\n"
    )
    (project / "configs" / "scripts").mkdir(parents=True)
    (project / "configs" / "scripts" / "helper.sh").write_text("#!/bin/bash\necho hi\n")
    (project / "configs" / "hooks").mkdir(parents=True)
    (project / "configs" / "hooks" / "pre.sh").write_text("echo pre\n")

    monkeypatch.setattr(sys, "argv", ["equip_scan.py", "--project", str(project)])
    rc = es.main()
    assert rc == 0

    inv = ec.load_yaml(project / ".claude" / "equipment" / "inventory.yaml")
    assert inv["summary"]["agents"] == 1
    assert inv["summary"]["scripts"] == 1
    assert inv["summary"]["hooks"] == 1
    assert {a["kind"] for a in inv["agents"]} == {"agent"}
    assert {s["kind"] for s in inv["scripts"]} == {"script"}
    assert {h["kind"] for h in inv["hooks"]} == {"hook"}


# ─── equip_audit: wildcard-tool-consent flag ───────────────────────────────

def test_check_tool_consent_flags_wildcard_as_block(tmp_path):
    agent_md = tmp_path / "wild.md"
    agent_md.write_text('---\nname: wild\ndescription: d\ntools: "*"\n---\nbody\n')
    flags: list = []
    ea.check_tool_consent(agent_md, flags)
    assert any(f.id == "PERM-01" and f.severity == "block" for f in flags)


def test_check_tool_consent_flags_broad_as_warn(tmp_path):
    agent_md = tmp_path / "broad.md"
    agent_md.write_text(
        "---\nname: broad\ndescription: d\ntools: Read, Write, Edit, Bash, WebFetch, WebSearch\n---\nbody\n"
    )
    flags: list = []
    ea.check_tool_consent(agent_md, flags)
    assert any(f.id == "PERM-02" and f.severity == "warn" for f in flags)
    assert not any(f.id == "PERM-01" for f in flags)


def test_check_tool_consent_scoped_tools_no_flag(tmp_path):
    agent_md = tmp_path / "scoped.md"
    agent_md.write_text("---\nname: scoped\ndescription: d\ntools: Read, Grep\n---\nbody\n")
    flags: list = []
    ea.check_tool_consent(agent_md, flags)
    assert not any(f.id.startswith("PERM") for f in flags)


def test_audit_agent_wildcard_forces_needs_review(tmp_path):
    agent_md = tmp_path / "wild.md"
    agent_md.write_text('---\nname: wild\ndescription: d\ntools: "*"\n---\nbody\n')
    a = ea.audit_agent(agent_md, None)
    a.compute_decision(overlap_native=False)
    assert a.decision == "NEEDS-REVIEW"
    assert any(f.id == "PERM-01" for f in a.flags)


def test_audit_agent_clean_adopts(tmp_path):
    agent_md = tmp_path / "clean.md"
    agent_md.write_text(
        "---\nname: clean\ndescription: d\ntools: Read, Grep\n---\n" + "line\n" * 5
    )
    a = ea.audit_agent(agent_md, None)
    a.compute_decision(overlap_native=False)
    assert a.decision == "ADOPT"
    assert a.flags == []


def test_audit_skill_wildcard_allowed_tools_flagged(tmp_path):
    skill_dir = tmp_path / "wild-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        '---\nname: wild-skill\ndescription: d\nallowed-tools:\n  - "*"\n---\n'
    )
    (skill_dir / "prompt.md").write_text("line\n" * 25)
    a = ea.audit_skill(skill_dir, None)
    a.compute_decision(overlap_native=False)
    assert any(f.id == "PERM-01" for f in a.flags)
    assert a.decision == "NEEDS-REVIEW"


def test_equip_audit_main_self_audit_includes_agent_section(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    (project / "configs" / "skills" / "sample-skill").mkdir(parents=True)
    (project / "configs" / "skills" / "sample-skill" / "SKILL.md").write_text(
        "---\nname: sample-skill\ndescription: d\n---\nbody\n"
    )
    (project / "configs" / "skills" / "sample-skill" / "prompt.md").write_text("line\n" * 25)
    (project / "configs" / "agents").mkdir(parents=True)
    (project / "configs" / "agents" / "wild.md").write_text(
        '---\nname: wild\ndescription: d\ntools: "*"\n---\nbody\n'
    )
    _init_repo(project)
    (project / ".gitkeep").touch()
    _git(["add", "-A"], cwd=project)
    _git(["commit", "-q", "-m", "init"], cwd=project)

    monkeypatch.setattr(sys, "argv", ["equip_audit.py", "--project", str(project), "--target", "."])
    rc = ea.main()
    assert rc == 0

    reports = list((project / ".claude" / "equipment" / "audits").glob("self-*.md"))
    assert len(reports) == 1
    text = reports[0].read_text()
    assert "## Agents (informational" in text
    assert "`wild`" in text
    assert "PERM-01" in text


# ─── Layout E: single-skill-at-root upstream repos (scamai/design-system) ───

def _make_single_skill_repo(path: Path) -> None:
    """A repo that IS one skill: SKILL.md at root + assets, no skills/ dir."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text("---\nname: design-system\ndescription: d\n---\nrules\n")
    (path / "tokens.css").write_text(":root { --radius: 0; }\n")
    (path / "components").mkdir()
    (path / "components" / "button.tsx").write_text("export const Button = 1\n")


def test_is_single_skill_repo_true_for_root_skill(tmp_path):
    repo = tmp_path / "design-system"
    _make_single_skill_repo(repo)
    assert ec.is_single_skill_repo(repo) is True


def test_is_single_skill_repo_false_when_container_exists(tmp_path):
    repo = tmp_path / "kit"
    (repo / "skills" / "foo").mkdir(parents=True)
    (repo / "SKILL.md").write_text("---\nname: x\ndescription: d\n---\n")
    assert ec.is_single_skill_repo(repo) is False


def test_upstream_skill_dirs_container_layout(tmp_path):
    repo = tmp_path / "plugin"
    for name in ("bar", "foo"):
        (repo / "skills" / name).mkdir(parents=True)
    (repo / "skills" / ".hidden").mkdir()
    dirs = ec.upstream_skill_dirs(repo)
    assert [d.name for d in dirs] == ["bar", "foo"]


def test_upstream_skill_dirs_single_skill_repo_yields_root(tmp_path):
    repo = tmp_path / "design-system"
    _make_single_skill_repo(repo)
    dirs = ec.upstream_skill_dirs(repo)
    assert dirs == [repo]
    # dir name doubles as the skill name (cache dirs are named by upstream id)
    assert dirs[0].name == "design-system"


def test_upstream_skill_dirs_empty_when_neither_shape(tmp_path):
    repo = tmp_path / "not-a-skill-repo"
    (repo / "src").mkdir(parents=True)
    assert ec.upstream_skill_dirs(repo) == []


def test_tree_hash_skips_git_internals(tmp_path):
    root = tmp_path / "repo"
    _make_single_skill_repo(root)
    (root / ".git" / "objects").mkdir(parents=True)
    (root / ".git" / "config").write_text("[core]\n")
    (root / ".git" / "objects" / "aa").write_text("blob\n")
    th = ec.tree_hash(root)
    assert "SKILL.md" in th
    assert "components/button.tsx" in th
    assert not any(k == ".git" or k.startswith(".git/") for k in th)


def test_equip_sync_diff_only_handles_single_skill_upstream(tmp_path, monkeypatch, capsys):
    """End-to-end: /equip sync --diff-only against a Layout E upstream lists
    the repo itself as one skill instead of erroring 'no skills dir'."""
    import equip_sync as esync

    project = tmp_path / "proj"
    (project / "configs" / "skills").mkdir(parents=True)
    ec.ensure_equipment_dir(project)
    upstreams = [ec.Upstream(id="design-system", repo="scamai/design-system")]
    ec.save_upstreams(project, upstreams)

    # Pre-seed the cache as a git repo so clone_or_update_cache is bypassed
    cache = ec.cache_dir(project) / "design-system"
    _make_single_skill_repo(cache)
    _init_repo(cache)
    _git(["add", "-A"], cwd=cache)
    _git(["commit", "-q", "-m", "init"], cwd=cache)

    monkeypatch.setattr(
        sys, "argv",
        ["equip_sync.py", "--project", str(project), "--upstream", "design-system", "--diff-only"],
    )
    rc = esync.main()
    assert rc == 0
    out = capsys.readouterr().out
    # The repo root shows up as ONE new skill named after the upstream id
    assert "NEW" in out and "design-system" in out
    assert "no skills dir" not in out
