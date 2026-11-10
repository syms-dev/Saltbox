from __future__ import annotations

import stat
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from saltbox_ui.daemon import Services, create_app
from saltbox_ui.daemon import routes as daemon_routes
from saltbox_ui.daemon.automation import AutomationService, Notifier
from saltbox_ui.daemon.updates import UpdateService
from saltbox_ui.layout import Layout
from saltbox_ui.secrets import HIDDEN
from saltbox_ui.state.updates import ImageStatus


class FakeApprise:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.argv: list[list[str]] = []

    def __call__(self, args: list[str]) -> tuple[int, str]:
        self.argv.append(args)
        url = Path(args[args.index("--config") + 1]).read_text().strip()
        self.sent.append((url, args[args.index("-t") + 1], args[args.index("-b") + 1]))
        return 0, ""


def container(name: str, status: str = "running", health: str | None = None, mode: str = "saltbox"):
    return {"name": name, "status": status, "health": health, "managed": True, "network_mode": mode}


@pytest.fixture
def setup(scratch_layout: Layout, fake_sb: Path):
    svc = Services(scratch_layout)
    apprise = FakeApprise()
    state = {"containers": [container("sonarr"), container("gluetun")], "disks": []}
    svc.automation = AutomationService(
        svc,
        notifier=Notifier(scratch_layout.state_dir / "tmp", runner=apprise, binary="/bin/apprise"),
        containers=lambda: state["containers"],
        disks=lambda: state["disks"],
        sleep=lambda s: None,
    )
    svc.automation.save({"alerts": {"enabled": True, "url": "ntfy://topic-secret"}})
    return svc, apprise, state


def test_settings_defaults_validation_and_privacy(setup) -> None:
    svc, _, _ = setup
    settings = svc.automation.settings()
    assert settings["alerts"]["events"]["job_failed"] is True
    assert settings["maintenance"] == {
        "enabled": False,
        "time": "04:00",
        "saltbox": False,
        "exclude": [],
    }
    with pytest.raises(ValueError, match="04:00"):
        svc.automation.save({"maintenance": {"time": "4am"}})
    assert stat.S_IMODE(svc.automation.settings_path.stat().st_mode) == 0o600


def test_alert_url_stays_off_the_command_line_and_falls_back_to_accounts(setup) -> None:
    svc, apprise, _ = setup
    assert svc.automation.alert("job_failed", "Job failed", "details")
    assert apprise.sent == [("ntfy://topic-secret", "Job failed", "details")]
    assert not any("topic-secret" in arg for arg in apprise.argv[0])
    assert list((svc.layout.state_dir / "tmp").iterdir()) == []  # the config file is gone
    svc.automation.save({"alerts": {"url": ""}})
    svc.layout.config_file("accounts").write_text("---\napprise: tgram://bot/chat\n")
    assert svc.automation.apprise_url() == "tgram://bot/chat"


def test_events_can_be_switched_off_and_repeats_wait_an_hour(setup) -> None:
    svc, apprise, _ = setup
    svc.automation.save({"alerts": {"events": {"disk": False}}})
    assert not svc.automation.alert("disk", "full", "x")
    assert svc.automation.alert("updates", "Updates available", "x")
    assert not svc.automation.alert("updates", "Updates available", "x")  # cooldown
    history = svc.automation.history()
    assert [(e["title"], e["sent"]) for e in history] == [
        ("Updates available", True),
        ("full", False),
    ]
    assert len(apprise.sent) == 1


def test_monitor_alerts_on_changes_only(setup, monkeypatch) -> None:
    svc, apprise, state = setup
    monkeypatch.setattr(svc.updates, "cached", lambda: {"images": {}, "repos": []})
    state["containers"] = [container("sonarr", health="unhealthy"), container("gluetun")]
    svc.automation.tick()  # first look: what is already wrong is the baseline
    assert apprise.sent == []
    state["containers"] = [
        container("sonarr"),
        container("gluetun", status="exited"),
        container("qbittorrent", mode="saltbox"),
    ]
    state["disks"] = [{"path": "/mnt/local", "percent": 93.0}]
    svc.automation.tick()
    titles = [title for _, title, _ in apprise.sent]
    assert "gluetun is stopped" in titles and "sonarr is running again" in titles
    assert "The VPN is down" in titles and "qBittorrent is not behind the VPN" in titles
    assert "/mnt/local is 93% full" in titles
    count = len(apprise.sent)
    svc.automation.tick()  # nothing changed: nothing new
    assert len(apprise.sent) == count


def test_new_updates_alert_once(setup, monkeypatch) -> None:
    svc, apprise, _ = setup
    images = {"images": {}, "repos": []}
    monkeypatch.setattr(svc.updates, "cached", lambda: images)
    svc.automation.tick()
    images["images"] = {"i": {"status": "update", "containers": ["sonarr"]}}
    images["repos"] = [{"name": "saltbox", "status": "update"}]
    svc.automation.tick()
    svc.automation.tick()
    updates = [body for _, title, body in apprise.sent if title == "Updates available"]
    assert updates == ["New versions for apps: sonarr; Saltbox itself."]


def test_failed_jobs_alert(setup) -> None:
    svc, apprise, _ = setup

    class Job:
        id, status, returncode = "abc", "failed", 2
        command = ["/usr/local/bin/sb", "install", "autoheal"]

    svc.automation.on_job_finished(Job())
    assert apprise.sent[-1][1] == "Job failed: sb install autoheal"


def test_maintenance_updates_all_but_excluded_and_reports(setup, monkeypatch) -> None:
    svc, apprise, _ = setup
    monkeypatch.setattr(daemon_routes, "_containers_or_none", lambda: [])
    svc.updates = UpdateService(
        svc.layout,
        containers=lambda: [],
        checker=lambda c: {
            "a": ImageStatus("a", "update", containers=["sonarr"]),
            "b": ImageStatus("b", "update", containers=["radarr"]),
        },
        repos=lambda: [],
    )
    svc.automation.save({"maintenance": {"enabled": True, "exclude": ["radarr"]}})
    record = svc.automation.run_maintenance(wait_seconds=30)
    assert record["status"] == "succeeded"
    assert [s["what"] for s in record["steps"]] == ["update Sonarr"]
    job = svc.runner.job(record["steps"][0]["job"])
    assert job.tags == ["sonarr"]
    assert apprise.sent[-1][1] == "Nightly maintenance done"
    assert (
        svc.automation.settings()["maintenance"]["last_run"]["date"]
        == datetime.now().date().isoformat()
    )


def test_next_maintenance(setup) -> None:
    svc, _, _ = setup
    svc.automation.clock = lambda: datetime(2026, 11, 10, 3, 0)
    assert svc.automation.next_maintenance() is None
    svc.automation.save({"maintenance": {"enabled": True, "time": "04:30"}})
    assert svc.automation.next_maintenance() == "2026-11-10T04:30"
    svc.automation.clock = lambda: datetime(2026, 11, 10, 9, 0)  # past the window
    assert svc.automation.next_maintenance() == "2026-11-11T04:30"


def test_routes_mask_the_apprise_url(setup) -> None:
    svc, _apprise, _ = setup
    client = TestClient(create_app(services=svc))
    shown = client.get("/api/automation").json()
    assert shown["settings"]["alerts"]["url"] == HIDDEN
    assert "topic-secret" not in str(shown)
    saved = client.put(
        "/api/automation", json={"alerts": {"url": HIDDEN, "events": {"disk": False}}}
    ).json()
    assert saved["settings"]["alerts"]["events"]["disk"] is False
    assert svc.automation.settings()["alerts"]["url"] == "ntfy://topic-secret"
    assert client.post("/api/automation/test").json()["ok"] is True
    assert client.put("/api/automation", json={"maintenance": {"time": "late"}}).status_code == 400
