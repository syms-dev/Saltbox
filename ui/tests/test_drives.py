"""Drive health from Scrutiny's dashboard summary."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from saltbox_ui import drives
from saltbox_ui.appsetup.discover import Discovery, Service
from saltbox_ui.appsetup.http import Response
from saltbox_ui.daemon import Services, create_app
from saltbox_ui.layout import Layout


def entry(name: str, status: int = 0, **device) -> dict:
    return {
        "device": {
            "wwn": f"0x5000c500{name}",
            "device_name": name,
            "model_name": "ST8000VN004-2M2101",
            "serial_number": "WKD0ABCD",
            "capacity": 8001563222016,
            "rotational_speed": 7200,
            "device_protocol": "ATA",
            "device_status": status,
            "archived": False,
            **device,
        },
        "smart": {
            "collector_date": "2026-11-13T05:00:00Z",
            "temp": 34,
            "power_on_hours": 26280,
        },
    }


SUMMARY = {
    "success": True,
    "data": {
        "summary": {
            "a": entry("sdb"),
            "b": entry("sda", status=2),
            "c": entry("nvme0", device_protocol="NVMe", rotational_speed=0, model_name="WD Black"),
            "d": entry("sdz", archived=True, device_status=1),
            # Registered, but the collector has not reported on it yet.
            "e": {"device": {**entry("sdc")["device"], "rotational_speed": 0}},
        }
    },
}
SERVICE = Service("scrutiny", "scrutiny", 8080, True, host="scrutiny")


def scrutiny(method: str, url: str, headers: dict, body: bytes | None) -> Response:
    assert (method, url) == ("GET", "http://scrutiny:8080/api/summary")
    return Response(200, json.dumps(SUMMARY).encode())


def test_drives_are_read_with_failing_ones_first() -> None:
    found = drives.health(SERVICE, scrutiny)
    assert [d["name"] for d in found] == ["/dev/sda", "/dev/nvme0", "/dev/sdb", "/dev/sdc"]
    failing, nvme, disk, unread = found
    assert failing["healthy"] is False
    assert failing["failed_scrutiny"] is True and failing["failed_smart"] is False
    assert nvme["kind"] == "NVMe" and nvme["model"] == "WD Black" and nvme["healthy"] is True
    assert disk == {
        "id": "0x5000c500sdb",
        "name": "/dev/sdb",
        "label": "",
        "model": "ST8000VN004-2M2101",
        "serial": "WKD0ABCD",
        "kind": "HDD",
        "capacity": 8001563222016,
        "failed_smart": False,
        "failed_scrutiny": False,
        "healthy": True,
        "checked_at": "2026-11-13T05:00:00Z",
        "temperature": 34,
        "power_on_hours": 26280,
    }
    assert unread["kind"] == "SSD" and unread["checked_at"] is None
    assert unread["temperature"] is None and unread["power_on_hours"] is None
    # Both verdicts can fail at once.
    both = drives.drive(entry("sdx", status=3))
    assert both["failed_smart"] and both["failed_scrutiny"] and not both["healthy"]


def client_for(layout: Layout, transport, installed: bool = True) -> tuple[TestClient, list]:
    reads: list[int] = []

    class Setup:
        def __init__(self, layout):
            self.transport = transport

        def discover(self):
            reads.append(1)
            return Discovery(services={"scrutiny": [SERVICE]} if installed else {})

    services = Services(layout)
    services.app_setup_factory = Setup
    return TestClient(create_app(services=services)), reads


def test_drives_route(scratch_layout: Layout, fake_sb: Path) -> None:
    client, reads = client_for(scratch_layout, scrutiny)
    data = client.get("/api/drives").json()
    assert data["installed"] is True and data["error"] == ""
    assert data["drives"][0]["name"] == "/dev/sda"
    client.get("/api/drives")
    assert len(reads) == 1  # kept for five minutes


def test_drives_route_without_scrutiny_or_when_it_is_down(
    scratch_layout: Layout, fake_sb: Path
) -> None:
    client, _ = client_for(scratch_layout, scrutiny, installed=False)
    assert client.get("/api/drives").json() == {"installed": False, "error": "", "drives": []}

    def down(method: str, url: str, headers: dict, body: bytes | None) -> Response:
        return Response(502, b"Bad Gateway")

    client, _ = client_for(scratch_layout, down)
    data = client.get("/api/drives").json()
    assert data["installed"] is True and data["drives"] == []
    assert data["error"] == "scrutiny: Bad Gateway"
