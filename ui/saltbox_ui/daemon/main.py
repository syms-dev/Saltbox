"""``saltbox-uid``: run the daemon.

Listens on 127.0.0.1 for local tools, on the Docker bridge address so
Traefik can reach it from its container, and on a Unix socket for root-only
access without a token. Every TCP request must carry the bearer token the
daemon keeps in its state directory; the Traefik route adds it after
Authelia has authenticated the person.
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
from pathlib import Path

from ..layout import Layout
from .app import create_app, ensure_token

DEFAULT_PORT = 8701
DEFAULT_SOCKET = "/run/saltbox-ui/api.sock"
DOCKER_BRIDGE_IP = "172.19.0.1"  # the saltbox network gateway, host.docker.internal in Traefik


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="saltbox-uid", description="Saltbox UI daemon")
    parser.add_argument("--host", action="append", help="address to listen on (repeatable)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("SALTBOX_UI_PORT", 0)))
    parser.add_argument("--uds", default=os.environ.get("SALTBOX_UI_SOCKET", DEFAULT_SOCKET))
    parser.add_argument("--no-uds", action="store_true", help="do not listen on a Unix socket")
    parser.add_argument("--no-token", action="store_true", help="development only: no auth")
    parser.add_argument(
        "--web", default=os.environ.get("SALTBOX_UI_WEB"), help="directory with the built web app"
    )
    parser.add_argument("--log-level", default="info")
    return parser


def default_hosts() -> list[str]:
    hosts = ["127.0.0.1"]
    if _address_present(DOCKER_BRIDGE_IP):
        hosts.append(DOCKER_BRIDGE_IP)
    return hosts


def _address_present(address: str) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((address, 0))
    except OSError:
        return False
    return True


def bind_sockets(hosts: list[str], port: int, uds: str | None) -> list[socket.socket]:
    sockets: list[socket.socket] = []
    for host in hosts:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen(128)
        sock.set_inheritable(True)
        sockets.append(sock)
    if uds:
        path = Path(uds)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(path))
        path.chmod(0o600)
        sock.listen(128)
        sock.set_inheritable(True)
        sockets.append(sock)
    return sockets


def web_dir(explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit)
    bundled = Path(__file__).resolve().parents[2] / "web" / "dist"
    return bundled if bundled.exists() else None


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(message)s"
    )
    import uvicorn

    layout = Layout.from_env()
    token = None if args.no_token else ensure_token(layout)
    app = create_app(layout, token=token, web_dir=web_dir(args.web))
    hosts = args.host or default_hosts()
    port = args.port or DEFAULT_PORT
    try:
        sockets = bind_sockets(hosts, port, None if args.no_uds else args.uds)
    except OSError as error:
        print(f"cannot listen: {error}", file=sys.stderr)
        return 1
    for host in hosts:
        logging.info("listening on http://%s:%s", host, port)
    if not args.no_uds:
        logging.info("listening on unix socket %s", args.uds)
    config = uvicorn.Config(app, log_level=args.log_level, proxy_headers=True, ws="websockets")
    server = uvicorn.Server(config)
    server.run(sockets=sockets)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
