#!/usr/bin/env bash
# pre-tool-guardian.sh — Block dangerous Bash commands before they execute
#
# Triggered: PreToolUse (matcher: Bash)
# Purpose:   Auto-block operations that either:
#   1. Timeout inside Claude Code (database migrations)
#   2. Are catastrophically destructive (rm -rf /, DROP DATABASE)
#   3. Could corrupt parallel agent sessions (force push to main)
#
# Output — Claude Code's PreToolUse schema, nothing else:
#   block   {"hookSpecificOutput":{"hookEventName":"PreToolUse",
#             "permissionDecision":"deny","permissionDecisionReason":"..."}}
#   rewrite {"hookSpecificOutput":{"hookEventName":"PreToolUse",
#             "updatedInput":{<tool_input with command replaced>},
#             "additionalContext":"..."}}
#   allow   exit 0 with no output
#
# Why the rewrite carries NO permissionDecision. Until 2026-10-20 both rewrite
# branches answered {"decision":"allow","updatedInput":…}. Claude Code rejects
# that object ("top-level decision is the legacy approve|block field") and runs
# the ORIGINAL command: 41 rejections in transcripts, 2026-09-22 → 10-19, so the
# unset-variable delete guard and the force-push rewrite had protected nothing.
# The fix is not "allow": "allow" also bypasses permission prompts and deny
# rules, so a guard that only meant to defuse a command would have granted it.
# updatedInput WITHOUT a decision rewrites and leaves the normal permission
# flow in place — verified live on 2.1.283: an unallowed `touch` rewritten this
# way was still denied, an allowed one ran in its rewritten form.
#
# No `set -e`, on purpose. A failed test inside a check must not abort the
# guard: rm_scan_flags used to return the status of its last `[[ … ]] && …`,
# so any statement whose last option token lacked an `f` killed the hook with
# exit 1 — a non-blocking error to Claude Code, which then ran the command with
# every later check (force push, DROP, pkill) skipped. Ten of 20,111 real
# commands replayed on 2026-10-20 crashed it that way.

set -uo pipefail

# Read JSON input from stdin
INPUT=$(cat)

TOOL_NAME=$(printf '%s' "$INPUT" | jq -r '.tool_name // ""' 2>/dev/null || echo "")

# Only act on Bash tool
if [[ "$TOOL_NAME" != "Bash" ]]; then
  exit 0
fi

COMMAND=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null || echo "")
TOOL_INPUT=$(printf '%s' "$INPUT" | jq -c '.tool_input // {}' 2>/dev/null || echo '{}')
HOOK_CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // ""' 2>/dev/null || echo "")

if [[ -z "$COMMAND" ]]; then
  exit 0
fi

# ─── Output helpers ───────────────────────────────────────────────────
# gd_deny <reason> — refuse the call; Claude sees the reason.
gd_deny() {
  jq -n --arg r "$1" \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
  exit 0
}
# gd_rewrite <new-command> <why> — run a safer command in place of the
# proposed one. The rest of tool_input (description, timeout,
# run_in_background) is carried over; updatedInput replaces the whole input.
gd_rewrite() {
  jq -n --argjson ti "$TOOL_INPUT" --arg c "$1" --arg why "$2" \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",updatedInput:($ti + {command:$c}),additionalContext:$why}}'
  exit 0
}

# ─── Dev mode check ───────────────────────────────────────────────────
# When ~/.claude/.dev-mode exists, skip migration blocking.
# Run `devmode` to toggle. Catastrophic operations are ALWAYS blocked.
DEV_MODE=false
[[ -f "$HOME/.claude/.dev-mode" ]] && DEV_MODE=true

# ─── Database migrations ──────────────────────────────────────────────
# These require interactive confirmation or long timeouts — must run manually.
# Common ORM/migration tools that block or timeout inside Claude Code.
# (Skipped in dev mode — toggle with: devmode on/off)
if [[ "$DEV_MODE" == false ]]; then
# Strip comment-only lines AND pure-assignment lines before scanning.
# A "pure assignment" is a line whose ENTIRE content is a single variable
# assignment (optionally followed by `;`). Lines like
#   DATABASE_URL="..." alembic upgrade head
# are NOT stripped — the assignment is a prefix, and the rest is a real
# command that must be scanned. (Earlier revisions over-stripped these,
# allowing env-prefixed migrations to slip past the guardian — KL1.)
#
# Prevented false positives (still stripped):
#   - Shell comments:       # alembic upgrade head
#   - String assignments:   INPUT='{"command":"alembic upgrade",...}'
#   - Heredoc data lines:   VAR="alembic upgrade head"
SCANNABLE=$(printf '%s\n' "$COMMAND" \
  | grep -v '^\s*#' \
  | grep -vE "^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*='[^']*'[[:space:]]*;?[[:space:]]*$" \
  | grep -vE '^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*="[^"]*"[[:space:]]*;?[[:space:]]*$' \
  || true)

MIGRATION_PATTERNS=(
  "db:push"
  "db:migrate"
  "prisma migrate"
  "drizzle-kit push"
  "alembic upgrade"
  "alembic downgrade"
  "rake db:migrate"
  "rake db:rollback"
  "knex migrate:latest"
  "knex migrate:rollback"
  "sequelize db:migrate"
  "flyway migrate"
  "liquibase update"
)

for pattern in "${MIGRATION_PATTERNS[@]}"; do
  if printf '%s\n' "$SCANNABLE" | grep -qF "$pattern"; then
    gd_deny "Database migration detected: '$pattern' cannot run inside Claude Code (interactive prompts / timeouts). Run manually in your terminal: $COMMAND"
  fi
done
fi  # end dev-mode gate

# ─── Catastrophic rm -rf on system/home directories ──────────────────
# Block rm with both -r and -f flags targeting /, ~, $HOME, or critical system paths.
# Handles any flag order: -rf, -fr, -r -f, -f -r, -rfi, etc.
# Root (/) matched with word-boundary-aware pattern: space+slash+(space|end|star)
# `~` needs its own anchoring, NOT the trailing \b the other alternatives use:
# \b requires a word/non-word transition, and `~` is itself a non-word char, so
# `~\b` could never match `~` or `~/...` (it only matched nonsense like `~abc`)
# — i.e. `rm -rf ~` sailed straight through. Anchor it as a home reference
# instead: start/space/`=` before it, and `/`, whitespace, or end after the
# optional ~user part. That still lets a trailing-tilde backup file through
# (`rm -rf /tmp/file~`), which is not a home reference.
DANGEROUS_TILDE='(^|[[:space:]]|=)~[a-zA-Z0-9._-]*(/|[[:space:]]|$)'
DANGEROUS_NAMED_PATHS="($DANGEROUS_TILDE|\\\$HOME\\b|(/home|/etc|/usr|/var|/sys|/proc|/boot)\\b)"
DANGEROUS_ROOT='(^|[[:space:]])/([[:space:]]|$|\*)'
# Split into individual shell statements before testing, then require ONE
# statement to satisfy every condition on its own.
#
# Per-LINE matching was too coarse in both directions:
#   - False positive: `SRC=/home/me/.claude; rm -rf /tmp/shadow-test` blocked a
#     benign temp delete because a home path shared its line. Shell one-liners
#     chain statements with ; && || far more often than they use newlines, so
#     "only look at rm lines" did not actually isolate the rm.
#   - False negative direction: the three greps ran independently over the whole
#     set of rm lines, so `rm -r a` on one line plus `rm -f /home/b` on another
#     combined into a block that neither statement earned.
# `tr` (not sed \n, which BSD sed rejects) keeps this portable to macOS.
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
RM_RECURSIVE=false
RM_FORCE=false
rm_scan_flags() {
  local after tok end_opts=false
  RM_RECURSIVE=false
  RM_FORCE=false
  after=$(printf '%s' "$1" | sed -E 's/^.*\brm\b//')
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

RM_STATEMENTS=$(printf '%s' "$COMMAND" | tr ';|&' '\n\n\n' | grep -E '\brm\b' || true)
CATASTROPHIC_RM=false
while IFS= read -r _stmt; do
  [[ -z "$_stmt" ]] && continue
  rm_scan_flags "$_stmt"
  $RM_RECURSIVE || continue
  $RM_FORCE || continue
  if printf '%s\n' "$_stmt" | grep -qE "$DANGEROUS_NAMED_PATHS" \
    || printf '%s\n' "$_stmt" | grep -qE "$DANGEROUS_ROOT"; then
    CATASTROPHIC_RM=true
    break
  fi
done <<< "$RM_STATEMENTS"
if [[ "$CATASTROPHIC_RM" == true ]]; then
  gd_deny "Catastrophic rm -rf blocked on system/home directory. Command: $COMMAND. If intentional, run manually in your terminal."
fi

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

# A delete written inside a single-quoted string is text, not a command, and
# rewriting it would corrupt the string. Count the quotes that open before the
# first rm; an odd number means we are inside one.
_pre_rm=$(printf '%s' "$COMMAND" | sed -E 's/(\brm\b).*/\1/')
_quotes=$(printf '%s' "$_pre_rm" | tr -cd "'" | wc -c | tr -d ' ')
if (( _quotes % 2 == 0 )); then
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
    _after=$(printf '%s' "$_stmt" | sed -E 's/^.*\brm\b//')
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
    gd_deny "Recursive delete refused: ${_refuse_reason}. Name the directory explicitly, or run it manually after checking what it expands to. Command: $COMMAND"
  fi

  if [[ -n "$_unresolved_var" ]]; then
    _guard_msg="pre-tool-guardian: refusing a recursive delete on unset ${_unresolved_var}"
    _SAFE_RM=${COMMAND//\$\{${_unresolved_var}\}/\$\{${_unresolved_var}:?${_guard_msg}\}}
    _SAFE_RM=${_SAFE_RM//\$${_unresolved_var}/\$\{${_unresolved_var}:?${_guard_msg}\}}
    gd_rewrite "$_SAFE_RM" "pre-tool-guardian rewrote \$${_unresolved_var} to \${${_unresolved_var}:?…} in a recursive delete: each Bash call is a fresh shell, so a variable set in an earlier call is unset here and the target would expand to the filesystem root. The command runs unchanged when the variable is set."
  fi
fi


# ─── Force push ───────────────────────────────────────────────────────
# Read as shell, not as text. The old rule was "`git push` anywhere AND
# --force/-f anywhere AND main anywhere", plus a sed over the whole string.
# Replayed over the 41 commands it fired on (2026-09-22 → 10-19), had its output
# ever been accepted it would have turned 14 `--force-with-lease` into
# `--force-with-lease-with-lease`, put `--force-with-lease` on 7 `git worktree
# remove --force` / `rm -f` statements, and corrupted 2 ref names
# (`feat/verdict-c-f-split`) — and it blocked `git push origin main && rm -f x`.
#
# The awk below walks the command once, honouring quotes, backslashes,
# comments and heredoc bodies (data, never commands), splits it into
# statements on ; & | ( ) ` $( and newlines (but not on the & of 2>&1), and
# looks only at a statement whose command is `git [global opts] push`. In that
# statement a force is a `--force` token, a short-option cluster containing f
# (-f, -uf), or a `+refspec`; `--force-with-lease` / `--force-if-includes` are
# already safe. A ref is main when the DESTINATION of a refspec (after the last
# `:`, minus `+` and refs/heads/) is main or master; with no refspec at all the
# pushed branch is the current one, read from the session's cwd unless the
# command changed directory or used `git -C`. `ssh … "…"`, `bash -c "…"` and
# eval carry the push in one quoted token, so their argument is split on
# separators and checked for the same three facts — block only, never rewritten.
#
# Prints: none | block<TAB>main|branch|delete|nested | rewrite<NL><new command>
read -r -d '' GD_PUSH_AWK <<'AWK'
function start_tok() { if (!in_tok) { in_tok = 1; tok_start = i; tok_val = "" } }
function flush_tok() {
  if (in_tok) { nt++; ts[nt] = tok_start; te[nt] = i - 1; tv[nt] = tok_val; in_tok = 0 }
}
function end_seg() { flush_tok(); if (nt > 0) analyze(); nt = 0 }
function block(code) { if (blocked == "") blocked = code }
function add_edit(s, e, t) { ne++; es[ne] = s; ee[ne] = e; et[ne] = t }
function dst_of(r,   p) {
  while ((p = index(r, ":")) > 0) r = substr(r, p + 1)
  sub(/^refs\/heads\//, "", r)
  return r
}
function nested(k,   s, j, n, parts) {
  s = ""
  for (j = k + 1; j <= nt; j++) s = s " " tv[j]
  n = split(s, parts, /[;&|\n]/)
  for (j = 1; j <= n; j++) {
    s = " " parts[j] " "
    if (s ~ /[ \t]git[ \t]+([^ \t]+[ \t]+)*push[ \t]/ &&
        (s ~ /[ \t](--force|--force-with-lease[^ \t]*|-[A-Za-z]*f[A-Za-z]*)[ \t]/ || s ~ /[ \t]\+[^ \t]/) &&
        s ~ /[ \t:+\/](main|master)[ \t'"]/) block("nested")
  }
}
function analyze(   k, w, hasC, j, v, skipnext, dd, npos, nf, np, lease, allrefs, nrefs, mainref, del, r, plus, raw, newv, pk) {
  k = 1
  while (k <= nt && tv[k] ~ /^[A-Za-z_][A-Za-z0-9_]*=/) k++
  while (k <= nt && (tv[k] == "sudo" || tv[k] == "command" || tv[k] == "env" || tv[k] == "nohup" || tv[k] == "time" || tv[k] == "exec")) {
    k++
    while (k <= nt && (tv[k] ~ /^[A-Za-z_][A-Za-z0-9_]*=/ || tv[k] ~ /^-/)) k++
  }
  if (k > nt) return
  w = tv[k]; sub(/.*\//, "", w)
  if (w == "cd" || w == "pushd") { cd_seen = 1; return }
  if (w == "ssh" || w == "bash" || w == "sh" || w == "zsh" || w == "eval") { nested(k); return }
  if (w != "git") return
  k++; hasC = 0
  while (k <= nt) {
    v = tv[k]
    if (v == "-C" || v == "-c" || v == "--git-dir" || v == "--work-tree" || v == "--namespace") { if (v != "-c") hasC = 1; k += 2; continue }
    if (v ~ /^--(git-dir|work-tree)=/) { hasC = 1; k++; continue }
    if (v ~ /^-/) { k++; continue }
    break
  }
  if (k > nt || tv[k] != "push") return
  pk = k
  skipnext = 0; dd = 0; npos = 0; nf = 0; np = 0; lease = 0; allrefs = 0; nrefs = 0; mainref = 0; del = 0
  for (j = pk + 1; j <= nt; j++) {
    v = tv[j]
    if (skipnext) { skipnext = 0; continue }
    if (v ~ /^[0-9]*[<>]/ || v ~ /^&>/) { if (v ~ /^[0-9]*[<>]+&?$/ || v ~ /^&>>?$/) skipnext = 1; continue }
    if (!dd && v == "--") { dd = 1; continue }
    if (!dd && v ~ /^--/) {
      if (v == "--force") { nf++; FI[nf] = j }
      else if (v ~ /^--force-with-lease/ || v == "--force-if-includes") lease = 1
      else if (v == "--all" || v == "--mirror" || v == "--branches") allrefs = 1
      else if (v == "--delete") del = 1
      else if (v == "--repo" || v == "--receive-pack" || v == "--exec" || v == "--push-option") skipnext = 1
      continue
    }
    if (!dd && v ~ /^-[^-]/) {
      if (v == "-o") { skipnext = 1; continue }
      # Only an alphanumeric cluster is short options. git rejects a malformed
      # `-f-with-lease`, so it is left alone rather than "repaired".
      if (v !~ /^-[A-Za-z0-9]+$/) continue
      if (index(v, "d") > 0) del = 1
      if (index(v, "f") > 0) { nf++; FI[nf] = j }
      continue
    }
    npos++
    if (npos == 1) continue
    nrefs++
    r = v; plus = 0
    if (substr(r, 1, 1) == "+") { plus = 1; r = substr(r, 2) }
    if (dst_of(r) == "main" || dst_of(r) == "master") {
      mainref = 1
      if (substr(r, 1, 1) == ":") del = 1
    }
    if (plus) { np++; PI[np] = j }
  }
  if (del && mainref) { block("delete"); return }
  if (nf == 0 && np == 0 && !lease) return
  if (mainref || (allrefs && (nf > 0 || np > 0))) { block("main"); return }
  if (nrefs == 0 && !allrefs && !cd_seen && !hasC && (ENVIRON["GD_BRANCH"] == "main" || ENVIRON["GD_BRANCH"] == "master")) { block("branch"); return }
  if (nf == 0 && np == 0) return
  for (j = 1; j <= nf; j++) {
    v = tv[FI[j]]
    if (v == "--force" || v == "-f") newv = "--force-with-lease"
    else { newv = v; gsub(/f/, "", newv); newv = (newv == "-") ? "--force-with-lease" : newv " --force-with-lease" }
    add_edit(ts[FI[j]], te[FI[j]], newv)
  }
  for (j = 1; j <= np; j++) {
    raw = substr(cmd, ts[PI[j]], te[PI[j]] - ts[PI[j]] + 1)
    sub(/\+/, "", raw)
    add_edit(ts[PI[j]], te[PI[j]], raw)
  }
  if (nf == 0 && !lease) add_edit(te[pk] + 1, te[pk], " --force-with-lease")
}
{ cmd = (NR == 1) ? $0 : cmd RS $0 }
END {
  n = length(cmd); i = 1; q = ""; in_tok = 0; nt = 0; ne = 0; hd_n = 0; blocked = ""; cd_seen = 0
  while (i <= n) {
    c = substr(cmd, i, 1)
    if (q == "'") { if (c == "'") q = ""; else tok_val = tok_val c; i++; continue }
    if (q == "\"") {
      if (c == "\\" && i < n) {
        nc = substr(cmd, i + 1, 1)
        if (nc == "\\" || nc == "\"" || nc == "$" || nc == "`") { tok_val = tok_val nc; i += 2; continue }
      }
      if (c == "\"") q = ""; else tok_val = tok_val c
      i++; continue
    }
    if (c == "\\") {
      if (i < n && substr(cmd, i + 1, 1) == "\n") { i += 2; continue }
      start_tok(); if (i < n) tok_val = tok_val substr(cmd, i + 1, 1); i += 2; continue
    }
    if (c == "'" || c == "\"") { start_tok(); q = c; i++; continue }
    if (c == " " || c == "\t") { flush_tok(); i++; continue }
    if (c == "#" && !in_tok) { while (i <= n && substr(cmd, i, 1) != "\n") i++; continue }
    if (c == "\n") {
      end_seg(); i++
      for (h = 1; h <= hd_n; h++) {
        while (i <= n) {
          e = index(substr(cmd, i), "\n")
          line = (e > 0) ? substr(cmd, i, e - 1) : substr(cmd, i)
          i = (e > 0) ? i + e : n + 1
          if (hd_strip[h]) sub(/^\t+/, "", line)
          if (line == hd_delim[h]) break
        }
      }
      hd_n = 0
      continue
    }
    if (c == "$" && substr(cmd, i + 1, 1) == "(") { end_seg(); i += 2; continue }
    if (c == ";" || c == "|" || c == "(" || c == ")" || c == "`") { end_seg(); i++; continue }
    if (c == "&") {
      if ((i > 1 && (substr(cmd, i - 1, 1) == ">" || substr(cmd, i - 1, 1) == "<")) || substr(cmd, i + 1, 1) == ">") {
        start_tok(); tok_val = tok_val c; i++; continue
      }
      end_seg(); i++; continue
    }
    if (c == "<" && substr(cmd, i, 2) == "<<" && substr(cmd, i, 3) != "<<<") {
      flush_tok(); j = i + 2; strip = 0
      if (substr(cmd, j, 1) == "-") { strip = 1; j++ }
      while (substr(cmd, j, 1) == " " || substr(cmd, j, 1) == "\t") j++
      qc = substr(cmd, j, 1); if (qc == "'" || qc == "\"") j++; else qc = ""
      word = ""
      while (j <= n && substr(cmd, j, 1) ~ /[A-Za-z0-9_]/) { word = word substr(cmd, j, 1); j++ }
      if (qc != "" && substr(cmd, j, 1) == qc) j++
      if (word != "") { hd_n++; hd_delim[hd_n] = word; hd_strip[hd_n] = strip }
      i = j; continue
    }
    start_tok(); tok_val = tok_val c; i++
  }
  end_seg()
  if (blocked != "") { print "block\t" blocked; exit }
  if (ne == 0) { print "none"; exit }
  for (a = 2; a <= ne; a++) {
    s0 = es[a]; e0 = ee[a]; t0 = et[a]; b = a - 1
    while (b >= 1 && es[b] < s0) { es[b + 1] = es[b]; ee[b + 1] = ee[b]; et[b + 1] = et[b]; b-- }
    es[b + 1] = s0; ee[b + 1] = e0; et[b + 1] = t0
  }
  out = cmd
  for (a = 1; a <= ne; a++) out = substr(out, 1, es[a] - 1) et[a] substr(out, ee[a] + 1)
  print "rewrite"; printf "%s", out
}
AWK

if [[ "$COMMAND" == *push* ]]; then
  GD_BRANCH=$(git -C "${HOOK_CWD:-$PWD}" symbolic-ref --short -q HEAD 2>/dev/null || true)
  _gp=$(printf '%s' "$COMMAND" | GD_BRANCH="$GD_BRANCH" LC_ALL=C awk 'BEGIN { RS = "\001" } '"$GD_PUSH_AWK" 2>/dev/null || true)
  case "$_gp" in
    block*)
      case "$_gp" in
        *branch) _why="it pushes the current branch, which is ${GD_BRANCH}" ;;
        *delete) _why="it deletes main/master on the remote" ;;
        *nested) _why="a wrapped command (ssh, bash -c, eval) force-pushes main/master" ;;
        *)       _why="it names main/master" ;;
      esac
      gd_deny "Force push to main/master blocked: ${_why}. This destroys shared history. Use --force-with-lease on a feature branch, or ask the user explicitly. Command: $COMMAND"
      ;;
    rewrite*)
      gd_rewrite "${_gp#rewrite$'\n'}" "pre-tool-guardian rewrote a force push to --force-with-lease, which refuses to overwrite the remote branch if someone else updated it since your last fetch. Only the git push statement changed."
      ;;
  esac
fi

# ─── SQL DROP DATABASE / DROP TABLE ──────────────────────────────────
# These are irreversible. Redirect to manual execution.
if printf '%s\n' "$COMMAND" | grep -qiE '\bDROP[[:space:]]+(DATABASE|TABLE|SCHEMA)\b'; then
  gd_deny "SQL DROP statement blocked. Irreversible operation must be run manually in your terminal after review. Command: $COMMAND"
fi

# ─── Self-killing pkill -f ───────────────────────────────────────────
# `pkill -f PAT` matches against full command lines, including the command line
# of the shell that launched it. Inside an ssh one-liner or a compound command
# whose own text contains PAT, the launching shell matches its own pattern and
# kills itself: exit 255/144, and the work after the `&&` never runs. It looks
# like the remote host rejected the connection, so the time goes into debugging
# ssh. Blocked only in the shape that actually self-destructs, because a guard
# that fires on ordinary `pkill -f name` is one you learn to ignore.
# `pkill` must sit at a COMMAND position — start of string, or after a
# separator or an opening quote. Matching it anywhere caught prose: this very
# guard's own commit message ("block the pkill -f shape that kills its own
# launcher") was refused, which is the failure mode the rule below warns about.
if printf '%s\n' "$COMMAND" | grep -qE '(^|[;&|(]|[[:space:]]&&[[:space:]]|["'"'"'])[[:space:]]*pkill[[:space:]]+(-[a-zA-Z]*f|--full)'; then
  _PK_PAT=$(printf '%s\n' "$COMMAND" \
    | sed -nE "s/.*(^|[;&|('\"]|[[:space:]])pkill[[:space:]]+(-[a-zA-Z]*f|--full)[[:space:]]+['\"]?([^'\"[:space:]]+).*/\3/p" \
    | head -1 || true)
  if [[ -n "$_PK_PAT" ]]; then
    # Occurrences of the pattern in the command the shell will carry.
    _PK_N=$(printf '%s\n' "$COMMAND" | grep -oF -- "$_PK_PAT" | wc -l | tr -d ' ')
    # A wrapped/remote one-liner carries the pattern in the wrapper's own argv,
    # so a single textual occurrence is still a self-match there.
    _PK_WRAPPED=false
    printf '%s\n' "$COMMAND" | grep -qE '(^|[[:space:]])(ssh|bash[[:space:]]+-c|sh[[:space:]]+-c)([[:space:]]|$)' \
      && _PK_WRAPPED=true
    if [[ "${_PK_N:-0}" -ge 2 || "$_PK_WRAPPED" == true ]]; then
      gd_deny "pkill -f ${_PK_PAT} will match the command line of the shell running it, so this kills its own launcher (exit 255/144) and everything after it never runs. Fixes: put the pkill in a script file, so the pattern is not in the caller argv; anchor the pattern (\"name\\.py --flag\"); and in monitors use the bracket trick pgrep \"na[m]e\". Command: $COMMAND"
    fi
  fi
fi

# ─── Allow everything else ───────────────────────────────────────────
exit 0
