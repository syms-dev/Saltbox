"""Recyclarr, set up from the web app: pick TRaSH Guides profiles, write the config.

Recyclarr (the Sandbox role) syncs quality profiles and custom formats from the
TRaSH Guides into Sonarr and Radarr. With Recyclarr 8 a profile is one
``trash_id``; this module writes ``recyclarr.yml`` with the chosen ones for
every installed Sonarr and Radarr instance, and ``secrets.yml`` with their
addresses and API keys read from the apps' own config, so no key is ever typed
or shown. A config written by hand is kept as a dated ``.bak`` copy first.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .appsetup.discover import Discovery
from .layout import Layout
from .yamlio import write_atomic

MARKER = "# Managed by the Saltbox UI"
CONTAINER = "recyclarr"


@dataclass(frozen=True)
class Profile:
    trash_id: str
    name: str
    summary: str
    default: bool = False


PROFILES: dict[str, list[Profile]] = {
    "sonarr": [
        Profile(
            "72dae194fc92bf828f32cde7744e51a1",
            "WEB-1080p",
            "1080p releases from streaming services. The TRaSH Guides default for TV.",
            default=True,
        ),
        Profile(
            "d1498e7d189fbe6c7110ceaabb7473e6",
            "WEB-2160p",
            "4K releases from streaming services, with HDR when there is one.",
        ),
    ],
    "radarr": [
        Profile(
            "d1d67249d3890e49bc12e275d989a7e9",
            "HD Bluray + WEB",
            "1080p Blu-ray encodes and streaming releases. The default for movies.",
            default=True,
        ),
        Profile(
            "64fb5f9858489bdac2af690e27c8f42f",
            "UHD Bluray + WEB",
            "4K Blu-ray encodes and streaming releases.",
        ),
        Profile(
            "9ca12ea80aa55ef916e3751f4b874151",
            "Remux + WEB 1080p",
            "Untouched 1080p Blu-ray remuxes; large files (20-40 GB a film).",
        ),
        Profile(
            "fd161a61e3ab826d3a22d53f935696dd",
            "Remux + WEB 2160p",
            "Untouched 4K remuxes; very large files (40-80 GB a film).",
        ),
    ],
}
QUALITY_TYPE = {"sonarr": "series", "radarr": "movie"}
TRASH_ID = re.compile(r"trash_id:\s*['\"]?([0-9a-f]{32})")


def config_dir(layout: Layout) -> Path:
    return layout.appdata / CONTAINER


def status(
    layout: Layout, found: Discovery, containers: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """What is installed, what the config selects now, and whether we wrote it."""
    directory = config_dir(layout)
    config = directory / "recyclarr.yml"
    text = config.read_text(encoding="utf-8") if config.exists() else ""
    selected = set(TRASH_ID.findall(text))
    record = containers.get(CONTAINER)
    return {
        "installed": directory.is_dir() or record is not None,
        "running": bool(record and record.get("status") == "running"),
        "config_exists": config.exists(),
        "managed": text.startswith(MARKER) or not text.strip(),
        "selected": {
            app: [p.trash_id for p in profiles if p.trash_id in selected]
            for app, profiles in PROFILES.items()
        },
        "profiles": {app: [asdict(p) for p in profiles] for app, profiles in PROFILES.items()},
        "instances": {app: [s.name for s in found.installed(app) if s.api_key] for app in PROFILES},
    }


class RecyclarrError(ValueError):
    pass


def write_config(
    layout: Layout, found: Discovery, selection: dict[str, list[str]]
) -> dict[str, Any]:
    """Write recyclarr.yml and secrets.yml for the chosen profiles; returns what was done."""
    directory = config_dir(layout)
    if not directory.is_dir():
        raise RecyclarrError("Recyclarr is not installed (no /opt/recyclarr yet)")
    known = {app: {p.trash_id: p for p in profiles} for app, profiles in PROFILES.items()}
    chosen = {
        app: [known[app][i] for i in ids if i in known.get(app, {})]
        for app, ids in selection.items()
        if app in PROFILES
    }
    instances = {app: [s for s in found.installed(app) if s.api_key] for app in PROFILES}
    if not any(chosen.get(app) and instances[app] for app in PROFILES):
        raise RecyclarrError("choose at least one profile for an installed Sonarr or Radarr")

    lines = [
        f"{MARKER}. Saving profiles there replaces this file; the previous one is kept as .bak.",
        "# Profiles come from the TRaSH Guides: https://trash-guides.info",
    ]
    secrets = [f"{MARKER}: addresses and API keys for recyclarr.yml."]
    for app in PROFILES:
        profiles, services = chosen.get(app) or [], instances[app]
        if not profiles or not services:
            continue
        lines.append(f"{app}:")
        for service in services:
            lines += [
                f"  {service.name}:",
                f"    base_url: !secret {service.name}_url",
                f"    api_key: !secret {service.name}_apikey",
                "    delete_old_custom_formats: true",
                "    quality_definition:",
                f"      type: {QUALITY_TYPE[app]}",
                "    quality_profiles:",
            ]
            for profile in profiles:
                lines += [
                    f"      - trash_id: {profile.trash_id}  # {profile.name}",
                    "        reset_unmatched_scores:",
                    "          enabled: true",
                ]
            secrets += [
                f"{service.name}_url: {service.url}",
                f'{service.name}_apikey: "{service.api_key}"',
            ]

    config = directory / "recyclarr.yml"
    backup = None
    if config.exists():
        current = config.read_text(encoding="utf-8")
        if current.strip() and not current.startswith(MARKER):
            backup = directory / f"recyclarr.yml.bak-{time.strftime('%Y%m%d-%H%M%S')}"
            backup.write_text(current, encoding="utf-8")
            _match_owner(backup, directory)
    write_atomic(config, "\n".join(lines) + "\n")
    secrets_path = directory / "secrets.yml"
    write_atomic(secrets_path, "\n".join(secrets) + "\n")
    secrets_path.chmod(0o600)
    for path in (config, secrets_path):
        _match_owner(path, directory)
    return {
        "config": str(config),
        "backup": str(backup) if backup else None,
        "instances": {app: [s.name for s in instances[app]] for app in PROFILES},
    }


def _match_owner(path: Path, directory: Path) -> None:
    """Files Recyclarr reads belong to whoever owns its folder (the container's user)."""
    try:
        info = directory.stat()
        if os.geteuid() == 0:
            os.chown(path, info.st_uid, info.st_gid)
    except OSError:
        pass
