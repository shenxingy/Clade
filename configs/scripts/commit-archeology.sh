#!/usr/bin/env bash
# commit-archeology.sh — Mine git history for recurring correction patterns.
#
# Universal capability: works on any git repo Claude Code is run in.
# Output:  ~/.claude/commit-lessons/<flat-cwd-slug>.jsonl
# Modes:
#   --scan        Refresh lessons.jsonl from current repo's git log.
#   --inject      Print formatted top patterns to stdout (for hook injection).
#                 Auto-runs --scan if cache older than COMMIT_ARCH_CACHE_HOURS.
#   --force       With --scan or --inject, ignore cache age.
#
# Tunable env vars:
#   COMMIT_ARCH_WINDOW=60        scan window (days)
#   COMMIT_ARCH_CACHE_HOURS=24   skip rescan if jsonl newer than this
#   COMMIT_ARCH_TOP_N=4          how many patterns to inject
#   COMMIT_ARCH_MIN=3            minimum occurrences to register a pattern
#
# Detectors:
#   wiring-gap       fix commits with "wire / hook up / not registered / not called"
#   deploy-gap       fix commits with "install.sh / missing from / not deployed"
#   compat-gap       fix commits with "macOS / bash 3 / cross-plat / compat / fallback"
#   disambiguate     commits with "disambiguate / collision / name clash / built-in"
#   claude-overridden     Claude-authored commits whose files later get a non-Claude fix
#   agent-author-share    agent vs human commit share + fix-rate split
#                         (agent = X-Clade-Task or Co-Authored-By: Claude trailer)
#   mass-fix-day-YYYY-MM-DD  any single day with ≥10 fix(*) commits
#
# Safe to run anywhere: no-ops outside git repos, on small repos, or first-run.

set -uo pipefail

# ─── Config ───────────────────────────────────────────────────────────
CLAUDE_DIR="${CLAUDE_DIR:-$HOME/.claude}"
LESSONS_DIR="$CLAUDE_DIR/commit-lessons"
WINDOW_DAYS="${COMMIT_ARCH_WINDOW:-60}"
CACHE_HOURS="${COMMIT_ARCH_CACHE_HOURS:-24}"
TOP_N="${COMMIT_ARCH_TOP_N:-4}"
MIN_OCCURRENCES="${COMMIT_ARCH_MIN:-3}"

mkdir -p "$LESSONS_DIR" 2>/dev/null

# ─── Utils ────────────────────────────────────────────────────────────
slug() { printf '%s' "$1" | sed 's|/|-|g'; }
is_git_repo() { git rev-parse --is-inside-work-tree &>/dev/null; }

cache_age_hours() {
  local f="$1" mtime now
  [[ -f "$f" ]] || { echo 9999; return; }
  if mtime=$(stat -c %Y "$f" 2>/dev/null); then :
  elif mtime=$(stat -f %m "$f" 2>/dev/null); then :
  else echo 9999; return
  fi
  now=$(date +%s)
  echo $(( (now - mtime) / 3600 ))
}

lessons_path() {
  printf '%s/%s.jsonl' "$LESSONS_DIR" "$(slug "$(pwd)")"
}

# ─── Detectors ────────────────────────────────────────────────────────
# Each detector emits TAB-separated rows:
#   pattern \t count \t last_sha \t last_msg \t last_date \t sha_list_csv

# Helper: keyword-class on fix commits
detect_fix_keyword() {
  local label="$1" regex="$2"
  local rows count first_line last_sha last_date last_msg sha_list
  rows=$(git log --since="${WINDOW_DAYS}.days.ago" \
                 --pretty=format:'%h%x09%ad%x09%s' --date=short 2>/dev/null \
          | grep -iE $'^[a-f0-9]+\t[0-9-]+\t(fix|chore.*fix)' \
          | grep -iE "$regex")
  count=$(printf '%s\n' "$rows" | grep -c . 2>/dev/null)
  count=${count:-0}
  [[ "$count" -lt "$MIN_OCCURRENCES" ]] && return 0
  first_line=$(printf '%s\n' "$rows" | head -1)
  IFS=$'\t' read -r last_sha last_date last_msg <<< "$first_line"
  sha_list=$(printf '%s\n' "$rows" | awk -F'\t' '{print $1}' | head -10 | paste -sd, -)
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$label" "$count" "$last_sha" "$last_msg" "$last_date" "$sha_list"
}

# Agent-authorship test shared by detectors below: a commit is agent-authored
# when it carries an X-Clade-Task trailer (committer.sh adds it whenever
# CLADE_WORKER_TASK_ID is set) or a Co-Authored-By: Claude trailer.
_AGENT_TRAILER_FMT='%(trailers:key=X-Clade-Task,valueonly,separator=;)%x09%(trailers:key=Co-Authored-By,valueonly,separator=;)'

# Detector: Claude-authored commit whose files later get a non-Claude fix
detect_claude_overridden() {
  local claude_shas hits=0 last_sha="" last_msg="" last_date="" sha_list=""
  claude_shas=$(git log --since="${WINDOW_DAYS}.days.ago" \
                  --pretty=format:"%H%x09${_AGENT_TRAILER_FMT}" 2>/dev/null \
                | awk -F'\t' '$2 != "" || tolower($3) ~ /claude/ {print $1}')
  [[ -z "$claude_shas" ]] && return 0
  while IFS= read -r csha; do
    [[ -z "$csha" ]] && continue
    local files next_sha next_is_agent
    files=$(git diff-tree --no-commit-id --name-only -r "$csha" 2>/dev/null)
    [[ -z "$files" ]] && continue
    # next commit on those files (oldest in csha..HEAD range)
    next_sha=$(git log "${csha}..HEAD" --pretty=format:'%H' -- $files 2>/dev/null | tail -1)
    [[ -z "$next_sha" ]] && continue
    next_is_agent=$(git log -1 --pretty=format:"${_AGENT_TRAILER_FMT}" "$next_sha" 2>/dev/null \
                    | awk -F'\t' '{ print ($1 != "" || tolower($2) ~ /claude/) ? "yes" : "no" }')
    if [[ "$next_is_agent" != "yes" ]]; then
      hits=$((hits+1))
      sha_list+="${csha:0:7},"
      last_sha="${next_sha:0:7}"
      last_msg=$(git log -1 --pretty=format:'%s' "$next_sha")
      last_date=$(git log -1 --pretty=format:'%ad' --date=short "$next_sha")
    fi
  done <<< "$claude_shas"
  [[ "$hits" -lt "$MIN_OCCURRENCES" ]] && return 0
  printf 'claude-overridden\t%s\t%s\t%s\t%s\t%s\n' "$hits" "$last_sha" "$last_msg" "$last_date" "${sha_list%,}"
}

# Detector: agent-vs-human segmentation by attribution trailer. Emits one
# row whose message column carries the fix-rate split per author class —
# the revert/fix-rate-by-author signal /audit consumes. Count column =
# number of agent-authored commits in the window.
detect_agent_segmentation() {
  git log --since="${WINDOW_DAYS}.days.ago" \
      --pretty=format:"%h%x09%ad%x09%s%x09${_AGENT_TRAILER_FMT}" \
      --date=short 2>/dev/null \
    | awk -F'\t' -v min="$MIN_OCCURRENCES" '{
        agent = ($4 != "" || tolower($5) ~ /claude/)
        fix = ($3 ~ /^fix/)
        if (agent) {
          a++; if (fix) af++
          if (a == 1) { lsha = $1; ldate = $2 }
          if (a <= 10) shas = shas $1 ","
        } else { h++; if (fix) hf++ }
      } END {
        if (a < min) exit
        arate = int(af * 100 / a)
        hrate = (h > 0) ? int(hf * 100 / h) : 0
        msg = sprintf("agent fix-rate %d%% (%d/%d) vs human %d%% (%d/%d)", arate, af, a, hrate, hf, h)
        sub(/,$/, "", shas)
        printf "agent-author-share\t%d\t%s\t%s\t%s\t%s\n", a, lsha, msg, ldate, shas
      }'
}

# Detector: any day with ≥10 fix commits → noisy initial pass
detect_mass_fix_spree() {
  git log --since="${WINDOW_DAYS}.days.ago" --pretty=format:'%h%x09%ad%x09%s' --date=short 2>/dev/null \
    | awk -F'\t' '$3 ~ /^fix/ {
        c[$2]++; lsha[$2]=$1; lmsg[$2]=$3
      } END {
        for (d in c) if (c[d] >= 10)
          printf "mass-fix-day-%s\t%d\t%s\t%s\t%s\t%s\n", d, c[d], lsha[d], lmsg[d], d, lsha[d]
      }'
}

# ─── Scan ─────────────────────────────────────────────────────────────
scan() {
  is_git_repo || return 0
  local total
  total=$(git log --since="${WINDOW_DAYS}.days.ago" --oneline 2>/dev/null | wc -l | tr -d ' ')
  [[ "${total:-0}" -lt 5 ]] && return 0  # not enough history

  local rows
  rows=$( (
    detect_fix_keyword "wiring-gap"   'wire|hook up|not registered|not called|not wired'
    detect_fix_keyword "deploy-gap"   'install\.sh|fix\(install\)|missing from|not deployed|tracks/'
    detect_fix_keyword "compat-gap"   'macos|bash 3|cross-plat|compat|fallback'
    detect_fix_keyword "disambiguate" 'disambiguate|collision|name clash|built-in'
    detect_claude_overridden
    detect_agent_segmentation
    detect_mass_fix_spree
  ) 2>/dev/null )

  [[ -z "$rows" ]] && return 0

  local cwd lessons_file now tmp
  cwd="$(pwd)"
  lessons_file="$(lessons_path)"
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  tmp="$lessons_file.tmp.$$"

  : > "$tmp"
  while IFS=$'\t' read -r pattern count last_sha last_msg last_date sha_list; do
    [[ -z "$pattern" ]] && continue
    if command -v jq &>/dev/null; then
      jq -nc \
        --arg ts "$now" \
        --arg project "$cwd" \
        --arg pattern "$pattern" \
        --argjson count "${count:-0}" \
        --arg last_sha "$last_sha" \
        --arg last_msg "$last_msg" \
        --arg last_date "$last_date" \
        --arg sha_list "$sha_list" \
        '{ts:$ts,project:$project,pattern:$pattern,count:$count,last_sha:$last_sha,last_msg:$last_msg,last_date:$last_date,sha_list:$sha_list}' \
        >> "$tmp"
    else
      # crude fallback: escape backslash and double-quote in last_msg
      local lm="${last_msg//\\/\\\\}"
      lm="${lm//\"/\\\"}"
      printf '{"ts":"%s","project":"%s","pattern":"%s","count":%s,"last_sha":"%s","last_msg":"%s","last_date":"%s","sha_list":"%s"}\n' \
        "$now" "$cwd" "$pattern" "$count" "$last_sha" "$lm" "$last_date" "$sha_list" \
        >> "$tmp"
    fi
  done <<< "$rows"

  if [[ -s "$tmp" ]]; then
    mv "$tmp" "$lessons_file"
  else
    rm -f "$tmp"
  fi
}

# ─── Inject ───────────────────────────────────────────────────────────
inject() {
  local lessons_file
  lessons_file="$(lessons_path)"
  [[ -s "$lessons_file" ]] || return 0

  echo "## 🧠 Commit Lessons (this repo, last ${WINDOW_DAYS}d)"
  if command -v jq &>/dev/null; then
    jq -rs --argjson n "$TOP_N" '
      sort_by(-.count) | .[:$n] | .[] |
      "- \(.count)× \(.pattern) (last \(.last_sha) on \(.last_date)) → \(.last_msg | .[0:70])"
    ' "$lessons_file" 2>/dev/null
  elif command -v python3 &>/dev/null; then
    python3 - "$lessons_file" "$TOP_N" <<'PY' 2>/dev/null
import json, sys
path, n = sys.argv[1], int(sys.argv[2])
rows = []
with open(path) as f:
    for line in f:
        try: rows.append(json.loads(line))
        except: pass
rows.sort(key=lambda r: -int(r.get("count", 0)))
for r in rows[:n]:
    msg = r.get("last_msg", "")[:70]
    print(f"- {r.get('count')}× {r.get('pattern')} (last {r.get('last_sha')} on {r.get('last_date')}) → {msg}")
PY
  else
    head -"$TOP_N" "$lessons_file"
  fi
}

# ─── Main ─────────────────────────────────────────────────────────────
main() {
  local mode="${1:-}" force=0
  for arg in "$@"; do [[ "$arg" == "--force" ]] && force=1; done

  cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" 2>/dev/null || exit 0
  is_git_repo || exit 0

  local lessons_file
  lessons_file="$(lessons_path)"

  case "$mode" in
    --scan|"")
      scan
      ;;
    --inject)
      local age
      age=$(cache_age_hours "$lessons_file")
      if [[ "$force" -eq 1 || "$age" -gt "$CACHE_HOURS" ]]; then
        scan
      fi
      inject
      ;;
    --force)
      scan
      inject
      ;;
    *)
      echo "Usage: $0 --scan | --inject [--force]" >&2
      exit 2
      ;;
  esac
}

main "$@"
