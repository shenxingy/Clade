---
name: Frontier Update — What's New Since 2026-06-13
date: 2026-07-15
status: needs_work
review_date: 2026-07-15
summary: >
  Re-sweep of the who-to-learn-from watch-list for developments since the last
  review (2026-06-13). Most important: (1) Anthropic's "Harness design for
  long-running apps" — clean context RESET + structured handoff beats compaction
  for long work, and evaluator value is task/model-dependent (make reset-with-
  handoff a first-class loop mode; measure evaluator lift per model). (2) ACP
  (Agent Client Protocol) is becoming the control-plane boundary — Goose
  v1.38-1.43 fully migrated (permissions, durable session state, per-message cost
  telemetry, cancellation); OpenHands + OpenCode ACP-facing. (3) Cognition SWE-1.7
  (long-horizon async) + "Fable cheaper than Opus" — a lead model + cheaper
  delegated sidekick beats optimizing lead-model token price (topology, not
  price). Also: Warp evaluator-driven skill-optimization loop, Factory
  event-triggered loops + persistent runbook, Amp Orbs (agent-ready remote
  worktree image), OpenHands run-budgets/trace-attribution/interrupt/bounded-
  concurrency, Addy Osmani correlated-blindspot judges + machine stop criteria,
  Armin Ronacher preserve architecture vocabulary in handoffs. Quiet since June:
  Huntley, 12-factor-agents, Aider, Mitchell Hashimoto.
sources:
  - https://www.anthropic.com/engineering/harness-design-long-running-apps
  - https://github.com/aaif-goose/goose
  - https://github.com/OpenHands/OpenHands
  - https://cognition.ai/blog/making-fable-cheaper-than-opus
  - https://www.warp.dev/blog/building-a-skill-optimization-loop
  - https://www.factory.ai/news/incident-response
  - https://ampcode.com/news/agents-in-orbs
  - https://github.com/vercel/ai
integrated_items: []
needs_work_items:
  - "Reset-with-structured-handoff as a first-class loop mode (clean context reset + typed handoff > compaction for long runs); measure marginal lift of evaluator stages per model (Anthropic harness-design, Mar 2026)"
  - "ACP watch/compat: mirror explicit capability discovery, cancellation, durable session state, and per-message cost telemetry (Goose v1.43 / OpenHands / OpenCode)"
  - "Model-topology optimization: benchmark lead + cheaper-sidekick delegation mixes on Clade's OWN tasks, not lead-model token price (Cognition Fable+sidekick: $1.86/60.7 vs Opus $2.04/54.6)"
  - "Evaluator-driven skill-optimization loop: held-out tasks + a separate grader iteratively improve a skill, vs treating skills as static prompts (Warp)"
  - "Run budgets + trace attribution (repo+harness+model) + interrupt endpoint + bounded tool concurrency as orchestration primitives (OpenHands 1.11.0)"
  - "Judge independence/diversity (tests + static checks + a different model or constrained rubric) to break correlated writer/reviewer blind spots + machine-checkable stop criteria for unattended goals (Addy Osmani)"
  - "Handoffs/skills must preserve architecture vocabulary, invariants, and ownership rationale — not just a progress log + next action (Armin Ronacher, The Tower Keeps Rising)"
  - "Agent-ready reproducible worktree image + proof-producing browser/test tooling as a prerequisite for scalable background workers (Amp Orbs / Factory)"
---

<!-- Research by 1 codex worker, 2026-07-15. Only NEW-since-2026-06-13 items; "no notable change" sources omitted from the needs_work rollup. -->

## What's new since 2026-06-13 (by source)

### Anthropic Engineering

- **New**: [Harness design for long-running application development](https://www.anthropic.com/engineering/harness-design-long-running-apps) (2026-03-24, surfaced as the important post after the prior review) reports a planner/generator/evaluator architecture; most importantly, it found clean context resets plus a structured handoff superior to compaction for long work, and says evaluator value is task/model-capability dependent rather than permanent harness furniture.
- **Matters for Clade?**: **yes** — make reset-with-handoff a first-class loop mode, and measure the marginal lift of evaluator stages as models change. [Managed Agents](https://www.anthropic.com/engineering/managed-agents) also argues for stable session/harness/sandbox interfaces while harness policies evolve.

### Geoffrey Huntley

- **New**: no notable change after 2026-06-13 on the public site; the latest front-page material remains the existing loop/Ralph-oriented work.
- **Matters for Clade?**: **no** — keep the source on watch, but no new practice to absorb.

### HumanLayer / Dexter Horthy — 12-factor-agents

- **New**: no notable change: the [repository](https://github.com/humanlayer/12-factor-agents) shows no releases or commits since the cutoff.
- **Matters for Clade?**: **no**.

### SST OpenCode

- **New**: OpenCode (now [anomalyco/opencode](https://github.com/anomalyco/opencode)) shipped rapid v1.17.6–v1.18.1 releases through July 14. The material change is its Desktop v2/session work: per-server permission state, remote-session permission auto-accept, persistent review state and improved sub-agent/session timeline UX ([v1.18.0](https://github.com/anomalyco/opencode/releases/tag/v1.18.0)).
- **Matters for Clade?**: **yes** — treat permission policy and review state as properties of a remote session/agent-server, not global UI toggles; its continued ACP-facing work is a compatibility signal.

### OpenHands / All-Hands-AI

- **New**: [OpenHands 1.11.0](https://github.com/OpenHands/OpenHands/releases/tag/1.11.0) (2026-07-09) adds agent profiles plus budget/usage dashboards. Recent commits add a parallel-tool-call concurrency limit, task/sub-agent visualizer, pause via interrupt endpoint, ACP agent settings/MCP configuration, and repository metadata in observability traces.
- **Matters for Clade?**: **yes** — adopt explicit run budgets, trace attribution (repo + harness + model), interruption, and bounded tool concurrency as orchestration primitives.

### Aider

- **New**: no notable change: [Aider releases](https://github.com/Aider-AI/aider/releases) contain nothing after the cutoff.
- **Matters for Clade?**: **no**.

### SWE-agent / mini-swe-agent

- **New**: [mini-swe-agent v2.4.2–v2.4.5](https://github.com/SWE-agent/mini-swe-agent/releases/tag/v2.4.5) (June 18–July 6) are maintenance releases; the meaningful robustness fix is not treating malformed tool calls as context truncation. The main [SWE-agent](https://github.com/SWE-agent/SWE-agent) has only small multimodal/config/docs fixes.
- **Matters for Clade?**: **yes, small** — classify malformed tool calls separately from truncation/retry exhaustion so recovery policies do not hide protocol defects.

### Cognition / Devin

- **New**: [SWE-1.7](https://cognition.ai/blog/swe-1-7) (2026-07-08) is explicitly trained for long-horizon asynchronous work. [Making Fable Cheaper Than Opus](https://cognition.ai/blog/making-fable-cheaper-than-opus) (2026-07-13) reports that a lead model plus cheaper delegated “sidekick” can reduce end-to-end cost while improving score: Fable+sidekick $1.86/60.7 vs Opus+sidekick $2.04/54.6 on their FrontierCode 1.1 experiment.
- **Matters for Clade?**: **yes** — model selection should optimize whole orchestration topology, not lead-model token price; benchmark high/low model delegation mixes in Clade’s own tasks.

### Factory.ai

- **New**: [Incident Response](https://www.factory.ai/news/incident-response) (2026-07-10) turns Slack alerts into autonomous RCA sessions on a Droid computer, with a persistent runbook memory and optional fix preparation. [Desktop Droid](https://www.factory.ai/news/working-with-droid-in-the-desktop-app) (2026-07-07) expands an agent across Desktop work without leaving its environment.
- **Matters for Clade?**: **yes** — the durable artifact is event-triggered loop runs plus a per-domain persistent runbook, not the product UI.

### Warp

- **New**: Warp’s direction is explicitly “cloud software factories.” Its [skill optimization loop](https://www.warp.dev/blog/building-a-skill-optimization-loop) (2026-06-18) uses an automated computer-use grader to iteratively improve a skill; its [spec-driven factory skill](https://www.warp.dev/blog/how-to-build-a-cloud-software-factory-add-spec-driven-development-skills) (2026-06-29) and [factory guide](https://www.warp.dev/blog/a-guide-to-cloud-software-factories-for-engineering-leaders) (2026-07-07) operationalize triage/spec/implementation/validation as reusable skills.
- **Matters for Clade?**: **yes** — add a testable skill-evaluation/improvement loop, with held-out tasks and a separate grader, rather than treating skills as static prompts.

### Simon Willison

- **New**: [July 13’s Datasette code-frequency note](https://simonwillison.net/2026/Jul/13/datasette-code-frequency/) is a concrete operator observation: code-change volume jumped with current coding agents/models (Opus 4.8, GPT-5.5, Fable 5, GPT-5.6 Sol).
- **Matters for Clade?**: **yes, small** — reinforces that review/verification throughput, not agent generation, is the scaling bottleneck.

### Armin Ronacher

- **New**: [The Tower Keeps Rising](https://lucumr.pocoo.org/2026/7/13/the-tower-keeps-rising/) (2026-07-13) warns that vibecoding can erode the project’s shared conceptual language; [Better Models: Worse Tools](https://lucumr.pocoo.org/2026/7/4/better-models-worse-tools/) (2026-07-04) is a related tool-quality critique.
- **Matters for Clade?**: **yes** — handoffs/skills should preserve architecture vocabulary, invariants, and ownership rationale, not just a progress log and next action.

### Mitchell Hashimoto

- **New**: no notable agentic-coding development after the cutoff; the newest post is [Pledging Another $400,000 to the Zig Software Foundation](https://mitchellh.com/writing/zig-donation-2026) (2026-06-21).
- **Matters for Clade?**: **no**.

### Addy Osmani

- **New**: [Agentic Code Review](https://addyosmani.com/blog/agentic-code-review/) (2026-06-15) cautions that writer/reviewer/judge loops have correlated blind spots. [Agentic Autonomy Levels](https://addyosmani.com/blog/agentic-autonomy-levels/) (2026-07-02) frames autonomy separately by agent scope and orchestration scale, with measurable stopping conditions as the requirement for high autonomy.
- **Matters for Clade?**: **yes** — introduce independence/diversity in judge evidence (tests, static checks, different model or constrained rubric) and require machine-checkable stop criteria for unattended goals.

### Boris Cherny / Thorsten Ball (Amp)

- **New**: Amp launched [Agents in Orbs](https://ampcode.com/news/agents-in-orbs) (2026-06-30), remote fresh hosted machines; [Putting an Agent in an Orb](https://ampcode.com/notes/putting-an-agent-in-an-orb) (2026-07-02) shows the enabling harness: a prepared, documented, agent-friendly headless repo/environment can produce screenshots and full-flow proof. [Agents, Anywhere](https://ampcode.com/news/agents-anywhere) (2026-07-08) lets a local `amp` installation create remote threads.
- **Matters for Clade?**: **yes** — a reproducible “agent-ready worktree” image plus proof-producing browser/test tooling is a prerequisite for scalable background workers.

### Vercel AI SDK — HarnessAgent

- **New**: The [AI SDK repository](https://github.com/vercel/ai) has heavily iterated its `@ai-sdk/harness`/workflow-harness adapters since June: sandbox abstraction and resume tests, active/inactive tool filtering, adapter-specific Codex/Claude Code/OpenCode fixes, approval handling, step-numbered telemetry, and CLI relay behavior. Recent release [1.0.33](https://github.com/vercel/ai/releases/tag/%40ai-sdk/workflow-harness%401.0.33) is patch-only, but the commit stream establishes a multi-harness adapter layer as a live product.
- **Matters for Clade?**: **yes** — keep Clade’s supervisor protocol separate from provider/harness adapters; standardize lifecycle events, tool filtering/approval and resumable sandbox bridges.

### Block Goose

- **New**: Goose (now [aaif-goose/goose](https://github.com/aaif-goose/goose)) v1.38–v1.43 completed a major ACP migration: Desktop talks to ACP directly; permissions, session extensions, skills, scheduler, steering, model/provider configuration, durable session state and reconnect-after-sleep are ACP-backed. [v1.43.0](https://github.com/aaif-goose/goose/releases/tag/v1.43.0) also adds per-message cost/token/latency accounting and bounds code-mode execution with timeout/cancellation.
- **Matters for Clade?**: **yes** — ACP is becoming the control-plane boundary to watch; mirror its explicit capability discovery, cancellation, durable session state, and per-message cost telemetry.

### Sonar Foundation Agent (ex-AutoCodeRover)

- **New**: no notable verified change. The named `sonar-source/sonar-foundation-agent` repository endpoint is not public/does not resolve; no release or SWE-bench movement was found under that identifier.
- **Matters for Clade?**: **no** — do not add an inference based on the historical AutoCodeRover name.

## New entries worth adding to the watch-list (if any)

- **ACP ecosystem / Goose** — ACP is moving from a connector experiment to the control plane for session lifecycle, capabilities, permissions, steering and durable state; monitor compatibility and spec changes.
- **Warp Oz / cloud software factories** — the strongest new public source for evaluator-driven skill optimization and spec/triage/validation skill pipelines.
- **Vercel AI SDK Harness** — adapter-layer reference implementation for running Codex/Claude Code/OpenCode under a common stream, sandbox and approval contract.
- **Factory Incident Response** — concrete event-triggered autonomous loop plus persistent domain runbook pattern.
