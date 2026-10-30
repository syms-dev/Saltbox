from pathlib import Path

from saltbox_ui.config import Inventory, instance_key, role_key


def test_keys():
    assert role_key("sonarr", "_docker_image_tag") == "sonarr_role_docker_image_tag"
    assert instance_key("sonarr4k", "_docker_image_tag") == "sonarr4k_docker_image_tag"


def test_missing_inventory_behaves_as_empty(tmp_path: Path):
    inventory = Inventory(tmp_path / "localhost.yml")
    assert inventory.as_dict() == {}
    assert inventory.instances("sonarr") == ["sonarr"]
    assert inventory.get("x", 1) == 1
    assert inventory.unset("x") is False


def test_set_creates_file_with_header_and_preserves_comments(tmp_path: Path):
    path = tmp_path / "localhost.yml"
    inventory = Inventory(path)
    inventory.set("sonarr_instances", "[sonarr, sonarr4k]")
    assert inventory.instances("sonarr") == ["sonarr", "sonarr4k"]
    text = path.read_text()
    assert text.startswith("---\n# Saltbox inventory")
    path.write_text(text + "# keep me\nplex_open_main_ports: true\n")
    inventory.set("sonarr4k_web_subdomain", "tv4k")
    out = path.read_text()
    assert "# keep me" in out
    assert "plex_open_main_ports: true" in out
    assert inventory.get("sonarr4k_web_subdomain") == "tv4k"
    assert inventory.unset("plex_open_main_ports") is True
    assert "plex_open_main_ports" not in path.read_text()


def test_overrides_grouped_by_scope(tmp_path: Path):
    path = tmp_path / "localhost.yml"
    path.write_text(
        "sonarr_instances: [sonarr, sonarr4k]\n"
        "sonarr_role_docker_image_tag: nightly\n"
        "sonarr4k_web_subdomain: tv4k\n"
        "sonarr_themepark_theme: nord\n"
        "sonarr_open_ports: true\n"
        "radarr_role_docker_image_tag: nightly\n"
    )
    inventory = Inventory(path)
    groups = inventory.overrides_for("sonarr", ["sonarr", "sonarr4k"])
    assert groups["role"] == {"sonarr_role_docker_image_tag": "nightly"}
    assert groups["sonarr4k"] == {"sonarr4k_web_subdomain": "tv4k"}
    assert set(groups["sonarr"]) == {
        "sonarr_instances",
        "sonarr_themepark_theme",
        "sonarr_open_ports",
    }
    assert "radarr_role_docker_image_tag" not in str(groups)
    assert inventory.effective("sonarr", "_docker_image_tag", "sonarr4k", "release") == "nightly"
    assert inventory.effective("sonarr", "_web_subdomain", "sonarr4k") == "tv4k"
    assert inventory.effective("sonarr", "_web_subdomain", "sonarr", "sonarr") == "sonarr"
