#!/usr/bin/env python3
"""check-workflow-script — preflight a Workflow launch before its agents run.

A Workflow script fails in ways that leave no error: a prior result cut short
inside the next agent's prompt, a placeholder where the data should be, agents
that hit a usage limit and come back as null inside a run reported
"completed". The 2026-10-22 audit of every run on one host (316 runs, 3,646
agents) measured all three:

  silent-truncation  ~81 of 294 scripts `.slice()` a stringified prior result
                     into a prompt with no log(); at 48 of 66 sites a real
                     result was cut, and the median cut dropped 41% of it.
  placeholder-args   10 of 324 launches carried a placeholder such as
                     "__FILL__", {"__see": "review-units"} or "(see packet
                     file)"; one of them ran to "completed" on the placeholder
                     and returned an empty result.
  quota              90 agents died on usage limits; 64 of them sat inside 16
                     runs reported completed.

Rules (each finding names its line):
  silent-truncation  WARN  .slice/.substring/.substr on JSON.stringify(...),
                           String(...) or .toString() (directly or through a
                           variable assigned from one) whose result reaches a
                           prompt, in a script where no log() or console.*
                           call names a cut. A cut word in a prompt or a
                           phase() title does not count: it describes the
                           task, not the truncation.
  placeholder-args   DENY  an args leaf or key that is a sentinel, not data.
  stringified-args   WARN  args is a JSON-encoded string of an object/array.
  quota              WARN  the profile's usage cache is fresh (< 10 min) and
                           the 7-day window is >= 90% or the 5-hour >= 85%.

Not shipped, on measurement (2026-10-23, 324 unique scripts on one host):
the audit's two fan-out rules. An array cap before a fan-out with no log() of
what it dropped: the best token-level version flagged 5 sites and 3 were real
(60%); the other 2 accounted for the drop through a variable logged further
down, which no window or name heuristic saw. A fan-out as wide as an agent's
own result: 2 sites, both real — too few to show the 80% a rule here needs.

Modes:
  check-workflow-script.py FILE...      findings, exit 0 (report-only) unless --strict
  check-workflow-script.py --hook       PreToolUse(Workflow) JSON on stdin
  check-workflow-script.py --survey [ROOT...] [--json]
  check-workflow-script.py --self-test

Hook contract: the args checks run FIRST and on their own, so a failure in
script resolution or the quota read can never drop a deny. The in-process
deadline (CLADE_PREFLIGHT_DEADLINE seconds, default 10) is armed only after
them, so when it fires it cuts the script and quota stages short and the deny
already found is still printed; reading stdin and the args check are bounded
by the wrapper's `timeout` instead. At most one JSON object is printed; deny
wins over warn. It never exits non-zero and never prints a traceback: a hook
that crashes is a launch that goes unchecked.

Stdlib only, Python 3.9 syntax: CI runs the self-test in a job that installs
nothing, and the hook runs under whatever python3 the machine has.
"""

from __future__ import annotations

import glob
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

# ─── Constants ────────────────────────────────────────────────────────

WARN_BUDGET = 1500          # combined additionalContext chars, per the hook contract
DENY_BUDGET = 1800
MAX_SCRIPT_BYTES = 4_000_000
HOOK_DEADLINE_S = 10.0      # default; CLADE_PREFLIGHT_DEADLINE overrides (the wrapper's bound is 12 s)
REFRESH_TIMEOUT_S = 5
QUOTA_MAX_AGE_S = 600       # an older cache says nothing: the status line rarely refreshes it
SEVEN_DAY_WARN = 90.0
FIVE_HOUR_WARN = 85.0

LOG_CALLEES = {"log", "phase", "console.log", "console.error", "console.warn", "console.info"}
# Calls that can account for a cut. Not phase(): a title such as
# phase('Drop stale units') names the task, not a truncation.
CUT_LOG_CALLEES = LOG_CALLEES - {"phase"}
# Object keys whose value is metadata, never a prompt.
META_KEYS = {"label", "phase", "title", "name", "description", "id", "key",
             "agentType", "model", "effort", "schema"}
APPEND_CALLEES = ("push", "unshift", "concat")
CUT_WORDS = re.compile(r"trunc|\bcut|clip|drop|omit|chars", re.I)
KEYWORDS_BEFORE_REGEX = {"return", "typeof", "instanceof", "in", "of", "new", "delete",
                         "void", "throw", "case", "do", "else", "yield", "await"}
STATEMENT_KEYWORDS = {"if", "for", "while", "switch", "catch", "with", "function", "return"}


# ─── JavaScript scanning ──────────────────────────────────────────────
# Not a parser. One linear pass that tells code from strings, comments,
# template text and regex literals, and records the bracket each token sits
# in, so a site can ask "am I inside agent()'s first argument?". The audit's
# acorn pass and a regex pass agreed on 73 of 77 truncating scripts; a
# token-level pass keeps the regex's reach (prompts built in helper functions)
# while seeing the brackets a regex cannot.

@dataclass
class Tok:
    kind: str     # ident | num | punct | str | tmpl | regex
    text: str
    start: int
    end: int
    frame: int    # innermost enclosing frame id, -1 at top level


@dataclass
class Frame:
    kind: str     # ( [ { ${ `
    open_tok: int
    parent: int
    callee: str = ""
    is_index: bool = False
    close_tok: int = -1


_PUNCT = sorted(["===", "!==", "**=", "<<=", ">>=", ">>>", "...", "?.", "??", "=>", "==", "!=",
                 "<=", ">=", "&&", "||", "++", "--", "+=", "-=", "*=", "/=", "%=", "&=",
                 "|=", "^=", "<<", ">>", "**"], key=len, reverse=True)
_IDENT_START = re.compile(r"[A-Za-z_$\u0080-￿]")
_IDENT = re.compile(r"[A-Za-z0-9_$\u0080-￿]+")
_NUM = re.compile(r"(?:0[xXoObB][0-9a-fA-F_]+|\d[\d_]*(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+)n?")


class Script:
    """Tokens, frames and line lookup for one JavaScript source."""

    def __init__(self, src: str) -> None:
        self.src = src
        self.toks: List[Tok] = []
        self.frames: List[Frame] = []
        self._nl = [i for i, ch in enumerate(src) if ch == "\n"]
        self._lex()
        self._by_open = {fr.open_tok: i for i, fr in enumerate(self.frames)}
        self._by_close = {fr.close_tok: fr.open_tok for fr in self.frames if fr.close_tok >= 0}

    def line_of(self, offset: int) -> int:
        return bisect_right(self._nl, offset - 1) + 1

    def line_text(self, offset: int) -> str:
        ln = self.line_of(offset)
        start = self._nl[ln - 2] + 1 if ln >= 2 else 0
        end = self._nl[ln - 1] if ln - 1 < len(self._nl) else len(self.src)
        return self.src[start:end]

    # The lexer keeps a stack of open frames. A template literal is a frame
    # whose body is text until `${` opens a code frame inside it.
    def _lex(self) -> None:
        src, n = self.src, len(self.src)
        i = 0
        stack: List[int] = []

        def cur() -> int:
            return stack[-1] if stack else -1

        def push_tok(kind: str, a: int, b: int) -> int:
            self.toks.append(Tok(kind, src[a:b], a, b, cur()))
            return len(self.toks) - 1

        def open_frame(kind: str, tok_index: int, callee: str = "", is_index: bool = False) -> None:
            self.frames.append(Frame(kind, tok_index, cur(), callee, is_index))
            stack.append(len(self.frames) - 1)

        def lex_template_body(j: int) -> int:
            """Scan template text from j; return the index after `${` or the closing backtick."""
            a = j
            while j < n:
                ch = src[j]
                if ch == "\\":
                    j += 2
                    continue
                if ch == "`":
                    if j > a:
                        push_tok("tmpl", a, j)
                    t = push_tok("punct", j, j + 1)
                    fr = stack.pop()
                    self.frames[fr].close_tok = t
                    return j + 1
                if ch == "$" and j + 1 < n and src[j + 1] == "{":
                    if j > a:
                        push_tok("tmpl", a, j)
                    t = push_tok("punct", j, j + 2)
                    open_frame("${", t)
                    return j + 2
                j += 1
            if j > a:
                push_tok("tmpl", a, j)
            return n

        while i < n:
            if stack and self.frames[stack[-1]].kind == "`":
                i = lex_template_body(i)
                continue
            ch = src[i]
            if ch in " \t\r\n\f\v﻿ ":
                i += 1
                continue
            if src.startswith("//", i):
                j = src.find("\n", i)
                i = n if j == -1 else j
                continue
            if src.startswith("/*", i):
                j = src.find("*/", i + 2)
                i = n if j == -1 else j + 2
                continue
            if ch in "'\"":
                j = i + 1
                while j < n and src[j] != ch and src[j] != "\n":
                    j += 2 if src[j] == "\\" else 1
                push_tok("str", i, min(j + 1, n))
                i = j + 1
                continue
            if ch == "`":
                t = push_tok("punct", i, i + 1)
                open_frame("`", t)
                i += 1
                continue
            if ch == "/" and self._regex_allowed():
                j = self._scan_regex(i)
                if j > 0:
                    push_tok("regex", i, j)
                    i = j
                    continue
            if _IDENT_START.match(ch):
                m = _IDENT.match(src, i)
                end = m.end() if m else i + 1
                push_tok("ident", i, end)
                i = end
                continue
            if ch.isdigit() or (ch == "." and i + 1 < n and src[i + 1].isdigit()):
                m = _NUM.match(src, i)
                end = m.end() if m and m.end() > i else i + 1
                push_tok("num", i, end)
                i = end
                continue
            if ch in "([{":
                callee, is_index = "", False
                if ch == "(":
                    callee = self._callee_before()
                elif ch == "[":
                    is_index = self._index_before()
                t = push_tok("punct", i, i + 1)
                open_frame(ch, t, callee, is_index)
                i += 1
                continue
            if ch in ")]}":
                # Close the nearest frame that this bracket can close; a
                # stray bracket never empties the stack below a template.
                want = {")": "(", "]": "[", "}": "{"}[ch]
                if stack and (self.frames[stack[-1]].kind == want
                              or (ch == "}" and self.frames[stack[-1]].kind == "${")):
                    fr = stack.pop()
                    t = push_tok("punct", i, i + 1)
                    self.frames[fr].close_tok = t
                    self.toks[t].frame = cur()
                else:
                    push_tok("punct", i, i + 1)
                i += 1
                continue
            for p in _PUNCT:
                if src.startswith(p, i):
                    push_tok("punct", i, i + len(p))
                    i += len(p)
                    break
            else:
                push_tok("punct", i, i + 1)
                i += 1

    def _regex_allowed(self) -> bool:
        if not self.toks:
            return True
        last = self.toks[-1]
        if last.kind in ("num", "str", "regex", "tmpl"):
            return False
        if last.kind == "ident":
            return last.text in KEYWORDS_BEFORE_REGEX
        return last.text not in (")", "]", "}", "`")

    def _scan_regex(self, i: int) -> int:
        src, n = self.src, len(self.src)
        j, in_class = i + 1, False
        while j < n:
            ch = src[j]
            if ch == "\n":
                return -1
            if ch == "\\":
                j += 2
                continue
            if ch == "[":
                in_class = True
            elif ch == "]":
                in_class = False
            elif ch == "/" and not in_class:
                j += 1
                while j < n and (src[j].isalnum() or src[j] in "_$"):
                    j += 1
                return j
            j += 1
        return -1

    def _callee_before(self) -> str:
        """The member chain written right before `(` — `agent`, `JSON.stringify`, `x.toString`."""
        parts: List[str] = []
        k = len(self.toks) - 1
        while k >= 0:
            t = self.toks[k]
            if t.kind == "ident":
                parts.append(t.text)
                if k >= 1 and self.toks[k - 1].text in (".", "?."):
                    parts.append(".")
                    k -= 2
                    continue
                break
            if t.text in (")", "]") and parts and parts[-1] == ".":
                parts.append("<expr>")
                break
            break
        return "".join(reversed(parts))

    def _index_before(self) -> bool:
        if not self.toks:
            return False
        last = self.toks[-1]
        if last.kind == "ident":
            return last.text not in KEYWORDS_BEFORE_REGEX and last.text not in STATEMENT_KEYWORDS
        return last.kind in ("str",) or last.text in (")", "]", "`")

    # ── navigation helpers ──
    def prev_sig(self, k: int) -> Optional[Tok]:
        return self.toks[k - 1] if k >= 1 else None

    def next_sig(self, k: int) -> Optional[Tok]:
        return self.toks[k + 1] if k + 1 < len(self.toks) else None

    def matching_open(self, close_k: int) -> int:
        """Token index of the bracket a closing `)`/`]` closes, or -1."""
        return self._by_close.get(close_k, -1)

    def frame_of_open(self, open_k: int) -> int:
        return self._by_open.get(open_k, -1)

    def arg_index(self, frame_id: int, k: int) -> int:
        """Which comma-separated argument of frame `frame_id` token k is in."""
        fr = self.frames[frame_id]
        commas = 0
        for j in range(fr.open_tok + 1, k):
            t = self.toks[j]
            if t.frame == frame_id and t.text == ",":
                commas += 1
        return commas

    def governing_key(self, frame_id: int, k: int) -> Optional[str]:
        """The object-literal key whose value holds token k, inside `{` frame `frame_id`."""
        fr = self.frames[frame_id]
        key: Optional[str] = None
        for j in range(fr.open_tok + 1, k):
            t = self.toks[j]
            if t.frame != frame_id or t.kind not in ("ident", "str"):
                continue
            before = self.toks[j - 1].text if j >= 1 else ""
            after = self.toks[j + 1].text if j + 1 < len(self.toks) else ""
            if before in ("{", ",") and after == ":":
                key = t.text.strip("'\"")
        return key


# ─── Rule: silent truncation ──────────────────────────────────────────

@dataclass
class Finding:
    rule: str
    line: int
    excerpt: str
    message: str
    severity: str = "warn"   # warn | deny


TRUNC_FIX = ("write the full result to a file and pass its path, interpolate a bounded "
             "summary field, or log(`cut ${n} of ${m} chars`) where you cut")


def _stringified_receiver(s: Script, dot_k: int) -> Tuple[bool, int]:
    """Is the expression before `.slice` a stringified value? Returns (yes, first token)."""
    k = dot_k - 1
    if k < 0:
        return False, k
    t = s.toks[k]
    if t.text == ")":
        open_k = s.matching_open(k)
        if open_k < 0:
            return False, k
        fid = s.frame_of_open(open_k)
        callee = s.frames[fid].callee if fid >= 0 else ""
        start = open_k
        # walk back over the callee's own tokens
        if callee:
            start = open_k - (2 * callee.count(".") + 1)
        if callee in ("JSON.stringify", "String") or callee.endswith(".toString") or callee == "toString":
            return True, max(start, 0)
        if not callee:
            inner = s.toks[open_k + 1:open_k + 4]
            texts = "".join(x.text for x in inner)
            if texts.startswith("JSON.stringify") or texts.startswith("String("):
                return True, open_k
        return False, max(start, 0)
    if t.kind == "ident" and not (k >= 1 and s.toks[k - 1].text in (".", "?.")):
        return _assigned_from_stringify(s, t.text), k
    return False, k


def _assigned_from_stringify(s: Script, name: str) -> bool:
    toks = s.toks
    for j in range(len(toks) - 3):
        if toks[j].kind == "ident" and toks[j].text == name and toks[j + 1].text == "=":
            if j >= 1 and toks[j - 1].text in (".", "?."):
                continue
            rhs = "".join(x.text for x in toks[j + 2:j + 6])
            if rhs.startswith("JSON.stringify(") or rhs.startswith("String("):
                return True
    return False


def _cut_args(s: Script, open_k: int, method: str) -> bool:
    """`(0, N)` or `(-N)`: a cut from the front or the back, not a chunk walk."""
    fid = s.frame_of_open(open_k)
    if fid < 0 or s.frames[fid].close_tok < 0:
        return False
    inner = s.toks[open_k + 1:s.frames[fid].close_tok]
    if not inner:
        return False
    if inner[0].text == "0" and len(inner) >= 3 and inner[1].text == ",":
        return True
    if method == "slice" and inner[0].text == "-" and len(inner) == 2 and inner[1].kind in ("num", "ident"):
        return True
    return False


def _prompt_context(s: Script, first_k: int, last_k: int, depth: int = 0) -> Tuple[bool, str]:
    """Does the expression spanning tokens first_k..last_k reach an agent prompt?"""
    before = s.prev_sig(first_k)
    after = s.next_sig(last_k)
    composite = bool((before and before.text in ("+", "+=")) or (after and after.text == "+"))
    anchor = first_k     # the outermost token walked: where the statement test starts
    fid = s.toks[first_k].frame
    while fid >= 0:
        fr = s.frames[fid]
        if fr.kind in ("${", "`"):
            composite = True
        elif fr.kind == "(":
            callee = fr.callee
            if callee in LOG_CALLEES:
                return False, "inside " + callee + "()"
            if callee == "agent" or callee.endswith(".agent"):
                if s.arg_index(fid, first_k) == 0:
                    return True, "agent() prompt"
                return False, "agent() options"
            if callee.split(".")[-1] in APPEND_CALLEES:
                composite = True
            elif callee in STATEMENT_KEYWORDS:
                return False, "condition"
        elif fr.kind == "[":
            if fr.is_index:
                return False, "index"
            composite = True
        elif fr.kind == "{":
            key = s.governing_key(fid, first_k)
            if key in META_KEYS:
                return False, "metadata key " + str(key)
            if key is None:
                break       # a block: decide at statement level
        anchor = fr.open_tok
        fid = fr.parent
    # Statement level.
    if composite:
        if fid < 0 and _statement_starts_with_return(s, anchor):
            return False, "the workflow's own return value"
        return True, "string built for a prompt"
    # `const v = <expr>` → does v reach a prompt?
    if before is not None and before.text == "=" and first_k >= 2 and depth < 2:
        var = s.toks[first_k - 2]
        if var.kind == "ident":
            for k, t in enumerate(s.toks):
                if k == first_k - 2 or t.kind != "ident" or t.text != var.text:
                    continue
                if k >= 1 and s.toks[k - 1].text in (".", "?."):
                    continue
                if _is_write_or_key(s, k):
                    continue
                hit, why = _prompt_context(s, k, k, depth + 1)
                if hit:
                    return True, "via " + var.text + " (" + why + ")"
    return False, "not interpolated"


def _is_write_or_key(s: Script, k: int) -> bool:
    """Is identifier k an assignment target (`v = …`) or an object key (`{ v: … }`)?

    Neither reads the variable. A `:` after it is a key only when `{` or `,`
    precedes it — in `ok ? v : ''` the `:` belongs to a ternary and v is read.
    """
    nxt = s.next_sig(k)
    if nxt is None:
        return False
    if nxt.text == "=":
        return True
    prev = s.prev_sig(k)
    return nxt.text == ":" and prev is not None and prev.text in ("{", ",")


# A line break ends a statement (ASI) unless the line ends or the next one
# starts with a token that cannot finish or cannot start an expression.
_CONT_END = {"+", "-", "*", "/", "%", "(", "[", "{", ",", "=", "?", ":", "=>", "||", "&&", "??",
             "+=", "-=", "${", ".", "?.", "`"}
_CONT_START = {"+", "-", "*", "/", "%", ".", "?.", "?", ":", "||", "&&", "??", ")", "]", "}", ","}


def _statement_starts_with_return(s: Script, k: int) -> bool:
    """Is token k part of a `return` statement in its own frame?"""
    fid = s.toks[k].frame
    open_k = s.frames[fid].open_tok if fid >= 0 else -1
    j = k - 1
    later = s.toks[k]
    while j > open_k:
        t = s.toks[j]
        if t.frame == fid:
            if t.text in (";", "{", "}"):
                return False
            if s.line_of(t.end) != s.line_of(later.start) and \
                    t.text not in _CONT_END and later.text not in _CONT_START:
                return False
            if t.kind == "ident" and t.text == "return":
                return True
            later = t
        j -= 1
    return False


def cut_is_logged(s: Script) -> bool:
    """Does any log() in the script name a cut? Then the author owns the truncation.

    Only log() and console.* count. A cut word anywhere else — an agent()
    prompt saying 'cut the scope to P1', a phase('Drop stale units') title —
    describes the work, and reading it as an accounted cut excused 58 of 191
    sites over the 324 scripts surveyed on 2026-10-23.
    """
    for fr in s.frames:
        if fr.kind == "(" and fr.callee in CUT_LOG_CALLEES and fr.close_tok > fr.open_tok:
            text = s.src[s.toks[fr.open_tok].start:s.toks[fr.close_tok].end]
            if CUT_WORDS.search(text):
                return True
    return False


def rule_silent_truncation(s: Script) -> List[Finding]:
    if cut_is_logged(s):
        return []
    out: List[Finding] = []
    seen = set()
    for k, t in enumerate(s.toks):
        if t.kind != "ident" or t.text not in ("slice", "substring", "substr"):
            continue
        if k < 1 or s.toks[k - 1].text not in (".", "?."):
            continue
        nxt = s.next_sig(k)
        if nxt is None or nxt.text != "(":
            continue
        if not _cut_args(s, k + 1, t.text):
            continue
        yes, first = _stringified_receiver(s, k - 1)
        if not yes:
            continue
        fid = s.frame_of_open(k + 1)
        close = s.frames[fid].close_tok if fid >= 0 else k + 1
        hit, why = _prompt_context(s, first, close)
        if not hit:
            continue
        line = s.line_of(t.start)
        excerpt = s.src[s.toks[first].start:s.toks[close].end]
        if (line, excerpt) in seen:
            continue
        seen.add((line, excerpt))
        out.append(Finding("silent-truncation", line, _short(excerpt, 90),
                           "cuts a stringified result inside a prompt with no log() naming the cut (" + why + ")"))
    return out


def _short(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1] + "…"


def check_source(src: str) -> List[Finding]:
    """Every script rule over one JavaScript source."""
    return rule_silent_truncation(Script(src[:MAX_SCRIPT_BYTES]))


# ─── Rule: placeholder and stringified args ───────────────────────────
# Derived from the 10 placeholder launches on the author's machine (2026-09-22 → 10-22).
# 8 of the 10 were a sentinel meaning "the data is in a file": __ARGS_
# PLACEHOLDER__, __FILL__, {"__file": …}, {"__see": …}, __RESOLVED_AND_
# PARTIAL__, ["__FROM_FILE__"], {"payload": "__FILE__"}, "(see packet file)".
# The other 2 were real truncations (an empty list, 1 of 23 packets) that no
# sentinel describes — a shape check needs an expected count, which is why the
# deny tells the author to pass one. Each pattern is a WHOLE-leaf match, so a
# long task description that mentions "__FILE__" or "placeholder" is not hit.

PLACEHOLDER_VALUE = [
    # Upper case only: all 11 real sentinels were (__FILL__, __FILE__, __LOAD__ …),
    # while __init__ or __eq__ in a list of method names is data.
    ("dunder sentinel", re.compile(r"^__[A-Z][A-Z0-9_]*__$")),
    # "see" only: "(from 2024 onward)" is prose, and "(see packet file)" is the shape seen.
    ("'(see …)' pointer", re.compile(r"^\(see\b[^)]*\)?$", re.I)),
    ("ellipsis", re.compile(r"^(?:\.{3}|…|\[\s*(?:\.{3}|…)\s*\]|\(\s*(?:\.{3}|…)\s*\))$")),
    # No ":" or "/": <https://…> is a markdown autolink, not a placeholder.
    ("angle-bracket token", re.compile(r"^<[A-Za-z][\w .|-]{0,60}>$")),
    # "placeholder" alone: "todo" and "fill" are ordinary status and CSS values.
    ("placeholder word", re.compile(r"^[\s<\[({_-]*placeholder[\s>\])}_-]*$", re.I)),
    ("elision marker", re.compile(r"^[\[(]\s*(?:elided|omitted|snip|truncated)\b[^\])]*[\])]?$|^\(truncated", re.I)),
]
# Keys: the two seen ({"__see": …}, {"__file": …}), their obvious siblings, and an
# upper-case dunder. Not any "__" prefix: GraphQL's "__typename" is data.
PLACEHOLDER_KEY = re.compile(r"^(?:__(?:[Ss]ee|[Ff]iles?|[Pp]ath|[Rr]ef|[Ll]oad|[Ff]ill|[Ff]rom_[Ff]ile)|__[A-Z][A-Z0-9_]*__)$")
# A lone <token> that is an HTML tag is markup, not a placeholder.
HTML_TAGS = {"a", "b", "i", "p", "br", "hr", "em", "li", "ol", "ul", "td", "th", "tr", "dl", "dt", "dd",
             "div", "img", "nav", "pre", "sub", "sup", "code", "span", "table", "strong", "small",
             "section", "header", "footer", "main", "body", "html", "head", "title", "button", "input"}


def _leaves(value: Any, path: str) -> Iterator[Tuple[str, str, Any]]:
    """(path, 'key'|'value', leaf) for every key and scalar leaf."""
    if isinstance(value, dict):
        for k, v in value.items():
            sub = path + "." + str(k) if re.match(r"^[A-Za-z_$][\w$]*$", str(k)) else path + "[" + json.dumps(str(k)) + "]"
            yield sub, "key", k
            yield from _leaves(v, sub)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _leaves(v, path + "[" + str(i) + "]")
    else:
        yield path, "value", value


def _placeholder_kind(text: str) -> Optional[str]:
    t = text.strip().strip('"').strip()
    for name, rx in PLACEHOLDER_VALUE:
        if rx.match(t):
            if name == "angle-bracket token" and t[1:-1].strip().lower() in HTML_TAGS:
                return None
            return name
    return None


def check_args(tool_input: Dict[str, Any]) -> Tuple[List[Finding], List[Finding]]:
    """(deny findings, warn findings) for tool_input.args."""
    if "args" not in tool_input:
        return [], []
    args = tool_input.get("args")
    deny: List[Finding] = []
    warn: List[Finding] = []
    value = args
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
        except ValueError:
            parsed = None
        if isinstance(parsed, (dict, list)):
            warn.append(Finding("stringified-args", 0, _short(args, 60),
                                "args is a JSON-encoded string that parses to " +
                                ("an object" if isinstance(parsed, dict) else "an array") +
                                "; pass the JSON value itself, or the script iterates a string"))
            value = parsed
        elif isinstance(parsed, str):
            value = parsed
    for path, where, leaf in _leaves(value, "args"):
        if where == "key":
            if isinstance(leaf, str) and PLACEHOLDER_KEY.match(leaf):
                deny.append(Finding("placeholder-args", 0, _short(path, 120),
                                    "sentinel key " + json.dumps(_short(leaf, 40)), "deny"))
            continue
        if isinstance(leaf, str):
            kind = _placeholder_kind(leaf)
            if kind:
                deny.append(Finding("placeholder-args", 0, _short(path, 120),
                                    kind + " " + json.dumps(_short(leaf, 40)), "deny"))
    return deny, warn


# ─── Rule: quota ──────────────────────────────────────────────────────

def config_dir(env: Dict[str, str]) -> Path:
    """CLAUDE_CONFIG_DIR when non-empty, else ~/.claude — claude-usage-watch.py's rule."""
    override = env.get("CLAUDE_CONFIG_DIR", "")
    if override:
        return Path(os.path.expanduser(override))
    home = env.get("HOME") or os.path.expanduser("~")
    return Path(home) / ".claude"


def refresh_usage_cache(env: Dict[str, str]) -> None:
    """Let claude-usage-watch.py refresh the cache (it does so past its 300 s TTL).

    The status line normally runs it with --statusline-input, which neither
    reads nor writes the cache, so a profile's cache can be weeks old. Output
    is discarded; a slow or failing refresh just leaves the cache stale, and
    a stale cache is reported as nothing.
    """
    if env.get("CLADE_PREFLIGHT_NO_REFRESH") == "1":
        return
    watcher = Path(os.path.abspath(__file__)).parent / "claude-usage-watch.py"
    if not watcher.is_file():
        return
    try:
        subprocess.run([sys.executable, str(watcher), "--refresh-only"], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=REFRESH_TIMEOUT_S, env=dict(env), check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def _hours_left(resets_at: Any, now: float) -> Optional[float]:
    if not isinstance(resets_at, str):
        return None
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(resets_at.replace("Z", "+00:00"))
        return (dt.timestamp() - now) / 3600
    except ValueError:
        return None


def check_quota(env: Dict[str, str], now: Optional[float] = None) -> List[Finding]:
    refresh_usage_cache(env)
    now = time.time() if now is None else now
    path = config_dir(env) / "usage-watch-cache.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    at = data.get("_at")
    if not isinstance(at, (int, float)):
        return []
    age = now - at
    if age > QUOTA_MAX_AGE_S or age < -60:
        return []
    parts: List[str] = []
    hot = False
    for key, label, limit in (("seven_day", "7-day", SEVEN_DAY_WARN), ("five_hour", "5-hour", FIVE_HOUR_WARN)):
        win = data.get(key)
        if not isinstance(win, dict):
            continue
        util = win.get("utilization")
        if not isinstance(util, (int, float)):
            continue
        left = _hours_left(win.get("resets_at"), now)
        if left is not None and left <= 0:
            continue    # a reading from the previous window
        when = "" if left is None else (" (resets in %.1f h)" % left if left < 48 else " (resets in %.1f d)" % (left / 24))
        parts.append("%s at %.0f%%%s" % (label, util, when))
        if util >= limit:
            hot = True
    if not hot:
        return []
    return [Finding("quota", 0, ", ".join(parts),
                    "agents that hit the limit come back as null inside a run reported completed; "
                    "defer, switch account, or make the script count nulls per stage and return "
                    "{incomplete, failed, resume}")]


# ─── Script resolution ────────────────────────────────────────────────

def resolve_script(tool_input: Dict[str, Any], cwd: str, env: Dict[str, str]) -> Tuple[Optional[str], str]:
    """(source, where) for the script the launch will run; (None, why) when unresolvable."""
    inline = tool_input.get("script")
    if isinstance(inline, str) and inline.strip():
        return inline, "inline script"
    sp = tool_input.get("scriptPath")
    if isinstance(sp, str) and sp:
        p = Path(os.path.expanduser(sp))
        if not p.is_absolute():
            p = Path(cwd) / p
        return _read(p), str(p)
    name = tool_input.get("name")
    if isinstance(name, str) and name and ".." not in name and not name.startswith("/"):
        for base in (Path(cwd) / ".claude" / "workflows", config_dir(env) / "workflows"):
            for ext in (".js", ".mjs"):
                p = base / (name + ext)
                if p.is_file():
                    return _read(p), str(p)
        return None, "saved workflow " + name + " not found"
    return None, "no script"


def _read(p: Path) -> Optional[str]:
    try:
        if not p.is_file():
            return None
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            return fh.read(MAX_SCRIPT_BYTES)
    except OSError:
        return None


# ─── Hook ─────────────────────────────────────────────────────────────

class _Deadline(BaseException):
    """Raised by the alarm: stop checking and emit what has been found so far."""


def _run_stage(stage: Callable[[], Tuple[List[Finding], List[Finding]]],
               deny: List[Finding], warn: List[Finding]) -> None:
    # Exception, not BaseException: the deadline must still reach hook_main.
    try:
        d, w = stage()
    except Exception:
        return
    deny.extend(d)
    warn.extend(w)


def _hook_cwd(payload: Dict[str, Any], env: Dict[str, str]) -> str:
    """The launch's directory: the payload's cwd, then CLAUDE_PROJECT_DIR, then ours.

    os.getcwd() raises inside a directory that was removed, which is why this
    runs inside the script stage and never ahead of the args check.
    """
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else ""
    return cwd or env.get("CLAUDE_PROJECT_DIR", "") or os.getcwd()


def _script_stage(tool_input: Dict[str, Any], payload: Dict[str, Any],
                  env: Dict[str, str]) -> Tuple[List[Finding], List[Finding]]:
    src, _where = resolve_script(tool_input, _hook_cwd(payload, env), env)
    if src is None:
        return [], []
    return [], SCANNER[0](src)


# The script rules, behind one indirection so the self-test can make the
# stage crash or run out of time and show the args deny survives both.
SCANNER: List[Callable[[str], List[Finding]]] = [check_source]


def _render(deny: List[Finding], warn: List[Finding]) -> str:
    if deny:
        shown = deny[:4]
        lines = ["Workflow preflight blocked this launch: " +
                 "; ".join(f.excerpt + " is a " + f.message for f in shown) +
                 (" (and %d more)" % (len(deny) - len(shown)) if len(deny) > len(shown) else "") +
                 ". The run would process a placeholder instead of the data — one audited run "
                 "completed on [{\"__see\": …}] and returned an empty result. Write the data to a "
                 "JSON file and pass its path, plus an expected count the script asserts (agents read "
                 "the file; the script itself cannot). Then relaunch."]
        if warn:
            lines.append("Also fix before relaunching: " + "; ".join(_warn_line(f) for f in warn))
        reason = _fit("\n".join(lines), DENY_BUDGET)
        return json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                  "permissionDecision": "deny",
                                                  "permissionDecisionReason": reason}})
    if warn:
        return json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                  "additionalContext": _warn_text(warn)}})
    return ""


def _warn_line(f: Finding) -> str:
    where = " line %d:" % f.line if f.line else ""
    return f.rule + where + " " + f.excerpt + " — " + f.message


def _warn_text(warn: List[Finding]) -> str:
    head = "Workflow preflight (report-only; the launch went ahead):"
    lines = [head]
    trunc = [f for f in warn if f.rule == "silent-truncation"]
    other = [f for f in warn if f.rule != "silent-truncation"]
    for f in other:
        lines.append("- " + f.rule + ": " + f.excerpt + " — " + f.message + ".")
    if trunc:
        lines.append("- silent-truncation: %d prompt site(s) cut a stringified result with no log() "
                     "naming the cut, so the next agent never learns part is missing. Fix: %s." % (len(trunc), TRUNC_FIX))
        budget = WARN_BUDGET - len("\n".join(lines)) - 40
        listed = 0
        for f in trunc:
            row = "  line %d: %s" % (f.line, f.excerpt)
            if len(row) + 1 > budget:
                break
            lines.append(row)
            budget -= len(row) + 1
            listed += 1
        if listed < len(trunc):
            lines.append("  … and %d more site(s)." % (len(trunc) - listed))
    return _fit("\n".join(lines), WARN_BUDGET)


def _fit(text: str, budget: int) -> str:
    return text if len(text) <= budget else text[:budget - 1] + "…"


def hook_main(stdin_text: str, env: Optional[Dict[str, str]] = None) -> str:
    """The --hook entry point: PreToolUse JSON in, at most one JSON object out."""
    env = dict(os.environ) if env is None else env
    try:
        payload = json.loads(stdin_text)
    except ValueError:
        return ""
    if not isinstance(payload, dict) or payload.get("tool_name") != "Workflow":
        return ""
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return ""
    deny: List[Finding] = []
    warn: List[Finding] = []
    # Args FIRST, on their own and before the deadline is armed: nothing
    # after this line can drop a deny.
    _run_stage(lambda: check_args(tool_input), deny, warn)
    try:
        _arm_deadline(_deadline_s(env))
        _run_stage(lambda: _script_stage(tool_input, payload, env), deny, warn)
        _run_stage(lambda: ([], check_quota(env)), deny, warn)
        _disarm_deadline()
    except _Deadline:
        pass
    finally:
        _disarm_deadline()
    return _render(deny, warn)


# ─── Deadline ─────────────────────────────────────────────────────────
# One-shot real-time timer. The handler raises only while armed, so a signal
# delivered just as the stages finish cannot escape past the except above.

_ARMED = [False]


def _deadline_s(env: Dict[str, str]) -> float:
    try:
        v = float(env.get("CLADE_PREFLIGHT_DEADLINE", "") or HOOK_DEADLINE_S)
    except ValueError:
        return HOOK_DEADLINE_S
    return v if 0 < v <= 3600 else HOOK_DEADLINE_S


def _on_alarm(_signum: int, _frame: Any) -> None:
    if _ARMED[0]:
        _ARMED[0] = False
        raise _Deadline()


def _arm_deadline(seconds: float) -> None:
    # No SIGALRM (Windows) or not the main thread: run unbounded here, and
    # let the wrapper's `timeout` and settings-hooks.json's 15 s bound us.
    if not hasattr(signal, "setitimer"):
        return
    try:
        signal.signal(signal.SIGALRM, _on_alarm)
        _ARMED[0] = True
        signal.setitimer(signal.ITIMER_REAL, seconds)
    except (ValueError, OSError):
        _ARMED[0] = False


def _disarm_deadline() -> None:
    _ARMED[0] = False
    if hasattr(signal, "setitimer"):
        try:
            signal.setitimer(signal.ITIMER_REAL, 0)
        except (ValueError, OSError):
            pass


def run_hook() -> int:
    try:
        text = sys.stdin.read()
        out = hook_main(text)
        if out:
            sys.stdout.write(out + "\n")
            sys.stdout.flush()
    except BaseException:  # noqa: BLE001 — a crashing hook is an unchecked launch
        pass
    return 0


# ─── File mode and survey ─────────────────────────────────────────────

def check_paths(paths: Sequence[str], strict: bool) -> int:
    total = 0
    problems = 0
    for p in paths:
        src = _read(Path(p))
        if src is None:
            print(p + ": not checked (unreadable)")
            problems += 1
            continue
        for f in check_source(src):
            total += 1
            print("%s:%d: [%s] %s — %s" % (p, f.line, f.rule, f.excerpt, f.message))
    print("check-workflow-script: %d finding(s) in %d file(s)%s" %
          (total, len(paths), "" if strict else " (report-only; --strict exits 1)"))
    return 1 if strict and (total or problems) else 0


DEFAULT_ROOTS = ("~/.claude/projects/*/*/workflows/scripts/*.js",
                 "~/.claude-profiles/*/projects/*/*/workflows/scripts/*.js")


def _expand_roots(roots: Sequence[str]) -> List[str]:
    files: List[str] = []
    for root in roots:
        root = os.path.expanduser(root)
        if os.path.isdir(root):
            for dirpath, _dirs, names in os.walk(root):
                files.extend(os.path.join(dirpath, n) for n in names if n.endswith((".js", ".mjs")))
        else:
            files.extend(glob.glob(root))
    return sorted(set(files))


def survey(roots: Sequence[str], as_json: bool) -> int:
    files = _expand_roots(roots or DEFAULT_ROOTS)
    by_hash: Dict[str, str] = {}
    for f in files:
        src = _read(Path(f))
        if src is None:
            continue
        by_hash.setdefault(hashlib.sha256(src.encode("utf-8", "replace")).hexdigest(), f)
    scripts: Dict[str, set] = defaultdict(set)
    sites: Dict[str, int] = defaultdict(int)
    rows = []
    for digest, f in sorted(by_hash.items(), key=lambda kv: kv[1]):
        src = _read(Path(f)) or ""
        for fd in check_source(src):
            scripts[fd.rule].add(digest)
            sites[fd.rule] += 1
            rows.append({"path": f, "sha256": digest[:12], "rule": fd.rule, "line": fd.line,
                         "excerpt": fd.excerpt, "message": fd.message})
    if as_json:
        print(json.dumps({"files": len(files), "unique_scripts": len(by_hash), "findings": rows}, indent=1))
        return 0
    print("check-workflow-script survey: %d file(s), %d unique script(s) by sha256" % (len(files), len(by_hash)))
    print("%-20s %8s %8s" % ("rule", "scripts", "sites"))
    for rule in ("silent-truncation",):
        print("%-20s %8d %8d" % (rule, len(scripts.get(rule, ())), sites.get(rule, 0)))
    print("(args and quota rules read a launch, not a script: they run only in --hook mode)")
    return 0


# ─── Self-test ────────────────────────────────────────────────────────
# Every control goes through hook_main or check_paths — the entry points the
# hook and the CLI use — so removing a guard from either path turns this red.
# Mutations that prove it live in orchestrator/tests/test_self_tests_can_fire.py.

def _payload(tool_input: Dict[str, Any], **extra: Any) -> str:
    d = {"tool_name": "Workflow", "tool_input": tool_input, "cwd": extra.pop("cwd", "/nonexistent"),
         "session_id": "s", "transcript_path": "/dev/null", "permission_mode": "default"}
    d.update(extra)
    return json.dumps(d)


def _decision(out: str) -> Tuple[str, str]:
    if not out:
        return "allow", ""
    h = json.loads(out)["hookSpecificOutput"]
    if h.get("permissionDecision") == "deny":
        return "deny", h.get("permissionDecisionReason", "")
    return "warn", h.get("additionalContext", "")


def self_test() -> int:
    failures: List[str] = []
    tmp = tempfile.mkdtemp(prefix="cws-selftest-")
    env = {"HOME": tmp, "CLAUDE_CONFIG_DIR": os.path.join(tmp, "cfg"), "CLADE_PREFLIGHT_NO_REFRESH": "1"}
    os.makedirs(env["CLAUDE_CONFIG_DIR"])

    def expect(name: str, got: Tuple[str, str], want: str, needle: str = "") -> None:
        if got[0] != want or (needle and needle not in got[1]):
            failures.append("%s: got %s %r, want %s containing %r" % (name, got[0], got[1][:160], want, needle))

    def run(tool_input: Dict[str, Any], **extra: Any) -> Tuple[str, str]:
        return _decision(hook_main(_payload(tool_input, **extra), env))

    cut = "const r = await agent('a')\nawait agent(`check:\\n${JSON.stringify(r).slice(0, 6000)}`)\n"
    expect("truncation in a prompt warns with its line", run({"script": cut}), "warn", "line 2")
    expect("truncation via a variable", run({"script": "const r = await agent('a')\nconst s = JSON.stringify(r)\n"
                                             "await agent('fix: ' + s.slice(0, 4000))\n"}), "warn", "line 3")
    expect("truncation through String() and concatenation",
           run({"script": "const r = await agent('a')\nawait agent(P +\n String(JSON.stringify(r)).slice(0, 7000), {label: 'x'})\n"}),
           "warn", "line 3")
    expect("truncation in a helper-built prompt",
           run({"script": "const mk = (r) => `verify ${JSON.stringify(r).slice(0, 5000)}`\nawait agent(mk(1))\n"}),
           "warn", "line 1")
    expect("truncation assigned then interpolated",
           run({"script": "const r = await agent('a')\nconst brief = JSON.stringify(r).slice(0, 3000)\n"
                          "await agent(`go ${brief}`)\n"}), "warn", "line 2")
    expect("a logged cut is the author's choice",
           run({"script": cut + "log(`cut ${n} of ${m} chars`)\n"}), "allow")
    expect("a log() that names no cut does not excuse one",
           run({"script": cut + "log(`${done.length}/${units.length} units returned`)\n"}), "warn", "line 2")
    expect("the workflow's own templated return value is not a prompt",
           run({"script": "const r = await agent('a')\nreturn `summary ${JSON.stringify(r).slice(0, 5000)}`\n"}), "allow")
    expect("a slice inside a label is metadata",
           run({"script": "await agent('x', { label: `v:${String(t).slice(0, 20)}` })\n"}), "allow")
    expect("a label in an options object built before the call is metadata too",
           run({"script": "const opts = { label: `v:${String(t).slice(0, 20)}`, phase: 'V' }\nawait agent('x', opts)\n"}),
           "allow")
    expect("a slice inside log() is not a prompt",
           run({"script": "log(`r=${JSON.stringify(r).slice(0, 200)}`)\n"}), "allow")
    expect("a chunk walk is not a cut",
           run({"script": "const s = JSON.stringify(r)\nfor (let i = 0; i < s.length; i += 8000) await agent(`part ${s.slice(i, i + 8000)}`)\n"}),
           "allow")
    expect("the workflow's own return value is not a prompt",
           run({"script": "const r = await agent('a')\nreturn JSON.stringify(r).slice(0, 5000)\n"}), "allow")
    expect("a slice in a string literal is text, not code",
           run({"script": "await agent('do not write JSON.stringify(r).slice(0, 10) in prompts')\n"}), "allow")
    expect("an array slice is not a stringified cut",
           run({"script": "await agent(`top ${items.slice(0, 5)}`)\n"}), "allow")

    # The logged-cut exemption reads log()/console.* only. A cut word in a
    # prompt or a phase() title describes the task: 58 of 191 surveyed sites
    # would be excused if any call's text counted.
    expect("a cut word inside an agent() prompt does not excuse a silent cut",
           run({"script": "const r = await agent('cut the scope to P1, drop the rest')\n"
                          "await agent(`check ${JSON.stringify(r).slice(0, 5000)}`)\n"}), "warn", "line 2")
    expect("a phase() title naming a drop does not excuse a silent cut",
           run({"script": "phase('Drop stale units')\nconst r = await agent('a')\n"
                          "await agent(`check ${JSON.stringify(r).slice(0, 5000)}`)\n"}), "warn", "line 3")
    expect("console.log naming the cut excuses it",
           run({"script": cut + "console.log('clipped the check prompt')\n"}), "allow")

    # Reach: every method, receiver and sink the rule claims, and every
    # exclusion — one control each, so removing any one branch turns this red.
    head = "const r = await agent('a')\n"
    for name, body, want in (
            (".substring(0, N)", "await agent(`x ${JSON.stringify(r).substring(0, 500)}`)\n", "warn"),
            (".substr(0, N)", "await agent(`x ${JSON.stringify(r).substr(0, 500)}`)\n", "warn"),
            (".slice(-N) keeps only the tail", "await agent(`x ${JSON.stringify(r).slice(-500)}`)\n", "warn"),
            (".toString() receiver", "await agent(`x ${r.toString().slice(0, 500)}`)\n", "warn"),
            ("a variable assigned from String()", "const s = String(r)\nawait agent(`x ${s.slice(0, 500)}`)\n", "warn"),
            ("a cut pushed onto the prompt's parts",
             "const parts = []\nparts.push(JSON.stringify(r).slice(0, 3000))\nawait agent(parts.join('\\n'))\n", "warn"),
            ("a cut inside an array literal",
             "const parts = ['head', JSON.stringify(r).slice(0, 3000)]\nawait agent(parts.join('\\n'))\n", "warn"),
            ("a cut joined with +", "const p = 'fix: ' + JSON.stringify(r).slice(0, 3000)\nawait agent(p)\n", "warn"),
            ("a cut read through a ternary", "const b = JSON.stringify(r).slice(0, 3000)\n"
             "await agent(`go ${ok ? b : ''}`)\n", "warn"),
            ("a regex literal holding a backtick does not open a template",
             "const t = s.replace(/`/g, \"'\")\nawait agent(`check ${JSON.stringify(r).slice(0, 5000)}`)\n", "warn"),
            ("a bare return on the line before does not swallow the next statement",
             "if (!r) return\nnotes.push(`prior: ${JSON.stringify(r).slice(0, 4000)}`)\nawait agent(notes.join('\\n'))\n",
             "warn"),
            ("a value a function returns into a variable a prompt reads",
             "let memo\nfunction f(x) { return memo = JSON.stringify(x).slice(0, 500) }\nawait agent(`x ${memo}`)\n", "warn"),
            ("an index key is not a prompt", "const seen = {}\nseen[JSON.stringify(r).slice(0, 80)] = true\n", "allow"),
            ("a condition is not a prompt",
             "if (`${JSON.stringify(r).slice(0, 200)}` === prev) log('same')\n", "allow"),
            ("an agent() option is not a prompt",
             "await agent('x', { cacheKey: JSON.stringify(r).slice(0, 64) })\n", "allow"),
            ("a line comment is not code", "// await agent(`x ${JSON.stringify(r).slice(0, 5000)}`)\n", "allow"),
            ("a block comment is not code", "/*\nawait agent(`x ${JSON.stringify(r).slice(0, 5000)}`)\n*/\n", "allow"),
            ("an object key that shares the variable's name is not a read",
             "const b = JSON.stringify(r).slice(0, 3000)\nawait agent(`go ${JSON.stringify({ n: 1, b: 2 })}`)\n", "allow"),
            ("an assignment target is not a read",
             "let b = JSON.stringify(r).slice(0, 3000)\nlet p\np = b = ''\nawait agent(p)\n", "allow")):
        expect("reach: " + name, run({"script": head + body}), want, "silent-truncation" if want == "warn" else "")

    # Placeholder args: every sentinel shape the host's 10 bad launches used.
    for shape in (["__FROM_FILE__"], {"payload": "__FILE__"}, {"buckets": "__FILL__"}, '"__ARGS_PLACEHOLDER__"',
                  [{"__see": "review-units"}], {"__file": "doc-units"}, [{"id": "P", "files": ["(see packet file)"]}],
                  {"ids": "..."}, {"ids": "…"}, {"path": "<scratch path>"}, {"x": "placeholder"},
                  {"x": "[elided]"}, {"x": "(truncated 4000 chars)"}):
        expect("placeholder %s denies" % json.dumps(shape)[:40], run({"script": "return 1", "args": shape}),
               "deny", "placeholder")
    expect("deny names the leaf path", run({"script": "return 1", "args": {"deploy_ids": ["__RESOLVED_AND_PARTIAL__"]}}),
           "deny", "args.deploy_ids[0]")
    two = run({"script": "return 1", "args": {"a": "__FILL__", "b": ["ok", "(see packet file)"]}})
    expect("deny names every placeholder leaf, not only the first", two, "deny", "args.b[1]")
    expect("…including the first", two, "deny", "args.a")
    expect("a JSON-encoded string is decoded before it is matched",
           run({"script": "return 1", "args": '"\\u2026"'}), "deny", "ellipsis")
    # 50 placeholder leaves under long keys plus a 40-site script: the reason
    # stays inside DENY_BUDGET and still opens with what to do instead.
    many_keys = {("k%02d_" % i) + "x" * 500: "__FILL__" for i in range(50)}
    many_cuts = "const r = await agent('a')\n"
    many_cuts += "".join("await agent(`c%d ${JSON.stringify(r).slice(0, %d)}`)\n" % (i, 900 + i) for i in range(40))
    big = run({"script": many_cuts, "args": many_keys})
    expect("a 50-leaf deny names the overflow", big, "deny", "(and 46 more)")
    expect("a 50-leaf deny keeps the instruction", big, "deny", "expected count the script asserts")
    if len(big[1]) > DENY_BUDGET:
        failures.append("a 50-leaf deny with 40 warnings is %d chars, over DENY_BUDGET %d" % (len(big[1]), DENY_BUDGET))
    for clean in ({"ids": ["P01", "P02"], "n": 2}, {"note": "replace the placeholder text in the hero"},
                  {"items": [{"id": "a", "status": "todo"}], "fit": "fill"}, {"sep": "<br>"},
                  {"methods": ["__init__", "__eq__"]}, {"node": {"__typename": "User"}},
                  {"since": "(from 2024 onward)"}, {"link": "<https://example.com/a>"}, {"note": "(refer to the spec)"},
                  {"task": "the macro __FILE__ expands to the path"}, {"task": "__FILE__ expands to the path"},
                  {"html": "<div class=\"x\">a</div>"},
                  {"creates": [], "see": "(see below for details) the rest"}, [1, 2, 3], "plain words"):
        expect("clean args %s pass" % json.dumps(clean)[:40], run({"script": "return 1", "args": clean}), "allow")
    expect("stringified args warn", run({"script": "return 1", "args": json.dumps({"ids": ["a"]})}), "warn", "JSON-encoded")
    expect("deny wins over warn",
           run({"script": cut, "args": [{"__see": "units"}]}), "deny", "silent-truncation")

    # Independence: a crash or a deadline in the script stage must not drop the deny.
    def boom(_src: str) -> List[Finding]:
        raise RuntimeError("scanner crashed")

    def out_of_time(_src: str) -> List[Finding]:
        raise _Deadline()

    def slow_scan(_src: str) -> List[Finding]:
        time.sleep(3)
        return []
    try:
        SCANNER[0] = boom
        expect("deny survives a crashing script stage", run({"script": "x", "args": ["__FILL__"]}), "deny")
        SCANNER[0] = out_of_time
        expect("deny survives the deadline firing in the script stage",
               run({"script": "x", "args": ["__FILL__"]}), "deny")
        # The real timer, through run_hook's stdin/stdout: a scanner that
        # would take 3 s is cut off at the 0.3 s deadline and the deny prints.
        SCANNER[0] = slow_scan
        saved = {k: os.environ.get(k) for k in env.keys() | {"CLADE_PREFLIGHT_DEADLINE"}}
        os.environ.update(env, CLADE_PREFLIGHT_DEADLINE="0.3")
        stdin, stdout, buf = sys.stdin, sys.stdout, io.StringIO()
        t0 = time.time()
        try:
            sys.stdin, sys.stdout = io.StringIO(_payload({"script": "x", "args": ["__FILL__"]})), buf
            rc = run_hook()
        finally:
            sys.stdin, sys.stdout = stdin, stdout
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        took = time.time() - t0
        expect("the deadline cuts a slow scan short and still prints the deny",
               _decision(buf.getvalue().strip()), "deny", "placeholder")
        if rc != 0 or took > 2.0:
            failures.append("deadline: run_hook rc=%d after %.1fs (a 0.3 s deadline over a 3 s scan)" % (rc, took))
    finally:
        SCANNER[0] = check_source
        _disarm_deadline()

    # No cwd in the payload, run from a directory that was removed:
    # os.getcwd() raises, and that must cost only the script stage.
    here = os.getcwd()
    gone = os.path.join(tmp, "gone")
    os.makedirs(gone)
    try:
        os.chdir(gone)
        os.rmdir(gone)
        no_cwd = json.dumps({"tool_name": "Workflow", "tool_input": {"script": "return 1", "args": ["__FILL__"]}})
        expect("a payload with no cwd, from a removed directory, is still denied",
               _decision(hook_main(no_cwd, {k: v for k, v in env.items() if k != "CLAUDE_PROJECT_DIR"})), "deny")
    finally:
        os.chdir(here)

    # Resolution: scriptPath, saved name, unresolvable name.
    proj = os.path.join(tmp, "proj")
    os.makedirs(os.path.join(proj, ".claude", "workflows"))
    with open(os.path.join(proj, ".claude", "workflows", "saved.js"), "w") as fh:
        fh.write(cut)
    with open(os.path.join(tmp, "path.js"), "w") as fh:
        fh.write(cut)
    expect("scriptPath is read", run({"scriptPath": os.path.join(tmp, "path.js")}), "warn", "line 2")
    expect("saved name is resolved under cwd", run({"name": "saved"}, cwd=proj), "warn", "line 2")
    os.makedirs(os.path.join(env["CLAUDE_CONFIG_DIR"], "workflows"))
    with open(os.path.join(env["CLAUDE_CONFIG_DIR"], "workflows", "user.mjs"), "w") as fh:
        fh.write(cut)
    expect("saved name falls back to the config dir", run({"name": "user"}, cwd=proj), "warn", "line 2")
    expect("unresolvable name is silent", run({"name": "missing"}, cwd=proj), "allow")
    with open(os.path.join(proj, ".claude", "outside.js"), "w") as fh:
        fh.write(cut)
    expect("a name that climbs out of workflows/ is not read", run({"name": "../outside"}, cwd=proj), "allow")
    expect("malformed stdin is silent", _decision(hook_main("{not json", env)), "allow")
    expect("another tool is ignored, whatever its input carries",
           _decision(hook_main(json.dumps({"tool_name": "Bash", "tool_input": {"command": "x", "args": ["__FILL__"]}}),
                               env)), "allow")
    expect("a subagent launch is checked the same", run({"script": "return 1", "args": ["__FILL__"]}, agent_id="a1"), "deny")

    # Quota: fresh and hot warns; stale, missing, cool or past-reset says nothing.
    cache = os.path.join(env["CLAUDE_CONFIG_DIR"], "usage-watch-cache.json")
    future = "2999-01-01T00:00:00+00:00"

    def write_cache(age: float, seven: float, five: float, resets: str = future) -> None:
        with open(cache, "w") as fh:
            json.dump({"_at": time.time() - age, "seven_day": {"utilization": seven, "resets_at": resets},
                       "five_hour": {"utilization": five, "resets_at": resets}}, fh)
    # Literal numbers, not the constants: a control written as
    # QUOTA_MAX_AGE_S + 60 moves with the constant and pins nothing.
    for age, seven, five, want, needle in (
            (30, 93, 10, "warn", "7-day at 93%"), (30, 20, 88, "warn", "5-hour at 88%"),
            (30, 90, 10, "warn", "7-day at 90%"), (30, 89.9, 10, "allow", ""),
            (30, 10, 85, "warn", "5-hour at 85%"), (30, 10, 84.9, "allow", ""),
            (540, 95, 10, "warn", "7-day at 95%"), (660, 95, 10, "allow", ""), (3600, 99, 99, "allow", ""),
            (-300, 99, 99, "allow", ""), (30, 40, 30, "allow", "")):
        write_cache(age, seven, five)
        expect("quota: %ss old, 7-day %s%%, 5-hour %s%%" % (age, seven, five), run({"script": "return 1"}), want, needle)
    write_cache(30, 99, 99, resets="2000-01-01T00:00:00+00:00")
    expect("a reading from a past window says nothing", run({"script": "return 1"}), "allow")
    for name, doc in (("no _at", {"seven_day": {"utilization": 99}, "five_hour": {"utilization": 99}}),
                      ("a non-numeric utilization", {"_at": time.time(), "seven_day": {"utilization": "99%"},
                                                     "five_hour": {"utilization": None}})):
        with open(cache, "w") as fh:
            json.dump(doc, fh)
        expect("a hot cache with %s says nothing" % name, run({"script": "return 1"}), "allow")
    os.remove(cache)
    expect("a missing cache says nothing", run({"script": "return 1"}), "allow")

    # File mode goes through check_paths.
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = check_paths([os.path.join(tmp, "path.js")], strict=True)
    if rc != 1 or ":2: [silent-truncation]" not in buf.getvalue():
        failures.append("file mode: rc=%d output=%r" % (rc, buf.getvalue()[:200]))

    shutil.rmtree(tmp, ignore_errors=True)
    if failures:
        print("check-workflow-script --self-test: FAILED (%d)" % len(failures))
        for f in failures:
            print("  " + f)
        return 1
    print("check-workflow-script --self-test: PASSED")
    return 0


# ─── CLI ──────────────────────────────────────────────────────────────

def main(argv: Sequence[str]) -> int:
    args = list(argv)
    if "--hook" in args:
        return run_hook()
    if "--self-test" in args:
        return self_test()
    if "--survey" in args:
        roots = [a for a in args if not a.startswith("--")]
        return survey(roots, "--json" in args)
    strict = "--strict" in args
    paths = [a for a in args if not a.startswith("--")]
    if not paths:
        print(__doc__)
        return 2
    return check_paths(paths, strict)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
