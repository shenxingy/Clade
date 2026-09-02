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

git add -A 2>/dev/null || exit 0

# Nothing to commit?
git diff --cached --quiet 2>/dev/null && exit 0

git commit -m "sync: $(hostname) $(date +%H:%M)" --quiet 2>/dev/null || exit 0

# ─── Push to GitHub remote (both github and nfs-with-remote modes) ───────────

HAS_REMOTE=$(git remote 2>/dev/null | grep -c origin || true)
if [[ "$SYNC_BACKEND" == "github" ]] || [[ "$HAS_REMOTE" -gt 0 ]]; then
  # Pull --rebase first to integrate any remote changes
  git pull --rebase --autostash --quiet 2>/dev/null || {
    # Conflict — abort rebase, merge with ours strategy
    git rebase --abort 2>/dev/null || true
    REMOTE_BRANCH=$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || echo "origin/master")
    git merge --no-edit -X ours "$REMOTE_BRANCH" 2>/dev/null || true
    echo "[$(date)] sync conflict on $(hostname) — merged with ours strategy" \
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
