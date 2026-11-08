#!/usr/bin/env bash
# test-memory-sync-breaker.sh — per-host circuit breaker for dotfiles sync pushes.
#
# Real sync-push runs use temporary Git stores and remotes; memory-sync runs use
# a temporary HOME and a counting sync-push stub or a wrapper around the real
# script. No real profile, sync store, network, or remote is touched.
#
# Internal:
#   MSB_HOOK / MSB_PUSH   test these source files instead of the repository's
#   MSB_ONLY="failures gate ..."  run only these sections
#   MSB_MUTANT=1          stop at the first failure and skip mutations
#   MSB_SKIP_MUTATIONS=1  skip the mutation suite (used for old-code red proof)

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK="${MSB_HOOK:-$REPO_ROOT/configs/hooks/memory-sync.sh}"
PUSH="${MSB_PUSH:-$REPO_ROOT/configs/scripts/sync-push.sh}"
BASE_PATH="$PATH"
MSB_MUTANT="${MSB_MUTANT:-}"
unset CLAUDE_CONFIG_DIR CLADE_PRIVATE_PROJECTS CLADE_PRIVATE_KEYWORDS
unset CLADE_SYNC_PUSH_BACKOFF_FILE CLADE_SYNC_PUSH_BACKOFF_NOW
unset CLADE_SYNC_PUSH_BACKOFF_BASE_SECONDS CLADE_SYNC_PUSH_BACKOFF_MAX_SECONDS

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'

pass() {
  TESTS_RUN=$((TESTS_RUN + 1)); TESTS_PASSED=$((TESTS_PASSED + 1))
  echo -e "  ${GREEN}✓${NC} $1"
}
fail() {
  TESTS_RUN=$((TESTS_RUN + 1)); TESTS_FAILED=$((TESTS_FAILED + 1))
  echo -e "  ${RED}✗${NC} $1"
  [[ -n "${2:-}" ]] && echo -e "    ${RED}→ $2${NC}"
  [[ -n "$MSB_MUTANT" ]] && exit 1
  return 0
}
section() { echo ""; echo -e "${YELLOW}━━━ $1 ━━━${NC}"; }
assert_eq() {
  if [[ "$1" == "$2" ]]; then pass "$3"; else fail "$3" "got '$1', want '$2'"; fi
}
check() {
  local msg="$1"; shift
  if "$@"; then pass "$msg"; else fail "$msg"; fi
}

for dependency in git jq; do
  if ! command -v "$dependency" >/dev/null 2>&1; then
    echo "FATAL: $dependency is required" >&2
    exit 1
  fi
done

SANDBOX="$(mktemp -d "${TMPDIR:-/tmp}/clade-msb.XXXXXX")"
case "$SANDBOX" in
  "${TMPDIR:-/tmp}"/clade-msb.*) : ;;
  *) echo "FATAL: unexpected sandbox '$SANDBOX'" >&2; exit 1 ;;
esac
trap 'rm -rf "$SANDBOX"' EXIT

new_store() {
  local name="$1"
  H="$SANDBOX/$name/home"
  STORE="$SANDBOX/$name/store"
  RUN_PATH="$BASE_PATH"
  mkdir -p "$H/.claude/scripts" "$STORE/corrections" "$STORE/memory"
  printf 'SYNC_BACKEND=nfs\nSYNC_DIR=%s\n' "$STORE" > "$H/.claude/.sync-config"
  printf -- '- rule one\n' > "$STORE/corrections/rules.md"
  printf 'base\n' > "$STORE/notes.txt"
  # All default patterns are present without the helper's comments, so a no-op
  # store stays byte-identical and a no-op run stays offline.
  printf '%s\n' \
    'corrections/history.jsonl' \
    '*.bak-*' \
    '.backups/' \
    'skills/synced/' \
    '__pycache__/' \
    '*.py[cod]' \
    '*.corrupt.*' \
    'skills/.trash/' > "$STORE/.gitignore"
  git init -q "$STORE"
  git -C "$STORE" config user.email test@example.com
  git -C "$STORE" config user.name test
  git -C "$STORE" add -A
  git -C "$STORE" -c core.hooksPath=/dev/null commit -qm base
}

run_push() {
  local now="$1"
  HOME="$H" PATH="${RUN_PATH:-$BASE_PATH}" \
    CLADE_SYNC_PUSH_LOCK="$H/.claude/push.lock" \
    CLADE_SYNC_PUSH_BACKOFF_NOW="$now" \
    CLADE_SYNC_PUSH_BACKOFF_BASE_SECONDS=60 \
    CLADE_SYNC_PUSH_BACKOFF_MAX_SECONDS=240 \
    bash "$PUSH" > "$H/push.out" 2>&1
  PUSH_RC=$?
}

run_hook() {
  local now="$1" input="$2"
  printf '%s' "$input" | HOME="$H" \
    CLADE_SYNC_PUSH_LOCK="$H/.claude/push.lock" \
    CLADE_SYNC_PUSH_BACKOFF_FILE="${HOOK_BACKOFF_FILE:-}" \
    CLADE_SYNC_PUSH_BACKOFF_NOW="$now" \
    CLADE_SYNC_PUSH_BACKOFF_BASE_SECONDS="${HOOK_BASE:-60}" \
    CLADE_SYNC_PUSH_BACKOFF_MAX_SECONDS="${HOOK_MAX:-240}" \
    bash "$HOOK" > "$H/hook.out" 2> "$H/hook.err"
  HOOK_RC=$?
}

fire_write() {
  local now="$1" path="$2" input
  input=$(jq -n --arg path "$path" '{tool_name:"Write",tool_input:{file_path:$path}}')
  run_hook "$now" "$input"
}

fire_write_real_time() {
  local path="$1" input
  input=$(jq -n --arg path "$path" '{tool_name:"Write",tool_input:{file_path:$path}}')
  printf '%s' "$input" | HOME="$H" CLADE_SYNC_PUSH_LOCK="$H/.claude/push.lock" \
    bash "$HOOK" > "$H/hook.out" 2> "$H/hook.err"
  HOOK_RC=$?
}

backoff_line() {
  if [[ -f "$H/.claude/.sync-push-backoff" ]]; then
    cat "$H/.claude/.sync-push-backoff"
  else
    printf '<absent>\n'
  fi
}

spawn_count() {
  if [[ -f "$H/spawns" ]]; then
    wc -l < "$H/spawns" | tr -d ' '
  else
    printf '0\n'
  fi
}

network_count() {
  if [[ -f "$H/network" ]]; then
    wc -l < "$H/network" | tr -d ' '
  else
    printf '0\n'
  fi
}

wait_count() {
  local want="$1" i
  for i in $(seq 1 60); do
    [[ "$(spawn_count)" -ge "$want" ]] && return 0
    sleep 0.05
  done
  return 1
}

wait_backoff() {
  local want="$1" i
  for i in $(seq 1 60); do
    [[ "$(backoff_line)" == "$want" ]] && return 0
    sleep 0.05
  done
  return 1
}

wait_absent() {
  local i
  for i in $(seq 1 60); do
    [[ ! -e "$H/.claude/.sync-push-backoff" ]] && return 0
    sleep 0.05
  done
  return 1
}

quiesce() { sleep 0.3; }

install_stub() {
  : > "$H/spawns"
  cat > "$H/.claude/scripts/sync-push.sh" <<EOF
#!/usr/bin/env bash
printf 'spawn\n' >> '$H/spawns'
EOF
  chmod +x "$H/.claude/scripts/sync-push.sh"
}

install_real_wrapper() {
  : > "$H/spawns"
  cat > "$H/.claude/scripts/sync-push.sh" <<EOF
#!/usr/bin/env bash
printf 'spawn\n' >> '$H/spawns'
exec bash '$PUSH'
EOF
  chmod +x "$H/.claude/scripts/sync-push.sh"
}

add_remote() {
  git init --bare -q "$H/remote.git"
  git -C "$STORE" remote add origin "$H/remote.git"
  git -C "$STORE" push -u origin HEAD >/dev/null 2>&1
}

make_git_shim() {
  local mode="$1" real_git
  real_git="$(command -v git)"
  mkdir -p "$H/shim"
  if [[ "$mode" == "unresolved" ]]; then
    cat > "$H/shim/git" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in pull|merge) exit 1 ;; esac
exec '$real_git' "\$@"
EOF
  elif [[ "$mode" == "rejected" ]]; then
    cat > "$H/shim/git" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in push) exit 1 ;; esac
exec '$real_git' "\$@"
EOF
  elif [[ "$mode" == "commit" ]]; then
    cat > "$H/shim/git" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in commit) exit 1 ;; esac
exec '$real_git' "\$@"
EOF
  else
    cat > "$H/shim/git" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in pull|push|fetch) printf '%s\n' "\${1:-}" >> '$H/network' ;; esac
exec '$real_git' "\$@"
EOF
  fi
  cat > "$H/shim/sleep" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "$H/shim/git" "$H/shim/sleep"
  RUN_PATH="$H/shim:$BASE_PATH"
}

t_failures() {
  section "sync-push records each failure class and clears only on success"

  new_store markers
  printf -- '- rule one\n<<<<<<< Updated upstream\n=======\n- rule two\n>>>>>>> Stashed changes\n' \
    > "$STORE/corrections/rules.md"
  run_push 1000
  assert_eq "$PUSH_RC" "1" "conflict markers make sync-push fail"
  assert_eq "$(backoff_line)" "1000 1 conflict-markers" \
    "a REFUSED push writes one machine-readable backoff line"
  if grep -q 'sync-push-backoff.*No such file' "$H/push.out"; then
    fail "the first refusal does not read missing backoff state" "$(cat "$H/push.out")"
  else
    pass "the first refusal does not read missing backoff state"
  fi
  check "the per-host file is outside the sync store" test ! -e "$STORE/.sync-push-backoff"
  run_push 1001
  assert_eq "$(backoff_line)" "1001 2 conflict-markers" \
    "a consecutive failure advances the time and count"
  printf -- '- rule one\n- rule two\n' > "$STORE/corrections/rules.md"
  run_push 1002
  assert_eq "$PUSH_RC" "0" "a manual push runs during an active backoff"
  assert_eq "$(backoff_line)" "<absent>" "a successful manual push clears the backoff"
  assert_eq "$(git -C "$STORE" rev-list --count HEAD)" "2" \
    "the manual recovery push really committed the fix"

  new_store unmerged
  local base_branch
  base_branch="$(git -C "$STORE" symbolic-ref --short HEAD)"
  git -C "$STORE" checkout -qb side
  printf 'side\n' > "$STORE/notes.txt"
  git -C "$STORE" add notes.txt
  git -C "$STORE" -c core.hooksPath=/dev/null commit -qm side
  git -C "$STORE" checkout -q "$base_branch"
  printf 'main\n' > "$STORE/notes.txt"
  git -C "$STORE" add notes.txt
  git -C "$STORE" -c core.hooksPath=/dev/null commit -qm main
  git -C "$STORE" merge side >/dev/null 2>&1
  check "the unmerged-path fixture really conflicted" \
    test -n "$(git -C "$STORE" ls-files -u)"
  run_push 2000
  assert_eq "$PUSH_RC" "1" "unmerged paths make sync-push fail"
  assert_eq "$(backoff_line)" "2000 1 unmerged-paths" \
    "an unmergeable store records unmerged-paths before marker handling"

  new_store unresolved
  add_remote
  printf -- '- rule two\n' >> "$STORE/corrections/rules.md"
  make_git_shim unresolved
  run_push 3000
  assert_eq "$PUSH_RC" "1" "an unresolved pull/merge conflict makes sync-push fail"
  assert_eq "$(backoff_line)" "3000 1 unresolved-conflict" \
    "the unresolved conflict is visible to sync-health through the reason token"

  new_store rejected
  add_remote
  printf -- '- rule two\n' >> "$STORE/corrections/rules.md"
  make_git_shim rejected
  run_push 4000
  assert_eq "$PUSH_RC" "1" "a rejected push exits nonzero after its retries"
  assert_eq "$(backoff_line)" "4000 1 push-failed" "a rejected push opens the breaker"
  RUN_PATH="$BASE_PATH"
  run_push 4001
  assert_eq "$PUSH_RC" "0" "manual retry succeeds without another commit"
  assert_eq "$(backoff_line)" "<absent>" "the no-new-commit retry clears the breaker"
  assert_eq "$(git --git-dir="$H/remote.git" rev-parse HEAD)" \
    "$(git -C "$STORE" rev-parse HEAD)" "the retry really pushed the existing local commit"

  new_store stage-failure
  printf -- '- rule two\n' >> "$STORE/corrections/rules.md"
  : > "$STORE/.git/index.lock"
  run_push 4500
  assert_eq "$PUSH_RC" "1" "a staging failure exits nonzero"
  assert_eq "$(backoff_line)" "4500 1 stage-failed" "a stale index lock records stage-failed"
  assert_eq "$(git -C "$STORE" rev-list --count HEAD)" "1" "the staging failure cannot commit"

  new_store commit-failure
  printf -- '- rule two\n' >> "$STORE/corrections/rules.md"
  make_git_shim commit
  run_push 4600
  assert_eq "$PUSH_RC" "1" "a commit failure after a successful add exits nonzero"
  assert_eq "$(backoff_line)" "4600 1 commit-failed" "a failed git commit records commit-failed"
  assert_eq "$(git -C "$STORE" rev-list --count HEAD)" "1" "the failed commit adds no history"
}

t_delivery() {
  section "empty-index runs stay offline unless a delivery or retry is pending"

  new_store no-op
  add_remote
  make_git_shim count
  run_push 4700
  run_push 4701
  run_push 4702
  assert_eq "$PUSH_RC" "0" "three no-op runs exit successfully"
  assert_eq "$(network_count)" "0" "three no-op runs make zero pull/push/fetch calls"
  assert_eq "$(backoff_line)" "<absent>" "a no-op run writes no backoff"

  new_store stranded
  add_remote
  printf -- '- stranded local commit\n' >> "$STORE/corrections/rules.md"
  git -C "$STORE" add -A
  git -C "$STORE" -c core.hooksPath=/dev/null commit -qm stranded
  make_git_shim count
  run_push 4800
  assert_eq "$PUSH_RC" "0" "an empty-index run with a stranded commit succeeds"
  assert_eq "$(git --git-dir="$H/remote.git" rev-parse HEAD)" \
    "$(git -C "$STORE" rev-parse HEAD)" "the stranded commit is pushed without new staged changes"
  assert_eq "$(backoff_line)" "<absent>" "a successful stranded-commit delivery leaves no backoff"

  new_store backoff-retry
  add_remote
  printf '4900 1 push-failed\n' > "$H/.claude/.sync-push-backoff"
  make_git_shim count
  run_push 4901
  assert_eq "$PUSH_RC" "0" "an empty-index manual retry runs while backoff exists"
  assert_eq "$(backoff_line)" "<absent>" "the empty-index manual retry clears backoff on success"

  new_store no-upstream
  git init --bare -q "$H/remote.git"
  git -C "$STORE" remote add origin "$H/remote.git"
  make_git_shim count
  run_push 4950
  assert_eq "$PUSH_RC" "0" "a remote with no upstream is treated as not ahead"
  assert_eq "$(network_count)" "0" "a remote with no upstream does not force a network call"
  assert_eq "$(backoff_line)" "<absent>" "a remote with no upstream writes no backoff"
}

t_gate() {
  section "memory-sync checks the breaker before every path class and topic gate"

  new_store gate
  printf -- '<<<<<<< Updated upstream\n=======\n>>>>>>> Stashed changes\n' \
    >> "$STORE/corrections/rules.md"
  run_push 5000
  install_stub
  mkdir -p "$H/.claude/memory/topic" "$H/.claude/corrections" \
    "$H/.claude/hooks" "$H/.claude/skills/demo"
  printf 'A concrete memory fact with enough detail to pass the specificity gate and its reason.\n' \
    > "$H/.claude/memory/topic/note.md"
  printf 'rule\n' > "$H/.claude/corrections/rules.md"
  printf '# hook\n' > "$H/.claude/hooks/demo.sh"
  printf '# skill\n' > "$H/.claude/skills/demo/SKILL.md"

  fire_write 5001 "$H/.claude/memory/topic/note.md"
  fire_write 5001 "$H/.claude/corrections/rules.md"
  fire_write 5001 "$H/.claude/hooks/demo.sh"
  fire_write 5001 "$H/.claude/skills/demo/SKILL.md"
  fire_write 5001 "$H/.claude/scripts/other.sh"
  run_hook 5001 '{"tool_name":"Bash","tool_input":{"command":"rm ~/.claude/corrections/old.md"}}'
  quiesce
  assert_eq "$HOOK_RC" "0" "blocked memory-sync calls still exit successfully"
  assert_eq "$(spawn_count)" "0" \
    "after a REFUSED, memory/corrections/hooks/skills/scripts and Bash spawn nothing"
  check "the blocked memory write never reaches its topic cooldown" \
    test ! -e "$H/.claude/memory/.sync-cooldown.json"

  fire_write 5059 "$H/.claude/skills/demo/SKILL.md"
  quiesce
  assert_eq "$(spawn_count)" "0" "the first 30-minute window stays closed before its boundary"
  fire_write 5060 "$H/.claude/corrections/rules.md"
  wait_count 1
  assert_eq "$(spawn_count)" "1" "the window boundary allows one half-open push"
}

t_claim() {
  section "an expired window admits one claimed probe, not every fire"

  new_store claim
  install_stub
  printf '1000 1 push-failed\n' > "$H/.claude/.sync-push-backoff"
  fire_write 1060 "$H/.claude/corrections/rules.md"
  check "the first expired-window fire spawns its probe" wait_count 1
  assert_eq "$(backoff_line)" "1060 1 push-failed" \
    "the claim records probe time without changing the failure count"
  fire_write 1061 "$H/.claude/corrections/rules.md"
  fire_write 1062 "$H/.claude/corrections/rules.md"
  quiesce
  assert_eq "$(spawn_count)" "1" "two later fires cannot spawn while the claimed probe is pending"
  assert_eq "$(backoff_line)" "1060 1 push-failed" "a stub that never reports leaves one claim intact"

  new_store claim-no-executable
  printf '1000 1 push-failed\n' > "$H/.claude/.sync-push-backoff"
  fire_write 1060 "$H/.claude/corrections/rules.md"
  quiesce
  assert_eq "$(spawn_count)" "0" "an expired window without an executable push spawns nothing"
  assert_eq "$(backoff_line)" "1000 1 push-failed" "no claim is written before the executable check"

  new_store claim-unwritable
  install_stub
  mkdir -p "$H/claim-state"
  printf '1000 1 push-failed\n' > "$H/claim-state/.sync-push-backoff"
  chmod 555 "$H/claim-state"
  if [[ "$(id -u)" -eq 0 ]]; then
    echo "  SKIP: unwritable-claim case (root ignores directory permissions)"
  else
    HOOK_BACKOFF_FILE="$H/claim-state/.sync-push-backoff" \
      fire_write 1060 "$H/.claude/corrections/rules.md"
    chmod 755 "$H/claim-state"
    assert_eq "$HOOK_RC" "0" "an unwritable claim does not abort the hook"
    check "an unwritable claim still spawns its probe" wait_count 1
    assert_eq "$(spawn_count)" "1" "an unwritable claim spawns exactly once"
    check "an unwritable claim leaves no temporary file" \
      test -z "$(find "$H/claim-state" -name '.sync-push-backoff.tmp.*' -print)"
  fi
  chmod 755 "$H/claim-state" 2>/dev/null || true
}

t_half_open() {
  section "half-open retries double to the cap; success closes the breaker"

  new_store success
  printf -- '<<<<<<< Updated upstream\n=======\n>>>>>>> Stashed changes\n' \
    >> "$STORE/corrections/rules.md"
  run_push 6000
  install_real_wrapper
  printf -- '- rule one\n- rule two\n' > "$STORE/corrections/rules.md"
  fire_write 6000 "$H/.claude/corrections/rules.md"
  quiesce
  assert_eq "$(spawn_count)" "0" "an active breaker blocks the automatic recovery attempt"
  fire_write 6060 "$H/.claude/corrections/rules.md"
  check "the half-open success probe spawns" wait_count 1
  check "the half-open success finishes and clears state" wait_absent
  assert_eq "$(backoff_line)" "<absent>" "the half-open success clears the backoff"
  assert_eq "$(git -C "$STORE" rev-list --count HEAD)" "2" \
    "the half-open success really committed"
  fire_write 6061 "$H/.claude/skills/demo/SKILL.md"
  check "the post-recovery write spawns" wait_count 2
  assert_eq "$(spawn_count)" "2" "a later write flows normally after recovery"

  new_store retry
  printf -- '<<<<<<< Updated upstream\n=======\n>>>>>>> Stashed changes\n' \
    >> "$STORE/corrections/rules.md"
  run_push 7000
  install_real_wrapper
  fire_write 7060 "$H/.claude/corrections/rules.md"
  check "the first failed probe spawns" wait_count 1
  check "the first failed probe records its result" wait_backoff "7060 2 conflict-markers"
  assert_eq "$(backoff_line)" "7060 2 conflict-markers" \
    "a failed half-open probe records the second consecutive failure"
  fire_write 7119 "$H/.claude/corrections/rules.md"
  quiesce
  assert_eq "$(spawn_count)" "1" "119 seconds into the second window stays closed"
  fire_write 7180 "$H/.claude/corrections/rules.md"
  check "the second failure backs off for 120 seconds" wait_count 2
  check "the second failed probe records its result" wait_backoff "7180 3 conflict-markers"
  fire_write 7419 "$H/.claude/corrections/rules.md"
  quiesce
  assert_eq "$(spawn_count)" "2" "239 seconds into the third window stays closed"
  fire_write 7420 "$H/.claude/corrections/rules.md"
  check "the third failure backs off for 240 seconds" wait_count 3
  check "the third failed probe records its result" wait_backoff "7420 4 conflict-markers"
  fire_write 7659 "$H/.claude/corrections/rules.md"
  quiesce
  assert_eq "$(spawn_count)" "3" "239 seconds into the capped fourth window stays closed"
  fire_write 7660 "$H/.claude/corrections/rules.md"
  check "the capped fourth window permits its probe" wait_count 4
  check "the fourth failed probe records its result" wait_backoff "7660 5 conflict-markers"
  assert_eq "$(spawn_count)" "4" "the capped window permits the next half-open probe"
  assert_eq "$(backoff_line)" "7660 5 conflict-markers" \
    "each real probe updates the persisted failure state"
}

t_robustness() {
  section "malformed backoff state fails open instead of wedging sync"

  new_store no-state
  install_stub
  fire_write 8000 "$H/.claude/skills/demo/SKILL.md"
  wait_count 1
  assert_eq "$HOOK_RC" "0" "no backoff file leaves the normal path successful"
  assert_eq "$(spawn_count)" "1" "no backoff file fails open"
  if grep -q 'sync-push-backoff' "$H/hook.err"; then
    fail "the no-state fast path avoids a missing-file read error" "$(cat "$H/hook.err")"
  else
    pass "the no-state fast path avoids a missing-file read error"
  fi

  new_store no-newline
  install_stub
  printf '8000 1 push-failed' > "$H/.claude/.sync-push-backoff"
  fire_write 8001 "$H/.claude/skills/demo/SKILL.md"
  quiesce
  assert_eq "$HOOK_RC" "0" "a final line without a newline is still parsed"
  assert_eq "$(spawn_count)" "0" "a newline-less active state stays closed"

  new_store malformed-time
  install_stub
  printf 'not-a-time 1 push-failed\n' > "$H/.claude/.sync-push-backoff"
  fire_write 8000 "$H/.claude/skills/demo/SKILL.md"
  wait_count 1
  assert_eq "$HOOK_RC" "0" "a malformed timestamp does not abort the hook"
  assert_eq "$(spawn_count)" "1" "a malformed timestamp fails open"

  new_store malformed-count
  install_stub
  printf '8000 nope push-failed\n' > "$H/.claude/.sync-push-backoff"
  fire_write 8000 "$H/.claude/skills/demo/SKILL.md"
  wait_count 1
  assert_eq "$HOOK_RC" "0" "a malformed count does not abort the hook"
  assert_eq "$(spawn_count)" "1" "a malformed count fails open"

  new_store malformed-reason
  install_stub
  printf '8000 1\n' > "$H/.claude/.sync-push-backoff"
  fire_write 8001 "$H/.claude/skills/demo/SKILL.md"
  wait_count 1
  assert_eq "$(spawn_count)" "1" "a missing reason fails open"

  new_store malformed-extra
  install_stub
  printf '8000 1 push-failed extra\n' > "$H/.claude/.sync-push-backoff"
  fire_write 8001 "$H/.claude/skills/demo/SKILL.md"
  wait_count 1
  assert_eq "$(spawn_count)" "1" "an extra state field fails open"

  new_store malformed-zero
  install_stub
  printf '8000 0 push-failed\n' > "$H/.claude/.sync-push-backoff"
  fire_write 8001 "$H/.claude/skills/demo/SKILL.md"
  wait_count 1
  assert_eq "$(spawn_count)" "1" "a zero failure count fails open"

  new_store invalid-base
  install_stub
  printf '8000 1 push-failed\n' > "$H/.claude/.sync-push-backoff"
  HOOK_BASE=nope fire_write 8001 "$H/.claude/skills/demo/SKILL.md"
  quiesce
  assert_eq "$HOOK_RC" "0" "an invalid base override falls back without aborting"
  assert_eq "$(spawn_count)" "0" "an invalid base override uses the default closed window"

  new_store zero-base
  install_stub
  printf '8000 1 push-failed\n' > "$H/.claude/.sync-push-backoff"
  HOOK_BASE=0 fire_write 8001 "$H/.claude/skills/demo/SKILL.md"
  quiesce
  assert_eq "$(spawn_count)" "0" "a zero base cannot bypass the default window"

  new_store invalid-max
  install_stub
  printf '8000 1 push-failed\n' > "$H/.claude/.sync-push-backoff"
  HOOK_MAX=nope fire_write 8001 "$H/.claude/skills/demo/SKILL.md"
  quiesce
  assert_eq "$HOOK_RC" "0" "an invalid maximum override falls back without aborting"
  assert_eq "$(spawn_count)" "0" "an invalid maximum override uses the default closed window"

  new_store invalid-now
  install_stub
  printf '%s 1 push-failed\n' "$(date +%s)" > "$H/.claude/.sync-push-backoff"
  fire_write nope "$H/.claude/skills/demo/SKILL.md"
  quiesce
  assert_eq "$HOOK_RC" "0" "an invalid clock override falls back without aborting"
  assert_eq "$(spawn_count)" "0" "an invalid clock override uses the real clock"

  new_store irregular-cap
  install_stub
  printf '8000 3 push-failed\n' > "$H/.claude/.sync-push-backoff"
  HOOK_BASE=100 HOOK_MAX=240 fire_write 8239 "$H/.claude/skills/demo/SKILL.md"
  quiesce
  assert_eq "$(spawn_count)" "0" "a 100-second base doubled twice stays capped at 240 seconds"
  HOOK_BASE=100 HOOK_MAX=240 fire_write 8240 "$H/.claude/skills/demo/SKILL.md"
  wait_count 1
  assert_eq "$(spawn_count)" "1" "the irregular-base cap opens at 240, not 400 seconds"

  new_store malformed-previous
  printf '8000 nope push-failed\n' > "$H/.claude/.sync-push-backoff"
  printf -- '<<<<<<< Updated upstream\n=======\n>>>>>>> Stashed changes\n' \
    >> "$STORE/corrections/rules.md"
  run_push 8001
  assert_eq "$(backoff_line)" "8001 1 conflict-markers" \
    "a malformed prior count restarts at one instead of aborting the recording"

  new_store previous-no-newline
  printf '7000 1 push-failed' > "$H/.claude/.sync-push-backoff"
  printf -- '<<<<<<< Updated upstream\n=======\n>>>>>>> Stashed changes\n' \
    >> "$STORE/corrections/rules.md"
  run_push 8001
  assert_eq "$(backoff_line)" "8001 2 conflict-markers" \
    "a newline-less prior count is still incremented"
}

t_defaults() {
  section "production defaults are 30 minutes doubling to a 24-hour cap"

  new_store default-base
  install_stub
  printf '%s 1 push-failed\n' "$(( $(date +%s) - 1740 ))" > "$H/.claude/.sync-push-backoff"
  fire_write_real_time "$H/.claude/skills/demo/SKILL.md"
  quiesce
  assert_eq "$(spawn_count)" "0" "the default first window is still closed at 29 minutes"
  printf '%s 1 push-failed\n' "$(( $(date +%s) - 1860 ))" > "$H/.claude/.sync-push-backoff"
  fire_write_real_time "$H/.claude/skills/demo/SKILL.md"
  wait_count 1
  assert_eq "$(spawn_count)" "1" "the default first window is open at 31 minutes"

  new_store default-cap
  install_stub
  printf '%s 10 push-failed\n' "$(( $(date +%s) - 86340 ))" > "$H/.claude/.sync-push-backoff"
  fire_write_real_time "$H/.claude/skills/demo/SKILL.md"
  quiesce
  assert_eq "$(spawn_count)" "0" "the default cap is still closed just before 24 hours"
  printf '%s 10 push-failed\n' "$(( $(date +%s) - 86460 ))" > "$H/.claude/.sync-push-backoff"
  fire_write_real_time "$H/.claude/skills/demo/SKILL.md"
  wait_count 1
  assert_eq "$(spawn_count)" "1" "the default cap is open just after 24 hours"
}

ALL_SECTIONS="failures delivery gate claim half_open robustness defaults"
for _section in ${MSB_ONLY:-$ALL_SECTIONS}; do
  "t_$_section"
done

if [[ -z "$MSB_MUTANT" && -z "${MSB_SKIP_MUTATIONS:-}" ]]; then
  section "mutations — removing a breaker guard must turn its section red"
  MUT_DIR="$SANDBOX/mutants"
  NMUT=0
  MUT_NAMES=(); MUT_EXPECT=(); MUT_ONLY=(); MUT_DIRS=(); MUT_TARGETS=()

  mutation() {
    local expect="$1" target="$2" name="$3" only="$4" dir="$MUT_DIR/m$NMUT" src
    mkdir -p "$dir/scripts" "$dir/hooks/lib"
    cp "$REPO_ROOT/configs/scripts/sync-push.sh" "$dir/scripts/sync-push.sh"
    cp "$REPO_ROOT/configs/scripts/sync-store-heal.sh" "$dir/scripts/sync-store-heal.sh"
    cp "$REPO_ROOT/configs/hooks/memory-sync.sh" "$dir/hooks/memory-sync.sh"
    cp "$REPO_ROOT/configs/hooks/lib/runtime-dir.sh" "$dir/hooks/lib/runtime-dir.sh"
    case "$target" in
      push) src="$dir/scripts/sync-push.sh" ;;
      hook) src="$dir/hooks/memory-sync.sh" ;;
    esac
    shift 4
    while [[ "$#" -ge 2 ]]; do
      if ! MSB_A="$1" MSB_R="$2" awk '
          { buf = buf (NR > 1 ? "\n" : "") $0 }
          END {
            a = ENVIRON["MSB_A"]; r = ENVIRON["MSB_R"]; s = buf; out = ""; n = 0
            while ((i = index(s, a)) > 0) {
              out = out substr(s, 1, i - 1) r; s = substr(s, i + length(a)); n++
            }
            if (n != 1) exit 3
            printf "%s\n", out s
          }' "$src" > "$src.next"; then
        fail "mutation '$name': its anchor no longer matches exactly once"
        return 0
      fi
      mv "$src.next" "$src"
      shift 2
    done
    MUT_NAMES[NMUT]="$name"; MUT_EXPECT[NMUT]="$expect"; MUT_ONLY[NMUT]="$only"
    MUT_DIRS[NMUT]="$dir"; MUT_TARGETS[NMUT]="$target"
    NMUT=$((NMUT + 1))
  }

  mutation green hook "no-op control (a comment reworded)" "$ALL_SECTIONS" \
    '# Non-blocking: runs sync-push in background.' '# Non-blocking: sync-push runs in background.'
  mutation red push "conflict-marker failure recording" failures \
    'sync_push_record_failure conflict-markers' ':'
  mutation red push "the unmerged-path guard" failures \
    'if [[ -n "$(git ls-files -u 2>/dev/null)" ]]; then' 'if false; then'
  mutation red push "unresolved-conflict failure recording" failures \
    'sync_push_record_failure unresolved-conflict' ':'
  mutation red push "rejected-push failure recording" failures \
    'sync_push_record_failure push-failed' ':'
  mutation red push "success clearing the breaker" failures \
    'sync_push_clear_backoff
exit 0' ':
exit 0'
  mutation red push "stage-failure recording" failures \
    'sync_push_record_failure stage-failed' ':'
  mutation red push "commit-failure recording" failures \
    'sync_push_record_failure commit-failed' ':'
  mutation red push "the offline no-op early exit" delivery \
    'if [[ "$_ahead" -eq 0 && ! -f "$SYNC_PUSH_BACKOFF" ]]; then' 'if false; then'
  mutation red push "the local upstream-ahead check" delivery \
    "_ahead=\$(git rev-list --count '@{u}..HEAD' 2>/dev/null || echo 0)" '_ahead=0'
  mutation red push "backoff permitting an empty-index retry" delivery \
    'if [[ "$_ahead" -eq 0 && ! -f "$SYNC_PUSH_BACKOFF" ]]; then' 'if [[ "$_ahead" -eq 0 ]]; then'
  mutation red push "the unresolved-upstream fallback" delivery \
    "_ahead=\$(git rev-list --count '@{u}..HEAD' 2>/dev/null || echo 0)" \
    "_ahead=\$(git rev-list --count '@{u}..HEAD' 2>/dev/null)"
  mutation red push "an unresolved upstream counting as ahead" delivery \
    "_ahead=\$(git rev-list --count '@{u}..HEAD' 2>/dev/null || echo 0)" \
    "_ahead=\$(git rev-list --count '@{u}..HEAD' 2>/dev/null || echo 1)"
  mutation red hook "the half-open claim" claim \
    'if [[ "$_backoff_half_open" == true ]]; then' 'if false; then'
  mutation red hook "the unwritable-claim degradation" claim \
    '2>/dev/null || {
    rm -f "$_backoff_tmp" 2>/dev/null || true
  }' '2>/dev/null'
  mutation red hook "tripling rather than doubling the window" half_open \
    '_window=$((_window * 2))' '_window=$((_window * 3))'
  mutation red push "the consecutive-failure increment" failures \
    '"$((previous + 1))"' '"1"'
  mutation red hook "the circuit-breaker call" gate \
    'if sync_push_backoff_active; then' 'if false; then'
  mutation red hook "the active-window comparison" gate \
    'if [[ $((_now - _failed_at)) -lt "$_window" ]]; then' 'if false; then'
  mutation red hook "exponential doubling" half_open \
    'while [[ "$_remaining" -gt 0 && "$_window" -lt "$_max" ]]; do' 'while false; do'
  mutation red hook "the maximum-window cap" robustness \
    '[[ "$_window" -gt "$_max" ]] && _window="$_max"' ':'
  mutation red hook "timestamp validation" robustness \
    "case \"\$_failed_at\" in ''|*[!0-9]*) return 1 ;; esac" ':'
  mutation red hook "failure-count validation" robustness \
    "case \"\$_failures\" in ''|*[!0-9]*) return 1 ;; esac" ':'
  mutation red push "the missing-backoff fast path" failures \
    'if [[ -f "$SYNC_PUSH_BACKOFF" ]]; then' 'if true; then'
  mutation red push "reading a final line without a newline" robustness \
    "IFS=' ' read -r ts count old_reason extra < \"\$SYNC_PUSH_BACKOFF\" || true" \
    "IFS=' ' read -r ts count old_reason extra < \"\$SYNC_PUSH_BACKOFF\""
  mutation red push "prior-count validation" robustness \
    "case \"\$count\" in
      ''|*[!0-9]*) ;;
      *) previous=\$count ;;
    esac" 'previous=$count'
  mutation red hook "the missing-file fast path" robustness \
    '[[ -f "$_file" ]] || return 1' ':'
  mutation red hook "the complete-state shape check" robustness \
    '[[ "$_failures" -ge 1 && -n "$_reason" && -z "$_extra" ]] || return 1' ':'
  mutation red hook "base-window validation" robustness \
    "case \"\$_base\" in ''|*[!0-9]*|0) _base=1800 ;; esac" ':'
  mutation red hook "the zero-base guard" robustness \
    '*[!0-9]*|0) _base=1800' '*[!0-9]*) _base=1800'
  mutation red hook "maximum-window validation" robustness \
    "case \"\$_max\" in ''|*[!0-9]*) _max=86400 ;; esac" ':'
  mutation red hook "clock-override validation" robustness \
    "case \"\$_now\" in ''|*[!0-9]*) _now=\$(date +%s) ;; esac" ':'
  mutation red hook "the default 30-minute base" defaults \
    'local _base="${CLADE_SYNC_PUSH_BACKOFF_BASE_SECONDS:-1800}"' \
    'local _base="${CLADE_SYNC_PUSH_BACKOFF_BASE_SECONDS:-60}"'
  mutation red hook "the default 24-hour cap" defaults \
    'local _max="${CLADE_SYNC_PUSH_BACKOFF_MAX_SECONDS:-86400}"' \
    'local _max="${CLADE_SYNC_PUSH_BACKOFF_MAX_SECONDS:-240}"'

  MSB_SELF="$REPO_ROOT/tests/test-memory-sync-breaker.sh"
  local_i=0
  while [[ "$local_i" -lt "$NMUT" ]]; do
    dir="${MUT_DIRS[$local_i]}"
    MSB_MUTANT=1 MSB_SKIP_MUTATIONS=1 MSB_ONLY="${MUT_ONLY[$local_i]}" \
      MSB_HOOK="$dir/hooks/memory-sync.sh" MSB_PUSH="$dir/scripts/sync-push.sh" \
      bash "$MSB_SELF" > "$MUT_DIR/m$local_i.log" 2>&1
    rc=$?
    first=$(grep -m1 '✗' "$MUT_DIR/m$local_i.log" 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g; s/^ *✗ *//')
    if [[ "${MUT_EXPECT[$local_i]}" == "green" ]]; then
      if [[ "$rc" -eq 0 ]]; then
        pass "control: ${MUT_NAMES[$local_i]} leaves the suite green"
      else
        fail "control: ${MUT_NAMES[$local_i]} leaves the suite green" \
          "rc=$rc, first failure: $first"
      fi
    elif [[ "$rc" -ne 0 ]]; then
      pass "without ${MUT_NAMES[$local_i]}: red — ${first:-rc=$rc}"
    else
      fail "without ${MUT_NAMES[$local_i]}: the suite stayed GREEN" "this guard is not checked"
    fi
    local_i=$((local_i + 1))
  done
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ "$TESTS_FAILED" -eq 0 ]]; then
  echo -e "  ${GREEN}ALL PASSED${NC} ($TESTS_PASSED/$TESTS_RUN)"
else
  echo -e "  ${RED}$TESTS_FAILED FAILED${NC} / $TESTS_PASSED passed / $TESTS_RUN total"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
exit "$TESTS_FAILED"
