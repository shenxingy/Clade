#!/usr/bin/env bash
# sync-push.sh — Push local changes to sync backend
#
# Called by:
#   - memory-sync.sh hook (after memory file write, async)
#   - Manually after bulk changes
#
# Uses a lockfile to prevent concurrent pushes from racing.

set -euo pipefail

CLAUDE_DIR="$HOME/.claude"
SYNC_CONFIG="$CLAUDE_DIR/.sync-config"

[[ -f "$SYNC_CONFIG" ]] || exit 0
# shellcheck source=/dev/null
source "$SYNC_CONFIG"

[[ "${SYNC_BACKEND:-none}" == "none" ]] && exit 0
[[ -d "${SYNC_DIR:-}" ]] || exit 0

# ─── Lock: prevent concurrent pushes ─────────────────────────────────────────

# Lock location: a per-user scratch root, never a fixed /tmp path. On a shared
# host the first account to create /tmp/claude-sync-push.lock owns it; for every
# other account `exec 9>` then fails and, under `set -e`, KILLS this script —
# the memory-sync hook's push is silently dead. $CLAUDE_DIR is $HOME-private and
# is the fallback when no runtime root resolves.
_SP_RUNTIME_LIB="$(cd "$(dirname "$0")" 2>/dev/null && pwd)/../hooks/lib/runtime-dir.sh"
if [[ -f "$_SP_RUNTIME_LIB" ]]; then
  # shellcheck source=/dev/null
  . "$_SP_RUNTIME_LIB" 2>/dev/null || true
fi
if [[ -n "${CLADE_SYNC_PUSH_LOCK:-}" ]]; then
  LOCK_FILE="$CLADE_SYNC_PUSH_LOCK"
elif declare -f clade_runtime_dir >/dev/null 2>&1 && _SP_RT=$(clade_runtime_dir 2>/dev/null); then
  LOCK_FILE="$_SP_RT/sync-push.lock"
else
  LOCK_FILE="$CLAUDE_DIR/.sync-push.lock"
fi

# flock is absent on Git Bash / minimal envs; guard so `set -e` doesn't abort the
# push there. Concurrent pushes are rare and git's own index lock is the backstop.
if command -v flock >/dev/null 2>&1; then
  # `|| exit 0`: an unopenable lock must degrade to "skip this push", never to
  # a `set -e` abort that leaves no log line anywhere.
  exec 9>"$LOCK_FILE" || exit 0
  flock -n 9 || exit 0  # another push is already running, skip
fi

# ─── Stage + commit ──────────────────────────────────────────────────────────

cd "$SYNC_DIR"

# NEVER stage a file carrying conflict markers. This is not hygiene — it is the
# bug that ate the correction log. `git pull --rebase --autostash` leaves marker
# text in the working tree when the AUTOSTASH POP conflicts (not the rebase), and
# `git rebase --abort` does not clean that up. The next run's `git add -A` then
# committed the markers, and the run after that conflicted on a file that already
# contained markers, so they nested and multiplied. Measured on this account
# 2026-09-17: 11 marker lines, two levels deep, sitting in a file injected into
# every session's context.
_marker_files=""
while IFS= read -r _f; do
  [ -f "$_f" ] || continue
  if grep -qE '^(<<<<<<< |=======$|>>>>>>> )' "$_f" 2>/dev/null; then
    _marker_files="$_marker_files $_f"
  fi
done < <(git ls-files -mo --exclude-standard 2>/dev/null)
if [ -n "$_marker_files" ]; then
  echo "[$(date)] sync-push REFUSED: conflict markers in$_marker_files" \
    >> "$CLAUDE_DIR/.sync-conflicts.log"
  echo "sync-push: conflict markers present, refusing to commit:$_marker_files" >&2
  echo "sync-push: resolve them by hand, then the next sync will proceed." >&2
  exit 1
fi

git add -A 2>/dev/null || exit 0

# Nothing to commit?
git diff --cached --quiet 2>/dev/null && exit 0

git commit -m "sync: $(hostname) $(date +%H:%M)" --quiet 2>/dev/null || exit 0

# ─── Push to GitHub remote (both github and nfs-with-remote modes) ───────────

HAS_REMOTE=$(git remote 2>/dev/null | grep -c origin || true)
if [[ "$SYNC_BACKEND" == "github" ]] || [[ "$HAS_REMOTE" -gt 0 ]]; then
  # Pull --rebase first to integrate any remote changes
  git pull --rebase --autostash --quiet 2>/dev/null || {
    # Conflict. `-X ours` used to run here unconditionally, and on an APPEND-ONLY
    # log that is the wrong semantics: "ours wins" discards whatever the other
    # machine appended. Traced on this account 2026-09-17 — 191 rule
    # disappearances from corrections/rules.md, every one inside a `sync:` or
    # `Merge` commit and NOT ONE inside an audit/promote commit, which is what a
    # deliberate retirement would look like. 178 rules survived only in history.
    #
    # `.gitattributes` now marks those files `merge=union`, so git concatenates
    # both sides and they never reach this path. What does reach it is a genuine
    # conflict in a non-append file, and there `ours` is still the safest default
    # for an unattended sync — but it is RECORDED per file, never silent.
    git rebase --abort 2>/dev/null || true
    REMOTE_BRANCH=$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || echo "origin/master")
    _conflicted=$(git diff --name-only "$REMOTE_BRANCH"...HEAD 2>/dev/null | tr '\n' ' ')
    git merge --no-edit -X ours "$REMOTE_BRANCH" 2>/dev/null || true
    echo "[$(date)] sync conflict on $(hostname) — merged -X ours; their side dropped for:$_conflicted" \
      >> "$CLAUDE_DIR/.sync-conflicts.log"
  }

  # Retry push up to 3 times
  for attempt in 1 2 3; do
    git push --quiet 2>/dev/null && break
    [[ $attempt -lt 3 ]] && sleep 2
  done || {
    echo "sync-push: push failed after 3 attempts (will retry next session)" >&2
  }
fi

exit 0
