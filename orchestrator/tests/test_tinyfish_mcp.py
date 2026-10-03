"""Observe MCP result envelopes through the CLI and installed credential/config boundary."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "configs/skills/web-search/scripts"


def check_result(tmp_path, value, operation="run", *flags):
    path = tmp_path / "response.json"
    path.write_text(json.dumps(value))
    env = {**os.environ, "CLADE_SEARCH_STATE_DIR": str(tmp_path / "state")}
    proc = subprocess.run([sys.executable, str(SCRIPTS / "mcp_result.py"), operation,
                           "--input", str(path), *flags], env=env, capture_output=True, text=True)
    assert not proc.stderr
    return proc.returncode, json.loads(proc.stdout)


@pytest.mark.parametrize("state,payload,expected,code", [
    ("PENDING", None, "running", 0),
    ("RUNNING", None, "running", 0),
    ("FAILED", None, "failed", 2),
    ("CANCELLED", None, "cancelled", 2),
    ("COMPLETED", {"status": "failure", "reason": "could not find data"}, "failed", 2),
    ("COMPLETED", {"status": "blocked"}, "blocked", 2),
    ("COMPLETED", {"status": "partial", "missing_fields": ["price"]}, "partial", 2),
    ("COMPLETED", {}, "unverified", 2),
    ("COMPLETED", {"records": []}, "partial", 2),
    ("COMPLETED", {"records": [{"price": 12}]}, "needs_review", 0),
    ("NEW_PROVIDER_STATE", None, "unverified", 2),
])
def test_run_cli_separates_execution_state_from_goal_outcome(tmp_path, state, payload, expected, code):
    envelope = {"jsonrpc": "2.0", "id": 1, "result": {"content": [
        {"type": "text", "text": json.dumps({"id": "owned-run", "status": state, "result": payload})}]}}
    status, result = check_result(tmp_path, envelope, "run", "--required-field", "records")
    assert status == code and result["status"] == expected
    assert result["evidence_verified"] is False
    if expected == "running":
        assert result["run_id"] == "owned-run" and result["do_not_resubmit"] is True
        assert result["poll_after_seconds"] >= 30


def test_fetch_cli_preserves_successes_marks_gaps_and_caches_original(tmp_path):
    text = "background " * 250 + " Pricing is free with limits. " + "trailing " * 200
    body = {"results": [{"url": "https://example.com/a", "final_url": "https://example.com/new", "text": text},
                        {"url": "https://example.com/a", "text": "duplicate"}],
            "errors": [{"url": "https://example.com/b", "code": "timeout"}]}
    envelope = {"structuredContent": body, "content": []}
    code, result = check_result(tmp_path, envelope, "fetch", "--requested-url", "https://example.com/a",
                                "--requested-url", "https://example.com/b", "--query", "pricing", "--max-chars", "400")
    assert code == 2 and result["status"] == "partial"
    assert len(result["sources"]) == 1 and result["missing_urls"] == ["https://example.com/b"]
    assert "Pricing is free" in result["sources"][0]["excerpt"]
    assert len(result["sources"][0]["excerpt"]) <= 400
    assert result["sources"][0]["final_url"] == "https://example.com/new"
    cache = Path(result["cache_file"])
    assert cache.stat().st_mode & 0o077 == 0
    assert json.loads(cache.read_text())["structuredContent"]["results"][0]["text"] == text


@pytest.mark.parametrize("envelope", [
    {"isError": True, "content": [{"type": "text", "text": "unauthorized"}]},
    {"jsonrpc": "2.0", "error": {"code": -1}},
    {"content": [{"type": "text", "text": '{"results": [truncated'}]},
    {"content": [{"type": "text", "text": "working, 40%"}]},
])
def test_error_progress_or_truncated_mcp_envelope_cannot_become_success(tmp_path, envelope):
    code, result = check_result(tmp_path, envelope, "fetch")
    assert code == 2 and result["status"] == "unverified"


def test_installed_mcp_configs_preserve_settings_and_resolve_private_header_helper(tmp_path):
    cc, cx = tmp_path / "claude profile", tmp_path / "codex profile"
    cc.mkdir(); cx.mkdir()
    cc_state = cc / ".claude.json"
    cc_state.write_text(json.dumps({"theme": "dark", "mcpServers": {"existing": {"url": "https://example.com/mcp"}}}))
    (cx / "config.toml").write_text('model = "existing-model"\n[mcp_servers.existing]\nurl = "https://example.com/mcp"\n')
    key_path = tmp_path / "private.key"
    fake_key = "sk-tinyfish-" + "isolated-test-1234567890"
    key_path.write_text(fake_key); key_path.chmod(0o600)
    env = {**os.environ, "TINYFISH_API_KEY": "", "TINYFISH_API_KEY_FILE": str(key_path),
           "CLADE_SEARCH_STATE_DIR": str(tmp_path / "state")}
    cmd = [sys.executable, str(SCRIPTS / "install_user.py"), "--claude-home", str(cc), "--codex-home", str(cx),
           "--claude-state", str(cc_state), "--with-mcp", "--block-provider", "brave"]
    for _ in range(2):
        p = subprocess.run(cmd, capture_output=True, text=True, env=env)
        assert p.returncode == 0, p.stderr
        assert fake_key not in p.stdout + p.stderr
    cc_obj = json.loads(cc_state.read_text()); cx_obj = tomllib.loads((cx / "config.toml").read_text())
    assert cc_obj["theme"] == "dark" and "existing" in cc_obj["mcpServers"]
    assert cx_obj["model"] == "existing-model" and "existing" in cx_obj["mcp_servers"]
    assert cx_obj["mcp_servers"]["tinyfish"]["enabled_tools"] == ["search", "fetch_content"]
    assert fake_key not in cc_state.read_text() + (cx / "config.toml").read_text()
    for command in [cc_obj["mcpServers"]["tinyfish"]["headersHelper"], cx_obj["mcp_servers"]["tinyfish"]["http_headers_helper"]]:
        output = subprocess.run(command, shell=True, cwd=tmp_path, env=env, capture_output=True, text=True)
        assert output.returncode == 0 and not output.stderr
        assert json.loads(output.stdout)["Authorization"] == "Bearer " + fake_key
    bad = subprocess.run([sys.executable, str(cc / "skills/web-search/scripts/mcp_headers.py")],
                         env={**env, "CLAUDE_CODE_MCP_SERVER_URL": "https://unrelated.example/mcp"}, capture_output=True, text=True)
    assert bad.returncode == 2 and fake_key not in bad.stdout + bad.stderr


def test_route_cli_uses_connected_mcp_even_without_api_key(tmp_path):
    env = {**os.environ, "TINYFISH_API_KEY": "", "TINYFISH_API_KEY_FILE": str(tmp_path / "absent")}
    p = subprocess.run([sys.executable, str(SCRIPTS / "web_search.py"), "route", "--operation", "fetch",
                        "--native", "failed", "--mcp", "available"], env=env, capture_output=True, text=True)
    result = json.loads(p.stdout)
    assert p.returncode == 0 and result["provider"] == "tinyfish" and result["transport"] == "mcp"
    assert result["next_action"] == "call_tinyfish_mcp_fetch_content" and not result["executed"]


@pytest.mark.parametrize("existing", [[], {"mcpServers": {"tinyfish": {"url": "https://user-chosen.example/mcp"}}}])
def test_installer_preflights_all_profiles_before_changing_any(tmp_path, existing):
    cc, cx = tmp_path / "cc", tmp_path / "cx"
    cc.mkdir(); cx.mkdir()
    config = cc / ".claude.json"
    original = json.dumps(existing)
    config.write_text(original)
    p = subprocess.run([sys.executable, str(SCRIPTS / "install_user.py"), "--claude-home", str(cc),
                        "--codex-home", str(cx), "--with-mcp"], capture_output=True, text=True,
                       env={**os.environ, "CLADE_SEARCH_STATE_DIR": str(tmp_path / "state")})
    assert p.returncode == 2 and not p.stderr
    assert config.read_text() == original
    assert not (cc / "skills").exists() and not (cx / "skills").exists()
    assert not (cx / "config.toml").exists()
