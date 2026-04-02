---
name: handoff
description: End-of-session context handoff. Saves session state so the next session or a parallel agent can pick up exactly where the left off. Run this when context is getting full (~80%) or before stopping work.
when_to_use: "context full, stop work, save state, end session, 保存, 交接, context getting full"
user_invocable: true
---

# Handoff Skill

When context is ~80% full (or before stopping), output a structured handoff document so the next session can resume exactly where this one left off — no re-explanation needed.

## Handoff Format

Copy and fill in every section below. Do NOT skip sections — each exists for a reason.

```markdown
## Goal
What is this project/feature trying to achieve? One paragraph maximum.

## Constraints & Preferences
- **Tech stack**: <language, framework, key libraries>
- **Code style**: <conventions this project follows>
- **What NOT to do**: <known anti-patterns or avoided approaches>
- **Project-specific rules**: <from CLAUDE.md, .claude/rules.d/, AGENTS.md>

## Progress (since last handoff or session start)

### Done
- <completed feature/changes with file paths>
- <verified working: what was tested>

### In Progress
- <partially complete, needs continuation>
- <where to pick up, what to check first>

### Blocked
- <stuck on X, reason, what would unblock it>

## Key Decisions + Rationale
- **<Decision>**: Chose <A> over <B> because <reason>
- **<Decision>**: <what was decided> — <why this approach>

## Next Steps
1. <immediate next action>
2. <follow-up after that>
3. <optional: what a third session would do>

## Critical Context
Any state the next session MUST know:
- <running processes, background jobs>
- <open PRs, pending reviews>
- <recent failures, known issues>
- <API keys or secrets needed (mention only location, never paste values)>

## Read These Files
<read-files>
- path/to/critical-file-1.md
- path/to/critical-file-2.py
</read-files>

## Recently Modified
<modified-files>
- src/feature_x.py (added handle_user function)
- tests/test_x.py (3 new edge case tests)
</modified-files>
```

## Rules

- **Goal**: Keep it to 1 paragraph. If you can't summarize it, the scope is too large.
- **Key Decisions**: Only record non-obvious decisions. "Used Python because it's the project language" doesn't need a note.
- **Blocked**: If blocked, write to `.claude/blockers.md` instead of leaving it in handoff.
- **Secrets**: Never paste actual API keys, tokens, or passwords. Just note where they are stored.
- **Read/Modified files**: These go in the XML-tagged sections so the next session can load them with exact context.

## What Happens to the Handoff

The next session receives this via `/pickup` or by reading the handoff file. It should be able to:
1. Understand the current state without asking you
2. Know exactly where to pick up
3. Understand why past decisions were made
