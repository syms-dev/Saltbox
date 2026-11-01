"""FastAPI application factory."""

from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .. import __version__
from ..catalog import Catalog
from ..config import ConfigService, Inventory
from ..layout import Layout
from ..runner import SbRunner
from .jobs import JobManager
from .routes import router

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

    def __post_init__(self) -> None:
        self.config = ConfigService(self.layout)
        self.inventory = Inventory(self.layout.inventory)
        self.catalog = Catalog(self.layout)
        self.runner = SbRunner(self.layout)
        self.jobs = JobManager(self.runner)


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Require the daemon token on TCP connections.

    Traefik adds the token to every request it forwards after Authelia has let
    the person through; local tools read it from the state directory. A
    connection over the Unix socket has no client address and is trusted: only
    root can open the socket.
    """

    def __init__(self, app, token: str):
        super().__init__(app)
        self.token = token

    async def dispatch(self, request: Request, call_next):
        if request.client is None or not request.url.path.startswith("/api/"):
            return await call_next(request)
        header = request.headers.get("authorization", "")
        presented = header[7:] if header.lower().startswith("bearer ") else ""
        if not presented or not hmac.compare_digest(presented, self.token):
            return JSONResponse({"error": "unauthorised"}, status_code=401)
        return await call_next(request)


def create_app(
    layout: Layout | None = None,
    *,
    token: str | None = None,
    web_dir: Path | None = None,
    services: Services | None = None,
) -> FastAPI:
    services = services or Services(layout or Layout.from_env(), token=token, web_dir=web_dir)
    app = FastAPI(title="saltbox-ui", version=__version__, docs_url="/api/docs", redoc_url=None)
    app.state.services = services
    app.include_router(router, prefix="/api")
    if services.token:
        app.add_middleware(BearerTokenMiddleware, token=services.token)
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
