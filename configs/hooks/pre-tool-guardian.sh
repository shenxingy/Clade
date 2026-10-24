#!/usr/bin/env bash
# pre-tool-guardian.sh — Block dangerous Bash commands before they execute
#
# Triggered: PreToolUse (matcher: Bash)
# Purpose:   Auto-block operations that either:
#   1. Timeout inside Claude Code (database migrations)
#   2. Are catastrophically destructive (rm -rf /, DROP DATABASE)
#   3. Could corrupt parallel agent sessions (force push to main)
# and warns, never blocks, when:
#   4. A subagent's foreground wait would outlive its prompt cache (5 minutes
#      unless the environment sets the subagent TTL to 1 hour)
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
# commands replayed on 2026-10-20 crashed it that way.

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
HOOK_CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // ""' 2>/dev/null || echo "")

if [[ -z "$COMMAND" ]]; then
  exit 0
fi

# ─── Output helpers ───────────────────────────────────────────────────
# gd_deny <reason> — refuse the call; Claude sees the reason.
gd_deny() {
  jq -n --arg r "$1" \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
  exit 0
}
# gd_rewrite <new-command> <why> — run a safer command in place of the
# proposed one. The rest of tool_input (description, timeout,
# run_in_background) is carried over; updatedInput replaces the whole input.
# A pending wait warning (below) rides along: the rewritten command still waits.
gd_rewrite() {
  jq -n --argjson ti "$TOOL_INPUT" --arg c "$1" --arg why "$2${GD_WAIT_WARN:+ $GD_WAIT_WARN}" \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",updatedInput:($ti + {command:$c}),additionalContext:$why}}'
  exit 0
}
# gd_warn <text> — let the command run unchanged, and tell the model why it
# should not have been written this way. No permissionDecision, for the same
# reason a rewrite carries none: "allow" would also skip permission prompts.
gd_warn() {
  jq -n --arg c "$1" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$c}}'
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
    gd_deny "Database migration detected: '$pattern' cannot run inside Claude Code (interactive prompts / timeouts). Run manually in your terminal: $COMMAND"
  fi
done
fi  # end dev-mode gate

# ─── Catastrophic rm -rf on system/home directories ──────────────────
# Block rm with both -r and -f flags targeting /, ~, $HOME, or critical system paths.
# Handles any flag order: -rf, -fr, -r -f, -f -r, -rfi, etc.
# Root (/) matched with word-boundary-aware pattern: space+slash+(space|end|star)
# `~` needs its own anchoring, NOT the trailing \b the other alternatives use:
# \b requires a word/non-word transition, and `~` is itself a non-word char, so
# `~\b` could never match `~` or `~/...` (it only matched nonsense like `~abc`)
# — i.e. `rm -rf ~` sailed straight through. Anchor it as a home reference
# instead: start/space/`=` before it, and `/`, whitespace, or end after the
# optional ~user part. That still lets a trailing-tilde backup file through
# (`rm -rf /tmp/file~`), which is not a home reference.
DANGEROUS_TILDE='(^|[[:space:]]|=)~[a-zA-Z0-9._-]*(/|[[:space:]]|$)'
DANGEROUS_NAMED_PATHS="($DANGEROUS_TILDE|\\\$HOME\\b|(/home|/etc|/usr|/var|/sys|/proc|/boot)\\b)"
DANGEROUS_ROOT='(^|[[:space:]])/([[:space:]]|$|\*)'
# Split into individual shell statements before testing, then require ONE
# statement to satisfy every condition on its own.
#
# Per-LINE matching was too coarse in both directions:
#   - False positive: `SRC=/home/me/.claude; rm -rf /tmp/shadow-test` blocked a
#     benign temp delete because a home path shared its line. Shell one-liners
#     chain statements with ; && || far more often than they use newlines, so
#     "only look at rm lines" did not actually isolate the rm.
#   - False negative direction: the three greps ran independently over the whole
#     set of rm lines, so `rm -r a` on one line plus `rm -f /home/b` on another
#     combined into a block that neither statement earned.
# `tr` (not sed \n, which BSD sed rejects) keeps this portable to macOS.
# rm_scan_flags <statement> — sets RM_RECURSIVE / RM_FORCE from the OPTION
# tokens of an rm statement, never from its operands.
#
# The rule used to be two greps over the whole statement for `-[a-zA-Z]*r` and
# `-[a-zA-Z]*f`, so any hyphen inside a FILENAME supplied the flags. Reproduced
# 2026-09-07: `rm -f <path under /home>/.radar-write-probe` was blocked as a
# catastrophic recursive delete, with no `-r` in the command at all — the `-wr`
# of the basename matched. That is a large share of ordinary cleanup.
#
# It is the over-blocking mirror of the under-blocking fixed on 2026-09-05, and
# one root cause serves both: the guard matched command TEXT instead of
# classifying tokens. A token supplies flags only when it STARTS with `-`, and
# after a `--` nothing does. GNU rm permutes its arguments, so an option may
# legitimately follow an operand — what an operand may never do is BE one.
RM_RECURSIVE=false
RM_FORCE=false
rm_scan_flags() {
  local after tok end_opts=false
  RM_RECURSIVE=false
  RM_FORCE=false
  after=$(printf '%s' "$1" | sed -E 's/^.*\brm\b//')
  while IFS= read -r tok; do
    [[ -z "$tok" ]] && continue
    if [[ "$tok" == "--" ]]; then end_opts=true; continue; fi
    $end_opts && continue
    case "$tok" in
      --recursive|--recursive=*) RM_RECURSIVE=true ;;
      --force|--force=*)         RM_FORCE=true ;;
      --*)                       : ;;
      -?*)
        if [[ "$tok" == *r* ]]; then RM_RECURSIVE=true; fi
        if [[ "$tok" == *f* ]]; then RM_FORCE=true; fi
        ;;
    esac
  done <<< "$(printf '%s' "$after" | tr ' \t' '\n\n')"
  return 0
}

RM_STATEMENTS=$(printf '%s' "$COMMAND" | tr ';|&' '\n\n\n' | grep -E '\brm\b' || true)
CATASTROPHIC_RM=false
while IFS= read -r _stmt; do
  [[ -z "$_stmt" ]] && continue
  rm_scan_flags "$_stmt"
  $RM_RECURSIVE || continue
  $RM_FORCE || continue
  if printf '%s\n' "$_stmt" | grep -qE "$DANGEROUS_NAMED_PATHS" \
    || printf '%s\n' "$_stmt" | grep -qE "$DANGEROUS_ROOT"; then
    CATASTROPHIC_RM=true
    break
  fi
done <<< "$RM_STATEMENTS"
if [[ "$CATASTROPHIC_RM" == true ]]; then
  gd_deny "Catastrophic rm -rf blocked on system/home directory. Command: $COMMAND. If intentional, run manually in your terminal."
fi

# ─── Recursive delete on a target the guardian cannot resolve ─────────
#
# The rule above matches the TEXT of the target, which is what a human types
# and not what an agent writes. Measured 2026-09-05: a recursive delete against
# $BUILD_DIR/, "$BUILD_DIR"/, ${OUT}/, $OUT/*, $(pwd)/* or a bare glob was
# ALLOWED by both guardians while every spelled-out form was blocked.
#
# What makes it dangerous is the shell lifecycle, not the regex. Each Bash tool
# call is a fresh shell, so a variable assigned in an earlier call is unset in
# this one and the target expands to the filesystem root — the very string the
# rule above exists to stop. GNU rm's --preserve-root does not save it either,
# because the expanded argument is root-plus-star rather than root.
#
# Two answers, because the two shapes differ in whether anything can be made
# safe:
#   a name  → rewrite $NAME to ${NAME:?...}. A set variable runs unchanged; an
#             unset one aborts naming itself. A correct command pays nothing.
#   no name → refuse. $(...) and a bare glob are decided at run time and there
#             is nothing to make required.
#
# Ordering matters: this runs AFTER the catastrophic-path block, so $HOME and
# the named system paths stay blocked rather than being rewritten into a
# "required" variable that is always set.

# A delete written inside a single-quoted string is text, not a command, and
# rewriting it would corrupt the string. Count the quotes that open before the
# first rm; an odd number means we are inside one.
_pre_rm=$(printf '%s' "$COMMAND" | sed -E 's/(\brm\b).*/\1/')
_quotes=$(printf '%s' "$_pre_rm" | tr -cd "'" | wc -c | tr -d ' ')
if (( _quotes % 2 == 0 )); then
  # Shell-owned names are always set, so requiring them proves nothing. $HOME
  # is on this list and is also blocked outright above; that block wins.
  _SHELL_OWNED=" HOME PWD OLDPWD TMPDIR XDG_RUNTIME_DIR CLAUDE_PROJECT_DIR "
  _unresolved_var=""
  _refuse_reason=""

  while IFS= read -r _stmt; do
    [[ -z "$_stmt" ]] && continue
    [[ -n "$_unresolved_var" || -n "$_refuse_reason" ]] && break
    rm_scan_flags "$_stmt"
    $RM_RECURSIVE || continue
    $RM_FORCE || continue

    # Everything after the rm, minus its flags, is a candidate target.
    _after=$(printf '%s' "$_stmt" | sed -E 's/^.*\brm\b//')
    while IFS= read -r _tok; do
      [[ -z "$_tok" ]] && continue
      case "$_tok" in -*) continue ;; esac
      _bare=${_tok//\"/}

      # No name to require: the value appears at run time.
      case "$_bare" in
        *'$('*|*'`'*)
          _refuse_reason="a command substitution decides the target at run time"
          break ;;
      esac
      case "$_bare" in
        '*'|'./'*'*'|'./*'|'.'|'./')
          _refuse_reason="a bare glob resolves against whatever the working directory happens to be"
          break ;;
      esac

      # $NAME or ${NAME} at the head of the target.
      _var=$(printf '%s' "$_bare" | sed -nE 's/^\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?.*/\1/p')
      [[ -z "$_var" ]] && continue
      [[ "$_SHELL_OWNED" == *" $_var "* ]] && continue
      # Assigned in this same command, so this shell will have it.
      if printf '%s\n' "$COMMAND" | grep -qE "(^|[[:space:];&|(])(export[[:space:]]+)?${_var}="; then
        continue
      fi
      _unresolved_var="$_var"
      break
    done <<< "$(printf '%s' "$_after" | tr ' \t' '\n\n')"
  done <<< "$RM_STATEMENTS"

  if [[ -n "$_refuse_reason" ]]; then
    gd_deny "Recursive delete refused: ${_refuse_reason}. Name the directory explicitly, or run it manually after checking what it expands to. Command: $COMMAND"
  fi

  if [[ -n "$_unresolved_var" ]]; then
    _guard_msg="pre-tool-guardian: refusing a recursive delete on unset ${_unresolved_var}"
    _SAFE_RM=${COMMAND//\$\{${_unresolved_var}\}/\$\{${_unresolved_var}:?${_guard_msg}\}}
    _SAFE_RM=${_SAFE_RM//\$${_unresolved_var}/\$\{${_unresolved_var}:?${_guard_msg}\}}
    gd_rewrite "$_SAFE_RM" "pre-tool-guardian rewrote \$${_unresolved_var} to \${${_unresolved_var}:?…} in a recursive delete: each Bash call is a fresh shell, so a variable set in an earlier call is unset here and the target would expand to the filesystem root. The command runs unchanged when the variable is set."
  fi
fi


# ─── Force push ───────────────────────────────────────────────────────
# Read as shell, not as text. The old rule was "`git push` anywhere AND
# --force/-f anywhere AND main anywhere", plus a sed over the whole string.
# Replayed over the 41 commands it fired on (2026-09-22 → 10-19), had its output
# ever been accepted it would have turned 14 `--force-with-lease` into
# `--force-with-lease-with-lease`, put `--force-with-lease` on 7 `git worktree
# remove --force` / `rm -f` statements, and corrupted 2 ref names
# (`feat/verdict-c-f-split`) — and it blocked `git push origin main && rm -f x`.
#
# The awk walks the command once, as the shell parses it, and reads only a
# statement whose command is `git [global opts] push`. There a force is
# `--force`, a short-option cluster with f (-f, -uf), a `+refspec` or --mirror;
# `--force-with-lease` / `--force-if-includes` are already safe. A ref is main
# when a refspec DESTINATION (after the last `:`, minus `+`, refs/heads/ and
# heads/) is main or master, or a glob or `:` that covers them. With no
# refspec, or HEAD, @ or a ref the shell computes, the pushed branch is the
# session's current one, unless a cd that surely ran, or `git -C`, moved it.
#
# Each rule below closes a way a statement was hidden from the walk, every one
# found allowed by both guardians on 2026-10-23 by review or by a fuzz run
# against real shells:
# - `$( … )` and backticks run, quoted or not: their statements are walked, and
#   the statement around them resumes after. A backtick ends at the next
#   unescaped backtick, whatever the quotes inside it say.
# - Arithmetic, $(( )), (( )) and $[ ], is no command, and its << is a shift:
#   read as a heredoc, `"$((1 << 20))"` hid every later line.
# - A here-string <<< is one word, never a heredoc: `read -r b <<<"$(date)";
#   git push --force origin main` was allowed.
# - A heredoc delimiter is a whole word (END-OF, \EOF). The body of an unquoted
#   one expands $( … ), so it is walked like a double-quoted string; one whose
#   delimiter never comes is read as commands, fail closed.
# - `$$` is one word, so `$$'\'` is a PID and a plain string; the readings zsh
#   and bash give `$$'` and `"$$(` instead are walked too.
# - `$"…"`, bash's translated string, is the string: `$"main"` is main.
# - `main>/dev/null` is the ref main; a `case` pattern's ) closes nothing.
# A string another shell parses (bash -c, eval, ssh's remote command, su -c,
# and every heredoc and here-string once a shell reads stdin) is walked again,
# block-only, and matched as text by facts() too. Config given to git on its
# command line (-c, --config-env, GIT_CONFIG_* in front of it) that sets an
# alias able to push, even through another alias, or a push refspec able to
# force, blocks as well.
#
# Prints: none | block<TAB>main|branch|delete|mirror|config|nested
#         | rewrite<NL><new command>
# A single-quoted literal, like GD_WAIT_AWK: read from a heredoc with `read -d
# ''`, one byte at a time, it cost every Bash call about 10 ms (whole-hook
# medians of 200 paired runs, no push: 44.2 ms vs 34.5 ms). So it has no
# single quote: "\047".
# shellcheck disable=SC2016  # awk source: its $fields are awk's, not the shell's
GD_PUSH_AWK='
# ─── verdicts, and the strings walked again
function block(code) { if (blocked == "") blocked = (wd > 0) ? "nested" : code }
function add_edit(s, e, t) { if (!ed) return; ne++; es[ne] = s; ee[ne] = e; et[ne] = t }
# enqueue — a string another shell runs, walked after this one, block-only.
function enqueue(text, mode, cdf, depth) {
  if (depth > 6) return
  nq++; qt[nq] = text; qm[nq] = mode; qc[nq] = cdf; qd[nq] = depth
}
# A heredoc body or here-string is a script once any shell here reads stdin.
# cdf is 1 when the only such shell is remote (ssh), whose branch is unknown.
function note_script(text) { ns++; scr[ns] = text; if (stdin_any) enqueue(text, "", stdin_cd, wd + 1) }
function set_stdin(cdf,   s) {
  if (stdin_any && stdin_cd <= cdf) return
  stdin_any = 1; stdin_cd = cdf
  for (s = 1; s <= ns; s++) enqueue(scr[s], "", cdf, wd + 1)
}
function nested(start, stop, cdf,   s, j) {
  s = ""
  for (j = start; j <= nt; j++) s = s " " tv[j]
  if (facts(s)) block("nested")
  s = ""
  for (j = start; j <= stop; j++) s = s ((j > start) ? " " : "") tv[j]
  enqueue(s, "", cdf, wd + 1)
}
function heredoc(body, quoted, closed) {
  if (!quoted) enqueue(body, "H", cd_seen, wd + 1)
  if (!closed) { if (facts(body)) block("nested"); enqueue(body, "", cd_seen, wd + 1); return }
  note_script(body)
}
# ─── words: ts..te in the command, tv the value with quotes removed
function start_tok() { if (!in_tok) { in_tok = 1; tok_start = i; tok_val = "" } }
function flush_tok() {
  if (!in_tok) return
  nt++; ts[nt] = tok_start; te[nt] = i - 1; tv[nt] = tok_val; in_tok = 0
  # A here-string, or a word that reads as a push, may be what a shell
  # reading stdin runs (echo "git push --all -f" | bash).
  if (tok_val ~ /^[0-9]*<<</) { sub(/^[0-9]*<<</, "", tok_val); note_script(tok_val) }
  else if (tok_val ~ /[ \t\n]/ && may_push(tok_val)) note_script(tok_val)
  # case WORD in … esac: until each pattern ends with its ), that ) closes
  # nothing, and it would have closed a $( early. cc counts the open cases
  # at this level, ip is 1 while a pattern is expected.
  if (tok_val == "in" && nt == 3 && tv[1] == "case") { cc[sn]++; ip[sn] = 1; end_seg() }
  if (tok_val == "esac" && nt == 1 && cc[sn] > 0) { cc[sn]--; ip[sn] = 0 }
}
# fd_tok — the word so far is the descriptor of a redirection (2>, {fd}>).
function fd_tok(   r) {
  if (!in_tok) return 0
  r = substr(cmd, tok_start, i - tok_start)
  return (r ~ /^[0-9]+$/ || r ~ /^\{[A-Za-z_][A-Za-z0-9_]*\}$/)
}
function arith() { return sn > 0 && (sk[sn] == "A" || sk[sn] == "[") }
# may_push(t) — the test this hook runs before the walk, for one word: "push"
# once quotes, backslashes and line continuations are gone, or an ANSI-C string.
function may_push(t,   u) { u = t; gsub(/\\\n/, "", u); gsub(/[\047"\\]/, "", u); return index(u, "push") || index(t, "$\047") }
# nocd — a cd in this statement may leave the directory of what follows
# unchanged: it runs in a subshell (a pipeline element, a background job), or
# only when something before it failed, or what follows runs only when it
# failed (||). Then the branch is still the session branch.
function end_seg() { flush_tok(); if (nt > 0 && !arith()) analyze(); nt = 0; nocd = 0 }
function cmd_pos(   k) { if (in_tok) return 0; for (k = 1; k <= nt; k++) if (!is_kw(tv[k])) return 0; return 1 }
# ─── substitutions: $( ), backticks, and arithmetic $(( )), (( )), $[ ]
# open_sub sets the statement around it aside (words, the word it is part of,
# quote, cd, parentheses); close_sub analyzes what ran inside and resumes. sp
# counts ( or [ opened inside, so only its own closes it; sbt is where the
# innermost backtick around it ends.
function open_exp(c,   nc) {
  if (c == "`") { open_sub("`", 1); return 1 }
  if (c != "$") return 0
  nc = substr(cmd, i + 1, 1)
  if (nc == "(") { if (substr(cmd, i + 2, 1) == "(" && arith_end(i + 3)) open_sub("A", 3); else open_sub("$", 2); return 1 }
  if (nc == "[") { open_sub("[", 2); return 1 }
  return 0
}
function open_sub(kind, width,   k, e) {
  start_tok()
  e = (sn > 0) ? sbt[sn] : 0
  if (kind == "`") {
    e = bt_end(i + 1)
    # With one level of backslashes removed, an escaped backtick inside runs too.
    if (index(substr(cmd, i + 1, e - i - 1), "\\")) enqueue(bt_text(substr(cmd, i + 1, e - i - 1)), "", cd_seen, wd + 1)
  }
  sn++; sk[sn] = kind; sp[sn] = 0; so[sn] = i; sq[sn] = q; snt[sn] = nt; scd[sn] = cd_seen; spd[sn] = pd; sbt[sn] = e
  cc[sn] = 0; ip[sn] = 0; snocd[sn] = nocd; nocd = 0
  for (k = 1; k <= nt; k++) { stv[sn, k] = tv[k]; sts[sn, k] = ts[k]; ste[sn, k] = te[k] }
  sst[sn] = tok_start; sval[sn] = tok_val
  nt = 0; in_tok = 0; q = ""
  i += width
}
function close_sub(width,   k) {
  end_seg()
  nt = snt[sn]
  for (k = 1; k <= nt; k++) { tv[k] = stv[sn, k]; ts[k] = sts[sn, k]; te[k] = ste[sn, k] }
  in_tok = 1; tok_start = sst[sn]; tok_val = sval[sn] substr(cmd, so[sn], i + width - so[sn])
  q = sq[sn]; cd_seen = scd[sn]; pd = spd[sn]; nocd = snocd[sn]; i += width; sn--
  if (q == "H") { in_tok = 0; nt = 0 }
}
# bt_end(p) — where the backtick substitution whose text starts at p ends.
function bt_end(p,   ch) {
  while (p <= n) { ch = substr(cmd, p, 1); if (ch == "\\") { p += 2; continue }; if (ch == "`") return p; p++ }
  return n + 1
}
function bt_text(s,   o, k, ch) {
  o = ""
  for (k = 1; k <= length(s); k++) {
    ch = substr(s, k, 1)
    if (ch == "\\" && k < length(s) && index("\\`$", substr(s, k + 1, 1))) { o = o substr(s, k + 1, 1); k++; continue }
    o = o ch
  }
  return o
}
# arith_end(p) — 1 when the (( before p closes with )), so it is arithmetic;
# 0 when its first unmatched ) stands alone, a subshell, as bash reads it.
function arith_end(p,   d, ch, e) {
  d = 0
  while (p <= n) {
    ch = substr(cmd, p, 1)
    if (ch == "\\") { p += 2; continue }
    if (ch == "\047" || ch == "\"") { e = index(substr(cmd, p + 1), ch); if (!e) return 0; p += e + 1; continue }
    if (ch == "(") d++
    else if (ch == ")") { if (d == 0) return substr(cmd, p + 1, 1) == ")"; d-- }
    p++
  }
  return 0
}
# ansi() — the escape at i inside an ANSI-C string, decoded, and i moved past it.
function ansi(   ch, v, k, d, w) {
  ch = substr(cmd, i, 1)
  if (ch == "x" || ch == "u" || ch == "U") {
    w = (ch == "x") ? 2 : ((ch == "u") ? 4 : 8)
    v = 0; k = 0
    while (k < w && (d = substr(cmd, i + 1 + k, 1)) ~ /^[0-9A-Fa-f]$/) { v = v * 16 + index("0123456789abcdef", tolower(d)) - 1; k++ }
    if (k == 0) { i++; return "\\" ch }
    i += 1 + k; return (v > 0 && v < 128) ? sprintf("%c", v) : "?"
  }
  if (ch ~ /^[0-7]$/) {
    v = 0; k = 0
    while (k < 3 && (d = substr(cmd, i + k, 1)) ~ /^[0-7]$/) { v = v * 8 + d; k++ }
    i += k; return (v > 0 && v < 128) ? sprintf("%c", v) : "?"
  }
  i++
  if (ch == "n") return "\n"
  if (ch == "t") return "\t"
  if (index("abeEfvr", ch)) return "\001"
  return ch
}
# ─── redirections and heredocs
# hd_word(j) — the heredoc delimiter at j, as the shell reads it: a whole
# word, quotes and backslashes removed, quoted if any part was. Sets hdw and
# hdq; returns where the word ends.
function hd_word(j,   ch, e) {
  hdw = ""; hdq = 0
  while (j <= n) {
    ch = substr(cmd, j, 1)
    if (index(" \t\n;&|<>()", ch)) break
    if (ch == "\\") { hdq = 1; hdw = hdw substr(cmd, j + 1, 1); j += 2; continue }
    if (ch == "\047" || ch == "\"") {
      hdq = 1; e = index(substr(cmd, j + 1), ch)
      if (!e) { hdw = hdw substr(cmd, j + 1); return n + 1 }
      hdw = hdw substr(cmd, j + 1, e - 1); j += e + 1; continue
    }
    hdw = hdw ch; j++
  }
  return j
}
# redirect — at an unquoted < or >, which ends a word unless the word is the
# redirection (>>, 2>&1) or its descriptor (2>, {fd}>). A heredoc registers
# its delimiter; its body is read at the end of the line.
function redirect(   j, strip) {
  if (arith()) return 0
  if (in_tok && !fd_tok() && tok_val !~ /^[0-9]*[<>]+&?$/ && tok_val !~ /^&>>?$/) flush_tok()
  if (substr(cmd, i, 3) == "<<<") {
    start_tok(); tok_val = tok_val "<<<"; i += 3
    while (i <= n && (substr(cmd, i, 1) == " " || substr(cmd, i, 1) == "\t")) i++
    return 1
  }
  if (substr(cmd, i, 2) == "<<") {
    in_tok = 0
    j = i + 2; strip = 0
    if (substr(cmd, j, 1) == "-") { strip = 1; j++ }
    while (substr(cmd, j, 1) == " " || substr(cmd, j, 1) == "\t") j++
    j = hd_word(j)
    if (hdw != "" || hdq) { hd_n++; hd_delim[hd_n] = hdw; hd_strip[hd_n] = strip; hd_q[hd_n] = hdq }
    i = j; return 1
  }
  return 0
}
# redir(v) — the words a redirection takes: 0 when v is none, 1 when its
# target is in the word (2>/dev/null, <file, a here-string <<<word), 2 when
# the target is the next word (`> log`).
function redir(v) {
  if (v !~ /^[0-9]*[<>]/ && v !~ /^&>/) return 0
  return (v ~ /^[0-9]*[<>]+&?$/ || v ~ /^&>>?$/) ? 2 : 1
}
# ─── reading a push
function dst_of(r,   p) {
  while ((p = index(r, ":")) > 0) r = substr(r, p + 1)
  sub(/^refs\/heads\//, "", r); sub(/^heads\//, "", r)
  return r
}
# glob_main(d) — a refspec glob (one *) whose matches include main or master.
function glob_main(d,   p, pre, suf, t, k, T) {
  if (!(p = index(d, "*"))) return 0
  pre = substr(d, 1, p - 1); suf = substr(d, p + 1)
  split("refs/heads/main refs/heads/master heads/main heads/master main master", T, " ")
  for (k = 1; k <= 6; k++) {
    t = T[k]
    if (length(t) >= length(pre) + length(suf) && substr(t, 1, length(pre)) == pre &&
        substr(t, length(t) - length(suf) + 1) == suf) return 1
  }
  return 0
}
# facts(text) — a force push (or delete) of main, read from TEXT as it stands
# and again with its quotes and backslashes removed (git pu""sh): a second
# check beside the walk of a string another shell runs, block only.
function facts(text,   n, parts, j, p, t, pass) {
  for (pass = 1; pass <= 2; pass++) {
    t = text
    if (pass == 2) gsub(/[\047"\\]/, "", t)
    n = split(t, parts, /[;&|\n]/)
    for (j = 1; j <= n; j++) {
      p = " " parts[j] " "
      if (p ~ /[ \t\047"(`]git[ \t]+([^ \t]+[ \t]+)*push[ \t]/ &&
          (p ~ /[ \t](--force|--force-with-lease[^ \t]*|--mirror|--delete|-[A-Za-z]*[fd][A-Za-z]*)[ \t\047"]/ ||
           p ~ /[ \t][+:][^ \t]/) &&
          p ~ /[ \t:+\/\047"](main|master)([ \t\047")`]|\\)/) return 1
    }
  }
  return 0
}
function is_shell(w) { return (w == "bash" || w == "sh" || w == "zsh" || w == "dash" || w == "ksh") }
function is_kw(w) {
  return (w == "{" || w == "}" || w == "!" || w == "if" || w == "then" || w == "elif" || w == "else" ||
          w == "fi" || w == "for" || w == "while" || w == "until" || w == "do" || w == "done" || w == "time")
}
# A shell given -c runs its next argument; given a script file it runs that
# file, which is not in the command (returns 0: the statement is read on);
# given neither (or -s) it reads its script from stdin — `echo … | bash`,
# `bash <<EOF`, `bash 2>&1 <<<"…"`: a redirection is no script file.
function analyze_shell(k,   j, v, r) {
  for (j = k + 1; j <= nt; j++) {
    v = tv[j]
    if ((r = redir(v)) > 0) { j += r - 1; continue }
    if (v == "-c" || (v ~ /^-[A-Za-z]+$/ && index(v, "c") > 0)) { nested(j + 1, j + 1, cd_seen); return 1 }
    if (v == "-s") { set_stdin(cd_seen); return 1 }
    if (v == "-o" || v == "+o" || v == "-O" || v == "+O" || v == "--rcfile" || v == "--init-file") { j++; continue }
    if (v ~ /^[-+]/) continue
    return 0
  }
  set_stdin(cd_seen); return 1
}
# ssh [options] host [command…]: the remote command is what follows the host,
# less its redirections, run on another machine (so its branch is unknown).
# With no command, ssh runs a shell that reads stdin.
function analyze_ssh(k,   j, v, m, r) {
  for (j = k + 1; j <= nt; j++) {
    v = tv[j]
    if (v ~ /^-[BbcDEeFIiJLlmOopQRSWw]$/) { j++; continue }
    if (v ~ /^-/) continue
    break
  }
  if (j > nt) return 0
  m = j + 1
  while (m <= nt && (r = redir(tv[m])) > 0) m += r
  if (m > nt) { set_stdin(1); return 1 }
  nested(j + 1, nt, 1); return 1
}
# su [opts] [user] -c cmd runs cmd through a shell; without -c it is a shell
# reading stdin. So is sudo (or doas) -s / -i with no command after it.
function analyze_su(k,   j) {
  for (j = k + 1; j <= nt; j++) {
    if (tv[j] == "-c" || tv[j] == "--command" || (tv[j] ~ /^-[A-Za-z]+$/ && index(tv[j], "c") > 0)) { nested(j + 1, j + 1, cd_seen); return }
    if (tv[j] ~ /^--command=/) { tv[j] = substr(tv[j], 11); nested(j, j, cd_seen); return }
  }
  set_stdin(cd_seen)
}
function analyze_sudo(k,   j, v, r, sh) {
  sh = 0
  for (j = k + 1; j <= nt; j++) {
    v = tv[j]
    if ((r = redir(v)) > 0) { j += r - 1; continue }
    if (v ~ /^-[ugCDhprtUT]$/) { j++; continue }
    if (v == "--shell" || v == "--login" || (v ~ /^-[A-Za-z]+$/ && (index(v, "s") || index(v, "i")))) { sh = 1; continue }
    if (v ~ /^-/) continue
    return 0
  }
  if (sh) set_stdin(cd_seen)
  return sh
}
# analyze — one statement. The command can sit behind any prefix (timeout 60,
# sudo -u bob, nice -n 19, xargs -I{}, env -C dir, then, do, {), and listing
# prefixes was how the first cut of this walk let `timeout 120 git push --force
# origin main` through. So each word is read in turn, and git, a shell, ssh,
# su, sudo or eval decides — unless it is not the command after all (the git
# of `sudo -u git git push`, a shell given a script file). An assignment
# (SHELL=/bin/bash) or an option is never the command. A bare `git` argument
# to echo is read too; that errs toward checking, never toward skipping.
function analyze(   k, w) {
  k = 1
  while (k <= nt && (tv[k] ~ /^[A-Za-z_][A-Za-z0-9_]*=/ || is_kw(tv[k]))) k++
  if (k <= nt) { w = tv[k]; sub(/.*\//, "", w); if (w == "cd" || w == "pushd" || w == "popd") { if (!nocd) cd_seen = 1; return } }
  for (; k <= nt; k++) {
    w = tv[k]
    if (w ~ /^[A-Za-z_][A-Za-z0-9_]*=/ || w ~ /^-/) continue
    sub(/.*\//, "", w)
    if (w == "git") { if (analyze_git(k)) return }
    else if (is_shell(w)) { if (analyze_shell(k)) return }
    else if (w == "ssh") { if (analyze_ssh(k)) return }
    else if (w == "su" || w == "runuser") { analyze_su(k); return }
    else if (w == "sudo" || w == "doas") { if (analyze_sudo(k)) return }
    else if (w == "eval") { nested(k + 1, nt, cd_seen); return }
  }
}
# add_cfg — one config setting (key=value) on the command line of git;
# --config-env names a variable, so its value is unknown ("?").
function add_cfg(r, how,   p) {
  p = index(r, "="); ncf++
  ck[ncf] = tolower(p ? substr(r, 1, p - 1) : r); cv[ncf] = (how != "-c") ? "?" : (p ? substr(r, p + 1) : "")
}
# analyze_git — 1 when this git is the command (a push, or an alias given on
# its command line); 0 when it is not, so the statement is read on.
function analyze_git(k,   hasC, j, v, skipnext, dd, npos, nf, np, lease, allrefs, mirror, nrefs, mainref, del, headref, subref, r, d, plus, raw, newv, pk, rd, p, ex, gv) {
  # GIT_CONFIG_KEY_n/VALUE_n and GIT_CONFIG_PARAMETERS assigned in front of
  # git are config on its command line too, read as -c is.
  ncf = 0; split("", gv)
  for (j = 1; j < k; j++) {
    v = tv[j]
    if (v ~ /^GIT_CONFIG_(KEY|VALUE)_[0-9]+=/) { p = index(v, "="); gv[substr(v, 12, p - 12)] = substr(v, p + 1) }
    else if (v ~ /^GIT_CONFIG_PARAMETERS=/) { r = substr(v, 23); while (match(r, /\047[^\047]*\047/)) { add_cfg(substr(r, RSTART + 1, RLENGTH - 2), "-c"); r = substr(r, RSTART + RLENGTH) } }
  }
  for (v in gv) if (v ~ /^KEY_/) add_cfg(gv[v] "=" ((("VALUE_" substr(v, 5)) in gv) ? gv["VALUE_" substr(v, 5)] : ""), "-c")
  k++; hasC = 0
  while (k <= nt) {
    v = tv[k]
    if (v == "-c" || v == "--config-env" || v ~ /^--config-env=/) {
      if (v ~ /^--config-env=/) { r = substr(v, 14); k++ } else { r = tv[k + 1]; k += 2 }
      add_cfg(r, v); continue
    }
    if (v == "-C" || v == "--git-dir" || v == "--work-tree" || v == "--namespace") { hasC = 1; k += 2; continue }
    if (v ~ /^--(git-dir|work-tree)=/) { hasC = 1; k++; continue }
    if (v ~ /^-/) { k++; continue }
    break
  }
  if (k > nt) return 0
  ex = 0
  if (tv[k] != "push") {
    # git follows a chain of aliases, so this one may push through another:
    # when it is given with -c, any -c alias that pushes blocks.
    for (j = 1; j <= ncf; j++) if (ck[j] == "alias." tolower(tv[k])) for (r = 1; r <= ncf; r++)
      if (ck[r] ~ /^alias\./ && (cv[r] ~ /push/ || cv[r] == "?")) { block("config"); return 1 }
    # A subcommand the shell computes ($(echo push), ${x}push) may be push:
    # it is read as one, and never rewritten.
    raw = substr(cmd, ts[k], te[k] - ts[k] + 1)
    if (!index(raw, "$") && !index(raw, "`")) return 0
    ex = 1
  }
  pk = k
  skipnext = 0; dd = 0; npos = 0; nf = 0; np = 0; lease = 0; allrefs = 0; mirror = 0; nrefs = 0; mainref = 0; del = 0; headref = 0; subref = 0
  for (j = pk + 1; j <= nt; j++) {
    v = tv[j]
    if (skipnext) { skipnext = 0; continue }
    if ((rd = redir(v)) > 0) { skipnext = (rd == 2); continue }
    if (!dd && v == "--") { dd = 1; continue }
    if (!dd && v ~ /^--/) {
      if (v == "--force") { nf++; FI[nf] = j }
      else if (v ~ /^--force-with-lease/ || v == "--force-if-includes") lease = 1
      else if (v == "--mirror") mirror = 1
      else if (v == "--all" || v == "--branches") allrefs = 1
      else if (v == "--delete") del = 1
      else if (v == "--repo" || v == "--receive-pack" || v == "--exec" || v == "--push-option") skipnext = 1
      continue
    }
    if (!dd && v ~ /^-[^-]/) {
      if (v == "-o") { skipnext = 1; continue }
      # Only an alphanumeric cluster is short options. git rejects a malformed
      # `-f-with-lease`, so it is left alone rather than "repaired".
      if (v !~ /^-[A-Za-z0-9]+$/) continue
      if (index(v, "d") > 0) del = 1
      if (index(v, "f") > 0) { nf++; FI[nf] = j }
      continue
    }
    npos++
    if (npos == 1) continue
    nrefs++
    r = v; plus = 0
    if (substr(r, 1, 1) == "+") { plus = 1; r = substr(r, 2) }
    d = dst_of(r)
    if (d == "main" || d == "master" || glob_main(d) || r == ":") {
      mainref = 1
      if (substr(r, 1, 1) == ":" && r != ":") del = 1
    }
    # HEAD and @ name the current branch, which the text does not; so, most
    # likely, does a ref the shell computes (git push -f origin "$(git branch
    # --show-current)"), and that one is the session branch even after a cd
    # or over ssh, where a substitution outside single quotes runs here.
    if (d == "HEAD" || d == "@") headref = 1
    raw = substr(cmd, ts[j], te[j] - ts[j] + 1)
    if (index(raw, "$(") || index(raw, "`")) subref = 1
    if (plus) { np++; PI[np] = j }
  }
  if (mirror) { block("mirror"); return 1 }
  if (del && mainref) { block("delete"); return 1 }
  # A refspec, mirror or push.default given with -c decides what a push with
  # no refspec sends, and a + in it forces: neither is in the arguments.
  if (nrefs == 0) for (j = 1; j <= ncf; j++)
    if ((ck[j] ~ /^remote\..+\.push$/ && (nf || np || lease || cv[j] ~ /^\+/ || cv[j] == "?")) ||
        (ck[j] ~ /^remote\..+\.mirror$/ && cv[j] != "false") ||
        (ck[j] == "push.default" && (cv[j] == "matching" || cv[j] == "?") && (nf || np || lease))) { block("config"); return 1 }
  if (nf == 0 && np == 0 && !lease) return 1
  if (mainref || (allrefs && (nf > 0 || np > 0 || lease))) { block("main"); return 1 }
  if ((((nrefs == 0 || headref) && !allrefs && !cd_seen && !hasC) || subref) &&
      (ENVIRON["GD_BRANCH"] == "main" || ENVIRON["GD_BRANCH"] == "master")) { block("branch"); return 1 }
  if (nf == 0 && np == 0 || ex) return 1
  for (j = 1; j <= nf; j++) {
    v = tv[FI[j]]
    if (v == "--force" || v == "-f") newv = "--force-with-lease"
    else { newv = v; gsub(/f/, "", newv); newv = (newv == "-") ? "--force-with-lease" : newv " --force-with-lease" }
    add_edit(ts[FI[j]], te[FI[j]], newv)
  }
  for (j = 1; j <= np; j++) {
    raw = substr(cmd, ts[PI[j]], te[PI[j]] - ts[PI[j]] + 1)
    sub(/\+/, "", raw)
    add_edit(ts[PI[j]], te[PI[j]], raw)
  }
  if (nf == 0 && !lease) add_edit(te[pk] + 1, te[pk], " --force-with-lease")
  return 1
}
# ─── the walk
# walk(text, mode, depth, cd0, edit) — one string: the command (depth 0), or
# one queued string another shell runs. mode "H" is the body of a heredoc with
# an unquoted delimiter: text, except for what the shell expands in it.
function walk(text, mode, depth, cd0, edit,   c, h, b0, found, closes, e, line, ls, lt) {
  cmd = text; n = length(cmd); i = 1; q = mode; in_tok = 0; nt = 0; hd_n = 0; sn = 0; pd = 0; cc[0] = 0; ip[0] = 0; nocd = 0
  cd_seen = cd0; wd = depth; ed = edit
  while (i <= n) {
    c = substr(cmd, i, 1)
    if (sn > 0 && sbt[sn] > 0 && i >= sbt[sn]) { while (sk[sn] != "`") close_sub(0); close_sub(1); continue }
    if (q == "\047") { if (c == "\047") q = ""; else tok_val = tok_val c; i++; continue }
    if (q == "$") {
      if (c == "\\" && i < n) { i++; tok_val = tok_val ansi(); continue }
      if (c == "\047") q = ""; else tok_val = tok_val c
      i++; continue
    }
    if (q == "\"") {
      if (c == "\\" && i < n) {
        nc = substr(cmd, i + 1, 1)
        if (nc == "\\" || nc == "\"" || nc == "$" || nc == "`") { tok_val = tok_val nc; i += 2; continue }
      }
      if (substr(cmd, i, 2) == "$$") { tok_val = tok_val "$$"; i += 2; continue }
      if (open_exp(c)) continue
      if (c == "\"") q = ""; else tok_val = tok_val c
      i++; continue
    }
    if (q == "H") {
      if (c == "\\" && i < n && index("$`\\\n", substr(cmd, i + 1, 1))) { i += 2; continue }
      if (substr(cmd, i, 2) == "$$") { i += 2; continue }
      if (!open_exp(c)) i++
      continue
    }
    if (c == "\\") {
      if (i < n && substr(cmd, i + 1, 1) == "\n") { i += 2; continue }
      start_tok(); if (i < n) tok_val = tok_val substr(cmd, i + 1, 1); i += 2; continue
    }
    if (substr(cmd, i, 2) == "$$") { start_tok(); tok_val = tok_val "$$"; i += 2; continue }
    if (substr(cmd, i, 2) == "$\047") { start_tok(); q = "$"; i += 2; continue }
    if (substr(cmd, i, 2) == "$\"") { start_tok(); q = "\""; i += 2; continue }
    if (c == "\047" || c == "\"") { start_tok(); q = c; i++; continue }
    if (c == " " || c == "\t") { flush_tok(); i++; continue }
    if (c == "#" && !in_tok) { while (i <= n && substr(cmd, i, 1) != "\n") i++; continue }
    if (c == "\n") {
      end_seg(); i++
      for (h = 1; h <= hd_n; h++) {
        b0 = i; found = 0; closes = 0; ls = i
        while (i <= n) {
          e = index(substr(cmd, i), "\n")
          line = (e > 0) ? substr(cmd, i, e - 1) : substr(cmd, i)
          ls = i; i = (e > 0) ? i + e : n + 1
          lt = 0
          if (hd_strip[h]) while (substr(line, lt + 1, 1) == "\t") lt++
          line = substr(line, lt + 1)
          if (line == hd_delim[h]) { found = 1; break }
          # Inside $( ), bash 5.2 also ends a heredoc at a line that only
          # starts with its delimiter, when that line holds a ), and runs the
          # rest of the line: `EOF x; git push …)` runs the push.
          if (sn > 0 && sk[sn] == "$" && hd_delim[h] != "" && index(line, ")") &&
              substr(line, 1, length(hd_delim[h])) == hd_delim[h]) {
            found = 1; closes = 1; i = ls + lt + length(hd_delim[h]); break
          }
        }
        heredoc(substr(cmd, b0, (found ? ls : i) - b0), hd_q[h], found)
        if (closes) break
      }
      hd_n = 0
      continue
    }
    if (open_exp(c)) continue
    if (c == "(" && substr(cmd, i + 1, 1) == "(" && cmd_pos() && arith_end(i + 2)) { open_sub("A", 2); continue }
    if (c == "(" && ip[sn] && !in_tok && nt == 0) { i++; continue }
    if (c == "(") { if (sn > 0) sp[sn]++; end_seg(); pd++; pcd[pd] = cd_seen; i++; continue }
    if (c == ")") {
      flush_tok()
      if (ip[sn]) { end_seg(); ip[sn] = 0; i++; continue }
      if (sn > 0 && sp[sn] == 0 && sk[sn] == "$") { close_sub(1); continue }
      if (sn > 0 && sp[sn] == 0 && sk[sn] == "A") { close_sub((substr(cmd, i + 1, 1) == ")") ? 2 : 1); continue }
      if (sn > 0 && sp[sn] > 0) sp[sn]--
      end_seg()
      if (pd > ((sn > 0) ? spd[sn] : 0)) { cd_seen = pcd[pd]; pd-- }
      i++; continue
    }
    if (sn > 0 && sk[sn] == "[") {
      if (c == "[") sp[sn]++
      else if (c == "]") { if (sp[sn] == 0) { close_sub(1); continue }; sp[sn]-- }
    }
    if (c == ";") {
      end_seg()
      if (substr(cmd, i + 1, 1) == ";" || substr(cmd, i + 1, 1) == "&") {
        if (cc[sn] > 0) ip[sn] = 1
        i += (substr(cmd, i, 3) == ";;&") ? 3 : 2; continue
      }
      i++; continue
    }
    if (c == "|") {
      nocd = 1; end_seg(); nocd = 1
      i += (substr(cmd, i + 1, 1) == "|" || substr(cmd, i + 1, 1) == "&") ? 2 : 1; continue
    }
    if (c == "&") {
      if (i > 1 && (substr(cmd, i - 1, 1) == ">" || substr(cmd, i - 1, 1) == "<")) { start_tok(); tok_val = tok_val c; i++; continue }
      if (substr(cmd, i + 1, 1) == ">") { flush_tok(); start_tok(); tok_val = tok_val c; i++; continue }
      if (substr(cmd, i + 1, 1) == "&") { end_seg(); i += 2; continue }
      nocd = 1; end_seg(); i++; continue
    }
    if ((c == "<" || c == ">") && redirect()) continue
    start_tok(); tok_val = tok_val c; i++
  }
  while (sn > 0) close_sub(0)
  end_seg()
}
{ cmd = (NR == 1) ? $0 : cmd RS $0 }
END {
  top = cmd; blocked = ""; ne = 0; ns = 0; nq = 0; stdin_any = 0; stdin_cd = 1
  walk(top, "", 0, 0, 1)
  # $$ is one word to bash and dash, but zsh reads $$ before an ANSI-C string
  # as $ and then the string, and bash parses "$$(" as $ and $(: that other
  # reading is walked too, block-only.
  if (top ~ /\$\$[\047(]/) { alt = top; gsub(/\$\$\047/, "_$\047", alt); gsub(/\$\$\(/, "_$(", alt); enqueue(alt, "", 0, 0) }
  for (qi = 1; qi <= nq && blocked == ""; qi++) walk(qt[qi], qm[qi], qd[qi], qc[qi], 0)
  if (stdin_any && facts(top)) block("nested")
  if (blocked != "") { print "block\t" blocked; exit }
  if (ne == 0) { print "none"; exit }
  for (a = 2; a <= ne; a++) {
    s0 = es[a]; e0 = ee[a]; t0 = et[a]; b = a - 1
    while (b >= 1 && es[b] < s0) { es[b + 1] = es[b]; ee[b + 1] = ee[b]; et[b + 1] = et[b]; b-- }
    es[b + 1] = s0; ee[b + 1] = e0; et[b + 1] = t0
  }
  out = top
  for (a = 1; a <= ne; a++) out = substr(out, 1, es[a] - 1) et[a] substr(out, ee[a] + 1)
  print "rewrite"; printf "%s", out
}'

# The walk runs when "push" survives quote removal and line continuations (git
# pu""sh is a push) or a $'…' string could spell it.
_gd_plain=${COMMAND//\\$'\n'/}; _gd_plain=${_gd_plain//\"/}; _gd_plain=${_gd_plain//\'/}; _gd_plain=${_gd_plain//\\/}
if [[ "$_gd_plain" == *push* || "$COMMAND" == *"\$'"* ]]; then
  GD_BRANCH=$(git -C "${HOOK_CWD:-$PWD}" symbolic-ref --short -q HEAD 2>/dev/null || true)
  _gp=$(printf '%s' "$COMMAND" | GD_BRANCH="$GD_BRANCH" LC_ALL=C awk 'BEGIN { RS = "\001" } '"$GD_PUSH_AWK" 2>/dev/null || true)
  case "$_gp" in
    block*)
      case "$_gp" in
        *branch) _why="it pushes the current branch, which is ${GD_BRANCH}" ;;
        *delete) _why="it deletes main/master on the remote" ;;
        *mirror) _why="--mirror force-updates every ref on the remote, main/master included" ;;
        *config) _why="git -c or GIT_CONFIG_* sets an alias or a push setting on its command line that forces the push" ;;
        *nested) _why="a wrapped or piped shell command (ssh, bash -c, eval, … | bash) force-pushes main/master" ;;
        *)       _why="it names main/master" ;;
      esac
      gd_deny "Force push to main/master blocked: ${_why}. This destroys shared history. Use --force-with-lease on a feature branch, or ask the user explicitly. Command: $COMMAND"
      ;;
    rewrite*)
      gd_rewrite "${_gp#rewrite$'\n'}" "pre-tool-guardian rewrote a force push to --force-with-lease, which refuses to overwrite the remote branch if someone else updated it since your last fetch. Only the git push statement changed."
      ;;
  esac
fi

# ─── SQL DROP DATABASE / DROP TABLE ──────────────────────────────────
# These are irreversible. Redirect to manual execution.
if printf '%s\n' "$COMMAND" | grep -qiE '\bDROP[[:space:]]+(DATABASE|TABLE|SCHEMA)\b'; then
  gd_deny "SQL DROP statement blocked. Irreversible operation must be run manually in your terminal after review. Command: $COMMAND"
fi

# ─── Self-killing pkill -f ───────────────────────────────────────────
# `pkill -f PAT` matches against full command lines, including the command line
# of the shell that launched it. Inside an ssh one-liner or a compound command
# whose own text contains PAT, the launching shell matches its own pattern and
# kills itself: exit 255/144, and the work after the `&&` never runs. It looks
# like the remote host rejected the connection, so the time goes into debugging
# ssh. Blocked only in the shape that actually self-destructs, because a guard
# that fires on ordinary `pkill -f name` is one you learn to ignore.
# `pkill` must sit at a COMMAND position — start of string, or after a
# separator or an opening quote. Matching it anywhere caught prose: this very
# guard's own commit message ("block the pkill -f shape that kills its own
# launcher") was refused, which is the failure mode the rule below warns about.
if printf '%s\n' "$COMMAND" | grep -qE '(^|[;&|(]|[[:space:]]&&[[:space:]]|["'"'"'])[[:space:]]*pkill[[:space:]]+(-[a-zA-Z]*f|--full)'; then
  _PK_PAT=$(printf '%s\n' "$COMMAND" \
    | sed -nE "s/.*(^|[;&|('\"]|[[:space:]])pkill[[:space:]]+(-[a-zA-Z]*f|--full)[[:space:]]+['\"]?([^'\"[:space:]]+).*/\3/p" \
    | head -1 || true)
  if [[ -n "$_PK_PAT" ]]; then
    # Occurrences of the pattern in the command the shell will carry.
    _PK_N=$(printf '%s\n' "$COMMAND" | grep -oF -- "$_PK_PAT" | wc -l | tr -d ' ')
    # A wrapped/remote one-liner carries the pattern in the wrapper's own argv,
    # so a single textual occurrence is still a self-match there.
    _PK_WRAPPED=false
    printf '%s\n' "$COMMAND" | grep -qE '(^|[[:space:]])(ssh|bash[[:space:]]+-c|sh[[:space:]]+-c)([[:space:]]|$)' \
      && _PK_WRAPPED=true
    if [[ "${_PK_N:-0}" -ge 2 || "$_PK_WRAPPED" == true ]]; then
      gd_deny "pkill -f ${_PK_PAT} will match the command line of the shell running it, so this kills its own launcher (exit 255/144) and everything after it never runs. Fixes: put the pkill in a script file, so the pattern is not in the caller argv; anchor the pattern (\"name\\.py --flag\"); and in monitors use the bracket trick pgrep \"na[m]e\". Command: $COMMAND"
    fi
  fi
fi

# ─── Allow everything else ───────────────────────────────────────────
# A subagent wait that outlives the cache runs, with the warning attached.
[[ -n "$GD_WAIT_WARN" ]] && gd_warn "$GD_WAIT_WARN"
exit 0
