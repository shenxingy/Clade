#!/usr/bin/env bash
# Claude Code status line — styled after robbyrussell oh-my-zsh theme

input=$(cat)

cwd=$(echo "$input" | jq -r '.cwd // .workspace.current_dir // ""')

# ─── Directory ───

dir_name=$(basename "$cwd")

# ─── Git branch (skip optional locks to avoid contention) ───

git_branch=""
if [ -n "$cwd" ] && git -C "$cwd" rev-parse --git-dir >/dev/null 2>&1; then
  git_branch=$(git -C "$cwd" -c gc.auto=0 symbolic-ref --short HEAD 2>/dev/null \
               || git -C "$cwd" -c gc.auto=0 rev-parse --short HEAD 2>/dev/null)
fi

# ─── Loop status ───

loop_segment=""
loop_state_file="${cwd}/.claude/loop-state"
if [ -f "$loop_state_file" ]; then
  loop_converged=$(grep "^CONVERGED=" "$loop_state_file" 2>/dev/null | cut -d= -f2)
  loop_interrupted=$(grep "^INTERRUPTED=" "$loop_state_file" 2>/dev/null | cut -d= -f2)
  loop_iter=$(grep "^ITERATION=" "$loop_state_file" 2>/dev/null | cut -d= -f2)
  if [ "$loop_interrupted" = "true" ]; then
    loop_segment=" \033[1;31m✗ loop stopped\033[0m"
  elif [ "$loop_converged" = "true" ]; then
    loop_segment=" \033[1;32m✓ loop done\033[0m"
  elif [ -n "$loop_iter" ]; then
    loop_segment=" \033[1;33m⟳ loop iter ${loop_iter}\033[0m"
  fi
fi

# ─── Build output ───

output=""

# Directory (cyan)
output+="\033[36m${dir_name}\033[0m"

# Git branch (blue prefix, red branch name)
if [ -n "$git_branch" ]; then
  output+=" \033[1;34mgit:(\033[0;31m${git_branch}\033[1;34m)\033[0m"
fi

# Loop status
output+="${loop_segment}"

printf "%b" "$output"
