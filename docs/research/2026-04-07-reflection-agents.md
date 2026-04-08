---
topic: Reflection Agents and Self-Critique Patterns for Code Generation (2025)
date: 2026-04-07
status: needs_work
sources:
  - https://arxiv.org/abs/2303.11366  # Reflexion (Shinn et al. 2023)
  - https://arxiv.org/abs/2310.11511  # Self-RAG (Asai et al. 2023)
  - https://arxiv.org/html/2602.02584  # Constitutional Spec-Driven Dev
---

[English] | [Back to README](../../README.md)

# Reflection Agents and Self-Critique Patterns for Code Generation (2025)

## Overview

Reflection agents move beyond single-pass generation or blind retry toward **structured self-evaluation and iterative refinement**. All effective patterns share one structure: **decoupled generation and critique** — the critique signal feeds back into generation without external human feedback or model fine-tuning.

Clade currently has: oracle review (second-model diff review), lint reflection loop, `--continue` for retries. These cover basic reflection but lack episodic failure memory, semantic spec validation, and multi-dimensional critique.

## Core Patterns

### 1. Reflexion — Verbal Reinforcement Learning (Shinn 2023)

Maintains an **episodic memory buffer** of prior failures as natural language. When a task fails, the agent generates a reflection:

> "I used `list.append()` instead of `list.extend()`, causing incorrect nesting. The spec requires flat arrays."

This reflection is prepended to the next retry prompt. Acts as a lightweight semantic gradient without fine-tuning.

**Key difference from simple retry**: Agent has explicit context about its failure *mode*, not just that it failed.

**For Clade**: After a worker fails lint/test/oracle, capture a structured reflection and inject into next retry. Currently Clade only injects the lint output, not a reasoning about WHY it failed.

### 2. Self-RAG — Multi-Dimensional Critique Tokens (Asai 2023)

Learnable reflection tokens predicted alongside generation:
- `ISREL` — is this retrieval relevant?
- `ISSUP` — does evidence support this claim?
- `ISUSE` — is this output useful?

**For code generation**: after generation, agent internally rates:
- `spec_adherence` — response fields match spec?
- `type_safety` — types correct?
- `lint_compliance` — passes linter?

If any token low-confidence, triggers targeted re-generation on that dimension only.

**Key difference**: Multi-dimensional critique tells the agent *which aspect* failed (types vs. spec vs. lint), enabling targeted fixes instead of blanket regeneration.

### 3. Recursive Debugging Agent

Closed-loop agent that **observes test failures and patches minimally**:

1. Run tests → capture stderr
2. Parse: `{file: "app.py", line: 42, error: "TypeError: 'NoneType'"}`
3. Generate **minimal patch** (not full replacement)
4. Re-run tests to verify fix
5. If new failures: repeat with ceiling

**Key difference**: Simple retry regenerates the whole module. Recursive debugging generates the **minimal diff** needed to fix one specific failure, then verifies.

**For Clade**: `_run_lint_check()` returns lint output. The `_run_with_context()` re-runs the full agent. The gap: no minimal-patch generation targeting one specific failure.

### 4. Constitutional AI for Code

Applies user-defined principles as self-critique constraints:

```yaml
Code Constitution:
  - "All external API calls must use exponential backoff"
  - "Database writes must specify transaction isolation"
  - "Worker timeouts must be explicit in task config"
```

Agent generates code, then critiques against principles deterministically. Principle violations trigger **targeted** regeneration (not full retry).

**Result**: Reduces security defects 73% vs. unconstrained generation in controlled studies.

**For Clade**: CLAUDE.md has coding rules, but they're only injected once at prompt time. A constitutional check *after* generation would catch violations the agent missed.

### 5. Spec-Driven Validation Loop

Treats the specification as ground truth. Validates generated code against spec *before* oracle review:

```
Spec: POST /api/users → 201 {id, email, createdAt}
Generated: POST /api/users → 200 {userId, mail}
Critic: "Status 200≠201; field 'mail' should be 'email'"
Retry: targeted fix for schema mismatch
```

**Two-stage critique**: semantic validation (spec) first, then quality review (oracle). Fails fast on spec violations without wasting oracle budget.

## How Each Pattern Differs From Simple Retry

| Pattern | What's Different |
|---------|-----------------|
| Reflexion | Natural language memory of failure MODE; prepended to next prompt |
| Self-RAG | Multi-dimensional critique tokens; targeted re-generation per dimension |
| Recursive Debugging | Minimal patch → verify fix → iterate; bounded loop |
| Constitutional AI | Deterministic principle-based critique; agent knows WHY it failed |
| Spec-Driven | Validation against concrete spec; violations are actionable schema diffs |

## Gaps vs Clade's Current Implementation

**Clade has:**
- Oracle review — post-hoc diff review (quality)
- Lint reflection — reactive, surface-level (syntax)
- `--continue` retries — preserves agent context

**Clade lacks:**

### §Gap 1 — Episodic Failure Memory (Reflexion)

Each retry is stateless. No structured reflection captures WHY the previous attempt failed.

**Fix**: In `_run_with_context()`, before the retry prompt, add a structured "failure reflection" block:
```
## Failure Analysis
- Previous attempt: [what was tried]
- Why it failed: [lint/test/oracle said: ...]
- What to do differently: [derived from failure type]
```
Small code change. Haiku generates the analysis from lint/oracle output.

### §Gap 2 — Multi-Dimensional Critique in Oracle (Self-RAG)

`_oracle_review()` returns binary APPROVED/REJECTED with a free-form reason.

**Fix**: Return structured critique JSON:
```json
{
  "decision": "REJECTED",
  "dimensions": {
    "spec_adherence": "fail — response uses 'mail' not 'email'",
    "type_safety": "pass",
    "test_coverage": "warn — 2 edge cases not covered"
  },
  "fix_guidance": "Rename 'mail' field to 'email' in response schema"
}
```
Worker receives specific dimension failures → targeted fix instead of full regeneration.

### §Gap 3 — Minimal-Patch Reflection Loop (Recursive Debugging)

Current reflection loop re-runs the full agent with lint errors. Agent often re-writes large sections unnecessarily.

**Fix**: Parse lint output to extract specific `file:line:error`, then use `--continue` with a minimal directive:
```
Fix this specific error only: path/to/file.py:42: error: undefined name 'foo'
Do not modify anything else.
```
This constrains the agent to a targeted fix, reducing the risk of introducing new errors.

### §Gap 4 — Constitutional Check After Generation

CLAUDE.md rules injected at prompt start. Agent may drift from them mid-generation.

**Fix**: After `verify_and_commit()` produces a diff, run a quick haiku check against CLAUDE.md's "Code Rules" section. If violations found, inject as high-priority fix context before committing.

### §Gap 5 — Spec-Driven Pre-Generation Checklist

No spec parsing before workers start. Workers derive intent from task description only.

**Fix (small)**: For tasks referencing GitHub issues (pre-hydrated), extract acceptance criteria as a bullet checklist and append to task file. Worker can check items off and agent knows it succeeded when all pass.

## Key Actionable Items

1. **§Gap 1 (episodic failure memory)** — Most valuable, smallest effort. Add structured failure analysis block to `_run_with_context()` retry prompt. Haiku generates it from lint output in <5 lines.

2. **§Gap 3 (minimal-patch reflection)** — Small effort. Parse lint output for specific file:line locations. Send targeted `--continue` prompt pointing to exact location. Prevents unnecessary full re-writes.

3. **§Gap 2 (structured oracle critique)** — Medium effort. Extend `_oracle_review()` to return JSON with dimension scores. Worker handles each failure dimension with targeted prompt.

4. **§Gap 4 (constitutional check)** — Medium effort. Post-generation CLAUDE.md rule validation via haiku call. Only on rules with verifiable syntax patterns.

5. **§Gap 5 (acceptance criteria extraction)** — Small effort. Extend `_pre_hydrate()` to extract "Acceptance Criteria" / "Definition of Done" items from GitHub issues as a checklist appended to task file.
