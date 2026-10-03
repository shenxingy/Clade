"""Observe retrieval across HTTP, disk-cache, CLI and installed-skill boundaries."""
from __future__ import annotations

from contextlib import contextmanager
import importlib.util
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "configs/skills/web-search/scripts"


@pytest.fixture
def module():
    spec = importlib.util.spec_from_file_location("clade_web_search", SCRIPTS / "web_search.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@contextmanager
def endpoint(module, monkeypatch, respond):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.handle_request()

        def do_POST(self):
            self.handle_request()

        def handle_request(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            payload = json.loads(body) if body else None
            calls.append((self.path, payload))
            status, result, headers = respond(self.path, payload, len(calls))
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    root = "http://127.0.0.1:" + str(server.server_port)
    monkeypatch.setattr(module, "SEARCH_ENDPOINT", root + "/search")
    monkeypatch.setattr(module, "FETCH_ENDPOINT", root + "/fetch")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield calls
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def client(module, tmp_path):
    return module.Client("sk-tinyfish-" + "fake-test-key-1234567890", tmp_path / "state")


@pytest.mark.parametrize("native,queries,pages,recurring,key,expected", [
    ("available", 1, 3, False, True, "native"),
    ("available", 5, 3, False, True, "tinyfish"),
    ("available", 1, 20, False, True, "tinyfish"),
    ("available", 1, 3, True, True, "tinyfish"),
    ("failed", 1, 3, False, True, "tinyfish"),
    ("unavailable", 1, 3, False, True, "tinyfish"),
    ("available", 5, 20, True, False, "native"),
    ("unavailable", 1, 3, False, False, "blocked"),
])
def test_route_hands_off_to_available_runtime_without_spawning(module, native, queries, pages, recurring, key, expected):
    result = module.route("search", native, queries, pages, recurring, "auto", key)
    assert result["provider"] == expected
    assert result["executed"] is False
    if expected == "native":
        assert result["next_action"] == "call_native_search"


def test_explicit_backend_is_not_silently_replaced(module):
    assert module.route("search", "available", 1, 1, False, "tinyfish", False)["provider"] == "blocked"
    assert module.route("search", "available", 99, 99, True, "native", True)["provider"] == "native"


def test_search_live_response_filters_deduplicates_and_reuses_disk_cache(module, monkeypatch, tmp_path):
    def respond(path, body, count):
        assert "include_domains=docs.example.com" in path
        return 200, {"results": [
            {"url": "https://docs.example.com/api#one", "title": "API", "snippet": "version " + str(count)},
            {"url": "https://docs.example.com/api#two"},
            {"url": "http://127.0.0.1/private"},
        ]}, {}
    with endpoint(module, monkeypatch, respond) as calls:
        service = client(module, tmp_path)
        first = service.search("API", {"include_domains": "docs.example.com"})
        second = service.search("API", {"include_domains": "docs.example.com"})
        fresh = service.search("API", {"include_domains": "docs.example.com"}, fresh=True)
    assert len(calls) == 2
    assert len(first["results"]) == 1 and first["omitted_results"] == 2
    assert second["cache_hit"] is True and second["results"][0]["snippet"] == "version 1"
    assert fresh["results"][0]["snippet"] == "version 2"
    stored = Path(first["cache_file"])
    assert stored.stat().st_mode & 0o077 == 0
    assert "retrieved_at" in json.loads(stored.read_text())


def test_beta_denial_falls_back_and_next_fetch_skips_beta_with_bounded_evidence(module, monkeypatch, tmp_path):
    content = ("unrelated material " * 100) + "\nTinyFish pricing allows free Search with limits.\n" + "background " * 300
    def respond(path, body, count):
        if "highlights" in body:
            return 403, {"message": "not enabled"}, {}
        return 200, {"results": [{"url": url, "text": content} for url in body["urls"]], "errors": []}, {}
    with endpoint(module, monkeypatch, respond) as calls:
        service = client(module, tmp_path)
        result = service.fetch(["https://example.com/a", "https://example.com/a", "https://example.com/b"],
                               "TinyFish pricing", max_chars=700, total_chars=900)
        service.fetch(["https://example.com/c"], "TinyFish pricing", fresh=True)
    assert len(calls) == 3 and "highlights" not in calls[-1][1]
    assert calls[-1][1]["ttl"] == 0
    assert result["highlights_capability"] is False
    assert len(result["results"]) == 2
    assert sum(len(row["excerpt"]) for row in result["results"]) <= 900
    assert "pricing allows free" in result["results"][0]["excerpt"]
    assert "pricing allows free" in result["results"][1]["excerpt"]
    assert result["results"][0]["selection"] == "local_keyword_passages"
    assert all(row["truncated"] for row in result["results"])
    raw = json.loads(Path(result["cache_files"][0]["path"]).read_text())
    assert raw["data"]["results"][0]["text"] == content


def test_successful_highlights_and_partial_page_failure_are_observable(module, monkeypatch, tmp_path):
    def respond(path, body, count):
        return 200, {"results": [{"url": body["urls"][0], "text": None,
                                 "highlights": [{"text": "Pricing evidence " * 100}]}],
                     "errors": [{"url": body["urls"][1], "code": "timeout"}]}, {}
    with endpoint(module, monkeypatch, respond):
        result = client(module, tmp_path).fetch(["https://example.com/one", "https://example.com/two"],
                                               "pricing", max_chars=200)
    assert result["status"] == "partial"
    assert result["highlights_capability"] is True
    assert result["results"][0]["selection"] == "tinyfish_highlights"
    assert len(result["results"][0]["excerpt"]) == 200
    assert result["errors"] == [{"url": "https://example.com/two", "code": "timeout"}]


def test_invalid_key_is_not_mislabeled_as_beta_denial(module, monkeypatch, tmp_path):
    with endpoint(module, monkeypatch, lambda *a: (403, {"secret": "never print upstream errors"}, {})) as calls:
        service = client(module, tmp_path)
        with pytest.raises(module.RetrievalError) as error:
            service.fetch(["https://example.com/"], "pricing")
    assert error.value.status == 403 and len(calls) == 2
    assert service.capabilities()["highlights"] == "unknown"


def test_unknown_beta_shape_fetches_plain_evidence_and_preserves_final_source(module, monkeypatch, tmp_path):
    def respond(path, body, count):
        row = {"url": body["urls"][0], "final_url": "https://example.com/canonical"}
        if "highlights" in body:
            row.update(text=None, highlights={"future_format": "not interpretable"})
        else:
            row["text"] = "Pricing: free Search with limits."
        return 200, {"results": [row]}, {}
    with endpoint(module, monkeypatch, respond) as calls:
        result = client(module, tmp_path).fetch(["https://example.com/old"], "pricing")
    assert len(calls) == 2 and "highlights" not in calls[-1][1]
    assert "free Search" in result["results"][0]["excerpt"]
    assert result["results"][0]["final_url"] == "https://example.com/canonical"
    assert result["results"][0]["selection"] == "local_keyword_passages"


def test_redirect_does_not_forward_credentials(module, monkeypatch, tmp_path):
    with endpoint(module, monkeypatch, lambda *a: (302, {}, {"Location": module.SEARCH_ENDPOINT + "/other"})) as calls:
        with pytest.raises(module.RetrievalError) as error:
            client(module, tmp_path).search("test")
    assert error.value.status == 302 and len(calls) == 1


def test_rate_limit_retries_once_and_respects_long_wait_without_sleep(module, monkeypatch, tmp_path):
    monkeypatch.setattr(module.time, "sleep", lambda value: None)
    with endpoint(module, monkeypatch, lambda *a: (429, {}, {"Retry-After": "1"})) as calls:
        with pytest.raises(module.RetrievalError):
            client(module, tmp_path).search("test")
    assert len(calls) == 2
    with endpoint(module, monkeypatch, lambda *a: (429, {}, {"Retry-After": "60"})) as calls:
        with pytest.raises(module.RetrievalError):
            client(module, tmp_path).search("test")
    assert len(calls) == 1


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://localhost/", "http://10.0.0.1/",
                                     "https://user:pass@example.com/", "http://169.254.169.254/latest", "https://example.com:8080/"])
def test_unsafe_urls_never_cross_network_boundary(module, monkeypatch, tmp_path, url):
    with endpoint(module, monkeypatch, lambda *a: (200, {"results": []}, {})) as calls:
        with pytest.raises(module.RetrievalError):
            client(module, tmp_path).fetch([url])
    assert not calls


def test_unmatched_and_empty_content_do_not_claim_answer(module):
    assert module.select_passages("unrelated document", "pricing limits", 100) == ("unrelated document", False)
    assert module.select_passages("", "pricing", 100) == ("", False)
    assert module.select_passages("基础信息 " * 250 + "套餐价格免费额度", "价格额度", 1000)[1]


def test_cli_missing_key_is_secret_free_and_explicitly_unavailable(tmp_path):
    env = {**os.environ, "TINYFISH_API_KEY": "", "TINYFISH_API_KEY_FILE": str(tmp_path / "absent")}
    result = subprocess.run([sys.executable, str(SCRIPTS / "web_search.py"), "search", "test"],
                            capture_output=True, text=True, env=env)
    assert result.returncode == 2 and not result.stderr
    assert json.loads(result.stdout)["code"] == "missing_tinyfish_key"


def test_installer_preserves_user_instructions_override_and_runs_from_unrelated_project(tmp_path):
    cc, cx = tmp_path / "cc", tmp_path / "cx"
    cx.mkdir()
    (cx / "AGENTS.md").write_text("regular instructions\n")
    override = cx / "AGENTS.override.md"
    override.write_text("personal override\n")
    env = {**os.environ, "CLADE_SEARCH_STATE_DIR": str(tmp_path / "state"), "TINYFISH_API_KEY": "",
           "TINYFISH_API_KEY_FILE": str(tmp_path / "absent")}
    command = [sys.executable, str(SCRIPTS / "install_user.py"), "--claude-home", str(cc),
               "--codex-home", str(cx), "--block-provider", "brave"]
    first = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    installed = override.read_text()
    # Updating from the installed copy also preserves the user's provider exclusions.
    command[1] = str(cx / "skills/web-search/scripts/install_user.py")
    second = subprocess.run(command[:-2], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert second.returncode == 0 and override.read_text() == installed
    assert installed.startswith("personal override\n") and installed.count("BEGIN CLADE WEB SEARCH") == 1
    assert "brave" in installed and (cx / "AGENTS.md").read_text() == "regular instructions\n"
    helper = cx / "skills/web-search/scripts/web_search.py"
    run = subprocess.run([sys.executable, str(helper), "route", "--operation", "search", "--native", "available"],
                         cwd=tmp_path, env=env, capture_output=True, text=True)
    assert run.returncode == 0 and json.loads(run.stdout)["provider"] == "native"
    assert (cc / "rules/clade-web-search.md").is_file()
    assert not list((cx / "skills/web-search").rglob("*.key"))
