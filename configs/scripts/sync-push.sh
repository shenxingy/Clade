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

LOCK_FILE="/tmp/claude-sync-push.lock"
exec 9>"$LOCK_FILE"
flock -n 9 || exit 0  # another push is already running, skip

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
    # Conflict — keep both versions
    git rebase --abort 2>/dev/null || true
    git merge --no-edit -s recursive -X ours 2>/dev/null || true
    # Log conflict for awareness
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
