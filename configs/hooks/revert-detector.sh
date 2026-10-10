#!/usr/bin/env bash
# revert-detector.sh — Detect git revert/reset commands as implicit corrections
# Triggered by PreToolUse on Bash
#
# When a user (or Claude) runs git revert, git reset --hard, git checkout -- <file>,
# or git restore <file>, log it as an implicit correction signal.
#
# Fail-open: errors are silently ignored. Does NOT block the command.

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // ""' 2>/dev/null || echo "")

if [[ "$TOOL_NAME" != "Bash" ]]; then
  exit 0
fi

RAW_COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null || echo "")

if [[ -z "$RAW_COMMAND" ]]; then
  exit 0
fi

# ─── Heredoc bodies are data, not commands ───────────────────────────
# rd_strip_heredocs <command> — the command with every heredoc BODY removed; the
# line that opens the heredoc is kept, so commands after `<<'EOF' &&` still count.
#
# Agents write files through `python3 - <<'EOF'` and `cat > f <<EOF`, and the body
# is often prose ABOUT git. Measured 2026-09-28 21:48Z: a python heredoc rewriting
# a README whose text documented `git checkout -- site/static/palette.json` and
# `cd ~/code/product/app-lego-mosaic && git pull` was logged as an implicit-revert
# correction filed under the project `~/code/product/app-lego-mosaic` — a path on
# another user's machine. Nothing was reverted. The 2026-09-28 `cd` resolution
# alone does not fix it: it would expand the README's `~` and file the record
# under `$HOME/code/product/app-lego-mosaic` instead.
#
# Recognises `<<WORD`, `<<'WORD'`, `<<"WORD"` and `<<-WORD` (leading tabs stripped
# from the terminator), and never a here-string `<<<`. Known limits, both failing
# toward silence: only the first heredoc on a line is tracked, and a `<<word`
# inside a quoted string swallows the rest of the command.
rd_strip_heredocs() {
  local line delim="" strip_tabs=false t tab=$'\t' q="[\"']?"
  local re_heredoc="(^|[^<])<<(-?)[[:space:]]*${q}([A-Za-z_][A-Za-z0-9_]*)${q}"
  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ -n "$delim" ]]; then
      t="$line"
      if $strip_tabs; then
        while [[ "$t" == "$tab"* ]]; do t="${t#"$tab"}"; done
      fi
      [[ "$t" == "$delim" ]] && delim=""
      continue
    fi
    printf '%s\n' "$line"
    if [[ "$line" =~ $re_heredoc ]]; then
      delim="${BASH_REMATCH[3]}"
      strip_tabs=false
      [[ -n "${BASH_REMATCH[2]}" ]] && strip_tabs=true
    fi
  done <<< "$1"
}

# Everything below reads COMMAND; only the persisted `prompt` keeps the raw text.
COMMAND=$(rd_strip_heredocs "$RAW_COMMAND")

# ─── Detect revert patterns ──────────────────────────────────────────
REVERT_PATTERNS=(
  'git[[:space:]]+revert'
  'git[[:space:]]+reset[[:space:]]+--hard'
  'git[[:space:]]+checkout[[:space:]]+--[[:space:]]'
  'git[[:space:]]+restore[[:space:]]'
)

MATCHED=false
for pattern in "${REVERT_PATTERNS[@]}"; do
  if echo "$COMMAND" | grep -qE "$pattern" 2>/dev/null; then
    MATCHED=true
    break
  fi
done

if ! $MATCHED; then
  exit 0
fi

# ─── Log as implicit correction, paired with the rejected files ───────
LIBDIR="$(cd "$(dirname "$0")" && pwd)/lib"
source "$LIBDIR/correction-pair.sh" 2>/dev/null || true

CORRECTIONS_DIR="$HOME/.claude/corrections"
mkdir -p "$CORRECTIONS_DIR" 2>/dev/null
HISTORY_FILE="$CORRECTIONS_DIR/history.jsonl"
TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
# PROJECT is assigned after rd_revert_base is defined — see below. It is not
# $CLAUDE_PROJECT_DIR, which names the session's repository rather than the one
# the git command touched.
PROJECT=""

# ─── Parse the revert command's own pathspec ──────────────────────────
# `reverted_files` used to be filled straight from cp_recent_files(session, 20) —
# the last 20 files Claude touched THIS SESSION, never intersected with the paths
# the git command actually names. Measured on a real history.jsonl: 21 records
# held exactly 20 files (the cap), and one record filed under project Clade for
# `cd ../codex-statusline-patch && git checkout -- codex-rs/Cargo.lock` listed 20
# files, none of them Cargo.lock. `repeat` then intersected two such session lists,
# so it measured session overlap, not recurrence.
#
# So: intersect the shadow with the command's OWN pathspec. Only two of the four
# matched command forms carry one — `git revert <commit>` takes no pathspec and
# `git reset --hard` cannot take one (git rejects pathspec + --hard). Their file
# set is only recoverable by querying git, and this hook is wired async on
# PreToolUse, so such a query would race the very command it describes. For those
# the honest answer is "not knowable here": reverted_files [] and repeat null.
# The loose session list is still recorded, under its true name `session_files`.

# rd_segments <command> — split a shell command into rough segments on ; | & and
# newlines. tr (not sed) because BSD sed has no \n in the replacement. The
# trailing newline from printf is required: `read` returns non-zero on a final
# unterminated line, so without it a while-read loop silently drops the last
# segment — which for a one-segment command is the whole command.
rd_segments() {
  # set2 repeats \n deliberately: POSIX leaves short-set2 padding unspecified.
  # shellcheck disable=SC2020
  printf '%s\n' "$1" | tr ';|&' '\n\n\n'
}

# rd_unquote <token> — strip one layer of surrounding quotes.
rd_unquote() {
  local t="$1"
  t="${t#\"}"; t="${t%\"}"
  t="${t#\'}"; t="${t%\'}"
  printf '%s' "$t"
}

# rd_is_revert_segment <segment> — true when this one segment is itself a revert.
rd_is_revert_segment() {
  local seg="$1" pattern
  for pattern in "${REVERT_PATTERNS[@]}"; do
    [[ "$seg" =~ $pattern ]] && return 0
  done
  return 1
}

# rd_revert_base <command> <input_json> — the directory the git command ran in.
# `cd <dir> && git ...` is the dominant real-world shape (68 of 68 informative
# records on the author's machine begin with it), and it is exactly the case that
# made the old records wrong: the session shadow is from one repo, the command
# operates on another.
#
# Three ways the literal `cd` token was still the wrong answer, all measured in
# history.jsonl between 2026-09-21 and 2026-09-28:
# - `WT=/abs/path … cd "$WT"` filed records under a project literally named `$WT`
#   (twice) and `$SCR/repo` (once). A variable the same command assigns is
#   resolved here; one it does not assign is unknowable, and the session's own
#   directory is the honest fallback — never the unexpanded text.
# - `cd ~/projects/Clade` filed under `~/projects/Clade`, a second key for a repo
#   every other record spells `/home/…/Clade`.
# - The LAST `cd` won, even one AFTER the revert: `cd svc && git checkout -- src
#   && cd .. && committer …` was filed under the parent. Only a `cd` that runs
#   before the first revert segment can be where the revert ran.
rd_revert_base() {
  local cmd="$1" input="$2" seg base="" cwd="" assigns="" tok w line name rest val
  local re_var='^\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?(.*)$'
  local re_assign='^[A-Za-z_][A-Za-z0-9_]*='
  local -a words
  if command -v jq >/dev/null 2>&1; then
    cwd=$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null || true)
  fi
  cwd="${cwd:-${CLAUDE_PROJECT_DIR:-$(pwd)}}"
  while IFS= read -r seg; do
    rd_is_revert_segment "$seg" && break
    read -ra words <<< "$seg"
    [[ ${#words[@]} -ge 1 ]] || continue
    # remember NAME=value words in order; bash 3.2 has no associative arrays
    for w in "${words[@]}"; do
      [[ "$w" =~ $re_assign ]] && assigns="${assigns}${w}"$'\n'
    done
    [[ ${#words[@]} -ge 2 && "${words[0]}" == "cd" ]] || continue
    tok="$(rd_unquote "${words[1]}")"
    if [[ "$tok" =~ $re_var ]]; then
      name="${BASH_REMATCH[1]}"; rest="${BASH_REMATCH[2]}"; val=""
      while IFS= read -r line; do
        [[ "$line" == "$name="* ]] && val="$(rd_unquote "${line#"$name="}")"
      done <<< "$assigns"
      tok="${val:+$val$rest}"
    fi
    case "$tok" in
      '~')   tok="$HOME" ;;
      '~/'*) tok="$HOME/${tok#\~/}" ;;
    esac
    # still carrying an expansion we cannot perform → unknowable, not a path
    case "$tok" in
      ''|*'$'*|*'`'*) base=""; continue ;;
    esac
    if [[ "$tok" == /* ]]; then base="$tok"; else base="${base:-$cwd}/$tok"; fi
  done < <(rd_segments "$cmd")
  printf '%s' "${base:-$cwd}"
}

# rd_is_probe <command> — true when the command puts back what it reverts, so the
# revert is the agent's own mutation test rather than a rejected change.
#
# The global CLAUDE.md requires exactly this ("A self-test is not evidence until
# a mutation makes it fail"), and agents follow it with one command: save the
# diff, `git checkout -- src`, run the tests expecting red, `git apply` the diff
# back. Every such command was recorded as an implicit-revert correction. Measured
# on the author's machine, 2026-09-23 05:20–05:49: seven records, all mutation
# probes, two of them `repeat:true`, up to 13 files in `reverted_files` and 20 in
# `session_files` — and
# correction-detector.sh surfaces those files to the NEXT explicit correction in
# that project as "files behind this correction". The instrument the stack
# mandates was feeding false evidence to the instrument that learns from it.
#
# Two signals, strongest first:
# - a `git apply` / `git stash pop|apply` in a segment AFTER the revert — the
#   round-trip itself, independent of anything the agent chose to print;
# - the uppercase word MUTATION anywhere in the command — the label agents print
#   for the probe. Weaker (it is a convention, not a mechanism) but it is the only
#   signal for `sed -i … file; <test>; git checkout -- file`, where the revert IS
#   the restore step. Case-sensitive on purpose: `git checkout --
#   orchestrator/task_factory/mutation_scan.py` is a real revert of a real file.
rd_is_probe() {
  local cmd="$1" seg after=false
  local re_label='(^|[^A-Za-z0-9_])MUTATION([^A-Za-z0-9_]|$)'
  local re_restore='^[[:space:]]*git[[:space:]]+(apply|stash[[:space:]]+(pop|apply))([[:space:]]|$)'
  [[ "$cmd" =~ $re_label ]] && return 0
  while IFS= read -r seg; do
    if ! $after; then
      rd_is_revert_segment "$seg" && after=true
      continue
    fi
    [[ "$seg" =~ $re_restore ]] && return 0
  done < <(rd_segments "$cmd")
  return 1
}

# rd_is_redirect <token> — true when the token OPENS a shell redirection, so it
# is part of the plumbing rather than a pathspec. `rd_segments` splits on ; | &
# but not on redirections, so without this every `git checkout -- src/ 2>/dev/null`
# filed `2>/dev/null` as a path it reverted. Measured on this machine's real
# history.jsonl: 4 of the 7 `revert_scope:"paths"` records carried such a token
# (`2>/dev/null`, `>/dev/null`, `2>`).
#
# This is the SECOND time a parser here has read the `>` of `2>/dev/null` as
# content: `workflow-scorecard.py`'s mutation guard did it too, and reported
# zero polls for every session ever scanned (see CLAUDE.md). Splitting a command
# string on whitespace and keeping what does not look like a flag is the shape
# that keeps producing it.
#
# Digit-prefixed forms cover `2>`/`2>>`; the bare `&>`/`>&` arrive as `>` because
# `rd_segments` already split them on `&`.
rd_is_redirect() {
  case "$1" in
    '>'*|'<'*)                     return 0 ;;
    [0-9]'>'*|[0-9]'<'*)           return 0 ;;
    [0-9][0-9]'>'*|[0-9][0-9]'<'*) return 0 ;;
    *)                             return 1 ;;
  esac
}

# rd_redirect_is_bare <token> — true when the token is the operator ALONE (`>`,
# `2>`, `<<<`), so its target is the NEXT token and must be skipped too.
# `>/dev/null` carries its own target and consumes nothing further.
rd_redirect_is_bare() {
  case "$1" in
    *'>'|*'<') return 0 ;;
    *)         return 1 ;;
  esac
}

# rd_revert_pathspec <command> — one pathspec token per line, empty when the
# command names none. Tokens are emitted RAW: a glob or $(...) is not expanded,
# it simply fails to match, which is the correct fail-open here. Splitting is on
# whitespace, so a quoted path containing a space splits into fragments that
# match nothing — also fail-open (an empty set, never a wrong file). Dropping a
# redirection likewise only ever SHRINKS the set, so the failure direction stays
# "no file" rather than "the wrong file".
rd_revert_pathspec() {
  local seg tok i n ddash seen_ddash
  local -a words
  while IFS= read -r seg; do
    read -ra words <<< "$seg"
    n=${#words[@]}
    [[ $n -ge 2 ]] || continue
    [[ "${words[0]}" == "git" ]] || continue
    case "${words[1]}" in
      checkout)
        # only the `--` form is a pathspec revert; `git checkout <branch>` is not
        ddash=-1
        for (( i=2; i<n; i++ )); do
          if [[ "${words[$i]}" == "--" ]]; then ddash=$i; break; fi
        done
        for (( i=ddash+1; ddash >= 0 && i<n; i++ )); do
          tok="${words[$i]}"
          if rd_is_redirect "$tok"; then
            rd_redirect_is_bare "$tok" && i=$((i+1))
            continue
          fi
          printf '%s\n' "$(rd_unquote "$tok")"
        done
        ;;
      restore)
        seen_ddash=false
        for (( i=2; i<n; i++ )); do
          tok="${words[$i]}"
          if rd_is_redirect "$tok"; then
            rd_redirect_is_bare "$tok" && i=$((i+1))
            continue
          fi
          if $seen_ddash; then printf '%s\n' "$(rd_unquote "$tok")"; continue; fi
          case "$tok" in
            --)             seen_ddash=true ;;
            --source|-s)    i=$((i+1)) ;;   # its value is the next token
            -*)             : ;;            # any other flag (--staged, -SW, …)
            *)              printf '%s\n' "$(rd_unquote "$tok")" ;;
          esac
        done
        ;;
    esac
  done < <(rd_segments "$1")
}

# rd_match_shadow <base_dir> <pathspec_lines> <shadow_lines> — the intersection.
# Exact hit on $base/$P; else a suffix hit, because `cd` prefixes, worktrees and
# relative pathspecs make exact resolution unreliable and the cost of a suffix
# false positive is one extra path in an evidence list. Order follows the shadow,
# each shadow path emitted at most once.
rd_match_shadow() {
  local base="${1%/}" specs="$2" shadow="$3" s p cand
  [[ -n "$specs" && -n "$shadow" ]] || return 0
  while IFS= read -r s; do
    [[ -n "$s" ]] || continue
    while IFS= read -r p; do
      [[ -n "$p" ]] || continue
      p="${p#./}"; p="${p%/}"
      if [[ -z "$p" || "$p" == "." ]]; then
        # `git checkout -- .` — everything under the base directory
        [[ -n "$base" && "$s" == "$base"/* ]] && { printf '%s\n' "$s"; break; }
        continue
      fi
      if [[ "$p" == /* ]]; then cand="$p"; else cand="$base/$p"; fi
      if [[ "$s" == "$cand" || "$s" == "$cand"/* ]]; then printf '%s\n' "$s"; break; fi
      if [[ "$s" == */"$p" || "$s" == */"$p"/* ]]; then printf '%s\n' "$s"; break; fi
    done <<< "$specs"
  done <<< "$shadow"
}

# rd_json_array <newline_separated> — JSON array of the non-empty lines.
rd_json_array() {
  if [[ -z "$1" ]] || ! command -v jq >/dev/null 2>&1; then printf '[]'; return 0; fi
  printf '%s\n' "$1" | jq -Rn '[inputs | select(length > 0)]' 2>/dev/null || printf '[]'
}

_session_files=""
if declare -f cp_recent_files >/dev/null 2>&1 && command -v jq >/dev/null 2>&1; then
  _session_files=$(cp_recent_files "$(cp_session_key "$INPUT")" 20)
fi

_paths=$(rd_revert_pathspec "$COMMAND")
if [[ -n "$_paths" ]]; then
  REVERT_SCOPE="paths"
elif echo "$COMMAND" | grep -qE 'git[[:space:]]+(revert|reset)' 2>/dev/null; then
  REVERT_SCOPE="commit"     # no pathspec exists to intersect — see the note above
else
  REVERT_SCOPE="unknown"    # e.g. `git restore --staged` with no path
fi
# A mutation probe is recorded — dropping it would make a misclassified real
# revert vanish without a trace — but it carries no evidence: no reverted_files,
# no session_files (correction-detector.sh surfaces both as "files behind this
# correction"), and repeat stays null. revert_paths keeps the raw pathspec.
if rd_is_probe "$COMMAND"; then
  REVERT_SCOPE="probe"
  _session_files=""
fi

# The repository the command actually operated on, which is not necessarily the
# session's. `cd <other repo> && git checkout -- <path>` is the dominant real
# shape — 68 of 92 informative records on the author's machine began with it —
# and every one of those was filed under the session's project instead. That
# made `repeat` compare a file against reverts in a repository it was never in,
# so recurrence could neither be detected across sessions in the right repo nor
# be trusted when it did fire. rd_revert_base already computed the right answer
# for shadow matching; only the record kept using the wrong one.
PROJECT=$(rd_revert_base "$COMMAND" "$INPUT")

_matched=""
if [[ "$REVERT_SCOPE" == "paths" ]]; then
  _matched=$(rd_match_shadow "$PROJECT" "$_paths" "$_session_files")
fi

REVERTED_FILES_JSON=$(rd_json_array "$_matched")
SESSION_FILES_JSON=$(rd_json_array "$_session_files")
REVERT_PATHS_JSON=$(rd_json_array "$_paths")

# repeat = has any of these files already been reverted before in this project?
# (a repeated revert is a stronger signal than a one-off — surfaced as data for
# auto-audit / humans; it does NOT auto-write a rule.)
#
# Only meaningful when the command named paths. `null` — not `false` — when it did
# not: false would assert "checked, no recurrence", which this hook cannot know for
# a commit-scoped revert. Pre-2026-09 records already carry null, so readers of
# history.jsonl already tolerate it.
REPEAT=null
if [[ "$REVERT_SCOPE" == "paths" ]]; then
  REPEAT=false
  if [[ "$REVERTED_FILES_JSON" != "[]" ]] && [[ -f "$HISTORY_FILE" ]] && command -v jq >/dev/null 2>&1; then
    if tail -n 500 "$HISTORY_FILE" 2>/dev/null | jq -es \
         --argjson now "$REVERTED_FILES_JSON" --arg proj "$PROJECT" '
           [ .[] | select(.type=="implicit-revert" and .project==$proj)
                 | (.reverted_files // [])[] ] as $past
           | any($past[]; ($now | index(.)) != null)
         ' >/dev/null 2>&1; then
      REPEAT=true
    fi
  fi
fi

# jq filter, not a shell string — the $-names are jq variables bound by the
# --arg/--argjson flags below.
# shellcheck disable=SC2016
RECORD='{timestamp:$ts, prompt:$prompt, project:$project, type:$type,
         reverted_files:$files, session_files:$session, revert_scope:$scope,
         revert_paths:$paths, repeat:$repeat}'

if declare -f cp_append_history >/dev/null 2>&1; then
  cp_append_history "$HISTORY_FILE" \
    --arg ts "$TIMESTAMP" \
    --arg prompt "$(cp_bound_prompt "$RAW_COMMAND")" \
    --arg project "$PROJECT" \
    --arg type "implicit-revert" \
    --argjson files "$REVERTED_FILES_JSON" \
    --argjson session "$SESSION_FILES_JSON" \
    --arg scope "$REVERT_SCOPE" \
    --argjson paths "$REVERT_PATHS_JSON" \
    --argjson repeat "$REPEAT" \
    "$RECORD"
else
  jq -nc \
    --arg ts "$TIMESTAMP" \
    --arg prompt "$RAW_COMMAND" \
    --arg project "$PROJECT" \
    --arg type "implicit-revert" \
    --argjson files "$REVERTED_FILES_JSON" \
    --argjson session "$SESSION_FILES_JSON" \
    --arg scope "$REVERT_SCOPE" \
    --argjson paths "$REVERT_PATHS_JSON" \
    --argjson repeat "$REPEAT" \
    "$RECORD" \
    >> "$HISTORY_FILE" 2>/dev/null
fi

exit 0
