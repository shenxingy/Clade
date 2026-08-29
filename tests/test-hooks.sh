#!/usr/bin/env bash
# test-hooks.sh — Hook delivery-channel tests (Claude Code 2.1 adaptation).
#
#   session-end-cleanup.sh  SessionEnd shadow cleanup: attribution, missing
#                           session_id, missing dir, CP_SHADOW_DIR override
#   post-edit-check.sh      findings → stderr + exit 2; clean → silent exit 0
#   skill-suggest.sh        synchronous delivery, bounded by an in-script
#                           `timeout 5` even when the content probe hangs
#   settings-hooks.json     the wiring that makes all three reachable
#
# Every path is redirected to throwaway dirs under /tmp; the real ~/.claude and
# the real /tmp/claude-edit-shadows are never touched. No API calls.
#
# Usage:
#   bash tests/test-hooks.sh        # Run all tests
#   bash tests/test-hooks.sh -v     # Verbose mode

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLEANUP_HOOK="$REPO_ROOT/configs/hooks/session-end-cleanup.sh"
POST_EDIT_HOOK="$REPO_ROOT/configs/hooks/post-edit-check.sh"
SKILL_SUGGEST="$REPO_ROOT/configs/hooks/skill-suggest.sh"
SETTINGS="$REPO_ROOT/configs/settings-hooks.json"

# ─── Test framework (mirrors tests/test-correction-pairing.sh) ───────
TESTS_RUN=0; TESTS_PASSED=0; TESTS_FAILED=0
VERBOSE="${1:-}"
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'

pass() { TESTS_RUN=$((TESTS_RUN + 1)); TESTS_PASSED=$((TESTS_PASSED + 1)); echo -e "  ${GREEN}✓${NC} $1"; }
fail() {
  TESTS_RUN=$((TESTS_RUN + 1)); TESTS_FAILED=$((TESTS_FAILED + 1))
  echo -e "  ${RED}✗${NC} $1"
  [[ -n "${2:-}" ]] && echo -e "    ${RED}→ $2${NC}"
  return 0
}
section() { echo ""; echo -e "${YELLOW}━━━ $1 ━━━${NC}"; }

assert_eq() {
  local got="$1" want="$2" msg="$3"
  if [[ "$got" == "$want" ]]; then pass "$msg"
  else fail "$msg" "got '$got', want '$want'"; fi
}
assert_contains() {
  local haystack="$1" needle="$2" msg="$3"
  if grep -qF "$needle" <<< "$haystack"; then pass "$msg"
  else
    fail "$msg" "output does not contain '$needle'"
    [[ "$VERBOSE" == "-v" ]] && echo "    output: $(head -8 <<< "$haystack")"
  fi
}

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found — skipping (CI installs jq)"; exit 0
fi

# ─── Sandbox ─────────────────────────────────────────────────────────
TMP_ROOT="$(mktemp -d /tmp/clade-hooks-test-XXXXXX)"
case "$TMP_ROOT" in
  /tmp/clade-hooks-test-*) : ;;
  *) echo "FATAL: sandbox '$TMP_ROOT' is not under /tmp — aborting"; exit 1 ;;
esac
trap 'rm -rf "$TMP_ROOT"' EXIT
export HOME="$TMP_ROOT/home"
mkdir -p "$HOME/.claude"

SID_A="aaaaaaaa-1111-2222-3333-444444444444"
SID_B="bbbbbbbb-5555-6666-7777-888888888888"

# ─── 1. session-end-cleanup.sh ───────────────────────────────────────

section "session-end-cleanup.sh — SessionEnd shadow cleanup"

# --- happy path: deletes the ending session's shadow, spares a live one ---
SHADOWS="$TMP_ROOT/shadows"
mkdir -p "$SHADOWS"
printf '{"timestamp":"t","file":"a.py"}\n' > "$SHADOWS/session-$SID_A.jsonl"
printf '{"timestamp":"t","file":"b.py"}\n' > "$SHADOWS/session-$SID_B.jsonl"

out=$(printf '{"session_id":"%s","hook_event_name":"SessionEnd","reason":"clear"}' "$SID_A" \
  | CP_SHADOW_DIR="$SHADOWS" bash "$CLEANUP_HOOK" 2>&1)
rc=$?

assert_eq "$rc" "0" "exits 0 on happy path"
[[ -f "$SHADOWS/session-$SID_A.jsonl" ]] \
  && fail "removes the ending session's shadow" "file still present" \
  || pass "removes the ending session's shadow"
[[ -f "$SHADOWS/session-$SID_B.jsonl" ]] \
  && pass "leaves a parallel live session's shadow intact" \
  || fail "leaves a parallel live session's shadow intact" "collateral deletion"
assert_eq "$out" "" "produces no output on the happy path"

# --- every SessionEnd reason is handled (no matcher in the wiring) ---
for reason in logout prompt_input_exit other; do
  printf '{"timestamp":"t","file":"a.py"}\n' > "$SHADOWS/session-$SID_A.jsonl"
  printf '{"session_id":"%s","hook_event_name":"SessionEnd","reason":"%s"}' "$SID_A" "$reason" \
    | CP_SHADOW_DIR="$SHADOWS" bash "$CLEANUP_HOOK" >/dev/null 2>&1
  [[ -f "$SHADOWS/session-$SID_A.jsonl" ]] \
    && fail "cleans up on reason=$reason" "shadow survived" \
    || pass "cleans up on reason=$reason"
done

# --- missing session_id: must NOT guess (the $PPID fallback would hit
#     another session's file), must not delete anything, must exit 0 ---
printf '{"timestamp":"t","file":"a.py"}\n' > "$SHADOWS/session-$SID_A.jsonl"
printf '{"timestamp":"t","file":"b.py"}\n' > "$SHADOWS/session-$SID_B.jsonl"
printf '{"timestamp":"t","file":"c.py"}\n' > "$SHADOWS/session-pid-$$.jsonl"
before=$(ls "$SHADOWS" | sort | tr '\n' ' ')

out=$(printf '{"hook_event_name":"SessionEnd","reason":"other"}' \
  | CP_SHADOW_DIR="$SHADOWS" bash "$CLEANUP_HOOK" 2>&1)
rc=$?
after=$(ls "$SHADOWS" | sort | tr '\n' ' ')

assert_eq "$rc" "0" "exits 0 when session_id is absent"
assert_eq "$after" "$before" "deletes nothing when session_id is absent"
assert_eq "$out" "" "silent when session_id is absent"

# empty-string session_id is the same case as absent
out=$(printf '{"session_id":"","hook_event_name":"SessionEnd"}' \
  | CP_SHADOW_DIR="$SHADOWS" bash "$CLEANUP_HOOK" 2>&1)
rc=$?
after=$(ls "$SHADOWS" | sort | tr '\n' ' ')
assert_eq "$rc" "0" "exits 0 on empty session_id"
assert_eq "$after" "$before" "deletes nothing on empty session_id"

# malformed / empty stdin must not explode
for bad in '' 'not json at all' '{'; do
  printf '%s' "$bad" | CP_SHADOW_DIR="$SHADOWS" bash "$CLEANUP_HOOK" >/dev/null 2>&1
  assert_eq "$?" "0" "exits 0 on malformed stdin ($(printf '%.12s' "${bad:-<empty>}"))"
done

# --- missing shadow directory: degrade safely, do not create it ---
MISSING_DIR="$TMP_ROOT/no-such-shadow-dir"
out=$(printf '{"session_id":"%s","hook_event_name":"SessionEnd"}' "$SID_A" \
  | CP_SHADOW_DIR="$MISSING_DIR" bash "$CLEANUP_HOOK" 2>&1)
rc=$?
assert_eq "$rc" "0" "exits 0 when the shadow dir does not exist"
assert_eq "$out" "" "silent when the shadow dir does not exist"
[[ -e "$MISSING_DIR" ]] \
  && fail "does not create the shadow dir" "cleanup created $MISSING_DIR" \
  || pass "does not create the shadow dir"

# --- shadow dir exists but this session never wrote a shadow ---
out=$(printf '{"session_id":"%s","hook_event_name":"SessionEnd"}' "cccccccc-0000-0000-0000-000000000000" \
  | CP_SHADOW_DIR="$SHADOWS" bash "$CLEANUP_HOOK" 2>&1)
assert_eq "$?" "0" "exits 0 when this session has no shadow file"
assert_eq "$out" "" "silent when this session has no shadow file"

# --- CP_SHADOW_DIR override is honoured (not the /tmp default) ---
ALT="$TMP_ROOT/alt-shadows"
mkdir -p "$ALT"
printf '{"timestamp":"t","file":"a.py"}\n' > "$ALT/session-$SID_A.jsonl"
printf '{"session_id":"%s","hook_event_name":"SessionEnd"}' "$SID_A" \
  | CP_SHADOW_DIR="$ALT" bash "$CLEANUP_HOOK" >/dev/null 2>&1
[[ -f "$ALT/session-$SID_A.jsonl" ]] \
  && fail "honours the CP_SHADOW_DIR override" "file in the override dir survived" \
  || pass "honours the CP_SHADOW_DIR override"

# --- path traversal in session_id cannot escape the shadow dir ---
CANARY="$TMP_ROOT/canary.jsonl"
printf 'do not delete me\n' > "$CANARY"
printf '{"session_id":"../canary","hook_event_name":"SessionEnd"}' \
  | CP_SHADOW_DIR="$SHADOWS" bash "$CLEANUP_HOOK" >/dev/null 2>&1
[[ -f "$CANARY" ]] \
  && pass "a traversal session_id cannot delete outside the shadow dir" \
  || fail "a traversal session_id cannot delete outside the shadow dir" "canary was deleted"

# --- round trip against the real writer: what edit-shadow-detector
#     creates is exactly what cleanup removes (no key-derivation drift) ---
RT="$TMP_ROOT/roundtrip"
mkdir -p "$RT"
printf '{"session_id":"%s","tool_input":{"file_path":"/x/y.py"}}' "$SID_A" \
  | CP_SHADOW_DIR="$RT" bash "$REPO_ROOT/configs/hooks/edit-shadow-detector.sh" >/dev/null 2>&1
written=$(ls "$RT" 2>/dev/null | wc -l | tr -d ' ')
printf '{"session_id":"%s","hook_event_name":"SessionEnd"}' "$SID_A" \
  | CP_SHADOW_DIR="$RT" bash "$CLEANUP_HOOK" >/dev/null 2>&1
remaining=$(ls "$RT" 2>/dev/null | wc -l | tr -d ' ')
if [[ "$written" == "1" && "$remaining" == "0" ]]; then
  pass "cleans up the exact file edit-shadow-detector writes"
else
  fail "cleans up the exact file edit-shadow-detector writes" \
    "wrote $written file(s), $remaining left after cleanup"
fi

# ─── 2. post-edit-check.sh ───────────────────────────────────────────

section "post-edit-check.sh — asyncRewake exit-2 delivery"

PROJ="$TMP_ROOT/proj"
mkdir -p "$PROJ"
git -C "$PROJ" init -q 2>/dev/null
git -C "$PROJ" config user.email "test@example.com"
git -C "$PROJ" config user.name "Test"
printf 'one\n' > "$PROJ/a.txt"; printf 'two\n' > "$PROJ/b.txt"; printf 'three\n' > "$PROJ/c.txt"
git -C "$PROJ" add -A >/dev/null 2>&1
git -C "$PROJ" commit -qm "base" >/dev/null 2>&1

run_post_edit() {  # <file_path> → sets RC / STDOUT_F / STDERR_F
  STDOUT_F="$TMP_ROOT/pe.out"; STDERR_F="$TMP_ROOT/pe.err"
  printf '{"tool_input":{"file_path":"%s"}}' "$1" \
    | CLAUDE_PROJECT_DIR="$PROJ" bash "$POST_EDIT_HOOK" \
      >"$STDOUT_F" 2>"$STDERR_F"
  RC=$?
}

# --- clean tree, unchecked file type: silent success, must NOT wake Claude ---
run_post_edit "$PROJ/a.txt"
assert_eq "$RC" "0" "clean check exits 0"
assert_eq "$(cat "$STDOUT_F")" "" "clean check writes nothing to stdout"
assert_eq "$(cat "$STDERR_F")" "" "clean check writes nothing to stderr (no wake)"

# --- a couple of dirty files must NOT wake Claude on the default threshold ---
# Every exit 2 interrupts the turn, and ordinary work sits above 2 uncommitted
# files almost permanently; a per-edit wake would train Claude to ignore the
# channel. Guards the default, so lowering it back is a visible test failure.
printf 'one changed\n' > "$PROJ/a.txt"
printf 'two changed\n' > "$PROJ/b.txt"
run_post_edit "$PROJ/a.txt"
assert_eq "$RC" "0" "2 dirty files stay below the default threshold (no wake)"
assert_eq "$(cat "$STDERR_F")" "" "sub-threshold dirty tree writes nothing to stderr"

# --- uncommitted files at/over the threshold: finding reaches stderr, exit 2 ---
# Pin the threshold explicitly: this asserts the delivery contract, not the
# default's value, which the assertions above own.
COMMIT_REMINDER_THRESHOLD=2
export COMMIT_REMINDER_THRESHOLD
run_post_edit "$PROJ/a.txt"
assert_eq "$RC" "2" "uncommitted-file finding exits 2 (asyncRewake wake signal)"
assert_contains "$(cat "$STDERR_F")" "files edited without commit" \
  "uncommitted-file finding is written to stderr"
assert_contains "$(cat "$STDERR_F")" "committer" \
  "uncommitted-file finding keeps the actionable committer hint"
assert_eq "$(cat "$STDOUT_F")" "" "findings do not go to stdout"

# Regression: the finding must be plain text on stderr, not the old
# {"systemMessage": ...} JSON that a background hook threw away.
if grep -q 'systemMessage' "$STDERR_F"; then
  fail "no longer emits the discarded systemMessage envelope" "stderr still has systemMessage"
else
  pass "no longer emits the discarded systemMessage envelope"
fi
unset COMMIT_REMINDER_THRESHOLD

# --- below the threshold: one dirty file → silent ---
git -C "$PROJ" checkout -- . >/dev/null 2>&1
printf 'only one changed\n' > "$PROJ/a.txt"
run_post_edit "$PROJ/a.txt"
assert_eq "$RC" "0" "one dirty file stays under the threshold and exits 0"
assert_eq "$(cat "$STDERR_F")" "" "under-threshold run stays silent"

# --- threshold is overridable ---
COMMIT_REMINDER_THRESHOLD=1
export COMMIT_REMINDER_THRESHOLD
run_post_edit "$PROJ/a.txt"
assert_eq "$RC" "2" "COMMIT_REMINDER_THRESHOLD=1 makes one dirty file a finding"
unset COMMIT_REMINDER_THRESHOLD

# --- both findings survive into a single wake ---
# A .py file with a syntax error trips the type check; keeping the tree dirty
# trips the commit reminder. asyncRewake fires once, so one message must carry
# both — emitting them separately dropped whichever came second.
# Threshold pinned low so the fixture only needs a couple of dirty files; the
# default's value is asserted separately above.
if command -v ruff >/dev/null 2>&1 || command -v pyright >/dev/null 2>&1 || command -v mypy >/dev/null 2>&1; then
  COMMIT_REMINDER_THRESHOLD=2
  export COMMIT_REMINDER_THRESHOLD
  printf 'def broken(:\n' > "$PROJ/broken.py"
  printf 'still dirty\n' > "$PROJ/b.txt"
  run_post_edit "$PROJ/broken.py"
  assert_eq "$RC" "2" "type-check failure exits 2"
  err="$(cat "$STDERR_F")"
  if grep -qF "broken.py" <<< "$err" && grep -qF "files edited without commit" <<< "$err"; then
    pass "type-check and commit findings arrive together in one wake"
  else
    fail "type-check and commit findings arrive together in one wake" \
      "stderr: $(head -5 <<< "$err")"
  fi
  rm -f "$PROJ/broken.py"
  unset COMMIT_REMINDER_THRESHOLD
else
  echo "  (no python type-checker available — skipping combined-findings case)"
fi

# --- no file_path: no-op ---
out=$(printf '{}' | CLAUDE_PROJECT_DIR="$PROJ" bash "$POST_EDIT_HOOK" 2>&1)
assert_eq "$?" "0" "exits 0 when tool_input.file_path is absent"
assert_eq "$out" "" "silent when tool_input.file_path is absent"

git -C "$PROJ" checkout -- . >/dev/null 2>&1

# ─── 3. skill-suggest.sh ─────────────────────────────────────────────

section "skill-suggest.sh — synchronous delivery, bounded latency"

THROTTLE="$TMP_ROOT/throttle"
fresh_throttle() { rm -rf "$THROTTLE"; mkdir -p "$THROTTLE"; }

# --- still delivers additionalContext (the whole point of going sync) ---
fresh_throttle
out=$(printf '{"tool_input":{"file_path":"src/blog/posts/hello.md"}}' \
  | SKILL_SUGGEST_THROTTLE_DIR="$THROTTLE" bash "$SKILL_SUGGEST" 2>/dev/null)
assert_eq "$?" "0" "exits 0 on a matching path"
ctx=$(jq -r '.hookSpecificOutput.additionalContext // empty' <<< "$out" 2>/dev/null)
if [[ -n "$ctx" ]]; then
  pass "emits hookSpecificOutput.additionalContext (deliverable only when sync)"
else
  fail "emits hookSpecificOutput.additionalContext" "output: $(head -3 <<< "$out")"
fi
assert_contains "$out" "blog-seo-check" "suggestion content survives the timeout re-exec"

# --- no match → no output ---
fresh_throttle
out=$(printf '{"tool_input":{"file_path":"/tmp/plain.zzz"}}' \
  | SKILL_SUGGEST_THROTTLE_DIR="$THROTTLE" bash "$SKILL_SUGGEST" 2>/dev/null)
assert_eq "$out" "" "silent on a non-matching path"

# --- BOUNDED: a hanging content probe must not hold the Edit/Write open.
#     A fifo with no writer blocks `grep application/ld+json "$FILE_PATH"`
#     forever — this is the unbounded step the in-script guard exists for. ---
if command -v timeout >/dev/null 2>&1 && command -v mkfifo >/dev/null 2>&1; then
  fresh_throttle
  FIFO="$TMP_ROOT/hangfile.html"   # must not match schema/sitemap/etc. by name
  mkfifo "$FIFO"
  start=$(date +%s)
  printf '{"tool_input":{"file_path":"%s"}}' "$FIFO" \
    | SKILL_SUGGEST_THROTTLE_DIR="$THROTTLE" bash "$SKILL_SUGGEST" >/dev/null 2>&1
  rc=$?
  elapsed=$(( $(date +%s) - start ))
  rm -f "$FIFO"

  if [[ $elapsed -le 8 ]]; then
    pass "a hanging content probe is killed by the in-script bound (${elapsed}s)"
  else
    fail "a hanging content probe is killed by the in-script bound" \
      "took ${elapsed}s — the timeout 5 guard did not bound the body"
  fi
  assert_eq "$rc" "0" "a timeout kill surfaces as exit 0, never as a hook failure"
else
  echo "  (timeout/mkfifo unavailable — skipping bounded-latency case)"
fi

# --- the guard is real, and cannot recurse ---
grep -qE 'timeout 5 bash "\$0"' "$SKILL_SUGGEST" \
  && pass "script re-execs its body under 'timeout 5'" \
  || fail "script re-execs its body under 'timeout 5'"
grep -q 'SKILL_SUGGEST_INNER' "$SKILL_SUGGEST" \
  && pass "re-exec is guarded against infinite recursion" \
  || fail "re-exec is guarded against infinite recursion"

# The inner invocation must run the body directly, not fork again.
fresh_throttle
out=$(printf '{"tool_input":{"file_path":"src/blog/posts/hello.md"}}' \
  | SKILL_SUGGEST_INNER=1 SKILL_SUGGEST_THROTTLE_DIR="$THROTTLE" bash "$SKILL_SUGGEST" 2>/dev/null)
assert_contains "$out" "additionalContext" "inner (already-bounded) invocation runs the body"

# ─── 4. settings-hooks.json wiring ───────────────────────────────────
# A hook script that is not wired is dead code; assert the delivery channel.

section "settings-hooks.json — delivery wiring"

jq -e . "$SETTINGS" >/dev/null 2>&1 \
  && pass "settings-hooks.json is valid JSON" \
  || fail "settings-hooks.json is valid JSON"

jq -e '[.hooks.SessionEnd[].hooks[].id] | index("session-end-cleanup")' "$SETTINGS" >/dev/null 2>&1 \
  && pass "session-end-cleanup registered on SessionEnd" \
  || fail "session-end-cleanup registered on SessionEnd"

jq -e '.hooks.SessionEnd[] | select([.hooks[].id] | index("session-end-cleanup")) | has("matcher") | not' \
  "$SETTINGS" >/dev/null 2>&1 \
  && pass "SessionEnd cleanup has no matcher (fires on every end reason)" \
  || fail "SessionEnd cleanup has no matcher (fires on every end reason)"

jq -e '.hooks.SessionEnd[].hooks[] | select(.id=="session-end-cleanup")
       | .command | test("session-end-cleanup\\.sh")' "$SETTINGS" >/dev/null 2>&1 \
  && pass "SessionEnd cleanup points at session-end-cleanup.sh" \
  || fail "SessionEnd cleanup points at session-end-cleanup.sh"

jq -e '.hooks.PostToolUse[].hooks[] | select(.id=="post-edit-check") | .asyncRewake == true' \
  "$SETTINGS" >/dev/null 2>&1 \
  && pass "post-edit-check has asyncRewake: true" \
  || fail "post-edit-check has asyncRewake: true"

# asyncRewake implies async (Claude Code command-hook field reference), so a
# separate async: true is dead config. The command-hook schema is also closed:
# type/command/args/async/asyncRewake/shell/if/timeout/statusMessage/once. Fields
# invented around the wake — rewakeMessage, rewakeSummary — read as real settings
# while doing nothing, and `claude plugin validate --strict` flags them as
# unrecognized. Wake text belongs in the hook's own stderr.
jq -e '.hooks.PostToolUse[].hooks[] | select(.id=="post-edit-check") | has("async") | not' \
  "$SETTINGS" >/dev/null 2>&1 \
  && pass "post-edit-check drops redundant async (asyncRewake implies it)" \
  || fail "post-edit-check drops redundant async (asyncRewake implies it)"

jq -e '.hooks.PostToolUse[].hooks[] | select(.id=="post-edit-check")
       | has("rewakeMessage") or has("rewakeSummary") | not' \
  "$SETTINGS" >/dev/null 2>&1 \
  && pass "post-edit-check carries no invented rewake* fields" \
  || fail "post-edit-check carries no invented rewake* fields"

jq -e '.hooks.PostToolUse[].hooks[] | select(.id=="skill-suggest") | has("async") | not' \
  "$SETTINGS" >/dev/null 2>&1 \
  && pass "skill-suggest is synchronous (no async flag)" \
  || fail "skill-suggest is synchronous (no async flag)"

jq -e '.hooks.PostToolUse[].hooks[] | select(.id=="skill-suggest") | has("asyncRewake") | not' \
  "$SETTINGS" >/dev/null 2>&1 \
  && pass "skill-suggest does not wake Claude for advisory hints" \
  || fail "skill-suggest does not wake Claude for advisory hints"

# Existing behaviour that must not regress (goal-file success criteria).
jq -e '.hooks.UserPromptSubmit[].hooks[] | select(.id=="secret-scanner") | has("async") | not' \
  "$SETTINGS" >/dev/null 2>&1 \
  && pass "secret-scanner stays synchronous" \
  || fail "secret-scanner stays synchronous"

jq -e '.hooks.PostToolUse[].hooks[] | select(.id=="edit-shadow-detector") | .async == true' \
  "$SETTINGS" >/dev/null 2>&1 \
  && pass "edit-shadow-detector stays async (silent signal, data only)" \
  || fail "edit-shadow-detector stays async (silent signal, data only)"

jq -e '.hooks.SessionStart[] | select(.matcher=="startup|clear|fork")' "$SETTINGS" >/dev/null 2>&1 \
  && pass "SessionStart baseline still covers startup|clear|fork" \
  || fail "SessionStart baseline still covers startup|clear|fork"

# ─── type:prompt hooks must carry statusMessage ──────────────────────
# Without it Claude Code renders the hook's ENTIRE prompt into the UI. The
# rule was written down in 2026-04 and violated anyway by precompact-state-save,
# whose prompt is ~900 chars — dumped at the exact moment context is scarce and
# the user is least able to absorb it. Prose did not hold the line; this does.
_missing=$(jq -r '
  .hooks | to_entries[] as $ev
  | $ev.value[]?.hooks[]?
  | select(.type=="prompt")
  | select((.statusMessage // "") == "")
  | "\($ev.key)/\(.id // "<no id>")"' "$SETTINGS" 2>/dev/null)
if [[ -z "$_missing" ]]; then
  pass "every type:prompt hook carries a statusMessage"
else
  fail "every type:prompt hook carries a statusMessage" "missing on: $(tr '\n' ' ' <<< "$_missing")"
fi

# ─── worker-checkpoint: per-tool-call workspace snapshots ─────────────────────
# A worker commits exactly once, at the end of verification, and stop()
# force-removes the worktree — so "correct at call 14, wrong at 15" had no
# record anywhere. This hook writes one commit per Edit/Write into a shadow
# repo OUTSIDE the worktree.
section "worker-checkpoint hook"

CK_HOOK="$REPO_ROOT/configs/hooks/worker-checkpoint.sh"
CK_ROOT=$(mktemp -d /tmp/clade-ck-XXXXXX)
mkdir -p "$CK_ROOT/wt"
( cd "$CK_ROOT/wt" && git init -q . && git config user.email t@e.com && git config user.name t \
  && echo v1 > f.txt && git add -A && git commit -q -m base ) >/dev/null 2>&1

ck_write() {  # $1 = new content
  echo "$1" > "$CK_ROOT/wt/f.txt"
  printf '{"tool_name":"Write","tool_input":{"file_path":"%s/wt/f.txt"}}' "$CK_ROOT" \
    | CLADE_WORKER_SHADOW_DIR="$CK_ROOT/shadow.git" CLADE_WORKER_WORKTREE="$CK_ROOT/wt" \
      bash "$CK_HOOK" >/dev/null 2>&1
}

# Inert without the env var — an interactive session must be untouched.
echo v0 > "$CK_ROOT/wt/f.txt"
printf '{"tool_name":"Write","tool_input":{"file_path":"%s/wt/f.txt"}}' "$CK_ROOT" \
  | bash "$CK_HOOK" >/dev/null 2>&1
if [[ -d "$CK_ROOT/shadow.git" ]]; then
  fail "hook is inert without CLADE_WORKER_SHADOW_DIR" "it created a shadow repo anyway"
else
  pass "hook is inert without CLADE_WORKER_SHADOW_DIR"
fi

ck_write v2; ck_write v3; ck_write v4
CK_N=$(git --git-dir="$CK_ROOT/shadow.git" rev-list --count HEAD 2>/dev/null || echo 0)
assert_eq "3" "$CK_N" "one checkpoint per tool call"

CK_OLD=$(git --git-dir="$CK_ROOT/shadow.git" show HEAD~2:f.txt 2>/dev/null)
assert_eq "v2" "$CK_OLD" "an earlier call's content is recoverable"

# The property the whole design rests on: a separate git-dir means a separate
# index, so checkpoints cannot contend with the worker's own commits.
CK_IDX_BEFORE=$(md5sum "$CK_ROOT/wt/.git/index" 2>/dev/null | cut -d' ' -f1)
ck_write v5
CK_IDX_AFTER=$(md5sum "$CK_ROOT/wt/.git/index" 2>/dev/null | cut -d' ' -f1)
assert_eq "$CK_IDX_BEFORE" "$CK_IDX_AFTER" "checkpointing never touches the worktree's own index"

( cd "$CK_ROOT/wt" && git add -A && git commit -q -m "worker commit" ) >/dev/null 2>&1 \
  && pass "the worker can still commit after a checkpoint" \
  || fail "the worker can still commit after a checkpoint"

# A repo-supplied pre-commit hook must not be able to block a checkpoint.
printf '#!/bin/sh\nexit 1\n' > "$CK_ROOT/wt/.git/hooks/pre-commit"
chmod +x "$CK_ROOT/wt/.git/hooks/pre-commit"
CK_N_BEFORE=$(git --git-dir="$CK_ROOT/shadow.git" rev-list --count HEAD)
ck_write v6
CK_N_AFTER=$(git --git-dir="$CK_ROOT/shadow.git" rev-list --count HEAD)
if [[ "$CK_N_AFTER" -gt "$CK_N_BEFORE" ]]; then
  pass "a hostile pre-commit hook cannot block a checkpoint"
else
  fail "a hostile pre-commit hook cannot block a checkpoint"
fi

# The shadow must live outside the worktree, or `git add -A` would sweep it in.
if ls -a "$CK_ROOT/wt" | grep -q shadow; then
  fail "the shadow repo lives outside the worktree" "found it inside"
else
  pass "the shadow repo lives outside the worktree"
fi

rm -rf "$CK_ROOT"

# ─── Summary ─────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ $TESTS_FAILED -eq 0 ]]; then
  echo -e "  ${GREEN}ALL PASSED${NC} ($TESTS_PASSED/$TESTS_RUN)"
else
  echo -e "  ${RED}$TESTS_FAILED FAILED${NC} / $TESTS_PASSED passed / $TESTS_RUN total"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

exit "$TESTS_FAILED"
