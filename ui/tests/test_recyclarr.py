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
