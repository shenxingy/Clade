#!/usr/bin/env python3
"""
blog_preflight.py — the five gates that stand between a draft and the user.

`blog-delivery-contract.md` states the problem it exists for: skills had
reviewers, the reviewer ran as advisory, and the writer presented sloppy drafts
anyway. The fix is infrastructure, not effort. The contract then specifies five
gates in full — and named this file as their implementation while the file did
not exist, so every gate has been advisory for the whole v1.9 line and the user
has been the first reviewer the contract promised they would never be.

    blog_preflight.py --draft drafts/my-post
    blog_preflight.py --draft drafts/my-post --gate 1
    blog_preflight.py --draft drafts/my-post --strict
    blog_preflight.py --self-test

Gate 1 Capability discovery  → writes capabilities.json
Gate 2 Format completeness   → .md, .html, .pdf, hero image all present
Gate 3 Visual verification   → needs patchright; degrades loudly, never silently
Gate 4 Content review        → reads the reviewer's BLOCKING: line from review.md
Gate 5 Assets + link integrity

Writes `<draft>/preflight-report.json`. Exit 0 = ship, 1 = blocked, 2 = usage.

Stdlib only, and **no API key is required for any gate**. Network is used for
one thing — HTTP HEAD on external links in Gate 5 — and when it is unavailable
those links are reported NOT CHECKED. A gate that cannot run says so; it never
reports a pass it did not earn.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from html import unescape as _unescape
from html.parser import HTMLParser
from pathlib import Path

CONTRACT_VERSION = "clade.blog.preflight/v1"

# Gate 1 probes these by NAME only. A value is never read, logged or written.
ENV_KEYS = ("GOOGLE_AI_API_KEY", "UNSPLASH_ACCESS_KEY", "PEXELS_API_KEY",
            "PIXABAY_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")
OPTIONAL_DEPS = ("patchright", "playwright", "weasyprint", "google.genai", "requests")
MANDATORY_AGENTS = ("blog-reviewer",)
OPTIONAL_AGENTS = ("blog-researcher", "blog-writer", "blog-seo", "blog-translator")
HELPER_SCRIPTS = ("analyze_blog.py", "lint_prose.py", "cognitive_load.py")
ROOT_CONTEXT = ("BRAND.md", "VOICE.md", "DISCOURSE.md")

LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "example.com",
               "example.org", "example.net"}
HERO_NAMES = ("hero.png", "hero.jpg", "hero.jpeg", "hero.webp")
LINK_TIMEOUT = 8


# ─── helpers ───

def _blocked(name: str, reason: str, **extra) -> dict:
    return {"gate": name, "status": "block", "reason": reason, **extra}


def _passed(name: str, note: str = "", **extra) -> dict:
    return {"gate": name, "status": "pass", "reason": note, **extra}


def _skipped(name: str, reason: str, **extra) -> dict:
    """Not run. Deliberately its own status — 'nothing ran' must not look like 'passed'."""
    return {"gate": name, "status": "skip", "reason": reason, **extra}


def _warned(name: str, reason: str, **extra) -> dict:
    return {"gate": name, "status": "warn", "reason": reason, **extra}


def has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def claude_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))


def slug_of(draft: Path) -> str | None:
    mds = [p for p in sorted(draft.glob("*.md")) if p.name not in ("review.md", "README.md")]
    return mds[0].stem if mds else None


class _Tags(HTMLParser):
    """Collect what Gate 5 needs. A regex over HTML is a bug with a schedule."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.imgs: list[str] = []
        self.links: list[str] = []
        self.meta: dict[str, str] = {}
        self.canonical: str | None = None
        self.jsonld: list[str] = []
        self._in_ld = False
        self.article_text: list[str] = []
        self._depth = 0
        self.codes: list[str] = []
        self._in_code = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "img" and a.get("src"):
            self.imgs.append(a["src"])
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag == "meta":
            key = a.get("property") or a.get("name")
            if key and a.get("content"):
                self.meta[key] = a["content"]
        elif tag == "link" and a.get("rel", "").lower() == "canonical":
            self.canonical = a.get("href")
        elif tag == "script" and a.get("type") == "application/ld+json":
            self._in_ld = True
        elif tag == "article":
            self._depth += 1
        elif tag == "code":
            self._in_code = True

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_ld = False
        elif tag == "article" and self._depth:
            self._depth -= 1
        elif tag == "code":
            self._in_code = False

    def handle_data(self, data):
        if self._in_ld:
            self.jsonld.append(data)
        if self._depth:
            self.article_text.append(data)
        if self._in_code:
            self.codes.append(data.strip())


def head_ok(url: str) -> tuple[bool | None, str]:
    """(True ok, False bad, None not checked)."""
    request = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "clade-blog-preflight/1"})
    try:
        with urllib.request.urlopen(request, timeout=LINK_TIMEOUT) as response:
            return (200 <= response.status < 400), str(response.status)
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 405):          # HEAD refused, not a dead link
            return None, f"HTTP {exc.code} on HEAD (not checked)"
        return False, f"HTTP {exc.code}"
    except (urllib.error.URLError, socket.timeout, OSError) as exc:
        return None, f"unreachable ({type(exc).__name__}) — NOT CHECKED"


# ─── Gate 1: capability discovery ───

def gate1(draft: Path, project: Path) -> dict:
    scripts = claude_dir() / "scripts" / "blog"
    caps = {
        "contract": CONTRACT_VERSION,
        "env_keys_present": sorted(k for k in ENV_KEYS if os.environ.get(k)),
        "optional_deps": {d: has_module(d) for d in OPTIONAL_DEPS},
        "root_context": {f: (project / f).is_file() for f in ROOT_CONTEXT},
        "agents": {},
        "helper_scripts": {},
    }
    for agent in MANDATORY_AGENTS + OPTIONAL_AGENTS:
        caps["agents"][agent] = any(
            (base / "agents" / f"{agent}.md").is_file()
            for base in (claude_dir(), project / "configs", project)
        )
    for script in HELPER_SCRIPTS:
        caps["helper_scripts"][script] = (scripts / script).is_file() or \
            (project / "configs" / "scripts" / "blog" / script).is_file()

    # An image path that needs no key at all: Openverse is a keyless CC search.
    keyed = [k for k in ("GOOGLE_AI_API_KEY", "UNSPLASH_ACCESS_KEY",
                         "PEXELS_API_KEY", "PIXABAY_API_KEY") if os.environ.get(k)]
    caps["image_paths"] = {"keyed_sources": keyed, "openverse_keyless": True}

    draft.mkdir(parents=True, exist_ok=True)
    (draft / "capabilities.json").write_text(json.dumps(caps, indent=2), encoding="utf-8")

    missing = [a for a in MANDATORY_AGENTS if not caps["agents"][a]]
    if missing:
        return _blocked("1 capability discovery",
                        f"mandatory agent(s) missing: {', '.join(missing)}. "
                        f"Gate 4 cannot run without a reviewer.", capabilities=caps)

    unused = [d for d, ok in caps["optional_deps"].items() if not ok]
    return _passed("1 capability discovery",
                   f"{len(caps['env_keys_present'])} key(s) present by name, "
                   f"{sum(caps['optional_deps'].values())}/{len(OPTIONAL_DEPS)} optional deps, "
                   f"image path available (Openverse needs no key)."
                   + (f" Absent, non-blocking: {', '.join(unused)}." if unused else ""),
                   capabilities=caps)


# ─── Gate 2: format completeness ───

def gate2(draft: Path) -> dict:
    slug = slug_of(draft)
    if not slug:
        return _blocked("2 format completeness", "no <slug>.md in the draft folder")
    want = {f"{slug}.md": draft / f"{slug}.md",
            f"{slug}.html": draft / f"{slug}.html",
            f"{slug}.pdf": draft / f"{slug}.pdf"}
    missing = [n for n, p in want.items() if not p.is_file()]
    hero = [n for n in HERO_NAMES if (draft / n).is_file()]
    if not hero:
        missing.append("hero image (" + "/".join(HERO_NAMES) + ")")
    if missing:
        return _blocked("2 format completeness",
                        f"missing artifact(s): {', '.join(missing)}", missing=missing)
    return _passed("2 format completeness", f"all four artifacts present for {slug}")


# ─── Gate 3: visual verification ───

def gate3(draft: Path) -> dict:
    slug = slug_of(draft)
    html = draft / f"{slug}.html" if slug else None
    if not html or not html.is_file():
        return _blocked("3 visual verification", "no rendered .html to inspect")

    findings = validate_jsonld(html.read_text(encoding="utf-8", errors="replace"))
    if findings:
        return _blocked("3 visual verification", "; ".join(findings), findings=findings)

    if not (has_module("patchright") or has_module("playwright")):
        # Loud, and its own status. The contract permits proceeding; it does not
        # permit calling this a pass.
        return _skipped(
            "3 visual verification",
            "patchright/playwright not installed — screenshots, SVG overflow, "
            "dark-mode and console-error checks did NOT run. JSON-LD was checked "
            "and is valid. Install patchright for full Gate 3 coverage.")
    # Installing patchright must not turn four unrun checks into a PASS. This
    # returned _passed the moment the module was importable, so the ONLY
    # difference the install made was replacing an honest SKIP with a false
    # pass — the gate got weaker as the machine got more capable.
    return _skipped(
        "3 visual verification",
        "JSON-LD is valid. Screenshots, SVG overflow, dark-mode and "
        "console-error checks did NOT run here: they need a live browser at "
        "three viewports, which the skill drives. A browser is available "
        "(patchright/playwright importable), so run that loop — this process "
        "does not, and will not report a pass it did not earn.")


def validate_jsonld(html: str) -> list[str]:
    blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.S | re.I)
    if not blocks:
        return ["no JSON-LD block found"]
    problems = []
    posting = None
    for raw in blocks:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            problems.append(f"JSON-LD is not valid JSON: {exc}")
            continue
        for node in (data if isinstance(data, list) else [data]):
            if isinstance(node, dict) and node.get("@type") == "BlogPosting":
                posting = node
    if posting is None and not problems:
        problems.append("no JSON-LD node with @type BlogPosting")
    if posting:
        for field in ("headline", "image", "datePublished", "author"):
            if not posting.get(field):
                problems.append(f"BlogPosting is missing required field {field!r}")
    return problems


# ─── Gate 4: content review ───

_BLOCKING = re.compile(r"^BLOCKING:\s*(true|false)\b\s*(?:\((.*?)\))?\s*$", re.M | re.I)


def gate4(draft: Path) -> dict:
    review = draft / "review.md"
    if not review.is_file():
        return _blocked("4 content review",
                        "review.md absent — the reviewer has not run. The contract "
                        "makes this blocking: the user is never the first reader.")
    matches = _BLOCKING.findall(review.read_text(encoding="utf-8", errors="replace"))
    if not matches:
        return _blocked("4 content review",
                        "review.md carries no machine-readable 'BLOCKING:' line. "
                        "The contract requires it as the scorecard's last line.")
    verdict, why = matches[-1]
    if verdict.lower() == "true":
        return _blocked("4 content review", why or "reviewer blocked the draft")
    return _passed("4 content review", why or "reviewer cleared the draft")


# ─── Gate 5: assets + link integrity ───

def gate5(draft: Path, project: Path, check_links: bool) -> dict:
    slug = slug_of(draft)
    html_path = draft / f"{slug}.html" if slug else None
    if not html_path or not html_path.is_file():
        return _blocked("5 assets + links", "no rendered .html to inspect")

    html = html_path.read_text(encoding="utf-8", errors="replace")
    parser = _Tags()
    parser.feed(html)

    problems: list[str] = []
    unchecked: list[str] = []

    def check_asset(url: str, label: str) -> None:
        if not url:
            return
        if url.startswith(("http://", "https://")):
            host = re.sub(r"^https?://([^/:]+).*", r"\1", url)
            if host in LOCAL_HOSTS:
                return
            if not check_links:
                unchecked.append(f"{label} {url}")
                return
            ok, detail = head_ok(url)
            if ok is None:
                unchecked.append(f"{label} {url} — {detail}")
            elif not ok:
                problems.append(f"{label} {url} — {detail}")
        elif not url.startswith("data:"):
            # Strip the query and fragment and percent-decode before touching
            # the filesystem. `hero.png?v=2` and `img/my%20hero.png` were both
            # reported missing while sitting right there on disk.
            local = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
            if not local:
                return
            candidates = [draft / local, project / local.lstrip("/")]
            if local.startswith("/"):
                candidates.append(draft / local.lstrip("/"))
            if not any(c.exists() for c in candidates):
                problems.append(f"{label} {url} does not exist on disk")

    for src in parser.imgs:
        check_asset(src, "<img>")
    og = parser.meta.get("og:image")
    if not og:
        problems.append("og:image is not set — the social-preview asset is load-bearing")
    else:
        check_asset(og, "og:image")

    for href in parser.links:
        if href.startswith("https://"):
            check_asset(href, "<a>")

    if not parser.canonical:
        problems.append("<link rel=canonical> is not set")
    elif not parser.canonical.startswith(("http://", "https://", "/")):
        problems.append(f"canonical is not well-formed: {parser.canonical}")

    # <code>filename.ext</code> must name a real file or be marked hypothetical.
    marked = "hypothetical" in html.lower() or "for illustration" in html.lower()
    if not marked:
        for code in parser.codes:
            # A version number is not a filename. `3.11`, `v1.2.3`, `0.5` and
            # `1.9.0` all satisfy "word chars, a dot, a short suffix", so a
            # correct draft mentioning a Python version was blocked for naming
            # a file that does not exist.
            if not re.fullmatch(r"[\w./-]+\.[A-Za-z0-9]{1,5}", code or ""):
                continue
            if re.fullmatch(r"v?\d+(?:\.\d+)+", code):
                continue                                   # 3.11, v1.2.3, 0.5.0
            if not re.search(r"\.[A-Za-z][A-Za-z0-9]{0,4}$", code):
                continue                                   # suffix must be alphabetic
            if True:
                if not (project / code).exists() and not (draft / code).exists():
                    problems.append(f"<code>{code}</code> names no file in the project "
                                    f"and the page is not marked hypothetical")

    # wordCount honesty: JSON-LD vs the actual <article> body, ±5%.
    for raw in re.findall(
            r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for node in (data if isinstance(data, list) else [data]):
            if not (isinstance(node, dict) and node.get("wordCount")):
                continue
            try:
                claimed = int(str(node["wordCount"]).strip().replace(",", ""))
            except (TypeError, ValueError):
                # `int("1,715")` and `int("about 1700")` raised straight out of
                # gate5, so a malformed field killed the run instead of failing
                # it, and preflight-report.json was never written.
                problems.append(
                    f"JSON-LD wordCount is not a number: {node['wordCount']!r}")
                continue
            body = " ".join(parser.article_text)
            if not body.strip():
                # _Tags counts only text inside <article>. A page that uses
                # <main> or a bare <body> gave an empty string, `actual` was 0,
                # and `if actual and ...` skipped the honesty check silently on
                # exactly the pages a hand-written renderer produces.
                body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
                body = re.sub(r"<[^>]+>", " ", body)
            actual = len(re.findall(r"[A-Za-z][A-Za-z'’-]*", _unescape(body)))
            if not actual:
                problems.append("JSON-LD declares a wordCount but the page has no prose")
            elif abs(claimed - actual) > 0.05 * actual:
                problems.append(
                    f"JSON-LD wordCount {claimed} vs {actual} actual "
                    f"({abs(claimed - actual) / actual:.0%} off, tolerance 5%)")

    if problems:
        return _blocked("5 assets + links", "; ".join(problems[:8]),
                        problems=problems, unchecked=unchecked)
    if unchecked:
        return _warned("5 assets + links",
                       f"{len(unchecked)} external URL(s) NOT CHECKED (offline or "
                       f"HEAD refused). Everything reachable passed.",
                       unchecked=unchecked)
    return _passed("5 assets + links",
                   f"{len(parser.imgs)} image(s), {len(parser.links)} link(s), "
                   f"canonical and og:image present")


# ─── driver ───

GATES = {1: "capability discovery", 2: "format completeness", 3: "visual verification",
         4: "content review", 5: "assets + links"}


def run(draft: Path, project: Path, only: int | None, check_links: bool) -> dict:
    results = []
    for number in sorted(GATES):
        if only and number != only:
            continue
        if number == 1:
            results.append(gate1(draft, project))
        elif number == 2:
            results.append(gate2(draft))
        elif number == 3:
            results.append(gate3(draft))
        elif number == 4:
            results.append(gate4(draft))
        else:
            results.append(gate5(draft, project, check_links))
        # The contract: first failure halts the chain and triggers the loop.
        if results[-1]["status"] == "block":
            break
    return {"contract": CONTRACT_VERSION, "draft": str(draft), "gates": results,
            "blocking": any(r["status"] == "block" for r in results)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--draft", type=Path, help="Draft folder")
    ap.add_argument("--project", type=Path, default=Path.cwd())
    ap.add_argument("--gate", type=int, choices=sorted(GATES))
    ap.add_argument("--strict", action="store_true",
                    help="Treat a skipped or warned gate as a block.")
    ap.add_argument("--no-network", action="store_true",
                    help="Do not make HEAD requests; report those links NOT CHECKED.")
    ap.add_argument("--format", choices=("markdown", "json"), default="markdown")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if not args.draft:
        ap.error("--draft is required")
    if not args.draft.is_dir():
        print(f"blog_preflight: no such draft folder: {args.draft}", file=sys.stderr)
        return 2

    report = run(args.draft, args.project, args.gate, not args.no_network)
    (args.draft / "preflight-report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")

    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        icon = {"pass": "PASS", "block": "BLOCK", "skip": "SKIP", "warn": "WARN"}
        print(f"## Preflight — {args.draft}\n")
        for row in report["gates"]:
            print(f"{icon[row['status']]:5s} Gate {row['gate']}")
            if row["reason"]:
                print(f"      {row['reason']}")
        halted = len(report["gates"]) < len(GATES) and not args.gate
        if halted:
            # Name the gates that did NOT run. "Nothing ran" and "everything
            # passed" must never look alike in this report.
            ran = {row["gate"].split()[0] for row in report["gates"]}
            skipped = [f"{n} {name}" for n, name in sorted(GATES.items())
                       if str(n) not in ran]
            print(f"\nHalted at Gate {report['gates'][-1]['gate']}. "
                  f"Did NOT run: {', '.join(skipped)}.")
        print(f"\nBLOCKING: {'true' if report['blocking'] else 'false'}")

    if report["blocking"]:
        return 1
    if args.strict and any(r["status"] in ("skip", "warn") for r in report["gates"]):
        return 1
    return 0


def self_test() -> int:
    import tempfile

    problems: list[str] = []
    good_ld = json.dumps({"@type": "BlogPosting", "headline": "H", "image": "hero.png",
                          "datePublished": "2026-01-01", "author": {"name": "A"}})

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        draft = root / "d"
        draft.mkdir()

        # Gate 2 blocks with nothing present, and names what is missing.
        if gate2(draft)["status"] != "block":
            problems.append("Gate 2 passed an empty draft folder")

        (draft / "post.md").write_text("# T\n", encoding="utf-8")
        (draft / "post.pdf").write_bytes(b"%PDF-1.4\n")
        (draft / "hero.png").write_bytes(b"\x89PNG\r\n")
        html = (f'<html><head><link rel="canonical" href="https://e.test/p">'
                f'<meta property="og:image" content="hero.png">'
                f'<script type="application/ld+json">{good_ld}</script></head>'
                f'<body><article><img src="hero.png">words words words</article>'
                f'</body></html>')
        (draft / "post.html").write_text(html, encoding="utf-8")

        if gate2(draft)["status"] != "pass":
            problems.append(f"Gate 2 blocked a complete draft: {gate2(draft)['reason']}")

        # Gate 1 BLOCKS without the reviewer. Only the empty-folder case was
        # covered, which fails on everything at once, so deleting this one
        # requirement changed nothing the self-test could see.
        import types as _types
        saved_dir = globals()["claude_dir"]
        globals()["claude_dir"] = lambda: Path(tmp) / "no-such-claude"
        try:
            if gate1(draft, Path(tmp) / "no-such-project")["status"] != "block":
                problems.append("Gate 1 passed with the mandatory reviewer agent absent")
        finally:
            globals()["claude_dir"] = saved_dir
        del _types

        # Gate 2 must block on the hero ALONE, with the other three present.
        hero_only = Path(tmp) / "hero-missing"
        hero_only.mkdir()
        (hero_only / "p.md").write_text("# T\n", encoding="utf-8")
        (hero_only / "p.html").write_text("<html></html>", encoding="utf-8")
        (hero_only / "p.pdf").write_bytes(b"%PDF")
        if gate2(hero_only)["status"] != "block":
            problems.append("Gate 2 passed a draft with no hero image")

        # Gate 3 must never call an unrun browser check a pass.
        g3 = gate3(draft)
        if g3["status"] not in ("pass", "skip"):
            problems.append(f"Gate 3 on valid JSON-LD returned {g3['status']}")
        if not (has_module("patchright") or has_module("playwright")):
            if g3["status"] != "skip":
                problems.append("Gate 3 reported a pass with no browser installed")
            elif "did NOT run" not in g3["reason"]:
                problems.append("Gate 3 skip does not say what did not run")

        bad = draft / "bad.html"
        bad.write_text('<script type="application/ld+json">{oops</script>', encoding="utf-8")
        if not validate_jsonld(bad.read_text()):
            problems.append("invalid JSON-LD was accepted")
        if not validate_jsonld(f'<script type="application/ld+json">'
                               f'{json.dumps({"@type": "BlogPosting"})}</script>'):
            problems.append("a BlogPosting missing every required field was accepted")

        # Gate 4 is blocking in BOTH absent cases the contract names.
        if gate4(draft)["status"] != "block":
            problems.append("Gate 4 passed with no review.md")
        (draft / "review.md").write_text("Scorecard\n", encoding="utf-8")
        if gate4(draft)["status"] != "block":
            problems.append("Gate 4 passed a review with no BLOCKING: line")
        (draft / "review.md").write_text("BLOCKING: true (Overall 87/100)\n", encoding="utf-8")
        if gate4(draft)["status"] != "block":
            problems.append("Gate 4 ignored BLOCKING: true")
        (draft / "review.md").write_text("BLOCKING: false (cleared all gates)\n",
                                         encoding="utf-8")
        if gate4(draft)["status"] != "pass":
            problems.append("Gate 4 blocked on BLOCKING: false")

        # Gate 5 offline: a missing local asset still blocks; remote is NOT CHECKED.
        g5 = gate5(draft, root, check_links=False)
        if g5["status"] != "pass":
            problems.append(f"Gate 5 blocked a clean page: {g5['reason']}")

        (draft / "post.html").write_text(
            html.replace('src="hero.png"', 'src="missing.png"'), encoding="utf-8")
        if gate5(draft, root, check_links=False)["status"] != "block":
            problems.append("Gate 5 passed an <img> pointing at nothing")

        (draft / "post.html").write_text(
            html.replace('<link rel="canonical" href="https://e.test/p">', ""),
            encoding="utf-8")
        if gate5(draft, root, check_links=False)["status"] != "block":
            problems.append("Gate 5 passed a page with no canonical")

        (draft / "post.html").write_text(
            html.replace('<meta property="og:image" content="hero.png">', ""),
            encoding="utf-8")
        if gate5(draft, root, check_links=False)["status"] != "block":
            problems.append("Gate 5 passed a page with no og:image")

        # The chain halts on the first block rather than reporting later gates.
        empty = root / "e"
        empty.mkdir()
        report = run(empty, root, None, check_links=False)
        if len(report["gates"]) >= len(GATES):
            problems.append("the chain did not halt on the first blocking gate")
        if not report["blocking"]:
            problems.append("a blocked run reported blocking=false")

    if problems:
        for line in problems:
            print(f"SELF-TEST FAILED: {line}")
        return 1
    print("SELF-TEST PASSED: every gate blocks on its own failure, the chain halts "
          "on the first block, and an unrun browser check reports SKIP rather than "
          "a pass it did not earn.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
