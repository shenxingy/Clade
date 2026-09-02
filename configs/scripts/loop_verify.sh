#!/usr/bin/env bash
# loop_verify.sh — syntax/health/test/verify nodes for one iteration.
#
# Extracted from loop-runner.sh, which sits against the 1500-line ceiling that
# test_conventions.py enforces. Verification is a cohesive group: everything
# here answers "is the tree still good?" after workers ran — syntax check, the
# one-shot syntax fixer, the baseline health check, the project verify_cmd
# sample, and the LLM verify node. Loop control and goal state stay behind.
#
# Sourced, not executed: it sets and reads the same globals in the caller as
# when these functions were inline, so the source line in loop-runner.sh must
# come before any call site.
#
# Reads:  SYNTAX_CHECK_TIMEOUT, TEST_SAMPLE_TIMEOUT, SUPERVISOR_TIMEOUT,
#         SUPERVISOR_MODEL, LOG_DIR, ITERATION, ITERATION_START_COMMIT,
#         PURE_JUDGE_FLAGS
# Writes: LAST_TEST_OUTPUT, LAST_TEST_RESULT, PREV_FAILED
# Uses:   log_info/log_success/log_warn, _timeout from loop-runner.sh

# ─── [DET] NODE: SYNTAX CHECK ───────────────────────────────────
# Checks syntax of all files changed since HEAD. No LLM calls.
node_syntax_check() {
  log_info "[DET] syntax_check"

  local changed_files
  changed_files=$(git diff --name-only 2>/dev/null || true)
  if [ -z "$changed_files" ]; then
    changed_files=$(git diff --name-only HEAD~1..HEAD 2>/dev/null || true)
  fi

  if [ -z "$changed_files" ]; then
    log_info "No changed files to check"
    echo ""
    return
  fi

  local failures=""

  while IFS= read -r f; do
    [ -f "$f" ] || continue
    case "$f" in
      *.py)
        if ! _timeout "$SYNTAX_CHECK_TIMEOUT" python3 -m py_compile "$f" 2>/dev/null; then
          failures="${failures}${f}\n"
          log_warn "Python syntax error: $f"
        fi
        ;;
      *.sh)
        if ! _timeout 10 bash -n "$f" 2>/dev/null; then
          failures="${failures}${f}\n"
          log_warn "Shell syntax error: $f"
        fi
        ;;
      *.ts|*.tsx)
        # Only check if npx tsc available and tsconfig exists
        if command -v npx &>/dev/null && [ -f "tsconfig.json" ]; then
          if ! _timeout "$SYNTAX_CHECK_TIMEOUT" npx tsc --noEmit 2>/dev/null; then
            failures="${failures}${f}\n"
            log_warn "TypeScript error: $f"
          fi
        fi
        ;;
    esac
  done <<< "$changed_files"

  printf "%b" "$failures"
}
# ────────────────────────────────────────────────────────────────

# ─── [LLM] NODE: FIX SYNTAX ─────────────────────────────────────
# Attempts to fix syntax errors. Called at most MAX_FIX_ATTEMPTS times per iteration.
node_fix_syntax() {
  local failing_files="$1"
  local files_list
  files_list=$(printf "%b" "$failing_files" | tr '\n' ' ')
  log_info "[LLM] fix_syntax (files: $files_list)"

  local fix_prompt="Fix syntax errors in these files: $files_list

Steps:
1. Run syntax check on each file to understand the exact errors
2. Fix only the syntax errors — do not refactor or add functionality
3. Verify each file passes its syntax check after fixing
4. Commit fixes with: committer \"fix: syntax errors\" $files_list

Only fix syntax errors. Do not change logic or add features."

  # Fixer edits files + commits → keeps user hooks deliberately (no PURE_JUDGE_FLAGS);
  # its stdout is only tee'd to the log, never parsed.
  _timeout "$SUPERVISOR_TIMEOUT" claude --model "$SUPERVISOR_MODEL" -p "$fix_prompt" \
    2>&1 | tee -a "$LOG_DIR/loop.log" || {
      log_warn "Fix syntax attempt failed or timed out"
    }
}
# ────────────────────────────────────────────────────────────────

# ─── Shared: read verify_cmd from CLAUDE.md (YAML or inline label) ──
_read_verify_cmd() {
  local vc
  vc=$(grep -m1 'verify_cmd:' CLAUDE.md 2>/dev/null | sed 's/.*verify_cmd:[[:space:]]*//' || true)
  if [ -z "$vc" ]; then
    vc=$(grep -m1 'Verify command:' CLAUDE.md 2>/dev/null | sed 's/.*Verify command:[[:space:]]*//' || true)
  fi
  printf '%s' "$vc"
}

# ─── #3: parse pytest-style "N failed" from verify output (best-effort) ──
# Echoes the failed+error count, or nothing if the output isn't parseable.
# Always exits 0 (pipefail-safe: grep returns non-zero on no match).
_parse_failed_count() {
  local out="$1" n
  n=$(printf '%s' "$out" | grep -oE '[0-9]+ (failed|error)' 2>/dev/null \
        | grep -oE '^[0-9]+' 2>/dev/null | awk '{s+=$1} END{if(NR)print s}') || true
  # No failure tokens, but a recognizable test summary → 0 failed (suite is green).
  if [ -z "$n" ] && printf '%s' "$out" | grep -qE '[0-9]+ passed'; then
    n=0
  fi
  printf '%s' "$n"
}

# ─── [DET] NODE: HEALTH CHECK (Anthropic: repair broken baseline first) ──
# Runs the verify_cmd at the START of an iteration so the supervisor repairs a
# broken baseline before planning new work. Iteration 1 runs fresh; later
# iterations reuse the prior iteration's test_sample result (no double run).
# On failure, writes .claude/health-warning.md, which node_hydrate_context folds
# into the supervisor's context.
node_health_check() {
  local verify_cmd; verify_cmd=$(_read_verify_cmd)
  rm -f .claude/health-warning.md
  if [ -z "$verify_cmd" ]; then
    return 0  # no verify_cmd → nothing to check
  fi

  local broken=0 out=""
  if [ "${ITERATION:-1}" -le 1 ]; then
    log_info "[DET] health_check (baseline, iter 1)"
    out=$(_timeout "$TEST_SAMPLE_TIMEOUT" bash -c "$verify_cmd" 2>&1) || broken=1
  else
    # Reuse the previous iteration's result — avoids a second full test run.
    [ "${LAST_TEST_RESULT:-0}" -ne 0 ] && broken=1
    out="${LAST_TEST_OUTPUT:-}"
  fi

  if [ "$broken" -ne 0 ]; then
    mkdir -p .claude
    {
      echo "## ⚠️ BASELINE HEALTH: FAILING"
      echo "The project's verify_cmd is currently failing. **Repair the broken"
      echo "baseline before planning any new feature work** (Anthropic harness lever)."
      echo '```'
      printf '%s\n' "$out" | tail -30
      echo '```'
    } > .claude/health-warning.md
    log_warn "[DET] health_check: baseline FAILING — supervisor will repair first"
  else
    log_success "[DET] health_check: baseline healthy"
  fi
  return 0
}
# ────────────────────────────────────────────────────────────────

# ─── [DET] NODE: TEST SAMPLE ────────────────────────────────────
# Runs the project's verify_cmd from CLAUDE.md. No LLM calls.
node_test_sample() {
  log_info "[DET] test_sample"

  local verify_cmd; verify_cmd=$(_read_verify_cmd)
  if [ -z "$verify_cmd" ]; then
    log_info "No verify_cmd in CLAUDE.md — skipping test sample"
    return 0
  fi

  log_info "Running verify: $verify_cmd"
  local tmp_out rc=0
  tmp_out=$(mktemp "${TMPDIR:-/tmp}/loop-verify.XXXXXX")
  _timeout "$TEST_SAMPLE_TIMEOUT" bash -c "$verify_cmd" >"$tmp_out" 2>&1 || rc=$?
  tee -a "$LOG_DIR/loop.log" < "$tmp_out" >&2

  # Carry the result forward so the next iteration's health_check can reuse it
  # rather than running the whole suite a second time.
  LAST_TEST_OUTPUT=$(cat "$tmp_out")
  LAST_TEST_RESULT=$rc

  # #3: per-iteration fix-rate — log the failed-count delta vs the prior iteration.
  local cur_failed; cur_failed=$(_parse_failed_count "$LAST_TEST_OUTPUT")
  if [ -n "$cur_failed" ]; then
    if [ -n "${PREV_FAILED:-}" ]; then
      local repaired=$((PREV_FAILED - cur_failed))
      printf '%s\t%s\t%s\t%s\n' "${ITERATION:-0}" "$PREV_FAILED" "$cur_failed" "$repaired" \
        >> "$LOG_DIR/fix-rate.tsv"
      log_info "[METRIC] iter ${ITERATION:-0} fix-rate: failed ${PREV_FAILED}→${cur_failed} (repaired ${repaired})"
    fi
    PREV_FAILED=$cur_failed
  fi

  rm -f "$tmp_out"
  if [ "$rc" -eq 0 ]; then
    log_success "Test sample passed"
  else
    log_warn "Test sample failed (workers may have introduced issues — continuing)"
  fi
  return "$rc"
}
# ────────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────────────

# ─── [LLM] NODE: VERIFY ────────────────────────────────────────────
# Calls /verify skill with structured output and parses JSON results (Junie pattern).
# Runs after test_sample to provide additional LLM-based verification.
node_verify() {
  log_info "[LLM] verify"

  # Get list of changed files for focused verification
  local changed_files
  changed_files=$({
    git diff --name-only 2>/dev/null || true
    if [ -n "${ITERATION_START_COMMIT:-}" ] \
       && [ "$(git rev-parse HEAD 2>/dev/null || true)" != "$ITERATION_START_COMMIT" ]; then
      git diff --name-only "$ITERATION_START_COMMIT"..HEAD 2>/dev/null || true
    fi
  } | awk 'NF && !seen[$0]++' | head -20)

  if [ -z "$changed_files" ]; then
    log_info "No changed files to verify"
    echo '{"passed": true, "items": [], "summary": "no changes"}'
    return
  fi

  # Build focused verify prompt
  local verify_prompt="Verify these changed files for correctness:
$changed_files

For each file:
1. Read the file and understand what changed
2. Run relevant syntax/compile/lint checks
3. If tests exist for this file, run them

Output a JSON object with this exact structure:
{
  \"passed\": true or false,
  \"items\": [
    {\"file\": \"path\", \"check\": \"what was checked\", \"passed\": true/false, \"reason\": \"why\"}
  ],
  \"summary\": \"one line summary\"
}

Be strict. Return passed:false if any check fails. Do not fabricate checks you did not run."

  local result
  if ! result=$(_timeout "$SUPERVISOR_TIMEOUT" claude -p "$verify_prompt" --model sonnet "${PURE_JUDGE_FLAGS[@]}" 2>&1); then
    log_warn "Verify call failed or timed out"
    echo '{"passed": null, "items": [], "summary": "verify call failed"}'
    return
  fi

  # Parse JSON from result (may have preamble text)
  local parsed
  parsed=$(echo "$result" | python3 -c "
import sys, json, re
text = sys.stdin.read()
match = re.search(r'\{[\s\S]*\}', text)
if match:
    try:
        d = json.loads(match.group())
        print(json.dumps(d))
    except Exception:
        print('{\"passed\": null, \"items\": [], \"summary\": \"parse error\"}')
else:
    print('{\"passed\": null, \"items\": [], \"summary\": \"no json found\"}')
" 2>/dev/null || echo '{"passed": null, "items": [], "summary": "parse error"}')

  echo "$parsed"

  if echo "$parsed" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('passed') is False else 1)" 2>/dev/null; then
    log_warn "Verify found issues: $(echo "$parsed" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("summary",""))' 2>/dev/null || echo "see log")"
  elif _verify_passed "$parsed"; then
    log_success "Verify passed"
  else
    log_warn "Verify unavailable or unparseable"
  fi
}

_verify_passed() {
  printf '%s' "$1" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("passed") is True else 1)' 2>/dev/null
}

