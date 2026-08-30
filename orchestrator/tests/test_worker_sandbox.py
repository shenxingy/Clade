"""Can a worker still plant a hook the operator will execute?

`worker_git_surface_guard` detects that escape; these tests are about
preventing it. Everything here runs the real syscalls against a real git
worktree — a Landlock ruleset that is asserted about rather than applied is
worth nothing, and "the control existed but never applied" is the exact defect
this module was written in response to.

The cost cases are as load-bearing as the prevention cases. `git gc` failing in
the shared repository is a real consequence of the technique, and it is pinned
here so it cannot quietly change into something worse.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import worker_sandbox  # noqa: E402
from worker_sandbox import (  # noqa: E402
    SandboxPlan,
    SandboxUnavailable,
    allow_rules_excluding,
    build_plan,
    describe,
    git_control_surfaces,
    landlock_abi,
)

requires_landlock = pytest.mark.skipif(
    landlock_abi() <= 0,
    reason="kernel does not provide Landlock (Linux 5.13+ with landlock in the LSM list)",
)

GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


@pytest.fixture
def repo(tmp_path):
    """A main checkout plus a worktree that shares its `.git`."""
    main = tmp_path / "main"
    main.mkdir()

    def git(*args, cwd=main):
        return subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, env=GIT_ENV
        )

    git("init", "-q", "-b", "main")
    (main / "README").write_text("hi")
    git("add", "README")
    git("commit", "-qm", "init")
    tree = tmp_path / "tree"
    git("worktree", "add", "-q", str(tree), "-b", "work")
    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=tree, capture_output=True, text=True, env=GIT_ENV,
    ).stdout.strip()
    return {"main": main, "tree": tree, "git_common": Path(common)}


def _in_sandbox(plan: SandboxPlan, code: str, cwd: Path) -> dict:
    """Run `code` in a child confined by `plan`; it prints one JSON object."""
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=str(cwd), capture_output=True, text=True,
        preexec_fn=plan.preexec(), env=GIT_ENV,
    )
    assert proc.returncode == 0, f"probe failed: {proc.stderr}"
    return json.loads(proc.stdout)


class TestTheEscapeIsPrevented:
    """The worktree agent must not be able to write the operator's hooks."""

    @requires_landlock
    def test_a_worker_cannot_plant_a_pre_commit_hook(self, repo):
        hook = repo["git_common"] / "hooks" / "pre-commit"
        with build_plan(git_control_surfaces(str(repo["git_common"]))) as plan:
            result = _in_sandbox(
                plan,
                f"""
                import json
                try:
                    open({str(hook)!r}, "w").write("#!/bin/sh\\nid\\n")
                    print(json.dumps({{"wrote": True, "errno": None}}))
                except OSError as exc:
                    print(json.dumps({{"wrote": False, "errno": exc.errno}}))
                """,
                repo["tree"],
            )
        assert result["wrote"] is False, "the whole point: this must be denied"
        assert not hook.exists()

    @requires_landlock
    def test_config_is_protected_too_not_just_hooks(self, repo):
        """`core.hooksPath` in .git/config reaches the same outcome by another route."""
        config = repo["git_common"] / "config"
        before = config.read_text()
        with build_plan(git_control_surfaces(str(repo["git_common"]))) as plan:
            result = _in_sandbox(
                plan,
                f"""
                import json
                try:
                    with open({str(config)!r}, "a") as fh:
                        fh.write("\\n[core]\\n\\thooksPath = /tmp/evil\\n")
                    print(json.dumps({{"wrote": True}}))
                except OSError:
                    print(json.dumps({{"wrote": False}}))
                """,
                repo["tree"],
            )
        assert result["wrote"] is False
        assert config.read_text() == before

    @requires_landlock
    def test_the_worker_can_still_do_its_job(self, repo):
        """A sandbox that breaks the worker would just get turned off."""
        with build_plan(git_control_surfaces(str(repo["git_common"]))) as plan:
            result = _in_sandbox(
                plan,
                """
                import json, subprocess
                open("new_file.txt", "w").write("agent output")
                open("README", "a").write("\\nedited by the agent\\n")
                add = subprocess.run(["git", "add", "-A"], capture_output=True, text=True)
                commit = subprocess.run(
                    ["git", "commit", "-m", "work", "-q"], capture_output=True, text=True
                )
                print(json.dumps({
                    "wrote_in_worktree": True,
                    "add_rc": add.returncode,
                    "commit_rc": commit.returncode,
                    "commit_err": ((commit.stderr or "") + (commit.stdout or "")).strip()[:200],
                }))
                """,
                repo["tree"],
            )
        assert result["wrote_in_worktree"] is True
        assert result["add_rc"] == 0, "git add writes the worktree index"
        assert result["commit_rc"] == 0, (
            f"a worktree commit must survive the sandbox: {result['commit_err']}"
        )


class TestTheCostsAreKnown:
    """Documented consequences. If these change, the docstring is wrong."""

    @requires_landlock
    def test_git_gc_on_the_shared_repo_fails(self, repo):
        """`gc` creates `.git/gc.pid.lock` — a new entry in a protected path's parent.

        Granting that would grant writes to `.git/hooks` as well, since Landlock
        rules cover a whole hierarchy. This is the price of the technique, and
        `worker_sandbox`'s docstring states it.
        """
        with build_plan(git_control_surfaces(str(repo["git_common"]))) as plan:
            result = _in_sandbox(
                plan,
                """
                import json, subprocess
                r = subprocess.run(["git", "gc", "-q", "--prune=now"], capture_output=True, text=True)
                print(json.dumps({"rc": r.returncode, "err": r.stderr.strip()[:200]}))
                """,
                repo["tree"],
            )
        assert result["rc"] != 0
        assert "denied" in result["err"].lower()

    @requires_landlock
    def test_reads_are_never_restricted(self, repo):
        """Only write-class rights are handled, so nothing a worker reads changes."""
        hook_dir = repo["git_common"] / "hooks"
        with build_plan(git_control_surfaces(str(repo["git_common"]))) as plan:
            result = _in_sandbox(
                plan,
                f"""
                import json, os
                print(json.dumps({{"listed": sorted(os.listdir({str(hook_dir)!r}))[:3] is not None}}))
                """,
                repo["tree"],
            )
        assert result["listed"] is True


class TestTheRuleSet:
    def test_a_protected_path_is_never_in_the_allow_list(self, tmp_path):
        target = tmp_path / "repo" / ".git" / "hooks"
        target.mkdir(parents=True)
        (target / "pre-commit").write_text("#!/bin/sh")
        allowed = allow_rules_excluding([str(target)])
        real = os.path.realpath(target)
        assert all(
            p != real and not p.startswith(real + os.sep) for p in allowed
        ), "the exclusion walk re-allowed the path it was meant to exclude"

    def test_siblings_survive_the_exclusion(self, tmp_path):
        gitdir = tmp_path / "repo" / ".git"
        (gitdir / "hooks").mkdir(parents=True)
        (gitdir / "objects").mkdir()
        allowed = set(allow_rules_excluding([str(gitdir / "hooks")]))
        assert os.path.realpath(gitdir / "objects") in allowed, (
            "git needs its object store; only hooks was supposed to be excluded"
        )

    def test_two_protected_paths_cannot_re_allow_each_other(self, tmp_path):
        """`config` is a sibling of `hooks`, so hooks' own walk would allow it."""
        gitdir = tmp_path / "repo" / ".git"
        (gitdir / "hooks").mkdir(parents=True)
        (gitdir / "config").write_text("[core]\n")
        protect = [str(gitdir / "hooks"), str(gitdir / "config")]
        allowed = set(allow_rules_excluding(protect))
        for path in protect:
            assert os.path.realpath(path) not in allowed

    def test_git_control_surfaces_names_both_routes(self, tmp_path):
        surfaces = git_control_surfaces(str(tmp_path))
        assert [os.path.basename(p) for p in surfaces] == ["hooks", "config"]


class TestFailureIsLoud:
    def test_an_unavailable_kernel_raises_rather_than_returning_none(self, monkeypatch):
        """The caller must choose between refusing and running unconfined."""
        monkeypatch.setattr(worker_sandbox, "landlock_abi", lambda: 0)
        with pytest.raises(SandboxUnavailable, match="Landlock"):
            build_plan(["/nonexistent"])

    def test_a_ruleset_with_no_rules_is_refused(self, monkeypatch):
        """Zero rules means "deny every write" — never silently ship that."""
        monkeypatch.setattr(worker_sandbox, "allow_rules_excluding", lambda _p: [])
        if landlock_abi() <= 0:
            pytest.skip("needs Landlock to reach the rule-installation step")
        with pytest.raises(SandboxUnavailable, match="no allow rules"):
            build_plan(["/tmp"])

    @requires_landlock
    def test_preexec_still_creates_a_process_group(self, repo):
        """The kill path signals the group; losing setsid would orphan the tree."""
        with build_plan(git_control_surfaces(str(repo["git_common"]))) as plan:
            result = _in_sandbox(
                plan,
                """
                import json, os
                print(json.dumps({"pid": os.getpid(), "pgid": os.getpgid(0)}))
                """,
                repo["tree"],
            )
        assert result["pid"] == result["pgid"], "setsid must still run in preexec"
        assert result["pgid"] != os.getpgid(0)

    @requires_landlock
    def test_close_is_idempotent(self, repo):
        plan = build_plan(git_control_surfaces(str(repo["git_common"])))
        plan.close()
        plan.close()  # must not raise on an already-closed descriptor


class TestDescribe:
    def test_a_disabled_sandbox_says_why(self):
        assert describe(None, "kernel too old") == {
            "sandboxed": False,
            "reason": "kernel too old",
        }

    @requires_landlock
    def test_an_active_sandbox_reports_what_it_protected(self, repo):
        with build_plan(git_control_surfaces(str(repo["git_common"]))) as plan:
            shape = describe(plan)
        assert shape["sandboxed"] is True
        assert shape["rules"] > 0
        assert any(p.endswith("/hooks") for p in shape["protected"])


# ─── Wiring ─────────────────────────────────────────────────────────────────
#
# Every defect this module was written alongside had the same shape: a control
# that existed, was documented, had a settings key, and never reached the
# spawn. These tests follow the setting all the way to `preexec_fn`.

import importlib.util  # noqa: E402


def _real_worker_module(name: str):
    """conftest swaps in a mock `worker`; load the real file under a private name."""
    worker_file = Path(__file__).parent.parent / "worker.py"
    spec = importlib.util.spec_from_file_location(name, worker_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _worker(mod, tmp_path: Path, project_dir: Path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(exist_ok=True)
    return mod.Worker(
        task_id="t-sandbox",
        description="noop",
        model="sonnet",
        project_dir=project_dir,
        claude_dir=claude_dir,
    )


class TestTheSettingReachesTheSpawn:
    async def test_off_by_default_passes_no_preexec(self, tmp_path, repo):
        mod = _real_worker_module("_real_worker_sandbox_off")
        worker = _worker(mod, tmp_path, repo["tree"])
        plan, shape = await worker._build_sandbox_plan()
        assert plan is None
        assert shape == {"sandboxed": False, "reason": "worker_sandbox is off"}

    @requires_landlock
    async def test_turning_it_on_produces_a_real_plan(self, tmp_path, repo, monkeypatch):
        mod = _real_worker_module("_real_worker_sandbox_on")
        monkeypatch.setitem(mod.GLOBAL_SETTINGS, "worker_sandbox", True)
        worker = _worker(mod, tmp_path, repo["tree"])
        plan, shape = await worker._build_sandbox_plan()
        try:
            assert plan is not None, "the setting was on and Landlock is available"
            assert shape["sandboxed"] is True
            assert any(p.endswith("/hooks") for p in shape["protected"])
            assert any(p.endswith("/config") for p in shape["protected"])
        finally:
            if plan is not None:
                plan.close()

    @requires_landlock
    async def test_the_spawned_process_is_actually_confined(self, tmp_path, repo, monkeypatch):
        """End to end: flip the setting, spawn, and try the escape from the child."""
        mod = _real_worker_module("_real_worker_sandbox_e2e")
        monkeypatch.setitem(mod.GLOBAL_SETTINGS, "worker_sandbox", True)
        worker = _worker(mod, tmp_path, repo["tree"])
        worker._log_path = tmp_path / ".claude" / "worker.log"
        hook = repo["git_common"] / "hooks" / "pre-commit"

        await worker._spawn_with_redacted_log(
            f"printf '#!/bin/sh\\nid\\n' > {hook} && echo PLANTED || echo DENIED",
            dict(os.environ), append=False,
        )
        await worker.proc.wait()
        await worker._finish_log_capture()

        assert "DENIED" in worker._log_path.read_text()
        assert not hook.exists(), "the hook must not exist on disk afterwards"
        assert worker._sandbox["sandboxed"] is True

    async def test_an_unavailable_sandbox_fails_the_spawn_when_fail_closed(
        self, tmp_path, repo, monkeypatch
    ):
        """Asked for confinement, could not get it — refuse rather than pretend."""
        mod = _real_worker_module("_real_worker_sandbox_closed")
        monkeypatch.setitem(mod.GLOBAL_SETTINGS, "worker_sandbox", True)
        monkeypatch.setitem(mod.GLOBAL_SETTINGS, "worker_sandbox_fail_closed", True)
        monkeypatch.setattr(mod.worker_sandbox, "landlock_abi", lambda: 0)
        worker = _worker(mod, tmp_path, repo["tree"])
        with pytest.raises(SandboxUnavailable):
            await worker._build_sandbox_plan()

    async def test_best_effort_records_why_it_did_not_apply(self, tmp_path, repo, monkeypatch):
        mod = _real_worker_module("_real_worker_sandbox_open")
        monkeypatch.setitem(mod.GLOBAL_SETTINGS, "worker_sandbox", True)
        monkeypatch.setitem(mod.GLOBAL_SETTINGS, "worker_sandbox_fail_closed", False)
        monkeypatch.setattr(mod.worker_sandbox, "landlock_abi", lambda: 0)
        worker = _worker(mod, tmp_path, repo["tree"])
        plan, shape = await worker._build_sandbox_plan()
        assert plan is None
        assert shape["sandboxed"] is False
        assert "unavailable" in shape["reason"]

    async def test_a_worker_outside_a_git_repo_is_not_an_error(
        self, tmp_path, monkeypatch
    ):
        """Nothing to protect is not the same as a failure to protect."""
        mod = _real_worker_module("_real_worker_sandbox_nogit")
        monkeypatch.setitem(mod.GLOBAL_SETTINGS, "worker_sandbox", True)
        plain = tmp_path / "plain"
        plain.mkdir()
        worker = _worker(mod, tmp_path, plain)
        plan, shape = await worker._build_sandbox_plan()
        if plan is not None:  # a tmp_path nested inside a repo would still resolve one
            plan.close()
            pytest.skip("tmp_path resolved a git common dir")
        assert shape["sandboxed"] is False
        assert "no git common directory" in shape["reason"]


class TestTheBackendHonoursPreexec:
    async def test_preexec_replaces_setsid_and_is_actually_called(self, tmp_path):
        from execution_backend import LocalSubprocessBackend

        marker = tmp_path / "preexec-ran"

        def hook():
            os.setsid()
            marker.write_text("yes")

        log = open(tmp_path / "out.log", "w")
        proc = await LocalSubprocessBackend().spawn(
            "echo hi", stdout=log, stderr=log, env=dict(os.environ),
            cwd=str(tmp_path), preexec=hook,
        )
        await proc.wait()
        log.close()
        assert marker.read_text() == "yes", "the backend ignored the preexec hook"

    async def test_the_default_is_unchanged_when_no_hook_is_given(self, tmp_path):
        from execution_backend import LocalSubprocessBackend

        log = open(tmp_path / "out.log", "w")
        proc = await LocalSubprocessBackend().spawn(
            "sleep 5", stdout=log, stderr=log, env=dict(os.environ), cwd=str(tmp_path),
        )
        try:
            assert os.getpgid(proc.pid) == proc.pid, "setsid must still be the default"
        finally:
            os.killpg(os.getpgid(proc.pid), 9)
            await proc.wait()
            log.close()
