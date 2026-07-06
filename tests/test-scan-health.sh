#!/usr/bin/env bash
# test-scan-health.sh — Tests for configs/scripts/scan-health.sh
#   Focused on _scan_mcp_budget: the MCP server context-budget audit
#   (tw93/Waza pattern — live reachability probe + estimated tool-schema
#   token cost vs a hard budget threshold).
#
# Sandboxed project dirs under /tmp only; never touches the real repo's
# .claude/mcp.json. Covers: servers under/over the token threshold (with
# the SAME server set, to prove it's the threshold gating and not server
# presence alone), an unreachable stdio server reported independent of
# budget outcome, a live-reachable http server NOT misreported as
# unreachable, and the missing/empty/malformed mcp.json no-op paths.
#
# Usage:
#   bash tests/test-scan-health.sh        # Run all tests
#   bash tests/test-scan-health.sh -v     # Verbose mode

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCAN="$REPO_ROOT/configs/scripts/scan-health.sh"

# ─── Test framework (mirrors tests/test-rule-injector.sh) ─────────────
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
}

section() { echo ""; echo -e "${YELLOW}━━━ $1 ━━━${NC}"; }
note() { echo -e "  ${YELLOW}·${NC} $1 (skipped)"; }

assert_contains() {
  local haystack="$1" needle="$2" msg="$3"
  TESTS_RUN=$((TESTS_RUN + 1))
  if grep -qF "$needle" <<< "$haystack"; then
    pass "$msg"
  else
    fail "$msg" "output does not contain '$needle'"
    [[ "$VERBOSE" == "-v" ]] && echo "    output: $(head -8 <<< "$haystack")"
  fi
}

assert_not_contains() {
  local haystack="$1" needle="$2" msg="$3"
  TESTS_RUN=$((TESTS_RUN + 1))
  if grep -qF "$needle" <<< "$haystack"; then
    fail "$msg" "output unexpectedly contains '$needle'"
  else
    pass "$msg"
  fi
}

assert_empty() {
  local out="$1" msg="$2"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ -z "$out" ]]; then
    pass "$msg"
  else
    fail "$msg" "expected no output, got: $(head -3 <<< "$out")"
  fi
}

assert_rc_zero() {
  local rc="$1" msg="$2"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ "$rc" -eq 0 ]]; then
    pass "$msg"
  else
    fail "$msg" "exit code $rc"
  fi
}

# ─── Sandbox ─────────────────────────────────────────────────────────

SANDBOX="$(mktemp -d /tmp/clade-test-scan-health-mcp-XXXXXX)"
case "$SANDBOX" in
  /tmp/clade-test-scan-health-mcp-*) : ;;
  *) echo "FATAL: sandbox '$SANDBOX' not under /tmp — aborting"; exit 1 ;;
esac
HTTP_PID=""
cleanup() {
  [[ -n "$HTTP_PID" ]] && kill "$HTTP_PID" 2>/dev/null
  rm -rf "$SANDBOX"
}
trap cleanup EXIT

mkproj() {
  local name="$1"
  mkdir -p "$SANDBOX/$name/.claude"
  echo "$SANDBOX/$name"
}

# Run scan-health.sh against a project dir with optional env overrides,
# e.g.: run_scan "$PROJ" MCP_TOOL_TOKEN_ESTIMATE=500 MCP_TOKEN_BUDGET_THRESHOLD=100
# stdout only (===TASK=== blocks); the "found N issue(s)" summary goes to stderr.
run_scan() {
  local dir="$1"; shift
  env "$@" bash "$SCAN" "$dir" 2>/dev/null
}

# ─── Suite 1: Missing / empty / malformed mcp.json — no-op, never crash ──

section "No mcp.json / empty / malformed config"

PROJ_NONE="$(mktemp -d "$SANDBOX/proj-none.XXXXXX")"
OUT=$(run_scan "$PROJ_NONE"); RC=$?
assert_empty "$OUT" "missing .claude/mcp.json produces no output"
assert_rc_zero "$RC" "missing .claude/mcp.json exits 0 (no set -e abort)"

PROJ_EMPTY="$(mkproj proj-empty)"
echo '{"mcpServers": {}}' > "$PROJ_EMPTY/.claude/mcp.json"
OUT=$(run_scan "$PROJ_EMPTY"); RC=$?
assert_empty "$OUT" "empty mcpServers dict produces no output"
assert_rc_zero "$RC" "empty mcpServers dict exits 0"

PROJ_BAD="$(mkproj proj-malformed)"
echo '{not valid json at all' > "$PROJ_BAD/.claude/mcp.json"
OUT=$(run_scan "$PROJ_BAD"); RC=$?
assert_empty "$OUT" "malformed JSON produces no output"
assert_rc_zero "$RC" "malformed JSON exits 0 (parse failure handled, not fatal)"

# ─── Suite 2: Token budget — under vs over, SAME server set ──────────────

section "Token budget: under vs over threshold (same servers, threshold varies)"

PROJ_BUDGET="$(mkproj proj-budget)"
cat > "$PROJ_BUDGET/.claude/mcp.json" <<'EOF'
{"mcpServers": {"onlyserver": {"command": "bash", "args": []}}}
EOF

# 1 server * 500 est = 500 tokens; threshold 5000 → well under, no budget task
OUT=$(run_scan "$PROJ_BUDGET" MCP_TOOL_TOKEN_ESTIMATE=500 MCP_TOKEN_BUDGET_THRESHOLD=5000); RC=$?
assert_not_contains "$OUT" "health_mcp_budget" "under-threshold: budget task does NOT fire"
assert_not_contains "$OUT" "health_mcp_unreachable" "under-threshold: single reachable server has no unreachable task"
assert_rc_zero "$RC" "under-threshold run exits 0"

# Same servers, same estimate, lower threshold → 500 > 100, must fire
OUT=$(run_scan "$PROJ_BUDGET" MCP_TOOL_TOKEN_ESTIMATE=500 MCP_TOKEN_BUDGET_THRESHOLD=100); RC=$?
assert_contains "$OUT" "health_mcp_budget" "over-threshold: budget task fires (same servers, lower threshold)"
assert_contains "$OUT" "~500 tokens across 1 server(s)" "over-threshold: task reports the computed total"
assert_contains "$OUT" "threshold 100" "over-threshold: task reports the threshold it exceeded"
assert_rc_zero "$RC" "over-threshold run exits 0"

# ─── Suite 3: Unreachable stdio server — reported, independent of budget ──

section "Unreachable server reporting (not silently ignored)"

PROJ_MIX="$(mkproj proj-mixed)"
cat > "$PROJ_MIX/.claude/mcp.json" <<'EOF'
{
  "mcpServers": {
    "goodsrv": {"command": "bash", "args": []},
    "badsrv": {"command": "definitely-not-a-real-mcp-binary-9x7z", "args": []}
  }
}
EOF

# High threshold so the budget check does NOT fire — proves unreachable
# reporting is independent of the budget outcome, not folded into it.
OUT=$(run_scan "$PROJ_MIX" MCP_TOOL_TOKEN_ESTIMATE=500 MCP_TOKEN_BUDGET_THRESHOLD=999999); RC=$?
assert_contains "$OUT" "health_mcp_unreachable" "unreachable stdio server IS reported even when budget is fine"
assert_contains "$OUT" "definitely-not-a-real-mcp-binary-9x7z" "unreachable task names the missing binary"
assert_not_contains "$OUT" "  - goodsrv (stdio): bash" "reachable server not listed under unreachable"
assert_not_contains "$OUT" "health_mcp_budget" "budget task withheld when total is under threshold"
assert_rc_zero "$RC" "mixed reachable/unreachable run exits 0"

# Low threshold on the SAME mixed set → both findings fire together, and
# the budget breakdown correctly labels each server's reachability.
OUT=$(run_scan "$PROJ_MIX" MCP_TOOL_TOKEN_ESTIMATE=500 MCP_TOKEN_BUDGET_THRESHOLD=100); RC=$?
assert_contains "$OUT" "health_mcp_unreachable" "both-findings case: unreachable task still present"
assert_contains "$OUT" "health_mcp_budget" "both-findings case: budget task fires (2*500=1000 > 100)"
assert_contains "$OUT" "goodsrv (stdio): ~500 tokens, reachable" "budget breakdown labels the reachable server correctly"
assert_contains "$OUT" "badsrv (stdio): ~500 tokens, unreachable" "budget breakdown labels the unreachable server correctly"

# ─── Suite 4: Live http/sse reachability probe ───────────────────────────

section "Live http/sse reachability probe"

if command -v python3 &>/dev/null && command -v curl &>/dev/null; then
  PORT=$((20000 + RANDOM % 10000))
  PROJ_HTTP_OK="$(mkproj proj-http-ok)"
  python3 -m http.server "$PORT" --directory "$PROJ_HTTP_OK" &>/dev/null &
  HTTP_PID=$!

  # Wait for the server to actually be listening (bounded, no fixed sleep).
  tries=0
  until curl -s -o /dev/null --max-time 1 "http://127.0.0.1:${PORT}/" 2>/dev/null || [[ $tries -ge 30 ]]; do
    tries=$((tries + 1))
    sleep 0.1
  done

  cat > "$PROJ_HTTP_OK/.claude/mcp.json" <<EOF
{"mcpServers": {"livehttp": {"url": "http://127.0.0.1:${PORT}/"}}}
EOF
  OUT=$(run_scan "$PROJ_HTTP_OK" MCP_TOOL_TOKEN_ESTIMATE=500 MCP_TOKEN_BUDGET_THRESHOLD=999999); RC=$?
  assert_empty "$OUT" "live-reachable http server produces no findings"
  assert_rc_zero "$RC" "live-reachable http run exits 0"

  kill "$HTTP_PID" 2>/dev/null
  wait "$HTTP_PID" 2>/dev/null
  HTTP_PID=""

  # Unreachable http: nothing listens on this port.
  DEAD_PORT=$((PORT + 1))
  PROJ_HTTP_DEAD="$(mkproj proj-http-dead)"
  cat > "$PROJ_HTTP_DEAD/.claude/mcp.json" <<EOF
{"mcpServers": {"deadhttp": {"url": "http://127.0.0.1:${DEAD_PORT}/"}}}
EOF
  OUT=$(run_scan "$PROJ_HTTP_DEAD" MCP_TOOL_TOKEN_ESTIMATE=500 MCP_TOKEN_BUDGET_THRESHOLD=999999); RC=$?
  assert_contains "$OUT" "health_mcp_unreachable" "unreachable http server IS reported"
  assert_contains "$OUT" "http://127.0.0.1:${DEAD_PORT}/" "unreachable http task names the unreachable URL"
  assert_rc_zero "$RC" "unreachable http run exits 0"
else
  note "live http reachability probe (python3/curl not available)"
fi

# ─── Summary ─────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ $TESTS_FAILED -eq 0 ]]; then
  echo -e "  ${GREEN}ALL PASSED${NC} ($TESTS_PASSED/$TESTS_RUN)"
else
  echo -e "  ${RED}$TESTS_FAILED FAILED${NC} / $TESTS_PASSED passed / $TESTS_RUN total"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

exit "$TESTS_FAILED"
