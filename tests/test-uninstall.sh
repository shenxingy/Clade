#!/usr/bin/env bash
# test-uninstall.sh — how uninstall.sh rewrites ~/.claude/settings.json and the
# shell rc files it took aliases out of.
#
# Each case runs the real uninstall.sh against a temporary HOME. The cases pin
# what a rewrite must keep: the file's mode and a link, the run itself when one
# file cannot be rewritten, and no candidate file left behind. Until 2026-11-26
# settings.json went through the fixed path /tmp/claude-settings-clean.json and
# `mv` (so a 0600 file came back 0644 and a link became a plain file), a
# settings.json jq could not parse ended the whole run under `set -e`, and the
# aliases went through `sed -i`, which BSD sed rejects, ending the run on macOS.
# No network, credential or real user file is used.
#
# Usage:
#   bash tests/test-uninstall.sh
#   UNINSTALL_SH=/path/old-uninstall.sh bash tests/test-uninstall.sh  # RED control

set -uo pipefail

SRC_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNINSTALL_SH="${UNINSTALL_SH:-$SRC_ROOT/uninstall.sh}"
TMP_ROOT=$(mktemp -d)
trap 'rm -rf "$TMP_ROOT"' EXIT

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'
section() { printf "\n${YELLOW}━━━ %s ━━━${NC}\n" "$1"; }
pass() { TESTS_RUN=$((TESTS_RUN + 1)); TESTS_PASSED=$((TESTS_PASSED + 1)); printf "  ${GREEN}✓${NC} %s\n" "$1"; }
fail() {
  TESTS_RUN=$((TESTS_RUN + 1)); TESTS_FAILED=$((TESTS_FAILED + 1))
  printf "  ${RED}✗${NC} %s\n" "$1"
  [[ -z "${2:-}" ]] || printf "    ${RED}→ %s${NC}\n" "$2"
  return 0
}
assert_eq() {
  if [[ "$1" == "$2" ]]; then pass "$3"; else fail "$3" "want='$2' got='$1'"; fi
}
assert_contains() {
  if grep -qF -- "$2" <<< "$1"; then pass "$3"; else fail "$3" "missing '$2'"; fi
}
assert_not_contains() {
  if grep -qF -- "$2" <<< "$1"; then fail "$3" "unexpected '$2'"; else pass "$3"; fi
}

# jq is what uninstall.sh needs to edit settings.json at all; without it every
# case below would test the skip branch. Fail rather than skip.
command -v jq >/dev/null 2>&1 || { echo "missing required test tool: jq"; exit 1; }

mode_of() { stat -c %a "$1" 2>/dev/null || stat -f %Lp "$1"; }

ALIASES='# Claude Code: skip permission prompts (added by clade)
alias claude="claude --dangerously-skip-permissions"
alias cc="claude --dangerously-skip-permissions"'

# new_home DIR: a HOME holding a settings.json with Clade's keys and the user's
# own, and a .zshrc with Clade's alias block between two user lines.
new_home() {
  local home="$1"
  mkdir -p "$home/.claude"
  printf '{"env":{"KEEP":"1"},"hooks":{"Stop":[]},"statusLine":{"type":"command"}}\n' \
    > "$home/.claude/settings.json"
  printf 'export BEFORE=1\n%s\nexport AFTER=1\n' "$ALIASES" > "$home/.zshrc"
}

# run_uninstall HOME LOG [PATH_PREFIX] — prints the exit code.
run_uninstall() {
  local home="$1" log="$2" prefix="${3:-}"
  HOME="$home" CODEX_HOME="$home/.codex" PATH="${prefix:+$prefix:}$PATH" \
    bash "$UNINSTALL_SH" </dev/null > "$log" 2>&1
  echo $?
}

leftovers() { find "$1" \( -name '.settings.json.*' -o -name '.zshrc.clade.*' \) 2>/dev/null | wc -l | tr -d ' '; }

# ─── settings.json ────────────────────────────────────────────────────

section "settings.json: Clade's keys go, the file stays the user's"
H="$TMP_ROOT/plain"
new_home "$H"
chmod 600 "$H/.claude/settings.json"
rc=$(run_uninstall "$H" "$TMP_ROOT/plain.log")
assert_eq "$rc" "0" "uninstall exits 0"
assert_eq "$(jq -c 'has("hooks"), has("statusLine"), .env.KEEP' "$H/.claude/settings.json" | tr '\n' ' ')" \
  "false false \"1\" " "hooks and statusLine are removed, the user's env is kept"
assert_eq "$(mode_of "$H/.claude/settings.json")" "600" "a 0600 settings.json is still 0600"
assert_eq "$(leftovers "$H")" "0" "no candidate file is left beside it"

section "settings.json that is a link"
H="$TMP_ROOT/linked"
new_home "$H"
mkdir -p "$TMP_ROOT/dotfiles"
mv "$H/.claude/settings.json" "$TMP_ROOT/dotfiles/settings.json"
ln -s "$TMP_ROOT/dotfiles/settings.json" "$H/.claude/settings.json"
rc=$(run_uninstall "$H" "$TMP_ROOT/linked.log")
assert_eq "$rc" "0" "uninstall exits 0"
if [[ -L "$H/.claude/settings.json" ]]; then pass "settings.json is still a link"
else fail "settings.json is still a link" "it was replaced by a plain file"; fi
assert_eq "$(jq -c 'has("hooks")' "$TMP_ROOT/dotfiles/settings.json")" "false" \
  "the file it links to is the one cleaned"

section "settings.json that jq cannot parse"
H="$TMP_ROOT/broken"
new_home "$H"
printf '{"hooks": {broken\n' > "$H/.claude/settings.json"
cp "$H/.claude/settings.json" "$TMP_ROOT/broken-before.json"
rc=$(run_uninstall "$H" "$TMP_ROOT/broken.log")
assert_eq "$rc" "0" "uninstall exits 0"
assert_eq "$(cksum < "$H/.claude/settings.json")" "$(cksum < "$TMP_ROOT/broken-before.json")" \
  "the unparseable settings.json is left byte for byte"
assert_contains "$(cat "$TMP_ROOT/broken.log")" "settings.json unchanged (jq cannot parse it)" \
  "the run says it left settings.json alone"
assert_not_contains "$(cat "$H/.zshrc")" "dangerously-skip-permissions" \
  "the run went on: the aliases after it were still removed"
assert_eq "$(leftovers "$H")" "0" "no candidate file is left beside it"

# ─── shell rc files ───────────────────────────────────────────────────

section "aliases: only Clade's block goes, the rc file stays the user's"
H="$TMP_ROOT/rc"
new_home "$H"
chmod 600 "$H/.zshrc"
rc=$(run_uninstall "$H" "$TMP_ROOT/rc.log")
assert_eq "$rc" "0" "uninstall exits 0"
assert_eq "$(cat "$H/.zshrc")" "$(printf 'export BEFORE=1\nexport AFTER=1')" \
  "the alias block is removed and the user's lines around it are kept"
assert_eq "$(mode_of "$H/.zshrc")" "600" "a 0600 .zshrc is still 0600"
assert_eq "$(leftovers "$H")" "0" "no candidate file is left beside it"

section "aliases in a linked rc file"
H="$TMP_ROOT/rc-linked"
new_home "$H"
mv "$H/.zshrc" "$TMP_ROOT/dotfiles/zshrc"
ln -s "$TMP_ROOT/dotfiles/zshrc" "$H/.zshrc"
rc=$(run_uninstall "$H" "$TMP_ROOT/rc-linked.log")
assert_eq "$rc" "0" "uninstall exits 0"
if [[ -L "$H/.zshrc" ]]; then pass ".zshrc is still a link"
else fail ".zshrc is still a link" "it was replaced by a plain file"; fi
assert_not_contains "$(cat "$TMP_ROOT/dotfiles/zshrc")" "dangerously-skip-permissions" \
  "the file it links to is the one cleaned"

# BSD sed, as on macOS, takes the argument after -i as a backup suffix, so
# `sed -i 'script' file` reads the file name as its script and fails. This shim
# refuses -i the same way and passes every other call to the real sed.
section "aliases under a sed that rejects a bare -i (BSD, macOS)"
SHIM="$TMP_ROOT/bsd-sed-bin"
mkdir -p "$SHIM"
REAL_SED=$(command -v sed)
cat > "$SHIM/sed" <<EOF
#!/usr/bin/env bash
for a in "\$@"; do [[ "\$a" == -i* ]] && { echo "sed: 1: \"\$2\": invalid command code" >&2; exit 1; }; done
exec "$REAL_SED" "\$@"
EOF
chmod +x "$SHIM/sed"
H="$TMP_ROOT/bsd"
new_home "$H"
rc=$(run_uninstall "$H" "$TMP_ROOT/bsd.log" "$SHIM")
assert_eq "$rc" "0" "uninstall exits 0"
assert_not_contains "$(cat "$H/.zshrc")" "dangerously-skip-permissions" "the aliases are removed"
assert_contains "$(cat "$TMP_ROOT/bsd.log")" "Removed aliases from $H/.zshrc" "the run says so"

# ─── Summary ─────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ $TESTS_FAILED -eq 0 ]]; then
  echo -e "  ${GREEN}ALL PASSED${NC} ($TESTS_PASSED/$TESTS_RUN)"
else
  echo -e "  ${RED}$TESTS_FAILED FAILED${NC} / $TESTS_PASSED passed / $TESTS_RUN total"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

[[ $TESTS_FAILED -eq 0 ]]
