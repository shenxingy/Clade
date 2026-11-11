#!/usr/bin/env python3
"""merge_then_test_cases.py — the cases land-pr.py and mainline-ci.py prove themselves on.

Imported by both scripts' self-tests and by orchestrator/tests/test_land_pr.py and
test_mainline_ci.py, so the suite and the mutation harness run one table. It holds
no guard: every guard stays in the two scripts, where test_self_tests_can_fire.py
(via can_fire/merge_then_test.py) removes it and the mutated script's own self-test
must go red.

Every case builds a throwaway world: a bare origin, clones of it, a fake `gh` on
PATH that answers from a JSON file and records what it was asked, and a gate
command that reads the checked-out tree. Each case runs the script under test as
a subprocess, through its own CLI, and asserts on its exit code and on what it
left behind (the merge call, the records).

Stdlib only.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import shlex
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Callable, Mapping

Case = Callable[[Path, Path], None]

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
path = os.environ["FAKE_GH_STATE"]
with open(path) as fh:
    st = json.load(fh)
args = sys.argv[1:]
st.setdefault("calls", []).append(args)
def save():
    with open(path, "w") as fh:
        json.dump(st, fh)
def fields():
    return args[args.index("--json") + 1].split(",") if "--json" in args else []
if args[:2] == ["pr", "view"]:
    save(); print(json.dumps({k: st["pr"].get(k) for k in fields()})); sys.exit(0)
if args[:2] == ["repo", "view"]:
    save(); print(json.dumps({k: st["repo"].get(k) for k in fields()})); sys.exit(0)
if args[:2] == ["pr", "merge"]:
    if st.get("merge_refused"):
        save(); print("base branch policy prohibits the merge", file=sys.stderr); sys.exit(1)
    if "--match-head-commit" in args and args[args.index("--match-head-commit") + 1] != st["pr"]["headRefOid"]:
        save(); print("head branch was modified", file=sys.stderr); sys.exit(1)
    st["merged_with"] = args
    if not st.get("merge_unconfirmed"):
        st["pr"]["state"] = "MERGED"; st["pr"]["mergedAt"] = "2026-01-01T00:00:00Z"
    save(); sys.exit(0)
save(); print("fake gh: unsupported " + " ".join(args), file=sys.stderr); sys.exit(2)
'''


def expect(cond: object, message: str) -> None:
    if not cond:
        raise AssertionError(message)


# ─── The world: a bare origin, clones, a fake gh ──────────────────────────────

class World:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.origin = root / "origin.git"
        self.work = root / "work"
        self.bin = root / "bin"
        self.gh_state = root / "gh.json"
        self.bin.mkdir(parents=True)
        (self.bin / "gh").write_text(FAKE_GH)
        (self.bin / "gh").chmod(0o755)
        self.env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
                    "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
                    "FAKE_GH_STATE": str(self.gh_state)}
        self.git(root, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.git(root, "clone", "-q", str(self.origin), str(self.work))
        self.git(self.work, "symbolic-ref", "HEAD", "refs/heads/main")
        self.base = self.commit({"shared.txt": "line\n", "README": "base\n"}, "chore: base")
        self.git(self.work, "push", "-q", "origin", "main")

    def git(self, cwd: Path, *args: str) -> str:
        out = subprocess.run(["git", *args], cwd=str(cwd), env=self.env, capture_output=True, text=True, timeout=120)
        expect(out.returncode == 0, f"fixture git {' '.join(args)} failed: {out.stderr}")
        return out.stdout.strip()

    def commit(self, files: Mapping[str, str | None], message: str) -> str:
        for name, content in files.items():
            path = self.work / name
            if content is None:
                path.unlink()
            else:
                path.write_text(content)
        self.git(self.work, "add", "-A")
        self.git(self.work, "commit", "-q", "--allow-empty", "-m", message)
        return self.git(self.work, "rev-parse", "HEAD")

    def clone(self, name: str) -> Path:
        path = self.root / name
        self.git(self.root, "clone", "-q", str(self.origin), str(path))
        return path

    def merge_pr(self, number: int, files: Mapping[str, str | None]) -> str:
        """A topic branch with one commit, merged into main with --no-ff and pushed: one first-parent merge."""
        branch = f"topic-{number}"
        self.git(self.work, "checkout", "-q", "-b", branch, "main")
        self.commit(files, f"feat: change {number}")
        self.git(self.work, "checkout", "-q", "main")
        self.git(self.work, "merge", "-q", "--no-ff", "-m", f"Merge pull request #{number} from {branch}", branch)
        self.git(self.work, "push", "-q", "origin", "main")
        return self.git(self.work, "rev-parse", "HEAD")

    def run(self, script: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(script), *args], env=self.env, capture_output=True,
                              text=True, timeout=300, stdin=subprocess.DEVNULL)

    def gh(self) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self.gh_state.read_text())
        return data


def run_all(cases: list[tuple[str, Case]], script: Path) -> int:
    failed = 0
    for name, case in cases:
        with tempfile.TemporaryDirectory(prefix="merge-then-test-") as tmp:
            try:
                case(Path(tmp), script)
                print(f"  PASS {name}")
            except Exception as exc:  # noqa: BLE001 - every failure is reported, then counted
                failed += 1
                print(f"  FAIL {name}: {exc}")
                if not isinstance(exc, AssertionError):
                    traceback.print_exc()
    print(f"{script.name} self-test: {len(cases) - failed}/{len(cases)} passed")
    return 1 if failed else 0


# ─── land-pr.py ──────────────────────────────────────────────────────────────

def _pr_world(tmp: Path, *, conflict: bool = False, pr: dict[str, Any] | None = None,
              repo: dict[str, Any] | None = None, **gh: Any) -> tuple[World, Path, str]:
    """A PR gated on its head, then main moves (a conflicting edit when asked) and the lander's clone is stale."""
    w = World(tmp)
    lander = w.clone("lander")
    w.git(w.work, "checkout", "-q", "-b", "feat")
    head = w.commit({"shared.txt" if conflict else "feature.txt": "feature\n"}, "feat: the PR")
    w.git(w.work, "push", "-q", "origin", "feat")
    w.git(w.work, "checkout", "-q", "main")
    w.commit({"shared.txt" if conflict else "other.txt": "main moved\n"}, "fix: main moved on")
    w.git(w.work, "push", "-q", "origin", "main")
    state = {"pr": {"number": 7, "state": "OPEN", "isDraft": False, "baseRefName": "main", "headRefName": "feat",
                    "headRefOid": head, "mergedAt": None, "url": "https://example.invalid/pull/7", **(pr or {})},
             "repo": {"defaultBranchRef": {"name": "main"}, "mergeCommitAllowed": True,
                      "squashMergeAllowed": True, "rebaseMergeAllowed": False, **(repo or {})}, **gh}
    w.gh_state.write_text(json.dumps(state))
    return w, lander, head


def _land(w: World, script: Path, lander: Path, record: dict[str, Any], *extra: str) -> subprocess.CompletedProcess[str]:
    path = w.root / "gate.json"
    path.write_text(json.dumps(record))
    return w.run(script, "7", "--repo", str(lander), "--record", str(path), "--confirm-wait", "0", *extra)


def _green(head: str) -> dict[str, Any]:
    return {"head": head, "exit": 0, "summary": "all passed", "ended": "2026-01-01T00:00:00Z"}


def _refused(out: subprocess.CompletedProcess[str], code: int, w: World, what: str) -> None:
    expect(out.returncode == code, f"{what}: expected exit {code}, got {out.returncode}: {out.stderr.strip()[-300:]}")
    expect("merged_with" not in w.gh(), f"{what}: gh pr merge ran anyway")


def land_merges_after_main_moved(tmp: Path, script: Path) -> None:
    w, lander, head = _pr_world(tmp)
    out = _land(w, script, lander, _green(head))
    expect(out.returncode == 0, f"a green head that merges cleanly into a moved main must land: {out.stderr}")
    call = w.gh().get("merged_with") or []
    expect(call[:3] == ["pr", "merge", "7"] and "--merge" in call, f"merge commits are preferred: {call}")
    expect(call[-2:] == ["--match-head-commit", head], f"the merge is locked to the gated head: {call}")
    expect("merged (merge)" in out.stdout, f"the confirmation is reported: {out.stdout}")


def land_accepts_ci_local_json(tmp: Path, script: Path) -> None:
    w, lander, head = _pr_world(tmp)
    out = _land(w, script, lander, {"verdict": "pass", "head": head, "dirty": False, "exit": 0, "unproven": []})
    expect(out.returncode == 0, f"ci-local's own JSON is a record: {out.stderr}")


def land_partial_needs_the_flag(tmp: Path, script: Path) -> None:
    w, lander, head = _pr_world(tmp)
    rec = {"verdict": "partial", "head": head, "dirty": False, "exit": 0,
           "unproven": [{"job": "Lint", "step": "secret step"}]}
    _refused(_land(w, script, lander, rec), 16, w, "a PARTIAL verdict without --allow-partial")
    out = _land(w, script, lander, rec, "--allow-partial")
    expect(out.returncode == 0, f"--allow-partial accepts it: {out.stderr}")


def land_refuses_flaky_and_dirty(tmp: Path, script: Path) -> None:
    w, lander, head = _pr_world(tmp)
    _refused(_land(w, script, lander, {"verdict": "flaky", "head": head, "dirty": False}), 16, w, "a FLAKY verdict")
    _refused(_land(w, script, lander, {**_green(head), "dirty": True}), 16, w, "a record from a dirty tree")


def land_refuses_red(tmp: Path, script: Path) -> None:
    w, lander, head = _pr_world(tmp)
    _refused(_land(w, script, lander, {**_green(head), "exit": 1, "summary": "2 failed"}), 14, w, "a red record")
    _refused(_land(w, script, lander, {"verdict": "fail", "head": head, "dirty": False}), 14, w, "a ci-local fail")


def land_refuses_another_head(tmp: Path, script: Path) -> None:
    w, lander, _head = _pr_world(tmp)
    _refused(_land(w, script, lander, _green(w.base)), 15, w, "a record for another head")


def land_refuses_a_conflict(tmp: Path, script: Path) -> None:
    w, lander, head = _pr_world(tmp, conflict=True)
    out = _land(w, script, lander, _green(head))
    _refused(out, 17, w, "a head that conflicts with the current main")
    expect("shared.txt" in out.stderr, f"the conflicting path is named: {out.stderr}")


def land_refuses_draft_and_closed(tmp: Path, script: Path) -> None:
    w, lander, head = _pr_world(tmp, pr={"isDraft": True})
    _refused(_land(w, script, lander, _green(head)), 11, w, "a draft PR")
    w2, lander2, head2 = _pr_world(tmp / "closed", pr={"state": "CLOSED"})
    _refused(_land(w2, script, lander2, _green(head2)), 10, w2, "a closed PR")


def land_refuses_wrong_base(tmp: Path, script: Path) -> None:
    w, lander, head = _pr_world(tmp, pr={"baseRefName": "release"})
    _refused(_land(w, script, lander, _green(head)), 12, w, "a PR into another branch")


def land_refuses_missing_record_and_method(tmp: Path, script: Path) -> None:
    w, lander, head = _pr_world(tmp)
    out = w.run(script, "7", "--repo", str(lander), "--confirm-wait", "0")
    _refused(out, 13, w, "no gate record at the default path")
    _refused(_land(w, script, lander, _green(head), "--method", "rebase"), 21, w, "a disabled merge method")


def land_needs_the_forge_to_confirm(tmp: Path, script: Path) -> None:
    w, lander, head = _pr_world(tmp, merge_unconfirmed=True)
    out = _land(w, script, lander, _green(head))
    expect(out.returncode == 19, f"a merge the forge never reports is not merged: {out.returncode} {out.stderr}")
    w2, lander2, head2 = _pr_world(tmp / "refused", merge_refused=True)
    out = _land(w2, script, lander2, _green(head2))
    expect(out.returncode == 18 and "up-to-date" in out.stderr, f"a forge refusal is exit 18: {out.stderr}")


LAND_CASES: list[tuple[str, Case]] = [
    ("merges after main moved, locked to the head", land_merges_after_main_moved),
    ("accepts ci-local --json as the record", land_accepts_ci_local_json),
    ("PARTIAL needs --allow-partial", land_partial_needs_the_flag),
    ("refuses FLAKY and a dirty tree", land_refuses_flaky_and_dirty),
    ("refuses a red record", land_refuses_red),
    ("refuses a record for another head", land_refuses_another_head),
    ("refuses a conflict with the current main", land_refuses_a_conflict),
    ("refuses a draft and a closed PR", land_refuses_draft_and_closed),
    ("refuses a PR into another base", land_refuses_wrong_base),
    ("refuses no record and a disabled method", land_refuses_missing_record_and_method),
    ("needs mergedAt; reports a forge refusal", land_needs_the_forge_to_confirm),
]


# ─── mainline-ci.py ──────────────────────────────────────────────────────────

def _gate(tmp: Path, flag: Path | None = None) -> str:
    """Counts runs; fails on a BROKEN file in the tree, on a stray file a previous run left, or once on a flag."""
    count = shlex.quote(str(tmp / "runs"))
    once = f"if [ -f {shlex.quote(str(flag))} ]; then rm {shlex.quote(str(flag))}; echo once; exit 1; fi; " if flag else ""
    return (f"echo run >> {count}; test ! -e stray.txt || {{ echo stray; exit 1; }}; touch stray.txt; {once}"
            "if [ -f BROKEN ]; then echo '1 failed'; exit 1; fi; echo 'all passed'")


def _runs(tmp: Path) -> int:
    path = tmp / "runs"
    return len(path.read_text().splitlines()) if path.exists() else 0


def _tick(w: World, script: Path, runner: Path, gate: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return w.run(script, "tick", "--repo", str(runner), "--branch", "main", "--state-dir", str(w.root / "state"),
                 "--gate", gate, *extra)


def _history(w: World) -> list[dict[str, Any]]:
    path = w.root / "state" / "history.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def _red(w: World, sha: str) -> dict[str, Any]:
    path = w.root / "state" / "red" / f"{sha[:8]}.json"
    expect(path.exists(), f"no red record at {path}")
    data: dict[str, Any] = json.loads(path.read_text())
    return data


def mainline_green_then_skip(tmp: Path, script: Path) -> None:
    w = World(tmp)
    runner = w.clone("runner")
    out = w.run(script, "tick", "--repo", str(runner), "--branch", "main", "--gate", _gate(tmp))
    expect(out.returncode == 0, f"a green main exits 0: {out.stdout}{out.stderr}")
    state = runner / ".git" / "clade-mainline"
    latest = json.loads((state / "latest.json").read_text())
    expect(latest.get("status") == "green" and latest.get("head") == w.base, f"latest.json is the green record: {latest}")
    expect(len((state / "history.jsonl").read_text().splitlines()) == 1, "one history line")
    w.commit({}, "chore: an empty commit, the same tree")
    w.git(w.work, "push", "-q", "origin", "main")
    out = w.run(script, "tick", "--repo", str(runner), "--branch", "main", "--gate", _gate(tmp))
    expect(out.returncode == 0 and "already tested" in out.stdout, f"the same tree is not run again: {out.stdout}")
    expect(_runs(tmp) == 1, f"the gate ran {_runs(tmp)} times for one tree")
    expect(len((state / "history.jsonl").read_text().splitlines()) == 1, "a skip writes no record")


def mainline_finds_the_culprit(tmp: Path, script: Path) -> None:
    w = World(tmp)
    runner = w.clone("runner")
    expect(_tick(w, script, runner, _gate(tmp)).returncode == 0, "the base is green")
    merges = [w.merge_pr(1, {"a.txt": "1\n"}), w.merge_pr(2, {"b.txt": "2\n"}),
              w.merge_pr(3, {"BROKEN": "x\n"}), w.merge_pr(4, {"c.txt": "4\n"})]
    blockers = w.root / "blockers.md"
    out = _tick(w, script, runner, _gate(tmp), "--blockers", str(blockers))
    expect(out.returncode == 1, f"a red main exits 1: {out.stdout}{out.stderr}")
    red = _red(w, merges[-1])
    culprit = (red.get("culprit") or {}).get("sha")
    expect(red.get("classification") == "culprit" and culprit == merges[2],
           f"the culprit is merge #3 {merges[2][:12]}, got {red.get('classification')} {culprit}")
    expect(len(red.get("probes") or []) == 2, f"4 merges take log2(4) = 2 probes, took {len(red.get('probes') or [])}")
    expect(_runs(tmp) == 5, f"base + head + rerun + 2 probes = 5 gate runs, got {_runs(tmp)}")
    expect(_history(w)[-1].get("status") == "red", "the red record is in history")
    expect(blockers.exists() and merges[2][:12] in blockers.read_text(), "the blockers line names the culprit")


def mainline_bounds_the_probes(tmp: Path, script: Path) -> None:
    w = World(tmp)
    runner = w.clone("runner")
    expect(_tick(w, script, runner, _gate(tmp)).returncode == 0, "the base is green")
    for n, files in enumerate(({"a.txt": "1\n"}, {"b.txt": "2\n"}, {"BROKEN": "x\n"}, {"c.txt": "4\n"}), 1):
        head = w.merge_pr(n, files)
    out = _tick(w, script, runner, _gate(tmp), "--max-probes", "1")
    expect(out.returncode == 1, f"still red: {out.stdout}")
    red = _red(w, head)
    expect(red.get("classification") == "unbisected" and "budget" in str(red.get("reason")),
           f"a spent budget is unbisected, not a guess: {red.get('classification')} {red.get('reason')}")
    expect(len(red.get("probes") or []) == 1, f"--max-probes 1 ran {len(red.get('probes') or [])} probes")


def mainline_flaky_is_not_bisected(tmp: Path, script: Path) -> None:
    w = World(tmp)
    runner = w.clone("runner")
    flag = tmp / "fail-once"
    expect(_tick(w, script, runner, _gate(tmp, flag)).returncode == 0, "the base is green")
    head = w.merge_pr(1, {"a.txt": "1\n"})
    flag.write_text("x")
    out = _tick(w, script, runner, _gate(tmp, flag))
    expect(out.returncode == 3, f"red then green on the rerun exits 3: {out.returncode} {out.stdout}")
    expect(_history(w)[-1].get("status") == "flaky", f"recorded flaky: {_history(w)[-1]}")
    expect(not (w.root / "state" / "red" / f"{head[:8]}.json").exists(), "a flake is never bisected")


def mainline_nothing_ran_is_red(tmp: Path, script: Path) -> None:
    w = World(tmp)
    runner = w.clone("runner")
    out = _tick(w, script, runner, "echo '{\"verdict\": \"none\", \"passed\": []}'")
    expect(out.returncode == 1, f"a ci-local 'none' verdict with exit 0 is red: {out.returncode} {out.stdout}")
    red = _red(w, w.base)
    expect(red.get("classification") == "unbisected" and "no green" in str(red.get("reason")),
           f"no green record: {red.get('reason')}")


def mainline_rewritten_history_is_unbisected(tmp: Path, script: Path) -> None:
    w = World(tmp)
    runner = w.clone("runner")
    expect(_tick(w, script, runner, _gate(tmp)).returncode == 0, "the base is green")
    w.git(w.work, "checkout", "-q", "--orphan", "rewritten")
    w.commit({"d.txt": "new root\n"}, "chore: a new root")
    w.commit({"BROKEN": "x\n"}, "feat: broken")
    head = w.commit({"e.txt": "e\n"}, "feat: more")
    w.git(w.work, "push", "-q", "--force", "origin", "rewritten:main")
    out = _tick(w, script, runner, _gate(tmp))
    expect(out.returncode == 1, f"red: {out.stdout}{out.stderr}")
    red = _red(w, head)
    expect(red.get("classification") == "unbisected" and "not an ancestor" in str(red.get("reason")),
           f"a last green off the new history is no bisect base: {red.get('classification')} {red.get('reason')}")


def mainline_lock_held_exits_75(tmp: Path, script: Path) -> None:
    w = World(tmp)
    runner = w.clone("runner")
    state = w.root / "state"
    state.mkdir()
    with (state / "lock").open("a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        out = _tick(w, script, runner, _gate(tmp))
    expect(out.returncode == 75, f"a held lock exits 75: {out.returncode} {out.stdout}{out.stderr}")
    expect(_runs(tmp) == 0, "and runs nothing")


def _stamp(hours_ago: float) -> str:
    when = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_ago)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def mainline_status_falls_back(tmp: Path, script: Path) -> None:
    w = World(tmp)
    runner = w.clone("runner")
    state = w.root / "state"
    state.mkdir()
    rows = [{"head": "a" * 40, "tree": "1", "status": "green", "ended": _stamp(30)},
            {"head": "b" * 40, "tree": "2", "status": "green", "ended": _stamp(2)},
            {"head": "c" * 40, "tree": "3", "status": "red", "ended": _stamp(0.1)}]
    (state / "history.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    base = ("status", "--repo", str(runner), "--state-dir", str(state))
    out = w.run(script, *base, "--json")
    report = json.loads(out.stdout)
    expect(out.returncode == 0 and report["fresh"] and report["fell_back"],
           f"a red latest falls back to the green 2 h ago: {out.returncode} {report}")
    expect((report.get("green") or {}).get("head") == "b" * 40, f"the newest green, not the oldest: {report}")
    out = w.run(script, *base, "--fresh-hours", "1")
    expect(out.returncode == 1 and "STALE" in out.stdout, f"a green 2 h old is stale in a 1 h window: {out.stdout}")
    (state / "history.jsonl").write_text(json.dumps(rows[2]) + "\n")
    out = w.run(script, *base)
    expect(out.returncode == 1, f"no green record at all is stale: {out.stdout}")


MAINLINE_CASES: list[tuple[str, Case]] = [
    ("records green, then skips the same tree", mainline_green_then_skip),
    ("finds the culprit among 4 merges in 2 probes", mainline_finds_the_culprit),
    ("--max-probes bounds the bisect", mainline_bounds_the_probes),
    ("a flaky red is not bisected", mainline_flaky_is_not_bisected),
    ("nothing ran is red", mainline_nothing_ran_is_red),
    ("rewritten history is unbisected", mainline_rewritten_history_is_unbisected),
    ("a held lock exits 75", mainline_lock_held_exits_75),
    ("status falls back through history", mainline_status_falls_back),
]
