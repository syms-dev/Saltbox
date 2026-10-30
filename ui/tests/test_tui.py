"""Drive the installer wizard end to end with Textual's test pilot."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Button, Input, Log, RadioButton, RadioSet, Select, Static

from saltbox_ui.installer import InstallerSession
from saltbox_ui.installer.plan import InstallPlan
from saltbox_ui.layout import Layout
from saltbox_ui.rclone import RcloneService
from saltbox_ui.tui.app import STEPS, InstallerApp
from saltbox_ui.tui.installer.rclone_screen import RcloneQuestionScreen
from saltbox_ui.tui.installer.screens import (
    AccountScreen,
    AppsScreen,
    DoneScreen,
    InstallScreen,
    PreflightScreen,
    PreinstallScreen,
    ReviewScreen,
    StorageScreen,
    WelcomeScreen,
)
from saltbox_ui.tui.widgets import CheckRow
from saltbox_ui.yamlio import load_plain
from tests.test_preflight import good_probe

GIB = 1024**3


@pytest.fixture
def session(scratch_layout: Layout, fake_sb: Path, fake_rclone: Path, tmp_path: Path):
    def rclone_factory(user: str) -> RcloneService:
        return RcloneService(fake_rclone, config_path=tmp_path / "rclone.conf")

    return InstallerSession(scratch_layout, rclone_factory=rclone_factory)


def make_app(session: InstallerSession, probe=None) -> InstallerApp:
    return InstallerApp(session, probe_factory=lambda layout: probe or good_probe())


async def settle(app: InstallerApp, pilot) -> None:
    await app.workers.wait_for_complete()
    await pilot.pause()


async def click(pilot, selector: str) -> None:
    """Click, then wait out Button's active effect, during which it ignores clicks."""
    await pilot.click(selector)
    await pilot.pause(0.3)


async def next_step(app: InstallerApp, pilot) -> None:
    await click(pilot, "#next")


def set_input(app: InstallerApp, widget_id: str, value: str) -> None:
    app.screen.query_one(f"#{widget_id}", Input).value = value


async def pick_radio(app: InstallerApp, radio_set: str, name: str, pilot) -> None:
    for button in app.screen.query_one(f"#{radio_set}", RadioSet).query(RadioButton):
        if button.name == name:
            button.value = True
    await pilot.pause()


async def test_full_wizard(session: InstallerSession) -> None:
    app = make_app(session)
    async with app.run_test(size=(120, 50)) as pilot:
        assert isinstance(app.screen, WelcomeScreen)
        assert "#resume" not in [f"#{b.id}" for b in app.screen.query(Button)]
        await next_step(app, pilot)

        assert isinstance(app.screen, PreflightScreen)
        await settle(app, pilot)
        rows = app.screen.query(CheckRow)
        assert len(rows) >= 10
        assert all(row.status == "pass" for row in rows)
        assert not app.screen.query_one("#next", Button).disabled
        await next_step(app, pilot)

        assert isinstance(app.screen, AccountScreen)
        set_input(app, "user_name", "seed")
        set_input(app, "user_pass", "short")
        set_input(app, "user_pass2", "short")
        set_input(app, "domain", "example.com")
        set_input(app, "email", "me@example.com")
        await next_step(app, pilot)
        assert isinstance(app.screen, AccountScreen)  # blocked: password too short
        set_input(app, "user_pass", "a-long-password-123")
        set_input(app, "user_pass2", "a-long-password-123")
        await next_step(app, pilot)

        assert app.screen.TITLE == "DNS and certificates"
        assert app.screen.query_one("#cf_token_box").display
        assert not app.screen.query_one("#manual_box").display
        await next_step(app, pilot)
        assert app.screen.TITLE == "DNS and certificates"  # blocked: token missing
        set_input(app, "cf_token", "cf-token")
        await next_step(app, pilot)

        assert isinstance(app.screen, AppsScreen)
        await next_step(app, pilot)

        assert app.screen.TITLE == "Advanced"
        set_input(app, "timezone", "Europe/Copenhagen")
        await next_step(app, pilot)

        assert isinstance(app.screen, ReviewScreen)
        await next_step(app, pilot)
        assert session.layout.config_file("accounts").exists()
        accounts = load_plain(session.layout.config_file("accounts"))
        assert accounts["user"]["name"] == "seed"
        assert accounts["cloudflare"]["scoped_token"] == "cf-token"

        assert isinstance(app.screen, PreinstallScreen)
        assert app.screen.query_one("#next", Button).disabled
        await click(pilot, "#run")
        await settle(app, pilot)
        assert "preinstall completed" in str(app.screen.query_one("#status", Static).content)
        assert session.plan.phase == "storage"
        assert "install preinstall" in "\n".join(app.screen.query_one("#log", Log).lines)
        await next_step(app, pilot)

        assert isinstance(app.screen, StorageScreen)
        assert not app.screen.query_one("#remote_box").display
        await next_step(app, pilot)

        assert isinstance(app.screen, InstallScreen)
        assert "sb install saltbox" in str(app.screen.query(".hint").first(Static).content)
        await click(pilot, "#run")
        await settle(app, pilot)
        assert session.plan.phase == "done"
        await next_step(app, pilot)

        assert isinstance(app.screen, DoneScreen)
        text = "\n".join(str(s.content) for s in app.screen.query(Static))
        assert "https://plex.example.com" in text
        assert "https://login.example.com" in text
        await next_step(app, pilot)  # Exit
    assert app.return_code == 0

    settings = load_plain(session.layout.config_file("settings"))
    assert settings["rclone"]["enabled"] == "no"
    adv = load_plain(session.layout.config_file("adv_settings"))
    assert adv["system"]["timezone"] == "Europe/Copenhagen"
    assert InstallPlan.load(session.plan_path).phase == "done"


async def test_preflight_failure_blocks(session: InstallerSession) -> None:
    app = make_app(session, probe=good_probe(virt="lxc"))
    async with app.run_test(size=(120, 50)) as pilot:
        await next_step(app, pilot)
        await settle(app, pilot)
        assert isinstance(app.screen, PreflightScreen)
        rows = {row.check_id: row for row in app.screen.query(CheckRow)}
        assert rows["lxc"].status == "fail"
        assert app.screen.query_one("#next", Button).disabled
        summary = str(app.screen.query_one("#preflight-summary", Static).content)
        assert "1 failed" in summary


async def test_resume_after_preinstall(session: InstallerSession) -> None:
    session.plan = InstallPlan(
        phase="storage",
        user_name="seed",
        user_pass="a-long-password-123",
        domain="example.com",
        email="me@example.com",
        cloudflare_token="cf-token",
        preinstall_started_at=1.0,
    )
    session.save()
    app = make_app(session)
    async with app.run_test(size=(120, 50)) as pilot:
        assert isinstance(app.screen, WelcomeScreen)
        assert app.screen.query_one("#resume", Button)
        await click(pilot, "#resume")
        assert isinstance(app.screen, StorageScreen)
        assert app.step_index == STEPS.index(StorageScreen)


async def test_discard_previous_plan(session: InstallerSession) -> None:
    session.plan.phase = "preinstall"
    session.save()
    app = make_app(session)
    async with app.run_test(size=(120, 50)) as pilot:
        await click(pilot, "#discard")
        assert not session.plan_path.exists()
        assert session.plan.phase == "collect"
        assert app.screen.query_one("#resume", Button).disabled


async def test_storage_creates_remote_through_rclone(session: InstallerSession) -> None:
    session.plan = InstallPlan(
        phase="storage",
        user_name="seed",
        user_pass="a-long-password-123",
        domain="example.com",
        email="me@example.com",
        cloudflare_token="cf-token",
    )
    session.save()
    app = make_app(session)
    async with app.run_test(size=(120, 60)) as pilot:
        await click(pilot, "#resume")
        assert isinstance(app.screen, StorageScreen)
        storage = app.screen
        await pick_radio(app, "storage_mode", "create", pilot)
        await settle(app, pilot)
        assert storage.query_one("#remote_box").display
        assert "no remotes" in str(storage.query_one("#remote_status", Static).content)
        select = storage.query_one("#new_type", Select)
        select.value = "drive"
        set_input(app, "new_name", "google")
        await click(pilot, "#create")
        await settle(app, pilot)

        modal = app.screen
        assert isinstance(modal, RcloneQuestionScreen)
        assert modal.question is not None
        assert modal.question.name == "client_id"
        await click(pilot, "#default")  # accept the empty client id
        await settle(app, pilot)
        # config_is_local is answered automatically; the token question comes next.
        assert modal.question.name == "config_token"
        authorize = str(modal.query_one("#authorize", Static).content)
        assert 'rclone authorize "drive"' in authorize
        await click(pilot, "#submit")  # empty token: the modal refuses, we stay
        await settle(app, pilot)
        assert isinstance(app.screen, RcloneQuestionScreen)
        assert "required" in str(modal.query_one("#error", Static).content)
        modal.query_one("#answer", Input).value = "{token}"
        await click(pilot, "#submit")
        await settle(app, pilot)

        assert app.screen is storage
        assert [r.remote for r in session.plan.remotes] == ["google"]
        assert "google created" in str(storage.query_one("#remote_status", Static).content)
        await click(pilot, "#mkmedia_0")
        await settle(app, pilot)
        assert session.rclone().list_dirs("google") == ["Media"]

        await next_step(app, pilot)
        assert isinstance(app.screen, InstallScreen)
        assert session.plan.storage_mode == "create"
        assert session.plan.rclone_enabled
        await click(pilot, "#run")
        await settle(app, pilot)
    settings = load_plain(session.layout.config_file("settings"))
    assert settings["rclone"]["enabled"] == "yes"
    assert settings["rclone"]["remotes"][0]["remote"] == "google"
    assert settings["rclone"]["remotes"][0]["settings"]["template"] == "google"


async def test_storage_existing_without_remotes_blocks(session: InstallerSession) -> None:
    session.plan = InstallPlan(phase="storage", user_name="seed", domain="example.com")
    session.save()
    app = make_app(session)
    async with app.run_test(size=(120, 50)) as pilot:
        await click(pilot, "#resume")
        await pick_radio(app, "storage_mode", "existing", pilot)
        await settle(app, pilot)
        await next_step(app, pilot)
        assert isinstance(app.screen, StorageScreen)  # blocked: nothing in rclone.conf
