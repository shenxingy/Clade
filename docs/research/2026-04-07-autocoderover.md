---
title: AutoCodeRover — AST-Based Fault Localization for Automated Patch Generation
date: 2026-04-07
review_date: 2026-06-14
reconciled: 2026-06-18
status: integrated
integrated_items:
  - "SBFL pre-pass ranked suspect hints — DONE: worker_tldr.py:662 (_sbfl_prepass, traceback-frequency proxy for Ochiai)"
  - "Patch retry budget — only the LLM call, capped 3× — DONE: worker.py:588-590 (--continue reflection retry, MAX_REFLECTION_RETRIES=3 at worker.py:554; _run_with_context use_continue=True at worker.py:967)"
  - "SBFL honesty (audit re-review) — DONE (d389ed0): the prepass was traceback-FREQUENCY mislabeled as SBFL/Ochiai. Now counts DISTINCT failing tests per function (failing-test coverage) with an honest label — recursion no longer inflates one function."
reference_items:
  - "Structured AST search APIs exposed to the agent — SKIP: clade_search_class/clade_search_method/clade_search_code wired in mcp_server.py:337-403; residual file-scoped variants subsumed by native Grep/Read (already-equivalent)"
  - "Iterative context retrieval split from patch phase — SKIP: soft two-phase directive with phase-boundary checkpoint injected at worker_taskfile.py:372-383; hard process-split forces context re-hydration the native loop avoids (different-not-deficient)"
  - "Method-granularity full-body search vs signature-only TLDR — SKIP: clade_search_method returns full method bodies on demand (mcp_server.py:250, _ast_search_method); TLDR stays signature-only by design (compact one-shot snapshot), on-demand bodies subsume the gap"
  - "Explicit iteration cap + LLM-declared sufficiency signal — SKIP: replaced by phase-boundary checkpoint gate (worker_taskfile.py:372-383, 'not arbitrary token count'); native agent loop has no fixed round budget by design (different-not-deficient)"
needs_work_items: []
---

# AutoCodeRover — AST-Based Fault Localization for Automated Patch Generation

## Core Approach

AutoCodeRover (Zhang et al., ISSTA 2024, arXiv 2404.05427) is a two-phase autonomous software engineering system. Its defining insight: treat the codebase as a structured program (an AST) rather than a flat collection of files. This lets the agent answer "what methods exist in class Foo?" or "where is this snippet used?" without reading entire files.

**Phase 1 — Context Retrieval**: An LLM agent is given the issue description and seven AST-backed search APIs. It issues API calls iteratively (up to 10 rounds), building a compact context of relevant classes, methods, and snippets. Each round the agent decides: enough context, or search further?

**Phase 2 — Patch Generation**: A second LLM agent receives only the frozen context from Phase 1 plus identified bug locations, and generates a patch diff. It may retry up to three times if syntax or format validation fails.

When a test suite is available, an optional pre-pass runs spectrum-based fault localization (SBFL) to inject ranked suspect methods into Phase 1 — narrowing search space before the agent begins.

**Cost efficiency**: AutoCodeRover averages ~37–39k tokens, $0.43–$0.45 per task at pass@1. SWE-agent averages ~240–245k tokens, $2.46–$2.51 — roughly 6× more expensive for comparable resolution rates.

## Key Techniques

**Seven AST-backed search APIs (no grep — parsed AST index):**
- `search_class(cls)` — class signature anywhere in codebase
- `search_class_in_file(cls, f)` — scoped to one file
- `search_method(m)` — full method body anywhere
- `search_method_in_class(m, cls)` — scoped to a class
- `search_method_in_file(m, f)` — scoped to a file
- `search_code(c)` — code snippet with ±3 lines context anywhere
- `search_code_in_file(c, f)` — scoped to a file

APIs operate on a parsed AST index — prevents false positives from comments and string literals.

**Iterative retrieval with 10-round cap**: The agent declares sufficiency explicitly before Phase 2 begins. Termination is LLM-declared, not rule-based.

**SBFL pre-pass**: Given a failing test, runs all tests with coverage. Ochiai formula per method: `fails / sqrt((fails+passes) * fails)`. Top-N suspect methods injected as ranked hints. Method granularity (not statement) — LLM needs function-level context.

**Inline patch retry**: Format validation + Python syntax check after each patch attempt. Retry only the patch generation LLM call (not Phase 1). Up to 3 retries, picks best result.

## What Clade Already Has

- **AST-based TLDR**: `worker_tldr.py:_generate_code_tldr` walks Python AST and JS/TS regex, extracts class/function signatures — same structural intuition as AutoCodeRover.
- **Pre-hydration**: `worker.py:_pre_hydrate` front-loads deterministic context (GitHub issues, PRs) before agent starts — same principle as AutoCodeRover's Phase 1 pre-pass.
- **Reflection loop**: `worker.py:_run_lint_check` fires on failure, injects lint errors, re-runs agent up to `MAX_REFLECTION_RETRIES=3` — mirrors AutoCodeRover's patch retry.
- **Worktree isolation per worker**: More mature execution model than AutoCodeRover (which runs in a single repo context).
- **Tool subsets**: `_build_tool_flags` restricts available tools by task type — AutoCodeRover does not address this.

## Gaps — What Clade Could Adopt

### Gap 1: On-demand AST query APIs (large effort)
**Problem**: Clade's TLDR is a one-shot snapshot. The agent cannot ask follow-up structural questions.

**Adoption path**: Build a local MCP tool (`clade_search`) backed by the existing `_parse_python_ast` infrastructure in `worker_tldr.py`. Expose AutoCodeRover's seven APIs. Register in `.claude/mcp.json` so workers can call it during their session. The AST index already exists — it just needs to become queryable rather than a one-shot dump.

### Gap 2: Two-phase separation (medium effort)
**Problem**: Clade sends the agent a single task file, handling everything in one pass.

**Adoption path**: Add a `phase` parameter to the task file template. Phase 1 task: "Explore the codebase and output a structured bug location report." Phase 2 task: "Given these bug locations, write the patch." Maps to Clade's existing worker mechanism — two sequential workers where Worker 2 receives Worker 1's output via `task_queue.send_message`.

### Gap 3: SBFL pre-pass (large effort)
**Problem**: Clade's lint check fires after a patch attempt fails. AutoCodeRover runs fault localization before the first attempt.

**Adoption path**: In `_build_task_file`, after `_pre_hydrate`, check if pytest is configured. If yes, run `pytest --cov`, identify failing tests, compute Ochiai scores, inject top-5 suspect methods as ranked hints into the task file. Pre-hydration step — no changes to the agent itself.

### Gap 4: Method-body retrieval vs. signature TLDR (medium effort)
**Problem**: `_generate_code_tldr` emits signatures only, truncated at 3000 chars. AutoCodeRover's `search_method` returns full implementation bodies.

**Adoption path**: Extend `_generate_code_tldr` with `include_bodies=True` flag. For small projects (<500 LOC), include all bodies. For larger projects, scope body inclusion to files mentioned in the issue or flagged by SBFL. Avoids truncation by scoping to high-suspicion files.

### Gap 5: Inline patch retry without subprocess restart (small effort)
**Problem**: Clade's reflection loop re-runs the entire `claude -p` subprocess on lint failure, discarding all intermediate reasoning.

**Adoption path**: In the reflection loop (`worker.py:~1138`), check if lint errors are syntax-only. If yes, inject lint output as a follow-up prompt to the same Claude Code session via `--continue` rather than a fresh `-p` invocation. Preserves agent context, significantly cheaper per retry.

### Gap 6: Iteration cap with sufficiency signal (small effort)
**Problem**: No cap on the initial exploration phase; agent may loop or terminate prematurely.

**Adoption path**: Add to Phase 1 task file: "You have at most 10 tool-call rounds. After each round, state explicitly whether you have enough context. When you do, output a structured bug location report and stop." Prompt-level change, no code modification.

## References

- [AutoCodeRover: Autonomous Program Improvement (arXiv 2404.05427)](https://arxiv.org/abs/2404.05427)
- [AutoCodeRover GitHub repository (nus-apr/auto-code-rover)](https://github.com/nus-apr/auto-code-rover)
- [AutoCodeRover ISSTA 2024 PDF](https://haifengruan.com/assets/pdf/autocoderover_issta24.pdf)
- [SBFL: Spectrum-Based Fault Localization (arXiv 2405.00565)](https://arxiv.org/abs/2405.00565)
