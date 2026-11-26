"""
ci_local_runner.py — what a GitHub runner gives a job that the workflow text
does not spell out. Imported by ci-local.py, which sits at this repository's
1500-line cap; installed and bundled beside it.

Four things. The first three were found by running ci-local.py against real
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
4. **A global prefix nobody else uses.** A runner is a fresh machine per job,
   so a step's `npm install -g` writes into a prefix of its own. Here it wrote
   into the developer's (2026-11-17, the first gate of #251): two gates at
   once raced there and one failed with npm `ENOTEMPTY`, and a gate replaced
   the user's own installed CLI. A step that uses nvm is the exception (4).

Stdlib only, like ci-local.py.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
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


# ─── 4. npm's global prefix ──────────────────────────────────────────────────
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
# the environment; `npm config set prefix`, which writes ~/.npmrc; and a step
# that uses nvm. nvm refuses NPM_CONFIG_PREFIX in any spelling outside
# $NVM_DIR (nvm_die_on_prefix): `nvm use` returns 11, and sourcing nvm.sh
# with a default alias set fails the step under `bash -e`, where it passes on
# main and on a runner (found in review, 2026-11-25). Such a step gets no
# prefix variable, and its output says so. It is read from the step's own text,
# comments dropped: `nvm.sh` by any path, or `nvm` where a command starts, so
# `$HOME/.nvm/bin`, `NVM_DIR` or a variable named nvm_x leave a step isolated.
# A miss fails the step with exit 11, which names the variable; a false match
# costs that one step its isolation, and its note names it.
_SH_COMMENT = re.compile(r"(^|\s)#.*$", re.M)
_NVM_USE = re.compile(
    r"nvm\.sh|(?:^|[;&|(`{!]|\b(?:then|do|else|elif|if|while|until|time|command)\s)\s*nvm(?![\w./=-])",
    re.M)
NVM_NOTE = ("runs without the job's npm prefix: it uses nvm, which refuses NPM_CONFIG_PREFIX, "
            "so its global installs go wherever nvm puts them, on this host")


def uses_nvm(script: str) -> bool:
    """Whether a step's run text sources nvm.sh or runs `nvm`, comments aside."""
    return bool(_NVM_USE.search(_SH_COMMENT.sub(r"\1", script)))


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
