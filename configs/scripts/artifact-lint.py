#!/usr/bin/env python3
"""artifact-lint — is this HTML report page legible at a glance?

Checks a single-page HTML artifact (a research finding, a status report, an
architecture page, an RCA, a handoff, a work-log) against the structure,
figure and build rules in `configs/skills/artifact/references/`. It is the
mechanical half of that skill: every rule here is one the skill also states in
prose, and a rule the script cannot check is not in this file.

    python3 artifact-lint.py page.html            # findings, exit 1 on FAIL
    python3 artifact-lint.py page.html --strict   # WARN also fails
    python3 artifact-lint.py page.html --json
    python3 artifact-lint.py --survey /path/to/hub --alias jane-doe=jdoe
    python3 artifact-lint.py --self-test

Why it exists — measured on 2026-09-23 over one company artifact hub (936
report pages plus 107 work-logs) with this script's --survey: 72% of pages
had no section explaining why the numbers look like this, 88% none saying
what was done to find out, 71% no next-step section, 68% no limits section,
66% no sources section, 53% no key or terms section, 35% a topic label for a
headline, 41% failed the head standard, and 32% carried any figure at all.
No page of 936 passed every check; two answered all five of why, method,
limits, next and key. The gap was hub-wide, not one author's: nothing named
the standard, so nothing could check it. This does.

Levels: FAIL blocks publishing (a page that cannot be read or does not render
on the intranet); WARN needs a fix or a written reason; INFO is a measurement.
The page declares its type with `<meta name="artifact-type" content="...">`
— finding | status | architecture | rca | handoff | reference | worklog |
landing — and the checks that only make sense for an argued page (claim
headings, limits, next step) relax for a reference register or a work-log.
An undeclared page is linted as a finding, the strictest shape, and told so.

stdlib only: CI's syntax-check job installs no project dependencies.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import statistics
import sys
from html.parser import HTMLParser
from typing import Iterable, TypedDict

# ─── Vocabulary ──────────────────────────────────────────────────────────────
# Each pattern is a heuristic and is reported as one; the skill's prose is the
# rule. Chinese and English both count: the hub this was measured on is
# bilingual, and a rule that only reads English would score half the pages
# as headless.

TYPES = ("finding", "status", "architecture", "rca", "handoff",
         "reference", "worklog", "landing")

_CLAIM_EN = re.compile(
    r"\b(is|are|was|were|be|not|no|never|can|cannot|can't|could|should|would"
    r"|will|must|may|might|does|did|do|has|have|had|learned|left|stuck"
    r"|already|beats|fails?|failed|works?|worked|needs?|means|says|shows"
    r"|holds|wins|loses|costs?|took|takes|stops?|stopped|drops?|why|how"
    r"|what|which|who|where|when|versus|vs\.?|than|still|only|except"
    r"|because|but|so|if|unless|until|before|after|instead)\b", re.I)
_CLAIM_ZH = re.compile(r"不|是|会|吗|还|没|才|就|比|为什么|怎么|哪|谁|多少|还是|了|能|要|在|因为|但|却|才|而")
_CJK = re.compile(r"[一-鿿぀-ヿ]")
_ENDS = re.compile(r"[.?!。？！]\s*$")

_KEY_TERMS = re.compile(
    r"colou?r key|key (and|&) terms|\bterms\b|glossary|definitions?"
    r"|what these words mean|how to read|reading (the|this) (page|table|chart)"
    r"|口径|术语|名词|怎么读|读法|符号说明|图例", re.I)
_SOURCES = re.compile(
    r"\bsources?\b|evidence|provenance|reproduc"
    r"|where (it|this|everything|things) (lives?|came from)|appendix"
    r"|来源|复现|出处|证据|附录", re.I)
# the two sections the owner kept asking for by name: why the numbers look
# like this (the mechanism, what was ruled out) and what was done to find out
_WHY = re.compile(
    r"\bwhy\b|because|mechanism|what drives|root cause|\bcauses?\b|explain"
    r"|how it happens|where (the|this|that) (gain|number|gap|difference) comes from"
    r"|为什么|原因|机制|怎么来的|来自哪|根因|解释", re.I)
_METHOD = re.compile(
    r"what (i|we) did|how (this|it|that) was (measured|built|done|counted|found)"
    r"|what (was|i|we) read|method(ology)?|research (log|process|done|notes?)"
    r"|how (we|i) (did|measured|counted|found)|measured how"
    r"|我做了|做了什么|做了哪些|研究过程|怎么测|怎么算|怎么做的|方法|怎么造", re.I)
_LIMITS = re.compile(
    r"limit|not (yet )?(done|covered)|does not cover|do not cover|not covered"
    r"|claims we do not|what (it|this) is not|unknown|could ?n.t (establish|see)"
    r"|open (question|item)|caveat|not (measured|supported)|honest gap"
    r"|what this (report|page) does not|non-goals?|falls? short|not (good )?enough"
    r"|not yet\b|missing|\bgaps?\b|don.t know|do not know|unverified|known-wrong"
    r"|misread|verified here|judge?ment|confidence|what (we|i) (could|can) ?n.t"
    r"|边界|缺口|限制|还没|不做|未做|未覆盖|不覆盖|局限|没做|不包括|不知道|未验证", re.I)
_NEXT = re.compile(
    r"\bnext\b|what to do|to-?do|follow-?ups?|continue|in order|action items?"
    r"|what would (make|it take)|what it would take|recommend|proposal|roadmap"
    r"|\bplan\b|decisions? (for|that wait)|needs? (your|an owner)|your call"
    r"|下一步|接下来|待办|要做|后续|行动项|建议|计划|需要你", re.I)
_FAILED = re.compile(
    r"did not work|didn.t work|what failed|failed|abandon|tried|derail"
    r"|could (have )?kill|went wrong|dead ends?|negative results?"
    r"|走不通|失败|没成|放弃|翻车|试过", re.I)
_ASOF = re.compile(
    r"as of|as-of|compiled|published|updated|measured|截至|统计至"
    r"|\b20\d\d[-/.]\d\d[-/.]\d\d\b"
    r"|\b\d{1,2} (jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w* 20\d\d\b"
    r"|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w* \d{1,2},? 20\d\d\b"
    r"|20\d\d年\s?\d{1,2}月", re.I)
_PLACEHOLDER = re.compile(r"lorem ipsum|\bTBD\b|\bTODO:|\bXXX\b|\bFIXME\b")
_BANNED_COPY = re.compile(
    r"revolutioni[sz]e|unlock the power|transform your business|get started today"
    r"|next-generation|seamlessly|赋能", re.I)
_PCT = re.compile(r"\d+(?:\.\d+)?\s?%")
_COUNT_NEAR = re.compile(r"\bn\s?=\s?\d|\b\d{1,3}(?:,\d{3})+\b|\b\d{3,}\b|\d+\s?/\s?\d+|\bof\s+\d|\b\d+\s+(?:pages|docs|documents|rows|files|runs|calls|samples|users|repos|commits)\b|共\s?\d|\d+\s?[个条份张次篇]")
_WORKLOG_HEADS = ("goal", "now", "human todo", "blockers")
_GREY = re.compile(r"^#(?:([0-9a-f])\1\1|([0-9a-f]{2})\2\2)$", re.I)
_DOCTYPE = re.compile(r"^\s*<!doctype html>", re.I)
_CHARSET = re.compile(r"<meta\s+charset", re.I)
_VIEWPORT = re.compile(r"<meta\s+name=[\"']?viewport", re.I)
_DECK_HINT = re.compile(r"deck|lede|abstract|summary|tldr|tl;dr|short version|一句话|先看结论|摘要", re.I)


# ─── Parse ───────────────────────────────────────────────────────────────────

class _Page(HTMLParser):
    """One pass over the page: headings, visible text, figures, styles, links."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.heads: list[list[str]] = []
        self._cur: str | None = None
        self.text: list[str] = []
        self.tags: collections.Counter[str] = collections.Counter()
        self.styles: list[str] = []
        self._in_style = False
        self._in_script = False
        self.script_bytes = 0
        self.title = ""
        self._in_title = False
        self.meta: dict[str, str] = {}
        self.ext: list[str] = []
        self.big_svgs: list[dict[str, object]] = []
        self._svg_depth = 0
        self._svg: dict[str, object] | None = None
        self._fig_depth = 0
        self._fig_has_caption = False
        self.figures_without_caption = 0
        self.figures_total = 0
        self.imgs_outside_figure = 0
        self.anchors = 0
        self.pars: list[str] = []
        self._in_p = False
        self._par = ""
        self.blocks: list[str] = []          # text of every p/li/figcaption, and one per table
        self._block: list[str] = []
        self._tables: list[str] = []         # open tables, cell text aggregated
        self.role_hints: list[str] = []      # id/class of headings and sections
        self.nav_text: list[str] = []        # text of in-page anchor links
        self._in_nav_a = False

    # tags ---------------------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        self.tags[tag] += 1
        if tag in ("h1", "h2", "h3", "section", "article", "aside", "nav", "details", "summary"):
            hint = (a.get("id", "") + " " + a.get("class", "") + " " + a.get("data-role", "")).strip()
            if hint:
                self.role_hints.append(hint.replace("-", " ").replace("_", " "))
        if tag in ("h1", "h2", "h3"):
            self._cur = tag
            self.heads.append([tag, ""])
        elif tag == "title":
            if self._svg_depth == 0:
                self._in_title = True
        elif tag == "style":
            self._in_style = True
        elif tag == "script":
            self._in_script = True
            if a.get("src", "").startswith(("http://", "https://", "//")):
                self.ext.append(a["src"])
        elif tag == "link":
            if "stylesheet" in a.get("rel", "") and a.get("href", "").startswith(("http://", "https://", "//")):
                self.ext.append(a["href"])
        elif tag == "meta":
            name = a.get("name", "").lower()
            if name:
                self.meta[name] = a.get("content", "")
        elif tag == "a" and a.get("href", "").startswith("#"):
            self.anchors += 1
            self._in_nav_a = True
            self.nav_text.append("")
        elif tag == "table":
            self._tables.append("")
        elif tag == "figure":
            self._fig_depth += 1
            self._fig_has_caption = False
            self.figures_total += 1
        elif tag == "figcaption":
            self._fig_has_caption = True
        elif tag == "img" and not self._fig_depth:
            self.imgs_outside_figure += 1
        elif tag == "p":
            self._in_p = True
            self._par = ""
        if tag in ("p", "li", "td", "th", "figcaption", "dd", "dt", "caption"):
            self._block.append("")
        if tag == "svg":
            self._svg_depth += 1
            if self._svg_depth == 1:
                vb = (a.get("viewBox") or a.get("viewbox") or "").split()
                w = h = 0.0
                try:
                    if len(vb) == 4:
                        w, h = float(vb[2]), float(vb[3])
                    else:
                        w = float(re.sub(r"[^0-9.]", "", a.get("width", "")) or 0)
                        h = float(re.sub(r"[^0-9.]", "", a.get("height", "")) or 0)
                except ValueError:
                    pass
                big = w >= 200 and h >= 80
                self._svg = {"big": big, "in_figure": self._fig_depth > 0,
                             "labelled": bool(a.get("aria-label") or a.get("aria-labelledby")) and a.get("role", "") == "img",
                             "colors": set(), "fonts": [], "titled": False,
                             "current": False,
                             # a palette reference figure is the one drawing whose
                             # job is to show many literal colours; it opts out of
                             # the palette and theme counts, explicitly, per figure
                             "ignore_palette": "palette" in a.get("data-artifact-lint", "")}
                if big:
                    self.big_svgs.append(self._svg)
        elif self._svg_depth and self._svg is not None:
            if tag == "title":
                self._svg["titled"] = True
            for key in ("fill", "stroke"):
                v = a.get(key, "").strip().lower()
                if v.startswith("#") and len(v) in (4, 7):
                    colors = self._svg["colors"]
                    assert isinstance(colors, set)
                    colors.add(v)
                elif v == "currentcolor" or v.startswith("var("):
                    self._svg["current"] = True
            fs = a.get("font-size", "")
            if fs:
                try:
                    fonts = self._svg["fonts"]
                    assert isinstance(fonts, list)
                    fonts.append(float(re.sub(r"[^0-9.]", "", fs) or 0))
                except ValueError:
                    pass
            style = a.get("style", "")
            if "currentcolor" in style.lower() or "var(--" in style:
                self._svg["current"] = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("h1", "h2", "h3"):
            self._cur = None
        elif tag == "title":
            self._in_title = False
        elif tag == "a":
            self._in_nav_a = False
        elif tag == "table":
            if self._tables:
                self.blocks.append(self._tables.pop().strip())
        elif tag == "style":
            self._in_style = False
        elif tag == "script":
            self._in_script = False
        elif tag == "svg":
            self._svg_depth = max(0, self._svg_depth - 1)
            if self._svg_depth == 0:
                self._svg = None
        elif tag == "figure":
            self._fig_depth = max(0, self._fig_depth - 1)
            if not self._fig_has_caption:
                self.figures_without_caption += 1
        elif tag == "p":
            self._in_p = False
            self.pars.append(self._par.strip())
        if tag in ("p", "li", "td", "th", "figcaption", "dd", "dt", "caption") and self._block:
            piece = self._block.pop().strip()
            if tag in ("td", "th", "caption") and self._tables:
                self._tables[-1] += " " + piece      # a rate's count usually sits in another cell
            else:
                self.blocks.append(piece)

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.styles.append(data)
            return
        if self._in_script:
            self.script_bytes += len(data)
            return
        if self._in_title:
            self.title += data
        if self._svg_depth:
            return
        if self._cur and self.heads:
            self.heads[-1][1] += data
        self.text.append(data)
        if self._in_p:
            self._par += data
        if self._block:
            self._block[-1] += data
        if self._in_nav_a and self.nav_text:
            self.nav_text[-1] += data


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def is_claim(heading: str) -> bool:
    """A heading that states a finding, not a topic label.

    English: three or more words with a verb-ish marker, or six words, or
    sentence punctuation. Chinese: six or more characters with a claim
    particle. 'Sources' and 'Timeline' are labels; 'Why recall is stuck at
    about a quarter' and 'Checked, not assumed' are claims.
    """
    h = _norm(heading)
    if not h:
        return False
    if _ENDS.search(h):
        return True
    if _CJK.search(h):
        return len(_CJK.findall(h)) >= 6 and bool(_CLAIM_ZH.search(h))
    words = len(h.split())
    return words >= 6 or (words >= 3 and bool(_CLAIM_EN.search(h)))


# ─── Checks ──────────────────────────────────────────────────────────────────

Finding = tuple[str, str, str]   # (id, level, message)


class Row(TypedDict):
    slug: str
    group: str
    kind: str
    words: int
    date: str
    fails: list[str]
    warns: list[str]
    figures: int
    claim_ratio: float | None


def lint_html(html: str, *, declared_type: str | None = None) -> tuple[list[Finding], dict[str, object]]:
    p = _Page()
    p.feed(html)
    p.close()
    out: list[Finding] = []

    def add(fid: str, level: str, msg: str) -> None:
        out.append((fid, level, msg))

    text = _norm(" ".join(p.text))
    words = len(text.split()) if not _CJK.search(text) else len(text.split()) + len(_CJK.findall(text)) // 2
    heads = [(t, _norm(x)) for t, x in p.heads]
    h1 = [x for t, x in heads if t == "h1"]
    h2 = [x for t, x in heads if t == "h2"]
    all_heads = " | ".join(x for _, x in heads)
    # a section's role can be stated by its heading, its id/class, or the
    # in-page nav that points at it — claim headings hide the role words, so
    # `<h2 id="limits">Why the set is not good enough</h2>` still counts
    roles = all_heads + " | " + " ".join(p.role_hints) + " | " + " ".join(_norm(t) for t in p.nav_text)
    css = "\n".join(p.styles)
    kind = (declared_type or p.meta.get("artifact-type") or "").strip().lower()
    if kind not in TYPES:
        if kind:
            add("type-unknown", "WARN", f"artifact-type {kind!r} is not one of {', '.join(TYPES)}")
        kind = "finding"
        add("type-undeclared", "INFO", "no <meta name=\"artifact-type\">; linted as a finding (the strictest shape)")
    argued = kind in ("finding", "status", "architecture", "rca", "handoff")

    # — build: does it render on an intranet, in both themes? —
    head = html[:1500]
    missing_head = [n for n, rx, hay in (("<!doctype html> as the first line", _DOCTYPE, html),
                                         ("<meta charset>", _CHARSET, head),
                                         ("<meta name=viewport>", _VIEWPORT, head)) if not rx.search(hay)]
    if missing_head:
        add("head-standard", "FAIL", "head standard: " + "; ".join(missing_head) + " (doctype first, both metas in the first 1,500 bytes)")
    if p.ext:
        add("external-refs", "FAIL", f"{len(p.ext)} external script/stylesheet ref(s) — inline them; the intranet has no CDN: {p.ext[0]}")
    if re.search(r"@import\s+url\(\s*['\"]?https?://", css) or re.search(r"url\(\s*['\"]?https?://[^)]*\.(woff2?|ttf|otf)", css):
        add("external-font", "FAIL", "CSS pulls a remote font or stylesheet; inline it as a data: URI or use a local stack")
    if not p.title.strip():
        add("title-tag", "WARN", "no <title>; the hub and the browser tab name the page from it")
    elif len(_norm(p.title)) > 90:
        add("title-tag", "WARN", f"<title> is {len(_norm(p.title))} chars; a name, not a summary (≤ 90)")
    has_tokens = "--" in css and ":root" in css
    single_theme = "artifact:single-theme" in html
    if "prefers-color-scheme" not in css and not single_theme:
        add("theme", "WARN", "no prefers-color-scheme block and no <!--artifact:single-theme--> declaration; the viewer's dark mode will get light-mode colours")
    if not has_tokens and not single_theme:
        add("tokens", "WARN", "no :root custom properties; colours are literals scattered through components, so a theme cannot be changed in one place")
    literal_sites = len(re.findall(r"#[0-9a-fA-F]{3,6}\b", re.sub(r":root\s*\{[^}]*\}|\[data-theme[^{]*\{[^}]*\}|@media[^{]*\{[^{]*:root[^{]*\{[^}]*\}", "", css)))
    if has_tokens and literal_sites > 12:
        add("color-literals", "WARN" if literal_sites > 24 else "INFO", f"{literal_sites} hex literals outside the token blocks; components should read var(--…)")
    bare_fonts = [v.strip() for v in re.findall(r"font-family\s*:([^;}]+)", css)
                  if "," not in v and "var(" not in v and "inherit" not in v]
    if bare_fonts:
        add("font-fallback", "WARN", f"a font-family with no fallback stack ({bare_fonts[0][:40]!r}); an intranet page cannot fetch a face it names")
    if _PLACEHOLDER.search(text):
        add("placeholder", "FAIL", "placeholder text left in the visible page (lorem ipsum / TBD / TODO: / XXX / FIXME)")
    banned = _BANNED_COPY.search(text)
    if banned:
        add("copy", "WARN", f"marketing filler in the copy ({banned.group(0)!r}); say what happens, with a number")
    if words < 120 and p.script_bytes > 4000:
        add("js-required", "WARN", f"{words} visible words but {p.script_bytes // 1000} kB of script; a page that renders nothing without JavaScript has no text for search, summaries or a slow client")
    if len(html) > 5_000_000:
        add("size", "WARN", f"{len(html) / 1e6:.1f} MB page; inline data URIs and galleries belong in files beside index.html")

    # — structure: can a reader stop after the first screen? —
    if len(h1) == 0:
        add("h1", "FAIL" if kind != "landing" else "WARN", "no <h1>; a page with no headline cannot be skimmed, linked or summarised")
    elif len(h1) > 1:
        add("h1", "WARN", f"{len(h1)} <h1> elements; one page, one headline")
    if h1 and argued and not is_claim(h1[0]):
        add("title-claim", "WARN", f"headline is a topic label, not a finding: {h1[0][:80]!r}")
    if kind != "worklog" and kind != "landing":
        lead = [x for x in p.pars[:6] if x]
        deck = max(lead, key=lambda x: len(x.split()) + len(_CJK.findall(x)) // 2, default="")
        deck_len = len(deck.split()) + len(_CJK.findall(deck)) // 2
        total = sum(len(x.split()) + len(_CJK.findall(x)) // 2 for x in lead)
        if deck_len < 35 and total < 60 and not _DECK_HINT.search(" ".join(p.role_hints) + " " + all_heads[:400]):
            add("deck", "WARN", "no abstract under the headline (≥ 35 words: what was measured, on what, the two numbers that matter, what to do)")
        elif not re.search(r"\d", deck):
            add("deck-number", "INFO", "the abstract carries no number; a status without a figure is a mood")
    if kind != "landing" and not _ASOF.search(text[:1800]):
        add("as-of", "FAIL" if argued else "WARN", "no date in the first screen (an 'as of' or 'compiled' stamp); an undated report is wrong within a week and nobody can tell")
    if len(h2) < 3 and words > 600 and kind not in ("worklog", "landing"):
        add("sections", "WARN", f"{len(h2)} <h2> sections for {words} words; give the reader a skim path")
    if argued and h2:
        claims = [h for h in h2 if is_claim(h)]
        ratio = len(claims) / len(h2)
        labels = [h for h in h2 if not is_claim(h)]
        if ratio < 1 / 3:
            add("headings-claim", "WARN", f"{len(claims)}/{len(h2)} section headings state a finding; labels hide the point: {', '.join(x[:32] for x in labels[:4])}")
        else:
            add("headings-claim", "INFO", f"{len(claims)}/{len(h2)} section headings state a finding")
    if kind == "worklog":
        hl = all_heads.lower()
        missing = [w for w in _WORKLOG_HEADS if w not in hl]
        if missing:
            add("worklog-header", "WARN", f"work-log header missing {', '.join(missing)} (protocol: Goal · Now · Human TODO · Blockers, then a newest-first timeline)")
        if "timeline" not in hl and "时间线" not in all_heads and "工作记录" not in all_heads:
            add("worklog-timeline", "WARN", "no timeline section; the append-only trail is the point of a work-log")
    n_tables = p.tags["table"]
    n_figs = len([s for s in p.big_svgs]) + p.tags["img"] + p.tags["canvas"]
    if (n_figs >= 2 or n_tables >= 3) and not _KEY_TERMS.search(roles):
        add("key-terms", "WARN", "figures/tables but no key: a section that defines each named entity and metric (with its denominator) and fixes one colour per entity for the whole page")
    if argued and not _LIMITS.search(roles):
        add("limits", "WARN", "no limits section (what is not covered, not measured, or claimed); silence reads as 'everything is fine'")
    if kind in ("finding", "status", "rca", "handoff") and not _NEXT.search(roles):
        add("next", "WARN", "no next-step section; a report that forces no decision is a diary")
    if argued and not _SOURCES.search(roles):
        add("sources", "WARN", "no sources/evidence/reproduce section; every number needs a place it came from")
    if kind in ("finding", "status", "rca", "decision") and not _WHY.search(roles):
        add("why", "WARN", "no section explaining why the numbers look like this (the mechanism, and what was ruled out); a number without its cause is a rumour with a decimal point")
    if argued and not _METHOD.search(roles):
        add("method", "WARN", "no section saying what was done to find this out (what was read, run, compared, in order); a reader cannot weigh a result without its method")
    if argued and kind in ("finding", "status", "handoff") and not _FAILED.search(roles + " " + text[:4000]):
        add("failed-attempts", "INFO", "nothing about what was tried and did not work; a reader without that re-proposes it")
    if words > 2500 and p.anchors < 5:
        add("toc", "WARN", f"{words} words and no in-page navigation (≥ 5 #anchor links)")
    if words > 20000:
        add("length", "WARN", f"{words} words on one page; split by sub-problem, not by length, and keep the answer page short")

    # — numbers: does every rate carry its population? —
    pcts = 0
    bare = 0
    for block in p.blocks:
        hits = _PCT.findall(block)
        if not hits:
            continue
        pcts += len(hits)
        if not _COUNT_NEAR.search(block):
            bare += len(hits)
    if pcts >= 4:
        share = bare / pcts
        lvl = "WARN" if share > 0.6 else "INFO"
        add("denominators", lvl, f"{bare}/{pcts} percentages sit in a block with no count beside them (n=, x/y, or a total)")

    # — figures: publication quality? —
    if n_tables >= 6 and n_figs == 0:
        add("wall-of-tables", "WARN", f"{n_tables} tables and no figure; the one comparison the page turns on deserves a chart")
    elif n_figs == 0 and argued and words > 1500:
        add("no-figure", "INFO", "no figure; fine for a short note, but a finding usually has one picture that carries it")
    if p.figures_without_caption:
        add("figcaption", "WARN", f"{p.figures_without_caption} <figure> without <figcaption>; the caption states the takeaway, in one sentence")
    if p.imgs_outside_figure:
        add("img-figure", "INFO", f"{p.imgs_outside_figure} <img> outside <figure>; screenshots and plots want a caption too")
    unl = [s for s in p.big_svgs if not (s["labelled"] or s["titled"])]
    if unl:
        add("svg-aria", "WARN", f"{len(unl)}/{len(p.big_svgs)} charts have no role=\"img\" aria-label (or <title>); a reader without sight, and a summariser, get nothing")
    small = [min(s["fonts"]) for s in p.big_svgs if isinstance(s["fonts"], list) and s["fonts"] and min(s["fonts"]) < 10]  # type: ignore[type-var]
    if small:
        add("svg-text-size", "WARN", f"{len(small)} chart(s) with text under 10px at drawn scale (smallest {min(small):g}); tick labels must be legible in a screenshot")
    palette: set[str] = set()
    counted = [s for s in p.big_svgs if not s["ignore_palette"]]
    for s in counted:
        cs = s["colors"]
        assert isinstance(cs, set)
        palette |= {c for c in cs if not _GREY.match(c)}
    if len(palette) > 8:
        add("svg-palette", "WARN", f"{len(palette)} distinct chromatic colours across the page's charts; ≤ 8 categorical hues, assigned in fixed order, one meaning each (a palette swatch figure may carry data-artifact-lint=\"ignore-palette\")")
    if counted and "prefers-color-scheme" in css and not any(s["current"] for s in counted) and palette:
        add("svg-theme", "WARN", "charts use only literal colours while the page has a dark mode; text and axes should use currentColor / var(--ink) so they survive the theme")

    stats: dict[str, object] = {
        "type": kind, "words": words, "h1": len(h1), "h2": len(h2), "figures": n_figs,
        "svg": len(p.big_svgs), "tables": n_tables, "external": len(p.ext), "palette": sorted(palette),
        "title": _norm(p.title), "headline": h1[0] if h1 else "",
        "claim_ratio": (sum(is_claim(h) for h in h2) / len(h2)) if h2 else None,
    }
    return out, stats


# ─── Survey ──────────────────────────────────────────────────────────────────

_PREFIX = re.compile(r"^(person|declared):")

SURVEY_IDS = ("title-claim", "deck", "as-of", "headings-claim", "key-terms", "why", "method",
              "limits", "next", "sources", "wall-of-tables", "figcaption", "external-refs", "theme", "toc")


def survey(root: str, aliases: dict[str, str], min_n: int = 5) -> tuple[list[Row], str]:
    """Lint every <root>/<slug>/index.html that has a manifest.json; group by owner.

    A manifest's `owner` (falling back to `publisher`) names the group after
    stripping `person:` / `declared:`; `aliases` merges spellings. Work-logs
    (slug prefix `worklog-`) are linted as such and reported separately.
    """
    rows: list[Row] = []
    for slug in sorted(os.listdir(root)):
        mpath = os.path.join(root, slug, "manifest.json")
        if not os.path.isfile(mpath):
            continue
        try:
            with open(mpath, encoding="utf-8") as fh:
                man = json.load(fh)
        except (OSError, ValueError):
            continue
        page = os.path.join(root, slug, str(man.get("entry") or "index.html"))
        if not os.path.isfile(page):
            page = os.path.join(root, slug, "index.html")
        if not os.path.isfile(page):
            continue
        try:
            with open(page, encoding="utf-8", errors="replace") as fh:
                html = fh.read()
        except OSError:
            continue
        who = str(man.get("owner") or man.get("publisher") or "unknown")
        who = _PREFIX.sub("", who)
        who = aliases.get(who, who)
        kind = "worklog" if slug.startswith("worklog-") else None
        findings, stats = lint_html(html, declared_type=kind)
        cr = stats["claim_ratio"]
        rows.append(Row(slug=slug, group=who, kind=str(stats["type"]), words=int(str(stats["words"])),
                        date=str(man.get("published_at") or "")[:10],
                        fails=sorted(f for f, lvl, _ in findings if lvl == "FAIL"),
                        warns=sorted(f for f, lvl, _ in findings if lvl == "WARN"),
                        figures=int(str(stats["figures"])), claim_ratio=cr if isinstance(cr, float) else None))
    groups: dict[str, list[Row]] = collections.defaultdict(list)
    for r in rows:
        if r["kind"] != "worklog":
            groups[r["group"]].append(r)
    lines = [f"artifact-lint survey: {len(rows)} pages under {root} ({sum(1 for r in rows if r['kind'] == 'worklog')} work-logs excluded from the table)",
             "share of pages WITHOUT each finding (higher is better); n ≥ %d" % min_n, ""]
    head = f"{'group':14}{'n':>5}{'med words':>10}{'fig':>5}  " + "".join(f"{i[:10]:>11}" for i in SURVEY_IDS)
    lines.append(head)
    ordered = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    for who, rs in ordered:
        if len(rs) < min_n:
            continue
        med = statistics.median([r["words"] for r in rs])
        fig = 100 * sum(1 for r in rs if r["figures"] > 0) / len(rs)
        cells = []
        for fid in SURVEY_IDS:
            clean = sum(1 for r in rs if fid not in r["warns"] and fid not in r["fails"])
            cells.append(f"{100 * clean / len(rs):10.0f}%")
        lines.append(f"{who[:14]:14}{len(rs):5d}{med:10.0f}{fig:4.0f}%  " + "".join(cells))
    return rows, "\n".join(lines)


# ─── Self-test ───────────────────────────────────────────────────────────────

_GOOD = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<meta name="artifact-type" content="finding">
<title>v9 learned the pipeline</title>
<style>:root{--ink:#0a0a0a;--bg:#fff;--a:#0072b2}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--ink:#eee;--bg:#111}}
body{font-family:Menlo,monospace;color:var(--ink);background:var(--bg)}</style></head>
<body><nav><a href="#a">a</a><a href="#b">b</a><a href="#c">c</a><a href="#d">d</a><a href="#e">e</a></nav>
<h1>v9 learned the pipeline, not the tampering.</h1>
<p>Compiled 2026-09-23. An independent re-score of the v9 model on the held-out set of 24 frauds
and 474 controls reproduces the 0.983 AUC exactly, and at the 1% operating point it flags 0 of 24;
on the 31,903-row test split it is the same model as its control. Judge it where it ships.</p>
<h2 id="a">Ranking inside the set is not detection at the threshold.</h2>
<p>Recall 30.9% of 12,152 forgeries at 1% real-clean FPR (n=1,921), against 33.4% for v8.</p>
<figure><svg viewBox="0 0 600 200" role="img" aria-label="per-arm score ranges"><text font-size="11" fill="currentColor">x</text><rect fill="#0072b2"><title>a tooltip, not the page title</title></rect></svg>
<figcaption>Every fraud scores below the model's threshold.</figcaption></figure>
<h2>Colour key and terms</h2><p>Solid chips are models; tinted chips are datasets.</p>
<h2 id="b">Why the AUC went up anyway</h2><p>The set is self-made; 54 of 54 originals share one producer.</p>
<h2>Limitations and claims we do not make</h2><p>Not tested on scans.</p>
<h2 id="next">Judge it where it ships.</h2><p>Score on the customer's real fraud set, owner named, by 2026-09-30.</p>
<h2 id="method">How this was measured</h2><p>Re-scored with the sweep harness, five seeds, the same split.</p>
<h2>Sources and reproduction</h2><p>runs/v9/, seed 0-4.</p>
</body></html>"""

_BAD = """<html><head><title>Model Update</title>
<link rel="stylesheet" href="https://cdn.example.com/x.css">
<style>body{color:#333;font-family:Inter}</style></head><body>
<h1>Model Update</h1><h1>Again</h1>
<p>Short.</p>
<h2>Overview</h2><p>Recall is 45% and precision 90%.</p>
<h2>Results</h2><table></table><table></table><table></table><table></table><table></table><table></table>
<figure><svg viewBox="0 0 600 200"><text font-size="7">x</text>
<rect fill="#ff0000"/><rect fill="#00ff00"/><rect fill="#0000ff"/><rect fill="#ffff00"/><rect fill="#ff00ff"/>
<rect fill="#00ffff"/><rect fill="#ff8800"/><rect fill="#8800ff"/><rect fill="#0088ff"/></svg></figure>
<p>We will seamlessly revolutionize detection. TBD.</p>
</body></html>"""

_WORKLOG = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="w">
<meta name="artifact-type" content="worklog"><title>Worklog: x</title>
<style>:root{--a:#000}@media (prefers-color-scheme: dark){:root{--a:#fff}}body{font-family:a,b}</style></head><body>
<h1>Worklog: x</h1><p>Updated 2026-09-23</p><h2>Goal</h2><p>g</p><h2>Now</h2><p>n</p><h2>Human TODO</h2><ul><li>a</li></ul>
<h2>Blockers</h2><p>none</p><h2>Timeline · newest first</h2><ul><li>10:00 — did</li></ul></body></html>"""


def _self_test() -> int:
    failures: list[str] = []

    def expect(cond: bool, msg: str) -> None:
        if not cond:
            failures.append(msg)

    good, gstats = lint_html(_GOOD)
    gids = {f for f, lvl, _ in good if lvl != "INFO"}
    expect(not gids, f"good page should have no WARN/FAIL, got {sorted(gids)}")
    expect(gstats["type"] == "finding", "declared type is read from <meta artifact-type>")
    cr = gstats["claim_ratio"]
    expect(isinstance(cr, float) and cr >= 0.5, "claim ratio counts claim headings")
    expect(gstats["title"] == "v9 learned the pipeline", f"an SVG <title> tooltip must not pollute the page title, got {gstats['title']!r}")
    no_id = _GOOD.replace('<h2 id="next">', "<h2>")
    expect(any(f == "next" for f, _, _ in lint_html(no_id)[0]), "a claim heading with no role id is not recognised as the next step (so the id is what carries the role)")

    bad, bstats = lint_html(_BAD)
    bids = {f: lvl for f, lvl, _ in bad}
    for fid, lvl in (("head-standard", "FAIL"), ("external-refs", "FAIL"), ("placeholder", "FAIL"),
                     ("as-of", "FAIL"), ("h1", "WARN"), ("title-claim", "WARN"), ("deck", "WARN"),
                     ("headings-claim", "WARN"), ("key-terms", "WARN"), ("limits", "WARN"),
                     ("next", "WARN"), ("sources", "WARN"), ("why", "WARN"), ("method", "WARN"),
                     ("theme", "WARN"), ("tokens", "WARN"),
                     ("font-fallback", "WARN"), ("copy", "WARN"), ("figcaption", "WARN"),
                     ("svg-aria", "WARN"), ("svg-text-size", "WARN"), ("svg-palette", "WARN"),
                     ("type-undeclared", "INFO")):
        expect(bids.get(fid) == lvl, f"bad page should carry {fid}={lvl}, got {bids.get(fid)}")
    swatch = _BAD.replace('<figure><svg viewBox="0 0 600 200">', '<figure><svg viewBox="0 0 600 200" data-artifact-lint="ignore-palette">')
    sids = {f for f, _, _ in lint_html(swatch)[0]}
    expect("svg-palette" not in sids, "a figure marked ignore-palette is left out of the palette count")
    expect("svg-text-size" in sids, "the opt-out covers colours only, not the other figure checks")
    tables_only = re.sub(r"<figure>.*?</figure>", "", _BAD, flags=re.S)
    tids = {f: lvl for f, lvl, _ in lint_html(tables_only)[0]}
    expect(tids.get("wall-of-tables") == "WARN", "six tables and no figure is a wall of tables")
    expect("figcaption" not in tids and "svg-palette" not in tids, "figure checks stay silent with no figure")
    expect("denominators" not in bids or bids["denominators"] == "WARN", "bare percentages are reported")

    # the heading heuristic itself, both languages
    expect(is_claim("Why recall is stuck at about a quarter"), "English claim heading")
    expect(is_claim("Checked, not assumed"), "short English claim with a marker")
    expect(not is_claim("Sources"), "single-word label")
    expect(not is_claim("The plan in five steps"), "noun phrase without a marker is a label")
    expect(is_claim("为什么 V1 V2 那两行不能按字面读"), "Chinese claim heading")
    expect(not is_claim("验证范围"), "Chinese two-character label")
    expect(not is_claim("先看结论"), "Chinese label without a claim particle")

    wl, wstats = lint_html(_WORKLOG)
    wids = {f for f, lvl, _ in wl if lvl != "INFO"}
    expect(not wids, f"protocol-shaped work-log passes, got {sorted(wids)}")
    broken = _WORKLOG.replace("<h2>Blockers</h2><p>none</p>", "")
    wl2, _ = lint_html(broken)
    expect(any(f == "worklog-header" for f, _, _ in wl2), "a work-log missing Blockers is flagged")

    # a stack held in a custom property is a stack
    tok = _GOOD.replace("body{font-family:Menlo,monospace;", "body{font-family:var(--mono);").replace(":root{--ink:#0a0a0a;", ":root{--mono:Menlo,monospace;--ink:#0a0a0a;")
    expect("font-fallback" not in {f for f, _, _ in lint_html(tok)[0]}, "font-family: var(--stack) is not a bare face")
    # a single-theme declaration silences the theme checks, and only those
    st = _GOOD.replace("@media (prefers-color-scheme: dark){:root:not([data-theme=\"light\"]){--ink:#eee;--bg:#111}}", "<!--artifact:single-theme-->")
    st = st.replace("</style></head>", "</style><!--artifact:single-theme--></head>")
    st_f, _ = lint_html(st)
    expect("theme" not in {f for f, _, _ in st_f}, "single-theme declaration is honoured")

    # survey grouping on a temp hub
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        for i, (who, html) in enumerate((("person:jane-doe", _GOOD), ("jdoe", _BAD), ("kim", _BAD), ("kim", _GOOD), ("x", _WORKLOG))):
            d = os.path.join(tmp, f"worklog-{i}" if html is _WORKLOG else f"p{i}")
            os.makedirs(d)
            with open(os.path.join(d, "index.html"), "w", encoding="utf-8") as fh:
                fh.write(html)
            with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as fh:
                json.dump({"owner": who, "published_at": "2026-09-23T00:00:00Z"}, fh)
        rows, table = survey(tmp, {"jane-doe": "jane"}, min_n=1)
        expect(len(rows) == 5, f"survey lints every page, got {len(rows)}")
        expect(sum(1 for r in rows if r["group"] == "jane") == 1, "owner prefix is stripped and aliased")
        expect(any(r["kind"] == "worklog" for r in rows), "worklog- slugs are linted as work-logs")
        expect("kim" in table and "jane" in table, "survey table lists every group")

    if failures:
        print("artifact-lint --self-test: FAIL")
        for f in failures:
            print("  -", f)
        return 1
    print("artifact-lint --self-test: PASSED (good page clean, bad page carries 24 findings, heuristics fire in both languages, survey groups)")
    return 0


# ─── CLI ─────────────────────────────────────────────────────────────────────

def _print(path: str, findings: Iterable[Finding], stats: dict[str, object], quiet: bool) -> None:
    fl = list(findings)
    n = collections.Counter(lvl for _, lvl, _ in fl)
    print(f"{path}: {stats['type']} · {stats['words']} words · {stats['h2']} sections · {stats['figures']} figures · {stats['tables']} tables"
          f" — {n['FAIL']} FAIL, {n['WARN']} WARN, {n['INFO']} INFO")
    for fid, lvl, msg in sorted(fl, key=lambda f: ({"FAIL": 0, "WARN": 1, "INFO": 2}[f[1]], f[0])):
        if quiet and lvl == "INFO":
            continue
        print(f"  {lvl:4} {fid:18} {msg}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="*", help="HTML file(s) to lint")
    ap.add_argument("--type", choices=TYPES, help="override the page's declared artifact-type")
    ap.add_argument("--strict", action="store_true", help="exit 1 on WARN as well as FAIL")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--quiet", action="store_true", help="hide INFO lines")
    ap.add_argument("--survey", metavar="DIR", help="lint every DIR/<slug>/index.html with a manifest.json and tabulate by owner")
    ap.add_argument("--alias", action="append", default=[], metavar="FROM=TO", help="merge an owner spelling into another (survey)")
    ap.add_argument("--min-n", type=int, default=5, help="survey: hide groups with fewer pages")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)

    if args.self_test:
        return _self_test()
    if args.survey:
        aliases = dict(a.split("=", 1) for a in args.alias if "=" in a)
        rows, table = survey(args.survey, aliases, args.min_n)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False))
        else:
            print(table)
        return 0
    if not args.paths:
        ap.error("give at least one HTML file, --survey DIR, or --self-test")
    worst = 0
    report: list[dict[str, object]] = []
    for path in args.paths:
        with open(path, encoding="utf-8", errors="replace") as fh:
            html = fh.read()
        findings, stats = lint_html(html, declared_type=args.type)
        if any(lvl == "FAIL" for _, lvl, _ in findings) or (args.strict and any(lvl == "WARN" for _, lvl, _ in findings)):
            worst = 1
        if args.json:
            report.append({"path": path, "stats": stats, "findings": [{"id": f, "level": lvl, "message": m} for f, lvl, m in findings]})
        else:
            _print(path, findings, stats, args.quiet)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    return worst


if __name__ == "__main__":
    sys.exit(main())
