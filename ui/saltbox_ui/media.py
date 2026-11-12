"""Media at a glance: the VPN, downloads, what is playing and what is coming up.

Each section is read from the app's own API with the same discovery app setup
uses (addresses, API keys, the accounts.yml login, the Plex token) and fails on
its own: a stopped SABnzbd shows as an error in its section, not an empty page.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

from .appsetup.discover import Discovery, Service
from .appsetup.http import Client, Response, SetupError, Transport
from .appsetup.tasks import SabClient, session_cookie
from .appsetup.vpnport import docker_cat, forwarded_port

ContainerReader = Callable[[str, str], str]
PUBLIC_IP_FILE = "/tmp/gluetun/ip"
UPCOMING_DAYS = 7
UPCOMING_LIMIT = 12
TORRENT_LIMIT = 5

_QBIT_COOKIES: dict[str, tuple[float, str]] = {}
COOKIE_TTL_SECONDS = 1800


def _section(read: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return {"available": True, **read()}
    except SetupError as error:
        return {"available": False, "error": str(error)}
    except Exception as error:  # an app answering oddly must not take the page down
        return {"available": False, "error": f"{type(error).__name__}: {error}"}


# -- VPN ----------------------------------------------------------------------------------
def vpn_status(
    found: Discovery,
    containers: list[dict[str, Any]],
    *,
    read_file: ContainerReader = docker_cat,
    read_log: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Gluetun's state, public address and forwarded port, and who is routed through it."""
    by_name = {c["name"]: c for c in containers}
    gluetun = found.qbit_vpn or ("gluetun" if "gluetun" in by_name else "")
    if not gluetun or gluetun not in by_name:
        return {"configured": False}
    record = by_name[gluetun]
    running = record.get("status") == "running"
    routed = sorted(
        c["name"] for c in containers if str(c.get("network_mode", "")) == f"container:{gluetun}"
    )
    public_ip = ""
    if running:
        raw = read_file(gluetun, PUBLIC_IP_FILE).strip()
        try:
            parsed = json.loads(raw) if raw.startswith("{") else {"public_ip": raw}
        except ValueError:
            parsed = {}
        public_ip = str(parsed.get("public_ip") or "")
    port = forwarded_port(gluetun, read_file, read_log) if running else None
    qbit = by_name.get("qbittorrent")
    qbit_protected = qbit is None or str(qbit.get("network_mode", "")) == f"container:{gluetun}"
    return {
        "configured": True,
        "container": gluetun,
        "running": running,
        "health": record.get("health"),
        "public_ip": public_ip,
        "forwarded_port": port,
        "routed": routed,
        "qbittorrent_protected": qbit_protected,
    }


# -- downloads -----------------------------------------------------------------
def qbit_request(
    service: Service,
    user: str,
    password: str,
    transport: Transport | None,
    method: str,
    path: str,
    **options: Any,
) -> Response:
    """One call to qBittorrent's API as the accounts.yml user, logging in when needed."""
    client = Client(service.host_url, transport=transport, name=service.name)
    headers = {"Cookie": _qbit_cookie(client, service, user, password), "Referer": service.host_url}
    response = client.request(method, path, headers=headers, ok=(200, 403), **options)
    if response.status == 403:  # the session expired: log in again once
        _QBIT_COOKIES.pop(service.host_url, None)
        headers["Cookie"] = _qbit_cookie(client, service, user, password)
        response = client.request(method, path, headers=headers, **options)
    return response


def qbittorrent(
    service: Service, user: str, password: str, transport: Transport | None
) -> dict[str, Any]:
    def call(path: str, **options: Any) -> Any:
        return qbit_request(service, user, password, transport, "GET", path, **options).json()

    transfer = call("/api/v2/transfer/info") or {}
    torrents = (
        call(
            "/api/v2/torrents/info",
            params={"filter": "downloading", "sort": "progress", "reverse": "true"},
        )
        or []
    )
    return {
        "download_speed": int(transfer.get("dl_info_speed") or 0),
        "upload_speed": int(transfer.get("up_info_speed") or 0),
        "downloading": len(torrents),
        "items": [
            {
                "name": str(t.get("name", "")),
                "progress": round(float(t.get("progress") or 0) * 100, 1),
                "eta": int(t.get("eta") or 0) if int(t.get("eta") or 0) < 8_640_000 else None,
                "speed": int(t.get("dlspeed") or 0),
            }
            for t in torrents[:TORRENT_LIMIT]
        ],
    }


def _qbit_cookie(client: Client, service: Service, user: str, password: str) -> str:
    cached = _QBIT_COOKIES.get(service.host_url)
    if cached is not None and time.monotonic() - cached[0] < COOKIE_TTL_SECONDS:
        return cached[1]
    response = client.request(
        "POST",
        "/api/v2/auth/login",
        form={"username": user, "password": password},
        headers={"Referer": service.host_url},
        ok=(200, 204, 401, 403),
    )
    cookie = session_cookie(response.headers.get("set-cookie", ""))
    if response.status in (401, 403) or not cookie or response.text.strip() == "Fails.":
        raise SetupError(f"{service.name}: the accounts.yml login was refused")
    _QBIT_COOKIES[service.host_url] = (time.monotonic(), cookie)
    return cookie


def sabnzbd(service: Service, transport: Transport | None) -> dict[str, Any]:
    client = SabClient(service.host_url, service.api_key, transport=transport, name=service.name)
    queue = (
        client.request(
            "GET", "/api", params={"mode": "queue", "output": "json", "limit": str(TORRENT_LIMIT)}
        ).json()
        or {}
    ).get("queue") or {}
    return {
        "download_speed": int(float(queue.get("kbpersec") or 0) * 1024),
        "paused": bool(queue.get("paused")),
        "downloading": int(queue.get("noofslots") or 0),
        "time_left": str(queue.get("timeleft") or ""),
        "size_left": str(queue.get("sizeleft") or ""),
        "items": [
            {
                "name": str(slot.get("filename", "")),
                "progress": float(slot.get("percentage") or 0),
                "time_left": str(slot.get("timeleft") or ""),
            }
            for slot in (queue.get("slots") or [])[:TORRENT_LIMIT]
        ],
    }


# -- Plex ---------------------------------------------------------------------------------------
def plex_sessions(service: Service, token: str, transport: Transport | None) -> dict[str, Any]:
    if not token:
        raise SetupError("no Plex token yet; link your Plex account in the installer")
    client = Client(service.host_url, transport=transport, name=service.name)
    data = client.request(
        "GET", "/status/sessions", headers={"X-Plex-Token": token, "Accept": "application/json"}
    ).json()
    sessions = []
    for item in ((data or {}).get("MediaContainer") or {}).get("Metadata") or []:
        duration = int(item.get("duration") or 0)
        offset = int(item.get("viewOffset") or 0)
        transcode = item.get("TranscodeSession") or {}
        if item.get("type") == "episode":
            title = item.get("grandparentTitle", "")
            code = _episode_code(item.get("parentIndex"), item.get("index"))
            subtitle = f"{code} · {item.get('title', '')}"
        else:
            title = item.get("title", "")
            subtitle = str(item.get("year", "") or item.get("parentTitle", "") or "")
        sessions.append(
            {
                "title": str(title),
                "subtitle": str(subtitle),
                "type": str(item.get("type", "")),
                "user": str((item.get("User") or {}).get("title", "")),
                "player": str((item.get("Player") or {}).get("title", "")),
                "state": str((item.get("Player") or {}).get("state", "")),
                "progress": round(offset / duration * 100, 1) if duration else 0.0,
                "transcoding": str(transcode.get("videoDecision", "")) == "transcode",
            }
        )
    return {"sessions": sessions}


# -- upcoming ------------------------------------------------------------------
def upcoming(
    found: Discovery, transport: Transport | None, now: datetime | None = None
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    start, end = now.date().isoformat(), (now + timedelta(days=UPCOMING_DAYS)).date().isoformat()
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    for role, kind in (("sonarr", "episode"), ("radarr", "movie")):
        for service in found.installed(role):
            if not service.api_key:
                continue
            client = Client(
                f"{service.host_url}/api/v3",
                headers={"X-Api-Key": service.api_key},
                transport=transport,
                name=service.name,
            )
            params = {"start": start, "end": end, "unmonitored": "false"}
            if role == "sonarr":
                params["includeSeries"] = "true"
            try:
                entries = client.request("GET", "/calendar", params=params).json() or []
            except SetupError as error:
                errors.append(str(error))
                continue
            for entry in entries:
                items.append(_calendar_item(entry, kind, service.name))
    items.sort(key=lambda i: i["date"] or "9999")
    return {"items": items[:UPCOMING_LIMIT], "errors": errors}


def _episode_code(season: object, episode: object) -> str:
    return f"S{int(season or 0):02d}E{int(episode or 0):02d}"  # type: ignore[call-overload]


def _calendar_item(entry: dict[str, Any], kind: str, app: str) -> dict[str, Any]:
    if kind == "episode":
        series = entry.get("series") or {}
        return {
            "kind": kind,
            "app": app,
            "title": str(series.get("title", "")),
            "subtitle": _episode_code(entry.get("seasonNumber"), entry.get("episodeNumber"))
            + f" · {entry.get('title', '')}",
            "date": str(entry.get("airDateUtc") or entry.get("airDate") or ""),
            "downloaded": bool(entry.get("hasFile")),
        }
    dates = [entry.get(k) for k in ("digitalRelease", "physicalRelease", "inCinemas")]
    return {
        "kind": kind,
        "app": app,
        "title": str(entry.get("title", "")),
        "subtitle": str(entry.get("year", "")),
        "date": str(next((d for d in dates if d), "")),
        "downloaded": bool(entry.get("hasFile")),
    }


# -- everything ----------------------------------------------------------------
def media_snapshot(
    found: Discovery,
    containers: list[dict[str, Any]],
    *,
    transport: Transport | None = None,
    read_file: ContainerReader = docker_cat,
    read_log: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    qbit, sab, plex = found.first("qbittorrent"), found.first("sabnzbd"), found.first("plex")
    jobs: dict[str, Callable[[], dict[str, Any]]] = {
        "vpn": lambda: vpn_status(found, containers, read_file=read_file, read_log=read_log),
        "upcoming": lambda: upcoming(found, transport),
    }
    if qbit is not None:
        jobs["qbittorrent"] = lambda: qbittorrent(qbit, found.user, found.password, transport)
    if sab is not None and sab.api_key:
        jobs["sabnzbd"] = lambda: sabnzbd(sab, transport)
    if plex is not None:
        jobs["plex"] = lambda: plex_sessions(plex, found.plex_token, transport)
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {name: pool.submit(_section, job) for name, job in jobs.items()}
        result = {name: future.result() for name, future in futures.items()}
    result["checked_at"] = time.time()
    return result
