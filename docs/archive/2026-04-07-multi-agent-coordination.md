---
topic: Anthropic Multi-Agent Coordination Patterns (2025)
date: 2026-04-07
status: needs_work
sources:
  - https://www.anthropic.com/engineering/multi-agent-research-system
  - https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/ai-agent-design-patterns
  - https://galileo.ai/blog/multi-agent-coordination-strategies
---

[English] | [Back to README](../../README.md)

# Anthropic Multi-Agent Coordination Patterns (2025)

## Overview

Anthropic's production multi-agent systems operate on a proven **orchestrator-worker** pattern: a lead agent (Opus 4.6) coordinates 3-5 parallel subagents (Sonnet 4). Performance data shows this architecture outperforms single-agent Opus by 90%+ on research-grade tasks. Token overhead is ~15x vs single-agent chat, but parallelization cuts wall time and output quality improves.

Multi-agent is justified when:
1. Context pollution is a problem (parallel workers stay in narrower contexts)
2. Workload is parallelizable (independent subtasks)
3. Tool specialization needed (15+ tools per agent)

Clade's WorkerPool + SwarmManager already implements the basic pattern. The gaps are in coordination **discipline**: no context versioning, no token budgets, no explicit handoff schemas.

## Core Patterns

### Pattern 1: Hierarchical Orchestrator-Worker

Lead agent decomposes work → spawns parallel workers → collects + synthesizes results.

**Decompose by context boundary, not problem type.**

| ❌ Decompose by phase | ✅ Decompose by domain |
|---|---|
| Planning → Implementation → Testing | Auth module (design + tests + edges) |
| Research → Writing → Editing | API layer (contracts + validation + errors) |
| Gather → Analyze → Summarize | Data layer (schema + queries + migrations) |

Phase decomposition creates handoff failures. Domain decomposition keeps context self-contained.

### Pattern 2: Explicit Handoff Schemas (Not Prose)

Current Clade: task description passed as unstructured markdown.

Anthropic recommended: versioned JSON envelope with explicit contracts:

```json
{
  "task_id": "auth-worker-1",
  "context_version": 3,
  "input": { "file_paths": ["src/auth.ts"], "constraints": ["no deps added"] },
  "expected_output": { "changed_files": [], "test_results": {} },
  "token_budget": 45000
}
```

This enables orchestrator-level validation: did worker touch only the expected files? Did tests pass? Is context version current?

### Pattern 3: Verification Subagent

Dedicated verification worker that runs the full test suite (not smoke tests). Minimal context needed — just the changed files and test command.

**Key property**: verification must be explicitly complete. Smoke tests that "pass" while prod-breaking tests are skipped are worse than no verification.

### Pattern 4: Context Archival After Worker Completion

After each worker completes, summarize its outputs to 1-3 key facts, archive full context to disk, drop from active orchestrator context. Workers retrieve summaries on demand.

This prevents "context rot" — accumulated partial conclusions diluting high-signal facts over long orchestrations.

## Failure Modes

### Circular Dependencies (Deadlock)

Agent A waits for B → B delegates back to A → 17x token explosion.

**Mitigation**: max 2 delegation hops; pre-compute dependency DAG at decomposition time; fail if cycles detected.

### Stale State / Context Desync

Worker A updates shared state; Worker B started before seeing the update.

**Mitigation**: version all shared state; workers check version before acting; orchestrator increments after each batch; fail fast on version mismatch.

### Context Rot

Agents accumulate stale reasoning, partial conclusions, old assumptions.

**Mitigation**: at each handoff, summarize previous worker outputs to 1-3 facts; archive full context to file; maintain sliding window of active tasks only.

### Incomplete Synchronization

Orchestrator spawns A, B, C in parallel but moves on after A completes, missing B and C.

**Mitigation**: explicit barrier operations (await all spawned workers); log all spawns + completions; timeout alert if any worker missing after N minutes.

## Gaps vs Clade's SwarmManager

### §Gap 1 — No Context Versioning

**Current**: Workers share state loosely. No version check → stale state propagates silently.

**Fix**: Add `context_version: int` to task metadata. Increment after each worker batch. Workers that get stale context fail fast with a clear error.

**Effort**: Medium. Requires new DB column + orchestrator version management.

### §Gap 2 — No Token Budget Per Worker

**Current**: Workers can consume unlimited tokens. No budget → runaway agents possible.

**Fix**: `token_budget` field per task. Monitor actual usage from `_parse_token_usage()`. Kill worker if budget exceeded. Log overages to task notes.

**Effort**: Small. `_parse_token_usage` already exists; add mid-run monitoring + budget enforcement.

### §Gap 3 — Prose Handoffs, No Validation

**Current**: Task description is unstructured text. No contract → orchestrator can't verify worker did the right thing.

**Fix**: For swarm tasks, use JSON task envelope with `input_schema` + `expected_output_schema`. Orchestrator validates after completion.

**Effort**: Medium. New task type + schema validation.

### §Gap 4 — No Context Archival

**Current**: Completed worker context stays in orchestrator memory.

**Fix**: After worker completes, call haiku to generate 1-sentence summary. Store in `task.notes`. Archive full log. Subsequent workers receive compact history.

**Effort**: Small. Haiku call after `verify_and_commit()`; write to task notes via `task_queue.update()`.

### §Gap 5 — SwarmManager Lacks Sync Barrier

**Current**: SwarmManager may not explicitly await all parallel workers before synthesis.

**Fix**: Add explicit `asyncio.gather(*workers)` barrier. Log all spawns + completions. Alert if any worker missing after `task_timeout`.

**Effort**: Small. Code review + barrier insertion.

### §Gap 6 — No Circular Dependency Detection

**Current**: No DAG validation at task decomposition time. Long chains possible.

**Fix**: When SwarmManager receives a batch of subtasks, build dependency graph. Reject if cycles detected. Track delegation depth — fail if > 2.

**Effort**: Small. Graph check on task list before spawn.

## Key Actionable Items

1. **§Gap 4 (context archival) — highest value/effort**: After worker completes, haiku generates 1-sentence summary → stored in `task.notes`. Orchestrator injects compact history for subsequent workers. Small code change, immediate quality win.

2. **§Gap 5 (sync barrier)**: Audit SwarmManager to ensure all parallel workers are gathered before orchestrator continues. May already be correct — needs code review.

3. **§Gap 2 (token budget)**: Add `token_budget` to task schema. Use existing `_parse_token_usage` to check usage at end. Log overages. Phase 2: mid-run monitoring.

4. **§Gap 1 (context versioning)**: Add `context_version` to task DB. Increment in `_on_worker_done`. Workers check on start.

5. **§Gap 6 (circular dep detection)**: Add DAG check in SwarmManager._decompose() before spawning workers.
