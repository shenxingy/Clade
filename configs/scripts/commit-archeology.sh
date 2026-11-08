#!/usr/bin/env bash
# commit-archeology.sh — Mine git history for recurring correction patterns.
#
# Universal capability: works on any git repo Claude Code is run in.
# Output:  ~/.claude/commit-lessons/<flat-cwd-slug>.jsonl (+ .head sidecar)
# Modes:
#   --scan        Refresh lessons.jsonl from current repo's git log.
#   --inject      Print cached patterns; refresh a missing/stale cache in the
#                 background. Age alone never rescans an unchanged HEAD.
#   --force       With --scan or --inject, ignore cache age and scan inline.
#
# Tunable env vars:
#   COMMIT_ARCH_WINDOW=60        scan window (days)
#   COMMIT_ARCH_CACHE_HOURS=24   refresh a moved HEAD only once cache is older
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
# Safe to run anywhere: no-ops outside git repos or on small repos; a first-run
# injection stays silent while its background scan populates the cache.

set -uo pipefail

# ─── Config ───────────────────────────────────────────────────────────
CLAUDE_DIR="${CLAUDE_DIR:-$HOME/.claude}"
LESSONS_DIR="$CLAUDE_DIR/commit-lessons"
WINDOW_DAYS="${COMMIT_ARCH_WINDOW:-60}"
CACHE_HOURS="${COMMIT_ARCH_CACHE_HOURS:-24}"
TOP_N="${COMMIT_ARCH_TOP_N:-4}"
MIN_OCCURRENCES="${COMMIT_ARCH_MIN:-3}"
# A refresh lock or reclaim mutex younger than this is never taken from its holder.
LOCK_GRACE_SECONDS=30

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
  local claude_shas file_rows file_lists csha files next_row
  local next_sha next_date next_msg
  local hits=0 last_sha="" last_msg="" last_date="" sha_list=""
  claude_shas=$(git log --since="${WINDOW_DAYS}.days.ago" \
                  --pretty=format:"%H%x09${_AGENT_TRAILER_FMT}" 2>/dev/null \
                | awk -F'\t' '$2 != "" || tolower($3) ~ /claude/ {print $1}')
  [[ -z "$claude_shas" ]] && return 0
  file_rows=$(printf '%s\n' "$claude_shas" | git diff-tree --name-only -r --stdin 2>/dev/null)
  file_lists=$(awk '
    NR == FNR { known[$0] = 1; next }
    $0 in known {
      if (current != "") print current "\t" files
      current = $0; files = ""; next
    }
    current != "" { files = (files == "") ? $0 : files " " $0 }
    END { if (current != "") print current "\t" files }
  ' <(printf '%s\n' "$claude_shas") <(printf '%s\n' "$file_rows"))
  while IFS=$'\t' read -r csha files; do
    [[ -z "$csha" || -z "$files" ]] && continue
    next_row=$(git log "${csha}..HEAD" \
                 --pretty=format:"%H%x09%ad%x09${_AGENT_TRAILER_FMT}%x09%s" \
                 --date=short -- $files 2>/dev/null | tail -1 \
               | awk -F'\t' '$3 == "" && tolower($4) !~ /claude/ {
                   msg = $5; for (i = 6; i <= NF; i++) msg = msg "\t" $i
                   printf "%s\t%s\t%s", $1, $2, msg
                 }')
    [[ -z "$next_row" ]] && continue
    IFS=$'\t' read -r next_sha next_date next_msg <<< "$next_row"
    hits=$((hits+1))
    sha_list+="${csha:0:7},"
    last_sha="${next_sha:0:7}"
    last_msg="$next_msg"
    last_date="$next_date"
  done <<< "$file_lists"
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

# Detector: share of agent-authored commits that add/touch a test file
# (Agent-Fingerprint 2026-06-18: test inclusion = quality + merge-rate signal,
# the mirror of the fix-rate split). Count column = agent commits in the window.
detect_agent_test_inclusion() {
  git log --since="${WINDOW_DAYS}.days.ago" \
      --pretty=format:"@@C@@%x09%h%x09%ad%x09%s%x09${_AGENT_TRAILER_FMT}" \
      --name-only --date=short 2>/dev/null \
    | awk -F'\t' -v min="$MIN_OCCURRENCES" '
        /^@@C@@\t/ {
          if (seen) { a += in_agent; at += (in_agent && had_test) }
          seen = 1
          in_agent = ($5 != "" || tolower($6) ~ /claude/) ? 1 : 0
          had_test = 0
          if (in_agent) { lsha = $2; ldate = $3 }
          next
        }
        in_agent && ($0 ~ /(^|\/)(test_[^\/]+\.py|[^\/]+_test\.(py|go)|[^\/]+\.(test|spec)\.[jt]sx?)$/ \
                     || $0 ~ /(^|\/)(tests?|__tests__|spec)\//) { had_test = 1 }
        END {
          if (seen) { a += in_agent; at += (in_agent && had_test) }
          if (a < min) exit
          rate = int(at * 100 / a)
          msg = sprintf("agent test-inclusion %d%% (%d/%d agent commits add/touch a test)", rate, at, a)
          printf "agent-test-inclusion\t%d\t%s\t%s\t%s\t%s\n", a, lsha, msg, ldate, ""
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
  local total head_sha
  total=$(git log --since="${WINDOW_DAYS}.days.ago" --oneline 2>/dev/null | wc -l | tr -d ' ')
  [[ "${total:-0}" -lt 5 ]] && return 0  # not enough history
  head_sha=$(git rev-parse HEAD 2>/dev/null)

  local rows
  rows=$( (
    detect_fix_keyword "wiring-gap"   'wire|hook up|not registered|not called|not wired'
    detect_fix_keyword "deploy-gap"   'install\.sh|fix\(install\)|missing from|not deployed|tracks/'
    detect_fix_keyword "compat-gap"   'macos|bash 3|cross-plat|compat|fallback'
    detect_fix_keyword "disambiguate" 'disambiguate|collision|name clash|built-in'
    detect_claude_overridden
    detect_agent_segmentation
    detect_agent_test_inclusion
    detect_mass_fix_spree
  ) 2>/dev/null )

  local cwd lessons_file now tmp head_tmp
  cwd="$(pwd)"
  lessons_file="$(lessons_path)"
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  tmp="$lessons_file.tmp.$$"
  head_tmp="$lessons_file.head.tmp.$$"

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

  mv "$tmp" "$lessons_file"
  printf '%s\n' "$head_sha" > "$head_tmp"
  mv "$head_tmp" "$lessons_file.head"
}

# ─── Background refresh ───────────────────────────────────────────────
# lock_is_young <path> — true while <path> was written within LOCK_GRACE_SECONDS.
# An unreadable mtime counts as young: a lock is left alone rather than stolen.
lock_is_young() {
  local mtime
  if mtime=$(stat -c %Y "$1" 2>/dev/null); then :
  elif mtime=$(stat -f %m "$1" 2>/dev/null); then :
  else return 0
  fi
  [[ "$(( $(date +%s) - mtime ))" -lt "$LOCK_GRACE_SECONDS" ]]
}

# take_lock <dir> — create <dir> holding a pid file with our PID. Of any number
# of concurrent callers exactly one succeeds, because the pid file is created
# O_EXCL (bash noclobber). mkdir alone does not decide it: uutils mkdir before
# 0.11.0, the default mkdir on Ubuntu 26.04 (0.10.0), reports success to a racer
# whose mkdir(2) failed with EEXIST (uutils #13970) - 39 of 300 four-way races
# on a hosted runner had two winners, and two sessions each launched a scan.
take_lock() {
  mkdir "$1" 2>/dev/null && ( set -C; printf '%s\n' "$$" > "$1/pid" ) 2>/dev/null
}

# drop_lock <dir> — remove a lock taken with take_lock.
drop_lock() {
  rm -f "$1/pid"
  rmdir "$1" 2>/dev/null
}

start_refresh() {
  local script_dir runtime_lib state lock pid
  local reclaim current_pid
  script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)
  runtime_lib="$script_dir/../hooks/lib/runtime-dir.sh"
  # shellcheck source=/dev/null
  . "$runtime_lib" 2>/dev/null || return 0
  state=$(clade_state_dir commit-archeology 2>/dev/null) || return 0
  lock="$state/$(slug "$(pwd)").lock"

  if ! take_lock "$lock"; then
    pid=$(head -1 "$lock/pid" 2>/dev/null)
    [[ "$pid" =~ ^[0-9]+$ ]] || return 0
    # Until the refresher has started and recorded its own PID, the lock names a
    # process that has already exited: the caller that spawned it, which returns
    # at once. A dead PID is therefore no evidence of an abandoned lock until the
    # lock is older than any startup. #212 recorded $! instead, which names the
    # refresher only if setsid does not fork (util-linux setsid forks when its
    # caller leads a process group, as a job under job control does).
    lock_is_young "$lock/pid" && return 0
    kill -0 "$pid" 2>/dev/null && return 0

    reclaim="$lock.reclaim"
    if ! take_lock "$reclaim"; then
      lock_is_young "$reclaim" && return 0
      drop_lock "$reclaim" || return 0
      take_lock "$reclaim" || return 0
    fi
    current_pid=$(head -1 "$lock/pid" 2>/dev/null)
    if [[ "$current_pid" != "$pid" ]] || kill -0 "$current_pid" 2>/dev/null; then
      drop_lock "$reclaim"
      return 0
    fi
    rm -f "$lock/pid"
    rmdir "$lock" 2>/dev/null
    if ! take_lock "$lock"; then
      drop_lock "$reclaim"
      return 0
    fi
    drop_lock "$reclaim"
  fi

  if command -v setsid >/dev/null 2>&1; then
    setsid bash "$script_dir/$(basename "${BASH_SOURCE[0]}")" --refresh "$lock" \
      </dev/null >/dev/null 2>&1 &
  else
    nohup bash "$script_dir/$(basename "${BASH_SOURCE[0]}")" --refresh "$lock" \
      </dev/null >/dev/null 2>&1 &
  fi
  # Our PID stays in the lock until the refresher records its own; the grace
  # period above, not the PID, protects that hand-off.
  disown %% 2>/dev/null || true
}

run_refresh() {
  REFRESH_LOCK_DIR="${1:-}"
  [[ -n "$REFRESH_LOCK_DIR" && -d "$REFRESH_LOCK_DIR" ]] || return 0
  trap 'rm -f "$REFRESH_LOCK_DIR/pid"; rmdir "$REFRESH_LOCK_DIR" 2>/dev/null' EXIT
  printf '%s\n' "$$" > "$REFRESH_LOCK_DIR/pid"
  # A caller that judged the cache stale just before another refresh finished and
  # released the lock arrives here with nothing left to do.
  [[ "$(head -1 "$(lessons_path).head" 2>/dev/null)" == "$(git rev-parse HEAD 2>/dev/null)" ]] && return 0
  scan
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
      if [[ "$force" -eq 1 ]]; then
        scan
        inject
      else
        local age current_head cached_head
        age=$(cache_age_hours "$lessons_file")
        if [[ -f "$lessons_file" && "$age" -le "$CACHE_HOURS" ]]; then
          inject
        else
          current_head=$(git rev-parse HEAD 2>/dev/null)
          cached_head=$(head -1 "$lessons_file.head" 2>/dev/null)
          inject
          if [[ "$cached_head" != "$current_head" ]]; then
            start_refresh
          fi
        fi
      fi
      ;;
    --refresh)
      run_refresh "${2:-}"
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
