#!/usr/bin/env bash
# test-sync-link-projects.sh — project auto-memory reaches the sync store.
#
# Claude Code reads a project's auto-memory from
# <config>/projects/<slug>/memory, and the dotfiles sync store is its own git
# repository. Before 2026-11-06 the linker found projects by basename, wrote
# links into directories Claude Code never reads, stopped after its first entry,
# and never moved a local memory directory into the store, so the memory loaded
# into every session had no diff history. Each case here reads what a consumer
# gets: the file Claude Code would open through the memory path, the store's
# git history, and what sync-health.sh prints at session start.
#
# Sections (SLP_ONLY="adopt prune ..." runs a subset):
#   adopt      a real memory dir moves into the store, verified, linked back,
#              committed; a later edit through the link is a diff in history
#   link       a store entry links to Claude Code's slug (leading "-", "." -> "-")
#   legacy     a basename entry links only to a top-level memory root: never a
#              `.git/<name>` hit, never a linked worktree
#   prune      wrong-target links go; correct ones (top-level and deeper), links
#              outside the store and dangling links stay; store content is
#              never touched
#   conflict   a differing store copy, or a name owned by another project,
#              blocks adoption; nothing moves, nothing is planted inside the
#              local dir; the conflict lands in ~/.claude/.sync-memory-conflicts
#              and once a day in ~/.claude/.sync-conflicts.log, and
#              sync-health.sh prints it until it is resolved
#   private    private-projects and conversation-mode stay local in every pass:
#              not adopted, not linked, an existing link detached to a copy
#   dryrun     changes nothing at all, writes no log
#   wiring     sync-pull.sh (the SessionStart hook) runs the whole chain
#   ambiguous  a slug two directories share is not adopted
#   store      an unreachable SYNC_DIR creates nothing
#   profiles   ~/.claude-profiles/*/projects and $CLAUDE_CONFIG_DIR/projects are
#              adopted from and linked into; a chained link is not a conflict
#   commit     an adoption left uncommitted by an earlier run is committed
#   budget     past CLADE_SYNC_LINK_BUDGET the rest waits for the next run, and
#              that run's conflicts are kept, not forgotten
#   races      a copy that does not verify, a directory recreated during the
#              move, and a write landing during the move (PATH shims for tar, mv)
#   lock       a second linker while one holds the lock does nothing (flock)
#   limits     a store key past 200 characters; a .project-path climbing out
#              of $HOME
#   remote     two hosts share one origin at different paths; per-checkout paths,
#              no-origin fallback, safe union migration and relinking, conflicts,
#              private projects, dry-run checksums, discovery and budget
#
# The last suite mutates one guard at a time and requires red from the sections
# that cover it. EXACTLY these are mutated (sync-link-projects.sh unless noted):
#   the leading "-" of the slug; the adopt pass; the commit; committing from the
#   store's status (not from this run's work); the clash check; the
#   owner != rel check; the several-candidates check; the unreachable-store
#   check; privacy in the adopt pass, in the link pass, and in the prune pass
#   (for .project-path entries and for legacy entries); the .git exclusion; the
#   repository-subdirectory rule; the dry-run guards on adopt and on detach; the
#   stray-symlink exclusion; copy verification; the adopt `ln` guard; the
#   late-write copy; the prune pass; the pass-2 legacy keep; the dangling-link
#   skip; the pass-3 memory-root check; the pass-3 existing-directory skip;
#   never replacing an existing link; following a chained link to its end; the
#   profile projects dirs; $CLAUDE_CONFIG_DIR; the time budget; keeping
#   conflicts across a deferred run; writing the conflict state file; removing
#   it when nothing conflicts; the conflict log; its once-a-day dedup; the
#   .project-path/.project-paths traversal guard; remote scheme, user, slash,
#   .git, scp-colon and host-case normalisation; origin adoption; discovery
#   privacy; migration privacy, origin ownership, active destination, clash,
#   verification and dry-run; migrated-link preservation; remote-prune privacy
#   and matching-slug retention; migrated-entry link skip; private-copy metadata
#   exclusion; .migrated-to key and target checks; and sync-health.sh's notice.
#   Two only where the machine can show them: the lock (needs flock) and the
#   200-character key cap (needs a short enough TMPDIR); a skip is printed.
# NOT mutated: the de-duplication of projects dirs by physical path (a second
# visit finds every link already right, so no output or state differs).
# A mutation whose anchor no longer matches exactly once is a failure.
#
# Every HOME, store and project is a throwaway directory; the real ~/.claude,
# the real profiles and the real store are never read or written
# (CLAUDE_CONFIG_DIR is cleared for that reason). No network: the fixture store
# has no remote, so sync-push.sh commits and does not push.
#
# Usage:
#   bash tests/test-sync-link-projects.sh        # run all tests
#   bash tests/test-sync-link-projects.sh -v     # verbose
# Internal:
#   SLP_SCRIPTS_DIR=DIR   test the sync scripts in DIR (needs DIR/../hooks)
#   SLP_ONLY="a b"        run only these sections
#   SLP_MUTANT=1          stop at the first failure; skip the mutation suite
#   SLP_JOBS=N            mutants run N at a time (default: CPU count, max 8)
#   SLP_SKIP_MUTATIONS=1  run every case, skip the mutation suite (used to show
#                         the cases fail against an older linker)

# SC2016: the mutation anchors are literal shell text, quoted on purpose.
# SC2012: ls output here only feeds failure messages.
# SC2329: the sections are called as "t_$name", which shellcheck cannot follow.
# shellcheck disable=SC2016,SC2012,SC2329
set -uo pipefail

# The suite runs inside Claude Code sessions, where CLAUDE_CONFIG_DIR names the
# REAL profile; the linker scans it. Never let a fixture reach it.
unset CLAUDE_CONFIG_DIR CLADE_PRIVATE_PROJECTS CLADE_SYNC_LINK_BUDGET CLADE_SYNC_PUSH_LOCK

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPTS="${SLP_SCRIPTS_DIR:-$REPO_ROOT/configs/scripts}"
HOOKS="$SCRIPTS/../hooks"
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
assert_not_contains() {
  if grep -qF -- "$2" <<< "$1"; then fail "$3" "output contains '$2'"; else pass "$3"; fi
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
store_commit() { (cd "$1/store" && git add -A && git commit -qm fixture) >/dev/null 2>&1; }
git_repo() { mkdir -p "$1" && git -C "$1" init -q . >/dev/null 2>&1; }
memdir() { printf '%s/.claude/projects/%s/memory' "$1" "$(slug_of "$2")"; }
remote_key_of() { printf '%s' "repo-$1" | LC_ALL=C sed 's/[^A-Za-z0-9]/-/g'; }
# run_slp HOME ARGS... — the linker, as sync-pull.sh runs it. Prefix
# SLP_BUDGET=, SLP_CCD= (CLAUDE_CONFIG_DIR), SLP_HOSTNAME=, SLP_PATH=,
# SLP_SHIM_MODE= to vary it.
run_slp() {
  local h=$1; shift
  HOME="$h" CLADE_RUNTIME_DIR="$h/.rt" CLAUDE_CONFIG_DIR="${SLP_CCD:-}" \
    HOSTNAME="${SLP_HOSTNAME:-test-host}" \
    CLADE_SYNC_LINK_BUDGET="${SLP_BUDGET:-0}" PATH="${SLP_PATH:-$PATH}" \
    SLP_SHIM_MODE="${SLP_SHIM_MODE:-}" \
    bash "$SCRIPTS/sync-link-projects.sh" "$@" 2>&1
}
run_health() { HOME="$1" bash "$HOOKS/sync-health.sh" 2>/dev/null; }
store_head() { git -C "$1/store" rev-parse HEAD 2>/dev/null; }
target_of() { local t; t=$(readlink "$1" 2>/dev/null) || return 1; printf '%s' "${t%/}"; }
real_dir() { [[ -d "$1" && ! -L "$1" ]]; }
no_links_inside() { [[ -z "$(find "$1" -mindepth 1 -type l 2>/dev/null)" ]]; }
snapshot_with_sums() {
  (cd "$1" && {
    find . -path ./store/.git -prune -o -print | LC_ALL=C sort
    find . -path ./store/.git -prune -o -type f -exec cksum {} + | LC_ALL=C sort
    find . -path ./store/.git -prune -o -type l -print | LC_ALL=C sort | while IFS= read -r f; do
      printf '%s -> %s\n' "$f" "$(readlink "$f")"
    done
    git -C store status --porcelain
    git -C store rev-parse HEAD
  })
}

# PATH shims for the race cases. They wrap the real tools and act only when
# SLP_SHIM_MODE names their case, so the linker under test is never edited.
SHIMBIN="$SANDBOX/shim-bin"
mkdir -p "$SHIMBIN"
REAL_MV=$(command -v mv); REAL_TAR=$(command -v tar)
cat > "$SHIMBIN/mv" <<EOF
#!/bin/sh
# mv shim: a write racing the adoption's move of <slug>/memory.
case "\${SLP_SHIM_MODE:-}:\$1" in
  late:*/memory) printf 'written late\n' > "\$1/late.md" ;;
esac
"$REAL_MV" "\$@" || exit \$?
case "\${SLP_SHIM_MODE:-}:\$1" in
  recreate:*/memory) mkdir -p "\$1" && printf 'concurrent\n' > "\$1/concurrent.md" ;;
esac
exit 0
EOF
cat > "$SHIMBIN/tar" <<EOF
#!/bin/sh
# tar shim: a slow extraction, or one that corrupts what it wrote.
case "\${SLP_SHIM_MODE:-}:\$1" in
  slow:-x*) sleep 2 ;;
esac
"$REAL_TAR" "\$@"; rc=\$?
case "\${SLP_SHIM_MODE:-}:\$1" in
  corrupt:-x*) f=\$(find . -type f -name '*.md' | head -1); [ -n "\$f" ] && printf 'X' >> "\$f" ;;
esac
exit \$rc
EOF
chmod +x "$SHIMBIN/mv" "$SHIMBIN/tar"

# ─── adopt: local memory moves into the store and gains history ──────

t_adopt() {
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
}

# ─── link: a store entry from another machine lands at the right slug ─

t_link() {
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
}

# ─── legacy: basename entries link only to a top-level memory root ────

t_legacy() {
section "legacy entries — exact top-level match, never a .git hit or a worktree"

new_home
git_repo "$H/projects/tools"
git_repo "$H/projects/host"
mkdir -p "$H/projects/host/.git/widgets"     # find -name widgets finds this first
mkdir -p "$H/store/projects-memory/tools" "$H/store/projects-memory/widgets"
printf 'tools memory\n' > "$H/store/projects-memory/tools/MEMORY.md"
printf 'widgets memory\n' > "$H/store/projects-memory/widgets/MEMORY.md"
# A linked worktree at top level: Claude Code keys its memory to the main
# checkout, so a legacy entry of the worktree's name must not link there.
git_repo "$H/projects/mainrepo"
git -C "$H/projects/mainrepo" -c user.email=t@example.com -c user.name=t -c core.hooksPath=/dev/null \
  commit -q --allow-empty -m init >/dev/null 2>&1
git -C "$H/projects/mainrepo" worktree add "$H/projects/wt" >/dev/null 2>&1
mkdir -p "$H/store/projects-memory/wt"
printf 'wt memory\n' > "$H/store/projects-memory/wt/MEMORY.md"
OUT=$(run_slp "$H")
assert_eq "$(cat "$(memdir "$H" "$H/projects/tools")/MEMORY.md" 2>/dev/null)" "tools memory" \
  "a legacy entry links to ~/projects/<name> at Claude Code's slug"
WHY="$(ls "$H/.claude/projects")"
check "a legacy entry whose only match is inside .git is not linked" \
  test -z "$(find "$H/.claude/projects" -name '*widgets*' -print)"
WHY="worktree setup: $(ls -a "$H/projects/wt" 2>&1 | tr '\n' ' '); slugs: $(ls "$H/.claude/projects")"
check "(fixture) the worktree exists" test -f "$H/projects/wt/.git"
check "a legacy entry whose top-level match is a linked worktree is not linked" \
  test ! -e "$(memdir "$H" "$H/projects/wt")"
}

# ─── prune: wrong-target links go, right ones stay ────────────────────

t_prune() {
section "prune — provably wrong links are removed, nothing else"

new_home
PM="$H/store/projects-memory"
git_repo "$H/projects/tools"
git_repo "$H/projects/mono"; mkdir -p "$H/projects/mono/sub"
git_repo "$H/projects/group/deep"
mkdir -p "$H/projects/my.app" "$H/projects/other" "$H/elsewhere-memory"
mkdir -p "$PM/tools" "$PM/clade" "$PM/sub" "$PM/projects-my-app" "$PM/deep"
printf 'legacy clade content\n' > "$PM/clade/MEMORY.md"
printf 'projects/my.app\n' > "$PM/projects-my-app/.project-path"
mklink() { mkdir -p "$H/.claude/projects/$1" && ln -s "$2" "$H/.claude/projects/$1/memory"; }
GOOD=$(slug_of "$H/projects/tools")
DEEP=$(slug_of "$H/projects/group/deep")
NODASH=$(slug_of "$H/projects/tools"); NODASH=${NODASH#-}
INGIT=$(slug_of "$H/projects/mono/.git/clade"); mkdir -p "$H/projects/mono/.git/clade"
GONE=$(slug_of "$H/projects/removed-long-ago")
SUBDIR=$(slug_of "$H/projects/mono/sub")
WRONGOWNER=$(slug_of "$H/projects/other")
OUTSIDE=$(slug_of "$H/projects/my.app")
mklink "$GOOD" "$PM/tools/"                   # trailing slash, as old links had
mklink "$DEEP" "$PM/deep"                     # a memory root below top level
mklink "$NODASH" "$PM/clade"
mklink "$INGIT" "$PM/clade/"
mklink "$GONE" "$PM/clade"
mklink "$SUBDIR" "$PM/sub"
mklink "$WRONGOWNER" "$PM/projects-my-app"
mklink "$OUTSIDE" "$H/elsewhere-memory"       # not into the store: not ours
mklink "dangling-no-dash" "$PM/no-such-entry" # dangling: left for a human
OUT=$(run_slp "$H")
PD="$H/.claude/projects"
check "kept: a legacy link at the project's own slug" test -L "$PD/$GOOD/memory"
assert_not_contains "$OUT" "pruned $GOOD/memory" \
  "and it was never pruned (pass 3 would relink a top-level one and hide that)"
check "kept: a legacy link at a memory root below top level (pass 3 cannot recreate it)" \
  test -L "$PD/$DEEP/memory"
check "kept: a dangling link into the store, even at a slug without '-'" \
  test -L "$PD/dangling-no-dash/memory"
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
}

# ─── conflict: nothing moves, and the conflict reaches a reader ───────

t_conflict() {
section "conflict — two versions of a file, or two owners of a name: nothing moves"

new_home
PM="$H/store/projects-memory"
mkdir -p "$H/projects/api" "$H/projects/web" "$H/projects/legacy" "$H/projects/x.y" "$H/projects/leg2"
mkdir -p "$PM/projects-api" "$PM/projects-web" "$PM/projects-legacy" "$PM/projects-x-y" "$PM/projects-leg2"
printf 'projects/api\n' > "$PM/projects-api/.project-path"
printf 'store version\n' > "$PM/projects-api/MEMORY.md"
printf 'projects/web\n' > "$PM/projects-web/.project-path"
printf 'same\n' > "$PM/projects-web/a.md"
printf 'old basename entry\n' > "$PM/projects-legacy/MEMORY.md"   # no .project-path
# Same store key, different owner, and NO file in common: only the owner check
# stands between this memory and another project's entry.
printf 'projects/x-y\n' > "$PM/projects-x-y/.project-path"
printf 'x-y memory\n' > "$PM/projects-x-y/a.md"
printf 'legacy two\n' > "$PM/projects-leg2/a.md"                  # no .project-path
store_commit "$H"
MA=$(memdir "$H" "$H/projects/api"); mkdir -p "$MA"; printf 'local version\n' > "$MA/MEMORY.md"
MW=$(memdir "$H" "$H/projects/web"); mkdir -p "$MW"; printf 'same\n' > "$MW/a.md"; printf 'only here\n' > "$MW/b.md"
ML=$(memdir "$H" "$H/projects/legacy"); mkdir -p "$ML"; printf 'mine\n' > "$ML/MEMORY.md"
MX=$(memdir "$H" "$H/projects/x.y"); mkdir -p "$MX"; printf 'x.y memory\n' > "$MX/only-here.md"
MG=$(memdir "$H" "$H/projects/leg2"); mkdir -p "$MG"; printf 'mine too\n' > "$MG/b.md"
OUT=$(run_slp "$H")
check "a local dir whose file differs from the store's stays a real directory" real_dir "$MA"
assert_eq "$(cat "$MA/MEMORY.md")" "local version" "with its own content"
WHY="inside: $(ls -A "$MA" | tr '\n' ' ')"
check "and the link pass plants nothing inside it (the old ln -sfn defect)" no_links_inside "$MA"
assert_eq "$(cat "$PM/projects-api/MEMORY.md")" "store version" "and the store's copy is not overwritten"
assert_contains "$OUT" "these files differ from projects-memory/projects-api: MEMORY.md" \
  "the conflict names the file"
check "files that are identical or new merge: adopted" test -L "$MW"
assert_eq "$(cat "$PM/projects-web/b.md" 2>/dev/null)" "only here" "the new file is in the store"
check "an entry of the same name that belongs to no project blocks adoption" real_dir "$ML"
assert_eq "$(cat "$PM/projects-legacy/MEMORY.md")" "old basename entry" "and is not overwritten"
check "an entry owned by another project blocks adoption with no file in common" real_dir "$MX"
check "and nothing of it reaches that project's entry" test ! -e "$PM/projects-x-y/only-here.md"
check "a legacy entry with no file in common blocks adoption too" real_dir "$MG"
check "and nothing of it reaches the legacy entry" test ! -e "$PM/projects-leg2/b.md"

# The run's output reaches nobody under the async hook; the record must.
STATE="$H/.claude/.sync-memory-conflicts"; LOG="$H/.claude/.sync-conflicts.log"
WHY="state file: $(cat "$STATE" 2>&1)"
check "the conflict is in ~/.claude/.sync-memory-conflicts" grep -qF "projects-memory/projects-api: MEMORY.md" "$STATE"
check "with the owner conflicts too" grep -qF "projects-memory/projects-x-y already belongs to ~/projects/x-y" "$STATE"
NLOG=$(grep -cF "these files differ from projects-memory/projects-api" "$LOG" 2>/dev/null)
assert_eq "${NLOG:-0}" "1" "and in ~/.claude/.sync-conflicts.log, once"
run_slp "$H" >/dev/null
NLOG=$(grep -cF "these files differ from projects-memory/projects-api" "$LOG" 2>/dev/null)
assert_eq "${NLOG:-0}" "1" "a second run the same day does not log it again"
HEALTH=$(run_health "$H")
assert_contains "$HEALTH" "project memory conflict" "sync-health.sh announces it at session start"
assert_contains "$HEALTH" "projects-memory/projects-api: MEMORY.md" "naming the conflict"

# Resolved by hand: the record goes, and so does the notice.
new_home
mkdir -p "$H/projects/api" "$H/store/projects-memory/projects-api"
printf 'projects/api\n' > "$H/store/projects-memory/projects-api/.project-path"
printf 'store version\n' > "$H/store/projects-memory/projects-api/MEMORY.md"
store_commit "$H"
MA=$(memdir "$H" "$H/projects/api"); mkdir -p "$MA"; printf 'local version\n' > "$MA/MEMORY.md"
run_slp "$H" >/dev/null
STATE="$H/.claude/.sync-memory-conflicts"
check "(fixture) a conflict is recorded" test -s "$STATE"
printf 'store version\n' > "$MA/MEMORY.md"
run_slp "$H" >/dev/null
check "once merged it is adopted" test -L "$MA"
check "and the state file is gone" test ! -e "$STATE"
assert_not_contains "$(run_health "$H")" "project memory conflict" "sync-health.sh says nothing more"
}

# ─── private: never leaves this machine, in any pass ─────────────────

t_private() {
section "private — private-projects and conversation-mode stay local in every pass"

new_home
PM="$H/store/projects-memory"
mkdir -p "$H/projects/diary" "$H/projects/chat/.claude"
: > "$H/projects/chat/.claude/conversation-mode"
MD=$(memdir "$H" "$H/projects/diary"); mkdir -p "$MD"; printf 'personal\n' > "$MD/MEMORY.md"
MC=$(memdir "$H" "$H/projects/chat"); mkdir -p "$MC"; printf 'chatty\n' > "$MC/MEMORY.md"
# The link pass: entries written by another host, for projects private here.
mkdir -p "$H/projects/chat2/.claude" "$H/projects/notes" "$PM/projects-chat2" "$PM/notes"
: > "$H/projects/chat2/.claude/conversation-mode"
printf 'projects/chat2\n' > "$PM/projects-chat2/.project-path"
printf 'from another host\n' > "$PM/projects-chat2/MEMORY.md"
printf 'legacy notes\n' > "$PM/notes/MEMORY.md"
# The prune pass: links that already exist into the store, for private projects.
mkdir -p "$H/projects/journal/.claude" "$H/projects/vault" "$PM/projects-journal" "$PM/vault"
: > "$H/projects/journal/.claude/conversation-mode"
printf 'projects/journal\n' > "$PM/projects-journal/.project-path"
printf 'journal memory\n' > "$PM/projects-journal/MEMORY.md"
printf 'vault memory\n' > "$PM/vault/MEMORY.md"
MJ=$(memdir "$H" "$H/projects/journal"); mkdir -p "${MJ%/memory}"; ln -s "$PM/projects-journal" "$MJ"
MV=$(memdir "$H" "$H/projects/vault"); mkdir -p "${MV%/memory}"; ln -s "$PM/vault" "$MV"
store_commit "$H"
printf '# private\n%s\n%s\n%s\n' "$H/projects/diary" "$H/projects/notes" "$H/projects/vault" \
  > "$H/.claude/private-projects"
OUT=$(run_slp "$H")
check "adopt: a project in private-projects is not adopted" real_dir "$MD"
check "adopt: a conversation-mode project is not adopted" real_dir "$MC"
WHY="$(git -C "$H/store" log --all --name-only --format= 2>/dev/null | tr '\n' ' ')"
check "adopt: neither reaches the store or its history" \
  test -z "$(git -C "$H/store" log --all --name-only --format= -- projects-memory/projects-diary projects-memory/projects-chat 2>/dev/null)" \
  -a ! -e "$PM/projects-diary" -a ! -e "$PM/projects-chat"
WHY="slugs: $(ls "$H/.claude/projects" | tr '\n' ' ')"
check "link: a conversation-mode project is not linked to its .project-path entry" \
  test ! -e "$(memdir "$H" "$H/projects/chat2")"
check "link: a private-projects project is not linked to a legacy entry of its name" \
  test ! -e "$(memdir "$H" "$H/projects/notes")"
check "prune: a conversation-mode project's link into the store is replaced by a real directory" real_dir "$MJ"
assert_eq "$(cat "$MJ/MEMORY.md" 2>/dev/null)" "journal memory" "holding the entry's memory"
check "without the store's .project-path" test ! -e "$MJ/.project-path"
check "prune: a private-projects project's link to a legacy entry is detached too" real_dir "$MV"
assert_eq "$(cat "$MV/MEMORY.md" 2>/dev/null)" "vault memory" "holding that entry's memory"
assert_eq "$(cat "$PM/projects-journal/MEMORY.md" 2>/dev/null)" "journal memory" \
  "the store entry itself is left alone (removing it is a human's decision)"
assert_contains "$OUT" "detached $(slug_of "$H/projects/journal")/memory" "the detach is reported"
check "and logged durably as a privacy event" grep -qF "privacy: $(slug_of "$H/projects/journal") is a private project" \
  "$H/.claude/.sync-conflicts.log"
# Control: the same directory IS adopted once the registry no longer lists it,
# so the absence above was the guard's doing.
rm -f "$H/.claude/private-projects"
run_slp "$H" >/dev/null
check "control: without the registry entry it would have been adopted" test -L "$MD"
}

# ─── dry-run: changes nothing ────────────────────────────────────────

t_dryrun() {
section "dry-run — reports, changes nothing"

new_home
PM="$H/store/projects-memory"
mkdir -p "$H/projects/alpha" "$H/projects/beta" "$PM/projects-beta" "$H/projects/gam" "$PM/projects-gam"
printf 'projects/beta\n' > "$PM/projects-beta/.project-path"
printf 'projects/gam\n' > "$PM/projects-gam/.project-path"
printf 'store\n' > "$PM/projects-gam/MEMORY.md"
mkdir -p "$H/projects/priv/.claude" "$PM/projects-priv"
: > "$H/projects/priv/.claude/conversation-mode"
printf 'projects/priv\n' > "$PM/projects-priv/.project-path"
printf 'private\n' > "$PM/projects-priv/MEMORY.md"
MPR=$(memdir "$H" "$H/projects/priv"); mkdir -p "${MPR%/memory}"; ln -s "$PM/projects-priv" "$MPR"
MAL=$(memdir "$H" "$H/projects/alpha"); mkdir -p "$MAL"; printf 'a\n' > "$MAL/MEMORY.md"
MGA=$(memdir "$H" "$H/projects/gam"); mkdir -p "$MGA"; printf 'local\n' > "$MGA/MEMORY.md"
mkdir -p "$H/.claude/projects/stale-no-dash"
ln -s "$PM/projects-beta" "$H/.claude/projects/stale-no-dash/memory"
snapshot() { (cd "$H" && find . -path ./store/.git -prune -o -print | LC_ALL=C sort | while IFS= read -r f; do
  if [[ -L "$f" ]]; then printf '%s -> %s\n' "$f" "$(readlink "$f")"; else printf '%s\n' "$f"; fi
done; git -C store status --porcelain; git -C store rev-parse HEAD); }
BEFORE=$(snapshot)
OUT=$(run_slp "$H" --dry-run)
assert_eq "$(snapshot)" "$BEFORE" "the tree, every link, the store and ~/.claude (no log, no state) are unchanged"
assert_contains "$OUT" "would adopt $(slug_of "$H/projects/alpha")" "it says what it would adopt"
assert_contains "$OUT" "would prune stale-no-dash/memory" "what it would prune"
assert_contains "$OUT" "would link $(slug_of "$H/projects/beta")/memory -> projects-memory/projects-beta" \
  "and what it would link"
assert_contains "$OUT" "would detach $(slug_of "$H/projects/priv")/memory" "and what it would detach"
assert_contains "$OUT" "conflict: $(slug_of "$H/projects/gam") is not adopted" "and the conflicts"
}

# ─── wiring: the SessionStart hook runs the chain ────────────────────

t_wiring() {
section "wiring — sync-pull.sh adopts and commits"

new_home
mkdir -p "$H/projects/gamma"
MG=$(memdir "$H" "$H/projects/gamma"); mkdir -p "$MG"; printf 'gamma memory\n' > "$MG/MEMORY.md"
HOME="$H" CLADE_RUNTIME_DIR="$H/.rt" bash "$SCRIPTS/sync-pull.sh" >/dev/null 2>&1 || true
assert_eq "$(git -C "$H/store" show HEAD:projects-memory/projects-gamma/MEMORY.md 2>/dev/null)" \
  "gamma memory" "after a session start the memory is in the store's history"
}

# ─── ambiguous: a slug two directories share is not adopted ───────────

t_ambiguous() {
section "ambiguous — ~/projects/my.app and ~/projects/my-app share one slug"

new_home
mkdir -p "$H/projects/my.app" "$H/projects/my-app"
MM=$(memdir "$H" "$H/projects/my.app"); mkdir -p "$MM"; printf 'whose?\n' > "$MM/MEMORY.md"
OUT=$(run_slp "$H" --verbose)
check "the memory stays a real directory" real_dir "$MM"
WHY="store holds: $(ls -A "$H/store/projects-memory" | tr '\n' ' ')"
check "and no entry is made for either project" test -z "$(ls -A "$H/store/projects-memory")"
assert_contains "$OUT" "several directories share this slug" "the skip says why"
}

# ─── store: an unreachable SYNC_DIR creates nothing ──────────────────

t_store() {
section "store — SYNC_DIR missing (NFS dropped): no shadow store under the mount point"

new_home
mkdir -p "$H/nfs"                                   # the mount point, empty
printf 'SYNC_BACKEND=nfs\nSYNC_DIR=%s\n' "$H/nfs/dotfiles" > "$H/.claude/.sync-config"
mkdir -p "$H/projects/foo"
MF=$(memdir "$H" "$H/projects/foo"); mkdir -p "$MF"; printf 'foo\n' > "$MF/MEMORY.md"
run_slp "$H" >/dev/null
check "nothing is created where the store should be" test ! -e "$H/nfs/dotfiles"
check "the memory stays a real directory" real_dir "$MF"
}

# ─── profiles: every projects directory Claude Code reads ─────────────

t_profiles() {
section "profiles — ~/.claude-profiles/*/projects and \$CLAUDE_CONFIG_DIR/projects"

new_home
PM="$H/store/projects-memory"
P1="$H/.claude-profiles/p1/projects"; CFG="$H/cfg"
mkdir -p "$P1" "$CFG/projects"
ln -s "$H/.claude" "$H/.claude-profiles/main"       # an alias of ~/.claude
mkdir -p "$H/projects/alpha" "$H/projects/beta" "$H/projects/gamma" "$PM/projects-gamma"
SA=$(slug_of "$H/projects/alpha"); SB=$(slug_of "$H/projects/beta"); SG=$(slug_of "$H/projects/gamma")
mkdir -p "$P1/$SA/memory"; printf 'alpha, written under profile p1\n' > "$P1/$SA/memory/MEMORY.md"
mkdir -p "$CFG/projects/$SB/memory"; printf 'beta, written under CLAUDE_CONFIG_DIR\n' > "$CFG/projects/$SB/memory/MEMORY.md"
printf 'projects/gamma\n' > "$PM/projects-gamma/.project-path"
printf 'gamma memory\n' > "$PM/projects-gamma/MEMORY.md"
# The layout a host already has: ~/.claude links into the store, and a profile
# links to ~/.claude's link. Followed to the end, that is the same entry.
mkdir -p "$H/.claude/projects/$SG" "$P1/$SG"
ln -s "$PM/projects-gamma" "$H/.claude/projects/$SG/memory"
ln -s "$H/.claude/projects/$SG/memory" "$P1/$SG/memory"
store_commit "$H"
OUT=$(SLP_CCD="$CFG" run_slp "$H")
check "a profile's real memory dir is adopted" test -L "$P1/$SA/memory"
assert_eq "$(cat "$PM/projects-alpha/MEMORY.md" 2>/dev/null)" "alpha, written under profile p1" "into the store"
assert_contains "$OUT" "adopted ~/.claude-profiles/p1/projects/$SA -> projects-memory/projects-alpha" \
  "and reported with its projects directory"
check "a \$CLAUDE_CONFIG_DIR memory dir is adopted" test -L "$CFG/projects/$SB/memory"
assert_eq "$(cat "$PM/projects-beta/MEMORY.md" 2>/dev/null)" "beta, written under CLAUDE_CONFIG_DIR" "into the store"
assert_eq "$(cat "$CFG/projects/$SG/memory/MEMORY.md" 2>/dev/null)" "gamma memory" \
  "a store entry is linked into \$CLAUDE_CONFIG_DIR/projects too"
assert_eq "$(cat "$P1/$SA/memory/MEMORY.md" 2>/dev/null)" "alpha, written under profile p1" \
  "and the profile reads its memory through the link"
assert_not_contains "$OUT" "conflict" "a profile link chained through ~/.claude to the entry is not a conflict"
check "and it is kept as it was" test "$(readlink "$P1/$SG/memory")" = "$H/.claude/projects/$SG/memory"
}

# ─── commit: an adoption whose commit was lost is committed later ─────

t_commit() {
section "commit — decided by the store's own state, so a lost commit is retried"

new_home
PM="$H/store/projects-memory"
mkdir -p "$H/projects/kappa" "$PM/projects-kappa"
# What a run killed after `ln -s`, or one whose sync-push found its lock held,
# leaves behind: an entry and its link, never committed.
printf 'projects/kappa\n' > "$PM/projects-kappa/.project-path"
printf 'kappa memory\n' > "$PM/projects-kappa/MEMORY.md"
MK=$(memdir "$H" "$H/projects/kappa"); mkdir -p "${MK%/memory}"; ln -s "$PM/projects-kappa" "$MK"
BASE=$(store_head "$H")
OUT=$(run_slp "$H")
assert_eq "$OUT" "" "(fixture) this run has nothing to adopt, prune or link"
assert_eq "$(git -C "$H/store" show HEAD:projects-memory/projects-kappa/MEMORY.md 2>/dev/null)" \
  "kappa memory" "yet the uncommitted entry is committed"
WHY="HEAD stayed at $BASE"
check "by a new commit" test "$(store_head "$H")" != "$BASE"
}

# ─── budget: past the time budget the rest waits for the next run ─────

t_budget() {
section "budget — the async hook's 30 s: defer the rest, keep their conflicts"

new_home
PM="$H/store/projects-memory"
mkdir -p "$H/projects/a1" "$H/projects/a2" "$H/projects/zz" "$PM/projects-zz"
printf 'projects/zz\n' > "$PM/projects-zz/.project-path"
printf 'store\n' > "$PM/projects-zz/MEMORY.md"
store_commit "$H"
MZ=$(memdir "$H" "$H/projects/zz"); mkdir -p "$MZ"; printf 'local\n' > "$MZ/MEMORY.md"
run_slp "$H" >/dev/null
STATE="$H/.claude/.sync-memory-conflicts"
check "(fixture) a complete run records the zz conflict" grep -qF "projects-memory/projects-zz" "$STATE"
M1=$(memdir "$H" "$H/projects/a1"); mkdir -p "$M1"; printf 'one\n' > "$M1/MEMORY.md"
M2=$(memdir "$H" "$H/projects/a2"); mkdir -p "$M2"; printf 'two\n' > "$M2/MEMORY.md"
# A 1 s budget and a copy that takes 2 s: one adoption, then the budget is spent.
OUT=$(SLP_BUDGET=1 SLP_PATH="$SHIMBIN:$PATH" SLP_SHIM_MODE=slow run_slp "$H")
N=0; [[ -L "$M1" ]] && N=$((N + 1)); [[ -L "$M2" ]] && N=$((N + 1))
assert_eq "$N" "1" "one directory is adopted within the budget, the other waits"
assert_contains "$OUT" "deferred: 2 memory directories to the next run" "the deferral is reported (a2 and zz)"
WHY="state: $(cat "$STATE" 2>&1)"
check "the conflict of a directory this run never examined is kept" grep -qF "projects-memory/projects-zz" "$STATE"
SLP_BUDGET=1 run_slp "$H" >/dev/null
check "the next run adopts the rest" test -L "$M1" -a -L "$M2"
}

# ─── races: verification, a recreated dir, a late write ───────────────

t_races() {
section "races — a bad copy, a directory recreated mid-move, a write landing mid-move"

new_home
mkdir -p "$H/projects/vc"
MVC=$(memdir "$H" "$H/projects/vc"); mkdir -p "$MVC"; printf 'original\n' > "$MVC/MEMORY.md"
OUT=$(SLP_PATH="$SHIMBIN:$PATH" SLP_SHIM_MODE=corrupt run_slp "$H")
check "a copy that does not verify leaves the memory a real directory" real_dir "$MVC"
assert_eq "$(cat "$MVC/MEMORY.md" 2>/dev/null)" "original" "with its content"
assert_contains "$OUT" "does not match" "and the mismatch is reported"

new_home
mkdir -p "$H/projects/rc"
MRC=$(memdir "$H" "$H/projects/rc"); mkdir -p "$MRC"; printf 'original\n' > "$MRC/MEMORY.md"
SLP_PATH="$SHIMBIN:$PATH" SLP_SHIM_MODE=recreate run_slp "$H" >/dev/null
check "a memory dir recreated during the move is left a real directory" real_dir "$MRC"
WHY="inside: $(ls -A "$MRC" | tr '\n' ' ')"
check "with no link planted inside it" no_links_inside "$MRC"

new_home
mkdir -p "$H/projects/lw"
MLW=$(memdir "$H" "$H/projects/lw"); mkdir -p "$MLW"; printf 'original\n' > "$MLW/MEMORY.md"
SLP_PATH="$SHIMBIN:$PATH" SLP_SHIM_MODE=late run_slp "$H" >/dev/null
check "(fixture) the directory is adopted" test -L "$MLW"
assert_eq "$(cat "$MLW/late.md" 2>/dev/null)" "written late" \
  "a write that landed between the copy and the move is readable through the link"
}

# ─── lock: one linker at a time ──────────────────────────────────────

t_lock() {
section "lock — a second linker while one runs changes nothing"

if ! command -v flock >/dev/null 2>&1; then
  echo "  (no flock on this machine: the linker runs unlocked here, so there is nothing to test)"
  return 0
fi
new_home
mkdir -p "$H/projects/lk" "$H/.rt"; chmod 700 "$H/.rt"
MLK=$(memdir "$H" "$H/projects/lk"); mkdir -p "$MLK"; printf 'x\n' > "$MLK/MEMORY.md"
( exec 9>"$H/.rt/sync-link-projects.lock"; flock -n 9 || exit 1; run_slp "$H" >/dev/null )
check "while another holds the lock, the memory dir is not touched" real_dir "$MLK"
run_slp "$H" >/dev/null
check "control: with the lock free it is adopted" test -L "$MLK"
}

# ─── limits: key length, and a .project-path that climbs out ──────────

LONG=$(printf '%0201d' 0 | tr 0 k)
long_key_possible() { [[ $(( ${#SANDBOX} + 12 + ${#LONG} )) -le 250 ]]; }

t_limits() {
section "limits — a store key past 200 characters; .project-path outside \$HOME"

new_home
mkdir -p "$SANDBOX/outside-$NHOME" "$H/store/projects-memory/evil"
printf '../outside-%s\n' "$NHOME" > "$H/store/projects-memory/evil/.project-path"
printf 'evil\n' > "$H/store/projects-memory/evil/MEMORY.md"
OUT=$(run_slp "$H")
WHY="links: $(find "$H/.claude/projects" -type l | tr '\n' ' ')"
check "an entry whose .project-path climbs out of \$HOME is linked nowhere" \
  test -z "$(find "$H/.claude/projects" -type l)"

if long_key_possible; then
  mkdir -p "$H/$LONG"
  MLG=$(memdir "$H" "$H/$LONG"); mkdir -p "$MLG"; printf 'long\n' > "$MLG/MEMORY.md"
  run_slp "$H" >/dev/null
  check "a project whose store key would pass 200 characters is not adopted" real_dir "$MLG"
else
  echo "  (TMPDIR too long for a 201-character key under a 255-byte slug: skipped)"
fi
}

# ─── remote: one repository identity, per-host paths, safe migration ──

t_remote() {
section "remote — two paths, one repository memory"

new_home; HA=$H
new_home; HB=$H
printf 'SYNC_BACKEND=nfs\nSYNC_DIR=%s\n' "$HA/store" > "$HB/.claude/.sync-config"
git_repo "$HA/projects/Clade"
git -C "$HA/projects/Clade" remote add origin 'git@GitHub.com:Owner/Repo.git'
git_repo "$HB/shenxingy-Clade"
git -C "$HB/shenxingy-Clade" remote add origin 'https://git@github.com/Owner/Repo.git/'
MA=$(memdir "$HA" "$HA/projects/Clade"); mkdir -p "$MA"
printf 'written on aries\n' > "$MA/MEMORY.md"
OUT_A=$(SLP_HOSTNAME=aries run_slp "$HA")
RK=$(remote_key_of 'github.com/Owner/Repo')
E="$HA/store/projects-memory/$RK"
assert_eq "$(cat "$E/.project-remote" 2>/dev/null)" "github.com/Owner/Repo" \
  "scheme, user, scp colon, .git, slash and host case normalise to one identity"
assert_eq "$(target_of "$MA")" "$E" "host A adopts into the remote-keyed entry"
check "a remote-keyed entry has no machine-specific .project-path" test ! -e "$E/.project-path"
check "host A records its path relative to its HOME" \
  grep -qFx "$(printf 'aries\tprojects/Clade')" "$E/.project-paths"
assert_not_contains "$OUT_A" "conflict" "host A's adoption has no conflict"
MB=$(memdir "$HB" "$HB/shenxingy-Clade"); mkdir -p "${MB%/memory}"
OUT_B=$(SLP_HOSTNAME=shenxingy run_slp "$HB")
assert_eq "$(target_of "$MB")" "$E" "host B discovers the same origin at its different path and links it"
check "host B appends its own path without changing host A's" \
  grep -qFx "$(printf 'shenxingy\tshenxingy-Clade')" "$E/.project-paths"
assert_eq "$(grep -cFx "$(printf 'aries\tprojects/Clade')" "$E/.project-paths" 2>/dev/null)" "1" \
  "host A's line is still there exactly once"
printf 'visible through the shared identity\n' > "$MA/from-aries.md"
assert_eq "$(cat "$MB/from-aries.md" 2>/dev/null)" "visible through the shared identity" \
  "a memory written through host A is readable through host B"
rm -rf "$HB/shenxingy-Clade"
git_repo "$HB/moved/Clade"
git -C "$HB/moved/Clade" remote add origin 'git@github.com:Owner/Repo.git'
MM=$(memdir "$HB" "$HB/moved/Clade"); mkdir -p "$MM"; printf 'after a move\n' > "$MM/moved.md"
OUT_MOVE=$(SLP_HOSTNAME=shenxingy run_slp "$HB")
assert_eq "$(target_of "$MM")" "$E" "adopting after a real move adds the new checkout path"
assert_eq "$(grep -c '^shenxingy' "$E/.project-paths" 2>/dev/null)" "2" \
  "the old and new paths both remain: a missing NFS path is not a deleted checkout"
check "the moved checkout's line is added" \
  grep -qFx "$(printf 'shenxingy\tmoved/Clade')" "$E/.project-paths"
check "the stale line is kept after the old directory really was removed" \
  grep -qFx "$(printf 'shenxingy\tshenxingy-Clade')" "$E/.project-paths"
assert_eq "$(target_of "$MB")" "$E" "the old memory link remains harmless beside the stale path"
assert_eq "$(SLP_HOSTNAME=shenxingy run_slp "$HB")" "" "host B's next run is idempotent"
assert_not_contains "$OUT_B" "conflict" "host B's discovery has no conflict"
assert_not_contains "$OUT_MOVE" "conflict" "the moved checkout has no conflict"

section "remote migration — both hosts' legacy pairs converge"
new_home; HA=$H
new_home; HB=$H
printf 'SYNC_BACKEND=nfs\nSYNC_DIR=%s\n' "$HA/store" > "$HB/.claude/.sync-config"
git_repo "$HA/projects/Clade"
git -C "$HA/projects/Clade" remote add origin 'git@github.com:Owner/Repo.git'
git_repo "$HB/shenxingy-Clade"
git -C "$HB/shenxingy-Clade" remote add origin 'https://github.com/Owner/Repo.git'
PM="$HA/store/projects-memory"; LA="$PM/projects-Clade"; LB="$PM/shenxingy-Clade"; E="$PM/$RK"
mkdir -p "$LA" "$LB"
printf 'projects/Clade\n' > "$LA/.project-path"; printf 'from aries\n' > "$LA/aries.md"
printf 'shenxingy-Clade\n' > "$LB/.project-path"; printf 'from the Mac\n' > "$LB/mac.md"
MA=$(memdir "$HA" "$HA/projects/Clade"); mkdir -p "${MA%/memory}"; ln -s "$LA" "$MA"
MB=$(memdir "$HB" "$HB/shenxingy-Clade"); mkdir -p "${MB%/memory}"; ln -s "$LB" "$MB"
store_commit "$HA"
SLP_HOSTNAME=aries run_slp "$HA" >/dev/null
SLP_HOSTNAME=shenxingy run_slp "$HB" >/dev/null
assert_eq "$(target_of "$MA")" "$E" "host A retires projects-Clade onto the shared entry"
assert_eq "$(target_of "$MB")" "$E" "host B retires shenxingy-Clade onto that same entry"
assert_eq "$(cat "$LA/.migrated-to" 2>/dev/null)" "$RK" "host A's legacy entry remains marked"
assert_eq "$(cat "$LB/.migrated-to" 2>/dev/null)" "$RK" "host B's legacy entry remains marked"
assert_eq "$(cat "$MB/aries.md" 2>/dev/null)" "from aries" "host A's legacy memory is readable through host B"
assert_eq "$(cat "$MA/mac.md" 2>/dev/null)" "from the Mac" "and host B's through host A"
check "host A's legacy path is recorded beside its hostname" \
  grep -qFx "$(printf 'aries\tprojects/Clade')" "$E/.project-paths"
assert_eq "$(grep -cFx "$(printf 'shenxingy\tshenxingy-Clade')" "$E/.project-paths" 2>/dev/null)" "1" \
  "host B's different legacy path is recorded once beside its hostname"
N=$(find "$PM" -type d -name 'repo-*' -print | grep -c .)
assert_eq "$N" "1" "the two legacy pairs produce exactly one remote-keyed entry"

section "remote migration — union, marker, relink and preserved original"
new_home
PM="$H/store/projects-memory"
git_repo "$H/projects/Clade"
git -C "$H/projects/Clade" remote add origin 'git@github.com:Owner/Repo.git'
L="$PM/projects-Clade"; E="$PM/$RK"
mkdir -p "$L" "$E"
printf 'projects/Clade\n' > "$L/.project-path"
printf 'legacy only\n' > "$L/legacy.md"
printf 'same\n' > "$L/shared.md"
printf 'github.com/Owner/Repo\n' > "$E/.project-remote"
printf 'remote only\n' > "$E/remote.md"
printf 'same\n' > "$E/shared.md"
M=$(memdir "$H" "$H/projects/Clade"); mkdir -p "${M%/memory}"; ln -s "$L" "$M"
store_commit "$H"
OUT=$(SLP_HOSTNAME=aries run_slp "$H")
assert_eq "$(cat "$L/.migrated-to" 2>/dev/null)" "$RK" "the legacy entry stays and names its replacement"
assert_eq "$(cat "$L/legacy.md" 2>/dev/null)" "legacy only" "legacy store content is never deleted"
assert_eq "$(cat "$E/legacy.md" 2>/dev/null)" "legacy only" "legacy-only content reaches the remote entry"
assert_eq "$(cat "$E/remote.md" 2>/dev/null)" "remote only" "remote-only content stays: the migration is a union"
check "the remote entry does not inherit .project-path" test ! -e "$E/.project-path"
check "migration records this host's path" grep -qFx "$(printf 'aries\tprojects/Clade')" "$E/.project-paths"
assert_eq "$(target_of "$M")" "$E" "this host's slug is relinked to the remote entry"
BK=$(ls -d "${M%/memory}"/memory.pre-sync-* 2>/dev/null | head -1)
assert_eq "$(target_of "$BK")" "$L" "the original link is preserved beside the new one"
assert_not_contains "$OUT" "claims the same project" "the retired legacy entry does not fight its replacement"
HEAD1=$(store_head "$H")
assert_eq "$(SLP_HOSTNAME=aries run_slp "$H")" "" "a migrated pair is quiet on the next run"
assert_eq "$(store_head "$H")" "$HEAD1" "and makes no new commit"
git_repo "$H/projects/other"
MW=$(memdir "$H" "$H/projects/other"); mkdir -p "${MW%/memory}"; ln -s "$E" "$MW"
SLP_HOSTNAME=aries run_slp "$H" >/dev/null
check "a remote entry link at another project's slug is pruned" test ! -e "$MW"

section "remote migration — a differing file blocks the whole entry"
new_home
PM="$H/store/projects-memory"
git_repo "$H/projects/Clade"
git -C "$H/projects/Clade" remote add origin 'git@github.com:Owner/Repo.git'
L="$PM/projects-Clade"; E="$PM/$RK"
mkdir -p "$L" "$E"
printf 'projects/Clade\n' > "$L/.project-path"
printf 'legacy version\n' > "$L/MEMORY.md"
printf 'must not move\n' > "$L/legacy.md"
printf 'github.com/Owner/Repo\n' > "$E/.project-remote"
printf 'remote version\n' > "$E/MEMORY.md"
M=$(memdir "$H" "$H/projects/Clade"); mkdir -p "${M%/memory}"; ln -s "$L" "$M"
store_commit "$H"
OUT=$(run_slp "$H")
check "a conflict writes no migration marker" test ! -e "$L/.migrated-to"
assert_eq "$(cat "$L/MEMORY.md")" "legacy version" "the legacy version is untouched"
assert_eq "$(cat "$E/MEMORY.md")" "remote version" "the remote version is untouched"
check "no other file from the conflicted entry moves" test ! -e "$E/legacy.md"
assert_eq "$(target_of "$M")" "$L" "the old link stays while the migration is blocked"
assert_contains "$OUT" "projects-memory/projects-Clade is not migrated to projects-memory/$RK" \
  "the migration conflict names both entries"
assert_contains "$OUT" "MEMORY.md" "and the differing file"
check "the migration conflict reaches the state file" \
  grep -qF "projects-memory/projects-Clade is not migrated to projects-memory/$RK" "$H/.claude/.sync-memory-conflicts"
check "and the durable conflict log" \
  grep -qF "projects-memory/projects-Clade is not migrated to projects-memory/$RK" "$H/.claude/.sync-conflicts.log"

section "remote migration — a mismatched or retired destination is not taken over"
new_home
PM="$H/store/projects-memory"
git_repo "$H/projects/Clade"
git -C "$H/projects/Clade" remote add origin 'git@github.com:Owner/Repo.git'
L="$PM/projects-Clade"; E="$PM/$RK"
mkdir -p "$L" "$E"
printf 'projects/Clade\n' > "$L/.project-path"; printf 'legacy\n' > "$L/legacy.md"
printf 'github.com/Other/Repo\n' > "$E/.project-remote"
M=$(memdir "$H" "$H/projects/Clade"); mkdir -p "$M"; printf 'local\n' > "$M/local.md"
store_commit "$H"
OUT=$(run_slp "$H")
check "adoption does not take over a key carrying another origin" real_dir "$M"
check "migration does not mark its source after the identity mismatch" test ! -e "$L/.migrated-to"
check "neither local nor legacy content enters the mismatched entry" \
  test ! -e "$E/local.md" -a ! -e "$E/legacy.md"
assert_contains "$OUT" "already belongs to origin github.com/Other/Repo" "the adoption identity conflict is named"
assert_contains "$OUT" "the destination belongs to origin github.com/Other/Repo" "the migration identity conflict is named"
printf 'github.com/Owner/Repo\n' > "$E/.project-remote"
printf 'repo-retired-target\n' > "$E/.migrated-to"
OUT=$(run_slp "$H")
check "a retired destination does not absorb a local adoption" real_dir "$M"
check "or a legacy migration" test ! -e "$L/.migrated-to" -a ! -e "$E/legacy.md"
assert_contains "$OUT" "the destination is not an active entry" "the retired destination conflict is named"

section "remote migration — dry-run changes no byte"
new_home
PM="$H/store/projects-memory"
git_repo "$H/projects/Clade"
git -C "$H/projects/Clade" remote add origin 'git@github.com:Owner/Repo.git'
L="$PM/projects-Clade"; E="$PM/$RK"
mkdir -p "$L"; printf 'projects/Clade\n' > "$L/.project-path"; printf 'legacy\n' > "$L/MEMORY.md"
M=$(memdir "$H" "$H/projects/Clade"); mkdir -p "${M%/memory}"
store_commit "$H"
BEFORE=$(snapshot_with_sums "$H")
OUT=$(run_slp "$H" --dry-run)
assert_eq "$(snapshot_with_sums "$H")" "$BEFORE" \
  "full tree listing, every file cksum, every link target and git state are unchanged"
assert_contains "$OUT" "would migrate projects-memory/projects-Clade -> projects-memory/$RK" \
  "dry-run names the migration"
assert_contains "$OUT" "would link $(slug_of "$H/projects/Clade")/memory -> projects-memory/$RK" \
  "and the link that would replace the legacy one"
assert_not_contains "$OUT" "would link $(slug_of "$H/projects/Clade")/memory -> projects-memory/projects-Clade" \
  "and does not also claim it would link the entry it just retired"
check "dry-run writes no conflict state or log" \
  test ! -e "$H/.claude/.sync-memory-conflicts" -a ! -e "$H/.claude/.sync-conflicts.log"

section "remote migration — private projects and no-origin fallback"
new_home
PM="$H/store/projects-memory"
git_repo "$H/projects/diary"
git -C "$H/projects/diary" remote add origin 'git@github.com:Owner/Private.git'
RK_PRIVATE=$(remote_key_of 'github.com/Owner/Private')
L="$PM/projects-diary"
mkdir -p "$L"; printf 'projects/diary\n' > "$L/.project-path"; printf 'personal\n' > "$L/MEMORY.md"
M=$(memdir "$H" "$H/projects/diary"); mkdir -p "${M%/memory}"; ln -s "$L" "$M"
printf '%s\n' "$H/projects/diary" > "$H/.claude/private-projects"
store_commit "$H"
run_slp "$H" >/dev/null
check "a private legacy entry is never migrated" test ! -e "$PM/$RK_PRIVATE"
check "and gains no migration marker" test ! -e "$L/.migrated-to"
check "privacy still detaches its existing store link" real_dir "$M"
assert_eq "$(cat "$M/MEMORY.md")" "personal" "the private memory stays readable locally"
check "without copying legacy metadata into the detached memory" test ! -e "$M/.project-path"

new_home
PM="$H/store/projects-memory"
git_repo "$H/projects/chat"; mkdir -p "$H/projects/chat/.claude"
: > "$H/projects/chat/.claude/conversation-mode"
git -C "$H/projects/chat" remote add origin 'git@github.com:Owner/Private.git'
E="$PM/$RK_PRIVATE"; mkdir -p "$E"
printf 'github.com/Owner/Private\n' > "$E/.project-remote"; printf 'private remote\n' > "$E/MEMORY.md"
M=$(memdir "$H" "$H/projects/chat"); mkdir -p "${M%/memory}"; ln -s "$E" "$M"
store_commit "$H"
run_slp "$H" >/dev/null
check "a private project's remote-entry link is detached" real_dir "$M"
check "remote identity metadata is not copied into private memory" \
  test ! -e "$M/.project-remote" -a ! -e "$M/.project-paths"
check "origin discovery does not record a private project's path" test ! -e "$E/.project-paths"
printf 'test-host\tprojects/chat\n' > "$E/.project-paths"
mv "$M" "${M%/memory}/memory.local-copy"
ln -s "$E" "$M"
run_slp "$H" >/dev/null
check "a private remote entry with an explicit host path is detached too" real_dir "$M"
check "and its remote metadata still does not enter the private copy" \
  test ! -e "$M/.project-remote" -a ! -e "$M/.project-paths"

new_home
git_repo "$H/projects/no-origin"
M=$(memdir "$H" "$H/projects/no-origin"); mkdir -p "$M"; printf 'local only\n' > "$M/MEMORY.md"
run_slp "$H" >/dev/null
E="$H/store/projects-memory/projects-no-origin"
assert_eq "$(target_of "$M")" "$E" "no origin keeps today's path-keyed adoption"
assert_eq "$(cat "$E/.project-path" 2>/dev/null)" "projects/no-origin" "and keeps .project-path"
check "no-origin writes no remote or per-host metadata" \
  test ! -e "$E/.project-remote" -a ! -e "$E/.project-paths" -a ! -e "$E/.migrated-to"

section "remote discovery — every match, mismatches and unsafe paths"
new_home
PM="$H/store/projects-memory"
git_repo "$H/projects/one"; git -C "$H/projects/one" remote add origin 'git@github.com:Owner/Repo.git'
git_repo "$H/code/two"; git -C "$H/code/two" remote add origin 'git@github.com:Owner/Repo.git'
E="$PM/$RK"; mkdir -p "$E"; printf 'github.com/Owner/Repo\n' > "$E/.project-remote"
M1=$(memdir "$H" "$H/projects/one"); M2=$(memdir "$H" "$H/code/two")
mkdir -p "${M1%/memory}" "${M2%/memory}"
store_commit "$H"
OUT=$(run_slp "$H" --verbose)
check "the first local checkout is recorded" \
  grep -qFx "$(printf 'test-host\tprojects/one')" "$E/.project-paths"
assert_eq "$(grep -cFx "$(printf 'test-host\tcode/two')" "$E/.project-paths" 2>/dev/null)" "1" \
  "the second local checkout is recorded too"
assert_eq "$(target_of "$M1")" "$E" "the first checkout is linked"
assert_eq "$(target_of "$M2")" "$E" "the second checkout of the same origin is linked too"
assert_not_contains "$OUT" "conflict" "multiple checkouts of one origin are not a conflict"

new_home
PM="$H/store/projects-memory"
git_repo "$H/projects/other"; git -C "$H/projects/other" remote add origin 'git@github.com:Other/Repo.git'
RK_WANTED=$(remote_key_of 'github.com/Owner/Wanted')
E="$PM/$RK_WANTED"; mkdir -p "$E"; printf 'github.com/Owner/Wanted\n' > "$E/.project-remote"
M=$(memdir "$H" "$H/projects/other"); mkdir -p "${M%/memory}"
store_commit "$H"
OUT=$(run_slp "$H" --verbose)
check "a different origin is not recorded or linked" test ! -e "$E/.project-paths" -a ! -e "$M"
assert_contains "$OUT" "no local project with origin" "the mismatch is explained"

new_home
PM="$H/store/projects-memory"; E="$PM/$RK_WANTED"
mkdir -p "$SANDBOX/outside-$NHOME" "$E"
printf 'github.com/Owner/Wanted\n' > "$E/.project-remote"
printf 'test-host\t../outside-%s\n' "$NHOME" > "$E/.project-paths"
store_commit "$H"
run_slp "$H" >/dev/null
WHY="links: $(find "$H/.claude/projects" -type l | tr '\n' ' ')"
check "a per-host path climbing out of HOME is not linked" \
  test -z "$(find "$H/.claude/projects" -type l)"

new_home
PM="$H/store/projects-memory"; L="$PM/projects-Clade"
git_repo "$H/projects/Clade"
mkdir -p "$L" "$H/store/outside"
printf 'projects/Clade\n' > "$L/.project-path"
printf '../outside\n' > "$L/.migrated-to"
M=$(memdir "$H" "$H/projects/Clade"); mkdir -p "${M%/memory}"; ln -s "$L" "$M"
store_commit "$H"
run_slp "$H" >/dev/null
assert_eq "$(target_of "$M")" "$L" "a traversal in .migrated-to cannot retire a link"

section "remote migration — copy verification and the time budget"
new_home
PM="$H/store/projects-memory"
git_repo "$H/projects/Clade"; git -C "$H/projects/Clade" remote add origin 'git@github.com:Owner/Repo.git'
L="$PM/projects-Clade"; mkdir -p "$L"
printf 'projects/Clade\n' > "$L/.project-path"; printf 'original\n' > "$L/MEMORY.md"
M=$(memdir "$H" "$H/projects/Clade"); mkdir -p "${M%/memory}"; ln -s "$L" "$M"
store_commit "$H"
OUT=$(SLP_PATH="$SHIMBIN:$PATH" SLP_SHIM_MODE=corrupt run_slp "$H")
check "a migration copy that does not verify gets no marker" test ! -e "$L/.migrated-to"
assert_eq "$(target_of "$M")" "$L" "and the legacy link is not retired"
assert_contains "$OUT" "migration copy of projects-memory/projects-Clade does not match" \
  "the failed verification is reported"

new_home
PM="$H/store/projects-memory"
for name in a1 a2; do
  git_repo "$H/projects/$name"
  git -C "$H/projects/$name" remote add origin "git@github.com:Owner/$name.git"
  mkdir -p "$PM/projects-$name"
  printf 'projects/%s\n' "$name" > "$PM/projects-$name/.project-path"
  printf '%s memory\n' "$name" > "$PM/projects-$name/MEMORY.md"
done
store_commit "$H"
OUT=$(SLP_BUDGET=1 SLP_PATH="$SHIMBIN:$PATH" SLP_SHIM_MODE=slow run_slp "$H")
N=$(find "$PM" -name .migrated-to -print | grep -c .)
assert_eq "$N" "1" "after the budget only one verified migration has happened"
assert_contains "$OUT" "deferred: 1 memory directories" "the other migration waits for the next run"
run_slp "$H" >/dev/null
N=$(find "$PM" -name .migrated-to -print | grep -c .)
assert_eq "$N" "2" "the next run finishes the deferred migration"
}

# ─── Run the sections ────────────────────────────────────────────────

# The remote-regression suite reuses these hermetic fixtures and assertions.
if [[ "${SLP_LIBRARY:-0}" -eq 1 ]]; then return 0; fi

ALL_SECTIONS="adopt link legacy prune conflict private dryrun wiring ambiguous store profiles commit budget races lock limits remote"
for _s in ${SLP_ONLY:-$ALL_SECTIONS}; do
  "t_$_s"
done

# ─── mutations: each guard, removed, turns this suite red ─────────────

if [[ -z "$SLP_MUTANT" && -z "${SLP_SKIP_MUTATIONS:-}" ]]; then
section "mutations — removing a guard must turn the suite red"

MUT_DIR="$SANDBOX/mutants"
NMUT=0
MUT_NAMES=(); MUT_EXPECT=(); MUT_ONLY=()
# mutation EXPECT NAME FILE SECTIONS ANCHOR REPLACEMENT — FILE is relative to
# configs/ (scripts/sync-link-projects.sh, hooks/sync-health.sh); ANCHOR is
# literal text that must match it exactly once; SECTIONS are the ones run.
mutation() {
  local expect=$1 name=$2 file=$3 only=$4 dir="$MUT_DIR/m$NMUT"
  mkdir -p "$dir/scripts" "$dir/hooks/lib"
  cp "$SCRIPTS"/sync-*.sh "$dir/scripts/"
  cp "$HOOKS/lib/runtime-dir.sh" "$dir/hooks/lib/"
  cp "$HOOKS/sync-health.sh" "$dir/hooks/"
  if ! SLP_A="$5" SLP_R="$6" awk '
      { buf = buf (NR > 1 ? "\n" : "") $0 }
      END {
        a = ENVIRON["SLP_A"]; r = ENVIRON["SLP_R"]; s = buf; out = ""; n = 0
        while ((i = index(s, a)) > 0) { out = out substr(s, 1, i - 1) r; s = substr(s, i + length(a)); n++ }
        if (n != 1) exit 3
        printf "%s\n", out s
      }' "$SCRIPTS/../$file" > "$dir/$file"; then
    fail "mutation '$name': its anchor no longer matches $file exactly once"
    return 0
  fi
  MUT_NAMES[NMUT]=$name; MUT_EXPECT[NMUT]=$expect; MUT_ONLY[NMUT]=$only
  NMUT=$((NMUT + 1))
}
L=scripts/sync-link-projects.sh

mutation green "no-op control (a comment reworded)" $L "$ALL_SECTIONS" \
  '# Regular files only.' '# Regular files only, really.'
mutation red "the leading '-' of the slug (old encoder)" $L "link" \
  'enc "$1"
  fi' 'enc "${1#/}"
  fi'
mutation red "the adopt pass" $L "adopt" \
  '    [[ -d "$mem" && ! -L "$mem" ]] || continue' '    continue'
mutation red "the commit" $L "adopt" \
  'bash "$SCRIPT_DIR/sync-push.sh" >/dev/null || true' ':'
mutation red "committing from the store's status (this run's work decides instead)" $L "commit" \
  '[[ -n "$(git -C "$SYNC_DIR" status --porcelain -- projects-memory 2>/dev/null)" ]]' \
  '[[ "$examined" -gt 0 ]]'
mutation red "the clash check" $L "conflict" \
  '      if [[ -n "$clash" ]]; then' '      if false; then'
mutation red "the owner != rel check" $L "conflict" \
  '      if [[ "$owner" != "$rel" ]]; then' '      if false; then'
mutation red "the several-candidates check" $L "ambiguous" \
  '    if [[ "$(printf '"'"'%s\n'"'"' "$cands" | wc -l | tr -d '"'"' '"'"')" -gt 1 ]]; then' '    if false; then'
mutation red "the unreachable-store check" $L "store" \
  '[[ -n "${SYNC_DIR:-}" && -d "$SYNC_DIR" ]] || exit 0' '[[ -n "${SYNC_DIR:-}" ]] || exit 0'
mutation red "privacy in the adopt pass" $L "private" \
  '    if printf '"'"'%s\n'"'"' "$dec" | any_private; then
      note' '    if false; then
      note'
mutation red "privacy in the link pass" $L "private" \
  '    if is_private "$proj"; then
      note "projects-memory/$key: $proj is a private project, not linked"; continue
    fi' ''
mutation red "privacy in the prune pass (.project-path entries)" $L "private" \
  '        is_private "$proj" || continue
        private=1' '        continue'
mutation red "privacy in the prune pass (legacy entries)" $L "private" \
  '      if printf '"'"'%s\n'"'"' "$dec" | any_private; then
        private=1' '      if false; then
        private=1'
mutation red "the .git exclusion" $L "adopt legacy prune" \
  '  case "$p/" in */.git/*) return 1 ;; esac' '  :'
mutation red "the repository-subdirectory rule" $L "prune" \
  '[[ "$(cd "$top" 2>/dev/null && pwd -P)" == "$here" ]] || return 1' ':'
mutation red "the dry-run guard on adopt" $L "dryrun" \
  '      say "adopt $where -> projects-memory/$key ($nfiles files, ~/$rel$extra)"
      continue' '      say "adopt $where -> projects-memory/$key ($nfiles files, ~/$rel$extra)"'
mutation red "the dry-run guard on detach" $L "dryrun" \
  '  if [[ "$DRY_RUN" -eq 1 ]]; then
    say "detach' '  if false; then
    say "detach'
mutation red "the stray-symlink exclusion (a plain cp -R)" $L "adopt" \
  '    if ! copy_files "$mem" "$dst" "$files"; then' '    cp -Rp "$mem/." "$dst/"
    if ! copy_files "$mem" "$dst" "$files"; then'
mutation red "copy verification" $L "races" \
  '    if [[ -n "$bad" ]]; then
      echo "  error: the store copy' '    if false; then
      echo "  error: the store copy'
mutation red "the adopt ln guard (a directory recreated mid-move)" $L "races" \
  'if [[ -e "$mem" || -L "$mem" ]] || ! ln -s "$dst" "$mem"; then' 'if ! ln -s "$dst" "$mem"; then'
mutation red "the late-write copy" $L "races" \
  '    late=$(differing_files missing-or-different' '    late=""; : $(differing_files missing-or-different'
mutation red "the prune pass" $L "prune" \
  '    [[ -L "$mem" ]] || continue
    target=' '    continue
    target='
mutation red "the pass-2 legacy keep" $L "prune" \
  '      elif [[ -n "$(printf '"'"'%s\n'"'"' "$dec" | filter_paths roots)" ]]; then
        continue' '      elif false; then
        continue'
mutation red "the dangling-link skip" $L "prune" \
  '    if [[ ! -d "$entry" ]]; then
      note "$where/memory: dangling' '    if false; then
      note "$where/memory: dangling'
mutation red "the pass-3 memory-root check" $L "legacy" \
  '      is_memory_root "$phys" || continue' '      :'
mutation red "the pass-3 existing-directory skip" $L "conflict" \
  '      if [[ -e "$mem" ]]; then
        note "projects-memory/$key: $where/memory is a local directory (see the adopt pass)"; continue
      fi' ''
mutation red "never replacing an existing link" $L "prune" \
  '      if [[ -L "$mem" ]]; then
        # Followed' '      if [[ -L "$mem" ]]; then rm -f "$mem"; fi
      if false; then
        # Followed'
mutation red "following a chained link to its end (one hop instead)" $L "profiles" \
  'cur=$(cd "$mem" 2>/dev/null && pwd -P) || cur=""' 'cur=$(link_target_phys "$mem") || cur=""'
mutation red "the profile projects dirs" $L "profiles" \
  '          "$HOME"/.claude-profiles/*/projects; do' '          ; do'
mutation red "\$CLAUDE_CONFIG_DIR" $L "profiles" \
  '${CLAUDE_CONFIG_DIR:+"$CLAUDE_CONFIG_DIR/projects"}' ''
mutation red "the time budget" $L "budget remote" \
  '"$examined" -gt 0 && "$SECONDS" -ge "$BUDGET" ]]' '"$examined" -gt 0 && "$SECONDS" -lt 0 ]]'
mutation red "keeping conflicts across a deferred run" $L "budget" \
  'if [[ "$deferred" -gt 0 && -f "$CONFLICT_STATE" ]]; then' 'if false; then'
mutation red "writing the conflict state file" $L "conflict" \
  'printf '"'"'%s'"'"' "$CONFLICTS" > "$CONFLICT_STATE.$$" && mv "$CONFLICT_STATE.$$" "$CONFLICT_STATE"' ':'
mutation red "removing the state file when nothing conflicts" $L "conflict" \
  '  rm -f "$CONFLICT_STATE"' '  :'
mutation red "the conflict log" $L "conflict" \
  '  log_once_today conflict "$1"' '  :'
mutation red "the conflict log's once-a-day dedup" $L "conflict" \
  '  if grep -F "[$TODAY " "$CONFLICT_LOG" 2>/dev/null | grep -qF -- "] $line"; then' '  if false; then'
mutation red "the .project-path and .project-paths traversal guard" $L "limits remote" \
  '  case "/$line/" in */../*) return 1 ;; esac' '  :'
mutation red "remote scheme stripping" $L "remote" \
  '  case "$url" in *://*) has_scheme=1; url=${url#*://} ;; esac' \
  '  case "$url" in *://*) has_scheme=1 ;; esac'
mutation red "remote user stripping" $L "remote" \
  '  if [[ "$prefix" == *@* ]]; then url="${prefix#*@}$suffix"; fi' \
  '  if false; then url="${prefix#*@}$suffix"; fi'
mutation red "remote trailing-slash stripping" $L "remote" \
  '  while [[ "$url" == */ ]]; do url=${url%/}; done' '  :'
mutation red "remote .git stripping" $L "remote" \
  '  if [[ "$url" == *.git ]]; then url=${url%.git}; fi' \
  '  if false; then url=${url%.git}; fi'
mutation red "scp-style remote colon conversion" $L "remote" \
  '    if [[ "$prefix" == *:* ]]; then url="${prefix%%:*}/${prefix#*:}$suffix"; fi' \
  '    if false; then url="${prefix%%:*}/${prefix#*:}$suffix"; fi'
mutation red "remote host lowercasing" $L "remote" \
  '  lower=$(printf '"'"'%s'"'"' "$host" | tr '"'"'A-Z'"'"' '"'"'a-z'"'"')' '  lower=$host'
mutation red "repository identity in adoption" $L "remote" \
  '    remote=$(project_remote "$proj")' '    remote=""'
mutation red "privacy during origin discovery" $L "remote" \
  '      if printf '"'"'%s\n'"'"' "$dec" | any_private; then continue; fi' \
  '      if false; then continue; fi'
mutation red "privacy in migration" $L "remote" \
  '  if is_private "$proj"; then
    note "projects-memory/$key: $proj is a private project, not migrated"' \
  '  if false; then
    note "projects-memory/$key: $proj is a private project, not migrated"'
mutation red "remote-origin ownership in adoption" $L "remote" \
  '        if [[ "$owner_remote" != "$remote" ]]; then' '        if false; then'
mutation red "the retired-destination adoption guard" $L "remote" \
  '      if [[ -f "$dst/.migrated-to" ]]; then' '      if false; then'
mutation red "remote-origin ownership in migration" $L "remote" \
  '    if [[ "$dest_remote" != "$remote" ]]; then' '    if false; then'
mutation red "the active-destination migration guard" $L "remote" \
  '    if [[ ! -d "$dst" || -f "$dst/.migrated-to" ]]; then' '    if false; then'
mutation red "the migration clash check" $L "remote" \
  '    if [[ -n "$clash" ]]; then
      conflict "projects-memory/$key is not migrated' \
  '    if false; then
      conflict "projects-memory/$key is not migrated'
mutation red "migration copy verification" $L "remote" \
  '  if [[ -n "$bad" ]]; then
    echo "  error: migration copy' \
  '  if false; then
    echo "  error: migration copy'
mutation red "the dry-run guard on migration" $L "remote" \
  '  if [[ "$DRY_RUN" -eq 1 ]]; then
    say "migrate' \
  '  if false; then
    say "migrate'
mutation red "preserving a migrated link" $L "remote" \
  '    if [[ "$retire" -eq 1 ]]; then' '    if false; then'
mutation red "privacy in remote-entry pruning" $L "remote" \
  '        if is_private "$proj"; then private=1; fi' \
  '        if false; then private=1; fi'
mutation red "remote-entry matching-slug retention" $L "remote" \
  '      if [[ "$matched" -eq 1 && "$private" -eq 0 ]]; then continue; fi' \
  '      if false; then continue; fi'
mutation red "skipping migrated entries in the link pass" $L "remote" \
  '  if [[ -f "$entry/.migrated-to" ]] || planned_migration "$key"; then
    note "projects-memory/$key: retired by .migrated-to, not linked"' \
  '  if false || planned_migration "$key"; then
    note "projects-memory/$key: retired by .migrated-to, not linked"'
mutation red "dry-run suppression of retired entries" $L "remote" \
  '  if [[ -f "$entry/.migrated-to" ]] || planned_migration "$key"; then' \
  '  if [[ -f "$entry/.migrated-to" ]]; then'
mutation red "excluding remote metadata from private copies" $L "remote" \
  "    -e './\\.project-remote' -e './\\.migrated-to' || true" \
  "    -e './\\.migrated-to' || true"
mutation red "the .migrated-to key guard" $L "remote" \
  '  case "$key" in '"'"''"'"'|*[!A-Za-z0-9-]*) return 0 ;; esac' '  :'
mutation red "the invalid migration-target guard" $L "remote" \
  '      if [[ -z "$migrated" || ! -d "$PROJECTS_MEMORY_DIR/$migrated" ]]; then' \
  '      if false; then'
mutation red "sync-health.sh's conflict notice" hooks/sync-health.sh "conflict" \
  'if [[ -s "$MEM_CONFLICTS" ]]; then' 'if false; then'
if command -v flock >/dev/null 2>&1; then
  mutation red "the lock" $L "lock" \
    '  flock -n 9 || exit 0' '  :'
else
  echo -e "  ${YELLOW}-${NC} not mutated here: the lock (no flock on this machine)"
fi
if long_key_possible; then
  mutation red "the 200-character key cap" $L "limits" \
    '    if [[ ${#key} -gt 200 ]]; then' '    if false; then'
else
  echo -e "  ${YELLOW}-${NC} not mutated here: the key cap (TMPDIR too long to build the case)"
fi

# Bounded parallelism; bash 3.2 has no `wait -n`, so wait oldest-first.
SLP_JOBS="${SLP_JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)}"
[[ "$SLP_JOBS" =~ ^[0-9]+$ && "$SLP_JOBS" -ge 1 ]] || SLP_JOBS=2
[[ "$SLP_JOBS" -gt 8 ]] && SLP_JOBS=8
SLP_SELF="$REPO_ROOT/tests/test-sync-link-projects.sh"
run_mutant() {
  SLP_SCRIPTS_DIR="$MUT_DIR/m$1/scripts" SLP_ONLY="${MUT_ONLY[$1]}" SLP_MUTANT=1 \
    bash "$SLP_SELF" > "$MUT_DIR/m$1.log" 2>&1
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
