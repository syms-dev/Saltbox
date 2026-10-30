from pathlib import Path

from saltbox_ui.config import ConfigService
from saltbox_ui.layout import Layout


def test_load_falls_back_to_defaults(scratch_layout: Layout):
    service = ConfigService(scratch_layout, list_remotes=lambda: ["google"])
    assert service.source("accounts") == "default"
    data = service.load_plain("accounts")
    assert data["user"]["name"] == "seed"
    assert service.source("motd") == "missing"
    assert service.load_plain("motd") == {}


def test_validate_reports_missing_required_file(scratch_layout: Layout):
    service = ConfigService(scratch_layout, list_remotes=lambda: ["google"])
    issues = service.validate("accounts")
    assert issues and "not found" in issues[0].message
    assert service.validate("motd") == []


def test_init_set_get_and_validate(scratch_layout: Layout):
    service = ConfigService(scratch_layout, list_remotes=lambda: ["google"])
    assert service.ensure_exists("accounts") is True
    assert service.ensure_exists("accounts") is False
    assert service.source("accounts") == "file"
    service.set("accounts", "user.domain", "example.com")
    service.set("accounts", "user.email", "me@example.com")
    service.set("accounts", "user.pass", "a-long-enough-password")
    assert service.get("accounts", "user.domain") == "example.com"
    issues = service.validate("accounts")
    assert [i.level for i in issues] == []
    text = service.path("accounts").read_text()
    assert text.startswith("---")
    assert "domain: example.com" in text


def test_validate_all_includes_inventory_duplicates(scratch_layout: Layout):
    service = ConfigService(scratch_layout, list_remotes=lambda: ["google"])
    for name in (
        "accounts",
        "settings",
        "adv_settings",
        "backup_config",
        "providers",
        "hetzner_vlan",
    ):
        service.ensure_exists(name)
    scratch_layout.inventory.write_text("plex_name: a\nplex_name: b\n")
    results = service.validate_all()
    assert "duplicate key" in results["inventory"][0].message
    assert any(i.level == "error" for i in results["accounts"])  # placeholder domain
    assert results["settings"] == []
    assert results["providers"] == []


def test_set_coerces_scalars(scratch_layout: Layout):
    service = ConfigService(scratch_layout, list_remotes=lambda: [])
    service.ensure_exists("adv_settings")
    service.set("adv_settings", "dns.ipv6", "yes")
    service.set("adv_settings", "traefik.cert.additional_domains", "[]")
    data = service.load_plain("adv_settings")
    assert data["dns"]["ipv6"] == "yes"
    assert data["traefik"]["cert"]["additional_domains"] == []
    assert "ipv6: yes" in service.path("adv_settings").read_text()


def test_paths(scratch_layout: Layout):
    service = ConfigService(scratch_layout)
    assert service.path("settings") == scratch_layout.repo / "settings.yml"
    assert service.default_path("motd") is None
    assert service.default_path("backup_config") == Path(
        scratch_layout.repo / "defaults" / "backup_config.yml.default"
    )
