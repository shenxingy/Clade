#!/usr/bin/env python3
"""
cognitive_load.py — how much must a reader hold to follow this section?

Flesch and Gunning Fog measure surface difficulty: word length, sentence length.
They are blind to the thing that actually loses a reader on a long B2B post,
which is being asked to keep six new proper nouns, four unexplained terms and a
forward reference in working memory at the same time. Cowan (2001) puts that
capacity at roughly four items.

Implements `configs/skills/blog/references/cognitive-load.md` — the thresholds,
the composite score, and the report shape all come from that file, which is the
specification. It described this script for a full release line before the
script existed; `/blog analyze --cognitive-load` failed on the missing file.

    cognitive_load.py POST.md
    cognitive_load.py POST.md --format json
    cognitive_load.py POST.md --jargon extra-terms.txt   # augments the defaults

Stdlib only, no network. Deterministic: same input, same score, every run.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
from pathlib import Path

# ─── Thresholds (cognitive-load.md, "Practical thresholds for long-form") ───
#
# (healthy_max, borderline_max). Above borderline_max is overloaded.
#
# jargon is a PER-SECTION COUNT, not a density. The reference's threshold table
# labelled the row "per 100 words" while the metric name
# (`jargon_introduction_count`), the report column, and the worked P1 example
# ("4 new jargon terms in 410 words" → overloaded) all treat it as a raw count.
# Three sites against one; the table row was the outlier and has been corrected
# there rather than left to contradict this code.
THRESHOLDS = {
    "new_entity_density": (3.0, 6.0),      # per 100 words
    "numeric_claim_density": (3.0, 5.0),   # per 100 words
    "jargon_introduction_count": (1, 3),   # per section
    "forward_reference_count": (0, 1),     # per section
    "avg_clause_depth": (1.5, 2.5),        # per sentence
}

OVERLOADED_POINTS = 25
BORDERLINE_POINTS = 10

# A density needs a denominator. Six prose words containing two capitalised
# names is "33.3 entities per 100 words", which is arithmetic, not a finding.
# Short sections are still listed — silence would read as healthy — but they are
# reported as unscored rather than given a number nobody should act on.
MIN_SCORABLE_WORDS = 40

# Domain jargon. Extend for another domain with --jargon; entries AUGMENT these.
DEFAULT_JARGON = {
    "canonical", "crawl budget", "e-e-a-t", "eeat", "entity salience",
    "faceted navigation", "hreflang", "index bloat", "internal link equity",
    "keyword cannibalization", "lcp", "cls", "inp", "ttfb", "fcp",
    "core web vitals", "schema markup", "json-ld", "structured data",
    "serp", "featured snippet", "knowledge panel", "rich result",
    "geo", "generative engine optimization", "ai overviews", "llms.txt",
    "passage ranking", "query fan-out", "grounding", "retrieval augmented",
    "rag", "citability", "share of voice", "backlink velocity",
    "domain authority", "topical authority", "pagerank", "nofollow",
    "robots.txt", "sitemap", "noindex", "soft 404", "render budget",
    "hydration", "critical rendering path", "first-party data",
}

_FORWARD_REFS = re.compile(
    r"\b(?:as (?:we|you)(?:'ll| will) see|we(?:'ll| will) (?:cover|discuss|return to)"
    r"|discussed below|described below|see below|later in this (?:post|article|guide)"
    r"|more on (?:this|that) (?:below|later)|covered later|in the next section)\b",
    re.I,
)
# Percentages, currency, plain counts, dates, ordinals, x-multipliers.
_NUMERIC = re.compile(
    r"(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(?:%|percent|x\b|×)"
    r"|[$£€¥]\s?\d[\d,.]*"
    r"|\b(?:19|20)\d{2}\b"
    r"|(?<![\w.])\d{1,3}(?:,\d{3})+(?![\w.])"
    r"|(?<![\w.])\d+(?:\.\d+)?(?![\w.%])",
)
_CLAUSE = re.compile(r"[,;:]|\bwhich\b|\bthat\b|\bwhere\b|\bwhile\b|\balthough\b|\(")
# A bullet or a blank line ends a unit as surely as a full stop does. Without
# this, a section written as an unpunctuated list is ONE sentence carrying every
# comma in it: a real reference doc in this repo scored avg_clause_depth 27.0.
_SENTENCE = re.compile(r"[.!?]+(?:\s|$)|\n\s*(?:[-*+]|\d+\.)\s+|\n\s*\n")
# A capitalized run, not at a sentence start. Two words max keeps "The Reader Is"
# from becoming one entity.
_ENTITY = re.compile(r"(?<![.!?]\s)(?<!^)\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b", re.M)

_ENTITY_STOPWORDS = {
    "The", "This", "That", "These", "Those", "It", "They", "We", "You", "I",
    "A", "An", "But", "And", "Or", "If", "When", "While", "Because", "So",
    "For", "In", "On", "At", "To", "From", "With", "By", "As", "Not", "No",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December",
}


def strip_noise(text: str) -> str:
    """Remove fenced code, inline code, links' URLs, and HTML comments.

    A code block is not prose and its identifiers are not entities the reader
    has to hold; counting them was the first version's largest error.
    """
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"~~~.*?~~~", " ", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"`[^`\n]+`", " ", text)
    # Bounded on both halves. `\[([^\]]*)\]\([^)]*\)` is O(n^2) on a document
    # full of unmatched `[`: the engine restarts at every bracket and scans to
    # end-of-text each time. Measured 22s on a 100 KB file of `[` characters.
    text = re.sub(r"\[([^\]\n]{0,300})\]\(([^)\s\n]{0,500})\)", r"\1", text)
    text = re.sub(r"^\s{0,3}\|.*\|\s*$", " ", text, flags=re.M)  # tables
    return text


def split_sections(text: str) -> list[tuple[str, str]]:
    """(heading, body) per H2. Content before the first H2 is 'Introduction'."""
    parts = re.split(r"^##\s+(.+?)\s*$", text, flags=re.M)
    if len(parts) == 1:
        return [("(whole document)", text)]
    sections = []
    if parts[0].strip():
        sections.append(("Introduction", parts[0]))
    for i in range(1, len(parts) - 1, 2):
        sections.append((parts[i].strip(), parts[i + 1]))
    return sections


# Latin words, OR runs of CJK ideographs and kana. A Chinese or Japanese post
# scored 0 prose words in every section under an ASCII-only pattern, so every
# section came back unscored and the overall load read 0 — a clean bill of
# health produced by the analyser being unable to see the text at all.
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*|[\u4e00-\u9fff\u3040-\u30ff]")


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def measure(sections, jargon: set[str]) -> list[dict]:
    """Per-section metrics. State carried forward: entities and jargon already seen."""
    seen_entities: set[str] = set()
    defined_jargon: set[str] = set()
    rows = []

    for heading, raw in sections:
        body = strip_noise(raw)
        words = _words(body)
        count = len(words)
        per100 = (100.0 / count) if count else 0.0

        entities = {
            e for e in _ENTITY.findall(body)
            if e.split()[0] not in _ENTITY_STOPWORDS and len(e) > 2
        }
        new_entities = entities - seen_entities
        seen_entities |= entities

        lowered = body.lower()
        # Word boundaries. A bare `in` matched "geo" inside "geometry", "rag"
        # inside "storage" and "cls" inside "clsid", so ordinary prose was
        # reported as introducing domain jargon.
        present = {term for term in jargon
                   if re.search(r"(?<![\w-])" + re.escape(term) + r"(?![\w-])", lowered)}
        new_jargon = present - defined_jargon
        defined_jargon |= present

        numerics = len(_NUMERIC.findall(body))
        forwards = len(_FORWARD_REFS.findall(body))

        sentences = [s for s in _SENTENCE.split(body) if _words(s)]
        clauses = (
            sum(len(_CLAUSE.findall(s)) for s in sentences) / len(sentences)
            if sentences else 0.0
        )

        metrics = {
            "new_entity_density": round(len(new_entities) * per100, 1),
            "numeric_claim_density": round(numerics * per100, 1),
            "jargon_introduction_count": len(new_jargon),
            "forward_reference_count": forwards,
            "avg_clause_depth": round(clauses, 1),
        }
        if count < MIN_SCORABLE_WORDS:
            score, verdicts = 0, {k: "unscored" for k in metrics}
        else:
            score, verdicts = grade(metrics)
        rows.append({
            "scored": count >= MIN_SCORABLE_WORDS,
            "section": heading,
            "words": count,
            "load_score": score,
            "verdicts": verdicts,
            "new_jargon": sorted(new_jargon),
            **metrics,
        })
    return rows


def grade(metrics: dict) -> tuple[int, dict]:
    """Composite 0-100. 25 per overloaded signal, 10 per borderline, capped."""
    score, verdicts = 0, {}
    for name, value in metrics.items():
        healthy_max, borderline_max = THRESHOLDS[name]
        if value > borderline_max:
            verdicts[name] = "overloaded"
            score += OVERLOADED_POINTS
        elif value > healthy_max:
            verdicts[name] = "borderline"
            score += BORDERLINE_POINTS
        else:
            verdicts[name] = "healthy"
    return min(score, 100), verdicts


def classify(row: dict) -> str:
    """A section with two or more overloaded signals is a P1 (cognitive-load.md)."""
    if not row.get("scored", True):
        return "unscored"
    overloaded = sum(1 for v in row["verdicts"].values() if v == "overloaded")
    if overloaded >= 2:
        return "P1"
    if overloaded == 1 or any(v == "borderline" for v in row["verdicts"].values()):
        return "P2"
    return "healthy"


def band(score: int) -> str:
    return "Low" if score < 25 else "Moderate" if score < 50 else "High" if score < 75 else "Severe"


def render(rows: list[dict], title: str, total_words: int) -> str:
    scored = [r for r in rows if r.get("scored", True)]
    scored_words = sum(r["words"] for r in scored)
    overall = round(sum(r["load_score"] * r["words"] for r in scored) / scored_words) if scored_words else 0
    out = [f"## Cognitive Load Heatmap: {title}", "",
           f"Overall load: {overall} / 100 ({band(overall)})", ""]

    short = [r for r in rows if not r.get("scored", True)]
    if short:
        out += [f"> {len(short)} section(s) under {MIN_SCORABLE_WORDS} prose words are "
                f"listed but not scored: a density over that few words is arithmetic, "
                f"not a finding. They are excluded from the overall.", ""]
    if total_words < 1000:
        out += [f"> Note: {total_words} prose words (tables, code and inline code are "
                f"not prose and are excluded). cognitive-load.md says to skip posts "
                f"under 1,000 words — intrinsic load is bounded by length. Reported "
                f"anyway, since you asked; weigh it lightly.", ""]

    out += ["| Section (H2) | Words | Load | Entities/100 | Numerics/100 | Jargon | Forward refs | Avg clauses |",
            "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        load = str(r["load_score"]) if r.get("scored", True) else "—"
        out.append(
            f"| {r['section']} | {r['words']} | {load} | "
            f"{r['new_entity_density']} | {r['numeric_claim_density']} | "
            f"{r['jargon_introduction_count']} | {r['forward_reference_count']} | "
            f"{r['avg_clause_depth']} |"
        )

    for label, key in (("Overloaded sections (P1)", "P1"), ("Borderline sections (P2)", "P2")):
        out += ["", f"### {label}"]
        hits = [r for r in rows if classify(r) == key]
        if not hits:
            out.append("- (none)")
        for r in hits:
            reasons = [f"{n.replace('_', ' ')} {r[n]}"
                       for n, v in r["verdicts"].items() if v == "overloaded"] or \
                      [f"{n.replace('_', ' ')} {r[n]}"
                       for n, v in r["verdicts"].items() if v == "borderline"]
            extra = f" (new jargon: {', '.join(r['new_jargon'][:5])})" if r["new_jargon"] else ""
            out.append(f"- **{r['section']}**: {'; '.join(reasons)}.{extra}")

    healthy = [r["section"] for r in rows if classify(r) == "healthy"]
    tiny = [r["section"] for r in rows if classify(r) == "unscored"]
    out += ["", "### Healthy sections", "- " + (", ".join(healthy) if healthy else "(none)")]
    if tiny:
        out += ["", f"### Too short to score (under {MIN_SCORABLE_WORDS} prose words)",
                "- " + ", ".join(tiny)]
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("path", nargs="?", type=Path)
    ap.add_argument("--format", choices=("markdown", "json"), default="markdown")
    ap.add_argument("--jargon", type=Path,
                    help="Newline-delimited terms. AUGMENTS the defaults, never replaces them.")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if not args.path:
        ap.error("a path is required")
    if not args.path.is_file():
        print(f"cognitive_load: no such file: {args.path}", file=sys.stderr)
        return 1

    jargon = set(DEFAULT_JARGON)
    if args.jargon:
        if not args.jargon.is_file():
            print(f"cognitive_load: no such jargon file: {args.jargon}", file=sys.stderr)
            return 1
        jargon |= {
            line.strip().lower()
            for line in args.jargon.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip() and not line.startswith("#")
        }

    text = args.path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)   # frontmatter
    match = re.search(r"^#\s+(.+?)\s*$", text, re.M)
    title = match.group(1) if match else args.path.stem

    # strip_noise BEFORE splitting. Splitting the raw text made a `## ` line
    # inside a fenced code block a section of the post: a fixture with two such
    # lines produced sections named "Fake heading one" and "Fake heading two".
    # lint_prose.py had this exact bug and was fixed; this file was not checked.
    rows = measure(split_sections(strip_noise(text)), jargon)
    total = sum(r["words"] for r in rows)

    if args.format == "json":
        print(json.dumps({
            "title": title,
            "total_words": total,
            "overall_load": (lambda sc: round(sum(r["load_score"] * r["words"] for r in sc)
                                              / sum(r["words"] for r in sc))
                             if sum(r["words"] for r in sc) else 0)(
                                 [r for r in rows if r.get("scored", True)]),
            "skip_recommended": total < 1000,
            "sections": [{**r, "priority": classify(r)} for r in rows],
        }, indent=2))
    else:
        sys.stdout.write(render(rows, title, total))

    # Exit 1 when a P1 exists, so a pipeline can gate on it.
    return 1 if any(classify(r) == "P1" for r in rows) else 0


def self_test() -> int:
    import tempfile

    problems: list[str] = []

    dense = (
        "## Methodology overview\n"
        "Acme Corp and Globex Systems partnered with Initech Labs and Umbrella "
        "Group to study crawl budget, index bloat, entity salience and query "
        "fan-out. As we will see, the SERP shifted. Later in this post we "
        "return to it, which matters, although the sample, which was small, "
        "was drawn from 12 sites.\n"
    )
    clean = (
        "## Why this matters\n"
        "A reader has finite attention. Keep one idea per paragraph. Say the "
        "thing plainly. Then say why it holds. A short sentence lands. Write "
        "the way you would explain it to someone standing next to you. Do not "
        "make them hold three unfinished thoughts at once. Finish one, then "
        "start the next. That is the whole rule, and it is enough.\n"
    )

    rows = measure(split_sections(dense + clean), set(DEFAULT_JARGON))
    by_name = {r["section"]: r for r in rows}

    hot = by_name.get("Methodology overview")
    cool = by_name.get("Why this matters")
    if not hot or not cool:
        return _fail(["sections did not split on H2"])

    if hot["load_score"] <= cool["load_score"]:
        problems.append(f"dense section scored {hot['load_score']} vs clean {cool['load_score']}")
    if hot["forward_reference_count"] < 2:
        problems.append(f"forward refs undercounted: {hot['forward_reference_count']}")
    if hot["jargon_introduction_count"] < 3:
        problems.append(f"jargon undercounted: {hot['jargon_introduction_count']}")
    if cool["load_score"] != 0:
        problems.append(f"clean prose scored {cool['load_score']}, expected 0")
    if classify(hot) != "P1":
        problems.append(f"dense section classified {classify(hot)}, expected P1")
    if classify(cool) != "healthy":
        problems.append(f"clean section classified {classify(cool)}, expected healthy")

    # Code must not be counted as prose. The first version of this control
    # fenced `dense` under a "## Sample" heading and asserted section 0 scored
    # 0 — but `dense` STARTS with its own "## " line, so section 0 was empty and
    # scored 0 whatever strip_noise did. Deleting the code-stripping entirely
    # left it green. It now compares the same body scored bare against scored
    # fenced, and checks that a heading inside the fence is not a section.
    body = dense.split("\n", 1)[1]
    bare = measure(split_sections("## Sample\n\n" + body), set(DEFAULT_JARGON))[0]
    fenced = measure(split_sections(strip_noise("## Sample\n\n```\n" + body + "\n```\n")),
                     set(DEFAULT_JARGON))[0]
    if bare["words"] == 0:
        problems.append("the fenced-code control scores an empty section, so it cannot fail")
    if fenced["words"] != 0:
        problems.append(f"a fenced code block was counted as {fenced['words']} prose words")

    # Through the SAME door main() uses. Calling strip_noise here directly made
    # the control blind to whether main() calls it at all: deleting it from
    # main() left this green, which is the defect this control exists for.
    with tempfile.TemporaryDirectory() as tmp:
        doc = pathlib.Path(tmp) / "p.md"
        doc.write_text("# T\n\n## Real\n\n" + body + "\n\n```\n## Fake heading\n```\n",
                       encoding="utf-8")
        out = subprocess.run([sys.executable, str(pathlib.Path(__file__).resolve()),
                              str(doc), "--format", "json"],
                             capture_output=True, text=True, check=False)
        try:
            sections = [r["section"] for r in json.loads(out.stdout)["sections"]]
        except (json.JSONDecodeError, KeyError):
            sections = []
            problems.append("the CLI did not return parseable JSON")
        if "Fake heading" in sections:
            problems.append("a heading inside a fenced block became a section")

    # A CJK post must not report zero words everywhere.
    cjk = measure(split_sections("## 章节\n\n" + "这是一段中文正文,用来测试分词。" * 6),
                  set(DEFAULT_JARGON))[0]
    if cjk["words"] == 0:
        problems.append("a CJK section reported 0 prose words")

    # Jargon must not fire on an English word that merely contains a term.
    if measure(split_sections("## S\n\n" + "The geometry of storage is a serpentine "
                              "problem for any team that ships. " * 4),
               set(DEFAULT_JARGON))[0]["jargon_introduction_count"]:
        problems.append("substring jargon match: geometry/storage/serpentine fired")

    # A density needs a denominator, and a bullet list is not one sentence.
    tiny_rows = measure(split_sections("## Tiny\n\nAcme Corp and Globex.\n"), set(DEFAULT_JARGON))
    if tiny_rows[0]["load_score"] != 0 or classify(tiny_rows[0]) != "unscored":
        problems.append("a four-word section was given a real score")

    bullets = "## Listy\n\n" + "".join(
        f"- A point, with a clause, which extends, and another\n" for _ in range(12))
    depth = measure(split_sections(bullets), set(DEFAULT_JARGON))[0]["avg_clause_depth"]
    if depth > 6:
        problems.append(f"an unpunctuated bullet list read as one sentence (depth {depth})")

    # Jargon is introduced ONCE; a repeat in a later section is not new.
    twice = measure(split_sections(dense + "\n## Again\n" + dense), set(DEFAULT_JARGON))
    if twice[-1]["jargon_introduction_count"] != 0:
        problems.append("jargon re-counted in a later section")

    if problems:
        return _fail(problems)
    print("SELF-TEST PASSED: dense prose outscores clean prose, code is not "
          "counted, jargon counts once, and the P1 rule fires.")
    return 0


def _fail(problems: list[str]) -> int:
    for line in problems:
        print(f"SELF-TEST FAILED: {line}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
