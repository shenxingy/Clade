# Prompt Eval Harness

Regression tests for the LLM prompts that gate autonomous work: the **oracle
review** (`worker_review.py:_oracle_review`) and the **loop supervisor**
output contract (`configs/scripts/loop-runner.sh:node_supervisor`).

Clade's stated quality metric is *90%+ oracle-approved success* — but before
this harness, an oracle prompt edit could not be shown to move that number
prior to deployment. Now: edit a prompt, replay 20 recorded fixtures through
the **live** code path, read the pass-rate delta.

> **Supersedes the wave-1 "oracle canary" idea** (BRAINSTORM.md: *"Optional
> known-bad-fixture canary at session start"*, skipped in wave 1). Instead of
> a per-session canary, known-good/known-bad fixtures live here and replay on
> demand or on a schedule — same liveness signal, no per-session API cost.

## Layout

```
evals/
├── run_oracle_eval.py     # replays oracle_cases/ through the LIVE _oracle_review
├── supervisor_eval.py     # offline structural eval of the LIVE node_supervisor parser
├── oracle_cases/          # 20 fixtures: task + diff + expected verdict + rationale
└── supervisor_cases/      # 7 fixtures: recorded supervisor replies + structural expectations
```

## Running

```bash
cd orchestrator

# Offline — no API calls. Fixture schema, prompt construction (criteria /
# test-evidence / fix-intent threading, placeholder rendering), and the 3
# infra-error simulations replayed through the real _oracle_review with a
# stubbed subprocess layer. Safe anywhere, runs in <2s.
python3 evals/run_oracle_eval.py --offline
python3 evals/supervisor_eval.py            # offline by nature

# Live — real `claude -p` (haiku) calls through the exact worker code path.
# Manual or scheduled ONLY (see cost policy). Exits 1 below threshold.
python3 evals/run_oracle_eval.py                      # full run, threshold 0.75
python3 evals/run_oracle_eval.py --cases reject-      # substring filter
python3 evals/run_oracle_eval.py --threshold 0.85 --concurrency 8
python3 evals/run_oracle_eval.py --model claude-haiku-4-5   # pin a snapshot
```

pytest (`tests/test_evals.py`) runs **only the offline layer** — live API
replays are never part of CI or the default test suite.

**Run the live eval before merging any change to** `_ORACLE_PROMPT_TEMPLATE`,
`_ORACLE_SPEC_PROMPT`, `_ORACLE_QUALITY_PROMPT`, `_FIX_INTENT_CRITERION`,
`_build_oracle_task_block`, the severity gate, or the confidence gate.

## Cost policy

- One full live run ≈ **31 haiku calls** (14 short-path cases × 2 passes +
  3 chunked cases × ~2.7 chunks; quality pass skipped after a spec rejection,
  so real runs come in at or under this). Infra-simulation cases never call
  the API. The runner prints the exact call count per run.
- Live runs are **manual or scheduled** (e.g. a weekly cron or a `/loop` goal
  before a prompt-change merge) — **never per-push CI**.
- Grader model is haiku (`worker_review.HAIKU_MODEL`), same tier production
  uses; `--model` pins a dated snapshot when comparing across model bumps.

**Safety**: the grader runs `claude -p --dangerously-skip-permissions`, which
is fully agentic — on the first live run (2026-06-12) graders treated fixture
tasks as work orders: one implemented a fixture's stub function in the repo,
others invented hooks/tests, committed, and pushed (4 commits reverted).
`worker_review.py` now pins the grader subprocess cwd to the `.claude`
scratch dir (eval runs use a per-case tempdir), so stray tool use cannot
reach the project repo. If you see fixture-flavored commits appear during a
live run, a containment regression has occurred — check `git log` first.

## Thresholds

Default pass-rate gate: **0.75** (15/20). Haiku grading is stochastic; the
margin absorbs known-tension cases (below) without letting a real prompt
regression through. **Ratchet the threshold up** as prompts improve; never
lower it without documenting which fixture became a known-miss and why.

Known-tension fixtures (expected to be the first to flip on noisy runs):

- `approve-real-fix-with-test-chunked` — the covering test lives in chunk 2;
  a per-chunk grader reviewing chunk 1 can't see it. Measures per-chunk
  blindness on fix-intent tasks.
- `reject-real-fix-without-test` — chunked path; rejection requires the model
  to mark the missing-test completeness violation as severity `error`.

## Oracle fixture schema

One JSON file per case in `oracle_cases/`, `id` == filename stem:

| field | req | meaning |
|---|---|---|
| `id`, `category`, `source`, `rationale` | yes | provenance + why this case exists. `source`: `constructed` or `git:<sha>` |
| `task` | yes | task description as the worker saw it (may embed a ```json schema block) |
| `diff` | yes | unified diff, exactly what `git diff HEAD~1 HEAD` feeds the gate |
| `expected_verdict` | yes | `approved` \| `rejected` \| `unreviewed` |
| `acceptance_criteria` | no | list threaded via `_build_oracle_task_block` |
| `test_evidence` | no | `{tests_passed, test_output, reg_warning}` → `_build_test_evidence` |
| `simulate` | infra only | `timeout` \| `garbage_output` \| `empty_output`; requires `expected_verdict: unreviewed` |

Categories (each must keep ≥1 fixture — enforced by `tests/test_evals.py`):
`clear-approve`, `style-nit-no-reject` (severity/confidence gates),
`reject-spec-violation`, `reject-missing-test-on-fix` (fix-intent criterion),
`reject-quality`, `infra-error` (liveness: fail-open must surface as
`unreviewed`, never `approved`).

## Curating new fixtures from production history

Mine real false-approves/false-rejects rather than inventing them:

1. **Tasks DB** — `~/.claude/orchestrator/tasks.db` keeps `oracle_result` /
   `oracle_reason` per task. Query for `rejected` rows that were later merged
   unchanged (false-reject) or `approved` rows that got reverted
   (false-approve): `git log --grep="revert" --oneline` cross-referenced with
   task branch names.
2. **Event stream** — `event_stream.py` JSONL logs carry the full
   task-description + verdict timeline per session.
3. Reconstruct the diff (`git show --format= <sha>`), set `source: git:<sha>`,
   write the contract-correct verdict (not necessarily what the oracle said
   at the time), and explain the discrepancy in `rationale`.

## Supervisor cases

`supervisor_eval.py` extracts the JSON-extraction snippet embedded in
`node_supervisor()` from the **current** `loop-runner.sh` (extraction failure
= loud error, never a stale copy) and replays recorded supervisor replies
through it, then asserts structure: non-empty descriptions, valid model tier
(`haiku|sonnet|opus`), non-empty `files`, and cross-task file independence.

Two fixtures intentionally pin **known parser weaknesses** (single-object
reply leaks its `files` array as a bogus task; brackets in prose break array
extraction and drop a valid plan). If you improve the parser, those fixtures
fail until updated — parser behavior changes must be visible diffs.
