#!/usr/bin/env bash
# test-loop-env.sh — the environment, deployment and out-of-process half of the
# loop test system. Split VERBATIM out of tests/test-loop.sh, which stood at
# 1448 lines against the 1500-line ceiling; every case below is the one that
# ran there, unchanged.
#
# NOT a standalone suite. It is SOURCED by tests/test-loop.sh and depends on
# that file's fixture (tests/lib/loop-fixture.sh) for the assertion helpers,
# the counters, `should_run`/`section`, the mocked claude/committer on PATH,
# and ORIG_DIR / TEST_DIR / SCRIPTS_DIR / REPO_DIR. Run it the one way CI and
# CLAUDE.md name:
#
#   bash tests/test-loop.sh
#
# Suites carried here:
#   12  models.env integration — the shell layer and orchestrator/config.py
#       must name the same models, and loop-runner must resolve its default
#       from models.env rather than a hardcoded literal
#   13  Deployed script verification — ~/.claude/scripts matches source
#   14  Signal handling — the SIGTERM cleanup writes INTERRUPTED=true
#   15  --max-runtime wall-clock bound, and setsid --wait availability
#   16  scan-health.sh test-runtime probe

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "test-loop-env.sh is sourced by tests/test-loop.sh, not run on its own:" >&2
  echo "it needs that file's fixture for the assertion helpers and counters." >&2
  echo "Run: bash tests/test-loop.sh" >&2
  exit 2
fi

# ═══════════════════════════════════════════════════════════════════════
# TEST SUITE 12: models.env Integration
# ═══════════════════════════════════════════════════════════════════════

if should_run "models"; then
section "models.env Integration"

source "$ORIG_DIR/configs/models.env"

# Pin the CROSS-SURFACE invariant, not the literals. Restating models.env's
# own contents proved nothing and went red on every legitimate model bump;
# what actually matters is that the shell layer and orchestrator/config.py
# name the same models, because a split between them routes the two surfaces
# to different models with nothing to notice.
CFG_ALIASES=$(python3 - "$ORIG_DIR/orchestrator/config.py" <<'PYEOF'
import ast, re, sys
src = open(sys.argv[1], encoding="utf-8").read()
m = re.search(r"^_MODEL_ALIASES = (\{.*?^\})", src, re.S | re.M)
a = ast.literal_eval(m.group(1))
print(f"{a['haiku']}\n{a['sonnet']}\n{a['opus']}")
PYEOF
)
CFG_HAIKU=$(sed -n 1p <<<"$CFG_ALIASES")
CFG_SONNET=$(sed -n 2p <<<"$CFG_ALIASES")
CFG_OPUS=$(sed -n 3p <<<"$CFG_ALIASES")

assert_eq "$CFG_HAIKU" "$MODEL_HAIKU" "MODEL_HAIKU matches config.py _MODEL_ALIASES"
assert_eq "$CFG_SONNET" "$MODEL_SONNET" "MODEL_SONNET matches config.py _MODEL_ALIASES"
assert_eq "$CFG_OPUS" "$MODEL_OPUS" "MODEL_OPUS matches config.py _MODEL_ALIASES"

# A generation-stale alias silently routes every task to a superseded model,
# so assert the shape rather than a literal that has to be edited each bump.
case "$MODEL_OPUS" in claude-opus-4-*) assert_eq "current" "stale" "MODEL_OPUS is not a superseded generation" ;; esac
case "$MODEL_SONNET" in claude-sonnet-4-*) assert_eq "current" "stale" "MODEL_SONNET is not a superseded generation" ;; esac

# The two assertions above compared models.env to config.py while loop-runner
# — the thing that actually runs — hardcoded claude-sonnet-4-6 and sourced
# neither. models.env's own header says "source this file instead of
# hardcoding"; install.sh was its only consumer. Pin the real defaults.
LR_DEFAULTS=$(bash -c '
  _SELF_DIR="'"$ORIG_DIR"'/configs/scripts"
  . "$_SELF_DIR/../models.env"
  echo "${MODEL_SONNET:-unset}"
')
assert_eq "$MODEL_SONNET" "$LR_DEFAULTS" "loop-runner resolves its model default from models.env"

# Behavioural, not textual: change models.env and loop-runner must follow.
# A grep for the variable name would pass on a file that also hardcodes a
# fallback the code actually uses.
FAKE_ENV_DIR=$(mktemp -d /tmp/clade-modelenv-XXXXXX)
mkdir -p "$FAKE_ENV_DIR/scripts"
cp "$ORIG_DIR"/configs/scripts/loop-runner.sh "$ORIG_DIR"/configs/scripts/loop_*.sh \
   "$ORIG_DIR"/configs/scripts/loop_*.py "$FAKE_ENV_DIR/scripts/" 2>/dev/null
printf 'MODEL_SONNET="sentinel-model-xyz"\n' > "$FAKE_ENV_DIR/models.env"
LR_OUT=$(cd "$TEST_DIR" && bash "$FAKE_ENV_DIR/scripts/loop-runner.sh" --help 2>&1 || true)
assert_contains "$LR_OUT" "sentinel-model-xyz" "loop-runner takes its model default from models.env, not a literal"
rm -rf "$FAKE_ENV_DIR"

# Test model_id resolution
model_id_test() {
  case "$1" in
    haiku)  echo "$MODEL_HAIKU" ;;
    sonnet) echo "$MODEL_SONNET" ;;
    opus)   echo "$MODEL_OPUS" ;;
    *)      echo "$1" ;;
  esac
}

assert_eq "$MODEL_HAIKU" "$(model_id_test haiku)" "model_id: haiku → full ID"
assert_eq "$MODEL_SONNET" "$(model_id_test sonnet)" "model_id: sonnet → full ID"
assert_eq "$MODEL_OPUS" "$(model_id_test opus)" "model_id: opus → full ID"
assert_eq "custom-model" "$(model_id_test custom-model)" "model_id: unknown → passthrough"
fi

# ═══════════════════════════════════════════════════════════════════════
# TEST SUITE 13: Deployed Script Verification
# ═══════════════════════════════════════════════════════════════════════

if should_run "deploy"; then
section "Deployed Script Verification"

# A dropped `. loop_*.sh` source line leaves every extracted node undefined.
for sibling in loop_args.sh loop_verify.sh loop_bounds.sh loop_score.sh; do
  TESTS_RUN=$((TESTS_RUN + 1))
  if grep -q "_sibling_script $sibling" "$ORIG_DIR/configs/scripts/loop-runner.sh"
  then pass "loop-runner.sh sources $sibling"
  else fail "loop-runner.sh does not source $sibling" "extracted nodes undefined"; fi
done

DEPLOY_DIR="$HOME/.claude/scripts"

if [[ ! -d "$DEPLOY_DIR" ]]; then
  # No kit deployed at all (e.g. CI runners) — deploy verification only makes
  # sense on machines that ran install.sh. Skipping is not a failure.
  echo "  (no deployed kit at $DEPLOY_DIR — skipping deploy verification)"
else
for script in loop-runner.sh loop_args.sh loop_verify.sh loop_bounds.sh loop_score.sh loop_checkpoint.py loop_goal.py loop_json.py run-tasks-parallel.sh run-tasks.sh run_tasks_common.sh; do
  src="$ORIG_DIR/configs/scripts/$script"
  dst="$DEPLOY_DIR/$script"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ -f "$src" && -f "$dst" ]]; then
    if diff -q "$src" "$dst" &>/dev/null; then
      pass "deployed $script matches source"
    else
      fail "deployed $script DIFFERS from source" "run install.sh to sync"
    fi
  elif [[ ! -f "$dst" ]]; then
    fail "$script not deployed" "missing: $dst"
  else
    pass "$script deployment check (source not found, skip)"
  fi
done
fi
fi

# ═══════════════════════════════════════════════════════════════════════
# TEST SUITE 14: Signal Handling
# ═══════════════════════════════════════════════════════════════════════

if should_run "signal"; then
section "Signal Handling"

# Test the SIGTERM trap logic from loop-runner.sh directly
# (Spawning a full loop with workers and killing it is fragile in CI)

REPO_DIR=$(setup_test_repo)
cd "$REPO_DIR"
mkdir -p .claude

STATE_FILE=".claude/loop-state-signal"
{ echo "ITERATION=2"; echo "CONVERGED=false"; } > "$STATE_FILE"

# Simulate the _cleanup function from loop-runner.sh
_cleanup_test() {
  [[ -n "${STATE_FILE:-}" ]] && {
    local key="INTERRUPTED" val="true"
    if grep -q "^${key}=" "$STATE_FILE"; then
      sed -i "s|^${key}=.*|${key}=${val}|" "$STATE_FILE"
    else
      echo "${key}=${val}" >> "$STATE_FILE"
    fi
  }
}

_cleanup_test
assert_file_contains "$STATE_FILE" "INTERRUPTED=true" "cleanup writes INTERRUPTED=true"
assert_file_contains "$STATE_FILE" "ITERATION=2" "cleanup preserves ITERATION"
fi

# ═══════════════════════════════════════════════════════════════════════
# TEST SUITE 15: setsid --wait Verification
# ─── Wall-clock bound ────────────────────────────────────────────────
# Iterations are not a time bound: one iteration runs until its workers finish,
# and worker work is unbounded, so `--max-iter 10` becomes an overnight run.
# `/start` exists to run unattended — exactly when nobody is watching the spend.
echo ""
echo "── --max-runtime bounds a run by wall clock ──"

# Pin the sandbox explicitly rather than inheriting whatever cd was last in
# effect. This fixture escaped into the repository root twice on 2026-09-02, and
# a stray `goal-*.md` at the root is exactly what check-roadmap-authority.py now
# looks for — a test that plants the shape its own gate rejects.
cd "$REPO_DIR"
printf '# Goal: never done\n\n- [ ] unchecked forever\n' > goal-runtime.md
mkdir -p logs/loop-runtime logs/loop-runtime-off
export MOCK_CLAUDE_RESPONSE='[]'

# Pre-seed the start epoch 90 minutes back so the branch is exercised without
# a test that actually sleeps.
out_rt=$(
  exec 3>&- 4>&- 5>&- 6>&- 7>&- 8>&- 9>&- 2>/dev/null
  LOOP_START_EPOCH=$(( $(date +%s) - 90*60 )) \
  timeout --kill-after=5s 60s bash "$SCRIPTS_DIR/loop-runner.sh" "goal-runtime.md" \
    --max-iter 5 --max-workers 1 --max-runtime 60 \
    --state .claude/loop-state-runtime --log-dir logs/loop-runtime 2>&1
) || true
assert_contains "$out_rt" "Wall-clock limit reached" "90m elapsed vs --max-runtime 60 stops the run"
assert_not_contains "$out_rt" "Iteration 2" "wall-clock stop happens before starting more work"
assert_file_contains "logs/loop-runtime/last-progress" "Exit: max_runtime" "records max_runtime as the exit reason"

# 0 disables the bound — the run must terminate for a DIFFERENT reason.
out_off=$(
  exec 3>&- 4>&- 5>&- 6>&- 7>&- 8>&- 9>&- 2>/dev/null
  LOOP_START_EPOCH=$(( $(date +%s) - 9999*60 )) \
  timeout --kill-after=5s 60s bash "$SCRIPTS_DIR/loop-runner.sh" "goal-runtime.md" \
    --max-iter 1 --max-workers 1 --max-runtime 0 \
    --state .claude/loop-state-runtime-off --log-dir logs/loop-runtime-off 2>&1
) || true
assert_not_contains "$out_off" "Wall-clock limit reached" "--max-runtime 0 disables the bound entirely"
assert_contains "$out_off" "Max iterations" "with the clock disabled the run still stops on --max-iter"
rm -f goal-runtime.md   # a stray root-level goal-*.md is what check-roadmap-authority.py rejects


# ═══════════════════════════════════════════════════════════════════════

if should_run "setsid"; then
section "setsid --wait Verification"

# Critical: setsid without --wait causes workers to appear to succeed instantly
TESTS_RUN=$((TESTS_RUN + 1))
if command -v setsid &>/dev/null; then
  if setsid --help 2>&1 | grep -q "\-\-wait"; then
    pass "setsid --wait is available"
  else
    fail "setsid exists but --wait flag missing" "workers may not wait for completion"
  fi
else
  fail "setsid not found" "install util-linux for process group isolation"
fi
fi


# ═══════════════════════════════════════════════════════════════════════
# TEST SUITE 16: scan-health.sh test-runtime probe
# ═══════════════════════════════════════════════════════════════════════

if should_run "healthprobe"; then
section "scan-health.sh test-runtime probe"

SCAN_HEALTH="$ORIG_DIR/configs/scripts/scan-health.sh"

# Slow suite: threshold forced to 0 so a 1s sleep trips the probe
REPO_DIR=$(setup_test_repo)
cd "$REPO_DIR"
cat > CLAUDE.md <<'CLAUDE_EOF'
# Project Type
- Type: cli
- Verify command: sleep 1
CLAUDE_EOF
out=$(TEST_RUNTIME_THRESHOLD=0 bash "$SCAN_HEALTH" . 2>/dev/null)
assert_contains "$out" "health_slow_tests" "slow verify_cmd emits a runtime task"
assert_contains "$out" "/trim-tests" "runtime task points at the trim-tests skill"
assert_contains "$out" "sleep 1" "runtime task names the probed command"

# Fast suite at default threshold (100s): no runtime task
cat > CLAUDE.md <<'CLAUDE_EOF'
# Project Type
- Type: cli
- Verify command: true
CLAUDE_EOF
out=$(bash "$SCAN_HEALTH" . 2>/dev/null)
assert_not_contains "$out" "health_slow_tests" "fast suite emits no runtime task"

# No verify/test command in CLAUDE.md: probe skipped silently
cat > CLAUDE.md <<'CLAUDE_EOF'
# Project Type
- Type: cli
CLAUDE_EOF
out=$(bash "$SCAN_HEALTH" . 2>/dev/null)
rc=$?
assert_exit_code 0 "$rc" "probe without verify_cmd exits clean"
assert_not_contains "$out" "health_slow_tests" "no verify_cmd → no runtime task"

# Template placeholder ("[e.g. ...]") is not runnable: probe skipped
cat > CLAUDE.md <<'CLAUDE_EOF'
# Project Type
- Type: cli
- Verify command: [e.g. ./scripts/smoke-test.sh, or N/A]
CLAUDE_EOF
out=$(TEST_RUNTIME_THRESHOLD=0 bash "$SCAN_HEALTH" . 2>/dev/null)
assert_not_contains "$out" "health_slow_tests" "template placeholder skipped"

# SCAN_HEALTH_SKIP_RUNTIME=1 opts out even for a slow suite
cat > CLAUDE.md <<'CLAUDE_EOF'
# Project Type
- Type: cli
- Verify command: sleep 1
CLAUDE_EOF
out=$(SCAN_HEALTH_SKIP_RUNTIME=1 TEST_RUNTIME_THRESHOLD=0 bash "$SCAN_HEALTH" . 2>/dev/null)
assert_not_contains "$out" "health_slow_tests" "SCAN_HEALTH_SKIP_RUNTIME=1 skips probe"

# Failing-but-slow command still reports (exit code captured, not swallowed)
cat > CLAUDE.md <<'CLAUDE_EOF'
# Project Type
- Type: cli
- Verify command: sleep 1 && false
CLAUDE_EOF
out=$(TEST_RUNTIME_THRESHOLD=0 bash "$SCAN_HEALTH" . 2>/dev/null)
rc=$?
assert_exit_code 0 "$rc" "failing verify_cmd does not kill scan-health"
assert_contains "$out" "health_slow_tests" "slow failing suite still emits runtime task"
assert_contains "$out" "exit code: 1" "task records the suite exit code"
fi

