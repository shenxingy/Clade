"""Make the git control surface unwritable to a worker, using Landlock.

The escape this exists for
--------------------------
A worker runs in a ``git worktree``. A worktree does not have its own
repository — ``git rev-parse --git-common-dir`` resolves to the *parent's*
``.git``. So an agent editing files "inside its own worktree" can write
``<main-repo>/.git/hooks/pre-commit``, and the next time the **operator**
commits in their own checkout, that script runs as them. ``.git/config`` is the
same surface by another route: ``core.hooksPath``, ``core.fsmonitor`` and
aliases are all commands git executes.

``worker_git_surface_guard`` (default on) *detects* this after the attempt and
flags the evidence bundle. It cannot prevent it, because a worker that cannot
write ``.git`` cannot commit at all — which is the whole difficulty.

Why this can be prevented after all
-----------------------------------
Landlock is allow-list only: a rule grants access to a path *and everything
beneath it*, and there is no deny rule. "``.git`` writable but ``.git/hooks``
not" therefore looks inexpressible. It is expressible — by walking from ``/``
down to the protected path and, at each level, allowing every sibling **except**
the component on the path to it. Nothing else on the filesystem loses write
access, so the blast radius is exactly the paths named.

Only write-class rights are handled. Reads and executes are never restricted,
so nothing a worker reads — skills, config, source, caches — is affected.

What it costs (measured, not predicted)
---------------------------------------
Granting write on an ancestor directory would grant it on the whole hierarchy
beneath, protected child included. So ancestors of a protected path keep their
existing children writable but do not allow *new* entries to be created
directly in them. Consequences, all verified in ``tests/test_worker_sandbox.py``:

* ``git commit`` from the worktree works. A worktree's index, ``COMMIT_EDITMSG``
  and ``HEAD`` live in ``.git/worktrees/<name>/``, not the common directory, so
  the common directory needs no new entries for an ordinary commit.
* ``git gc`` and ``git pack-refs`` **fail** in the shared repository: both
  create a new lock file directly in ``.git`` (``gc.pid.lock``,
  ``packed-refs.lock``). Auto-gc runs opportunistically and its failure is a
  warning rather than a failed commit, but a worker that explicitly runs ``git
  gc`` on the shared repository will fail under the sandbox.
* Creating a new file directly in the *main checkout's* root directory is
  denied. The worker's own worktree is a different directory and is fully
  writable.

That tradeoff is why this ships **default off** (``worker_sandbox``). It is a
real behaviour change, and the operator picks it.

Availability
------------
Linux only, kernel 5.13+ (Landlock ABI 1). The rights used are masked down to
whatever ABI the running kernel reports, so a newer right is simply not handled
on an older kernel rather than failing the whole ruleset. When
``worker_sandbox`` is on and Landlock is unavailable, ``worker_sandbox_fail_closed``
(default **on**) refuses the spawn rather than running unconfined — a security
control that silently does nothing is the exact defect this repository has
spent its recent history removing.

Leaf module: stdlib only, no project imports. ``execution_backend`` uses it.
"""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass, field

# ─── Syscall + ABI constants ────────────────────────────────────────────────

#: x86_64/arm64 syscall numbers. Landlock landed with the same numbers on both.
_NR_CREATE_RULESET = 444
_NR_ADD_RULE = 445
_NR_RESTRICT_SELF = 446
_NR_PRCTL = 157

_PR_SET_NO_NEW_PRIVS = 38
_LANDLOCK_CREATE_RULESET_VERSION = 1
_LANDLOCK_RULE_PATH_BENEATH = 1

_ACCESS_FS = {
    "EXECUTE": 1 << 0,
    "WRITE_FILE": 1 << 1,
    "READ_FILE": 1 << 2,
    "READ_DIR": 1 << 3,
    "REMOVE_DIR": 1 << 4,
    "REMOVE_FILE": 1 << 5,
    "MAKE_CHAR": 1 << 6,
    "MAKE_DIR": 1 << 7,
    "MAKE_REG": 1 << 8,
    "MAKE_SOCK": 1 << 9,
    "MAKE_FIFO": 1 << 10,
    "MAKE_BLOCK": 1 << 11,
    "MAKE_SYM": 1 << 12,
    "REFER": 1 << 13,      # ABI 2
    "TRUNCATE": 1 << 14,   # ABI 3
}

#: Lowest ABI that supports each right; anything absent is ABI 1.
_RIGHT_MIN_ABI = {"REFER": 2, "TRUNCATE": 3}

#: Rights that only mean anything on a directory. Landlock returns EINVAL if
#: they are requested for a rule whose target is a regular file.
_DIR_ONLY = {
    "REMOVE_DIR", "REMOVE_FILE", "MAKE_CHAR", "MAKE_DIR", "MAKE_REG",
    "MAKE_SOCK", "MAKE_FIFO", "MAKE_BLOCK", "MAKE_SYM", "REFER",
}


class SandboxUnavailable(RuntimeError):
    """Landlock cannot be used here — wrong platform, old kernel, or disabled."""


class _RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _PathBeneathAttr(ctypes.Structure):
    # The kernel declares this packed; the natural alignment of a u64 followed
    # by an s32 would otherwise pad it to 16 bytes and be rejected.
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def _libc() -> ctypes.CDLL:
    return ctypes.CDLL("libc.so.6", use_errno=True)


# ─── Availability ───────────────────────────────────────────────────────────
def landlock_abi() -> int:
    """Landlock ABI version supported by this kernel; 0 when unavailable.

    Probed rather than inferred from ``uname``: a kernel can carry the syscalls
    while Landlock is absent from the active LSM list, in which case creating a
    ruleset fails and only the probe reveals it.
    """
    try:
        libc = _libc()
        version = libc.syscall(
            _NR_CREATE_RULESET, None, ctypes.c_size_t(0),
            ctypes.c_uint32(_LANDLOCK_CREATE_RULESET_VERSION),
        )
    except (OSError, AttributeError):
        return 0
    return version if version > 0 else 0


def _write_mask(abi: int) -> int:
    """Write-class rights supported at this ABI.

    Read and execute rights are deliberately excluded: leaving them unhandled
    means the ruleset cannot restrict them at all, so a worker's reads stay
    exactly as they were.
    """
    mask = 0
    for name, bit in _ACCESS_FS.items():
        if name in ("EXECUTE", "READ_FILE", "READ_DIR"):
            continue
        if _RIGHT_MIN_ABI.get(name, 1) > abi:
            continue
        mask |= bit
    return mask


def _file_mask(abi: int) -> int:
    return _write_mask(abi) & ~sum(_ACCESS_FS[n] for n in _DIR_ONLY)


# ─── Which paths are control surfaces ───────────────────────────────────────
def git_control_surfaces(git_common_dir: str) -> list[str]:
    """The paths inside a shared git directory that execute operator-side.

    ``hooks/`` is scripts git runs; ``config`` can point ``core.hooksPath``
    somewhere else, define ``core.fsmonitor``, or add an alias — all of which
    are commands. Protecting hooks without protecting config would leave the
    door open by a second route.
    """
    common = os.path.realpath(git_common_dir)
    return [os.path.join(common, "hooks"), os.path.join(common, "config")]


def allow_rules_excluding(protect: list[str]) -> list[str]:
    """Paths to allow so that everything stays writable except ``protect``.

    Walks from ``/`` to each protected path, allowing every sibling at each
    level. A sibling that is itself protected (or lies beneath another
    protected path) is dropped, so two overlapping targets cannot re-allow
    each other.
    """
    targets = {os.path.realpath(p) for p in protect if p}
    allow: set[str] = set()
    for target in targets:
        parts = [p for p in target.strip("/").split("/") if p]
        for depth, on_path in enumerate(parts):
            parent = "/" + "/".join(parts[:depth])
            try:
                entries = os.listdir(parent)
            except OSError:
                continue
            for entry in entries:
                if entry != on_path:
                    allow.add(os.path.join(parent, entry))
    return sorted(
        path for path in allow
        if not any(path == t or path.startswith(t + os.sep) for t in targets)
    )


# ─── Plan ───────────────────────────────────────────────────────────────────
@dataclass
class SandboxPlan:
    """A prepared Landlock ruleset, ready to be applied in a forked child.

    The ruleset is built **in the parent** — thousands of ``open`` calls and
    one ``landlock_add_rule`` each — and the file descriptor is inherited across
    ``fork``. The child then only runs ``prctl`` plus one ``landlock_restrict_self``,
    which matters because work done in ``preexec_fn`` happens between fork and
    exec, where very little is safe to do.
    """

    protect: tuple[str, ...]
    ruleset_fd: int
    rule_count: int
    abi: int
    _closed: bool = field(default=False, repr=False)

    def preexec(self):
        """The ``preexec_fn`` to hand to ``create_subprocess_shell``.

        Also calls ``setsid``: the local backend's kill path signals the whole
        process group, and replacing its ``preexec_fn`` without keeping that
        would orphan every process the agent spawns.
        """
        fd = self.ruleset_fd

        def _apply() -> None:
            os.setsid()
            libc = _libc()
            if libc.syscall(ctypes.c_long(_NR_PRCTL), _PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
                raise OSError(ctypes.get_errno(), "prctl(PR_SET_NO_NEW_PRIVS)")
            if libc.syscall(_NR_RESTRICT_SELF, fd, 0) != 0:
                raise OSError(ctypes.get_errno(), "landlock_restrict_self")

        return _apply

    def close(self) -> None:
        """Release the ruleset fd. Safe to call twice."""
        if not self._closed:
            self._closed = True
            try:
                os.close(self.ruleset_fd)
            except OSError:
                pass

    def __enter__(self) -> SandboxPlan:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def build_plan(protect: list[str]) -> SandboxPlan:
    """Compile ``protect`` into a Landlock ruleset.

    Raises :class:`SandboxUnavailable` when Landlock is not usable, so the
    caller decides between refusing the spawn and running unconfined — this
    module never makes that choice silently.
    """
    abi = landlock_abi()
    if abi <= 0:
        raise SandboxUnavailable("kernel does not provide Landlock (need Linux 5.13+)")

    dir_mask, file_mask = _write_mask(abi), _file_mask(abi)
    libc = _libc()
    attr = _RulesetAttr(dir_mask)
    fd = libc.syscall(_NR_CREATE_RULESET, ctypes.byref(attr), ctypes.sizeof(attr), 0)
    if fd < 0:
        raise SandboxUnavailable(
            f"landlock_create_ruleset failed (errno {ctypes.get_errno()}); "
            "Landlock may be absent from the active LSM list"
        )

    count = 0
    try:
        for path in allow_rules_excluding(protect):
            try:
                # O_PATH: we never read or write through this descriptor, and it
                # works for paths the process could not otherwise open.
                # O_NOFOLLOW: a symlink's target is covered by its own rule, if
                # it has one — following here could silently widen the grant.
                pfd = os.open(path, os.O_PATH | os.O_CLOEXEC | os.O_NOFOLLOW)
            except OSError:
                continue  # raced away, or a dangling symlink; not fatal
            try:
                rights = dir_mask if os.path.isdir(path) else file_mask
                rule = _PathBeneathAttr(rights, pfd)
                if libc.syscall(
                    _NR_ADD_RULE, fd, _LANDLOCK_RULE_PATH_BENEATH, ctypes.byref(rule), 0
                ) == 0:
                    count += 1
            finally:
                os.close(pfd)
    except BaseException:
        os.close(fd)
        raise

    if count == 0:
        os.close(fd)
        raise SandboxUnavailable(
            "no allow rules could be installed — refusing to apply a ruleset "
            "that would deny every write"
        )
    return SandboxPlan(
        protect=tuple(os.path.realpath(p) for p in protect),
        ruleset_fd=fd,
        rule_count=count,
        abi=abi,
    )


def plan_for_git_surface(
    git_common_dir: str | None,
    *,
    enabled: bool,
    fail_closed: bool,
    extra_protect: tuple[str, ...] = (),
) -> tuple[SandboxPlan | None, dict]:
    """Resolve the sandbox for one spawn. Returns ``(plan_or_None, description)``.

    The policy, in one place so the caller cannot get it half-right:

    * disabled       → no plan, and the description says so
    * no common dir  → nothing to protect; a worker outside a git repository is
      not exposed to this escape, so this is not a failure
    * unavailable    → re-raises :class:`SandboxUnavailable` when ``fail_closed``,
      otherwise returns no plan with the reason recorded

    ``fail_closed`` defaults on at the settings layer. A worker that silently
    runs unconfined after the operator asked for a sandbox is worse than one
    that refuses to start, because only the second is visible.
    """
    if not enabled:
        return None, describe(None, "worker_sandbox is off")
    if not git_common_dir:
        return None, describe(None, "no git common directory to protect")
    protect = git_control_surfaces(git_common_dir) + [p for p in extra_protect if p]
    try:
        plan = build_plan(protect)
    except SandboxUnavailable as exc:
        if fail_closed:
            raise
        return None, describe(None, f"unavailable: {exc}")
    return plan, describe(plan)


def describe(plan: SandboxPlan | None, reason: str = "") -> dict:
    """Log/evidence shape: what was confined, never the allow-list itself."""
    if plan is None:
        return {"sandboxed": False, "reason": reason or "disabled"}
    return {
        "sandboxed": True,
        "landlock_abi": plan.abi,
        "protected": list(plan.protect),
        "rules": plan.rule_count,
    }
