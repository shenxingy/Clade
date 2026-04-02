You are generating a morning briefing for a developer returning to their project.

Summarize the current state and suggest the top 3 next steps.

## Format

```
## Morning Brief — {date}

### Overnight / Recent Activity
- {what happened since last session: commits, loop runs, failures}
- {or "No activity since last session"}

### Current State
- Goal progress: {X of Y TODO items done in current phase}
- Open blockers: {list from .claude/blockers.md, or "none"}
- Skipped tasks: {count from .claude/skipped.md, or "none"}
- Decisions made: {count from .claude/decisions.md, or "none — review needed"}

### Top 3 Next Steps
1. {Most impactful next action — be specific}
2. {Second priority}
3. {Third priority}

### Suggested Command
{The exact /loop or /start command to run, with appropriate goal file}
```

## Rules
- Be concise — this is a 30-second read, not a report
- Focus on what to DO, not what was done
- If blockers exist, the #1 next step should address them
- Reference specific files and TODO items by name
