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
# Push: on by default, and ONLY to the remote branch with the same name as the
#   local branch (see "Push" at the bottom for the four cases). A branch that
#   tracks a differently named branch — `git worktree add -b X <path>
#   origin/main` gives X the upstream origin/main — is committed and NOT
#   pushed. Autonomous workers (CLADE_WORKER_TASK_ID set — parallel agent
#   worktrees, loop and orchestrator workers) never push; their runner merges
#   or pushes. Pass --no-push to skip pushing anywhere else.
# Exit: 0 committed (pushed, or the push skipped with a message saying why);
#   3 committed, but the push itself failed; 1 a refusal before the commit, or
#   the FATAL attribution check on the new HEAD.

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
  echo "  Flags:    --no-push  skip the push after the commit" >&2
  echo "  Push:     only to the remote branch named like the local one; a branch" >&2
  echo "            tracking another name (e.g. origin/main) is not pushed, and" >&2
  echo "            nor is a worker commit (CLADE_WORKER_TASK_ID set)" >&2
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
if [[ -n "$CHECKS_SH" ]] && ! bash "$CHECKS_SH" staged "$MSG"; then
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

# ─── Push ─────────────────────────────────────────────────────────────
# Publish only to the remote branch with the SAME name as the local branch.
# This used to be a bare `git push`, and its destination was whatever the
# branch tracked. `git worktree add -b fix/x <path> origin/main` — the usual
# way to start work — makes origin/main the upstream of fix/x, so:
#   push.default=simple (git's default) refused it, and committer then exited
#     non-zero after a successful commit, which a caller reads as "not
#     committed";
#   push.default=upstream pushed the feature commit straight onto main;
#   push.default=matching pushed every same-named branch, not only this one.
# An explicit `<remote> HEAD:refs/heads/<branch>` refspec takes push.default
# out of it. Never forced: a rejected push stays rejected.
#   autonomous worker      → skip with a message, exit 0 (see below)
#   detached HEAD          → skip with a message, exit 0
#   upstream, other name   → skip, print how to push it explicitly, exit 0
#   upstream, same name    → push to it
#   no upstream            → push -u to <remote>/<branch>, where <remote> is
#                            the branch's configured push remote, else origin;
#                            neither → skip with a message, exit 0
# A push that git itself rejects exits 3, distinct from the 1 of a pre-commit refusal.
#
# Autonomous workers (CLADE_WORKER_TASK_ID set) never push. Their runner owns
# delivery: run-tasks-parallel.sh merges each batch/task-* branch into the
# main checkout locally and deletes it, and orchestrator/worker.py runs its
# tests and oracle gate BEFORE its own auto_push and undoes the commit on
# failure. A worker branch has no upstream, so the `-u` path below would
# otherwise publish every unreviewed task branch and leave it on the remote.
push_same_name_branch() {
  local ref branch merge upstream_branch remote shown
  if [[ -n "${CLADE_WORKER_TASK_ID:-}" ]]; then
    echo "Not pushed: autonomous worker commit (CLADE_WORKER_TASK_ID is set); the runner that launched it integrates or pushes. The commit is kept." >&2
    return 0
  fi
  # The full ref, not `--short`: when a tag or another ref shares the branch's
  # name, `--short` answers `heads/<name>`, and every lookup below would miss
  # the real branch's config and push to refs/heads/heads/<name>.
  if ! ref=$(git symbolic-ref --quiet HEAD 2>/dev/null); then
    echo "Not pushed: detached HEAD, so there is no branch to push. The commit is kept." >&2
    return 0
  fi
  if [[ "$ref" != refs/heads/* ]]; then
    echo "Not pushed: HEAD points at '$ref', which is not a local branch. The commit is kept." >&2
    return 0
  fi
  branch="${ref#refs/heads/}"

  # The remote `git push` itself would pick: branch.<b>.pushRemote overrides
  # remote.pushDefault, which overrides branch.<b>.remote. "." means "this
  # repository" (a branch tracking a LOCAL branch) and is never a push target.
  remote=$(git config --get "branch.$branch.pushRemote" 2>/dev/null || true)
  [[ -n "$remote" ]] || remote=$(git config --get remote.pushDefault 2>/dev/null || true)
  [[ -n "$remote" ]] || remote=$(git config --get "branch.$branch.remote" 2>/dev/null || true)
  [[ "$remote" != "." ]] || remote=""
  if [[ -z "$remote" ]] && git remote get-url origin >/dev/null 2>&1; then
    remote="origin"
  fi

  # Upstream = branch.<b>.merge. Any value names the branch it tracks; treat
  # one that is set without branch.<b>.remote as an upstream too — skipping a
  # push is the safe reading of a half-written tracking config.
  merge=$(git config --get "branch.$branch.merge" 2>/dev/null || true)
  upstream_branch="${merge#refs/heads/}"
  if [[ -n "$merge" && "$upstream_branch" != "$branch" ]]; then
    shown="$(git config --get "branch.$branch.remote" 2>/dev/null || true)"
    if [[ -z "$shown" || "$shown" == "." ]]; then
      shown="the local branch '$upstream_branch'"
    else
      shown="'$shown/$upstream_branch'"
    fi
    echo "Not pushed: '$branch' tracks $shown, not a branch named '$branch'. The commit is kept." >&2
    echo "  To publish it under its own name: git push -u ${remote:-<remote>} HEAD:refs/heads/$branch" >&2
    return 0
  fi

  if [[ -z "$remote" ]]; then
    echo "Not pushed: '$branch' has no push remote configured and the repository has no 'origin' remote. The commit is kept." >&2
    return 0
  fi
  if [[ -n "$merge" ]]; then
    git push "$remote" "HEAD:refs/heads/$branch" || return 3
  else
    git push -u "$remote" "HEAD:refs/heads/$branch" || return 3
  fi
  return 0
}

if [[ "$DO_PUSH" == true ]]; then
  PUSH_RC=0
  push_same_name_branch || PUSH_RC=$?
  if [[ "$PUSH_RC" -ne 0 ]]; then
    echo "Push FAILED (the commit above is kept locally; nothing was forced)." >&2
    exit "$PUSH_RC"
  fi
fi
