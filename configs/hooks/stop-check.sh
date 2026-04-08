#!/bin/bash
# stop-check.sh — Verify session is actually complete before stopping.
# Hooks §Gap 3: Prevents false-done sessions in overnight autonomous loops.
# Blocks (exit 2) if: uncommitted changes exist or blockers.md has entries.
# Runs as a Stop event hook alongside the existing LLM prompt check.

# Only run inside a git repository
if ! git rev-parse --is-inside-work-tree &>/dev/null 2>&1; then
    exit 0
fi

issues=()

# Check for uncommitted changes (staged or unstaged)
UNSTAGED=$(git diff --name-only 2>/dev/null | wc -l | tr -d '[:space:]')
STAGED=$(git diff --cached --name-only 2>/dev/null | wc -l | tr -d '[:space:]')
UNTRACKED=$(git ls-files --others --exclude-standard 2>/dev/null | grep -v '^\.claude/' | wc -l | tr -d '[:space:]')
if [[ "${STAGED:-0}" -gt 0 ]]; then
    issues+=("${STAGED} staged (but uncommitted) file(s). Commit them before stopping.")
fi
if [[ "${UNSTAGED:-0}" -gt 0 ]]; then
    issues+=("${UNSTAGED} modified (unstaged) file(s). Stage and commit or revert before stopping.")
fi
if [[ "${UNTRACKED:-0}" -gt 0 ]]; then
    issues+=("${UNTRACKED} untracked file(s) outside .claude/. Check if they should be committed.")
fi

# Check for active blockers
BLOCKER_FILE=".claude/blockers.md"
if [[ -f "$BLOCKER_FILE" ]]; then
    BLOCKER_COUNT=$(grep -c "^## Blocker" "$BLOCKER_FILE" 2>/dev/null || echo 0)
    if [[ "${BLOCKER_COUNT:-0}" -gt 0 ]]; then
        issues+=("${BLOCKER_COUNT} blocker(s) recorded in .claude/blockers.md.")
    fi
fi

if [[ ${#issues[@]} -gt 0 ]]; then
    echo "[stop-check] Session not clean:" >&2
    for issue in "${issues[@]}"; do
        echo "  - $issue" >&2
    done
    exit 2
fi

exit 0
