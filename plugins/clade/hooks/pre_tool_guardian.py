#!/usr/bin/env python3
"""Codex-native destructive-command guard for Clade."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


MIGRATIONS = (
    "db:push", "db:migrate", "prisma migrate", "drizzle-kit push",
    "alembic upgrade", "alembic downgrade", "rake db:migrate",
    "rake db:rollback", "knex migrate:latest", "knex migrate:rollback",
    "sequelize db:migrate", "flyway migrate", "liquibase update",
)


def _deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _rewrite(command: str) -> dict:
    # Codex's contract, not Claude Code's: Codex 0.163 rejects updatedInput
    # unless it comes with permissionDecision "allow" ("PreToolUse hook returned
    # updatedInput without permissionDecision:allow"). The Claude Code guardian
    # must NOT send "allow" — there it also bypasses permission prompts and deny
    # rules — so the two hooks agree on the verdict and differ on the wire.
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": {"command": command},
        }
    }


# Kept deliberately in step with configs/hooks/pre-tool-guardian.sh.
# configs/codex-migration.json records the two as a parity pair, and
# tests/test-pre-tool-guardian.sh now feeds one command to both hooks and fails
# when their verdicts differ — which is how the drift below was found. Until
# 2026-09-05 this mirror matched only /, ~ and $HOME, so it allowed a recursive
# delete of /home, /etc, /usr, /var, /sys, /proc and /boot that the shell hook
# blocked; and it split on LINES where the shell splits on statements, so a
# home path merely sharing a line with a benign delete read differently here.
_DANGEROUS_TILDE = r"(?:^|[\s=])~[A-Za-z0-9._-]*(?:/|\s|$)"
_DANGEROUS_NAMED = (
    r"(?:" + _DANGEROUS_TILDE + r"|\$\{?HOME\}?"
    r"|(?:/home|/etc|/usr|/var|/sys|/proc|/boot)\b)"
)
_DANGEROUS_ROOT = r"(?:^|\s)/(?:\s|$|\*)"

# Names the shell always provides, so requiring them proves nothing. HOME is
# on this list and is also caught by _DANGEROUS_NAMED; that block wins.
_SHELL_OWNED = frozenset(
    {"HOME", "PWD", "OLDPWD", "TMPDIR", "XDG_RUNTIME_DIR", "CLAUDE_PROJECT_DIR"}
)


def _statements(command: str) -> list[str]:
    """Split the way the shell hook does — on ; | & — not on newlines.

    Per-line matching was too coarse in both directions; the reasoning is
    recorded at length in pre-tool-guardian.sh. Matching per statement means
    every condition has to be met by the same statement.
    """
    return re.split(r"[;|&\n]", command)


def _recursive_force(statement: str) -> bool:
    """Read -r and -f from the OPTION tokens of an rm statement, never operands.

    This used to test the whole statement for ``-[a-zA-Z]*r`` and
    ``-[a-zA-Z]*f``, so any hyphen inside a FILENAME supplied the flags.
    Reproduced 2026-09-07: a plain ``rm -f`` on a path under /home whose
    basename contains a hyphen, letters and an r was blocked as a catastrophic
    recursive delete with no -r in the command at all.

    It is the over-blocking mirror of the under-blocking fixed on 2026-09-05,
    and one root cause serves both: matching command TEXT instead of
    classifying tokens. A token supplies flags only when it starts with ``-``,
    and after a ``--`` nothing does. GNU rm permutes, so an option may follow
    an operand — what an operand may never do is BE one.
    """
    recursive = force = False
    end_of_options = False
    after = re.sub(r"^.*\brm\b", "", statement, count=1)
    for token in after.split():
        if token == "--":
            end_of_options = True
            continue
        if end_of_options or not token.startswith("-") or token == "-":
            continue
        if token.startswith("--"):
            name = token.split("=", 1)[0]
            if name == "--recursive":
                recursive = True
            elif name == "--force":
                force = True
            continue
        if "r" in token:
            recursive = True
        if "f" in token:
            force = True
    return recursive and force


def _delete_targets(statement: str) -> list[str]:
    after = re.sub(r"^.*\brm\b", "", statement, count=1)
    return [token for token in after.split() if not token.startswith("-")]


def _unresolved_delete(command: str) -> tuple[str, str] | None:
    """A recursive delete whose target this guardian cannot resolve.

    Returns ("refuse", why) when nothing can be made safe — a command
    substitution or a bare glob is decided at run time and offers no name to
    require — or ("rewrite", name) when there is a name to make required.

    The danger is the shell lifecycle rather than the text: each Bash tool call
    is a fresh shell, so a variable assigned in an earlier call is unset in this
    one and the target expands to the filesystem root.
    """
    # A delete written inside a single-quoted string is text, not a command,
    # and rewriting it would corrupt the string it sits in.
    head = re.split(r"\brm\b", command, maxsplit=1)[0]
    if head.count("'") % 2 == 1:
        return None

    for statement in _statements(command):
        if not _recursive_force(statement):
            continue
        for token in _delete_targets(statement):
            bare = token.replace('"', "")
            if "$(" in bare or "`" in bare:
                return ("refuse", "a command substitution decides the target at run time")
            if re.fullmatch(r"\.?/?\*+|\.|\./", bare):
                return (
                    "refuse",
                    "a bare glob resolves against whatever the working "
                    "directory happens to be",
                )
            match = re.match(r"^\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", bare)
            if not match:
                continue
            name = match.group(1)
            if name in _SHELL_OWNED:
                continue
            # Assigned in this same command, so this shell will have it.
            if re.search(rf"(?:^|[\s;&|(])(?:export\s+)?{re.escape(name)}=", command):
                continue
            return ("rewrite", name)
    return None


# ─── Force push ──────────────────────────────────────────────────────────
# Same walk as the awk in configs/hooks/pre-tool-guardian.sh, step for step;
# the reasoning is recorded there. Positions count from 0 here and from 1
# there. Quotes ('…', "…", $"…", and $'…' with its escapes decoded),
# backslashes, comments and heredocs are honoured; statements split on
# ; & | ( ) and newlines, but not on the & of 2>&1; a command substitution
# is walked as statements of its own while the statement around it resumes
# after it; arithmetic is never a command; a string another shell runs
# (bash -c, eval, ssh, su -c, a heredoc that expands or feeds a shell) is
# walked again, block-only; only a `git [global opts] push` statement is read.
_SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
_KEYWORDS = frozenset({"{", "}", "!", "if", "then", "elif", "else", "fi",
                       "for", "while", "until", "do", "done", "time"})
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_MAIN_REFS = ("refs/heads/main", "refs/heads/master", "heads/main", "heads/master", "main", "master")
_MAX_DEPTH = 6


def _redirect_words(word: str) -> int:
    """The words a redirection takes: 0 when `word` is none, 1 when its target
    is in the word (2>/dev/null, <file, a here-string <<<word), 2 when the
    target is the next word (`> log`)."""
    if not (re.match(r"^[0-9]*[<>]", word) or word.startswith("&>")):
        return 0
    return 2 if re.match(r"^[0-9]*[<>]+&?$", word) or re.match(r"^&>>?$", word) else 1


def _may_push(command: str) -> bool:
    """Whether the walk has anything to read: "push" once quotes, backslashes
    and line continuations are gone (git pu""sh is a push), or a $'…' string,
    whose escapes can spell it."""
    return "push" in re.sub(r"[\\'\"]", "", command.replace("\\\n", "")) or "$'" in command


def _dst(ref: str) -> str:
    ref = re.sub(r"^refs/heads/", "", ref.rsplit(":", 1)[-1])
    return re.sub(r"^heads/", "", ref)


def _glob_main(dst: str) -> bool:
    """A refspec glob (one *) whose matches include main or master."""
    if "*" not in dst:
        return False
    pre, _, suf = dst.partition("*")
    return any(len(t) >= len(pre) + len(suf) and t.startswith(pre) and t.endswith(suf)
               for t in _MAIN_REFS)


def _facts(text: str) -> bool:
    """A force push (or delete) of main, read from TEXT as it stands and again
    with its quotes and backslashes removed: a second check beside the walk of
    a string another shell runs, block only."""
    for t in (text, re.sub(r"[\\'\"]", "", text)):
        for part in re.split(r"[;&|\n]", t):
            p = " " + part + " "
            if (re.search(r"[ \t'\"(`]git[ \t]+(?:[^ \t]+[ \t]+)*?push[ \t]", p)
                    and (re.search(r"[ \t](?:--force|--force-with-lease[^ \t]*|--mirror|--delete"
                                   r"|-[A-Za-z]*[fd][A-Za-z]*)[ \t'\"]", p)
                         or re.search(r"[ \t][+:][^ \t]", p))
                    and re.search(r"[ \t:+/'\"](?:main|master)(?:[ \t'\")`]|\\)", p)):
                return True
    return False


def _ansi(cmd: str, i: int) -> tuple[str, int]:
    """The escape at cmd[i] inside $'…', decoded, and where it ends."""
    ch = cmd[i]
    if ch in "xuU":
        m = re.match(r"[0-9A-Fa-f]{1,%d}" % {"x": 2, "u": 4, "U": 8}[ch], cmd[i + 1:])
        if not m:
            return "\\" + ch, i + 1
        v = int(m.group(0), 16)
        return (chr(v) if 0 < v < 128 else "?"), i + 1 + len(m.group(0))
    m = re.match(r"[0-7]{1,3}", cmd[i:])
    if m:
        v = int(m.group(0), 8)
        return (chr(v) if 0 < v < 128 else "?"), i + len(m.group(0))
    if ch == "n":
        return "\n", i + 1
    if ch == "t":
        return "\t", i + 1
    if ch in "abeEfvr":
        return "\x01", i + 1
    return ch, i + 1


def _bt_end(cmd: str, p: int) -> int:
    """Where the backtick substitution whose text starts at p ends."""
    while p < len(cmd):
        if cmd[p] == "\\":
            p += 2
            continue
        if cmd[p] == "`":
            return p
        p += 1
    return len(cmd)


def _arith_end(cmd: str, p: int) -> bool:
    """Whether the (( before p closes with )), so it is arithmetic."""
    depth = 0
    while p < len(cmd):
        ch = cmd[p]
        if ch == "\\":
            p += 2
            continue
        if ch in "'\"":
            e = cmd.find(ch, p + 1)
            if e < 0:
                return False
            p = e + 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                return cmd[p + 1:p + 2] == ")"
            depth -= 1
        p += 1
    return False


def _hd_word(cmd: str, j: int) -> tuple[str, bool, int]:
    """The heredoc delimiter at j: (word, quoted, end)."""
    word, quoted = "", False
    while j < len(cmd):
        ch = cmd[j]
        if ch in " \t\n;&|<>()":
            break
        if ch == "\\":
            quoted = True
            word += cmd[j + 1:j + 2]
            j += 2
            continue
        if ch in "'\"":
            quoted = True
            e = cmd.find(ch, j + 1)
            if e < 0:
                return word + cmd[j + 1:], True, len(cmd)
            word += cmd[j + 1:e]
            j = e + 1
            continue
        word += ch
        j += 1
    return word, quoted, j


class _PushWalk:
    """One command's force-push verdict: the awk's walk, its state as attributes."""

    def __init__(self, branch: str) -> None:
        self.branch = branch
        self.blocked = ""
        self.edits: list[tuple[int, int, str]] = []
        self.scripts: list[str] = []
        self.queue: list[tuple[str, str, bool, int]] = []
        self.stdin_any = False
        self.stdin_cd = True
        self.depth = 0

    def run(self, command: str) -> None:
        self.walk(command, "", 0, False, True)
        # The other reading of $$, block-only (see the awk).
        if re.search(r"\$\$['(]", command):
            self.enqueue(re.sub(r"\$\$(?=['(])", "_$", command), "", False, 0)
        k = 0
        while k < len(self.queue) and not self.blocked:
            text, mode, cd, depth = self.queue[k]
            self.walk(text, mode, depth, cd, False)
            k += 1
        if self.stdin_any and _facts(command):
            self.block("nested")

    # ─ verdicts, and the strings walked again
    def block(self, code: str) -> None:
        if not self.blocked:
            self.blocked = "nested" if self.depth > 0 else code

    def add_edit(self, start: int, end: int, text: str) -> None:
        if self.edits_on:
            self.edits.append((start, end, text))

    def enqueue(self, text: str, mode: str, cd: bool, depth: int) -> None:
        if depth <= _MAX_DEPTH:
            self.queue.append((text, mode, cd, depth))

    def note_script(self, text: str) -> None:
        self.scripts.append(text)
        if self.stdin_any:
            self.enqueue(text, "", self.stdin_cd, self.depth + 1)

    def set_stdin(self, cd: bool) -> None:
        if self.stdin_any and self.stdin_cd <= cd:
            return
        self.stdin_any, self.stdin_cd = True, cd
        for text in self.scripts:
            self.enqueue(text, "", cd, self.depth + 1)

    def nested(self, vals: list[str], start: int, stop: int, cd: bool) -> None:
        if _facts("".join(" " + v for v in vals[start:])):
            self.block("nested")
        self.enqueue(" ".join(vals[start:stop + 1]), "", cd, self.depth + 1)

    def heredoc(self, body: str, quoted: bool, closed: bool) -> None:
        if not quoted:
            self.enqueue(body, "H", self.cd_seen, self.depth + 1)
        if not closed:
            if _facts(body):
                self.block("nested")
            self.enqueue(body, "", self.cd_seen, self.depth + 1)
            return
        self.note_script(body)

    # ─ words
    def start_tok(self) -> None:
        if self.tok is None:
            self.tok = [self.i, ""]

    def flush_tok(self) -> None:
        if self.tok is None:
            return
        val = self.tok[1]
        self.toks.append((self.tok[0], self.i, val))
        self.tok = None
        # A here-string, or a word that reads as a push, may be what a shell
        # reading stdin runs (echo "git push --all -f" | bash).
        m = re.match(r"[0-9]*<<<", val)
        if m:
            self.note_script(val[m.end():])
        elif re.search(r"[ \t\n]", val) and _may_push(val):
            self.note_script(val)
        case = self.cases[-1]
        if val == "in" and len(self.toks) == 3 and self.toks[0][2] == "case":
            case[0] += 1
            case[1] = True
            self.end_seg()
        if val == "esac" and len(self.toks) == 1 and case[0] > 0:
            case[0] -= 1
            case[1] = False

    def fd_tok(self) -> bool:
        if self.tok is None:
            return False
        return bool(re.fullmatch(r"[0-9]+|\{[A-Za-z_][A-Za-z0-9_]*\}", self.cmd[self.tok[0]:self.i]))

    def arith(self) -> bool:
        return bool(self.subs) and self.subs[-1]["kind"] in ("A", "[")

    def end_seg(self) -> None:
        self.flush_tok()
        if self.toks and not self.arith():
            self.analyze()
        self.toks = []
        self.nocd = False

    def cmd_pos(self) -> bool:
        return self.tok is None and all(t[2] in _KEYWORDS for t in self.toks)

    # ─ substitutions
    def open_exp(self, c: str) -> bool:
        cmd, i = self.cmd, self.i
        if c == "`":
            self.open_sub("`", 1)
            return True
        if c != "$":
            return False
        nc = cmd[i + 1:i + 2]
        if nc == "(":
            if cmd[i + 2:i + 3] == "(" and _arith_end(cmd, i + 3):
                self.open_sub("A", 3)
            else:
                self.open_sub("$", 2)
            return True
        if nc == "[":
            self.open_sub("[", 2)
            return True
        return False

    def open_sub(self, kind: str, width: int) -> None:
        self.start_tok()
        bt = self.subs[-1]["bt"] if self.subs else None
        if kind == "`":
            bt = _bt_end(self.cmd, self.i + 1)
            inner = self.cmd[self.i + 1:bt]
            if "\\" in inner:
                self.enqueue(re.sub(r"\\([\\`$])", r"\1", inner), "", self.cd_seen, self.depth + 1)
        self.subs.append({"kind": kind, "parens": 0, "start": self.i, "quote": self.q,
                          "toks": self.toks, "tok": self.tok, "cd": self.cd_seen,
                          "pd": len(self.parens), "bt": bt, "nocd": self.nocd})
        self.cases.append([0, False])
        self.nocd = False
        self.toks, self.tok, self.q = [], None, ""
        self.i += width

    def close_sub(self, width: int) -> None:
        self.end_seg()
        sub = self.subs.pop()
        self.cases.pop()
        self.toks, self.q, self.cd_seen = sub["toks"], sub["quote"], sub["cd"]
        self.nocd = sub["nocd"]
        del self.parens[sub["pd"]:]
        self.tok = [sub["tok"][0], sub["tok"][1] + self.cmd[sub["start"]:self.i + width]]
        self.i += width
        if self.q == "H":
            self.tok, self.toks = None, []

    def redirect(self) -> bool:
        if self.arith():
            return False
        cmd, i = self.cmd, self.i
        if (self.tok is not None and not self.fd_tok()
                and not re.match(r"^[0-9]*[<>]+&?$", self.tok[1]) and not re.match(r"^&>>?$", self.tok[1])):
            self.flush_tok()
        if cmd.startswith("<<<", i):
            self.start_tok()
            self.tok[1] += "<<<"
            self.i += 3
            while self.i < self.n and cmd[self.i] in " \t":
                self.i += 1
            return True
        if cmd.startswith("<<", i):
            self.tok = None
            j, strip = i + 2, False
            if cmd[j:j + 1] == "-":
                strip, j = True, j + 1
            while cmd[j:j + 1] in (" ", "\t"):
                j += 1
            word, quoted, j = _hd_word(cmd, j)
            if word or quoted:
                self.hds.append((word, strip, quoted))
            self.i = j
            return True
        return False

    # ─ the walk
    def walk(self, text: str, mode: str, depth: int, cd0: bool, edits: bool) -> None:
        self.cmd, self.n, self.i, self.q = text, len(text), 0, mode
        self.tok: list | None = None
        self.toks: list[tuple[int, int, str]] = []
        self.hds: list[tuple[str, bool, bool]] = []
        self.subs: list[dict] = []
        self.parens: list[bool] = []
        # Per level (the command, then each open substitution): open case
        # statements, and whether a pattern, ended by its ), is expected.
        self.cases: list[list] = [[0, False]]
        # A cd in this statement may leave the directory of what follows
        # unchanged: a subshell (pipeline element, background job), or ||.
        self.nocd = False
        self.cd_seen, self.depth, self.edits_on = cd0, depth, edits
        cmd, n = text, len(text)
        while self.i < n:
            i = self.i
            c = cmd[i]
            if self.subs and self.subs[-1]["bt"] is not None and i >= self.subs[-1]["bt"]:
                while self.subs[-1]["kind"] != "`":
                    self.close_sub(0)
                self.close_sub(1)
                continue
            if self.q == "'":
                if c == "'":
                    self.q = ""
                else:
                    self.tok[1] += c
                self.i += 1
                continue
            if self.q == "$'":
                if c == "\\" and i + 1 < n:
                    s, self.i = _ansi(cmd, i + 1)
                    self.tok[1] += s
                    continue
                if c == "'":
                    self.q = ""
                else:
                    self.tok[1] += c
                self.i += 1
                continue
            if self.q == '"':
                if c == "\\" and i + 1 < n and cmd[i + 1] in '\\"$`':
                    self.tok[1] += cmd[i + 1]
                    self.i += 2
                    continue
                if cmd.startswith("$$", i):
                    self.tok[1] += "$$"
                    self.i += 2
                    continue
                if self.open_exp(c):
                    continue
                if c == '"':
                    self.q = ""
                else:
                    self.tok[1] += c
                self.i += 1
                continue
            if self.q == "H":
                if c == "\\" and i + 1 < n and cmd[i + 1] in "$`\\\n":
                    self.i += 2
                    continue
                if cmd.startswith("$$", i):
                    self.i += 2
                    continue
                if not self.open_exp(c):
                    self.i += 1
                continue
            if c == "\\":
                if cmd[i + 1:i + 2] == "\n":
                    self.i += 2
                    continue
                self.start_tok()
                self.tok[1] += cmd[i + 1:i + 2]
                self.i += 2
                continue
            if cmd.startswith("$$", i):
                self.start_tok()
                self.tok[1] += "$$"
                self.i += 2
                continue
            if cmd.startswith("$'", i):
                self.start_tok()
                self.q = "$'"
                self.i += 2
                continue
            if cmd.startswith('$"', i):
                self.start_tok()
                self.q = '"'
                self.i += 2
                continue
            if c in "'\"":
                self.start_tok()
                self.q = c
                self.i += 1
                continue
            if c in " \t":
                self.flush_tok()
                self.i += 1
                continue
            if c == "#" and self.tok is None:
                while self.i < n and cmd[self.i] != "\n":
                    self.i += 1
                continue
            if c == "\n":
                self.end_seg()
                self.i += 1
                for delim, strip, quoted in self.hds:
                    b0, found, closes, ls = self.i, False, False, self.i
                    while self.i < n:
                        e = cmd.find("\n", self.i)
                        line = cmd[self.i:e] if e >= 0 else cmd[self.i:]
                        ls = self.i
                        self.i = e + 1 if e >= 0 else n
                        lt = len(line) - len(line.lstrip("\t")) if strip else 0
                        line = line[lt:]
                        if line == delim:
                            found = True
                            break
                        if (self.subs and self.subs[-1]["kind"] == "$" and delim and ")" in line
                                and line.startswith(delim)):
                            found = closes = True
                            self.i = ls + lt + len(delim)
                            break
                    self.heredoc(cmd[b0:ls if found else self.i], quoted, found)
                    if closes:
                        break
                self.hds = []
                continue
            if self.open_exp(c):
                continue
            if c == "(" and cmd[i + 1:i + 2] == "(" and self.cmd_pos() and _arith_end(cmd, i + 2):
                self.open_sub("A", 2)
                continue
            if c == "(" and self.cases[-1][1] and self.tok is None and not self.toks:
                self.i += 1
                continue
            if c == "(":
                if self.subs:
                    self.subs[-1]["parens"] += 1
                self.end_seg()
                self.parens.append(self.cd_seen)
                self.i += 1
                continue
            if c == ")":
                self.flush_tok()
                if self.cases[-1][1]:
                    self.end_seg()
                    self.cases[-1][1] = False
                    self.i += 1
                    continue
                top = self.subs[-1] if self.subs else None
                if top and top["parens"] == 0 and top["kind"] == "$":
                    self.close_sub(1)
                    continue
                if top and top["parens"] == 0 and top["kind"] == "A":
                    self.close_sub(2 if cmd[i + 1:i + 2] == ")" else 1)
                    continue
                if top and top["parens"] > 0:
                    top["parens"] -= 1
                self.end_seg()
                if len(self.parens) > (top["pd"] if top else 0):
                    self.cd_seen = self.parens.pop()
                self.i += 1
                continue
            if self.subs and self.subs[-1]["kind"] == "[":
                if c == "[":
                    self.subs[-1]["parens"] += 1
                elif c == "]":
                    if self.subs[-1]["parens"] == 0:
                        self.close_sub(1)
                        continue
                    self.subs[-1]["parens"] -= 1
            if c == ";":
                self.end_seg()
                if cmd[i + 1:i + 2] in (";", "&"):
                    if self.cases[-1][0] > 0:
                        self.cases[-1][1] = True
                    self.i += 3 if cmd.startswith(";;&", i) else 2
                    continue
                self.i += 1
                continue
            if c == "|":
                self.nocd = True
                self.end_seg()
                self.nocd = True
                self.i += 2 if cmd[i + 1:i + 2] in ("|", "&") else 1
                continue
            if c == "&":
                if i > 0 and cmd[i - 1] in "<>":
                    self.start_tok()
                    self.tok[1] += c
                    self.i += 1
                    continue
                if cmd[i + 1:i + 2] == ">":
                    self.flush_tok()
                    self.start_tok()
                    self.tok[1] += c
                    self.i += 1
                    continue
                if cmd[i + 1:i + 2] == "&":
                    self.end_seg()
                    self.i += 2
                    continue
                self.nocd = True
                self.end_seg()
                self.i += 1
                continue
            if c in "<>" and self.redirect():
                continue
            self.start_tok()
            self.tok[1] += c
            self.i += 1
        while self.subs:
            self.close_sub(0)
        self.end_seg()

    # ─ one statement
    def analyze(self) -> None:
        vals = [t[2] for t in self.toks]
        k = 0
        while k < len(vals) and (_ASSIGN.match(vals[k]) or vals[k] in _KEYWORDS):
            k += 1
        if k < len(vals) and vals[k].rsplit("/", 1)[-1] in ("cd", "pushd", "popd"):
            if not self.nocd:
                self.cd_seen = True
            return
        while k < len(vals):
            v = vals[k]
            if _ASSIGN.match(v) or v.startswith("-"):
                k += 1
                continue
            w = v.rsplit("/", 1)[-1]
            if w == "git":
                if self.analyze_git(vals, k):
                    return
            elif w in _SHELLS:
                if self.analyze_shell(vals, k):
                    return
            elif w == "ssh":
                if self.analyze_ssh(vals, k):
                    return
            elif w in ("su", "runuser"):
                self.analyze_su(vals, k)
                return
            elif w in ("sudo", "doas"):
                if self.analyze_sudo(vals, k):
                    return
            elif w == "eval":
                self.nested(vals, k + 1, len(vals) - 1, self.cd_seen)
                return
            k += 1

    def analyze_shell(self, vals: list[str], k: int) -> bool:
        j = k + 1
        while j < len(vals):
            v = vals[j]
            words = _redirect_words(v)
            if words:
                j += words
                continue
            if v == "-c" or (re.match(r"^-[A-Za-z]+$", v) and "c" in v):
                self.nested(vals, j + 1, j + 1, self.cd_seen)
                return True
            if v == "-s":
                self.set_stdin(self.cd_seen)
                return True
            if v in ("-o", "+o", "-O", "+O", "--rcfile", "--init-file"):
                j += 2
                continue
            if v[:1] in ("-", "+"):
                j += 1
                continue
            return False
        self.set_stdin(self.cd_seen)
        return True

    def analyze_ssh(self, vals: list[str], k: int) -> bool:
        j = k + 1
        while j < len(vals):
            v = vals[j]
            if re.match(r"^-[BbcDEeFIiJLlmOopQRSWw]$", v):
                j += 2
                continue
            if v.startswith("-"):
                j += 1
                continue
            break
        if j >= len(vals):
            return False
        m = j + 1
        while m < len(vals) and _redirect_words(vals[m]):
            m += _redirect_words(vals[m])
        if m >= len(vals):
            self.set_stdin(True)
            return True
        self.nested(vals, j + 1, len(vals) - 1, True)
        return True

    def analyze_su(self, vals: list[str], k: int) -> None:
        for j in range(k + 1, len(vals)):
            v = vals[j]
            if v in ("-c", "--command") or (re.match(r"^-[A-Za-z]+$", v) and "c" in v):
                self.nested(vals, j + 1, j + 1, self.cd_seen)
                return
            if v.startswith("--command="):
                vals[j] = v[len("--command="):]
                self.nested(vals, j, j, self.cd_seen)
                return
        self.set_stdin(self.cd_seen)

    def analyze_sudo(self, vals: list[str], k: int) -> bool:
        shell = False
        j = k + 1
        while j < len(vals):
            v = vals[j]
            words = _redirect_words(v)
            if words:
                j += words
                continue
            if re.match(r"^-[ugCDhprtUT]$", v):
                j += 2
                continue
            if v in ("--shell", "--login") or (re.match(r"^-[A-Za-z]+$", v) and ("s" in v or "i" in v)):
                shell = True
                j += 1
                continue
            if v.startswith("-"):
                j += 1
                continue
            return False
        if shell:
            self.set_stdin(self.cd_seen)
        return shell

    def analyze_git(self, vals: list[str], k: int) -> bool:
        seg = self.toks
        # GIT_CONFIG_KEY_n/VALUE_n and GIT_CONFIG_PARAMETERS assigned in front
        # of git are config on its command line too, read as -c is.
        cfg: list[tuple[str, str]] = []
        env: dict[str, str] = {}
        for v in vals[:k]:
            m = re.match(r"GIT_CONFIG_((?:KEY|VALUE)_[0-9]+)=", v)
            if m:
                env[m.group(1)] = v[m.end():]
            elif v.startswith("GIT_CONFIG_PARAMETERS="):
                for item in re.findall(r"'([^']*)'", v[len("GIT_CONFIG_PARAMETERS="):]):
                    key, _, val = item.partition("=")
                    cfg.append((key.lower(), val))
        for name, key in env.items():
            if name.startswith("KEY_"):
                key, _, val = (key + "=" + env.get("VALUE_" + name[4:], "")).partition("=")
                cfg.append((key.lower(), val))
        k += 1
        has_c = False
        while k < len(vals):
            v = vals[k]
            if v in ("-c", "--config-env") or v.startswith("--config-env="):
                if v.startswith("--config-env="):
                    raw, k = v[len("--config-env="):], k + 1
                else:
                    raw, k = (vals[k + 1] if k + 1 < len(vals) else ""), k + 2
                key, _, val = raw.partition("=")
                cfg.append((key.lower(), val if v == "-c" else "?"))
                continue
            if v in ("-C", "--git-dir", "--work-tree", "--namespace"):
                has_c = True
                k += 2
                continue
            if re.match(r"^--(?:git-dir|work-tree)=", v):
                has_c = True
                k += 1
                continue
            if v.startswith("-"):
                k += 1
                continue
            break
        if k >= len(vals):
            return False
        computed = False
        if vals[k] != "push":
            # git follows a chain of aliases, so this one may push through
            # another: when it is given with -c, any -c alias that pushes blocks.
            name = "alias." + vals[k].lower()
            if any(key == name for key, _ in cfg) and any(
                    key.startswith("alias.") and ("push" in val or val == "?") for key, val in cfg):
                self.block("config")
                return True
            # A subcommand the shell computes may be push: read as one, never rewritten.
            raw = self.cmd[seg[k][0]:seg[k][1]]
            if "$" not in raw and "`" not in raw:
                return False
            computed = True
        pk = k
        skip = dd = False
        npos = nrefs = 0
        lease = allrefs = mirror = mainref = delete = headref = subref = False
        forces: list[int] = []
        pluses: list[int] = []
        for j in range(pk + 1, len(vals)):
            v = vals[j]
            if skip:
                skip = False
                continue
            words = _redirect_words(v)
            if words:
                skip = words == 2
                continue
            if not dd and v == "--":
                dd = True
                continue
            if not dd and v.startswith("--"):
                if v == "--force":
                    forces.append(j)
                elif v.startswith("--force-with-lease") or v == "--force-if-includes":
                    lease = True
                elif v == "--mirror":
                    mirror = True
                elif v in ("--all", "--branches"):
                    allrefs = True
                elif v == "--delete":
                    delete = True
                elif v in ("--repo", "--receive-pack", "--exec", "--push-option"):
                    skip = True
                continue
            if not dd and re.match(r"^-[^-]", v):
                if v == "-o":
                    skip = True
                    continue
                if not re.match(r"^-[A-Za-z0-9]+$", v):
                    continue
                if "d" in v:
                    delete = True
                if "f" in v:
                    forces.append(j)
                continue
            npos += 1
            if npos == 1:
                continue
            nrefs += 1
            ref, plus = v, False
            if ref.startswith("+"):
                ref, plus = ref[1:], True
            dst = _dst(ref)
            if dst in ("main", "master") or _glob_main(dst) or ref == ":":
                mainref = True
                if ref.startswith(":") and ref != ":":
                    delete = True
            if dst in ("HEAD", "@"):
                headref = True
            raw = self.cmd[seg[j][0]:seg[j][1]]
            if "$(" in raw or "`" in raw:
                subref = True
            if plus:
                pluses.append(j)
        if mirror:
            self.block("mirror")
            return True
        if delete and mainref:
            self.block("delete")
            return True
        if nrefs == 0 and any(
                (re.match(r"^remote\..+\.push$", key) and (forces or pluses or lease or val.startswith("+") or val == "?"))
                or (re.match(r"^remote\..+\.mirror$", key) and val != "false")
                or (key == "push.default" and val in ("matching", "?") and (forces or pluses or lease))
                for key, val in cfg):
            self.block("config")
            return True
        if not forces and not pluses and not lease:
            return True
        if mainref or (allrefs and (forces or pluses or lease)):
            self.block("main")
            return True
        if ((((nrefs == 0 or headref) and not allrefs and not self.cd_seen and not has_c) or subref)
                and self.branch in ("main", "master")):
            self.block("branch")
            return True
        if not forces and not pluses or computed:
            return True
        for j in forces:
            v = vals[j]
            if v in ("--force", "-f"):
                new = "--force-with-lease"
            else:
                rest = v.replace("f", "")
                new = "--force-with-lease" if rest == "-" else rest + " --force-with-lease"
            self.add_edit(seg[j][0], seg[j][1], new)
        for j in pluses:
            self.add_edit(seg[j][0], seg[j][1], self.cmd[seg[j][0]:seg[j][1]].replace("+", "", 1))
        if not forces and not lease:
            self.add_edit(seg[pk][1], seg[pk][1], " --force-with-lease")
        return True


def _force_push(command: str, branch: str) -> tuple[str, str] | None:
    """("block", main|branch|delete|mirror|config|nested), ("rewrite", new command) or None."""
    walk = _PushWalk(branch)
    walk.run(command)
    if walk.blocked:
        return ("block", walk.blocked)
    if not walk.edits:
        return None
    out = command
    for start, end, text in sorted(walk.edits, key=lambda e: e[0], reverse=True):
        out = out[:start] + text + out[end:]
    return ("rewrite", out)


def _current_branch(cwd: str) -> str:
    try:
        p = subprocess.run(
            ["git", "-C", cwd, "symbolic-ref", "--short", "-q", "HEAD"],
            capture_output=True, text=True, timeout=3,
        )
        return p.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def evaluate(command: str, branch: str = "") -> dict | None:
    lower = command.lower()
    dev_mode = (Path.home() / ".clade" / ".dev-mode").exists()
    if not dev_mode:
        for pattern in MIGRATIONS:
            if pattern in lower:
                return _deny(
                    f"Database migration detected ({pattern}). Review and run it manually."
                )

    for statement in _statements(command):
        if not _recursive_force(statement):
            continue
        if re.search(_DANGEROUS_NAMED, statement) or re.search(_DANGEROUS_ROOT, statement):
            return _deny(f"Catastrophic recursive deletion blocked: {statement.strip()}")

    unresolved = _unresolved_delete(command)
    if unresolved is not None:
        kind, detail = unresolved
        if kind == "refuse":
            return _deny(
                f"Recursive delete refused: {detail}. Name the directory explicitly, "
                f"or run it manually after checking what it expands to. Command: {command}"
            )
        guard = f"pre_tool_guardian: refusing a recursive delete on unset {detail}"
        safer = command.replace("${" + detail + "}", "${" + detail + ":?" + guard + "}")
        safer = re.sub(
            r"\$" + re.escape(detail) + r"\b",
            "${" + detail + ":?" + guard + "}",
            safer,
        )
        return _rewrite(safer)

    pushed = _force_push(command, branch) if _may_push(command) else None
    if pushed is not None:
        kind, detail = pushed
        if kind == "block":
            why = {
                "branch": f"it pushes the current branch, which is {branch}",
                "delete": "it deletes main/master on the remote",
                "mirror": "--mirror force-updates every ref on the remote, main/master included",
                "config": ("git -c or GIT_CONFIG_* sets an alias or a push setting on its command line "
                           "that forces the push"),
                "nested": "a wrapped or piped shell command (ssh, bash -c, eval, … | bash) force-pushes main/master",
            }.get(detail, "it names main/master")
            return _deny(
                f"Force push to main/master blocked: {why}. This destroys shared history. "
                "Use --force-with-lease on a feature branch, or ask the user explicitly. "
                f"Command: {command}"
            )
        return _rewrite(detail)

    if re.search(r"\bDROP\s+(?:DATABASE|TABLE|SCHEMA)\b", command, re.IGNORECASE):
        return _deny("Irreversible SQL DROP operation blocked; review and run it manually.")
    return None


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    if event.get("tool_name") != "Bash":
        return 0
    command = (event.get("tool_input") or {}).get("command") or ""
    branch = _current_branch(event.get("cwd") or os.getcwd()) if _may_push(command) else ""
    try:
        decision = evaluate(command, branch)
    except Exception as exc:  # a crashing guard is a silent allow; say so
        print(f"pre_tool_guardian: internal error, command not checked: {exc!r}", file=sys.stderr)
        return 0
    if decision:
        json.dump(decision, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
