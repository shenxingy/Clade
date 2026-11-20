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
  usage_segment=" $(printf '%s' "$input" \
    | python3 "$_usage_script" --statusline-input 2>/dev/null)"
fi

# ─── Task time: elapsed since the latest prompt, and a range for what is left ───
# Inline, not a drop-in: drop-in segments get no stdin, and this one needs the
# transcript_path in $input. task-eta.py fails soft (prints nothing, exits 0);
# no python3, a missing script or `slt eta off` drop the segment, nothing else.
eta_segment=""
_eta_script="$HOME/.claude/scripts/task-eta.py"
if [ "$(cat "$HOME/.claude/.statusline-eta" 2>/dev/null)" != "off" ] \
   && command -v python3 >/dev/null 2>&1 && [ -f "$_eta_script" ]; then
  _eta=$(printf '%s' "$input" | python3 "$_eta_script" --stdin 2>/dev/null)
  _eta=${_eta//\\/}                     # printf %b below must not read an escape in it
  [ -n "$_eta" ] && eta_segment=" \033[2m${_eta}\033[0m"
fi

# ─── Extra segments (drop-in scripts) ───
# Other tools (e.g. amsg) that want a statusLine segment install an
# executable here instead of overwriting settings.json's statusLine.command
# wholesale, which would silently hide this script's output (dir/git/usage).
extra_segment=""
extra_dir="$HOME/.claude/statusline-extra.d"
if [ -d "$extra_dir" ]; then
  for f in "$extra_dir"/*; do
    [ -x "$f" ] || continue
    seg=$("$f" 2>/dev/null)
    [ -n "$seg" ] && extra_segment+=" ${seg}"
  done
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

# Task time (dim): task 20m · idle | bg workflow 20m · 11m-2.2h left
output+="${eta_segment}"

# Extra (drop-in) segments
output+="${extra_segment}"

printf "%b" "$output"
