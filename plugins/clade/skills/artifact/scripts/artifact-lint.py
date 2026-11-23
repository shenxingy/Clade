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

The `lead` check came later. Measured on 2026-11-22 over 54 recent pages on
one internal artifact hub, judged by two independent reviewers from phone and
desktop screenshots: both passed 1 of 54. A page can carry every section above
and still bury what its owner must do or decide under a byline, a contents bar
and a row of number tiles; `lead` asks for that block first (section "Lead").

Levels: FAIL blocks publishing (a page that cannot be read or does not render
on the intranet, or whose owner cannot find the lead: what they must do or
decide); WARN needs a fix or a written reason; INFO is a measurement.
The page declares its type with `<meta name="artifact-type" content="...">`
— finding | status | architecture | rca | handoff | decision | reference | worklog |
landing — and the checks that only make sense for an argued page (claim
headings, next step, why) relax for a reference register or a work-log. The
limits check does not relax: a register is exactly where a reader turns "not
listed" into "does not exist", so it owes a line on what it does not cover.
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

TYPES = ("finding", "status", "architecture", "rca", "handoff", "decision",
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
_WORKLOG_HEADS = ("human todo", "blockers", "now", "goal")
_GREY = re.compile(r"^#(?:([0-9a-f])\1\1|([0-9a-f]{2})\2\2)$", re.I)
_DOCTYPE = re.compile(r"^\s*<!doctype html>", re.I)
_CHARSET = re.compile(r"<meta\s+charset", re.I)
_VIEWPORT = re.compile(r"<meta\s+name=[\"']?viewport", re.I)
_DECK_HINT = re.compile(r"deck|lede|abstract|summary|tldr|tl;dr|short version|一句话|先看结论|摘要", re.I)


# ─── Lead ────────────────────────────────────────────────────────────────────
# The first block under the headline is the lead, `id="bottom-line"`: the
# bottom line in one or two sentences, then what the owner must do or decide
# ("Needs you: … by <date>", or "Nothing needed from you."), then any blocker
# they must know now. Only an eyebrow, the headline and one short as-of line
# may sit above it. Provenance, version notes, contents, terms, goals, methods
# and number tiles go below it; provenance and version history go to the foot.
#
# Measured 2026-11-22 on 54 recent pages of one internal artifact hub, judged
# by two independent reviewers from phone (390x844) and desktop screenshots:
# both passed 1 of 54. One reviewer found the owner's ask on the phone's first
# screen in 14 of 54 and below the fold or nowhere in 27 of 54. What most often
# sat between the headline and the lead: a byline or provenance line, a deck
# without the ask, number tiles, a method, a goal, a contents bar.
#
# The check is a necessary condition — markup and position — not a judge of
# the words: on those 54 pages 4 place an anchor within the budget and 1 passes
# cleanly. The first-screen review in the artifact skill's references/review.md
# judges the content. The constants below are copied verbatim from a shared
# spec that a second implementation copies too; change both or neither.

# A phone shows about this much text under a two-line headline: ~100 English
# words or ~200 Chinese characters (a CJK character counts half a unit).
LEAD_BUDGET = 100
LEAD_WINDOW = 120
LEAD_IDS = frozenset({"bottom-line", "needs-you", "next", "ask", "asks", "decision", "decisions",
                      "bluf", "tldr", "tl-dr"})
_LEAD_LABEL = (r"bottom line|bluf|tl;?dr|needs you|what you need to (?:know|do|decide)"
               r"|your (?:call|decision|move)|decisions? (?:needed|owed|for you)|next steps?"
               r"|human todo|nothing (?:is )?needed from you"
               r"|结论|要你|需要你|你要做|你需要|待你|下一步|请你")
_LEAD_HEAD = re.compile(r"^\s*(?:\d+\s*[·.、]?\s*)?(?:" + _LEAD_LABEL + r")", re.I)
_LEAD_LABEL_RE = re.compile(r"^\s*(?:" + _LEAD_LABEL + r")\s*[:：]", re.I)
_ASK = re.compile(
    r"\b(?:you|your)\b[^.?!。？！\n]{0,60}?\b(?:need to|must|have to|decide|approve|review|sign|confirm"
    r"|choose|pick|merge|reply|vote)\b"
    r"|\bneeds? you\b|\byour (?:call|decision|approval|sign-?off|vote)\b|\bdecisions? (?:needed|owed|for you)\b"
    r"|\bdecide by\b|\baction (?:needed|required)\b"
    r"|\bnothing (?:is )?(?:needed|required) (?:from|of) you\b|\bno action (?:is )?(?:needed|required)\b"
    r"|\bnothing for you to do\b"
    r"|要你|需要你|请你|你来(?:定|决定|拍板)|你(?:决定|确认|拍板|审批|批准|选|签字|投票)|等你|不需要你|无需你"
    r"|你只需|你要做|你需要", re.I)
_LEAD_NAVLIKE = re.compile(r"(?:^|\s)(?:toc|contents|reading-contents|tour|modal)(?:\s|$)", re.I)
_WL_TODO = re.compile(r"^(?:\d+\s*[·.、]?\s*)?(?:human todo|needs you|需要你|要你)", re.I)
_WL_GOAL_NOW = re.compile(r"^(?:\d+\s*[·.、]?\s*)?(?:goal|now|目标|现在|当前)\b", re.I)

# Hidden text is not counted and carries no anchors.
_LEAD_HIDDEN_TAGS = frozenset({"script", "style", "svg", "noscript", "template", "dialog", "nav", "aside"})
# A void element has no end tag, so pushing one would leave it open for good.
_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"})
# A label anchor is the first text inside one of these, outside a heading.
_LEAD_BLOCKS = frozenset({"p", "li", "dt", "dd", "div", "section", "td", "th", "blockquote", "header",
                          "article", "strong", "b"})
_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
# End tags HTML lets an author omit. A start tag in "closed by" ends the nearest
# open element of that kind first, as a browser does, unless a "scope" element
# was opened after it — so an unclosed <p class="toc"> or <li aria-hidden="true">
# hides itself, not every block after it. (kind, closed by, scope)
# The p row's "closed by" is the HTML standard's list of start tags that close
# a <p>; the scopes are the nesting a page actually has (a button in a
# paragraph, a list in a list item, a table in a cell). The second
# implementation of the lead check ends omitted tags with this same table.
_IMPLIED_END = (
    (frozenset({"p"}),
     frozenset({"address", "article", "aside", "blockquote", "details", "dialog", "div", "dl",
                "dd", "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2",
                "h3", "h4", "h5", "h6", "header", "hgroup", "hr", "li", "main", "menu", "nav",
                "ol", "p", "pre", "section", "table", "ul"}),
     frozenset({"button"})),
    (frozenset({"li"}), frozenset({"li"}), frozenset({"ol", "ul"})),
    (frozenset({"dt", "dd"}), frozenset({"dt", "dd"}), frozenset({"dl"})),
    (frozenset({"td", "th"}), frozenset({"td", "th"}), frozenset({"table"})),
    (frozenset({"tr"}), frozenset({"tr"}), frozenset({"table"})),
)
_NO_OPEN = (-1,) * len(_IMPLIED_END)   # no element of any kind open


def units(s: str) -> float:
    """Words, with a CJK character counting half: the measure of a phone screen."""
    return len(_CJK.sub(" ", s).split()) + len(_CJK.findall(s)) / 2


# One unit of units(): a CJK character (half) or a run of other non-space characters (one).
_UNIT_TOKEN = re.compile(rf"{_CJK.pattern}|(?:(?!{_CJK.pattern})\S)+")


def _cut_units(s: str, n: float) -> str:
    """The longest prefix of `s` holding at most `n` units, cut at a unit boundary."""
    used, end = 0.0, 0
    for m in _UNIT_TOKEN.finditer(s):
        used += 0.5 if _CJK.fullmatch(m.group()) else 1
        if used > n:
            break
        end = m.end()
    return s[:end]


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
        # the lead: visible text only, measured in units() from the top. Each open
        # element carries its ancestors' state — (tag, hidden, inside a heading,
        # the nearest open element of each _IMPLIED_END kind, inside an element
        # carrying a LEAD_IDS token) — so nothing walks the stack: a page that
        # omits every </p> stays linear. Void tags never push.
        self._lstack: list[tuple[str, bool, bool, tuple[int, ...], bool]] = []
        self._lopen: collections.Counter[str] = collections.Counter()   # open elements per tag name
        self.lead_units = 0.0
        self.h1_end: float | None = None             # units at the end of the first visible <h1>
        self.h1_text = ""
        self._in_h1 = False
        self._lhead: tuple[str, float, int] | None = None  # the open heading: (tag, start, stack index)
        self._lhead_text = ""                        # and its text so far
        self._fresh: int | None = None               # stack index of a block opened with no text yet
        self.lead_heads: list[tuple[str, str, float]] = []     # visible h2-h4: (tag, text, start)
        self.lead_anchors: list[tuple[float, str, str]] = []   # (start, kind, what)
        self.lead_text: list[tuple[float, str]] = []           # visible text nodes: (start, text)
        self.par_lead: list[bool] = []       # per entry of pars: the <p> sits inside a LEAD_IDS element
        self._par_lead = False

    # lead ---------------------------------------------------------------
    def _lead_hidden(self) -> bool:
        return bool(self._lstack) and self._lstack[-1][1]

    def _in_heading(self) -> bool:
        return bool(self._lstack) and self._lstack[-1][2]

    def _lead_implied_end(self, tag: str) -> None:
        """Close what this start tag closes without an end tag (_IMPLIED_END)."""
        near = self._lstack[-1][3] if self._lstack else _NO_OPEN
        cut = min((i for i, (_, closers, _) in zip(near, _IMPLIED_END) if i >= 0 and tag in closers), default=-1)
        if cut >= 0:
            self._lead_pop_to(cut)

    def _lead_start(self, tag: str, a: dict[str, str]) -> None:
        self._lead_implied_end(tag)  # before the void check: <hr> ends a <p>
        if tag in _VOID:
            return  # no end tag will ever pop it
        toks = {t.lower().replace("_", "-") for t in (a.get("id", "") + " " + a.get("class", "") + " " + a.get("data-role", "")).split()}
        hidden = (self._lead_hidden() or tag in _LEAD_HIDDEN_TAGS or a.get("role", "").lower() == "navigation"
                  or "hidden" in a or a.get("aria-hidden", "").lower() == "true"
                  or bool(_LEAD_NAVLIKE.search(" ".join(sorted(toks)))))
        here = len(self._lstack)
        near = tuple(here if tag in kind else (-1 if tag in scope else n)
                     for n, (kind, _, scope) in zip(self._lstack[-1][3] if self._lstack else _NO_OPEN, _IMPLIED_END))
        in_lead = (bool(self._lstack) and self._lstack[-1][4]) or bool(toks & LEAD_IDS)
        self._lstack.append((tag, hidden, self._in_heading() or tag in _HEADINGS, near, in_lead))
        self._lopen[tag] += 1
        if hidden:
            return  # hidden elements carry no anchors
        if toks & LEAD_IDS:
            self.lead_anchors.append((self.lead_units, "role", " ".join(sorted(toks & LEAD_IDS))))
        if tag in ("h1", "h2", "h3", "h4"):
            if tag == "h1" and self.h1_end is None:
                self._in_h1 = True
            self._lhead, self._lhead_text = (tag, self.lead_units, here), ""
        elif tag in _LEAD_BLOCKS:
            self._fresh = here

    def _lead_close_heading(self) -> None:
        if self._in_h1:
            self._in_h1 = False
            self.h1_end = self.lead_units
        if self._lhead is None:
            return
        tag, start, _ = self._lhead
        text = _norm(self._lhead_text)
        self._lhead = None
        if tag != "h1":
            self.lead_heads.append((tag, text, start))
            if _LEAD_HEAD.search(text):
                self.lead_anchors.append((start, "head", text))

    def _lead_end(self, tag: str) -> None:
        # void, stray or already closed: changes nothing, and costs nothing —
        # otherwise each stray end tag would search the whole stack in vain
        if not self._lopen[tag]:
            return
        # pop back to the nearest open element of this name, so an unclosed
        # <p> or <li> inside it closes with it
        i = len(self._lstack) - 1
        while self._lstack[i][0] != tag:
            i -= 1
        self._lead_pop_to(i)

    def _lead_pop_to(self, i: int) -> None:
        """Close the element at stack index i and everything opened inside it."""
        for entry in self._lstack[i:]:   # paid for once, by the push
            self._lopen[entry[0]] -= 1
        del self._lstack[i:]
        if self._lhead is not None and self._lhead[2] >= i:
            self._lead_close_heading()   # the open heading was among them
        if self._fresh is not None and self._fresh >= i:
            self._fresh = None           # the block closed with no text: what follows is not inside it

    def _lead_data(self, data: str) -> None:
        if self._lead_hidden():
            return  # hidden text is not counted
        data = data.replace("\u00a0", " ")  # `Bottom&nbsp;line:` is a label
        # a heading's text keeps the spaces between its inline elements
        if self._lhead is not None:
            self._lhead_text += data
        if self._in_h1:
            self.h1_text += data
        if not data.strip():
            return  # whitespace between tags is never a block's first text
        if self._fresh is not None and not self._in_heading() and _LEAD_LABEL_RE.search(data):
            self.lead_anchors.append((self.lead_units, "label", _norm(data)))
        self._fresh = None
        self.lead_text.append((self.lead_units, data))
        self.lead_units += units(data)

    # tags ---------------------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        self._lead_start(tag, a)
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
            self._par_lead = bool(self._lstack) and self._lstack[-1][4]
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
        self._lead_end(tag)
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
            self.par_lead.append(self._par_lead)
        if tag in ("p", "li", "td", "th", "figcaption", "dd", "dt", "caption") and self._block:
            piece = self._block.pop().strip()
            if tag in ("td", "th", "caption") and self._tables:
                self._tables[-1] += " " + piece      # a rate's count usually sits in another cell
            else:
                self.blocks.append(piece)

    def handle_data(self, data: str) -> None:
        self._lead_data(data)
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


# A page longer than this needs an index that follows the reader. 6,000 words
# is the top 9% of one company hub (97 of 1,065 pages, measured 2026-09-24);
# below it a reader can hold the shape of the page in their head.
_LONG_PAGE = 6000

_LEAD_FIX = ("put a #bottom-line block (Bottom line + Needs you / 结论 + 需要你) directly under the headline "
             "and move provenance, version notes, contents, terms, goals and tiles below it")


def _lead_window(p: _Page, start: float) -> str:
    """The visible text from the anchor up to anchor + LEAD_WINDOW units.

    Whole text nodes while they fit, then the last one cut at a unit boundary,
    so an ask 200 units down the same paragraph is outside the window.
    """
    end = start + LEAD_WINDOW
    parts: list[str] = []
    for u, d in p.lead_text:
        if u < start:
            continue  # text above the anchor is not the lead's
        if u >= end:
            break
        parts.append(_cut_units(d, end - u))
    return _norm(" ".join(parts))


def _anchor_asks(a: tuple[float, str, str]) -> bool:
    """The anchor itself is the ask: a needs-you role, or a Needs you / Human TODO label or heading."""
    if a[1] == "role":
        return "needs-you" in a[2].split()
    if a[1] in ("label", "head"):
        return bool(re.search(r"needs you|human todo|需要你|要你", a[2], re.I))
    return False


def lead_findings(p: _Page, kind: str) -> list[Finding]:
    """The lead check: is the owner's block first under the headline, and does it ask?

    `lead` (FAIL) when no lead anchor sits within LEAD_BUDGET units of the end of
    the first <h1>, or when a work-log puts Goal or Now before Human TODO — one
    `lead` per page, the order problem first. `lead-ask` (WARN) when the lead is
    in place but says nothing the owner must do or decide.
    """
    out: list[Finding] = []
    h1_end = p.h1_end if p.h1_end is not None else 0.0
    h1_text = _norm(p.h1_text)
    # The lead is the anchor that starts first. A heading's anchor is recorded
    # when it closes, after any role element inside it, so the parser's order is
    # not document order: sort by where each element starts. sorted() is stable,
    # and a tie is settled below by asking whether ANY anchor at that place asks.
    after = sorted((a for a in p.lead_anchors if a[0] >= h1_end), key=lambda a: a[0])
    anchor: tuple[float, str, str] | None
    if _ASK.search(h1_text):
        anchor = (h1_end, "h1", h1_text)  # the headline itself carries the ask
    else:
        anchor = after[0] if after else None
    pos = anchor[0] - h1_end if anchor is not None else None
    within = pos is not None and pos <= LEAD_BUDGET

    order = ""
    if kind == "worklog":
        heads = [h.lower() for _, h, _ in p.lead_heads]
        todo = next((i for i, h in enumerate(heads) if _WL_TODO.search(h)), None)
        goal_now = next((i for i, h in enumerate(heads) if _WL_GOAL_NOW.search(h)), None)
        if todo is not None and goal_now is not None and goal_now < todo:
            order = "Goal" if re.match(r"^(?:\d+\s*[·.、]?\s*)?(?:goal|目标)", heads[goal_now]) else "Now"
    if order:
        out.append(("lead", "FAIL", f"work-log header puts {order} before Human TODO; "
                                    "the order is Human TODO · Blockers · Now · Goal"))
    elif not within:
        shown = _norm(" ".join(d for u, d in p.lead_text if u >= h1_end))[:60]
        where = "none" if pos is None else f"{pos:g} units below the headline (budget {LEAD_BUDGET})"
        out.append(("lead", "FAIL", f"the lead (bottom line + what the owner must do or decide) is at: {where}; "
                                    f"first after the h1: {shown!r} — {_LEAD_FIX}"))

    if within and anchor is not None:
        window = h1_text + " " + _lead_window(p, anchor[0])
        asks = bool(_ASK.search(window))
        # anchors that start where the lead starts are all the lead:
        # <h2 id="next">Human TODO</h2> asks through its heading, not its id
        tied = [a for a in after if a[0] == anchor[0]]
        asks = asks or any(_anchor_asks(a) for a in tied)
        if not asks:
            out.append(("lead-ask", "WARN", "the lead states no ask; say what the owner must do or decide, "
                                            "or \"Nothing needed from you.\" / 「不需要你做什么。」"))
    return out


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
    argued = kind in ("finding", "status", "architecture", "rca", "handoff", "decision")

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
        # the deck sits under the lead: the lead's own paragraphs (inside a
        # LEAD_IDS element, or opening with a lead label) are not the deck and
        # do not use up the six places it is looked for in
        under = [x for x, in_lead in zip(p.pars, p.par_lead)
                 if x and not in_lead and not _LEAD_LABEL_RE.search(x.replace("\u00a0", " "))]
        first = under[:6]
        deck = max(first, key=lambda x: len(x.split()) + len(_CJK.findall(x)) // 2, default="")
        deck_len = len(deck.split()) + len(_CJK.findall(deck)) // 2
        total = sum(len(x.split()) + len(_CJK.findall(x)) // 2 for x in first)
        if deck_len < 35 and total < 60 and not _DECK_HINT.search(" ".join(p.role_hints) + " " + all_heads[:400]):
            add("deck", "WARN", "no abstract under the lead (≥ 35 words: subject, the conclusion's key evidence and its reach)")
        elif not re.search(r"\d", deck):
            add("deck-number", "INFO", "the abstract carries no number; check whether quantitative evidence is relevant to the reader question")
    if argued or kind == "worklog":
        out.extend(lead_findings(p, kind))
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
            add("worklog-header", "WARN", f"work-log header missing {', '.join(missing)} (protocol: Human TODO · Blockers · Now · Goal, then a newest-first timeline)")
        if "timeline" not in hl and "时间线" not in all_heads and "工作记录" not in all_heads:
            add("worklog-timeline", "WARN", "no timeline section; the append-only trail is the point of a work-log")
    n_tables = p.tags["table"]
    n_figs = len([s for s in p.big_svgs]) + p.tags["img"] + p.tags["canvas"]
    if (n_figs >= 2 or n_tables >= 3) and not _KEY_TERMS.search(roles):
        add("key-terms", "WARN", "figures/tables but no key: a section that defines each named entity and metric (with its denominator) and fixes one colour per entity for the whole page")
    if (argued or kind == "reference") and not _LIMITS.search(roles):
        add("limits", "WARN", "no limits section (what is not covered, not measured, or claimed); "
                              "silence reads as 'everything is fine', and in a register as 'does not exist'")
    if kind in ("finding", "status", "rca", "handoff", "decision") and not _NEXT.search(roles):
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
    if words > _LONG_PAGE and p.anchors >= 5:
        pinned = bool(re.search(r"position\s*:\s*(?:sticky|fixed)", css, re.I))
        follows = bool(re.search(r"IntersectionObserver|aria-current|scroll-?spy|:target", html, re.I))
        if not (pinned and follows):
            lack = "is not pinned" if not pinned else "never marks the current section"
            add("nav-position", "WARN",
                f"{words} words and the section index {lack}; a reader two thirds down a page this "
                "long cannot tell where they are or what is left — pin it (position: sticky) and mark "
                "the current section (IntersectionObserver + aria-current), or split the page")
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

SURVEY_IDS = ("lead", "title-claim", "deck", "as-of", "headings-claim", "key-terms", "why", "method",
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
<p>Compiled 2026-09-23.</p>
<section id="bottom-line"><p><strong>Bottom line:</strong> an independent re-score of the v9 model on the held-out
set of 24 frauds and 474 controls reproduces the 0.983 AUC exactly, and at the 1% operating point it flags
0 of 24; on the 31,903-row test split it is the same model as its control.</p>
<p><strong>Needs you:</strong> approve scoring it on the customer's real fraud set by 2026-09-30.</p></section>
<p>The v9 document-fraud model, re-scored on 24 held-out frauds and 474 controls: its 0.983 AUC comes from
ranking the pipeline's artefacts, not the tampering, and at the 1% operating point it catches none of the 24.
That holds for this self-made set only; the customer's real fraud has not been scored.</p>
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
<h1>Worklog: x</h1><p>Updated 2026-09-23</p><h2>Human TODO</h2><ul><li>a</li></ul><h2>Blockers</h2><p>none</p>
<h2>Now</h2><p>n</p><h2>Goal</h2><p>g</p><h2>Timeline · newest first</h2><ul><li>10:00 — did</li></ul></body></html>"""

# the lead, as the artifact skill teaches it: bottom line, then what the owner must do
_LEAD_OK = ('<section id="bottom-line"><p><strong>Bottom line:</strong> the parser is fixed.</p>'
            '<p><strong>Needs you:</strong> approve the release by 2026-11-25.</p></section>')


def _lead_page(between: str, lead: str = _LEAD_OK, *, h1: str = "The parser is fixed and ships on Friday.",
               kind: str = "finding") -> str:
    """A minimal page: headline, then `between`, then `lead`, then a body section."""
    return ('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="w">'
            f'<meta name="artifact-type" content="{kind}"><title>x</title></head><body>'
            f"<h1>{h1}</h1>{between}{lead}<h2>Evidence</h2><p>Body text.</p></body></html>")


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
                     ("lead", "FAIL"), ("type-undeclared", "INFO")):
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

    # — the lead: the owner's block first under the headline, and it asks —
    def lead_of(html: str) -> list[tuple[str, str]]:
        return [(f, m) for f, _, m in lint_html(html)[0] if f in ("lead", "lead-ask")]

    def prose(n: int) -> str:
        return "<p>" + " ".join(["byline"] * n) + "</p>"   # exactly n units

    asof = "<p>As of 2026-11-22.</p>"
    expect(lead_of(_lead_page(asof)) == [], f"a lead block under the headline is clean, got {lead_of(_lead_page(asof))}")
    bare = _lead_page(asof, _LEAD_OK.replace("<p><strong>Needs you:</strong> approve the release by 2026-11-25.</p>", ""))
    expect([f for f, _ in lead_of(bare)] == ["lead-ask"], f"a lead with no ask and no Needs-you label warns, got {lead_of(bare)}")
    expect(lead_of(_lead_page(prose(150), "", h1="解析器修好了，周五发布，要你拍板。")) == [],
           "a headline that carries the ask is the lead, with no block under it")
    far = lead_of(_lead_page(prose(150)))
    expect([f for f, _ in far] == ["lead"] and "150 units" in far[0][1] and "byline" in far[0][1],
           f"150 units of byline between the headline and the lead fail, naming the position and what is in the way, got {far}")
    expect(lead_of(_lead_page(prose(LEAD_BUDGET))) == [], "a lead exactly at the budget passes")
    expect([f for f, _ in lead_of(_lead_page(prose(LEAD_BUDGET + 1)))] == ["lead"], "one unit over the budget fails")
    expect(lead_of(_lead_page("<p>" + "字" * (2 * LEAD_BUDGET) + "</p>")) == [], "a CJK character counts half a unit")
    expect([f for f, _ in lead_of(_lead_page("<p>" + "字" * (2 * LEAD_BUDGET + 2) + "</p>"))] == ["lead"],
           "two CJK characters over the budget fail")
    for wrap in ("<nav>{}</nav>", "<aside>{}</aside>", '<div class="reading-contents">{}</div>',
                 '<div class="reading_contents">{}</div>', '<div id="toc">{}</div>', '<div data-role="toc">{}</div>',
                 '<div role="navigation">{}</div>', "<div hidden>{}</div>", '<div aria-hidden="true">{}</div>'):
        hid = lead_of(_lead_page(wrap.format(prose(150))))
        expect(hid == [], f"text inside {wrap.format('…')} is not counted against the lead, got {hid}")
    decoy = lead_of(_lead_page('<aside id="bottom-line"><p>Needs you: nothing.</p></aside>' + prose(150)))
    expect([f for f, _ in decoy] == ["lead"], f"a lead id inside hidden text is no anchor, got {decoy}")
    none = lead_of(_lead_page(asof, "<p>The parser is fixed.</p>"))
    expect([f for f, _ in none] == ["lead"] and "none" in none[0][1], f"a page with no lead anchor fails 'none', got {none}")
    by_id = _lead_page(asof, '<div id="bottom-line"><p>It ships on Friday. Nothing needed from you.</p></div>')
    expect(lead_of(by_id) == [], f"an id alone marks the lead, got {lead_of(by_id)}")
    owed = _lead_page(asof, '<section id="needs-you"><p>Merge pull request 12 by 2026-11-25.</p></section>')
    expect(lead_of(owed) == [], f"a needs-you block is itself the ask, got {lead_of(owed)}")
    zh = _lead_page("<p>截至 2026-11-22。</p>", "<p><strong>结论：</strong>解析器修好了。</p>"
                    "<p><strong>需要你：</strong>11 月 25 日前批准发布。</p>", h1="解析器修好了，周五发布。")
    expect(lead_of(zh) == [], f"a Chinese lead (结论 + 需要你) is clean, got {lead_of(zh)}")
    old = re.sub(r"<h2>Human TODO</h2>.*?(?=<h2>Timeline)", "<h2>Goal</h2><p>g</p><h2>Now</h2><p>n</p>"
                 "<h2>Human TODO</h2><ul><li>a</li></ul><h2>Blockers</h2><p>none</p>", _WORKLOG, flags=re.S)
    worder = lead_of(old)
    expect([f for f, _ in worder] == ["lead"] and "Human TODO · Blockers · Now · Goal" in worder[0][1],
           f"a work-log header in the old order (Goal · Now · Human TODO) fails, got {worder}")
    long_goal = lead_of(old.replace("<h2>Goal</h2><p>g</p>", "<h2>Goal</h2>" + prose(150)))
    expect(len(long_goal) == 1 and "Goal before Human TODO" in long_goal[0][1],
           f"one lead finding per page, and the order problem is the one reported, got {long_goal}")
    for exempt in ("reference", "landing"):
        expect(lead_of(_lead_page(prose(150), "", kind=exempt)) == [], f"a {exempt} page is not asked for a lead")
    messy = _lead_page('<nav><ul><li>' + " ".join(["toc"] * 80) + '<li>' + " ".join(["toc"] * 80) + '</ul></nav>'
                       '<p>As of 2026-11-22.<br><hr>').replace("<body>", '<body><img src="x" alt="" aria-hidden="true"><input hidden>')
    expect(lead_of(messy) == [], f"unclosed <p>/<li> and void tags leave the hidden stack intact, got {lead_of(messy)}")
    # where an anchor counts: after the headline, as a block's first text, outside any heading
    wrapped = _lead_page(prose(150)).replace("<h1>", '<header id="next"><h1>').replace("</h1>", "</h1></header>")
    expect([f for f, _ in lead_of(wrapped)] == ["lead"],
           f"a lead id on an element that opens before the headline is no lead, got {lead_of(wrapped)}")
    mid = lead_of(_lead_page('<p>As of 2026-11-22. See <a href="#x">plan</a> next step: ship</p>' + prose(150), ""))
    expect([f for f, _ in mid] == ["lead"] and "none" in mid[0][1],
           f"a label-shaped phrase in the middle of a paragraph is no label anchor, got {mid}")
    indented = _lead_page(asof, "<p>\n  <span>Needs you:</span> approve the release by Friday.</p>")
    expect(lead_of(indented) == [], f"hand-indented markup before a label keeps it the block's first text, got {lead_of(indented)}")
    in_h5 = lead_of(_lead_page(asof + "<div><h5>Next step: ship it</h5></div>" + prose(150), ""))
    expect([f for f, _ in in_h5] == ["lead"] and "none" in in_h5[0][1],
           f"a label inside a heading (h5 too) is no label anchor, got {in_h5}")
    under = _lead_page(asof, '<div class="bottom_line"><p>It ships on Friday. Nothing needed from you.</p></div>')
    expect(lead_of(under) == [], f"an id or class spelled with _ (bottom_line) marks the lead, got {lead_of(under)}")
    second = _lead_page(asof, _LEAD_OK + prose(150) + "<h1>A second headline</h1>")
    expect(lead_of(second) == [], f"only the first <h1> is the headline, got {lead_of(second)}")
    branded = _lead_page(prose(150), "", h1="解析器修好了，周五发布，要你拍板。").replace("<body>", "<body><nav><h1>Brand</h1></nav>")
    expect(lead_of(branded) == [], f"an <h1> inside a nav is not the headline; the first visible one is, got {lead_of(branded)}")
    spans = _lead_page(prose(150), "", h1="The parser ships Friday; <em>you</em> <em>must</em> approve it.")
    expect(lead_of(spans) == [], f"the headline's text keeps the space between inline elements, got {lead_of(spans)}")
    # the ask must sit in the first LEAD_WINDOW units from the anchor, measured to the unit, not the text node
    bl = "<strong>Bottom line:</strong>"   # 2 units; with the parser sentence below, 6
    above = _lead_page("<p>Drafted for you to review.</p>", f'<section id="bottom-line"><p>{bl} the parser is fixed.</p></section>')
    expect([f for f, _ in lead_of(above)] == ["lead-ask"], f"an ask above the lead is not the lead's ask, got {lead_of(above)}")

    def window_case(k: int, shape: str) -> list[str]:
        h1 = "The parser is fixed and ships on Friday."
        if shape == "chinese":
            body, h1 = "<p><strong>结论：</strong>" + "字" * k + "要你批准。</p>", "解析器修好了，周五发布。"
        elif shape == "split":
            body = f"<p>{bl} the parser is fixed.</p>" + prose(k).replace("byline", "word") + "<p>You must approve it.</p>"
        else:
            body = f"<p>{bl} " + " ".join(["word"] * k) + " you must approve it.</p>"
        return [f for f, _ in lead_of(_lead_page("", f'<section id="bottom-line">{body}</section>', h1=h1))]

    # 6 + k + 2 ("You must") ≤ LEAD_WINDOW; 2 + k + 2 ≤ LEAD_WINDOW; 2 + (k + 2) / 2 ≤ LEAD_WINDOW
    for k, shape, label in ((LEAD_WINDOW - 8, "split", "split across nodes"),
                            (LEAD_WINDOW - 4, "single", "in one text node"),
                            (2 * LEAD_WINDOW - 6, "chinese", "in one Chinese text node")):
        expect(window_case(k, shape) == [], f"an ask that ends at the window's last unit, {label}, counts")
        expect(window_case(k + 1, shape) == ["lead-ask"],
               f"an ask one unit past the window, {label}, does not count, got {window_case(k + 1, shape)}")

    # an end tag HTML lets an author omit is implied where a browser implies it:
    # an unclosed hidden <p>, item, term, cell or row hides itself, not the lead after it
    filler = " ".join(["word"] * 150)
    toc = "Contents: " + " ".join(["section"] * 150)
    lead_li = "<strong>Bottom line:</strong> fixed. <strong>Needs you:</strong> approve it."
    for what, between, lead in (
            ("a <p class=toc>", f'<p class="toc">{toc}', _LEAD_OK),
            ("a <p hidden>", f"<p hidden>{toc}", _LEAD_OK),
            ("an <li>", f'<ul><li aria-hidden="true">{toc}<li id="bottom-line">{lead_li}</ul>', ""),
            ("a <dt>", f'<dl><dt hidden>{toc}<dd id="bottom-line">{lead_li}</dl>', ""),
            ("a <td>", f'<table><tr><td aria-hidden="true">{toc}<td id="bottom-line">{lead_li}</table>', ""),
            ("a <tr>", f'<table><tr aria-hidden="true"><td>{toc}<tr><td id="bottom-line">{lead_li}</table>', "")):
        got = lead_of(_lead_page(between, lead))
        expect(got == [], f"{what} left open ends at the next one, as a browser ends it, got {got}")
    hr = lead_of(_lead_page(f'<p aria-hidden="true">Contents<hr>{" ".join(["byline"] * 150)}'))
    expect([f for f, _ in hr] == ["lead"] and "150 units" in hr[0][1],
           f"an <hr> ends an open <p>, so the text after it counts, got {hr}")
    # ... and only within its scope: a list in an item, a term list in a term, a table in a cell, a button in a <p>
    for what, between in (("a list inside a hidden item", f'<ul><li aria-hidden="true">Contents<ul><li>{filler}</ul></ul>'),
                          ("a term list inside a hidden term", f'<dl><dd aria-hidden="true">Terms<dl><dt>{filler}</dl></dl>'),
                          ("a table inside a hidden cell",
                           f'<table><tr><td aria-hidden="true">Key<table><tr><td>{filler}</table></table>'),
                          ("a button inside a hidden <p>", f'<p aria-hidden="true">Menu <button>open<p>{filler}</button></p>')):
        got = lead_of(_lead_page(between))
        expect(got == [], f"{what} stays hidden: its own <li>/<dt>/<td>/<p> does not end the outer one, got {got}")
    deep = _Page()
    deep.feed("<body><h1>x</h1>" + "<p>As of today." * 2000)
    expect(len(deep._lstack) <= 3, f"2,000 unclosed <p> keep the lead stack shallow, got depth {len(deep._lstack)}")
    h5_strong = lead_of(_lead_page(asof + "<div><h5><strong>Next step:</strong> ship it</h5></div>" + prose(150), ""))
    expect([f for f, _ in h5_strong] == ["lead"] and "none" in h5_strong[0][1],
           f"a block opened inside a heading is inside the heading, so its label is no anchor, got {h5_strong}")
    stray = _lead_page(asof + "</span></div></li>")
    expect(lead_of(stray) == [], f"a stray end tag changes nothing, got {lead_of(stray)}")

    # every hidden element is a guard, not only nav and aside: an inline script,
    # a style block or a labelled drawing between the headline and the lead
    for tag, wrap in (("script", '<script>var help = "{}";</script>'), ("style", "<style>/* {} */</style>"),
                      ("svg", '<svg role="img" aria-label="flow"><text>{}</text></svg>'),
                      ("noscript", "<noscript><p>{}</p></noscript>"), ("template", "<template><p>{}</p></template>"),
                      ("dialog", "<dialog><p>{}</p></dialog>")):
        got = lead_of(_lead_page(wrap.format(filler)))
        expect(got == [], f"text inside <{tag}> is not counted against the lead, got {got}")
    by_role = _lead_page(asof, '<div data-role="bottom-line"><p>It ships on Friday. Nothing needed from you.</p></div>')
    expect(lead_of(by_role) == [], f"a data-role marks the lead as an id does, got {lead_of(by_role)}")
    inline = lead_of(_lead_page("<p>As of today. <em>Next step:</em> nothing yet.</p>" + prose(150), ""))
    expect([f for f, _ in inline] == ["lead"] and "none" in inline[0][1],
           f"a label inside an inline element mid-paragraph is no label anchor, got {inline}")
    goal_first = _lead_page(asof, _LEAD_OK + "<h2>Goal of the study</h2><p>g</p><h2>Needs you: approval</h2><p>a</p>")
    expect(lead_of(goal_first) == [], f"the Human TODO-first order is asked of work-logs only, got {lead_of(goal_first)}")

    # (v2) the lead is the anchor that STARTS first, and lead-ask belongs to a lead within budget
    held = _lead_page(prose(95), '<h2>Next steps for the full evaluation of every arm <span class="ask">x</span></h2>'
                                 "<p>You must approve.</p>")
    expect(lead_of(held) == [], f"a lead heading that starts within budget holding a role element past it passes, got {lead_of(held)}")
    beyond = lead_of(_lead_page(prose(150), '<section id="bottom-line"><p><strong>Bottom line:</strong> fixed.</p></section>'))
    expect([f for f, _ in beyond] == ["lead"], f"a lead beyond budget with no ask is one lead FAIL, no lead-ask, got {beyond}")
    for h2 in ('<h2 id="next">Human TODO</h2>', '<h2><a id="next"></a>Human TODO</h2>'):
        tie = lead_of(_lead_page(asof, h2 + "<p>The parser is fixed.</p>"))
        expect(tie == [], f"anchors that start at the same place are all the lead, so {h2} asks, got {tie}")
    # (v2) the work-log order reads h2-h4 only, names the heading that comes first, and reads a numbered prefix
    now_h1 = lead_of(_WORKLOG.replace("<h1>Worklog: x</h1>", "<h1>Now shipping the parser</h1>"))
    expect(now_h1 == [], f"a work-log in the right order whose headline starts with Now passes, got {now_h1}")
    now_first = lead_of(_WORKLOG.replace("<h2>Human TODO</h2><ul><li>a</li></ul><h2>Blockers</h2><p>none</p>\n<h2>Now</h2><p>n</p>",
                                         "<h2>Now</h2><p>n</p><h2>Human TODO</h2><ul><li>a</li></ul><h2>Blockers</h2><p>none</p>"))
    expect([f for f, _ in now_first] == ["lead"] and "puts Now before Human TODO" in now_first[0][1],
           f"a work-log with Now before Human TODO is told so, got {now_first}")
    numbered = lead_of(re.sub(r"<h2>Human TODO</h2>.*?(?=<h2>Timeline)",
                              "<h2>1 · Goal</h2><p>g</p><h2>2 · Human TODO</h2><ul><li>a</li></ul>"
                              "<h2>3 · Blockers</h2><p>none</p><h2>4 · Now</h2><p>n</p>", _WORKLOG, flags=re.S))
    expect([f for f, _ in numbered] == ["lead"] and "puts Goal before Human TODO" in numbered[0][1],
           f"numbered work-log headings (1 · Goal before 2 · Human TODO) fail the order, got {numbered}")
    # (v2) a no-break space is a space, and a block's first text ends when the block does
    nbsp = _lead_page(asof, "<p>Bottom&nbsp;line: the parser is fixed.</p><p>Needs&nbsp;you: approve the release by 2026-11-25.</p>")
    expect(lead_of(nbsp) == [], f"Bottom&nbsp;line: and Needs&nbsp;you: are labels, got {lead_of(nbsp)}")
    for after_empty in ("<p></p>Needs you: approve it.", "<div></div>Next step: ship.", "<p><img src=x></p><span>Next step: ship.</span>"):
        gone = lead_of(_lead_page("", after_empty))
        expect([f for f, _ in gone] == ["lead"] and "none" in gone[0][1],
               f"text after an empty closed block is not its first text, so {after_empty!r} has no lead, got {gone}")

    # (v2) the deck sits under the lead: the lead's paragraphs are not the deck and do not use up its places
    def deck_of(html: str) -> list[str]:
        return [m for f, _, m in lint_html(html)[0] if f == "deck"]

    long_words = " ".join(["evidence"] * 40)
    in_role = deck_of(_lead_page(asof, f'<section id="bottom-line"><p>{long_words}</p>'
                                       "<p><strong>Needs you:</strong> approve it.</p></section>"))
    expect(len(in_role) == 1 and "no abstract under the lead" in in_role[0],
           f"a long paragraph inside the lead block is not the deck, got {in_role}")
    for label in ("<strong>Bottom line:</strong>", "Bottom&nbsp;line:"):
        by_label = deck_of(_lead_page(asof, f"<p>{label} {long_words}</p><p><strong>Needs you:</strong> approve it.</p>"))
        expect(len(by_label) == 1, f"a long paragraph opening with {label} is the lead, not the deck, got {by_label}")
    places = deck_of(_lead_page(asof, '<section id="bottom-line">' + "<p>Point.</p>" * 6 + "</section>"
                                      f"<p>{long_words}</p>"))
    expect(places == [], f"six lead paragraphs do not use up the places a deck under the lead is looked for in, got {places}")

    # a stack held in a custom property is a stack
    tok = _GOOD.replace("body{font-family:Menlo,monospace;", "body{font-family:var(--mono);").replace(":root{--ink:#0a0a0a;", ":root{--mono:Menlo,monospace;--ink:#0a0a0a;")
    expect("font-fallback" not in {f for f, _, _ in lint_html(tok)[0]}, "font-family: var(--stack) is not a bare face")
    # a single-theme declaration silences the theme checks, and only those
    st = _GOOD.replace("@media (prefers-color-scheme: dark){:root:not([data-theme=\"light\"]){--ink:#eee;--bg:#111}}", "<!--artifact:single-theme-->")
    st = st.replace("</style></head>", "</style><!--artifact:single-theme--></head>")
    st_f, _ = lint_html(st)
    expect("theme" not in {f for f, _, _ in st_f}, "single-theme declaration is honoured")

    # a section reachable only from the index still counts — the shape hub pages
    # actually have: the label is a styled <div>, and the only thing naming it is
    # the nav link. Without nav text in `roles` the lint reports five sections
    # missing from a page that has them.
    div_only = _BAD.replace("<body>", '<body><nav><a href="#m">Method</a><a href="#l">Limits</a>'
                                      '<a href="#n">Next</a><a href="#w">Why</a>'
                                      '<a href="#s">Sources</a></nav>')
    dids = {f for f, _, _ in lint_html(div_only)[0]}
    expect(not ({"method", "limits", "next", "why", "sources"} & dids),
           f"a section named only by an in-page index link counts as present, got {sorted(dids)}")

    # a register still owes its limits, and only its limits
    ref = _BAD.replace("<html><head>", '<html><head><meta name="artifact-type" content="reference">')
    rids = {f: lvl for f, lvl, _ in lint_html(ref)[0]}
    expect(rids.get("limits") == "WARN", "a register with no limits section is flagged: 'not listed' reads as 'does not exist'")
    expect("next" not in rids and "why" not in rids, "next-step and why do relax for a register")
    expect("headings-claim" not in rids, "label headings are correct in a register")

    # a long page needs an index that follows the reader
    long_page = _GOOD.replace("</body>", ("<p>" + ("evidence " * 600) + "</p>") * 11 + "</body>")
    lids = {f: lvl for f, lvl, _ in lint_html(long_page)[0]}
    expect(lids.get("nav-position") == "WARN", f"a {_LONG_PAGE}+ word page whose index is neither pinned nor position-aware is flagged, got {lids.get('nav-position')}")
    pinned = long_page.replace("body{font-family:Menlo,monospace;", "nav{position:sticky;top:0}body{font-family:Menlo,monospace;")
    pinned = pinned.replace('<nav><a href="#a">a</a>', '<nav><a href="#a" aria-current="true">a</a>')
    expect("nav-position" not in {f for f, _, _ in lint_html(pinned)[0]}, "a pinned index that marks the current section passes")
    half = long_page.replace("body{font-family:Menlo,monospace;", "nav{position:sticky;top:0}body{font-family:Menlo,monospace;")
    expect("nav-position" in {f for f, _, _ in lint_html(half)[0]}, "pinning alone is not enough; the index must say where the reader is")
    expect("nav-position" not in {f for f, _, _ in lint_html(_GOOD)[0]}, "a short page is not asked for a pinned index")

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
    print("artifact-lint --self-test: PASSED (good page clean, bad page carries 25 findings, lead first under the headline within budget, heuristics fire in both languages, survey groups)")
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
