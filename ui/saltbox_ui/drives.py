"""Drive health, read from Scrutiny when it is installed.

Scrutiny collects S.M.A.R.T. data for every drive and judges each one twice:
by the drive's own SMART verdict, and by Scrutiny's thresholds built from
real-world failure rates. ``GET /api/summary`` (what its dashboard uses)
returns one entry per drive with a ``device_status`` bit field: 1 is "failed
SMART", 2 is "failed Scrutiny", 0 is passed.
"""

from __future__ import annotations

from typing import Any

from .appsetup.discover import Service
from .appsetup.http import Client, Transport

FAILED_SMART = 1
FAILED_SCRUTINY = 2


def _kind(device: dict[str, Any]) -> str:
    """HDD, SSD or NVMe, from what the drive reports."""
    if str(device.get("device_protocol", "")).upper() == "NVME":
        return "NVMe"
    speed = device.get("rotational_speed")
    return "HDD" if isinstance(speed, int | float) and speed > 0 else "SSD"


def drive(entry: dict[str, Any]) -> dict[str, Any]:
    device = entry.get("device") or {}
    smart = entry.get("smart") or {}
    status = int(device.get("device_status") or 0)
    name = str(device.get("device_name") or "")
    return {
        "id": str(device.get("wwn") or device.get("scrutiny_uuid") or name),
        "name": f"/dev/{name}" if name and not name.startswith("/") else name,
        "label": str(device.get("label") or device.get("friendly_name") or ""),
        "model": str(device.get("model_name") or ""),
        "serial": str(device.get("serial_number") or ""),
        "kind": _kind(device),
        "capacity": int(device.get("capacity") or 0),
        "failed_smart": bool(status & FAILED_SMART),
        "failed_scrutiny": bool(status & FAILED_SCRUTINY),
        "healthy": status == 0,
        # No reading yet: Scrutiny knows the drive but its collector has not reported.
        "checked_at": str(smart.get("collector_date") or "") or None,
        "temperature": int(smart["temp"]) if smart.get("temp") else None,
        "power_on_hours": int(smart["power_on_hours"]) if smart.get("power_on_hours") else None,
    }


def health(service: Service, transport: Transport | None = None) -> list[dict[str, Any]]:
    """Every drive Scrutiny watches (not the archived ones), failing ones first, then by name."""
    client = Client(service.host_url, transport=transport, name=service.name)
    data = client.get("/api/summary") or {}
    summary = (data.get("data") or {}).get("summary") or {}
    drives = [
        drive(entry)
        for entry in summary.values()
        if isinstance(entry, dict) and not (entry.get("device") or {}).get("archived")
    ]
    return sorted(drives, key=lambda d: (d["healthy"], d["name"]))
