#!/usr/bin/env bash
# test-checks.sh — Tests for the shared commit-path gate:
#   configs/scripts/checks.sh    (staged-secret scan, shellcheck, commit-msg)
#   configs/scripts/committer.sh (gate wiring, abort behavior, push target)
#
# Uses throwaway git repos under /tmp and never touches the real $HOME. Every
# committer call passes --no-push except the push-target section, which pushes
# only to throwaway bare repositories under /tmp.
#
# Usage:
#   bash tests/test-checks.sh        # Run all tests
#   bash tests/test-checks.sh -v     # Verbose mode

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMMITTER="$REPO_ROOT/configs/scripts/committer.sh"
CHECKS="$REPO_ROOT/configs/scripts/checks.sh"
GIT_IDENTITY="$REPO_ROOT/configs/scripts/git_identity.py"

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

# Here-strings, not `echo | grep -q`: under pipefail, grep -q exits at the
# first match and can SIGPIPE the echo of a large haystack — the pipeline
# then reports failure even though the needle WAS found.
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

assert_file_contains() {
  local path="$1" needle="$2" msg="$3"
  TESTS_RUN=$((TESTS_RUN + 1))
  if grep -qF "$needle" "$path" 2>/dev/null; then
    pass "$msg"
  else
    fail "$msg" "'$needle' not found in $path"
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

# All committer tests run behind the same explicit human VCS identity anchor.
# The path override keeps the suite hermetic and proves no real user identity
# is consulted or modified.
IDENTITY_HOME="$(mktemp -d /tmp/clade-identity-test.XXXXXX)"
CLEANUP_DIRS+=("$IDENTITY_HOME")
export CLADE_GIT_IDENTITY_FILE="$IDENTITY_HOME/git-identity.json"
python3 "$GIT_IDENTITY" pin --name Test --email test@example.com >/dev/null

# Fresh throwaway repo with one initial commit and no remote; the committer
# calls on it pass --no-push. The push-target section builds its own pairs.
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
# Underscore-prefixed provider key (the Scam.ai shape). Same concatenation
# trick, same reason. `sk_` sits inside the ordinary word `task_`, so the
# pattern that catches this one has to carry a leading boundary — the two
# assertions below pin both halves of that.
FAKE_SK_UNDERSCORE="sk_""d69f0a1b2c3d4e5f60718293a4b5c6d7"
FAKE_TASK_ID="task_""abcdefghijklmnopqrstuvwxyz012345"

# ─── Git identity trust boundary ────────────────────────────────────
echo "── git_identity.py trust boundary ──"

D="$(make_repo)"
python3 "$GIT_IDENTITY" check --repo "$D" >/dev/null 2>&1
assert_eq 0 $? "pinned identity accepts matching Git configuration"

git -C "$D" config user.email "dukeamlmachine@gmail.com"
OUT="$(python3 "$GIT_IDENTITY" check --repo "$D" 2>&1; echo "rc=$?")"
assert_contains "$OUT" "rc=1" "identity check rejects a different configured email"
assert_contains "$OUT" "Provider login emails must never be used as VCS identity" \
  "identity rejection explains the provider/VCS boundary"

git -C "$D" config user.email "test@example.com"
OUT="$(GIT_AUTHOR_EMAIL="dukeamlmachine@gmail.com" python3 "$GIT_IDENTITY" check --repo "$D" 2>&1; echo "rc=$?")"
assert_contains "$OUT" "rc=1" "identity check rejects a contaminated GIT_AUTHOR_EMAIL"
assert_contains "$OUT" "effective author" "environment contamination identifies the effective author source"

MISSING_IDENTITY="$IDENTITY_HOME/missing.json"
OUT="$(cd "$D" && CLADE_GIT_IDENTITY_FILE="$MISSING_IDENTITY" \
  bash "$COMMITTER" "feat: should not commit" README.md --no-push 2>&1; echo "rc=$?")"
assert_contains "$OUT" "rc=1" "committer fails closed when no identity is pinned"
assert_contains "$OUT" "no pinned Git identity" "missing identity error gives the pinning reason"
assert_eq 1 "$(commit_count "$D")" "missing identity creates no commit"

git -C "$D" config user.email "dukeamlmachine@gmail.com"
echo "wrong config" > "$D/wrong.txt"
OUT="$(cd "$D" && bash "$COMMITTER" "feat: reject wrong identity" wrong.txt --no-push 2>&1; echo "rc=$?")"
assert_contains "$OUT" "rc=1" "committer blocks a configured identity mismatch before commit"
assert_eq 1 "$(commit_count "$D")" "configured identity mismatch creates no commit"
assert_eq "" "$(git -C "$D" diff --cached --name-only)" "identity rejection leaves the index untouched"

git -C "$D" config user.email "test@example.com"
echo "correct config" > "$D/correct.txt"
(cd "$D" && bash "$COMMITTER" "feat: preserve pinned identity" correct.txt --no-push) >/dev/null 2>&1
assert_eq 0 $? "committer accepts the pinned identity"
assert_eq "Test <test@example.com>|Test <test@example.com>" \
  "$(git -C "$D" log -1 --format='%an <%ae>|%cn <%ce>')" \
  "committer writes the pinned author and committer to HEAD"
python3 "$GIT_IDENTITY" verify-head --repo "$D" >/dev/null 2>&1
assert_eq 0 $? "post-commit verification accepts exact pinned attribution"

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

# The underscore-key shape, through BOTH paths. redact.py grew this pattern
# and checks.sh's inline ERE claims to mirror it — a claim that is only true
# while something checks it.
D="$(make_repo)"
echo "api_key = $FAKE_SK_UNDERSCORE" > "$D/config.txt"
git -C "$D" add config.txt
( cd "$D" && bash "$CHECKS" staged ) >/dev/null 2>&1
assert_eq 1 $? "staged scan fails on an sk_ underscore key"

D="$(make_repo)"
echo "api_key = $FAKE_SK_UNDERSCORE" > "$D/config.txt"
git -C "$D" add config.txt
( cd "$D" && HOME="$ISO" bash "$ISO/checks.sh" staged ) >/dev/null 2>&1
assert_eq 1 $? "fallback ERE path also detects the sk_ underscore key"

# ...and must not fire on an ordinary identifier that merely contains `sk_`.
D="$(make_repo)"
echo "job = $FAKE_TASK_ID" > "$D/config.txt"
git -C "$D" add config.txt
( cd "$D" && HOME="$ISO" bash "$ISO/checks.sh" staged ) >/dev/null 2>&1
assert_eq 0 $? "fallback ERE does not fire on task_<32 alnum>"

# ─── The fallback pattern has two homes; pin them equal ──────────────
# checks.sh's SECRET_ERE and correction-detector.sh's CD_SECRET_ERE are the
# same detector, used when python3 or redact.py is unavailable. The 2026-09-02
# review found them diverged in BOTH directions — one had the leading boundary
# that keeps `task_<32>` out and was missing four shapes; the other had the
# shapes and false-positived on ordinary words. A fallback that disagrees with
# the real detector is one nobody can reason about.
CHECKS_ERE=$(grep '^SECRET_ERE=' "$CHECKS" | cut -d= -f2-)
HOOK_ERE=$(grep '^CD_SECRET_ERE=' "$REPO_ROOT/configs/hooks/correction-detector.sh" | cut -d= -f2-)
assert_eq "$CHECKS_ERE" "$HOOK_ERE" "checks.sh and correction-detector.sh share one secret pattern"

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

# ─── committer.sh traceability trailers (CLADE_WORKER_TASK_ID) ───────
echo "── committer.sh traceability trailers ──"

D="$(make_repo)"
echo "agent change" > "$D/agent.txt"
( cd "$D" && CLADE_WORKER_TASK_ID=42 bash "$COMMITTER" "feat: agent change" agent.txt --no-push ) >/dev/null 2>&1
BODY="$(git -C "$D" log -1 --format=%B)"
assert_not_contains "$BODY" "Co-Authored-By" "worker commit does not claim Claude as a co-author"
assert_contains "$BODY" "X-Clade-Task: 42" "worker commit carries X-Clade-Task trailer"
TRAILER_VAL="$(git -C "$D" log -1 --format='%(trailers:key=X-Clade-Task,valueonly)' | tr -d '\n')"
assert_eq "42" "$TRAILER_VAL" "git parses X-Clade-Task as a real trailer (single -m block)"
# no CLADE_WORKER_MODEL set → Agent-Signature falls back to the unknown-model placeholder
assert_contains "$BODY" "Agent-Signature: unknown-model" "worker commit without a model falls back to unknown-model"

echo "human change" > "$D/human.txt"
( cd "$D" && bash "$COMMITTER" "feat: human change" human.txt --no-push ) >/dev/null 2>&1
BODY="$(git -C "$D" log -1 --format=%B)"
assert_not_contains "$BODY" "Co-Authored-By" "interactive commit stays trailer-free"
assert_not_contains "$BODY" "X-Clade-Task" "interactive commit has no task trailer"
assert_not_contains "$BODY" "Agent-Signature" "interactive commit has no model-provenance trailer"

# ─── committer.sh Agent-Signature trailer (CLADE_WORKER_MODEL) ───────
echo "── committer.sh Agent-Signature trailer ──"

echo "agent model change" > "$D/agent-model.txt"
( cd "$D" && CLADE_WORKER_TASK_ID=7 CLADE_WORKER_MODEL="claude-opus-4-6" \
    bash "$COMMITTER" "feat: agent model change" agent-model.txt --no-push ) >/dev/null 2>&1
BODY="$(git -C "$D" log -1 --format=%B)"
assert_contains "$BODY" "Agent-Signature: claude-opus-4-6" "worker commit records the resolved model as Agent-Signature"
SIG_VAL="$(git -C "$D" log -1 --format='%(trailers:key=Agent-Signature,valueonly)' | tr -d '\n')"
assert_eq "claude-opus-4-6" "$SIG_VAL" "git parses Agent-Signature as a real trailer (single -m block)"

# ─── committer.sh push target ────────────────────────────────────────
echo "── committer.sh pushes only to a same-named remote branch ──"

# committer ended with a bare `git push`, so the push went wherever the branch
# tracked. `git worktree add -b X <path> origin/main` makes origin/main the
# upstream of X: push.default=upstream then put a feature commit on main, and
# git's default (simple) refused it and committer exited non-zero after a
# successful commit. These cases run WITHOUT --no-push against a local bare
# remote, and with the global/system git config switched off so a caller's own
# push.default, remote.pushDefault or branch.autoSetupMerge cannot decide them.
PUSH_ROOT="$(mktemp -d /tmp/clade-push-test.XXXXXX)"
CLEANUP_DIRS+=("$PUSH_ROOT")
: > "$PUSH_ROOT/empty-gitconfig"
SAVED_GIT_CONFIG_GLOBAL="${GIT_CONFIG_GLOBAL-__unset__}"
SAVED_GIT_CONFIG_NOSYSTEM="${GIT_CONFIG_NOSYSTEM-__unset__}"
export GIT_CONFIG_GLOBAL="$PUSH_ROOT/empty-gitconfig" GIT_CONFIG_NOSYSTEM=1

# $PUSH_ROOT/<name> is a work repo whose main is published to the bare
# $PUSH_ROOT/<name>.git as origin. Called directly, never in $(...), so the
# directories stay under the one PUSH_ROOT the EXIT trap removes.
new_push_pair() {
  local w="$PUSH_ROOT/$1" r="$PUSH_ROOT/$1.git"
  git init -q --bare "$r" 2>/dev/null
  git init -q "$w" 2>/dev/null
  git -C "$w" config user.email "test@example.com"
  git -C "$w" config user.name "Test"
  git -C "$w" config commit.gpgsign false
  echo "init" > "$w/README.md"
  git -C "$w" add README.md
  git -C "$w" commit -qm "chore: init"
  git -C "$w" branch -M main
  git -C "$w" remote add origin "$r"
  git -C "$w" push -q origin main:refs/heads/main 2>/dev/null
  git -C "$w" fetch -q origin
}
remote_sha() { git -C "$1" rev-parse -q --verify "refs/heads/$2" 2>/dev/null || echo none; }

# 1. A worktree branch tracking origin/main is NOT pushed to main.
new_push_pair wt
W="$PUSH_ROOT/wt-worktree"
git -C "$PUSH_ROOT/wt" worktree add -q -b feat/wt "$W" origin/main 2>/dev/null
git -C "$W" branch -q --set-upstream-to=origin/main
git -C "$W" config push.default upstream
MAIN_BEFORE="$(remote_sha "$PUSH_ROOT/wt.git" main)"
echo "change" > "$W/wt.txt"
OUT="$(cd "$W" && bash "$COMMITTER" "feat: worktree change" wt.txt 2>&1; echo "rc=$?")"
assert_contains "$OUT" "rc=0" "branch tracking origin/main: committer exits 0 (the commit succeeded)"
assert_eq "feat: worktree change" "$(git -C "$W" log -1 --format=%s)" "branch tracking origin/main: the commit landed locally"
assert_eq "$MAIN_BEFORE" "$(remote_sha "$PUSH_ROOT/wt.git" main)" \
  "branch tracking origin/main is never pushed to main (push.default=upstream)"
assert_eq "none" "$(remote_sha "$PUSH_ROOT/wt.git" feat/wt)" \
  "branch tracking origin/main is not published under its own name unasked"
assert_contains "$OUT" "Not pushed: 'feat/wt' tracks 'origin/main'" "the skip names the mismatched upstream"
assert_contains "$OUT" "git push -u origin HEAD:refs/heads/feat/wt" "the skip prints the explicit push command"

git -C "$W" config push.default simple
echo "again" > "$W/wt.txt"
OUT="$(cd "$W" && bash "$COMMITTER" "fix: worktree follow-up" wt.txt 2>&1; echo "rc=$?")"
assert_contains "$OUT" "rc=0" "branch tracking origin/main exits 0 under push.default=simple too"
assert_eq "$MAIN_BEFORE" "$(remote_sha "$PUSH_ROOT/wt.git" main)" "push.default=simple: main is still untouched"

# 2. No upstream → pushed to the same-named remote branch, upstream set.
new_push_pair fresh
F="$PUSH_ROOT/fresh"
git -C "$F" checkout -q -b feat/new
git -C "$F" branch -q --unset-upstream 2>/dev/null || true
MAIN_BEFORE="$(remote_sha "$PUSH_ROOT/fresh.git" main)"
echo "new" > "$F/new.txt"
OUT="$(cd "$F" && bash "$COMMITTER" "feat: new branch" new.txt 2>&1; echo "rc=$?")"
assert_contains "$OUT" "rc=0" "no upstream: committer exits 0"
assert_eq "$(git -C "$F" rev-parse HEAD)" "$(remote_sha "$PUSH_ROOT/fresh.git" feat/new)" \
  "no upstream: pushed to the same-named remote branch"
assert_eq "origin|refs/heads/feat/new" \
  "$(git -C "$F" config --get branch.feat/new.remote)|$(git -C "$F" config --get branch.feat/new.merge)" \
  "no upstream: the push sets origin/feat/new as the upstream"
assert_eq "$MAIN_BEFORE" "$(remote_sha "$PUSH_ROOT/fresh.git" main)" "no upstream: main is untouched"

# 3. Same-named upstream → pushed to it (the branch case 2 just published).
echo "more" > "$F/new.txt"
OUT="$(cd "$F" && bash "$COMMITTER" "fix: follow-up" new.txt 2>&1; echo "rc=$?")"
assert_contains "$OUT" "rc=0" "same-named upstream: committer exits 0"
assert_eq "$(git -C "$F" rev-parse HEAD)" "$(remote_sha "$PUSH_ROOT/fresh.git" feat/new)" \
  "same-named upstream: the new commit is pushed to it"

# ... and ONLY to it: push.default=matching made a bare push publish every
# same-named branch, including a local main that is ahead of origin/main.
new_push_pair match
M="$PUSH_ROOT/match"
MAIN_BEFORE="$(remote_sha "$PUSH_ROOT/match.git" main)"
git -C "$M" commit -q --allow-empty -m "chore: local-only main commit"
git -C "$M" checkout -q -b feat/same
git -C "$M" push -q -u origin HEAD:refs/heads/feat/same 2>/dev/null
git -C "$M" config push.default matching
echo "same" > "$M/same.txt"
OUT="$(cd "$M" && bash "$COMMITTER" "feat: same-name change" same.txt 2>&1; echo "rc=$?")"
assert_contains "$OUT" "rc=0" "same-named upstream under push.default=matching: exits 0"
assert_eq "$(git -C "$M" rev-parse HEAD)" "$(remote_sha "$PUSH_ROOT/match.git" feat/same)" \
  "push.default=matching: the current branch is pushed"
assert_eq "$MAIN_BEFORE" "$(remote_sha "$PUSH_ROOT/match.git" main)" \
  "push.default=matching: a local main ahead of origin is NOT pushed along with it"

# 4. --no-push → nothing pushed, no upstream recorded.
new_push_pair quiet
Q="$PUSH_ROOT/quiet"
git -C "$Q" checkout -q -b feat/quiet
git -C "$Q" branch -q --unset-upstream 2>/dev/null || true
echo "quiet" > "$Q/quiet.txt"
OUT="$(cd "$Q" && bash "$COMMITTER" "feat: quiet change" quiet.txt --no-push 2>&1; echo "rc=$?")"
assert_contains "$OUT" "rc=0" "--no-push: committer exits 0"
assert_eq "none" "$(remote_sha "$PUSH_ROOT/quiet.git" feat/quiet)" "--no-push: nothing is pushed"
assert_eq "" "$(git -C "$Q" config --get branch.feat/quiet.merge)" "--no-push: no upstream is recorded"

# 5. Detached HEAD → skipped with a message, exit 0.
new_push_pair detached
X="$PUSH_ROOT/detached"
git -C "$X" checkout -q --detach
REFS_BEFORE="$(git -C "$PUSH_ROOT/detached.git" for-each-ref --format='%(refname) %(objectname)')"
echo "detached" > "$X/detached.txt"
OUT="$(cd "$X" && bash "$COMMITTER" "feat: detached change" detached.txt 2>&1; echo "rc=$?")"
assert_contains "$OUT" "rc=0" "detached HEAD: committer exits 0 (the commit succeeded)"
assert_contains "$OUT" "Not pushed: detached HEAD" "detached HEAD: the skip says why"
assert_eq "$REFS_BEFORE" "$(git -C "$PUSH_ROOT/detached.git" for-each-ref --format='%(refname) %(objectname)')" \
  "detached HEAD: the remote is untouched"
assert_eq "feat: detached change" "$(git -C "$X" log -1 --format=%s)" "detached HEAD: the commit landed"

# 6. No upstream and no origin remote → skipped with a message, exit 0.
new_push_pair lonely
L="$PUSH_ROOT/lonely"
git -C "$L" remote remove origin
echo "lonely" > "$L/lonely.txt"
OUT="$(cd "$L" && bash "$COMMITTER" "feat: no remote" lonely.txt 2>&1; echo "rc=$?")"
assert_contains "$OUT" "rc=0" "no remote at all: committer exits 0"
assert_contains "$OUT" "has no 'origin' remote" "no remote at all: the skip says why"

# 7. Tracking a LOCAL branch (remote ".") is a different-name upstream too:
#    push.default=upstream used to push into this repository's own main.
new_push_pair local
LC="$PUSH_ROOT/local"
git -C "$LC" checkout -q -b feat/local
git -C "$LC" config branch.feat/local.remote .
git -C "$LC" config branch.feat/local.merge refs/heads/main
git -C "$LC" config push.default upstream
LOCAL_MAIN_BEFORE="$(git -C "$LC" rev-parse main)"
echo "local" > "$LC/local.txt"
OUT="$(cd "$LC" && bash "$COMMITTER" "feat: local tracking" local.txt 2>&1; echo "rc=$?")"
assert_contains "$OUT" "rc=0" "branch tracking a local branch: committer exits 0"
assert_eq "$LOCAL_MAIN_BEFORE" "$(git -C "$LC" rev-parse main)" "branch tracking local main never moves main"
assert_contains "$OUT" "git push -u origin HEAD:refs/heads/feat/local" \
  "local-tracking skip suggests origin, never the '.' pseudo-remote"

# 8. A push git rejects exits 3 (commit kept) and is never forced.
new_push_pair race
RC_DIR="$PUSH_ROOT/race"
git -C "$RC_DIR" checkout -q -b feat/race
git -C "$RC_DIR" push -q -u origin HEAD:refs/heads/feat/race 2>/dev/null
OTHER="$(git -C "$RC_DIR" commit-tree -p HEAD -m "chore: another writer" "HEAD^{tree}")"
git -C "$RC_DIR" push -q origin "$OTHER:refs/heads/feat/race" 2>/dev/null
echo "mine" > "$RC_DIR/race.txt"
OUT="$(cd "$RC_DIR" && bash "$COMMITTER" "feat: racing change" race.txt 2>&1; echo "rc=$?")"
assert_contains "$OUT" "rc=3" "rejected push: exit 3, distinct from the 1 of a pre-commit refusal"
assert_contains "$OUT" "Push FAILED" "rejected push: says the push, not the commit, failed"
assert_eq "feat: racing change" "$(git -C "$RC_DIR" log -1 --format=%s)" "rejected push: the commit is kept"
assert_eq "$OTHER" "$(remote_sha "$PUSH_ROOT/race.git" feat/race)" "rejected push: the remote branch is never forced"

# 9. The push remote is the one `git push` itself would pick (a fork workflow):
#    branch.<b>.pushRemote over remote.pushDefault over origin.
new_push_pair tri
T="$PUSH_ROOT/tri"
git init -q --bare "$PUSH_ROOT/tri-fork.git" 2>/dev/null
git -C "$T" remote add fork "$PUSH_ROOT/tri-fork.git"
git -C "$T" config remote.pushDefault fork
git -C "$T" checkout -q -b feat/tri
git -C "$T" branch -q --unset-upstream 2>/dev/null || true
echo "tri" > "$T/tri.txt"
OUT="$(cd "$T" && bash "$COMMITTER" "feat: fork push" tri.txt 2>&1; echo "rc=$?")"
assert_eq "$(git -C "$T" rev-parse HEAD)|none" \
  "$(remote_sha "$PUSH_ROOT/tri-fork.git" feat/tri)|$(remote_sha "$PUSH_ROOT/tri.git" feat/tri)" \
  "remote.pushDefault=fork: pushed to the fork, not origin"
git -C "$T" config remote.pushDefault origin
git -C "$T" checkout -q -b feat/tri2 main
git -C "$T" branch -q --unset-upstream 2>/dev/null || true
git -C "$T" config branch.feat/tri2.pushRemote fork
echo "tri2" > "$T/tri2.txt"
OUT="$(cd "$T" && bash "$COMMITTER" "feat: fork push two" tri2.txt 2>&1; echo "rc=$?")"
assert_eq "$(git -C "$T" rev-parse HEAD)|none" \
  "$(remote_sha "$PUSH_ROOT/tri-fork.git" feat/tri2)|$(remote_sha "$PUSH_ROOT/tri.git" feat/tri2)" \
  "branch.<b>.pushRemote=fork wins over remote.pushDefault=origin"

# 10. ... and branch.<b>.remote below both: a branch tracking up/<same-name>
#     with no pushRemote/pushDefault goes to `up`, never to origin.
new_push_pair route
RT="$PUSH_ROOT/route"
git init -q --bare "$PUSH_ROOT/route-up.git" 2>/dev/null
git -C "$RT" remote add up "$PUSH_ROOT/route-up.git"
git -C "$RT" checkout -q -b feat/up
git -C "$RT" push -q -u up HEAD:refs/heads/feat/up 2>/dev/null
echo "up" > "$RT/up.txt"
OUT="$(cd "$RT" && bash "$COMMITTER" "feat: tracks up" up.txt 2>&1; echo "rc=$?")"
assert_eq "$(git -C "$RT" rev-parse HEAD)|none" \
  "$(remote_sha "$PUSH_ROOT/route-up.git" feat/up)|$(remote_sha "$PUSH_ROOT/route.git" feat/up)" \
  "branch.<b>.remote=up (same-name upstream): pushed to up, not origin"
#     remote.pushDefault=fork outranks branch.<b>.remote=origin.
git init -q --bare "$PUSH_ROOT/route-fork.git" 2>/dev/null
git -C "$RT" remote add fork "$PUSH_ROOT/route-fork.git"
git -C "$RT" checkout -q -b feat/pd main
git -C "$RT" push -q -u origin HEAD:refs/heads/feat/pd 2>/dev/null
ORIGIN_PD_BEFORE="$(remote_sha "$PUSH_ROOT/route.git" feat/pd)"
git -C "$RT" config remote.pushDefault fork
echo "pd" > "$RT/pd.txt"
OUT="$(cd "$RT" && bash "$COMMITTER" "feat: pushDefault over remote" pd.txt 2>&1; echo "rc=$?")"
assert_eq "$(git -C "$RT" rev-parse HEAD)|$ORIGIN_PD_BEFORE" \
  "$(remote_sha "$PUSH_ROOT/route-fork.git" feat/pd)|$(remote_sha "$PUSH_ROOT/route.git" feat/pd)" \
  "remote.pushDefault=fork wins over branch.<b>.remote=origin"

# 11. A tag (or any ref) named like the branch must not confuse the branch
#     name: `symbolic-ref --short` answers `heads/<name>` then, which missed the
#     branch's config, pushed to refs/heads/heads/<name> and rewrote its upstream.
new_push_pair tagged
TG="$PUSH_ROOT/tagged"
git -C "$TG" checkout -q -b rel1 --track origin/main
git -C "$TG" tag rel1
git -C "$TG" config push.default upstream
MAIN_BEFORE="$(remote_sha "$PUSH_ROOT/tagged.git" main)"
echo "rel1" > "$TG/rel1.txt"
OUT="$(cd "$TG" && bash "$COMMITTER" "feat: tagged branch tracking main" rel1.txt 2>&1; echo "rc=$?")"
assert_contains "$OUT" "rc=0" "tag named like a branch tracking origin/main: exits 0"
assert_eq "$MAIN_BEFORE|none|none" \
  "$(remote_sha "$PUSH_ROOT/tagged.git" main)|$(remote_sha "$PUSH_ROOT/tagged.git" rel1)|$(remote_sha "$PUSH_ROOT/tagged.git" heads/rel1)" \
  "tag named like a branch tracking origin/main: nothing is pushed anywhere"
assert_eq "refs/heads/main" "$(git -C "$TG" config --get branch.rel1.merge)" \
  "tag named like a branch tracking origin/main: its upstream config is kept"
git -C "$TG" checkout -q -b rel2 main
git -C "$TG" push -q -u origin HEAD:refs/heads/rel2 2>/dev/null
git -C "$TG" tag rel2
echo "rel2" > "$TG/rel2.txt"
OUT="$(cd "$TG" && bash "$COMMITTER" "feat: tagged same-name branch" rel2.txt 2>&1; echo "rc=$?")"
assert_eq "$(git -C "$TG" rev-parse HEAD)|none|refs/heads/rel2" \
  "$(remote_sha "$PUSH_ROOT/tagged.git" rel2)|$(remote_sha "$PUSH_ROOT/tagged.git" heads/rel2)|$(git -C "$TG" config --get branch.rel2.merge)" \
  "tag named like a same-name-tracking branch: pushed to refs/heads/<branch>, upstream kept"

# 12. An autonomous worker never pushes, in the exact shape run-tasks-parallel.sh
#     builds: `git branch batch/task-N-TS main` + `git worktree add`, so the
#     branch has no upstream and the -u path would publish it to origin.
new_push_pair worker
WK="$PUSH_ROOT/worker-wt"
git -C "$PUSH_ROOT/worker" branch batch/task-0-20261023 main
git -C "$PUSH_ROOT/worker" worktree add -q "$WK" batch/task-0-20261023 2>/dev/null
REFS_BEFORE="$(git -C "$PUSH_ROOT/worker.git" for-each-ref --format='%(refname) %(objectname)')"
echo "worker" > "$WK/worker.txt"
OUT="$(cd "$WK" && CLADE_WORKER_TASK_ID=batch-20261023-0 bash "$COMMITTER" "feat: worker change" worker.txt 2>&1; echo "rc=$?")"
assert_contains "$OUT" "rc=0" "worker commit (CLADE_WORKER_TASK_ID): committer exits 0"
assert_contains "$OUT" "Not pushed: autonomous worker commit" "worker commit: the skip says why"
assert_eq "feat: worker change" "$(git -C "$WK" log -1 --format=%s)" "worker commit: the commit landed"
assert_eq "$REFS_BEFORE" "$(git -C "$PUSH_ROOT/worker.git" for-each-ref --format='%(refname) %(objectname)')" \
  "worker commit: the task branch is not published"
assert_eq "" "$(git -C "$WK" config --get branch.batch/task-0-20261023.merge)" "worker commit: no upstream is recorded"

# 13. HEAD symbolically pointing at a ref outside refs/heads/ (here a
#     remote-tracking ref) is not a branch: skipped, never pushed as
#     refs/heads/refs/remotes/... .
new_push_pair oddhead
OH="$PUSH_ROOT/oddhead"
git -C "$OH" update-ref refs/remotes/origin/odd HEAD
git -C "$OH" symbolic-ref HEAD refs/remotes/origin/odd
REFS_BEFORE="$(git -C "$PUSH_ROOT/oddhead.git" for-each-ref --format='%(refname) %(objectname)')"
echo "odd" > "$OH/odd.txt"
OUT="$(cd "$OH" && bash "$COMMITTER" "feat: odd head" odd.txt 2>&1; echo "rc=$?")"
assert_contains "$OUT" "rc=0" "HEAD on a non-branch ref: committer exits 0"
assert_contains "$OUT" "which is not a local branch" "HEAD on a non-branch ref: the skip says why"
assert_eq "$REFS_BEFORE" "$(git -C "$PUSH_ROOT/oddhead.git" for-each-ref --format='%(refname) %(objectname)')" \
  "HEAD on a non-branch ref: the remote is untouched"

if [[ "$SAVED_GIT_CONFIG_GLOBAL" == "__unset__" ]]; then unset GIT_CONFIG_GLOBAL; else export GIT_CONFIG_GLOBAL="$SAVED_GIT_CONFIG_GLOBAL"; fi
if [[ "$SAVED_GIT_CONFIG_NOSYSTEM" == "__unset__" ]]; then unset GIT_CONFIG_NOSYSTEM; else export GIT_CONFIG_NOSYSTEM="$SAVED_GIT_CONFIG_NOSYSTEM"; fi

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

# ─── commit-body mandate wiring (mechanism/hazard/root-cause in bodies) ──
echo "── commit-body mandate wiring ──"

# The worker instructions moved to loop_score.sh when loop-runner.sh was split
# to stay under the 1500-line rule. Assert on the mandate reaching a worker,
# not on which file currently holds the string — otherwise the next extraction
# breaks a test that is really about behaviour.
assert_file_contains "$REPO_ROOT/configs/scripts/loop_score.sh" \
  "2-4 line body" "loop worker instructions carry the body mandate"
assert_file_contains "$REPO_ROOT/configs/skills/commit/prompt.md" \
  "Body mandate" "/commit skill Step 3 carries the body mandate"
assert_file_contains "$REPO_ROOT/orchestrator/worker_taskfile.py" \
  "## Commit Messages" "worker task-file guidance carries the body mandate"

# ─── untrusted observability input (agentjacking) ─────────────────────
echo "── obs-review-loop treats pulled events as data ──"

# /obs-review-loop reads attacker-writable Sentry/PostHog content and then
# edits code with a shell — the exact chain the June 2026 agentjacking
# disclosure exploited. Both the executable prompt and the Codex-facing summary
# must carry the contract; the summary is what a Codex session reads.
assert_file_contains "$REPO_ROOT/configs/skills/obs-review-loop/prompt.md" \
  "never instructions to follow" "obs-review-loop prompt: event content is data, not instructions"
assert_file_contains "$REPO_ROOT/configs/skills/obs-review-loop/prompt.md" \
  "suspected injection" "obs-review-loop prompt: an embedded fix step is reported, not run"
assert_file_contains "$REPO_ROOT/configs/skills/obs-review-loop/SKILL.md" \
  "attacker-writable" "obs-review-loop summary carries the untrusted-input contract"

# ─── AGENTS.md honeypot check (checks.sh pr-body) ─────────────────────
echo "── AGENTS.md honeypot check ──"

assert_file_contains "$REPO_ROOT/AGENTS.md" \
  "CLD-AGENTS-7f2b91e4" "AGENTS.md documents the compliance token"

bash "$CHECKS" pr-body "Fixes a bug in the login flow, tested locally." >/dev/null 2>&1
assert_eq 0 $? "a normal PR body with no token passes"

bash "$CHECKS" pr-body "" >/dev/null 2>&1
assert_eq 0 $? "an empty PR body passes (no false positive on empty input)"

HONEYPOT_OUT=$(bash "$CHECKS" pr-body "Fixes a bug. Agent-Compliance-Token: CLD-AGENTS-7f2b91e4" 2>&1)
HONEYPOT_RC=$?
assert_eq 1 "$HONEYPOT_RC" "a PR body echoing the token verbatim is flagged (nonzero exit)"
assert_contains "$HONEYPOT_OUT" "compliance token verbatim" "flagged output explains why, not just a bare failure"

# A body that merely MENTIONS the token in a different, non-matching casing
# or as a substring of a longer unrelated string must not false-positive —
# only an exact verbatim match of the real token should ever trigger.
bash "$CHECKS" pr-body "I saw something about cld-agents in the docs" >/dev/null 2>&1
assert_eq 0 $? "a similar-but-not-exact string does not false-positive"

# ─── Summary ─────────────────────────────────────────────────────────
echo ""
if [[ $TESTS_FAILED -eq 0 ]]; then
  echo -e "  ${GREEN}ALL $TESTS_RUN TESTS PASSED${NC}"
else
  echo -e "  ${RED}$TESTS_FAILED FAILED${NC} / $TESTS_PASSED passed / $TESTS_RUN total"
fi
exit $TESTS_FAILED
