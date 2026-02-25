# Agent Ground Rules

These rules enable autonomous, unattended operation across all projects.

## Commits
- Use `committer "type: message" file1 file2` for all commits — NEVER `git add .`
  - `committer` is at `~/.local/bin/committer` (symlinked from `~/.claude/scripts/committer.sh`)
  - This prevents parallel agents from staging each other's files
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
