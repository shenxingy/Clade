#!/usr/bin/env bash
# test-commit-archeology.sh — non-blocking SessionStart commit-lesson refresh.
# Uses only a temporary HOME, runtime dir and synthetic git repositories.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCH_SOURCE="${COMMIT_ARCH_SCRIPT:-$REPO_ROOT/configs/scripts/commit-archeology.sh}"

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

pass() {
  TESTS_RUN=$((TESTS_RUN + 1))
  TESTS_PASSED=$((TESTS_PASSED + 1))
  printf 'ok %d - %s\n' "$TESTS_RUN" "$1"
}
fail() {
  TESTS_RUN=$((TESTS_RUN + 1))
  TESTS_FAILED=$((TESTS_FAILED + 1))
  printf 'not ok %d - %s\n' "$TESTS_RUN" "$1"
  [[ -n "${2:-}" ]] && printf '  %s\n' "$2"
}
assert_eq() {
  local got="$1" want="$2" label="$3"
  if [[ "$got" == "$want" ]]; then pass "$label"
  else fail "$label" "got '$got', want '$want'"; fi
}
assert_contains() {
  local text="$1" needle="$2" label="$3"
  if grep -qF "$needle" <<< "$text"; then pass "$label"
  else fail "$label" "missing '$needle'"; fi
}
assert_empty() {
  local text="$1" label="$2"
  if [[ -z "$text" ]]; then pass "$label"
  else fail "$label" "expected empty output, got '$text'"; fi
}
assert_lt() {
  local got="$1" ceiling="$2" label="$3"
  if [[ "$got" -lt "$ceiling" ]]; then pass "$label"
  else fail "$label" "got $got, expected < $ceiling"; fi
}
assert_le() {
  local got="$1" ceiling="$2" label="$3"
  if [[ "$got" -le "$ceiling" ]]; then pass "$label"
  else fail "$label" "got $got, expected <= $ceiling"; fi
}

SANDBOX="$(mktemp -d /tmp/clade-commit-archeology-test.XXXXXX)"
case "$SANDBOX" in
  /tmp/clade-commit-archeology-test.*) ;;
  *) printf 'unsafe sandbox: %s\n' "$SANDBOX" >&2; exit 1 ;;
esac
trap 'rm -rf "$SANDBOX"' EXIT

export HOME="$SANDBOX/home"
export GIT_CONFIG_NOSYSTEM=1
export GIT_CONFIG_GLOBAL="$SANDBOX/gitconfig"
mkdir -p "$HOME"
: > "$GIT_CONFIG_GLOBAL"

TEST_ROOT="$SANDBOX/configs"
TEST_ARCH="$TEST_ROOT/scripts/commit-archeology.sh"
mkdir -p "$TEST_ROOT/scripts" "$TEST_ROOT/hooks/lib"
cp "$REPO_ROOT/configs/hooks/lib/runtime-dir.sh" "$TEST_ROOT/hooks/lib/runtime-dir.sh"
# Delay and count only the temporary copy; production needs no test-only hook.
awk '
  /^scan\(\) \{/ {
    print
    print "  printf '\''%s\\n'\'' \"$$\" >> \"${COMMIT_ARCH_TEST_SCAN_LOG:-/dev/null}\""
    print "  sleep \"${COMMIT_ARCH_TEST_SCAN_DELAY:-0}\""
    next
  }
  /^run_refresh\(\) \{/ {
    print
    print "  sleep \"${COMMIT_ARCH_TEST_REFRESH_START_DELAY:-0}\""
    next
  }
  /^    kill -0 \"\$pid\" 2>\/dev\/null && return 0$/ {
    print
    print "    printf '\''reclaim-ready\\n'\'' >> \"${COMMIT_ARCH_TEST_RECLAIM_LOG:-/dev/null}\""
    print "    sleep \"${COMMIT_ARCH_TEST_RECLAIM_DELAY:-0}\""
    next
  }
  /^    rm -f \"\$lock\/pid\"$/ {
    print "    printf '\''reclaim-held\\n'\'' >> \"${COMMIT_ARCH_TEST_HOLD_LOG:-/dev/null}\""
    print "    sleep \"${COMMIT_ARCH_TEST_HOLD_DELAY:-0}\""
    print
    next
  }
  { print }
' "$ARCH_SOURCE" > "$TEST_ARCH"

CLAUDE_DIR="$HOME/.claude"
RUNTIME_DIR="$SANDBOX/runtime"
PROJ="$SANDBOX/project"
SCAN_LOG="$SANDBOX/scan.log"
: > "$SCAN_LOG"

slug() { printf '%s' "$1" | sed 's|/|-|g'; }
lessons_file() { printf '%s/commit-lessons/%s.jsonl\n' "$CLAUDE_DIR" "$(slug "$PROJ")"; }
head_file() { printf '%s.head\n' "$(lessons_file)"; }
lock_dir() { printf '%s/commit-archeology/%s.lock\n' "$RUNTIME_DIR" "$(slug "$PROJ")"; }
scan_count() {
  local count
  count=$(grep -c . "$SCAN_LOG" 2>/dev/null)
  printf '%s\n' "${count:-0}"
}
reset_scan_log() { : > "$SCAN_LOG"; }

commit_file() {
  local repo="$1" file="$2" message="$3" trailer="${4:-}"
  mkdir -p "$(dirname "$repo/$file")"
  printf '%s\n' "$message" >> "$repo/$file"
  git -C "$repo" add -- "$file"
  if [[ -n "$trailer" ]]; then
    git -C "$repo" commit -q -m "$message" -m "$trailer"
  else
    git -C "$repo" commit -q -m "$message"
  fi
}

make_project() {
  mkdir -p "$PROJ"
  git -C "$PROJ" init -q
  git -C "$PROJ" config user.name 'Archeology Test'
  git -C "$PROJ" config user.email 'archeology@example.invalid'
  commit_file "$PROJ" base.txt 'feat: initial state'
  for i in 1 2 3; do
    commit_file "$PROJ" wiring.txt "fix: wire startup hook $i"
  done
  commit_file "$PROJ" base.txt 'feat: enough history'
}

run_arch() {
  HOME="$HOME" CLAUDE_DIR="$CLAUDE_DIR" CLAUDE_PROJECT_DIR="$PROJ" \
    CLADE_RUNTIME_DIR="$RUNTIME_DIR" COMMIT_ARCH_MIN=3 \
    COMMIT_ARCH_TEST_SCAN_LOG="$SCAN_LOG" \
    COMMIT_ARCH_TEST_SCAN_DELAY="${COMMIT_ARCH_TEST_SCAN_DELAY:-0}" \
    COMMIT_ARCH_TEST_REFRESH_START_DELAY="${COMMIT_ARCH_TEST_REFRESH_START_DELAY:-0}" \
    COMMIT_ARCH_TEST_RECLAIM_LOG="${COMMIT_ARCH_TEST_RECLAIM_LOG:-/dev/null}" \
    COMMIT_ARCH_TEST_RECLAIM_DELAY="${COMMIT_ARCH_TEST_RECLAIM_DELAY:-0}" \
    COMMIT_ARCH_TEST_HOLD_LOG="${COMMIT_ARCH_TEST_HOLD_LOG:-/dev/null}" \
    COMMIT_ARCH_TEST_HOLD_DELAY="${COMMIT_ARCH_TEST_HOLD_DELAY:-0}" \
    bash "$TEST_ARCH" "$@"
}

wait_for_nonempty() {
  local file="$1" waited=0
  while [[ ! -s "$file" && "$waited" -lt 100 ]]; do
    sleep 0.1
    waited=$((waited + 1))
  done
  [[ -s "$file" ]]
}
wait_for_scan_count() {
  local wanted="$1" waited=0
  while [[ "$(scan_count)" -lt "$wanted" && "$waited" -lt 100 ]]; do
    sleep 0.1
    waited=$((waited + 1))
  done
  [[ "$(scan_count)" -ge "$wanted" ]]
}
wait_for_file() {
  local file="$1" waited=0
  while [[ ! -f "$file" && "$waited" -lt 100 ]]; do
    sleep 0.1
    waited=$((waited + 1))
  done
  [[ -f "$file" ]]
}
wait_for_head() {
  local wanted="$1" waited=0 current=""
  while [[ "$waited" -lt 100 ]]; do
    current=$(head -1 "$(head_file)" 2>/dev/null)
    [[ "$current" == "$wanted" ]] && return 0
    sleep 0.1
    waited=$((waited + 1))
  done
  return 1
}
wait_for_lock_release() {
  local waited=0
  while [[ -d "$(lock_dir)" && "$waited" -lt 100 ]]; do
    sleep 0.1
    waited=$((waited + 1))
  done
  [[ ! -d "$(lock_dir)" ]]
}
seed_cache() {
  COMMIT_ARCH_TEST_SCAN_DELAY=0 run_arch --scan >/dev/null 2>&1
  reset_scan_log
}
age_cache() { touch -t 200001010000 "$(lessons_file)"; }
move_head() { commit_file "$PROJ" moved.txt 'feat: move HEAD for refresh'; }

make_project
# ─── probe: trace the concurrent case on the old (#212) lock ───
DBG="$SANDBOX/dbg.log"; export DBG
python3 - "$TEST_ARCH" <<'PY'
import sys
p=sys.argv[1]; s=open(p).read()
def ins(anchor, add, after=True):
    global s
    assert s.count(anchor)==1, anchor
    s=s.replace(anchor, anchor+add if after else add+anchor)
L='printf "%s %s ' ; E='\\n" "$(date +%s.%N)" "$$" '
ins('start_refresh() {\n', '  printf "%s %s start_refresh ppid=%s\\n" "$(date +%s.%N)" "$$" "$PPID" >> "$DBG"\n')
ins('  if ! mkdir "$lock" 2>/dev/null; then\n    pid=$(head -1 "$lock/pid" 2>/dev/null)\n', '    printf "%s %s mkdir-fail pid=[%s] alive=%s\\n" "$(date +%s.%N)" "$$" "$pid" "$(kill -0 "$pid" 2>/dev/null && echo y || echo n)" >> "$DBG"\n')
ins('    current_pid=$(head -1 "$lock/pid" 2>/dev/null)\n', '    printf "%s %s reclaim-mutex current=[%s]\\n" "$(date +%s.%N)" "$$" "$current_pid" >> "$DBG"\n')
ins('    rm -f "$lock/pid"\n    rmdir "$lock" 2>/dev/null\n', '    printf "%s %s RECLAIM from %s\\n" "$(date +%s.%N)" "$$" "$pid" >> "$DBG"\n', after=False)
ins('  else\n    printf \'%s\\n\' "$$" > "$lock/pid"\n  fi\n', '  printf "%s %s owns lock\\n" "$(date +%s.%N)" "$$" >> "$DBG"\n')
ins('  printf \'%s\\n\' "$!" > "$lock/pid" 2>/dev/null\n', '  printf "%s %s spawned %s file=[%s] pgid=%s\\n" "$(date +%s.%N)" "$$" "$!" "$(head -1 "$lock/pid")" "$(ps -o pgid= -p $$ | tr -d " ")" >> "$DBG"\n')
ins('run_refresh() {\n', '  printf "%s %s run_refresh ppid=%s lock-exists=%s file=[%s]\\n" "$(date +%s.%N)" "$$" "$PPID" "$([[ -d "${1:-}" ]] && echo y || echo n)" "$(head -1 "${1:-/nonexistent}/pid" 2>/dev/null)" >> "$DBG"\n')
ins('  printf \'%s\\n\' "$$" > "$REFRESH_LOCK_DIR/pid"\n', '  printf "%s %s refresh head=[%s] HEAD=[%s]\\n" "$(date +%s.%N)" "$$" "$(head -1 "$(lessons_path).head" 2>/dev/null)" "$(git rev-parse HEAD 2>/dev/null)" >> "$DBG"\n')
ins('scan() {\n', '  printf "%s %s SCAN ppid=%s args=[%s]\\n" "$(date +%s.%N)" "$$" "$PPID" "$(tr "\\0" " " < /proc/$$/cmdline 2>/dev/null)" >> "$DBG"\n  ps -o pid=,ppid=,pgid=,sid=,stat=,args= -p "$$" -p "$PPID" >> "$DBG" 2>&1\n')
ins('          start_refresh\n', '          printf "%s %s inject-called-start_refresh cached=[%s] current=[%s]\\n" "$(date +%s.%N)" "$$" "$cached_head" "$current_head" >> "$DBG"\n', after=False)
open(p,'w').write(s)
PY
[[ $? -eq 0 ]] || { echo "instrumentation failed"; exit 1; }
bad=0; total=0
for iter in $(seq 1 "${ITERS:-30}"); do
  total=$((total+1))
  : > "$DBG"
  printf '%s TEST seed\n' "$(date +%s.%N)" >> "$DBG"
  seed_cache; age_cache; move_head
  NEW_HEAD=$(git -C "$PROJ" rev-parse HEAD)
  printf '%s TEST launch\n' "$(date +%s.%N)" >> "$DBG"
  (COMMIT_ARCH_TEST_REFRESH_START_DELAY=0.3 COMMIT_ARCH_TEST_SCAN_DELAY=2 run_arch --inject > /dev/null) &
  P1=$!
  (COMMIT_ARCH_TEST_REFRESH_START_DELAY=0.3 COMMIT_ARCH_TEST_SCAN_DELAY=2 run_arch --inject > /dev/null) &
  P2=$!
  wait "$P1"; wait "$P2"
  printf '%s TEST callers-done\n' "$(date +%s.%N)" >> "$DBG"
  wait_for_scan_count 1; wait_for_head "$NEW_HEAD"; wait_for_lock_release
  printf '%s TEST settled scans=%s\n' "$(date +%s.%N)" "$(scan_count)" >> "$DBG"
  sleep 0.5
  c=$(scan_count)
  if [[ "$c" != 1 ]]; then
    bad=$((bad+1)); echo "=== ITER $iter scans=$c scanlog=[$(tr '\n' ' ' < "$SCAN_LOG")]"; cat "$DBG"
  fi
done
echo "--- last iteration trace"; cat "$DBG"
echo "PROBE RESULT: $bad of $total iterations double-scanned"
