#!/usr/bin/env bash
# pre-tool-guardian.sh's two recursive-delete rules: the catastrophic-path
# refusal and the unresolved-target rewrite. Sourced by that hook, which calls
# gd_rm_check. They moved here when the hook sat at 1,496 of its 1,500 lines
# (test_conventions.py), with the force-push walk (force-push-walk.sh). They
# read the hook's COMMAND and answer through its gd_deny and gd_rewrite, both
# of which exit. A reason quotes GD_CMD, the hook's clipped copy of the
# command, never COMMAND itself.
#
# The hook fails closed without this file: a command with an rm word is
# refused, because no delete in it can be checked. So is one when this file
# defines no gd_rm_check (an empty or stale copy).

# ─── Catastrophic rm -rf on system/home directories ──────────────────
# Block rm with both -r and -f flags targeting /, ~, $HOME, or critical system paths.
# Handles any flag order: -rf, -fr, -r -f, -f -r, -rfi, etc.
# Root (/) matched with word-boundary-aware pattern: space+slash+(space|end|star)
# `~` needs its own anchoring, NOT the trailing \b the other alternatives use:
# \b requires a word/non-word transition, and `~` is itself a non-word char, so
# `~\b` could never match `~` or `~/...` (it only matched nonsense like `~abc`)
# — i.e. `rm -rf ~` sailed straight through. Anchor it as a home reference
# instead: start/space/`=` before it, and after the optional ~user part `/`,
# whitespace, the end, or a redirect or `)` glued on (`~>/dev/null` and
# `(rm -rf ~)` passed until 2026-11-17). That still lets a trailing-tilde
# backup file through (`rm -rf /tmp/file~`), which is not a home reference.
DANGEROUS_TILDE='(^|[[:space:]]|=)~[a-zA-Z0-9._-]*(/|[[:space:]]|$|[<>)])'
DANGEROUS_NAMED_PATHS="($DANGEROUS_TILDE|\\\$[{]?HOME\\b|(/home|/etc|/usr|/var|/sys|/proc|/boot)\\b)"  # [{]?: ${HOME} too
DANGEROUS_ROOT='(^|[[:space:]])/([[:space:]]|$|\*)'
# rm_scan_flags <statement> — sets RM_RECURSIVE / RM_FORCE from the OPTION
# tokens of an rm statement, never from its operands.
#
# The rule used to be two greps over the whole statement for `-[a-zA-Z]*r` and
# `-[a-zA-Z]*f`, so any hyphen inside a FILENAME supplied the flags. Reproduced
# 2026-09-07: `rm -f <path under /home>/.radar-write-probe` was blocked as a
# catastrophic recursive delete, with no `-r` in the command at all — the `-wr`
# of the basename matched. That is a large share of ordinary cleanup.
#
# It is the over-blocking mirror of the under-blocking fixed on 2026-09-05, and
# one root cause serves both: the guard matched command TEXT instead of
# classifying tokens. A token supplies flags only when it STARTS with `-`, and
# after a `--` nothing does. GNU rm permutes its arguments, so an option may
# legitimately follow an operand — what an operand may never do is BE one.
# Both read the text after the FIRST word rm. They read it after the LAST one
# until 2026-11-17, so `rm -rf / rm` had no flags and was let through.
RM_WORD='(^|[^A-Za-z0-9_])rm([^A-Za-z0-9_]|$)'
rm_after_first() { [[ "$1" =~ $RM_WORD ]] && printf '%s' "${1#*"${BASH_REMATCH[0]}"}"; return 0; }
RM_RECURSIVE=false
RM_FORCE=false
rm_scan_flags() {
  local after tok end_opts=false
  RM_RECURSIVE=false
  RM_FORCE=false
  after=$(rm_after_first "$1")
  while IFS= read -r tok; do
    [[ -z "$tok" ]] && continue
    if [[ "$tok" == "--" ]]; then end_opts=true; continue; fi
    $end_opts && continue
    case "$tok" in
      --recursive|--recursive=*) RM_RECURSIVE=true ;;
      --force|--force=*)         RM_FORCE=true ;;
      --*)                       : ;;
      -?*)
        if [[ "$tok" == *r* ]]; then RM_RECURSIVE=true; fi
        if [[ "$tok" == *f* ]]; then RM_FORCE=true; fi
        ;;
    esac
  done <<< "$(printf '%s' "$after" | tr ' \t' '\n\n')"
  return 0
}

# Proven-deep operands are exempt (rm-targets.sh says why); no lib, no exemption.
# shellcheck source=SCRIPTDIR/rm-targets.sh
source "$(dirname "${BASH_SOURCE[0]}")/rm-targets.sh" 2>/dev/null \
  || rm_all_operands_deep() { return 1; }

# gd_rm_catastrophic — refuse a recursive force delete whose statement names
# a protected path, unless rm_all_operands_deep proves every operand deep.
gd_rm_catastrophic() {
  CATASTROPHIC_RM=false
  while IFS= read -r _stmt; do
    [[ -z "$_stmt" ]] && continue
    rm_scan_flags "$_stmt"
    $RM_RECURSIVE || continue
    $RM_FORCE || continue
    if printf '%s\n' "$_stmt" | grep -qE "$DANGEROUS_NAMED_PATHS" \
      || printf '%s\n' "$_stmt" | grep -qE "$DANGEROUS_ROOT"; then
      rm_all_operands_deep "$_stmt" && continue
      CATASTROPHIC_RM=true
      break
    fi
  done <<< "$RM_STATEMENTS"
  if [[ "$CATASTROPHIC_RM" == true ]]; then
    gd_deny "Catastrophic rm -rf blocked on system/home directory. ${RM_SHALLOW:+Target: $RM_SHALLOW. }Refused: /, a home directory or a directory directly inside one (two levels for a dot-directory such as ~/.claude), and /etc, /usr, /var, /sys, /proc, /boot. Not refused: a literal path two levels below a home directory, or under /tmp or /var/tmp. If this target really must go, it is the owner's to run in their own terminal. Command: $GD_CMD"
  fi
}

# ─── Recursive delete on a target the guardian cannot resolve ─────────
#
# The rule above matches the TEXT of the target, which is what a human types
# and not what an agent writes. Measured 2026-09-05: a recursive delete against
# $BUILD_DIR/, "$BUILD_DIR"/, ${OUT}/, $OUT/*, $(pwd)/* or a bare glob was
# ALLOWED by both guardians while every spelled-out form was blocked.
#
# What makes it dangerous is the shell lifecycle, not the regex. Each Bash tool
# call is a fresh shell, so a variable assigned in an earlier call is unset in
# this one and the target expands to the filesystem root — the very string the
# rule above exists to stop. GNU rm's --preserve-root does not save it either,
# because the expanded argument is root-plus-star rather than root.
#
# Two answers, because the two shapes differ in whether anything can be made
# safe:
#   a name  → rewrite $NAME to ${NAME:?...}. A set variable runs unchanged; an
#             unset one aborts naming itself. A correct command pays nothing.
#   no name → refuse. $(...) and a bare glob are decided at run time and there
#             is nothing to make required.
#
# Ordering matters: this runs AFTER the catastrophic-path block, so $HOME and
# the named system paths stay blocked rather than being rewritten into a
# "required" variable that is always set.
gd_rm_unresolved() {
  # A delete written inside a single-quoted string is text, not a command, and
  # rewriting it would corrupt the string. Count the quotes that open before the
  # first rm; an odd number means we are inside one.
  _pre_rm=$(printf '%s' "$COMMAND" | sed -E 's/(\brm\b).*/\1/')
  _quotes=$(printf '%s' "$_pre_rm" | tr -cd "'" | wc -c | tr -d ' ')
  (( _quotes % 2 == 0 )) || return 0
  # Shell-owned names are always set, so requiring them proves nothing. $HOME
  # is on this list and is also blocked outright above; that block wins.
  _SHELL_OWNED=" HOME PWD OLDPWD TMPDIR XDG_RUNTIME_DIR CLAUDE_PROJECT_DIR "
  _unresolved_var=""
  _refuse_reason=""

  while IFS= read -r _stmt; do
    [[ -z "$_stmt" ]] && continue
    [[ -n "$_unresolved_var" || -n "$_refuse_reason" ]] && break
    rm_scan_flags "$_stmt"
    $RM_RECURSIVE || continue
    $RM_FORCE || continue

    # Everything after the rm, minus its flags, is a candidate target.
    _after=$(rm_after_first "$_stmt")
    while IFS= read -r _tok; do
      [[ -z "$_tok" ]] && continue
      case "$_tok" in -*) continue ;; esac
      _bare=${_tok//\"/}

      # No name to require: the value appears at run time.
      case "$_bare" in
        *'$('*|*'`'*)
          _refuse_reason="a command substitution decides the target at run time"
          break ;;
      esac
      case "$_bare" in
        '*'|'./'*'*'|'./*'|'.'|'./')
          _refuse_reason="a bare glob resolves against whatever the working directory happens to be"
          break ;;
      esac

      # $NAME or ${NAME} at the head of the target.
      _var=$(printf '%s' "$_bare" | sed -nE 's/^\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?.*/\1/p')
      [[ -z "$_var" ]] && continue
      [[ "$_SHELL_OWNED" == *" $_var "* ]] && continue
      # Assigned in this same command, so this shell will have it.
      if printf '%s\n' "$COMMAND" | grep -qE "(^|[[:space:];&|(])(export[[:space:]]+)?${_var}="; then
        continue
      fi
      _unresolved_var="$_var"
      break
    done <<< "$(printf '%s' "$_after" | tr ' \t' '\n\n')"
  done <<< "$RM_STATEMENTS"

  if [[ -n "$_refuse_reason" ]]; then
    gd_deny "Recursive delete refused: ${_refuse_reason}. Name the directory explicitly, or run it manually after checking what it expands to. Command: $GD_CMD"
  fi

  if [[ -n "$_unresolved_var" ]]; then
    _guard_msg="pre-tool-guardian: refusing a recursive delete on unset ${_unresolved_var}"
    _SAFE_RM=${COMMAND//\$\{${_unresolved_var}\}/\$\{${_unresolved_var}:?${_guard_msg}\}}
    _SAFE_RM=${_SAFE_RM//\$${_unresolved_var}/\$\{${_unresolved_var}:?${_guard_msg}\}}
    gd_rewrite "$_SAFE_RM" "pre-tool-guardian rewrote \$${_unresolved_var} to \${${_unresolved_var}:?…} in a recursive delete: each Bash call is a fresh shell, so a variable set in an earlier call is unset here and the target would expand to the filesystem root. The command runs unchanged when the variable is set."
  fi
  return 0
}

# gd_rm_check — both rules, in that order; it returns when neither fires.
# Split into statements first, and require ONE statement to meet every
# condition. Per-line greps blocked `SRC=/home/me; rm -rf /tmp/x` for a home
# path on the same line, and combined `rm -r a` and `rm -f /home/b` from two
# statements into a block neither earned. `tr`, not sed \n: BSD sed rejects it.
gd_rm_check() {
  RM_STATEMENTS=$(printf '%s' "$COMMAND" | tr ';|&' '\n\n\n' | grep -E '\brm\b' || true)
  gd_rm_catastrophic
  gd_rm_unresolved
}
