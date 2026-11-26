"""
ci_local_runner.py — what a GitHub runner gives a job that the workflow text
does not spell out. Imported by ci-local.py, which sits near this repository's
1500-line cap; installed and bundled beside it.

Six things. The first three were found by running ci-local.py against real
repositories that moved their CI to owned hardware (scamai, 2026-11-21):

1. **Which machine a `runs-on:` can land on.** GitHub matches runner labels
   case-insensitively, and a self-hosted runner carries OS labels spelled
   `macOS`, `Linux`, `Windows` and architecture labels `X64`, `ARM`, `ARM64`.
   ci-local.py matched lower-case substrings of the raw value, so
   `[self-hosted, macOS, macserver-public]` named no platform at all: it RAN
   on Linux, and a witty macOS job's steps executed on a Linux host.
2. **Which pushes start a workflow.** A push trigger whose only filters are
   `tags:`/`tags-ignore:` fires for tags and never for a branch. Run on a
   branch head, such a workflow's "tag matches version" check failed by
   construction (email-town-labeler's release.yml read `GITHUB_REF_NAME` as
   empty), so every non-tag gate of that repository read `fail`.
3. **The files and variables every step gets.** `$GITHUB_ENV`, `$GITHUB_PATH`,
   `$GITHUB_OUTPUT`, `$GITHUB_STEP_SUMMARY`, `$RUNNER_TEMP` and
   `$GITHUB_WORKSPACE` were unset, so `echo dir >> "$GITHUB_PATH"` failed
   with `bash: : No such file or directory`. Inside a hosted job (this
   repository's own CI runs ci-local's tests) a step inherited the OUTER
   job's files instead, and wrote into the outer job's environment.
4. **What a throwaway runner may do and this host may not.** A hosted runner
   is a VM deleted after the job, and workflows treat it so: a "Free up disk
   space" step runs `sudo rm -rf /usr/share/dotnet /opt/ghc` and
   `docker image prune -a -f`. On 2026-11-25 ci-local.py ran one on a
   persistent host with passwordless sudo, and the prune deleted 316 GB of
   that host's Docker images. Such a step is not run unless
   --allow-host-mutation says the machine is throwaway.
5. **A global prefix nobody else uses.** A runner is a fresh machine per job,
   so a step's `npm install -g` writes into a prefix of its own. Here it wrote
   into the developer's (2026-11-17, the first gate of #251): two gates at
   once raced there and one failed with npm `ENOTEMPTY`, and a gate replaced
   the user's own installed CLI. A step that uses nvm is the exception (5).
6. **The shell a step runs in.** `bash -eo pipefail -c`, with no stdin and a
   timeout whose default scales with the host's load, all its output kept:
   the tail is what a report shows, and nvm's refusal of the prefix (5) can
   sit anywhere in it, which runs the step again without the prefix. Moved
   here from ci-local.py, at its line cap, on 2026-11-25 and 2026-11-26.

Stdlib only, like ci-local.py.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

# ─── YAML fragments ──────────────────────────────────────────────────────────


def _uncomment(line: str) -> str:
    return re.sub(r"(^|\s)#.*$", "", line).rstrip()


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def flow_items(text: str) -> list[tuple[str, str]]:
    """Top-level `(name, value)` items of a flow value: `push`,
    `[push, pull_request]`, or `{push: {tags: [v*]}, workflow_dispatch: {}}`.
    A bare name has the value ""."""
    t = text.strip()
    if t[:1] in ("[", "{"):
        t = t[1:-1] if t[-1:] in ("]", "}") else t[1:]
    items, depth, cur = [], 0, ""
    for c in t:
        depth += (c in "[{") - (c in "]}")
        if c == "," and depth == 0:
            items.append(cur)
            cur = ""
        else:
            cur += c
    items.append(cur)
    out = []
    for it in items:
        if it.strip():
            name, _, value = it.partition(":")
            out.append((name.strip().strip("'\""), value.strip()))
    return out


def flow_names(text: str) -> list[str]:
    """Top-level names of a flow value (see flow_items)."""
    return [name for name, _ in flow_items(text)]


# ─── 1. Runner labels ────────────────────────────────────────────────────────
# A label names an OS when it holds one of these words, whatever its case:
# the self-hosted OS labels (macOS, Linux, Windows), the hosted images
# (ubuntu-24.04, macos-15, windows-2022) and third-party runner profiles built
# on them (namespace-profile-ghostty-macos-tahoe). An architecture is named by
# a self-hosted label exactly, or by a hosted image's `-arm` suffix
# (ubuntu-24.04-arm, windows-11-arm). A label naming neither — `self-hosted`,
# `macserver-public`, a runner group — says nothing about the platform, and a
# job with no platform label at all runs here, as it always did.
_OS_WORDS = (("macos", "Darwin"), ("windows", "Windows"), ("ubuntu", "Linux"), ("linux", "Linux"))
_ARCH_LABELS = {"x64": "X64", "arm": "ARM", "arm64": "ARM64"}


def runs_on_labels(runs_on: str) -> list[str]:
    """The labels of a `runs-on:` value as ci-local.py collected it: one line
    (`ubuntu-latest`, `[self-hosted, macOS]`, `{group: g, labels: [a, b]}`) or
    the lines under a bare `runs-on:` (a `- label` list, or a mapping whose
    `labels:` holds them; a `group:` name is not a label)."""
    labels: list[str] = []
    for raw in runs_on.splitlines():
        line = _uncomment(raw).strip()
        if line.startswith("- "):
            line = line[2:].strip()
        if line.startswith("{"):
            labels += [lb for k, v in flow_items(line) if k == "labels" for lb in flow_names(v)]
            continue
        key, colon, rest = line.partition(":")
        if colon and key.strip() in ("labels", "group"):
            labels += flow_names(rest) if key.strip() == "labels" and rest.strip() else []
            continue
        labels += flow_names(line)
    return [lb for lb in labels if lb]


def machine_arch(machine: str) -> str:
    """platform.machine() in the runner's own spelling (X64, ARM64, ARM)."""
    m = machine.lower()
    if m in ("x86_64", "amd64", "x64"):
        return "X64"
    if m in ("aarch64", "arm64"):
        return "ARM64"
    return "ARM" if m.startswith("arm") else machine


def platform_need(runs_on: str, system: str, machine: str) -> str | None:
    """Why a job with this `runs-on:` cannot land on a host of this
    platform.system() and platform.machine(), or None when it can (or when its
    labels name no platform). Labels compare case-insensitively, as GitHub
    matches them."""
    labels = [lb.lower() for lb in runs_on_labels(runs_on)]
    systems = {s for lb in labels for word, s in _OS_WORDS if word in lb}
    if systems and system not in systems:
        return f"needs {'/'.join(sorted(systems))}; this machine is {system}"
    arches = {_ARCH_LABELS[lb] for lb in labels if lb in _ARCH_LABELS}
    arches |= {"ARM64" for lb in labels if lb.endswith("-arm") and any(w in lb for w, _ in _OS_WORDS)}
    here = machine_arch(machine)
    if arches and here not in arches:
        return f"needs {'/'.join(sorted(arches))}; this machine is {here}"
    return None


# ─── 2. Tag-only push tiers ──────────────────────────────────────────────────
# Events that never start a run for a branch push or a pull request. A workflow
# whose push trigger filters on tags alone, and whose every other trigger is in
# this list, is a tag tier: the hosted run of a branch push or PR never
# executes it, exactly as it never executes a schedule tier. Any other trigger
# (pull_request, workflow_call, workflow_run, merge_group, create …) may start
# it on that path, so the workflow stays a push/PR workflow, as it was read
# before this tier existed.
_OFF_PUSH_PR = frozenset({"workflow_dispatch", "schedule", "release", "repository_dispatch"})


def push_filters(on_block: str) -> dict[str, str] | None:
    """The filters under an `on:` block's push trigger, name -> value text
    ({"tags": '["v*"]'}; {} for a bare push), or None when push is not a
    trigger. Flow and block styles, comments ignored."""
    lines = [ln for ln in (_uncomment(x) for x in on_block.splitlines()) if ln.strip()]
    if not lines:
        return None
    head = lines[0].split(":", 1)[1].strip() if ":" in lines[0] else ""
    if head:                                   # on: push | [push, …] | {push: {…}}
        value = dict(flow_items(head)).get("push")
        return None if value is None else dict(flow_items(value)) if value.startswith("{") else {}
    body = lines[1:]
    if not body:
        return None
    pad = min(_indent(ln) for ln in body)
    for i, ln in enumerate(body):
        if _indent(ln) != pad:
            continue
        item = ln.strip()
        if item.startswith("- "):              # on:\n  - push
            if item[2:].strip().strip("'\"") == "push":
                return {}
            continue
        name, _, rest = item.partition(":")
        if name.strip().strip("'\"") != "push":
            continue
        if rest.strip():
            return dict(flow_items(rest)) if rest.strip().startswith("{") else {}
        kids = []
        for nxt in body[i + 1:]:
            if _indent(nxt) <= pad:
                break
            kids.append(nxt)
        if not kids:
            return {}
        kid_pad = min(_indent(k) for k in kids)
        return {k.strip().partition(":")[0].strip().strip("'\""): k.strip().partition(":")[2].strip()
                for k in kids if _indent(k) == kid_pad}
    return None


def tag_tier(on_block: str, triggers: set[str]) -> str | None:
    """The tag filter of a workflow that only a tag push starts — e.g.
    `tags: ["v*"]` — or None. `triggers` is the workflow's event names."""
    filters = push_filters(on_block)
    if filters is None or "push" not in triggers:
        return None
    if not filters.keys() & {"tags", "tags-ignore"} or filters.keys() & {"branches", "branches-ignore"}:
        return None
    if not triggers - {"push"} <= _OFF_PUSH_PR:
        return None
    key = "tags" if "tags" in filters else "tags-ignore"
    return f"{key}: {filters[key]}" if filters[key] else key   # a block list shows its key


def head_tags(repo: Path) -> list[str]:
    """The tags pointing at the checkout's HEAD; [] outside git."""
    try:
        proc = subprocess.run(["git", "-C", str(repo), "tag", "--points-at", "HEAD"],
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return proc.stdout.split() if proc.returncode == 0 else []


# ─── 3. What every step gets ─────────────────────────────────────────────────


def parse_env_file(text: str) -> tuple[dict[str, str], str]:
    """$GITHUB_ENV as the runner reads it: `NAME=value` lines, and
    `NAME<<DELIMITER` … `DELIMITER` for a multi-line value. (pairs, error); a
    non-empty error is what makes the runner fail the step that wrote it."""
    out: dict[str, str] = {}
    lines = [ln.rstrip("\r") for ln in text.split("\n")]
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line:
            continue
        eq, here = line.find("="), line.find("<<")
        if eq > 0 and (here < 0 or eq < here):
            name, value = line.split("=", 1)
        elif here > 0:
            name, delimiter = line.split("<<", 1)
            if not delimiter:
                return out, f"invalid format {line[:60]!r}"
            body: list[str] = []
            while i < len(lines) and lines[i] != delimiter:
                body.append(lines[i])
                i += 1
            if i >= len(lines):
                return out, f"matching delimiter not found {delimiter[:40]!r}"
            i += 1
            value = "\n".join(body)
        else:
            return out, f"invalid format {line[:60]!r}"
        out[name] = value
    return out, ""


def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""      # a step may delete its own command file


class JobFiles:
    """The per-job directory a runner gives a job: an empty RUNNER_TEMP, and a
    fresh set of command files for every step attempt. What a step writes to
    $GITHUB_ENV and $GITHUB_PATH reaches the later steps of the same job, and
    no other job. $GITHUB_OUTPUT and $GITHUB_STEP_SUMMARY are written and not
    read: ci-local.py evaluates no `${{ steps.<id>.outputs.* }}`, so a step
    reading one stays unproven, as before. $GITHUB_STATE likewise."""

    # $GITHUB_STATE too: only an action's post step reads it, but a run: step
    # inside a hosted job must not write the outer job's.
    _COMMANDS = {"GITHUB_ENV": "set_env", "GITHUB_PATH": "add_path", "GITHUB_OUTPUT": "set_output",
                 "GITHUB_STEP_SUMMARY": "step_summary", "GITHUB_STATE": "save_state"}

    def __init__(self, workspace: Path) -> None:
        # TemporaryDirectory removes itself when collected, so an interrupted
        # run leaves nothing behind either.
        self._dir = tempfile.TemporaryDirectory(prefix="ci-local-job-")
        root = Path(self._dir.name)
        self.workspace = workspace
        self.temp = root / "temp"
        self.temp.mkdir()
        self._commands = root / "commands"
        self._commands.mkdir()
        # npm's global prefix for this job's steps (isolate_npm_global).
        self.npm_prefix = root / "npm-prefix"
        self.npm_prefix.mkdir()
        # Written by earlier steps: env (NAME -> value) and PATH entries, the
        # newest first, as the runner prepends them.
        self.env: dict[str, str] = {}
        self.path: list[str] = []
        self._attempt = 0
        self._current: dict[str, str] = {}

    def begin_step(self) -> dict[str, str]:
        """Empty command files for one step attempt, and the variables that
        name them. A rerun gets new files: the failed attempt's writes are not
        applied."""
        self._attempt += 1
        self._current = {}
        for var, stem in self._COMMANDS.items():
            path = self._commands / f"{stem}_{self._attempt}"
            path.write_text("", encoding="utf-8")
            self._current[var] = str(path)
        return {**self._current, "RUNNER_TEMP": str(self.temp),
                "GITHUB_WORKSPACE": str(self.workspace)}

    def end_step(self) -> str:
        """Apply the passing attempt's $GITHUB_ENV and $GITHUB_PATH to the
        later steps. Returns why the runner would fail the step instead ("" when
        it would not)."""
        env, error = parse_env_file(_read(self._current.get("GITHUB_ENV", "")))
        if error:
            return f"$GITHUB_ENV: {error} (the runner fails the step that wrote it)"
        self.env.update(env)
        for line in _read(self._current.get("GITHUB_PATH", "")).split("\n"):
            entry = line.rstrip("\r")
            if entry:
                if entry in self.path:
                    self.path.remove(entry)
                self.path.insert(0, entry)
        return ""

    def close(self) -> None:
        self._dir.cleanup()


# ─── 4. Commands that change the host ────────────────────────────────────────
# A step holding any of these is written for a VM that is deleted after the
# job, and is not run here unless --allow-host-mutation says this machine is
# one:
#   - sudo, in any form;
#   - docker system/image/builder/buildx/volume/container/network prune, and a
#     docker rmi or image rm of every image (-a, names from $(docker images),
#     backticks or xargs, or no name at all); a named image is left alone;
#   - rm of a path outside the checkout and $RUNNER_TEMP: an absolute path
#     (/tmp included: other users' and sessions' files live there), ~ or $HOME.
#     A workflow cannot name this machine's checkout by an absolute path, so
#     it names it $GITHUB_WORKSPACE, $PWD or a relative path, none of which
#     is flagged;
#   - apt/apt-get/aptitude remove, purge, autoremove; dpkg --remove/--purge.
# A step is SETUP when every command in it is host setup or cleanup (package
# installs, removals, prunes) or only reports (echo, df, docker images): it
# tests nothing, so skipping it leaves no lane unproven — if a later gate
# needed what it installs, that gate fails here, visibly. Any other step with
# such a command is a gate this run did not execute: unproven.
#
# The scan is a rough shell lexer, not a parser: it splits on ; & | ( ) and
# newlines outside quotes, scans $( ) and backticks as scripts of their own,
# and looks inside `bash -c '…'` and eval. It guards against workflows written
# for hosted runners, not against a workflow hiding a command on purpose
# ($SUDO, a script file that runs sudo). A heredoc body is read as commands,
# which fails closed: a word there can skip a step, never run one.

_HOME_ROOTS = ("~", "$HOME", "${HOME}")
_PREFIX_WORDS = frozenset({"if", "then", "else", "elif", "do", "while", "until", "!", "{", "}",
                           "time", "nohup", "exec", "builtin"})
# The wrappers that run the command after them, and their flags that take the
# next word as a value.
_VALUE_FLAGS = {
    "sudo": frozenset({"-u", "-g", "-h", "-p", "-C", "-D", "-U", "-r", "-t", "-T",
                       "--user", "--group", "--host", "--prompt", "--chdir"}),
    "env": frozenset({"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}),
    "xargs": frozenset({"-I", "-n", "-P", "-L", "-d", "-s", "-E", "-a", "--max-args",
                        "--max-procs", "--delimiter", "--arg-file"}),
}
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\[[^]]*\])?\+?=.*", re.S)
_REDIRECT = re.compile(r"\d*(>>?|<<?<?|&>>?|>&|<&|>\|)")
_SHELLS = frozenset({"bash", "sh", "zsh", "dash"})
_APT = frozenset({"apt", "apt-get", "aptitude"})
_APT_REMOVE = frozenset({"remove", "purge", "autoremove", "autopurge"})
_APT_SETUP = _APT_REMOVE | {"install", "update", "upgrade", "dist-upgrade", "full-upgrade",
                            "clean", "autoclean"}
_DOCKER_PRUNE = frozenset({"system", "image", "builder", "buildx", "volume", "container",
                           "network"})
_DOCKER_REPORT = (("images",), ("ps",), ("info",), ("version",), ("system", "df"),
                  ("image", "ls"))
# Host setup and cleanup besides apt and docker.
_SETUP_TOOLS = frozenset({"add-apt-repository", "snap", "swapoff", "tee", "mkdir", "chmod",
                          "chown", "ln", "dpkg", "rm", "rmdir"})
# Commands that only report or steer the shell.
_REPORTS = frozenset({"echo", "printf", "df", "du", "free", "true", "false", ":", "ls", "set",
                      "sleep", "date", "cat", "sync", "uname", "whoami", "id", "nproc", "lsblk",
                      "findmnt", "[", "[[", "test", "for", "case", "esac", "fi", "done", "exit",
                      "return", "command", "type", "which", "hash", "export", "shopt", "cd",
                      "pushd", "popd"})


def _scan(text: str, i: int, closer: str, out: list[str]) -> int:
    """Append the simple commands of `text` from `i` to `out`, up to `closer`
    (")" or "`" for a substitution, "" for the whole script); return the index
    after it. A substitution is scanned on its own and stands in its command
    as `$(…)`."""
    cur: list[str] = []
    quote, depth = "", 0

    def cut() -> None:
        seg = "".join(cur).strip()
        if seg:
            out.append(seg)
        cur.clear()

    while i < len(text):
        c = text[i]
        if quote == "'":
            quote = "" if c == "'" else quote
            cur.append(c)
            i += 1
        elif c == "\\":
            cur.append(text[i:i + 2])
            i += 2
        elif text.startswith("$(", i) or (c == "`" and closer != "`"):
            i = _scan(text, i + (1 if c == "`" else 2), "`" if c == "`" else ")", out)
            cur.append("$(…)")
        elif c == closer and not quote and depth == 0:
            cut()
            return i + 1
        elif c == '"':
            quote = "" if quote else '"'
            cur.append(c)
            i += 1
        elif quote:
            cur.append(c)
            i += 1
        elif c == "'":
            quote = "'"
            cur.append(c)
            i += 1
        elif c == "#" and (not cur or cur[-1][-1:].isspace()):
            while i < len(text) and text[i] != "\n":
                i += 1
        elif text.startswith("${", i):
            end = text.find("}", i)
            end = len(text) if end < 0 else end + 1
            cur.append(text[i:end])
            i = end
        elif c == "&" and (text[i - 1:i] in (">", "<") or text[i + 1:i + 2] == ">"):
            cur.append(c)            # 2>&1, &>file: a redirection, not a separator
            i += 1
        elif c in ";&|\n()":
            depth += (c == "(") - (c == ")" and depth > 0)
            cut()
            i += 1
        else:
            cur.append(c)
            i += 1
    cut()
    return i


def _words(segment: str) -> list[str]:
    """A simple command's words, quotes removed, redirections dropped."""
    try:
        raw = shlex.split(segment)
    except ValueError:
        raw = segment.split()
    words: list[str] = []
    skip_next = False
    for w in raw:
        if skip_next:
            skip_next = False
            continue
        m = _REDIRECT.match(w)
        if m:
            skip_next = m.end() == len(w)      # `> file`: the target is the next word
            continue
        words.append(w)
    return words


def _drop_flags(words: list[str], tool: str) -> list[str]:
    while words and words[0].startswith("-"):
        if words[0] == "--":
            return words[1:]
        words = words[2:] if words[0] in _VALUE_FLAGS[tool] else words[1:]
    return words


def _commands(script: str, sudo: bool = False, depth: int = 0):
    """(words, run by sudo, fed by xargs) for each simple command, with the
    prefixes that only wrap a command (env, nohup, if, X=1 …) removed."""
    segments: list[str] = []
    _scan(script.replace("\\\n", " "), 0, "", segments)
    for seg in segments:
        words, by_sudo, by_xargs = _words(seg), sudo, False
        while words:
            w = words[0]
            tool = w.rsplit("/", 1)[-1]
            if w in _PREFIX_WORDS or _ASSIGNMENT.fullmatch(w):
                words = words[1:]
            elif w == "command" and len(words) > 1 and not words[1].startswith("-"):
                words = words[1:]
            elif tool in _VALUE_FLAGS:
                by_sudo |= tool == "sudo"
                by_xargs |= tool == "xargs"
                words = _drop_flags(words[1:], tool)
            else:
                break
        base = words[0].rsplit("/", 1)[-1] if words else ""
        inner = None
        if base in _SHELLS and "-c" in words[1:-1]:
            inner = words[words.index("-c", 1) + 1]
        elif base == "eval":
            inner = " ".join(words[1:])
        if inner is not None and depth < 5:
            yield from _commands(inner, by_sudo, depth + 1)
            continue
        yield words, by_sudo, by_xargs


def _outside_checkout(path: str) -> bool:
    """An rm operand as written: $RUNNER_TEMP/x, $GITHUB_WORKSPACE/x, $PWD/x and
    a relative path are inside; an absolute path, ~ and $HOME are not."""
    return path.startswith(_HOME_ROOTS) or path.startswith("/")


def _docker(args: list[str], by_xargs: bool) -> tuple[str, bool]:
    """(what it mutates or "", whether it is setup, cleanup or a report)."""
    words = [a for a in args if not a.startswith("-")]
    if len(words) >= 2 and words[0] in _DOCKER_PRUNE and words[1] == "prune":
        return "docker " + " ".join(args)[:60], True
    if words[:1] == ["rmi"] or words[:2] in (["image", "rm"], ["image", "remove"]):
        names = words[1:] if words[0] == "rmi" else words[2:]
        if by_xargs or not names or {"-a", "--all"} & set(args) or any("$(" in n for n in names):
            return "docker " + " ".join(args)[:60] + " (every image)", True
        return "", True
    return "", any(tuple(words[:len(r)]) == r for r in _DOCKER_REPORT)


def _classify(words: list[str], by_sudo: bool, by_xargs: bool) -> tuple[str, bool]:
    """(what this command mutates on the host or "", whether it is host setup,
    cleanup or a report — the commands a setup step is made of)."""
    if not words:
        return ("sudo" if by_sudo else ""), True
    base, args = words[0].rsplit("/", 1)[-1], words[1:]
    hit, setup = "", base in _REPORTS or base in _SETUP_TOOLS
    if base == "docker":
        hit, setup = _docker(args, by_xargs)
    elif base in ("rm", "rmdir"):
        operands = args[args.index("--") + 1:] if "--" in args else \
            [a for a in args if not a.startswith("-")]
        hit = next((f"{base} {a}" for a in operands if _outside_checkout(a)), "")
    elif base in _APT:
        sub = next((a for a in args if not a.startswith("-")), "")
        hit, setup = (f"{base} {sub}" if sub in _APT_REMOVE else ""), sub in _APT_SETUP
    elif base == "dpkg" and {"-r", "--remove", "-P", "--purge"} & set(args):
        hit = "dpkg " + " ".join(args)[:40]
    if by_sudo:
        hit = "sudo " + " ".join(words)[:60]
    return hit, setup


@dataclass(frozen=True)
class HostMutation:
    found: str          # the commands, as the report names them
    setup_only: bool    # every command is host setup, cleanup or a report

    @property
    def reason(self) -> str:
        kind = "host setup or cleanup" if self.setup_only else "a gate step that changes the host"
        return (f"skipped-unsafe: {kind} written for a throwaway runner ({self.found}); "
                "not run on this persistent host — --allow-host-mutation runs it on a VM")


def host_mutation(script: str) -> HostMutation | None:
    """What in this run: script would change the host beyond the checkout and
    $RUNNER_TEMP, or None when nothing does."""
    found: list[str] = []
    setup_only = True
    for words, by_sudo, by_xargs in _commands(script):
        hit, setup = _classify(words, by_sudo, by_xargs)
        if hit and hit not in found:
            found.append(hit)
        setup_only &= setup
    if not found:
        return None
    shown = "; ".join(found)
    return HostMutation(shown if len(shown) <= 160 else shown[:157] + "...", setup_only)


# ─── 5. npm's global prefix ──────────────────────────────────────────────────
# validate-plugin.yml installs Claude Code with `npm install -g`. On a runner
# that lands in a machine nobody else uses; here it landed in the developer's
# own node install (nvm, Homebrew, /usr/local): the gate replaced their `claude`,
# forcing the Linux jobs on a Mac put a second one under /opt/homebrew, and two
# gates at once on one host raced in that directory. So every step of a job
# gets the job's own empty prefix, removed with the job's directory, and its
# bins go first on PATH, so what one step installs is what a later step runs.
#
# npm's cache is NOT moved. cacache is content-addressed and written for
# concurrent writers, and a per-job cache would download the package again on
# every gate. Moving the prefix also moves the global npmrc npm reads
# (<prefix>/etc/npmrc, which a runner does not have either); ~/.npmrc is read
# as before, and its own `prefix=` is outranked by the environment.
#
# What still changes this host's npm state: a prefix the workflow names
# itself (as on a runner, it wins); `sudo npm install -g`, since sudo resets
# the environment (section 4 runs it only under --allow-host-mutation); `npm config set prefix`, which writes ~/.npmrc; and a step
# that uses nvm. nvm refuses NPM_CONFIG_PREFIX in any spelling outside
# $NVM_DIR (nvm_die_on_prefix) and deactivates itself: `nvm use` returns 11,
# so sourcing nvm.sh with a default alias fails a step under `bash -e`, and a
# script without -e goes on with another node and passes, where main and a
# runner use nvm's (both found in review, 2026-11-25). Such a step gets no
# prefix variable, and its output and the JSON say so. It is found two ways.
# First from its own text, comments dropped: `nvm.sh` by any path, or `nvm`
# where a command starts, so `$HOME/.nvm/bin`, `NVM_DIR` or a variable named
# nvm_x leave a step isolated; a false match costs that one step its
# isolation. Then from nvm's own refusal in its output, which names the job's
# prefix: nvm was loaded where the text does not show it (a script the step
# runs, an eval), so that attempt is discarded, failed or passed, and the step
# runs again without the variable, on fresh runner files: the discarded
# attempt's $GITHUB_ENV and $GITHUB_PATH writes are dropped. Two shapes still
# go wrong. Not found: a step that hides nvm's stderr (`2>/dev/null`) and has
# no -e. It runs on whatever node is left, and passes or fails on it. Found,
# and still failed: a step that loads nvm out of sight (`run: ./ci/build.sh`,
# which sources nvm.sh) and is not safe to run twice. Nothing but its runner
# files is undone, so what its first attempt did before nvm refused (a
# `mkdir out`) fails the second run, and the flake rerun after it. A runner
# runs the step once, and passes it.
_SH_COMMENT = re.compile(r"(^|\s)#.*$", re.M)
_NVM_USE = re.compile(
    r"nvm\.sh|(?:^|[;&|(`{!]|\b(?:then|do|else|elif|if|while|until|time|command)\s)\s*nvm(?![\w./=-])",
    re.M)
NVM_NOTE = ("runs without the job's npm prefix: it uses nvm, which refuses NPM_CONFIG_PREFIX, "
            "so its global installs go wherever nvm puts them, on this host")
NVM_REFUSED = ("ran again without the job's npm prefix: nvm refused NPM_CONFIG_PREFIX in its "
               "output (exit {}), so its global installs go wherever nvm puts them, on this host")


def uses_nvm(script: str) -> bool:
    """Whether a step's run text sources nvm.sh or runs `nvm`, comments aside."""
    return bool(_NVM_USE.search(_SH_COMMENT.sub(r"\1", script)))


def nvm_refused(output: str, prefix: Path) -> bool:
    """Whether a step's `output` holds nvm's refusal of the job's `prefix`.
    nvm_die_on_prefix names the variable it found and its value, and the
    job's is NPM_CONFIG_PREFIX, the one spelling isolate_npm_global leaves.
    Only the job's own value counts: a prefix the workflow names, or one the
    step's own script exports, is refused on a runner too."""
    said = ('nvm is not compatible with the "NPM_CONFIG_PREFIX" environment variable: '
            f'currently set to "{prefix}"')
    return said in output


def isolate_npm_global(env: dict[str, str], prefix: Path, workflow_keys: list[str],
                       script: str) -> str:
    """Point npm's global prefix in a step's `env` at `prefix`, and put its
    bins first on PATH. `env` already holds the workflow's env, and
    `workflow_keys` names what the workflow set there itself (its env: and
    $GITHUB_ENV, with a value): a prefix it names wins, as on a runner. Any
    other is replaced: the caller's, in any spelling, or a `${{ }}` one that
    only the hosted run can set (unset, npm would fall back to this host's).
    A step whose `script` uses nvm gets no prefix variable, only the PATH
    entries; the return value is then why (NVM_NOTE), and "" otherwise."""
    named = {k for k in workflow_keys if k.lower() == "npm_config_prefix"}
    # npm reads npm_config_* in any case, and the LAST in the environment
    # wins, so a caller's stray lower-case npm_config_prefix (nvm warns about
    # one) would decide by environment order. No other spelling survives.
    for key in [k for k in env if k.lower() == "npm_config_prefix" and k not in named]:
        del env[key]
    why = ""
    if not named:
        if uses_nvm(script):
            why = NVM_NOTE
        else:
            env["NPM_CONFIG_PREFIX"] = str(prefix)
    # npm links global bins into <prefix>/bin, except on Windows, where they
    # sit in the prefix itself. Both go first. With no PATH at all (`env -i`),
    # the rest is exec's default, os.defpath: the prefix alone has no bash.
    env["PATH"] = os.pathsep.join([str(prefix / "bin"), str(prefix), env.get("PATH") or os.defpath])
    return why


# ─── 6. The shell a step runs in ─────────────────────────────────────────────
def attempt(script: str, cwd: Path, env: dict[str, str],
            timeout: int) -> tuple[int, float, str, bool]:
    """Run one step once: (exit code, seconds, all its output, timed out). A
    timeout reports exit 124, like coreutils `timeout`; only the flag tells
    it apart from a step that exits 124 itself."""
    t0 = time.time()
    try:
        proc = subprocess.run(
            ["bash", "-eo", "pipefail", "-c", script],
            cwd=cwd, env=env, capture_output=True, text=True,
            # A hosted runner gives a step no interactive stdin. Inheriting
            # the terminal's instead means one `read` anywhere in a suite
            # hangs the whole run with no output and no clue why — measured
            # at 13 minutes and 9% CPU before this was added.
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        # text=True is not applied to the partial output a timeout carries.
        parts = [p.decode("utf-8", "replace") if isinstance(p, bytes) else (p or "")
                 for p in (exc.stdout, exc.stderr)]
        return 124, time.time() - t0, "".join(parts), True
    return proc.returncode, time.time() - t0, (proc.stdout or "") + (proc.stderr or ""), False


def step_tail(note: str, output: str, lines: int) -> str:
    """A step's last `lines` lines of output, under its npm note if it has one."""
    return "\n".join(filter(None, [note, "\n".join(output.splitlines()[-lines:])]))


def attempt_in_prefix(script: str, cwd: Path, env: dict[str, str], files: JobFiles,
                      timeout: int, echo: bool) -> tuple[int, float, str, bool, str]:
    """Run one step on the job's runner files: (exit code, seconds, output,
    timed out, why), why being NVM_REFUSED's text when it ran again and ""
    otherwise. nvm, loaded where the step's text does not show it (a script,
    an eval), can refuse the job's prefix and deactivate itself: the attempt
    failed, or passed on another node. Its result is then discarded and the
    step runs once more without the prefix, on fresh runner files, so the
    discarded attempt's $GITHUB_ENV and $GITHUB_PATH writes are dropped;
    nothing else it did is undone. The prefix leaves `env` itself, so a flake
    rerun after it runs without it too. Not after a timeout, like the flake
    rerun, and not a rerun: --no-rerun leaves it alone."""
    rc, elapsed, out, timed_out = attempt(script, cwd, {**env, **files.begin_step()}, timeout)
    if timed_out or not nvm_refused(out, files.npm_prefix):
        return rc, elapsed, out, timed_out, ""
    env.pop("NPM_CONFIG_PREFIX", None)
    why = NVM_REFUSED.format(rc)
    if echo:
        print(f"nvm refused the job's npm prefix (exit {rc}), running it again "
              "without it … ", end="", flush=True)
    rc, redo, out, timed_out = attempt(script, cwd, {**env, **files.begin_step()}, timeout)
    return rc, elapsed + redo, out, timed_out, why


# A fixed per-step timeout reads a loaded host as a hang. On a 32-core box at
# load ~80, this repository's pytest step took 1,914 s against 528 s on a quiet
# one, so the 900 s that suits a quiet machine killed a step that was only
# waiting for CPU, and a timed-out step is never rerun. The default therefore
# scales with how oversubscribed the host is when the run starts: 900 s at or
# below one runnable task per CPU, up to 4x (3,600 s) so a real hang still ends.
# Sampled once, at the start; --timeout sets it outright.
STEP_TIMEOUT_BASE = 900
STEP_TIMEOUT_MAX_FACTOR = 4.0


def default_step_timeout(load1: float | None, cpus: int | None) -> tuple[int, str]:
    """(seconds, why) for the default step timeout, from the 1-minute load
    average and the CPU count. Either unknown (no os.getloadavg on Windows)
    falls back to the base."""
    if not load1 or not cpus or cpus < 1:
        return STEP_TIMEOUT_BASE, f"{STEP_TIMEOUT_BASE} s, load unknown"
    factor = min(max(load1 / cpus, 1.0), STEP_TIMEOUT_MAX_FACTOR)
    return (int(STEP_TIMEOUT_BASE * factor),
            f"{STEP_TIMEOUT_BASE} s x {factor:.1f}, load {load1:.0f} on {cpus} CPUs")


def host_load() -> tuple[float | None, int | None]:
    try:
        load1 = os.getloadavg()[0]
    except (AttributeError, OSError):
        load1 = None
    return load1, os.cpu_count()
