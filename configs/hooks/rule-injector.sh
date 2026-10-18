#!/usr/bin/env bash
# rule-injector.sh — PostToolUse hook (matchers: Edit|Write AND Bash)
#
# Path-scoped rule injection: rules that only matter for certain files live in
# rule files instead of CLAUDE.md, and get injected into context only when the
# agent actually touches a matching file. Keeps base context lean as the
# learned-rule corpus grows.
#
# Which files count as "touched":
#   Edit|Write  .tool_input.file_path, as before.
#   Bash        when file_path is empty: path-like tokens of .tool_input.command
#               that exist as regular files AFTER the command ran (this is
#               PostToolUse, so `sed -i`, `cat > f <<EOF` and `cat f` all count).
#               Measured 2026-10-18 over the author's 40 latest sessions
#               (approximate regex counts): 6,890 Bash reads through
#               cat/head/tail/sed -n against 484 Read calls, and 2,738 Bash
#               writes against 373 Edit/Write — an Edit|Write-only hook missed
#               most file access. Tokens are only ever tested with [ -f ] / [ -d ]
#               and regex-matched: no eval, no expansion. A token carrying a glob
#               metacharacter (* ? [ ] { }) or a `$` is skipped, because what the
#               shell expanded it to is unknowable without expanding it.
#               Path-like = contains '/' or ends in a `.ext`, so a bare
#               `Makefile` is only seen as `./Makefile`. Bounds: the first 400
#               unique path-like tokens are examined, and at most 40 existing
#               files are matched.
#   Where a relative token resolves: against the hook input's .cwd (fallback
#               $CLAUDE_PROJECT_DIR), moved by a literal `cd DIR` / `pushd DIR`
#               that starts a segment of the same command. The .cwd alone is not
#               enough: in the author's 40 latest transcripts (2026-10-18),
#               2,033 of 5,083 read-shaped Bash calls began with `cd X &&` or
#               `cd X;`, and after 1,744 of 1,785 absolute cds to another dir the
#               transcript's recorded cwd stayed at the pre-cd dir (that is the
#               transcript field; no live hook payload was logged). An absolute
#               cd target is taken as is; a relative one only when it exists as
#               a directory under the current base (otherwise .cwd already
#               followed that cd, as it does for an in-project cd). A target
#               that is `-`, or carries `$` or a glob, makes the base unknown,
#               and relative tokens after it are skipped. `~/` resolves against
#               $HOME. Known imprecision: a cd inside `( … )` is not undone at
#               the `)`.
#
# Sources (in this order):
#   $PROJECT/.claude/rules/*.md        globs relative to $PROJECT
#   <dir>/.claude/rules/*.md           NESTED: every dir between a touched
#                                      file and $PROJECT (exclusive) that holds
#                                      .claude/rules; globs relative to <dir>,
#                                      and only files under <dir> can match —
#                                      the semantics Claude Code itself gives
#                                      apps/<app>/.claude/rules (observed
#                                      2026-10-18), so a session started at a
#                                      monorepo root still gets an app's rules.
#                                      Never inside a third-party tree
#                                      (node_modules, vendor, third_party,
#                                      site-packages, .git): a Bash token can
#                                      merely MENTION a path, and a package's
#                                      own rules are not this project's.
#   ~/.claude/rules/*.md               globs relative to $PROJECT
# Unreadable rule files are skipped. Any rule file whose absolute path matches
# a `claudeMdExcludes` glob (user, project, local and managed settings, merged —
# the setting Claude Code applies to rules files) is skipped too.
#
# Rule file format (YAML frontmatter + markdown body):
#   ---
#   paths: orchestrator/**/*.py, tests/*.py
#   ---
#   Rule body — injected when a touched file matches one of the globs.
#
# `paths:` accepts a comma-separated line or a YAML list (`- glob` lines).
# Glob semantics (gitignore-style):
#   - pattern containing '/' → matched against the path relative to the base
#   - pattern without '/'   → matched against the basename (*.css = any css)
#   - '**' crosses directories; '*' and '?' do not match '/'
# Files without a `paths:` frontmatter key are ignored (not path-scoped).
# Each rule file's globs are compiled ONCE per invocation into two combined
# EREs (slash patterns, basename patterns) by a single awk pass over every
# rule file — not once per token, which is what keeps 30 rule files × 15 globs
# × 40 files inside the 5 s hook timeout.
#
# Size: Claude Code caps a hook's additionalContext at 10,000 characters. Over
# that it saves the text to a file, shows Claude a 2,000-character preview, and
# does not ask Claude to read the rest (code.claude.com/docs/en/hooks). One
# Bash command can match many rules, so entries stop at CTX_BUDGET bytes (bytes
# >= UTF-16 units, so the bound is safe); a matched rule that does not fit is
# NOT recorded as delivered — the output names it, and it injects on the next
# matching access.
#
# Dedup: each rule file is injected at most once per session per agent:
#   $PROJECT/.claude/sessions/<session_id>.rules-injected               (main)
#   $PROJECT/.claude/sessions/<session_id>.agent-<agent_id>.rules-injected
# Subagents carry the parent's session_id, so a session-only key meant that
# after the first injection no subagent could receive the rule. agent_id is
# present only when the hook fires inside a subagent (Claude Code 2.1.283
# hook-input docs), so the main thread's sentinel name is unchanged. Both ids
# are reduced to [A-Za-z0-9_-] before they become part of a filename. The
# sentinel also holds a `#<cksum> <size>` line per delivered body, so the same
# TEXT is not injected twice — a worktree's checked-out copy of a root rule, or
# one rule both global and project.
# Same dir + lifecycle as session-baseline.sh's *.baseline files.
#
# Output: hookSpecificOutput.additionalContext with the matching rule bodies.
# Silent (no output, exit 0) when nothing matches — failure paths included.
#
# Portability: bash 3.2 + BSD userland (no declare -A, mapfile, ${v,,}).

set -u

command -v jq &>/dev/null || exit 0

INPUT=""
if [ ! -t 0 ]; then
  INPUT=$(cat 2>/dev/null || true)
fi
[ -z "$INPUT" ] && exit 0

MAX_FILES=40      # existing files matched per invocation
MAX_TOKENS=400    # unique path-like tokens (and cd moves) examined per command
CTX_BUDGET=8400   # bytes of rule entries per call (the cap is 10,000 chars)
NOTE_MAX=400      # bytes of rule names listed in the held-back note
NL='
'
TAB=$(printf '\t')

# ─── Hook input ──────────────────────────────────────────────────────
# One jq call. Fields are NUL-separated so a multi-line command (a heredoc)
# survives intact; `read -d ''` splits on NUL in bash 3.2 too. A NUL INSIDE a
# field becomes a space first — otherwise "\u0000" in the command shifts every
# later field and the command text chooses the session id.
FILE_PATH="" COMMAND="" SESSION_ID="" HOOK_CWD="" AGENT_ID=""
{
  IFS= read -r -d '' FILE_PATH
  IFS= read -r -d '' COMMAND
  IFS= read -r -d '' SESSION_ID
  IFS= read -r -d '' HOOK_CWD
  IFS= read -r -d '' AGENT_ID
} < <(printf '%s' "$INPUT" | jq -j '
  [ .tool_input.file_path, .tool_input.command, .session_id, .cwd, .agent_id ]
  | map((. // "" | tostring | split("\u0000") | join(" ")) + "\u0000") | add' 2>/dev/null)

[ -z "$FILE_PATH" ] && [ -z "$COMMAND" ] && exit 0

# Both ids become part of a filename: never a path.
SESSION_ID="${SESSION_ID//[^A-Za-z0-9_-]/_}"

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
[ "$PROJECT_DIR" != "/" ] && PROJECT_DIR="${PROJECT_DIR%/}"
REL_BASE="${HOOK_CWD:-$PROJECT_DIR}"
[ "$REL_BASE" != "/" ] && REL_BASE="${REL_BASE%/}"

# ─── Path helpers ────────────────────────────────────────────────────
# Lexically collapse '.', '..' and '//' in an absolute path. Sets NORM.
# Pure bash: no subshell per token.
normalize_path() {
  NORM="$1"
  case "$NORM" in
    */./*|*/../*|*/.|*/..|*//*) ;;
    *) return 0 ;;
  esac
  local oldifs="$IFS" seg n=0 out="" i=0
  local -a parts stack
  IFS=/
  set -f
  # shellcheck disable=SC2206  # deliberate split on IFS=/ with globbing off
  parts=($NORM)
  set +f
  IFS="$oldifs"
  stack=()
  for seg in "${parts[@]}"; do
    case "$seg" in
      ''|.) continue ;;
      ..) [ "$n" -gt 0 ] && n=$((n - 1)); continue ;;
    esac
    stack[n]="$seg"
    n=$((n + 1))
  done
  while [ "$i" -lt "$n" ]; do out="$out/${stack[$i]}"; i=$((i + 1)); done
  NORM="${out:-/}"
}

# Resolve a token to an absolute, normalized path. Relative tokens resolve
# against BASE ("" = unknown, after an unresolvable cd). Sets NORM; returns 1
# when the token cannot be resolved.
BASE="$REL_BASE"
resolve_token() {
  # shellcheck disable=SC2088  # a literal "~/" prefix, matched not expanded
  case "$1" in
    /*) normalize_path "$1" ;;
    "~/"*) [ -n "${HOME:-}" ] || return 1; normalize_path "$HOME/${1#"~/"}" ;;
    *) [ -n "$BASE" ] || return 1; normalize_path "$BASE/$1" ;;
  esac
}

# A `cd DIR` that starts a segment moves BASE for the tokens after it.
set_cd_base() {
  case "$1" in
    ""|"~") BASE="${HOME:-}"; return 0 ;;
    -|*[][*?{}]*|*\$*) BASE=""; return 0 ;;
  esac
  resolve_token "$1" || { BASE=""; return 0; }
  # shellcheck disable=SC2088  # a literal "~/" prefix, matched not expanded
  case "$1" in
    /*|"~/"*) BASE="$NORM" ;;
    *) [ -d "$NORM" ] && BASE="$NORM" ;;   # else .cwd already followed this cd
  esac
  return 0
}

# Display form of a path: project-relative, ~/-relative, or absolute.
display_path() {
  # shellcheck disable=SC2088  # "~/" is display text, not a path to expand
  case "$1" in
    "$PROJECT_DIR"/*) DISP="${1#"$PROJECT_DIR"/}" ;;
    "${HOME:-/nonexistent}"/*) DISP="~/${1#"${HOME:-}"/}" ;;
    *) DISP="$1" ;;
  esac
}

# Byte length of $1 (a UTF-8 byte count is >= its UTF-16 length). Sets BLEN.
blen() { local LC_ALL=C; BLEN=${#1}; }

# ─── Candidate files ─────────────────────────────────────────────────
CANDS=()       # absolute, normalized
CAND_REL=()    # project-relative (absolute when outside the project)
NCANDS=0
CAND_SEEN="$NL"

add_candidate() {
  case "$CAND_SEEN" in *"$NL$1$NL"*) return 0 ;; esac
  CAND_SEEN="$CAND_SEEN$1$NL"
  CANDS[NCANDS]="$1"
  case "$1" in
    "$PROJECT_DIR"/*) CAND_REL[NCANDS]="${1#"$PROJECT_DIR"/}" ;;
    *) CAND_REL[NCANDS]="$1" ;;
  esac
  NCANDS=$((NCANDS + 1))
}

# Split each line into segments on ; | & ( ) and each segment on whitespace and
# the remaining shell punctuation. A segment that starts with cd/pushd prints
# "cd<TAB>target" (a token can never hold a TAB, so the line is unambiguous).
# Otherwise print path-like tokens with no glob metacharacter and no unexpanded
# variable, deduped per cd position, at most MAX_TOKENS lines in all.
command_tokens() {
  printf '%s\n' "$COMMAND" | awk -v max="$MAX_TOKENS" \
    -v sep="[ $TAB<>\`\"'=,]+" '
    {
      ns = split($0, seg, "[;|&()]+")
      for (s = 1; s <= ns; s++) {
        n = split(seg[s], t, sep)
        k = 1
        while (k <= n && t[k] == "") k++
        if (k <= n && (t[k] == "cd" || t[k] == "pushd")) {
          k++
          while (k <= n && (t[k] == "" || t[k] ~ /^-./)) k++
          print "cd\t" (k <= n ? t[k] : "")
          cdn++
          if (++c >= max) exit
          continue
        }
        for (i = 1; i <= n; i++) {
          w = t[i]
          if (w == "" || substr(w, 1, 1) == "-") continue
          if (index(w, "*") || index(w, "?") || index(w, "[") || index(w, "]") || index(w, "{") || index(w, "}")) continue
          if (index(w, "$")) continue
          if (!index(w, "/") && w !~ /\.[A-Za-z0-9_+-]+$/) continue
          if ((cdn, w) in seen) continue
          seen[cdn, w] = 1
          print w
          if (++c >= max) exit
        }
      }
    }'
}

if [ -n "$FILE_PATH" ]; then
  # Edit|Write: the tool names the file; no existence filter (unchanged).
  resolve_token "$FILE_PATH" && add_candidate "$NORM"
else
  while IFS= read -r tok; do
    case "$tok" in
      "cd$TAB"*) set_cd_base "${tok#"cd$TAB"}"; continue ;;
    esac
    resolve_token "$tok" || continue
    [ -f "$NORM" ] || continue
    add_candidate "$NORM"
    [ "$NCANDS" -ge "$MAX_FILES" ] && break
  done < <(command_tokens)
fi

[ "$NCANDS" -eq 0 ] && exit 0

# ─── Sentinel (once per session, per agent) ──────────────────────────
SESS_DIR="$PROJECT_DIR/.claude/sessions"
SENT_KEY="${SESSION_ID:-nosession}"
if [ -n "$AGENT_ID" ]; then
  SENT_KEY="$SENT_KEY.agent-${AGENT_ID//[^A-Za-z0-9_-]/_}"
fi
SENT_FILE="$SESS_DIR/$SENT_KEY.rules-injected"
SENT="$NL"
[ -f "$SENT_FILE" ] && SENT="$NL$(cat "$SENT_FILE" 2>/dev/null)$NL"

# ─── Rule directories ────────────────────────────────────────────────
PROJECT_RULES="$PROJECT_DIR/.claude/rules"
GLOBAL_RULES=""
[ -n "${HOME:-}" ] && GLOBAL_RULES="$HOME/.claude/rules"
[ "$GLOBAL_RULES" = "$PROJECT_RULES" ] && GLOBAL_RULES=""

RULE_DIRS=("$PROJECT_RULES")
NDIRS=1
DIR_SEEN="$NL$PROJECT_RULES$NL${GLOBAL_RULES:+$GLOBAL_RULES$NL}"

# A third-party tree under the project: its rules are the package's, not ours.
is_vendored() {
  case "/${1#"$PROJECT_DIR"/}/" in
    */node_modules/*|*/vendor/*|*/third_party/*|*/site-packages/*|*/.git/*) return 0 ;;
  esac
  return 1
}

# Nested: walk from each candidate's directory up to $PROJECT_DIR (exclusive).
i=0
while [ "$i" -lt "$NCANDS" ]; do
  d="${CANDS[$i]%/*}"
  while :; do
    case "$d" in "$PROJECT_DIR"/*) : ;; *) break ;; esac
    rd="$d/.claude/rules"
    if [ -d "$rd" ] && ! is_vendored "$d"; then
      case "$DIR_SEEN" in
        *"$NL$rd$NL"*) : ;;
        *)
          DIR_SEEN="$DIR_SEEN$rd$NL"
          RULE_DIRS[NDIRS]="$rd"
          NDIRS=$((NDIRS + 1))
          ;;
      esac
    fi
    d="${d%/*}"
  done
  i=$((i + 1))
done

if [ -n "$GLOBAL_RULES" ]; then
  RULE_DIRS[NDIRS]="$GLOBAL_RULES"
  NDIRS=$((NDIRS + 1))
fi

# Rule files not yet injected for this session/agent, in source order. One awk
# reads them all, and mawk and BSD awk stop at the first file they cannot open,
# so an unreadable file is dropped here rather than silencing every rule.
RULE_FILES=()
NRULES=0
i=0
while [ "$i" -lt "$NDIRS" ]; do
  dir="${RULE_DIRS[$i]}"
  i=$((i + 1))
  [ -d "$dir" ] || continue
  for f in "$dir"/*.md; do
    [ -f "$f" ] && [ -r "$f" ] || continue
    case "$SENT" in *"$NL$f$NL"*) continue ;; esac
    RULE_FILES[NRULES]="$f"
    NRULES=$((NRULES + 1))
  done
done
[ "$NRULES" -eq 0 ] && exit 0

# claudeMdExcludes: absolute-path globs, merged across settings layers. A
# settings file that never names the key costs a grep, not a jq.
EXCLUDES=""
for s in "${HOME:-/nonexistent}/.claude/settings.json" \
         "$PROJECT_DIR/.claude/settings.json" \
         "$PROJECT_DIR/.claude/settings.local.json" \
         /etc/claude-code/managed-settings.json \
         "/Library/Application Support/ClaudeCode/managed-settings.json"; do
  [ -f "$s" ] && [ -r "$s" ] || continue
  grep -q claudeMdExcludes "$s" 2>/dev/null || continue
  EXCLUDES="$EXCLUDES$(jq -r '.claudeMdExcludes[]? | strings' "$s" 2>/dev/null)$NL"
done

# ─── Compile: frontmatter globs → combined EREs, one awk pass ────────
# Per rule file with a CLOSED frontmatter and a non-empty `paths:`, and whose
# path no claudeMdExcludes glob matches, prints
#   <file> US <slash-ERE> US <basename-ERE>
# where each ERE is an alternation of anchored per-glob EREs (either may be
# empty). Glob → ERE: '**/' → '(.*/)?'   '**' → '.*'   '*' → '[^/]*'
# '?' → '[^/]'; everything else regex-escaped. Same semantics as before.
US=$(printf '\037')
compile_rules() {
  RI_EXCLUDES="$EXCLUDES" awk -v us="$US" -v q="'" '
    function g2e(g,   out, i, n, c) {
      out = ""; n = length(g); i = 1
      while (i <= n) {
        c = substr(g, i, 1)
        if (c == "*") {
          if (substr(g, i, 3) == "**/") { out = out "(.*/)?"; i += 3; continue }
          if (substr(g, i, 2) == "**") { out = out ".*"; i += 2; continue }
          out = out "[^/]*"
        } else if (c == "?") {
          out = out "[^/]"
        } else if (index(".+()[]{}^$|\\", c)) {
          out = out "\\" c
        } else {
          out = out c
        }
        i++
      }
      return "^" out "$"
    }
    function addglob(v,   e) {
      sub(/^[[:space:]]+/, "", v); sub(/[[:space:]]+$/, "", v)
      sub(/^"/, "", v); sub(/"$/, "", v)
      if (substr(v, 1, 1) == q) v = substr(v, 2)
      if (substr(v, length(v), 1) == q) v = substr(v, 1, length(v) - 1)
      if (v == "") return
      e = "(" g2e(v) ")"
      if (index(v, "/")) sl = (sl == "" ? e : sl "|" e)
      else bs = (bs == "" ? e : bs "|" e)
    }
    function flush() {
      if (cur != "" && state == 2 && (sl != "" || bs != "") && !(ex != "" && cur ~ ex)) print cur us sl us bs
      sl = ""; bs = ""; cur = ""; state = 0; inlist = 0
    }
    BEGIN {
      ex = ""
      ne = split(ENVIRON["RI_EXCLUDES"], xs, "\n")
      for (j = 1; j <= ne; j++) {
        v = xs[j]; sub(/^[[:space:]]+/, "", v); sub(/[[:space:]]+$/, "", v)
        if (v != "") ex = (ex == "" ? "" : ex "|") "(" g2e(v) ")"
      }
    }
    FNR == 1 {
      flush(); cur = FILENAME
      if ($0 ~ /^---[[:space:]]*$/) state = 1
      next
    }
    state != 1 { next }
    /^---[[:space:]]*$/ { state = 2; next }
    /^paths:/ {
      val = $0; sub(/^paths:[[:space:]]*/, "", val)
      if (val != "") { n = split(val, parts, ","); for (j = 1; j <= n; j++) addglob(parts[j]) }
      else inlist = 1
      next
    }
    inlist && /^[[:space:]]*-[[:space:]]*/ {
      val = $0; sub(/^[[:space:]]*-[[:space:]]*/, "", val); addglob(val); next
    }
    inlist { inlist = 0 }
    END { flush() }
  ' "${RULE_FILES[@]}" 2>/dev/null
}

# Print the body (everything after the closing '---').
extract_body() {
  awk '
    NR == 1 { if ($0 ~ /^---[[:space:]]*$/) { infm = 1; next } else exit }
    infm && /^---[[:space:]]*$/ { infm = 0; body = 1; next }
    body { print }
  ' "$1"
}

# ─── Match + collect ─────────────────────────────────────────────────
CONTEXT=""
CTX_BYTES=0
INJECTED_FILES=""   # sentinel lines: rule paths and #<cksum> body keys
CALL_KEYS="$NL"
HELD=""             # rules matched but held back for the size cap
NHELD=0

while IFS="$US" read -r f slash_ere base_ere; do
  [ -n "$f" ] || continue
  rdir="${f%/*}"
  if [ "$rdir" = "$PROJECT_RULES" ]; then
    scope="project"; base=""
  elif [ -n "$GLOBAL_RULES" ] && [ "$rdir" = "$GLOBAL_RULES" ]; then
    scope="global"; base=""
  else
    base="${rdir%/.claude/rules}"
    scope="nested: ${base#"$PROJECT_DIR"/}"
  fi

  hit=""
  i=0
  while [ "$i" -lt "$NCANDS" ]; do
    c="${CANDS[$i]}"
    if [ -n "$base" ]; then
      # Nested dir: only files under it, globs relative to it.
      case "$c" in "$base"/*) rel="${c#"$base"/}" ;; *) i=$((i + 1)); continue ;; esac
    else
      rel="${CAND_REL[$i]}"
    fi
    if [ -n "$slash_ere" ] && [[ "$rel" =~ $slash_ere ]]; then hit="${CAND_REL[$i]}"; break; fi
    if [ -n "$base_ere" ] && [[ "${c##*/}" =~ $base_ere ]]; then hit="${CAND_REL[$i]}"; break; fi
    i=$((i + 1))
  done
  [ -z "$hit" ] && continue

  body=$(extract_body "$f" | head -c 4000)
  [ -z "$body" ] && continue

  # The same text already reached this context (earlier, or from another copy
  # this call): record the file as delivered, inject nothing.
  key="#$(printf '%s' "$body" | cksum)"
  case "$SENT$CALL_KEYS" in
    *"$NL$key$NL"*) INJECTED_FILES="$INJECTED_FILES$f$NL"; continue ;;
  esac

  entry="[path-scoped rule: ${f##*/} ($scope) — matched $hit]
$body

"
  blen "$entry"
  if [ -n "$CONTEXT" ] && [ $((CTX_BYTES + BLEN)) -gt "$CTX_BUDGET" ]; then
    display_path "$f"
    HELD="${HELD:+$HELD, }$DISP"
    NHELD=$((NHELD + 1))
    continue
  fi
  CONTEXT="$CONTEXT$entry"
  CTX_BYTES=$((CTX_BYTES + BLEN))
  INJECTED_FILES="$INJECTED_FILES$f$NL$key$NL"
  CALL_KEYS="$CALL_KEYS$key$NL"
done < <(compile_rules)

[ -z "$INJECTED_FILES" ] && exit 0

# Record sentinels before emitting (re-running after a failed emit re-injects,
# which is the safe direction). Held-back rules are not recorded.
mkdir -p "$SESS_DIR" 2>/dev/null || true
printf '%s' "$INJECTED_FILES" 2>/dev/null >> "$SENT_FILE" || true
# Cleanup: sentinels older than 7 days (mirrors session-baseline.sh policy)
find "$SESS_DIR" -maxdepth 1 -type f -name '*.rules-injected' -mtime +7 -delete 2>/dev/null || true

[ -z "$CONTEXT" ] && exit 0

if [ "$NHELD" -gt 0 ]; then
  blen "$HELD"
  [ "$BLEN" -gt "$NOTE_MAX" ] && HELD="$(printf '%s' "$HELD" | head -c "$NOTE_MAX")…"
  CONTEXT="${CONTEXT}[path-scoped rules held back: $NHELD more matched ($HELD). They were left out to keep this under Claude Code's 10,000-character hook-context limit, and each one injects on the next matching file access; read one now if it bears on this step.]
"
fi

jq -n --arg ctx "$CONTEXT" \
  '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":$ctx}}'

exit 0
