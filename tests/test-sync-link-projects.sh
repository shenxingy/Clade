#!/usr/bin/env bash
# test-sync-link-projects.sh — project auto-memory reaches the sync store.
#
# Claude Code reads a project's auto-memory from
# ~/.claude/projects/<slug>/memory, and the dotfiles sync store is its own git
# repository. Before 2026-11-06 the linker found projects by basename, wrote
# links into directories Claude Code never reads, stopped after its first entry,
# and never moved a local memory directory into the store, so the memory loaded
# into every session had no diff history. Each case here reads what a consumer
# gets: the file Claude Code would open through the memory path, and the
# store's git history.
#
#   adopt     a real memory dir moves into the store, verified, linked back,
#             committed; a later edit through the link is a diff in history
#   link      a store entry links to Claude Code's slug (leading "-", "." -> "-")
#   legacy    a basename entry links only to a top-level directory of that name,
#             never to a `.git/<name>` hit
#   prune     wrong-target links go; correct ones, and links outside the store,
#             stay; store content is never touched
#   conflict  a store copy that differs blocks adoption; nothing moves
#   private   private-projects and conversation-mode never reach the store
#   dry-run   changes nothing at all
#   wiring    sync-pull.sh (the SessionStart hook) runs the whole chain
#
# The last suite removes each guard of the linker in turn and requires this
# suite to go red. A mutation whose anchor no longer matches is a failure.
#
# Every HOME, store and project is a throwaway directory; the real ~/.claude
# and the real store are never read or written. No network: the fixture store
# has no remote, so sync-push.sh commits and does not push.
#
# Usage:
#   bash tests/test-sync-link-projects.sh        # run all tests
#   bash tests/test-sync-link-projects.sh -v     # verbose
# Internal:
#   SLP_SCRIPTS_DIR=DIR   test the sync scripts in DIR (needs DIR/../hooks/lib)
#   SLP_MUTANT=1          stop at the first failure; skip the mutation suite
#   SLP_JOBS=N            mutants run N at a time (default: CPU count, max 8)
#   SLP_SKIP_MUTATIONS=1  run every case, skip the mutation suite (used to show
#                         the cases fail against an older linker)

# SC2016: the mutation anchors are literal shell text, quoted on purpose.
# SC2012: ls output here only feeds failure messages.
# shellcheck disable=SC2016,SC2012
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPTS="${SLP_SCRIPTS_DIR:-$REPO_ROOT/configs/scripts}"
SLP_MUTANT="${SLP_MUTANT:-}"

# ─── Test framework (mirrors tests/test-hooks.sh) ────────────────────
TESTS_RUN=0; TESTS_PASSED=0; TESTS_FAILED=0
VERBOSE="${1:-}"
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; NC='\033[0m'

pass() { TESTS_RUN=$((TESTS_RUN + 1)); TESTS_PASSED=$((TESTS_PASSED + 1)); echo -e "  ${GREEN}✓${NC} $1"; }
fail() {
  TESTS_RUN=$((TESTS_RUN + 1)); TESTS_FAILED=$((TESTS_FAILED + 1))
  echo -e "  ${RED}✗${NC} $1"
  [[ -n "${2:-}" ]] && echo -e "    ${RED}→ $2${NC}"
  if [[ -n "$SLP_MUTANT" ]]; then exit 1; fi
  return 0
}
section() { echo ""; echo -e "${YELLOW}━━━ $1 ━━━${NC}"; }
check() {   # check "message" command... — pass when the command succeeds
  local msg=$1; shift
  if "$@"; then pass "$msg"; else fail "$msg" "${WHY:-}"; fi
  WHY=""
}
assert_eq() {
  if [[ "$1" == "$2" ]]; then pass "$3"; else fail "$3" "got '$1', want '$2'"; fi
}
assert_contains() {
  if grep -qF -- "$2" <<< "$1"; then pass "$3"
  else
    fail "$3" "output does not contain '$2'"
    [[ "$VERBOSE" == "-v" ]] && echo "    output: $(head -12 <<< "$1")"
  fi
  return 0
}
WHY=""

if ! command -v git >/dev/null 2>&1; then
  echo "git not found — skipping"; exit 0
fi

# ─── Sandbox ─────────────────────────────────────────────────────────
SANDBOX=$(mktemp -d "${TMPDIR:-/tmp}/slp-test.XXXXXX") || exit 1
# Physical path: macOS /tmp is a symlink, and Claude Code slugs the real path.
SANDBOX=$(cd "$SANDBOX" && pwd -P)
trap 'rm -rf "$SANDBOX"' EXIT
NHOME=0

# Claude Code's encoding, written independently of the script under test.
slug_of() { printf '%s' "$1" | LC_ALL=C sed 's/[^A-Za-z0-9]/-/g'; }

# new_home — sets H to a fresh HOME with ~/.claude, a git store with no remote
# and ~/projects. Sets a global rather than printing: under $(...) the counter
# would never advance and every case would share one HOME.
new_home() {
  NHOME=$((NHOME + 1))
  H="$SANDBOX/home$NHOME"
  local h=$H
  mkdir -p "$h/.claude/projects" "$h/store/projects-memory" "$h/projects"
  printf 'SYNC_BACKEND=nfs\nSYNC_DIR=%s\n' "$h/store" > "$h/.claude/.sync-config"
  (
    cd "$h/store" || exit 1
    git init -q . && git config user.email t@example.com && git config user.name t
    git config core.hooksPath /dev/null
    printf 'store\n' > README && git add -A && git commit -qm base
  ) >/dev/null 2>&1
}
git_repo() { mkdir -p "$1" && git -C "$1" init -q . >/dev/null 2>&1; }
memdir() { printf '%s/.claude/projects/%s/memory' "$1" "$(slug_of "$2")"; }
run_slp() {   # HOME ARGS... — the linker, as sync-pull.sh runs it
  local h=$1; shift
  HOME="$h" CLADE_RUNTIME_DIR="$h/.rt" bash "$SCRIPTS/sync-link-projects.sh" "$@" 2>&1
}
store_head() { git -C "$1/store" rev-parse HEAD 2>/dev/null; }
target_of() { local t; t=$(readlink "$1" 2>/dev/null) || return 1; printf '%s' "${t%/}"; }

# ─── 1. adopt: local memory moves into the store and gains history ───

section "adopt — a real memory directory becomes a store entry with history"

new_home
git_repo "$H/projects/Clade"
mkdir -p "$H/projects/Clade/.git/clade"   # the old `find -name clade` hit
M=$(memdir "$H" "$H/projects/Clade")
mkdir -p "$M/notes"
printf '# Memory index\n- [fleet](fleet.md)\n' > "$M/MEMORY.md"
printf 'build-a and build-b track main\n' > "$M/fleet.md"
printf 'nested topic\n' > "$M/notes/deep.md"
BASE=$(store_head "$H")
OUT=$(run_slp "$H")
E="$H/store/projects-memory/projects-Clade"

WHY="memory is $(ls -ld "$M" 2>&1)"
check "the memory path is now a symlink" test -L "$M"
assert_eq "$(target_of "$M")" "$E" "it points at projects-memory/<key derived from the path under HOME>"
assert_eq "$(cat "$M/MEMORY.md" 2>/dev/null)" "$(printf '# Memory index\n- [fleet](fleet.md)')" \
  "Claude Code reads the same MEMORY.md through it"
assert_eq "$(cat "$M/notes/deep.md" 2>/dev/null)" "nested topic" "a nested topic file came along"
assert_eq "$(cat "$E/.project-path" 2>/dev/null)" "projects/Clade" \
  ".project-path names the project relative to HOME, case kept"
HIST=$(git -C "$H/store" log --format=%H -- projects-memory/projects-Clade/fleet.md 2>/dev/null)
WHY="no commit touches projects-memory/projects-Clade/fleet.md; HEAD moved from $BASE to $(store_head "$H")"
check "the adoption is committed: the topic file has git history" test -n "$HIST"
assert_eq "$(git -C "$H/store" show HEAD:projects-memory/projects-Clade/fleet.md 2>/dev/null)" \
  "build-a and build-b track main" "the committed content is the memory's content"
BK=$(ls -d "${M%/memory}"/memory.pre-sync-* 2>/dev/null | head -1)
WHY="no memory.pre-sync-* next to the link"
check "the original directory is kept, not deleted" test -f "$BK/fleet.md"
assert_contains "$OUT" "adopted $(slug_of "$H/projects/Clade") -> projects-memory/projects-Clade" \
  "the adoption is reported"

# A later edit made through the link is a diff in the store's history.
printf 'build-a and build-b track main\nbuild-c too\n' > "$M/fleet.md"
# Its own lock dir: sync-push skips silently when the lock is held, and a
# shared one is contended by parallel mutants (and by the real user's pushes).
HOME="$H" CLADE_RUNTIME_DIR="$H/.rt" bash "$SCRIPTS/sync-push.sh" >/dev/null 2>&1 || true
DIFF=$(git -C "$H/store" log -p -1 -- projects-memory/projects-Clade/fleet.md 2>/dev/null)
assert_contains "$DIFF" "+build-c too" "an edit through the link shows up as a diff in history"

HEAD1=$(store_head "$H")
OUT2=$(run_slp "$H")
assert_eq "$OUT2" "" "a second run has nothing to do and says nothing"
assert_eq "$(store_head "$H")" "$HEAD1" "and commits nothing"
WHY="slug directories: $(ls "$H/.claude/projects" | tr '\n' ' ')"
check "no link is made at the .git/clade path the old linker chose" \
  test ! -e "$(memdir "$H" "$H/projects/Clade/.git/clade")"

# A symlink inside a memory directory (the old linker's `ln -sfn` onto a real
# directory left these) must not be committed as an absolute path.
mkdir -p "$H/projects/ink"
M2=$(memdir "$H" "$H/projects/ink")
mkdir -p "$M2" && printf 'ink topic\n' > "$M2/topic.md"
ln -s "$H/store/projects-memory/projects-Clade" "$M2/stale-link"
OUT=$(run_slp "$H")
check "a memory dir holding a stray symlink is still adopted" test -L "$M2"
WHY="store entry holds: $(ls -A "$H/store/projects-memory/projects-ink" 2>&1 | tr '\n' ' ')"
check "the stray symlink is not copied into the store" \
  test ! -e "$H/store/projects-memory/projects-ink/stale-link" -a ! -L "$H/store/projects-memory/projects-ink/stale-link"
assert_contains "$OUT" "symlinks not copied: stale-link" "and the report names it"

# ─── 2. link: a store entry from another machine lands at the right slug ─

section "link — store entries reach the directory Claude Code reads"

new_home
mkdir -p "$H/projects/my.app" "$H/store/projects-memory/projects-my-app" \
  "$H/store/projects-memory/projects-elsewhere"
printf 'projects/my.app\n' > "$H/store/projects-memory/projects-my-app/.project-path"
printf 'from the other machine\n' > "$H/store/projects-memory/projects-my-app/MEMORY.md"
printf 'projects/elsewhere\n' > "$H/store/projects-memory/projects-elsewhere/.project-path"
OUT=$(run_slp "$H")
SL=$(slug_of "$H/projects/my.app")
case "$SL" in -*) pass "the expected slug starts with '-' (encoder sanity)" ;; *) fail "slug sanity" "$SL" ;; esac
assert_eq "$(cat "$H/.claude/projects/$SL/memory/MEMORY.md" 2>/dev/null)" "from the other machine" \
  "Claude Code finds the entry at its own slug ('.' becomes '-', leading '-')"
NODASH="${SL#-}"
WHY="the old encoder's directory exists: $NODASH"
check "nothing is written at the slug without the leading '-'" test ! -e "$H/.claude/projects/$NODASH"
WHY="$(ls "$H/.claude/projects")"
check "an entry whose project is not on this machine is not linked anywhere" \
  test -z "$(find "$H/.claude/projects" -iname '*elsewhere*' -print)"

# ─── 3. legacy: basename entries link only to a top-level project ─────

section "legacy entries — exact top-level match, never a .git hit"

new_home
git_repo "$H/projects/tools"
git_repo "$H/projects/host"
mkdir -p "$H/projects/host/.git/widgets"     # find -name widgets finds this first
mkdir -p "$H/store/projects-memory/tools" "$H/store/projects-memory/widgets"
printf 'tools memory\n' > "$H/store/projects-memory/tools/MEMORY.md"
printf 'widgets memory\n' > "$H/store/projects-memory/widgets/MEMORY.md"
OUT=$(run_slp "$H")
assert_eq "$(cat "$(memdir "$H" "$H/projects/tools")/MEMORY.md" 2>/dev/null)" "tools memory" \
  "a legacy entry links to ~/projects/<name> at Claude Code's slug"
WHY="$(ls "$H/.claude/projects")"
check "a legacy entry whose only match is inside .git is not linked" \
  test -z "$(find "$H/.claude/projects" -name '*widgets*' -print)"

# ─── 4. prune: wrong-target links go, right ones stay ─────────────────

section "prune — provably wrong links are removed, nothing else"

new_home
PM="$H/store/projects-memory"
git_repo "$H/projects/tools"
git_repo "$H/projects/mono"; mkdir -p "$H/projects/mono/sub"
mkdir -p "$H/projects/my.app" "$H/projects/other" "$H/elsewhere-memory"
mkdir -p "$PM/tools" "$PM/clade" "$PM/sub" "$PM/projects-my-app"
printf 'legacy clade content\n' > "$PM/clade/MEMORY.md"
printf 'projects/my.app\n' > "$PM/projects-my-app/.project-path"
mklink() { mkdir -p "$H/.claude/projects/$1" && ln -s "$2" "$H/.claude/projects/$1/memory"; }
GOOD=$(slug_of "$H/projects/tools")
NODASH=$(slug_of "$H/projects/tools"); NODASH=${NODASH#-}
INGIT=$(slug_of "$H/projects/mono/.git/clade"); mkdir -p "$H/projects/mono/.git/clade"
GONE=$(slug_of "$H/projects/removed-long-ago")
SUBDIR=$(slug_of "$H/projects/mono/sub")
WRONGOWNER=$(slug_of "$H/projects/other")
OUTSIDE=$(slug_of "$H/projects/my.app")
mklink "$GOOD" "$PM/tools/"                   # trailing slash, as old links had
mklink "$NODASH" "$PM/clade"
mklink "$INGIT" "$PM/clade/"
mklink "$GONE" "$PM/clade"
mklink "$SUBDIR" "$PM/sub"
mklink "$WRONGOWNER" "$PM/projects-my-app"
mklink "$OUTSIDE" "$H/elsewhere-memory"       # not into the store: not ours
OUT=$(run_slp "$H")
PD="$H/.claude/projects"
check "kept: a legacy link at the project's own slug" test -L "$PD/$GOOD/memory"
WHY="$OUT"
check "pruned: a slug without the leading '-'" test ! -e "$PD/$NODASH/memory"
check "pruned: a slug that only a path inside .git produces" test ! -e "$PD/$INGIT/memory"
check "pruned: a slug no directory on this machine produces" test ! -e "$PD/$GONE/memory"
check "pruned: a repository subdirectory (memory keys to the repository root)" test ! -e "$PD/$SUBDIR/memory"
check "pruned: a link into an entry whose .project-path names another project" \
  test ! -e "$PD/$WRONGOWNER/memory"
assert_eq "$(target_of "$PD/$OUTSIDE/memory")" "$H/elsewhere-memory" \
  "kept untouched: a link that points outside the store (and the right slug is not taken over)"
assert_eq "$(cat "$PM/clade/MEMORY.md" 2>/dev/null)" "legacy clade content" "store content is never touched"
check "an emptied slug directory is removed with its link" test ! -d "$PD/$NODASH"
assert_contains "$OUT" "pruned $NODASH/memory -> projects-memory/clade" "each prune is reported with its link"

# ─── 5. conflict: a differing store copy blocks adoption ──────────────

section "conflict — two versions of a file: nothing moves"

new_home
PM="$H/store/projects-memory"
mkdir -p "$H/projects/api" "$H/projects/web" "$H/projects/legacy"
mkdir -p "$PM/projects-api" "$PM/projects-web" "$PM/projects-legacy"
printf 'projects/api\n' > "$PM/projects-api/.project-path"
printf 'store version\n' > "$PM/projects-api/MEMORY.md"
printf 'projects/web\n' > "$PM/projects-web/.project-path"
printf 'same\n' > "$PM/projects-web/a.md"
printf 'old basename entry\n' > "$PM/projects-legacy/MEMORY.md"   # no .project-path
MA=$(memdir "$H" "$H/projects/api"); mkdir -p "$MA"; printf 'local version\n' > "$MA/MEMORY.md"
MW=$(memdir "$H" "$H/projects/web"); mkdir -p "$MW"; printf 'same\n' > "$MW/a.md"; printf 'only here\n' > "$MW/b.md"
ML=$(memdir "$H" "$H/projects/legacy"); mkdir -p "$ML"; printf 'mine\n' > "$ML/MEMORY.md"
OUT=$(run_slp "$H")
check "a local dir whose file differs from the store's stays a real directory" test -d "$MA" -a ! -L "$MA"
assert_eq "$(cat "$MA/MEMORY.md")" "local version" "with its own content"
assert_eq "$(cat "$PM/projects-api/MEMORY.md")" "store version" "and the store's copy is not overwritten"
assert_contains "$OUT" "these files differ from projects-memory/projects-api: MEMORY.md" \
  "the conflict names the file"
check "files that are identical or new merge: adopted" test -L "$MW"
assert_eq "$(cat "$PM/projects-web/b.md" 2>/dev/null)" "only here" "the new file is in the store"
check "an entry of the same name that belongs to no project blocks adoption" test -d "$ML" -a ! -L "$ML"
assert_eq "$(cat "$PM/projects-legacy/MEMORY.md")" "old basename entry" "and is not overwritten"

# ─── 6. private: never leaves this machine ───────────────────────────

section "private — private-projects and conversation-mode stay local"

new_home
mkdir -p "$H/projects/diary" "$H/projects/chat/.claude"
: > "$H/projects/chat/.claude/conversation-mode"
MD=$(memdir "$H" "$H/projects/diary"); mkdir -p "$MD"; printf 'personal\n' > "$MD/MEMORY.md"
MC=$(memdir "$H" "$H/projects/chat"); mkdir -p "$MC"; printf 'chatty\n' > "$MC/MEMORY.md"
printf '# private\n%s\n' "$H/projects/diary" > "$H/.claude/private-projects"
OUT=$(run_slp "$H")
check "a project in private-projects is not adopted" test -d "$MD" -a ! -L "$MD"
check "a conversation-mode project is not adopted" test -d "$MC" -a ! -L "$MC"
WHY="$(git -C "$H/store" log --all --name-only --format= 2>/dev/null | tr '\n' ' ')"
check "neither reaches the store's history" \
  test -z "$(git -C "$H/store" log --all --name-only --format= -- projects-memory 2>/dev/null)"
# Control: the same directory IS adopted once the registry no longer lists it,
# so the absence above was the guard's doing.
rm -f "$H/.claude/private-projects"
run_slp "$H" >/dev/null
check "control: without the registry entry it would have been adopted" test -L "$MD"

# ─── 7. dry-run: changes nothing ─────────────────────────────────────

section "dry-run — reports, changes nothing"

new_home
mkdir -p "$H/projects/alpha" "$H/projects/beta" "$H/store/projects-memory/projects-beta"
printf 'projects/beta\n' > "$H/store/projects-memory/projects-beta/.project-path"
MAL=$(memdir "$H" "$H/projects/alpha"); mkdir -p "$MAL"; printf 'a\n' > "$MAL/MEMORY.md"
mkdir -p "$H/.claude/projects/stale-no-dash"
ln -s "$H/store/projects-memory/projects-beta" "$H/.claude/projects/stale-no-dash/memory"
snapshot() { (cd "$H" && find . -path ./store/.git -prune -o -print | LC_ALL=C sort | while IFS= read -r f; do
  if [[ -L "$f" ]]; then printf '%s -> %s\n' "$f" "$(readlink "$f")"; else printf '%s\n' "$f"; fi
done; git -C store status --porcelain; git -C store rev-parse HEAD); }
BEFORE=$(snapshot)
OUT=$(run_slp "$H" --dry-run)
assert_eq "$(snapshot)" "$BEFORE" "the tree, every link and the store are unchanged"
assert_contains "$OUT" "would adopt $(slug_of "$H/projects/alpha")" "it says what it would adopt"
assert_contains "$OUT" "would prune stale-no-dash/memory" "what it would prune"
assert_contains "$OUT" "would link $(slug_of "$H/projects/beta")/memory -> projects-memory/projects-beta" \
  "and what it would link"

# ─── 8. wiring: the SessionStart hook runs the chain ─────────────────

section "wiring — sync-pull.sh adopts and commits"

new_home
mkdir -p "$H/projects/gamma"
MG=$(memdir "$H" "$H/projects/gamma"); mkdir -p "$MG"; printf 'gamma memory\n' > "$MG/MEMORY.md"
HOME="$H" CLADE_RUNTIME_DIR="$H/.rt" bash "$SCRIPTS/sync-pull.sh" >/dev/null 2>&1 || true
assert_eq "$(git -C "$H/store" show HEAD:projects-memory/projects-gamma/MEMORY.md 2>/dev/null)" \
  "gamma memory" "after a session start the memory is in the store's history"

# ─── 9. mutations: each guard, removed, turns this suite red ──────────

if [[ -z "$SLP_MUTANT" && -z "${SLP_SKIP_MUTATIONS:-}" ]]; then
section "mutations — removing a guard must turn the suite red"

MUT_DIR="$SANDBOX/mutants"
NMUT=0
MUT_NAMES=(); MUT_EXPECT=()
# mutation EXPECT NAME ANCHOR REPLACEMENT — literal text that must match the
# linker exactly once. Builds a mutant tree; the runner below executes it.
mutation() {
  local expect=$1 name=$2 dir="$MUT_DIR/m$NMUT"
  mkdir -p "$dir/scripts" "$dir/hooks/lib"
  cp "$SCRIPTS"/sync-*.sh "$dir/scripts/"
  cp "$SCRIPTS/../hooks/lib/runtime-dir.sh" "$dir/hooks/lib/"
  if ! SLP_A="$3" SLP_R="$4" awk '
      { buf = buf (NR > 1 ? "\n" : "") $0 }
      END {
        a = ENVIRON["SLP_A"]; r = ENVIRON["SLP_R"]; s = buf; out = ""; n = 0
        while ((i = index(s, a)) > 0) { out = out substr(s, 1, i - 1) r; s = substr(s, i + length(a)); n++ }
        if (n != 1) exit 3
        printf "%s\n", out s
      }' "$SCRIPTS/sync-link-projects.sh" > "$dir/scripts/sync-link-projects.sh"; then
    fail "mutation '$name': its anchor no longer matches the linker exactly once"
    return 0
  fi
  MUT_NAMES[NMUT]=$name; MUT_EXPECT[NMUT]=$expect
  NMUT=$((NMUT + 1))
}

mutation green "no-op control (a comment reworded)" \
  '# Regular files only.' '# Regular files only, really.'
mutation red "the leading '-' of the slug (old encoder)" \
  'enc "$1"
  fi' 'enc "${1#/}"
  fi'
mutation red "the adopt pass" \
  '  [[ -d "$mem" && ! -L "$mem" ]] || continue' '  continue'
mutation red "the commit after adoption" \
  'bash "$SCRIPT_DIR/sync-push.sh" >/dev/null || true' ':'
mutation red "the conflict check" \
  '    if [[ -n "$clash" ]]; then' '    if false; then'
mutation red "the private-project check" \
  '  if is_private "$proj"; then' '  if false; then'
mutation red "the .git exclusion" \
  '  case "$p/" in */.git/*) return 1 ;; esac' '  :'
mutation red "the repository-subdirectory rule" \
  '[[ "$(cd "$top" 2>/dev/null && pwd -P)" == "$here" ]] || return 1' ':'
mutation red "the dry-run guard on adopt" \
  '    say "adopt $slug -> projects-memory/$key ($nfiles files, ~/$rel$extra)"
    adopted=$((adopted + 1))
    continue' '    say "adopt $slug -> projects-memory/$key ($nfiles files, ~/$rel$extra)"'
mutation red "the stray-symlink exclusion (a plain cp -R)" \
  '  copy_failed=0
' '  cp -Rp "$mem/." "$dst/"
  copy_failed=0
'
mutation red "the prune pass" \
  '  [[ -L "$mem" ]] || continue
  target=' '  continue
  target='
mutation red "never replacing an existing link" \
  '  if [[ -L "$mem" ]]; then
    cur=' '  if [[ -L "$mem" ]]; then rm -f "$mem"; fi
  if false; then
    cur='

# Bounded parallelism; bash 3.2 has no `wait -n`, so wait oldest-first.
SLP_JOBS="${SLP_JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)}"
[[ "$SLP_JOBS" =~ ^[0-9]+$ && "$SLP_JOBS" -ge 1 ]] || SLP_JOBS=2
[[ "$SLP_JOBS" -gt 8 ]] && SLP_JOBS=8
SLP_SELF="$REPO_ROOT/tests/test-sync-link-projects.sh"
run_mutant() {
  SLP_SCRIPTS_DIR="$MUT_DIR/m$1/scripts" SLP_MUTANT=1 bash "$SLP_SELF" > "$MUT_DIR/m$1.log" 2>&1
}
MUT_PIDS=(); MUT_RCS=()
NEXT=0; I=0
while [[ "$I" -lt "$NMUT" ]]; do
  if [[ $((I - NEXT)) -ge "$SLP_JOBS" ]]; then
    wait "${MUT_PIDS[$NEXT]}"; MUT_RCS[NEXT]=$?
    NEXT=$((NEXT + 1))
  fi
  run_mutant "$I" &
  MUT_PIDS[I]=$!
  I=$((I + 1))
done
while [[ "$NEXT" -lt "$NMUT" ]]; do
  wait "${MUT_PIDS[$NEXT]}"; MUT_RCS[NEXT]=$?
  NEXT=$((NEXT + 1))
done

I=0
while [[ "$I" -lt "$NMUT" ]]; do
  rc="${MUT_RCS[$I]}"
  first=$(grep -m1 '✗' "$MUT_DIR/m$I.log" 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g; s/^ *✗ *//')
  if [[ "${MUT_EXPECT[$I]}" == "green" ]]; then
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
