from pathlib import Path

from saltbox_ui.catalog import parse_playbook
from saltbox_ui.catalog.playbook import TagIndex


def test_parse_saltbox_playbook(repo_root: Path):
    entries = {e.role: e for e in parse_playbook(repo_root / "saltbox.yml")}
    assert entries["sonarr"].tags == ("sonarr",)
    assert entries["sonarr"].section == "apps"
    assert entries["sonarr"].install_tag == "sonarr"
    assert entries["plex"].install_tag == "plex"
    assert "plex-reset-codecs" in entries["plex"].tags
    assert entries["docker"].section == "core"
    assert entries["docker"].install_tag == "docker"
    assert entries["pre_tasks"].section == "pre"
    assert entries["pre_tasks"].always
    assert entries["permissions"].section == "other"
    assert entries["permissions"].install_tag == "fix-permissions"
    assert entries["cloudplow"].when == ("use_cloudplow",)
    assert entries["authentik_worker"].install_tag is None
    assert entries["user"].line > 0


def test_tag_index(repo_root: Path):
    index = TagIndex(parse_playbook(repo_root / "saltbox.yml"))
    tags = index.all_tags()
    assert "saltbox" in tags and "sonarr" in tags
    assert "never" not in tags and "always" not in tags
    assert "sonarr" in index.by_tag()["saltbox"] or "main_tags" in index.by_tag()["saltbox"]
