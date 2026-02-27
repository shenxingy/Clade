===TASK===
model: haiku
TYPE: HORIZONTAL
---
# Test Writer — Add Unit Tests

## Goal

Improve test coverage for **[MODULE_NAME]** by adding unit tests for currently untested code paths.

## Context

**File(s) to test:** `[FILE_PATH]`
**Current coverage:** [X%]
**Target coverage:** 80%+
**Test framework:** [pytest/Jest/your framework]

Add comprehensive unit tests that:
- Cover all public functions/methods
- Include happy path + error cases
- Use realistic test data, not trivial mocks
- Follow the project's testing conventions

## Acceptance Criteria

- [ ] All public functions in [FILE_PATH] have at least one passing test
- [ ] Test file follows project naming convention (`test_*.py` or `*.test.ts`)
- [ ] Coverage for [FILE_PATH] is now ≥ 80%
- [ ] All tests pass when run locally
- [ ] Tests don't mock away the core logic — they test real behavior

### Edge Cases Covered
- [ ] Empty/null input is handled correctly
- [ ] Boundary conditions (min/max, first/last)
- [ ] Invalid input raises expected error (not silent failure)
- [ ] Async operations complete correctly (if applicable)

---

## Verification Checklist

### Auto-Verifiable (you must complete before committing)

- [ ] Run test suite: `[pytest|npm test]` — all tests pass
- [ ] Check coverage: `[pytest --cov|npm test -- --coverage]` shows ≥80% for [FILE_PATH]
- [ ] Code review: No test mocks that defeat the purpose (e.g., mocking database calls when testing DB queries)
- [ ] Code review: Assertions are meaningful (not just `assert True`)
- [ ] Code review: Test names describe what is being tested
- [ ] No console.error or unhandled promise rejections in test output

### Human-Verifiable (flag if unsure)

- [ ] Tests read like documentation — someone unfamiliar with the code understands the behavior from the test names
- [ ] Test data is realistic, not contrived
- [ ] Both positive and negative cases are tested

---

## How to Use This Template

1. Copy this file to your task queue: `cat configs/templates/task-test-writer.md >> tasks.txt`
2. Replace `[PLACEHOLDER]` fields with actual module info
3. Run with batch-tasks: `bash batch-tasks tasks.txt`
4. Worker will add tests and commit when coverage target is met

## Tips for the Worker

- Start by reading the target file to understand what functions exist
- List the functions/methods that currently have no tests
- Write one test per function, start with happy path
- Run tests frequently (after each function, not all at the end)
- Use existing tests in the codebase as a style reference
