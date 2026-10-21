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
# Overridable so the suite can be pointed at an older copy: every case added
# on 2026-10-20 was shown red against the guardian it replaced.
HOOK="${GUARDIAN_HOOK:-$REPO_ROOT/configs/hooks/pre-tool-guardian.sh}"

# ─── Test framework (mirrors tests/test-rule-injector.sh) ────────────
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
VERBOSE="${1:-}"

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[0;33m'; NC='\033[0m'

section() { printf "\n${YELLOW}━━━ %s ━━━${NC}\n" "$1"; }

PY_HOOK="${GUARDIAN_PY_HOOK:-$REPO_ROOT/plugins/clade/hooks/pre_tool_guardian.py}"

# A cwd that is not a git repository, so the "current branch" rule reads
# nothing unless a test points the payload at a repository on purpose.
NOREPO_CWD=$(mktemp -d)
trap 'rm -rf "$NOREPO_CWD"' EXIT

# payload <command> [cwd] → the hook-input JSON both guardians read
payload() {
  python3 -c "
import json,sys
print(json.dumps({'tool_name':'Bash','tool_input':{'command':sys.argv[1],'description':'d','timeout':5000},'cwd':sys.argv[2]}))" "$1" "${2:-$NOREPO_CWD}"
}

# classify <hook-output> <exit-code> <claude|codex> → the verdict, read against
# the schema the RUNTIME accepts, not against substrings.
#
# Until 2026-10-20 this was a substring test — "block" or "deny" read BLOCK,
# any "updatedInput" read REWRITE — so it passed for the whole life of an
# output Claude Code rejected ({"decision":"allow","updatedInput":…}: 41
# rejections, every one running the original command). And an empty output
# read ALLOW, so a guardian that crashed with exit 1 passed every ALLOW case.
# Now:
#   CRASH              non-zero exit — Claude Code runs the command unchecked
#   LEGACY             a top-level decision/reason — deprecated, or rejected
#   NO-EVENT           hookSpecificOutput without hookEventName "PreToolUse"
#   REWRITE-ESCALATES  Claude shape: updatedInput with a permissionDecision —
#                      "allow" would also bypass prompts and deny rules
#   REWRITE-NO-ALLOW   Codex shape: updatedInput without "allow", which Codex
#                      0.163 rejects
# REWRITE is a third verdict, not a flavour of ALLOW: the command that runs is
# not the command that was proposed.
classify() {
  local out="$1" rc="$2" shape="$3"
  if [[ "$rc" != 0 ]]; then echo "CRASH"; return; fi
  if [[ -z "${out//[[:space:]]/}" ]]; then echo "ALLOW"; return; fi
  jq -r --arg shape "$shape" '
    if (type != "object") then "UNPARSED"
    elif has("decision") or has("reason") then "LEGACY"
    else (.hookSpecificOutput // {}) as $h
    | if $h.hookEventName != "PreToolUse" then "NO-EVENT"
      elif $h.permissionDecision == "deny" and (($h.permissionDecisionReason // "") != "") then "BLOCK"
      elif ($h.updatedInput.command? | type) == "string" then
        (if $shape == "claude" and ($h | has("permissionDecision")) then "REWRITE-ESCALATES"
         elif $shape == "codex" and $h.permissionDecision != "allow" then "REWRITE-NO-ALLOW"
         else "REWRITE" end)
      else "UNKNOWN" end
    end' <<< "$out" 2>/dev/null || echo "UNPARSED"
}

# run_sh / run_py <command> [cwd] → raw output; exit code in $RUN_RC
run_sh() { RUN_OUT=$(payload "$1" "${2:-}" | bash "$HOOK" 2>/dev/null); RUN_RC=$?; }
run_py() { RUN_OUT=$(payload "$1" "${2:-}" | python3 "$PY_HOOK" 2>/dev/null); RUN_RC=$?; }

# verdict <command> [cwd] → the shell guardian's verdict
verdict() { run_sh "$1" "${2:-}"; classify "$RUN_OUT" "$RUN_RC" claude; }

# py_verdict <command> [cwd] → the Codex guardian's verdict on the same input
py_verdict() { run_py "$1" "${2:-}"; classify "$RUN_OUT" "$RUN_RC" codex; }

# rewritten <command> [cwd] → the command the shell guardian would run instead
rewritten() { run_sh "$1" "${2:-}"; jq -r '.hookSpecificOutput.updatedInput.command // empty' <<< "$RUN_OUT" 2>/dev/null; }
py_rewritten() { run_py "$1" "${2:-}"; jq -r '.hookSpecificOutput.updatedInput.command // empty' <<< "$RUN_OUT" 2>/dev/null; }

# assert_rewrite <label> <command> <expected command> [cwd]
assert_rewrite() {
  local label="$1" cmd="$2" want="$3" got
  TESTS_RUN=$((TESTS_RUN + 1))
  run_sh "$cmd" "${4:-}"   # not in $(…): RUN_OUT/RUN_RC must reach this shell
  got=$(jq -r '.hookSpecificOutput.updatedInput.command // empty' <<< "$RUN_OUT" 2>/dev/null)
  if [[ "$got" == "$want" && "$(classify "$RUN_OUT" "$RUN_RC" claude)" == "REWRITE" ]]; then
    TESTS_PASSED=$((TESTS_PASSED + 1))
    printf "  ${GREEN}✓${NC} %s\n" "$label"
  else
    TESTS_FAILED=$((TESTS_FAILED + 1))
    printf "  ${RED}✗${NC} %s\n      cmd:  %s\n      want: %s\n      got:  %s (%s)\n" \
      "$label" "$cmd" "$want" "$got" "$(classify "$RUN_OUT" "$RUN_RC" claude)"
  fi
  return 0
}

assert_verdict() {
  local label="$1" cmd="$2" want="$3" got
  TESTS_RUN=$((TESTS_RUN + 1))
  got=$(verdict "$cmd" "${4:-}")
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

# assert_parity <label> <command>
#
# configs/codex-migration.json records the two guardians as a parity pair and
# nothing had ever fed one command to both. They had drifted: the shell hook
# blocked a recursive delete of /home, /etc, /usr, /var, /sys, /proc and /boot
# and the Python mirror allowed every one of them. Aligning the regex once
# would drift again; this is the check that keeps them honest.
assert_parity() {
  local label="$1" cmd="$2" sh py sh_new py_new
  TESTS_RUN=$((TESTS_RUN + 1))
  sh=$(verdict "$cmd")
  py=$(py_verdict "$cmd")
  # A REWRITE must agree on the command too, not only on the verdict: each hook
  # names itself in the unset-variable message, so that label is normalised.
  sh_new=$(rewritten "$cmd"); sh_new=${sh_new//pre-tool-guardian:/GUARD:}
  py_new=$(py_rewritten "$cmd"); py_new=${py_new//pre_tool_guardian:/GUARD:}
  if [[ "$sh" == "$py" && "$sh_new" == "$py_new" ]]; then
    TESTS_PASSED=$((TESTS_PASSED + 1))
    printf "  ${GREEN}✓${NC} parity: %s (%s)\n" "$label" "$sh"
  else
    TESTS_FAILED=$((TESTS_FAILED + 1))
    printf "  ${RED}✗${NC} parity: %s (shell=%s codex=%s)\n" "$label" "$sh" "$py"
    [[ "$sh_new" != "$py_new" ]] && printf "      shell runs: %s\n      codex runs: %s\n" "$sh_new" "$py_new"
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

# ─── Delete targets an agent actually writes ─────────────────────────
#
# The rule above matches the TEXT of the target, so it blocks what a human
# types and allowed everything an agent writes. Measured 2026-09-05: every
# case in this section was ALLOW on both guardians while the spelled-out
# forms were blocked.
#
# The reason it matters is the shell lifecycle, not the regex. Every Bash tool
# call is a fresh shell, so a variable assigned in an earlier call is unset in
# this one and a delete against "$BUILD_DIR"/ expands to the filesystem root —
# the exact string the true-positive section above asserts a BLOCK for. GNU
# rm's --preserve-root does not help: the expanded argument is root-plus-star.
#
# The answer is the shape already in this hook for force-push: answer
# {"decision":"allow","updatedInput":...} and hand back a command that is safe
# to run. ${NAME:?...} runs unchanged when NAME is set and aborts naming
# itself when it is not, so the fix costs a correct command nothing.
section "Unresolved delete targets — rewritten, not allowed"
assert_verdict "bare variable target"          'rm -rf $BUILD_DIR/'          REWRITE
assert_verdict "quoted variable target"        'rm -rf "$BUILD_DIR"/'        REWRITE
assert_verdict "braced variable target"        'rm -rf ${OUT}/'              REWRITE
assert_verdict "variable target with a glob"   'rm -rf $OUT/*'               REWRITE
assert_verdict "quoted variable plus glob"     'rm -rf "$DIR"/*'             REWRITE
assert_verdict "variable target after a cd"    'cd /tmp/x && rm -rf $STALE/' REWRITE

section "Unresolved delete targets — refused outright"
# A command substitution and a bare glob have no rewrite that makes them safe:
# there is no name to make required, and the value is decided at run time.
assert_verdict "command substitution target"   'rm -rf $(pwd)/*'             BLOCK
assert_verdict "glob relative to the cwd"      'rm -rf ./*'                  BLOCK
assert_verdict "bare glob after a cd"          'cd /tmp/x && rm -rf *'       BLOCK

section "Resolved or shell-owned targets — still allowed untouched"
# The rewrite must cost a correct command nothing, or it becomes the next
# thing people learn to work around.
assert_verdict "variable assigned in the same command" \
  'BUILD_DIR=/tmp/safe-build; rm -rf $BUILD_DIR/'                            ALLOW
assert_verdict "variable exported in the same command" \
  'export OUT=/tmp/out && rm -rf $OUT/*'                                     ALLOW
assert_verdict "TMPDIR is set by the shell"     'rm -rf $TMPDIR/scratch'     ALLOW
assert_verdict "literal path is not a variable" 'rm -rf /tmp/scratch/x'      ALLOW
# $HOME is a shell-owned variable AND a catastrophic target. The block wins.
assert_verdict "HOME stays blocked, not rewritten" 'rm -rf $HOME/x'          BLOCK
# Rewriting a token inside a quoted string would corrupt the string.
assert_verdict "delete quoted inside a single-quoted string" \
  "echo 'rm -rf \$FOO/' >> notes.md"                                         ALLOW

# Known limitation, pinned so it is visible rather than surprising.
#
# The rm rule has always been blind to command position: it fires wherever the
# text appears, which is why `echo $(rm -rf <home>)` is asserted BLOCK above —
# there the delete really would run. A double-quoted string carrying the same
# text is not a command, but this rule cannot tell the two apart, so the
# rewrite reaches it too. Single quotes ARE handled, because a rewrite inside
# one would change bytes the shell was going to treat as literal.
#
# Making this exact would need command-position parsing for rm, the way the
# pkill rule already does it. That is a larger change than this fix, and it
# would have to keep the $() case blocking. Recorded here so the next reader
# knows it is a decision, not an oversight.
assert_verdict "double-quoted delete text is rewritten too (known limitation)" \
  'echo "rm -rf $X" > note.txt'                                              REWRITE

# ─── The two guardians agree ─────────────────────────────────────────
section "Parity — the shell hook and the Codex mirror return the same verdict"
assert_parity "home directory"            'rm -rf /home/alexshen'
assert_parity "/etc"                      'rm -rf /etc/nginx'
assert_parity "/usr"                      'rm -rf /usr/local'
assert_parity "/var"                      'rm -rf /var/lib/x'
assert_parity "/sys"                      'rm -rf /sys/kernel'
assert_parity "/proc"                     'rm -rf /proc/1'
assert_parity "/boot"                     'rm -rf /boot/efi'
assert_parity "tilde"                     'rm -rf ~/projects'
assert_parity "HOME"                      'rm -rf $HOME/x'
assert_parity "bare variable target"      'rm -rf $BUILD_DIR/'
assert_parity "quoted variable target"    'rm -rf "$BUILD_DIR"/'
assert_parity "braced variable target"    'rm -rf ${OUT}/'
assert_parity "variable plus glob"        'rm -rf $OUT/*'
assert_parity "command substitution"      'rm -rf $(pwd)/*'
assert_parity "glob relative to the cwd"  'rm -rf ./*'
assert_parity "assigned in the same command" 'BUILD_DIR=/tmp/x; rm -rf $BUILD_DIR/'
assert_parity "benign temp delete"        'rm -rf /tmp/scratch/x'
assert_parity "rm without -f"             'rm -r /home/alexshen/tmpdir'
assert_parity "force push to main"        'git push --force origin main'
assert_parity "force push to a feature branch" 'git push --force origin feature/x'
assert_parity "SQL DROP"                  'psql -c "DROP DATABASE prod"'
assert_parity "ordinary command"          'git status'

# ─── Flags come from options, never from an operand ──────────────────
#
# The guard decided that -r and -f were passed by testing the whole statement
# for `-[a-zA-Z]*r` and `-[a-zA-Z]*f`. Any hyphen inside a FILENAME supplies
# them. Reproduced 2026-09-07: a plain `rm -f` on a path under /home whose
# basename contains a hyphen, some letters and an r was blocked as a
# catastrophic recursive delete, with no -r in the command at all.
#
# It is the over-blocking mirror of the under-blocking fixed the day before,
# and one root cause serves both: the guard matched command TEXT instead of
# classifying tokens. A token supplies flags only when it STARTS with `-`;
# after a `--` nothing does. GNU rm permutes, so an option may follow an
# operand — what it may never do is BE one.
section "Flags are read from options, not from filenames"
assert_verdict "hyphenated filename does not supply -r" \
  'rm -f /home/alexshen/notes/my-report.txt'                                  ALLOW
assert_verdict "the reproduction from the radar run" \
  'rm -f /home/alexshen/.claude/research/.radar-write-probe'                  ALLOW
assert_verdict "another hyphenated basename" \
  'rm -f /home/alexshen/x-ray.log'                                            ALLOW
assert_verdict "hyphenated dir name does not supply -r" \
  'rm -f /home/alexshen/my-project/notes.txt'                                 ALLOW
# The other direction is what the guard is for, and it must not move.
assert_verdict "a real -r on the same path still blocks" \
  'rm -rf /home/alexshen/notes/my-report.txt'                                 BLOCK
assert_verdict "options after the operand still count (GNU permutes)" \
  'rm /home/alexshen/notes -rf'                                               BLOCK
assert_verdict "long options count too" \
  'rm --recursive --force /home/alexshen/notes'                               BLOCK
assert_verdict "after -- a dash token is a filename, not an option" \
  'rm -f -- /home/alexshen/-r-file.txt'                                       ALLOW
assert_verdict "-- does not disarm a real recursive delete" \
  'rm -rf -- /home/alexshen/notes'                                            BLOCK

section "The rewrite and refuse paths read flags the same way"
# Both were added on 2026-09-05 and inherited the same text match, so a plain
# single-file delete was being rewritten or refused on the strength of its
# filename.
assert_verdict "non-recursive delete of a variable path is untouched" \
  'rm -f $BUILD_DIR/my-report.txt'                                            ALLOW
assert_verdict "non-recursive delete under a substitution is untouched" \
  'rm -f $(pwd)/my-report.txt'                                                ALLOW
assert_verdict "non-recursive delete of a bare glob is untouched" \
  'rm -f ./*'                                                                 ALLOW
# And the recursive forms they were built for still fire.
assert_verdict "recursive delete of a variable path is still rewritten" \
  'rm -rf $BUILD_DIR/my-report.txt'                                           REWRITE
assert_verdict "recursive delete under a substitution is still refused" \
  'rm -rf $(pwd)/my-report.txt'                                               BLOCK

section "Parity — flag parsing agrees across both guardians"
assert_parity "hyphenated filename, -f only"  'rm -f /home/alexshen/notes/my-report.txt'
assert_parity "the radar reproduction"        'rm -f /home/alexshen/.claude/research/.radar-write-probe'
assert_parity "real -r on the same path"      'rm -rf /home/alexshen/notes/my-report.txt'
assert_parity "options after the operand"     'rm /home/alexshen/notes -rf'
assert_parity "long options"                  'rm --recursive --force /home/alexshen/notes'
assert_parity "dash token after --"           'rm -f -- /home/alexshen/-r-file.txt'
assert_parity "non-recursive variable path"   'rm -f $BUILD_DIR/my-report.txt'
assert_parity "recursive variable path"       'rm -rf $BUILD_DIR/my-report.txt'

# ─── Other guardian rules still fire ─────────────────────────────────
section "Other rules — unaffected by the rm change"
assert_verdict "force push to main"        'git push --force origin main'         BLOCK
assert_verdict "SQL DROP"                  'psql -c "DROP DATABASE prod"'         BLOCK
assert_verdict "ordinary command"          'git status'                           ALLOW

section "Self-killing pkill -f"
# `pkill -f PAT` matches full command lines, including the launching shell's.
# In an ssh/bash -c one-liner the wrapper's own argv carries PAT, so the shell
# kills itself: exit 255/144, and everything after the && silently never runs.
# It reads as an ssh failure, which is where the debugging time goes.
assert_verdict "ssh one-liner, pattern twice" \
  'ssh lynx "pkill -f train.py; python train.py --resume"'    BLOCK
assert_verdict "ssh one-liner, single occurrence still self-matches" \
  'ssh castor "pkill -f crop_faces"'                          BLOCK
assert_verdict "compound command, pattern twice" \
  'pkill -f monitor.sh && ./monitor.sh'                       BLOCK
assert_verdict "bash -c wrapper" \
  'bash -c "pkill -f worker && ./worker"'                     BLOCK
# The other direction matters more than the blocks: a guard that fires on
# ordinary work is one you learn to click past.
assert_verdict "bare local pkill -f stays allowed" \
  'pkill -f uvicorn'                                          ALLOW
assert_verdict "pkill without -f stays allowed" \
  'pkill -9 dotnet'                                           ALLOW
assert_verdict "grepping for a process name is not a kill" \
  'ps aux | grep train.py'                                    ALLOW
assert_verdict "after a semicolon separator" \
  'cd /srv; pkill -f app.py && ./app.py'                      BLOCK
# Regression. The first cut matched `pkill -f` ANYWHERE in the string, so the
# guard refused its own commit message. `pkill` has to sit at a COMMAND
# position — start of string, or after a separator or an opening quote — and
# the grep and the pattern-extracting sed must agree on which characters count
# as that position. They did not: the sed omitted the quote characters, so the
# ssh cases matched the grep, extracted an empty pattern, and fell through to
# allow. A guard that fires on prose is one you learn to click past; a guard
# that matches and then silently extracts nothing protects nothing.
assert_verdict "pkill named inside a commit message" \
  'git commit -m "block the pkill -f shape that kills its launcher"'  ALLOW
assert_verdict "pkill discussed in prose written to a file" \
  'echo "use pkill -f name carefully" >> NOTES.md'            ALLOW

# ─── Force push — read as shell, not as text ─────────────────────────
# The rule was "git push anywhere AND --force/-f anywhere AND main anywhere",
# rewritten with a sed over the whole string. Its rewrites never applied (the
# output was rejected), and replayed over the 41 commands it fired on they
# would have corrupted 23: `--force-with-lease-with-lease`, `--force-with-lease`
# on `git worktree remove` and `rm -f`, `feat/verdict-c--force-with-lease-split`.
section "Force push — only a force token of a git push statement counts"
assert_rewrite "-f on a feature branch" \
  'git push -f origin feat/x'                 'git push --force-with-lease origin feat/x'
assert_rewrite "--force on a feature branch" \
  'git push --force origin feat/x'            'git push --force-with-lease origin feat/x'
assert_rewrite "a short-option cluster carrying f" \
  'git push -uf origin feat/x'                'git push -u --force-with-lease origin feat/x'
assert_rewrite "a +refspec is a force too" \
  'git push origin +feat/x'                   'git push --force-with-lease origin feat/x'
assert_rewrite "git -C <dir> push" \
  'git -C /tmp/r push --force origin feat'    'git -C /tmp/r push --force-with-lease origin feat'
assert_rewrite "only the push statement changes" \
  'git push -f origin feat 2>&1 | tail -3'    'git push --force-with-lease origin feat 2>&1 | tail -3'
assert_verdict "--force-with-lease is already safe (no -with-lease-with-lease)" \
  'git push --force-with-lease origin feat/x'                         ALLOW
assert_verdict "--force-with-lease=<ref>:<sha> is already safe" \
  'git push --force-with-lease=feat/x:93fdca1 origin feat/x'          ALLOW
assert_verdict "--force on git worktree remove is not a push" \
  'git push origin feat/x && git worktree remove --force ../wt'       ALLOW
assert_verdict "-f inside a ref name is not a flag" \
  'git push origin feat/verdict-c-f-split'                            ALLOW
assert_verdict "rm -f beside a push to main is not a force push" \
  'git push origin main && rm -f x.log'                               ALLOW
assert_verdict "push text inside a quoted message" \
  'git commit -m "never git push -f to shared" && git push origin feat/x' ALLOW
assert_verdict "push text inside a heredoc body is data" \
  "cat > n.md <<'EOF'
git push -f origin x
EOF
git status"                                                            ALLOW
assert_verdict "a malformed -f-with-lease is left for git to reject" \
  'git push -q -f-with-lease origin feat/x'                           ALLOW

section "Force push — main and master stay blocked, in every spelling"
assert_verdict "--force to main"            'git push --force origin main'          BLOCK
assert_verdict "+main refspec"              'git push origin +main'                 BLOCK
assert_verdict "HEAD:main destination"      'git push origin HEAD:main --force'     BLOCK
assert_verdict "refs/heads/master"          'git push -f origin refs/heads/master'  BLOCK
assert_verdict "--force-with-lease to main" 'git push --force-with-lease origin main' BLOCK
assert_verdict "deleting main on the remote" 'git push origin :main'                BLOCK
assert_verdict "--delete main"              'git push origin --delete main'         BLOCK
assert_verdict "--all with --force"         'git push --all -f origin'              BLOCK
assert_verdict "inside bash -c"             'bash -c "git push --force origin main"' BLOCK
assert_verdict "inside an ssh one-liner"    'ssh h "cd r && git push -f origin master"' BLOCK
# The & of 2>&1 is a redirection, not a statement separator. Split there and
# the flags after it land in a statement that does not start with git.
assert_verdict "a redirection before the flags does not end the statement" \
  'git push 2>&1 -f origin main'                                       BLOCK
assert_rewrite "a redirection before the flags, feature branch" \
  'git push 2>&1 -f origin feat/x'            'git push 2>&1 --force-with-lease origin feat/x'
assert_verdict "an ordinary push to main is not a force push" \
  'git push origin main'                                               ALLOW

# An adversarial review of the first cut found these allowed: it read a
# statement only when its FIRST word was git, so anything in front — a prefix
# command, a shell keyword, a group — hid the push, and a shell fed its script
# on stdin was never read at all. The old text match had blocked every one.
section "Force push — behind prefixes, groupings and piped shells"
assert_verdict "timeout prefix"             'timeout 120 git push --force origin main'          BLOCK
assert_verdict "sudo -u prefix"             'sudo -u bob git push -f origin main'               BLOCK
assert_verdict "nice -n prefix"             'nice -n 19 git push --force origin master'         BLOCK
assert_verdict "xargs prefix"               'printf x | xargs -I{} git push --force origin main' BLOCK
assert_verdict "brace group"                '{ git push --force origin main; }'                 BLOCK
assert_verdict "if / then"                  'if true; then git push --force origin main; fi'    BLOCK
assert_verdict "for / do"                   'for x in 1; do git push --force origin main; done' BLOCK
assert_verdict "shell function"             'f() { git push --force origin main; }; f'          BLOCK
assert_verdict "echo piped into bash"       'echo "git push --force origin main" | bash'        BLOCK
assert_verdict "printf piped into sh -s"    'printf "git push -f origin main\n" | sh -s'        BLOCK
assert_verdict "heredoc fed to bash" "bash <<'EOF'
git push --force origin main
EOF"                                                                                            BLOCK
assert_verdict "heredoc fed to ssh" "ssh host <<'EOF'
cd repo && git push -f origin master
EOF"                                                                                            BLOCK
assert_verdict "ssh options before the host" 'ssh -i k -p 22 host "git push -f origin main"'   BLOCK
# Options with a value must be skipped as pairs, or `-i key host` reads `key`
# as the host and `host` as a remote command, and the stdin script is missed.
assert_verdict "ssh options, then a heredoc script" "ssh -i key host <<'EOF'
git push --force origin main
EOF"                                                                                            BLOCK
assert_rewrite "a prefix on a feature branch still rewrites" \
  'timeout 120 git push -f origin feat/x'     'timeout 120 git push --force-with-lease origin feat/x'
# And the false positive that review found: a script ARGUMENT is not a command.
assert_verdict "bash script.sh with prose about a push" \
  'bash run.sh "notes about git push --force origin main"'            ALLOW
assert_verdict "a piped shell with nothing to push"  'curl -s https://example.com/i.sh | bash' ALLOW
assert_verdict "ssh with an ordinary remote command" 'ssh host cat notes.md'                   ALLOW

section "Parity — prefixes, groupings and piped shells"
assert_parity "timeout prefix"          'timeout 120 git push --force origin main'
assert_parity "sudo -u prefix"          'sudo -u bob git push -f origin main'
assert_parity "brace group"             '{ git push --force origin main; }'
assert_parity "for / do"                'for x in 1; do git push --force origin main; done'
assert_parity "echo piped into bash"    'echo "git push --force origin main" | bash'
assert_parity "heredoc fed to bash"     "bash <<'EOF'
git push --force origin main
EOF"
assert_parity "ssh options"             'ssh -i k -p 22 host "git push -f origin main"'
assert_parity "prefix rewrite"          'timeout 120 git push -f origin feat/x'
assert_parity "script argument"         'bash run.sh "notes about git push --force origin main"'

# With no refspec, git pushes the CURRENT branch, which the command text does
# not name — so it is read from the session's cwd, unless the command moved.
section "Force push — no refspec means the current branch"
GD_REPO=$(mktemp -d)
git -C "$GD_REPO" init -q -b main >/dev/null 2>&1 || { git -C "$GD_REPO" init -q >/dev/null 2>&1; git -C "$GD_REPO" symbolic-ref HEAD refs/heads/main; }
assert_verdict "git push -f on main"                 'git push -f'                     BLOCK "$GD_REPO"
assert_verdict "git push --force origin on main"     'git push --force origin'         BLOCK "$GD_REPO"
assert_verdict "after a cd the branch is unknown"    'cd /tmp/elsewhere && git push -f' REWRITE "$GD_REPO"
# HEAD and @ name the current branch too — neither guardian caught this before.
assert_verdict "HEAD as the destination, on main"    'git push -f origin HEAD'         BLOCK "$GD_REPO"
assert_verdict "@ as the destination, on main"       'git push --force origin @'       BLOCK "$GD_REPO"
TESTS_RUN=$((TESTS_RUN + 1))
if [[ "$(py_verdict 'git push -f origin HEAD' "$GD_REPO")" == "BLOCK" ]]; then
  TESTS_PASSED=$((TESTS_PASSED + 1)); printf "  ${GREEN}✓${NC} parity: the Codex mirror reads HEAD as the current branch\n"
else
  TESTS_FAILED=$((TESTS_FAILED + 1)); printf "  ${RED}✗${NC} parity: the Codex mirror reads HEAD as the current branch\n"
fi
git -C "$GD_REPO" symbolic-ref HEAD refs/heads/feat/x
assert_rewrite "git push -f on a feature branch" 'git push -f' 'git push --force-with-lease' "$GD_REPO"
assert_rewrite "HEAD on a feature branch is rewritten, not blocked" \
  'git push -f origin HEAD' 'git push --force-with-lease origin HEAD' "$GD_REPO"
rm -rf "$GD_REPO"

# ─── The rewrite keeps the rest of the call ──────────────────────────
# updatedInput REPLACES tool_input, so a rewrite that sent only {command}
# would drop the call's timeout and run_in_background.
section "A rewrite carries the rest of tool_input"
run_sh 'git push -f origin feat/x'
TESTS_RUN=$((TESTS_RUN + 1))
if [[ "$(jq -r '.hookSpecificOutput.updatedInput.timeout // empty' <<< "$RUN_OUT" 2>/dev/null)" == "5000" \
   && "$(jq -r '.hookSpecificOutput.updatedInput.description // empty' <<< "$RUN_OUT" 2>/dev/null)" == "d" ]]; then
  TESTS_PASSED=$((TESTS_PASSED + 1)); printf "  ${GREEN}✓${NC} timeout and description survive the rewrite\n"
else
  TESTS_FAILED=$((TESTS_FAILED + 1)); printf "  ${RED}✗${NC} timeout and description survive the rewrite\n      output: %s\n" "$RUN_OUT"
fi

# ─── A crash is not an allow ─────────────────────────────────────────
# Reproductions from transcripts (2026-10-06 → 10-17): each exited 1 inside
# rm_scan_flags under `set -e`, a non-blocking error to Claude Code, which ran
# the command with every later check skipped. classify() now reads a non-zero
# exit as CRASH, so these would have failed even as ALLOW cases.
section "Commands that used to crash the guardian"
assert_verdict "grep for 'rm -' then a pipe" \
  'cd /x && grep -n "rm \|rm -\|trap" a.sh | head; git diff A HEAD -- a.sh' ALLOW
assert_verdict "grep for 'rm -' with other words" \
  'grep -n "next\|rm -\|reset" README.md | head -40; git --version'       ALLOW
assert_verdict "a quoted rm- pattern after a worktree remove" \
  'git -C /p worktree remove --force /p/wt; systemctl --user list-units | grep -E "rm-"' ALLOW
assert_verdict "a crash shape followed by a real force push to main" \
  'grep -n "rm -\|x" a.sh | head; git push --force origin main'           BLOCK

section "Parity — force push, read the same way by both guardians"
assert_parity "-f on a feature branch"        'git push -f origin feat/x'
assert_parity "short-option cluster"          'git push -uf origin feat/x'
assert_parity "+refspec"                      'git push origin +feat/x'
assert_parity "git -C"                        'git -C /tmp/r push --force origin feat'
assert_parity "lease is untouched"            'git push --force-with-lease origin feat/x'
assert_parity "worktree remove --force"       'git push origin feat/x && git worktree remove --force ../wt'
assert_parity "-f inside a ref name"          'git push origin feat/verdict-c-f-split'
assert_parity "rm -f beside a push to main"   'git push origin main && rm -f x.log'
assert_parity "quoted message"                'git commit -m "never git push -f to shared" && git push origin feat/x'
assert_parity "heredoc body"                  "cat > n.md <<'EOF'
git push -f origin x
EOF
git status"
assert_parity "HEAD:main"                     'git push origin HEAD:main --force'
assert_parity "+main"                         'git push origin +main'
assert_parity "deleting main"                 'git push origin :main'
assert_parity "bash -c"                       'bash -c "git push --force origin main"'
assert_parity "malformed -f-with-lease"       'git push -q -f-with-lease origin feat/x'

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
