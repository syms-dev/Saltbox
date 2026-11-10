"""Media at a glance, against stand-ins for each app's API."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest

from saltbox_ui import media
from saltbox_ui.appsetup.discover import Discovery, Service
from saltbox_ui.appsetup.http import Response

NOW = datetime(2026, 11, 10, 12, tzinfo=UTC)


class Apps:
    """One fake transport for every app, with a qBittorrent session that can expire."""

    def __init__(self) -> None:
        self.logins = 0
        self.expired = False
        self.calls: list[str] = []

    def __call__(self, method, url, headers, body):
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        self.calls.append(f"{method} {parts.netloc}{parts.path}")
        if parts.path == "/api/v2/auth/login":
            self.logins += 1
            ok = b"password=pw" in (body or b"")
            return Response(
                204 if ok else 200,
                b"" if ok else b"Fails.",
                {"set-cookie": "SID=abc; HttpOnly"} if ok else {},
            )
        if parts.path.startswith("/api/v2/"):
            if headers.get("Cookie") != "SID=abc" or self.expired:
                self.expired = False
                return Response(403, b"Forbidden")
            if parts.path == "/api/v2/transfer/info":
                return _json({"dl_info_speed": 2_000_000, "up_info_speed": 50_000})
            return _json(
                [{"name": "Show.S01E01", "progress": 0.425, "eta": 120, "dlspeed": 1_000_000}]
            )
        if parts.netloc.startswith("sabnzbd"):
            assert query["apikey"] == ["sabkey"]
            return _json(
                {
                    "queue": {
                        "kbpersec": "1024",
                        "noofslots": 1,
                        "timeleft": "0:05:00",
                        "sizeleft": "300 MB",
                        "paused": False,
                        "slots": [
                            {"filename": "Movie.2024", "percentage": "60", "timeleft": "0:05:00"}
                        ],
                    }
                }
            )
        if parts.path == "/status/sessions":
            assert headers["X-Plex-Token"] == "plextoken"
            return _json(
                {
                    "MediaContainer": {
                        "Metadata": [
                            {
                                "type": "episode",
                                "grandparentTitle": "The Show",
                                "parentIndex": 2,
                                "index": 5,
                                "title": "Pilot",
                                "duration": 1000,
                                "viewOffset": 250,
                                "User": {"title": "seed"},
                                "Player": {"title": "Apple TV", "state": "playing"},
                                "TranscodeSession": {"videoDecision": "transcode"},
                            },
                            {
                                "type": "movie",
                                "title": "A Film",
                                "year": 2024,
                                "duration": 0,
                                "User": {"title": "guest"},
                                "Player": {"title": "Chrome", "state": "paused"},
                            },
                        ]
                    }
                }
            )
        if parts.path == "/api/v3/calendar":
            assert headers["X-Api-Key"] in {"sonarrkey", "radarrkey"}
            if parts.netloc.startswith("sonarr"):
                return _json(
                    [
                        {
                            "series": {"title": "The Show"},
                            "seasonNumber": 2,
                            "episodeNumber": 6,
                            "title": "Next",
                            "airDateUtc": "2026-11-12T02:00:00Z",
                            "hasFile": False,
                        }
                    ]
                )
            return _json(
                [
                    {
                        "title": "A Film",
                        "year": 2024,
                        "digitalRelease": "2026-11-11T00:00:00Z",
                        "hasFile": True,
                    }
                ]
            )
        return Response(404, b"")


def _json(data) -> Response:
    return Response(200, json.dumps(data).encode())


def service(role: str, port: int, key: str = "") -> Service:
    return Service(role, role, port, True, api_key=key, host=role)


@pytest.fixture
def found() -> Discovery:
    media._QBIT_COOKIES.clear()
    return Discovery(
        services={
            "qbittorrent": [service("qbittorrent", 8080)],
            "sabnzbd": [service("sabnzbd", 8080, "sabkey")],
            "plex": [service("plex", 32400)],
            "sonarr": [service("sonarr", 8989, "sonarrkey")],
            "radarr": [service("radarr", 7878, "radarrkey")],
        },
        user="seed",
        password="pw",
        plex_token="plextoken",
        qbit_vpn="gluetun",
    )


CONTAINERS = [
    {"name": "gluetun", "status": "running", "health": "healthy", "network_mode": "saltbox"},
    {
        "name": "qbittorrent",
        "status": "running",
        "health": None,
        "network_mode": "container:gluetun",
    },
]


def files(container: str, path: str) -> str:
    return {
        "/tmp/gluetun/ip": '{"public_ip":"185.98.171.144","country":"Canada"}',
        "/tmp/gluetun/forwarded_port": "51413",
    }.get(path, "")


def test_everything_at_once(found: Discovery) -> None:
    apps = Apps()
    snap = media.media_snapshot(found, CONTAINERS, transport=apps, read_file=files)
    assert snap["vpn"] == {
        "available": True,
        "configured": True,
        "container": "gluetun",
        "running": True,
        "health": "healthy",
        "public_ip": "185.98.171.144",
        "forwarded_port": 51413,
        "routed": ["qbittorrent"],
        "qbittorrent_protected": True,
    }
    assert snap["qbittorrent"]["download_speed"] == 2_000_000
    assert snap["qbittorrent"]["items"][0] == {
        "name": "Show.S01E01",
        "progress": 42.5,
        "eta": 120,
        "speed": 1_000_000,
    }
    assert (
        snap["sabnzbd"]["download_speed"] == 1024 * 1024
        and snap["sabnzbd"]["items"][0]["progress"] == 60.0
    )
    playing = snap["plex"]["sessions"]
    assert playing[0]["title"] == "The Show" and playing[0]["subtitle"] == "S02E05 · Pilot"
    assert playing[0]["progress"] == 25.0 and playing[0]["transcoding"] is True
    assert playing[1]["title"] == "A Film" and playing[1]["state"] == "paused"


def test_upcoming_merges_and_sorts(found: Discovery) -> None:
    result = media.upcoming(found, Apps(), now=NOW)
    assert [i["title"] for i in result["items"]] == ["A Film", "The Show"]
    assert result["items"][1]["subtitle"] == "S02E06 · Next"
    assert result["items"][0]["downloaded"] is True


def test_qbittorrent_logs_in_once_and_again_when_the_session_expires(found: Discovery) -> None:
    apps = Apps()
    qbit = found.first("qbittorrent")
    media.qbittorrent(qbit, "seed", "pw", apps)
    media.qbittorrent(qbit, "seed", "pw", apps)
    assert apps.logins == 1
    apps.expired = True
    media.qbittorrent(qbit, "seed", "pw", apps)
    assert apps.logins == 2


def test_each_section_fails_on_its_own(found: Discovery) -> None:
    found.password = "wrong"
    found.plex_token = ""
    snap = media.media_snapshot(found, CONTAINERS, transport=Apps(), read_file=files)
    assert snap["qbittorrent"] == {
        "available": False,
        "error": "qbittorrent: the accounts.yml login was refused",
    }
    assert "no Plex token" in snap["plex"]["error"]
    assert snap["sabnzbd"]["available"] is True


def test_vpn_warns_when_qbittorrent_is_outside_it(found: Discovery) -> None:
    containers = [CONTAINERS[0], {**CONTAINERS[1], "network_mode": "saltbox"}]
    status = media.vpn_status(found, containers, read_file=files)
    assert status["qbittorrent_protected"] is False and status["routed"] == []
    assert media.vpn_status(Discovery(), [], read_file=files) == {"configured": False}
