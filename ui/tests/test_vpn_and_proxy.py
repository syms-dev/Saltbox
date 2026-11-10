"""qBittorrent inside Gluetun is recognised, and Prowlarr gets FlareSolverr as its proxy."""

from __future__ import annotations

import json
from urllib.parse import urlsplit

from saltbox_ui.appsetup.discover import Discovery, Service
from saltbox_ui.appsetup.http import Response
from saltbox_ui.appsetup.tasks import SetupContext, prowlarr_flaresolverr_task
from saltbox_ui.state.containers import list_containers_cli, name_network_modes

GLUETUN_ID = "3f2a9c41b7d0" + "e" * 52


def test_docker_ids_in_network_modes_become_names() -> None:
    inspect = [
        {
            "Id": GLUETUN_ID,
            "Name": "/gluetun",
            "Config": {"Labels": {}},
            "State": {"Status": "running"},
            "HostConfig": {"NetworkMode": "saltbox"},
        },
        {
            "Id": "a" * 64,
            "Name": "/qbittorrent",
            "Config": {"Labels": {}},
            "State": {"Status": "running"},
            "HostConfig": {"NetworkMode": f"container:{GLUETUN_ID}"},
        },
        {
            "Id": "b" * 64,
            "Name": "/sonarr",
            "Config": {"Labels": {}},
            "State": {"Status": "running"},
            "HostConfig": {"NetworkMode": "container:gone0000"},
        },
    ]

    def docker(args):
        if args[1] == "ps":
            return 0, "\n".join(i["Id"] for i in inspect)
        return 0, json.dumps(inspect)

    records = {c["name"]: c for c in list_containers_cli(docker)}
    assert records["qbittorrent"]["network_mode"] == "container:gluetun"
    assert records["sonarr"]["network_mode"] == "container:gone0000"  # unknown stays as it was
    assert (
        name_network_modes([{"id": "x", "name": "n", "network_mode": "host"}])[0]["network_mode"]
        == "host"
    )


class FakeProwlarr:
    def __init__(self) -> None:
        self.tags: list[dict] = []
        self.proxies: list[dict] = []
        self.indexers = [{"name": "ExtraTorrent", "tags": []}, {"name": "1337x", "tags": []}]

    def __call__(self, method, url, headers, body):
        assert headers.get("X-Api-Key") == "prowlarrkey"
        path = urlsplit(url).path.removeprefix("/api/v1")
        data = json.loads(body) if body else None
        if (method, path) == ("GET", "/tag"):
            return _json(self.tags)
        if (method, path) == ("POST", "/tag"):
            self.tags.append({"id": 7, "label": data["label"]})
            return _json(self.tags[-1])
        if (method, path) == ("GET", "/indexerProxy/schema"):
            return _json(
                [
                    {
                        "implementation": "FlareSolverr",
                        "fields": [
                            {"name": "host", "value": "http://localhost:8191/"},
                            {"name": "requestTimeout", "value": 30},
                        ],
                    }
                ]
            )
        if (method, path) == ("GET", "/indexerProxy"):
            return _json(self.proxies)
        if (method, path) == ("POST", "/indexerProxy"):
            self.proxies.append(data)
            return _json(data)
        if (method, path) == ("GET", "/indexer"):
            return _json(self.indexers)
        return Response(404, b"")


def _json(data) -> Response:
    return Response(200, json.dumps(data).encode())


def test_prowlarr_gets_flaresolverr_as_its_proxy() -> None:
    prowlarr = Service("prowlarr", "prowlarr", 9696, True, api_key="prowlarrkey", host="prowlarr")
    solver = Service("flaresolverr", "flaresolverr", 8191, True, host="flaresolverr")
    fake = FakeProwlarr()
    ctx = SetupContext(Discovery(), transport=fake)
    task = prowlarr_flaresolverr_task(ctx, prowlarr, solver)
    assert task.refresh().status == "todo"
    task.apply()
    proxy = fake.proxies[0]
    assert proxy["name"] == "FlareSolverr" and proxy["tags"] == [7]
    assert {f["name"]: f["value"] for f in proxy["fields"]} == {
        "host": "http://flaresolverr:8191/",
        "requestTimeout": 60,
    }
    task.refresh()
    assert task.status == "done" and "No indexer uses it yet" in task.detail
    fake.indexers[0]["tags"] = [7]
    assert "Indexers using it: ExtraTorrent." in task.refresh().detail
    task.apply()  # a second run reuses the tag
    assert len(fake.tags) == 1


def test_running_containers_count_as_installed(monkeypatch) -> None:
    from saltbox_ui import appsetup
    from saltbox_ui.state import containers

    found = Discovery(
        services={"flaresolverr": [Service("flaresolverr", "flaresolverr", 8191, False)]}
    )
    monkeypatch.setattr(
        containers, "list_containers", lambda: [{"name": "flaresolverr", "status": "running"}]
    )
    appsetup._mark_running(found)
    assert found.first("flaresolverr") is not None
