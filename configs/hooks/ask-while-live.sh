#!/usr/bin/env bash
# ask-while-live.sh — refuse AskUserQuestion while this session has a live
# background task, so its completion notice can still wake the session.
#
# Triggered: PreToolUse (matcher: AskUserQuestion), main thread only.
#
# Why. AskUserQuestion parks the session until a human answers. A background
# task that finishes meanwhile queues its <task-notification>, and nothing
# reads it until the answer arrives. Measured 2026-10-22 over 59 lead
# sessions that ran a Workflow (26 AskUserQuestion calls): 4 questions were
# open when a workflow finished, and the 7 completions behind them sat unread
# for 36.5 completion-hours. A plain-text question ends the turn instead, and
# a completion notice then starts the next one.
#
# Output — Claude Code's PreToolUse schema, nothing else:
#   deny   {"hookSpecificOutput":{"hookEventName":"PreToolUse",
#            "permissionDecision":"deny","permissionDecisionReason":"..."}}
#   allow  exit 0 with no output
# A wrong deny costs one plain-text question. A missed live task is the
# failure this exists for, so every doubt resolves toward "still running".
#
# What counts, read from the transcript (shapes measured 2026-10-23 on 183
# lead transcripts, Claude Code 2.1.236 → 2.1.283). Launches are read from the
# structured `toolUseResult` of the launching tool's result record, never from
# result text, so a file that merely quotes a launch line launches nothing:
#   Bash      .backgroundTaskId — run_in_background, a timeout that moved the
#             command to the background, or a manual background
#   Workflow  .taskType "local_workflow" → .taskId (always "async_launched")
#   Agent     .isAsync true or .status "async_launched" → .agentId
#   Monitor   .taskId + .timeoutMs; it expires at launch + timeoutMs unless
#             .persistent
#   SendMessage .resumedAgentId — a finished agent running again
#   a `task_status` attachment with status "running" (a snapshot of a task)
# A task ends at the first of:
#   a <task-notification> naming its <task-id> with a <status> other than
#     running/pending (completed, failed, killed, …), or a Monitor
#     "[Monitor expired after …]" / "[Monitor timed out …]" event — read from
#     queue-operation records, user messages and queued_command attachments,
#     never from a tool result, which is only what some command printed
#   a TaskStop result (.task_id + .task_type), a TaskOutput result whose
#     .task.status is not running, a task_status attachment that is not
#     running, or a Monitor's expiry time passing
#   the process that owned it exiting: a task launched before the start time
#     of this session's live process (<config>/sessions/<pid>.json) belongs to
#     a process that is gone — a resumed session would otherwise be refused
#     every question for good. Skipped when no live entry names the session.
#
# Speed: a fixed-string grep keeps only lines carrying one of the markers
# below; jq parses those. 0.03 s for the grep on a 62 MB transcript; see
# tests/test-ask-while-live.sh for the bound the suite enforces.
# Robustness: a missing transcript, no jq, a malformed or oversized line, or
# any parse failure ends in exit 0 with no output, never in stray stdout. A
# FIFO or device path is refused before grep could block on it.
#
# CLADE_ASK_WHILE_LIVE_NOW (epoch seconds) replaces the clock. It exists for
# re-scoring a past transcript at the moment of each question and for the
# clock cases in the test suite; nothing sets it in normal use. A value that
# is not all digits is ignored and the real clock used.
#
# Timestamps: Claude Code writes "2026-10-22T22:44:36.421Z", and jq's
# fromdateiso8601 rejects the fraction, so `secs` strips it first. Without the
# strip every record's time is null, which switches off Monitor expiry and the
# process-start filter below on all real data.

set -uo pipefail

# No jq: every read below falls back to "", so the hook exits 0 silently.
INPUT=$(cat)

TOOL_NAME=$(printf '%s' "$INPUT" | jq -r '.tool_name // ""' 2>/dev/null || echo "")
[[ "$TOOL_NAME" == "AskUserQuestion" ]] || exit 0

# A subagent's question is not the lead's to redirect, and the lead's tasks
# do not notify it. Claude Code sets agent_id only inside a subagent.
AGENT_ID=$(printf '%s' "$INPUT" | jq -r '.agent_id // ""' 2>/dev/null || echo "")
[[ -z "$AGENT_ID" ]] || exit 0

TRANSCRIPT=$(printf '%s' "$INPUT" | jq -r '.transcript_path // ""' 2>/dev/null || echo "")
SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // ""' 2>/dev/null || echo "")
[[ -n "$TRANSCRIPT" && -f "$TRANSCRIPT" && -r "$TRANSCRIPT" ]] || exit 0

NOW="${CLADE_ASK_WHILE_LIVE_NOW:-}"
[[ "$NOW" =~ ^[0-9]+$ ]] || NOW=$(date +%s)

# ─── Start of this session's live process ─────────────────────────────
# Claude Code keeps one <config>/sessions/<pid>.json per running process,
# with its sessionId and startedAt (ms). Only an entry whose pid is alive
# counts; with several, the earliest wins, which keeps the most tasks.
STARTED=null
CFG="${CLAUDE_CONFIG_DIR:-${HOME:-}/.claude}"
if [[ -n "$SESSION_ID" && -d "$CFG/sessions" ]]; then
  set -- "$CFG"/sessions/*.json
  if [[ -e "$1" ]]; then
    while read -r pid started; do
      [[ "$pid" =~ ^[0-9]+$ && "$started" =~ ^[0-9]+$ ]] || continue
      kill -0 "$pid" 2>/dev/null || continue
      started=$((started / 1000))
      if [[ "$STARTED" == null || "$started" -lt "$STARTED" ]]; then
        STARTED=$started
      fi
    done < <(jq -r --arg sid "$SESSION_ID" '
        select(type == "object" and .sessionId == $sid
               and (.pid | type) == "number" and (.startedAt | type) == "number")
        | "\(.pid) \(.startedAt | floor)"' "$@" 2>/dev/null)
  fi
fi

# ─── Live tasks ───────────────────────────────────────────────────────
# The markers are JSON keys as Claude Code writes them (compact, `"key":"`),
# so text quoting a key inside a string (`\"key\":\"`) does not match.
# "task_id" covers both TaskStop and TaskOutput (its .task.task_id).
# Lines over 4 MiB are skipped unparsed: no launch record is that long, and a
# notification that long only loses its "ended", which errs toward a deny.
OUT=$(LC_ALL=C grep -a -F \
        -e '"backgroundTaskId":"' -e '"taskId":"' -e '"agentId":"' \
        -e '"resumedAgentId":"' -e '"task_id":"' -e '<task-notification>' \
        "$TRANSCRIPT" 2>/dev/null \
  | jq -R -n -c --argjson now "$NOW" --argjson started "$STARTED" '
    def secs:
      if type == "string" then (sub("\\.[0-9]+Z$"; "Z") | try fromdateiso8601 catch null)
      else null end;
    def str: if type == "string" then . else "" end;
    def obj: if type == "object" then . else {} end;
    def texts:
      if type == "string" then .
      elif type == "array" then
        [ .[] | select(type == "object" and .type == "text") | (.text | str) ] | join("\n")
      else "" end;
    # Text that can carry a real notification: never a tool result.
    def notice_text:
      if .type == "queue-operation" then (.content | str)
      elif .type == "user" then (.message | obj | .content | texts)
      elif .type == "attachment" and ((.attachment | obj | .type) == "queued_command")
        then (.attachment.prompt | texts)
      else "" end;
    # ids a text reports finished
    def finished_ids:
      if index("<task-notification>") == null then empty
      else split("<task-notification>")[1:][]
        | split("</task-notification>")[0] as $b
        | ([$b | capture("<task-id>(?<v>[A-Za-z0-9_-]+)</task-id>")] | first | .v) as $id
        | ([$b | capture("<status>(?<v>[A-Za-z_]+)</status>")] | first | .v) as $st
        | select($id != null)
        | select(($st != null and $st != "running" and $st != "pending")
                 or ($b | contains("<event>[Monitor expired after"))
                 or ($b | contains("<event>[Monitor timed out")))
        | $id
      end;
    def finish($id): .ended[$id] = true | del(.live[$id]);
    def launch($id; $k; $l; $t; $x):
      if .ended[$id] or .live[$id] then . else .live[$id] = {k: $k, l: $l, t: $t, x: $x} end;
    # A resumed agent keeps its id, so it runs again whatever ended it before.
    def relaunch($id; $k; $l; $t): .live[$id] = {k: $k, l: $l, t: $t, x: null};
    def step($r):
      ($r.timestamp | secs) as $t
      | ($r.toolUseResult | obj) as $u
      | ($r.attachment | obj) as $a
      | if $r.type == "user" and ($u | length) > 0 then
          if ($u.backgroundTaskId | type) == "string" then
            launch($u.backgroundTaskId; "Bash"; ""; $t; null)
          elif $u.taskType == "local_workflow" and ($u.taskId | type) == "string" then
            launch($u.taskId; "workflow"; ($u.summary // $u.workflowName | str); $t; null)
          elif ($u.isAsync == true or $u.status == "async_launched")
               and ($u.agentId | type) == "string" then
            launch($u.agentId; "agent"; ($u.description | str); $t; null)
          elif ($u.taskId | type) == "string" and ($u | has("timeoutMs")) then
            launch($u.taskId; "Monitor"; ""; $t;
              (if $u.persistent == true or ($u.timeoutMs | type) != "number" or $t == null
               then null else $t + $u.timeoutMs / 1000 end))
          elif ($u.resumedAgentId | type) == "string" then
            relaunch($u.resumedAgentId; "agent"; ($u.pin | obj | .name | str); $t)
          elif ($u.task_id | type) == "string" and ($u | has("task_type")) then
            finish($u.task_id)
          elif ($u.retrieval_status | type) == "string"
               and ($u.task | obj | .task_id | type) == "string"
               and (($u.task.status // "running") as $s | $s != "running" and $s != "pending") then
            finish($u.task.task_id)
          else . end
        else . end
      | if $r.type == "attachment" and $a.type == "task_status" and ($a.taskId | type) == "string" then
          if $a.status == "running" then launch($a.taskId; ($a.taskType | str); ($a.description | str); $t; null)
          else finish($a.taskId) end
        else . end
      | reduce ($r | notice_text | finished_ids) as $id (.; finish($id));
    reduce (inputs | select(length <= 4194304) | (try fromjson catch null) | select(type == "object")) as $r
      ({live: {}, ended: {}}; . as $s | try step($r) catch $s)
    | [ .live | to_entries[] | .value + {id: .key}
        | select(.x == null or .x > $now)
        | select($started == null or .t == null or .t >= $started - 2) ]
    | sort_by(.t // 0)
    | select(length > 0)
    | length as $n
    | ([ .[:5][] | "\(.id) \(.k)" + (if .l != "" then " \"" + (.l | .[:60]) + "\"" else "" end) ]
       | join(", ")) as $list
    | ($list + (if $n > 5 then ", +\($n - 5) more" else "" end)) as $list
    | {hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny",
        permissionDecisionReason: ("\($n) background task(s) still running (\($list)). AskUserQuestion blocks this session until it is answered, so their completion notices cannot wake you — measured: 7 completions sat unread for 36.5 h behind 4 questions. Ask in plain text and end your turn instead.")}}
  ' 2>/dev/null) || OUT=""

[[ "$OUT" == '{"hookSpecificOutput":{"hookEventName":"PreToolUse",'* ]] && printf '%s\n' "$OUT"
exit 0
