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


# ─── Usage pace ───

usage_segment=""
_usage_script="$HOME/.claude/scripts/claude-usage-watch.py"
if command -v python3 >/dev/null 2>&1 && [ -f "$_usage_script" ]; then
  usage_segment=" $(python3 "$_usage_script" 2>/dev/null)"
fi

# ─── Build output ───

output=""

# Directory (cyan)
output+="\033[36m${dir_name}\033[0m"

# Git branch (blue prefix, red branch name)
if [ -n "$git_branch" ]; then
  output+=" \033[1;34mgit:(\033[0;31m${git_branch}\033[1;34m)\033[0m"
fi

# Usage pace: +3% (4.4d)
output+="${usage_segment}"

printf "%b" "$output"
