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
| single-shot | psf/requests ×6 | **1/6** | one sonnet pass + TLDR context |
| oracle-loop | psf/requests ×6 | **1/6** | + oracle gate + reflection (N=3) |

**Key finding:** on this subset the oracle loop did **not** beat single-shot. Per-instance
analysis showed why: the oracle (a model reviewing the diff) **approved wrong patches**
(model judgment ≠ ground truth), and on `requests-1963` reflection **over-edited**
(3 iterations → 7 files / 6 KB, still wrong). **Without a real test signal, oracle + iteration
≈ single-shot.** SWE-bench's real lever is **test-driven** iteration (run the failing
test → fix to green) — which Clade has (repro filter + test gate + requeue) but which the
`requests` subset can't measure faithfully (its tests hit the network → flaky feedback).

## Honest scope

`1/6` is **not** "Clade = 16%". It's a tiny (N=6), hard, old (2014-era requests), unrepresentative
slice, run with Clade's strongest lever (test-driven iteration) **off**. A fair number needs
the `testdriven` mode on a non-network repo (pytest/sympy) over a representative sample. The
value here is the **working, standard, reproducible measurement pipeline** + the finding that
oracle-without-tests is not the lever.
