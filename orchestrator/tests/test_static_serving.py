"""How the orchestrator serves its own UI.

Three defects live here, and all three were invisible because nothing asserted
on the static surface:

1. ``GET /`` returned ``FileResponse(web/index.html)`` unconditionally. Since
   7d5603b that file is the Vite *source* shell — it loads ``/src/main.tsx``,
   raw TypeScript no browser will execute — so the documented entry URL
   (``start.sh`` prints ``http://localhost:8765``) rendered a blank page on
   every machine, built or not. Only ``/web/`` worked.
2. The static mount fell back to ``web/`` when ``web/dist`` was absent, which
   the code called "legacy". It stopped being legacy the moment 7d5603b
   overwrote the xterm + ``app-*.js`` page: the fallback served the same
   unbootable shell, silently, with no hint that a build was missing.
3. ``/web/usage.html`` 404s once ``dist`` exists — Vite declares no
   ``publicDir``, so the hand-written dashboard is never copied into the build
   output, and the mount is the only thing that used to serve it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.routing import Mount

import server


def _mounted_static_dirs(app: FastAPI) -> list[Path]:
    dirs = []
    for route in app.routes:
        inner = getattr(route, "app", None)
        directory = getattr(inner, "directory", None)
        if isinstance(route, Mount) and directory is not None:
            dirs.append(Path(str(directory)))
    return dirs


def test_root_redirects_to_web():
    """`/` must hand off to the one code path that owns the shell."""

    with TestClient(server.app, follow_redirects=False) as client:
        r = client.get("/")
    assert r.status_code in (307, 308), r.status_code
    assert r.headers["location"] == "/web/"


def test_root_never_returns_the_unbuilt_vite_shell():
    """The regression this file exists for: `/` used to return `main.tsx`."""

    with TestClient(server.app, follow_redirects=False) as client:
        r = client.get("/")
    assert "main.tsx" not in r.text


def test_no_route_serves_the_vite_source_directory():
    """`web/` is a source tree, never a static root. Would have caught 7d5603b."""

    source_dir = Path(server.WEB_DIR).resolve()
    for directory in _mounted_static_dirs(server.app):
        assert directory.resolve() != source_dir, (
            f"{directory} is the Vite source dir; only web/dist may be mounted"
        )


def test_usage_dashboard_has_its_own_route_not_just_the_mount():
    """Dist-independent: the mount cannot serve a file Vite never copies."""

    paths = [getattr(r, "path", None) for r in server.app.routes]
    assert "/web/usage.html" in paths

    idx_route = paths.index("/web/usage.html")
    mount_idx = [
        i for i, r in enumerate(server.app.routes)
        if isinstance(r, Mount) and getattr(r, "path", "") == "/web"
    ]
    # Starlette matches in registration order, so a Mount at /web declared
    # first would swallow the usage route and 404 it on built machines.
    for i in mount_idx:
        assert idx_route < i, "/web/usage.html must be registered before the /web mount"


def test_usage_dashboard_is_served():
    with TestClient(server.app) as client:
        r = client.get("/web/usage.html")
    assert r.status_code == 200, r.status_code
    assert "Clade — Usage by Machine" in r.text


@pytest.fixture()
def unbuilt_app(tmp_path):
    """A server whose `web/dist` does not exist."""

    app = FastAPI()
    server.mount_web_ui(app, tmp_path / "dist-does-not-exist", Path(server.WEB_DIR))
    return app


def test_unbuilt_web_returns_503_naming_the_build_command(unbuilt_app):
    with TestClient(unbuilt_app) as client:
        for path in ("/web/", "/web/index.html", "/web/assets/index.js"):
            r = client.get(path)
            assert r.status_code == 503, f"{path} -> {r.status_code}"
            assert "npm run build" in r.json()["error"], path


def test_unbuilt_web_still_serves_the_usage_dashboard(unbuilt_app):
    """An operator with no node toolchain still gets the usage dashboard."""

    with TestClient(unbuilt_app) as client:
        r = client.get("/web/usage.html")
    assert r.status_code == 200
    assert "Clade — Usage by Machine" in r.text


def test_built_web_mounts_dist_only(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>built</html>")

    app = FastAPI()
    server.mount_web_ui(app, dist, Path(server.WEB_DIR))

    assert [d.resolve() for d in _mounted_static_dirs(app)] == [dist.resolve()]
    with TestClient(app) as client:
        assert client.get("/web/").text == "<html>built</html>"
        # Still the explicit route, not the mount — dist has no usage.html.
        assert client.get("/web/usage.html").status_code == 200
