#!/usr/bin/env bash
# loop_holdout.sh — acceptance scenarios kept OUTSIDE the repository (--holdout DIR).
#
# Why. StrongDM's software-factory write-up names the failure: "A test, stored
# in the codebase, can be lazily rewritten to match the code." Every other /loop
# gate lives in the tree a worker commits into: loop_verify.sh re-reads
# verify_cmd from the repository's CLAUDE.md on every iteration, and
# loop-runner.sh pastes the whole goal file into the supervisor prompt. A
# holdout is a directory of executable scenarios the loop runs but no prompt
# ever names.
#
# Honest scope. The workers run as the same user as the loop, so they CAN read
# or write any absolute path, this directory and its log included. This makes
# the scenarios harder to rewrite, not impossible to rewrite: they are outside
# every commit a worker makes, nothing that names them or carries their output
# is written inside the checkout, and a change to them mid-run is reported. It
# is not a sandbox.
#
# Contract:
#   - DIR must resolve (cd DIR && pwd -P — no realpath dependency) outside
#     `git rev-parse --show-toplevel`, and outside every other worktree of the
#     same repository. A scenario that is a symlink resolving into the
#     repository, or into another worktree of it, is refused too.
#   - A scenario is a top-level, executable, non-hidden regular file in DIR.
#     Other files are fixtures, expected outputs, helpers or notes: they do not
#     run, but they are part of the set — the change fingerprint covers every
#     entry under DIR, recursively (_holdout_fingerprint). Zero scenarios is
#     refused: a holdout that checks nothing would read as a pass.
#   - Each scenario runs with cwd = the checkout root and stdin closed;
#     exit 0 = satisfied. A watchdog (_holdout_bounded, python3 — no timeout or
#     gtimeout binary needed) cuts it off after HOLDOUT_TIMEOUT seconds
#     (CLADE_LOOP_HOLDOUT_TIMEOUT, validated here): SIGTERM to its whole
#     process group, SIGKILL 5 s later. A scenario cut off counts as failed.
#   - Whatever the scenarios write into the checkout is put back after they
#     run (_holdout_capture/_holdout_restore), so node_commit_changes cannot
#     sweep it into a commit, whose file names would reach the next prompt. The
#     git index is put back byte for byte from a copy, so skip-worktree,
#     intent-to-add and assume-unchanged entries survive.
#   - Nothing that names DIR or a scenario, and none of their output, is
#     written inside the checkout. Names, exit codes, output and the put-back
#     paths go to LOOP_HOLDOUT_LOG_DIR/iter-N-holdout.log, outside the
#     repository: $HOME/.claude/loop-holdout/<checkout>-<hash>, or
#     CLADE_LOOP_HOLDOUT_LOG_DIR, refused inside the checkout, another worktree
#     of it, or DIR. loop.log and last-progress (under LOG_DIR, inside the
#     checkout by default) and the supervisor context get counts only; the
#     terminal is told where the log is (_holdout_tell, stderr only).
#   - node_holdout runs after node_verify; a failure keeps the iteration out of
#     goal reconciliation and keeps the run from converging. So does a pass in
#     an iteration whose scenario set changed: it counts once it passes again
#     unchanged, and the end-of-run report names the iteration it changed in.
#   - --resume carries the directory, the baseline fingerprint and the change
#     record through loop_checkpoint.py, which refuses a resume whose
#     --holdout differs from the interrupted run's (holdout_state_*).
#
# Sourced by loop-runner.sh AFTER loop_verify.sh.
# Reads:  HOLDOUT_TIMEOUT, LOG_DIR, STATE_FILE, ITERATION, HOME,
#         CLADE_LOOP_HOLDOUT_LOG_DIR
# Uses:   log_info/log_success/log_warn/log_error (loop-runner.sh),
#         _read_verify_cmd (loop_verify.sh) — asserted below, not assumed.
# Writes: LOOP_HOLDOUT_* only, reached by the caller through the functions in
#         this file.

# ─── The interface with the caller — asserted at source time ──────────
_loop_holdout_require_caller() {
  local missing="" fn
  for fn in "$@"; do
    declare -f "$fn" >/dev/null 2>&1 || missing="$missing $fn"
  done
  if [ -n "$missing" ]; then
    printf 'loop_holdout.sh: sourced by a caller that does not define:%s\n' \
      "$missing" >&2
    return 1
  fi
  return 0
}
if ! _loop_holdout_require_caller log_info log_success log_warn log_error \
    _read_verify_cmd; then
  return 1 2>/dev/null || exit 1
fi

# State, set by holdout_validate and node_holdout. Empty DIR = no holdout.
LOOP_HOLDOUT_DIR=""          # physical path of the holdout directory
LOOP_HOLDOUT_CHECKOUT=""     # physical path of the checkout root (scenario cwd)
LOOP_HOLDOUT_COMMON=""       # physical git common dir of the checkout's repository
LOOP_HOLDOUT_LOG_DIR=""      # physical path of the holdout log, outside the repository
LOOP_HOLDOUT_COUNT=0         # scenarios found at validation
LOOP_HOLDOUT_FINGERPRINT=""  # digest of everything under DIR, for change detection
LOOP_HOLDOUT_CHANGED_AT=""   # iteration a change was last seen in; empty = never
LOOP_HOLDOUT_LAST_ITER=""    # iteration of the last run; empty = never ran
LOOP_HOLDOUT_LAST_TOTAL=0    # scenarios run in the last run
LOOP_HOLDOUT_LAST_FAILED=0   # of those, how many did not exit 0
# ────────────────────────────────────────────────────────────────

# ─── Path helpers (bash 3.2, BSD userland: no realpath, no readlink -f) ──
# Physical directory of DIR, or nothing and status 1.
_holdout_physical_dir() {
  (cd "$1" 2>/dev/null && pwd -P)
}

# Physical path of FILE, following a chain of symlinks by hand.
_holdout_physical_file() {
  local f="$1" t hops=0 d
  while [ -L "$f" ]; do
    hops=$((hops + 1))
    [ "$hops" -le 40 ] || return 1
    t=$(readlink "$f") || return 1
    case "$t" in
      /*) f="$t" ;;
      *)  f="$(dirname "$f")/$t" ;;
    esac
  done
  d=$(_holdout_physical_dir "$(dirname "$f")") || return 1
  printf '%s/%s' "$d" "$(basename "$f")"
}

# Physical form of a directory PATH that need not exist yet: its deepest
# existing ancestor resolved with pwd -P, the missing components appended.
# Status 1 when a component exists but is not a directory, or a missing one is
# "." or "..", which cannot be resolved before the directory exists.
_holdout_physical_target() {
  local p="$1" tail="" base d
  case "$p" in /*) ;; *) p="$PWD/$p" ;; esac
  while [ "${p%/}" != "$p" ] && [ "$p" != / ]; do p="${p%/}"; done
  while [ ! -d "$p" ]; do
    if [ -e "$p" ] || [ -L "$p" ]; then return 1; fi
    base="${p##*/}"
    case "$base" in .|..) return 1 ;; esac
    tail="/$base$tail"
    p="${p%/*}"
    [ -n "$p" ] || p=/
  done
  d=$(_holdout_physical_dir "$p") || return 1
  [ "$d" != / ] || d=""
  if [ -z "$d$tail" ]; then printf '/'; return 0; fi
  printf '%s%s' "$d" "$tail"
}

# Status 0 when PATH is ROOT or lies under it. Both physical. "$2" is quoted
# in the pattern, so glob characters in the path match literally.
_holdout_is_inside() {
  case "$1/" in
    "$2"/*) return 0 ;;
  esac
  return 1
}

# Physical git common dir of the repository holding DIR, or nothing. Two
# worktrees of one repository share it; two separate repositories do not.
_holdout_common_dir() {
  (cd "$1" 2>/dev/null || exit 1
   d=$(git rev-parse --git-common-dir 2>/dev/null) || exit 1
   cd "$d" 2>/dev/null && pwd -P)
}

# _holdout_lands_inside WHAT PATH TOP COMMON → status 0, with the reason on
# stderr, when PATH (physical, need not exist) lies inside the checkout TOP or
# inside another worktree sharing git common dir COMMON.
_holdout_lands_inside() {
  local what="$1" path="$2" top="$3" common="$4" probe there
  if _holdout_is_inside "$path" "$top"; then
    echo "ERROR: --holdout refused: $what would be written inside the repository: $path (checkout $top)." >&2
    return 0
  fi
  probe="$path"
  while [ ! -d "$probe" ]; do probe=$(dirname "$probe"); done
  there=$(_holdout_common_dir "$probe") || there=""
  if [ -n "$common" ] && [ "$there" = "$common" ]; then
    echo "ERROR: --holdout refused: $what would be written inside another worktree of this same repository: $path." >&2
    return 0
  fi
  return 1
}

# Human-facing, terminal only: never tee'd into loop.log, which sits inside
# the checkout by default. Says where the holdout log is.
_holdout_tell() { echo "[$(date '+%H:%M:%S')] [INFO]  $*" >&2; }
# ────────────────────────────────────────────────────────────────

# ─── Scenario discovery ─────────────────────────────────────────
# _holdout_scan DIR ROOT [COMMON] → scenario paths, one per line, byte-sorted.
# Status 1, with the reason on stderr, when a scenario resolves inside ROOT or
# (a symlink) into another worktree sharing git common dir COMMON, a name
# carries a newline, or there are no scenarios at all.
_holdout_scan() {
  local dir="$1" root="$2" common="${3:-}" f phys there n=0 found=""
  for f in "$dir"/*; do
    [ -f "$f" ] && [ -x "$f" ] || continue
    case "$f" in
      *"
"*) echo "ERROR: --holdout: a scenario name in $dir contains a newline" >&2
        return 1 ;;
    esac
    if ! phys=$(_holdout_physical_file "$f"); then
      echo "ERROR: --holdout: cannot resolve scenario $f" >&2
      return 1
    fi
    if _holdout_is_inside "$phys" "$root"; then
      echo "ERROR: --holdout refused: scenario $(basename "$f") resolves inside the repository ($phys)." >&2
      echo "  A worker can rewrite and commit that file; keep the scenario itself outside the checkout." >&2
      return 1
    fi
    # DIR itself was checked against the other worktrees; a symlink can leave it.
    if [ -L "$f" ] && [ -n "$common" ]; then
      there=$(_holdout_common_dir "$(dirname "$phys")") || there=""
      if [ "$there" = "$common" ]; then
        echo "ERROR: --holdout refused: scenario $(basename "$f") resolves into another worktree of this same repository ($phys)." >&2
        echo "  A worker's commit reaches it through the shared history; keep the scenario itself outside every checkout." >&2
        return 1
      fi
    fi
    found="$found$f
"
    n=$((n + 1))
  done
  if [ "$n" -eq 0 ]; then
    echo "ERROR: --holdout: $dir holds no executable scenario (chmod +x a file to make it one)." >&2
    echo "  A holdout that checks nothing would read as a pass." >&2
    return 1
  fi
  printf '%s' "$found" | LC_ALL=C sort
}

# Content digest of FILE (git's object hash: cryptographic, unlike cksum).
_holdout_content_hash() {
  { git hash-object --stdin < "$1"; } 2>/dev/null || echo unreadable
}

# One line per entry read NUL-separated from stdin, paths relative to DIR:
# type, exec bit and content of a file; target (and, for a file, content) of
# a symlink; a directory by its path, so an added or removed one counts.
_holdout_describe_entries() {
  local p x sum
  while IFS= read -r -d '' p; do
    [ "$p" != . ] || continue
    if [ -L "$p" ]; then
      sum=none
      if [ -f "$p" ]; then sum=$(_holdout_content_hash "$p"); fi
      printf 'l %s %s %s\n' "$(readlink "$p")" "$sum" "$p"
    elif [ -d "$p" ]; then
      printf 'd %s\n' "$p"
    elif [ -f "$p" ]; then
      if [ -x "$p" ]; then x=x; else x=-; fi
      printf 'f %s %s %s\n' "$x" "$(_holdout_content_hash "$p")" "$p"
    else
      printf 'o %s\n' "$p"
    fi
  done
}

# A digest of EVERY entry under DIR, recursively — fixtures, expected outputs
# and helpers count as much as the scenarios: a rewritten expected output makes
# a failing check pass as surely as a rewritten check. Any edit, addition,
# removal or chmod changes it. A symlinked directory counts by its target, not
# its contents (find does not follow it). Kept as one digest, not a listing,
# because it travels through the checkpoint on a command line.
_holdout_fingerprint() {
  local listing digest
  if [ ! -d "$LOOP_HOLDOUT_DIR" ]; then
    printf 'missing'
    return 0
  fi
  listing=$(cd "$LOOP_HOLDOUT_DIR" 2>/dev/null &&
    find . -print0 2>/dev/null | _holdout_describe_entries | LC_ALL=C sort)
  digest=$(printf '%s\n' "$listing" | git hash-object --stdin 2>/dev/null) || digest=""
  if [ -z "$digest" ]; then
    digest="cksum:$(printf '%s\n' "$listing" | cksum)"
  fi
  printf '%s' "$digest"
}
# ────────────────────────────────────────────────────────────────

# ─── Scenario watchdog ──────────────────────────────────────────
# A hung scenario must not stall the loop, and stock macOS has neither timeout
# nor gtimeout: loop-runner.sh's _timeout then runs the command with no bound
# at all. So the bound is a watchdog of its own, in python3, which the loop
# needs anyway (git_identity.py, loop_checkpoint.py). The scenario runs in a
# new session; at the bound its whole process group gets SIGTERM, then SIGKILL
# GRACE seconds later, so a child it left running cannot go on writing into the
# checkout after the put-back. GNU timeout is not used even where it exists:
# without -k it never kills a scenario that ignores SIGTERM, and one watchdog
# on every platform is one path to test. Exit 124 = cut off, as timeout(1).
# A signal to the loop (Ctrl-C, kill) is passed on to the scenario's group.
_HOLDOUT_WATCHDOG_PY='
import os
import signal
import subprocess
import sys

GRACE = 5


def main():
    limit = int(sys.argv[1])
    try:
        child = subprocess.Popen(sys.argv[2:], start_new_session=True)
    except OSError as exc:
        sys.stderr.write("holdout watchdog: cannot run %s: %s\n" % (sys.argv[2], exc))
        return 126

    def kill_group(sig):
        try:
            os.killpg(child.pid, sig)
        except OSError:
            pass

    def forward(signum, _frame):
        kill_group(signum)
        os._exit(128 + signum)

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, forward)
    try:
        status = child.wait(timeout=limit)
    except subprocess.TimeoutExpired:
        kill_group(signal.SIGTERM)
        try:
            child.wait(timeout=GRACE)
        except subprocess.TimeoutExpired:
            pass
        kill_group(signal.SIGKILL)
        child.wait()
        sys.stderr.write("holdout watchdog: cut off after %ss\n" % limit)
        return 124
    return status if status >= 0 else 128 - status


sys.exit(main())
'

# _holdout_bounded SECONDS CMD... — CMD's exit status, or 124 when cut off.
_holdout_bounded() {
  python3 -c "$_HOLDOUT_WATCHDOG_PY" "$@"
}
# ────────────────────────────────────────────────────────────────

# ─── Validation — once, before anything runs (main, dry-run included) ──
# Messages go to stderr with echo, not log_*: LOG_DIR may not exist yet, and
# a refusal must not leave a log directory behind. Nothing is created here:
# the holdout log directory is made by node_holdout, so --dry-run writes none.
holdout_validate() {
  local given="$1" abs top top_abs here_common there_common list f skipped=0 timeout_ok
  local log_want log_abs ckpt_abs key
  if [ -z "$given" ]; then
    return 0
  fi
  # A bound of 0 is no bound at all, and a non-number would make every
  # scenario "time out" — both read as a gate that is not there.
  case "${HOLDOUT_TIMEOUT:-}" in
    ''|*[!0-9]*) timeout_ok=false ;;
    *) if [ "$HOLDOUT_TIMEOUT" -gt 0 ]; then timeout_ok=true; else timeout_ok=false; fi ;;
  esac
  if [ "$timeout_ok" != "true" ]; then
    echo "ERROR: --holdout: CLADE_LOOP_HOLDOUT_TIMEOUT must be a whole number of seconds above 0 (got '${HOLDOUT_TIMEOUT:-}')." >&2
    return 1
  fi
  # The watchdog that bounds each scenario is python3 (_holdout_bounded).
  # Fail closed: an unbounded scenario that hangs stalls the whole loop.
  if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: --holdout needs python3: its watchdog is what cuts off a scenario that hangs, and without one a hung scenario would stall the loop." >&2
    return 1
  fi
  if [ ! -d "$given" ]; then
    echo "ERROR: --holdout: not a directory: $given" >&2
    return 1
  fi
  if ! abs=$(_holdout_physical_dir "$given"); then
    echo "ERROR: --holdout: cannot enter $given" >&2
    return 1
  fi
  top=$(git rev-parse --show-toplevel 2>/dev/null) || top=""
  if [ -z "$top" ] || ! top_abs=$(_holdout_physical_dir "$top"); then
    echo "ERROR: --holdout needs the loop to run inside a git checkout (git rev-parse --show-toplevel failed in $(pwd))." >&2
    return 1
  fi
  if _holdout_is_inside "$abs" "$top_abs"; then
    echo "ERROR: --holdout refused: $abs resolves inside the repository ($top_abs)." >&2
    echo "  A scenario a worker can edit and commit is not held out. Move the directory outside the checkout." >&2
    return 1
  fi
  here_common=$(_holdout_common_dir "$top_abs") || here_common=""
  there_common=$(_holdout_common_dir "$abs") || there_common=""
  if [ -n "$here_common" ] && [ "$here_common" = "$there_common" ]; then
    echo "ERROR: --holdout refused: $abs is inside another worktree of this same repository ($here_common)." >&2
    echo "  A worker's commit reaches it through the shared history. Move it outside every checkout of this repository." >&2
    return 1
  fi
  list=$(_holdout_scan "$abs" "$top_abs" "$here_common") || return 1

  # The holdout log names DIR and every scenario and keeps their output, so it
  # goes where neither a worker's `git add -A` nor the next prompt reaches.
  log_want="${CLADE_LOOP_HOLDOUT_LOG_DIR:-}"
  if [ -z "$log_want" ]; then
    if [ -z "${HOME:-}" ]; then
      echo "ERROR: --holdout: HOME is not set, so the holdout log has no default place; set CLADE_LOOP_HOLDOUT_LOG_DIR to a directory outside the repository." >&2
      return 1
    fi
    key=$(printf '%s' "$top_abs" | git hash-object --stdin 2>/dev/null | cut -c1-12)
    log_want="$HOME/.claude/loop-holdout/$(basename "$top_abs")-${key:-0}"
  fi
  if ! log_abs=$(_holdout_physical_target "$log_want"); then
    echo "ERROR: --holdout: cannot use $log_want for the holdout log: part of it is not a directory, or it names . or .. below a directory that does not exist yet." >&2
    return 1
  fi
  if _holdout_lands_inside "the holdout log (it names every scenario and keeps their output)" \
      "$log_abs" "$top_abs" "$here_common"; then
    echo "  Set CLADE_LOOP_HOLDOUT_LOG_DIR to a directory outside every checkout of this repository." >&2
    return 1
  fi
  if _holdout_is_inside "$log_abs" "$abs"; then
    echo "ERROR: --holdout refused: the holdout log ($log_abs) would be written inside the holdout directory, where every write reads as a changed scenario set." >&2
    echo "  Set CLADE_LOOP_HOLDOUT_LOG_DIR to a directory outside it." >&2
    return 1
  fi
  # The resume checkpoint records DIR as well (loop_checkpoint.py, under $HOME).
  if [ -n "${HOME:-}" ] && ckpt_abs=$(_holdout_physical_target "$HOME/.claude/loop-checkpoints") &&
     _holdout_lands_inside "the resume checkpoint (it records the holdout directory)" \
       "$ckpt_abs" "$top_abs" "$here_common"; then
    echo "  Run the loop with HOME outside the checkout." >&2
    return 1
  fi

  LOOP_HOLDOUT_DIR="$abs"
  LOOP_HOLDOUT_CHECKOUT="$top_abs"
  LOOP_HOLDOUT_COMMON="$here_common"
  LOOP_HOLDOUT_LOG_DIR="$log_abs"
  LOOP_HOLDOUT_COUNT=$(printf '%s\n' "$list" | grep -c .) || LOOP_HOLDOUT_COUNT=0
  LOOP_HOLDOUT_FINGERPRINT=$(_holdout_fingerprint)

  for f in "$abs"/*; do
    if [ -f "$f" ] && [ ! -x "$f" ]; then
      skipped=$((skipped + 1))
    fi
  done
  if [ "$skipped" -gt 0 ]; then
    echo "NOTE: --holdout: $skipped non-executable file(s) in $abs are not scenarios and will not run." >&2
  fi
  return 0
}

# holdout_warn_named GIVEN FILE... — warn when a file names the holdout.
# The goal file and the --context file are pasted into the supervisor prompt
# whole, so a holdout path written in either tells the workers where the
# scenarios live, and the counts-only context means nothing. A warning, not a
# refusal: the /loop skill already forbids it, and this checks that it held.
# Searched: DIR as given (trailing slashes dropped), its physical path, and the
# ~/ form of each under $HOME; only forms holding a "/", so a bare name does
# not fire on prose. Scenario names are not searched for the same reason: a
# short one like `check` would.
holdout_warn_named() {
  local given="${1%/}" file form forms="" found
  shift
  [ -n "$given" ] && [ -n "${LOOP_HOLDOUT_DIR:-}" ] || return 0
  for form in "$given" "$LOOP_HOLDOUT_DIR"; do
    forms="$forms$form"$'\n'
    if [ -n "${HOME:-}" ]; then
      case "$form" in
        "$HOME"/*) forms="$forms~/${form#"$HOME"/}"$'\n' ;;
      esac
    fi
  done
  for file in "$@"; do
    [ -n "$file" ] && [ -f "$file" ] || continue
    found=""
    while IFS= read -r form; do
      case "$form" in */*) ;; *) continue ;; esac
      case "$found" in *"[$form]"*) continue ;; esac
      if grep -qF -- "$form" "$file" 2>/dev/null; then
        found="${found}[$form]"
      fi
    done <<EOF
$forms
EOF
    if [ -n "$found" ]; then
      echo "WARNING: --holdout: $file names the holdout directory ($found)." >&2
      echo "  It is pasted into the supervisor prompt, so the workers learn where the scenarios live. Remove the path from it." >&2
    fi
  done
  return 0
}

holdout_enabled() {
  [ -n "$LOOP_HOLDOUT_DIR" ]
}

# One line for the start banner, which goes to loop.log: counts only.
holdout_summary() {
  if holdout_enabled; then
    printf '%s scenario(s), outside the repository' "$LOOP_HOLDOUT_COUNT"
  else
    printf 'none'
  fi
}

# The dry-run preview: printed, never logged, so it may name DIR.
holdout_preview() {
  if holdout_enabled; then
    printf '%s scenario(s) in %s (outside the repository); holdout log in %s' \
      "$LOOP_HOLDOUT_COUNT" "$LOOP_HOLDOUT_DIR" "$LOOP_HOLDOUT_LOG_DIR"
  else
    printf 'none'
  fi
}

# After the start banner: where the names and output go, on the terminal only.
holdout_announce() {
  holdout_enabled || return 0
  _holdout_tell "  Holdout log:  $LOOP_HOLDOUT_LOG_DIR (outside the repository: scenario names, exit codes and output)"
}
# ────────────────────────────────────────────────────────────────

# ─── Checkout guard — what a scenario writes never reaches a commit ──
# Scenarios run in the checkout, and node_commit_changes then sweeps whatever
# is left there into a commit, whose file names reach the next supervisor
# prompt through `git diff --stat`. So node_holdout captures the checkout
# before the first scenario and puts back every path the scenarios changed.
#
# The worktree capture is the tree `git stash -u` would take, with no ref
# touched: built in a scratch copy of the index (add -A, then write-tree), so
# tracked and untracked files, modes and symlinks all count. Ignored files are
# outside it, as they are outside every commit. The real index is captured as a
# byte copy plus a digest of what git reads from it (_holdout_index_state), and
# put back from the copy — never with read-tree, which drops skip-worktree and
# intent-to-add entries: in a sparse checkout every skipped file would then
# read as deleted, and the commit sweep would commit the deletions.
# The loop's own bookkeeping (.claude/, LOG_DIR, STATE_FILE) is never swept by
# node_commit_changes, so it is never put back either (_holdout_changes):
# log_* writes LOG_DIR while the scenarios run, and a human may edit the goal,
# raise --stop into STATE_FILE or set the interrupt flag under .claude/ at that
# moment too.
# Everything here runs with cwd = the checkout root, and the scratch files
# live in the git dir, never in /tmp.

# Absolute path of NAME in the (per-worktree) git dir.
_holdout_git_path() {
  local p
  p=$(git rev-parse --git-path "$1" 2>/dev/null) || return 1
  case "$p" in
    /*) ;;
    *) p="$PWD/$p" ;;
  esac
  printf '%s' "$p"
}
_holdout_tmp_index()    { _holdout_git_path "clade-holdout-index.$$"; }
_holdout_index_backup() { _holdout_git_path "clade-holdout-index-backup.$$"; }

# A runner path as a repo-relative path, or nothing when it lies outside.
_holdout_relpath() {
  case "$1" in
    "$LOOP_HOLDOUT_CHECKOUT"/*) printf '%s' "${1#"$LOOP_HOLDOUT_CHECKOUT"/}" ;;
    /*) ;;
    *) printf '%s' "${1#./}" ;;
  esac
}

# Digest of the real index as git reads it: each entry's mode, object, stage
# and path, its skip-worktree / assume-unchanged tag (ls-files -v), and which
# entries are intent-to-add (diff-files lists only those as added). Stat data
# is left out, so a scenario that only ran `git status`, which may rewrite the
# index file to refresh it, changes nothing. "absent" when there is no index.
_holdout_index_state() {
  local index
  index=$(_holdout_git_path index) || return 1
  if [ ! -e "$index" ]; then
    printf 'absent'
    return 0
  fi
  (
    set -o pipefail
    { git ls-files -s -v -z && printf 'intent-to-add\0' &&
      git diff-files --name-only -z --diff-filter=A; } | git hash-object --stdin
  )
}

# The worktree as a tree object, built in a scratch copy of the index. No
# exclude pathspecs: `git add` exits 1 when one names an existing ignored
# directory, which .claude/ and logs/ usually are.
_holdout_worktree_tree() {
  local tmp wt=""
  tmp=$(_holdout_tmp_index) || return 1
  # A copy of the real index keeps its stat cache, so add -A rehashes only
  # what changed rather than the whole tree.
  if ! cp "$(_holdout_git_path index)" "$tmp" 2>/dev/null; then
    GIT_INDEX_FILE="$tmp" git read-tree HEAD 2>/dev/null ||
      GIT_INDEX_FILE="$tmp" git read-tree --empty 2>/dev/null || { rm -f "$tmp"; return 1; }
  fi
  if GIT_INDEX_FILE="$tmp" git add -A >/dev/null 2>&1; then
    wt=$(GIT_INDEX_FILE="$tmp" git write-tree 2>/dev/null) || wt=""
  fi
  rm -f "$tmp"
  [ -n "$wt" ] || return 1
  printf '%s' "$wt"
}

# → "<index-state> <worktree-tree>"; status 1 when git cannot take it.
_holdout_snapshot() {
  local idx wt
  idx=$(_holdout_index_state) || return 1
  wt=$(_holdout_worktree_tree) || return 1
  printf '%s %s' "$idx" "$wt"
}

# Before the scenarios: a snapshot, and a byte copy of the index for the
# put-back. Status 1 (nothing kept) when either cannot be taken.
_holdout_capture() {
  local snap index backup
  snap=$(_holdout_snapshot) || return 1
  backup=$(_holdout_index_backup) || return 1
  rm -f "$backup"
  if [ "${snap%% *}" != absent ]; then
    index=$(_holdout_git_path index) || return 1
    cp -p "$index" "$backup" 2>/dev/null || { rm -f "$backup"; return 1; }
  fi
  printf '%s' "$snap"
}

# The real index back to the bytes _holdout_capture copied (or back to no
# index, when there was none), under git's own index.lock so a concurrent git
# command fails rather than interleaves.
_holdout_index_put_back() {
  local before="$1" index backup lock
  index=$(_holdout_git_path index) || return 1
  backup=$(_holdout_index_backup) || return 1
  lock="$index.lock"
  if ! (set -C; : > "$lock") 2>/dev/null; then
    echo "cannot take $lock: another git command holds the index" >&2
    return 1
  fi
  if [ "$before" = absent ]; then
    rm -f "$index" && rm -f "$lock" && return 0
  elif cp "$backup" "$lock" 2>/dev/null && mv -f "$lock" "$index"; then
    return 0
  fi
  rm -f "$lock"
  return 1
}

# _holdout_changes FILTER BEFORE NOW → NUL-separated paths that git's
# --diff-filter FILTER selects between two worktree trees, minus the loop's
# own bookkeeping — the same exclusions node_commit_changes makes.
_holdout_changes() {
  local log state p
  log=$(_holdout_relpath "${LOG_DIR%/}")
  state=$(_holdout_relpath "$STATE_FILE")
  git diff-tree -r -z --no-renames --diff-filter="$1" --name-only "$2" "$3" |
    while IFS= read -r -d '' p; do
      case "$p" in .claude|.claude/*) continue ;; esac
      if [ -n "$log" ]; then
        case "$p" in "$log"|"$log"/*) continue ;; esac
      fi
      if [ -n "$state" ] && [ "$p" = "$state" ]; then continue; fi
      printf '%s\0' "$p"
    done
}

# _holdout_restore CAPTURE → how many changes were put back, on stdout; the
# paths on stderr, created ones first, then changed, retyped or deleted ones,
# then the index.
_holdout_restore() {
  local idx_before="${1%% *}" wt_before="${1#* }" now idx_now wt_now tmp n=0 p d
  now=$(_holdout_snapshot) || return 1
  idx_now="${now%% *}"
  wt_now="${now#* }"
  if [ "$wt_now" != "$wt_before" ]; then
    n=$(_holdout_changes AMTD "$wt_before" "$wt_now" | tr -cd '\000' | wc -c | tr -d ' ')
    _holdout_changes A "$wt_before" "$wt_now" | tr '\000' '\n' | sed 's/^/created: /' >&2
    _holdout_changes MTD "$wt_before" "$wt_now" | tr '\000' '\n' | sed 's/^/changed: /' >&2
    # Created first, so a file the scenario turned into a directory is free
    # again before it is put back.
    _holdout_changes A "$wt_before" "$wt_now" |
      while IFS= read -r -d '' p; do
        rm -f -- "$p"
        d=$(dirname -- "$p")
        while [ "$d" != "." ] && rmdir -- "$d" 2>/dev/null; do d=$(dirname -- "$d"); done
      done
    # Changed, retyped or deleted: back from the capture, worker leftovers included.
    tmp=$(_holdout_tmp_index) || return 1
    if ! GIT_INDEX_FILE="$tmp" git read-tree "$wt_before" 2>/dev/null; then
      rm -f "$tmp"
      return 1
    fi
    _holdout_changes MTD "$wt_before" "$wt_now" |
      GIT_INDEX_FILE="$tmp" git checkout-index -f -z --stdin
    rm -f "$tmp"
  fi
  if [ "$idx_now" != "$idx_before" ]; then
    echo "changed: (the git index)" >&2
    _holdout_index_put_back "$idx_before" || return 1
    n=$((n + 1))
  fi
  printf '%s' "$n"
}
# ────────────────────────────────────────────────────────────────

# ─── [DET] NODE: HOLDOUT ────────────────────────────────────────
# This iteration's holdout log, created outside the repository; /dev/null when
# it cannot be written, so nothing falls back to a path inside the checkout.
_holdout_detail_log() {
  local f="$LOOP_HOLDOUT_LOG_DIR/iter-${ITERATION:-0}-holdout.log"
  if (umask 077 && mkdir -p "$LOOP_HOLDOUT_LOG_DIR" && : > "$f") 2>/dev/null; then
    printf '%s' "$f"
  else
    printf '/dev/null'
  fi
}

# Runs every scenario. Status 0 when all pass in an iteration whose scenario
# set did not change (or there is no holdout), 1 otherwise. loop.log sits
# inside the checkout by default, so it gets a scenario's position and result,
# never its name; the name, exit code and output go to $detail.
node_holdout() {
  holdout_enabled || return 0
  log_info "[DET] holdout"

  local fp list f name rc n total=0 failed=0 cut=0 cap restored detail
  LOOP_HOLDOUT_LAST_ITER="${ITERATION:-0}"
  detail=$(_holdout_detail_log)
  if [ "$detail" = /dev/null ]; then
    log_warn "holdout: cannot write the holdout log outside the repository — scenario names and output are not kept this iteration"
  fi

  fp=$(_holdout_fingerprint)
  if [ "$fp" != "$LOOP_HOLDOUT_FINGERPRINT" ]; then
    log_warn "HOLDOUT CHANGED mid-run: a file under the holdout directory was added, removed or edited since the last check. Check who changed it before trusting this result; this iteration's holdout does not count as acceptance."
    printf '=== the holdout directory changed since the last check\n' >> "$detail"
    LOOP_HOLDOUT_FINGERPRINT="$fp"
    LOOP_HOLDOUT_CHANGED_AT="${ITERATION:-0}"
  fi

  if ! list=$(_holdout_scan "$LOOP_HOLDOUT_DIR" "$LOOP_HOLDOUT_CHECKOUT" "$LOOP_HOLDOUT_COMMON" 2>>"$detail"); then
    log_error "holdout: the scenario set can no longer be run — counted as failed"
    [ "$detail" = /dev/null ] || _holdout_tell "holdout: the reason is in $detail"
    LOOP_HOLDOUT_LAST_TOTAL=0
    LOOP_HOLDOUT_LAST_FAILED=1
    return 1
  fi
  n=$(printf '%s\n' "$list" | grep -c .) || n=0

  cap=$(cd "$LOOP_HOLDOUT_CHECKOUT" && _holdout_capture) || cap=""
  if [ -z "$cap" ]; then
    log_warn "holdout: could not capture the checkout first — anything a scenario writes there is not put back this iteration"
  fi

  while IFS= read -r f; do
    [ -n "$f" ] || continue
    total=$((total + 1))
    name=$(basename "$f")
    rc=0
    printf '=== %s\n' "$name" >> "$detail"
    (cd "$LOOP_HOLDOUT_CHECKOUT" && _holdout_bounded "${HOLDOUT_TIMEOUT:-120}" "$f") \
      < /dev/null >> "$detail" 2>&1 || rc=$?
    if [ "$rc" -eq 0 ]; then
      printf '=== %s: PASS\n' "$name" >> "$detail"
      log_info "  holdout scenario $total of $n: PASS"
    elif [ "$rc" -eq 124 ]; then
      failed=$((failed + 1))
      cut=$((cut + 1))
      printf '=== %s: FAIL (cut off after %ss)\n' "$name" "${HOLDOUT_TIMEOUT:-120}" >> "$detail"
      log_warn "  holdout scenario $total of $n: FAIL (cut off after ${HOLDOUT_TIMEOUT:-120}s)"
    else
      failed=$((failed + 1))
      printf '=== %s: FAIL (exit %s)\n' "$name" "$rc" >> "$detail"
      log_warn "  holdout scenario $total of $n: FAIL"
    fi
  done <<< "$list"

  if [ -n "$cap" ]; then
    printf '=== put back after the scenarios ran\n' >> "$detail"
    restored=$(cd "$LOOP_HOLDOUT_CHECKOUT" && _holdout_restore "$cap" 2>>"$detail") || restored=""
    (cd "$LOOP_HOLDOUT_CHECKOUT" && rm -f "$(_holdout_index_backup)")
    case "$restored" in
      "") log_error "holdout: could not put back what the scenarios wrote in the checkout — this iteration's commit may carry it" ;;
      0) ;;
      *) log_warn "holdout: the scenarios wrote $restored change(s) into the checkout — put back so no commit or prompt carries them (paths in the holdout log). A scenario must not write into the checkout." ;;
    esac
  fi

  LOOP_HOLDOUT_LAST_TOTAL=$total
  LOOP_HOLDOUT_LAST_FAILED=$failed
  [ "$detail" = /dev/null ] || _holdout_tell "holdout: names, exit codes and output in $detail"
  if [ "$failed" -gt 0 ]; then
    if [ "$cut" -gt 0 ]; then
      log_warn "holdout: $failed of $total scenario(s) FAILED ($cut cut off after ${HOLDOUT_TIMEOUT:-120}s)"
    else
      log_warn "holdout: $failed of $total scenario(s) FAILED"
    fi
    return 1
  fi
  if holdout_changed_this_check; then
    log_warn "holdout: all $total scenario(s) passed, but the scenario set changed in this iteration — not counted as acceptance until it passes again unchanged"
    return 1
  fi
  log_success "holdout: all $total scenario(s) passed"
  return 0
}

# Status 0 when the last check saw the scenario set change.
holdout_changed_this_check() {
  [ -n "$LOOP_HOLDOUT_CHANGED_AT" ] && [ "$LOOP_HOLDOUT_CHANGED_AT" = "$LOOP_HOLDOUT_LAST_ITER" ]
}

# The proxy-gamed signal: the visible, in-repo gate is green and the held-out
# one is not. Called with test_sample's status after node_holdout. Silent when
# no verify_cmd is declared — "passed" would then mean "skipped".
holdout_note_divergence() {
  local test_result="$1" what
  holdout_enabled || return 0
  [ "$LOOP_HOLDOUT_LAST_ITER" = "${ITERATION:-0}" ] || return 0
  [ "$LOOP_HOLDOUT_LAST_FAILED" -gt 0 ] || return 0
  [ "$test_result" -eq 0 ] || return 0
  [ -n "$(_read_verify_cmd)" ] || return 0
  if [ "$LOOP_HOLDOUT_LAST_TOTAL" -eq 0 ]; then
    what="the held-out scenarios cannot be run"
  else
    what="$LOOP_HOLDOUT_LAST_FAILED of $LOOP_HOLDOUT_LAST_TOTAL held-out scenario(s) fail"
  fi
  log_error "HOLDOUT FAILED — visible verify_cmd passed: $what while the in-repo gate is green. The visible gate does not cover what the holdout checks, or was rewritten to pass."
  return 0
}

# Convergence needs held-out acceptance too: workers are told not to edit the
# goal file, but nothing stops one from ticking its boxes, and a goal that was
# complete before the run never reaches reconciliation at all. Reuses this
# iteration's result when node_holdout already ran; otherwise runs it now.
# Status 0 = convergence is blocked.
holdout_blocks_convergence() {
  holdout_enabled || return 1
  if [ "$LOOP_HOLDOUT_LAST_ITER" != "${ITERATION:-0}" ]; then
    node_holdout || true
  fi
  if [ "$LOOP_HOLDOUT_LAST_FAILED" -gt 0 ]; then
    if [ "$LOOP_HOLDOUT_LAST_TOTAL" -eq 0 ]; then
      log_warn "Goal checklist is complete, but the held-out acceptance scenarios cannot be run — not converged"
    else
      log_warn "Goal checklist is complete, but held-out acceptance fails ($LOOP_HOLDOUT_LAST_FAILED of $LOOP_HOLDOUT_LAST_TOTAL) — not converged"
    fi
    return 0
  fi
  if holdout_changed_this_check; then
    log_warn "Goal checklist is complete, but the held-out scenario set changed in this iteration — not converged until it passes again unchanged"
    return 0
  fi
  return 1
}
# ────────────────────────────────────────────────────────────────

# ─── What the supervisor sees — counts, never names ─────────────
# Folded into .claude/loop-context.md by node_hydrate_context. Everything in
# that file reaches the supervisor prompt, so nothing here may carry a
# scenario's name, path, exit code or output.
holdout_context_block() {
  holdout_enabled || return 0
  [ -n "$LOOP_HOLDOUT_LAST_ITER" ] || return 0
  echo ""
  echo "## Held-out acceptance"
  if [ "$LOOP_HOLDOUT_LAST_TOTAL" -eq 0 ]; then
    echo "Last check (iteration $LOOP_HOLDOUT_LAST_ITER): the held-out acceptance scenarios could not be run. Goal items stay unreconciled until they run and pass."
  elif [ "$LOOP_HOLDOUT_LAST_FAILED" -gt 0 ]; then
    echo "Last check (iteration $LOOP_HOLDOUT_LAST_ITER): $LOOP_HOLDOUT_LAST_FAILED of $LOOP_HOLDOUT_LAST_TOTAL held-out acceptance scenario(s) FAILED. Goal items stay unreconciled, and the run cannot converge, until every one passes."
  elif holdout_changed_this_check; then
    echo "Last check (iteration $LOOP_HOLDOUT_LAST_ITER): all $LOOP_HOLDOUT_LAST_TOTAL held-out acceptance scenario(s) passed, but the held-out set changed during that iteration, so the pass does not count yet. Goal items stay unreconciled until the scenarios pass again unchanged."
  else
    echo "Last check (iteration $LOOP_HOLDOUT_LAST_ITER): all $LOOP_HOLDOUT_LAST_TOTAL held-out acceptance scenario(s) passed."
  fi
  echo "These scenarios are withheld from this prompt by design. Meet the goal as written; do not plan work that looks for or edits them."
}

# One line for the end-of-run report and last-progress (counts only: both
# are under LOG_DIR, inside the checkout by default).
holdout_report_line() {
  holdout_enabled || return 0
  local line
  if [ -z "$LOOP_HOLDOUT_LAST_ITER" ]; then
    line='configured, never ran'
  elif [ "$LOOP_HOLDOUT_LAST_TOTAL" -eq 0 ]; then
    line="the scenarios could not be run at iteration $LOOP_HOLDOUT_LAST_ITER"
  elif [ "$LOOP_HOLDOUT_LAST_FAILED" -eq 0 ]; then
    line="all $LOOP_HOLDOUT_LAST_TOTAL scenario(s) passed at iteration $LOOP_HOLDOUT_LAST_ITER"
  else
    line="$LOOP_HOLDOUT_LAST_FAILED of $LOOP_HOLDOUT_LAST_TOTAL scenario(s) failed at iteration $LOOP_HOLDOUT_LAST_ITER"
  fi
  # The tamper signal has to reach --status and the report, not only one WARN
  # line in loop.log: a rewritten scenario passes, and the run then converges.
  if [ -n "$LOOP_HOLDOUT_CHANGED_AT" ]; then
    line="$line; scenario set CHANGED mid-run at iteration $LOOP_HOLDOUT_CHANGED_AT — check who changed it"
  fi
  printf '%s' "$line"
}
# ────────────────────────────────────────────────────────────────

# ─── Checkpoint state — carried across --resume by loop_checkpoint.py ──
# The directory is part of the checkpoint's identity: a resume without the
# same --holdout would otherwise reconcile and converge with the gate off.
# The fingerprint is the baseline the next check compares against, so a
# scenario edited between the last check and the crash is still reported.
holdout_state_dir()         { printf '%s' "$LOOP_HOLDOUT_DIR"; }
holdout_state_fingerprint() { printf '%s' "$LOOP_HOLDOUT_FINGERPRINT"; }
holdout_state_changed_at()  { printf '%s' "$LOOP_HOLDOUT_CHANGED_AT"; }
# holdout_state_restore FINGERPRINT CHANGED_AT — after a matched recovery.
holdout_state_restore() {
  holdout_enabled || return 0
  if [ -n "$1" ]; then
    LOOP_HOLDOUT_FINGERPRINT="$1"
  fi
  LOOP_HOLDOUT_CHANGED_AT="$2"
}
# ────────────────────────────────────────────────────────────────
