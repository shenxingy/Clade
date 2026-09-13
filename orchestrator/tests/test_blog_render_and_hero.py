"""The two remaining scripts Gate 2 depends on, neither of which existed.

`blog_render.py` produces the .html and .pdf the contract says "cannot diverge
by construction" from the .md — a construction that was not running.
`generate_hero.py` implements the hero ladder, whose only keyless rung is the
one that must always work.

The self-tests inside each script cover their internals. These cover the CLI,
the files that land on disk, and the failure paths — including the ones that
must fail LOUDLY rather than substituting something.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "configs" / "scripts" / "blog"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name[:-3], SCRIPTS / name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name[:-3]] = module
    spec.loader.exec_module(module)
    return module


render = _load("blog_render.py")
hero = _load("generate_hero.py")

_SRC = (
    "---\ntitle: A Real Post\nauthor: Someone\ndate: 2026-09-12\n"
    "description: What it is about.\ncanonical: https://e.test/a-real-post\n---\n\n"
    "# A Real Post\n\nAn opening with **bold**, `code`, and a [link](https://e.test/x).\n\n"
    "## A section\n\n- one\n- two\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n"
    "```\nnot *markdown* here\n```\n\n> quoted\n"
)


# ─── blog_render ───

def test_html_is_written_without_a_pdf_engine(tmp_path):
    (tmp_path / "post.md").write_text(_SRC, encoding="utf-8")
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / "blog_render.py"), "--md", str(tmp_path / "post.md"),
         "--out-dir", str(tmp_path), "--no-pdf"],
        capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stderr
    assert (tmp_path / "post.html").is_file()


def test_a_missing_pdf_engine_fails_loudly_and_substitutes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "_installed", lambda _n: False)
    ok, detail = render.render_pdf(tmp_path / "nope.html", tmp_path / "out.pdf")
    if ok:
        pytest.skip("a chromium binary is on this machine; the negative path needs none")
    assert not (tmp_path / "out.pdf").exists(), "a PDF appeared from nowhere"
    assert detail


def test_find_spec_on_an_absent_parent_package_does_not_raise():
    # find_spec("patchright.sync_api") RAISES when patchright is absent; it does
    # not return None. The degradation path tracebacked out of itself.
    assert render._installed("definitely_not_installed_xyz.sub_module") is False


def test_the_page_carries_everything_gate3_and_gate5_look_for(tmp_path):
    meta, body = render.split_frontmatter(_SRC)
    html = render.build_page(meta, render.to_html(body)[0], "post", "hero.png")
    for anchor in ("<!DOCTYPE html>", '<link rel="canonical"', 'property="og:image"',
                   'name="twitter:card"', "prefers-color-scheme",
                   'type="application/ld+json"', '<img src="hero.png"'):
        assert anchor in html, f"missing {anchor}"


def test_the_json_ld_is_a_complete_blogposting(tmp_path):
    meta, body = render.split_frontmatter(_SRC)
    html = render.build_page(meta, render.to_html(body)[0], "post", "hero.png")
    ld = json.loads(re.search(r'application/ld\+json">(.*?)</script>', html, re.S).group(1))
    assert ld["@type"] == "BlogPosting"
    for field in ("headline", "image", "datePublished", "author", "wordCount"):
        assert ld.get(field), f"missing {field}"


def test_emphasis_is_not_applied_inside_a_code_fence():
    html, _ = render.to_html("```\nnot *markdown* here\n```\n")
    assert "<em>" not in html


def test_html_in_the_source_is_escaped_not_executed():
    html, _ = render.to_html("A paragraph with <script>alert(1)</script> in it.\n")
    assert "<script>alert" not in html


def test_an_unsupported_construct_warns_rather_than_mangling(monkeypatch):
    monkeypatch.setattr(render, "_installed", lambda n: False if n == "markdown" else True)
    _html, warnings = render.to_html("[ref]: https://e.test\n\nSee [ref].\n")
    assert warnings and "markdown" in warnings[0]


def test_frontmatter_lists_are_parsed():
    meta, _ = render.split_frontmatter("---\ntags: [a, b, c]\n---\nbody\n")
    assert meta["tags"] == ["a", "b", "c"]


def test_a_missing_source_is_an_error_not_a_traceback(tmp_path):
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / "blog_render.py"), "--md", str(tmp_path / "no.md")],
        capture_output=True, text=True, check=False)
    assert out.returncode == 2 and "Traceback" not in out.stderr


# ─── generate_hero ───

def test_the_query_drops_headline_filler():
    query = hero.build_query("What Is the Ultimate Guide to Your Database?", ["cloud"])
    assert "cloud" in query
    assert "database" in query
    for filler in ("what", "the", "ultimate", "guide", "your"):
        assert filler not in query.split()


def test_relaxation_widens_until_something_matches(monkeypatch):
    # Measured against the live API: 4 terms returned 0, 3 returned 1, 2 returned
    # 27. A single-shot query is a way to reach rung 5 with a working network.
    tried = []

    def fake(query, limit=20):
        tried.append(query)
        return [{"title": "x"}] if len(query.split()) <= 2 else []

    monkeypatch.setattr(hero, "openverse_search", fake)
    results, used = hero.search_with_relaxation(["a", "b", "c", "d"], log=lambda _m: None)
    assert results and used == "a b"
    assert tried[0] == "a b c d", "the most specific query must be tried first"


def test_relaxation_gives_up_rather_than_returning_junk(monkeypatch):
    monkeypatch.setattr(hero, "openverse_search", lambda q, limit=20: [])
    results, _ = hero.search_with_relaxation(["a", "b"], log=lambda _m: None)
    assert results == []


def test_wide_images_outrank_tall_ones():
    wide = {"title": "server", "width": 1200, "height": 630, "source": "flickr",
            "license": "by", "tags": []}
    assert hero.score(wide, {"server"}) > hero.score({**wide, "width": 600, "height": 1200},
                                                     {"server"})


def test_source_authority_matches_the_contract_ranking():
    order = ["unsplash", "pexels", "wikimedia", "pixabay"]
    values = [hero.SOURCE_AUTHORITY[s] for s in order]
    assert values == sorted(values, reverse=True)


@pytest.mark.parametrize("licence", ["nc", "by-nc", "by-nd", "by-nc-sa", "by-nc-nd"])
def test_non_commercial_and_no_derivatives_licences_are_refused(licence):
    # A blog hero is a commercial use for most publishers. This is a licence
    # violation, not a style preference.
    assert licence not in hero.SAFE_LICENSES


def test_attribution_carries_every_field_the_licence_requires():
    text = hero.credit_text({
        "title": "T", "creator": "C", "creator_url": "https://e.test/c",
        "license": "by-sa", "license_version": "4.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "foreign_landing_url": "https://e.test/x", "id": "abc"})
    for anchor in ("T", "C", "https://e.test/c", "CC BY-SA 4.0",
                   "creativecommons.org", "https://e.test/x", "abc"):
        assert anchor in text, f"attribution missing {anchor}"


def test_attribution_survives_a_result_with_missing_fields():
    # Openverse rows are third-party data; a None creator must not crash the run
    # or silently produce an attribution-free image.
    text = hero.credit_text({"id": "x"})
    assert "Unknown" in text and "licence CONDITION" in text


def test_the_block_message_names_the_keyless_rung():
    assert "no key" in hero.BLOCK_MESSAGE.lower()
    for path in ("Banana MCP", "GOOGLE_AI_API_KEY", "hero.png"):
        assert path in hero.BLOCK_MESSAGE


def test_a_non_image_response_is_refused(tmp_path, monkeypatch):
    class _Resp:
        headers = {"Content-Type": "text/html"}

        def read(self):
            return b"<html>not an image</html>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(hero.urllib.request, "urlopen", lambda *a, **k: _Resp())
    with pytest.raises(ValueError, match="non-image"):
        hero.download("https://e.test/page", tmp_path / "hero")


def test_the_canonical_openverse_host_is_used():
    # api.openverse.engineering 301s here; following it every call is a needless
    # dependency on the redirect staying up.
    assert hero.OPENVERSE.startswith("https://api.openverse.org/")
