#!/usr/bin/env bash
# test-kimi-hooks.sh — Kimi 2.6.0 hook protocol and install.sh §11c.
# Every runtime case executes the exact command read from the installed
# config.toml. HOME, KIMI_CODE_HOME, project, runtime and sync state are
# temporary. No Kimi process, network, credential, or real user file is used.
#
# KIMI_SRC_ROOT may point at a git-show/archive copy of the old tree for the
# required RED control. KIMI_ADAPTER_OVERRIDE replaces only the installed
# adapter after installation for guard-ablation controls.

set -uo pipefail

SRC_ROOT="${KIMI_SRC_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
INSTALL_SH="${KIMI_INSTALL_SH:-$SRC_ROOT/install.sh}"
TMP_ROOT=$(mktemp -d)
trap 'rm -rf "$TMP_ROOT"' EXIT

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'
section() { printf "\n${YELLOW}━━━ %s ━━━${NC}\n" "$1"; }
pass() { TESTS_RUN=$((TESTS_RUN + 1)); TESTS_PASSED=$((TESTS_PASSED + 1)); printf "  ${GREEN}✓${NC} %s\n" "$1"; }
fail() {
  TESTS_RUN=$((TESTS_RUN + 1)); TESTS_FAILED=$((TESTS_FAILED + 1))
  printf "  ${RED}✗${NC} %s\n" "$1"
  [[ -z "${2:-}" ]] || printf "    ${RED}→ %s${NC}\n" "$2"
  return 0
}
assert_eq() {
  if [[ "$1" == "$2" ]]; then pass "$3"; else fail "$3" "want='$2' got='$1'"; fi
}
assert_contains() {
  if grep -qF "$2" <<< "$1"; then pass "$3"; else fail "$3" "missing '$2' in: $1"; fi
}
assert_file() {
  if [[ -e "$1" ]]; then pass "$2"; else fail "$2" "missing $1"; fi
}
assert_no_file() {
  if [[ ! -e "$1" ]]; then pass "$2"; else fail "$2" "unexpected $1"; fi
}

for required in jq git python3; do
  command -v "$required" >/dev/null 2>&1 || { echo "missing required test tool: $required"; exit 1; }
done

RUN_HOME="$TMP_ROOT/runtime-home"
RUNTIME="$TMP_ROOT/runtime"
SHADOW="$TMP_ROOT/shadows"
PROJ="$TMP_ROOT/project"
HISTORY="$RUN_HOME/.claude/corrections/history.jsonl"
FAKE_BIN="$TMP_ROOT/no-network-bin"
SYNC_MARKER="$TMP_ROOT/sync-marker"
mkdir -p "$RUN_HOME/.kimi-code" "$RUNTIME" "$SHADOW" "$PROJ/src" "$FAKE_BIN"
printf 'default_model = "kimi-code/k3"\n' > "$RUN_HOME/.kimi-code/config.toml"
for cmd in gh docker tailscale gcloud; do
  printf '#!/usr/bin/env bash\nexit 0\n' > "$FAKE_BIN/$cmd"
  chmod +x "$FAKE_BIN/$cmd"
done

install_home() {
  local home="$1" log="$2"
  HOME="$home" KIMI_CODE_HOME="$home/.kimi-code" \
    bash "$INSTALL_SH" </dev/null > "$log" 2>&1
}

section "install the runtime fixture"
if install_home "$RUN_HOME" "$TMP_ROOT/runtime-install.log"; then
  pass "install.sh succeeds against the temporary HOME"
else
  fail "install.sh succeeds against the temporary HOME" "see $TMP_ROOT/runtime-install.log"
  printf '\n%d passed, %d failed, %d total\n' "$TESTS_PASSED" "$TESTS_FAILED" "$TESTS_RUN"
  exit 1
fi
if [[ -n "${KIMI_ADAPTER_OVERRIDE:-}" ]]; then
  cp "$KIMI_ADAPTER_OVERRIDE" "$RUN_HOME/.kimi-code/hooks/decision-to-kimi.sh"
  chmod +x "$RUN_HOME/.kimi-code/hooks/decision-to-kimi.sh"
fi

git -C "$PROJ" init -q
git -C "$PROJ" config user.email kimi-hooks@example.invalid
git -C "$PROJ" config user.name kimi-hooks
printf '# fixture\n' > "$PROJ/CLAUDE.md"
printf 'one\n' > "$PROJ/src/app.py"
git -C "$PROJ" add -A
git -C "$PROJ" commit -qm 'fixture initial'

hook_command() {
  python3 - "$1/.kimi-code/config.toml" "$2" "$3" <<'PY'
import re, sys
path, event, hook = sys.argv[1:]
blocks, current = [], None
for line in open(path, encoding="utf-8"):
    if line.strip() == "[[hooks]]":
        if current is not None:
            blocks.append(current)
        current = [line]
    elif line.startswith("["):
        if current is not None:
            blocks.append(current)
        current = None
    elif current is not None:
        current.append(line)
if current is not None:
    blocks.append(current)
for block in blocks:
    text = "".join(block)
    def field(name):
        match = re.search(r"(?m)^" + re.escape(name) + r'\s*=\s*"((?:[^"\\]|\\.)*)"\s*$', text)
        return match.group(1) if match else None
    command = field("command") or ""
    if field("event") == event and ("/" + hook) in command:
        print(command)
        break
PY
}

RUN_OUT=""
RUN_RC=0
run_hook() {
  local event="$1" hook="$2" payload="$3" cmd
  cmd=$(hook_command "$RUN_HOME" "$event" "$hook")
  if [[ -z "$cmd" ]]; then
    RUN_OUT="MISSING COMMAND: $event/$hook"
    RUN_RC=97
    return
  fi
  RUN_OUT=$(printf '%s' "$payload" | HOME="$RUN_HOME" KIMI_CODE_HOME="$RUN_HOME/.kimi-code" \
    CLAUDE_PROJECT_DIR="$PROJ" CLADE_RUNTIME_DIR="$RUNTIME" CP_SHADOW_DIR="$SHADOW" \
    SYNC_MARKER="$SYNC_MARKER" PATH="$FAKE_BIN:$PATH" bash -c "$cmd" 2>"$TMP_ROOT/last-stderr")
  RUN_RC=$?
}

# Mirror internal/runHook.ts:resultFromExitCode and structuredOutput.
kimi_verdict() {
  if [[ "$RUN_RC" == 2 ]]; then printf 'BLOCK'; return; fi
  if [[ "$RUN_RC" != 0 ]]; then printf 'ALLOW'; return; fi
  if [[ -z "${RUN_OUT//[[:space:]]/}" ]]; then printf 'ALLOW'; return; fi
  if jq -e '(.hookSpecificOutput.permissionDecision? // "") == "deny"' <<< "$RUN_OUT" >/dev/null 2>&1; then
    printf 'BLOCK'
  elif jq -e '(.message? | type) == "string" or (.hookSpecificOutput.message? | type) == "string"' <<< "$RUN_OUT" >/dev/null 2>&1; then
    printf 'MESSAGE'
  else
    printf 'ALLOW'
  fi
}
assert_verdict() {
  local got
  got=$(kimi_verdict)
  assert_eq "$got" "$2" "$1 (rc=$RUN_RC, verdict=$got)"
}
run_payload() {
  run_hook "$1" "$2" "$3"
  assert_verdict "$4" "$5"
}

prompt_payload() {
  jq -nc --arg sid "$1" --arg prompt "$2" --arg cwd "$PROJ" \
    '{hook_event_name:"UserPromptSubmit",session_id:$sid,cwd:$cwd,
      prompt:[{type:"text",text:"first part"},{type:"image_url",imageUrl:{url:"fixture"}},{type:"text",text:$prompt}]}'
}
tool_payload() {
  jq -nc --arg event "$1" --arg sid "$2" --arg name "$3" --argjson input "$4" --arg cwd "$PROJ" \
    '{hook_event_name:$event,session_id:$sid,cwd:$cwd,tool_name:$name,tool_input:$input,tool_call_id:"call_fixture",tool_output:"fixture output"}'
}

section "PreToolUse guards through the installed commands"
run_payload PreToolUse pre-tool-guardian.sh \
  "$(tool_payload PreToolUse session_guard Bash '{"command":"git push --force origin main"}')" \
  "guardian denies a force push to main" BLOCK
assert_contains "$(jq -r '.hookSpecificOutput.permissionDecisionReason // empty' <<< "$RUN_OUT")" \
  "Force push to main/master blocked" "guardian preserves its own deny reason"
run_payload PreToolUse pre-tool-guardian.sh \
  "$(tool_payload PreToolUse session_guard Bash '{"command":"git status --short"}')" \
  "guardian allows a safe Bash call" ALLOW
run_payload PreToolUse pre-tool-guardian.sh \
  "$(tool_payload PreToolUse session_guard Bash '{"command":"rm -rf $BUILD_DIR/"}')" \
  "guardian rewrite becomes a deny, never an original-command allow" BLOCK
assert_contains "$(jq -r '.hookSpecificOutput.permissionDecisionReason // empty' <<< "$RUN_OUT")" \
  'BUILD_DIR:?' "rewrite denial names the safer command"
run_payload PreToolUse linter-config-guard.sh \
  "$(tool_payload PreToolUse session_lint Edit '{"path":"/tmp/.ruff.toml","old_string":"a","new_string":"b"}')" \
  "linter guard sees Kimi's Edit path and denies" BLOCK
assert_contains "$(jq -r '.hookSpecificOutput.permissionDecisionReason // empty' <<< "$RUN_OUT")" \
  "/tmp/.ruff.toml" "linter denial names the protected path"
run_payload PreToolUse linter-config-guard.sh \
  "$(tool_payload PreToolUse session_lint Write '{"path":"/tmp/app.py","content":"print(1)\n"}')" \
  "linter guard allows an ordinary Write" ALLOW

section "UserPromptSubmit prompt arrays, context and attribution"
SECRET='sk-'"test-1234567890abcdefghij"  # split so the staged-diff secret scan does not see a literal key
run_payload UserPromptSubmit secret-scanner.sh \
  "$(prompt_payload session_secret "credential is $SECRET")" \
  "secret scanner reads prompt parts and emits a Kimi message" MESSAGE
assert_contains "$(jq -r '.message // empty' <<< "$RUN_OUT")" \
  "Handle it as data" "secret note is the wrapped hook's own handling guidance"
run_payload UserPromptSubmit secret-scanner.sh \
  "$(prompt_payload session_secret "ordinary request with no credential")" \
  "secret scanner stays silent on a safe prompt" ALLOW

SID='session_c49ae4fd-1b85-4f0f-aaaa-bbbbbbbbbbbb'
run_payload UserPromptSubmit correction-detector.sh \
  "$(prompt_payload "$SID" "No, that is wrong. Use the safer approach instead.")" \
  "correction detector reads prompt parts and emits a Kimi message" MESSAGE
assert_contains "$(jq -r '.message // empty' <<< "$RUN_OUT")" \
  "possible correction" "correction context reaches Kimi's message field"
LAST=$(tail -n 1 "$HISTORY" 2>/dev/null)
assert_eq "$(jq -r '.session_id // empty' <<< "$LAST")" "$SID" \
  "correction history keeps Kimi's session_ id intact"
assert_eq "$(jq -r 'has("transcript_path") and (.transcript_path == null)' <<< "$LAST")" "true" \
  "missing Kimi transcript_path persists as null"
BEFORE=$(wc -l < "$HISTORY" | tr -d ' ')
run_payload UserPromptSubmit correction-detector.sh \
  "$(prompt_payload "$SID" "Please refactor the parser and add coverage.")" \
  "correction detector stays silent on a non-correction" ALLOW
assert_eq "$(wc -l < "$HISTORY" | tr -d ' ')" "$BEFORE" \
  "safe prompt writes no correction record"

section "data-only correction loop and cleanup"
run_payload PostToolUse edit-shadow-detector.sh \
  "$(tool_payload PostToolUse "$SID" Edit "{\"path\":\"$PROJ/src/app.py\",\"old_string\":\"one\",\"new_string\":\"two\"}")" \
  "edit shadow records through Kimi's path argument without output" ALLOW
SHADOW_FILE="$SHADOW/session-$SID.jsonl"
assert_file "$SHADOW_FILE" "edit shadow uses the intact Kimi session id"
assert_contains "$(cat "$SHADOW_FILE" 2>/dev/null)" "$PROJ/src/app.py" "edit shadow records the written file"
run_payload PostToolUse revert-detector.sh \
  "$(tool_payload PostToolUse "$SID" Bash '{"command":"git checkout -- src/app.py"}')" \
  "PostToolUse revert detector stays data-only" ALLOW
LAST=$(tail -n 1 "$HISTORY" 2>/dev/null)
assert_eq "$(jq -r '.type // empty' <<< "$LAST")" "implicit-revert" "revert is recorded after the Bash call"
assert_eq "$(jq -r '.session_id // empty' <<< "$LAST")" "$SID" "revert history keeps the session_ id"
assert_eq "$(jq -r '.transcript_path == null' <<< "$LAST")" "true" "revert transcript_path is null, not a crash"
assert_contains "$(jq -c '.reverted_files' <<< "$LAST")" "src/app.py" "revert pairs the file recorded by the shadow"
BEFORE=$(wc -l < "$HISTORY" | tr -d ' ')
run_payload PostToolUse revert-detector.sh \
  "$(tool_payload PostToolUse "$SID" Bash '{"command":"git status --short"}')" \
  "an ordinary Bash result writes no revert record" ALLOW
assert_eq "$(wc -l < "$HISTORY" | tr -d ' ')" "$BEFORE" "safe Bash leaves history unchanged"
run_payload SessionEnd session-end-cleanup.sh \
  "$(tool_payload SessionEnd "$SID" Bash '{"command":""}')" \
  "SessionEnd cleanup has no protocol output" ALLOW
assert_no_file "$SHADOW_FILE" "SessionEnd removes only the ending session's shadow"

section "session baseline and one-continuation Stop guard"
STOP_SID='session_stop_guard_01'
run_payload SessionStart session-baseline.sh \
  "$(tool_payload SessionStart "$STOP_SID" Bash '{"command":""}')" \
  "SessionStart baseline needs no model channel" ALLOW
BASELINE="$PROJ/.claude/sessions/$STOP_SID.baseline"
assert_file "$BASELINE" "SessionStart writes the stop-check baseline"
printf 'dirty\n' > "$PROJ/src/new-file.txt"
run_payload Stop stop-check.sh \
  "$(jq -nc --arg sid "$STOP_SID" --arg cwd "$PROJ" '{hook_event_name:"Stop",session_id:$sid,cwd:$cwd,stop_hook_active:false}')" \
  "stop-check exit-2 becomes a Kimi block" BLOCK
assert_contains "$(jq -r '.hookSpecificOutput.permissionDecisionReason // empty' <<< "$RUN_OUT")" \
  "uncommitted change" "Stop block carries the hook's stderr reason"
CLEAN_SID='session_stop_clean_01'
run_payload SessionStart session-baseline.sh \
  "$(tool_payload SessionStart "$CLEAN_SID" Bash '{"command":""}')" \
  "a second baseline runs for the clean-stop fixture" ALLOW
run_payload Stop stop-check.sh \
  "$(jq -nc --arg sid "$CLEAN_SID" --arg cwd "$PROJ" '{hook_event_name:"Stop",session_id:$sid,cwd:$cwd,stop_hook_active:false}')" \
  "stop-check allows a session with no new dirt" ALLOW

section "SessionStart context is delivered once on the first prompt"
CONTEXT_SID='session_context_once_01'
PAYLOAD=$(prompt_payload "$CONTEXT_SID" "Please continue the current task")
run_payload UserPromptSubmit session-context.sh "$PAYLOAD" \
  "session context reaches the first Kimi prompt" MESSAGE
assert_contains "$(jq -r '.message // empty' <<< "$RUN_OUT")" "Recent commits:" \
  "first-prompt message contains the wrapped SessionStart context"
SENTINEL="$RUNTIME/kimi-session-context/$CONTEXT_SID.session-context.sh.once"
assert_file "$SENTINEL" "once-per-session sentinel lives under the private runtime dir"
run_payload UserPromptSubmit session-context.sh "$PAYLOAD" \
  "the same session gets no duplicate context" ALLOW
run_payload UserPromptSubmit session-context.sh \
  "$(prompt_payload session_context_once_02 "Please continue")" \
  "a different Kimi session gets its own context" MESSAGE

section "memory sync on both PostToolUse matchers"
: > "$RUN_HOME/.claude/.sync-config"
cat > "$RUN_HOME/.claude/scripts/sync-push.sh" <<'EOF'
#!/usr/bin/env bash
printf 'push\n' >> "$SYNC_MARKER"
EOF
chmod +x "$RUN_HOME/.claude/scripts/sync-push.sh"
run_payload PostToolUse memory-sync.sh \
  "$(tool_payload PostToolUse session_memory Edit "{\"path\":\"$RUN_HOME/.claude/hooks/learned.md\",\"old_string\":\"a\",\"new_string\":\"b\"}")" \
  "memory-sync Edit is fire-and-forget with no stdout" ALLOW
for _ in $(seq 1 50); do [[ -f "$SYNC_MARKER" ]] && break; sleep 0.1; done
assert_eq "$(grep -c '^push$' "$SYNC_MARKER" 2>/dev/null || true)" "1" \
  "Kimi Edit path triggers the real memory-sync entry point"
run_payload PostToolUse memory-sync.sh \
  "$(tool_payload PostToolUse session_memory Bash '{"command":"touch ~/.claude/hooks/another.md"}')" \
  "memory-sync Bash is also fire-and-forget" ALLOW
for _ in $(seq 1 50); do [[ "$(grep -c '^push$' "$SYNC_MARKER" 2>/dev/null || true)" == 2 ]] && break; sleep 0.1; done
assert_eq "$(grep -c '^push$' "$SYNC_MARKER" 2>/dev/null || true)" "2" \
  "the distinct Bash wiring invokes the same command again"
run_payload PostToolUse memory-sync.sh \
  "$(tool_payload PostToolUse session_memory Edit "{\"path\":\"$PROJ/src/app.py\",\"old_string\":\"one\",\"new_string\":\"two\"}")" \
  "an unsynced path is a safe no-op" ALLOW
assert_eq "$(grep -c '^push$' "$SYNC_MARKER" 2>/dev/null || true)" "2" \
  "unsynced Edit does not invoke sync-push"

section "remaining adapter protocol forms and fail-open"
ADAPTER="$RUN_HOME/.kimi-code/hooks/decision-to-kimi.sh"
LEGACY="$TMP_ROOT/legacy-block.sh"
cat > "$LEGACY" <<'EOF'
#!/usr/bin/env bash
cat >/dev/null
printf '%s' '{"decision":"block","reason":"legacy block reason"}'
EOF
chmod +x "$LEGACY"
RUN_OUT=$(prompt_payload session_legacy "block this" | HOME="$RUN_HOME" "$ADAPTER" "$LEGACY")
RUN_RC=$?
assert_verdict "legacy decision:block becomes a Kimi block" BLOCK
assert_contains "$(jq -r '.hookSpecificOutput.permissionDecisionReason // empty' <<< "$RUN_OUT")" \
  "legacy block reason" "legacy block reason survives"
LEGACY_REWRITE="$TMP_ROOT/legacy-rewrite.sh"
cat > "$LEGACY_REWRITE" <<'EOF'
#!/usr/bin/env bash
cat >/dev/null
printf '%s' '{"decision":"allow","updatedInput":{"command":"echo safer"}}'
EOF
chmod +x "$LEGACY_REWRITE"
RUN_OUT=$(prompt_payload session_legacy_rewrite "rewrite this" | HOME="$RUN_HOME" "$ADAPTER" "$LEGACY_REWRITE")
RUN_RC=$?
assert_verdict "legacy top-level updatedInput becomes a deny" BLOCK
assert_contains "$(jq -r '.hookSpecificOutput.permissionDecisionReason // empty' <<< "$RUN_OUT")" \
  "echo safer" "legacy rewrite denial names the safer command"
NONCOMMAND_REWRITE="$TMP_ROOT/noncommand-rewrite.sh"
cat > "$NONCOMMAND_REWRITE" <<'EOF'
#!/usr/bin/env bash
cat >/dev/null
printf '%s' '{"hookSpecificOutput":{"updatedInput":{"file_path":"/tmp/safer.txt"}}}'
EOF
chmod +x "$NONCOMMAND_REWRITE"
RUN_OUT=$(prompt_payload session_noncommand_rewrite "rewrite this" | HOME="$RUN_HOME" "$ADAPTER" "$NONCOMMAND_REWRITE")
RUN_RC=$?
assert_verdict "a non-command updatedInput is still refused, never dropped" BLOCK
assert_contains "$(jq -r '.hookSpecificOutput.permissionDecisionReason // empty' <<< "$RUN_OUT")" \
  "/tmp/safer.txt" "non-command rewrite denial describes the requested input"
EMPTY_BLOCK="$TMP_ROOT/empty-block.sh"
printf '#!/usr/bin/env bash\ncat >/dev/null\nexit 2\n' > "$EMPTY_BLOCK"
chmod +x "$EMPTY_BLOCK"
RUN_OUT=$(prompt_payload session_empty_block "stop" | HOME="$RUN_HOME" "$ADAPTER" "$EMPTY_BLOCK" 2>/dev/null)
RUN_RC=$?
assert_verdict "exit 2 with no stderr still blocks" BLOCK
assert_contains "$(jq -r '.hookSpecificOutput.permissionDecisionReason // empty' <<< "$RUN_OUT")" \
  "Blocked by UserPromptSubmit hook" "an empty block reason gets Kimi's default reason"
EMPTY_JSON="$TMP_ROOT/empty-json-block.sh"
printf '#!/usr/bin/env bash\ncat >/dev/null\nprintf "%%s" '\''{"decision":"block"}'\''\n' > "$EMPTY_JSON"
chmod +x "$EMPTY_JSON"
RUN_OUT=$(prompt_payload session_empty_json "stop" | HOME="$RUN_HOME" "$ADAPTER" "$EMPTY_JSON")
RUN_RC=$?
assert_contains "$(jq -r '.hookSpecificOutput.permissionDecisionReason // empty' <<< "$RUN_OUT")" \
  "Blocked by UserPromptSubmit hook" "an empty JSON block reason also gets the default"
MALFORMED="$TMP_ROOT/malformed-input.sh"
cat > "$MALFORMED" <<'EOF'
#!/usr/bin/env bash
input=$(cat)
if [[ "$input" == '{broken' ]]; then
  printf '%s' '{"decision":"block","reason":"raw input preserved"}'
else
  printf '%s' '{"decision":"block","reason":"raw input lost"}'
fi
EOF
chmod +x "$MALFORMED"
RUN_OUT=$(printf '{broken' | HOME="$RUN_HOME" "$ADAPTER" "$MALFORMED")
RUN_RC=$?
assert_contains "$(jq -r '.hookSpecificOutput.permissionDecisionReason // empty' <<< "$RUN_OUT")" \
  "raw input preserved" "malformed JSON reaches the wrapped hook unchanged under fail-open"
printf 'not a directory\n' > "$TMP_ROOT/runtime-blocker"
RUN_OUT=$(prompt_payload session_runtime_failure "continue" | HOME="$RUN_HOME" CLAUDE_PROJECT_DIR="$PROJ" \
  CLADE_RUNTIME_DIR="$TMP_ROOT/runtime-blocker" "$ADAPTER" --once-per-session \
  "$RUN_HOME/.claude/hooks/session-context.sh")
RUN_RC=$?
assert_eq "$RUN_RC|$RUN_OUT" "0|" "unavailable private runtime state fails open without context"
PLAIN="$TMP_ROOT/plain-context.sh"
cat > "$PLAIN" <<'EOF'
#!/usr/bin/env bash
cat >/dev/null
printf 'plain prompt context'
EOF
chmod +x "$PLAIN"
RUN_OUT=$(prompt_payload session_plain "continue" | HOME="$RUN_HOME" "$ADAPTER" "$PLAIN")
RUN_RC=$?
assert_eq "$RUN_OUT" "plain prompt context" "plain stdout uses Kimi's prompt-context channel unchanged"
RUN_OUT=$(printf '{}' | "$ADAPTER" "$TMP_ROOT/does-not-exist" 2>/dev/null)
RUN_RC=$?
assert_eq "$RUN_RC|$RUN_OUT" "0|" "missing wrapped hook fails open"
NONZERO="$TMP_ROOT/nonzero-hook.sh"
cat > "$NONZERO" <<'EOF'
#!/usr/bin/env bash
cat >/dev/null
printf 'partial output that must not be injected'
exit 1
EOF
chmod +x "$NONZERO"
RUN_OUT=$(prompt_payload session_nonzero "continue" | HOME="$RUN_HOME" "$ADAPTER" "$NONZERO" 2>/dev/null)
RUN_RC=$?
assert_eq "$RUN_RC|$RUN_OUT" "0|" "a non-zero, non-block wrapped exit fails open without partial context"
WRONG_EVENT="$RUNTIME/kimi-session-context/session_wrong_event.session-context.sh.once"
RUN_OUT=$(tool_payload SessionStart session_wrong_event Bash '{"command":""}' | \
  HOME="$RUN_HOME" CLAUDE_PROJECT_DIR="$PROJ" CLADE_RUNTIME_DIR="$RUNTIME" \
  "$ADAPTER" --once-per-session "$RUN_HOME/.claude/hooks/session-context.sh")
RUN_RC=$?
assert_eq "$RUN_RC|$RUN_OUT" "0|" "once-only context does not run on SessionStart itself"
assert_no_file "$WRONG_EVENT" "wrong-event invocation writes no once sentinel"
BAD_ID='bad.id'
BAD_SENTINEL="$RUNTIME/kimi-session-context/$BAD_ID.session-context.sh.once"
RUN_OUT=$(prompt_payload "$BAD_ID" "continue" | HOME="$RUN_HOME" CLAUDE_PROJECT_DIR="$PROJ" \
  CLADE_RUNTIME_DIR="$RUNTIME" "$ADAPTER" --once-per-session "$RUN_HOME/.claude/hooks/session-context.sh")
RUN_RC=$?
assert_eq "$RUN_RC|$RUN_OUT" "0|" "a non-Kimi-shaped session id cannot arm first-prompt context"
assert_no_file "$BAD_SENTINEL" "invalid session id writes no sentinel"
NORMALISE="$TMP_ROOT/normalise-check.sh"
cat > "$NORMALISE" <<'EOF'
#!/usr/bin/env bash
input=$(cat)
jq -nr --argjson input "$input" '
  if ($input.hook_event_name == "UserPromptSubmit"
      and ($input.prompt | type) == "string"
      and ($input | has("transcript_path"))
      and $input.transcript_path == null)
  then "normalised" else "not normalised" end'
EOF
chmod +x "$NORMALISE"
RUN_OUT=$(prompt_payload session_normalise "one two" | HOME="$RUN_HOME" "$ADAPTER" "$NORMALISE")
RUN_RC=$?
assert_eq "$RUN_OUT" "normalised" "event name, prompt string and null transcript reach the wrapped hook"
EVENT_DEFAULT="$TMP_ROOT/event-default-check.sh"
cat > "$EVENT_DEFAULT" <<'EOF'
#!/usr/bin/env bash
input=$(cat)
jq -nr --argjson input "$input" '
  {hookSpecificOutput:{permissionDecision:"deny",permissionDecisionReason:(
    if ($input | has("hook_event_name")) then "event key present" else "event key missing" end)}}'
EOF
chmod +x "$EVENT_DEFAULT"
RUN_OUT=$(jq -nc '{session_id:"session_event_default",prompt:[{type:"text",text:"continue"}]}' | \
  HOME="$RUN_HOME" "$ADAPTER" "$EVENT_DEFAULT")
RUN_RC=$?
assert_contains "$(jq -r '.hookSpecificOutput.permissionDecisionReason // empty' <<< "$RUN_OUT")" \
  "event key present" "adapter supplies hook_event_name even for a hand-piped payload"

section "installer migration, idempotency and user entries"
check_config() {
  python3 - "$1" "$2" "$3" <<'PY'
import re, sys
home, expected_total, user_mode = sys.argv[1], int(sys.argv[2]), sys.argv[3]
path = home + "/.kimi-code/config.toml"
text = open(path, encoding="utf-8").read()
raw = re.split(r"(?m)^\[\[hooks\]\]\s*$", text)[1:]
entries = []
for chunk in raw:
    chunk = re.split(r"(?m)^\[(?!\[hooks\]\])", chunk, maxsplit=1)[0]
    def field(name):
        m = re.search(r"(?m)^" + name + r"\s*=\s*(.+?)\s*$", chunk)
        return m.group(1).strip() if m else None
    entries.append({k: field(k) for k in ("event", "matcher", "command", "timeout")})
specs = [
    ("PreToolUse", "Bash", "pre-tool-guardian.sh", "5", ""),
    ("PreToolUse", "Edit|Write", "linter-config-guard.sh", "5", ""),
    ("UserPromptSubmit", "", "secret-scanner.sh", "5", ""),
    ("UserPromptSubmit", "", "correction-detector.sh", "5", ""),
    ("PostToolUse", "Edit|Write", "edit-shadow-detector.sh", "5", ""),
    ("PostToolUse", "Bash", "revert-detector.sh", "5", ""),
    ("SessionStart", "startup|clear", "session-baseline.sh", "5", ""),
    ("SessionEnd", "", "session-end-cleanup.sh", "5", ""),
    ("UserPromptSubmit", "", "session-context.sh", "10", "--once-per-session "),
    ("Stop", "", "stop-check.sh", "10", ""),
    ("PostToolUse", "Edit|Write", "memory-sync.sh", "10", ""),
    ("PostToolUse", "Bash", "memory-sync.sh", "10", ""),
]
errors = []
if len(entries) != expected_total:
    errors.append(f"entry count {len(entries)} != {expected_total}")
for event, matcher, hook, timeout, mode in specs:
    command = f'"{home}/.kimi-code/hooks/decision-to-kimi.sh {mode}{home}/.claude/hooks/{hook}"'
    matches = [e for e in entries if e == {"event": f'"{event}"', "matcher": f'"{matcher}"', "command": command, "timeout": timeout}]
    if len(matches) != 1:
        errors.append(f"{event}/{matcher}/{hook}: exact entry count {len(matches)}")
if user_mode == "user":
    user = '"custom-user-hook"'
    if sum(e["command"] == user for e in entries) != 1:
        errors.append("user-written entry missing or duplicated")
if errors:
    print("; ".join(errors))
    sys.exit(1)
PY
}

OLD_HOME="$TMP_ROOT/old-guardian-home"
mkdir -p "$OLD_HOME/.kimi-code"
cat > "$OLD_HOME/.kimi-code/config.toml" <<EOF
default_model = "kimi-code/k3"

[[hooks]]
event = "PreToolUse"
matcher = "Bash"
command = "$OLD_HOME/.kimi-code/hooks/decision-to-kimi.sh $OLD_HOME/.claude/hooks/pre-tool-guardian.sh"
timeout = 5
EOF
install_home "$OLD_HOME" "$TMP_ROOT/old-install-1.log"
OLD_RC=$?
assert_eq "$OLD_RC" "0" "legacy-only guardian home installs successfully"
OLD_CHECK=$(check_config "$OLD_HOME" 12 legacy 2>&1)
assert_eq "$OLD_CHECK" "" "legacy guardian migrates to exactly the 12-entry portable set"
install_home "$OLD_HOME" "$TMP_ROOT/old-install-2.log"
SECOND_CHECK=$(check_config "$OLD_HOME" 12 legacy 2>&1)
assert_eq "$SECOND_CHECK" "" "second install adds no duplicate entries"

USER_HOME="$TMP_ROOT/user-hook-home"
mkdir -p "$USER_HOME/.kimi-code"
cat > "$USER_HOME/.kimi-code/config.toml" <<'EOF'
default_model = "kimi-code/k3"

[[hooks]]
event = "SessionStart"
matcher = "custom-user-matcher"
command = "custom-user-hook"
timeout = 17
EOF
USER_BLOCK=$(sed -n '/^\[\[hooks\]\]$/,$p' "$USER_HOME/.kimi-code/config.toml")
install_home "$USER_HOME" "$TMP_ROOT/user-install-1.log"
USER_CHECK=$(check_config "$USER_HOME" 13 user 2>&1)
assert_eq "$USER_CHECK" "" "user-written hook survives beside the portable set"
install_home "$USER_HOME" "$TMP_ROOT/user-install-2.log"
USER_CHECK=$(check_config "$USER_HOME" 13 user 2>&1)
assert_eq "$USER_CHECK" "" "reinstall preserves the user entry exactly once"
assert_eq "$(sed -n '/^\[\[hooks\]\]$/,$p' "$USER_HOME/.kimi-code/config.toml" | head -5)" "$USER_BLOCK" \
  "the user-written TOML block is byte-for-byte untouched"

EMPTY_HOME="$TMP_ROOT/no-config-home"
mkdir -p "$EMPTY_HOME/.kimi-code"
install_home "$EMPTY_HOME" "$TMP_ROOT/no-config-install.log"
assert_no_file "$EMPTY_HOME/.kimi-code/config.toml" "installer never fabricates Kimi config.toml"

printf '\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
if [[ "$TESTS_FAILED" == 0 ]]; then
  printf "  ${GREEN}ALL PASSED${NC} (%d/%d)\n" "$TESTS_PASSED" "$TESTS_RUN"
else
  printf "  ${RED}%d FAILED${NC} / %d passed / %d total\n" "$TESTS_FAILED" "$TESTS_PASSED" "$TESTS_RUN"
fi
printf '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
exit "$TESTS_FAILED"
