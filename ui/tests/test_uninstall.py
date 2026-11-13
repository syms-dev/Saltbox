"""Uninstalling an app: containers go, settings only on request, nothing else breaks."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from saltbox_ui import uninstall
from saltbox_ui.daemon import Services, create_app
from saltbox_ui.daemon import routes as daemon_routes
from saltbox_ui.layout import Layout


def container(name: str, network: str = "saltbox", depends_on: str = "") -> dict:
    return {
        "name": name,
        "status": "running",
        "health": None,
        "managed": True,
        "image_ref": f"example/{name}:latest",
        "network_mode": network,
        "urls": [],
        "labels": {"com.github.saltbox.depends_on": depends_on} if depends_on else {},
    }


CONTAINERS = [
    container("lidarr"),
    container("gluetun"),
    container("qbittorrent", network="container:gluetun"),
    container("traefik"),
    container("authelia", depends_on="authelia-redis"),
    container("authelia-redis"),
    container("petio", depends_on="petio-mongo"),
    container("petio-mongo"),
]


def test_dependents_names_what_would_break() -> None:
    assert uninstall.dependents({"lidarr"}, CONTAINERS) == []
    assert uninstall.dependents({"gluetun"}, CONTAINERS) == [
        "qbittorrent runs inside gluetun's network"
    ]
    assert uninstall.dependents({"authelia-redis"}, CONTAINERS) == [
        "authelia needs authelia-redis to start"
    ]
    # Removing an app together with what it brought along breaks nothing.
    assert uninstall.dependents({"petio", "petio-mongo"}, CONTAINERS) == []


def test_only_a_plain_folder_directly_under_appdata_can_be_deleted(tmp_path: Path) -> None:
    appdata = tmp_path / "opt"
    (appdata / "lidarr").mkdir(parents=True)
    (appdata / "lidarr" / "config.xml").write_text("<Config/>")
    outside = tmp_path / "precious"
    outside.mkdir()
    (appdata / "linked").symlink_to(outside)
    (appdata / "file").write_text("not a folder")
    assert uninstall.data_folder(appdata, "lidarr") == appdata / "lidarr"
    for name in ("linked", "file", "missing", "..", ".", "", "../precious", "lidarr/..", "a b"):
        assert uninstall.data_folder(appdata, name) is None, name
        with pytest.raises(uninstall.UninstallError):
            uninstall.delete_folder(appdata, name)
    assert outside.is_dir() and (appdata / "lidarr" / "config.xml").exists()
    assert uninstall.delete_folder(appdata, "lidarr") == appdata / "lidarr"
    assert not (appdata / "lidarr").exists() and outside.is_dir()


@pytest.fixture
def box(scratch_layout: Layout, fake_sb: Path, monkeypatch: pytest.MonkeyPatch):
    running = [dict(c) for c in CONTAINERS]
    removed: list[str] = []

    def remove(name: str, runner=None) -> None:
        removed.append(name)
        running[:] = [c for c in running if c["name"] != name]

    monkeypatch.setattr(daemon_routes, "_containers_or_none", lambda: [dict(c) for c in running])
    monkeypatch.setattr(uninstall, "remove_container", remove)
    for name in ("lidarr", "gluetun", "traefik", "authelia", "petio"):
        (scratch_layout.appdata / name).mkdir(parents=True)
    (scratch_layout.appdata / "lidarr" / "lidarr.db").write_text("data")
    services = Services(scratch_layout)
    monkeypatch.setattr(services.updates, "refresh", lambda **_: False)
    return TestClient(create_app(services=services)), scratch_layout, removed


def test_uninstall_keeps_settings_unless_told_otherwise(box) -> None:
    client, layout, removed = box
    plan = client.get("/api/apps/saltbox/lidarr/uninstall").json()
    assert plan == {
        "containers": ["lidarr"],
        "folders": [str(layout.appdata / "lidarr")],
        "instances": ["lidarr"],
        "blockers": [],
    }
    done = client.post("/api/apps/saltbox/lidarr/uninstall", json={}).json()
    assert done == {"removed": ["lidarr"], "deleted": [], "kept": [str(layout.appdata / "lidarr")]}
    assert removed == ["lidarr"] and (layout.appdata / "lidarr" / "lidarr.db").exists()
    apps = {a["role"]: a for a in client.get("/api/apps").json()}
    assert apps["lidarr"]["containers"] == [] and apps["lidarr"]["installed"] is True

    # A second pass, with the settings: the app is then gone from the installed list.
    again = client.post("/api/apps/saltbox/lidarr/uninstall", json={"delete_data": True}).json()
    assert again == {"removed": [], "deleted": [str(layout.appdata / "lidarr")], "kept": []}
    assert not (layout.appdata / "lidarr").exists()
    apps = {a["role"]: a for a in client.get("/api/apps").json()}
    assert apps["lidarr"]["installed"] is False
    assert client.post("/api/apps/saltbox/lidarr/uninstall", json={}).status_code == 409


def test_uninstall_refuses_what_other_things_need(box) -> None:
    client, layout, removed = box
    gluetun = client.post("/api/apps/saltbox/gluetun/uninstall", json={"delete_data": True})
    assert gluetun.status_code == 409
    assert "qbittorrent runs inside gluetun's network" in gluetun.json()["detail"]
    for role in ("traefik", "authelia"):
        refused = client.post(f"/api/apps/saltbox/{role}/uninstall", json={})
        assert refused.status_code == 409 and "part of Saltbox itself" in refused.json()["detail"]
    assert client.post("/api/apps/saltbox/nope/uninstall", json={}).status_code == 404
    assert removed == [] and (layout.appdata / "gluetun").is_dir()
