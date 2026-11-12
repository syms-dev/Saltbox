"""Seeding limits and finished torrents in qBittorrent."""

import json
import urllib.parse
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from saltbox_ui import media, seeding
from saltbox_ui.appsetup.discover import Discovery, Service
from saltbox_ui.appsetup.http import Response
from saltbox_ui.daemon import Services, create_app
from saltbox_ui.layout import Layout

GIB = 1024**3


def torrent(state: str, size: float, category: str = "sonarr", seeding_days: float = 0) -> dict:
    return {
        "state": state,
        "size": int(size * GIB),
        "category": category,
        "seeding_time": int(seeding_days * 86400),
        "ratio": 1.0,
    }


TORRENTS = [
    torrent("uploading", 4, "sonarr", 3),
    torrent("stalledUP", 10, "radarr", 40),
    torrent("forcedUP", 1, "", 1),
    torrent("queuedUP", 2, "sonarr", 2),
    torrent("stoppedUP", 8, "sonarr"),  # qBittorrent 5
    torrent("pausedUP", 6, "manual"),  # qBittorrent 4
    torrent("downloading", 50, "sonarr"),  # not finished: not counted
    torrent("missingFiles", 5, "radarr"),
]


class Qbit:
    """qBittorrent's API as far as seeding goes; refuses a wrong password."""

    def __init__(self) -> None:
        self.preferences: dict = {"max_ratio_enabled": False, "max_ratio": -1, "max_ratio_act": 0}
        self.filters: list[str] = []

    def __call__(self, method: str, url: str, headers: dict, body: bytes | None) -> Response:
        parts = urllib.parse.urlsplit(url)
        if parts.path == "/api/v2/auth/login":
            ok = b"password=pw" in (body or b"")
            return Response(204 if ok else 401, b"", {"set-cookie": "SID=abc"} if ok else {})
        if parts.path == "/api/v2/app/preferences":
            return Response(200, json.dumps(self.preferences).encode())
        if parts.path == "/api/v2/app/setPreferences":
            form = dict(urllib.parse.parse_qsl((body or b"").decode()))
            self.preferences.update(json.loads(form["json"]))
            return Response(200, b"")
        if parts.path == "/api/v2/torrents/info":
            self.filters.append(dict(urllib.parse.parse_qsl(parts.query)).get("filter", ""))
            return Response(200, json.dumps(TORRENTS).encode())
        return Response(404, b"")


@pytest.fixture
def qbit() -> Qbit:
    media._QBIT_COOKIES.clear()
    return Qbit()


SERVICE = Service("qbittorrent", "qbittorrent", 8080, True, host="qbittorrent")


def test_limits_read_ratio_and_days_and_the_action() -> None:
    assert seeding.limits({}) == {
        "ratio": None,
        "days": None,
        "inactive_days": None,
        "action": "stop",
    }
    found = seeding.limits(
        {
            "max_ratio_enabled": True,
            "max_ratio": 2,
            "max_seeding_time_enabled": True,
            "max_seeding_time": 20160,
            "max_inactive_seeding_time_enabled": False,
            "max_inactive_seeding_time": 1440,
            "max_ratio_act": 3,
        }
    )
    assert found == {"ratio": 2.0, "days": 14.0, "inactive_days": None, "action": "remove_files"}
    # A limit that is switched on but holds qBittorrent's "none" value is no limit.
    assert seeding.limits({"max_ratio_enabled": True, "max_ratio": -1})["ratio"] is None


def test_summary_separates_seeding_from_stopped_and_ignores_unfinished() -> None:
    found = seeding.summary(TORRENTS)
    assert found["seeding"] == {"count": 4, "size": 17 * GIB}
    assert found["stopped"] == {"count": 2, "size": 14 * GIB}
    assert found["longest_seeding_days"] == 40.0
    assert found["categories"][0] == {"name": "sonarr", "seeding": 2, "stopped": 1}
    assert {"name": "", "seeding": 1, "stopped": 0} in found["categories"]


def test_status_says_when_nothing_will_ever_stop(qbit: Qbit) -> None:
    found = seeding.status(SERVICE, "seed", "pw", qbit)
    assert found["unlimited"] is True and found["seeding"]["count"] == 4
    assert qbit.filters == ["completed"]
    qbit.preferences.update(max_seeding_time_enabled=True, max_seeding_time=4320)
    found = seeding.status(SERVICE, "seed", "pw", qbit)
    assert found["unlimited"] is False and found["limits"]["days"] == 3.0


def test_set_limits_stops_rather_than_removes(qbit: Qbit) -> None:
    qbit.preferences["max_ratio_act"] = 1  # "remove": Sonarr and Radarr object to it
    seeding.set_limits(SERVICE, "seed", "pw", qbit, ratio=1.5, days=14)
    assert qbit.preferences == {
        "max_ratio_enabled": True,
        "max_ratio": 1.5,
        "max_seeding_time_enabled": True,
        "max_seeding_time": 20160,
        "max_ratio_act": 0,
    }
    # Turning one off leaves its old number alone and only clears the switch.
    seeding.set_limits(SERVICE, "seed", "pw", qbit, ratio=None, days=30)
    assert qbit.preferences["max_ratio_enabled"] is False and qbit.preferences["max_ratio"] == 1.5
    assert qbit.preferences["max_seeding_time"] == 43200


@pytest.mark.parametrize(
    "ratio, days", [(0, None), (-1, None), (101, None), (None, 0), (None, 4000)]
)
def test_set_limits_refuses_nonsense(qbit: Qbit, ratio, days) -> None:
    with pytest.raises(seeding.SeedingError):
        seeding.set_limits(SERVICE, "seed", "pw", qbit, ratio=ratio, days=days)
    assert "max_seeding_time" not in qbit.preferences


def client_for(layout: Layout, qbit: Qbit | None, password: str = "pw") -> TestClient:
    class Setup:
        transport = qbit

        def __init__(self, layout):
            pass

        def discover(self):
            services = {"qbittorrent": [SERVICE]} if qbit is not None else {}
            return Discovery(services=services, user="seed", password=password)

    services = Services(layout)
    services.app_setup_factory = Setup
    return TestClient(create_app(services=services))


def test_seeding_routes(scratch_layout: Layout, fake_sb: Path, qbit: Qbit) -> None:
    client = client_for(scratch_layout, qbit)
    before = client.get("/api/seeding").json()
    assert before["installed"] is True and before["error"] == ""
    assert before["unlimited"] is True and before["seeding"]["count"] == 4
    client.get("/api/seeding")
    assert len(qbit.filters) == 1  # the torrent list is read once a minute, not per page view
    assert client.put("/api/seeding", json={"ratio": 0}).status_code == 422
    assert client.put("/api/seeding", json={"ratio": "lots"}).status_code == 422
    after = client.put("/api/seeding", json={"ratio": 2, "days": 14}).json()
    assert after["limits"] == {"ratio": 2.0, "days": 14.0, "inactive_days": None, "action": "stop"}
    assert after["unlimited"] is False
    assert client.get("/api/seeding").json()["limits"]["ratio"] == 2.0
    cleared = client.put("/api/seeding", json={"ratio": None, "days": None}).json()
    assert cleared["unlimited"] is True


def test_seeding_routes_without_qbittorrent_or_with_a_refused_login(
    scratch_layout: Layout, fake_sb: Path, qbit: Qbit
) -> None:
    none = client_for(scratch_layout, None)
    assert none.get("/api/seeding").json() == {"installed": False, "error": "", "tools": []}
    assert none.put("/api/seeding", json={"ratio": 2}).status_code == 409
    refused = client_for(scratch_layout, qbit, password="wrong")
    status = refused.get("/api/seeding").json()
    assert status["installed"] is True and "login was refused" in status["error"]
    assert "limits" not in status
    assert refused.put("/api/seeding", json={"ratio": 2}).status_code == 502
    assert qbit.preferences["max_ratio_enabled"] is False
