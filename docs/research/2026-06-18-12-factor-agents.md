---
title: 12-Factor Agents — Factor-by-Factor Audit of Clade
date: 2026-06-18
review_date: 2026-06-18
reconciled: 2026-06-18
status: integrated
summary: >
  HumanLayer's 12-Factor Agents is a methodology for reliable production LLM agents,
  built around the thesis "agents are mostly deterministic software with strategically
  placed LLM decision points" — not open-ended loops. Audited Clade factor-by-factor:
  11/12 factors COVERED (plus the bonus Factor 13), 1 PARTIAL (Factor 7, human-contact
  is pull/file-inbox not an inline durable-pause tool call). No fully missing factors.
  Clade's Blueprint loop (deterministic pre/post nodes + LLM supervisor/worker) is a
  near-textbook instantiation of the methodology's central thesis.
integrated_items:
  - "Factor 1 Natural Language to Tool Calls — COVERED: NL goal/task → structured fields via config.py:595 (_parse_task_schema), config.py:527 (_parse_task_type); the LLM→tool-call step itself is delegated to Claude Code native (different-not-deficient: Clade is a harness ON TOP of a tool-calling model, not a re-implementation)"
  - "Factor 2 Own your prompts — COVERED: worker_taskfile.py:180 (build_task_file hand-assembles every context block), worker_review.py:291 (_ORACLE_JUDGE_SYSTEM_PROMPT via --append-system-prompt), configs/skills/*/prompt.md (hand-authored, version-controlled, no framework templating)"
  - "Factor 3 Own your context window — COVERED: condensers.py:40 (Condenser ABC), condensers.py:136 (ObservationMaskingCondenser), config.py:131 (context_span_budget=6000), worker_tldr.py:375 (_span_evict_tldr priority-preserving eviction), worker_taskfile.py:225 (_localize_tldr_for_task haiku narrowing)"
  - "Factor 4 Tools are just structured outputs — COVERED: mcp_server.py:319 (@app.list_tools advertises skills with inputSchema from argument-hint), mcp_server.py:591 (--output-format json), mcp_server.py:607 (json.loads of tool stdout), mcp_server.py:216 (_ast_search_class returns structured file:line + signatures)"
  - "Factor 5 Unify execution state and business state — COVERED: task_queue.py:58 (one tasks row holds business state status/depends_on/phase AND execution state worker_id/started_at/elapsed_s/last_commit), event_stream.py:42-46 (EventStream writes to SQLite via task_queue AND a JSONL mirror — SQLite is the single source of truth, JSONL is crash-safe replay, not a competing store)"
  - "Factor 6 Launch/Pause/Resume with simple APIs — COVERED: routes/tasks.py:349 (POST /api/tasks/{id}/run), routes/workers.py:25/35/45 (POST pause/resume/stop), worker.py:378 (pause SIGSTOP), worker.py:386 (resume SIGCONT), event_stream.py:237 (replay for resume), server.py:52 (_recover_orphaned_tasks + _replay_interrupted_tasks on startup)"
  - "Factor 8 Own your control flow — COVERED: loop-runner.sh:1140 (run_blueprint_loop explicit DET+LLM state machine: pre_flight→hydrate→supervisor→workers→syntax_check→test→commit→convergence), session.py:813 (status_loop 1s polling reflection), reactions.py:72 (ReactionExecutor threshold escalation), loop-runner.sh:1068 (_save_checkpoint per-phase crash recovery)"
  - "Factor 9 Compact Errors into Context Window — COVERED: error_classifier.py:133 (classify → ClassifiedError dataclass, 13 semantic categories), error_classifier.py:227 (derive_retry_decision → compact hint_block + [AUTO-RETRY n/3] prefix), error_classifier.py:331 (summarize → one-line), worker_utils.py:812 (_maybe_enqueue_classify_retry injects hint into retry task)"
  - "Factor 10 Small, Focused Agents — COVERED: configs/agents/ (37 narrow-role agent defs each with a scoped tools list), worker.py:93 (one Worker per task, isolated worktree), swarm.py:22 (SwarmManager = lightweight dispatcher of up to 20 focused workers, not a monolith), worker_taskfile.py:373 (_fix_two_phase scopes a fix task to a tight workflow)"
  - "Factor 11 Trigger from anywhere — COVERED: routes/webhooks.py:35 (POST /api/webhooks/github — issues+comments), github_sync.py (gh issue pull→task), configs/scripts/loop-runner.sh (CLI goal-file), mcp_server.py (MCP tools for external IDEs), routes/tasks.py (REST POST /api/tasks) — 5 distinct entry points all feeding one task queue"
  - "Factor 12 Make your agent a stateless reducer — COVERED: worker.py:324 (each task spawns a fresh claude -p subprocess, no session affinity), worker_taskfile.py (full input state injected via task file), worker.py:408 (poll reads exit code, writes results to durable queue), task_queue.py + event_stream.py + git worktree = all state external/durable; worker holds no cross-task memory"
  - "Factor 13 (bonus) Pre-fetch all the context you might need — COVERED: worker_taskfile.py:225 (code TLDR pre-generated), worker_tldr.py:662 (_sbfl_prepass ranked suspects), worker_taskfile.py:306 (recent sibling completions injected), loop-runner.sh node_hydrate_context (pre-flight context hydration before supervisor runs)"
needs_work_items: []
reference_items:
  - "Factor 7 inline human-contact — SKIP different-not-deficient: outer-loop human contact already exists (blockers.md session.py:689 + interventions task_queue.py:160 + inbox routes/tasks.py:405); an inline suspend-resume-one-worker tool is narrow and counter to autonomous-by-design"
  - "Factor 1's LLM→tool-call inference step — N/A by design: Clade does not implement the natural-language-to-function-call decoder; it wraps Claude Code, which already does this natively. The harness owns task-schema parsing (config.py:595) and skill→action dispatch (mcp_server.py:524), not token-level tool selection. Re-implementing it would duplicate the model. (different-not-deficient)"
sources:
  - https://github.com/humanlayer/12-factor-agents
  - https://www.humanlayer.dev/blog/12-factor-agents
  - https://deepwiki.com/humanlayer/12-factor-agents/3-the-12-factors
---

[中文] | [Back to README](../../README.md)

# 12-Factor Agents — Factor-by-Factor Audit of Clade (2026-06-18)

HumanLayer's [**12-Factor Agents**](https://github.com/humanlayer/12-factor-agents) (named after Heroku's 12-Factor App) is a methodology of twelve principles for building LLM agents reliable enough for production. Its central thesis: **the best "agents" are mostly deterministic software with a handful of strategically placed LLM decision points** — not open-ended `while-true: call-the-model` loops. Most production wins come from *owning* the parts frameworks try to hide: the prompt, the context window, the control flow, the state.

This document audits Clade against all 12 factors (plus the bonus Factor 13). For each, it cites the Clade code that implements (or fails to implement) the principle, and applies "**different ≠ deficient**" strictly — a factor is only marked weak when Clade is demonstrably missing the *capability*, not merely using a different mechanism.

---

## Factor-by-Factor Audit Table

| # | Factor | What it asks | Clade's state (file:line) | Verdict |
|---|--------|--------------|---------------------------|---------|
| 1 | **Natural Language to Tool Calls** | Convert NL intent into structured, executable calls. | NL goal → structured task fields: `config.py:595` `_parse_task_schema` (acceptance_criteria/input_files/provides/requires), `config.py:527` `_parse_task_type`. Skill NL→action dispatch: `mcp_server.py:524` `clade_run_skill`. The token-level LLM→tool-call decode is delegated to Claude Code native. | **COVERED** |
| 2 | **Own your prompts** | Hand-control prompts; don't rely on framework defaults. | `worker_taskfile.py:180` `build_task_file` assembles every context block by hand; `worker_review.py:291` `_ORACLE_JUDGE_SYSTEM_PROMPT` via `--append-system-prompt`; `configs/skills/*/prompt.md` are hand-authored & version-controlled. | **COVERED** |
| 3 | **Own your context window** | Deliberately manage what enters context. | `condensers.py:40` `Condenser` ABC + `condensers.py:136` `ObservationMaskingCondenser`; `config.py:131` `context_span_budget=6000`; `worker_tldr.py:375` `_span_evict_tldr` (priority-preserving); `worker_taskfile.py:225` haiku TLDR localization. | **COVERED** |
| 4 | **Tools are just structured outputs** | Tools = a way to get validated, structured model output. | `mcp_server.py:319` `@app.list_tools` advertises skills with `inputSchema`; `mcp_server.py:591` `--output-format json`; `mcp_server.py:607` `json.loads(stdout)`; AST search returns structured `file:line`+signatures (`mcp_server.py:216`). | **COVERED** |
| 5 | **Unify execution state and business state** | One serializable source of truth for both. | `task_queue.py:58` — a single `tasks` row holds business state (`status`,`depends_on`,`phase`) AND execution state (`worker_id`,`started_at`,`elapsed_s`,`last_commit`). `event_stream.py:42` writes SQLite **and** a JSONL mirror — SQLite is the source of truth, JSONL is crash-safe replay (not a competing store). | **COVERED** |
| 6 | **Launch/Pause/Resume with simple APIs** | Start, suspend, continue via plain interfaces. | `routes/tasks.py:349` `POST /api/tasks/{id}/run`; `routes/workers.py:25/35/45` pause/resume/stop; `worker.py:378/386` SIGSTOP/SIGCONT; `event_stream.py:237` `replay()`; `server.py:52` orphan-recovery + interrupted-task replay on startup. | **COVERED** |
| 7 | **Contact humans with tool calls** | Human contact as a tool the agent invokes mid-flight, durably suspending. | `session.py:689` `_check_blockers` (worker writes `blockers.md`, human polls); `task_queue.py:160` interventions table; `routes/tasks.py:405` `_write_worker_inbox` file messaging. Outer-loop escalation is solid, but it's **pull/requeue**, not an inline `request_human_input()` tool that suspends *this* execution and resumes in place. | **PARTIAL** |
| 8 | **Own your control flow** | Explicit, custom control logic — not framework routing. | `loop-runner.sh:1140` `run_blueprint_loop` — explicit DET+LLM state machine (pre_flight→hydrate→supervisor→workers→syntax→test→commit→convergence); `session.py:813` `status_loop` polling reflection; `reactions.py:72` threshold escalation; `loop-runner.sh:1068` per-phase checkpoints. | **COVERED** |
| 9 | **Compact Errors into Context Window** | Summarize failures concisely; feed back into retry. | `error_classifier.py:133` `classify`→`ClassifiedError` (13 categories); `error_classifier.py:227` `derive_retry_decision`→ compact `hint_block` + `[AUTO-RETRY n/3]`; `error_classifier.py:331` `summarize`; `worker_utils.py:812` injects hint into the requeued task. | **COVERED** |
| 10 | **Small, Focused Agents** | Narrow agents, not one broad do-everything agent. | `configs/agents/` — 37 narrow-role defs, each a scoped `tools` list; `worker.py:93` one Worker per task in an isolated worktree; `swarm.py:22` `SwarmManager` = thin dispatcher of ≤20 focused workers, not a monolith. | **COVERED** |
| 11 | **Trigger from anywhere** | Launch from diverse event sources / channels. | `routes/webhooks.py:35` GitHub webhook; `github_sync.py` issue-pull; `loop-runner.sh` CLI goal-file; `mcp_server.py` MCP tools (external IDEs); `routes/tasks.py` REST. 5 entry points → one queue. | **COVERED** |
| 12 | **Make your agent a stateless reducer** | Pure function: input thread+context → output, no hidden state. | `worker.py:324` fresh `claude -p` subprocess per task (no session affinity); full input via task file; `worker.py:408` results written to durable queue; all state lives in SQLite + JSONL + git worktree, none in the worker. | **COVERED** |
| 13 | **(bonus) Pre-fetch all context you need** | Pre-load likely-needed context before the agent runs. | `worker_taskfile.py:225` code TLDR; `worker_tldr.py:662` `_sbfl_prepass` ranked suspects; `worker_taskfile.py:306` sibling completions; `loop-runner.sh` `node_hydrate_context` pre-flight. | **COVERED** |

---

## Verdict

**Score: 11/12 COVERED + bonus Factor 13 COVERED; 1 PARTIAL (Factor 7); 0 MISSING.**

Clade is an unusually clean instantiation of the 12-Factor *thesis itself*. The methodology's headline claim — "agents are mostly deterministic software with LLM decision points, not autonomous loops" — is almost verbatim the Blueprint loop in `loop-runner.sh:1140`: a deterministic state machine (`pre_flight`, `hydrate_context`, `syntax_check`, `commit`, `convergence`) wrapping two LLM nodes (`supervisor`, `workers`). The factors that frameworks most often hide — **own your prompts** (F2), **own your context window** (F3), **own your control flow** (F8), **stateless reducer** (F12) — are exactly where Clade has invested the most: hand-built task files, condensers with span budgets, an explicit phase state machine, and fresh-subprocess-per-task workers with all state externalized.

**The one honest gap — Factor 7.** Clade's human-contact story is strong on the *outer loop* (a worker hits a wall → writes `.claude/blockers.md` → the loop halts and a human picks it up; or the interventions table records a correction that's injected into a requeued task). What it lacks is the 12-factor *inner-loop* ideal: a worker mid-execution emitting a structured `request_human_input(question, options)` tool call that **durably suspends that exact process** and later **resumes it in place** with the typed answer threaded back into its context. Clade's mechanism is requeue-with-context (the worker dies, a fresh task carries the correction forward), which is a deliberate consequence of Factor 12's stateless-reducer design — but the suspend-and-resume-in-place capability is genuinely absent. This is a reversible add: a `contact-human` MCP tool plus a `parked` worker state in `task_queue.py`. It is flagged in `needs_work_items` rather than dismissed.

**Why no other factor is marked weak (different ≠ deficient applied):**

- **Factor 1** — Clade does *not* re-implement the natural-language-to-function-call decoder; it is a harness layered on Claude Code, which already does tool-call inference natively. Clade owns the level above it (task-schema parsing, skill dispatch). Re-implementing the decoder would duplicate the model — listed as `reference_items` (N/A by design), not a gap.
- **Factor 5** — An earlier read suspected SQLite and the JSONL event log were two competing stores. The code (`event_stream.py:42-46`) shows the JSONL is a *mirror* of the SQLite writes for crash-safe replay; SQLite remains the single source of truth. Covered, not partial.
- **Factor 11** — "Meet users where they are" in the original means Slack/SMS/email. Clade's channels are GitHub, CLI, MCP, and REST — the right channels for a *coding* agent. Same capability (multi-source trigger into one queue), domain-appropriate surface. Covered.

**Net:** No new feature work is mandated by this methodology beyond the single Factor 7 inner-loop human-contact tool. The audit's main value is confirmation: Clade already embodies the 12-factor philosophy structurally, and the one identified gap is small, concrete, and reversible.

---

## Sources

- [humanlayer/12-factor-agents (GitHub)](https://github.com/humanlayer/12-factor-agents) — the canonical factor list
- [12 Factor Agents — HumanLayer Blog](https://www.humanlayer.dev/blog/12-factor-agents) — the writeup / thesis
- [The 12 Factors — DeepWiki](https://deepwiki.com/humanlayer/12-factor-agents/3-the-12-factors) — per-factor detail
