from __future__ import annotations

from pathlib import Path

import pytest

from saltbox_ui.appsetup import AppSetup, summarize
from saltbox_ui.appsetup.discover import discover, sabnzbd_api_key, xml_api_key
from saltbox_ui.config import ConfigService, Inventory
from saltbox_ui.layout import Layout
from saltbox_ui.plex import write_plex_facts
from tests.fake_apps import FakeArr, FakeNetwork, FakePlex, FakeQbit

KEYS = {"sonarr": "s" * 32, "radarr": "r" * 32, "lidarr": "l" * 32, "prowlarr": "p" * 32}


def install(layout: Layout, *apps: str) -> None:
    for app in apps:
        folder = layout.appdata / app
        folder.mkdir(parents=True, exist_ok=True)
        if app in KEYS:
            (folder / "config.xml").write_text(
                f"<Config>\n  <Port>1</Port>\n  <ApiKey>{KEYS[app]}</ApiKey>\n</Config>\n"
            )


@pytest.fixture
def box(scratch_layout: Layout):
    config = ConfigService(scratch_layout)
    config.ensure_exists("accounts")
    config.set("accounts", "user.name", "seed")
    config.set("accounts", "user.pass", "a-long-password-123")
    install(
        scratch_layout,
        "sonarr",
        "radarr",
        "lidarr",
        "prowlarr",
        "qbittorrent",
        "autoscan",
        "plex",
        "bazarr",
        "seerr",
    )
    write_plex_facts(scratch_layout, instance="plex", client_id="Saltboxabc", token="plex-token")
    net = FakeNetwork()
    apps = {role: net.add(role, FakeArr(role, key)) for role, key in KEYS.items()}
    apps["qbittorrent"] = net.add("qbittorrent", FakeQbit("seed", "a-long-password-123"))
    apps["plex"] = net.add("plex", FakePlex("plex-token"))
    made: list[Path] = []
    setup = AppSetup(
        scratch_layout, transport=net, resolver=lambda name: name, ensure_dir=made.append
    )
    return setup, apps, net, made


def by_id(tasks):
    return {task.id: task for task in tasks}


def test_discovery_reads_keys_ports_and_login(scratch_layout: Layout) -> None:
    install(scratch_layout, "sonarr", "qbittorrent")
    config = ConfigService(scratch_layout)
    config.ensure_exists("accounts")
    config.set("accounts", "user.pass", "pw-123456789012")
    Inventory(scratch_layout.inventory).update({"sonarr_role_web_port": "18989"})
    found = discover(scratch_layout)
    sonarr = found.first("sonarr")
    assert sonarr.api_key == KEYS["sonarr"]
    assert sonarr.port == 18989
    assert sonarr.url == "http://sonarr:18989"
    assert found.first("radarr") is None
    assert found.first("qbittorrent").api_key == ""
    assert found.password == "pw-123456789012"


def test_key_readers(tmp_path: Path) -> None:
    xml = tmp_path / "config.xml"
    xml.write_text("<Config><ApiKey> abc123 </ApiKey></Config>")
    assert xml_api_key(xml) == "abc123"
    assert xml_api_key(tmp_path / "missing.xml") == ""
    ini = tmp_path / "sabnzbd.ini"
    ini.write_text("__version__ = 19\n[misc]\nhost = ::\napi_key = sabkey\n")
    assert sabnzbd_api_key(ini) == "sabkey"


def test_status_before_setup(box) -> None:
    setup, *_ = box
    tasks = setup.status()
    counts = summarize(tasks)
    assert counts["error"] == 0
    assert counts["done"] == 0
    assert counts["manual"] == 2  # Bazarr and Seerr
    ids = set(by_id(tasks))
    assert {
        "qbittorrent:folders",
        "sonarr:rootfolder",
        "sonarr:qbittorrent",
        "sonarr:autoscan",
        "prowlarr:sonarr",
        "prowlarr:radarr",
        "prowlarr:lidarr",
        "prowlarr:qbittorrent",
        "plex:radarr",
        "plex:sonarr",
        "plex:lidarr",
    } <= ids
    seerr = by_id(tasks)["seerr"]
    assert KEYS["radarr"] in seerr.detail and "plex, port 32400" in seerr.detail
    assert "a-long-password" not in " ".join(t.detail for t in tasks)


def test_apply_connects_everything(box) -> None:
    setup, apps, _net, made = box
    tasks = setup.apply()
    errors = [(t.id, t.detail) for t in tasks if t.status == "error"]
    assert errors == []
    assert summarize(tasks)["todo"] == 0

    assert apps["qbittorrent"].preferences["save_path"].endswith("/qbittorrent/completed/")
    assert apps["qbittorrent"].preferences["temp_path_enabled"] is True
    assert Path("/mnt/unionfs/downloads/torrents/qbittorrent/incoming") in made
    assert Path("/mnt/unionfs/Media/Music") in made

    sonarr = apps["sonarr"]
    assert [f["path"] for f in sonarr.rootfolders] == ["/mnt/unionfs/Media/TV"]
    client = sonarr.downloadclients[0]
    values = {f["name"]: f["value"] for f in client["fields"]}
    assert values["host"] == "qbittorrent" and values["port"] == 8080
    assert values["username"] == "seed" and values["password"] == "a-long-password-123"
    assert values["tvCategory"] == "sonarr"
    assert values["tvImportedCategory"] is None
    hook = sonarr.notifications[0]
    hook_values = {f["name"]: f["value"] for f in hook["fields"]}
    assert hook_values["url"] == "http://autoscan:3030/triggers/sonarr"
    assert hook_values["method"] == 1
    assert hook["onDownload"] and hook["onUpgrade"] and hook["onEpisodeFileDelete"]
    assert not hook["onGrab"] and not hook["onHealthIssue"]

    lidarr_root = apps["lidarr"].rootfolders[0]
    assert lidarr_root["defaultQualityProfileId"] == 4
    assert lidarr_root["defaultMetadataProfileId"] == 7
    assert {f["name"]: f["value"] for f in apps["lidarr"].downloadclients[0]["fields"]}[
        "musicCategory"
    ] == "lidarr"

    linked = {
        item["implementation"]: {f["name"]: f["value"] for f in item["fields"]}
        for item in apps["prowlarr"].applications
    }
    assert linked["Sonarr"]["baseUrl"] == "http://sonarr:8989"
    assert linked["Sonarr"]["prowlarrUrl"] == "http://prowlarr:9696"
    assert linked["Radarr"]["apiKey"] == KEYS["radarr"]
    assert apps["prowlarr"].applications[0]["syncLevel"] == "fullSync"
    prowlarr_client = {f["name"]: f["value"] for f in apps["prowlarr"].downloadclients[0]["fields"]}
    assert prowlarr_client["category"] == "prowlarr"

    plex = apps["plex"]
    assert sorted(s["title"] for s in plex.sections) == ["Movies", "Music", "TV Shows"]
    movies = next(s for s in plex.sections if s["title"] == "Movies")
    assert movies["agent"] == "tv.plex.agents.movie"
    assert movies["Location"][0]["path"] == "/mnt/unionfs/Media/Movies"
    assert sorted(plex.refreshed) == ["1", "2", "3"]


def test_apply_twice_changes_nothing(box) -> None:
    setup, apps, *_ = box
    setup.apply()
    tasks = setup.apply()
    assert summarize(tasks)["todo"] == 0
    assert len(apps["sonarr"].rootfolders) == 1
    assert len(apps["sonarr"].downloadclients) == 1
    assert len(apps["sonarr"].notifications) == 1
    assert len(apps["prowlarr"].applications) == 3
    assert len(apps["plex"].sections) == 3


def test_failures_are_reported_per_task(box) -> None:
    setup, apps, net, _ = box
    apps["qbittorrent"].password = "changed-in-the-ui"
    net.down.add("radarr")
    tasks = by_id(setup.apply())
    assert tasks["qbittorrent:folders"].status == "error"
    assert "login refused" in tasks["qbittorrent:folders"].detail
    assert tasks["radarr:rootfolder"].status == "error"
    assert "cannot reach radarr:7878" in tasks["radarr:rootfolder"].detail
    assert tasks["sonarr:rootfolder"].status == "done"
    assert tasks["plex:sonarr"].status == "done"


def test_missing_api_key_and_sabnzbd(box, scratch_layout: Layout) -> None:
    setup, apps, _net, _ = box
    (scratch_layout.appdata / "lidarr" / "config.xml").write_text("<Config></Config>")
    install(scratch_layout, "sabnzbd")
    (scratch_layout.appdata / "sabnzbd" / "sabnzbd.ini").write_text("[misc]\napi_key = sabkey\n")
    tasks = by_id(setup.apply())
    assert tasks["lidarr:apikey"].status == "manual"
    assert "prowlarr:lidarr" not in tasks
    sab = next(c for c in apps["sonarr"].downloadclients if c["implementation"] == "Sabnzbd")
    sab_values = {f["name"]: f["value"] for f in sab["fields"]}
    assert sab_values["apiKey"] == "sabkey" and sab_values["tvCategory"] == "sonarr"


def test_extra_instances_need_their_own_root_folder(box, scratch_layout: Layout) -> None:
    setup, _apps, net, _ = box
    Inventory(scratch_layout.inventory).update({"sonarr_instances": ["sonarr", "sonarr4k"]})
    install(scratch_layout, "sonarr4k")
    (scratch_layout.appdata / "sonarr4k" / "config.xml").write_text(
        "<Config><ApiKey>k4k</ApiKey></Config>"
    )
    net.add("sonarr4k", FakeArr("sonarr", "k4k"))
    tasks = by_id(setup.apply())
    assert tasks["sonarr4k:rootfolder"].status == "manual"
    assert tasks["sonarr4k:autoscan"].status == "done"
    hook = net.apps["sonarr4k"].notifications[0]
    assert {f["name"]: f["value"] for f in hook["fields"]}["url"].endswith("/triggers/sonarr4k")


def test_without_plex_token_libraries_are_manual(box, scratch_layout: Layout) -> None:
    setup, *_ = box
    (scratch_layout.appdata / "saltbox" / "plex.ini").unlink()
    tasks = by_id(setup.status())
    assert tasks["plex:sonarr"].status == "manual"


# -- faces -------------------------------------------------------------------
async def test_setup_screen_connects_everything(box) -> None:
    from textual.widgets import Button, Static

    from saltbox_ui.tui.setup_screen import SetupApp
    from saltbox_ui.tui.widgets import CheckRow

    setup, apps, *_ = box
    app = SetupApp(setup)
    async with app.run_test(size=(120, 60)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        rows = {row.check_id: row for row in app.screen.query(CheckRow)}
        assert rows["sonarr:rootfolder"].status == "todo"
        assert rows["bazarr"].status == "manual"
        summary = str(app.screen.query_one("#setup-summary", Static).content)
        assert "to connect" in summary and "by hand" in summary
        assert not app.screen.query_one("#setup_apply", Button).disabled

        await pilot.click("#setup_apply")
        await pilot.pause(0.3)
        await app.workers.wait_for_complete()
        await pilot.pause()
        rows = {row.check_id: row for row in app.screen.query(CheckRow)}
        assert rows["sonarr:rootfolder"].status == "done"
        assert rows["plex:radarr"].status == "done"
        summary = str(app.screen.query_one("#setup-summary", Static).content)
        assert "to connect" not in summary and "failed" not in summary
        assert app.screen.query_one("#setup_apply", Button).disabled  # nothing left
        await pilot.click("#setup_close")
        await pilot.pause()
    assert apps["sonarr"].rootfolders


async def test_done_screen_opens_setup(box, scratch_layout: Layout, fake_sb) -> None:
    from saltbox_ui.installer import InstallerSession
    from saltbox_ui.installer.plan import InstallPlan
    from saltbox_ui.tui.app import STEPS, InstallerApp
    from saltbox_ui.tui.installer.screens import DoneScreen
    from saltbox_ui.tui.setup_screen import SetupScreen

    setup, *_ = box
    session = InstallerSession(
        scratch_layout, plan=InstallPlan(phase="done", user_name="seed", domain="example.com")
    )
    app = InstallerApp(session, app_setup_factory=lambda layout: setup)
    async with app.run_test(size=(120, 60)) as pilot:
        app.show_step(STEPS.index(DoneScreen))
        await pilot.pause()
        await pilot.click("#connect_apps")
        await pilot.pause()
        assert isinstance(app.screen, SetupScreen)
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.click("#setup_close")
        await pilot.pause()
        assert isinstance(app.screen, DoneScreen)


def test_daemon_setup_routes(box, scratch_layout: Layout) -> None:
    from fastapi.testclient import TestClient

    from saltbox_ui.daemon import Services, create_app

    setup, apps, *_ = box
    client = TestClient(
        create_app(services=Services(scratch_layout, app_setup_factory=lambda layout: setup))
    )
    status = client.get("/api/setup").json()
    assert status["summary"]["todo"] > 0
    assert all("password" not in t["detail"] for t in status["tasks"])
    applied = client.post("/api/setup/apply").json()
    assert applied["summary"]["todo"] == 0 and applied["summary"]["error"] == 0
    assert apps["prowlarr"].applications


def test_sbx_setup(box, env_layout: Layout, monkeypatch, capsys) -> None:
    import json

    import saltbox_ui.appsetup as appsetup
    from saltbox_ui.cli import main

    setup, *_ = box
    monkeypatch.setattr(appsetup, "AppSetup", lambda layout: setup)
    assert main(["setup", "apply"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["error"] == 0
    assert main(["setup", "status"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["todo"] == 0
