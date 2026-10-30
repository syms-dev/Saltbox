from saltbox_ui.catalog import Catalog
from saltbox_ui.layout import Layout


def test_apps_from_real_repo(repo_layout: Layout):
    catalog = Catalog(repo_layout)
    apps = {a.role: a for a in catalog.apps()}
    assert "sonarr" in apps and "plex" in apps
    assert "docker" not in apps  # core role
    assert "permissions" not in apps  # maintenance tag
    sonarr = apps["sonarr"]
    assert sonarr.sb_tag == "sonarr"
    assert sonarr.supports_instances
    assert sonarr.title == "Sonarr"
    assert sonarr.categories == ["Content Acquisition Apps > Collection Manager"]
    assert sonarr.main_tags == ["feederbox", "saltbox"]
    plex = apps["plex"]
    assert plex.selector == "media_servers_enabled"
    assert plex.main_tags == ["mediabox", "saltbox"]
    assert apps["sabnzbd"].selector == "download_clients_enabled"
    assert apps["jackett"].selector == "download_indexers_enabled"
    assert apps["emby"].selector is None
    assert apps["emby"].main_tags == []


def test_profiles_and_hidden(repo_layout: Layout):
    catalog = Catalog(repo_layout)
    assert catalog.profiles["media_servers_enabled"] == ["plex"]
    assert "sonarr" in catalog.profiles["saltbox_roles"]
    hidden = {a.role: a for a in catalog.apps(include_hidden=True)}
    assert hidden["docker"].section == "core"
    assert catalog.app("plex").role == "plex"
    assert catalog.app("nope") is None
    categories = catalog.categories()
    assert "saltbox/plex" in categories["Content Delivery Apps > Media Server"]


def test_sandbox_absent_is_fine(repo_layout: Layout):
    catalog = Catalog(repo_layout)
    assert catalog.sandbox_roles == []
    assert all(a.repo == "saltbox" for a in catalog.apps())


def test_bundled_metadata_has_sandbox_entries():
    from saltbox_ui.catalog.catalog import load_bundled_metadata

    meta = load_bundled_metadata()
    assert "sandbox/kometa" in meta
    assert meta["sandbox/kometa"]["categories"]
    assert meta["saltbox/plex"]["link"].startswith("https://")
