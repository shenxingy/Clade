#!/usr/bin/env bash
# test-sync-health.sh — wedged sync stores and native MEMORY.md index caps.
#
# Every HOME, bare remote, clone and log is a throwaway fixture. The hook never
# fetches: the behind case makes the remote unreachable after fetching its ref.
#
# Usage:
#   bash tests/test-sync-health.sh
# Internal:
#   SH_HOOK=PATH             test another sync-health.sh
#   SH_ONLY="a b"           run only these sections
#   SH_SKIP_MUTATIONS=1     skip the guard-removal suite
#   SH_MUTANT=1             stop at the first functional failure

# SC2329: sections are called as "t_$name", which shellcheck cannot follow.
# shellcheck disable=SC2329
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK="${SH_HOOK:-$REPO_ROOT/configs/hooks/sync-health.sh}"
HOST_NAME=$(hostname)
NOW=$(date +%s)

unset CLAUDE_CONFIG_DIR CLADE_SYNC_STALE_DAYS CLADE_SYNC_GIT_TIMEOUT CLADE_SYNC_HEALTH_BUDGET
unset CLADE_SYNC_MEMORY_LINE_CAP CLADE_SYNC_MEMORY_BYTE_CAP CLADE_SYNC_MEMORY_WARN_PERCENT
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0 LC_ALL=C

UTF8_LOCALE=""
for CANDIDATE in C.UTF-8 C.utf8 en_US.UTF-8 en_US.utf8; do
  if locale -a 2>/dev/null | grep -qxF "$CANDIDATE"; then
    UTF8_LOCALE=$CANDIDATE
    break
  fi
done

TESTS_RUN=0; TESTS_PASSED=0; TESTS_FAILED=0
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'
pass() { TESTS_RUN=$((TESTS_RUN + 1)); TESTS_PASSED=$((TESTS_PASSED + 1)); echo -e "  ${GREEN}✓${NC} $1"; }
fail() {
  TESTS_RUN=$((TESTS_RUN + 1)); TESTS_FAILED=$((TESTS_FAILED + 1))
  echo -e "  ${RED}✗${NC} $1"
  [[ -n "${2:-}" ]] && echo -e "    ${RED}→ $2${NC}"
  [[ -n "${SH_MUTANT:-}" ]] && exit 1
  return 0
}
section() { echo ""; echo -e "${YELLOW}━━━ $1 ━━━${NC}"; }
assert_eq() {
  if [[ "$1" == "$2" ]]; then pass "$3"; else fail "$3" "got '$1', want '$2'"; fi
}
assert_contains() {
  if grep -qF -- "$2" <<< "$1"; then pass "$3"
  else fail "$3" "output does not contain '$2'; output: $(head -8 <<< "$1")"; fi
}
assert_not_contains() {
  if grep -qF -- "$2" <<< "$1"; then
    fail "$3" "output unexpectedly contains '$2'; output: $(head -8 <<< "$1")"
  else pass "$3"; fi
}
assert_empty() {
  if [[ -z "$1" ]]; then pass "$2"; else fail "$2" "output: $(head -8 <<< "$1")"; fi
}

if ! command -v git >/dev/null 2>&1; then
  echo "git is required for the sync-store fixtures" >&2
  exit 1
fi

SANDBOX=$(mktemp -d "${TMPDIR:-/tmp}/sync-health-test.XXXXXX") || exit 1
trap 'rm -rf "$SANDBOX"' EXIT
NHOME=0
H=""; STORE=""; REMOTE=""

new_store() {
  NHOME=$((NHOME + 1))
  H="$SANDBOX/home$NHOME"
  STORE="$H/store"
  REMOTE="$H/remote.git"
  mkdir -p "$H/.claude"
  git init -q --bare "$REMOTE"
  git --git-dir="$REMOTE" symbolic-ref HEAD refs/heads/main
  git clone -q "$REMOTE" "$STORE" 2>/dev/null
  git -C "$STORE" config user.email sync-health@example.com
  git -C "$STORE" config user.name sync-health-fixture
  git -C "$STORE" config core.hooksPath /dev/null
  mkdir -p "$STORE/projects-memory/healthy"
  printf 'store\n' > "$STORE/README"
  printf '# small memory\n' > "$STORE/projects-memory/healthy/MEMORY.md"
  git -C "$STORE" add -A
  git -C "$STORE" commit -qm base
  git -C "$STORE" push -qu origin HEAD
  printf 'SYNC_BACKEND=github\nSYNC_DIR=%s\n' "$STORE" > "$H/.claude/.sync-config"
}

host_commit() {
  local dir=$1 epoch=${2:-}
  if [[ -n "$epoch" ]]; then
    GIT_AUTHOR_DATE="@$epoch +0000" GIT_COMMITTER_DATE="@$epoch +0000" \
      git -C "$dir" commit -q --allow-empty -m "sync: $HOST_NAME 00:00"
  else
    git -C "$dir" commit -q --allow-empty -m "sync: $HOST_NAME 00:00"
  fi
}

run_health() {
  local home=$1
  shift
  HOME="$home" env "$@" bash "$HOOK" 2>"$home/.claude/stderr"
}

health_log() {
  if [[ -f "$H/.claude/.sync-health.log" ]]; then
    cat "$H/.claude/.sync-health.log"
  fi
}

refused_line() {
  local stamp=${1:-$(date)}
  printf '[%s] sync-push REFUSED: conflict markers in corrections/rules.md\n' "$stamp" \
    >> "$H/.claude/.sync-conflicts.log"
}

write_sized_file() {
  local file=$1 bytes=$2
  mkdir -p "$(dirname "$file")"
  head -c "$bytes" < /dev/zero | tr '\0' 'x' > "$file"
}

write_lined_file() {
  local file=$1 lines=$2
  mkdir -p "$(dirname "$file")"
  awk -v n="$lines" 'BEGIN { for (i = 0; i < n; i++) print "x" }' > "$file"
}

make_unmerged() {
  local dir=$1
  shift
  for f in "$@"; do printf 'base\n' > "$dir/$f"; done
  git -C "$dir" add -A && git -C "$dir" commit -qm base-files
  for f in "$@"; do printf 'local\n' > "$dir/$f"; done
  git -C "$dir" add -A && git -C "$dir" commit -qm local
  git -C "$dir" checkout -qb conflicting-side HEAD~1
  for f in "$@"; do printf 'other\n' > "$dir/$f"; done
  git -C "$dir" add -A && git -C "$dir" commit -qm other
  git -C "$dir" checkout -q main
  git -C "$dir" merge conflicting-side >/dev/null 2>&1 || true
}

stamp_for_epoch() {
  local dir=$1 epoch=$2 commit
  commit=$(printf 'timestamp fixture\n' | \
    GIT_AUTHOR_DATE="@$epoch +0000" GIT_COMMITTER_DATE="@$epoch +0000" \
    git -C "$dir" commit-tree 'HEAD^{tree}')
  git -C "$dir" show -s --format=%ad --date=default "$commit"
}

t_healthy() {
  section "healthy — a clean, current store is silent"
  new_store
  OUT=$(run_health "$H")
  assert_eq "$?" "0" "healthy hook exits zero"
  assert_empty "$OUT" "healthy store emits none of the new stdout warnings"
  if [[ ! -f "$H/.claude/.sync-health.log" ]]; then
    pass "healthy store appends no health log"
  else
    fail "healthy store appends no health log" "$(cat "$H/.claude/.sync-health.log")"
  fi
}

t_unmerged() {
  section "unmerged — count unique index paths and show only the first few"
  new_store
  make_unmerged "$STORE" a.txt b.txt c.txt d.txt

  OUT=$(run_health "$H")
  assert_eq "$?" "0" "unmerged hook exits zero"
  assert_contains "$OUT" "4 unmerged paths" "four conflicted paths are counted once, not once per index stage"
  LINE=$(grep 'unmerged paths' <<< "$OUT")
  assert_contains "$LINE" "a.txt, b.txt, c.txt" "the first three unmerged paths are named on one line"
  assert_not_contains "$LINE" "d.txt" "the path preview stays bounded"
  assert_eq "$(grep -c 'unmerged paths' <<< "$OUT")" "1" "unmerged paths produce exactly one stdout line"
  assert_contains "$(health_log)" "4 unmerged paths" "unmerged warning reaches the health log"
}

t_autostash() {
  section "autostash — a leftover pull stash names the mid-pop state"
  new_store
  printf 'dirty\n' >> "$STORE/README"
  git -C "$STORE" stash push -qm 'pull --rebase --autostash'
  OUT=$(run_health "$H")
  assert_eq "$?" "0" "autostash hook exits zero"
  assert_contains "$OUT" "leftover autostash" "an autostash stash entry is reported"
  assert_contains "$OUT" "pull --autostash was left mid-pop" "the warning explains the interrupted pull"
  assert_eq "$(grep -c 'leftover autostash' <<< "$OUT")" "1" "autostash produces exactly one stdout line"
  assert_contains "$(health_log)" "leftover autostash" "autostash warning reaches the health log"
}

t_stale() {
  section "stale — host commit age, never-synced changes, and env override"
  new_store
  host_commit "$STORE" "$((NOW - 10 * 86400))"
  git -C "$STORE" push -q
  OUT=$(run_health "$H")
  assert_contains "$OUT" "last sync commit by $HOST_NAME was 10 days ago" "an old host commit is reported even when pushed"
  assert_contains "$OUT" "threshold: 7 days" "the stale warning names its default threshold"
  assert_contains "$(health_log)" "last sync commit by $HOST_NAME" "stale warning reaches the health log"
  OUT=$(run_health "$H" CLADE_SYNC_STALE_DAYS=11)
  assert_not_contains "$OUT" "last sync commit" "CLADE_SYNC_STALE_DAYS overrides the stale threshold"

  new_store
  printf 'unsynced\n' >> "$STORE/README"
  OUT=$(run_health "$H")
  assert_contains "$OUT" "this host has never made a sync commit" "a first-time host with local changes says it has never synced"
  assert_eq "$(grep -c 'never made a sync commit' <<< "$OUT")" "1" "never-synced is one line, not an epoch-age calculation"

  new_store
  host_commit "$STORE" "$((NOW - 2 * 86400))"
  git -C "$STORE" push -q
  OUT=$(run_health "$H")
  assert_not_contains "$OUT" "last sync commit" "a recent host commit is silent"

  new_store
  host_commit "$STORE" "$((NOW - 10 * 86400))"
  GIT_AUTHOR_DATE="@$NOW +0000" GIT_COMMITTER_DATE="@$NOW +0000" \
    git -C "$STORE" commit -q --allow-empty -m 'sync: other-host 00:00'
  git -C "$STORE" push -q
  OUT=$(run_health "$H")
  assert_contains "$OUT" "last sync commit by $HOST_NAME was 10 days ago" "another host's newer sync commit does not hide this host's stale commit"
}

t_refused() {
  section "refused — trailing streak, non-refusal reset, and commit-time reset"
  new_store
  refused_line; refused_line
  OUT=$(run_health "$H")
  assert_not_contains "$OUT" "REFUSED streak" "two trailing refusals stay below the threshold"
  refused_line
  OUT=$(run_health "$H")
  assert_contains "$OUT" "REFUSED streak: 3" "three trailing refusals produce their count"
  assert_eq "$(grep -c 'REFUSED streak' <<< "$OUT")" "1" "REFUSED streak produces exactly one stdout line"
  assert_contains "$(health_log)" "REFUSED streak: 3" "REFUSED warning reaches the health log"

  printf '[%s] sync conflict resolved\n' "$(date)" >> "$H/.claude/.sync-conflicts.log"
  OUT=$(run_health "$H")
  assert_not_contains "$OUT" "REFUSED streak" "a non-REFUSED line ends the trailing streak"

  : > "$H/.claude/.sync-conflicts.log"
  refused_line; refused_line; refused_line
  host_commit "$STORE"
  git -C "$STORE" push -q
  OUT=$(run_health "$H")
  assert_not_contains "$OUT" "REFUSED streak" "a host sync commit at or after the last refusal resets the streak"

  new_store
  host_commit "$STORE" "$((NOW - 7200))"
  OLD_STAMP=$(git -C "$STORE" show -s --format=%cd --date=default HEAD)
  refused_line "$OLD_STAMP"; refused_line "$OLD_STAMP"; refused_line "$OLD_STAMP"
  host_commit "$STORE" "$((NOW - 3600))"
  refused_line; refused_line; refused_line
  OUT=$(run_health "$H")
  assert_contains "$OUT" "REFUSED streak: 3" "only refusals after the last host commit remain in the streak"

  new_store
  refused_line; refused_line; refused_line
  git -C "$STORE" commit -q --allow-empty -m 'sync: other-host 00:00'
  git -C "$STORE" push -q
  OUT=$(run_health "$H")
  assert_contains "$OUT" "REFUSED streak: 3" "another host's sync commit does not reset this host's refusal streak"

  new_store
  ZH_STAMP='2026年 11月 07日 星期六 10:13:57 CST'
  refused_line "$ZH_STAMP"; refused_line "$ZH_STAMP"; refused_line "$ZH_STAMP"
  host_commit "$STORE"
  git -C "$STORE" push -q
  if [[ -n "$UTF8_LOCALE" ]]; then
    OUT=$(run_health "$H" LC_ALL="$UTF8_LOCALE")
    assert_contains "$OUT" "REFUSED streak: 3" "a non-ASCII refusal timestamp fails toward reporting under $UTF8_LOCALE"
  else
    fail "non-ASCII timestamp behavior under UTF-8" "NOT MEASURED: no C.UTF-8, C.utf8, en_US.UTF-8 or en_US.utf8 locale exists"
  fi
}

t_remote() {
  section "remote — fetched behind count and stale unpushed ahead count"
  new_store
  PEER="$H/peer"
  git clone -q "$REMOTE" "$PEER"
  git -C "$PEER" config user.email peer@example.com
  git -C "$PEER" config user.name peer
  printf 'remote\n' > "$PEER/remote.txt"
  git -C "$PEER" add -A && git -C "$PEER" commit -qm remote
  git -C "$PEER" push -q
  git -C "$STORE" fetch -q origin
  git -C "$STORE" remote set-url origin "$H/no-such-remote"
  OUT=$(run_health "$H")
  assert_contains "$OUT" "1 commit(s) behind upstream" "the already-fetched upstream ref reports behind work"
  assert_contains "$OUT" "no fetch" "the behind warning makes the offline guarantee visible"
  assert_contains "$(health_log)" "behind upstream" "behind warning reaches the health log"

  new_store
  host_commit "$STORE" "$((NOW - 10 * 86400))"
  OUT=$(run_health "$H")
  assert_contains "$OUT" "1 commit(s) ahead of upstream" "old ahead work is reported as unpushed"
  assert_contains "$OUT" "unpushed work" "the ahead warning explains why it matters"
  assert_contains "$(health_log)" "ahead of upstream" "ahead warning reaches the health log"

  PEER="$H/peer"
  git clone -q "$REMOTE" "$PEER"
  git -C "$PEER" config user.email peer@example.com
  git -C "$PEER" config user.name peer
  printf 'divergent\n' > "$PEER/divergent.txt"
  git -C "$PEER" add -A && git -C "$PEER" commit -qm divergent
  git -C "$PEER" push -q
  git -C "$STORE" fetch -q origin
  OUT=$(run_health "$H")
  assert_contains "$OUT" "behind upstream" "a diverged store still names its behind count"
  assert_contains "$OUT" "ahead of upstream" "a diverged store still names its stale ahead count"
  assert_eq "$(grep -c 'upstream' <<< "$OUT")" "1" "behind and ahead share one remote-status stdout line"

  new_store
  host_commit "$STORE" "$((NOW - 9 * 86400))"
  host_commit "$STORE" "$((NOW - 5 * 86400))"
  host_commit "$STORE" "$((NOW - 3600))"
  OUT=$(run_health "$H")
  assert_contains "$OUT" "3 commit(s) ahead of upstream" "daily fresh commits do not hide three unpushed commits"
  assert_contains "$OUT" "oldest unpushed commit is 9 days old" "ahead age comes from the oldest, not newest, unpushed commit"
  assert_eq "$(grep -c 'ahead of upstream' <<< "$OUT")" "1" "the ageing unpushed run produces one ahead line"

  new_store
  host_commit "$STORE" "$((NOW - 5 * 86400))"
  host_commit "$STORE" "$((NOW - 2 * 86400))"
  host_commit "$STORE" "$((NOW - 3600))"
  OUT=$(run_health "$H")
  assert_not_contains "$OUT" "ahead of upstream" "an unpushed run whose oldest commit is young stays silent"
}

t_rebase() {
  section "rebase — rewritten committer dates do not erase sync age or refusals"
  new_store
  host_commit "$STORE" "$((NOW - 9 * 86400))"
  for DAYS in 8 6 4; do
    STAMP=$(stamp_for_epoch "$STORE" "$((NOW - DAYS * 86400))")
    refused_line "$STAMP"
  done
  PEER="$H/peer"
  git clone -q "$REMOTE" "$PEER"
  git -C "$PEER" config user.email peer@example.com
  git -C "$PEER" config user.name peer
  printf 'peer\n' > "$PEER/peer.txt"
  git -C "$PEER" add -A && git -C "$PEER" commit -qm peer
  git -C "$PEER" push -q
  git -C "$STORE" pull -q --rebase
  assert_eq "$(git -C "$STORE" log -1 --format=%at)" "$((NOW - 9 * 86400))" "fixture rebase preserves the old author date"
  if [[ "$(git -C "$STORE" log -1 --format=%ct)" -gt "$(git -C "$STORE" log -1 --format=%at)" ]]; then
    pass "fixture rebase rewrites the committer date"
  else
    fail "fixture rebase rewrites the committer date" "author and committer dates did not diverge"
  fi

  OUT=$(run_health "$H")
  assert_contains "$OUT" "last sync commit by $HOST_NAME was 9 days ago" "rebase does not hide this host's stale sync commit"
  assert_contains "$OUT" "REFUSED streak: 3" "rebase does not move the last host commit past the refusal timestamps"
  assert_contains "$OUT" "1 commit(s) ahead of upstream; oldest unpushed commit is 9 days old" "rebase does not make the unpushed work look fresh"
}

t_index() {
  section "index — 79 percent is silent, 80 percent of either native cap warns"
  new_store
  MEM="$H/.claude/projects/demo/memory/MEMORY.md"
  write_lined_file "$MEM" 158
  OUT=$(run_health "$H")
  assert_not_contains "$OUT" "MEMORY.md index cap" "158 lines (79 percent of 200) is silent"
  write_lined_file "$MEM" 160
  OUT=$(run_health "$H")
  assert_contains "$OUT" "MEMORY.md index cap" "160 lines (80 percent of 200) warns"
  assert_contains "$OUT" "160 lines" "the index warning names the line count"
  assert_contains "$OUT" "KB" "the index warning names the byte count in KB"
  assert_contains "$OUT" "$MEM" "the index warning names the file"
  assert_eq "$(grep -c 'MEMORY.md index cap' <<< "$OUT")" "1" "one index warning is one stdout line"
  assert_contains "$(health_log)" "MEMORY.md index cap" "index warning reaches the health log"
  OUT=$(run_health "$H" CLADE_SYNC_MEMORY_WARN_PERCENT=90)
  assert_not_contains "$OUT" "MEMORY.md index cap" "the index warning percentage is env-overridable"
  OUT=$(run_health "$H" CLADE_SYNC_MEMORY_LINE_CAP=100 CLADE_SYNC_MEMORY_WARN_PERCENT=80)
  assert_contains "$OUT" "MEMORY.md index cap" "the native line cap is env-overridable for fixtures"

  new_store
  MEM="$H/.claude/projects/bytes/memory/MEMORY.md"
  write_sized_file "$MEM" 20224
  OUT=$(run_health "$H")
  assert_not_contains "$OUT" "MEMORY.md index cap" "20224 bytes (79 percent of 25 KiB) is silent"
  write_sized_file "$MEM" 20480
  OUT=$(run_health "$H")
  assert_contains "$OUT" "20.0 KB" "20480 bytes (80 percent of 25 KiB) warns with its KB size"
  OUT=$(run_health "$H" CLADE_SYNC_MEMORY_BYTE_CAP=40960)
  assert_not_contains "$OUT" "MEMORY.md index cap" "the native byte cap is env-overridable for fixtures"

  new_store
  STORE_MEM="$STORE/projects-memory/healthy/MEMORY.md"
  PROFILE_MEM="$H/.claude-profiles/work/projects/demo/memory/MEMORY.md"
  write_lined_file "$STORE_MEM" 160
  write_lined_file "$PROFILE_MEM" 160
  mkdir -p "$H/.claude/projects/linked" "$H/.claude-profiles/p1/projects/linked" "$H/.claude-profiles/p2/projects/linked" \
    "$H/.claude/projects/file-link/memory"
  ln -s "$STORE/projects-memory/healthy" "$H/.claude/projects/linked/memory"
  ln -s "$STORE/projects-memory/healthy" "$H/.claude-profiles/p1/projects/linked/memory"
  ln -s "$STORE/projects-memory/healthy" "$H/.claude-profiles/p2/projects/linked/memory"
  ln -s "$STORE_MEM" "$H/.claude/projects/file-link/memory/MEMORY.md"
  git -C "$STORE" add -A && git -C "$STORE" commit -qm large-memories
  git -C "$STORE" push -q
  OUT=$(run_health "$H")
  assert_contains "$OUT" "$STORE_MEM" "the store's physical path names the shared memory"
  assert_contains "$OUT" "$PROFILE_MEM" "a real non-symlinked profile memory keeps its own warning"
  assert_eq "$(grep 'MEMORY.md index cap' <<< "$OUT" | grep -c "$STORE_MEM")" "1" "store memory plus three links produces exactly one store line"
  assert_eq "$(grep -c 'MEMORY.md index cap' <<< "$OUT")" "2" "two physical over-cap files produce two lines, not five"

  new_store
  rm "$H/.claude/.sync-config"
  MEM="$H/.claude/projects/no-config/memory/MEMORY.md"
  write_lined_file "$MEM" 158
  OUT=$(run_health "$H")
  assert_not_contains "$OUT" "MEMORY.md index cap" "without a sync config, 158 lines stays silent"
  write_lined_file "$MEM" 160
  OUT=$(run_health "$H")
  assert_contains "$OUT" "$MEM" "without a sync config, a real local memory is still watched"
  assert_eq "$(grep -c 'MEMORY.md index cap' <<< "$OUT")" "1" "the no-config index watch produces one line"
  OUT=$(run_health "$H")
  assert_not_contains "$(cat "$H/.claude/stderr")" ".sync-config is missing" "a second no-config session does not invent a prior sync setup"
  if [[ ! -f "$H/.claude/.sync-health.log" ]]; then
    pass "no-config index warnings never create the Case-1 health-log heuristic"
  else
    fail "no-config index warnings never create the Case-1 health-log heuristic" "log exists: $(cat "$H/.claude/.sync-health.log")"
  fi
}

t_robustness() {
  section "robustness — lock-free probes, portable watchdogs, and a whole-hook deadline"
  new_store
  mv "$STORE/.git" "$H/store-git-metadata"
  BIN="$H/git-log-bin"
  mkdir -p "$BIN"
  REAL_GIT=$(command -v git)
  cat > "$BIN/git" <<EOF
#!/bin/sh
printf '%s|%s\n' "\${GIT_OPTIONAL_LOCKS:-unset}" "\$*" >> '$H/git-calls'
exec '$REAL_GIT' "\$@"
EOF
  chmod +x "$BIN/git"
  refused_line; refused_line; refused_line
  OUT=$(run_health "$H" PATH="$BIN:$PATH")
  assert_empty "$OUT" "a non-git SYNC_DIR skips all store wedge warnings"
  CALLS=$(cat "$H/git-calls")
  assert_contains "$CALLS" "rev-parse" "the repository probe still runs"
  assert_not_contains "$CALLS" "ls-files" "a non-git store never probes the index"
  assert_not_contains "$CALLS" "stash" "a non-git store never probes stashes"
  assert_not_contains "$CALLS" "rev-list" "a non-git store never probes upstream"
  assert_contains "$CALLS" "0|" "the repository probe disables optional locks"
  assert_not_contains "$CALLS" "unset" "no git probe may take the shared store's optional index lock"

  new_store
  BIN="$H/slow-git-bin"
  mkdir -p "$BIN"
  cat > "$BIN/git" <<'EOF'
#!/bin/sh
exec sleep 5
EOF
  chmod +x "$BIN/git"
  START=$SECONDS
  OUT=$(run_health "$H" PATH="$BIN:$PATH" CLADE_SYNC_GIT_TIMEOUT=1)
  ELAPSED=$((SECONDS - START))
  if [[ "$ELAPSED" -le 3 ]]; then
    pass "a hung git probe is cut off (${ELAPSED}s)"
  else
    fail "a hung git probe is cut off" "took ${ELAPSED}s"
  fi
  assert_contains "$OUT" "store checks cut short" "a timed-out repository probe says the store checks were cut short"
  assert_eq "$(grep -c 'store checks cut short' <<< "$OUT")" "1" "a repository-probe timeout produces one cut-short line"

  new_store
  make_unmerged "$STORE" a b
  BIN="$H/no-timeout-bin"
  mkdir -p "$BIN"
  for cmd in bash awk date grep head hostname sed stat wc git sleep tr; do
    ln -s "$(command -v "$cmd")" "$BIN/$cmd"
  done
  START=$SECONDS
  OUT=$(run_health "$H" PATH="$BIN" CLADE_SYNC_GIT_TIMEOUT=3)
  RC=$?
  ELAPSED=$((SECONDS - START))
  assert_eq "$RC" "0" "without timeout or gtimeout the hook itself still runs and exits zero"
  assert_contains "$OUT" "2 unmerged paths" "the bash watchdog still reports a wedged store without timeout or gtimeout"
  if [[ "$ELAPSED" -le 2 ]]; then
    pass "fast no-timeout probes reap their watchdogs immediately (${ELAPSED}s)"
  else
    fail "fast no-timeout probes reap their watchdogs immediately" "took ${ELAPSED}s"
  fi

  new_store
  BIN="$H/no-timeout-slow-bin"
  mkdir -p "$BIN"
  for cmd in bash awk date grep head hostname sed stat wc sleep tr; do
    ln -s "$(command -v "$cmd")" "$BIN/$cmd"
  done
  cat > "$BIN/git" <<'EOF'
#!/bin/sh
exec sleep 5
EOF
  chmod +x "$BIN/git"
  START=$SECONDS
  OUT=$(run_health "$H" PATH="$BIN" CLADE_SYNC_GIT_TIMEOUT=1)
  ELAPSED=$((SECONDS - START))
  if [[ "$ELAPSED" -le 3 ]]; then
    pass "the no-timeout watchdog kills a hung git probe (${ELAPSED}s)"
  else
    fail "the no-timeout watchdog kills a hung git probe" "took ${ELAPSED}s"
  fi
  assert_contains "$OUT" "store checks cut short" "a watchdog-killed repository probe reports the cut-short state"
  assert_eq "$(grep -c 'store checks cut short' <<< "$OUT")" "1" "the fallback repository timeout also produces one line"

  new_store
  printf 'project/memory.md\n' > "$H/.claude/.sync-memory-conflicts"
  BIN="$H/slow-real-git-bin"
  mkdir -p "$BIN"
  cat > "$BIN/git" <<EOF
#!/bin/sh
sleep 1
exec '$REAL_GIT' "\$@"
EOF
  chmod +x "$BIN/git"
  START=$SECONDS
  OUT=$(run_health "$H" PATH="$BIN:$PATH" CLADE_SYNC_HEALTH_BUDGET=3)
  RC=$?
  ELAPSED=$((SECONDS - START))
  assert_eq "$RC" "0" "a slow-but-alive store still lets the hook exit cleanly"
  if [[ "$ELAPSED" -le 4 ]]; then
    pass "the whole-hook deadline stops successive slow probes (${ELAPSED}s)"
  else
    fail "the whole-hook deadline stops successive slow probes" "took ${ELAPSED}s"
  fi
  assert_contains "$OUT" "project memory conflict" "the deadline preserves the earlier memory-conflict output"
  assert_contains "$OUT" "store checks cut short" "the whole-hook deadline reports that later probes were skipped"
}

ALL_SECTIONS="healthy unmerged autostash stale refused remote rebase index robustness"
for NAME in ${SH_ONLY:-$ALL_SECTIONS}; do
  "t_$NAME"
done

if [[ -z "${SH_SKIP_MUTATIONS:-}" ]]; then
  section "mutations — removing a new guard must turn its section red"

  MUT_DIR="$SANDBOX/mutants"
  mkdir -p "$MUT_DIR"
  NMUT=0
  MUT_NAMES=(); MUT_EXPECT=(); MUT_ONLY=()
  mutation() {
    local expect=$1 name=$2 only=$3 dir="$MUT_DIR/m$NMUT"
    if ! SH_A="$4" SH_R="$5" awk '
        {buf = buf (NR > 1 ? "\n" : "") $0}
        END {
          a = ENVIRON["SH_A"]; r = ENVIRON["SH_R"]; s = buf; out = ""; n = 0
          while ((i = index(s, a)) > 0) {
            out = out substr(s, 1, i - 1) r
            s = substr(s, i + length(a)); n++
          }
          if (n != 1) exit 3
          printf "%s\n", out s
        }' "$HOOK" > "$dir.sh"; then
      fail "mutation '$name': its anchor no longer matches exactly once"
      return 0
    fi
    MUT_NAMES[NMUT]=$name; MUT_EXPECT[NMUT]=$expect; MUT_ONLY[NMUT]=$only
    NMUT=$((NMUT + 1))
  }

  mutation green "no-op control (a comment reworded)" "$ALL_SECTIONS" \
    '# Case 5: ls-files -u' '# Case 5 (control): ls-files -u'
  mutation red "the unmerged-path guard" unmerged \
    'if [[ -n "$UNMERGED" ]]; then' 'if false; then'
  mutation red "unique unmerged paths" unmerged \
    'NF >= 2 && !seen[$2]++' 'NF >= 2'
  mutation red "the bounded unmerged-path preview" unmerged \
    'NR <= 3' 'NR <= 4'
  mutation red "the autostash guard" autostash \
    "if grep -qi 'autostash' <<< \"\$STASHES\"; then" 'if false; then'
  mutation red "the stale-commit threshold" stale \
    'if [[ "$SYNC_AGE_DAYS" -ge "$STALE_DAYS" ]]; then' 'if false; then'
  mutation red "the never-synced local-change guard" stale \
    'if [[ -n "$LOCAL_STATUS" ]]; then' 'if false; then'
  mutation red "the stale threshold override" stale \
    'STALE_DAYS="${CLADE_SYNC_STALE_DAYS:-7}"' 'STALE_DAYS=7'
  mutation red "the this-host commit filter" "stale refused" \
    '--grep="^sync: $HOST_NAME "' '--grep="^sync: "'
  mutation red "the REFUSED threshold" refused \
    'if [[ "$REFUSED_COUNT" -ge 3 ]]; then' 'if false; then'
  mutation red "the REFUSED commit-time reset" refused \
    'if [[ "$REFUSED_COUNT" -ge 3 && "$LAST_SYNC" =~ ^[0-9]+$ ]]; then' 'if false; then'
  mutation red "the non-REFUSED streak reset" refused \
    '{buf = ""}' '{buf = buf $0 ORS}'
  mutation red "the non-ASCII timestamp guard" refused \
    "  [[ -z \"\$(printf '%s' \"\$stamp\" | LC_ALL=C tr -d '\\040-\\176')\" ]] || return 1" '  :'
  mutation red "the behind-upstream guard" remote \
    'if [[ "$BEHIND" =~ ^[0-9]+$ && "$BEHIND" -gt 0 ]]; then' 'if false; then'
  mutation red "the stale-ahead guard" remote \
    'if [[ "$AHEAD" =~ ^[0-9]+$ && "$AHEAD" -gt 0 ]]; then' 'if false; then'
  mutation red "the oldest-unpushed age threshold" remote \
    'if [[ "$AHEAD_AGE_DAYS" -ge "$STALE_DAYS" ]]; then' 'if false; then'
  mutation red "the oldest-unpushed timestamp selection" remote \
    'NF {last = $1}' 'NR == 1 {last = $1}'
  mutation red "the last-sync author date" rebase \
    'log -1 --format=%at --grep=' 'log -1 --format=%ct --grep='
  mutation red "the oldest-unpushed author dates" rebase \
    "log --format=%at '@{upstream}..HEAD'" "log --format=%ct '@{upstream}..HEAD'"
  mutation red "the index line-cap branch" index \
    'if [[ $((MEMORY_LINES * 100)) -ge $((MEMORY_WARN_PERCENT * MEMORY_LINE_CAP)) || \' 'if [[ 1 -eq 0 || \'
  mutation red "the index byte-cap branch" index \
    '$((MEMORY_BYTES * 100)) -ge $((MEMORY_WARN_PERCENT * MEMORY_BYTE_CAP)) ]]; then' '1 -eq 0 ]]; then'
  mutation red "the physical-memory dedupe" index \
    "  case \"\$MEMORY_SEEN\" in
    *\$'\\n'\"\$MEMORY_PHYSICAL\"\$'\\n'*) continue ;;
  esac" '  :'
  mutation red "the symlinked-file exclusion" index \
    '[[ -f "$MEMORY_FILE" && ! -L "$MEMORY_FILE" ]] || continue' '[[ -f "$MEMORY_FILE" ]] || continue'
  mutation red "the configured-store guard" index \
    'if [[ -f "$SYNC_CONFIG" ]]; then
# shellcheck source=/dev/null
source "$SYNC_CONFIG"' 'if true; then
# shellcheck source=/dev/null
source "$SYNC_CONFIG"'
  mutation red "the no-config index log guard" index \
    '    if [[ -f "$SYNC_CONFIG" ]]; then
      notice "MEMORY.md index cap:' '    if true; then
      notice "MEMORY.md index cap:'
  mutation red "the repository guard" robustness \
    'if [[ "$IS_REPO" == "true" ]]; then' 'if true; then'
  mutation red "the git timeout" robustness \
    '    timeout "$limit" git -C "$SYNC_DIR" "$@"' '    git -C "$SYNC_DIR" "$@"'
  mutation red "the watchdog kill" robustness \
    '    kill -TERM "$watchdog" 2>/dev/null || true' '    :'
  mutation red "the watchdog redirect" robustness \
    '    ( sleep "$limit"; kill -TERM "$pid" ) >/dev/null 2>&1 &' '    ( sleep "$limit"; kill -TERM "$pid" ) &'
  mutation red "the fallback timeout status" robustness \
    '    [[ "$rc" -ne 143 ]] || rc=124' '    :'
  mutation red "the whole-hook deadline" robustness \
    '  [[ "$remaining" -gt 0 ]] || return 125' '  remaining=99'
  mutation red "the cut-short notice" robustness \
    '  if [[ "$REPO_PROBE_RC" -eq 124 || "$REPO_PROBE_RC" -eq 125 || "$(date +%s)" -ge "$HOOK_DEADLINE" ]]; then' '  if false; then'
  mutation red "the optional-lock guard" robustness \
    '  export GIT_OPTIONAL_LOCKS=0' '  :'
  mutation red "new notices appending to the health log" unmerged \
    "notice() {
  local msg=\"\$1\"
  echo \"[sync-health] \$msg\"
  echo \"[\$(date '+%Y-%m-%d %H:%M:%S')] \$msg\" >> \"\$LOG\"
}" "notice() {
  local msg=\"\$1\"
  echo \"[sync-health] \$msg\"
}"

  I=0
  while [[ "$I" -lt "$NMUT" ]]; do
    SH_HOOK="$MUT_DIR/m$I.sh" SH_ONLY="${MUT_ONLY[$I]}" SH_SKIP_MUTATIONS=1 SH_MUTANT=1 \
      bash "$REPO_ROOT/tests/test-sync-health.sh" > "$MUT_DIR/m$I.log" 2>&1
    RC=$?
    FIRST=$(grep -m1 '✗' "$MUT_DIR/m$I.log" 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g; s/^ *✗ *//')
    if [[ "${MUT_EXPECT[$I]}" == "green" ]]; then
      if [[ "$RC" -eq 0 ]]; then pass "control: ${MUT_NAMES[$I]} leaves the suite green"
      else fail "control: ${MUT_NAMES[$I]} leaves the suite green" "rc=$RC, first failure: $FIRST"; fi
    elif [[ "$RC" -ne 0 ]]; then
      pass "without ${MUT_NAMES[$I]}: red — ${FIRST:-rc=$RC}"
    else
      fail "without ${MUT_NAMES[$I]}: the suite stayed GREEN" "this guard is claimed and not checked"
    fi
    I=$((I + 1))
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
