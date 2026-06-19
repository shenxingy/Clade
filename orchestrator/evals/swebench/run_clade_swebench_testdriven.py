#!/usr/bin/env python3
"""Test-driven loop (C2) on pytest (non-network). Clade's real loop levers:
  - repro filter: generate a failing test from the issue, run it IN THE ENV
    (docker exec); only accept once the model's own repro PASSES.
  - regression gate: a sample of existing PASS_TO_PASS tests must stay green.
  - oracle review + reflection retry.
Host source is mounted over /testbed so claude (host) edits run against the
instance's real Docker env.
"""
from __future__ import annotations
import asyncio, json, random, subprocess, sys, time, shlex
from pathlib import Path

sys.path.insert(0, "/home/alexshen/projects/clade/orchestrator")
import worker_tldr as wt          # noqa: E402
import worker_review as wr        # noqa: E402
from datasets import load_dataset  # noqa: E402

WORK = Path("/tmp/swe-td"); WORK.mkdir(exist_ok=True)
PRED = Path("/tmp/clade_td_preds.jsonl")
PY = "/opt/miniconda3/envs/testbed/bin/python"
# NOTE: never exclude '*test*' — it matches src/_pytest/ (the "test" substring)!
SRC_ONLY = ("':(exclude)tests' ':(exclude)testing' ':(glob,exclude)**/test_*.py' "
            "':(glob,exclude)**/*_test.py' ':(exclude)conftest.py' ':(exclude).claude' "
            "':(exclude).clade-task.md' ':(exclude)test_clade_repro.py'")
MAX_ITER = 3
N_INSTANCES = 6
REGRESSION_SAMPLE = 8

_REPRO_PROMPT = (
    "Write a SINGLE minimal pytest test function that reproduces the bug below: it must "
    "FAIL on the current (buggy) code and PASS once the bug is fixed. Use only stdlib + the "
    "project's own imports. 5-25 lines, start with imports then `def test_...():`. Output ONLY "
    "Python code, no markdown.\n\nBug:\n{problem}"
)


def sh(cmd, cwd=None, timeout=180):
    return subprocess.run(cmd, shell=True, cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True, timeout=timeout)


def dexec(cid, inner, timeout=300):
    p = sh(f'docker exec {cid} bash -lc {shlex.quote("cd /testbed && " + inner)}', timeout=timeout)
    return p.returncode, (p.stdout + p.stderr)


def sync(cid, repo: Path, base: str):
    """Make the container's /testbed mirror the host worktree's CURRENT state:
    reset tracked source to base, then copy the host's changed files in. Keeps the
    env's editable-install metadata intact (mounting breaks setuptools_scm) and is
    revert-safe. The repro test is untracked, so it's copied separately."""
    sh(f"docker exec {cid} bash -lc 'cd /testbed && git checkout -q -- . 2>/dev/null; rm -f test_clade_repro.py'")
    changed = sh(f"git diff --name-only {base}", repo).stdout.split()
    for f in changed:
        f = f.strip()
        if f:
            sh(f"docker cp {shlex.quote(str(repo / f))} {cid}:/testbed/{f}")
    rp = repo / "test_clade_repro.py"
    if rp.exists():
        sh(f"docker cp {shlex.quote(str(rp))} {cid}:/testbed/test_clade_repro.py")


async def _haiku(prompt: str, claude_dir: Path) -> str:
    f = claude_dir / "p.md"; f.write_text(prompt)
    p = sh(f'claude -p "$(cat {shlex.quote(str(f))})" --model haiku --dangerously-skip-permissions', timeout=180)
    return p.stdout


def _claude_edit(repo_dir, text, cont):
    if cont:
        cmd = f'claude -p --continue {shlex.quote(text)} --model sonnet --dangerously-skip-permissions'
    else:
        (repo_dir / ".clade-task.md").write_text(text)
        cmd = f'claude -p "$(cat {shlex.quote(str(repo_dir/".clade-task.md"))})" --model sonnet --dangerously-skip-permissions'
    try:
        subprocess.run(cmd, shell=True, cwd=str(repo_dir), capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        pass


async def solve(inst, repo_dir, cid) -> dict:
    iid, base = inst["instance_id"], inst["base_commit"]
    p2p = json.loads(inst["PASS_TO_PASS"])
    reg = random.Random(0).sample(p2p, min(REGRESSION_SAMPLE, len(p2p)))
    claude_dir = repo_dir / ".claude"; claude_dir.mkdir(exist_ok=True)

    # 1) generate a repro test, confirm it FAILS at base (captures the bug)
    repro_code = await _haiku(_REPRO_PROMPT.format(problem=inst["problem_statement"][:3500]), claude_dir)
    repro_code = repro_code.strip().removeprefix("```python").removeprefix("```").removesuffix("```").strip()
    repro_path = repro_dir = repo_dir / "test_clade_repro.py"
    repro_valid = False
    if "def test" in repro_code:
        repro_path.write_text(repro_code)
        sync(cid, repo_dir, base)
        rc, _ = dexec(cid, f"{PY} -m pytest test_clade_repro.py -q -p no:cacheprovider", timeout=180)
        repro_valid = rc != 0  # must fail at base
        if not repro_valid:
            repro_path.unlink(missing_ok=True)
            sh("docker exec {} bash -lc 'rm -f /testbed/test_clade_repro.py'".format(cid))

    tldr = wt._generate_code_tldr(str(repo_dir))
    try:
        local = await wt._localize_tldr_for_task(inst["problem_statement"], tldr, repo_dir)
    except Exception:
        local = tldr
    task = (f"{inst['problem_statement'][:4000]}\n\n---\n## Code map\n{local[:9000]}\n\n---\n"
            "Fix the bug by editing SOURCE files only (never tests). Minimal, correct change.")

    t0, iters, verdict, reflection = time.time(), 0, "max_iter", ""
    for attempt in range(1, MAX_ITER + 1):
        iters = attempt
        _claude_edit(repo_dir, task if attempt == 1 else reflection, cont=(attempt > 1))
        diff = sh(f"git diff {base} -- . {SRC_ONLY}", repo_dir).stdout
        if not diff.strip():
            reflection = "You made NO source changes. Edit the source to fix the bug now."
            continue
        sync(cid, repo_dir, base)  # push host edits into the container's env
        # repro signal (in-env)
        repro_ok = True; repro_out = ""
        if repro_valid:
            rc, repro_out = dexec(cid, f"{PY} -m pytest test_clade_repro.py -q -p no:cacheprovider", timeout=180)
            repro_ok = (rc == 0)
        # regression signal (in-env, sample of existing tests)
        rc2, reg_out = dexec(cid, f"{PY} -m pytest {' '.join(shlex.quote(t) for t in reg)} -q -p no:cacheprovider", timeout=300)
        reg_ok = (rc2 == 0)
        # oracle
        try:
            approved, reason, infra = await wr._oracle_review(inst["problem_statement"][:4000], diff, claude_dir)
        except Exception as e:
            approved, reason, infra = True, str(e), True
        print(f"  {iid} it{attempt}: diff{len(diff)} repro={'PASS' if repro_ok else 'FAIL'}"
              f"{'(n/a)' if not repro_valid else ''} reg={'OK' if reg_ok else 'BROKE'} "
              f"oracle={'OK' if approved else 'REJ'}", flush=True)
        if repro_ok and reg_ok and (approved or infra):
            verdict = "accepted"; break
        parts = []
        if not repro_ok:
            parts.append(f"Your own reproduction test still FAILS:\n{repro_out[-800:]}")
        if not reg_ok:
            parts.append(f"You BROKE existing tests (regression):\n{reg_out[-800:]}")
        if not approved and not infra:
            parts.append(f"Reviewer rejected: {reason[:800]}")
        reflection = "\n\n".join(parts) + "\nFix these. Edit source only."

    sh("rm -rf .clade-task.md .claude test_clade_repro.py", repo_dir)
    diff = sh(f"git diff {base} -- . {SRC_ONLY}", repo_dir).stdout
    print(f"  {iid}: {iters} iters {time.time()-t0:.0f}s {verdict} repro_valid={repro_valid} diff{len(diff)}", flush=True)
    return {"instance_id": iid, "model_name_or_path": "clade-testdriven", "model_patch": diff,
            "_iters": iters, "_seconds": round(time.time()-t0), "_verdict": verdict, "_repro_valid": repro_valid}


async def main():
    ds = load_dataset("princeton-nlp/SWE-bench_Lite", split="test")
    local = sh("docker images --format '{{.Repository}}'").stdout
    insts = [x for x in ds if x["repo"] == "pytest-dev/pytest"
             and f"pytest-{x['instance_id'].split('-')[-1]}" in local][:N_INSTANCES]
    print("instances:", [x["instance_id"] for x in insts], flush=True)
    repo = WORK / "pytest"
    if not repo.exists():
        sh(f"git clone -q https://github.com/pytest-dev/pytest {repo}", timeout=300)
    preds = []
    for inst in insts:
        sh("git reset --hard -q && git clean -fdq", repo); sh(f"git checkout -q {inst['base_commit']}", repo)
        img = f"swebench/sweb.eval.x86_64.pytest-dev_1776_{inst['instance_id'].replace('pytest-dev__','')}:latest"
        cid = sh(f"docker run -d {img} sleep infinity").stdout.strip()[:12]
        try:
            preds.append(await solve(inst, repo, cid))
        finally:
            sh(f"docker rm -f {cid}")
    with PRED.open("w") as f:
        for p in preds:
            f.write(json.dumps(p) + "\n")
    print(f"\nwrote {len(preds)} → {PRED} (repro_valid: {sum(p['_repro_valid'] for p in preds)}/{len(preds)})", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
