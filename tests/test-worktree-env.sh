#!/usr/bin/env bash
# test-worktree-env.sh — Tests for worktree worker environments:
#   configs/scripts/run-tasks-parallel.sh  (env bootstrap: .venv/node_modules
#       symlinks + optional 'Env bootstrap:' command from CLAUDE.md)
#   configs/hooks/post-tool-use-lint.sh    (per-file fast path by extension,
#       full verify_cmd fallback, exit-2 + lint-feedback.md contract)
#
# Uses throwaway git repos under /tmp and a stub `claude` binary on PATH;
# never touches the real $HOME and never calls the real claude CLI.
#
# Usage:
#   bash tests/test-worktree-env.sh        # Run all tests
#   bash tests/test-worktree-env.sh -v     # Verbose mode

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNNER="$REPO_ROOT/configs/scripts/run-tasks-parallel.sh"
HOOK="$REPO_ROOT/configs/hooks/post-tool-use-lint.sh"

# ─── Test framework (mirrors tests/test-checks.sh) ───────────────────
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

# Here-strings, not `echo | grep -q`: under pipefail, grep -q exits at the
# first match and can SIGPIPE the echo of a large haystack.
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

assert_file_exists() {
  local path="$1" msg="$2"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ -e "$path" ]]; then
    pass "$msg"
  else
    fail "$msg" "missing: $path"
  fi
}

assert_file_missing() {
  local path="$1" msg="$2"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ -e "$path" ]]; then
    fail "$msg" "unexpectedly exists: $path"
  else
    pass "$msg"
  fi
}

CLEANUP_DIRS=()
cleanup() {
  for d in "${CLEANUP_DIRS[@]:-}"; do
    [[ -n "$d" && -d "$d" ]] && rm -rf "$d"
  done
}
trap cleanup EXIT

# ═════════════════════════════════════════════════════════════════════
# Section 1: run-tasks-parallel.sh worktree env bootstrap
# ═════════════════════════════════════════════════════════════════════
echo "── worktree env bootstrap (run-tasks-parallel.sh) ──"

TMP=$(mktemp -d /tmp/clade-wtenv.XXXXXX)
CLEANUP_DIRS+=("$TMP")

# Main checkout: gitignored env dirs at root (.venv) and one level down
# (sub/node_modules) — exactly what a fresh worktree will lack.
WTREPO="$TMP/repo"
mkdir -p "$WTREPO"
git -C "$WTREPO" init -q -b main
git -C "$WTREPO" config user.email "test@clade.local"
git -C "$WTREPO" config user.name "clade-test"
printf '.venv/\nnode_modules/\n.marker-bootstrap\nlogs/\n' > "$WTREPO/.gitignore"
echo "hello" > "$WTREPO/README.md"
git -C "$WTREPO" add .gitignore README.md
git -C "$WTREPO" commit -qm "init"
mkdir -p "$WTREPO/.venv/bin" "$WTREPO/sub/node_modules"

# Stub claude: records env state of its cwd (the worktree), consumes stdin.
mkdir -p "$TMP/bin"
cat > "$TMP/bin/claude" << 'EOF'
#!/usr/bin/env bash
{
  [[ -L .venv ]] && echo "venv-symlink"
  [[ -d .venv && ! -L .venv ]] && echo "venv-realdir"
  [[ -L sub/node_modules ]] && echo "nm-symlink"
  [[ -f .marker-bootstrap ]] && echo "bootstrap-ran"
} >> "$MARKER_FILE"
cat > /dev/null
exit 0
EOF
chmod +x "$TMP/bin/claude"

TASKS="$TMP/tasks.txt"
cat > "$TASKS" << 'EOF'
===TASK===
model: haiku
timeout: 60
retries: 0
---
Record worktree env state
EOF

run_parallel() {
  # One full runner pass against the temp repo with the stub claude on PATH.
  ( cd "$WTREPO" && \
    env PATH="$TMP/bin:$PATH" MARKER_FILE="$MARKER_FILE" \
        WORKTREE_BASE="$TMP/wt" MAX_WORKERS=1 \
        timeout 180 bash "$RUNNER" "$TASKS" 2>&1 )
}

# ── Run 1: no bootstrap cmd (template placeholder) → symlinks only ──
cat > "$WTREPO/CLAUDE.md" << 'EOF'
# Project Type
- Type: toolkit
- Env bootstrap: [optional shell command, or N/A]
EOF
MARKER_FILE="$TMP/marker-1"
OUT=$(run_parallel)
MARKER=$(cat "$MARKER_FILE" 2>/dev/null || true)
assert_contains "$OUT" "SUCCESS" "run 1: task succeeds"
assert_contains "$MARKER" "venv-symlink" "run 1: .venv symlinked from main checkout"
assert_contains "$MARKER" "nm-symlink" "run 1: sub/node_modules symlinked (depth 2)"
assert_not_contains "$OUT" "Env bootstrap:" "run 1: template placeholder is not executed"
# Regression: trailing-slash gitignore patterns (.venv/) do NOT match symlinks,
# so the post-task `git add -A` auto-commit would stage them unless the runner
# removes the links first — leaking a self-pointing symlink into main.
TRACKED=$(git -C "$WTREPO" ls-files)
assert_not_contains "$TRACKED" ".venv" "run 1: env symlink never committed/merged into main"
assert_not_contains "$TRACKED" "node_modules" "run 1: node_modules symlink never committed/merged"

# ── Run 2: bootstrap cmd creates .venv → symlink pass must not clobber ──
cat > "$WTREPO/CLAUDE.md" << 'EOF'
# Project Type
- Type: toolkit
- Env bootstrap: mkdir -p .venv && touch .marker-bootstrap
EOF
MARKER_FILE="$TMP/marker-2"
OUT=$(run_parallel)
MARKER=$(cat "$MARKER_FILE" 2>/dev/null || true)
assert_contains "$MARKER" "bootstrap-ran" "run 2: Env bootstrap command executed in worktree"
assert_contains "$MARKER" "venv-realdir" "run 2: bootstrap-created .venv NOT clobbered by symlink"
assert_contains "$MARKER" "nm-symlink" "run 2: missing dirs still symlinked alongside bootstrap"

# ── Run 3: bootstrap cmd fails → warn + continue, spawn unaffected ──
cat > "$WTREPO/CLAUDE.md" << 'EOF'
# Project Type
- Type: toolkit
- Env bootstrap: exit 7
EOF
MARKER_FILE="$TMP/marker-3"
OUT=$(run_parallel)
MARKER=$(cat "$MARKER_FILE" 2>/dev/null || true)
assert_contains "$OUT" "WARNING: Env bootstrap failed" "run 3: failed bootstrap warns"
assert_contains "$OUT" "SUCCESS" "run 3: task still spawns and succeeds"
assert_contains "$MARKER" "venv-symlink" "run 3: symlinks still applied after bootstrap failure"

# ═════════════════════════════════════════════════════════════════════
# Section 2: post-tool-use-lint.sh per-file fast path
# ═════════════════════════════════════════════════════════════════════
echo "── post-edit lint hook (post-tool-use-lint.sh) ──"

PROJ=$(mktemp -d /tmp/clade-lint.XXXXXX)
CLEANUP_DIRS+=("$PROJ")
mkdir -p "$PROJ/.claude"
cat > "$PROJ/.claude/orchestrator.json" << 'EOF'
{"verify_cmd": "touch verify-ran.marker"}
EOF

run_hook() {
  # $1 = project dir, $2 = stdin JSON. Sets HOOK_OUT / HOOK_EC.
  HOOK_OUT=$(printf '%s' "$2" | CLAUDE_PROJECT_DIR="$1" bash "$HOOK" 2>&1)
  HOOK_EC=$?
}

fixture_json() {
  jq -n --arg fp "$1" '{tool_name: "Edit", tool_input: {file_path: $fp}}'
}

# ── .py with a syntax error → per-file check fails, full verify skipped ──
printf 'def broken(:\n    pass\n' > "$PROJ/bad.py"
rm -f "$PROJ/verify-ran.marker" "$PROJ/.claude/lint-feedback.md"
run_hook "$PROJ" "$(fixture_json "$PROJ/bad.py")"
assert_eq "2" "$HOOK_EC" "bad .py: exits 2"
assert_contains "$HOOK_OUT" "per-file check failed" "bad .py: stderr names the per-file check"
assert_file_exists "$PROJ/.claude/lint-feedback.md" "bad .py: lint-feedback.md written"
assert_contains "$(cat "$PROJ/.claude/lint-feedback.md")" "bad.py" "bad .py: feedback names the file"
assert_file_missing "$PROJ/verify-ran.marker" "bad .py: full verify_cmd NOT run"

# ── valid .py → per-file check passes, full verify skipped ──
printf 'x = 1\n' > "$PROJ/good.py"
rm -f "$PROJ/verify-ran.marker"
run_hook "$PROJ" "$(fixture_json "$PROJ/good.py")"
assert_eq "0" "$HOOK_EC" "good .py: exits 0"
assert_file_missing "$PROJ/verify-ran.marker" "good .py: full verify_cmd NOT run"

# ── .sh with a syntax error → bash -n fails ──
printf 'if [ ; then\n' > "$PROJ/bad.sh"
rm -f "$PROJ/verify-ran.marker" "$PROJ/.claude/lint-feedback.md"
run_hook "$PROJ" "$(fixture_json "$PROJ/bad.sh")"
assert_eq "2" "$HOOK_EC" "bad .sh: exits 2"
assert_file_exists "$PROJ/.claude/lint-feedback.md" "bad .sh: lint-feedback.md written"
assert_contains "$(cat "$PROJ/.claude/lint-feedback.md")" "bad.sh" "bad .sh: feedback names the file"
assert_file_missing "$PROJ/verify-ran.marker" "bad .sh: full verify_cmd NOT run"

# ── valid .sh → per-file check passes ──
printf 'echo ok\n' > "$PROJ/good.sh"
rm -f "$PROJ/verify-ran.marker"
run_hook "$PROJ" "$(fixture_json "$PROJ/good.sh")"
assert_eq "0" "$HOOK_EC" "good .sh: exits 0"

# ── relative file_path resolves against the project dir ──
printf 'def nope(:\n' > "$PROJ/rel.py"
run_hook "$PROJ" "$(fixture_json "rel.py")"
assert_eq "2" "$HOOK_EC" "relative .py path: resolved and checked (exits 2)"

# ── no per-file check applies (.md) → falls back to full verify_cmd ──
echo "# doc" > "$PROJ/notes.md"
rm -f "$PROJ/verify-ran.marker"
run_hook "$PROJ" "$(fixture_json "$PROJ/notes.md")"
assert_eq "0" "$HOOK_EC" ".md edit: exits 0 via verify_cmd fallback"
assert_file_exists "$PROJ/verify-ran.marker" ".md edit: full verify_cmd ran"

# ── garbage stdin → falls back to full verify_cmd (legacy behavior) ──
rm -f "$PROJ/verify-ran.marker"
run_hook "$PROJ" "not json at all"
assert_eq "0" "$HOOK_EC" "garbage stdin: exits 0 via verify_cmd fallback"
assert_file_exists "$PROJ/verify-ran.marker" "garbage stdin: full verify_cmd ran"

# ── fallback failure preserves the original contract exactly ──
PROJ2=$(mktemp -d /tmp/clade-lint2.XXXXXX)
CLEANUP_DIRS+=("$PROJ2")
mkdir -p "$PROJ2/.claude"
cat > "$PROJ2/.claude/orchestrator.json" << 'EOF'
{"verify_cmd": "echo BUILD BROKE >&2; exit 1"}
EOF
echo "# doc" > "$PROJ2/notes.md"
run_hook "$PROJ2" "$(fixture_json "$PROJ2/notes.md")"
assert_eq "2" "$HOOK_EC" "fallback failure: exits 2"
assert_contains "$HOOK_OUT" "verify_cmd failed" "fallback failure: original stderr message kept"
FEEDBACK=$(cat "$PROJ2/.claude/lint-feedback.md" 2>/dev/null || true)
assert_contains "$FEEDBACK" "verify_cmd" "fallback failure: feedback names verify_cmd"
assert_contains "$FEEDBACK" "BUILD BROKE" "fallback failure: feedback carries command output"

# ── no orchestrator.json → silent no-op ──
PROJ3=$(mktemp -d /tmp/clade-lint3.XXXXXX)
CLEANUP_DIRS+=("$PROJ3")
printf 'def broken(:\n' > "$PROJ3/bad.py"
run_hook "$PROJ3" "$(fixture_json "$PROJ3/bad.py")"
assert_eq "0" "$HOOK_EC" "no orchestrator.json: exits 0 (hook stays opt-in)"

# ─── Summary ─────────────────────────────────────────────────────────
echo ""
if [[ $TESTS_FAILED -eq 0 ]]; then
  echo -e "  ${GREEN}ALL $TESTS_RUN TESTS PASSED${NC}"
else
  echo -e "  ${RED}$TESTS_FAILED FAILED${NC} / $TESTS_PASSED passed / $TESTS_RUN total"
fi
exit $TESTS_FAILED
