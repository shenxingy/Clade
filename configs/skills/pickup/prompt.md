<command-metadata>
name: pickup
trigger: user runs /pickup at start of new session, or after /handoff
completion-status: DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
</command-metadata>

Resume work from the most recent handoff file.

## Execution Steps

### Step 1: Find Handoff File
```bash
ls -t .claude/handoff-*.md 2>/dev/null | head -5
```

If no files found: say "No handoff file found. Starting fresh." and stop.

### Step 2: Read + Parse
Read the most recent handoff file completely.

Parse these sections:
- **Goal**: the one-sentence objective
- **Blocked**: check if "none" or has real blockers
- **Next Steps**: the ordered action list
- **Meta**: branch, uncommitted status, build status

### Step 3: Verify Git State
```bash
git branch --show-current
git status -sb
```

If current branch doesn't match handoff Meta.Branch: warn the user but continue.

### Step 4: Display Briefing (max 20 lines)

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Resuming: {handoff date} ({X hours/days ago})
Goal: {Goal section content}

Done: {count of Done ✅ items}
In Progress: {In Progress items if any}
Blocked: {Blocked content OR "none"}

Branch: {branch}  Build: {passing|failing|unknown}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Picking up at:
→ {Next Steps #1}
→ {Next Steps #2}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Step 5: Resume or Pause

**If Blocked is "none"**: Immediately start executing Next Steps #1. Do NOT ask "shall I proceed?" — just start.

**If Blocked has items**: List each blocker clearly. Ask user to resolve before continuing autonomously.

**If handoff is >48 hours old**: Flag the age prominently. Ask user to confirm goal is still current before proceeding.

## Completion Status

- **✅ DONE**: Handoff loaded and resumed (or blockers presented)
- **⚠ DONE_WITH_CONCERNS**: Loaded but git state doesn't match, or handoff >48h old
- **❌ BLOCKED**: No handoff file found, or file unreadable
- **❓ NEEDS_CONTEXT**: Ask via AskUserQuestion

## 3-Strike Rule
If you fail to complete a step 3 times: write failure details to `.claude/blockers.md` and stop.
