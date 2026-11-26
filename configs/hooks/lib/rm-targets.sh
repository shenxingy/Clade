#!/usr/bin/env bash
# Which recursive-delete targets pre-tool-guardian.sh's catastrophic rule
# exists for. Sourced by rm-guard.sh, which holds that rule; kept apart because
# the hook sat at the 1500-line cap.
#
# The rule's text match is depth-blind: `/home\b`, `/var\b` and a home `~/`
# match at ANY depth, so every recursive delete under a home directory or
# /var/tmp was "catastrophic". Measured 2026-11-09 over one host's retained
# transcripts (every profile, 30 days): about 47 sessions carry the refusal,
# and its delete targets were ~20 scratch directories under /var/tmp, git
# worktrees under ~/projects/worktrees, deep scratch such as
# ~/rd/face-crop/out/webcam-good, and about 5 greps whose PATTERN held the
# words; one target was a real home directory. After a refusal the next calls
# either reached the same delete another way or left it in a file for a human.
#
# So the text match still decides, and one narrow exemption is added: a
# statement is let through only when EVERY operand of its rm is a literal,
# anchored path rm_operand_is_deep can prove is deep. Anything it cannot
# prove — a variable other than a leading $HOME, a substitution, a `..`, a
# glob at the top, a relative path, `find … -exec rm -rf {}` — keeps the old
# verdict, so the rule is never weaker than it was where it is unsure.
#
# Deep means: two levels below a home directory (three when the first is a
# dot-directory, so ~/.claude/projects stays protected), strictly under
# /var/tmp, or an absolute path outside every protected tree (`/tmp/home-x`
# no longer reads as /home). /, a home directory, a directory directly inside
# one, and /etc /usr /var /sys /proc /boot at any depth are never deep.
#
# The Codex mirror carries the same logic (_operand_is_deep in
# plugins/clade/hooks/pre_tool_guardian.py); the parity section of
# tests/test-pre-tool-guardian.sh feeds both the same commands.
#
# The refusal's first sentence ("Catastrophic rm -rf blocked on system/home
# directory.") is kept verbatim in rm-guard.sh: friction-rank.py groups refusals
# by first sentence, so rewording it would split this guard's history in two.
# rm-guard.sh fails closed without this file: no operand is exempt.

# Regexes live in variables: bash 3.2 and 4+ disagree on escapes written
# inline after =~, and an unquoted ~ there could be tilde-expanded.
RM_REDIR_BARE='^[0-9]*(>|>>|<|>[|])$'
RM_REDIR_GLUED='^[0-9]*[<>]'
RM_PLAIN_PATH='^[~]?[A-Za-z0-9._/*+@%=,:-]*$'

# rm_operands <statement> — the operands of an rm statement, one per line:
# every token after the FIRST word rm that is not an option or a redirection,
# and every token after `--`. Reading from the first word judges a superset of
# the real rm's operands, so a stray later "rm" can only add a token to
# refuse. Without rm-guard.sh's rm_after_first there are none: no exemption.
rm_operands() {
  local tok end_opts=false skip_next=false
  # rm_after_first is rm-guard.sh's: the same text its flags are read from. A
  # first token `rm` would not do: in `\rm -rf ~ rm /var/tmp/x` it is the
  # second rm, and only `/var/tmp/x` would be judged.
  declare -F rm_after_first >/dev/null || return 0
  while IFS= read -r tok; do
    [[ -z "$tok" ]] && continue
    if $skip_next; then skip_next=false; continue; fi
    # A redirection is not an operand: a bare operator takes the next token
    # as its target; `2>/dev/null` carries its own. A word with a redirect
    # glued after it (`~>/dev/null`) is NOT skipped: its operand is `~`, and
    # rm_operand_is_deep refuses the `>`.
    if [[ "$tok" =~ $RM_REDIR_BARE ]]; then skip_next=true; continue; fi
    [[ "$tok" =~ $RM_REDIR_GLUED ]] && continue
    if ! $end_opts; then
      if [[ "$tok" == "--" ]]; then end_opts=true; continue; fi
      case "$tok" in -?*) continue ;; esac
    fi
    printf '%s\n' "$tok"
  done <<< "$(rm_after_first "$1" | tr ' \t' '\n\n')"
  return 0
}

# rm_home_rest_is_deep <path below a home directory, no leading slash>
rm_home_rest_is_deep() {
  local rest="$1" top
  [[ "$rest" == */* ]] || return 1
  top=${rest%%/*}
  case "$top" in *'*'*|*'?'*|*'['*|*'{'*) return 1 ;; esac
  case "$top" in .*) [[ "$rest" == */*/* ]] || return 1 ;; esac
  return 0
}

# rm_operand_is_deep <operand> — succeeds only when the operand provably names
# none of the catastrophic targets. Fails on anything it cannot prove.
rm_operand_is_deep() {
  local t="$1" rest top
  # shellcheck disable=SC2016  # literal text to match, not an expansion
  local home_var='$HOME' home_braced='${HOME}'
  local dot_seg='/./' slash='/' star_tail='/*'
  t=${t//\"/}
  t=${t//\'/}
  case "$t" in
    "$home_var"|"$home_var"/*)       t="~${t#"$home_var"}" ;;
    "$home_braced"|"$home_braced"/*) t="~${t#"$home_braced"}" ;;
  esac
  # Only plain path characters, and a tilde only in front. That refuses any
  # other variable or substitution, a brace (`~/x/{..,..}` is `~/x/..`), a
  # `?` or `[…]` glob (`??` matches `..`), a backslash, and a redirect or
  # subshell glued to the word (`~>/dev/null` deletes `~`).
  [[ "$t" =~ $RM_PLAIN_PATH ]] || return 1
  t=$(printf '%s' "$t" | tr -s '/')
  while [[ "$t" == *"$dot_seg"* ]]; do t=${t//"$dot_seg"/$slash}; done
  # A trailing /, /. or /* deletes the directory's contents: judge the directory.
  while :; do
    case "$t" in
      */)             t=${t%/} ;;
      */.)            t=${t%/.} ;;
      *"$star_tail")  t=${t%"$star_tail"} ;;
      *) break ;;
    esac
  done
  # `..` can climb back into anything.
  case "/$t/" in */../*) return 1 ;; esac
  # A `*` is judged only in the last component, and never after a dot:
  # `.*` matches `..`, so `~/a/b/.*/.*/c` reaches `~/c`.
  case "$t" in *'*'*/*) return 1 ;; esac
  case "${t##*/}" in .*'*'*) return 1 ;; esac
  case "$t" in
    '~'*)
      rest=${t:1}
      if [[ "$rest" == */* ]]; then rest=${rest#*/}; else rest=""; fi
      rm_home_rest_is_deep "$rest"; return $? ;;
    /home/*|/Users/*)
      rest=${t#/*/}
      top=${rest%%/*}
      case "$top" in *'*'*|*'?'*|*'['*|*'{'*) return 1 ;; esac
      if [[ "$rest" == */* ]]; then rest=${rest#*/}; else rest=""; fi
      rm_home_rest_is_deep "$rest"; return $? ;;
    /root/*)
      rm_home_rest_is_deep "${t#/root/}"; return $? ;;
    /var/tmp/*)
      return 0 ;;
    ''|/home|/Users|/root|/etc|/etc/*|/usr|/usr/*|/boot|/boot/*|/sys|/sys/*|/proc|/proc/*|/var|/var/*)
      return 1 ;;
    /*)
      top=${t#/}
      top=${top%%/*}
      case "$top" in *'*'*|*'?'*|*'['*|*'{'*) return 1 ;; esac
      return 0 ;;
  esac
  return 1  # relative: what it names depends on the working directory
}

# rm_all_operands_deep <statement> — every operand deep, and at least one.
# Sets RM_SHALLOW to the first operand that is not (empty when there is none).
rm_all_operands_deep() {
  local op seen=false
  RM_SHALLOW=""
  while IFS= read -r op; do
    [[ -z "$op" ]] && continue
    seen=true
    if ! rm_operand_is_deep "$op"; then RM_SHALLOW="$op"; return 1; fi
  done <<< "$(rm_operands "$1")"
  $seen
}
