# /ship — Full Release Pipeline

Full release pipeline: tests → coverage → review gate → version bump → CHANGELOG → commit → PR.
Each step is a hard gate — failure stops the pipeline and reports clearly.

**Flags:** `--no-bump` (skip version bump + CHANGELOG), `--no-pr` (skip PR creation), `--dry-run` (show plan only, no changes)

---

## Steps

### Step 1: Pre-flight

1. Check working tree is clean: `git status --porcelain`. If dirty, report what's uncommitted and STOP with BLOCKED.
2. Confirm `gh` CLI is available: `gh --version`. If missing, skip Step 7 (PR) and warn.
3. Detect platform:
   - Python: `pyproject.toml` or `setup.py`
   - Node: `package.json`
   - Other: report "no version file found" and skip Step 4-5

### Step 2: Run Tests

Run the project test command in order of precedence:
1. `CLAUDE.md` `## Test command:` line if present
2. `.claude/orchestrator.json` `test_cmd` field if present
3. Auto-detect: `pytest` if `tests/` exists, `npm test` if `package.json` has test script

Run the command. If ANY test fails:
- Show the failure output (first 50 lines)
- STOP with BLOCKED: `Test suite failed — fix failures before shipping`

Report: `✅ Tests: N passed`

### Step 3: Review Gate

Check if VERIFY.md exists and has a recent full pass (within 7 days — check `Last full pass:` line).

If VERIFY.md exists and pass is recent: `✅ Review: VERIFY.md passed on [date] (within 7 days)`
If VERIFY.md is stale or missing: run `/review` inline OR report `⚠ Review gate skipped — run /review to verify`

Do NOT block on this step — warn and continue.

### Step 4: Version Bump (skip with --no-bump)

1. Read current version:
   - `pyproject.toml`: `version = "X.Y.Z"` under `[project]` or `[tool.poetry]`
   - `package.json`: `"version": "X.Y.Z"`
   - `setup.py`: `version='X.Y.Z'`
2. Ask user: "Bump type? [patch (default) / minor / major]" — use AskUserQuestion if interactive, else default to patch.
3. Compute new version (X.Y.Z+1 for patch, X.Y+1.0 for minor, X+1.0.0 for major).
4. Write new version string back to the source file.
5. Report: `Version: X.Y.Z → X.Y.Z+1`

### Step 5: CHANGELOG (skip with --no-bump)

1. Get previous git tag: `git describe --tags --abbrev=0 2>/dev/null || echo ""`
2. Get commit log since tag: `git log --oneline <prev-tag>..HEAD` (or `git log --oneline -20` if no tag)
3. Group commits by conventional type (feat/fix/chore/docs/refactor/test/perf).
4. Prepend entry to `CHANGELOG.md` (create if missing):
   ```markdown
   ## [X.Y.Z+1] — YYYY-MM-DD

   ### Features
   - feat: description (abc1234)

   ### Fixes
   - fix: description (def5678)
   ```
5. Report: `CHANGELOG.md updated`

### Step 6: Commit Version + CHANGELOG

Use `committer` script for the version bump and CHANGELOG:
```bash
committer "chore: bump version to X.Y.Z+1" <version-file> CHANGELOG.md
```

Report: `✅ Committed: chore: bump version to X.Y.Z+1`

### Step 7: Create PR (skip with --no-pr or if gh unavailable)

```bash
gh pr create \
  --title "Release vX.Y.Z+1" \
  --body "$(cat <<'BODY'
## Release vX.Y.Z+1

<CHANGELOG section for this version>

## Test plan
- [x] All tests pass
- [x] Version bumped in source file
- [x] CHANGELOG updated
BODY
)"
```

Report: `✅ PR created: <url>`

---

## Summary Output

```
/ship complete:
  ✅ Tests: 178 passed
  ✅ Review: VERIFY.md passed 2026-04-10
  ✅ Version: 1.2.3 → 1.2.4
  ✅ CHANGELOG: updated
  ✅ Committed: chore: bump version to 1.2.4
  ✅ PR: https://github.com/...
```

---

## Completion Status

- ✅ **DONE** — all steps completed, PR created (or --no-pr specified)
- ⚠ **DONE_WITH_CONCERNS** — PR created but review gate was stale; run /review to verify
- ❌ **BLOCKED** — test failure, dirty working tree, or git conflict; write to `.claude/blockers.md`
- ❓ **NEEDS_CONTEXT** — no version file found or test command unknown; ask user
