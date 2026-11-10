"""Host facts: disks, mounts, systemd units, reboot flag."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

SALTBOX_MOUNT_TYPES = {"fuse.rclone", "fuse.mergerfs", "nfs", "nfs4", "cifs"}
DEFAULT_PATHS = ("/", "/opt", "/mnt/local", "/srv")


def disk_usage(
    paths: tuple[str, ...] = DEFAULT_PATHS, *, mount_root: str | None = "/mnt"
) -> list[dict[str, Any]]:
    """Usage per filesystem for Saltbox's paths and every mountpoint directly under /mnt.

    Paths on the same filesystem (``/``, ``/opt`` and ``/srv`` usually are) are reported
    once, with all their paths, so a pool of drives shows each drive and the pool.
    """
    candidates = list(paths)
    if mount_root is not None and Path(mount_root).is_dir():
        try:
            children = sorted(Path(mount_root).iterdir())
        except OSError:
            children = []
        candidates += [str(c) for c in children if os.path.ismount(c)]
    result: list[dict[str, Any]] = []
    by_device: dict[int, dict[str, Any]] = {}
    for path in candidates:
        try:
            device = os.stat(path).st_dev
            usage = shutil.disk_usage(path)
        except OSError:
            continue
        if device in by_device:
            if path not in by_device[device]["paths"]:
                by_device[device]["paths"].append(path)
            continue
        entry = {
            "path": path,
            "paths": [path],
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent": round(usage.used / usage.total * 100, 1) if usage.total else 0.0,
        }
        by_device[device] = entry
        result.append(entry)
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
