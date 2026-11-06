#!/usr/bin/env python3
"""pr-verification-gaps.py — what did merged PRs say they could not verify, and how deeply were they read?

Why this exists
---------------
Every PR body the delivery skills write (``/create-pr`` §4, ``/delivery`` §6,
``/ship``) and this repository's ``.github/PULL_REQUEST_TEMPLATE.md`` carry two
fixed lines:

    Review depth: none | skimmed | read-in-full
    Could not verify: none | <item>; <item>

One unverified item is a caveat. The same item in PR after PR is a missing
capability, and Larson (*adopting verification pattern*, 2026-10-30) names what
to do with the list: "That list is your roadmap". Nothing collected those lists,
and nothing said how deeply a PR had been read: the 2026-11-05 essay sweep
counted 34 of 34 recent Clade PRs merged with no reviewer but the author (TODO.md,
that sweep's section). ``/retro`` runs this and shows the top recurring items as
candidate TODO entries. It writes nothing.

What it reports
---------------
For one repository (``--repo``, default the one gh resolves from the working
directory), every PR merged in the window (``--since`` days, default 7), by any
author:

- Could not verify: how many PRs state the line, say ``none``, left it unfilled
  (the template's ``<…>`` placeholder, the ``a | b`` format itself, or nothing),
  or carry no line; every item, grouped by its words (case, ``*`` and backtick
  emphasis, trailing punctuation and a trailing ``(reason)`` are ignored); and
  the top ``--top`` (default 3) items that recur in 2 or more distinct PRs,
  ranked by PR count, then by the latest merge, then by name.
- Review depth: none / skimmed / read-in-full, plus unfilled, unparsed and
  missing, and two cross-checks against the forge: a PR claiming a reading with
  no submitted review by anyone but its author, and a PR saying ``none`` that
  carries such a review (a line nobody updated).

What it cannot see
------------------
- Both lines are SELF-REPORTED. An author may rate the depth high; the forge
  cross-check flags a claim no review backs, but a reader outside GitHub (an
  agent review run, a call) leaves no review there, so a flag is a question for
  the author, not a verdict.
- A PR without the line is not a verified PR. The rollup covers only the PRs
  that state it and says how many that is; with none stating it, the section
  reads NOT MEASURED, never "nothing unverified".
- Items are grouped by their words. Two phrasings of one gap count apart, which
  is why the delivery skills ask authors to reuse an earlier PR's wording.
- Lines inside an HTML comment or a fenced code block, or opening in inline
  code, are not read: the template's comment explains the format, and a PR
  describing it quotes it.

Data: one ``gh pr list --state merged --search merged:>=<day>`` (at most
``_GH_LIMIT`` PRs; reaching the cap is noted), plus ``gh repo view`` when no
``--repo`` is given. ``--fixture DIR`` reads the same raw output from files. No
gh call carries ``--jq``, so the self-test's fixtures hold gh's raw output.

Stdlib only, on purpose: the syntax-check CI job installs no dependencies.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

DEPTHS = ("none", "skimmed", "read-in-full")
_GH_LIMIT = 1000
_RECURS = 2  # an item is recurring once two distinct PRs name it
_PR_FIELDS = "number,title,url,body,author,mergedAt,reviews"
_REPO_NAME = re.compile(r"^[\w.-]+/[\w.-]+$")

# ─── Reading one PR body ────────────────────────────────────────────────────

# A label at the start of a line, after any list bullet, quote marker or bold. Not after a backtick: a line that
# opens with `Review depth: …` in inline code is quoting the format, as a PR describing it does.
_LINE = re.compile(r"^[\s>*-]*(review depth|could not verify)[*`\s]*:[*`\s]*(.*?)[*`\s]*$", re.I)
_DEPTH = re.compile(r"^(none|skimmed|read[- ]in[- ]full)\b[.,;:]?\s*(.*)$", re.I)
_FENCE = re.compile(r"^\s*(```|~~~)")
_REASON = re.compile(r"\s*\(([^()]*)\)$")
_EMPHASIS = re.compile(r"[*`]")  # not `_`: an identifier such as test_foo is a word, not emphasis
_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.S)


def _visible_lines(body: str) -> list[str]:
    """BODY's lines outside HTML comments and fenced code: a format explained or quoted is not a statement.

    An unclosed ``<!--`` hides the rest of the body on GitHub, so it hides it here too."""
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    text = _COMMENT.sub("", text)
    lines: list[str] = []
    fenced = False
    for line in text.split("\n"):
        if _FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            lines.append(line)
    return lines


def _unfilled(value: str) -> bool:
    """The template's `<…>` placeholder, the skill's own `a | b` format line, or nothing at all."""
    return not value or value.startswith("<") or "|" in value


def _depth(value: str | None) -> dict[str, Any]:
    if value is None:
        return {"state": "missing"}
    if _unfilled(value):
        return {"state": "unfilled", "raw": value}
    match = _DEPTH.match(value)
    if not match:
        return {"state": "unparsed", "raw": value}
    return {"state": "stated", "depth": re.sub(r"\s", "-", match.group(1).lower()), "by": match.group(2).strip()}


def _item(text: str) -> tuple[str, str, str]:
    """(key, label, reason) of one could-not-verify item. 'macOS run (no Mac)' and '**macos run**.' share a key."""
    flat = " ".join(_EMPHASIS.sub("", text).split()).rstrip(" .,:")
    match = _REASON.search(flat)
    if match and match.start() > 0:
        label, reason = flat[:match.start()].rstrip(" .,:"), match.group(1).strip()
    else:
        label, reason = flat, ""
    label = label.strip(" \"'")
    return label.lower(), label, reason


def _unverified(value: str | None) -> dict[str, Any]:
    if value is None:
        return {"state": "missing"}
    if _unfilled(value):
        return {"state": "unfilled", "raw": value}
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for part in value.split(";"):
        key, label, reason = _item(part)
        if key and key not in seen:
            seen.add(key)
            items.append({"key": key, "label": label, "reason": reason})
    items = [item for item in items if item["key"] != "none"]
    return {"state": "stated", "items": items} if items else {"state": "none", "items": []}


def parse_body(body: object) -> dict[str, dict[str, Any]]:
    """The two review lines of one PR body. The first visible line of each label counts."""
    found: dict[str, str] = {}
    for line in _visible_lines(body if isinstance(body, str) else ""):
        match = _LINE.match(line)
        if match:
            found.setdefault(match.group(1).lower(), match.group(2).strip())
    return {"review_depth": _depth(found.get("review depth")),
            "could_not_verify": _unverified(found.get("could not verify"))}


# ─── One pull request, and the rollup ───────────────────────────────────────


def _when(raw: object) -> datetime.datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        stamp = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=datetime.timezone.utc)


def _login(item: dict[str, Any]) -> str:
    author = item.get("author")
    return str(author.get("login") or "") if isinstance(author, dict) else ""


def _reviewed_by_other(pr: dict[str, Any]) -> bool:
    """A submitted review by anyone but the PR's author; a pending review is not submitted."""
    author = _login(pr).lower()
    for review in pr.get("reviews") or []:
        if not isinstance(review, dict):
            continue
        reviewer = _login(review).lower()
        if reviewer and reviewer != author and review.get("state") != "PENDING":
            return True
    return False


def pull_row(pr: dict[str, Any], merged: datetime.datetime) -> dict[str, Any]:
    parsed = parse_body(pr.get("body"))
    return {"number": pr.get("number"), "title": str(pr.get("title") or ""), "url": str(pr.get("url") or ""),
            "merged_at": merged.isoformat(), **parsed, "reviewed_by_other": _reviewed_by_other(pr)}


def rollup(pulls: list[dict[str, Any]], top: int) -> dict[str, Any]:
    """Both lines across PULLS: the counts, every item, and the top recurring ones."""
    def states(line: str, state: str) -> list[int]:
        return [row["number"] for row in pulls if row[line]["state"] == state]

    by_key: dict[str, dict[str, Any]] = {}
    for row in sorted(pulls, key=lambda r: r["merged_at"]):  # oldest first: an item keeps its first wording
        for item in row["could_not_verify"].get("items", []):
            entry = by_key.setdefault(item["key"], {"item": item["label"], "prs": [], "reasons": [],
                                                    "last_merged": row["merged_at"]})
            entry["prs"].append(row["number"])
            entry["last_merged"] = max(entry["last_merged"], row["merged_at"])
            if item["reason"] and item["reason"] not in entry["reasons"]:
                entry["reasons"].append(item["reason"])
    items = sorted(by_key.values(), key=lambda e: e["item"].lower())
    items.sort(key=lambda e: e["last_merged"], reverse=True)  # a tie goes to the gap seen most recently
    items.sort(key=lambda e: len(e["prs"]), reverse=True)
    recurring = [e for e in items if len(e["prs"]) >= _RECURS]
    said_none, listed = states("could_not_verify", "none"), states("could_not_verify", "stated")

    depths = {row["number"]: row["review_depth"] for row in pulls}
    counts = {depth: sum(1 for d in depths.values() if d.get("depth") == depth) for depth in DEPTHS}
    claimed = [row["number"] for row in pulls if row["review_depth"].get("depth") in ("skimmed", "read-in-full")
               and not row["reviewed_by_other"]]
    stale = [row["number"] for row in pulls if row["review_depth"].get("depth") == "none" and row["reviewed_by_other"]]
    return {
        "could_not_verify": {
            "stated": len(said_none) + len(listed), "none": len(said_none), "listed": len(listed),
            "unfilled": len(states("could_not_verify", "unfilled")),
            "missing": len(states("could_not_verify", "missing")),
            "items": items, "recurring": recurring[:top], "recurring_dropped": max(0, len(recurring) - top),
            "singletons": sum(1 for e in items if len(e["prs"]) < _RECURS),
        },
        "review_depth": {
            "stated": sum(counts.values()), "counts": counts,
            "unfilled": len(states("review_depth", "unfilled")), "missing": len(states("review_depth", "missing")),
            "unparsed": [{"number": n, "raw": d.get("raw", "")} for n, d in depths.items()
                         if d["state"] == "unparsed"],
            "claimed_without_forge_review": claimed, "none_with_forge_review": stale,
        },
    }


# ─── Sources: gh and the fixture directory ──────────────────────────────────


class GhError(Exception):
    """A read that failed. The message is what the report prints."""


def _json(text: str, what: str) -> Any:
    try:
        return json.loads(text)
    except ValueError as exc:
        raise GhError(f"unparseable {what} output ({exc})") from exc


class GhSource:
    def now(self) -> datetime.datetime:
        return datetime.datetime.now(datetime.timezone.utc)

    def _run(self, args: list[str], timeout: float = 300) -> str:
        try:
            proc = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout,
                                  stdin=subprocess.DEVNULL)
        except FileNotFoundError as exc:
            raise GhError("gh is not installed or not on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise GhError(f"gh {args[0]} timed out after {timeout:.0f}s") from exc
        if proc.returncode != 0:
            detail = next((ln.strip() for ln in proc.stderr.splitlines() if ln.strip()), f"exit {proc.returncode}")
            if re.search(r"gh auth login|not logged|HTTP 401|authentication", proc.stderr, re.I):
                raise GhError(f"gh is not authenticated (run `gh auth login`): {detail[:200]}")
            raise GhError(detail[:300])
        return proc.stdout

    def repo(self) -> str:
        value = _json(self._run(["repo", "view", "--json", "nameWithOwner"]), "gh repo view")
        name = value.get("nameWithOwner") if isinstance(value, dict) else None
        if not isinstance(name, str) or not _REPO_NAME.match(name):
            raise GhError("gh repo view named no repository: run inside a GitHub checkout or pass --repo")
        return name

    def merged_prs(self, repo: str, start: datetime.datetime) -> list[Any]:
        out = self._run(["pr", "list", "--repo", repo, "--state", "merged", "--search", f"merged:>={start:%Y-%m-%d}",
                         "--limit", str(_GH_LIMIT), "--json", _PR_FIELDS])
        value = _json(out, "gh pr list")
        if not isinstance(value, list):
            raise GhError("gh pr list printed no list")
        return value


class FixtureSource(GhSource):
    """DIR/meta.json {now}, DIR/repo.json (`gh repo view --json nameWithOwner`), DIR/prs.json (`gh pr list --json`)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.meta = self._read("meta.json")

    def _read(self, name: str) -> Any:
        try:
            return _json((self.root / name).read_text(encoding="utf-8"), f"fixture {name}")
        except OSError as exc:
            raise GhError(f"no fixture {name} in {self.root}") from exc

    def now(self) -> datetime.datetime:
        return _when(self.meta.get("now")) or super().now()

    def _run(self, args: list[str], timeout: float = 300) -> str:
        name = {"repo": "repo.json", "pr": "prs.json"}[args[0]]
        return json.dumps(self._read(name))


# ─── Measurement and output ─────────────────────────────────────────────────


def measure(source: GhSource, repo: str, days: float, top: int) -> dict[str, Any]:
    now = source.now()
    start = now - datetime.timedelta(days=days)
    raw = source.merged_prs(repo, start)
    notes = [f"gh pr list returned its {_GH_LIMIT}-PR cap: older PRs in the window are missing"] \
        if len(raw) >= _GH_LIMIT else []
    pulls = []
    for pr in raw:
        merged = _when(pr.get("mergedAt")) if isinstance(pr, dict) else None
        # gh's search is by day, so the window's first day comes back whole: keep only what merged after START.
        if isinstance(pr, dict) and merged is not None and start <= merged <= now:
            pulls.append(pull_row(pr, merged))
    pulls.sort(key=lambda r: r["merged_at"])
    return {"measured": True, "repo": repo, "window": {"start": start.isoformat(), "end": now.isoformat(),
                                                       "days": days},
            "prs": len(pulls), "notes": notes, **rollup(pulls, top), "pulls": pulls}


def _refs(numbers: list[int]) -> str:
    return ", ".join(f"#{n}" for n in numbers)


def print_report(report: dict[str, Any]) -> None:
    window, total = report["window"], report["prs"]
    print(f"pr-verification-gaps: {report['repo']}, PRs merged {window['start'][:10]} → {window['end'][:10]} "
          f"({window['days']:g} days), any author: {total} PR(s).")
    for note in report["notes"]:
        print(f"  note: {note}")
    if not total:
        print("No PR merged in the window, so neither line can be rolled up.")
        return
    gaps = report["could_not_verify"]
    print()
    print(f"Could not verify — stated in {gaps['stated']} of {total} PRs ({gaps['none']} said none, "
          f"{gaps['unfilled']} left it unfilled, {gaps['missing']} carry no line).")
    if not gaps["stated"]:
        print("  NOT MEASURED: no PR in the window states the line. That is not 'nothing unverified'.")
    else:
        if gaps["stated"] < total:
            print(f"  Covers those {gaps['stated']} only: the other {total - gaps['stated']} are not counted as "
                  f"verified.")
        if gaps["recurring"]:
            print(f"  Recurring in {_RECURS}+ PRs, top {len(gaps['recurring'])} — candidate TODO entries, "
                  f"reported only (nothing is written):")
            for entry in gaps["recurring"]:
                why = f"; reasons: {'; '.join(entry['reasons'][:3])}" if entry["reasons"] else ""
                print(f"  - [ ] Verify {entry['item']} — unverified in {len(entry['prs'])} merged PRs "
                      f"({_refs(entry['prs'])}){why}")
            if gaps["recurring_dropped"]:
                print(f"  {gaps['recurring_dropped']} more recurring item(s) beyond the top {len(gaps['recurring'])}.")
        else:
            print(f"  No item recurs in {_RECURS} or more PRs.")
        print(f"  {gaps['singletons']} item(s) named by one PR only.")
    depth = report["review_depth"]
    counts = ", ".join(f"{name} {depth['counts'][name]}" for name in DEPTHS)
    unparsed = "; ".join(f"#{u['number']} {u['raw'][:40]!r}" for u in depth["unparsed"])
    print()
    print(f"Review depth, self-reported by each PR's author — stated in {depth['stated']} of {total}: {counts}; "
          f"{depth['unfilled']} unfilled, {len(depth['unparsed'])} unparsed{f' ({unparsed})' if unparsed else ''}, "
          f"{depth['missing']} carry no line.")
    if not depth["stated"]:
        print("  NOT MEASURED: no PR in the window states a depth, so none can be checked against the forge.")
        return
    claimed, stale = depth["claimed_without_forge_review"], depth["none_with_forge_review"]
    print(f"  Against the forge: {len(claimed)} claim a reading that no submitted review by anyone but the author "
          f"backs{f' ({_refs(claimed)})' if claimed else ''} — a reader outside GitHub leaves none, so ask, do not "
          f"overrule; {len(stale)} say none while carrying one{f' ({_refs(stale)})' if stale else ''}.")


def _unmeasured(reason: str, as_json: bool) -> int:
    if as_json:
        json.dump({"measured": False, "reason": reason}, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"pr-verification-gaps: NOT MEASURED — {reason}.")
        print("That is not zero gaps: no PR body was read, so nothing can be stated.")
    return 1


# ─── Self-test ──────────────────────────────────────────────────────────────
# Through main(), the entry point /retro runs: with --fixture on synthetic PRs
# holding gh's raw `gh pr list --json` output, and without it against a fake gh
# on PATH that records its arguments. Every guard has a control that fires and
# one that must not; the mutations that remove each guard are in
# orchestrator/tests/test_self_tests_can_fire.py.

_NOW = datetime.datetime(2026, 3, 15, 12, 0, tzinfo=datetime.timezone.utc)


def _pr(number: int, body: str, days_ago: float, author: str = "owner",
        reviews: tuple[tuple[str, str], ...] = (), now: datetime.datetime = _NOW) -> dict[str, Any]:
    merged = now - datetime.timedelta(days=days_ago)
    return {"number": number, "title": f"feat: change {number}", "url": f"https://github.com/acme/app/pull/{number}",
            "body": body, "author": {"login": author, "is_bot": False},
            "mergedAt": merged.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "reviews": [{"author": {"login": who}, "state": state, "body": ""} for who, state in reviews]}


# What each PR must read as: (review depth state or value, could-not-verify state, its item keys).
_EXPECTED = {
    1: ("none", "stated", ["live hook firing", "macos run"]),            # after a line quoting the format
    2: ("read-in-full", "stated", ["live hook firing", "hosted ci"]),     # Markdown emphasis, case, a trailing period
    3: ("unfilled", "unfilled", []),                                      # the template, left as it was
    4: ("missing", "missing", []),                                        # only inside an HTML comment
    5: ("missing", "missing", []),                                        # only inside fenced code
    6: ("read-in-full", "none", []),                                      # 'read in full', spaced
    7: ("unparsed", "none", []),                                          # 'thoroughly'; 'none (reason)'
    8: ("none", "stated", ["macos run", "hosted ci"]),                    # 'hosted CI' twice in one PR counts once
    9: ("skimmed", "stated", ["macos run", "real api call"]),
    10: ("skimmed", "stated", ["real api call"]),
    12: ("missing", "missing", []),                                       # after an unclosed comment
    13: ("missing", "stated", ["playwright e2e"]),                       # the first of two lines counts
    14: ("unfilled", "unfilled", []),                                     # the skills' own `a | b` format line
}
# Recurring, in order: macOS run (3 PRs); then three items in 2 PRs each, by latest merge: real API call (#10, 1 day
# ago), hosted CI (#8, 2 days ago), live hook firing (#2, 5 days ago), which --top 3 drops.
_EXPECTED_RECURRING = [("macOS run", [1, 8, 9]), ("real API call", [9, 10]), ("hosted CI", [2, 8])]


def _fixture_prs(now: datetime.datetime = _NOW) -> list[dict[str, Any]]:
    return [
        _pr(1, "Fixes the hook.\r\n- `Review depth: skimmed` means someone else skimmed it.\r\n\r\nReview depth: none"
               "\r\nCould not verify: live hook firing (no Claude Code session); macOS run (no Mac reachable)\r\n",
            6, now=now),
        _pr(2, "- **Review depth:** read-in-full (by @alice)\n- **Could not verify:** **Live hook firing**.; "
               "`hosted CI` (pushed after the local gate)\n", 5, reviews=(("alice", "APPROVED"),), now=now),
        _pr(3, "Review depth: <none | skimmed | read-in-full>\nCould not verify: <none | item (why); item (why)>\n",
            4, now=now),
        _pr(4, "Body.\n<!--\nReview depth: skimmed\nCould not verify: windows run\n-->\n", 4, now=now),
        _pr(5, "Example:\n```\nReview depth: read-in-full\nCould not verify: windows run\n```\n", 3, now=now),
        _pr(6, "Review depth: read in full\nCould not verify: none\n", 3,
            reviews=(("owner", "COMMENTED"), ("bob", "PENDING")), now=now),
        _pr(7, "Review depth: thoroughly\nCould not verify: none (every step ran locally)\n", 2, now=now),
        _pr(8, "Review depth: None\nCould not verify: macOS run; hosted CI; hosted CI (again)\n", 2,
            reviews=(("bob", "COMMENTED"),), now=now),
        _pr(9, "Review depth: skimmed\nCould not verify: macos run (Touch ID not pressed); real API call (no key)\n",
            1, now=now),
        _pr(10, "Review depth: skimmed by @carol\nCould not verify: real API call (no key)\n", 0.9, author="Owner",
            reviews=(("OWNER", "APPROVED"),), now=now),
        # Merged on the window's first day, but before its first hour: gh's day-granular search returns it.
        _pr(11, "Review depth: none\nCould not verify: macOS run\n", 7.25, now=now),
        _pr(12, "Merged.\n<!-- Review depth: read-in-full\nCould not verify: windows run\n", 0.5, now=now),
        _pr(13, "Could not verify: Playwright E2E (no browser)\nCould not verify: none\n", 0.4, now=now),
        _pr(14, "Review depth: none | skimmed | read-in-full\nCould not verify: none | <item>; <item>\n", 0.3,
            now=now),
    ]


_FAKE_GH = r'''import json, sys
from pathlib import Path
here = Path(__file__).parent
with open(here / "calls.jsonl", "a", encoding="utf-8") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
route = json.loads((here / "routes.json").read_text(encoding="utf-8")).get(" ".join(sys.argv[1:3]), {})
sys.stdout.write(route.get("stdout", ""))
sys.stderr.write(route.get("stderr", ""))
sys.exit(route.get("code", 0))
'''


def _write_fixture(root: Path, prs: list[dict[str, Any]]) -> Path:
    root.mkdir(parents=True)
    (root / "meta.json").write_text(json.dumps({"now": _NOW.isoformat()}), encoding="utf-8")
    (root / "repo.json").write_text(json.dumps({"nameWithOwner": "acme/app"}), encoding="utf-8")
    (root / "prs.json").write_text(json.dumps(prs), encoding="utf-8")
    return root


def _write_fake_gh(bindir: Path, routes: dict[str, Any]) -> Path:
    bindir.mkdir(parents=True)
    (bindir / "fake_gh.py").write_text(_FAKE_GH, encoding="utf-8")
    (bindir / "gh").write_text(f'#!/bin/sh\nexec "{sys.executable}" "{bindir / "fake_gh.py"}" "$@"\n',
                               encoding="utf-8")
    (bindir / "gh").chmod(0o755)
    (bindir / "routes.json").write_text(json.dumps(routes), encoding="utf-8")
    return bindir / "calls.jsonl"


def self_test(entry: Callable[[list[str]], int]) -> int:
    """Can every parsing rule, the ranking, the forge cross-check and each failure report still go red?"""
    failures: list[str] = []

    def expect(label: str, actual: object, wanted: object) -> None:
        if actual != wanted:
            failures.append(f"{label}: expected {wanted!r}, got {actual!r}")

    def run(args: list[str], path: str | None = None) -> tuple[int, str]:
        buffer, saved = io.StringIO(), os.environ.get("PATH", "")
        try:
            if path is not None:
                os.environ["PATH"] = path
            with contextlib.redirect_stdout(buffer):
                code = entry(args)
        except Exception as exc:  # a crash is a failed control, not a crashed self-test
            return -1, f"{buffer.getvalue()}\nCRASHED: {type(exc).__name__}: {exc}"
        finally:
            os.environ["PATH"] = saved
        return code, buffer.getvalue()

    def run_json(label: str, args: list[str], path: str | None = None) -> tuple[int, dict[str, Any]]:
        code, out = run([*args, "--json"], path)
        try:
            return code, json.loads(out)
        except ValueError:
            failures.append(f"{label}: --json printed no JSON: {out[-400:]}")
            return code, {}

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        main_fixture = str(_write_fixture(root / "main", _fixture_prs()))

        # 1. Every PR body reads as it must, and the window keeps #11 out.
        code, report = run_json("the main fixture", ["--fixture", main_fixture, "--repo", "acme/app"])
        expect("exit code of a measured run", code, 0)
        rows = {row["number"]: row for row in report.get("pulls", [])}
        expect("PRs inside the window (#11 merged hours before it opened)", sorted(rows), sorted(_EXPECTED))
        for number, (depth, state, keys) in _EXPECTED.items():
            row = rows.get(number, {})
            got = row.get("review_depth", {})
            expect(f"#{number} review depth", got.get("depth", got.get("state")), depth)
            unverified = row.get("could_not_verify", {})
            expect(f"#{number} could-not-verify state", unverified.get("state"), state)
            expect(f"#{number} items", [i["key"] for i in unverified.get("items", [])], keys)
        expect("#2's reviewer note", rows.get(2, {}).get("review_depth", {}).get("by"), "(by @alice)")
        expect("#9's macOS reason", [i["reason"] for i in rows.get(9, {}).get("could_not_verify", {}).get("items", [])],
               ["Touch ID not pressed", "no key"])

        # 2. The rollup: counts, ranking, the top-N cut, singletons.
        gaps = report.get("could_not_verify", {})
        expect("could-not-verify counts", {k: gaps.get(k) for k in ("stated", "none", "listed", "unfilled", "missing")},
               {"stated": 8, "none": 2, "listed": 6, "unfilled": 2, "missing": 3})
        expect("the top 3 recurring items, in order",
               [(e["item"], e["prs"]) for e in gaps.get("recurring", [])], _EXPECTED_RECURRING)
        expect("recurring items beyond the top 3", gaps.get("recurring_dropped"), 1)
        expect("items named by one PR only", gaps.get("singletons"), 1)
        expect("macOS run's reasons, first wording first",
               (gaps.get("recurring") or [{}])[0].get("reasons"), ["no Mac reachable", "Touch ID not pressed"])

        # 3. Review depth and the forge cross-check.
        depth = report.get("review_depth", {})
        expect("review depth counts", depth.get("counts"), {"none": 2, "skimmed": 2, "read-in-full": 2})
        expect("review depth unfilled / missing", (depth.get("unfilled"), depth.get("missing")), (2, 4))
        expect("unparsed depths", depth.get("unparsed"), [{"number": 7, "raw": "thoroughly"}])
        # #6: its author's own review and a PENDING one; #9: none; #10: 'OWNER' reviewing 'Owner'. #2 is backed.
        expect("claims no forge review backs", depth.get("claimed_without_forge_review"), [6, 9, 10])
        expect("'none' with a forge review", depth.get("none_with_forge_review"), [8])

        # 4. The text /retro reads.
        code, text = run(["--fixture", main_fixture, "--repo", "acme/app"])
        wanted = ["- [ ] Verify macOS run — unverified in 3 merged PRs (#1, #8, #9); reasons: no Mac reachable; "
                  "Touch ID not pressed",
                  "- [ ] Verify real API call — unverified in 2 merged PRs (#9, #10)",
                  "1 more recurring item(s) beyond the top 3", "Covers those 8 only: the other 5 are not counted",
                  "self-reported", "(#6, #9, #10)", "say none while carrying one (#8)", "1 unparsed (#7 'thoroughly')"]
        for line in wanted:
            if line not in text:
                failures.append(f"the report does not say {line!r}:\n{text[-1500:]}")
        code, text = run(["--fixture", main_fixture, "--repo", "acme/app", "--top", "5"])
        if "Verify live hook firing" not in text or "beyond the top" in text:
            failures.append(f"--top 5 must list all four recurring items and drop none:\n{text[-800:]}")

        # 5. No PR states the line: NOT MEASURED for that section, never "nothing recurs".
        silent = str(_write_fixture(root / "silent", [_pr(20, "No review lines here.", 1)]))
        code, text = run(["--fixture", silent, "--repo", "acme/app"])
        if "NOT MEASURED: no PR in the window states the line" not in text or "No item recurs" in text \
                or "NOT MEASURED: no PR in the window states a depth" not in text or "Against the forge" in text:
            failures.append(f"a window where no PR states either line must read NOT MEASURED twice:\n{text[-800:]}")
        empty = str(_write_fixture(root / "empty", []))
        code, text = run(["--fixture", empty, "--repo", "acme/app"])
        if code != 0 or "No PR merged in the window" not in text:
            failures.append(f"an empty window must say so and exit 0, got {code}:\n{text[-400:]}")

        # 6. Through a fake gh: the repository gh resolves, and the arguments sent.
        now = datetime.datetime.now(datetime.timezone.utc)
        prs = [_pr(30, "Review depth: none\nCould not verify: macOS run\n", 1, now=now),
               _pr(31, "Review depth: none\nCould not verify: macOS run\n", 2, now=now)]
        log = _write_fake_gh(root / "bin", {"repo view": {"stdout": json.dumps({"nameWithOwner": "acme/app"})},
                                            "pr list": {"stdout": json.dumps(prs)}})
        path = f"{root / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}"
        code, report = run_json("the fake-gh run", ["--since", "7"], path)
        expect("through gh: the repository gh resolved", report.get("repo"), "acme/app")
        expect("through gh: the recurring item", [(e["item"], e["prs"]) for e in
                                                  report.get("could_not_verify", {}).get("recurring", [])],
               [("macOS run", [31, 30])])
        calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
        listed = [c for c in calls if c[:2] == ["pr", "list"]]
        start = _when((report.get("window") or {}).get("start"))
        call = listed[0] if len(listed) == 1 else []

        def value(flag: str) -> str:
            return call[call.index(flag) + 1] if flag in call[:-1] else ""

        if not start or value("--repo") != "acme/app" or value("--state") != "merged" \
                or value("--search") != f"merged:>={start:%Y-%m-%d}" or value("--limit") != str(_GH_LIMIT) \
                or not {"body", "mergedAt", "reviews", "author"} <= set(value("--json").split(",")):
            failures.append(f"gh pr list must read --repo acme/app --state merged --search merged:>=<day> --limit "
                            f"{_GH_LIMIT} --json with body, mergedAt, reviews and author: {listed}")

        # 7. Nothing read is NOT MEASURED, with the reason, and exit 1 — never a report of zero gaps.
        _write_fake_gh(root / "noauth", {"repo view": {"stderr": "To get started with GitHub CLI, please run:  "
                                                                 "gh auth login\n", "code": 4}})
        code, report = run_json("an unauthenticated gh", [], f"{root / 'noauth'}{os.pathsep}{os.environ['PATH']}")
        expect("an unauthenticated gh: exit code", code, 1)
        expect("an unauthenticated gh: measured", report.get("measured"), False)
        if "not authenticated" not in str(report.get("reason")):
            failures.append(f"an unauthenticated gh must say so: {report}")
        (root / "nogh").mkdir()
        code, text = run(["--repo", "acme/app"], str(root / "nogh"))
        if code != 1 or "NOT MEASURED — gh is not installed" not in text:
            failures.append(f"a missing gh must read NOT MEASURED and exit 1, got {code}:\n{text[-400:]}")

    for failure in failures:
        print(f"FAIL: {failure}")
    print(f"pr-verification-gaps self-test: {'FAILED' if failures else 'PASSED'} ({len(failures)} failure(s))")
    return 1 if failures else 0


# ─── Entry point ────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Roll up the 'Could not verify:' and 'Review depth:' lines of a repository's merged PRs.",
        epilog="Report only: the recurring items are candidate TODO entries; nothing is written.")
    parser.add_argument("--since", type=float, default=7.0, metavar="DAYS", help="Merge window in days (default 7).")
    parser.add_argument("--repo", metavar="OWNER/NAME", help="Repository to read (default: the one gh resolves here).")
    parser.add_argument("--top", type=int, default=3, metavar="N", help="Recurring items to list (default 3).")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a report.")
    parser.add_argument("--fixture", metavar="DIR", help="Read gh's JSON from DIR instead of the network (tests).")
    parser.add_argument("--self-test", action="store_true",
                        help="Ask every parsing rule, the ranking and each failure report whether it can go red.")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test(main)
    if args.since <= 0:
        parser.error("--since must be a positive number of days")
    if args.top < 1:
        parser.error("--top must be at least 1")
    if args.repo and not _REPO_NAME.match(args.repo):
        parser.error(f"--repo {args.repo!r} is not OWNER/NAME")
    try:
        source = FixtureSource(Path(args.fixture)) if args.fixture else GhSource()
        repo = args.repo or source.repo()
        report = measure(source, repo, args.since, args.top)
    except GhError as exc:
        return _unmeasured(str(exc), args.json)
    if args.json:
        json.dump(report, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
