"""Bearer-token authorisation for the orchestrator control plane.

Why this exists
---------------
Every route on this server was reachable by anyone who could open a socket to
it. That is not a theoretical exposure:

* ``orchestrator/start.sh`` binds ``0.0.0.0`` — not loopback — whenever it
  detects Tailscale, which is the documented way to run this server
  (``docs/orchestrator.md``). The control plane is therefore offered to the
  whole tailnet by default, not to one machine.
* Even on loopback, a multi-user host has no trust boundary at 127.0.0.1: any
  local account can connect.
* ``POST /api/sessions`` opens a session on an arbitrary path and its workers
  run ``--dangerously-skip-permissions`` with the parent environment passed
  through, as the account that started the server. ``GET /api/settings``
  returned every stored secret verbatim.

``orchestrator/caddy-setup.sh`` does configure Basic Auth, but only in front of
a public domain; it never covers the socket itself, and it is a separate
one-time script the main docs do not reference.

Design
------
Pure ASGI middleware rather than ``BaseHTTPMiddleware`` or a per-route
``Depends``. Two reasons: ``BaseHTTPMiddleware`` only sees ``http`` scopes, so
it cannot guard ``/ws/chat`` and ``/ws/status``; and a dependency has to be
added to all 93 route decorators, where the next route added silently forgets
it. Middleware is default-closed for anything new.

Fail closed, following the precedent this repository already set for
``webhook_secret``: no configured token means every guarded request is
rejected, unless the operator explicitly sets ``api_allow_unauthenticated``.
``config.ensure_api_token`` mints one on first start, so the rejection path is
a misconfiguration signal, never the normal case.

This module is a stdlib-only leaf. It never imports project modules — the
caller passes a settings accessor — so it can sit at the bottom of the import
DAG next to ``runtime_redaction``.
"""

from __future__ import annotations

import hmac
import json
import secrets
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs

# 32 bytes of urlsafe base64 ≈ 43 characters. Same order as a GitHub PAT.
TOKEN_BYTES = 32

# Header name accepted in addition to ``Authorization: Bearer``. A browser can
# set this on fetch(); it cannot set headers on a WebSocket handshake, which is
# why the query parameter below also exists.
TOKEN_HEADER = "x-clade-token"
TOKEN_QUERY_PARAM = "token"

# Served to anyone: the SPA shell and its static assets, plus the version probe
# that exists precisely so an operator can tell whether a *stale* process is
# running before they can be expected to hold a credential. None of these read
# or mutate project state.
PUBLIC_EXACT = frozenset({"/", "/api/version"})
PUBLIC_PREFIXES = ("/web/", "/web", "/favicon.ico", "/assets/")

# Endpoints that authenticate their callers themselves, with a *different*
# credential that a third party legitimately holds. Guarding them with the
# operator token would break them: GitHub signs webhooks with
# ``webhook_secret`` (and that path already fails closed on its own), and
# ``usage-agent.py`` on other machines pushes with ``usage_hub_token``.
#
# ``/api/usage/ingest`` is exempt only while ``usage_ingest_token`` is set. Its
# documented "empty token = open ingest" mode is a fail-open that this
# middleware closes rather than inherits.
SELF_AUTHENTICATED_ALWAYS = frozenset({"/api/webhooks/github"})
SELF_AUTHENTICATED_IF_SET = {"/api/usage/ingest": "usage_ingest_token"}

# Value substituted for a secret in any response that echoes settings back.
# ``POST /api/settings`` must treat it as "leave this key alone" — the settings
# panel GETs the whole object and POSTs the whole object back, so without that
# rule the first save would overwrite every secret with the mask.
REDACTED = "********"

# A settings key is a secret if its name ends with one of these. Matching on
# the name rather than a hand-kept list means a secret added later is masked
# the day it is added, which is the failure mode a list has.
_SECRET_SUFFIXES = ("_token", "_secret", "_key", "_password")


def generate_token() -> str:
    """Mint a fresh control-plane token."""

    return secrets.token_urlsafe(TOKEN_BYTES)


def is_secret_key(key: str) -> bool:
    """True when a settings key holds a credential rather than a preference."""

    return key.endswith(_SECRET_SUFFIXES)


def redact_settings(settings: Mapping[str, Any]) -> dict:
    """Copy of ``settings`` with every non-empty secret replaced by a mask.

    An empty secret stays empty rather than becoming a mask: the UI needs to
    tell "not configured" from "configured, hidden", and masking an empty
    string would report a credential that does not exist.
    """

    out = {}
    for key, value in settings.items():
        if is_secret_key(key) and isinstance(value, str) and value:
            out[key] = REDACTED
        else:
            out[key] = value
    return out


def strip_redacted(body: Mapping[str, Any]) -> dict:
    """Drop keys a client echoed back still masked, so a save cannot erase one."""

    return {
        key: value
        for key, value in body.items()
        if not (is_secret_key(key) and value == REDACTED)
    }


def _header(scope_headers: list, name: str) -> str:
    """Read one header out of a raw ASGI header list. Case-insensitive."""

    wanted = name.lower().encode()
    for raw_key, raw_value in scope_headers:
        if raw_key.lower() == wanted:
            return raw_value.decode("latin-1")
    return ""


def extract_token(scope: Mapping[str, Any]) -> str:
    """Pull a presented token out of an ASGI scope.

    Three sources, in order of preference. The query parameter is last and
    exists because the WebSocket handshake gives a browser no way to set a
    header; it is also what makes the printed start-up URL work as a one-click
    hand-off into the UI.
    """

    headers = scope.get("headers") or []

    authorization = _header(headers, "authorization")
    if authorization[:7].lower() == "bearer ":
        token = authorization[7:].strip()
        if token:
            return token

    direct = _header(headers, TOKEN_HEADER).strip()
    if direct:
        return direct

    query = scope.get("query_string") or b""
    if query:
        values = parse_qs(query.decode("latin-1")).get(TOKEN_QUERY_PARAM) or []
        if values and values[0].strip():
            return values[0].strip()

    return ""


def is_public_path(path: str) -> bool:
    """True for paths served without any credential."""

    return path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIXES)


def is_self_authenticated(path: str, settings: Mapping[str, Any]) -> bool:
    """True for paths that carry their own, different credential."""

    if path in SELF_AUTHENTICATED_ALWAYS:
        return True
    setting_name = SELF_AUTHENTICATED_IF_SET.get(path)
    if setting_name is None:
        return False
    return bool(str(settings.get(setting_name) or "").strip())


class TokenAuthMiddleware:
    """Reject any control-plane request that does not present the token.

    ``settings_getter`` is called per request rather than captured once, so
    rotating the token through the API takes effect on the next request instead
    of at the next restart.
    """

    def __init__(
        self,
        app: Callable,
        settings_getter: Callable[[], Mapping[str, Any]],
    ) -> None:
        self.app = app
        self._settings = settings_getter

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        allowed, reason = self._authorize(scope)
        if allowed:
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            # Closing before accepting makes the server answer the handshake
            # with an HTTP error, which is what a browser surfaces.
            await send({"type": "websocket.close", "code": 1008})
            return

        await self._reject(send, reason)

    def _authorize(self, scope: dict) -> tuple[bool, str]:
        path = scope.get("path", "")

        if is_public_path(path):
            return True, ""

        # A CORS preflight carries no credentials by design and is answered by
        # CORSMiddleware, which sits outside this one. Letting OPTIONS through
        # keeps the two orderings equivalent and leaks nothing: the preflight
        # response describes policy, never data.
        if scope["type"] == "http" and scope.get("method", "").upper() == "OPTIONS":
            return True, ""

        settings = self._settings() or {}

        if is_self_authenticated(path, settings):
            return True, ""

        expected = str(settings.get("api_token") or "").strip()
        if not expected:
            if settings.get("api_allow_unauthenticated", False):
                return True, ""
            return False, (
                "Control plane is not configured: api_token is unset. Restart the "
                "orchestrator to mint one, or set api_allow_unauthenticated to serve "
                "without authentication deliberately."
            )

        presented = extract_token(scope)
        if presented and hmac.compare_digest(presented, expected):
            return True, ""
        return False, "Missing or invalid API token."

    @staticmethod
    async def _reject(send: Callable, reason: str) -> None:
        body = json.dumps({"detail": reason}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"www-authenticate", b'Bearer realm="clade-orchestrator"'),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
