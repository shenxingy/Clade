#!/usr/bin/env bash
# test-sync-link-projects-remote.sh — multi-checkout and discovery regressions.
#
# Sections (SLPR_ONLY="checkouts ..." selects a subset):
#   checkouts  two legacy links and two real memory dirs at one origin on one
#              host all stay linked, including a later write; run two is quiet
#   discovery  one origin index per run, non-HOME slugs skipped before decode,
#              and a per-slug budget whose incomplete-index misses defer and resume
#   dryrun     an existing remote entry gains no .project-paths under --dry-run,
#              either through discovery or migration into that entry; and parity:
#              on one project with two legacy keys (a basename or a second path
#              key, clashing or not, sorting before or after the new key, into a
#              new or an existing entry), on two checkouts sharing one slug, and
#              on adoptions (then a link in another profile, a second checkout,
#              a clashing migration or adoption into the same key, a path key, a
#              key another origin's migration wants), and on chained profile
#              links (through a migrated link, under a symlinked HOME, through an
#              adopted directory, into a recreated entry, through a pruned link,
#              a cycle), a dry run changes no byte and then the real run adopts,
#              migrates, prunes, links, records and conflicts exactly as the dry
#              run said
#   identity   remote/key mismatches are left alone in link and prune; repo
#              subdirectories and linked worktrees keep path keys
#
# The mutation suite removes recorded and unrecorded checkout retention, the
# shared discovery index, HOME-prefix filter, per-slug budget, final-newline
# guard, planned-destination conflict check (also into an existing entry),
# record_host_path dry-run guard, each dry-run table the later passes read
# (planned copies recorded, a planned destination listed once, planned
# destinations, their glob order, entry status and origin, planned checkout paths
# read and recorded, a planned path key's owner recorded and read, a planned
# migration's marker, its prune and valid target, dry prunes recorded and freeing
# the slug, dry links recorded, seen, and already right), each part of an
# adoption's preview (its copy, recorded checkout and link, adopting into a
# planned entry and checking its planned copies), a planned destination's origin
# in migration, each step of following a chained link through the dry run's
# links (the call, a hop's spelling, a hop linked, a hop pruned, a planned entry
# at the end), link and prune remote/key checks, and the repository-root
# identity guard. Each must make its section fail. A no-op control must stay
# green. NOT in this list: dry_cur's eight-hop bound, whose removal hangs the
# cycle case rather than failing it (checked by hand under `timeout`). Every
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
  PM="$H/store/projects-memory"; RK=$(remote_key_of 'github.com/owner/shared'); E="$PM/$RK"
  L1="$PM/projects-shared"; L2="$PM/srv-shared"
  for p in projects/shared srv/shared; do
    git_repo "$H/$p"; git -C "$H/$p" remote add origin git@github.com:owner/shared.git
    k=$(slug_of "$p"); mkdir -p "$PM/$k"; printf '%s\n' "$p" > "$PM/$k/.project-path"
    m=$(memdir "$H" "$H/$p"); mkdir -p "${m%/memory}"; ln -s "$PM/$k" "$m"
  done
  M1=$(memdir "$H" "$H/projects/shared"); M2=$(memdir "$H" "$H/srv/shared")
}

migration_keys() {
  sed -n -e 's/^  would migrate projects-memory\/\([^ ]*\) -> .*/\1/p' \
    -e 's/^  migrated projects-memory\/\([^ ]*\) -> .*/\1/p' | LC_ALL=C sort
}

# plan_of — a linker's actions and conflicts with the tense and the parenthesised
# detail removed, so a dry run's "would link X -> Y (...)" and a real run's
# "linked X -> Y (...)" compare equal. Not de-duplicated: a dry run that plans
# one link twice differs from a real run that makes it once.
plan_of() {
  awk '
    /^  conflict: / { print; next }
    { sub(/^  would /, "  ") }
    {
      v = $1
      if (v == "adopted") v = "adopt"; else if (v == "migrated") v = "migrate"
      else if (v == "pruned") v = "prune"; else if (v == "linked") v = "link"
      else if (v == "recorded") v = "record"; else if (v == "detached") v = "detach"
      if (v !~ /^(adopt|migrate|prune|link|record|detach)$/) next
      rest = $0; sub(/^ *[^ ]+ /, "", rest); sub(/ \(.*/, "", rest)
      print v " " rest
    }' | LC_ALL=C sort
}

# parity_fixture NAME SECOND — one checkout ~/projects/NAME (origin owner/NAME)
# and two legacy store keys for it: projects-NAME (path-keyed, so it migrates)
# and SECOND. The memory links of two projects dirs point at SECOND, and a third
# projects dir has the slug and no link yet. This is the aries shape behind #209's
# follow-up: the project's links named a different legacy key than the one it
# migrated, so the new key claimed the project in the link pass. The caller
# gives SECOND its .project-path (path-keyed) or leaves it a basename entry.
parity_fixture() {
  local name=$1 slug pd
  new_home
  PM="$H/store/projects-memory"; P="$H/projects/$name"
  git_repo "$P"; git -C "$P" remote add origin "git@github.com:owner/$name.git"
  RK=$(remote_key_of "github.com/owner/$name"); E="$PM/$RK"
  L1="$PM/projects-$name"; L2="$PM/$2"
  mkdir -p "$L1" "$L2"
  printf 'projects/%s\n' "$name" > "$L1/.project-path"
  printf 'first key\n' > "$L1/first.md"
  printf 'second key\n' > "$L2/second.md"
  slug=$(slug_of "$P")
  for pd in "$H/.claude/projects" "$H/.claude-profiles/p1/projects"; do
    mkdir -p "$pd/$slug"; ln -s "$L2" "$pd/$slug/memory"
  done
  mkdir -p "$H/.claude-profiles/p2/projects/$slug"
}

# adopt_fixture NAME TEXT — ~/projects/NAME (origin owner/NAME) with a real memory
# directory in ~/.claude holding MEMORY.md = TEXT, and profile p2 with the slug
# and no memory yet: a host's first real run adopts it, then links p2.
adopt_fixture() {
  new_home
  PM="$H/store/projects-memory"; P="$H/projects/$1"
  git_repo "$P"; git -C "$P" remote add origin "git@github.com:owner/$1.git"
  RK=$(remote_key_of "github.com/owner/$1"); E="$PM/$RK"
  M=$(memdir "$H" "$P"); mkdir -p "$M"; printf '%s\n' "$2" > "$M/MEMORY.md"
  mkdir -p "$H/.claude-profiles/p2/projects/$(slug_of "$P")"
}

# assert_parity LABEL CONFLICTS — the dry run writes nothing, then the real run on
# that same unchanged fixture makes exactly the plan the dry run printed. CONFLICTS
# is how many the real run reports, so the case cannot pass by conflicting nowhere.
assert_parity() {
  local before dry real
  store_commit "$H"
  before=$(snapshot_with_sums "$H")
  dry=$(run_slp "$H" --dry-run)
  assert_eq "$(snapshot_with_sums "$H")" "$before" "$1: the dry run changes no byte, link or git state"
  real=$(run_slp "$H")
  assert_eq "$(migration_keys <<< "$dry")" "$(migration_keys <<< "$real")" \
    "$1: dry and real migrate the same keys"
  assert_eq "$(grep '^  conflict: ' <<< "$dry" | LC_ALL=C sort)" \
    "$(grep '^  conflict: ' <<< "$real" | LC_ALL=C sort)" "$1: dry and real report the same conflicts"
  assert_eq "$(plan_of <<< "$dry")" "$(plan_of <<< "$real")" \
    "$1: dry and real plan the same prunes, links and records"
  assert_eq "$(grep -c '^  conflict: ' <<< "$real")" "$2" "$1: the real run reports $2 conflicts"
}

t_checkouts() {
section "checkouts — two linked legacy entries at one origin"
new_home
PM="$H/store/projects-memory"
for p in projects/shared srv/shared; do
  git_repo "$H/$p"
  git -C "$H/$p" remote add origin git@github.com:owner/shared.git
done
RK=$(remote_key_of 'github.com/owner/shared'); E="$PM/$RK"
M1=$(memdir "$H" "$H/projects/shared"); M2=$(memdir "$H" "$H/srv/shared")
for p in projects/shared srv/shared; do
  k=$(slug_of "$p"); mkdir -p "$PM/$k"
  printf '%s\n' "$p" > "$PM/$k/.project-path"
  printf 'note from %s\n' "$p" > "$PM/$k/note-$k.md"
  m=$(memdir "$H" "$H/$p"); mkdir -p "${m%/memory}"; ln -s "$PM/$k" "$m"
done
store_commit "$H"
SLP_HOSTNAME=aries run_slp "$H" >/dev/null
assert_both_linked "$E" "$M1" "$M2" "migration run 1"
assert_eq "$(cat "$M1/note-srv-shared.md" 2>/dev/null)" "note from srv/shared" \
  "the second legacy memory is visible through the first checkout"
HEAD1=$(store_head "$H")
assert_eq "$(SLP_HOSTNAME=aries run_slp "$H")" "" "migration run 2 changes nothing"
assert_eq "$(store_head "$H")" "$HEAD1" "migration run 2 commits nothing"
assert_eq "$(grep -c '^aries' "$E/.project-paths")" "2" "both checkout paths remain recorded"

section "checkouts — two real memory dirs and a later write"
new_home
for p in projects/shared srv/shared; do
  git_repo "$H/$p"
  git -C "$H/$p" remote add origin git@github.com:owner/shared.git
  m=$(memdir "$H" "$H/$p"); mkdir -p "$m"; printf 'memory from %s\n' "$p" > "$m/$(slug_of "$p").md"
done
PM="$H/store/projects-memory"; E="$PM/$RK"
M1=$(memdir "$H" "$H/projects/shared"); M2=$(memdir "$H" "$H/srv/shared")
OUT=$(SLP_HOSTNAME=aries run_slp "$H")
assert_both_linked "$E" "$M1" "$M2" "adoption run 1"
assert_not_contains "$OUT" "pruned $(slug_of "$H/projects/shared")/memory -> projects-memory/$RK" \
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
for p in projects/shared srv/shared; do
  git_repo "$H/$p"; git -C "$H/$p" remote add origin git@github.com:owner/shared.git
done
PM="$H/store/projects-memory"; E="$PM/$RK"; mkdir -p "$E"
printf 'github.com/owner/shared\n' > "$E/.project-remote"
printf 'aries\tprojects/shared\n' > "$E/.project-paths"
M1=$(memdir "$H" "$H/projects/shared"); M2=$(memdir "$H" "$H/srv/shared")
mkdir -p "${M1%/memory}" "${M2%/memory}"; ln -s "$E" "$M1"; ln -s "$E" "$M2"
store_commit "$H"
OUT=$(SLP_HOSTNAME=aries run_slp "$H")
assert_both_linked "$E" "$M1" "$M2" "unrecorded checkout run 1"
assert_not_contains "$OUT" "pruned $(slug_of "$H/srv/shared")/memory -> projects-memory/$RK" \
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
assert_contains "$DRY" "would migrate projects-memory/projects-shared" "the first migration is still previewed"
assert_not_contains "$DRY" "would migrate projects-memory/srv-shared" \
  "the conflicting second migration is not previewed"
assert_not_contains "$DRY" "would prune $(slug_of "$H/srv/shared")" \
  "the conflicting checkout has no would-prune line"
assert_not_contains "$DRY" "would link $(slug_of "$H/srv/shared")" \
  "the conflicting checkout has no would-link line"
REAL=$(run_slp "$H")
DRY_CONFLICT=$(grep '^  conflict: projects-memory/srv-shared' <<< "$DRY")
REAL_CONFLICT=$(grep '^  conflict: projects-memory/srv-shared' <<< "$REAL")
assert_eq "$DRY_CONFLICT" "$REAL_CONFLICT" "dry and real print the identical conflict"
check "the real run leaves the second legacy entry unmigrated" test ! -e "$L2/.migrated-to"
assert_eq "$(migration_keys <<< "$DRY")" "$(migration_keys <<< "$REAL")" \
  "dry and real agree on the migrated key set"
assert_eq "$(migration_keys <<< "$REAL")" "projects-shared" "only the first legacy key migrates"
assert_eq "$(target_of "$M2")" "$L2" "the second checkout keeps its legacy memory link"

section "dry-run — a planned migration into an EXISTING entry still counts"
# The destination already exists (another host migrated first and the store
# synced). A real run copies the first legacy entry into it before checking the
# second; a dry run must compare the second with that planned entry too.
two_legacy_entries
mkdir -p "$E"; printf 'github.com/owner/shared\n' > "$E/.project-remote"
printf 'from another host\n' > "$E/other-host.md"
printf 'projects version\n' > "$L1/MEMORY.md"
printf 'shared version\n' > "$L2/MEMORY.md"
store_commit "$H"
DRY=$(run_slp "$H" --dry-run)
assert_contains "$DRY" "would migrate projects-memory/projects-shared" \
  "the first migration into the existing entry is previewed"
assert_not_contains "$DRY" "would migrate projects-memory/srv-shared" \
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
EXPECTED_KEYS=$(printf 'projects-shared\nsrv-shared')
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
EXPECTED_KEYS=$(printf 'projects-shared\nsrv-shared')
assert_eq "$(migration_keys <<< "$DRY")" "$EXPECTED_KEYS" "dry-run previews the identical subset too"
REAL=$(run_slp "$H")
assert_eq "$(migration_keys <<< "$REAL")" "$EXPECTED_KEYS" "the real run also migrates the identical subset"
check "both identical-subset legacy entries gain markers" \
  test -f "$L1/.migrated-to" -a -f "$L2/.migrated-to"

section "dry-run parity — links at a second legacy key the migration did not retire"
# The aries run: a basename entry held the links, the path-keyed entry migrated,
# and the new key then claimed every linked slug. "ink" sorts before repo-...,
# so the basename entry also links the unlinked profile first.
parity_fixture ink ink
assert_parity "basename second key" 3
assert_eq "$(target_of "$H/.claude-profiles/p2/projects/$(slug_of "$P")/memory")" "$L2" \
  "the basename entry linked the empty profile before the new key reached it"

section "dry-run parity — two path-keyed entries, the linked one blocked by a clash"
parity_fixture ink projects-ink2
printf 'projects/ink\n' > "$L2/.project-path"; printf 'differs\n' > "$L2/first.md"
assert_parity "clashing second path key" 4
check "the clashing second key is not migrated" test ! -e "$L2/.migrated-to"

section "dry-run parity — two path-keyed entries that both migrate"
parity_fixture ink projects-ink2
printf 'projects/ink\n' > "$L2/.project-path"
assert_parity "both path keys migrate" 0
assert_eq "$(target_of "$H/.claude-profiles/p2/projects/$(slug_of "$P")/memory")" "$E" \
  "the empty profile is linked to the new key exactly once"

section "dry-run parity — a planned key sorting before the other claimant"
# repo-...-zap sorts before the basename entry zap: the real run links the empty
# profile to the new key first, and the basename entry then finds it taken.
parity_fixture zap zap
assert_parity "planned key first" 2
assert_eq "$(target_of "$H/.claude-profiles/p2/projects/$(slug_of "$P")/memory")" "$E" \
  "the new key linked the empty profile before the basename entry reached it"

section "dry-run parity — two recorded checkouts whose paths share one slug"
# projects/a.b and projects/a-b encode to one slug: the real run links it for the
# first and finds it already right for the second, so the dry run must too.
new_home
PM="$H/store/projects-memory"; RK=$(remote_key_of 'github.com/owner/ab'); E="$PM/$RK"
for p in projects/a.b projects/a-b; do
  git_repo "$H/$p"; git -C "$H/$p" remote add origin git@github.com:owner/ab.git
done
mkdir -p "$E" "$(dirname "$(memdir "$H" "$H/projects/a.b")")"
printf 'github.com/owner/ab\n' > "$E/.project-remote"
printf 'test-host\tprojects/a.b\ntest-host\tprojects/a-b\n' > "$E/.project-paths"
assert_parity "one slug, two checkouts" 0
assert_eq "$(target_of "$(memdir "$H" "$H/projects/a-b")")" "$E" "the shared slug is linked once, to the entry"

section "dry-run parity — a migration into an EXISTING entry, links at a basename key"
# The destination is on disk (another host's checkout only), so the planned
# migration must not list it a second time: a second visit would reach every
# link the basename entry holds again and print each conflict twice.
parity_fixture ink ink
mkdir -p "$E"; printf 'github.com/owner/ink\n' > "$E/.project-remote"
printf 'other-host\tprojects/ink\n' > "$E/.project-paths"
assert_parity "existing destination, basename second key" 3

section "dry-run parity — an adoption, then its link in another profile"
# A host's first run: the new entry an adoption creates is linked into every
# other profile with the slug, and its checkout is recorded.
adopt_fixture foo 'local'
assert_parity "adopt, then link" 0
assert_eq "$(target_of "$H/.claude-profiles/p2/projects/$(slug_of "$P")/memory")" "$E" \
  "the other profile is linked to the adopted entry"

section "dry-run parity — a second checkout adopts into an entry recorded for the first"
# The adoption records ~/projects/two-b, so the link pass links it as well as
# two-a; with no record it would link two-a alone, since discovery never runs.
new_home
PM="$H/store/projects-memory"; RK=$(remote_key_of 'github.com/owner/two'); E="$PM/$RK"
for p in projects/two-a projects/two-b; do
  git_repo "$H/$p"; git -C "$H/$p" remote add origin git@github.com:owner/two.git
done
mkdir -p "$E"; printf 'github.com/owner/two\n' > "$E/.project-remote"
printf 'test-host\tprojects/two-a\n' > "$E/.project-paths"
M=$(memdir "$H" "$H/projects/two-b"); mkdir -p "$M"; printf 'b\n' > "$M/MEMORY.md"
mkdir -p "$H/.claude-profiles/p2/projects/$(slug_of "$H/projects/two-b")"
assert_parity "adopt into an entry recorded for another checkout" 0
assert_eq "$(target_of "$H/.claude-profiles/p2/projects/$(slug_of "$H/projects/two-b")/memory")" "$E" \
  "the adopted checkout is linked in the other profile too"

section "dry-run parity — an adoption, then a migration into the same key that clashes"
# The adopted memory is in the new key before the migration pass compares the
# legacy entry with it; the legacy entry keeps its link, and both keys claim it.
adopt_fixture bar 'local version'
L1="$PM/projects-bar"; mkdir -p "$L1"
printf 'projects/bar\n' > "$L1/.project-path"; printf 'store version\n' > "$L1/MEMORY.md"
mkdir -p "$H/.claude-profiles/p1/projects/$(slug_of "$P")"
ln -s "$L1" "$H/.claude-profiles/p1/projects/$(slug_of "$P")/memory"
assert_parity "adopt, then a clashing migration" 4
check "the clashing legacy entry is not migrated" test ! -e "$L1/.migrated-to"

section "dry-run parity — two profiles adopt into one new key, their files differing"
adopt_fixture two 'one'
M1="$H/.claude-profiles/p1/projects/$(slug_of "$P")/memory"
mkdir -p "$M1"; printf 'two\n' > "$M1/MEMORY.md"
assert_parity "two adoptions, one key" 1
check "the second profile's memory stays a local directory" real_dir "$M1"

section "dry-run parity — a path-keyed adoption, then its link in another profile"
# No origin: the new entry is named by its path and carries .project-path,
# which is what the link pass reads to find the project.
new_home
PM="$H/store/projects-memory"; P="$H/projects/plain"; mkdir -p "$P"
M=$(memdir "$H" "$P"); mkdir -p "$M"; printf 'plain\n' > "$M/MEMORY.md"
mkdir -p "$H/.claude-profiles/p2/projects/$(slug_of "$P")"
assert_parity "a path-keyed adoption" 0
assert_eq "$(target_of "$H/.claude-profiles/p2/projects/$(slug_of "$P")/memory")" "$PM/projects-plain" \
  "the other profile is linked to the path-keyed entry"

section "dry-run parity — an adoption's new key, wanted by a different origin's migration"
# github.com/owner/a.b and github.com/owner/a-b encode to one key. The adoption
# takes it for a.b, so the a-b legacy entry finds it owned by another origin.
new_home
PM="$H/store/projects-memory"
for p in dot:a.b dash:a-b; do
  git_repo "$H/projects/${p%%:*}"
  git -C "$H/projects/${p%%:*}" remote add origin "git@github.com:owner/${p#*:}.git"
done
M=$(memdir "$H" "$H/projects/dot"); mkdir -p "$M"; printf 'dot\n' > "$M/MEMORY.md"
L1="$PM/projects-dash"; mkdir -p "$L1"
printf 'projects/dash\n' > "$L1/.project-path"; printf 'dash\n' > "$L1/dash.md"
assert_parity "one key, two origins" 1
check "the other origin's legacy entry is not migrated" test ! -e "$L1/.migrated-to"

section "dry-run parity — a profile chained through ~/.claude's link to a migrating key"
# The author's host: each profile's memory is a link to ~/.claude/projects/<slug>/
# memory. The real run retires ~/.claude's link and relinks it to the new key,
# so the chain reaches the new key; a dry run following the disk reached the
# legacy key and reported a conflict the real run never has.
chain_fixture() {   # ~/projects/ink: ~/.claude links to projects-ink, p1 chains to it
  new_home
  PM="$H/store/projects-memory"; P="$H/projects/ink"
  git_repo "$P"; git -C "$P" remote add origin git@github.com:owner/ink.git
  E="$PM/$(remote_key_of github.com/owner/ink)"; L1="$PM/projects-ink"
  mkdir -p "$L1"; printf 'projects/ink\n' > "$L1/.project-path"; printf 'x\n' > "$L1/MEMORY.md"
  mkdir -p "$H/.claude/projects/$(slug_of "$P")" "$H/.claude-profiles/p1/projects/$(slug_of "$P")"
  ln -s "$L1" "$H/.claude/projects/$(slug_of "$P")/memory"
  ln -s "$H/.claude/projects/$(slug_of "$P")/memory" "$H/.claude-profiles/p1/projects/$(slug_of "$P")/memory"
}
chain_fixture
assert_parity "chain through a migrated link" 0
assert_eq "$(cd "$H/.claude-profiles/p1/projects/$(slug_of "$P")/memory" && pwd -P)" "$E" \
  "the chain reaches the new key"

section "dry-run parity — the same chain under a HOME reached through a symlink"
# HOME's spelling differs from its physical path, so each hop of the chain is
# renamed to the projects dir's spelling before the dry tables are read.
chain_fixture
ln -s "$H" "$H-link"; H="$H-link"
assert_parity "chain under a symlinked HOME" 0

section "dry-run parity — a profile chained through a directory that is adopted"
adopt_fixture foo 'local'
mkdir -p "$H/.claude-profiles/p1/projects/$(slug_of "$P")"
ln -s "$M" "$H/.claude-profiles/p1/projects/$(slug_of "$P")/memory"
assert_parity "chain through an adopted directory" 0

section "dry-run parity — a dangling link into the entry an adoption recreates"
# p1 still links to an entry removed from the store; the adoption from ~/.claude
# makes it live again, so the link is already right, not a conflict.
adopt_fixture gone 'local'
mkdir -p "$H/.claude-profiles/p1/projects/$(slug_of "$P")"
ln -s "$E" "$H/.claude-profiles/p1/projects/$(slug_of "$P")/memory"
assert_parity "dangling link into a recreated entry" 0

section "dry-run parity — a chain through a link the prune removes"
# ~/projects/hop's slug chains to a slug no checkout produces, whose link into the
# same entry the prune removes; by the link pass the chain leads nowhere, which
# is a conflict, not the link it once was.
new_home
PM="$H/store/projects-memory"; P="$H/projects/hop"
git_repo "$P"; git -C "$P" remote add origin git@github.com:owner/hop.git
E="$PM/$(remote_key_of github.com/owner/hop)"
mkdir -p "$E" "$H/.claude/projects/$(slug_of "$P")" "$H/.claude/projects/-nowhere"
printf 'github.com/owner/hop\n' > "$E/.project-remote"; printf 'test-host\tprojects/hop\n' > "$E/.project-paths"
ln -s "$E" "$H/.claude/projects/-nowhere/memory"
ln -s "$H/.claude/projects/-nowhere/memory" "$(memdir "$H" "$P")"
assert_parity "chain through a pruned link" 1

section "dry-run parity — a cycle of links at a linked slug"
# `cd` fails on a cycle; the dry run's own hop-by-hop walk must stop and fail too.
new_home
PM="$H/store/projects-memory"; P="$H/projects/loop"
git_repo "$P"; git -C "$P" remote add origin git@github.com:owner/loop.git
E="$PM/$(remote_key_of github.com/owner/loop)"
mkdir -p "$E"; printf 'github.com/owner/loop\n' > "$E/.project-remote"
printf 'test-host\tprojects/loop\n' > "$E/.project-paths"
for p in p1 p2; do mkdir -p "$H/.claude-profiles/$p/projects/$(slug_of "$P")"; done
ln -s "$H/.claude-profiles/p2/projects/$(slug_of "$P")/memory" "$H/.claude-profiles/p1/projects/$(slug_of "$P")/memory"
ln -s "$H/.claude-profiles/p1/projects/$(slug_of "$P")/memory" "$H/.claude-profiles/p2/projects/$(slug_of "$P")/memory"
assert_parity "a cycle of links" 2
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
  '  [[ -z "$clash" && "$DRY_RUN" -eq 1 ]] && clash=$(planned_clash "$newkey" "$src" "$files")' '  :'
mutation "the planned-destination check on an existing entry" "dryrun" \
  '  [[ -z "$clash" && "$DRY_RUN" -eq 1 ]] && clash=$(planned_clash "$newkey" "$src" "$files")' \
  '  [[ -z "$clash" && "$DRY_RUN" -eq 1 && ! -d "$dst" ]] && clash=$(planned_clash "$newkey" "$src" "$files")'
mutation "recording planned copies" "dryrun" \
  '  DRY_SOURCES="$DRY_SOURCES$1"$'"'"'\t'"'"'"$2"$'"'"'\n'"'"'' '  :'
mutation "skipping a planned destination already listed" "dryrun" \
  '  entry_exists "$1" && return 0' '  :'
mutation "an adoption's planned copy" "dryrun" \
  '      remember_planned_copy "$key" "$mem" "$remote" "$rel"' '      :'
mutation "an adoption's recorded checkout" "dryrun" \
  '      if [[ -n "$remote" ]]; then record_host_path "$dst" "$rel"; fi' '      :'
mutation "an adoption's link" "dryrun" \
  '      DRY_LINKS="$DRY_LINKS$mem"$'"'"'\t'"'"'"$key"$'"'"'\n'"'"'' '      :'
mutation "recording a planned path key's owner" "dryrun" \
  '  [[ -n "$3" ]] || DRY_OWNERS="$DRY_OWNERS$1"$'"'"'\t'"'"'"$4"$'"'"'\n'"'"'' '  :'
mutation "reading a planned path key's owner" "dryrun" \
  '    [[ "$DRY_RUN" -eq 1 ]] && dry_lookup "$DRY_OWNERS" "${1##*/}" && printf '"'"'%s'"'"' "$DRY_VALUE"' \
  '    :'
mutation "an adoption into a planned entry" "dryrun" \
  '    if [[ -e "$dst" || -L "$dst" ]] || entry_exists "$key"; then' \
  '    if [[ -e "$dst" || -L "$dst" ]]; then'
mutation "the planned-copy check in adoption" "dryrun" \
  '      [[ -z "$clash" && "$DRY_RUN" -eq 1 ]] && clash=$(planned_clash "$key" "$mem" "$files")' '      :'
mutation "a planned destination's origin in migration" "dryrun" \
  '  if entry_exists "$newkey"; then' '  if [[ -d "$dst" ]]; then'
mutation "following a chain through the dry run's links" "dryrun" \
  '        if [[ "$DRY_RUN" -eq 1 ]]; then cur=$(dry_cur "$mem") || cur=""; fi' '        :'
mutation "a chain hop renamed to its projects dir's spelling" "dryrun" \
  '      case "$t" in "${PROJECTS_PHYS[$i]}"/*) t="${PROJECTS_DIRS[$i]}/${t#"${PROJECTS_PHYS[$i]}"/}"; break ;; esac' \
  '      :'
mutation "a chain hop the dry run would have linked" "dryrun" \
  '    if dry_lookup "$DRY_LINKS" "$t"; then printf' '    if false; then printf'
mutation "a chain hop the dry run would have pruned" "dryrun" \
  '    case "$DRY_GONE" in *$'"'"'\n'"'"'"$t"$'"'"'\n'"'"'*) return 1 ;; esac' '    :'
mutation "a chain ending in an entry the dry run would create" "dryrun" \
  '  if [[ "${t%/*}" == "$PM_PHYS" ]] && dry_lookup "$DRY_NEW" "${t##*/}"; then' '  if false; then'
mutation "the record_host_path dry-run guard" "dryrun" \
  '  if [[ "$DRY_RUN" -eq 1 ]]; then
    say "record' \
  '  if false; then
    say "record'
mutation "planned destinations in the dry link pass" "dryrun" \
  'if [[ "$DRY_RUN" -eq 1 && "$DRY_NEW" != $'"'"'\n'"'"' ]]; then' 'if false; then'
mutation "glob order for planned destinations" "dryrun" \
  '              done <<< "$DRY_NEW"; } | sort)' '              done <<< "$DRY_NEW"; } | cat)'
mutation "a planned destination counting as an entry" "dryrun" \
  '  entry_exists "$key" || continue' '  [[ -d "$entry" ]] || continue'
mutation "a planned destination's origin" "dryrun" \
  '    [[ "$DRY_RUN" -eq 1 ]] && dry_lookup "$DRY_NEW" "${1##*/}" && printf '"'"'%s'"'"' "$DRY_VALUE"' \
  '    :'
mutation "reading planned checkout paths" "dryrun" \
  '  [[ "$DRY_RUN" -eq 1 ]] || return 0
  # A dry run also counts' '  return 0
  # A dry run also counts'
mutation "recording planned checkout paths" "dryrun" \
  '    DRY_PATHS="$DRY_PATHS${entry##*/}"$'"'"'\t'"'"'"$rel"$'"'"'\n'"'"'' '    :'
mutation "a planned migration's marker" "dryrun" \
  '    [[ "$DRY_RUN" -eq 1 ]] && dry_lookup "$DRY_MIGRATED" "${1##*/}" && printf '"'"'%s'"'"' "$DRY_VALUE"' \
  '    :'
mutation "pruning links into planned migrations" "dryrun" \
  '    elif [[ -f "$entry/.migrated-to" ]] || planned_migration "$key"; then' \
  '    elif [[ -f "$entry/.migrated-to" ]]; then'
mutation "a planned destination as a valid migration target" "dryrun" \
  '      if [[ -z "$migrated" ]] || ! entry_exists "$migrated"; then' \
  '      if [[ -z "$migrated" || ! -d "$PROJECTS_MEMORY_DIR/$migrated" ]]; then'
mutation "recording dry-run prunes" "dryrun" \
  '      DRY_GONE="$DRY_GONE$mem"$'"'"'\n'"'"'' '      :'
mutation "a dry-run prune freeing the slug" "dryrun" \
  '        case "$DRY_GONE" in *$'"'"'\n'"'"'"$mem"$'"'"'\n'"'"'*) dry_link "$where" "$mem" "$key"; continue ;; esac' \
  '        :'
mutation "a dry-run link seen by later entries" "dryrun" \
  '        if dry_lookup "$DRY_LINKS" "$mem"; then' '        if false; then'
mutation "recording dry-run links" "dryrun" \
  '  DRY_LINKS="$DRY_LINKS$2"$'"'"'\t'"'"'"$3"$'"'"'\n'"'"'' '  :'
mutation "a dry-run link to the same entry is already right" "dryrun" \
  '          [[ "$DRY_VALUE" == "$key" ]] \' '          false \'
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
