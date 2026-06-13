**English**（中文版尚未提供 — [README 中文版](../../README.zh-CN.md)）

← Back to [README](../../README.md) · companion: [Who to Learn From](../who-to-learn-from.md) (the watch-list)

# Research Index — What We've Already Studied

The two docs work as a pair:

- **[who-to-learn-from.md](../who-to-learn-from.md)** = the **watch-list** (WHO to learn from, incl. frontier sources we have *not* read yet).
- **This file** = the **deep-dives we've completed** + their **open gap backlog** — the surface to actually start implementing from.

Each deep-dive in this folder has YAML frontmatter (`status`, `summary`, `integrated_items`, `needs_work_items`). This index rolls that up so you don't re-read 30 KB to find what's left to do. **Source of truth is each doc's frontmatter** — when you close a gap, update the doc, then refresh this index.

- **Last reviewed:** 2026-06-13 · **Cadence:** refresh when a deep-dive's `status` changes or a new one lands.

**Status:** ✅ integrated (absorbed) · 📘 reference (studied, nothing to build) · 🔨 needs_work (open gaps)

## Table of Contents

- [Where we're weakest (theme view)](#where-were-weakest-theme-view)
- [Index of deep-dives](#index-of-deep-dives)
- [Open-gap backlog (by effort)](#open-gap-backlog-by-effort)
- [Research backlog — watch-list entries not yet deep-dived](#research-backlog--watch-list-entries-not-yet-deep-dived)
- [How to use this for a study session](#how-to-use-this-for-a-study-session)

---

## Where we're weakest (theme view)

The gaps cluster into 5 themes. This is the strategic read — *where the most external lessons point at the same Clade weakness.*

> ⚠️ **2026-06-13 code-audit reconciliation.** The themes below were drafted from the April research docs. A grep+spot-check audit of `orchestrator/` found **most small/medium items already implemented** (several carry gap-citing docstrings like `(Sweep §Gap2)` / `Multi-agent Gap 3` — prior loop work that never got back-filled here). The heat ratings describe where the *lessons* converge, not where Clade is still weak today. **Genuinely-open items are the short list in the [backlog callout](#open-gap-backlog-by-effort) below — trust that, not the per-theme "start here" notes.**

| Theme | Our gap (in one line) | Sources pushing on it | Heat |
|-------|----------------------|----------------------|------|
| **Fault localization / context retrieval** | Clade injects one flat TLDR blob; no ranked "suspect files→methods→lines", no iterative narrowing, no semantic search | Aider (PageRank+tree-sitter), Agentless (hierarchical JSON localize), AutoCodeRover (AST search APIs + SBFL), Moatless (typed search, span budgeting), Sweep (AST bipartite) | 🔥🔥🔥 hottest — 5 sources, our biggest deficit vs SWE-bench scaffolds |
| **Reflection / retry loop** | Clade retries one-shot (re-runs whole subprocess); no failure-mode memory, no repro-test patch filter, no minimal-patch targeting, no constitutional re-check | Aider (3× reflection), Agentless (repro-test filter), AutoCodeRover (cheap LLM-only retry), Reflexion/Self-RAG (episodic memory, minimal patch, constitutional, spec checklist), Sweep (test runner) | 🔥🔥🔥 most 🟢 cheap wins — start here for momentum |
| **Context compression / layering** | TLDR only; no structured condenser strategies, no L1/L2/L3 tiers, no per-span token budget | OpenHands (9 condensers), Aider (ChatChunks layering), Moatless (token budgeting) | 🔥🔥 |
| **Hooks / spec scaffolding** | Hooks don't rewrite-on-block, aren't matcher-scoped, don't persist allow-rules; no source-traced TODOs / VERIFY invariants (Stop + PostToolUseFailure hooks now exist) | Kiro (enhanced stop hook, EARS invariants, traced TODOs), Claude Code hook docs (input rewrite, async, matcher if) | 🔥🔥 |
| **PR-review / oracle craft** | Oracle is single-pass; large diffs truncated at 3000 chars (auto-approve risk); no per-finding fixes or confidence; worker state lost on restart (no event replay) | Qodo Merge (diff chunking, 2-pass, per-finding, confidence), Reflection (per-dimension fixes), Composio (reaction system), OpenHands (EventStream) | 🔥🔥 |

**Takeaway:** strategically, **fault localization** is the deepest deficit (5 sources, needs a real index) — the high-value bet. Tactically, **reflection/retry** and **hooks** hold the most 🟢 cheap wins — start there for momentum, then commit to the fault-localization track.

## Index of deep-dives

Grouped by [watch-list](../who-to-learn-from.md) tier. `Gaps` = count of open `needs_work_items`.

### Peer harnesses (watch-list Tier 2)
| Source | Status | Gaps | Core lesson | Doc |
|--------|--------|------|-------------|-----|
| **Aider** | 🔨 | 5 | repo-map = tree-sitter + PageRank; lint reflection loop; weak-model for cheap work | [→](2026-03-30-aider-research.md) |
| **OpenHands** | 🔨 | 2 | EventStream event-sourcing (replayable state); 9 condenser types | [→](2026-03-30-openhands-architecture.md) |
| **Cursor / Devin** | 📘 | 0 | Planner/Worker/Judge triad; deterministic verify phase (we cover via POST) | [→](2026-03-30-cursor-devin-research.md) |
| **SWE-agent** | 📘 | 0 | ACI design principles; lint guardrail after edits (we have this) | [→](2026-03-30-swe-agent-research.md) |
| **mini-swe-agent** | 📘 | 0 | ~150-line core; single bash tool; output truncation (we distill instead) | [→](2026-03-30-mini-swe-agent-deep-dive.md) |
| **Composio** | 🔨 | 2 | CI reaction system; activity detection via Claude JSONL | [→](2026-03-30-composio-orchestrator-research.md) |
| **Kiro (AWS)** | 🔨 | 5 | 3-file spec system (EARS); steering files; enhanced agentStop hook | [→](2026-03-30-aws-kiro-deep-research.md) |
| **Community CC harnesses** | ✅ | 0 | Query Control Plane (QueryParams vs QueryState + TransitionReason) | [→](2026-04-08-community-harness-repos.md) |

### SWE-bench localization scaffolds (watch-list Tier 2)
| Source | Status | Gaps | Core lesson | Doc |
|--------|--------|------|-------------|-----|
| **Agentless** | 🔨 | 4 | Localize→Repair→Validate as explicit phases; 40-patch sampling + repro-test filter | [→](2026-04-07-agentless.md) |
| **AutoCodeRover** | 🔨 | 6 | 7 callable AST search APIs; SBFL pre-pass; cheap LLM-only retry | [→](2026-04-07-autocoderover.md) |
| **Moatless Tools** | 🔨 | 7 | Typed search actions; span-level FileContext + token budgeting; semantic index | [→](2026-04-08-moatless-tools.md) |
| **Sweep AI** | 🔨 | 4 | AST bipartite graph; topological diff propagation; entity pruning; caller hints | [→](2026-04-08-sweep-ai.md) |

*NB: the AutoCodeRover team now leads **Sonar Foundation Agent** (79.2% SWE-bench Verified, open-source w/ traces) — see watch-list bot-behavior section. Re-read this cluster alongside that.*

### Orchestration & academic patterns (watch-list Tier 3 / foundational)
| Source | Status | Gaps | Core lesson | Doc |
|--------|--------|------|-------------|-----|
| **LangGraph / CrewAI** | 🔨 | 2 | StateGraph checkpointing; interrupt() human-in-loop; Send API map-reduce | [→](2026-03-30-langgraph-crewai-research.md) |
| **Reflection agents** | 🔨 | 5 | Reflexion episodic memory; minimal-patch; constitutional check; spec checklist | [→](2026-04-07-reflection-agents.md) |

### Craft: PR review & hooks
| Source | Status | Gaps | Core lesson | Doc |
|--------|--------|------|-------------|-----|
| **Qodo Merge (PR-Agent)** | 🔨 | 5 | Diff chunking; 2-pass oracle; per-finding fixes; confidence scoring | [→](2026-04-08-qodo-merge.md) |
| **Claude Code hooks** | 🔨 | 4 | Input rewrite; async hooks; matcher `if`; persistent perms *(Stop + PostToolUseFailure already closed)* | [→](2026-04-07-claude-hooks.md) |

## Open-gap backlog (by effort)

> ✅ **Reconciled against code 2026-06-13.** A direct audit of `orchestrator/` found the overwhelming majority of the small + medium items below **already implemented** — episodic failure memory, minimal-patch retry, acceptance-criteria checklist, post-worker test runner, caller hints, diff chunking, confidence scoring, two-pass oracle, entity-level TLDR pruning, all four hook items, and more (many cite their source gap in-code). **Do not build from the lists below without re-grepping first — they predate the audit.**
>
> **Confirmed STILL OPEN (verified absent in code today):**
> | Item | Source | Effort | Note |
> |------|--------|--------|------|
> | ~~Constitutional check vs CLAUDE.md~~ | Reflection §G4 | ✅ done | **DONE 2026-06-13 (a56d921)** — project CLAUDE.md "Code Rules" injected into the oracle quality + chunked passes; rides findings→fix→requeue. |
> | **Reproduction-test filter** | Agentless | 🟡 medium | *Highest fix-quality lever in the cluster.* Generate a repro test for the bug, use it to filter/validate the patch. Touches `verify_and_commit` (critical path). **← recommended next build.** |
> | **Split retrieve(P1)/patch(P2) phases** | AutoCodeRover | 🟡 medium | Freeze context before patching. Partial today (method-granularity search exists). |
> | **Localize→Repair→Validate as explicit phases** | Agentless | 🔴 large | We run one end-to-end worker pass. Architectural. |
> | **7 callable AST search APIs** | AutoCodeRover | 🔴 large | Partial — `clade_search_*` MCP tools exist; not the full 7-API surface. |
> | **Embedding semantic index (FAISS+Voyage)** | Moatless | 🔴 large | No vector retrieval. Architectural. |
>
> *(SBFL/Ochiai and SWE-bench-harness greps were inconclusive — re-verify before trusting.)*

The lists below are the **pre-audit** backlog, kept for provenance. Cheapest first; re-grep each before building.

### 🟢 Small (cheap wins — start here), grouped by sub-theme

**Reflection / retry**
- ⭐ **[Reflection]** Episodic failure memory — a "Failure Analysis" block (what was tried / why it failed / what to change) in the retry prompt, haiku-generated from lint+oracle output. *Flagged highest-value-smallest-effort.* → `worker.py`.
- **[Reflection]** Minimal-patch reflection — parse lint for `file:line`, then `--continue` with "fix this specific error only, change nothing else." Stops needless full rewrites.
- **[Reflection]** Spec-driven acceptance-criteria checklist — extract "Acceptance Criteria"/"Definition of Done" from pre-hydrated issues, append to the task file. → `_pre_hydrate`.

**Fault localization / retrieval**
- **[AutoCodeRover]** Patch-validation retry budget — retry only the patch-gen LLM call (≤3×), not the whole subprocess. → `worker.py`.
- **[AutoCodeRover]** Explicit exploration cap + LLM "sufficient context" signal before patching (caps at 10 rounds).
- **[Moatless]** Two-phase search-then-identify — secondary haiku distills large result sets before injection. → `worker_tldr.py`.
- **[Moatless]** StringReplace edit-validation discipline (uniqueness + line-number stripping) in the worker **system prompt** — no code change.
- **[Sweep]** Post-worker functional test runner — `test_cmd` in orchestrator config, run after commit, feed failures into retry.
- **[Sweep]** Call-site dependency hints — grep callers of changed functions → "if you change X, also update these." Plain Bash.

**Oracle / PR review**
- **[Qodo]** Diff chunking for diffs >3000 chars — prevents truncated large refactors from auto-approving. → `_oracle_review`.
- **[Qodo]** Confidence-scored findings (high/medium/low per dimension) so the worker fixes high-confidence first.

**Hooks**
- **[Claude-hooks]** Async PostToolUse — `async:true` on formatting/notification hooks to kill per-edit latency (verify current flag).
- **[Claude-hooks]** Input rewriting (`git push -f` → `--force-with-lease`) via `updatedInput` instead of a hard block.
- **[Claude-hooks]** Matcher `if` to skip `pre-tool-guardian.sh` on safe Bash calls.
- **[Claude-hooks]** Persistent allow-rules via `updatedPermissions` to stop reprompting known-safe patterns.

### 🟡 Medium
- **[Agentless]** Hierarchical localization as **structured JSON** ("suspect files→classes→lines") before repair.
- **[Agentless]** Patch sampling + majority-vote re-ranking (N haiku candidates, pick via oracle).
- **[Agentless]** Reproduction-test generation as a patch filter — *highest fix-quality lever in the cluster.* → `worker.py` verify.
- **[AutoCodeRover]** Split context-retrieval (Phase 1) from patch-gen (Phase 2) — freeze context before patching.
- **[AutoCodeRover]** Method-granularity search (full bodies ±3 lines) vs signature-only TLDR.
- **[Moatless]** Span-level FileContext with per-span token budgeting + eviction.
- **[Moatless]** Typed search actions (FindClass/FindFunction/SemanticSearch) in worker system prompt.
- **[Moatless]** `max_tokens_per_worker` budget — orchestrator doesn't observe worker token usage. → `config.py`.
- **[Sweep]** Entity-level TLDR pruning — filter TLDR to issue-relevant entities (3-5× less noise).
- **[Sweep]** Hybrid context retrieval — keyword grep + structural haiku in `_localize_tldr_for_task`.
- **[Qodo + Reflection]** Per-finding / per-dimension targeted fixes — `findings:[{dimension,severity,fix_suggestion}]`; worker applies in order. *(These two overlap — build once.)*
- **[Qodo]** Two-pass oracle — spec-adherence check then quality/bug check, reconciled.
- **[Reflection]** Constitutional check after generation — haiku validates the diff against CLAUDE.md "Code Rules" before commit.

### 🔴 Large (architectural)
- **[Agentless]** Localize→Repair→Validate as explicit first-class phases (we run one end-to-end worker pass).
- **[AutoCodeRover]** Structured AST search APIs exposed to the agent (7 callable tools).
- **[AutoCodeRover]** Spectrum-based fault localization (SBFL / Ochiai scores) as a pre-pass hint.
- **[Moatless]** Embedding-based semantic search index (FAISS + tree-sitter + Voyage).
- **[Moatless]** SWE-bench evaluation harness (no benchmark harness today → can't measure worker quality).

### 🔵 Low (deprioritized)
- **[Qodo]** PR-review audience differentiation (author vs reviewer comments) — author flagged low priority for autonomous flows.

### ⚪ Untagged (need a sizing pass)
*Many cluster into the themes above — Aider reflection → reflection theme, OpenHands condensers → context-compression, Kiro stop hook → hooks.*
- **[Aider]** multi-cycle reflection loop · L1/L2/L3 ChatChunks layering · PageRank `/map` · tree-sitter indexing · adaptive repo-map sizing
- **[Kiro]** source-traced TODOs (`_From: GOALS.md §X.Y`) · conditional CLAUDE.md inclusion by file type · enhanced stop hook (security/spec/coverage) · VERIFY.md invariants · worker-scoped steering files
- **[OpenHands]** EventStream replayable state (fault tolerance) · structured condenser strategies
- **[Composio]** PR-review reaction system (→ `github_sync.py`) · activity detection via Claude JSONL
- **[LangGraph]** interrupt() human-in-loop breakpoints · Send API map-reduce dispatch

## Research backlog — watch-list entries not yet deep-dived

High-value [watch-list](../who-to-learn-from.md) sources with **no deep-dive yet** (candidates for `/deep-research` → a new file here):

- **Anthropic "Effective harnesses for long-running agents"** (Tier 1) — diff against our loop primitives.
- **Sonar Foundation Agent** — top open SWE-bench scaffold w/ traces (pairs with the localization cluster).
- **SST opencode** — most architecturally similar peer; session model.
- **Geoffrey Huntley — Ralph/CURSED** — loop convergence & goal-framing.
- **12-Factor Agents** — factor-by-factor audit of Clade.
- **Agent Fingerprint study** — empirical agent commit/PR features (→ worker commit hygiene).

## How to use this for a study session

1. Open the [theme view](#where-were-weakest-theme-view) → pick the hottest theme you have appetite for (default: **fault localization**).
2. Read the relevant deep-dive(s) for that theme.
3. Pull one item from the [backlog](#open-gap-backlog-by-effort) — prefer 🟢 small for a first win.
4. Apply the **"different ≠ deficient"** gate ([watch-list](../who-to-learn-from.md#how-we-vet-what-we-absorb)) — confirm it's a real deficit before building.
5. Build it (reversible — commit small), update the deep-dive's frontmatter (`needs_work_items` → `integrated_items`), then refresh this index's counts + `Last reviewed`.
