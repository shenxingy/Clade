#!/usr/bin/env bash
# radar-cron.sh — run /radar unattended on a schedule.
#
# Why a local cron and not a cloud routine: radar's third lane mines
# ~/.claude/corrections/history.jsonl — this machine's record of where the
# stack actually failed its user. A cloud runner cannot see that file, and the
# lane that only reads the public web is the one that already existed.
#
# Why not CronCreate: those jobs are session-only and auto-expire after 7 days.
# "Keep up with the field" is not a one-week commitment.
#
# Install (weekly, Monday 08:07 local — off the :00 mark on purpose):
#   (crontab -l 2>/dev/null; echo "7 8 * * 1 $HOME/.claude/scripts/radar-cron.sh") | crontab -
# Remove:
#   crontab -l | grep -v radar-cron | crontab -
#
# After the sweep it runs keep-sessions.py --apply, the kit's one weekly
# housekeeping job (the last section of this file); that step cannot fail
# the sweep.
#
# ─── Where the sweep's code edits go ─────────────────────────────────
# The skill builds small fixes as well as a digest. Until 2026-10-20 the agent
# ran from cron's cwd ($HOME) and edited the Clade checkout in place, whatever
# branch someone had open there: the 10-12 run left its edits on fix/warm-pace
# for four days, the 10-19 run left them on main, where another session's Stop
# hook found them. The agent could not run bash or git, so none of it was ever
# verified or committed by the run that wrote it.
#
# Now the wrapper — trusted code, not the agent — owns the git and the
# verification:
#   1. it creates a worktree of the kit repo on a fresh branch radar/<date>,
#      from origin/main, OUTSIDE ~/.claude (the harness refuses every edit
#      under ~/.claude), and runs the agent with that worktree as its cwd.
#      Measured 2026-10-20 (claude 2.1.283, acceptEdits): outside its cwd the
#      agent is refused even a Read, so no other checkout can be touched;
#      --add-dir grants the read-only inputs the lanes need.
#   2. after the agent exits it runs `bash -n` on every changed shell file and
#      the shell suites that name a changed file, inside bubblewrap: no
#      network, the filesystem read-only except the worktree and a private
#      /tmp. Running agent-written code is the security fork the 10-12 TODO
#      named — this run also read untrusted web content and the user's private
#      correction history — and the sandbox removes the exfiltration leg and
#      any write outside the worktree. No bwrap (macOS): parse only, and the
#      record says the suites were not run.
#   3. it commits to that local branch with the verification in the message,
#      removes the worktree, and leaves the branch for review. It never pushes:
#      the edits came from a run that read the open web and private history,
#      and a public repository is not where an unreviewed copy of that goes.
#      session-context.sh lists radar/* branches when a session opens the kit.
set -uo pipefail

CLAUDE_BIN="${CLADE_CLAUDE_BIN:-$HOME/.local/bin/claude}"
RESEARCH_DIR="$HOME/.claude/research"
LOG="$RESEARCH_DIR/radar-cron.log"
RUN_DATE="${CLADE_RADAR_DATE:-$(date +%Y-%m-%d)}"
KIT_DIR="${CLADE_RADAR_REPO:-$(cat "$HOME/.claude/.kit-source-dir" 2>/dev/null || true)}"
WT_ROOT="${CLADE_RADAR_WORKTREES:-$HOME/.clade/radar-worktrees}"
SUITE_TIMEOUT="${CLADE_RADAR_SUITE_TIMEOUT:-600}"

# Lock location: a per-user scratch root, never a fixed /tmp path. On a shared
# host the first account to create /tmp/clade-radar.lock owns it, and every
# other account's `exec 9>` fails — taking the `|| exit 0` branch BEFORE the
# first log() call, so the weekly sweep silently never runs and leaves no trace.
# cron has no XDG_RUNTIME_DIR, so the ${TMPDIR:-/tmp}/clade-$EUID leg inside the
# helper is the NORMAL path here; $RESEARCH_DIR (already $HOME-private) is the
# last resort if even that is unusable.
_RADAR_RUNTIME_LIB="$(cd "$(dirname "$0")" 2>/dev/null && pwd)/../hooks/lib/runtime-dir.sh"
# shellcheck source=/dev/null
[[ -f "$_RADAR_RUNTIME_LIB" ]] && . "$_RADAR_RUNTIME_LIB" 2>/dev/null
if [[ -n "${CLADE_RADAR_LOCK:-}" ]]; then
  LOCK="$CLADE_RADAR_LOCK"
elif declare -f clade_runtime_dir >/dev/null 2>&1 && _RADAR_RT=$(clade_runtime_dir 2>/dev/null); then
  LOCK="$_RADAR_RT/radar.lock"
else
  LOCK="$RESEARCH_DIR/.radar.lock"
fi
# A sweep that searches, reads, and triages is not a 60-second job; but an
# unattended run that hangs must not still be holding the lock next week.
TIMEOUT_SECS="${CLADE_RADAR_TIMEOUT:-2700}"

mkdir -p "$RESEARCH_DIR"

log() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG"; }

if [[ ! -x "$CLAUDE_BIN" ]]; then
  log "SKIP: no claude binary at $CLAUDE_BIN (set CLADE_CLAUDE_BIN)"
  exit 0
fi

# flock -n: if last week's run is somehow still going, skip rather than stack.
# Log the open failure: an unopenable lock used to end the run before the first
# log line, which is indistinguishable from "cron never fired".
exec 9>"$LOCK" || { log "SKIP: cannot open lock $LOCK"; exit 0; }
if ! flock -n 9; then
  log "SKIP: a radar run is already in progress"
  exit 0
fi

_timeout() { if command -v timeout >/dev/null 2>&1; then timeout "$@"; else shift; "$@"; fi; }

# ─── Fold in what the agent could not write ──────────────────────────
# The harness refuses every Write/Edit/redirect under ~/.claude/** as a
# sensitive path, in every permission mode short of bypass — so the sweep
# cannot write its own digest or append to its own ledger, and stages both
# instead. Measured 2026-09-21: four such pairs (2026-08-17, 08-24, 08-31,
# 09-07) had sat in $HOME for five weeks, the ledger's last entry was
# 2026-09-05, and every sweep since diffed the field against a ledger missing
# its own predecessors' findings. A note asking a human to run two commands is
# not a mechanism. This wrapper runs from cron as the user, outside the
# harness, so the fold-in lives here — BEFORE the sweep (the ledger it reads
# must be whole) and AFTER it (this run's output lands the same day). Staged
# names are the contract: radar-YYYY-MM-DD.md and
# known-concepts-append-YYYY-MM-DD.md, in $HOME (older runs) or in the run's
# worktree under .radar-staged/ (the agent cannot write outside its cwd now).
# A staged file is removed only after its content is safely in place; a digest
# that would clobber an existing one is left staged and logged, never
# overwritten.
fold_staged() {
  local dir f dest
  for dir in "$HOME" "$@"; do
    [[ -d "$dir" ]] || continue
    for f in "$dir"/known-concepts-append-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md; do
      [[ -f "$f" ]] || continue
      if { printf '\n'; cat "$f"; } >> "$RESEARCH_DIR/known-concepts.md"; then
        rm -f "$f"
        log "FOLDED ledger append $(basename "$f")"
      else
        log "FOLD FAILED (left staged): $f"
      fi
    done
    for f in "$dir"/radar-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md; do
      [[ -f "$f" ]] || continue
      dest="$RESEARCH_DIR/$(basename "$f")"
      if [[ -e "$dest" ]]; then
        log "FOLD SKIPPED (digest exists, left staged): $f"
      elif mv "$f" "$dest"; then
        log "FOLDED digest $(basename "$f")"
      else
        log "FOLD FAILED (left staged): $f"
      fi
    done
  done
}

fold_staged

# ─── Keep earlier radar branches reviewable ──────────────────────────
# One TSV in the existing radar state directory is the handoff to
# session-context.sh. Fields: branch, status, date, paths/upstream/error,
# deletion-candidate (0/1), branch tip, first-conflict date. The last field
# preserves that date even when a later probe can only report "unknown".
RADAR_BRANCH_STATE="${CLADE_RADAR_BRANCH_STATE:-$RESEARCH_DIR/radar-branch-state.tsv}"
RADAR_DELETE_WEEKS="${CLADE_RADAR_DELETE_AFTER_WEEKS:-4}"
case "$RADAR_DELETE_WEEKS" in
  ''|*[!0-9]*) RADAR_DELETE_WEEKS=4 ;;
esac

radar_state_field() {  # radar_state_field <branch> <column>
  [[ -f "$RADAR_BRANCH_STATE" ]] || return 0
  awk -F '\t' -v b="$1" -v f="$2" '$1 == b { print $f; exit }' "$RADAR_BRANCH_STATE" 2>/dev/null
}

radar_previous_conflict() {
  local branch="$1" since
  since=$(radar_state_field "$branch" 7)
  case "$since" in
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;;
    *) since="" ;;
  esac
  if [[ -z "$since" && "$(radar_state_field "$branch" 2)" == conflict ]]; then
    since=$(radar_state_field "$branch" 3)
    case "$since" in
      [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;;
      *) since="" ;;
    esac
  fi
  printf '%s' "$since"
}

radar_conflict_since() {
  local since
  since=$(radar_previous_conflict "$1")
  printf '%s' "${since:-$RUN_DATE}"
}

radar_join_paths() {  # radar_join_paths <newline-separated paths>; sets RADAR_PATHS
  local paths="$1" p
  RADAR_PATHS=""
  while IFS= read -r p; do
    [[ -n "$p" ]] || continue
    RADAR_PATHS+="${RADAR_PATHS:+, }$p"
  done <<< "$paths"
  [[ -n "$RADAR_PATHS" ]] || RADAR_PATHS="paths unavailable"
}

radar_record_state() {  # branch status date details candidate tip conflict-since
  local details="${4:--}"
  details=${details//$'\t'/ }
  details=${details//$'\n'/ }
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$1" "$2" "$3" "$details" "$5" "${6:--}" "${7:--}" >> "$RADAR_STATE_NEXT"
}

radar_branch_upkeep() {
  local main_ref="$1" branch old_tip new_tip after_tip upstream_remote upstream_merge
  local merge_out merge_rc probe_wt rebase_out paths behind runtime_root
  local status date details candidate conflict_since previous previous_date previous_tip
  local first_ts now mode=modern pushed_refs non_main_upstream main_merge_ref
  main_merge_ref="refs/heads/${main_ref##*/}"
  RADAR_STATE_NEXT="$RADAR_BRANCH_STATE.tmp.$$"
  if ! printf '# branch\tstatus\tdate\tdetails\tdeletion-candidate\ttip\tfirst-conflict\n' > "$RADAR_STATE_NEXT"; then
    log "UPKEEP SKIPPED: cannot write $RADAR_STATE_NEXT"
    return 0
  fi

  # A same-ref probe is a capability check, not a version parser. Apple Git and
  # distribution builds do not all use upstream's version suffixes.
  if ! _timeout 60 git -C "$KIT_DIR" merge-tree --write-tree "$main_ref" "$main_ref" >/dev/null 2>&1; then
    mode=fallback
  fi

  while IFS= read -r branch; do
    [[ "$branch" == radar/* ]] || continue
    old_tip=$(git -C "$KIT_DIR" rev-parse "refs/heads/$branch" 2>/dev/null)
    upstream_remote=$(git -C "$KIT_DIR" config --get "branch.$branch.remote" 2>/dev/null)
    upstream_merge=$(git -C "$KIT_DIR" config --get "branch.$branch.merge" 2>/dev/null)
    pushed_refs=$(git -C "$KIT_DIR" for-each-ref --contains "refs/heads/$branch" --format='%(refname)' refs/remotes/ 2>/dev/null)
    # branch.autoSetupMerge makes a branch cut from origin/main track main even
    # though no radar branch was pushed. Only a non-main upstream or an actual
    # remote-tracking copy makes the branch shared.
    non_main_upstream=0
    if [[ -n "$upstream_remote" || -n "$upstream_merge" ]]; then
      if [[ "$upstream_merge" != "$main_merge_ref" ]]; then
        non_main_upstream=1
      elif [[ "$upstream_remote" != origin && "$upstream_remote" != . ]]; then
        non_main_upstream=1
      fi
    fi
    status=clean; date="$RUN_DATE"; details="-"; candidate=0; conflict_since="-"
    new_tip="$old_tip"; merge_rc=0; merge_out=""; paths=""

    if [[ "$mode" == modern ]]; then
      merge_out=$(_timeout 60 git -C "$KIT_DIR" merge-tree --write-tree --name-only "$main_ref" "$branch" 2>&1)
      merge_rc=$?
      if [[ $merge_rc -eq 1 ]]; then
        paths=$(printf '%s\n' "$merge_out" | sed -n '2,/^$/p' | sed '/^$/d')
      fi
    else
      probe_wt=""
      if declare -f clade_runtime_dir >/dev/null 2>&1 && runtime_root=$(clade_runtime_dir 2>/dev/null); then
        probe_wt=$(mktemp -d "$runtime_root/radar-merge.XXXXXX" 2>/dev/null)
      fi
      if [[ -n "$probe_wt" ]] && git -C "$KIT_DIR" -c core.hooksPath=/dev/null worktree add -q --detach "$probe_wt" "$branch" >/dev/null 2>&1; then
        merge_out=$(_timeout 60 git -C "$probe_wt" -c core.hooksPath=/dev/null merge --no-commit --no-ff "$main_ref" 2>&1)
        merge_rc=$?
        [[ $merge_rc -eq 1 ]] && paths=$(git -C "$probe_wt" diff --name-only --diff-filter=U 2>/dev/null)
        git -C "$probe_wt" merge --abort >/dev/null 2>&1
        git -C "$KIT_DIR" worktree remove --force "$probe_wt" >/dev/null 2>&1
      else
        merge_rc=129
        [[ -z "$probe_wt" ]] || rmdir "$probe_wt" 2>/dev/null
      fi
    fi

    if [[ $merge_rc -eq 0 ]]; then
      behind=$(git -C "$KIT_DIR" rev-list --count "$branch..$main_ref" 2>/dev/null)
      case "$behind" in ''|*[!0-9]*) behind=0 ;; esac
      if [[ $behind -gt 0 ]]; then
        if [[ -n "$pushed_refs" ]]; then
          status=upstream
          details="remote ref: ${pushed_refs%%$'\n'*}"
          log "UPKEEP $branch has a remote-tracking copy; left untouched"
        elif [[ $non_main_upstream -eq 1 ]]; then
          status=upstream
          details="${upstream_remote:-unknown}:${upstream_merge:-unknown}"
          log "UPKEEP $branch has a non-main upstream; left untouched"
        else
          probe_wt=""
          if declare -f clade_runtime_dir >/dev/null 2>&1 && runtime_root=$(clade_runtime_dir 2>/dev/null); then
            probe_wt=$(mktemp -d "$runtime_root/radar-rebase.XXXXXX" 2>/dev/null)
          fi
          if [[ -n "$probe_wt" ]] && git -C "$KIT_DIR" -c core.hooksPath=/dev/null worktree add -q "$probe_wt" "$branch" >/dev/null 2>&1; then
            rebase_out=$(_timeout 120 git -C "$probe_wt" -c core.hooksPath=/dev/null rebase "$main_ref" 2>&1)
            merge_rc=$?
            if [[ $merge_rc -eq 0 ]]; then
              git -C "$KIT_DIR" worktree remove --force "$probe_wt" >/dev/null 2>&1
              new_tip=$(git -C "$KIT_DIR" rev-parse "refs/heads/$branch" 2>/dev/null)
              status=rebased; details="$main_ref"
              log "UPKEEP $branch rebased onto $main_ref"
            else
              paths=$(git -C "$probe_wt" diff --name-only --diff-filter=U 2>/dev/null)
              git -C "$probe_wt" -c core.hooksPath=/dev/null rebase --abort >/dev/null 2>&1
              git -C "$KIT_DIR" worktree remove --force "$probe_wt" >/dev/null 2>&1
              after_tip=$(git -C "$KIT_DIR" rev-parse "refs/heads/$branch" 2>/dev/null)
              [[ "$after_tip" == "$old_tip" ]] || log "UPKEEP WARNING: $branch moved during a failed rebase ($old_tip -> $after_tip)"
              new_tip="$after_tip"
              if [[ -n "$paths" ]]; then
                radar_join_paths "$paths"
                status=conflict; date=$(radar_conflict_since "$branch"); details="$RADAR_PATHS"
                conflict_since="$date"
                log "UPKEEP $branch rebase stopped; aborted; conflicts: $details"
              else
                details=$(printf '%s\n' "$rebase_out" | tail -n 1)
                status=unknown; details="rebase failed: ${details:-exit $merge_rc}"
                conflict_since=$(radar_previous_conflict "$branch")
                [[ -n "$conflict_since" ]] || conflict_since="-"
                log "UPKEEP $branch rebase failed without unmerged paths; aborted: $details"
              fi
            fi
          else
            status=unknown; details="no throwaway worktree available for rebase"
            [[ -z "$probe_wt" ]] || rmdir "$probe_wt" 2>/dev/null
          fi
        fi
      else
        previous=$(radar_state_field "$branch" 2)
        previous_tip=$(radar_state_field "$branch" 6)
        if [[ "$previous" == rebased && "$previous_tip" == "$old_tip" ]]; then
          previous_date=$(radar_state_field "$branch" 3)
          status=rebased; date="$previous_date"; details="$main_ref"
        fi
      fi
    elif [[ $merge_rc -eq 1 ]]; then
      radar_join_paths "$paths"
      status=conflict; date=$(radar_conflict_since "$branch"); details="$RADAR_PATHS"
      conflict_since="$date"
      log "UPKEEP $branch conflicts with $main_ref: $details"
    else
      status=unknown; details="merge status could not be checked"
      conflict_since=$(radar_previous_conflict "$branch")
      [[ -n "$conflict_since" ]] || conflict_since="-"
      log "UPKEEP $branch merge status unknown: $(printf '%s\n' "$merge_out" | tail -n 1)"
    fi

    if [[ "$status" == conflict ]]; then
      # Author time survives our own rebases; committer time does not.
      first_ts=$(git -C "$KIT_DIR" log --format=%at --reverse "$main_ref..$branch" 2>/dev/null | head -n 1)
      now=$(date +%s)
      case "$first_ts" in
        ''|*[!0-9]*) ;;
        *) [[ $((now - first_ts)) -gt $((RADAR_DELETE_WEEKS * 7 * 86400)) ]] && candidate=1 ;;
      esac
    fi
    radar_record_state "$branch" "$status" "$date" "$details" "$candidate" "$new_tip" "$conflict_since"
  done < <(git -C "$KIT_DIR" branch --no-merged "$main_ref" --list 'radar/*' --format='%(refname:short)' 2>/dev/null)

  if mv "$RADAR_STATE_NEXT" "$RADAR_BRANCH_STATE"; then
    log "UPKEEP state written to $RADAR_BRANCH_STATE"
  else
    rm -f "$RADAR_STATE_NEXT"
    log "UPKEEP state write failed: $RADAR_BRANCH_STATE"
  fi
}

# ─── The run's own worktree ──────────────────────────────────────────
# radar_worktree — sets WT and RADAR_BRANCH, or leaves WT empty. A second run
# on one day takes radar/<date>-2, -3, … rather than reusing a branch someone
# may be reviewing.
WT=""
RADAR_BRANCH=""
radar_worktree() {
  local base n=1 branch path
  [[ -n "$KIT_DIR" ]] && git -C "$KIT_DIR" rev-parse --git-dir >/dev/null 2>&1 || {
    log "NO WORKTREE: no kit repository (${KIT_DIR:-unset}); the sweep runs without code edits"
    return 0
  }
  _timeout 60 git -C "$KIT_DIR" fetch -q origin main >/dev/null 2>&1 || log "fetch failed; branching from the last known origin/main"
  if git -C "$KIT_DIR" rev-parse -q --verify origin/main >/dev/null 2>&1; then
    base=origin/main
  elif git -C "$KIT_DIR" rev-parse -q --verify refs/heads/main >/dev/null 2>&1; then
    base=main
  else
    base=$(git -C "$KIT_DIR" symbolic-ref --short -q HEAD 2>/dev/null || echo HEAD)
  fi
  radar_branch_upkeep "$base"
  branch="radar/$RUN_DATE"
  while git -C "$KIT_DIR" rev-parse -q --verify "refs/heads/$branch" >/dev/null 2>&1; do
    n=$((n + 1)); branch="radar/$RUN_DATE-$n"
  done
  path="$WT_ROOT/${branch//\//-}"
  mkdir -p "$WT_ROOT"
  if git -C "$KIT_DIR" worktree add -q -b "$branch" "$path" "$base" >/dev/null 2>&1; then
    WT="$path"; RADAR_BRANCH="$branch"
    mkdir -p "$WT/.radar-staged"
    # Ignore the staging dir repository-wide (info/exclude is shared by every
    # worktree), whatever the branch's .gitignore says. Naming an ignored path
    # in a `git add` pathspec — even as an exclude — makes git exit 1, which is
    # how the first cut of this commit step failed every time.
    _exclude="$(git -C "$KIT_DIR" rev-parse --git-common-dir)/info/exclude"
    case "$_exclude" in /*) ;; *) _exclude="$KIT_DIR/$_exclude" ;; esac
    mkdir -p "$(dirname "$_exclude")"
    grep -qxF '.radar-staged/' "$_exclude" 2>/dev/null || printf '.radar-staged/\n' >> "$_exclude"
    log "WORKTREE $WT on $RADAR_BRANCH from $base"
  else
    log "NO WORKTREE: git worktree add failed for $path; the sweep runs without code edits"
  fi
}
radar_worktree

# Without a worktree the agent runs in an empty directory, so it has nothing
# to edit — a digest-only sweep, never an edit to someone's checkout.
if [[ -n "$WT" ]]; then
  RUN_DIR="$WT"; STAGE_DIR="$WT/.radar-staged"
else
  RUN_DIR=$(mktemp -d "${TMPDIR:-/tmp}/radar-run.XXXXXX"); STAGE_DIR="$RUN_DIR"
fi

# Read-only inputs the lanes need, granted per run: the ledger and digests,
# the correction history (Lane C), and the transcripts, which Lane D's report
# cites by file and record and Lane C's own tallies read. Everything else
# outside the run directory is refused to the agent.
RADAR_ADD_DIRS=()
for _d in "$RESEARCH_DIR" "$HOME/.claude/corrections" "$HOME/.claude/projects" "$HOME"/.claude-profiles/*/projects; do
  [[ -d "$_d" ]] && RADAR_ADD_DIRS+=(--add-dir "$_d")
done

# ─── Web surface for Lane A ──────────────────────────────────────────
# acceptEdits grants file edits and nothing else, so WebSearch and WebFetch
# each needed an interactive grant no one was present to give: Lane A — the
# lane this skill exists for — did not run for five consecutive weekly sweeps
# (2026-08-17 → 2026-09-21) while the log recorded DONE and {"ok":true}.
# Granted here, scoped to this invocation, rather than in settings.json where
# it would widen every interactive session. WebFetch is allowed only on named
# practitioner/reference domains: an unattended agent that reads the user's
# own correction history and then reads the open web must not also hold an
# arbitrary-URL GET, which is the third leg of the lethal trifecta (private
# data + untrusted content + exfiltration channel). WebSearch returns
# harness-mediated snippets and carries no URL the model composes. Extend the
# list rather than replacing it with a bare WebFetch.
RADAR_ALLOWED_TOOLS=(
  "WebSearch"
  "WebFetch(domain:arxiv.org)"
  "WebFetch(domain:news.ycombinator.com)"
  "WebFetch(domain:hn.algolia.com)"
  "WebFetch(domain:anthropic.com)"
  # `domain:` is an exact host match, not a suffix: the 2026-10-05 sweep was
  # refused https://www.anthropic.com/engineering, the form search results link
  # to, while the bare host was allowed.
  "WebFetch(domain:www.anthropic.com)"
  "WebFetch(domain:code.claude.com)"
  "WebFetch(domain:github.com)"
  "WebFetch(domain:simonwillison.net)"
  "WebFetch(domain:lucumr.pocoo.org)"
  "WebFetch(domain:addyosmani.com)"
  "WebFetch(domain:ghuntley.com)"
  "WebFetch(domain:ampcode.com)"
)
# One comma-joined value, passed AFTER the prompt: --allowedTools is variadic,
# and placed before the positional prompt it would swallow the prompt as one
# more tool name. No entry contains a comma, so the join is lossless.
RADAR_ALLOWED_TOOLS_CSV="$(IFS=,; printf '%s' "${RADAR_ALLOWED_TOOLS[*]}")"

if [[ -n "$WT" ]]; then
  WHERE="You are running in an isolated git worktree of the Clade repository at $WT, \
on branch $RADAR_BRANCH, made from origin/main for this run. Make every Clade \
change here and nowhere else — other checkouts are not reachable. You cannot run \
bash or git: when you finish, the cron wrapper commits your edits to this \
branch, runs bash -n and the affected shell suites in a sandbox with no network, \
and records the results for review. So do not leave 'run this' notes, and do \
not describe an edit as verified."
else
  WHERE="There is no repository checkout in this run, so make no code edits; \
report fixes in the digest instead."
fi

# ─── Lane D's input ──────────────────────────────────────────────────
# The agent runs read-only commands (grep, jq, find: the 2026-10-26 and 11-02
# sweeps computed the old hook-error tally that way), but `python3 <script>`
# waits for an approval nobody is there to give; both digests record it. So
# friction-rank.py (beside this script), which ranks the harness's verdicts in
# the transcripts by distinct sessions, is run here and handed over as a file.
# A run that could not produce it says so in the prompt, so the digest cannot
# read a missing report as a quiet week.
# --holdout-weeks 2: this runs Monday morning, hours into the ISO week, so the
# current week alone would hold out hours of data, and SKILL.md tells the grader
# that a family absent from the held-out column is a burst.
FRICTION_REPORT="$STAGE_DIR/friction-$RUN_DATE.txt"
FRICTION_PY="$(cd "$(dirname "$0")" 2>/dev/null && pwd)/friction-rank.py"
if command -v python3 >/dev/null 2>&1 && [[ -f "$FRICTION_PY" ]] \
   && _timeout 300 python3 "$FRICTION_PY" --top 15 --holdout-weeks 2 > "$FRICTION_REPORT" 2>&1; then
  LANE_D="Lane D's report, from friction-rank.py, is $FRICTION_REPORT: read it rather than re-deriving it."
  log "LANE D report at $FRICTION_REPORT"
else
  LANE_D="Lane D was NOT MEASURED this run (friction-rank.py did not produce a report; see $FRICTION_REPORT if it exists): say so in the digest."
  log "LANE D NOT MEASURED"
fi

log "START weekly radar sweep"
# --print: headless, one shot. Permission mode is explicit rather than inherited
# from the interactive shell alias, which cron does not load.
if ( cd "$RUN_DIR" && _timeout "$TIMEOUT_SECS" "$CLAUDE_BIN" \
     "/radar

Run the full four-lane sweep unattended. $WHERE $LANE_D

Write the digest to $STAGE_DIR/radar-$RUN_DATE.md and the ledger append to \
$STAGE_DIR/known-concepts-append-$RUN_DATE.md — exactly those names — and the \
cron wrapper folds them into $RESEARCH_DIR. Do not ask a human to run a command.

You are running with no human present: do not ask questions, and do not leave a \
confirmed gap as a bare TODO if it is small enough to build now." \
     --print \
     --permission-mode acceptEdits \
     "${RADAR_ADD_DIRS[@]}" \
     --allowedTools "$RADAR_ALLOWED_TOOLS_CSV" \
     >> "$LOG" 2>&1 ); then
  log "DONE"
else
  rc=$?
  [[ $rc -eq 124 ]] && log "TIMEOUT after ${TIMEOUT_SECS}s" || log "FAILED rc=$rc"
fi

fold_staged "$STAGE_DIR"

# ─── Verify and commit what the agent changed ────────────────────────
# radar_sandbox_args — the bwrap prefix: no network, the filesystem
# read-only except the worktree and a private /tmp, and HOME pointed into that
# /tmp. Order matters: the tmpfs goes on /tmp BEFORE the worktree is bound, or
# a worktree that lives under /tmp disappears beneath it.
radar_sandbox_args() {
  RADAR_BWRAP=(bwrap --ro-bind / / --tmpfs /tmp --bind "$WT" "$WT" --dev /dev --proc /proc
    --unshare-net --unshare-pid --die-with-parent
    --setenv HOME /tmp/home --chdir "$WT" --)
}
have_sandbox() {
  command -v bwrap >/dev/null 2>&1 || return 1
  radar_sandbox_args
  "${RADAR_BWRAP[@]}" true >/dev/null 2>&1
}

if [[ -n "$WT" ]]; then
  CHANGED=$(cd "$WT" && git status --porcelain --untracked-files=all | sed -E 's/^.. //; s/^.* -> //')
  if [[ -z "$CHANGED" ]]; then
    git -C "$KIT_DIR" worktree remove --force "$WT" >/dev/null 2>&1
    git -C "$KIT_DIR" branch -D "$RADAR_BRANCH" >/dev/null 2>&1
    log "NO CODE EDITS — worktree and $RADAR_BRANCH removed"
  else
    VERIFY=""
    PARSE_FAILS=0
    while IFS= read -r f; do
      [[ "$f" == *.sh && -f "$WT/$f" ]] || continue
      if bash -n "$WT/$f" 2>/dev/null; then VERIFY+="  bash -n $f: ok"$'\n'
      else VERIFY+="  bash -n $f: FAIL"$'\n'; PARSE_FAILS=$((PARSE_FAILS + 1)); fi
    done <<< "$CHANGED"
    # The suites that name a changed file, by basename. A changed suite runs too.
    SUITES=""
    while IFS= read -r f; do
      [[ -n "$f" ]] || continue
      case "$f" in tests/test-*.sh) SUITES+="$f"$'\n' ;; esac
      while IFS= read -r s; do SUITES+="${s#"$WT"/}"$'\n'; done \
        < <(grep -lF -- "$(basename "$f")" "$WT"/tests/test-*.sh 2>/dev/null)
    done <<< "$CHANGED"
    SUITES=$(printf '%s' "$SUITES" | sed '/^$/d' | sort -u)
    SUITE_FAILS=0
    if [[ -z "$SUITES" ]]; then
      VERIFY+="  suites: none name a changed file"$'\n'
    elif have_sandbox; then
      while IFS= read -r s; do
        if _timeout "$SUITE_TIMEOUT" "${RADAR_BWRAP[@]}" \
             bash -c 'mkdir -p /tmp/home && exec bash "$0"' "$s" >/dev/null 2>&1; then
          VERIFY+="  $s (sandbox, no network): pass"$'\n'
        else
          VERIFY+="  $s (sandbox, no network): FAIL"$'\n'; SUITE_FAILS=$((SUITE_FAILS + 1))
        fi
      done <<< "$SUITES"
    else
      VERIFY+="  suites NOT run — no bwrap sandbox on this host: $(printf '%s' "$SUITES" | tr '\n' ' ')"$'\n'
    fi
    NFILES=$(printf '%s\n' "$CHANGED" | sed '/^$/d' | wc -l | tr -d ' ')
    MSG="radar($RUN_DATE): unattended sweep edits — UNREVIEWED, $NFILES file(s)

Written by the weekly radar cron, which could not run bash or git; committed
and verified by its wrapper. Review before landing: the run also read the open
web and the private correction history.

Verification ($PARSE_FAILS parse failure(s), $SUITE_FAILS suite failure(s)):
$VERIFY
Digest: $RESEARCH_DIR/radar-$RUN_DATE.md"
    if ( cd "$WT" && git add -A -- . \
         && git -c core.hooksPath=/dev/null commit -q -m "$MSG" ); then
      git -C "$KIT_DIR" worktree remove --force "$WT" >/dev/null 2>&1
      log "COMMITTED $RADAR_BRANCH ($NFILES file(s), $PARSE_FAILS parse / $SUITE_FAILS suite failure(s)) — review: git -C $KIT_DIR log -p origin/main..$RADAR_BRANCH"
    else
      log "COMMIT FAILED — edits left in $WT on $RADAR_BRANCH"
    fi
  fi
fi

# ─── Keep the corrected sessions before the 30-day cleanup ───────────
# Claude Code deletes a transcript 30 days after its last write, and a session
# a correction points at is a ready-made eval only while it exists.
# keep-sessions.py copies those sessions, redacted, to
# ~/.local/share/clade/sessions/ (see its docstring). It runs here because this
# is the one weekly job the kit already has, and LAST, so it can neither delay
# nor fail the sweep: whatever it exits with is logged, the wrapper's own exit
# status is unchanged, and a hang is cut off by the timeout where `timeout`
# exists. Only its one-line summary reaches this log.
KEEP_SESSIONS="${CLADE_KEEP_SESSIONS:-$(cd "$(dirname "$0")" 2>/dev/null && pwd)/keep-sessions.py}"
KEEP_SESSIONS_TIMEOUT="${CLADE_KEEP_SESSIONS_TIMEOUT:-1800}"
keep_sessions() {
  local out rc
  if ! command -v python3 >/dev/null 2>&1 || [[ ! -f "$KEEP_SESSIONS" ]]; then
    log "KEEP-SESSIONS SKIPPED: no python3, or no $KEEP_SESSIONS"
    return 0
  fi
  out=$(_timeout "$KEEP_SESSIONS_TIMEOUT" python3 "$KEEP_SESSIONS" --apply 2>&1 </dev/null)
  rc=$?
  if [[ $rc -eq 0 ]]; then
    log "KEEP-SESSIONS $(printf '%s\n' "$out" | tail -n 1)"
  else
    log "KEEP-SESSIONS FAILED rc=$rc (the sweep is unaffected): $(printf '%s\n' "$out" | tail -n 1)"
  fi
  return 0
}
keep_sessions
