"""design_lint_source — the `source` lane of design-lint.py.

Static analysis of a UI source tree (CSS/SCSS/LESS, HTML, JSX/TSX, Vue,
Svelte, Astro, plus .js/.ts for the motion-runtime checks) against the
checkable half of configs/skills/frontend-design/references/design-rules.md.
It lives beside design-lint.py, which sat at 1,489 of the 1,500-line cap,
and is run through it: `design-lint source <dir>`. What it shares with the
html lane is in design_lint_common.py. Stdlib only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from design_lint_common import (
    _FOCUS_RESTORE, _STYLE_BLOCK, Report, custom_properties, resolve_value)


# ─── Lane: source (static analysis of UI source trees) ───
#
# The html lane judges one rendered artifact page. This lane judges the SOURCE
# a product is built from — CSS/SCSS/LESS, HTML, and the template/JSX files
# that carry class names and copy — against the checkable half of
# configs/skills/frontend-design/references/design-rules.md: the spacing grid,
# the type-scale caps, the motion table, token discipline and the copy ban.
# Those rules exist because an agent asked for "premium, polished, designed"
# ships 13/18/22/27 px spacing, nine font sizes and a 900 ms fade by default;
# an explicit system it executes well.
#
# What it cannot see (one primary action per viewport, shared edges, tier
# contrast, control heights, responsive re-composition, every state) is
# reported as a SKIP naming the screenshot review, so a clean run never reads
# as a clean page.
#
# Severity policy: FAIL only for the two accessibility floors the html lane
# already fails on (motion with no reduced-motion guard, focus outline removed
# without a replacement). Everything else is WARN with the measured value,
# because each of those rules admits a written visual reason — the reviewer
# decides, this instrument names the sites. The thresholds are the essay's own
# numbers (4-px grid, 4–6 sizes, 3–4 weights, at most 2 families, 400 ms,
# 16 px), not measured fire rates; run it on a tree you consider clean before
# treating a WARN count as a verdict.

SOURCE_SUFFIXES = {".css", ".scss", ".less", ".html", ".htm",
                   ".tsx", ".jsx", ".vue", ".svelte", ".astro"}
SOURCE_MARKUP_SUFFIXES = {".html", ".htm", ".vue", ".svelte", ".astro"}
SOURCE_SCRIPT_SUFFIXES = {".tsx", ".jsx"}
# Plain script files carry the scroll story's runtime (GSAP, canvas, Three.js)
# and get ONLY the motion-runtime checks — never spacing, type or colour: a
# `padding: 13` inside a PDF library is not a design decision, and the guard
# that matters (`useReducedMotion`, `matchMedia('(prefers-reduced-motion')`)
# lives here as often as in a stylesheet.
SOURCE_RUNTIME_SUFFIXES = {".js", ".mjs", ".cjs", ".ts", ".mts", ".cts"}
SOURCE_SKIP_DIRS = {"node_modules", "dist", "build", "out", "coverage", "vendor",
                    ".git", ".next", ".nuxt", ".svelte-kit", ".turbo",
                    "storybook-static", "__pycache__"}
SPACING_GRID_PX = 4
SPACING_NUDGE_PX = 2            # 1–2 px is a hairline or an optical nudge, not space
TYPE_SIZES_MAX = 6
TYPE_WEIGHTS_MAX = 4
TYPE_FAMILIES_MAX = 2
RADIUS_VALUES_MAX = 4
SHADOW_VALUES_MAX = 3
MOTION_MAX_MS = 400.0           # above this only a signature sequence is allowed
MOTION_TRANSLATE_MAX_PX = 16.0
EXAMPLES_SHOWN = 5

SLOP_PHRASES = (
    "revolutioni[sz]e", "unlock the power", "transform your business",
    "get started today", "next[- ]generation", "supercharge", "seamlessly",
    "cutting[- ]edge", "game[- ]changing", "unleash", "赋能", "重新定义", "颠覆",
)
_SLOP = re.compile("(?<![A-Za-z])(?:" + "|".join(SLOP_PHRASES) + ")", re.I)

_GENERIC_FAMILIES = {"serif", "sans-serif", "monospace", "cursive", "fantasy",
                     "system-ui", "ui-sans-serif", "ui-serif", "ui-monospace",
                     "ui-rounded", "inherit", "initial", "unset", "revert", "math",
                     "emoji", "fangsong"}
_TW_FONT_SIZE_PX = {"xs": 12.0, "sm": 14.0, "base": 16.0, "lg": 18.0, "xl": 20.0,
                    "2xl": 24.0, "3xl": 30.0, "4xl": 36.0, "5xl": 48.0, "6xl": 60.0,
                    "7xl": 72.0, "8xl": 96.0, "9xl": 128.0}
_TW_FONT_WEIGHT = {"thin": 100, "extralight": 200, "light": 300, "normal": 400,
                   "medium": 500, "semibold": 600, "bold": 700, "extrabold": 800,
                   "black": 900}
_CSS_WEIGHT = {"normal": 400, "bold": 700}
_LAYOUT_TRANSITION_PROPS = {"all", "width", "height", "top", "left", "right",
                            "bottom", "margin", "padding", "inset", "min-width",
                            "max-width", "min-height", "max-height", "font-size",
                            "line-height"}
# An infinite animation is a loader when its keyframe name or its selector says
# so; anything else that loops forever is the "background drifting to no
# purpose" the rules forbid.
_LOADER_HINT = re.compile(
    r"spin|load|skeleton|shimmer|pulse|progress|ping|indeterminate|busy|wait", re.I)

_SRC_COMMENT = re.compile(r"/\*.*?\*/|<!--.*?-->", re.S)
_SRC_LINE_COMMENT = re.compile(r"^[ \t]*//[^\n]*$", re.M)
_SRC_SCRIPT_BLOCK = re.compile(r"<script\b[^>]*>.*?</script>", re.S | re.I)
_SRC_TAG = re.compile(r"<[^>]*>")
# `name: value` in CSS, SCSS, style attributes, CSS-in-JS template literals and
# React style objects (camelCase is normalised). Custom-property definitions
# (`--ink: #222`) never match: the name must start with a letter and cannot be
# preceded by `-`, so a token file is not reported as a wall of literals.
_PROP_DECL = re.compile(
    r"(?<![\w$-])([A-Za-z][\w-]*)\s*:\s*('[^'\n]*'|\"[^\"\n]*\"|[^;{}\n]+)")
_LENGTH = re.compile(r"(-?\d*\.?\d+)(px|rem)\b")
_TIME = re.compile(r"(\d*\.?\d+)(ms|s)\b")
_COLOR_LITERAL = re.compile(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgb|hsl)a?\(", re.I)
_UNRESOLVABLE = re.compile(r"\b(?:calc|clamp|min|max|env|var)\(", re.I)
_KEYFRAMES_OPEN = re.compile(r"@keyframes\s+([\w-]+)\s*\{", re.I)
_TRANSLATE = re.compile(r"translate(?:X|Y|3d)?\(\s*(-?\d*\.?\d+)px", re.I)
_MOTION_GUARD = re.compile(r"prefers-reduced-motion|useReducedMotion|reduced-?motion", re.I)

_TW_SPACING = re.compile(
    r"(?<![\w-])-?(?:p|px|py|pt|pr|pb|pl|ps|pe|m|mx|my|mt|mr|mb|ml|ms|me|gap|gap-x|gap-y|"
    r"space-x|space-y)-\[(-?\d*\.?\d+)px\]")
_TW_TEXT_PX = re.compile(r"(?<![\w-])text-\[(\d*\.?\d+)px\]")
_TW_TEXT_STEP = re.compile(r"(?<![\w-])text-(xs|sm|base|lg|xl|[2-9]xl)(?![\w-])")
_TW_WEIGHT = re.compile(
    r"(?<![\w-])font-(thin|extralight|light|normal|medium|semibold|bold|extrabold|black)(?![\w-])")
_TW_RADIUS = re.compile(
    r"(?<![\w-])rounded(?:-(?:t|r|b|l|tl|tr|br|bl|s|e|ss|se|es|ee))?-\[(\d*\.?\d+)px\]")
_TW_DURATION = re.compile(r"(?<![\w-])duration-(?:\[(\d+)ms\]|(\d+))(?![\w-])")
_TW_TRANSITION_ALL = re.compile(r"(?<![\w-])transition-all(?![\w-])")
# Only Tailwind's own infinite utilities can be judged statically: spin, ping
# and pulse are loaders, bounce is ambient. A custom `animate-<name>` (an
# `animate-in` from tailwindcss-animate is a one-shot entrance) is motion, but
# whether it loops lives in the config this scan does not read.
_TW_ANIMATE = re.compile(r"(?<![\w-])animate-(spin|ping|pulse|bounce)(?![\w-])")
_TW_MOTION = re.compile(r"(?<![\w-])(?:transition(?:-[\w]+)?|duration-[\w\[\]]+|animate-[\w\[\]]+)(?![\w-])")
_TW_COLOR = re.compile(
    r"(?<![\w-])(?:bg|text|border|from|via|to|ring|fill|stroke|outline|decoration|divide|"
    r"shadow|accent|caret|placeholder)-\[#[0-9a-fA-F]{3,8}\]")
_TW_OUTLINE_NONE = re.compile(r"(?<![\w-])outline-none(?![\w-])")
_TW_FOCUS_RESTORE = re.compile(r"(?<![\w-])focus(?:-visible|-within)?:(?:ring|outline|border|shadow)")

# ─── Motion runtime (signature-motion.md §5) ───
#
# Three properties of a scroll story or hero piece that a static read CAN see.
# Scroll-jacking: a wheel/touch listener that calls preventDefault, or a
# page-snapping library. DPR: `devicePixelRatio` used with no Math.min/clamp
# nearby — the 2–3x canvas that drops frames on phones. Render loop: a
# requestAnimationFrame loop or setAnimationLoop with no visibility gate
# anywhere in the tree, so the canvas keeps drawing off-screen and after the
# intro. Each is a WARN naming the site; a legitimate drag handler or a demand
# frameloop is the reviewer's call, not this instrument's.
_WHEEL_LISTENER = re.compile(
    r"addEventListener\s*\(\s*['\"](?:wheel|mousewheel|DOMMouseScroll|touchmove)['\"]", re.I)
_PREVENT_DEFAULT = re.compile(r"\.preventDefault\s*\(")
_SCROLLJACK_LIB = re.compile(
    r"['\"](?:fullpage\.js|fullpage|@fullpage/[\w-]+|pagepiling(?:\.js)?|jquery\.scrollify|"
    r"scrollify|onepage-scroll)['\"]", re.I)
_DPR_USE = re.compile(r"devicePixelRatio")
_DPR_CAP = re.compile(r"Math\.min\s*\(|clamp\s*\(|dpr\s*[=:]\s*\{?\s*\[|setPixelRatio\s*\(\s*Math\.min", re.I)
_RENDER_LOOP = re.compile(r"\bsetAnimationLoop\s*\(|\brequestAnimationFrame\s*\(")
_VISIBILITY_GATE = re.compile(
    r"IntersectionObserver|visibilitychange|document\.hidden|isIntersecting|\bonEnter\b|"
    r"\bonLeave\b|\bonToggle\b|\binView\b|\buseInView\b|frameloop\s*=\s*['\"]demand", re.I)


@dataclass
class _Site:
    """One place in the tree where a rule was measured: `file:line what`."""
    label: str
    line: int
    text: str

    def __str__(self) -> str:
        return f"{self.label}:{self.line} {self.text}"


@dataclass
class _SourceScan:
    spacing_total: int = 0
    spacing_off: list[_Site] = field(default_factory=list)
    margins: int = 0
    gaps: int = 0
    sizes: dict[float, _Site] = field(default_factory=dict)
    weights: dict[int, _Site] = field(default_factory=dict)
    families: dict[str, _Site] = field(default_factory=dict)
    radii: dict[str, _Site] = field(default_factory=dict)
    shadows: dict[str, _Site] = field(default_factory=dict)
    durations: int = 0
    durations_over: list[_Site] = field(default_factory=list)
    layout_transitions: list[_Site] = field(default_factory=list)
    infinite_ambient: list[_Site] = field(default_factory=list)
    keyframes: int = 0
    translate_over: list[_Site] = field(default_factory=list)
    colors: list[_Site] = field(default_factory=list)
    slop: list[_Site] = field(default_factory=list)
    markup_files: int = 0
    has_motion: bool = False
    has_guard: bool = False
    kills_outline: list[_Site] = field(default_factory=list)
    restores_focus: bool = False
    script_files: int = 0
    scrolljack: list[_Site] = field(default_factory=list)
    dpr_uncapped: list[_Site] = field(default_factory=list)
    dpr_capped: int = 0
    render_loops: list[_Site] = field(default_factory=list)
    has_visibility_gate: bool = False


def _blank_comments(text: str) -> str:
    """Replace comment bodies with spaces, keeping every newline so line
    numbers computed on the result still point at the original file."""
    def blank(m: re.Match) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))
    return _SRC_LINE_COMMENT.sub(blank, _SRC_COMMENT.sub(blank, text))


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _kebab(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()


def _px(value: str, unit: str) -> float:
    return float(value) * (16.0 if unit == "rem" else 1.0)


def _off_grid(px: float) -> bool:
    if abs(px) <= SPACING_NUDGE_PX:
        return False
    return abs(px / SPACING_GRID_PX - round(px / SPACING_GRID_PX)) > 1e-6


def _first(sites: list[_Site]) -> str:
    shown = ", ".join(str(s) for s in sites[:EXAMPLES_SHOWN])
    more = len(sites) - EXAMPLES_SHOWN
    return shown + (f" … +{more} more" if more > 0 else "")


def _scan_declarations(text: str, label: str, props: dict[str, str], scan: _SourceScan) -> None:
    for m in _PROP_DECL.finditer(text):
        name = _kebab(m.group(1))
        raw = m.group(2).strip()
        # A React style object or CSS-in-JS value is a quoted string; the
        # declaration regex stops at the line end, so trim to the closing quote
        # or `color: '#fff'` on the same line is read as part of `paddingTop`.
        if raw[:1] in ("'", '"') and raw.find(raw[0], 1) > 0:
            raw = raw[1:raw.find(raw[0], 1)]
        if not raw or "$" in raw:              # template interpolation: unresolvable
            continue
        line = _line_of(text, m.start())
        site = _Site(label, line, f"{name}: {raw[:48]}")
        value = resolve_value(raw, props)

        if name in ("gap", "row-gap", "column-gap") or name.startswith(("margin", "padding")):
            if name.startswith("margin"):
                scan.margins += 1
            elif name.startswith("gap") or name.endswith("gap"):
                scan.gaps += 1
            if _UNRESOLVABLE.search(value):
                continue
            lengths = [_px(lm.group(1), lm.group(2)) for lm in _LENGTH.finditer(value)]
            if lengths:
                scan.spacing_total += 1
                if any(_off_grid(px) for px in lengths):
                    scan.spacing_off.append(site)
        elif name == "font-size":
            sm = _LENGTH.search(value)
            if sm and not _UNRESOLVABLE.search(value):
                scan.sizes.setdefault(round(_px(sm.group(1), sm.group(2)), 1), site)
        elif name == "font-weight":
            wm = re.search(r"\b([1-9]00)\b", value)
            weight = int(wm.group(1)) if wm else _CSS_WEIGHT.get(value.strip().lower())
            if weight:
                scan.weights.setdefault(weight, site)
        elif name == "font-family":
            first = value.split(",")[0].strip().strip("'\"").lower()
            if first and first not in _GENERIC_FAMILIES and "var(" not in first:
                scan.families.setdefault(first, site)
        elif name == "border-radius" or name.endswith("-radius"):
            key = "pill" if re.search(r"%|9{3,}|1e\d|vmax", value) else " ".join(value.split())
            if key and not _UNRESOLVABLE.search(key):
                scan.radii.setdefault(key, site)
        elif name == "box-shadow":
            key = " ".join(value.split())
            if key and key.lower() != "none":
                scan.shadows.setdefault(key, site)
        elif name in ("transition", "transition-property", "transition-duration",
                      "animation", "animation-duration", "animation-iteration-count"):
            _scan_motion_decl(text, m, name, value, site, scan)
        elif name in ("outline", "outline-style") and re.match(r"(none|0)\b", value.strip()):
            scan.kills_outline.append(site)

        # Shadow colours are judged under geometry.shadow; counting them here
        # too would report one shadow token as two findings.
        if _COLOR_LITERAL.search(raw) and name not in (
                "content", "src", "href", "url", "background-image", "mask-image",
                "box-shadow", "text-shadow", "filter"):
            scan.colors.append(site)


def _scan_motion_decl(text: str, m: re.Match, name: str, value: str,
                      site: _Site, scan: _SourceScan) -> None:
    if value.strip().lower() in ("none", "0", "0s", "0ms"):
        return
    scan.has_motion = True
    context = text[max(0, m.start() - 120):m.end()]
    loader = bool(_LOADER_HINT.search(context))
    if name in ("animation", "animation-iteration-count") and "infinite" in value.lower() and not loader:
        scan.infinite_ambient.append(site)
    for segment in value.split(","):
        tm = _TIME.search(segment)
        if tm and name != "animation-iteration-count":
            scan.durations += 1
            ms = float(tm.group(1)) * (1000.0 if tm.group(2) == "s" else 1.0)
            if ms > MOTION_MAX_MS and not (loader and "infinite" in value.lower()):
                scan.durations_over.append(site)
        if name in ("transition", "transition-property"):
            head = re.match(r"\s*([a-z-]+)", segment, re.I)
            # A shorthand with no property name transitions `all`, per spec.
            prop = head.group(1).lower() if head and not _TIME.match(segment.strip()) else "all"
            if prop in _LAYOUT_TRANSITION_PROPS:
                scan.layout_transitions.append(site)
                break


def _scan_tailwind(text: str, label: str, scan: _SourceScan) -> None:
    def site(m: re.Match) -> _Site:
        return _Site(label, _line_of(text, m.start()), m.group(0)[:48])

    for m in _TW_SPACING.finditer(text):
        scan.spacing_total += 1
        if _off_grid(float(m.group(1))):
            scan.spacing_off.append(site(m))
    for m in _TW_TEXT_PX.finditer(text):
        scan.sizes.setdefault(round(float(m.group(1)), 1), site(m))
    for m in _TW_TEXT_STEP.finditer(text):
        scan.sizes.setdefault(_TW_FONT_SIZE_PX[m.group(1)], site(m))
    for m in _TW_WEIGHT.finditer(text):
        scan.weights.setdefault(_TW_FONT_WEIGHT[m.group(1)], site(m))
    for m in _TW_RADIUS.finditer(text):
        scan.radii.setdefault(f"{m.group(1)}px", site(m))
    for m in _TW_DURATION.finditer(text):
        scan.has_motion = True
        scan.durations += 1
        if float(m.group(1) or m.group(2)) > MOTION_MAX_MS:
            scan.durations_over.append(site(m))
    for m in _TW_TRANSITION_ALL.finditer(text):
        scan.has_motion = True
        scan.layout_transitions.append(site(m))
    for m in _TW_ANIMATE.finditer(text):
        if not _LOADER_HINT.search(m.group(1)):
            scan.infinite_ambient.append(site(m))
    if _TW_MOTION.search(text):
        scan.has_motion = True
    for m in _TW_COLOR.finditer(text):
        scan.colors.append(site(m))
    for m in _TW_OUTLINE_NONE.finditer(text):
        scan.kills_outline.append(site(m))
    if _TW_FOCUS_RESTORE.search(text):
        scan.restores_focus = True


def _scan_keyframes(text: str, label: str, scan: _SourceScan) -> None:
    for m in _KEYFRAMES_OPEN.finditer(text):
        scan.keyframes += 1
        depth, j = 1, m.end()
        while j < len(text) and depth:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
            j += 1
        block = text[m.end():j]
        for t in _TRANSLATE.finditer(block):
            if abs(float(t.group(1))) > MOTION_TRANSLATE_MAX_PX:
                scan.translate_over.append(_Site(
                    label, _line_of(text, m.end() + t.start()),
                    f"@keyframes {m.group(1)}: {t.group(0)}"))
                break


def _scan_copy(text: str, label: str, suffix: str, scan: _SourceScan) -> None:
    if suffix in SOURCE_MARKUP_SUFFIXES:
        prose = _SRC_TAG.sub(lambda t: re.sub(r"[^\n]", " ", t.group(0)),
                             _SRC_SCRIPT_BLOCK.sub(lambda t: re.sub(r"[^\n]", " ", t.group(0)),
                                                   _STYLE_BLOCK.sub(lambda t: re.sub(r"[^\n]", " ", t.group(0)), text)))
    elif suffix in SOURCE_SCRIPT_SUFFIXES:
        prose = text                      # JSX text and string literals both count
    else:
        return
    scan.markup_files += 1
    for m in _SLOP.finditer(prose):
        scan.slop.append(_Site(label, _line_of(prose, m.start()), f"“{m.group(0)}”"))


def _scan_runtime(text: str, label: str, scan: _SourceScan) -> None:
    """The motion-runtime checks: run on every script-bearing file."""
    scan.script_files += 1
    if _VISIBILITY_GATE.search(text):
        scan.has_visibility_gate = True
    for m in _WHEEL_LISTENER.finditer(text):
        if _PREVENT_DEFAULT.search(text):
            scan.scrolljack.append(_Site(label, _line_of(text, m.start()),
                                         m.group(0)[:40] + " + preventDefault()"))
    for m in _SCROLLJACK_LIB.finditer(text):
        scan.scrolljack.append(_Site(label, _line_of(text, m.start()), m.group(0)))
    for m in _DPR_USE.finditer(text):
        window = text[max(0, m.start() - 80):m.end() + 80]
        if _DPR_CAP.search(window):
            scan.dpr_capped += 1
        else:
            scan.dpr_uncapped.append(_Site(label, _line_of(text, m.start()),
                                           text[m.start():m.end() + 24].split("\n")[0]))
    loops = list(_RENDER_LOOP.finditer(text))
    # One requestAnimationFrame is a "next frame" hop; a loop calls it from
    # inside itself, so it shows up at least twice. setAnimationLoop is a loop
    # by definition.
    if any("setAnimationLoop" in m.group(0) for m in loops) or len(loops) >= 2:
        scan.render_loops.append(_Site(label, _line_of(text, loops[0].start()),
                                       f"{len(loops)} render-loop call(s)"))


def _emit_scale(report: Report, check: str, tag: str, found: dict, cap: int, noun: str,
                key_fmt=str) -> None:
    if not found:
        report.add(check, "SKIP", tag, f"no {noun} declarations found")
        return
    keys = sorted(found, key=lambda k: (isinstance(k, str), k))
    listed = ", ".join(key_fmt(k) for k in keys)
    if len(found) > cap:
        report.add(check, "WARN", tag,
                   f"{len(found)} distinct {noun} values ({listed}) — the rule allows {cap}; "
                   f"first sites: {_first([found[k] for k in keys])}",
                   measured=len(found), threshold=cap)
    else:
        report.add(check, "PASS", tag, f"{len(found)} distinct {noun} values ({listed})",
                   measured=len(found), threshold=cap)


def lint_source(paths: list[Path], root: Path, report: Report) -> None:
    """Scan a UI source tree once; the type scale and motion guard are
    product-level properties, so findings aggregate across files and each
    example carries its own `file:line`."""
    texts: dict[str, str] = {}
    for path in paths:
        try:
            label = str(path.relative_to(root))
        except ValueError:
            label = path.name
        try:
            texts[label] = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            report.add("source.read", "SKIP", label, f"unreadable: {exc}")
    tag = str(root)
    if not texts:
        report.add("source.scope", "SKIP", tag, "no readable UI source files")
        return

    props: dict[str, str] = {}
    for raw in texts.values():
        props.update(custom_properties(raw))
    scan = _SourceScan()
    by_suffix: dict[str, int] = {}
    for label, raw in texts.items():
        suffix = Path(label).suffix.lower()
        by_suffix[suffix] = by_suffix.get(suffix, 0) + 1
        text = _blank_comments(raw)
        if _MOTION_GUARD.search(text):
            scan.has_guard = True
        if suffix in SOURCE_RUNTIME_SUFFIXES:
            _scan_runtime(text, label, scan)       # runtime checks only, by design
            continue
        if _FOCUS_RESTORE.search(text):
            scan.restores_focus = True
        _scan_declarations(text, label, props, scan)
        _scan_tailwind(text, label, scan)
        _scan_keyframes(text, label, scan)
        _scan_copy(text, label, suffix, scan)
        if suffix in SOURCE_SCRIPT_SUFFIXES or suffix in SOURCE_MARKUP_SUFFIXES:
            _scan_runtime(text, label, scan)

    report.add("source.scope", "PASS", tag,
               f"{len(texts)} file(s): " + ", ".join(f"{n} {s}" for s, n in sorted(by_suffix.items())))

    # -- spacing grid ---------------------------------------------------------
    if scan.spacing_total == 0:
        report.add("source.spacing.grid", "SKIP", tag, "no px/rem spacing declarations found")
    elif scan.spacing_off:
        report.add("source.spacing.grid", "WARN", tag,
                   f"{len(scan.spacing_off)} of {scan.spacing_total} spacing values are off the "
                   f"{SPACING_GRID_PX}-px grid (margins {scan.margins}, gaps {scan.gaps}): "
                   f"{_first(scan.spacing_off)} — each needs a written visual reason or the "
                   f"nearest scale step", measured=len(scan.spacing_off), threshold=0)
    else:
        report.add("source.spacing.grid", "PASS", tag,
                   f"{scan.spacing_total} spacing values, all on the {SPACING_GRID_PX}-px grid "
                   f"(margins {scan.margins}, gaps {scan.gaps}; 1–{SPACING_NUDGE_PX} px nudges ignored)",
                   measured=0, threshold=0)

    # -- type scale -----------------------------------------------------------
    _emit_scale(report, "source.type.sizes", tag, scan.sizes, TYPE_SIZES_MAX,
                "font-size", key_fmt=lambda k: f"{k:g}px")
    _emit_scale(report, "source.type.weights", tag, scan.weights, TYPE_WEIGHTS_MAX, "font-weight")
    _emit_scale(report, "source.type.families", tag, scan.families, TYPE_FAMILIES_MAX,
                "font-family")

    # -- geometry -------------------------------------------------------------
    _emit_scale(report, "source.geometry.radius", tag, scan.radii, RADIUS_VALUES_MAX,
                "border-radius")
    _emit_scale(report, "source.geometry.shadow", tag, scan.shadows, SHADOW_VALUES_MAX,
                "box-shadow", key_fmt=lambda k: k[:32])

    # -- motion ---------------------------------------------------------------
    if not scan.has_motion:
        report.add("source.motion", "SKIP", tag, "no transition or animation declared")
    else:
        if scan.durations_over:
            report.add("source.motion.duration", "WARN", tag,
                       f"{len(scan.durations_over)} of {scan.durations} durations exceed "
                       f"{MOTION_MAX_MS:.0f} ms (reserved for one signature sequence): "
                       f"{_first(scan.durations_over)}",
                       measured=len(scan.durations_over), threshold=0)
        elif scan.durations:
            report.add("source.motion.duration", "PASS", tag,
                       f"all {scan.durations} durations at or under {MOTION_MAX_MS:.0f} ms",
                       measured=0, threshold=0)
        if scan.layout_transitions:
            report.add("source.motion.property", "WARN", tag,
                       f"{len(scan.layout_transitions)} transition(s) on a layout property or "
                       f"`all` (relayout on every frame): {_first(scan.layout_transitions)}",
                       measured=len(scan.layout_transitions), threshold=0)
        else:
            report.add("source.motion.property", "PASS", tag,
                       "transitions name transform/opacity-class properties only")
        if scan.infinite_ambient:
            report.add("source.motion.infinite", "WARN", tag,
                       f"{len(scan.infinite_ambient)} infinite animation(s) that are not loaders: "
                       f"{_first(scan.infinite_ambient)}",
                       measured=len(scan.infinite_ambient), threshold=0)
        else:
            report.add("source.motion.infinite", "PASS", tag,
                       "no ambient infinite animation (loaders excepted)")
        if scan.translate_over:
            report.add("source.motion.displacement", "WARN", tag,
                       f"{len(scan.translate_over)} keyframe(s) move more than "
                       f"{MOTION_TRANSLATE_MAX_PX:.0f} px: {_first(scan.translate_over)}",
                       measured=len(scan.translate_over), threshold=MOTION_TRANSLATE_MAX_PX)
        elif scan.keyframes:
            report.add("source.motion.displacement", "PASS", tag,
                       f"{scan.keyframes} @keyframes, none translating past "
                       f"{MOTION_TRANSLATE_MAX_PX:.0f} px")
        if scan.has_guard:
            report.add("source.motion.reduced", "PASS", tag,
                       "motion is guarded by prefers-reduced-motion")
        else:
            report.add("source.motion.reduced", "FAIL", tag,
                       "declares transition/animation with no prefers-reduced-motion guard "
                       "anywhere under this root — if the guard lives in a global stylesheet "
                       "outside it, run on the directory that contains both")

    # -- motion runtime (signature-motion.md §5) ------------------------------
    if not scan.script_files:
        report.add("source.motion.runtime", "SKIP", tag,
                   "no script-bearing files — scroll-jacking, DPR and render-loop checks did not run")
    else:
        if scan.scrolljack:
            report.add("source.motion.scrolljack", "WARN", tag,
                       f"{len(scan.scrolljack)} site(s) intercept the user's scroll: "
                       f"{_first(scan.scrolljack)} — pin the scene, never decide the page's "
                       f"scroll for the reader (a drag handler is the reviewer's call)",
                       measured=len(scan.scrolljack), threshold=0)
        else:
            report.add("source.motion.scrolljack", "PASS", tag,
                       f"no wheel/touch interception or page-snapping library in "
                       f"{scan.script_files} script-bearing file(s)")
        if scan.dpr_uncapped:
            report.add("source.motion.dpr", "WARN", tag,
                       f"{len(scan.dpr_uncapped)} devicePixelRatio use(s) with no cap nearby: "
                       f"{_first(scan.dpr_uncapped)} — cap at 2 (Math.min) or a 3x canvas "
                       f"drops frames on phones", measured=len(scan.dpr_uncapped), threshold=0)
        elif scan.dpr_capped:
            report.add("source.motion.dpr", "PASS", tag,
                       f"devicePixelRatio capped at all {scan.dpr_capped} use(s)")
        else:
            report.add("source.motion.dpr", "SKIP", tag, "devicePixelRatio not used")
        if scan.render_loops and not scan.has_visibility_gate:
            report.add("source.motion.render-loop", "WARN", tag,
                       f"{len(scan.render_loops)} render loop(s) with no visibility gate "
                       f"anywhere under this root: {_first(scan.render_loops)} — pause "
                       f"off-screen (IntersectionObserver, visibilitychange) and stop after "
                       f"the intro", measured=len(scan.render_loops), threshold=0)
        elif scan.render_loops:
            report.add("source.motion.render-loop", "PASS", tag,
                       f"{len(scan.render_loops)} render loop(s) and a visibility gate is present")
        else:
            report.add("source.motion.render-loop", "SKIP", tag, "no render loop found")

    # -- focus visibility -----------------------------------------------------
    if not scan.kills_outline:
        report.add("source.focus", "SKIP", tag, "nothing removes the focus outline")
    elif scan.restores_focus:
        report.add("source.focus", "PASS", tag,
                   f"outline removed at {len(scan.kills_outline)} site(s) and a focus style is restored")
    else:
        report.add("source.focus", "FAIL", tag,
                   f"removes the focus outline without a replacement indicator: "
                   f"{_first(scan.kills_outline)}")

    # -- token discipline -----------------------------------------------------
    if scan.colors:
        report.add("source.color.literal", "WARN", tag,
                   f"{len(scan.colors)} colour literal(s) outside custom-property definitions "
                   f"(a token file is the fix): {_first(scan.colors)}",
                   measured=len(scan.colors), threshold=0)
    else:
        report.add("source.color.literal", "PASS", tag,
                   "no colour literal outside custom-property definitions")

    # -- copy -----------------------------------------------------------------
    if not scan.markup_files:
        report.add("source.copy.slop", "SKIP", tag, "no markup or JSX files to read copy from")
    elif scan.slop:
        report.add("source.copy.slop", "WARN", tag,
                   f"{len(scan.slop)} banned marketing phrase(s): {_first(scan.slop)} — say what "
                   f"happens, with a number", measured=len(scan.slop), threshold=0)
    else:
        report.add("source.copy.slop", "PASS", tag,
                   f"no banned marketing phrase in {scan.markup_files} markup/JSX file(s)")

    # -- what a static scan cannot see ----------------------------------------
    report.add("source.unmeasured", "SKIP", tag,
               "one primary action per viewport, shared edges, tier contrast, control "
               "heights, responsive re-composition and per-state completeness are not "
               "visible statically — run the screenshot review in design-review.md")
