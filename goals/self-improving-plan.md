# Goal: Design the Self-Improving Claude Code System

## Vision

Make Claude Code sessions get measurably better over time — like training a model, but with interpretable, editable "weights" (CLAUDE.md, hooks, corrections, memory).

The output of this loop is a single, comprehensive plan document at `docs/plans/2026-02-25-self-improving-system.md`.

## What exists today (audit these first)

- [x] **Audit corrections system** — read `configs/hooks/correction-detector.sh`, `templates/corrections/rules.md`, understand how corrections are captured, stored, and applied. Document gaps.
- [x] **Audit hooks pipeline** — read all hooks in `configs/hooks/`, understand the full lifecycle (session-start → pre-tool → post-tool → stop). What signals are captured? What's missing?
- [x] **Audit memory system** — check `~/.claude/projects/*/memory/`, understand what's persisted across sessions. Is it used effectively?
- [x] **Audit CLAUDE.md evolution** — read `templates/CLAUDE.md` and the user's `~/.claude/CLAUDE.md`. How do lessons graduate from corrections → CLAUDE.md?
- [x] **Audit /audit skill** — read `configs/skills/audit/`, understand what it already does. What should it do that it doesn't?

## Plan requirements (what the plan document must contain)

- [x] **Architecture diagram** — ASCII diagram showing the full feedback loop: signal capture → pattern recognition → rule extraction → deployment → verification
- [x] **Signal taxonomy** — categorize ALL feedback signals (explicit corrections, implicit edits, reverts, manual file changes, test failures, hook rejections). For each: how to capture, confidence level, volume.
- [x] **Rule lifecycle** — design the full lifecycle: raw signal → candidate rule → validated rule → CLAUDE.md principle → hook enforcement. Include graduation criteria and retirement criteria.
- [x] **Eval framework** — how to measure if Claude Code is actually improving. Propose concrete metrics (correction rate, revert rate, user edit rate, session scorecard).
- [x] **Implementation roadmap** — break down into 3 phases: Quick Wins (< 1 day), Medium (1 week), Long-term (ongoing). Each item must be specific enough to become a TODO task.
- [x] **Anti-patterns** — what NOT to do (rule explosion, overfitting to one user's quirks, context window bloat, false positive hooks)

## Constraints

- Plan must be actionable within THIS project (claude-code-kit)
- Each phase item must specify which files to create/modify
- Total plan document should be 200-400 lines — comprehensive but not bloated
- Build on existing infrastructure, don't redesign from scratch

## Output

Write the complete plan to: `docs/plans/2026-02-25-self-improving-system.md`
