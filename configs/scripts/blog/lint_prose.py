#!/usr/bin/env python3
"""
lint_prose.py — the second-order pass: prose that passed the blocklist and still reads like AI.

`analyze_blog.py` already runs the first-order check — trigger phrases, trigger
word density, TTR, burstiness. `ai-slop-detection.md` opens by saying that pass
is necessary and not sufficient: replace the obvious vocabulary and the model
reaches for the next-most-trained pattern, which is structural and rhythmic and
survives any word swap. Every H2 a question. Every list item eighty words. Three
hedges in twenty. A vocabulary edit does not touch one of those.

That second pass was specified in full — ten structural tics, three rhythmic
signals, every threshold numeric — and never implemented, so "AI-detection
passed" has meant the first-order pass alone for the whole v1.8.x line.

    lint_prose.py POST.md
    lint_prose.py POST.md --format json
    lint_prose.py POST.md --first-order      # include the phrase/lexical summary

Exit 1 when any signal fires, so Gate 4 can branch on it.
Stdlib only, no network. The phrase tables are IMPORTED from analyze_blog.py —
two copies of one list is how they diverge.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import statistics
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _phrase_tables() -> tuple[list[str], list[str], list[str]]:
    """Borrow the first-order tables from analyze_blog.py rather than restating them."""
    target = _HERE / "analyze_blog.py"
    if not target.is_file():
        return [], [], []
    spec = importlib.util.spec_from_file_location("_analyze_blog", target)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 - a broken sibling must not take the linter down
        return [], [], []
    return (list(getattr(module, "AI_PHRASES", [])),
            list(getattr(module, "AI_TRIGGER_WORDS", [])),
            list(getattr(module, "TRANSITION_WORDS", [])))


AI_PHRASES, AI_TRIGGER_WORDS, TRANSITION_WORDS = _phrase_tables()

# Signal 8's own examples are "First... Next... Additionally... Crucially...".
# analyze_blog.TRANSITION_WORDS is a READABILITY list — however, therefore,
# furthermore, consequently — and contains none of first, next or crucially, so
# borrowing it alone to avoid duplication produced a signal that could not
# detect the pattern the reference names. The capsule openers are declared here
# because they are THIS signal's definition, and the borrowed list is unioned in
# because those are legitimate capsule openers too.
CAPSULE_OPENERS = {
    "first", "second", "third", "next", "then", "finally", "lastly",
    "additionally", "crucially", "importantly", "notably", "ultimately",
    "meanwhile", "overall", "essentially", "fundamentally", "critically",
}
TRANSITION_WORDS = sorted(CAPSULE_OPENERS | {t.lower() for t in TRANSITION_WORDS
                                             if " " not in t})

# ─── Thresholds (ai-slop-detection.md) ───
QUESTION_H2_RATIO = 0.70          # 1. > 70% of H2s ending in ?
HERE_OPENERS_PER_1500 = 3         # 2. 3+ per 1,500 words
THREE_CLAUSE_RATIO = 0.50         # 3. > 50% in any 200-word window
FALSE_BALANCE_PER_1000 = 2        # 4. more than twice per 1,000 words
HEDGES_PER_20_WORDS = 2           # 5. > 2 in a 20-word window
LIST_ITEM_SD_FLOOR = 5            # 6. SD < 5 words
WRAPUP_QUESTIONS = 3              # 7. 3 or more
CAPSULE_TRANSITION_RATIO = 0.50   # 8. > 50% of H2 openers
LISTICLE_INTRO_WORDS = 250        # 10. > 250 words before the list
PARAGRAPH_SD_FLOOR = 4            # sentence-length SD within a paragraph
PARAGRAPH_CV_FLOOR = 0.35         # ...and relative: SD/mean, so short != flat
OPENER_TOP3_SHARE = 0.25          # top three first-words > 25%
POST_PARAGRAPH_SD_FLOOR = 25      # paragraph word-count SD across the post

# ─── Which signals decide the exit code ───
#
# Measured on 30 human-written documents in this repository (docs/ and skill
# references, each over 3 KB). POPULATION MATTERS AND THIS ONE IS NOT BLOG
# POSTS: it is technical documentation, which legitimately has flatter
# paragraph shapes and more uniform list items than the consumer long-form
# these thresholds were written for. Read the rates as a floor on false alarms,
# not as a verdict on the spec.
#
#     paragraph_shape_flatness      70%      symmetric_list_bloat     63%
#     paragraph_sentence_flatness   50%      opening_word_repetition  43%
#     ...every other signal          0-6%
#
# A signal that fires on seven of ten human documents does not discriminate,
# and a linter that cries wolf gets bypassed — which is the failure this whole
# contract exists to prevent. The ten structural tics decide the exit code; the
# four measured-noisy signals are reported as advisory and need --strict to
# fail the run. Nothing is silently dropped: every signal is still computed and
# still printed.
ADVISORY = {
    "paragraph_shape_flatness",
    "paragraph_sentence_flatness",
    "opening_word_repetition",
    "symmetric_list_bloat",
}

HEDGES = ("may", "might", "often", "typically", "generally", "usually",
          "tend to", "perhaps", "somewhat", "likely")

_FALSE_BALANCE = re.compile(
    r"\bwhile\s+[^.,;]{3,60},\s*(?:also\b|it\s+also\b|there\s+(?:is|are)\s+also\b)"
    r"|\bon\s+(?:the\s+)?one\s+hand\b[^.]{0,200}?\bon\s+the\s+other\b",
    re.I | re.S,
)
_WRAPUP = re.compile(
    r"what\s+does\s+this\s+mean\s+for\b[^?]{0,60}\?"
    r"|why\s+does\s+this\s+matter\s*\?"
    r"|what\s+(?:does|do)\s+that\s+mean\b[^?]{0,60}\?",
    re.I,
)
_KEY_INSIGHT = re.compile(
    r"(?:^|\.\s+)(?:the\s+key\s+insight\s+is|what(?:'s|\s+is)\s+important\s+here\s+is"
    r"|the\s+key\s+takeaway\s+is|the\s+important\s+thing\s+(?:here\s+)?is)\b",
    re.I | re.M,   # without re.M, `^` meant start-of-DOCUMENT, so the tell was
)                  # invisible anywhere but the first sentence of the whole post
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(])")
_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
_LIST_ITEM = re.compile(r"^\s{0,3}(?:[-*+]|\d+[.)])\s+(.*)$", re.M)


def strip_noise(text: str) -> str:
    """Fenced code, inline code, HTML comments and tables are not prose."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"~~~.*?~~~", " ", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"`[^`\n]+`", " ", text)
    text = re.sub(r"^\s{0,3}\|.*\|\s*$", " ", text, flags=re.M)
    return text


def words(text: str) -> list[str]:
    return _WORD.findall(text)


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if words(s)]


def paragraphs(text: str) -> list[str]:
    out = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block or block.startswith("#") or _LIST_ITEM.match(block):
            continue
        if len(words(block)) >= 15:
            out.append(block)
    return out


def _finding(name: str, fired: bool, detail: str, value=None, threshold=None) -> dict:
    return {"signal": name, "fired": fired, "detail": detail,
            "value": value, "threshold": threshold}


# ─── Second-order: structural tics 1-10 ───

def structural(raw: str, prose: str) -> list[dict]:
    # `raw` here is already noise-stripped by analyze(). Reading the true raw
    # counted an H2 written INSIDE a fenced code block as a heading of the post.
    out = []
    h2s = re.findall(r"^##\s+(.+?)\s*$", raw, re.M)
    total_words = len(words(prose))

    # 1. Question-cadence H2s
    if h2s:
        q = sum(1 for h in h2s if h.rstrip().endswith("?"))
        ratio = q / len(h2s)
        out.append(_finding(
            "question_cadence_h2", ratio > QUESTION_H2_RATIO,
            f"{q} of {len(h2s)} H2 headings are questions. Real long-form mixes "
            f"question, statement and noun-phrase headings.",
            round(ratio, 2), QUESTION_H2_RATIO))

    # 2. The Heres opener
    # PARAGRAPH starts, not line starts. `\n` matches any wrap, so re-wrapping
    # the same prose changed the count, and the message says "paragraph(s)".
    heres = sum(1 for para in re.split(r"\n\s*\n", prose)
                if re.match(r"\s*Here(?:'s|\s+(?:are|is))\b", para))
    allowed = max(HERE_OPENERS_PER_1500, round(HERE_OPENERS_PER_1500 * total_words / 1500))
    out.append(_finding(
        "here_openers", heres >= allowed,
        f'{heres} paragraph(s) open with "Here". Once is fine; a habit is a fingerprint.',
        heres, allowed))

    # 3. Three-clause sentence rhythm, in any 200-word window
    sents = sentences(prose)
    worst, window = 0.0, []
    for sentence in sents:
        window.append(sentence)
        while sum(len(words(s)) for s in window) > 200 and len(window) > 1:
            window.pop(0)
        # A ratio over three sentences is noise. The spec says "any 200-word
        # window"; a real one holds eight to twelve sentences, so require the
        # window to be substantially full before believing its ratio.
        if len(window) >= 5 and sum(len(words(s)) for s in window) >= 120:
            three = sum(1 for s in window if s.count(",") == 2 and s.rstrip().endswith("."))
            worst = max(worst, three / len(window))
    out.append(_finding(
        "three_clause_rhythm", worst > THREE_CLAUSE_RATIO,
        f"Worst 200-word window is {worst:.0%} three-clause sentences. The cadence "
        f"becomes metronomic.", round(worst, 2), THREE_CLAUSE_RATIO))

    # 4. False-balance framing
    fb = len(_FALSE_BALANCE.findall(prose))
    fb_allowed = max(FALSE_BALANCE_PER_1000, round(FALSE_BALANCE_PER_1000 * total_words / 1000))
    out.append(_finding(
        "false_balance", fb > fb_allowed,
        f'{fb} "While X, also Y" / "on one hand" framings. Even-handed shape, no '
        f"added information.", fb, fb_allowed))

    # 5. Hedge stacking in any 20-word window
    # Word boundaries, not substrings: `"maybe".count("may")` is 1 and
    # `"unlikely".count("likely")` is 1, so the first version scored ordinary
    # prose as hedging.
    tokens = [w.lower() for w in words(prose)]
    single = {h for h in HEDGES if " " not in h}
    multi = [h for h in HEDGES if " " in h]
    worst_hedges = 0
    for i in range(len(tokens)):
        window_tokens = tokens[i:i + 20]
        if len(window_tokens) < 20 and i:
            break
        count = sum(1 for t in window_tokens if t in single)
        chunk = " ".join(window_tokens)
        count += sum(chunk.count(h) for h in multi)
        worst_hedges = max(worst_hedges, count)
    out.append(_finding(
        "hedge_stacking", worst_hedges > HEDGES_PER_20_WORDS,
        f"Densest 20-word span carries {worst_hedges} hedges. Three hedges in one "
        f"breath says nothing carefully.", worst_hedges, HEDGES_PER_20_WORDS))

    # 6. Symmetric list bloat
    items = [len(words(m)) for m in _LIST_ITEM.findall(raw) if words(m)]
    if len(items) >= 4:
        sd = statistics.pstdev(items)
        out.append(_finding(
            "symmetric_list_bloat", sd < LIST_ITEM_SD_FLOOR,
            f"List items vary by SD {sd:.1f} words across {len(items)} items. Real "
            f"lists are lumpy; some items need a line, others a paragraph.",
            round(sd, 1), LIST_ITEM_SD_FLOOR))

    # 7. The wrap-up question
    wrap = len(_WRAPUP.findall(prose))
    out.append(_finding(
        "wrapup_question", wrap >= WRAPUP_QUESTIONS,
        f'{wrap} "what does this mean / why does this matter" closers. Once is '
        f"rhetorical; three is filler.", wrap, WRAPUP_QUESTIONS))

    # 8. Capsule transitions opening H2 sections
    openers = section_openers(raw)
    if openers:
        capsule = sum(
            1 for o in openers
            if (words(o) or [""])[0].lower().strip(",") in {t.lower() for t in TRANSITION_WORDS}
        )
        ratio = capsule / len(openers)
        out.append(_finding(
            "capsule_transitions", ratio > CAPSULE_TRANSITION_RATIO,
            f"{capsule} of {len(openers)} sections open on a single-word transition. "
            f"Real prose buries transitions inside sentences.",
            round(ratio, 2), CAPSULE_TRANSITION_RATIO))

    # 9. The "key insight" tell
    ki = len(_KEY_INSIGHT.findall(prose))
    out.append(_finding(
        "key_insight_tell", ki > 0,
        f'{ki} "the key insight is" style opener(s). The model telegraphing a '
        f"summary; cut it and let the sentence stand.", ki, 0))

    # 10. Listicle introduction bloat
    # Only for a document that IS a listicle. The signal fired on any essay with
    # a list past the 250-word mark, which is most long-form writing: the
    # reference calls it "Listicle introduction bloat", and a listicle is a post
    # whose body is mostly the list.
    items_all = _LIST_ITEM.findall(raw)
    first_list = _LIST_ITEM.search(raw)
    listicle = (len(items_all) >= 5
                and sum(len(words(i)) for i in items_all) >= 0.35 * max(total_words, 1))
    if first_list and listicle:
        intro = len(words(strip_noise(raw[:first_list.start()])))
        out.append(_finding(
            "listicle_intro_bloat", intro > LISTICLE_INTRO_WORDS,
            f"{intro} words before the first list item, in a document that is "
            f"{len(items_all)} list items. A listicle should get to the list.",
            intro, LISTICLE_INTRO_WORDS))

    return out


def section_openers(raw: str) -> list[str]:
    """First prose sentence after each H2."""
    out = []
    for match in re.finditer(r"^##\s+.+?$\n+(.*?)(?=\n##\s|\Z)", raw, re.M | re.S):
        body = strip_noise(match.group(1)).strip()
        for line in body.splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "-", "*", ">", "|")) and words(line):
                out.append(sentences(line)[0] if sentences(line) else line)
                break
    return out


# ─── Second-order: rhythmic signals ───

def rhythmic(prose: str) -> list[dict]:
    out = []
    paras = paragraphs(prose)

    flat = []
    for para in paras:
        lens = [len(words(s)) for s in sentences(para)]
        if len(lens) < 3:
            continue
        sd, mean = statistics.pstdev(lens), statistics.mean(lens)
        # ai-slop-detection.md says "SD < 4". Taken alone that penalises SHORT
        # sentences rather than flat ones: "Migrations fail on the boring parts.
        # Not the schema. The seventeen scripts nobody remembered, each pointing
        # at a column that moved." runs 6/3/12 words — four-fold variation — and
        # scores SD 3.7. Flatness is a RELATIVE property, so the absolute floor
        # is kept and paired with a coefficient-of-variation floor. Recorded in
        # the reference too; a threshold in two places disagreeing is worse than
        # either value.
        if sd < PARAGRAPH_SD_FLOOR and (mean and sd / mean < PARAGRAPH_CV_FLOOR):
            flat.append(round(sd, 1))
    out.append(_finding(
        "paragraph_sentence_flatness", bool(flat),
        f"{len(flat)} paragraph(s) have internal sentence-length SD under "
        f"{PARAGRAPH_SD_FLOOR}. Every sentence the same length reads as machinery.",
        len(flat), 0))

    sents = sentences(prose)
    firsts = [(words(s) or [""])[0].lower() for s in sents]
    if len(firsts) >= 10:
        counts = sorted({w: firsts.count(w) for w in set(firsts)}.values(), reverse=True)
        share = sum(counts[:3]) / len(firsts)
        out.append(_finding(
            "opening_word_repetition", share > OPENER_TOP3_SHARE,
            f"The three commonest sentence-opening words cover {share:.0%} of all "
            f"sentences.", round(share, 2), OPENER_TOP3_SHARE))

    if len(paras) >= 4:
        sd = statistics.pstdev([len(words(p)) for p in paras])
        out.append(_finding(
            "paragraph_shape_flatness", sd < POST_PARAGRAPH_SD_FLOOR,
            f"Paragraph word counts vary by SD {sd:.0f} across {len(paras)} "
            f"paragraphs. Real long-form varies dramatically.",
            round(sd), POST_PARAGRAPH_SD_FLOOR))

    return out


# ─── First-order summary (borrowed tables) ───

def first_order(prose: str) -> list[dict]:
    out = []
    total = len(words(prose)) or 1
    lowered = prose.lower()

    hits = [p for p in AI_PHRASES if p.lower() in lowered]
    out.append(_finding("trigger_phrases", bool(hits),
                        f"{len(hits)} trigger phrase(s): {', '.join(hits[:6])}"
                        if hits else "no trigger phrases", len(hits), 0))

    tw = sum(len(re.findall(rf"\b{re.escape(w)}\b", lowered)) for w in AI_TRIGGER_WORDS)
    density = tw * 1000 / total
    out.append(_finding("trigger_word_density", density > 5,
                        f"{density:.1f} AI trigger words per 1,000 words.",
                        round(density, 1), 5))

    tokens = [w.lower() for w in words(prose)]
    ttr = len(set(tokens)) / len(tokens) if tokens else 0.0
    out.append(_finding("type_token_ratio", ttr < 0.40 and total >= 300,
                        f"TTR {ttr:.2f} — vocabulary diversity.", round(ttr, 2), 0.40))

    lens = [len(words(s)) for s in sentences(prose)]
    if len(lens) >= 5 and statistics.mean(lens):
        burst = statistics.pstdev(lens) / statistics.mean(lens)
        out.append(_finding("burstiness", burst < 0.3,
                            f"Burstiness {burst:.2f} — sentence-length variation.",
                            round(burst, 2), 0.3))
    return out


def analyze(raw: str, include_first: bool) -> dict:
    raw = re.sub(r"\A---\n.*?\n---\n", "", raw, flags=re.S)
    prose = strip_noise(raw)
    result = {
        "words": len(words(prose)),
        "second_order": structural(prose, prose) + rhythmic(prose),
    }
    if include_first:
        result["first_order"] = first_order(prose)
    every = [f for group in (result.get("first_order", []), result["second_order"])
             for f in group if f["fired"]]
    result["fired"] = [f["signal"] for f in every if f["signal"] not in ADVISORY]
    result["advisory"] = [f["signal"] for f in every if f["signal"] in ADVISORY]
    return result


def render(result: dict) -> str:
    out = ["## AI Slop Detection Report", "", f"Prose words: {result['words']}", ""]
    if "first_order" in result:
        out += ["### First-order (Phrase + Lexical)"]
        for f in result["first_order"]:
            out.append(f"- {'FAIL' if f['fired'] else 'pass'} · {f['signal']}: {f['detail']}")
        out.append("")
    out += ["### Second-order (Structural + Rhythmic)"]
    for f in result["second_order"]:
        out.append(f"- {'FAIL' if f['fired'] else 'pass'} · {f['signal']}: {f['detail']}")
    out += ["", f"**{len(result['fired'])} signal(s) fired"
            + (f", {len(result['advisory'])} advisory" if result["advisory"] else "")
            + ".**"]
    if result["advisory"]:
        out.append(f"Advisory ({', '.join(result['advisory'])}) are rhythm signals "
                   f"measured to fire on 43-70% of human-written technical prose in "
                   f"this repository. Weigh them; they do not fail the run without "
                   f"--strict.")
    if result["fired"]:
        out.append("A vocabulary edit will not fix a structural signal. Vary the "
                   "shapes: heading forms, sentence lengths, list-item weights.")
    else:
        out.append("Both passes clean. Note that this measures SHAPE, not truth — "
                   "a well-shaped fabricated statistic passes every one of these.")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("path", nargs="?", type=Path)
    ap.add_argument("--format", choices=("markdown", "json"), default="markdown")
    ap.add_argument("--first-order", action="store_true",
                    help="Include the phrase/lexical pass (analyze_blog.py runs it too).")
    ap.add_argument("--strict", action="store_true",
                    help="Fail on the advisory rhythm signals too (see ADVISORY).")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if not args.path:
        ap.error("a path is required")
    if not args.path.is_file():
        print(f"lint_prose: no such file: {args.path}", file=sys.stderr)
        return 1

    try:
        text = args.path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        # is_file() passes on a file this process cannot open.
        print(f"lint_prose: cannot read {args.path}: {exc}", file=sys.stderr)
        return 1
    result = analyze(text, args.first_order)
    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        sys.stdout.write(render(result))
    failed = result["fired"] + (result["advisory"] if args.strict else [])
    return 1 if failed else 0


def self_test() -> int:
    problems: list[str] = []

    sloppy = (
        "## Why does this matter?\n\n"
        "Here's the thing. The key insight is that teams ship faster.\n\n"
        "## What does this mean for you?\n\n"
        "Here are the reasons. While speed matters, it also costs. "
        "It may often typically be the case that this holds.\n\n"
        "## Is this worth it?\n\n"
        "Here is the answer. What does this mean for teams? Why does this matter?\n"
        "What does this mean for buyers?\n\n"
        "- One item here of length\n- Two item here of length\n"
        "- Three item here of size\n- Four item here of size\n"
    )
    human = (
        "## The cost nobody budgets\n\n"
        "Migrations fail on the boring parts. Not the schema. The seventeen "
        "scripts nobody remembered, each pointing at a column that moved.\n\n"
        "## What we changed\n\n"
        "We froze writes for four hours on a Sunday, which everyone hated and "
        "which turned out to be the only thing that worked. The alternative was "
        "a dual-write window, and dual writes mean reconciliation, and "
        "reconciliation means a second bug surface at exactly the moment you "
        "can least afford one. So: four hours, one Sunday, done.\n\n"
        "It held.\n"
    )

    dirty = analyze(sloppy, include_first=False)
    clean = analyze(human, include_first=False)

    for name in ("question_cadence_h2", "here_openers", "wrapup_question",
                 "key_insight_tell", "hedge_stacking"):
        if name not in dirty["fired"]:
            problems.append(f"positive control did not fire: {name}")
    if clean["fired"]:
        problems.append(f"negative control fired on human prose: {clean['fired']}")
    # All FOUR, not one. Checking only symmetric_list_bloat meant any of the
    # other three could be promoted into the blocking set and the banner would
    # still claim they were held out.
    for signal in ("paragraph_shape_flatness", "paragraph_sentence_flatness",
                   "opening_word_repetition", "symmetric_list_bloat"):
        if signal not in ADVISORY:
            problems.append(f"{signal} left the advisory bucket")
    if "symmetric_list_bloat" not in dirty["advisory"]:
        problems.append("the measured-noisy list signal did not reach the advisory bucket")
    if set(dirty["fired"]) & ADVISORY:
        problems.append("an advisory signal leaked into the blocking set")

    # Signal 8's own examples must be detectable.
    capsules = "\n\n".join(f"## Section {i}\n\n{w.title()}, the thing happened here "
                            f"and it mattered to the team."
                            for i, w in enumerate(("first", "next", "crucially",
                                                   "additionally")))
    if "capsule_transitions" not in analyze(capsules, include_first=False)["fired"]:
        problems.append("capsule_transitions misses the four openers the spec names")

    # At the start of a LINE that is not preceded by ". " — after a heading,
    # which is where the tell actually appears. The first fixture put it after
    # a full stop, which the `\.\s+` alternative matches without re.M, so the
    # control could not tell the two apart.
    if "key_insight_tell" not in analyze(
            "## A section\n\nThe key insight is that it works\n",
            include_first=False)["fired"]:
        problems.append("key_insight_tell only matches at the start of the document")

    # here_openers must not change when the same prose is re-wrapped.
    # The wrapped form must put a "Here" at the start of a LINE that is NOT a
    # paragraph start. The first fixture wrapped only after the "Here", so both
    # splits counted three and the control could not see the difference.
    flat = ("One paragraph that mentions it. Here's one thing.\n\n"
            "Another paragraph. Here are two things.\n\n"
            "A third paragraph. Here is a third thing.\n\nAnd a fourth one.")
    wrapped = ("One paragraph that mentions it.\nHere's one thing.\n\n"
               "Another paragraph.\nHere are two things.\n\n"
               "A third paragraph.\nHere is a third thing.\n\nAnd a fourth one.")
    def _signal(text, name):
        # BY NAME. Indexing structural()[1] read whichever finding happened to
        # be second, and question_cadence_h2 is omitted entirely when the
        # fixture has no H2 — so the control was reading three_clause_rhythm.
        return next((f["value"] for f in structural(text, text) if f["signal"] == name), None)

    if _signal(flat, "here_openers") != _signal(wrapped, "here_openers"):
        problems.append("here_openers changes when the same prose is re-wrapped")

    # An essay is not a listicle.
    essay = ("## S\n\n" + "A paragraph of ordinary argument that runs on. " * 60
             + "\n\n- one\n- two\n")
    if "listicle_intro_bloat" in analyze(essay, include_first=False)["fired"]:
        problems.append("listicle_intro_bloat fired on an essay with a short list")

    # A structural signal must survive a pure vocabulary swap — that is the point.
    swapped = sloppy.replace("The key insight is", "The thing is")
    if "question_cadence_h2" not in analyze(swapped, include_first=False)["fired"]:
        problems.append("a structural signal vanished on a vocabulary edit")

    # Code must not be read as prose.
    if analyze("## S\n\n```\n" + sloppy + "\n```\n", include_first=False)["fired"]:
        problems.append("a fenced code block was linted as prose")

    if problems:
        for line in problems:
            print(f"SELF-TEST FAILED: {line}")
        return 1
    print("SELF-TEST PASSED: fires on structural tics, stays quiet on uneven "
          "human prose, survives a vocabulary swap, ignores code, and keeps the "
          "four measured-noisy signals out of the blocking set.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
