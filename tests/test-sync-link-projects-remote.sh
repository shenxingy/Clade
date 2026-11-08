#!/usr/bin/env bash
# test-sync-link-projects-remote.sh — multi-checkout and discovery regressions.
#
# Sections (SLPR_ONLY="checkouts ..." selects a subset):
#   checkouts  two legacy links and two real memory dirs at one origin on one
#              host all stay linked, including a later write; run two is quiet
#   discovery  one origin index per run, non-HOME slugs skipped before decode,
#              and a per-slug budget whose incomplete-index misses defer and resume
#   dryrun     an existing remote entry gains no .project-paths under --dry-run,
#              either through discovery or migration into that entry
#   identity   remote/key mismatches are left alone in link and prune; repo
#              subdirectories and linked worktrees keep path keys
#
# The mutation suite removes recorded and unrecorded checkout retention, the
# shared discovery index, HOME-prefix filter, per-slug budget, final-newline
# guard, planned-destination conflict check, record_host_path dry-run guard,
# link and prune remote/key checks, and the repository-root identity guard.
# Each must make its section fail. A no-op control must stay green. Every
# fixture uses a temporary HOME and git store.
#
# SLP_SCRIPTS_DIR selects a copy of the linker (for pre-fix red proofs).
# SLPR_SKIP_MUTATIONS=1 runs behavior only; SLPR_JOBS caps parallel mutants.

set -uo pipefail
SLP_LIBRARY=1
# shellcheck source=tests/test-sync-link-projects.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/test-sync-link-projects.sh"
SLP_MUTANT="${SLPR_MUTANT:-}"

REAL_GIT=$(command -v git)
cat > "$SHIMBIN/git" <<EOF
#!/bin/sh
case "\${SLP_SHIM_MODE:-}" in
  all|count|slow)
    if [ "\$1" = -C ]; then printf '%s\t%s\n' "\$2" "\$3 \$4 \$5" >> "$SANDBOX/git-all.log"; fi
    ;;
esac
case "\${SLP_SHIM_MODE:-}:\$1:\$3:\$4" in
  count:-C:remote:get-url) printf '%s\n' "\$2" >> "$SANDBOX/git-count.log" ;;
  slow:-C:rev-parse:--show-toplevel) sleep 2 ;;
  slow:-C:remote:get-url) sleep 2 ;;
esac
exec "$REAL_GIT" "\$@"
EOF
chmod +x "$SHIMBIN/git"

assert_both_linked() {
  local entry=$1 first=$2 second=$3 run=$4
  assert_eq "$(target_of "$first")" "$entry" "first checkout stays linked ($run)"
  assert_eq "$(target_of "$second")" "$entry" "second checkout stays linked ($run)"
}

two_legacy_entries() {
  new_home
  PM="$H/store/projects-memory"; RK=$(remote_key_of 'github.com/scamai/internal'); E="$PM/$RK"
  L1="$PM/projects-internal"; L2="$PM/shared-nfs-internal"
  for p in projects/internal shared-nfs/internal; do
    git_repo "$H/$p"; git -C "$H/$p" remote add origin git@github.com:scamai/internal.git
    k=$(slug_of "$p"); mkdir -p "$PM/$k"; printf '%s\n' "$p" > "$PM/$k/.project-path"
    m=$(memdir "$H" "$H/$p"); mkdir -p "${m%/memory}"; ln -s "$PM/$k" "$m"
  done
  M1=$(memdir "$H" "$H/projects/internal"); M2=$(memdir "$H" "$H/shared-nfs/internal")
}

migration_keys() {
  sed -n -e 's/^  would migrate projects-memory\/\([^ ]*\) -> .*/\1/p' \
    -e 's/^  migrated projects-memory\/\([^ ]*\) -> .*/\1/p' | LC_ALL=C sort
}

t_checkouts() {
section "checkouts — two linked legacy entries at one origin"
new_home
PM="$H/store/projects-memory"
for p in projects/internal shared-nfs/internal; do
  git_repo "$H/$p"
  git -C "$H/$p" remote add origin git@github.com:scamai/internal.git
done
RK=$(remote_key_of 'github.com/scamai/internal'); E="$PM/$RK"
M1=$(memdir "$H" "$H/projects/internal"); M2=$(memdir "$H" "$H/shared-nfs/internal")
for p in projects/internal shared-nfs/internal; do
  k=$(slug_of "$p"); mkdir -p "$PM/$k"
  printf '%s\n' "$p" > "$PM/$k/.project-path"
  printf 'note from %s\n' "$p" > "$PM/$k/note-$k.md"
  m=$(memdir "$H" "$H/$p"); mkdir -p "${m%/memory}"; ln -s "$PM/$k" "$m"
done
store_commit "$H"
SLP_HOSTNAME=aries run_slp "$H" >/dev/null
assert_both_linked "$E" "$M1" "$M2" "migration run 1"
assert_eq "$(cat "$M1/note-shared-nfs-internal.md" 2>/dev/null)" "note from shared-nfs/internal" \
  "the second legacy memory is visible through the first checkout"
HEAD1=$(store_head "$H")
assert_eq "$(SLP_HOSTNAME=aries run_slp "$H")" "" "migration run 2 changes nothing"
assert_eq "$(store_head "$H")" "$HEAD1" "migration run 2 commits nothing"
assert_eq "$(grep -c '^aries' "$E/.project-paths")" "2" "both checkout paths remain recorded"

section "checkouts — two real memory dirs and a later write"
new_home
for p in projects/internal shared-nfs/internal; do
  git_repo "$H/$p"
  git -C "$H/$p" remote add origin git@github.com:scamai/internal.git
  m=$(memdir "$H" "$H/$p"); mkdir -p "$m"; printf 'memory from %s\n' "$p" > "$m/$(slug_of "$p").md"
done
PM="$H/store/projects-memory"; E="$PM/$RK"
M1=$(memdir "$H" "$H/projects/internal"); M2=$(memdir "$H" "$H/shared-nfs/internal")
OUT=$(SLP_HOSTNAME=aries run_slp "$H")
assert_both_linked "$E" "$M1" "$M2" "adoption run 1"
assert_not_contains "$OUT" "pruned $(slug_of "$H/projects/internal")/memory -> projects-memory/$RK" \
  "a matching remote link is not pruned and recreated"
HEAD1=$(store_head "$H")
assert_eq "$(SLP_HOSTNAME=aries run_slp "$H")" "" "adoption run 2 changes nothing"
assert_eq "$(store_head "$H")" "$HEAD1" "adoption run 2 commits nothing"
rm "$M1"; mkdir -p "$M1"; printf 'written again\n' > "$M1/again.md"
SLP_HOSTNAME=aries run_slp "$H" >/dev/null
assert_both_linked "$E" "$M1" "$M2" "run 3 after a later write"
assert_eq "$(cat "$M2/again.md" 2>/dev/null)" "written again" "the later write is visible through both"

section "checkouts — an unrecorded second link is retained"
new_home
for p in projects/internal shared-nfs/internal; do
  git_repo "$H/$p"; git -C "$H/$p" remote add origin git@github.com:scamai/internal.git
done
PM="$H/store/projects-memory"; E="$PM/$RK"; mkdir -p "$E"
printf 'github.com/scamai/internal\n' > "$E/.project-remote"
printf 'aries\tprojects/internal\n' > "$E/.project-paths"
M1=$(memdir "$H" "$H/projects/internal"); M2=$(memdir "$H" "$H/shared-nfs/internal")
mkdir -p "${M1%/memory}" "${M2%/memory}"; ln -s "$E" "$M1"; ln -s "$E" "$M2"
store_commit "$H"
OUT=$(SLP_HOSTNAME=aries run_slp "$H")
assert_both_linked "$E" "$M1" "$M2" "unrecorded checkout run 1"
assert_not_contains "$OUT" "pruned $(slug_of "$H/shared-nfs/internal")/memory -> projects-memory/$RK" \
  "the matching second link is recorded, not pruned and recreated"
HEAD1=$(store_head "$H")
assert_eq "$(SLP_HOSTNAME=aries run_slp "$H")" "" "unrecorded checkout run 2 changes nothing"
assert_eq "$(store_head "$H")" "$HEAD1" "unrecorded checkout run 2 commits nothing"

section "checkouts — append after a hand-edited missing final newline"
new_home
PM="$H/store/projects-memory"; RK=$(remote_key_of 'github.com/Owner/Repo'); E="$PM/$RK"
git_repo "$H/projects/Clade"; git -C "$H/projects/Clade" remote add origin git@github.com:Owner/Repo.git
mkdir -p "$E"; printf 'github.com/Owner/Repo\n' > "$E/.project-remote"
printf 'other-host\tprojects/other' > "$E/.project-paths"
M=$(memdir "$H" "$H/projects/Clade"); mkdir -p "${M%/memory}"
store_commit "$H"
run_slp "$H" >/dev/null
assert_eq "$(wc -l < "$E/.project-paths" | tr -d ' ')" "2" "the append starts on a new line"
assert_eq "$(sed -n '1p' "$E/.project-paths")" "$(printf 'other-host\tprojects/other')" \
  "the other host's unterminated line remains readable"
assert_eq "$(sed -n '2p' "$E/.project-paths")" "$(printf 'test-host\tprojects/Clade')" \
  "this host's line is appended intact"
HEAD1=$(store_head "$H")
assert_eq "$(run_slp "$H")" "" "the repaired metadata is stable on the next run"
assert_eq "$(store_head "$H")" "$HEAD1" "and no further commit is needed"
}

t_discovery() {
section "discovery — one origin index per run"
new_home
PM="$H/store/projects-memory"
for spec in 'projects/one Other/One' 'projects/two Other/Two' 'code/three Other/Three'; do
  p=${spec%% *}; origin=${spec#* }
  git_repo "$H/$p"; git -C "$H/$p" remote add origin "git@github.com:$origin.git"
  m=$(memdir "$H" "$H/$p"); mkdir -p "${m%/memory}"
done
for name in Wanted1 Wanted2 Wanted3; do
  key=$(remote_key_of "github.com/Owner/$name"); mkdir -p "$PM/$key"
  printf 'github.com/Owner/%s\n' "$name" > "$PM/$key/.project-remote"
done
DUP="$H/.claude-profiles/p1/projects/$(slug_of "$H/projects/one")"
mkdir -p "$DUP"
store_commit "$H"
: > "$SANDBOX/git-count.log"
SLP_PATH="$SHIMBIN:$PATH" SLP_SHIM_MODE=count run_slp "$H" >/dev/null
N=$(wc -l < "$SANDBOX/git-count.log" | tr -d ' ')
assert_eq "$N" "3" "three distinct roots are queried once, not once per remote entry or profile"

section "discovery — outside-HOME slugs are skipped before decoding"
new_home
PM="$H/store/projects-memory"
OUTSIDE="$SANDBOX/outside-$NHOME"
git_repo "$OUTSIDE"; git -C "$OUTSIDE" remote add origin git@github.com:Owner/Outside.git
M=$(memdir "$H" "$OUTSIDE"); mkdir -p "${M%/memory}"
RK_OUTSIDE=$(remote_key_of 'github.com/Owner/Outside'); E="$PM/$RK_OUTSIDE"
mkdir -p "$E"; printf 'github.com/Owner/Outside\n' > "$E/.project-remote"
store_commit "$H"
: > "$SANDBOX/git-all.log"
OUT=$(SLP_PATH="$SHIMBIN:$PATH" SLP_SHIM_MODE=all run_slp "$H" --verbose)
check "an outside-HOME origin is not linked, as before" test ! -e "$M"
assert_eq "$(grep -cF "$OUTSIDE" "$SANDBOX/git-all.log" 2>/dev/null)" "0" \
  "no git call touches the outside-HOME path while indexing"

section "discovery — the budget stops between slugs and resumes next run"
new_home
PM="$H/store/projects-memory"
for name in A B C; do
  git_repo "$H/projects/$name"
  git -C "$H/projects/$name" remote add origin "git@github.com:Owner/$name.git"
  m=$(memdir "$H" "$H/projects/$name"); mkdir -p "${m%/memory}"
done
EB="$PM/$(remote_key_of 'github.com/Owner/B')"; mkdir -p "$EB"
printf 'github.com/Owner/B\n' > "$EB/.project-remote"
store_commit "$H"
MB=$(memdir "$H" "$H/projects/B")
: > "$SANDBOX/git-all.log"
OUT=$(SLP_BUDGET=1 SLP_PATH="$SHIMBIN:$PATH" SLP_SHIM_MODE=slow run_slp "$H")
N=$(awk -F '\t' '$2 ~ /^rev-parse --show-toplevel/ { print $1 }' "$SANDBOX/git-all.log" | LC_ALL=C sort -u | wc -l | tr -d ' ')
check "the index stops after fewer than all three slugs" test "$N" -lt 3
check "an entry absent from the incomplete index is deferred" test ! -e "$MB"
assert_contains "$OUT" "deferred: 1 memory directories" "the waiting entry is counted"
assert_not_contains "$OUT" "no local project with origin" "an incomplete index is not proof of absence"
run_slp "$H" >/dev/null
assert_eq "$(target_of "$MB")" "$EB" "the unbudgeted next run links the deferred entry"
}

t_dryrun() {
section "dry-run — discovery into an existing remote entry writes nothing"
new_home
PM="$H/store/projects-memory"; RK=$(remote_key_of 'github.com/Owner/Repo'); E="$PM/$RK"
git_repo "$H/projects/Clade"; git -C "$H/projects/Clade" remote add origin git@github.com:Owner/Repo.git
mkdir -p "$E"; printf 'github.com/Owner/Repo\n' > "$E/.project-remote"
M=$(memdir "$H" "$H/projects/Clade"); mkdir -p "${M%/memory}"
store_commit "$H"
BEFORE=$(snapshot_with_sums "$H")
OUT=$(run_slp "$H" --dry-run)
assert_eq "$(snapshot_with_sums "$H")" "$BEFORE" "existing-entry discovery leaves every byte and link unchanged"
assert_contains "$OUT" "would record projects-memory/$RK" "the discovery write is previewed"

section "dry-run — migration into an existing remote entry writes nothing"
new_home
PM="$H/store/projects-memory"; E="$PM/$RK"; L="$PM/projects-Clade"
git_repo "$H/projects/Clade"; git -C "$H/projects/Clade" remote add origin git@github.com:Owner/Repo.git
mkdir -p "$E" "$L"
printf 'github.com/Owner/Repo\n' > "$E/.project-remote"
printf 'projects/Clade\n' > "$L/.project-path"; printf 'legacy\n' > "$L/MEMORY.md"
M=$(memdir "$H" "$H/projects/Clade"); mkdir -p "${M%/memory}"; ln -s "$L" "$M"
store_commit "$H"
BEFORE=$(snapshot_with_sums "$H")
OUT=$(run_slp "$H" --dry-run)
assert_eq "$(snapshot_with_sums "$H")" "$BEFORE" "existing-entry migration leaves every byte and link unchanged"
assert_contains "$OUT" "would record projects-memory/$RK" "the migration write is previewed"

section "dry-run — a later planned migration conflicts exactly as the real run"
two_legacy_entries
printf 'projects version\n' > "$L1/MEMORY.md"
printf 'shared version\n' > "$L2/MEMORY.md"
store_commit "$H"
DRY=$(run_slp "$H" --dry-run)
assert_contains "$DRY" "would migrate projects-memory/projects-internal" "the first migration is still previewed"
assert_not_contains "$DRY" "would migrate projects-memory/shared-nfs-internal" \
  "the conflicting second migration is not previewed"
assert_not_contains "$DRY" "would prune $(slug_of "$H/shared-nfs/internal")" \
  "the conflicting checkout has no would-prune line"
assert_not_contains "$DRY" "would link $(slug_of "$H/shared-nfs/internal")" \
  "the conflicting checkout has no would-link line"
REAL=$(run_slp "$H")
DRY_CONFLICT=$(grep '^  conflict: projects-memory/shared-nfs-internal' <<< "$DRY")
REAL_CONFLICT=$(grep '^  conflict: projects-memory/shared-nfs-internal' <<< "$REAL")
assert_eq "$DRY_CONFLICT" "$REAL_CONFLICT" "dry and real print the identical conflict"
check "the real run leaves the second legacy entry unmigrated" test ! -e "$L2/.migrated-to"
assert_eq "$(migration_keys <<< "$DRY")" "$(migration_keys <<< "$REAL")" \
  "dry and real agree on the migrated key set"
assert_eq "$(migration_keys <<< "$REAL")" "projects-internal" "only the first legacy key migrates"
assert_eq "$(target_of "$M2")" "$L2" "the second checkout keeps its legacy memory link"

section "dry-run — a planned migration into an EXISTING entry still counts"
# The destination already exists (another host migrated first and the store
# synced). A real run copies the first legacy entry into it before checking the
# second; a dry run must compare the second with that planned entry too.
two_legacy_entries
mkdir -p "$E"; printf 'github.com/scamai/internal\n' > "$E/.project-remote"
printf 'from another host\n' > "$E/other-host.md"
printf 'projects version\n' > "$L1/MEMORY.md"
printf 'shared version\n' > "$L2/MEMORY.md"
store_commit "$H"
DRY=$(run_slp "$H" --dry-run)
assert_contains "$DRY" "would migrate projects-memory/projects-internal" \
  "the first migration into the existing entry is previewed"
assert_not_contains "$DRY" "would migrate projects-memory/shared-nfs-internal" \
  "the second is not previewed when it clashes with the first, though the entry exists"
REAL=$(run_slp "$H")
assert_eq "$(migration_keys <<< "$DRY")" "$(migration_keys <<< "$REAL")" \
  "dry and real agree on the migrated key set into an existing entry"
check "the real run leaves the clashing legacy entry unmigrated" test ! -e "$L2/.migrated-to"

section "dry-run — disjoint planned migrations both proceed"
two_legacy_entries
printf 'only projects\n' > "$L1/projects.md"
printf 'only shared\n' > "$L2/shared.md"
store_commit "$H"
DRY=$(run_slp "$H" --dry-run)
EXPECTED_KEYS=$(printf 'projects-internal\nshared-nfs-internal')
assert_eq "$(migration_keys <<< "$DRY")" "$EXPECTED_KEYS" "dry-run previews both disjoint migrations"
REAL=$(run_slp "$H")
assert_eq "$(migration_keys <<< "$REAL")" "$EXPECTED_KEYS" "the real run migrates both disjoint entries"
check "both disjoint legacy entries gain markers" \
  test -f "$L1/.migrated-to" -a -f "$L2/.migrated-to"

section "dry-run — an identical subset also proceeds"
two_legacy_entries
printf 'shared memory\n' > "$L1/MEMORY.md"
printf 'first-only extra\n' > "$L1/first.md"
printf 'shared memory\n' > "$L2/MEMORY.md"
store_commit "$H"
DRY=$(run_slp "$H" --dry-run)
EXPECTED_KEYS=$(printf 'projects-internal\nshared-nfs-internal')
assert_eq "$(migration_keys <<< "$DRY")" "$EXPECTED_KEYS" "dry-run previews the identical subset too"
REAL=$(run_slp "$H")
assert_eq "$(migration_keys <<< "$REAL")" "$EXPECTED_KEYS" "the real run also migrates the identical subset"
check "both identical-subset legacy entries gain markers" \
  test -f "$L1/.migrated-to" -a -f "$L2/.migrated-to"
}

t_identity() {
section "identity — the link pass rejects a remote/key mismatch"
new_home
PM="$H/store/projects-memory"; E="$PM/repo-not-the-origin-key"
git_repo "$H/projects/Clade"; git -C "$H/projects/Clade" remote add origin git@github.com:Owner/Repo.git
mkdir -p "$E"; printf 'github.com/Owner/Repo\n' > "$E/.project-remote"
printf 'test-host\tprojects/Clade\n' > "$E/.project-paths"
M=$(memdir "$H" "$H/projects/Clade")
store_commit "$H"
run_slp "$H" >/dev/null
check "a mismatched remote entry is not linked" test ! -e "$M"

section "identity — prune leaves a remote/key mismatch for a human"
new_home
PM="$H/store/projects-memory"; E="$PM/repo-not-the-origin-key"
git_repo "$H/projects/one"; git_repo "$H/projects/two"
mkdir -p "$E"; printf 'github.com/Owner/Repo\n' > "$E/.project-remote"
printf 'test-host\tprojects/two\n' > "$E/.project-paths"
M=$(memdir "$H" "$H/projects/one"); mkdir -p "${M%/memory}"; ln -s "$E" "$M"
store_commit "$H"
run_slp "$H" >/dev/null
assert_eq "$(target_of "$M")" "$E" "prune does not interpret a mismatched entry's host paths"

section "identity — subdirectories and linked worktrees keep path keys"
new_home
git_repo "$H/projects/mono"; mkdir -p "$H/projects/mono/sub"
git -C "$H/projects/mono" remote add origin git@github.com:Owner/Repo.git
M=$(memdir "$H" "$H/projects/mono/sub"); mkdir -p "$M"; printf 'subdirectory\n' > "$M/MEMORY.md"
run_slp "$H" >/dev/null
E="$H/store/projects-memory/projects-mono-sub"
assert_eq "$(target_of "$M")" "$E" "a repository subdirectory adopts under its path key"
assert_eq "$(cat "$E/.project-path" 2>/dev/null)" "projects/mono/sub" "the subdirectory keeps .project-path"
check "no remote-keyed entry absorbs the subdirectory" test ! -e "$H/store/projects-memory/$RK"

new_home
git_repo "$H/projects/main"
git -C "$H/projects/main" remote add origin git@github.com:Owner/Repo.git
git -C "$H/projects/main" -c user.email=t@example.com -c user.name=t -c core.hooksPath=/dev/null \
  commit -q --allow-empty -m init >/dev/null 2>&1
git -C "$H/projects/main" worktree add "$H/projects/wt" >/dev/null 2>&1
M=$(memdir "$H" "$H/projects/wt"); mkdir -p "$M"; printf 'worktree\n' > "$M/MEMORY.md"
run_slp "$H" >/dev/null
E="$H/store/projects-memory/projects-wt"
assert_eq "$(target_of "$M")" "$E" "a linked worktree adopts under its path key"
check "the linked worktree has no remote metadata" test ! -e "$E/.project-remote"
}

ALL_SECTIONS="checkouts discovery dryrun identity"
for _s in ${SLPR_ONLY:-$ALL_SECTIONS}; do "t_$_s"; done

if [[ -z "${SLPR_MUTANT:-}" && -z "${SLPR_SKIP_MUTATIONS:-}" ]]; then
section "mutations — discovery and metadata guards"
MUT_DIR="$SANDBOX/mutants-remote"
NMUT=0
MUT_NAMES=(); MUT_ONLY=()
mutation() {
  local name=$1 only=$2 dir="$MUT_DIR/m$NMUT"
  mkdir -p "$dir/scripts" "$dir/hooks/lib"
  cp "$SCRIPTS"/sync-*.sh "$dir/scripts/"
  cp "$HOOKS/lib/runtime-dir.sh" "$dir/hooks/lib/"
  cp "$HOOKS/sync-health.sh" "$dir/hooks/"
  if ! SLP_A="$3" SLP_R="$4" awk '
      { buf = buf (NR > 1 ? "\n" : "") $0 }
      END {
        a = ENVIRON["SLP_A"]; r = ENVIRON["SLP_R"]; s = buf; out = ""; n = 0
        while ((i = index(s, a)) > 0) { out = out substr(s, 1, i - 1) r; s = substr(s, i + length(a)); n++ }
        if (n != 1) exit 3
        printf "%s\n", out s
      }' "$SCRIPTS/../scripts/sync-link-projects.sh" > "$dir/scripts/sync-link-projects.sh"; then
    fail "mutation '$name': its anchor no longer matches exactly once"
    return 0
  fi
  MUT_NAMES[NMUT]=$name; MUT_ONLY[NMUT]=$only; NMUT=$((NMUT + 1))
}
mutation "no-op control" "$ALL_SECTIONS" '# Regular files only.' '# Regular files only, really.'
MUT_CONTROL=0
mutation "recorded checkout retention" "checkouts" \
  '      if [[ "$matched" -eq 1 && "$private" -eq 0 ]]; then continue; fi' \
  '      if false; then continue; fi'
mutation "unrecorded checkout retention" "checkouts" \
  '          if [[ "$matched" -eq 1 ]]; then continue; fi' \
  '          if false; then continue; fi'
mutation "the shared discovery index" "discovery" \
  '  DISCOVERY_BUILT=1' '  DISCOVERY_BUILT=0'
mutation "the HOME-prefix discovery filter" "discovery" \
  '      case "$slug" in "$home_slug"|"$home_slug"-*) ;; *) continue ;; esac' \
  '      :'
mutation "the per-slug discovery budget" "discovery" \
  '      if budget_exhausted; then return 0; fi' \
  '      if false; then return 0; fi'
mutation "the final-newline append guard" "checkouts" \
  '  if [[ -s "$entry/.project-paths" && -n "$(tail -c 1 "$entry/.project-paths")" ]]; then' \
  '  if false; then'
mutation "the planned-destination conflict check" "dryrun" \
  '  if [[ "$DRY_RUN" -eq 1 ]]; then
    planned=$(planned_migration_sources' \
  '  if false; then
    planned=$(planned_migration_sources'
mutation "the planned-destination check on an existing entry" "dryrun" \
  '  if [[ "$DRY_RUN" -eq 1 ]]; then
    planned=$(planned_migration_sources' \
  '  if [[ "$DRY_RUN" -eq 1 && ! -d "$dst" ]]; then
    planned=$(planned_migration_sources'
mutation "the record_host_path dry-run guard" "dryrun" \
  '  if [[ "$DRY_RUN" -eq 1 ]]; then
    say "record' \
  '  if false; then
    say "record'
mutation "the link remote/key check" "identity" \
  '    if [[ "$key" != "$(key_of_remote "$remote")" ]]; then
      note "projects-memory/$key: .project-remote does not match its key"' \
  '    if false; then
      note "projects-memory/$key: .project-remote does not match its key"'
mutation "the prune remote/key check" "identity" \
  '    if [[ -n "$remote" && "$key" != "$(key_of_remote "$remote")" ]]; then
      note "$where/memory: projects-memory/$key has a mismatched .project-remote' \
  '    if false; then
      note "$where/memory: projects-memory/$key has a mismatched .project-remote'
mutation "the repository-root identity guard" "identity" \
  '  is_memory_root "$1" || return 0' '  :'

SLPR_JOBS="${SLPR_JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)}"
[[ "$SLPR_JOBS" =~ ^[0-9]+$ && "$SLPR_JOBS" -ge 1 ]] || SLPR_JOBS=2
[[ "$SLPR_JOBS" -gt 4 ]] && SLPR_JOBS=4
SLPR_SELF="$REPO_ROOT/tests/test-sync-link-projects-remote.sh"
run_mutant() {
  SLP_SCRIPTS_DIR="$MUT_DIR/m$1/scripts" SLPR_ONLY="${MUT_ONLY[$1]}" SLPR_MUTANT=1 \
    bash "$SLPR_SELF" > "$MUT_DIR/m$1.log" 2>&1
}
MUT_PIDS=(); MUT_RCS=(); NEXT=0; I=0
while [[ "$I" -lt "$NMUT" ]]; do
  if [[ $((I - NEXT)) -ge "$SLPR_JOBS" ]]; then
    wait "${MUT_PIDS[$NEXT]}"; MUT_RCS[NEXT]=$?; NEXT=$((NEXT + 1))
  fi
  run_mutant "$I" & MUT_PIDS[I]=$!; I=$((I + 1))
done
while [[ "$NEXT" -lt "$NMUT" ]]; do
  wait "${MUT_PIDS[$NEXT]}"; MUT_RCS[NEXT]=$?; NEXT=$((NEXT + 1))
done
I=0
while [[ "$I" -lt "$NMUT" ]]; do
  rc="${MUT_RCS[$I]}"
  first=$(grep -m1 '✗' "$MUT_DIR/m$I.log" 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g; s/^ *✗ *//')
  if [[ "$I" -eq "$MUT_CONTROL" ]]; then
    if [[ "$rc" -eq 0 ]]; then pass "control: ${MUT_NAMES[$I]} leaves the suite green"
    else fail "control: ${MUT_NAMES[$I]} leaves the suite green" "rc=$rc, first failure: $first"; fi
  elif [[ "$rc" -ne 0 ]]; then
    pass "without ${MUT_NAMES[$I]}: red — ${first:-rc=$rc}"
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
