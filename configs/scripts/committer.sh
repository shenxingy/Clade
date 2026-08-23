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

# VCS identity is an explicit human-owned trust anchor. It must never be
# inferred from the active Claude/Codex/provider account, whose login email may
# belong to a different person. Resolve the helper like checks.sh so source
# checkouts and installed copies enforce the same boundary.
GIT_IDENTITY_PY=""
if [[ -f "$SELF_DIR/git_identity.py" ]]; then
  GIT_IDENTITY_PY="$SELF_DIR/git_identity.py"
elif [[ -f "$HOME/.claude/scripts/git_identity.py" ]]; then
  GIT_IDENTITY_PY="$HOME/.claude/scripts/git_identity.py"
fi
PYTHON_BIN=""
if command -v python3 &>/dev/null; then
  PYTHON_BIN="python3"
elif command -v python &>/dev/null; then
  PYTHON_BIN="python"
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

# Fail before touching the index when the identity is absent, configured for a
# different human, or contaminated by GIT_AUTHOR_*/GIT_COMMITTER_* variables.
if [[ -z "$GIT_IDENTITY_PY" || -z "$PYTHON_BIN" ]]; then
  echo "Error: Clade Git identity guard is unavailable; refusing to commit." >&2
  exit 1
fi
if ! "$PYTHON_BIN" "$GIT_IDENTITY_PY" check --repo .; then
  exit 1
fi
IDENTITY_TSV=$("$PYTHON_BIN" "$GIT_IDENTITY_PY" show --format tsv)
IFS=$'\t' read -r PINNED_GIT_NAME PINNED_GIT_EMAIL <<< "$IDENTITY_TSV"
export GIT_AUTHOR_NAME="$PINNED_GIT_NAME"
export GIT_AUTHOR_EMAIL="$PINNED_GIT_EMAIL"
export GIT_COMMITTER_NAME="$PINNED_GIT_NAME"
export GIT_COMMITTER_EMAIL="$PINNED_GIT_EMAIL"

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

# Commit — autonomous workers (orchestrator / loop-runner export
# CLADE_WORKER_TASK_ID) get traceability trailers so learning loops can
# segment agent vs human commits; interactive sessions stay trailer-free.
# Agent-Signature records model provenance (Round-4 gap, Yegge pattern):
# worker_fallback_model can silently swap a worker onto a different model
# mid-run, so X-Clade-Task alone can't tell you which model wrote a given
# commit — CLADE_WORKER_MODEL (set by worker.py's _build_cmd_and_env) does.
# All trailers share one -m so git parses them as a single trailer block.
COMMIT_ARGS=(-m "$MSG")
if [[ -n "${CLADE_WORKER_TASK_ID:-}" ]]; then
  COMMIT_ARGS+=(-m "X-Clade-Task: ${CLADE_WORKER_TASK_ID}
Agent-Signature: ${CLADE_WORKER_MODEL:-unknown-model}")
fi
git --no-pager commit "${COMMIT_ARGS[@]}"
if ! "$PYTHON_BIN" "$GIT_IDENTITY_PY" verify-head --repo .; then
  echo "FATAL: commit was created with unexpected attribution; stop delivery and inspect HEAD." >&2
  exit 1
fi
echo "Committed: $MSG"

# Push
if [[ "$DO_PUSH" == true ]]; then
  git push
fi
