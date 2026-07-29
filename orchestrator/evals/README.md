# Evaluation Harnesses

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
├── run_loop_eval.py       # offline: drives the LIVE oracle retry/convergence fns over verdict sequences
├── run_provider_conformance.py # sanitized runtime/connection/surface matrix + gated live catalog smoke
├── oracle_cases/          # 20 fixtures: task + diff + expected verdict + rationale
├── supervisor_cases/      # 7 fixtures: recorded supervisor replies + structural expectations
├── loop_cases/            # 7 fixtures: oracle-verdict SEQUENCES + expected fan-out/terminal (+ _baseline.json)
└── provider_cases/        # 6 secret-free runtime/provider/surface fixtures
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
python3 evals/run_loop_eval.py               # offline: oracle retry/convergence loop (fan-out + reject-cap)
python3 evals/run_provider_conformance.py    # offline: provider/runtime/surface contracts

# Live — real `claude -p` (haiku) calls through the exact worker code path.
# Manual or scheduled ONLY (see cost policy). Exits 1 below threshold.
python3 evals/run_oracle_eval.py                      # full run, threshold 0.75
python3 evals/run_oracle_eval.py --cases reject-      # substring filter
python3 evals/run_oracle_eval.py --threshold 0.85 --concurrency 8
python3 evals/run_oracle_eval.py --model claude-haiku-4-5   # pin a snapshot

# Read-only live model-catalog smoke. Each provider is separately credential
# gated; missing credentials print SKIP and exit 0. The output contains only a
# model count, catalog digest, and safe error category — never IDs/endpoints/keys.
python3 evals/run_provider_conformance.py --live anthropic
python3 evals/run_provider_conformance.py --live openai
```

pytest (`tests/test_evals.py`) runs **only the offline layer** — live API
replays are never part of CI or the default test suite.

### Provider conformance (`run_provider_conformance.py`)

The sanitized fixture matrix drives the real native-profile resolver, provider
registry, execution envelope, runtime command adapter, worker environment
binding, and canonical Claude/Codex/MCP/generic surface guidance. Fixtures may
contain opaque provider/model/profile identities, but schema validation rejects
URLs, machine paths, credential keys, and key material.

Normal PR/push CI runs only these deterministic fixtures. Manual/weekly live
jobs inject Anthropic and OpenAI credentials into separate jobs and perform one
read-only `/models` request. Catalog transport rejects non-HTTPS endpoints and
all redirects so an authorization header cannot be forwarded to another
origin.

### Loop-review eval (`run_loop_eval.py` + `loop_cases/`)

`oracle_cases/` grade a single *verdict*; `loop_cases/` grade the retry *loop*
around it — over a SEQUENCE of verdicts: does a rejection get one cheap
sequential retry vs. a diverse fan-out (plateau escape at reject-depth ≥ 1), and
does the reject-round cap escalate instead of requeuing forever? It drives the
live `worker_utils.oracle_reject_depth` + `oracle_retry_sample_count` (the
reject-cap gate is a documented **mirror** of the `worker.py` site — keep in
sync; see the SYNC comment). Pure/offline, < 1 s, wired into CI via
`tests/test_loop_eval.py`. `--json` emits per-attempt JSONL traces;
`--update-baseline` refreshes `loop_cases/_baseline.json` (a snapshot so any
behavior drift shows as a reviewable diff).

**Run it before merging any change to** `oracle_retry_sample_count`, the
reject-round-cap gate, `parallel_fix_samples`, or `oracle_max_reject_rounds`.

**Run the live eval before merging any change to** `_ORACLE_PROMPT_TEMPLATE`,
`_ORACLE_SPEC_PROMPT`, `_ORACLE_QUALITY_PROMPT`, `_FIX_INTENT_CRITERION`,
`_build_oracle_task_block`, the severity gate, or the confidence gate.

### Oracle calibration (`run_oracle_calibration.py`)

Pass rate treats false-approves and false-rejects equally; calibration makes the
dangerous side explicit. A **false-approve** is a predicted `approve` for a
fixture whose ground-truth label is `rejected`; its rate is calculated over all
ground-truth rejects. The harness also reports the confusion matrix, both
classes' precision/recall, false-reject rate, and a deterministic bootstrap CI.
`unreviewed` infra fixtures are excluded and named in the output.

```bash
# Offline by default: a small recorded sample, no API calls.
python3 evals/run_oracle_calibration.py

# Calibrate a recorded oracle run (JSONL: {"case": "fixture-id", "predicted": "approve|reject"}).
python3 evals/run_oracle_calibration.py --predictions predictions.jsonl --false-approve-ceiling 0.05 --json

# Live replay is manual/scheduled only under the same cost policy as the oracle eval.
python3 evals/run_oracle_calibration.py --live --false-approve-ceiling 0.05
```

The optional ceiling is an auto-merge gate: the command exits 1 when the
false-approve rate exceeds it. Default operation remains offline; never add
`--live` to per-push CI.

## Cost policy

- One full live run ≈ **31 haiku calls** (14 short-path cases × 2 passes +
  3 chunked cases × ~2.7 chunks; quality pass skipped after a spec rejection,
  so real runs come in at or under this). Infra-simulation cases never call
  the API. The runner prints the exact call count per run.
- Live runs are **manual or scheduled** (e.g. a weekly cron or a `/loop` goal
  before a prompt-change merge) — **never per-push CI**.
- Grader model is haiku (`worker_review.HAIKU_MODEL`), same tier production
  uses; `--model` pins a dated snapshot when comparing across model bumps.

**Safety / grader isolation** — the first live runs (2026-06-12) found three
ways a `claude -p` grader is NOT a judge by default; `worker_review.py` now
guards each, and `tests/test_oracle_integrity.py` pins the command contract:

1. **Agentic graders**: with `--dangerously-skip-permissions`, graders
   treated fixture tasks as work orders — one implemented a fixture's stub
   function in the repo, others invented hooks/tests, committed, and pushed
   (4 commits reverted). Fix: flag removed, cwd pinned to the `.claude`
   scratch dir (eval runs use a per-case tempdir).
2. **User hooks hijack output**: a prompt-type Stop hook's `{"ok":...}`
   decision got printed as the grader's reply, and user CLAUDE.md ground
   rules re-framed the grader as an autonomous worker. Fix:
   `--setting-sources ""` + an appended judge system prompt.
3. **Fenced JSON**: haiku wraps verdicts in ```` ```json ```` fences despite
   "no markdown" — strict `json.loads` read every healthy review as an infra
   error (oracle dead, fail-open `unreviewed` on all commits). Fix:
   `_strip_json_fence` before parsing.

If fixture-flavored commits appear during a live run, containment has
regressed — check `git log` first.

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

1. Runtime failure sources create sanitized `clade.eval_candidate/v1`
   quarantine rows pinned to an exact EvidenceBundle revision/digest. Raw hook
   JSONL is intentionally not an ingestion source because it lacks exact
   attempt identity.
2. List and inspect pending rows:

   ```bash
   python3 eval_review_cli.py --claude-dir /path/to/project/.claude list
   python3 eval_review_cli.py --claude-dir /path/to/project/.claude show <candidate-id>
   ```

3. A human reproduces the case and writes the target corpus label contract to
   a JSON file. Promotion requires reviewer identity, reason, corpus target,
   and that case file; rejection also requires reviewer and reason:

   ```bash
   python3 eval_review_cli.py --claude-dir /path/to/project/.claude \
     promote <candidate-id> --target oracle --reviewer alex \
     --reason "reproduced with parser fixture" --case-file /tmp/case.json
   python3 eval_review_cli.py --claude-dir /path/to/project/.claude \
     reject <candidate-id> --reviewer alex --reason "environment-only failure"
   ```

Promotion atomically creates a non-overwriting corpus file, then compare-and-
sets the candidate from `quarantined` to `promoted`. A DB failure removes a
newly created file; a conflicting case ID leaves the candidate quarantined.
Every fixture promoted this way has `source: eval:<candidate-id>` and a
`promotion_provenance` block containing the exact evidence digest, reviewer,
reason, trigger, diff digest, and redaction metadata. No code path assigns
ground truth automatically.

## Runtime quality metrics

`GET /api/eval-candidates/metrics?session=<session-id>` returns
`clade.eval_metrics/v1`. Every ratio exposes its numerator and denominator;
an empty denominator is `null`, never a misleading zero:

- evidence completeness = lifecycle-complete terminal bundles / terminal
  attempts;
- source integrity = candidates resolving to their exact evidence
  revision/digest / all candidates;
- confirmed false-approve rate = unique oracle-approved attempts whose
  human-promoted oracle label is `rejected` (or promoted resolve case) / all
  oracle-approved attempts;
- human override rate = promoted oracle fixtures whose human label disagrees
  with the observed approved/rejected verdict / comparable promotions;
- accepted regression coverage = promoted rows with a present corpus file
  whose provenance matches candidate ID and evidence digest / all promotions.

The React dashboard exposes the same snapshot under the **Evals** tab.

## Attempt routing telemetry

Every runtime attempt advances an immutable nested
`clade.attempt_telemetry/v1` snapshot inside its EvidenceBundle. The snapshot
keeps:

- atomic `attempt_index` and optional `parent_attempt_id` lineage;
- `queue_ms`, `inference_ms`, and `verify_ms`, plus their phase boundaries;
- resolved agent runtime, connection, model, effort, and audit reason;
- terminal lifecycle outcome, worker status, verification result, and final
  oracle verdict.

Unavailable phases are `null`; a preflight or spawn failure never fabricates
inference or verification time. Same-task retries link to the previous attempt.
Retry, correction, and handoff tasks use their existing `parent_task_id` to
resolve the exact latest parent attempt. This JSON-only addition preserves the
outer `clade.evidence/v1` and frozen SQLite schema while giving routing replay
fixtures a stable, redacted source.

## Routing replay

Run the matched-arm replay offline:

```bash
python3 evals/run_routing_eval.py
python3 evals/run_routing_eval.py --json
```

Each `routing_cases/*.json` record pins one sanitized task digest, exact base
tree, and deterministic verifier contract, then carries one cheap and one
strong recorded attempt projection. The runner makes no model, network, or
subprocess calls. It compares:

- `strong_self`: the recorded strong attempt;
- `native_cheap`: the recorded cheap attempt;
- `cheap_to_strong`: cheap first, then the matched strong fallback only when
  cheap did not finish with a passing verifier and non-rejected oracle.

Every policy reports explicit numerator/denominator/value objects for pass@1,
pass@k, success/USD, success/wall-hour, and queue overhead, plus wall-time
variance and sample/attempt counts. Empty denominators are `null`. The committed
starter corpus is visibly marked `constructed:`; future human-reviewed
production projections use `eval:` provenance and must keep the same
task/base/verifier match.

The default Step-12 eligibility gate requires at least six complete matched
cases, no cascade pass@k regression versus strong-self, and no cascade
success/USD or success/wall-hour regression. Insufficient samples yield **not
evaluated**, not a pass. The replay passing is evidence to review a default-off
policy; it does not itself enable routing.

## Verifier-aware routing cascade

The runtime policy is deliberately default-off. Enabling
`verifier_cascade_enabled` still does nothing unless automatic model routing is
enabled and the project explicitly declares a deterministic verifier:

```json
{
  "test_cmd": "pytest tests/ -q",
  "test_cmd_deterministic": true,
  "test_cmd_id": "project-pytest"
}
```

The command itself is not copied into routing evidence; its SHA-256 digest and
the declared ID form the verifier identity. Cheap-first eligibility additionally
requires a non-critical task, readiness at or above
`verifier_cascade_min_score`, a task class in
`verifier_cascade_task_types`, and non-empty `own_files`. The changed-file count
may not exceed `verifier_cascade_max_files`.

An eligible task gets exactly one cheap attempt. No diff, a failing or
unavailable verifier, a retryable classified runtime error, verifier/oracle
disagreement or unavailability, oracle rejection, or scope expansion creates
one strong fallback. That child preserves task lineage, ownership bounds,
runtime connection, execution profile and requirements, task type, and phase.
A failing strong child does not create another cascade child. Attempt telemetry
records the stage, normalized verifier status, and escalation signal.

Passing the committed constructed replay is not production break-even evidence,
so installs and upgrades keep this setting disabled until reviewed production
samples justify changing the default.

## Production routing break-even report

The session API exposes a read-only report from the latest immutable attempt
snapshots:

```text
GET /api/eval-candidates/routing-break-even
GET /api/eval-candidates/routing-break-even?min_samples=30
```

It groups production observations by task class, agent runtime, model, and
effort. Every group reports attempts/tasks, oracle-approved verified successes,
success rate, estimated-cost and full phase-time denominators, success/USD,
success/wall-hour, and deterministic bootstrap 95% intervals. A break-even
projection estimates how many independent attempts would match the best
observed success rate, with projected cost and serial wall time.

The projection is explicitly observational. Attempts sourced from
`constructed:` or `eval:` fixtures, missing cost or phase timing, or lacking a
determinate verifier/oracle outcome are excluded with reason counts. At least
30 observations per group are required by default. Even above that floor,
ordinary production groups are not matched counterfactuals, so the report
returns a null recommendation and `router_mutated: false`. A causal routing
recommendation requires the same task/base/verifier matching contract used by
the replay corpus.

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
