#!/usr/bin/env bash
# test-sync-store.sh — generated and self-healed ignores for the dotfiles store.
#
# Every HOME and git repository is a throwaway fixture. The setup run uses a
# fake gh and a stub project linker, so it cannot reach the network or another
# checkout. The push fixture has no remote.
#
# Internal: CLADE_TEST_SYNC_SETUP, CLADE_TEST_SYNC_PUSH and CLADE_TEST_SYNC_HEAL
# may name scratch copies, used to prove these cases fail against older code.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYNC_SETUP="${CLADE_TEST_SYNC_SETUP:-$REPO_ROOT/configs/scripts/sync-setup.sh}"
SYNC_PUSH="${CLADE_TEST_SYNC_PUSH:-$REPO_ROOT/configs/scripts/sync-push.sh}"
SYNC_HEAL="${CLADE_TEST_SYNC_HEAL:-$REPO_ROOT/configs/scripts/sync-store-heal.sh}"

TESTS_RUN=0; TESTS_PASSED=0; TESTS_FAILED=0
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
  if [[ "$1" == "$2" ]]; then pass "$3"; else fail "$3" "expected '$2', got '$1'"; fi
}
assert_not_contains() {
  if grep -qF -- "$2" <<< "$1"; then fail "$3" "output unexpectedly contains '$2'"; else pass "$3"; fi
}
assert_ignored() {
  if git -C "$1" check-ignore -q -- "$2"; then
    pass "$2 is ignored"
  else
    fail "$2 is ignored" "git check-ignore rejected the default pattern"
  fi
}
assert_not_ignored() {
  if git -C "$1" check-ignore -q -- "$2"; then
    fail "$2 is synced" "a default pattern ignores a memory file"
  else
    pass "$2 is synced"
  fi
}
assert_same_file() {
  if cmp -s "$1" "$2"; then
    pass "$3"
  else
    fail "$3" "$1 differs from $2"
  fi
}

TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/clade-sync-store.XXXXXX")"
trap 'rm -rf "$TMP_ROOT"' EXIT
export HOME="$TMP_ROOT/home"
mkdir -p "$HOME"
export GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME=clade-test GIT_AUTHOR_EMAIL=test@clade.local
export GIT_COMMITTER_NAME=clade-test GIT_COMMITTER_EMAIL=test@clade.local
unset CLAUDE_CONFIG_DIR CLADE_PRIVATE_PROJECTS CLADE_PRIVATE_KEYWORDS CLADE_SYNC_PUSH_LOCK

# Run both scripts from a sibling-file layout identical to ~/.claude/scripts.
# The conditional keeps this suite runnable against pre-helper HEAD copies.
mkdir -p "$TMP_ROOT/push-bin"
cp "$SYNC_PUSH" "$TMP_ROOT/push-bin/sync-push.sh"
if [[ -f "$SYNC_HEAL" ]]; then
  cp "$SYNC_HEAL" "$TMP_ROOT/push-bin/sync-store-heal.sh"
fi
SYNC_PUSH_RUN="$TMP_ROOT/push-bin/sync-push.sh"

DEFAULT_IGNORE=$(cat <<'EOF'
# Raw correction events are private; keep them local.
corrections/history.jsonl
# Local safety backups.
*.bak-*
.backups/
# Claude Code's regenerated skill cache stays local.
skills/synced/
# Byte-compiled Python caches cause cross-machine conflicts.
__pycache__/
*.py[cod]
# Self-heal forensic backups stay local.
*.corrupt.*
# Claude Code's removed-skill trash stays local.
skills/.trash/
# Claude Code's auto-dream lock and session logs are per-host and private.
.consolidate-lock
projects-memory/*/logs/
EOF
)

section "sync-setup — a fresh store ignores every default local-only path"
SETUP_ROOT="$TMP_ROOT/setup"
SETUP_HOME="$SETUP_ROOT/home"
SETUP_NFS="$SETUP_ROOT/nfs"
mkdir -p "$SETUP_HOME/.claude/corrections" "$SETUP_NFS" "$SETUP_ROOT/bin"
printf '{"event":"private"}\n' > "$SETUP_HOME/.claude/corrections/history.jsonl"
cp "$SYNC_SETUP" "$SETUP_ROOT/bin/sync-setup.sh"
if [[ -f "$SYNC_HEAL" ]]; then
  cp "$SYNC_HEAL" "$SETUP_ROOT/bin/sync-store-heal.sh"
fi
printf '#!/bin/sh\nexit 1\n' > "$SETUP_ROOT/bin/gh"
printf '#!/bin/sh\nexit 0\n' > "$SETUP_ROOT/bin/sync-link-projects.sh"
chmod +x "$SETUP_ROOT/bin/gh" "$SETUP_ROOT/bin/sync-link-projects.sh"
HOME="$SETUP_HOME" PATH="$SETUP_ROOT/bin:$PATH" \
  bash "$SETUP_ROOT/bin/sync-setup.sh" --nfs "$SETUP_NFS" > "$SETUP_ROOT/output" 2>&1
SETUP_RC=$?
SETUP_STORE="$SETUP_NFS/claude-dotfiles"
assert_eq "$SETUP_RC" "0" "sync-setup initializes the fixture store"
if [[ -f "$SETUP_STORE/.gitignore" ]]; then
  SETUP_IGNORE=$(cat "$SETUP_STORE/.gitignore")
else
  SETUP_IGNORE=""
fi
assert_eq "$SETUP_IGNORE" "$DEFAULT_IGNORE" \
  "the generated .gitignore contains exactly the default lines and group comments"
assert_eq "$(grep -xcF 'projects-memory/*/.project-paths merge=union' "$SETUP_STORE/.gitattributes" 2>/dev/null)" "1" \
  "sync-setup marks per-host project paths for union merge"
assert_ignored "$SETUP_STORE" "corrections/history.jsonl"
assert_ignored "$SETUP_STORE" "rules.md.bak-20261107"
assert_ignored "$SETUP_STORE" ".backups/local/rules.md"
assert_ignored "$SETUP_STORE" "skills/synced/cache/SKILL.md"
assert_ignored "$SETUP_STORE" "scripts/__pycache__/module.pyc"
assert_ignored "$SETUP_STORE" "scripts/module.pyo"
assert_ignored "$SETUP_STORE" "x.corrupt.1"
assert_ignored "$SETUP_STORE" "skills/.trash/markers.md"
assert_ignored "$SETUP_STORE" "projects-memory/repo-example/.consolidate-lock"
assert_ignored "$SETUP_STORE" "projects-memory/repo-example/logs/2026/11/09/abcd1234-title.md"
assert_not_ignored "$SETUP_STORE" "projects-memory/repo-example/MEMORY.md"
assert_not_ignored "$SETUP_STORE" "projects-memory/repo-example/logs-of-builds.md"
assert_eq "$(cat "$SETUP_STORE/corrections/history.jsonl")" '{"event":"private"}' \
  "the private correction event was written into the migrated store"
assert_not_contains "$(git -C "$SETUP_STORE" status --porcelain --untracked-files=all)" \
  "corrections/history.jsonl" "git status omits the written correction history"
assert_not_contains "$(git -C "$SETUP_STORE" ls-files)" \
  "corrections/history.jsonl" "the initial setup commit does not track correction history"

# Re-running setup is also an upgrade path. A comment containing a pattern is
# not the pattern line itself. Keep the final local line unterminated too.
SETUP_COMMENT='# keep *.corrupt.* and skills/.trash/ out of git'
printf '%s\nsetup-local' "$SETUP_COMMENT" > "$SETUP_STORE/.gitignore"
HOME="$SETUP_HOME" PATH="$SETUP_ROOT/bin:$PATH" \
  bash "$SETUP_ROOT/bin/sync-setup.sh" --nfs "$SETUP_NFS" >/dev/null 2>&1
assert_eq "$?" "0" "sync-setup also upgrades an existing store"
EXPECTED_SETUP_IGNORE=$(printf '%s\nsetup-local\n%s' "$SETUP_COMMENT" "$DEFAULT_IGNORE")
assert_eq "$(cat "$SETUP_STORE/.gitignore")" "$EXPECTED_SETUP_IGNORE" \
  "setup matches whole lines, not comments, and preserves an unterminated final line"
HOME="$SETUP_HOME" PATH="$SETUP_ROOT/bin:$PATH" \
  bash "$SETUP_ROOT/bin/sync-setup.sh" --nfs "$SETUP_NFS" >/dev/null 2>&1
assert_eq "$(cat "$SETUP_STORE/.gitignore")" "$EXPECTED_SETUP_IGNORE" \
  "a further setup run is idempotent"

section "sync scripts — complete patterns with local comments need no healing"
cat > "$SETUP_ROOT/live.gitignore" <<'EOF'
# raw correction event log — keep local, never sync to GitHub (privacy)
corrections/history.jsonl
# local safety backups
*.bak-*
.backups/
# Claude Code's claude.ai skill cache, regenerated per session
skills/synced/
# byte-compiled caches (caused cross-host conflicts)
__pycache__/
*.py[cod]
# self-heal forensic backups
*.corrupt.*
# Claude Code's trash of removed skills
skills/.trash/
# auto-dream lock + session logs (per host)
.consolidate-lock
projects-memory/*/logs/
EOF
cp "$SETUP_ROOT/live.gitignore" "$SETUP_STORE/.gitignore"
git -C "$SETUP_STORE" add .gitignore
git -C "$SETUP_STORE" -c core.hooksPath=/dev/null commit -qm local-comments
NOOP_HEAD=$(git -C "$SETUP_STORE" rev-parse HEAD)
HOME="$SETUP_HOME" CLADE_RUNTIME_DIR="$SETUP_ROOT/push-runtime" \
  bash "$SYNC_PUSH_RUN" > "$SETUP_ROOT/noop-push.out" 2>&1
assert_eq "$?" "0" "a complete ignore file still allows sync-push"
assert_same_file "$SETUP_STORE/.gitignore" "$SETUP_ROOT/live.gitignore" \
  "sync-push appends no orphan comments when every pattern is present"
assert_eq "$(git -C "$SETUP_STORE" rev-parse HEAD)" "$NOOP_HEAD" \
  "a complete ignore file causes no healing commit"
cp "$SETUP_ROOT/live.gitignore" "$SETUP_STORE/.gitignore"
HOME="$SETUP_HOME" PATH="$SETUP_ROOT/bin:$PATH" \
  bash "$SETUP_ROOT/bin/sync-setup.sh" --nfs "$SETUP_NFS" >/dev/null 2>&1
assert_eq "$?" "0" "sync-setup accepts the same complete ignore file"
assert_same_file "$SETUP_STORE/.gitignore" "$SETUP_ROOT/live.gitignore" \
  "sync-setup also leaves a complete ignore file byte-identical"

section "sync scripts — both entry points call the one shared definition"
assert_eq "$(grep -cF 'sync-store-heal.sh' "$SYNC_SETUP")" "1" \
  "sync-setup names the shared healer once"
assert_eq "$(grep -cF 'sync-store-heal.sh' "$SYNC_PUSH")" "1" \
  "sync-push names the shared healer once"
assert_eq "$(grep -cF 'sync_store_heal_gitignore' "$SYNC_SETUP")" "1" \
  "sync-setup has no separate inline ignore loop"
assert_eq "$(grep -cF 'sync_store_heal_gitignore' "$SYNC_PUSH")" "1" \
  "sync-push has no separate inline ignore loop"
assert_eq "$(grep -cF 'projects-memory/*/.project-paths merge=union' "$SYNC_SETUP")" "1" \
  "setup carries the project-paths attribute"
assert_eq "$(grep -cF 'projects-memory/*/.project-paths merge=union' "$SYNC_PUSH")" "1" \
  "push carries the same attribute for existing stores"

section "sync-store-heal — generic line appends have a checked failure contract"
HELPER_ROOT="$TMP_ROOT/helper"
mkdir -p "$HELPER_ROOT"
printf 'local-last\n' > "$HELPER_ROOT/terminated"
(
  # shellcheck source=/dev/null
  source "$SYNC_HEAL" 2>/dev/null || exit 99
  sync_store_append_missing_lines "$HELPER_ROOT/terminated" <<'EOF'
next
EOF
)
assert_eq "$?" "0" "the generic helper accepts another metadata line list"
assert_eq "$(cat "$HELPER_ROOT/terminated")" "$(printf 'local-last\nnext')" \
  "a terminated existing line gains no spurious blank line"
printf 'local-last' > "$HELPER_ROOT/read-failure"
(
  # shellcheck source=/dev/null
  source "$SYNC_HEAL" 2>/dev/null || exit 99
  tail() { return 1; }
  sync_store_append_missing_lines "$HELPER_ROOT/read-failure" <<'EOF'
next
EOF
)
assert_eq "$?" "1" "a final-line read failure returns nonzero"
assert_eq "$(cat "$HELPER_ROOT/read-failure")" "local-last" \
  "a final-line read failure does not concatenate into the existing line"
ln -s missing-dir/gitignore "$HELPER_ROOT/append-failure"
(
  # shellcheck source=/dev/null
  source "$SYNC_HEAL" 2>/dev/null || exit 99
  sync_store_append_missing_lines "$HELPER_ROOT/append-failure" <<'EOF'
next
EOF
)
assert_eq "$?" "1" "an append failure returns nonzero to the best-effort caller"
printf 'a\n' > "$HELPER_ROOT/duplicate-input"
(
  # shellcheck source=/dev/null
  source "$SYNC_HEAL" 2>/dev/null || exit 99
  sync_store_append_missing_lines "$HELPER_ROOT/duplicate-input" <<'EOF'
a
b
EOF
)
assert_eq "$?" "0" "the generic helper accepts a mix of present and new lines"
assert_eq "$(cat "$HELPER_ROOT/duplicate-input")" "$(printf 'a\nb')" \
  "the generic helper appends only b and never duplicates a"

: > "$HELPER_ROOT/early-failure"
: > "$HELPER_ROOT/early-failure-empty"
EARLY_TAIL_FLAG="$HELPER_ROOT/first-tail-failed"
(
  # shellcheck source=/dev/null
  source "$SYNC_HEAL" 2>/dev/null || exit 99
  tail() {
    if [[ ! -e "$EARLY_TAIL_FLAG" ]]; then
      : > "$EARLY_TAIL_FLAG"
      return 1
    fi
    command tail "$@"
  }
  sync_store_heal_gitignore "$HELPER_ROOT/early-failure"
)
assert_eq "$?" "1" "a first-group append failure returns nonzero immediately"
assert_eq "$(grep -xcF 'corrections/history.jsonl' "$HELPER_ROOT/early-failure")" "0" \
  "the failed first group never adds the private-history ignore"
assert_same_file "$HELPER_ROOT/early-failure" "$HELPER_ROOT/early-failure-empty" \
  "no later group is appended after the first-group failure"

section "sync-push — an existing store self-heals its ignores before scanning"
PUSH_ROOT="$TMP_ROOT/push"
PUSH_HOME="$PUSH_ROOT/home"
PUSH_STORE="$PUSH_ROOT/store"
mkdir -p "$PUSH_HOME/.claude" "$PUSH_STORE/corrections" "$PUSH_STORE/skills/.trash"
printf 'SYNC_BACKEND=nfs\nSYNC_DIR=%s\n' "$PUSH_STORE" > "$PUSH_HOME/.claude/.sync-config"
git -C "$PUSH_STORE" init -q
git -C "$PUSH_STORE" config user.email test@clade.local
git -C "$PUSH_STORE" config user.name clade-test
# As above, comments are not ignore directives, and the last line has no newline.
PUSH_COMMENT='# keep *.corrupt.* and skills/.trash/ out of git'
printf '%s\nlocal-first\nlocal-last' "$PUSH_COMMENT" > "$PUSH_STORE/.gitignore"
printf -- '- rule one\n' > "$PUSH_STORE/corrections/rules.md"
git -C "$PUSH_STORE" add -A
git -C "$PUSH_STORE" -c core.hooksPath=/dev/null commit -qm base
printf '%s\n' '<<<<<<< Updated upstream' '=======' '>>>>>>> Stashed changes' > "$PUSH_STORE/x.corrupt.1"
printf '%s\n' '<<<<<<< Updated upstream' '=======' '>>>>>>> Stashed changes' > "$PUSH_STORE/skills/.trash/markers.md"
printf -- '- rule one\n- rule two\n' > "$PUSH_STORE/corrections/rules.md"
HOME="$PUSH_HOME" CLADE_RUNTIME_DIR="$PUSH_ROOT/runtime" \
  bash "$SYNC_PUSH_RUN" > "$PUSH_ROOT/output" 2>&1
PUSH_RC=$?
PUSH_OUT=$(cat "$PUSH_ROOT/output"; cat "$PUSH_HOME/.claude/.sync-conflicts.log" 2>/dev/null)
assert_eq "$PUSH_RC" "0" "x.corrupt.1 and skills/.trash markers no longer refuse the push"
assert_not_contains "$PUSH_OUT" "REFUSED" "the marker guard does not log a refusal for an ignored quarantine file"
assert_not_contains "$PUSH_OUT" "corrections/history.jsonl is already tracked" \
  "an untracked correction history does not emit the tracked-file warning"
assert_eq "$(git -C "$PUSH_STORE" show HEAD:corrections/rules.md 2>/dev/null)" "$(printf -- '- rule one\n- rule two')" \
  "the ordinary clean edit still commits"
PUSH_TRACKED=$(git -C "$PUSH_STORE" ls-files)
assert_not_contains "$PUSH_TRACKED" "x.corrupt.1" "the corrupt backup is not committed"
assert_not_contains "$PUSH_TRACKED" "skills/.trash/markers.md" "the trash file is not committed"
EXPECTED_IGNORE=$(printf '%s\nlocal-first\nlocal-last\n%s' "$PUSH_COMMENT" "$DEFAULT_IGNORE")
assert_eq "$(cat "$PUSH_STORE/.gitignore")" "$EXPECTED_IGNORE" \
  "healing matches whole lines and appends without reordering existing lines or comments"
HOME="$PUSH_HOME" CLADE_RUNTIME_DIR="$PUSH_ROOT/runtime" bash "$SYNC_PUSH_RUN" >/dev/null 2>&1
assert_eq "$(cat "$PUSH_STORE/.gitignore")" "$EXPECTED_IGNORE" \
  "a second push adds no duplicate lines and needs no trailing-newline repair"
assert_eq "$(grep -xcF '*.corrupt.*' "$PUSH_STORE/.gitignore")" "1" "the corrupt pattern stays singular"
assert_eq "$(grep -xcF 'skills/.trash/' "$PUSH_STORE/.gitignore")" "1" "the trash pattern stays singular"
assert_eq "$(grep -xcF 'corrections/history.jsonl' "$PUSH_STORE/.gitignore")" "1" \
  "the private history pattern stays singular"
assert_eq "$(grep -xcF 'projects-memory/*/.project-paths merge=union' "$PUSH_STORE/.gitattributes" 2>/dev/null)" "1" \
  "the existing store heals exactly one project-paths attribute"
assert_eq "$(git -C "$PUSH_STORE" show HEAD:.gitattributes 2>/dev/null)" "projects-memory/*/.project-paths merge=union" \
  "the healed attribute is committed for other hosts"

section "sync-push — a #205 store gains only incomplete groups"
UPGRADE_ROOT="$TMP_ROOT/upgrade-205"
UPGRADE_HOME="$UPGRADE_ROOT/home"
UPGRADE_STORE="$UPGRADE_ROOT/store"
mkdir -p "$UPGRADE_HOME/.claude" "$UPGRADE_STORE/corrections"
printf 'SYNC_BACKEND=nfs\nSYNC_DIR=%s\n' "$UPGRADE_STORE" > "$UPGRADE_HOME/.claude/.sync-config"
git -C "$UPGRADE_STORE" init -q
git -C "$UPGRADE_STORE" config user.email test@clade.local
git -C "$UPGRADE_STORE" config user.name clade-test
printf '%s\n' '*.corrupt.*' 'skills/.trash/' > "$UPGRADE_STORE/.gitignore"
printf -- '- rule one\n' > "$UPGRADE_STORE/corrections/rules.md"
git -C "$UPGRADE_STORE" add -A
git -C "$UPGRADE_STORE" -c core.hooksPath=/dev/null commit -qm base
HOME="$UPGRADE_HOME" CLADE_RUNTIME_DIR="$UPGRADE_ROOT/runtime" \
  bash "$SYNC_PUSH_RUN" >/dev/null 2>&1
assert_eq "$?" "0" "the #205 upgrade push completes"
cat > "$UPGRADE_ROOT/expected.gitignore" <<'EOF'
*.corrupt.*
skills/.trash/
# Raw correction events are private; keep them local.
corrections/history.jsonl
# Local safety backups.
*.bak-*
.backups/
# Claude Code's regenerated skill cache stays local.
skills/synced/
# Byte-compiled Python caches cause cross-machine conflicts.
__pycache__/
*.py[cod]
# Claude Code's auto-dream lock and session logs are per-host and private.
.consolidate-lock
projects-memory/*/logs/
EOF
assert_same_file "$UPGRADE_STORE/.gitignore" "$UPGRADE_ROOT/expected.gitignore" \
  "only missing patterns and their group comments are appended"
cp "$UPGRADE_STORE/.gitignore" "$UPGRADE_ROOT/once.gitignore"
HOME="$UPGRADE_HOME" CLADE_RUNTIME_DIR="$UPGRADE_ROOT/runtime" \
  bash "$SYNC_PUSH_RUN" >/dev/null 2>&1
assert_same_file "$UPGRADE_STORE/.gitignore" "$UPGRADE_ROOT/once.gitignore" \
  "complete groups add no comments on the next run"

section "sync-push — partially present groups never duplicate their patterns"
PARTIAL_ROOT="$TMP_ROOT/partial-groups"
PARTIAL_HOME="$PARTIAL_ROOT/home"
PARTIAL_STORE="$PARTIAL_ROOT/store"
mkdir -p "$PARTIAL_HOME/.claude" "$PARTIAL_STORE/corrections"
printf 'SYNC_BACKEND=nfs\nSYNC_DIR=%s\n' "$PARTIAL_STORE" > "$PARTIAL_HOME/.claude/.sync-config"
git -C "$PARTIAL_STORE" init -q
git -C "$PARTIAL_STORE" config user.email test@clade.local
git -C "$PARTIAL_STORE" config user.name clade-test
printf '%s\n' '*.bak-*' '__pycache__/' > "$PARTIAL_STORE/.gitignore"
printf -- '- rule one\n' > "$PARTIAL_STORE/corrections/rules.md"
git -C "$PARTIAL_STORE" add -A
git -C "$PARTIAL_STORE" -c core.hooksPath=/dev/null commit -qm base
HOME="$PARTIAL_HOME" CLADE_RUNTIME_DIR="$PARTIAL_ROOT/runtime" \
  bash "$SYNC_PUSH_RUN" >/dev/null 2>&1
assert_eq "$?" "0" "the partial-group healing push completes"
cat > "$PARTIAL_ROOT/expected.gitignore" <<'EOF'
*.bak-*
__pycache__/
# Raw correction events are private; keep them local.
corrections/history.jsonl
# Local safety backups.
.backups/
# Claude Code's regenerated skill cache stays local.
skills/synced/
# Byte-compiled Python caches cause cross-machine conflicts.
*.py[cod]
# Self-heal forensic backups stay local.
*.corrupt.*
# Claude Code's removed-skill trash stays local.
skills/.trash/
# Claude Code's auto-dream lock and session logs are per-host and private.
.consolidate-lock
projects-memory/*/logs/
EOF
assert_same_file "$PARTIAL_STORE/.gitignore" "$PARTIAL_ROOT/expected.gitignore" \
  "each incomplete group gains its comment and only its missing patterns"
assert_eq "$(grep -xcF '*.bak-*' "$PARTIAL_STORE/.gitignore")" "1" \
  "the already present backup suffix stays singular"
assert_eq "$(grep -xcF '__pycache__/' "$PARTIAL_STORE/.gitignore")" "1" \
  "the already present Python cache directory stays singular"
cp "$PARTIAL_STORE/.gitignore" "$PARTIAL_ROOT/once.gitignore"
HOME="$PARTIAL_HOME" CLADE_RUNTIME_DIR="$PARTIAL_ROOT/runtime" \
  bash "$SYNC_PUSH_RUN" >/dev/null 2>&1
assert_same_file "$PARTIAL_STORE/.gitignore" "$PARTIAL_ROOT/once.gitignore" \
  "a second partial-group healing run is byte-identical"

section "sync-push — already tracked history is reported but never untracked"
TRACKED_ROOT="$TMP_ROOT/tracked-history"
TRACKED_HOME="$TRACKED_ROOT/home"
TRACKED_STORE="$TRACKED_ROOT/store"
mkdir -p "$TRACKED_HOME/.claude" "$TRACKED_STORE/corrections"
printf 'SYNC_BACKEND=nfs\nSYNC_DIR=%s\n' "$TRACKED_STORE" > "$TRACKED_HOME/.claude/.sync-config"
git -C "$TRACKED_STORE" init -q
git -C "$TRACKED_STORE" config user.email test@clade.local
git -C "$TRACKED_STORE" config user.name clade-test
printf '{"event":"already tracked"}\n' > "$TRACKED_STORE/corrections/history.jsonl"
git -C "$TRACKED_STORE" add -A
git -C "$TRACKED_STORE" -c core.hooksPath=/dev/null commit -qm base
HOME="$TRACKED_HOME" CLADE_RUNTIME_DIR="$TRACKED_ROOT/runtime" CLADE_SYNC_PUSH_TODAY=2026-11-07 \
  bash "$SYNC_PUSH_RUN" > "$TRACKED_ROOT/output" 2>&1
assert_eq "$?" "0" "a store already tracking history still completes its push"
TRACKED_NOTICE="[2026-11-07] sync-push privacy: corrections/history.jsonl is already tracked; untrack it with: git -C \"$TRACKED_STORE\" rm --cached corrections/history.jsonl"
assert_eq "$(grep -xcF "$TRACKED_NOTICE" "$TRACKED_HOME/.claude/.sync-conflicts.log" 2>/dev/null)" "1" \
  "the log names the tracked file and the exact manual untrack command"
if git -C "$TRACKED_STORE" ls-files --error-unmatch corrections/history.jsonl >/dev/null 2>&1; then
  pass "the warning leaves history.jsonl tracked"
else
  fail "the warning leaves history.jsonl tracked" "sync-push untracked the file"
fi
HOME="$TRACKED_HOME" CLADE_RUNTIME_DIR="$TRACKED_ROOT/runtime" CLADE_SYNC_PUSH_TODAY=2026-11-07 \
  bash "$SYNC_PUSH_RUN" >/dev/null 2>&1
assert_eq "$(grep -cF 'corrections/history.jsonl is already tracked' "$TRACKED_HOME/.claude/.sync-conflicts.log")" "1" \
  "a second push on the same day adds no duplicate warning"
HOME="$TRACKED_HOME" CLADE_RUNTIME_DIR="$TRACKED_ROOT/runtime" CLADE_SYNC_PUSH_TODAY=2026-11-08 \
  bash "$SYNC_PUSH_RUN" >/dev/null 2>&1
assert_eq "$(grep -cF 'corrections/history.jsonl is already tracked' "$TRACKED_HOME/.claude/.sync-conflicts.log")" "2" \
  "a push on the next day writes one fresh warning"

section "sync-push — refusals do not interleave privacy notices"
REFUSED_TRACKED_ROOT="$TMP_ROOT/refused-tracked-history"
REFUSED_TRACKED_HOME="$REFUSED_TRACKED_ROOT/home"
REFUSED_TRACKED_STORE="$REFUSED_TRACKED_ROOT/store"
mkdir -p "$REFUSED_TRACKED_HOME/.claude" "$REFUSED_TRACKED_STORE/corrections"
printf 'SYNC_BACKEND=nfs\nSYNC_DIR=%s\n' "$REFUSED_TRACKED_STORE" > "$REFUSED_TRACKED_HOME/.claude/.sync-config"
git -C "$REFUSED_TRACKED_STORE" init -q
git -C "$REFUSED_TRACKED_STORE" config user.email test@clade.local
git -C "$REFUSED_TRACKED_STORE" config user.name clade-test
printf '{"event":"already tracked"}\n' > "$REFUSED_TRACKED_STORE/corrections/history.jsonl"
printf -- '- rule one\n' > "$REFUSED_TRACKED_STORE/corrections/rules.md"
git -C "$REFUSED_TRACKED_STORE" add -A
git -C "$REFUSED_TRACKED_STORE" -c core.hooksPath=/dev/null commit -qm base
printf '%s\n' '<<<<<<< Updated upstream' '=======' '>>>>>>> Stashed changes' \
  >> "$REFUSED_TRACKED_STORE/corrections/rules.md"
for _day in 07 08 09; do
  HOME="$REFUSED_TRACKED_HOME" CLADE_RUNTIME_DIR="$REFUSED_TRACKED_ROOT/runtime" \
    CLADE_SYNC_PUSH_TODAY="2026-11-$_day" bash "$SYNC_PUSH_RUN" >/dev/null 2>&1
  assert_eq "$?" "1" "the tracked marker store is refused on 2026-11-$_day"
done
REFUSED_TRACKED_LOG="$REFUSED_TRACKED_HOME/.claude/.sync-conflicts.log"
assert_eq "$(grep -cF 'corrections/history.jsonl is already tracked' "$REFUSED_TRACKED_LOG")" "0" \
  "a refused run writes no tracked-history privacy notice"
assert_eq "$(tail -n 3 "$REFUSED_TRACKED_LOG" | grep -cF 'sync-push REFUSED:')" "3" \
  "the last three log lines remain an uninterrupted REFUSED streak"
unset _day

# The exemption is for ignored quarantine paths only. A marker in an ordinary
# tracked file must still block the commit, so deleting the whole scan cannot
# make this suite green.
printf '%s\n' '<<<<<<< Updated upstream' '=======' '>>>>>>> Stashed changes' >> "$PUSH_STORE/corrections/rules.md"
PUSH_COMMITS=$(git -C "$PUSH_STORE" rev-list --count HEAD)
HOME="$PUSH_HOME" CLADE_RUNTIME_DIR="$PUSH_ROOT/runtime" \
  bash "$SYNC_PUSH_RUN" > "$PUSH_ROOT/refused-output" 2>&1
REFUSED_RC=$?
if [[ "$REFUSED_RC" -ne 0 ]]; then
  pass "an ordinary tracked file with markers is still refused"
else
  fail "an ordinary tracked file with markers is still refused" "sync-push exited 0"
fi
assert_eq "$(git -C "$PUSH_STORE" rev-list --count HEAD)" "$PUSH_COMMITS" \
  "the ordinary marker file creates no commit"
assert_eq "$(grep -cF 'conflict markers' "$PUSH_ROOT/refused-output")" "1" \
  "the refusal still explains the real conflict markers"

section "sync-push — an unwritable ignore file degrades to the old marker scan"
FAIL_ROOT="$TMP_ROOT/heal-failure"
FAIL_HOME="$FAIL_ROOT/home"
FAIL_STORE="$FAIL_ROOT/store"
# A directory fails for every uid, including root; chmod cannot express this case.
mkdir -p "$FAIL_HOME/.claude" "$FAIL_STORE/corrections" "$FAIL_STORE/.gitignore"
printf 'SYNC_BACKEND=nfs\nSYNC_DIR=%s\n' "$FAIL_STORE" > "$FAIL_HOME/.claude/.sync-config"
git -C "$FAIL_STORE" init -q
git -C "$FAIL_STORE" config user.email test@clade.local
git -C "$FAIL_STORE" config user.name clade-test
printf -- '- clean base\n' > "$FAIL_STORE/corrections/rules.md"
git -C "$FAIL_STORE" add -A
git -C "$FAIL_STORE" -c core.hooksPath=/dev/null commit -qm base
printf -- '- clean edit\n' > "$FAIL_STORE/corrections/rules.md"
HOME="$FAIL_HOME" CLADE_RUNTIME_DIR="$FAIL_ROOT/runtime" \
  bash "$SYNC_PUSH_RUN" > "$FAIL_ROOT/clean-output" 2>&1
FAIL_CLEAN_RC=$?
assert_eq "$FAIL_CLEAN_RC" "0" "a failed heal does not abort a clean push"
assert_eq "$(cat "$FAIL_ROOT/clean-output")" "" "the failed heal emits no stderr noise"
assert_eq "$(git -C "$FAIL_STORE" show HEAD:corrections/rules.md 2>/dev/null)" "- clean edit" \
  "the clean edit commits despite the directory-shaped .gitignore"

# With the heal unavailable, quarantine files are visible to the marker scan
# again and must take the pre-existing REFUSED-and-log path.
printf '%s\n' '<<<<<<< Updated upstream' '=======' '>>>>>>> Stashed changes' > "$FAIL_STORE/x.corrupt.1"
printf -- '- another clean edit\n' >> "$FAIL_STORE/corrections/rules.md"
FAIL_COMMITS=$(git -C "$FAIL_STORE" rev-list --count HEAD)
HOME="$FAIL_HOME" CLADE_RUNTIME_DIR="$FAIL_ROOT/runtime" \
  bash "$SYNC_PUSH_RUN" > "$FAIL_ROOT/refused-output" 2>&1
FAIL_REFUSED_RC=$?
if [[ "$FAIL_REFUSED_RC" -ne 0 ]]; then
  pass "a failed heal leaves a marker-carrying quarantine file refused"
else
  fail "a failed heal leaves a marker-carrying quarantine file refused" "sync-push exited 0"
fi
assert_eq "$(git -C "$FAIL_STORE" rev-list --count HEAD)" "$FAIL_COMMITS" \
  "the refused quarantine file creates no commit"
FAIL_REFUSED_LOG=$(cat "$FAIL_HOME/.claude/.sync-conflicts.log" 2>/dev/null)
assert_eq "$(grep -cF 'REFUSED: conflict markers in x.corrupt.1' <<< "$FAIL_REFUSED_LOG")" "1" \
  "the refusal after a failed heal is logged with the quarantine filename"

section "sync-push — final pattern append failure is quiet and non-fatal"
APPEND_ROOT="$TMP_ROOT/final-append-failure"
APPEND_HOME="$APPEND_ROOT/home"
APPEND_STORE="$APPEND_ROOT/store"
mkdir -p "$APPEND_HOME/.claude" "$APPEND_STORE/corrections"
printf 'SYNC_BACKEND=nfs\nSYNC_DIR=%s\n' "$APPEND_STORE" > "$APPEND_HOME/.claude/.sync-config"
git -C "$APPEND_STORE" init -q
git -C "$APPEND_STORE" config user.email test@clade.local
git -C "$APPEND_STORE" config user.name clade-test
printf -- '- clean base\n' > "$APPEND_STORE/corrections/rules.md"
git -C "$APPEND_STORE" add -A
git -C "$APPEND_STORE" -c core.hooksPath=/dev/null commit -qm base
# The missing parent makes the final append fail with ENOENT for every uid.
ln -s missing-dir/gitignore "$APPEND_STORE/.gitignore"
printf -- '- clean edit\n' > "$APPEND_STORE/corrections/rules.md"
HOME="$APPEND_HOME" CLADE_RUNTIME_DIR="$APPEND_ROOT/runtime" \
  bash "$SYNC_PUSH_RUN" > "$APPEND_ROOT/output" 2>&1
APPEND_RC=$?
assert_eq "$APPEND_RC" "0" "a final pattern append failure does not abort a clean push"
assert_eq "$(cat "$APPEND_ROOT/output")" "" "the final pattern append failure emits no output"
assert_eq "$(git -C "$APPEND_STORE" show HEAD:corrections/rules.md 2>/dev/null)" "- clean edit" \
  "the clean edit commits after the final pattern append fails"

section "sync-push — newline append failure is quiet and non-fatal"
if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "  - not measured as root: read-only .gitignore (chmod cannot deny root)"
else
  NEWLINE_ROOT="$TMP_ROOT/newline-append-failure"
  NEWLINE_HOME="$NEWLINE_ROOT/home"
  NEWLINE_STORE="$NEWLINE_ROOT/store"
  mkdir -p "$NEWLINE_HOME/.claude" "$NEWLINE_STORE/corrections"
  printf 'SYNC_BACKEND=nfs\nSYNC_DIR=%s\n' "$NEWLINE_STORE" > "$NEWLINE_HOME/.claude/.sync-config"
  git -C "$NEWLINE_STORE" init -q
  git -C "$NEWLINE_STORE" config user.email test@clade.local
  git -C "$NEWLINE_STORE" config user.name clade-test
  printf 'local-last' > "$NEWLINE_STORE/.gitignore"
  printf -- '- clean base\n' > "$NEWLINE_STORE/corrections/rules.md"
  git -C "$NEWLINE_STORE" add -A
  git -C "$NEWLINE_STORE" -c core.hooksPath=/dev/null commit -qm base
  chmod 444 "$NEWLINE_STORE/.gitignore"
  printf -- '- clean edit\n' > "$NEWLINE_STORE/corrections/rules.md"
  HOME="$NEWLINE_HOME" CLADE_RUNTIME_DIR="$NEWLINE_ROOT/runtime" \
    bash "$SYNC_PUSH_RUN" > "$NEWLINE_ROOT/output" 2>&1
  NEWLINE_RC=$?
  chmod u+w "$NEWLINE_STORE/.gitignore"
  assert_eq "$NEWLINE_RC" "0" "a newline append failure does not abort a clean push"
  assert_eq "$(cat "$NEWLINE_ROOT/output")" "" "the newline append failure emits no output"
  assert_eq "$(git -C "$NEWLINE_STORE" show HEAD:corrections/rules.md 2>/dev/null)" "- clean edit" \
    "the clean edit commits after the newline append fails"
fi

section "sync-push — a missing helper degrades quietly, not the privacy notice"
MISSING_ROOT="$TMP_ROOT/missing-helper"
MISSING_HOME="$MISSING_ROOT/home"
MISSING_STORE="$MISSING_ROOT/store"
MISSING_BIN="$MISSING_ROOT/bin"
mkdir -p "$MISSING_HOME/.claude" "$MISSING_STORE/corrections" "$MISSING_BIN"
cp "$SYNC_PUSH" "$MISSING_BIN/sync-push.sh"
printf 'SYNC_BACKEND=nfs\nSYNC_DIR=%s\n' "$MISSING_STORE" > "$MISSING_HOME/.claude/.sync-config"
git -C "$MISSING_STORE" init -q
git -C "$MISSING_STORE" config user.email test@clade.local
git -C "$MISSING_STORE" config user.name clade-test
printf '{"event":"already tracked"}\n' > "$MISSING_STORE/corrections/history.jsonl"
printf -- '- clean base\n' > "$MISSING_STORE/corrections/rules.md"
git -C "$MISSING_STORE" add -A
git -C "$MISSING_STORE" -c core.hooksPath=/dev/null commit -qm base
printf -- '- clean edit\n' > "$MISSING_STORE/corrections/rules.md"
HOME="$MISSING_HOME" CLADE_RUNTIME_DIR="$MISSING_ROOT/runtime" CLADE_SYNC_PUSH_TODAY=2026-11-07 \
  bash "$MISSING_BIN/sync-push.sh" > "$MISSING_ROOT/output" 2> "$MISSING_ROOT/error"
assert_eq "$?" "0" "sync-push without its sibling helper commits a clean edit"
assert_eq "$(cat "$MISSING_ROOT/error")" "" "a missing helper emits no stderr"
assert_eq "$(git -C "$MISSING_STORE" show HEAD:corrections/rules.md 2>/dev/null)" "- clean edit" \
  "the clean edit reaches the store history without the helper"
assert_eq "$(grep -cF 'corrections/history.jsonl is already tracked' "$MISSING_HOME/.claude/.sync-conflicts.log" 2>/dev/null)" "1" \
  "the tracked-history notice still works without the helper"
if [[ ! -e "$MISSING_STORE/.gitignore" ]]; then
  pass "a missing helper does not invent an ignore file"
else
  fail "a missing helper does not invent an ignore file" ".gitignore exists"
fi

section "sync-push — unreadable and failing helper sources are also quiet"
for _failure in directory invalid; do
  SOURCE_ROOT="$TMP_ROOT/source-$_failure"
  SOURCE_HOME="$SOURCE_ROOT/home"
  SOURCE_STORE="$SOURCE_ROOT/store"
  SOURCE_BIN="$SOURCE_ROOT/bin"
  mkdir -p "$SOURCE_HOME/.claude" "$SOURCE_STORE/corrections" "$SOURCE_BIN"
  cp "$SYNC_PUSH" "$SOURCE_BIN/sync-push.sh"
  if [[ "$_failure" == "directory" ]]; then
    mkdir "$SOURCE_BIN/sync-store-heal.sh"
  else
    printf 'false\n' > "$SOURCE_BIN/sync-store-heal.sh"
  fi
  printf 'SYNC_BACKEND=nfs\nSYNC_DIR=%s\n' "$SOURCE_STORE" > "$SOURCE_HOME/.claude/.sync-config"
  git -C "$SOURCE_STORE" init -q
  git -C "$SOURCE_STORE" config user.email test@clade.local
  git -C "$SOURCE_STORE" config user.name clade-test
  printf -- '- clean base\n' > "$SOURCE_STORE/corrections/rules.md"
  git -C "$SOURCE_STORE" add -A
  git -C "$SOURCE_STORE" -c core.hooksPath=/dev/null commit -qm base
  printf -- '- clean edit\n' > "$SOURCE_STORE/corrections/rules.md"
  HOME="$SOURCE_HOME" CLADE_RUNTIME_DIR="$SOURCE_ROOT/runtime" \
    bash "$SOURCE_BIN/sync-push.sh" > "$SOURCE_ROOT/output" 2> "$SOURCE_ROOT/error"
  assert_eq "$?" "0" "a $_failure helper source does not abort sync-push"
  assert_eq "$(cat "$SOURCE_ROOT/error")" "" "a $_failure helper source emits no stderr"
  assert_eq "$(git -C "$SOURCE_STORE" show HEAD:corrections/rules.md 2>/dev/null)" "- clean edit" \
    "a $_failure helper source still permits the clean commit"
done
unset _failure

section "sync-setup — ignore write failure is explicit and makes no commit"
SETUP_FAIL_ROOT="$TMP_ROOT/setup-write-failure"
SETUP_FAIL_HOME="$SETUP_FAIL_ROOT/home"
SETUP_FAIL_NFS="$SETUP_FAIL_ROOT/nfs"
SETUP_FAIL_STORE="$SETUP_FAIL_NFS/claude-dotfiles"
SETUP_FAIL_BIN="$SETUP_FAIL_ROOT/bin"
mkdir -p "$SETUP_FAIL_HOME/.claude/corrections" "$SETUP_FAIL_STORE" "$SETUP_FAIL_BIN"
printf '{"event":"private"}\n' > "$SETUP_FAIL_HOME/.claude/corrections/history.jsonl"
ln -s missing-dir/gitignore "$SETUP_FAIL_STORE/.gitignore"
cp "$SYNC_SETUP" "$SETUP_FAIL_BIN/sync-setup.sh"
if [[ -f "$SYNC_HEAL" ]]; then
  cp "$SYNC_HEAL" "$SETUP_FAIL_BIN/sync-store-heal.sh"
fi
printf '#!/bin/sh\nexit 1\n' > "$SETUP_FAIL_BIN/gh"
printf '#!/bin/sh\nexit 0\n' > "$SETUP_FAIL_BIN/sync-link-projects.sh"
chmod +x "$SETUP_FAIL_BIN/gh" "$SETUP_FAIL_BIN/sync-link-projects.sh"
HOME="$SETUP_FAIL_HOME" PATH="$SETUP_FAIL_BIN:$PATH" \
  bash "$SETUP_FAIL_BIN/sync-setup.sh" --nfs "$SETUP_FAIL_NFS" \
  > "$SETUP_FAIL_ROOT/output" 2> "$SETUP_FAIL_ROOT/error"
if [[ "$?" -ne 0 ]]; then
  pass "an unwritable setup ignore file stops initialization"
else
  fail "an unwritable setup ignore file stops initialization" "sync-setup exited 0"
fi
assert_eq "$(grep -xcF "sync-setup: could not write $SETUP_FAIL_STORE/.gitignore; no initial commit was made." "$SETUP_FAIL_ROOT/error")" "1" \
  "the setup write failure names the ignore file and absent initial commit"
if git -C "$SETUP_FAIL_STORE" rev-parse --verify HEAD >/dev/null 2>&1; then
  fail "the failed setup makes no initial commit" "HEAD exists"
else
  pass "the failed setup makes no initial commit"
fi
assert_not_contains "$(git -C "$SETUP_FAIL_STORE" ls-files)" \
  "corrections/history.jsonl" "the failed setup does not track private history"

section "sync-setup — a missing helper is explicit and makes no commit"
SETUP_MISSING_ROOT="$TMP_ROOT/setup-missing-helper"
SETUP_MISSING_HOME="$SETUP_MISSING_ROOT/home"
SETUP_MISSING_NFS="$SETUP_MISSING_ROOT/nfs"
SETUP_MISSING_STORE="$SETUP_MISSING_NFS/claude-dotfiles"
SETUP_MISSING_BIN="$SETUP_MISSING_ROOT/bin"
mkdir -p "$SETUP_MISSING_HOME/.claude/corrections" "$SETUP_MISSING_NFS" "$SETUP_MISSING_BIN"
printf '{"event":"private"}\n' > "$SETUP_MISSING_HOME/.claude/corrections/history.jsonl"
cp "$SYNC_SETUP" "$SETUP_MISSING_BIN/sync-setup.sh"
printf '#!/bin/sh\nexit 1\n' > "$SETUP_MISSING_BIN/gh"
printf '#!/bin/sh\nexit 0\n' > "$SETUP_MISSING_BIN/sync-link-projects.sh"
chmod +x "$SETUP_MISSING_BIN/gh" "$SETUP_MISSING_BIN/sync-link-projects.sh"
HOME="$SETUP_MISSING_HOME" PATH="$SETUP_MISSING_BIN:$PATH" \
  bash "$SETUP_MISSING_BIN/sync-setup.sh" --nfs "$SETUP_MISSING_NFS" \
  > "$SETUP_MISSING_ROOT/output" 2> "$SETUP_MISSING_ROOT/error"
if [[ "$?" -ne 0 ]]; then
  pass "a missing setup helper stops initialization"
else
  fail "a missing setup helper stops initialization" "sync-setup exited 0"
fi
assert_eq "$(grep -xcF "sync-setup: could not load $SETUP_MISSING_BIN/sync-store-heal.sh for $SETUP_MISSING_STORE/.gitignore; no initial commit was made." "$SETUP_MISSING_ROOT/error")" "1" \
  "the missing-helper error names both required paths and no initial commit"
if git -C "$SETUP_MISSING_STORE" rev-parse --verify HEAD >/dev/null 2>&1; then
  fail "the missing-helper setup makes no initial commit" "HEAD exists"
else
  pass "the missing-helper setup makes no initial commit"
fi

section "sync-push — concurrent project-paths lines union-merge"
UNION_ROOT="$TMP_ROOT/project-paths-union"
UNION_BARE="$UNION_ROOT/bare.git"
UNION_A="$UNION_ROOT/clone-a"
UNION_B="$UNION_ROOT/clone-b"
UNION_A_HOME="$UNION_ROOT/home-a"
UNION_B_HOME="$UNION_ROOT/home-b"
UNION_PATHS="projects-memory/repo-github-com-Owner-Repo/.project-paths"
mkdir -p "$UNION_A_HOME/.claude" "$UNION_B_HOME/.claude" "$UNION_ROOT"
git init -q --bare "$UNION_BARE"
# The bare store is empty until the first push; git warns about that on stderr.
git clone -q "$UNION_BARE" "$UNION_A" 2>/dev/null
mkdir -p "$UNION_A/projects-memory/repo-github-com-Owner-Repo"
printf 'seed-host\tprojects/seed\n' > "$UNION_A/$UNION_PATHS"
git -C "$UNION_A" config user.email test@clade.local
git -C "$UNION_A" config user.name clade-test
git -C "$UNION_A" config core.hooksPath /dev/null
git -C "$UNION_A" add -A
git -C "$UNION_A" commit -qm base
git -C "$UNION_A" push -qu origin HEAD >/dev/null 2>&1
git clone -q "$UNION_BARE" "$UNION_B"
for clone in "$UNION_A" "$UNION_B"; do
  git -C "$clone" config user.email test@clade.local
  git -C "$clone" config user.name clade-test
  git -C "$clone" config core.hooksPath /dev/null
done
printf 'SYNC_BACKEND=nfs\nSYNC_DIR=%s\n' "$UNION_A" > "$UNION_A_HOME/.claude/.sync-config"
printf 'SYNC_BACKEND=nfs\nSYNC_DIR=%s\n' "$UNION_B" > "$UNION_B_HOME/.claude/.sync-config"
printf 'host-a\tprojects/repo\n' >> "$UNION_A/$UNION_PATHS"
HOME="$UNION_A_HOME" CLADE_RUNTIME_DIR="$UNION_ROOT/runtime-a" bash "$SYNC_PUSH_RUN" > "$UNION_ROOT/output-a" 2>&1
assert_eq "$?" "0" "the first host pushes its appended line"
printf 'host-b\tshared/repo\n' >> "$UNION_B/$UNION_PATHS"
HOME="$UNION_B_HOME" CLADE_RUNTIME_DIR="$UNION_ROOT/runtime-b" bash "$SYNC_PUSH_RUN" > "$UNION_ROOT/output-b" 2>&1
assert_eq "$?" "0" "the second host pulls, merges and pushes through sync-push"
EXPECTED_PATHS=$(printf 'seed-host\tprojects/seed\nhost-a\tprojects/repo\nhost-b\tshared/repo')
assert_eq "$(cat "$UNION_B/$UNION_PATHS")" "$EXPECTED_PATHS" \
  "both hosts' lines survive the real merge path"
printf 'trigger the pull\n' > "$UNION_A/projects-memory/repo-github-com-Owner-Repo/trigger.md"
HOME="$UNION_A_HOME" CLADE_RUNTIME_DIR="$UNION_ROOT/runtime-a" bash "$SYNC_PUSH_RUN" >/dev/null 2>&1
assert_eq "$(cat "$UNION_A/$UNION_PATHS")" "$EXPECTED_PATHS" \
  "the first host receives the other line on its next pull"
assert_eq "$(git --git-dir="$UNION_BARE" show "HEAD:$UNION_PATHS")" \
  "$EXPECTED_PATHS" "the bare store contains every host line"
assert_eq "$(grep -xcF 'projects-memory/*/.project-paths merge=union' "$UNION_B/.gitattributes" 2>/dev/null)" "1" \
  "healing stays idempotent through the merge"
UNION_HEAD=$(git -C "$UNION_B" rev-parse HEAD)
HOME="$UNION_B_HOME" CLADE_RUNTIME_DIR="$UNION_ROOT/runtime-b" bash "$SYNC_PUSH_RUN" >/dev/null 2>&1
assert_eq "$(git -C "$UNION_B" rev-parse HEAD)" "$UNION_HEAD" "a further push changes no commit"

section "Summary"
echo -e "  Ran: $TESTS_RUN  ${GREEN}Passed: $TESTS_PASSED${NC}  ${RED}Failed: $TESTS_FAILED${NC}"
[[ "$TESTS_FAILED" -eq 0 ]] && { echo -e "  ${GREEN}ALL PASSED${NC}"; exit 0; } || { echo -e "  ${RED}FAILURES${NC}"; exit 1; }
