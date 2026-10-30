from __future__ import annotations

from pathlib import Path

import pytest

from saltbox_ui.installer import InstallerSession
from saltbox_ui.installer import session as session_module
from saltbox_ui.installer.plan import InstallPlan
from saltbox_ui.layout import Layout
from saltbox_ui.rclone import RcloneService
from saltbox_ui.yamlio import load_plain


def filled_plan(**overrides) -> InstallPlan:
    base = {
        "user_name": "seed",
        "user_pass": "a-long-password-123",
        "domain": "example.com",
        "email": "me@example.com",
        "cloudflare_token": "cf-token",
    }
    base.update(overrides)
    return InstallPlan(**base)


@pytest.fixture
def session(scratch_layout: Layout, fake_sb: Path) -> InstallerSession:
    return InstallerSession(scratch_layout, plan=filled_plan())


def test_fresh_session_is_not_resumable(scratch_layout: Layout, fake_sb: Path) -> None:
    session = InstallerSession(scratch_layout)
    assert not session.resumable
    assert session.plan.phase == "collect"
    session.save()
    assert session.plan_path.exists()
    assert not session.resumable  # collect phase never resumes


def test_plan_persists_between_sessions(session: InstallerSession) -> None:
    session.set_phase("storage")
    again = InstallerSession(session.layout)
    assert again.resumable
    assert again.plan.phase == "storage"
    assert again.plan.domain == "example.com"
    again.discard()
    assert not again.plan_path.exists()
    assert again.plan.phase == "collect"


def test_corrupt_plan_file_is_ignored(scratch_layout: Layout, fake_sb: Path) -> None:
    scratch_layout.state_dir.mkdir(parents=True)
    (scratch_layout.state_dir / "install-plan.json").write_text("{not json")
    assert InstallerSession(scratch_layout).plan.phase == "collect"


def test_apply_config_creates_files_and_validates(session: InstallerSession) -> None:
    created = session.ensure_config_files()
    assert "accounts" in created
    assert "hetzner_vlan" in created
    touched = session.apply_config()
    assert "accounts.yml" in touched
    accounts = load_plain(session.layout.config_file("accounts"))
    assert accounts["user"]["domain"] == "example.com"
    results = session.validate()
    assert not session.has_errors(results)


def test_validate_reports_errors(session: InstallerSession) -> None:
    session.plan.email = "not-an-email"
    session.apply_config()
    results = session.validate()
    assert session.has_errors(results)
    assert any("email" in i.path for i in results["accounts"])


def test_preinstall_then_install(session: InstallerSession) -> None:
    lines: list[str] = []
    job = session.run_preinstall(on_line=lines.append)
    assert job.status == "succeeded"
    assert any("install preinstall" in line for line in lines)
    assert session.plan.phase == "storage"
    assert session.plan.jobs["preinstall"] == job.id
    assert session.plan.preinstall_started_at is not None

    session.plan.profile = "mediabox"
    session.plan.extra_apps = ["overseerr"]
    job = session.run_install(on_line=lines.append)
    assert job.status == "succeeded"
    assert session.plan.phase == "done"
    assert any("install mediabox,overseerr" in line for line in lines)
    assert InstallPlan.load(session.plan_path).phase == "done"


def test_failed_preinstall_keeps_phase(
    session: InstallerSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_SB_EXIT", "2")
    job = session.run_preinstall()
    assert job.status == "failed"
    assert session.plan.phase == "preinstall"
    assert InstallPlan.load(session.plan_path).phase == "preinstall"


def test_resume_after_reboot(session: InstallerSession, monkeypatch: pytest.MonkeyPatch) -> None:
    session.plan.phase = "preinstall"
    session.plan.preinstall_started_at = 1_000.0
    session.save()
    monkeypatch.setattr(session_module, "boot_time", lambda: 900.0)
    assert not session.preinstall_rebooted()
    assert not session.resume_after_reboot()
    monkeypatch.setattr(session_module, "boot_time", lambda: 1_100.0)
    assert session.preinstall_rebooted()
    assert session.resume_after_reboot()
    assert session.plan.phase == "storage"
    assert session.plan.notes
    assert not session.resume_after_reboot()  # only once


def test_rclone_runs_as_plan_user(session: InstallerSession) -> None:
    service = session.rclone()
    assert isinstance(service, RcloneService)
    assert service.user == "seed"
    assert service.command("version")[:4] == ["sudo", "-u", "seed", "-H"]


def test_run_tag_records_job(session: InstallerSession) -> None:
    job = session.run_tag(["plex", "radarr"])
    assert job.status == "succeeded"
    assert session.plan.jobs["plex,radarr"] == job.id
