#!/usr/bin/env bash
# committer — Safe commit script for multi-agent parallel development
#
# Usage: committer "feat: message" file1 file2 ...
#
# Why: When running 3-4 parallel Claude Code sessions on the same repo,
# `git add .` stages ALL files and causes agents to interfere with each other.
# This script forces explicit file specification, preventing cross-agent contamination.
#
# Convention: conventional commit format required (feat/fix/refactor/test/chore/docs/perf)

set -euo pipefail

MSG="${1:-}"
if [[ -z "$MSG" ]]; then
  echo "Usage: committer <message> <file> [file2...]" >&2
  echo "" >&2
  echo "  Message format: conventional commits" >&2
  echo "  Examples:" >&2
  echo "    committer \"feat(auth): add JWT refresh\" src/auth.ts" >&2
  echo "    committer \"fix: resolve null pointer\" lib/user.ts lib/session.ts" >&2
  echo "    committer \"chore: update deps\" package.json pnpm-lock.yaml" >&2
  echo "" >&2
  echo "  Prefixes: feat fix refactor test chore docs perf style ci build" >&2
  exit 1
fi
shift

if [[ $# -eq 0 ]]; then
  echo "Error: must specify files explicitly." >&2
  echo "  'git add .' is not allowed — it interferes with parallel agent sessions." >&2
  exit 1
fi

# Reject glob wildcards and directory shortcuts
for f in "$@"; do
  if [[ "$f" == "." || "$f" == ".." || "$f" == "*" ]]; then
    echo "Error: '$f' is not allowed. Specify exact file paths." >&2
    echo "  Parallel agents use git add . to interfere — this prevents that." >&2
    exit 1
  fi
done

# Validate conventional commit format
if ! echo "$MSG" | grep -qE '^(feat|fix|refactor|test|chore|docs|perf|style|ci|build)(\(.+\))?: .+'; then
  echo "Error: Commit message must follow conventional commit format." >&2
  echo "  Pattern: <type>(<scope>): <description>" >&2
  echo "  Types:   feat fix refactor test chore docs perf style ci build" >&2
  echo "  Got:     $MSG" >&2
  exit 1
fi

# Reset staging area — clear any previously staged files from other agents
git restore --staged :/ 2>/dev/null || true

# Stage only the explicitly specified files
git add -- "$@"

# Show exactly what will be committed
echo "Staged changes:"
git diff --cached --stat
echo ""

# Commit
git commit -m "$MSG"
echo "Committed: $MSG"
