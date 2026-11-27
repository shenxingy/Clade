#!/usr/bin/env python3
"""branch-sweep.py — delete the remote branches a merged PR already holds, and only those.

Agents open one branch per change. /merge-pr deletes each branch as it lands,
but a session that dies after the merge, a squash merge that `git branch -d`
refuses, or a repository with delete_branch_on_merge off leaves the branch
behind, and the list grows until nobody can tell live work from residue. On
2026-11-27 this repository held 19 such branches, every one of them the exact
head of a merged PR.

Each branch falls in exactly one class, checked in this order:

  default       the default branch                          never touched
  protected     a branch protection rule covers it           never touched
  unknown       more PRs name it than one query returns      kept
  open-pr       head of an open PR                           kept
  open-base     base of an open PR (a stack's parent)        kept
  archived      under archive/ or backup/                    kept: parked on purpose, counted only
  merged        its tip IS the head of a PR merged over a    deletable
                day ago (--min-age-hours)
  merged-recent the same, merged more recently               kept: its session may still be on it
  merged-moved  a merged PR exists, but the tip moved after  kept: those commits live only here
  closed        head of a closed, unmerged PR                kept: a person decides
  no-pr         no PR ever had this head                     kept: a person decides

Only `merged` is ever deleted, because only there nothing is lost: the PR keeps
the commits and its "Restore branch" button puts the ref back. A branch merged
within the last day waits, because the session that merged it may still be
working there; a sweep is for residue, not for another agent's live branch. The default is a
report. --apply writes a log (branch, sha, PR, restore command) first, then
deletes each branch with a lease on the sha it was classified at, so a branch
someone pushed to in between is refused, not lost. --enable-auto-delete sets
delete_branch_on_merge, which stops the list growing back; it changes a
repository setting, so --apply never implies it.

    branch-sweep.py                          # report on the current checkout's repository
    branch-sweep.py --repo owner/name --json
    branch-sweep.py --apply                  # from a checkout of that repository
    branch-sweep.py --enable-auto-delete
    branch-sweep.py --self-test

Exit: 0 a report, or every deletion done; 1 an API or usage error, nothing
deleted; 3 a deletion was refused.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

DELETABLE = "merged"
# Report order. `merged` first: it is what --apply acts on.
CLASSES = ("merged", "merged-recent", "merged-moved", "closed", "no-pr", "unknown",
           "open-pr", "open-base", "archived", "protected", "default")
ARCHIVE_PREFIXES = ("archive/", "backup/")
DECIDE = {"merged-moved", "closed", "no-pr", "unknown"}
PR_PAGE = 20          # associatedPullRequests per branch; more reads as `unknown`
PUSH_CHUNK = 50       # refs per `git push`
LIST_CAP = 40         # names printed per class; --json lists every one

REFS_QUERY = """query($owner:String!,$name:String!,$after:String){repository(owner:$owner,name:$name){
 defaultBranchRef{name} deleteBranchOnMerge
 refs(refPrefix:"refs/heads/",first:100,after:$after){pageInfo{hasNextPage endCursor}
  nodes{name branchProtectionRule{id} target{oid ... on Commit{committedDate}}
   associatedPullRequests(first:%d){totalCount nodes{number state headRefOid mergedAt}}}}}}""" % PR_PAGE
OPEN_QUERY = """query($owner:String!,$name:String!,$after:String){repository(owner:$owner,name:$name){
 pullRequests(states:OPEN,first:100,after:$after){pageInfo{hasNextPage endCursor} nodes{baseRefName}}}}"""
GITHUB_URL = re.compile(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?/?$", re.I)


class SweepError(Exception):
    pass


@dataclass
class Branch:
    name: str
    sha: str
    protected: bool = False
    committed: str = ""
    prs: list[dict] = field(default_factory=list)
    prs_complete: bool = True
    cls: str = ""
    pr: int | None = None


# ─── Classification ─────────────────────────────────────────────

def _when(stamp: str | None) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None


def classify(b: Branch, default: str, open_bases: set[str],
             cutoff: dt.datetime | None = None) -> tuple[str, int | None]:
    """cutoff: a PR merged after it is `merged-recent`; an unreadable mergedAt counts as recent."""
    if b.name == default:
        return "default", None
    if b.protected:
        return "protected", None
    if not b.prs_complete:
        return "unknown", None
    open_prs = [p for p in b.prs if p.get("state") == "OPEN"]
    if open_prs:
        return "open-pr", open_prs[0].get("number")
    if b.name in open_bases:
        return "open-base", None
    if b.name.startswith(ARCHIVE_PREFIXES):
        return "archived", None
    merged = [p for p in b.prs if p.get("state") == "MERGED"]
    for p in merged:
        if p.get("headRefOid") == b.sha:
            when = _when(p.get("mergedAt"))
            if cutoff is not None and (when is None or when > cutoff):
                return "merged-recent", p.get("number")
            return "merged", p.get("number")
    if merged:
        return "merged-moved", merged[0].get("number")
    closed = [p for p in b.prs if p.get("state") == "CLOSED"]
    if closed:
        return "closed", closed[0].get("number")
    return "no-pr", None


# ─── GitHub reads ───────────────────────────────────────────────

def gh(*args: str, cwd: Path | None = None) -> str:
    try:
        proc = subprocess.run(["gh", *args], cwd=cwd, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SweepError(f"gh {args[0]}: {exc}") from exc
    if proc.returncode != 0:
        raise SweepError(f"gh {' '.join(args[:2])} failed: {proc.stderr.strip()[:400]}")
    return proc.stdout


def graphql_pages(query: str, owner: str, name: str):
    after = None
    while True:
        args = ["api", "graphql", "-f", f"query={query}", "-F", f"owner={owner}", "-F", f"name={name}"]
        if after:
            args += ["-f", f"after={after}"]
        try:
            repo = json.loads(gh(*args))["data"]["repository"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise SweepError(f"unexpected GraphQL answer for {owner}/{name}: {exc}") from exc
        if repo is None:
            raise SweepError(f"no repository {owner}/{name}")
        yield repo
        conn = repo.get("refs") or repo.get("pullRequests") or {}
        info = conn.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            return
        after = info.get("endCursor")


def read_repo(slug: str, cutoff: dt.datetime | None = None) -> tuple[str, bool, list[Branch]]:
    owner, name = slug.split("/", 1)
    default, auto_delete, branches = "", False, []
    for repo in graphql_pages(REFS_QUERY, owner, name):
        default = (repo.get("defaultBranchRef") or {}).get("name", "")
        auto_delete = bool(repo.get("deleteBranchOnMerge"))
        for node in repo["refs"]["nodes"]:
            target = node.get("target") or {}
            assoc = node.get("associatedPullRequests") or {}
            prs = assoc.get("nodes") or []
            branches.append(Branch(
                name=node["name"], sha=target.get("oid", ""),
                protected=node.get("branchProtectionRule") is not None,
                committed=target.get("committedDate") or "",
                prs=prs, prs_complete=assoc.get("totalCount", 0) <= len(prs)))
    open_bases = {n["baseRefName"] for repo in graphql_pages(OPEN_QUERY, owner, name)
                  for n in repo["pullRequests"]["nodes"]}
    for b in branches:
        b.cls, b.pr = classify(b, default, open_bases, cutoff)
    return default, auto_delete, branches


# ─── Deletion ───────────────────────────────────────────────────

def remote_slug(checkout: Path, remote: str) -> str:
    proc = subprocess.run(["git", "remote", "get-url", remote], cwd=checkout,
                          capture_output=True, text=True, stdin=subprocess.DEVNULL)
    m = GITHUB_URL.search(proc.stdout.strip()) if proc.returncode == 0 else None
    return f"{m.group(1)}/{m.group(2)}" if m else ""


def delete_with_lease(checkout: Path, remote: str, doomed: list[Branch]) -> dict[str, str]:
    """Delete each branch only if the remote still holds the sha it was classified at."""
    results: dict[str, str] = {}
    for i in range(0, len(doomed), PUSH_CHUNK):
        chunk = doomed[i:i + PUSH_CHUNK]
        cmd = ["git", "push", "--porcelain"]
        cmd += [f"--force-with-lease=refs/heads/{b.name}:{b.sha}" for b in chunk]
        cmd += [remote] + [f":refs/heads/{b.name}" for b in chunk]
        proc = subprocess.run(cmd, cwd=checkout, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=300)
        for line in proc.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3 and parts[1].startswith(":refs/heads/"):
                results[parts[1][len(":refs/heads/"):]] = "deleted" if parts[0] == "-" else parts[2]
        for b in chunk:
            results.setdefault(b.name, f"no result (git push exit {proc.returncode}: "
                                       f"{proc.stderr.strip()[-200:]})")
    return results


def default_log(slug: str, now: dt.datetime) -> Path:
    base = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return base / "branch-sweep" / f"{slug.replace('/', '-')}-{now:%Y%m%dT%H%M%SZ}.tsv"


def write_log(path: Path, slug: str, remote: str, doomed: list[Branch]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# branch-sweep {slug}: branches deleted after their PR merged",
             f"# restore one: git fetch {remote} pull/<pr>/head && git push {remote} <sha>:refs/heads/<branch>",
             "branch\tsha\tpr"]
    lines += [f"{b.name}\t{b.sha}\t{b.pr}" for b in doomed]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ─── Report ─────────────────────────────────────────────────────

def age_days(committed: str, now: dt.datetime) -> str:
    when = _when(committed)
    return f"{(now - when).days} d" if when else "?"


def report(slug: str, default: str, auto_delete: bool, branches: list[Branch], now: dt.datetime) -> str:
    out = [f"branch-sweep: {slug} — {len(branches)} branches, default {default or '?'}, "
           f"delete_branch_on_merge {'on' if auto_delete else 'OFF'}"]
    for cls in CLASSES:
        group = [b for b in branches if b.cls == cls]
        if not group:
            continue
        what = ("deletable (each PR page restores it)" if cls == DELETABLE
                else "kept — a person decides" if cls in DECIDE else "kept")
        out.append(f"  {cls:<13}{len(group):>4}  {what}")
        if cls in ("default", "archived"):
            continue
        for b in sorted(group, key=lambda x: x.committed)[:LIST_CAP]:
            pr = f"#{b.pr}" if b.pr else ""
            out.append(f"      {b.name}  {pr}  {age_days(b.committed, now)}".rstrip())
        if len(group) > LIST_CAP:
            out.append(f"      ... {len(group) - LIST_CAP} more (--json lists every one)")
    n = sum(b.cls == DELETABLE for b in branches)
    if not auto_delete:
        out.append(f"Turn on delete_branch_on_merge so the list stops growing: "
                   f"branch-sweep.py --repo {slug} --enable-auto-delete")
    if n:
        out.append(f"Delete the {n} merged one(s): branch-sweep.py --repo {slug} --apply "
                   f"(from a checkout of {slug})")
    return "\n".join(out)


# ─── Entry point ────────────────────────────────────────────────

def main(argv: list[str] | None = None, now: dt.datetime | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", help="owner/name (default: the current checkout's repository)")
    ap.add_argument("--apply", action="store_true", help="delete the `merged` class (needs a checkout)")
    ap.add_argument("--remote", default="origin", help="the checkout's remote for --apply (default origin)")
    ap.add_argument("--log", type=Path, help="where --apply writes its log first")
    ap.add_argument("--min-age-hours", type=float, default=24.0,
                    help="a PR merged more recently than this is merged-recent and kept (default 24)")
    ap.add_argument("--enable-auto-delete", action="store_true",
                    help="set delete_branch_on_merge=true on the repository")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    now = now or dt.datetime.now(dt.timezone.utc)
    checkout = Path.cwd()
    try:
        slug = args.repo or gh("repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner",
                               cwd=checkout).strip()
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", slug or ""):
            raise SweepError(f"not an owner/name repository: {slug!r}")
        default, auto_delete, branches = read_repo(slug, now - dt.timedelta(hours=args.min_age_hours))
        if args.enable_auto_delete and not auto_delete:
            gh("api", "-X", "PATCH", f"repos/{slug}", "-F", "delete_branch_on_merge=true")
            auto_delete = True
        doomed = [b for b in branches if b.cls == DELETABLE]
        results: dict[str, str] = {}
        if args.apply and doomed:
            here = remote_slug(checkout, args.remote)
            if here.lower() != slug.lower():
                raise SweepError(f"--apply runs from a checkout of {slug}; remote {args.remote!r} "
                                 f"here is {here or 'not a GitHub repository'}")
            log = args.log or default_log(slug, now)
            try:
                write_log(log, slug, args.remote, doomed)
            except OSError as exc:
                raise SweepError(f"cannot write the log {log}, so nothing is deleted: {exc}") from exc
            results = delete_with_lease(checkout, args.remote, doomed)
    except SweepError as exc:
        print(f"branch-sweep: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"repo": slug, "default": default, "delete_branch_on_merge": auto_delete,
                          "branches": [{"name": b.name, "sha": b.sha, "class": b.cls, "pr": b.pr,
                                        "committed": b.committed} for b in branches],
                          "deleted": sorted(n for n, r in results.items() if r == "deleted"),
                          "refused": {n: r for n, r in results.items() if r != "deleted"}}, indent=1))
    else:
        print(report(slug, default, auto_delete, branches, now))
        if results:
            print(f"Log: {log}")
            for name, result in sorted(results.items()):
                print(f"  {'deleted' if result == 'deleted' else 'REFUSED'}  {name}"
                      + ("" if result == "deleted" else f"  ({result})"))
    return 3 if any(r != "deleted" for r in results.values()) else 0


# ─── Self-test ──────────────────────────────────────────────────
# Drives main() through a fake gh on PATH against a real bare remote whose path
# reads as github.com/acme/widgets, so the lease, the log-before-delete and the
# setting flag are checked through the entry point, not through the helpers.

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
open(os.environ["FAKE_GH_CALLS"], "a").write(" ".join(a) + "\n")
fx = json.load(open(os.environ["FAKE_GH_FIXTURE"]))
if a[:2] == ["repo", "view"]:
    print("acme/widgets")
elif a[:2] == ["api", "graphql"]:
    q = next(x for x in a if x.startswith("query="))
    key = "open" if "states:OPEN" in q else "refs"
    page = 1 if any(x.startswith("after=") for x in a) else 0
    print(json.dumps({"data": {"repository": fx[key][page]}}))
elif a[:3] == ["api", "-X", "PATCH"]:
    print("{}")
else:
    sys.exit(f"fake gh: unexpected {a}")
'''


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _node(name: str, sha: str, prs: list[dict], protected: bool = False, total: int | None = None) -> dict:
    return {"name": name, "branchProtectionRule": {"id": "r"} if protected else None,
            "target": {"oid": sha, "committedDate": "2026-11-01T00:00:00Z"},
            "associatedPullRequests": {"totalCount": len(prs) if total is None else total, "nodes": prs}}


def self_test() -> int:
    failures: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(f"  {'ok  ' if ok else 'FAIL'} {what}")
        if not ok:
            failures.append(what)

    with tempfile.TemporaryDirectory() as tmp_s:
        tmp = Path(tmp_s)
        bare = tmp / "github.com" / "acme" / "widgets.git"
        bare.parent.mkdir(parents=True)
        _git(tmp, "init", "-q", "--bare", "-b", "main", str(bare))
        work = tmp / "work"
        _git(tmp, "clone", "-q", str(bare), str(work))
        for k, v in (("user.email", "t@example.com"), ("user.name", "t")):
            _git(work, "config", k, v)
        _git(work, "commit", "-q", "--allow-empty", "-m", "init")
        _git(work, "push", "-q", "origin", "HEAD:refs/heads/main")
        sha: dict[str, str] = {}
        for name in ("done", "done2", "moved", "stale", "parent", "openhead", "guarded", "spike", "busy",
                     "archive/old", "fresh"):
            _git(work, "commit", "-q", "--allow-empty", "-m", name)
            sha[name] = _git(work, "rev-parse", "HEAD")
            _git(work, "push", "-q", "origin", f"HEAD:refs/heads/{name}")
        def merged(n: int, oid: str, at: str = "2026-11-20T00:00:00Z") -> dict:
            return {"number": n, "state": "MERGED", "headRefOid": oid, "mergedAt": at}
        refs_page0 = {"defaultBranchRef": {"name": "main"}, "deleteBranchOnMerge": False,
                      "refs": {"pageInfo": {"hasNextPage": True, "endCursor": "c1"}, "nodes": [
                          _node("main", sha["done"], []),
                          _node("done", sha["done"], [merged(1, sha["done"])]),
                          _node("moved", sha["moved"], [merged(2, "0" * 40)]),
                          # Classified at an older sha: the remote moved on, so the lease refuses.
                          _node("stale", "1" * 40, [merged(3, "1" * 40)]),
                          _node("parent", sha["parent"], [merged(4, sha["parent"])]),
                          _node("openhead", sha["openhead"], [merged(5, sha["openhead"]),
                                                              {"number": 6, "state": "OPEN",
                                                               "headRefOid": sha["openhead"]}]),
                      ]}}
        refs_page1 = {"defaultBranchRef": {"name": "main"}, "deleteBranchOnMerge": False,
                      "refs": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [
                          _node("guarded", sha["guarded"], [merged(7, sha["guarded"])], protected=True),
                          _node("spike", sha["spike"], [{"number": 8, "state": "CLOSED",
                                                         "headRefOid": sha["spike"]}]),
                          _node("busy", sha["busy"], [merged(9, sha["busy"])], total=PR_PAGE + 1),
                          _node("done2", sha["done2"], [merged(10, sha["done2"])]),
                          _node("archive/old", sha["archive/old"], [merged(11, sha["archive/old"])]),
                          # Merged 2 h before `now`: its session may still be on it.
                          _node("fresh", sha["fresh"], [merged(12, sha["fresh"], "2026-11-26T22:00:00Z")]),
                      ]}}
        open_pages = [{"pullRequests": {"pageInfo": {"hasNextPage": False}, "nodes": [{"baseRefName": "parent"}]}}]
        fixture = tmp / "fixture.json"
        fixture.write_text(json.dumps({"refs": [refs_page0, refs_page1], "open": open_pages}))
        bindir = tmp / "bin"
        bindir.mkdir()
        (bindir / "gh").write_text(FAKE_GH)
        (bindir / "gh").chmod(0o755)
        calls = tmp / "calls.txt"
        env = {"PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
               "FAKE_GH_FIXTURE": str(fixture), "FAKE_GH_CALLS": str(calls),
               "CLAUDE_CONFIG_DIR": str(tmp / "cfg")}
        saved = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        old_cwd = Path.cwd()
        os.chdir(work)
        now = dt.datetime(2026, 11, 27, tzinfo=dt.timezone.utc)

        def remote_has(name: str) -> bool:
            return bool(_git(work, "ls-remote", "origin", f"refs/heads/{name}"))

        def run_main(*argv: str) -> tuple[int, str]:
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                code = main(list(argv), now=now)
            return code, buf.getvalue()

        try:
            print("classification (both pages read, through main):")
            code, out = run_main("--json")
            data = json.loads(out)
            got = {b["name"]: b["class"] for b in data["branches"]}
            want = {"main": "default", "done": "merged", "done2": "merged", "moved": "merged-moved",
                    "stale": "merged", "parent": "open-base", "openhead": "open-pr",
                    "guarded": "protected", "spike": "closed", "busy": "unknown",
                    "archive/old": "archived", "fresh": "merged-recent"}
            for name, cls in want.items():
                check(got.get(name) == cls, f"{name} is {cls} (got {got.get(name)})")
            check(code == 0, "a report exits 0")
            check(all(remote_has(n) for n in ("done", "done2", "stale")), "a report deletes nothing")
            check("PATCH" not in calls.read_text(), "a report changes no setting")
            nb = Branch("x", "a" * 40, prs=[{"number": 1, "state": "MERGED", "headRefOid": "a" * 40,
                                             "mergedAt": "2026-11-01T00:00:00Z"}])
            check(classify(nb, "main", set())[0] == "merged" and classify(nb, "x", set())[0] == "default",
                  "the default branch outranks a merged PR")
            check(classify(nb, "main", set(), now)[0] == "merged"
                  and classify(Branch("y", "b" * 40, prs=[{"number": 2, "state": "MERGED",
                                                           "headRefOid": "b" * 40}]),
                               "main", set(), now)[0] == "merged-recent",
                  "a merged PR with no readable mergedAt is held as recent")
            code, out = run_main("--json", "--min-age-hours", "1")
            check({b["name"]: b["class"] for b in json.loads(out)["branches"]}.get("fresh") == "merged",
                  "--min-age-hours reaches the classification")

            print("--apply refuses without a log, and from a checkout of another repository:")
            blocker = tmp / "blocker"
            blocker.write_text("a file where the log directory would go")
            code, out = run_main("--apply", "--log", str(blocker / "sweep.tsv"))
            check(code == 1 and remote_has("done"), "an unwritable log exits 1 and deletes nothing")
            _git(work, "remote", "add", "other", str(tmp / "github.com" / "acme" / "gadgets.git"))
            code, out = run_main("--apply", "--remote", "other")
            check(code == 1 and remote_has("done") and "checkout of acme/widgets" in out,
                  "a remote naming another repository exits 1 and deletes nothing")

            print("--apply deletes exactly the merged class, under a lease:")
            log = tmp / "sweep.tsv"
            code, out = run_main("--apply", "--log", str(log))
            check(not remote_has("done") and not remote_has("done2"), "both merged branches are deleted")
            check(remote_has("stale"), "a branch whose tip moved since it was read is kept (lease)")
            check(code == 3 and "REFUSED  stale" in out, "the refused lease exits 3 and is named")
            kept = ("main", "moved", "parent", "openhead", "guarded", "spike", "busy", "archive/old", "fresh")
            check(all(remote_has(n) for n in kept), "every other class is untouched")
            text = log.read_text() if log.is_file() else ""
            check(f"done\t{sha['done']}\t1" in text and "stale\t" in text,
                  "the log names each branch, sha and PR before the push")
            check("PATCH" not in calls.read_text(), "--apply alone changes no setting")

            print("--enable-auto-delete:")
            code, out = run_main("--enable-auto-delete")
            check("PATCH repos/acme/widgets -F delete_branch_on_merge=true" in calls.read_text(),
                  "--enable-auto-delete sets delete_branch_on_merge")
        finally:
            os.chdir(old_cwd)
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    print(f"branch-sweep self-test: {'FAILED ' + str(len(failures)) if failures else 'all passed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
