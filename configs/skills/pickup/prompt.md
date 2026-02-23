Load context from the latest handoff file to resume work seamlessly from the previous session.

## Steps

1. Look for `.claude/handoff-*.md` files in the current project directory (use Glob: `.claude/handoff-*.md`)
2. If no handoff files found: say "No handoff file found. Starting fresh — read CLAUDE.md and TODO.md for context." Then stop.
3. Sort by filename (they're timestamped YYYY-MM-DD-HH-MM), take the most recent one
4. Read the handoff file completely
5. Also run `git status -sb` to verify current repo state matches what the handoff describes

## Output

Present this briefing (concise, actionable):

```
Resuming from: {handoff date and time}
Age: {X hours ago}

What was done:
  • [bullet 1 from Session Summary]
  • [bullet 2 from Session Summary]
  • [bullet 3 — truncate to 3 max]

Current state:
  Branch: {branch}
  Git:     {git status -sb output, 1 line}

Blockers needing your input:
  • [list each blocker OR "none — ready to proceed autonomously"]

Picking up at:
  → {Step 1 from Next Steps}
  → {Step 2 from Next Steps}
```

## Then

- If blockers exist: list them clearly and ask the user to address them before proceeding
- If no blockers: immediately start executing Step 1 from the handoff's Next Steps — don't wait for the user to say "go"
- If the handoff file is older than 24 hours: mention the age prominently before proceeding ("Note: this handoff is {X} hours old — verify the state is still accurate")
- If git state doesn't match the handoff (e.g., handoff says "uncommitted changes" but git is clean): flag the discrepancy before proceeding

## Notes

- The goal is zero-friction resumption — the user should not need to re-explain context
- Trust the handoff document but verify with git — it's ground truth
- The session that wrote the handoff may have been interrupted; check for half-finished work
