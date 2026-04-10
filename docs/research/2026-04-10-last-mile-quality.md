---
title: "Last-Mile Quality in AI-Assisted Development"
date: 2026-04-10
status: processed
needs_work_items:
  - "Sprint contracts (pre-negotiated done criteria) — not yet in Clade worker task files"
  - "Separate evaluator agent — oracle exists but is same-model; external skeptical evaluator missing"
  - "Iteration cap at 3 with human checkpoint — no hard cap today (stuck_timeout_minutes only)"
  - "Behavioral (E2E) verification — unit tests only; no browser/live-env check"
  - "Context reset protocol over compaction — agents show 'context anxiety' near limit"
  - "Code Health baseline gate — no pre-agentic health check before spawning workers"
  - "Fix Rate metric (not binary pass/fail) — only Resolved Rate tracked today"
---

# Last-Mile Quality in AI-Assisted Development

## The Problem (Consensus Definition)

The "last mile" / "80% problem" / "烂尾" describes the gap between AI-generated code that
compiles/demos and code that is actually shippable. AI amplifies throughput while
proportionally amplifying defect volume, and agents have no reliable internal mechanism
for knowing when work is actually done.

## Key Statistics

- Only 68.3% of AI-generated projects execute out-of-the-box (Python: 89.2%, JavaScript: 61.9%, Java: 44.0%)
- AI-created PRs have 1.7× more bugs, 1.64× more maintainability errors, 75% more logic errors per 100 PRs
- GPT-5: 65% on isolated SWE-Bench Verified → only 21% on multi-step SWE-EVO tasks
- Security vulnerabilities increase 37.6% after just 5 iterations of AI "improvements"
- Without structural guidance: agents fix ~20% of code health issues. With MCP-augmented feedback: 90-100%

## Root Causes of "烂尾"

1. **Assumption propagation** — agent misunderstands requirements early, builds on faulty premise; problems surface "5 PRs deep"
2. **Self-evaluation failure** — agents "confidently praise their own mediocre work" (Anthropic internal finding)
3. **Context decay** — long sessions forget early context; "context anxiety" causes premature wrap-up
4. **No pre-agreed done criteria** — vague goal + agent decides when it's "done" = guaranteed mismatch
5. **Iteration degradation** — security/quality degrade after 3–5 rounds; code looks more sophisticated but has more bugs
6. **Behavioral gap** — unit tests pass ≠ feature correct; agents never verify "as a real user would"
7. **Comprehension debt** — developer loses ability to maintain code they never understood

## Proven Patterns (Evidence-Ranked)

### 1. Sprint Contracts (Anthropic harness — strongest evidence)
Pre-negotiate specific measurable acceptance criteria BEFORE implementation begins.
Generator and evaluator agree on hard thresholds. Any failure triggers new sprint.
"What success looks like" is separated from implementation.

### 2. Separate Evaluator Agent (Anthropic harness)
One agent generates. A SEPARATE agent audits — tuned to be skeptical, without access
to the generator's reasoning. Self-evaluation is systematically unreliable.

### 3. Iteration Cap at 3 (arXiv:2506.11022)
Hard cap: after 3 consecutive LLM-only iterations, require human checkpoint.
Security degrades 37.6% after 5 iterations. Early iterations have positive ROI only.

### 4. Behavioral (E2E) Verification (Anthropic harness)
Must verify features "as a human user would" — browser automation, live environment.
Unit test passage ≠ feature correctness. Playwright + sprint contract criteria.

### 5. Context Reset > Compaction (Anthropic harness)
Clean context + explicit progress file outperforms compaction for long sessions.
Agents show "context anxiety" and prematurely wrap up as context approaches limit.

### 6. TDD-First (DORA 2025)
Write tests before implementation. Pass/fail oracle exists before agent starts.
TDD is the specific amplifier that makes AI quality gains real vs. illusory.

### 7. Code Health Baseline Gate (CodeScene)
Establish Code Health ≥ 9.4 baseline BEFORE deploying agents on a codebase.
Defect risk increases 30%+ in structurally unhealthy code.

### 8. Fix Rate Metric > Binary Pass/Fail (SWE-EVO paper)
Track % of FAIL_TO_PASS tests repaired per iteration, not just "resolved/not resolved".
Reveals systematic progress invisible to binary scoring.

## Emerging "Definition of Done" (2025-2026 consensus)

1. All pre-negotiated sprint contract acceptance criteria pass
2. Automated tests pass (unit + integration + E2E behavioral)
3. Code Health score meets or exceeds baseline (no structural regression)
4. Static analysis, linter, type checker pass (CI gates)
5. External evaluator confirms WITHOUT access to generator's reasoning
6. Developer can read and explain the generated code (comprehension gate)
7. No iteration chain longer than 3 without human review checkpoint
8. PR submitted and reviewed

## Key Sources

- arXiv:2512.05239 — Bug survey (8 categories, functional bugs dominant)
- arXiv:2512.22387 — 68.3% reproducibility baseline
- arXiv:2512.18470 — SWE-EVO: 21% multi-step completion rate
- arXiv:2506.11022 — 37.6% security degradation after 5 iterations
- Anthropic: Effective Harnesses for Long-Running Agents (sprint contracts, separate evaluator)
- Addy Osmani: The 80% Problem in Agentic Coding
- CodeScene: Agentic AI Coding Best Practice Patterns
- DORA 2025: TDD as the quality amplifier
- CodeRabbit: 1.7× bug rate in AI PRs
