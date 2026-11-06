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
# Three passes, in this order:
#   adopt  A real (not symlinked) local memory directory is copied into the store
#          as projects-memory/<key>/ with a .project-path file holding the
#          project's path relative to $HOME. The copy is checked file by file
#          (cksum: CRC and size), then the directory is replaced by a symlink to
#          it. The original stays beside it as memory.pre-sync-<timestamp>. If
#          the store entry already holds a DIFFERENT version of a file, or the
#          name belongs to another project, nothing moves and the conflict is
#          recorded (below).
#   prune  A memory symlink into the store that is provably wrong is removed (the
#          link only, never store content): one into an entry whose
#          .project-path names a different project, or, for a legacy entry, one
#          at a slug no memory root on this machine produces: no leading "-",
#          or only a path inside .git, a repository subdirectory or a linked
#          worktree, or no existing directory at all. A private project's link
#          is detached instead: a verified local copy replaces it.
#   link   An entry with .project-path is linked to the slug of $HOME/<path> when
#          that directory exists here, in every projects directory. A legacy
#          entry (no .project-path, named by basename) is linked only to a
#          directory of exactly that name directly under one search root. Links
#          are only ever CREATED: an existing link or directory is never
#          replaced, only reported.
#
# Bounded, because sync-pull.sh runs this inside an async SessionStart hook with
# a 30 s timeout: once CLADE_SYNC_LINK_BUDGET seconds (default 10; 0 = no limit)
# have passed, the remaining memory directories are left for the next run and
# counted as deferred. At least one directory is examined per run. The first run
# on a host with a long backlog can be run by hand without the limit:
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
# a UTF-8 locale. A project path differing in case between machines
# (`projects/Clade` vs `projects/clade`) gets one store entry per spelling. A run
# killed in the middle of a copy leaves a partial store entry and an intact local
# directory. The next run completes the entry, except that a file cut short
# differs from the local one and is reported as a conflict, not overwritten.
# Until then any sync-push.sh (they all `git add -A`) may commit the partial
# entry. The copy is one tar pipe per directory, and no directory starts after
# the budget, so this needs a kill inside that pipe.
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

read_project_path() {   # an entry's .project-path, or nothing for a legacy entry
  local f="$1/.project-path" line=""
  [[ -f "$f" ]] || return 0
  IFS= read -r line < "$f" || true
  line=${line%$'\r'}
  # A path that climbs out of $HOME or is absolute is not one this script wrote.
  case "/$line/" in */../*) return 0 ;; esac
  case "$line" in ''|/*) return 0 ;; esac
  printf '%s' "$line"
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
  files=$(regular_files "$entry" | grep -vx './\.project-path')
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
    if [[ "$DRY_RUN" -eq 0 && "$BUDGET" -gt 0 && "$examined" -gt 0 && "$SECONDS" -ge "$BUDGET" ]]; then
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
    key=$(key_of_rel "$rel")
    if [[ ${#key} -gt 200 ]]; then
      note "$where: store key would exceed 200 characters"; continue
    fi
    dst="$PROJECTS_MEMORY_DIR/$key"
    files=$(regular_files "$mem")

    if [[ -e "$dst" || -L "$dst" ]]; then
      owner=$(read_project_path "$dst")
      if [[ "$owner" != "$rel" ]]; then
        conflict "$where is not adopted — projects-memory/$key already belongs to ${owner:+~/}${owner:-a legacy entry with no .project-path}"
        continue
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
    [[ -f "$dst/.project-path" ]] || printf '%s\n' "$rel" > "$dst/.project-path"
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
if [[ "$deferred" -gt 0 ]]; then
  echo "  deferred: $deferred memory directories to the next run (time budget ${BUDGET}s; CLADE_SYNC_LINK_BUDGET=0 lifts it)"
fi

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
    reason=""
    private=0
    if [[ -n "$owner" ]]; then
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
      say "prune $where/memory -> projects-memory/$key ($reason)"
      continue
    fi
    rm -f "$mem" && say "pruned $where/memory -> projects-memory/$key ($reason)"
    rmdir "$slugdir" 2>/dev/null || true   # only if nothing else lives there
  done
done

# ─── Pass 3: link store entries to this machine's projects ───────────────────

for entry in "$PROJECTS_MEMORY_DIR"/*/; do
  entry=${entry%/}
  [[ -d "$entry" ]] || continue
  key=${entry##*/}
  owner=$(read_project_path "$entry")

  if [[ -n "$owner" ]]; then
    proj=$(project_path "$owner")
    if [[ ! -d "$proj" ]]; then
      note "projects-memory/$key: ~/$owner is not on this machine"; continue
    fi
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
    proj=$found
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
      if [[ -n "$owner" ]]; then
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
done

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
