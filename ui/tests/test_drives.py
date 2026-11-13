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
            "b": entry("sda", status=2, scrutiny_uuid="uuid-sda"),
            "c": entry("nvme0", device_protocol="NVMe", rotational_speed=0, model_name="WD Black"),
            "d": entry("sdz", archived=True, device_status=1),
            # Registered, but the collector has not reported on it yet.
            "e": {"device": {**entry("sdc")["device"], "rotational_speed": 0}},
        }
    },
}
SERVICE = Service("scrutiny", "scrutiny", 8080, True, host="scrutiny")


# What Scrutiny says about the failing drive: two readings, the later one with a critical
# attribute past Scrutiny's threshold, one failing the maker's own, and one only warned about.
DETAILS = {
    "success": True,
    "data": {
        "smart_results": [
            {"date": "2026-11-12T05:00:00Z", "attrs": {"5": {"attribute_id": 5, "status": 0}}},
            {
                "date": "2026-11-13T05:00:00Z",
                "attrs": {
                    "5": {
                        "attribute_id": 5,
                        "raw_value": 24,
                        "status": 4,
                        "status_reason": "Observed Failure Rate for Critical Attribute is "
                        "greater than 10%",
                        "failure_rate": 0.1423,
                    },
                    "199": {
                        "attribute_id": 199,
                        "raw_value": 3,
                        "status": 1,
                        "status_reason": "Attribute is failing manufacturer SMART threshold",
                    },
                    "9": {"attribute_id": 9, "raw_value": 26280, "status": 0},
                    "194": {"attribute_id": 194, "raw_value": 34, "status": 2},
                },
            },
        ]
    },
    "metadata": {
        "5": {
            "display_name": "Reallocated Sectors Count",
            "critical": True,
            "description": "Count of reallocated sectors.",
        },
        "199": {"display_name": "UltraDMA CRC Error Count", "critical": False, "description": ""},
    },
}


def scrutiny(method: str, url: str, headers: dict, body: bytes | None) -> Response:
    assert method == "GET"
    if url == "http://scrutiny:8080/api/summary":
        return Response(200, json.dumps(SUMMARY).encode())
    # Only the failing drive is asked about, by Scrutiny's own id for it.
    assert url == "http://scrutiny:8080/api/device/uuid-sda/details", url
    return Response(200, json.dumps(DETAILS).encode())


def test_drives_are_read_with_failing_ones_first() -> None:
    found = drives.health(SERVICE, scrutiny)
    assert [d["name"] for d in found] == ["/dev/sda", "/dev/nvme0", "/dev/sdb", "/dev/sdc"]
    failing, nvme, disk, unread = found
    assert failing["healthy"] is False
    assert failing["failed_scrutiny"] is True and failing["failed_smart"] is False
    # Which attributes, and why: critical ones first; a warning alone is not a failure.
    assert failing["failing"] == [
        {
            "id": "5",
            "name": "Reallocated Sectors Count",
            "description": "Count of reallocated sectors.",
            "critical": True,
            "value": 24,
            "reason": "Observed Failure Rate for Critical Attribute is greater than 10%",
            "failure_rate": 0.1423,
            "failed_smart": False,
            "failed_scrutiny": True,
        },
        {
            "id": "199",
            "name": "UltraDMA CRC Error Count",
            "description": "",
            "critical": False,
            "value": 3,
            "reason": "Attribute is failing manufacturer SMART threshold",
            "failure_rate": None,
            "failed_smart": True,
            "failed_scrutiny": False,
        },
    ]
    assert failing["key"] == "drive:0x5000c500sda:scrutiny:199,5"
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
        "failing": [],
        "key": None,
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


def test_a_drive_issue_can_be_dismissed_until_it_changes(
    scratch_layout: Layout, fake_sb: Path
) -> None:
    client, _ = client_for(scratch_layout, scrutiny)
    failing = client.get("/api/drives").json()["drives"][0]
    assert failing["dismissed"] is False
    key = failing["key"]
    assert client.post("/api/dismissals", json={"key": ""}).status_code == 422
    assert client.post("/api/dismissals", json={"key": key, "label": "/dev/sda"}).json() == {
        "dismissed": True
    }
    drives_now = client.get("/api/drives").json()["drives"]
    assert drives_now[0]["dismissed"] is True and drives_now[1]["dismissed"] is False
    saved = scratch_layout.state_dir / "dismissed.json"
    assert key in json.loads(saved.read_text()) and saved.stat().st_mode & 0o777 == 0o600
    # Another attribute failing is a different issue: its key no longer matches.
    worse = {**failing, "failing": [*failing["failing"], {"id": "197"}]}
    assert drives.issue_key(worse) != key
    assert client.post("/api/dismissals/restore", json={"key": key}).json() == {"restored": True}
    assert client.get("/api/drives").json()["drives"][0]["dismissed"] is False
    assert client.post("/api/dismissals/restore", json={"key": key}).json() == {"restored": False}


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
