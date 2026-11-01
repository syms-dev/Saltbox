"""The saltbox-ui daemon: a FastAPI service over the engine.

Both faces talk to it: the web app through Traefik and Authelia, local tools
through a Unix socket. It owns the one-at-a-time job queue so an install
started from a browser survives the tab closing.
"""

from .app import Services, create_app

__all__ = ["Services", "create_app"]
