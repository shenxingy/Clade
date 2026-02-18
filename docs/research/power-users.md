# Power User Patterns Research

## Sources

- [Claude Code Official Docs](https://code.claude.com/docs/en/common-workflows)
- [Pro Workflow](https://github.com/rohitg00/pro-workflow) — battle-tested patterns from power users
- [Claude Code Creator's workflow](https://venturebeat.com/technology/the-creator-of-claude-code-just-revealed-his-workflow-and-developers-are) — VentureBeat article
- [OpenClaw GitHub org](https://github.com/openclaw) — 35 commits/day pattern
- [awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code) — curated plugin/skill list

---

## Claude Code Creator's Key Practices

1. **`/commit-push-pr`** — used dozens of times daily. Single command for version control bureaucracy.
2. **Specialized subagents** — `code-simplifier` for architecture cleanup, `verify-app` for E2E verification.
3. **Self-verification** — giving AI ability to verify its own work (run tests, browser automation) improves quality 2-3x.
4. **80/20 ratio** — 80% AI-written code, 20% human review/correction.

## Pro Workflow Framework

### Core Pattern: Self-Correction Loop
- Claude learns from user corrections automatically
- Proposes rules → stores in SQLite with FTS5 search
- Categories: Navigation, Editing, Testing, Git, Quality, Architecture
- Learnings surfaced before new tasks via `/replay`

### Wrap-Up Ritual
- End-of-session checklist
- `/handoff` generates structured documents for next session
- SessionEnd hook auto-saves metrics

### Split Memory (Modular CLAUDE.md)
- Break CLAUDE.md into functional modules for large projects
- Reduces token bloat in context window
- Templates for consistent structure

### 80/20 Batch Review
- Don't review every change immediately
- Batch reviews at checkpoints
- Adaptive quality gates that tighten/relax based on correction history

### Adaptive Quality Gates
- Track correction rate per category
- High correction rate → tighten gates (more verification)
- Low correction rate → relax gates (less friction)
- Visualized via heatmap

### Scout Agent (Pre-Implementation)
- Scores readiness 0-100 before coding
- Confidence-gated exploration
- Auto-gathers missing context before implementation starts

## OpenClaw Pattern (205K★, 35 commits/day)

### Observed Workflow
```
/review-pr → /prepare-pr → /merge-pr
```

### Characteristics
- Consistent semantic commit prefixes: `feat:`, `fix:`, `refactor:`, `test:`, `chore:`, `perf:`
- Batch systematic refactoring (extract helpers, dedup fixtures)
- Multiple parallel sessions (inferred from volume)
- Primary developer (steipete): ~28 commits/day
- No visible `Co-Authored-By: Claude` but patterns strongly suggest AI assistance

## incident.io Pattern (Blog: "Shipping Faster with Claude Code and Git Worktrees")

### Key Insight
- Run 3-4 Claude Code sessions in parallel via worktrees
- Each worktree = independent feature branch
- Human reviews merge PRs while Claude works on next feature
- Throughput multiplied by number of parallel sessions

### Setup
```bash
git worktree add ../project-feat-a -b feat/feature-a
git worktree add ../project-feat-b -b feat/feature-b
cd ../project-feat-a && claude
# In another terminal:
cd ../project-feat-b && claude
```

## Common Anti-Patterns to Avoid

1. **Giant context windows** — load everything into one session instead of using subagents
2. **No verification** — trust AI output without running tests
3. **Serial everything** — one task at a time instead of parallel worktrees
4. **Manual quality checks** — not using hooks to automate lint/type-check
5. **Repeating mistakes** — not recording lessons learned (no PROGRESS.md equivalent)
6. **Over-planning** — spending more time planning than executing
7. **No rollback strategy** — batch tasks with no checkpoint/recovery

## Patterns We Should Adopt (Priority Order)

### Immediate
1. **Hooks** — PostToolUse type-check, Stop verification, Notification alerts
2. **batch-tasks resilience** — timeout, retry, rollback, issue reporting
3. **Custom subagents** — code-reviewer with persistent memory

### Short-term
4. **`/commit-push-pr` skill** — single command for commit → push → PR
5. **SessionStart context loading** — auto-inject git status, recent errors
6. **TaskCompleted quality gate** — must pass type-check before completing

### Medium-term
7. **Self-correction memory** — track corrections, surface before new tasks
8. **Parallel worktree sessions** — 2-3 concurrent Claude sessions for independent features
9. **Agent teams** — coordinated parallel agents for large tasks

### Long-term
10. **Browser verification** — Playwright smoke tests after UI changes
11. **Adaptive quality gates** — tighten/relax based on error rates
12. **Scout agent** — readiness scoring before implementation
