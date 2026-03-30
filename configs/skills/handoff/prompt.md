Perform an end-of-session handoff. This document will be read by the next session or parallel agent to resume work without losing context.

## Steps

1. Run `git log --oneline -10` and `git status -sb` to capture current repo state
2. Read `TODO.md` (if it exists) to understand overall task state
3. Identify what was accomplished THIS session (compare recent git log vs session start)
4. Identify any blockers or decisions that require human input
5. List exact next steps, ordered by priority, with specific file paths

## Output

Create the directory `.claude/` if it doesn't exist, then save to `.claude/handoff-{YYYY-MM-DD-HH-MM}.md` using today's date and current time.

Use this exact structure:

```
# Handoff: {YYYY-MM-DD HH:MM}

## Session Summary
- Accomplished: [bullet list with exact file paths changed]
- Commits made: [from git log this session, or "none"]

## Current State
- Branch: [branch name]
- Uncommitted changes: [git status -sb output, or "clean"]
- Build/tests: [passing / failing / unknown]

## Blockers (needs human input)
- [Each item that is stuck waiting on human decision, OR write "none — ready to continue"]

## Next Steps (ordered)
1. [Specific task with exact file paths and what to do]
2. [Specific task with exact file paths and what to do]
3. [...]

## Gotchas & Discoveries
- [Important findings about the codebase that the next agent needs to know]
- [Pitfalls to avoid, configs that matter, non-obvious dependencies]

## TODO.md Status
- Completed this session: [list or "none"]
- In progress: [list or "none"]
- Up next: [next TODO item]
```

After saving, output:
- The file path of the handoff document
- A 3-bullet summary of what was accomplished
- Whether any blockers need human attention before the next session can proceed autonomously

## Notes

- Be specific about file paths — the next agent has no memory of this session
- If you have uncommitted work, mention each file and what state it's in
- If this session made no progress, say so honestly — it helps diagnose problems


---

## Completion Status

- ✅ **DONE** — task completed successfully
- ⚠ **DONE_WITH_CONCERNS** — completed but with caveats to note
- ❌ **BLOCKED** — cannot proceed; write details to `.claude/blockers.md`
- ❓ **NEEDS_CONTEXT** — missing information; use AskUserQuestion

**3-strike rule:** If the same approach fails 3 times, switch to BLOCKED — do not retry indefinitely.
