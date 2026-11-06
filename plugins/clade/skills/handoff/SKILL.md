---
name: handoff
description: "End-of-session context handoff. Saves session state so the next session or a parallel agent can pick up exactly where the left off. Run this when context is getting full (~80%) or before stopping work."
---

# Clade for Codex

This workflow runs **directly in Codex**. Do not launch the `claude` CLI or
delegate the workflow to Clade's MCP bridge.

Codex compatibility rules:

- Plugin skills are namespaced. Invoke this workflow explicitly as
  `$clade:handoff`; a bare `$name` does not select the installed Clade plugin.
- Read the nearest `AGENTS.md` files for repository instructions. If a project
  has only `CLAUDE.md`, treat it as legacy project guidance and read it too.
- Store new Clade working state under `.clade/` (or `~/.clade/` for personal
  state). Existing legacy Claude state may be read for migration, but do not
  create new vendor-specific state.
- A `/skill-name` reference means the corresponding Codex
  `$clade:skill-name` plugin skill, or the same workflow invoked naturally when
  explicit skill invocation is not available.
- Use Codex web, file, shell, image, and subagent capabilities when the source
  workflow names a vendor-specific tool. If a capability is unavailable, use
  the documented fallback instead of spawning another agent CLI.
- Paths such as `<plugin-root>/...` are relative to the installed Clade plugin
  containing this `SKILL.md`; resolve that root before invoking a helper.

## Canonical Clade workflow

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
ls .clade/handoff-*.md 2>/dev/null | wc -l
```

- **First handoff (count = 0)**: Use the INITIAL TEMPLATE below
- **Subsequent handoffs (count ≥ 1)**: Read the most recent `.clade/handoff-*.md`, then do INCREMENTAL UPDATE:
  - Keep Goal and Constraints unchanged (only update if user explicitly changed direction)
  - Move "In Progress" items to "Done ✅" if git log shows they were completed
  - Append new Done items from this session's commits
  - Update Next Steps based on current git state and TODO.md
  - Add new Key Decisions if any were made this session
  - Carry Hypotheses forward: update each status from this session's evidence,
    keep every ruled-out entry, and rewrite the current one's "Drop it if" when
    the evidence moved. Keep Stop conditions & out of scope unless the user
    changed the scope. A v2 handoff has neither section: add both.

### Step 3: Write Handoff File

When working on a shared `/tasks` task, include `project_id`, `task_id`,
`session_id`, delivery ID and checkpoint SHA in the handoff. Read the live task
before reporting its state. With a known recipient, preserve the code first
and use the task helper's holder-guarded `handoff` with that recipient's fresh
session ID and resume context. Without a recipient, retain ownership and name
the pending handoff; writing Markdown alone neither releases nor transfers it.
Submitted tasks require review or `request-changes`, not a silent reassignment.

Save to: `.clade/handoff-{YYYY-MM-DD-HH-MM}.md`

**INITIAL TEMPLATE** (use for first handoff):

```markdown
# Handoff: {YYYY-MM-DD HH:MM}
<!-- STRUCTURED HANDOFF v3 — preserve all section headers exactly -->

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

## Hypotheses
<!-- Every hypothesis this session acted on, INCLUDING the dropped ones.
     Status: current | UNCONFIRMED | ruled-out. At most one is current.
     Mechanical work with no hypothesis: write "- none — mechanical work". -->
- **H1 [current]**: {The claim the In Progress work and Next Steps rest on}
  - Evidence: {What you observed: command → output, file:line. Mark anything you did not observe "inferred".}
  - Drop it if: {The specific, checkable observation that would falsify it}
- **H2 [ruled-out]**: {A claim that was tried and dropped}
  - Evidence: {The observation that ruled it out}
- **H3 [UNCONFIRMED]**: {A claim raised but not yet tested — not a fact}
  - Evidence: {Why it was raised}
  - Drop it if: {What would rule it out}

## Stop conditions & out of scope
- Done when: {The observable condition that means the Goal is met — a test passes, a PR is open}
- Stop and re-plan if: {A result that means the approach, not just one step, is wrong}
- Out of scope: {What this task deliberately does not do, and why}

## Next Steps (ordered by priority)
<!-- Proposals, not orders: /pickup re-checks the current hypothesis before acting on them. -->
1. {Exact next action — specific file, specific change, specific command} (rests on H1)
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
- HEAD: {git rev-parse --short HEAD}
- Uncommitted: {git status -sb output, or "clean"}
- Build: {passing | failing | unknown — based on last verify/test run}
- Session: {approximate duration}
```

**Writing Hypotheses — why the section exists.** A session that has committed
to a hypothesis keeps pursuing it after the evidence turns, and a summary that
keeps "the current work" keeps that commitment too (context inertia, Breunig,
2026-10-14). The next session's `/pickup` re-checks the current hypothesis
before acting, and it can only do that with what you write here:

- **Evidence is what you saw**, not how sure you are. "inferred" is an honest
  label; an inference written as an observation is how a wrong hypothesis
  survives the reset.
- **"Drop it if" must be checkable** in a command or two. "If it doesn't work"
  checks nothing.
- **Keep ruled-out entries.** Each one stops the next session re-trying it.
- **Next Steps never restate a hypothesis as fact.** "Fix the middleware bug"
  hides the bet; "patch the middleware (rests on H1)" names it, so the steps
  that fall with H1 are visible.

### Step 4: Report

Output:
```
Handoff saved: .clade/handoff-{timestamp}.md

Goal: {one sentence}
Done this session: {N items}
Blockers: {none / list}
Current hypothesis: {H-current, one line — or "none"}
Next: {Step 1 from Next Steps}
```

## Completion Status

- **✅ DONE**: Handoff file saved successfully
- **⚠ DONE_WITH_CONCERNS**: Saved but with uncommitted changes or unresolved blockers
- **❌ BLOCKED**: Cannot capture state — details to `.clade/blockers.md`
- **❓ NEEDS_CONTEXT**: Missing information needed to write accurate handoff

## 3-Strike Rule
If you fail to complete a step 3 times: write failure details to `.clade/blockers.md` and stop.

## Additional skill reference

# Handoff Skill

When context is ~80% full (or before stopping), output a structured handoff document so the next session can resume exactly where this one left off — no re-explanation needed.

## Handoff Format (STRUCTURED HANDOFF v3)

The authoritative template lives in `prompt.md` (Step 3) — this is the shape it produces.
Saved to `.clade/handoff-{YYYY-MM-DD-HH-MM}.md`; `/pickup` parses these exact section headers.

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
- **Blocked**: If blocked, write to `.clade/blockers.md` instead of leaving it in handoff.
- **Secrets**: Never paste actual API keys, tokens, or passwords. Just note where they are stored.
- **Read/Modified files**: These go in the XML-tagged sections so the next session can load them with exact context.

## What Happens to the Handoff

The next session receives this via `/pickup` or by reading the handoff file. It should be able to:
1. Understand the current state without asking you
2. Know exactly where to pick up
3. Understand why past decisions were made
4. Re-check the hypothesis the work rests on before acting on it, and skip the ones already ruled out

## Delivery completion

If this workflow changes files or external state:

- Inspect the real final state before responding, including `git status` for a
  repository task.
- Never report `DONE` while task-owned changes are uncommitted. Use or continue
  `$clade:delivery` and create a repository-compliant checkpoint or preserve
  the work when committing is unavailable.
- When the user request or trusted repository policy makes publication,
  deployment, or live verification part of the task, do not silently downgrade
  the result to local-only work.
- If a required delivery transition lacks authority, credentials, a destination,
  or reachable external state, report `BLOCKED` or `NEEDS_CONTEXT` rather than
  appending a "not committed/pushed/deployed" caveat after `DONE`.
