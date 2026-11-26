#!/usr/bin/env bash
# worker-checkpoint.sh — snapshot the worktree after every agent file write.
# exists-for: a worker's work had no record between its single commit and the deletion of its worktree (added 2026-08-29 in ce44dbf) · retire-when: no runner sets CLADE_WORKER_SHADOW_DIR any more (run-tasks-parallel.sh, orchestrator/worker.py)
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
# What a snapshot holds: exactly what `git add -A` in the worktree itself would
# stage — its tracked files plus the untracked files its ignore rules admit.
# See "Mirror the worktree's ignore rules" below for why that takes work.
#
# Fail-open: any error is silently ignored. A checkpoint is evidence, never a
# gate — it must not be able to stop a worker.

INPUT=$(cat)

SHADOW="${CLADE_WORKER_SHADOW_DIR:-}"
[[ -z "$SHADOW" ]] && exit 0
# Absolute before the `cd` below, so a relative setting means what it always did.
case "$SHADOW" in /*) ;; *) SHADOW="$PWD/$SHADOW" ;; esac

# FILE_PATH is a LABEL, not a gate. The snapshot below is `add -A` over the whole
# worktree, so it never needed a path — and requiring one made this hook blind to
# a Bash-tool write, which is precisely the failure it exists to catch. Ronacher's
# primary complaint about the unattended run was the model abandoning the edit
# tool for Python string splicing: "you're going to have to resort to using the
# diff viewer of the final artifacts." A checkpointer that only sees Edit|Write
# records nothing for exactly that run.
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)

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

REL="${FILE_PATH:+${FILE_PATH#"$WORKTREE"/}}"
REL="${REL:-<bash-write>}"
TOOL=$(echo "$INPUT" | jq -r '.tool_name // "edit"' 2>/dev/null)

# Every path below is relative to the work-tree root. From a subdirectory git
# would read them against it, and ls-files would list only that subtree.
cd "$WORKTREE" 2>/dev/null || exit 0
WORKTREE=$PWD

# ─── Mirror the worktree's ignore rules ───
# The shadow is a fresh bare repository, so its own info/exclude is empty and
# its own index decides what counts as tracked. Left alone, `add -A` honours
# the worktree's .gitignore files (they sit in the work tree) and a global
# core.excludesFile (ambient config), and nothing else. Probed 2026-11-26 on a
# linked worktree, the shape run-tasks-parallel.sh creates: a file listed only
# in info/exclude landed in the shadow, and a file the worktree tracks although
# a rule matches it (`git add -f`) never did.
#
# info/exclude lives in the COMMON git dir of a linked worktree; --git-path
# resolves that. On a main worktree it prints a path relative to the cwd, which
# the cd above made the work-tree root.
EXCLUDE=$(git rev-parse --git-path info/exclude 2>/dev/null)
mkdir -p "$SHADOW/info" 2>/dev/null
if [[ -f "$EXCLUDE" ]]; then
  # Copied every run, so an edit to it reaches the next snapshot; through a
  # temp file, so a concurrent run never reads it half-written.
  cp "$EXCLUDE" "$SHADOW/info/exclude.$$" 2>/dev/null \
    && mv -f "$SHADOW/info/exclude.$$" "$SHADOW/info/exclude" 2>/dev/null
else
  : > "$SHADOW/info/exclude" 2>/dev/null
fi
SHADOW_GIT=(--git-dir="$SHADOW" --work-tree="$WORKTREE")
# A repo-local core.excludesFile is in the worktree's config, which the shadow
# never reads. `config --get` also returns a global one; passing that again
# changes nothing.
EXCLUDES_FILE=$(git config --get core.excludesFile 2>/dev/null)
[[ -n "$EXCLUDES_FILE" ]] && SHADOW_GIT+=(-c "core.excludesFile=$EXCLUDES_FILE")

# Ignore rules apply only to untracked files, and add -A asks the SHADOW's
# index which files those are. So a path an earlier snapshot recorded (a shadow
# reused from a run before this fix, or a rule added mid-run) stays in every
# later one: drop each one a rule now matches, from the shadow's index only —
# the worktree is never touched. check-ignore, run in the worktree, names only
# the paths the worktree does not track, so a tracked one is never dropped:
# the step after add -A would put it back, but a run in parallel with this one
# could commit a snapshot without it in between.
DROP=$(git "${SHADOW_GIT[@]}" ls-files -ci --exclude-standard 2>/dev/null)
[[ -n "$DROP" ]] && printf '%s\n' "$DROP" | git check-ignore --stdin 2>/dev/null \
  | git "${SHADOW_GIT[@]}" update-index --force-remove --stdin >/dev/null 2>&1
git "${SHADOW_GIT[@]}" add -A >/dev/null 2>&1 || exit 0
# Then record each path the worktree tracks although a rule matches it, which
# `git status` reports and add -A into the shadow never would. update-index
# takes paths literally, skips an unchanged one by its stat data, and --remove
# keeps a path deleted since from aborting the rest.
KEEP=$(git ls-files -ci --exclude-standard 2>/dev/null)
[[ -n "$KEEP" ]] && printf '%s\n' "$KEEP" \
  | git "${SHADOW_GIT[@]}" update-index --add --remove --stdin >/dev/null 2>&1
# --allow-empty: a write that changed nothing is still a step in the timeline,
# and dropping it would renumber every later checkpoint.
git "${SHADOW_GIT[@]}" \
  -c core.hooksPath=/dev/null \
  commit -q --no-verify --allow-empty -m "checkpoint: ${TOOL} ${REL}" >/dev/null 2>&1

exit 0
