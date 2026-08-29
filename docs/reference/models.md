# Claude Model Selection Guide

---
name: models.md
date: 2026-02-18
status: integrated
review_date: 2026-11-30
summary:
  - "Claude model benchmarks, cost-performance analysis, and selection guidelines"
integrated_items:
  - "Model selection table (Sonnet/Haiku/Opus) — batch-tasks skill 有完整实现，包含 SWE-bench 基准数据"
  - "Cost-performance guidance — session-context.sh 有实现（line 153），注入到每次 session"
  - "Model research skill — configs/skills/model-research/ 存在，研究建议没有这个，Clade 更好"
needs_work_items: []
reference_items: []

## Current Models

Mirrors `orchestrator/config.py:_MODEL_ALIASES` and `_MODEL_RATES`, which are
the source of truth; `configs/models.env` carries the same ids for the shell
layer. Verified 2026-08-29.

| Model | ID | Input / Output | Context | Max Output |
|-------|----|---------------|---------|------------|
| **Fable 5** | `claude-fable-5` | $10 / $50 per MTok | 1M | 128K tokens |
| **Opus 5** | `claude-opus-5` | $5 / $25 per MTok | 1M | 128K tokens |
| **Sonnet 5** | `claude-sonnet-5` | $3 / $15 per MTok | 1M | 128K tokens |
| **Haiku 4.5** | `claude-haiku-4-5` | $1 / $5 per MTok | 200K | 64K tokens |

Clade's aliases resolve `opus` → Opus 5, `sonnet` → Sonnet 5, `haiku` → Haiku
4.5. Superseded ids (`claude-opus-4-8`/`4-7`/`4-6`, `claude-sonnet-4-6`) stay
accepted so older task rows and evidence bundles keep resolving.

## Performance Benchmarks — 4.6 generation, recorded 2026-02-18

Kept as the measurement that produced the routing rule below, NOT as current
figures. No verified SWE-bench/OSWorld numbers for the 5 generation were to
hand when this was revised on 2026-08-29, and inventing them to keep the
section looking current would be worse than saying so.

### Coding (SWE-bench Verified)
- Opus 4.6: **80.8%**
- Sonnet 4.6: **79.6%** (delta: 1.2 pts)
- Haiku 4.5: ~65%

### Agent / Computer Use (OSWorld)
- Opus 4.6: **72.7%**
- Sonnet 4.6: **72.5%** (essentially tied)

### Key Insight
Sonnet 4.6 matches Opus 4.6 on most coding and agent benchmarks at 60% of the cost and higher speed. Opus 4.6 retains an edge in deep reasoning, large-scale refactoring, and tasks requiring very long outputs (128K vs 64K max).

## Cost-Performance Matrix

Relative cost per task (estimated by typical token usage):

| Task type | Haiku | Sonnet | Opus | Best value |
|-----------|-------|--------|------|------------|
| Simple edit (<20 lines, 1 file) | $0.01 | $0.03 | $0.05 | **Haiku** |
| Standard feature (2-4 files) | $0.05 | $0.15 | $0.25 | **Sonnet** |
| Complex feature (5+ files) | $0.10 | $0.30 | $0.50 | **Sonnet** |
| Large refactor (10+ files, cross-cutting) | — | $0.50 | $0.80 | **Opus** |
| Architecture design / deep reasoning | — | $0.40 | $0.70 | **Opus** |

## Model Selection Rules

### For interactive sessions (`/model` in Claude Code)

| Scenario | Recommended | Reason |
|----------|-------------|--------|
| Daily coding (features, bugs, refactoring) | **Sonnet 4.6** | ~Same quality as Opus, 40% cheaper, faster |
| Large-scale refactoring (10+ files, legacy code) | **Opus 4.6** | Deeper reasoning for complex cross-file patterns |
| Architecture design, complex system decisions | **Opus 4.6** | 128K max output, stronger on multi-step reasoning |
| Quick lookups, simple edits, formatting | **Sonnet 4.6** | Haiku can't be used as main model in Claude Code |

### For batch-tasks (`model:` per task)

| Criteria | Model | Timeout |
|----------|-------|---------|
| 1 file, mechanical change (<20 lines): deletions, renames, typo fixes, import cleanup | `haiku` | 300s |
| 1-2 files, simple but needs understanding: add a field, update a config, write a test | `haiku` | 300s |
| 2-4 files, standard feature with clear pattern: new endpoint, component, form field | `sonnet` | 600s |
| 4-8 files, multi-component feature: feature with API + UI + schema + tests | `sonnet` | 900s |
| 5+ files, architectural: refactor auth system, cross-cutting concern, state management redesign | `opus` | 1200s |
| Ambiguous / requires deep codebase understanding: "improve performance", "fix flaky tests" | `opus` | 1200s |

**Default: `sonnet`** — only use `opus` when the task genuinely requires deep multi-file reasoning. Use `haiku` aggressively for mechanical changes.

### For sub-agents (agent frontmatter)

| Agent type | Model | Reason |
|------------|-------|--------|
| Type-checking, linting (mechanical) | `haiku` | No reasoning needed, just run and report |
| Test execution (mechanical) | `haiku` | Same — run and parse |
| Code review (reasoning) | `sonnet` | Needs to understand patterns and suggest improvements |
| App verification (reasoning) | `sonnet` | Needs to understand what changed and why it might break |

## When to Switch Models (interactive session)

Signs you should switch to Opus:
- You're about to refactor a module that touches 10+ files
- You need Claude to understand a large legacy codebase it hasn't seen
- The task requires reasoning about subtle interactions across multiple systems
- You need very long outputs (>64K tokens)

Signs you should stay on / switch to Sonnet:
- Normal feature development, bug fixes, tests
- The task is well-defined with clear patterns to follow
- You want faster responses during iterative development
- Cost matters (Sonnet is 40% cheaper)

## Sources

- [Anthropic: Claude Sonnet 4.6 announcement](https://www.anthropic.com/news/claude-sonnet-4-6)
- [Claude models overview](https://platform.claude.com/docs/en/about-claude/models/overview)
- [VentureBeat analysis](https://venturebeat.com/technology/anthropics-sonnet-4-6-matches-flagship-ai-performance-at-one-fifth-the-cost/)
