# Implementation Plan: 2026-H2 Evidence-Driven Agent Harness

> **Role: a completed, dated plan — history, not a backlog.** Its Status header
> records that every numbered step landed. Open work lives in
> [TODO.md](TODO.md); counts stated inside this file are snapshots of when it
> was written, not current state. Decided 2026-08-29.

## Status (audited 2026-07-29)

Every numbered step in the Execution Order below has landed. The plan's own
exit criteria are met: Brainstorm/TODO report truthful counts, both MCP
servers run on SDK v2, `/equip sync --apply` fails closed on unaudited drift,
worker events/provider output are sanitized before persistence, and the final
merged `main` has been installed on this server with the checkout back on
`main` (see `PROGRESS.md`, 2026-07-28 entries and the follow-on 2026-07-29
delivery hardening — safe `abandon` transition `9975895`/`26e88ec`, task
connection revalidation `c5a5c92`, crash-safe Loop checkpoint recovery
`25949fe`). The documentation convergence audit then reproduced one follow-on
runtime gap: Loop lacks a safe coordinator-owned replacement for the retired
worker-side goal marking, so that P0 is tracked separately in `TODO.md`.

Only two items remain, and both are deliberately conditional, not
undelivered work — see `TODO.md` "Conditional watch" entries and the matching
BRAINSTORM.md `[Reconciled]` section:

- **Step 16 final shim deletion**: the compatibility-retirement *window*
  (idempotent migration, `agent_runtime`-only writes, deprecation headers) is
  done (`11bd560`); deleting the remaining `worker_provider`/task `provider`
  input aliases and the historical SQLite column is gated on one stable
  release recording zero compatibility events, which has not yet been
  observed.
- **Beads-style note-to-self**: intentionally out of scope unless measured
  loop-runner cross-iteration context loss recurs; no such recurrence has
  been observed.

Per-step completion evidence (exact SHA per step) is recorded inline in the
Execution Order section below rather than restated here.

## Context

### Current state — snapshot of 2026-07-27, superseded

Kept as the record of what was believed when this plan was written; the Status
block at the top of this file (audited 2026-07-29) supersedes every count here
and reports the MCP migration below as shipped. Re-measured 2026-08-29:
`TODO.md` holds 212 completed and 2 open items — both "Conditional watch"
(`TODO.md:311,314`) — and `BRAINSTORM.md` has 2 unchecked boxes, not 44.

- `TODO.md` has 188 completed checkboxes and one real open item:
  migrate both MCP servers from Python SDK v1 to v2 and remove the `mcp<2`
  compatibility ceiling.
- MCP Python SDK `v2.0.0` shipped on 2026-07-28. V1 is now in
  security-maintenance mode, so the former upstream blocker is gone:
  <https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.0.0>.
- `BRAINSTORM.md` has 44 unchecked boxes, but they are not 44 open features:
  - 33 are already implemented, superseded, or intentionally rejected;
  - 1 is a conditional watch item (Beads-style note-to-self);
  - 10 remain actionable.
- The 2026-07-27 universal-harness architecture has progressed:
  - Phase 0 (correct vocabulary/fail closed), Phase 1 (execution envelope and
    capability contracts), and most of Phase 2 (surface-specific status and
    package composition) landed in PR #34 / commit `2fcc82a`;
  - Phase 3 is partial (static connection registry exists; live discovery,
    TTL/pinned fallback, and real provider adapters do not);
  - Phase 4 (Kimi/headless/cloud conformance matrix) and Phase 5 (removing
    compatibility shims) remain open.
- Existing foundations that must be reused rather than rebuilt:
  - `ExecutionEnvelope`, `WorkerEnvelope`, `StatusSnapshot`;
  - append-only `EventStream` with crash replay;
  - pre-push tests, two-pass oracle, oracle calibration, loop eval, and
    SWE-bench runners;
  - corrections/rules/hooks pipeline;
  - provider-aware model routing (default off);
  - resumable Git delivery controller with checkpoint/candidate evidence;
  - SHA-pinned GitHub Actions and staged-secret scanning.

### Target state

Clade should produce one durable, safe, evidence-linked record for every task
attempt, learn from real failures through a quarantined eval pipeline, and
measure routing decisions with real outcomes before enabling adaptive routing.
The runtime/provider abstraction should then be completed against recorded
conformance fixtures rather than extended with more ad-hoc branches.

The target is not a larger agent organization. It is a smaller, protocolized
core with better evidence, recovery, safety, and evaluation.

## Backlog Reconciliation

### Promote to the execution backlog

1. MCP Python SDK v2 migration.
2. Runtime-event and provider-output redaction before persistence.
3. Versioned lifecycle-linked `EvidenceBundle`.
4. Failure/revert/oracle-disagreement to sanitized eval-candidate pipeline.
5. Routing attempt telemetry and replay corpus.
6. Verifier-aware, default-off routing cascade after replay evidence.
7. Empirical routing break-even reports with sample counts/uncertainty.
8. `/equip sync` re-screening against the exact fetched upstream commit.
9. Universal harness Phase 3–5 residual work.
10. North Star/dashboard and VISION positioning update after metrics exist.

### Close as already implemented

- Round-4 plan drift, context-warning dead path, and orphan-process safety bugs.
- Round-2 mutation lane, judge hardening, friction log, MCP input examples,
  strike ladder, and flake-verdict policy.
- Elite-workflow oracle, CI, conventions, hydration, trim-tests, audit,
  quiet-run, merge, invariant, registry, history, rule injection, worktree,
  eval, recovery, and steering items.
- Delivery state machine, checkpoint/candidate split, restack, merge strategy,
  cleanup gate, and regression coverage.
- Universal harness Phases 0–2.

### Keep out of TODO

- Beads note-to-self: retain as a trigger-based watch item; implement only if
  real cross-iteration context-loss evidence appears.
- Automatic draft-PR creation: publication requires explicit user or
  repository authority. Keep the controller's idempotent `publish --draft`
  capability, not unconditional auto-publication.
- More permanent agent roles, branded crew topologies, slash-command growth,
  and compatibility layers for inactive research scaffolds.

## Architecture Decisions

1. **Reconcile before building**: mark stale Brainstorm checkboxes as resolved
   or superseded and promote only accepted work to TODO.
   This prevents autonomous loops from executing historical research prose.
2. **Migrate MCP first**: the upstream compatibility blocker disappeared on
   2026-07-28, and `pip install mcp` now resolves to v2.
   Keep the migration atomic across the orchestrator server, distributable MCP
   package, dependencies, and tests.
3. **Sanitize before aggregating**: event redaction lands before EvidenceBundle
   and automatic eval ingestion, so new aggregation paths never normalize
   copying raw secrets or private paths.
4. **EvidenceBundle is a new lifecycle contract, not a larger
   `completion_summary`**: summaries remain human-readable; evidence is typed,
   versioned, append-only per attempt, and machine-verifiable.
5. **Use one attempt identity**: task retry, provider thread/turn, worker
   events, oracle result, delivery candidate, and eval candidate must share an
   `attempt_id`/`attempt_index`.
6. **Quarantine before corpus**: real failures produce sanitized candidates,
   never automatic ground-truth fixtures. Human confirmation is required
   before promotion to oracle/loop/routing evals.
7. **Measure routing before changing routing**: add telemetry and replay
   runners first. The verifier-aware cascade remains opt-in until success per
   dollar and success per wall-hour do not regress for a task class.
8. **No learned router without enough data**: explicit deterministic rules
   remain authoritative when sample count or confidence is insufficient.
9. **Complete provider abstraction through conformance fixtures**: add live
   registry/discovery and new runtime adapters only after recorded fixtures
   cover identity, capabilities, degradation, status, and resume behavior.
10. **Remove compatibility shims last**: `worker_provider`, Claude-specific
    model fields, and legacy command names stay readable until migration
    telemetry and contract tests prove no supported path depends on them.

## Versioned Contracts

### `clade.evidence/v1`

Minimum fields:

```yaml
schema_version: clade.evidence/v1
task_id: string
attempt_id: string
attempt_index: integer
parent_attempt_id: string|null
request:
  description_hash: string
  acceptance_criteria: [string]
execution:
  envelope: clade.execution/v1
  started_at: timestamp
  finished_at: timestamp
  queue_ms: integer
  inference_ms: integer
  verify_ms: integer
git:
  base_sha: string|null
  head_sha: string|null
  changed_files: [string]
verification:
  commands: [{command, exit_code, output_digest, artifact_refs}]
  oracle: {verdict, reason, model, calibration_version}
artifacts:
  - {kind, path_or_uri, digest, media_type, created_at}
delivery:
  delivery_id: string|null
  pr: integer|null
  candidate_sha: string|null
  human_verdict: string|null
cost:
  input_tokens: integer|null
  output_tokens: integer|null
  estimated_usd: number|null
redaction:
  policy_version: string
  redaction_count: integer
outcome:
  status: verified|rejected|unreviewed|cancelled
  rollback_ref: string|null
```

Rules:

- Store evidence as immutable per-attempt records, not mutable task columns.
- Store large stdout/stderr and media by digest/reference, not inline in SQLite.
- Never include credentials, authorization headers, private endpoint query
  strings, or unsanitized absolute paths.
- Evidence may reference a delivery record but must not grant Git publication
  or merge authority.

### `clade.eval_candidate/v1`

Minimum fields:

- candidate ID and source attempt/evidence ID;
- trigger (`incident_failure`, `oracle_rejected`, `oracle_unreviewed`,
  `oracle_disagreement`, `managed_revert`, `explicit_correction`);
- sanitized diff/signal payload, exact immutable evidence revision/digest,
  observed verdict, and provenance; candidates never contain proposed ground
  truth;
- review state (`quarantined`, `promoted`, `rejected`, `expired`);
- reviewer identity/time and target corpus on promotion.

## Execution Order

### Wave 0 — Truthful backlog and immediate compatibility

0. **Record late delivery authority — completed 2026-07-28 (`e72428e`)**
   - Add a monotonic, audited transition for explicit push/PR/merge/delete
     authority granted after a delivery has started.
   - Never require direct edits to Git-private delivery state.
   - Tests: late authority enables publication; conflicting authority is
     rejected.
   - Delivered as `delivery.py cmd_authorize`: records authority per action,
     refuses to silently replace an already-granted non-pending authority,
     and rejects updates on a terminal delivery state.

0a. **Remove automatic squash bias — completed 2026-07-28 (`1e603d0`)**
   - Preserve live stack topology, prefer rebase for a single verified commit,
     and require an explicit history-semantic decision for multi-commit PRs
     whenever the forge allows several merge methods.
   - Tests: multi-commit `auto` is ambiguous; single-commit `auto` rebases.

1. **Reconcile Brainstorm/TODO state — completed 2026-07-28 (`9f82463`)**
   - Files: `BRAINSTORM.md`, `TODO.md`, `docs/research/README.md`
   - Mark 33 stale checkboxes resolved/superseded.
   - Keep the Beads item explicitly conditional.
   - Promote the accepted program below into TODO with phase/status labels.
   - Depends on: nothing.

2. **Migrate MCP Python SDK v2 — completed 2026-07-28 (`c76a098`, #40)**
   - Files: `orchestrator/mcp_server.py`,
     `mcp-package/src/clade_mcp/server.py`,
     `orchestrator/requirements.txt`, `mcp-package/pyproject.toml`,
     MCP tests and package/install fixtures.
   - Replace v1 low-level decorator registration with v2 `on_*` handlers or a
     shared `MCPServer` surface, preserve compact/full tool behavior and stdio.
   - Update dependency floors and keep `httpx` explicit where Clade itself
     still imports it.
   - Verify v1-era clients remain supported by the v2 server.
   - Depends on: nothing.

3. **Re-screen `/equip sync` — completed 2026-07-28 (`e34632c`)**
   - Files: `configs/scripts/equip_sync.py`,
     `configs/scripts/equip_audit.py`, equip tests and skill docs.
   - Bind an audit report to the exact upstream commit.
   - If fetched HEAD differs, run injection/red-flag screening again or block
     apply until a new report is accepted.
   - Depends on: nothing.

### Wave 1 — Safe evidence substrate

4. **Add structured runtime redaction — completed 2026-07-28 (`229ad3c`)**
   - Files: new leaf module `orchestrator/runtime_redaction.py`,
     `orchestrator/event_stream.py`, provider-output persistence call sites,
     focused tests.
   - Recursively redact sensitive keys and high-signal token/path patterns
     before JSONL/SQLite/log persistence.
   - Record redaction metadata without retaining originals.
   - Depends on: nothing, but must land before Steps 5–6.

5. **Define and persist `EvidenceBundle` — completed 2026-07-28 (`400f01b`)**
   - Files: new leaf module `orchestrator/evidence_bundle.py`,
     `orchestrator/task_queue.py`, `orchestrator/config.py`,
     schema fixture and contract tests.
   - Add immutable evidence table keyed by attempt identity.
   - Validate schema version, digests, redaction metadata, and state
     transitions.
   - Depends on: Step 4.

6. **Wire worker, verifier, delivery, and UI evidence — completed 2026-07-28 (`421eaf7`)**
   - Files: `orchestrator/worker.py`, `orchestrator/worker_review.py`,
     `orchestrator/worker_envelope.py`, delivery controller,
     task/detail API and TypeScript views.
   - Capture execution envelope, timings, Git SHA, test evidence, oracle
     verdict, artifact references, cost, and delivery candidate.
   - Keep screenshots/video optional by task type but visible when present.
   - Depends on: Step 5.

### Wave 2 — Failures become evals

7. **Create quarantined eval candidates — completed 2026-07-28**
   - Files: new `orchestrator/eval_candidates.py`,
     event/oracle/correction/revert integration points, DB migration, tests.
   - Produce candidates from real failure signals after redaction.
   - Deduplicate by source attempt + trigger + diff digest.
   - Depends on: Steps 4–6.

8. **Add review/promote tooling — completed 2026-07-28**
   - Files: `orchestrator/evals/`, a small CLI or route, eval README/tests.
   - Review pending candidates and promote accepted cases into the correct
     corpus with complete provenance.
   - Never accept automatically.
   - Depends on: Step 7.

9. **Add regression-coverage metrics — completed 2026-07-28**
   - Files: analytics/status modules and dashboard types/components.
   - Report candidates pending, accepted coverage, false-approve rate, human
     overrides, and evidence completeness.
   - Depends on: Steps 6–8.

### Wave 3 — Measured routing

10. **Persist attempt and phase timings — completed 2026-07-28**
    - Files: task/evidence schema, worker lifecycle, routing and status tests.
    - Record `attempt_index`, `parent_attempt_id`, `queue_ms`, `inference_ms`,
      `verify_ms`, final oracle, route reason, model, effort, and outcome.
    - Depends on: Step 5.

11. **Build routing replay eval — completed 2026-07-28**
    - Files: new `orchestrator/evals/run_routing_eval.py`, sanitized fixtures,
      tests and documentation.
    - Compare strong-self, native-cheap, and cheap→strong cascade on fixed
      task/base/verifier inputs.
    - Report pass@1/pass@k, success/$, success/wall-hour, queue overhead,
      variance, and sample count.
    - Depends on: Steps 8 and 10.

12. **Implement verifier-aware cascade, default off — completed 2026-07-28**
    - Files: `orchestrator/worker_routing.py`, retry/requeue paths, settings UI,
      replay/contract tests.
    - Cheap-first only for low-risk tasks with deterministic verifiers.
    - Escalate on no diff, test failure, repeated error, verifier disagreement,
      unreliable verifier, or scope/risk expansion.
    - Allow at most one cheap retry.
    - Depends on: Step 11 meeting documented non-regression thresholds.
    - Delivered as a fail-closed two-stage state machine: one eligible cheap
      attempt, then at most one strong fallback. Every fallback preserves task
      lineage, runtime connection/profile/requirements, phase, and ownership
      bounds. Preflight and terminal telemetry distinguish not-run, passed,
      failed, disagreement, unreliable, no-diff, and scope-expansion outcomes.
      The toggle remains off because the passing starter replay is constructed,
      not production evidence.

13. **Fit empirical break-even reports — completed 2026-07-28**
    - Files: analytics/reporting only at first.
    - Group by task class/model/effort; show confidence intervals and refuse a
      recommendation below the minimum sample size.
    - A learned router is a later decision, not part of this step.
    - Depends on: sustained data from Steps 10–12.
    - Delivered as a production-only read model over latest immutable attempt
      evidence. It reports task-class/runtime/model/effort groups, explicit
      denominators, deterministic 95% intervals, and independent-attempt
      cost/wall projections. Constructed/eval evidence is excluded; comparisons
      require 30 samples per group. Ordinary production grouping is labeled
      observational and cannot produce or apply a routing recommendation
      without matched task/base/verifier counterfactuals.

### Wave 4 — Finish the universal harness

14. **Complete provider/model registry — completed 2026-07-28 (`1495c3b`)**
    - Files: `orchestrator/execution_envelope.py`,
      `orchestrator/execution_resolver.py`, provider skill, settings/API/UI.
    - Add live discovery with TTL, explicit stale pinned fallback, capability
      provenance, and real Anthropic/OpenAI/MiniMax/Moonshot connection
      adapters.
    - Depends on: stable EvidenceBundle identity fields.

15. **Add runtime/surface conformance fixtures — completed 2026-07-28 (`8728746`, gated by `b2c3608`)**
    - Files: recorded sanitized adapter fixtures and conformance runners.
    - Cover Claude, Codex, MCP/headless first; add Kimi only when the runtime
      is available and its lifecycle can be observed.
    - Credential-gated live smoke tests report skipped coverage rather than
      silently passing.
    - Depends on: Step 14.

16. **Retire compatibility shims — window landed 2026-07-28 (`11bd560`); final deletion is a conditional watch**
    - Files: config/settings, worker/runtime adapters, generators, docs.
    - Remove deprecated aliases only after fixture and telemetry evidence show
      no supported path uses them.
    - Provide explicit migration errors/import tooling.
    - Depends on: Steps 14–15.
    - Delivered: internal terminology, workers, status, task responses, and
      UI use only `agent_runtime`; settings/SQLite migrations are idempotent;
      new rows no longer dual-write `provider`; old API inputs get deprecation
      headers plus a secret-free aggregate counter
      (`docs/COMPATIBILITY-RETIREMENT.md`). Not yet done, and deliberately
      not invented as done: deleting the remaining input aliases and the
      historical `tasks.provider` SQLite column — gated on one stable release
      recording zero compatibility events (see TODO.md "Conditional watch").

### Wave 5 — Product metrics and positioning

17. **Update North Star and dashboard — completed 2026-07-28 (`ef1a8e5`)**
    - Files: `VISION.md`, analytics/status API, dashboard.
    - Add evidence completeness, false-approval rate, human override rate,
      regression coverage, success/$, and success/wall-hour alongside
      autonomous duration.
    - Depends on: Waves 1–3 producing real data.

18. **Reposition the orchestrator — completed 2026-07-28 (`1e603d0`)**
    - Files: `VISION.md`, README architecture sections.
    - Treat native fan-out/scheduling as harness table stakes.
    - Position Clade around provider-neutral execution identity, evidence,
      verifier calibration, correction learning, delivery, and fleet truth.
    - Depends on: implemented mechanisms, not research promises.

### Wave 6 — Local rollout and repository cleanup

19. **Install the final merged configuration on this server — completed 2026-07-28 (`ac0802a`, #58)**
    - Source: the final verified `main`, never an intermediate task branch.
    - Run the repository install flow so current skills, hooks, scripts,
      agents, generated catalogs, and native Codex plugin surfaces are present
      in the user-scoped installation.
    - Preserve credentials, provider connections, learned correction rules,
      and other user-owned mutable state.
    - Compare installed files against the tracked canonical sources and run
      the clean-HOME install regression before and after the real installation.
    - Depends on: Waves 0–5 merged and final `main` verified.
    - Superseded once more by the 2026-07-29 follow-on delivery-hardening
      commits landing after this closeout (`9975895`, `26e88ec`, `c5a5c92`,
      `25949fe`); the Codex plugin cache was refreshed for the delivery changes
      that preceded Loop recovery (`8d93e1e`), while the Claude/MCP Loop files
      were installed separately from merged `main`. Re-running Wave 6 whenever
      meaningful post-closeout commits land is expected, not a sign the
      original closeout was wrong.

20. **Remove completed delivery branches and return to main — completed 2026-07-28 (`ac0802a`, #58)**
    - Merge only exact reviewed candidate SHAs after required CI is green.
    - Delete merged task branches locally and remotely when no live child
      delivery depends on them.
    - Run `git fetch --prune`, switch to `main`, update with `--ff-only`, and
      prove `main == origin/main`.
    - Remove no branch/worktree that is unmerged, owned by another live
      session, or needed by a stacked child.
    - Final state: clean worktree, no completed local/remote task branches,
      no stale worktrees, and all delivery records terminal.
    - Depends on: Step 19.

## File Interaction Graph

```text
runtime_redaction.py
    ├── event_stream.py
    ├── provider stdout/stderr persistence
    └── eval_candidates.py

execution_envelope.py
    └── evidence_bundle.py
          ├── task_queue.py
          ├── worker.py
          │     ├── worker_review.py
          │     └── worker_envelope.py
          ├── delivery.py
          ├── eval_candidates.py
          ├── worker_routing.py
          └── status/dashboard

eval_candidates.py
    └── eval promotion CLI/route
          ├── oracle/loop/resolve corpora
          └── routing replay corpus

MCP v2 SDK
    ├── orchestrator/mcp_server.py
    ├── mcp-package/src/clade_mcp/server.py
    ├── dependency manifests
    └── install/runtime tests
```

## PR / Delivery Boundaries

Each numbered step is an independently reviewable PR unless explicitly split
after code inspection. Never combine Waves 0–5 into one branch.

Recommended first delivery stack:

```text
main
├── backlog-reconciliation
├── mcp-sdk-v2
├── equip-sync-rescreen
└── runtime-event-redaction
      └── evidence-contract
            └── evidence-wiring
```

The first four branches are independent. Evidence contract/wiring is a stack
because the latter consumes the former. Every PR must carry its own tests and
exact-SHA candidate evidence.

After the final feature PR merges, perform local installation and branch
cleanup as one explicit closeout transaction; do not treat either as an
afterthought or leave the repository on a topic branch.

## Risks & Mitigations

- **Historical checkbox drift**: reconcile by code/commit evidence, not by
  changing `[ ]` to `[x]` blindly; record implemented SHA or superseding
  mechanism.
- **MCP v2 wire regression**: test compact/full discovery and tool invocation
  over stdio with the installed v2 SDK; retain backward protocol negotiation.
- **Secret leakage into evidence/evals**: sanitize before persistence, keep raw
  output outside promoted fixtures, and add canary-secret tests.
- **Over-redaction destroys debugging value**: redact typed fields and
  high-signal patterns; record hashes/counts and preserve non-sensitive
  surrounding context.
- **SQLite migration breaks old installs**: use additive, idempotent migrations
  and schema snapshot tests; no destructive rewrite.
- **EvidenceBundle duplicates WorkerEnvelope**: WorkerEnvelope remains the
  worker's completion message; EvidenceBundle is the cross-lifecycle audit
  record and may reference the WorkerEnvelope.
- **Eval poisoning**: quarantine and human confirmation are mandatory; a model
  cannot assign its own ground truth.
- **Routing benchmark overfits**: fixed base/verifier, repeated trials,
  variance reporting, task-class stratification, and no default-on decision
  from a single run.
- **Provider discovery becomes a credential broker**: repository state stores
  only secret-free connection identities; credentials remain user-scoped.
- **Compatibility removal strands users**: remove aliases only after telemetry,
  conformance tests, deprecation warnings, and documented migration.
- **Plan grows faster than delivery**: execute one wave at a time, maximum six
  active tasks, one writer per file set, and re-audit remaining scope after
  every wave.
- **Local install overwrites user-owned state**: use the repository installer
  and its merge/preserve rules; snapshot and compare user-scoped mutable files,
  never copy the repository tree wholesale over `~/.claude`.
- **Branch cleanup destroys stacked work**: resolve live delivery ownership and
  child ancestry before deletion; cleanup only merged, session-owned branches.

## Verification Strategy

### Per checkpoint

- focused pytest for affected modules;
- `git diff --check`;
- generated-copy drift checks when skills/packages change;
- explicit secret/redaction fixtures for evidence work.

### Per candidate

```bash
cd orchestrator
.venv/bin/python -m pytest tests/ -v
find . \( -name .venv -o -name node_modules -o -name __pycache__ \) \
  -prune -o -name "*.py" -print | xargs -n1 python -m py_compile
cd ..
bash -n configs/hooks/*.sh configs/scripts/*.sh install.sh
python3 configs/scripts/regen-codex-plugin.py --check
bash tests/test-loop.sh
bash tests/test-install.sh
```

Add feature-specific gates:

- MCP v2: stdio discovery + compact/full tool call tests for both server copies.
- Redaction: nested JSON, tokens, paths, false-positive corpus, corrupt input,
  and replay tests.
- Evidence: migration, schema version, append-only attempts, artifact digest,
  delivery linkage, and legacy-task tests.
- Eval ingestion: dedup, quarantine, explicit promotion, provenance, and
  no-secret fixtures.
- Routing: deterministic replay runner plus a manual/live cost tier; live API
  tests never become mandatory for contributors without credentials.
- Runtime matrix: recorded contract fixtures in CI and credential-gated live
  smoke tests.
- Final local rollout: `tests/test-install.sh`, a throwaway-HOME install,
  real `./install.sh`, installed-vs-canonical comparison, and a post-install
  smoke check of skill/hook/script discovery.
- Final Git cleanup: delivery `verify-clean`, `git worktree list --porcelain`,
  `git branch -vv`, remote branch inspection, `git fetch --prune`, and exact
  `main`/`origin/main` SHA equality.

## First-Phase Exit Criteria

Wave 0–1 is complete only when:

- Brainstorm and TODO report truthful counts;
- both MCP servers run on SDK v2 without the `<2` ceiling;
- `/equip sync --apply` cannot consume unaudited upstream drift;
- worker events/provider outputs are sanitized before persistence;
- full repository verification passes on each exact candidate SHA;
- every change is delivered as its own repository-compliant commit/PR unit.

The whole program is complete only when the final merged `main` has also been
installed on this server, installed configuration matches the canonical
repository surfaces, completed branches are absent locally/remotely, the
checkout is back on `main`, and `main == origin/main` with a clean worktree.

## Planning Assumptions Requiring Confirmation

1. Keep all new behavior backward-compatible and default off when it can
   change routing, publication, or external side effects.
2. Use SQLite/JSONL and local artifact references; do not add a hosted
   telemetry service.
3. Execute the recommended order: Wave 0–1 first, then evidence/evals, then
   routing, and only then finish provider/runtime expansion.
