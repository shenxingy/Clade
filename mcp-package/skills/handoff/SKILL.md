---
name: handoff
description: End-of-session context handoff. Saves session state so the next session or a parallel agent can pick up exactly where the left off. Run this when context is getting full (~80%) or before stopping work.
when_to_use: "context full, stop work, save state, end session, 保存, 交接, context getting full"
user_invocable: true
---

# Handoff Skill

When context is ~80% full (or before stopping), output a structured handoff document so the next session can resume exactly where this one left off — no re-explanation needed.

## Handoff Format (STRUCTURED HANDOFF v3)

The authoritative template lives in `prompt.md` (Step 3) — this is the shape it produces.
Saved to `.claude/handoff-{YYYY-MM-DD-HH-MM}.md`; `/pickup` parses these exact section headers.

```markdown
# Handoff: {YYYY-MM-DD HH:MM}
<!-- STRUCTURED HANDOFF v3 — preserve all section headers exactly -->

## Goal
One sentence: the overall objective of this work session / task.

## Constraints & Preferences
- <technical constraints, stack choices, things explicitly NOT to do>
- <user preferences discovered this session>

## Progress
### Done ✅
- [x] <completed item with exact file path> (<short commit hash>)

### In Progress 🔄
- [ ] <item currently being worked on — what specifically remains>

### Blocked 🚫
- <specific blocker needing human input — OR "none">

## Key Decisions
- **<Decision>**: <rationale — why this over alternatives>

## Hypotheses
- **H1 [current]**: <the claim the In Progress work and Next Steps rest on>
  - Evidence: <what you observed — command → output, file:line; "inferred" when you did not>
  - Drop it if: <the specific, checkable observation that would falsify it>
- **H2 [ruled-out]**: <a claim tried and dropped>
  - Evidence: <the observation that ruled it out>
- **H3 [UNCONFIRMED]**: <raised, not yet tested>
  - Evidence: <why it was raised>
  - Drop it if: <what would rule it out>

## Stop conditions & out of scope
- Done when: <the observable condition that means the Goal is met>
- Stop and re-plan if: <a result that means the approach, not one step, is wrong>
- Out of scope: <what this task deliberately does not do, and why>

## Next Steps (ordered by priority)
1. <exact next action — specific file, specific change, specific command> (rests on H1)
2. <second action>

## Critical Context
- <non-obvious codebase facts, pitfalls, configs that matter>
- <API keys or secrets needed (mention only location, never paste values)>

## Files
<read-files>
<absolute paths of files READ this session, one per line>
</read-files>

<modified-files>
<absolute paths of files MODIFIED this session, one per line>
</modified-files>

## Meta
- Branch: <git branch --show-current>
- HEAD: <git rev-parse --short HEAD>
- Uncommitted: <git status -sb output, or "clean">
- Build: <passing | failing | unknown>
- Session: <approximate duration>
```

Subsequent handoffs are incremental: keep Goal/Constraints, move completed In-Progress items to Done ✅, carry Hypotheses forward with updated statuses, update Next Steps (see prompt.md Step 2).

## Rules

- **Goal**: Keep it to 1 paragraph. If you can't summarize it, the scope is too large.
- **Key Decisions**: Only record non-obvious decisions. "Used Python because it's the project language" doesn't need a note.
- **Hypotheses**: At most one `current`; each entry carries the evidence actually observed and a checkable "Drop it if". Keep `ruled-out` entries. `/pickup` re-checks the current one before acting on Next Steps, so a vague drop condition carries a wrong hypothesis across the reset — the failure this section exists to stop.
- **Stop conditions & out of scope**: What "done" looks like, what result means re-plan, and what the task will not widen into.
- **Blocked**: If blocked, write to `.claude/blockers.md` instead of leaving it in handoff.
- **Secrets**: Never paste actual API keys, tokens, or passwords. Just note where they are stored.
- **Read/Modified files**: These go in the XML-tagged sections so the next session can load them with exact context.

## What Happens to the Handoff

The next session receives this via `/pickup` or by reading the handoff file. It should be able to:
1. Understand the current state without asking you
2. Know exactly where to pick up
3. Understand why past decisions were made
4. Re-check the hypothesis the work rests on before acting on it, and skip the ones already ruled out
