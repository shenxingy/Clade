---
title: Agentless — UIUC 2024
date: 2026-04-07
status: needs_work
integrated_items:
  - item: Pre-hydration context fetch before worker starts (_pre_hydrate in worker.py)
    clade_location: orchestrator/worker.py:528 — fetches linked GitHub issues/PRs into task prompt
  - item: Hierarchical localization concept (repo structure → files → functions → lines)
    clade_location: orchestrator/worker_tldr.py — _generate_code_tldr() extracts file+function structure for context injection
  - item: Multi-sample patch generation via LLM temperature
    clade_location: orchestrator/worker.py — reflection loop retries (up to MAX_REFLECTION_RETRIES) with lint context
  - item: Patch validation with test filtering
    clade_location: orchestrator/worker.py — verify_and_commit() + oracle review (_oracle_review in worker_review.py)
needs_work_items:
  - item: Three-phase pipeline as explicit first-class objects (Localize → Repair → Validate nodes)
    gap: Clade runs as a single worker prompt — no explicit Localize phase before Repair. Worker gets the whole task prompt and is expected to self-navigate. Agentless separates these into three deterministic phases with LLM calls at each boundary.
    effort: large
  - item: Hierarchical file localization as structured JSON output
    gap: Clade uses TLDR (function signatures) as context injection but does not produce structured JSON of "suspected files → classes → lines" before the repair phase. Agentless produces a ranked list of suspect locations that constrains the repair LLM.
    effort: medium
  - item: Patch sampling + majority-vote re-ranking
    gap: Clade reflection loop retries sequentially (up to 3×). Agentless generates 40 patches (4 location sets × 10 samples) and picks the best via test re-ranking. Clade could generate N candidate patches with haiku and pick via oracle.
    effort: medium
  - item: Reproduction test generation as patch filter
    gap: Agentless generates a reproduction test for the original issue, uses it to filter candidate patches. Clade has _run_lint_check() but no reproduction test generation. This would significantly improve fix quality.
    effort: medium
---

# Agentless — UIUC 2024 Research Notes

**Date**: 2026-04-07
**Paper**: arXiv:2407.01489 — "Agentless: Demystifying LLM-based Software Engineering Agents"
**Authors**: Chunqiu Steven Xia, Yinlin Deng, Soren Dunn, Lingming Zhang (UIUC)
**GitHub**: https://github.com/OpenAutoCoder/Agentless
**Benchmark**: SWE-bench Lite (300 real GitHub issues from 11 popular Python repos)

---

## 1. Core Thesis

Agentless challenges the assumption that AI coding agents need complex autonomous action loops. The paper demonstrates that a **structured, non-agentic pipeline** (the LLM never picks its next action) can outperform agent-based systems on SWE-bench while costing 10× less.

Key claim: most SWE-bench failures are from incorrect fault localization, not repair ability. Solving localization correctly is more valuable than giving the LLM more tools.

---

## 2. Three-Phase Pipeline

### Phase 1: Hierarchical Localization

Three nested LLM calls, each narrowing scope:

1. **File-level**: Given repo structure (file tree), ask LLM to rank suspicious files
2. **Class/Function-level**: For each suspicious file, extract skeleton (function signatures, class defs) → ask LLM to identify suspicious classes/functions
3. **Line-level**: For each suspicious function, show ±10 lines → ask LLM to produce exact edit locations as JSON

Output: structured JSON of `{file, class, function, start_line, end_line}` tuples.

This is deterministic and reproducible — the same issue gets the same localization on re-run (modulo LLM randomness).

### Phase 2: Repair (Patch Generation)

- 4 separate location sets (due to 4-sample localization draw)
- For each location set: generate 10 patches (1 greedy + 9 sampled at temperature 0.8)
- Format: unified diff (git diff format)
- Total: up to 40 candidate patches per issue

No tool use. No agent loop. Just: `{issue description} + {localized code context} → diff`.

### Phase 3: Validation + Re-ranking

1. **Syntax filter**: discard patches that fail to apply or have syntax errors
2. **Regression test filter**: run existing repo tests — discard patches that break them
3. **Reproduction test**: generate a test that reproduces the original bug → use it to filter patches that don't fix the issue
4. **Majority vote re-ranking**: among surviving patches, pick the one that appears most often (or best test pass rate)

Final output: one patch submitted to SWE-bench judge.

---

## 3. Performance Results

| Approach | SWE-bench Lite | Cost/issue |
|---|---|---|
| Agentless (GPT-4o) | 27.33% | $0.34 |
| Agentless (Claude 3.5 Sonnet, Dec 2024) | 40.7% | ~$0.70 |
| Best agent-based (open-source, 2024) | ~22% | $3.34 |
| Agentless + fine-tuned SWE LLM (2025) | 60.4% | N/A |

The approach scales well with better base models: switching from GPT-4o to Claude 3.5 Sonnet gives a +13 point improvement with no architectural changes.

---

## 4. Key Design Decisions (Clade-relevant)

### Separation of Localization and Repair
Most agent approaches give the agent both responsibilities. Separating them into deterministic phases with structured JSON handoffs between them:
- Makes failures debuggable (was it a localization failure or repair failure?)
- Allows independent optimization of each phase
- Removes the agent's ability to "distract itself" following wrong tool calls

**Clade analogy**: `_build_task_file()` injects TLDR context but doesn't structurally constrain the worker to specific files/lines. A localization pre-pass (producing a JSON struct) before the repair worker prompt would tighten focus.

### Skeleton-based Context Injection
Rather than sending entire files, Agentless sends "skeletons" — just signatures and docstrings, not implementations. This matches Clade's `_generate_code_tldr()` approach in `worker_tldr.py`, which extracts function signatures rather than full file content.

### Reproduction Test Generation
Agentless automatically writes a failing test that proves the bug exists. This test is used both to filter patches and to verify the fix. Clade has `_run_lint_check()` for static analysis but no dynamic reproduction test generation. This is a significant quality gap.

### Patch Sampling at Temperature 0.8
Multiple samples are cheap (parallel API calls) and dramatically improve coverage. Clade's reflection loop is sequential (attempt 1 → lint error → attempt 2). Generating N=10 parallel patches with haiku then picking the best via oracle would be more cost-effective.

---

## 5. What Clade Already Does Well

- **Pre-hydration** (`_pre_hydrate`): fetches linked GitHub issues/PRs before worker starts — analogous to Agentless gathering issue description context before localization
- **TLDR code context** (`worker_tldr.py`): skeleton-style extraction of function signatures — analogous to Agentless phase 1 skeleton extraction
- **Verify-and-commit** (`verify_and_commit`): runs tests and oracle review after patch generation — analogous to Agentless validation phase
- **Reflection loop**: retry with lint context — partial analogue to patch re-ranking (sequential, not parallel)
- **Worktrees**: each worker in isolated git worktree — avoids patch interference (Agentless runs in isolated repo copies)

---

## 6. Clade Integration Opportunities

### Opportunity A: Structured Localization Pre-pass (medium effort)
Before the main worker prompt, run a haiku call with the repo TLDR → produce JSON of `{suspect_files, suspect_functions}` → inject as additional context into the worker's task prompt. This narrows focus without requiring a full architecture change.

```python
# In _build_task_file(), after _generate_code_tldr():
suspect_locs = await _localize_fault(self.description, tldr, self._project_dir)
if suspect_locs:
    context_blocks.append(f"# Suspected Change Locations\n\n{suspect_locs}")
```

### Opportunity B: Reproduction Test Generation (medium effort)
In `_on_worker_done()`, before verify-and-commit, attempt to generate a failing test from the task description with haiku. If successful, run it to confirm the fix landed.

### Opportunity C: Parallel Patch Sampling via Swarm (large effort)
For high-priority tasks, spawn N=3 swarm workers with different temperature seeds, then pick the winner via oracle. This requires SwarmManager coordination. The oracle already exists (`_oracle_review`).

---

## 7. Sources

- Paper: https://arxiv.org/abs/2407.01489
- GitHub: https://github.com/OpenAutoCoder/Agentless
- Kimi-Dev (Agentless as skill prior): https://arxiv.org/html/2509.23045v2
