#!/usr/bin/env bash
# test-codex-hooks.sh — Codex 0.169.0 user-hook discovery, Clade's adapter, and
# uninstall.sh taking the wiring out again.
# Every runtime case executes the exact command installed in hooks.json. HOME,
# CODEX_HOME, project, runtime, sync state and git repositories are temporary.
# No Codex/Kimi process, network, credential or real user file is used.
#
# CODEX_SRC_ROOT/CODEX_INSTALL_SH/CODEX_UNINSTALL_SH point at an old tree for the RED control.
# CODEX_ADAPTER_OVERRIDE/CODEX_MERGER_OVERRIDE support guard-ablation controls.

set -uo pipefail

SRC_ROOT="${CODEX_SRC_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
INSTALL_SH="${CODEX_INSTALL_SH:-$SRC_ROOT/install.sh}"
UNINSTALL_SH="${CODEX_UNINSTALL_SH:-$SRC_ROOT/uninstall.sh}"
MERGER="${CODEX_MERGER_OVERRIDE:-$SRC_ROOT/configs/scripts/codex-hooks-merge.py}"
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
assert_probe() {
  local errors rc
  errors=$($1 "$2" "$3" 2>&1)
  rc=$?
  assert_eq "$rc|$errors" "0|" "$4"
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
mkdir -p "$RUN_HOME" "$RUNTIME" "$SHADOW" "$PROJ/src" "$FAKE_BIN"
for cmd in gh docker tailscale gcloud; do
  printf '#!/usr/bin/env bash\nexit 0\n' > "$FAKE_BIN/$cmd"
  chmod +x "$FAKE_BIN/$cmd"
done

install_home() {
  local home="$1" log="$2"
  HOME="$home" CODEX_HOME="$home/.codex" \
    PATH="$FAKE_BIN:$PATH" bash "$INSTALL_SH" </dev/null > "$log" 2>&1
}

amsg_fixture() {
  local home="$1"
  mkdir -p "$home/.codex"
  python3 - "$home/.codex/hooks.json" <<'PY'
import json, sys
from pathlib import Path
fixture = {
    "description": "amsg user hooks fixture",
    "futureTop": {"preserve": [1, 2, 3]},
    "hooks": {
        event: [{
            "hooks": [{
                "type": "command",
                "command": f"/fake/amsg/{event.lower()}",
                "timeout": 4,
                **({"additionalContextLimit": 900} if event == "SessionStart" else {}),
                "futureHandler": "preserve",
            }]
        }]
        for event in ("SessionStart", "UserPromptSubmit", "Stop", "SessionEnd")
    },
}
Path(sys.argv[1]).write_text(json.dumps(fixture, indent=1) + "\n", encoding="utf-8")
PY
}

SPECS=(
  $'PreToolUse\t^(Edit|Write)$\tlinter-config-guard.sh\t5\tsync'
  $'UserPromptSubmit\t\tsecret-scanner.sh\t5\tsync'
  $'UserPromptSubmit\t\tcorrection-detector.sh\t5\tsync'
  $'PostToolUse\t^(Edit|Write)$\tedit-shadow-detector.sh\t5\tasync'
  $'PreToolUse\t^Bash$\trevert-detector.sh\t5\tasync'
  $'SessionStart\t^(startup|clear|fork)$\tsession-baseline.sh\t5\tsync'
  $'SessionEnd\t\tsession-end-cleanup.sh\t3\tsync'
  $'Stop\t\tstop-check.sh\t10\tsync'
  $'PostToolUse\t^(Edit|Write)$\tmemory-sync.sh\t10\tasync'
  $'PostToolUse\t^Bash$\tmemory-sync.sh\t10\tasync'
)
spec_text() { printf '%s\n' "${SPECS[@]}"; }

check_wiring() {
  python3 - "$1" <<'PY'
import json, sys
from pathlib import Path
home = Path(sys.argv[1])
path = home / ".codex" / "hooks.json"
errors = []
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except Exception as exc:
    print(f"hooks.json: {exc}")
    raise SystemExit(0)
specs = [
    ("PreToolUse", "^(Edit|Write)$", "linter-config-guard.sh", 5, False),
    ("UserPromptSubmit", "", "secret-scanner.sh", 5, False),
    ("UserPromptSubmit", "", "correction-detector.sh", 5, False),
    ("PostToolUse", "^(Edit|Write)$", "edit-shadow-detector.sh", 5, True),
    ("PreToolUse", "^Bash$", "revert-detector.sh", 5, True),
    ("SessionStart", "^(startup|clear|fork)$", "session-baseline.sh", 5, False),
    ("SessionEnd", "", "session-end-cleanup.sh", 3, False),
    ("Stop", "", "stop-check.sh", 10, False),
    ("PostToolUse", "^(Edit|Write)$", "memory-sync.sh", 10, True),
    ("PostToolUse", "^Bash$", "memory-sync.sh", 10, True),
]
entries = []
for event, groups in data.get("hooks", {}).items():
    for group in groups:
        for handler in group["hooks"]:
            entries.append((event, group.get("matcher") or "", handler))
adapter = home / ".codex" / "clade-hooks" / "decision-to-codex.sh"
for event, matcher, hook, timeout, asynchronous in specs:
    command = f'"{adapter}" "{home}/.claude/hooks/{hook}"'
    hits = [h for e, m, h in entries if e == event and m == matcher and h.get("command") == command]
    if len(hits) != 1:
        errors.append(f"{event}/{matcher}/{hook}: count={len(hits)}")
    elif hits[0].get("timeout") != timeout or bool(hits[0].get("async", False)) != asynchronous:
        errors.append(f"{event}/{hook}: wrong timeout/async {hits[0]}")
owned = [h for _, _, h in entries if h.get("command", "").startswith(f'"{adapter}" ')]
if len(owned) != 10:
    errors.append(f"Clade wiring count={len(owned)}, want 10")
for forbidden in ("pre-tool-guardian.sh", "session-context.sh", "pre_tool_guardian.py", "session_context.py"):
    if any(forbidden in h.get("command", "") for _, _, h in entries):
        errors.append(f"plugin-owned hook duplicated: {forbidden}")
print("; ".join(errors))
PY
}

section "empty install, exact declarative wiring and reinstall"
if install_home "$RUN_HOME" "$TMP_ROOT/runtime-install.log"; then
  pass "install.sh succeeds against a temporary HOME with an empty Codex directory"
else
  fail "install.sh succeeds against a temporary HOME with an empty Codex directory" "see $TMP_ROOT/runtime-install.log"
fi
ADAPTER="$RUN_HOME/.codex/clade-hooks/decision-to-codex.sh"
assert_file "$ADAPTER" "the adapter is installed under clade-hooks, not Codex-owned hooks/"
assert_no_file "$RUN_HOME/.codex/config.toml" "install.sh never fabricates Codex trust state in config.toml"
assert_probe check_wiring "$RUN_HOME" unused "all ten exact event/matcher/command/timeout/async wirings are present"
assert_contains "$(cat "$TMP_ROOT/runtime-install.log")" "10 Clade hook wirings" "the install summary reports the Codex hook count"
cp "$RUN_HOME/.codex/hooks.json" "$TMP_ROOT/runtime-first.json"
install_home "$RUN_HOME" "$TMP_ROOT/runtime-reinstall.log"
REINSTALL_RC=$?
cmp -s "$RUN_HOME/.codex/hooks.json" "$TMP_ROOT/runtime-first.json"
CMP_RC=$?
assert_eq "$REINSTALL_RC|$CMP_RC" "0|0" "a no-op reinstall leaves hooks.json byte-identical"
assert_contains "$(cat "$TMP_ROOT/runtime-reinstall.log")" "10 wired, 0 new" "the no-op reinstall reports zero new hooks needing trust review"
# The override goes in only after the last install into RUN_HOME. The reinstall
# above copies the source adapter back over the installed one, so an override
# copied before it was never the adapter any later case ran.
if [[ -n "${CODEX_ADAPTER_OVERRIDE:-}" ]]; then
  cp "$CODEX_ADAPTER_OVERRIDE" "$ADAPTER"
  chmod +x "$ADAPTER"
fi

section "amsg fixture preserves user groups, indices, fields and symlink mode"
USER_HOME="$TMP_ROOT/amsg-home"
amsg_fixture "$USER_HOME"
cp "$USER_HOME/.codex/hooks.json" "$TMP_ROOT/amsg-before.json"
printf '[hooks.state."/fake/hooks.json:session_start:0:0"]\ntrusted_hash = "fixture"\n' > "$USER_HOME/.codex/config.toml"
cp "$USER_HOME/.codex/config.toml" "$TMP_ROOT/amsg-config-before.toml"
install_home "$USER_HOME" "$TMP_ROOT/amsg-install.log"
USER_RC=$?
USER_ERRORS=$(python3 - "$TMP_ROOT/amsg-before.json" "$USER_HOME/.codex/hooks.json" <<'PY'
import json, sys
before = json.load(open(sys.argv[1], encoding="utf-8"))
after = json.load(open(sys.argv[2], encoding="utf-8"))
errors = []
for key in before:
    if key != "hooks" and after.get(key) != before[key]:
        errors.append(f"top-level {key} changed")
for event, groups in before["hooks"].items():
    if after["hooks"][event][:len(groups)] != groups:
        errors.append(f"{event} user groups changed or moved")
if len(after["hooks"]["SessionStart"]) != 2:
    errors.append("SessionStart did not append exactly one Clade group")
if after["hooks"]["SessionStart"][0] != before["hooks"]["SessionStart"][0]:
    errors.append("session_start:0:0 trust identity changed")
print("; ".join(errors))
PY
)
assert_eq "$USER_RC|$USER_ERRORS" "0|" "amsg entries stay deep-equal at their original indices and unknown fields survive"
cmp -s "$USER_HOME/.codex/config.toml" "$TMP_ROOT/amsg-config-before.toml"
assert_eq "$?" "0" "existing Codex trusted_hash state is byte-identical after installation"

LINK_HOME="$TMP_ROOT/symlink-home"
mkdir -p "$LINK_HOME/.codex" "$LINK_HOME/actual"
printf '{"description":"linked","hooks":{}}\n' > "$LINK_HOME/actual/hooks.json"
chmod 640 "$LINK_HOME/actual/hooks.json"
ln -s "$LINK_HOME/actual/hooks.json" "$LINK_HOME/.codex/hooks.json"
install_home "$LINK_HOME" "$TMP_ROOT/symlink-install.log"
LINK_RC=$?
LINK_MODE=$(stat -c %a "$LINK_HOME/actual/hooks.json" 2>/dev/null || stat -f %Lp "$LINK_HOME/actual/hooks.json")
if [[ -L "$LINK_HOME/.codex/hooks.json" ]]; then LINK_PRESERVED=yes; else LINK_PRESERVED=no; fi
assert_eq "$LINK_RC|$LINK_PRESERVED|$LINK_MODE" "0|yes|640" "a symlink remains a symlink and its target keeps mode 0640"

section "unsafe inputs and no-Python installs touch nothing"
for kind in invalid wrong-hooks wrong-event wrong-root; do
  home="$TMP_ROOT/unsafe-$kind"
  mkdir -p "$home/.codex"
  case "$kind" in
    invalid) printf '{not json\n' > "$home/.codex/hooks.json" ;;
    wrong-hooks) printf '{"hooks":[]}\n' > "$home/.codex/hooks.json" ;;
    wrong-event) printf '{"hooks":{"Stop":{}}}\n' > "$home/.codex/hooks.json" ;;
    wrong-root) printf '[]\n' > "$home/.codex/hooks.json" ;;
  esac
  cp "$home/.codex/hooks.json" "$home/before"
  install_home "$home" "$TMP_ROOT/unsafe-$kind.log"
  rc=$?
  cmp -s "$home/.codex/hooks.json" "$home/before"
  cmp_rc=$?
  warnings=$(grep -c 'WARNING: Codex hooks unchanged' "$TMP_ROOT/unsafe-$kind.log" || true)
  assert_eq "$rc|$cmp_rc|$warnings" "0|0|1" "$kind input leaves the file untouched with one warning"
done
NO_PY_HOME="$TMP_ROOT/no-python-home"
NO_PY_BIN="$TMP_ROOT/no-python-bin"
mkdir -p "$NO_PY_HOME/.codex" "$NO_PY_BIN"
printf '{"description":"no python","hooks":{}}\n' > "$NO_PY_HOME/.codex/hooks.json"
cp "$NO_PY_HOME/.codex/hooks.json" "$NO_PY_HOME/before"
for cmd in python python3; do
  printf '#!/usr/bin/env bash\nexit 1\n' > "$NO_PY_BIN/$cmd"
  chmod +x "$NO_PY_BIN/$cmd"
done
HOME="$NO_PY_HOME" CODEX_HOME="$NO_PY_HOME/.codex" PATH="$NO_PY_BIN:$FAKE_BIN:$PATH" \
  bash "$INSTALL_SH" </dev/null > "$TMP_ROOT/no-python.log" 2>&1
NO_PY_RC=$?
cmp -s "$NO_PY_HOME/.codex/hooks.json" "$NO_PY_HOME/before"
NO_PY_CMP=$?
assert_eq "$NO_PY_RC|$NO_PY_CMP|$(grep -c 'no working Python' "$TMP_ROOT/no-python.log" || true)" \
  "0|0|1" "no working Python leaves hooks.json untouched and warns once"

SPACE_HOME="$TMP_ROOT/home with space"
install_home "$SPACE_HOME" "$TMP_ROOT/space-install.log"
SPACE_RC=$?
SPACE_CMD=$(python3 - "$SPACE_HOME/.codex/hooks.json" <<'PY'
import json, sys
for group in json.load(open(sys.argv[1]))["hooks"]["PreToolUse"]:
    for handler in group["hooks"]:
        if "linter-config-guard.sh" in handler.get("command", ""):
            print(handler["command"])
PY
)
SPACE_OUT=$(printf '%s' '{"hook_event_name":"PreToolUse","cwd":"/repo","tool_name":"Bash","tool_input":{"command":"true"}}' | \
  HOME="$SPACE_HOME" bash -c "$SPACE_CMD" 2>/dev/null)
SPACE_HOOK_RC=$?
# ${SPACE_CMD:+wired}: with no command, `bash -c ""` exits 0 and the case would pass on a tree that wires nothing.
assert_eq "$SPACE_RC|${SPACE_CMD:+wired}|$SPACE_HOOK_RC|$SPACE_OUT" "0|wired|0|" "a HOME containing spaces installs and executes a quoted hook command"

# Codex-shaped payload builders, from schema.rs:279-297,324-343,499-524,567-602.
tool_payload() {
  jq -nc --arg event "$1" --arg sid "$2" --arg name "$3" --argjson input "$4" --arg cwd "$PROJ" \
    '{session_id:$sid,turn_id:"turn_fixture",transcript_path:null,cwd:$cwd,
      hook_event_name:$event,model:"fixture-model",permission_mode:"bypass",
      tool_name:$name,tool_input:$input,tool_use_id:"call_fixture"}
     + (if $event == "PostToolUse" then {tool_response:{success:true}} else {} end)'
}
prompt_payload() {
  jq -nc --arg sid "$1" --arg prompt "$2" --arg cwd "$PROJ" \
    '{session_id:$sid,turn_id:"turn_fixture",transcript_path:null,cwd:$cwd,
      hook_event_name:"UserPromptSubmit",model:"fixture-model",permission_mode:"bypass",prompt:$prompt}'
}
start_payload() {
  jq -nc --arg sid "$1" --arg source "$2" --arg cwd "$PROJ" \
    '{session_id:$sid,transcript_path:null,cwd:$cwd,hook_event_name:"SessionStart",
      model:"fixture-model",permission_mode:"bypass",source:$source}'
}
stop_payload() {
  jq -nc --arg sid "$1" --argjson active "$2" --arg cwd "$PROJ" \
    '{session_id:$sid,turn_id:"turn_fixture",transcript_path:null,cwd:$cwd,
      hook_event_name:"Stop",model:"fixture-model",permission_mode:"bypass",
      stop_hook_active:$active,last_assistant_message:null}'
}
end_payload() {
  jq -nc --arg sid "$1" --arg cwd "$PROJ" \
    '{session_id:$sid,transcript_path:null,cwd:$cwd,hook_event_name:"SessionEnd",reason:"other"}'
}

RUN_OUT=""
RUN_RC=0
run_hook() {
  local event="$1" hook="$2" payload="$3" cmd
  cmd=$(python3 - "$RUN_HOME/.codex/hooks.json" "$event" "$hook" <<'PY'
import json, sys
for group in json.load(open(sys.argv[1])).get("hooks", {}).get(sys.argv[2], []):
    for handler in group["hooks"]:
        if handler.get("command", "").endswith("/" + sys.argv[3] + '"'):
            print(handler["command"])
            raise SystemExit(0)
PY
)
  if [[ -z "$cmd" ]]; then
    RUN_OUT="MISSING COMMAND: $event/$hook"
    RUN_RC=97
    return
  fi
  RUN_OUT=$(printf '%s' "$payload" | HOME="$RUN_HOME" CODEX_HOME="$RUN_HOME/.codex" \
    CLADE_WORKER_TASK_ID="" CLADE_RUNTIME_DIR="$RUNTIME" CP_SHADOW_DIR="$SHADOW" SYNC_MARKER="$SYNC_MARKER" \
    PATH="$FAKE_BIN:$PATH" bash -c "$cmd" 2>"$TMP_ROOT/last-stderr")
  RUN_RC=$?
}

# A strict consumer mirror for the subset emitted by the adapter. Unknown fields,
# missing hookEventName and empty deny reasons are invalid, as in schema.rs and
# output_parser.rs at rust-v0.169.0.
output_verdict() {
  python3 - "$1" "$2" "$3" <<'PY'
import json, sys
event, rc, text = sys.argv[1], int(sys.argv[2]), sys.argv[3]
if rc != 0:
    print("INVALID: nonzero adapter exit")
    raise SystemExit(0)
if not text.strip():
    print("ALLOW")
    raise SystemExit(0)
try:
    value = json.loads(text)
except Exception as exc:
    print(f"INVALID: {exc}")
    raise SystemExit(0)
if not isinstance(value, dict):
    print("INVALID: non-object")
    raise SystemExit(0)
universal = {"continue", "stopReason", "suppressOutput", "systemMessage"}
allowed = universal | {"decision", "reason", "hookSpecificOutput"}
if set(value) - allowed:
    print(f"INVALID: unknown top-level {set(value) - allowed}")
    raise SystemExit(0)
h = value.get("hookSpecificOutput")
if h is not None:
    fields = {
        "PreToolUse": {"hookEventName", "permissionDecision", "permissionDecisionReason", "updatedInput", "additionalContext"},
        "PostToolUse": {"hookEventName", "additionalContext", "updatedMCPToolOutput"},
        "UserPromptSubmit": {"hookEventName", "additionalContext"},
        "SessionStart": {"hookEventName", "additionalContext"},
        "SubagentStart": {"hookEventName", "additionalContext"},
    }.get(event, set())
    if not isinstance(h, dict) or h.get("hookEventName") != event or set(h) - fields:
        print("INVALID: hookSpecificOutput schema")
        raise SystemExit(0)
    if h.get("permissionDecision") == "deny":
        if event != "PreToolUse" or not h.get("permissionDecisionReason", "").strip():
            print("INVALID: deny reason/event")
        else:
            print("BLOCK")
        raise SystemExit(0)
    if h.get("additionalContext"):
        print("CONTEXT")
        raise SystemExit(0)
if value.get("decision") == "block":
    if event not in {"Stop", "SubagentStop", "UserPromptSubmit", "PostToolUse"} or not value.get("reason", "").strip():
        print("INVALID: block reason/event")
    else:
        print("BLOCK")
elif value.get("systemMessage"):
    print("MESSAGE")
else:
    print("ALLOW")
PY
}
assert_verdict() {
  local got
  got=$(output_verdict "$2" "$RUN_RC" "$RUN_OUT")
  assert_eq "$got" "$3" "$1 (adapter rc=$RUN_RC)"
}
run_payload() {
  run_hook "$1" "$2" "$3"
  assert_verdict "$4" "$1" "$5"
}

RECORDER="$TMP_ROOT/recorder.sh"
cat > "$RECORDER" <<'EOF'
#!/usr/bin/env bash
input=$(cat)
printf '%s\n' "$input" | jq -c . >> "$RECORD"
printf '%s\n' "${CLAUDE_PROJECT_DIR:-}" >> "$ENV_RECORD"
EOF
chmod +x "$RECORDER"
PATCH='*** Begin Patch
*** Add File: relative/new.txt
+hello
+world
*** Update File: /absolute/old.txt
@@
-old
+new
*** Delete File: gone.txt
-bye
*** Update File: before.txt
*** Move to: after.txt
@@
-a
+b
*** End Patch'

run_adapter() {
  local adapter="$1" wrapped="$2" payload="$3"
  RUN_OUT=$(printf '%s' "$payload" | HOME="$RUN_HOME" CODEX_HOME="$RUN_HOME/.codex" \
    CLADE_WORKER_TASK_ID="" CLADE_RUNTIME_DIR="$RUNTIME" CP_SHADOW_DIR="$SHADOW" RECORD="$RECORD" ENV_RECORD="$ENV_RECORD" \
    "$adapter" "$wrapped" 2>"$TMP_ROOT/adapter-stderr")
  RUN_RC=$?
}

probe_adapter() {
  local adapter="$1" probe="$2" d payload errors rc
  d=$(mktemp -d "$TMP_ROOT/probe-adapter.XXXXXX") || return 1
  RECORD="$d/records" ENV_RECORD="$d/env"
  case "$probe" in
    fanout|post-fanout)
      local event=PreToolUse
      [[ "$probe" == fanout ]] || event=PostToolUse
      payload=$(jq -nc --arg event "$event" --arg patch "$PATCH" --arg cwd "$PROJ" \
        '{hook_event_name:$event,session_id:"s",cwd:$cwd,tool_name:"apply_patch",tool_input:{command:$patch},tool_response:{}}')
      run_adapter "$adapter" "$RECORDER" "$payload"
      local call_count=0
      [[ ! -f "$RECORD" ]] || call_count=$(wc -l < "$RECORD" | tr -d ' ')
      if [[ "$RUN_RC" != 0 || "$call_count" != 5 ]]; then
        errors="rc=$RUN_RC, calls=$call_count, want 0/5"
      else
      errors=$(python3 - "$RECORD" "$PROJ" "$RUN_RC" <<'PY'
import json, sys
from pathlib import Path
records = [json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines()] if Path(sys.argv[1]).exists() else []
project, rc = sys.argv[2], int(sys.argv[3])
errors = []
if rc != 0 or len(records) != 5:
    errors.append(f"rc={rc}, calls={len(records)}, want 0/5")
if records:
    expected = [
        ("Write", project + "/relative/new.txt"),
        ("Edit", "/absolute/old.txt"),
        ("Edit", project + "/gone.txt"),
        ("Edit", project + "/before.txt"),
        ("Edit", project + "/after.txt"),
    ]
    if [(r["tool_name"], r["tool_input"]["file_path"]) for r in records] != expected:
        errors.append("tool/path fan-out differs")
    if records[0]["tool_input"].get("content") != "hello\nworld":
        errors.append("Add content differs")
    if records[1]["tool_input"].get("old_string") != "old" or records[1]["tool_input"].get("new_string") != "new":
        errors.append("Update strings differ")
    if records[2]["tool_input"].get("new_string") != "" or records[2]["tool_input"].get("old_string") != "bye":
        errors.append("Delete mapping differs")
    for record in records[3:]:
        ti = record["tool_input"]
        if ti.get("old_file_path") != project + "/before.txt" or ti.get("new_file_path") != project + "/after.txt":
            errors.append("Move metadata differs")
print("; ".join(errors))
PY
)
      fi
      ;;
    no-headers)
      payload=$(jq -nc --arg cwd "$PROJ" '{hook_event_name:"PreToolUse",cwd:$cwd,tool_name:"apply_patch",tool_input:{command:"*** Begin Patch\n*** End Patch"}}')
      run_adapter "$adapter" "$RECORDER" "$payload"
      [[ ! -e "$RECORD" && "$RUN_RC" == 0 && -z "$RUN_OUT" ]] || errors="empty patch was not a no-op"
      ;;
    malformed)
      cat > "$d/hook.sh" <<'EOF'
#!/usr/bin/env bash
cat >/dev/null
touch "$RECORD"
EOF
      chmod +x "$d/hook.sh"
      run_adapter "$adapter" "$d/hook.sh" '{broken'
      [[ ! -e "$RECORD" && "$RUN_RC" == 0 && -z "$RUN_OUT" ]] || errors="malformed stdin did not fail open"
      ;;
    deny|move-deny)
      if [[ "$probe" == deny ]]; then
        payload=$(jq -nc --arg cwd "$PROJ" '{hook_event_name:"PreToolUse",cwd:$cwd,tool_name:"apply_patch",tool_input:{command:"*** Begin Patch\n*** Add File: a.txt\n+a\n*** Update File: .ruff.toml\n@@\n-a\n+b\n*** Delete File: c.txt\n-c\n*** End Patch"}}')
      else
        payload=$(jq -nc --arg cwd "$PROJ" '{hook_event_name:"PreToolUse",cwd:$cwd,tool_name:"apply_patch",tool_input:{command:"*** Begin Patch\n*** Update File: safe.txt\n*** Move to: .ruff.toml\n@@\n-a\n+b\n*** End Patch"}}')
      fi
      run_adapter "$adapter" "$RUN_HOME/.claude/hooks/linter-config-guard.sh" "$payload"
      [[ $(output_verdict PreToolUse "$RUN_RC" "$RUN_OUT") == BLOCK ]] || errors="Codex did not receive a valid deny: $RUN_OUT"
      [[ "$RUN_OUT" == *".ruff.toml"* ]] || errors="deny does not name the protected path"
      ;;
    bash)
      payload=$(tool_payload PreToolUse session_bash Bash '{"command":"printf \"a b\""}')
      run_adapter "$adapter" "$RECORDER" "$payload"
      errors=$(python3 - "$RECORD" "$ENV_RECORD" "$PROJ" <<'PY'
import json, sys
from pathlib import Path
try:
    record = json.loads(Path(sys.argv[1]).read_text().strip())
    environment = Path(sys.argv[2]).read_text().strip()
    if record["tool_name"] != "Bash" or record["tool_input"]["command"] != 'printf "a b"':
        print("Bash payload changed")
    elif environment != sys.argv[3]:
        print("CLAUDE_PROJECT_DIR does not equal cwd")
except Exception as exc:
    print(exc)
PY
)
      ;;
    context-fanout)
      cat > "$d/hook.sh" <<'EOF'
#!/usr/bin/env bash
input=$(cat)
jq -n --arg event 'PreToolUse' --arg path "$(jq -r '.tool_input.file_path' <<< "$input")" \
  '{systemMessage:("system:" + $path),hookSpecificOutput:{hookEventName:$event,additionalContext:("context:" + $path)}}'
EOF
      chmod +x "$d/hook.sh"
      payload=$(jq -nc --arg cwd "$PROJ" '{hook_event_name:"PreToolUse",cwd:$cwd,tool_name:"apply_patch",tool_input:{command:"*** Begin Patch\n*** Add File: one.txt\n+1\n*** Add File: two.txt\n+2\n*** End Patch"}}')
      run_adapter "$adapter" "$d/hook.sh" "$payload"
      [[ $(output_verdict PreToolUse "$RUN_RC" "$RUN_OUT") == CONTEXT ]] || errors="fan-out context was invalid"
      [[ $(jq -r '.hookSpecificOutput.additionalContext | split("\n\n") | length' <<< "$RUN_OUT") == 2 ]] || errors="additionalContext was not aggregated once per file"
      [[ $(jq -r '.systemMessage | split("\n\n") | length' <<< "$RUN_OUT") == 2 ]] || errors="systemMessage was not aggregated once per file"
      ;;
    nonzero)
      cat > "$d/hook.sh" <<'EOF'
#!/usr/bin/env bash
cat >/dev/null
printf '%s' '{"hookSpecificOutput":{"additionalContext":"must not leak"}}'
exit 1
EOF
      chmod +x "$d/hook.sh"
      run_adapter "$adapter" "$d/hook.sh" "$(prompt_payload session_nonzero continue)"
      [[ "$RUN_RC" == 0 && -z "$RUN_OUT" ]] || errors="nonzero wrapped hook leaked output"
      ;;
    unknown-deny)
      cat > "$d/hook.sh" <<'EOF'
#!/usr/bin/env bash
cat >/dev/null
printf '%s' '{"decision":"block","reason":"safe deny","unknownField":true}'
EOF
      chmod +x "$d/hook.sh"
      run_adapter "$adapter" "$d/hook.sh" "$(tool_payload PreToolUse session_unknown Bash '{"command":"true"}')"
      [[ $(output_verdict PreToolUse "$RUN_RC" "$RUN_OUT") == BLOCK ]] || errors="unknown input fields invalidated deny"
      [[ "$RUN_OUT" != *unknownField* ]] || errors="unknown output field reached Codex"
      ;;
    stop-block)
      # stop-check.sh asks for a continuation with exit 2 and its reason on stderr.
      cat > "$d/hook.sh" <<'EOF'
#!/usr/bin/env bash
cat >/dev/null
echo "uncommitted change in src/app.py" >&2
exit 2
EOF
      chmod +x "$d/hook.sh"
      run_adapter "$adapter" "$d/hook.sh" "$(stop_payload session_stop_probe false)"
      if [[ $(output_verdict Stop "$RUN_RC" "$RUN_OUT") != BLOCK ]]; then
        errors="Stop exit 2 did not become a Codex block: $RUN_OUT"
      elif [[ $(jq -r '.reason // empty' <<< "$RUN_OUT" 2>/dev/null) != *"uncommitted change"* ]]; then
        errors="the Stop block lost the hook's reason: $RUN_OUT"
      fi
      ;;
    empty-reason)
      # Codex drops a deny whose reason is empty (output_parser.rs:441-470).
      cat > "$d/hook.sh" <<'EOF'
#!/usr/bin/env bash
cat >/dev/null
exit 2
EOF
      chmod +x "$d/hook.sh"
      run_adapter "$adapter" "$d/hook.sh" "$(tool_payload PreToolUse session_empty_reason Bash '{"command":"true"}')"
      [[ $(output_verdict PreToolUse "$RUN_RC" "$RUN_OUT") == BLOCK ]] || errors="an exit-2 deny with no stderr was lost: $RUN_OUT"
      ;;
    prompt-context)
      cat > "$d/hook.sh" <<'EOF'
#!/usr/bin/env bash
cat >/dev/null
printf '%s' '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"prompt context"}}'
EOF
      chmod +x "$d/hook.sh"
      run_adapter "$adapter" "$d/hook.sh" "$(prompt_payload session_prompt_probe hello)"
      [[ $(output_verdict UserPromptSubmit "$RUN_RC" "$RUN_OUT") == CONTEXT ]] || errors="UserPromptSubmit context did not reach Codex: $RUN_OUT"
      ;;
    ask)
      # Codex 0.169.0 has no ask (output_parser.rs:121-175); the adapter denies.
      cat > "$d/hook.sh" <<'EOF'
#!/usr/bin/env bash
cat >/dev/null
printf '%s' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"needs a human"}}'
EOF
      chmod +x "$d/hook.sh"
      run_adapter "$adapter" "$d/hook.sh" "$(tool_payload PreToolUse session_ask Bash '{"command":"true"}')"
      [[ $(output_verdict PreToolUse "$RUN_RC" "$RUN_OUT") == BLOCK ]] || errors="an ask Codex cannot honour did not become a deny: $RUN_OUT"
      ;;
    rewrite|rewrite-fanout)
      cat > "$d/hook.sh" <<'EOF'
#!/usr/bin/env bash
cat >/dev/null
printf '%s' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","updatedInput":{"command":"echo safe"}}}'
EOF
      chmod +x "$d/hook.sh"
      if [[ "$probe" == rewrite ]]; then
        run_adapter "$adapter" "$d/hook.sh" "$(tool_payload PreToolUse session_rewrite Bash '{"command":"echo raw"}')"
        if [[ $(output_verdict PreToolUse "$RUN_RC" "$RUN_OUT") != ALLOW ]] || \
           ! jq -e '.hookSpecificOutput | .permissionDecision == "allow" and .updatedInput.command == "echo safe"' <<< "$RUN_OUT" >/dev/null 2>&1; then
          errors="a single-call rewrite did not reach Codex as allow plus updatedInput: $RUN_OUT"
        fi
      else
        payload=$(jq -nc --arg cwd "$PROJ" '{hook_event_name:"PreToolUse",cwd:$cwd,tool_name:"apply_patch",tool_input:{command:"*** Begin Patch\n*** Add File: one.txt\n+1\n*** End Patch"}}')
        run_adapter "$adapter" "$d/hook.sh" "$payload"
        [[ $(output_verdict PreToolUse "$RUN_RC" "$RUN_OUT") == BLOCK ]] || errors="a per-file rewrite of apply_patch was not refused: $RUN_OUT"
      fi
      ;;
    *) errors="unknown adapter probe" ;;
  esac
  rm -rf "$d"
  [[ -z "${errors:-}" ]] || { printf '%s\n' "$errors"; return 1; }
  return 0
}

section "adapter apply_patch fan-out, Bash, fail-open and exact deny schema"
for probe in fanout post-fanout no-headers malformed deny move-deny bash context-fanout nonzero unknown-deny \
             stop-block empty-reason prompt-context ask rewrite rewrite-fanout; do
  assert_probe probe_adapter "$ADAPTER" "$probe" "adapter probe: $probe"
done

section "ported correction, secret, baseline, Stop, cleanup and memory effects"
git -C "$PROJ" init -q
git -C "$PROJ" config user.email codex-hooks@example.invalid
git -C "$PROJ" config user.name codex-hooks
printf '# fixture\n' > "$PROJ/CLAUDE.md"
printf 'one\n' > "$PROJ/src/app.py"
git -C "$PROJ" add -A
git -C "$PROJ" commit -qm 'fixture initial'
SID="2b80cde4-0f6c-4c2f-9ee4-111111111111"
PATCH_TWO='*** Begin Patch
*** Update File: src/app.py
@@
-one
+two
*** Add File: src/new.py
+print(2)
*** End Patch'
run_payload PostToolUse edit-shadow-detector.sh \
  "$(jq -nc --arg sid "$SID" --arg patch "$PATCH_TWO" --arg cwd "$PROJ" '{session_id:$sid,turn_id:"t",transcript_path:null,cwd:$cwd,hook_event_name:"PostToolUse",model:"m",permission_mode:"bypass",tool_name:"apply_patch",tool_input:{command:$patch},tool_use_id:"call",tool_response:{success:true}}')" \
  "PostToolUse apply_patch runs the edit shadow once per file" ALLOW
SHADOW_FILE="$SHADOW/session-$SID.jsonl"
assert_file "$SHADOW_FILE" "the correction-pairing shadow is written"
assert_eq "$(jq -s 'map(.file) | join("|")' "$SHADOW_FILE" 2>/dev/null)" "\"$PROJ/src/app.py|$PROJ/src/new.py\"" "both absolute edited paths reach the shadow"
run_payload PreToolUse revert-detector.sh \
  "$(tool_payload PreToolUse "$SID" Bash '{"command":"git checkout -- src/app.py"}')" \
  "async PreToolUse revert detector remains data-only" ALLOW
LAST=$(tail -n 1 "$HISTORY" 2>/dev/null)
assert_eq "$(jq -r '.type // empty' <<< "$LAST")" "implicit-revert" "revert history is appended"
assert_contains "$(jq -c '.reverted_files' <<< "$LAST")" "src/app.py" "the revert intersects the apply_patch shadow"

CORRECTION_SID="2b80cde4-0f6c-4c2f-9ee4-222222222222"
run_payload UserPromptSubmit correction-detector.sh \
  "$(prompt_payload "$CORRECTION_SID" "No, that is wrong. Use the safer approach instead.")" \
  "correction context is valid Codex UserPromptSubmit output" CONTEXT
LAST=$(tail -n 1 "$HISTORY" 2>/dev/null)
assert_eq "$(jq -r '.session_id // empty' <<< "$LAST")" "$CORRECTION_SID" "explicit correction history keeps the Codex session id"
SECRET='sk-'"test-1234567890abcdefghij"
run_payload UserPromptSubmit secret-scanner.sh \
  "$(prompt_payload session_secret "credential is $SECRET")" \
  "secret scanner emits Codex additionalContext" CONTEXT
assert_contains "$(jq -r '.hookSpecificOutput.additionalContext' <<< "$RUN_OUT")" "Handle it as data" "secret handling guidance survives translation"

STOP_SID="2b80cde4-0f6c-4c2f-9ee4-333333333333"
run_payload SessionStart session-baseline.sh "$(start_payload "$STOP_SID" startup)" \
  "SessionStart baseline runs through its installed command" ALLOW
BASELINE="$PROJ/.claude/sessions/$STOP_SID.baseline"
assert_file "$BASELINE" "the stop-check baseline is written"
printf 'dirty\n' > "$PROJ/src/new-file.txt"
run_payload Stop stop-check.sh "$(stop_payload "$STOP_SID" false)" \
  "Stop exit-2 becomes a non-empty Codex continuation block" BLOCK
assert_contains "$(jq -r '.reason' <<< "$RUN_OUT")" "uncommitted change" "Stop continuation carries the real reason"
run_payload Stop stop-check.sh "$(stop_payload "$STOP_SID" true)" \
  "stop_hook_active=true escapes a repeated Stop block" ALLOW
assert_file "$SHADOW_FILE" "the shadow still exists before SessionEnd, so its removal is observable"
run_payload SessionEnd session-end-cleanup.sh "$(end_payload "$SID")" \
  "SessionEnd cleanup has no protocol output" ALLOW
assert_no_file "$SHADOW_FILE" "SessionEnd removes the ending session's shadow"

: > "$RUN_HOME/.claude/.sync-config"
cat > "$RUN_HOME/.claude/scripts/sync-push.sh" <<'EOF'
#!/usr/bin/env bash
printf 'push\n' >> "$SYNC_MARKER"
EOF
chmod +x "$RUN_HOME/.claude/scripts/sync-push.sh"
MEMORY_PATCH="*** Begin Patch
*** Add File: $RUN_HOME/.claude/hooks/learned.md
+memory
*** End Patch"
run_payload PostToolUse memory-sync.sh \
  "$(jq -nc --arg patch "$MEMORY_PATCH" --arg cwd "$PROJ" '{session_id:"session_memory",cwd:$cwd,hook_event_name:"PostToolUse",tool_name:"apply_patch",tool_input:{command:$patch},tool_response:{}}')" \
  "memory-sync apply_patch is data-only" ALLOW
for _ in $(seq 1 50); do [[ -f "$SYNC_MARKER" ]] && break; sleep 0.1; done
assert_eq "$(grep -c '^push$' "$SYNC_MARKER" 2>/dev/null || true)" "1" "the Edit/Write memory-sync command invokes sync-push"
run_payload PostToolUse memory-sync.sh \
  "$(tool_payload PostToolUse session_memory Bash '{"command":"touch ~/.claude/hooks/another.md"}')" \
  "memory-sync Bash is data-only" ALLOW
for _ in $(seq 1 50); do [[ "$(grep -c '^push$' "$SYNC_MARKER" 2>/dev/null || true)" == 2 ]] && break; sleep 0.1; done
assert_eq "$(grep -c '^push$' "$SYNC_MARKER" 2>/dev/null || true)" "2" "the separate Bash wiring invokes sync-push again"

# Direct merger probes are also the mutation harness's oracles.
probe_merger() {
  local merger="$1" probe="$2" d target output rc errors=""
  d=$(mktemp -d "$TMP_ROOT/probe-merger.XXXXXX") || return 1
  target="$d/.codex/hooks.json"
  mkdir -p "$d/.codex"
  case "$probe" in
    create)
      output=$(spec_text | python3 "$merger" --target "$target" --adapter "$d/.codex/clade-hooks/decision-to-codex.sh" --claude-hooks "$d/.claude/hooks" 2>&1)
      rc=$?
      [[ "$rc" == 0 && -f "$target" ]] || errors="missing target was not created: $output"
      [[ $(python3 -c 'import json,sys; print(sum(len(g["hooks"]) for gs in json.load(open(sys.argv[1]))["hooks"].values() for g in gs))' "$target" 2>/dev/null) == 10 ]] || errors="created file does not hold ten wirings"
      ;;
    preserve-append)
      amsg_fixture "$d"
      cp "$target" "$d/before"
      output=$(spec_text | python3 "$merger" --target "$target" --adapter "$d/.codex/clade-hooks/decision-to-codex.sh" --claude-hooks "$d/.claude/hooks" 2>&1)
      rc=$?
      errors=$(python3 - "$d/before" "$target" <<'PY'
import json, sys
before = json.load(open(sys.argv[1])); after = json.load(open(sys.argv[2]))
errors = []
for key in before:
    if key != "hooks" and after.get(key) != before[key]: errors.append(f"{key} changed")
for event, groups in before["hooks"].items():
    if after["hooks"][event][:len(groups)] != groups: errors.append(f"{event} groups moved")
print("; ".join(errors))
PY
)
      [[ "$rc" == 0 && -z "$errors" ]] || errors="append preservation failed: $errors $output"
      ;;
    idempotent|no-op)
      if [[ "$probe" == idempotent ]]; then
        output=$(spec_text | python3 "$merger" --target "$target" --adapter "$d/.codex/clade-hooks/decision-to-codex.sh" --claude-hooks "$d/.claude/hooks" 2>&1)
      else
        output=$(spec_text | python3 "$merger" --target "$target" --adapter "$d/.codex/clade-hooks/decision-to-codex.sh" --claude-hooks "$d/.claude/hooks" 2>&1)
        python3 - "$target" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
path.write_text(json.dumps(json.loads(path.read_text()), separators=(",", ":")) + "\n")
PY
      fi
      cp "$target" "$d/before"
      output=$(spec_text | python3 "$merger" --target "$target" --adapter "$d/.codex/clade-hooks/decision-to-codex.sh" --claude-hooks "$d/.claude/hooks" 2>&1)
      rc=$?
      cmp -s "$target" "$d/before" || errors="a no-op rewrote or duplicated the file"
      [[ "$rc" == 0 && -z "$errors" ]] || errors="$errors $output"
      ;;
    wrong-type)
      printf '{"hooks":[]}\n' > "$target"
      cp "$target" "$d/before"
      output=$(spec_text | python3 "$merger" --target "$target" --adapter "$d/adapter" --claude-hooks "$d/hooks" 2>&1)
      rc=$?
      cmp -s "$target" "$d/before" || errors="wrong type was modified"
      [[ "$rc" == 0 && $(grep -c 'WARNING: Codex hooks unchanged' <<< "$output") == 1 ]] || errors="wrong type did not warn safely: rc=$rc $output"
      [[ -z "$errors" ]] || errors="$errors"
      ;;
    symlink-mode)
      mkdir -p "$d/actual"
      printf '{"hooks":{}}\n' > "$d/actual/hooks.json"
      chmod 640 "$d/actual/hooks.json"
      ln -s "$d/actual/hooks.json" "$target"
      output=$(spec_text | python3 "$merger" --target "$target" --adapter "$d/adapter" --claude-hooks "$d/hooks" 2>&1)
      rc=$?
      [[ -L "$target" ]] || errors="symlink was replaced"
      mode=$(stat -c %a "$d/actual/hooks.json" 2>/dev/null || stat -f %Lp "$d/actual/hooks.json")
      [[ "$rc" == 0 && "$mode" == 640 ]] || errors="target mode changed: $mode $output"
      ;;
    space-command)
      home="$d/home with space"
      mkdir -p "$home/.codex/clade-hooks" "$home/.claude/hooks"
      cp "$ADAPTER" "$home/.codex/clade-hooks/decision-to-codex.sh"
      cp "$RECORDER" "$home/.claude/hooks/linter-config-guard.sh"
      chmod +x "$home/.codex/clade-hooks/decision-to-codex.sh" "$home/.claude/hooks/linter-config-guard.sh"
      output=$(spec_text | python3 "$merger" --target "$target" --adapter "$home/.codex/clade-hooks/decision-to-codex.sh" --claude-hooks "$home/.claude/hooks" 2>&1)
      rc=$?
      command=$(python3 - "$target" <<'PY'
import json, sys
print(json.load(open(sys.argv[1]))["hooks"]["PreToolUse"][0]["hooks"][0]["command"])
PY
)
      RECORD="$d/record" ENV_RECORD="$d/env"
      printf '%s' '{"hook_event_name":"PreToolUse","cwd":"/repo","tool_name":"Bash","tool_input":{"command":"true"}}' | RECORD="$RECORD" ENV_RECORD="$ENV_RECORD" bash -c "$command" >/dev/null 2>&1
      run_rc=$?
      [[ "$rc" == 0 && "$run_rc" == 0 && -f "$RECORD" ]] || errors="quoted installed command did not execute"
      ;;
    *) errors="unknown merger probe" ;;
  esac
  rm -rf "$d"
  [[ -z "$errors" ]] || { printf '%s\n' "$errors"; return 1; }
  return 0
}

section "direct merger safety and real command execution"
for probe in create preserve-append idempotent no-op wrong-type symlink-mode space-command; do
  assert_probe probe_merger "$MERGER" "$probe" "merger probe: $probe"
done

mutate() {
  local source="$1" dest="$2" old="$3" new="$4" expected="${5:-1}"
  python3 - "$source" "$dest" "$old" "$new" "$expected" <<'PY'
from pathlib import Path
import sys
source, dest, old, new, expected = sys.argv[1:]
text = Path(source).read_text(encoding="utf-8")
assert text.count(old) == int(expected), (old, text.count(old))
Path(dest).write_text(text.replace(old, new), encoding="utf-8")
PY
}

section "guard ablation controls (each mutant must go red)"
assert_probe probe_adapter "$ADAPTER" fanout "no-op adapter control remains green"
assert_probe probe_merger "$MERGER" preserve-append "no-op merger control remains green"

ADAPTER_MUTATIONS=(
  $'absolute-paths\tfile_path:($path | absolute($root.cwd))\tfile_path:$path\tfanout'
  $'move-destination\telse [$file.path, $file.move_to] end\telse [$file.path] end\tmove-deny'
  $'delete-files\tAdd|Update|Delete\tAdd|Update\tfanout\t2'
  $'add-content\tcontent:($file.added | join("\\n"))\tcontent:""\tfanout'
  $'deny-short-circuit\tif is_block_output "$TRANSLATED"; then\tif false; then\tdeny'
  $'deny-event-name\thookEventName:"PreToolUse",permissionDecision\thookEventName:"Wrong",permissionDecision\tdeny\t2'
  $'malformed-input\t[[ -n "$NORMALIZED" ]] || exit 0\t:\tmalformed'
  $'nonzero-fail-open\t[[ "$RUN_RC" == 0 && -n "${RUN_OUTPUT//[[:space:]]/}" ]] || return 0\t[[ -n "${RUN_OUTPUT//[[:space:]]/}" ]] || return 0\tnonzero'
  $'project-env\tCLAUDE_PROJECT_DIR="$PROJECT_DIR"\tCLAUDE_PROJECT_DIR=""\tbash'
  $'post-fanout\t( "$EVENT" == PreToolUse || "$EVENT" == PostToolUse )\t"$EVENT" == PreToolUse\tpost-fanout'
  $'exit-two-block\tif [[ "$RUN_RC" == 2 ]]; then\tif false; then\tstop-block'
  $'stop-block\tUserPromptSubmit|PostToolUse|Stop|SubagentStop)\tUserPromptSubmit|PostToolUse|SubagentStop)\tstop-block'
  $'empty-reason\t[[ -n "${reason//[[:space:]]/}" ]] || reason="Blocked by ${EVENT:-hook} hook"\t:\tempty-reason'
  $'prompt-context\tSessionStart|SubagentStart|UserPromptSubmit|PreToolUse|PostToolUse)\tSessionStart|SubagentStart|PreToolUse|PostToolUse)\tprompt-context'
  $'ask-deny\t($h.permissionDecision? == "deny") or ($h.permissionDecision? == "ask")\t($h.permissionDecision? == "deny")\task'
  $'rewrite-allow\tif [[ "$EVENT" == PreToolUse && "$fanout" == 0 ]]; then\tif false; then\trewrite'
  $'rewrite-fanout-block\tTRANSLATED=$(emit_block "The hook requested a per-file input rewrite\tTRANSLATED="" #\trewrite-fanout'
  $'context-aggregation\t|| CONTEXTS+=\t|| CONTEXTS=""; CONTEXTS+=\tcontext-fanout'
)
for mutation in "${ADAPTER_MUTATIONS[@]}"; do
  IFS=$'\t' read -r name old new probe count <<< "$mutation"
  mutant="$TMP_ROOT/adapter-$name.sh"
  if ! mutate "$ADAPTER" "$mutant" "$old" "$new" "${count:-1}"; then
    fail "adapter mutation $name removes its intended guard" "mutation text not found"
    continue
  fi
  chmod +x "$mutant"
  if probe_adapter "$mutant" "$probe" >/dev/null 2>&1; then
    fail "adapter mutation $name goes red" "mutant survived $probe; $(grep -n 'TOOL_NAME.*apply_patch' "$mutant" 2>/dev/null)"
  else
    pass "adapter mutation $name goes red"
  fi
done

MERGER_MUTATIONS=(
  $'append-order\t.append(spec["group"])\t.insert(0, spec["group"])\tpreserve-append'
  $'idempotence\tif not present(document, spec):\t\tif True:\tidempotent'
  $'create-write\tif additions:\t\tif False:\tcreate'
  $'no-op-write\tif additions:\t\tif True:\tno-op'
  $'symlink\ttarget.resolve() if target.is_symlink() else target\ttarget\tsymlink-mode'
  $'file-mode\tos.chmod(temporary, mode)\t:\tsymlink-mode'
  $'hooks-type\tif not isinstance(hooks, dict):\t\tif False:\twrong-type'
  $'unknown-fields\tadditions = []\tdocument = {"hooks": document["hooks"]}\n    additions = []\tpreserve-append'
  $'path-quoting\tcustom function replacement\tcustom function replacement\tspace-command'
)
for mutation in "${MERGER_MUTATIONS[@]}"; do
  IFS=$'\t' read -r name old new probe <<< "$mutation"
  mutant="$TMP_ROOT/merger-$name.py"
  if [[ "$name" == path-quoting ]]; then
    python3 - "$MERGER" "$mutant" <<'PY'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_text()
start = text.index("def shell_quote")
end = text.index("\n\n\ndef load_specs", start)
Path(sys.argv[2]).write_text(text[:start] + "def shell_quote(value: str) -> str:\n    return value" + text[end:])
PY
  elif ! mutate "$MERGER" "$mutant" "$old" "$new"; then
    fail "merger mutation $name removes its intended guard" "mutation text not found"
    continue
  fi
  if probe_merger "$mutant" "$probe" >/dev/null 2>&1; then
    fail "merger mutation $name goes red" "mutant survived $probe"
  else
    pass "merger mutation $name goes red"
  fi
done

section "uninstall.sh takes out Clade's Codex wiring and nothing else"
uninstall_home() {  # uninstall_home HOME LOG [UNINSTALL_SH] [PATH_PREFIX]
  local home="$1" log="$2" script="${3:-$UNINSTALL_SH}" path_prefix="${4:-$FAKE_BIN}"
  HOME="$home" CODEX_HOME="$home/.codex" PATH="$path_prefix:$PATH" PYTHONDONTWRITEBYTECODE=1 \
    bash "$script" </dev/null > "$log" 2>&1
}
# One real install seeds every case: the amsg fixture plus a user event list
# that is empty on purpose, then the edits a user makes AFTER installing — a
# group behind Clade's, a handler added INTO Clade's SessionEnd group, and a
# profile holding its own copy of a Clade group beside its own.
UN_T="$TMP_ROOT/uninstall-template"
amsg_fixture "$UN_T"
python3 - "$UN_T/.codex/hooks.json" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
document = json.loads(path.read_text(encoding="utf-8"))
document["hooks"]["PermissionRequest"] = []
path.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
PY
cp "$UN_T/.codex/hooks.json" "$TMP_ROOT/un-before.json"
printf '[hooks.state."/fake/hooks.json:session_start:0:0"]\ntrusted_hash = "fixture"\n' > "$UN_T/.codex/config.toml"
cp "$UN_T/.codex/config.toml" "$TMP_ROOT/un-config-before.toml"
install_home "$UN_T" "$TMP_ROOT/un-install.log"
UN_INSTALL_RC=$?
python3 - "$UN_T" "$TMP_ROOT/un-before.json" "$TMP_ROOT/un-expected.json" "$TMP_ROOT/un-profile-expected.json" <<'PY'
import copy, json, sys
from pathlib import Path
home, before = Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
path = home / ".codex" / "hooks.json"
document = json.loads(path.read_text(encoding="utf-8"))
def clade(group):
    return any("clade-hooks/decision-to-codex.sh" in h.get("command", "") for h in group["hooks"])
after_install = {"hooks": [{"type": "command", "command": "/fake/user/after-install"}]}
shared = {"type": "command", "command": "/fake/user/shared-group", "timeout": 2}
clade_stop = next(g for g in document["hooks"]["Stop"] if clade(g))
clade_end = next(g for g in document["hooks"]["SessionEnd"] if clade(g))
document["hooks"]["Stop"].append(after_install)
clade_end["hooks"].append(shared)
path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
expected = copy.deepcopy(before)
expected["hooks"]["Stop"].append(after_install)
expected["hooks"]["SessionEnd"].append({"matcher": clade_end.get("matcher"), "hooks": [shared]})
Path(sys.argv[3]).write_text(json.dumps(expected) + "\n", encoding="utf-8")
own = home / ".codex-profiles" / "own"
own.mkdir(parents=True)
profile_user = {"hooks": [{"type": "command", "command": "/fake/profile/own"}]}
(own / "hooks.json").write_text(json.dumps(
    {"description": "own profile", "hooks": {"Stop": [profile_user, clade_stop]}}, indent=2) + "\n", encoding="utf-8")
Path(sys.argv[4]).write_text(json.dumps({"description": "own profile", "hooks": {"Stop": [profile_user]}}) + "\n", encoding="utf-8")
PY
mkdir -p "$UN_T/.codex-profiles/linked" "$TMP_ROOT/un-seed/.codex-profiles"
ln -s "$UN_T/.codex/hooks.json" "$UN_T/.codex-profiles/linked/hooks.json"
cp -R "$UN_T/.codex" "$TMP_ROOT/un-seed/"
cp -R "$UN_T/.codex-profiles/own" "$TMP_ROOT/un-seed/.codex-profiles/"

seed_codex_home() {  # seed_codex_home DEST — the template's installed state, re-rooted at DEST
  python3 - "$TMP_ROOT/un-seed" "$1" "$UN_T" <<'PY'
import os, shutil, sys
from pathlib import Path
seed, dest, old = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
for rel in (".codex/hooks.json", ".codex/config.toml", ".codex-profiles/own/hooks.json"):
    target = dest / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text((seed / rel).read_text(encoding="utf-8").replace(old, str(dest)), encoding="utf-8")
link = dest / ".codex-profiles" / "linked" / "hooks.json"
link.parent.mkdir(parents=True, exist_ok=True)
os.symlink(dest / ".codex" / "hooks.json", link)
adapter = dest / ".codex" / "clade-hooks" / "decision-to-codex.sh"
adapter.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(seed / ".codex" / "clade-hooks" / "decision-to-codex.sh", adapter)
PY
}

codex_uninstalled() {  # codex_uninstalled HOME — empty when only Clade's wiring is gone
  python3 - "$1" "$TMP_ROOT/un-expected.json" "$TMP_ROOT/un-profile-expected.json" "$TMP_ROOT/un-config-before.toml" <<'PY'
import json, sys
from pathlib import Path
home = Path(sys.argv[1])
errors = []
def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{path}: {exc}")
for rel, want in ((".codex/hooks.json", sys.argv[2]), (".codex-profiles/own/hooks.json", sys.argv[3])):
    got = load(home / rel)
    if got is not None and got != json.loads(Path(want).read_text(encoding="utf-8")):
        errors.append(f"{rel} is not exactly the user's own groups: {json.dumps(got)[:400]}")
if not (home / ".codex-profiles" / "linked" / "hooks.json").is_symlink():
    errors.append("the linked profile hooks.json is no longer a link")
if (home / ".codex" / "clade-hooks").exists():
    errors.append("~/.codex/clade-hooks/ was left behind")
if (home / ".codex" / "config.toml").read_text(encoding="utf-8") != Path(sys.argv[4]).read_text(encoding="utf-8"):
    errors.append("config.toml trust state changed")
print("; ".join(errors))
PY
}

# Each probe is also an oracle for the mutation controls below.
probe_codex_uninstall() {
  local script="$1" probe="$2" d rc errors=""
  d=$(mktemp -d "$TMP_ROOT/probe-uninstall.XXXXXX") || return 1
  case "$probe" in
    roundtrip)
      seed_codex_home "$d"
      uninstall_home "$d" "$d/log" "$script"
      rc=$?
      errors=$(codex_uninstalled "$d")
      [[ "$rc" == 0 ]] || errors="uninstall exited $rc $errors"
      ;;
    untouched)
      amsg_fixture "$d"
      cp "$d/.codex/hooks.json" "$d/before"
      uninstall_home "$d" "$d/log" "$script"
      rc=$?
      cmp -s "$d/.codex/hooks.json" "$d/before" || errors="a hooks.json holding nothing of Clade's was rewritten"
      [[ "$rc" == 0 ]] || errors="uninstall exited $rc $errors"
      ;;
    invalid|no-python)
      seed_codex_home "$d"
      [[ "$probe" == no-python ]] || printf 'garbage\n' >> "$d/.codex/hooks.json"
      cp "$d/.codex/hooks.json" "$d/before"
      if [[ "$probe" == invalid ]]; then
        warning='WARNING: Codex hooks unchanged'
        uninstall_home "$d" "$d/log" "$script"
      else
        warning='(no working Python)'
        uninstall_home "$d" "$d/log" "$script" "$NO_PY_BIN:$FAKE_BIN"
      fi
      rc=$?
      cmp -s "$d/.codex/hooks.json" "$d/before" || errors="a hooks.json the uninstaller could not clean was changed"
      [[ -f "$d/.codex/clade-hooks/decision-to-codex.sh" ]] || errors="$errors; the adapter was deleted while hooks.json still runs it"
      grep -qF "$warning" "$d/log" || errors="$errors; no '$warning' line"
      [[ "$rc" == 0 ]] || errors="uninstall exited $rc $errors"
      ;;
    external-link)
      seed_codex_home "$d"
      mkdir -p "$d/.codex-profiles/ext" "$d/elsewhere"
      cp "$d/.codex-profiles/own/hooks.json" "$d/elsewhere/hooks.json"
      cp "$d/elsewhere/hooks.json" "$d/before"
      ln -s "$d/elsewhere/hooks.json" "$d/.codex-profiles/ext/hooks.json"
      uninstall_home "$d" "$d/log" "$script"
      rc=$?
      cmp -s "$d/elsewhere/hooks.json" "$d/before" || errors="a profile link's target outside ~/.codex was edited"
      [[ -f "$d/.codex/clade-hooks/decision-to-codex.sh" ]] || errors="$errors; the adapter was deleted while a linked file still runs it"
      [[ $(grep -c 'clade-hooks/decision-to-codex.sh' "$d/.codex/hooks.json") == 0 ]] || errors="$errors; ~/.codex/hooks.json was not cleaned"
      [[ "$rc" == 0 ]] || errors="uninstall exited $rc $errors"
      ;;
    symlink-main)
      seed_codex_home "$d"
      mkdir -p "$d/actual"
      mv "$d/.codex/hooks.json" "$d/actual/hooks.json"
      chmod 640 "$d/actual/hooks.json"
      ln -s "$d/actual/hooks.json" "$d/.codex/hooks.json"
      uninstall_home "$d" "$d/log" "$script"
      rc=$?
      mode=$(stat -c %a "$d/actual/hooks.json" 2>/dev/null || stat -f %Lp "$d/actual/hooks.json")
      [[ -L "$d/.codex/hooks.json" && "$mode" == 640 ]] || errors="the link or its target's mode changed: mode=$mode"
      [[ $(grep -c 'clade-hooks/decision-to-codex.sh' "$d/actual/hooks.json") == 0 ]] || errors="$errors; the link target was not cleaned"
      [[ "$rc" == 0 ]] || errors="uninstall exited $rc $errors"
      ;;
    *) errors="unknown uninstall probe" ;;
  esac
  rm -rf "$d"
  [[ -z "$errors" ]] || { printf '%s\n' "$errors"; return 1; }
  return 0
}

uninstall_home "$UN_T" "$TMP_ROOT/un-uninstall.log"
UN_RC=$?
assert_eq "$UN_INSTALL_RC|$UN_RC" "0|0" "install.sh then uninstall.sh both succeed against the temporary HOME"
assert_probe codex_uninstalled "$UN_T" unused \
  "after a real install: every user group, field and empty list is back exactly, the own profile too, the adapter is gone and trust state is untouched"
assert_contains "$(cat "$TMP_ROOT/un-uninstall.log")" "Codex hooks: 10 removed from $UN_T/.codex/hooks.json" \
  "uninstall.sh reports the ten wirings it took out"
assert_contains "$(cat "$TMP_ROOT/un-uninstall.log")" "Codex hooks: 1 removed from $UN_T/.codex-profiles/own/hooks.json" \
  "uninstall.sh cleans a profile that holds its own hooks.json"
cp "$UN_T/.codex/hooks.json" "$TMP_ROOT/un-after.json"
uninstall_home "$UN_T" "$TMP_ROOT/un-uninstall-2.log"
UN_RC=$?
cmp -s "$UN_T/.codex/hooks.json" "$TMP_ROOT/un-after.json"
assert_eq "$UN_RC|$?" "0|0" "a second uninstall leaves hooks.json byte-identical"
for probe in roundtrip untouched invalid no-python external-link symlink-main; do
  assert_probe probe_codex_uninstall "$UNINSTALL_SH" "$probe" "uninstall probe: $probe"
done

# Guard ablations: a source tree whose uninstall.sh or merger is a mutant, and
# whose other files link to the real ones. Rows are one line each — `read` stops
# at a newline, and a row cut short there leaves the probe name empty, which
# "goes red" without running anything — and a mutant must still parse, so red
# means the guard is missed, not that the file broke.
uninstall_tree() {  # uninstall_tree DIR UNINSTALL_SH MERGER
  local dir="$1" item
  mkdir -p "$dir/configs/scripts"
  cp "$2" "$dir/uninstall.sh"
  for item in "$SRC_ROOT/configs/"*; do
    [[ "$(basename "$item")" == scripts ]] || ln -s "$item" "$dir/configs/"
  done
  for item in "$SRC_ROOT/configs/scripts/"*; do
    [[ "$(basename "$item")" == codex-hooks-merge.py ]] || ln -s "$item" "$dir/configs/scripts/"
  done
  cp "$3" "$dir/configs/scripts/codex-hooks-merge.py"
}
uninstall_tree "$TMP_ROOT/un-control" "$UNINSTALL_SH" "$MERGER"
assert_probe probe_codex_uninstall "$TMP_ROOT/un-control/uninstall.sh" roundtrip "no-op uninstall tree control remains green"
UNINSTALL_MUTATIONS=(
  $'uninstall\tprofile-links-skipped\t[[ "$_codex_hooks" == "$CODEX_DIR/hooks.json" || ! -L "$_codex_hooks" ]] || continue\t:\texternal-link'
  $'uninstall\tprofiles-cleaned\t[[ "$_codex_hooks" == "$CODEX_DIR/hooks.json" || ! -L "$_codex_hooks" ]] || continue\t[[ "$_codex_hooks" == "$CODEX_DIR/hooks.json" ]] || continue\troundtrip'
  $'uninstall\tadapter-kept\tif [[ -n "$_codex_still" ]]; then\tif false; then\tinvalid'
  $'merger\tno-op-write\tif removed:\tif True:\tuntouched'
  $'merger\tempty-group\tif not handlers:\tif False:\troundtrip'
  $'merger\tshared-group\tgroup["hooks"] = handlers\tcontinue\troundtrip'
  $'merger\tuser-empty-event\tif event_removed and not kept_groups:\tif not kept_groups:\troundtrip'
  $'merger\temptied-event\tif event_removed and not kept_groups:\tif False:\troundtrip'
  $'merger\tadapter-prefix\t.startswith(prefix)]\t.startswith("")]\troundtrip'
)
for mutation in "${UNINSTALL_MUTATIONS[@]}"; do
  IFS=$'\t' read -r kind name old new probe <<< "$mutation"
  [[ -n "$probe" ]] || { fail "uninstall mutation $name is one well-formed row" "$mutation"; continue; }
  tree="$TMP_ROOT/un-mut-$name"
  mkdir -p "$tree"
  if [[ "$kind" == uninstall ]]; then
    mutate "$UNINSTALL_SH" "$tree/uninstall.mutant" "$old" "$new" \
      && uninstall_tree "$tree" "$tree/uninstall.mutant" "$MERGER"
  else
    mutate "$MERGER" "$tree/merger.mutant" "$old" "$new" \
      && uninstall_tree "$tree" "$UNINSTALL_SH" "$tree/merger.mutant"
  fi || { fail "uninstall mutation $name removes its intended guard" "mutation text not found"; continue; }
  if ! bash -n "$tree/uninstall.sh" 2>/dev/null \
     || ! python3 -c 'import ast, sys; ast.parse(open(sys.argv[1]).read())' "$tree/configs/scripts/codex-hooks-merge.py" 2>/dev/null; then
    fail "uninstall mutation $name still parses" "a mutant that cannot run goes red for the wrong reason"
    continue
  fi
  if probe_codex_uninstall "$tree/uninstall.sh" "$probe" >/dev/null 2>&1; then
    fail "uninstall mutation $name goes red" "mutant survived $probe"
  else
    pass "uninstall mutation $name goes red"
  fi
done

printf '\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
if [[ "$TESTS_FAILED" == 0 ]]; then
  printf "  ${GREEN}ALL PASSED${NC} (%d/%d)\n" "$TESTS_PASSED" "$TESTS_RUN"
else
  printf "  ${RED}%d FAILED${NC} / %d passed / %d total\n" "$TESTS_FAILED" "$TESTS_PASSED" "$TESTS_RUN"
fi
printf '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
exit "$TESTS_FAILED"
