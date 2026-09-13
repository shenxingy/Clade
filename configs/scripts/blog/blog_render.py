#!/usr/bin/env python3
"""
blog_render.py — one markdown source, three artifacts that cannot disagree.

Gate 2 of `blog-delivery-contract.md` requires `.md`, `.html`, `.pdf` and a hero
image in every draft folder, and says of the first three: "The .html and .pdf
are rendered from this; they cannot diverge by construction." This file is named
as that implementation and did not exist, so the construction guaranteeing they
could not diverge was not running and Gate 2 could never pass.

    blog_render.py --md drafts/post/my-post.md --out-dir drafts/post
    blog_render.py --md POST.md --out-dir . --no-pdf

HTML is always produced: self-contained, HTML5, JSON-LD BlogPosting, Open Graph
and Twitter Card, dark-mode via prefers-color-scheme, a real <img> for the hero.
PDF needs a renderer — patchright, playwright or weasyprint. With none present
the PDF is reported as NOT produced and the exit code says so; it is never
silently skipped, and no substitute is fabricated.

Markdown: uses the `markdown` package when installed. Without it, a built-in
converter handles the subset the blog skills actually emit — ATX headings,
paragraphs, fenced code, lists, tables, blockquotes, links, images, emphasis,
inline code, horizontal rules. Reference-style links, footnotes, nested lists
beyond one level and raw inline HTML are NOT in that subset, and a document
using them is reported rather than silently mangled.

Stdlib only unless those optional packages happen to be installed. No API key.
"""

from __future__ import annotations

import argparse
import html as _html
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERO_NAMES = ("hero.png", "hero.jpg", "hero.jpeg", "hero.webp")

# Constructs the built-in fallback does not implement. Silently mangling one is
# worse than declining, so their presence is reported.
_UNSUPPORTED = {
    "reference-style link": re.compile(r"^\s*\[[^\]]+\]:\s+\S+", re.M),
    "footnote": re.compile(r"\[\^[^\]]+\]"),
    # Two spaces is a nested list in CommonMark and in every editor's default.
    # Requiring four meant the commonest nesting was flattened with no warning,
    # which the docstring explicitly promises not to do.
    "nested list": re.compile(r"^(?:\t| {2,})(?:[-*+]|\d+[.)])\s+", re.M),
}

_CSS = """\
:root{--bg:#fff;--fg:#1a1a1a;--muted:#5b5b5b;--rule:#e3e3e3;--code:#f5f5f5;--link:#0b5fbe}
@media (prefers-color-scheme:dark){
:root{--bg:#131313;--fg:#e9e9e9;--muted:#a2a2a2;--rule:#2e2e2e;--code:#1e1e1e;--link:#7db4ff}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
article{max-width:44rem;margin:0 auto;padding:2.5rem 1.25rem 5rem}
h1{font-size:2.1rem;line-height:1.2;margin:0 0 .5rem}
h2{font-size:1.45rem;line-height:1.3;margin:2.5rem 0 .75rem;
padding-top:1.25rem;border-top:1px solid var(--rule)}
h3{font-size:1.15rem;margin:1.75rem 0 .5rem}
p,li{color:var(--fg)}
a{color:var(--link)}
img{max-width:100%;height:auto;border-radius:6px}
figure{margin:2rem 0}figcaption{color:var(--muted);font-size:.875rem;margin-top:.5rem}
blockquote{margin:1.5rem 0;padding:.25rem 0 .25rem 1rem;border-left:3px solid var(--rule);
color:var(--muted)}
code{background:var(--code);padding:.15em .35em;border-radius:3px;font-size:.9em}
pre{background:var(--code);padding:1rem;border-radius:6px;overflow-x:auto}
pre code{background:none;padding:0}
table{border-collapse:collapse;width:100%;margin:1.5rem 0;display:block;overflow-x:auto}
th,td{border:1px solid var(--rule);padding:.5rem .65rem;text-align:left}
hr{border:0;border-top:1px solid var(--rule);margin:2.5rem 0}
.byline{color:var(--muted);font-size:.9rem;margin:0 0 2rem}
"""


# ─── frontmatter ───

def split_frontmatter(text: str) -> tuple[dict, str]:
    match = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", text, re.S)
    if not match:
        return {}, text
    meta: dict = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip().strip("'\"")
        if value.startswith("[") and value.endswith("]"):
            meta[key.strip()] = [v.strip().strip("'\"")
                                 for v in value[1:-1].split(",") if v.strip()]
        else:
            meta[key.strip()] = value
    return meta, match.group(2)


# ─── markdown ───

def to_html(md: str) -> tuple[str, list[str]]:
    """(html, warnings). Uses the markdown package when present."""
    warnings = []
    if _installed("markdown"):
        import markdown as _md
        return _md.markdown(md, extensions=["extra", "sane_lists", "toc"]), warnings

    for name, pattern in _UNSUPPORTED.items():
        if pattern.search(md):
            warnings.append(
                f"{name} found, and the built-in converter does not implement it. "
                f"`pip install markdown` for full fidelity — the output below "
                f"leaves it as written rather than guessing.")
    return _fallback(md), warnings


def _inline(text: str) -> str:
    out = _html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", lambda m: f"<code>{m.group(1)}</code>", out)
    # The line was already escaped above, so `&` is now `&amp;`. Escaping the
    # captured URL a SECOND time produced `&amp;amp;` and every link with a
    # query string resolved to a 404 that Gate 5 then reported as a dead link.
    out = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+&quot;([^&]*)&quot;)?\)",
                 lambda m: f'<img src="{m.group(2)}" alt="{m.group(1)}">', out)
    out = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                 lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![*\w])\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", out)
    return out


def _fallback(md: str) -> str:
    lines, out, i = md.splitlines(), [], 0
    while i < len(lines):
        line = lines[i]

        if line.startswith("```") or line.startswith("~~~"):
            fence, i = line[:3], i + 1
            body = []
            while i < len(lines) and not lines[i].startswith(fence):
                body.append(_html.escape(lines[i])); i += 1
            i += 1
            out.append("<pre><code>" + "\n".join(body) + "</code></pre>")
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2).strip())}</h{level}>")
            i += 1
            continue

        if re.match(r"^\s{0,3}(?:---+|\*\*\*+|___+)\s*$", line):
            out.append("<hr>"); i += 1; continue

        if re.match(r"^\s{0,3}\|.*\|\s*$", line):
            rows = []
            while i < len(lines) and re.match(r"^\s{0,3}\|.*\|\s*$", lines[i]):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            if len(rows) >= 2 and all(re.fullmatch(r":?-{2,}:?", c) for c in rows[1]):
                head, body = rows[0], rows[2:]
            else:
                head, body = None, rows
            table = ["<table>"]
            if head:
                table.append("<thead><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in head)
                             + "</tr></thead>")
            table.append("<tbody>")
            for row in body:
                table.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>")
            table += ["</tbody>", "</table>"]
            out.append("".join(table))
            continue

        item = re.match(r"^\s{0,3}([-*+]|\d+[.)])\s+(.*)$", line)
        if item:
            ordered = not item.group(1) in ("-", "*", "+")
            tag = "ol" if ordered else "ul"
            items = []
            while i < len(lines):
                nxt = re.match(r"^\s{0,3}([-*+]|\d+[.)])\s+(.*)$", lines[i])
                if not nxt or (not nxt.group(1) in ("-", "*", "+")) != ordered:
                    break
                items.append(f"<li>{_inline(nxt.group(2).strip())}</li>")
                i += 1
            out.append(f"<{tag}>" + "".join(items) + f"</{tag}>")
            continue

        if line.lstrip().startswith(">"):
            quote = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                quote.append(lines[i].lstrip()[1:].strip()); i += 1
            out.append(f"<blockquote><p>{_inline(' '.join(quote))}</p></blockquote>")
            continue

        if not line.strip():
            i += 1; continue

        para = []
        while i < len(lines) and lines[i].strip() and not re.match(
                r"^(#{1,6}\s|```|~~~|\s{0,3}[-*+]\s|\s{0,3}\d+[.)]\s|\s{0,3}\||>)", lines[i]):
            para.append(lines[i].strip()); i += 1
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
        else:
            # The paragraph loop refuses lines matching its exclusion pattern.
            # If no branch above claimed such a line, `i` never advances and the
            # converter spins forever on a document it merely cannot format.
            # Found by mutating the fence check: the hang, not a wrong result,
            # was the failure. Emit it verbatim rather than dropping it.
            out.append(f"<p>{_inline(lines[i].strip())}</p>")
            i += 1
    return "\n".join(out)


# ─── page ───

def find_hero(out_dir: Path) -> str | None:
    for name in HERO_NAMES:
        if (out_dir / name).is_file():
            return name
    return None


def build_page(meta: dict, body_html: str, slug: str, hero: str | None) -> str:
    title = meta.get("title") or _first_h1(body_html) or slug.replace("-", " ").title()
    desc = meta.get("description") or meta.get("meta_description") or ""
    author = meta.get("author") or "Unknown"
    date = meta.get("date") or meta.get("datePublished") or ""
    canonical = meta.get("canonical") or meta.get("url") or f"/{slug}"

    esc = lambda s: _html.escape(str(s), quote=True)  # noqa: E731
    hero_tag = (f'<img src="{esc(hero)}" alt="{esc(title)}" width="1200" height="630">'
                if hero else "")
    byline = f'<p class="byline">{esc(author)}{f" · {esc(date)}" if date else ""}</p>'
    article = (f"<h1>{esc(title)}</h1>\n{byline}\n{hero_tag}\n{body_html}")

    # Counted from the WHOLE article, which is what Gate 5 measures. Counting
    # the body alone claimed 19 against 23 actual — the title and byline live
    # inside <article> too — and the page failed the ±5% honesty check this
    # very field exists for. Caught by the renderer's own self-test against the
    # gate's own rule.
    word_count = _count_words(article)

    ld = {"@context": "https://schema.org", "@type": "BlogPosting",
          "headline": title, "image": hero or "", "datePublished": date,
          "author": {"@type": "Person", "name": author},
          "wordCount": word_count}
    if desc:
        ld["description"] = desc

    return f"""<!DOCTYPE html>
<html lang="{esc(meta.get('lang', 'en'))}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
{f'<meta name="description" content="{esc(desc)}">' if desc else ''}
<link rel="canonical" href="{esc(canonical)}">
<meta property="og:type" content="article">
<meta property="og:title" content="{esc(title)}">
{f'<meta property="og:description" content="{esc(desc)}">' if desc else ''}
<meta property="og:image" content="{esc(hero or '')}">
<meta property="og:url" content="{esc(canonical)}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(title)}">
{f'<meta name="twitter:description" content="{esc(desc)}">' if desc else ''}
<meta name="twitter:image" content="{esc(hero or '')}">
<style>{_CSS}</style>
<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>
</head>
<body>
<article>
{article}
</article>
</body>
</html>
"""


def _strip_leading_h1(md: str) -> str:
    """Drop the document's own H1; the page renders one from the title.

    `re.sub(r"^#\\s+.*$", "", md, count=1, flags=re.M)` deleted the first line
    starting with "# " ANYWHERE, so a shell comment inside a fenced code block
    became the victim whenever the post had no H1 of its own — silently, in the
    reader's code sample.
    """
    lines, out, fenced, dropped = md.splitlines(keepends=True), [], False, False
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            fenced = not fenced
        elif not fenced and not dropped and re.match(r"#\s+\S", stripped):
            dropped = True
            continue
        out.append(line)
    return "".join(out)


def _count_words(html_fragment: str) -> int:
    """Words a reader sees. Tags out, entities resolved, THEN counted.

    Stripping tags with a regex leaves `&amp;` `&lt;` `&nbsp;` in the text, and
    "amp", "lt" and "nbsp" match the word pattern. A page with a table of
    ampersands claimed more words than it had and was blocked by Gate 5's
    honesty check — the renderer failing the gate it feeds.
    """
    text = re.sub(r"<[^>]+>", " ", html_fragment)
    text = _html.unescape(text)
    return len(re.findall(r"[A-Za-z][A-Za-z'’-]*|[\u4e00-\u9fff\u3040-\u30ff]", text))


def _first_h1(body: str) -> str | None:
    match = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S | re.I)
    return re.sub(r"<[^>]+>", "", match.group(1)).strip() if match else None


# ─── pdf ───

def _installed(name: str) -> bool:
    """find_spec RAISES ModuleNotFoundError when the PARENT package is absent.

    `find_spec("patchright.sync_api")` does not return None on a machine without
    patchright — it raises, and this function tracebacked out of a degradation
    path whose entire purpose was to survive that case.
    """
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def render_pdf(html_path: Path, pdf_path: Path) -> tuple[bool, str]:
    for module in ("patchright", "playwright"):
        if not _installed(module) or not _installed(f"{module}.sync_api"):
            continue
        try:
            api = importlib.import_module(f"{module}.sync_api")
            with api.sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page()
                page.goto(html_path.resolve().as_uri())
                page.pdf(path=str(pdf_path), format="A4", print_background=True)
                browser.close()
            return True, module
        except Exception as exc:  # noqa: BLE001 — try the next engine
            last = f"{module}: {exc}"
    if _installed("weasyprint"):
        try:
            from weasyprint import HTML as _WeasyHTML
            _WeasyHTML(filename=str(html_path)).write_pdf(str(pdf_path))
            return True, "weasyprint"
        except Exception as exc:  # noqa: BLE001
            last = f"weasyprint: {exc}"
    for binary in ("chromium", "chromium-browser", "google-chrome"):
        try:
            with tempfile.TemporaryDirectory() as tmp:
                subprocess.run(
                    [binary, "--headless", "--disable-gpu", f"--user-data-dir={tmp}",
                     f"--print-to-pdf={pdf_path}", "--no-pdf-header-footer",
                     html_path.resolve().as_uri()],
                    check=True, capture_output=True, timeout=90)
            if pdf_path.is_file():
                return True, binary
        except (FileNotFoundError, subprocess.SubprocessError) as exc:
            last = f"{binary}: {type(exc).__name__}"
    return False, locals().get("last", "no PDF engine found")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--md", type=Path, help="Source markdown")
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if not args.md:
        ap.error("--md is required")
    if not args.md.is_file():
        print(f"blog_render: no such file: {args.md}", file=sys.stderr)
        return 2

    out_dir = args.out_dir or args.md.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = args.md.stem

    meta, body_md = split_frontmatter(args.md.read_text(encoding="utf-8", errors="replace"))
    body_md = _strip_leading_h1(body_md)
    body_html, warnings = to_html(body_md)
    hero = find_hero(out_dir)

    html_path = out_dir / f"{slug}.html"
    html_path.write_text(build_page(meta, body_html, slug, hero), encoding="utf-8")
    print(f"wrote {html_path}")
    for warning in warnings:
        print(f"  warning: {warning}")
    if not hero:
        print(f"  warning: no hero image in {out_dir} — Gate 2 requires one of "
              f"{', '.join(HERO_NAMES)}")

    if args.no_pdf:
        return 0
    ok, detail = render_pdf(html_path, out_dir / f"{slug}.pdf")
    if ok:
        print(f"wrote {out_dir / f'{slug}.pdf'} (via {detail})")
        return 0
    print(f"PDF NOT PRODUCED — {detail}. Gate 2 requires it; install one of "
          f"patchright, playwright, weasyprint, or a chromium binary. "
          f"Nothing was substituted.", file=sys.stderr)
    return 1


def self_test() -> int:
    problems: list[str] = []
    src = (
        "---\ntitle: A Real Post\nauthor: Someone\ndate: 2026-09-12\n"
        "description: What it is about.\ncanonical: https://e.test/a-real-post\n---\n\n"
        "# A Real Post\n\nAn opening paragraph with **bold** and `code` and a "
        "[link](https://e.test/x).\n\n"
        "## A section\n\n- one\n- two\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n"
        "```\nnot markdown\n```\n\n> quoted\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "post.md").write_text(src, encoding="utf-8")
        (root / "hero.png").write_bytes(b"\x89PNG\r\n")

        meta, body_md = split_frontmatter(src)
        if meta.get("title") != "A Real Post":
            problems.append(f"frontmatter not parsed: {meta}")
        body_html, _ = to_html(re.sub(r"^#\s+.*$", "", body_md, count=1, flags=re.M))
        page = build_page(meta, body_html, "post", "hero.png")

        for anchor in ('<link rel="canonical"', 'property="og:image"',
                       'name="twitter:card"', "prefers-color-scheme",
                       'type="application/ld+json"', "<!DOCTYPE html>"):
            if anchor not in page:
                problems.append(f"rendered page is missing {anchor}")

        match = re.search(r'application/ld\+json">(.*?)</script>', page, re.S)
        try:
            ld = json.loads(match.group(1))
        except Exception:  # noqa: BLE001
            problems.append("JSON-LD is not valid JSON")
            ld = {}
        for field in ("headline", "image", "datePublished", "author", "wordCount"):
            if not ld.get(field):
                problems.append(f"JSON-LD missing {field}")
        if ld.get("@type") != "BlogPosting":
            problems.append("JSON-LD @type is not BlogPosting")

        # The wordCount must survive Gate 5's own ±5% check against this page.
        article = re.search(r"<article>(.*)</article>", page, re.S).group(1)
        actual = len(re.findall(r"[A-Za-z][A-Za-z'’-]*", re.sub(r"<[^>]+>", " ", article)))
        claimed = ld.get("wordCount", 0)
        if actual and abs(claimed - actual) > 0.05 * actual:
            problems.append(f"wordCount {claimed} vs {actual} — fails the gate that "
                            f"reads this very field")

        for anchor in ("<strong>bold</strong>", "<code>code</code>", "<ul>", "<table>",
                       "<pre><code>", "<blockquote>", 'href="https://e.test/x"'):
            if anchor not in page:
                problems.append(f"markdown not converted: {anchor}")

        # The fixture fence must CONTAIN emphasis markers, or the assertion is
        # vacuous: the first version fenced the literal text "not markdown",
        # which has no asterisks, so deleting the fence handling left it green.
        fenced_page = build_page({}, to_html("```\ncode *with* stars\n```\n")[0],
                                 "p", None)
        inside = fenced_page.split("<pre>")[-1].split("</pre>")[0]
        if "*with*" not in inside:
            problems.append("the code-fence control lost its own emphasis markers")
        if "<em>" in inside:
            problems.append("emphasis was applied inside a code fence")

        # An entity is not a word. `&amp;` counted as "amp", inflating wordCount
        # until the page failed the Gate 5 check that reads that very field.
        if _count_words("<p>a &amp; b &lt; c</p>") != 3:
            problems.append(
                f"entities counted as words: got {_count_words('<p>a &amp; b &lt; c</p>')}")

        # The h1 strip must not reach inside a fenced block.
        stripped = _strip_leading_h1("Intro line.\n\n```\n# not a heading\n```\n")
        if "# not a heading" not in stripped:
            problems.append("the h1 strip deleted a comment inside a code fence")
        if _strip_leading_h1("# Real Title\n\nBody.\n").lstrip().startswith("#"):
            problems.append("the h1 strip did not remove a real leading h1")

        # A URL must be escaped once, not twice.
        linked, _ = to_html("See [it](https://e.test/x?a=1&b=2).\n")
        if "&amp;amp;" in linked:
            problems.append("a URL was HTML-escaped twice")

        if "<h1>A Real Post</h1>" not in page:
            problems.append("the h1 is missing or duplicated")
        if page.count("<h1") != 1:
            problems.append(f"expected exactly one h1, found {page.count('<h1')}")

        # Force the built-in converter. `to_html` returns early with no warnings
        # when the `markdown` package is installed, so this control FAILED the
        # whole self-test on any machine that had it — the opposite of a dead
        # assertion, and just as wrong.
        saved = globals()["_installed"]
        globals()["_installed"] = lambda name: False if name == "markdown" else saved(name)
        try:
            for construct, text in (
                    ("reference-style link", "[ref]: https://e.test\n\nSee [ref].\n"),
                    ("footnote", "A claim[^1].\n\n[^1]: the note.\n"),
                    ("nested list", "- one\n  - nested\n")):
                if not to_html(text)[1]:
                    problems.append(f"the fallback converter did not warn on a {construct}")
        finally:
            globals()["_installed"] = saved

    if problems:
        for line in problems:
            print(f"SELF-TEST FAILED: {line}")
        return 1
    print("SELF-TEST PASSED: renders a self-contained page with canonical, OG, "
          "Twitter, dark mode and valid BlogPosting JSON-LD whose wordCount "
          "survives the gate that reads it; warns on constructs it cannot convert.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
