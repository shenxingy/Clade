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

# TESTS_RUN is incremented HERE, not in the assert wrappers. It used to live in
# the wrappers, so a bare pass/fail — the shape you need for any check that is
# not a string comparison — recorded a result without recording that it ran, and
# the summary printed "Ran: 45  Passed: 46". test-hooks.sh already counts this
# way; this file did not, and the mismatch was invisible until the two numbers
# disagreed out loud.
pass() { TESTS_RUN=$((TESTS_RUN + 1)); TESTS_PASSED=$((TESTS_PASSED + 1)); echo -e "  ${GREEN}✓${NC} $1"; }
fail() {
  TESTS_RUN=$((TESTS_RUN + 1)); TESTS_FAILED=$((TESTS_FAILED + 1))
  echo -e "  ${RED}✗${NC} $1"
  [[ -n "${2:-}" ]] && echo -e "    ${RED}→ $2${NC}"
}
section() { echo ""; echo -e "${YELLOW}━━━ $1 ━━━${NC}"; }

assert_contains() {
  local haystack="$1" needle="$2" msg="$3"
  if grep -qF "$needle" <<< "$haystack"; then pass "$msg"
  else
    fail "$msg" "output does not contain '$needle'"
    [[ "$VERBOSE" == "-v" ]] && echo "    output: $(head -8 <<< "$haystack")"
  fi
}
# Equality, not substring. `.project` has to be exactly the repository the
# command touched: asserting that the record merely CONTAINS a path passes when
# it holds the session's project and the foreign one both. This helper did not
# exist when the project-attribution assertions were first written, so those two
# calls ran as an undefined command — bash printed to stderr, the suite counted
# nothing, and the run stayed green at the same 39 tests. A test that cannot
# fail is the defect it was written to catch.
assert_eq() {
  local got="$1" want="$2" msg="$3"
  if [[ "$got" == "$want" ]]; then pass "$msg"
  else fail "$msg" "expected '$want', got '$got'"; fi
}
assert_not_contains() {
  local haystack="$1" needle="$2" msg="$3"
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
# correction-detector.sh is silent inside a dispatched worker (§5b). A /loop
# worker running this suite would inherit that marker and turn every
# correction case red for a reason unrelated to the code under test.
unset CLADE_WORKER_TASK_ID

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

# ─── 3a2. the history record carries the domain it is classified by ──
# session-scorecard.sh selects `.domain` from history.jsonl to decide which
# rules had a correction in their area. The field had never been written — 0 of
# 983 records — because domain detection ran AFTER the append and was nested
# inside the stats-file branch. Every record read back as `unknown`, so the
# domain match never fired and every rule was credited with a hit on every run.
section "correction-detector — the record carries its domain"
CD_HOOK="$REPO_ROOT/configs/hooks/correction-detector.sh"
printf '{"prompt":"no, that is wrong, you broke the build again"}' \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$CD_HOOK" >/dev/null 2>&1
CDREC=$(grep '"type":"explicit"' "$HISTORY" 2>/dev/null | tail -n 1)
assert_eq "$(jq -r 'has("domain")' <<< "${CDREC:-\{\}}" 2>/dev/null)" "true" \
  "an explicit correction record has a domain field"

# And the value has to be the DETECTED domain, not the "unknown" fallback that a
# missing field also produces downstream — asserting merely non-null would have
# passed before this fix too, since the reader defaults to unknown either way.
#
# detect_domain classifies `git diff` output, so this needs a REAL repository.
# $PROJ has only a `.git` directory, which is enough to look like a project and
# not enough for git to answer, so the fixture gets its own.
CD_REPO="$TMP_ROOT/domain-repo"
mkdir -p "$CD_REPO/src"
git -C "$CD_REPO" init -q >/dev/null 2>&1
git -C "$CD_REPO" config user.email t@example.com >/dev/null 2>&1
git -C "$CD_REPO" config user.name t >/dev/null 2>&1
echo "# repo" > "$CD_REPO/CLAUDE.md"
git -C "$CD_REPO" add -A >/dev/null 2>&1
git -C "$CD_REPO" commit -qm init >/dev/null 2>&1
: > "$CD_REPO/src/Widget.tsx"
git -C "$CD_REPO" add -A >/dev/null 2>&1
printf '{"prompt":"no, that is wrong, you broke the component again"}' \
  | CLAUDE_PROJECT_DIR="$CD_REPO" bash "$CD_HOOK" >/dev/null 2>&1
CDREC2=$(grep '"type":"explicit"' "$HISTORY" 2>/dev/null | tail -n 1)
assert_eq "$(jq -r '.domain' <<< "${CDREC2:-\{\}}" 2>/dev/null)" "frontend" \
  "the domain is the one detect_domain resolved, not the unknown fallback"


# ─── 3a2b. the domain survives a CLEAN tree ──────────────────────────
# The test above stages a file, which is why it never saw this: measured on the
# author's machine 2026-09-08, all 37 history records carrying `domain` were
# "unknown". Moving the call before the append fixed the field's ABSENCE, not
# its VALUE. The defect is the classifier's INPUT — `git diff --name-only
# --diff-filter=ACMR HEAD` exits 0 with EMPTY output on a clean tree, so the
# `||` fallbacks behind it were dead code and every grep missed. And
# UserPromptSubmit is exactly when the tree tends to be clean: the user says
# "that's wrong" after the work was committed.
section "correction-detector — domain on a clean tree"

CD_CLEAN="$TMP_ROOT/domain-clean"
mkdir -p "$CD_CLEAN/src"
git -C "$CD_CLEAN" init -q >/dev/null 2>&1
git -C "$CD_CLEAN" config user.email t@example.com >/dev/null 2>&1
git -C "$CD_CLEAN" config user.name t >/dev/null 2>&1
echo "# repo" > "$CD_CLEAN/CLAUDE.md"
: > "$CD_CLEAN/src/Widget.tsx"
git -C "$CD_CLEAN" add -A >/dev/null 2>&1
git -C "$CD_CLEAN" commit -qm "add widget" >/dev/null 2>&1
assert_eq "$(git -C "$CD_CLEAN" status --porcelain 2>/dev/null | wc -l | tr -d ' ')" "0" \
  "fixture tree is clean, the state the hook actually fires in"

# (a) with a session shadow: the files Claude WROTE decide the domain. This is
# the meaning the fix picks — a correction rejects what Claude did, and the
# shadow is the only record of that work which survives a commit.
CD_SID_A="cccccccc-1111-2222-3333-444444444444"
shadow_in "$CD_CLEAN/src/Widget.tsx" "$CD_SID_A" | bash "$SHADOW_HOOK"
correct_in "no, that is wrong, you broke the component again" "$CD_SID_A" \
  | CLAUDE_PROJECT_DIR="$CD_CLEAN" bash "$CORRECTION_HOOK" >/dev/null 2>&1
assert_eq "$(jq -r '.domain' <<< "$(grep '"type":"explicit"' "$HISTORY" | tail -n 1)")" "frontend" \
  "a clean tree still classifies, from the files Claude touched this session"

# (b) no shadow at all — an older Claude Code with no session_id, another
# machine, or a session whose first prompt is the correction. The last commit is
# the only evidence left, and it beats "unknown".
CD_SID_B="dddddddd-1111-2222-3333-444444444444"
correct_in "no, that is wrong, you broke the component again" "$CD_SID_B" \
  | CLAUDE_PROJECT_DIR="$CD_CLEAN" bash "$CORRECTION_HOOK" >/dev/null 2>&1
assert_eq "$(jq -r '.domain' <<< "$(grep '"type":"explicit"' "$HISTORY" | tail -n 1)")" "frontend" \
  "with no shadow, a clean tree falls back to the last commit, not unknown"

# (c) the priority order is the design decision, so it is pinned: when the two
# inputs disagree, what CLAUDE wrote wins over what happens to be uncommitted.
# The tree here holds a .py the user edited; the shadow holds Claude's .tsx.
CD_SID_C="eeeeeeee-1111-2222-3333-444444444444"
printf 'x = 1\n' > "$CD_CLEAN/src/user_edit.py"
shadow_in "$CD_CLEAN/src/Widget.tsx" "$CD_SID_C" | bash "$SHADOW_HOOK"
correct_in "no, that is wrong, you broke the component again" "$CD_SID_C" \
  | CLAUDE_PROJECT_DIR="$CD_CLEAN" bash "$CORRECTION_HOOK" >/dev/null 2>&1
assert_eq "$(jq -r '.domain' <<< "$(grep '"type":"explicit"' "$HISTORY" | tail -n 1)")" "frontend" \
  "the session shadow outranks the working tree when they disagree"
rm -f "$CD_CLEAN/src/user_edit.py"

# (d) the same starvation in the library itself, isolated from the hook.
# detect_domain with no argument must not answer "unknown" in a repository whose
# only evidence is its history.
section "domain-detect — a clean repository is still classifiable"
CD_LIB_OUT=$( cd "$CD_CLEAN" && source "$REPO_ROOT/configs/hooks/lib/domain-detect.sh" \
              && detect_domain && echo "$DOMAIN" )
assert_eq "$CD_LIB_OUT" "frontend" \
  "detect_domain with no argument classifies a clean tree from its last commit"

# An explicitly passed list must NOT cascade — a caller that names its own input
# gets an answer about that input, which is what tests/test-skill-routing.sh
# asserts of this same function.
CD_LIB_EXPL=$( cd "$CD_CLEAN" && source "$REPO_ROOT/configs/hooks/lib/domain-detect.sh" \
               && detect_domain "docs/readme.md" && echo "$DOMAIN" )
assert_eq "$CD_LIB_EXPL" "unknown" \
  "an explicit file list is classified as given, never widened to the repo"

# ─── 3a2c. stats.json seeds the classifier's whole vocabulary ────────
# `_STATS_SEED` listed nine of the thirteen domains detect_domain can return;
# devops, security, cli and mobile were missing, so those increments landed on a
# key nothing had ever seeded. jq's `// 0` hides it, but a fresh stats.json then
# advertises a smaller vocabulary than the classifier has — and `cli` is the
# single most likely domain for a shell-heavy repository.
section "correction-detector — the stats seed covers every domain"
CD_VOCAB=$(grep -oE 'DOMAIN="[a-z]+"' "$REPO_ROOT/configs/hooks/lib/domain-detect.sh" \
           | sed 's/^DOMAIN="//; s/"$//' | sort -u)
CD_SEED=$(grep -m1 '^_STATS_SEED=' "$CORRECTION_HOOK" | sed "s/^_STATS_SEED='//; s/'\$//")
CD_SEED_KEYS=$(jq -r 'keys[]' <<< "$CD_SEED" 2>/dev/null | sort -u)
CD_MISSING=$(comm -23 <(printf '%s\n' "$CD_VOCAB") <(printf '%s\n' "$CD_SEED_KEYS") | tr '\n' ' ' | sed 's/ *$//')
assert_eq "$CD_MISSING" "" "no domain detect_domain can return is missing from the stats seed"

# ─── 3a3. a corrupt stats.json self-heals instead of no-opping forever ─
# The increment is `jq … file > tmp && mv || rm -f tmp`, which fails silently on
# invalid JSON. The real file on the author's machine held two nested sets of
# unresolved git conflict markers, so every increment had been discarded for an
# unknown length of time — and a counter that stops counting looks exactly like
# a quiet week.
section "correction-detector — a corrupt stats.json is repaired, not ignored"
CD_STATS="$HOME/.claude/corrections/stats.json"
mkdir -p "$(dirname "$CD_STATS")"
printf '%s\n' '<<<<<<< Updated upstream' '{"frontend": 3}' '=======' '{"frontend": 9}' '>>>>>>> Stashed changes' > "$CD_STATS"
printf '{"prompt":"no, that is wrong, you broke the component again"}' \
  | CLAUDE_PROJECT_DIR="$CD_REPO" bash "$CD_HOOK" >/dev/null 2>&1
assert_eq "$(jq -e . "$CD_STATS" >/dev/null 2>&1 && echo valid || echo invalid)" "valid" \
  "a stats.json full of conflict markers is rebuilt into valid JSON"
CD_BUMPED=$(jq -r '.frontend // 0' "$CD_STATS" 2>/dev/null)
if [[ "${CD_BUMPED:-0}" -ge 1 ]]; then
  pass "the correction that found it is still counted (frontend=$CD_BUMPED)"
else
  fail "the correction that found it is still counted" "frontend=$CD_BUMPED"
fi
CD_SAVED=$(ls "$HOME/.claude/corrections/"stats.json.corrupt.* 2>/dev/null | wc -l)
assert_eq "$CD_SAVED" "1" "the unreadable file is kept beside it, not discarded"

# ─── 3b. the field-data record that motivated the fix ────────────────
# Verbatim shape from history.jsonl: a revert in ANOTHER repo, filed under this
# project, carrying 20 session files none of which the command named.
section "revert-detector — cd into a foreign repo"
revert_in "cd /tmp/other-repo && git checkout -- codex-rs/Cargo.lock" "$SID" \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
LAST=$(tail -n 1 "$HISTORY")
assert_contains "$LAST" '"reverted_files":[]' "a foreign-repo revert claims none of this session's files"
assert_contains "$LAST" "codex-rs/Cargo.lock" "revert_paths keeps the raw pathspec for audit"

# The record must be filed under the repository the command touched, not the
# session's. 68 of 92 informative records on the author's machine began `cd
# <other repo> &&` and every one was filed under the session's project, so
# `repeat` compared a file against reverts in a repository it had never been in.
assert_eq "$(jq -r '.project' <<< "$LAST")" "/tmp/other-repo" \
  "the record is filed under the repo the command operated on"

# With no `cd`, the session's own directory is still the right answer.
revert_in "git checkout -- src/util.py" "$SID" \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
assert_eq "$(jq -r '.project' <<< "$(tail -n 1 "$HISTORY")")" "$PROJ" \
  "a plain revert is still filed under the session's project"

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

# ─── 3d. a shell redirection is plumbing, not a pathspec ─────────────
# Field data: 4 of the 7 real `revert_scope:"paths"` records on the author's
# machine filed a redirection token as a reverted path — `2>/dev/null`,
# `>/dev/null`, `2>`. Same defect class as workflow-scorecard.py's mutation
# guard matching the `>/` of `2>/dev/null` (CLAUDE.md), which is why it is
# pinned here rather than left to review.
section "revert-detector — redirections are not pathspecs"

revert_in 'git checkout -- .claude-plugin/ 2>/dev/null' "$SID" \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
LAST=$(jq -c '.revert_paths' <<< "$(tail -n 1 "$HISTORY")")
assert_contains "$LAST" ".claude-plugin/" "attached redirect: the real pathspec survives"
assert_not_contains "$LAST" "2>/dev/null" "attached redirect: 2>/dev/null is not a path"

revert_in 'git restore --staged :/ >/dev/null 2>&1' "$SID" \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
LAST=$(jq -c '.revert_paths' <<< "$(tail -n 1 "$HISTORY")")
assert_not_contains "$LAST" "/dev/null" "restore: >/dev/null is not a path"
assert_not_contains "$LAST" '"2>"' "restore: a bare 2> operator is not a path"

# The case that makes this a correctness bug and not just noise: a SEPARATED
# redirect target is a real filename, so the old parser could match it against
# the shadow and name a file the revert never touched.
revert_in 'git checkout -- src/app.py > src/util.py' "$SID" \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
LAST=$(tail -n 1 "$HISTORY")
assert_contains "$(jq -c '.reverted_files' <<< "$LAST")" "src/app.py" \
  "separated redirect: the reverted file is still found"
assert_not_contains "$(jq -c '.reverted_files' <<< "$LAST")" "src/util.py" \
  "separated redirect: the redirect TARGET is never reported as reverted"
assert_not_contains "$(jq -c '.revert_paths' <<< "$LAST")" "src/util.py" \
  "separated redirect: the redirect target is not a pathspec"

# ─── 3e. a mutation probe is the agent's own test, not a rejection ──
# The global CLAUDE.md requires deleting a guard and watching the test go red.
# Agents do it in one command — save the diff, `git checkout -- src`, test,
# `git apply` it back — and every one was recorded as an implicit-revert with
# its session files attached: seven on 2026-09-23 alone, two `repeat:true`, and
# correction-detector.sh surfaces those files to the next explicit correction.
section "revert-detector — a mutation probe carries no rejection evidence"

revert_in 'git diff -- src > /tmp/p.patch && git checkout -- src/app.py && npm test; git apply /tmp/p.patch' "$SID" \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
LAST=$(tail -n 1 "$HISTORY")
assert_contains "$LAST" '"revert_scope":"probe"' "revert then git apply is a probe"
assert_contains "$LAST" '"reverted_files":[]' "probe: no file is claimed as rejected"
assert_contains "$LAST" '"session_files":[]' "probe: the session list is not offered as evidence"
assert_contains "$LAST" '"repeat":null' "probe: repeat is not computed"
assert_contains "$(jq -c '.revert_paths' <<< "$LAST")" "src/app.py" "probe: the raw pathspec is still kept"

revert_in 'git stash && git checkout -- src/app.py && make test; git stash pop' "$SID" \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
assert_contains "$(tail -n 1 "$HISTORY")" '"revert_scope":"probe"' "revert then git stash pop is a probe"

# The sed-then-restore shape has no restore step after the revert — the revert
# IS the restore. The label identifies it; so, since §3h, does the edit itself.
revert_in 'echo "=== MUTATION A ==="; sed -i s/x/y/ src/app.py && npm test; git checkout -- src/app.py' "$SID" \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
assert_contains "$(tail -n 1 "$HISTORY")" '"revert_scope":"probe"' "a MUTATION-labelled command is a probe"
revert_in 'echo "=== MUTATION A ==="; git checkout -- src/app.py' "$SID" \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
assert_contains "$(tail -n 1 "$HISTORY")" '"revert_scope":"probe"' "the MUTATION label alone still marks a probe"

# Controls. A restore BEFORE the revert is not a round-trip, and a lowercase
# `mutation` in a real filename is not the label.
revert_in 'git apply fix.patch; git checkout -- src/app.py' "$SID" \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
LAST=$(tail -n 1 "$HISTORY")
assert_contains "$LAST" '"revert_scope":"paths"' "git apply BEFORE the revert: still a real revert"
assert_contains "$(jq -c '.reverted_files' <<< "$LAST")" "src/app.py" "git apply BEFORE the revert: evidence kept"
revert_in 'git checkout -- orchestrator/task_factory/mutation_scan.py' "$SID" \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
assert_contains "$(tail -n 1 "$HISTORY")" '"revert_scope":"paths"' "a file named mutation_*.py is not a probe"

# ─── 3f. the project is where the revert ran, not the text of a `cd` ──
# Field data 2026-09-21 → 09-28: records filed under the literal projects `$WT`
# and `$SCR/repo`, one under `~/projects/Clade`, and a `cd` AFTER the revert
# deciding the project of a revert that ran before it.
section "revert-detector — the cd target is resolved, not copied"

revert_in 'WT=/tmp/wt-a && cd "$WT" && git checkout -- src/app.py' "$SID" \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
assert_eq "$(jq -r '.project' <<< "$(tail -n 1 "$HISTORY")")" "/tmp/wt-a" \
  "a variable the command assigns is resolved"

revert_in 'WT=/tmp/wt-b; cd ${WT}/sub && git checkout -- src/app.py' "$SID" \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
assert_eq "$(jq -r '.project' <<< "$(tail -n 1 "$HISTORY")")" "/tmp/wt-b/sub" \
  "\${NAME}/suffix is resolved with its suffix"

revert_in 'cd "$UNSET_ELSEWHERE" && git checkout -- src/app.py' "$SID" \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
assert_eq "$(jq -r '.project' <<< "$(tail -n 1 "$HISTORY")")" "$PROJ" \
  "an unresolvable variable falls back to the session dir, never the raw text"

revert_in 'cd ~/repo-x && git checkout -- src/app.py' "$SID" \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
assert_eq "$(jq -r '.project' <<< "$(tail -n 1 "$HISTORY")")" "$HOME/repo-x" \
  "a leading ~ is expanded"

revert_in 'cd /tmp/svc && git checkout -- src/app.py && cd /tmp && echo done' "$SID" \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
assert_eq "$(jq -r '.project' <<< "$(tail -n 1 "$HISTORY")")" "/tmp/svc" \
  "a cd AFTER the revert does not decide where it ran"

revert_in 'cd /tmp/mono && cd backend && git checkout -- src/app.py' "$SID" \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
assert_eq "$(jq -r '.project' <<< "$(tail -n 1 "$HISTORY")")" "/tmp/mono/backend" \
  "a relative cd is joined to the directory before it"

# ─── 3g. a heredoc body is data, not a command ───────────────────────
# Field data 2026-09-28 21:48Z: a python heredoc rewriting a README that
# DOCUMENTED `git checkout -- …` and `cd ~/code/… && git pull` was logged as a
# revert, under a project taken from the README's own text. Nothing was reverted.
section "revert-detector — heredoc bodies are not parsed as commands"

# BSD wc pads its count with spaces; compare bare numbers.
hist_lines() { wc -l < "$HISTORY" | tr -d ' '; }
_before=$(hist_lines)
revert_in "cd /tmp/docs-repo && python3 - <<'EOF'
s = '''To ship it:
cd ~/code/elsewhere && git pull
git checkout -- site/static/palette.json
'''
open('README.md', 'w').write(s)
EOF
git status --short" "$SID" | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
assert_eq "$(hist_lines)" "$_before" "git text inside a heredoc body writes no record"

# A real revert AFTER the heredoc still counts, and the heredoc's `cd` text does
# not decide where it ran. The persisted prompt keeps the whole raw command.
revert_in "cd /tmp/svc-h && cat > notes.md <<EOF
cd ~/somewhere-else
EOF
git checkout -- src/app.py" "$SID" | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
LAST=$(tail -n 1 "$HISTORY")
assert_eq "$(jq -r '.project' <<< "$LAST")" "/tmp/svc-h" "a cd inside a heredoc body is not a cd"
assert_contains "$(jq -c '.revert_paths' <<< "$LAST")" "src/app.py" "a revert after the heredoc keeps its pathspec"
assert_contains "$(jq -r '.prompt' <<< "$LAST")" "somewhere-else" "the record keeps the raw command, body included"

# Controls. A here-string `<<<` is not a heredoc, so a revert after it on the
# next line still counts; and a `<<-` terminator may be tab-indented.
_before=$(hist_lines)
revert_in "jq -r .x <<< '{}'
git checkout -- src/app.py" "$SID" | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
assert_eq "$(hist_lines)" "$((_before + 1))" "a here-string does not swallow the next line"
_before=$(hist_lines)
revert_in "cat <<-END
	git checkout -- inside/body.py
	END
git checkout -- src/app.py" "$SID" | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
assert_eq "$(hist_lines)" "$((_before + 1))" "<<- ends at a tab-indented terminator"
assert_not_contains "$(jq -c '.revert_paths' <<< "$(tail -n 1 "$HISTORY")")" "inside/body.py" \
  "<<- body text is not read as a pathspec"

# ─── 3h. a revert of a file the same command edits is a probe ───────
# Field data 2026-10-05 → 10-12: 115 implicit-revert records, 0 marked probe,
# 64 of them edit-then-revert (or revert-then-edit) one file in one command with
# no label and no `git apply` — the dominant shape is `python3 - "$f" <<'EOF'`.
section "revert-detector — an edit and a revert of the same file in one command"

revert_in 'sed -i s/x/y/ src/app.py && npm test; git checkout -- src/app.py' "$SID" \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
LAST=$(tail -n 1 "$HISTORY")
assert_contains "$LAST" '"revert_scope":"probe"' "sed -i then revert of the same file is a probe"
assert_contains "$LAST" '"reverted_files":[]' "edit probe: no file is claimed as rejected"

revert_in 'F=src/app.py; sed -E -i "s/x/y/" "$F"; npm test; git checkout -- "$F"' "$SID" \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
assert_contains "$(tail -n 1 "$HISTORY")" '"revert_scope":"probe"' "a \$VAR pathspec matches the edit of \$VAR"

revert_in "f=src/app.py
python3 - \"\$f\" <<'EOF'
import sys
p = sys.argv[1]
open(p, 'a').write('#')
EOF
npm test
git checkout -- \$f" "$SID" | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
assert_contains "$(tail -n 1 "$HISTORY")" '"revert_scope":"probe"' "python3 - \"\$f\" <<EOF is an edit of \$f"

revert_in "git checkout -- src/app.py && python3 - <<'EOF'
p = 'src/app.py'
open(p, 'a').write('#')
EOF
npm test" "$SID" | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
assert_contains "$(tail -n 1 "$HISTORY")" '"revert_scope":"probe"' "restore then re-mutate via an interpreter body is a probe"

# Controls: an edit of ANOTHER file, a read-only sed, and a non-interpreter
# heredoc that merely names the file are not edits of what was reverted.
revert_in 'sed -i s/x/y/ src/other.py; git checkout -- src/app.py' "$SID" \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
LAST=$(tail -n 1 "$HISTORY")
assert_contains "$LAST" '"revert_scope":"paths"' "an edit of a different file is not a probe"
assert_contains "$(jq -c '.reverted_files' <<< "$LAST")" "src/app.py" "an edit of a different file: evidence kept"
revert_in 'sed -n 1,5p src/app.py; git checkout -- src/app.py' "$SID" \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
assert_contains "$(tail -n 1 "$HISTORY")" '"revert_scope":"paths"' "a read-only sed is not an edit"
revert_in "cat > notes.md <<EOF
see src/app.py
EOF
git checkout -- src/app.py" "$SID" | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
assert_contains "$(tail -n 1 "$HISTORY")" '"revert_scope":"paths"' "a cat heredoc naming the file is prose, not an edit"
revert_in "python3 - <<'EOF'
print('unrelated')
EOF
git checkout -- src/app.py" "$SID" | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
assert_contains "$(tail -n 1 "$HISTORY")" '"revert_scope":"paths"' "an interpreter body that never names the file is not an edit of it"
# The revert segment names the file by definition, so it must never be read as
# the edit: a comment about an EARLIER `sed -i` is a real revert of that edit.
revert_in 'git checkout -- src/app.py  # undo the earlier sed -i experiment' "$SID" \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$REVERT_HOOK"
assert_contains "$(tail -n 1 "$HISTORY")" '"revert_scope":"paths"' "the revert segment itself is never read as the edit"

# ─── 3i. only the main thread's reverts are the owner's signal ───────
# Field data 2026-09-22 → 10-22: 172 of 220 implicit-revert records were issued
# by Workflow subagents inside their own runs — mutation probes, worktree resets,
# cleanup — and every reader of history.jsonl counted them as the owner
# rejecting a change. Claude Code puts `agent_id` in the hook input exactly when
# the call runs inside a subagent; `agent_type` alone is the main thread of a
# `--agent` session. A dispatched worker carries CLADE_WORKER_TASK_ID instead.
section "revert-detector — a subagent's or worker's revert is not a correction"
revert_in_as() {   # <command> <session> <extra-json-object>
  jq -n --arg c "$1" --arg s "$2" --argjson x "$3" \
    '{tool_name:"Bash", tool_input:{command:$c}, session_id:$s} + $x'
}
# reverts_recorded <hook> <extra-json> [env-assignment] — how many records one
# revert of src/app.py adds. Shared with the mutation suite (§8).
reverts_recorded() {
  local hook="$1" extra="$2" before after
  before=$(hist_lines)
  revert_in_as 'git checkout -- src/app.py' "$SID" "$extra" \
    | env ${3:+"$3"} CLAUDE_PROJECT_DIR="$PROJ" bash "$hook"
  after=$(hist_lines)
  echo $(( after - before ))
}
assert_eq "$(reverts_recorded "$REVERT_HOOK" '{"agent_id":"a1b2c3d4e5f60718"}')" "0" \
  "a revert inside a subagent (agent_id set) writes no record"
assert_eq "$(reverts_recorded "$REVERT_HOOK" '{}' CLADE_WORKER_TASK_ID=batch-20261023-1)" "0" \
  "a revert inside a dispatched worker writes no record"
# Controls: the same revert on the main thread, a main thread started with
# --agent (agent_type, no agent_id), and a null agent_id are all recorded.
assert_eq "$(reverts_recorded "$REVERT_HOOK" '{}')" "1" \
  "control: the same revert on the main thread is recorded"
assert_eq "$(reverts_recorded "$REVERT_HOOK" '{"agent_type":"code-reviewer"}')" "1" \
  "control: agent_type without agent_id is the main thread, still recorded"
assert_eq "$(reverts_recorded "$REVERT_HOOK" '{"agent_id":null}')" "1" \
  "control: a null agent_id is the main thread, still recorded"

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
assert_contains "$CTX2" "A possible correction was detected" "correction still fires normally"
assert_not_contains "$CTX2" "Concrete signal" "no concrete-signal block when nothing was rejected"

# ─── 5b. precision: the user's own words, not hedges or pastes ───────
# Field data from one machine (230 explicit records, 19 projects): bare 应该
# ("probably") was the ONLY trigger for 80 of them, 要不要 ("whether") for 7,
# and in one project 25 of 83 came from text the user pasted or quoted. Each
# false fire told the model "a user correction was detected — write a rule".
section "correction-detector — fires on the user's words, not hedges or pastes"
fires() {
  correct_in "$1" "sess-precision" | CLAUDE_PROJECT_DIR="$PROJ2" bash "$CORRECTION_HOOK" 2>/dev/null \
    | jq -r '.hookSpecificOutput.additionalContext // ""' 2>/dev/null
}
_hist_before="$(wc -l < "$HISTORY" 2>/dev/null || echo 0)"
assert_eq "$(fires '应该是我起了一个头，他才发现已经毕业七年了')" "" "bare 应该 (probably) is not a correction"
assert_eq "$(fires '到底要不要买这个新手机？')" "" "要不要 (whether) is not a correction"
assert_eq "$(fires '帮我看看 <pasted_content id="ab12">Go back to filtering menu. Actually the X is better instead. 不对的尺码请退货</pasted_content>')" "" \
  "words inside a paste are not the user correcting"
assert_eq "$(fires '看看这个 <pasted_content id="u1">wrong, revert it, 不对')" "" "an unterminated paste is still a paste"
assert_eq "$(wc -l < "$HISTORY" 2>/dev/null || echo 0)" "$_hist_before" "none of those leaves a history record"
assert_contains "$(fires '你应该先读一下配置文件')" "keyword: '你应该'" "你应该 still fires, and the notice names the keyword"
assert_contains "$(fires '这个开关不应该放在最上面')" "keyword: '不应该'" "不应该 still fires"
assert_contains "$(fires '要不要加测试？不要用 mock')" "keyword: '不要'" "a real 不要 beside 要不要 still fires"
assert_contains "$(fires '不对，<pasted_content id="x1">plain page text</pasted_content> 用另一个')" "keyword: '不对'" \
  "a correction typed outside a paste still fires"
_ctx_en="$(fires 'no, that is wrong')"
assert_contains "$_ctx_en" "keyword: 'wrong'" "an English keyword is named without its boundary characters"
assert_contains "$_ctx_en" "First decide whether the user is rejecting something you did" \
  "the notice asks for a judgement before any rule is written"

# ─── 5c. conversation-mode projects ──────────────────────────────────
# A repository that is a conversation rather than a codebase (.claude/
# conversation-mode) gets a notice that asks for a one-line fix instead of a
# rule, and its text stays out of the cross-project log, which lives in the
# sync store with its own remote: one machine's copy already held 87 previews
# from such a repository.
section "correction-detector — conversation-mode projects"
_lines() { if [[ -f "$1" ]]; then wc -l < "$1" | tr -d ' '; else echo 0; fi; }
CROSS="$HOME/.claude/corrections/cross-project-rules.jsonl"
PROJC="$TMP_ROOT/proj-conv"; mkdir -p "$PROJC/.git" "$PROJC/.claude"; echo "# c" > "$PROJC/CLAUDE.md"
touch "$PROJC/.claude/conversation-mode"
_cross0=$(_lines "$CROSS"); _hist0=$(_lines "$HISTORY")
CTXC=$(correct_in "不对，是我起的头" "sess-conv" | CLAUDE_PROJECT_DIR="$PROJC" bash "$CORRECTION_HOOK" 2>/dev/null \
  | jq -r '.hookSpecificOutput.additionalContext // ""')
assert_contains "$CTXC" "This project is in conversation mode" "conversation mode gets the conversation notice"
assert_contains "$CTXC" "fix it in your reply in one plain sentence" "the notice asks for a one-line fix"
assert_not_contains "$CTXC" "Append a rule to" "conversation mode is not told to append a rule"
assert_not_contains "$CTXC" "Defect classes" "conversation mode does not get the code root-cause taxonomy"
assert_eq "$(_lines "$CROSS")" "$_cross0" "conversation text stays out of the synced cross-project log"
assert_eq "$(_lines "$HISTORY")" "$(( _hist0 + 1 ))" "the local history still counts it"
# Control: the same words in an ordinary project get the old notice and log.
CTXN=$(correct_in "不对，是我起的头" "sess-conv" | CLAUDE_PROJECT_DIR="$PROJ2" bash "$CORRECTION_HOOK" 2>/dev/null \
  | jq -r '.hookSpecificOutput.additionalContext // ""')
assert_contains "$CTXN" "Append a rule to" "control: an ordinary project still gets the rule-writing notice"
assert_eq "$(_lines "$CROSS")" "$(( _cross0 + 1 ))" "control: an ordinary project still feeds the cross-project log"
# A session marked private (a personal-mode skill touches the marker) behaves
# the same wherever it was started, here in an ordinary project.
mkdir -p "$HOME/.claude/private-sessions"; touch "$HOME/.claude/private-sessions/sess-private"
_cross1=$(_lines "$CROSS")
CTXP=$(correct_in "不对，你说反了" "sess-private" | CLAUDE_PROJECT_DIR="$PROJ2" bash "$CORRECTION_HOOK" 2>/dev/null \
  | jq -r '.hookSpecificOutput.additionalContext // ""')
assert_contains "$CTXP" "This project is in conversation mode" "a private session gets the conversation notice"
assert_contains "$CTXP" "write nothing about this conversation under ~/.claude" "the notice keeps the session out of the synced directory"
assert_eq "$(_lines "$CROSS")" "$_cross1" "a private session writes nothing to the cross-project log"

# ─── 5d. GATE: a dispatched worker's brief is not a correction ────────
# run-tasks-parallel.sh pipes the task brief into `claude -p` with
# CLADE_WORKER_TASK_ID exported; that brief is the worker's one and only
# "user prompt". Measured 2026-09-21: 13 of a fortnight's 72 explicit records
# were /loop briefs, logged once per retry. The SAME prompt that fires in
# case 5 must persist nothing and inject nothing here — the control is the
# env var alone, so deleting the guard turns both assertions red.
section "correction-detector — a worker session records no corrections"
BEFORE_W="$(wc -l < "$HISTORY" 2>/dev/null || echo 0)"
OUTW=$(correct_in "no, use tabs instead" "worker-session-abc" \
        | CLADE_WORKER_TASK_ID="batch-20260921-1" CLAUDE_PROJECT_DIR="$PROJ2" bash "$CORRECTION_HOOK")
AFTER_W="$(wc -l < "$HISTORY" 2>/dev/null || echo 0)"
if [[ "$BEFORE_W" == "$AFTER_W" ]]; then
  pass "worker brief persists no history record"
else fail "worker brief persists no history record" "history grew $BEFORE_W → $AFTER_W"; fi
assert_eq "$(jq -r '.hookSpecificOutput.additionalContext // ""' <<< "$OUTW" 2>/dev/null)" "" \
  "worker brief injects no rule-extraction context"

# ─── 5e. recall: rejections the keyword list missed; precision: tags ──
# Hand-labelled set, 364 owner messages typed after Workflow runs: the hook as
# of 2026-10-22 fired on 32 and caught 13 of the 37 rejections (precision 41%,
# recall 35%). 9 of its 19 false fires were a 对不对 tag question ("…, right?"),
# which carries 不对 inside it; the strip alone gives precision 57%. The added
# phrasings are measured only in-sample (see the hook's comment). The prompts
# below are synthetic, one per shape — the owner's own messages stay out of this
# public repository.
section "correction-detector — missed rejection phrasings, and tag questions"
# fires_with <hook> <prompt> — like fires(), against any copy of the hook.
fires_with() {
  correct_in "$2" "sess-recall" | CLAUDE_PROJECT_DIR="$PROJ2" bash "$1" 2>/dev/null \
    | jq -r '.hookSpecificOutput.additionalContext // ""' 2>/dev/null
}
assert_contains "$(fires '这个结果不太对，再查一下')" "keyword: '不太对'" "不太对 (not quite right) fires"
assert_contains "$(fires '你理解错我的意思')" "keyword: '理解错'" "理解错 (misunderstood) fires"
assert_contains "$(fires '你这里没懂我要什么')" "keyword: '没懂'" "没懂 (did not get it) fires"
assert_contains "$(fires '这两版我都不满意')" "keyword: '不满意'" "不满意 (not satisfied) fires"
assert_contains "$(fires '手机上还是打不开')" "keyword: '打不开'" "打不开 (will not open) fires"
assert_contains "$(fires '这几个任务做多了')" "keyword: '做多了'" "做多了 (did too much) fires"
assert_contains "$(fires '改完变成四不像了')" "keyword: '四不像'" "四不像 (neither one thing nor the other) fires"
assert_contains "$(fires '这一页说得太多了')" "keyword: '说得太多'" "说得太多 (says too much) fires"
_hist_tag="$(wc -l < "$HISTORY" 2>/dev/null || echo 0)"
assert_eq "$(fires '所以我们已经有单独的仓库了，对不对？')" "" "a 对不对 tag question is not a correction"
assert_eq "$(fires '你算一下这几个数对不对得上')" "" "对不对 inside a question is not a correction"
assert_eq "$(wc -l < "$HISTORY" 2>/dev/null || echo 0)" "$_hist_tag" "neither tag question leaves a history record"
# Controls: the strip ignores word boundaries, so it must not eat a real 不对
# that sits beside another 对 — after a word ending in 对, after another 不对,
# or after a tag in unpunctuated dictation — nor one the tag merely follows.
assert_contains "$(fires '不对不对，换一个方案')" "keyword: '不对'" "不对不对 (no, no) is still a rejection"
assert_contains "$(fires '不对不对不对')" "keyword: '不对'" "a longer run of 不对 is still a rejection"
assert_contains "$(fires '不对，我们只要第二版，对不对？')" "keyword: '不对'" "a rejection followed by a tag still fires"
assert_contains "$(fires '这个结论绝对不对')" "keyword: '不对'" "绝对不对 (absolutely wrong) is still a rejection"
assert_contains "$(fires '两份表的比对不对，数据错位了')" "keyword: '不对'" "比对不对 (the comparison is wrong) is still a rejection"
assert_contains "$(fires '这是同一个库对不对不对是两个库')" "keyword: '不对'" "a tag running into 不对 still fires"
assert_contains "$(fires '是这样对不对不对不对换一个')" "keyword: '不对'" "a tag running into 不对不对 still fires"
# ...while a tag after a word ending in 对 is still only a tag.
assert_eq "$(fires '这次的比对对不对？')" "" "a tag after a word ending in 对 is not a correction"

# ─── 6. session-key fallback when session_id absent ──────────────────
section "lib — \$PPID fallback when session_id missing"
echo '{"tool_input":{"file_path":"/tmp/x/nokey.py"}}' | bash "$SHADOW_HOOK"
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
if [[ "$BEFORE_N" == "$AFTER_N" ]]; then
  pass "non-correction prompt persists nothing"
else fail "non-correction prompt persists nothing" "history grew $BEFORE_N → $AFTER_N"; fi

# ─── 8. mutations: each guard of §3i and §5e, removed, turns its case red ──
# A case that cannot fail is not evidence. Each mutant below is a copy of the
# hook with ONE guard deleted, placed beside the real lib/ and scripts/ so it
# still runs; the case that pins that guard is re-run against it and must see
# the old behaviour. The control rewords a comment and must stay correct. An
# anchor that no longer occurs exactly once is a failure, not a skip.
section "mutations — each new guard, removed, turns its case red"
MUT_ROOT="$TMP_ROOT/mut"
mkdir -p "$MUT_ROOT/configs/hooks"
ln -s "$REPO_ROOT/configs/hooks/lib" "$MUT_ROOT/configs/hooks/lib"
ln -s "$REPO_ROOT/configs/scripts" "$MUT_ROOT/configs/scripts"
# mutant <src> <name> <anchor> <replacement> — literal text, not a regex.
mutant() {
  local out="$MUT_ROOT/configs/hooks/$2"
  MUT_A="$3" MUT_R="$4" awk '
    { buf = buf (NR > 1 ? "\n" : "") $0 }
    END {
      a = ENVIRON["MUT_A"]; r = ENVIRON["MUT_R"]; s = buf; out = ""; n = 0
      while ((i = index(s, a)) > 0) { out = out substr(s, 1, i - 1) r; s = substr(s, i + length(a)); n++ }
      if (n != 1) exit 3
      printf "%s\n", out s
    }' "$1" > "$out" || return 1
  printf '%s' "$out"
}
anchor_lost() { fail "mutation '$1': its anchor no longer matches the hook exactly once"; }

_m="the agent_id guard"
if M=$(mutant "$REVERT_HOOK" m-agent.sh 'if [[ -n "$AGENT_ID" ]]; then' 'if false; then'); then
  assert_eq "$(reverts_recorded "$M" '{"agent_id":"a1b2c3d4e5f60718"}')" "1" "mutant without $_m: a subagent revert is recorded again"
else anchor_lost "$_m"; fi

_m="the worker guard"
if M=$(mutant "$REVERT_HOOK" m-worker.sh 'if [[ -n "${CLADE_WORKER_TASK_ID:-}" ]]; then' 'if false; then'); then
  assert_eq "$(reverts_recorded "$M" '{}' CLADE_WORKER_TASK_ID=batch-20261023-1)" "1" "mutant without $_m: a worker revert is recorded again"
else anchor_lost "$_m"; fi

_m="the added phrasings"
if M=$(mutant "$CORRECTION_HOOK" m-phrasings.sh '|不太对|理解错|没懂|不满意|打不开|做多了|四不像|说的太多|说得太多'\''' "'"); then
  assert_eq "$(fires_with "$M" '这个结果不太对，再查一下')" "" "mutant without $_m: 不太对 no longer fires"
else anchor_lost "$_m"; fi

_m="the 对不对 strip"
if M=$(mutant "$CORRECTION_HOOK" m-tag.sh 'SCAN="${SCAN//对不对/}"' ':'); then
  assert_contains "$(fires_with "$M" '所以我们已经有单独的仓库了，对不对？')" "keyword: '不对'" "mutant without $_m: the tag question fires again"
else anchor_lost "$_m"; fi

_m="the 不对不对 split"
if M=$(mutant "$CORRECTION_HOOK" m-double.sh 'while [[ "$SCAN" == *不对不对* ]]; do SCAN="${SCAN//不对不对/不对 不对}"; done' ':'); then
  assert_eq "$(fires_with "$M" '不对不对，换一个方案')" "" "mutant without $_m: 不对不对 is swallowed by the strip"
else anchor_lost "$_m"; fi

# One pass leaves a pair when a tag runs into 不对不对: the shortest input that
# tells the loop from a single substitution (found by enumerating every string
# of up to 10 characters over 不/对/绝/X).
_m="the split loop"
if M=$(mutant "$CORRECTION_HOOK" m-once.sh 'while [[ "$SCAN" == *不对不对* ]]; do SCAN="${SCAN//不对不对/不对 不对}"; done' 'SCAN="${SCAN//不对不对/不对 不对}"'); then
  assert_eq "$(fires_with "$M" '是这样对不对不对不对换一个')" "" "mutant splitting once instead of $_m: a tag running into 不对不对 is swallowed"
else anchor_lost "$_m"; fi

_m="the 对-word split"
if M=$(mutant "$CORRECTION_HOOK" m-word.sh 'for _w in 绝对 比对 核对 校对 相对 针对 配对; do SCAN="${SCAN//${_w}不对/${_w} 不对}"; done' ':'); then
  assert_eq "$(fires_with "$M" '这个结论绝对不对')" "" "mutant without $_m: 绝对不对 is swallowed by the strip"
else anchor_lost "$_m"; fi

_m="a reworded comment (no-op control)"
if M=$(mutant "$CORRECTION_HOOK" m-noop.sh 'A tag question asks; it does not reject' 'A tag question asks, it does not reject'); then
  assert_eq "$(fires_with "$M" '所以我们已经有单独的仓库了，对不对？')" "" "control mutant ($_m): the tag question stays silent"
else anchor_lost "$_m"; fi

# ─── Summary ─────────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  Ran: $TESTS_RUN  ${GREEN}Passed: $TESTS_PASSED${NC}  ${RED}Failed: $TESTS_FAILED${NC}"
[[ "$TESTS_FAILED" -eq 0 ]] && { echo -e "  ${GREEN}ALL PASSED${NC}"; exit 0; } || { echo -e "  ${RED}FAILURES${NC}"; exit 1; }
