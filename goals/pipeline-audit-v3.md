# Goal: Pipeline Deep Audit — Remaining Fixes

Fix remaining medium/high issues from the pipeline consistency audit. Critical issues were already fixed in prior commits.

## Remaining Fixes

### 1. verify-task-completed.sh: git diff logic
- File: `configs/hooks/verify-task-completed.sh` line ~25
- Current: `git diff --name-only HEAD~1` with fallback to `git diff --name-only` (unstaged only)
- Fix: Use `git diff --name-only --diff-filter=ACMR HEAD 2>/dev/null || echo ""`
- Also handle first-commit case where HEAD~1 doesn't exist

### 2. session-context.sh: macOS stat compatibility
- File: `configs/hooks/session-context.sh` line ~62-69
- Current: `stat -c %Y` (Linux-only)
- Fix: Add macOS fallback: `stat -c %Y "$f" 2>/dev/null || stat -f %m "$f" 2>/dev/null`
- Also handle race condition where file disappears between ls and stat

### 3. pre-tool-guardian.sh: rm -rf regex gaps
- File: `configs/hooks/pre-tool-guardian.sh`
- Current regex for detecting `rm -rf` on system dirs is complex and has gaps (doesn't catch path tricks like `/../`)
- Fix: Simplify the regex — detect `rm` with `-r` and `-f` flags (in any order) targeting `/`, `~`, `$HOME`, or known system paths
- Also fix force-push detection: `git[[:space:]]+push` doesn't handle double spaces

### 4. SKILL.md consistency: add user_invocable field
- All skill SKILL.md files should have `user_invocable: true` in their frontmatter for consistency
- Currently only `audit/SKILL.md` has it
- Files to update: batch-tasks, commit, handoff, loop, model-research, orchestrate, pickup, sync

## Success Criteria

- `bash -n` passes for all modified .sh files in configs/hooks/
- All SKILL.md files contain `user_invocable: true`
- `grep -rn "stat -c" configs/hooks/` returns 0 results (all replaced with cross-platform version)
- `grep -c "user_invocable" configs/skills/*/SKILL.md` shows all skills have the field
