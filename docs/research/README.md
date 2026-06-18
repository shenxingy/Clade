**English**（中文版尚未提供 — [README 中文版](../../README.zh-CN.md)）

← Back to [README](../../README.md) · companion: [Who to Learn From](../who-to-learn-from.md) (the watch-list)

# Research Index — What We've Already Studied

The two docs work as a pair:

- **[who-to-learn-from.md](../who-to-learn-from.md)** = the **watch-list** (WHO to learn from, incl. frontier sources we have *not* read yet).
- **This file** = the **deep-dives we've completed** + their **open gap backlog** — the surface to actually start implementing from.

Each deep-dive in this folder has YAML frontmatter (`status`, `summary`, `integrated_items`, `needs_work_items`). This index rolls that up so you don't re-read 30 KB to find what's left to do. **Source of truth is each doc's frontmatter** — when you close a gap, update the doc, then refresh this index.

- **Last reviewed:** 2026-06-18 · **Cadence:** refresh when a deep-dive's `status` changes or a new one lands.

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
| **Aider** | ✅ | 0 | repo-map = tree-sitter + PageRank; lint reflection loop; weak-model for cheap work | [→](2026-03-30-aider-research.md) |
| **OpenHands** | ✅ | 0 | EventStream event-sourcing (replayable state); 9 condenser types | [→](2026-03-30-openhands-architecture.md) |
| **Cursor / Devin** | 📘 | 0 | Planner/Worker/Judge triad; deterministic verify phase (we cover via POST) | [→](2026-03-30-cursor-devin-research.md) |
| **SWE-agent** | 📘 | 0 | ACI design principles; lint guardrail after edits (we have this) | [→](2026-03-30-swe-agent-research.md) |
| **mini-swe-agent** | 📘 | 0 | ~150-line core; single bash tool; output truncation (we distill instead) | [→](2026-03-30-mini-swe-agent-deep-dive.md) |
| **Composio** | ✅ | 0 | CI reaction system; activity detection via Claude JSONL | [→](2026-03-30-composio-orchestrator-research.md) |
| **Kiro (AWS)** | ✅ | 0 | 3-file spec system (EARS); steering files; enhanced agentStop hook | [→](2026-03-30-aws-kiro-deep-research.md) |
| **Community CC harnesses** | ✅ | 0 | Query Control Plane (QueryParams vs QueryState + TransitionReason) | [→](2026-04-08-community-harness-repos.md) |

### SWE-bench localization scaffolds (watch-list Tier 2)
| Source | Status | Gaps | Core lesson | Doc |
|--------|--------|------|-------------|-----|
| **Agentless** | ✅ | 0 | Localize→Repair→Validate as explicit phases; 40-patch sampling + repro-test filter | [→](2026-04-07-agentless.md) |
| **AutoCodeRover** | ✅ | 0 | 7 callable AST search APIs; SBFL pre-pass; cheap LLM-only retry | [→](2026-04-07-autocoderover.md) |
| **Moatless Tools** | ✅ | 0 | Typed search actions; span-level FileContext + token budgeting; semantic index | [→](2026-04-08-moatless-tools.md) |
| **Sweep AI** | ✅ | 0 | AST bipartite graph; topological diff propagation; entity pruning; caller hints | [→](2026-04-08-sweep-ai.md) |

*NB: the AutoCodeRover team now leads **Sonar Foundation Agent** (79.2% SWE-bench Verified, open-source w/ traces) — see watch-list bot-behavior section. Re-read this cluster alongside that.*

### Orchestration & academic patterns (watch-list Tier 3 / foundational)
| Source | Status | Gaps | Core lesson | Doc |
|--------|--------|------|-------------|-----|
| **LangGraph / CrewAI** | ✅ | 0 | StateGraph checkpointing; interrupt() human-in-loop; Send API map-reduce | [→](2026-03-30-langgraph-crewai-research.md) |
| **Reflection agents** | ✅ | 0 | Reflexion episodic memory; minimal-patch; constitutional check; spec checklist | [→](2026-04-07-reflection-agents.md) |

### Craft: PR review & hooks
| Source | Status | Gaps | Core lesson | Doc |
|--------|--------|------|-------------|-----|
| **Qodo Merge (PR-Agent)** | ✅ | 0 | Diff chunking; 2-pass oracle; per-finding fixes; confidence scoring | [→](2026-04-08-qodo-merge.md) |
| **Claude Code hooks** | ✅ | 0 | Input rewrite; async hooks; matcher `if`; persistent perms *(Stop + PostToolUseFailure already closed)* | [→](2026-04-07-claude-hooks.md) |

### Frontier sources (studied 2026-06-18 — cleared the research backlog)
| Source | Status | Gaps | Core lesson | Doc |
|--------|--------|------|-------------|-----|
| **Anthropic — Effective Harnesses** | ✅ | 0 | Iteration-start health check (now built); generator≠judge; acceptance-contract grading | [→](2026-06-18-anthropic-effective-harnesses.md) |
| **Sonar Foundation Agent** | ✅ | 0 | Ex-AutoCodeRover team dropped rigid scaffolding for 1 agent + 3 tools — *endorses* Clade's iterating loop | [→](2026-06-18-sonar-foundation-agent.md) |
| **SST opencode** | ✅ | 0 | Client/server split + session model (we have both); read-only judge hardening (now wired) | [→](2026-06-18-sst-opencode.md) |
| **Huntley Ralph / CURSED** | 📘 | 0 | `while:; do cat PROMPT \| claude; done` — confirms Ralph ≈ /loop; our convergence detection is stronger | [→](2026-06-18-huntley-ralph-cursed.md) |
| **12-Factor Agents** | ✅ | 0 | 11/12 covered + bonus factor 13; Factor-7 inline human-contact is different-by-design | [→](2026-06-18-12-factor-agents.md) |
| **Agent Fingerprint** | ✅ | 0 | Commit-type bug FIXED (uncorrupts fix-rate); test-inclusion signal now built | [→](2026-06-18-agent-fingerprint.md) |

## Open-gap backlog (by effort)

> ### ✅ 2026-06-18 — full reconciliation + cleared the research backlog (19 study agents)
>
> Two sweeps in one session: (1) re-verified every `needs_work` deep-dive item-by-item against `orchestrator/` + `configs/` (51 tracked "gaps" across 12 docs → most were already built in prior loop work, never back-filled); (2) deep-dived all **6 remaining watch-list frontier sources** so the research backlog is now empty.
>
> **What got built this sweep** (6 items, all tested — commits `2c034eb`, `32556fd`, `49af13e`):
> - **Worker commit-type classifier** (`config._infer_commit_type`) — stop hardcoding `feat:`; a real bug that *zeroed the agent fix-rate metric* (`commit-archeology.sh` keys `fix` off `/^fix/`, so every agent fix counted as a feat → `0/N`). [Agent-Fingerprint]
> - **Acceptance-criteria extraction** (`worker_hydrate._extract_acceptance_criteria`) — lift done-criteria out of a hydrated issue body into a first-class contract callout. [Reflection §G5]
> - **Loop iteration-start health check** + **per-iteration fix-rate metric** (loop-runner.sh). [Anthropic · last-mile]
> - **Test-inclusion signal** (PR body + commit-archeology dimension). [Agent-Fingerprint]
> - **Read-only judge hardening** — wired `DISALLOWED_TOOLS_JUDGE` to 5 judge spawns that had it defined-but-not-called. [opencode]
>
> **Closed as already-built / different-not-deficient:** Moatless StringReplace discipline (false open — `EDIT_DISCIPLINE_BLOCK` worker_utils.py:50 already wired); Aider tree-sitter index (on-demand `clade_search_*` + grep cover it at <500-file scale; Sonar validates simple-tools-win); Qodo audience-diff (autonomous = no author/reviewer split); 12-Factor Factor-7 (outer-loop human contact already exists). Sonar + Ralph + 12-Factor land as **endorsements** of Clade's design, not gaps.
>
> **Then built the last 4 too (commits `32556fd`, `49af13e`) — backlog is now empty:**
>
> | Gap | Source | What shipped |
> |-----|--------|------|
> | Iteration-start health check | Anthropic | `node_health_check` in loop-runner.sh — verify_cmd at iteration start, broken baseline folded into supervisor context for repair-first |
> | Test-inclusion signal | Agent-Fingerprint | `tests_added` → PR body (`_build_pr_body`) + `detect_agent_test_inclusion` in commit-archeology.sh |
> | Fix-Rate per-iteration metric | last-mile | pytest failed-count delta per iteration → `fix-rate.tsv`, summarized in the loop report |
> | Read-only judge hardening | opencode | wired `DISALLOWED_TOOLS_JUDGE` to the verify + session supervisor/decompose/suggest judges (was defined-but-not-called) — stronger than a deny-list |
>
> **Net for the whole sweep: 0 open gaps across all 23 deep-dives.** Two latent bugs caught and fixed along the way: the always-`feat:` commit type (zeroed the fix-rate metric), and a YAML duplicate-key in `reflection-agents.md` (second `integrated_items:` block clobbered the first). +19 new tests, full suite green (623).
>
> ### 🔬 2026-06-18 — adversarial re-review of the "different-not-deficient" rulings
>
> The sweep above had a confirmation bias: agents incentivized to *close* gaps tend to rationalize SKIPs. So 4 adversarial agents re-attacked every "different-not-deficient" ruling — verify the claimed alternative is actually *in code*, then steelman the expert. Most held (Localize→Repair→Validate, Qodo audience, provider scope, warm-pool, ChatChunks, greenfield init — genuinely different). But the review **overturned 3 rationalizations, found 1 bug, and corrected several over-claims** — all now built:
>
> | Finding | Was claimed | Reality (audit) | Fix |
> |---------|-------------|-----------------|-----|
> | **SWE-bench eval** | "`run_oracle_eval` already covers it" | FALSE — that measures judge *accuracy* + parser robustness, **zero** end-to-end resolution. The whole study's parity was *reasoning, not measurement*; the SKIP protected it from being tested. | `evals/run_resolve_eval.py` — SWE-bench-Lite pipeline + dry-run self-test (`a1272c2`). **Run it for a real number.** |
> | **Patch-sampling** | "iterate covers sampling's benefit" | Rationalization — in-process retry is **lint-only**, the diverse-sample escape shipped **disabled** (`parallel_fix_samples=1`) AND **unreachable** (`is_critical_path` never auto-set), no selection. | plateau-triggered diverse fan-out on the 2nd oracle rejection (`8e47313`). |
> | **PageRank repo-map** | "LLM selection ≈ PageRank" | Cruder — non-deterministic haiku + keyword-substring, no graph centrality; central-but-keyword-poor files missed. | deterministic import-graph PageRank centrality (`d389ed0`). |
> | **`blocked` task** (bug) | — | `_check_blockers` set `blocked`, which **no path could requeue** → orphaned forever. | retry accepts `blocked` (`f0c519a`). |
> | over-claim: "SBFL" | spectrum/Ochiai | traceback-*frequency* | now counts **distinct failing tests** + honest label (`d389ed0`). |
> | over-claim: localizer window | covers the repo | `tldr[:3000]` truncated the relevant file out | 3000→8000 (`d389ed0`). |
> | over-claim: AST search | covers the codebase | Python AST real, **JS/TS was regex** | widened JS/TS parse: interface/type/enum/arrow/export/methods (`d389ed0`). |
>
> **Honest bottom line:** "0 open gaps" is now backed by *builds + a real eval harness*, not just reasoning — but **true parity with the experts is still unproven until `run_resolve_eval.py` is run on real SWE-bench instances** (needs the claude CLI + per-instance Docker envs). The number, not the argument, is the last mile.
>
> ### 🎯 2026-06-18 — live resolve runs (first real datapoints) + multi-language unlock
>
> First end-to-end resolve runs of Clade's worker loop on **real sibling repos** (planted bug → worker `claude -p` → score against FAIL_TO_PASS/PASS_TO_PASS, neither touched a test file):
> - **owlcast (Python)** — planted `_pick_video_file` selection bug → **RESOLVED in 33s** (worker re-derived the exact correct one-liner).
> - **faker-100 (TypeScript)** — planted `classifyPlatform` `&&`→`||` bug → **RESOLVED in 86s** (auto-committed the fix).
>
> Honest scope: both are *easy 1-line bugs* and prove the **loop works end-to-end on a real codebase**, not a SWE-bench-comparable resolve-rate. Notable finding: Clade's Python scaffolding (SBFL/repro) **didn't contribute** — SBFL is blind to *assertion* failures (no impl frame in the traceback), and the haiku localizer fell back to the full map. The worker won on the model's own navigation + a clear symptom + the TLDR.
>
> **Multi-language unlock (B):** Clade was BLIND on non-Python/JS repos (empty TLDR). Now `worker_tldr._parse_with_treesitter` gives real AST signatures for Go/Rust/Java/Ruby/C/C++/C#/PHP via lazy tree-sitter grammars (optional + graceful; `requirements-treesitter.txt`), JS/TS stay on the tuned regex. Verified on real sibling code (companyOS TS schemas, Go AST). This is the audit's "for a multi-lang shop, tree-sitter is the real answer" — now built (`efabb1e`/`0755765`).
>
> ---
>
> ✅ **Reconciled against code 2026-06-13.** A direct audit of `orchestrator/` found the overwhelming majority of the small + medium items below **already implemented** — episodic failure memory, minimal-patch retry, acceptance-criteria checklist, post-worker test runner, caller hints, diff chunking, confidence scoring, two-pass oracle, entity-level TLDR pruning, all four hook items, and more (many cite their source gap in-code). **Do not build from the lists below without re-grepping first — they predate the audit.**
>
> **Final dispositions after deep study (2026-06-14, 4 parallel study agents + code review):**
> | Item | Source | Disposition |
> |------|--------|-------------|
> | Constitutional check vs CLAUDE.md | Reflection §G4 | ✅ **DONE** (a56d921 + 7d50b0c) — CLAUDE.md "Code Rules" injected into oracle quality + chunked passes; wired in both `_run_oracle_gate` and `oracle_cli.py`. |
> | Reproduction-test filter | Agentless §6B | ✅ **DONE** (601bd9b + 7d50b0c) — Clade already *generated* a confirmed-failing repro then threw it away; now persisted (task-id namespaced) + re-run post-fix, result feeds oracle evidence, hard-block behind `repro_test_gate`. |
> | Split retrieve(P1)/patch(P2) | AutoCodeRover | ❌ **SKIP different-not-deficient** — soft two-phase directive already injected (`worker_taskfile.py:269`); hard process-split forces context re-hydration the native single-context loop avoids. |
> | Localize→Repair→Validate phases | Agentless | ❌ **SKIP different-not-deficient** — localize + validate already deterministic phases; making *repair* non-agentic discards the native navigate/edit/verify loop (Agentless's split only existed to stop weak models distracting themselves). |
> | 7 callable AST search APIs | AutoCodeRover | ❌ **SKIP already-equivalent** — `clade_search_class/method/code` exist + wired (`mcp_server.py:337`); the residual 4 are file-scoped variants subsumed by native Grep/Read-with-path. |
> | Embedding semantic index (FAISS+Voyage) | Moatless | ❌ **SKIP different-not-deficient** — paid API + doubled deps + stale-on-every-commit for negligible gain at <500-file scale (doc's own words: "overkill"); 3/4 search actions already exist as tools. |
> | SBFL / Ochiai pre-pass | AutoCodeRover | ✅ **ALREADY-DONE** — `_sbfl_prepass` (traceback-frequency proxy, `worker_tldr.py:659`); prior grep was a false negative. |
> | SWE-bench eval harness | Moatless | ❌ **SKIP different-not-deficient** — Clade-shaped eval already exists (`evals/run_oracle_eval.py`); SWE-bench measures the wrong thing for a general loop tool. |
>
> **Net: of 7 studied items, 2 were genuinely deficient and are now built; 5 were already-done or different-not-deficient.** Newly-found gaps (separate from this cluster) — all now resolved:
> - ✅ **`test-baseline.json` swarm race** — FIXED (be1e980): namespaced to `test-baseline-{task_id}.json`, same pattern as the repro filter.
> - ✅ **`_sbfl_prepass` had no unit test** — ADDED (94a77ab); the test caught a real bug (traceback regex matched newlines → suspect-ranking corrupted across keys), fixed in the same commit.
> - ❌ **Parallel patch-sampling + majority-vote re-rank** (Agentless Opp. C) — **SKIP, different-not-deficient + cost.** Agentless sampled 40 patches for a one-shot benchmark with a weak base model maximizing pass@1. Clade has a strong base model that already *iterates* (reflection retry w/ episodic memory + minimal-patch targeting) and *verifies* (oracle gate → requeue, repro-test filter) — covering sampling's core benefit (escaping one bad attempt) without the N× per-task token cost. `swarm.py` is a worker-pool manager, not a candidate sampler. Revisit only if we observe tasks where sequential iteration *plateaus* on the same wrong approach — then a diverse multi-angle attempt (judge-panel pattern) is the lever, as an opt-in for hard tasks, not a default.

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

✅ **Empty as of 2026-06-18.** The 6 frontier sources that previously lived here were all deep-dived this sweep — see the [Frontier sources](#frontier-sources-studied-2026-06-18--cleared-the-research-backlog) table above:

- ✅ **Anthropic "Effective harnesses for long-running agents"** (Tier 1) → [doc](2026-06-18-anthropic-effective-harnesses.md) · 0 gaps — iteration-start health check now built.
- ✅ **Sonar Foundation Agent** → [doc](2026-06-18-sonar-foundation-agent.md) · 0 gaps — endorses Clade's iterating-loop design.
- ✅ **SST opencode** → [doc](2026-06-18-sst-opencode.md) · 0 gaps — read-only judge hardening now wired.
- ✅ **Geoffrey Huntley — Ralph/CURSED** → [doc](2026-06-18-huntley-ralph-cursed.md) · 0 gaps — confirms Ralph ≈ /loop.
- ✅ **12-Factor Agents** → [doc](2026-06-18-12-factor-agents.md) · 0 gaps — 11/12 + bonus covered.
- ✅ **Agent Fingerprint study** → [doc](2026-06-18-agent-fingerprint.md) · 0 gaps — commit-type bug fixed + test-inclusion signal built.

New frontier candidates land on the [watch-list](../who-to-learn-from.md); pull one here when it's worth a `/deep-research`.

## How to use this for a study session

1. Open the [theme view](#where-were-weakest-theme-view) → pick the hottest theme you have appetite for (default: **fault localization**).
2. Read the relevant deep-dive(s) for that theme.
3. Pull one item from the [backlog](#open-gap-backlog-by-effort) — prefer 🟢 small for a first win.
4. Apply the **"different ≠ deficient"** gate ([watch-list](../who-to-learn-from.md#how-we-vet-what-we-absorb)) — confirm it's a real deficit before building.
5. Build it (reversible — commit small), update the deep-dive's frontmatter (`needs_work_items` → `integrated_items`), then refresh this index's counts + `Last reviewed`.
