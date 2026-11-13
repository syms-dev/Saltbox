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
from .appsetup.http import Client, SetupError, Transport

FAILED_SMART = 1
FAILED_SCRUTINY = 2
# An attribute's status uses other bits than a drive's:
# 1 failed SMART, 2 warning, 4 failed Scrutiny.
ATTRIBUTE_FAILED_SMART = 1
ATTRIBUTE_FAILED_SCRUTINY = 4


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


def failing_attributes(details: dict[str, Any]) -> list[dict[str, Any]]:
    """The attributes that fail in a drive's latest reading, with Scrutiny's name and reason.

    ``details`` is Scrutiny's answer for one drive: ``data.smart_results`` holds the
    readings (each with ``attrs`` keyed by attribute id) and ``metadata`` describes the
    attributes. A reason reads like "Observed Failure Rate for Critical Attribute is
    greater than 10%" or "Attribute is failing manufacturer SMART threshold".
    """
    readings = [r for r in (details.get("data") or {}).get("smart_results") or [] if r]
    if not readings:
        return []
    latest = max(readings, key=lambda reading: str(reading.get("date") or ""))
    metadata = details.get("metadata") or {}
    found = []
    for key, attribute in (latest.get("attrs") or {}).items():
        status = int(attribute.get("status") or 0)
        if not status & (ATTRIBUTE_FAILED_SMART | ATTRIBUTE_FAILED_SCRUTINY):
            continue
        described = metadata.get(str(key)) or {}
        value = attribute.get("raw_value", attribute.get("value"))
        rate = attribute.get("failure_rate")
        found.append(
            {
                "id": str(key),
                "name": str(described.get("display_name") or f"Attribute {key}"),
                "description": str(described.get("description") or "").strip(),
                "critical": bool(described.get("critical")),
                "value": value if isinstance(value, int | float) else None,
                "reason": str(attribute.get("status_reason") or "").strip(),
                "failure_rate": round(float(rate), 4) if isinstance(rate, int | float) else None,
                "failed_smart": bool(status & ATTRIBUTE_FAILED_SMART),
                "failed_scrutiny": bool(status & ATTRIBUTE_FAILED_SCRUTINY),
            }
        )
    return sorted(found, key=lambda a: (not a["critical"], a["name"]))


def _details(client: Client, device: dict[str, Any]) -> dict[str, Any]:
    """One drive's details. Scrutiny addresses a drive by its own id; older ones by WWN."""
    for key in (device.get("scrutiny_uuid"), device.get("wwn")):
        if not key:
            continue
        try:
            return client.get(f"/api/device/{key}/details") or {}
        except SetupError:
            continue
    return {}


def issue_key(found: dict[str, Any]) -> str:
    """Names what is wrong with a drive, so a dismissal ends when it gets worse."""
    verdicts = (("smart", found["failed_smart"]), ("scrutiny", found["failed_scrutiny"]))
    checks = "+".join(name for name, failed in verdicts if failed)
    attributes = ",".join(sorted(a["id"] for a in found["failing"]))
    return f"drive:{found['id']}:{checks}:{attributes}"


def health(service: Service, transport: Transport | None = None) -> list[dict[str, Any]]:
    """Every drive Scrutiny watches (not the archived ones), failing ones first, then by name.

    A failing drive also carries the attributes that fail and why, from its details.
    """
    client = Client(service.host_url, transport=transport, name=service.name)
    data = client.get("/api/summary") or {}
    summary = (data.get("data") or {}).get("summary") or {}
    drives = []
    for entry in summary.values():
        device = entry.get("device") or {} if isinstance(entry, dict) else {}
        if not device or device.get("archived"):
            continue
        found = drive(entry)
        found["failing"] = [] if found["healthy"] else failing_attributes(_details(client, device))
        found["key"] = None if found["healthy"] else issue_key(found)
        drives.append(found)
    return sorted(drives, key=lambda d: (d["healthy"], d["name"]))
