#!/usr/bin/env bash
# test-wf-reader-guard.sh — Tests for configs/hooks/wf-reader-guard.sh
#   (PreToolUse Bash, wired in the frontmatter of configs/agents/wf-reader.md:
#    the agent's Bash runs a read allowlist and nothing else)
#
# Pipes fixture hook-input JSON through the hook and asserts the verdict.
# Nothing is executed except the hook itself: the commands are inert text.
#
# Both directions are asserted. A guard that denies everything passes every
# deny case, so the allow cases are what prove it is usable; a guard that
# allows everything passes every allow case, so the deny cases — each a real
# write, launch or escape — are what prove it guards. Every case added on
# 2026-10-23 was shown red against a guard with the matching check removed;
# those removals live in orchestrator/tests/test_self_tests_can_fire.py.
#
# Needs bash and jq, nothing else, so it also runs under the bash:3.2 image
# with a jq mounted in (the shipped hooks target bash 3.2).
#
# Usage:
#   bash tests/test-wf-reader-guard.sh        # Run all tests
#   bash tests/test-wf-reader-guard.sh -v     # Verbose mode
#   WF_READER_GUARD=/path/copy.sh bash tests/test-wf-reader-guard.sh
#   WF_READER_GUARD_FAIL_FAST=1 …             # stop at the first red case

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK="${WF_READER_GUARD:-$REPO_ROOT/configs/hooks/wf-reader-guard.sh}"
AGENT="$REPO_ROOT/configs/agents/wf-reader.md"
FAIL_FAST="${WF_READER_GUARD_FAIL_FAST:-}"
BASH_BIN="${BASH:-bash}"

# ─── Test framework (mirrors tests/test-pre-tool-guardian.sh) ────────
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
VERBOSE="${1:-}"

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[0;33m'; NC='\033[0m'

section() { printf "\n${YELLOW}━━━ %s ━━━${NC}\n" "$1"; }
pass() {
  TESTS_RUN=$((TESTS_RUN + 1)); TESTS_PASSED=$((TESTS_PASSED + 1))
  [[ "$VERBOSE" == "-v" ]] && printf "  ${GREEN}✓${NC} %s\n" "$1"
  return 0
}
fail() {
  TESTS_RUN=$((TESTS_RUN + 1)); TESTS_FAILED=$((TESTS_FAILED + 1))
  printf "  ${RED}✗${NC} %s\n" "$1"
  [[ -n "${2:-}" ]] && printf "      %s\n" "$2"
  if [[ -n "$FAIL_FAST" ]]; then exit 1; fi
  return 0
}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

command -v jq >/dev/null 2>&1 || { echo "test-wf-reader-guard: jq is required" >&2; exit 1; }
[[ -f "$HOOK" ]] || { echo "test-wf-reader-guard: no hook at $HOOK" >&2; exit 1; }

# payload <command> → the hook input Claude Code sends for a Bash call
payload() {
  jq -cn --arg c "$1" '{tool_name:"Bash",tool_input:{command:$c,description:"d"},agent_id:"a1",agent_type:"wf-reader"}'
}

# classify <output> <rc> → ALLOW | DENY | CRASH | MALFORMED, read against the
# schema the runtime accepts, not against substrings. An empty output with a
# non-zero exit is a CRASH: Claude Code would run the command unchecked
# (unless the frontmatter's `|| exit 2` catches it — tested separately below).
classify() {
  local out="$1" rc="$2"
  if [[ "$rc" != 0 ]]; then echo "CRASH"; return; fi
  if [[ -z "${out//[[:space:]]/}" ]]; then echo "ALLOW"; return; fi
  printf '%s' "$out" | jq -r '
    if type != "object" then "MALFORMED"
    elif has("decision") or has("reason") then "MALFORMED"
    else (.hookSpecificOutput // {}) as $h
      | if $h.hookEventName == "PreToolUse" and $h.permissionDecision == "deny"
           and ($h.permissionDecisionReason | type) == "string"
           and ($h.permissionDecisionReason | length) > 0
        then "DENY" else "MALFORMED" end
    end' 2>/dev/null || echo "MALFORMED"
}

# verdict_of <hook-input-json> → the classified verdict; LAST_OUT keeps the output
LAST_OUT=""
verdict_of() {
  local rc
  LAST_OUT=$(printf '%s' "$1" | "$BASH_BIN" "$HOOK" 2>/dev/null)
  rc=$?
  classify "$LAST_OUT" "$rc"
}

expect() {  # expect <ALLOW|DENY> <command> [label]
  local want="$1" cmd="$2" label="${3:-$2}" got
  got=$(verdict_of "$(payload "$cmd")")
  if [[ "$got" == "$want" ]]; then
    pass "$want: $label"
  else
    fail "$want: $label" "got $got — output: ${LAST_OUT:0:300}"
  fi
}
allow() { expect ALLOW "$@"; }
deny() { expect DENY "$@"; }

# ─── 1. Reads that must run ──────────────────────────────────────────
section "allowed reads"

allow 'cat README.md'
allow 'head -n 40 configs/hooks/wf-reader-guard.sh'
allow 'tail -n 5 CHANGELOG.md'
allow "sed -n '1,40p' install.sh"
allow 'sed -n 5p install.sh'
allow "sed -n '\$p' install.sh" "sed -n '\$p' (last line)"
allow "sed -n '10,+5p;20q' install.sh" "sed -n with N,+M and q"
allow "sed -ne '1,3p' install.sh" "sed -ne (the -e ends the cluster)"
allow "sed -n -e '1p' -e '9p' install.sh" "sed -n -e … -e …"
allow "sed -n -- '1p' install.sh" "sed -n -- with a print script"
allow 'grep -rn "wf-reader" configs/agents'
allow "grep -n 'a;b|c > d && e' file.txt" "quoted ; | > && are text, not syntax"
allow "grep -n 'foo\$' file.txt" "a \$ inside single quotes"
allow 'grep -n "end$" file.txt' "a trailing \$ inside double quotes"
allow 'grep -c x a.txt b.txt 2>/dev/null' "grep with 2>/dev/null"
allow 'grep -rn --file=patterns.txt -- --filter src' "grep --file and a pattern after --"
allow 'rg -n "TODO" configs/scripts'
allow "find . -name '*.py' -type f -newer README.md" "find with a quoted glob"
allow 'ls -la configs/hooks/*.sh' "ls with an unquoted glob"
allow 'wc -l configs/hooks/*.sh' "wc with an unquoted glob"
allow 'sort -u names.txt | uniq -c | sort -rn | head -20'
allow 'uniq -f 2 names.txt' "uniq -f N with one file"
allow 'cut -d: -f1 /etc/passwd | tr a-z A-Z'
allow 'tr -d x < input.txt' "input redirection"
allow 'stat README.md && file README.md'
allow 'jq -r ".facts[].name" docs/facts.json'
allow 'diff configs/agents/wf-reader.md agents/wf-reader.md'
allow 'echo ---; pwd; cd configs && ls'
allow 'git log --oneline -5'
allow 'git --no-pager -C configs log -1 --format=%H' "git --no-pager -C <dir>"
allow 'git show HEAD:README.md | head -3'
allow 'git diff HEAD~1 -- configs/hooks'
allow 'git diff --output-indicator-new=+ HEAD' "git diff --output-indicator-* is not --output"
allow 'git status --porcelain'
allow 'git rev-parse --show-toplevel'
allow 'git ls-files configs/agents'
allow 'git grep -n wf-reader'
allow 'git blame -L 1,5 README.md'
allow 'git cat-file -p HEAD'
allow 'git branch --list'
allow 'git branch --show-current'
allow 'git branch --list -a -v'
allow "git tag --list 'v*'"
allow 'git tag -l -n3'
allow 'git remote -v'
allow 'cat a.txt >/dev/null 2>&1 || echo missing' "|| with output to /dev/null and 2>&1"
allow $'cat a.txt\ncat b.txt' "two reads on two lines"
allow $'grep -n x \\\n  file.txt' "a backslash-newline continuation"
allow 'cat x; ' "a trailing ;"

# ─── 2. Writes, launches and escapes that must not run ───────────────
section "denied: the commands the TODO names"

deny 'touch x'
deny 'git commit -m "x"'
deny 'gh pr comment 1 --body hi'
deny "sed -i 's/a/b/' file.txt"
deny 'cat a.txt > out.txt' "> file"
deny 'cat a.txt | tee out.txt' "tee"
deny 'rm -f x'
deny 'mv a b'
deny 'cp a b'
deny "python3 -c 'print(1)'" "python3"
deny 'curl -X POST https://example.com' "curl -X POST"
deny 'echo $(touch pwned)' "\$( … )"

section "denied: the rest of the shell"

deny 'cat a.txt >> out.txt' ">> file"
deny 'cat a.txt &> out.txt' "&> file"
deny 'cat a.txt >| out.txt' ">| file"
deny 'cat a.txt 2> err.txt' "2> file"
deny 'cat a.txt >&out.txt' ">&file (stdout and stderr to a file)"
deny 'cat a.txt > /dev/null.bak' "a path that only starts with /dev/null"
deny 'cat <<< x' "here-string"
deny 'cat <> new.txt' "the read-write redirection <> (creates the file)"
deny 'cat < /dev/tcp/example.com/80' "input from bash's /dev/tcp socket"
deny 'cat < /dev/udp/example.com/53' "input from bash's /dev/udp socket"
deny $'cat <<EOF\ncat x \'\nEOF\ntouch pwned\necho \'' "a here-document hiding a command behind a quote"
deny $'cat x # \'\ntouch pwned\necho \'' "a comment hiding a command behind a quote"
deny 'cat <(touch pwned)' "process substitution <( )"
deny 'cat x > >(sh)' "process substitution >( )"
deny '(touch pwned)' "a subshell"
deny 'cat x & touch y' "a background job"
deny 'cat x &' "a lone background job"
deny 'cat x |& head' "|&"
deny 'echo `touch pwned`' "backticks"
deny 'cat "$(touch pwned)"' "\$( … ) inside double quotes"
deny 'cat "`touch pwned`"' "backticks inside double quotes"
deny 'cat $HOME/x' "an unquoted \$VAR"
deny 'cat "${HOME}/x"' "\${VAR} inside double quotes"
deny "sort \$'-o' out.txt in.txt" "\$'…' quoting that spells an option"
deny 'FOO=1 cat x' "a VAR=value prefix"
deny 'env cat x' "env"
deny 'xargs rm < list.txt' "xargs"
deny "bash -c 'cat x'" "bash -c"
deny "sh -c 'cat x'" "sh -c"
deny 'eval cat x' "eval"
deny "awk '{print}' x" "awk"
deny "node -e '1'" "node"
deny "perl -e '1'" "perl"
deny 'cat x; touch y' "; then a write"
deny 'cat x && touch y' "&& then a write"
deny 'cat x || touch y' "|| then a write"
deny 'cat x | sh' "a pipe into sh"
deny $'cat x\ntouch y' "a write on the next line"
deny 'cat x | | head' "an empty pipeline stage"
deny "cat 'x" "an unterminated quote"
deny '/bin/rm x' "a command by path"
deny 'command cat x' "command"
deny 'for f in a; do cat $f; done' "a for loop"

section "denied: write and launch options of allowed commands"

deny "sed -n -i '1p' file.txt" "sed -n -i"
deny "sed -ni '1p' file.txt" "sed -ni"
deny "sed -n --in-place '1p' file.txt" "sed --in-place"
deny "sed -n '1p;w out.txt' file.txt" "sed w command"
deny "sed -n 's/a/b/w out.txt' file.txt" "sed s///w"
deny "sed -n '1e id' file.txt" "sed e command"
deny "sed -n '1r /etc/passwd' file.txt" "sed r command"
deny "sed -n -e '1p' -e 'w out.txt' file.txt" "a second -e script that writes"
deny "sed -n -- 'w out.txt' file.txt" "sed -- then a writing script (measured: GNU sed writes)"
deny "sed '1p' file.txt" "sed without -n"
deny "sed -n -f script.sed file.txt" "sed -f (a script file)"
deny 'sed -n 1p *' "an unquoted glob in sed's arguments (a file named -i)"
deny 'sed -n 1p {-i,x}' "a brace expansion spelling -i"
deny 'find . -delete' "find -delete"
deny 'find . -rm' "find -rm (bfs)"
# {} quoted: unquoted it is a brace, and the glob rule would answer instead.
deny "find . -exec rm '{}' ';'" "find -exec"
deny "find . -execdir rm '{}' +" "find -execdir"
deny "find . -ok rm '{}' ';'" "find -ok"
deny "find . -okdir rm '{}' ';'" "find -okdir"
deny 'find . -fprint out.txt' "find -fprint"
deny 'find . -fls out.txt' "find -fls"
deny 'find * -name x' "an unquoted glob in find's arguments (a file named -delete)"
deny "grep --filter='*:sh' x ." "grep --filter (ugrep runs a program)"
deny 'grep --save-config x' "grep --save-config (ugrep writes a file)"
deny 'grep --pager=sh x f' "grep --pager (ugrep opens a program)"
deny 'grep --view=sh x f' "grep --view (ugrep opens a program)"
deny 'rg --pre=cat x' "rg --pre"
deny 'rg --hostname-bin=sh x' "rg --hostname-bin"
deny 'sort -o out.txt in.txt' "sort -o"
deny 'sort -uo out.txt in.txt' "sort -uo"
deny 'sort in.txt -o out.txt' "sort -o after the file (GNU permutes)"
deny 'sort --output=out.txt in.txt' "sort --output"
deny 'sort --ou=out.txt in.txt' "sort --ou= (an accepted abbreviation)"
deny 'sort --compress-program=sh in.txt' "sort --compress-program"
deny 'uniq in.txt out.txt' "uniq IN OUT"
deny 'uniq -f 2 in.txt out.txt' "uniq -f N IN OUT"
deny 'file -C -m magic' "file -C"
deny 'file --compile -m magic' "file --compile"
deny 'git -c core.pager=sh log' "git -c"
deny 'git --exec-path=/tmp log' "git --exec-path"
deny 'git push' "git push"
deny 'git checkout main' "git checkout"
deny 'git reset --hard' "git reset"
deny 'git fetch' "git fetch"
deny 'git log --output=out.txt' "git log --output"
deny 'git diff --output=out.txt' "git diff --output"
deny 'git show --ou=out.txt HEAD' "git show --ou= (an abbreviation)"
deny 'git grep -Ocat foo' "git grep -O"
deny 'git grep --open-files-in-pager=sh foo' "git grep --open-files-in-pager"
deny 'git grep --open=cat foo' "git grep --open= (measured: runs the program)"
deny 'git branch newbranch' "git branch <name> (creates)"
deny 'git branch --list -D main' "git branch --list -D"
deny 'git branch -m a b' "git branch -m"
deny 'git branch --lis' "git branch --lis (abbreviations are not listed)"
deny 'git tag v9' "git tag <name> (creates)"
deny 'git tag --list -a v9' "git tag -a (annotate, not --all)"
deny 'git tag --list -d v1' "git tag -d"
deny 'git remote add x https://example.com' "git remote add"
deny 'git log *.md' "an unquoted glob in git's arguments"

# ─── 3. The hook input itself ────────────────────────────────────────
section "hook input"

got=$(verdict_of '{"tool_name":"Read","tool_input":{"file_path":"/x"}}')
[[ "$got" == ALLOW ]] && pass "a non-Bash tool is left alone" \
  || fail "a non-Bash tool is left alone" "got $got"

got=$(verdict_of '{"tool_input":{"command":"cat x"}}')
[[ "$got" == DENY ]] && pass "an input naming no tool is denied" \
  || fail "an input naming no tool is denied" "got $got"

got=$(verdict_of 'not json')
[[ "$got" == DENY ]] && pass "unreadable hook input is denied" \
  || fail "unreadable hook input is denied" "got $got"

got=$(verdict_of '{"tool_name":"Bash","tool_input":{"command":"cat x\rtouch y"}}')
[[ "$got" == DENY ]] && pass "a control character (CR) is denied" \
  || fail "a control character (CR) is denied" "got $got"

got=$(verdict_of '{"tool_name":"Bash","tool_input":{"command":"cat x\u0000; touch y"}}')
[[ "$got" == DENY ]] && pass "a NUL byte is denied" \
  || fail "a NUL byte is denied" "got $got"

long="cat x"
while (( ${#long} <= 8200 )); do long="$long && cat x"; done
got=$(verdict_of "$(payload "$long")")
[[ "$got" == DENY ]] && pass "a command over 8192 characters is denied" \
  || fail "a command over 8192 characters is denied" "got $got"

# Without jq the hook cannot read the call; it must still say no, in valid JSON.
NOJQ_PATH="$TMP/nojq-bin"
mkdir -p "$NOJQ_PATH"
LAST_OUT=$(payload 'cat x' | env PATH="$NOJQ_PATH" "$BASH_BIN" "$HOOK" 2>/dev/null)
rc=$?
got=$(classify "$LAST_OUT" "$rc")
# "jq is not installed", not just "jq": every reason lists jq among the reads.
if [[ "$got" == DENY && "$LAST_OUT" == *"jq is not installed"* ]]; then
  pass "with no jq on PATH the call is denied, naming jq"
else
  fail "with no jq on PATH the call is denied, naming jq" "got $got — ${LAST_OUT:0:200}"
fi

# ─── 4. What the agent is told ───────────────────────────────────────
section "deny reason"

LAST_OUT=$(payload 'touch x' | "$BASH_BIN" "$HOOK" 2>/dev/null)
reason=$(printf '%s' "$LAST_OUT" | jq -r '.hookSpecificOutput.permissionDecisionReason // ""')
[[ "$reason" == *"Read tool"* ]] && pass "the reason points the agent at the Read tool" \
  || fail "the reason points the agent at the Read tool" "$reason"
[[ "$reason" == *"git log"* && "$reason" == *"sed -n"* ]] && pass "the reason lists the Bash reads that are allowed" \
  || fail "the reason lists the Bash reads that are allowed" "$reason"
[[ "$reason" != *$'\n'* ]] && pass "the reason is one line" \
  || fail "the reason is one line" "$reason"
[[ "$(printf '%s' "$LAST_OUT" | grep -c '')" == 1 ]] && pass "the output is one JSON line" \
  || fail "the output is one JSON line" "$LAST_OUT"

# ─── 5. The wiring in the agent file ─────────────────────────────────
# The hook guards only what wires it. Read the command the frontmatter runs,
# point its ~ at a scratch HOME, and run it the way Claude Code does: through
# a shell. A missing script must come out as exit 2 (blocking), never as the
# non-blocking error that would let the call run.
section "frontmatter wiring"

hooks_json=$(sed -n '/^---$/,/^---$/{s/^hooks: //p;}' "$AGENT")
wired=$(printf '%s' "$hooks_json" | jq -r '
  [.PreToolUse[]? | select(.matcher == "Bash") | .hooks[]? | select(.type == "command") | .command] | first // ""' 2>/dev/null)
if [[ "$wired" == *wf-reader-guard.sh* ]]; then
  pass "wf-reader.md wires wf-reader-guard.sh as a PreToolUse Bash command hook"
else
  fail "wf-reader.md wires wf-reader-guard.sh as a PreToolUse Bash command hook" "hooks: $hooks_json"
fi

FAKE_HOME="$TMP/home"
mkdir -p "$FAKE_HOME/.claude/hooks"
cp "$HOOK" "$FAKE_HOME/.claude/hooks/wf-reader-guard.sh"
out=$(payload 'touch x' | HOME="$FAKE_HOME" sh -c "$wired" 2>/dev/null); rc=$?
got=$(classify "$out" "$rc")
[[ "$got" == DENY ]] && pass "the wired command denies a write" \
  || fail "the wired command denies a write" "got $got rc=$rc"
out=$(payload 'cat x' | HOME="$FAKE_HOME" sh -c "$wired" 2>/dev/null); rc=$?
got=$(classify "$out" "$rc")
[[ "$got" == ALLOW ]] && pass "the wired command allows a read" \
  || fail "the wired command allows a read" "got $got rc=$rc"

EMPTY_HOME="$TMP/empty-home"
mkdir -p "$EMPTY_HOME"
payload 'cat x' | HOME="$EMPTY_HOME" sh -c "$wired" >/dev/null 2>&1; rc=$?
[[ "$rc" == 2 ]] && pass "with the script missing the wired command exits 2 (blocks)" \
  || fail "with the script missing the wired command exits 2 (blocks)" "rc=$rc"

# ─── Summary ─────────────────────────────────────────────────────────
printf "\n${YELLOW}━━━ Results ━━━${NC}\n"
printf "  Total:  %d\n" "$TESTS_RUN"
printf "  ${GREEN}Passed: %d${NC}\n" "$TESTS_PASSED"
if [[ $TESTS_FAILED -gt 0 ]]; then
  printf "  ${RED}Failed: %d${NC}\n" "$TESTS_FAILED"
  exit 1
fi
printf "  ${GREEN}All tests passed.${NC}\n"
exit 0
