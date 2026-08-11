#!/usr/bin/env bash
# loop_args.sh — CLI surface for loop-runner.sh: option parsing and usage.
#
# Extracted from loop-runner.sh, which had grown to exactly the 1500-line
# ceiling in CLAUDE.md Code Rules — leaving no room to fix the parser or
# document a flag without tripping the convention test. Sourced, not executed:
# it sets the same globals in the caller as before.


# ─── PARSE ARGS ─────────────────────────────────────────────────
parse_args() {
  # Handle --status and --stop before GOAL_FILE is required
  for arg in "$@"; do
    case "$arg" in
      --help|-h) print_usage; exit 0 ;;
      --status) show_status; exit 0 ;;
      --stop)   write_stop_sentinel; exit 0 ;;
      --interrupt)
        # Write interrupt state file and exit (LangGraph pattern)
        mkdir -p .claude
        python3 -c "
import json, sys, time
state = {'interrupted': True, 'reason': 'manual', 'timestamp': time.time()}
path = '.claude/interrupt-state.json'
with open(path, 'w') as f:
    json.dump(state, f, indent=2)
print(f'Interrupt state written to {path}')
"
        exit 0 ;;
    esac
  done

  # Positional goal file, accepted on either side of the flags. Taking "$1"
  # unconditionally made the documented `--dry-run goal.md` form set
  # GOAL_FILE=--dry-run, failing as "Goal file not found" rather than a parse error.
  if [ $# -gt 0 ] && [ "${1#-}" = "$1" ]; then
    GOAL_FILE="$1"
    shift
  fi

  while [ $# -gt 0 ]; do
    case "$1" in
      --model)        SUPERVISOR_MODEL="$2"; shift 2 ;;
      --worker-model) WORKER_MODEL="$2"; shift 2 ;;
      --max-iter)     MAX_ITER="$2"; shift 2 ;;
      --max-workers)  MAX_WORKERS="$2"; shift 2 ;;
      --supervisor-timeout) SUPERVISOR_TIMEOUT="$2"; shift 2 ;;
      --max-consecutive-failures) MAX_CONSECUTIVE_FAILURESOverride="$2"; shift 2 ;;
      --context)      CONTEXT_FILE="$2"; shift 2 ;;
      --state)        STATE_FILE="$2"; shift 2 ;;
      --log-dir)      LOG_DIR="$2"; shift 2 ;;
      --resume)       RESUME=true; shift ;;
      --budget)       shift 2 ;;  # accepted but not used in Blueprint mode
      --exit-gate)    shift 2 ;;  # accepted but not used in Blueprint mode
      --dry-run)      DRY_RUN=true; shift ;;
      -*) log_warn "Unknown flag: $1"; shift ;;
      *)
        # Trailing positional: the goal file when it followed the flags.
        if [ -z "$GOAL_FILE" ]; then GOAL_FILE="$1"; else log_warn "Ignoring extra argument: $1"; fi
        shift ;;
    esac
  done

  # Apply --max-consecutive-failures override if provided
  if [ -n "$MAX_CONSECUTIVE_FAILURESOverride" ]; then
    MAX_CONSECUTIVE_FAILURES="$MAX_CONSECUTIVE_FAILURESOverride"
  fi
}


# ─── ENTRY POINT ────────────────────────────────────────────────
print_usage() {
  cat <<'EOF'
Usage: loop-runner.sh GOAL_FILE [options]
       loop-runner.sh [options] GOAL_FILE
       loop-runner.sh --status
       loop-runner.sh --stop

GOAL_FILE may appear before or after the options.

Options:
  --model MODEL         supervisor model (default: claude-sonnet-4-6)
  --worker-model MODEL  worker model (default: same as supervisor)
  --max-iter N          max iterations (default: 10)
  --max-workers N       max parallel workers (default: 4)
  --supervisor-timeout N  seconds the supervisor gets to produce a plan
                        (default: 300). Planning cost scales with goal size;
                        raise this for very large goals.
  --max-consecutive-failures N  stop after N consecutive worker failures
  --context FILE        pre-generated context file
  --state FILE          state file (default: .claude/loop-state.json)
  --log-dir DIR         log directory (default: logs/loop)
  --dry-run             preview iteration plan, no claude calls
  --resume              resume an identity-matched interrupted run
EOF
}
