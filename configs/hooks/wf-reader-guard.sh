#!/usr/bin/env bash
# wf-reader-guard.sh — make the wf-reader agent's Bash read-only, by control
#
# Triggered: PreToolUse (matcher: Bash), wired ONLY in the `hooks:` frontmatter
#            of configs/agents/wf-reader.md — never in settings-hooks.json.
# Purpose:   wf-reader's body says "read, never change", and until this hook
#            that was an instruction and nothing more: under a
#            bypassPermissions parent its Bash ran anything, and Claude Code
#            2.1.283 ignores a frontmatter `permissionMode` under a bypass,
#            acceptEdits or auto parent. This hook DENIES every Bash call that
#            is not on a short read allowlist.
#
# Output — Claude Code's PreToolUse schema:
#   deny   {"hookSpecificOutput":{"hookEventName":"PreToolUse",
#            "permissionDecision":"deny","permissionDecisionReason":"..."}}
#   allow  exit 0 with no output. Never "allow": that would also skip the
#          permission prompts and deny rules a read still owes.
#
# Scope, verified in the 2.1.283 binary (2026-10-23):
#   - an agent file's frontmatter `hooks:` is parsed for agents under
#     ~/.claude/agents (source userSettings) and registered for THAT agent's
#     session only, so the hook needs no agent_type test and has none: it
#     guards whatever session wires it, and nothing else.
#   - a PreToolUse/PermissionRequest entry that fails to load keeps the whole
#     agent from loading ("nothing it sits in is applied"), so a broken wiring
#     removes wf-reader instead of leaving it unguarded.
#   - a PLUGIN agent's `hooks:` is ignored ("sets hooks, which is ignored for
#     plugin agents"). The plugin mirror agents/wf-reader.md, spawned as
#     clade:wf-reader, is therefore NOT guarded; only `agentType: "wf-reader"`
#     is.
#   - NOT enforced where the runtime skips session hooks, and wf-reader still
#     loads there with an unrestricted Bash: `disableAllHooks: true` in any
#     settings source (user, project or local settings — so a repository can
#     ship it — or managed policy), or `allowManagedHooksOnly` in managed
#     policy. The hook lookup then returns settings hooks only (Y$/vhe). A
#     managed `strictPluginOnlyCustomization` covering hooks skips the
#     registration itself. Nothing here can detect either case: this file is
#     what does not run.
#   - a hook that exits non-zero with any code but 2 is a non-blocking error
#     and the call RUNS. The frontmatter therefore runs this file as
#     `bash <path> || exit 2`: a missing file, a missing bash or a crash here
#     becomes a deny.
#
# Allowed, each segment of a `|`, `&&`, `||`, `;` or newline chain:
#   cat head tail ls wc cut tr stat jq diff echo pwd cd — any arguments
#   grep, without ugrep's --filter, --pager, --view and --save-config
#   sed -n with print-only scripts (N,Mp  $p  Nq  =)    never -i, w, e, r
#   rg, find, sort, uniq, file — without their write/exec options (below)
#   git log|show|diff|status|rev-parse|ls-files|grep|blame|cat-file,
#   git branch --list, git tag --list, git remote -v — after at most
#   `--no-pager` and `-C <dir>`
#   redirection: output only to /dev/null, fd duplication (2>&1), input (<)
#   from anything but bash's /dev/tcp and /dev/udp sockets
# Denied: everything else, and in particular command substitution (`$(…)`,
# backticks), any $-expansion or $'…' quoting, subshells, groups, process
# substitution, here-documents, background jobs, comments, VAR=value prefixes,
# and every interpreter (python, node, perl, ruby, awk, sh, bash).
#
# Options that turn a reader into a writer or a launcher — each one real:
#   sed     the w, W, e and r commands, s///w and s///e live in the SCRIPT,
#           not the flags, so only line-number print scripts pass
#   sort    -o/--output writes, and GNU accepts --ou= as --output (measured);
#           --compress-program runs a program
#   uniq    a second file name is the OUTPUT file
#   find    -delete -exec -execdir -ok -okdir -fprint -fprint0 -fprintf -fls,
#           and -rm: the native build shadows find with an embedded bfs,
#           where -rm is -delete
#   rg      --pre runs a program per file; --hostname-bin runs one
#   git     grep -O/--open-files-in-pager runs a program, and `git grep
#           --open=cat` is accepted as an abbreviation (measured, git 2.43);
#           log/show/diff --output writes; -c and --exec-path before the
#           subcommand run configured programs; branch/tag mutate unless listing
#   file    -C/--compile writes magic.mgc
# An unquoted glob or brace in those commands' arguments is denied too: a file
# named `-i`, `-delete` or `--pre=x` in the directory would otherwise be
# expanded into an option the checks above never saw. grep keeps its globs
# (`grep -n x *.py` is the everyday read): only ugrep has options to inject,
# and the native build's grep wrapper sends those to GNU grep after expansion.
#
# No `set -e`: a test that comes out false inside a check is a verdict, not an
# error, and must not end the script early. A real crash still fails closed
# through the frontmatter's `|| exit 2`; everything this file does not
# recognise ends in wr_deny, never in a silent pass.

set -uo pipefail
export LC_ALL=C

WR_MAX_LEN=8192
WR_ALLOWED="cat head tail grep ls wc cut tr stat jq diff echo pwd cd, sed -n 'N,Mp', rg, find, sort, uniq, file, git log|show|diff|status|rev-parse|ls-files|grep|blame|cat-file, git branch --list, git tag --list, git remote -v; joined by | && || ; with output redirected only to /dev/null"

# ─── Output ───────────────────────────────────────────────────────────
# wr_deny <why> — refuse the call with one line of reason, then stop.
# Built with printf, not jq, so a missing jq still produces a valid deny.
wr_deny() {
  local msg="wf-reader is read-only: $1. Use the Read tool (or Grep/Glob where listed), or Bash limited to: $WR_ALLOWED."
  msg="${msg//\\/\\\\}"
  msg="${msg//\"/\\\"}"
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}\n' "$msg"
  exit 0
}

# wr_show <word> — a word quoted into a reason: printable and short.
wr_show() {
  local w="$1" out="" c i
  for (( i = 0; i < ${#w} && i < 40; i++ )); do
    c="${w:i:1}"
    case "$c" in
      [A-Za-z0-9._/=:,+@%~*{}-]|'['|']') out+="$c" ;;
      *) out+="?" ;;
    esac
  done
  printf '%s' "$out"
}

# ─── Hook input ───────────────────────────────────────────────────────
IFS= read -r -d '' INPUT || true

command -v jq >/dev/null 2>&1 || wr_deny "the guard reads the call with jq, and jq is not installed"

TOOL_NAME=$(printf '%s' "$INPUT" | jq -r 'if type == "object" then (.tool_name // "") else error("not an object") end' 2>/dev/null) \
  || wr_deny "the hook input could not be read"
# The matcher is Bash; the other tools wf-reader holds are read-only by nature.
[[ -n "$TOOL_NAME" && "$TOOL_NAME" != "Bash" ]] && exit 0
[[ "$TOOL_NAME" == "Bash" ]] || wr_deny "the hook input names no tool"

# A control character other than tab and newline (a CR, a NUL) is a byte the
# tokenizer below would read differently from bash.
CMD_STATE=$(printf '%s' "$INPUT" | jq -r '
  .tool_input.command as $c
  | if ($c | type) != "string" then "missing"
    elif ($c | explode | any((. < 32 and . != 9 and . != 10) or . == 127)) then "control"
    else "ok" end' 2>/dev/null) || wr_deny "the hook input could not be read"
case "$CMD_STATE" in
  ok) ;;
  control) wr_deny "the command contains a control character" ;;
  *) wr_deny "the call carries no command string" ;;
esac
COMMAND=$(printf '%s' "$INPUT" | jq -j '.tool_input.command' 2>/dev/null) \
  || wr_deny "the hook input could not be read"

(( ${#COMMAND} <= WR_MAX_LEN )) || wr_deny "the command is longer than $WR_MAX_LEN characters"

# ─── Tokenizer ────────────────────────────────────────────────────────
# Splits COMMAND the way bash would into words (quotes removed), separators
# (| && || ;) and redirections. It knows only what a read needs; anything
# else denies. Parallel arrays, because bash 3.2 has no associative ones:
#   T_KIND  w (word) | op (separator) | r (redirection operator)
#   T_VAL   the word with its quoting removed, or the operator
#   T_GLOB  1 when the word holds an unquoted * ? [ or {
T_KIND=(); T_VAL=(); T_GLOB=()
w_text=""; w_open=0; w_glob=0; w_quoted=0

wr_emit() { T_KIND+=("$1"); T_VAL+=("$2"); T_GLOB+=("${3:-0}"); }
wr_flush() {
  if (( w_open )); then wr_emit w "$w_text" "$w_glob"; fi
  w_text=""; w_open=0; w_glob=0; w_quoted=0
}

wr_tokenize() {
  local s="$1" n=${#1} i=0 c nx rest q
  while (( i < n )); do
    c="${s:i:1}"
    case "$c" in
      "'")
        rest="${s:i+1}"
        [[ "$rest" == *"'"* ]] || wr_deny "an unterminated single quote"
        q="${rest%%"'"*}"
        w_text+="$q"; w_open=1; w_quoted=1
        i=$(( i + ${#q} + 2 )) ;;
      '"')
        w_open=1; w_quoted=1; i=$(( i + 1 ))
        while :; do
          (( i < n )) || wr_deny "an unterminated double quote"
          c="${s:i:1}"
          case "$c" in
            '"') i=$(( i + 1 )); break ;;
            '\')
              nx="${s:i+1:1}"
              case "$nx" in
                '$'|'`'|'"'|'\') w_text+="$nx"; i=$(( i + 2 )) ;;
                $'\n') i=$(( i + 2 )) ;;
                *) w_text+='\'; i=$(( i + 1 )) ;;
              esac ;;
            '`') wr_deny "command substitution" ;;
            '$')
              nx="${s:i+1:1}"
              case "$nx" in
                '"'|' '|$'\t'|$'\n') w_text+='$'; i=$(( i + 1 )) ;;
                *) wr_deny "a \$ expansion inside double quotes (variables and \$(...) are not allowed)" ;;
              esac ;;
            *) w_text+="$c"; i=$(( i + 1 )) ;;
          esac
        done ;;
      ' '|$'\t') wr_flush; i=$(( i + 1 )) ;;
      $'\n') wr_flush; wr_emit op ';'; i=$(( i + 1 )) ;;
      '\')
        nx="${s:i+1:1}"
        if [[ -z "$nx" ]]; then wr_deny "a trailing backslash"; fi
        if [[ "$nx" == $'\n' ]]; then i=$(( i + 2 )); continue; fi
        w_text+="$nx"; w_open=1; w_quoted=1; i=$(( i + 2 )) ;;
      '`') wr_deny "command substitution" ;;
      '$')
        nx="${s:i+1:1}"
        case "$nx" in
          ''|' '|$'\t'|$'\n') w_text+='$'; w_open=1; i=$(( i + 1 )) ;;
          *) wr_deny "a \$ expansion (variables, \$(...), \$'...' and \${...} are not allowed)" ;;
        esac ;;
      '|')
        wr_flush
        case "${s:i+1:1}" in
          '|') wr_emit op '||'; i=$(( i + 2 )) ;;
          '&') wr_deny "the |& pipe" ;;
          *) wr_emit op '|'; i=$(( i + 1 )) ;;
        esac ;;
      '&')
        wr_flush
        case "${s:i+1:1}" in
          '&') wr_emit op '&&'; i=$(( i + 2 )) ;;
          '>')
            if [[ "${s:i+2:1}" == '>' ]]; then wr_emit r '&>>'; i=$(( i + 3 ))
            else wr_emit r '&>'; i=$(( i + 2 )); fi ;;
          *) wr_deny "a background job (&)" ;;
        esac ;;
      ';')
        wr_flush
        [[ "${s:i+1:1}" == ';' ]] && wr_deny "the ;; separator"
        wr_emit op ';'; i=$(( i + 1 )) ;;
      '('|')') wr_deny "subshells, groups, arithmetic and process substitution" ;;
      '>'|'<')
        # A word of bare digits right before the operator is its fd number.
        if (( w_open && ! w_quoted )) && [[ -n "$w_text" && "$w_text" != *[!0-9]* ]]; then
          w_text=""; w_open=0; w_glob=0; w_quoted=0
        else
          wr_flush
        fi
        nx="${s:i+1:1}"
        if [[ "$c" == '>' ]]; then
          case "$nx" in
            '>') wr_emit r '>>'; i=$(( i + 2 )) ;;
            '&') wr_emit r '>&'; i=$(( i + 2 )) ;;
            '|') wr_emit r '>|'; i=$(( i + 2 )) ;;
            '(') wr_deny "process substitution" ;;
            *) wr_emit r '>'; i=$(( i + 1 )) ;;
          esac
        else
          case "$nx" in
            '<') wr_deny "here-documents and here-strings" ;;
            '>') wr_deny "the read-write redirection <>" ;;
            '&') wr_emit r '<&'; i=$(( i + 2 )) ;;
            '(') wr_deny "process substitution" ;;
            *) wr_emit r '<'; i=$(( i + 1 )) ;;
          esac
        fi ;;
      '#')
        (( w_open )) || wr_deny "a shell comment"
        w_text+='#'; i=$(( i + 1 )) ;;
      '*'|'?'|'['|'{') w_text+="$c"; w_open=1; w_glob=1; i=$(( i + 1 )) ;;
      *) w_text+="$c"; w_open=1; i=$(( i + 1 )) ;;
    esac
  done
  wr_flush
}

# ─── Per-command checks ───────────────────────────────────────────────
# The current segment's words: S_VAL[0] is the command, S_GLOB its glob flags.
S_VAL=(); S_GLOB=()

wr_no_globs() {  # <cmd> — deny an unquoted glob or brace in any argument
  local k
  for (( k = 1; k < ${#S_VAL[@]}; k++ )); do
    (( S_GLOB[k] )) && wr_deny "an unquoted glob or brace in a $1 argument ($(wr_show "${S_VAL[k]}")); quote patterns and list paths, so no file name can become an option"
  done
  return 0
}

# A sed script that only prints: commands joined by ; or newline, each an
# optional line address (N, $, N,M, N,$, N,+M) then p, or Nq, or =.
WR_SED_CMD_RE='^(([0-9]+|\$)(,([0-9]+|\$|\+[0-9]+))?)?[[:space:]]*p$|^([0-9]+|\$)?[[:space:]]*q$|^(([0-9]+|\$)(,([0-9]+|\$))?)?[[:space:]]*=$'
wr_sed_script_ok() {
  local s="${1//$'\n'/;}" part
  while :; do
    part="${s%%;*}"
    part="${part#"${part%%[![:space:]]*}"}"
    part="${part%"${part##*[![:space:]]}"}"
    if [[ -n "$part" ]] && ! [[ "$part" =~ $WR_SED_CMD_RE ]]; then
      return 1
    fi
    [[ "$s" == *';'* ]] || break
    s="${s#*;}"
  done
  return 0
}

# wr_sed_script <word> — deny unless the word is a print-only sed script.
wr_sed_script() {
  wr_sed_script_ok "$1" || wr_deny "a sed script that does more than print line ranges ($(wr_show "$1")); sed may only print, e.g. sed -n '10,40p' file"
  return 0
}

wr_check_sed() {
  wr_no_globs sed
  local k a cl saw_n=0 have_script=0 want_script=0 end_opts=0
  for (( k = 1; k < ${#S_VAL[@]}; k++ )); do
    a="${S_VAL[k]}"
    if (( want_script )); then
      wr_sed_script "$a"; have_script=1; want_script=0
      continue
    fi
    if (( end_opts )); then
      # After --, the first word is still the SCRIPT when no -e gave one:
      # `sed -n -- 'w out' f` writes out (measured, GNU sed 4.9).
      (( have_script )) || { wr_sed_script "$a"; have_script=1; }
      continue
    fi
    case "$a" in
      --) end_opts=1 ;;
      -) ;;
      -e) want_script=1 ;;
      --quiet|--silent) saw_n=1 ;;
      --regexp-extended) ;;
      --*) wr_deny "the sed option $(wr_show "$a"); sed may only print, as sed -n 'N,Mp' file" ;;
      -*)
        # A cluster of n, E and r, optionally ending in e (-ne '1p').
        cl="${a#-}"
        if [[ "$cl" == *e ]]; then cl="${cl%e}"; want_script=1; fi
        case "$cl" in
          *[!nEr]*) wr_deny "the sed option $(wr_show "$a") (only -n, -e, -E and -r; never -i)" ;;
          *n*) saw_n=1 ;;
        esac ;;
      *) (( have_script )) || { wr_sed_script "$a"; have_script=1; } ;;
    esac
  done
  (( want_script )) && wr_deny "sed -e without a script"
  (( saw_n )) || wr_deny "sed without -n"
  (( have_script )) || wr_deny "sed without a script"
  return 0
}

# grep: GNU grep has no option that writes or runs anything, but ugrep —
# installed as grep, or the ugrep the native build embeds — does: --filter
# runs a program per file, --pager and --view open one, --save-config writes.
# GNU grep rejects all four, so refusing them costs a GNU user nothing.
wr_check_grep() {
  local k
  for (( k = 1; k < ${#S_VAL[@]}; k++ )); do
    case "${S_VAL[k]}" in
      --) break ;;
      --filter|--filter=*|--pager|--pager=*|--view|--view=*|--save-config|--save-config=*)
        wr_deny "grep $(wr_show "${S_VAL[k]}"), which ugrep reads as running a program or writing a file" ;;
    esac
  done
  return 0
}

wr_check_find() {
  wr_no_globs find
  local k
  for (( k = 1; k < ${#S_VAL[@]}; k++ )); do
    case "${S_VAL[k]}" in
      -delete|-rm|-exec|-execdir|-ok|-okdir|-fprint|-fprint0|-fprintf|-fls)
        wr_deny "find ${S_VAL[k]}, which deletes, writes or runs a command" ;;
    esac
  done
  return 0
}

wr_check_rg() {
  wr_no_globs rg
  local k
  for (( k = 1; k < ${#S_VAL[@]}; k++ )); do
    case "${S_VAL[k]}" in
      --pre*|--ho*) wr_deny "rg $(wr_show "${S_VAL[k]}"), which can run a program" ;;
    esac
  done
  return 0
}

wr_check_sort() {
  wr_no_globs sort
  local k a
  for (( k = 1; k < ${#S_VAL[@]}; k++ )); do
    a="${S_VAL[k]}"
    case "$a" in
      --) break ;;
      --o*|--co*) wr_deny "sort $(wr_show "$a"), which writes a file or runs a program" ;;
      --*) ;;
      -*o*) wr_deny "sort -o, which writes a file" ;;
    esac
  done
  return 0
}

wr_check_uniq() {
  wr_no_globs uniq
  local k a files=0 end_opts=0
  for (( k = 1; k < ${#S_VAL[@]}; k++ )); do
    a="${S_VAL[k]}"
    if (( end_opts )); then files=$(( files + 1 )); continue; fi
    case "$a" in
      --) end_opts=1 ;;
      -f|-s|-w)
        # their count argument, when it is one
        if [[ -n "${S_VAL[k+1]:-}" && "${S_VAL[k+1]}" != *[!0-9]* ]]; then k=$(( k + 1 )); fi ;;
      -) files=$(( files + 1 )) ;;
      -*) ;;
      *) files=$(( files + 1 )) ;;
    esac
  done
  (( files <= 1 )) || wr_deny "uniq with two file names, which writes the second"
  return 0
}

wr_check_file() {
  wr_no_globs file
  local k a
  for (( k = 1; k < ${#S_VAL[@]}; k++ )); do
    a="${S_VAL[k]}"
    case "$a" in
      --co*) wr_deny "file --compile, which writes a file" ;;
      --*) ;;
      -*C*) wr_deny "file -C, which writes a file" ;;
    esac
  done
  return 0
}

# git: global options, then one read-only subcommand.
wr_check_git() {
  wr_no_globs git
  local k=1 a sub n=${#S_VAL[@]}
  while (( k < n )); do
    a="${S_VAL[k]}"
    case "$a" in
      --no-pager) k=$(( k + 1 )) ;;
      -C) (( k + 1 < n )) || wr_deny "git -C without a directory"; k=$(( k + 2 )) ;;
      -*) wr_deny "the git option $(wr_show "$a") before the subcommand (only --no-pager and -C <dir>)" ;;
      *) break ;;
    esac
  done
  (( k < n )) || wr_deny "git without a subcommand"
  sub="${S_VAL[k]}"
  k=$(( k + 1 ))
  case "$sub" in
    log|show|diff)
      for (( ; k < n; k++ )); do
        a="${S_VAL[k]}"
        case "$a" in
          --) break ;;
          --output-indicator-*) ;;
          --ou*) wr_deny "git $sub --output, which writes a file" ;;
        esac
      done ;;
    grep)
      for (( ; k < n; k++ )); do
        a="${S_VAL[k]}"
        case "$a" in
          --) break ;;
          --op*) wr_deny "git grep --open-files-in-pager, which runs a program" ;;
          --*) ;;
          -*O*) wr_deny "git grep -O, which runs a program" ;;
        esac
      done ;;
    status|rev-parse|ls-files|blame|cat-file) ;;
    branch|tag)
      # An allowlist, not a deny list: git abbreviates long options here
      # (`git branch --lis` lists), and for tag -a, -s and -v create, sign
      # and verify where for branch -a and -v only widen the listing.
      local listing=0
      for (( ; k < n; k++ )); do
        a="${S_VAL[k]}"
        case "$a" in
          --list|-l) listing=1; continue ;;
          -i|--ignore-case|--contains|--no-contains|--merged|--no-merged|--points-at|--omit-empty) continue ;;
          --column|--no-column|--color|--no-color|--sort=*|--format=*|--color=*|--column=*) continue ;;
          -*) ;;
          *) continue ;;
        esac
        if [[ "$sub" == branch ]]; then
          case "$a" in
            --show-current) listing=1; continue ;;
            -a|--all|-r|--remotes|-v|-vv|--verbose|--abbrev=*|--no-abbrev) continue ;;
          esac
        else
          case "$a" in
            -n|-n[0-9]*) continue ;;
          esac
        fi
        wr_deny "git $sub $(wr_show "$a") (git $sub may only list: --list plus filters)"
      done
      (( listing )) || wr_deny "git $sub without --list, which can create, move or delete" ;;
    remote)
      for (( ; k < n; k++ )); do
        case "${S_VAL[k]}" in
          -v|--verbose) ;;
          *) wr_deny "git remote $(wr_show "${S_VAL[k]}") (only git remote -v)" ;;
        esac
      done ;;
    *) wr_deny "git $(wr_show "$sub"), which is not a read-only subcommand here" ;;
  esac
  return 0
}

WR_ASSIGN_RE='^[A-Za-z_][A-Za-z0-9_]*[+]?='
wr_check_segment() {
  (( ${#S_VAL[@]} > 0 )) || return 0
  local cmd="${S_VAL[0]}"
  if [[ "$cmd" =~ $WR_ASSIGN_RE ]]; then
    wr_deny "a VAR=value prefix ($(wr_show "$cmd"))"
  fi
  case "$cmd" in
    cat|head|tail|ls|wc|cut|tr|stat|jq|diff|echo|pwd|cd) ;;
    grep) wr_check_grep ;;
    sed) wr_check_sed ;;
    find) wr_check_find ;;
    rg) wr_check_rg ;;
    sort) wr_check_sort ;;
    uniq) wr_check_uniq ;;
    file) wr_check_file ;;
    git) wr_check_git ;;
    *) wr_deny "'$(wr_show "$cmd")' is not on the read allowlist" ;;
  esac
  return 0
}

# ─── Walk the chain ───────────────────────────────────────────────────
wr_tokenize "$COMMAND"

seg_redirs=0
prev_op=""
k=0
nt=${#T_KIND[@]}
while (( k <= nt )); do
  if (( k == nt )) || [[ "${T_KIND[k]}" == op ]]; then
    op=""; (( k < nt )) && op="${T_VAL[k]}"
    if (( ${#S_VAL[@]} == 0 )); then
      (( seg_redirs )) && wr_deny "a redirection with no command"
      # An empty stage beside | && || is a syntax error to bash; refuse it
      # rather than guess how bash would read the rest.
      [[ "$prev_op" == '|' || "$prev_op" == '&&' || "$prev_op" == '||' ]] && wr_deny "an empty pipeline stage"
      [[ "$op" == '|' || "$op" == '&&' || "$op" == '||' ]] && wr_deny "an empty pipeline stage"
    fi
    wr_check_segment
    S_VAL=(); S_GLOB=(); seg_redirs=0
    prev_op="$op"
    k=$(( k + 1 ))
    continue
  fi
  if [[ "${T_KIND[k]}" == r ]]; then
    rop="${T_VAL[k]}"
    (( k + 1 < nt )) && [[ "${T_KIND[k+1]}" == w ]] || wr_deny "a redirection ($rop) without a target"
    target="${T_VAL[k+1]}"
    case "$rop" in
      '>'|'>>'|'>|'|'&>'|'&>>')
        [[ "$target" == /dev/null ]] || wr_deny "output redirection to $(wr_show "$target") (only /dev/null)" ;;
      '>&'|'<&')
        [[ "$target" == - || ( -n "$target" && "$target" != *[!0-9]* ) ]] \
          || wr_deny "the redirection $rop$(wr_show "$target") (only a file-descriptor number, as in 2>&1)" ;;
      '<')
        # bash itself opens a socket for these; nothing else under /dev/ does.
        case "$target" in
          /dev/tcp/*|/dev/udp/*) wr_deny "a network redirection ($(wr_show "$target"))" ;;
        esac ;;
      *) wr_deny "the redirection $rop" ;;
    esac
    seg_redirs=1
    k=$(( k + 2 ))
    continue
  fi
  S_VAL+=("${T_VAL[k]}"); S_GLOB+=("${T_GLOB[k]}")
  k=$(( k + 1 ))
done

exit 0
