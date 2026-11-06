#!/usr/bin/env bash
# sync-health.sh — Detect dotfiles sync drift at session start
#
# Runs on SessionStart. Checks for the silent-fail conditions that broke
# sync from 2026-04-01 through 2026-04-29:
#   1. Sync directory exists but .sync-config is missing
#   2. .sync-config exists but synced paths aren't symlinks (replaced by real dirs)
#   3. .sync-config exists but $SYNC_DIR is unreachable
#   4. project memories sync-link-projects.sh could not move into the store
#
# Cases 1-3 emit a single-line warning to stderr (visible in transcript) and
# write a one-liner to ~/.claude/.sync-health.log so a human can grep history.
# Case 4 prints to stdout, which SessionStart adds to the session's context: it
# needs a hand merge, and the linker that found it runs in an async hook whose
# own output reaches nobody.

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

# Case 4: memory conflicts. sync-link-projects.sh rewrites this file on every
# complete run and removes it when nothing is left, so its presence means the
# conflict still stands. Until it is merged, that memory has no git history.
MEM_CONFLICTS="$CLAUDE_DIR/.sync-memory-conflicts"
if [[ -s "$MEM_CONFLICTS" ]]; then
  n=$(grep -c . "$MEM_CONFLICTS" 2>/dev/null || true)
  echo "[sync-health] ${n:-?} project memory conflict(s): this memory is not in the sync store, so it has no history, until merged by hand (full list: $MEM_CONFLICTS)"
  head -5 "$MEM_CONFLICTS" | sed 's/^/  - /'
  if [[ "${n:-0}" -gt 5 ]]; then echo "  - ... and $((n - 5)) more"; fi
fi

exit 0
