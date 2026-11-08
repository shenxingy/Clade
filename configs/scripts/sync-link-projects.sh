#!/usr/bin/env bash
# sync-link-projects.sh — Keep every project's auto-memory inside the sync store,
# and link each store entry back to the directory Claude Code reads it from.
#
# Claude Code reads a project's auto-memory from <config>/projects/<slug>/memory/,
# where <config> is $CLAUDE_CONFIG_DIR when set and ~/.claude otherwise. <slug>
# is the project's absolute path with every character outside [A-Za-z0-9]
# replaced by "-", so it starts with "-", and a hash is appended past 200
# characters. The project is the canonical git root of the session's directory
# (a linked worktree maps to its main checkout), or that directory outside git.
# Read from the Claude Code 2.1.283 binary: `replace(/[^a-zA-Z0-9]/g,"-")` and
# `defaultPath()`. The sync store is its own git repository with its own remote,
# so a memory directory has diff history only when it IS a directory in the
# store, symlinked back into place.
#
# Until 2026-11-06 this script only linked store -> local, and four defects kept
# memories out of the store (measured on the author's main host 2026-11-05: 29
# real memory directories, 24 of them non-empty, in no repository at all):
#   - it found a project with `find -maxdepth 3 -name <basename> | head -1`:
#     case-sensitive, first hit wins. `projects-memory/clade` resolved to some
#     repository's `.git/clade`, never to `~/projects/Clade`;
#   - its encoder dropped the leading "-", so its links sat in directories
#     Claude Code never reads;
#   - `((linked++))` / `((skipped++))` evaluate to 0 on the first pass and, under
#     `set -e`, killed the script after its first entry;
#   - nothing ever moved a local memory directory INTO the store.
#
# Projects directories scanned, each once by physical path: ~/.claude/projects,
# $CLAUDE_CONFIG_DIR/projects, and ~/.claude-profiles/*/projects (one config dir
# per account on a host that runs several; radar-cron.sh and stop-check.sh read
# the same layout).
#
# Privacy first, in every pass: a private project (listed in
# ~/.claude/private-projects or $CLADE_PRIVATE_PROJECTS, or carrying
# .claude/conversation-mode) is never adopted, never linked, and a link it
# already has into the store is replaced by a local copy. When a slug decodes to
# several directories and any of them is private, the slug counts as private.
#
# Four passes, in this order:
#   adopt  A real (not symlinked) local memory directory is copied into the store
#          as projects-memory/<key>/. With an origin, <key> is repo- plus the
#          encoded normalised origin (scheme, user@, trailing .git and slash
#          removed; scp's host:owner becomes host/owner; only the host lowercased).
#          Only a physical repository root that is not a linked worktree uses
#          that identity; a subdirectory or worktree keeps the path key. Without
#          an origin the old path key and .project-path are unchanged.
#          .project-remote holds the identity and .project-paths holds one
#          "<hostname><TAB>path relative to HOME" line per checkout. Deviation
#          from the original one-path-per-host design: lines are ADDED, never
#          replaced, so every checkout on a host keeps its memory. A stale line
#          is kept too: an unmounted NFS path looks missing and is not deletion
#          evidence. Remote entries do not write .project-path: only this script
#          read it, and one path cannot describe every checkout. Copies are
#          cksum-verified, then replaced by links; originals stay beside them as
#          memory.pre-sync-<timestamp>. A different file version or owner blocks
#          the move and is recorded as a conflict (below).
#   migrate
#          A path-keyed entry whose project exists here, is not private and has
#          an origin is union-copied into its remote-keyed entry with the same
#          cksum verification. Any differing same-name file blocks the whole
#          entry. The legacy entry is never deleted: .migrated-to names the new
#          key, and prune/link retire it. Its link on this host is moved to a
#          fresh memory.pre-sync-<timestamp> name before the new link is made.
#   prune  A memory symlink into the store that is provably wrong is removed (the
#          link only, never store content): one into an entry with no matching
#          checkout on this host, a migrated entry, or, for a legacy entry, one
#          at a slug no memory root on this machine produces. ANY of this host's
#          recorded checkout slugs keeps a remote link; an unrecorded slug whose
#          actual origin matches is recorded and kept too. A private project's
#          link is detached instead: a verified local copy replaces it, without
#          any of the linker's metadata files.
#   link   A path-keyed entry links to $HOME/<.project-path>. A remote-keyed entry
#          links EVERY existing checkout recorded for this host. If it has no
#          line, one lazily built origin -> candidate-roots index supplies every
#          matching checkout. Each distinct slug is decoded at most once per run,
#          and every remote entry reuses that index. A legacy basename entry is
#          linked only to a directory of exactly that name directly under one
#          search root. Links are only ever CREATED: an existing link or directory
#          is never replaced, except for the preserved migration relink above.
#
# Bounded, because sync-pull.sh runs this inside an async SessionStart hook with
# a 30 s timeout: once CLADE_SYNC_LINK_BUDGET seconds (default 10; 0 = no limit)
# have passed, remaining adoptions and migrations are deferred, and discovery
# stops BETWEEN slugs. One eligible slug may finish after the budget; the next
# is not decoded. The partial index is marked incomplete: matches still link,
# but an entry with no match is deferred rather than called absent. At least one
# eligible slug (not the whole index) is examined per run. The first run on a
# host with a long backlog can be run by hand without the limit:
#   CLADE_SYNC_LINK_BUDGET=0 bash ~/.claude/scripts/sync-link-projects.sh
#
# Committed from the store's own state: whenever projects-memory/ has anything
# uncommitted after the passes, sync-push.sh runs. An adoption whose commit was
# lost (a killed run, a sync-push that found its lock held) is committed by the
# next run, and so is a memory edit made where memory-sync.sh does not look.
#
# Conflicts are recorded where a reader finds them, not only on stdout (which,
# under the async hook, reaches nobody):
#   ~/.claude/.sync-memory-conflicts  every conflict of the latest run, one per
#                                     line; removed when there are none.
#                                     sync-health.sh prints it at session start.
#   ~/.claude/.sync-conflicts.log     the history, one line per conflict per day
#                                     (sync-push.sh writes its own lines there).
#
# Usage: sync-link-projects.sh [--dry-run] [--verbose]
#   --dry-run  print what would change, and every skip with its reason; change
#              nothing (no budget, no log). Safe against a live ~/.claude.
#   --verbose  also print what was skipped, and why.
#
# Limits: a slug past 200 characters is skipped (Claude Code's hash suffix is
# not reproduced here). A path holding non-ASCII characters matches only under
# a UTF-8 locale. Without an origin, a project path differing in case between
# machines (`projects/Clade` vs `projects/clade`) gets one store entry per spelling.
# Origin discovery needs an existing memory slug; it does not walk the filesystem.
# .project-paths is marked merge=union by sync-setup, and sync-push heals that
# attribute into older stores before merging. Concurrent host lines therefore
# survive; a conflict from before that upgrade can still need one rediscovery.
# HOSTNAME can change on a Mac when its network changes, so one Mac may acquire
# checkout lines under more than one hostname; old names are harmless.
# A run killed in the middle of a copy leaves a partial store entry and an intact local
# directory. The next run completes the entry, except that a file cut short
# differs from the local one and is reported as a conflict, not overwritten.
# Until then any sync-push.sh (they all `git add -A`) may commit the partial
# entry. The copy is one tar pipe per directory, and discovery stops before the
# next slug after the budget, so a timeout can land inside that pipe or one slug.
#
# No `set -e`, on purpose: its interaction with arithmetic is the third defect
# above. Every fallible step is checked where it happens instead.

set -uo pipefail

DRY_RUN=0
VERBOSE=0
for _arg in "$@"; do
  case "$_arg" in
    --dry-run) DRY_RUN=1; VERBOSE=1 ;;
    --verbose) VERBOSE=1 ;;
    -h|--help) sed -n '2,/^$/s/^# \{0,1\}//p' "$0"; exit 0 ;;
    *) echo "sync-link-projects: unknown argument: $_arg" >&2; exit 2 ;;
  esac
done

CLAUDE_DIR="$HOME/.claude"
SYNC_CONFIG="$CLAUDE_DIR/.sync-config"
SCRIPT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"
CONFLICT_LOG="$CLAUDE_DIR/.sync-conflicts.log"
CONFLICT_STATE="$CLAUDE_DIR/.sync-memory-conflicts"

[[ -f "$SYNC_CONFIG" ]] || exit 0
# shellcheck source=/dev/null
source "$SYNC_CONFIG"
[[ "${SYNC_BACKEND:-none}" == "none" ]] && exit 0
# An unreachable store (NFS mount dropped) must not read as "every link is wrong",
# nor become a shadow store under the mount point that hides itself on remount.
[[ -n "${SYNC_DIR:-}" && -d "$SYNC_DIR" ]] || exit 0

# ─── Projects directories ────────────────────────────────────────────────────

PROJECTS_DIRS=()
_seen=$'\n'
for _d in "$CLAUDE_DIR/projects" ${CLAUDE_CONFIG_DIR:+"$CLAUDE_CONFIG_DIR/projects"} \
          "$HOME"/.claude-profiles/*/projects; do
  [[ -d "$_d" ]] || continue
  _p=$(cd "$_d" 2>/dev/null && pwd -P) || continue
  case "$_seen" in *$'\n'"$_p"$'\n'*) continue ;; esac
  _seen="$_seen$_p"$'\n'
  PROJECTS_DIRS[${#PROJECTS_DIRS[@]}]=$_d
done
[[ ${#PROJECTS_DIRS[@]} -gt 0 ]] || exit 0

label_of() {   # how a projects directory is named in output: "" for ~/.claude
  # shellcheck disable=SC2088  # a literal "~/" for the reader, not a path
  case "$1" in
    "$CLAUDE_DIR/projects") printf '' ;;
    "$HOME"/*) printf '~/%s/' "${1#"$HOME"/}" ;;
    *) printf '%s/' "$1" ;;
  esac
}

PROJECTS_MEMORY_DIR="$SYNC_DIR/projects-memory"
if [[ ! -d "$PROJECTS_MEMORY_DIR" ]]; then
  [[ "$DRY_RUN" -eq 1 ]] && exit 0
  mkdir -p "$PROJECTS_MEMORY_DIR" || exit 0
fi
PM_PHYS=$(cd "$PROJECTS_MEMORY_DIR" && pwd -P) || exit 0
HOME_PHYS=$(cd "$HOME" && pwd -P) || exit 0
PRIVATE_PROJECTS_FILE="${CLADE_PRIVATE_PROJECTS:-$CLAUDE_DIR/private-projects}"
STAMP=$(date +%Y%m%d%H%M%S)
TODAY=$(date +%Y-%m-%d)
HOST_NAME=${HOSTNAME:-}
[[ -n "$HOST_NAME" ]] || HOST_NAME=$(hostname 2>/dev/null)
HOST_NAME=${HOST_NAME//$'\t'/-}
HOST_NAME=${HOST_NAME//$'\r'/-}
HOST_NAME=${HOST_NAME//$'\n'/-}
[[ -n "$HOST_NAME" ]] || HOST_NAME=unknown-host
BUDGET="${CLADE_SYNC_LINK_BUDGET:-10}"
[[ "$BUDGET" =~ ^[0-9]+$ ]] || BUDGET=10

SEARCH_ROOTS=(
  "$HOME/projects"
  "$HOME/code"
  "$HOME/src"
  "$HOME/work"
  "$HOME"
)

# ─── Output ──────────────────────────────────────────────────────────────────

say() {   # an action taken (or, under --dry-run, one that would be taken)
  if [[ "$DRY_RUN" -eq 1 ]]; then echo "  would $1"; else echo "  $1"; fi
}
note() {  # a skip and its reason: printed only under --verbose / --dry-run
  [[ "$VERBOSE" -eq 1 ]] && echo "  skip $1"
  return 0
}

CONFLICTS=""
log_once_today() {   # KIND MESSAGE — one line per message per day in the log
  local line="sync-link-projects $1: $2"
  [[ "$DRY_RUN" -eq 1 ]] && return 0
  if grep -F "[$TODAY " "$CONFLICT_LOG" 2>/dev/null | grep -qF -- "] $line"; then
    return 0
  fi
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$line" >> "$CONFLICT_LOG" 2>/dev/null || true
}
conflict() {   # MESSAGE — printed, kept for the state file, logged once a day
  echo "  conflict: $1"
  [[ "$DRY_RUN" -eq 1 ]] && return 0
  CONFLICTS="$CONFLICTS$1"$'\n'
  log_once_today conflict "$1"
}

# ─── Lock: one linker at a time per user ─────────────────────────────────────
# Several sessions start together; two adopt passes racing on one directory
# would both copy and one `mv` would fail. Same lock pattern as sync-push.sh.

if [[ "$DRY_RUN" -eq 0 ]] && command -v flock >/dev/null 2>&1; then
  _rt_lib="$SCRIPT_DIR/../hooks/lib/runtime-dir.sh"
  if [[ -f "$_rt_lib" ]]; then
    # shellcheck source=/dev/null
    . "$_rt_lib" 2>/dev/null || true
  fi
  if declare -f clade_runtime_dir >/dev/null 2>&1 && _rt=$(clade_runtime_dir 2>/dev/null); then
    _lock="$_rt/sync-link-projects.lock"
  else
    _lock="$CLAUDE_DIR/.sync-link-projects.lock"
  fi
  exec 9>"$_lock" || exit 0
  flock -n 9 || exit 0
fi

# ─── Slugs (mirror Claude Code's encoding) ───────────────────────────────────

_ALNUM='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'

enc() {   # every character outside [A-Za-z0-9] becomes "-"
  local s=$1
  printf '%s' "${s//[!$_ALNUM]/-}"
}

slug_of_path() {   # absolute path -> the directory name Claude Code uses
  if command -v cygpath >/dev/null 2>&1; then
    enc "$(cygpath -w "$1")"   # native Windows Claude Code sees C:\Users\...
  else
    enc "$1"
  fi
}

project_path() {   # store-relative path recorded in an entry -> absolute path
  if [[ "$1" == "." ]]; then printf '%s' "$HOME_PHYS"; else printf '%s/%s' "$HOME_PHYS" "$1"; fi
}

key_of_rel() {     # projects/Clade -> projects-Clade; never empty, never "-..."
  local k
  k=$(enc "$1")
  while [[ "$k" == -* ]]; do k=${k#-}; done
  [[ -n "$k" ]] || k="home-directory"
  printf '%s' "$k"
}

clean_project_rel() {   # a relative path this script may safely resolve under HOME
  local line=${1%$'\r'}
  # A path that climbs out of $HOME or is absolute is not one this script wrote.
  case "/$line/" in */../*) return 1 ;; esac
  case "$line" in ''|/*) return 1 ;; esac
  printf '%s' "$line"
}

read_project_path() {   # an entry's .project-path, or nothing for a legacy entry
  local f="$1/.project-path" line=""
  [[ -f "$f" ]] || return 0
  IFS= read -r line < "$f" || true
  clean_project_rel "$line" || return 0
}

normalise_remote() {   # origin URL -> host/owner/repo, with only the host lowercased
  local url=$1 has_scheme=0 prefix suffix host lower
  url=${url%$'\r'}
  case "$url" in ''|*$'\n'*|*$'\t'*) return 0 ;; esac
  case "$url" in *://*) has_scheme=1; url=${url#*://} ;; esac
  prefix=${url%%/*}; suffix=${url#"$prefix"}
  if [[ "$prefix" == *@* ]]; then url="${prefix#*@}$suffix"; fi
  while [[ "$url" == */ ]]; do url=${url%/}; done
  if [[ "$url" == *.git ]]; then url=${url%.git}; fi
  if [[ "$has_scheme" -eq 0 ]]; then
    prefix=${url%%/*}; suffix=${url#"$prefix"}
    if [[ "$prefix" == *:* ]]; then url="${prefix%%:*}/${prefix#*:}$suffix"; fi
  fi
  host=${url%%/*}; suffix=${url#"$host"}
  lower=$(printf '%s' "$host" | tr 'A-Z' 'a-z')
  printf '%s%s' "$lower" "$suffix"
}

project_remote() {   # a repository root's normalised origin, or nothing
  local url
  is_memory_root "$1" || return 0
  url=$(git -C "$1" remote get-url origin 2>/dev/null) || return 0
  normalise_remote "$url"
}

key_of_remote() { printf 'repo-%s' "$(enc "$1")"; }

read_project_remote() {   # an entry's normalised repository identity
  local f="$1/.project-remote" remote=""
  [[ -f "$f" ]] || return 0
  IFS= read -r remote < "$f" || true
  remote=${remote%$'\r'}
  case "$remote" in ''|*$'\t'*) return 0 ;; esac
  printf '%s' "$remote"
}

read_host_paths() {   # ENTRY -> every safe relative path recorded for this host
  local f="$1/.project-paths" host="" rel="" extra="" safe seen=$'\n'
  [[ -f "$f" ]] || return 0
  while IFS=$'\t' read -r host rel extra || [[ -n "$host$rel$extra" ]]; do
    [[ "$host" == "$HOST_NAME" && -z "$extra" ]] || continue
    safe=$(clean_project_rel "$rel") || continue
    case "$seen" in *$'\n'"$safe"$'\n'*) continue ;; esac
    seen="$seen$safe"$'\n'
    printf '%s\n' "$safe"
  done < "$f"
  return 0
}

record_host_path() {   # ENTRY REL — add this host/path if absent; never replace a line
  local entry=$1 rel=$2 current
  current=$(read_host_paths "$entry")
  if printf '%s\n' "$current" | grep -Fx -- "$rel" >/dev/null 2>&1; then return 0; fi
  if [[ "$DRY_RUN" -eq 1 ]]; then
    say "record projects-memory/${entry##*/}: $HOST_NAME -> ~/$rel"
    return 0
  fi
  if [[ -s "$entry/.project-paths" && -n "$(tail -c 1 "$entry/.project-paths")" ]]; then
    if ! printf '\n' >> "$entry/.project-paths"; then
      echo "  error: cannot terminate projects-memory/${entry##*/}/.project-paths" >&2
      return 1
    fi
  fi
  if ! printf '%s\t%s\n' "$HOST_NAME" "$rel" >> "$entry/.project-paths"; then
    echo "  error: cannot write projects-memory/${entry##*/}/.project-paths" >&2
    return 1
  fi
  echo "  recorded projects-memory/${entry##*/}: $HOST_NAME -> ~/$rel"
}

read_migrated_to() {   # a safe store key, never a path supplied by the marker
  local f="$1/.migrated-to" key=""
  [[ -f "$f" ]] || return 0
  IFS= read -r key < "$f" || true
  key=${key%$'\r'}
  case "$key" in ''|*[!A-Za-z0-9-]*) return 0 ;; esac
  printf '%s' "$key"
}

# decode_slug SLUG — every existing directory whose slug is SLUG. The encoding
# is lossy ("/", ".", "_" and "-" all become "-"), so this walks the filesystem
# along the slug instead of guessing. At each level the next path component's
# encoding is the slug up to one of its remaining "-"s, so each split point
# becomes one glob in which every "-" may be any non-alphanumeric character
# (`my-app` -> `my[!A-Za-z0-9]app`, which matches `my.app`, `my_app`, `my-app`).
# Globs, not a loop over every entry: a directory like /tmp can hold 100k names.
# Literal paths, so a symlinked directory counts under its own name too.
_walk() {   # DIR REST — REST is empty or starts with "-"
  local dir=$1 rest=$2 head tail pat e
  if [[ -z "$rest" ]]; then printf '%s\n' "$dir"; return 0; fi
  head=""
  tail=${rest#-}
  while :; do
    case "$tail" in
      *-*) head="$head${tail%%-*}"; tail="-${tail#*-}" ;;
      *)   head="$head$tail"; tail="" ;;
    esac
    if [[ -n "$head" ]]; then
      pat=${head//-/[!$_ALNUM]}
      # shellcheck disable=SC2231  # $pat is meant to glob
      for e in "$dir"/$pat; do
        case "${e##*/}" in .|..) continue ;; esac
        [[ -d "$e" ]] || continue
        _walk "$e" "$tail"
      done
    fi
    [[ -n "$tail" ]] || break
    head="$head-"
    tail=${tail#-}
  done
  return 0
}
decode_slug() {
  local slug=$1 home_slug
  # A name may start with "." (`.git`, `.reorg`), and an unmatched glob must
  # expand to nothing. Always called in a subshell, so this does not leak.
  shopt -s dotglob nullglob
  if command -v cygpath >/dev/null 2>&1; then
    # Windows slugs begin with a drive letter; only $HOME's subtree is decoded.
    home_slug=$(slug_of_path "$HOME_PHYS")
    case "$slug" in
      "$home_slug") printf '%s\n' "$HOME_PHYS" ;;
      "$home_slug"-*) _walk "$HOME_PHYS" "${slug#"$home_slug"}" ;;
    esac
    return 0
  fi
  case "$slug" in -*) _walk "" "$slug" ;; esac
  return 0
}

# is_memory_root DIR — could Claude Code key a project's memory by DIR? Not a
# path inside .git, not a subdirectory of a repository, not a linked worktree
# (both of those key to the repository's main checkout). Outside git, any
# directory can be a project root. Unknown (no git, unreadable) counts as yes,
# so the prune pass errs toward keeping a link.
is_memory_root() {
  local p=$1 top here gd cd_
  case "$p/" in */.git/*) return 1 ;; esac
  top=$(git -C "$p" rev-parse --show-toplevel 2>/dev/null) || return 0
  here=$(cd "$p" 2>/dev/null && pwd -P) || return 0
  [[ "$(cd "$top" 2>/dev/null && pwd -P)" == "$here" ]] || return 1
  gd=$(cd "$p" && cd "$(git rev-parse --git-dir 2>/dev/null)" 2>/dev/null && pwd -P) || return 0
  cd_=$(cd "$p" && cd "$(git rev-parse --git-common-dir 2>/dev/null)" 2>/dev/null && pwd -P) || return 0
  [[ "$gd" == "$cd_" ]]
}

# filter_paths MODE — read decoded paths on stdin, print one per physical
# directory. MODE "roots" keeps memory roots only; "any" keeps every path
# outside .git.
filter_paths() {
  local mode=$1 p phys seen=$'\n'
  while IFS= read -r p; do
    [[ -n "$p" ]] || continue
    if [[ "$mode" == "roots" ]]; then
      is_memory_root "$p" || continue
    else
      case "$p/" in */.git/*) continue ;; esac
    fi
    phys=$(cd "$p" 2>/dev/null && pwd -P) || continue
    case "$seen" in *$'\n'"$phys"$'\n'*) continue ;; esac
    seen="$seen$phys"$'\n'
    printf '%s\n' "$p"
  done
}

is_private() {   # private projects never leave this machine (sync-push's rule)
  local p=$1 phys line
  [[ -f "$p/.claude/conversation-mode" ]] && return 0
  [[ -f "$PRIVATE_PROJECTS_FILE" ]] || return 1
  phys=$(cd "$p" 2>/dev/null && pwd -P) || phys=$p
  while IFS= read -r line || [[ -n "$line" ]]; do
    line=${line%$'\r'}
    case "$line" in ''|'#'*) continue ;; esac
    line=${line%/}
    case "$p/" in "$line"/*) return 0 ;; esac
    case "$phys/" in "$line"/*) return 0 ;; esac
  done < "$PRIVATE_PROJECTS_FILE"
  return 1
}

any_private() {   # read paths on stdin: is any of them a private project?
  local p
  while IFS= read -r p; do
    [[ -n "$p" ]] || continue
    is_private "$p" && return 0
  done
  return 1
}

# ─── Copies: a constant number of processes per directory ────────────────────
# One tar pair copies and one cksum per side checks, however many files there
# are. A loop of cp and cmp per file forked ~8 processes per file and made a
# first run on a loaded host take 79 s for 414 files, past the hook's 30 s.

regular_files() {   # DIR — its regular files as ./relative paths, one per line
  (cd "$1" && find . -type f -print)
}

_files=()
_load_files() {   # LIST — fill _files from a newline-separated list
  local f
  _files=()
  while IFS= read -r f; do
    [[ -n "$f" ]] && _files[${#_files[@]}]=$f
  done <<< "$1"
  return 0
}

sums() {   # DIR LIST — "crc size name" for each listed file that exists in DIR
  _load_files "$2"
  [[ ${#_files[@]} -gt 0 ]] || return 0
  (cd "$1" 2>/dev/null && cksum "${_files[@]}" 2>/dev/null)
  return 0
}

copy_files() {   # SRC DST LIST — copy the listed files, keeping mode and mtime
  _load_files "$3"
  [[ ${#_files[@]} -gt 0 ]] || return 0
  (cd "$1" && tar -cf - "${_files[@]}") | (cd "$2" && tar -xpf -)
}

# differing_files MODE SRC DST LIST — listed files whose content differs:
#   conflicting           present in both SRC and DST, different
#   missing-or-different  absent from DST, or different
differing_files() {
  local mode=$1 src=$2 dst=$3 list=$4
  [[ -n "$list" ]] || return 0
  { sums "$src" "$list" | sed 's/^/S /'; sums "$dst" "$list" | sed 's/^/D /'; } \
    | awk -v mode="$mode" '
        { name = $0; sub(/^[SD] [0-9]+ [0-9]+ /, "", name); v = $2 " " $3 }
        $1 == "S" { s[name] = v; order[++n] = name; next }
        { d[name] = v }
        END {
          for (i = 1; i <= n; i++) {
            k = order[i]; out = k; sub(/^\.\//, "", out)
            if (k in d) { if (d[k] != s[k]) print out }
            else if (mode == "missing-or-different") print out
          }
        }'
}

link_target_phys() {   # where a symlink points, as a physical path (best effort)
  local link=$1 t parent
  t=$(readlink "$link") || return 1
  while [[ "$t" == */ ]]; do t=${t%/}; done
  case "$t" in /*) ;; *) t="${link%/*}/$t" ;; esac
  parent=$(cd "${t%/*}" 2>/dev/null && pwd -P) || return 1
  printf '%s/%s' "$parent" "${t##*/}"
}

oneline() { tr '\n' ' ' | sed 's/ $//'; }

memory_files() {   # user memory only; linker metadata never becomes a private copy
  regular_files "$1" | grep -vx \
    -e './\.project-path' -e './\.project-paths' \
    -e './\.project-remote' -e './\.migrated-to' || true
}

next_memory_backup() {   # SLUGDIR — an unused pre-sync name, including same-run adoptions
  local slugdir=$1 base candidate n=0
  base="$slugdir/memory.pre-sync-$STAMP"; candidate=$base
  while [[ -e "$candidate" || -L "$candidate" ]]; do
    n=$((n + 1)); candidate="$base-$n"
  done
  printf '%s' "$candidate"
}

# detach MEM ENTRY WHERE KEY — a private project's link into the store becomes a
# verified local copy of the entry. The store entry, and whatever history it
# already has, is left alone: removing it is a decision for a human.
detach() {
  local mem=$1 entry=$2 where=$3 key=$4 tmp files bad
  if [[ "$DRY_RUN" -eq 1 ]]; then
    say "detach $where/memory from projects-memory/$key (private project: a local copy replaces the link)"
    return 0
  fi
  tmp="${mem%/memory}/memory.detach-$STAMP"
  files=$(memory_files "$entry")
  if ! mkdir "$tmp" || ! copy_files "$entry" "$tmp" "$files"; then
    echo "  error: could not copy projects-memory/$key for private $where; the link stays" >&2
    return 0
  fi
  bad=$(differing_files missing-or-different "$entry" "$tmp" "$files" | oneline)
  if [[ -n "$bad" ]]; then
    echo "  error: the local copy for private $where does not match ($bad); the link stays, the copy is $tmp" >&2
    return 0
  fi
  if ! rm -f "$mem" || ! mv "$tmp" "$mem"; then
    echo "  error: could not put the local copy in place for $where; it is at $tmp" >&2
    return 0
  fi
  say "detached $where/memory from projects-memory/$key (private project; its memory is a local copy now)"
  log_once_today privacy "$where is a private project and was linked into projects-memory/$key; it has a local copy now. The store entry and its history are untouched: remove them by hand if they must not stay in the store."
}

# ─── Pass 1: adopt local memory into the store ───────────────────────────────

budget_exhausted() {
  [[ "$DRY_RUN" -eq 0 && "$BUDGET" -gt 0 && "$examined" -gt 0 && "$SECONDS" -ge "$BUDGET" ]]
}

examined=0
deferred=0
for pd in "${PROJECTS_DIRS[@]}"; do
  label=$(label_of "$pd")
  for mem in "$pd"/*/memory; do
    [[ -d "$mem" && ! -L "$mem" ]] || continue
    slugdir=${mem%/memory}
    slug=${slugdir##*/}
    where="$label$slug"
    if [[ -z "$(ls -A "$mem" 2>/dev/null)" ]]; then
      note "$where: memory directory is empty"; continue
    fi
    if budget_exhausted; then
      deferred=$((deferred + 1)); continue
    fi
    examined=$((examined + 1))

    dec=$(decode_slug "$slug")
    if printf '%s\n' "$dec" | any_private; then
      note "$where: private project, its memory stays on this machine"; continue
    fi
    # Prefer a directory current Claude Code keys memory by; an older version
    # keyed it by the session's own directory, and that memory deserves history too.
    cands=$(printf '%s\n' "$dec" | filter_paths roots)
    [[ -n "$cands" ]] || cands=$(printf '%s\n' "$dec" | filter_paths any)
    if [[ -z "$cands" ]]; then
      note "$where: no project directory on this machine has this slug"; continue
    fi
    if [[ "$(printf '%s\n' "$cands" | wc -l | tr -d ' ')" -gt 1 ]]; then
      note "$where: several directories share this slug: $(printf '%s\n' "$cands" | oneline)"; continue
    fi
    proj=$cands
    case "$proj/" in
      "$HOME_PHYS"/*) ;;
      *) note "$where: $proj is outside \$HOME, so it has no portable name"; continue ;;
    esac
    if [[ "$proj" == "$HOME_PHYS" ]]; then rel="."; else rel=${proj#"$HOME_PHYS"/}; fi
    remote=$(project_remote "$proj")
    if [[ -n "$remote" ]]; then key=$(key_of_remote "$remote"); else key=$(key_of_rel "$rel"); fi
    if [[ ${#key} -gt 200 ]]; then
      note "$where: store key would exceed 200 characters"; continue
    fi
    dst="$PROJECTS_MEMORY_DIR/$key"
    files=$(memory_files "$mem")

    if [[ -e "$dst" || -L "$dst" ]]; then
      if [[ -f "$dst/.migrated-to" ]]; then
        note "$where: projects-memory/$key is retired by .migrated-to"; continue
      fi
      if [[ -n "$remote" ]]; then
        owner_remote=$(read_project_remote "$dst")
        if [[ "$owner_remote" != "$remote" ]]; then
          conflict "$where is not adopted — projects-memory/$key already belongs to origin ${owner_remote:-an entry with no .project-remote}"
          continue
        fi
      else
        owner=$(read_project_path "$dst")
        if [[ "$owner" != "$rel" ]]; then
          conflict "$where is not adopted — projects-memory/$key already belongs to ${owner:+~/}${owner:-a legacy entry with no .project-path}"
          continue
        fi
      fi
      clash=$(differing_files conflicting "$mem" "$dst" "$files" | oneline)
      if [[ -n "$clash" ]]; then
        conflict "$where is not adopted — these files differ from projects-memory/$key: $clash (merge by hand: diff -r '$mem' '$dst')"
        continue
      fi
    fi

    nfiles=$(printf '%s\n' "$files" | grep -c .)
    # Regular files only. A symlink inside a memory directory is not something
    # Claude Code writes; the old linker left them (`ln -sfn` onto a real
    # directory links INSIDE it), and copied into the store they would commit an
    # absolute path to this machine. They stay in the kept original.
    links=$( (cd "$mem" && find . -type l) | sed 's|^\./||' | oneline)
    extra=""
    [[ -n "$links" ]] && extra="; symlinks not copied: $links"
    if [[ "$DRY_RUN" -eq 1 ]]; then
      say "adopt $where -> projects-memory/$key ($nfiles files, ~/$rel$extra)"
      continue
    fi

    mkdir -p "$dst" || { echo "  error: cannot create $dst" >&2; continue; }
    if [[ -n "$remote" ]]; then
      if [[ ! -f "$dst/.project-remote" ]] && ! printf '%s\n' "$remote" > "$dst/.project-remote"; then
        echo "  error: cannot write $dst/.project-remote; the local directory is untouched" >&2
        continue
      fi
      if ! record_host_path "$dst" "$rel"; then
        echo "  error: cannot record $where in $dst; the local directory is untouched" >&2
        continue
      fi
    else
      [[ -f "$dst/.project-path" ]] || printf '%s\n' "$rel" > "$dst/.project-path"
    fi
    if ! copy_files "$mem" "$dst" "$files"; then
      echo "  error: copying $where into the store failed; the local directory is untouched" >&2
      continue
    fi
    bad=$(differing_files missing-or-different "$mem" "$dst" "$files" | oneline)
    if [[ -n "$bad" ]]; then
      echo "  error: the store copy of $where does not match ($bad); the local directory is untouched" >&2
      continue
    fi

    backup="$slugdir/memory.pre-sync-$STAMP"
    if ! mv "$mem" "$backup"; then
      echo "  error: could not move $mem aside; it stays a local directory" >&2
      continue
    fi
    # `ln -s` into an existing directory would create the link INSIDE it, so a
    # directory recreated by a concurrent write in this window is left alone.
    if [[ -e "$mem" || -L "$mem" ]] || ! ln -s "$dst" "$mem"; then
      echo "  error: could not link $where/memory to the store; the original is at $backup" >&2
      continue
    fi
    # A write that landed between the copy and the move is in the backup only.
    late=$(differing_files missing-or-different "$backup" "$dst" "$(regular_files "$backup")")
    if [[ -n "$late" ]]; then
      copy_files "$backup" "$dst" "$(printf '%s\n' "$late" | sed 's|^|./|')" \
        || echo "  error: a late write to $where did not reach the store; it is in $backup" >&2
    fi
    say "adopted $where -> projects-memory/$key ($nfiles files; original kept as ${backup##*/}$extra)"
  done
done
# ─── Pass 1b: retire this host's path-keyed entries into repository identity ──

DRY_MIGRATED_KEYS=$'\n'
planned_migration() {
  [[ "$DRY_RUN" -eq 1 ]] || return 1
  case "$DRY_MIGRATED_KEYS" in *$'\n'"$1"$'\n'*) return 0 ;; esac
  return 1
}

migrate_legacy_entry() {   # ENTRY KEY REL PROJECT — never deletes the legacy entry
  local src=$1 key=$2 rel=$3 proj=$4 remote newkey dst dest_remote files clash nfiles bad
  local slug pd where mem target
  if is_private "$proj"; then
    note "projects-memory/$key: $proj is a private project, not migrated"
    return 0
  fi
  remote=$(project_remote "$proj")
  [[ -n "$remote" ]] || return 0
  newkey=$(key_of_remote "$remote")
  if [[ ${#newkey} -gt 200 ]]; then
    note "projects-memory/$key: remote store key would exceed 200 characters"; return 0
  fi
  dst="$PROJECTS_MEMORY_DIR/$newkey"
  if [[ -e "$dst" || -L "$dst" ]]; then
    if [[ ! -d "$dst" || -f "$dst/.migrated-to" ]]; then
      conflict "projects-memory/$key is not migrated to projects-memory/$newkey — the destination is not an active entry"
      return 0
    fi
    dest_remote=$(read_project_remote "$dst")
    if [[ "$dest_remote" != "$remote" ]]; then
      conflict "projects-memory/$key is not migrated to projects-memory/$newkey — the destination belongs to origin ${dest_remote:-an entry with no .project-remote}"
      return 0
    fi
  fi
  files=$(memory_files "$src")
  if [[ -d "$dst" ]]; then
    clash=$(differing_files conflicting "$src" "$dst" "$files" | oneline)
    if [[ -n "$clash" ]]; then
      conflict "projects-memory/$key is not migrated to projects-memory/$newkey — these files differ: $clash (merge by hand: diff -r '$src' '$dst')"
      return 0
    fi
  fi
  nfiles=$(printf '%s\n' "$files" | grep -c .)
  if [[ "$DRY_RUN" -eq 1 ]]; then
    say "migrate projects-memory/$key -> projects-memory/$newkey ($nfiles files, ~/$rel; legacy entry kept with .migrated-to)"
    DRY_MIGRATED_KEYS="$DRY_MIGRATED_KEYS$key"$'\n'
    record_host_path "$dst" "$rel"
    slug=$(slug_of_path "$proj")
    if [[ ${#slug} -le 200 ]]; then
      for pd in "${PROJECTS_DIRS[@]}"; do
        where="$(label_of "$pd")$slug"; mem="$pd/$slug/memory"
        if [[ -L "$mem" ]]; then
          target=$(link_target_phys "$mem") || target=""
          [[ "$target" == "$src" ]] || continue
          say "prune $where/memory -> projects-memory/$key (migrated to projects-memory/$newkey; original kept beside it)"
        elif [[ -e "$mem" ]]; then
          continue
        fi
        say "link $where/memory -> projects-memory/$newkey"
      done
    fi
    return 0
  fi

  mkdir -p "$dst" || { echo "  error: cannot create $dst; projects-memory/$key is untouched" >&2; return 0; }
  if [[ ! -f "$dst/.project-remote" ]] && ! printf '%s\n' "$remote" > "$dst/.project-remote"; then
    echo "  error: cannot write $dst/.project-remote; projects-memory/$key is untouched" >&2
    return 0
  fi
  if ! record_host_path "$dst" "$rel"; then
    echo "  error: cannot record projects-memory/$key at its destination; its links are untouched" >&2
    return 0
  fi
  if ! copy_files "$src" "$dst" "$files"; then
    echo "  error: migration copy of projects-memory/$key failed; its links are untouched" >&2
    return 0
  fi
  bad=$(differing_files missing-or-different "$src" "$dst" "$files" | oneline)
  if [[ -n "$bad" ]]; then
    echo "  error: migration copy of projects-memory/$key does not match ($bad); the legacy entry and its links are untouched" >&2
    return 0
  fi
  if ! printf '%s\n' "$newkey" > "$src/.migrated-to.$$" || ! mv "$src/.migrated-to.$$" "$src/.migrated-to"; then
    rm -f "$src/.migrated-to.$$"
    echo "  error: cannot mark projects-memory/$key as migrated; its links are untouched" >&2
    return 0
  fi
  say "migrated projects-memory/$key -> projects-memory/$newkey ($nfiles files; legacy entry kept with .migrated-to)"
}

for entry in "$PROJECTS_MEMORY_DIR"/*/; do
  entry=${entry%/}
  [[ -d "$entry" && ! -f "$entry/.migrated-to" ]] || continue
  owner=$(read_project_path "$entry")
  [[ -n "$owner" ]] || continue
  proj=$(project_path "$owner")
  [[ -d "$proj" ]] || continue
  if is_private "$proj"; then
    migrate_legacy_entry "$entry" "${entry##*/}" "$owner" "$proj"
    continue
  fi
  remote=$(project_remote "$proj")
  [[ -n "$remote" ]] || continue
  if budget_exhausted; then
    deferred=$((deferred + 1)); continue
  fi
  examined=$((examined + 1))
  migrate_legacy_entry "$entry" "${entry##*/}" "$owner" "$proj"
done

# ─── Pass 2: prune memory links that are provably wrong ──────────────────────

for pd in "${PROJECTS_DIRS[@]}"; do
  label=$(label_of "$pd")
  for mem in "$pd"/*/memory; do
    [[ -L "$mem" ]] || continue
    target=$(link_target_phys "$mem") || continue
    [[ "${target%/*}" == "$PM_PHYS" ]] || continue   # not into the store: not ours
    key=${target##*/}
    entry="$PROJECTS_MEMORY_DIR/$key"
    slugdir=${mem%/memory}
    slug=${slugdir##*/}
    where="$label$slug"
    if [[ ! -d "$entry" ]]; then
      note "$where/memory: dangling link to projects-memory/$key, left for a human"; continue
    fi

    owner=$(read_project_path "$entry")
    remote=$(read_project_remote "$entry")
    migrated=$(read_migrated_to "$entry")
    reason=""
    private=0
    retire=0
    if [[ -n "$remote" && "$key" != "$(key_of_remote "$remote")" ]]; then
      note "$where/memory: projects-memory/$key has a mismatched .project-remote, left for a human"; continue
    fi
    if [[ -n "$remote" ]]; then
      owners=$(read_host_paths "$entry")
      matched=0
      while IFS= read -r owner; do
        [[ -n "$owner" ]] || continue
        proj=$(project_path "$owner")
        [[ "$slug" == "$(slug_of_path "$proj")" ]] || continue
        matched=1
        if is_private "$proj"; then private=1; fi
      done <<< "$owners"
      if [[ "$matched" -eq 1 && "$private" -eq 0 ]]; then continue; fi
      if [[ "$matched" -eq 0 ]]; then
        dec=$(decode_slug "$slug")
        if printf '%s\n' "$dec" | any_private; then
          private=1
        else
          while IFS= read -r proj; do
            [[ -n "$proj" ]] || continue
            case "$proj/" in "$HOME_PHYS"/*) ;; *) continue ;; esac
            [[ "$(project_remote "$proj")" == "$remote" ]] || continue
            if [[ "$proj" == "$HOME_PHYS" ]]; then owner="."; else owner=${proj#"$HOME_PHYS"/}; fi
            record_host_path "$entry" "$owner" || true
            matched=1
          done < <(printf '%s\n' "$dec" | filter_paths roots)
          if [[ "$matched" -eq 1 ]]; then continue; fi
          reason="projects-memory/$key has no checkout with origin $remote at this slug on $HOST_NAME"
        fi
      fi
    elif [[ -f "$entry/.migrated-to" ]]; then
      if [[ -z "$migrated" || ! -d "$PROJECTS_MEMORY_DIR/$migrated" ]]; then
        note "$where/memory: projects-memory/$key has an invalid migration target, left for a human"; continue
      fi
      if [[ -n "$owner" ]]; then
        proj=$(project_path "$owner")
        if [[ "$slug" == "$(slug_of_path "$proj")" ]] && is_private "$proj"; then
          private=1
        else
          reason="migrated to projects-memory/$migrated"; retire=1
        fi
      else
        reason="migrated to projects-memory/$migrated"; retire=1
      fi
    elif [[ -n "$owner" ]]; then
      proj=$(project_path "$owner")
      if [[ "$slug" == "$(slug_of_path "$proj")" ]]; then
        is_private "$proj" || continue
        private=1
      else
        reason="projects-memory/$key belongs to ~/$owner"
      fi
    elif ! command -v cygpath >/dev/null 2>&1 && [[ "$slug" != -* ]]; then
      reason="no leading '-': Claude Code never reads this directory"
    else
      dec=$(decode_slug "$slug")
      if printf '%s\n' "$dec" | any_private; then
        private=1
      elif [[ -n "$(printf '%s\n' "$dec" | filter_paths roots)" ]]; then
        continue
      elif [[ -n "$dec" ]]; then
        reason="only a .git path, a repository subdirectory or a linked worktree has this slug"
      elif command -v cygpath >/dev/null 2>&1; then
        continue   # outside $HOME on Windows: undecidable here, keep it
      else
        reason="no directory on this machine has this slug"
      fi
    fi

    if [[ "$private" -eq 1 ]]; then
      detach "$mem" "$entry" "$where" "$key"
      continue
    fi
    if [[ "$DRY_RUN" -eq 1 ]]; then
      extra=""; [[ "$retire" -eq 1 ]] && extra="; original kept beside it"
      say "prune $where/memory -> projects-memory/$key ($reason$extra)"
      continue
    fi
    if [[ "$retire" -eq 1 ]]; then
      backup=$(next_memory_backup "$slugdir")
      if mv "$mem" "$backup"; then
        say "pruned $where/memory -> projects-memory/$key ($reason; original kept as ${backup##*/})"
      else
        echo "  error: could not preserve $where/memory before relinking; the old link stays" >&2
      fi
    else
      rm -f "$mem" && say "pruned $where/memory -> projects-memory/$key ($reason)"
    fi
    rmdir "$slugdir" 2>/dev/null || true   # only if nothing else lives there
  done
done

# ─── Pass 3: link store entries to this machine's projects ───────────────────

DISCOVERY_INDEX=$'\n'
DISCOVERY_BUILT=0
DISCOVERY_COMPLETE=0
build_discovery_index() {   # one origin -> all candidate roots index per run
  [[ "$DISCOVERY_BUILT" -eq 0 ]] || return 0
  DISCOVERY_BUILT=1
  local home_slug pd slugdir slug dec p phys remote seen_slugs=$'\n' seen_paths=$'\n'
  home_slug=$(slug_of_path "$HOME_PHYS")
  for pd in "${PROJECTS_DIRS[@]}"; do
    for slugdir in "$pd"/*; do
      [[ -d "$slugdir" ]] || continue
      slug=${slugdir##*/}
      case "$slug" in "$home_slug"|"$home_slug"-*) ;; *) continue ;; esac
      case "$seen_slugs" in *$'\n'"$slug"$'\n'*) continue ;; esac
      seen_slugs="$seen_slugs$slug"$'\n'
      if budget_exhausted; then return 0; fi
      examined=$((examined + 1))
      dec=$(decode_slug "$slug")
      [[ -n "$dec" ]] || continue
      if printf '%s\n' "$dec" | any_private; then continue; fi
      while IFS= read -r p; do
        [[ -n "$p" ]] || continue
        case "$p/" in "$HOME_PHYS"/*) ;; *) continue ;; esac
        phys=$(cd "$p" 2>/dev/null && pwd -P) || continue
        case "$seen_paths" in *$'\n'"$phys"$'\n'*) continue ;; esac
        seen_paths="$seen_paths$phys"$'\n'
        remote=$(project_remote "$p")
        [[ -n "$remote" ]] || continue
        DISCOVERY_INDEX="$DISCOVERY_INDEX$remote"$'\t'"$p"$'\n'
      done < <(printf '%s\n' "$dec" | filter_paths roots)
    done
  done
  DISCOVERY_COMPLETE=1
}

find_remote_project() {   # REMOTE — every indexed checkout of this origin
  local wanted=$1
  build_discovery_index
  printf '%s' "$DISCOVERY_INDEX" | awk -F '\t' -v wanted="$wanted" \
    '$1 == wanted { sub(/^[^\t]*\t/, ""); print }'
}

for entry in "$PROJECTS_MEMORY_DIR"/*/; do
  entry=${entry%/}
  [[ -d "$entry" ]] || continue
  key=${entry##*/}
  if [[ -f "$entry/.migrated-to" ]] || planned_migration "$key"; then
    note "projects-memory/$key: retired by .migrated-to, not linked"; continue
  fi
  remote=$(read_project_remote "$entry")
  owner=$(read_project_path "$entry")
  projects=""
  named=0

  if [[ -n "$remote" ]]; then
    if [[ "$key" != "$(key_of_remote "$remote")" ]]; then
      note "projects-memory/$key: .project-remote does not match its key"; continue
    fi
    named=1
    owners=$(read_host_paths "$entry")
    if [[ -z "$owners" ]]; then
      build_discovery_index
      found=$(find_remote_project "$remote")
      if [[ -z "$found" ]]; then
        if [[ "$DISCOVERY_COMPLETE" -eq 0 ]]; then
          deferred=$((deferred + 1))
        else
          note "projects-memory/$key: no local project with origin '$remote' has a memory slug here"
        fi
        continue
      fi
      while IFS= read -r proj; do
        [[ -n "$proj" ]] || continue
        if [[ "$proj" == "$HOME_PHYS" ]]; then owner="."; else owner=${proj#"$HOME_PHYS"/}; fi
        if ! record_host_path "$entry" "$owner"; then
          echo "  error: cannot record projects-memory/$key for $HOST_NAME; it is not linked" >&2
          continue
        fi
        projects="$projects$proj"$'\n'
      done <<< "$found"
    else
      while IFS= read -r owner; do
        [[ -n "$owner" ]] || continue
        projects="$projects$(project_path "$owner")"$'\n'
      done <<< "$owners"
    fi
  elif [[ -n "$owner" ]]; then
    named=1
    projects="$(project_path "$owner")"$'\n'
  else
    # Legacy entry, named by basename: exactly one directory of that name
    # directly under a search root, and one Claude Code could key memory by.
    found=""; seen=$'\n'
    for root in "${SEARCH_ROOTS[@]}"; do
      [[ -d "$root/$key" ]] || continue
      phys=$(cd "$root/$key" 2>/dev/null && pwd -P) || continue
      case "$seen" in *$'\n'"$phys"$'\n'*) continue ;; esac
      seen="$seen$phys"$'\n'
      is_memory_root "$phys" || continue
      found="$found$phys"$'\n'
    done
    found=${found%$'\n'}
    if [[ -z "$found" ]]; then
      note "projects-memory/$key: no top-level project named '$key' here"; continue
    fi
    if [[ "$(printf '%s\n' "$found" | wc -l | tr -d ' ')" -gt 1 ]]; then
      note "projects-memory/$key: several projects are named '$key': $(printf '%s\n' "$found" | oneline)"; continue
    fi
    projects="$found"$'\n'
  fi

  while IFS= read -r proj; do
    [[ -n "$proj" ]] || continue
    if [[ ! -d "$proj" ]]; then
      note "projects-memory/$key: $proj is not on this machine for $HOST_NAME"; continue
    fi
    if is_private "$proj"; then
      note "projects-memory/$key: $proj is a private project, not linked"; continue
    fi
    slug=$(slug_of_path "$proj")
    if [[ ${#slug} -gt 200 ]]; then
      note "projects-memory/$key: slug past 200 characters (Claude Code hashes it)"; continue
    fi

    for pd in "${PROJECTS_DIRS[@]}"; do
      where="$(label_of "$pd")$slug"
      mem="$pd/$slug/memory"
      if [[ -L "$mem" ]]; then
        # Followed to the end: a profile's link to ~/.claude/projects/<slug>/memory,
        # itself a link to this entry, is already right.
        cur=$(cd "$mem" 2>/dev/null && pwd -P) || cur=""
        [[ "$cur" == "$PM_PHYS/$key" ]] && continue
        if [[ "$named" -eq 1 ]]; then
          conflict "$where/memory -> $(readlink "$mem") is kept; projects-memory/$key claims the same project (merge by hand)"
        else
          note "projects-memory/$key: $where/memory already links to $(readlink "$mem")"
        fi
        continue
      fi
      if [[ -e "$mem" ]]; then
        note "projects-memory/$key: $where/memory is a local directory (see the adopt pass)"; continue
      fi
      if [[ "$DRY_RUN" -eq 1 ]]; then
        say "link $where/memory -> projects-memory/$key"
        continue
      fi
      mkdir -p "$pd/$slug" && ln -s "$entry" "$mem" \
        && say "linked $where/memory -> projects-memory/$key"
    done
  done <<< "$projects"
done

if [[ "$deferred" -gt 0 ]]; then
  echo "  deferred: $deferred memory directories to the next run (time budget ${BUDGET}s; CLADE_SYNC_LINK_BUDGET=0 lifts it)"
fi

[[ "$DRY_RUN" -eq 1 ]] && exit 0

# ─── Record conflicts where a reader finds them ──────────────────────────────
# A complete run rewrites the list, so a conflict merged by hand disappears. A
# run that deferred directories did not look at all of them, so it only adds.

if [[ "$deferred" -gt 0 && -f "$CONFLICT_STATE" ]]; then
  CONFLICTS=$( { cat "$CONFLICT_STATE"; printf '%s' "$CONFLICTS"; } | awk 'NF && !seen[$0]++')
  [[ -n "$CONFLICTS" ]] && CONFLICTS="$CONFLICTS"$'\n'
fi
if [[ -n "$CONFLICTS" ]]; then
  printf '%s' "$CONFLICTS" > "$CONFLICT_STATE.$$" && mv "$CONFLICT_STATE.$$" "$CONFLICT_STATE"
else
  rm -f "$CONFLICT_STATE"
fi

# ─── Commit what the store holds uncommitted ─────────────────────────────────
# Copied into the store is not yet history. Decided from the store's own state,
# not from this run's adoptions: an adoption whose commit was lost (the run was
# killed, or sync-push found its lock held and skipped) is committed by the next
# run. sync-push.sh carries the conflict-marker and privacy guards, and pushes
# only when a remote exists.

if [[ -f "$SCRIPT_DIR/sync-push.sh" ]] \
   && [[ -n "$(git -C "$SYNC_DIR" status --porcelain -- projects-memory 2>/dev/null)" ]]; then
  bash "$SCRIPT_DIR/sync-push.sh" >/dev/null || true
fi

exit 0
