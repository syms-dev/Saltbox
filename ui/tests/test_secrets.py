"""Secrets stay on the server: masked in what the daemon sends, restored when saved."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from saltbox_ui.daemon import Services, create_app
from saltbox_ui.daemon import routes as daemon_routes
from saltbox_ui.layout import Layout
from saltbox_ui.secrets import (
    HIDDEN,
    Redactor,
    UnknownPlaceholder,
    is_secret_key,
    mask_text,
    mask_tree,
    placeholder,
    secret_values,
    unmask_text,
)

ACCOUNTS = """---
cloudflare:
  api: abcdef0123456789  # global key
  email: me@example.com
  scoped_token: "tok-123456"
user:
  domain: example.com
  name: seed
  pass: hunter2hunter2
  ssh_key: ssh-ed25519 AAAAC3Nz
"""

INVENTORY = """---
gluetun_role_docker_envs_custom:
  VPN_SERVICE_PROVIDER: protonvpn
  WIREGUARD_PRIVATE_KEY: "kL3n0tR3alKey="
sonarr_role_web_port: 8989
items:
  - token: firsttoken1
  - token: secondtoken2
"""


@pytest.mark.parametrize(
    ("key", "secret"),
    [
        ("pass", True),
        ("api", True),
        ("WIREGUARD_PRIVATE_KEY", True),
        ("scoped_token", True),
        ("plex_role_claim", True),
        ("client_secret", True),
        ("ssh_key", False),
        ("domain", False),
        ("web_port", False),
        ("keyboard", False),
    ],
)
def test_secret_keys(key: str, secret: bool) -> None:
    assert is_secret_key(key) is secret


def test_masked_text_names_each_secret_and_round_trips() -> None:
    masked = mask_text(ACCOUNTS)
    for value in ("abcdef0123456789", "tok-123456", "hunter2hunter2"):
        assert value not in masked
    assert f"api: {placeholder('cloudflare.api')}  # global key" in masked
    assert f"pass: {placeholder('user.pass')}" in masked
    assert "ssh-ed25519 AAAAC3Nz" in masked and "me@example.com" in masked
    assert unmask_text(masked, ACCOUNTS) == ACCOUNTS


def test_nested_and_repeated_keys() -> None:
    masked = mask_text(INVENTORY)
    assert "kL3n0tR3alKey=" not in masked and "firsttoken1" not in masked
    assert placeholder("items.token#2") in masked
    edited = masked.replace("protonvpn", "mullvad")
    restored = unmask_text(edited, INVENTORY)
    assert '"kL3n0tR3alKey="' in restored and "mullvad" in restored and "secondtoken2" in restored


def test_a_typed_value_replaces_the_secret_and_unknown_placeholders_are_refused() -> None:
    masked = mask_text(ACCOUNTS).replace(placeholder("user.pass"), "newpassword99")
    assert "pass: newpassword99" in unmask_text(masked, ACCOUNTS)
    with pytest.raises(UnknownPlaceholder):
        unmask_text(f"x: {placeholder('nowhere')}", ACCOUNTS)


def test_mask_tree_and_redactor() -> None:
    data = {"user": {"pass": "hunter2hunter2", "name": "seed"}, "env": {"VPN_PASSWORD": "pw123456"}}
    assert mask_tree(data) == {
        "user": {"pass": HIDDEN, "name": "seed"},
        "env": {"VPN_PASSWORD": HIDDEN},
    }
    redact = Redactor(secret_values(ACCOUNTS).values())
    assert redact("login with hunter2hunter2 and tok-123456") == f"login with {HIDDEN} and {HIDDEN}"
    assert Redactor(["abc"])("abc") == "abc"  # too short to hide safely


# -- through the daemon ----------------------------------------------------------------
@pytest.fixture
def box(scratch_layout: Layout, fake_sb: Path) -> tuple[TestClient, Layout]:
    scratch_layout.config_file("accounts").write_text(ACCOUNTS)
    scratch_layout.inventory.parent.mkdir(parents=True, exist_ok=True)
    scratch_layout.inventory.write_text(INVENTORY)
    sonarr = scratch_layout.appdata / "sonarr"
    sonarr.mkdir(parents=True)
    (sonarr / "config.xml").write_text(
        "<Config><ApiKey>0123456789abcdef0123456789abcdef</ApiKey></Config>"
    )
    return TestClient(create_app(services=Services(scratch_layout))), scratch_layout


def test_config_files_are_masked_and_saving_keeps_secrets(box) -> None:
    client, layout = box
    shown = client.get("/api/config/accounts").json()
    assert "hunter2hunter2" not in str(shown) and shown["hidden"] == 3
    assert shown["data"]["user"]["pass"] == HIDDEN
    edited = shown["text"].replace("example.com", "example.org")
    assert client.put("/api/config/accounts", json={"text": edited}).status_code == 200
    saved = layout.config_file("accounts").read_text()
    assert "pass: hunter2hunter2" in saved and "domain: example.org" in saved
    revealed = client.get("/api/config/accounts?reveal=true").json()
    assert "hunter2hunter2" in revealed["text"]
    bad = client.put("/api/config/accounts", json={"text": f"x: {placeholder('nope')}\n"})
    assert bad.status_code == 400


def test_inventory_and_overrides_are_masked(box) -> None:
    client, layout = box
    shown = client.get("/api/inventory").json()
    assert "kL3n0tR3alKey=" not in str(shown)
    client.put("/api/inventory", json={"text": shown["text"] + "sonarr_role_x: 1\n"})
    assert "kL3n0tR3alKey=" in layout.inventory.read_text()
    detail = client.get("/api/apps/saltbox/gluetun").json()
    env = detail["overrides"]["role"]["gluetun_role_docker_envs_custom"]
    assert env == {"VPN_SERVICE_PROVIDER": "protonvpn", "WIREGUARD_PRIVATE_KEY": HIDDEN}
    revealed = client.get("/api/apps/saltbox/gluetun?reveal=true").json()
    assert "kL3n0tR3alKey=" in str(revealed["overrides"])


def test_job_logs_and_records_hide_known_secrets(box, monkeypatch) -> None:
    client, _ = box
    job = client.post(
        "/api/jobs", json={"kind": "install", "tags": ["x"], "extra_vars": ["pw=hunter2hunter2"]}
    ).json()
    assert "hunter2hunter2" not in job["command_line"]
    log = client.get(f"/api/jobs/{job['id']}/log").json()
    assert "hunter2hunter2" not in str(log)
    assert HIDDEN in log["job"]["command_line"]
    with client.websocket_connect(f"/api/jobs/{job['id']}/stream") as ws:
        text = ""
        message = ws.receive_json()
        while message["type"] == "log":
            text += message["text"]
            message = ws.receive_json()
    assert "hunter2hunter2" not in text and HIDDEN in text


def test_setup_instructions_and_container_logs_hide_api_keys(box, monkeypatch) -> None:
    client, _layout = box
    key = "0123456789abcdef0123456789abcdef"

    class Task:
        status = "manual"

        def as_dict(self):
            return {
                "app": "Bazarr",
                "detail": f"Sonarr API key {key}",
                "id": "b",
                "status": "manual",
                "title": "Sonarr",
            }

    class Setup:
        def __init__(self, layout):
            pass

        def status(self):
            return [Task()]

    client.app.state.services.app_setup_factory = Setup
    shown = client.get("/api/setup").json()
    assert key not in str(shown) and HIDDEN in shown["tasks"][0]["detail"]
    assert key in str(client.get("/api/setup?reveal=true").json())

    from saltbox_ui.state import containers as containers_module

    monkeypatch.setattr(
        daemon_routes,
        "_containers_or_none",
        lambda: [{"name": "sonarr", "managed": True, "status": "running", "health": None}],
    )
    monkeypatch.setattr(
        containers_module, "_run_merged", lambda args: (0, f"GET /api/v3/series?apikey={key}\n")
    )
    lines = client.get("/api/containers/sonarr/logs").json()["lines"]
    assert lines == [f"GET /api/v3/series?apikey={HIDDEN}"]


def test_an_app_without_a_config_folder_counts_as_installed(box, monkeypatch) -> None:
    client, layout = box
    autoheal = {
        "name": "autoheal",
        "managed": True,
        "status": "running",
        "health": None,
        "urls": [],
    }
    monkeypatch.setattr(daemon_routes, "_containers_or_none", lambda: [dict(autoheal)])
    apps = {a["role"]: a for a in client.get("/api/apps").json()}
    assert apps["autoheal"]["installed"] is True
    assert not (layout.appdata / "autoheal").exists()
