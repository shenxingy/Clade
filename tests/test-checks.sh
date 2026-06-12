#!/usr/bin/env bash
# test-checks.sh — Tests for the shared commit-path gate:
#   configs/scripts/checks.sh    (staged-secret scan, shellcheck, commit-msg)
#   configs/scripts/committer.sh (gate wiring, abort behavior)
#
# Uses throwaway git repos under /tmp; never touches the real $HOME and never
# pushes (every committer call passes --no-push).
#
# Usage:
#   bash tests/test-checks.sh        # Run all tests
#   bash tests/test-checks.sh -v     # Verbose mode

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMMITTER="$REPO_ROOT/configs/scripts/committer.sh"
CHECKS="$REPO_ROOT/configs/scripts/checks.sh"

# ─── Test framework (mirrors tests/test-loop.sh) ─────────────────────
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

assert_contains() {
  local haystack="$1" needle="$2" msg="$3"
  TESTS_RUN=$((TESTS_RUN + 1))
  if echo "$haystack" | grep -qF "$needle"; then
    pass "$msg"
  else
    fail "$msg" "output does not contain '$needle'"
    [[ "$VERBOSE" == "-v" ]] && echo "    output: $(echo "$haystack" | head -5)"
  fi
}

assert_not_contains() {
  local haystack="$1" needle="$2" msg="$3"
  TESTS_RUN=$((TESTS_RUN + 1))
  if echo "$haystack" | grep -qF "$needle"; then
    fail "$msg" "output unexpectedly contains '$needle'"
  else
    pass "$msg"
  fi
}

# ─── Helpers ─────────────────────────────────────────────────────────

CLEANUP_DIRS=()
cleanup() {
  local d
  for d in "${CLEANUP_DIRS[@]:-}"; do
    [[ -n "$d" && -d "$d" ]] && rm -rf "$d"
  done
}
trap cleanup EXIT

# Fresh throwaway repo with one initial commit (no remote — that is why every
# committer call below uses --no-push).
make_repo() {
  local d
  d="$(mktemp -d /tmp/clade-checks-test.XXXXXX)"
  CLEANUP_DIRS+=("$d")
  git -C "$d" init -q
  git -C "$d" config user.email "test@example.com"
  git -C "$d" config user.name "Test"
  git -C "$d" config commit.gpgsign false
  echo "init" > "$d/README.md"
  git -C "$d" add README.md
  git -C "$d" commit -qm "chore: init"
  echo "$d"
}

commit_count() { git -C "$1" rev-list --count HEAD; }

# Fake AWS access key id, built by concatenation so this test file itself
# never contains a contiguous scannable literal (the gate would flag it).
FAKE_AKIA="AKIA""IOSFODNN7EXAMPLE"

# ─── checks.sh commit-msg ────────────────────────────────────────────
echo "── checks.sh commit-msg ──"

bash "$CHECKS" commit-msg "feat: add thing" >/dev/null 2>&1
assert_eq 0 $? "commit-msg accepts conventional subject"

bash "$CHECKS" commit-msg "feat(scope): add thing" >/dev/null 2>&1
assert_eq 0 $? "commit-msg accepts scoped subject"

bash "$CHECKS" commit-msg "loop: iter 3 changes" >/dev/null 2>&1
assert_eq 1 $? "commit-msg rejects non-conventional type"

bash "$CHECKS" commit-msg "" >/dev/null 2>&1
assert_eq 1 $? "commit-msg rejects empty message"

bash "$CHECKS" commit-msg "fix: subject
body line explaining the mechanism" >/dev/null 2>&1
assert_eq 0 $? "commit-msg validates only the subject line of a multi-line message"

# ─── checks.sh staged secret scan ────────────────────────────────────
echo "── checks.sh staged (secret scan) ──"

D="$(make_repo)"
echo "aws_key = $FAKE_AKIA" > "$D/config.txt"
git -C "$D" add config.txt
( cd "$D" && bash "$CHECKS" staged ) >/dev/null 2>&1
assert_eq 1 $? "staged scan fails on a fake AWS key"

( cd "$D" && CLADE_ALLOW_SECRETS=1 bash "$CHECKS" staged ) >/dev/null 2>&1
assert_eq 0 $? "CLADE_ALLOW_SECRETS=1 overrides the staged scan"

D="$(make_repo)"
echo "plain content" > "$D/clean.txt"
git -C "$D" add clean.txt
( cd "$D" && bash "$CHECKS" staged ) >/dev/null 2>&1
assert_eq 0 $? "staged scan passes on clean content"

# Removing a previously-committed secret must NOT be blocked (only added
# lines are scanned — the gate should never fight secret cleanup).
D="$(make_repo)"
echo "aws_key = $FAKE_AKIA" > "$D/leak.txt"
git -C "$D" add leak.txt
git -C "$D" -c commit.gpgsign=false commit -qm "chore: simulate old leak"
echo "rotated" > "$D/leak.txt"
git -C "$D" add leak.txt
( cd "$D" && bash "$CHECKS" staged ) >/dev/null 2>&1
assert_eq 0 $? "removing a leaked secret is not blocked"

# Fallback ERE path: copy checks.sh somewhere with no redact.py sibling and
# point HOME away from the real ~/.claude — the inline grep pattern starts
# with '-----BEGIN', so this also guards the explicit `grep -e` against
# option-parsing regressions.
ISO="$(mktemp -d /tmp/clade-checks-iso.XXXXXX)"
CLEANUP_DIRS+=("$ISO")
cp "$CHECKS" "$ISO/checks.sh"
D="$(make_repo)"
echo "aws_key = $FAKE_AKIA" > "$D/config.txt"
git -C "$D" add config.txt
( cd "$D" && HOME="$ISO" bash "$ISO/checks.sh" staged ) >/dev/null 2>&1
assert_eq 1 $? "fallback ERE path (no redact.py) still detects the key"

# ─── checks.sh shellcheck ────────────────────────────────────────────
echo "── checks.sh shellcheck ──"

if command -v shellcheck &>/dev/null; then
  D="$(make_repo)"
  printf '#!/usr/bin/env bash\nlocal x=1\n' > "$D/bad.sh"
  bash "$CHECKS" shellcheck "$D/bad.sh" >/dev/null 2>&1
  assert_eq 1 $? "shellcheck subcommand fails on an error-severity script"

  printf '#!/usr/bin/env bash\necho ok\n' > "$D/good.sh"
  bash "$CHECKS" shellcheck "$D/good.sh" >/dev/null 2>&1
  assert_eq 0 $? "shellcheck subcommand passes a clean script"

  CLADE_SKIP_SHELLCHECK=1 bash "$CHECKS" shellcheck "$D/bad.sh" >/dev/null 2>&1
  assert_eq 0 $? "CLADE_SKIP_SHELLCHECK=1 skips the shellcheck gate"
else
  echo "  (shellcheck not installed — subcommand tests skipped; CI runs them)"
fi

# Resolve bash absolutely first — with PATH stripped, `env bash` can't find it
BASH_BIN="$(command -v bash)"
OUT="$(PATH="/nonexistent" "$BASH_BIN" "$CHECKS" shellcheck /dev/null 2>&1; echo "rc=$?")" || true
assert_contains "$OUT" "rc=0" "missing shellcheck binary degrades to a skip, not a failure"

# ─── committer.sh gate wiring ────────────────────────────────────────
echo "── committer.sh pre-commit gate ──"

D="$(make_repo)"
echo "aws_key = $FAKE_AKIA" > "$D/secret.txt"
OUT="$( cd "$D" && bash "$COMMITTER" "feat: add config" secret.txt --no-push 2>&1; echo "rc=$?" )"
assert_contains "$OUT" "rc=1" "committer aborts when a staged secret is detected"
assert_contains "$OUT" "commit aborted" "committer surfaces the secret-scan abort reason"
assert_eq 1 "$(commit_count "$D")" "no commit was created on secret abort"
assert_eq "" "$(git -C "$D" diff --cached --name-only)" "staging area is reset after abort"

OUT="$( cd "$D" && CLADE_ALLOW_SECRETS=1 bash "$COMMITTER" "feat: add config" secret.txt --no-push 2>&1; echo "rc=$?" )"
assert_contains "$OUT" "rc=0" "CLADE_ALLOW_SECRETS=1 lets the flagged commit through"
assert_eq 2 "$(commit_count "$D")" "override commit landed"

D="$(make_repo)"
echo "normal change" > "$D/file.txt"
( cd "$D" && bash "$COMMITTER" "feat: add file" file.txt --no-push ) >/dev/null 2>&1
assert_eq 0 $? "committer commits clean changes normally"
assert_eq 2 "$(commit_count "$D")" "clean commit landed"

( cd "$D" && bash "$COMMITTER" "not-a-type: nope" file.txt --no-push ) >/dev/null 2>&1
assert_eq 1 $? "committer still rejects non-conventional messages (via checks.sh)"

# ─── committer.sh attribution trailers (CLADE_WORKER_TASK_ID) ────────
echo "── committer.sh attribution trailers ──"

D="$(make_repo)"
echo "agent change" > "$D/agent.txt"
( cd "$D" && CLADE_WORKER_TASK_ID=42 bash "$COMMITTER" "feat: agent change" agent.txt --no-push ) >/dev/null 2>&1
BODY="$(git -C "$D" log -1 --format=%B)"
assert_contains "$BODY" "Co-Authored-By: Claude <noreply@anthropic.com>" "worker commit carries Co-Authored-By trailer"
assert_contains "$BODY" "X-Clade-Task: 42" "worker commit carries X-Clade-Task trailer"
TRAILER_VAL="$(git -C "$D" log -1 --format='%(trailers:key=X-Clade-Task,valueonly)' | tr -d '\n')"
assert_eq "42" "$TRAILER_VAL" "git parses X-Clade-Task as a real trailer (single -m block)"

echo "human change" > "$D/human.txt"
( cd "$D" && bash "$COMMITTER" "feat: human change" human.txt --no-push ) >/dev/null 2>&1
BODY="$(git -C "$D" log -1 --format=%B)"
assert_not_contains "$BODY" "Co-Authored-By" "interactive commit stays trailer-free"
assert_not_contains "$BODY" "X-Clade-Task" "interactive commit has no task trailer"

# ─── commit-archeology.sh agent segmentation ─────────────────────────
echo "── commit-archeology.sh agent segmentation ──"

ARCH="$REPO_ROOT/configs/scripts/commit-archeology.sh"
D="$(make_repo)"
for i in 1 2 3; do
  echo "a$i" > "$D/a$i.txt"
  ( cd "$D" && CLADE_WORKER_TASK_ID="$i" bash "$COMMITTER" "fix: agent fix $i" "a$i.txt" --no-push ) >/dev/null 2>&1
done
echo "h1" > "$D/h1.txt"
( cd "$D" && bash "$COMMITTER" "feat: human feature" h1.txt --no-push ) >/dev/null 2>&1

FAKE_HOME="$(mktemp -d /tmp/clade-arch-home.XXXXXX)"
CLEANUP_DIRS+=("$FAKE_HOME")
( cd "$D" && CLAUDE_DIR="$FAKE_HOME/.claude" CLAUDE_PROJECT_DIR="$D" COMMIT_ARCH_MIN=3 \
    bash "$ARCH" --scan ) >/dev/null 2>&1
LESSONS_FILE="$FAKE_HOME/.claude/commit-lessons/$(echo "$D" | sed 's|/|-|g').jsonl"
TESTS_RUN=$((TESTS_RUN + 1))
if [[ -s "$LESSONS_FILE" ]]; then
  pass "archeology --scan wrote a lessons file"
else
  fail "archeology --scan wrote a lessons file" "missing: $LESSONS_FILE"
fi
LESSONS="$(cat "$LESSONS_FILE" 2>/dev/null || true)"
assert_contains "$LESSONS" "agent-author-share" "segmentation row present (trailer-derived)"
assert_contains "$LESSONS" "agent fix-rate 100% (3/3) vs human 0% (0/2)" "fix-rate split segments agent vs human"

# ─── Summary ─────────────────────────────────────────────────────────
echo ""
if [[ $TESTS_FAILED -eq 0 ]]; then
  echo -e "  ${GREEN}ALL $TESTS_RUN TESTS PASSED${NC}"
else
  echo -e "  ${RED}$TESTS_FAILED FAILED${NC} / $TESTS_PASSED passed / $TESTS_RUN total"
fi
exit $TESTS_FAILED
