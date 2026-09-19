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


# ─── Inherited contrast across an inversion band ────────────────────────────
#
# Regression corpus for a real published artifact where white headline text
# landed on a light-grey plate at 1.17:1 while every declared colour+background
# pair passed. The colour was inherited from an inverting ancestor; the plate
# came from the un-inverted palette. Declaration-pairing cannot see it.

_INVERSION_PAGE = """<html><head><style>
  :root { --bg:#ffffff; --fg:#08080a; --muted:#ededf0; }
  @media(prefers-color-scheme:dark){ :root{ --bg:#050506; --fg:#ffffff; --muted:#111114; } }
  body { background:var(--bg); color:var(--fg); }
  .thesis { background:var(--fg); color:var(--bg); }
  blockquote { background:var(--muted); }
</style></head><body><section class="thesis">
  <blockquote>headline that collides</blockquote>
</section></body></html>"""


def _run_html(tmp_path, html, name="page.html"):
    page = tmp_path / name
    page.write_text(html)
    report = design_lint.Report(lane="html")
    design_lint.lint_html(page, report, name)
    return report


def _finding(report, check):
    return next(f for f in report.findings if f.check == check)


def test_inversion_band_descendant_background_is_caught(tmp_path):
    report = _run_html(tmp_path, _INVERSION_PAGE)
    inherited = _finding(report, "html.contrast.inherited")
    assert inherited.severity == "FAIL"
    assert inherited.measured is not None and inherited.measured < 1.3
    assert "blockquote" in inherited.detail


def test_declared_pair_check_alone_never_sees_the_inversion_collision(tmp_path):
    # The point of the new check: the old one is not merely quieter here, it is
    # structurally blind, because `blockquote` declares no `color` at all.
    report = _run_html(tmp_path, _INVERSION_PAGE)
    declared = _finding(report, "html.contrast")
    assert declared.severity != "FAIL"


def test_worst_theme_wins_so_a_dark_only_failure_is_not_hidden(tmp_path):
    # Light resolves to near-black on white (fine); dark collides. Collapsing
    # the two palettes onto whichever is declared last would report a pass.
    html = """<html><head><style>
      :root { --bg:#ffffff; --fg:#111111; --plate:#f2f2f2; }
      @media(prefers-color-scheme:dark){ :root{ --bg:#101010; --fg:#141414; --plate:#101010; } }
      body { background:var(--bg); color:var(--fg); }
      .card { background:var(--plate); }
    </style></head><body><div class="card">text</div></body></html>"""
    inherited = _finding(_run_html(tmp_path, html), "html.contrast.inherited")
    assert inherited.severity == "FAIL"
    assert "[dark]" in inherited.detail


def test_a_correctly_inverted_band_passes(tmp_path):
    # Same structure, but the plate is expressed in the band's own polarity.
    html = _INVERSION_PAGE.replace("blockquote { background:var(--muted); }",
                                   "blockquote { background:var(--fg); color:var(--bg); }")
    inherited = _finding(_run_html(tmp_path, html), "html.contrast.inherited")
    assert inherited.severity == "PASS"


def test_descendant_selectors_are_matched_against_the_tree(tmp_path):
    html = """<html><head><style>
      body { color:#ffffff; background:#000000; }
      .band p { background:#f0f0f0; }
    </style></head><body><div class="band"><p>white on near-white</p></div></body></html>"""
    inherited = _finding(_run_html(tmp_path, html), "html.contrast.inherited")
    assert inherited.severity == "FAIL"


def test_unsupported_selectors_are_reported_not_silently_dropped(tmp_path):
    html = """<html><head><style>
      body { color:#000000; background:#ffffff; }
      .a > .b { background:#ffffff; }
      li:nth-child(2) { background:#ffffff; }
    </style></head><body><p>ok</p></body></html>"""
    inherited = _finding(_run_html(tmp_path, html), "html.contrast.inherited")
    assert "unsupported selector" in inherited.detail


def test_text_over_a_transparent_element_uses_the_nearest_opaque_backdrop(tmp_path):
    html = """<html><head><style>
      body { color:#ffffff; background:#eeeeee; }
      .shell { background:transparent; }
    </style></head><body><div class="shell"><span>white on light grey</span></div></body></html>"""
    inherited = _finding(_run_html(tmp_path, html), "html.contrast.inherited")
    assert inherited.severity == "FAIL"


def test_split_media_separates_the_two_palettes(tmp_path):
    base, dark = design_lint._split_media(
        ":root{--x:#fff}@media(prefers-color-scheme:dark){:root{--x:#000}}.a{color:red}")
    assert "#fff" in base and "#000" not in base
    assert "#000" in dark
    assert ".a{color:red}" in base


def test_page_with_no_elements_skips_rather_than_passing(tmp_path):
    inherited = _finding(_run_html(tmp_path, ""), "html.contrast.inherited")
    assert inherited.severity == "SKIP"


def test_band_scoped_token_override_is_honoured(tmp_path):
    # The canonical fix for the inversion collision is to re-point the token
    # for the band's subtree. A checker that resolves every var() against
    # :root would still report FAIL and make the real fix unverifiable.
    # The override must be polarity-relative (var(--fg), not a fixed hex) —
    # a literal grey that works in light mode collides again in dark mode.
    html = _INVERSION_PAGE.replace(
        ".thesis { background:var(--fg); color:var(--bg); }",
        ".thesis { background:var(--fg); color:var(--bg); --muted:var(--fg); }")
    inherited = _finding(_run_html(tmp_path, html), "html.contrast.inherited")
    assert inherited.severity == "PASS"


def test_a_fixed_hex_override_that_only_suits_light_mode_still_fails(tmp_path):
    html = _INVERSION_PAGE.replace(
        ".thesis { background:var(--fg); color:var(--bg); }",
        ".thesis { background:var(--fg); color:var(--bg); --muted:#3a3a3a; }")
    inherited = _finding(_run_html(tmp_path, html), "html.contrast.inherited")
    assert inherited.severity == "FAIL"
    assert "[dark]" in inherited.detail


# ─── parse_color must refuse what it cannot composite ───────────────────────


@pytest.mark.parametrize("value", [
    "color-mix(in srgb,#ffffff 12%,transparent)",   # scraping #ffffff inverts the verdict
    "rgba(255,255,255,0.12)",                       # translucent veil, not a plate
    "rgb(255 255 255 / 0.2)",                       # space-separated alpha
    "#ffffff80",                                    # 8-digit hex carries alpha
    "hsl(0 0% 100%)",                               # unmodelled colour space
    "oklch(0.9 0.1 200)",
])
def test_parse_color_refuses_values_it_cannot_composite(value):
    assert design_lint.parse_color(value) is None


@pytest.mark.parametrize("value,expected", [
    ("#08080a", (8, 8, 10)),
    ("#fff", (255, 255, 255)),
    ("rgb(12,34,56)", (12, 34, 56)),
    ("rgba(12,34,56,1)", (12, 34, 56)),
    ("white", (255, 255, 255)),
])
def test_parse_color_still_resolves_opaque_values(value, expected):
    assert design_lint.parse_color(value) == expected


def test_translucent_backdrop_falls_through_to_the_opaque_ancestor(tmp_path):
    # A 10%-white veil over black is still black-ish; treating it as solid
    # white would flip a passing page to FAIL.
    html = """<html><head><style>
      body { color:#ffffff; background:#000000; }
      .veil { background:rgba(255,255,255,0.1); }
    </style></head><body><div class="veil">white on near-black</div></body></html>"""
    inherited = _finding(_run_html(tmp_path, html), "html.contrast.inherited")
    assert inherited.severity == "PASS"


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


# ─── Source lane: design-rules.md decomposed into static checks ─────────────
#
# Each fixture plants exactly the violation its test names, and the clean
# fixture at the end plants none — so a regression that stops a check firing
# and a regression that makes it fire on good code are both caught. The
# thresholds under test are the essay's numbers (4-px grid, 4–6 sizes, 3–4
# weights, ≤2 families, 400 ms, 16 px), not measured fire rates.


def _run_source(tmp_path, files: dict[str, str]):
    for name, body in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
    report = design_lint.Report(lane="source")
    paths = design_lint.collect(tmp_path, "source")
    design_lint.lint_source(paths, tmp_path, report)
    return report


def _maybe(report, check):
    return next((f for f in report.findings if f.check == check), None)


_GUARD = "@media (prefers-reduced-motion: reduce) { * { animation: none; transition: none; } }\n"


def test_off_grid_spacing_is_named_with_file_and_line(tmp_path):
    report = _run_source(tmp_path, {"a.css": ".x { padding: 13px 27px; }\n.y { gap: 16px; }\n"})
    grid = _finding(report, "source.spacing.grid")
    assert grid.severity == "WARN"
    assert grid.measured == 1 and "a.css:1" in grid.detail and "13px 27px" in grid.detail


def test_on_grid_spacing_passes_and_hairline_nudges_are_ignored(tmp_path):
    report = _run_source(tmp_path, {"a.css": ".x { padding: 8px 16px; margin-top: 1px; gap: 24px; }\n"})
    assert _finding(report, "source.spacing.grid").severity == "PASS"


def test_spacing_resolves_tokens_and_rem_before_judging(tmp_path):
    # 0.8125rem is 13px; a var() to it must be seen through, not skipped.
    report = _run_source(tmp_path, {
        "tokens.css": ":root { --space-odd: 0.8125rem; }\n",
        "b.css": ".x { padding: var(--space-odd); }\n",
    })
    grid = _finding(report, "source.spacing.grid")
    assert grid.severity == "WARN" and "b.css:1" in grid.detail


def test_tailwind_arbitrary_spacing_counts_as_off_grid(tmp_path):
    report = _run_source(tmp_path, {"Card.tsx": '<div className="p-[13px] mt-4" />\n'})
    grid = _finding(report, "source.spacing.grid")
    assert grid.severity == "WARN" and "p-[13px]" in grid.detail


def test_react_style_object_values_are_read_one_property_at_a_time(tmp_path):
    # `{ paddingTop: '13px', color: '#fff' }` on one line: the spacing check
    # must see 13px and the colour check must still see #fff.
    report = _run_source(tmp_path, {
        "Box.tsx": "const s = { paddingTop: '13px', color: '#fff' };\n"})
    assert _finding(report, "source.spacing.grid").severity == "WARN"
    colour = _finding(report, "source.color.literal")
    assert colour.severity == "WARN" and "color: #fff" in colour.detail


def test_seven_font_sizes_warn_with_rem_normalised_to_px(tmp_path):
    css = "".join(f".s{i} {{ font-size: {v}; }}\n"
                  for i, v in enumerate(["12px", "14px", "1rem", "18px", "20px", "24px", "2rem"]))
    sizes = _finding(_run_source(tmp_path, {"a.css": css}), "source.type.sizes")
    assert sizes.severity == "WARN" and sizes.measured == 7 and "32px" in sizes.detail


def test_six_font_sizes_pass_and_tailwind_steps_count_as_sizes(tmp_path):
    report = _run_source(tmp_path, {
        "a.css": ".s { font-size: 13px; } .t { font-size: 40px; }\n",
        "A.tsx": '<p className="text-sm text-lg text-2xl text-[56px]" />\n'})
    sizes = _finding(report, "source.type.sizes")
    assert sizes.severity == "PASS" and sizes.measured == 6


def test_five_weights_and_three_families_warn_generic_families_ignored(tmp_path):
    css = ("".join(f".w{w} {{ font-weight: {w}; }}\n" for w in (300, 400, 500, 600, 700))
           + '.a { font-family: "Inter", sans-serif; }\n'
           + '.b { font-family: Georgia, serif; }\n'
           + '.c { font-family: "JetBrains Mono", monospace; }\n'
           + '.d { font-family: system-ui; }\n')
    report = _run_source(tmp_path, {"a.css": css})
    assert _finding(report, "source.type.weights").measured == 5
    families = _finding(report, "source.type.families")
    assert families.severity == "WARN" and families.measured == 3


def test_radius_variants_collapse_to_one_pill_and_five_values_warn(tmp_path):
    css = ".a { border-radius: 4px; } .b { border-radius: 6px; } .c { border-radius: 8px; }\n" \
          ".d { border-radius: 12px; } .e { border-radius: 9999px; } .f { border-radius: 50%; }\n"
    radius = _finding(_run_source(tmp_path, {"a.css": css}), "source.geometry.radius")
    assert radius.severity == "WARN" and radius.measured == 5 and "pill" in radius.detail


def test_four_shadows_warn_three_pass(tmp_path):
    shadows = ["0 1px 2px rgba(0,0,0,.1)", "0 2px 8px rgba(0,0,0,.1)",
               "0 8px 24px rgba(0,0,0,.2)", "0 0 0 1px #000"]
    css = "".join(f".s{i} {{ box-shadow: {s}; }}\n" for i, s in enumerate(shadows))
    assert _finding(_run_source(tmp_path, {"a.css": css}), "source.geometry.shadow").measured == 4
    css3 = "".join(f".s{i} {{ box-shadow: {s}; }}\n" for i, s in enumerate(shadows[:3]))
    assert _finding(_run_source(tmp_path, {"a.css": css3}), "source.geometry.shadow").severity == "PASS"


def test_durations_over_400ms_warn_but_a_loader_spin_is_exempt(tmp_path):
    css = (".panel { transition: opacity 800ms; }\n"
           ".spinner { animation: spin 1s linear infinite; }\n"
           "@keyframes spin { to { transform: rotate(360deg); } }\n" + _GUARD)
    report = _run_source(tmp_path, {"a.css": css})
    duration = _finding(report, "source.motion.duration")
    assert duration.severity == "WARN" and duration.measured == 1 and "800ms" in duration.detail
    assert _finding(report, "source.motion.infinite").severity == "PASS"


def test_ambient_infinite_animation_warns(tmp_path):
    css = ".orb { animation: float 6s ease-in-out infinite; }\n" + _GUARD
    infinite = _finding(_run_source(tmp_path, {"a.css": css}), "source.motion.infinite")
    assert infinite.severity == "WARN" and "float" in infinite.detail


def test_tailwind_animate_bounce_is_ambient_but_custom_animate_is_not_judged(tmp_path):
    report = _run_source(tmp_path, {
        "A.tsx": '<div className="animate-bounce" /><div className="animate-in" />\n' + _GUARD})
    infinite = _finding(report, "source.motion.infinite")
    assert infinite.severity == "WARN" and infinite.measured == 1


def test_layout_transitions_and_bare_shorthand_warn_transform_passes(tmp_path):
    bad = ".a { transition: width 200ms; } .b { transition: .2s; } .c { transition: all 150ms; }\n" + _GUARD
    prop = _finding(_run_source(tmp_path, {"a.css": bad}), "source.motion.property")
    assert prop.severity == "WARN" and prop.measured == 3
    good = ".a { transition: transform 150ms, opacity 150ms; }\n" + _GUARD
    assert _finding(_run_source(tmp_path, {"a.css": good}), "source.motion.property").severity == "PASS"


def test_tailwind_transition_all_warns(tmp_path):
    report = _run_source(tmp_path, {"A.tsx": '<a className="transition-all duration-200" />\n' + _GUARD})
    assert _finding(report, "source.motion.property").severity == "WARN"


def test_keyframe_translating_past_16px_warns_8px_passes(tmp_path):
    big = "@keyframes rise { from { transform: translateY(40px); } to { transform: none; } }\n.a{animation: rise 200ms}\n" + _GUARD
    move = _finding(_run_source(tmp_path, {"a.css": big}), "source.motion.displacement")
    assert move.severity == "WARN" and "rise" in move.detail and "40px" in move.detail
    small = big.replace("40px", "8px")
    assert _finding(_run_source(tmp_path, {"a.css": small}), "source.motion.displacement").severity == "PASS"


def test_motion_without_reduced_motion_guard_fails_anywhere_in_the_tree_passes(tmp_path):
    css = ".a { transition: opacity 150ms; }\n"
    assert _finding(_run_source(tmp_path, {"a.css": css}), "source.motion.reduced").severity == "FAIL"
    report = _run_source(tmp_path, {"a.css": css, "globals.css": _GUARD})
    assert _finding(report, "source.motion.reduced").severity == "PASS"


def test_use_reduced_motion_hook_counts_as_a_guard(tmp_path):
    report = _run_source(tmp_path, {
        "A.tsx": 'const r = useReducedMotion();\n<div className="duration-200" />\n'})
    assert _finding(report, "source.motion.reduced").severity == "PASS"


def test_no_motion_at_all_skips_rather_than_passing(tmp_path):
    assert _finding(_run_source(tmp_path, {"a.css": ".a { color: red; }\n"}), "source.motion").severity == "SKIP"


def test_outline_none_without_restore_fails_and_the_removing_rule_is_not_a_restore(tmp_path):
    # `button:focus { outline: none }` mentions `outline` inside a :focus rule —
    # the naive regex counted that as a restore and passed the exact defect.
    css = "button:focus { outline: none; }\n"
    focus = _finding(_run_source(tmp_path, {"a.css": css}), "source.focus")
    assert focus.severity == "FAIL" and "a.css:1" in focus.detail


def test_outline_none_with_focus_visible_restore_passes(tmp_path):
    css = "button:focus { outline: none; }\nbutton:focus-visible { box-shadow: 0 0 0 2px #000; }\n"
    assert _finding(_run_source(tmp_path, {"a.css": css}), "source.focus").severity == "PASS"


def test_tailwind_outline_none_needs_a_focus_visible_ring(tmp_path):
    bare = {"A.tsx": '<button className="outline-none" />\n'}
    assert _finding(_run_source(tmp_path, bare), "source.focus").severity == "FAIL"
    ringed = {"A.tsx": '<button className="outline-none focus-visible:ring-2" />\n'}
    assert _finding(_run_source(tmp_path, ringed), "source.focus").severity == "PASS"


def test_html_lane_shares_the_focus_restore_fix(tmp_path):
    html = "<html><head><style>button:focus { outline: none; }</style></head><body><button>x</button></body></html>"
    assert _finding(_run_html(tmp_path, html), "html.focus").severity == "FAIL"


def test_colour_literals_in_components_warn_but_token_definitions_do_not(tmp_path):
    tokens = {"tokens.css": ":root { --ink: #222222; --bg: rgb(255,255,255); }\n.a { color: var(--ink); }\n"}
    assert _finding(_run_source(tmp_path, tokens), "source.color.literal").severity == "PASS"
    literal = {"Btn.tsx": '<button className="bg-[#3b82f6]" style={{ color: "#fff" }} />\n'}
    colour = _finding(_run_source(tmp_path, literal), "source.color.literal")
    assert colour.severity == "WARN" and colour.measured == 2


def test_shadow_colours_are_not_double_counted_as_literals(tmp_path):
    css = ".a { box-shadow: 0 1px 2px rgba(0,0,0,.1); }\n"
    assert _finding(_run_source(tmp_path, {"a.css": css}), "source.color.literal").severity == "PASS"


def test_marketing_slop_is_named_by_phrase_and_line_specific_copy_passes(tmp_path):
    slop = {"index.html": "<h1>Revolutionize your workflow</h1>\n<p>Get started today. 赋能企业</p>\n"}
    copy = _finding(_run_source(tmp_path, slop), "source.copy.slop")
    assert copy.severity == "WARN" and copy.measured == 3
    assert "index.html:1" in copy.detail and "Revolutionize" in copy.detail and "赋能" in copy.detail
    specific = {"index.html": "<p>Upload a document and receive a tampering report in under 30 seconds.</p>\n"}
    assert _finding(_run_source(tmp_path, specific), "source.copy.slop").severity == "PASS"


def test_copy_in_jsx_text_is_read_and_css_only_trees_skip(tmp_path):
    jsx = {"Hero.tsx": "export const H = () => <h1>Unlock the power of AI</h1>;\n"}
    assert _finding(_run_source(tmp_path / "jsx", jsx), "source.copy.slop").severity == "WARN"
    css_only = _run_source(tmp_path / "css", {"a.css": ".a{}"})
    assert _finding(css_only, "source.copy.slop").severity == "SKIP"


def test_unmeasurable_rules_are_reported_as_a_skip_not_omitted(tmp_path):
    report = _run_source(tmp_path, {"a.css": ".a { padding: 8px; }\n"})
    skip = _finding(report, "source.unmeasured")
    assert skip.severity == "SKIP" and "screenshot" in skip.detail


def test_collect_skips_build_output_and_minified_files(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "node_modules" / "x").mkdir(parents=True)
    (tmp_path / "dist").mkdir()
    (tmp_path / "src" / "a.css").write_text(".a{}")
    (tmp_path / "src" / "b.min.css").write_text(".a{}")
    (tmp_path / "node_modules" / "x" / "c.css").write_text(".a{}")
    (tmp_path / "dist" / "d.css").write_text(".a{}")
    paths = design_lint.collect(tmp_path, "source")
    assert [p.name for p in paths] == ["a.css"]


def test_main_source_exit_code_is_0_on_warn_only_and_1_on_fail(tmp_path, capsys):
    (tmp_path / "a.css").write_text(".a { padding: 13px; }\n")
    assert design_lint.main(["source", str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["lane"] == "source" and not payload["failed"]
    (tmp_path / "b.css").write_text(".b { transition: opacity 100ms; }\n")
    assert design_lint.main(["source", str(tmp_path), "--json"]) == 1


def test_clean_source_tree_raises_no_warn_or_fail(tmp_path):
    # Negative control: a tree obeying every rule must be silent, so a check
    # that starts firing on good code is caught as surely as one that stops.
    clean = {
        "tokens.css": (":root { --ink: #1a1a1a; --bg: #ffffff; --accent: #0a7d3c; "
                       "--space-2: 8px; --space-4: 16px; --radius: 8px; "
                       "--shadow-float: 0 8px 24px rgba(0,0,0,.16); }\n" + _GUARD),
        "app.css": (".card { padding: var(--space-4); border-radius: var(--radius); "
                    "font-size: 16px; font-weight: 400; font-family: \"Inter\", sans-serif; "
                    "transition: transform 160ms, opacity 160ms; }\n"
                    ".card h2 { font-size: 18px; font-weight: 600; margin: 0 0 var(--space-2); }\n"
                    ".menu { box-shadow: var(--shadow-float); }\n"
                    "button:focus { outline: none; }\nbutton:focus-visible { outline: 2px solid var(--accent); }\n"),
        "Page.tsx": ('export const P = () => <main className="p-4 gap-6 text-sm">'
                     "Upload a file and get a report in under 30 seconds.</main>;\n"),
    }
    report = _run_source(tmp_path, clean)
    noisy = [f for f in report.findings if f.severity in ("WARN", "FAIL")]
    assert noisy == [], [f.detail for f in noisy]
    assert _finding(report, "source.spacing.grid").severity == "PASS"
    assert _finding(report, "source.focus").severity == "PASS"
    assert _finding(report, "source.motion.reduced").severity == "PASS"
