#!/usr/bin/env bash
# sync-link-projects.sh — Keep every project's auto-memory inside the sync store,
# and link each store entry back to the directory Claude Code reads it from.
#
# Claude Code reads a project's auto-memory from ~/.claude/projects/<slug>/memory/.
# <slug> is the project's absolute path with every character outside [A-Za-z0-9]
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
# Three passes, in this order:
#   adopt  A real (not symlinked) local memory directory is copied into the store
#          as projects-memory/<key>/ with a .project-path file holding the
#          project's path relative to $HOME. Every file is compared byte for
#          byte, then the directory is replaced by a symlink to the copy. The
#          original stays beside it as memory.pre-sync-<timestamp>. If the store
#          entry already holds a DIFFERENT version of a file, nothing moves and
#          the files are named. Private projects (listed in
#          ~/.claude/private-projects, or carrying .claude/conversation-mode)
#          are never adopted. After an adoption, sync-push.sh commits it.
#   prune  A memory symlink into the store that is provably wrong is removed (the
#          link only, never store content): one into an entry whose
#          .project-path names a different project, or, for a legacy entry, one
#          at a slug no memory root on this machine produces: no leading "-",
#          or only a path inside .git, a repository subdirectory or a linked
#          worktree, or no existing directory at all.
#   link   An entry with .project-path is linked to the slug of $HOME/<path> when
#          that directory exists here. A legacy entry (no .project-path, named by
#          basename) is linked only to a directory of exactly that name directly
#          under one search root. Links are only ever CREATED: an existing link
#          or directory is never replaced, only reported.
#
# Usage: sync-link-projects.sh [--dry-run] [--verbose]
#   --dry-run  print what would change, and every skip with its reason; change
#              nothing. Safe against a live ~/.claude.
#   --verbose  also print what was skipped, and why.
#
# Limits: a slug past 200 characters is skipped (Claude Code's hash suffix is
# not reproduced here). A path holding non-ASCII characters matches only under
# a UTF-8 locale. A project path differing in case between machines
# (`projects/Clade` vs `projects/clade`) gets one store entry per spelling.
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
PROJECTS_DIR="$CLAUDE_DIR/projects"
SCRIPT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"

[[ -f "$SYNC_CONFIG" ]] || exit 0
# shellcheck source=/dev/null
source "$SYNC_CONFIG"
[[ "${SYNC_BACKEND:-none}" == "none" ]] && exit 0
# An unreachable store (NFS mount dropped) must not read as "every link is wrong".
[[ -n "${SYNC_DIR:-}" && -d "$SYNC_DIR" ]] || exit 0
[[ -d "$PROJECTS_DIR" ]] || exit 0

PROJECTS_MEMORY_DIR="$SYNC_DIR/projects-memory"
if [[ ! -d "$PROJECTS_MEMORY_DIR" ]]; then
  [[ "$DRY_RUN" -eq 1 ]] && exit 0
  mkdir -p "$PROJECTS_MEMORY_DIR" || exit 0
fi
PM_PHYS=$(cd "$PROJECTS_MEMORY_DIR" && pwd -P) || exit 0
HOME_PHYS=$(cd "$HOME" && pwd -P) || exit 0
PRIVATE_PROJECTS_FILE="${CLADE_PRIVATE_PROJECTS:-$CLAUDE_DIR/private-projects}"
STAMP=$(date +%Y%m%d%H%M%S)

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

# paths_of_slug MODE SLUG — decoded paths, one per physical directory. MODE
# "roots" keeps memory roots only; "any" keeps every path outside .git.
paths_of_slug() {
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
  done < <(decode_slug "$2")
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

# differing_files MODE SRC DST — files under SRC that DST lacks or holds
# differently ("missing-or-different"), or that DST holds differently
# ("conflicting": present in both, bytes differ).
differing_files() {
  local mode=$1 src=$2 dst=$3 f
  (cd "$src" && find . -type f -print) | while IFS= read -r f; do
    f=${f#./}
    if [[ -f "$dst/$f" ]]; then
      cmp -s "$src/$f" "$dst/$f" || printf '%s\n' "$f"
    elif [[ "$mode" == "missing-or-different" ]]; then
      printf '%s\n' "$f"
    fi
  done
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

# ─── Pass 1: adopt local memory into the store ───────────────────────────────

adopted=0
for mem in "$PROJECTS_DIR"/*/memory; do
  [[ -d "$mem" && ! -L "$mem" ]] || continue
  slugdir=${mem%/memory}
  slug=${slugdir##*/}
  if [[ -z "$(ls -A "$mem" 2>/dev/null)" ]]; then
    note "$slug: memory directory is empty"; continue
  fi

  # Prefer a directory current Claude Code keys memory by; an older version
  # keyed it by the session's own directory, and that memory deserves history too.
  cands=$(paths_of_slug roots "$slug")
  [[ -n "$cands" ]] || cands=$(paths_of_slug any "$slug")
  if [[ -z "$cands" ]]; then
    note "$slug: no project directory on this machine has this slug"; continue
  fi
  if [[ "$(printf '%s\n' "$cands" | wc -l | tr -d ' ')" -gt 1 ]]; then
    note "$slug: several directories share this slug: $(printf '%s\n' "$cands" | oneline)"; continue
  fi
  proj=$cands
  case "$proj/" in
    "$HOME_PHYS"/*) ;;
    *) note "$slug: $proj is outside \$HOME, so it has no portable name"; continue ;;
  esac
  if is_private "$proj"; then
    note "$slug: private project, its memory stays on this machine"; continue
  fi
  if [[ "$proj" == "$HOME_PHYS" ]]; then rel="."; else rel=${proj#"$HOME_PHYS"/}; fi
  key=$(key_of_rel "$rel")
  if [[ ${#key} -gt 200 ]]; then
    note "$slug: store key would exceed 200 characters"; continue
  fi
  dst="$PROJECTS_MEMORY_DIR/$key"

  if [[ -e "$dst" || -L "$dst" ]]; then
    owner=$(read_project_path "$dst")
    if [[ "$owner" != "$rel" ]]; then
      echo "  conflict: $slug is not adopted — projects-memory/$key already belongs to ${owner:+~/}${owner:-a legacy entry with no .project-path}"
      continue
    fi
    clash=$(differing_files conflicting "$mem" "$dst" | oneline)
    if [[ -n "$clash" ]]; then
      echo "  conflict: $slug is not adopted — these files differ from projects-memory/$key: $clash (merge by hand: diff -r '$mem' '$dst')"
      continue
    fi
  fi

  nfiles=$( (cd "$mem" && find . -type f) | wc -l | tr -d ' ')
  # Regular files only. A symlink inside a memory directory is not something
  # Claude Code writes; the old linker left them (`ln -sfn` onto a real
  # directory links INSIDE it), and copied into the store they would commit an
  # absolute path to this machine. They stay in the kept original.
  links=$( (cd "$mem" && find . -type l) | sed 's|^\./||' | oneline)
  extra=""
  [[ -n "$links" ]] && extra="; symlinks not copied: $links"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    say "adopt $slug -> projects-memory/$key ($nfiles files, ~/$rel$extra)"
    adopted=$((adopted + 1))
    continue
  fi

  mkdir -p "$dst" || { echo "  error: cannot create $dst" >&2; continue; }
  [[ -f "$dst/.project-path" ]] || printf '%s\n' "$rel" > "$dst/.project-path"
  copy_failed=0
  while IFS= read -r f; do
    f=${f#./}
    mkdir -p "$(dirname "$dst/$f")" && cp -p "$mem/$f" "$dst/$f" || copy_failed=1
  done < <(cd "$mem" && find . -type f -print)
  if [[ "$copy_failed" -ne 0 ]]; then
    echo "  error: copying $slug into the store failed; the local directory is untouched" >&2
    continue
  fi
  bad=$(differing_files missing-or-different "$mem" "$dst" | oneline)
  if [[ -n "$bad" ]]; then
    echo "  error: the store copy of $slug does not match ($bad); the local directory is untouched" >&2
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
    echo "  error: could not link $slug/memory to the store; the original is at $backup" >&2
    continue
  fi
  # A write that landed between the copy and the move is in the backup only.
  late=$(differing_files missing-or-different "$backup" "$dst")
  if [[ -n "$late" ]]; then
    while IFS= read -r f; do
      mkdir -p "$(dirname "$dst/$f")" && cp -p "$backup/$f" "$dst/$f"
    done <<< "$late"
  fi
  say "adopted $slug -> projects-memory/$key ($nfiles files; original kept as ${backup##*/}$extra)"
  adopted=$((adopted + 1))
done

# ─── Pass 2: prune memory links that are provably wrong ──────────────────────

for mem in "$PROJECTS_DIR"/*/memory; do
  [[ -L "$mem" ]] || continue
  target=$(link_target_phys "$mem") || continue
  [[ "${target%/*}" == "$PM_PHYS" ]] || continue   # not into the store: not ours
  key=${target##*/}
  entry="$PROJECTS_MEMORY_DIR/$key"
  slugdir=${mem%/memory}
  slug=${slugdir##*/}
  if [[ ! -d "$entry" ]]; then
    note "$slug/memory: dangling link to projects-memory/$key, left for a human"; continue
  fi

  owner=$(read_project_path "$entry")
  reason=""
  if [[ -n "$owner" ]]; then
    [[ "$slug" == "$(slug_of_path "$(project_path "$owner")")" ]] && continue
    reason="projects-memory/$key belongs to ~/$owner"
  elif ! command -v cygpath >/dev/null 2>&1 && [[ "$slug" != -* ]]; then
    reason="no leading '-': Claude Code never reads this directory"
  elif [[ -n "$(paths_of_slug roots "$slug")" ]]; then
    continue
  elif [[ -n "$(decode_slug "$slug")" ]]; then
    reason="only a .git path, a repository subdirectory or a linked worktree has this slug"
  elif command -v cygpath >/dev/null 2>&1; then
    continue   # outside $HOME on Windows: undecidable here, keep it
  else
    reason="no directory on this machine has this slug"
  fi

  if [[ "$DRY_RUN" -eq 1 ]]; then
    say "prune $slug/memory -> projects-memory/$key ($reason)"
    continue
  fi
  rm -f "$mem" && say "pruned $slug/memory -> projects-memory/$key ($reason)"
  rmdir "$slugdir" 2>/dev/null || true   # only if nothing else lives there
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
    slug=$(slug_of_path "$proj")
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
    slug=$(slug_of_path "$found")
  fi
  if [[ ${#slug} -gt 200 ]]; then
    note "projects-memory/$key: slug past 200 characters (Claude Code hashes it)"; continue
  fi

  mem="$PROJECTS_DIR/$slug/memory"
  if [[ -L "$mem" ]]; then
    cur=$(link_target_phys "$mem") || cur=""
    [[ "$cur" == "$PM_PHYS/$key" ]] && continue
    if [[ -n "$owner" ]]; then
      echo "  conflict: $slug/memory -> $(readlink "$mem") is kept; projects-memory/$key claims the same project (merge by hand)"
    else
      note "projects-memory/$key: $slug/memory already links to $(readlink "$mem")"
    fi
    continue
  fi
  if [[ -e "$mem" ]]; then
    note "projects-memory/$key: $slug/memory is a local directory (see the adopt pass)"; continue
  fi
  if [[ "$DRY_RUN" -eq 1 ]]; then
    say "link $slug/memory -> projects-memory/$key"
    continue
  fi
  mkdir -p "$PROJECTS_DIR/$slug" && ln -s "$entry" "$mem" \
    && say "linked $slug/memory -> projects-memory/$key"
done

# ─── Commit what was adopted ─────────────────────────────────────────────────
# Copied into the store is not yet history: commit now rather than waiting for
# the next memory write to trigger memory-sync.sh. sync-push.sh carries the
# conflict-marker and privacy guards, and pushes only when a remote exists.

if [[ "$DRY_RUN" -eq 0 && "$adopted" -gt 0 && -f "$SCRIPT_DIR/sync-push.sh" ]]; then
  bash "$SCRIPT_DIR/sync-push.sh" >/dev/null || true
fi

exit 0
