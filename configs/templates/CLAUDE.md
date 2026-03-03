# Project Type
- Type: [web-fullstack | api-only | cli | ml-pipeline | library | skill-system | toolkit]
- Frontend: [framework + port, or N/A]
- Backend: [framework + port, or N/A]
- Test command: [e.g. pytest tests/ -v]
- Verify command: [e.g. ./scripts/smoke-test.sh, or N/A]

# Features (Behavior Anchors)
# Used by /verify to check that key behaviors still hold after each loop iteration.
# Format: - [Feature name]: [what happens when user does X]

# FROZEN Sections Convention
# Sections marked with `# FROZEN` should NOT be modified by AI agents.
# This is a strong convention (prompt-enforced, ~90% effective), not a filesystem lock.
# Human must explicitly remove the FROZEN marker to allow AI edits.
# Use for: project vision, core architecture decisions, security policies.

# Agent Ground Rules

These rules apply to ALL agents (Claude Code sessions) across all projects. They enable autonomous, unattended operation with minimal human intervention.

## Commits
- Use `committer "type: message" file1 file2` for all commits — NEVER `git add .`
  - `committer` is at `~/.claude/scripts/committer.sh` (or `~/.local/bin/committer` if symlinked)
  - This prevents parallel agents from staging each other's files
- After modifying each file, commit immediately with committer before opening the next file. Never batch file edits into one commit.
- Conventional commit format required: `feat/fix/refactor/test/chore/docs/perf`
- Commit small and often — each logical unit gets its own commit

## Communication
- When blocked on something requiring human input: write to `.claude/blockers.md` and stop
  - Format: `## Blocker [datetime]\n[what you need]\n[what you tried]`
- Don't loop retrying what you cannot fix — surface it clearly, then stop
- When starting a task, switching focus, or reaching a milestone: `vt title "action - context"` (if VibeTunnel installed)

## Autonomy
- Proceed WITHOUT asking for: file edits, test runs, builds, type-checks, lint
- Ask the user BEFORE: deleting files, modifying .env, running migrations, force-pushing

## Context Management
- Context window ~80% full → run `/handoff` to save state, then start a new session with `/pickup`
- If `.claude/handoff-*.md` exists at session start → it is auto-loaded; run `/pickup` to activate
- Task queue pattern: the user may send multiple tasks in sequence — queue them, execute in order, don't wait between tasks

## Code Architecture (Claude Code-Optimized)

Structure code for efficient Claude Code tool usage:

- **File size**: Keep each file under 1500 lines (Read tool default = 2000 lines; under 1500 = readable in one shot)
- **Module count**: 4-6 modules per component. NOT 1 monolith, NOT 15+ fragments. Each additional file = 1 extra Read tool call.
- **Section markers**: Use clear `# ─── Section Name ───` headers so Grep can navigate within files
- **Edit-friendly**: Shorter files = fewer string duplicates = reliable Edit tool operations
- **Cohesion over separation**: Keep tightly coupled code in one file. Fix a bug by reading 1 file, not 3.
- **DAG imports**: Module dependency graph must be a strict DAG (no circular imports). Use lazy imports or duck typing (`Any`) to break potential cycles.
- **CSS extraction**: For HTML files with inline CSS > 200 lines, extract to separate `.css` file. Keep JS inline if tightly coupled (SPA globals, no module system).

## Pre-Code Reflection

Before writing or modifying code, consider these failure patterns (learned from cross-project audits):

- **Settings/wiring**: If adding a config/setting/flag — trace the full path: definition → read → callsite → effect. Untested wiring = silent feature breakage.
- **Edge cases**: Does this work on first run (empty DB, no git history)? On a different OS (stat -c vs -f, path separators)? With empty/null/duplicate input?
- **Async boundaries**: If async — what happens when the world changes mid-flight? Subprocess needs kill+drain on timeout? Closure captures stale state? Lock granularity sufficient?
- **Security surface**: Am I validating at the system boundary? Any secrets, credentials, or user input flowing into commands/queries/URLs without sanitization?
- **Deploy gap**: Will this change actually reach the runtime? Source ≠ deployed. Config ≠ loaded. Defined ≠ called.
