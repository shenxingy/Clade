#!/usr/bin/env bash
# loop_bounds.sh — resource ceilings for one autonomous run.
#
# Extracted from loop-runner.sh, which sits against the 1500-line ceiling that
# test_conventions.py enforces; bounds are a cohesive concern with their own
# tests, so they leave together rather than being trimmed to fit.
#
# Iteration count is NOT a resource bound. One iteration runs until its workers
# finish, worker work is unbounded, and `/start` exists to run unattended —
# which is exactly when nobody is watching either the clock or the spend.
#
# Both ceilings are checked BETWEEN iterations. They bound how long a run keeps
# starting new work; they cannot interrupt an iteration already in flight. That
# is the per-worker watchdog's job (run-tasks-parallel.sh, DEFAULT_TIMEOUT).
# The two layers together are what make a run actually bounded.
#
# Reads:  MAX_RUNTIME_MIN, MAX_COST_USD, LOOP_START_EPOCH, LOG_DIR
# Writes: exit_reason (on stop)
# Uses:   log_warn, log_info from loop-runner.sh

# ─── Wall clock ──────────────────────────────────────────────────────
# Returns 0 when the run should stop.
bounds_runtime_exceeded() {
  [ "${MAX_RUNTIME_MIN:-0}" -gt 0 ] || return 1
  local elapsed_min=$(( ( $(date +%s) - ${LOOP_START_EPOCH:-$(date +%s)} ) / 60 ))
  if [ "$elapsed_min" -ge "$MAX_RUNTIME_MIN" ]; then
    log_warn "Wall-clock limit reached: ${elapsed_min}m ≥ ${MAX_RUNTIME_MIN}m (--max-runtime)"
    exit_reason="max_runtime"
    return 0
  fi
  return 1
}

# ─── Spend ───────────────────────────────────────────────────────────
# Sum every `"total_cost_usd":N` the CLI emitted into this run's logs.
#
# The figure comes from claude's own stream-json output, so it needs no API
# call and no orchestrator venv — this script must keep running standalone.
# Semantics deliberately mirror orchestrator/run_budget.py:check_budget
# (>= ceiling stops, named reason) so the shell and Python paths cannot drift
# into disagreeing about what "over budget" means.
#
# Missing logs read as 0 spent, which fails OPEN: a run whose cost cannot be
# observed keeps going rather than halting on absent evidence. The wall clock
# still bounds it, and a silent stop would be indistinguishable from success.
bounds_spent_usd() {
  local dir="${LOG_DIR:-}"
  [ -n "$dir" ] && [ -d "$dir" ] || { echo "0"; return 0; }
  grep -rhoE '"total_cost_usd":[0-9.]+' "$dir" 2>/dev/null \
    | cut -d: -f2 \
    | awk '{ total += $1 } END { printf "%.4f", total + 0 }'
}

bounds_cost_exceeded() {
  # bash cannot compare floats; awk decides and signals through its exit status.
  awk -v c="${MAX_COST_USD:-0}" 'BEGIN { exit !(c > 0) }' || return 1
  local spent
  spent=$(bounds_spent_usd)
  if awk -v s="$spent" -v c="$MAX_COST_USD" 'BEGIN { exit !(s >= c) }'; then
    log_warn "Spend limit reached: \$${spent} ≥ \$${MAX_COST_USD} (--max-cost)"
    exit_reason="max_cost"
    return 0
  fi
  log_info "Spend so far: \$${spent} of \$${MAX_COST_USD} (--max-cost)"
  return 1
}

# ─── Combined gate ───────────────────────────────────────────────────
# Returns 0 when any ceiling says stop.
bounds_exceeded() {
  bounds_runtime_exceeded && return 0
  bounds_cost_exceeded && return 0
  return 1
}
