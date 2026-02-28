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

- [ ] [criterion 1]
- [ ] [criterion 2]
- [ ] [edge case: e.g., empty input → error shown, not silently dropped]

---

## Verification Checklist

Workers must complete **Auto-Verifiable** before marking a task done.
**Human-Verifiable** items block merge — flag them in `.claude/blockers.md` if not met.

### Auto-Verifiable (loop worker must complete)

- [ ] `tsc --noEmit` passes (or equivalent type-check for the project)
- [ ] Build passes
- [ ] Lint clean (no new errors)
- [ ] Tests pass — existing + any new tests covering changed paths
- [ ] Code review: API payload field names/types match backend schema exactly
- [ ] Code review: error branches handled (not silently swallowed or logged only)
- [ ] Code review: no double-submit / race condition on user actions
- [ ] Code review: no console.error / unhandled promise rejections introduced
- [ ] Regression: shared components/interfaces not broken for existing callers

### Human-Verifiable (block merge until reviewed)

- [ ] Mobile layout 375px — all content reachable, no overflow clipping
- [ ] Desktop layout 1440px — layout complete and proportional
- [ ] Browser console clean (no red errors, no unexpected warnings)
- [ ] Happy path UX feel correct end-to-end
- [ ] Edge case inputs tested manually (empty, null, very long, special chars)
- [ ] Scroll completeness — all content scrollable to, nothing cut off
