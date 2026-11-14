from __future__ import annotations

import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from saltbox_ui import recyclarr
from saltbox_ui.appsetup.discover import Discovery, Service
from saltbox_ui.daemon import Services, create_app
from saltbox_ui.daemon import routes as daemon_routes
from saltbox_ui.layout import Layout

WEB_1080 = "72dae194fc92bf828f32cde7744e51a1"
HD_BLURAY = "d1d67249d3890e49bc12e275d989a7e9"
UHD_BLURAY = "64fb5f9858489bdac2af690e27c8f42f"


def found(*, radarr: bool = True) -> Discovery:
    services = {
        "sonarr": [Service("sonarr", "sonarr", 8989, True, api_key="sonarrkey0123456789")],
        "radarr": [Service("radarr", "radarr", 7878, radarr, api_key="radarrkey0123456789")],
    }
    return Discovery(services=services)


@pytest.fixture
def layout(scratch_layout: Layout) -> Layout:
    (scratch_layout.appdata / "recyclarr").mkdir(parents=True)
    return scratch_layout


def test_writes_config_and_secrets_for_each_instance(layout: Layout) -> None:
    result = recyclarr.write_config(
        layout, found(), {"sonarr": [WEB_1080], "radarr": [HD_BLURAY, UHD_BLURAY, "bogus"]}
    )
    config = (layout.appdata / "recyclarr" / "recyclarr.yml").read_text()
    assert config.startswith(recyclarr.MARKER)
    assert (
        "  sonarr:\n    base_url: !secret sonarr_url\n    api_key: !secret sonarr_apikey" in config
    )
    assert f"- trash_id: {WEB_1080}  # WEB-1080p" in config
    assert f"- trash_id: {UHD_BLURAY}  # UHD Bluray + WEB" in config
    assert "type: series" in config and "type: movie" in config
    assert "bogus" not in config and "sonarrkey" not in config
    secrets = layout.appdata / "recyclarr" / "secrets.yml"
    assert "sonarr_url: http://sonarr:8989" in secrets.read_text()
    assert 'radarr_apikey: "radarrkey0123456789"' in secrets.read_text()
    assert stat.S_IMODE(secrets.stat().st_mode) == 0o600
    assert result["backup"] is None and result["instances"]["radarr"] == ["radarr"]


def test_keeps_a_copy_of_a_hand_written_config(layout: Layout) -> None:
    config = layout.appdata / "recyclarr" / "recyclarr.yml"
    config.write_text("sonarr:\n  mine:\n    base_url: http://x\n")
    result = recyclarr.write_config(layout, found(), {"sonarr": [WEB_1080]})
    assert result["backup"] is not None
    assert Path(result["backup"]).read_text().startswith("sonarr:\n  mine:")
    # our own file is replaced without another copy
    assert recyclarr.write_config(layout, found(), {"sonarr": [WEB_1080]})["backup"] is None


def test_refuses_an_empty_choice_and_a_missing_install(layout: Layout, tmp_path: Path) -> None:
    with pytest.raises(recyclarr.RecyclarrError, match="choose at least one"):
        recyclarr.write_config(layout, found(), {"sonarr": [], "radarr": []})
    with pytest.raises(recyclarr.RecyclarrError, match="choose at least one"):
        recyclarr.write_config(layout, found(radarr=False), {"radarr": [HD_BLURAY]})
    other = Layout(repo=layout.repo, appdata=tmp_path / "empty", state_dir=tmp_path / "s")
    with pytest.raises(recyclarr.RecyclarrError, match="not installed"):
        recyclarr.write_config(other, found(), {"sonarr": [WEB_1080]})


def test_status_reads_the_current_selection(layout: Layout) -> None:
    recyclarr.write_config(layout, found(), {"sonarr": [WEB_1080], "radarr": [UHD_BLURAY]})
    info = recyclarr.status(layout, found(), {"recyclarr": {"status": "running"}})
    assert info["installed"] and info["running"] and info["managed"]
    assert info["selected"] == {"sonarr": [WEB_1080], "radarr": [UHD_BLURAY]}
    assert info["instances"] == {"sonarr": ["sonarr"], "radarr": ["radarr"]}
    assert [p["name"] for p in info["profiles"]["sonarr"]] == ["WEB-1080p", "WEB-2160p"]


def test_routes_save_and_sync(layout: Layout, fake_sb: Path, monkeypatch) -> None:
    class Setup:
        def __init__(self, layout):
            pass

        def discover(self):
            return found()

    services = Services(layout)
    services.app_setup_factory = Setup
    client = TestClient(create_app(services=services))
    monkeypatch.setattr(daemon_routes, "_containers_or_none", lambda: [])
    assert client.put("/api/recyclarr", json={"sonarr": []}).status_code == 400
    saved = client.put("/api/recyclarr", json={"sonarr": [WEB_1080]}).json()
    assert saved["status"]["selected"]["sonarr"] == [WEB_1080]
    assert client.post("/api/recyclarr/sync", json={}).status_code == 409  # not running
    monkeypatch.setattr(
        daemon_routes,
        "_containers_or_none",
        lambda: [{"name": "recyclarr", "status": "running", "managed": True, "health": None}],
    )
    job = client.post("/api/recyclarr/sync", json={"preview": True}).json()
    assert job["command"] == ["docker", "exec", "recyclarr", "recyclarr", "sync", "--preview"]
    assert job["kind"] == "recyclarr"
    # the general job endpoint cannot be used to run arbitrary commands
    assert client.post("/api/jobs", json={"kind": "recyclarr"}).status_code == 422


# -- are the synced profiles in use? ---------------------------------------------------------
class Arr:
    """Sonarr's or Radarr's quality profiles, library and mass editor."""

    def __init__(self, resource: str, ids_field: str, key: str):
        self.resource, self.ids_field, self.key = resource, ids_field, key
        self.profiles = [{"id": 1, "name": "Any"}, {"id": 4, "name": "HD-1080p"}]
        self.items = [{"id": n, "qualityProfileId": 4 if n < 5 else 1} for n in range(1, 8)]
        self.edits: list[dict] = []

    def __call__(self, method: str, url: str, headers: dict, body: bytes | None):
        import json as jsonlib
        from urllib.parse import urlsplit

        from saltbox_ui.appsetup.http import Response

        if headers.get("X-Api-Key") != self.key:
            return Response(401, b'{"error": "Unauthorized"}')
        path = urlsplit(url).path
        if (method, path) == ("GET", "/api/v3/qualityprofile"):
            return Response(200, jsonlib.dumps(self.profiles).encode())
        if (method, path) == ("GET", f"/api/v3/{self.resource}"):
            return Response(200, jsonlib.dumps(self.items).encode())
        if (method, path) == ("PUT", f"/api/v3/{self.resource}/editor"):
            edit = jsonlib.loads(body or b"{}")
            self.edits.append(edit)
            for item in self.items:
                if item["id"] in edit[self.ids_field]:
                    item["qualityProfileId"] = edit["qualityProfileId"]
            return Response(202, b"[]")
        return Response(404, b"{}")


SONARR = Service("sonarr", "sonarr", 8989, True, api_key="sonarrkey0123456789", host="sonarr")


def test_usage_shows_that_a_sync_alone_moves_nothing() -> None:
    sonarr = Arr("series", "seriesIds", "sonarrkey0123456789")
    before = recyclarr.usage(SONARR, ["WEB-1080p"], sonarr)
    assert before["total"] == 7 and before["noun"] == "series"
    assert before["missing"] == ["WEB-1080p"]  # asked for, not in Sonarr: not synced yet
    assert [(p["name"], p["count"], p["synced"]) for p in before["profiles"]] == [
        ("HD-1080p", 4, False),
        ("Any", 3, False),
    ]
    sonarr.profiles.append({"id": 9, "name": "WEB-1080p"})  # what the sync creates
    after = recyclarr.usage(SONARR, ["WEB-1080p"], sonarr)
    assert after["missing"] == []
    assert after["profiles"][0] == {"id": 9, "name": "WEB-1080p", "count": 0, "synced": True}


def test_assign_moves_only_what_is_on_another_profile() -> None:
    sonarr = Arr("series", "seriesIds", "sonarrkey0123456789")
    sonarr.profiles.append({"id": 9, "name": "WEB-1080p"})
    sonarr.items[0]["qualityProfileId"] = 9
    result = recyclarr.assign(SONARR, 9, sonarr)
    assert result == {"moved": 6, "total": 7, "profile": "WEB-1080p"}
    assert sonarr.edits == [{"seriesIds": [2, 3, 4, 5, 6, 7], "qualityProfileId": 9}]
    assert recyclarr.assign(SONARR, 9, sonarr)["moved"] == 0 and len(sonarr.edits) == 1
    with pytest.raises(recyclarr.RecyclarrError, match="no quality profile 77"):
        recyclarr.assign(SONARR, 77, sonarr)

    radarr = Arr("movie", "movieIds", "radarrkey0123456789")
    service = Service("radarr", "radarr", 7878, True, api_key="radarrkey0123456789", host="radarr")
    recyclarr.assign(service, 1, radarr)
    assert radarr.edits == [{"movieIds": [1, 2, 3, 4], "qualityProfileId": 1}]


def test_usage_and_assign_routes(layout: Layout, monkeypatch: pytest.MonkeyPatch) -> None:
    sonarr = Arr("series", "seriesIds", "sonarrkey0123456789")
    sonarr.profiles.append({"id": 9, "name": "WEB-1080p"})

    def transport(method: str, url: str, headers: dict, body: bytes | None):
        from saltbox_ui.appsetup.http import Response

        if "sonarr" in url:
            return sonarr(method, url, headers, body)
        return Response(503, b"starting")  # Radarr is not answering

    class Setup:
        def __init__(self, layout):
            self.transport = transport

        def discover(self):
            known = found()
            for services in known.services.values():
                for service in services:
                    service.host = service.name
            return known

    services = Services(layout)
    services.app_setup_factory = Setup
    client = TestClient(create_app(services=services))
    monkeypatch.setattr(daemon_routes, "_containers_or_none", lambda: [])
    # Read once before anything is chosen: no profile counts as synced yet.
    early = client.get("/api/recyclarr/usage").json()["instances"][0]
    assert not any(profile["synced"] for profile in early["profiles"]) and early["missing"] == []
    client.put("/api/recyclarr", json={"sonarr": [WEB_1080], "radarr": [HD_BLURAY]})

    # Saving the choice is seen at once, not after the cached answer runs out.
    data = client.get("/api/recyclarr/usage").json()
    first, second = data["instances"]
    assert first["name"] == "sonarr" and first["missing"] == []
    assert first["profiles"][0] == {"id": 9, "name": "WEB-1080p", "count": 0, "synced": True}
    assert second["name"] == "radarr" and second["error"]  # stopped: said so, not a failure

    moved = client.post("/api/recyclarr/assign", json={"instance": "sonarr", "profile_id": 9})
    assert moved.json()["moved"] == 7 and moved.json()["profile"] == "WEB-1080p"
    assert moved.json()["usage"]["instances"][0]["profiles"][0]["count"] == 7
    assert (
        client.post(
            "/api/recyclarr/assign", json={"instance": "sonarr", "profile_id": 77}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/recyclarr/assign", json={"instance": "lidarr", "profile_id": 1}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/recyclarr/assign", json={"instance": "radarr", "profile_id": 1}
        ).status_code
        == 502
    )
