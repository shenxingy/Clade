#!/usr/bin/env bash
# test-ask-while-live.sh — Tests for configs/hooks/ask-while-live.sh
#   (PreToolUse AskUserQuestion: refuse the question while a background task
#   launched by this session is still running)
#
# Builds fixture transcripts whose records copy the shapes Claude Code wrote on
# this host (2.1.236 → 2.1.283): the launching tool's result record with its
# structured toolUseResult, and the three places a <task-notification> lands
# (queue-operation, user message, queued_command attachment). Covers: each
# launch kind (Workflow, background Bash, async Agent, Monitor, a resumed agent,
# a task_status snapshot), each way a task ends (a terminal <status>, TaskStop,
# TaskOutput, a Monitor's expiry event or time, task_status), text that only
# QUOTES a launch or a notification, subagent and other-tool input, missing /
# unreadable / FIFO / malformed / oversized / NUL-bearing transcripts,
# millisecond and whole-second timestamps, the CLADE_ASK_WHILE_LIVE_NOW clock
# override, the process-start registry and its 2 s boundary, the settings
# wiring, and a 100 MB timing bound.
#
# Runs under bash 3.2 (macOS /bin/bash) as well as 5.x; CI runs only 5.x, so
# keep to 3.2 syntax — a `${2:-{\}}` default once broke every check on 3.2.
#
# The last suite removes each guard of the hook in turn and requires this
# suite to go red, with a no-op control that must stay green — the mutation
# check, kept here so CI re-runs it. A mutation whose anchor no longer matches
# is a failure, not a skip.
#
# Usage:
#   bash tests/test-ask-while-live.sh        # Run all tests
#   bash tests/test-ask-while-live.sh -v     # Verbose mode
# Internal (the mutation suite sets these for each mutant run):
#   ASK_HOOK / ASK_SETTINGS   test these files instead of the repository's
#   ASK_MUTANT=1              stop at the first failure; skip timing + mutations

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK="${ASK_HOOK:-$REPO_ROOT/configs/hooks/ask-while-live.sh}"
SETTINGS="${ASK_SETTINGS:-$REPO_ROOT/configs/settings-hooks.json}"
ASK_MUTANT="${ASK_MUTANT:-}"

# ─── Test framework (mirrors tests/test-rule-injector.sh) ────────────
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
VERBOSE="${1:-}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

pass() {
  TESTS_PASSED=$((TESTS_PASSED + 1))
  echo -e "  ${GREEN}✓${NC} $1"
}

fail() {
  TESTS_FAILED=$((TESTS_FAILED + 1))
  echo -e "  ${RED}✗${NC} $1"
  [[ -n "${2:-}" ]] && echo -e "    ${RED}→ $2${NC}"
  # A mutant run only has to show that SOMETHING noticed.
  [[ -n "$ASK_MUTANT" ]] && exit 1
  return 0
}

section() { echo ""; echo -e "${YELLOW}━━━ $1 ━━━${NC}"; }

check() {  # check MSG CONDITION-RESULT(0/1) [DETAIL]
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ "$2" -eq 0 ]]; then pass "$1"; else fail "$1" "${3:-}"; fi
}
check_cmd() {  # check_cmd MSG DETAIL COMMAND... — passes when COMMAND succeeds
  local msg="$1" detail="$2"
  shift 2
  if "$@" > /dev/null 2>&1; then check "$msg" 0; else check "$msg" 1 "$detail"; fi
}

# ─── Sandbox ─────────────────────────────────────────────────────────

SANDBOX="$(mktemp -d /tmp/clade-test-ask-while-live-XXXXXX)"
case "$SANDBOX" in
  /tmp/clade-test-ask-while-live-*) : ;;
  *) echo "FATAL: sandbox '$SANDBOX' not under /tmp — aborting"; exit 1 ;;
esac
cleanup() { chmod -R u+rw "$SANDBOX" 2>/dev/null; rm -rf "$SANDBOX"; }
trap cleanup EXIT

FAKE_HOME="$SANDBOX/home"
EMPTY_CFG="$SANDBOX/cfg-empty"
mkdir -p "$FAKE_HOME/.claude" "$EMPTY_CFG"

# ─── Fixture records ─────────────────────────────────────────────────
# Each r_* prints one transcript line. OFFSET is seconds from now (negative =
# in the past), so expiry and process-start cases need no clock injection.
#
# Timestamps carry milliseconds, as Claude Code writes them
# ("2026-10-22T22:44:36.421Z"). jq's fromdateiso8601 rejects that shape, so a
# fixture with whole seconds would pass even with the hook's millisecond strip
# removed — and on real data every time rule would then be switched off.
# ISO_WHOLE=1 emits whole seconds, for the one case that pins that form too.
ISO_WHOLE=""
iso() {
  if [[ -n "$ISO_WHOLE" ]]; then
    jq -nr --argjson o "${1:-0}" '(now + $o) | floor | todate'
  else
    jq -nr --argjson o "${1:-0}" '(now + $o) | floor | todate | sub("Z$"; ".421Z")'
  fi
}

# The launching tool's result: its text plus the structured toolUseResult.
r_result() {  # OFFSET TEXT TOOL_USE_RESULT_JSON
  jq -nc --arg ts "$(iso "$1")" --arg text "$2" --argjson tu "$3" \
    '{parentUuid:"p",isSidechain:false,type:"user",timestamp:$ts,
      message:{role:"user",content:[{tool_use_id:"toolu_fixture",type:"tool_result",content:$text}]},
      toolUseResult:$tu}'
}
r_workflow() {  # ID OFFSET [SUMMARY]
  local s="${3:-Fixture workflow run}"
  r_result "$2" "Workflow launched in background. Task ID: $1
Summary: $s" "$(jq -nc --arg id "$1" --arg s "$s" \
    '{runId:"wf_0000aaaa-000",scriptPath:"/x/s.js",status:"async_launched",summary:$s,
      taskId:$id,taskType:"local_workflow",transcriptDir:"/x",workflowName:"fixture"}')"
}
r_bash() {  # ID OFFSET
  r_result "$2" "Command running in background with ID: $1. Output is being written to: /tmp/x/$1.output" \
    "$(jq -nc --arg id "$1" '{stdout:"",stderr:"",interrupted:false,isImage:false,noOutputExpected:false,backgroundTaskId:$id}')"
}
r_bash_timeout() {  # ID OFFSET — a foreground command moved to the background
  r_result "$2" "Command did not complete within its 120s timeout and was moved to the background (ID: $1). Output is being written to: /tmp/x/$1.output" \
    "$(jq -nc --arg id "$1" '{stdout:"",stderr:"",interrupted:false,isImage:false,noOutputExpected:false,backgroundTaskId:$id,timedOutAfterMs:120000}')"
}
r_agent() {  # ID OFFSET [DESCRIPTION]
  r_result "$2" "Async agent launched successfully.
agentId: $1 (internal ID - do not mention to user.)" \
    "$(jq -nc --arg id "$1" --arg d "${3:-Fixture agent}" \
      '{isAsync:true,status:"async_launched",agentId:$id,description:$d,prompt:"p",outputFile:"/x",canReadOutputFile:true,resolvedModel:"m"}')"
}
r_agent_sync() {  # ID OFFSET — a foreground agent that already finished (inferred shape)
  r_result "$2" "done" "$(jq -nc --arg id "$1" '{status:"completed",agentId:$id,content:[{type:"text",text:"done"}],totalDurationMs:10}')"
}
r_monitor() {  # ID OFFSET TIMEOUT_MS PERSISTENT(true|false)
  r_result "$2" "Monitor started (task $1, expires in 30m unless the source ends first)." \
    "$(jq -nc --arg id "$1" --argjson t "$3" --argjson p "$4" '{taskId:$id,timeoutMs:$t,persistent:$p}')"
}
r_resume() {  # ID OFFSET — SendMessage to a finished agent runs it again
  r_result "$2" "{\"success\":true,\"message\":\"Resuming agent x\",\"resumedAgentId\":\"$1\"}" \
    "$(jq -nc --arg id "$1" '{success:true,message:"Resuming agent x",resumedAgentId:$id,pin:{id:$id,name:$id,ref:"r"}}')"
}
r_taskstop() {  # ID OFFSET
  r_result "$2" "{\"message\":\"Successfully stopped task: $1 (cmd)\"}" \
    "$(jq -nc --arg id "$1" '{message:("Successfully stopped task: " + $id + " (cmd)"),task_id:$id,task_type:"local_workflow",command:"cmd"}')"
}
r_taskoutput() {  # ID STATUS OFFSET
  r_result "$3" "<retrieval_status>success</retrieval_status>" \
    "$(jq -nc --arg id "$1" --arg st "$2" '{retrieval_status:"success",task:{task_id:$id,task_type:"local_workflow",status:$st,description:"d",output:"o"}}')"
}
# A <task-notification> block. STATUS "-" = none (a Monitor event); EVENT optional.
notif() {  # ID STATUS [EVENT]
  local st="" ev=""
  [[ "$2" != "-" ]] && st="<status>$2</status>
"
  [[ -n "${3:-}" ]] && ev="<event>$3</event>
"
  printf '<task-notification>\n<task-id>%s</task-id>\n<tool-use-id>toolu_fixture</tool-use-id>\n<output-file>/tmp/x/%s.output</output-file>\n%s<summary>Fixture %s</summary>\n%s</task-notification>' \
    "$1" "$1" "$st" "$1" "$ev"
}
r_queue() {  # OFFSET TEXT — queue-operation enqueue, written the moment it happens
  jq -nc --arg ts "$(iso "$1")" --arg c "$2" '{type:"queue-operation",operation:"enqueue",timestamp:$ts,sessionId:"s",content:$c}'
}
r_user_text() {  # OFFSET TEXT — a notification delivered as the next turn
  jq -nc --arg ts "$(iso "$1")" --arg c "$2" '{type:"user",timestamp:$ts,message:{role:"user",content:$c},origin:{kind:"task-notification"}}'
}
r_attach() {  # OFFSET TEXT — a notification absorbed mid-turn
  jq -nc --arg ts "$(iso "$1")" --arg c "$2" '{type:"attachment",timestamp:$ts,attachment:{type:"queued_command",prompt:$c,commandMode:"task-notification"}}'
}
r_task_status() {  # ID STATUS OFFSET
  jq -nc --arg ts "$(iso "$3")" --arg id "$1" --arg st "$2" \
    '{type:"attachment",timestamp:$ts,attachment:{type:"task_status",taskId:$id,taskType:"local_bash",description:"Fixture snapshot",status:$st}}'
}
r_tool_text() {  # OFFSET TEXT — a tool result carrying TEXT and NO toolUseResult (e.g. a cat)
  jq -nc --arg ts "$(iso "$1")" --arg c "$2" \
    '{type:"user",timestamp:$ts,message:{role:"user",content:[{tool_use_id:"toolu_cat",type:"tool_result",content:$c}]},toolUseResult:{stdout:$c,stderr:"",interrupted:false,isImage:false}}'
}
r_filler() {
  jq -nc --arg ts "$(iso "${1:--1}")" '{type:"assistant",timestamp:$ts,message:{role:"assistant",content:[{type:"text",text:"working on it"}]}}'
}

# ─── Running the hook ────────────────────────────────────────────────
# ask FIXTURE [EXTRA_JSON] — runs the hook; stdout lands in $SANDBOX/out
# (bytes, so a stray newline is visible), exit code in $RC. ASK_NOW, when set,
# is handed to the hook as CLADE_ASK_WHILE_LIVE_NOW; unset, the hook sees it
# empty, so a value leaking in from the caller's environment cannot steer it.
SID="sess-fixture"
RC=0
ASK_NOW=""
ask() {
  # Not "${2:-{\}}": bash 3.2 (macOS /bin/bash) keeps the backslash, which
  # turned every default call into `--argjson x '{\}'` and exit 2.
  local tp="$SANDBOX/$1.jsonl" extra="${2:-}"
  [[ -n "$extra" ]] || extra='{}'
  [[ "$1" == /* ]] && tp="$1"
  jq -nc --arg tp "$tp" --arg sid "$SID" --argjson x "$extra" \
    '{session_id:$sid,transcript_path:$tp,cwd:"/tmp",hook_event_name:"PreToolUse",
      tool_name:"AskUserQuestion",tool_input:{questions:[{question:"Proceed?",options:[]}]}} + $x' \
    | HOME="$FAKE_HOME" CLAUDE_CONFIG_DIR="${CFG_DIR:-$EMPTY_CFG}" CLADE_ASK_WHILE_LIVE_NOW="$ASK_NOW" \
        bash "$HOOK" > "$SANDBOX/out" 2>"$SANDBOX/err"
  RC=$?
}
out() { cat "$SANDBOX/out"; }

expect_deny() {  # MSG NEEDLE... — a well-formed deny whose reason holds each NEEDLE
  local msg="$1"; shift
  local o; o=$(out)
  if [[ "$RC" -ne 0 ]]; then check "$msg" 1 "exit code $RC"; return; fi
  if ! jq -e '(keys == ["hookSpecificOutput"])
        and .hookSpecificOutput.hookEventName == "PreToolUse"
        and .hookSpecificOutput.permissionDecision == "deny"
        and (.hookSpecificOutput.permissionDecisionReason | type) == "string"' \
        > /dev/null 2>&1 <<< "$o"; then
    check "$msg" 1 "not a PreToolUse deny: $(head -c 300 <<< "$o")"; return
  fi
  local reason n
  reason=$(jq -r '.hookSpecificOutput.permissionDecisionReason' <<< "$o")
  for n in "$@"; do
    if ! grep -qF -- "$n" <<< "$reason"; then
      check "$msg" 1 "reason lacks '$n': $reason"; return
    fi
  done
  check "$msg" 0
  [[ "$VERBOSE" == "-v" ]] && echo "    reason: $reason"
  return 0
}
expect_silent() {  # MSG — exit 0 and not one byte of stdout
  local size
  size=$(wc -c < "$SANDBOX/out" | tr -d ' ')
  if [[ "$RC" -ne 0 ]]; then check "$1" 1 "exit code $RC"
  elif [[ "$size" != "0" ]]; then check "$1" 1 "stdout has $size bytes: $(head -c 200 "$SANDBOX/out")"
  else check "$1" 0; fi
}
reason_lacks() {  # MSG NEEDLE
  if grep -qF -- "$2" "$SANDBOX/out"; then check "$1" 1 "reason contains '$2'"; else check "$1" 0; fi
}

# ─── Suite 1: Each launch kind, live and ended ───────────────────────
section "Live tasks are refused; ended ones are not"

{ r_filler; r_workflow wfx000001 -600 "Audit the fixture corpus"; r_filler; } > "$SANDBOX/wf-live.jsonl"
ask wf-live
expect_deny "a live Workflow refuses the question" \
  "1 background task(s) still running" "wfx000001 workflow" '"Audit the fixture corpus"' \
  "Ask in plain text and end your turn instead."

{ r_workflow wfx000001 -600; r_queue -60 "$(notif wfx000001 completed)"; } > "$SANDBOX/wf-done-queue.jsonl"
ask wf-done-queue
expect_silent "a Workflow whose completion is queued is over (queue-operation)"

{ r_workflow wfx000001 -600; r_user_text -60 "$(notif wfx000001 completed)"; } > "$SANDBOX/wf-done-user.jsonl"
ask wf-done-user
expect_silent "a completion delivered as a user message ends it"

{ r_workflow wfx000001 -600; r_attach -60 "$(notif wfx000001 completed)"; } > "$SANDBOX/wf-done-attach.jsonl"
ask wf-done-attach
expect_silent "a completion absorbed as a queued_command attachment ends it"

{ r_workflow wfx000001 -600; r_taskstop wfx000001 -60; } > "$SANDBOX/wf-stopped.jsonl"
ask wf-stopped
expect_silent "a Workflow killed with TaskStop is over"

{ r_workflow wfx000001 -600; r_queue -60 "$(notif wfx000001 failed)"; } > "$SANDBOX/wf-failed.jsonl"
ask wf-failed
expect_silent "a failed status ends it"

{ r_bash bsx000001 -600; r_queue -60 "$(notif bsx000001 killed)"; } > "$SANDBOX/bash-killed.jsonl"
ask bash-killed
expect_silent "a killed status ends it"

{ r_workflow wfx000001 -600; r_queue -60 "$(notif wfx000001 running)"; } > "$SANDBOX/wf-status-running.jsonl"
ask wf-status-running
expect_deny "a notification whose status is 'running' does not end it" "wfx000001"

{ r_bash bsx000001 -300; } > "$SANDBOX/bash-live.jsonl"
ask bash-live
expect_deny "a live background Bash refuses the question" "bsx000001 Bash"

{ r_bash bsx000001 -300; r_queue -10 "$(notif bsx000001 completed)"; } > "$SANDBOX/bash-done.jsonl"
ask bash-done
expect_silent "a background Bash that completed is over"

{ r_bash_timeout btx000001 -300; } > "$SANDBOX/bash-moved.jsonl"
ask bash-moved
expect_deny "a command moved to the background by its timeout is a live task" "btx000001 Bash"

{ r_workflow wfx000001 -900; r_bash bsx000002 -800; r_queue -700 "$(notif wfx000001 completed)"; } > "$SANDBOX/two-one-live.jsonl"
ask two-one-live
expect_deny "two tasks, one ended: only the live one counts" "1 background task(s)" "bsx000002 Bash"
reason_lacks "the ended task is not listed" "wfx000001"

{ for i in 1 2 3 4 5 6 7; do r_bash "bsx00000$i" "-$((900 - i))"; done; } > "$SANDBOX/seven.jsonl"
ask seven
expect_deny "seven live tasks: counted in full, listed five, then '+2 more'" \
  "7 background task(s)" "bsx000001 Bash" "bsx000005 Bash" ", +2 more)"
reason_lacks "the sixth task is not listed by id" "bsx000006"

{ r_agent aax0000000000001 -300 "Review the fixture branch"; } > "$SANDBOX/agent-live.jsonl"
ask agent-live
expect_deny "a live async Agent refuses the question" "aax0000000000001 agent" '"Review the fixture branch"'

{ r_agent aax0000000000001 -300; r_queue -100 "$(notif aax0000000000001 completed)"; } > "$SANDBOX/agent-done.jsonl"
ask agent-done
expect_silent "a completed async Agent is over"

{ r_agent aax0000000000001 -300; r_queue -100 "$(notif aax0000000000001 completed)"; r_resume aax0000000000001 -50; } > "$SANDBOX/agent-resumed.jsonl"
ask agent-resumed
expect_deny "SendMessage resuming a finished agent makes it live again" "aax0000000000001 agent"

{ r_agent aax0000000000001 -300; r_queue -200 "$(notif aax0000000000001 completed)"; r_resume aax0000000000001 -150; r_queue -100 "$(notif aax0000000000001 completed)"; } > "$SANDBOX/agent-resumed-done.jsonl"
ask agent-resumed-done
expect_silent "a resumed agent's second completion ends it again"

{ r_agent_sync aax0000000000002 -300; } > "$SANDBOX/agent-sync.jsonl"
ask agent-sync
expect_silent "a foreground Agent result is not a background task"

{ r_monitor mmx000001 -600 1800000 false; } > "$SANDBOX/mon-live.jsonl"
ask mon-live
expect_deny "a Monitor inside its timeout is live" "mmx000001 Monitor"

{ r_monitor mmx000001 -2400 1800000 false; } > "$SANDBOX/mon-old.jsonl"
ask mon-old
expect_silent "a Monitor past its timeout has expired even with no notice on disk"

{ r_monitor mmx000001 -86400 1800000 true; } > "$SANDBOX/mon-persistent.jsonl"
ask mon-persistent
expect_deny "a persistent Monitor never expires" "mmx000001 Monitor"

{ r_monitor mmx000001 -600 1800000 false; r_queue -300 "$(notif mmx000001 - 'UNITS CHANGED 18:09Z')"; } > "$SANDBOX/mon-event.jsonl"
ask mon-event
expect_deny "an ordinary Monitor event leaves it live" "mmx000001 Monitor"

{ r_monitor mmx000001 -600 1800000 false; r_queue -300 "$(notif mmx000001 - '[Monitor expired after 30m with 3 events delivered. Re-arm it if you still need the watch.]')"; } > "$SANDBOX/mon-expired.jsonl"
ask mon-expired
expect_silent "a Monitor's expiry notice ends it"

{ r_monitor mmx000001 -600 1800000 false; r_queue -300 "$(notif mmx000001 - '[Monitor timed out — re-arm if needed.]')"; } > "$SANDBOX/mon-timedout.jsonl"
ask mon-timedout
expect_silent "a Monitor's timed-out notice ends it"

# Every time rule rests on parsing the record's timestamp. The fixtures carry
# Claude Code's millisecond form; this pins that they still do, and that the
# whole-second form parses as well.
ms_fixture_ok() {
  grep -qE '"timestamp":"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z"' "$SANDBOX/mon-old.jsonl"
}
check_cmd "fixture: timestamps carry milliseconds, as Claude Code writes them" \
  "$(head -c 200 "$SANDBOX/mon-old.jsonl")" ms_fixture_ok
ISO_WHOLE=1
{ r_monitor mmx000001 -2400 1800000 false; } > "$SANDBOX/mon-old-whole.jsonl"
ISO_WHOLE=""
ask mon-old-whole
expect_silent "a whole-second timestamp parses too: that Monitor has expired"

# The clock: CLADE_ASK_WHILE_LIVE_NOW replaces it (re-scoring a past
# transcript at the moment of each question); a value that is not all digits
# falls back to the real clock rather than breaking the parse.
ASK_NOW=$(( $(date +%s) - 1500 ))
ask mon-old
expect_deny "CLADE_ASK_WHILE_LIVE_NOW 25 min back: a Monitor expired now was live then" "mmx000001 Monitor"
ASK_NOW=$(( $(date +%s) + 3600 ))
ask mon-live
expect_silent "CLADE_ASK_WHILE_LIVE_NOW an hour ahead: a live Monitor has expired by then"
ASK_NOW="soon"
ask mon-live
expect_deny "a non-numeric CLADE_ASK_WHILE_LIVE_NOW falls back to the real clock" "mmx000001 Monitor"
ASK_NOW=""

{ r_workflow wfx000001 -600; r_taskoutput wfx000001 completed -60; } > "$SANDBOX/taskoutput-done.jsonl"
ask taskoutput-done
expect_silent "TaskOutput reporting 'completed' ends it"

{ r_workflow wfx000001 -600; r_taskoutput wfx000001 running -60; } > "$SANDBOX/taskoutput-running.jsonl"
ask taskoutput-running
expect_deny "TaskOutput reporting 'running' leaves it live" "wfx000001"

{ r_filler; r_task_status bsx000009 running -60; } > "$SANDBOX/status-running.jsonl"
ask status-running
expect_deny "a task_status snapshot saying 'running' is a live task" "bsx000009"

{ r_bash bsx000009 -600; r_task_status bsx000009 completed -60; } > "$SANDBOX/status-done.jsonl"
ask status-done
expect_silent "a task_status snapshot saying 'completed' ends it"

{ r_queue -601 "$(notif bsx000001 completed)"; r_bash bsx000001 -600; } > "$SANDBOX/end-first.jsonl"
ask end-first
expect_silent "a completion written before its launch record still ends it"

# ─── Suite 2: Quoting is not launching, printing is not ending ───────
section "Only structured launches and real notifications count"

{ r_tool_text -60 "Workflow launched in background. Task ID: wqx000001
Command running in background with ID: bqx000001."; } > "$SANDBOX/quoted-launch.jsonl"
ask quoted-launch
expect_silent "a tool result that only QUOTES launch lines launches nothing"

{ r_tool_text -60 '{"toolUseResult":{"backgroundTaskId":"bqx000002","taskId":"wqx000002","taskType":"local_workflow"}}'; } > "$SANDBOX/escaped-keys.jsonl"
ask escaped-keys
expect_silent "launch keys inside a string (escaped JSON) launch nothing"

{ r_workflow wfx000001 -600; r_tool_text -60 "$(notif wfx000001 completed)"; } > "$SANDBOX/printed-notif.jsonl"
ask printed-notif
expect_deny "a notification PRINTED by a command (a tool result) does not end the task" "wfx000001"

{ r_queue -60 "$(notif wzx000404 completed)"; } > "$SANDBOX/unknown-end.jsonl"
ask unknown-end
expect_silent "a notification for a task never launched here changes nothing"

# ─── Suite 3: Scope ──────────────────────────────────────────────────
section "Main thread, AskUserQuestion only"

ask wf-live '{"agent_id":"a0123456789abcdef","agent_type":"general-purpose"}'
expect_silent "inside a subagent (agent_id set) the hook stays out"

ask wf-live '{"tool_name":"Bash"}'
expect_silent "any tool but AskUserQuestion is ignored"

# ─── Suite 4: Robustness ─────────────────────────────────────────────
section "Bad input ends in exit 0 and no stdout"

jq -nc '{tool_name:"AskUserQuestion",session_id:"s"}' \
  | HOME="$FAKE_HOME" CLAUDE_CONFIG_DIR="$EMPTY_CFG" bash "$HOOK" > "$SANDBOX/out" 2>/dev/null; RC=$?
expect_silent "no transcript_path"

ask "$SANDBOX/does-not-exist.jsonl"
expect_silent "a transcript that does not exist"

mkdir -p "$SANDBOX/a-directory.jsonl"
ask "$SANDBOX/a-directory.jsonl"
expect_silent "a transcript path that is a directory"

cp "$SANDBOX/wf-live.jsonl" "$SANDBOX/unreadable.jsonl"; chmod 000 "$SANDBOX/unreadable.jsonl"
if [[ -r "$SANDBOX/unreadable.jsonl" ]]; then
  echo "  (running as root: an unreadable file cannot be made — skipped)"
else
  ask unreadable
  expect_silent "an unreadable transcript"
fi
chmod 644 "$SANDBOX/unreadable.jsonl"

printf 'not json at all' | HOME="$FAKE_HOME" CLAUDE_CONFIG_DIR="$EMPTY_CFG" bash "$HOOK" > "$SANDBOX/out" 2>/dev/null; RC=$?
expect_silent "stdin that is not JSON"
HOME="$FAKE_HOME" CLAUDE_CONFIG_DIR="$EMPTY_CFG" bash "$HOOK" < /dev/null > "$SANDBOX/out" 2>/dev/null; RC=$?
expect_silent "empty stdin"

# A FIFO would block grep forever; the hook must refuse it at once.
if command -v mkfifo >/dev/null 2>&1; then
  mkfifo "$SANDBOX/fifo.jsonl"
  ask fifo &
  FIFO_PID=$!
  waited=0
  while kill -0 "$FIFO_PID" 2>/dev/null && [[ "$waited" -lt 30 ]]; do sleep 0.1; waited=$((waited + 1)); done
  if kill -0 "$FIFO_PID" 2>/dev/null; then
    { exec 7>"$SANDBOX/fifo.jsonl"; exec 7>&-; } 2>/dev/null   # unblock the reader
    kill "$FIFO_PID" 2>/dev/null; wait "$FIFO_PID" 2>/dev/null
    check "a FIFO transcript path returns at once instead of blocking" 1 "still blocked after 3 s"
  else
    wait "$FIFO_PID" 2>/dev/null
    check "a FIFO transcript path returns at once instead of blocking" 0
  fi
else
  echo "  (mkfifo unavailable — skipped)"
fi

{
  echo 'garbage that is not JSON'
  echo '{"type":"user","timestamp":"2026-10-23T00:00:00Z","toolUseResult":{"backgroundTaskId":'
  echo '[1,2,3]'
  echo '{"type":"user","message":"a string, not an object","toolUseResult":"a string"}'
  echo '{"type":"user","timestamp":"not-a-date","toolUseResult":{"taskType":"local_workflow"}}'
  echo '{"type":"attachment","attachment":"not an object"}'
  echo '{"type":"queue-operation","operation":"enqueue","content":{"not":"a string"}}'
  r_workflow wfx000001 -600
  echo '{"type":"user","timestamp":"2026-10-23T00:00:00Z","toolUseResult":{"taskId":"<task-notification>"'
} > "$SANDBOX/malformed-live.jsonl"
ask malformed-live
expect_deny "malformed lines around a live Workflow: still refused" "wfx000001"

{ cat "$SANDBOX/malformed-live.jsonl"; r_queue -60 "$(notif wfx000001 completed)"; echo '{"broken'; } > "$SANDBOX/malformed-done.jsonl"
ask malformed-done
expect_silent "malformed lines around a finished Workflow: still silent"

{ printf 'binary\000noise "taskId":"x"\n'; r_workflow wfx000001 -600; } > "$SANDBOX/nul.jsonl"
ask nul
expect_deny "a NUL byte in the transcript does not hide a live task" "wfx000001"

# A 5 MiB line: skipped unparsed (> 4 MiB), so the hook stays fast. The
# notification inside it is lost, which errs toward a deny — by design.
# Streamed into the file: 5 MiB is past the per-argument limit of exec.
HUGE_HEAD=$(r_queue -60 "$(notif bsx000001 completed)")
{
  r_workflow wfx000001 -600
  r_bash bsx000001 -500
  printf '%s' "${HUGE_HEAD%\"\}}"
  head -c 5242880 < /dev/zero | tr '\0' 'x'
  printf '"}\n'
} > "$SANDBOX/huge-line.jsonl"
HUGE_BYTES=$(tail -n 1 "$SANDBOX/huge-line.jsonl" | wc -c | tr -d ' ')
huge_fixture_ok() {
  tail -n 1 "$SANDBOX/huge-line.jsonl" | jq -e '.type == "queue-operation"' && [ "$HUGE_BYTES" -gt 4194304 ]
}
check_cmd "fixture: the last line is valid JSON of ${HUGE_BYTES} bytes (> 4 MiB)" "" huge_fixture_ok
ask huge-line
expect_deny "a 5 MiB line neither crashes the hook nor breaks its JSON" "2 background task(s)" "bsx000001"

mkdir -p "$SANDBOX/nojq-bin"
jq -nc --arg tp "$SANDBOX/wf-live.jsonl" '{tool_name:"AskUserQuestion",transcript_path:$tp,session_id:"s"}' > "$SANDBOX/nojq-in.json"
PATH="$SANDBOX/nojq-bin" HOME="$FAKE_HOME" CLAUDE_CONFIG_DIR="$EMPTY_CFG" "$BASH" "$HOOK" \
  < "$SANDBOX/nojq-in.json" > "$SANDBOX/out" 2>/dev/null; RC=$?
expect_silent "no jq on PATH: exit 0, nothing printed"

# ─── Suite 5: Tasks of a process that has exited ─────────────────────
section "A task launched before this process started is gone"

reg() {  # DIR FILE PID STARTED_OFFSET [SESSION]
  mkdir -p "$1/sessions"
  jq -nc --argjson pid "$3" --argjson o "$4" --arg sid "${5:-$SID}" \
    '{pid:$pid,sessionId:$sid,cwd:"/tmp",startedAt:(((now + $o) * 1000) | floor),kind:"interactive"}' \
    > "$1/sessions/$2.json"
}
{ r_workflow wfx000001 -1800; } > "$SANDBOX/before-restart.jsonl"

CFG_DIR="$SANDBOX/cfg-after"; reg "$CFG_DIR" a $$ -600
ask before-restart
expect_silent "launched before this live process started: its process exited, so it is over"

CFG_DIR="$SANDBOX/cfg-before"; reg "$CFG_DIR" a $$ -3600
ask before-restart
expect_deny "launched after this live process started: still running" "wfx000001"

CFG_DIR="$SANDBOX/cfg-dead"; reg "$CFG_DIR" a 2147483646 -600
ask before-restart
expect_deny "a registry entry whose pid is not alive is ignored" "wfx000001"

CFG_DIR="$SANDBOX/cfg-other"; reg "$CFG_DIR" a $$ -600 "another-session"
ask before-restart
expect_deny "a registry entry for another session is ignored" "wfx000001"

CFG_DIR="$SANDBOX/cfg-two"; reg "$CFG_DIR" a $$ -3600; reg "$CFG_DIR" b $$ -600
ask before-restart
expect_deny "two live entries for the session: the earliest start wins" "wfx000001"

# The boundary. The filter allows 2 s between a launch record's timestamp and
# the process start: 1 s after the start is this process's own task (dropping
# it is the missed live task this hook exists to prevent); 5 s before belongs
# to the process that exited.
{ r_workflow wfx000002 -599; } > "$SANDBOX/just-after-start.jsonl"
{ r_workflow wfx000003 -605; } > "$SANDBOX/just-before-start.jsonl"
CFG_DIR="$SANDBOX/cfg-edge"; reg "$CFG_DIR" a $$ -600
ask just-after-start
expect_deny "launched 1 s after this process started: still running" "wfx000002"
ask just-before-start
expect_silent "launched 5 s before this process started: over"

# A launch whose time cannot be read is kept: every doubt resolves toward
# "still running".
r_workflow wfx000004 -1800 | jq -c 'del(.timestamp)' > "$SANDBOX/no-timestamp.jsonl"
ask no-timestamp
expect_deny "a launch with no timestamp is kept even with a live registry entry" "wfx000004"
unset CFG_DIR

# ─── Suite 6: Wiring ─────────────────────────────────────────────────
section "Wired on PreToolUse AskUserQuestion"

WIRED=$(jq -c '[.hooks.PreToolUse[]? | select(.matcher == "AskUserQuestion") | .hooks[]?
                | select(.command == "~/.claude/hooks/ask-while-live.sh")]' "$SETTINGS" 2>/dev/null)
check_cmd "settings-hooks.json wires the hook on the AskUserQuestion matcher" "found: ${WIRED:-none}" \
  test "$(jq 'length' <<< "${WIRED:-[]}")" = 1
check_cmd "the entry has a statusMessage and a timeout" "" \
  jq -e '.[0] | (.statusMessage | type) == "string" and (.statusMessage | length) > 0 and (.timeout | type) == "number"' <<< "${WIRED:-[]}"
check_cmd "the entry is synchronous (an async hook cannot refuse a call)" "" \
  jq -e '.[0] | (.async // false) == false' <<< "${WIRED:-[]}"
if [[ -z "$ASK_MUTANT" ]]; then
  check_cmd "the hook file is executable" "" test -x "$HOOK"
fi

# ─── Suite 7: Speed ──────────────────────────────────────────────────
if [[ -z "$ASK_MUTANT" ]]; then
section "A 100 MB transcript stays far inside the 5 s hook timeout"

BIG="$SANDBOX/big.jsonl"
{
  r_workflow wfx000001 -600
  EVENT=$(r_queue -300 "$(notif mzx000001 - 'UNITS CHANGED')")
  i=0; while [[ "$i" -lt 2000 ]]; do printf '%s\n' "$EVENT"; i=$((i + 1)); done
  FILL=$(jq -nc --arg t "$(head -c 1000 < /dev/zero | tr '\0' 'y')" \
    '{type:"assistant",timestamp:"2026-10-23T00:00:00Z",message:{role:"assistant",content:[{type:"text",text:$t}]}}')
  yes "$FILL" | head -n 95000
} > "$BIG"
BIG_MB=$(( $(wc -c < "$BIG" | tr -d ' ') / 1000000 ))
TIMEFORMAT='%R'
PERF_T=$( { time ask big; } 2>&1 )
expect_deny "the ${BIG_MB} MB transcript is still read correctly" "wfx000001"
check_cmd "a ${BIG_MB} MB transcript takes ${PERF_T}s (< 2 s)" "took ${PERF_T}s" \
  awk -v t="$PERF_T" 'BEGIN { exit !(t + 0 < 2.0) }'
rm -f "$BIG"
fi

# ─── Suite 8: Mutations ──────────────────────────────────────────────
#
# A clean run and a run with a guard missing print the same "ALL PASSED"
# unless something removes the guard and looks. Each entry edits ONE guard out
# of a copy of the hook (or settings-hooks.json), runs this suite against the
# copy, and requires it to go red. The first entry is the negative control: a
# no-op edit must leave the suite green, or a red result proves nothing.

if [[ -z "$ASK_MUTANT" ]]; then
section "Mutations: removing each guard turns this suite red"

MUT_DIR="$SANDBOX/mutants"
mkdir -p "$MUT_DIR"
MUT_NAMES=(); MUT_FILES=(); MUT_TARGETS=(); MUT_EXPECT=()
NMUT=0

# mutation EXPECT TARGET NAME ANCHOR REPLACEMENT — literal text, no regex.
mutation() {
  local expect="$1" target="$2" name="$3" src out
  case "$target" in
    hook) src="$HOOK" ;;
    *) src="$SETTINGS" ;;
  esac
  out="$MUT_DIR/m$NMUT.$target"
  if ! ASK_A="$4" ASK_R="$5" awk '
      { buf = buf (NR > 1 ? "\n" : "") $0 }
      END {
        a = ENVIRON["ASK_A"]; r = ENVIRON["ASK_R"]; s = buf; out = ""; n = 0
        while ((i = index(s, a)) > 0) { out = out substr(s, 1, i - 1) r; s = substr(s, i + length(a)); n++ }
        if (n != 1) exit 3
        printf "%s\n", out s
      }' "$src" > "$out"; then
    TESTS_RUN=$((TESTS_RUN + 1))
    fail "mutation '$name': its anchor no longer matches the $target exactly once"
    return 0
  fi
  MUT_NAMES[NMUT]="$name"; MUT_FILES[NMUT]="$out"
  MUT_TARGETS[NMUT]="$target"; MUT_EXPECT[NMUT]="$expect"
  NMUT=$((NMUT + 1))
}

mutation green hook "no-op control (a comment reworded)" \
  '# Speed: a fixed-string grep' '# Speed:  a fixed-string grep'

# Scope and input guards
mutation red hook "the AskUserQuestion-only check" \
  '[[ "$TOOL_NAME" == "AskUserQuestion" ]] || exit 0' 'true'
mutation red hook "the subagent (agent_id) exit" \
  '[[ -z "$AGENT_ID" ]] || exit 0' 'true'
mutation red hook "the regular-file check (a FIFO would block)" \
  '[[ -n "$TRANSCRIPT" && -f "$TRANSCRIPT" && -r "$TRANSCRIPT" ]] || exit 0' '[[ -n "$TRANSCRIPT" ]] || exit 0'
mutation red hook "grep -a (NUL bytes)" \
  'grep -a -F' 'grep -F'
mutation red hook "the per-line parse guard" \
  '(try fromjson catch null)' 'fromjson'
mutation red hook "the 4 MiB line cap" \
  'select(length <= 4194304)' 'select(true)'
mutation red hook "the stdout gate (silent means zero bytes)" \
  "[[ \"\$OUT\" == '{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",'* ]] && printf '%s\\n' \"\$OUT\"" "printf '%s\\n' \"\$OUT\""

# Prefilter markers
mutation red hook "the backgroundTaskId marker" "-e '\"backgroundTaskId\":\"' " ''
mutation red hook "the taskId marker" "-e '\"taskId\":\"' " ''
mutation red hook "the agentId marker" "-e '\"agentId\":\"' " ''
mutation red hook "the resumedAgentId marker" "-e '\"resumedAgentId\":\"' " ''
mutation red hook "the task_id marker (TaskStop, TaskOutput)" "-e '\"task_id\":\"' " ''
mutation red hook "the <task-notification> marker" "-e '<task-notification>' " ''

# Launches
mutation red hook "background Bash launch" \
  'launch($u.backgroundTaskId; "Bash"; ""; $t; null)' '.'
mutation red hook "Workflow launch" \
  'launch($u.taskId; "workflow"; ($u.summary // $u.workflowName | str); $t; null)' '.'
mutation red hook "async Agent launch" \
  'launch($u.agentId; "agent"; ($u.description | str); $t; null)' '.'
mutation red hook "async-only Agent (a foreground result is no task)" \
  '($u.isAsync == true or $u.status == "async_launched")' 'true'
mutation red hook "Monitor launch" \
  '($u | has("timeoutMs"))' 'false'
mutation red hook "a resumed agent runs again" \
  'relaunch($u.resumedAgentId; "agent"; ($u.pin | obj | .name | str); $t)' '.'
mutation red hook "a task_status 'running' snapshot" \
  'then launch($a.taskId; ($a.taskType | str); ($a.description | str); $t; null)' 'then .'

# Ends
mutation red hook "ends from notifications at all" \
  'reduce ($r | notice_text | finished_ids) as $id (.; finish($id))' '.'
mutation red hook "notices read from queue-operation records" \
  'if .type == "queue-operation" then (.content | str)' 'if .type == "queue-operation" then ""'
mutation red hook "notices read from queued_command attachments" \
  'then (.attachment.prompt | texts)' 'then ""'
mutation red hook "tool results excluded from notices" \
  'elif .type == "user" then (.message | obj | .content | texts)' 'elif .type == "user" then (.message | obj | .content | tostring)'
mutation red hook "every terminal status ends a task, not only 'completed'" \
  '($st != null and $st != "running" and $st != "pending")' '($st == "completed")'
mutation red hook "'running' is not an end" \
  '$st != "running" and ' ''
mutation red hook "a Monitor's expiry notice" \
  'or ($b | contains("<event>[Monitor expired after"))' ''
mutation red hook "a Monitor's timed-out notice" \
  'or ($b | contains("<event>[Monitor timed out"))' ''
mutation red hook "TaskStop ends a task" \
  'finish($u.task_id)' '.'
mutation red hook "TaskOutput 'completed' ends a task" \
  'finish($u.task.task_id)' '.'
mutation red hook "TaskOutput 'running' does not" \
  '($u.task.status // "running") as $s | $s != "running" and $s != "pending"' 'true'
mutation red hook "a task_status that is not 'running' ends a task" \
  'else finish($a.taskId) end' 'else . end'
mutation red hook "an end seen before the launch still counts" \
  'if .ended[$id] or .live[$id] then .' 'if .live[$id] then .'
mutation red hook "a Monitor expires at launch + timeoutMs" \
  'select(.x == null or .x > $now)' 'select(true)'
mutation red hook "a persistent Monitor never expires" \
  '$u.persistent == true or ' ''

# Time and clock
mutation red hook "the millisecond strip before fromdateiso8601" \
  'sub("\\.[0-9]+Z$"; "Z") | ' ''
mutation red hook "CLADE_ASK_WHILE_LIVE_NOW replaces the clock" \
  'NOW="${CLADE_ASK_WHILE_LIVE_NOW:-}"' 'NOW=""'
mutation red hook "a non-numeric clock override falls back to the clock" \
  '[[ "$NOW" =~ ^[0-9]+$ ]] || NOW=$(date +%s)' '[[ -n "$NOW" ]] || NOW=$(date +%s)'

# Process start
mutation red hook "tasks older than this process are dropped" \
  'select($started == null or .t == null or .t >= $started - 2)' 'select(true)'
mutation red hook "the 2 s slack keeps a task launched just after the start" \
  '.t >= $started - 2' '.t >= $started + 60'
mutation red hook "the slack is small: a task from just before the start is dropped" \
  '.t >= $started - 2' '.t >= $started - 60'
mutation red hook "a launch with no timestamp is kept" \
  '.t == null or .t >= $started' '.t >= $started'
mutation red hook "a dead pid's registry entry is ignored" \
  'kill -0 "$pid" 2>/dev/null || continue' 'true'
mutation red hook "only this session's registry entry counts" \
  '.sessionId == $sid' 'true'
mutation red hook "the earliest live entry wins" \
  '"$started" -lt "$STARTED"' '"$started" -gt "$STARTED"'

# Reason
mutation red hook "five ids listed, the rest counted" \
  '.[:5][]' '.[]'
mutation red hook "the '+N more' tail" \
  'if $n > 5 then ", +\($n - 5) more" else "" end' '""'

# Wiring
mutation red settings "the AskUserQuestion matcher" \
  '"matcher": "AskUserQuestion"' '"matcher": "AskUserQuestionX"'

# Bounded parallelism; bash 3.2 has no `wait -n`, so wait oldest-first.
ASK_JOBS=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)
[[ "$ASK_JOBS" =~ ^[0-9]+$ && "$ASK_JOBS" -ge 1 ]] || ASK_JOBS=2
[[ "$ASK_JOBS" -gt 16 ]] && ASK_JOBS=16
ASK_SELF="$REPO_ROOT/tests/test-ask-while-live.sh"

run_mutant() {
  local h="$HOOK" st="$SETTINGS"
  case "${MUT_TARGETS[$1]}" in
    hook) h="${MUT_FILES[$1]}" ;;
    *) st="${MUT_FILES[$1]}" ;;
  esac
  if command -v timeout >/dev/null 2>&1; then
    ASK_MUTANT=1 ASK_HOOK="$h" ASK_SETTINGS="$st" timeout 120 bash "$ASK_SELF" > "$MUT_DIR/m$1.log" 2>&1
  else
    ASK_MUTANT=1 ASK_HOOK="$h" ASK_SETTINGS="$st" bash "$ASK_SELF" > "$MUT_DIR/m$1.log" 2>&1
  fi
}

MUT_PIDS=(); MUT_RCS=()
ASK_NEXT=0
ASK_I=0
while [[ "$ASK_I" -lt "$NMUT" ]]; do
  if [[ $((ASK_I - ASK_NEXT)) -ge "$ASK_JOBS" ]]; then
    wait "${MUT_PIDS[$ASK_NEXT]}"; MUT_RCS[ASK_NEXT]=$?
    ASK_NEXT=$((ASK_NEXT + 1))
  fi
  run_mutant "$ASK_I" &
  MUT_PIDS[ASK_I]=$!
  ASK_I=$((ASK_I + 1))
done
while [[ "$ASK_NEXT" -lt "$NMUT" ]]; do
  wait "${MUT_PIDS[$ASK_NEXT]}"; MUT_RCS[ASK_NEXT]=$?
  ASK_NEXT=$((ASK_NEXT + 1))
done

ASK_I=0
while [[ "$ASK_I" -lt "$NMUT" ]]; do
  ASK_RC="${MUT_RCS[$ASK_I]}"
  ASK_FIRST=$(grep -m1 '✗' "$MUT_DIR/m$ASK_I.log" 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g; s/^ *✗ *//')
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ "${MUT_EXPECT[$ASK_I]}" == "green" ]]; then
    if [[ "$ASK_RC" -eq 0 ]]; then
      pass "control: ${MUT_NAMES[$ASK_I]} leaves the suite green"
    else
      fail "control: ${MUT_NAMES[$ASK_I]} leaves the suite green" "rc=$ASK_RC, first failure: $ASK_FIRST"
    fi
  elif [[ "$ASK_RC" -ne 0 ]]; then
    pass "without ${MUT_NAMES[$ASK_I]}: red — ${ASK_FIRST:-rc=$ASK_RC}"
  else
    fail "without ${MUT_NAMES[$ASK_I]}: the suite stayed GREEN" "this guard is claimed and not checked"
  fi
  ASK_I=$((ASK_I + 1))
done
fi

# ─── Summary ─────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ $TESTS_FAILED -eq 0 ]]; then
  echo -e "  ${GREEN}ALL PASSED${NC} ($TESTS_PASSED/$TESTS_RUN)"
else
  echo -e "  ${RED}$TESTS_FAILED FAILED${NC} / $TESTS_PASSED passed / $TESTS_RUN total"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

exit "$TESTS_FAILED"
