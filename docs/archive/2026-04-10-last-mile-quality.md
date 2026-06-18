---
title: "Last-Mile Quality in AI-Assisted Development"
date: 2026-04-10
reconciled: 2026-06-18
status: integrated
integrated_items:
  - "Sprint contracts (pre-negotiated done criteria) — DONE: config.py:595 _parse_task_schema parses acceptance_criteria; injected into task file at worker_taskfile.py:366 and threaded to oracle grader at worker_review.py:332"
  - "Behavioral (E2E) verification — DONE: configs/scripts/setup-browser-verify.sh wires Playwright MCP; worker_taskfile.py:52 FRONTEND_VISUAL_BLOCK injects browser self-verify for frontend projects; configs/agents/verify-app.md"
  - "Fix-Rate per-iteration metric — DONE (commit 32556fd): loop-runner.sh parses pytest failed-counts in node_test_sample and logs the per-iteration failed→failed delta to `$LOG_DIR/fix-rate.tsv`, summarized in the loop report"
reference_items:
  - "Separate evaluator agent — SKIP: oracle is same-model by design (worker_review.py), but cross-vendor skeptical evaluators exist as configs/agents/second-opinion-codex.md + second-opinion-gemini.md ('breaks the generator/reviewer same-vendor blind spot'). On-demand cross-vendor agent vs always-on harness evaluator — different mechanism, adequate."
  - "Iteration cap at 3 with human checkpoint — SKIP: hard cap exists — MAX_REFLECTION_RETRIES=3 (worker_utils.py:34, worker.py:554) on the reflection loop; loop skill enforces 'max 3 consecutive empty iterations → stop' + 3-strike human-checkpoint escalation (configs/skills/loop/prompt.md:94,241). Original 'stuck_timeout only' claim is stale."
  - "Context reset protocol over compaction — SKIP: /handoff (clean progress doc) + /pickup pattern is recommended before /compact (configs/skills/handoff/prompt.md:13); compression_feedback.py counters context-anxiety; session_tree.py records compaction boundaries. Handoff-doc-then-fresh-session IS reset-over-compaction."
  - "Code Health baseline gate — SKIP: test-pass baseline captured pre-edit via _capture_test_baseline (worker_taskfile.py:404) + intramorphic regression block (worker_utils.py:461). Behavioral baseline-before-agent + regression gate vs CodeScene's static Code-Health≥9.4 score — different metric, same don't-regress purpose."
needs_work_items: []
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
