from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from saltbox_ui.appsetup.http import Response
from saltbox_ui.daemon import Services, create_app
from saltbox_ui.daemon import routes as daemon_routes
from saltbox_ui.daemon.updates import UpdateService
from saltbox_ui.layout import Layout
from saltbox_ui.state.containers import web_urls
from saltbox_ui.state.repos import RepoStatus
from saltbox_ui.state.updates import (
    ImageStatus,
    Registry,
    check_updates,
    local_digests,
    parse_ref,
)


# -- image references and addresses ---------------------------------------------
@pytest.mark.parametrize(
    ("image", "registry", "repository", "tag"),
    [
        ("nginx", "registry-1.docker.io", "library/nginx", "latest"),
        ("hotio/sonarr:release", "registry-1.docker.io", "hotio/sonarr", "release"),
        ("ghcr.io/hotio/sonarr:release", "ghcr.io", "hotio/sonarr", "release"),
        ("lscr.io/linuxserver/plex", "lscr.io", "linuxserver/plex", "latest"),
        ("localhost:5000/me/app:1", "localhost:5000", "me/app", "1"),
    ],
)
def test_parse_ref(image, registry, repository, tag) -> None:
    ref = parse_ref(image)
    assert (ref.registry, ref.repository, ref.tag) == (registry, repository, tag)


def test_pinned_images_are_not_checked() -> None:
    assert parse_ref("ghcr.io/a/b@sha256:abc") is None
    assert parse_ref("") is None


def test_web_urls_prefer_the_main_router() -> None:
    labels = {
        "traefik.http.routers.sonarr-http.rule": "Host(`sonarr.example.com`)",
        "traefik.http.routers.sonarr-api.rule": "Host(`sonarr.example.com`) && PathPrefix(`/api`)",
        "traefik.http.routers.sonarr.rule": "(Host(`t.example.com`) || Host(`sonarr.example.com`))",
        "traefik.enable": "true",
    }
    assert web_urls("sonarr", labels) == ["https://t.example.com", "https://sonarr.example.com"]
    assert web_urls("gluetun", {}) == []


# -- registry --------------------------------------------------------------------
class FakeRegistry:
    """Docker Hub style: anonymous HEAD is challenged, a pull token unlocks it."""

    def __init__(self, digests: dict[str, str]):
        self.digests = digests
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url))
        if url.startswith("https://auth.example/token"):
            return Response(200, json.dumps({"token": "t0k"}).encode(), {})
        if headers.get("Authorization") != "Bearer t0k":
            challenge = 'Bearer realm="https://auth.example/token",service="registry.example"'
            return Response(401, b"", {"www-authenticate": challenge})
        key = url.split("/v2/", 1)[1]
        if key not in self.digests:
            return Response(404, b"", {})
        return Response(200, b"", {"docker-content-digest": self.digests[key]})


def test_registry_token_flow_and_cache() -> None:
    fake = FakeRegistry({"hotio/sonarr/manifests/release": "sha256:new"})
    registry = Registry(fake)
    ref = parse_ref("ghcr.io/hotio/sonarr:release")
    assert registry.digest(ref) == "sha256:new"
    assert registry.digest(ref) == "sha256:new"
    token_calls = [url for _, url in fake.calls if "auth.example" in url]
    assert len(token_calls) == 1  # token reused
    assert "scope=repository%3Ahotio%2Fsonarr%3Apull" in token_calls[0]
    assert all(method in ("HEAD", "GET") for method, _ in fake.calls)


def test_local_digests_and_check_updates() -> None:
    inspected = [
        {"Id": "sha256:img1", "RepoDigests": ["ghcr.io/hotio/sonarr@sha256:old"]},
        {"Id": "sha256:img2", "RepoDigests": ["ghcr.io/hotio/radarr@sha256:same"]},
        {"Id": "sha256:img3", "RepoDigests": []},
    ]

    def runner(args):
        assert args[:3] == ["docker", "image", "inspect"]
        return 0, json.dumps(inspected)

    assert local_digests(["sha256:img1"], runner)["sha256:img1"] == ["sha256:old"]
    containers = [
        {"name": "sonarr", "image_ref": "ghcr.io/hotio/sonarr:release", "image_id": "sha256:img1"},
        {
            "name": "sonarr4k",
            "image_ref": "ghcr.io/hotio/sonarr:release",
            "image_id": "sha256:img1",
        },
        {"name": "radarr", "image_ref": "ghcr.io/hotio/radarr:release", "image_id": "sha256:img2"},
        {"name": "local", "image_ref": "ghcr.io/me/local:latest", "image_id": "sha256:img3"},
        {"name": "pinned", "image_ref": "ghcr.io/a/b@sha256:x", "image_id": "sha256:img2"},
        {"name": "gone", "image_ref": "ghcr.io/me/gone:latest", "image_id": "sha256:img2"},
    ]
    fake = FakeRegistry(
        {
            "hotio/sonarr/manifests/release": "sha256:new",
            "hotio/radarr/manifests/release": "sha256:same",
            "me/local/manifests/latest": "sha256:whatever",
        }
    )
    result = check_updates(containers, registry=Registry(fake), runner=runner)
    sonarr = result["ghcr.io/hotio/sonarr:release"]
    assert sonarr.status == "update" and sonarr.containers == ["sonarr", "sonarr4k"]
    assert result["ghcr.io/hotio/radarr:release"].status == "current"
    assert result["ghcr.io/me/local:latest"].status == "unknown"
    assert result["ghcr.io/a/b@sha256:x"].detail == "pinned to a digest"
    assert "HTTP 404" in result["ghcr.io/me/gone:latest"].detail


def test_check_updates_without_docker() -> None:
    containers = [{"name": "sonarr", "image_ref": "a/b:c", "image_id": "sha256:1"}]
    result = check_updates(
        containers, registry=Registry(FakeRegistry({})), runner=lambda a: (1, "no daemon")
    )
    assert result["a/b:c"].status == "unknown"
    assert "no daemon" in result["a/b:c"].detail


# -- the daemon's cached service -------------------------------------------------
def test_update_service_cache_and_staleness(scratch_layout: Layout) -> None:
    clock = [1000.0]
    calls = []

    def checker(containers):
        calls.append(len(containers))
        return {"img": ImageStatus("img", "update", containers=["sonarr"])}

    service = UpdateService(
        scratch_layout,
        containers=lambda: [{"name": "sonarr"}],
        checker=checker,
        clock=lambda: clock[0],
        max_age=60,
    )
    assert service.cached()["checked_at"] is None
    service.ensure_fresh()
    service.wait()
    assert calls == [1]
    assert service.status_by_container()["sonarr"]["status"] == "update"
    service.ensure_fresh()
    service.wait()
    assert calls == [1]  # still fresh
    clock[0] += 120
    service.ensure_fresh()
    service.wait()
    assert calls == [1, 1]


def test_cache_from_an_older_daemon_is_refreshed(scratch_layout: Layout) -> None:
    scratch_layout.state_dir.mkdir(parents=True, exist_ok=True)
    (scratch_layout.state_dir / "updates.json").write_text(
        json.dumps({"checked_at": 1000.0, "images": {}})
    )
    checks = []
    service = UpdateService(
        scratch_layout,
        containers=lambda: [],
        checker=lambda c: (checks.append(1), {})[1],
        repos=lambda: [],
        clock=lambda: 1001.0,
    )
    service.ensure_fresh()
    service.wait()
    assert checks == [1]
    service.ensure_fresh()
    service.wait()
    assert checks == [1]


def test_update_service_keeps_last_result_on_error(scratch_layout: Layout) -> None:
    service = UpdateService(
        scratch_layout,
        containers=lambda: [],
        checker=lambda c: {"img": ImageStatus("img", "current", containers=["plex"])},
    )
    service.refresh(wait=True)

    def broken():
        raise RuntimeError("docker is down")

    service.containers = broken
    service.refresh(wait=True)
    data = service.cached()
    assert data["error"] == "images: docker is down"
    assert data["images"]["img"]["status"] == "current"


# -- routes ----------------------------------------------------------------------
CONTAINERS = [
    {
        "name": "sonarr",
        "status": "running",
        "health": "healthy",
        "managed": True,
        "image_ref": "ghcr.io/hotio/sonarr:release",
        "network_mode": "saltbox",
        "urls": ["https://sonarr.example.com"],
    },
    {
        "name": "gluetun",
        "status": "running",
        "health": "healthy",
        "managed": True,
        "image_ref": "qmcgaw/gluetun:latest",
        "network_mode": "saltbox",
        "urls": [],
    },
    {
        "name": "qbittorrent",
        "status": "running",
        "health": None,
        "managed": True,
        "image_ref": "saltydk/qbittorrent:latest",
        "network_mode": "container:gluetun",
        "urls": ["https://qbittorrent.example.com"],
    },
]


@pytest.fixture
def client(scratch_layout: Layout, fake_sb: Path, monkeypatch: pytest.MonkeyPatch):
    for name in ("sonarr", "gluetun", "qbittorrent", "radarr"):
        (scratch_layout.appdata / name).mkdir(parents=True)
    monkeypatch.setattr(daemon_routes, "_containers_or_none", lambda: [dict(c) for c in CONTAINERS])
    services = Services(scratch_layout)
    services.updates = UpdateService(
        scratch_layout,
        containers=lambda: CONTAINERS,
        checker=lambda containers: {
            "ghcr.io/hotio/sonarr:release": ImageStatus(
                "ghcr.io/hotio/sonarr:release", "update", containers=["sonarr"]
            ),
            "qmcgaw/gluetun:latest": ImageStatus(
                "qmcgaw/gluetun:latest", "update", containers=["gluetun"]
            ),
            "saltydk/qbittorrent:latest": ImageStatus(
                "saltydk/qbittorrent:latest", "current", containers=["qbittorrent"]
            ),
        },
        repos=lambda: [
            RepoStatus(
                "saltbox", "/srv/git/saltbox", "main", "1111111", "2222222", status="update"
            ),
            RepoStatus("sandbox", "/opt/sandbox", "master", "3333333", "3333333", status="current"),
        ],
    )
    services.updates.refresh(wait=True)
    return TestClient(create_app(services=services)), services


def wait_job(client: TestClient, job_id: str) -> dict:
    import time

    for _ in range(200):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] not in ("pending", "running"):
            return job
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_apps_carry_links_and_update_status(client) -> None:
    http, _ = client
    apps = {a["role"]: a for a in http.get("/api/apps").json()}
    sonarr = apps["sonarr"]
    assert sonarr["urls"] == ["https://sonarr.example.com"]
    assert sonarr["update_available"] is True
    assert sonarr["containers"][0]["update"] == "update"
    assert apps["qbittorrent"]["update_available"] is False
    assert apps["radarr"]["containers"] == [] and apps["radarr"]["urls"] == []
    detail = http.get("/api/apps/saltbox/sonarr").json()
    assert detail["urls"] == ["https://sonarr.example.com"] and detail["update_available"]
    overview = http.get("/api/overview").json()
    assert overview["updates"]["pending"] == ["gluetun", "sonarr"]


def test_update_one_app(client) -> None:
    http, _ = client
    job = http.post("/api/apps/saltbox/sonarr/update").json()
    assert job["tags"] == ["sonarr"]
    assert wait_job(http, job["id"])["status"] == "succeeded"


def test_updating_gluetun_rebuilds_what_runs_inside_it(client) -> None:
    http, _ = client
    job = http.post("/api/apps/saltbox/gluetun/update").json()
    assert job["tags"] == ["gluetun", "qbittorrent"]
    wait_job(http, job["id"])


def test_update_all_and_recheck_after_job(client) -> None:
    http, services = client
    checks = []
    original = services.updates.checker
    services.updates.checker = lambda containers: (checks.append(1), original(containers))[1]
    job = http.post("/api/updates/apply").json()
    assert set(job["tags"]) == {"sonarr", "gluetun", "qbittorrent"}
    wait_job(http, job["id"])
    services.updates.wait(5)
    assert checks  # the finished install triggered a fresh check
    assert http.post("/api/updates/check").status_code == 202
    assert http.get("/api/updates").json()["images"]


def test_saltbox_checkouts_are_reported_and_updated_with_sb_update(client) -> None:
    http, services = client
    assert http.get("/api/overview").json()["updates"]["saltbox"] == ["saltbox"]
    repos = http.get("/api/updates").json()["repos"]
    assert [(r["name"], r["status"]) for r in repos] == [
        ("saltbox", "update"),
        ("sandbox", "current"),
    ]
    checks = []
    services.updates.repos = lambda: (checks.append(1), [])[1]
    job = http.post("/api/saltbox/update").json()
    assert job["kind"] == "update" and job["command"][1] == "update"
    assert wait_job(http, job["id"])["status"] == "succeeded"
    services.updates.wait(5)
    assert checks  # sb update triggered a fresh check
    assert http.get("/api/overview").json()["updates"]["saltbox"] == []


# -- container actions and logs ---------------------------------------------------
def test_container_actions_and_logs(client, monkeypatch: pytest.MonkeyPatch) -> None:
    from saltbox_ui.state import containers as containers_module

    http, _ = client
    calls: list[list[str]] = []

    def docker(args):
        calls.append(args)
        if args[1] == "logs":
            return 0, "2026-11-10T01:00:00Z started\n2026-11-10T01:00:01Z ready\n"
        return 0, ""

    monkeypatch.setattr(containers_module, "_run_long", docker)
    monkeypatch.setattr(containers_module, "_run_merged", docker)
    restarted = http.post("/api/containers/sonarr/restart")
    assert restarted.status_code == 200
    assert restarted.json()["name"] == "sonarr" and restarted.json()["update"] == "update"
    assert calls[-1] == ["docker", "restart", "--", "sonarr"]
    logs = http.get("/api/containers/sonarr/logs?tail=5").json()
    assert logs["lines"][-1].endswith("ready")
    assert calls[-1] == ["docker", "logs", "--tail", "5", "--timestamps", "--", "sonarr"]
    assert http.get("/api/containers/sonarr/logs?tail=999999").status_code == 200
    assert calls[-1][3] == "2000"  # capped


def test_container_actions_refuse_unknown_names_and_actions(client, monkeypatch) -> None:
    from saltbox_ui.state import containers as containers_module

    http, _ = client
    monkeypatch.setattr(containers_module, "_run_long", lambda args: (0, ""))
    assert http.post("/api/containers/sonarr/remove").status_code == 404
    assert http.post("/api/containers/not-ours/restart").status_code == 404
    assert http.get("/api/containers/not-ours/logs").status_code == 404
    assert http.post("/api/containers/-v/stop").status_code == 404


def test_container_action_failure_is_reported(client, monkeypatch) -> None:
    from saltbox_ui.state import containers as containers_module

    http, _ = client
    monkeypatch.setattr(containers_module, "_run_long", lambda args: (1, "is not running"))
    response = http.post("/api/containers/sonarr/stop")
    assert response.status_code == 502 and "is not running" in response.json()["detail"]


# -- containers that are not the main container of a listed app ------------------------------
INFRASTRUCTURE = [
    {
        "name": "traefik",
        "status": "running",
        "health": None,
        "managed": True,
        "image_ref": "traefik:v3",
        "network_mode": "saltbox",
        "urls": [],
        "labels": {},
    },
    {
        "name": "authelia",
        "status": "running",
        "health": "healthy",
        "managed": True,
        "image_ref": "authelia/authelia:latest",
        "network_mode": "saltbox",
        "urls": ["https://login.example.com"],
        # Saltbox records what a container needs started first; the Authelia role
        # creates its own Redis under this name.
        "labels": {"com.github.saltbox.depends_on": "authelia-redis,lldap"},
    },
    {
        "name": "authelia-redis",
        "status": "running",
        "health": None,
        "managed": True,
        "image_ref": "redis:alpine",
        "network_mode": "saltbox",
        "urls": [],
        "labels": {},
    },
    {
        "name": "sonarr",
        "status": "running",
        "health": None,
        "managed": True,
        "image_ref": "ghcr.io/hotio/sonarr:release",
        "network_mode": "saltbox",
        "urls": [],
        "labels": {"com.github.saltbox.depends_on": ""},
    },
    {
        "name": "watchdog",  # started by hand, not by a Saltbox role
        "status": "running",
        "health": None,
        "managed": False,
        "image_ref": "example/watchdog:latest",
        "network_mode": "bridge",
        "urls": [],
        "labels": {},
    },
]


@pytest.fixture
def infrastructure(scratch_layout: Layout, fake_sb: Path, monkeypatch: pytest.MonkeyPatch):
    """A box where the only new images are for Traefik, Authelia's Redis and a stray container."""
    (scratch_layout.appdata / "sonarr").mkdir(parents=True)
    monkeypatch.setattr(
        daemon_routes, "_containers_or_none", lambda: [dict(c) for c in INFRASTRUCTURE]
    )
    services = Services(scratch_layout)
    services.updates = UpdateService(
        scratch_layout,
        containers=lambda: INFRASTRUCTURE,
        checker=lambda containers: {
            "traefik:v3": ImageStatus("traefik:v3", "update", containers=["traefik"]),
            "redis:alpine": ImageStatus("redis:alpine", "update", containers=["authelia-redis"]),
            "example/watchdog:latest": ImageStatus(
                "example/watchdog:latest", "update", containers=["watchdog"]
            ),
            "authelia/authelia:latest": ImageStatus(
                "authelia/authelia:latest", "current", containers=["authelia"]
            ),
        },
        repos=lambda: [],
    )
    services.updates.refresh(wait=True)
    return TestClient(create_app(services=services)), services


def test_updates_for_core_and_companion_containers_are_counted_the_same_everywhere(
    infrastructure,
) -> None:
    http, _ = infrastructure
    updates = http.get("/api/overview").json()["updates"]
    assert updates["pending"] == ["authelia-redis", "traefik", "watchdog"]
    assert [(a["role"], a["title"], a["containers"], a["core"]) for a in updates["apps"]] == [
        ("authelia", "Authelia", ["authelia-redis"], True),
        ("traefik", "Traefik Proxy", ["traefik"], True),
    ]
    assert updates["unknown"] == ["watchdog"]

    apps = {a["role"]: a for a in http.get("/api/apps").json()}
    # Running infrastructure is in the list, marked as core, with what its role brought along.
    assert apps["traefik"]["core"] is True and apps["traefik"]["installed"] is True
    assert [c["name"] for c in apps["authelia"]["containers"]] == ["authelia", "authelia-redis"]
    assert apps["sonarr"]["core"] is False
    assert sorted(role for role, app in apps.items() if app["update_available"]) == [
        "authelia",
        "traefik",
    ]
    # Roles that are not apps and run nothing stay out: no databases, no tools.
    assert "redis" not in apps and "postgres" not in apps and "docker" not in apps
    detail = http.get("/api/apps/saltbox/authelia").json()
    assert detail["update_available"] is True
    assert [c["update"] for c in detail["containers"]] == ["current", "update"]


def test_update_all_reaches_core_and_companion_containers(infrastructure) -> None:
    http, _ = infrastructure
    job = http.post("/api/updates/apply").json()
    assert job["tags"] == ["authelia", "traefik"]
    wait_job(http, job["id"])


def test_nightly_maintenance_uses_the_same_list_and_honours_exclusions(infrastructure) -> None:
    _, services = infrastructure
    services.automation.save({"maintenance": {"enabled": True, "exclude": ["traefik"]}})
    record = services.automation.run_maintenance(wait_seconds=30)
    assert [step["what"] for step in record["steps"]] == ["update Authelia"]
    assert record["status"] == "succeeded"
