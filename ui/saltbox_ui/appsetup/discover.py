"""Find the installed apps, their addresses and their API keys.

Everything comes from what Saltbox leaves on disk: each app's config file
under the appdata path (``/opt/<instance>/config.xml`` for the *arr apps),
instance lists and port overrides from the inventory, the user's name and
password from ``accounts.yml`` (Saltbox gives qBittorrent and Autoscan the
same login), and the Plex token from ``/opt/saltbox/plex.ini``.
"""

from __future__ import annotations

import configparser
import ipaddress
import re
import shutil
import socket
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..config import ConfigService, Inventory
from ..layout import Layout
from ..plex import read_plex_facts

# Saltbox's default web ports (``<role>_role_web_port``); the inventory may override them.
DEFAULT_PORTS = {
    "sonarr": 8989,
    "radarr": 7878,
    "lidarr": 8686,
    "prowlarr": 9696,
    "qbittorrent": 8080,
    "sabnzbd": 8080,
    "autoscan": 3030,
    "plex": 32400,
    "bazarr": 6767,
    "seerr": 5055,
}
API_VERSION = {"sonarr": "v3", "radarr": "v3", "lidarr": "v1", "prowlarr": "v1"}
ARR_ROLES = ("sonarr", "radarr", "lidarr")

Resolver = Callable[[str], str | None]


@dataclass
class Service:
    role: str
    name: str  # instance and container name, e.g. "sonarr" or "sonarr4k"
    port: int
    installed: bool
    api_key: str = ""
    host: str = ""  # address the engine uses from the host

    @property
    def url(self) -> str:
        """Address other containers use: the container name on the saltbox network."""
        return f"http://{self.name}:{self.port}"

    @property
    def host_url(self) -> str:
        return f"http://{self.host or self.name}:{self.port}"


@dataclass
class Discovery:
    services: dict[str, list[Service]] = field(default_factory=dict)
    user: str = ""
    password: str = ""
    plex_token: str = ""
    qbit_vpn: str = ""  # the Gluetun container qBittorrent is routed through, if any

    def first(self, role: str) -> Service | None:
        for service in self.services.get(role, []):
            if service.installed:
                return service
        return None

    def installed(self, role: str) -> list[Service]:
        return [s for s in self.services.get(role, []) if s.installed]


def default_resolver(name: str) -> str | None:
    """The container's address from /etc/hosts (sdhm), or from Docker itself."""
    try:
        socket.gethostbyname(name)
        return name
    except OSError:
        pass
    if shutil.which("docker") is None:
        return None
    result = subprocess.run(
        [
            "docker",
            "inspect",
            "-f",
            "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}",
            name,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    for address in result.stdout.split() if result.returncode == 0 else []:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            continue
        return f"[{parsed}]" if parsed.version == 6 else str(parsed)
    return None


def xml_api_key(path: Path) -> str:
    try:
        match = re.search(r"<ApiKey>\s*([^<\s]+)\s*</ApiKey>", path.read_text(errors="replace"))
    except OSError:
        return ""
    return match.group(1) if match else ""


def sabnzbd_api_key(path: Path) -> str:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return ""
    try:
        parser.read_string("[__top__]\n" + text)
    except configparser.Error:
        return ""
    for section in ("misc", "__top__"):
        if parser.has_option(section, "api_key"):
            return parser.get(section, "api_key").strip()
    return ""


def config_path(layout: Layout, role: str, name: str) -> Path:
    base = layout.appdata / name
    if role == "sabnzbd":
        return base / "sabnzbd.ini"
    if role == "autoscan":
        return base / "config.yml"
    if role == "unpackerr":
        return base / "unpackerr.conf"
    if role == "seerr":
        return base / "settings.json"
    return base / "config.xml"


def discover(
    layout: Layout,
    *,
    inventory: Inventory | None = None,
    config: ConfigService | None = None,
) -> Discovery:
    inventory = inventory or Inventory(layout.inventory)
    config = config or ConfigService(layout)
    result = Discovery()

    accounts = config.load_plain("accounts") if config.exists("accounts") else {}
    user = accounts.get("user") or {}
    result.user = str(user.get("name") or "")
    result.password = str(user.get("pass") or "")

    for role, default_port in DEFAULT_PORTS.items():
        services = []
        for name in inventory.instances(role, [role]):
            port = inventory.effective(role, "_web_port", name, default_port)
            path = config_path(layout, role, name)
            installed = (layout.appdata / name).is_dir()
            service = Service(role=role, name=name, port=int(port), installed=installed)
            if installed:
                if role in API_VERSION:
                    service.api_key = xml_api_key(path)
                elif role == "sabnzbd":
                    service.api_key = sabnzbd_api_key(path)
            services.append(service)
        result.services[role] = services

    qbit = result.first("qbittorrent")
    if qbit is not None:
        mode = str(inventory.effective("qbittorrent", "_docker_network_mode", qbit.name, "") or "")
        if mode.startswith("container:"):
            result.qbit_vpn = mode.split(":", 1)[1]

    plex = result.first("plex")
    if plex is not None:
        result.plex_token = read_plex_facts(layout, plex.name).get("token", "")
    return result


def resolve_hosts(found: Discovery, resolver: Resolver | None = None) -> None:
    """Fill in host-side addresses for installed services."""
    resolve = resolver or default_resolver
    for services in found.services.values():
        for service in services:
            if service.installed and not service.host:
                service.host = resolve(service.name) or service.name
