from __future__ import annotations

import stat
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from saltbox_ui.daemon import Services, create_app
from saltbox_ui.daemon.install import route_settings, systemd_unit, traefik_route, write_route
from saltbox_ui.layout import Layout
from saltbox_ui.yamlio import load_plain


@pytest.fixture
def client(scratch_layout: Layout, fake_sb: Path) -> TestClient:
    app = create_app(services=Services(scratch_layout))
    return TestClient(app)


@pytest.fixture
def slow_sb(tmp_path: Path) -> Path:
    """An sb that prints a line every 50 ms for a while, for stream and cancel tests."""
    path = tmp_path / "bin" / "sb"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/bin/sh\n"
        'echo "sb args: $*"\n'
        'for i in $(seq 1 ${FAKE_SB_LINES:-6}); do echo "line $i"; sleep 0.05; done\n'
        'exit "${FAKE_SB_EXIT:-0}"\n'
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("timed out")


# -- meta, overview, config ------------------------------------------------
def test_meta_and_no_web(client: TestClient) -> None:
    meta = client.get("/api/meta").json()
    assert meta["version"]
    assert meta["web"] is False
    assert "repo" in meta["layout"]
    assert client.get("/").json()["api"] == "/api/docs"


def test_overview_on_fresh_layout(client: TestClient) -> None:
    data = client.get("/api/overview").json()
    assert data["install"]["installed"] is False
    assert data["install"]["configs_present"] is False
    assert data["jobs"]["busy"] is False
    assert isinstance(data["host"]["disks"], list)
    assert "accounts" in data["config_issues"]  # required file missing


def test_config_round_trip(client: TestClient, scratch_layout: Layout) -> None:
    files = {f["name"]: f for f in client.get("/api/config").json()}
    assert files["accounts"]["exists"] is False
    assert files["accounts"]["source"] == "default"

    shown = client.get("/api/config/accounts").json()
    assert "user:" in shown["text"]  # the default is offered when the file is missing
    text = shown["text"].replace("testsaltbox.ml", "example.com")
    saved = client.put("/api/config/accounts", json={"text": text}).json()
    assert scratch_layout.config_file("accounts").exists()
    assert not any(i["message"].startswith("required config file") for i in saved["issues"])

    patched = client.patch(
        "/api/config/accounts", json={"path": "user.email", "value": "me@example.com"}
    ).json()
    assert isinstance(patched["issues"], list)
    assert load_plain(scratch_layout.config_file("accounts"))["user"]["email"] == "me@example.com"

    bad = client.put("/api/config/accounts", json={"text": "user:\n  name: a\nuser:\n  name: b\n"})
    assert bad.status_code == 422
    assert "duplicate" in bad.json()["detail"]
    assert client.put("/api/config/accounts", json={"text": "a: [\n"}).status_code == 422
    assert client.get("/api/config/nope").status_code == 404


def test_validate_all(client: TestClient) -> None:
    results = client.post("/api/config/validate").json()
    assert set(results) >= {"accounts", "settings", "inventory"}


def test_inventory_round_trip(client: TestClient, scratch_layout: Layout) -> None:
    assert client.get("/api/inventory").json()["data"] == {}
    client.put(
        "/api/inventory", json={"text": "---\nsonarr_instances:\n  - sonarr\n  - sonarr4k\n"}
    )
    data = client.get("/api/inventory").json()
    assert data["data"]["sonarr_instances"] == ["sonarr", "sonarr4k"]
    assert data["issues"] == []


# -- apps --------------------------------------------------------------------
def test_apps_and_detail(client: TestClient) -> None:
    apps = client.get("/api/apps").json()
    assert len(apps) > 50
    sonarr = next(a for a in apps if a["role"] == "sonarr")
    assert sonarr["installed"] is False
    assert sonarr["instances"] == ["sonarr"]
    detail = client.get("/api/apps/saltbox/sonarr").json()
    assert detail["app"]["role"] == "sonarr"
    assert detail["overrides"]["role"] == {}
    assert client.get("/api/apps/saltbox/not-an-app").status_code == 404


def test_overrides_update(client: TestClient, scratch_layout: Layout) -> None:
    body = {
        "values": {
            "sonarr_instances": ["sonarr", "sonarr4k"],
            "sonarr_role_traefik_sso_middleware": "",
        }
    }
    data = client.put("/api/apps/saltbox/sonarr/overrides", json=body).json()
    assert data["overrides"]["role"]["sonarr_role_traefik_sso_middleware"] == ""
    inv = load_plain(scratch_layout.inventory)
    assert inv["sonarr_instances"] == ["sonarr", "sonarr4k"]
    data = client.put(
        "/api/apps/saltbox/sonarr/overrides", json={"unset": ["sonarr_instances", "missing"]}
    ).json()
    assert data["removed"] == ["sonarr_instances"]
    assert "sonarr_instances" not in load_plain(scratch_layout.inventory)


def test_catalog_endpoints(client: TestClient) -> None:
    categories = client.get("/api/catalog/categories").json()
    assert isinstance(categories, dict) and categories
    assert client.get("/api/catalog/tags").json() == {}


def test_state_endpoints(client: TestClient) -> None:
    assert client.get("/api/state/facts").json() == {}
    assert client.get("/api/state/ports").json() == {}
    assert client.get("/api/state/motd").json() == []
    host = client.get("/api/state/host").json()
    assert "disks" in host and "reboot_required" in host


# -- jobs --------------------------------------------------------------------
def test_job_lifecycle(client: TestClient) -> None:
    assert client.get("/api/jobs").json()["jobs"] == []
    started = client.post("/api/jobs", json={"kind": "install", "tags": ["core", "plex"]})
    assert started.status_code == 202
    job = started.json()
    assert job["command_line"].endswith("install core,plex")
    wait_for(lambda: client.get(f"/api/jobs/{job['id']}").json()["status"] == "succeeded")
    log = client.get(f"/api/jobs/{job['id']}/log").json()
    assert "sb args: install core,plex" in log["text"]
    assert (
        client.get(f"/api/jobs/{job['id']}/log", params={"offset": log["offset"]}).json()["text"]
        == ""
    )
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.post("/api/jobs", json={"kind": "install", "tags": []}).status_code == 422
    assert client.post("/api/jobs", json={"kind": "dance"}).status_code == 422


def test_job_rejects_concurrent_runs(scratch_layout: Layout, slow_sb: Path) -> None:
    client = TestClient(create_app(services=Services(scratch_layout)))
    first = client.post("/api/jobs", json={"kind": "update"}).json()
    second = client.post("/api/jobs", json={"kind": "update"})
    assert second.status_code == 409
    assert client.get("/api/jobs").json()["busy"] is True
    wait_for(lambda: client.get(f"/api/jobs/{first['id']}").json()["status"] == "succeeded")
    assert client.get("/api/jobs").json()["busy"] is False


def test_job_stream_and_cancel(
    scratch_layout: Layout, slow_sb: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_SB_LINES", "100")
    client = TestClient(create_app(services=Services(scratch_layout)))
    job = client.post("/api/jobs", json={"kind": "update"}).json()
    with client.websocket_connect(f"/api/jobs/{job['id']}/stream") as ws:
        received = ""
        while "line 3" not in received:
            message = ws.receive_json()
            assert message["type"] == "log"
            received += message["text"]
        assert client.post(f"/api/jobs/{job['id']}/cancel").json()["cancelled"] is True
        final = None
        while final is None:
            message = ws.receive_json()
            if message["type"] == "done":
                final = message["job"]
            else:
                received += message["text"]
    assert final["status"] == "interrupted"
    assert "cancelled" in received
    assert client.post(f"/api/jobs/{job['id']}/cancel").json()["cancelled"] is False


def test_stream_of_finished_job_replays_log(client: TestClient) -> None:
    job = client.post("/api/jobs", json={"kind": "validate"}).json()
    wait_for(lambda: client.get(f"/api/jobs/{job['id']}").json()["status"] == "succeeded")
    with client.websocket_connect(f"/api/jobs/{job['id']}/stream") as ws:
        text = ""
        message = ws.receive_json()
        while message["type"] == "log":
            text += message["text"]
            message = ws.receive_json()
        assert message["type"] == "done"
        assert message["job"]["status"] == "succeeded"
    assert "validate-config" in text


# -- auth and web ---------------------------------------------------------------
def test_bearer_token_required_on_tcp(scratch_layout: Layout, fake_sb: Path) -> None:
    app = create_app(services=Services(scratch_layout, token="s3cret"))
    client = TestClient(app)  # the test client presents a client address, like TCP
    assert client.get("/api/meta").status_code == 401
    assert client.get("/api/meta", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/meta", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert client.get("/").status_code == 200  # the page itself is not behind the token


def test_web_dir_served_with_spa_fallback(scratch_layout: Layout, tmp_path: Path) -> None:
    web = tmp_path / "dist"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<html>app</html>")
    (web / "assets" / "app.js").write_text("console.log(1)")
    client = TestClient(create_app(services=Services(scratch_layout, web_dir=web)))
    assert client.get("/").text == "<html>app</html>"
    assert client.get("/apps/sonarr").text == "<html>app</html>"
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/api/meta").json()["web"] is True


# -- install helpers -------------------------------------------------------------
def test_systemd_unit_and_route(scratch_layout: Layout, tmp_path: Path) -> None:
    unit = systemd_unit("/usr/local/bin/saltbox-uid", web=Path("/srv/git/saltbox/ui/web/dist"))
    assert "ExecStart=/usr/local/bin/saltbox-uid --web /srv/git/saltbox/ui/web/dist" in unit
    assert "StateDirectory=saltbox-ui" in unit

    route = traefik_route(domain="example.com", token="tok", hsts=True)
    assert "Host(`saltbox.example.com`)" in route
    assert "Bearer tok" in route
    assert "hsts@file" in route and "authelia@docker" in route
    assert "- '*.example.com'" in route
    assert "http://172.19.0.1:8701" in route
    load_plain_route = load_plain(_write(tmp_path / "route.yml", route))
    assert load_plain_route["http"]["routers"]["saltbox-ui"]["tls"]["certResolver"] == "cfdns"

    plain = traefik_route(
        domain="example.com", token="tok", wildcard=False, certresolver="httpresolver"
    )
    assert "sans" not in plain
    assert "certResolver: httpresolver" in plain


def test_route_settings_and_write(scratch_layout: Layout, tmp_path: Path) -> None:
    from saltbox_ui.config import ConfigService

    config = ConfigService(scratch_layout)
    with pytest.raises(ValueError, match=r"user\.domain"):
        write_route(scratch_layout, "tok", traefik_dir=tmp_path / "traefik")
    config.ensure_exists("accounts")
    config.ensure_exists("adv_settings")
    config.set("accounts", "user.domain", "example.com")
    config.set("adv_settings", "traefik.cert.http_validation", "yes")
    config.set("adv_settings", "traefik.cert.zerossl", "yes")
    settings = route_settings(config)
    assert settings == {
        "domain": "example.com",
        "certresolver": "zerosslhttp",
        "wildcard": False,
        "hsts": False,
    }
    path = write_route(scratch_layout, "tok", traefik_dir=tmp_path / "traefik")
    assert path.name == "saltbox-ui.yml"
    assert path.stat().st_mode & 0o777 == 0o600
    assert "saltbox.example.com" in path.read_text()


def _write(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


def test_enable_web_writes_everything(scratch_layout: Layout, tmp_path: Path) -> None:
    from saltbox_ui.config import ConfigService
    from saltbox_ui.daemon.install import enable_web

    config = ConfigService(scratch_layout)
    config.ensure_exists("accounts")
    config.set("accounts", "user.domain", "example.com")
    result = enable_web(
        scratch_layout,
        web=Path("/srv/git/saltbox/ui/web/dist"),
        unit_dir=tmp_path / "systemd",
        traefik_dir=tmp_path / "traefik",
        start=False,
    )
    assert result["url"] == "https://saltbox.example.com"
    assert (tmp_path / "systemd" / "saltbox-ui.service").exists()
    token = (scratch_layout.state_dir / "api-token").read_text().strip()
    assert token
    assert f"Bearer {token}" in (tmp_path / "traefik" / "saltbox-ui.yml").read_text()
    assert (
        "--web /srv/git/saltbox/ui/web/dist"
        in (tmp_path / "systemd" / "saltbox-ui.service").read_text()
    )
    assert result["steps"] == {}
