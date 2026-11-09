#!/usr/bin/env bash
# sync-health.sh — Detect dotfiles sync drift at session start
# exists-for: dotfiles sync failed silently from 2026-04-01 to 2026-04-29 (added 2026-04-29 in 4fe2624) · retire-when: the sync store is retired (no ~/.claude/.sync-config on any machine)
#
# Runs on SessionStart. Checks for the silent-fail conditions that broke
# sync from 2026-04-01 through 2026-04-29:
#   1. Sync directory exists but .sync-config is missing
#   2. .sync-config exists but synced paths aren't symlinks (replaced by real dirs)
#   3. .sync-config exists but $SYNC_DIR is unreachable
#   4. project memories sync-link-projects.sh could not move into the store
#   5. unmerged paths in the store's index
#   6. a leftover pull --autostash stash entry
#   7. this host's last sync commit is stale, or it has never committed changes
#   8. a trailing streak of sync-push REFUSED lines
#   9. commits behind the fetched upstream, or stale unpushed commits ahead
#  10. MEMORY.md files approaching Claude Code's native index cap
#  11. sync-push's per-host backoff: paused pushes, probe expiry or bad state
#
# Cases 1-3 emit a single-line warning to stderr (visible in transcript) and
# write a one-liner to ~/.claude/.sync-health.log so a human can grep history.
# Case 4 prints to stdout, which SessionStart adds to the session's context: it
# needs a hand merge, and the linker that found it runs in an async hook whose
# own output reaches nobody. Cases 5-11 also print one line per finding to
# stdout and append that finding to the health log when sync is configured.
# Case 10 is stdout-only without a config so it cannot arm Case 1's heuristic;
# Case 11's pre-existing backoff file already establishes prior sync setup.

set -euo pipefail

HOOK_LIBDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib"
# shellcheck source=/dev/null
source "$HOOK_LIBDIR/sync-push-backoff.sh" 2>/dev/null || true

_sync_epoch_local() {
  python3 -c 'from datetime import datetime; import sys; print(datetime.fromtimestamp(int(sys.argv[1])).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"))' \
    "$1" 2>/dev/null ||
    date -r "$1" '+%Y-%m-%d %H:%M:%S %Z' 2>/dev/null ||
    printf 'epoch %s\n' "$1"
}

CLAUDE_DIR="$HOME/.claude"
SYNC_CONFIG="$CLAUDE_DIR/.sync-config"
LOG="$CLAUDE_DIR/.sync-health.log"
CONFLICT_LOG="$CLAUDE_DIR/.sync-conflicts.log"
SYNCED=(skills hooks scripts corrections memory)
HOOK_BUDGET="${CLADE_SYNC_HEALTH_BUDGET:-3}"
HOOK_START=$(date +%s)
HOOK_DEADLINE=$((HOOK_START + HOOK_BUDGET))

warn() {
  local msg="$1"
  echo "[sync-health] $msg" >&2
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $msg" >> "$LOG"
}

notice() {
  local msg="$1"
  echo "[sync-health] $msg"
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $msg" >> "$LOG"
}

# The store can be on NFS. Every probe is lock-free and bounded by both its own
# timeout and the whole-hook deadline. Stock macOS has neither timeout nor
# gtimeout, so its fallback is a background watchdog, never an unbounded git.
_sync_git() {
  local limit now remaining pid watchdog rc
  now=$(date +%s)
  remaining=$((HOOK_DEADLINE - now))
  [[ "$remaining" -gt 0 ]] || return 125
  limit="${CLADE_SYNC_GIT_TIMEOUT:-2}"
  [[ "$limit" -le "$remaining" ]] || limit="$remaining"
  export GIT_OPTIONAL_LOCKS=0
  if command -v timeout >/dev/null 2>&1; then
    timeout "$limit" git -C "$SYNC_DIR" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then
    gtimeout "$limit" git -C "$SYNC_DIR" "$@"
  else
    git -C "$SYNC_DIR" "$@" &
    pid=$!
    # Redirect the whole watchdog: otherwise a command substitution waits for
    # the sleeping child to close its inherited stdout, even after git exits.
    ( sleep "$limit"; kill -TERM "$pid" ) >/dev/null 2>&1 &
    watchdog=$!
    rc=0
    wait "$pid" 2>/dev/null || rc=$?
    [[ "$rc" -ne 143 ]] || rc=124
    kill -TERM "$watchdog" 2>/dev/null || true
    wait "$watchdog" 2>/dev/null || true
    return "$rc"
  fi
}

# sync-push logs `date`'s default format and no success marker. Git's own date
# parser converts that timestamp without GNU date -d or a non-BSD date fallback.
_refused_epoch() {
  local line="$1" stamp ident epoch
  stamp=$(printf '%s\n' "$line" | sed -n 's/^\[\([^]]*\)\].*/\1/p')
  [[ -n "$stamp" ]] || return 1
  # Git misparses localized stamps (zh_CN month/day can swap). An external C
  # locale rejects non-ASCII bytes regardless of the shell's locale handling.
  [[ -z "$(printf '%s' "$stamp" | LC_ALL=C tr -d '\040-\176')" ]] || return 1
  ident=$(GIT_AUTHOR_DATE="$stamp" _sync_git \
    -c user.name=sync-health -c user.email=sync-health@localhost \
    var GIT_AUTHOR_IDENT 2>/dev/null) || return 1
  epoch=$(printf '%s\n' "$ident" | awk '{print $(NF-1)}')
  [[ "$epoch" =~ ^[0-9]+$ ]] || return 1
  printf '%s\n' "$epoch"
}

# Load the store path for Case 11's recovery hints. Case 1: sync was set up on
# this host previously (heuristic: NFS dir or log file exists) but config is gone.
if [[ -f "$SYNC_CONFIG" ]]; then
# shellcheck source=/dev/null
source "$SYNC_CONFIG"
else
  if [[ -d "$HOME/shared-nfs/claude-dotfiles/.git" ]] || \
     [[ -d "$HOME/claude-dotfiles/.git" ]] || \
     [[ -f "$LOG" ]]; then
    warn "Sync repo found but ~/.claude/.sync-config is missing — pushes are silently no-op. Run sync-setup.sh to recover."
  fi
  SYNC_DIR=""
fi

# Case 11: the per-host circuit breaker is a local file, so report it before
# any store probes. The first timestamp can be a claimed probe's start time.
_backoff_status=absent
_backoff_reason=""
if declare -F sync_push_backoff_active >/dev/null 2>&1; then
  sync_push_backoff_active || true
fi
BACKOFF_STORE="${SYNC_DIR:-the sync store (SYNC_DIR in ~/.claude/.sync-config)}"
BACKOFF_MANUAL_FIX="run ~/.claude/scripts/sync-push.sh by hand (manual pushes always run and clear the backoff file on success)"
BACKOFF_FIX="inspect $CONFLICT_LOG and $BACKOFF_STORE, then $BACKOFF_MANUAL_FIX"
case "$_backoff_reason" in
  unmerged-paths|conflict-markers)
    BACKOFF_FIX="resolve $_backoff_reason in $BACKOFF_STORE, then $BACKOFF_MANUAL_FIX"
    ;;
esac
case "$_backoff_status" in
  active)
    BACKOFF_UNTIL_LOCAL=$(_sync_epoch_local "$_backoff_until")
    notice "sync-push backoff: reason=$_backoff_reason consecutive-failures=$_backoff_failures; pushes paused until $BACKOFF_UNTIL_LOCAL; fix: $BACKOFF_FIX"
    ;;
  expired)
    notice "sync-push backoff: reason=$_backoff_reason consecutive-failures=$_backoff_failures; window expired, next write probes; fix: $BACKOFF_FIX"
    ;;
  unreadable)
    notice "sync-push backoff file is unreadable: $_backoff_file; fix: repair or remove the file, then $BACKOFF_MANUAL_FIX"
    ;;
esac

# The index watch below is useful without a store; every store check stays
# behind this guard, and Case 1 otherwise behaves exactly as it did before.
if [[ -f "$SYNC_CONFIG" ]]; then

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

IS_REPO=""
REPO_PROBE_RC=0
if [[ -n "${SYNC_DIR:-}" && -d "$SYNC_DIR" ]]; then
  IS_REPO=$(_sync_git rev-parse --is-inside-work-tree 2>/dev/null) || REPO_PROBE_RC=$?
fi

if [[ "$IS_REPO" == "true" ]]; then
  HOST_NAME=$(hostname)
  STALE_DAYS="${CLADE_SYNC_STALE_DAYS:-7}"

  # Case 5: ls-files -u has one row per stage, so count unique paths, not rows.
  if UNMERGED=$(_sync_git ls-files -u 2>/dev/null); then
    if [[ -n "$UNMERGED" ]]; then
      UNMERGED_PATHS=$(printf '%s\n' "$UNMERGED" | awk -F '\t' 'NF >= 2 && !seen[$2]++ {print $2}')
      UNMERGED_COUNT=$(printf '%s\n' "$UNMERGED_PATHS" | awk 'NF {n++} END {print n + 0}')
      UNMERGED_PREVIEW=$(printf '%s\n' "$UNMERGED_PATHS" | awk \
        'NR <= 3 {if (NR > 1) printf ", "; printf "%s", $0}')
      notice "store has $UNMERGED_COUNT unmerged paths: $UNMERGED_PREVIEW"
    fi
  fi

  # Case 6: an autostash entry means pull --rebase --autostash never finished
  # its pop; rebase --abort alone does not remove this entry or its markers.
  if STASHES=$(_sync_git stash list --format=%gs 2>/dev/null); then
    if grep -qi 'autostash' <<< "$STASHES"; then
      notice "leftover autostash stash: a pull --autostash was left mid-pop"
    fi
  fi

  # Case 7: a host with no earlier commit and a clean store has nothing to
  # report. A host with local changes says "never" once instead of reporting
  # the epoch as its last sync date. Rebase rewrites committer dates but keeps
  # author dates, so %at measures the real sync age and refusal reset point.
  LAST_SYNC=""
  SYNC_AGE_DAYS=""
  if LAST_SYNC=$(_sync_git log -1 --format=%at --grep="^sync: $HOST_NAME " 2>/dev/null); then
    if [[ "$LAST_SYNC" =~ ^[0-9]+$ ]]; then
      SYNC_AGE_DAYS=$(( ($(date +%s) - LAST_SYNC) / 86400 ))
      if [[ "$SYNC_AGE_DAYS" -ge "$STALE_DAYS" ]]; then
        notice "last sync commit by $HOST_NAME was $SYNC_AGE_DAYS days ago (threshold: $STALE_DAYS days)"
      fi
    elif [[ -z "$LAST_SYNC" ]]; then
      if LOCAL_STATUS=$(_sync_git status --porcelain 2>/dev/null); then
        if [[ -n "$LOCAL_STATUS" ]]; then
          notice "this host has never made a sync commit, but the store has local changes"
        fi
      fi
    fi
  fi

  # Case 8: only the trailing REFUSED run counts. A later host commit is the
  # success marker sync-push omits; keep just refusals newer than that commit.
  REFUSED_LINES=()
  if [[ -f "$CONFLICT_LOG" ]]; then
    while IFS= read -r line; do
      REFUSED_LINES+=("$line")
    done < <(awk '
      index($0, "sync-push REFUSED:") {buf = buf $0 ORS; next}
      {buf = ""}
      END {printf "%s", buf}
    ' "$CONFLICT_LOG")
  fi
  REFUSED_COUNT=${#REFUSED_LINES[@]}
  if [[ "$REFUSED_COUNT" -ge 3 && "$LAST_SYNC" =~ ^[0-9]+$ ]]; then
    LAST_REFUSED_INDEX=$((REFUSED_COUNT - 1))
    FIRST_REFUSED_EPOCH=$(_refused_epoch "${REFUSED_LINES[0]}" || true)
    LAST_REFUSED_EPOCH=$(_refused_epoch "${REFUSED_LINES[$LAST_REFUSED_INDEX]}" || true)
    if [[ "$FIRST_REFUSED_EPOCH" =~ ^[0-9]+$ && "$LAST_REFUSED_EPOCH" =~ ^[0-9]+$ ]]; then
      if [[ "$LAST_SYNC" -ge "$LAST_REFUSED_EPOCH" ]]; then
        REFUSED_COUNT=0
      elif [[ "$LAST_SYNC" -ge "$FIRST_REFUSED_EPOCH" ]]; then
        # Timestamps are ordered. Binary-search the first refusal newer than
        # the commit rather than spawning one git date parser per log line.
        LO=0
        HI=$LAST_REFUSED_INDEX
        REFUSED_DATES_OK=1
        while [[ $((HI - LO)) -gt 1 ]]; do
          MID=$(( (LO + HI) / 2 ))
          MID_EPOCH=$(_refused_epoch "${REFUSED_LINES[$MID]}" || true)
          if [[ ! "$MID_EPOCH" =~ ^[0-9]+$ ]]; then
            REFUSED_DATES_OK=0
            break
          elif [[ "$MID_EPOCH" -le "$LAST_SYNC" ]]; then
            LO=$MID
          else
            HI=$MID
          fi
        done
        if [[ "$REFUSED_DATES_OK" -eq 1 ]]; then
          REFUSED_COUNT=$((REFUSED_COUNT - HI))
        fi
      fi
    fi
  fi
  if [[ "$REFUSED_COUNT" -ge 3 ]]; then
    notice "sync-push REFUSED streak: $REFUSED_COUNT consecutive refusal(s) at end of .sync-conflicts.log"
  fi

  # Case 9: @{upstream} is the already-fetched ref. Neither command fetches.
  # Divergence is one finding: combine behind and stale-ahead into one line.
  REMOTE_MSG=""
  if BEHIND=$(_sync_git rev-list --count 'HEAD..@{upstream}' 2>/dev/null); then
    if [[ "$BEHIND" =~ ^[0-9]+$ && "$BEHIND" -gt 0 ]]; then
      REMOTE_MSG="store is $BEHIND commit(s) behind upstream (already-fetched ref; no fetch)"
    fi
    if AHEAD=$(_sync_git rev-list --count '@{upstream}..HEAD' 2>/dev/null); then
      if [[ "$AHEAD" =~ ^[0-9]+$ && "$AHEAD" -gt 0 ]]; then
        # git log is newest-first: its last author timestamp is the oldest
        # unpushed commit. Author dates survive rebase; committer dates do not.
        # `log -1 --reverse` would instead return the newest commit.
        if AHEAD_EPOCHS=$(_sync_git log --format=%at '@{upstream}..HEAD' 2>/dev/null); then
          OLDEST_AHEAD=$(printf '%s\n' "$AHEAD_EPOCHS" | awk \
            'NF {last = $1} END {if (last ~ /^[0-9]+$/) print last}')
          if [[ "$OLDEST_AHEAD" =~ ^[0-9]+$ ]]; then
            AHEAD_AGE_DAYS=$(( ($(date +%s) - OLDEST_AHEAD) / 86400 ))
            if [[ "$AHEAD_AGE_DAYS" -ge "$STALE_DAYS" ]]; then
              AHEAD_MSG="$AHEAD commit(s) ahead of upstream; oldest unpushed commit is $AHEAD_AGE_DAYS days old (unpushed work)"
              if [[ -n "$REMOTE_MSG" ]]; then
                REMOTE_MSG="$REMOTE_MSG; also $AHEAD_MSG"
              else
                REMOTE_MSG="store is $AHEAD_MSG"
              fi
            fi
          fi
        fi
      fi
    fi
  fi
  if [[ -n "$REMOTE_MSG" ]]; then
    notice "$REMOTE_MSG"
  fi
fi
fi

# A quick non-git result is silent; a timeout or exhausted deadline is not a
# healthy result. Emit one line whether the initial or a later probe was cut.
if [[ -f "$SYNC_CONFIG" && -d "${SYNC_DIR:-}" ]]; then
  if [[ "$REPO_PROBE_RC" -eq 124 || "$REPO_PROBE_RC" -eq 125 || "$(date +%s)" -ge "$HOOK_DEADLINE" ]]; then
    notice "store checks cut short: git probes exceeded the ${HOOK_BUDGET}s budget (slow or hung SYNC_DIR?)"
  fi
fi

# Case 10: Claude Code loads only the first 200 lines and 25,000 characters of
# MEMORY.md ("25 KB" in its docs; 2.1.283 compares the trimmed string's length
# with 25000, not 25*1024). This counts bytes, never fewer than characters, so it
# warns early on non-ASCII text and never late. Warn at 80% of either cap; all
# three are env-overridable so the boundary can be exercised without changing
# the shipped native limits.
MEMORY_LINE_CAP="${CLADE_SYNC_MEMORY_LINE_CAP:-200}"
MEMORY_BYTE_CAP="${CLADE_SYNC_MEMORY_BYTE_CAP:-25000}"
MEMORY_WARN_PERCENT="${CLADE_SYNC_MEMORY_WARN_PERCENT:-80}"
MEMORY_FILES=()
if [[ -n "${SYNC_DIR:-}" ]]; then
  MEMORY_FILES+=("$SYNC_DIR"/projects-memory/*/MEMORY.md)
fi
MEMORY_FILES+=(
  "$HOME"/.claude/projects/*/memory/MEMORY.md
  "$HOME"/.claude-profiles/*/projects/*/memory/MEMORY.md
)
MEMORY_SEEN=$'\n'
for MEMORY_FILE in "${MEMORY_FILES[@]}"; do
  [[ -f "$MEMORY_FILE" && ! -L "$MEMORY_FILE" ]] || continue
  # Store entries come first. Resolve directory symlinks portably so one store
  # file linked from several profiles is reported once, at its store path.
  MEMORY_PHYSICAL=$(cd -P "${MEMORY_FILE%/*}" 2>/dev/null && pwd -P) || continue
  MEMORY_PHYSICAL="$MEMORY_PHYSICAL/MEMORY.md"
  case "$MEMORY_SEEN" in
    *$'\n'"$MEMORY_PHYSICAL"$'\n'*) continue ;;
  esac
  MEMORY_SEEN="${MEMORY_SEEN}${MEMORY_PHYSICAL}"$'\n'
  MEMORY_LINES=$(wc -l < "$MEMORY_FILE" 2>/dev/null) || continue
  MEMORY_LINES=$((MEMORY_LINES))
  MEMORY_BYTES=$(stat -c %s "$MEMORY_FILE" 2>/dev/null || stat -f %z "$MEMORY_FILE" 2>/dev/null) || continue
  if [[ $((MEMORY_LINES * 100)) -ge $((MEMORY_WARN_PERCENT * MEMORY_LINE_CAP)) || \
        $((MEMORY_BYTES * 100)) -ge $((MEMORY_WARN_PERCENT * MEMORY_BYTE_CAP)) ]]; then
    MEMORY_KB=$(awk -v bytes="$MEMORY_BYTES" 'BEGIN {printf "%.1f", bytes / 1024}')
    # Without sync, writing LOG would make the next session invent a Case-1
    # prior setup. The index warning is stdout-only on those hosts.
    if [[ -f "$SYNC_CONFIG" ]]; then
      notice "MEMORY.md index cap: $MEMORY_FILE has $MEMORY_LINES lines, $MEMORY_KB KB (threshold: $MEMORY_WARN_PERCENT% of $MEMORY_LINE_CAP lines or $MEMORY_BYTE_CAP bytes)"
    else
      echo "[sync-health] MEMORY.md index cap: $MEMORY_FILE has $MEMORY_LINES lines, $MEMORY_KB KB (threshold: $MEMORY_WARN_PERCENT% of $MEMORY_LINE_CAP lines or $MEMORY_BYTE_CAP bytes)"
    fi
  fi
done

exit 0
