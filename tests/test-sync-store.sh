#!/usr/bin/env bash
# test-sync-store.sh — generated and self-healed ignores for the dotfiles store.
#
# Every HOME and git repository is a throwaway fixture. The setup run uses a
# fake gh and a stub project linker, so it cannot reach the network or another
# checkout. The push fixture has no remote.
#
# Internal: CLADE_TEST_SYNC_SETUP and CLADE_TEST_SYNC_PUSH may name scratch
# copies of the scripts, used to prove these cases fail against older code.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SYNC_SETUP="${CLADE_TEST_SYNC_SETUP:-$REPO_ROOT/configs/scripts/sync-setup.sh}"
SYNC_PUSH="${CLADE_TEST_SYNC_PUSH:-$REPO_ROOT/configs/scripts/sync-push.sh}"

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

TMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/clade-sync-store.XXXXXX")"
trap 'rm -rf "$TMP_ROOT"' EXIT
export HOME="$TMP_ROOT/home"
mkdir -p "$HOME"
export GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME=clade-test GIT_AUTHOR_EMAIL=test@clade.local
export GIT_COMMITTER_NAME=clade-test GIT_COMMITTER_EMAIL=test@clade.local
unset CLAUDE_CONFIG_DIR CLADE_PRIVATE_PROJECTS CLADE_PRIVATE_KEYWORDS CLADE_SYNC_PUSH_LOCK

section "sync-setup — a fresh store ignores quarantined files"
SETUP_ROOT="$TMP_ROOT/setup"
SETUP_HOME="$SETUP_ROOT/home"
SETUP_NFS="$SETUP_ROOT/nfs"
mkdir -p "$SETUP_HOME/.claude" "$SETUP_NFS" "$SETUP_ROOT/bin"
cp "$SYNC_SETUP" "$SETUP_ROOT/bin/sync-setup.sh"
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
assert_eq "$SETUP_IGNORE" "$(printf '*.corrupt.*\nskills/.trash/')" \
  "the generated .gitignore contains exactly the quarantine patterns"
assert_eq "$(grep -xcF '*.corrupt.*' "$SETUP_STORE/.gitignore" 2>/dev/null)" "1" \
  "sync-setup writes the corrupt-backup pattern once"
assert_eq "$(grep -xcF 'skills/.trash/' "$SETUP_STORE/.gitignore" 2>/dev/null)" "1" \
  "sync-setup writes the skills trash pattern once"
assert_eq "$(grep -xcF 'projects-memory/*/.project-paths merge=union' "$SETUP_STORE/.gitattributes" 2>/dev/null)" "1" \
  "sync-setup marks per-host project paths for union merge"

# Re-running setup is also an upgrade path. A comment containing either pattern
# is not the pattern line itself. Keep the final local line unterminated too.
SETUP_COMMENT='# keep *.corrupt.* and skills/.trash/ out of git'
printf '%s\nsetup-local' "$SETUP_COMMENT" > "$SETUP_STORE/.gitignore"
HOME="$SETUP_HOME" PATH="$SETUP_ROOT/bin:$PATH" \
  bash "$SETUP_ROOT/bin/sync-setup.sh" --nfs "$SETUP_NFS" >/dev/null 2>&1
assert_eq "$?" "0" "sync-setup also upgrades an existing store"
EXPECTED_SETUP_IGNORE=$(printf '%s\nsetup-local\n*.corrupt.*\nskills/.trash/' "$SETUP_COMMENT")
assert_eq "$(cat "$SETUP_STORE/.gitignore")" "$EXPECTED_SETUP_IGNORE" \
  "setup matches whole lines, not comments, and preserves an unterminated final line"
HOME="$SETUP_HOME" PATH="$SETUP_ROOT/bin:$PATH" \
  bash "$SETUP_ROOT/bin/sync-setup.sh" --nfs "$SETUP_NFS" >/dev/null 2>&1
assert_eq "$(cat "$SETUP_STORE/.gitignore")" "$EXPECTED_SETUP_IGNORE" \
  "a further setup run is idempotent"

section "sync scripts — both entry points use the same patterns"
SETUP_PATTERN_LIST=$(sed -n 's/^for _sync_ignore in \(.*\); do$/\1/p' "$SYNC_SETUP")
PUSH_PATTERN_LIST=$(sed -n 's/^sync_push_append_missing .*gitignore" \(.*\)$/\1/p' "$SYNC_PUSH")
# Two empty extractions would compare equal, so the parity check needs both.
if [[ -n "$SETUP_PATTERN_LIST" && -n "$PUSH_PATTERN_LIST" ]]; then
  pass "both pattern-list extractions are non-empty"
else
  fail "both pattern-list extractions are non-empty" "setup='$SETUP_PATTERN_LIST' push='$PUSH_PATTERN_LIST'"
fi
assert_eq "$PUSH_PATTERN_LIST" "$SETUP_PATTERN_LIST" "setup and push carry byte-identical ignore patterns"
assert_eq "$(grep -cF 'projects-memory/*/.project-paths merge=union' "$SYNC_SETUP")" "1" \
  "setup carries the project-paths attribute"
assert_eq "$(grep -cF 'projects-memory/*/.project-paths merge=union' "$SYNC_PUSH")" "1" \
  "push carries the same attribute for existing stores"

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
  bash "$SYNC_PUSH" > "$PUSH_ROOT/output" 2>&1
PUSH_RC=$?
PUSH_OUT=$(cat "$PUSH_ROOT/output"; cat "$PUSH_HOME/.claude/.sync-conflicts.log" 2>/dev/null)
assert_eq "$PUSH_RC" "0" "x.corrupt.1 and skills/.trash markers no longer refuse the push"
assert_not_contains "$PUSH_OUT" "REFUSED" "the marker guard does not log a refusal for an ignored quarantine file"
assert_eq "$(git -C "$PUSH_STORE" show HEAD:corrections/rules.md 2>/dev/null)" "$(printf -- '- rule one\n- rule two')" \
  "the ordinary clean edit still commits"
PUSH_TRACKED=$(git -C "$PUSH_STORE" ls-files)
assert_not_contains "$PUSH_TRACKED" "x.corrupt.1" "the corrupt backup is not committed"
assert_not_contains "$PUSH_TRACKED" "skills/.trash/markers.md" "the trash file is not committed"
EXPECTED_IGNORE=$(printf '%s\nlocal-first\nlocal-last\n*.corrupt.*\nskills/.trash/' "$PUSH_COMMENT")
assert_eq "$(cat "$PUSH_STORE/.gitignore")" "$EXPECTED_IGNORE" \
  "healing matches whole lines and appends without reordering existing lines"
HOME="$PUSH_HOME" CLADE_RUNTIME_DIR="$PUSH_ROOT/runtime" bash "$SYNC_PUSH" >/dev/null 2>&1
assert_eq "$(cat "$PUSH_STORE/.gitignore")" "$EXPECTED_IGNORE" \
  "a second push adds no duplicate lines and needs no trailing-newline repair"
assert_eq "$(grep -xcF '*.corrupt.*' "$PUSH_STORE/.gitignore")" "1" "the corrupt pattern stays singular"
assert_eq "$(grep -xcF 'skills/.trash/' "$PUSH_STORE/.gitignore")" "1" "the trash pattern stays singular"
assert_eq "$(grep -xcF 'projects-memory/*/.project-paths merge=union' "$PUSH_STORE/.gitattributes" 2>/dev/null)" "1" \
  "the existing store heals exactly one project-paths attribute"
assert_eq "$(git -C "$PUSH_STORE" show HEAD:.gitattributes 2>/dev/null)" "projects-memory/*/.project-paths merge=union" \
  "the healed attribute is committed for other hosts"

# The exemption is for ignored quarantine paths only. A marker in an ordinary
# tracked file must still block the commit, so deleting the whole scan cannot
# make this suite green.
printf '%s\n' '<<<<<<< Updated upstream' '=======' '>>>>>>> Stashed changes' >> "$PUSH_STORE/corrections/rules.md"
PUSH_COMMITS=$(git -C "$PUSH_STORE" rev-list --count HEAD)
HOME="$PUSH_HOME" CLADE_RUNTIME_DIR="$PUSH_ROOT/runtime" \
  bash "$SYNC_PUSH" > "$PUSH_ROOT/refused-output" 2>&1
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
  bash "$SYNC_PUSH" > "$FAIL_ROOT/clean-output" 2>&1
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
  bash "$SYNC_PUSH" > "$FAIL_ROOT/refused-output" 2>&1
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
  bash "$SYNC_PUSH" > "$APPEND_ROOT/output" 2>&1
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
    bash "$SYNC_PUSH" > "$NEWLINE_ROOT/output" 2>&1
  NEWLINE_RC=$?
  chmod u+w "$NEWLINE_STORE/.gitignore"
  assert_eq "$NEWLINE_RC" "0" "a newline append failure does not abort a clean push"
  assert_eq "$(cat "$NEWLINE_ROOT/output")" "" "the newline append failure emits no output"
  assert_eq "$(git -C "$NEWLINE_STORE" show HEAD:corrections/rules.md 2>/dev/null)" "- clean edit" \
    "the clean edit commits after the newline append fails"
fi

section "sync-push — concurrent project-paths lines union-merge"
UNION_ROOT="$TMP_ROOT/project-paths-union"
UNION_BARE="$UNION_ROOT/bare.git"
UNION_A="$UNION_ROOT/clone-a"
UNION_B="$UNION_ROOT/clone-b"
UNION_A_HOME="$UNION_ROOT/home-a"
UNION_B_HOME="$UNION_ROOT/home-b"
mkdir -p "$UNION_A_HOME/.claude" "$UNION_B_HOME/.claude" "$UNION_ROOT"
git init -q --bare "$UNION_BARE"
# The bare store is empty until the first push; git warns about that on stderr.
git clone -q "$UNION_BARE" "$UNION_A" 2>/dev/null
mkdir -p "$UNION_A/projects-memory/repo-github-com-Owner-Repo"
printf 'seed-host\tprojects/seed\n' > "$UNION_A/projects-memory/repo-github-com-Owner-Repo/.project-paths"
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
printf 'aries\tprojects/internal\n' >> "$UNION_A/projects-memory/repo-github-com-Owner-Repo/.project-paths"
HOME="$UNION_A_HOME" CLADE_RUNTIME_DIR="$UNION_ROOT/runtime-a" bash "$SYNC_PUSH" > "$UNION_ROOT/output-a" 2>&1
assert_eq "$?" "0" "the first host pushes its appended line"
printf 'shenxingy\tshared-nfs/internal\n' >> "$UNION_B/projects-memory/repo-github-com-Owner-Repo/.project-paths"
HOME="$UNION_B_HOME" CLADE_RUNTIME_DIR="$UNION_ROOT/runtime-b" bash "$SYNC_PUSH" > "$UNION_ROOT/output-b" 2>&1
assert_eq "$?" "0" "the second host pulls, merges and pushes through sync-push"
EXPECTED_PATHS=$(printf 'seed-host\tprojects/seed\naries\tprojects/internal\nshenxingy\tshared-nfs/internal')
assert_eq "$(cat "$UNION_B/projects-memory/repo-github-com-Owner-Repo/.project-paths")" "$EXPECTED_PATHS" \
  "both hosts' lines survive the real merge path"
printf 'trigger the pull\n' > "$UNION_A/projects-memory/repo-github-com-Owner-Repo/trigger.md"
HOME="$UNION_A_HOME" CLADE_RUNTIME_DIR="$UNION_ROOT/runtime-a" bash "$SYNC_PUSH" >/dev/null 2>&1
assert_eq "$(cat "$UNION_A/projects-memory/repo-github-com-Owner-Repo/.project-paths")" "$EXPECTED_PATHS" \
  "the first host receives the other line on its next pull"
assert_eq "$(git --git-dir="$UNION_BARE" show HEAD:projects-memory/repo-github-com-Owner-Repo/.project-paths)" \
  "$EXPECTED_PATHS" "the bare store contains every host line"
assert_eq "$(grep -xcF 'projects-memory/*/.project-paths merge=union' "$UNION_B/.gitattributes" 2>/dev/null)" "1" \
  "healing stays idempotent through the merge"
UNION_HEAD=$(git -C "$UNION_B" rev-parse HEAD)
HOME="$UNION_B_HOME" CLADE_RUNTIME_DIR="$UNION_ROOT/runtime-b" bash "$SYNC_PUSH" >/dev/null 2>&1
assert_eq "$(git -C "$UNION_B" rev-parse HEAD)" "$UNION_HEAD" "a further push changes no commit"

section "Summary"
echo -e "  Ran: $TESTS_RUN  ${GREEN}Passed: $TESTS_PASSED${NC}  ${RED}Failed: $TESTS_FAILED${NC}"
[[ "$TESTS_FAILED" -eq 0 ]] && { echo -e "  ${GREEN}ALL PASSED${NC}"; exit 0; } || { echo -e "  ${RED}FAILURES${NC}"; exit 1; }
