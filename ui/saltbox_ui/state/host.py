"""Host facts: disks, mounts, systemd units, reboot flag."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

SALTBOX_MOUNT_TYPES = {"fuse.rclone", "fuse.mergerfs", "nfs", "nfs4", "cifs"}
DEFAULT_PATHS = ("/", "/opt", "/mnt/local", "/srv")


def disk_usage(paths: tuple[str, ...] = DEFAULT_PATHS) -> list[dict[str, Any]]:
    result = []
    for path in paths:
        if not Path(path).exists():
            continue
        usage = shutil.disk_usage(path)
        result.append(
            {
                "path": path,
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "percent": round(usage.used / usage.total * 100, 1) if usage.total else 0.0,
            }
        )
    return result


def mounts(proc_mounts: str | None = None) -> list[dict[str, str]]:
    """Saltbox-relevant mounts from ``/proc/mounts`` (or the given text)."""
    text = proc_mounts
    if text is None:
        try:
            text = Path("/proc/mounts").read_text(encoding="utf-8")
        except OSError:
            return []
    result = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        source, target, fstype = parts[0], parts[1], parts[2]
        if fstype in SALTBOX_MOUNT_TYPES or target.startswith(("/mnt/remote", "/mnt/unionfs")):
            result.append(
                {"source": source, "target": target.replace("\\040", " "), "type": fstype}
            )
    return result


def systemd_units(pattern: str = "saltbox_managed_*") -> list[dict[str, str]]:
    """``systemctl list-units`` for Saltbox-managed services."""
    if shutil.which("systemctl") is None:
        return []
    result = subprocess.run(
        [
            "systemctl",
            "list-units",
            "--all",
            "--no-legend",
            "--no-pager",
            "--plain",
            "--output=json",
            pattern,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    import json

    try:
        units = json.loads(result.stdout)
    except ValueError:
        return []
    return [
        {
            "unit": u.get("unit", ""),
            "active": u.get("active", ""),
            "sub": u.get("sub", ""),
            "description": u.get("description", ""),
        }
        for u in units
    ]


def reboot_required() -> bool:
    return Path("/var/run/reboot-required").exists()
