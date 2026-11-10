import json

from saltbox_ui.layout import Layout
from saltbox_ui.state import (
    cached_tags,
    list_fact_roles,
    mounts,
    read_motd_services,
    read_port_assignments,
    read_role_facts,
)
from saltbox_ui.state.facts import read_all_facts, redact_value

FACTS = """[sonarr]
api_key = abcdef1234567890
url = http://sonarr:8989

[sonarr4k]
api_key = zyx
"""

MOTD = """---
sonarr:
  enabled: true
  instances:
    - name: sonarr
      url: https://sonarr.example.com
      apikey: abcdef1234567890
plex:
  - name: plex
    url: https://plex.example.com
    token: tok
"""

PROC_MOUNTS = """/dev/sda1 / ext4 rw 0 0
google: /mnt/remote/google fuse.rclone rw,nosuid 0 0
local:remote/google /mnt/unionfs fuse.mergerfs rw 0 0
tmpfs /run tmpfs rw 0 0
nas:/export /mnt/remote/nas\\040box nfs rw 0 0
"""


def test_facts(scratch_layout: Layout):
    scratch_layout.facts_dir.mkdir(parents=True)
    (scratch_layout.facts_dir / "sonarr.ini").write_text(FACTS)
    assert list_fact_roles(scratch_layout) == ["sonarr"]
    facts = read_role_facts(scratch_layout, "sonarr")
    assert facts["sonarr"]["api_key"] == "abcdef1234567890"
    assert facts["sonarr4k"] == {"api_key": "zyx"}
    assert read_role_facts(scratch_layout, "radarr") == {}
    redacted = read_all_facts(scratch_layout)
    assert redacted["sonarr"]["sonarr"]["api_key"] == "abcd…"
    assert redacted["sonarr"]["sonarr"]["url"] == "http://sonarr:8989"
    assert redact_value("api_key", "zyx") == "…"


def test_ports_and_tags(scratch_layout: Layout):
    assert read_port_assignments(scratch_layout) == {}
    scratch_layout.facts_dir.mkdir(parents=True)
    scratch_layout.ports_file.write_text(json.dumps({"rclone": {"google": {"rc": 5572}}}))
    assert read_port_assignments(scratch_layout)["rclone"]["google"]["rc"] == 5572
    assert cached_tags(scratch_layout) == {}
    scratch_layout.cache_file.write_text(
        json.dumps({str(scratch_layout.repo): {"commit": "x", "tags": ["a"]}})
    )
    assert cached_tags(scratch_layout)[str(scratch_layout.repo)]["tags"] == ["a"]


def test_motd(scratch_layout: Layout):
    assert read_motd_services(scratch_layout) == []
    scratch_layout.config_file("motd").write_text(MOTD)
    services = read_motd_services(scratch_layout)
    assert [s["service"] for s in services] == ["plex", "sonarr"]
    sonarr = next(s for s in services if s["service"] == "sonarr")
    assert sonarr["apikey"] == "abcd…"
    assert sonarr["url"] == "https://sonarr.example.com"
    plex = next(s for s in services if s["service"] == "plex")
    assert plex["token"] == "…"
    assert read_motd_services(scratch_layout, redact=False)[1]["apikey"] == "abcdef1234567890"


def test_mounts_parsing():
    found = mounts(PROC_MOUNTS)
    assert [m["target"] for m in found] == [
        "/mnt/remote/google",
        "/mnt/unionfs",
        "/mnt/remote/nas box",
    ]
    assert found[1]["type"] == "fuse.mergerfs"


def test_containers_from_the_docker_cli() -> None:
    import json

    from saltbox_ui.state.containers import list_containers_cli

    inspected = [
        {
            "Id": "abcdef1234567890",
            "Name": "/sonarr",
            "Config": {
                "Image": "ghcr.io/hotio/sonarr:release",
                "Labels": {
                    "com.github.saltbox.saltbox_managed": "true",
                    "traefik.enable": "true",
                    "traefik.http.routers.sonarr.middlewares": "a@file,b@file",
                },
            },
            "State": {"Status": "running", "Health": {"Status": "healthy"}},
        },
        {
            "Id": "0123456789abcdef",
            "Name": "/gluetun",
            "Config": {"Image": "qmcgaw/gluetun", "Labels": {}},
            "State": {"Status": "exited"},
        },
    ]
    calls = []

    def runner(args):
        calls.append(args)
        if args[:2] == ["docker", "ps"]:
            return 0, "abcdef1234567890\n0123456789abcdef\n"
        return 0, json.dumps(inspected)

    found = list_containers_cli(runner)
    assert [c["name"] for c in found] == ["gluetun", "sonarr"]
    sonarr = found[1]
    assert sonarr["managed"] and sonarr["traefik"] and sonarr["health"] == "healthy"
    assert sonarr["labels"]["traefik.http.routers.sonarr.middlewares"] == "a@file,b@file"
    assert found[0]["managed"] is False and found[0]["status"] == "exited"
    assert calls[1][:2] == ["docker", "inspect"]
    assert list_containers_cli(lambda args: (0, "")) == []
