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
# or write any absolute path, this directory included. This makes the
# scenarios harder to rewrite, not impossible to rewrite: they are outside
# every commit a worker makes, their names and paths never enter a prompt, and
# a change to them mid-run is reported. It is not a sandbox.
#
# Contract:
#   - DIR must resolve (cd DIR && pwd -P — no realpath dependency) outside
#     `git rev-parse --show-toplevel`, and outside every other worktree of the
#     same repository. A scenario that is a symlink resolving into the
#     repository is refused too.
#   - A scenario is a top-level, executable, non-hidden regular file in DIR.
#     Other files are notes and are not run. Zero scenarios is refused: a
#     holdout that checks nothing would read as a pass.
#   - Each scenario runs with cwd = the checkout root and stdin closed;
#     exit 0 = satisfied. Bounded by HOLDOUT_TIMEOUT seconds each.
#   - node_holdout runs after node_verify; a failure keeps the iteration out of
#     goal reconciliation and keeps the run from converging.
#   - The supervisor sees counts only (holdout_context_block). Names, exit
#     codes and output go to the human-facing log: loop.log and
#     $LOG_DIR/iter-N-holdout.log.
#
# Sourced by loop-runner.sh AFTER loop_verify.sh.
# Reads:  HOLDOUT_TIMEOUT, LOG_DIR, ITERATION
# Uses:   log_info/log_success/log_warn/log_error, _timeout (loop-runner.sh),
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
    _timeout _read_verify_cmd; then
  return 1 2>/dev/null || exit 1
fi

# State, set by holdout_validate and node_holdout. Empty DIR = no holdout.
LOOP_HOLDOUT_DIR=""          # physical path of the holdout directory
LOOP_HOLDOUT_CHECKOUT=""     # physical path of the checkout root (scenario cwd)
LOOP_HOLDOUT_COUNT=0         # scenarios found at validation
LOOP_HOLDOUT_FINGERPRINT=""  # names + cksums at validation, for change detection
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
# ────────────────────────────────────────────────────────────────

# ─── Scenario discovery ─────────────────────────────────────────
# _holdout_scan DIR ROOT → scenario paths, one per line, byte-sorted.
# Status 1, with the reason on stderr, when a scenario resolves inside ROOT,
# a name carries a newline, or there are no scenarios at all.
_holdout_scan() {
  local dir="$1" root="$2" f phys n=0 found=""
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

# Names and cksums of the scenario set, one line each. Any edit, addition or
# removal changes it.
_holdout_fingerprint() {
  local list f
  list=$(_holdout_scan "$LOOP_HOLDOUT_DIR" "$LOOP_HOLDOUT_CHECKOUT" 2>/dev/null) || {
    echo "unscannable"
    return 0
  }
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    printf '%s %s\n' "$(basename "$f")" "$(cksum < "$f" 2>/dev/null || echo unreadable)"
  done <<< "$list"
}
# ────────────────────────────────────────────────────────────────

# ─── Validation — once, before anything runs (main, dry-run included) ──
# Messages go to stderr with echo, not log_*: LOG_DIR may not exist yet, and
# a refusal must not leave a log directory behind.
holdout_validate() {
  local given="$1" abs top top_abs here_common there_common list f skipped=0
  if [ -z "$given" ]; then
    return 0
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
  list=$(_holdout_scan "$abs" "$top_abs") || return 1

  LOOP_HOLDOUT_DIR="$abs"
  LOOP_HOLDOUT_CHECKOUT="$top_abs"
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

holdout_enabled() {
  [ -n "$LOOP_HOLDOUT_DIR" ]
}

# One line for the dry-run preview and the start banner (human-facing).
holdout_summary() {
  if holdout_enabled; then
    printf '%s scenario(s) in %s (outside the repository)' \
      "$LOOP_HOLDOUT_COUNT" "$LOOP_HOLDOUT_DIR"
  else
    printf 'none'
  fi
}
# ────────────────────────────────────────────────────────────────

# ─── [DET] NODE: HOLDOUT ────────────────────────────────────────
# Runs every scenario. Status 0 when all pass (or no holdout), 1 otherwise.
node_holdout() {
  holdout_enabled || return 0
  log_info "[DET] holdout"

  local fp list f name rc total=0 failed=0
  local detail="$LOG_DIR/iter-${ITERATION:-0}-holdout.log"
  : > "$detail"

  fp=$(_holdout_fingerprint)
  if [ "$fp" != "$LOOP_HOLDOUT_FINGERPRINT" ]; then
    log_warn "HOLDOUT CHANGED mid-run: a scenario was added, removed or edited since the run started. Check who changed it before trusting this result."
    LOOP_HOLDOUT_FINGERPRINT="$fp"
  fi

  if ! list=$(_holdout_scan "$LOOP_HOLDOUT_DIR" "$LOOP_HOLDOUT_CHECKOUT" 2>>"$detail"); then
    log_error "holdout: the scenario set can no longer be run (see $detail) — counted as failed"
    LOOP_HOLDOUT_LAST_ITER="${ITERATION:-0}"
    LOOP_HOLDOUT_LAST_TOTAL=0
    LOOP_HOLDOUT_LAST_FAILED=1
    return 1
  fi

  while IFS= read -r f; do
    [ -n "$f" ] || continue
    total=$((total + 1))
    name=$(basename "$f")
    rc=0
    printf '=== %s\n' "$name" >> "$detail"
    (cd "$LOOP_HOLDOUT_CHECKOUT" && _timeout "${HOLDOUT_TIMEOUT:-120}" "$f") \
      < /dev/null >> "$detail" 2>&1 || rc=$?
    if [ "$rc" -eq 0 ]; then
      printf '=== %s: PASS\n' "$name" >> "$detail"
      log_info "  holdout PASS: $name"
    else
      failed=$((failed + 1))
      if [ "$rc" -eq 124 ]; then
        printf '=== %s: FAIL (timed out after %ss)\n' "$name" "${HOLDOUT_TIMEOUT:-120}" >> "$detail"
        log_warn "  holdout FAIL: $name (timed out after ${HOLDOUT_TIMEOUT:-120}s)"
      else
        printf '=== %s: FAIL (exit %s)\n' "$name" "$rc" >> "$detail"
        log_warn "  holdout FAIL: $name (exit $rc)"
      fi
    fi
  done <<< "$list"

  LOOP_HOLDOUT_LAST_ITER="${ITERATION:-0}"
  LOOP_HOLDOUT_LAST_TOTAL=$total
  LOOP_HOLDOUT_LAST_FAILED=$failed
  if [ "$failed" -eq 0 ]; then
    log_success "holdout: all $total scenario(s) passed"
    return 0
  fi
  log_warn "holdout: $failed of $total scenario(s) FAILED — details in $detail"
  return 1
}

# The proxy-gamed signal: the visible, in-repo gate is green and the held-out
# one is not. Called with test_sample's status after node_holdout. Silent when
# no verify_cmd is declared — "passed" would then mean "skipped".
holdout_note_divergence() {
  local test_result="$1"
  holdout_enabled || return 0
  [ "$LOOP_HOLDOUT_LAST_ITER" = "${ITERATION:-0}" ] || return 0
  [ "$LOOP_HOLDOUT_LAST_FAILED" -gt 0 ] || return 0
  [ "$test_result" -eq 0 ] || return 0
  [ -n "$(_read_verify_cmd)" ] || return 0
  log_error "HOLDOUT FAILED — visible verify_cmd passed: $LOOP_HOLDOUT_LAST_FAILED of $LOOP_HOLDOUT_LAST_TOTAL held-out scenario(s) fail while the in-repo gate is green. The visible gate does not cover what the holdout checks, or was rewritten to pass."
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
    log_warn "Goal checklist is complete, but held-out acceptance fails ($LOOP_HOLDOUT_LAST_FAILED of $LOOP_HOLDOUT_LAST_TOTAL) — not converged"
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
  if [ "$LOOP_HOLDOUT_LAST_FAILED" -eq 0 ]; then
    echo "Last check (iteration $LOOP_HOLDOUT_LAST_ITER): all $LOOP_HOLDOUT_LAST_TOTAL held-out acceptance scenario(s) passed."
  elif [ "$LOOP_HOLDOUT_LAST_TOTAL" -eq 0 ]; then
    echo "Last check (iteration $LOOP_HOLDOUT_LAST_ITER): the held-out acceptance scenarios could not be run. Goal items stay unreconciled until they run and pass."
  else
    echo "Last check (iteration $LOOP_HOLDOUT_LAST_ITER): $LOOP_HOLDOUT_LAST_FAILED of $LOOP_HOLDOUT_LAST_TOTAL held-out acceptance scenario(s) FAILED. Goal items stay unreconciled, and the run cannot converge, until every one passes."
  fi
  echo "These scenarios are withheld from this prompt by design. Meet the goal as written; do not plan work that looks for or edits them."
}

# One line for the end-of-run report and last-progress (human-facing).
holdout_report_line() {
  holdout_enabled || return 0
  if [ -z "$LOOP_HOLDOUT_LAST_ITER" ]; then
    printf 'configured, never ran'
  elif [ "$LOOP_HOLDOUT_LAST_FAILED" -eq 0 ]; then
    printf 'all %s scenario(s) passed at iteration %s' "$LOOP_HOLDOUT_LAST_TOTAL" "$LOOP_HOLDOUT_LAST_ITER"
  else
    printf '%s of %s scenario(s) failed at iteration %s' \
      "$LOOP_HOLDOUT_LAST_FAILED" "$LOOP_HOLDOUT_LAST_TOTAL" "$LOOP_HOLDOUT_LAST_ITER"
  fi
}
# ────────────────────────────────────────────────────────────────
