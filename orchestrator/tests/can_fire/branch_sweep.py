"""branch-sweep.py's mutations, loaded into test_self_tests_can_fire.py's MUTATIONS.

Each one removes one guard that keeps the sweep from deleting a branch that
still holds something, and its --self-test must turn red. That self-test drives
main() through a fake gh on PATH (two GraphQL pages, one open-PR page) against
a real bare remote, so the lease and the log-before-delete are exercised
through the entry point.
"""

from __future__ import annotations

MUTATIONS: dict[str, list[tuple[str, str, str]]] = {"configs/scripts/branch-sweep.py": [
    # Classification: every class that keeps a branch.
    ("the default branch is never touched",
     "    if b.name == default:\n        return \"default\", None",
     "    if False:\n        return \"default\", None"),
    ("a protected branch is never touched",
     "    if b.protected:",
     "    if False:"),
    ("a branch with more PRs than one query returns is unknown, not merged",
     "    if not b.prs_complete:",
     "    if False:"),
    ("an open PR outranks an older merged one on the same branch",
     "    if open_prs:",
     "    if False:"),
    ("the base of an open PR is kept",
     "    if b.name in open_bases:",
     "    if False:"),
    ("archive/ and backup/ branches are kept",
     "    if b.name.startswith(ARCHIVE_PREFIXES):",
     "    if False:"),
    ("only a tip that IS the merged PR's head is deletable — later commits would be lost",
     '        if p.get("headRefOid") == b.sha:',
     "        if True:"),
    ("a PR merged within --min-age-hours is held for its session",
     "            if cutoff is not None and (when is None or when > cutoff):",
     "            if False:"),
    ("--min-age-hours reaches the classification",
     "read_repo(slug, now - dt.timedelta(hours=args.min_age_hours))",
     "read_repo(slug, now - dt.timedelta(hours=24))"),
    # Reading: the second page of branches.
    ("every page of branches is read",
     '        if not info.get("hasNextPage"):\n            return',
     "        if True:\n            return"),
    # Deleting.
    ("each deletion carries a lease on the sha it was classified at",
     '        cmd += [f"--force-with-lease=refs/heads/{b.name}:{b.sha}" for b in chunk]',
     "        cmd += []"),
    ("the log is written before anything is deleted",
     "                write_log(log, slug, args.remote, doomed)",
     "                pass"),
    ("--apply runs only from a checkout of the same repository",
     "            if here.lower() != slug.lower():",
     "            if False:"),
    ("a refused deletion exits 3",
     '    return 3 if any(r != "deleted" for r in results.values()) else 0',
     "    return 0"),
    # The setting.
    ("delete_branch_on_merge changes only under --enable-auto-delete",
     "        if args.enable_auto_delete and not auto_delete:",
     "        if not auto_delete:"),
]}
