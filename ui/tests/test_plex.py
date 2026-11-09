from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

import pytest

from saltbox_ui.layout import Layout
from saltbox_ui.plex import (
    PlexClient,
    PlexError,
    facts_path,
    new_client_id,
    read_plex_facts,
    write_plex_facts,
)


class FakePlexTv:
    """Records requests and answers from a table keyed by (method, path)."""

    def __init__(self, answers: dict[tuple[str, str], list[tuple[int, object]]]):
        self.answers = answers
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request) -> tuple[int, bytes]:
        self.requests.append(request)
        path = request.full_url.removeprefix("https://plex.tv/api/v2")
        status, body = self.answers[(request.get_method(), path)].pop(0)
        return status, json.dumps(body).encode()


def test_client_id_format() -> None:
    assert re.fullmatch(r"Saltbox[a-z0-9]{8}", new_client_id())


def test_pin_flow() -> None:
    fake = FakePlexTv(
        {
            ("POST", "/pins"): [(201, {"id": 7, "code": "XY9Z"})],
            ("GET", "/pins/7"): [(200, {"authToken": None}), (200, {"authToken": "tok\n"})],
            ("GET", "/user"): [(200, {"username": "seedling"})],
        }
    )
    client = PlexClient("Saltboxabc12345", opener=fake)
    pin = client.create_pin()
    assert (pin.id, pin.code) == (7, "XY9Z")
    assert pin.link_url == "https://plex.tv/link"
    assert "clientID=Saltboxabc12345" in pin.auth_url and "code=XY9Z" in pin.auth_url
    assert client.check_pin(pin) is None
    assert client.check_pin(pin) == "tok"
    assert client.username("tok") == "seedling"

    create = fake.requests[0]
    assert create.data == b"strong=false"
    assert create.get_header("X-plex-client-identifier") == "Saltboxabc12345"
    assert create.get_header("X-plex-product") == "Saltbox"
    assert fake.requests[-1].get_header("X-plex-token") == "tok"


def test_errors() -> None:
    fake = FakePlexTv(
        {
            ("POST", "/pins"): [(500, {})],
            ("GET", "/pins/1"): [(404, {})],
            ("GET", "/user"): [(401, {})],
        }
    )
    client = PlexClient("Saltboxabc12345", opener=fake)
    with pytest.raises(PlexError, match="HTTP 500"):
        client.create_pin()
    from saltbox_ui.plex import Pin

    with pytest.raises(PlexError, match="expired"):
        client.check_pin(Pin(1, "AAAA", client.client_id))
    with pytest.raises(PlexError, match="rejected"):
        client.username("bad")


def test_network_error_is_a_plex_error() -> None:
    def offline(request):
        from saltbox_ui.plex import _urlopen

        return _urlopen(urllib.request.Request("http://127.0.0.1:9/"))

    with pytest.raises(PlexError, match=r"cannot reach plex\.tv"):
        PlexClient(opener=offline).create_pin()


def test_facts_round_trip_keeps_other_keys(scratch_layout: Layout) -> None:
    path = facts_path(scratch_layout)
    path.parent.mkdir(parents=True)
    path.write_text(
        "[plex]\nclient_identifier = old\ntoken = \nCustomKey = keep\n\n[plex4k]\ntoken = x\n"
    )
    written = write_plex_facts(scratch_layout, instance="plex", client_id="Saltboxnew", token="tok")
    assert written == path
    assert path.stat().st_mode & 0o777 == 0o640
    assert read_plex_facts(scratch_layout, "plex") == {
        "client_identifier": "Saltboxnew",
        "token": "tok",
        "CustomKey": "keep",
    }
    assert read_plex_facts(scratch_layout, "plex4k") == {"token": "x"}
    assert read_plex_facts(scratch_layout, "missing") == {}


def test_facts_created_from_scratch(scratch_layout: Layout, tmp_path: Path) -> None:
    write_plex_facts(
        scratch_layout, instance="plex", client_id="c", token="t", owner="no-such-user-xyz"
    )
    assert facts_path(scratch_layout).read_text() == "[plex]\nclient_identifier = c\ntoken = t\n\n"
