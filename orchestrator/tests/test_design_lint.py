"""Tests for configs/scripts/design-lint.py — the rendered-output design floor
validator (WCAG contrast math, CSS custom-property resolution, the text-vs-surface
thinness discriminator, and relative-path finding labels).

design-lint.py has no local imports of sibling files, so it is loaded the same
way configs/scripts/redact.py is in test_redact.py: via spec_from_file_location,
registered in sys.modules BEFORE exec_module so its @dataclass decorators can
resolve the module through cls.__module__. A plain `import design-lint` is not
valid Python syntax (hyphenated filename), which is why this indirection is
needed rather than a sys.path insert + import statement.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_DESIGN_LINT_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "scripts" / "design-lint.py"
)
_spec = importlib.util.spec_from_file_location("clade_design_lint", _DESIGN_LINT_PATH)
assert _spec and _spec.loader
design_lint = importlib.util.module_from_spec(_spec)
sys.modules["clade_design_lint"] = design_lint
_spec.loader.exec_module(design_lint)


# ─── WCAG contrast ratio math (published W3C reference pairs) ──────────────


def test_black_on_white_is_21_to_1():
    # The maximum possible WCAG contrast ratio — canonical reference pair.
    assert design_lint.contrast_ratio((0, 0, 0), (255, 255, 255)) == pytest.approx(21.0, abs=1e-9)


def test_white_on_white_and_black_on_black_are_1_to_1():
    assert design_lint.contrast_ratio((255, 255, 255), (255, 255, 255)) == pytest.approx(1.0)
    assert design_lint.contrast_ratio((0, 0, 0), (0, 0, 0)) == pytest.approx(1.0)


def test_777_gray_on_white_matches_published_reference():
    # #777777 on white is the commonly cited near-miss for WCAG AA text (4.5:1).
    ratio = design_lint.contrast_ratio((0x77, 0x77, 0x77), (255, 255, 255))
    assert ratio == pytest.approx(4.48, abs=0.01)
    assert ratio < design_lint.CONTRAST_TEXT


def test_767676_gray_on_white_matches_wcag_aa_boundary_reference():
    # #767676 on white is W3C's own textbook "just clears AA text" gray.
    ratio = design_lint.contrast_ratio((0x76, 0x76, 0x76), (255, 255, 255))
    assert ratio == pytest.approx(4.54, abs=0.01)
    assert ratio >= design_lint.CONTRAST_TEXT


def test_contrast_ratio_is_symmetric_regardless_of_argument_order():
    a, b = (0x59, 0x59, 0x59), (255, 255, 255)
    assert design_lint.contrast_ratio(a, b) == design_lint.contrast_ratio(b, a)


def test_luminance_of_black_and_white_are_the_relative_luminance_extremes():
    assert design_lint.luminance((0, 0, 0)) == pytest.approx(0.0)
    assert design_lint.luminance((255, 255, 255)) == pytest.approx(1.0)


# ─── CSS custom property resolution (var(), fallbacks, nesting) ────────────


def test_custom_properties_collects_root_declarations():
    css = ":root { --ink: #222222; --bg: #ffffff; }"
    props = design_lint.custom_properties(css)
    assert props["--ink"] == "#222222"
    assert props["--bg"] == "#ffffff"


def test_custom_properties_later_definition_wins_matching_the_cascade():
    css = ":root { --ink: #111111; } .dark { --ink: #eeeeee; }"
    props = design_lint.custom_properties(css)
    assert props["--ink"] == "#eeeeee"


def test_resolve_value_substitutes_a_simple_var_reference():
    props = {"--ink": "#222222"}
    assert design_lint.resolve_value("var(--ink)", props) == "#222222"


def test_resolve_value_uses_the_fallback_when_the_property_is_undefined():
    assert design_lint.resolve_value("var(--missing, #ffffff)", {}) == "#ffffff"


def test_resolve_value_ignores_the_fallback_when_the_property_is_defined():
    props = {"--ink": "#222222"}
    assert design_lint.resolve_value("var(--ink, #ffffff)", props) == "#222222"


def test_resolve_value_resolves_a_nested_var_chain():
    props = {"--a": "var(--b)", "--b": "var(--c)", "--c": "#000000"}
    assert design_lint.resolve_value("var(--a)", props) == "#000000"


def test_resolve_value_circular_reference_terminates_via_the_recursion_cap():
    # --a and --b reference each other; without the depth>8 cutoff this would
    # recurse forever. It must return promptly rather than hang or raise.
    props = {"--a": "var(--b)", "--b": "var(--a)"}
    result = design_lint.resolve_value("var(--a)", props)
    assert isinstance(result, str)


def test_lint_html_resolves_custom_properties_before_measuring_contrast(tmp_path):
    # End-to-end: a declared colour pair that only exists behind var() tokens
    # must still be resolved and scored — a checker that gives up at var(--ink)
    # is blind on exactly the idiom the design skill recommends.
    html = """<html><head><style>
      :root { --ink: #ffffff; --panel: #ffff00; }
      .caption { color: var(--ink); background: var(--panel); }
    </style></head><body><p class="caption">hi</p></body></html>"""
    page = tmp_path / "page.html"
    page.write_text(html)

    report = design_lint.Report(lane="html")
    design_lint.lint_html(page, report, "page.html")

    contrast = next(f for f in report.findings if f.check == "html.contrast")
    expected_ratio = design_lint.contrast_ratio((255, 255, 255), (255, 255, 0))
    assert contrast.measured == pytest.approx(round(expected_ratio, 2), abs=0.01)
    assert contrast.severity == "FAIL"  # white-on-yellow is nowhere near 4.5:1


# ─── Text-vs-surface thinness discriminator ─────────────────────────────────

PIL = pytest.importorskip("PIL", reason="Pillow not installed — render-lane pixel checks are optional")
from PIL import Image  # type: ignore[import-untyped]  # noqa: E402

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)


def _solid_square(size=30, square=20, margin=5):
    """A filled panel: mostly interior pixels, thinness should read low."""
    img = Image.new("RGB", (size, size), WHITE)
    px = img.load()
    for r in range(margin, margin + square):
        for c in range(margin, margin + square):
            px[c, r] = BLACK
    return img


def _narrow_stroke(size=12, width=3, height=8, top=2, left=4):
    """A glyph-stem-like vertical stroke: some interior, mostly boundary."""
    img = Image.new("RGB", (size, size), WHITE)
    px = img.load()
    for r in range(top, top + height):
        for c in range(left, left + width):
            px[c, r] = BLACK
    return img


def _hairline(size=10, row=5, left=2, length=6):
    """A single-pixel-wide line: no interior at any width — anti-alias fringe."""
    img = Image.new("RGB", (size, size), WHITE)
    px = img.load()
    for c in range(left, left + length):
        px[c, row] = BLACK
    return img


def test_thinness_of_a_filled_surface_panel_is_low():
    # 20x20 solid block inside a 30x30 canvas: interior is the inset 18x18
    # region (324 px) out of an area of 400 px -> thinness = 1 - 324/400 = 0.19.
    img = _solid_square()
    thin = design_lint._thinness(img, BLACK)
    assert thin == pytest.approx(0.19, abs=0.01)
    assert thin < design_lint.TEXT_THINNESS_MIN  # reads as surface, not text


def test_thinness_of_a_narrow_stroke_falls_in_the_text_like_range():
    # 3px-wide, 8-row stroke: only the centre column, rows 2..7, is interior
    # (6 px) out of an area of 24 px -> thinness = 1 - 6/24 = 0.75.
    img = _narrow_stroke()
    thin = design_lint._thinness(img, BLACK)
    assert thin == pytest.approx(0.75, abs=0.01)
    assert design_lint.TEXT_THINNESS_MIN <= thin < design_lint.TEXT_THINNESS_MAX


def test_thinness_of_a_single_pixel_hairline_is_maximal():
    # A genuinely 1px-wide run has zero interior pixels under the 3x3 min
    # filter at any position -> thinness = 1.0, which the module deliberately
    # excludes as anti-aliasing fringe rather than treating it as text.
    img = _hairline()
    thin = design_lint._thinness(img, BLACK)
    assert thin == pytest.approx(1.0)
    assert not (design_lint.TEXT_THINNESS_MIN <= thin < design_lint.TEXT_THINNESS_MAX)


def test_thinness_of_absent_colour_is_zero():
    img = Image.new("RGB", (10, 10), WHITE)
    assert design_lint._thinness(img, BLACK) == 0.0


def test_local_backdrop_resolves_the_surface_directly_behind_the_colour():
    # A white caption sitting on a yellow panel, both on a magenta page. The
    # backdrop for the white pixels must resolve to yellow (what they actually
    # sit on), not magenta (the page's dominant colour) — the exact confusion
    # a global-dominant-colour measurement would make.
    magenta = (255, 0, 255)
    yellow = (255, 255, 0)
    img = Image.new("RGB", (20, 20), magenta)
    px = img.load()
    for r in range(4, 16):
        for c in range(4, 16):
            px[c, r] = yellow
    for r in range(8, 12):
        for c in range(8, 12):
            px[c, r] = WHITE
    backdrop = design_lint._local_backdrop(img, WHITE)
    assert backdrop == yellow


# ─── Relative-path finding labels ───────────────────────────────────────────


def test_findings_are_labelled_by_path_relative_to_the_scan_root_not_basename(tmp_path, capsys):
    # Regression for the basename-collision bug: many artifact pages share the
    # name index.html, so a checker that labels findings by basename silently
    # collapses distinct pages into one target and corrupts every aggregate.
    root = tmp_path / "artifacts"
    (root / "campaign-a").mkdir(parents=True)
    (root / "campaign-b" / "nested").mkdir(parents=True)
    (root / "campaign-a" / "index.html").write_text(
        '<html><body><img src="x.png"></body></html>'
    )
    (root / "campaign-b" / "nested" / "index.html").write_text(
        '<html><body><img src="y.png"></body></html>'
    )

    exit_code = design_lint.main(["html", str(root), "--json"])
    assert exit_code == 1

    payload = json.loads(capsys.readouterr().out)
    alt_findings = [f for f in payload["findings"] if f["check"] == "html.alt"]
    targets = {f["target"] for f in alt_findings}

    assert targets == {"campaign-a/index.html", "campaign-b/nested/index.html"}
    assert "index.html" not in targets


def test_single_file_target_is_labelled_by_its_filename(tmp_path, capsys):
    page = tmp_path / "solo.html"
    page.write_text('<html><body><img src="z.png"></body></html>')

    design_lint.main(["html", str(page), "--json"])

    payload = json.loads(capsys.readouterr().out)
    targets = {f["target"] for f in payload["findings"]}
    assert targets == {"solo.html"}
