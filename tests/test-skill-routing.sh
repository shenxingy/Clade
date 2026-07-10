#!/usr/bin/env bash
# test-skill-routing.sh — Tests for the shell-side skill routing layer:
#   configs/hooks/lib/domain-detect.sh   (file list → domain classification)
#   configs/hooks/skill-suggest.sh       (PostToolUse edit → next-skill hint)
#   configs/hooks/session-context.sh     (SessionStart project-aware routing)
#
# Uses throwaway dirs/git repos under mktemp; never touches the real $HOME
# state except read-only (session-context.sh reads ~/.claude, all guarded).
#
# Usage:
#   bash tests/test-skill-routing.sh        # Run all tests
#   bash tests/test-skill-routing.sh -v     # Verbose mode

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOMAIN_DETECT="$REPO_ROOT/configs/hooks/lib/domain-detect.sh"
SKILL_SUGGEST="$REPO_ROOT/configs/hooks/skill-suggest.sh"
SESSION_CONTEXT="$REPO_ROOT/configs/hooks/session-context.sh"

# ─── Test framework (mirrors tests/test-checks.sh) ────────────────────
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
VERBOSE="${1:-}"

RED='\033[0;31m'
GREEN='\033[0;32m'
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

assert_eq() {
  local expected="$1" actual="$2" msg="$3"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ "$expected" == "$actual" ]]; then
    pass "$msg"
  else
    fail "$msg" "expected '$expected', got '$actual'"
  fi
}

# Here-strings, not `echo | grep -q` — see tests/test-checks.sh for why.
assert_contains() {
  local haystack="$1" needle="$2" msg="$3"
  TESTS_RUN=$((TESTS_RUN + 1))
  if grep -qF "$needle" <<< "$haystack"; then
    pass "$msg"
  else
    fail "$msg" "output does not contain '$needle'"
    [[ "$VERBOSE" == "-v" ]] && echo "    output: $(head -5 <<< "$haystack")"
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

TMP_ROOT=$(mktemp -d /tmp/clade-routing-test.XXXXXX)
cleanup() { rm -rf "$TMP_ROOT"; }
trap cleanup EXIT

# ─── 1. domain-detect.sh ──────────────────────────────────────────────
echo "── domain-detect.sh ──"

# Run each detection in a subshell so DOMAIN doesn't leak between cases
detect() {
  ( source "$DOMAIN_DETECT"; detect_domain "$1"; echo "$DOMAIN" )
}

assert_eq "devops"   "$(detect 'Dockerfile')"                "Dockerfile → devops"
assert_eq "devops"   "$(detect '.github/workflows/ci.yml')"  "GitHub workflow → devops"
assert_eq "security" "$(detect 'src/auth/login.py')"         "auth path beats python → security"
assert_eq "frontend" "$(detect 'src/components/App.tsx')"    "tsx component → frontend"
assert_eq "backend"  "$(detect 'src/routes/users.ts')"       "ts under routes/ → backend"
assert_eq "frontend" "$(detect 'src/utils/format.ts')"       "plain ts util → frontend"
assert_eq "ml"       "$(detect 'train_model.py')"            "train*.py → ml"
assert_eq "backend"  "$(detect 'app/main.py')"               "plain python → backend"
assert_eq "backend"  "$(detect 'api/handler.go')"            "go handler → backend"
assert_eq "systems"  "$(detect 'pkg/parser.go')"             "plain go → systems"
assert_eq "ios"      "$(detect 'App/Main.swift')"            "swift → ios"
assert_eq "android"  "$(detect 'app/src/Main.kt')"           "kotlin → android"
assert_eq "academic" "$(detect 'paper/main.tex')"            "tex → academic"
assert_eq "cli"      "$(detect 'scripts/deploy.sh')"         "shell script → cli"
assert_eq "unknown"  "$(detect 'README')"                    "unmatched file → unknown"

# ─── 2. skill-suggest.sh ──────────────────────────────────────────────
echo "── skill-suggest.sh ──"

# Each call gets a fresh throttle dir unless the case tests throttling.
# The env var must prefix the bash stage of the pipe, NOT jq — otherwise the
# hook silently uses the real /tmp throttle dir shared with live sessions.
suggest() {
  local file_path="$1" throttle_dir="$2"
  jq -n --arg fp "$file_path" '{tool_input:{file_path:$fp}}' \
    | SKILL_SUGGEST_THROTTLE_DIR="$throttle_dir" bash "$SKILL_SUGGEST"
}

OUT=$(suggest "content/blog/post.md" "$(mktemp -d "$TMP_ROOT/th.XXXX")")
assert_contains "$OUT" "/blog-seo-check" "blog post edit suggests /blog-seo-check"

OUT=$(suggest "src/routes/users.py" "$(mktemp -d "$TMP_ROOT/th.XXXX")")
assert_contains "$OUT" "/verify" "API route edit suggests /verify"

OUT=$(suggest "src/auth/token.py" "$(mktemp -d "$TMP_ROOT/th.XXXX")")
assert_contains "$OUT" "/cso" "auth file edit suggests /cso"

OUT=$(suggest "configs/skills/foo/SKILL.md" "$(mktemp -d "$TMP_ROOT/th.XXXX")")
assert_contains "$OUT" "./install.sh" "Clade config edit suggests install.sh redeploy"

OUT=$(suggest "tests/foo_test.py" "$(mktemp -d "$TMP_ROOT/th.XXXX")")
assert_contains "$OUT" "test suite" "test file edit suggests running tests"

OUT=$(suggest "README.md" "$(mktemp -d "$TMP_ROOT/th.XXXX")")
assert_eq "" "$OUT" "unmatched file → no suggestion"

OUT=$(echo '{}' | SKILL_SUGGEST_THROTTLE_DIR="$(mktemp -d "$TMP_ROOT/th.XXXX")" bash "$SKILL_SUGGEST")
assert_eq "" "$OUT" "missing file_path → no output, no error"

# Throttle: same category twice within window → second call silent
TH_DIR=$(mktemp -d "$TMP_ROOT/th.XXXX")
OUT1=$(suggest "blog/a.md" "$TH_DIR")
OUT2=$(suggest "blog/b.md" "$TH_DIR")
assert_contains "$OUT1" "/blog-seo-check" "throttle: first blog suggestion fires"
assert_eq "" "$OUT2" "throttle: second blog suggestion within 5min is silent"

# Throttle is per-category: a different category still fires
OUT3=$(suggest "src/auth/token.py" "$TH_DIR")
assert_contains "$OUT3" "/cso" "throttle: different category unaffected"

# ─── 3. session-context.sh routing block ──────────────────────────────
echo "── session-context.sh routing ──"

make_repo() {
  local dir="$1"
  mkdir -p "$dir" && cd "$dir" || return 1
  git init -q -b main .
  git -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
  cd - >/dev/null || return 1
}

run_session_context() {
  local dir="$1"
  echo '{}' | CLAUDE_PROJECT_DIR="$dir" bash "$SESSION_CONTEXT" \
    | jq -r '.hookSpecificOutput.additionalContext // empty'
}

# Blog project routing
R1="$TMP_ROOT/repo-blog"
make_repo "$R1"
mkdir -p "$R1/blog"
OUT=$(run_session_context "$R1")
assert_contains "$OUT" "Blog project" "blog/ dir → blog routing hint"

# Design system routing
R2="$TMP_ROOT/repo-ds"
make_repo "$R2"
touch "$R2/.design-system.md"
OUT=$(run_session_context "$R2")
assert_contains "$OUT" "Design system detected" ".design-system.md → /frontend-design hint"

# Generic project-with-tests routing
R3="$TMP_ROOT/repo-node"
make_repo "$R3"
echo '{}' > "$R3/package.json"
OUT=$(run_session_context "$R3")
assert_contains "$OUT" "/verify after code changes" "package.json → /verify workflow hint"

# Regression guard: the <available_skills> XML catalog was removed 2026-07-10
# (duplicated Claude Code native skill discovery AND overflowed the hook
# output inline limit, knocking the whole context out to a persisted file).
assert_not_contains "$OUT" "<available_skills>" "no skill-catalog XML re-injection"
assert_not_contains "$OUT" "## Available Skills" "no Available Skills section"

# Non-git dir → silent exit 0
R4="$TMP_ROOT/not-a-repo"
mkdir -p "$R4"
OUT=$(echo '{}' | CLAUDE_PROJECT_DIR="$R4" bash "$SESSION_CONTEXT")
assert_eq "" "$OUT" "non-git dir → no output"

# Output is valid JSON when present
RAW=$(echo '{}' | CLAUDE_PROJECT_DIR="$R3" bash "$SESSION_CONTEXT")
TESTS_RUN=$((TESTS_RUN + 1))
if jq -e '.hookSpecificOutput.additionalContext' <<< "$RAW" >/dev/null 2>&1; then
  pass "hook output is valid additionalContext JSON"
else
  fail "hook output is valid additionalContext JSON" "jq could not parse: $(head -c 200 <<< "$RAW")"
fi

# ─── Summary ──────────────────────────────────────────────────────────
echo ""
echo "── Results: $TESTS_PASSED/$TESTS_RUN passed ──"
if [[ $TESTS_FAILED -gt 0 ]]; then
  exit 1
fi
exit 0
