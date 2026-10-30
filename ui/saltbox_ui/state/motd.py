"""The MOTD config, the most convenient list of app URLs and credentials.

``sb install motd-generate-config`` writes ``motd.yml`` with one section per
service type and one entry per instance. Secrets are redacted by default.
"""

from __future__ import annotations

from typing import Any

from ..layout import Layout
from ..yamlio import load_plain
from .facts import redact_value

SECTIONS = (
    "plex",
    "emby",
    "jellyfin",
    "sonarr",
    "radarr",
    "lidarr",
    "readarr",
    "sabnzbd",
    "nzbget",
    "qbittorrent",
    "rtorrent",
)


def read_motd_services(layout: Layout, *, redact: bool = True) -> list[dict[str, Any]]:
    path = layout.config_file("motd")
    if not path.exists():
        return []
    data = load_plain(path) or {}
    services: list[dict[str, Any]] = []
    for section in SECTIONS:
        block = data.get(section)
        if block is None:
            continue
        instances = block if isinstance(block, list) else block.get("instances") or []
        enabled = True if isinstance(block, list) else block.get("enabled", True)
        for instance in instances:
            if not isinstance(instance, dict):
                continue
            entry = {"service": section, "section_enabled": bool(enabled)}
            for key, value in instance.items():
                entry[key] = (
                    redact_value(key, str(value)) if redact and value is not None else value
                )
            services.append(entry)
    return services
