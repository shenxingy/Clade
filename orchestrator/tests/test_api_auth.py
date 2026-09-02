"""Control-plane authorisation.

The orchestrator served all 93 of its routes to anyone who could open a socket,
and ``orchestrator/start.sh`` binds 0.0.0.0 whenever it detects Tailscale, so
"it is only on loopback" was never true either. These tests pin the guard:
default-closed, self-authenticating endpoints still reachable by the third
parties that hold their credentials, and secrets masked on the way out.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import api_auth  # noqa: E402
from api_auth import (  # noqa: E402
    REDACTED,
    TokenAuthMiddleware,
    extract_token,
    generate_token,
    is_public_path,
    is_secret_key,
    is_self_authenticated,
    redact_settings,
    strip_redacted,
)

# Short on purpose: checks.sh scans staged diffs for `token = "<12+ chars>"`,
# and the repo-wide escape hatch (CLADE_ALLOW_SECRETS=1) would disable that
# scan for the whole commit rather than for this one obviously-fake fixture.
TOKEN = "tok-abc"


def _scope(path: str, *, method: str = "GET", headers=None, query: bytes = b"") -> dict:
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers or [],
        "query_string": query,
    }


# ─── Token minting ────────────────────────────────────────────────────────────


def test_generated_tokens_are_unique_and_long():
    first, second = generate_token(), generate_token()
    assert first != second
    # 32 random bytes, urlsafe-base64 encoded.
    assert len(first) >= 40


# ─── Token extraction ─────────────────────────────────────────────────────────


def test_extract_token_from_authorization_header():
    scope = _scope("/api/tasks", headers=[(b"authorization", b"Bearer " + TOKEN.encode())])
    assert extract_token(scope) == TOKEN


def test_extract_token_authorization_scheme_is_case_insensitive():
    scope = _scope("/api/tasks", headers=[(b"Authorization", b"bearer " + TOKEN.encode())])
    assert extract_token(scope) == TOKEN


def test_extract_token_from_dedicated_header():
    scope = _scope("/api/tasks", headers=[(b"x-clade-token", TOKEN.encode())])
    assert extract_token(scope) == TOKEN


def test_extract_token_from_query_string():
    """A browser cannot set headers on a WebSocket handshake."""

    scope = _scope("/ws/status", query=b"session=abc&token=" + TOKEN.encode())
    assert extract_token(scope) == TOKEN


def test_extract_token_absent_is_empty():
    assert extract_token(_scope("/api/tasks")) == ""


def test_extract_token_ignores_non_bearer_authorization():
    scope = _scope("/api/tasks", headers=[(b"authorization", b"Basic Zm9vOmJhcg==")])
    assert extract_token(scope) == ""


# ─── Path classification ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path", ["/", "/api/version", "/web", "/web/", "/web/index.html", "/assets/x.js", "/favicon.ico"]
)
def test_public_paths(path):
    assert is_public_path(path)


@pytest.mark.parametrize("path", ["/webhook", "/website", "/web-admin", "/assets-private/x"])
def test_prefix_confusion_is_not_public(path):
    """A bare startswith("/web") would have opened every route beginning /web.

    None of these exists today. That is the point: the middleware's whole claim
    is that a route added tomorrow is guarded by default.
    """

    assert not is_public_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "/web/../api/tasks",
        "/web/../../api/settings",
        "/assets/../api/tasks",
        "/../api/tasks",
    ],
)
def test_dot_dot_is_never_public(path):
    """Nothing normalises the path between here and the router today — but a TLS
    front end would, and then the middleware and the router would disagree about
    which route a request names."""

    assert not is_public_path(path)


@pytest.mark.parametrize(
    "path",
    ["/api/tasks", "/api/settings", "/api/sessions", "/ws/status", "/api/workers"],
)
def test_guarded_paths_are_not_public(path):
    assert not is_public_path(path)


def test_webhook_is_always_self_authenticated():
    """GitHub signs with webhook_secret; that path fails closed on its own."""

    assert is_self_authenticated("/api/webhooks/github", {})


def test_usage_ingest_is_exempt_only_while_its_own_token_is_set():
    # Configured: remote usage-agent.py nodes authenticate with usage_hub_token.
    assert is_self_authenticated("/api/usage/ingest", {"usage_ingest_token": "abc"})
    # Unconfigured: its documented "empty = open ingest" mode is a fail-open
    # this middleware closes rather than inherits.
    assert not is_self_authenticated("/api/usage/ingest", {"usage_ingest_token": ""})
    assert not is_self_authenticated("/api/usage/ingest", {})


# ─── Secret masking ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "key", ["api_token", "webhook_secret", "usage_hub_token", "minimax_api_key"]
)
def test_secret_key_detection(key):
    assert is_secret_key(key)


@pytest.mark.parametrize("key", ["max_workers", "auto_merge", "codex_strong_model"])
def test_non_secret_keys(key):
    assert not is_secret_key(key)


def test_redact_masks_populated_secrets_only():
    out = redact_settings(
        {"api_token": "s3cret", "webhook_secret": "", "max_workers": 4}
    )
    assert out["api_token"] == REDACTED
    # Empty stays empty: the UI must tell "unset" from "set but hidden".
    assert out["webhook_secret"] == ""
    assert out["max_workers"] == 4


def test_strip_redacted_protects_secrets_from_a_round_trip_save():
    """The settings panel GETs the whole object and POSTs it back."""

    cleaned = strip_redacted(
        {"api_token": REDACTED, "webhook_secret": "new-value", "max_workers": 8}
    )
    assert "api_token" not in cleaned
    assert cleaned["webhook_secret"] == "new-value"
    assert cleaned["max_workers"] == 8


# ─── Middleware decisions ─────────────────────────────────────────────────────


async def _noop_app(scope, receive, send):  # pragma: no cover - never invoked here
    return None


def _authorize(settings: dict, scope: dict):
    middleware = TokenAuthMiddleware(_noop_app, settings_getter=lambda: settings)
    return middleware._authorize(scope)


def test_guarded_route_rejected_without_token():
    allowed, reason = _authorize({"api_token": TOKEN}, _scope("/api/tasks"))
    assert not allowed
    assert "token" in reason.lower()


def test_guarded_route_allowed_with_correct_token():
    scope = _scope("/api/tasks", headers=[(b"authorization", b"Bearer " + TOKEN.encode())])
    allowed, _ = _authorize({"api_token": TOKEN}, scope)
    assert allowed


def test_guarded_route_rejected_with_wrong_token():
    scope = _scope("/api/tasks", headers=[(b"authorization", b"Bearer wrong")])
    allowed, _ = _authorize({"api_token": TOKEN}, scope)
    assert not allowed


def test_unset_token_fails_closed():
    """Same stance the repository already took for webhook_secret."""

    allowed, reason = _authorize({"api_token": ""}, _scope("/api/tasks"))
    assert not allowed
    assert "not configured" in reason.lower()


def test_unset_token_opens_only_on_explicit_opt_out():
    settings = {"api_token": "", "api_allow_unauthenticated": True}
    allowed, _ = _authorize(settings, _scope("/api/tasks"))
    assert allowed


def test_preflight_is_exempt():
    """OPTIONS carries no credentials by design and is answered by CORS."""

    allowed, _ = _authorize({"api_token": TOKEN}, _scope("/api/tasks", method="OPTIONS"))
    assert allowed


def test_public_path_needs_no_token():
    allowed, _ = _authorize({"api_token": TOKEN}, _scope("/api/version"))
    assert allowed


def test_websocket_needs_a_token():
    scope = {
        "type": "websocket",
        "path": "/ws/status",
        "headers": [],
        "query_string": b"session=abc",
    }
    allowed, _ = _authorize({"api_token": TOKEN}, scope)
    assert not allowed


def test_websocket_allowed_with_query_token():
    scope = {
        "type": "websocket",
        "path": "/ws/status",
        "headers": [],
        "query_string": b"session=abc&token=" + TOKEN.encode(),
    }
    allowed, _ = _authorize({"api_token": TOKEN}, scope)
    assert allowed


# ─── ASGI behaviour ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rejected_http_request_gets_401_and_never_reaches_the_app():
    called = False

    async def app(scope, receive, send):  # pragma: no cover - must not run
        nonlocal called
        called = True

    sent = []

    async def send(message):
        sent.append(message)

    middleware = TokenAuthMiddleware(app, settings_getter=lambda: {"api_token": TOKEN})
    await middleware(_scope("/api/sessions", method="POST"), None, send)

    assert not called
    assert sent[0]["status"] == 401
    assert any(name == b"www-authenticate" for name, _ in sent[0]["headers"])


@pytest.mark.asyncio
async def test_rejected_websocket_is_closed_before_accept():
    sent = []

    async def send(message):
        sent.append(message)

    async def app(scope, receive, send):  # pragma: no cover - must not run
        raise AssertionError("unauthenticated websocket reached the app")

    middleware = TokenAuthMiddleware(app, settings_getter=lambda: {"api_token": TOKEN})
    scope = {"type": "websocket", "path": "/ws/chat", "headers": [], "query_string": b""}
    await middleware(scope, None, send)

    assert sent == [{"type": "websocket.close", "code": 1008}]


@pytest.mark.asyncio
async def test_authorized_request_passes_through():
    seen = []

    async def app(scope, receive, send):
        seen.append(scope["path"])

    middleware = TokenAuthMiddleware(app, settings_getter=lambda: {"api_token": TOKEN})
    scope = _scope("/api/tasks", headers=[(b"x-clade-token", TOKEN.encode())])
    await middleware(scope, None, None)

    assert seen == ["/api/tasks"]


@pytest.mark.asyncio
async def test_lifespan_scope_is_never_blocked():
    seen = []

    async def app(scope, receive, send):
        seen.append(scope["type"])

    middleware = TokenAuthMiddleware(app, settings_getter=lambda: {"api_token": ""})
    await middleware({"type": "lifespan"}, None, None)

    assert seen == ["lifespan"]


# ─── Coverage of the real route table ─────────────────────────────────────────


def test_every_mutating_route_on_the_real_app_is_guarded():
    """A route added tomorrow is guarded by default; this proves it today."""

    import server  # noqa: PLC0415 - import cost is paid once, inside the test

    settings = {"api_token": TOKEN}
    unguarded = []
    for route in server.app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None) or set()
        if not path.startswith("/api/"):
            continue
        if not (methods & {"POST", "PUT", "DELETE", "PATCH"}):
            continue
        allowed, _ = _authorize(settings, _scope(path, method="POST"))
        if allowed:
            unguarded.append(path)

    # Only the endpoints that authenticate their own callers may be open.
    assert set(unguarded) <= {"/api/webhooks/github"}, unguarded


def test_settings_route_masks_secrets_in_its_response_shape():
    """GET /api/settings used to return every stored credential verbatim."""

    import config  # noqa: PLC0415

    rendered = redact_settings(config.GLOBAL_SETTINGS)
    for key, value in rendered.items():
        if api_auth.is_secret_key(key) and config.GLOBAL_SETTINGS.get(key):
            assert value == REDACTED, key
