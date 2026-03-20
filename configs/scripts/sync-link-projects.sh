#!/usr/bin/env bash
# sync-link-projects.sh — Link project memory from sync dir to ~/.claude/projects/
#
# Scans sync repo's projects-memory/ for known projects.
# For each project name found locally, creates the correct symlink
# under ~/.claude/projects/<encoded-path>/memory.
#
# Safe to re-run: uses -sfn (force, no-dereference).

set -euo pipefail

CLAUDE_DIR="$HOME/.claude"
SYNC_CONFIG="$CLAUDE_DIR/.sync-config"

[[ -f "$SYNC_CONFIG" ]] || exit 0
# shellcheck source=/dev/null
source "$SYNC_CONFIG"

PROJECTS_MEMORY_DIR="$SYNC_DIR/projects-memory"
[[ -d "$PROJECTS_MEMORY_DIR" ]] || exit 0

# ─── Path encoder (mirrors Claude Code's encoding) ───────────────────────────

encode_path() {
  # Claude encodes absolute path: /home/user/projects/foo → -home-user-projects-foo
  echo "$1" | sed 's|^/||; s|/|-|g'
}

# ─── Search roots for project directories ────────────────────────────────────

SEARCH_ROOTS=(
  "$HOME/projects"
  "$HOME/code"
  "$HOME/src"
  "$HOME/work"
  "$HOME"
)

find_project_path() {
  local proj_name="$1"
  for root in "${SEARCH_ROOTS[@]}"; do
    [[ -d "$root" ]] || continue
    local found
    found=$(find "$root" -maxdepth 3 -name "$proj_name" -type d 2>/dev/null | head -1)
    [[ -n "$found" ]] && echo "$found" && return 0
  done
  return 1
}

# ─── Link each project ───────────────────────────────────────────────────────

linked=0
skipped=0

for proj_dir in "$PROJECTS_MEMORY_DIR"/*/; do
  [[ -d "$proj_dir" ]] || continue
  proj_name=$(basename "$proj_dir")

  local_path=$(find_project_path "$proj_name") || { ((skipped++)); continue; }

  encoded=$(encode_path "$local_path")
  target_dir="$CLAUDE_DIR/projects/$encoded"
  mkdir -p "$target_dir"

  # Only symlink if not already pointing to the right place
  existing_link="$target_dir/memory"
  if [[ -L "$existing_link" && "$(readlink "$existing_link")" == "$proj_dir" ]]; then
    ((skipped++))
    continue
  fi

  ln -sfn "$proj_dir" "$existing_link"
  echo "  Linked $proj_name → $local_path"
  ((linked++))
done

[[ $linked -gt 0 ]] && echo "  $linked project(s) linked, $skipped skipped"

exit 0
