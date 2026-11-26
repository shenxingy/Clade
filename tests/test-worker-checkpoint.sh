#!/usr/bin/env bash
# test-worker-checkpoint.sh — Tests for configs/hooks/worker-checkpoint.sh
#   (PostToolUse Edit|Write and Bash, async: one shadow-repository commit per
#    agent write, armed only by CLADE_WORKER_SHADOW_DIR)
#
# Split out of tests/test-hooks.sh on 2026-11-26, when the ignore-rule cases
# below would have taken that file past the 1500-line rule. The first two
# sections moved verbatim; the hook path became overridable so
# orchestrator/tests/test_hook_guards_can_fire.py can run this suite against a
# mutated copy of the hook and require it to go red.
#
# Every repository is a throwaway under /tmp, and HOME, XDG_CONFIG_HOME and the
# system git config are redirected or off, so no ambient ignore rule decides a
# case. No API calls.
#
# Usage:
#   bash tests/test-worker-checkpoint.sh        # Run all tests
#   WORKER_CHECKPOINT_HOOK=/path/copy.sh bash tests/test-worker-checkpoint.sh
#   WORKER_CHECKPOINT_FAIL_FAST=1 …             # stop at the first red case

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CK_HOOK="${WORKER_CHECKPOINT_HOOK:-$REPO_ROOT/configs/hooks/worker-checkpoint.sh}"
FAIL_FAST="${WORKER_CHECKPOINT_FAIL_FAST:-}"

# ─── Test framework (mirrors tests/test-hooks.sh) ────────────────────
TESTS_RUN=0; TESTS_PASSED=0; TESTS_FAILED=0
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'

pass() { TESTS_RUN=$((TESTS_RUN + 1)); TESTS_PASSED=$((TESTS_PASSED + 1)); echo -e "  ${GREEN}✓${NC} $1"; }
fail() {
  TESTS_RUN=$((TESTS_RUN + 1)); TESTS_FAILED=$((TESTS_FAILED + 1))
  echo -e "  ${RED}✗${NC} $1"
  [[ -n "${2:-}" ]] && echo -e "    ${RED}→ $2${NC}"
  if [[ -n "$FAIL_FAST" ]]; then exit 1; fi
  return 0
}
section() { echo ""; echo -e "${YELLOW}━━━ $1 ━━━${NC}"; }

assert_eq() {
  local got="$1" want="$2" msg="$3"
  if [[ "$got" == "$want" ]]; then pass "$msg"
  else fail "$msg" "got '$got', want '$want'"; fi
}

# No jq gate: the hook reads its label with jq and fails open without it, and
# no case here reads that label — so a missing jq cannot turn into a skip.
[[ -f "$CK_HOOK" ]] || { echo "test-worker-checkpoint: no hook at $CK_HOOK" >&2; exit 1; }

# ─── Sandbox ─────────────────────────────────────────────────────────
TMP_ROOT="$(mktemp -d /tmp/clade-ck-test-XXXXXX)"
case "$TMP_ROOT" in
  /tmp/clade-ck-test-*) : ;;
  *) echo "FATAL: sandbox '$TMP_ROOT' is not under /tmp — aborting"; exit 1 ;;
esac
trap 'rm -rf "$TMP_ROOT"' EXIT
export HOME="$TMP_ROOT/home" XDG_CONFIG_HOME="$TMP_ROOT/xdg" GIT_CONFIG_NOSYSTEM=1
mkdir -p "$HOME" "$XDG_CONFIG_HOME"

# ─── worker-checkpoint: per-tool-call workspace snapshots ─────────────────────
# A worker commits exactly once, at the end of verification, and stop()
# force-removes the worktree — so "correct at call 14, wrong at 15" had no
# record anywhere. This hook writes one commit per Edit/Write into a shadow
# repo OUTSIDE the worktree.
section "worker-checkpoint hook"

CK_ROOT=$(mktemp -d /tmp/clade-ck-XXXXXX)
mkdir -p "$CK_ROOT/wt"
( cd "$CK_ROOT/wt" && git init -q . && git config user.email t@e.com && git config user.name t \
  && echo v1 > f.txt && git add -A && git commit -q -m base ) >/dev/null 2>&1

ck_write() {  # $1 = new content
  echo "$1" > "$CK_ROOT/wt/f.txt"
  printf '{"tool_name":"Write","tool_input":{"file_path":"%s/wt/f.txt"}}' "$CK_ROOT" \
    | CLADE_WORKER_SHADOW_DIR="$CK_ROOT/shadow.git" CLADE_WORKER_WORKTREE="$CK_ROOT/wt" \
      bash "$CK_HOOK" >/dev/null 2>&1
}

# Inert without the env var — an interactive session must be untouched.
echo v0 > "$CK_ROOT/wt/f.txt"
printf '{"tool_name":"Write","tool_input":{"file_path":"%s/wt/f.txt"}}' "$CK_ROOT" \
  | bash "$CK_HOOK" >/dev/null 2>&1
if [[ -d "$CK_ROOT/shadow.git" ]]; then
  fail "hook is inert without CLADE_WORKER_SHADOW_DIR" "it created a shadow repo anyway"
else
  pass "hook is inert without CLADE_WORKER_SHADOW_DIR"
fi

ck_write v2; ck_write v3; ck_write v4
CK_N=$(git --git-dir="$CK_ROOT/shadow.git" rev-list --count HEAD 2>/dev/null || echo 0)
assert_eq "3" "$CK_N" "one checkpoint per tool call"

CK_OLD=$(git --git-dir="$CK_ROOT/shadow.git" show HEAD~2:f.txt 2>/dev/null)
assert_eq "v2" "$CK_OLD" "an earlier call's content is recoverable"

# The property the whole design rests on: a separate git-dir means a separate
# index, so checkpoints cannot contend with the worker's own commits.
CK_IDX_BEFORE=$(md5sum "$CK_ROOT/wt/.git/index" 2>/dev/null | cut -d' ' -f1)
ck_write v5
CK_IDX_AFTER=$(md5sum "$CK_ROOT/wt/.git/index" 2>/dev/null | cut -d' ' -f1)
assert_eq "$CK_IDX_BEFORE" "$CK_IDX_AFTER" "checkpointing never touches the worktree's own index"

( cd "$CK_ROOT/wt" && git add -A && git commit -q -m "worker commit" ) >/dev/null 2>&1 \
  && pass "the worker can still commit after a checkpoint" \
  || fail "the worker can still commit after a checkpoint"

# A repo-supplied pre-commit hook must not be able to block a checkpoint.
printf '#!/bin/sh\nexit 1\n' > "$CK_ROOT/wt/.git/hooks/pre-commit"
chmod +x "$CK_ROOT/wt/.git/hooks/pre-commit"
CK_N_BEFORE=$(git --git-dir="$CK_ROOT/shadow.git" rev-list --count HEAD)
ck_write v6
CK_N_AFTER=$(git --git-dir="$CK_ROOT/shadow.git" rev-list --count HEAD)
if [[ "$CK_N_AFTER" -gt "$CK_N_BEFORE" ]]; then
  pass "a hostile pre-commit hook cannot block a checkpoint"
else
  fail "a hostile pre-commit hook cannot block a checkpoint"
fi

# The shadow must live outside the worktree, or `git add -A` would sweep it in.
if ls -a "$CK_ROOT/wt" | grep -q shadow; then
  fail "the shadow repo lives outside the worktree" "found it inside"
else
  pass "the shadow repo lives outside the worktree"
fi

rm -rf "$CK_ROOT"

# ─── worker-checkpoint must see a write that never touched Edit/Write ───
#
# It did not. The hook was wired to PostToolUse Edit|Write and additionally
# exited 0 on an empty .tool_input.file_path — so an agent writing through a
# `python - <<EOF` heredoc produced no checkpoint at all. That is the precise
# failure mode the unattended-run literature names ("once the model abandoned
# the edit tool for Python string splicing…"), i.e. the hook was blind in the
# one case it exists for. The path was only ever a commit-message label; the
# snapshot is `git add -A` over the whole worktree.

WC_DIR=$(mktemp -d)
(
  cd "$WC_DIR" || exit 1
  git init -q .
  git config user.email t@example.com; git config user.name t
  echo base > file.txt; git add -A; git -c core.hooksPath=/dev/null commit -qm base
) >/dev/null 2>&1
echo "written by bash, not by Edit" > "$WC_DIR/from-bash.txt"
WC_SHADOW="$WC_DIR/.shadow.git"
WC_OUT=$(CLADE_WORKER_SHADOW_DIR="$WC_SHADOW" CLADE_WORKER_WORKTREE="$WC_DIR" \
  bash "$CK_HOOK" \
  <<< '{"tool_name":"Bash","tool_input":{"command":"python - <<EOF"}}' 2>&1)
WC_N=$(git --git-dir="$WC_SHADOW" rev-list --count HEAD 2>/dev/null || echo 0)
if [[ "${WC_N:-0}" -ge 1 ]]; then
  pass "a Bash write with no file_path still produces a checkpoint"
else
  fail "a Bash write with no file_path still produces a checkpoint" \
       "shadow has $WC_N commit(s); hook said: $WC_OUT"
fi
# And the snapshot must actually contain the file the Bash tool wrote.
if git --git-dir="$WC_SHADOW" --work-tree="$WC_DIR" show --name-only --format= HEAD 2>/dev/null \
   | grep -q "from-bash.txt"; then
  pass "the checkpoint contains the file written outside Edit/Write"
else
  fail "the checkpoint contains the file written outside Edit/Write" \
       "$(git --git-dir="$WC_SHADOW" show --name-only --format= HEAD 2>&1 | head -3)"
fi
# The hook must still be inert when no shadow dir is configured.
if bash "$CK_HOOK" \
   <<< '{"tool_name":"Bash","tool_input":{}}' >/dev/null 2>&1; then
  pass "worker-checkpoint stays inert without CLADE_WORKER_SHADOW_DIR"
else
  fail "worker-checkpoint stays inert without CLADE_WORKER_SHADOW_DIR" "non-zero exit"
fi
rm -rf "$WC_DIR"

# ─── worker-checkpoint mirrors the worktree's ignore rules ───────────────────
# The shadow is a fresh bare repository: its own info/exclude is empty, and its
# own index decides what counts as tracked. Until 2026-11-26 a snapshot so
# honoured the worktree's .gitignore files and a global excludesFile, and
# nothing else. Probed on a LINKED worktree — the shape run-tasks-parallel.sh
# creates, whose info/exclude lives in the common git dir — a file listed only
# in info/exclude (where Claude Code's runtime files are listed) landed in the
# shadow, and a file the worktree tracks although a rule matches it never did.
# A snapshot must hold what `git add -A` in the worktree would stage.
section "worker-checkpoint mirrors the worktree's ignore rules"

XR="$TMP_ROOT/excl"
XWT="$XR/wt"; XSH="$XR/shadow.git"
mkdir -p "$XR"
(
  cd "$XR" && git init -q main && cd main \
    && git config user.email t@e.com && git config user.name t \
    && printf '*.log\n' > .gitignore && echo base > f.txt && echo tracked > tracked-later.txt \
    && echo fixture > forced.log && echo gone > a-gone.log \
    && git add .gitignore f.txt tracked-later.txt && git add -f forced.log a-gone.log \
    && git -c core.hooksPath=/dev/null -c commit.gpgsign=false commit -qm base \
    && git -c core.hooksPath=/dev/null worktree add -q "$XWT" -b task
) >/dev/null 2>&1
# Both settings live with the COMMON dir (main/.git), which a linked worktree reads.
printf 'local-secret.env\n**/.claude/checkpoints/\n' >> "$XR/main/.git/info/exclude"
printf 'repo-local-ignored.txt\n' > "$XR/repo-excludes"
git -C "$XWT" config core.excludesFile "$XR/repo-excludes"

echo s > "$XWT/local-secret.env"
mkdir -p "$XWT/sub/.claude/checkpoints" && echo c > "$XWT/sub/.claude/checkpoints/a.json"
echo r > "$XWT/repo-local-ignored.txt"
echo l > "$XWT/x.log"
echo u > "$XWT/untracked.txt"
echo later > "$XWT/later.txt"

# Run from a directory that is neither the worktree nor any repository: the
# hook must read the worktree CLADE_WORKER_WORKTREE names, whatever its cwd.
xr_snap() {  # $1 = worktree, $2 = shadow
  ( cd "$XR" && printf '{"tool_name":"Bash","tool_input":{}}' \
      | CLADE_WORKER_SHADOW_DIR="$2" CLADE_WORKER_WORKTREE="$1" bash "$CK_HOOK" ) >/dev/null 2>&1
}
xr_tree() { git --git-dir="$1" ls-tree -r --name-only HEAD 2>/dev/null; }
xr_has() {  # $1 = shadow, $2 = path, $3 = message
  if xr_tree "$1" | grep -qxF "$2"; then pass "$3"
  else fail "$3" "'$2' is not in the snapshot: $(xr_tree "$1" | tr '\n' ' ')"; fi
}
xr_lacks() {
  if xr_tree "$1" | grep -qxF "$2"; then fail "$3" "'$2' is in the snapshot"; else pass "$3"; fi
}

XIDX=$(git -C "$XWT" rev-parse --git-path index)
case "$XIDX" in /*) ;; *) XIDX="$XWT/$XIDX" ;; esac
XIDX_BEFORE=$(cksum < "$XIDX")
xr_snap "$XWT" "$XSH"
assert_eq "$(git --git-dir="$XSH" rev-list --count HEAD 2>/dev/null)" "1" "a linked worktree is snapshotted"
assert_eq "$(cksum < "$XIDX")" "$XIDX_BEFORE" "the linked worktree's own index is untouched"
xr_has   "$XSH" untracked.txt "an untracked file is in the snapshot (control)"
xr_lacks "$XSH" x.log "a .gitignore'd file is not (control: the shadow always honoured those)"
xr_lacks "$XSH" local-secret.env "a file listed only in info/exclude is not in the snapshot"
xr_lacks "$XSH" sub/.claude/checkpoints/a.json "nor a file under a directory info/exclude lists"
xr_lacks "$XSH" repo-local-ignored.txt "a repo-local core.excludesFile is honoured"
xr_has   "$XSH" forced.log "a file the worktree tracks although a rule matches it is in the snapshot"
xr_has   "$XSH" later.txt "a file no rule matches yet is in the snapshot"

# A rule added after a path was recorded takes it out of the next snapshot,
# unless the worktree tracks that path — `git status` would still report it.
printf 'later.txt\ntracked-later.txt\n' >> "$XR/main/.git/info/exclude"
xr_snap "$XWT" "$XSH"
assert_eq "$(git --git-dir="$XSH" rev-list --count HEAD 2>/dev/null)" "2" "the second write is a second checkpoint"
xr_lacks "$XSH" later.txt "a path recorded earlier drops out once info/exclude lists it"
[[ -f "$XWT/later.txt" ]] && pass "dropping it leaves the worktree's file in place" \
  || fail "dropping it leaves the worktree's file in place" "the hook deleted it"
xr_has   "$XSH" tracked-later.txt "a tracked path a new rule matches stays in the snapshot"
xr_has   "$XSH" forced.log "and so does the forced one, snapshot after snapshot"

# A main worktree: --git-path prints .git/info/exclude relative to the cwd. A
# tracked forced file deleted from the worktree must not stop the next one
# from being recorded (update-index aborts on a missing path without --remove).
echo m > "$XR/main/local-secret.env"
rm -f "$XR/main/a-gone.log"
xr_snap "$XR/main" "$XR/main-shadow.git"
xr_lacks "$XR/main-shadow.git" local-secret.env "a main worktree's info/exclude is honoured too"
xr_has   "$XR/main-shadow.git" f.txt "a main worktree's tracked file is in its snapshot (control)"
xr_lacks "$XR/main-shadow.git" a-gone.log "a forced file the worker deleted is not in the snapshot"
xr_has   "$XR/main-shadow.git" forced.log "the next forced file is recorded all the same"

# The hook changes into the worktree before it snapshots, so a relative
# CLADE_WORKER_SHADOW_DIR must still name a directory under the hook's cwd.
( cd "$XR" && printf '{"tool_name":"Bash","tool_input":{}}' \
    | CLADE_WORKER_SHADOW_DIR=rel-shadow.git CLADE_WORKER_WORKTREE="$XWT" bash "$CK_HOOK" ) >/dev/null 2>&1
assert_eq "$(git --git-dir="$XR/rel-shadow.git" rev-list --count HEAD 2>/dev/null)" "1" \
  "a relative CLADE_WORKER_SHADOW_DIR still resolves against the hook's cwd"
[[ -e "$XWT/rel-shadow.git" ]] && fail "no shadow appears inside the worktree" "found $XWT/rel-shadow.git" \
  || pass "no shadow appears inside the worktree"

# The copy is refreshed every run, so once the worktree has no info/exclude, a
# copy an earlier run left in the shadow must stop applying.
mv "$XR/main/.git/info/exclude" "$XR/exclude.removed"
xr_snap "$XWT" "$XSH"
xr_has "$XSH" local-secret.env "a removed info/exclude no longer applies to the next snapshot"

# ─── Summary ─────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ $TESTS_FAILED -eq 0 ]]; then
  echo -e "  ${GREEN}ALL PASSED${NC} ($TESTS_PASSED/$TESTS_RUN)"
else
  echo -e "  ${RED}$TESTS_FAILED FAILED${NC} / $TESTS_PASSED passed / $TESTS_RUN total"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

[[ $TESTS_FAILED -eq 0 ]]
