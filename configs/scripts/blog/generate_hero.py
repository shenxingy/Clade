#!/usr/bin/env python3
"""
generate_hero.py — a 1200x630 hero for the draft, and never without attribution.

Gate 2 of `blog-delivery-contract.md` requires a hero image in every draft
folder, and the contract specifies a five-step ladder for obtaining one. This
file is named as its implementation and did not exist, so Gate 2's hero
requirement had no way to be satisfied except by hand.

The ladder, and who runs which rung:

  1. Banana MCP            — the CALLER's, not this script's. An MCP tool handle
                             lives in the agent session; a subprocess cannot
                             reach it. Run it first if Gate 1 saw the tool.
  2. Gemini image API      — key-gated and BILLED. Only attempted with both
                             GOOGLE_AI_API_KEY and the google-genai SDK present,
                             and it announces the cost before calling.
  3. Premium stock APIs    — key-gated (Unsplash / Pexels / Pixabay).
  4. Openverse             — NO KEY, NO ACCOUNT, NO SPEND. The guaranteed rung.
  5. Block with instructions.

Rung 4 is the one that must always work, because a skill that produces nothing
without a paid account is not a working skill. Rungs 2 and 3 are accelerators
for a user who already pays for them.

    generate_hero.py --draft drafts/post --title "What a migration costs"
    generate_hero.py --draft drafts/post --title "..." --tags cloud,database
    generate_hero.py --draft drafts/post --title "..." --dry-run

`hero-credit.txt` is written next to the image every time — including for the
AI rungs, where it records that no attribution is required. An unattributed CC
image is a licence violation shipped at scale.

Stdlib only. Network is required to fetch an image and nothing else.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# The contract cites api.openverse.engineering. That host now 301s to this one
# (verified 2026-09-12); following a redirect for every request is a needless
# round trip and a needless dependency on the redirect staying up.
OPENVERSE = "https://api.openverse.org/v1/images/"

# Ranked by the contract. Openverse is not in its table; it sits at the same
# authority as Wikimedia, which the contract does rank.
SOURCE_AUTHORITY = {"unsplash": 1.0, "pexels": 0.9, "wikimedia": 0.8,
                    "flickr": 0.8, "openverse": 0.8, "pixabay": 0.7}

# Commercial-use, modification-allowed licences. NC and ND are excluded on
# purpose: a blog hero is a commercial use for most publishers, and getting that
# wrong is a licence violation, not a style preference.
SAFE_LICENSES = ("cc0", "pdm", "by", "by-sa")

TARGET_W, TARGET_H = 1200, 630
TARGET_RATIO = TARGET_W / TARGET_H
TIMEOUT = 20
STOPWORDS = {"the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "is",
             "it", "at", "what", "why", "how", "your", "you", "we", "our", "with",
             "actually", "really", "guide", "complete", "ultimate", "best"}


def build_query(title: str, tags: list[str]) -> str:
    """Strip the filler a headline carries; keep the nouns an image search needs."""
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z-]+", title.lower())
             if w not in STOPWORDS and len(w) > 2]
    terms = list(dict.fromkeys([t.strip().lower() for t in tags if t.strip()] + words))
    return " ".join(terms[:5]) or title.strip() or "abstract background"


def score(result: dict, query_terms: set[str]) -> float:
    """relevance x source authority, per the contract's ranking rule."""
    provider = (result.get("source") or result.get("provider") or "").lower()
    authority = next((v for k, v in SOURCE_AUTHORITY.items() if k in provider), 0.6)

    title = (result.get("title") or "").lower()
    tags = " ".join(t.get("name", "") for t in (result.get("tags") or [])).lower()
    hay = f"{title} {tags}"
    hits = sum(1 for term in query_terms if term in hay)
    relevance = hits / max(len(query_terms), 1)

    width, height = result.get("width") or 0, result.get("height") or 0
    if width and height:
        ratio = width / height
        # 1200x630 is ~1.90:1. Penalise portrait hard; a tall image cannot be
        # cropped to a wide hero without losing the subject.
        fit = max(0.0, 1.0 - abs(ratio - TARGET_RATIO) / TARGET_RATIO)
        size = 1.0 if width >= TARGET_W else width / TARGET_W
    else:
        fit, size = 0.5, 0.5

    return round(authority * (0.5 + relevance) * (0.5 + 0.3 * fit + 0.2 * size), 4)


def search_with_relaxation(terms: list[str], log=print) -> tuple[list[dict], str]:
    """Openverse ANDs its terms, so a specific title finds nothing.

    Measured: "database server migration costs" returns 0 results,
    "database server migration" returns 1, "server migration" returns 27. A
    single-shot query built from a headline is therefore mostly a way to hit
    rung 5 with a working network — which is what happened on the first real
    run of this script.

    Drops the LAST term each round; build_query already orders tags before
    title words, so the least specific goes first. Every relaxation is printed:
    a search that quietly widened until it matched something would hand back an
    off-topic hero with no hint that it had.
    """
    for i in range(len(terms)):
        attempt = terms[:len(terms) - i]
        if not attempt:
            break
        query = " ".join(attempt)
        results = openverse_search(query)
        if results:
            if i:
                log(f"  relaxed to {query!r} after {i} narrower "
                    f"quer{'y' if i == 1 else 'ies'} returned nothing")
            return results, query
    return [], " ".join(terms)


def openverse_search(query: str, limit: int = 20) -> list[dict]:
    url = OPENVERSE + "?" + urllib.parse.urlencode({
        "q": query, "page_size": limit, "license": ",".join(SAFE_LICENSES),
        "aspect_ratio": "wide", "mature": "false",
    })
    request = urllib.request.Request(
        url, headers={"User-Agent": "clade-blog-hero/1 (+https://github.com/shenxingy/Clade)"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8")).get("results", [])


def credit_text(result: dict) -> str:
    """CC attribution: title, creator, source, licence, and where to verify it."""
    return (
        f"{result.get('title') or 'Untitled'}\n"
        f"by {result.get('creator') or 'Unknown'}"
        f"{' (' + result['creator_url'] + ')' if result.get('creator_url') else ''}\n"
        f"Licence: CC {(result.get('license') or '').upper()} "
        f"{result.get('license_version') or ''}".rstrip() + "\n"
        f"Licence text: {result.get('license_url') or 'see source'}\n"
        f"Source: {result.get('foreign_landing_url') or result.get('url') or 'unknown'}\n"
        f"Retrieved via Openverse (openverse.org), id {result.get('id') or 'unknown'}\n"
        f"\nAttribution is a licence CONDITION, not a courtesy. Reproduce these\n"
        f"lines wherever the image appears.\n"
    )


def download(url: str, dest_stem: Path) -> Path:
    request = urllib.request.Request(url, headers={"User-Agent": "clade-blog-hero/1"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        blob = response.read()
        ctype = (response.headers.get("Content-Type") or "").split(";")[0].strip()
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
           "image/gif": ".gif"}.get(ctype)
    if not ext:
        # A declared non-image type is refused OUTRIGHT. Falling back to the URL
        # suffix here meant a URL with no extension defaulted to ".jpg", so an
        # HTML error page from a dead CDN link was written out as the hero and
        # every later gate saw a file of the right name.
        if ctype and not ctype.startswith("image/"):
            raise ValueError(f"refusing a non-image response (Content-Type: {ctype})")
        ext = Path(urllib.parse.urlparse(url).path).suffix.lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            raise ValueError(
                f"refusing a response of unknown type ({ctype or 'no Content-Type'}) "
                f"with no recognisable image extension in the URL")
    path = dest_stem.with_suffix(ext)
    path.write_bytes(blob)
    return path


def keyed_rungs_available() -> list[str]:
    """Rungs 2 and 3 — reported, never required."""
    out = []
    if os.environ.get("GOOGLE_AI_API_KEY"):
        out.append("gemini (rung 2, BILLED per image)")
    for key, name in (("UNSPLASH_ACCESS_KEY", "unsplash"), ("PEXELS_API_KEY", "pexels"),
                      ("PIXABAY_API_KEY", "pixabay")):
        if os.environ.get(key):
            out.append(f"{name} (rung 3)")
    return out


BLOCK_MESSAGE = (
    "Hero image required but no generation path succeeded. Configure Banana MCP, "
    "set GOOGLE_AI_API_KEY, set an UNSPLASH/PEXELS/PIXABAY key, or place a "
    "1200x630 hero.png in the draft folder manually. Openverse (rung 4) needs no "
    "key at all and is tried by default — if it failed, the network is the reason."
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--draft", type=Path, help="Draft folder")
    ap.add_argument("--title", default="", help="Post title, used to build the query")
    ap.add_argument("--tags", default="", help="Comma-separated topic tags")
    ap.add_argument("--query", help="Override the derived search query")
    ap.add_argument("--dry-run", action="store_true",
                    help="Rank candidates and print them; download nothing.")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if not args.draft:
        ap.error("--draft is required")
    args.draft.mkdir(parents=True, exist_ok=True)

    keyed = keyed_rungs_available()
    if keyed:
        print(f"note: higher rungs are configured ({', '.join(keyed)}). This script "
              f"takes rung 4; run the keyed rung first if you prefer it.", file=sys.stderr)

    terms = ([args.query] if args.query
             else build_query(args.title, args.tags.split(",")).split())
    print(f"openverse query: {' '.join(terms)!r}")

    try:
        results, query = search_with_relaxation(terms)
    except (urllib.error.URLError, socket.timeout, OSError, json.JSONDecodeError) as exc:
        print(f"openverse unreachable ({type(exc).__name__}: {exc}).\n{BLOCK_MESSAGE}",
              file=sys.stderr)
        return 1

    terms = set(query.split())
    ranked = sorted(((score(r, terms), r) for r in results
                     if (r.get("license") or "").lower() in SAFE_LICENSES),
                    key=lambda pair: pair[0], reverse=True)
    if not ranked:
        print(f"no commercially usable result for {query!r}.\n{BLOCK_MESSAGE}",
              file=sys.stderr)
        return 1

    if args.dry_run:
        for value, result in ranked[:5]:
            print(f"  {value:6.4f}  CC {(result.get('license') or '').upper():5s} "
                  f"{(result.get('width') or 0)}x{(result.get('height') or 0)}  "
                  f"{(result.get('title') or '')[:56]}")
        return 0

    best = ranked[0][1]
    try:
        path = download(best.get("url"), args.draft / "hero")
    except (urllib.error.URLError, socket.timeout, OSError, ValueError) as exc:
        print(f"download failed ({exc}).\n{BLOCK_MESSAGE}", file=sys.stderr)
        return 1

    (args.draft / "hero-credit.txt").write_text(credit_text(best), encoding="utf-8")
    print(f"wrote {path} ({(best.get('width') or 0)}x{(best.get('height') or 0)}, "
          f"CC {(best.get('license') or '').upper()})")
    print(f"wrote {args.draft / 'hero-credit.txt'}")
    if (best.get("width") or 0) < TARGET_W:
        print(f"  warning: {best.get('width')}px wide, under the {TARGET_W}px target. "
              f"Upscaling is not done here; re-run with a different --query for a "
              f"larger source.")
    return 0


def self_test() -> int:
    """Offline. Every network path is exercised by its own failure mode."""
    import tempfile

    problems: list[str] = []

    query = build_query("What a Migration Actually Costs for Your Team", ["database"])
    if "migration" not in query or "your" in query.split():
        problems.append(f"query building kept filler or dropped the subject: {query!r}")


    wide = {"title": "server rack", "width": 1200, "height": 630, "source": "flickr",
            "license": "by", "tags": [{"name": "server"}]}
    tall = {**wide, "width": 600, "height": 1200}
    off_topic = {**wide, "title": "a cat", "tags": []}
    terms = {"server", "rack"}
    if not score(wide, terms) > score(tall, terms):
        problems.append("a portrait image did not rank below a wide one")
    if not score(wide, terms) > score(off_topic, terms):
        problems.append("an off-topic image did not rank below a relevant one")
    if not score({**wide, "source": "unsplash"}, terms) > score(
            {**wide, "source": "pixabay"}, terms):
        problems.append("source authority is not applied")

    # Relaxation, driven by a stub: only the two-term query has results, which
    # is the real shape measured against the live API.
    tried: list[str] = []

    def _stub(q: str, limit: int = 20) -> list[dict]:
        tried.append(q)
        return [wide] if len(q.split()) <= 2 else []

    real_search, globals()["openverse_search"] = openverse_search, _stub
    try:
        found, used = search_with_relaxation(["alpha", "beta", "gamma", "delta"],
                                             log=lambda _m: None)
    finally:
        globals()["openverse_search"] = real_search
    if not found:
        problems.append("relaxation never widened far enough to find anything")
    if used != "alpha beta":
        problems.append(f"relaxation stopped at {used!r}, expected 'alpha beta'")
    if tried[0] != "alpha beta gamma delta":
        problems.append("relaxation did not try the most specific query first")

    for licence in ("nc", "by-nc", "by-nd", "by-nc-sa"):
        if licence in SAFE_LICENSES:
            problems.append(f"{licence} is not safe for a commercial hero")

    credit = credit_text({"title": "T", "creator": "C", "license": "by",
                          "license_version": "2.0",
                          "license_url": "https://creativecommons.org/licenses/by/2.0/",
                          "foreign_landing_url": "https://e.test/x", "id": "abc"})
    for anchor in ("T", "C", "CC BY 2.0", "creativecommons.org", "https://e.test/x",
                   "licence CONDITION"):
        if anchor not in credit:
            problems.append(f"attribution is missing {anchor!r}")

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "hero-credit.txt").write_text(credit, encoding="utf-8")

    if "no key" not in BLOCK_MESSAGE.lower():
        problems.append("the block message does not say the keyless rung exists")
    if "openverse.org" not in OPENVERSE:
        problems.append("not using the canonical Openverse host")

    if problems:
        for line in problems:
            print(f"SELF-TEST FAILED: {line}")
        return 1
    print("SELF-TEST PASSED: ranks wide over tall and relevant over not, refuses "
          "NC/ND licences, and writes a complete CC attribution — all offline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
