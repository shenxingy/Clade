"""Tests for github_sync.ensure_repo_invariants (domdomegg preflight) and its
ProjectSession wiring.

Everything must be fail-open: a machine without gh auth or network gets logged
warnings in the findings dict, never an exception. gh subprocesses are mocked
via the AsyncioProxy pattern from test_oracle_integrity.py.
"""

from __future__ import annotations

import asyncio

import github_sync as gs


# ─── Test doubles ─────────────────────────────────────────────────────────────


class FakeProc:
    def __init__(self, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self.killed = False

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self):
        self.killed = True


class AsyncioProxy:
    def __init__(self, **overrides):
        self._overrides = overrides

    def __getattr__(self, name):
        if name in self._overrides:
            return self._overrides[name]
        return getattr(asyncio, name)


def _shell_dispatcher(responses: list[tuple[str, FakeProc]]):
    """First substring match in `responses` wins; records command strings."""
    calls: list[str] = []

    async def _fake_shell(cmd, **kwargs):
        calls.append(cmd)
        for needle, proc in responses:
            if needle in cmd:
                return proc
        return FakeProc(stderr=b"unexpected command", returncode=1)

    return calls, _fake_shell


_REPO_VIEW_OK = FakeProc(stdout=b'{"viewerPermission": "ADMIN", "squashMergeAllowed": true}')


# ─── ensure_repo_invariants ──────────────────────────────────────────────────


class TestEnsureRepoInvariants:
    async def test_happy_path_creates_labels_and_checks_perms(self, tmp_path, monkeypatch):
        calls, fake_shell = _shell_dispatcher([
            ("gh label create", FakeProc()),
            ("gh repo view", _REPO_VIEW_OK),
        ])
        monkeypatch.setattr(gs, "asyncio", AsyncioProxy(create_subprocess_shell=fake_shell))

        findings = await gs.ensure_repo_invariants(tmp_path)

        assert findings["labels_ensured"] == [
            "orchestrator", "pending", "running", "done", "failed"
        ]
        assert findings["viewer_permission"] == "ADMIN"
        assert findings["squash_merge_allowed"] is True
        assert findings["warnings"] == []
        # idempotent form: every label create uses --force
        label_cmds = [c for c in calls if "gh label create" in c]
        assert len(label_cmds) == 5 and all("--force" in c for c in label_cmds)

    async def test_gh_missing_is_fail_open(self, tmp_path, monkeypatch):
        async def _boom(*a, **k):
            raise FileNotFoundError("gh not installed")
        monkeypatch.setattr(gs, "asyncio", AsyncioProxy(create_subprocess_shell=_boom))

        findings = await gs.ensure_repo_invariants(tmp_path)  # must not raise

        assert findings["labels_ensured"] == []
        assert len(findings["warnings"]) == 6  # 5 labels + repo view
        assert findings["viewer_permission"] is None

    async def test_timeout_is_fail_open(self, tmp_path, monkeypatch):
        proc = FakeProc()

        async def _timeout_wait_for(coro, timeout=None):
            coro.close()
            raise asyncio.TimeoutError

        calls, fake_shell = _shell_dispatcher([("gh", proc)])
        monkeypatch.setattr(gs, "asyncio", AsyncioProxy(
            create_subprocess_shell=fake_shell, wait_for=_timeout_wait_for,
        ))

        findings = await gs.ensure_repo_invariants(tmp_path)

        assert any("timeout" in w for w in findings["warnings"])
        assert proc.killed

    async def test_read_only_permission_warns(self, tmp_path, monkeypatch):
        _, fake_shell = _shell_dispatcher([
            ("gh label create", FakeProc()),
            ("gh repo view", FakeProc(
                stdout=b'{"viewerPermission": "READ", "squashMergeAllowed": true}')),
        ])
        monkeypatch.setattr(gs, "asyncio", AsyncioProxy(create_subprocess_shell=fake_shell))

        findings = await gs.ensure_repo_invariants(tmp_path)

        assert findings["viewer_permission"] == "READ"
        assert any("viewerPermission=READ" in w for w in findings["warnings"])

    async def test_squash_merge_disabled_warns(self, tmp_path, monkeypatch):
        _, fake_shell = _shell_dispatcher([
            ("gh label create", FakeProc()),
            ("gh repo view", FakeProc(
                stdout=b'{"viewerPermission": "ADMIN", "squashMergeAllowed": false}')),
        ])
        monkeypatch.setattr(gs, "asyncio", AsyncioProxy(create_subprocess_shell=fake_shell))

        findings = await gs.ensure_repo_invariants(tmp_path)

        assert findings["squash_merge_allowed"] is False
        assert any("squash merge disabled" in w for w in findings["warnings"])

    async def test_unparseable_repo_view_warns(self, tmp_path, monkeypatch):
        _, fake_shell = _shell_dispatcher([
            ("gh label create", FakeProc()),
            ("gh repo view", FakeProc(stdout=b"flaky output")),
        ])
        monkeypatch.setattr(gs, "asyncio", AsyncioProxy(create_subprocess_shell=fake_shell))

        findings = await gs.ensure_repo_invariants(tmp_path)

        assert any("unparseable JSON" in w for w in findings["warnings"])

    async def test_flags_scope_the_checks(self, tmp_path, monkeypatch):
        calls, fake_shell = _shell_dispatcher([("gh repo view", _REPO_VIEW_OK)])
        monkeypatch.setattr(gs, "asyncio", AsyncioProxy(create_subprocess_shell=fake_shell))

        findings = await gs.ensure_repo_invariants(
            tmp_path, ensure_labels=False, check_merge=True
        )
        assert findings["labels_ensured"] == []
        assert not any("gh label create" in c for c in calls)

        calls2, fake_shell2 = _shell_dispatcher([("gh label create", FakeProc())])
        monkeypatch.setattr(gs, "asyncio", AsyncioProxy(create_subprocess_shell=fake_shell2))
        findings2 = await gs.ensure_repo_invariants(
            tmp_path, ensure_labels=True, check_merge=False
        )
        assert findings2["viewer_permission"] is None
        assert not any("gh repo view" in c for c in calls2)

    async def test_custom_label_setting_respected(self, tmp_path, monkeypatch):
        calls, fake_shell = _shell_dispatcher([
            ("gh label create", FakeProc()), ("gh repo view", _REPO_VIEW_OK),
        ])
        monkeypatch.setattr(gs, "asyncio", AsyncioProxy(create_subprocess_shell=fake_shell))
        monkeypatch.setitem(gs.GLOBAL_SETTINGS, "github_issues_label", "my-bot")

        findings = await gs.ensure_repo_invariants(tmp_path)

        assert "my-bot" in findings["labels_ensured"]


# ─── ProjectSession wiring ───────────────────────────────────────────────────


class TestSessionPreflightWiring:
    async def test_session_init_schedules_preflight(self, tmp_path, monkeypatch):
        import session as sess_mod

        called: dict = {}

        async def _fake(project_dir, *, ensure_labels, check_merge):
            called["args"] = (project_dir, ensure_labels, check_merge)
            return {}

        monkeypatch.setattr(gs, "ensure_repo_invariants", _fake)
        monkeypatch.setitem(sess_mod.GLOBAL_SETTINGS, "github_issues_sync", True)
        monkeypatch.setitem(sess_mod.GLOBAL_SETTINGS, "auto_merge", True)

        sess_mod.ProjectSession(str(tmp_path))
        await asyncio.sleep(0.01)  # let the fire-and-forget task run

        assert called["args"] == (tmp_path, True, True)

    async def test_session_init_skips_when_features_off(self, tmp_path, monkeypatch):
        import session as sess_mod

        called: dict = {}

        async def _fake(project_dir, **kw):
            called["hit"] = True
            return {}

        monkeypatch.setattr(gs, "ensure_repo_invariants", _fake)
        monkeypatch.setitem(sess_mod.GLOBAL_SETTINGS, "github_issues_sync", False)
        monkeypatch.setitem(sess_mod.GLOBAL_SETTINGS, "auto_merge", False)

        sess_mod.ProjectSession(str(tmp_path))
        await asyncio.sleep(0.01)

        assert called == {}

    def test_session_init_outside_event_loop_does_not_crash(self, tmp_path, monkeypatch):
        import session as sess_mod

        monkeypatch.setitem(sess_mod.GLOBAL_SETTINGS, "github_issues_sync", True)
        monkeypatch.setitem(sess_mod.GLOBAL_SETTINGS, "auto_merge", True)

        # No running loop here — the preflight must be skipped, not raised.
        s = sess_mod.ProjectSession(str(tmp_path))
        assert s.project_dir == tmp_path
