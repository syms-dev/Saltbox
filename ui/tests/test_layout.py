from pathlib import Path

from saltbox_ui.layout import DEFAULT_APPDATA, Layout, appdata_from_inventory


def test_defaults_match_sb_go():
    layout = Layout()
    assert layout.repo == Path("/srv/git/saltbox")
    assert layout.playbook == Path("/srv/git/saltbox/saltbox.yml")
    assert layout.inventory == Path("/srv/git/saltbox/inventories/host_vars/localhost.yml")
    assert layout.config_file("accounts") == Path("/srv/git/saltbox/accounts.yml")
    assert layout.default_file("settings") == Path("/srv/git/saltbox/defaults/settings.yml.default")
    assert layout.facts_dir == Path("/opt/saltbox")
    assert layout.sandbox_repo == Path("/opt/sandbox")
    assert layout.cache_file == Path("/srv/git/saltbox/cache.json")


def test_appdata_from_inventory(tmp_path: Path):
    inventory = tmp_path / "localhost.yml"
    assert appdata_from_inventory(inventory) == DEFAULT_APPDATA
    inventory.write_text("server_appdata_path: /data/apps/\n")
    assert appdata_from_inventory(inventory) == Path("/data/apps")
    inventory.write_text("server_appdata_path: relative\n")
    assert appdata_from_inventory(inventory) == DEFAULT_APPDATA
    inventory.write_text("not: [valid\n")
    assert appdata_from_inventory(inventory) == DEFAULT_APPDATA


def test_from_env_reads_inventory_for_appdata(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "inventories" / "host_vars").mkdir(parents=True)
    (repo / "inventories" / "host_vars" / "localhost.yml").write_text(
        "server_appdata_path: /mnt/apps\n"
    )
    layout = Layout.from_env({"SALTBOX_REPO": str(repo)})
    assert layout.appdata == Path("/mnt/apps")
    assert layout.facts_dir == Path("/mnt/apps/saltbox")
    explicit = Layout.from_env({"SALTBOX_REPO": str(repo), "SALTBOX_APPDATA": "/opt2"})
    assert explicit.appdata == Path("/opt2")
