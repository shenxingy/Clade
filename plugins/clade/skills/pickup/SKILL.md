---
name: pickup
description: "Start-of-session context pickup. Reads the latest handoff file and resumes work where the last session left off. Run this at the start of a new session if a handoff file exists."
---

# Clade for Codex

This workflow runs **directly in Codex**. Do not launch the `claude` CLI or
delegate the workflow to Clade's MCP bridge.

Codex compatibility rules:

- Plugin skills are namespaced. Invoke this workflow explicitly as
  `$clade:pickup`; a bare `$name` does not select the installed Clade plugin.
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
name: pickup
trigger: user runs /pickup at start of new session, or after /handoff
completion-status: DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
</command-metadata>

Resume work from the most recent handoff file.

## Shared task pickup

If Git-common `clade/tasks/binding.json` exists, first load `/tasks` and read
its snapshot. A handoff's task reference must match this project and the live
owner. Use a fresh session ID and claim ready work, or receive an explicit
holder-guarded handoff; do not reuse the previous session's identity. Preserve
the original objective when choosing among ready tasks. A task blocked on a
dependency is not runnable just because a handoff lists it as the next step.
An unavailable task backend blocks new claims, but existing work can still be
checkpointed. If no Markdown handoff exists, continue from the shared task
record and acceptance criteria instead of stopping at Step 1.

## Execution Steps

### Step 1: Find Handoff File
```bash
ls -t .clade/handoff-*.md 2>/dev/null | head -5
```

If no files found: say "No handoff file found. Starting fresh." and stop.

### Step 2: Read + Parse
Read the most recent handoff file completely.

Parse these sections:
- **Goal**: the one-sentence objective
- **Blocked**: check if "none" or has real blockers
- **Hypotheses**: the `current` one with its Evidence and "Drop it if" line, the
  `UNCONFIRMED` ones (not facts), and the `ruled-out` ones (do not re-try them
  unless new evidence reopens one)
- **Stop conditions & out of scope**: when the Goal counts as met, which result
  means re-plan, and what the task must not widen into
- **Next Steps**: the ordered list of PROPOSED actions — written by a session
  already committed to its hypothesis, so they are proposals, not orders
- **Meta**: branch, HEAD, uncommitted status, build status

A v2 handoff (`STRUCTURED HANDOFF v2`) has no Hypotheses or Stop conditions
section. Take the assumption Next Steps #1 rests on as the current hypothesis,
mark it UNCONFIRMED, and re-check it the same way in Step 5.

A v3 handoff whose Hypotheses section is `- none — mechanical work` has no
hypothesis to re-check. Step 5 still runs check 1 (commits since Meta.HEAD) and
check 3 (stop conditions), skips check 2, and then acts as **Holds**.

### Step 3: Verify Git State
```bash
git branch --show-current
git status -sb
git merge-base --is-ancestor <Meta.HEAD> HEAD; echo "ancestor: $?"
git log --oneline <Meta.HEAD>..HEAD
```

If current branch doesn't match handoff Meta.Branch: warn the user but continue.

`<Meta.HEAD>..HEAD` lists every commit since the handoff, however many — a fixed
`-10` window misses the 11th. Work that landed after the handoff may have moved
the ground under its hypothesis; Step 5 checks whether it did.

- **ancestor: 0** — the handoff's HEAD is still in this history; the log is the
  complete list of what landed since (empty when nothing did).
- **ancestor: 1** (rebased, squash-merged, or another branch) or **128** (this
  clone does not have the commit) — the log cannot say what changed: **the
  repository moved**. Step 5 takes the Contradicted path.

A v2 handoff has no Meta.HEAD: run `git log --oneline -10` instead and compare it
with the handoff's Done list.

### Step 4: Display Briefing (max 20 lines)

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Resuming: {handoff date} ({X hours/days ago})
Goal: {Goal section content}

Done: {count of Done ✅ items}
In Progress: {In Progress items if any}
Blocked: {Blocked content OR "none"}
Hypothesis: {current hypothesis, one line} [{status in the handoff}]

Branch: {branch}  Build: {passing|failing|unknown}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Proposed next (re-checked in Step 5):
→ {Next Steps #1}
→ {Next Steps #2}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Step 5: Re-check the hypothesis, then resume

Executing the last session's Next Steps as orders carries its commitment to a
hypothesis across the reset, even when the evidence has since turned (context
inertia, Breunig, 2026-10-14). So test the ground under them before the first edit.

**If Blocked has items**: List each blocker clearly. Ask user to resolve before continuing autonomously.

**If handoff is >48 hours old**: Flag the age prominently. Ask user to confirm goal is still current before proceeding.

**Once nothing is blocked (and an old handoff's goal is confirmed), re-check first.** Read-only and a few commands — not a re-investigation:
1. **Repository**: did any commit after Meta.HEAD (Step 3) touch what the current
   hypothesis cites? Do those files still say what its Evidence says? If Step 3
   found Meta.HEAD is not an ancestor of HEAD, the repository moved: Contradicted.
2. **Verified facts**: re-run the cheapest check its Evidence or "Drop it if" line
   names — one test, one grep, one command. A fact the handoff marks "inferred" is
   not verified.
3. **Stop conditions**: if "Done when" is already met, report that and stop — there
   is nothing to resume. Drop any proposed step that falls under "Out of scope".

Print one line — `Re-check: {H} holds | contradicted | not re-checked — {evidence}`,
or `Re-check: no hypothesis (mechanical work) — {evidence}` — and act on it:

- **Holds** (the check supports it, finds nothing against it, or there is no
  hypothesis because the work is mechanical): start the first
  Next Step that still follows from it. Do NOT ask "shall I proceed?" — just start.
- **Contradicted** (a "Drop it if" or "Stop and re-plan if" condition is met, or the
  repository moved under it): do not execute the old Next Steps. Treat the hypothesis
  as ruled-out on the evidence you just saw (the next /handoff records it so; a moved
  repository alone does not falsify it, so record that one as UNCONFIRMED), re-plan
  from the Goal, the verified facts and the remaining hypotheses, state the new first
  step in one line and start it — still without asking. Ask only if the re-plan would
  change the Goal itself or take a destructive step.
- **Cannot be checked cheaply** (another host, credentials, a long run): proceed with
  it UNCONFIRMED, say "not re-checked: {why}", and prefer a first step that tests it.

## Completion Status

- **✅ DONE**: Handoff loaded, hypothesis re-checked, and resumed (or blockers presented)
- **⚠ DONE_WITH_CONCERNS**: Loaded but git state doesn't match, handoff >48h old, or the re-check contradicted the handoff's hypothesis and the plan changed
- **❌ BLOCKED**: No handoff file found, or file unreadable
- **❓ NEEDS_CONTEXT**: Ask via AskUserQuestion

## 3-Strike Rule
If you fail to complete a step 3 times: write failure details to `.clade/blockers.md` and stop.

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
