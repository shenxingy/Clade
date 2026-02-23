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
