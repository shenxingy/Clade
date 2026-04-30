#!/usr/bin/env bash
# sync-health.sh — Detect dotfiles sync drift at session start
#
# Runs on SessionStart. Checks for the silent-fail conditions that broke
# sync from 2026-04-01 through 2026-04-29:
#   1. Sync directory exists but .sync-config is missing
#   2. .sync-config exists but synced paths aren't symlinks (replaced by real dirs)
#   3. .sync-config exists but $SYNC_DIR is unreachable
#
# Emits a single-line warning to stderr (visible in transcript) and writes
# a one-liner to ~/.claude/.sync-health.log so a human can grep history.

set -euo pipefail

CLAUDE_DIR="$HOME/.claude"
SYNC_CONFIG="$CLAUDE_DIR/.sync-config"
LOG="$CLAUDE_DIR/.sync-health.log"
SYNCED=(skills hooks scripts corrections memory)

warn() {
  local msg="$1"
  echo "[sync-health] $msg" >&2
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $msg" >> "$LOG"
}

# Case 1: sync was set up on this host previously (heuristic: NFS dir or
# log file exists) but config file is gone.
if [[ ! -f "$SYNC_CONFIG" ]]; then
  if [[ -d "$HOME/shared-nfs/claude-dotfiles/.git" ]] || \
     [[ -d "$HOME/claude-dotfiles/.git" ]] || \
     [[ -f "$LOG" ]]; then
    warn "Sync repo found but ~/.claude/.sync-config is missing — pushes are silently no-op. Run sync-setup.sh to recover."
  fi
  exit 0
fi

# shellcheck source=/dev/null
source "$SYNC_CONFIG"

# Case 2: config present, but synced paths are real dirs (symlinks broken).
broken=()
for d in "${SYNCED[@]}"; do
  path="$CLAUDE_DIR/$d"
  [[ -e "$path" ]] || continue
  if [[ ! -L "$path" ]]; then
    broken+=("$d")
  fi
done
if [[ "${#broken[@]}" -gt 0 ]]; then
  warn "Sync configured but real-dir replacing symlink: ${broken[*]} — writes won't reach $SYNC_DIR. Re-run sync-setup.sh."
fi

# Case 3: SYNC_DIR unreachable (NFS mount dropped, repo deleted, etc).
if [[ -n "${SYNC_DIR:-}" ]] && [[ ! -d "$SYNC_DIR" ]]; then
  warn "Sync configured to $SYNC_DIR but path doesn't exist — pushes will fail."
fi

exit 0
