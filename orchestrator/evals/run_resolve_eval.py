#!/usr/bin/env python3
"""Resolve-rate eval harness — runs SWE-bench-Lite-style instances through
Clade's solve → apply → test → score pipeline and reports a real resolve-rate
+ cost.

Why: Clade's quality story has always been *oracle-approved* success, never an
end-to-end *resolve-rate* (does the produced patch make the project's
FAIL_TO_PASS tests pass without breaking PASS_TO_PASS?). Peer agents publish
this number — Sonar 79.2 % @ $1.90, Moatless 39 % @ $0.14 on SWE-bench-Lite —
and Clade skipped the measurement. This harness closes that gap with the SAME
scoring contract SWE-bench uses, so a Clade number is directly comparable.

Structure mirrors ``run_oracle_eval.py``: JSONL/fixture loader + schema gate,
an injectable runner, ``summarize()`` + a scoreboard, and a threshold gate with
the same exit-code style (0 = at/above threshold, 1 = below, 2 = bad fixtures).

Modes
-----
  --dry-run    FULL pipeline against 1-2 BUNDLED synthetic instances whose
               ``solve_fn`` is a canned patch and whose ``test_cmd`` is a
               trivial local pytest. NO network, NO Docker, NO claude CLI.
               Proves the scoring pipeline works; this is what CI/tests run.

  (default)    Real instances. Each instance needs a checked-out repo at
               ``base_commit`` and a working ``test_cmd`` environment, and the
               solver is Clade's worker loop driving the real ``claude`` CLI.
               Both are per-instance setup the caller plugs in — see
               ``solve_with_worker`` and ``materialize_repo`` for the seams,
               and ``load_swebench_lite`` for fetching the real dataset.

Real SWE-bench execution (Docker per-instance test envs) is OUT OF SCOPE: this
harness scores whatever ``test_cmd`` you point it at in whatever environment
you materialize. The Docker harness is the plug-in boundary, not bundled here.

Instance schema (SWE-bench-Lite shape), one JSON file per case in
``resolve_cases/`` (``instance_id`` == filename stem):

  instance_id        unique id (== filename stem)
  repo               "owner/name" the instance came from
  base_commit        sha the patch applies on top of
  problem_statement  the issue text → becomes the task description
  FAIL_TO_PASS       [pytest node ids] that must PASS after the patch
  PASS_TO_PASS       [pytest node ids] that must STAY passing after the patch
  test_cmd           shell command that runs the suite (pytest -v style)
  synthetic          {repo_files, canned_patch} — present ONLY on bundled
                     offline cases; real instances omit it (repo is checked
                     out by ``materialize_repo`` instead).

Exit codes: 0 = resolve-rate at/above threshold, 1 = below threshold,
2 = fixtures invalid / unusable.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Awaitable, Callable

EVALS_DIR = Path(__file__).resolve().parent
RESOLVE_CASES_DIR = EVALS_DIR / "resolve_cases"

logger = logging.getLogger("resolve_eval")

REQUIRED_FIELDS = {
    "instance_id", "repo", "base_commit", "problem_statement",
    "FAIL_TO_PASS", "PASS_TO_PASS", "test_cmd",
}

# Peer numbers on SWE-bench-Lite for the comparison line (source: public
# leaderboard snapshots cited in the task). Pure context — not a gate.
PEERS = [("Sonar", 79.2, 1.90), ("Moatless", 39.0, 0.14)]

# Default resolve-rate gate. With the 2 bundled synthetic cases the harness
# self-tests at 50 % (1 resolved, 1 unresolved), so the dry-run uses its own
# lower gate (see DRY_RUN_THRESHOLD). Ratchet this up as real numbers come in.
DEFAULT_THRESHOLD = 0.40
DRY_RUN_THRESHOLD = 0.0  # dry-run proves the pipeline, not a quality bar

# A solver maps (instance, repo_dir) -> a unified-diff patch string ("" = no
# patch produced). Injectable so the whole pipeline is testable offline.
SolveFn = Callable[[dict, Path], Awaitable[str]]


# ─── Instance loading & schema validation ────────────────────────────────────


def validate_instance(inst: dict, source_name: str = "?") -> list[str]:
    """Return a list of schema errors for one instance (empty = valid)."""
    errors: list[str] = []
    if not isinstance(inst, dict):
        return [f"{source_name}: instance is not a JSON object"]
    iid = inst.get("instance_id", source_name)
    missing = REQUIRED_FIELDS - set(inst)
    if missing:
        errors.append(f"{iid}: missing required fields: {sorted(missing)}")
    for field in ("instance_id", "repo", "base_commit", "problem_statement", "test_cmd"):
        if field in inst and (not isinstance(inst[field], str) or not inst[field].strip()):
            errors.append(f"{iid}: {field} must be a non-empty string")
    for field in ("FAIL_TO_PASS", "PASS_TO_PASS"):
        v = inst.get(field)
        if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
            errors.append(f"{iid}: {field} must be a list of non-empty strings")
    if isinstance(inst.get("FAIL_TO_PASS"), list) and not inst["FAIL_TO_PASS"]:
        errors.append(f"{iid}: FAIL_TO_PASS must be non-empty (nothing to resolve otherwise)")
    syn = inst.get("synthetic")
    if syn is not None:
        if not isinstance(syn, dict):
            errors.append(f"{iid}: synthetic must be an object")
        else:
            rf = syn.get("repo_files")
            if not isinstance(rf, dict) or not rf or not all(
                isinstance(k, str) and isinstance(val, str) for k, val in rf.items()
            ):
                errors.append(f"{iid}: synthetic.repo_files must be a non-empty path->content map")
            if not isinstance(syn.get("canned_patch"), str):
                errors.append(f"{iid}: synthetic.canned_patch must be a string")
    return errors


def load_instances(path: Path = RESOLVE_CASES_DIR) -> tuple[list[dict], list[str]]:
    """Load instances from a directory of ``*.json`` files OR a single
    ``.jsonl`` file (one instance per line). Returns (instances, errors)."""
    instances: list[dict] = []
    errors: list[str] = []
    raw: list[tuple[str, dict]] = []  # (source_name, instance)

    if path.is_file() and path.suffix == ".jsonl":
        for i, line in enumerate(path.read_text().splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                raw.append((f"{path.name}:{i}", json.loads(line)))
            except json.JSONDecodeError as e:
                errors.append(f"{path.name}:{i}: unreadable JSON ({e})")
    elif path.is_dir():
        paths = sorted(path.glob("*.json"))
        if not paths:
            return [], [f"no instances found in {path}"]
        for p in paths:
            try:
                raw.append((p.name, json.loads(p.read_text())))
            except (json.JSONDecodeError, OSError) as e:
                errors.append(f"{p.name}: unreadable JSON ({e})")
    else:
        return [], [f"dataset path not found: {path}"]

    seen: set[str] = set()
    for source_name, inst in raw:
        errors.extend(validate_instance(inst, source_name))
        iid = inst.get("instance_id") if isinstance(inst, dict) else None
        if iid:
            # For the bundled .json directory, id must match filename stem
            # (same provenance contract as the oracle harness).
            if source_name.endswith(".json") and iid != Path(source_name).stem:
                errors.append(f"{source_name}: instance_id {iid!r} != filename stem")
            if iid in seen:
                errors.append(f"{source_name}: duplicate instance_id {iid!r}")
            seen.add(iid)
        if isinstance(inst, dict):
            instances.append(inst)
    return instances, errors


def load_swebench_lite(out_path: Path) -> None:  # pragma: no cover — never called in tests
    """STUB: fetch ``princeton-nlp/SWE-bench_Lite`` into a local JSONL.

    Deliberately NOT imported/called at module load or in tests — this harness
    is offline-safe by construction. To produce a real dataset file::

        pip install datasets            # HuggingFace datasets, NOT a repo dep
        python -c "from datasets import load_dataset; \\
            ds = load_dataset('princeton-nlp/SWE-bench_Lite', split='test'); \\
            import json; \\
            open('lite.jsonl','w').write('\\n'.join( \\
                json.dumps({ \\
                    'instance_id': r['instance_id'], 'repo': r['repo'], \\
                    'base_commit': r['base_commit'], \\
                    'problem_statement': r['problem_statement'], \\
                    'FAIL_TO_PASS': json.loads(r['FAIL_TO_PASS']), \\
                    'PASS_TO_PASS': json.loads(r['PASS_TO_PASS']), \\
                    'test_cmd': 'python -m pytest -p no:cacheprovider --no-header -q', \\
                }) for r in ds))"

    Then point the harness at it: ``--dataset lite.jsonl``. You STILL need a
    per-instance test environment (the repo checked out at ``base_commit`` with
    deps installed — that is what ``materialize_repo`` is the seam for, and what
    the SWE-bench Docker harness normally provides).
    """
    raise NotImplementedError(
        "load_swebench_lite is a documented fetch stub — run the snippet in its "
        "docstring to create a JSONL, then pass it via --dataset."
    )


# ─── Repo materialization (the per-instance environment seam) ────────────────


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd),
        capture_output=True, text=True, timeout=60,
        env={"GIT_TERMINAL_PROMPT": "0", "HOME": str(cwd),
             "GIT_AUTHOR_NAME": "eval", "GIT_AUTHOR_EMAIL": "eval@local",
             "GIT_COMMITTER_NAME": "eval", "GIT_COMMITTER_EMAIL": "eval@local"},
    )


def materialize_repo(inst: dict, work_dir: Path) -> Path:
    """Produce a working git repo for ``inst`` under ``work_dir`` and return it.

    Bundled synthetic instances carry their files inline (``synthetic.repo_files``)
    and are materialized fully offline — a fresh ``git init`` + commit so ``git
    apply`` and per-test scoring behave exactly as on a real checkout.

    REAL INSTANCES PLUG IN HERE: replace the ``else`` branch with a checkout of
    ``inst['repo']`` at ``inst['base_commit']`` and a dependency install (this is
    what the SWE-bench Docker harness does per instance). The rest of the
    pipeline — apply patch, run test_cmd, score F2P/P2P — is environment-agnostic.
    """
    repo_dir = work_dir / "repo"
    repo_dir.mkdir(parents=True, exist_ok=True)
    syn = inst.get("synthetic")
    if syn and isinstance(syn.get("repo_files"), dict):
        for rel, content in syn["repo_files"].items():
            fp = repo_dir / rel
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content)
        _git(["init", "-q"], repo_dir)
        _git(["add", "-A"], repo_dir)
        _git(["commit", "-q", "-m", "base"], repo_dir)
        return repo_dir
    raise NotImplementedError(
        f"{inst['instance_id']}: no bundled repo_files and real checkout not wired. "
        "Implement the real-instance branch of materialize_repo (clone "
        f"{inst['repo']} @ {inst['base_commit'][:12]} + install deps)."
    )


def apply_patch(patch: str, repo_dir: Path) -> tuple[bool, str]:
    """Apply a unified diff to the repo. Returns (applied, detail).

    Mirrors how a Clade worker's diff lands on a worktree: ``git apply``. Falls
    back to a 3-way apply (handles minor context drift), same as SWE-bench.
    """
    if not patch.strip():
        return False, "empty patch"
    (repo_dir / ".eval_patch.diff").write_text(patch)
    try:
        res = _git(["apply", "--whitespace=nowarn", ".eval_patch.diff"], repo_dir)
        if res.returncode != 0:
            res = _git(["apply", "--3way", "--whitespace=nowarn", ".eval_patch.diff"], repo_dir)
        ok = res.returncode == 0
        return ok, (res.stderr.strip()[:300] if not ok else "applied")
    finally:
        (repo_dir / ".eval_patch.diff").unlink(missing_ok=True)


# ─── Test execution + scoring (the resolve-rate contract) ────────────────────

_PYTEST_RESULT_RE = re.compile(r'^(.+?::[\w\[\]:./-]+)\s+(PASSED|FAILED|ERROR)', re.M)


def parse_pytest_results(output: str) -> dict[str, bool]:
    """Parse ``pytest -v`` output into {node_id: passed}. Same shape as
    worker_utils._parse_pytest_results, kept local so the harness has no
    import-time dependency on the worker module."""
    return {m.group(1).strip(): m.group(2) == "PASSED"
            for m in _PYTEST_RESULT_RE.finditer(output)}


def _force_verbose_pytest(cmd: str) -> str:
    """Normalize a pytest command so it emits ``node::id PASSED`` lines: strip
    quiet flags (``-q`` suppresses per-node lines even with ``-v``) and ensure
    ``-v`` is present. Non-pytest commands are returned unchanged."""
    if "pytest" not in cmd:
        return cmd
    cmd = re.sub(r'(?<!\S)(-q|--quiet|--no-header)(?=\s|$)', '', cmd)
    cmd = re.sub(r'\s{2,}', ' ', cmd).strip()
    if " -v" not in f" {cmd}":
        cmd = cmd.replace("pytest", "pytest -v", 1)
    return cmd


def run_tests(inst: dict, repo_dir: Path, timeout: int = 120) -> dict[str, bool]:
    """Run ``inst['test_cmd']`` in ``repo_dir`` (forced verbose so node-level
    results parse). Returns {node_id: passed}; {} if the suite can't run."""
    cmd = _force_verbose_pytest(inst["test_cmd"])
    try:
        proc = subprocess.run(
            cmd, cwd=str(repo_dir), shell=True,
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logger.warning("%s: test_cmd timed out after %ds", inst["instance_id"], timeout)
        return {}
    return parse_pytest_results(proc.stdout + proc.stderr)


def score_instance(inst: dict, results: dict[str, bool]) -> tuple[bool, str]:
    """Apply the SWE-bench resolve contract: every FAIL_TO_PASS must now PASS
    and every PASS_TO_PASS must STILL pass. Returns (resolved, detail)."""
    f2p_fail = [t for t in inst["FAIL_TO_PASS"] if not results.get(t, False)]
    p2p_fail = [t for t in inst["PASS_TO_PASS"] if not results.get(t, False)]
    if f2p_fail:
        return False, f"FAIL_TO_PASS still failing: {f2p_fail[:3]}"
    if p2p_fail:
        return False, f"PASS_TO_PASS regressed: {p2p_fail[:3]}"
    return True, "all F2P pass, no P2P regression"


# ─── Solvers ─────────────────────────────────────────────────────────────────


async def solve_canned(inst: dict, repo_dir: Path) -> str:
    """Offline solver: return the bundled canned patch. Drives --dry-run."""
    syn = inst.get("synthetic") or {}
    return syn.get("canned_patch", "")


async def solve_with_worker(inst: dict, repo_dir: Path) -> str:  # pragma: no cover — needs claude CLI
    """REAL solver: run ``inst['problem_statement']`` through Clade's worker
    loop and return the diff it produced.

    The plug-in path (left as a documented seam — needs the claude CLI + an
    initialized orchestrator, neither available offline):

      1. Write ``.claude/orchestrator.json`` with ``test_cmd`` into ``repo_dir``
         so worker_utils._run_project_tests / _capture_test_baseline pick it up.
      2. ``task = await TaskQueue(repo_dir/'.claude').add(problem_statement, model=...)``
      3. Spawn a ``worker.Worker`` over ``repo_dir`` (it calls _setup_worktree,
         runs ``claude -p``, then verify_and_commit). See worker.py.
      4. Read the produced diff: ``git -C <worktree> diff <base_commit>``.

    Until wired, fail loudly so a 0 % "resolve-rate" is never silently a
    misconfiguration. The full run needs the claude CLI + per-instance env.
    """
    raise NotImplementedError(
        "solve_with_worker is the real-solver seam — wire it to worker.Worker "
        "(needs claude CLI + an initialized orchestrator). Use --dry-run for the "
        "offline pipeline check."
    )


# ─── Runner ──────────────────────────────────────────────────────────────────


async def run_instance(inst: dict, solve_fn: SolveFn) -> dict:
    """Full pipeline for one instance: materialize → solve → apply → test →
    score. Captures wall-time. Never raises — failures become unresolved rows."""
    iid = inst["instance_id"]
    started = time.monotonic()
    row = {"instance_id": iid, "resolved": False, "detail": "", "patched": False,
           "elapsed_s": 0.0}
    with tempfile.TemporaryDirectory(prefix=f"resolve-{iid}-") as tmp:
        work = Path(tmp)
        try:
            repo_dir = materialize_repo(inst, work)
            patch = await solve_fn(inst, repo_dir)
            if not patch.strip():
                row["detail"] = "solver produced no patch"
            else:
                applied, detail = apply_patch(patch, repo_dir)
                row["patched"] = applied
                if not applied:
                    row["detail"] = f"patch did not apply: {detail}"
                else:
                    results = run_tests(inst, repo_dir)
                    if not results:
                        row["detail"] = "test_cmd produced no parseable results"
                    else:
                        resolved, detail = score_instance(inst, results)
                        row["resolved"] = resolved
                        row["detail"] = detail
        except NotImplementedError as e:
            row["detail"] = f"setup not wired: {e}"
        except Exception as e:  # pragma: no cover — defensive
            logger.warning("%s: pipeline error: %s", iid, e)
            row["detail"] = f"pipeline error: {type(e).__name__}"
    row["elapsed_s"] = round(time.monotonic() - started, 2)
    return row


async def run_all(instances: list[dict], solve_fn: SolveFn,
                  cost_fn: Callable[[dict], float] | None = None) -> list[dict]:
    """Run every instance sequentially (real solves are expensive + serialize on
    the claude CLI). Attaches a per-instance cost estimate if ``cost_fn`` given."""
    rows: list[dict] = []
    for inst in instances:
        row = await run_instance(inst, solve_fn)
        row["cost"] = round(cost_fn(inst), 4) if cost_fn else 0.0
        rows.append(row)
    return rows


# ─── Summary + scoreboard ────────────────────────────────────────────────────


def summarize(rows: list[dict], threshold: float) -> dict:
    """Compute resolve-rate + cost aggregates. Returns a summary dict.

    rate = resolved / total; ok = rate >= threshold (>= so a 0.0 gate always
    passes the dry-run, matching run_oracle_eval's >= semantics)."""
    total = len(rows)
    resolved = sum(1 for r in rows if r["resolved"])
    rate = resolved / total if total else 0.0
    total_cost = round(sum(r.get("cost", 0.0) for r in rows), 4)
    return {
        "total": total,
        "resolved": resolved,
        "rate": rate,
        "total_cost": total_cost,
        "avg_cost": round(total_cost / total, 4) if total else 0.0,
        "ok": total > 0 and rate >= threshold,
    }


def print_scoreboard(rows: list[dict], summary: dict, threshold: float,
                     elapsed: float) -> None:
    print(f"\n{'instance':<32} {'resolved':<9} {'cost':>8} {'time':>7}  detail")
    print("-" * 92)
    for r in rows:
        mark = "RESOLVED " if r["resolved"] else "unresolved"
        print(f"{r['instance_id']:<32} {mark:<9} "
              f"${r.get('cost', 0.0):>7.4f} {r['elapsed_s']:>6.1f}s  {r['detail'][:34]}")
    print("-" * 92)
    pct = summary["rate"] * 100
    print(f"resolve-rate: {summary['resolved']}/{summary['total']} = {pct:.1f}% "
          f"(threshold {threshold * 100:.0f}%) — "
          f"${summary['total_cost']:.4f} total (${summary['avg_cost']:.4f}/inst), "
          f"{elapsed:.1f}s wall")
    peer_str = ", ".join(f"{n} {r:.1f}% @ ${c:.2f}" for n, r, c in PEERS)
    print(f"peers (SWE-bench-Lite): {peer_str}")
    if not summary["ok"]:
        print("BELOW THRESHOLD — resolve-rate regressed (or threshold too high for "
              "this instance set; ratchet with care).")


# ─── CLI ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="full pipeline on bundled synthetic cases with the "
                             "canned solver — no network/Docker/claude CLI")
    parser.add_argument("--dataset", default=str(RESOLVE_CASES_DIR),
                        help="instances: a dir of *.json or a single *.jsonl "
                             f"(default: {RESOLVE_CASES_DIR})")
    parser.add_argument("--threshold", type=float, default=None,
                        help=f"resolve-rate gate (default {DEFAULT_THRESHOLD}; "
                             f"{DRY_RUN_THRESHOLD} in --dry-run)")
    parser.add_argument("--instances", default="",
                        help="only run instances whose id contains this substring")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    dataset = Path(args.dataset)
    instances, errors = load_instances(dataset)
    if errors:
        print(f"INSTANCE SCHEMA ERRORS ({len(errors)}):")
        for e in errors:
            print(f"  - {e}")
        return 2
    if args.instances:
        instances = [i for i in instances if args.instances in i["instance_id"]]
        if not instances:
            print(f"no instances match filter {args.instances!r}")
            return 2

    if args.dry_run:
        solve_fn: SolveFn = solve_canned
        threshold = DRY_RUN_THRESHOLD if args.threshold is None else args.threshold
        instances = [i for i in instances if i.get("synthetic")]
        if not instances:
            print("--dry-run needs bundled synthetic instances (none found)")
            return 2
        print(f"DRY-RUN: {len(instances)} bundled synthetic instance(s), "
              "canned solver, local pytest — no network/Docker/claude CLI")
    else:
        solve_fn = solve_with_worker
        threshold = DEFAULT_THRESHOLD if args.threshold is None else args.threshold
        logger.info("REAL run: each instance needs the claude CLI + a per-instance "
                    "test environment (repo @ base_commit). See materialize_repo / "
                    "solve_with_worker. Use --dry-run for the offline pipeline check.")
        print(f"loaded {len(instances)} instance(s) from {dataset}")

    started = time.monotonic()
    rows = asyncio.run(run_all(instances, solve_fn))
    elapsed = time.monotonic() - started
    summary = summarize(rows, threshold)
    print_scoreboard(rows, summary, threshold, elapsed)
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
