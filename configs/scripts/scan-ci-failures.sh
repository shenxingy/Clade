#!/usr/bin/env bash
# scan-ci-failures — Generate tasks from failed CI runs
#
# Usage: bash scan-ci-failures.sh [repo-dir] [max-runs]
#
# Fetches recent failed GitHub Actions runs and generates task blocks for each.
# Output format: ===TASK=== blocks (can append to tasks.txt)
#
# Dependencies: gh CLI configured and authenticated
#
# Why: Closes the loop on CI failures — instead of manual discovery,
# auto-generate fix tasks with log context so workers understand the failure.

set -euo pipefail

REPO_DIR="${1:-.}"
MAX_RUNS="${2:-5}"

# Verify we're in a git repo or the specified repo exists
if [[ ! -d "$REPO_DIR/.git" ]]; then
  echo "Error: $REPO_DIR is not a git repository" >&2
  exit 1
fi

# Check gh CLI availability
if ! command -v gh &>/dev/null; then
  echo "Error: gh CLI not found. Install from https://cli.github.com/" >&2
  exit 1
fi

cd "$REPO_DIR"

# Get repository owner/name
REPO_FULL=$(gh repo view --json nameWithOwner --jq '.nameWithOwner')
if [[ -z "$REPO_FULL" ]]; then
  echo "Error: Could not determine repository. Run from a git repo with 'gh auth login'." >&2
  exit 1
fi

echo "# CI Failure Tasks — $REPO_FULL"
echo ""

# Fetch latest failed runs
FAILED_RUNS=$(gh run list --status failure --limit "$MAX_RUNS" --json databaseId,name,conclusion,headBranch --jq '.[]')

if [[ -z "$FAILED_RUNS" ]]; then
  echo "No failed CI runs found."
  exit 0
fi

# Process each failure
while IFS= read -r run_obj; do
  RUN_ID=$(echo "$run_obj" | jq -r '.databaseId')
  RUN_NAME=$(echo "$run_obj" | jq -r '.name')
  BRANCH=$(echo "$run_obj" | jq -r '.headBranch')

  # Fetch run details and extract first failed step
  RUN_DETAILS=$(gh run view "$RUN_ID" --json jobs,url --jq '.')

  # Find the first failed job
  FAILED_JOB=$(echo "$RUN_DETAILS" | jq -r '.jobs[]? | select(.conclusion == "failure") | .name' | head -1)
  FAILED_STEP=""

  if [[ -n "$FAILED_JOB" ]]; then
    # Try to get step-level details
    FAILED_STEP=$(echo "$RUN_DETAILS" | jq -r ".jobs[]? | select(.name == \"$FAILED_JOB\") | .steps[]? | select(.conclusion == \"failure\") | .name" | head -1)
  fi

  STEP_NAME="${FAILED_STEP:-$FAILED_JOB}"

  # Get run logs (last 20 lines for context)
  LOG_URL=$(echo "$RUN_DETAILS" | jq -r '.url')

  # Generate task block
  cat <<EOF
===TASK===
model: sonnet
TYPE: VERTICAL
source_ref: ci_run_$RUN_ID
---
fix: CI failure in "$STEP_NAME" on branch $BRANCH

## Context
- Run: $RUN_NAME
- Failed step: $STEP_NAME
- Repository: $REPO_FULL
- Branch: $BRANCH
- Logs: $LOG_URL

## What to do
1. Review the failed CI run logs
2. Identify root cause
3. Fix the code and ensure the step passes locally
4. Run \`git commit -m "fix: resolve CI failure in $STEP_NAME"\` when done

EOF

done <<< "$FAILED_RUNS"

echo "# End of CI failure tasks"
