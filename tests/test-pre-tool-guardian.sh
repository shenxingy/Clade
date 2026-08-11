#!/usr/bin/env bash
# test-pre-tool-guardian.sh — Tests for configs/hooks/pre-tool-guardian.sh
#   (PreToolUse Bash: block catastrophic / irreversible shell commands)
#
# Pipes fixture hook-input JSON through the hook and asserts the allow/block
# verdict. Nothing is ever executed — the hook only inspects the command
# string, so these fixtures are inert text.
#
# The catastrophic-rm rule is the focus. It must stay sharp in BOTH
# directions, and the regression it guards is real: matching per LINE blocked
# `SRC=/home/me/.claude; rm -rf /tmp/shadow-test`, a benign temp delete that
# merely shared a line with a home path. Shell one-liners chain statements
# with ; && || far more often than they use newlines, so the rule matches per
# STATEMENT and every condition must be met by the same statement.
#
# Usage:
#   bash tests/test-pre-tool-guardian.sh        # Run all tests
#   bash tests/test-pre-tool-guardian.sh -v     # Verbose mode

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK="$REPO_ROOT/configs/hooks/pre-tool-guardian.sh"

# ─── Test framework (mirrors tests/test-rule-injector.sh) ────────────
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
VERBOSE="${1:-}"

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[0;33m'; NC='\033[0m'

section() { printf "\n${YELLOW}━━━ %s ━━━${NC}\n" "$1"; }

# verdict <command> → prints "BLOCK" or "ALLOW"
verdict() {
  local out
  out=$(python3 -c "
import json,sys
print(json.dumps({'tool_name':'Bash','tool_input':{'command':sys.argv[1]}}))" "$1" \
    | bash "$HOOK" 2>&1)
  if [[ "$out" == *'"block"'* ]]; then echo "BLOCK"; else echo "ALLOW"; fi
}

assert_verdict() {
  local label="$1" cmd="$2" want="$3" got
  TESTS_RUN=$((TESTS_RUN + 1))
  got=$(verdict "$cmd")
  if [[ "$got" == "$want" ]]; then
    TESTS_PASSED=$((TESTS_PASSED + 1))
    printf "  ${GREEN}✓${NC} %s\n" "$label"
    [[ "$VERBOSE" == "-v" ]] && printf "      cmd: %s\n" "$cmd"
  else
    TESTS_FAILED=$((TESTS_FAILED + 1))
    printf "  ${RED}✗${NC} %s (got=%s want=%s)\n" "$label" "$got" "$want"
    printf "      cmd: %s\n" "$cmd"
  fi
  return 0
}

# ─── Catastrophic rm: must stay blocked ──────────────────────────────
section "Catastrophic rm — true positives"
assert_verdict "home directory"            'rm -rf /home/alexshen'                BLOCK
assert_verdict "filesystem root"           'rm -rf /'                             BLOCK
assert_verdict "root with glob"            'rm -rf /*'                            BLOCK
assert_verdict "\$HOME, flags reversed"    'rm -fr $HOME'                         BLOCK
assert_verdict "tilde"                     'rm -rf ~/projects'                    BLOCK
assert_verdict "/etc"                      'rm -rf /etc/nginx'                    BLOCK
assert_verdict "/usr"                      'rm -rf /usr/local'                    BLOCK
assert_verdict "split flags -r -f"         'rm -r -f /home/alexshen'              BLOCK
assert_verdict "combined flags -rfi"       'rm -rfi /home/alexshen'               BLOCK
assert_verdict "dangerous rm later in chain" \
  'cd /tmp && rm -rf /home/alexshen'                                              BLOCK
assert_verdict "dangerous rm inside \$()" \
  'echo $(rm -rf /home/alexshen)'                                                 BLOCK

# ─── Benign deletes: must be allowed ─────────────────────────────────
# Every case below is a real shape produced while working on Clade's own
# correction-pairing shadows under /tmp — these are exactly what regressed.
section "Benign deletes — false-positive regressions"
assert_verdict "temp cleanup alone"        'rm -rf /tmp/scratch/x'                ALLOW
assert_verdict "temp cleanup + home path in same statement-line" \
  'rm -rf /tmp/scratch/x; cp -r /home/alexshen/foo /tmp/scratch/'                 ALLOW
assert_verdict "temp cleanup after cd into home" \
  'cd /home/alexshen/projects/Clade && rm -rf /tmp/shadow-test'                   ALLOW
assert_verdict "home path captured in a variable first" \
  'SRC=/home/alexshen/.claude; rm -rf /tmp/claude-edit-shadows'                   ALLOW
assert_verdict "home path piped into the same line" \
  'ls /home/alexshen | head -1; rm -rf /tmp/out'                                  ALLOW
assert_verdict "rm without -f"             'rm -r /home/alexshen/tmpdir'          ALLOW
assert_verdict "rm without -r"             'rm -f /home/alexshen/note.txt'        ALLOW
# Conditions must be met by ONE statement, not pooled across several.
assert_verdict "-r and -f split across two separate rm statements" \
  'rm -r /tmp/a; rm -f /home/alexshen/b'                                          ALLOW
assert_verdict "no rm at all"              'cp -rf /home/alexshen /tmp/backup'    ALLOW
# The tilde anchor must mean "home reference", not "the character ~".
assert_verdict "trailing-tilde backup file" 'rm -rf /tmp/file~'                   ALLOW
assert_verdict "tilde mid-path, not home"  'rm -rf /tmp/a~b/c'                    ALLOW

# ─── Other guardian rules still fire ─────────────────────────────────
section "Other rules — unaffected by the rm change"
assert_verdict "force push to main"        'git push --force origin main'         BLOCK
assert_verdict "SQL DROP"                  'psql -c "DROP DATABASE prod"'         BLOCK
assert_verdict "ordinary command"          'git status'                           ALLOW

# ─── Summary ─────────────────────────────────────────────────────────
printf "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
if [[ "$TESTS_FAILED" -eq 0 ]]; then
  printf "  ${GREEN}ALL PASSED${NC} (%d/%d)\n" "$TESTS_PASSED" "$TESTS_RUN"
else
  printf "  ${RED}FAILED${NC} (%d/%d passed, %d failed)\n" \
    "$TESTS_PASSED" "$TESTS_RUN" "$TESTS_FAILED"
fi
printf "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
[[ "$TESTS_FAILED" -eq 0 ]]
