#!/usr/bin/env bash
# test-post-compact-reinject.sh — Tests for post-compact-reinject.sh
#
# The SessionStart(compact) hook that re-injects the PreCompact-saved task goal
# and re-arms path-scoped rules after context compaction. Verifies the wiring
# hole is closed: a startup-only matcher misses source=compact, so this hook is
# the "after" half of the save/reload pair. §7 runs the real producer
# (pre-compact.sh): a snapshot that records no task is orientation, never a
# task to resume.
#
# All state is redirected to a throwaway project dir under /tmp; the real
# ~/.claude is never touched. No API calls.
#
# Usage:
#   bash tests/test-post-compact-reinject.sh        # Run all tests
#   bash tests/test-post-compact-reinject.sh -v     # Verbose mode

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK="$REPO_ROOT/configs/hooks/post-compact-reinject.sh"

# ─── Test framework (mirrors tests/test-correction-pairing.sh) ───────
TESTS_RUN=0; TESTS_PASSED=0; TESTS_FAILED=0
VERBOSE="${1:-}"
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'

pass() { TESTS_PASSED=$((TESTS_PASSED + 1)); echo -e "  ${GREEN}✓${NC} $1"; }
fail() {
  TESTS_FAILED=$((TESTS_FAILED + 1))
  echo -e "  ${RED}✗${NC} $1"
  [[ -n "${2:-}" ]] && echo -e "    ${RED}→ $2${NC}"
}
section() { echo ""; echo -e "${YELLOW}━━━ $1 ━━━${NC}"; }

assert_contains() {
  local haystack="$1" needle="$2" msg="$3"
  TESTS_RUN=$((TESTS_RUN + 1))
  if grep -qF "$needle" <<< "$haystack"; then pass "$msg"
  else
    fail "$msg" "output does not contain '$needle'"
    [[ "$VERBOSE" == "-v" ]] && echo "    output: $(head -8 <<< "$haystack")"
  fi
}
assert_not_contains() {
  local haystack="$1" needle="$2" msg="$3"
  TESTS_RUN=$((TESTS_RUN + 1))
  if grep -qF "$needle" <<< "$haystack"; then fail "$msg" "output unexpectedly contains '$needle'"
  else pass "$msg"; fi
}
assert_empty() {
  local haystack="$1" msg="$2"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ -z "$haystack" ]]; then pass "$msg"
  else
    fail "$msg" "expected no output, got: $(head -3 <<< "$haystack")"
  fi
}

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found — skipping (CI installs jq)"; exit 0
fi

# ─── Sandbox ─────────────────────────────────────────────────────────
TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMP_ROOT"' EXIT

PROJ="$TMP_ROOT/proj"
mkdir -p "$PROJ/.claude/sessions"
SID="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
STATE="$PROJ/.claude/compact-state.md"
SENTINEL="$PROJ/.claude/sessions/${SID}.rules-injected"

compact_in() { jq -n --arg s "$1" --arg src "$2" '{session_id:$s, source:$src}'; }
ctx_of()     { jq -r '.hookSpecificOutput.additionalContext // ""' 2>/dev/null; }

write_state() {
  cat > "$STATE" <<'EOF'
# Pre-compact State: 2026-07-05 12:00

## Current Task
Implement the widget frobnicator per GOAL-42.

## Next Step
Wire frobnicate() into the dispatch table at dispatch.py:88.
EOF
}

# ─── 1. compact source with fresh state → goal re-injected ───────────
section "re-injects the saved goal on source=compact"
write_state
OUT=$(compact_in "$SID" "compact" | CLAUDE_PROJECT_DIR="$PROJ" bash "$HOOK")
CTX=$(ctx_of <<< "$OUT")
assert_contains "$CTX" "Post-compaction restore" "emits the restore header"
assert_contains "$CTX" "GOAL-42" "carries the verbatim saved task goal"
assert_contains "$CTX" "dispatch.py:88" "carries the verbatim next-step detail"

# ─── 2. clears the path-scoped rule sentinel (re-arm on next edit) ───
section "re-arms path-scoped rules by clearing the sentinel"
printf '%s\n' "$PROJ/.claude/rules/py.md" > "$SENTINEL"
TESTS_RUN=$((TESTS_RUN + 1))
[[ -f "$SENTINEL" ]] && pass "sentinel exists before compaction" \
  || fail "sentinel exists before compaction" "setup failed"
compact_in "$SID" "compact" | CLAUDE_PROJECT_DIR="$PROJ" bash "$HOOK" >/dev/null
TESTS_RUN=$((TESTS_RUN + 1))
[[ ! -f "$SENTINEL" ]] && pass "sentinel cleared so rules re-inject on next edit" \
  || fail "sentinel cleared so rules re-inject on next edit" "$SENTINEL still present"

# ─── 2b. a SUBAGENT compacted → main state untouched, nothing injected ─
# Claude Code fires this hook for a subagent's compaction too; 2.1.323+ passes
# its agent_id, and its transcript lives under <session>/subagents/. The old
# hook ignored both: it cleared the main thread's sentinel and injected the
# project snapshot into the subagent as "resume from it" (167 subagent
# transcripts on one host, 2026-11-16). Each case below is red against it.
section "a subagent's compaction re-arms only its own rules and injects nothing"
AID="a56d5e158f16bb4cc"
AGENT_SENT="$PROJ/.claude/sessions/${SID}.agent-${AID}.rules-injected"
reset_sentinels() {
  printf '%s\n' "$PROJ/.claude/rules/py.md" > "$SENTINEL"
  printf '%s\n' "$PROJ/.claude/rules/py.md" > "$AGENT_SENT"
}
check_subagent_case() {   # $1 = hook input JSON, $2 = label
  local out
  write_state; reset_sentinels
  out=$(printf '%s' "$1" | CLAUDE_PROJECT_DIR="$PROJ" bash "$HOOK")
  assert_empty "$out" "$2: no project snapshot injected into the subagent"
  TESTS_RUN=$((TESTS_RUN + 1))
  [[ -f "$SENTINEL" ]] && pass "$2: the main thread's sentinel is kept" \
    || fail "$2: the main thread's sentinel is kept" "$SENTINEL was removed"
  TESTS_RUN=$((TESTS_RUN + 1))
  [[ ! -f "$AGENT_SENT" ]] && pass "$2: the subagent's own sentinel is cleared" \
    || fail "$2: the subagent's own sentinel is cleared" "$AGENT_SENT still present"
}
check_subagent_case \
  "$(jq -n --arg s "$SID" --arg a "$AID" '{session_id:$s, source:"compact", agent_id:$a, agent_type:"general-purpose"}')" \
  "agent_id"
check_subagent_case \
  "$(jq -n --arg s "$SID" --arg t "/x/projects/-p/$SID/subagents/workflows/wf_1/agent-$AID.jsonl" '{session_id:$s, source:"compact", transcript_path:$t}')" \
  "subagent transcript_path"

# Control: a main-thread transcript_path is not mistaken for a subagent's.
write_state; reset_sentinels
OUT2C=$(jq -n --arg s "$SID" --arg t "/x/projects/-p/$SID.jsonl" '{session_id:$s, source:"compact", transcript_path:$t}' \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$HOOK")
assert_contains "$(ctx_of <<< "$OUT2C")" "GOAL-42" "main-thread transcript: the saved goal is still injected"
TESTS_RUN=$((TESTS_RUN + 1))
[[ ! -f "$SENTINEL" ]] && pass "main-thread transcript: the main sentinel is cleared" \
  || fail "main-thread transcript: the main sentinel is cleared" "$SENTINEL still present"
TESTS_RUN=$((TESTS_RUN + 1))
[[ -f "$AGENT_SENT" ]] && pass "a main-thread compaction leaves a subagent's sentinel alone" \
  || fail "a main-thread compaction leaves a subagent's sentinel alone" "$AGENT_SENT was removed"
rm -f "$AGENT_SENT"

# ─── 3. non-compact source (startup) → silent (defensive guard) ──────
section "ignores non-compact sources"
write_state
OUT3=$(compact_in "$SID" "startup" | CLAUDE_PROJECT_DIR="$PROJ" bash "$HOOK")
assert_empty "$OUT3" "startup source produces no output (startup hook owns that path)"

# ─── 4. stale compact-state (> 2h) → silent (no resurrection) ────────
section "does not resurface stale state"
write_state
if ! touch -d '3 hours ago' "$STATE" 2>/dev/null; then
  touch -t 202001010000 "$STATE" 2>/dev/null || true
fi
OUT4=$(compact_in "$SID" "compact" | CLAUDE_PROJECT_DIR="$PROJ" bash "$HOOK")
assert_empty "$OUT4" "state older than 2h is not re-injected"

# ─── 5. no compact-state file → silent ───────────────────────────────
section "silent when there is nothing to restore"
rm -f "$STATE"
OUT5=$(compact_in "$SID" "compact" | CLAUDE_PROJECT_DIR="$PROJ" bash "$HOOK")
assert_empty "$OUT5" "missing compact-state.md produces no output"

# ─── 6. empty/absent source still proceeds (belt-and-braces) ─────────
section "no-source input still injects (documented fallback)"
write_state
OUT6=$(echo '{}' | CLAUDE_PROJECT_DIR="$PROJ" bash "$HOOK")
CTX6=$(ctx_of <<< "$OUT6")
assert_contains "$CTX6" "Post-compaction restore" "empty-source input still injects the restore header"
assert_contains "$CTX6" "GOAL-42" "empty-source input carries the saved goal"

# ─── 7. what the producer really writes → orientation, not "resume" ──
# The fixture above records a Current Task. The real pre-compact.sh had recorded
# none in 25 of 25 field restores (2026-09-18 → 10-26), and this hook framed the
# TODO backlog it carried in 19 of them as "your task state … resume from it".
# So run the real producer, then the hook.
section "a snapshot with no recorded task is orientation, not an instruction"
PRODUCER="$REPO_ROOT/configs/hooks/pre-compact.sh"
rm -f "$STATE"
printf '# TODO\n- [ ] Rewrite the billing module\n' > "$PROJ/TODO.md"
CLAUDE_PROJECT_DIR="$PROJ" bash "$PRODUCER" </dev/null >/dev/null 2>&1
CTX7=$(compact_in "$SID" "compact" | CLAUDE_PROJECT_DIR="$PROJ" bash "$HOOK" | ctx_of)
assert_contains "$CTX7" "No task was recorded" "the producer's snapshot is framed as carrying no task"
assert_contains "$CTX7" "Rewrite the billing module" "the repository snapshot is still delivered"
assert_contains "$CTX7" "backlog, not the current task" "its TODO items are labelled backlog"
assert_not_contains "$CTX7" "resume from it" "it is never framed as a task to resume"

# An install that has not picked up the new producer still writes the old
# marker; it gets the same framing.
printf '# Pre-compact State: x\n\n## Current Task\n(no current-task.md found)\n\n## Open TODO Items\n- [ ] Old backlog item\n' > "$STATE"
CTX8=$(compact_in "$SID" "compact" | CLAUDE_PROJECT_DIR="$PROJ" bash "$HOOK" | ctx_of)
assert_contains "$CTX8" "No task was recorded" "the older producer's marker gets the same framing"
assert_not_contains "$CTX8" "resume from it" "and is not framed as a task to resume either"
rm -f "$PROJ/TODO.md"

# ─── 8. a subagent's PreCompact leaves the project's snapshot alone ──
# A subagent's compaction fires PreCompact too. Writing then refreshed the
# snapshot's mtime and kept session-context.sh's two-hour "resume" window open
# on a snapshot no main-thread compaction wrote. Red against the old producer,
# which read no input at all.
section "pre-compact.sh writes nothing for a subagent's compaction"
printf 'KEEP-ME\n' > "$STATE"
touch -t 202601010000 "$STATE"
jq -n --arg s "$SID" '{session_id:$s, agent_id:"a1b2", agent_type:"general-purpose"}' \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$PRODUCER" >/dev/null 2>&1
assert_contains "$(cat "$STATE")" "KEEP-ME" "agent_id: the project's snapshot is not rewritten"
jq -n --arg s "$SID" --arg t "/x/projects/-p/$SID/subagents/agent-a1b2.jsonl" '{session_id:$s, transcript_path:$t}' \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$PRODUCER" >/dev/null 2>&1
assert_contains "$(cat "$STATE")" "KEEP-ME" "subagent transcript_path: the snapshot is not rewritten"
TESTS_RUN=$((TESTS_RUN + 1))
touch -t 202601010001 "$PROJ/.mtime-ref"
[[ "$STATE" -ot "$PROJ/.mtime-ref" ]] \
  && pass "and its mtime is not refreshed" || fail "and its mtime is not refreshed" "$STATE is newer than its fixture time"
rm -f "$PROJ/.mtime-ref"
# Control: the main thread's compaction does write it.
jq -n --arg s "$SID" --arg t "/x/projects/-p/$SID.jsonl" '{session_id:$s, transcript_path:$t}' \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$PRODUCER" >/dev/null 2>&1
assert_not_contains "$(cat "$STATE")" "KEEP-ME" "control: a main-thread compaction rewrites the snapshot"
assert_contains "$(cat "$STATE")" "none recorded" "control: and records that no task was recorded"

# ─── Summary ─────────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  Ran: $TESTS_RUN  ${GREEN}Passed: $TESTS_PASSED${NC}  ${RED}Failed: $TESTS_FAILED${NC}"
[[ "$TESTS_FAILED" -eq 0 ]] && { echo -e "  ${GREEN}ALL PASSED${NC}"; exit 0; } || { echo -e "  ${RED}FAILURES${NC}"; exit 1; }
