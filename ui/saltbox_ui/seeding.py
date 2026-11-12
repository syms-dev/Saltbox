"""Finished torrents in qBittorrent: how many keep seeding, and when they stop.

Sonarr and Radarr remove a finished download from qBittorrent (and its copy in
the downloads folder) only once qBittorrent has *stopped* it because it reached
a seeding limit: its state is ``pausedUP``/``stoppedUP`` and the ratio or time
limit is met (Sonarr's ``QBittorrent.cs``, ``CanBeRemoved``). qBittorrent ships
with no limit, so by default nothing ever stops and finished torrents pile up.

This module reads that picture and sets qBittorrent's global limits: a share
ratio, a seeding time, or both (whichever comes first), with "stop the torrent"
as the action. Never "remove": the apps have to see the stopped torrent to
finish their own bookkeeping, and they complain when qBittorrent removes it.
"""

from __future__ import annotations

import json
from typing import Any

from .appsetup.discover import Service
from .appsetup.http import Transport
from .media import qbit_request

SEEDING_STATES = {"uploading", "stalledUP", "forcedUP", "queuedUP", "checkingUP"}
STOPPED_STATES = {"pausedUP", "stoppedUP"}  # qBittorrent 4 says paused, 5 says stopped
ACTIONS = {0: "stop", 1: "remove", 2: "super_seed", 3: "remove_files"}
STOP = 0
MINUTES_PER_DAY = 1440
MAX_RATIO = 100.0
MAX_DAYS = 3650.0
TOP_CATEGORIES = 6


class SeedingError(ValueError):
    pass


def limits(preferences: dict[str, Any]) -> dict[str, Any]:
    """The global seeding limits in qBittorrent's preferences, in ratio and days."""

    def enabled(flag: str, value: str) -> float | None:
        number = preferences.get(value)
        if not preferences.get(flag) or not isinstance(number, int | float) or number < 0:
            return None
        return float(number)

    minutes = enabled("max_seeding_time_enabled", "max_seeding_time")
    idle = enabled("max_inactive_seeding_time_enabled", "max_inactive_seeding_time")
    return {
        "ratio": enabled("max_ratio_enabled", "max_ratio"),
        "days": None if minutes is None else round(minutes / MINUTES_PER_DAY, 2),
        "inactive_days": None if idle is None else round(idle / MINUTES_PER_DAY, 2),
        "action": ACTIONS.get(int(preferences.get("max_ratio_act") or 0), "stop"),
    }


def summary(torrents: list[dict[str, Any]]) -> dict[str, Any]:
    """Finished torrents by what they are doing: still seeding, or stopped and left there."""
    groups: dict[str, dict[str, Any]] = {
        "seeding": {"count": 0, "size": 0},
        "stopped": {"count": 0, "size": 0},
    }
    categories: dict[str, dict[str, int]] = {}
    longest = 0
    for torrent in torrents:
        state = str(torrent.get("state", ""))
        kind = (
            "seeding" if state in SEEDING_STATES else "stopped" if state in STOPPED_STATES else None
        )
        if kind is None:
            continue
        groups[kind]["count"] += 1
        groups[kind]["size"] += int(torrent.get("size") or 0)
        name = str(torrent.get("category") or "")
        categories.setdefault(name, {"seeding": 0, "stopped": 0})[kind] += 1
        if kind == "seeding":
            longest = max(longest, int(torrent.get("seeding_time") or 0))
    ranked = sorted(categories.items(), key=lambda item: -(item[1]["seeding"] + item[1]["stopped"]))
    return {
        **groups,
        "longest_seeding_days": round(longest / 86400, 1),
        "categories": [{"name": name, **counts} for name, counts in ranked[:TOP_CATEGORIES]],
    }


def status(
    service: Service, user: str, password: str, transport: Transport | None
) -> dict[str, Any]:
    """Seeding limits and what the finished torrents are doing."""

    def get(path: str, **options: Any) -> Any:
        return qbit_request(service, user, password, transport, "GET", path, **options).json()

    preferences = get("/api/v2/app/preferences") or {}
    torrents = get("/api/v2/torrents/info", params={"filter": "completed"}) or []
    found = limits(preferences)
    return {
        "limits": found,
        # With no limit nothing ever stops, so Sonarr and Radarr never remove anything.
        "unlimited": found["ratio"] is None
        and found["days"] is None
        and found["inactive_days"] is None,
        **summary(torrents if isinstance(torrents, list) else []),
    }


def validated(ratio: float | None, days: float | None) -> tuple[float | None, float | None]:
    if ratio is not None and not 0 < ratio <= MAX_RATIO:
        raise SeedingError(f"the ratio must be above 0 and at most {MAX_RATIO:g}")
    if days is not None and not 0 < days <= MAX_DAYS:
        raise SeedingError(f"the number of days must be above 0 and at most {MAX_DAYS:g}")
    return ratio, days


def set_limits(
    service: Service,
    user: str,
    password: str,
    transport: Transport | None,
    *,
    ratio: float | None,
    days: float | None,
) -> dict[str, Any]:
    """Set the global ratio and time limits (``None`` turns one off); torrents stop when reached."""
    ratio, days = validated(ratio, days)
    changes: dict[str, Any] = {
        "max_ratio_enabled": ratio is not None,
        "max_seeding_time_enabled": days is not None,
        "max_ratio_act": STOP,
    }
    if ratio is not None:
        changes["max_ratio"] = ratio
    if days is not None:
        changes["max_seeding_time"] = round(days * MINUTES_PER_DAY)
    qbit_request(
        service,
        user,
        password,
        transport,
        "POST",
        "/api/v2/app/setPreferences",
        form={"json": json.dumps(changes)},
    )
    return changes
