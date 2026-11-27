#!/usr/bin/env bash
# test-ensure-dev-server.sh — Tests for configs/scripts/ensure-dev-server.sh
#   (Round-4 gap: idempotent dev-server discovery/start shared across
#   /verify, verify-app, and concurrent worktree workers)
#
# Uses REAL toy Node "dev servers" (a trivial http server via `node -e`) under
# throwaway /tmp project dirs — no mocking of curl/flock/jq, since the whole
# point of this script is real process + port + lock behavior. Every spawned
# server is tracked and force-killed on exit.
#
# Usage:
#   bash tests/test-ensure-dev-server.sh        # Run all tests
#   bash tests/test-ensure-dev-server.sh -v     # Verbose mode

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT="$REPO_ROOT/configs/scripts/ensure-dev-server.sh"

# ─── Test framework (mirrors tests/test-mailbox-drain.sh) ────────────
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
VERBOSE="${1:-}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

pass() { TESTS_PASSED=$((TESTS_PASSED + 1)); echo -e "  ${GREEN}✓${NC} $1"; }
fail() {
  TESTS_FAILED=$((TESTS_FAILED + 1))
  echo -e "  ${RED}✗${NC} $1"
  [[ -n "${2:-}" ]] && echo -e "    ${RED}→ $2${NC}"
}
section() { echo ""; echo -e "${YELLOW}━━━ $1 ━━━${NC}"; }

assert_contains() {
  local haystack="$1" needle="$2" msg="$3"
  TESTS_RUN=$((TESTS_RUN + 1))
  if grep -qF "$needle" <<< "$haystack"; then pass "$msg"
  else
    fail "$msg" "output does not contain '$needle'"
    [[ "$VERBOSE" == "-v" ]] && echo "    output: $haystack"
  fi
}
assert_eq() {
  local actual="$1" expected="$2" msg="$3"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ "$actual" == "$expected" ]]; then pass "$msg"
  else fail "$msg" "expected '$expected', got '$actual'"; fi
}

for bin in node curl jq python3; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "$bin not found — skipping (CI installs it)"; exit 0
  fi
done

# ─── Sandbox ─────────────────────────────────────────────────────────

SANDBOX="$(mktemp -d /tmp/clade-test-dev-server-XXXXXX)"
case "$SANDBOX" in
  /tmp/clade-test-dev-server-*) : ;;
  *) echo "FATAL: sandbox '$SANDBOX' not under /tmp — aborting"; exit 1 ;;
esac
_SPAWNED_PIDS=()
cleanup() {
  for p in "${_SPAWNED_PIDS[@]:-}"; do
    [[ -n "$p" ]] && kill -9 "$p" 2>/dev/null
    [[ -n "$p" ]] && kill -9 -- "-$p" 2>/dev/null  # process group too
  done
  rm -rf "$SANDBOX"
}
trap cleanup EXIT

toy_project() {
  # $1 = subdir name, $2 = port
  local dir="$SANDBOX/$1"
  mkdir -p "$dir/.claude"
  cat > "$dir/package.json" <<EOF
{"name":"toy","scripts":{"dev":"node -e \\"require('http').createServer((req,res)=>res.end('ok')).listen(process.env.PORT||$2)\\""}}
EOF
  echo "$dir"
}

# free_port: a port nothing on this host listens on, chosen per run. The cases
# used the fixed ports 4501-4504 and 4599 until 2026-11-26, so two runs on one
# host (concurrent gates, or a dev server already on 4501) shared servers: one
# run's cold start found the other's server, reported STATUS=reused, and three
# cases failed while the suite read as a flake.
free_port() {
  python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()'
}
# need_free PORT: the port must not answer before a case starts its own server,
# so a case never tests a server some other process owns.
need_free() {
  if curl -s -o /dev/null --max-time 1 "http://localhost:$1" 2>/dev/null; then
    echo "FATAL: port $1 already answers before the case started — another process owns it"; exit 1
  fi
}
PORT1=$(free_port); PORT2=$(free_port); PORT3=$(free_port); PORT4=$(free_port); PORT5=$(free_port)
for _p in "$PORT1" "$PORT2" "$PORT3" "$PORT4" "$PORT5"; do
  [[ "$_p" =~ ^[0-9]+$ ]] || { echo "FATAL: free_port returned '$_p'"; exit 1; }
  need_free "$_p"
done

track_state_pid() {
  # Records the pid from a project's dev-server.json for cleanup.
  local dir="$1"
  local pid
  pid=$(jq -r '.pid // empty' "$dir/.claude/dev-server.json" 2>/dev/null)
  [[ -n "$pid" ]] && _SPAWNED_PIDS+=("$pid")
}

# ─── 1. Cold start ─────────────────────────────────────────────────────
section "Cold start"

P1=$(toy_project proj1 "$PORT1")
OUT1=$(timeout 40 bash "$SCRIPT" "$PORT1" "$P1")
RC1=$?
track_state_pid "$P1"
assert_eq "$RC1" "0" "cold start exits 0"
assert_contains "$OUT1" "PORT=$PORT1" "reports the requested port"
assert_contains "$OUT1" "STATUS=started" "reports STATUS=started on cold start"
TESTS_RUN=$((TESTS_RUN + 1))
[[ -f "$P1/.claude/dev-server.json" ]] && pass "state file written" \
  || fail "state file written" "missing $P1/.claude/dev-server.json"

# ─── 2. Reuse (fast, same pid, no double-start) ────────────────────────
section "Reuse"

T0=$(date +%s%N)
OUT2=$(timeout 10 bash "$SCRIPT" "$PORT1" "$P1")
RC2=$?
T1=$(date +%s%N)
ELAPSED_MS=$(( (T1 - T0) / 1000000 ))
assert_eq "$RC2" "0" "reuse exits 0"
assert_contains "$OUT2" "STATUS=reused" "reports STATUS=reused on second call"
TESTS_RUN=$((TESTS_RUN + 1))
[[ "$ELAPSED_MS" -lt 5000 ]] && pass "reuse is fast (<5s, no restart attempted): ${ELAPSED_MS}ms" \
  || fail "reuse is fast (<5s, no restart attempted)" "took ${ELAPSED_MS}ms"

# ─── 3. Concurrent callers serialize — exactly one real process ───────
section "Concurrency"

P2=$(toy_project proj2 "$PORT2")
for _i in 1 2 3 4; do
  timeout 40 bash "$SCRIPT" "$PORT2" "$P2" > "$SANDBOX/race-$_i.out" 2>&1 &
done
wait
STARTED_COUNT=$(grep -l "STATUS=started" "$SANDBOX"/race-*.out 2>/dev/null | wc -l | tr -d ' ')
TESTS_RUN=$((TESTS_RUN + 1))
[[ "$STARTED_COUNT" == "1" ]] && pass "exactly one of 4 concurrent callers actually started the server" \
  || fail "exactly one of 4 concurrent callers actually started the server" "STATUS=started appeared $STARTED_COUNT times"

# Re-run once more now that the race has settled, to read a definitive status
FINAL=$(timeout 10 bash "$SCRIPT" "$PORT2" "$P2")
track_state_pid "$P2"
assert_contains "$FINAL" "STATUS=reused" "post-race call finds a single reused server"
NODE_COUNT=$(pgrep -f "PORT.*$PORT2|$PORT2.*listen" 2>/dev/null | wc -l | tr -d ' ')
TESTS_RUN=$((TESTS_RUN + 1))
# One tree is the dev command and at most its shell wrapper. Zero means no
# server ran at all, which `-le 2` alone passed (a record of 2026-11-26 shows
# "found 0" passing while the cold start had found another run's server).
[[ "$NODE_COUNT" -ge 1 && "$NODE_COUNT" -le 2 ]] && pass "exactly one server process tree for the race port (found $NODE_COUNT)" \
  || fail "exactly one server process tree for the race port" "found $NODE_COUNT matching processes — 0 is no server, 3+ a double-start"

# ─── 4. Unreachable — no dev-server available ──────────────────────────
section "Unreachable (no dev script)"

P3="$SANDBOX/proj3"
mkdir -p "$P3/.claude"
echo "no package.json here" > "$P3/README.md"
OUT4=$(timeout 10 bash "$SCRIPT" "$PORT3" "$P3")
RC4=$?
assert_eq "$RC4" "1" "no dev server available exits 1"
assert_contains "$OUT4" "STATUS=unreachable" "reports STATUS=unreachable"

# ─── 5. Port resolution from CLAUDE.md ─────────────────────────────────
section "Port from CLAUDE.md"

P4="$SANDBOX/proj4"
mkdir -p "$P4/.claude"
cat > "$P4/CLAUDE.md" <<EOF
## Project Type
Frontend: Next.js, port $PORT4
EOF
OUT5=$(timeout 10 bash "$SCRIPT" "" "$P4")
assert_contains "$OUT5" "PORT=$PORT4" "port parsed from CLAUDE.md's Frontend: line"
assert_contains "$OUT5" "STATUS=unreachable" "no package.json here either — still unreachable, not a crash"

# ─── 6. Already-reachable-but-untracked server is reused, not restarted ─
section "Untracked external server"

P5=$(toy_project proj5 "$PORT5")
# Start the toy server directly (bypassing the script) to simulate a server
# the user started by hand outside this script's tracking.
( cd "$P5" && setsid node -e "require('http').createServer((req,res)=>res.end('ok')).listen($PORT5)" \
    > /dev/null 2>&1 & )
_ext_wait=0
while [ "$_ext_wait" -lt 30 ]; do
  curl -sf -o /dev/null --max-time 1 "http://localhost:$PORT5" 2>/dev/null && break
  sleep 0.2
  _ext_wait=$((_ext_wait + 1))
done
OUT6=$(timeout 10 bash "$SCRIPT" "$PORT5" "$P5")
_ext_pid=$(pgrep -f "listen\($PORT5\)" 2>/dev/null | head -1)
[[ -n "$_ext_pid" ]] && _SPAWNED_PIDS+=("$_ext_pid")
assert_contains "$OUT6" "STATUS=reused" "untracked-but-reachable server is reused, not restarted"

# ─── Summary ─────────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  Ran: $TESTS_RUN  ${GREEN}Passed: $TESTS_PASSED${NC}  ${RED}Failed: $TESTS_FAILED${NC}"
[[ "$TESTS_FAILED" -eq 0 ]] && { echo -e "  ${GREEN}ALL PASSED${NC}"; exit 0; } || { echo -e "  ${RED}FAILURES${NC}"; exit 1; }
