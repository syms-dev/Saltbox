"""A disposable Saltbox host for end-to-end tests of the daemon and web app.

``python -m tests.e2e_box --port 8790 --token e2e`` builds a box in a temp
directory and serves the real daemon (real routes, real bearer-token check,
real job runner, the built web app) on it. Only the outside world is faked:

- ``sb``: prints a short Ansible-like log; a tag containing ``e2e-fail``
  fails the way a real playbook does, and ``e2e-slow`` runs for a minute.
  ``sb update`` is ``fake_sb_update.py``: it needs a terminal, shows an
  announcement in a full-screen viewer and asks whether to run a migration.
- ``docker``: ``ps``, ``inspect`` and ``image inspect`` answer from a fixed
  set of containers (healthy, unhealthy, stopped, one inside Gluetun).
- the image registry: Sonarr, Gluetun, Traefik and Authelia's Redis have newer
  images, the rest are current.
- the Saltbox checkout is a git repository one commit behind its upstream.
- Ubuntu wants a restart after a kernel update; restarting only leaves a note.
- Scrutiny reports three drives, one of them failing, and says which attribute.
- media is on local disks only, and Autoscan waits for an anchor file that is missing.
- the last day of logs has one known error (Prowlarr) and one that repeats (Sonarr).

The Playwright suite in ``ui/web/e2e`` starts this as its web server.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from saltbox_ui.appsetup import AppSetup
from saltbox_ui.appsetup.http import Response
from saltbox_ui.daemon import Services, create_app
from saltbox_ui.daemon.updates import UpdateService
from saltbox_ui.layout import Layout
from saltbox_ui.state.updates import Registry, check_updates

from .saltbox_checkout import saltbox_checkout

REPO_ROOT = saltbox_checkout()
WEB_DIST = Path(__file__).resolve().parents[1] / "web" / "dist"
DOMAIN = "e2e.example"
UPDATED_IMAGES = {"hotio/sonarr", "qmcgaw/gluetun", "library/traefik", "library/redis"}


def _container(
    name: str,
    image: str,
    *,
    status: str = "running",
    health: str | None = "healthy",
    network: str = "saltbox",
    web: bool = True,
    depends_on: str = "",
) -> dict[str, Any]:
    labels = {"com.github.saltbox.saltbox_managed": "true"}
    if depends_on:
        labels["com.github.saltbox.depends_on"] = depends_on
    if web:
        host = f"Host(`{name}.{DOMAIN}`)"
        labels[f"traefik.http.routers.{name}.rule"] = host
        labels[f"traefik.http.routers.{name}-http.rule"] = host
        labels[f"traefik.http.routers.{name}-api.rule"] = f"{host} && PathPrefix(`/api`)"
    state: dict[str, Any] = {"Status": status}
    if health is not None:
        state["Health"] = {"Status": health}
    return {
        "Id": f"{name:0>16}"[:16].replace(" ", "0"),
        "Name": f"/{name}",
        "Config": {"Image": image, "Labels": labels},
        "State": state,
        "Image": f"sha256:{name}",
        "HostConfig": {"NetworkMode": network},
    }


CONTAINERS = [
    _container("plex", "ghcr.io/hotio/plex:release"),
    _container("sonarr", "ghcr.io/hotio/sonarr:release"),
    _container("radarr", "ghcr.io/hotio/radarr:release"),
    _container("prowlarr", "ghcr.io/hotio/prowlarr:release", health="unhealthy"),
    _container("gluetun", "qmcgaw/gluetun:latest", web=False),
    _container(
        "qbittorrent", "saltydk/qbittorrent:latest", health=None, network="container:gluetun"
    ),
    _container("dozzle", "amir20/dozzle:latest", status="exited", health=None),
    # Autoheal keeps no config folder; it counts as installed by its container alone.
    _container("autoheal", "willfarrell/autoheal:latest", health=None, web=False),
    _container("recyclarr", "ghcr.io/recyclarr/recyclarr:8", health=None, web=False),
    # Saltbox's own core, not apps anyone picked. Traefik has a newer image, and so
    # has the Redis that the Authelia role creates beside Authelia.
    _container("traefik", "traefik:v3", health=None, web=False),
    _container("authelia", "authelia/authelia:4", depends_on="authelia-redis"),
    _container("authelia-redis", "redis:alpine", health=None, web=False),
    _container("scrutiny", "ghcr.io/analogj/scrutiny:master-omnibus", health=None),
    _container("autoscan", "ghcr.io/saltydk/autoscan:latest", health=None),
    # Installed and not used: the one the uninstall test removes.
    _container("lidarr", "ghcr.io/hotio/lidarr:release"),
]
# Autoscan has no folder here so that Connect apps leaves it alone: only its log matters.
NO_APPDATA = {"autoheal", "authelia-redis", "autoscan"}
SECRET_KEY = "e2e-wireguard-private-key="

FAKE_DOCKER = """#!{python}
import json, os, sys
containers = json.load(open({inspect!r}))
args = sys.argv[1:]
if args[:1] == ["ps"]:
    print("\\n".join(c["Id"] for c in containers))
elif args[:2] == ["inspect", "-f"]:
    print("")  # no network addresses: the daemon reaches apps by name
elif args[:1] == ["inspect"]:
    print(json.dumps([c for c in containers if c["Id"] in args[1:]]))
elif args[:2] == ["image", "inspect"]:
    out = []
    for c in containers:
        if c["Image"] in args[2:]:
            repo = c["Config"]["Image"].rsplit(":", 1)[0]
            out.append({{"Id": c["Image"], "RepoDigests": [repo + "@sha256:" + c["Image"][7:]]}})
    print(json.dumps(out))
elif args[:1] in (["start"], ["stop"], ["restart"]):
    name = args[-1]
    for c in containers:
        if c["Name"] == "/" + name:
            c["State"]["Status"] = "exited" if args[0] == "stop" else "running"
            if args[0] != "stop" and "Health" in c["State"]:
                c["State"]["Health"]["Status"] = "healthy"
    json.dump(containers, open({inspect!r}, "w"))
    print(name)
elif args[:2] == ["rm", "--force"]:
    json.dump([c for c in containers if c["Name"] != "/" + args[-1]], open({inspect!r}, "w"))
    print(args[-1])
elif args[:1] == ["logs"] and "--since" in args:
    # The last day of a log, for the problem finder: one error Prowlarr is known for,
    # one that Sonarr keeps repeating, and nothing wrong anywhere else.
    stamp = "2026-11-13T07:06:22.000000000Z "
    if args[-1] == "autoscan" and not os.path.exists({anchor!r}):
        # Autoscan waits for a file that only cloud storage would bring; this box has none.
        missing = 'missing_anchors=["' + {merged!r} + '"]'
        held = "Nov 13 07:06:22 ERR Anchor files unavailable, retaining queued scans "
        for _ in range(3):
            print(stamp + held + missing)
    elif args[-1] == "prowlarr":
        blocked = "Unable to access example.invalid, blocked by CloudFlare Protection."
        print(stamp + "[Warn] Torznab: " + blocked)
    elif args[-1] == "sonarr":
        for n in range(4):
            failed = "[Error] ImportService: Import failed for /downloads/Some.Show.S01E0"
            print(stamp + failed + str(n))
    else:
        print(stamp + "[Info] Nothing to report")
elif args[:1] == ["stats"]:
    for i, c in enumerate(c for c in containers if c["State"]["Status"] == "running"):
        cpu = 31.5 if c["Name"] == "/plex" else 0.4 * (i + 1)
        mem = 1500 if c["Name"] == "/plex" else 120 + 40 * i
        print(json.dumps({{"Name": c["Name"][1:], "CPUPerc": f"{{cpu:.2f}}%",
                          "MemUsage": f"{{mem}}MiB / 15.5GiB", "MemPerc": f"{{mem / 158.72:.2f}}%",
                          "PIDs": "20"}}))
elif args[:4] == ["exec", "recyclarr", "recyclarr", "sync"]:
    preview = "--preview" in args
    print("[INF] Processing Sonarr Server: [sonarr]")
    print("[INF] Created 42 New Custom Formats" + (" (preview)" if preview else ""))
    print("[INF] Updated Quality Profile: WEB-1080p")
    print("[INF] Completed at " + ("preview" if preview else "sync"))
elif args[:1] == ["logs"]:
    name = args[-1]
    for i in range(1, 41):
        level = "WARN" if i % 13 == 0 else "INFO"
        print(f"2026-11-10T06:{{i:02d}}:00.000000000Z [{{level}}] {{name}}: e2e log line {{i}}")
else:
    sys.exit("fake docker: unsupported " + " ".join(args))
"""

FAKE_TAILSCALE = """#!{python}
import json, sys
if sys.argv[1:3] == ["status", "--json"]:
    print(json.dumps({{
        "BackendState": "Running", "Version": "1.90.0",
        "Self": {{"HostName": "saltbox", "DNSName": "saltbox.tail-e2e.ts.net.",
                  "TailscaleIPs": ["100.64.0.5", "fd7a:115c:a1e0::5"],
                  "Online": True, "UserID": 1}},
        "User": {{"1": {{"LoginName": "owner@example.com"}}}},
        "Peer": {{"phone": {{"Online": True}}, "laptop": {{"Online": False}}}},
        "CurrentTailnet": {{"MagicDNSEnabled": True}},
    }}))
elif sys.argv[1:4] == ["serve", "status", "--json"]:
    try:
        target = open({serve!r}).read().strip()
    except OSError:
        target = ""
    web = {{"saltbox.tail-e2e.ts.net:8443": {{"Handlers": {{"/": {{"Proxy": target}}}}}}}}
    print(json.dumps({{"Web": web}} if target else {{}}))
elif sys.argv[1:2] == ["serve"] and sys.argv[-1] == "off":
    import os
    if os.path.exists({serve!r}):
        os.remove({serve!r})
elif sys.argv[1:2] == ["serve"]:
    open({serve!r}, "w").write(sys.argv[-1])
else:
    sys.exit("fake tailscale: unsupported " + " ".join(sys.argv[1:]))
"""

FAKE_APPRISE = """#!{python}
import sys
args = sys.argv[1:]
url = open(args[args.index("--config") + 1]).read().strip()
with open({log!r}, "a") as log:
    log.write(url + " | " + args[args.index("-t") + 1] + "\\n")
"""

FAKE_SB = """#!/bin/sh
if [ "$1" = update ]; then exec @PYTHON@ @FAKE_UPDATE@ "$@"; fi
echo "Executing Ansible playbook with command: ansible-playbook saltbox.yml --tags $2"
echo
echo "PLAY [localhost] ***"
sleep 1
case "$*" in
  *e2e-slow*)
    echo "TASK [e2e-slow : wait] ***"
    sleep 60;;
  *e2e-fail*)
    echo 'fatal: [localhost]: FAILED! => {"msg": "e2e failure"}'
    echo "PLAY RECAP ***"
    echo "localhost : ok=3 changed=0 unreachable=0 failed=1"
    exit 2;;
esac
echo "TASK [$2 : Create Docker container] ***"
echo "changed: [localhost]"
echo "PLAY RECAP ***"
echo "localhost : ok=12 changed=1 unreachable=0 failed=0"
"""


def registry_transport(method: str, url: str, headers: dict[str, str], body: Any) -> Response:
    """A registry with no auth: every image is current except UPDATED_IMAGES."""
    path = url.split("/v2/", 1)[1]
    repository = path.split("/manifests/", 1)[0]
    name = repository.rsplit("/", 1)[-1]
    digest = "sha256:newer" if repository in UPDATED_IMAGES else f"sha256:{name}"
    return Response(200, b"", {"docker-content-digest": digest})


def _json(data: Any) -> Response:
    return Response(200, json.dumps(data).encode())


def _drive(name: str, model: str, capacity: float, **extra: Any) -> dict[str, Any]:
    device = {
        "wwn": f"0x5000c500{name}",
        "device_name": name,
        "model_name": model,
        "serial_number": f"E2E{name.upper()}",
        "capacity": int(capacity * 1e12),
        "rotational_speed": 7200,
        "device_protocol": "ATA",
        "device_status": 0,
        "scrutiny_uuid": f"uuid-{name}",
        **extra,
    }
    smart = {"collector_date": "2026-11-13T05:00:00Z", "temp": 34, "power_on_hours": 26280}
    return {"device": device, "smart": smart}


# Three drives as Scrutiny reports them: one is past Scrutiny's failure thresholds.
SCRUTINY_DRIVES = {
    "a": _drive("sda", "ST8000VN004-2M2101", 8),
    "b": _drive("sdb", "WDC WD80EFAX-68KNBN0", 8, device_status=2),
    "c": _drive("nvme0", "Samsung SSD 980 PRO", 1, device_protocol="NVMe", rotational_speed=0),
}

SCRUTINY_FAILING = {
    "success": True,
    "data": {
        "smart_results": [
            {
                "date": "2026-11-13T05:00:00Z",
                "attrs": {
                    "5": {
                        "attribute_id": 5,
                        "raw_value": 24,
                        "status": 4,
                        "status_reason": "Observed Failure Rate for Critical Attribute is "
                        "greater than 10%",
                        "failure_rate": 0.14,
                    },
                    "9": {"attribute_id": 9, "raw_value": 26280, "status": 0},
                },
            }
        ]
    },
    "metadata": {
        "5": {
            "display_name": "Reallocated Sectors Count",
            "critical": True,
            "description": "Count of reallocated sectors.",
        }
    },
}

# qBittorrent as it ships: no seeding limit, so finished torrents never stop.
QBIT_PREFERENCES: dict[str, Any] = {
    "max_ratio_enabled": False,
    "max_ratio": -1,
    "max_seeding_time_enabled": False,
    "max_seeding_time": -1,
    "max_ratio_act": 0,
}
FINISHED_TORRENTS = [
    {"state": "uploading", "size": 4 * 1024**3, "category": "sonarr", "seeding_time": 86400 * 3},
    {"state": "stalledUP", "size": 10 * 1024**3, "category": "radarr", "seeding_time": 86400 * 40},
    {"state": "stalledUP", "size": 2 * 1024**3, "category": "sonarr", "seeding_time": 86400},
    {"state": "stoppedUP", "size": 6 * 1024**3, "category": "", "seeding_time": 86400 * 9},
]


def apps_transport(method: str, url: str, headers: dict[str, str], body: Any) -> Response:
    """Just enough of qBittorrent, Plex, Sonarr and Radarr for the media cards."""
    import datetime as dt
    from urllib.parse import parse_qsl, urlsplit

    parts = urlsplit(url)
    host, path = parts.hostname or "", parts.path
    if path == "/api/v2/auth/login":
        ok = b"password12345678" in (body or b"")
        return Response(204 if ok else 200, b"" if ok else b"Fails.", {"set-cookie": "SID=e2e"})
    if path == "/api/v2/transfer/info":
        return _json({"dl_info_speed": 12_582_912, "up_info_speed": 524_288})
    if path == "/api/v2/torrents/info":
        if "filter=completed" in parts.query:
            return _json(FINISHED_TORRENTS)
        return _json(
            [{"name": "Some.Show.S03E04.1080p.WEB", "progress": 0.62, "eta": 300, "dlspeed": 8e6}]
        )
    if path == "/api/device/uuid-sdb/details":  # Scrutiny, about the failing drive
        return _json(SCRUTINY_FAILING)
    if path == "/api/summary":  # Scrutiny's dashboard
        return _json({"success": True, "data": {"summary": SCRUTINY_DRIVES}})
    if path == "/api/v2/app/preferences":
        return _json(QBIT_PREFERENCES)
    if path == "/api/v2/app/setPreferences":
        form = dict(parse_qsl((body or b"").decode()))
        QBIT_PREFERENCES.update(json.loads(form["json"]))
        return Response(200, b"")
    if path == "/status/sessions":
        return _json(
            {
                "MediaContainer": {
                    "Metadata": [
                        {
                            "type": "episode",
                            "grandparentTitle": "Some Show",
                            "parentIndex": 3,
                            "index": 2,
                            "title": "The One Before",
                            "duration": 2_700_000,
                            "viewOffset": 1_350_000,
                            "User": {"title": "seed"},
                            "Player": {"title": "Living Room TV", "state": "playing"},
                        }
                    ]
                }
            }
        )
    if path == "/api/v3/calendar":
        soon = (dt.datetime.now(dt.UTC) + dt.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        if host == "sonarr":
            return _json(
                [
                    {
                        "series": {"title": "Some Show"},
                        "seasonNumber": 3,
                        "episodeNumber": 5,
                        "title": "The Next One",
                        "airDateUtc": soon,
                        "hasFile": False,
                    }
                ]
            )
        return _json([{"title": "A Film", "year": 2026, "digitalRelease": soon, "hasFile": False}])
    return Response(404, b"not part of the e2e box")


def e2e_files(container: str, path: str) -> str:
    return {"/tmp/gluetun/ip": "185.98.171.144", "/tmp/gluetun/forwarded_port": "51413"}.get(
        path, ""
    )


def _git(cwd: Path, *args: str) -> None:
    env = dict(
        os.environ,
        GIT_AUTHOR_NAME="e2e",
        GIT_AUTHOR_EMAIL="e2e@example.invalid",
        GIT_COMMITTER_NAME="e2e",
        GIT_COMMITTER_EMAIL="e2e@example.invalid",
    )
    subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True)


def build_box(root: Path) -> Layout:
    repo = root / "saltbox"
    repo.mkdir(parents=True)
    for name in ("schema", "defaults"):
        shutil.copytree(REPO_ROOT / name, repo / name)
    shutil.copy(REPO_ROOT / "saltbox.yml", repo / "saltbox.yml")
    for defaults in (REPO_ROOT / "roles").glob("*/defaults/main.yml"):
        target = repo / defaults.relative_to(REPO_ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(defaults, target)
    (repo / "inventories" / "host_vars").mkdir(parents=True)
    (repo / "inventories" / "host_vars" / "localhost.yml").write_text(
        "---\n"
        "gluetun_role_docker_envs_custom:\n"
        "  VPN_SERVICE_PROVIDER: protonvpn\n"
        f'  WIREGUARD_PRIVATE_KEY: "{SECRET_KEY}"\n'
    )
    for name in ("accounts", "settings"):
        text = (repo / "defaults" / f"{name}.yml.default").read_text()
        # This box keeps its media on its own disks: no cloud remotes.
        text = text.replace("rclone:\n  enabled: yes", "rclone:\n  enabled: no")
        (repo / f"{name}.yml").write_text(text.replace("testsaltbox.ml", DOMAIN))
    backups = root / "backups"
    backups.mkdir()
    (backups / "saltbox_backup.tar").write_bytes(b"0" * 4096)
    (repo / "backup_config.yml").write_text(
        (repo / "defaults" / "backup_config.yml.default")
        .read_text()
        .replace("/home/{{ user.name }}/Backups/Saltbox", str(backups))
    )

    # A checkout one commit behind the branch it tracks.
    upstream = root / "upstream.git"
    _git(root, "init", "-q", "--bare", "-b", "master", str(upstream))
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "box")
    _git(repo, "remote", "add", "origin", str(upstream))
    _git(repo, "push", "-q", "-u", "origin", "master")
    newer = root / "newer"
    _git(root, "clone", "-q", str(upstream), str(newer))
    (newer / "CHANGELOG").write_text("newer\n")
    _git(newer, "add", "CHANGELOG")
    _git(newer, "commit", "-qm", "newer")
    _git(newer, "push", "-q", "origin", "master")

    appdata = root / "opt"
    (appdata / "saltbox").mkdir(parents=True)  # the facts folder an install leaves
    for container in CONTAINERS:
        if container["Name"][1:] not in NO_APPDATA:
            (appdata / container["Name"][1:]).mkdir(parents=True)
    for name in ("sonarr", "radarr"):
        (appdata / name / "config.xml").write_text(
            f"<Config><ApiKey>{name}e2eapikey0123456789abcdef</ApiKey></Config>"
        )
    (appdata / "saltbox" / "plex.ini").write_text(
        "[plex]\nclient_identifier = e2e\ntoken = e2eplextoken12345\n"
    )

    bin_dir = root / "bin"
    bin_dir.mkdir()
    inspect = root / "inspect.json"
    inspect.write_text(json.dumps(CONTAINERS))
    docker = bin_dir / "docker"
    (root / "mnt" / "local").mkdir(parents=True)
    docker.write_text(
        FAKE_DOCKER.format(
            python=sys.executable,
            inspect=str(inspect),
            anchor=str(root / "mnt" / "local" / "mounted.bin"),
            merged=str(root / "mnt" / "unionfs" / "mounted.bin"),
        )
    )
    sb = bin_dir / "sb"
    fake_update = Path(__file__).with_name("fake_sb_update.py")
    sb.write_text(
        FAKE_SB.replace("@PYTHON@", sys.executable).replace("@FAKE_UPDATE@", str(fake_update))
    )
    tailscale = bin_dir / "tailscale"
    tailscale.write_text(
        FAKE_TAILSCALE.format(python=sys.executable, serve=str(root / "tailscale-serve"))
    )
    apprise = bin_dir / "apprise"
    apprise.write_text(FAKE_APPRISE.format(python=sys.executable, log=str(root / "apprise.log")))
    for path in (docker, sb, tailscale, apprise):
        path.chmod(0o755)
    os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
    return Layout(repo=repo, appdata=appdata, sb_binary=sb, state_dir=root / "state")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--token", default="e2e-token")
    parser.add_argument("--web", default=str(WEB_DIST))
    args = parser.parse_args(argv)

    import uvicorn

    with tempfile.TemporaryDirectory(prefix="saltbox-e2e-") as tmp:
        layout = build_box(Path(tmp))
        services = Services(
            layout,
            token=args.token,
            web_dir=Path(args.web),
            tailscale_socket=str(Path(tmp) / "tailscale.sock"),
        )
        # Ubuntu has updated the kernel and wants a restart; "restarting" leaves a note instead.
        flag = Path(tmp) / "reboot-required"
        flag.write_text("*** System restart required ***\n")
        flag.with_name("reboot-required.pkgs").write_text("linux-image-6.8.0-55-generic\nlibc6\n")
        services.reboot_flag = flag
        services.reboot = lambda: (Path(tmp) / "rebooted").write_text("yes\n")
        services.uptime = lambda: 5 * 86400  # not just booted, whatever the test machine is
        services.storage_roots = (Path(tmp) / "mnt" / "unionfs", Path(tmp) / "mnt" / "local")
        services.app_setup_factory = lambda layout: AppSetup(
            layout,
            transport=apps_transport,
            resolver=lambda name: name,
            container_reader=e2e_files,
            log_reader=lambda name: "",
        )
        registry = Registry(transport=registry_transport)
        services.updates = UpdateService(
            layout, checker=lambda containers: check_updates(containers, registry=registry)
        )
        app = create_app(services=services)
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", ws="websockets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
