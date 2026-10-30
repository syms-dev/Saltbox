from __future__ import annotations

from pathlib import Path

from saltbox_ui.catalog import Catalog
from saltbox_ui.config import ConfigService, Inventory
from saltbox_ui.installer.plan import InstallPlan, Remote
from saltbox_ui.layout import Layout
from saltbox_ui.yamlio import load_plain


def make_plan(**overrides) -> InstallPlan:
    base = {
        "user_name": "seed",
        "user_pass": "a-long-password-123",
        "domain": "example.com",
        "email": "me@example.com",
        "cloudflare_token": "cf-token",
    }
    base.update(overrides)
    return InstallPlan(**base)


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    plan = make_plan(remotes=[Remote("google", upload=True)], extra_apps=["overseerr"])
    path = tmp_path / "state" / "plan.json"
    plan.save(path)
    assert path.stat().st_mode & 0o777 == 0o600
    loaded = InstallPlan.load(path)
    assert loaded == plan
    assert isinstance(loaded.remotes[0], Remote)


def test_from_dict_ignores_unknown_keys() -> None:
    plan = InstallPlan.from_dict({"user_name": "bob", "future_field": 1})
    assert plan.user_name == "bob"


def test_redacted_hides_secrets() -> None:
    plan = make_plan(dockerhub_token="dh", provider_credentials={"api_key": "k"})
    data = plan.redacted()
    assert data["user_pass"] != plan.user_pass
    assert data["cloudflare_token"] != "cf-token"
    assert data["dockerhub_token"] != "dh"
    assert data["provider_credentials"]["api_key"] != "k"
    assert data["domain"] == "example.com"


def test_install_tags_by_profile() -> None:
    assert make_plan(profile="saltbox").install_tags() == ["saltbox"]
    assert make_plan(profile="core").install_tags() == ["core"]
    custom = make_plan(profile="custom", extra_apps=["plex", "radarr"], sandbox_apps=["tdarr"])
    assert custom.install_tags() == ["core", "plex", "radarr", "sandbox-tdarr"]
    boxed = make_plan(profile="mediabox", extra_apps=["mediabox", "overseerr"])
    assert boxed.install_tags() == ["mediabox", "overseerr"]


def test_rclone_enabled_requires_remotes() -> None:
    assert not make_plan(storage_mode="local", remotes=[Remote("g")]).rclone_enabled
    assert not make_plan(storage_mode="create").rclone_enabled
    assert make_plan(storage_mode="existing", remotes=[Remote("g")]).rclone_enabled


def test_summary_mentions_choices() -> None:
    summary = dict(make_plan(dns_mode="manual", storage_mode="local").summary())
    assert summary["DNS"].startswith("manual")
    assert "rclone disabled" in summary["Storage"]
    assert summary["Install"] == "saltbox"


def test_apply_writes_saltbox_files(scratch_layout: Layout) -> None:
    config = ConfigService(scratch_layout)
    for name in ("accounts", "settings", "adv_settings", "backup_config", "providers"):
        config.ensure_exists(name)
    config.ensure_exists("hetzner_vlan")
    inventory = Inventory(scratch_layout.inventory)
    plan = make_plan(
        storage_mode="existing",
        remotes=[Remote("google", upload=True), Remote("box", template="sftp", union=False)],
        media_servers=["jellyfin"],
        sandbox_apps=["tdarr"],
        dns_ipv6=True,
        timezone="Europe/Copenhagen",
        backup_rclone=True,
    )
    touched = plan.apply(config, inventory, Catalog(scratch_layout).profiles)
    assert touched == [
        "accounts.yml",
        "settings.yml",
        "adv_settings.yml",
        "backup_config.yml",
        "inventories/host_vars/localhost.yml",
    ]

    accounts = load_plain(scratch_layout.config_file("accounts"))
    assert accounts["user"] == {
        "name": "seed",
        "pass": "a-long-password-123",
        "domain": "example.com",
        "email": "me@example.com",
        "ssh_key": None,
    }
    assert accounts["cloudflare"]["scoped_token"] == "cf-token"
    assert accounts["cloudflare"]["api"] is None

    settings = load_plain(scratch_layout.config_file("settings"))
    assert settings["rclone"]["enabled"] == "yes"
    remotes = settings["rclone"]["remotes"]
    assert [r["remote"] for r in remotes] == ["google", "box"]
    assert remotes[0]["settings"]["upload"] == "yes"
    assert remotes[1]["settings"]["union"] == "no"
    assert remotes[1]["settings"]["template"] == "sftp"
    assert remotes[0]["settings"]["vfs_cache"] == {
        "enabled": "no",
        "max_age": "504h",
        "size": "50G",
    }

    adv = load_plain(scratch_layout.config_file("adv_settings"))
    assert adv["dns"]["ipv6"] == "yes"
    assert adv["system"]["timezone"] == "Europe/Copenhagen"
    assert adv["traefik"]["provider"] == "cloudflare"
    assert adv["traefik"]["cert"]["http_validation"] == "no"

    backup = load_plain(scratch_layout.config_file("backup_config"))
    assert backup["backup"]["rclone"]["enable"] is True
    assert backup["backup"]["rclone"]["destination"] == "google:/Backups/Saltbox"
    assert backup["backup"]["rclone"]["template"] == "google"

    inv = load_plain(scratch_layout.inventory)
    assert inv["media_servers_enabled"] == ["jellyfin"]
    assert inv["sandbox_roles"] == ["tdarr"]
    assert "download_clients_enabled" not in inv  # same as the role default

    # Everything written passes the same validation sb runs.
    results = config.validate_all()
    errors = [i for issues in results.values() for i in issues if i.level == "error"]
    assert errors == []


def test_apply_manual_dns_and_provider(scratch_layout: Layout) -> None:
    config = ConfigService(scratch_layout)
    inventory = Inventory(scratch_layout.inventory)
    profiles = Catalog(scratch_layout).profiles

    manual = make_plan(dns_mode="manual", cloudflare_token="")
    manual.apply(config, inventory, profiles)
    adv = load_plain(scratch_layout.config_file("adv_settings"))
    assert adv["traefik"]["cert"]["http_validation"] == "yes"
    accounts = load_plain(scratch_layout.config_file("accounts"))
    assert accounts["cloudflare"]["scoped_token"] is None

    provider = make_plan(
        dns_mode="provider",
        cloudflare_token="",
        provider="hetzner",
        provider_credentials={"api_key": "secret"},
    )
    touched = provider.apply(config, inventory, profiles)
    assert "providers.yml" in touched
    adv = load_plain(scratch_layout.config_file("adv_settings"))
    assert adv["traefik"]["provider"] == "hetzner"
    providers = load_plain(scratch_layout.config_file("providers"))
    assert providers["hetzner"]["api_key"] == "secret"


def test_apply_local_storage_drops_remotes(scratch_layout: Layout) -> None:
    config = ConfigService(scratch_layout)
    inventory = Inventory(scratch_layout.inventory)
    profiles = Catalog(scratch_layout).profiles
    make_plan(storage_mode="existing", remotes=[Remote("google")]).apply(
        config, inventory, profiles
    )
    make_plan(storage_mode="local").apply(config, inventory, profiles)
    settings = load_plain(scratch_layout.config_file("settings"))
    assert settings["rclone"]["enabled"] == "no"
    assert "remotes" not in settings["rclone"]
