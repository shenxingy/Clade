#!/usr/bin/env bash
# sync-pull.sh — Pull latest from sync backend (run at session-start)
#
# - Pulls latest from git remote (GitHub or NFS-backed git)
# - Re-links any new project memories that exist locally

set -euo pipefail

CLAUDE_DIR="$HOME/.claude"
SYNC_CONFIG="$CLAUDE_DIR/.sync-config"

[[ -f "$SYNC_CONFIG" ]] || exit 0
# shellcheck source=/dev/null
source "$SYNC_CONFIG"

[[ "${SYNC_BACKEND:-none}" == "none" ]] && exit 0
[[ -d "${SYNC_DIR:-}" ]] || exit 0

# ─── Pull ────────────────────────────────────────────────────────────────────

cd "$SYNC_DIR"

# Only pull from remote in GitHub mode — NFS is already live
if [[ "$SYNC_BACKEND" == "github" ]]; then
  git pull --rebase --autostash --quiet 2>/dev/null || {
    echo "sync-pull: git pull failed (offline?), using local cache" >&2
  }
fi

# ─── Re-link project memories ────────────────────────────────────────────────

"$(dirname "$0")/sync-link-projects.sh" 2>/dev/null || true

exit 0
