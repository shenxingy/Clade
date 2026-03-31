<command-metadata>
name: handoff
trigger: user runs /handoff, context near full, or ending work session
completion-status: DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
</command-metadata>

Save session state so the next session or parallel agent can resume exactly where you left off.

## When to Run
- Context window is ~80% full
- About to stop work for the day
- Switching to a different task
- Before running /compact

## Execution Steps

### Step 1: Collect Data (run in parallel)
```bash
git log --oneline -15
git status -sb
git diff --stat HEAD~5..HEAD 2>/dev/null
```
Also read TODO.md current state.

### Step 2: Detect Iteration Number
```bash
ls .claude/handoff-*.md 2>/dev/null | wc -l
```

- **First handoff (count = 0)**: Use the INITIAL TEMPLATE below
- **Subsequent handoffs (count ≥ 1)**: Read the most recent `.claude/handoff-*.md`, then do INCREMENTAL UPDATE:
  - Keep Goal and Constraints unchanged (only update if user explicitly changed direction)
  - Move "In Progress" items to "Done ✅" if git log shows they were completed
  - Append new Done items from this session's commits
  - Update Next Steps based on current git state and TODO.md
  - Add new Key Decisions if any were made this session

### Step 3: Write Handoff File

Save to: `.claude/handoff-{YYYY-MM-DD-HH-MM}.md`

**INITIAL TEMPLATE** (use for first handoff):

```markdown
# Handoff: {YYYY-MM-DD HH:MM}
<!-- STRUCTURED HANDOFF v2 — preserve all section headers exactly -->

## Goal
{One sentence: the overall objective of this work session / task}

## Constraints & Preferences
- {Technical constraints, stack choices, things explicitly NOT to do}
- {User preferences discovered this session}

## Progress
### Done ✅
- [x] {Completed item with exact file path} ({short commit hash})

### In Progress 🔄
- [ ] {Item currently being worked on — what specifically remains to do}

### Blocked 🚫
- {Specific blocker needing human input — OR write "none"}

## Key Decisions
- **{Decision}**: {Rationale — why this over alternatives}

## Next Steps (ordered by priority)
1. {Exact next action — specific file, specific change, specific command}
2. {Second action}
3. {Third action}

## Critical Context
- {Non-obvious codebase facts the next agent must know}
- {Pitfalls discovered, configs that matter, edge cases found}
- {Anything that took time to figure out — save the next agent that time}

## Files
<read-files>
{absolute paths of files READ this session, one per line}
</read-files>

<modified-files>
{absolute paths of files MODIFIED this session, one per line}
</modified-files>

## Meta
- Branch: {git branch --show-current}
- Uncommitted: {git status -sb output, or "clean"}
- Build: {passing | failing | unknown — based on last verify/test run}
- Session: {approximate duration}
```

### Step 4: Report

Output:
```
Handoff saved: .claude/handoff-{timestamp}.md

Goal: {one sentence}
Done this session: {N items}
Blockers: {none / list}
Next: {Step 1 from Next Steps}
```

## Completion Status

- **✅ DONE**: Handoff file saved successfully
- **⚠ DONE_WITH_CONCERNS**: Saved but with uncommitted changes or unresolved blockers
- **❌ BLOCKED**: Cannot capture state — details to `.claude/blockers.md`
- **❓ NEEDS_CONTEXT**: Missing information needed to write accurate handoff

## 3-Strike Rule
If you fail to complete a step 3 times: write failure details to `.claude/blockers.md` and stop.
