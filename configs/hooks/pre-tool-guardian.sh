#!/usr/bin/env bash
# pre-tool-guardian.sh — Block dangerous Bash commands before they execute
# exists-for: no incident recorded (added 2026-02-23 in e434b46 for unattended runs, OpenClaw playbook); need: stop timing-out migrations, catastrophic deletes, force pushes to main and DROP before they run · retire-when: per check, only after an ablation shows no such command reaches execution without it; a check that never fires is flagged for review, not retired
#
# Triggered: PreToolUse (matcher: Bash)
# Purpose:   Auto-block operations that either:
#   1. Timeout inside Claude Code (database migrations)
#   2. Are catastrophically destructive (rm -rf /, DROP DATABASE)
#   3. Could corrupt parallel agent sessions (force push to main)
# and warns, never blocks, when:
#   4. A subagent's foreground wait would outlive its prompt cache (5 minutes
#      unless the environment sets the subagent TTL to 1 hour)
# Sources lib/rm-guard.sh (which sources lib/rm-targets.sh) and, for a command
# that may push, lib/force-push-walk.sh. A missing lib fails closed.
#
# Output — Claude Code's PreToolUse schema, nothing else:
#   block   {"hookSpecificOutput":{"hookEventName":"PreToolUse",
#             "permissionDecision":"deny","permissionDecisionReason":"..."}}
#   rewrite {"hookSpecificOutput":{"hookEventName":"PreToolUse",
#             "updatedInput":{<tool_input with command replaced>},
#             "additionalContext":"..."}}
#   warn    {"hookSpecificOutput":{"hookEventName":"PreToolUse",
#             "additionalContext":"..."}}   (the command runs unchanged)
#   allow   exit 0 with no output
#
# Why the rewrite carries NO permissionDecision. Until 2026-10-20 both rewrite
# branches answered {"decision":"allow","updatedInput":…}. Claude Code rejects
# that object ("top-level decision is the legacy approve|block field") and runs
# the ORIGINAL command: 41 rejections in transcripts, 2026-09-22 → 10-19, so the
# unset-variable delete guard and the force-push rewrite had protected nothing.
# The fix is not "allow": "allow" also bypasses permission prompts and deny
# rules, so a guard that only meant to defuse a command would have granted it.
# updatedInput WITHOUT a decision rewrites and leaves the normal permission
# flow in place — verified live on 2.1.283: an unallowed `touch` rewritten this
# way was still denied, an allowed one ran in its rewritten form.
#
# No `set -e`, on purpose. A failed test inside a check must not abort the
# guard: rm_scan_flags used to return the status of its last `[[ … ]] && …`,
# so any statement whose last option token lacked an `f` killed the hook with
# exit 1 — a non-blocking error to Claude Code, which then ran the command with
# every later check (force push, DROP, pkill) skipped. Ten of 20,111 real
# commands replayed on 2026-10-20 crashed it that way. settings-hooks.json now
# sets "onFailure": "block": on Claude Code 2.1.295+ a crash or a timeout refuses
# the call instead, safe or not, so this rule stands; older CLIs still fail open.

set -uo pipefail

# Read JSON input from stdin
INPUT=$(cat)

TOOL_NAME=$(printf '%s' "$INPUT" | jq -r '.tool_name // ""' 2>/dev/null || echo "")

# Only act on Bash tool
if [[ "$TOOL_NAME" != "Bash" ]]; then
  exit 0
fi

COMMAND=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null || echo "")
TOOL_INPUT=$(printf '%s' "$INPUT" | jq -c '.tool_input // {}' 2>/dev/null || echo '{}')
# shellcheck disable=SC2034  # read by lib/force-push-walk.sh
HOOK_CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // ""' 2>/dev/null || echo "")

if [[ -z "$COMMAND" ]]; then
  exit 0
fi

# ─── Output helpers ───────────────────────────────────────────────────
# Every value reaches jq on its stdin, never as an argument. Linux will not
# start a program when any one argument is over 128 KiB (MAX_ARG_STRLEN,
# 131,072 bytes), and every deny reason quotes the command. Until 2026-11-26
# the helpers passed it with --arg and --argjson, so on a longer command jq
# never ran ("Argument list too long"): the hook printed nothing, exited 0, and
# Claude Code ran the call, a block-on-failure setting included, since exit 0
# is no failure. Probed that day with a quoted heredoc of harmless lines and
# then a delete of the home directory: refused at 122,924 and 129,098 bytes,
# run at 131,107, 133,165, 143,406 and 266,298. Both rewrites failed the same
# way, and ran the original command.
#
# GD_CMD is the command as a reason quotes it: its first GD_CMD_MAX characters
# and a marker, since 140 KB of heredoc tells the reader nothing. Every reason
# quotes it after its first sentence, which friction-rank.py groups refusals
# by, so those sentences are unchanged.
GD_CMD_MAX=2000
GD_CMD=$COMMAND
if (( ${#COMMAND} > GD_CMD_MAX )); then
  GD_CMD="${COMMAND:0:GD_CMD_MAX}… [command clipped: the first $GD_CMD_MAX of ${#COMMAND} characters are shown]"
fi
# gd_deny <reason> — refuse the call; Claude sees the reason. When jq cannot
# write it, a fixed refusal goes out instead: a deny never turns into silence.
gd_deny() {
  local out
  out=$(printf '%s' "$1" | jq -Rs \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:.}}' 2>/dev/null) \
    && [[ -n "$out" ]] \
    || out='{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"pre-tool-guardian refused this command and could not write why: jq failed. Check it, then run it in your own terminal."}}'
  printf '%s\n' "$out"
  exit 0
}
# gd_rewrite <new-command> <why> — run a safer command in place of the
# proposed one. The rest of tool_input (description, timeout,
# run_in_background) is carried over; updatedInput replaces the whole input.
# A pending wait warning (below) rides along: the rewritten command still waits.
# jq reads tool_input (one line: jq -c escapes every newline), the why (its
# newlines made spaces), then the command, lines and all. When it cannot write
# the rewrite the call is refused, so the original never runs in its place.
gd_rewrite() {
  local why="$2${GD_WAIT_WARN:+ $GD_WAIT_WARN}" out
  why=${why//$'\n'/ }
  out=$(printf '%s\n%s\n%s' "$TOOL_INPUT" "$why" "$1" | jq -Rs \
    '(split("\n")[:2]) as [$ti, $why]
     | {hookSpecificOutput:{hookEventName:"PreToolUse",
        updatedInput:(($ti | fromjson) + {command:ltrimstr($ti + "\n" + $why + "\n")}),additionalContext:$why}}' 2>/dev/null) \
    && [[ -n "$out" ]] \
    || gd_deny "pre-tool-guardian could not write the safer form of this command, so it refuses it rather than run the original. Command: $GD_CMD"
  printf '%s\n' "$out"
  exit 0
}
# gd_warn <text> — let the command run unchanged, and tell the model why it
# should not have been written this way. No permissionDecision, for the same
# reason a rewrite carries none: "allow" would also skip permission prompts.
gd_warn() {
  printf '%s' "$1" | jq -Rs '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:.}}'
  exit 0
}

# ─── Subagent waits that outlive the prompt cache ─────────────────────
#
# By default a subagent's prompt cache lives 5 minutes. A foreground Bash call
# that blocks longer than that makes the next turn re-create the agent's whole
# context at the cache-write rate. Measured 2026-10-22 over 316 Workflow runs
# (3,646 agents, 218,031 API calls on the author's machine): 1,459 cache misses
# followed a gap over 300 s, they carried 548M of the 1,342M cache-write tokens
# (41%), and 82.5% of that cost followed a Bash sleep, poll or wait — typically
# `until …; do sleep N; done`.
#
# Warn-only, and four gates decide whether the shape is read at all:
#   - agent_id in the hook input. Claude Code 2.1.283 sets it only inside a
#     subagent ("Absent for the main thread, even in --agent sessions"). The
#     main thread is out of scope. A subscriber's main thread, outside overage,
#     writes its cache at the 1-hour tier (a server-flagged allowlist that
#     names `repl_main_thread*` by default; an API-key session gets 5 minutes
#     there too): every cache write in the 40 newest main-thread transcripts on
#     the author's machine is 1h, every one in the 40 newest Workflow
#     subagents 5m.
#   - the subagent TTL is not 1 hour in the environment. 2.1.283 picks it in
#     this order: FORCE_PROMPT_CACHING_5M (5m), CLAUDE_CODE_SUBAGENT_PROMPT_
#     CACHE_TTL ("5m" or "1h"), the `subagentPromptCacheTtl` setting, the
#     agent's frontmatter `ttl`, ENABLE_PROMPT_CACHING_1H (on Bedrock also
#     ENABLE_PROMPT_CACHING_1H_BEDROCK), else 5m. The hook inherits and reads
#     the environment variables; the setting and the frontmatter live in files
#     it does not open, so a TTL set there is not seen — which is why the
#     warning says "by default".
#   - not run_in_background: a backgrounded call blocks nothing.
#   - the call's effective timeout exceeds 270 s. Claude Code stops waiting
#     for a foreground call at min(timeout || BASH_DEFAULT_TIMEOUT_MS ||
#     120000, max(BASH_MAX_TIMEOUT_MS || 600000, default)) and moves it to the
#     background, so the turn resumes by then; a call capped at or under 270 s
#     cannot outlive the cache whatever it runs. Measured over the 224,870
#     Bash calls of Workflow subagents on the author's machine (2026-09-22 →
#     10-23): 1,653 of the 1,655 foreground calls that ran past 270 s had an
#     effective timeout over 270 s, and only 14,043 of the 223,441 foreground
#     calls (6.3%) did, so this gate alone spares most of them.
# 270 s, not 300: the model's own turn before and after the call also spends
# the TTL.
#
# The awk below reads the command as shell (quotes, heredoc bodies, comments,
# statements, nested `bash -c` / `ssh host` / `eval` scripts) and estimates the
# longest it can block. What it counts as a wait:
#   - `sleep` summed over its arguments (GNU suffixes s/m/h/d, `infinity`),
#     and over consecutive statements: `sleep 200; sleep 200` is 400 s
#   - an until/while loop around a sleep: unbounded, so the call's timeout
#   - a for loop around a sleep, when its count is literal (`$(seq 1 19)`,
#     `{1..19}`, a word list): count × sleep. An unknown count (a glob, a
#     `$var`), or a sleep whose length is not literal, stays silent.
#   - `tail -f`, `watch`, `inotifywait`, `pidwait`, `gh run watch`,
#     `gh pr checks --watch`, `docker wait`, `kubectl wait` (its --timeout,
#     default 30 s; a negative one waits without end, one it cannot read is
#     not counted)
#   - `python3 -c` around `time.sleep(N)`: N summed, or unbounded inside a
#     `while`. A `python3 - <<EOF` script is not read: there a sleep is far
#     more often a rate limit inside real work than a wait.
#   - `wait` on a backgrounded job that is itself one of the above. A bare
#     `wait` on ordinary work is not: of the 103 calls in that corpus that ran
#     the `wait` builtin with a timeout over 270 s, 5 ran past 270 s, and a
#     warning that is moot 95% of the time is one an agent learns to skip.
# A `timeout N` prefix bounds what it wraps, so `timeout 260 bash -c 'until
# …'` is silent, as are the two slices the warning recommends: a for loop of
# 26 × sleep 10, and a call whose own timeout is 270000 or less. A job sent to
# the background with `&`, `( … ) &` or `{ …; } &` blocks nothing unless a
# later `wait` collects it. Not seen: a script file the command runs, which
# may poll (`bash poll.sh`), and long foreground WORK (tests, builds) — this
# rule is about waiting, 82.5% of the measured long-gap miss cost.
#
# The remedy it gives for a job that outlasts the agent is nohup, not
# run_in_background: 2.1.283 terminates a synchronous subagent's
# run_in_background jobs when it gives its final response.
#
# Replayed 16,043 of those 224,870 calls through the old and the new hook —
# every foreground one with an effective timeout over 270 s (14,043) plus
# 2,000 sampled from the rest, each with its agent_id, timeout and
# run_in_background, no TTL variable set: nothing crashed and no deny or
# rewrite changed. It warned before 1,313 of the 1,655 foreground calls that
# ran past 270 s. Of the 342 it did not: 2 set no timeout, so the gate skips
# them; 241 run no wait loop (scripts, test gates, builds, data jobs); 41 are
# `systemd-run --wait`; 21 run a wait script by name; 19 loop with no sleep
# (paced by `read -t` or an ssh timeout); 17 are `python3 - <<EOF` polls; and
# 1 nests a double-quoted string inside a `$( … )` inside a double-quoted
# string, which the awk does not follow. 1,313 of its 2,142 warnings preceded
# such a call; 731 of the other 829 are until/while polls that finished early.
# The 2,000 sampled calls check that the gate and the other verdicts hold;
# they are not a false-positive rate, since the gate stops every one of them
# before the awk.
#
# Prints nothing, or "<seconds><TAB><what waits>".
# A single-quoted literal, not a heredoc: `read -d ''` takes a heredoc one
# byte at a time, which as a heredoc cost every Bash call ~6 ms (median, on a
# loaded 32-core host) before any gate ran. So the program carries no single
# quote; awk spells it "\047".
# shellcheck disable=SC2016  # awk source: its $fields are awk's, not the shell's
GD_WAIT_AWK='function min2(a, b) { return (a < b) ? a : b }
# dur(s) — seconds in a sleep/timeout duration; -1 when it is not a literal
function dur(s,   u, v) {
  if (s == "infinity" || s == "inf") return INF
  if (s !~ /^([0-9]+\.?[0-9]*|\.[0-9]+)[smhd]?$/) return -1
  u = substr(s, length(s), 1)
  if (u ~ /[smhd]/) v = substr(s, 1, length(s) - 1) + 0
  else { v = s + 0; u = "s" }
  if (u == "m") v *= 60
  else if (u == "h") v *= 3600
  else if (u == "d") v *= 86400
  return v
}
function tstart(d) { if (!INTOK[d]) { INTOK[d] = 1; TOKV[d] = "" } }
function tflush(d) { if (INTOK[d]) { NT[d]++; TV[d, NT[d]] = TOKV[d]; INTOK[d] = 0 } }
function seg(d, sep) { tflush(d); if (NT[d] > 0) stmt(d, sep); NT[d] = 0 }
# add_wait — record that a statement at depth d blocks `secs` (INF: until
# something else ends it; -1: a sleep of unknown length). Inside a loop it
# describes one iteration; a background job only matters to a later `wait`.
function add_wait(d, secs, label, bg,   f, a) {
  if (secs == 0) return
  if (bg) { if (secs > BGMAX[d]) { BGMAX[d] = secs; BGL[d] = label }; return }
  f = LD[d]
  if (f > 0) {
    LS[d, f] = 1
    if (secs >= INF) LU[d, f] = 1
    else if (secs < 0) LX[d, f] = 1
    else LSUM[d, f] += secs
    if (LL[d, f] == "") LL[d, f] = label
    return
  }
  if (secs < 0) return
  a = min2(secs, BOUND[d])
  TOT[d] += a
  if (a > LBLS[d]) { LBLS[d] = a; LBL[d] = label }
}
function push_loop(d, kind,   f) {
  f = ++LD[d]
  LK[d, f] = kind; LS[d, f] = 0; LU[d, f] = 0; LX[d, f] = 0; LSUM[d, f] = 0; LC[d, f] = -1; LL[d, f] = ""
}
function close_loop(d, bg,   f, r, lbl) {
  f = LD[d]
  if (f < 1) return
  LD[d]--
  r = 0; lbl = ""
  if (LK[d, f] == "uw") { if (LS[d, f]) { r = INF; lbl = "an until/while loop around " LL[d, f] } }
  else if (LU[d, f]) { r = INF; lbl = "a for loop around " LL[d, f] }
  else if (LS[d, f]) {
    if (LC[d, f] >= 0 && !LX[d, f]) { r = LC[d, f] * LSUM[d, f]; lbl = "a for loop of " LC[d, f] " x " LL[d, f] }
    else r = -1
  }
  add_wait(d, r, lbl, bg)
}
# The count of a for header: a literal word list or {A..B}. `in $(seq …)` is cut at
# the `$(`, so the count is taken from the seq statement that follows.
function for_count(d, k, sep,   n, j, c, v, m, a, b) {
  n = NT[d]
  if (TV[d, k + 2] != "in") return
  c = 0
  for (j = k + 3; j <= n; j++) {
    v = TV[d, j]
    if (v ~ /^\{-?[0-9]+\.\.-?[0-9]+\}$/) {
      gsub(/[{}]/, "", v); m = index(v, ".."); a = substr(v, 1, m - 1) + 0; b = substr(v, m + 2) + 0
      c += ((b >= a) ? b - a : a - b) + 1
    } else if (v ~ /[*?[$`]/) return
    else c++
  }
  if (sep == "$(" || sep == "`") { if (c == 0) FORPEND[d] = LD[d]; return }
  LC[d, LD[d]] = c
}
function seq_count(d, k, n,   j, v, m, x1, x2, x3) {
  m = 0
  for (j = k + 1; j <= n; j++) {
    v = TV[d, j]
    if (v == "-s" || v == "-f") { j++; continue }
    if (v ~ /^-[a-z]/) continue
    if (v !~ /^-?[0-9]+(\.[0-9]+)?$/) return -1
    m++
    if (m == 1) x1 = v + 0; else if (m == 2) x2 = v + 0; else x3 = v + 0
  }
  if (m == 1) return (x1 > 0) ? int(x1) : 0
  if (m == 2) return (x2 >= x1) ? int(x2 - x1) + 1 : 0
  if (m == 3 && x2 != 0) return ((x3 - x1) / x2 >= 0) ? int((x3 - x1) / x2) + 1 : 0
  return -1
}
function open_group(d, type,   g) {
  g = ++GD[d]
  GT[d, g] = type; GTOT[d, g] = TOT[d]; GLS[d, g] = LBLS[d]; GLB[d, g] = LBL[d]
}
# A group closed with `) &` or `} &` runs in the background: what it waited
# for moves to the background tally, where only a later `wait` collects it.
function close_group(d, bg,   g, delta) {
  g = GD[d]
  if (g < 1) return
  GD[d]--
  if (!bg || GT[d, g] == "S") return
  delta = TOT[d] - GTOT[d, g]
  if (delta > BGMAX[d]) { BGMAX[d] = delta; BGL[d] = LBL[d] }
  TOT[d] = GTOT[d, g]; LBLS[d] = GLS[d, g]; LBL[d] = GLB[d, g]
}
function is_shell(w) { return (w == "bash" || w == "sh" || w == "zsh" || w == "dash" || w == "ksh") }
function stmt(d, sep,   n, k, w, bg) {
  n = NT[d]; bg = (sep == "&"); k = 1
  while (k <= n && TV[d, k] ~ /^[A-Za-z_][A-Za-z0-9_]*=/) k++
  while (k <= n) {
    w = TV[d, k]
    if (w == "until" || w == "while") { push_loop(d, "uw"); k++; continue }
    if (w == "for" || w == "select") { push_loop(d, "for"); for_count(d, k, sep); return }
    if (w == "done") { close_loop(d, bg); FORPEND[d] = 0; return }
    if (w == "{") { open_group(d, "B"); k++; continue }
    if (w == "}") { close_group(d, bg); return }
    if (w == "do" || w == "then" || w == "else" || w == "elif" || w == "if" || w == "!" || w == "fi" || w == "esac" || w == "time" || w == "-p") { k++; continue }
    break
  }
  if (k > n) { FORPEND[d] = 0; return }
  if (FORPEND[d] > 0) {
    if (TV[d, k] == "seq") LC[d, FORPEND[d]] = seq_count(d, k, n)
    FORPEND[d] = 0
  }
  run_cmd(d, k, n, bg)
}
# run_cmd — one simple command from word k: its prefixes (a `timeout N`
# bounds the rest), then what it waits on, if anything.
function run_cmd(d, k, n, bg,   sb, w, v, j, secs, unk, r, eb, script) {
  sb = INF
  while (k <= n) {
    w = TV[d, k]; sub(/.*\//, "", w)
    if (w == "timeout") {
      for (k++; k <= n; k++) {
        v = TV[d, k]
        if (v == "-s" || v == "-k" || v == "--signal" || v == "--kill-after") { k++; continue }
        if (v ~ /^-/) continue
        break
      }
      secs = dur(TV[d, k])
      if (secs > 0 && secs < sb) sb = secs
      k++; continue
    }
    if (w in PFX) {
      for (k++; k <= n; k++) {
        v = TV[d, k]
        if (index(PFX[w], " " v " ") > 0) { k++; continue }
        if (v ~ /^-/ || v ~ /^[A-Za-z_][A-Za-z0-9_]*=/) continue
        break
      }
      continue
    }
    break
  }
  if (k > n) return
  w = TV[d, k]; sub(/.*\//, "", w)
  eb = min2(BOUND[d], sb)
  if (w == "sleep") {
    secs = 0; unk = 0
    for (j = k + 1; j <= n; j++) {
      v = TV[d, j]
      if (v ~ /^[0-9]*[<>]/ || v ~ /^&>/) break
      r = dur(v)
      if (r < 0) unk = 1; else secs += r
    }
    if (unk || k == n) secs = -1; else secs = min2(secs, sb)
    add_wait(d, secs, "sleep " TV[d, k + 1], bg)
    return
  }
  if (w == "wait") {
    if (BGMAX[d] > 0) add_wait(d, min2(BGMAX[d], sb), "wait for " BGL[d], bg)
    BGMAX[d] = 0
    return
  }
  if (w == "tail") {
    for (j = k + 1; j <= n; j++) {
      v = TV[d, j]
      if (v == "--") break
      if (v ~ /^--follow/ || (v ~ /^-[A-Za-z0-9]+$/ && v ~ /[fF]/)) { add_wait(d, sb, "tail -f", bg); return }
    }
    return
  }
  if (w == "watch" || w == "pidwait") { add_wait(d, sb, w, bg); return }
  if (w == "inotifywait") {
    secs = INF
    for (j = k + 1; j <= n; j++) {
      v = TV[d, j]
      if (v == "-t" || v == "--timeout") { r = dur(TV[d, j + 1]); if (r > 0) secs = r; j++ }
      else if (v ~ /^--timeout=/) { r = dur(substr(v, 11)); if (r > 0) secs = r }
    }
    add_wait(d, min2(secs, sb), "inotifywait", bg)
    return
  }
  if (w == "gh") {
    if (TV[d, k + 1] == "run" && TV[d, k + 2] == "watch") { add_wait(d, sb, "gh run watch", bg); return }
    if (TV[d, k + 1] == "pr" && TV[d, k + 2] == "checks")
      for (j = k + 3; j <= n; j++) if (TV[d, j] == "--watch") { add_wait(d, sb, "gh pr checks --watch", bg); return }
    return
  }
  if (w == "docker") { if (TV[d, k + 1] == "wait") add_wait(d, sb, "docker wait", bg); return }
  if (w == "kubectl") {
    if (TV[d, k + 1] != "wait") return
    secs = 30
    for (j = k + 2; j <= n; j++) {
      v = TV[d, j]
      if (v == "--timeout") { v = "--timeout=" TV[d, j + 1]; j++ }
      if (v ~ /^--timeout=/) { v = substr(v, 11); secs = (v ~ /^-/) ? INF : dur(v) }
    }
    add_wait(d, min2(secs, sb), "kubectl wait", bg)
    return
  }
  if (is_shell(w)) {
    for (j = k + 1; j <= n; j++) {
      v = TV[d, j]
      if (v == "-c" || (v ~ /^-[A-Za-z]+$/ && index(v, "c") > 0)) {
        if (j < n) { r = scan(TV[d, j + 1], eb, d + 1); add_wait(d, r, LBL[d + 1], bg) }
        return
      }
      if (v == "-o" || v == "+o" || v == "-O" || v == "+O" || v == "--rcfile" || v == "--init-file") { j++; continue }
      if (v == "-s") break
      if (v ~ /^[-+]/ || v ~ /^[0-9]*[<>]/) continue
      return
    }
    STDIN_SH[d] = 1; SHB[d] = sb; SHBG[d] = bg
    return
  }
  if (w == "ssh") {
    for (j = k + 1; j <= n; j++) {
      v = TV[d, j]
      if (v ~ /^-[BbcDEeFIiJLlmOopQRSWw]$/) { j++; continue }
      if (v ~ /^-/) continue
      break
    }
    if (j > n) return
    if (j == n) { STDIN_SH[d] = 1; SHB[d] = sb; SHBG[d] = bg; return }
    script = TV[d, j + 1]
    for (j += 2; j <= n; j++) script = script " " TV[d, j]
    r = scan(script, eb, d + 1); add_wait(d, r, LBL[d + 1], bg)
    return
  }
  if (w == "eval" && k < n) {
    script = TV[d, k + 1]
    for (j = k + 2; j <= n; j++) script = script " " TV[d, j]
    r = scan(script, eb, d + 1); add_wait(d, r, LBL[d + 1], bg)
    return
  }
  # `python3 -c "import time; time.sleep(575)"` is sleep 575 spelled so that
  # the block Claude Code itself puts on a leading `sleep` does not see it.
  if (w ~ /^python[0-9.]*$/) {
    for (j = k + 1; j < n; j++) if (TV[d, j] == "-c" || TV[d, j] ~ /^-[A-Za-z]*c$/) break
    if (j >= n || TV[d, j + 1] !~ /time\.sleep\(/) return
    script = TV[d, j + 1]
    if (script ~ /(^|[^A-Za-z0-9_])while[ \t(]/) { add_wait(d, sb, "a python while loop around time.sleep", bg); return }
    secs = 0
    while (match(script, /time\.sleep\([^)]*\)/)) {
      v = substr(script, RSTART + 11, RLENGTH - 12); gsub(/[ \t]/, "", v)
      r = dur(v)
      if (r < 0 || v ~ /[smhd]$/) return
      secs += r
      script = substr(script, RSTART + RLENGTH)
    }
    add_wait(d, min2(secs, sb), "python time.sleep", bg)
  }
}
# scan — the longest `text` can block, capped at `bound`. Depth d keeps the
# tokens and loops of each nested script apart from those of its caller.
function scan(text, bound, d,   n, i, c, q, nc, e, line, h, qc, word, strip, j, r, body) {
  if (d > 6) return 0
  NT[d] = 0; INTOK[d] = 0; TOKV[d] = ""; LD[d] = 0; GD[d] = 0; TOT[d] = 0; BGMAX[d] = 0; BGL[d] = ""
  LBL[d] = ""; LBLS[d] = 0; HDN[d] = 0; STDIN_SH[d] = 0; FORPEND[d] = 0; BOUND[d] = bound
  n = length(text); i = 1; q = ""
  while (i <= n) {
    c = substr(text, i, 1)
    if (q == "\047") {
      e = index(substr(text, i), "\047")
      if (e == 0) { TOKV[d] = TOKV[d] substr(text, i); i = n + 1; continue }
      TOKV[d] = TOKV[d] substr(text, i, e - 1); i += e; q = ""; continue
    }
    if (q == "\"") {
      if (c == "\\" && i < n) {
        nc = substr(text, i + 1, 1)
        if (nc == "\\" || nc == "\"" || nc == "$" || nc == "`") { TOKV[d] = TOKV[d] nc; i += 2; continue }
      }
      if (c == "\"") q = ""; else TOKV[d] = TOKV[d] c
      i++; continue
    }
    if (c == "\\") {
      if (i < n && substr(text, i + 1, 1) == "\n") { i += 2; continue }
      tstart(d); if (i < n) TOKV[d] = TOKV[d] substr(text, i + 1, 1); i += 2; continue
    }
    if (c == "\047" || c == "\"") { tstart(d); q = c; i++; continue }
    if (c == " " || c == "\t") { tflush(d); i++; continue }
    if (c == "#" && !INTOK[d]) { while (i <= n && substr(text, i, 1) != "\n") i++; continue }
    if (c == "\n") {
      seg(d, "\n"); i++
      for (h = 1; h <= HDN[d]; h++) {
        body = ""
        while (i <= n) {
          e = index(substr(text, i), "\n")
          line = (e > 0) ? substr(text, i, e - 1) : substr(text, i)
          i = (e > 0) ? i + e : n + 1
          if (HDS[d, h]) sub(/^\t+/, "", line)
          if (line == HDD[d, h]) break
          body = body line "\n"
        }
        # A heredoc is data unless a shell or ssh on its line reads its
        # script from stdin.
        if (STDIN_SH[d]) { r = scan(body, min2(bound, SHB[d]), d + 1); add_wait(d, r, LBL[d + 1], SHBG[d]) }
      }
      HDN[d] = 0; STDIN_SH[d] = 0
      continue
    }
    if (c == "$" && substr(text, i + 1, 1) == "(") { seg(d, "$("); open_group(d, "S"); i += 2; continue }
    if (c == "(") { seg(d, "("); open_group(d, "G"); i++; continue }
    if (c == ")") {
      seg(d, ")")
      j = i + 1
      while (substr(text, j, 1) == " " || substr(text, j, 1) == "\t") j++
      close_group(d, substr(text, j, 1) == "&" && substr(text, j + 1, 1) != "&" && substr(text, j + 1, 1) != ">")
      i++; continue
    }
    if (c == ";" || c == "`") { seg(d, c); i++; continue }
    if (c == "|") { seg(d, "|"); i++; if (substr(text, i, 1) == "|" || substr(text, i, 1) == "&") i++; continue }
    if (c == "&") {
      if ((i > 1 && (substr(text, i - 1, 1) == ">" || substr(text, i - 1, 1) == "<")) || substr(text, i + 1, 1) == ">") {
        tstart(d); TOKV[d] = TOKV[d] c; i++; continue
      }
      if (substr(text, i + 1, 1) == "&") { seg(d, "&&"); i += 2; continue }
      seg(d, "&"); i++; continue
    }
    # A here-string `<<<` lands here too, harmlessly: its `<<` reads as a
    # heredoc with no word, which registers nothing, and the third < starts a
    # plain word. Excluding `<<<` at its first < instead, as this test did,
    # sent the SECOND < here, where it took the opening quote of the next word
    # and every later quote was misread: 7 long polls of the replay (6 of
    # them on `gh pr checks`) went unseen that way.
    if (c == "<" && substr(text, i, 2) == "<<") {
      tflush(d); j = i + 2; strip = 0
      if (substr(text, j, 1) == "-") { strip = 1; j++ }
      while (substr(text, j, 1) == " " || substr(text, j, 1) == "\t") j++
      qc = substr(text, j, 1); if (qc == "\047" || qc == "\"") j++; else qc = ""
      word = ""
      while (j <= n && substr(text, j, 1) ~ /[A-Za-z0-9_]/) { word = word substr(text, j, 1); j++ }
      if (qc != "" && substr(text, j, 1) == qc) j++
      if (word != "") { HDN[d]++; HDD[d, HDN[d]] = word; HDS[d, HDN[d]] = strip }
      i = j; continue
    }
    tstart(d); TOKV[d] = TOKV[d] c; i++
  }
  seg(d, "")
  return min2(TOT[d], bound)
}
BEGIN {
  INF = 1e12
  # Prefixes that run the rest of the statement in the foreground, and which
  # of their options take a separate value.
  PFX["nice"] = " -n --adjustment "; PFX["nohup"] = " "; PFX["command"] = " "
  PFX["sudo"] = " -u -g -h -p -C -D -r -t -U "; PFX["env"] = " -u -C -S --unset --chdir "
  PFX["stdbuf"] = " -i -o -e "; PFX["ionice"] = " -c -n -p -P -u "; PFX["exec"] = " -a "
}
{ cmd = (NR == 1) ? $0 : cmd RS $0 }
END {
  limit = ENVIRON["GD_WAIT_LIMIT"] + 0
  r = scan(cmd, ENVIRON["GD_WAIT_BOUND_MS"] / 1000, 1)
  if (r > limit) printf "%d\t%s\n", r, ((LBLS[1] > limit) ? LBL[1] : "several waits in one call")
}'

GD_WAIT_LIMIT_S=270
GD_WAIT_WARN=""
# gd_ms <value> <fallback> — sets GD_MS to <value> as a positive whole number
# of milliseconds, or to <fallback>. Base 10 forced: a leading zero is not octal.
gd_ms() {
  GD_MS=$2
  if [[ "$1" =~ ^0*([0-9]{1,12})(\.[0-9]*)?$ ]] && (( 10#${BASH_REMATCH[1]} > 0 )); then
    GD_MS=$((10#${BASH_REMATCH[1]}))
  fi
  return 0
}
# gd_env_true <value> — a boolean environment variable as Claude Code 2.1.283
# reads it: 1, true, yes or on, in any case. (It also trims blanks; nobody
# writes " 1", so this does not.)
gd_env_true() {
  case "$1" in 1|[Tt][Rr][Uu][Ee]|[Yy][Ee][Ss]|[Oo][Nn]) return 0 ;; esac
  return 1
}
# gd_subagent_ttl_1h — true when the environment gives a subagent's requests
# the 1-hour cache, in 2.1.283's order (see the gates above). The
# subagentPromptCacheTtl setting and an agent's frontmatter ttl sit between
# the TTL variable and ENABLE_PROMPT_CACHING_1H there and are not seen here.
gd_subagent_ttl_1h() {
  gd_env_true "${FORCE_PROMPT_CACHING_5M:-}" && return 1
  case "${CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL:-}" in 1h) return 0 ;; 5m) return 1 ;; esac
  gd_env_true "${ENABLE_PROMPT_CACHING_1H:-}" && return 0
  gd_env_true "${CLAUDE_CODE_USE_BEDROCK:-}" && gd_env_true "${ENABLE_PROMPT_CACHING_1H_BEDROCK:-}" && return 0
  return 1
}
# gd_wait_check — sets GD_WAIT_WARN when this call is a subagent wait that can
# outlive the cache. Cheapest test first: the four before jq fork nothing, so
# a main-thread call and most subagent calls cost a few string matches.
# `"agent_id"` and `"timeout"` with their quotes can only be keys here — a
# quote inside a JSON string value is escaped. Every shape the awk reads
# contains one of the four words; a new shape needs its word added there too.
gd_wait_check() {
  local w bg timeout agent default max eff found tab
  [[ "$INPUT" == *'"agent_id"'* ]] || return 0
  [[ "$COMMAND" == *sleep* || "$COMMAND" == *wait* || "$COMMAND" == *tail* || "$COMMAND" == *watch* ]] || return 0
  gd_subagent_ttl_1h && return 0
  gd_ms "${BASH_DEFAULT_TIMEOUT_MS:-}" 120000; default=$GD_MS
  [[ "$INPUT" == *'"timeout"'* ]] || (( default > GD_WAIT_LIMIT_S * 1000 )) || return 0
  w=$(printf '%s' "$INPUT" | jq -r '"\(.tool_input.run_in_background // false)|\(.tool_input.timeout // "")|\(.agent_id // "")"' 2>/dev/null || true)
  bg=${w%%|*}; w=${w#*|}
  timeout=${w%%|*}; agent=${w#*|}
  [[ -n "$agent" && "$bg" != "true" ]] || return 0
  gd_ms "${BASH_MAX_TIMEOUT_MS:-}" 600000; max=$GD_MS
  (( max < default )) && max=$default
  gd_ms "$timeout" "$default"; eff=$GD_MS
  (( eff > max )) && eff=$max
  (( eff > GD_WAIT_LIMIT_S * 1000 )) || return 0
  found=$(printf '%s' "$COMMAND" | GD_WAIT_LIMIT="$GD_WAIT_LIMIT_S" GD_WAIT_BOUND_MS="$eff" \
    LC_ALL=C awk 'BEGIN { RS = "\001" } '"$GD_WAIT_AWK" 2>/dev/null || true)
  [[ -n "$found" ]] || return 0
  tab=$'\t'
  # Both slices are portable (macOS has no `timeout`), and both are silent here.
  GD_WAIT_WARN="pre-tool-guardian: this subagent call can block for up to ${found%%"$tab"*} s (${found#*"$tab"}). By default a subagent's prompt cache lives 5 minutes, so a wait past ~${GD_WAIT_LIMIT_S} s makes the next turn re-create the whole context. Wait in slices of ${GD_WAIT_LIMIT_S} s or less, then check and call again: bound the loop (for i in \$(seq 1 26); do <check> && break; sleep 10; done), or give this Bash call a timeout of ${GD_WAIT_LIMIT_S}000 or less. To outlast this agent, detach the job (nohup <job> > <log> 2>&1 &), record the log path and end; run_in_background is no detach here, since a synchronous subagent's background jobs end with its final response."
  return 0
}
gd_wait_check

# ─── Dev mode check ───────────────────────────────────────────────────
# When ~/.claude/.dev-mode exists, skip migration blocking.
# Run `devmode` to toggle. Catastrophic operations are ALWAYS blocked.
DEV_MODE=false
[[ -f "$HOME/.claude/.dev-mode" ]] && DEV_MODE=true

# ─── Database migrations ──────────────────────────────────────────────
# These require interactive confirmation or long timeouts — must run manually.
# Common ORM/migration tools that block or timeout inside Claude Code.
# (Skipped in dev mode — toggle with: devmode on/off)
if [[ "$DEV_MODE" == false ]]; then
# Strip comment-only lines AND pure-assignment lines before scanning.
# A "pure assignment" is a line whose ENTIRE content is a single variable
# assignment (optionally followed by `;`). Lines like
#   DATABASE_URL="..." alembic upgrade head
# are NOT stripped — the assignment is a prefix, and the rest is a real
# command that must be scanned. (Earlier revisions over-stripped these,
# allowing env-prefixed migrations to slip past the guardian — KL1.)
#
# Prevented false positives (still stripped):
#   - Shell comments:       # alembic upgrade head
#   - String assignments:   INPUT='{"command":"alembic upgrade",...}'
#   - Heredoc data lines:   VAR="alembic upgrade head"
SCANNABLE=$(printf '%s\n' "$COMMAND" \
  | grep -v '^\s*#' \
  | grep -vE "^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*='[^']*'[[:space:]]*;?[[:space:]]*$" \
  | grep -vE '^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*="[^"]*"[[:space:]]*;?[[:space:]]*$' \
  || true)

MIGRATION_PATTERNS=(
  "db:push"
  "db:migrate"
  "prisma migrate"
  "drizzle-kit push"
  "alembic upgrade"
  "alembic downgrade"
  "rake db:migrate"
  "rake db:rollback"
  "knex migrate:latest"
  "knex migrate:rollback"
  "sequelize db:migrate"
  "flyway migrate"
  "liquibase update"
)

for pattern in "${MIGRATION_PATTERNS[@]}"; do
  if printf '%s\n' "$SCANNABLE" | grep -qF "$pattern"; then
    gd_deny "Database migration detected: '$pattern' cannot run inside Claude Code (interactive prompts / timeouts). Run manually in your terminal: $GD_CMD"
  fi
done
fi  # end dev-mode gate

# ─── Recursive deletes (lib/rm-guard.sh) ─────────────────────────────
# The catastrophic-path rule and the unresolved-target rule live in
# lib/rm-guard.sh, and the force-push walk below in lib/force-push-walk.sh:
# together they were half of this file, which had reached 1,496 of its 1,500
# lines. Each guard fails closed. A lib that is missing, or defines no check
# (an empty or stale copy), refuses every command its rule would have read,
# naming the file, so a hook copied without its lib/ stops deletes and pushes
# rather than letting them through unchecked.
GD_LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib"
# shellcheck source=SCRIPTDIR/lib/rm-guard.sh
source "$GD_LIB/rm-guard.sh" 2>/dev/null
if declare -F gd_rm_check >/dev/null; then
  gd_rm_check
elif printf '%s\n' "$COMMAND" | grep -qE '\brm\b'; then
  gd_deny "pre-tool-guardian cannot check this delete: $GD_LIB/rm-guard.sh is missing or incomplete, so a command with an rm word is refused. Reinstall Clade (./install.sh) to restore it. Command: $GD_CMD"
fi

# ─── Force push (lib/force-push-walk.sh) ──────────────────────────────
# The walk runs when "push" survives quote removal and line continuations (git
# pu""sh is a push) or a $'…' string could spell it. Only then is its lib read.
_gd_plain=${COMMAND//\\$'\n'/}; _gd_plain=${_gd_plain//\"/}; _gd_plain=${_gd_plain//\'/}; _gd_plain=${_gd_plain//\\/}
if [[ "$_gd_plain" == *push* || "$COMMAND" == *"\$'"* ]]; then
  # shellcheck source=SCRIPTDIR/lib/force-push-walk.sh
  source "$GD_LIB/force-push-walk.sh" 2>/dev/null
  declare -F gd_push_check >/dev/null \
    || gd_deny "pre-tool-guardian cannot check this push: $GD_LIB/force-push-walk.sh is missing or incomplete, so a command that may push is refused. Reinstall Clade (./install.sh) to restore it. Command: $GD_CMD"
  gd_push_check
fi

# ─── SQL DROP DATABASE / DROP TABLE ──────────────────────────────────
# These are irreversible. Redirect to manual execution.
if printf '%s\n' "$COMMAND" | grep -qiE '\bDROP[[:space:]]+(DATABASE|TABLE|SCHEMA)\b'; then
  gd_deny "SQL DROP statement blocked. Irreversible operation must be run manually in your terminal after review. Command: $GD_CMD"
fi

# ─── Self-killing pkill -f ───────────────────────────────────────────
# `pkill -f PAT` matches full command lines, including that of the shell that
# launched it: an ssh or `bash -c` one-liner, and the Bash tool's own shell, which
# carries the whole command. That shell dies (exit 255/144) and everything after
# the pkill is lost, which reads as a remote or tool failure. Refused when work
# would be lost: a wrapper, a second occurrence of PAT, or a statement after the
# pkill (Lane D, 30 days to 2026-11-09: exit 144 in 14 main-thread sessions, and
# every pkill -f sampled from them was `pkill -f PAT; more`). A bare
# `pkill -f name`, a `|| true` tail and a `[n]ame` pattern pass: a guard that
# fires on those is one you learn to ignore. `pkill` must sit at a command
# position: matching it anywhere refused this guard's own commit message.
if printf '%s\n' "$COMMAND" | grep -qE '(^|[;&|(]|[[:space:]]&&[[:space:]]|["'"'"'])[[:space:]]*pkill[[:space:]]+(-[a-zA-Z]*f|--full)'; then
  _PK_PAT=$(printf '%s\n' "$COMMAND" \
    | sed -nE "s/.*(^|[;&|('\"]|[[:space:]])pkill[[:space:]]+(-[a-zA-Z]*f|--full)[[:space:]]+['\"]?([^'\"[:space:]]+).*/\3/p" \
    | head -1 || true)
  if [[ -n "$_PK_PAT" ]]; then
    # PAT twice, matched in bash: as a grep argument a PAT over 128 KiB never ran.
    _PK_TWICE=false
    [[ "$COMMAND" == *"$_PK_PAT"*"$_PK_PAT"* ]] && _PK_TWICE=true
    _PK_WRAPPED=false
    printf '%s\n' "$COMMAND" | grep -qE '(^|[[:space:]])(ssh|bash[[:space:]]+-c|sh[[:space:]]+-c)([[:space:]]|$)' \
      && _PK_WRAPPED=true
    # What follows the last pkill, quoted text and a `|| true` tail removed.
    # Cut as "all before the last pkill" and the rest: ${COMMAND##*pkill} is
    # quadratic in what follows it, 40 s on 286 KB, past the hook's 5 s timeout.
    _PK_PRE=${COMMAND%pkill*}
    _PK_AFTER=$(printf '%s' "${COMMAND:${#_PK_PRE}+5}" | tr '\n' ';' | sed -E "s/\"[^\"]*\"//g; s/'[^']*'//g; s/[|][|][[:space:]]*(true|:)[[:space:];]*\$//")
    _PK_RE='(;|&&|[|][|])[[:space:]]*[^[:space:];&|]'
    [[ "$_PK_PAT" != *'['* && "$_PK_AFTER" =~ $_PK_RE ]] && _PK_WRAPPED=true
    if [[ "$_PK_TWICE" == true || "$_PK_WRAPPED" == true ]]; then
      gd_deny "pkill -f ${_PK_PAT} will match the command line of the shell running it, so this kills its own launcher (exit 255/144) and everything after it never runs. Fixes: use the bracket trick, pkill -f \"[n]ame\", whose regex cannot match its own text; or run the pkill as its own call, or from a script file; and anchor the pattern (\"name\\.py --flag\"). Command: $GD_CMD"
    fi
  fi
fi

# ─── Allow everything else ───────────────────────────────────────────
# A subagent wait that outlives the cache runs, with the warning attached.
[[ -n "$GD_WAIT_WARN" ]] && gd_warn "$GD_WAIT_WARN"
exit 0
