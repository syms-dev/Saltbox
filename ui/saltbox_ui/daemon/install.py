"""Wire the daemon into the host: a systemd unit and a Traefik route.

The route is a Traefik file-provider fragment in Traefik's config directory
(``/opt/traefik`` by default, watched by Traefik). It sends
``saltbox.<domain>`` through the same middleware chain Saltbox gives every
app, including Authelia, then adds the daemon's bearer token so the daemon
can tell Traefik's traffic from anything else on the host.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from ..config import ConfigService
from ..layout import Layout
from ..yamlio import write_atomic
from .main import DEFAULT_PORT, DEFAULT_SOCKET, DOCKER_BRIDGE_IP

UNIT_NAME = "saltbox-ui.service"
ROUTE_FILENAME = "saltbox-ui.yml"
DEFAULT_SUBDOMAIN = "saltbox"


def systemd_unit(executable: str | None = None, *, web: Path | None = None) -> str:
    exe = executable or _daemon_executable()
    extra = f" --web {web}" if web else ""
    return f"""[Unit]
Description=Saltbox UI daemon
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
ExecStart={exe}{extra}
Restart=on-failure
RestartSec=5
RuntimeDirectory=saltbox-ui
RuntimeDirectoryMode=0700
StateDirectory=saltbox-ui
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
"""


def _daemon_executable() -> str:
    found = shutil.which("saltbox-uid")
    if found:
        return found
    return f"{sys.executable} -m saltbox_ui.daemon.main"


def traefik_route(
    *,
    domain: str,
    token: str,
    subdomain: str = DEFAULT_SUBDOMAIN,
    port: int = DEFAULT_PORT,
    upstream_ip: str = DOCKER_BRIDGE_IP,
    certresolver: str = "cfdns",
    wildcard: bool = True,
    hsts: bool = False,
    sso_middleware: str = "authelia@docker",
) -> str:
    host = f"{subdomain}.{domain}"
    middlewares = ["globalHeaders@file", "secureHeaders@file", "robotHeaders@file"]
    if hsts:
        middlewares.append("hsts@file")
    middlewares += [sso_middleware, "saltbox-ui-token@file"]
    middleware_lines = "\n".join(f"        - {m}" for m in middlewares)
    tls = f"        certResolver: {certresolver}\n"
    if wildcard:
        tls += (
            f"        domains:\n          - main: {domain}\n"
            f"            sans:\n              - '*.{domain}'\n"
        )
    return f"""# Managed by saltbox-ui. The daemon listens on the Docker bridge address so
# Traefik reaches it from its container; Authelia runs first, then the token
# header tells the daemon the request came through this route.
http:
  routers:
    saltbox-ui-http:
      rule: Host(`{host}`)
      entryPoints:
        - web
      service: saltbox-ui
      middlewares:
        - globalHeaders@file
        - redirect-to-https@docker
    saltbox-ui:
      rule: Host(`{host}`)
      entryPoints:
        - websecure
      service: saltbox-ui
      middlewares:
{middleware_lines}
      tls:
{tls}  middlewares:
    saltbox-ui-token:
      headers:
        customRequestHeaders:
          Authorization: "Bearer {token}"
  services:
    saltbox-ui:
      loadBalancer:
        servers:
          - url: http://{upstream_ip}:{port}
"""


def route_settings(config: ConfigService) -> dict[str, Any]:
    """Derive the route parameters from accounts.yml and adv_settings.yml."""
    accounts = config.load_plain("accounts") if config.exists("accounts") else {}
    adv = config.load_plain("adv_settings") if config.exists("adv_settings") else {}
    traefik = adv.get("traefik") or {}
    cert = traefik.get("cert") or {}
    http_validation = str(cert.get("http_validation", "no")).lower() in {"yes", "true"}
    zerossl = str(cert.get("zerossl", "no")).lower() in {"yes", "true"}
    if http_validation:
        resolver = "zerosslhttp" if zerossl else "httpresolver"
    else:
        resolver = "zerossl" if zerossl else "cfdns"
    return {
        "domain": (accounts.get("user") or {}).get("domain") or "",
        "certresolver": resolver,
        "wildcard": not http_validation,
        "hsts": str(traefik.get("hsts", "no")).lower() in {"yes", "true"},
    }


def write_route(
    layout: Layout,
    token: str,
    *,
    subdomain: str = DEFAULT_SUBDOMAIN,
    traefik_dir: Path | None = None,
) -> Path:
    config = ConfigService(layout)
    settings = route_settings(config)
    if not settings["domain"]:
        raise ValueError("accounts.yml has no user.domain; run the installer first")
    target_dir = traefik_dir or (layout.appdata / "traefik")
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / ROUTE_FILENAME
    write_atomic(path, traefik_route(token=token, subdomain=subdomain, **settings))
    path.chmod(0o600)
    return path


def install_unit(unit_dir: Path = Path("/etc/systemd/system"), *, web: Path | None = None) -> Path:
    path = unit_dir / UNIT_NAME
    unit_dir.mkdir(parents=True, exist_ok=True)
    write_atomic(path, systemd_unit(web=web))
    return path


def systemctl(*args: str) -> tuple[int, str]:
    if shutil.which("systemctl") is None:
        return 127, "systemctl not found"
    result = subprocess.run(
        ["systemctl", *args], capture_output=True, text=True, check=False, timeout=60
    )
    return result.returncode, (result.stdout + result.stderr).strip()


def enable_web(
    layout: Layout,
    *,
    subdomain: str = DEFAULT_SUBDOMAIN,
    web: Path | None = None,
    unit_dir: Path = Path("/etc/systemd/system"),
    traefik_dir: Path | None = None,
    start: bool = True,
) -> dict[str, Any]:
    """Token, Traefik route, systemd unit, enable: everything the web face needs.

    Returns what was done; ``url`` is where the web app will answer once
    Traefik has picked up the route and issued a certificate.
    """
    from .app import ensure_token

    token = ensure_token(layout)
    route = write_route(layout, token, subdomain=subdomain, traefik_dir=traefik_dir)
    unit = install_unit(unit_dir, web=web)
    result: dict[str, Any] = {"route": str(route), "unit": str(unit), "steps": {}}
    if start:
        code, output = systemctl("daemon-reload")
        result["steps"]["daemon-reload"] = output or ("ok" if code == 0 else f"exit {code}")
        code, output = systemctl("enable", "--now", UNIT_NAME)
        result["steps"]["enable"] = output or ("ok" if code == 0 else f"exit {code}")
        result["started"] = code == 0
    result["url"] = url_for(layout, subdomain)
    return result


def url_for(layout: Layout, subdomain: str = DEFAULT_SUBDOMAIN) -> str | None:
    config = ConfigService(layout)
    domain = route_settings(config)["domain"]
    return f"https://{subdomain}.{domain}" if domain else None


SOCKET_PATH = DEFAULT_SOCKET
