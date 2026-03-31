---
name: worktree
description: Create and manage git worktrees for parallel Claude Code sessions
when_to_use: "create worktree, parallel session, git worktree, isolated branch"
argument-hint: '"task prompt" | --list | --merge [branch] | --clean'
user_invocable: true
---

# Worktree Skill

Quickly spin up isolated git worktrees so you can open parallel Claude Code sessions without conflicts. Each worktree gets its own branch and a TASK.md describing what to work on.

## Usage

### Create a new worktree
```
/worktree "Fix all padding issues in settings pages"
```
Creates a worktree, branch, and TASK.md. Prints the command to start a new Claude session in it.

### List active worktrees
```
/worktree --list
```

### Merge a worktree branch back
```
/worktree --merge wt/fix-padding-settings
/worktree --merge --all
```

### Clean up all worktrees
```
/worktree --clean
```

## How it works

1. **Create**: Makes a sibling directory `../<project>-wt-<n>` with a new branch `wt/<slug>`
2. **TASK.md**: Written to the worktree root so the new Claude session auto-reads it
3. **Merge**: Merges the worktree branch into your current branch
4. **Clean**: Removes worktree directories and deletes merged branches
