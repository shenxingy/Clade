# Claude Model Selection Guide

> Last updated: 2026-02-18

## Current Models

| Model | ID | Input / Output | Context | Max Output | Speed |
|-------|----|---------------|---------|------------|-------|
| **Opus 4.6** | `claude-opus-4-6` | $5 / $25 per MTok | 200K (1M beta) | 128K tokens | Medium |
| **Sonnet 4.6** | `claude-sonnet-4-6` | $3 / $15 per MTok | 200K (1M beta) | 64K tokens | Fast |
| **Haiku 4.5** | `claude-haiku-4-5` | $1 / $5 per MTok | 200K | 64K tokens | Fastest |

## Performance Benchmarks

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
