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
# the reasoning is recorded there. Quotes, backslashes, comments and heredoc
# bodies are honoured; statements split on ; & | ( ) ` $( and newlines, but
# not on the & of 2>&1; only a `git [global opts] push` statement is read.
_SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
_KEYWORDS = frozenset({"{", "}", "!", "if", "then", "elif", "else", "fi",
                       "for", "while", "until", "do", "done", "time"})
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _segments(command: str) -> list[list[tuple[int, int, str]]]:
    """Statements as lists of (start, end, unquoted value) tokens."""
    n = len(command)
    i = 0
    quote = ""
    tok: list | None = None
    seg: list[tuple[int, int, str]] = []
    segs: list[list[tuple[int, int, str]]] = []
    heredocs: list[tuple[str, bool]] = []

    def flush(end: int) -> None:
        nonlocal tok
        if tok is not None:
            seg.append((tok[0], end, tok[1]))
            tok = None

    def end_seg(end: int) -> None:
        nonlocal seg
        flush(end)
        if seg:
            segs.append(seg)
        seg = []

    while i < n:
        c = command[i]
        if quote == "'":
            if c == "'":
                quote = ""
            else:
                tok[1] += c
            i += 1
            continue
        if quote == '"':
            if c == "\\" and i + 1 < n and command[i + 1] in '\\"$`':
                tok[1] += command[i + 1]
                i += 2
                continue
            if c == '"':
                quote = ""
            else:
                tok[1] += c
            i += 1
            continue
        if c == "\\":
            if command[i + 1:i + 2] == "\n":
                i += 2
                continue
            if tok is None:
                tok = [i, ""]
            tok[1] += command[i + 1:i + 2]
            i += 2
            continue
        if c in "'\"":
            if tok is None:
                tok = [i, ""]
            quote = c
            i += 1
            continue
        if c in " \t":
            flush(i)
            i += 1
            continue
        if c == "#" and tok is None:
            while i < n and command[i] != "\n":
                i += 1
            continue
        if c == "\n":
            end_seg(i)
            i += 1
            for delim, strip in heredocs:
                while i < n:
                    e = command.find("\n", i)
                    line = command[i:e] if e >= 0 else command[i:]
                    i = e + 1 if e >= 0 else n
                    if strip:
                        line = line.lstrip("\t")
                    if line == delim:
                        break
            heredocs = []
            continue
        if c == "$" and command[i + 1:i + 2] == "(":
            end_seg(i)
            i += 2
            continue
        if c in ";|()`":
            end_seg(i)
            i += 1
            continue
        if c == "&":
            if (i > 0 and command[i - 1] in "<>") or command[i + 1:i + 2] == ">":
                if tok is None:
                    tok = [i, ""]
                tok[1] += c
                i += 1
                continue
            end_seg(i)
            i += 1
            continue
        if command.startswith("<<", i) and not command.startswith("<<<", i):
            flush(i)
            j = i + 2
            strip = False
            if command[j:j + 1] == "-":
                strip = True
                j += 1
            while command[j:j + 1] in (" ", "\t") and j < n:
                j += 1
            qc = command[j:j + 1]
            if qc in ("'", '"'):
                j += 1
            else:
                qc = ""
            m = re.match(r"[A-Za-z0-9_]+", command[j:])
            word = m.group(0) if m else ""
            j += len(word)
            if qc and command[j:j + 1] == qc:
                j += 1
            if word:
                heredocs.append((word, strip))
            i = j
            continue
        if tok is None:
            tok = [i, ""]
        tok[1] += c
        i += 1
    end_seg(n)
    return segs


def _dst(ref: str) -> str:
    return re.sub(r"^refs/heads/", "", ref.rsplit(":", 1)[-1])


def _facts(text: str) -> bool:
    """The three facts of a force push to main, read from TEXT — only where
    the command cannot be walked (bash -c / eval / ssh strings, and the whole
    command when a shell reads its script from stdin)."""
    for part in re.split(r"[;&|\n]", text):
        p = " " + part + " "
        if (re.search(r"[ \t'\"(]git[ \t]+(?:[^ \t]+[ \t]+)*?push[ \t]", p)
                and (re.search(r"[ \t](?:--force|--force-with-lease[^ \t]*|-[A-Za-z]*f[A-Za-z]*)[ \t'\"]", p)
                     or re.search(r"[ \t]\+[^ \t]", p))
                and re.search(r"[ \t:+/'\"](?:main|master)(?:[ \t'\"]|\\)", p)):
            return True
    return False


def _nested_force_main(values: list[str]) -> bool:
    return _facts("".join(" " + v for v in values))


def _shell_reads(vals: list[str], k: int) -> tuple[str, int]:
    """("c", start) for -c, ("stdin", 0) when the shell reads its script from
    stdin, ("file", 0) when it runs a script file the command does not show."""
    j = k + 1
    while j < len(vals):
        v = vals[j]
        if v == "-c" or (re.match(r"^-[A-Za-z]+$", v) and "c" in v):
            return ("c", j + 1)
        if v == "-s":
            return ("stdin", 0)
        if v in ("-o", "+o", "-O", "+O", "--rcfile", "--init-file"):
            j += 2
            continue
        if v[:1] in ("-", "+"):
            j += 1
            continue
        return ("file", 0)
    return ("stdin", 0)


def _ssh_command(vals: list[str], k: int) -> int | None:
    """Index of the remote command after `ssh [opts] host`; -1 when there is
    none (ssh then runs a shell on stdin); None when there is no host."""
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
        return None
    return -1 if j == len(vals) - 1 else j + 1


def _force_push(command: str, branch: str) -> tuple[str, str] | None:
    """("block", main|branch|delete|nested), ("rewrite", new command) or None."""
    blocked = ""
    cd_seen = False
    stdin_shell = False
    edits: list[tuple[int, int, str]] = []
    for seg in _segments(command):
        vals = [t[2] for t in seg]
        k = 0
        while k < len(seg) and (_ASSIGN.match(vals[k]) or vals[k] in _KEYWORDS):
            k += 1
        if k < len(seg) and vals[k].rsplit("/", 1)[-1] in ("cd", "pushd"):
            cd_seen = True
            continue
        # The command can sit behind any prefix (timeout 60, sudo -u bob,
        # xargs -I{}, then, do, {): the first word this guard reads decides.
        k = next((i for i, v in enumerate(vals)
                  if v.rsplit("/", 1)[-1] in ("git", "ssh", "eval") or v.rsplit("/", 1)[-1] in _SHELLS), None)
        if k is None:
            continue
        word = vals[k].rsplit("/", 1)[-1]
        if word in _SHELLS:
            how, start = _shell_reads(vals, k)
            if how == "c" and _nested_force_main(vals[start:]):
                blocked = blocked or "nested"
            elif how == "stdin":
                stdin_shell = True
            continue
        if word == "ssh":
            at = _ssh_command(vals, k)
            if at == -1:
                stdin_shell = True
            elif at is not None and _nested_force_main(vals[at:]):
                blocked = blocked or "nested"
            continue
        if word == "eval":
            if _nested_force_main(vals[k + 1:]):
                blocked = blocked or "nested"
            continue
        k += 1
        has_c = False
        while k < len(seg):
            v = vals[k]
            if v in ("-C", "-c", "--git-dir", "--work-tree", "--namespace"):
                if v != "-c":
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
        if k >= len(seg) or vals[k] != "push":
            continue
        pk = k
        skip = dd = False
        npos = nrefs = 0
        lease = allrefs = mainref = delete = headref = False
        forces: list[int] = []
        pluses: list[int] = []
        for j in range(pk + 1, len(seg)):
            v = vals[j]
            if skip:
                skip = False
                continue
            if re.match(r"^[0-9]*[<>]", v) or v.startswith("&>"):
                if re.match(r"^[0-9]*[<>]+&?$", v) or re.match(r"^&>>?$", v):
                    skip = True
                continue
            if not dd and v == "--":
                dd = True
                continue
            if not dd and v.startswith("--"):
                if v == "--force":
                    forces.append(j)
                elif v.startswith("--force-with-lease") or v == "--force-if-includes":
                    lease = True
                elif v in ("--all", "--mirror", "--branches"):
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
            if _dst(ref) in ("main", "master"):
                mainref = True
                if ref.startswith(":"):
                    delete = True
            # HEAD and @ name the current branch, which the text does not.
            if _dst(ref) in ("HEAD", "@"):
                headref = True
            if plus:
                pluses.append(j)
        if delete and mainref:
            blocked = blocked or "delete"
            continue
        if not forces and not pluses and not lease:
            continue
        if mainref or (allrefs and (forces or pluses)):
            blocked = blocked or "main"
            continue
        if ((nrefs == 0 or headref) and not allrefs and not cd_seen and not has_c
                and branch in ("main", "master")):
            blocked = blocked or "branch"
            continue
        if not forces and not pluses:
            continue
        for j in forces:
            v = vals[j]
            if v in ("--force", "-f"):
                new = "--force-with-lease"
            else:
                rest = v.replace("f", "")
                new = "--force-with-lease" if rest == "-" else rest + " --force-with-lease"
            edits.append((seg[j][0], seg[j][1], new))
        for j in pluses:
            raw = command[seg[j][0]:seg[j][1]].replace("+", "", 1)
            edits.append((seg[j][0], seg[j][1], raw))
        if not forces and not lease:
            edits.append((seg[pk][1], seg[pk][1], " --force-with-lease"))
    if stdin_shell and _facts(command):
        blocked = blocked or "nested"
    if blocked:
        return ("block", blocked)
    if not edits:
        return None
    out = command
    for start, end, text in sorted(edits, key=lambda e: e[0], reverse=True):
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

    pushed = _force_push(command, branch) if "push" in command else None
    if pushed is not None:
        kind, detail = pushed
        if kind == "block":
            why = {
                "branch": f"it pushes the current branch, which is {branch}",
                "delete": "it deletes main/master on the remote",
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
    branch = _current_branch(event.get("cwd") or os.getcwd()) if "push" in command else ""
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
