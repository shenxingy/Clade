"""Does the delivery contract describe something that exists?

`blog-delivery-contract.md:151` names this file as "coherence test that asserts
this contract" — and it did not exist, alongside the five scripts the contract
specified and the reviewer agent it made mandatory. A contract nothing checks is
a wish, and this one had been describing infrastructure that was never built for
a full release line while reading as though it were shipped.

So: every script the contract names must exist and run. Every agent it makes
mandatory must exist. Every gate must have an implementation. Every threshold
quoted in prose must equal the constant the code uses.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CONTRACT = REPO / "configs" / "skills" / "blog" / "references" / "blog-delivery-contract.md"
SCRIPTS = REPO / "configs" / "scripts" / "blog"
AGENTS = REPO / "configs" / "agents"


def _text() -> str:
    return CONTRACT.read_text(encoding="utf-8", errors="replace")


def _load(name: str):
    path = SCRIPTS / name
    spec = importlib.util.spec_from_file_location(name[:-3], path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name[:-3]] = module
    spec.loader.exec_module(module)
    return module


def test_the_contract_itself_exists():
    assert CONTRACT.is_file()


@pytest.mark.parametrize("script", ["blog_preflight.py", "lint_prose.py",
                                    "cognitive_load.py", "analyze_blog.py",
                                    "blog_render.py", "generate_hero.py"])
def test_every_script_the_contract_names_exists(script):
    assert (SCRIPTS / script).is_file(), f"{script} is named by the contract"


@pytest.mark.parametrize("script", ["blog_preflight.py", "lint_prose.py",
                                    "cognitive_load.py", "blog_render.py",
                                    "generate_hero.py"])
def test_every_named_script_self_tests_clean(script):
    out = subprocess.run([sys.executable, str(SCRIPTS / script), "--self-test"],
                         capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stdout + out.stderr


def test_no_path_the_contract_names_is_a_phantom():
    # The defect class this file exists for. Every `scripts/…` or `agents/…`
    # path in the contract must resolve somewhere real.
    # A path cited AS a phantom (the corrected precedent) is not a claim.
    body = re.sub(r"^> .*$", "", _text(), flags=re.M)
    missing = []
    for ref in set(re.findall(r"`(?:~/\.claude/)?(?:configs/)?"
                              r"((?:scripts|agents|tests)/[\w./-]+\.(?:py|sh|md))`", body)):
        candidates = [REPO / ref, REPO / "configs" / ref,
                      REPO / "configs" / "scripts" / "blog" / Path(ref).name,
                      REPO / "orchestrator" / "tests" / Path(ref).name,
                      REPO / "orchestrator" / ref,
                      REPO / "configs" / "skills" / "blog" / ref]
        if not any(c.exists() for c in candidates):
            missing.append(ref)
    assert not missing, f"the contract names paths that do not exist: {missing}"


def test_the_mandatory_reviewer_agent_exists():
    # Gate 1 blocks without it, so its absence would make every run impossible.
    assert (AGENTS / "blog-reviewer.md").is_file()


@pytest.mark.parametrize("agent", ["blog-researcher", "blog-writer", "blog-seo",
                                   "blog-translator"])
def test_every_optional_agent_the_contract_lists_exists(agent):
    # Listed as optional in Gate 1, but "optional" means the run degrades, not
    # that the file may be fiction. /blog translate spawns blog-translator.
    assert (AGENTS / f"{agent}.md").is_file()


def test_gate1_agent_list_matches_the_contract():
    preflight = _load("blog_preflight.py")
    declared = set(re.findall(r"`(blog-[a-z]+)`", _text()))
    coded = set(preflight.MANDATORY_AGENTS) | set(preflight.OPTIONAL_AGENTS)
    assert declared <= coded | {"blog-analyze", "blog-rewrite", "blog-write",
                                "blog-flow", "blog-discourse", "blog-translate"}, \
        f"the contract names agents Gate 1 never probes: {declared - coded}"


def test_every_gate_in_the_contract_has_an_implementation():
    preflight = _load("blog_preflight.py")
    headings = re.findall(r"^## Gate (\d+):\s*(.+?)\s*$", _text(), re.M)
    assert headings, "the contract declares no gates"
    for number, _name in headings:
        assert int(number) in preflight.GATES, f"Gate {number} has no implementation"
    assert len(preflight.GATES) == len(headings), \
        "blog_preflight implements a different number of gates than the contract declares"


def test_the_blocking_line_format_is_what_gate4_parses():
    # The contract gives the exact two forms. If the parser and the prose ever
    # disagree, a blocked draft ships.
    preflight = _load("blog_preflight.py")
    for line in re.findall(r"^BLOCKING: .+$", _text(), re.M):
        assert preflight._BLOCKING.search(line), f"gate 4 cannot parse {line!r}"


def test_gate4_blocks_when_the_reviewer_says_true(tmp_path):
    preflight = _load("blog_preflight.py")
    (tmp_path / "review.md").write_text("BLOCKING: true (Overall 87/100)\n", encoding="utf-8")
    assert preflight.gate4(tmp_path)["status"] == "block"


def test_gate4_blocks_when_the_reviewer_never_ran(tmp_path):
    # "The user is NEVER the first reviewer; the gates are."
    preflight = _load("blog_preflight.py")
    assert preflight.gate4(tmp_path)["status"] == "block"


def test_gate2_requires_exactly_the_four_artifacts_the_contract_lists(tmp_path):
    preflight = _load("blog_preflight.py")
    (tmp_path / "p.md").write_text("# T\n", encoding="utf-8")
    (tmp_path / "p.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "p.pdf").write_bytes(b"%PDF")
    assert preflight.gate2(tmp_path)["status"] == "block", "no hero image, yet it passed"
    (tmp_path / "hero.png").write_bytes(b"\x89PNG")
    assert preflight.gate2(tmp_path)["status"] == "pass"


def test_a_gate_that_cannot_run_reports_skip_not_pass(tmp_path):
    # The contract permits Gate 3 to proceed without patchright. It does not
    # permit calling an unrun check a pass, and "nothing ran" must not look
    # like "everything passed".
    preflight = _load("blog_preflight.py")
    good = json.dumps({"@type": "BlogPosting", "headline": "H", "image": "i.png",
                       "datePublished": "2026-01-01", "author": "A"})
    (tmp_path / "p.md").write_text("# T\n", encoding="utf-8")
    (tmp_path / "p.html").write_text(
        f'<script type="application/ld+json">{good}</script>', encoding="utf-8")
    result = preflight.gate3(tmp_path)
    if not (preflight.has_module("patchright") or preflight.has_module("playwright")):
        assert result["status"] == "skip"
        assert "did NOT run" in result["reason"]


def test_the_chain_halts_on_the_first_block(tmp_path):
    # "All gates run sequentially. First failure halts the chain."
    preflight = _load("blog_preflight.py")
    report = preflight.run(tmp_path, tmp_path, None, check_links=False)
    assert report["blocking"]
    assert len(report["gates"]) < len(preflight.GATES)


def test_no_gate_requires_an_api_key(tmp_path, monkeypatch):
    # Standing constraint: a paid API is an accelerator, never a dependency.
    preflight = _load("blog_preflight.py")
    for key in preflight.ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    good = json.dumps({"@type": "BlogPosting", "headline": "H", "image": "hero.png",
                       "datePublished": "2026-01-01", "author": "A"})
    (tmp_path / "p.md").write_text("# T\n", encoding="utf-8")
    (tmp_path / "p.pdf").write_bytes(b"%PDF")
    (tmp_path / "hero.png").write_bytes(b"\x89PNG")
    (tmp_path / "p.html").write_text(
        f'<html><head><link rel="canonical" href="https://e.test/p">'
        f'<meta property="og:image" content="hero.png">'
        f'<script type="application/ld+json">{good}</script></head>'
        f'<body><article><img src="hero.png"> a b c</article></body></html>',
        encoding="utf-8")
    (tmp_path / "review.md").write_text("BLOCKING: false (clear)\n", encoding="utf-8")
    report = preflight.run(tmp_path, tmp_path, None, check_links=False)
    assert not report["blocking"], f"a keyless run was blocked: {report['gates']}"


def test_gate1_records_a_keyless_image_path():
    # Gate 1 blocks on "no image-gen path at all". Openverse needs no key, so
    # that failure mode must not fire merely because no key is configured.
    preflight = _load("blog_preflight.py")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        caps = preflight.gate1(Path(tmp) / "d", REPO)["capabilities"]
    assert caps["image_paths"]["openverse_keyless"] is True


def test_gate1_never_records_a_secret_value(tmp_path, monkeypatch):
    # Assembled rather than written out: the repository's own commit-time secret
    # scanner correctly refuses a diff containing a key-shaped literal, and
    # silencing that gate for a fixture is how a real key eventually rides along.
    sentinel = "sk-" + "fixture" + "-value-must-not-be-persisted"
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", sentinel)
    preflight = _load("blog_preflight.py")
    preflight.gate1(tmp_path, REPO)
    written = (tmp_path / "capabilities.json").read_text(encoding="utf-8")
    assert sentinel not in written
    assert "must-not-be-persisted" not in written
    assert "UNSPLASH_ACCESS_KEY" in written, "the key NAME should be recorded"


def test_wordcount_honesty_is_enforced_at_the_stated_tolerance(tmp_path):
    # "±5%. Catches the 'I claimed 1,715 words but the body is 1,400' defect."
    preflight = _load("blog_preflight.py")
    body = " ".join(["word"] * 100)
    for claimed, expect in ((100, "pass"), (103, "pass"), (200, "block")):
        ld = json.dumps({"@type": "BlogPosting", "headline": "H", "image": "hero.png",
                         "datePublished": "2026-01-01", "author": "A",
                         "wordCount": claimed})
        (tmp_path / "p.md").write_text("# T\n", encoding="utf-8")
        (tmp_path / "hero.png").write_bytes(b"\x89PNG")
        (tmp_path / "p.html").write_text(
            f'<html><head><link rel="canonical" href="https://e.test/p">'
            f'<meta property="og:image" content="hero.png">'
            f'<script type="application/ld+json">{ld}</script></head>'
            f'<body><article><img src="hero.png"> {body}</article></body></html>',
            encoding="utf-8")
        assert preflight.gate5(tmp_path, tmp_path, False)["status"] == expect, \
            f"wordCount {claimed} against 100 actual should {expect}"


def test_the_hero_ladder_has_a_rung_that_needs_no_key():
    # Rungs 1-3 are MCP- or key-gated. If the keyless rung were removed, /blog
    # could not produce a hero at all without a paid account, and Gate 2 makes
    # the hero mandatory — the skill would be unusable rather than degraded.
    hero = _load("generate_hero.py")
    assert "openverse.org" in hero.OPENVERSE
    assert "no key" in hero.BLOCK_MESSAGE.lower()
    for licence in ("nc", "by-nc", "by-nd", "by-nc-sa"):
        assert licence not in hero.SAFE_LICENSES


def test_the_renderer_emits_a_wordcount_gate5_will_accept(tmp_path):
    # The two scripts check each other: the renderer writes the field, Gate 5
    # audits it at ±5%. They disagreed on their first run — the renderer counted
    # the body while the gate measured the whole <article>.
    render = _load("blog_render.py")
    preflight = _load("blog_preflight.py")
    src = ("---\ntitle: A Post\nauthor: P\ndate: 2026-01-01\n"
           "canonical: https://e.test/a\n---\n\n# A Post\n\n"
           + "Some real words in a sentence. " * 40)
    (tmp_path / "a.md").write_text(src, encoding="utf-8")
    (tmp_path / "hero.png").write_bytes(b"\x89PNG")
    (tmp_path / "a.pdf").write_bytes(b"%PDF")
    meta, body = render.split_frontmatter(src)
    body = re.sub(r"^#\s+.*$", "", body, count=1, flags=re.M)
    html, _ = render.to_html(body)
    (tmp_path / "a.html").write_text(
        render.build_page(meta, html, "a", "hero.png"), encoding="utf-8")
    result = preflight.gate5(tmp_path, tmp_path, check_links=False)
    assert result["status"] == "pass", result["reason"]


def test_the_contract_no_longer_claims_a_precedent_that_never_existed():
    # It cited `tests/test_installer_sync.py`, which never existed under any
    # name, as evidence that "the fix is infrastructure, not effort".
    assert "test_installer_sync.py" not in _text() or \
        "never existed" in _text(), \
        "the phantom precedent is cited without the correction"
