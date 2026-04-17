---
topic: OpenHands Architecture + SWE-bench 2025 Landscape
date: 2026-04-08
status: reference
sources:
  - https://arxiv.org/html/2511.03690v1
  - https://openhands.dev/blog/openhands-codeact-21-an-open-state-of-the-art-software-development-agent
  - https://www.swebench.com/
  - https://live-swe-agent.github.io/
  - https://arxiv.org/abs/2512.22087
  - https://arxiv.org/html/2510.04905v1
  - https://arxiv.org/abs/2412.18431
---

[English] | [Back to README](../../README.md)

# OpenHands Architecture + SWE-bench 2025 Landscape

## Overview

SWE-bench performance in 2025 shows **agent scaffolding architecture accounts for a 22+ point performance swing** on SWE-bench Pro, while model selection contributes only ~1 point. The key lesson: orchestration and tool design beat model upgrades at the frontier.

---

## 1. OpenHands (All-Hands.dev)

### Architecture

OpenHands v1 (late 2025) implements a **modular SDK-first design**:
- Separates agent, tool, and workspace into reusable packages
- Opt-in sandboxing with clear boundaries (local or cloud deployment)
- Threading/async support for multi-tenant reliability
- Contrast with v0: monolithic, sandbox-centric, not composable

### CodeAct Pattern (v2.1)

Consolidates LLM actions into a **unified code action space** via function calling:
- `enable_llm_editor` tool for direct LLM-based file editing
- Uses Anthropic's `str_replace_editor` as implementation
- Achieves 50%+ solve rates on SWE-bench Verified
- Combines precise function calling + natural language via Claude-3.5

### Key Differentiators vs Clade

| Dimension | OpenHands | Clade |
|---|---|---|
| Sandboxing | Docker per task (opt-in) | Git worktrees per worker |
| Tool abstraction | SDK-level tool interfaces | Shell + Claude Code CLI |
| Editing | `str_replace_editor` function call | Claude Code Edit/Write tools |
| Orchestration | Single agent + tool loop | Multi-worker SwarmManager |
| Context | CAT framework (milestone compression) | ObservationMaskingCondenser |

**Clade advantage**: multi-worker parallel execution with worktree isolation is more mature than OpenHands' single-agent model. Clade's SwarmManager enables true parallelism.

---

## 2. SWE-bench 2025 Performance Landscape

### Top Performers

| System | Benchmark | Score |
|---|---|---|
| Claude Opus 4.5 + Live-SWE-agent | SWE-bench Verified | **79.2%** |
| Claude Sonnet 4.5 + Live-SWE-agent | SWE-bench Pro (hard) | 45.8% |
| OpenHands CodeAct 2.1 | SWE-bench Verified | 50%+ |
| Agentless (Claude 3.5 Sonnet) | SWE-bench Lite | 40.7% |
| Pure Claude Opus 4.5 (no scaffolding) | SWE-bench Verified | ~26% |

**Critical insight**: Pure model inference without scaffolding scores 23-30%. Adding good scaffolding architecture jumps to 50-79%. Scaffolding contributes more than model capability.

---

## 3. Key Technical Patterns

### A. Context Management (22+ point impact)

**Observation masking outperforms LLM summarization:**
- 2.6% performance gain with 52% cost reduction
- Already implemented in Clade: `ObservationMaskingCondenser` (message size guard 8KB/2KB)

**Three-layer context workspace:**
1. Stable: task semantics, file ownership (never compressed)
2. Long-term: condensed history (summary of past turns)
3. Short-term: recent high-fidelity interactions (last N turns)

**Context-as-a-Tool (CAT) framework:**
- Agents proactively compress historical trajectories at milestones
- Achieves 57.6% on SWE-bench Verified
- Clade gap: compression is reactive (at 80% context), not agent-initiated

### B. Code Search & Navigation

**Semantic > Lexical:**
- Graph Retrieval-Augmented Generation (GraphRAG) outperforms grep/ripgrep
- Language Server Protocol (LSP) integration: symbol resolution, type info, AST fragments
- Multi-repository semantic indexing reduces context bloat

**For Clade**: Current `_generate_code_tldr()` uses AST-parsed signatures — good foundation. Gap: no on-demand query API (AutoCodeRover Gap 1). LSP integration would be the next step beyond AST snapshots.

### C. Validation Patterns

**Fail-to-pass (F→P) tests:**
- Test existence confirmed before patch attempt (prevents false positives)
- Worker sees only pre-existing tests; verification in isolation
- **Clade gap**: `_sbfl_prepass()` covers failing test detection; `_generate_repro_test()` covers repro generation. No isolation layer yet.

**Intramorphic testing:**
- Compare original vs. modified system outputs (no test oracle needed)
- Catches regressions without having ground-truth expected values

**Docker-based reproducible environments:**
- Pin dependencies and toolchains
- **Clade gap**: workers run in git worktrees (filesystem isolation only); no dependency pinning

---

## 4. Patterns for Clade's Multi-Worker Orchestration

### Factory Production Line Pattern
```
Plan → Spawn → Monitor → Verify → Integrate → Retro
```
Each stage has explicit entry/exit criteria and failure handling.
This maps naturally to Clade's: `_build_task_file` → worker → `_on_worker_done` → oracle → merge → PROGRESS.md.

### Shared Knowledge Repository
Top performers maintain shared context that worker agents query:
- Codebase graphs, symbol indices, test results
- Prevents duplicate searches across parallel workers
- **Clade gap**: each worker regenerates TLDR independently. A shared, refreshed TLDR cache would reduce redundant work.

### Event Log Architecture
- Immutable event logs for state tracking (not shared memory)
- Enables parallel worker safety, deterministic replay, supervisory visibility
- Clade already has this: `EventStream.get_recent_events()`

---

## 5. Actionable Gaps for Clade

| Gap | Impact | Effort | Status |
|---|---|---|---|
| Agent-initiated context compression (CAT pattern) | High | Medium | TODO |
| LSP integration for semantic code navigation | High | Large | TODO |
| Shared TLDR cache across parallel workers | Medium | Small | TODO |
| Docker-based worker isolation | Medium | Large | TODO |
| Intramorphic testing (regression detection) | Medium | Medium | TODO |

### Immediate wins:
1. **Shared TLDR cache**: Instead of each worker calling `_generate_code_tldr()` independently, cache it in the session and reuse across workers. Already has mtime-based cache — just needs session-level sharing via `ProjectSession`.
2. **Agent-initiated compression**: Add a `compress` tool to workers that triggers `ObservationMaskingCondenser` mid-session rather than waiting for 80% context. Prompt engineering change.

---

## Key Takeaway for Clade

> The gap between Clade and top SWE-bench systems is primarily **context quality** (what the agent sees and when) and **search precision** (semantic vs. lexical). Not model choice. The multi-worker parallelism Clade has is actually ahead of most published systems — the wins will come from smarter context injection and better validation loops.
