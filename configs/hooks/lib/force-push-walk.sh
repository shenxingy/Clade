#!/usr/bin/env bash
# pre-tool-guardian.sh's force-push rule: an awk walk of the command as the
# shell parses it, and the verdict the hook gives on what it finds. Sourced by
# that hook only when the command may push, which then calls gd_push_check.
# It moved here when the hook sat at 1,496 of its 1,500 lines
# (test_conventions.py), with the recursive-delete rules (rm-guard.sh). It
# reads the hook's COMMAND and HOOK_CWD and answers through its gd_deny and
# gd_rewrite, both of which exit.
#
# The hook fails closed without this file: a command that may push is
# refused, because the walk cannot run. So is one when this file defines no
# gd_push_check (an empty or stale copy).

# ─── Force push ───────────────────────────────────────────────────────
# Read as shell, not as text. The old rule was "`git push` anywhere AND
# --force/-f anywhere AND main anywhere", plus a sed over the whole string.
# Replayed over the 41 commands it fired on (2026-09-22 → 10-19), had its output
# ever been accepted it would have turned 14 `--force-with-lease` into
# `--force-with-lease-with-lease`, put `--force-with-lease` on 7 `git worktree
# remove --force` / `rm -f` statements, and corrupted 2 ref names
# (`feat/verdict-c-f-split`) — and it blocked `git push origin main && rm -f x`.
#
# The awk walks the command once, as the shell parses it, and reads only a
# statement whose command is `git [global opts] push`. There a force is
# `--force`, a short-option cluster with f (-f, -uf), a `+refspec` or --mirror;
# `--force-with-lease` / `--force-if-includes` are already safe. A ref is main
# when a refspec DESTINATION (after the last `:`, minus `+`, refs/heads/ and
# heads/) is main or master, or a glob or `:` that covers them. With no
# refspec, or HEAD, @ or a ref the shell computes, the pushed branch is the
# session's current one, unless a cd that surely ran, or `git -C`, moved it.
#
# Each rule below closes a way a statement was hidden from the walk, every one
# found allowed by both guardians on 2026-10-23 by review or by a fuzz run
# against real shells:
# - `$( … )` and backticks run, quoted or not: their statements are walked, and
#   the statement around them resumes after. A backtick ends at the next
#   unescaped backtick, whatever the quotes inside it say.
# - Arithmetic, $(( )), (( )) and $[ ], is no command, and its << is a shift:
#   read as a heredoc, `"$((1 << 20))"` hid every later line.
# - A here-string <<< is one word, never a heredoc: `read -r b <<<"$(date)";
#   git push --force origin main` was allowed.
# - A heredoc delimiter is a whole word (END-OF, \EOF). The body of an unquoted
#   one expands $( … ), so it is walked like a double-quoted string; one whose
#   delimiter never comes is read as commands, fail closed.
# - `$$` is one word, so `$$'\'` is a PID and a plain string; the readings zsh
#   and bash give `$$'` and `"$$(` instead are walked too.
# - `$"…"`, bash's translated string, is the string: `$"main"` is main.
# - `main>/dev/null` is the ref main; a `case` pattern's ) closes nothing.
# A string another shell parses (bash -c, eval, ssh's remote command, su -c,
# and every heredoc and here-string once a shell reads stdin) is walked again,
# block-only, and matched as text by facts() too. Config given to git on its
# command line (-c, --config-env, GIT_CONFIG_* in front of it) that sets an
# alias able to push, even through another alias, or a push refspec able to
# force, blocks as well.
#
# Prints: none | block<TAB>main|branch|delete|mirror|config|nested
#         | rewrite<NL><new command>
# A single-quoted literal, like the hook's GD_WAIT_AWK: read from a heredoc
# with `read -d ''`, one byte at a time, it cost every Bash call about 10 ms
# (whole-hook medians of 200 paired runs, no push: 44.2 ms vs 34.5 ms). So it
# has no single quote: "\047".
# shellcheck disable=SC2016  # awk source: its $fields are awk's, not the shell's
GD_PUSH_AWK='
# ─── verdicts, and the strings walked again
function block(code) { if (blocked == "") blocked = (wd > 0) ? "nested" : code }
function add_edit(s, e, t) { if (!ed) return; ne++; es[ne] = s; ee[ne] = e; et[ne] = t }
# enqueue — a string another shell runs, walked after this one, block-only.
function enqueue(text, mode, cdf, depth) {
  if (depth > 6) return
  nq++; qt[nq] = text; qm[nq] = mode; qc[nq] = cdf; qd[nq] = depth
}
# A heredoc body or here-string is a script once any shell here reads stdin.
# cdf is 1 when the only such shell is remote (ssh), whose branch is unknown.
function note_script(text) { ns++; scr[ns] = text; if (stdin_any) enqueue(text, "", stdin_cd, wd + 1) }
function set_stdin(cdf,   s) {
  if (stdin_any && stdin_cd <= cdf) return
  stdin_any = 1; stdin_cd = cdf
  for (s = 1; s <= ns; s++) enqueue(scr[s], "", cdf, wd + 1)
}
function nested(start, stop, cdf,   s, j) {
  s = ""
  for (j = start; j <= nt; j++) s = s " " tv[j]
  if (facts(s)) block("nested")
  s = ""
  for (j = start; j <= stop; j++) s = s ((j > start) ? " " : "") tv[j]
  enqueue(s, "", cdf, wd + 1)
}
function heredoc(body, quoted, closed) {
  if (!quoted) enqueue(body, "H", cd_seen, wd + 1)
  if (!closed) { if (facts(body)) block("nested"); enqueue(body, "", cd_seen, wd + 1); return }
  note_script(body)
}
# ─── words: ts..te in the command, tv the value with quotes removed
function start_tok() { if (!in_tok) { in_tok = 1; tok_start = i; tok_val = "" } }
function flush_tok() {
  if (!in_tok) return
  nt++; ts[nt] = tok_start; te[nt] = i - 1; tv[nt] = tok_val; in_tok = 0
  # A here-string, or a word that reads as a push, may be what a shell
  # reading stdin runs (echo "git push --all -f" | bash).
  if (tok_val ~ /^[0-9]*<<</) { sub(/^[0-9]*<<</, "", tok_val); note_script(tok_val) }
  else if (tok_val ~ /[ \t\n]/ && may_push(tok_val)) note_script(tok_val)
  # case WORD in … esac: until each pattern ends with its ), that ) closes
  # nothing, and it would have closed a $( early. cc counts the open cases
  # at this level, ip is 1 while a pattern is expected.
  if (tok_val == "in" && nt == 3 && tv[1] == "case") { cc[sn]++; ip[sn] = 1; end_seg() }
  if (tok_val == "esac" && nt == 1 && cc[sn] > 0) { cc[sn]--; ip[sn] = 0 }
}
# fd_tok — the word so far is the descriptor of a redirection (2>, {fd}>).
function fd_tok(   r) {
  if (!in_tok) return 0
  r = substr(cmd, tok_start, i - tok_start)
  return (r ~ /^[0-9]+$/ || r ~ /^\{[A-Za-z_][A-Za-z0-9_]*\}$/)
}
function arith() { return sn > 0 && (sk[sn] == "A" || sk[sn] == "[") }
# may_push(t) — the test this hook runs before the walk, for one word: "push"
# once quotes, backslashes and line continuations are gone, or an ANSI-C string.
function may_push(t,   u) { u = t; gsub(/\\\n/, "", u); gsub(/[\047"\\]/, "", u); return index(u, "push") || index(t, "$\047") }
# nocd — a cd in this statement may leave the directory of what follows
# unchanged: it runs in a subshell (a pipeline element, a background job), or
# only when something before it failed, or what follows runs only when it
# failed (||). Then the branch is still the session branch.
function end_seg() { flush_tok(); if (nt > 0 && !arith()) analyze(); nt = 0; nocd = 0 }
function cmd_pos(   k) { if (in_tok) return 0; for (k = 1; k <= nt; k++) if (!is_kw(tv[k])) return 0; return 1 }
# ─── substitutions: $( ), backticks, and arithmetic $(( )), (( )), $[ ]
# open_sub sets the statement around it aside (words, the word it is part of,
# quote, cd, parentheses); close_sub analyzes what ran inside and resumes. sp
# counts ( or [ opened inside, so only its own closes it; sbt is where the
# innermost backtick around it ends.
function open_exp(c,   nc) {
  if (c == "`") { open_sub("`", 1); return 1 }
  if (c != "$") return 0
  nc = substr(cmd, i + 1, 1)
  if (nc == "(") { if (substr(cmd, i + 2, 1) == "(" && arith_end(i + 3)) open_sub("A", 3); else open_sub("$", 2); return 1 }
  if (nc == "[") { open_sub("[", 2); return 1 }
  return 0
}
function open_sub(kind, width,   k, e) {
  start_tok()
  e = (sn > 0) ? sbt[sn] : 0
  if (kind == "`") {
    e = bt_end(i + 1)
    # With one level of backslashes removed, an escaped backtick inside runs too.
    if (index(substr(cmd, i + 1, e - i - 1), "\\")) enqueue(bt_text(substr(cmd, i + 1, e - i - 1)), "", cd_seen, wd + 1)
  }
  sn++; sk[sn] = kind; sp[sn] = 0; so[sn] = i; sq[sn] = q; snt[sn] = nt; scd[sn] = cd_seen; spd[sn] = pd; sbt[sn] = e
  cc[sn] = 0; ip[sn] = 0; snocd[sn] = nocd; nocd = 0
  for (k = 1; k <= nt; k++) { stv[sn, k] = tv[k]; sts[sn, k] = ts[k]; ste[sn, k] = te[k] }
  sst[sn] = tok_start; sval[sn] = tok_val
  nt = 0; in_tok = 0; q = ""
  i += width
}
function close_sub(width,   k) {
  end_seg()
  nt = snt[sn]
  for (k = 1; k <= nt; k++) { tv[k] = stv[sn, k]; ts[k] = sts[sn, k]; te[k] = ste[sn, k] }
  in_tok = 1; tok_start = sst[sn]; tok_val = sval[sn] substr(cmd, so[sn], i + width - so[sn])
  q = sq[sn]; cd_seen = scd[sn]; pd = spd[sn]; nocd = snocd[sn]; i += width; sn--
  if (q == "H") { in_tok = 0; nt = 0 }
}
# bt_end(p) — where the backtick substitution whose text starts at p ends.
function bt_end(p,   ch) {
  while (p <= n) { ch = substr(cmd, p, 1); if (ch == "\\") { p += 2; continue }; if (ch == "`") return p; p++ }
  return n + 1
}
function bt_text(s,   o, k, ch) {
  o = ""
  for (k = 1; k <= length(s); k++) {
    ch = substr(s, k, 1)
    if (ch == "\\" && k < length(s) && index("\\`$", substr(s, k + 1, 1))) { o = o substr(s, k + 1, 1); k++; continue }
    o = o ch
  }
  return o
}
# arith_end(p) — 1 when the (( before p closes with )), so it is arithmetic;
# 0 when its first unmatched ) stands alone, a subshell, as bash reads it.
function arith_end(p,   d, ch, e) {
  d = 0
  while (p <= n) {
    ch = substr(cmd, p, 1)
    if (ch == "\\") { p += 2; continue }
    if (ch == "\047" || ch == "\"") { e = index(substr(cmd, p + 1), ch); if (!e) return 0; p += e + 1; continue }
    if (ch == "(") d++
    else if (ch == ")") { if (d == 0) return substr(cmd, p + 1, 1) == ")"; d-- }
    p++
  }
  return 0
}
# ansi() — the escape at i inside an ANSI-C string, decoded, and i moved past it.
function ansi(   ch, v, k, d, w) {
  ch = substr(cmd, i, 1)
  if (ch == "x" || ch == "u" || ch == "U") {
    w = (ch == "x") ? 2 : ((ch == "u") ? 4 : 8)
    v = 0; k = 0
    while (k < w && (d = substr(cmd, i + 1 + k, 1)) ~ /^[0-9A-Fa-f]$/) { v = v * 16 + index("0123456789abcdef", tolower(d)) - 1; k++ }
    if (k == 0) { i++; return "\\" ch }
    i += 1 + k; return (v > 0 && v < 128) ? sprintf("%c", v) : "?"
  }
  if (ch ~ /^[0-7]$/) {
    v = 0; k = 0
    while (k < 3 && (d = substr(cmd, i + k, 1)) ~ /^[0-7]$/) { v = v * 8 + d; k++ }
    i += k; return (v > 0 && v < 128) ? sprintf("%c", v) : "?"
  }
  i++
  if (ch == "n") return "\n"
  if (ch == "t") return "\t"
  if (index("abeEfvr", ch)) return "\001"
  return ch
}
# ─── redirections and heredocs
# hd_word(j) — the heredoc delimiter at j, as the shell reads it: a whole
# word, quotes and backslashes removed, quoted if any part was. Sets hdw and
# hdq; returns where the word ends.
function hd_word(j,   ch, e) {
  hdw = ""; hdq = 0
  while (j <= n) {
    ch = substr(cmd, j, 1)
    if (index(" \t\n;&|<>()", ch)) break
    if (ch == "\\") { hdq = 1; hdw = hdw substr(cmd, j + 1, 1); j += 2; continue }
    if (ch == "\047" || ch == "\"") {
      hdq = 1; e = index(substr(cmd, j + 1), ch)
      if (!e) { hdw = hdw substr(cmd, j + 1); return n + 1 }
      hdw = hdw substr(cmd, j + 1, e - 1); j += e + 1; continue
    }
    hdw = hdw ch; j++
  }
  return j
}
# redirect — at an unquoted < or >, which ends a word unless the word is the
# redirection (>>, 2>&1) or its descriptor (2>, {fd}>). A heredoc registers
# its delimiter; its body is read at the end of the line.
function redirect(   j, strip) {
  if (arith()) return 0
  if (in_tok && !fd_tok() && tok_val !~ /^[0-9]*[<>]+&?$/ && tok_val !~ /^&>>?$/) flush_tok()
  if (substr(cmd, i, 3) == "<<<") {
    start_tok(); tok_val = tok_val "<<<"; i += 3
    while (i <= n && (substr(cmd, i, 1) == " " || substr(cmd, i, 1) == "\t")) i++
    return 1
  }
  if (substr(cmd, i, 2) == "<<") {
    in_tok = 0
    j = i + 2; strip = 0
    if (substr(cmd, j, 1) == "-") { strip = 1; j++ }
    while (substr(cmd, j, 1) == " " || substr(cmd, j, 1) == "\t") j++
    j = hd_word(j)
    if (hdw != "" || hdq) { hd_n++; hd_delim[hd_n] = hdw; hd_strip[hd_n] = strip; hd_q[hd_n] = hdq }
    i = j; return 1
  }
  return 0
}
# redir(v) — the words a redirection takes: 0 when v is none, 1 when its
# target is in the word (2>/dev/null, <file, a here-string <<<word), 2 when
# the target is the next word (`> log`).
function redir(v) {
  if (v !~ /^[0-9]*[<>]/ && v !~ /^&>/) return 0
  return (v ~ /^[0-9]*[<>]+&?$/ || v ~ /^&>>?$/) ? 2 : 1
}
# ─── reading a push
function dst_of(r,   p) {
  while ((p = index(r, ":")) > 0) r = substr(r, p + 1)
  sub(/^refs\/heads\//, "", r); sub(/^heads\//, "", r)
  return r
}
# glob_main(d) — a refspec glob (one *) whose matches include main or master.
function glob_main(d,   p, pre, suf, t, k, T) {
  if (!(p = index(d, "*"))) return 0
  pre = substr(d, 1, p - 1); suf = substr(d, p + 1)
  split("refs/heads/main refs/heads/master heads/main heads/master main master", T, " ")
  for (k = 1; k <= 6; k++) {
    t = T[k]
    if (length(t) >= length(pre) + length(suf) && substr(t, 1, length(pre)) == pre &&
        substr(t, length(t) - length(suf) + 1) == suf) return 1
  }
  return 0
}
# facts(text) — a force push (or delete) of main, read from TEXT as it stands
# and again with its quotes and backslashes removed (git pu""sh): a second
# check beside the walk of a string another shell runs, block only.
function facts(text,   n, parts, j, p, t, pass) {
  for (pass = 1; pass <= 2; pass++) {
    t = text
    if (pass == 2) gsub(/[\047"\\]/, "", t)
    n = split(t, parts, /[;&|\n]/)
    for (j = 1; j <= n; j++) {
      p = " " parts[j] " "
      if (p ~ /[ \t\047"(`]git[ \t]+([^ \t]+[ \t]+)*push[ \t]/ &&
          (p ~ /[ \t](--force|--force-with-lease[^ \t]*|--mirror|--delete|-[A-Za-z]*[fd][A-Za-z]*)[ \t\047"]/ ||
           p ~ /[ \t][+:][^ \t]/) &&
          p ~ /[ \t:+\/\047"](main|master)([ \t\047")`]|\\)/) return 1
    }
  }
  return 0
}
function is_shell(w) { return (w == "bash" || w == "sh" || w == "zsh" || w == "dash" || w == "ksh") }
function is_kw(w) {
  return (w == "{" || w == "}" || w == "!" || w == "if" || w == "then" || w == "elif" || w == "else" ||
          w == "fi" || w == "for" || w == "while" || w == "until" || w == "do" || w == "done" || w == "time")
}
# A shell given -c runs its next argument; given a script file it runs that
# file, which is not in the command (returns 0: the statement is read on);
# given neither (or -s) it reads its script from stdin — `echo … | bash`,
# `bash <<EOF`, `bash 2>&1 <<<"…"`: a redirection is no script file.
function analyze_shell(k,   j, v, r) {
  for (j = k + 1; j <= nt; j++) {
    v = tv[j]
    if ((r = redir(v)) > 0) { j += r - 1; continue }
    if (v == "-c" || (v ~ /^-[A-Za-z]+$/ && index(v, "c") > 0)) { nested(j + 1, j + 1, cd_seen); return 1 }
    if (v == "-s") { set_stdin(cd_seen); return 1 }
    if (v == "-o" || v == "+o" || v == "-O" || v == "+O" || v == "--rcfile" || v == "--init-file") { j++; continue }
    if (v ~ /^[-+]/) continue
    return 0
  }
  set_stdin(cd_seen); return 1
}
# ssh [options] host [command…]: the remote command is what follows the host,
# less its redirections, run on another machine (so its branch is unknown).
# With no command, ssh runs a shell that reads stdin.
function analyze_ssh(k,   j, v, m, r) {
  for (j = k + 1; j <= nt; j++) {
    v = tv[j]
    if (v ~ /^-[BbcDEeFIiJLlmOopQRSWw]$/) { j++; continue }
    if (v ~ /^-/) continue
    break
  }
  if (j > nt) return 0
  m = j + 1
  while (m <= nt && (r = redir(tv[m])) > 0) m += r
  if (m > nt) { set_stdin(1); return 1 }
  nested(j + 1, nt, 1); return 1
}
# su [opts] [user] -c cmd runs cmd through a shell; without -c it is a shell
# reading stdin. So is sudo (or doas) -s / -i with no command after it.
function analyze_su(k,   j) {
  for (j = k + 1; j <= nt; j++) {
    if (tv[j] == "-c" || tv[j] == "--command" || (tv[j] ~ /^-[A-Za-z]+$/ && index(tv[j], "c") > 0)) { nested(j + 1, j + 1, cd_seen); return }
    if (tv[j] ~ /^--command=/) { tv[j] = substr(tv[j], 11); nested(j, j, cd_seen); return }
  }
  set_stdin(cd_seen)
}
function analyze_sudo(k,   j, v, r, sh) {
  sh = 0
  for (j = k + 1; j <= nt; j++) {
    v = tv[j]
    if ((r = redir(v)) > 0) { j += r - 1; continue }
    if (v ~ /^-[ugCDhprtUT]$/) { j++; continue }
    if (v == "--shell" || v == "--login" || (v ~ /^-[A-Za-z]+$/ && (index(v, "s") || index(v, "i")))) { sh = 1; continue }
    if (v ~ /^-/) continue
    return 0
  }
  if (sh) set_stdin(cd_seen)
  return sh
}
# analyze — one statement. The command can sit behind any prefix (timeout 60,
# sudo -u bob, nice -n 19, xargs -I{}, env -C dir, then, do, {), and listing
# prefixes was how the first cut of this walk let `timeout 120 git push --force
# origin main` through. So each word is read in turn, and git, a shell, ssh,
# su, sudo or eval decides — unless it is not the command after all (the git
# of `sudo -u git git push`, a shell given a script file). An assignment
# (SHELL=/bin/bash) or an option is never the command. A bare `git` argument
# to echo is read too; that errs toward checking, never toward skipping.
function analyze(   k, w) {
  k = 1
  while (k <= nt && (tv[k] ~ /^[A-Za-z_][A-Za-z0-9_]*=/ || is_kw(tv[k]))) k++
  if (k <= nt) { w = tv[k]; sub(/.*\//, "", w); if (w == "cd" || w == "pushd" || w == "popd") { if (!nocd) cd_seen = 1; return } }
  for (; k <= nt; k++) {
    w = tv[k]
    if (w ~ /^[A-Za-z_][A-Za-z0-9_]*=/ || w ~ /^-/) continue
    sub(/.*\//, "", w)
    if (w == "git") { if (analyze_git(k)) return }
    else if (is_shell(w)) { if (analyze_shell(k)) return }
    else if (w == "ssh") { if (analyze_ssh(k)) return }
    else if (w == "su" || w == "runuser") { analyze_su(k); return }
    else if (w == "sudo" || w == "doas") { if (analyze_sudo(k)) return }
    else if (w == "eval") { nested(k + 1, nt, cd_seen); return }
  }
}
# add_cfg — one config setting (key=value) on the command line of git;
# --config-env names a variable, so its value is unknown ("?").
function add_cfg(r, how,   p) {
  p = index(r, "="); ncf++
  ck[ncf] = tolower(p ? substr(r, 1, p - 1) : r); cv[ncf] = (how != "-c") ? "?" : (p ? substr(r, p + 1) : "")
}
# analyze_git — 1 when this git is the command (a push, or an alias given on
# its command line); 0 when it is not, so the statement is read on.
function analyze_git(k,   hasC, j, v, skipnext, dd, npos, nf, np, lease, allrefs, mirror, nrefs, mainref, del, headref, subref, r, d, plus, raw, newv, pk, rd, p, ex, gv) {
  # GIT_CONFIG_KEY_n/VALUE_n and GIT_CONFIG_PARAMETERS assigned in front of
  # git are config on its command line too, read as -c is.
  ncf = 0; split("", gv)
  for (j = 1; j < k; j++) {
    v = tv[j]
    if (v ~ /^GIT_CONFIG_(KEY|VALUE)_[0-9]+=/) { p = index(v, "="); gv[substr(v, 12, p - 12)] = substr(v, p + 1) }
    else if (v ~ /^GIT_CONFIG_PARAMETERS=/) { r = substr(v, 23); while (match(r, /\047[^\047]*\047/)) { add_cfg(substr(r, RSTART + 1, RLENGTH - 2), "-c"); r = substr(r, RSTART + RLENGTH) } }
  }
  for (v in gv) if (v ~ /^KEY_/) add_cfg(gv[v] "=" ((("VALUE_" substr(v, 5)) in gv) ? gv["VALUE_" substr(v, 5)] : ""), "-c")
  k++; hasC = 0
  while (k <= nt) {
    v = tv[k]
    if (v == "-c" || v == "--config-env" || v ~ /^--config-env=/) {
      if (v ~ /^--config-env=/) { r = substr(v, 14); k++ } else { r = tv[k + 1]; k += 2 }
      add_cfg(r, v); continue
    }
    if (v == "-C" || v == "--git-dir" || v == "--work-tree" || v == "--namespace") { hasC = 1; k += 2; continue }
    if (v ~ /^--(git-dir|work-tree)=/) { hasC = 1; k++; continue }
    if (v ~ /^-/) { k++; continue }
    break
  }
  if (k > nt) return 0
  ex = 0
  if (tv[k] != "push") {
    # git follows a chain of aliases, so this one may push through another:
    # when it is given with -c, any -c alias that pushes blocks.
    for (j = 1; j <= ncf; j++) if (ck[j] == "alias." tolower(tv[k])) for (r = 1; r <= ncf; r++)
      if (ck[r] ~ /^alias\./ && (cv[r] ~ /push/ || cv[r] == "?")) { block("config"); return 1 }
    # A subcommand the shell computes ($(echo push), ${x}push) may be push:
    # it is read as one, and never rewritten.
    raw = substr(cmd, ts[k], te[k] - ts[k] + 1)
    if (!index(raw, "$") && !index(raw, "`")) return 0
    ex = 1
  }
  pk = k
  skipnext = 0; dd = 0; npos = 0; nf = 0; np = 0; lease = 0; allrefs = 0; mirror = 0; nrefs = 0; mainref = 0; del = 0; headref = 0; subref = 0
  for (j = pk + 1; j <= nt; j++) {
    v = tv[j]
    if (skipnext) { skipnext = 0; continue }
    if ((rd = redir(v)) > 0) { skipnext = (rd == 2); continue }
    if (!dd && v == "--") { dd = 1; continue }
    if (!dd && v ~ /^--/) {
      if (v == "--force") { nf++; FI[nf] = j }
      else if (v ~ /^--force-with-lease/ || v == "--force-if-includes") lease = 1
      else if (v == "--mirror") mirror = 1
      else if (v == "--all" || v == "--branches") allrefs = 1
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
    d = dst_of(r)
    if (d == "main" || d == "master" || glob_main(d) || r == ":") {
      mainref = 1
      if (substr(r, 1, 1) == ":" && r != ":") del = 1
    }
    # HEAD and @ name the current branch, which the text does not; so, most
    # likely, does a ref the shell computes (git push -f origin "$(git branch
    # --show-current)"), and that one is the session branch even after a cd
    # or over ssh, where a substitution outside single quotes runs here.
    if (d == "HEAD" || d == "@") headref = 1
    raw = substr(cmd, ts[j], te[j] - ts[j] + 1)
    if (index(raw, "$(") || index(raw, "`")) subref = 1
    if (plus) { np++; PI[np] = j }
  }
  if (mirror) { block("mirror"); return 1 }
  if (del && mainref) { block("delete"); return 1 }
  # A refspec, mirror or push.default given with -c decides what a push with
  # no refspec sends, and a + in it forces: neither is in the arguments.
  if (nrefs == 0) for (j = 1; j <= ncf; j++)
    if ((ck[j] ~ /^remote\..+\.push$/ && (nf || np || lease || cv[j] ~ /^\+/ || cv[j] == "?")) ||
        (ck[j] ~ /^remote\..+\.mirror$/ && cv[j] != "false") ||
        (ck[j] == "push.default" && (cv[j] == "matching" || cv[j] == "?") && (nf || np || lease))) { block("config"); return 1 }
  if (nf == 0 && np == 0 && !lease) return 1
  if (mainref || (allrefs && (nf > 0 || np > 0 || lease))) { block("main"); return 1 }
  if ((((nrefs == 0 || headref) && !allrefs && !cd_seen && !hasC) || subref) &&
      (ENVIRON["GD_BRANCH"] == "main" || ENVIRON["GD_BRANCH"] == "master")) { block("branch"); return 1 }
  if (nf == 0 && np == 0 || ex) return 1
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
  return 1
}
# ─── the walk
# walk(text, mode, depth, cd0, edit) — one string: the command (depth 0), or
# one queued string another shell runs. mode "H" is the body of a heredoc with
# an unquoted delimiter: text, except for what the shell expands in it.
function walk(text, mode, depth, cd0, edit,   c, h, b0, found, closes, e, line, ls, lt) {
  cmd = text; n = length(cmd); i = 1; q = mode; in_tok = 0; nt = 0; hd_n = 0; sn = 0; pd = 0; cc[0] = 0; ip[0] = 0; nocd = 0
  cd_seen = cd0; wd = depth; ed = edit
  while (i <= n) {
    c = substr(cmd, i, 1)
    if (sn > 0 && sbt[sn] > 0 && i >= sbt[sn]) { while (sk[sn] != "`") close_sub(0); close_sub(1); continue }
    if (q == "\047") { if (c == "\047") q = ""; else tok_val = tok_val c; i++; continue }
    if (q == "$") {
      if (c == "\\" && i < n) { i++; tok_val = tok_val ansi(); continue }
      if (c == "\047") q = ""; else tok_val = tok_val c
      i++; continue
    }
    if (q == "\"") {
      if (c == "\\" && i < n) {
        nc = substr(cmd, i + 1, 1)
        if (nc == "\\" || nc == "\"" || nc == "$" || nc == "`") { tok_val = tok_val nc; i += 2; continue }
      }
      if (substr(cmd, i, 2) == "$$") { tok_val = tok_val "$$"; i += 2; continue }
      if (open_exp(c)) continue
      if (c == "\"") q = ""; else tok_val = tok_val c
      i++; continue
    }
    if (q == "H") {
      if (c == "\\" && i < n && index("$`\\\n", substr(cmd, i + 1, 1))) { i += 2; continue }
      if (substr(cmd, i, 2) == "$$") { i += 2; continue }
      if (!open_exp(c)) i++
      continue
    }
    if (c == "\\") {
      if (i < n && substr(cmd, i + 1, 1) == "\n") { i += 2; continue }
      start_tok(); if (i < n) tok_val = tok_val substr(cmd, i + 1, 1); i += 2; continue
    }
    if (substr(cmd, i, 2) == "$$") { start_tok(); tok_val = tok_val "$$"; i += 2; continue }
    if (substr(cmd, i, 2) == "$\047") { start_tok(); q = "$"; i += 2; continue }
    if (substr(cmd, i, 2) == "$\"") { start_tok(); q = "\""; i += 2; continue }
    if (c == "\047" || c == "\"") { start_tok(); q = c; i++; continue }
    if (c == " " || c == "\t") { flush_tok(); i++; continue }
    if (c == "#" && !in_tok) { while (i <= n && substr(cmd, i, 1) != "\n") i++; continue }
    if (c == "\n") {
      end_seg(); i++
      for (h = 1; h <= hd_n; h++) {
        b0 = i; found = 0; closes = 0; ls = i
        while (i <= n) {
          e = index(substr(cmd, i), "\n")
          line = (e > 0) ? substr(cmd, i, e - 1) : substr(cmd, i)
          ls = i; i = (e > 0) ? i + e : n + 1
          lt = 0
          if (hd_strip[h]) while (substr(line, lt + 1, 1) == "\t") lt++
          line = substr(line, lt + 1)
          if (line == hd_delim[h]) { found = 1; break }
          # Inside $( ), bash 5.2 also ends a heredoc at a line that only
          # starts with its delimiter, when that line holds a ), and runs the
          # rest of the line: `EOF x; git push …)` runs the push.
          if (sn > 0 && sk[sn] == "$" && hd_delim[h] != "" && index(line, ")") &&
              substr(line, 1, length(hd_delim[h])) == hd_delim[h]) {
            found = 1; closes = 1; i = ls + lt + length(hd_delim[h]); break
          }
        }
        heredoc(substr(cmd, b0, (found ? ls : i) - b0), hd_q[h], found)
        if (closes) break
      }
      hd_n = 0
      continue
    }
    if (open_exp(c)) continue
    if (c == "(" && substr(cmd, i + 1, 1) == "(" && cmd_pos() && arith_end(i + 2)) { open_sub("A", 2); continue }
    if (c == "(" && ip[sn] && !in_tok && nt == 0) { i++; continue }
    if (c == "(") { if (sn > 0) sp[sn]++; end_seg(); pd++; pcd[pd] = cd_seen; i++; continue }
    if (c == ")") {
      flush_tok()
      if (ip[sn]) { end_seg(); ip[sn] = 0; i++; continue }
      if (sn > 0 && sp[sn] == 0 && sk[sn] == "$") { close_sub(1); continue }
      if (sn > 0 && sp[sn] == 0 && sk[sn] == "A") { close_sub((substr(cmd, i + 1, 1) == ")") ? 2 : 1); continue }
      if (sn > 0 && sp[sn] > 0) sp[sn]--
      end_seg()
      if (pd > ((sn > 0) ? spd[sn] : 0)) { cd_seen = pcd[pd]; pd-- }
      i++; continue
    }
    if (sn > 0 && sk[sn] == "[") {
      if (c == "[") sp[sn]++
      else if (c == "]") { if (sp[sn] == 0) { close_sub(1); continue }; sp[sn]-- }
    }
    if (c == ";") {
      end_seg()
      if (substr(cmd, i + 1, 1) == ";" || substr(cmd, i + 1, 1) == "&") {
        if (cc[sn] > 0) ip[sn] = 1
        i += (substr(cmd, i, 3) == ";;&") ? 3 : 2; continue
      }
      i++; continue
    }
    if (c == "|") {
      nocd = 1; end_seg(); nocd = 1
      i += (substr(cmd, i + 1, 1) == "|" || substr(cmd, i + 1, 1) == "&") ? 2 : 1; continue
    }
    if (c == "&") {
      if (i > 1 && (substr(cmd, i - 1, 1) == ">" || substr(cmd, i - 1, 1) == "<")) { start_tok(); tok_val = tok_val c; i++; continue }
      if (substr(cmd, i + 1, 1) == ">") { flush_tok(); start_tok(); tok_val = tok_val c; i++; continue }
      if (substr(cmd, i + 1, 1) == "&") { end_seg(); i += 2; continue }
      nocd = 1; end_seg(); i++; continue
    }
    if ((c == "<" || c == ">") && redirect()) continue
    start_tok(); tok_val = tok_val c; i++
  }
  while (sn > 0) close_sub(0)
  end_seg()
}
{ cmd = (NR == 1) ? $0 : cmd RS $0 }
END {
  top = cmd; blocked = ""; ne = 0; ns = 0; nq = 0; stdin_any = 0; stdin_cd = 1
  walk(top, "", 0, 0, 1)
  # $$ is one word to bash and dash, but zsh reads $$ before an ANSI-C string
  # as $ and then the string, and bash parses "$$(" as $ and $(: that other
  # reading is walked too, block-only.
  if (top ~ /\$\$[\047(]/) { alt = top; gsub(/\$\$\047/, "_$\047", alt); gsub(/\$\$\(/, "_$(", alt); enqueue(alt, "", 0, 0) }
  for (qi = 1; qi <= nq && blocked == ""; qi++) walk(qt[qi], qm[qi], qd[qi], qc[qi], 0)
  if (stdin_any && facts(top)) block("nested")
  if (blocked != "") { print "block\t" blocked; exit }
  if (ne == 0) { print "none"; exit }
  for (a = 2; a <= ne; a++) {
    s0 = es[a]; e0 = ee[a]; t0 = et[a]; b = a - 1
    while (b >= 1 && es[b] < s0) { es[b + 1] = es[b]; ee[b + 1] = ee[b]; et[b + 1] = et[b]; b-- }
    es[b + 1] = s0; ee[b + 1] = e0; et[b + 1] = t0
  }
  out = top
  for (a = 1; a <= ne; a++) out = substr(out, 1, es[a] - 1) et[a] substr(out, ee[a] + 1)
  print "rewrite"; printf "%s", out
}'

# gd_push_check — walk $COMMAND, and refuse or rewrite on what the walk prints.
gd_push_check() {
  GD_BRANCH=$(git -C "${HOOK_CWD:-$PWD}" symbolic-ref --short -q HEAD 2>/dev/null || true)
  _gp=$(printf '%s' "$COMMAND" | GD_BRANCH="$GD_BRANCH" LC_ALL=C awk 'BEGIN { RS = "\001" } '"$GD_PUSH_AWK" 2>/dev/null || true)
  case "$_gp" in
    block*)
      case "$_gp" in
        *branch) _why="it pushes the current branch, which is ${GD_BRANCH}" ;;
        *delete) _why="it deletes main/master on the remote" ;;
        *mirror) _why="--mirror force-updates every ref on the remote, main/master included" ;;
        *config) _why="git -c or GIT_CONFIG_* sets an alias or a push setting on its command line that forces the push" ;;
        *nested) _why="a wrapped or piped shell command (ssh, bash -c, eval, … | bash) force-pushes main/master" ;;
        *)       _why="it names main/master" ;;
      esac
      gd_deny "Force push to main/master blocked: ${_why}. This destroys shared history. Use --force-with-lease on a feature branch, or ask the user explicitly. Command: $COMMAND"
      ;;
    rewrite*)
      gd_rewrite "${_gp#rewrite$'\n'}" "pre-tool-guardian rewrote a force push to --force-with-lease, which refuses to overwrite the remote branch if someone else updated it since your last fetch. Only the git push statement changed."
      ;;
  esac
  return 0
}
