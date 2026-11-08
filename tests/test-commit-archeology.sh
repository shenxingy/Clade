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

printf '# first run: detached scan creates the cache\n'
FIRST_OUT=$(COMMIT_ARCH_TEST_SCAN_DELAY=1 run_arch --inject)
assert_empty "$FIRST_OUT" 'first run prints nothing'
if wait_for_file "$(lessons_file)" && wait_for_head "$(git -C "$PROJ" rev-parse HEAD)"; then
  pass 'first run creates cache and records HEAD in the background'
else
  fail 'first run creates cache and records HEAD in the background' "cache=$(lessons_file)"
fi
assert_contains "$(< "$(lessons_file)")" 'wiring-gap' 'background scan writes real detector output'
wait_for_lock_release
assert_eq "$(scan_count)" '1' 'first run scans exactly once'

printf '# fresh cache: no refresh, even if HEAD moves\n'
reset_scan_log
move_head
FRESH_OUT=$(COMMIT_ARCH_TEST_SCAN_DELAY=1 run_arch --inject)
assert_contains "$FRESH_OUT" 'wiring-gap' 'fresh cached lessons are injected'
sleep 0.2
assert_eq "$(scan_count)" '0' 'fresh cache does not rescan after HEAD moves'

printf '# unchanged HEAD: age alone never triggers archaeology\n'
seed_cache
age_cache
UNCHANGED_OUT=$(COMMIT_ARCH_TEST_SCAN_DELAY=1 run_arch --inject)
assert_contains "$UNCHANGED_OUT" 'wiring-gap' 'unchanged-HEAD cache is still injected'
sleep 0.2
assert_eq "$(scan_count)" '0' 'unchanged HEAD past the age limit does not rescan'

printf '# explicit force: retain the synchronous manual escape hatch\n'
seed_cache
FORCE_OUT=$(COMMIT_ARCH_TEST_SCAN_DELAY=1 run_arch --inject --force)
assert_contains "$FORCE_OUT" 'wiring-gap' 'forced injection prints the refreshed lessons'
assert_eq "$(scan_count)" '1' 'forced injection scans inline even with a fresh unchanged cache'

printf '# stale cache: print first, refresh later\n'
seed_cache
age_cache
move_head
NEW_HEAD=$(git -C "$PROJ" rev-parse HEAD)
T0=$(date +%s)
STALE_OUT=$(COMMIT_ARCH_TEST_SCAN_DELAY=4 run_arch --inject)
RC=$?
T1=$(date +%s)
assert_eq "$RC" '0' 'stale injection exits zero'
assert_contains "$STALE_OUT" 'wiring-gap' 'stale cached lessons are printed immediately'
assert_lt "$((T1 - T0))" '2' 'stale injection returns well under the four-second scan'
wait_for_scan_count 1
wait_for_head "$NEW_HEAD"
wait_for_lock_release
assert_eq "$(scan_count)" '1' 'stale injection launches one background refresh'

printf '# concurrent starts: one refresh per repository\n'
seed_cache
age_cache
move_head
NEW_HEAD=$(git -C "$PROJ" rev-parse HEAD)
(COMMIT_ARCH_TEST_REFRESH_START_DELAY=0.3 COMMIT_ARCH_TEST_SCAN_DELAY=2 run_arch --inject > "$SANDBOX/concurrent-1.out") &
P1=$!
(COMMIT_ARCH_TEST_REFRESH_START_DELAY=0.3 COMMIT_ARCH_TEST_SCAN_DELAY=2 run_arch --inject > "$SANDBOX/concurrent-2.out") &
P2=$!
wait "$P1"
RC1=$?
wait "$P2"
RC2=$?
assert_eq "$RC1|$RC2" '0|0' 'both concurrent injections exit zero'
wait_for_scan_count 1
wait_for_head "$NEW_HEAD"
wait_for_lock_release
assert_eq "$(scan_count)" '1' 'two concurrent injections launch exactly one scan'
assert_contains "$(< "$SANDBOX/concurrent-1.out")" 'wiring-gap' 'first concurrent caller gets cached lessons'
assert_contains "$(< "$SANDBOX/concurrent-2.out")" 'wiring-gap' 'second concurrent caller gets cached lessons'

printf '# stale lock: a paused reclaimer cannot delete a fresh PID\n'
seed_cache
age_cache
move_head
NEW_HEAD=$(git -C "$PROJ" rev-parse HEAD)
mkdir -p "$(lock_dir)"
bash -c 'exit 0' &
DEAD_PID=$!
wait "$DEAD_PID" 2>/dev/null
printf '%s\n' "$DEAD_PID" > "$(lock_dir)/pid"
RECLAIM_LOG="$SANDBOX/reclaim.log"
: > "$RECLAIM_LOG"
(COMMIT_ARCH_TEST_RECLAIM_LOG="$RECLAIM_LOG" COMMIT_ARCH_TEST_RECLAIM_DELAY=1 \
  COMMIT_ARCH_TEST_SCAN_DELAY=2 run_arch --inject > "$SANDBOX/stale-lock-2.out") &
P2=$!
if wait_for_nonempty "$RECLAIM_LOG"; then
  pass 'paused caller is holding the dead-PID read barrier'
else
  fail 'paused caller is holding the dead-PID read barrier' 'caller never reached the reclaim pause'
fi
(COMMIT_ARCH_TEST_SCAN_DELAY=2 run_arch --inject > "$SANDBOX/stale-lock-1.out") &
P1=$!
wait "$P1"
RC1=$?
wait "$P2"
RC2=$?
assert_eq "$RC1|$RC2" '0|0' 'both stale-lock callers exit zero'
assert_contains "$(< "$SANDBOX/stale-lock-1.out")" 'wiring-gap' 'dead lock does not suppress cached output'
assert_contains "$(< "$SANDBOX/stale-lock-2.out")" 'wiring-gap' 'paused dead-lock caller also gets cached output'
wait_for_scan_count 1
if wait_for_head "$NEW_HEAD"; then pass 'dead lock is reclaimed and refreshes HEAD'
else fail 'dead lock is reclaimed and refreshes HEAD' 'HEAD sidecar was not updated'; fi
wait_for_lock_release
assert_eq "$(scan_count)" '1' 'paused stale-lock recovery still launches one scan'

printf '# reclaim mutex: a second caller cannot enter the held critical section\n'
seed_cache
age_cache
move_head
NEW_HEAD=$(git -C "$PROJ" rev-parse HEAD)
mkdir -p "$(lock_dir)"
bash -c 'exit 0' &
DEAD_PID=$!
wait "$DEAD_PID" 2>/dev/null
printf '%s\n' "$DEAD_PID" > "$(lock_dir)/pid"
HOLD_LOG="$SANDBOX/reclaim-held.log"
: > "$HOLD_LOG"
(COMMIT_ARCH_TEST_HOLD_LOG="$HOLD_LOG" COMMIT_ARCH_TEST_HOLD_DELAY=1 \
  COMMIT_ARCH_TEST_SCAN_DELAY=2 run_arch --inject > "$SANDBOX/mutex-hold-1.out") &
P1=$!
if wait_for_nonempty "$HOLD_LOG"; then
  pass 'first caller is paused after revalidation with the mutex held'
else
  fail 'first caller is paused after revalidation with the mutex held' 'caller never reached the post-revalidation hold'
fi
(COMMIT_ARCH_TEST_SCAN_DELAY=2 run_arch --inject > "$SANDBOX/mutex-hold-2.out") &
P2=$!
wait "$P2"
RC2=$?
wait "$P1"
RC1=$?
assert_eq "$RC1|$RC2" '0|0' 'both mutex-hold callers exit zero'
assert_contains "$(< "$SANDBOX/mutex-hold-1.out")" 'wiring-gap' 'mutex holder prints cached lessons'
assert_contains "$(< "$SANDBOX/mutex-hold-2.out")" 'wiring-gap' 'second caller prints cached lessons while mutex is held'
wait_for_scan_count 1
if wait_for_head "$NEW_HEAD"; then pass 'mutex-held recovery refreshes the HEAD sidecar'
else fail 'mutex-held recovery refreshes the HEAD sidecar' 'HEAD sidecar was not updated'; fi
wait_for_lock_release
assert_eq "$(scan_count)" '1' 'second caller cannot start a scan while the mutex is held'
if [[ -d "$(lock_dir)" || -d "$(lock_dir).reclaim" ]]; then
  fail 'mutex-held recovery releases both lock directories' 'lock or reclaim directory remains'
else
  pass 'mutex-held recovery releases both lock directories'
fi

printf '# stale reclaim mutex: an abandoned directory is reclaimed\n'
seed_cache
age_cache
move_head
NEW_HEAD=$(git -C "$PROJ" rev-parse HEAD)
mkdir -p "$(lock_dir)"
bash -c 'exit 0' &
DEAD_PID=$!
wait "$DEAD_PID" 2>/dev/null
printf '%s\n' "$DEAD_PID" > "$(lock_dir)/pid"
mkdir "$(lock_dir).reclaim"
touch -t 200001010000 "$(lock_dir).reclaim"
ABANDONED_OUT=$(COMMIT_ARCH_TEST_SCAN_DELAY=1 run_arch --inject)
assert_contains "$ABANDONED_OUT" 'wiring-gap' 'abandoned reclaim mutex allows cached output'
wait_for_scan_count 1
if wait_for_head "$NEW_HEAD"; then pass 'abandoned reclaim mutex permits the refresh'
else fail 'abandoned reclaim mutex permits the refresh' 'HEAD sidecar was not updated'; fi
wait_for_lock_release
assert_eq "$(scan_count)" '1' 'abandoned reclaim mutex launches one scan'
if [[ -d "$(lock_dir).reclaim" ]]; then
  fail 'reclaim mutex is released after recovery' "$(lock_dir).reclaim remains"
else
  pass 'reclaim mutex is released after recovery'
fi

printf '# malformed and half-created locks are not stolen\n'
seed_cache
age_cache
move_head
reset_scan_log
mkdir -p "$(lock_dir)"
printf 'not-a-pid\n' > "$(lock_dir)/pid"
MALFORMED_OUT=$(COMMIT_ARCH_TEST_SCAN_DELAY=1 run_arch --inject)
assert_contains "$MALFORMED_OUT" 'wiring-gap' 'malformed lock still allows cached output'
sleep 0.2
assert_eq "$(scan_count)" '0' 'malformed lock is not treated as a dead numeric pid'
rm -f "$(lock_dir)/pid"
rmdir "$(lock_dir)"
mkdir "$(lock_dir)"
EMPTY_LOCK_OUT=$(COMMIT_ARCH_TEST_SCAN_DELAY=1 run_arch --inject)
assert_contains "$EMPTY_LOCK_OUT" 'wiring-gap' 'half-created lock still allows cached output'
sleep 0.2
assert_eq "$(scan_count)" '0' 'lock without a PID is left for its in-flight owner'
rmdir "$(lock_dir)"

printf '# internal refresh rejects an invalid lock\n'
reset_scan_log
INVALID_OUT=$(run_arch --refresh "$SANDBOX/not-a-lock")
assert_empty "$INVALID_OUT" 'invalid internal refresh prints nothing'
sleep 0.2
assert_eq "$(scan_count)" '0' 'invalid internal refresh does not scan'

printf '# no setsid: POSIX nohup fallback completes first-run scan\n'
NO_SETSID_BIN="$SANDBOX/no-setsid-bin"
mkdir -p "$NO_SETSID_BIN"
for cmd in awk bash basename chmod date dirname git grep head id jq mkdir mv nohup paste rm rmdir sed sleep stat tail tr wc; do
  ln -s "$(command -v "$cmd")" "$NO_SETSID_BIN/$cmd"
done
rm -f "$(lessons_file)" "$(head_file)"
reset_scan_log
NO_SETSID_OUT=$(PATH="$NO_SETSID_BIN" COMMIT_ARCH_TEST_SCAN_DELAY=0 run_arch --inject 2> "$SANDBOX/no-setsid.err")
assert_empty "$NO_SETSID_OUT" 'nohup fallback first run prints nothing'
assert_empty "$(< "$SANDBOX/no-setsid.err")" 'fast nohup handoff is silent when the child finishes first'
if wait_for_file "$(lessons_file)" && wait_for_head "$(git -C "$PROJ" rev-parse HEAD)"; then
  pass 'nohup fallback creates the cache and HEAD sidecar'
else
  fail 'nohup fallback creates the cache and HEAD sidecar' 'fallback scan did not finish'
fi
wait_for_lock_release
assert_eq "$(scan_count)" '1' 'nohup fallback scans exactly once'

printf '# setsid preference and prompt PID handoff\n'
REAL_SETSID=$(command -v setsid 2>/dev/null || true)
if [[ -n "$REAL_SETSID" ]]; then
  SETSID_BIN="$SANDBOX/setsid-bin"
  cp -a "$NO_SETSID_BIN" "$SETSID_BIN"
  cat > "$SETSID_BIN/setsid" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$COMMIT_ARCH_TEST_SETSID_LOG"
exec "$COMMIT_ARCH_TEST_REAL_SETSID" "$@"
EOF
  rm -f "$SETSID_BIN/sleep"
  cat > "$SETSID_BIN/sleep" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "${1:-}" >> "$COMMIT_ARCH_TEST_SLEEP_LOG"
exec "$COMMIT_ARCH_TEST_REAL_SLEEP" "$@"
EOF
  chmod +x "$SETSID_BIN/setsid" "$SETSID_BIN/sleep"
  REAL_SLEEP=$(command -v sleep)
  : > "$SANDBOX/setsid.log"
  : > "$SANDBOX/sleep.log"
  rm -f "$(lessons_file)" "$(head_file)"
  reset_scan_log
  SETSID_OUT=$(PATH="$SETSID_BIN" COMMIT_ARCH_TEST_REAL_SETSID="$REAL_SETSID" \
    COMMIT_ARCH_TEST_REAL_SLEEP="$REAL_SLEEP" \
    COMMIT_ARCH_TEST_SETSID_LOG="$SANDBOX/setsid.log" \
    COMMIT_ARCH_TEST_SLEEP_LOG="$SANDBOX/sleep.log" \
    COMMIT_ARCH_TEST_SCAN_DELAY=2 run_arch --inject)
  assert_empty "$SETSID_OUT" 'setsid first run prints nothing'
  if wait_for_file "$(lessons_file)" && wait_for_head "$(git -C "$PROJ" rev-parse HEAD)"; then
    pass 'setsid launch creates the cache and HEAD sidecar'
  else
    fail 'setsid launch creates the cache and HEAD sidecar' 'setsid scan did not finish'
  fi
  wait_for_lock_release
  SETSID_CALLS=$(grep -c . "$SANDBOX/setsid.log" 2>/dev/null)
  assert_eq "${SETSID_CALLS:-0}" '1' 'setsid is preferred when available'
  HANDOFF_SLEEPS=$(grep -c '^0.1$' "$SANDBOX/sleep.log" 2>/dev/null)
  assert_le "${HANDOFF_SLEEPS:-0}" '2' 'PID handoff breaks promptly once the child owns the lock'
else
  printf 'setsid unavailable: preferred-launch assertions not applicable\n'
fi

printf '# disown failure: refresh still fails open\n'
rm -f "$(lessons_file)" "$(head_file)"
reset_scan_log
disown() { return 1; }
export -f disown
DISOWN_OUT=$(run_arch --inject)
DISOWN_RC=$?
unset -f disown
assert_eq "$DISOWN_RC" '0' 'a disown failure does not fail SessionStart'
assert_empty "$DISOWN_OUT" 'disown failure does not add output'
if wait_for_file "$(lessons_file)" && wait_for_head "$(git -C "$PROJ" rev-parse HEAD)"; then
  pass 'disown failure does not cancel the detached scan'
else
  fail 'disown failure does not cancel the detached scan' 'scan did not finish'
fi
wait_for_lock_release

printf '# runtime setup: missing helper and state failure stop before lock work\n'
mv "$TEST_ROOT/hooks/lib/runtime-dir.sh" "$TEST_ROOT/hooks/lib/runtime-dir.sh.saved"
rm -f "$(lessons_file)" "$(head_file)"
reset_scan_log
clade_state_dir() {
  mkdir -p "$CLADE_RUNTIME_DIR/commit-archeology"
  printf '%s\n' "$CLADE_RUNTIME_DIR/commit-archeology"
}
export -f clade_state_dir
MISSING_HELPER_OUT=$(run_arch --inject)
MISSING_HELPER_RC=$?
unset -f clade_state_dir
mv "$TEST_ROOT/hooks/lib/runtime-dir.sh.saved" "$TEST_ROOT/hooks/lib/runtime-dir.sh"
assert_eq "$MISSING_HELPER_RC" '0' 'missing runtime helper fails open for SessionStart'
assert_empty "$MISSING_HELPER_OUT" 'missing runtime helper prints nothing'
sleep 0.2
assert_eq "$(scan_count)" '0' 'missing runtime helper stops before state resolution or scanning'
wait_for_lock_release

mv "$TEST_ROOT/hooks/lib/runtime-dir.sh" "$TEST_ROOT/hooks/lib/runtime-dir.sh.saved"
printf 'clade_state_dir() { return 1; }\n' > "$TEST_ROOT/hooks/lib/runtime-dir.sh"
rm -f "$(lessons_file)" "$(head_file)"
reset_scan_log
: > "$SANDBOX/mkdir.log"
export COMMIT_ARCH_TEST_MKDIR_LOG="$SANDBOX/mkdir.log"
mkdir() {
  printf '%s\n' "$*" >> "$COMMIT_ARCH_TEST_MKDIR_LOG"
  command mkdir "$@"
}
export -f mkdir
STATE_FAIL_OUT=$(run_arch --inject)
STATE_FAIL_RC=$?
unset -f mkdir
unset COMMIT_ARCH_TEST_MKDIR_LOG
mv "$TEST_ROOT/hooks/lib/runtime-dir.sh.saved" "$TEST_ROOT/hooks/lib/runtime-dir.sh"
assert_eq "$STATE_FAIL_RC" '0' 'runtime state failure fails open for SessionStart'
assert_empty "$STATE_FAIL_OUT" 'runtime state failure prints nothing'
LOCK_ATTEMPTS=$(grep -c '[.]lock' "$SANDBOX/mkdir.log" 2>/dev/null)
assert_eq "${LOCK_ATTEMPTS:-0}" '0' 'runtime state failure stops before any lock mkdir'
assert_eq "$(scan_count)" '0' 'runtime state failure does not scan'

printf '# empty result: unchanged HEAD is still a cache hit\n'
EMPTY_PROJ="$SANDBOX/empty-project"
mkdir -p "$EMPTY_PROJ"
git -C "$EMPTY_PROJ" init -q
git -C "$EMPTY_PROJ" config user.name 'Archeology Test'
git -C "$EMPTY_PROJ" config user.email 'archeology@example.invalid'
for i in 1 2 3 4 5; do
  commit_file "$EMPTY_PROJ" feature.txt "feat: ordinary change $i"
done
SAVED_PROJ="$PROJ"
PROJ="$EMPTY_PROJ"
reset_scan_log
EMPTY_OUT=$(COMMIT_ARCH_TEST_SCAN_DELAY=0 run_arch --inject)
assert_empty "$EMPTY_OUT" 'empty first scan prints nothing'
if wait_for_file "$(lessons_file)" && wait_for_head "$(git -C "$PROJ" rev-parse HEAD)"; then
  pass 'a scan with no lessons still creates a HEAD-keyed cache'
else
  fail 'a scan with no lessons still creates a HEAD-keyed cache' 'empty cache or HEAD sidecar missing'
fi
wait_for_lock_release
age_cache
reset_scan_log
EMPTY_AGAIN=$(run_arch --inject)
assert_empty "$EMPTY_AGAIN" 'empty cached result stays silent'
sleep 0.2
assert_eq "$(scan_count)" '0' 'empty result at unchanged HEAD does not rescan'
PROJ="$SAVED_PROJ"

printf '# claude-overridden: batched history walk keeps detector semantics\n'
AGENT_PROJ="$SANDBOX/agent-project"
mkdir -p "$AGENT_PROJ"
git -C "$AGENT_PROJ" init -q
git -C "$AGENT_PROJ" config user.name 'Archeology Test'
git -C "$AGENT_PROJ" config user.email 'archeology@example.invalid'
commit_file "$AGENT_PROJ" base.txt 'feat: agent root commit' 'Co-Authored-By: Claude <claude@example.com>'
for i in 1 2 3 4; do
  commit_file "$AGENT_PROJ" "file-$i.txt" "feat: agent change $i" 'Co-Authored-By: Claude <claude@example.com>'
  commit_file "$AGENT_PROJ" "file-$i.txt" "fix: human follow-up $i"
done
commit_file "$AGENT_PROJ" skipped.txt 'feat: agent original to skip' 'Co-Authored-By: Claude <claude@example.com>'
commit_file "$AGENT_PROJ" skipped.txt 'feat: agent next means not overridden' 'Co-Authored-By: Claude <claude@example.com>'
commit_file "$AGENT_PROJ" skipped.txt 'fix: later human must not replace the agent next'
PROJ="$AGENT_PROJ"
GIT_BIN="$SANDBOX/git-bin"
mkdir -p "$GIT_BIN"
REAL_GIT=$(command -v git)
cat > "$GIT_BIN/git" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$COMMIT_ARCH_TEST_GIT_LOG"
exec "$COMMIT_ARCH_TEST_REAL_GIT" "$@"
EOF
chmod +x "$GIT_BIN/git"
AWK_BIN="$SANDBOX/awk-bin"
mkdir -p "$AWK_BIN"
REAL_AWK=$(command -v awk)
cat > "$AWK_BIN/awk" <<'EOF'
#!/usr/bin/env bash
original=("$@")
while [[ $# -gt 0 ]]; do
  if [[ "$1" == "-v" ]]; then
    shift
    if [[ "${1:-}" == *$'\n'* ]]; then
      printf 'newline in string\n' >&2
      exit 2
    fi
  fi
  shift
done
exec "$COMMIT_ARCH_TEST_REAL_AWK" "${original[@]}"
EOF
chmod +x "$AWK_BIN/awk"
SHIM_OUT=$(PATH="$AWK_BIN:$PATH" COMMIT_ARCH_TEST_REAL_AWK="$REAL_AWK" \
  awk -v "bad=$(printf 'a\nb')" 'BEGIN { print "ran" }' 2>&1)
SHIM_RC=$?
assert_eq "$SHIM_RC" '2' 'BWK-compatible awk shim rejects multiline -v data'
assert_contains "$SHIM_OUT" 'newline in string' 'awk shim reports the multiline -v defect'
GIT_LOG="$SANDBOX/git.log"
: > "$GIT_LOG"
PATH="$AWK_BIN:$GIT_BIN:$PATH" COMMIT_ARCH_TEST_REAL_AWK="$REAL_AWK" \
  COMMIT_ARCH_TEST_REAL_GIT="$REAL_GIT" \
  COMMIT_ARCH_TEST_GIT_LOG="$GIT_LOG" run_arch --scan >/dev/null 2>&1
AGENT_LESSONS="$(< "$(lessons_file)")"
assert_contains "$AGENT_LESSONS" '"pattern":"claude-overridden"' 'overridden detector emits a row'
assert_contains "$AGENT_LESSONS" '"count":5' 'an agent next is terminal for its predecessor, while that agent can itself be overridden'
assert_contains "$AGENT_LESSONS" 'fix: human follow-up 1' 'batched detector preserves the original last-hit ordering'
GIT_CALLS=$(wc -l < "$GIT_LOG" | tr -d ' ')
assert_le "$GIT_CALLS" '20' 'overridden detector batches file lists and per-commit metadata lookups'

printf '\n%d tests: %d passed, %d failed\n' "$TESTS_RUN" "$TESTS_PASSED" "$TESTS_FAILED"
[[ "$TESTS_FAILED" -eq 0 ]]
