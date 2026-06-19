# Clade on SWE-bench — the standard, leaderboard-comparable measurement

SWE-bench (Princeton, `princeton-nlp/SWE-bench_Lite`, 300 instances) is **the** industry
benchmark for AI coding agents. Every number you've heard is this yardstick:
Sonar Foundation Agent **79.2%**, Moatless **39%**, Devin/closed systems ~70–80%.

## What it actually checks (objective, no model judging)

Each instance is a **real historical GitHub issue** from a popular Python project
(django, requests, sympy…). The agent is given:

- the repo at the commit **before** the fix,
- the issue text (`problem_statement`),
- **NOT** the solution, **NOT** the tests.

The agent must produce a **patch**. The harness then applies `[agent_patch + the
maintainer's real hidden test]` and runs it in the instance's exact env (Docker):

- **FAIL_TO_PASS** — tests that failed before must now pass (bug actually fixed),
- **PASS_TO_PASS** — tests that passed before must still pass (no regression).

`resolved` = the patch makes the hidden test pass without breaking anything. This is
why it's trustworthy where our own `_oracle_review` is not: **real tests on real bugs,
no model opinion** (the oracle can — and does — approve patches that fail the hidden test).

## How to run

```bash
pip install swebench datasets                      # Docker required for eval
# 1. generate Clade patches (this repo's generator)
python evals/swebench/run_clade_swebench.py --repo psf/requests --mode oracle
# 2. evaluate with the OFFICIAL harness (real Docker envs + hidden tests)
python -m swebench.harness.run_evaluation \
  -d princeton-nlp/SWE-bench_Lite -s test -p /tmp/clade_preds.jsonl \
  -id clade-run --cache_level env -i psf__requests-2317 ...
```

Generation modes (increasing fidelity to Clade's loop):
`single` (one pass + TLDR/PageRank context) · `oracle` (+ `_oracle_review` gate +
reflection retry) · `testdriven` (+ in-env test feedback; see the testdriven runner —
container mounts host source over `/testbed`, tests run via `docker exec` in the real env).

## Measured datapoints (2026-06-19)

First real, comparable numbers for Clade — **replacing reasoning with measurement.**

| run | subset | resolved | note |
|-----|--------|----------|------|
| single-shot | psf/requests ×6 | **1/6 (17%)** | one sonnet pass + TLDR context |
| oracle-loop | psf/requests ×6 | **1/6 (17%)** | + oracle gate + reflection (N=3) |
| **test-driven** | pytest ×5 | **2/5 (40%)** | + in-env repro + regression gate driving iteration |

(reference, full 300 + full loops: Moatless **39%**, Sonar **79.2%**.)

**Key findings:**
1. **Oracle-without-tests ≈ single-shot.** On requests the oracle loop didn't beat
   single-shot: the oracle (a model reviewing the diff) **approved wrong patches**
   (model judgment ≠ ground truth), and on `requests-1963` reflection **over-edited**
   (3 iters → 7 files, still wrong).
2. **Test-driven iteration is the lever.** On pytest, running a generated repro +
   regression sample **in the instance's real env** (via `docker cp` into the container)
   to drive iteration resolved **40%** — Moatless territory, and the first evidence the
   loop moves the needle. (Caveat: different subset from the requests runs, so not a
   perfectly controlled A/B; tiny N; 1 instance excluded for a capture bug.)

The test-driven runner mounts/cp's host edits into the instance's Docker env so the loop's
test feedback is real (`run_clade_swebench_testdriven.py`). NB: never exclude `*test*` from
the patch diff — it matches `src/_pytest/` (the "test" substring); use precise test-file
globs.

## Honest scope

`1/6` is **not** "Clade = 16%". It's a tiny (N=6), hard, old (2014-era requests), unrepresentative
slice, run with Clade's strongest lever (test-driven iteration) **off**. A fair number needs
the `testdriven` mode on a non-network repo (pytest/sympy) over a representative sample. The
value here is the **working, standard, reproducible measurement pipeline** + the finding that
oracle-without-tests is not the lever.
