#!/usr/bin/env bash
# test-correction-pairing.sh — Tests for the correction-PAIRING pipeline:
#   edit-shadow-detector.sh  (records files Claude writes, keyed by session_id)
#   revert-detector.sh       (cross-refs the shadow → reverted_files + repeat)
#   correction-detector.sh   (surfaces the rejected files on an EXPLICIT correction)
#   lib/correction-pair.sh   (shared session-key + shadow-read helpers)
#
# All state is redirected to throwaway HOME / project / shadow dirs under /tmp;
# the real ~/.claude is never touched. No API calls.
#
# Usage:
#   bash tests/test-correction-pairing.sh        # Run all tests
#   bash tests/test-correction-pairing.sh -v     # Verbose mode

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHADOW_HOOK="$REPO_ROOT/configs/hooks/edit-shadow-detector.sh"
REVERT_HOOK="$REPO_ROOT/configs/hooks/revert-detector.sh"
CORRECTION_HOOK="$REPO_ROOT/configs/hooks/correction-detector.sh"

# ─── Test framework (mirrors tests/test-rule-injector.sh) ────────────
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
  if grep -qF "$needle" <<< "$haystack"; then
    fail "$msg" "output unexpectedly contains '$needle'"
    [[ "$VERBOSE" == "-v" ]] && echo "    output: $(head -8 <<< "$haystack")"
  else pass "$msg"; fi
}

if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found — skipping (CI installs jq)"; exit 0
fi

# ─── Sandbox ─────────────────────────────────────────────────────────
TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMP_ROOT"' EXIT
export HOME="$TMP_ROOT/home"
export CP_SHADOW_DIR="$TMP_ROOT/shadows"
mkdir -p "$HOME/.claude" "$CP_SHADOW_DIR"
HISTORY="$HOME/.claude/corrections/history.jsonl"

PROJ="$TMP_ROOT/proj"
mkdir -p "$PROJ/.git"           # makes it a "real" project (project-local rules path)
echo "# proj" > "$PROJ/CLAUDE.md"

SID="11111111-2222-3333-4444-555555555555"

shadow_in()    { jq -n --arg f "$1" --arg s "$2" '{tool_input:{file_path:$f}, session_id:$s}'; }
revert_in()    { jq -n --arg c "$1" --arg s "$2" '{tool_name:"Bash", tool_input:{command:$c}, session_id:$s}'; }
correct_in()   { jq -n --arg p "$1" --arg s "$2" '{prompt:$p, session_id:$s}'; }

# ─── 1. edit-shadow keys by session_id ───────────────────────────────
section "edit-shadow-detector — session_id keying"
shadow_in "$PROJ/src/app.py" "$SID" | bash "$SHADOW_HOOK"
shadow_in "$PROJ/src/util.py" "$SID" | bash "$SHADOW_HOOK"
SFILE="$CP_SHADOW_DIR/session-$SID.jsonl"
TESTS_RUN=$((TESTS_RUN + 1))
if [[ -f "$SFILE" ]]; then pass "shadow file created under session_id key"
else fail "shadow file created under session_id key" "missing $SFILE"; fi
assert_contains "$(cat "$SFILE" 2>/dev/null)" "src/app.py" "shadow records the written file"

# ─────────────────────────────────────────────────────────────────────

# ─── 2. revert-detector: a commit-scoped revert names no files ───────
# `git reset --hard` cannot take a pathspec (git rejects pathspec + --hard) and
# this hook is async on PreToolUse, so querying git would race the very command
# it describes. reverted_files is therefore [] and repeat is null — "not
# knowable", not "checked and found nothing". The loose session list survives
# under its true name, session_files.
section "revert-detector — commit-scoped revert (no pathspec)"
revert_in "git reset --hard HEAD~1" "$SID" | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
LAST=$(tail -n 1 "$HISTORY" 2>/dev/null)
assert_contains "$LAST" '"type":"implicit-revert"' "revert logged as implicit-revert"
assert_contains "$LAST" '"revert_scope":"commit"' "reset --hard is scope=commit"
assert_contains "$LAST" '"reverted_files":[]' "no file set is claimed for a commit-scoped revert"
assert_contains "$LAST" '"repeat":null' "repeat is null, not false, when nothing is knowable"
assert_contains "$(jq -c '.session_files' <<< "$LAST")" "src/app.py" "session_files keeps what Claude wrote (app.py)"
assert_contains "$(jq -c '.session_files' <<< "$LAST")" "src/util.py" "session_files keeps what Claude wrote (util.py)"

# ─── 3. revert-detector: reverted_files is the pathspec intersection ─
# The regression this guards: reverted_files used to be the whole session list,
# so reverting app.py also "reverted" util.py, and the NEXT revert of any file
# in the session overlapped it and came back repeat=true. Measured on a real
# history.jsonl: 21 records held exactly the 20-file cap, and 39 records carried
# repeat=true off that overlap.
section "revert-detector — reverted_files is the command's own pathspec"
revert_in "git checkout -- src/app.py" "$SID" | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
LAST=$(tail -n 1 "$HISTORY")
assert_contains "$LAST" '"revert_scope":"paths"' "checkout -- <path> is scope=paths"
assert_contains "$(jq -c '.reverted_files' <<< "$LAST")" "src/app.py" "reverted_files names the reverted file"
assert_not_contains "$(jq -c '.reverted_files' <<< "$LAST")" "src/util.py" "reverted_files excludes the file the command never named"
assert_contains "$LAST" '"repeat":false' "first pathspec revert of app.py is not a repeat"

# a genuine recurrence — same file reverted twice — is still repeat=true
revert_in "git checkout -- src/app.py" "$SID" | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
assert_contains "$(tail -n 1 "$HISTORY")" '"repeat":true' "second revert of the SAME file is a repeat"

# an unrelated file is NOT a recurrence (this returned true before the fix)
revert_in "git checkout -- src/other.py" "$SID" | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
LAST=$(tail -n 1 "$HISTORY")
assert_contains "$LAST" '"repeat":false' "reverting a DIFFERENT file is not a repeat"
assert_contains "$LAST" '"reverted_files":[]' "a path Claude never wrote intersects nothing"

# ─── 3b. the field-data record that motivated the fix ────────────────
# Verbatim shape from history.jsonl: a revert in ANOTHER repo, filed under this
# project, carrying 20 session files none of which the command named.
section "revert-detector — cd into a foreign repo"
revert_in "cd /tmp/other-repo && git checkout -- codex-rs/Cargo.lock" "$SID" \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
LAST=$(tail -n 1 "$HISTORY")
assert_contains "$LAST" '"reverted_files":[]' "a foreign-repo revert claims none of this session's files"
assert_contains "$LAST" "codex-rs/Cargo.lock" "revert_paths keeps the raw pathspec for audit"

# ─── 3c. flag parsing and compound commands ──────────────────────────
section "revert-detector — pathspec parsing"
revert_in "git restore --staged --source=HEAD~1 -- src/util.py" "$SID" \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
LAST=$(tail -n 1 "$HISTORY")
assert_contains "$(jq -c '.revert_paths' <<< "$LAST")" "src/util.py" "git restore: the path is kept"
assert_not_contains "$(jq -c '.revert_paths' <<< "$LAST")" "staged" "git restore: --staged is not a path"
assert_not_contains "$(jq -c '.revert_paths' <<< "$LAST")" "HEAD~1" "git restore: --source's value is not a path"

revert_in 'git status --short | grep py; git checkout -- src/app.py' "$SID" \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
assert_contains "$(jq -c '.revert_paths' <<< "$(tail -n 1 "$HISTORY")")" "src/app.py" \
  "compound command: only the git segment contributes a path"

revert_in "git checkout -- ." "$SID" | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
LAST=$(jq -c '.reverted_files' <<< "$(tail -n 1 "$HISTORY")")
assert_contains "$LAST" "src/app.py" "checkout -- . matches everything under the base (app.py)"
assert_contains "$LAST" "src/util.py" "checkout -- . matches everything under the base (util.py)"

# ─── 4. explicit correction surfaces the concrete pair (gate: open) ──
section "correction-detector — concrete signal on explicit correction"
OUT=$(correct_in "no, that's wrong — revert it, use the config value instead" "$SID" \
        | CLAUDE_PROJECT_DIR="$PROJ" bash "$CORRECTION_HOOK")
CTX=$(jq -r '.hookSpecificOutput.additionalContext // ""' <<< "$OUT" 2>/dev/null)
assert_contains "$CTX" "Concrete signal" "explicit correction injects the concrete-signal block"
assert_contains "$CTX" "src/app.py" "concrete signal lists the rejected file"

# ─── 5. GATE: no recent rejected change → no concrete signal (no noise) ─
section "correction-detector — gate stays shut without a rejected change"
PROJ2="$TMP_ROOT/proj2"; mkdir -p "$PROJ2/.git"; echo "# p2" > "$PROJ2/CLAUDE.md"
OUT2=$(correct_in "no, use tabs instead" "no-shadow-session-xyz" \
        | CLAUDE_PROJECT_DIR="$PROJ2" bash "$CORRECTION_HOOK")
CTX2=$(jq -r '.hookSpecificOutput.additionalContext // ""' <<< "$OUT2" 2>/dev/null)
assert_contains "$CTX2" "A user correction was detected" "correction still fires normally"
assert_not_contains "$CTX2" "Concrete signal" "no concrete-signal block when nothing was rejected"

# ─── 6. session-key fallback when session_id absent ──────────────────
section "lib — \$PPID fallback when session_id missing"
echo '{"tool_input":{"file_path":"/tmp/x/nokey.py"}}' | bash "$SHADOW_HOOK"
TESTS_RUN=$((TESTS_RUN + 1))
if ls "$CP_SHADOW_DIR"/session-pid-*.jsonl >/dev/null 2>&1; then
  pass "falls back to a pid-keyed shadow file without session_id"
else fail "falls back to a pid-keyed shadow file without session_id" "no session-pid-* file"; fi

# ─── 7. prompt redaction before persistence ──────────────────────────
# history.jsonl and cross-project-rules.jsonl are appended to disk and may sit
# on a shared mount at 0664. A credential pasted into a correction must never
# reach either file — the model still sees the prompt, the disk copy does not.
section "correction-detector — secrets masked before any disk write"

PROJ3="$TMP_ROOT/proj3"; mkdir -p "$PROJ3/.git"; echo "# p3" > "$PROJ3/CLAUDE.md"
CROSS="$HOME/.claude/corrections/cross-project-rules.jsonl"

# Fake credentials, split so this file carries no contiguous scannable
# literal — checks.sh scans every staged diff and would block the commit
# that adds these very tests. Same convention as tests/test-checks.sh.
GH_TOKEN="ghp_""abcdefghijklmnopqrstuvwxyz0123456789"
correct_in "no, that's wrong, my token is $GH_TOKEN, put it back" "sess-redact-1" \
  | CLAUDE_PROJECT_DIR="$PROJ3" bash "$CORRECTION_HOOK" >/dev/null
REC="$(tail -n 1 "$HISTORY" 2>/dev/null)"
assert_contains "$REC" "<redacted:github_token>" "history.jsonl prompt field is masked"
assert_not_contains "$REC" "ghp_abcdefghijkl" "history.jsonl never holds the raw github token"
XREC="$(tail -n 1 "$CROSS" 2>/dev/null)"
assert_contains "$XREC" "<redacted:github_token>" "cross-project-rules.jsonl preview is masked"
assert_not_contains "$XREC" "ghp_abcdefghijkl" "cross-project preview never holds the raw token"

# Pairs the redact.py pattern widening with this write path: `sk_<hex>` is the
# shape that matched nothing before, and it only matters once the hook calls
# the redactor at all.
SK_KEY="sk_""d69f1a2b3c4d5e6f7081920a1b2c3d4e5f60718293a4b5c6"
correct_in "no, that's wrong, the key is $SK_KEY" "sess-redact-2" \
  | CLAUDE_PROJECT_DIR="$PROJ3" bash "$CORRECTION_HOOK" >/dev/null
REC2="$(tail -n 1 "$HISTORY" 2>/dev/null)"
assert_contains "$REC2" "<redacted:generic_secret_key>" "underscore-prefixed key masked end-to-end"
assert_not_contains "$REC2" "sk_d69f1a" "history.jsonl never holds the raw sk_ key"

# The redactor must not fail open when python3 is missing or broken — the
# documented failure mode is a malformed pattern raising at import. The
# degraded path detects and withholds rather than substituting, because a
# fixed-length substitution leaves the token's tail behind.
STUB="$TMP_ROOT/stub-nopy"; mkdir -p "$STUB"
printf '#!/bin/sh\nexit 1\n' > "$STUB/python3"; chmod +x "$STUB/python3"
AKIA_KEY="AKIA""IOSFODNN7EXAMPLE"
correct_in "no, that's wrong, the aws id is $AKIA_KEY" "sess-redact-3" \
  | PATH="$STUB:$PATH" CLAUDE_PROJECT_DIR="$PROJ3" bash "$CORRECTION_HOOK" >/dev/null
REC3="$(tail -n 1 "$HISTORY" 2>/dev/null)"
assert_contains "$REC3" "prompt withheld" "record is withheld when python3 is unavailable"
assert_not_contains "$REC3" "AKIAIOSFODNN7" "raw AWS key absent on the fallback path"

# ... and no tail of the key survives either. This is the assertion that a
# sed-substitution fallback would fail: it masks 32 of 48 chars and keeps 16.
correct_in "no, that's wrong, the key is $SK_KEY" "sess-redact-4" \
  | PATH="$STUB:$PATH" CLAUDE_PROJECT_DIR="$PROJ3" bash "$CORRECTION_HOOK" >/dev/null
REC4="$(tail -n 1 "$HISTORY" 2>/dev/null)"
assert_not_contains "$REC4" "5f60718293a4b5c6" "no trailing fragment of the key survives the fallback"

# The fallback must not over-withhold: a secret-free correction still keeps its
# text, which is the whole learning signal.
correct_in "no, that's wrong, use the config value instead" "sess-redact-5" \
  | PATH="$STUB:$PATH" CLAUDE_PROJECT_DIR="$PROJ3" bash "$CORRECTION_HOOK" >/dev/null
REC5="$(tail -n 1 "$HISTORY" 2>/dev/null)"
assert_contains "$REC5" "use the config value instead" "secret-free prompt keeps its text on the fallback path"

# Redaction sits BELOW the correction gate, so a non-correction prompt must
# still persist nothing at all. Pins the placement against a future move up.
BEFORE_N="$(wc -l < "$HISTORY" 2>/dev/null || echo 0)"
correct_in "please add a docstring to the parser" "sess-redact-6" \
  | CLAUDE_PROJECT_DIR="$PROJ3" bash "$CORRECTION_HOOK" >/dev/null
AFTER_N="$(wc -l < "$HISTORY" 2>/dev/null || echo 0)"
TESTS_RUN=$((TESTS_RUN + 1))
if [[ "$BEFORE_N" == "$AFTER_N" ]]; then
  pass "non-correction prompt persists nothing"
else fail "non-correction prompt persists nothing" "history grew $BEFORE_N → $AFTER_N"; fi

# ─── Summary ─────────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  Ran: $TESTS_RUN  ${GREEN}Passed: $TESTS_PASSED${NC}  ${RED}Failed: $TESTS_FAILED${NC}"
[[ "$TESTS_FAILED" -eq 0 ]] && { echo -e "  ${GREEN}ALL PASSED${NC}"; exit 0; } || { echo -e "  ${RED}FAILURES${NC}"; exit 1; }
