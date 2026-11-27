#!/usr/bin/env python3
"""
land-pr.py — merge a PR on the gate of its own head, into whatever main is now.

The rule (configs/CLAUDE.md, "Merge, then test: no queue, no re-gate"): a PR is
gated once, on its head. It merges when that record is green for the exact head
and the head merges cleanly into the CURRENT default branch. Main moving after
the gate is never a reason to gate again; a post-merge runner (mainline-ci.py)
tests every new main tree and traces a red one to the merge that broke it.

Measured in a private repository on 2026-11-10: each PR ran about three full
suites (its head, then re-gates after main moved) at 17 minutes each on a
14-worker host: one on its head, the rest re-gates after main moved.

Usage
-----
    land-pr.py <pr> --record gate.json        check, then merge
    land-pr.py <pr> --record gate.json --dry-run
    land-pr.py <pr> --method squash           override the repository's method
    land-pr.py --self-test

The record is either the tiny format

    {"head": "<sha>", "exit": 0, "summary": "...", "ended": "<ISO-8601>"}

(optional "dirty": true marks a run that tested more than the head), or the
JSON `ci-local.py --json` prints, which carries `head`, `dirty` and `verdict`:

    python3 ci-local.py --json > gate.json     # on a clean checkout of the PR head

Without --record it reads <git common dir>/clade-gate/<head sha>.json.

Checks, in order, each with its own exit code:

    10  the PR is not open             15  the record names another head
    11  the PR is a draft              16  the record does not certify the head
    12  the base is not the default        (dirty tree, PARTIAL without
        branch (stacks land bottom-up       --allow-partial, FLAKY, no verdict)
        through merge-pr)              17  the head conflicts with current main
    13  no gate record                 18  `gh pr merge` refused
    14  the record is red              19  the forge never reported mergedAt
    20  git or gh failed               21  the merge method is not allowed
    22  the merge result fails `.claude/merge-check.sh`

Before merging it runs the repository's own `.claude/merge-check.sh`, when the
merge result carries one, in a throwaway worktree of that result (both parents,
the tree merge-tree wrote). It is for properties of the WHOLE tree that two
individually green PRs can break together: a line cap, a byte ceiling, a count
of generated files. Each PR's gate tests its own head, so it cannot see them; on
2026-11-26 three such pairs kept Clade's main red for 2 h 44 min. Keep it to
seconds: it is not a second gate. The script gets LAND_PR_REPO (the checkout
land-pr was run from), LAND_PR_BASE and LAND_PR_HEAD.

A conflict resolution is new code: it makes a new head, and that head needs its
own gate. The merge runs `gh pr merge --match-head-commit <sha>`, so a push
after the checks cannot land ungated. Branch protection is never bypassed: a
"require branches to be up to date" setting makes the forge refuse, and that
refusal is exit 18, reported as such.

Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

EXIT_NOT_OPEN = 10
EXIT_DRAFT = 11
EXIT_WRONG_BASE = 12
EXIT_NO_RECORD = 13
EXIT_RED = 14
EXIT_HEAD_MISMATCH = 15
EXIT_UNCERTIFIED = 16
EXIT_CONFLICT = 17
EXIT_MERGE_FAILED = 18
EXIT_NOT_CONFIRMED = 19
EXIT_TOOL = 20
EXIT_METHOD = 21
EXIT_MERGE_CHECK = 22

MERGE_CHECK = ".claude/merge-check.sh"

PR_FIELDS = "number,state,isDraft,baseRefName,headRefName,headRefOid,mergedAt,url"
REPO_FIELDS = "defaultBranchRef,mergeCommitAllowed,squashMergeAllowed,rebaseMergeAllowed"


class Refusal(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


# ─── Tools ───────────────────────────────────────────────────────────────────

def run(cmd: list[str], cwd: Path, timeout: float = 300,
        env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
                              env=env, stdin=subprocess.DEVNULL)
    except FileNotFoundError as exc:
        raise Refusal(EXIT_TOOL, f"{cmd[0]} not found: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise Refusal(EXIT_TOOL, f"{' '.join(cmd[:3])} timed out after {timeout} s") from exc


def gh_json(repo: Path, *args: str) -> dict:
    out = run(["gh", *args], repo)
    if out.returncode != 0:
        raise Refusal(EXIT_TOOL, f"gh {' '.join(args[:2])} failed: {out.stderr.strip()[-400:]}")
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError as exc:
        raise Refusal(EXIT_TOOL, f"gh {' '.join(args[:2])} printed no JSON") from exc
    if not isinstance(data, dict):
        raise Refusal(EXIT_TOOL, f"gh {' '.join(args[:2])} printed {type(data).__name__}, not an object")
    return data


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], repo)


# ─── The gate record ─────────────────────────────────────────────────────────

@dataclass
class Record:
    head: str | None
    green: bool
    certified: bool
    why: str


def read_record(data: dict, allow_partial: bool) -> Record:
    """What a record says about one head: is it green, and does it certify that head alone?"""
    head = data.get("head") if isinstance(data.get("head"), str) else None
    if data.get("dirty"):
        return Record(head, True, False, "the run started on a dirty tree, so it did not test the head alone")
    if "verdict" in data:  # ci-local.py --json
        v = data.get("verdict")
        if v == "pass":
            return Record(head, True, True, "ci-local verdict pass")
        if v == "partial" and allow_partial:
            lanes = ", ".join(f"{u.get('job')} > {u.get('step') or '(job)'}" for u in data.get("unproven") or [])
            return Record(head, True, True, f"ci-local verdict partial, accepted by --allow-partial: {lanes}")
        if v == "partial":
            return Record(head, True, False, "ci-local verdict partial: unproven lanes; prove them, or "
                                             "pass --allow-partial if they are proven elsewhere")
        if v == "flaky":
            return Record(head, True, False, "ci-local verdict flaky: a step passed only on its rerun")
        return Record(head, False, True, f"ci-local verdict {v}")
    code = data.get("exit")
    if not isinstance(code, int) or isinstance(code, bool):
        return Record(head, False, False, "the record carries neither a verdict nor an integer exit")
    if code != 0:
        return Record(head, False, True, f"exit {code}: {str(data.get('summary', ''))[:200]}")
    return Record(head, True, True, f"exit 0: {str(data.get('summary', ''))[:200]}")


def default_record_path(repo: Path, head: str) -> Path:
    out = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if out.returncode != 0:
        raise Refusal(EXIT_TOOL, f"not a git repository: {repo}")
    return Path(out.stdout.strip()) / "clade-gate" / f"{head}.json"


# ─── The checks ──────────────────────────────────────────────────────────────

def fetch(repo: Path, remote: str, default: str, pr: dict) -> None:
    """The current default branch, and the PR head by sha, PR ref or branch name."""
    out = git(repo, "fetch", "-q", remote, f"+refs/heads/{default}:refs/remotes/{remote}/{default}")
    if out.returncode != 0:
        raise Refusal(EXIT_TOOL, f"git fetch {remote} {default} failed: {out.stderr.strip()[-400:]}")
    head = pr["headRefOid"]
    for ref in (head, f"refs/pull/{pr['number']}/head", f"refs/heads/{pr.get('headRefName') or ''}"):
        if git(repo, "cat-file", "-e", f"{head}^{{commit}}").returncode == 0:
            return
        git(repo, "fetch", "-q", remote, ref)
    if git(repo, "cat-file", "-e", f"{head}^{{commit}}").returncode != 0:
        raise Refusal(EXIT_TOOL, f"could not fetch the PR head {head} from {remote}")


def merges_cleanly(repo: Path, remote: str, default: str, head: str) -> str:
    """The tree the merge would produce; a conflict is a refusal."""
    out = git(repo, "merge-tree", "--write-tree", "--name-only", f"{remote}/{default}", head)
    if out.returncode == 1:
        # --name-only: the tree id, the conflicted paths, a blank line, then messages.
        files = []
        for line in out.stdout.splitlines()[1:]:
            if not line:
                break
            files.append(line)
        raise Refusal(EXIT_CONFLICT, f"{head[:12]} conflicts with {remote}/{default} ({', '.join(files[:8]) or 'see git merge-tree'}). "
                                     "Resolve it on the branch; the resolution is a new head and needs its own gate.")
    if out.returncode != 0:
        raise Refusal(EXIT_TOOL, f"git merge-tree failed (git >= 2.38 needed): {out.stderr.strip()[-300:]}")
    return out.stdout.split("\n", 1)[0].strip()


def merge_check(repo: Path, base_ref: str, head: str, tree: str, timeout: float) -> str:
    """Run the merge result's own `.claude/merge-check.sh` in a throwaway worktree of that result."""
    if git(repo, "cat-file", "-e", f"{tree}:{MERGE_CHECK}").returncode != 0:
        return f"no {MERGE_CHECK} in the merge result"
    base = git(repo, "rev-parse", "--verify", f"{base_ref}^{{commit}}").stdout.strip()
    ident = {**os.environ, "GIT_AUTHOR_NAME": "land-pr", "GIT_AUTHOR_EMAIL": "land-pr@localhost",
             "GIT_COMMITTER_NAME": "land-pr", "GIT_COMMITTER_EMAIL": "land-pr@localhost"}
    made = run(["git", "commit-tree", tree, "-p", base, "-p", head, "-m", "land-pr merge check"], repo, env=ident)
    if made.returncode != 0 or not base:
        raise Refusal(EXIT_TOOL, f"could not make the merge-result commit: {made.stderr.strip()[-300:]}")
    with tempfile.TemporaryDirectory(prefix="land-pr-check-") as tmp:
        tree_dir = Path(tmp) / "merged"
        add = git(repo, "worktree", "add", "--quiet", "--detach", str(tree_dir), made.stdout.strip())
        if add.returncode != 0:
            raise Refusal(EXIT_TOOL, f"git worktree add failed: {add.stderr.strip()[-300:]}")
        try:
            env = {**os.environ, "LAND_PR_REPO": str(repo), "LAND_PR_BASE": base, "LAND_PR_HEAD": head}
            # Its own session, so a timeout ends everything it started, not only bash.
            proc = subprocess.Popen(["bash", MERGE_CHECK], cwd=str(tree_dir), stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, env=env,
                                    start_new_session=True)
            try:
                output, _ = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.communicate()
                raise Refusal(EXIT_MERGE_CHECK, f"{MERGE_CHECK} on the merge result timed out after {timeout:g} s") from exc
        finally:
            git(repo, "worktree", "remove", "--force", str(tree_dir))
            git(repo, "worktree", "prune")
    if proc.returncode != 0:
        tail = "\n".join(output.strip().splitlines()[-20:])
        raise Refusal(EXIT_MERGE_CHECK, f"{MERGE_CHECK} failed (exit {proc.returncode}) on the merge of {head[:12]} into "
                                        f"{base[:12]}: each side is green alone, together they are not. Fix forward on "
                                        f"the branch; the fix is a new head and needs its own gate.\n{tail}")
    return f"{MERGE_CHECK} passed on the merge result"


def choose_method(requested: str, repo_info: dict) -> str:
    allowed = [m for m, key in (("merge", "mergeCommitAllowed"), ("squash", "squashMergeAllowed"),
                                ("rebase", "rebaseMergeAllowed")) if repo_info.get(key)]
    if requested != "auto":
        if requested not in allowed:
            raise Refusal(EXIT_METHOD, f"--method {requested} is not allowed here; allowed: {', '.join(allowed) or 'none'}")
        return requested
    # Rebase replays commits, so its tree is not guaranteed to be the one
    # merge-tree checked; it is used only when asked for or the only method.
    for method in ("merge", "squash"):
        if method in allowed:
            return method
    if allowed:
        return allowed[0]
    raise Refusal(EXIT_METHOD, "the repository allows no merge method")


def land(args: argparse.Namespace) -> str:
    repo = Path(args.repo).resolve()
    pr = gh_json(repo, "pr", "view", str(args.pr), "--json", PR_FIELDS)
    if str(pr.get("state")).upper() != "OPEN":
        raise Refusal(EXIT_NOT_OPEN, f"PR #{pr.get('number')} is {pr.get('state')}, not open")
    if pr.get("isDraft"):
        raise Refusal(EXIT_DRAFT, f"PR #{pr.get('number')} is a draft")
    repo_info = gh_json(repo, "repo", "view", "--json", REPO_FIELDS)
    default = (repo_info.get("defaultBranchRef") or {}).get("name")
    if not default:
        raise Refusal(EXIT_TOOL, "gh repo view named no default branch")
    if pr.get("baseRefName") != default:
        raise Refusal(EXIT_WRONG_BASE, f"PR #{pr['number']} targets {pr.get('baseRefName')}, not {default}; "
                                       "a stacked PR lands bottom-up through merge-pr")
    head = pr.get("headRefOid") or ""

    path = Path(args.record) if args.record else default_record_path(repo, head)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise Refusal(EXIT_NO_RECORD, f"no gate record at {path}. Gate the head once: on a clean checkout of "
                                      f"{head[:12]}, run `python3 ci-local.py --json > {path}`") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise Refusal(EXIT_NO_RECORD, f"unreadable gate record {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise Refusal(EXIT_NO_RECORD, f"gate record {path} is not a JSON object")
    record = read_record(data, args.allow_partial)
    if record.head != head:
        raise Refusal(EXIT_HEAD_MISMATCH, f"the record is for {record.head or 'no head'}, the PR head is {head}. "
                                          "Gate the head the PR has now.")
    if not record.green:
        raise Refusal(EXIT_RED, f"the gate of {head[:12]} is red ({record.why})")
    if not record.certified:
        raise Refusal(EXIT_UNCERTIFIED, f"the record does not certify {head[:12]}: {record.why}")

    fetch(repo, args.remote, default, pr)
    tree = merges_cleanly(repo, args.remote, default, head)
    checked = merge_check(repo, f"{args.remote}/{default}", head, tree, args.merge_check_timeout)
    method = choose_method(args.method, repo_info)
    plan = (f"PR #{pr['number']} head {head[:12]}: gate green ({record.why}); merges cleanly into "
            f"{args.remote}/{default}; {checked}")
    if args.dry_run:
        return f"would merge ({method}): {plan}"

    out = run(["gh", "pr", "merge", str(pr["number"]), f"--{method}", "--match-head-commit", head], repo)
    if out.returncode != 0:
        raise Refusal(EXIT_MERGE_FAILED, f"gh pr merge refused: {(out.stderr or out.stdout).strip()[-500:]}. If branch "
                                         "protection requires up-to-date branches, that setting is the re-gate this "
                                         "rule removes (configs/CLAUDE.md).")
    deadline = time.monotonic() + args.confirm_wait
    while True:
        after = gh_json(repo, "pr", "view", str(pr["number"]), "--json", "mergedAt,state")
        merged_at = after.get("mergedAt")
        if merged_at or time.monotonic() >= deadline:
            break
        time.sleep(2)
    if not merged_at:
        raise Refusal(EXIT_NOT_CONFIRMED, f"gh pr merge returned 0 but PR #{pr['number']} reports state "
                                          f"{after.get('state')} with no mergedAt (queued or auto-merge?)")
    return f"merged ({method}) at {merged_at}: {plan}"


# ─── CLI ─────────────────────────────────────────────────────────────────────

def self_test() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import merge_then_test_cases as cases

    return cases.run_all(cases.LAND_CASES, Path(__file__).resolve())


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["--self-test"]:
        return self_test()
    ap = argparse.ArgumentParser(description="Merge a PR on the gate of its own head, into the current main.",
                                 epilog="Exit codes 10-22 name each refusal; see the module docstring.")
    ap.add_argument("pr", help="PR number or URL")
    ap.add_argument("--record", help="gate record JSON (default <git common dir>/clade-gate/<head>.json)")
    ap.add_argument("--repo", default=".", help="local checkout of the repository (default: cwd)")
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--method", choices=("auto", "merge", "squash", "rebase"), default="auto",
                    help="auto: merge commits when allowed, else squash, else the only allowed method")
    ap.add_argument("--allow-partial", action="store_true",
                    help="accept a ci-local PARTIAL verdict; its unproven lanes must be proven elsewhere")
    ap.add_argument("--dry-run", action="store_true", help="run every check, merge nothing")
    ap.add_argument("--merge-check-timeout", type=float, default=600.0,
                    help=f"seconds {MERGE_CHECK} may take on the merge result (default 600)")
    ap.add_argument("--confirm-wait", type=float, default=20.0,
                    help="seconds to wait for the forge to report mergedAt (default 20)")
    args = ap.parse_args(argv)
    try:
        print(f"land-pr: {land(args)}")
        return 0
    except Refusal as exc:
        print(f"land-pr: refused ({exc.code}): {exc}", file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
