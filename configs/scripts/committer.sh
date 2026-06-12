#!/usr/bin/env bash
# committer — Safe commit script for multi-agent parallel development
#
# Usage: committer "feat: message" file1 file2 ... [--no-push]
#
# Why: When running 3-4 parallel Claude Code sessions on the same repo,
# `git add .` stages ALL files and causes agents to interfere with each other.
# This script forces explicit file specification, preventing cross-agent contamination.
#
# Convention: conventional commit format required (feat/fix/refactor/test/chore/docs/perf)
# Push: enabled by default. Pass --no-push to skip (e.g. parallel agent worktrees).

set -euo pipefail

# Resolve shared checks.sh (staged-secret scan, shellcheck, commit-msg regex) —
# sibling copy first (repo checkouts / CI), then the deployed copy. Missing on
# a fresh machine → gates are skipped so committer still bootstraps.
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECKS_SH=""
if [[ -f "$SELF_DIR/checks.sh" ]]; then
  CHECKS_SH="$SELF_DIR/checks.sh"
elif [[ -f "$HOME/.claude/scripts/checks.sh" ]]; then
  CHECKS_SH="$HOME/.claude/scripts/checks.sh"
fi

MSG="${1:-}"
if [[ -z "$MSG" ]]; then
  echo "Usage: committer <message> <file> [file2...] [--no-push]" >&2
  echo "" >&2
  echo "  Message format: conventional commits" >&2
  echo "  Examples:" >&2
  echo "    committer \"feat(auth): add JWT refresh\" src/auth.ts" >&2
  echo "    committer \"fix: resolve null pointer\" lib/user.ts lib/session.ts" >&2
  echo "    committer \"chore: update deps\" package.json pnpm-lock.yaml" >&2
  echo "" >&2
  echo "  Prefixes: feat fix refactor test chore docs perf style ci build" >&2
  echo "  Flags:    --no-push  skip git push after commit" >&2
  exit 1
fi
shift

# Parse --no-push flag from remaining args
DO_PUSH=true
FILTERED_ARGS=()
for arg in "$@"; do
  if [[ "$arg" == "--no-push" ]]; then
    DO_PUSH=false
  else
    FILTERED_ARGS+=("$arg")
  fi
done
set -- "${FILTERED_ARGS[@]}"

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

# Validate conventional commit format (shared regex lives in checks.sh;
# inline fallback keeps committer standalone on machines without checks.sh)
if [[ -n "$CHECKS_SH" ]]; then
  bash "$CHECKS_SH" commit-msg "$MSG" || exit 1
elif ! echo "$MSG" | head -1 | grep -qE '^(feat|fix|refactor|test|chore|docs|perf|style|ci|build)(\(.+\))?: .+'; then
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

# Pre-commit gate (fail-closed): staged-secret scan + shellcheck on staged .sh.
# Escape hatches: CLADE_ALLOW_SECRETS=1 / CLADE_SKIP_SHELLCHECK=1 (see checks.sh)
if [[ -n "$CHECKS_SH" ]] && ! bash "$CHECKS_SH" staged; then
  git restore --staged :/ 2>/dev/null || true
  echo "Aborted: pre-commit checks failed — nothing committed." >&2
  exit 1
fi

# Show exactly what will be committed
echo "Staged changes:"
git --no-pager diff --cached --stat
echo ""

# Commit
git --no-pager commit -m "$MSG"
echo "Committed: $MSG"

# Push
if [[ "$DO_PUSH" == true ]]; then
  git push
fi
