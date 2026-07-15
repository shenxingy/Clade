---
name: OpenAI — Codex & Agent-Framework Repos (Tier-2)
date: 2026-07-15
status: needs_work
review_date: 2026-07-15
summary: >
  Deep-dive on OpenAI's public agentic-coding repos, vetted against Clade
  (supervisor/worker loop that already drives `codex exec` workers). Codex
  itself: `codex exec --json` (JSONL lifecycle events) + `--output-schema` is a
  clean worker protocol Clade's Codex backend does NOT yet consume (docs/codex.md
  admits no JSONL/resume/usage/cancel). openai/codex-plugin-cc packages EXACTLY
  Clade's manual CC->Codex pattern with an app-server broker, resumable named
  jobs, and an ALLOW|BLOCK stop-review gate. openai/skills = the SKILL.md folder
  convention (Clade's generator already keeps CC+Codex aligned — steal only
  agents/openai.yaml + tier metadata). The agent frameworks (agents-python,
  symphony, swarm, evals, simple-evals, realtime-agents, harmony) mostly operate
  at a deliberately DIFFERENT conversational/voice layer, but surfaced real,
  buildable gaps: schema-validated handoff envelopes, a repo-owned run contract,
  an end-to-end loop eval corpus, oracle calibration (false-approve rate), a
  declared worker phase graph, and a schema-first internal protocol. Symphony
  validates Clade's worktree-loop topology as correct.
sources:
  - https://github.com/openai/codex
  - https://github.com/openai/codex-plugin-cc
  - https://github.com/openai/skills
  - https://github.com/openai/openai-agents-python
  - https://github.com/openai/symphony
  - https://github.com/openai/swarm
  - https://github.com/openai/evals
  - https://github.com/openai/simple-evals
  - https://github.com/openai/openai-realtime-agents
  - https://github.com/openai/harmony
integrated_items:
  - "Persistent supervisor/worker loop in isolated git worktrees + SQLite task queue + oracle/PR gate — already Clade's topology; openai/symphony independently validates it (worker.py WorkerPool, task_queue.py claim_next_pending)"
  - "codex exec headless workers — Clade already drives them (proven in the mnemo orchestration); this doc scopes making them FIRST-CLASS"
  - "Typed child-worker handoff fields (handoff_type/handoff_payload) + _handoff_to_worker; JSONL event causality (event_stream.py); TracingService span tree"
  - "Skills system with a CC<->Codex generator (configs/skills, plugins/clade/skills, skills.list) — more complete than openai/skills' now-deprecated catalog"
  - "Oracle fixtures (20 live-oracle + supervisor-parser) + SWE-bench runners (orchestrator/evals/) — judge-level eval exists; the gap is the loop-level corpus"
# Loop status 2026-07-15: 7/9 built as opt-in additive primitives (PRs #11-#15,#19);
# 2 deferred as design-heavy (need architecture decisions, not a single additive module).
needs_work_items:
  - "[DEFERRED design-heavy] Codex backend as first-class worker: consume `codex exec --json` (persist thread_id from thread.started) + require an `--output-schema` result {status,summary,tests,changed_files,blocker}; add resume/cancel/usage before advertising Codex-native /loop (openai/codex)"
  - "[DEFERRED design-heavy] CC<->Codex companion adapter: app-server broker + workspace state {job_id,codex_thread_id,session_id,phase,log,final} + resumable named jobs (--resume-last keyed by repo) + a stop-review gate whose review output has a machine-parseable ALLOW|BLOCK first line, run once per changed head (openai/codex-plugin-cc)"
  - "[DONE #14] Handoff registry {type -> JSON Schema/validator, redaction/allowlist, payload-version}: validate before task insert, keep raw payload in events, build the child prompt from a typed projection (openai-agents-python)"
  - "[DONE #15] Optional versioned repo-owned run contract (CLADE_WORKFLOW.md: intake states, concurrency, retry/backoff, worktree hooks, verify commands, oracle/auto-merge posture, worker template); record its git SHA in the task/event span (openai/symphony)"
  - "[DONE #13] Single versioned worker-completion envelope {status,summary,artifacts,next_handoff?,context_patch?,blockers} validated+persisted atomically — one source of truth for /pickup, web UI, child task-file (openai/swarm + harmony)"
  - "[DONE #11] End-to-end loop eval corpus: orchestrator/evals/loop_cases/*.json (task, fixture ref, expected terminal state, evidence, cost ceiling, tags) run in fresh worktrees with per-case JSONL + baseline/delta report; offline in CI + small live canary (openai/evals)"
  - "[DONE #12] Oracle calibration split (30-50 adjudicated historical diffs, human label+severity): report approve/reject precision-recall separately + false-approve rate + bootstrap CI; require a false-approve ceiling before auto-merge (openai/simple-evals)"
  - "[DONE #19] Declared worker phase graph (plan->implement->verify->oracle->repair|done|blocked) with permitted tools, evidence-to-cross-edge, recorded transition_reason; enforce in pool/queue + render in event stream/UI (openai-realtime-agents) — shipped as opt-in observability (worker_phase_graph.py); enforcement stays advisory by design"
  - "[DONE #13] Schema-first internal protocol: versioned WorkerEnvelope for supervisor plans/worker reports/oracle evidence/condenser summaries, validated producer+consumer with round-trip fixtures — replace remaining prose/regex JSON parsing (openai/harmony) — envelope primitive shipped; broader prose/regex replacement is incremental follow-up"
---

<!-- Research by 2 parallel codex workers, 2026-07-15, orchestrated by Claude Code. Verdicts checked against live Clade source (orchestrator/worker.py, task_queue.py, worker_review.py, event_stream.py, orchestrator/evals/, configs/skills). Method: the house rule — "does Clade do this; DEFICIENT or DIFFERENT-by-design; what specifically to steal?" -->

# OpenAI Codex-adjacent research notes

Research date: 2026-07-15. Stars are GitHub API snapshots. File references are to the corresponding shallow clones in `/tmp/openai-research`.

### openai/codex (98131★)

- **What it is** — The open-source Codex terminal/app harness: interactive coding agent plus `codex exec` for scripts/CI, with its own plugins, hooks, MCP, sandboxing, resumable SQLite state, and now native in-session multi-agent threads.
- **Notable patterns/architecture**
  - `codex exec` is a clean automation contract: final message only on stdout; `--json` emits JSONL lifecycle/item events (including commands, file changes, MCP, plans), and `--output-schema` + `-o` makes the final output schema-valid JSON (`docs/noninteractive` / official docs; CLI behavior). `--ephemeral`, explicit `--sandbox workspace-write|danger-full-access`, `--ignore-user-config`, and `--ignore-rules` make runs reproducible.
  - The config model is unusually harness-friendly: trusted `.codex/config.toml` layers, profiles, `service_tier = "flex"|"fast"`, sandbox writable-root/network controls, and per-MCP enable/allow/deny/approval/timeout configuration (official config reference; `codex-rs/config/src/config_toml.rs`). Note the important correction: public config documents `minimal..xhigh`; source also accepts `ultra` (`codex-rs/protocol/src/openai_models.rs`) and translates it to request `max` (`codex-rs/core/src/client.rs`). It is an effort preset, not itself “delegation.”
  - Native fanout is now first-class rather than a shell convention: `[agents]` roles can point at a role config, with `max_threads` (default 6), `max_depth` (default 1), and per-CSV-worker timeout; implementation has spawn/assign/wait/close tools (`codex-rs/core/src/tools/handlers/multi_agents_v2/`). Full-history forks must inherit parent model/effort; isolated forks can override them (`codex-rs/core/src/config/mod.rs`).
  - Plugins package skills/hooks/MCP as one unit (`codex-rs/plugin/src/manifest.rs`); marketplaces are repo-local `.agents/plugins/marketplace.json` with install/auth policy. Hooks support lifecycle events through command handlers, but prompt/agent handlers are currently parsed then skipped (official config reference; `codex-rs/config/src/hook_config.rs`).
- **Clade verdict**: **DIFFERENT** — Codex’s fanout is thread-local collaboration; Clade uniquely persists a supervisor/worker process across iterations, owns Git worktrees, task queue, convergence and oracle/PR gates. But Clade’s Codex backend is knowingly incomplete (`docs/codex.md`: runtime adapter still needs JSONL events, resume, usage and cancellation).
- **Steal for Clade** — Make `ExecutionBackend(Codex)` consume `codex exec --json` as the canonical worker protocol, persist `thread_id` from `thread.started`, and require an `--output-schema` worker result (`status`, `summary`, `tests`, `changed_files`, `blocker`). Then implement resume/cancel/usage from those events before advertising Codex-native `/loop`. Add worker config knobs for `--sandbox`, `service_tier`, and an environment allowlist; default isolated worktree workers to `workspace-write` and explicitly enable network only where task policy needs it. Do **not** replace worktree orchestration with Codex fanout—optionally use native fanout inside a single research/review worker only.

### openai/codex-plugin-cc (28672★)

- **What it is** — An official Claude Code marketplace plugin that makes Codex a packaged companion: read-only review/adversarial review, write-capable “rescue” delegation, background-job controls, and Claude-to-Codex session transfer through the Codex app-server.
- **Notable patterns/architecture**
  - It wraps the persistent Codex app-server rather than scraping CLI output (`plugins/codex/scripts/app-server-broker.mjs`, `lib/app-server.mjs`), while a per-workspace state store tracks queued/running/completed jobs, session ID, logs, phase and progress preview (`lib/state.mjs`, `lib/job-control.mjs`). `/status`, `/result`, and `/cancel` are genuine job controls, not conversational promises.
  - The Claude subagent is deliberately a thin forwarder: `agents/codex-rescue.md` does exactly one companion invocation, chooses foreground/background by task size, defaults writes on implementation work, and maps continuation to `--resume-last`. This prevents Claude-side duplicated investigation and preserves a resumable Codex thread.
  - Review is separated from delegation. `/codex:review` is native, read-only and cannot be steered; `/codex:adversarial-review` supplies challenge framing. Both use explicit working-tree/branch target selection (`commands/review.md`, `commands/adversarial-review.md`) and return the reviewer output without a second model summary.
  - Optional stop-time gate is a small but real closed loop: `hooks/hooks.json` wires SessionStart/End lifecycle and a 900s Stop hook; `stop-review-gate-hook.mjs` runs a targeted Codex task with a 15-minute process timeout and emits `ALLOW:` / `BLOCK:` JSON to keep Claude working when review finds an issue. It scopes active jobs to Claude session IDs.
- **Clade verdict**: **DEFICIENT** — Clade is more flexible (multi-worker worktrees, SQLite queue, oracle), but its current Codex execution is a lower-level `codex exec` worker and its native plugin explicitly excludes runtime orchestration. It lacks the polished CC↔Codex companion surface: persistent session transfer, resumable named jobs and a local stop-review gate.
- **Steal for Clade** — Build a narrow `codex-companion` adapter before broad provider-neutral orchestration: app-server broker; workspace state records `{job_id, codex_thread_id, session_id, phase, log, final}`; `$codex-rescue`, `$codex-status`, `$codex-result`, `$codex-cancel`; and `--resume-last` keyed by repo. Port the gate protocol verbatim in spirit—review output must have a machine-parseable `ALLOW|BLOCK` first line and only run once per changed head/turn—to feed Clade’s oracle rather than create unbounded Stop loops. Reuse their thin-forwarder rule, but retain Clade’s own worktree ownership and acceptance-criteria gate.

### openai/skills (23728★)

- **What it is** — A now-deprecated catalog of Codex Agent Skills, superseded by `openai/plugins`; it is still a useful, concrete reference for the Agent Skills folder convention and curated/system distribution split.
- **Notable patterns/architecture**
  - Catalog tiers are filesystem-native: `skills/.system` (auto-installed), `.curated` and `.experimental` (installed with `$skill-installer`), with per-skill licensing (`README.md`). It intentionally does not invent a heavy registry format.
  - The canonical unit is `SKILL.md` with only YAML `name` + trigger-focused `description` in always-visible metadata; the body loads after trigger. Optional `agents/openai.yaml` supplies UI metadata, while `scripts/`, `references/`, and `assets/` support progressive disclosure (`skills/.system/skill-creator/SKILL.md`).
  - Curated examples are operational, not just prompt packs: `skills/.curated/gh-fix-ci/SKILL.md` scopes GitHub Actions vs external checks, bundles a deterministic inspection script, and explicitly separates diagnosis/plan from implementation approval.
  - The repository’s own README says to use `openai/plugins` for current examples. Treat this as a format precedent, not a live catalog dependency.
- **Clade verdict**: **DIFFERENT** — Clade already has canonical `configs/skills`, generated Codex `plugins/clade/skills`, a curated `skills.list`, scripts/references, and strong runtime-specific skills. Its generator is valuable because it keeps Claude and Codex formats aligned; OpenAI’s catalog cannot replace it.
- **Steal for Clade** — Add a lightweight `agents/openai.yaml` generation/validation step to `configs/scripts/regen-codex-plugin.py`, deriving display name, short description and default prompt from each canonical skill; this improves Codex plugin discoverability without changing execution. Add explicit skill-tier metadata in `skills.list` (system/core vs curated/optional vs experimental) and make the generator enforce “frontmatter trigger description + body <=500 lines + referenced resources one level deep.” Borrow the `gh-fix-ci` pattern selectively: bundle deterministic scripts for fragile, repeated Clade workflows and state an approval boundary where a skill is diagnosis-only.

# OpenAI agent-framework sweep — 2026-07-15

Source reads are from depth-1 clones at `/tmp/openai-research/<repo>`; star counts are current `gh api` values. Verdicts were checked against Clade's current source, especially `orchestrator/worker.py`, `task_queue.py`, `worker_review.py`, `tracing.py`, `event_stream.py`, `configs/scripts/loop-runner.sh`, and `orchestrator/evals/`.

### openai/openai-agents-python (27914★)

**What it is.** A general-purpose, provider-agnostic application SDK: an `Agent` has instructions, tools, handoffs and guardrails; `Runner` executes an in-process conversational graph. It is not a coding-work scheduler.

**Notable patterns.**

- A handoff is deliberately a typed tool: `src/agents/handoffs/__init__.py` defines a strict JSON-schema payload, `on_handoff` callback, enable predicate, and `input_filter`. The filter can prune the next agent's *model input* while preserving the complete event history. That separation is unusually clean.
- Handoff state is durable enough to resume: `src/agents/run_state.py` serializes handoffs and pending nested agent-as-tool runs; the SDK also offers pluggable SQLite/Redis/SQLAlchemy/etc. sessions under `src/agents/memory/`.
- Guardrails are executable tripwires, not review prose: `src/agents/guardrail.py` supports input checks before or concurrently with a run, plus output checks; a triggered result halts execution. Tracing is a first-class span tree in `src/agents/tracing/`.

**Clade verdict — DIFFERENT by design.** Clade's supervisor/worker boundary is durable project work in isolated git worktrees, not a model-selected conversational delegation; its oracle gates a completed diff/test evidence, rather than policing each message. Clade already has typed child-worker fields (`handoff_type`, `handoff_payload`) and re-spawns a child in `orchestrator/worker.py:_handoff_to_worker`, SQLite task state, JSONL event causality, and `TracingService`. Replacing that with an in-process handoff graph would lose isolation and reviewability. The confirmed deficiency is narrower: Clade's typed handoff payload is JSON injected into a description, with no declared schema/validator or explicit context allowlist; handoff context can therefore be oversized or malformed.

**Steal for Clade.** Add a small handoff registry: `{type -> JSON Schema/Pydantic model, validator, redaction/allowlist, payload-version}`. Validate before task insertion and retain the raw payload in event history, but construct the child prompt from a compact, typed projection. Add optional `handoff_context_filter` semantics so task-file construction can preserve the audit record while limiting successor context. Do **not** copy per-turn output guardrails; retain the oracle as the delivery gate.

### openai/symphony (25963★)

**What it is.** A long-running issue-tracker-to-agent dispatcher, explicitly for per-issue autonomous implementations. Its specification calls it a scheduler/runner, with ticket writing and completion policy left to a repository-owned `WORKFLOW.md` prompt.

**Notable patterns.**

- `SPEC.md` divides policy (`WORKFLOW.md` prompt), typed configuration, coordination, execution, integration, and observability. The workflow file is repository versioned and carries runtime settings, hooks and prompt—not merely instructions.
- Its authoritative runtime state has `running`, `claimed`, retry entries, concurrency limits, token/rate-limit totals, and reconciliation. It deterministically names a per-issue workspace, preserves it across retries, cancels a run that becomes tracker-ineligible, and applies exponential backoff. See `SPEC.md` §§3–5 and the reference `elixir/lib/symphony_elixir/orchestrator.ex`.
- The implementation exposes structured status including retry queue and per-session token information through `elixir/lib/symphony_elixir_web/presenter.ex`, and verifies operational behavior via snapshot and live E2E fixtures (`elixir/test/symphony_elixir/*`). It makes no universal merge/oracle promise: successful work may hand off to Human Review.

**Clade verdict — DIFFERENT by design, with one confirmed operational gap.** Clade already matches the important topology: SQLite task queue + `claim_next_pending`, worker pool, worktrees, queue recovery, tracker/GitHub sync, reactions/event stream, and an oracle/PR gate. Clade is stronger on independent review, verification anchors, fault localization, worker condensers and multi-provider runtime. Symphony's Linear-only daemon and mutable `WORKFLOW.md` are not superior substitutes. The gap is that Clade does not have a single, explicit repository-owned *run contract* that declares the worker policy, eligibility states, retry/backoff and workspace lifecycle together; its policy is split among global settings, task types, skills and server configuration. This makes a deployment's autonomous behavior harder to diff/review or reproduce.

**Steal for Clade.** Introduce an optional, versioned `CLADE_WORKFLOW.md` with typed front matter: intake source/states, max concurrency, retry/backoff, worktree hooks, required verification commands, oracle/auto-merge posture, and the worker-task template. At dispatch, record its Git SHA + normalized config in the task/event span. Keep Clade's SQLite state and oracle; do not replace them with Symphony's in-memory-only restart model or Linear assumption.

### openai/swarm (21798★)

**What it is.** An archived, educational minimal multi-agent library (the README directs production users to Agents SDK). It demonstrates a tiny control loop of agent completion → tool calls → optional agent switch → returned history/context.

**Notable patterns.**

- `swarm/core.py` makes handoff a normal function result: a tool returning an `Agent` changes `active_agent`; a `Result` can simultaneously return tool text, an agent and `context_variables`.
- The engine deep-copies caller messages/context and returns the new messages, active agent and context rather than owning a database; `swarm/types.py` is essentially its entire protocol. This makes the transition explicit and easily unit-tested.
- The current agent's system prompt replaces the previous one while the conversation remains, and `max_turns` bounds the loop. This is a useful didactic reference, not a reliability system.

**Clade verdict — DIFFERENT by design.** Swarm's `Agent` return is a synchronous session-routing primitive; Clade's task-file/typed-worker handoff crosses processes, worktrees and potentially hours. A direct agent handoff has no claim/ownership, persistence, review gate, retries or artifact boundary. Clade's explicit task records are the safer choice for coding work.

**Steal for Clade.** Borrow the *single return contract*, not the runtime: make worker completion/handoff emit one versioned envelope—`{status, summary, artifacts, next_handoff?, context_patch?, blockers}`—then have the pool validate/persist it atomically. This makes `handoff_type` less ad hoc and gives `/pickup`, the web UI and child task-file builder the same source of truth. Do not add model-directed arbitrary worker routing.

### openai/evals (18916★)

**What it is.** The larger legacy/open-source eval framework and registry: declarative YAML/JSONL eval definitions plus custom evaluators, completion-function protocol, reproducible sample execution and event-level records.

**Notable patterns.**

- `evals/eval.py` assigns stable sample IDs, derives a deterministic per-sample seed, shuffles/indexes samples, and runs isolated sample work in parallel. `SolverEval` copies a stateful solver per sample so test cases cannot contaminate one another.
- `evals/record.py` records sampling, function calls, matches, raw samples, metrics and extra data as typed events keyed to the sample; this preserves failure investigation rather than only an aggregate score.
- The registry splits an eval set, base-eval implementation, sample JSONL and metrics (`evals/base.py`, `evals/registry/`). Its Completion Function Protocol lets the same benchmark exercise a tool-using system, not only a bare model.

**Clade verdict — DEFICIENT, but not because it has “no harness.”** Clade already has `orchestrator/evals/`: 20 live-oracle fixtures, offline contract/liveness replays, seven supervisor-parser fixtures, and SWE-bench runners. `orchestrator/evals/README.md` explicitly requires live replays for oracle-prompt changes. The confirmed missing layer is a versioned, system-level task corpus that can run the *whole* Clade loop with seeded/isolated cases and report per-case outcomes over versions. Current oracle fixtures test the judge; SWE-bench is a separate runner; neither gives a standard run record for scheduler → worker → tests → oracle → retry/merge behavior. Live oracle runs are also manual/scheduled, so no baseline/delta is automatically retained for release comparison.

**Steal for Clade.** Create `orchestrator/evals/loop_cases/*.json` plus a manifest: task, fixture repo/ref, setup, expected terminal state, required evidence, cost ceiling and tags. Run each in a fresh worktree with a stable case ID; write JSONL records for dispatch, tool/worker events, test evidence, oracle verdict, retry count, token/cost and terminal state. Produce a baseline/delta report that fails only on declared critical regressions. Start offline/simulated in CI and schedule a small live canary set—matching Clade's existing cost policy. Reuse `event_stream.py`; do not import the old Evals registry wholesale.

### openai/simple-evals (4570★)

**What it is.** A small reference library for benchmark implementations (now frozen for new model results; its README says it remains a reference for HealthBench, BrowseComp and SimpleQA). It emphasizes transparent per-example scoring and reporting rather than a general orchestration platform.

**Notable patterns.**

- `types.py` separates sampler, single-example result (`score`, conversation, metrics, HTML) and aggregate result; implementations can emit both machine metrics and a human-debuggable transcript.
- Deterministic graders parse constrained final answers rather than trusting free-form prose (for example `mmlu_eval.py` and `mgsm_eval.py`).
- HealthBench goes further than “LLM-as-judge”: `healthbench_meta_eval.py` evaluates grader labels against physician labels and reports class-sensitive/F1 plus bootstrap statistics. That is an important model for validating the evaluator itself.

**Clade verdict — DEFICIENT (small, high-signal).** Clade has oracle fixture accuracy thresholds and confidence/severity gates, but no documented oracle calibration set with independent human labels and class-sensitive false-approve/false-reject reporting. A flat fixture pass rate can conceal the dangerous asymmetric error: approving a defective autonomous change.

**Steal for Clade.** Extend the oracle corpus with a small adjudicated calibration split (initially 30–50 historical diffs, human label + severity). Report precision/recall separately for `approve` and `reject`, false-approve rate, and bootstrap interval; require a false-approve ceiling before enabling auto-merge. Keep the existing live replay, and record rubric-version/model-version so score shifts are interpretable. Do not adopt benchmark answer-extraction machinery.

### openai/openai-realtime-agents (6925★)

**What it is.** A demo/reference application for voice agents using the realtime SDK. It shows sequential specialist handoffs and a two-tier chat-agent/supervisor architecture optimized for conversational latency.

**Notable patterns.**

- The chat-supervisor demo has a cheap, fast front agent allowed to answer only a narrow allowlist; all non-trivial decisions call a stronger supervisor tool. See `src/app/agentConfigs/chatSupervisor/index.ts` and `supervisorAgent.ts`. The front agent immediately preserves UX with a holding response while the supervisor reasons/calls tools.
- Specialist edges are explicit agent graphs, not free-form discovery: `simpleHandoff.ts` and `customerServiceRetail/index.ts` enumerate allowed handoffs. Prompts encode state-machine milestones (authentication before route) and transfer rationale/context.
- Output moderation is separately wired in `src/app/App.tsx` and `agentConfigs/guardrails.ts`, including UI states while a streamed answer is still in progress.

**Clade verdict — N-A for the realtime design; DIFFERENT for the transferable part.** Latency masking, voice turn-taking and response moderation do not apply to autonomous coding loops. Clade already has a supervisor plan plus worker execution and an oracle after artifacts exist; the voice repo's supervisor is an answer generator, not an independent reviewer. The transferable idea—explicit capability boundaries—is partly present in Clade task-type tool subsets but not consistently rendered as a visible transition graph.

**Steal for Clade.** Add a declared worker phase graph (`plan → implement → verify → oracle → repair|done|blocked`) with permitted tools, evidence required to cross each edge, and a recorded `transition_reason`. This is an observability/guardrail improvement, not an LLM-chosen graph: enforce it in the pool/task queue and render it in the event stream/UI. It will make rejected/repair loops diagnosable without importing voice-agent patterns.

### openai/harmony (4454★)

**What it is.** The Rust/Python/JS renderer-parser for the gpt-oss Harmony response format. It turns typed conversations (roles, authority tiers, channels, tool namespaces and function calls) into model tokens and parses completion tokens back to structured messages.

**Notable patterns.**

- `src/chat.rs` makes `SystemContent` and `DeveloperContent` structured types, including channel requirements, reasoning effort and tool configuration, rather than concatenated prompt strings.
- `src/encoding.rs` is a symmetric renderer/parser. It rejects authority/content misuse (for example, system content in a non-system message) and has explicit completion/training rendering paths.
- The suite tests round trips and malformed cases (`src/tests.rs`); Python mirrors the Rust API in `python/openai_harmony/__init__.py`. The core lesson is loss-resistant structured protocol plus dual implementation parity, not the token format itself.

**Clade verdict — DIFFERENT by design.** Harmony is mandatory wire formatting for gpt-oss inference; Clade delegates message rendering to Claude Code/Codex subprocesses and must not interpose a foreign token protocol. Clade already has structured task DB fields, typed handoff payloads, JSONL events, a structured `/handoff`, and condensers. The confirmed deficiency is boundary inconsistency: some worker/supervisor output is still parsed from prose/Markdown or regex-extracted JSON (the existing supervisor eval even pins parser weaknesses), so its internal protocol is less schema-first than its task DB.

**Steal for Clade.** Define a versioned internal `WorkerEnvelope` JSON schema for supervisor task plans, worker terminal reports, oracle evidence and condenser summaries; validate at producer and consumer, retain raw payload + schema version, and use a single renderer for task-file/PR/UI views. Add round-trip and backward-compatibility fixtures, mirroring Harmony's renderer/parser discipline. Do not adopt Harmony itself unless Clade directly hosts gpt-oss.

## Bottom line

The strongest concrete builds are (1) schema-validated handoffs/envelopes, (2) repository-versioned workflow policy with a recorded SHA, (3) an end-to-end loop corpus with per-case records/deltas, and (4) oracle calibration that measures false approves separately. Symphony validates Clade's overall worktree-loop topology; the SDK/Swarm/realtime repos mostly operate at a deliberately different conversational or voice-runtime layer.
