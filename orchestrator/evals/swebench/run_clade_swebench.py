#!/usr/bin/env python3
"""Real SWE-bench harness for Clade — generate patches, then evaluate with the
official `swebench` Docker harness (the standard, leaderboard-comparable yardstick
the experts report: Sonar 79.2%, Moatless 39%).

This is the patch GENERATOR (the `solve_with_worker` seam run_resolve_eval stubbed).
Evaluation is the official CLI:

    pip install swebench datasets
    python evals/swebench/run_clade_swebench.py --repo psf/requests --mode oracle
    python -m swebench.harness.run_evaluation \\
        -d princeton-nlp/SWE-bench_Lite -s test -p /tmp/clade_preds.jsonl -id clade-run \\
        -i <instance_ids...>

Modes (increasing fidelity to Clade's real loop):
  single     — one `claude -p` pass with TLDR/PageRank-localized context (baseline).
  oracle     — + Clade's `_oracle_review` gate + reflection retry on reject (no test signal).
  testdriven — + in-env test feedback: a container (mounted host source over /testbed)
               runs an existing-test regression gate per iteration (the real loop;
               use only on non-network repos — requests tests hit the network).

Measured (2026-06-19, psf/requests Lite subset, N=6): single 1/6, oracle 1/6 — oracle
WITHOUT a real test signal ≈ single-shot (the gate approves wrong patches; reflection can
over-edit). See evals/swebench/README.md.
"""
from __future__ import annotations
import argparse, asyncio, json, subprocess, sys, time, shlex
from pathlib import Path

_ORCH = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ORCH))
import worker_tldr as wt          # noqa: E402
import worker_review as wr        # noqa: E402

SRC_ONLY = "':(exclude)*test*' ':(exclude)tests' ':(exclude).claude' ':(exclude).clade-task.md'"
REPO_URL = {
    "psf/requests": "https://github.com/psf/requests",
    "pytest-dev/pytest": "https://github.com/pytest-dev/pytest",
    "sphinx-doc/sphinx": "https://github.com/sphinx-doc/sphinx",
}


def sh(cmd, cwd, timeout=120):
    return subprocess.run(cmd, shell=True, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)


def _claude(repo_dir: Path, prompt_or_continue: str, is_continue: bool) -> None:
    if is_continue:
        cmd = f'claude -p --continue {shlex.quote(prompt_or_continue)} --model sonnet --dangerously-skip-permissions'
    else:
        (repo_dir / ".clade-task.md").write_text(prompt_or_continue)
        cmd = (f'claude -p "$(cat {shlex.quote(str(repo_dir/".clade-task.md"))})" '
               f'--model sonnet --dangerously-skip-permissions')
    try:
        subprocess.run(cmd, shell=True, cwd=str(repo_dir), capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        pass


async def _build_task(inst: dict, repo_dir: Path) -> str:
    tldr = wt._generate_code_tldr(str(repo_dir))
    try:
        local = await wt._localize_tldr_for_task(inst["problem_statement"], tldr, repo_dir)
    except Exception:
        local = tldr
    return (f"{inst['problem_statement'][:4000]}\n\n---\n## Code map\n{local[:10000]}\n\n---\n"
            "Fix the bug by editing SOURCE files only (never tests). Make a minimal, correct change.")


async def solve(inst: dict, repo_dir: Path, mode: str, max_iter: int) -> dict:
    iid, base = inst["instance_id"], inst["base_commit"]
    sh("git reset --hard -q && git clean -fdq", repo_dir)
    sh(f"git checkout -q {base}", repo_dir)
    claude_dir = repo_dir / ".claude"; claude_dir.mkdir(exist_ok=True)
    base_task = await _build_task(inst, repo_dir)
    t0, iters, verdict, reflection = time.time(), 0, "max_iter", ""

    for attempt in range(1, (1 if mode == "single" else max_iter) + 1):
        iters = attempt
        _claude(repo_dir, base_task if attempt == 1 else reflection, is_continue=(attempt > 1))
        diff = sh(f"git diff {base} -- . {SRC_ONLY}", repo_dir).stdout
        if mode == "single":
            verdict = "single"; break
        if not diff.strip():
            reflection = "You made NO source changes. Edit the source file(s) to fix the bug now."
            continue
        try:
            approved, reason, infra = await wr._oracle_review(inst["problem_statement"][:4000], diff, claude_dir)
        except Exception as e:
            approved, reason, infra = True, str(e), True
        print(f"  {iid} iter{attempt}: diff {len(diff)}c oracle={'OK' if approved else 'REJECT'}"
              f"{' (infra)' if infra else ''}", flush=True)
        if approved or infra:
            verdict = "approved" if approved else "oracle_infra"; break
        reflection = (f"An independent reviewer REJECTED your fix:\n{reason[:1500]}\n"
                      "Address this specifically. Edit only source files.")

    sh("rm -rf .clade-task.md .claude", repo_dir)
    diff = sh(f"git diff {base} -- . {SRC_ONLY}", repo_dir).stdout
    print(f"  {iid}: {iters} iters {time.time()-t0:.0f}s {verdict} diff {len(diff)}c", flush=True)
    return {"instance_id": iid, "model_name_or_path": f"clade-{mode}",
            "model_patch": diff, "_iters": iters, "_seconds": round(time.time() - t0), "_verdict": verdict}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="psf/requests")
    ap.add_argument("--mode", choices=["single", "oracle", "testdriven"], default="oracle")
    ap.add_argument("--max-iter", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0, help="cap instances (0=all in repo)")
    ap.add_argument("--out", default="/tmp/clade_preds.jsonl")
    ap.add_argument("--workdir", default="/tmp/swe-clade")
    args = ap.parse_args()
    if args.mode == "testdriven":
        print("testdriven mode: see run_clade_swebench_testdriven.py (in-env container loop)")
        return

    from datasets import load_dataset
    ds = load_dataset("princeton-nlp/SWE-bench_Lite", split="test")
    insts = [x for x in ds if x["repo"] == args.repo]
    if args.limit:
        insts = insts[:args.limit]
    wdir = Path(args.workdir); wdir.mkdir(exist_ok=True, parents=True)
    repo_dir = wdir / args.repo.replace("/", "__")
    if not repo_dir.exists():
        print(f"cloning {args.repo}…", flush=True)
        sh(f"git clone -q {REPO_URL[args.repo]} {repo_dir}", wdir, timeout=300)
    preds = [await solve(inst, repo_dir, args.mode, args.max_iter) for inst in insts]
    with open(args.out, "w") as f:
        for p in preds:
            f.write(json.dumps(p) + "\n")
    print(f"\nwrote {len(preds)} predictions ({sum(1 for p in preds if p['model_patch'].strip())} non-empty) → {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
