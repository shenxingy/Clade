"""Old sessions must still execute their pinned hook after cache replacement."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "configs/scripts/codex-plugin-update.py"


@pytest.fixture
def updater():
    spec = importlib.util.spec_from_file_location("codex_plugin_update", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bundle(home, version):
    root = home / "plugins/cache/clade/clade" / version
    (root / ".codex-plugin").mkdir(parents=True)
    (root / ".codex-plugin/plugin.json").write_text(json.dumps({"name": "clade", "version": version}))
    (root / "hooks").mkdir()
    (root / "hooks/pre_tool_guardian.py").write_text("print('original hook')\n")
    (root / "skills/review").mkdir(parents=True)
    (root / "skills/review/SKILL.md").write_text("original instructions\n")
    return root


@pytest.mark.parametrize("exit_code", [0, 7])
def test_old_session_hook_and_skill_survive_cli_cache_replacement(updater, tmp_path, monkeypatch, exit_code):
    home = tmp_path / "codex"
    old = bundle(home, "0.3.1+codex.old")
    original = {p.relative_to(old): p.read_bytes() for p in old.rglob("*") if p.is_file()}

    def install(command, **kwargs):
        assert command == ["codex", "plugin", "add", "clade@clade"]
        assert kwargs["env"]["CODEX_HOME"] == str(home)
        shutil.rmtree(old.parent)
        bundle(home, "0.3.1+codex.new")
        return subprocess.CompletedProcess(command, exit_code)

    with monkeypatch.context() as patch:
        patch.setattr(updater.subprocess, "run", install)
        assert updater.update(home, tmp_path / "backups") == exit_code
    # Observe beyond the installer boundary: execute the exact old path.
    r = subprocess.run([sys.executable, str(old / "hooks/pre_tool_guardian.py")], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout == "original hook\n"
    assert {p.relative_to(old): p.read_bytes() for p in old.rglob("*") if p.is_file()} == original
    assert (old.parent / "0.3.1+codex.new/.codex-plugin/plugin.json").is_file()


@pytest.mark.parametrize("failure", [KeyboardInterrupt(), subprocess.TimeoutExpired("codex", 300)])
def test_restore_runs_when_install_is_interrupted(updater, tmp_path, monkeypatch, failure):
    home = tmp_path / "codex"
    old = bundle(home, "old")

    def interrupt(*args, **kwargs):
        shutil.rmtree(old)
        raise failure

    monkeypatch.setattr(updater.subprocess, "run", interrupt)
    with pytest.raises(type(failure)):
        updater.update(home, tmp_path / "backups")
    assert (old / "skills/review/SKILL.md").read_text() == "original instructions\n"


def test_terminal_recovery_cli_uses_selected_home_and_preserves_mode(updater, tmp_path):
    home = tmp_path / "codex"
    old = bundle(home, "old")
    hook = old / "hooks/pre_tool_guardian.py"
    hook.chmod(0o755)
    mode = hook.stat().st_mode
    saved = updater.snapshot(home, tmp_path / "backups")
    shutil.rmtree(old)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--codex-home", str(home), "--restore", str(saved)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert hook.stat().st_mode == mode
    assert "no plugin reinstall performed" in result.stdout


def test_snapshot_can_recover_later_without_overwriting_new_files(updater, tmp_path):
    home = tmp_path / "codex"
    old = bundle(home, "old")
    saved = updater.snapshot(home, tmp_path / "backups")
    shutil.rmtree(old)
    updater.restore(saved, home)
    updater.restore(saved, home)  # idempotent
    hook = old / "hooks/pre_tool_guardian.py"
    hook.write_text("changed by another process\n")
    with pytest.raises(ValueError, match="conflict"):
        updater.restore(saved, home)
    assert hook.read_text() == "changed by another process\n"


def test_corrupt_backup_and_path_escape_are_rejected(updater, tmp_path):
    home = tmp_path / "codex"
    old = bundle(home, "old")
    saved = updater.snapshot(home, tmp_path / "backups")
    shutil.rmtree(old)
    hook = saved / "bundles/old/hooks/pre_tool_guardian.py"
    hook.write_text("corrupt\n")
    with pytest.raises(ValueError, match="checksum"):
        updater.restore(saved, home)
    assert not old.exists()
    index = json.loads((saved / "snapshot.json").read_text())
    index["versions"]["../outside"] = index["versions"].pop("old")
    (saved / "snapshot.json").write_text(json.dumps(index))
    with pytest.raises(ValueError, match="version"):
        updater.restore(saved, home)


def test_symlink_and_concurrent_update_refuse_before_cli(updater, tmp_path, monkeypatch):
    home = tmp_path / "codex"
    old = bundle(home, "old")
    backups = tmp_path / "backups"
    backups.mkdir()
    (backups / "update.lock").mkdir()
    monkeypatch.setattr(updater.subprocess, "run", lambda *a, **kw: pytest.fail("CLI must not run"))
    with pytest.raises(FileExistsError):
        updater.update(home, backups)
    (backups / "update.lock").rmdir()
    (old / "linked").symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="symlink"):
        updater.update(home, backups)
    assert not (backups / "update.lock").exists()


def test_first_install_without_old_cache(updater, tmp_path, monkeypatch):
    monkeypatch.setattr(updater.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0))
    assert updater.update(tmp_path / "codex", tmp_path / "backups") == 0


def test_historical_dangling_alias_does_not_prevent_bundle_backup(updater, tmp_path, capsys):
    home = tmp_path / "codex"
    old = bundle(home, "old")
    alias = old.parent / "0.3.1"
    alias.symlink_to("removed-version", target_is_directory=True)
    saved = updater.snapshot(home, tmp_path / "backups")
    assert "Skipping dangling cache alias" in capsys.readouterr().out
    index = json.loads((saved / "snapshot.json").read_text())
    assert list(index["versions"]) == ["old"]
    assert alias.is_symlink()
