#!/usr/bin/env bash
# Claude Code status line — styled after robbyrussell oh-my-zsh theme, and fitted
# to the pane: project, branch, task state, usage pace, then drop-in segments.

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

ESC=$(printf '\033')
plain() { printf '%s' "$1" | sed "s/${ESC}\[[0-9;]*m//g"; }   # ANSI colours stripped

# ─── Usage pace ───

usage_segment=""
_usage_script="$HOME/.claude/scripts/claude-usage-watch.py"
if command -v python3 >/dev/null 2>&1 && [ -f "$_usage_script" ]; then
  usage_segment=$(printf '%s' "$input" \
    | python3 "$_usage_script" --statusline-input 2>/dev/null)
fi

# ─── Task time: run / wait / idle, and how long ───
# Inline, not a drop-in: drop-in segments get no stdin, and this one needs the
# transcript_path in $input. task-eta.py fails soft (prints nothing, exits 0);
# no python3, a missing script or `slt eta off` drop the segment, nothing else.
# --forms prints the segment three times, longest first, for the fit below.
eta_full="" eta_short="" eta_min=""
_eta_script="$HOME/.claude/scripts/task-eta.py"
if [ "$(cat "$HOME/.claude/.statusline-eta" 2>/dev/null)" != "off" ] \
   && command -v python3 >/dev/null 2>&1 && [ -f "$_eta_script" ]; then
  _eta=$(printf '%s' "$input" | python3 "$_eta_script" --stdin --forms 2>/dev/null)
  _eta=${_eta//\\/}                     # printf %b below must not read an escape in it
  { IFS= read -r eta_full; IFS= read -r eta_short; IFS= read -r eta_min; } <<EOF
$_eta
EOF
  [ -n "$eta_short" ] || eta_short=$eta_full
  [ -n "$eta_min" ] || eta_min=$eta_short
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
    seg=${seg//\\/}
    [ -n "$seg" ] && extra_segment+="${extra_segment:+ }${seg}"
  done
fi

# ─── Fit to the pane ───
# Claude Code indents the line two columns, keeps two free on the right and cuts
# the rest with "…" (seen 2026-11-20 on tmux splits 29, 35, 46 and 94 wide): a
# 29-column split showed "faceswap-platform-100 gi…" and never the task. It sets
# COLUMNS to the pane's width for this command, so shorten or drop the least
# useful piece first until the line fits. No COLUMNS (an older Claude Code, a
# hand run): print everything, as before.

dir=$dir_name branch=$git_branch eta=$eta_full usage=$usage_segment extra=$extra_segment
usage_plain=$(plain "$usage") extra_plain=$(plain "$extra")

cut_to() {  # cut_to TEXT N — at most N characters, the last one "…" when cut
  if [ "${#1}" -le "$2" ]; then printf '%s' "$1"; else printf '%s…' "${1:0:$(($2 - 1))}"; fi
}

width() {
  local w=0 p
  for p in "$dir" "$branch" "$eta" "$usage_plain" "$extra_plain"; do
    [ -n "$p" ] && w=$((w + ${#p} + 1))
  done
  echo $((w > 0 ? w - 1 : 0))
}

budget=""
case "${COLUMNS:-}" in ''|*[!0-9]*) ;; *) budget=$((COLUMNS - 4)) ;; esac

if [ -n "$budget" ]; then
  for step in extra usage_time branch_cut eta_short dir_cut branch usage eta_min; do
    [ "$(width)" -le "$budget" ] && break
    case $step in
      extra)      extra="" extra_plain="" ;;
      usage_time) usage=${usage% (*} usage_plain=${usage_plain% (*} ;;   # "-10% (1.9d)" -> "-10%"
      branch_cut) branch=$(cut_to "$branch" 12) ;;
      eta_short)  eta=$eta_short ;;
      dir_cut)    dir=$(cut_to "$dir" 14) ;;
      branch)     branch="" ;;
      usage)      usage="" usage_plain="" ;;
      eta_min)    eta=$eta_min ;;
    esac
  done
  # A later step can free the room an earlier drop needed: put back what now fits.
  if [ -z "$usage" ] && [ -n "$usage_segment" ]; then
    usage=${usage_segment% (*} usage_plain=$(plain "$usage_segment") usage_plain=${usage_plain% (*}
    [ "$(width)" -le "$budget" ] || usage="" usage_plain=""
  fi
  if [ -z "$branch" ] && [ -n "$git_branch" ]; then
    branch=$(cut_to "$git_branch" 12)
    [ "$(width)" -le "$budget" ] || branch=""
  fi
fi

# ─── Build output ───

output=""
output+="\033[36m${dir}\033[0m"                                   # directory (cyan)
[ -n "$branch" ] && output+=" \033[0;31m${branch}\033[0m"          # branch (red), no "git:(…)" label
[ -n "$eta" ] && output+=" \033[2m${eta}\033[0m"                   # task state (dim): run 3m · 6-20m left
[ -n "$usage" ] && output+=" ${usage}"                             # usage pace: -10% (1.9d)
[ -n "$extra" ] && output+=" ${extra}"                             # drop-in segments

printf "%b" "$output"
