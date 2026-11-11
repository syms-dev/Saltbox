"""Opening the web app over Tailscale: only the server's owner gets in, through its own socket."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

from saltbox_ui.daemon import Services, create_app
from saltbox_ui.daemon import app as daemon_app
from saltbox_ui.daemon.main import bind_sockets, tailscale_socket_for
from saltbox_ui.layout import Layout
from saltbox_ui.state.system import tailscale_serve, tailscale_serve_status


@pytest.fixture
def daemon(scratch_layout: Layout, fake_sb: Path, tmp_path: Path, monkeypatch):
    """The real app under uvicorn on the daemon socket and the Tailscale socket."""
    monkeypatch.setattr(daemon_app.TailscaleOwner, "__call__", lambda self: "owner@example.com")
    run_dir = Path("/tmp") / f"sbx-ts-{tmp_path.name[-12:]}"  # AF_UNIX paths must stay short
    api = str(run_dir / "api.sock")
    tailnet = tailscale_socket_for(api)
    app = create_app(services=Services(scratch_layout, token="tok", tailscale_socket=tailnet))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
    sockets = bind_sockets([], 0, api, (tailnet,))
    thread = threading.Thread(target=server.run, kwargs={"sockets": sockets}, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.02)

    def client(path: str) -> httpx.Client:
        return httpx.Client(transport=httpx.HTTPTransport(uds=path), base_url="http://saltbox")

    yield client(api), client(tailnet)
    server.should_exit = True
    thread.join(5)


def test_only_the_owner_gets_in_over_tailscale(daemon) -> None:
    local, tailnet = daemon
    assert local.get("/api/meta").status_code == 200  # root's own tools, unchanged
    assert tailnet.get("/api/meta").status_code == 401  # no tailnet identity (a tagged device)
    assert (
        tailnet.get("/api/meta", headers={"Tailscale-User-Login": "guest@example.com"}).status_code
        == 403
    )
    owner = {"Tailscale-User-Login": "Owner@Example.com"}
    assert tailnet.get("/api/meta", headers=owner).status_code == 200
    # tailscale serve is a proxy too; its forwarding headers must not trip the SSO check
    forwarded = {**owner, "X-Forwarded-Host": "saltbox.tail1234.ts.net"}
    assert tailnet.get("/api/meta", headers=forwarded).status_code == 200
    # the page itself loads for anyone who can reach it; the data does not
    assert tailnet.get("/").status_code == 200
    # browsers' cross-site protection still applies to the owner
    sibling = {**owner, "Sec-Fetch-Site": "same-site"}
    assert tailnet.post("/api/saltbox/update", headers=sibling).status_code == 403


def test_serve_status_and_toggle() -> None:
    sock = "/run/saltbox-ui/tailscale.sock"
    calls: list[list[str]] = []

    def runner(args: list[str]) -> tuple[int, str]:
        calls.append(args)
        if args[:3] == ["tailscale", "serve", "status"]:
            return 0, json.dumps(
                {
                    "TCP": {"8443": {"HTTPS": True}},
                    "Web": {
                        "saltbox.tail1234.ts.net:8443": {
                            "Handlers": {"/": {"Proxy": f"unix:{sock}"}}
                        }
                    },
                }
            )
        return 0, ""

    assert tailscale_serve_status(sock, runner) == {
        "enabled": True,
        "url": "https://saltbox.tail1234.ts.net:8443/",
    }
    assert tailscale_serve_status("/other.sock", runner) == {"enabled": False}
    assert tailscale_serve(sock, True, runner)[0]
    assert calls[-1] == ["tailscale", "serve", "--bg", "--https=8443", f"unix:{sock}"]
    tailscale_serve(sock, False, runner)
    assert calls[-1] == ["tailscale", "serve", "--https=8443", "off"]
    failed = tailscale_serve_status(sock, lambda args: (1, "serve config denied"))
    assert failed == {"enabled": False, "error": "serve config denied"}


def test_owner_lookup_is_cached() -> None:
    calls = []
    owner = daemon_app.TailscaleOwner(lambda: (calls.append(1), {"owner": "Me@Example.com"})[1])
    assert owner() == "me@example.com" and owner() == "me@example.com"
    assert len(calls) == 1
    assert daemon_app.TailscaleOwner(lambda: {"installed": False})() is None
