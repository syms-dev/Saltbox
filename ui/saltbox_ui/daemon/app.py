"""FastAPI application factory."""

from __future__ import annotations

import hmac
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocketClose

from .. import __version__
from ..catalog import Catalog
from ..config import ConfigService, Inventory
from ..layout import Layout
from ..runner import SbRunner
from .jobs import JobManager
from .routes import router
from .updates import UpdateService

log = logging.getLogger("saltbox_ui.daemon")

TOKEN_FILENAME = "api-token"


@dataclass
class Services:
    """Everything the routes need, built once per process."""

    layout: Layout
    config: ConfigService = field(init=False)
    inventory: Inventory = field(init=False)
    catalog: Catalog = field(init=False)
    runner: SbRunner = field(init=False)
    jobs: JobManager = field(init=False)
    token: str | None = None
    web_dir: Path | None = None
    app_setup_factory: Callable[[Layout], Any] | None = None
    updates: UpdateService = field(init=False)

    def __post_init__(self) -> None:
        self.config = ConfigService(self.layout)
        self.inventory = Inventory(self.layout.inventory)
        self.catalog = Catalog(self.layout)
        self.runner = SbRunner(self.layout)
        self.jobs = JobManager(self.runner)
        self.updates = UpdateService(self.layout)
        # An install job pulls new images; check again once it has finished.
        self.jobs.on_finish.append(
            lambda job: self.updates.refresh() if job.kind in {"install", "update"} else None
        )


class DaemonGuard:
    """Require the daemon token on TCP connections, for HTTP and WebSocket alike.

    Traefik adds the token to every request it forwards after Authelia has let
    the person through; local tools read it from the state directory. A
    connection over the Unix socket has no client address and is trusted: only
    root can open the socket.

    Browsers also say where a request comes from. A state-changing request that
    another site started (``Sec-Fetch-Site`` other than ``same-origin`` or
    ``none``), or a WebSocket opened from another origin, is refused even though
    Traefik would add the token to it: a page on a sibling app's subdomain
    shares the Authelia cookie and must not be able to start jobs here.

    This is plain ASGI rather than ``BaseHTTPMiddleware``, which never sees
    WebSocket connections.
    """

    SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
    SAME_SITE = frozenset({"same-origin", "none"})

    def __init__(self, app: ASGIApp, token: str):
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope["type"]
        if kind not in ("http", "websocket") or not scope.get("path", "").startswith("/api/"):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        reason = self._refusal(scope, headers)
        if reason is None:
            await self.app(scope, receive, send)
        elif kind == "websocket":
            code = 4401 if reason == "unauthorised" else 4403
            await WebSocketClose(code=code)(scope, receive, send)
        else:
            status = 401 if reason == "unauthorised" else 403
            await JSONResponse({"error": reason}, status_code=status)(scope, receive, send)

    def _refusal(self, scope: Scope, headers: Headers) -> str | None:
        if scope.get("client") is not None:
            header = headers.get("authorization", "")
            presented = header[7:] if header.lower().startswith("bearer ") else ""
            if not presented or not hmac.compare_digest(presented, self.token):
                return "unauthorised"
        if scope["type"] == "websocket":
            origin = headers.get("origin")
            if origin and urlsplit(origin).netloc != headers.get("host", ""):
                return "cross-origin request refused"
        elif scope.get("method", "GET") not in self.SAFE_METHODS:
            site = headers.get("sec-fetch-site")
            if site is not None and site not in self.SAME_SITE:
                return "cross-site request refused"
        return None


def create_app(
    layout: Layout | None = None,
    *,
    token: str | None = None,
    web_dir: Path | None = None,
    services: Services | None = None,
) -> FastAPI:
    services = services or Services(layout or Layout.from_env(), token=token, web_dir=web_dir)
    app = FastAPI(
        title="saltbox-ui",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.services = services
    app.include_router(router, prefix="/api")
    if services.token:
        app.add_middleware(DaemonGuard, token=services.token)
    if services.web_dir and (services.web_dir / "index.html").exists():
        _mount_web(app, services.web_dir)
    else:

        @app.get("/", include_in_schema=False)
        def no_web() -> JSONResponse:
            return JSONResponse(
                {
                    "message": "saltbox-ui daemon is running; the web app is not built",
                    "api": "/api/docs",
                }
            )

    return app


def _mount_web(app: FastAPI, web_dir: Path) -> None:
    """Serve the built web app with a single-page fallback to index.html."""
    root = web_dir.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        candidate = (root / path).resolve() if path else root / "index.html"
        if candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(root / "index.html")


def default_web_dir(layout: Layout) -> Path | None:
    """The built web app: the repo checkout first, then next to the package."""
    candidates = [
        layout.repo / "ui" / "web" / "dist",
        Path(__file__).resolve().parents[2] / "web" / "dist",
    ]
    for candidate in candidates:
        if (candidate / "index.html").exists():
            return candidate
    return None


def read_token(layout: Layout) -> str | None:
    path = layout.state_dir / TOKEN_FILENAME
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def ensure_token(layout: Layout) -> str:
    """Return the daemon token, creating it (root only) when missing."""
    import secrets

    path = layout.state_dir / TOKEN_FILENAME
    existing = read_token(layout)
    if existing:
        return existing
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(token + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)
    return token
