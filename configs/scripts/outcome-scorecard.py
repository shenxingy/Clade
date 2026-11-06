#!/usr/bin/env python3
"""outcome-scorecard.py — did the merged work stick, or did it only merge?

Why this exists
---------------
Every scorecard Clade had measured INPUTS. ``workflow-scorecard.py`` reads how a
fan-out used its slots, ``session-scorecard.sh`` reads the corrections log, and
``/retro`` reads commit velocity and hotspots. None of them asks whether the
work that merged was any good, so "the agents ran a lot" could pass for "the
work was good". Outside evidence says the two do not move together. These are
cited from the brief that commissioned this script and were not re-fetched
here: Faros AI's 2025 study of 10k+ developers saw +98% PRs merged and +91%
review time with no company-level gain, and the AIDev dataset of 456k
agent-authored PRs found them accepted less often than human PRs. On the
author's host, in the 7 days to 2026-11-05, there were 2,025 agent threads
(96.9% started by another agent) and 424 merged PRs, and nothing said how many
of those 424 stuck.

What it measures
----------------
Every PR the author merged in the window (``--since``) gets one status:

``REVERTED``       a later default-branch commit says "This reverts commit <sha>"
                   of its merge commit (the full sha or a prefix of 7+
                   characters); or a later commit or merged PR is titled exactly
                   ``Revert "<its title>"``, with or without a trailing ``(#N)``;
                   or a later merged PR whose title says revert references
                   ``#<its number>``. A revert counts whenever it landed, up to
                   now: ``--settle`` bounds only fix-forwards and the
                   settled/kept split, never a revert.
``FIXED-FORWARD``  not reverted, and a later merged PR by ANYONE into the same
                   base branch, within ``--settle`` days, has a fix-type title
                   (``fix:``, ``fix(scope):``, ``fix!:``, ``hotfix``, ``bugfix``) and
                   shares a changed path with it. Bookkeeping paths do not
                   count: TODO.md, PROGRESS.md, CHANGELOG*.md, a changelog/
                   directory, README*.md, docs/facts.json and lockfiles. The
                   same base, because a repository that lands each change on
                   dev and again on main would otherwise read the second
                   landing as a fix of the first. This is a SIGNAL, and its
                   precision has not been measured: a fix to the same file may
                   repair something else, and its first real runs are in
                   docs/configuration.md. Each block prints how many
                   fix-forwards shared a path that is not Markdown, the paths
                   they most often shared, and the fan-in: every fix credited
                   as the fix-forward of 3 or more PRs, which usually means a
                   shared file such as an append-only log, not that many
                   repairs. So a reader can judge it.
``SETTLING``       merged less than ``--settle`` days ago and neither of the
                   above. It has not had time to be reverted, so it is never
                   counted as kept.
``KEPT``           settled, and neither reverted nor fixed-forward.
``REVERT``         the author's PR that itself reverts another PR, by the same
                   PR-title rules, whether or not that PR was read: a revert
                   of a PR merged before the window, or of a ``#N`` that is no
                   PR read, says "target outside the window". Undoing a change
                   is not new work that stuck, so it enters neither side of the
                   kept rate.

The kept rate is kept / settled, where settled means merged at least
``--settle`` days ago, whatever happened to the PR afterwards. A young PR enters
neither side of the rate, even when it has already been reverted: counting young
failures but not young successes would bias the rate down. With the defaults
(``--since 7 --settle 7``) no PR in the window is old enough, so no rate is
printed, though a young PR is still listed as reverted or fixed-forward when it
already is. ``--since 14`` scores the week before.

Review load is open-to-merge time (median, p90), the share merged with no review
from anyone but the PR's author (a bot reviewer counts as someone, a pending
review does not), and median lines changed. ``--tokens`` adds Claude Code
transcript usage in the window, divided by merged PRs. Per settled and per kept
PR divide only the tokens spent up to now - ``--settle``, when those PRs merged:
the last ``--settle`` days' tokens produced only PRs too young to be settled.
Those tokens are host-wide and not attributed to any PR, and Codex and Kimi
usage is not counted, so with ``--repo`` every per-PR figure overstates that
repository set's cost, and the report says so.

What it cannot see
------------------
- Bad work that nobody touched again reads as KEPT. A revert or a fix is
  evidence of a problem, and the absence of both is not evidence of quality.
- A revert or fix that landed outside the default branch, or in another
  repository. A PR into another base branch (dev, a release branch) is scored,
  and the report says how many there were; a change landed on two branches is
  counted once per branch.
- Paths beyond the first 100 per PR, which is all ``gh pr list`` returns. A PR
  at that cap is noted.
- Whether the ``#N`` in a revert title is a PR. With no PR read under that
  number, a title that says revert and names an issue reads as a revert PR.

Data: one ``gh pr list`` per repository (every author, so later PRs by anyone
count) and one paginated ``gh api .../commits`` on its default branch, after one
``gh api repos/R`` for that branch's name. When ``gh pr list`` hits a gateway
error (HTTP 502/503/504), which large monorepos do because GraphQL computes 100
PRs' files per page, the same fields are read through one paginated GraphQL
search at 10 PRs per page, and the report says so. With no ``--repo``, the
repositories are those where ``--author`` merged a PR in the window, found with
``gh search prs``. ``--fixture DIR`` reads the same raw output from files. No
gh call carries ``--jq``: every projection of gh's output is Python, shared by
both sources, so the self-test runs each one on raw pages, and it runs the real
gh calls against a fake gh on PATH that records their arguments.

Stdlib only, on purpose: the syntax-check CI job installs no dependencies.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import io
import json
import math
import os
import re
import socket
import statistics
import subprocess
import sys
import tempfile
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

# ─── Classification rules ───────────────────────────────────────────────────

KEPT, REVERTED, FIXED, SETTLING = "kept", "reverted", "fixed-forward", "settling"
# The author's own PR that reverts another PR, read or not. Undoing a bad change
# is not new work that stuck, so it enters neither side of the kept rate.
REVERT_PR = "revert"
STATUSES = (KEPT, REVERTED, FIXED, SETTLING, REVERT_PR)

# git writes the full 40-character sha into a revert; people shorten it, and
# below 7 characters a prefix stops naming one commit.
_MIN_SHA_PREFIX = 7
_REVERTS_COMMIT = re.compile(r"This reverts commit ([0-9a-fA-F]+)")
# GitHub's revert button titles the PR 'Revert "<title>"', and a squash merge
# appends " (#N)" to that subject. A `git revert` of a squash commit puts the
# original's own " (#N)" inside the quotes instead.
_REVERT_TITLE = re.compile(r'^Revert "(.*)"(?: \(#\d+\))?$')
_REVERT_WORD = re.compile(r"\brevert", re.I)
_FIX_TITLE = re.compile(r"^fix(\(.*\))?!?:|^(hotfix|bugfix)\b", re.I)

# Paths that most PRs touch for bookkeeping. A later fix sharing only these says
# nothing about whether it repaired this PR.
_BOOKKEEPING_NAMES = frozenset({
    "TODO.md", "PROGRESS.md",
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "uv.lock", "poetry.lock", "Cargo.lock", "go.sum",
})
_BOOKKEEPING_PATHS = frozenset({"docs/facts.json"})
_BOOKKEEPING_DOC = re.compile(r"^(?:README|CHANGELOG)[^/]*\.md$")
# A per-version changelog (docs/changelog/0.17.md) is CHANGELOG.md split by release.
_BOOKKEEPING_DIR = re.compile(r"(?:^|/)changelogs?/", re.I)

# `gh pr list` and `gh search prs` stop at 1000 results; GraphQL returns at most
# 100 files per PR. Hitting either cap is said, never absorbed.
_GH_LIMIT = 1000
_FILES_CAP = 100
_REPO_NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
# One fix credited as the fix-forward of this many PRs or more is reported: it
# usually touched a file they all share, such as an append-only log, rather
# than repairing each of them.
_FAN_IN = 3


def _when(raw: object) -> datetime.datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        stamp = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=datetime.timezone.utc)


def _after(when: datetime.datetime | None, merged_at: datetime.datetime | None) -> bool:
    return when is not None and merged_at is not None and when > merged_at


def _login(item: dict[str, Any]) -> str:
    author = item.get("author")
    return str(author.get("login") or "") if isinstance(author, dict) else ""


def _title(item: dict[str, Any]) -> str:
    return str(item.get("title") or "").strip()


def _merge_oid(pr: dict[str, Any]) -> str:
    commit = pr.get("mergeCommit")
    return str(commit.get("oid") or "").lower() if isinstance(commit, dict) else ""


def _base(pr: dict[str, Any]) -> str:
    return str(pr.get("baseRefName") or "")


def _paths(pr: dict[str, Any]) -> set[str]:
    return {f["path"] for f in pr.get("files") or [] if isinstance(f, dict) and isinstance(f.get("path"), str)}


def _is_bookkeeping(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    if path in _BOOKKEEPING_PATHS or name in _BOOKKEEPING_NAMES:
        return True
    return bool(_BOOKKEEPING_DOC.match(name) or _BOOKKEEPING_DIR.search(path))


def _q(text: str, limit: int = 70) -> str:
    """A title for the report: double-quoted, cut at LIMIT with an ellipsis."""
    return f'"{text if len(text) <= limit else text[:limit - 1] + "…"}"'


def _reverts_title(subject: str, title: str, number: int) -> bool:
    match = _REVERT_TITLE.match(subject.strip())
    if not match or not title:
        return False
    return match.group(1) in (title, f"{title} (#{number})")


def _pr_title_reverts(later_title: str, title: str, number: int) -> str | None:
    """How a PR titled LATER_TITLE says it reverts PR #NUMBER: "" by exact title, " references #N", or None."""
    if _reverts_title(later_title, title, number):
        return ""
    if _REVERT_WORD.search(later_title) and re.search(rf"#{number}(?!\d)", later_title):
        return f" references #{number}"
    return None


# ─── Classification ─────────────────────────────────────────────────────────


def revert_evidence(pr: dict[str, Any], all_prs: list[dict[str, Any]], commits: list[dict[str, Any]]) -> str | None:
    """What reverted this PR, at any time up to now (no --settle bound), or None."""
    number = int(pr.get("number") or 0)
    title = _title(pr)
    merged_at = _when(pr.get("mergedAt"))
    oid = _merge_oid(pr)
    for commit in commits:
        sha = str(commit.get("sha") or "").lower()
        if oid and sha == oid:
            continue
        message = str(commit.get("message") or "")
        # A sha reference proves the order by itself: nothing can name a commit
        # that does not exist yet, so no date check here.
        for ref in (r.lower() for r in _REVERTS_COMMIT.findall(message)):
            if oid and len(ref) >= _MIN_SHA_PREFIX and oid.startswith(ref):
                return f"commit {sha[:7]} reverts {ref[:12]}"
        subject = message.split("\n", 1)[0]
        # A title is not unique: a reland carries the title of the change an
        # earlier revert removed, so only a LATER revert counts.
        if _reverts_title(subject, title, number) and _after(_when(commit.get("date")), merged_at):
            return f"commit {sha[:7]} {_q(subject)}"
    for other in all_prs:
        if other.get("number") == number:
            continue
        if not _after(_when(other.get("mergedAt")), merged_at):
            continue
        other_title = _title(other)
        how = _pr_title_reverts(other_title, title, number)
        if how is not None:
            return f"#{other.get('number')} {_q(other_title)}{how}"
    return None


def reverted_target(pr: dict[str, Any], all_prs: list[dict[str, Any]]) -> str | None:
    """Which PR this PR reverts, by the PR-title rules above, or None.

    A revert title whose target is no PR read is still a revert: the PRs read are those merged in the window, so
    a revert of an older PR would otherwise be scored as new work, and could count as kept.
    """
    title = _title(pr)
    number = int(pr.get("number") or 0)
    for other in all_prs:
        if other.get("number") == pr.get("number"):
            continue
        if _pr_title_reverts(title, _title(other), int(other.get("number") or 0)) is not None:
            return f"reverts #{other.get('number')} {_q(_title(other))}"
    return _unread_target(title, number)


def _unread_target(title: str, number: int) -> str | None:
    """The PR-title rules with no target to match: an exact 'Revert "<title>"', or a revert word beside a #N."""
    match = _REVERT_TITLE.match(title)
    if match:
        return f"reverts {_q(match.group(1))}, target outside the window"
    ref = next((ref for ref in re.findall(r"#(\d+)", title) if int(ref) != number), None)
    if _REVERT_WORD.search(title) and ref:
        return f"reverts #{ref}, target outside the window"
    return None


def fix_forward_evidence(pr: dict[str, Any], all_prs: list[dict[str, Any]],
                         settle: datetime.timedelta) -> tuple[str, list[str], int] | None:
    """The later fix that touched this PR's files within the settle time, the paths it shared and its number, or None.

    A SIGNAL, not a verdict: the fix may repair something else in the same file. Only a fix into the same base
    branch counts: in a repository that lands each change on dev and again on main, the second landing shares
    every file with the first and is not a repair of it.
    """
    merged_at = _when(pr.get("mergedAt"))
    if merged_at is None:
        return None
    mine = _paths(pr)
    for later in all_prs:
        if later.get("number") == pr.get("number"):
            continue
        if _base(later) != _base(pr):
            continue
        when = _when(later.get("mergedAt"))
        if when is None or not merged_at < when <= merged_at + settle:
            continue
        later_title = _title(later)
        if not _FIX_TITLE.match(later_title):
            continue
        shared = sorted(p for p in mine & _paths(later) if not _is_bookkeeping(p))
        if shared:
            more = f" +{len(shared) - 2} more" if len(shared) > 2 else ""
            evidence = f"#{later.get('number')} {_q(later_title)} shares {', '.join(shared[:2])}{more}"
            return evidence, shared, int(later.get("number") or 0)
    return None


def classify(pr: dict[str, Any], all_prs: list[dict[str, Any]], commits: list[dict[str, Any]],
             now: datetime.datetime, settle: datetime.timedelta) -> tuple[str, str, list[str], int | None]:
    """(status, evidence, paths a fix-forward shared, the fix's number). A revert PR, then reverted, fixed-forward,
    settling. A revert is searched up to now, whatever --settle says: --settle bounds only the fix-forward search
    and how old a PR must be to count as settled."""
    undoes = reverted_target(pr, all_prs)
    if undoes:
        return REVERT_PR, undoes, [], None
    evidence = revert_evidence(pr, all_prs, commits)
    if evidence:
        return REVERTED, evidence, [], None
    fixed = fix_forward_evidence(pr, all_prs, settle)
    if fixed:
        return FIXED, fixed[0], fixed[1], fixed[2]
    merged_at = _when(pr.get("mergedAt"))
    if merged_at is None or now - merged_at < settle:
        return SETTLING, "younger than the settle time", [], None
    return KEPT, "", [], None


# ─── Review load ────────────────────────────────────────────────────────────


def _reviewed_by_other(pr: dict[str, Any]) -> bool:
    author = _login(pr).lower()
    for review in pr.get("reviews") or []:
        if not isinstance(review, dict):
            continue
        reviewer = _login(review).lower()
        if reviewer and reviewer != author and review.get("state") != "PENDING":
            return True
    return False


def _rate(part: int, whole: int) -> float | None:
    if not whole:
        return None  # no denominator, no rate
    return part / whole


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _p90(values: list[float]) -> float | None:
    """Nearest-rank 90th percentile: a value that occurred, never an interpolation."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.9 * len(ordered)) - 1)]


def review_load(pulls: list[dict[str, Any]]) -> dict[str, Any]:
    hours = [row["open_to_merge_h"] for row in pulls if row["open_to_merge_h"] is not None]
    lines = [float(row["lines_changed"]) for row in pulls]
    unreviewed = sum(1 for row in pulls if not row["reviewed_by_other"])
    return {
        "prs": len(pulls),
        "open_to_merge_h_median": _median(hours),
        "open_to_merge_h_p90": _p90(hours),
        "unreviewed": unreviewed,
        "unreviewed_share": _rate(unreviewed, len(pulls)),
        "lines_changed_median": _median(lines),
    }


def summarise(pulls: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts, the kept rate over settled PRs, and review load, for one repository or the total."""
    counts = {status: sum(1 for row in pulls if row["status"] == status) for status in STATUSES}
    settled = sum(1 for row in pulls if row["settled"])
    young = sum(1 for row in pulls if row["young"])
    # A fix-forward that shared only Markdown is the weakest form of the signal: on
    # a repository whose PRs all edit the same context docs it is most of them.
    non_md = sum(1 for row in pulls if row["status"] == FIXED
                 and any(not path.lower().endswith(".md") for path in row["shared"]))
    # What the fix-forwards had in common, so a reader can judge the signal: a
    # shared checklist or manifest is a weaker sign than a shared source file.
    shared: dict[str, int] = {}
    for row in pulls:
        for path in row["shared"]:
            shared[path] = shared.get(path, 0) + 1
    # One fix credited for many PRs usually touched a file they all share. Keyed by repository too: the total pools
    # every repository's rows, and #77 in one is not #77 in another.
    credited: dict[tuple[str, int], int] = {}
    for row in pulls:
        if row["fixed_by"] is not None:
            key = (row["repo"], row["fixed_by"])
            credited[key] = credited.get(key, 0) + 1
    fan_in = [{"repo": repo, "number": number, "prs": count}
              for (repo, number), count in sorted(credited.items(), key=lambda item: (-item[1], item[0]))
              if count >= _FAN_IN]
    return {
        "prs": len(pulls),
        "counts": counts,
        "settled": settled,
        "young": young,
        "kept_rate": _rate(counts[KEPT], settled),
        "fixed_forward_non_markdown": non_md,
        "review": review_load(pulls),
        "fix_forward_top_shared": sorted(shared.items(), key=lambda item: (-item[1], item[0]))[:3],
        "fix_forward_fan_in": fan_in,
    }


# ─── Source interface and the GraphQL fallback ──────────────────────────────


class GhError(Exception):
    """A read that failed. The message is what the report prints, by name."""


def _json_values(text: str, what: str) -> list[Any]:
    """Every JSON value in TEXT, arrays flattened. `gh api --paginate` writes one value per page."""
    decoder = json.JSONDecoder()
    values: list[Any] = []
    index = 0
    while True:
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            return values
        try:
            value, index = decoder.raw_decode(text, index)
        except ValueError as exc:
            raise GhError(f"unparseable {what} output ({exc})") from exc
        if isinstance(value, list):
            values.extend(value)
        else:
            values.append(value)


class Source:
    """Where PRs and commits come from: gh, or a fixture directory written the same way."""

    def now(self) -> datetime.datetime:
        return datetime.datetime.now(datetime.timezone.utc)

    def host(self) -> str:
        return socket.gethostname()

    def home(self) -> Path:
        return Path.home()

    def whoami(self) -> str:
        raise NotImplementedError

    def discover(self, author: str, start: datetime.datetime) -> list[dict[str, Any]]:
        raise NotImplementedError

    def merged_prs(self, repo: str, start: datetime.datetime) -> tuple[list[dict[str, Any]], list[str]]:
        """Every PR merged into REPO since START, any author, and what was noted reading them.

        `gh pr list` asks GraphQL for up to 100 PRs per page with their files, and on a large monorepo
        computing the files outlasts GitHub's time budget: measured 2026-11-05, one private monorepo
        returned HTTP 502 for 50 PRs as for 1000, and for either half of a 14-day window. On a gateway
        error the same fields are read through a search at 10 PRs per page (that repository: 306 PRs, 134 s).
        Any other error is the repository's failure, reported by name.
        """
        try:
            return self._pr_list(repo, start), []
        except GhError as exc:
            if not _GATEWAY_ERROR.search(str(exc)):
                raise
            first = str(exc)
        try:
            prs = self._pr_search(repo, start)
        except GhError as exc:
            raise GhError(f"{first}; the paginated GraphQL search failed too: {exc}") from exc
        return prs, [f"gh pr list failed ({first[:60]}); read through a GraphQL search, "
                     f"{_SEARCH_PAGE} PRs per page, instead"]

    def _pr_list(self, repo: str, start: datetime.datetime) -> list[dict[str, Any]]:
        raise NotImplementedError

    def _pr_search(self, repo: str, start: datetime.datetime) -> list[dict[str, Any]]:
        raise NotImplementedError

    def default_branch(self, repo: str) -> str:
        raise NotImplementedError

    def commits(self, repo: str, branch: str, start: datetime.datetime) -> list[dict[str, Any]]:
        raise NotImplementedError


_GATEWAY_ERROR = re.compile(r"HTTP 50[234]\b")
_SEARCH_PAGE = 10
# The same fields `gh pr list --json` returns; _search_rows gives them its shape, so one classifier reads both.
_SEARCH_QUERY = """query($q: String!, $endCursor: String) {
  search(query: $q, type: ISSUE, first: %d, after: $endCursor) {
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest {
      number title createdAt mergedAt additions deletions baseRefName
      author { login } mergeCommit { oid }
      files(first: 100) { nodes { path } }
      reviews(first: 100) { nodes { author { login } state } }
    } }
  }
}""" % _SEARCH_PAGE
_PR_FIELDS = "number,title,createdAt,mergedAt,mergeCommit,author,additions,deletions,files,reviews,baseRefName"


# ─── Projections: gh's raw output → the rows the classifier reads ───────────
# Done here, in Python, and never in a `--jq` argument: both sources read gh's
# raw output through these, so the self-test's fixtures hold that raw output
# and every projection below runs under it. A jq string was invisible to it.


def _nodes(connection: object) -> list[Any]:
    """A GraphQL connection's nodes: {"nodes": [...]} → [...]."""
    nodes = connection.get("nodes") if isinstance(connection, dict) else None
    return list(nodes) if isinstance(nodes, list) else []


def _search_rows(pages: list[Any]) -> list[dict[str, Any]]:
    """The PRs on GraphQL search pages (`gh api graphql --paginate` prints one object per page), shaped as
    `gh pr list --json` gives them: files and reviews as lists, not connections. Left as connections, _paths
    would find no path and every review would vanish, so the repository would show no fix-forward and no review."""
    rows = []
    for page in pages:
        data = page.get("data") if isinstance(page, dict) else None
        search = data.get("search") if isinstance(data, dict) else None
        for node in (search.get("nodes") or []) if isinstance(search, dict) else []:
            if isinstance(node, dict):
                rows.append({**node, "files": _nodes(node.get("files")), "reviews": _nodes(node.get("reviews"))})
    return rows


def _commit_rows(values: list[Any]) -> list[dict[str, Any]]:
    """REST commits as {sha, message, date}. The date is the COMMITTER's, when the commit landed on the branch,
    which is when a revert takes effect. The author date is when it was written: a rebase or a cherry-pick keeps
    it, so it can fall before the merge of the PR the revert undoes."""
    rows = []
    for value in values:
        commit = value.get("commit") if isinstance(value, dict) else None
        if not isinstance(commit, dict):
            continue
        committer = commit.get("committer")
        rows.append({"sha": str(value.get("sha") or ""), "message": str(commit.get("message") or ""),
                     "date": committer.get("date") if isinstance(committer, dict) else None})
    return rows


def _field(values: list[Any], key: str, what: str) -> str:
    """KEY of the one object a `gh api` read printed, or a GhError naming WHAT."""
    value = values[0].get(key) if values and isinstance(values[0], dict) else None
    if not isinstance(value, str) or not value:
        raise GhError(f"{what} returned no {key}")
    return value


# ─── Sources: gh and the fixture directory ──────────────────────────────────


class GhSource(Source):
    def _run(self, args: list[str], timeout: float = 600) -> str:
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

    def whoami(self) -> str:
        return _field(_json_values(self._run(["api", "user"]), "gh api user"), "login", "gh api user")

    def discover(self, author: str, start: datetime.datetime) -> list[dict[str, Any]]:
        out = self._run(["search", "prs", f"--author={author}", f"--merged-at=>={start:%Y-%m-%d}",
                         "--limit", str(_GH_LIMIT), "--json", "repository,number"])
        return [v for v in _json_values(out, "gh search prs") if isinstance(v, dict)]

    def _pr_list(self, repo: str, start: datetime.datetime) -> list[dict[str, Any]]:
        out = self._run(["pr", "list", "--repo", repo, "--state", "merged", "--search", f"merged:>={start:%Y-%m-%d}",
                         "--limit", str(_GH_LIMIT), "--json", _PR_FIELDS])
        return [v for v in _json_values(out, "gh pr list") if isinstance(v, dict)]

    def _pr_search(self, repo: str, start: datetime.datetime) -> list[dict[str, Any]]:
        query = f"repo:{repo} is:pr is:merged merged:>={start:%Y-%m-%d}"
        out = self._run(["api", "graphql", "--paginate", "-f", f"query={_SEARCH_QUERY}", "-f", f"q={query}"])
        return _search_rows(_json_values(out, "gh api graphql"))

    def default_branch(self, repo: str) -> str:
        out = self._run(["api", f"repos/{repo}"])
        return _field(_json_values(out, f"gh api repos/{repo}"), "default_branch", f"gh api repos/{repo}")

    def commits(self, repo: str, branch: str, start: datetime.datetime) -> list[dict[str, Any]]:
        since = start.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        query = urllib.parse.urlencode({"sha": branch, "since": since, "per_page": 100})
        out = self._run(["api", f"repos/{repo}/commits?{query}", "--paginate"])
        return _commit_rows(_json_values(out, "gh api commits"))


class FixtureSource(Source):
    """DIR/meta.json {now, login, host}, DIR/search.json, DIR/repos/<owner>/<name>/{prs,commits,repo}.json.

    Each file holds what gh prints for that read, raw: search.json and prs.json the `gh search prs` and
    `gh pr list --json` arrays, prs.search.json the GraphQL search pages, commits.json the REST commits and
    repo.json `gh api repos/R`. They go through the same projections as gh's output. prs.error.txt fails the
    `gh pr list` read with its text, the way a gh call fails.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        try:
            self.meta = json.loads((root / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise GhError(f"fixture {root}/meta.json unreadable ({exc})") from exc

    def _read(self, *parts: str) -> Any:
        path = self.root.joinpath(*parts)
        try:
            return _json_values(path.read_text(encoding="utf-8"), str(path.relative_to(self.root)))
        except OSError as exc:
            raise GhError(f"no fixture {path.relative_to(self.root)}") from exc

    def now(self) -> datetime.datetime:
        stamp = _when(self.meta.get("now"))
        return stamp if stamp else super().now()

    def host(self) -> str:
        return str(self.meta.get("host") or "fixture")

    def home(self) -> Path:
        return self.root / "home"

    def whoami(self) -> str:
        if self.meta.get("whoami_error"):
            raise GhError(str(self.meta["whoami_error"]))
        return str(self.meta.get("login") or "")

    def discover(self, author: str, start: datetime.datetime) -> list[dict[str, Any]]:
        return [v for v in self._read("search.json") if isinstance(v, dict)]

    def _pr_list(self, repo: str, start: datetime.datetime) -> list[dict[str, Any]]:
        owner, name = repo.split("/", 1)
        failure = self.root / "repos" / owner / name / "prs.error.txt"
        if failure.is_file():
            raise GhError(failure.read_text(encoding="utf-8").strip())
        return [v for v in self._read("repos", owner, name, "prs.json") if isinstance(v, dict)]

    def _pr_search(self, repo: str, start: datetime.datetime) -> list[dict[str, Any]]:
        owner, name = repo.split("/", 1)
        return _search_rows(self._read("repos", owner, name, "prs.search.json"))

    def default_branch(self, repo: str) -> str:
        owner, name = repo.split("/", 1)
        return _field(self._read("repos", owner, name, "repo.json"), "default_branch", f"fixture {repo}/repo.json")

    def commits(self, repo: str, branch: str, start: datetime.datetime) -> list[dict[str, Any]]:
        owner, name = repo.split("/", 1)
        return _commit_rows(self._read("repos", owner, name, "commits.json"))


# ─── Measurement ────────────────────────────────────────────────────────────


def discover_repos(source: Source, login: str, start: datetime.datetime) -> tuple[list[str], list[str]]:
    found = source.discover(login, start)
    notes = []
    if len(found) >= _GH_LIMIT:
        notes.append(f"repository discovery hit gh's {_GH_LIMIT}-result cap: some repositories may be missing")
    names = set()
    for item in found:
        repo = item.get("repository")
        if isinstance(repo, dict) and isinstance(repo.get("nameWithOwner"), str):
            names.add(repo["nameWithOwner"])
    return sorted(names), notes


def measure_repo(source: Source, repo: str, login: str, start: datetime.datetime, now: datetime.datetime,
                 settle: datetime.timedelta) -> dict[str, Any]:
    raw, notes = source.merged_prs(repo, start)
    if len(raw) >= _GH_LIMIT:
        notes.append(f"gh pr list returned its {_GH_LIMIT}-PR cap: earlier PRs in the window are missing")
    all_prs = sorted((p for p in raw if _when(p.get("mergedAt"))), key=lambda p: _when(p.get("mergedAt")) or now)
    mine = [p for p in all_prs
            if _login(p).lower() == login.lower() and (_when(p.get("mergedAt")) or now) >= start]
    commits: list[dict[str, Any]] = []
    branch = ""
    if mine:
        branch = source.default_branch(repo)
        commits = source.commits(repo, branch, start)
        off: dict[str, int] = {}
        for pr in mine:
            if _base(pr) != branch:
                off[_base(pr) or "?"] = off.get(_base(pr) or "?", 0) + 1
        if off:
            bases = ", ".join(f"{name} ×{n}" for name, n in sorted(off.items(), key=lambda item: (-item[1], item[0])))
            notes.append(f"{sum(off.values())} of the {len(mine)} PRs by {login} target a branch other than "
                         f"{branch} ({bases}): a change landed on two branches counts once per branch, reverts on "
                         f"those branches are seen only through PR titles, and a fix-forward is matched within "
                         f"one base branch")
    capped = [p for p in all_prs
              if len(p.get("files") or []) >= _FILES_CAP and (_when(p.get("mergedAt")) or now) >= start]
    if capped:
        notes.append(f"{len(capped)} PR(s) at gh's {_FILES_CAP}-file cap: paths beyond it are not compared")
    pulls = []
    for pr in mine:
        status, evidence, shared, fixed_by = classify(pr, all_prs, commits, now, settle)
        merged_at = _when(pr.get("mergedAt")) or now
        created = _when(pr.get("createdAt"))
        rated = status != REVERT_PR
        age = now - merged_at
        pulls.append({
            "repo": repo,
            "number": pr.get("number"),
            "title": _title(pr),
            "merged_at": pr.get("mergedAt"),
            "status": status,
            "evidence": evidence,
            "shared": shared,
            "fixed_by": fixed_by,
            "base": _base(pr),
            # Settled is age, not status: a young revert is not yet a settled failure.
            "settled": rated and age >= settle,
            "young": rated and age < settle,
            "open_to_merge_h": (merged_at - created).total_seconds() / 3600 if created else None,
            "lines_changed": int(pr.get("additions") or 0) + int(pr.get("deletions") or 0),
            "reviewed_by_other": _reviewed_by_other(pr),
        })
    summary = summarise(pulls)
    summary.update({"repo": repo, "default_branch": branch, "pulls": pulls, "notes": notes})
    return summary


def _measure_one(source: Source, repo: str, login: str, start: datetime.datetime, now: datetime.datetime,
                 settle: datetime.timedelta) -> tuple[str, dict[str, Any] | None, str]:
    try:
        return repo, measure_repo(source, repo, login, start, now, settle), ""
    except GhError as exc:
        return repo, None, str(exc)


# ─── Tokens ─────────────────────────────────────────────────────────────────


def token_roots(home: Path) -> list[Path]:
    roots = [home / ".claude" / "projects"]
    profiles = home / ".claude-profiles"
    if profiles.is_dir():
        roots.extend(sorted(p / "projects" for p in profiles.iterdir() if (p / "projects").is_dir()))
    return roots


def sum_tokens(roots: list[Path], start: datetime.datetime, end: datetime.datetime,
               split: datetime.datetime) -> dict[str, Any]:
    """Claude Code assistant usage with a timestamp in [start, end], one count per API call, and the part up to SPLIT.

    Claude Code writes one API response as one record per content block, each repeating the usage, so a call is
    keyed by message.id: input fields once, output as the max over its records. A profile that is a symlink to
    ~/.claude would read every file twice, so files are keyed by realpath. SPLIT is now - settle: a settled PR
    merged before it, so the tokens spent after it cannot have produced one.
    """
    files: dict[str, Path] = {}
    cutoff = start.timestamp()
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.jsonl"):
            real = os.path.realpath(path)
            try:
                if os.stat(real).st_mtime < cutoff:
                    continue  # appended to before the window opened, so nothing in it is inside it
            except OSError:
                continue
            files.setdefault(real, path)
    calls: dict[str, list[int]] = {}  # id -> [input, cache write, cache read, output]
    early: set[str] = set()  # ids of the calls made at or before SPLIT
    unreadable = 0
    for real in sorted(files):
        try:
            handle = open(real, encoding="utf-8", errors="replace")
        except OSError:
            unreadable += 1
            continue
        with handle:
            for number, line in enumerate(handle):
                if '"usage"' not in line or '"assistant"' not in line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                message = record.get("message") if isinstance(record, dict) else None
                if record.get("type") != "assistant" or not isinstance(message, dict):
                    continue
                usage = message.get("usage")
                if not isinstance(usage, dict) or message.get("model") == "<synthetic>":
                    continue
                when = _when(record.get("timestamp"))
                if when is None or when < start or when > end:
                    continue
                key = message.get("id") or f"{real}:{number}"
                call = calls.get(key)
                if call is None:
                    calls[key] = [int(usage.get("input_tokens") or 0), int(usage.get("cache_creation_input_tokens") or 0),
                                  int(usage.get("cache_read_input_tokens") or 0), int(usage.get("output_tokens") or 0)]
                    if when <= split:
                        early.add(key)
                else:
                    call[3] = max(call[3], int(usage.get("output_tokens") or 0))
    return {
        "files": len(files),
        "unreadable_files": unreadable,
        "calls": len(calls),
        "input": sum(c[0] for c in calls.values()),
        "cache_write": sum(c[1] for c in calls.values()),
        "cache_read": sum(c[2] for c in calls.values()),
        "output": sum(c[3] for c in calls.values()),
        "billed": sum(c[0] + c[1] + c[3] for c in calls.values()),
        "settled_window": {
            "start": start.isoformat(), "end": max(start, split).isoformat(), "calls": len(early),
            "billed": sum(c[0] + c[1] + c[3] for key, c in calls.items() if key in early),
        },
    }


# ─── Output ─────────────────────────────────────────────────────────────────


def _human(count: float | None) -> str:
    if count is None:
        return "n/a"
    for size, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(count) >= size:
            return f"{count / size:.1f}{suffix}"
    return f"{count:.0f}"


def _day(stamp: str) -> str:
    when = _when(stamp)
    return when.strftime("%Y-%m-%d %H:%MZ") if when else stamp


def _hours(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 60:.0f}m" if value < 1 else f"{value:.1f}h"


def _print_block(heading: str, summary: dict[str, Any], settle_days: float, pooled: bool = False) -> None:
    """One repository's block, or with POOLED the total's, whose fan-in names each fix's repository."""
    if not summary["prs"]:
        print(f"{heading}: no PRs, so no rates.")
        return
    counts, n = summary["counts"], summary["prs"]
    print(f"{heading}:")
    fixed = f"; {summary['fixed_forward_non_markdown']} share a non-Markdown path" if counts[FIXED] else ""
    undo = f" · {counts[REVERT_PR]} revert(s) of other PRs, not rated" if counts[REVERT_PR] else ""
    print(f"  {n} merged: {counts[KEPT]} kept · {counts[REVERTED]} reverted · "
          f"{counts[FIXED]} fixed-forward (signal{fixed}) · {counts[SETTLING]} settling{undo}")
    left = f"{summary['young']} younger than {settle_days:g}d"
    if counts[REVERT_PR]:
        left += f" and {counts[REVERT_PR]} revert(s) of other PRs"
    if summary["kept_rate"] is None:
        print(f"  kept rate: no settled PRs ({left}); a --since longer than --settle scores older ones")
    else:
        print(f"  kept rate: kept {counts[KEPT]} of {summary['settled']} settled PRs "
              f"({summary['kept_rate'] * 100:.0f}%); {left} left out")
    review = summary["review"]
    print(f"  review load over {review['prs']} PRs: open→merge median {_hours(review['open_to_merge_h_median'])}, "
          f"p90 {_hours(review['open_to_merge_h_p90'])} · {review['unreviewed']} of {review['prs']} "
          f"({review['unreviewed_share'] * 100:.0f}%) merged with no review from anyone but the author · "
          f"median {_human(review['lines_changed_median'])} lines changed")
    if summary["fix_forward_top_shared"]:
        print(f"  fixed-forward PRs most often shared: "
              + ", ".join(f"{path} ×{n}" for path, n in summary["fix_forward_top_shared"]))
    if summary["fix_forward_fan_in"]:
        print("  fan-in: " + ", ".join(f"{item['repo'] if pooled else ''}#{item['number']} fixed-forward "
                                       f"{item['prs']} PRs" for item in summary["fix_forward_fan_in"])
              + f" (a fix credited for {_FAN_IN}+ PRs usually touched a file they share, not that many repairs)")


def print_report(report: dict[str, Any]) -> None:
    window, author = report["window"], report["author"]
    span = f"merged {_day(window['start'])} → {_day(window['end'])} ({window['days']:g}d)"
    repos, failed = report["repos"], report["failed"]
    print(f"Outcome scorecard — PRs by {author} {span}; settle {report['settle_days']:g}d; "
          f"{len(repos)} repo(s) measured, {len(failed)} not measured; host {report['host']}.")
    print("FIXED-FORWARD is a signal whose precision is unmeasured; SETTLING PRs are younger than the "
          "settle time and never counted as kept.")
    for summary in repos:
        print()
        _print_block(f"{summary['repo']} — PRs by {author} {span}", summary, report["settle_days"])
        for row in summary["pulls"]:
            if row["status"] in (REVERTED, FIXED, REVERT_PR):
                print(f"    {row['status']:13} #{row['number']} {_q(row['title'], 60)} — {row['evidence']}")
        for note in summary["notes"]:
            print(f"    note: {note}")
    print()
    _print_block(f"Total over {len(repos)} measured repo(s) — PRs by {author} {span}", report["total"],
                 report["settle_days"], pooled=True)
    for item in failed:
        print(f"NOT MEASURED {item['repo']}: {item['reason']}")
    for note in report["notes"]:
        print(f"note: {note}")
    tokens = report.get("tokens")
    if tokens:
        total = report["total"]
        merged, settled, kept = total["prs"], total["settled"], total["counts"][KEPT]
        early = tokens["settled_window"]
        per_merged = "no PRs" if tokens["per_merged_pr"] is None else _human(tokens["per_merged_pr"])
        per_settled = "no settled PRs" if tokens["per_settled_pr"] is None else _human(tokens["per_settled_pr"])
        per_kept = "no kept PRs" if tokens["per_kept_pr"] is None else _human(tokens["per_kept_pr"])
        print()
        print(f"Tokens — Claude Code transcripts on host {report['host']}, {span.split(' ', 1)[1]}, "
              f"{tokens['files']:,} files, {tokens['calls']:,} API calls: {_human(tokens['billed'])} "
              f"input + cache write + output, {_human(tokens['cache_read'])} cache read; per merged PR "
              f"({merged} by {author}, {len(repos)} repo(s)): {per_merged}.")
        reach = (f"the {_human(early['billed'])} spent {_day(early['start'])} → {_day(early['end'])}, when those "
                 f"PRs merged" if early["start"] < early["end"] else
                 f"no tokens, as no part of the window is {report['settle_days']:g}d old")
        print(f"  Per settled and per kept PR divide {reach}, not the last {report['settle_days']:g}d's: "
              f"per settled PR ({settled}): {per_settled}; per kept PR ({kept}): {per_kept}.")
        print("  Host-wide, not attributed per PR: every session on this host is in the sum, whatever it worked "
              "on; Codex and Kimi are not counted.")
        if tokens["pr_scope"] == "named":
            print(f"  --repo narrows the PRs to {len(repos)} repository(ies) while the tokens are the whole host's, "
                  f"so every per-PR figure overstates what those PRs cost.")


def _unmeasured(reason: str, as_json: bool) -> int:
    if as_json:
        json.dump({"measured": False, "reason": reason}, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"outcome-scorecard: NOT MEASURED — {reason}.")
        print("That is not zero PRs: nothing was read, so no outcome can be stated.")
    return 1  # nothing was measured


# ─── Self-test ──────────────────────────────────────────────────────────────
# Through main(), the entry point the CLI uses: with --fixture on synthetic
# repositories holding gh's raw output (GraphQL pages with their files.nodes,
# REST commits with commit.committer.date), and without it against a fake gh on
# PATH that records every call, so the projections and the gh arguments are
# both under test. Every guard has a control that fires and one that must not;
# their mutations are in orchestrator/tests/test_self_tests_can_fire.py. The
# fixtures are built in outcome_scorecard_fixtures.py, beside this file; what
# they must produce is stated here.

# The owner's PRs in acme/app and the status each must get. now = T + 28d (T is
# the fixtures' clock), --since 30 opens the window at T - 2d, --settle 7.
_EXPECTED = {
    1: KEPT,        # negative control for the 6-char sha, an inexact revert title, and #1 inside "#12"
    10: REVERTED,   # by a 7-character sha prefix 10 days on, past --settle; also fixed earlier, and a revert wins
    11: REVERTED,   # by commit subject 'Revert "<title>" (#20)', committed after it though authored before it
    12: REVERTED,   # by a PR merged 9 days later, past --settle, whose title says revert and names #12
    13: FIXED,      # a later fix by someone else shares src/delta.py
    14: KEPT,       # a later fix shares only bookkeeping paths, a changelog/ directory among them
    15: KEPT,       # a later NON-fix shares src/zeta.py; a fix sharing it merged BEFORE #15
    16: KEPT,       # a fix sharing src/eta.py merged 8 days later, past --settle 7
    17: SETTLING,   # merged 1 day before now
    18: KEPT,       # authored by 'Owner', reviewed only by 'OWNER'; a later PR names #18 without saying revert
    19: KEPT,       # a 'Revert "feat: kappa"' commit and PR landed BEFORE it (a reland); a pending review
    27: FIXED,      # 'Hotfix ...', upper case
    30: REVERTED,   # by the full sha, 1 day old: reverted but not settled
    32: REVERTED,   # by 'Revert "<title> (#32)"', the git-revert-of-a-squash form
    50: REVERTED,   # by a later merged PR titled exactly 'Revert "feat: xi"', with no revert commit
    51: KEPT,       # names #18 without saying revert, so it neither reverts #18 nor is a revert
    52: REVERTED,   # by the owner's own revert PR, #53
    53: REVERT_PR,  # 'Revert "feat: pi"': the owner undoing #52 is not rated
    54: REVERTED,   # by #55, whose title says it reverts #54
    55: REVERT_PR,  # says revert and names #54, a PR in the set: not rated
    56: KEPT,       # 'revert-proof' says revert but names no #N and quotes no title: not a revert
    57: FIXED,      # a later fix shares only docs/guide.md: fixed-forward, but not through a non-Markdown path
    58: FIXED,      # 'bugfix: ...'
    59: FIXED,      # 'fix!: ...', the breaking-change marker
    60: FIXED,      # the fix merged exactly --settle days later still counts
    62: KEPT,       # into dev; its twin #63 into main shares the file and has a fix title, and is no fix of it
    63: KEPT,       # the main copy of #62
    64: REVERT_PR,  # 'Revert "feat: chi"', a PR that was never read: its target is outside the window
    65: REVERT_PR,  # says revert and names #4, no PR read: its target is outside the window
    66: FIXED,      # 66-68 each append to configs/registry.json, and one fix to it, #77, is credited for all
    67: FIXED,      # three: a fan-in of 3, reported
    68: FIXED,
}
# acme/heavy, read through the GraphQL fallback, so its files and reviews arrive as connections: #40 and #43 are
# fixed forward by #77 through a shared path, a fan-in of 2, under the threshold; #40 is reviewed by alice; #61
# merged exactly --settle days before now, so it is settled.
_EXPECTED_HEAVY = {40: FIXED, 43: FIXED, 61: KEPT}
# The fan-in each scope reports. acme/heavy's fix is #77 too, so a total keyed by number alone would read 5.
_FAN_IN_APP = [{"repo": "acme/app", "number": 77, "prs": 3}]


def _gh_call_failures(report: dict[str, Any], log: Path) -> list[str]:
    """What the fake-gh run got wrong: the outcome GhSource read, and the arguments it sent gh."""
    found: list[str] = []
    start = _when((report.get("window") or {}).get("start"))
    if start is None:
        return [f"the fake-gh run printed no window: {str(report)[:300]}"]
    day = f"{start:%Y-%m-%d}"
    try:
        calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError) as exc:
        return [f"the fake gh recorded no calls ({exc})"]
    repos = {r.get("repo"): r for r in report.get("repos", [])}
    statuses = {name: {row["number"]: row["status"] for row in r.get("pulls", [])} for name, r in repos.items()}
    if statuses != {"acme/app": {1: REVERTED}, "acme/heavy": {40: FIXED}} or report.get("failed"):
        found.append(f"through gh: expected acme/app #1 reverted and acme/heavy #40 fixed-forward, got {statuses}, "
                     f"failed {report.get('failed')}")
    if (repos.get("acme/heavy") or {}).get("review", {}).get("unreviewed") != 0:
        found.append("through gh: alice's review of acme/heavy #40 was not read off the GraphQL connection")

    def of(*head: str) -> list[list[str]]:
        return [c for c in calls if c[:len(head)] == list(head)]

    def value(call: list[str], flag: str) -> str:
        return call[call.index(flag) + 1] if flag in call[:-1] else ""

    search = of("search", "prs")
    if len(search) != 1 or "--author=owner" not in search[0] or f"--merged-at=>={day}" not in search[0]:
        found.append(f"gh search prs must ask for --author=owner --merged-at=>={day}: {search}")
    listed = of("pr", "list")
    if sorted(value(c, "--repo") for c in listed) != ["acme/app", "acme/heavy"] or any(
            value(c, "--search") != f"merged:>={day}" or value(c, "--state") != "merged" for c in listed):
        found.append(f"gh pr list must read --state merged --search merged:>={day} per repository: {listed}")
    graphql = of("api", "graphql")
    if len(graphql) != 1 or f"q=repo:acme/heavy is:pr is:merged merged:>={day}" not in graphql[0]:
        found.append(f"the GraphQL fallback must search merged:>={day} in acme/heavy: {graphql}")
    commits = [c for c in calls if c[:1] == ["api"] and len(c) > 1 and c[1].startswith("repos/acme/app/commits?")]
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(commits[0][1]).query) if len(commits) == 1 else {}
    since = _when((query.get("since") or [""])[0])
    if query.get("sha") != ["trunk"] or since != start.replace(microsecond=0) or "--paginate" not in commits[0]:
        found.append(f"acme/app's commits must be read from its default branch trunk since {start:%Y-%m-%dT%H:%M:%SZ}"
                     f", every page: {commits}")
    return found


def self_test(entry: Callable[[list[str]], int]) -> int:
    """Can every classification rule, the review count, the rates, the failure reports and the token sum go red?"""
    from outcome_scorecard_fixtures import oid, write_fake_gh, write_fixture  # beside this file
    failures: list[str] = []

    def expect(label: str, actual: object, wanted: object) -> None:
        close = isinstance(actual, float) and isinstance(wanted, (int, float)) and abs(actual - wanted) < 1e-9
        if not close and actual != wanted:
            failures.append(f"{label}: expected {wanted!r}, got {actual!r}")

    def run(args: list[str]) -> tuple[int, str]:
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                code = entry(args)
        except Exception as exc:  # a crash is a failed control, not a crashed self-test
            return -1, f"{buffer.getvalue()}\nCRASHED: {type(exc).__name__}: {exc}"
        return code, buffer.getvalue()

    def run_json(label: str, args: list[str]) -> tuple[int, dict[str, Any]]:
        code, out = run([*args, "--json"])
        try:
            value = json.loads(out)
        except ValueError:
            failures.append(f"{label}: --json printed no JSON: {out[-400:]}")
            return code, {}
        return code, value if isinstance(value, dict) else {}

    def lacks(label: str, text: str, needles: tuple[str, ...]) -> None:
        for needle in needles:
            if needle not in text:
                failures.append(f"{label} lacks {needle!r}")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_fixture(root, _FILES_CAP, _GH_LIMIT)
        fixture = ["--fixture", str(root)]
        named = [*fixture, "--since", "30", "--settle", "7",
                 "--repo", "acme/app", "--repo", "acme/empty", "--repo", "acme/heavy"]
        base = [*named, "--repo", "acme/broken", "--tokens"]

        code, report = run_json("the full run", base)
        expect("exit code with a failing repo", code, 1)
        repos = {r["repo"]: r for r in report.get("repos", [])}
        app = repos.get("acme/app", {})
        statuses = {row["number"]: row["status"] for row in app.get("pulls", [])}
        for number, wanted in _EXPECTED.items():
            expect(f"acme/app #{number}", statuses.get(number), wanted)
        expect("acme/app PRs counted (owner's in any case, inside the window)", sorted(statuses), sorted(_EXPECTED))
        expect("acme/app settled PRs (old enough, and not a revert)", app.get("settled"), 26)
        expect("acme/app kept rate over settled PRs only", app.get("kept_rate"), 10 / 26)
        expect("acme/app fix-forwards through a non-Markdown path", app.get("fixed_forward_non_markdown"), 8)
        evidence = {row["number"]: row["evidence"] for row in app.get("pulls", [])}
        expect("acme/app #64, a revert of a PR never read", evidence.get(64),
               'reverts "feat: chi", target outside the window')
        expect("acme/app #65, a revert naming a #N never read", evidence.get(65), "reverts #4, target outside the window")
        review = app.get("review", {})
        expect("acme/app merged with no review from anyone but the author", review.get("unreviewed"), 31)
        # The open hours are 1..29 with a tail of 48, 96 and 200: median 16.5, mean 24.3.
        expect("acme/app open→merge median (h), not the mean", review.get("open_to_merge_h_median"), 16.5)
        expect("acme/app open→merge p90 (h)", review.get("open_to_merge_h_p90"), 29.0)
        expect("acme/app median lines changed", review.get("lines_changed_median"), 566.5)
        expect("acme/app fix-forwards' most shared paths", app.get("fix_forward_top_shared"),
               [["configs/registry.json", 3], ["docs/guide.md", 1], ["src/delta.py", 1]])
        expect("acme/app fan-in (one fix credited for 3+ PRs)", app.get("fix_forward_fan_in"), _FAN_IN_APP)
        expect("total fan-in, keyed by repository", (report.get("total") or {}).get("fix_forward_fan_in"),
               _FAN_IN_APP)
        app_notes = " | ".join(app.get("notes", []))
        lacks("acme/app notes", app_notes, ("1 of the 32 PRs by owner target a branch other than main (dev ×1)",
                                            f"1 PR(s) at gh's {_FILES_CAP}-file cap"))
        heavy = repos.get("acme/heavy", {})
        expect("acme/heavy read through the GraphQL search after a 502",
               {row["number"]: row["status"] for row in heavy.get("pulls", [])}, _EXPECTED_HEAVY)
        expect("acme/heavy kept rate (a PR exactly --settle days old is settled)", heavy.get("kept_rate"), 1 / 3)
        expect("acme/heavy unreviewed (alice's review read off the GraphQL connection)",
               heavy.get("review", {}).get("unreviewed"), 2)
        expect("acme/heavy fix-forward's shared path (read off the GraphQL connection)",
               heavy.get("fix_forward_top_shared"), [["src/heavy.py", 2]])
        expect("acme/heavy fan-in (a fix credited twice is under the threshold)", heavy.get("fix_forward_fan_in"), [])
        if not any("GraphQL search" in note for note in heavy.get("notes", [])):
            failures.append(f"the GraphQL fallback must be noted: {heavy.get('notes')}")
        empty = repos.get("acme/empty", {})
        expect("acme/empty PRs", empty.get("prs"), 0)
        expect("acme/empty kept rate", empty.get("kept_rate", "missing"), None)
        expect("acme/empty unreviewed share", empty.get("review", {}).get("unreviewed_share", "missing"), None)
        expect("failed repos", [f.get("repo") for f in report.get("failed", [])], ["acme/broken"])
        tokens = report.get("tokens") or {}
        expect("token files (a symlinked profile read once)", tokens.get("files"), 2)
        expect("token API calls (one per message id; none after now; no <synthetic> or user record)",
               tokens.get("calls"), 3)
        expect("tokens input + cache write + output", tokens.get("billed"), 100 + 10 + 50 + 1 + 2 + 4 + 1000)
        expect("tokens cache read", tokens.get("cache_read"), 1000 + 3)
        expect("tokens spent up to now - settle", (tokens.get("settled_window") or {}).get("billed"), 167)
        expect("tokens per merged PR", tokens.get("per_merged_pr"), 1167 / 35)
        expect("tokens per settled PR (the tokens up to now - settle)", tokens.get("per_settled_pr"), 167 / 29)
        expect("tokens per kept PR (the tokens up to now - settle)", tokens.get("per_kept_pr"), 167 / 11)
        expect("token PR scope under --repo", tokens.get("pr_scope"), "named")

        code, text = run(base)
        expect("text exit code with a failing repo", code, 1)
        lacks("text report", text, (
            "NOT MEASURED acme/broken: HTTP 404", "signal whose precision is unmeasured",
            "32 merged: 10 kept · 8 reverted · 9 fixed-forward (signal; 8 share a non-Markdown path) · 1 settling"
            " · 4 revert(s) of other PRs, not rated",
            "kept 10 of 26 settled PRs (38%); 2 younger than 7d and 4 revert(s) of other PRs left out",
            "31 of 32 (97%) merged with no review from anyone but the author",
            "fixed-forward PRs most often shared: configs/registry.json ×3, docs/guide.md ×1, src/delta.py ×1",
            "\n  fan-in: #77 fixed-forward 3 PRs (a fix credited for 3+ PRs usually touched a file they share",
            "\n  fan-in: acme/app#77 fixed-forward 3 PRs (",
            "kept 11 of 29 settled PRs (38%)",
            f'{REVERTED:13} #10 "feat: alpha" — commit {oid("c10")[:7]} reverts {oid("pr10")[:7]}',
            f'{REVERT_PR:13} #53 "Revert "feat: pi"" — reverts #52 "feat: pi"',
            f'{REVERT_PR:13} #64 "Revert "feat: chi"" — reverts "feat: chi", target outside the window',
            "    note: gh pr list failed (HTTP 502", "    note: 1 of the 32 PRs by owner target",
            "not attributed per PR", "Codex and Kimi", "per settled PR (29): 6;", "per kept PR (11): 15.",
            "--repo narrows the PRs to 3 repository(ies)"))
        empty_lines = [ln for ln in text.splitlines() if ln.startswith("acme/empty")]
        if len(empty_lines) != 1 or "no PRs" not in empty_lines[0] or "%" in empty_lines[0]:
            failures.append(f"a repo with no PRs must print 'no PRs' and no rate: {empty_lines}")

        # --settle bounds fix-forwards and the settled/kept split; its help must not say it bounds reverts.
        shown = io.StringIO()
        with contextlib.redirect_stdout(shown), contextlib.suppress(SystemExit):
            entry(["--help"])
        lacks("--help", " ".join(shown.getvalue().split()), ("Reverts are counted whenever they landed, up to now.",))

        # Only measurable repositories: the one run that must exit 0.
        code, _ = run(named)
        expect("exit code when every repository was measured", code, 0)

        # The default shape, --since no longer than --settle: nothing has settled, so no rate.
        young = [*fixture, "--since", "6", "--settle", "7", "--repo", "acme/app", "--tokens"]
        code, report = run_json("the no-settled run", young)
        app = (report.get("repos") or [{}])[0]
        expect("no-settled run: acme/app statuses", {row["number"]: row["status"] for row in app.get("pulls", [])},
               {17: SETTLING, 30: REVERTED})
        expect("no-settled run: kept rate", app.get("kept_rate", "missing"), None)
        expect("no-settled run: tokens per kept PR", (report.get("tokens") or {}).get("per_kept_pr", "missing"), None)
        code, text = run(young)
        rate_lines = [ln for ln in text.splitlines() if "kept rate:" in ln]
        if len(rate_lines) != 2 or any("no settled PRs" not in ln or "%" in ln for ln in rate_lines):
            failures.append(f"with nothing settled, every kept-rate line must say so and print no rate: {rate_lines}")
        lacks("no-settled text", text, ("per kept PR (0): no kept PRs", "per settled PR (0): no settled PRs"))

        code, found = run_json("the discovery run", [*fixture, "--since", "30", "--tokens"])
        expect("discovered and measured", [r.get("repo") for r in found.get("repos", [])], ["acme/app"])
        expect("discovered and failed", [f.get("repo") for f in found.get("failed", [])], ["acme/broken"])
        expect("token PR scope with discovery", (found.get("tokens") or {}).get("pr_scope"), "discovered")

        code, capped = run_json("the capped run", ["--fixture", str(root / "capped"), "--since", "30"])
        lacks("capped run notes", " | ".join(capped.get("notes", [])),
              (f"repository discovery hit gh's {_GH_LIMIT}-result cap",))
        lacks("capped repo notes", " | ".join(note for r in capped.get("repos", []) for note in r.get("notes", [])),
              (f"gh pr list returned its {_GH_LIMIT}-PR cap",))

        code, text = run(["--fixture", str(root / "auth"), "--since", "30"])
        expect("exit code when @me cannot be resolved", code, 1)
        if "NOT MEASURED" not in text or "gh auth login" not in text:
            failures.append(f"an unauthenticated gh must be reported, not read as zero PRs: {text[-300:]}")
        code, unread = run_json("the unauthenticated --json run", ["--fixture", str(root / "auth"), "--since", "30"])
        expect("--json when nothing was measured", unread.get("measured"), False)

        # The real GhSource, never the network: PATH holds only a fake gh that
        # fails the way an unauthenticated one does, and then an empty directory.
        # Never an empty PATH: Python reads that as the current directory.
        fake, nobin = root / "bin", root / "nobin"
        fake.mkdir()
        nobin.mkdir()
        (fake / "gh").write_text("#!/bin/sh\necho 'To get started with GitHub CLI, please run:  gh auth login' >&2\n"
                                 "exit 4\n", encoding="utf-8")
        (fake / "gh").chmod(0o755)
        # And a fake gh that answers: GhSource's own calls and projections, end to end.
        calls = write_fake_gh(root / "ghbin", datetime.datetime.now(datetime.timezone.utc))
        saved = os.environ.get("PATH")
        try:
            os.environ["PATH"] = str(fake)
            auth_code, auth_text = run(["--since", "7"])
            os.environ["PATH"] = str(nobin)
            missing_code, missing_text = run(["--since", "7"])
            os.environ["PATH"] = str(root / "ghbin")
            gh_code, gh_report = run_json("the fake-gh run", ["--since", "7", "--settle", "7"])
            failures.extend(_gh_call_failures(gh_report, calls))
        finally:
            if saved is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = saved
    expect("exit code with an unauthenticated gh", auth_code, 1)
    if "gh is not authenticated" not in auth_text:
        failures.append(f"an unauthenticated gh must be reported as such: {auth_text[-300:]}")
    expect("exit code with no gh", missing_code, 1)
    expect("exit code of the fake-gh run", gh_code, 0)
    if "gh is not installed" not in missing_text:
        failures.append(f"a missing gh must be reported by name: {missing_text[-300:]}")

    if failures:
        for line in failures:
            print(f"SELF-TEST FAILED: {line}")
        return 1
    print("SELF-TEST PASSED: reverts (sha, title, PR reference, past --settle), revert PRs (target read or not), "
          "fix-forwards (same base only) and their fan-in, settling and its boundaries, review load, caps, empty and "
          "failing repos, the token sum and its window, and the gh calls and their raw-output projections all fire "
          "on their controls and stay quiet on the rest.")
    return 0


# ─── Entry point ────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Did the PRs an author merged stick? Reverts, fix-forwards and review load, per repository.",
        epilog="With no --repo, measures every repository where --author merged a PR in the window.",
    )
    parser.add_argument("--since", type=float, default=7.0, metavar="DAYS", help="Merge window in days (default 7).")
    parser.add_argument("--repo", action="append", metavar="OWNER/NAME",
                        help="Repository to measure (repeatable). Default: discovered with gh search prs.")
    parser.add_argument("--author", default="@me", help="Whose merged PRs to score (default @me).")
    parser.add_argument("--settle", type=float, default=7.0, metavar="DAYS",
                        help="Days after merge within which a later fix counts as a fix-forward, and under which a "
                             "PR is settling, never kept (default 7). Reverts are counted whenever they landed, "
                             "up to now.")
    parser.add_argument("--tokens", action="store_true",
                        help="Also sum Claude Code transcript usage in the window (host-wide, not per PR).")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a report.")
    parser.add_argument("--fixture", metavar="DIR", help="Read gh/git JSON from DIR instead of the network (tests).")
    parser.add_argument("--self-test", action="store_true",
                        help="Ask every classification rule, rate and failure report whether it can still go red.")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test(main)
    if args.since <= 0:
        parser.error("--since must be a positive number of days")
    if args.settle < 0:
        parser.error("--settle must not be negative")
    for repo in args.repo or []:
        if not _REPO_NAME.match(repo):
            parser.error(f"--repo {repo!r} is not OWNER/NAME")

    try:
        source: Source = FixtureSource(Path(args.fixture)) if args.fixture else GhSource()
    except GhError as exc:
        return _unmeasured(str(exc), args.json)
    now = source.now()
    start = now - datetime.timedelta(days=args.since)
    settle = datetime.timedelta(days=args.settle)

    login = args.author
    if login == "@me":
        try:
            login = source.whoami()
        except GhError as exc:
            return _unmeasured(f"cannot resolve --author @me: {exc}", args.json)
    notes: list[str] = []
    if args.repo:
        repos = sorted(dict.fromkeys(args.repo))
    else:
        try:
            repos, notes = discover_repos(source, login, start)
        except GhError as exc:
            return _unmeasured(f"cannot discover the repositories {login} merged into: {exc}", args.json)

    measured: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, min(4, len(repos)))) as pool:
        for repo, summary, reason in pool.map(lambda r: _measure_one(source, r, login, start, now, settle), repos):
            if summary is None:
                failed.append({"repo": repo, "reason": reason})
            else:
                measured.append(summary)

    report: dict[str, Any] = {
        "measured": True,
        "window": {"start": start.isoformat(), "end": now.isoformat(), "days": args.since},
        "settle_days": args.settle,
        "author": login,
        "host": source.host(),
        "repos": measured,
        "failed": failed,
        # Pooled per PR, not averaged per repository: a median of medians is not a median.
        "total": summarise([row for summary in measured for row in summary["pulls"]]),
        "tokens": None,
        "notes": notes,
    }
    if args.tokens:
        tokens = sum_tokens(token_roots(source.home()), start, now, now - settle)
        total = report["total"]
        tokens["per_merged_pr"] = None if not total["prs"] else tokens["billed"] / total["prs"]
        # A settled PR merged before now - settle, so it is divided into the tokens spent before then, never the
        # last --settle days': those produced only PRs that cannot be settled yet.
        early = tokens["settled_window"]["billed"]
        tokens["per_settled_pr"] = None if not total["settled"] else early / total["settled"]
        kept = total["counts"][KEPT]
        tokens["per_kept_pr"] = None if not kept else early / kept
        tokens["pr_scope"] = "named" if args.repo else "discovered"
        report["tokens"] = tokens

    if args.json:
        json.dump(report, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print_report(report)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
