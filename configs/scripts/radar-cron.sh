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
  if git -C "$KIT_DIR" rev-parse -q --verify origin/main >/dev/null 2>&1; then base=origin/main
  else base=$(git -C "$KIT_DIR" symbolic-ref --short -q HEAD 2>/dev/null || echo HEAD); fi
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
# the correction history (Lane C), and transcripts for the hook-rejection
# tally. Everything else outside the run directory is refused to the agent.
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

log "START weekly radar sweep"
# --print: headless, one shot. Permission mode is explicit rather than inherited
# from the interactive shell alias, which cron does not load.
if ( cd "$RUN_DIR" && _timeout "$TIMEOUT_SECS" "$CLAUDE_BIN" \
     "/radar

Run the full three-lane sweep unattended. $WHERE

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
