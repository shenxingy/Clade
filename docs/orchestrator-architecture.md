**English**（中文版尚未提供 — [README 中文版](../README.zh-CN.md)）

← Back to [README](../README.md)

# Orchestrator architecture map

The dormant orchestrator's import DAG and key-file table. Moved verbatim from
`CLAUDE.md` on 2026-11-16, so that every Clade session no longer loads it.
`check-arch-map.py` fails when a module under `orchestrator/` is missing from
this file, and `test_documented_detector_score_is_derived` re-derives the
detector score stated in the import DAG.

## Table of Contents

- [Orchestrator Layer (`orchestrator/`) — DORMANT as of 2026-09-02](#orchestrator-layer-orchestrator--dormant-as-of-2026-09-02)
- [Key File Map](#key-file-map)

## Orchestrator Layer (`orchestrator/`) — DORMANT as of 2026-09-02

> **The GUI is not in use.** The owner works entirely in the terminal; the
> FastAPI server, its React UI and the worker-pool / task-queue / routing /
> evidence stack behind them are deliberately dormant. It may be rebuilt, so
> nothing here is deleted and CI keeps it green — but this is **not**
> load-bearing code, and a finding here does not weigh the same as one on the
> terminal path (`configs/` skills, hooks, scripts, and the Codex plugin).
>
> The measurable consequence, and the reason this note exists: no `tasks.db` on
> the author's host carries the current schema and no evidence store exists, so
> every number this repository has about worker parallelism actually comes from
> Claude Code's own Workflow/subagent layer — which this orchestrator does not
> control. Auditing an unrun system as if it were load-bearing is how effort
> gets spent on a control that never applies.

Key modules (import DAG — leaf → root):

```
# Leaves (no project imports)
config.py            ← constants, settings, utilities
agent_runtime.py     ← agent-runtime ids + fail-closed validation
cascade_policy.py    ← pure verifier-aware cheap→strong eligibility, lineage, and signal helpers
fault_localize.py    ← multi-language SBFL: test-runner detection, go/js failure parsers, cross-lang symbol index (stdlib-only leaf; worker_tldr imports it)
agent_output.py      ← stdlib-only contract for reading a spawned agent's own usage report (stream-json/json → cost, tokens, per-model usage, prose projection)
pytest_report.py     ← stdlib-only pytest-output contract: colour-proof result parsing, verbosity normalization, colour-free subprocess env (shared by worker_utils, worker_tldr, evals/)
ideas.py             ← IdeasManager, async idea CRUD
process_manager.py   ← ProcessPool, start.sh lifecycle
repo_map.py          ← deterministic repository-structure analysis: AST/tree-sitter TLDR, entity pruning, PageRank centrality. Pure and synchronous — no LLM call, no subprocess, no DB (imports fault_localize)
worker_tldr.py       ← task-specific localization, fault location, SBFL, repro-test generation, scoring — the half that spends money (imports repo_map, fault_localize)
worker_review.py     ← oracle + PR review
worker_utils.py      ← output helpers, lint reflection, LoopDetectionService, worker-state helpers
worker_hydrate.py    ← _pre_hydrate (GitHub issue/PR pre-hydration)
condensers.py        ← Condenser ABC + implementations
api_auth.py          ← stdlib-only bearer-token guard for the control plane (ASGI middleware, so it covers websockets too) + settings-secret masking
runtime_redaction.py ← stdlib-only secret/path redaction before persistence
evidence_bundle.py   ← versioned immutable attempt evidence + digest-chain contract
event_stream.py      ← crash-safe JSONL event logging
tracing.py           ← TracingService, task spans
reactions.py         ← ReactionExecutor
error_classifier.py  ← error classify/summarize + retry decisions
session_tree.py      ← SessionTree
usage_tracker.py     ← multi-machine ccusage ingestion (used by routes/usage.py)
execution_envelope.py ← versioned immutable execution contract (runtime/provider/protocol/model split)
worker_envelope.py   ← versioned terminal contract emitted by workers
handoff_registry.py  ← typed worker-handoff schemas + prompt-safe projections
reset_handoff.py     ← compact typed context seeds for clean loop resets
run_contract.py      ← repository-owned autonomous-run policy (optional CLADE_WORKFLOW.md)
run_budget.py        ← pure run-budget policy + trace attribution
merge_policy.py      ← truthful pull-request history selection
judge_diversity.py   ← deterministic review checks independent of the LLM oracle, plus 9 test-integrity signals (counted from the diff, fed to the oracle, never an auto-fail); scored by evals/run_hack_eval.py — 100% recall / 6.2% false alarms on a 34-case adversarial corpus
status_snapshot.py   ← provider-neutral status truth rendered by surface adapters
worker_phase_graph.py ← declared worker/task/loop lifecycle graph (additive observability)
worker_sandbox.py    ← stdlib-only Landlock confinement: makes the shared .git/hooks and .git/config unwritable to a worker (default off)
compatibility_telemetry.py ← secret-free compatibility-window counters
webhook_trust.py     ← fail-closed actor authorisation for GitHub webhook events (payload-only; no API call to fail open on)
eval_candidates.py   ← validated identifiers + digests for quarantined eval candidates
eval_metrics.py      ← read-only, denominator-explicit evidence/eval quality metrics
    ↑
# Mid-tier
github_sync.py       ← gh CLI wrappers (issues, push, sync)
task_schema.py       ← tasks.db DDL: table creation + additive ALTER migrations (leaf; task_queue imports it)
task_queue.py        ← SQLite tasks + append-only evidence persistence
routing_break_even.py ← production-only observational routing analytics
swarm.py             ← SwarmManager (extracted from worker.py)
worker_pool.py       ← WorkerPool: which workers exist and polling them (extracted from worker.py; re-exported there, bound to that module's Worker)
worker_taskfile.py   ← build_task_file: task file construction + context injection
worker_runtime.py    ← runtime-route resolution + durable selection failure
worker_evidence.py   ← attempt lifecycle + worker/verifier/delivery evidence projection
attempt_telemetry.py ← pure attempt-level routing/phase telemetry builders (imports cascade_policy)
provider_registry.py ← secret-safe live model discovery, TTL cache, pinned fallback
worker_routing.py    ← pure route decision: runtime, model, effort, audit reason
worker_provider.py   ← WHICH agent CLI a worker runs (claude vs codex command + env)
execution_backend.py ← HOW a worker process is spawned/torn down (lazy config import)
execution_resolver.py ← route + provider → immutable execution envelope
worker_status.py     ← worker status serialization kept out of the execution engine
eval_review.py       ← human review + atomic corpus promotion for eval candidates
eval_review_cli.py   ← standalone CLI to promote/reject quarantined eval candidates
    ↑
worker.py            ← Worker, WorkerPool — core execution engine
session.py           ← ProjectSession, registry, status_loop (lazy-imports task_factory/)
    ↑
# Roots
server.py            ← FastAPI app, remaining routes, mounts all routes/* routers
mcp_server.py        ← standalone MCP entrypoint exposing skills (stdio transport)
oracle_cli.py        ← standalone oracle gate CLI (strangler extraction; shim configs/scripts/oracle-review.sh)
routes/tasks.py      ← Task CRUD + bulk-action routes
routes/workers.py    ← Worker control + inspection routes
routes/webhooks.py   ← GitHub webhook handler
routes/ideas.py      ← Ideas API routes (CRUD, evaluate, execute, promote)
routes/process.py    ← Process manager API routes
routes/usage.py      ← Usage dashboard API routes
routes/evals.py      ← Human-review routes for quarantined eval candidates
routes/providers.py  ← Secret-safe provider/model registry inspection + refresh
```

Every `orchestrator/*.py` and `orchestrator/routes/*.py` must appear above —
CI's "Architecture map coverage" gate fails on any module missing from this file.

`orchestrator/task_factory/` is excluded from that gate by `check-arch-map.py`'s
`SKIP_DIRS`, so its four modules are listed here for the reader rather than
enforced. All four are lazy-imported from `session.py`:

```
ci_watcher.py     ← failed GitHub Actions run → task
coverage_scan.py  ← coverage gap → task
dep_update.py     ← outdated dependency → task
mutation_scan.py  ← surviving mutant → task
```

## Key File Map
| File | Purpose |
|------|---------|
| `config.py` | `GLOBAL_SETTINGS`, `_ALLOWED_TASK_COLS`, model aliases, cost utils |
| `agent_runtime.py` | Agent-runtime identity and fail-closed selection shared by routing/settings/factory |
| `cascade_policy.py` | Pure default-off verifier-cascade policy, escalation signals, and retry contract projection |
| `evidence_bundle.py` | Immutable `clade.evidence/v1` snapshots, lifecycle validation, and digest-chain verification |
| `task_schema.py` | `ensure_schema` — every CREATE TABLE and additive migration for tasks.db, split out of `task_queue._ensure_db` |
| `task_queue.py` | SQLite CRUD for tasks, loops, messages, interventions, and append-only attempt evidence |
| `routing_break_even.py` | Read-only production EvidenceBundle aggregation for observational routing break-even metrics |
| `worker.py` | `Worker`, `WorkerPool` — core execution engine |
| `swarm.py` | `SwarmManager` (extracted from worker.py; re-exported there) |
| `worker_pool.py` | `WorkerPool` — worker scheduling and polling. `worker.py` subclasses it to bind its own `Worker`, which keeps privately-loaded test copies private |
| `worker_taskfile.py` | `build_task_file` — task file construction + context injection |
| `worker_runtime.py` | Runtime route resolution and fail-closed task outcome persistence |
| `worker_sandbox.py` | Landlock ruleset that PREVENTS the git control-surface escape `worker_git_surface_guard` only detects (`worker_sandbox`, default off) |
| `worker_evidence.py` | Evidence attempt lifecycle, Git/test/oracle/cost/artifact projection, and terminal delivery candidate |
| `repo_map.py` | `_generate_code_tldr`, `_pagerank_centrality`, `_keyword_filter_tldr` — builds the map of a repository. Split out of `worker_tldr.py` at 1459 of the 1500-line ceiling; the boundary is "map the repo" vs "narrow that map to a task", and the purity of this half is what the split buys |
| `worker_tldr.py` | `_localize_tldr_for_task`, `_localize_fault`, `_sbfl_prepass`, `_score_task` — narrows the map for one task |
| `agent_output.py` | `parse_agent_output` / `absorb_agent_result` — the agent's self-reported `total_cost_usd` and usage, and the prose projection every log consumer reads (leaf) |
| `pytest_report.py` | `parse_results` / `force_verbose` / `color_free_env` — the one definition of how pytest output is read back (leaf) |
| `worker_review.py` | `_write_pr_review`, `_oracle_review`, `_write_progress_entry` (leaf) |
| `oracle_cli.py` | Standalone oracle gate — same judge as the orchestrator, no server needed (`oracle-review.sh` shim; opt-in `/commit` gate via `CLADE_ORACLE_GATE=1`) |
| `worker_utils.py` | Output helpers, lint reflection, `LoopDetectionService`, worker-state helpers (leaf) |
| `session.py` | `ProjectSession`, `SessionRegistry`, `status_loop()` |
| `server.py` | FastAPI app, session/loop/swarm/usage/settings routes, WebSocket |
| `github_sync.py` | GitHub issue create/update/pull/push via `gh` CLI |
| `ideas.py` | `IdeasManager` — async idea CRUD, AI evaluation, promotion |
| `process_manager.py` | `ProcessPool`, `StartProcess` — start.sh lifecycle control |
| `usage_tracker.py` | Multi-machine ccusage ingestion (`~/.claude/orchestrator/usage.db`) |
| `routes/tasks.py` | Task CRUD, bulk actions, and on-demand verified evidence attempts |
| `routes/workers.py` | Worker control + inspection routes (10 handlers) |
| `routes/ideas.py` | Ideas API routes (CRUD, evaluate, execute, promote) |
| `webhook_trust.py` | `is_trusted_actor` — a signature proves the event came from GitHub, not that its author may direct a permission-bypassed worker |
| `api_auth.py` | `TokenAuthMiddleware` — default-closed authorisation for all 93 routes and both websockets. Middleware, not per-route `Depends`, because the next route added would silently forget the dependency and because `BaseHTTPMiddleware` never sees a websocket scope |
| `routes/usage.py` | Usage dashboard API routes |
| `web/src/` | Vite + React + TypeScript UI source (App.tsx, components/, stores/, hooks/, lib/) |
| `web/index.html` | Vite *source* shell (`<div id="root">` + main.tsx) — the build entry, never served. It loads `/src/main.tsx`, which no browser executes. |
| `web/usage.html` | Standalone usage dashboard. Served by an explicit route registered BEFORE the `/web` mount — `vite.config.ts` declares no `publicDir`, so the build never copies it into `dist/` and the mount alone 404s it on every machine that built. |
