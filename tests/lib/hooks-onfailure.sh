#!/usr/bin/env bash
# hooks-onfailure.sh — which hooks in configs/settings-hooks.json fail closed.
#
# Sourced by tests/test-hooks.sh, never run on its own: it uses that suite's
# helpers (pass, fail, assert_eq) and its $SETTINGS. Split out because
# test-hooks.sh sits at the edge of the 1500-line cap.
#
# A hook that fails — cannot start, times out, exits other than 0 or 2, prints
# output that does not parse — is a non-blocking error by default: the action
# goes ahead. For pre-tool-guardian that ran the command with no check at all:
# on 2026-11-26 19:04-19:18Z, 7 of the 283 Bash calls of one Claude Code 2.1.331
# Workflow run hit the guardian's 5 s timeout, and each command ran unchecked.
# None of the 858 other Bash calls on the host in that window did: that run's
# agents ran their builds in the session's own cgroup scope, where its hooks run
# too, and starved them. "onFailure": "block" (Claude Code 2.1.295+; an older
# CLI ignores the key, as it ignores id and description) refuses the call
# instead. secret-scanner stays fail-open on purpose: it only ever adds a note
# and never blocks a prompt, so a failure that blocked one would stop work the
# hook exists not to stop (docs/research/2026-11-26-claude-code-2.1.331-rechecks.md).
jq -e '.hooks.PreToolUse[].hooks[] | select(.id=="pre-tool-guardian") | .onFailure == "block"' \
  "$SETTINGS" >/dev/null 2>&1 \
  && pass "pre-tool-guardian fails closed (onFailure: block)" \
  || fail "pre-tool-guardian fails closed (onFailure: block)"

# Once a timeout refuses the call, the limit decides how often a starved
# guardian turns into a refusal. A normal run takes about 0.05 s; in the starved
# run above, 30 of 82 trivially fast Bash calls took 5 s or more end to end and
# 2 took 15 s or more. No other hook fails closed, so their limits stay as set.
jq -e '.hooks.PreToolUse[].hooks[] | select(.id=="pre-tool-guardian")
       | (.timeout | type) == "number" and .timeout >= 15' \
  "$SETTINGS" >/dev/null 2>&1 \
  && pass "pre-tool-guardian's timeout leaves a starved guardian room (>= 15 s)" \
  || fail "pre-tool-guardian's timeout leaves a starved guardian room (>= 15 s)"

jq -e '[.hooks.UserPromptSubmit[].hooks[] | select(.id=="secret-scanner")] | length == 1
       and (.[0].onFailure // "continue") == "continue"' \
  "$SETTINGS" >/dev/null 2>&1 \
  && pass "secret-scanner stays fail-open: a failed note never blocks a prompt" \
  || fail "secret-scanner stays fail-open: a failed note never blocks a prompt"

# The field takes effect only on a synchronous command/http/mcp_tool hook, and
# not on Stop, SubagentStop, TaskCompleted or TeammateIdle (Claude Code hooks
# reference, "Block the action when a hook fails"); its values are "block" and
# "continue". Anywhere else it reads as a guard while guarding nothing.
# Prints one line per misplaced or misspelt onFailure.
onfailure_misplaced() {
  jq -r '
    .hooks | to_entries[] as $ev
    | $ev.value[]?.hooks[]? | select(has("onFailure"))
    | .onFailure as $of | .type as $ty
    | select(((["block", "continue"] | index([$of])) == null)
             or ((["command", "http", "mcp_tool"] | index([$ty])) == null)
             or .async == true or .asyncRewake == true
             or ((["Stop", "SubagentStop", "TaskCompleted", "TeammateIdle"] | index([$ev.key])) != null))
    | "\($ev.key)/\(.id // .command // "?")"' "$1" 2>/dev/null
}
_of_bad=$(onfailure_misplaced "$SETTINGS")
if [[ -z "$_of_bad" ]]; then
  pass "every onFailure sits where Claude Code honours it"
else
  fail "every onFailure sits where Claude Code honours it" "misplaced: $(tr '\n' ' ' <<< "$_of_bad")"
fi
# Negative control: the check fires on each misplacement it claims to catch.
_of_fx="$(mktemp)"
cat > "$_of_fx" <<'FX'
{"hooks":{
 "Stop":[{"hooks":[{"id":"on-stop","type":"command","command":"x","onFailure":"block"}]}],
 "PostToolUse":[{"hooks":[{"id":"on-async","type":"command","command":"x","async":true,"onFailure":"block"},
                          {"id":"on-rewake","type":"command","command":"x","asyncRewake":true,"onFailure":"block"},
                          {"id":"on-prompt","type":"prompt","prompt":"x","onFailure":"block"},
                          {"id":"misspelt","type":"command","command":"x","onFailure":"deny"},
                          {"id":"fine","type":"command","command":"x","onFailure":"block"}]}]}}
FX
assert_eq "$(onfailure_misplaced "$_of_fx" | sort | tr '\n' ' ')" \
  "PostToolUse/misspelt PostToolUse/on-async PostToolUse/on-prompt PostToolUse/on-rewake Stop/on-stop " \
  "the onFailure placement check fires on each misplacement, and not on a valid one"
rm -f "$_of_fx"
