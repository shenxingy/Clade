===TASK===
model: haiku
TYPE: HORIZONTAL
---
# Refactor Bot — Eliminate Code Duplication

## Goal

Identify and extract duplicate code in **[MODULE_NAME]** into reusable helpers to improve maintainability and reduce bug surface area.

## Context

**Files in scope:** `[FILES_OR_PATTERN]` (e.g., `src/handlers/*.ts`)
**Duplication pattern:** [DESCRIBE: repeated conditionals, common utility code, similar patterns]
**Target:** Consolidate into 1-2 shared helper functions

Examples of duplication to look for:
- Repeated error handling / validation logic
- Similar loop structures or data transformations
- Copy-pasted utility code (string formatting, date parsing, etc.)
- Repeated initialization or setup patterns

## Acceptance Criteria

- [ ] Identified at least 2 code blocks with duplication in [FILES_OR_PATTERN]
- [ ] Created shared helper function(s) with clear, descriptive names
- [ ] All callers updated to use the helper (find with grep to confirm)
- [ ] No logic changes — behavior is identical to before
- [ ] All existing tests still pass
- [ ] Code is more readable than before the refactor

### Duplication Metrics
- [ ] Lines of code reduced by ≥10%
- [ ] Duplicated logic now appears in exactly 1 place
- [ ] Helper function is generic enough to reuse (not just moving the problem)

---

## Verification Checklist

### Auto-Verifiable (you must complete before committing)

- [ ] `tsc --noEmit` passes (or equivalent type-check)
- [ ] Build passes (no compilation errors)
- [ ] All existing tests still pass
- [ ] Run: `grep -rn "<old_pattern>"` — confirm no instances remain (or only 1 in the shared helper)
- [ ] Code review: Helper function has clear, single responsibility
- [ ] Code review: Helper function name reflects its purpose (not generic like `utils` or `helper`)
- [ ] Code review: No unintended side effects introduced

### Human-Verifiable (flag if unsure)

- [ ] Refactored code is objectively easier to understand and modify
- [ ] The new helper could be useful in future changes (not just this file)
- [ ] No over-engineering: the helper is exactly as complex as it needs to be

---

## How to Use This Template

1. Copy to your task queue: `cat configs/templates/task-refactor-bot.md >> tasks.txt`
2. Replace `[PLACEHOLDERS]` with specific files/patterns and duplication types
3. Run with batch-tasks: `bash batch-tasks tasks.txt`
4. Worker will identify duplication, extract helpers, and test

## Tips for the Worker

1. Start by reading all files in scope and identify similar patterns
2. Don't refactor prematurely — only extract code that appears 2+ times
3. Test frequently: run tests after each helper extraction
4. Use meaningful names: if you can't name it clearly, the abstraction isn't right
5. Keep helpers small and focused (≤15 lines if possible)
6. Add a docstring to helpers explaining what they do and why they exist
7. Commit each helper extraction separately:
   - `committer "refactor: extract {helper_name} helper"`
   - `committer "refactor: use {helper_name} in {file}"`
