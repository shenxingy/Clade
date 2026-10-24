#!/usr/bin/env bash
# test-workflow-preflight.sh — end-to-end tests for configs/hooks/workflow-preflight.sh
#   (PreToolUse Workflow → configs/scripts/check-workflow-script.py --hook)
#
# Every case pipes a hook-input fixture through the real hook script and reads
# the answer against the schema Claude Code accepts — never by substring:
#   DENY   hookSpecificOutput.permissionDecision "deny" with a reason
#   WARN   hookSpecificOutput.additionalContext and NO permissionDecision
#   ALLOW  exit 0, no output
#   CRASH  any non-zero exit (Claude Code would run the launch unchecked)
#
# The placeholder fixtures are the exact shapes of real launches on the
# author's host (2026-09-22 → 10-23): "__ARGS_PLACEHOLDER__" as a JSON-encoded
# string, {"payload": "__FILE__"}, [{"__see": "review-units"}] (that run went
# to "completed" on the placeholder), "(see packet file)" inside a packet list.
#
# Hermetic: HOME and CLAUDE_CONFIG_DIR point at temp dirs, the usage-cache
# refresh is either disabled (CLADE_PREFLIGHT_NO_REFRESH=1) or served by a
# fake claude-usage-watch.py, and nothing touches the network or ~/.claude.
#
# The last section removes each guard of the shell wrapper in turn and requires
# the wrapper cases to go red — the checker's own guards are mutated by
# orchestrator/tests/test_self_tests_can_fire.py against its --self-test.
#
# Usage:
#   bash tests/test-workflow-preflight.sh          # run all tests
#   WORKFLOW_PREFLIGHT_HOOK=/path/to/other.sh bash tests/test-workflow-preflight.sh
#                                                   # run against another hook
#                                                   # (a no-op must turn it red)

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK="${WORKFLOW_PREFLIGHT_HOOK:-$REPO_ROOT/configs/hooks/workflow-preflight.sh}"
CHECKER="$REPO_ROOT/configs/scripts/check-workflow-script.py"

TESTS_RUN=0; TESTS_PASSED=0; TESTS_FAILED=0
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[0;33m'; NC='\033[0m'
pass() { TESTS_RUN=$((TESTS_RUN + 1)); TESTS_PASSED=$((TESTS_PASSED + 1)); printf "  ${GREEN}✓${NC} %s\n" "$1"; }
fail() {
  TESTS_RUN=$((TESTS_RUN + 1)); TESTS_FAILED=$((TESTS_FAILED + 1))
  printf "  ${RED}✗${NC} %s\n" "$1"
  [[ -n "${2:-}" ]] && printf "    ${RED}→ %s${NC}\n" "$2"
  return 0
}
section() { printf "\n${YELLOW}━━━ %s ━━━${NC}\n" "$1"; }

if ! command -v python3 >/dev/null 2>&1 || ! command -v jq >/dev/null 2>&1; then
  echo "SKIP: python3 and jq are required"
  exit 0
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP/home"
export CLAUDE_CONFIG_DIR="$TMP/cfg"
export CLADE_PREFLIGHT_NO_REFRESH=1
unset CLADE_PREFLIGHT_SCRIPT CLADE_PREFLIGHT_TIMEOUT
mkdir -p "$HOME" "$CLAUDE_CONFIG_DIR" "$TMP/proj/.claude/workflows" "$CLAUDE_CONFIG_DIR/workflows"

# payload <tool_input JSON> [cwd] [extra JSON merged at top level]
payload() {
  python3 - "$1" "${2:-$TMP/proj}" "${3:-{\}}" <<'PY'
import json, sys
d = {"session_id": "s1", "transcript_path": "/dev/null", "cwd": sys.argv[2],
     "permission_mode": "bypassPermissions", "hook_event_name": "PreToolUse",
     "tool_name": "Workflow", "tool_input": json.loads(sys.argv[1])}
d.update(json.loads(sys.argv[3]))
print(json.dumps(d))
PY
}

# run_hook <stdin-text> → sets OUT and RC
run_hook() {
  OUT=$(printf '%s' "$1" | bash "$HOOK" 2>/dev/null)
  RC=$?
}

verdict() {
  if [[ "$RC" != 0 ]]; then echo CRASH; return; fi
  if [[ -z "${OUT//[[:space:]]/}" ]]; then echo ALLOW; return; fi
  jq -r '
    if type != "object" then "UNPARSED"
    elif has("decision") or has("reason") then "LEGACY"
    else (.hookSpecificOutput // {}) as $h
    | if $h.hookEventName != "PreToolUse" then "NO-EVENT"
      elif $h.permissionDecision == "deny" and (($h.permissionDecisionReason // "") != "") then "DENY"
      elif ($h | has("permissionDecision")) then "OTHER-DECISION"
      elif (($h.additionalContext // "") != "") then "WARN"
      else "EMPTY" end
    end' <<<"$OUT" 2>/dev/null || echo UNPARSED
}

text_of() {
  jq -r '.hookSpecificOutput.permissionDecisionReason // .hookSpecificOutput.additionalContext // ""' <<<"$OUT" 2>/dev/null
}

# expect <name> <want-verdict> [needle in the reason/context]
expect() {
  local name="$1" want="$2" needle="${3:-}" got
  got=$(verdict)
  if [[ "$got" != "$want" ]]; then
    fail "$name" "verdict $got, want $want; output: ${OUT:0:300}"
    return
  fi
  if [[ -n "$needle" ]] && ! grep -qF -- "$needle" <<<"$(text_of)"; then
    fail "$name" "no '$needle' in: $(text_of | head -c 400)"
    return
  fi
  pass "$name"
}

# expect_input <name> <want> <tool_input JSON> [needle] [cwd] [extra]
expect_input() {
  run_hook "$(payload "$3" "${5:-$TMP/proj}" "${6:-{\}}")"
  expect "$1" "$2" "${4:-}"
}

js_input() {  # js_input <file> → {"script": <file contents>}
  python3 -c 'import json,sys; print(json.dumps({"script": open(sys.argv[1]).read()}))' "$1"
}

# ─── Fixture scripts ─────────────────────────────────────────────────
cat > "$TMP/cut.js" <<'JS'
export const meta = { name: 'fixture-cut', description: 'review then check' }
const fix = await agent('fix the bug', { label: 'fix', phase: 'Fix' })
const check = await agent(`Check the fix. It reported:\n${JSON.stringify(fix).slice(0, 7000)}`, { label: 'check', phase: 'Check' })
return { fix, check }
JS
cat > "$TMP/clean.js" <<'JS'
export const meta = { name: 'fixture-clean', description: 'pass a path, not a cut' }
const fix = await agent('fix the bug and write the full report to /tmp/x/fix.json', { label: 'fix' })
const check = await agent(`Check the fix. Its full report is at /tmp/x/fix.json; summary: ${fix.summary}`, { label: `check:${String(fix.id).slice(0, 20)}` })
log(`fix ${JSON.stringify(fix).slice(0, 200)}`)
return { fix, check }
JS
cat > "$TMP/cutword.js" <<'JS'
const plan = await agent('Cut the scope to P1 and drop the rest; clip nothing else.', { label: 'plan' })
await agent(`Do the plan:\n${JSON.stringify(plan).slice(0, 6000)}`, { label: 'do' })
JS
cat > "$TMP/logged.js" <<'JS'
const fix = await agent('fix')
const s = JSON.stringify(fix)
if (s.length > 7000) log(`check prompt: cut ${s.length - 7000} of ${s.length} chars`)
await agent(`Check:\n${s.slice(0, 7000)}`, { label: 'check' })
JS
cp "$TMP/cut.js" "$TMP/proj/.claude/workflows/saved-cut.js"
cp "$TMP/cut.js" "$CLAUDE_CONFIG_DIR/workflows/user-cut.mjs"

# ─── Script resolution and the truncation rule ───────────────────────
section "Truncation rule, through every way a launch names its script"
expect_input "inline script with a silent cut warns" WARN "$(js_input "$TMP/cut.js")" "line 3"
OUT_WARN="$OUT"
expect_input "scriptPath is read and checked" WARN "{\"scriptPath\": \"$TMP/cut.js\"}" "line 3"
expect_input "relative scriptPath resolves against the hook's cwd" WARN '{"scriptPath": "../cut.js"}' "line 3"
expect_input "saved name resolves under <cwd>/.claude/workflows" WARN '{"name": "saved-cut"}' "line 3"
expect_input "saved name falls back to the config dir's workflows/" WARN '{"name": "user-cut"}' "line 3"
expect_input "an unresolvable name is silent" ALLOW '{"name": "no-such-workflow"}'
expect_input "a clean script is silent (label slice, log slice, summary field)" ALLOW "$(js_input "$TMP/clean.js")"
expect_input "a cut the script logs is the author's choice" ALLOW "$(js_input "$TMP/logged.js")"
expect_input "a cut word inside a prompt does not excuse a silent cut" WARN "$(js_input "$TMP/cutword.js")" "line 2"
# The warning must say what to do, and name the excerpt.
OUT="$OUT_WARN"; RC=0
expect "the warning names the excerpt and the fix" WARN 'JSON.stringify(fix).slice(0, 7000)'
expect "the warning offers the file-and-path fix" WARN "write the full result to a file"
if [[ $(text_of | wc -c) -le 1600 ]]; then pass "the warning stays within its ~1,500-char budget"
else fail "the warning stays within its ~1,500-char budget" "$(text_of | wc -c) chars"; fi

# 40 cut sites: the context is capped and says how many it left out.
python3 - "$TMP/many.js" <<'PY'
import sys
lines = ["const r = await agent('a')"]
for i in range(40):
    lines.append("await agent(`check %d:\\n${JSON.stringify(r).slice(0, %d)}`)" % (i, 1000 + i))
open(sys.argv[1], "w").write("\n".join(lines) + "\n")
PY
expect_input "forty sites stay within the budget and count the rest" WARN "$(js_input "$TMP/many.js")" "more site(s)"
if [[ $(text_of | wc -c) -le 1600 ]]; then pass "forty sites: context ≤ ~1,500 chars"
else fail "forty sites: context ≤ ~1,500 chars" "$(text_of | wc -c) chars"; fi

# ─── Placeholder args → deny ─────────────────────────────────────────
section "Placeholder args are denied (real launch shapes)"
expect_input "\"__ARGS_PLACEHOLDER__\" as a JSON-encoded string (wf_9d59c30c)" DENY \
  '{"script": "return args", "args": "\"__ARGS_PLACEHOLDER__\""}' "placeholder"
expect_input "{\"payload\": \"__FILE__\"} (wf_1c4f6d67)" DENY \
  '{"script": "return args", "args": {"payload": "__FILE__"}}' "args.payload"
expect_input "[{\"__see\": \"review-units\"}] — ran to completed (wf_f95c1fbf)" DENY \
  '{"script": "return args", "args": [{"__see": "review-units"}]}' 'args[0].__see'
expect_input "{\"__file\": \"doc-units\"} (wf_71a273df)" DENY \
  '{"script": "return args", "args": {"__file": "doc-units"}}' "sentinel key"
expect_input "ids [\"__FROM_FILE__\"] beside real fields (wf_242c61fc)" DENY \
  '{"script": "return args", "args": {"scratch": "/tmp/s", "head": "6845658", "ids": ["__FROM_FILE__"]}}' "args.ids[0]"
expect_input "\"(see packet file)\" inside one packet of 23 (wf_14cbe1f0)" DENY \
  '{"script": "return args", "args": [{"id": "PKT-01", "file": "/tmp/p/PKT-01.json", "safe": true, "files": ["(see packet file)"]}]}' 'args[0].files[0]'
expect_input "\"__FILL__\" (wf_29b3b8ce)" DENY \
  '{"script": "return args", "args": {"sp": "/tmp/s", "buckets": "__FILL__"}}' "args.buckets"
expect_input "an ellipsis as the whole value" DENY '{"script": "return args", "args": {"ids": ["P01", "..."]}}' 'args.ids[1]'
expect_input "a lone <angle> token" DENY '{"script": "return args", "args": {"path": "<scratch path>"}}' "args.path"
expect_input "the deny tells the author what to do instead" DENY \
  '{"script": "return args", "args": {"payload": "__FILE__"}}' "expected count the script asserts"
expect_input "the deny is the same inside a subagent (agent_id)" DENY \
  '{"script": "return args", "args": ["__FILL__"]}' "placeholder" "$TMP/proj" '{"agent_id": "a1b2", "agent_type": "general-purpose"}'

section "Real data passes"
expect_input "ids, counts, paths and an empty list" ALLOW \
  '{"script": "return args", "args": {"ids": ["P01", "P02"], "expected": 2, "file": "/tmp/s/units.json", "creates": []}}'
expect_input "prose that mentions __FILE__, placeholder and (see below)" ALLOW \
  '{"script": "return args", "args": {"task": "the C macro __FILE__ expands to the path; replace the placeholder text (see below)"}}'
expect_input "no args at all" ALLOW '{"script": "return 1"}'

section "Stringified args warn, deny wins over warn"
expect_input "args as a JSON-encoded object warns" WARN \
  '{"script": "return args", "args": "{\"ids\": [\"a\", \"b\"]}"}' "JSON-encoded string"
expect_input "a placeholder plus a silent cut: deny, with the cut named" DENY \
  "$(python3 -c 'import json,sys; print(json.dumps({"script": open(sys.argv[1]).read(), "args": [{"__see": "units"}]}))' "$TMP/cut.js")" \
  "silent-truncation"

# ─── Quota ───────────────────────────────────────────────────────────
section "Quota reading (fresh / stale / missing)"
CACHE="$CLAUDE_CONFIG_DIR/usage-watch-cache.json"
write_cache() {  # write_cache <age-seconds> <7-day %> <5-hour %>
  python3 - "$CACHE" "$1" "$2" "$3" <<'PY'
import json, sys, time
from datetime import datetime, timedelta, timezone
later = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
soon = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
json.dump({"_at": time.time() - float(sys.argv[2]),
           "seven_day": {"utilization": float(sys.argv[3]), "resets_at": later},
           "five_hour": {"utilization": float(sys.argv[4]), "resets_at": soon}}, open(sys.argv[1], "w"))
PY
}
write_cache 60 93 20
expect_input "fresh cache, 7-day at 93%: warn" WARN '{"script": "return 1"}' "7-day at 93%"
expect "the quota warning says what a null means" WARN "come back as null"
write_cache 60 30 88
expect_input "fresh cache, 5-hour at 88%: warn" WARN '{"script": "return 1"}' "5-hour at 88%"
write_cache 3600 99 99
expect_input "a cache an hour old says nothing, however high" ALLOW '{"script": "return 1"}'
write_cache 60 40 10
expect_input "a fresh, cool reading says nothing" ALLOW '{"script": "return 1"}'
rm -f "$CACHE"
expect_input "no cache at all says nothing" ALLOW '{"script": "return 1"}'
printf '{"_at": "yesterday", "seven_day": ' > "$CACHE"
expect_input "a corrupt cache says nothing" ALLOW '{"script": "return 1"}'
expect_input "a corrupt cache never costs the deny" DENY '{"script": "return 1", "args": ["__FILL__"]}'
rm -f "$CACHE"

# The refresh: a fake claude-usage-watch.py beside a copy of the checker
# writes a hot, fresh reading, as the real one does past its TTL.
section "The stale cache is refreshed first (fake watcher, no network)"
mkdir -p "$TMP/scripts"
cp "$CHECKER" "$TMP/scripts/check-workflow-script.py"
cat > "$TMP/scripts/claude-usage-watch.py" <<'PY'
import json, os, sys, time
d = os.environ["CLAUDE_CONFIG_DIR"]
open(os.path.join(d, "watch-argv"), "w").write(" ".join(sys.argv[1:]))
json.dump({"_at": time.time(), "seven_day": {"utilization": 95, "resets_at": "2999-01-01T00:00:00+00:00"},
           "five_hour": {"utilization": 10, "resets_at": "2999-01-01T00:00:00+00:00"}},
          open(os.path.join(d, "usage-watch-cache.json"), "w"))
PY
write_cache 86400 10 10   # a day old: the gate must refresh, not trust it
OUT=$(payload '{"script": "return 1"}' | CLADE_PREFLIGHT_NO_REFRESH=0 CLADE_PREFLIGHT_SCRIPT="$TMP/scripts/check-workflow-script.py" bash "$HOOK" 2>/dev/null); RC=$?
expect "a day-old cache is refreshed before it is read" WARN "7-day at 95%"
if [[ "$(cat "$CLAUDE_CONFIG_DIR/watch-argv" 2>/dev/null)" == "--refresh-only" ]]; then
  pass "the refresh runs the watcher with --refresh-only"
else
  fail "the refresh runs the watcher with --refresh-only" "argv: $(cat "$CLAUDE_CONFIG_DIR/watch-argv" 2>/dev/null || echo '<not run>')"
fi
rm -f "$CACHE" "$CLAUDE_CONFIG_DIR/watch-argv"
OUT=$(payload '{"script": "return 1"}' | CLADE_PREFLIGHT_NO_REFRESH=1 CLADE_PREFLIGHT_SCRIPT="$TMP/scripts/check-workflow-script.py" bash "$HOOK" 2>/dev/null); RC=$?
expect "CLADE_PREFLIGHT_NO_REFRESH=1 skips the refresh" ALLOW
[[ ! -f "$CLAUDE_CONFIG_DIR/watch-argv" ]] && pass "…and the watcher never ran" || fail "…and the watcher never ran"
printf 'import time\ntime.sleep(30)\n' > "$TMP/scripts/claude-usage-watch.py"
write_cache 86400 99 99
start=$(date +%s)
OUT=$(payload '{"script": "return 1", "args": ["__FILL__"]}' | CLADE_PREFLIGHT_NO_REFRESH=0 CLADE_PREFLIGHT_SCRIPT="$TMP/scripts/check-workflow-script.py" bash "$HOOK" 2>/dev/null); RC=$?
elapsed=$(( $(date +%s) - start ))
expect "a hanging refresh still delivers the deny" DENY "placeholder"
if [[ $elapsed -le 9 ]]; then pass "a hanging refresh is cut off (${elapsed}s)"
else fail "a hanging refresh is cut off" "took ${elapsed}s"; fi
# CLADE_PREFLIGHT_DEADLINE: the in-process deadline cuts the same hang at 1 s,
# ahead of the refresh's own 5 s timeout, and the deny found before it prints.
start=$(date +%s)
OUT=$(payload '{"script": "return 1", "args": ["__FILL__"]}' | CLADE_PREFLIGHT_DEADLINE=1 CLADE_PREFLIGHT_NO_REFRESH=0 CLADE_PREFLIGHT_SCRIPT="$TMP/scripts/check-workflow-script.py" bash "$HOOK" 2>/dev/null); RC=$?
elapsed=$(( $(date +%s) - start ))
expect "the deadline fires mid-refresh and the deny still prints" DENY "placeholder"
if [[ $elapsed -le 3 ]]; then pass "a 1 s deadline ends the launch check in ${elapsed}s, not the refresh's 5 s"
else fail "a 1 s deadline ends the launch check before the refresh's 5 s" "took ${elapsed}s"; fi
rm -f "$CACHE"

# ─── No cwd, from a removed directory ────────────────────────────────
section "A removed working directory costs the script check, never the deny"
mkdir -p "$TMP/gone"
printf '%s' '{"tool_name": "Workflow", "tool_input": {"script": "return 1", "args": ["__FILL__"]}}' > "$TMP/nocwd.json"
OUT=$(cd "$TMP/gone" && rmdir "$TMP/gone" && env -u CLAUDE_PROJECT_DIR bash "$HOOK" < "$TMP/nocwd.json" 2>/dev/null); RC=$?
expect "no cwd in the payload, run from a removed directory: denied" DENY "placeholder"

# ─── Failure modes: the hook never blocks a launch by breaking ───────
section "Fail-open"
run_hook '{not json'
expect "malformed stdin: exit 0, no output" ALLOW
run_hook ''
expect "empty stdin: exit 0, no output" ALLOW
run_hook '{"tool_name": "Bash", "tool_input": {"command": "ls"}}'
expect "another tool: no output" ALLOW
run_hook '{"tool_name": "Workflow", "tool_input": "not an object"}'
expect "a non-object tool_input: no output" ALLOW
# These feed stdin from a file: a checker that never reads it would break the
# writer's pipe, and pipefail would blame the hook for the writer's EPIPE.
payload '{"script": "return 1", "args": ["__FILL__"]}' > "$TMP/deny-payload.json"
printf 'import sys\nsys.stderr.write("Traceback (most recent call last): boom\\n")\nraise SystemExit(3)\n' > "$TMP/crash.py"
printf 'import time\ntime.sleep(8)\n' > "$TMP/hang.py"
# 300 KB: past any pipe buffer, so a hook that exits without reading stdin
# breaks the writer's pipe and the writer's exit status shows it.
python3 -c 'import json,sys; print(json.dumps({"tool_name": "Workflow", "cwd": sys.argv[1], "tool_input": {"script": "// " + "x" * 300000 + "\nreturn 1", "args": ["__FILL__"]}}))' "$TMP/proj" > "$TMP/big-payload.json"
mkdir -p "$TMP/nopy"
ln -sf "$(command -v dirname)" "$TMP/nopy/dirname"
ln -sf "$(command -v cat)" "$TMP/nopy/cat"
HAVE_TIMEOUT=""
if command -v timeout >/dev/null 2>&1 || command -v gtimeout >/dev/null 2>&1; then HAVE_TIMEOUT=1; fi
SKIPPED=0

# The wrapper's own guards, as one function so the mutation section below can
# run exactly these cases against each mutated copy of the wrapper.
wrapper_guard_cases() {
  local st err
  OUT=$(CLADE_PREFLIGHT_SCRIPT="$TMP/crash.py" bash "$HOOK" < "$TMP/deny-payload.json" 2>/dev/null); RC=$?
  expect "a crashing checker exits 0 (the launch is not blocked)" ALLOW
  err=$(CLADE_PREFLIGHT_SCRIPT="$TMP/crash.py" bash "$HOOK" < "$TMP/deny-payload.json" 2>&1 >/dev/null)
  if [[ -z "$err" ]]; then pass "a checker's traceback never reaches stderr"
  else fail "a checker's traceback never reaches stderr" "stderr: ${err:0:120}"; fi
  OUT=$(CLADE_PREFLIGHT_SCRIPT="$TMP/missing.py" bash "$HOOK" < "$TMP/deny-payload.json" 2>/dev/null); RC=$?
  expect "a missing checker exits 0 silently" ALLOW
  st=$( { cat "$TMP/big-payload.json" | CLADE_PREFLIGHT_SCRIPT="$TMP/missing.py" bash "$HOOK" >/dev/null 2>&1; echo "${PIPESTATUS[0]} ${PIPESTATUS[1]}"; } )
  if [[ "$st" == "0 0" ]]; then pass "a missing checker still drains stdin (300 KB writer exits 0)"
  else fail "a missing checker still drains stdin" "writer/hook status: $st"; fi
  OUT=$(PATH="$TMP/nopy" "$(command -v bash)" "$HOOK" < "$TMP/deny-payload.json" 2>/dev/null); RC=$?
  expect "no python3 on PATH: exit 0 silently" ALLOW
  st=$( { cat "$TMP/big-payload.json" | PATH="$TMP/nopy" "$(command -v bash)" "$HOOK" >/dev/null 2>&1; echo "${PIPESTATUS[0]} ${PIPESTATUS[1]}"; } )
  if [[ "$st" == "0 0" ]]; then pass "no python3: stdin still drained (300 KB writer exits 0)"
  else fail "no python3: stdin still drained" "writer/hook status: $st"; fi
  OUT=$(bash "$HOOK" < "$TMP/deny-payload.json" 2>/dev/null); RC=$?
  expect "control: the same payload through the real checker is denied" DENY "placeholder"
  st=$( { cat "$TMP/big-payload.json" | bash "$HOOK" >/dev/null 2>&1; echo "${PIPESTATUS[0]} ${PIPESTATUS[1]}"; } )
  if [[ "$st" == "0 0" ]]; then pass "control: the real checker reads a 300 KB payload whole"
  else fail "control: the real checker reads a 300 KB payload whole" "writer/hook status: $st"; fi
  if [[ -n "$HAVE_TIMEOUT" ]]; then
    OUT=$(CLADE_PREFLIGHT_TIMEOUT=abc bash "$HOOK" < "$TMP/deny-payload.json" 2>/dev/null); RC=$?
    expect "a non-numeric CLADE_PREFLIGHT_TIMEOUT falls back to 12 s; the deny still prints" DENY "placeholder"
    start=$(date +%s)
    OUT=$(CLADE_PREFLIGHT_TIMEOUT=2 CLADE_PREFLIGHT_SCRIPT="$TMP/hang.py" bash "$HOOK" < "$TMP/deny-payload.json" 2>/dev/null); RC=$?
    elapsed=$(( $(date +%s) - start ))
    if [[ $RC == 0 && $elapsed -le 6 ]]; then pass "a hanging checker is cut off and exits 0 (${elapsed}s)"
    else fail "a hanging checker is cut off and exits 0" "rc=$RC after ${elapsed}s"; fi
  else
    SKIPPED=$((SKIPPED + 2))
    echo "  SKIP (2): no timeout/gtimeout here — the hang bound is settings-hooks.json's 15 s"
  fi
}
wrapper_guard_cases

# ─── Wiring ──────────────────────────────────────────────────────────
section "Wiring"
SETTINGS="$REPO_ROOT/configs/settings-hooks.json"
jq -e '.hooks.PreToolUse[] | select(.matcher=="Workflow") | .hooks[] | select(.id=="workflow-preflight")
       | (.command | test("workflow-preflight\\.sh$")) and (.statusMessage | length > 0) and (has("async") | not)' \
  "$SETTINGS" >/dev/null 2>&1 \
  && pass "settings-hooks.json wires workflow-preflight on PreToolUse/Workflow, sync, with a statusMessage" \
  || fail "settings-hooks.json wires workflow-preflight on PreToolUse/Workflow, sync, with a statusMessage"
_t=$(jq -r '.hooks.PreToolUse[] | select(.matcher=="Workflow") | .hooks[0].timeout' "$SETTINGS" 2>/dev/null)
if [[ "$_t" =~ ^[0-9]+$ && "$_t" -gt 12 ]]; then pass "the hook timeout ($_t s) outlasts the interpreter bound (12 s)"
else fail "the hook timeout outlasts the interpreter bound (12 s)" "timeout=$_t"; fi
[[ -x "$REPO_ROOT/configs/hooks/workflow-preflight.sh" ]] && pass "the hook is executable" || fail "the hook is executable"

# ─── Mutations: each wrapper guard must be observed ──────────────────
# Remove one guard from a copy of the wrapper, run wrapper_guard_cases against
# it, and require at least one failure; a no-op control must stay green. A
# mutation whose anchor no longer matches the wrapper is a failure, not a skip.
section "Each wrapper guard turns the wrapper cases red when removed"
MUT_ROOT="$TMP/mut"
mkdir -p "$MUT_ROOT/hooks"
ln -sfn "$REPO_ROOT/configs/scripts" "$MUT_ROOT/scripts"
REAL_HOOK="$HOOK"
wrapper_mutation() {  # wrapper_mutation <red|green> <name> <anchor> <replacement>
  local want="$1" name="$2" failed
  if ! python3 - "$REAL_HOOK" "$MUT_ROOT/hooks/workflow-preflight.sh" "$3" "$4" <<'PY'
import sys
src = open(sys.argv[1], encoding="utf-8").read()
if src.count(sys.argv[3]) != 1:
    sys.exit(3)
open(sys.argv[2], "w", encoding="utf-8").write(src.replace(sys.argv[3], sys.argv[4], 1))
PY
  then
    fail "mutation '$name': its anchor no longer matches the wrapper exactly once"
    return 0
  fi
  failed=$(HOOK="$MUT_ROOT/hooks/workflow-preflight.sh"; TESTS_RUN=0; TESTS_PASSED=0; TESTS_FAILED=0
           wrapper_guard_cases >/dev/null 2>&1; echo "$TESTS_FAILED")
  if [[ "$want" == red && "$failed" -gt 0 ]]; then pass "removing $name turns the wrapper cases red ($failed failed)"
  elif [[ "$want" == green && "$failed" -eq 0 ]]; then pass "no-op control stays green: $name"
  else fail "mutation '$name' (want $want)" "$failed wrapper case(s) failed"; fi
}
wrapper_mutation green "a comment reworded" '# Every early exit drains stdin first' '# Every early exit drains  stdin first'
wrapper_mutation red "the stdin drain on an early exit" '_wp_skip() { cat >/dev/null 2>&1; exit 0; }' '_wp_skip() { exit 0; }'
wrapper_mutation red "the python3 presence check" 'command -v python3 >/dev/null 2>&1 || _wp_skip' ':'
wrapper_mutation red "the CLADE_PREFLIGHT_SCRIPT override" 'CHECKER="${CLADE_PREFLIGHT_SCRIPT:-}"' 'CHECKER=""'
wrapper_mutation red "the sibling ../scripts lookup" \
  'if [[ -n "$_wp_sib" && -f "$_wp_sib/check-workflow-script.py" ]]; then' 'if false; then'
wrapper_mutation red "the stderr redirect" \
  '$_WP_TIMEOUT python3 "$CHECKER" --hook 2>/dev/null' '$_WP_TIMEOUT python3 "$CHECKER" --hook'
wrapper_mutation red "the unconditional exit 0" \
  '$_WP_TIMEOUT python3 "$CHECKER" --hook 2>/dev/null
exit 0' '$_WP_TIMEOUT python3 "$CHECKER" --hook 2>/dev/null
exit $?'
if [[ -n "$HAVE_TIMEOUT" ]]; then
  wrapper_mutation red "timeout detection" 'if command -v timeout >/dev/null 2>&1; then' 'if false; then'
  wrapper_mutation red "the numeric check on CLADE_PREFLIGHT_TIMEOUT" '[[ "$_WP_SECS" =~ ^[0-9]+$ ]] || _WP_SECS=12' ':'
else
  SKIPPED=$((SKIPPED + 2))
  echo "  SKIP (2): the timeout mutations need timeout/gtimeout"
fi
HOOK="$REAL_HOOK"

# ─── Summary ─────────────────────────────────────────────────────────
printf "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
[[ "$SKIPPED" -gt 0 ]] && printf "  ${YELLOW}%d case(s) skipped${NC} (not counted as passed)\n" "$SKIPPED"
if [[ "$TESTS_FAILED" -eq 0 ]]; then
  printf "  ${GREEN}ALL PASSED${NC} (%d/%d)\n" "$TESTS_PASSED" "$TESTS_RUN"
else
  printf "  ${RED}FAILED${NC} (%d/%d passed, %d failed)\n" "$TESTS_PASSED" "$TESTS_RUN" "$TESTS_FAILED"
fi
printf "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
[[ "$TESTS_FAILED" -eq 0 ]]
