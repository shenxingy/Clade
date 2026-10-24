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
#   WARN               additionalContext alone: the command runs unchanged
#   WARN-DECIDES       a warning that also carries a permissionDecision — an
#                      "allow" there would skip the permission prompt, which a
#                      warning has no business doing
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
      elif (($h.additionalContext // "") != "") then
        (if ($h | has("permissionDecision")) then "WARN-DECIDES" else "WARN" end)
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

# finish — the summary line and the suite's exit status
finish() {
  printf "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
  if [[ "$TESTS_FAILED" -eq 0 ]]; then
    printf "  ${GREEN}ALL PASSED${NC} (%d/%d)\n" "$TESTS_PASSED" "$TESTS_RUN"
  else
    printf "  ${RED}FAILED${NC} (%d/%d passed, %d failed)\n" \
      "$TESTS_PASSED" "$TESTS_RUN" "$TESTS_FAILED"
  fi
  printf "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
  [[ "$TESTS_FAILED" -eq 0 ]]
  exit $?
}

# ─── Subagent waits that outlive the prompt cache ────────────────────
#
# A different kind of rule from everything else in this file: it never blocks.
# Inside a subagent (the hook input carries agent_id), a foreground wait that
# can outlast the subagent prompt cache (5 minutes by default) gets a warning
# attached and runs unchanged. Measured 2026-10-22 over the Workflow runs on
# the author's machine: 82.5% of the cost of cache misses after a gap over
# 300 s followed a Bash sleep, poll or wait, typically `until …; do sleep N;
# done`.
#
# Defined here and run at the end; GUARDIAN_WAITS_ONLY=1 runs only this block.
# orchestrator/tests/test_self_tests_can_fire.py does that against a mutated
# copy of the hook, once per guard it lists, and requires each to turn the
# block red; it sets GUARDIAN_FAIL_FAST=1, which stops at the first red case.

# wpayload <command> <timeout-ms|-> <agent-id|-> [bg] — hook input as Claude
# Code sends it; "-" leaves the field out. Built with jq, not python, because
# the mutation harness runs this block once per mutation.
wpayload() {
  jq -nc --arg c "$1" --arg t "$2" --arg a "$3" --arg bg "${4:-}" --arg cwd "$NOREPO_CWD" '
    {tool_name: "Bash", cwd: $cwd,
     tool_input: ({command: $c, description: "d"}
       + (if $t == "-" then {} else {timeout: ($t | tonumber)} end)
       + (if $bg == "bg" then {run_in_background: true} else {} end))}
    + (if $a == "-" then {} else {agent_id: $a} end)'
}
# w_run — feed it to the hook with the Bash timeout and prompt-cache TTL
# variables cleared, so the result does not depend on the environment the
# suite runs in. WAIT_ENV adds NAME=VALUE pairs back for the cases that test
# them.
WAIT_ENV=""
w_run() {
  # shellcheck disable=SC2086  # WAIT_ENV is a list of NAME=VALUE words
  RUN_OUT=$(wpayload "$@" | env -u BASH_DEFAULT_TIMEOUT_MS -u BASH_MAX_TIMEOUT_MS \
    -u FORCE_PROMPT_CACHING_5M -u CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL \
    -u CLAUDE_CODE_PROMPT_CACHE_TTL -u ENABLE_PROMPT_CACHING_1H \
    -u ENABLE_PROMPT_CACHING_1H_BEDROCK -u CLAUDE_CODE_USE_BEDROCK \
    $WAIT_ENV bash "$HOOK" 2>/dev/null)
  RUN_RC=$?
}
# w_failed — count a failure; under GUARDIAN_FAIL_FAST stop at the first one.
# The mutation harness sets it: it needs one red case, not the whole list.
w_failed() {
  TESTS_FAILED=$((TESTS_FAILED + 1))
  [[ -n "${GUARDIAN_FAIL_FAST:-}" ]] && finish
  return 0
}
WAIT_CTX() { jq -r '.hookSpecificOutput.additionalContext // empty' <<< "$RUN_OUT" 2>/dev/null; }

# assert_wait <label> <command> <want> <timeout-ms|-> <agent-id|-> [bg]
assert_wait() {
  local label="$1" cmd="$2" want="$3" got
  TESTS_RUN=$((TESTS_RUN + 1))
  w_run "$cmd" "$4" "$5" "${6:-}"
  got=$(classify "$RUN_OUT" "$RUN_RC" claude)
  # A WARN must be THIS warning, not some other note.
  [[ "$got" == WARN && "$(WAIT_CTX)" != *"subagent call can block"* ]] && got="WARN-OTHER"
  if [[ "$got" == "$want" ]]; then
    TESTS_PASSED=$((TESTS_PASSED + 1))
    printf "  ${GREEN}✓${NC} %s\n" "$label"
  else
    printf "  ${RED}✗${NC} %s (got=%s want=%s)\n      cmd: %s\n" "$label" "$got" "$want" "$cmd"
    w_failed
  fi
  return 0
}

# assert_wait_says <label> <command> <timeout-ms> <substring>... — the warning
# names what it found and what to do instead. A substring written "!text"
# must NOT appear.
assert_wait_says() {
  local label="$1" cmd="$2" t="$3" ctx s ok=1
  shift 3
  TESTS_RUN=$((TESTS_RUN + 1))
  w_run "$cmd" "$t" a1b2c3
  ctx=$(WAIT_CTX)
  [[ -n "$ctx" ]] || ok=0
  for s in "$@"; do
    if [[ "$s" == '!'* ]]; then [[ "$ctx" != *"${s#!}"* ]] || ok=0
    else [[ "$ctx" == *"$s"* ]] || ok=0; fi
  done
  if [[ "$ok" == 1 ]]; then
    TESTS_PASSED=$((TESTS_PASSED + 1))
    printf "  ${GREEN}✓${NC} %s\n" "$label"
  else
    printf "  ${RED}✗${NC} %s\n      cmd:  %s\n      want: %s\n      got:  %s\n" "$label" "$cmd" "$*" "$ctx"
    w_failed
  fi
  return 0
}

wait_cases() {
  local T=600000 A=a1b2c3

  section "Subagent waits — warned when they can outlive the 5-minute cache"
  assert_wait "until loop around sleep"         'until grep -q DONE /tmp/run.log; do sleep 30; done' WARN $T $A
  assert_wait "while loop around sleep"         'while ! test -s out.json; do sleep 20; done; cat out.json' WARN $T $A
  assert_wait "sleep 600"                       'sleep 600'                                       WARN $T $A
  assert_wait "sleep 5m (GNU suffix)"           'sleep 5m'                                        WARN $T $A
  assert_wait "sleep 1h"                        'sleep 1h; date'                                  WARN $T $A
  assert_wait "sleep infinity"                  'sleep infinity'                                  WARN $T $A
  assert_wait "sleep sums its arguments"        'sleep 4m 40s'                                    WARN $T $A
  assert_wait "short sleeps add up across statements" 'sleep 200; date; sleep 200'                WARN $T $A
  assert_wait "a sleep that is not first in the command" 'date -u && sleep 400 && tail -3 run.log' WARN $T $A
  assert_wait "timeout 590 around a bash -c poll (the audit's top shape)" \
    'timeout 590 bash -c "until ! systemctl --user is-active -q job; do sleep 10; done"'          WARN $T $A
  assert_wait "timeout 590 around bash -c sleep"  "timeout 590 bash -c 'sleep 580'; tail -1 log"  WARN $T $A
  assert_wait "for loop over \$(seq 1 19) x sleep 30" \
    'for i in $(seq 1 19); do grep -q done f && break; sleep 30; done'                           WARN $T $A
  assert_wait "for loop over {1..19}"           'for i in {1..19}; do sleep 30; done'             WARN $T $A
  assert_wait "poll run on another host over ssh" \
    'ssh -o BatchMode=yes host "until [ -f /tmp/x.rc ]; do sleep 30; done; cat /tmp/x.rc"'       WARN $T $A
  assert_wait "poll fed to bash as a heredoc" "bash <<'EOF'
until [ -f /tmp/x.rc ]; do sleep 30; done
EOF"                                                                                              WARN $T $A
  assert_wait "wait on a backgrounded sleep"    'sleep 600 & wait'                                WARN $T $A
  assert_wait "wait on a backgrounded poll group" \
    '( until [ -f x ]; do sleep 5; done ) & wait'                                                WARN $T $A
  assert_wait "tail -f into grep -m1"           'tail -f run.log | grep -m1 DONE'                 WARN $T $A
  assert_wait "a wait inside \$( … )"           'x=$(timeout 600 tail -F run.log | grep -m1 DONE)' WARN $T $A
  assert_wait "kubectl wait --timeout=600s"     'kubectl wait --for=condition=ready pod/x --timeout=600s' WARN $T $A
  assert_wait "inotifywait -t 600"              'inotifywait -t 600 -e create /tmp/out'           WARN $T $A
  assert_wait "gh run watch"                    'gh run watch 12345 --exit-status'                WARN $T $A
  assert_wait "python -c time.sleep (sleep spelled past the built-in block)" \
    'timeout 590 python3 -c "import time; time.sleep(575)"; tail -2 run.log'                     WARN $T $A
  assert_wait "python -c while loop around time.sleep" "python3 -B -c \"
import os, time
while not os.path.exists('x.rc'): time.sleep(20)
\""                                                                                               WARN $T $A
  assert_wait "watch"                           'watch -n 5 nvidia-smi'                           WARN $T $A
  assert_wait "pidwait"                         'pidwait -f trainer.py'                           WARN $T $A
  assert_wait "docker wait"                     'docker wait trainer'                             WARN $T $A
  assert_wait "gh pr checks --watch"            'gh pr checks 12 --watch'                         WARN $T $A
  assert_wait "kubectl wait --timeout given as a separate word" \
    'kubectl wait --for=delete pod/x --timeout 600s'                                             WARN $T $A
  assert_wait "kubectl wait with a negative --timeout waits without end" \
    'kubectl wait --for=condition=complete job/x --timeout=-1s'                                  WARN $T $A
  assert_wait "inotifywait with no timeout"     'inotifywait -e create /tmp/out'                  WARN $T $A
  assert_wait "tail --follow=name"              'tail --follow=name run.log | grep -m1 DONE'      WARN $T $A
  assert_wait "a poll run through eval"         'eval "until [ -f x ]; do sleep 5; done"'         WARN $T $A
  assert_wait "sudo, skipping the value of -u"  'sudo -u svc sleep 600'                           WARN $T $A
  assert_wait "nice, skipping the value of -n"  'nice -n 5 sleep 600'                             WARN $T $A
  assert_wait "env, skipping an assignment"     'env FOO=1 sleep 600'                             WARN $T $A
  assert_wait "nohup in the foreground"         'nohup sleep 600'                                 WARN $T $A
  assert_wait "command"                         'command sleep 600'                               WARN $T $A
  assert_wait "stdbuf, skipping the value of -o" 'stdbuf -o L sleep 600'                          WARN $T $A
  assert_wait "ionice, skipping the value of -c" 'ionice -c 3 sleep 600'                          WARN $T $A
  assert_wait "exec, skipping the value of -a"  'exec -a waiter sleep 600'                        WARN $T $A
  assert_wait "an assignment before the command" 'CI=1 sleep 600'                                 WARN $T $A
  assert_wait "bash -lc (combined flags)"       "bash -lc 'until [ -f x ]; do sleep 5; done'"     WARN $T $A
  assert_wait "bash -o pipefail -c"             "bash -o pipefail -c 'until [ -f x ]; do sleep 5; done'" WARN $T $A
  assert_wait "timeout -s KILL, skipping the signal" \
    "timeout -s KILL 590 bash -c 'until [ -f x ]; do sleep 5; done'"                             WARN $T $A
  assert_wait "a poll fed to ssh as a heredoc"  "ssh host <<'EOF'
until [ -f /tmp/x.rc ]; do sleep 30; done
EOF"                                                                                              WARN $T $A
  assert_wait "a comment with a quote in it is skipped" "# don't wait forever
until test -f x; do sleep 5; done"                                                                WARN $T $A
  assert_wait "a # inside a word is not a comment" 'echo a#b; sleep 600'                          WARN $T $A
  assert_wait "wait on a backgrounded { …; } group" '{ until [ -f x ]; do sleep 5; done; } & wait' WARN $T $A
  assert_wait "a <<- heredoc ends at its tab-indented delimiter" "$(printf 'cat > note.txt <<-EOF\n\thello\n\tEOF\nsleep 600')" WARN $T $A
  assert_wait "sleep stops at a redirect"       'sleep 600 >/dev/null; date'                      WARN $T $A
  assert_wait "sleep stops at &>"               'sleep 600 &>/dev/null'                           WARN $T $A
  assert_wait "2>&1 is a redirect, not a background job" \
    'until [ -f x ]; do sleep 5; done 2>&1 | tail -1'                                            WARN $T $A
  assert_wait "&> is a redirect, not a background job" \
    'until [ -f x ]; do sleep 5; done &>/dev/null'                                               WARN $T $A
  assert_wait "( … ) && is not a background job" '( until [ -f x ]; do sleep 5; done ) && echo ready' WARN $T $A
  assert_wait "( … ) &> is not a background job" '( until [ -f x ]; do sleep 5; done ) &> poll.log'   WARN $T $A
  assert_wait "sleep 1d"                        'sleep 1d'                                        WARN $T $A
  assert_wait "for loop over a word list (10 x 30 s)" 'for h in a b c d e f g h i j; do sleep 30; done' WARN $T $A
  # A here-string once sent its second < into the heredoc branch, which took
  # the next word's opening quote and misread every later quote. 7 long polls
  # in the replayed corpus (6 on gh pr checks) went unseen that way.
  assert_wait "a poll with a here-string in it" "$(cat <<'CMD'
for i in $(seq 1 19); do s=$(gh pr checks 12 --json name,bucket); g=$(jq -r '.[] | select(.name=="gate") | .bucket' <<<"$s"); [ "$g" != pending ] && break; sleep 30; done
CMD
)"                                                                                                WARN $T $A
  assert_wait "a poll with a spaced here-string in it" "$(cat <<'CMD'
for i in $(seq 1 40); do s=$(ssh h "systemctl --user is-active job"); read -r a <<< "$s"; [ "$a" != active ] && break; sleep 45; done
CMD
)"                                                                                                WARN $T $A

  section "Subagent waits — silent when they cannot outlive it"
  assert_wait "sleep 60"                        'sleep 60; tail -3 run.log'                       ALLOW $T $A
  assert_wait "sleep 270 is the limit, not over it" 'sleep 270'                                   ALLOW $T $A
  assert_wait "sleep 4m"                        'sleep 4m'                                        ALLOW $T $A
  # A timeout prefix bounds what it wraps (GNU and busybox; macOS has none).
  assert_wait "a timeout 260 slice around a poll" \
    "timeout 260 bash -c 'until grep -q DONE run.log; do sleep 10; done'; tail -3 run.log"       ALLOW $T $A
  assert_wait "timeout 120 around tail -f"      'timeout 120 tail -f run.log | grep -m1 DONE'     ALLOW $T $A
  assert_wait "for loop of 5 x sleep 30 (150 s)" 'for i in $(seq 1 5); do sleep 30; done'         ALLOW $T $A
  assert_wait "for loop with an unknown count"  'for f in *.log; do gzip "$f"; sleep 1; done'     ALLOW $T $A
  assert_wait "kubectl wait defaults to 30 s"   'kubectl wait --for=condition=ready pod/x'        ALLOW $T $A
  assert_wait "kubectl wait --timeout=120s"     'kubectl wait --for=condition=ready pod/x --timeout=120s' ALLOW $T $A
  assert_wait "inotifywait -t 60"               'inotifywait -t 60 -e create /tmp/out'            ALLOW $T $A
  assert_wait "a detached sleep that nothing waits for" 'sleep 600 &'                             ALLOW $T $A
  assert_wait "a detached poll group"           '( until [ -f x ]; do sleep 5; done ) &'          ALLOW $T $A
  assert_wait "a detached nohup poll"           "nohup bash -c 'until [ -f x ]; do sleep 5; done' > poll.log 2>&1 &" ALLOW $T $A
  # 5 of 103 bare `wait` calls in the measured corpus ran past 270 s.
  assert_wait "a bare wait on ordinary work"    'pytest -q tests/a & pytest -q tests/b & wait'    ALLOW $T $A
  assert_wait "a while loop with no sleep"      'while read -r l; do echo "$l"; done < list.txt'  ALLOW $T $A
  assert_wait "a loop described in a commit message" \
    'git commit -m "poll with until x; do sleep 600; done"'                                     ALLOW $T $A
  assert_wait "a sleep described in a commit message" \
    'git commit -m "retry once; sleep 400; then give up"'                                       ALLOW $T $A
  assert_wait "a loop written to a script file is data" "cat > poll.sh <<'EOF'
until [ -f x ]; do sleep 30; done
EOF
chmod +x poll.sh"                                                                                 ALLOW $T $A
  assert_wait "sleep named inside a string"     'echo "sleep 600"'                                ALLOW $T $A
  assert_wait "python -c time.sleep(60)"        'python3 -c "import time; time.sleep(60)"'        ALLOW $T $A
  assert_wait "long work is not a wait"         'pytest -q tests/'                                ALLOW $T $A
  assert_wait "the recommended bounded loop: 26 x sleep 10" \
    'for i in $(seq 1 26); do test -f x && break; sleep 10; done'                                ALLOW $T $A
  assert_wait "a { …; } group sent to the background" '{ until [ -f x ]; do sleep 5; done; } &'   ALLOW $T $A
  assert_wait "for loop with a glob word: count unknown" 'for f in a.log *.log; do sleep 200; done' ALLOW $T $A
  assert_wait "for loop with a sleep of unknown length" \
    'for i in $(seq 1 100); do sleep "$D"; sleep 3; done'                                        ALLOW $T $A
  assert_wait "kubectl wait --timeout it cannot read is not counted" \
    'kubectl wait --for=condition=ready pod/x --timeout=1m30s'                                   ALLOW $T $A
  assert_wait "kubectl wait --timeout=0 checks once" 'kubectl wait --for=condition=ready pod/x --timeout=0' ALLOW $T $A
  assert_wait "inotifywait --timeout=60"        'inotifywait --timeout=60 -e create /tmp/out'     ALLOW $T $A
  assert_wait "a here-string is not a heredoc"  'read -r a <<< "$(date)"; sleep 5'                ALLOW $T $A

  section "Subagent waits — the gates"
  assert_wait "no agent_id: the main thread is never warned" \
    'until grep -q DONE /tmp/run.log; do sleep 30; done'                                         ALLOW $T -
  assert_wait "no agent_id: sleep 600"          'sleep 600'                                       ALLOW $T -
  assert_wait "an empty agent_id is no agent"   'sleep 600'                                       ALLOW $T ""
  assert_wait "run_in_background blocks nothing" \
    'until grep -q DONE /tmp/run.log; do sleep 30; done'                                         ALLOW $T $A bg
  assert_wait "no timeout: Claude Code stops it at 120 s" \
    'until grep -q DONE /tmp/run.log; do sleep 30; done'                                         ALLOW - $A
  assert_wait "timeout 270000 cannot outlive it" 'sleep 600'                                      ALLOW 270000 $A
  assert_wait "timeout 0 means the default, as in Claude Code" 'sleep 600'                         ALLOW 0 $A
  assert_wait "timeout 300000 can"              'sleep 600'                                       WARN 300000 $A
  assert_wait_says "the call's timeout bounds an unbounded poll" \
    'until grep -q DONE /tmp/run.log; do sleep 30; done' 300000 "up to 300 s"
  assert_wait_says "a timeout over the 600 s ceiling is clamped to it" \
    'until grep -q DONE /tmp/run.log; do sleep 30; done' 3600000 "up to 600 s"
  WAIT_ENV="BASH_DEFAULT_TIMEOUT_MS=900000"
  assert_wait_says "BASH_DEFAULT_TIMEOUT_MS applies when the call sets none" \
    'until grep -q DONE /tmp/run.log; do sleep 30; done' - "up to 900 s"
  WAIT_ENV="BASH_MAX_TIMEOUT_MS=3600000"
  assert_wait_says "BASH_MAX_TIMEOUT_MS raises the ceiling" \
    'until grep -q DONE /tmp/run.log; do sleep 30; done' 3600000 "up to 3600 s"
  WAIT_ENV=""

  section "Subagent waits — silent when the environment gives subagents the 1-hour cache"
  WAIT_ENV="CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL=1h"
  assert_wait "CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL=1h" 'sleep 600'                              ALLOW $T $A
  WAIT_ENV="CLAUDE_CODE_PROMPT_CACHE_TTL=1h"
  assert_wait "CLAUDE_CODE_PROMPT_CACHE_TTL is the main thread's, not a subagent's" 'sleep 600'   WARN $T $A
  WAIT_ENV="ENABLE_PROMPT_CACHING_1H=1"
  assert_wait "ENABLE_PROMPT_CACHING_1H=1"      'sleep 600'                                       ALLOW $T $A
  WAIT_ENV="ENABLE_PROMPT_CACHING_1H=TRUE"
  assert_wait "ENABLE_PROMPT_CACHING_1H=TRUE, read in any case" 'sleep 600'                       ALLOW $T $A
  WAIT_ENV="ENABLE_PROMPT_CACHING_1H=0"
  assert_wait "ENABLE_PROMPT_CACHING_1H=0 is off" 'sleep 600'                                     WARN $T $A
  WAIT_ENV="ENABLE_PROMPT_CACHING_1H=1 CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL=5m"
  assert_wait "the subagent TTL variable outranks ENABLE_PROMPT_CACHING_1H" 'sleep 600'           WARN $T $A
  WAIT_ENV="FORCE_PROMPT_CACHING_5M=1 CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL=1h"
  assert_wait "FORCE_PROMPT_CACHING_5M outranks the TTL variable" 'sleep 600'                     WARN $T $A
  WAIT_ENV="CLAUDE_CODE_USE_BEDROCK=1 ENABLE_PROMPT_CACHING_1H_BEDROCK=1"
  assert_wait "ENABLE_PROMPT_CACHING_1H_BEDROCK on Bedrock" 'sleep 600'                           ALLOW $T $A
  WAIT_ENV="ENABLE_PROMPT_CACHING_1H_BEDROCK=1"
  assert_wait "ENABLE_PROMPT_CACHING_1H_BEDROCK off Bedrock does nothing" 'sleep 600'             WARN $T $A
  WAIT_ENV=""

  section "Subagent waits — what the warning says"
  # run_in_background is not the remedy: Claude Code 2.1.283 terminates a
  # synchronous subagent's background jobs at its final response. And no
  # `timeout 260` example: macOS has no `timeout`.
  assert_wait_says "it names the shape, the bound and both remedies" \
    'until grep -q DONE /tmp/run.log; do sleep 30; done' $T \
    "up to 600 s" "until/while loop around sleep 30" "By default" "270 s or less" \
    'for i in $(seq 1 26); do <check> && break; sleep 10; done' "timeout of 270000 or less" \
    "nohup <job> > <log> 2>&1 &" "run_in_background is no detach" \
    "!start the job with run_in_background" "!timeout 260"
  # The loop it recommends, taken from the warning itself, must be silent, so
  # the advice and the rule cannot drift apart.
  w_run 'sleep 600' $T $A
  _slice=$(WAIT_CTX | sed -n 's/.*bound the loop (\(.*\)), or give.*/\1/p')
  _slice=${_slice//<check>/test -f x}
  assert_wait "the loop the warning recommends is itself silent" "${_slice:-sleep 600}" ALLOW $T $A
  assert_wait_says "a for loop is count x sleep" \
    'for i in $(seq 1 19); do sleep 30; done' $T "up to 570 s" "a for loop of 19 x sleep 30"
  assert_wait_says "several short sleeps are summed" 'sleep 200; sleep 200' $T "up to 400 s"

  section "Subagent waits — never a block, never a lost verdict"
  assert_wait "a deny still wins"               'git push --force origin main; sleep 600'         BLOCK $T $A
  assert_wait "a rewrite still rewrites"        'rm -rf $BUILD_DIR/ && until [ -f x ]; do sleep 30; done' REWRITE $T $A
  assert_wait_says "and the rewrite carries the wait warning" \
    'rm -rf $BUILD_DIR/ && until [ -f x ]; do sleep 30; done' $T "subagent call can block"
  # Kimi reads only a deny; a warning must reach it as an allow, not a block.
  TESTS_RUN=$((TESTS_RUN + 1))
  _kimi=$(wpayload 'sleep 600' $T $A | bash "$REPO_ROOT/configs/kimi-hooks/decision-to-kimi.sh" "$HOOK" 2>/dev/null)
  if [[ -z "$_kimi" ]]; then
    TESTS_PASSED=$((TESTS_PASSED + 1)); printf "  ${GREEN}✓${NC} the Kimi shim passes a warning through as an allow\n"
  else
    printf "  ${RED}✗${NC} the Kimi shim passes a warning through as an allow\n      got: %s\n" "$_kimi"; w_failed
  fi
  # Not mirrored, on purpose: agent_id and the 5-minute subagent TTL are Claude
  # Code facts. Pinned so the divergence is visible, not discovered.
  # Empty output is the pass condition, so a missing python3 would pass it.
  if ! command -v python3 >/dev/null 2>&1; then
    printf "  ${YELLOW}-${NC} the Codex mirror case: SKIPPED, python3 not installed\n"
    return 0
  fi
  TESTS_RUN=$((TESTS_RUN + 1))
  _py=$(wpayload 'sleep 600' $T $A | python3 "$PY_HOOK" 2>/dev/null)
  if [[ -z "$_py" ]]; then
    TESTS_PASSED=$((TESTS_PASSED + 1)); printf "  ${GREEN}✓${NC} the Codex mirror does not carry this rule (known divergence)\n"
  else
    printf "  ${RED}✗${NC} the Codex mirror does not carry this rule (known divergence)\n      got: %s\n" "$_py"; w_failed
  fi
}

if [[ -n "${GUARDIAN_WAITS_ONLY:-}" ]]; then
  wait_cases
  finish
fi

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

wait_cases

# ─── Summary ─────────────────────────────────────────────────────────
finish
