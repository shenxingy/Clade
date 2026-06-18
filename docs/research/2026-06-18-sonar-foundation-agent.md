---
name: Sonar Foundation Agent — Free-Workflow Tool-Calling Agent (autonomy-matched-to-model)
date: 2026-06-18
status: integrated
review_date: 2026-06-18
reconciled: 2026-06-18
summary: >
  SonarSource's Foundation Agent (ex-AutoCodeRover team) tops the unfiltered SWE-bench
  leaderboard — 79.2% Verified / 52.6% Full with Claude Opus 4.5, ~$1.90/issue, 10.4 min/issue.
  Architecturally it is the OPPOSITE of its AutoCodeRover ancestor: a single LlamaIndex
  tool-calling agent with just three tools (stateful bash, Anthropic-compatible text editor,
  treesitter AST symbol search), two prompts (test-driven system prompt + issue user prompt),
  and a 150-step cap. Its headline thesis — "match agent autonomy to model capability" — is
  exactly Clade's design stance (strong base model that ITERATES, not a rigid scaffold).
  Every concrete mechanism (AST search, test-driven validation, reproducer-first, minimal
  patch, non-prescriptive prompts, autonomous regression discovery) is already in Clade's
  localization cluster. No genuine gaps found.
integrated_items:
  - "Treesitter AST symbol search (find class/method/code) — DONE: mcp_server.py:216 (_ast_search_class), mcp_server.py:250 (_ast_search_method), mcp_server.py:381 (clade_search_code); index parity with Sonar's find_symbols / AutoCodeRover AST search"
  - "Test-driven validation — re-run project tests post-patch, undo+requeue on regression — DONE: worker_utils.py:396 (_run_project_tests reads test_cmd), worker.py:818 (regression gate before oracle/push), worker.py:842 (auto_committed=False on failure)"
  - "Reproducer-first (write failing test, fix, verify it passes) — DONE: worker_tldr.py:767 (_generate_repro_test persists only confirmed-failing repro), worker_utils.py:515 (_run_repro_filter re-runs post-fix), worker.py:826 (feeds oracle evidence; hard-block under repro_test_gate)"
  - "Autonomous regression discovery (no PASS_TO_PASS/FAIL_TO_PASS metadata) — DONE: worker_utils.py:444 (_capture_test_baseline) + worker_utils.py:461 (_find_intramorphic_regressions) detect fix-introduced regressions by before/after diff, no benchmark oracle"
  - "Minimal-patch directive (small patches resolve more — Sonar Fig 1-3) — DONE: worker_taskfile.py:385 ('Make the minimal targeted change — prefer 1-3 line edits')"
  - "Non-prescriptive / high-level prompting for thinking models — DONE: worker_taskfile.py:378-396 (phase scaffold is principle-level, not step-by-step keystrokes); Opus base model + extended thinking is the runtime"
  - "Stateful bash + on-demand editor as primary tools — DONE: native Claude Code Bash/Edit/Read are stateful and Anthropic-trained (Sonar's whole 'tools deeply integrated into Anthropic models' rationale is Clade's native substrate by construction)"
reference_items:
  - "150-step hard cap (empirical efficacy/cost balance) — SKIP: Clade's loop converges on goal-met / max-iter (configs/skills/loop/SKILL.md:36) and workers commit incrementally (worker.py:811 auto_committed); a per-task tool-call cap targets one-shot benchmark cost control, not an iterating autonomous loop (different-not-deficient)"
  - "'Save tentative patches' so the agent never terminates answer-less — SKIP: Clade auto-commits the working patch as it goes (worker.py:811) and persists state via event_stream; the failure mode Sonar patches (run out of steps mid-validation, lose the patch) cannot occur — commits are the durable tentative state (different-not-deficient)"
  - "Single-agent free workflow replacing two-stage retrieve→patch — SKIP: already reconciled as different-not-deficient in 2026-04-07-autocoderover.md; Clade's soft two-phase checkpoint (worker_taskfile.py:378) is prompt-level, not a hard process split; Sonar's own data (58%→70%) confirms the free workflow is the better default Clade already runs"
  - "Treesitter (multi-language) vs Clade's Python-AST + JS/TS-regex index — SKIP: marginal; Clade is <500-file single-language-dominant scale (CLAUDE.md), and clade_search_* already serves on-demand structural queries (mcp_server.py:337); a treesitter rewrite is breadth Clade does not need yet (engineered-enough)"
needs_work_items: []
---

[English] | [Back to README](../../README.md)

# Sonar Foundation Agent — Free-Workflow Tool-Calling Agent

## Overview

The **Sonar Foundation Agent** is SonarSource's general-purpose coding agent, built by the
former **AutoCodeRover** team (Haifeng Ruan, Yuntong Zhang) after Sonar's Feb-2025 acquisition.
As of 2025-12-19 it holds the **top spot on the unfiltered SWE-bench leaderboard**: **79.2%
SWE-bench Verified** and **52.6% SWE-bench Full** with Claude Opus 4.5, averaging **$1.90/issue
and 10.4 minutes/issue**. It is an internal research project; the tech ships in the SonarQube
Remediation Agent (beta). A 6-page technical report and the methodology are public (no full
agent source or per-task traces are released — the repo is a report + README).

The story worth absorbing is the **architectural reversal**. AutoCodeRover (ISSTA 2024) was a
rigid two-stage pipeline (retrieve context → generate patch, separate agents). The Foundation
Agent throws that out: **one agent, three tools, two prompts, maximum autonomy** — and that
nearly doubles efficacy on the same benchmark family. Their stated lesson is Clade's own thesis.

## Architecture

A **single tool-calling agent implemented on LlamaIndex**. Given the issue description and a
system prompt, it iteratively invokes tools to investigate and patch, emitting a unified-diff
patch. No pipeline, no stage separation, no sub-agents.

**Three tools** (report §2.2), deliberately minimal:

| Tool | Mechanism | Note |
|------|-----------|------|
| `bash` | Stateful — same bash process across invocations; 5-min per-command timeout | Interface-compatible with Anthropic `bash_20250124` (so the model is pre-trained for it) |
| `text_editor` | View / create / edit files via string replacement; returns the edited portion after each edit | Compatible with Anthropic `text_editor_20250728` |
| AST Search | treesitter index of all classes/functions built at startup; search a symbol in a file or whole codebase | "more efficient than grep from bash, saving reasoning steps and LLM cost"; inherited from AutoCodeRover |

**Important correction**: several news summaries claim the agent uses *spectrum-based fault
localization (SBFL)*. The primary technical report does **not** — it lists only bash + text
editor + AST search. SBFL was an *optional* AutoCodeRover pre-pass; the Foundation Agent
dropped it in favor of letting the model drive retrieval. (Clade kept a lightweight SBFL
proxy anyway — see below — so this is a non-issue either way.)

**Two prompts only** (§2.3):
- **System prompt** — defines a *test-driven methodology* (fully understand the issue → write a
  reproducer test → fix → verify with reproducer + regression tests) stated as **high-level
  principles, not step-by-step instructions**, explicitly to give thinking models room
  ("adapt your approach to task complexity"; no SWE-bench-specific knowledge, to avoid overfit).
- **User prompt** — the issue verbatim + output location, with an instruction to **save
  tentative patches** so the agent doesn't run out of steps mid-validation and terminate empty.

**Budget**: at most **150 tool-call steps per task** (empirical efficacy/cost balance).
**Regression tests are discovered autonomously** — the agent does *not* read SWE-bench's
`PASS_TO_PASS` / `FAIL_TO_PASS` metadata; it finds and runs relevant tests itself.

## The central lesson: autonomy matched to model capability

The report's headline finding (Fig 4), all on Claude Sonnet 4.5, same tools:

| Workflow | SWE-bench Verified |
|----------|-------------------|
| Two-stage (AutoCodeRover-style, rigid) | 58.0% |
| Free workflow (single agent decides) | 70.8% |
| Free workflow + extended thinking + concise prompts | 75.0% |

The two-stage split *helped* in 2024 when LLMs lost track of long context; with 2025 models it
*hurts* (−12.8 pts). And over-detailed prompts cap a thinking model at ~70% — distilling the
prompt to principles unlocked the last 5 points. Their conclusion: **"as underlying models grow
more powerful, we must grant them more autonomy."** Efficacy/cost trade across models on Verified:
GPT-5 70.8% / $0.45, Gemini 3 Pro 72.4% / $0.59, Sonnet 4.5 74.8% / $1.25, Opus 4.5 79.2% / $1.90.

Patch analysis (Figs 1-3, Table 2): correct patches are overwhelmingly **small** (<30 lines;
Opus correct patches cluster at 2-4 LOC; exact-match patches avg 4-5 LOC). **Smaller patch →
higher resolve probability.** This is direct empirical backing for Clade's minimal-patch rule.

## Per-pattern comparison with Clade

### 1. AST symbol search — COVERED
Sonar's `find_symbols` / AST Search = Clade's `clade_search_class` (`mcp_server.py:216`),
`clade_search_method` (`mcp_server.py:250`), `clade_search_code` (`mcp_server.py:381`), exposed
as MCP tools and explicitly recommended in the task file when spans are evicted
(`worker_taskfile.py:264-266`). Same "AST search beats grep, saves tokens" rationale. Sonar uses
treesitter (multi-language) vs Clade's Python-AST + JS/TS-regex — marginal at Clade's <500-file
scale (reference item). **Covered.**

### 2. Test-driven validation — COVERED
Sonar verifies every patch against project + regression tests before answering. Clade runs
`_run_project_tests` (`worker_utils.py:396`, reads `test_cmd` from `.claude/orchestrator.json`)
**before the oracle gate and before push** (`worker.py:814-818`); a regression **undoes the
commit and requeues with evidence** (`worker.py:842`). Plus `_capture_test_baseline`
(`worker_utils.py:444`) + `_find_intramorphic_regressions` (`worker_utils.py:461`) catch
fix-introduced regressions by before/after diff — **autonomous regression discovery, no
benchmark metadata**, exactly Sonar's "discover and run relevant regression tests fully
autonomously." **Covered.**

### 3. Reproducer-first — COVERED
Sonar's core principle: write a reproducer test, fix, verify it passes. Clade's
`_generate_repro_test` (`worker_tldr.py:767`) persists a repro **only when it is confirmed
failing on the buggy code**, `_run_repro_filter` (`worker_utils.py:515`) re-runs it after the
fix as executable proof the bug is resolved, and the result feeds oracle evidence (hard-block
under `repro_test_gate`, `worker.py:826-847`). This is Agentless §6B — same shape as Sonar.
**Covered.**

### 4. Minimal patch — COVERED + EXTERNALLY VALIDATED
Sonar's Figs 1-3 are empirical proof that small patches resolve more issues. Clade already
mandates it: `worker_taskfile.py:385` — "Make the minimal targeted change — prefer 1-3 line
edits." Sonar's data *validates* Clade's existing rule rather than exposing a gap. **Covered.**

### 5. Non-prescriptive prompting for thinking models — COVERED (by design)
Sonar's last 5 points came from making prompts *less* prescriptive so the thinking model has
room. Clade runs an Opus base model with extended thinking natively and frames the task file as
*principles + phase boundaries* (`worker_taskfile.py:378-396`), not keystroke scripts. Clade's
whole premise — "strong base model that ITERATES vs one-shot benchmark scaffolds" — IS Sonar's
conclusion. **Covered by design.**

### 6. Single agent / free workflow — COVERED (different-not-deficient, already reconciled)
The retrieve→patch split is reconciled in `2026-04-07-autocoderover.md` as different-not-
deficient: Clade's two-phase is a *soft* prompt checkpoint (`worker_taskfile.py:378`), not a
hard process split. Sonar's own 58%→70% result confirms the free workflow Clade already runs is
the better default. **Covered.**

### 7. Stateful bash + on-demand editor — COVERED (native substrate)
Sonar's whole tool rationale is "Anthropic models are trained for these tools." Clade runs
*on* Claude Code — native `Bash` (stateful), `Edit`, `Read` are that substrate by construction.
Nothing to adopt. **Covered.**

### 8. 150-step cap & save-tentative-patches — N/A for Clade (reference)
Both target a one-shot benchmark's failure mode: an agent that runs out of tool calls
mid-validation and terminates with no patch. Clade **auto-commits the working patch as it goes**
(`worker.py:811`), so the patch is durable state, and the loop converges on goal-met / max-iter
(`configs/skills/loop/SKILL.md:36`) rather than a per-task call budget. The Sonar failure mode
structurally cannot occur. **Different-not-deficient.**

## Verdict

**No genuine gaps.** The Sonar Foundation Agent is the strongest possible external endorsement
of Clade's localization cluster and its core stance: every concrete mechanism — AST symbol
search, test-driven + reproducer-first validation, autonomous regression discovery, minimal
patches, principle-level prompting for a thinking model — is already implemented with file:line
evidence above. Its central thesis ("grant capable models more autonomy; rigid multi-stage
scaffolds now *hurt*") is precisely why Clade is an iterating Claude-Code loop and not a
benchmark pipeline, and its patch-size data externally validates Clade's minimal-patch rule.
The few non-adopted items (150-step cap, save-tentative-patches) are one-shot-benchmark cost
artifacts that Clade's event-sourced, auto-committing, iterating loop renders moot.

## References

- [Introducing Sonar Foundation Agent — SonarSource blog](https://www.sonarsource.com/blog/introducing-sonar-foundation-agent)
- [Sonar Foundation Agent — GitHub (technical report + README)](https://github.com/AutoCodeRoverSG/sonar-foundation-agent)
- [Sonar Foundation Agent Technical Report (PDF)](https://raw.githubusercontent.com/AutoCodeRoverSG/sonar-foundation-agent/main/technical_report.pdf) — Ruan & Zhang, SonarSource, 2025
- [Sonar Claims Top Spot on SWE-bench Leaderboard — press release](https://www.sonarsource.com/company/press-releases/sonar-claims-top-spot-on-swe-bench-leaderboard/)
- [AutoCodeRover: Autonomous Program Improvement (ISSTA 2024, arXiv 2404.05427)](https://arxiv.org/abs/2404.05427)
- [SWE-bench official leaderboard](https://www.swebench.com/)
