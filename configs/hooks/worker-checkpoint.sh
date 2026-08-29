#!/usr/bin/env bash
# worker-checkpoint.sh — snapshot the worktree after every agent file write.
# Triggered by PostToolUse on Edit|Write (async — data only, output unused).
#
# Clade can tell you THAT an attempt failed and hand back a digest-chained
# final diff. It cannot tell you WHEN it went wrong: a worker commits exactly
# once, at the end of verification, and `stop()` force-removes the worktree.
# The one 2026 paper with per-step annotation rather than pass/fail puts the
# decisive error at median step 7 — precisely the interval with no record.
#
# This writes one commit per tool call into a shadow repository OUTSIDE the
# worktree, so "correct at call 14, wrong at 15" becomes answerable.
#
# Why a separate --git-dir is safe (measured, not assumed):
#   - the worktree's own index is byte-identical before and after a shadow
#     commit — separate git-dir means separate index, so no index.lock contention
#   - a shadow commit taken WHILE the worker is committing succeeds, and so
#     does the worker's commit
#   - the worktree stays clean: `git status` never mentions the shadow
#
# Fires only when the orchestrator sets CLADE_WORKER_SHADOW_DIR at spawn.
# Interactive sessions never set it, so this hook is inert there.
#
# Fail-open: any error is silently ignored. A checkpoint is evidence, never a
# gate — it must not be able to stop a worker.

INPUT=$(cat)

SHADOW="${CLADE_WORKER_SHADOW_DIR:-}"
[[ -z "$SHADOW" ]] && exit 0

FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
[[ -z "$FILE_PATH" ]] && exit 0

WORKTREE="${CLADE_WORKER_WORKTREE:-$PWD}"
[[ -d "$WORKTREE" ]] || exit 0

if [[ ! -d "$SHADOW" ]]; then
  mkdir -p "$(dirname "$SHADOW")" 2>/dev/null || exit 0
  git init -q --bare "$SHADOW" 2>/dev/null || exit 0
  # A rescue history, not a reviewed one: identity is fixed here so it never
  # depends on the ambient git config, and hooks are off so a repo-supplied
  # pre-commit cannot block a checkpoint.
  git --git-dir="$SHADOW" config user.email "checkpoint@clade.local" 2>/dev/null
  git --git-dir="$SHADOW" config user.name "clade-checkpoint" 2>/dev/null
  git --git-dir="$SHADOW" config core.hooksPath /dev/null 2>/dev/null
fi

REL="${FILE_PATH#"$WORKTREE"/}"
TOOL=$(echo "$INPUT" | jq -r '.tool_name // "edit"' 2>/dev/null)

git --git-dir="$SHADOW" --work-tree="$WORKTREE" add -A >/dev/null 2>&1 || exit 0
# --allow-empty: a write that changed nothing is still a step in the timeline,
# and dropping it would renumber every later checkpoint.
git --git-dir="$SHADOW" --work-tree="$WORKTREE" \
  -c core.hooksPath=/dev/null \
  commit -q --no-verify --allow-empty -m "checkpoint: ${TOOL} ${REL}" >/dev/null 2>&1

exit 0
