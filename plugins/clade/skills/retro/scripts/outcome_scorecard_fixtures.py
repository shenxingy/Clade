#!/usr/bin/env python3
"""outcome_scorecard_fixtures.py — the synthetic repositories outcome-scorecard.py's self-test reads.

Data only, imported by that self-test; it has no CLI and holds no guard of its
own. What the fixtures must produce, and every guard, stay in
outcome-scorecard.py, where test_self_tests_can_fire.py mutates them and the
mutated script's own self-test must go red. Split out on 2026-11-05, when the
script reached its 1500-line cap, as scorecard_fixtures.py was before it.

Every file holds what gh PRINTS for that read, raw: `gh pr list --json` arrays,
GraphQL search pages with files and reviews as connections, REST commits with
the date under commit.committer, so the script's own projections run on them.
The fake gh on PATH records the arguments the script sends it.

Stdlib only: the syntax-check CI job installs nothing.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import shlex
import sys
from pathlib import Path
from typing import Any

# ─── Builders: one PR, commit or search page, raw ───────────────────────────

T = datetime.datetime(2026, 2, 1, 12, tzinfo=datetime.timezone.utc)


def iso(days: float = 0.0, hours: float = 0.0, t0: datetime.datetime = T) -> str:
    return (t0 + datetime.timedelta(days=days, hours=hours)).isoformat().replace("+00:00", "Z")


def oid(seed: str) -> str:
    return hashlib.sha1(seed.encode()).hexdigest()


def pr(number: int, title: str, day: float, author: str = "owner", files: tuple[str, ...] = ("src/x.py",),
       reviews: tuple[tuple[str, str], ...] = (), open_hours: float = 1.0, base: str = "main",
       t0: datetime.datetime = T) -> dict[str, Any]:
    """A PR as `gh pr list --json` prints it: files and reviews already lists."""
    return {
        "number": number, "title": title, "author": {"login": author},
        "createdAt": iso(day, -open_hours, t0), "mergedAt": iso(day, t0=t0),
        "mergeCommit": {"oid": oid(f"pr{number}")}, "baseRefName": base,
        "additions": number * 10, "deletions": number,
        "files": [{"path": p, "additions": 1, "deletions": 0} for p in files],
        "reviews": [{"author": {"login": who}, "state": state} for who, state in reviews],
    }


def search_pages(prs: list[dict[str, Any]], per_page: int = 2) -> list[str]:
    """PRs as GraphQL search pages, files and reviews as connections. `gh api graphql --paginate` prints them all,
    one object after another; without --paginate it prints the first."""
    nodes = [{**row, "files": {"nodes": [{"path": f["path"]} for f in row["files"]]},
              "reviews": {"nodes": row["reviews"]}} for row in prs]
    pages = [nodes[i:i + per_page] for i in range(0, len(nodes), per_page)] or [[]]
    return [json.dumps({"data": {"search": {
        "pageInfo": {"hasNextPage": i < len(pages) - 1, "endCursor": f"c{i}"}, "nodes": page}}}) + "\n"
        for i, page in enumerate(pages)]


def commit(seed: str, message: str, day: float, authored: float | None = None,
           t0: datetime.datetime = T) -> dict[str, Any]:
    """A commit as the REST API returns it. AUTHORED, when given, is an author date apart from the committer's."""
    return {"sha": oid(seed), "url": f"https://api.github.invalid/commits/{oid(seed)}",
            "commit": {"message": message,
                       "author": {"name": "a", "date": iso(day if authored is None else authored, t0=t0)},
                       "committer": {"name": "c", "date": iso(day, t0=t0)}}}


# ─── The --fixture directories ──────────────────────────────────────────────


def write_fixture(root: Path, files_cap: int, gh_limit: int) -> None:
    """The --fixture directories. FILES_CAP and GH_LIMIT are gh's caps, as the script states them."""
    def put(rel: str, value: Any) -> None:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    put("meta.json", {"now": iso(28), "login": "owner", "host": "fixture-host"})
    put("search.json", [{"repository": {"nameWithOwner": "acme/app"}, "number": 1},
                        {"repository": {"nameWithOwner": "acme/app"}, "number": 10},
                        {"repository": {"nameWithOwner": "acme/broken"}, "number": 2}])
    book = ("TODO.md", "web/package-lock.json", "docs/facts.json", "README.zh-CN.md", "CHANGELOG.md",
            "docs/changelog/0.17.md")
    put("repos/acme/app/prs.json", [
        pr(1, "feat: one", 0, files=("src/one.py",), open_hours=1),
        pr(5, "feat: before the window", -3),
        pr(10, "feat: alpha", 0, files=("src/alpha.py",), open_hours=2),
        pr(11, "feat: beta", 0, files=("src/beta.py",), open_hours=3),
        pr(12, "feat: gamma", 0, files=("src/gamma.py",), open_hours=4),
        pr(13, "feat: delta", 0, files=("src/delta.py", "TODO.md"), reviews=(("alice", "APPROVED"),), open_hours=5),
        pr(14, "feat: epsilon", 0, files=("src/eps.py", *book), open_hours=6),
        pr(15, "feat: zeta", 0, files=("src/zeta.py",), open_hours=7),
        pr(16, "feat: eta", 0, files=("src/eta.py",), open_hours=8),
        pr(17, "feat: theta", 27, files=("src/theta.py",), open_hours=9),
        pr(18, "feat: iota", 0, author="Owner", files=("src/iota.py",), reviews=(("OWNER", "COMMENTED"),),
           open_hours=10),
        pr(19, "feat: kappa", 4, files=("src/kappa.py",), reviews=(("bob", "PENDING"),), open_hours=11),
        pr(27, "feat: lambda", 0, files=("src/lambda.py",), open_hours=12),
        pr(30, "feat: mu", 27, files=("src/mu.py",), open_hours=13),
        pr(32, "feat: nu", 0, files=("src/nu.py",), open_hours=14),
        pr(50, "feat: xi", 0, files=("src/xi.py",), open_hours=15),
        pr(51, "feat: follow-up to #18", 1, files=("src/follow.py",), open_hours=16),
        pr(52, "feat: pi", 0, files=("src/pi.py",), open_hours=17),
        pr(53, 'Revert "feat: pi"', 1, files=("src/pi.py",), open_hours=18),
        pr(54, "feat: omicron", 0, files=("src/omicron.py",), open_hours=19),
        pr(55, "Roll back omicron, it reverts #54", 1, files=("src/omicron.py",), open_hours=20),
        pr(56, "feat: revert-proof loader", 0, files=("src/loader.py",), open_hours=21),
        pr(57, "docs: guide", 0, files=("docs/guide.md",), open_hours=22),
        pr(58, "feat: rho", 0, files=("src/rho.py",), open_hours=23),
        pr(59, "feat: sigma", 0, files=("src/sigma.py",), open_hours=24),
        pr(60, "feat: tau", 0, files=("src/tau.py",), open_hours=25),
        pr(62, "fix: phi", 0, files=("src/phi.py",), open_hours=26, base="dev"),
        pr(63, "fix: phi", 0.5, files=("src/phi.py",), open_hours=27),
        # Reverts of PRs that were never read: merged before the window, so not in this list.
        pr(64, 'Revert "feat: chi"', 0, files=("src/chi.py",), open_hours=28),
        pr(65, "Roll back the loader, it reverts #4", 0, files=("src/loader.py",), open_hours=29),
        # Three PRs that each also append to one shared file, and one later fix to it (#77) credited for all
        # three. Their open times are the long tail that keeps the open→merge median off the mean.
        pr(66, "feat: register a", 0, files=("src/reg_a.py", "configs/registry.json"), open_hours=48),
        pr(67, "feat: register b", 0, files=("src/reg_b.py", "configs/registry.json"), open_hours=96),
        pr(68, "feat: register c", 0, files=("src/reg_c.py", "configs/registry.json"), open_hours=200),
        # Everyone else's: the later PRs that revert or fix, and the ones that must not count.
        # Merged 9 days after #12, past --settle 7: a revert has no time bound.
        pr(21, "Revert gamma rollout, see #12", 9, author="alice", files=("src/gamma.py",)),
        pr(22, "fix(delta): off by one", 2, author="alice", files=("src/delta.py",)),
        pr(23, "fix: bookkeeping", 1, author="bob", files=book),
        pr(24, "feat: zeta follow-up", 1, author="bob", files=("src/zeta.py",)),
        pr(25, "fix: eta", 8, author="bob", files=("src/eta.py",)),
        pr(26, "fix: alpha edge case", 1, author="bob", files=("src/alpha.py",)),
        pr(28, "Hotfix lambda crash", 1, author="bob", files=("src/lambda.py",)),
        pr(31, "fix: zeta prep", -1, author="bob", files=("src/zeta.py",)),
        pr(33, 'Revert "feat: kappa"', 3, author="alice", files=("src/kappa.py",)),
        pr(70, 'Revert "feat: xi"', 1, author="alice", files=("src/xi.py",)),
        pr(71, "fix: guide typo", 1, author="bob", files=("docs/guide.md",)),
        pr(72, "bugfix: rho null", 1, author="bob", files=("src/rho.py",)),
        pr(73, "fix!: sigma api", 1, author="bob", files=("src/sigma.py",)),
        pr(74, "fix: tau", 7, author="bob", files=("src/tau.py",)),
        pr(75, "chore: generated sweep", 1, author="bob", files=tuple(f"gen/f{i:03}.py" for i in range(files_cap))),
        pr(77, "fix: registry entry", 1, author="bob", files=("configs/registry.json",)),
    ])
    put("repos/acme/app/repo.json", {"default_branch": "main", "full_name": "acme/app"})
    put("repos/acme/app/commits.json", [
        # Committed 10 days after #10, past --settle 7: a revert has no time bound.
        commit("c10", f"Revert alpha\n\nThis reverts commit {oid('pr10')[:7]}.", 10),
        # Rebased, so its author date (day -1) falls before #11 merged: only the committer date, when it landed,
        # puts it after #11.
        commit("c11", 'Revert "feat: beta" (#20)\n\nThe body names no sha.', 1, authored=-1),
        commit("c32", 'Revert "feat: nu (#32)"', 1),
        commit("c30", f'Revert mu\n\nThis reverts commit {oid("pr30")}.', 27.5),
        commit("n1a", f"chore: tidy\n\nThis reverts commit {oid('pr1')[:6]}.", 1),
        commit("n1b", 'Revert "feat: one more"', 1),
        commit("n19", 'Revert "feat: kappa"', 3),
        commit("pr11", "feat: beta (#11)", 0),
    ])
    put("repos/acme/empty/prs.json", [pr(3, "feat: not ours", 1, author="bob")])
    # gh pr list times out on a big monorepo (a gateway error): read through the search instead, two pages.
    (root / "repos/acme/heavy").mkdir(parents=True, exist_ok=True)
    (root / "repos/acme/heavy/prs.search.json").write_text("".join(search_pages([
        pr(40, "feat: heavy", 0, files=("src/heavy.py",), reviews=(("alice", "APPROVED"),)),
        pr(43, "feat: heavy part two", 0, files=("src/heavy.py",)),
        # The same number as acme/app's fix #77, credited here for two PRs: pooled by number alone, the total
        # would read one fix credited for five.
        pr(77, "fix: heavy edge case", 1, author="bob", files=("src/heavy.py",)),
        pr(61, "feat: upsilon", 21, files=("src/upsilon.py",)),
    ])), encoding="utf-8")
    put("repos/acme/heavy/repo.json", {"default_branch": "main"})
    put("repos/acme/heavy/commits.json", [])
    (root / "repos/acme/heavy/prs.error.txt").write_text(
        "HTTP 502: 502 Bad Gateway (https://api.github.com/graphql)\n", encoding="utf-8")
    # A 404 is not a timeout: no fallback, even though the search would answer.
    for name in ("prs.search.json", "repo.json", "commits.json"):
        (root / "repos/acme/broken").mkdir(parents=True, exist_ok=True)
        (root / "repos/acme/broken" / name).write_text((root / "repos/acme/heavy" / name).read_text())
    (root / "repos/acme/broken/prs.error.txt").write_text("HTTP 404: Not Found (repos/acme/broken)\n",
                                                          encoding="utf-8")
    put("auth/meta.json", {"now": iso(28), "whoami_error": "gh is not authenticated (run `gh auth login`)"})
    # gh's 1000-result caps, on discovery and on one repository's PR list.
    put("capped/meta.json", {"now": iso(28), "login": "owner"})
    put("capped/search.json", [{"repository": {"nameWithOwner": "acme/bulk"}, "number": i} for i in range(gh_limit)])
    put("capped/repos/acme/bulk/prs.json", [pr(1000 + i, f"feat: bulk {i}", 1, author="bob", files=("src/b.py",))
                                            for i in range(gh_limit)])

    # Transcripts: one call written as two records (output streamed 5 then 50),
    # one call before the window, one after now - settle, one after now, one under a second
    # profile, a profile that is a symlink to ~/.claude, as on the author's host,
    # and two records that are not API calls: a <synthetic> one and a user one.
    def record(msg_id: str, day: float, usage: dict[str, int], kind: str = "assistant",
               model: str = "claude-opus-5-5") -> str:
        return json.dumps({"type": kind, "timestamp": iso(day),
                           "message": {"id": msg_id, "model": model, "usage": usage,
                                       "content": [{"type": "tool_result", "content": "assistant"}]}})

    lead = root / "home/.claude/projects/proj/s1.jsonl"
    lead.parent.mkdir(parents=True)
    lead.write_text("\n".join([
        record("m1", 5, {"input_tokens": 100, "cache_creation_input_tokens": 10, "cache_read_input_tokens": 1000,
                         "output_tokens": 5}),
        record("m1", 5, {"input_tokens": 100, "cache_creation_input_tokens": 10, "cache_read_input_tokens": 1000,
                         "output_tokens": 50}),
        record("m2", -40, {"input_tokens": 7777, "output_tokens": 7777}),
        record("m4", 25, {"input_tokens": 1000}),
        record("m5", 29, {"input_tokens": 88888}),
        record("syn", 5, {"input_tokens": 50000}, model="<synthetic>"),
        record("u1", 5, {"input_tokens": 90000}, kind="user"),
    ]) + "\n", encoding="utf-8")
    other = root / "home/.claude-profiles/p1/projects/proj/s2.jsonl"
    other.parent.mkdir(parents=True)
    other.write_text(record("m3", 6, {"input_tokens": 1, "cache_creation_input_tokens": 2,
                                      "cache_read_input_tokens": 3, "output_tokens": 4}) + "\n", encoding="utf-8")
    (root / "home/.claude-profiles/main").symlink_to(root / "home/.claude")


# ─── The fake gh ────────────────────────────────────────────────────────────


# A fake gh for GhSource: it appends its argv to calls.jsonl and answers from routes.json, keyed by the read
# (the repository, never the query), so a wrong qualifier still gets an answer and only the recorded argv shows it.
# A route whose stdout is a list is pages, and like gh it prints past the first only under --paginate.
FAKE_GH = r'''import json, os, re, sys
here = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
with open(os.path.join(here, "calls.jsonl"), "a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\n")
if args[:2] == ["pr", "list"] and "--repo" in args:
    key = "pr list " + args[args.index("--repo") + 1]
elif args[:2] == ["api", "graphql"]:
    q = next((a[2:] for a in args if a.startswith("q=")), "")
    key = "graphql " + (re.findall(r"repo:(\S+)", q) or ["?"])[0]
elif args[:1] == ["api"] and len(args) > 1:
    key = "api " + args[1].split("?", 1)[0]
else:
    key = " ".join(args[:2])
with open(os.path.join(here, "routes.json"), encoding="utf-8") as fh:
    route = json.load(fh).get(key)
if route is None:
    sys.stderr.write("fake gh: no route for %s\n" % key)
    sys.exit(2)
out = route.get("stdout", "")
if isinstance(out, list):  # pages: gh prints them all only under --paginate
    out = "".join(out) if "--paginate" in args else out[0]
sys.stdout.write(out)
sys.stderr.write(route.get("stderr", ""))
sys.exit(route.get("code", 0))
'''


def write_fake_gh(bindir: Path, now: datetime.datetime) -> Path:
    """A fake gh in BINDIR answering one discovery run: acme/app reverted by sha on its default branch 'trunk',
    acme/heavy read through the GraphQL fallback after a 504 and fixed forward. Returns its call log."""
    bindir.mkdir(parents=True)
    (bindir / "fake_gh.py").write_text(FAKE_GH, encoding="utf-8")
    (bindir / "gh").write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} '
                               f'{shlex.quote(str(bindir / "fake_gh.py"))} "$@"\n', encoding="utf-8")
    (bindir / "gh").chmod(0o755)
    heavy = [pr(40, "feat: heavy", -3, files=("src/heavy.py",), reviews=(("alice", "APPROVED"),), t0=now),
             pr(42, "fix: heavy", -2, author="bob", files=("src/heavy.py",), t0=now)]
    routes = {
        "api user": {"stdout": json.dumps({"login": "owner", "id": 1})},
        "search prs": {"stdout": json.dumps([
            {"number": 1, "repository": {"name": "app", "nameWithOwner": "acme/app"}},
            {"number": 40, "repository": {"name": "heavy", "nameWithOwner": "acme/heavy"}}])},
        "pr list acme/app": {"stdout": json.dumps([pr(1, "feat: one", -2, files=("src/one.py",), base="trunk",
                                                      t0=now)])},
        "api repos/acme/app": {"stdout": json.dumps({"full_name": "acme/app", "default_branch": "trunk"})},
        "api repos/acme/app/commits": {"stdout": json.dumps([
            commit("g1", f"Revert one\n\nThis reverts commit {oid('pr1')}.", -1, t0=now)])},
        "pr list acme/heavy": {"stderr": "HTTP 504: Gateway Timeout (https://api.github.com/graphql)\n", "code": 1},
        "graphql acme/heavy": {"stdout": search_pages(heavy, per_page=1)},
        "api repos/acme/heavy": {"stdout": json.dumps({"full_name": "acme/heavy", "default_branch": "main"})},
        "api repos/acme/heavy/commits": {"stdout": "[]"},
    }
    (bindir / "routes.json").write_text(json.dumps(routes), encoding="utf-8")
    return bindir / "calls.jsonl"
