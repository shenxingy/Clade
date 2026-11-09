# Loop Goal — [Short Description]

MODE: VERTICAL   # VERTICAL (default) or HORIZONTAL (file-level micro-tasks, up to 20)

## Goal

[Describe the ideal end state. What should be true when this loop is done?
Write declaratively, not imperatively — "The system does X" not "Implement X".]

## Context

[Key files, constraints, or background the supervisor needs to understand the scope.]

## Acceptance Criteria

[List observable conditions that confirm the goal is achieved.
Be explicit about edge cases — "invalid input shows error" not "works correctly".]

These `- [ ]` lines are the goal items the loop counts; write each so one task
can fully satisfy it. A number you want hit belongs in the verify command or a
`--holdout` scenario: a checkbox is ticked when its task lands, met or not.

- [ ] [criterion 1]
- [ ] [criterion 2]
- [ ] [edge case: e.g., empty input → error shown, not silently dropped]

---

## Verification Checklist

Plain bullets, not goal items: the loop never counts or ticks them, so they
cannot hold convergence open. **Auto-Verifiable** is for the supervisor, which
reads this list and writes the relevant checks into each task's "how to verify";
the binding gate is the repository's verify command plus any `--holdout`
scenarios. **Human-Verifiable** is for you, after the loop exits and before merge.

### Auto-Verifiable (supervisor copies into task checks)

- `tsc --noEmit` passes (or equivalent type-check for the project)
- Build passes
- Lint clean (no new errors)
- Tests pass — existing + any new tests covering changed paths
- Code review: API payload field names/types match backend schema exactly
- Code review: error branches handled (not silently swallowed or logged only)
- Code review: no double-submit / race condition on user actions
- Code review: no console.error / unhandled promise rejections introduced
- Regression: shared components/interfaces not broken for existing callers

### Human-Verifiable (owner, before merge)

- Mobile layout 375px — all content reachable, no overflow clipping
- Desktop layout 1440px — layout complete and proportional
- Browser console clean (no red errors, no unexpected warnings)
- Happy path UX feel correct end-to-end
- Edge case inputs tested manually (empty, null, very long, special chars)
- Scroll completeness — all content scrollable to, nothing cut off
