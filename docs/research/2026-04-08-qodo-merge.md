---
topic: Qodo Merge (PR-Agent) — Multi-Agent PR Review Patterns (2025)
date: 2026-04-08
status: needs_work
sources:
  - https://github.com/qodo-ai/pr-agent
  - https://qodo-merge-docs.qodo.ai/
  - https://www.qodo.ai/blog/introducing-qodo-2-0-agentic-code-review/
---

[English] | [Back to README](../../README.md)

# Qodo Merge — Multi-Agent PR Review Patterns (2025)

## Overview

Qodo Merge (formerly CodiumAI PR-Agent) is an AI-powered PR review tool that uses **parallel specialized agents** with a judge-phase reconciliation. Key insight: single-pass "approve/reject" review misses too much — different dimensions (bugs, security, test coverage, maintainability) require different prompting strategies.

Clade currently has: `_oracle_review()` (single-pass APPROVED/REJECTED + reason), `_write_pr_review()` (haiku diff summary). Both are single-pass and dimension-agnostic.

## Core Architecture

### 1. Parallel Specialized Agents

Qodo 2.0 runs 4+ agents simultaneously, each with a tuned prompt:
- **Bug detection agent**: focuses on logic errors, null handling, off-by-one
- **Security agent**: focuses on injection, auth, secret exposure
- **Test coverage agent**: checks if new code has tests; flags untested paths
- **Maintainability agent**: checks naming, complexity, code duplication

A **judge agent** post-processes all findings to eliminate duplicates and rank by confidence.

### 2. Token-Aware Chunking for Large PRs

Large PRs chunk into 32K-token segments. Each chunk generates 3 suggestions independently. Final output scales with complexity, not fixed count. Most PRs under 600 LOC process in a single call (~30 seconds).

**For Clade**: current diff[:3000] truncation loses context for large diffs.

### 3. Severity via Confidence, Not Labels

Findings are not pre-classified as "critical/warning/info." Instead:
- Higher-confidence findings (agent agreement + concrete fix) surface first
- Post-processing deduplication removes duplicate findings across agents
- Severity emerges from agent confidence score, not manual labeling

### 4. Remediation Prompts Per Finding

Each finding includes a `fix_suggestion` — a copy-paste prompt the author can feed to Claude/Copilot to fix the specific issue. This makes feedback actionable rather than just descriptive.

### 5. Audience Differentiation

- **For authors**: fix suggestions, inline code changes, specific line numbers
- **For maintainers**: effort estimates, risk level, compliance tracking
- PR history context: avoids re-flagging previously-accepted patterns

## How This Differs From Clade's Current Oracle

| Dimension | Clade Current | Qodo Merge Pattern |
|-----------|--------------|-------------------|
| Pass count | Single-pass | Parallel multi-agent |
| Output | APPROVED/REJECTED + 1 reason | Structured per-dimension scores |
| Fix guidance | 1-line reason | Per-finding fix_suggestion prompt |
| Large diffs | Truncated at 3000 chars | Proportional chunking |
| Confidence | Binary | Scored per finding (high/medium/low) |
| Dedup | None | Judge agent removes duplicates |

## Gaps vs Clade's Current Implementation

### §Gap 1 — Multi-Dimensional Oracle Scoring

Current `_oracle_review()` now returns structured JSON with 3 dimensions (correctness, completeness, code_quality). But it's still a single-pass review.

**Enhancement**: Run haiku in 2 passes: (1) factual check — does the code match the task spec? (2) quality check — are there obvious bugs/security issues? Reconcile both. Two haiku calls costs ~$0.002 total but catches more issues.

### §Gap 2 — Per-Finding Fix Suggestions

Oracle rejection currently returns a single `fix_guidance` string. For complex diffs, multiple issues may exist.

**Fix**: Return a `findings: [{dimension, severity, fix_suggestion}]` list. Worker applies fixes in order rather than re-doing everything.

### §Gap 3 — Diff Chunking for Large Changes

`_oracle_review` truncates diff at 3000 chars. A 500-line refactor loses most of the diff.

**Fix**: For diffs > 3000 chars, chunk into segments of 2000 chars, review each independently, merge findings. Already have the haiku call infrastructure.

### §Gap 4 — PR Review Audience Differentiation

`_write_pr_review()` posts a single review comment. The review targets reviewers, not the author.

**Enhancement**: Post two comments: (1) author-facing with actionable fix suggestions, (2) reviewer-facing with effort/risk summary. Use `gh pr comment` twice.

### §Gap 5 — Confidence-Scored Findings

Oracle returns binary decision. Multi-agent systems surface findings by confidence.

**Fix** (small): After structured oracle critique, add a `confidence` field per dimension: "high" (clear violation), "medium" (likely issue), "low" (style preference). Worker prioritizes fixing high-confidence issues first.

## Key Actionable Items

1. **§Gap 3 (diff chunking)** — Small effort. In `_oracle_review`, if diff > 3000 chars, chunk into 2000-char segments, review each, merge findings. Prevents large refactors from being auto-approved due to truncation.

2. **§Gap 2 (per-finding fixes)** — Medium effort. Extend oracle JSON schema to include `findings: list` array. Worker iterates over findings instead of treating rejection as monolithic.

3. **§Gap 5 (confidence scoring)** — Small effort. Add `confidence` field to each dimension in structured oracle response. Worker uses confidence to prioritize fix order.

4. **§Gap 1 (two-pass oracle)** — Medium effort. Split oracle into spec-check + quality-check sequential calls. Small cost increase, higher detection rate.

5. **§Gap 4 (audience differentiation)** — Low priority for now. Single comment is adequate for autonomous workflows.
