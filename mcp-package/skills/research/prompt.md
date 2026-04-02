Research external tools/competitors/approaches for a given topic and write a structured analysis to BRAINSTORM.md.

## Steps

1. Read `VISION.md`, `TODO.md`, and `BRAINSTORM.md` for project context (understand what already exists before researching)
2. Use WebSearch with the current year (2026) in the query to find 3-5 relevant tools, competitors, or approaches for the topic: `$ARGUMENTS`. Run at most 5 searches. If WebSearch returns no results or fails, proceed with knowledge cutoff data and note "⚠ Web search unavailable — results based on training data only".
3. For each result: extract key features, pricing/licensing, UX patterns, what they do well, what they do poorly
4. Compare against current VISION.md — what gaps does this research reveal? what patterns can we borrow?
5. Append a structured entry to `BRAINSTORM.md`:

```markdown
## [Research] {date} — {topic}

### Tools surveyed
| Tool | Key features | What to borrow |
|---|---|---|
| ... | ... | ... |

### Gaps vs current VISION
- ...

### Recommended additions to TODO.md
- [ ] ...
```

## Rules
- Always read VISION.md first — generic suggestions are noise, project-specific insights are signal
- Always search with year 2026 for up-to-date information
- Be specific and actionable — "add OAuth2 login flow like tool X's 2-click setup" not "add authentication"
- Mark entries as `[Research]` (not `[AI]`) so they're distinguishable in BRAINSTORM.md
- Do NOT auto-process into GOALS.md or TODO.md — just write to BRAINSTORM.md inbox


---

## Completion Status

- ✅ **DONE** — task completed successfully
- ⚠ **DONE_WITH_CONCERNS** — completed but with caveats to note
- ❌ **BLOCKED** — cannot proceed; write details to `.claude/blockers.md`
- ❓ **NEEDS_CONTEXT** — missing information; use AskUserQuestion

**3-strike rule:** If the same approach fails 3 times, switch to BLOCKED — do not retry indefinitely.
